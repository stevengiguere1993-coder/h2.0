"""PDF generator for a BonTravail (work order)."""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bon_item import BonItem
from app.models.bon_travail import BonTravail
from app.models.client import Client
from app.services.soumission_pdf import (
    ACCENT_HEX,
    COMPANY_EMAIL,
    COMPANY_NAME,
    COMPANY_RBQ,
    COMPANY_SITE,
    DARK_HEX,
    LINE_HEX,
    MUTED_HEX,
    _lazy_reportlab,
)

log = logging.getLogger(__name__)

_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "logo.png",
)


def _money(n: Optional[float | int]) -> str:
    if n is None:
        return "—"
    return f"{float(n):,.2f} $".replace(",", " ")


async def _load(db: AsyncSession, bon_id: int):
    bon = (
        await db.execute(select(BonTravail).where(BonTravail.id == bon_id))
    ).scalar_one_or_none()
    if bon is None:
        return None, [], None
    items = list(
        (
            await db.execute(
                select(BonItem)
                .where(BonItem.bon_id == bon_id)
                .order_by(BonItem.position.asc(), BonItem.id.asc())
            )
        ).scalars().all()
    )
    client: Optional[Client] = None
    if bon.client_id:
        client = (
            await db.execute(select(Client).where(Client.id == bon.client_id))
        ).scalar_one_or_none()
    return bon, items, client


def _render_bytes(
    bon: BonTravail, items: list[BonItem], client: Optional[Client]
) -> bytes:
    rl = _lazy_reportlab()
    colors = rl["colors"]
    mm = rl["mm"]
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Image = rl["Image"]
    DARK = colors.HexColor(DARK_HEX)
    MUTED = colors.HexColor(MUTED_HEX)
    ACCENT = colors.HexColor(ACCENT_HEX)
    LINE = colors.HexColor(LINE_HEX)

    ParagraphStyle = rl["ParagraphStyle"]
    base = rl["getSampleStyleSheet"]()
    s = {
        "h1": ParagraphStyle(
            "h1", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=22, leading=26, textColor=DARK,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=11, leading=14, textColor=DARK, spaceBefore=6,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontName="Helvetica",
            fontSize=10, leading=13, textColor=DARK,
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.5, leading=11, textColor=MUTED,
        ),
        "accent": ParagraphStyle(
            "accent", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=9, leading=12, textColor=ACCENT,
        ),
    }

    buf = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buf, pagesize=rl["letter"],
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Bon {bon.reference}", author=COMPANY_NAME,
    )
    story: list = []

    left_cell: list = []
    if os.path.exists(_LOGO_PATH):
        try:
            logo = Image(_LOGO_PATH, width=28 * mm, height=28 * mm)
            left_cell.append(logo)
            left_cell.append(Spacer(1, 4))
        except Exception as exc:
            log.warning("Could not embed logo: %s", exc)
    left_cell.extend([
        Paragraph(f"<b>{COMPANY_NAME}</b>", s["h2"]),
        Paragraph(COMPANY_RBQ, s["small"]),
        Paragraph(f"{COMPANY_SITE} &middot; {COMPANY_EMAIL}", s["small"]),
    ])

    right_cell: list = [
        Paragraph("BON DE TRAVAIL", s["h1"]),
        Paragraph(f"N<sup>o</sup> {bon.reference}", s["accent"]),
        Paragraph(f"Émis le {datetime.now().strftime('%Y-%m-%d')}", s["small"]),
    ]

    header_tbl = Table(
        [[left_cell, right_cell]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
    )
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 14))

    if client is not None:
        lines = [f"<b>{client.name}</b>"]
        if client.email: lines.append(client.email)
        if client.phone: lines.append(client.phone)
        if client.address: lines.append(client.address)
    else:
        lines = ["<b>Client</b>"]
    story.append(Paragraph("ADRESSÉ À", s["accent"]))
    for line in lines:
        story.append(Paragraph(line, s["body"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph(bon.title, s["h2"]))
    if bon.description:
        story.append(Paragraph(bon.description.replace("\n", "<br/>"), s["body"]))
    if bon.scope_md:
        story.append(Spacer(1, 6))
        story.append(Paragraph("PORTÉE DES TRAVAUX", s["accent"]))
        story.append(Paragraph(bon.scope_md.replace("\n", "<br/>"), s["body"]))
    story.append(Spacer(1, 10))

    data = [["Description", "Qté", "Unité", "Prix unit.", "Total"]]
    subtotal = 0.0
    for it in items:
        q = float(it.quantity)
        up = float(it.unit_price)
        line_total = (
            float(it.total) if it.total is not None else round(q * up, 2)
        )
        subtotal += line_total
        data.append([
            Paragraph(it.description, s["body"]),
            f"{q:g}", it.unit or "",
            _money(up), _money(line_total),
        ])
    if len(data) == 1:
        data.append([
            Paragraph("<i>Voir la description ci-dessus.</i>", s["small"]),
            "", "", "", "",
        ])

    tbl = Table(
        data,
        colWidths=[
            doc.width * 0.50, doc.width * 0.08, doc.width * 0.10,
            doc.width * 0.15, doc.width * 0.17,
        ],
        repeatRows=1,
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, ACCENT),
        ("LINEABOVE", (0, -1), (-1, -1), 0.25, LINE),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 10))

    # Bon total may be the manually-set amount on the bon, or the
    # sum of items when items are present.
    shown_total = round(subtotal, 2) if items else (
        float(bon.amount) if bon.amount is not None else 0.0
    )
    totals_rows = [["MONTANT CAD", _money(shown_total)]]
    totals_tbl = Table(totals_rows, colWidths=[doc.width * 0.30, doc.width * 0.20])
    totals_tbl.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, -1), (-1, -1), 11),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, -1), (-1, -1), DARK),
        ("LINEABOVE", (0, -1), (-1, -1), 0.75, DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    wrap = Table(
        [["", totals_tbl]],
        colWidths=[doc.width * 0.50, doc.width * 0.50],
    )
    wrap.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(wrap)
    story.append(Spacer(1, 18))

    # Signature block
    story.append(Paragraph("ACCEPTATION CLIENT", s["accent"]))
    if bon.signed_by_name and bon.signed_at:
        story.append(Paragraph(
            f"Signé électroniquement par <b>{bon.signed_by_name}</b> le "
            f"{bon.signed_at.strftime('%Y-%m-%d %H:%M %Z')}.",
            s["body"],
        ))
    else:
        story.append(Paragraph(
            "En signant ce bon de travail, le client autorise l'exécution "
            "des travaux décrits pour le montant indiqué ci-dessus.",
            s["small"],
        ))
        story.append(Spacer(1, 24))
        story.append(Paragraph(
            "X ______________________________________", s["body"]
        ))
        story.append(Paragraph(
            "Signature du client — nom en lettres moulées + date",
            s["small"],
        ))

    story.append(Spacer(1, 16))
    story.append(Paragraph(
        f"{COMPANY_NAME} &middot; {COMPANY_RBQ} &middot; {COMPANY_EMAIL}",
        s["small"],
    ))

    doc.build(story)
    return buf.getvalue()


async def render_bon_pdf(
    db: AsyncSession, bon_id: int
) -> Optional[tuple[BonTravail, bytes]]:
    bon, items, client = await _load(db, bon_id)
    if bon is None:
        return None
    pdf = _render_bytes(bon, items, client)
    return bon, pdf
