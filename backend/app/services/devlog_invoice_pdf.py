"""Génère le PDF d'une facture du pôle Développement logiciel.

Facture professionnelle envoyée au client : en-tête (numéro,
émission, échéance), bloc émetteur (Horizon Services Immobiliers),
bloc client, tableau des items (description / qté / prix unitaire /
total), sous-total, TPS (5%), TVQ (9.975%), total final, note de
paiement et coordonnées.

Pas de fuite d'info interne (pas de coûts, marges, taux internes).
Toutes les lignes sont déjà au montant facturable client.

Pattern inspiré de ``app.services.devlog_soumission_pdf`` (PR #473)
et ``app.services.offer_pdf`` (PR #445).
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.devlog_client import DevlogClient
from app.models.devlog_invoice import DevlogInvoice
from app.models.devlog_invoice_item import DevlogInvoiceItem


log = logging.getLogger(__name__)


_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "logo.png",
)


BUYER_ENTITY_NAME = "Horizon Services Immobiliers"
BUYER_ENTITY_TAGLINE = "Pôle Développement logiciel"
BUYER_ADDRESS_LINES = (
    "Montréal, Québec, Canada",
    "comptabilite@immohorizon.com",
)

# Taux de taxes Québec — hardcoded pour l'instant (la valeur change
# très rarement, on n'a pas besoin d'une table de config dédiée).
TPS_RATE = 0.05
TVQ_RATE = 0.09975

PAYMENT_INSTRUCTIONS = (
    "Paiement dû dans les 30 jours suivant la date d'émission. "
    "Modalités acceptées : virement bancaire (Interac e-Transfer "
    "vers comptabilite@immohorizon.com) ou chèque libellé à "
    "« Horizon Services Immobiliers inc. »."
)


def _fmt_money(n: Any) -> str:
    """Format canadien français : « 1 234,56 $ »."""
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{v:,.2f}"
    s = s.replace(",", " ").replace(".", ",")
    return f"{s} $"


def _fmt_date(d: Any) -> str:
    if d is None:
        return "—"
    try:
        return d.strftime("%Y-%m-%d")
    except Exception:
        return str(d)


def compute_invoice_totals(items: list[DevlogInvoiceItem]) -> dict[str, float]:
    """Calcule sous-total, TPS, TVQ et total final."""
    sous_total = round(sum(float(it.total or 0) for it in items), 2)
    tps = round(sous_total * TPS_RATE, 2)
    tvq = round(sous_total * TVQ_RATE, 2)
    total = round(sous_total + tps + tvq, 2)
    return {
        "sous_total": sous_total,
        "tps": tps,
        "tvq": tvq,
        "total": total,
    }


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
        "Paragraph": Paragraph,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
    }


def _styles(rl: dict[str, Any]):
    PS = rl["ParagraphStyle"]
    base = rl["getSampleStyleSheet"]()
    colors = rl["colors"]
    dark = colors.HexColor("#111111")
    muted = colors.HexColor("#6b6b6b")
    accent = colors.HexColor("#1e40af")
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
        "body_bold": PS(
            "body_bold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
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
        "big_amount": PS(
            "big_amount",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=accent,
        ),
    }


async def _load(
    db: AsyncSession, invoice_id: int
) -> tuple[Optional[DevlogInvoice], list[DevlogInvoiceItem], Optional[DevlogClient]]:
    invoice = (
        await db.execute(
            select(DevlogInvoice).where(DevlogInvoice.id == invoice_id)
        )
    ).scalar_one_or_none()
    if invoice is None:
        return None, [], None
    items = list(
        (
            await db.execute(
                select(DevlogInvoiceItem)
                .where(DevlogInvoiceItem.invoice_id == invoice_id)
                .order_by(
                    DevlogInvoiceItem.position.asc(),
                    DevlogInvoiceItem.id.asc(),
                )
            )
        ).scalars().all()
    )
    client: Optional[DevlogClient] = None
    if invoice.client_id is not None:
        client = (
            await db.execute(
                select(DevlogClient).where(DevlogClient.id == invoice.client_id)
            )
        ).scalar_one_or_none()
    return invoice, items, client


def _render_bytes(
    invoice: DevlogInvoice,
    items: list[DevlogInvoiceItem],
    client: Optional[DevlogClient],
) -> bytes:
    rl = _lazy_reportlab()
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Image = rl["Image"]
    mm = rl["mm"]
    colors = rl["colors"]

    totals = compute_invoice_totals(items)

    buf = io.BytesIO()
    invoice_label = invoice.number or f"#{invoice.id}"
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=rl["A4"],
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Facture {invoice_label}",
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
    left_block.append(Paragraph(f"<b>{BUYER_ENTITY_NAME}</b>", s["body"]))
    left_block.append(Paragraph(BUYER_ENTITY_TAGLINE, s["small"]))
    for line in BUYER_ADDRESS_LINES:
        left_block.append(Paragraph(line, s["small"]))

    right_block = [
        Paragraph("<b>FACTURE</b>", s["title"]),
        Paragraph(
            f"N° {invoice_label}",
            s["subtitle"],
        ),
        Paragraph(
            f"Émise le {_fmt_date(invoice.issued_date or datetime.utcnow().date())}",
            s["small"],
        ),
        Paragraph(
            f"Échéance : {_fmt_date(invoice.due_date)}",
            s["small"],
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

    # --- Client ---
    story.append(Paragraph("FACTURÉ À", s["section"]))
    if client is not None:
        client_lines = [client.name]
        if client.company:
            client_lines.append(client.company)
        if client.email:
            client_lines.append(client.email)
        if client.address:
            client_lines.append(client.address)
        for line in client_lines:
            story.append(Paragraph(line, s["body"]))
    else:
        story.append(Paragraph("À confirmer", s["body"]))

    # --- Items ---
    story.append(Paragraph("DÉTAIL DE LA FACTURE", s["section"]))
    rows: list[list[Any]] = []
    rows.append([
        Paragraph("<b>Description</b>", s["body_bold"]),
        Paragraph("<b>Qté</b>", s["body_bold"]),
        Paragraph("<b>Prix unit.</b>", s["body_bold"]),
        Paragraph("<b>Total</b>", s["body_bold"]),
    ])
    if items:
        for it in items:
            desc_parts = [(it.description or "").strip() or "—"]
            if it.unit:
                desc_parts.append(f"<font color='#6b6b6b' size='8'>({it.unit})</font>")
            rows.append([
                Paragraph(" ".join(desc_parts), s["body"]),
                Paragraph(f"{float(it.quantity or 0):g}", s["body"]),
                Paragraph(_fmt_money(it.unit_price), s["body"]),
                Paragraph(_fmt_money(it.total), s["body"]),
            ])
    else:
        rows.append([
            Paragraph("<i>Aucune ligne</i>", s["body"]),
            Paragraph("", s["body"]),
            Paragraph("", s["body"]),
            Paragraph("", s["body"]),
        ])

    items_table = Table(rows, colWidths=["50%", "10%", "20%", "20%"])
    items_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [colors.white, colors.HexColor("#fafafa")],
            ),
        ])
    )
    story.append(items_table)

    # --- Totaux ---
    story.append(Spacer(1, 6))
    totals_rows = [
        [
            Paragraph("Sous-total", s["body"]),
            Paragraph(_fmt_money(totals["sous_total"]), s["body"]),
        ],
        [
            Paragraph(
                f"TPS ({TPS_RATE * 100:.0f} %)", s["body"]
            ),
            Paragraph(_fmt_money(totals["tps"]), s["body"]),
        ],
        [
            Paragraph(
                f"TVQ ({TVQ_RATE * 100:.3f} %)", s["body"]
            ),
            Paragraph(_fmt_money(totals["tvq"]), s["body"]),
        ],
        [
            Paragraph("<b>Total à payer</b>", s["body_bold"]),
            Paragraph(
                f"<b>{_fmt_money(totals['total'])}</b>", s["big_amount"]
            ),
        ],
    ]
    totals_table = Table(totals_rows, colWidths=["70%", "30%"])
    totals_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (0, -1), "RIGHT"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#1e40af")),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eff6ff")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(totals_table)

    # --- Note + paiement ---
    if invoice.notes:
        story.append(Spacer(1, 12))
        story.append(Paragraph("NOTES", s["section"]))
        story.append(Paragraph(invoice.notes, s["body"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph("MODALITÉS DE PAIEMENT", s["section"]))
    story.append(Paragraph(PAYMENT_INSTRUCTIONS, s["body"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f"Document généré par le portail Horizon le "
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}.",
        s["legal"],
    ))

    doc.build(story)
    return buf.getvalue()


async def generate_invoice_pdf(
    db: AsyncSession, invoice_id: int
) -> bytes:
    """Rend le PDF d'une facture du pôle Dev Logiciel."""
    invoice, items, client = await _load(db, invoice_id)
    if invoice is None:
        raise ValueError(f"Facture {invoice_id} introuvable.")
    return _render_bytes(invoice, items, client)
