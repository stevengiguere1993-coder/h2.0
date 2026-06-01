"""Ré-extraction manuelle d'une fiche `LeadAnalysis` via Groq
(Llama 3.3 70B). Remplaçant gratuit de la Couche 3 Claude.

Différences vs `re_extract_with_claude` (PR #491 + #508) :
  - Groq Llama 3.3 70B ne supporte PAS le multi-modal natif. Pour
    les PDFs et images, on **OCR-ise** d'abord via les helpers
    Tesseract déjà présents dans `lead_extraction` (`parse_pdf`,
    `parse_pdf_ocr`, `parse_image_ocr`). Le texte OCR-isé est ensuite
    concaténé au reste des sources et envoyé en texte pur.
  - Tier gratuit Groq : 14 400 req/jour, 30 req/minute. Aucune carte
    de crédit requise.
  - Tool calling JSON Schema standard (compatible OpenAI). Si le SDK
    `groq` officiel n'est pas installé, on fallback sur un appel
    HTTP direct via `httpx` (API REST `https://api.groq.com/openai/v1`).

Audit log : `lead_analysis.re_extracted_with_groq`.
``model_used = "llama-3.3-70b (manual, groq)"``.

Patch « doux » identique à Claude :
  - adresse/ville/code postal/province sont TOUJOURS remplacés si
    Groq propose une valeur (champs identifiants — Groq voit souvent
    la version la plus propre).
  - les autres champs sont remplis uniquement s'ils sont vides en
    base (l'utilisateur a pu corriger manuellement, on ne casse pas).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.models.lead_analysis import LeadAnalysis, LeadAnalysisAttachment


log = logging.getLogger(__name__)


# Tool schema aligné 1:1 sur `_RE_EXTRACT_TOOL` de l'endpoint Claude
# (mêmes noms de champs que les colonnes `LeadAnalysis`). On le
# redéfinit ici plutôt que de l'importer pour ne pas créer de
# couplage entre les deux fichiers (Claude peut bouger sans casser
# Groq et inversement).
_GROQ_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "save_lead_fields",
        "description": (
            "Sauvegarde les champs extraits d'une fiche d'analyse d'un "
            "immeuble multi-logements québécois. Ne fournis QUE les "
            "champs explicitement présents dans les sources."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Adresse civique complète."},
                "city": {"type": "string", "description": "Ville."},
                "postal_code": {"type": "string", "description": "Code postal canadien (A1A 1A1)."},
                "province": {"type": "string", "description": "Province (ex. QC)."},
                "asking_price": {"type": "number", "description": "Prix demandé en CAD (sans symbole)."},
                "nb_logements": {"type": "integer", "description": "Nombre total de logements."},
                "typology_json": {"type": "string", "description": "Répartition par typologie au format JSON string, ex. '{\"3.5\": 4, \"4.5\": 2}'. Inclus seulement les types présents."},
                "revenus_bruts": {"type": "number", "description": "Revenus bruts annuels en CAD."},
                "taxes_municipales": {"type": "number", "description": "Taxes municipales annuelles en CAD."},
                "taxes_scolaires": {"type": "number", "description": "Taxes scolaires annuelles en CAD."},
                "assurances": {"type": "number", "description": "Prime d'assurance annuelle en CAD."},
                "energie": {"type": "number", "description": "Coût annuel d'énergie commune en CAD."},
                "depenses_autres": {"type": "number", "description": "Autres dépenses annuelles en CAD."},
                "annee_construction": {"type": "integer", "description": "Année de construction."},
                "superficie_terrain": {"type": "number", "description": "Superficie terrain (pi² ou m², pris tel quel)."},
                "superficie_batiment": {"type": "number", "description": "Superficie bâtiment (pi² ou m², pris tel quel)."},
                "evaluation_municipale": {"type": "number", "description": "Évaluation municipale en CAD."},
                "description": {"type": "string", "description": "Description / commentaire du courtier."},
                "courtier_nom": {"type": "string", "description": "Nom du courtier inscripteur."},
                "courtier_contact": {"type": "string", "description": "Téléphone ou courriel du courtier."},
                "type_batiment": {"type": "string", "description": "Type de bâtiment (ex. 6-plex, immeuble à appartements)."},
                "nb_stationnements": {"type": "integer", "description": "Nombre de stationnements."},
            },
            "required": [],
        },
    },
}


_GROQ_SYSTEM = """\
Tu es un assistant spécialisé dans l'extraction de données immobilières \
québécoises (multi-logements 4+ portes). Tu reçois plusieurs sources \
sur le même immeuble : URLs (texte HTML extrait), texte brut collé, \
et fichiers PDF/image (déjà OCR-isés en texte par le serveur).

Règles :
1. Extrais UNIQUEMENT ce qui est explicitement présent. N'invente pas.
2. Convertis les chiffres en valeurs numériques pures (sans $, sans \
virgules de milliers). Ex: "2 450,75 $" -> 2450.75
3. Pour les % exprimés, divise par 100 si tu retournes un taux (TGA, etc.).
4. Si plusieurs valeurs candidates pour un même champ (ex. 2 années de \
taxes), prends la plus récente.
5. Pour `typology_json`, retourne une chaîne JSON valide, ex. \
'{"3.5": 4, "4.5": 2}'.

Appelle TOUJOURS l'outil `save_lead_fields` avec ce que tu trouves, \
même si tu ne trouves qu'un seul champ.
"""


# Champs qu'on accepte de patcher depuis la ré-extraction Groq
# (mêmes que ceux scalaires côté Claude — alignés sur LeadAnalysis).
_PATCHABLE_FIELDS = {
    "address", "city", "postal_code", "province",
    "asking_price", "nb_logements", "revenus_bruts",
    "taxes_municipales", "taxes_scolaires", "assurances",
    "energie", "depenses_autres", "annee_construction",
    "superficie_terrain", "superficie_batiment",
    "evaluation_municipale", "description",
    "courtier_nom", "courtier_contact", "type_batiment",
    "nb_stationnements", "typology_json",
}

# Champs identifiants — toujours remplacés par la valeur Groq quand
# présente (Groq voit en général une version plus propre que les
# couches 1/2 sur ces champs). Pour le reste, on ne touche pas un
# champ déjà rempli.
_REPLACE_ALWAYS = {"address", "city", "postal_code", "province"}


@dataclass
class ExtractResult:
    """Résultat d'une ré-extraction Groq. Mêmes contrats que la
    version Claude : on retourne la liste des champs effectivement
    patchés (pour le toast + tests), le tag `model_used` à inscrire
    dans la fiche, et un éventuel error string si l'appel a échoué
    pour une raison non-fatale (quota, etc.).

    ``error_reason`` est une clé courte pour l'audit log
    (ex. ``"no_source"``, ``"ocr_unavailable"``, ``"ocr_empty"``,
    ``"groq_api"``, ``"no_extract"``). Le caller (endpoint FastAPI)
    l'enregistre dans ``lead_analysis.re_extract_failed``."""

    fields_patched: List[str] = field(default_factory=list)
    model_used: str = "llama-3.3-70b (manual, groq)"
    error: Optional[str] = None
    error_reason: Optional[str] = None
    extracted: Dict[str, Any] = field(default_factory=dict)


def _ocr_attachment(att: LeadAnalysisAttachment) -> str:
    """Convertit un attachment binaire en texte exploitable par Groq.

    Stratégie :
      - PDF : `parse_pdf` (couche texte native via pypdf) ; si vide ou
        bruité, fallback OCR Tesseract via `parse_pdf_ocr`.
      - Image : OCR Tesseract direct via `parse_image_ocr`.
      - Excel (.xlsx) : `parse_excel` (lecture openpyxl → texte
        structuré).
      - Texte (HTML / TXT) : décode UTF-8 et renvoie tel quel.
      - Autre : chaîne vide (Groq ne saurait rien en faire).

    Ne lève jamais — toute erreur OCR est convertie en chaîne vide
    + log warning. Le caller gère le cas « rien extrait ».
    """
    # Import paresseux : `lead_extraction` est lourd à charger
    # (~100 KB) et `lead_extraction_groq` peut être importé hors
    # du contexte FastAPI (tests).
    from app.services.lead_extraction import (
        parse_pdf,
        parse_pdf_ocr,
        parse_image_ocr,
        parse_excel,
    )

    ct = (att.content_type or "").lower()
    fn = (att.filename or "").lower()
    blob = att.blob or b""
    if not blob:
        return ""

    try:
        if ct == "application/pdf" or fn.endswith(".pdf"):
            text = parse_pdf(blob) or ""
            if len(text.strip()) < 50:
                ocr = parse_pdf_ocr(blob, filename=att.filename or "pdf")
                if ocr.strip():
                    text = ocr
            return text

        if ct.startswith("image/") or fn.endswith(
            (".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp", ".tiff", ".bmp")
        ):
            return parse_image_ocr(blob, filename=att.filename or "image")

        if (
            "excel" in ct
            or "spreadsheetml" in ct
            or fn.endswith((".xlsx", ".xls"))
        ):
            return parse_excel(blob, filename=att.filename or "xlsx")

        if (
            ct.startswith("text/")
            or "html" in ct
            or fn.endswith((".txt", ".html", ".htm", ".md", ".csv"))
        ):
            try:
                return blob.decode("utf-8", errors="replace")
            except Exception:
                return blob.decode("latin-1", errors="replace")
    except Exception as exc:
        log.warning(
            "Groq: OCR/parse de l'attachment %s a échoué : %s",
            att.filename,
            exc,
        )
        return ""

    return ""


async def _call_groq_api(
    user_text: str,
    api_key: str,
    model: str,
) -> Dict[str, Any]:
    """Appel à l'API Groq avec tool calling, via SDK officiel si
    disponible, sinon via httpx direct.

    Retourne le `tool_call.function.arguments` parsé en dict, ou
    `{}` si Groq n'a pas appelé l'outil.

    Lève `httpx.HTTPStatusError` ou équivalent SDK sur erreur API
    (le caller convertit en HTTPException 502).
    """
    messages = [
        {"role": "system", "content": _GROQ_SYSTEM},
        {"role": "user", "content": user_text},
    ]

    try:
        from groq import Groq

        client = Groq(api_key=api_key)

        def _sync_call() -> Any:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                tools=[_GROQ_TOOL_SCHEMA],
                tool_choice={
                    "type": "function",
                    "function": {"name": "save_lead_fields"},
                },
                temperature=0,
                max_tokens=3072,
            )

        resp = await asyncio.to_thread(_sync_call)

        choices = getattr(resp, "choices", None) or []
        if not choices:
            return {}
        msg = choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            name = getattr(fn, "name", None)
            args_str = getattr(fn, "arguments", None) or "{}"
            if name == "save_lead_fields":
                try:
                    parsed = json.loads(args_str)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError as exc:
                    log.warning(
                        "Groq: JSON arguments invalide : %s — brut: %s",
                        exc,
                        args_str[:300],
                    )
                    return {}
        return {}
    except ImportError:
        log.info("Groq SDK absent — fallback HTTP direct via httpx")

    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "tools": [_GROQ_TOOL_SCHEMA],
        "tool_choice": {
            "type": "function",
            "function": {"name": "save_lead_fields"},
        },
        "temperature": 0,
        "max_tokens": 3072,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Groq HTTP {resp.status_code}: {resp.text[:300]}",
                request=resp.request,
                response=resp,
            )
        body = resp.json()

    choices = body.get("choices") or []
    if not choices:
        return {}
    msg = choices[0].get("message") or {}
    tool_calls = msg.get("tool_calls") or []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        if fn.get("name") == "save_lead_fields":
            args_str = fn.get("arguments") or "{}"
            try:
                parsed = json.loads(args_str)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError as exc:
                log.warning(
                    "Groq (HTTP): JSON arguments invalide : %s — "
                    "brut: %s",
                    exc,
                    args_str[:300],
                )
                return {}
    return {}


async def reextract_with_groq(
    analysis: LeadAnalysis,
    attachments: List[LeadAnalysisAttachment],
    force_ocr: bool = True,
) -> ExtractResult:
    """Relance l'extraction sur une `LeadAnalysis` existante en
    utilisant Groq Llama 3.3 70B. Reprend les sources déjà attachées
    (URLs, texte brut, attachments).

    ``force_ocr`` est conservé pour symétrie d'API mais n'a pas
    d'effet : on OCR-ise toujours les PDFs/images car Groq Llama
    ne supporte pas le multi-modal natif (contrairement à Claude
    ou Gemini).

    Retourne un `ExtractResult` — le caller (endpoint FastAPI) gère
    le commit DB + l'audit log.
    """
    api_key = (getattr(settings, "groq_api_key", None) or "").strip()
    if not api_key:
        return ExtractResult(
            error_reason="no_api_key",
            error=(
                "Ré-extraction Groq désactivée : GROQ_API_KEY n'est "
                "pas configurée sur le serveur. Ajoute-la dans les "
                "env vars Render (Dashboard → h2-0 → Environment). "
                "Crée une clé gratuite sur https://console.groq.com."
            ),
        )

    model = (
        getattr(settings, "groq_model", None) or "llama-3.3-70b-versatile"
    ).strip()

    url_lines = [
        u.strip()
        for u in (analysis.source_urls or "").splitlines()
        if u.strip()
    ]
    url_texts: List[str] = []
    if url_lines:
        from app.services.lead_extraction import _fetch_url_text
        for u in url_lines:
            try:
                t = await _fetch_url_text(u)
            except Exception as exc:
                log.warning("Groq: fetch URL %s a échoué : %s", u, exc)
                t = ""
            if t:
                url_texts.append(f"=== URL: {u} ===\n{t}")

    src_text = (analysis.source_text or "").strip()

    attachment_texts: List[str] = []
    for att in attachments:
        txt = _ocr_attachment(att)
        if txt and txt.strip():
            attachment_texts.append(
                f"=== Fichier: {att.filename} ({att.content_type}) ===\n"
                f"{txt[:40_000]}"
            )

    prior_extraction = ""
    if analysis.extracted_json:
        prior_extraction = (
            "=== Extraction des couches précédentes (référence) ===\n"
            + (analysis.extracted_json[:8000])
        )

    parts: List[str] = []
    if url_texts:
        parts.append("\n\n".join(url_texts))
    if src_text:
        parts.append(
            f"=== Texte brut collé par l'utilisateur ===\n{src_text}"
        )
    if attachment_texts:
        parts.append("\n\n".join(attachment_texts))
    if prior_extraction:
        parts.append(prior_extraction)

    if not parts:
        # Trois cas distincts à distinguer pour ne pas afficher le
        # message trompeur « aucune source » alors qu'en réalité Phil
        # a uploadé un screenshot mais Tesseract est mort côté serveur.
        ocr_needed_attachments = [
            a for a in attachments
            if (a.content_type or "").lower().startswith("image/")
            or (a.filename or "").lower().endswith(
                (".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp",
                 ".tiff", ".bmp", ".pdf")
            )
        ]
        has_text_source = bool(url_lines) or bool(src_text)

        # Cas 1 : vraiment aucune source du tout.
        if not attachments and not has_text_source:
            return ExtractResult(
                error_reason="no_source",
                error=(
                    "Aucune source originale exploitable sur cette fiche. "
                    "Recolle des URLs/texte ou ajoute des fichiers d'abord."
                ),
            )

        # Cas 2 : seules sources sont des images/PDFs ET Tesseract est
        # indisponible côté serveur — message orienté admin/diagnostic.
        if ocr_needed_attachments and not has_text_source:
            # Import local pour éviter la circularité au load time.
            from app.services.lead_extraction import _check_tesseract_status
            tess = _check_tesseract_status()
            if not tess.startswith("OK"):
                return ExtractResult(
                    error_reason="ocr_unavailable",
                    error=(
                        "Sources image/PDF présentes mais OCR indisponible "
                        f"côté serveur (Tesseract — état : « {tess} »). "
                        "Contacte un admin pour vérifier le déploiement "
                        "(buildpack apt + Aptfile), OU recolle le texte "
                        "directement dans la fiche."
                    ),
                )
            # Cas 3 : Tesseract est OK mais n'a rien pu extraire (images
            # floues, contraste insuffisant, etc.).
            return ExtractResult(
                error_reason="ocr_empty",
                error=(
                    "OCR n'a rien pu extraire des images/PDFs de cette "
                    "fiche (images floues, mal cadrées ou texte trop "
                    "petit). Essaie d'envoyer une version plus nette, "
                    "ou colle le texte directement."
                ),
            )

        # Fallback (sources texte présentes mais filtrées pour autre
        # raison — ex. URLs toutes en erreur). On retombe sur le
        # message générique.
        return ExtractResult(
            error_reason="no_source",
            error=(
                "Aucune source originale exploitable sur cette fiche. "
                "Recolle des URLs/texte ou ajoute des fichiers d'abord."
            ),
        )

    user_text = (
        "Voici les sources originales de cette fiche. Ré-extrais "
        "tous les champs que tu peux identifier de façon fiable.\n\n"
        + "\n\n".join(parts)
    )

    try:
        extracted = await _call_groq_api(user_text, api_key, model)
    except httpx.HTTPStatusError as exc:
        return ExtractResult(
            error_reason="groq_api",
            error=f"Groq API : {str(exc)[:300]}",
        )
    except Exception as exc:
        log.exception("Groq: appel API échoué")
        return ExtractResult(
            error_reason="groq_api",
            error=f"Erreur ré-extraction Groq : {str(exc)[:200]}",
        )

    if not extracted:
        return ExtractResult(
            error_reason="no_extract",
            error=(
                "Groq n'a pas pu extraire de champs. Réessaie ou "
                "ajoute plus de sources."
            ),
        )

    fields_patched: List[str] = []
    for k, v in (extracted or {}).items():
        if k not in _PATCHABLE_FIELDS:
            continue
        if v in (None, "", "null"):
            continue
        current = getattr(analysis, k, None)
        if k in _REPLACE_ALWAYS or current is None or current == "":
            setattr(analysis, k, v)
            fields_patched.append(k)

    return ExtractResult(
        fields_patched=fields_patched,
        model_used="llama-3.3-70b (manual, groq)",
        extracted=extracted,
    )