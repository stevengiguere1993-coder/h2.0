"""Remplissage des formulaires OFFICIELS du Tribunal administratif du
logement (exigence Phil 2026-07-17 : « tu devras prendre EXACTEMENT les
documents que je te donne »).

Les PDF sources sont les formulaires AcroForm publiés par le TAL,
embarqués dans ``app/assets/tal/`` :

- TAL-806 ``avis_modification``      — Avis d'augmentation de loyer et de
  modification d'une autre condition du bail (art. 1942-1943 C.c.Q.)
- TAL-807 ``avis_non_reconduction``  — Avis de non-reconduction du bail
  par le locataire (art. 1946 C.c.Q.) — signé par le LOCATAIRE.
- TAL-808 ``avis_travaux_majeurs``   — Avis de réparation ou
  d'amélioration majeure (art. 1922-1923 C.c.Q.)
- TAL-809 ``avis_reprise``           — Avis de reprise de logement
  (art. 1960 C.c.Q.)
- TAL-828 ``reponse_cession``        — Réponse à un avis de cession de
  bail, avis transmis à compter du 21 février 2024 (art. 1871 et
  1978.2 C.c.Q.)

On remplit les champs du formulaire (pypdf) sans toucher au document ;
la section « Accusé de réception … en mains propres » reste vide (le
suivi d'ouverture/signature en ligne de Kratos en tient lieu). Un PDF
modèle peut être REMPLACÉ par version plus récente du TAL via la table
``imm_doc_templates`` (Paramètres → Modèles de documents) ; les noms de
champs requis sont validés à l'upload (``validate_template``).
"""

from __future__ import annotations

import io
import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # évite l'import circulaire avec tal_forms
    from app.services.tal_forms import TalContext

log = logging.getLogger(__name__)

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "tal"

#: type → nom de fichier du formulaire officiel embarqué.
OFFICIAL_FORMS: dict[str, str] = {
    "avis_modification": "tal_806_avis_modification.pdf",
    "avis_non_reconduction": "tal_807_non_reconduction.pdf",
    "avis_travaux_majeurs": "tal_808_travaux_majeurs.pdf",
    "avis_reprise": "tal_809_reprise.pdf",
    "reponse_cession": "tal_828_reponse_cession.pdf",
}


def is_official(form_type: str) -> bool:
    return form_type in OFFICIAL_FORMS


# ── Formatage ─────────────────────────────────────────────────────────


def _d(v: Optional[date]) -> str:
    """Les dates du formulaire sont des cases « Année  Mois  Jour » —
    l'ISO AAAA-MM-JJ y est lisible et sans ambiguïté."""
    return v.isoformat() if v else ""


def _money(v: Optional[float]) -> str:
    if v is None:
        return ""
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def _pct(v: Optional[float]) -> str:
    if v is None:
        return ""
    return f"{v:g}".replace(".", ",")


def _adresse(ctx: "TalContext") -> str:
    parts: list[str] = []
    if ctx.logement_adresse:
        a = ctx.logement_adresse
        if ctx.logement_numero:
            a = f"{a}, {ctx.logement_numero}"
        parts.append(a)
    if ctx.logement_ville:
        parts.append(ctx.logement_ville)
    return ", ".join(parts)


# ── Mappers : contexte → champs du formulaire ─────────────────────────
# Chaque mapper retourne (champs_texte, cases_a_cocher).


def _map_avis_modification(
    ctx: "TalContext",
) -> tuple[dict[str, str], list[str]]:
    mode = ctx.modif_mode
    if not mode:
        if ctx.hausse_pct is not None:
            mode = "hausse_pct"
        elif ctx.hausse_montant is not None:
            mode = "hausse_montant"
        elif ctx.nouveau_loyer is not None:
            mode = "nouveau_loyer"
    loyer = _money(ctx.bail_loyer_mensuel)

    text: dict[str, str] = {
        "Nom du locataire": ctx.locataire_nom or "",
        "Adresse du logement loué": _adresse(ctx),
        "Date-2": _d(ctx.nouvelle_date_debut),
        "Date-3": _d(ctx.nouvelle_date_fin),
        "Texte-1": ctx.motif_modification or "",
        "Nom du locateur ou du mandataire": ctx.locateur_nom or "",
        "Adresse": ctx.locateur_adresse or "",
        "No de téléphone": ctx.locateur_telephone or "",
        "Date-4": _d(ctx.date_emission or date.today()),
    }
    boxes: list[str] = []
    if mode == "nouveau_loyer":
        boxes.append("Montant-1")
        text["sera augmenté à"] = loyer
        text["Indiquer le nouveau loyer"] = _money(ctx.nouveau_loyer)
    elif mode == "hausse_montant":
        boxes.append("Montant-2")
        text["sera augmenté de"] = loyer
        text["Indiquer le montant de laugmentation"] = _money(
            ctx.hausse_montant
        )
    elif mode == "hausse_pct":
        boxes.append("Montant-3")
        text["sera augmenté de_2"] = loyer
        text["Indiquer le pourcentage daugmentation"] = _pct(ctx.hausse_pct)
    return text, boxes


def _map_avis_non_reconduction(
    ctx: "TalContext",
) -> tuple[dict[str, str], list[str]]:
    # Avis DU LOCATAIRE au locateur (art. 1946) — le locataire signe.
    text = {
        "Nom du locateur-1": ctx.locateur_nom or "",
        "Adresse du logement loué": _adresse(ctx),
        "Date-1": _d(ctx.depart_date or ctx.bail_date_fin),
        "Date-2": _d(ctx.date_emission or date.today()),
        "Locataire-1": ctx.locataire_nom or "",
    }
    return text, []


def _map_avis_travaux_majeurs(
    ctx: "TalContext",
) -> tuple[dict[str, str], list[str]]:
    text: dict[str, str] = {
        "Nom du locataire": ctx.locataire_nom or "",
        "Adresse du logement loué": _adresse(ctx),
        "Texte-1": ctx.travaux_description or "",
        "Date-1": _d(ctx.travaux_date_debut),
        "Date-4": _d(ctx.date_emission or date.today()),
        "Locateur-1": ctx.locateur_nom or "",
    }
    boxes: list[str] = []
    duree = (ctx.travaux_duree_valeur or "").strip()
    unite = (ctx.travaux_duree_unite or "").strip().lower()
    if duree:
        if unite.startswith("sem"):
            boxes.append("durée-2")
            text["Semaines"] = duree
        elif unite.startswith("mois"):
            boxes.append("durée-3")
            text["mois"] = duree
        else:
            boxes.append("durée-1")
            text["Jours"] = duree
    if ctx.travaux_evacuation:
        boxes.append("évacuation-2")
        text["Date-2"] = _d(ctx.travaux_evacuation_du)
        text["Date-3"] = _d(ctx.travaux_evacuation_au)
        text["indemnité"] = _money(ctx.travaux_indemnite)
    else:
        boxes.append("évacuation-1")
    if (ctx.travaux_conditions or "").strip():
        boxes.append("Conditions")
        text["Texte-2"] = (ctx.travaux_conditions or "").strip()
    return text, boxes


_MOI_MEME = {"moi-même", "moi-meme", "moi même", "moi meme", "moimême"}


def _map_avis_reprise(
    ctx: "TalContext",
) -> tuple[dict[str, str], list[str]]:
    text: dict[str, str] = {
        "Nom du locataire": ctx.locataire_nom or "",
        "Adresse du logement loué": _adresse(ctx),
        "Locateur-1": ctx.locateur_nom or "",
        "Date-3": _d(ctx.date_emission or date.today()),
    }
    boxes: list[str] = []
    if ctx.bail_date_fin is not None:
        boxes.append(
            "à lexpiration de votre bail à durée fixe se terminant le"
        )
        text["Date-1"] = _d(ctx.bail_date_fin)
    else:
        boxes.append("le")
        text["Date-2"] = _d(ctx.reprise_date)
    lien = (ctx.reprise_lien or "").strip().lower()
    beneficiaire = (ctx.reprise_beneficiaire or "").strip()
    if not beneficiaire or lien in _MOI_MEME or beneficiaire.lower() in _MOI_MEME:
        boxes.append("moimême")
    else:
        boxes.append("moimême-2")
        libelle = beneficiaire
        if ctx.reprise_lien and lien not in _MOI_MEME:
            libelle = f"{beneficiaire} — {ctx.reprise_lien.strip()}"
        text[
            "Nom du bénéficiaire et lien de parenté ou autre lien "
            "de ce bénéficiaire avec le locateurpropriétaire"
        ] = libelle
    return text, boxes


def _map_reponse_cession(
    ctx: "TalContext",
) -> tuple[dict[str, str], list[str]]:
    decision = ctx.cession_decision or (
        "accepte" if ctx.cession_accepte else "refus_serieux"
    )
    text: dict[str, str] = {
        "Nom du locataire-1": ctx.locataire_nom or "",
        "Adresse du logement loué": _adresse(ctx),
        "Locateur-1": ctx.locateur_nom or "",
        "Date-3": _d(ctx.date_emission or date.today()),
    }
    boxes: list[str] = []
    if decision == "accepte":
        boxes.append("J'accepte")
        text["Date-1"] = _d(ctx.cession_date)
    elif decision == "refus_autre":
        boxes.append("Je refuse - autre")
        text["Date-2"] = _d(ctx.cession_date)
        text["Motif de refus"] = ctx.cession_motif_refus or ""
    else:
        boxes.append("Je refuse - sérieux")
        text["Motif de refus"] = ctx.cession_motif_refus or ""
    return text, boxes


_MAPPERS = {
    "avis_modification": _map_avis_modification,
    "avis_non_reconduction": _map_avis_non_reconduction,
    "avis_travaux_majeurs": _map_avis_travaux_majeurs,
    "avis_reprise": _map_avis_reprise,
    "reponse_cession": _map_reponse_cession,
}

#: Champs indispensables par formulaire — validés quand un PDF modèle de
#: remplacement est téléversé (une version TAL aux champs renommés serait
#: silencieusement générée à blanc sinon).
REQUIRED_FIELDS: dict[str, set[str]] = {
    "avis_modification": {
        "Nom du locataire",
        "Adresse du logement loué",
        "Montant-1",
        "sera augmenté à",
        "Indiquer le nouveau loyer",
        "Montant-2",
        "sera augmenté de",
        "Indiquer le montant de laugmentation",
        "Montant-3",
        "sera augmenté de_2",
        "Indiquer le pourcentage daugmentation",
        "Date-2",
        "Date-3",
        "Texte-1",
        "Nom du locateur ou du mandataire",
        "Adresse",
        "No de téléphone",
        "Date-4",
    },
    "avis_non_reconduction": {
        "Nom du locateur-1",
        "Adresse du logement loué",
        "Date-1",
        "Date-2",
        "Locataire-1",
    },
    "avis_travaux_majeurs": {
        "Nom du locataire",
        "Adresse du logement loué",
        "Texte-1",
        "Date-1",
        "durée-1",
        "durée-2",
        "durée-3",
        "Jours",
        "Semaines",
        "mois",
        "évacuation-1",
        "évacuation-2",
        "Date-2",
        "Date-3",
        "indemnité",
        "Conditions",
        "Texte-2",
        "Date-4",
        "Locateur-1",
    },
    "avis_reprise": {
        "Nom du locataire",
        "Adresse du logement loué",
        "à lexpiration de votre bail à durée fixe se terminant le",
        "le",
        "Date-1",
        "Date-2",
        "moimême",
        "moimême-2",
        "Nom du bénéficiaire et lien de parenté ou autre lien "
        "de ce bénéficiaire avec le locateurpropriétaire",
        "Locateur-1",
        "Date-3",
    },
    "reponse_cession": {
        "Nom du locataire-1",
        "Adresse du logement loué",
        "J'accepte",
        "Je refuse - sérieux",
        "Je refuse - autre",
        "Date-1",
        "Date-2",
        "Motif de refus",
        "Locateur-1",
        "Date-3",
    },
}


# ── Remplissage ───────────────────────────────────────────────────────


def _load_template(form_type: str) -> bytes:
    return (_ASSETS_DIR / OFFICIAL_FORMS[form_type]).read_bytes()


def fill_official_pdf(
    form_type: str,
    ctx: "TalContext",
    template_bytes: Optional[bytes] = None,
) -> bytes:
    """Remplit le formulaire officiel `form_type` avec `ctx`.

    ``template_bytes`` : PDF modèle de remplacement (imm_doc_templates) ;
    None = formulaire embarqué. Les champs absents du modèle sont ignorés
    avec un warning (jamais d'échec de génération pour un nom de champ).
    """
    from pypdf import PdfReader, PdfWriter

    if template_bytes is None:
        template_bytes = _load_template(form_type)
    reader = PdfReader(io.BytesIO(template_bytes))
    fields_meta = reader.get_fields() or {}

    text_fields, boxes = _MAPPERS[form_type](ctx)

    def _on_state(name: str) -> str:
        states = (fields_meta.get(name) or {}).get("/_States_") or []
        for s in states:
            if str(s) != "/Off":
                return str(s)
        return "/On"

    values: dict[str, str] = {
        k: v for k, v in text_fields.items() if v
    }
    for b in boxes:
        values[b] = _on_state(b)

    missing = [k for k in values if k not in fields_meta]
    for k in missing:
        values.pop(k)
    if missing:
        log.warning(
            "Formulaire %s : champs absents du modèle, ignorés : %s",
            form_type,
            missing,
        )

    writer = PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        writer.update_page_form_field_values(page, values)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def validate_template(form_type: str, pdf_bytes: bytes) -> list[str]:
    """Champs requis MANQUANTS dans un PDF modèle de remplacement
    (liste vide = compatible)."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        present = set((reader.get_fields() or {}).keys())
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"PDF illisible : {exc}") from exc
    required = REQUIRED_FIELDS.get(form_type, set())
    return sorted(k for k in required if k not in present)
