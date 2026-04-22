"""Generate a PDF for a Facture — mirrors soumission_pdf layout with
the word FACTURE and an optional due date / balance block."""

from __future__ import annotations

import io
import logging
import os
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.facture import Facture
from app.models.facture_item import FactureItem
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


def _date(d: Optional[datetime | date]) -> str:
    if d is None:
        return "—"
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%Y-%m-%d")


async def _load(db: AsyncSession, facture_id: int):
    fa = (
        await db.execute(select(Facture).where(Facture.id == facture_id))
    ).scalar_one_or_none()
    if fa is None:
        return None, [], None
    items = list(
        (
            await db.execute(
                select(FactureItem)
                .where(FactureItem.facture_id == facture_id)
                .order_by(FactureItem.position.asc(), FactureItem.id.asc())
            )
        )
        .scalars()
        .all()
    )
    client: Optional[Client] = None
    if fa.client_id:
        client = (
            await db.execute(select(Client).where(Client.id == fa.client_id))
        ).scalar_one_or_none()
    return fa, items, client


def _render_bytes(
    fa: Facture,
    items: list[FactureItem],
    client: Optional[Client],
    *,
    tax_gst: Optional[str] = None,
    tax_qst: Optional[str] = None,
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
        title=f"Facture {fa.reference}", author=COMPANY_NAME,
    )
    story: list = []

    left_cell: list = []
    if os.path.exists(_LOGO_PATH):
        try:
            logo = Image(_LOGO_PATH, width=28 * mm, height=28 * mm)
            left_cell.append(logo)
            left_cell.append(Spacer(1, 4))
        except Exception as exc:
            log.warning("Could not embed logo in PDF: %s", exc)
    left_cell.extend([
        Paragraph(f"<b>{COMPANY_NAME}</b>", s["h2"]),
        Paragraph(COMPANY_RBQ, s["small"]),
        Paragraph(f"{COMPANY_SITE} &middot; {COMPANY_EMAIL}", s["small"]),
    ])
    if tax_gst:
        left_cell.append(Paragraph(f"TPS : {tax_gst}", s["small"]))
    if tax_qst:
        left_cell.append(Paragraph(f"TVQ : {tax_qst}", s["small"]))

    right_cell: list = [
        Paragraph("FACTURE", s["h1"]),
        Paragraph(f"N<sup>o</sup> {fa.reference}", s["accent"]),
        Paragraph(f"Émise le {_date(fa.issued_at or fa.created_at)}", s["small"]),
    ]
    if fa.due_at:
        right_cell.append(
            Paragraph(f"Échéance : {_date(fa.due_at)}", s["small"])
        )

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
    story.append(Paragraph("FACTURÉ À", s["accent"]))
    for line in lines:
        story.append(Paragraph(line, s["body"]))
    story.append(Spacer(1, 10))

    # Items
    data = [["Description", "Qté", "Unité", "Prix unit.", "Total"]]
    subtotal = 0.0
    for it in items:
        q = float(it.quantity)
        up = float(it.unit_price)
        line_total = float(it.total) if it.total is not None else round(q * up, 2)
        subtotal += line_total
        data.append([
            Paragraph(it.description, s["body"]),
            f"{q:g}", it.unit or "",
            _money(up), _money(line_total),
        ])
    if len(data) == 1:
        data.append([
            Paragraph("<i>Aucun item.</i>", s["small"]),
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

    subtotal = round(subtotal, 2)
    tps = round(subtotal * 0.05, 2)
    tvq = round(subtotal * 0.09975, 2)
    total = round(subtotal + tps + tvq, 2)
    balance = float(fa.balance) if fa.balance is not None else total

    totals_rows = [
        ["Sous-total", _money(subtotal)],
        ["TPS (5 %)", _money(tps)],
        ["TVQ (9,975 %)", _money(tvq)],
        ["TOTAL CAD", _money(total)],
    ]
    if balance != total:
        totals_rows.append(["Solde dû", _money(balance)])

    totals_tbl = Table(totals_rows, colWidths=[doc.width * 0.30, doc.width * 0.20])
    totals_tbl.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, -2), MUTED),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 11),
        ("TEXTCOLOR", (0, -1), (-1, -1), DARK),
        ("LINEABOVE", (0, -1), (-1, -1), 0.75, DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    totals_wrap = Table(
        [["", totals_tbl]],
        colWidths=[doc.width * 0.50, doc.width * 0.50],
    )
    totals_wrap.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(totals_wrap)
    story.append(Spacer(1, 18))

    # Note client-facing (facultative) — mention libre à afficher sur
    # la facture (ex. « Merci pour votre confiance », « Paiement net
    # 15 jours », référence interne du client). Ne PAS confondre avec
    # internal_notes qui restent côté admin.
    client_note = getattr(fa, "client_note", None)
    if client_note:
        story.append(Paragraph("NOTE", s["accent"]))
        story.append(
            Paragraph(client_note.replace("\n", "<br/>"), s["body"])
        )
        story.append(Spacer(1, 12))

    story.append(Paragraph("MODALITÉS DE PAIEMENT", s["accent"]))
    story.append(Paragraph(
        "Les taxes TPS (5 %) et TVQ (9,975 %) sont applicables. "
        "Paiement dû à la date d'échéance indiquée ci-dessus. Les "
        "virements bancaires (Interac) et chèques à l'ordre de "
        f"{COMPANY_NAME} sont acceptés. Pour toute question, contacte-"
        "nous à info@immohorizon.com.", s["small"],
    ))
    story.append(Spacer(1, 16))
    story.append(Paragraph(
        f"{COMPANY_NAME} &middot; {COMPANY_RBQ} &middot; {COMPANY_EMAIL}",
        s["small"],
    ))

    doc.build(story)
    return buf.getvalue()


async def _fetch_tax_numbers() -> tuple[Optional[str], Optional[str]]:
    try:
        from app.integrations.quickbooks import get_qbo
        qbo = get_qbo()
        if not qbo.ready:
            return None, None
        nums = await qbo.tax_registration_numbers()
        return nums.get("gst"), nums.get("qst")
    except Exception as exc:
        log.warning("Could not fetch QBO tax numbers: %s", exc)
        return None, None


async def render_facture_pdf(
    db: AsyncSession, facture_id: int
) -> Optional[tuple[Facture, bytes]]:
    fa, items, client = await _load(db, facture_id)
    if fa is None:
        return None
    gst, qst = await _fetch_tax_numbers()
    pdf = _render_bytes(fa, items, client, tax_gst=gst, tax_qst=qst)
    return fa, pdf
