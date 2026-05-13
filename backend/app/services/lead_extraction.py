"""Extraction d'infos immeuble depuis sources multiples.

Pipeline unifié :
  1. Pour chaque input (URL, texte, fichier image/PDF) on prépare un
     content block Anthropic.
  2. On envoie tous les blocks à Claude avec un schéma JSON cible.
  3. On parse le JSON retourné et on le mappe sur les colonnes
     `lead_analyses`.

Modèle utilisé : `claude-sonnet-4-6` (vision native, qualité élevée
pour l'extraction structurée). Fallback `claude-haiku-4-5` si besoin
de réduire les coûts.

Sources supportées :
  - URLs : Centris.ca, DuProprio.com, Realtor.ca, ou n'importe quel
    autre site avec contenu HTML public. On fetch via httpx avec un
    User-Agent réaliste ; si bloqué (403/Cloudflare), on envoie
    l'URL telle quelle à Claude qui essaiera de raisonner dessus.
  - Texte : passé tel quel.
  - Image (JPEG/PNG/WebP/HEIC) : envoyée comme content block image.
  - PDF : encodé en base64 et envoyé via le type document Anthropic.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


EXTRACTION_MODEL = os.environ.get(
    "LEAD_EXTRACTION_MODEL", "claude-sonnet-4-6"
)


SYSTEM_PROMPT = """Tu es un assistant d'extraction de données pour \
un dirigeant qui acquiert des immeubles à logements au Québec. \
Tu reçois des sources hétérogènes (lien Centris, DuProprio, PMML, \
courriel courtier, photo de fiche MLS, PDF descriptif, capture \
d'écran, SMS).

Règles d'extraction :
- Convertis TOUS les nombres en VALEUR NUMÉRIQUE PURE (jamais de \
chaîne, jamais de symbole). Exemples :
  - « 3 560 000 $ » → 3560000
  - « 2 676 100 $ » → 2676100
  - « 1 908 » (année) → 1908
- Pour la typologie, parse les expressions du type « 8 x 5.5 + 4 x 4.5 » \
ou « 8 unités de 5 ½ et 4 unités de 4 ½ » en un dict
  `{ "1.5": 0, "2.5": 0, "3.5": 0, "4.5": 4, "5.5": 8, ... }`.
- Adresse civique + rue dans `address` (ex. « 3715-3737 Ethel ») et \
ville dans `city` (ex. « Verdun »).
- Si plusieurs blocs structurés sont fournis (Meta tags, JSON-LD, \
__NEXT_DATA__, En-têtes h1-h3, Texte visible), CROISE-les pour \
trouver la même info plutôt que de te limiter à un seul bloc.
- Si une info n'est pas présente, retourne `null`. Ne devine jamais — \
null vaut mieux qu'une valeur approximative.
- Réponds UNIQUEMENT avec le JSON strict, sans texte avant ni après, \
sans markdown.
- Si tu vois plusieurs immeubles différents dans les sources \
(adresses qui ne matchent pas), retourne un array JSON de plusieurs \
objets. Sinon retourne un seul objet."""


SCHEMA_GUIDE = """Schéma JSON attendu (1 objet, ou array si plusieurs immeubles distincts) :

{
  "address": "123 Rue Example",            // adresse civique + rue
  "city": "Montréal",
  "postal_code": "H1H 1H1",
  "province": "QC",
  "asking_price": 1250000,                 // CAD, prix demandé
  "nb_logements": 6,
  "typology": {                            // répartition par typo
    "1.5": 0,
    "2.5": 0,
    "3.5": 2,
    "4.5": 4,
    "5.5": 0,
    "6.5+": 0,
    "loft": 0
  },
  "revenus_bruts": 84000,                  // CAD/an
  "taxes_municipales": 8500,               // CAD/an
  "taxes_scolaires": 1200,                 // CAD/an
  "assurances": 4500,                      // CAD/an
  "energie": 0,                            // CAD/an si payé par owner
  "depenses_autres": 0,                    // entretien, déneigement…
  "annee_construction": 1965,
  "superficie_terrain": 4500,              // pi² ou m² — précise ?
  "superficie_batiment": 3800,
  "evaluation_municipale": 980000,
  "description": "Triplex bien situé...",  // notes du courtier
  "courtier_nom": "Jane Doe",
  "courtier_contact": "514-555-1234 / jane@centris.ca",
  "type_batiment": "Triplex",              // Plex / Multi / Mixte / etc.
  "nb_stationnements": 3
}"""


@dataclass
class ExtractionInput:
    """Un input à extraire. Un seul type doit être rempli à la fois."""

    url: Optional[str] = None
    text: Optional[str] = None
    # (filename, content_type, raw bytes)
    file_data: Optional[Tuple[str, str, bytes]] = None


@dataclass
class ExtractionResult:
    """Résultat d'une extraction. `data` est un dict (un seul
    immeuble) ou une list de dicts (plusieurs)."""

    data: List[dict] = field(default_factory=list)
    model_used: Optional[str] = None
    raw_response: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


async def _fetch_url_text(url: str) -> str:
    """Récupère le contenu HTML d'une URL et le transforme en texte
    riche pour Claude.

    Pour les sites SPA (Next.js, Nuxt, etc. — beaucoup de courtiers
    modernes : pmml.ca, certaines pages immobilières), le HTML rendu
    côté serveur est souvent vide ; la donnée vit dans des blocs
    `<script id="__NEXT_DATA__">` ou `<script type="application/ld+json">`.
    On les extrait en priorité et on les passe à Claude tels quels
    (en JSON) avant de stripper le HTML.

    Si l'URL est bloquée, on retourne juste l'URL pour que Claude
    raisonne dessus."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.8",
    }
    try:
        async with httpx.AsyncClient(
            timeout=20.0, follow_redirects=True
        ) as client:
            r = await client.get(url, headers=headers)
            if r.status_code >= 400:
                return f"[URL non accessible — code {r.status_code}] {url}"
            html = r.text
    except Exception as exc:  # noqa: BLE001
        log.warning("fetch_url_text failed for %s: %s", url, exc)
        return f"[URL non récupérable : {exc!s}] {url}"

    parts: List[str] = [f"[Source URL : {url}]"]

    # 1. __NEXT_DATA__ (Next.js apps : pmml.ca et beaucoup d'autres).
    nd_match = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>([\s\S]*?)</script>',
        html,
        flags=re.I,
    )
    if nd_match:
        nd_raw = nd_match.group(1).strip()
        if len(nd_raw) > 40_000:
            nd_raw = nd_raw[:40_000] + "\n[…tronqué]"
        parts.append(f"[Bloc __NEXT_DATA__ — JSON Next.js]\n{nd_raw}")

    # 2. JSON-LD (schema.org Property / Apartment / Place).
    ld_matches = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
        html,
        flags=re.I,
    )
    for i, blob in enumerate(ld_matches[:5]):  # max 5 pour limiter le bruit
        clean = blob.strip()
        if not clean:
            continue
        if len(clean) > 8_000:
            clean = clean[:8_000] + "\n[…tronqué]"
        parts.append(f"[JSON-LD #{i + 1}]\n{clean}")

    # 3. Meta OpenGraph + Twitter (titre, description, image, prix).
    meta_tags = re.findall(
        r'<meta\s+(?:property|name)=["\'](og:[^"\']+|twitter:[^"\']+|description)["\']'
        r'\s+content=["\']([^"\']+)["\']',
        html,
        flags=re.I,
    )
    if meta_tags:
        meta_str = "\n".join(f"{k}: {v}" for k, v in meta_tags[:20])
        parts.append(f"[Meta tags]\n{meta_str}")

    # 3b. Titre + headers structurels (h1/h2/h3) — utile sur les sites
    # qui rendent tout en HTML statique (Astro, Hugo, Jekyll, pmml.ca).
    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, flags=re.I)
    if title_m:
        parts.append(f"[Titre page]\n{title_m.group(1).strip()}")
    headers = re.findall(
        r"<h[1-3][^>]*>([\s\S]{1,300}?)</h[1-3]>", html, flags=re.I
    )
    if headers:
        cleaned = []
        for h in headers[:30]:
            h_clean = re.sub(r"<[^>]+>", " ", h)
            h_clean = re.sub(r"\s+", " ", h_clean).strip()
            if h_clean and len(h_clean) < 200:
                cleaned.append(f"- {h_clean}")
        if cleaned:
            parts.append("[En-têtes (h1..h3)]\n" + "\n".join(cleaned))

    # 4. Texte visible — strip standard. Pour pmml.ca, c'est le bloc
    # qui contient la plupart des données (prix, typologie, évaluation
    # municipale, année). On le met en TÊTE de liste pour que Claude
    # le voie en premier — les meta/JSON-LD viennent compléter.
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<!--[\s\S]*?-->", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&#x27;", "'", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#?\w+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 35_000:
        text = text[:35_000] + "\n[…tronqué]"

    # 5. Pré-extraction par regex côté Python — on identifie les
    # patterns canoniques (prix, typologie, évaluation, année,
    # courtier) directement dans le texte strippé et on les injecte
    # en TÊTE du prompt sous forme de pré-données. Donne un coup de
    # pouce à Claude qui peut alors traduire en JSON sans deviner.
    if text:
        pre_extracted = _pre_extract_canonical_fields(text)
        if pre_extracted:
            parts.insert(1, "[Données identifiées par regex]\n" + pre_extracted)
        parts.insert(2, f"[Texte de la page]\n{text}")

    return "\n\n".join(parts)


def _pre_extract_canonical_fields(text: str) -> str:
    """Cherche des patterns canoniques (prix demandé, X logements,
    évaluation municipale, année construction, X x typo) dans le
    texte et retourne un bloc lisible pour Claude. Best-effort —
    on ne fournit que ce qu'on trouve avec une confiance raisonnable."""
    lines: List[str] = []

    # Prix demandé : « Prix demandé : 3 560 000 $ » ou « Prix demandé 3 560 000 $ »
    m = re.search(
        r"Prix demand[eé][^0-9$]{0,30}?([\d\s]{3,15})\s*\$",
        text,
        flags=re.I,
    )
    if m:
        cleaned = re.sub(r"\s", "", m.group(1))
        if cleaned.isdigit():
            lines.append(f"Prix demandé : {int(cleaned)} CAD")

    # Évaluation municipale totale
    m = re.search(
        r"[ÉE]valuation municipale[^0-9$]{0,40}?([\d\s]{3,15})\s*\$",
        text,
        flags=re.I,
    )
    if m:
        cleaned = re.sub(r"\s", "", m.group(1))
        if cleaned.isdigit():
            lines.append(f"Évaluation municipale : {int(cleaned)} CAD")

    # Évaluation terrain
    m = re.search(
        r"[ÉE]valuation municipale du terrain[^0-9$]{0,40}?([\d\s]{3,15})\s*\$",
        text,
        flags=re.I,
    )
    if m:
        cleaned = re.sub(r"\s", "", m.group(1))
        if cleaned.isdigit():
            lines.append(f"Évaluation municipale terrain : {int(cleaned)} CAD")

    # Évaluation bâtiment
    m = re.search(
        r"[ÉE]valuation municipale du b[aâ]timent[^0-9$]{0,40}?([\d\s]{3,15})\s*\$",
        text,
        flags=re.I,
    )
    if m:
        cleaned = re.sub(r"\s", "", m.group(1))
        if cleaned.isdigit():
            lines.append(f"Évaluation municipale bâtiment : {int(cleaned)} CAD")

    # Année de construction
    m = re.search(
        r"Ann[eé]e\s+de\s+construction[^\d]{0,30}?(\d{4})",
        text,
        flags=re.I,
    )
    if m:
        lines.append(f"Année de construction : {m.group(1)}")

    # Nombre de logements / unités
    m = re.search(
        r"(?:Nombre d['e]\s*(?:logements|unit[eé]s)|(?:\b|[^\d])(\d{1,3})\s*(?:logements|Unit[eé]s))",
        text,
        flags=re.I,
    )
    if m:
        # Cas 2 : « 12 Unités »
        if m.group(1):
            lines.append(f"Nombre de logements : {m.group(1)}")
        else:
            # Cas 1 : « Nombre de logements 12 » — refaire le match
            m2 = re.search(
                r"Nombre d['e]\s*(?:logements|unit[eé]s)[^\d]{0,15}?(\d{1,3})",
                text,
                flags=re.I,
            )
            if m2:
                lines.append(f"Nombre de logements : {m2.group(1)}")

    # Typologie : on EXIGE le pattern X.5 ou X ½ (caractéristique
    # des typologies multilogements québécois : 2.5, 3.5, 4.5, 5.5,
    # 6.5). Évite les faux positifs (« 2 x 6 unités », « 1 x 1 dans
    # un numéro de cadastre », etc.).
    typo_matches = re.findall(
        r"(\d{1,2})\s*[xX×]\s*(\d\s*(?:\.\s*5|½))",
        text,
    )
    typo_clean: Dict[str, int] = {}
    for qty, typ in typo_matches:
        # « 5 ½ » → « 5.5 », « 5.5 » → « 5.5 »
        t = typ.strip().replace("½", ".5")
        t = re.sub(r"\s+", "", t)
        try:
            qn = int(qty)
            # On garde le MAX (pas la somme) : le texte cite souvent
            # plusieurs fois la même typologie (description + tableau).
            typo_clean[t] = max(typo_clean.get(t, 0), qn)
        except ValueError:
            pass
    if typo_clean:
        lines.append(
            "Typologie identifiée : "
            + " + ".join(f"{q}×{t}" for t, q in typo_clean.items())
        )

    # Nombre de stationnements
    m = re.search(
        r"Nombre\s+de\s+stationnements[^\d]{0,15}?(\d{1,3})",
        text,
        flags=re.I,
    )
    if m:
        lines.append(f"Nombre de stationnements : {m.group(1)}")

    # Adresse : best-effort sur les patterns « 3715-3737 Rue X » ou
    # « X-Y Rue Name » courants dans le titre/h1.
    m = re.search(
        r"(\d{1,5}\s*-\s*\d{1,5}\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\.\-' ]{2,50})",
        text,
    )
    if m:
        addr = m.group(1).strip()
        if len(addr) < 100:
            lines.append(f"Adresse possible : {addr}")

    return "\n".join(lines)


def _build_content_blocks(
    inputs: List[ExtractionInput],
) -> Tuple[List[dict], List[str]]:
    """Convertit la liste d'inputs en content blocks Anthropic.
    Retourne aussi la liste des warnings (sources sautées)."""
    blocks: List[dict] = []
    warnings: List[str] = []

    for inp in inputs:
        if inp.text and inp.text.strip():
            blocks.append({"type": "text", "text": inp.text.strip()})
        if inp.file_data:
            filename, content_type, data = inp.file_data
            ct = (content_type or "").lower()
            if ct.startswith("image/"):
                # Anthropic vision accepte image/jpeg, image/png,
                # image/webp, image/gif. On force vers ces 4.
                supported = {
                    "image/jpeg",
                    "image/jpg",
                    "image/png",
                    "image/webp",
                    "image/gif",
                }
                if ct == "image/jpg":
                    ct = "image/jpeg"
                if ct not in supported:
                    warnings.append(
                        f"Format image non supporté pour {filename} : {ct}"
                    )
                    continue
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": ct,
                            "data": base64.b64encode(data).decode("ascii"),
                        },
                    }
                )
            elif ct == "application/pdf":
                blocks.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.b64encode(data).decode("ascii"),
                        },
                    }
                )
            else:
                warnings.append(
                    f"Type de fichier non supporté pour {filename} : {ct}"
                )
    return blocks, warnings


async def extract_lead_info(
    *,
    urls: List[str] | None = None,
    text: str | None = None,
    files: List[Tuple[str, str, bytes]] | None = None,
) -> ExtractionResult:
    """Pipeline principal d'extraction. Retourne le résultat structuré."""
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY non configuré — extraction impossible."
        )

    inputs: List[ExtractionInput] = []
    # Texte d'entrée brut.
    if text and text.strip():
        inputs.append(ExtractionInput(text=text))

    # URLs : on fetch et on injecte le texte récupéré.
    for u in urls or []:
        u = u.strip()
        if not u:
            continue
        fetched = await _fetch_url_text(u)
        inputs.append(ExtractionInput(text=fetched))

    # Fichiers : on les passe tels quels.
    for filename, content_type, data in files or []:
        inputs.append(
            ExtractionInput(file_data=(filename, content_type, data))
        )

    if not inputs:
        return ExtractionResult(
            data=[],
            warnings=["Aucune source fournie."],
        )

    content_blocks, warns = _build_content_blocks(inputs)
    # Ajoute toujours la consigne JSON en fin pour bien cadrer la sortie.
    content_blocks.append(
        {
            "type": "text",
            "text": (
                "Extrais maintenant les infos selon le schéma ci-dessous.\n\n"
                + SCHEMA_GUIDE
            ),
        }
    )

    import anthropic  # import paresseux

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        msg = client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content_blocks}],
        )
    except anthropic.APIError as exc:
        log.exception("Claude extraction failed")
        raise RuntimeError(f"Claude API error: {exc!s}") from exc

    raw = "\n".join(b.text for b in msg.content if b.type == "text").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)

    parsed: Any
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("Claude returned non-JSON: %s", raw[:300])
        warns.append(f"Réponse Claude non-JSON : {exc!s}")
        return ExtractionResult(
            data=[],
            model_used=EXTRACTION_MODEL,
            raw_response=raw,
            warnings=warns,
        )

    if isinstance(parsed, dict):
        data = [parsed]
    elif isinstance(parsed, list):
        data = [x for x in parsed if isinstance(x, dict)]
    else:
        warns.append("Format JSON inattendu (ni dict ni list).")
        data = []

    return ExtractionResult(
        data=data,
        model_used=EXTRACTION_MODEL,
        raw_response=raw,
        warnings=warns,
    )
