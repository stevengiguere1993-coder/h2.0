"""Génère le PDF d'une Offre d'achat minimaliste.

Une page A4 — bloc d'offre formel mais épuré, inspiré DuProprio :
- Header avec acheteur et date
- Identification propriété (adresse depuis le deal)
- Prix offert (chiffres + lettres)
- Date prise de possession
- Conditions cochées avec délais
- Acompte
- Date limite de réponse
- Lignes de signature acheteur / vendeur
- Mentions légales en bas

ReportLab pur Python — pas de dépendance système, compatible Render Free.
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.offer import Offer
from app.models.prospection_deal import ProspectionDeal
from app.services.offer_template import (
    BUYER_ENTITY_ADDRESS,
    BUYER_ENTITY_NAME,
    LEGAL_NOTICE,
    amount_to_french_words,
    format_money,
)


log = logging.getLogger(__name__)


_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "logo.png",
)


def _lazy_reportlab() -> dict[str, Any]:
    from reportlab.lib import colors  # type: ignore
    from reportlab.lib.pagesizes import A4  # type: ignore
    from reportlab.lib.styles import (  # type: ignore
        ParagraphStyle,
        getSampleStyleSheet,
    )
    from reportlab.lib.units import mm  # type: ignore
    from reportlab.platypus import (  # type: ignore
        Image,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    return {
        "colors": colors,
        "A4": A4,
        "ParagraphStyle": ParagraphStyle,
        "getSampleStyleSheet": getSampleStyleSheet,
        "mm": mm,
        "Image": Image,
        "KeepTogether": KeepTogether,
        "Paragraph": Paragraph,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
    }


def _date_fr(d) -> str:
    if d is None:
        return "____________"
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%Y-%m-%d")


def _styles(rl: dict[str, Any]):
    PS = rl["ParagraphStyle"]
    base = rl["getSampleStyleSheet"]()
    colors = rl["colors"]
    dark = colors.HexColor("#111111")
    muted = colors.HexColor("#6b6b6b")
    accent = colors.HexColor("#2f7d32")
    return {
        "title": PS(
            "title",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=dark,
        ),
        "subtitle": PS(
            "subtitle",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=10,
            leading=13,
            textColor=muted,
        ),
        "section": PS(
            "section",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.white,
            backColor=accent,
            leftIndent=4,
            rightIndent=4,
            spaceBefore=8,
            spaceAfter=4,
            borderPadding=4,
        ),
        "body": PS(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=dark,
        ),
        "small": PS(
            "small",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=muted,
        ),
        "legal": PS(
            "legal",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=11,
            textColor=muted,
        ),
    }


async def _load(
    db: AsyncSession, offer_id: int
) -> tuple[Optional[Offer], Optional[ProspectionDeal]]:
    offer = (
        await db.execute(select(Offer).where(Offer.id == offer_id))
    ).scalar_one_or_none()
    if offer is None:
        return None, None
    deal = (
        await db.execute(
            select(ProspectionDeal).where(
                ProspectionDeal.id == offer.deal_id
            )
        )
    ).scalar_one_or_none()
    return offer, deal


def _property_address(deal: Optional[ProspectionDeal]) -> str:
    if deal is None:
        return "____________"
    parts = [deal.address]
    la = deal.lead_analysis
    if la is not None:
        if la.city:
            parts.append(la.city)
        if la.postal_code:
            parts.append(la.postal_code)
    return ", ".join(p for p in parts if p)


def _condition_line(label: str, enabled: bool, delay_days: Optional[int]) -> str:
    mark = "[X]" if enabled else "[ ]"
    if enabled and delay_days is not None:
        return f"{mark} {label} (délai : {delay_days} jours)"
    return f"{mark} {label}"


def _render_bytes(offer: Offer, deal: Optional[ProspectionDeal]) -> bytes:
    rl = _lazy_reportlab()
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Image = rl["Image"]
    mm = rl["mm"]
    colors = rl["colors"]

    buf = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=rl["A4"],
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Offre d'achat {offer.id}",
        author=BUYER_ENTITY_NAME,
    )
    s = _styles(rl)
    story: list = []

    # --- Header ---
    left_block: list = []
    if os.path.exists(_LOGO_PATH):
        try:
            left_block.append(Image(_LOGO_PATH, width=22 * mm, height=22 * mm))
        except Exception:
            pass
    left_block.extend([
        Paragraph(f"<b>{BUYER_ENTITY_NAME}</b>", s["body"]),
        Paragraph(BUYER_ENTITY_ADDRESS, s["small"]),
    ])
    right_block = [
        Paragraph("<b>OFFRE D'ACHAT</b>", s["title"]),
        Paragraph(
            f"Émise le {datetime.utcnow().strftime('%Y-%m-%d')}",
            s["subtitle"],
        ),
    ]
    header = Table([[left_block, right_block]], colWidths=["55%", "45%"])
    header.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ])
    )
    story.append(header)
    story.append(Spacer(1, 10))

    # --- 1. Identification ---
    story.append(Paragraph("1. PARTIES", s["section"]))
    story.append(Paragraph(
        f"<b>Acheteur :</b> {BUYER_ENTITY_NAME}, {BUYER_ENTITY_ADDRESS}",
        s["body"],
    ))
    vendeur_label = (
        offer.vendeur_nom
        if offer.vendeur_nom and offer.vendeur_nom.strip()
        else "Le ou les propriétaires soussignés"
    )
    story.append(Paragraph(
        f"<b>Vendeur :</b> {vendeur_label}",
        s["body"],
    ))

    # --- 2. Objet ---
    story.append(Paragraph("2. PROPRIÉTÉ VISÉE", s["section"]))
    story.append(Paragraph(
        f"L'Acheteur promet d'acheter, aux prix et conditions ci-dessous, "
        f"l'immeuble situé au :",
        s["body"],
    ))
    story.append(Spacer(1, 2))
    story.append(Paragraph(
        f"<b>{_property_address(deal)}</b>",
        s["body"],
    ))

    # --- 3. Prix offert ---
    story.append(Paragraph("3. PRIX OFFERT", s["section"]))
    prix_num = format_money(offer.prix_offert) if offer.prix_offert else "____________"
    prix_lettres = (
        amount_to_french_words(offer.prix_offert)
        if offer.prix_offert
        else "____________"
    )
    story.append(Paragraph(
        f"Le prix d'achat offert est de <b>{prix_num}</b>",
        s["body"],
    ))
    story.append(Paragraph(
        f"<i>(en lettres : {prix_lettres})</i>",
        s["small"],
    ))

    # --- 4. Acompte ---
    story.append(Paragraph("4. ACOMPTE", s["section"]))
    story.append(Paragraph(
        f"Un acompte de <b>{format_money(offer.acompte)}</b> sera versé "
        "en fidéicommis chez le notaire désigné par l'Acheteur, "
        "remboursable si l'une des conditions ci-dessous n'est pas réalisée.",
        s["body"],
    ))

    # --- 5. Prise de possession ---
    story.append(Paragraph("5. PRISE DE POSSESSION", s["section"]))
    story.append(Paragraph(
        f"L'Acheteur prendra possession de l'immeuble le "
        f"<b>{_date_fr(offer.date_possession)}</b>.",
        s["body"],
    ))

    # --- 6. Conditions ---
    story.append(Paragraph("6. CONDITIONS", s["section"]))
    story.append(Paragraph(
        _condition_line(
            "Conditionnelle à une inspection préachat satisfaisante",
            offer.condition_inspection,
            offer.condition_inspection_delai_jours,
        ),
        s["body"],
    ))
    story.append(Paragraph(
        _condition_line(
            "Conditionnelle à l'obtention d'un financement hypothécaire",
            offer.condition_financement,
            offer.condition_financement_delai_jours,
        ),
        s["body"],
    ))
    story.append(Paragraph(
        _condition_line(
            "Conditionnelle à la vente d'une autre propriété par l'Acheteur",
            offer.condition_vente,
            None,
        ),
        s["body"],
    ))

    # --- 7. Inclusions ---
    if offer.inclusions:
        story.append(Paragraph("7. INCLUSIONS", s["section"]))
        story.append(Paragraph(offer.inclusions, s["body"]))

    # --- 8. Délai de réponse ---
    story.append(Paragraph("8. DÉLAI D'ACCEPTATION", s["section"]))
    story.append(Paragraph(
        f"La présente offre est irrévocable jusqu'au "
        f"<b>{_date_fr(offer.date_limite_reponse)}</b> à 23h59. "
        "Passé ce délai sans acceptation, elle devient nulle.",
        s["body"],
    ))

    # --- Signatures ---
    story.append(Spacer(1, 8))
    story.append(Paragraph("SIGNATURES", s["section"]))
    sig_table = Table(
        [
            [
                Paragraph("<b>Acheteur</b>", s["body"]),
                Paragraph("<b>Vendeur</b>", s["body"]),
            ],
            [
                Paragraph(
                    f"{BUYER_ENTITY_NAME}<br/>"
                    f"Signé électroniquement le "
                    f"{datetime.utcnow().strftime('%Y-%m-%d')}",
                    s["small"],
                ),
                Paragraph(
                    (
                        f"Signé par {offer.signed_name} "
                        f"le {_date_fr(offer.signed_at)}"
                        if offer.signed_at
                        else "(en attente de signature)"
                    ),
                    s["small"],
                ),
            ],
        ],
        colWidths=["50%", "50%"],
    )
    sig_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEABOVE", (0, 1), (-1, 1), 0.5, colors.HexColor("#999999")),
            ("TOPPADDING", (0, 1), (-1, 1), 18),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(sig_table)

    # --- Mentions légales ---
    story.append(Spacer(1, 12))
    story.append(Paragraph(LEGAL_NOTICE, s["legal"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Document généré par le portail Horizon le "
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}.",
        s["legal"],
    ))

    doc.build(story)
    return buf.getvalue()


async def render_offer_pdf(db: AsyncSession, offer_id: int) -> bytes:
    offer, deal = await _load(db, offer_id)
    if offer is None:
        raise ValueError(f"Offer {offer_id} introuvable")
    return _render_bytes(offer, deal)
