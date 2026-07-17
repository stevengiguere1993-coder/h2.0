"""Génération PDF des documents locatifs (TAL + lettres maison).

Depuis 2026-07-17 (exigence Phil), les 5 avis encadrés par un formulaire
du TAL utilisent **exactement les PDF officiels**, remplis champ par
champ — voir ``tal_officiel.py`` :

- ``avis_modification``      (TAL-806)  ``avis_non_reconduction`` (TAL-807)
- ``avis_travaux_majeurs``   (TAL-808)  ``avis_reprise``          (TAL-809)
- ``reponse_cession``        (TAL-828)

Ce module conserve les 2 LETTRES maison (aucun formulaire TAL n'existe),
générées reportlab, envoyées par courriel SANS signature :

- ``rappel_paiement`` : avis de retard — paiement exigé IMMÉDIATEMENT.
- ``avis_acces`` : accès au logement, préavis 24 h (art. 1931-1933).

Retirés (2026-07-17) : mise_en_demeure (« on n'envoie pas de mise en
demeure au Québec »), sommaire_bail (inutile), trousse_bail (bail = en
pause, licence Publications du Québec ou service externe à venir).

API : ``generate_tal_pdf(form_type, context)`` → ``bytes`` PDF.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# --- Modèle de contexte typé ------------------------------------------------


@dataclass
class TalContext:
    """Contexte commun à tous les formulaires.

    Tous les champs sont optionnels — le générateur affiche « [À compléter] »
    si une valeur est manquante, pour que l'utilisateur voie clairement ce
    qu'il doit corriger sur le PDF avant signature.
    """

    # Locateur (entreprise propriétaire)
    locateur_nom: Optional[str] = None
    locateur_adresse: Optional[str] = None
    locateur_telephone: Optional[str] = None
    locateur_courriel: Optional[str] = None

    # Locataire
    locataire_nom: Optional[str] = None
    locataire_email: Optional[str] = None

    # Logement
    logement_adresse: Optional[str] = None
    logement_numero: Optional[str] = None  # ex. Apt 3
    logement_ville: Optional[str] = None

    # Bail courant
    bail_date_debut: Optional[date] = None
    bail_date_fin: Optional[date] = None
    bail_loyer_mensuel: Optional[float] = None
    bail_chauffage_inclus: bool = False
    bail_eau_chaude_inclus: bool = False
    bail_electricite_inclus: bool = False
    bail_internet_inclus: bool = False

    # Dépôt de garantie (héritage — plus utilisé depuis le retrait de la
    # trousse bail, conservé pour les anciens params sauvegardés)
    depot_garantie: Optional[float] = None

    # Avis de modification TAL-806 : une des 3 formes de hausse
    # (modif_mode 'nouveau_loyer' | 'hausse_montant' | 'hausse_pct',
    # inféré du champ fourni si absent) + renouvellement + autres modifs.
    modif_mode: Optional[str] = None
    nouveau_loyer: Optional[float] = None
    hausse_montant: Optional[float] = None
    hausse_pct: Optional[float] = None
    nouvelle_date_debut: Optional[date] = None
    nouvelle_date_fin: Optional[date] = None
    motif_modification: Optional[str] = None  # « Autre(s) modification(s) »

    # Avis de retard (rappel_paiement) — paiement IMMÉDIAT exigé.
    montant_du: Optional[float] = None
    mois_concerne: Optional[date] = None  # ex. 2025-04 → "avril 2025"

    # Non-reconduction du bail par le locataire (TAL-807)
    depart_date: Optional[date] = None  # défaut : fin du bail

    # Reprise du logement (avis_reprise — TAL-809, art. 1960 CcQ)
    reprise_date: Optional[date] = None  # si bail à durée indéterminée
    reprise_beneficiaire: Optional[str] = None
    reprise_lien: Optional[str] = None  # ex. « moi-même », « mon père »

    # Travaux majeurs (avis_travaux_majeurs — TAL-808, art. 1922-1923)
    travaux_description: Optional[str] = None
    travaux_date_debut: Optional[date] = None
    travaux_duree_valeur: Optional[str] = None  # ex. « 2 »
    travaux_duree_unite: Optional[str] = None  # jours | semaines | mois
    travaux_evacuation: bool = False
    travaux_evacuation_du: Optional[date] = None
    travaux_evacuation_au: Optional[date] = None
    travaux_indemnite: Optional[float] = None  # offerte si évacuation
    travaux_conditions: Optional[str] = None  # autres conditions

    # Accès au logement (avis_acces — art. 1931-1933 CcQ)
    acces_date: Optional[date] = None
    acces_plage: Optional[str] = None  # ex. « entre 9 h et 12 h »
    acces_motif: Optional[str] = None

    # Réponse à un avis de cession de bail (TAL-828, art. 1871/1978.2) :
    # cession_decision 'accepte' | 'refus_serieux' | 'refus_autre'.
    cession_decision: Optional[str] = None
    cession_date: Optional[date] = None  # date de cession de l'avis reçu
    cession_accepte: bool = True  # héritage (anciens params)
    cession_motif_refus: Optional[str] = None

    # Date du document (default = aujourd'hui à la génération)
    date_emission: Optional[date] = None


# --- Helpers de mise en forme ---------------------------------------------


_MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _fmt_date(d: Optional[date]) -> str:
    if d is None:
        return "[À compléter]"
    return f"{d.day} {_MOIS_FR[d.month - 1]} {d.year}"


def _fmt_mois(d: Optional[date]) -> str:
    if d is None:
        return "[À compléter]"
    return f"{_MOIS_FR[d.month - 1]} {d.year}"


def _fmt_money(n: Optional[float]) -> str:
    if n is None:
        return "[À compléter]"
    return f"{n:,.2f} $".replace(",", " ").replace(".", ",")


def _fmt_or(value: Optional[str]) -> str:
    return value if value else "[À compléter]"


def _fmt_adresse_complete(ctx: TalContext) -> str:
    parts: list[str] = []
    if ctx.logement_adresse:
        a = ctx.logement_adresse
        if ctx.logement_numero:
            a = f"{a}, {ctx.logement_numero}"
        parts.append(a)
    if ctx.logement_ville:
        parts.append(ctx.logement_ville)
    return ", ".join(parts) if parts else "[Adresse à compléter]"


def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TalTitle",
            parent=base["Title"],
            fontSize=15,
            leading=18,
            alignment=TA_CENTER,
            spaceAfter=14,
            textColor=colors.HexColor("#0a0a0b"),
        ),
        "h2": ParagraphStyle(
            "TalH2",
            parent=base["Heading2"],
            fontSize=11,
            leading=14,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor("#0a0a0b"),
        ),
        "body": ParagraphStyle(
            "TalBody",
            parent=base["BodyText"],
            fontSize=10.5,
            leading=15,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
        ),
        "right": ParagraphStyle(
            "TalRight",
            parent=base["BodyText"],
            fontSize=10.5,
            leading=15,
            alignment=TA_RIGHT,
        ),
        "small": ParagraphStyle(
            "TalSmall",
            parent=base["BodyText"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#555555"),
        ),
    }


def _header_block(ctx: TalContext, styles: dict) -> list:
    """En-tête commun : locateur en haut-gauche, date en haut-droite."""
    today = ctx.date_emission or date.today()
    locateur_lines = [
        _fmt_or(ctx.locateur_nom),
        _fmt_or(ctx.locateur_adresse),
    ]
    if ctx.locateur_telephone:
        locateur_lines.append(f"Tél. {ctx.locateur_telephone}")
    if ctx.locateur_courriel:
        locateur_lines.append(ctx.locateur_courriel)
    left = "<br/>".join(locateur_lines)
    right = _fmt_date(today)
    table = Table(
        [
            [
                Paragraph(left, styles["small"]),
                Paragraph(right, styles["right"]),
            ]
        ],
        colWidths=[10 * cm, 7 * cm],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return [table, Spacer(1, 0.5 * cm)]


def _destinataire(ctx: TalContext, styles: dict) -> list:
    nom = _fmt_or(ctx.locataire_nom)
    addr = _fmt_adresse_complete(ctx)
    body = (
        f"<b>Destinataire :</b><br/>{nom}<br/>{addr}"
    )
    return [Paragraph(body, styles["body"]), Spacer(1, 0.3 * cm)]


def _signature_block(ctx: TalContext, styles: dict) -> list:
    """Bloc de clôture des lettres SANS signature en ligne : nom du
    locateur en toutes lettres (la lettre part par courriel telle
    quelle, personne n'y appose de signature électronique)."""
    return [
        Spacer(1, 1.2 * cm),
        Paragraph(
            f"{_fmt_or(ctx.locateur_nom)}<br/>Le locateur",
            styles["small"],
        ),
    ]


# --- Builders par type de formulaire --------------------------------------


def _build_rappel_paiement(ctx: TalContext, styles: dict) -> list:
    # Exigence Phil 2026-07-17 : « il doit payer IMMÉDIATEMENT » — pas de
    # délai de grâce, pas de signature.
    flow: list = []
    flow.extend(_header_block(ctx, styles))
    flow.append(
        Paragraph("AVIS DE RETARD — LOYER IMPAYÉ", styles["title"])
    )
    flow.extend(_destinataire(ctx, styles))

    flow.append(
        Paragraph(
            (
                f"Selon nos registres, le loyer du mois de "
                f"<b>{_fmt_mois(ctx.mois_concerne)}</b> pour le logement situé "
                f"au <b>{_fmt_adresse_complete(ctx)}</b>, d'un montant de "
                f"<b>{_fmt_money(ctx.montant_du)}</b>, n'a toujours pas été acquitté."
            ),
            styles["body"],
        )
    )
    flow.append(
        Paragraph(
            (
                "Le loyer est payable le premier jour du mois. <b>Vous devez "
                "acquitter ce montant IMMÉDIATEMENT.</b>"
            ),
            styles["body"],
        )
    )
    flow.append(
        Paragraph(
            (
                "À défaut de paiement, nous nous réservons tous les recours "
                "prévus par la loi, y compris une demande au Tribunal "
                "administratif du logement en recouvrement du loyer et, si "
                "le retard dépasse trois semaines, en résiliation du bail "
                "(art. 1971 du <i>Code civil du Québec</i>)."
            ),
            styles["body"],
        )
    )
    flow.extend(_signature_block(ctx, styles))
    return flow


def _build_avis_acces(ctx: TalContext, styles: dict) -> list:
    flow: list = []
    flow.extend(_header_block(ctx, styles))
    flow.append(Paragraph("AVIS D'ACCÈS AU LOGEMENT", styles["title"]))
    flow.extend(_destinataire(ctx, styles))

    flow.append(
        Paragraph(
            (
                f"Conformément aux articles 1931 et suivants du <i>Code "
                f"civil du Québec</i>, je vous avise de mon intention "
                f"d'accéder au logement situé au "
                f"<b>{_fmt_adresse_complete(ctx)}</b> :"
            ),
            styles["body"],
        )
    )

    rows = [
        ["Date", _fmt_date(ctx.acces_date)],
        ["Plage horaire", _fmt_or(ctx.acces_plage)],
        ["Motif", _fmt_or(ctx.acces_motif)],
    ]
    t = Table(rows, colWidths=[7 * cm, 10 * cm])
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f7f7f7")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    flow.append(t)
    flow.append(Spacer(1, 0.4 * cm))

    flow.append(
        Paragraph(
            (
                "Le présent avis vous est transmis au moins vingt-quatre "
                "(24) heures à l'avance. La visite aura lieu entre 9 h et "
                "21 h (ou entre 7 h et 19 h s'il s'agit de travaux), "
                "conformément aux articles 1932 et 1933 du <i>Code civil "
                "du Québec</i>. Si le moment proposé vous convient mal, "
                "communiquez avec moi pour convenir d'un autre moment."
            ),
            styles["body"],
        )
    )

    flow.extend(_signature_block(ctx, styles))
    return flow


#: Lettres maison (reportlab). Les 5 formulaires officiels sont servis
#: par tal_officiel.fill_official_pdf.
_BUILDERS = {
    "rappel_paiement": _build_rappel_paiement,
    "avis_acces": _build_avis_acces,
}

#: Types dont l'envoi se fait par simple courriel avec PDF joint — AUCUNE
#: signature en ligne (exigence Phil 2026-07-17, points 4 et 7).
SIGNATURE_NON_REQUISE = {"rappel_paiement", "avis_acces"}


def available_form_types() -> list[str]:
    from app.services.tal_officiel import OFFICIAL_FORMS

    return [*OFFICIAL_FORMS.keys(), *_BUILDERS.keys()]


def generate_tal_pdf(
    form_type: str,
    ctx: TalContext,
    template_bytes: Optional[bytes] = None,
) -> bytes:
    """Génère le PDF demandé — formulaire OFFICIEL rempli pour les 5
    types TAL, lettre reportlab sinon. Lève KeyError si inconnu.

    ``template_bytes`` : PDF modèle de remplacement (imm_doc_templates)
    pour les formulaires officiels ; ignoré pour les lettres."""
    from app.services.tal_officiel import fill_official_pdf, is_official

    if is_official(form_type):
        return fill_official_pdf(form_type, ctx, template_bytes)

    builder = _BUILDERS[form_type]
    styles = _build_styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=form_type.replace("_", " ").upper(),
        author="h2.0 — Horizon Services Immobiliers",
    )
    flow = builder(ctx, styles)
    doc.build(flow)
    return buf.getvalue()
