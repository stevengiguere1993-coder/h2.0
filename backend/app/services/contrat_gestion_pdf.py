"""PDF de la Convention de gestion immobilière (ReportLab, pur Python).

Rend le corps markdown (titres `#`/`##`, gras `**`, listes `-`) en
flowables, puis ajoute les blocs de signature (Mandataire pré-rempli,
Mandant, Caution solidaire). La variante signée remplit le bloc Mandant
avec le nom + la date + l'image de signature et appose un bandeau
emerald plein largeur en haut de la 1re page (horodatage + IP + hash).

Réutilise les helpers partagés de `soumission_pdf` (logo clair, palette).
"""

from __future__ import annotations

import html as _html
import io
import logging
import re
from datetime import datetime
from typing import Any, Optional

from app.models.contrat_gestion import ContratGestion
from app.services.contrat_gestion_template import (
    MANDATAIRE_NOM,
    MANDATAIRE_REPRESENTANT,
    MANDATAIRE_TITRE,
)
from app.services.soumission_pdf import (
    ACCENT_HEX,
    COMPANY_EMAIL,
    COMPANY_NAME,
    DARK_HEX,
    LINE_HEX,
    MUTED_HEX,
    _lazy_reportlab,
    _logo_light_source,
)

log = logging.getLogger(__name__)


_MONTHS_FR_CA = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def _date_fr_ca_long(d: Optional[datetime]) -> str:
    if d is None:
        return ""
    dd = d.date() if isinstance(d, datetime) else d
    return f"{dd.day} {_MONTHS_FR_CA[dd.month - 1]} {dd.year}"


def _inline_markup(text_value: str) -> str:
    """Échappe le HTML puis convertit `**gras**` → <b>gras</b>."""
    escaped = _html.escape(text_value or "")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)


def _styles(rl: dict[str, Any]):
    ParagraphStyle = rl["ParagraphStyle"]
    styles = rl["getSampleStyleSheet"]()
    base = styles["Normal"]
    return {
        "title": ParagraphStyle(
            "cg_title", parent=base, fontName="Helvetica-Bold",
            fontSize=15, leading=19, spaceAfter=10, textColor=rl["colors"].HexColor(DARK_HEX),
        ),
        "h2": ParagraphStyle(
            "cg_h2", parent=base, fontName="Helvetica-Bold",
            fontSize=11, leading=14, spaceBefore=12, spaceAfter=5,
            textColor=rl["colors"].HexColor(ACCENT_HEX),
        ),
        "body": ParagraphStyle(
            "cg_body", parent=base, fontName="Helvetica",
            fontSize=8.6, leading=12.4, spaceAfter=5,
            textColor=rl["colors"].HexColor(DARK_HEX), alignment=4,  # justify
        ),
        "bullet": ParagraphStyle(
            "cg_bullet", parent=base, fontName="Helvetica",
            fontSize=8.6, leading=12.4, spaceAfter=2, leftIndent=14,
            bulletIndent=4, textColor=rl["colors"].HexColor(DARK_HEX),
        ),
        "sig_label": ParagraphStyle(
            "cg_sig_label", parent=base, fontName="Helvetica-Bold",
            fontSize=8, leading=11, textColor=rl["colors"].HexColor(DARK_HEX),
        ),
        "sig_small": ParagraphStyle(
            "cg_sig_small", parent=base, fontName="Helvetica",
            fontSize=7.5, leading=10, textColor=rl["colors"].HexColor(MUTED_HEX),
        ),
    }


def _body_flowables(rl: dict[str, Any], st: dict[str, Any], body_md: str) -> list:
    """Convertit le markdown simplifié en flowables ReportLab."""
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    mm = rl["mm"]
    flow: list = []
    for raw in body_md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flow.append(Spacer(1, 3))
            continue
        if line.startswith("## "):
            flow.append(Paragraph(_inline_markup(line[3:]), st["h2"]))
        elif line.startswith("# "):
            flow.append(Paragraph(_inline_markup(line[2:]), st["title"]))
        elif line.startswith("- "):
            flow.append(
                Paragraph(_inline_markup(line[2:]), st["bullet"], bulletText="•")
            )
        else:
            flow.append(Paragraph(_inline_markup(line), st["body"]))
    del mm
    return flow


def _signature_image_flowable(
    rl: dict[str, Any], contrat: ContratGestion, attr: str = "signature_image"
):
    """Renvoie une Image reportlab d'une signature manuscrite, ou None."""
    blob = getattr(contrat, attr, None)
    if not blob:
        return None
    try:
        from PIL import Image as _PILImage  # type: ignore

        img = _PILImage.open(io.BytesIO(blob))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        mm = rl["mm"]
        # Ratio préservé, hauteur bornée.
        ratio = (img.width / img.height) if img.height else 3.0
        h = 14 * mm
        w = min(h * ratio, 60 * mm)
        return rl["Image"](buf, width=w, height=h)
    except Exception:
        log.exception("[CG_PDF] Image de signature illisible (contrat %s)", contrat.id)
        return None


def _signature_block(
    rl: dict[str, Any], st: dict[str, Any], contrat: ContratGestion
) -> list:
    """Blocs de signature : Mandataire (pré-rempli) + Mandant (+ Caution)."""
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    colors = rl["colors"]
    mm = rl["mm"]

    # État de chaque signataire (flux à deux signatures).
    mandant_signed = bool(contrat.signed_at)
    mandant_name = (contrat.signed_name or contrat.representant_nom or "").strip()
    mandant_date = _date_fr_ca_long(contrat.signed_at) if mandant_signed else ""
    mandant_img = (
        _signature_image_flowable(rl, contrat, "signature_image")
        if mandant_signed
        else None
    )

    mgv_signed = bool(contrat.mandataire_signed_at)
    mgv_name = (
        contrat.mandataire_signed_name or contrat.mandataire_nom
        or MANDATAIRE_REPRESENTANT
    ).strip()
    mgv_date = _date_fr_ca_long(contrat.mandataire_signed_at) if mgv_signed else ""
    mgv_img = (
        _signature_image_flowable(rl, contrat, "mandataire_signature_image")
        if mgv_signed
        else None
    )

    line = "_______________________________"

    def party(
        role: str, name: str, title: str, is_signed: bool, date: str, img
    ) -> list:
        cell: list = [Paragraph(role, st["sig_label"]), Spacer(1, 12)]
        if is_signed:
            if img is not None:
                cell.append(img)
            cell.append(Paragraph("<b>Signée électroniquement</b>", st["sig_small"]))
            cell.append(Paragraph(_html.escape(name), st["sig_label"]))
            if title:
                cell.append(Paragraph(_html.escape(title), st["sig_small"]))
            cell.append(Paragraph(f"Le {date}", st["sig_small"]))
        else:
            cell.append(Paragraph(line, st["sig_small"]))
            cell.append(Paragraph(_html.escape(name) if name else "&nbsp;", st["sig_label"]))
            if title:
                cell.append(Paragraph(_html.escape(title), st["sig_small"]))
            cell.append(Paragraph("Date : _______________", st["sig_small"]))
        return cell

    left = party(
        "LE MANDATAIRE", mgv_name, MANDATAIRE_TITRE, mgv_signed, mgv_date, mgv_img
    )
    right = party(
        "LE MANDANT",
        contrat.representant_nom or "",
        contrat.representant_titre or "",
        mandant_signed,
        mandant_date,
        mandant_img,
    )

    tbl = Table([[left, right]], colWidths=[85 * mm, 85 * mm])
    tbl.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ])
    )

    flow: list = [Spacer(1, 10 * mm), tbl]

    if contrat.caution_requise:
        caution_name = (contrat.caution_nom or mandant_name or "").strip()
        flow.append(Spacer(1, 8 * mm))
        flow.append(Paragraph("CAUTIONNEMENT SOLIDAIRE", st["h2"]))
        flow.append(Paragraph(
            "Je, soussigné, m'engage solidairement avec le Mandant à "
            "respecter toutes et chacune des obligations contenues aux "
            "présentes et renonce à cette fin aux bénéfices de division "
            "et de discussion. Le présent cautionnement solidaire n'est "
            "pas attaché à l'exercice de fonctions particulières au sein "
            "du Mandant.",
            st["body"],
        ))
        caution_cell: list = [
            Paragraph("Caution solidaire", st["sig_label"]), Spacer(1, 10)
        ]
        if mandant_signed:
            caution_img = _signature_image_flowable(
                rl, contrat, "signature_image"
            )
            if caution_img is not None:
                caution_cell.append(caution_img)
            caution_cell.append(Paragraph("<b>Signée électroniquement</b>", st["sig_small"]))
            caution_cell.append(Paragraph(_html.escape(caution_name), st["sig_label"]))
            caution_cell.append(Paragraph(f"Le {mandant_date}", st["sig_small"]))
        else:
            caution_cell.append(Paragraph(line, st["sig_small"]))
            caution_cell.append(
                Paragraph(_html.escape(caution_name) if caution_name else "&nbsp;", st["sig_label"])
            )
        ctbl = Table([[caution_cell]], colWidths=[110 * mm])
        ctbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(LINE_HEX)),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]))
        flow.append(Spacer(1, 4 * mm))
        flow.append(ctbl)

    return flow


def _header_footer(rl: dict[str, Any], contrat: ContratGestion):
    """Retourne un callback on_page (logo + pied de page)."""
    mm = rl["mm"]
    colors = rl["colors"]

    def _draw(canvas, doc):  # noqa: ANN001
        canvas.saveState()
        w, _h = doc.pagesize
        logo_src = _logo_light_source()
        if logo_src is not None:
            try:
                from reportlab.lib.utils import ImageReader  # type: ignore

                canvas.drawImage(
                    ImageReader(logo_src), 15 * mm, doc.pagesize[1] - 22 * mm,
                    width=32 * mm, height=12 * mm, preserveAspectRatio=True,
                    mask="auto", anchor="nw",
                )
            except Exception:
                pass
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor(MUTED_HEX))
        canvas.drawRightString(
            w - 15 * mm, 10 * mm,
            f"{COMPANY_NAME} · {COMPANY_EMAIL} · page {doc.page}",
        )
        canvas.restoreState()

    return _draw


def render_contrat_pdf(contrat: ContratGestion, body_md: str) -> bytes:
    """Rend le PDF (non signé) de la convention."""
    rl = _lazy_reportlab()
    mm = rl["mm"]
    buf = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=rl["letter"],
        topMargin=26 * mm,
        bottomMargin=16 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        title="Convention de gestion immobilière",
    )
    st = _styles(rl)
    story = _body_flowables(rl, st, body_md)
    story.extend(_signature_block(rl, st, contrat))
    on_page = _header_footer(rl, contrat)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def _render_signed_bytes(contrat: ContratGestion, body_md: str) -> bytes:
    """PDF signé : bloc Mandant rempli + bandeau emerald page 1."""
    import hashlib

    base_pdf = render_contrat_pdf(contrat, body_md)
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore
        from reportlab.pdfgen import canvas  # type: ignore
    except Exception:
        log.warning("[CG_PDF] pypdf indisponible — PDF signé sans bandeau (contrat %s).", contrat.id)
        return base_pdf

    rl = _lazy_reportlab()
    mm = rl["mm"]
    colors = rl["colors"]
    page_w_pt, page_h_pt = rl["letter"]

    signed_at = contrat.signed_at
    signed_name = (contrat.signed_name or "—").strip() or "—"
    signed_ip = (contrat.signed_ip or "—").strip() or "—"
    if signed_at is not None:
        signed_long = _date_fr_ca_long(signed_at)
        signed_clock = signed_at.strftime("%H:%M UTC")
    else:
        signed_long = "—"
        signed_clock = "—"
    pdf_hash = hashlib.sha256(base_pdf).hexdigest()[:16]

    overlay_buf = io.BytesIO()
    c = canvas.Canvas(overlay_buf, pagesize=rl["letter"])
    band_h = 18 * mm
    band_y = page_h_pt - band_h
    c.setFillColor(colors.HexColor("#059669"))
    c.rect(0, band_y, page_w_pt, band_h, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(15 * mm, band_y + band_h - 6 * mm, "✓ SIGNEE ELECTRONIQUEMENT")
    c.setFont("Helvetica", 8)
    c.drawString(
        15 * mm, band_y + band_h - 11 * mm,
        f"{signed_name} le {signed_long} a {signed_clock} depuis IP {signed_ip}",
    )
    c.drawString(
        15 * mm, band_y + 3 * mm,
        f"Hash du document (SHA-256, 16 premiers caracteres) : {pdf_hash}",
    )
    c.save()
    overlay_buf.seek(0)

    try:
        reader_base = PdfReader(io.BytesIO(base_pdf))
        reader_overlay = PdfReader(overlay_buf)
        writer = PdfWriter()
        overlay_page = reader_overlay.pages[0]
        for idx, page in enumerate(reader_base.pages):
            if idx == 0:
                try:
                    page.merge_page(overlay_page)
                except Exception:
                    log.exception("[CG_PDF] Overlay bandeau échoué (contrat %s)", contrat.id)
            writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception as exc:
        log.exception("[CG_PDF] Fusion overlay signé échouée (contrat %s): %s", contrat.id, exc)
        return base_pdf


def generate_signed_contrat_pdf(contrat: ContratGestion, body_md: str) -> bytes:
    return _render_signed_bytes(contrat, body_md)


def _slugify(name: Optional[str]) -> str:
    import unicodedata

    base = unicodedata.normalize("NFKD", (name or "").strip())
    base = base.encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")
    return base or "Mandant"


def contrat_pdf_filename(contrat: ContratGestion, signed: bool = False) -> str:
    slug = _slugify(contrat.compagnie or contrat.representant_nom)
    suffix = "_SIGNE" if signed else ""
    return f"Convention_gestion_MGV_{slug}{suffix}.pdf"
