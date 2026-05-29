"""Generate a PDF for a Soumission using ReportLab.

Pure Python, no system dependencies — safe on Render Free.
"""

from __future__ import annotations

import io
import logging
import os
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact_request import ContactRequest
from app.models.client import Client
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem

log = logging.getLogger(__name__)


# ReportLab is imported lazily inside `_render_bytes` so that the backend
# can start even when the wheel is not yet installed — the PDF endpoints
# simply return an HTTP 500 with a clear error until the deployment
# picks up the new dependency.
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
        "PageBreak": PageBreak,
        "Paragraph": Paragraph,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
    }


_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "logo.png",
)

# Le logo asset (assets/logo.png) est blanc sur fond noir. Sur un PDF
# (fond blanc) ça donne un vilain carré noir. On l'inverse une seule
# fois (noir sur blanc) et on met le résultat en cache mémoire.
# Pillow est dispo en prod (dépendance de reportlab) ; en repli on
# garde le logo source.
_LOGO_LIGHT_CACHE: Optional[bytes] = None
_LOGO_LIGHT_DONE = False


def _logo_light_bytes() -> Optional[bytes]:
    global _LOGO_LIGHT_CACHE, _LOGO_LIGHT_DONE
    if _LOGO_LIGHT_DONE:
        return _LOGO_LIGHT_CACHE
    _LOGO_LIGHT_DONE = True
    if not os.path.exists(_LOGO_PATH):
        return None
    try:
        from PIL import Image as _PILImage, ImageOps  # type: ignore

        img = _PILImage.open(_LOGO_PATH).convert("RGB")
        inverted = ImageOps.invert(img)
        out = io.BytesIO()
        inverted.save(out, format="PNG")
        _LOGO_LIGHT_CACHE = out.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.warning("Logo clair (PDF) non généré, repli logo source : %s", exc)
        _LOGO_LIGHT_CACHE = None
    return _LOGO_LIGHT_CACHE


def _logo_light_source():
    """Source du logo adaptée à un fond blanc (noir sur blanc) pour les
    PDF. Renvoie un BytesIO du logo inversé, le chemin source en repli,
    ou None si l'asset est absent."""
    if not os.path.exists(_LOGO_PATH):
        return None
    data = _logo_light_bytes()
    if data:
        return io.BytesIO(data)
    return _LOGO_PATH


COMPANY_NAME = "Horizon Services Immobiliers"
COMPANY_RBQ = "RBQ 5868-5991-01"
COMPANY_INSURANCE = "Police d'assurance : SUM-CGL-44100-001"
COMPANY_SITE = "immohorizon.com"
COMPANY_EMAIL = "info@immohorizon.com"

ACCENT_HEX = "#d89b3c"
DARK_HEX = "#111111"
MUTED_HEX = "#6b6b6b"
LINE_HEX = "#e2e2e2"


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


async def _load(db: AsyncSession, soumission_id: int):
    sm = (
        await db.execute(
            select(Soumission).where(Soumission.id == soumission_id)
        )
    ).scalar_one_or_none()
    if sm is None:
        return None, [], None, None
    items = list(
        (
            await db.execute(
                select(SoumissionItem)
                .where(SoumissionItem.soumission_id == soumission_id)
                .order_by(SoumissionItem.position.asc(), SoumissionItem.id.asc())
            )
        )
        .scalars()
        .all()
    )
    contact: Optional[ContactRequest] = None
    if sm.contact_request_id:
        contact = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == sm.contact_request_id
                )
            )
        ).scalar_one_or_none()
    # Soumission rattachée à un client existant (post-conversion) : on
    # charge aussi le client pour que l'« Adressée à » affiche son nom
    # (et son représentant) au lieu de « Client à confirmer ».
    client: Optional[Client] = None
    if sm.client_id:
        client = (
            await db.execute(
                select(Client).where(Client.id == sm.client_id)
            )
        ).scalar_one_or_none()
    return sm, items, contact, client


def _styles(rl: dict[str, Any]):
    ParagraphStyle = rl["ParagraphStyle"]
    colors = rl["colors"]
    DARK = colors.HexColor(DARK_HEX)
    MUTED = colors.HexColor(MUTED_HEX)
    ACCENT = colors.HexColor(ACCENT_HEX)
    base = rl["getSampleStyleSheet"]()
    styles = {
        "h1": ParagraphStyle(
            "h1",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=DARK,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=DARK,
            spaceBefore=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=DARK,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=MUTED,
        ),
        "accent": ParagraphStyle(
            "accent",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=ACCENT,
        ),
    }
    return styles


def _render_bytes(
    sm: Soumission,
    items: list[SoumissionItem],
    contact: Optional[ContactRequest],
    client: Optional[Client] = None,
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
    DARK = colors.HexColor(DARK_HEX)
    MUTED = colors.HexColor(MUTED_HEX)
    ACCENT = colors.HexColor(ACCENT_HEX)
    LINE = colors.HexColor(LINE_HEX)

    buf = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=rl["letter"],
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Soumission {sm.reference}",
        author=COMPANY_NAME,
    )
    s = _styles(rl)
    story: list = []

    # Header: logo + company on the left, "SOUMISSION" on the right.
    Image = rl["Image"]
    left_cell: list = []
    _logo_src = _logo_light_source()
    if _logo_src is not None:
        try:
            logo = Image(_logo_src, width=28 * mm, height=28 * mm)
            left_cell.append(logo)
            left_cell.append(Spacer(1, 4))
        except Exception as exc:
            log.warning("Could not embed logo in PDF: %s", exc)
    left_cell.extend([
        Paragraph(f"<b>{COMPANY_NAME}</b>", s["h2"]),
        Paragraph(COMPANY_RBQ, s["small"]),
        Paragraph(COMPANY_INSURANCE, s["small"]),
        Paragraph(
            f"{COMPANY_SITE} &middot; {COMPANY_EMAIL}", s["small"]
        ),
    ])
    # Tax numbers (pulled from QBO CompanyInfo when available).
    if tax_gst:
        left_cell.append(Paragraph(f"TPS : {tax_gst}", s["small"]))
    if tax_qst:
        left_cell.append(Paragraph(f"TVQ : {tax_qst}", s["small"]))

    right_cell: list = [
        Paragraph("SOUMISSION", s["h1"]),
        Paragraph(f"N<sup>o</sup> {sm.reference}", s["accent"]),
        Paragraph(f"Émise le {_date(sm.created_at)}", s["small"]),
    ]
    if sm.valid_until:
        right_cell.append(
            Paragraph(f"Valide jusqu'au {_date(sm.valid_until)}", s["small"])
        )

    header_tbl = Table(
        [[left_cell, right_cell]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
    )
    header_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ]
        )
    )
    story.append(header_tbl)
    story.append(Spacer(1, 14))

    # Client block
    if contact is not None:
        client_lines = [f"<b>{contact.name}</b>"]
        if contact.email:
            client_lines.append(contact.email)
        if contact.phone:
            client_lines.append(contact.phone)
        if contact.address:
            client_lines.append(contact.address)
    elif client is not None:
        client_lines = [f"<b>{client.name}</b>"]
        rep = getattr(client, "representative", None)
        if rep:
            client_lines.append(f"À l'attention de {rep}")
        if client.email:
            client_lines.append(client.email)
        if client.phone:
            client_lines.append(client.phone)
        if client.address:
            client_lines.append(client.address)
    else:
        client_lines = ["<b>Client à confirmer</b>"]
    story.append(Paragraph("ADRESSÉE À", s["accent"]))
    for line in client_lines:
        story.append(Paragraph(line, s["body"]))
    story.append(Spacer(1, 10))

    # Title + description
    story.append(Paragraph(sm.title, s["h2"]))
    if sm.description:
        story.append(Paragraph(sm.description.replace("\n", "<br/>"), s["body"]))
    story.append(Spacer(1, 10))

    # Line items
    data = [["Description", "Qté", "Unité", "Prix unit.", "Total"]]
    for it in items:
        q = float(it.quantity)
        up = float(it.unit_price)
        line_total = (
            float(it.total) if it.total is not None else round(q * up, 2)
        )
        data.append(
            [
                Paragraph(it.description, s["body"]),
                f"{q:g}",
                it.unit or "",
                _money(up),
                _money(line_total),
            ]
        )
    if len(data) == 1:
        data.append(
            [
                Paragraph(
                    "<i>Aucun item — la soumission sera détaillée sur le chantier.</i>",
                    s["small"],
                ),
                "",
                "",
                "",
                "",
            ]
        )

    tbl = Table(
        data,
        colWidths=[
            doc.width * 0.50,
            doc.width * 0.08,
            doc.width * 0.10,
            doc.width * 0.15,
            doc.width * 0.17,
        ],
        repeatRows=1,
    )
    tbl.setStyle(
        TableStyle(
            [
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
            ]
        )
    )
    story.append(tbl)
    story.append(Spacer(1, 10))

    # Totals (right-aligned)
    # Compute totals from the line items at render time. The Soumission
    # row rarely has subtotal/tps/tvq saved because the UI keeps those
    # values live from the items table; using the items here guarantees
    # the PDF is always consistent with what the user is editing.
    computed_subtotal = 0.0
    for it in items:
        if it.total is not None:
            computed_subtotal += float(it.total)
        else:
            computed_subtotal += float(it.quantity) * float(it.unit_price)
    computed_subtotal = round(computed_subtotal, 2)
    computed_tps = round(computed_subtotal * 0.05, 2)
    computed_tvq = round(computed_subtotal * 0.09975, 2)
    computed_total = round(computed_subtotal + computed_tps + computed_tvq, 2)

    totals_rows = [
        ["Sous-total", _money(computed_subtotal)],
        ["TPS (5 %)", _money(computed_tps)],
        ["TVQ (9,975 %)", _money(computed_tvq)],
        ["TOTAL CAD", _money(computed_total)],
    ]
    totals_tbl = Table(totals_rows, colWidths=[doc.width * 0.30, doc.width * 0.20])
    totals_tbl.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("TEXTCOLOR", (0, 0), (-1, -2), MUTED),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, -1), (-1, -1), 11),
                ("TEXTCOLOR", (0, -1), (-1, -1), DARK),
                ("LINEABOVE", (0, -1), (-1, -1), 0.75, DARK),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    totals_wrap = Table(
        [["", totals_tbl]],
        colWidths=[doc.width * 0.50, doc.width * 0.50],
    )
    totals_wrap.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")])
    )
    story.append(totals_wrap)
    story.append(Spacer(1, 18))

    # NB: on ne rend PAS `sm.notes` ici — c'est un champ INTERNE
    # ("Notes privées non visibles par le client") utilisé par
    # l'équipe pour consigner les motifs de refus, la marge voulue,
    # les particularités du chantier, etc. La description publique
    # côté client est `sm.description`, rendue plus haut.

    # Note client-facing (client_note) — utilisé pour des mentions
    # spécifiques à ce devis : modalités de paiement particulières,
    # inclusions/exclusions, délais.
    if getattr(sm, "client_note", None):
        story.append(Paragraph("NOTE", s["accent"]))
        story.append(
            Paragraph(sm.client_note.replace("\n", "<br/>"), s["body"])
        )
        story.append(Spacer(1, 12))

    # Si la soumission est de type ESTIMÉ (pricing_kind="estime"),
    # on insère une clause client-facing qui clarifie que les
    # montants sont estimatifs et peuvent évoluer en cours de
    # projet — avec engagement à tenir le client au courant.
    if getattr(sm, "pricing_kind", "forfaitaire") == "estime":
        story.append(Paragraph("ESTIMÉ — IMPORTANT", s["accent"]))
        story.append(
            Paragraph(
                "Cette soumission est un <b>estimé</b> et non un prix "
                "forfaitaire fixe. Les montants présentés sont basés sur "
                "notre meilleure évaluation des matériaux, de la "
                "main-d'œuvre et des conditions actuellement connues. "
                "Les coûts réels peuvent varier en cours de projet "
                "(découvertes en cours de travaux, ajustements de "
                "matériaux, modifications demandées par le client, "
                "fluctuations des prix fournisseurs, etc.). "
                "Nous nous engageons à <b>tenir le client informé en "
                "continu</b> de l'avancement, des coûts engagés et de "
                "tout écart significatif par rapport à cet estimé, "
                "afin que les décisions soient prises ensemble.",
                s["body"],
            )
        )
        story.append(Spacer(1, 12))

    # Conditions
    story.append(Paragraph("CONDITIONS", s["accent"]))
    story.append(
        Paragraph(
            "Prix valides jusqu'à la date indiquée ci-dessus. "
            "Les taxes TPS (5 %) et TVQ (9,975 %) sont applicables. "
            "L'acceptation de cette soumission constitue le bon de commande. "
            "Le paiement est dû selon les termes convenus à la signature.",
            s["small"],
        )
    )

    story.append(Spacer(1, 16))
    story.append(
        Paragraph(
            f"{COMPANY_NAME} &middot; {COMPANY_RBQ} &middot; "
            f"{COMPANY_INSURANCE} &middot; {COMPANY_EMAIL}",
            s["small"],
        )
    )

    doc.build(story)
    return buf.getvalue()


async def _fetch_tax_numbers() -> tuple[Optional[str], Optional[str]]:
    """Pull TPS/TVQ registration numbers from QBO. Best-effort."""
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


async def render_soumission_pdf(
    db: AsyncSession, soumission_id: int
) -> Optional[tuple[Soumission, bytes]]:
    sm, items, contact, client = await _load(db, soumission_id)
    if sm is None:
        return None
    # Les documents de type « contrat » utilisent le rendu du contrat
    # d'entreprise (sections APCHQ + clauses générales G1-G20). Import
    # tardif : contract_pdf importe ce module → éviterait une boucle.
    if getattr(sm, "kind", "quote") == "contract":
        from app.services.contract_pdf import render_contract_pdf

        return await render_contract_pdf(db, soumission_id)
    gst, qst = await _fetch_tax_numbers()
    pdf = _render_bytes(sm, items, contact, client, tax_gst=gst, tax_qst=qst)
    return sm, pdf
