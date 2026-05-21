"""Génère le PDF d'une Entente de confidentialité (NDA).

Une page A4 — document légal épuré inspiré du flow Offer
d'achat (PR #445), mais avec un thème bleu pour différencier
visuellement les deux types de documents.

Structure :
- Header avec logo Horizon et titre « ENTENTE DE CONFIDENTIALITÉ »
- 1. PARTIES (émetteur / destinataire)
- 2. OBJET (propriété visée + nature des informations)
- 3. ENGAGEMENT (5 engagements numérotés)
- 4. DURÉE (2 ans à compter de la signature)
- 5. JURIDICTION (Québec)
- Bloc signature électronique + mentions légales

ReportLab pur Python — pas de dépendance système, compatible
Render Free comme `offer_pdf.py`.
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.nda import NDA
from app.models.prospection_deal import ProspectionDeal
from app.services.nda_template import (
    ENGAGEMENT_ITEMS,
    ISSUER_ENTITY_ADDRESS,
    ISSUER_ENTITY_NAME,
    LEGAL_NOTICE,
    NDA_DURATION_YEARS,
    NDA_JURISDICTION,
    format_property_address,
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
    # Bleu Horizon — distingue visuellement le NDA de l'Offre d'achat
    # (qui utilise un vert #2f7d32).
    accent = colors.HexColor("#1d4ed8")
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
    db: AsyncSession, nda_id: int
) -> tuple[Optional[NDA], Optional[ProspectionDeal]]:
    nda = (
        await db.execute(select(NDA).where(NDA.id == nda_id))
    ).scalar_one_or_none()
    if nda is None:
        return None, None
    deal = (
        await db.execute(
            select(ProspectionDeal).where(
                ProspectionDeal.id == nda.deal_id
            )
        )
    ).scalar_one_or_none()
    return nda, deal


def _property_address(deal: Optional[ProspectionDeal]) -> str:
    if deal is None:
        return "____________"
    la = deal.lead_analysis
    return format_property_address(
        deal.address,
        la.city if la is not None else None,
        la.postal_code if la is not None else None,
    )


def _render_bytes(nda: NDA, deal: Optional[ProspectionDeal]) -> bytes:
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
        title=f"Entente de confidentialité {nda.id}",
        author=ISSUER_ENTITY_NAME,
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
        Paragraph(f"<b>{ISSUER_ENTITY_NAME}</b>", s["body"]),
        Paragraph(ISSUER_ENTITY_ADDRESS, s["small"]),
    ])
    right_block = [
        Paragraph("<b>ENTENTE DE CONFIDENTIALITÉ</b>", s["title"]),
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

    # --- 1. Parties ---
    story.append(Paragraph("1. PARTIES", s["section"]))
    story.append(Paragraph(
        f"<b>Émetteur :</b> {ISSUER_ENTITY_NAME}, "
        f"{ISSUER_ENTITY_ADDRESS}",
        s["body"],
    ))
    destinataire = (
        nda.investor_name.strip()
        if nda.investor_name and nda.investor_name.strip()
        else "Le destinataire soussigné"
    )
    story.append(Paragraph(
        f"<b>Destinataire :</b> {destinataire}",
        s["body"],
    ))

    # --- 2. Objet ---
    story.append(Paragraph("2. OBJET", s["section"]))
    story.append(Paragraph(
        "L'Émetteur s'apprête à transmettre au Destinataire des "
        "informations confidentielles concernant la propriété "
        f"située au :",
        s["body"],
    ))
    story.append(Spacer(1, 2))
    story.append(Paragraph(
        f"<b>{_property_address(deal)}</b>",
        s["body"],
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "(la « Propriété »), notamment des analyses financières, "
        "des données locatives, des évaluations et des stratégies "
        "de mise en valeur.",
        s["body"],
    ))

    # --- 3. Engagement ---
    story.append(Paragraph("3. ENGAGEMENT", s["section"]))
    story.append(Paragraph(
        "Le Destinataire s'engage à :", s["body"]
    ))
    story.append(Spacer(1, 2))
    for i, item in enumerate(ENGAGEMENT_ITEMS, start=1):
        story.append(Paragraph(
            f"<b>{i}.</b> {item}",
            s["body"],
        ))

    # --- 4. Durée ---
    story.append(Paragraph("4. DURÉE", s["section"]))
    duree_lettres = "deux" if NDA_DURATION_YEARS == 2 else str(NDA_DURATION_YEARS)
    story.append(Paragraph(
        f"La présente entente lie le Destinataire pour une période "
        f"de <b>{duree_lettres} ({NDA_DURATION_YEARS}) ans</b> à "
        "compter de la date de signature, peu importe que "
        "l'investissement envisagé ait lieu ou non.",
        s["body"],
    ))

    # --- 5. Juridiction ---
    story.append(Paragraph("5. JURIDICTION", s["section"]))
    story.append(Paragraph(
        f"Les tribunaux du <b>{NDA_JURISDICTION}</b> ont juridiction "
        "exclusive sur tout litige découlant de la présente "
        f"entente. Le droit applicable est celui du "
        f"{NDA_JURISDICTION}.",
        s["body"],
    ))

    # --- Signatures ---
    story.append(Spacer(1, 8))
    story.append(Paragraph("SIGNATURE", s["section"]))
    sig_table = Table(
        [
            [
                Paragraph("<b>Émetteur</b>", s["body"]),
                Paragraph("<b>Destinataire</b>", s["body"]),
            ],
            [
                Paragraph(
                    f"{ISSUER_ENTITY_NAME}<br/>"
                    f"Signé électroniquement le "
                    f"{datetime.utcnow().strftime('%Y-%m-%d')}",
                    s["small"],
                ),
                Paragraph(
                    (
                        f"Signé par {nda.signed_name} "
                        f"le {_date_fr(nda.signed_at)}"
                        if nda.signed_at
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


async def render_nda_pdf(db: AsyncSession, nda_id: int) -> bytes:
    nda, deal = await _load(db, nda_id)
    if nda is None:
        raise ValueError(f"NDA {nda_id} introuvable")
    return _render_bytes(nda, deal)
