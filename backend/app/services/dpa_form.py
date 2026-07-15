"""Accord de DÉBIT PRÉAUTORISÉ (DPA) — formulaire PDF prérempli.

Conforme aux exigences de la Règle H1 de Paiements Canada pour un DPA
de catégorie « personnel » : identification du payeur et du bénéficiaire,
montant fixe et fréquence, renseignements bancaires (ou spécimen de
chèque), clauses obligatoires d'annulation et de remboursement.

Le créancier perçoit les loyers via le service de perception de
prélèvements (ex. Dépôts et retraits directs Desjardins) : le locataire
remplit/signe ce formulaire et le retourne avec un spécimen de chèque.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Optional

from reportlab.lib import colors
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


def _fmt_money(n: Optional[float]) -> str:
    if n is None:
        return "________________ $"
    return f"{n:,.2f} $".replace(",", " ").replace(".", ",")


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "dpa_title", parent=base["Title"], fontSize=15, leading=19,
            spaceAfter=2, textColor=colors.HexColor("#0a0a0b"),
        ),
        "sub": ParagraphStyle(
            "dpa_sub", parent=base["Normal"], fontSize=9, leading=12,
            textColor=colors.HexColor("#555555"), spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "dpa_h2", parent=base["Heading2"], fontSize=11, leading=14,
            spaceBefore=10, spaceAfter=4,
            textColor=colors.HexColor("#0a0a0b"),
        ),
        "body": ParagraphStyle(
            "dpa_body", parent=base["Normal"], fontSize=9.5, leading=13.5,
        ),
        "small": ParagraphStyle(
            "dpa_small", parent=base["Normal"], fontSize=8, leading=11,
            textColor=colors.HexColor("#555555"),
        ),
    }


def _champ_table(rows: list[tuple[str, str]]) -> Table:
    t = Table(
        [[label, value] for label, value in rows],
        colWidths=[6.2 * cm, 10.8 * cm],
    )
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#333333")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                (
                    "LINEBELOW",
                    (1, 0),
                    (1, -1),
                    0.4,
                    colors.HexColor("#bbbbbb"),
                ),
            ]
        )
    )
    return t


def generate_dpa_pdf(
    *,
    locataire_nom: str,
    logement_adresse: str,
    creancier_nom: str,
    loyer_mensuel: Optional[float],
    jour_prelevement: int = 1,
) -> bytes:
    """PDF de l'accord DPA prérempli (les renseignements bancaires
    restent à remplir à la main par le locataire)."""
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        leftMargin=1.9 * cm,
        rightMargin=1.9 * cm,
        title="Accord de débit préautorisé (DPA)",
    )

    el: list = []
    el.append(Paragraph("Accord de débit préautorisé (DPA)", st["title"]))
    el.append(
        Paragraph(
            "Paiement du loyer par prélèvement bancaire — catégorie "
            "« personnel » (Règle H1 de Paiements Canada)",
            st["sub"],
        )
    )

    el.append(Paragraph("1. Identification", st["h2"]))
    el.append(
        _champ_table(
            [
                ("Payeur (locataire)", locataire_nom or ""),
                ("Adresse du logement", logement_adresse or ""),
                ("Bénéficiaire (locateur)", creancier_nom or ""),
            ]
        )
    )

    el.append(Paragraph("2. Autorisation de prélèvement", st["h2"]))
    el.append(
        Paragraph(
            f"J'autorise <b>{creancier_nom}</b> à prélever de mon compte "
            f"bancaire, identifié ci-dessous, la somme de "
            f"<b>{_fmt_money(loyer_mensuel)}</b> par mois, le "
            f"<b>{jour_prelevement}<super>er</super></b> jour de chaque "
            "mois (ou le jour ouvrable suivant), à titre de paiement du "
            "loyer du logement identifié ci-dessus. Le montant pourra être "
            "ajusté au loyer prévu au bail en vigueur, sur préavis écrit "
            "d'au moins 10 jours avant le prélèvement modifié.",
            st["body"],
        )
    )

    el.append(Paragraph("3. Renseignements bancaires du payeur", st["h2"]))
    el.append(
        _champ_table(
            [
                ("Institution financière", ""),
                ("N° d'institution (3 chiffres)", ""),
                ("N° de transit (5 chiffres)", ""),
                ("N° de compte", ""),
            ]
        )
    )
    el.append(Spacer(1, 4))
    el.append(
        Paragraph(
            "☐ Un spécimen de chèque portant la mention « ANNULÉ » est "
            "joint au présent accord (recommandé).",
            st["body"],
        )
    )

    el.append(Paragraph("4. Annulation", st["h2"]))
    el.append(
        Paragraph(
            "Je peux révoquer la présente autorisation en tout temps, sur "
            "préavis écrit de 30 jours au bénéficiaire. Je peux obtenir un "
            "spécimen de formulaire d'annulation, ou plus d'information "
            "sur mon droit d'annuler un accord de DPA, auprès de mon "
            "institution financière ou en visitant www.paiements.ca. "
            "L'annulation du DPA ne met pas fin à mon obligation de payer "
            "le loyer prévu au bail par un autre mode de paiement.",
            st["body"],
        )
    )

    el.append(Paragraph("5. Remboursement", st["h2"]))
    el.append(
        Paragraph(
            "J'ai certains droits de recours si un débit n'est pas "
            "conforme au présent accord. Par exemple, j'ai le droit de "
            "recevoir le remboursement de tout débit qui n'est pas "
            "autorisé ou qui n'est pas compatible avec le présent accord "
            "de DPA. Pour obtenir plus d'information sur mes droits de "
            "recours, je peux communiquer avec mon institution financière "
            "ou visiter www.paiements.ca.",
            st["body"],
        )
    )

    el.append(Paragraph("6. Signature du payeur", st["h2"]))
    sig = Table(
        [
            ["Signature :", "", "Date :", ""],
        ],
        colWidths=[2.2 * cm, 8.3 * cm, 1.6 * cm, 4.9 * cm],
    )
    sig.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("TOPPADDING", (0, 0), (-1, -1), 16),
                ("LINEBELOW", (1, 0), (1, 0), 0.6, colors.black),
                ("LINEBELOW", (3, 0), (3, 0), 0.6, colors.black),
            ]
        )
    )
    el.append(sig)

    el.append(Spacer(1, 10))
    el.append(
        Paragraph(
            "Une fois rempli et signé, retournez ce formulaire au "
            f"bénéficiaire ({creancier_nom}) avec votre spécimen de "
            "chèque. Le bénéficiaire perçoit les loyers par l'entremise "
            "du service de prélèvements préautorisés de son institution "
            "financière (Desjardins — Dépôts et retraits directs). "
            f"Généré le {date.today().isoformat()}.",
            st["small"],
        )
    )

    doc.build(el)
    return buf.getvalue()
