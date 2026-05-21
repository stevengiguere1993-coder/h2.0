"""Extraction d'infos immeuble — 100% locale, sans aucun LLM externe.

Cette refonte retire complètement les appels à Gemini (et à Claude
pour ce service précis). Avant : on payait/utilisait un quota Gemini
gratuit qui plafonnait à ~50 req/jour sur le tier free récent (cf.
erreur HTTP 429 vue en prod). Maintenant : tout est traité par des
parsers Python purs, sans rate limit, sans coût, sans dépendance
externe sur le critical path.

Sources supportées :
  - URLs Centris.ca         → parser CSS spécifique (BeautifulSoup)
  - URLs DuProprio.com      → parser CSS spécifique
  - URLs Realtor.ca         → parser CSS spécifique
  - URLs Pmml.ca / Next.js  → bloc __NEXT_DATA__ (JSON applicatif)
  - URLs génériques         → JSON-LD (schema.org) en priorité,
                              sinon regex best-effort sur HTML stripped
  - Texte libre             → regex + heuristiques (prix, logements,
                              adresse, code postal, évaluation,
                              taxes, courtier, typologie québécoise)
  - PDFs texte              → pypdf + regex texte
  - PDFs scannés            → fallback OCR Tesseract (pdf2image →
                              images PIL → pytesseract page par page)
  - Images (PNG/JPG/HEIC/…) → OCR Tesseract (pytesseract sur l'image
                              décodée par Pillow / pillow-heif)

API publique inchangée : `extract_lead_info(urls, text, files)` →
`ExtractionResult(data, model_used, raw_response, warnings)`.
`model_used` vaut désormais ``"local-parser-v1"``.

Autres services du repo qui restent sur leur LLM (hors scope de cette
refonte) : `estimate-expenses` (Claude) et `debug-extract-url`
(garde Gemini pour debug d'extraction). Les paquets
`google-generativeai` et `anthropic` restent donc dans les deps.

Stack OCR (binaires système installés via backend/Aptfile sur Render) :
  - tesseract-ocr + tesseract-ocr-fra  → moteur OCR + pack français
  - poppler-utils                      → pdftoppm pour pdf2image
"""

from __future__ import annotations

import io
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)


MODEL_TAG = "local-parser-v1"


# ── Activation du support HEIC/HEIF (photos iPhone) ───────────────
#
# Depuis iOS 11, les iPhones prennent des photos en .heic par défaut.
# Pillow standard ne sait pas lire ce format — il faut enregistrer un
# opener via pillow-heif. L'import est paresseux pour ne pas planter
# si le paquet est absent en local (dev), mais en prod (Render) il
# est installé via requirements.txt.
try:
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
except ImportError:  # pragma: no cover — env dev sans pillow-heif
    log.info("pillow-heif absent — support HEIC/HEIF désactivé")


# Seuil sous lequel on considère qu'un PDF est "scanné" (couche texte
# vide ou bruitée) et qu'on tombe en fallback OCR. 50 caractères c'est
# moins qu'une ligne d'adresse + prix — n'importe quel PDF descriptif
# réel dépasse largement.
_PDF_OCR_FALLBACK_THRESHOLD = 50


# Normalisations OCR fréquentes. Tesseract confond parfois certains
# caractères sur du texte stylisé. Ces remplacements sont conservateurs
# (ne touchent QUE des contextes ambigus) — on les applique APRÈS l'OCR
# mais AVANT parse_text(), pour donner toutes les chances aux regex.
_OCR_FIXES = [
    # « S 1 234 » → « $ 1 234 » (Tesseract rend souvent $ comme S quand
    # la police est fine). Conditionné à un nombre qui suit.
    (re.compile(r"\bS\s+(\d[\d\s\.,]*)"), r"$ \1"),
    # Caractères pipe verticaux en bordure de tableau → espace.
    (re.compile(r"[|]+"), " "),
    # Ligatures et caractères mal reconnus dans les nombres : « O »
    # entre deux chiffres → « 0 » ; « l » entre deux chiffres → « 1 ».
    (re.compile(r"(\d)\s*[Oo]\s*(\d)"), r"\1 0 \2"),
    (re.compile(r"(\d)\s*[lI]\s*(\d)"), r"\1 1 \2"),
]


def _normalize_ocr_text(text: str) -> str:
    """Applique des corrections best-effort au texte sorti par Tesseract.

    Tesseract peut introduire des confusions sur du texte stylisé
    (chiffres ambigus, dollar mal reconnu). On nettoie avant de passer
    à parse_text() pour donner toutes les chances aux regex. Restera
    toujours du bruit résiduel — c'est attendu, le parser est tolérant.
    """
    if not text:
        return ""
    out = text
    for pattern, repl in _OCR_FIXES:
        out = pattern.sub(repl, out)
    return out


def parse_image_ocr(image_bytes: bytes, filename: str = "image") -> str:
    """OCR sur une image (PNG/JPEG/HEIC/etc.). Retourne le texte extrait.

    Stack : Pillow décode l'image (HEIC géré via pillow-heif registré
    au module load), puis pytesseract appelle le binaire Tesseract en
    français+anglais. Phil reçoit souvent des screenshots de tableaux
    Excel (texte propre, contraste fort) — Tesseract performe très
    bien sur ce type d'input.

    Retourne une chaîne vide si l'OCR échoue (image illisible, binaire
    Tesseract absent, exception inattendue). Le caller émet alors un
    warning explicite.
    """
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError as exc:
        log.warning("OCR désactivé — paquet manquant : %s", exc)
        return ""

    t0 = time.perf_counter()
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Tesseract préfère RGB/L. Pour HEIC, RGBA, palette indexée, on
        # convertit pour éviter "OSError: cannot write mode RGBA as JPEG"
        # ou des résultats dégradés.
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        text = pytesseract.image_to_string(img, lang="fra+eng") or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("OCR image '%s' a échoué : %s", filename, exc)
        return ""
    dt = time.perf_counter() - t0
    log.info(
        "OCR image '%s' : %d chars extraits en %.2fs",
        filename,
        len(text),
        dt,
    )
    return text


def parse_pdf_ocr(pdf_bytes: bytes, filename: str = "pdf") -> str:
    """OCR sur un PDF scanné. Convertit en images puis OCR page par page.

    Utilisé en fallback quand pypdf retourne une chaîne vide ou trop
    courte (PDF purement scanné, sans couche texte). Nécessite le
    binaire `pdftoppm` fourni par poppler-utils (installé via Aptfile
    sur Render).

    DPI 200 est un bon compromis qualité/vitesse pour du texte de
    fiche MLS scannée. Au-delà la précision n'augmente plus mais le
    temps explose (1-5 sec par page à 200 DPI, 10+ sec à 400 DPI).
    """
    try:
        import pytesseract  # type: ignore
        from pdf2image import convert_from_bytes  # type: ignore
    except ImportError as exc:
        log.warning("OCR PDF désactivé — paquet manquant : %s", exc)
        return ""

    t0 = time.perf_counter()
    try:
        images = convert_from_bytes(pdf_bytes, dpi=200)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Conversion PDF→images (poppler) a échoué pour '%s' : %s",
            filename,
            exc,
        )
        return ""

    texts: List[str] = []
    for i, img in enumerate(images, start=1):
        try:
            page_text = pytesseract.image_to_string(img, lang="fra+eng") or ""
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "OCR PDF '%s' page %d a échoué : %s", filename, i, exc
            )
            continue
        if page_text.strip():
            texts.append(page_text)

    full = "\n\n".join(texts)
    dt = time.perf_counter() - t0
    log.info(
        "OCR PDF '%s' : %d pages, %d chars extraits en %.2fs",
        filename,
        len(images),
        len(full),
        dt,
    )
    return full


# ── Compatibilité : exports utilisés par `debug-extract-url` ──────
#
# L'endpoint diagnostic ``/lead-analyses/debug-extract-url`` reste sur
# Gemini pour permettre à l'utilisateur de comparer ce que voit le
# LLM vs ce que voient les parsers locaux. Pour qu'il continue de
# fonctionner sans modifier l'endpoint, on ré-exporte ici les
# symboles attendus. La refonte du pipeline principal n'a aucun lien
# avec le debug — ils coexistent.

import os as _os

EXTRACTION_MODEL = _os.environ.get(
    "LEAD_EXTRACTION_MODEL", "gemini-2.0-flash"
)

SYSTEM_PROMPT = (
    "Tu es un assistant d'extraction de données pour un dirigeant "
    "qui acquiert des immeubles à logements au Québec. Tu reçois des "
    "sources hétérogènes (Centris, DuProprio, PMML, courriel, photo "
    "de fiche MLS, PDF descriptif, capture d'écran, SMS). Convertis "
    "TOUS les nombres en valeur numérique pure. Pour la typologie, "
    "parse en dict { \"4.5\": 4, \"5.5\": 8 }. Adresse civique dans "
    "`address`, ville dans `city`. Si une info n'est pas présente, "
    "retourne null. Réponds UNIQUEMENT avec du JSON strict."
)

SCHEMA_GUIDE = (
    "Schéma JSON attendu (1 objet ou array si plusieurs immeubles) :\n"
    "{ \"address\": str, \"city\": str, \"postal_code\": str, "
    "\"province\": str, \"asking_price\": int, \"nb_logements\": int, "
    "\"typology\": { \"3.5\": int, \"4.5\": int, ... }, "
    "\"revenus_bruts\": int, \"taxes_municipales\": int, "
    "\"taxes_scolaires\": int, \"assurances\": int, \"energie\": int, "
    "\"depenses_autres\": int, \"annee_construction\": int, "
    "\"superficie_terrain\": int, \"superficie_batiment\": int, "
    "\"evaluation_municipale\": int, \"description\": str, "
    "\"courtier_nom\": str, \"courtier_contact\": str, "
    "\"type_batiment\": str, \"nb_stationnements\": int }"
)


async def _fetch_url_text(url: str) -> str:
    """Variante texte du fetch — utilisée par l'endpoint debug pour
    montrer ce que le LLM verrait. Renvoie le HTML stripé + meta tags
    + JSON-LD + __NEXT_DATA__ concaténés (lisible)."""
    html, err = await _fetch_html(url)
    if err:
        return f"[URL non accessible : {err}] {url}"
    parts: List[str] = [f"[Source URL : {url}]"]
    nd = _NEXTDATA_RE.search(html)
    if nd:
        chunk = nd.group(1).strip()
        if len(chunk) > 40_000:
            chunk = chunk[:40_000] + "\n[…tronqué]"
        parts.append(f"[Bloc __NEXT_DATA__]\n{chunk}")
    for i, ld in enumerate(_JSONLD_RE.findall(html)[:5]):
        clean = ld.strip()
        if len(clean) > 8_000:
            clean = clean[:8_000] + "\n[…tronqué]"
        if clean:
            parts.append(f"[JSON-LD #{i + 1}]\n{clean}")
    stripped = _strip_html(html)
    if len(stripped) > 35_000:
        stripped = stripped[:35_000] + "\n[…tronqué]"
    parts.append(f"[Texte de la page]\n{stripped}")
    return "\n\n".join(parts)


# ── Dataclasses publiques ─────────────────────────────────────────


@dataclass
class ExtractionInput:
    """Un input à extraire (compat avec l'ancienne signature)."""

    url: Optional[str] = None
    text: Optional[str] = None
    # (filename, content_type, raw bytes)
    file_data: Optional[Tuple[str, str, bytes]] = None


@dataclass
class ExtractionResult:
    """Résultat d'une extraction. `data` est une liste de dicts (un
    par immeuble distinct détecté — souvent un seul)."""

    data: List[dict] = field(default_factory=list)
    model_used: Optional[str] = None
    raw_response: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


# ── Helpers numériques ────────────────────────────────────────────


_NUM_CLEAN_RE = re.compile(r"[^\d.,kKmM]")


def normalize_number(s: Any) -> Optional[float]:
    """Convertit une valeur potentiellement bruitée en float.

    Robuste aux formats vus en immobilier québécois :
      - "1 200 000"      → 1_200_000.0
      - "1,200,000"      → 1_200_000.0
      - "1.2M" / "1,2 M" → 1_200_000.0
      - "1.5k"           → 1_500.0
      - "3 560 000 $"    → 3_560_000.0
      - "84 000"         → 84_000.0
      - 1250000 (int)    → 1_250_000.0

    Retourne ``None`` si la valeur n'est pas convertible.
    """
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    raw = str(s).strip()
    if not raw:
        return None

    # Détecte un suffixe M / k (multiplicateur).
    multiplier = 1.0
    last = raw[-1]
    if last in "Mm":
        multiplier = 1_000_000.0
        raw = raw[:-1].strip()
    elif last in "Kk":
        multiplier = 1_000.0
        raw = raw[:-1].strip()

    # Vire tout ce qui n'est pas chiffre/virgule/point.
    cleaned = re.sub(r"[^\d.,]", "", raw)
    if not cleaned:
        return None

    # Heuristique séparateur décimal :
    # - Si la chaîne contient à la fois "," et "." : le DERNIER des deux
    #   est le séparateur décimal (les autres sont des milliers).
    # - Si elle contient un seul "," et au plus 2 chiffres après, c'est
    #   décimal (style FR : "1,5").
    # - Sinon les "," et "." sont des séparateurs de milliers.
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    # "." seul : ambigu (peut être milliers FR rares ou décimal EN).
    # On suppose décimal — sauf si 3 chiffres exactement après et pas
    # de M/k (style "1.250" mal formaté → 1250).
    elif "." in cleaned and multiplier == 1.0:
        parts = cleaned.split(".")
        if (
            len(parts) == 2
            and len(parts[1]) == 3
            and len(parts[0]) <= 3
        ):
            # Probable séparateur de milliers européen rare.
            cleaned = cleaned.replace(".", "")

    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def _int_or_none(s: Any) -> Optional[int]:
    """Variante de normalize_number qui force le résultat en int."""
    v = normalize_number(s)
    if v is None:
        return None
    try:
        return int(round(v))
    except (ValueError, OverflowError):
        return None


# ── Parser texte libre (regex + heuristiques) ─────────────────────


_POSTAL_RE = re.compile(r"\b([A-Z]\d[A-Z])\s?(\d[A-Z]\d)\b", re.I)
_PHONE_RE = re.compile(
    r"(?:\+?1[\-.\s]?)?\(?(\d{3})\)?[\-.\s]?(\d{3})[\-.\s]?(\d{4})"
)
_EMAIL_RE = re.compile(r"[\w\.\-+]+@[\w\.\-]+\.[a-z]{2,}", re.I)


def parse_text(text: str) -> Dict[str, Any]:
    """Extrait des champs depuis du texte libre (description courtier,
    SMS, copier-coller, texte de PDF). Best-effort, retourne un dict
    partiel — jamais d'exception non catchée."""
    if not text:
        return {}
    out: Dict[str, Any] = {}

    # Prix demandé. Plusieurs formes : "Prix demandé : 3 560 000 $",
    # "Prix demandé 1,2M$", "1 250 000 $". On préfère la forme
    # qualifiée (avec "demandé") quand elle existe.
    m = re.search(
        r"(?:prix\s+demand[eé]|prix\s+de\s+vente|asking\s+price)[\s:]*\$?\s*"
        r"([\d][\d\s\.,]*[\d])\s*(?:\$|cad)?",
        text,
        flags=re.I,
    )
    if not m:
        m = re.search(
            r"([\d][\d\s\.,]*\d)\s*(?:M|m)\s*\$",  # "1,2 M$"
            text,
        )
        if m:
            v = normalize_number(m.group(1) + "M")
            if v:
                out["asking_price"] = int(round(v))
        else:
            # Fallback générique : un montant > 100 000 $ proche du
            # mot "prix" → asking_price probable.
            m = re.search(
                r"prix[^\d]{0,40}?([\d][\d\s\.,]{4,})\s*\$",
                text,
                flags=re.I,
            )
            if m:
                v = _int_or_none(m.group(1))
                if v and v >= 50_000:
                    out["asking_price"] = v
    else:
        v = normalize_number(m.group(1))
        if v:
            # Cas "1,2 M $" capté dans le 1er regex aussi.
            tail = text[m.end():m.end() + 6].lower()
            if "m" in tail and v < 1000:
                v = v * 1_000_000
            out["asking_price"] = int(round(v))

    # Nombre de logements. "12 logements", "12 unités", "12 portes",
    # "Nombre de logements : 8".
    m = re.search(
        r"nombre\s+d['e]\s*(?:logements|unit[eé]s)[^\d]{0,15}?(\d{1,3})",
        text,
        flags=re.I,
    )
    if m:
        out["nb_logements"] = int(m.group(1))
    else:
        m = re.search(
            r"\b(\d{1,3})\s*(?:logements?|unit[eé]s?|portes?)\b",
            text,
            flags=re.I,
        )
        if m:
            v = int(m.group(1))
            if 1 <= v <= 999:
                out["nb_logements"] = v

    # Typologie québécoise (X.5 ou X ½, caractéristique 1.5, 2.5, 3.5,
    # 4.5, 5.5, 6.5). Pattern : "8 x 5.5", "12 x 4 ½", "8 unités de
    # 5½". On REFUSE les patterns sans ".5" (faux positifs : "2 x 6").
    typology: Dict[str, int] = {}
    typo_re = re.compile(
        r"(\d{1,2})\s*(?:[xX×]|unit[eé]s?\s+de)\s*(\d)\s*(?:[\.,]\s*5|½)",
    )
    for m in typo_re.finditer(text):
        try:
            qty = int(m.group(1))
            base = int(m.group(2))
            key = f"{base}.5"
            # On garde le MAX si le texte cite plusieurs fois la même
            # typologie (description + tableau).
            typology[key] = max(typology.get(key, 0), qty)
        except ValueError:
            pass
    if typology:
        out["typology"] = typology
        # Si nb_logements absent, déduit de la typologie.
        if "nb_logements" not in out:
            out["nb_logements"] = sum(typology.values())

    # Année de construction. "Bâti en 1965", "Année de construction 1908",
    # "construit en 1972".
    m = re.search(
        r"(?:b[aâ]ti(?:e)?(?:\s+en)?|construit(?:e)?(?:\s+en)?|"
        r"ann[eé]e\s+(?:de\s+)?construction)\s*:?\s*(\d{4})",
        text,
        flags=re.I,
    )
    if m:
        y = int(m.group(1))
        if 1700 <= y <= 2100:
            out["annee_construction"] = y

    # Évaluation municipale.
    m = re.search(
        r"[ée]valuation\s+municipale(?:\s+totale)?[^\d$]{0,40}?\$?\s*"
        r"([\d][\d\s\.,]*\d)\s*\$?",
        text,
        flags=re.I,
    )
    if m:
        v = _int_or_none(m.group(1))
        if v and v >= 1_000:
            out["evaluation_municipale"] = v

    # Revenus bruts annuels.
    m = re.search(
        r"revenus?\s*(?:bruts?\s+)?(?:annuels?\s+)?[^\d$]{0,15}?\$?\s*"
        r"([\d][\d\s\.,]*\d)",
        text,
        flags=re.I,
    )
    if m:
        v = _int_or_none(m.group(1))
        if v and v >= 1_000:
            out["revenus_bruts"] = v

    # Taxes municipales.
    m = re.search(
        r"taxes?\s+municipal(?:es?)?[^\d$]{0,15}?\$?\s*"
        r"([\d][\d\s\.,]*\d)",
        text,
        flags=re.I,
    )
    if m:
        v = _int_or_none(m.group(1))
        if v and v >= 100:
            out["taxes_municipales"] = v

    # Taxes scolaires.
    m = re.search(
        r"taxes?\s+scolaires?[^\d$]{0,15}?\$?\s*([\d][\d\s\.,]*\d)",
        text,
        flags=re.I,
    )
    if m:
        v = _int_or_none(m.group(1))
        if v and v >= 50:
            out["taxes_scolaires"] = v

    # Assurances.
    m = re.search(
        r"assurances?[^\d$]{0,15}?\$?\s*([\d][\d\s\.,]*\d)",
        text,
        flags=re.I,
    )
    if m:
        v = _int_or_none(m.group(1))
        if v and v >= 100:
            out["assurances"] = v

    # Énergie / chauffage payé par le propriétaire.
    m = re.search(
        r"(?:[eé]nergie|chauffage|[eé]lectricit[eé]|hydro)[^\d$]{0,15}?\$?\s*"
        r"([\d][\d\s\.,]*\d)",
        text,
        flags=re.I,
    )
    if m:
        v = _int_or_none(m.group(1))
        if v and v >= 100:
            out["energie"] = v

    # Stationnements.
    m = re.search(
        r"(?:nombre\s+de\s+)?stationnements?[^\d]{0,15}?(\d{1,3})",
        text,
        flags=re.I,
    )
    if m:
        v = int(m.group(1))
        if 0 <= v <= 999:
            out["nb_stationnements"] = v

    # Superficie terrain / bâtiment (en pi² souvent).
    m = re.search(
        r"superficie\s+(?:du\s+)?terrain[^\d]{0,15}?"
        r"([\d][\d\s\.,]*\d)\s*(?:pi|pieds|m)?",
        text,
        flags=re.I,
    )
    if m:
        v = _int_or_none(m.group(1))
        if v and v >= 100:
            out["superficie_terrain"] = v
    m = re.search(
        r"superficie\s+(?:du\s+)?b[aâ]timent[^\d]{0,15}?"
        r"([\d][\d\s\.,]*\d)\s*(?:pi|pieds|m)?",
        text,
        flags=re.I,
    )
    if m:
        v = _int_or_none(m.group(1))
        if v and v >= 100:
            out["superficie_batiment"] = v

    # Code postal canadien (format A1A 1A1).
    m = _POSTAL_RE.search(text)
    if m:
        out["postal_code"] = f"{m.group(1).upper()} {m.group(2).upper()}"

    # Adresse civique « 3715-3737 Rue Ethel », « 1234 Boulevard X »,
    # « 5678 Avenue Y ». On accepte un range numérique optionnel.
    m = re.search(
        r"\b(\d{1,5}(?:\s*-\s*\d{1,5})?)\s+"
        r"((?:Rue|Boul(?:evard)?\.?|Av(?:enue)?\.?|Ch(?:emin)?\.?|"
        r"Rte|Route|Place|Pl\.?|Mont[eé]e|Terrasse|Croissant)\s+"
        r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-' \.]{2,50})",
        text,
        flags=re.I,
    )
    if m:
        addr = f"{m.group(1).strip()} {m.group(2).strip()}"
        out["address"] = re.sub(r"\s+", " ", addr).strip()[:200]

    # Ville. Trois heuristiques, dans l'ordre de précision :
    #   a) « Ville : Verdun » / « Municipalité : Verdun »
    #   b) format québécois canonique « <adresse>, <Ville> (QC) <CP> »
    #   c) immédiatement avant un code postal canadien
    m = re.search(
        r"(?:Ville|Municipalit[eé])\s*:?\s*"
        r"([A-ZÀ-Ÿ][A-Za-zÀ-ÿ\-' ]{2,40})",
        text,
    )
    if m:
        out["city"] = m.group(1).strip()
    else:
        m = re.search(
            r",\s*([A-ZÀ-Ÿ][A-Za-zÀ-ÿ\-' ]{2,40}?)\s*"
            r"\(\s*(?:QC|Qu[eé]bec|ON|Ontario)\s*\)",
            text,
        )
        if m:
            out["city"] = m.group(1).strip()

    # Province (presque toujours QC, mais parfois explicite).
    if re.search(r"\bQu[eé]bec\b|\bQC\b", text):
        out["province"] = "QC"

    # Type de bâtiment.
    for kw, label in (
        (r"\btriplex\b", "Triplex"),
        (r"\bduplex\b", "Duplex"),
        (r"\bquadruplex\b", "Quadruplex"),
        (r"\bquintuplex\b", "Quintuplex"),
        (r"\bplex\b", "Plex"),
        (r"\bcondominium\b|\bcondo\b", "Condo"),
        (r"\bmulti(?:logements?|plex)?\b", "Multilogements"),
        (r"\bmixte\b", "Mixte"),
    ):
        if re.search(kw, text, flags=re.I):
            out["type_batiment"] = label
            break

    # Courtier — nom probable (après "Courtier :" / "Agent :"). On
    # accepte les noms en majuscules initiales, 2 à 4 mots. On doit
    # combiner re.I sur le préfixe MAIS rester case-sensitive sur le
    # capture group (sinon le nom est confondu avec le mot-clé). On
    # split donc en deux étapes : trouver le préfixe, puis matcher le
    # nom à partir de là.
    pref = re.search(
        r"\b(?:courtier|agent|repr[eé]sentant)\b\s*:?\s*",
        text,
        flags=re.I,
    )
    if pref:
        tail = text[pref.end():pref.end() + 120]
        nm = re.match(
            r"([A-ZÀ-Ÿ][a-zà-ÿ\-']+(?:\s+[A-ZÀ-Ÿ][a-zà-ÿ\-']+){1,3})",
            tail,
        )
        if nm:
            out["courtier_nom"] = nm.group(1).strip()

    # Courtier — téléphone + email regroupés.
    contact_bits: List[str] = []
    m = _PHONE_RE.search(text)
    if m:
        contact_bits.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    m = _EMAIL_RE.search(text)
    if m:
        contact_bits.append(m.group(0))
    if contact_bits:
        out["courtier_contact"] = " / ".join(contact_bits)

    return out


# ── Parser JSON-LD (schema.org) ───────────────────────────────────


_JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>'
    r'([\s\S]*?)</script>',
    flags=re.I,
)


_SCHEMA_TYPES = {
    "product",
    "realestatelisting",
    "house",
    "apartment",
    "singlefamilyresidence",
    "residence",
    "place",
    "accommodation",
    "offer",
}


def _walk_jsonld(node: Any, found: List[dict]) -> None:
    """Aplatit un graphe JSON-LD pour récupérer tous les sous-objets
    typés (schema.org). Robuste aux @graph, listes imbriquées, etc."""
    if isinstance(node, dict):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t] if t else []
        if any(
            isinstance(x, str) and x.lower() in _SCHEMA_TYPES
            for x in types
        ):
            found.append(node)
        for v in node.values():
            _walk_jsonld(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk_jsonld(v, found)


def parse_jsonld(html: str) -> Dict[str, Any]:
    """Cherche les blocs ``<script type="application/ld+json">`` et en
    extrait les champs immobiliers connus de schema.org."""
    out: Dict[str, Any] = {}
    for raw in _JSONLD_RE.findall(html):
        try:
            parsed = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        found: List[dict] = []
        _walk_jsonld(parsed, found)
        for node in found:
            _merge_jsonld_node(node, out)
    return out


def _merge_jsonld_node(node: dict, out: dict) -> None:
    """Extrait les champs reconnus d'un nœud schema.org et les pose
    dans ``out`` s'ils ne sont pas déjà présents."""

    def _put(key: str, value: Any) -> None:
        if value is None or value == "" or out.get(key) is not None:
            return
        out[key] = value

    # Nom / description
    _put("description", node.get("description") or node.get("name"))

    # Address (peut être string ou objet PostalAddress).
    addr = node.get("address")
    if isinstance(addr, dict):
        street = addr.get("streetAddress")
        city = addr.get("addressLocality")
        postal = addr.get("postalCode")
        prov = addr.get("addressRegion")
        if street:
            _put("address", str(street).strip()[:200])
        if city:
            _put("city", str(city).strip()[:100])
        if postal:
            _put("postal_code", str(postal).strip().upper()[:10])
        if prov:
            _put("province", str(prov).strip().upper()[:5])
    elif isinstance(addr, str):
        _put("address", addr.strip()[:200])

    # Prix : offers.price, offers.priceSpecification.price, price.
    offers = node.get("offers")
    if isinstance(offers, dict):
        price = offers.get("price") or offers.get("lowPrice")
        if price is None:
            ps = offers.get("priceSpecification")
            if isinstance(ps, dict):
                price = ps.get("price")
        v = _int_or_none(price)
        if v:
            _put("asking_price", v)
    elif isinstance(offers, list) and offers:
        v = _int_or_none(offers[0].get("price"))
        if v:
            _put("asking_price", v)
    else:
        v = _int_or_none(node.get("price"))
        if v:
            _put("asking_price", v)

    # Année construction (yearBuilt / dateBuilt).
    y = _int_or_none(node.get("yearBuilt") or node.get("dateBuilt"))
    if y and 1700 <= y <= 2100:
        _put("annee_construction", y)

    # Nb d'unités (numberOfRooms est ambigu — on l'évite ici).
    v = _int_or_none(node.get("numberOfUnits"))
    if v:
        _put("nb_logements", v)

    # Surfaces.
    fs = node.get("floorSize")
    if isinstance(fs, dict):
        v = _int_or_none(fs.get("value"))
        if v:
            _put("superficie_batiment", v)
    elif fs is not None:
        v = _int_or_none(fs)
        if v:
            _put("superficie_batiment", v)

    ls = node.get("lotSize")
    if isinstance(ls, dict):
        v = _int_or_none(ls.get("value"))
        if v:
            _put("superficie_terrain", v)
    elif ls is not None:
        v = _int_or_none(ls)
        if v:
            _put("superficie_terrain", v)


# ── Parser __NEXT_DATA__ (Next.js — pmml.ca, etc.) ────────────────


_NEXTDATA_RE = re.compile(
    r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>([\s\S]*?)</script>',
    flags=re.I,
)


def has_next_data(html: str) -> bool:
    return bool(_NEXTDATA_RE.search(html))


def parse_next_data(html: str) -> Dict[str, Any]:
    """Extrait depuis le bloc ``__NEXT_DATA__`` (Next.js). Les sites
    immobiliers Next.js (pmml.ca par ex.) sérialisent leur état dans
    ``props.pageProps`` — on cherche récursivement les champs connus
    (price, address, units, etc.).

    Bonus : on convertit aussi l'arbre JSON en texte stringifié et on
    le passe à ``parse_text`` — ça capte les champs québécois rares
    (typologie, taxes, évaluation) que le SPA stocke en chaînes
    libres dans le JSON."""
    m = _NEXTDATA_RE.search(html)
    if not m:
        return {}
    try:
        parsed = json.loads(m.group(1).strip())
    except (ValueError, TypeError):
        return {}

    out: Dict[str, Any] = {}
    _walk_next_data(parsed, out)

    # Filet de sécurité : passer le JSON stringifié à parse_text pour
    # rattraper ce qu'on aurait raté. Les valeurs déjà extraites par
    # le walker structurel ne sont pas écrasées.
    try:
        text_blob = json.dumps(parsed, ensure_ascii=False)
        text_out = parse_text(text_blob)
        for k, v in text_out.items():
            out.setdefault(k, v)
    except (TypeError, ValueError):
        pass

    return out


# Clés JSON couramment utilisées par les SPA immobiliers (Next.js
# notamment) → mapping vers nos champs canoniques.
_NEXT_FIELD_MAP: Dict[str, str] = {
    "price": "asking_price",
    "askingprice": "asking_price",
    "listprice": "asking_price",
    "salesprice": "asking_price",
    "prixdemande": "asking_price",
    "address": "address",
    "streetaddress": "address",
    "adresse": "address",
    "city": "city",
    "ville": "city",
    "postalcode": "postal_code",
    "codepostal": "postal_code",
    "province": "province",
    "yearbuilt": "annee_construction",
    "anneeconstruction": "annee_construction",
    "numberofunits": "nb_logements",
    "nbunits": "nb_logements",
    "nblogements": "nb_logements",
    "units": "nb_logements",
    "description": "description",
    "evaluationmunicipale": "evaluation_municipale",
    "revenusbruts": "revenus_bruts",
    "taxesmunicipales": "taxes_municipales",
    "taxesscolaires": "taxes_scolaires",
    "lotsize": "superficie_terrain",
    "floorsize": "superficie_batiment",
    "areaterrain": "superficie_terrain",
    "areabatiment": "superficie_batiment",
}


def _walk_next_data(node: Any, out: dict, _depth: int = 0) -> None:
    """Parcourt récursivement un arbre JSON et pose dans ``out`` les
    valeurs des clés connues."""
    if _depth > 25:  # garde-fou contre les cycles improbables
        return
    if isinstance(node, dict):
        for k, v in node.items():
            key_norm = re.sub(r"[^a-z]", "", str(k).lower())
            mapped = _NEXT_FIELD_MAP.get(key_norm)
            if mapped and mapped not in out:
                if mapped in (
                    "asking_price",
                    "annee_construction",
                    "nb_logements",
                    "evaluation_municipale",
                    "revenus_bruts",
                    "taxes_municipales",
                    "taxes_scolaires",
                    "superficie_terrain",
                    "superficie_batiment",
                ):
                    iv = _int_or_none(v)
                    if iv:
                        out[mapped] = iv
                elif isinstance(v, str) and v.strip():
                    out[mapped] = v.strip()[:500]
            _walk_next_data(v, out, _depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk_next_data(v, out, _depth + 1)


# ── Parsers spécifiques sites ─────────────────────────────────────


def _get_soup(html: str):
    """Crée un BeautifulSoup en gérant l'import paresseusement (le
    paquet est lourd à importer ; sur des URLs sans HTML utile on
    veut éviter le coût)."""
    from bs4 import BeautifulSoup  # type: ignore

    return BeautifulSoup(html, "html.parser")


def _strip_html(html: str) -> str:
    """Strip HTML → texte plat. Utilisé en fallback regex."""
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<!--[\s\S]*?-->", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&#x27;|&#39;", "'", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#?\w+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_centris(html: str) -> Dict[str, Any]:
    """Parser sélecteurs CSS spécifiques à Centris.ca. En cas d'échec
    sur un sélecteur, on retombe gracieusement sur JSON-LD puis sur
    parse_text(HTML stripped)."""
    out: Dict[str, Any] = {}
    try:
        soup = _get_soup(html)
    except Exception:  # noqa: BLE001
        return parse_text(_strip_html(html))

    # Prix : Centris utilise .priceTag, ou un <span itemprop="price">,
    # ou un <meta itemprop="price">.
    for sel in (".priceTag", "[itemprop='price']", "meta[itemprop='price']"):
        node = soup.select_one(sel)
        if node:
            raw = node.get("content") or node.get_text(" ", strip=True)
            v = _int_or_none(raw)
            if v and v >= 10_000:
                out["asking_price"] = v
                break

    # Adresse : .address ou h1
    for sel in (".address", "h1[itemprop='address']", "h1.heading"):
        node = soup.select_one(sel)
        if node:
            txt = node.get_text(" ", strip=True)
            if txt:
                # Souvent Centris cumule "adresse, ville (province)" → on
                # split sur la 1re virgule.
                if "," in txt:
                    parts = [p.strip() for p in txt.split(",", 1)]
                    out["address"] = parts[0][:200]
                    if len(parts) == 2:
                        rest = parts[1]
                        # « Verdun (Montréal) (QC) H4G 1M4 »
                        city_m = re.match(
                            r"([^\(]+)\s*(?:\([^\)]+\))?\s*\(([A-Z]{2})\)?",
                            rest,
                        )
                        if city_m:
                            out["city"] = city_m.group(1).strip()
                            out["province"] = city_m.group(2)
                        pm = _POSTAL_RE.search(rest)
                        if pm:
                            out["postal_code"] = (
                                f"{pm.group(1).upper()} {pm.group(2).upper()}"
                            )
                else:
                    out["address"] = txt[:200]
                break

    # Description (.description, .summary, .text).
    for sel in (".description", ".summary", "[itemprop='description']"):
        node = soup.select_one(sel)
        if node:
            txt = node.get_text(" ", strip=True)
            if txt and len(txt) > 30:
                out["description"] = txt[:2000]
                break

    # Fallback massif sur JSON-LD pour les champs encore manquants.
    ld = parse_jsonld(html)
    for k, v in ld.items():
        out.setdefault(k, v)

    # Fallback regex sur le texte strippé pour ce qui reste (taxes,
    # typologie, année, etc.).
    text_out = parse_text(_strip_html(html))
    for k, v in text_out.items():
        out.setdefault(k, v)

    return out


def parse_duproprio(html: str) -> Dict[str, Any]:
    """Parser DuProprio.com. Approche similaire à Centris : sélecteurs
    courants + fallback JSON-LD + fallback regex texte."""
    out: Dict[str, Any] = {}
    try:
        soup = _get_soup(html)
    except Exception:  # noqa: BLE001
        return parse_text(_strip_html(html))

    # Prix demandé : sur DuProprio, classes possibles : .listing-price,
    # .price__value, [data-qaid="listing-price"].
    for sel in (
        ".listing-price",
        ".price__value",
        "[data-qaid='listing-price']",
        ".sc-price",
        "meta[itemprop='price']",
    ):
        node = soup.select_one(sel)
        if node:
            raw = node.get("content") or node.get_text(" ", strip=True)
            v = _int_or_none(raw)
            if v and v >= 10_000:
                out["asking_price"] = v
                break

    # Adresse.
    for sel in (
        ".listing-location__address",
        "h1.listing-title",
        "[data-qaid='listing-address']",
        "h1",
    ):
        node = soup.select_one(sel)
        if node:
            txt = node.get_text(" ", strip=True)
            if txt:
                out.setdefault("address", txt[:200])
                break

    # Description.
    for sel in (
        ".listing-description",
        "[data-qaid='listing-description']",
        ".sc-description",
    ):
        node = soup.select_one(sel)
        if node:
            txt = node.get_text(" ", strip=True)
            if txt and len(txt) > 30:
                out["description"] = txt[:2000]
                break

    ld = parse_jsonld(html)
    for k, v in ld.items():
        out.setdefault(k, v)
    text_out = parse_text(_strip_html(html))
    for k, v in text_out.items():
        out.setdefault(k, v)
    return out


def parse_realtor(html: str) -> Dict[str, Any]:
    """Parser Realtor.ca. Realtor.ca est très protégé (Cloudflare), le
    fetch HTTP direct retourne souvent du HTML minimal — on tape donc
    JSON-LD si présent, et le reste en regex texte."""
    out: Dict[str, Any] = {}
    try:
        soup = _get_soup(html)
    except Exception:  # noqa: BLE001
        return parse_text(_strip_html(html))

    # Prix : #listingPriceValue, #priceColLeft.
    for sel in (
        "#listingPriceValue",
        "#priceColLeft",
        "[itemprop='price']",
        "meta[itemprop='price']",
    ):
        node = soup.select_one(sel)
        if node:
            raw = node.get("content") or node.get_text(" ", strip=True)
            v = _int_or_none(raw)
            if v and v >= 10_000:
                out["asking_price"] = v
                break

    # Adresse.
    for sel in (
        "#listingAddress",
        "h1[itemprop='address']",
        ".listingAddress",
    ):
        node = soup.select_one(sel)
        if node:
            txt = node.get_text(" ", strip=True)
            if txt:
                out.setdefault("address", txt[:200])
                break

    # Description.
    for sel in (
        "#propertyDescriptionCon",
        "[itemprop='description']",
        ".propertyDescription",
    ):
        node = soup.select_one(sel)
        if node:
            txt = node.get_text(" ", strip=True)
            if txt and len(txt) > 30:
                out["description"] = txt[:2000]
                break

    ld = parse_jsonld(html)
    for k, v in ld.items():
        out.setdefault(k, v)
    text_out = parse_text(_strip_html(html))
    for k, v in text_out.items():
        out.setdefault(k, v)
    return out


# ── Parser PDF (pypdf) ────────────────────────────────────────────


def parse_pdf(blob: bytes) -> str:
    """Extrait le texte brut d'un PDF (toutes pages concaténées).
    Retourne une chaîne vide si le PDF est purement scanné (pas de
    couche texte) — le caller émettra alors un warning."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        log.warning("pypdf non installé — extraction PDF désactivée")
        return ""
    try:
        reader = PdfReader(io.BytesIO(blob))
        chunks: List[str] = []
        for page in reader.pages:
            try:
                t = page.extract_text() or ""
            except Exception:  # noqa: BLE001
                t = ""
            if t.strip():
                chunks.append(t)
        return "\n".join(chunks)
    except Exception as exc:  # noqa: BLE001
        log.warning("pypdf extraction failed: %s", exc)
        return ""


# ── Fusion multi-sources ──────────────────────────────────────────


# Priorité décroissante : parser dédié (Centris/DuProprio/Realtor/Next)
# l'emporte sur JSON-LD générique, qui l'emporte sur regex texte.
# Les sources OCR (image-ocr, pdf-ocr) sont notées un cran plus bas que
# le texte natif — Tesseract introduit du bruit, donc si on a un PDF
# avec couche texte ET une image OCR pour le même immeuble, on garde
# les valeurs natives.
_PARSER_PRIORITY: Dict[str, int] = {
    "centris": 100,
    "duproprio": 100,
    "realtor": 100,
    "next_data": 90,
    "jsonld": 70,
    "text": 50,
    "pdf": 50,
    "image-ocr": 40,
    "pdf-ocr": 40,
}


def merge_extracted(sources: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """Fusionne plusieurs dicts en respectant la priorité du parseur.

    ``sources`` est une liste de ``(parser_tag, dict)``. Pour chaque
    champ, on garde la valeur du parseur le plus prioritaire qui a
    fourni une valeur non-nulle. À priorité égale, premier arrivé.
    La typologie est fusionnée champ par champ (les sources peuvent
    se compléter).
    """
    merged: Dict[str, Any] = {}
    field_origin: Dict[str, int] = {}

    for tag, data in sources:
        if not data:
            continue
        prio = _PARSER_PRIORITY.get(tag, 0)
        for k, v in data.items():
            if v is None or v == "":
                continue
            if k == "typology" and isinstance(v, dict):
                existing = merged.get("typology") or {}
                for tk, tv in v.items():
                    # Pour la typologie : on prend le MAX (le texte cite
                    # la typo plusieurs fois, on veut le compte réel).
                    existing[tk] = max(existing.get(tk, 0), int(tv))
                merged["typology"] = existing
                field_origin[k] = max(field_origin.get(k, 0), prio)
                continue
            if k not in merged or prio > field_origin.get(k, -1):
                merged[k] = v
                field_origin[k] = prio
    return merged


# ── Fetch URL ─────────────────────────────────────────────────────


async def _fetch_html(url: str) -> Tuple[str, Optional[str]]:
    """Télécharge le HTML d'une URL. Retourne (html, error_msg).
    En cas d'échec, html est "" et error_msg explique pourquoi."""
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
                return "", (
                    f"page inaccessible (HTTP {r.status_code}) — "
                    "le site bloque peut-être les fetchs automatisés"
                )
            return r.text, None
    except httpx.TimeoutException:
        return "", "timeout après 20 s"
    except Exception as exc:  # noqa: BLE001
        return "", f"erreur réseau : {exc!s}"


def _parser_for_domain(domain: str) -> str:
    d = domain.lower()
    if "centris.ca" in d:
        return "centris"
    if "duproprio.com" in d:
        return "duproprio"
    if "realtor.ca" in d:
        return "realtor"
    return "generic"


# ── Pipeline principal ────────────────────────────────────────────


async def extract_lead_info(
    *,
    urls: List[str] | None = None,
    text: str | None = None,
    files: List[Tuple[str, str, bytes]] | None = None,
) -> ExtractionResult:
    """Pipeline principal d'extraction 100% local.

    Stratégie :
      1. Pour chaque URL, on détecte le domaine et on dispatche vers
         le parser dédié, en fallback sur __NEXT_DATA__ puis JSON-LD
         puis regex texte.
      2. Le texte libre passe par ``parse_text``.
      3. Les fichiers PDF passent par ``pypdf`` puis ``parse_text``.
         Si la couche texte est vide ou < 50 chars (PDF scanné), on
         tombe en fallback OCR Tesseract (``parse_pdf_ocr``).
      4. Les fichiers image passent par OCR Tesseract direct
         (``parse_image_ocr``) puis ``parse_text`` sur le texte OCR
         normalisé. Couvre les screenshots de tableaux Excel, photos
         de fiches MLS, captures de courriels, photos HEIC iPhone.
      5. On fusionne les résultats selon la priorité parser dédié >
         JSON-LD > texte. Si plusieurs sources ont des adresses
         différentes, on crée plusieurs entrées de sortie.
    """
    warnings: List[str] = []
    # Liste de tuples (parser_tag, addr_key, data_dict).
    extracted: List[Tuple[str, str, Dict[str, Any]]] = []

    # ── URLs ───
    for u in urls or []:
        u = (u or "").strip()
        if not u:
            continue
        html, fetch_err = await _fetch_html(u)
        if fetch_err:
            warnings.append(f"URL {u} : {fetch_err}")
            continue

        domain = urlparse(u).netloc
        parser_kind = _parser_for_domain(domain)
        sources_for_url: List[Tuple[str, Dict[str, Any]]] = []
        try:
            if parser_kind == "centris":
                sources_for_url.append(("centris", parse_centris(html)))
            elif parser_kind == "duproprio":
                sources_for_url.append(("duproprio", parse_duproprio(html)))
            elif parser_kind == "realtor":
                sources_for_url.append(("realtor", parse_realtor(html)))
            else:
                # Site générique : on essaie __NEXT_DATA__ d'abord
                # (couvre pmml.ca et tout autre Next.js), puis JSON-LD,
                # puis regex sur HTML stripped.
                if has_next_data(html):
                    sources_for_url.append(
                        ("next_data", parse_next_data(html))
                    )
                ld = parse_jsonld(html)
                if ld:
                    sources_for_url.append(("jsonld", ld))
                if not sources_for_url:
                    # Ni Next ni JSON-LD : full regex.
                    sources_for_url.append(
                        ("text", parse_text(_strip_html(html)))
                    )
                else:
                    # Toujours compléter avec le texte strippé pour
                    # rattraper taxes, typologie québécoise, etc.
                    sources_for_url.append(
                        ("text", parse_text(_strip_html(html)))
                    )
        except Exception as exc:  # noqa: BLE001
            log.exception("parser failed for %s", u)
            warnings.append(
                f"URL {u} : erreur de parsing ({type(exc).__name__})"
            )
            continue

        # Mini-merge intra-URL.
        url_merged = merge_extracted(sources_for_url)
        if not url_merged:
            warnings.append(
                f"URL {u} : aucun champ extrait — page sans données "
                "structurées reconnaissables (Cloudflare, SPA non "
                "Next.js, ou format inhabituel)"
            )
            continue
        url_merged["source_url"] = u
        addr_key = _addr_key(url_merged)
        extracted.append((f"url:{parser_kind}", addr_key, url_merged))

    # ── Texte libre ───
    if text and text.strip():
        td = parse_text(text)
        if td:
            extracted.append(("text", _addr_key(td), td))
        else:
            warnings.append(
                "Texte libre : aucun champ reconnaissable extrait"
            )

    # ── Fichiers ───
    for filename, content_type, blob in files or []:
        ct = (content_type or "").lower()
        if ct == "application/pdf" or filename.lower().endswith(".pdf"):
            # 1) Couche texte native via pypdf (PDFs descriptifs MLS,
            #    courtiers qui exportent depuis Centris, etc.).
            pdf_text = parse_pdf(blob)
            ocr_used = False
            if (
                not pdf_text.strip()
                or len(pdf_text.strip()) < _PDF_OCR_FALLBACK_THRESHOLD
            ):
                # 2) PDF probablement scanné (pas de couche texte ou
                #    presque rien). Fallback OCR Tesseract page par page.
                log.info(
                    "PDF '%s' : couche texte vide/courte (%d chars), "
                    "fallback OCR Tesseract",
                    filename,
                    len(pdf_text.strip()),
                )
                ocr_text = parse_pdf_ocr(blob, filename=filename)
                if ocr_text.strip():
                    pdf_text = _normalize_ocr_text(ocr_text)
                    ocr_used = True
            if not pdf_text.strip():
                warnings.append(
                    f"PDF « {filename} » : ni texte natif ni OCR "
                    "exploitable (PDF illisible ou binaires Tesseract/"
                    "poppler indisponibles sur le serveur)"
                )
                continue
            td = parse_text(pdf_text)
            if td:
                tag = "pdf-ocr" if ocr_used else "pdf"
                extracted.append((tag, _addr_key(td), td))
            else:
                warnings.append(
                    f"PDF « {filename} » : texte extrait "
                    f"({'OCR' if ocr_used else 'natif'}) mais aucun "
                    "champ reconnaissable"
                )
        elif ct.startswith("image/") or filename.lower().endswith(
            (".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp", ".tiff", ".bmp")
        ):
            # Screenshot de tableau Excel, photo de fiche MLS, capture
            # de courriel, photo HEIC iPhone, etc. → OCR Tesseract.
            ocr_text = parse_image_ocr(blob, filename=filename)
            if not ocr_text.strip():
                warnings.append(
                    f"Image « {filename} » : OCR n'a rien extrait "
                    "(image floue, texte non reconnu, ou binaire "
                    "Tesseract indisponible sur le serveur)"
                )
                continue
            normalized = _normalize_ocr_text(ocr_text)
            td = parse_text(normalized)
            if td:
                extracted.append(("image-ocr", _addr_key(td), td))
            else:
                warnings.append(
                    f"Image « {filename} » : OCR a produit du texte "
                    "mais aucun champ reconnaissable (essayer une "
                    "image plus nette ou recadrer sur le tableau)"
                )
        else:
            warnings.append(
                f"Fichier « {filename} » : type {ct or 'inconnu'} "
                "non supporté"
            )

    if not extracted:
        if not warnings:
            warnings.append("Aucune source fournie.")
        return ExtractionResult(
            data=[],
            model_used=MODEL_TAG,
            warnings=warnings,
        )

    # ── Regroupement par adresse ───
    # Si plusieurs sources désignent le même immeuble (même adresse,
    # ou pas d'adresse), on les fusionne. Si elles désignent des
    # adresses différentes, on crée plusieurs fiches.
    by_addr: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
    for tag, addr_key, data in extracted:
        by_addr.setdefault(addr_key, []).append((tag.split(":")[-1], data))

    data_out: List[Dict[str, Any]] = []
    for addr_key, sources in by_addr.items():
        merged = merge_extracted(sources)
        if merged:
            data_out.append(merged)

    return ExtractionResult(
        data=data_out,
        model_used=MODEL_TAG,
        warnings=warnings,
    )


def _addr_key(d: Dict[str, Any]) -> str:
    """Clé de regroupement par adresse. Si pas d'adresse, on retombe
    sur un singleton « unknown » — toutes les sources sans adresse
    seront fusionnées en une seule fiche (cas standard pour 99% des
    inputs)."""
    addr = (d.get("address") or "").strip().lower()
    if not addr:
        return "unknown"
    # Normalise : retire les espaces multiples, garde alphanumeric.
    return re.sub(r"[^\w]+", "_", addr)[:80]
