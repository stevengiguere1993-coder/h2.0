"""Render a MeasurementSnapshot as a printable PDF — label, type,
aire, valeurs du relevé (cuisine/SDB/…), notes, et miniatures des
photos attachées.

reportlab est déjà une dépendance du projet (utilisée pour les
factures/soumissions). On fait un layout simple et compact, pas une
œuvre d'art — l'objectif est de pouvoir remettre une copie au client
ou au sous-traitant.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.contact_request import ContactRequest
from app.models.measurement import MeasurementSnapshot
from app.models.measurement_photo import MeasurementPhoto


log = logging.getLogger(__name__)


# Human-readable labels for the template types. Kept separate from the
# frontend catalog so the PDF renders nicely even if we reorg things
# later.
_TEMPLATE_LABELS = {
    "cuisine": "Cuisine",
    "salle_bain": "Salle de bain",
    "sous_sol": "Sous-sol complet",
    "multilogement": "Multilogement",
    "renovation_complete": "Rénovation complète",
}


def _readable_key(key: str) -> str:
    return key.replace("_", " ").capitalize()


async def render_measurement_pdf(
    db: AsyncSession, m: MeasurementSnapshot
) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        Image,
        PageBreak,
    )

    # Load side data: client / prospect + photos metadata (blobs loaded
    # lazily below when a photo actually needs to be drawn).
    client: Optional[Client] = None
    prospect: Optional[ContactRequest] = None
    if m.client_id:
        client = (
            await db.execute(select(Client).where(Client.id == m.client_id))
        ).scalar_one_or_none()
    if m.contact_request_id:
        prospect = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == m.contact_request_id
                )
            )
        ).scalar_one_or_none()
    photos = (
        await db.execute(
            select(MeasurementPhoto)
            .where(MeasurementPhoto.measurement_id == m.id)
            .order_by(MeasurementPhoto.created_at.asc())
        )
    ).scalars().all()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=f"Relevé {m.id}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        fontSize=18,
        spaceAfter=6,
        textColor=colors.HexColor("#0b0d10"),
    )
    meta_style = ParagraphStyle(
        "Meta",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#555555"),
    )
    body_style = styles["Normal"]

    story: list = []

    # Header
    story.append(
        Paragraph(
            "Horizon Services Immobiliers — Relevé de mesures",
            ParagraphStyle(
                "Eyebrow",
                parent=styles["Normal"],
                fontSize=9,
                textColor=colors.HexColor("#d89b3c"),
                spaceAfter=4,
            ),
        )
    )
    story.append(Paragraph(m.label, title_style))

    # Meta line (client / prospect / date / address)
    meta_bits: list[str] = []
    if client:
        meta_bits.append(f"<b>Client :</b> {client.name}")
    if prospect:
        meta_bits.append(f"<b>Prospect :</b> {prospect.name}")
    if m.address:
        meta_bits.append(f"<b>Adresse :</b> {m.address}")
    captured = (
        m.captured_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        if m.captured_at
        else "—"
    )
    meta_bits.append(f"<b>Relevé :</b> {captured}")
    kind_label = {
        "horizontal": "Polygone horizontal",
        "vertical": "Mur (polygone × hauteur)",
        "checklist": _TEMPLATE_LABELS.get(
            m.template_type or "", "Relevé structuré"
        ),
    }.get(m.kind, m.kind)
    meta_bits.append(f"<b>Type :</b> {kind_label}")
    story.append(Paragraph(" &nbsp;·&nbsp; ".join(meta_bits), meta_style))
    story.append(Spacer(1, 14))

    # Main values block
    data_rows: list[list[str]] = []
    if m.area_ft2 and float(m.area_ft2) > 0:
        data_rows.append(["Aire", f"{float(m.area_ft2):,.2f} ft²"])
    if m.perimeter_ft and float(m.perimeter_ft) > 0:
        data_rows.append(["Périmètre", f"{float(m.perimeter_ft):,.2f} ft"])
    if m.wall_height_ft:
        data_rows.append(
            ["Hauteur de mur", f"{float(m.wall_height_ft):,.2f} ft"]
        )

    # Checklist fields, rendered key → value
    if m.template_data_json:
        try:
            data = json.loads(m.template_data_json)
            if isinstance(data, dict):
                for k, v in data.items():
                    if v is None or v == "":
                        continue
                    if isinstance(v, bool):
                        v = "Oui" if v else "Non"
                    data_rows.append([_readable_key(k), str(v)])
        except Exception:
            pass

    if data_rows:
        tbl = Table(data_rows, colWidths=[2.2 * inch, 4.2 * inch])
        tbl.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                    ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#0b0d10")),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    (
                        "LINEBELOW",
                        (0, 0),
                        (-1, -2),
                        0.3,
                        colors.HexColor("#e5e5e5"),
                    ),
                ]
            )
        )
        story.append(tbl)
        story.append(Spacer(1, 14))

    if m.notes:
        story.append(Paragraph("<b>Notes</b>", body_style))
        story.append(Spacer(1, 4))
        story.append(Paragraph(m.notes.replace("\n", "<br/>"), body_style))
        story.append(Spacer(1, 14))

    # Photos (up to 6, 2 per row)
    if photos:
        story.append(Paragraph("<b>Photos</b>", body_style))
        story.append(Spacer(1, 6))
        rendered_cells: list[list] = []
        row: list = []
        for p in photos[:6]:
            await db.refresh(p, attribute_names=["image"])
            if not p.image:
                continue
            try:
                img = Image(io.BytesIO(bytes(p.image)))
                img.drawWidth = 3.1 * inch
                img.drawHeight = 2.3 * inch
                cell = [img]
                if p.caption:
                    cell.append(
                        Paragraph(
                            p.caption,
                            ParagraphStyle(
                                "Cap",
                                parent=body_style,
                                fontSize=8,
                                textColor=colors.HexColor("#666666"),
                                spaceBefore=2,
                            ),
                        )
                    )
                row.append(cell)
                if len(row) == 2:
                    rendered_cells.append(row)
                    row = []
            except Exception as exc:
                log.warning("PDF photo render failed: %s", exc)
        if row:
            # pad the last row to 2 columns
            row.append("")
            rendered_cells.append(row)
        if rendered_cells:
            photo_tbl = Table(
                rendered_cells, colWidths=[3.3 * inch, 3.3 * inch]
            )
            photo_tbl.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ]
                )
            )
            story.append(photo_tbl)

    # Footer
    story.append(Spacer(1, 24))
    story.append(
        Paragraph(
            "Horizon Services Immobiliers &nbsp;·&nbsp; RBQ 5868-5991-01 "
            "&nbsp;·&nbsp; info@immohorizon.com",
            ParagraphStyle(
                "Footer",
                parent=meta_style,
                alignment=1,
                textColor=colors.HexColor("#888888"),
            ),
        )
    )

    doc.build(story)
    return buffer.getvalue()
