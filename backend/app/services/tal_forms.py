"""Génération PDF des formulaires usuels du Tribunal administratif du
logement (TAL, ex-Régie du logement).

Les formulaires officiels TAL sont des PDF gouvernementaux qu'on ne peut
pas redistribuer tels quels. Ce module produit donc des **lettres
officielles équivalentes** pré-remplies avec les bonnes mentions
juridiques, dans un format PDF propre signable et imprimable. Couvre
les communications les plus fréquentes :

- ``avis_modification`` : avis au locataire de modification du bail
  (hausse de loyer + autres modifs) — délais 3-6 mois selon durée du bail.
- ``avis_fin_bail`` : avis de non-renouvellement par le locateur
  (cas légalement permis, délai 6 mois pour bail >= 12 mois).
- ``rappel_paiement`` : rappel amiable de paiement de loyer en retard.
- ``mise_en_demeure`` : mise en demeure formelle avant recours TAL.
- ``sommaire_bail`` : résumé du bail courant pour archivage interne.

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

    # Modifications proposées (avis_modification + sommaire_bail)
    nouveau_loyer: Optional[float] = None
    nouvelle_date_debut: Optional[date] = None
    nouvelle_date_fin: Optional[date] = None
    motif_modification: Optional[str] = None

    # Paiements (rappel + mise en demeure)
    montant_du: Optional[float] = None
    mois_concerne: Optional[date] = None  # ex. 2025-04 → "avril 2025"
    delai_paiement_jours: int = 10

    # Motif fin de bail
    motif_fin_bail: Optional[str] = None

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


def _signature_block(styles: dict) -> list:
    return [
        Spacer(1, 1.2 * cm),
        Paragraph(
            "____________________________________<br/>Signature du locateur",
            styles["small"],
        ),
    ]


# --- Builders par type de formulaire --------------------------------------


def _build_avis_modification(ctx: TalContext, styles: dict) -> list:
    flow: list = []
    flow.extend(_header_block(ctx, styles))
    flow.append(
        Paragraph(
            "AVIS DE MODIFICATION DU BAIL",
            styles["title"],
        )
    )
    flow.extend(_destinataire(ctx, styles))

    flow.append(
        Paragraph(
            (
                f"Conformément aux articles 1942 et suivants du <i>Code civil "
                f"du Québec</i>, je vous transmets par les présentes un "
                f"avis de modification du bail concernant le logement situé "
                f"au <b>{_fmt_adresse_complete(ctx)}</b>."
            ),
            styles["body"],
        )
    )

    # Tableau bail courant vs proposé
    rows = [
        ["", "Bail courant", "Renouvellement proposé"],
        [
            "Loyer mensuel",
            _fmt_money(ctx.bail_loyer_mensuel),
            _fmt_money(ctx.nouveau_loyer),
        ],
        [
            "Date de début",
            _fmt_date(ctx.bail_date_debut),
            _fmt_date(ctx.nouvelle_date_debut),
        ],
        [
            "Date de fin",
            _fmt_date(ctx.bail_date_fin),
            _fmt_date(ctx.nouvelle_date_fin),
        ],
    ]
    t = Table(rows, colWidths=[5 * cm, 6 * cm, 6 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    flow.append(t)
    flow.append(Spacer(1, 0.4 * cm))

    if ctx.motif_modification:
        flow.append(
            Paragraph(
                f"<b>Motifs des modifications :</b> {ctx.motif_modification}",
                styles["body"],
            )
        )

    flow.append(
        Paragraph(
            (
                "<b>Délai de réponse :</b> Vous disposez d'un délai d'<b>un (1) "
                "mois</b> à compter de la réception du présent avis pour "
                "accepter ou refuser les modifications proposées en m'en "
                "informant par écrit. À défaut de réponse de votre part, vous "
                "serez réputé avoir accepté les modifications. Si vous refusez, "
                "je devrai m'adresser au Tribunal administratif du logement "
                "dans le mois suivant votre refus pour fixation du loyer."
            ),
            styles["body"],
        )
    )

    flow.append(
        Paragraph(
            (
                "Pour toute question, vous pouvez communiquer avec moi aux "
                "coordonnées indiquées en en-tête."
            ),
            styles["body"],
        )
    )

    flow.extend(_signature_block(styles))
    return flow


def _build_avis_fin_bail(ctx: TalContext, styles: dict) -> list:
    flow: list = []
    flow.extend(_header_block(ctx, styles))
    flow.append(Paragraph("AVIS DE NON-RENOUVELLEMENT DU BAIL", styles["title"]))
    flow.extend(_destinataire(ctx, styles))

    flow.append(
        Paragraph(
            (
                f"Je vous avise par les présentes que le bail concernant "
                f"le logement situé au <b>{_fmt_adresse_complete(ctx)}</b>, "
                f"actuellement en vigueur jusqu'au "
                f"<b>{_fmt_date(ctx.bail_date_fin)}</b>, ne sera pas renouvelé."
            ),
            styles["body"],
        )
    )

    motif = ctx.motif_fin_bail or "[motif légal à compléter]"
    flow.append(
        Paragraph(
            (
                f"<b>Motif :</b> {motif}.<br/>Cet avis est donné conformément "
                f"aux articles 1959 à 1968 du <i>Code civil du Québec</i>, qui "
                f"encadrent les cas où un locateur peut reprendre ou évincer "
                f"un locataire."
            ),
            styles["body"],
        )
    )

    flow.append(
        Paragraph(
            (
                "<b>Délai de contestation :</b> Vous disposez d'<b>un (1) "
                "mois</b> à compter de la réception du présent avis pour "
                "vous y opposer en saisissant le Tribunal administratif "
                "du logement, à défaut de quoi vous serez réputé avoir "
                "consenti à quitter le logement à l'échéance du bail."
            ),
            styles["body"],
        )
    )

    flow.extend(_signature_block(styles))
    return flow


def _build_rappel_paiement(ctx: TalContext, styles: dict) -> list:
    flow: list = []
    flow.extend(_header_block(ctx, styles))
    flow.append(Paragraph("RAPPEL — LOYER EN RETARD", styles["title"]))
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
                f"Nous vous prions de bien vouloir régulariser la situation "
                f"dans un délai de <b>{ctx.delai_paiement_jours} jours</b> à "
                f"compter de la réception du présent rappel."
            ),
            styles["body"],
        )
    )
    flow.append(
        Paragraph(
            (
                "Si vous éprouvez des difficultés financières ponctuelles, "
                "n'hésitez pas à communiquer avec nous afin de convenir "
                "d'une entente."
            ),
            styles["body"],
        )
    )
    flow.extend(_signature_block(styles))
    return flow


def _build_mise_en_demeure(ctx: TalContext, styles: dict) -> list:
    flow: list = []
    flow.extend(_header_block(ctx, styles))
    flow.append(
        Paragraph(
            "MISE EN DEMEURE — DÉFAUT DE PAIEMENT DU LOYER",
            styles["title"],
        )
    )
    flow.extend(_destinataire(ctx, styles))

    flow.append(
        Paragraph(
            (
                f"Malgré nos avis précédents, le loyer du mois de "
                f"<b>{_fmt_mois(ctx.mois_concerne)}</b> pour le logement "
                f"<b>{_fmt_adresse_complete(ctx)}</b>, au montant de "
                f"<b>{_fmt_money(ctx.montant_du)}</b>, demeure impayé."
            ),
            styles["body"],
        )
    )

    flow.append(
        Paragraph(
            (
                f"<b>Vous êtes par les présentes mis en demeure</b> de "
                f"verser cette somme dans un délai de "
                f"<b>{ctx.delai_paiement_jours} jours</b> à compter de la "
                f"réception du présent avis."
            ),
            styles["body"],
        )
    )

    flow.append(
        Paragraph(
            (
                "À défaut, je me verrai dans l'obligation d'introduire "
                "sans autre avis ni délai un recours devant le Tribunal "
                "administratif du logement, conformément à l'article 1971 "
                "du <i>Code civil du Québec</i>, en vue notamment de la "
                "résiliation du bail, de l'expulsion du logement et du "
                "recouvrement des sommes dues, intérêts et frais en sus."
            ),
            styles["body"],
        )
    )

    flow.append(
        Paragraph(
            (
                "Le présent avis vaut mise en demeure conformément aux "
                "articles 1594 et suivants du <i>Code civil du Québec</i>."
            ),
            styles["small"],
        )
    )

    flow.extend(_signature_block(styles))
    return flow


def _build_sommaire_bail(ctx: TalContext, styles: dict) -> list:
    flow: list = []
    flow.extend(_header_block(ctx, styles))
    flow.append(Paragraph("SOMMAIRE DU BAIL", styles["title"]))

    inclusions: list[str] = []
    if ctx.bail_chauffage_inclus:
        inclusions.append("chauffage")
    if ctx.bail_eau_chaude_inclus:
        inclusions.append("eau chaude")
    if ctx.bail_electricite_inclus:
        inclusions.append("électricité")
    if ctx.bail_internet_inclus:
        inclusions.append("Internet")
    inclusions_str = ", ".join(inclusions) if inclusions else "Aucune"

    rows = [
        ["Locateur", _fmt_or(ctx.locateur_nom)],
        ["Locataire", _fmt_or(ctx.locataire_nom)],
        ["Logement", _fmt_adresse_complete(ctx)],
        ["Date de début", _fmt_date(ctx.bail_date_debut)],
        ["Date de fin", _fmt_date(ctx.bail_date_fin)],
        ["Loyer mensuel", _fmt_money(ctx.bail_loyer_mensuel)],
        ["Inclusions", inclusions_str],
    ]
    t = Table(rows, colWidths=[5 * cm, 12 * cm])
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f7f7f7")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    flow.append(t)
    flow.append(Spacer(1, 0.5 * cm))
    flow.append(
        Paragraph(
            (
                "Document interne généré par h2.0 — sert d'aide-mémoire et "
                "ne se substitue pas au bail signé. Vérifier que les "
                "informations correspondent au bail officiel avant tout usage."
            ),
            styles["small"],
        )
    )
    return flow


_BUILDERS = {
    "avis_modification": _build_avis_modification,
    "avis_fin_bail": _build_avis_fin_bail,
    "rappel_paiement": _build_rappel_paiement,
    "mise_en_demeure": _build_mise_en_demeure,
    "sommaire_bail": _build_sommaire_bail,
}


def available_form_types() -> list[str]:
    return list(_BUILDERS.keys())


def generate_tal_pdf(form_type: str, ctx: TalContext) -> bytes:
    """Génère le PDF demandé. Lève KeyError si form_type inconnu."""
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
