"""Génère le PDF d'une Promesse d'achat à partir du template duProprio v4.7.

Les sections texte libre (baux, inclusions, exclusions, autres conditions)
sont rendues telles que saisies. Les sections cochables (inspection,
visite logements, eau/septique, etc.) apparaissent uniquement si activées.

ReportLab pur Python — aucune dépendance système (compatible Render Free).
"""

from __future__ import annotations

import io
import logging
import os
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.purchase_agreement import PurchaseAgreement


log = logging.getLogger(__name__)


_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "logo.png",
)

COMPANY_NAME = "Horizon Services Immobiliers"
COMPANY_RBQ = "RBQ 5868-5991-01"
COMPANY_SITE = "immohorizon.com"
COMPANY_EMAIL = "info@immohorizon.com"

ACCENT_HEX = "#d89b3c"
DARK_HEX = "#111111"
MUTED_HEX = "#6b6b6b"
LINE_HEX = "#e2e2e2"
HEADER_BG_HEX = "#2f7d32"  # vert duProprio


def _lazy_reportlab() -> dict[str, Any]:
    from reportlab.lib import colors  # type: ignore
    from reportlab.lib.pagesizes import letter  # type: ignore
    from reportlab.lib.styles import (  # type: ignore
        ParagraphStyle,
        getSampleStyleSheet,
    )
    from reportlab.lib.units import mm  # type: ignore
    from reportlab.platypus import (  # type: ignore
        Image,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    return {
        "colors": colors,
        "letter": letter,
        "ParagraphStyle": ParagraphStyle,
        "getSampleStyleSheet": getSampleStyleSheet,
        "mm": mm,
        "Image": Image,
        "KeepTogether": KeepTogether,
        "PageBreak": PageBreak,
        "Paragraph": Paragraph,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
    }


def _money(n: Optional[float]) -> str:
    if n is None:
        return "_____________________"
    return f"{float(n):,.2f} $".replace(",", " ")


def _date(d: Optional[date | datetime]) -> str:
    if d is None:
        return "____________"
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%Y-%m-%d")


def _txt(v: Optional[str], width: int = 30) -> str:
    if v is None or not str(v).strip():
        return "_" * width
    return str(v)


def _yn(v: bool) -> str:
    return "☒" if v else "☐"


def _styles(rl: dict[str, Any]):
    ParagraphStyle = rl["ParagraphStyle"]
    colors = rl["colors"]
    DARK = colors.HexColor(DARK_HEX)
    MUTED = colors.HexColor(MUTED_HEX)
    base = rl["getSampleStyleSheet"]()
    return {
        "h1": ParagraphStyle(
            "h1",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=DARK,
        ),
        "section": ParagraphStyle(
            "section",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.white,
            backColor=colors.HexColor(HEADER_BG_HEX),
            leftIndent=4,
            rightIndent=4,
            spaceBefore=8,
            spaceAfter=4,
            borderPadding=4,
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=DARK,
            spaceBefore=4,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=DARK,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=MUTED,
        ),
        "italic": ParagraphStyle(
            "italic",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8.5,
            leading=11,
            textColor=MUTED,
        ),
    }


# --- Helpers de rendu --------------------------------------------------


def _section_header(rl, title: str, styles) -> Any:
    return rl["Paragraph"](title, styles["section"])


def _two_col_block(rl, left_rows: list[str], right_rows: list[str], styles) -> Any:
    """Tableau 2 colonnes Acheteur / Vendeur."""
    Paragraph = rl["Paragraph"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    colors = rl["colors"]
    left_cell = [Paragraph(t, styles["body"]) for t in left_rows]
    right_cell = [Paragraph(t, styles["body"]) for t in right_rows]
    tbl = Table(
        [[left_cell, right_cell]],
        colWidths=["50%", "50%"],
    )
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor(LINE_HEX)),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor(LINE_HEX)),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return tbl


def _party_lines(role: str, n: int, name, address, day, eve, email) -> list[str]:
    return [
        f"<b>{role.upper()} {n} :</b>",
        f"Nom : {_txt(name)}",
        f"Adresse : {_txt(address)}",
        f"Téléphone (jour) : {_txt(day, 18)}",
        f"Téléphone (soir) : {_txt(eve, 18)}",
        f"Courriel : {_txt(email)}",
    ]


def _signature_image_flowable(rl, sig_bytes: Optional[bytes], styles):
    Image = rl["Image"]
    mm = rl["mm"]
    if not sig_bytes:
        return rl["Paragraph"]("(non signé)", styles["small"])
    try:
        return Image(io.BytesIO(sig_bytes), width=60 * mm, height=20 * mm)
    except Exception as exc:
        log.warning("PA signature image render failed: %s", exc)
        return rl["Paragraph"]("(signature illisible)", styles["small"])


# --- Loader ------------------------------------------------------------


async def _load(db: AsyncSession, pa_id: int) -> Optional[PurchaseAgreement]:
    pa = (
        await db.execute(
            select(PurchaseAgreement).where(PurchaseAgreement.id == pa_id)
        )
    ).scalar_one_or_none()
    if pa is None:
        return None
    # Force-load deferred signature blobs.
    await db.refresh(
        pa,
        attribute_names=["buyer_signature_image", "seller_signature_image"],
    )
    return pa


# --- Render ------------------------------------------------------------


def _render_bytes(pa: PurchaseAgreement) -> bytes:
    rl = _lazy_reportlab()
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    PageBreak = rl["PageBreak"]
    KeepTogether = rl["KeepTogether"]
    mm = rl["mm"]
    colors = rl["colors"]

    buf = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=rl["letter"],
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Promesse d'achat {pa.reference}",
        author=COMPANY_NAME,
    )
    s = _styles(rl)
    story: list = []

    # ---- Header
    Image = rl["Image"]
    left: list = []
    if os.path.exists(_LOGO_PATH):
        try:
            left.append(Image(_LOGO_PATH, width=22 * mm, height=22 * mm))
        except Exception:
            pass
    left.extend([
        Paragraph(f"<b>{COMPANY_NAME}</b>", s["body"]),
        Paragraph(COMPANY_RBQ, s["small"]),
        Paragraph(f"{COMPANY_SITE} &middot; {COMPANY_EMAIL}", s["small"]),
    ])
    right = [
        Paragraph("<b>OFFRE D'ACHAT</b>", s["h1"]),
        Paragraph("immeuble à revenus (usage résidentiel)", s["italic"]),
        Paragraph(f"N<sup>o</sup> {pa.reference}", s["body"]),
    ]
    header = Table([[left, right]], colWidths=["55%", "45%"])
    header.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ])
    )
    story.append(header)
    story.append(Spacer(1, 8))

    # ---- 1. Identification des parties
    story.append(_section_header(rl, "1. IDENTIFICATION DES PARTIES", s))
    story.append(_two_col_block(
        rl,
        _party_lines("Acheteur", 1, pa.buyer_1_name, pa.buyer_1_address,
                     pa.buyer_1_phone_day, pa.buyer_1_phone_eve, pa.buyer_1_email),
        _party_lines("Vendeur", 1, pa.seller_1_name, pa.seller_1_address,
                     pa.seller_1_phone_day, pa.seller_1_phone_eve, pa.seller_1_email),
        s,
    ))
    if pa.buyer_2_name or pa.seller_2_name:
        story.append(Spacer(1, 4))
        story.append(_two_col_block(
            rl,
            _party_lines("Acheteur", 2, pa.buyer_2_name, pa.buyer_2_address,
                         pa.buyer_2_phone_day, pa.buyer_2_phone_eve, pa.buyer_2_email),
            _party_lines("Vendeur", 2, pa.seller_2_name, pa.seller_2_address,
                         pa.seller_2_phone_day, pa.seller_2_phone_eve, pa.seller_2_email),
            s,
        ))

    # ---- 2. Objet du contrat
    story.append(_section_header(rl, "2. OBJET DU CONTRAT", s))
    story.append(Paragraph(
        "L'Acheteur promet d'acheter, aux prix et conditions ci-dessous "
        "énoncés, l'immeuble suivant :",
        s["body"],
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"<b>Adresse civique :</b> {_txt(pa.property_address, 60)}",
        s["body"],
    ))
    story.append(Paragraph(
        f"<b>Désignation cadastrale (numéro de lot) :</b> "
        f"{_txt(pa.lot_designation, 40)}",
        s["body"],
    ))
    dim = ""
    if pa.lot_width or pa.lot_depth:
        unit = pa.lot_dimension_unit or "m"
        dim = (
            f"{pa.lot_width or '___'} × {pa.lot_depth or '___'} {unit}"
        )
    area = ""
    if pa.lot_area:
        area = f"{pa.lot_area} {pa.lot_area_unit or 'm²'}"
    story.append(Paragraph(
        f"<b>Mesures du lot :</b> {dim or '____ × ____'}  "
        f"&nbsp;&nbsp; <b>Superficie :</b> {area or '____'}",
        s["body"],
    ))

    # ---- 3. Prix et modalités de paiement
    story.append(_section_header(rl, "3. PRIX ET MODALITÉS DE PAIEMENT", s))
    story.append(Paragraph(
        f"<b>3.1 Prix :</b> Le prix d'achat sera de "
        f"<b>{_money(pa.price)}</b>, payé entièrement à la signature de "
        "l'acte de vente.",
        s["body"],
    ))
    if pa.down_payment is not None or pa.mortgage_amount is not None:
        story.append(Paragraph(
            "<b>3.2 Modalités :</b> "
            f"Mise de fonds : <b>{_money(pa.down_payment)}</b> &middot; "
            f"Emprunt hypothécaire : <b>{_money(pa.mortgage_amount)}</b>",
            s["body"],
        ))
    if pa.deposit_amount is not None:
        story.append(Paragraph(
            f"<b>3.3 Acompte :</b> {_money(pa.deposit_amount)} en "
            f"fidéicommis chez M<sup>e</sup> {_txt(pa.deposit_notary, 30)}, "
            "remboursable si l'offre devient nulle.",
            s["body"],
        ))

    # ---- 4. Déclarations de l'Acheteur
    story.append(_section_header(rl, "4. DÉCLARATIONS DE L'ACHETEUR", s))
    story.append(Paragraph(
        f"<b>4.1 a)</b> L'Acheteur déclare avoir visité l'immeuble le "
        f"<b>{_date(pa.visit_date)}</b> et s'en déclare satisfait.",
        s["body"],
    ))
    story.append(Paragraph(
        "<b>4.1 b)</b> L'Acheteur a vérifié la destination autorisée par "
        "le zonage municipal.",
        s["body"],
    ))
    if pa.rented_appliances_text:
        story.append(Paragraph(
            f"<b>4.3 Contrats de location :</b> {pa.rented_appliances_text}",
            s["body"],
        ))

    # ---- 5. Déclarations du Vendeur
    story.append(_section_header(rl, "5. DÉCLARATIONS DU VENDEUR", s))
    story.append(Paragraph(
        "Le Vendeur déclare l'immeuble libre de vices, hypothèques non "
        "divulguées, avis de non-conformité et procédures de la Régie du "
        "logement, selon les clauses standard duProprio v4.7 (5.1 a-k, "
        "5.2 livraison, 5.3 titre, 5.4 documents, 5.5 frais, 5.6 vice, "
        "5.7 conjoint).",
        s["body"],
    ))
    if pa.annual_rents is not None:
        story.append(Paragraph(
            f"<b>5.1 k)</b> Loyers annuels : <b>{_money(pa.annual_rents)}</b>.",
            s["body"],
        ))
    if pa.leases_expiry_text:
        story.append(Paragraph(
            f"<b>Échéance des baux :</b> {pa.leases_expiry_text}",
            s["body"],
        ))

    # ---- 6. Conditions
    story.append(_section_header(rl, "6. CONDITIONS DE LA PRÉSENTE OFFRE D'ACHAT", s))
    fin_kind = (pa.financing_kind or "hypothecaire").lower()
    if fin_kind == "comptant":
        story.append(Paragraph(
            f"{_yn(True)} <b>6.1.2 Achat comptant</b> — l'Acheteur "
            "fournira la preuve de disponibilité des fonds dans les "
            "10 jours suivant l'acceptation.",
            s["body"],
        ))
    else:
        story.append(Paragraph(
            f"{_yn(True)} <b>6.1.1 Financement hypothécaire</b> — "
            f"emprunt minimum {pa.financing_min_pct or '___'} %, taux "
            f"max {pa.financing_max_rate or '___'} %, amortissement "
            f"{pa.financing_amortization_years or '___'} ans, terme min "
            f"{pa.financing_min_term_years or '___'} ans. Engagement du "
            "créancier dans les 20 jours suivant l'acceptation.",
            s["body"],
        ))
    story.append(Paragraph(
        f"{_yn(pa.inspection_enabled)} <b>6.2.1 Inspection</b> — "
        f"délai de {pa.inspection_days} jours suivant l'acceptation pour "
        "faire inspecter l'immeuble par un expert en bâtiment, aux frais "
        "de l'Acheteur.",
        s["body"],
    ))
    story.append(Paragraph(
        f"{_yn(pa.visit_units_enabled)} <b>6.2.2 Visite des logements et "
        "vérification des baux</b> — 5 jours après l'acceptation pour "
        "obtenir copies des baux, dépenses et états financiers.",
        s["body"],
    ))
    story.append(Paragraph(
        f"{_yn(pa.water_septic_enabled)} <b>6.2.3 Tests eau potable / "
        "installations septiques</b> — 7 jours pour effectuer les tests.",
        s["body"],
    ))
    if pa.buyer_property_sale_enabled:
        story.append(Paragraph(
            f"{_yn(True)} <b>6.2.4 Vente de l'immeuble de l'Acheteur</b> "
            f"situé au {_txt(pa.buyer_property_address, 40)}, "
            f"avant le {_date(pa.buyer_property_deadline)}. Clause de "
            "72 heures applicable.",
            s["body"],
        ))
    if pa.conditional_other_offer_enabled:
        story.append(Paragraph(
            f"{_yn(True)} <b>6.2.5 Acceptation conditionnelle à l'annulation "
            f"d'une autre offre</b> acceptée le {_date(pa.other_offer_date)}.",
            s["body"],
        ))

    # ---- 7. Transfert et occupation
    story.append(_section_header(rl, "7. TRANSFERT DE PROPRIÉTÉ ET OCCUPATION", s))
    story.append(Paragraph(
        f"<b>7.1 Acte de vente</b> — signé devant le notaire de l'Acheteur "
        f"le ou avant le <b>{_date(pa.act_of_sale_date)}</b>.",
        s["body"],
    ))
    occ_compl = ""
    if pa.occupation_compensation_per_month:
        occ_compl = (
            f" Si le Vendeur reste après l'acte : indemnité de "
            f"<b>{_money(pa.occupation_compensation_per_month)}</b>/mois."
        )
    story.append(Paragraph(
        f"<b>7.2 Occupation</b> — disponible le "
        f"<b>{_date(pa.occupation_date)}</b> à "
        f"<b>{pa.occupation_time or '____'}</b>.{occ_compl}",
        s["body"],
    ))
    if pa.baux_text:
        story.append(Paragraph(
            f"<b>7.4 Baux :</b> {pa.baux_text}",
            s["body"],
        ))
    if pa.inclusions_text:
        story.append(Paragraph(
            f"<b>7.5 Inclusions :</b> {pa.inclusions_text}",
            s["body"],
        ))
    if pa.exclusions_text:
        story.append(Paragraph(
            f"<b>7.6 Exclusions :</b> {pa.exclusions_text}",
            s["body"],
        ))

    # ---- 8. Autres conditions
    if pa.other_conditions_text:
        story.append(_section_header(rl, "8. AUTRES CONDITIONS ET DÉCLARATIONS", s))
        story.append(Paragraph(pa.other_conditions_text, s["body"]))

    # ---- 9. Délai d'acceptation
    story.append(_section_header(rl, "9. DÉLAI D'ACCEPTATION", s))
    story.append(Paragraph(
        f"La présente offre d'achat est irrévocable jusqu'à "
        f"<b>{pa.acceptance_deadline_time or '____'}</b> le "
        f"<b>{_date(pa.acceptance_deadline_date)}</b>. Si le Vendeur "
        "l'accepte dans le délai prévu, elle constituera un contrat "
        "liant juridiquement l'Acheteur et le Vendeur.",
        s["body"],
    ))

    # ---- 10. Signature acheteur
    story.append(_section_header(rl, "10. SIGNATURE DE L'ACHETEUR", s))
    sig_buyer = _signature_image_flowable(rl, pa.buyer_signature_image, s)
    buyer_signed_line = (
        f"Signé par {pa.buyer_signed_name or '____'} "
        f"le {_date(pa.buyer_signed_at)}"
        if pa.buyer_signed_at
        else "(en attente)"
    )
    story.append(KeepTogether([
        sig_buyer,
        Spacer(1, 2),
        Paragraph(buyer_signed_line, s["small"]),
    ]))

    # ---- 11. Réponse vendeur
    story.append(_section_header(rl, "11. RÉPONSE DU VENDEUR", s))
    accepted = pa.seller_response == "accepted"
    rejected = pa.seller_response == "rejected"
    story.append(Paragraph(
        f"{_yn(accepted)} J'accepte cette offre d'achat &nbsp;&nbsp; "
        f"{_yn(rejected)} Je refuse cette offre d'achat",
        s["body"],
    ))
    sig_seller = _signature_image_flowable(rl, pa.seller_signature_image, s)
    seller_signed_line = (
        f"Signé par {pa.seller_signed_name or '____'} "
        f"le {_date(pa.seller_signed_at)}"
        if pa.seller_signed_at
        else "(en attente de réponse)"
    )
    story.append(KeepTogether([
        sig_seller,
        Spacer(1, 2),
        Paragraph(seller_signed_line, s["small"]),
    ]))
    if rejected and pa.seller_rejection_reason:
        story.append(Paragraph(
            f"<i>Motif du refus :</i> {pa.seller_rejection_reason}",
            s["small"],
        ))

    # Footer
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Document généré par le portail Horizon le "
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}. "
        "Ce contrat n'engage les parties qu'après signature.",
        s["italic"],
    ))

    doc.build(story)
    return buf.getvalue()


async def render_purchase_agreement_pdf(
    db: AsyncSession, pa_id: int
) -> bytes:
    pa = await _load(db, pa_id)
    if pa is None:
        raise ValueError(f"PurchaseAgreement {pa_id} introuvable")
    return _render_bytes(pa)
