"""Rent roll → unités de la fiche d'analyse (Phil 2026-10-07).

« Dans la section Unités & optimisation, je peux mettre un PDF ou une
photo et ça vient l'analyser de la même façon que dans la section Infos
et remplir le rent roll par unité au lieu de la moyenne. »

Même lecture que la section Infos (``lead_extraction``) : couche texte
des PDF, OCR si le serveur en a un, image/PDF scanné transmis tels quels
à l'IA (Gemini, cascade à chaud ; relais Groq), parser local (regex) en
filet. Le résultat est une PROPOSITION : le tableau de la fiche n'est
remplacé que quand l'utilisateur l'applique.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.services import lead_extraction as _ex

log = logging.getLogger(__name__)


SYSTEM_PROMPT_RENT_ROLL = (
    "Tu extrais le RENT ROLL (la liste des logements avec leur loyer "
    "mensuel ACTUEL) d'un immeuble à logements au Québec, à partir de "
    "documents hétérogènes : PDF de courtier, photo ou capture d'écran "
    "d'un tableau, courriel, texte collé. Une entrée par logement. "
    "Convertis un loyer annuel en mensuel (divise par 12). Ignore les "
    "lignes de total, de moyenne et les revenus de stationnement ou de "
    "buanderie. Typologie au format québécois X.5 (1.5, 2.5, 3.5, 4.5, "
    "5.5, 6.5) ; un studio = 1.5. Si le document n'est pas un rent roll, "
    "retourne une liste vide. Réponds UNIQUEMENT avec du JSON strict."
)

SCHEMA_RENT_ROLL = (
    "Schéma JSON attendu : { \"unites\": [ { \"numero\": str|null "
    "(numéro ou étiquette du logement, ex. « 101 », « App. 3 »), "
    "\"typo\": str|null (format X.5), \"loyer_actuel\": number (loyer "
    "mensuel en $), \"loyer_optimise\": number|null (loyer visé ou de "
    "marché seulement si le document l'indique explicitement), "
    "\"notes\": str|null (vacant, chauffé, stationnement inclus…) } ] }"
)

#: Plage d'un loyer mensuel plausible au Québec (hors commercial).
LOYER_MENSUEL_MIN = 250.0
LOYER_MENSUEL_MAX = 6000.0

_TYPO_RE = re.compile(r"(?<!\d)([1-9])\s*(?:[.,]\s*5|½|1\s*/\s*2)(?![\d/])")
_STUDIO_RE = re.compile(r"\bstudio\b", re.I)
# Montant : « 950 », « 1 250 », « 1,250 », « 1250.00 » — jamais suivi
# d'un tiret ou d'une barre (dates 2025-07-01) ni d'un autre chiffre.
_MONTANT_RE = re.compile(
    r"(?<![\d,.])(\d{1,2}[  ,]\d{3}|\d{3,5})(?:[.,](\d{2}))?(\s*\$)?(?![\d\-/])"
)
_NUMERO_RE = re.compile(
    r"^\s*(?:app(?:t|artement)?\.?|unit[eé]?|logement|log\.?|no\.?|n°|#)?"
    r"\s*([0-9]{1,4}[A-Za-z]?)\b(?![.,]?\d*\s*\$)",
    re.I,
)
_TOTAL_RE = re.compile(r"\b(total|sous-total|moyenne|somme|revenus?)\b", re.I)
# Préfixe EXPLICITE de logement (« App. 3 », « Unité 2B », « #12 ») — sans
# « $ » sur la ligne, c'est lui ou la typologie qui distingue un loyer
# d'un numéro civique (« 1234 rue Test ») ou d'une année.
_PREFIXE_UNITE_RE = re.compile(
    r"^\s*(?:app(?:t|artement)?\.?|unit[eé]?|logement|log\.?|no\.?|n°|#)\s*[0-9]", re.I
)


def normaliser_typo(val: Any) -> Optional[str]:
    """« 4 1/2 », « 4½ », « 4,5 », « 4.5 », « Studio » → « 4.5 » / « 1.5 » ;
    texte inconnu → nettoyé (16 car. max) ; vide → None."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("null", "none"):
        return None
    m = _TYPO_RE.search(s)
    if m:
        return f"{m.group(1)}.5"
    if _STUDIO_RE.search(s):
        return "1.5"
    return s[:16]


def _montant_mensuel(ligne: str) -> Optional[float]:
    """Premier montant plausible d'un loyer mensuel sur la ligne (les
    montants suivis de « $ » d'abord) ; un montant annuel (> 6 000 $)
    est ramené au mois."""
    avec_dollar: List[float] = []
    sans_dollar: List[float] = []
    for m in _MONTANT_RE.finditer(ligne):
        brut = m.group(1).replace(" ", "").replace(" ", "").replace(",", "")
        try:
            v = float(brut + ("." + m.group(2) if m.group(2) else ""))
        except ValueError:
            continue
        (avec_dollar if m.group(3) else sans_dollar).append(v)
    for candidats in (avec_dollar, sans_dollar):
        for v in candidats:
            if LOYER_MENSUEL_MIN <= v <= LOYER_MENSUEL_MAX:
                return v
        for v in candidats:
            if LOYER_MENSUEL_MAX < v <= LOYER_MENSUEL_MAX * 12:
                return round(v / 12.0, 2)
    return None


def parse_rent_roll_text(texte: str) -> List[Dict[str, Any]]:
    """Parser local (regex) : une unité par ligne portant un loyer
    plausible ; numéro et typologie quand ils sont lisibles. Moins de
    deux unités → ce n'est pas un rent roll (liste vide)."""
    out: List[Dict[str, Any]] = []
    for ligne in (texte or "").splitlines():
        l = ligne.strip()
        if not l or _TOTAL_RE.search(l):
            continue
        a_typo = bool(_TYPO_RE.search(l) or _STUDIO_RE.search(l))
        # Sans « $ », il faut une typologie ou un préfixe d'unité : sinon
        # « 1234 rue Test » ou « Bail 2025 » passeraient pour des loyers.
        if "$" not in l and not a_typo and not _PREFIXE_UNITE_RE.match(l):
            continue
        loyer = _montant_mensuel(l)
        if loyer is None:
            continue
        typo = normaliser_typo(l) if a_typo else None
        numero = None
        mn = _NUMERO_RE.match(l)
        if mn:
            numero = mn.group(1)
        out.append(
            {
                "numero": numero,
                "typo": typo,
                "loyer_actuel": loyer,
                "loyer_optimise": None,
                "notes": None,
            }
        )
    return out if len(out) >= 2 else []


def normaliser_unites_extraites(obj: Any) -> List[Dict[str, Any]]:
    """Sortie IA → liste propre d'unités. Accepte une liste d'unités,
    ``{"unites": [...]}`` ou ``[{"unites": [...]}]`` (enveloppe Gemini)."""
    items: Any = obj
    if (
        isinstance(items, list)
        and len(items) == 1
        and isinstance(items[0], dict)
        and isinstance(items[0].get("unites"), list)
    ):
        items = items[0]["unites"]
    elif isinstance(items, dict):
        items = items.get("unites") if isinstance(items.get("unites"), list) else [items]
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        loyer = _ex.normalize_number(it.get("loyer_actuel"))
        if loyer is None or loyer <= 0:
            continue
        if loyer > LOYER_MENSUEL_MAX:
            loyer = round(loyer / 12.0, 2)
        opt = _ex.normalize_number(it.get("loyer_optimise"))
        if opt is not None and opt > LOYER_MENSUEL_MAX:
            opt = round(opt / 12.0, 2)
        numero = it.get("numero")
        numero_s = str(numero).strip()[:32] if numero not in (None, "", "null") else None
        notes = it.get("notes")
        notes_s = str(notes).strip()[:120] if notes not in (None, "", "null") else None
        out.append(
            {
                "numero": numero_s or None,
                "typo": normaliser_typo(it.get("typo")),
                "loyer_actuel": round(float(loyer), 2),
                "loyer_optimise": round(float(opt), 2) if opt and opt > 0 else None,
                "notes": notes_s or None,
            }
        )
    return out


@dataclass
class RentRollResult:
    unites: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    model_used: str = "none"
    #: « ia » | « local » | « none »
    source: str = "none"


async def extraire_rent_roll(
    *,
    files: Optional[List[Tuple[str, str, bytes]]] = None,
    text: Optional[str] = None,
) -> RentRollResult:
    """Lit un rent roll (PDF, images, Excel, texte collé) : IA d'abord
    (Gemini → relais Groq), parser local en filet."""
    warnings: List[str] = []
    ocr_warnings: List[str] = []
    material_parts: List[str] = []
    images: List[Tuple[str, bytes]] = []
    textes_locaux: List[str] = []

    if text and text.strip():
        material_parts.append(f"[Texte fourni]\n{text.strip()}")
        textes_locaux.append(text)

    for filename, content_type, blob in files or []:
        ct = (content_type or "").lower()
        bas = (filename or "").lower()
        if ct == "application/pdf" or bas.endswith(".pdf"):
            pdf_text = _ex.parse_pdf(blob)
            if len(pdf_text.strip()) < _ex._PDF_OCR_FALLBACK_THRESHOLD:
                ocr = _ex.parse_pdf_ocr(blob, filename=filename)
                if ocr.strip():
                    pdf_text = _ex._normalize_ocr_text(ocr)
            if pdf_text.strip():
                material_parts.append(f"[PDF : {filename}]\n{pdf_text[:40_000]}")
                textes_locaux.append(pdf_text)
            else:
                images.append(("application/pdf", blob))
                ocr_warnings.append(
                    f"PDF « {filename} » : aucune couche texte (document "
                    "scanné) et OCR serveur indisponible — transmis tel "
                    "quel à l'IA."
                )
        elif ct.startswith("image/") or bas.endswith(
            (".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp", ".tiff", ".bmp")
        ):
            images.append(_ex.preparer_image_pour_ia(ct or "image/png", blob))
            ocr = _ex.parse_image_ocr(blob, filename=filename)
            if ocr.strip():
                textes_locaux.append(_ex._normalize_ocr_text(ocr))
            else:
                ocr_warnings.append(
                    f"Image « {filename} » : OCR serveur muet — lecture "
                    "confiée à l'IA."
                )
        elif "excel" in ct or "spreadsheetml" in ct or bas.endswith((".xlsx", ".xls")):
            xl = _ex.parse_excel(blob, filename=filename)
            if xl.strip():
                material_parts.append(f"[Excel : {filename}]\n{xl[:60_000]}")
                textes_locaux.append(xl)
            else:
                warnings.append(f"Excel « {filename} » : contenu illisible.")
        else:
            warnings.append(
                f"Fichier « {filename} » : type {ct or 'inconnu'} non supporté"
            )

    local: List[Dict[str, Any]] = []
    for t in textes_locaux:
        local.extend(parse_rent_roll_text(t))

    material = "\n\n".join(p for p in material_parts if p.strip())
    ia: Optional[List[Dict[str, Any]]] = None
    model_used = "none"
    if material.strip() or images:
        data, gemini_err, gmodel = await _ex._run_gemini_safely(
            material, images, system=SYSTEM_PROMPT_RENT_ROLL, guide=SCHEMA_RENT_ROLL
        )
        if data is not None:
            ia = normaliser_unites_extraites(data)
            model_used = gmodel or "gemini"
        else:
            gdata, gerr, gm = await _ex._run_groq_safely(
                material, images, system=SYSTEM_PROMPT_RENT_ROLL, guide=SCHEMA_RENT_ROLL
            )
            if gdata is not None:
                ia = normaliser_unites_extraites(gdata)
                model_used = f"groq ({gm})"
                warnings.append(
                    f"Gemini indisponible ({gemini_err or 'aucune réponse'}) "
                    f"— relais pris par Groq ({gm})."
                )
            else:
                warnings.append(
                    f"IA indisponible — Gemini : {gemini_err or 'aucune réponse'} ; "
                    f"Groq : {gerr or 'aucune réponse'}."
                )

    if ia:
        log.info("Rent roll : %d unité(s) lues par %s", len(ia), model_used)
        return RentRollResult(unites=ia, warnings=warnings, model_used=model_used, source="ia")
    if local:
        warnings.append(
            f"{len(local)} unité(s) reconnues par le parser local (sans IA) "
            "— vérifie les montants avant d'appliquer."
        )
        return RentRollResult(unites=local, warnings=warnings, model_used="local", source="local")
    warnings.extend(ocr_warnings)
    if not warnings:
        warnings.append("Aucun loyer reconnu dans le document.")
    return RentRollResult(unites=[], warnings=warnings, model_used="none", source="none")
