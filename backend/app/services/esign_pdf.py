"""eSign — rendu PDF.

Deux responsabilités :

1. `page_png()` : rend UNE page du PDF original en PNG (pdf2image /
   poppler, déjà dans l'Aptfile) — sert à l'éditeur visuel de zones
   côté admin ET à la page publique de signature. Fonctions sync
   CPU-bound → les endpoints les appellent via `asyncio.to_thread`.

2. `build_final_pdf()` : produit le PDF final « aplati » quand tous
   les signataires ont signé — chaque zone (signature, initiales,
   date, texte, case) est fusionnée dans la page via un overlay
   reportlab + pypdf (recette reprise de `nda_pdf._render_signed_bytes`),
   puis une page d'audit est ajoutée en annexe (signataires, IP,
   horodatages, journal d'événements, SHA-256 de l'original).

Les coordonnées des zones sont des FRACTIONS de page (0..1, origine
coin HAUT-gauche) ; reportlab a l'origine en BAS-gauche → conversion
ici, en points PDF réels de chaque page (pas de A4 codé en dur).
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from app.models.esign import (
    EsignDocument,
    EsignEvent,
    EsignField,
    EsignFieldKind,
    EsignSigner,
)

log = logging.getLogger(__name__)

TZ_MONTREAL = ZoneInfo("America/Toronto")

_MONTHS_FR_CA = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)

_EVENT_LABELS = {
    "cree": "Document créé",
    "envoye": "Invitation envoyée",
    "relance": "Relance envoyée",
    "ouvert": "Document ouvert",
    "sms_envoye": "Code SMS envoyé",
    "sms_verifie": "Identité vérifiée par SMS",
    "signe": "Document signé",
    "refuse": "Signature refusée",
    "complete": "Document complété",
    "annule": "Document annulé",
    "expire": "Lien de signature expiré",
}


def date_fr_ca_long(d: Optional[datetime]) -> str:
    """« 6 août 2026 » en heure de Montréal."""
    if d is None:
        return "—"
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    local = d.astimezone(TZ_MONTREAL)
    return f"{local.day} {_MONTHS_FR_CA[local.month - 1]} {local.year}"


def datetime_fr_ca(d: Optional[datetime]) -> str:
    """« 6 août 2026 à 14:32 » en heure de Montréal."""
    if d is None:
        return "—"
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    local = d.astimezone(TZ_MONTREAL)
    return (
        f"{local.day} {_MONTHS_FR_CA[local.month - 1]} {local.year} "
        f"à {local.strftime('%H:%M')}"
    )


# ---------------------------------------------------------------------------
# Lecture / rendu de pages
# ---------------------------------------------------------------------------


def pdf_page_count(pdf_bytes: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


def page_png(pdf_bytes: bytes, page_number: int, dpi: int = 130) -> bytes:
    """Rend la page `page_number` (1-based) en PNG.

    130 dpi ≈ 1100 px de large pour une page lettre — suffisant pour
    positionner des zones à l'écran sans exploser le poids réseau.
    """
    from pdf2image import convert_from_bytes

    images = convert_from_bytes(
        pdf_bytes,
        dpi=dpi,
        first_page=page_number,
        last_page=page_number,
        fmt="png",
    )
    if not images:
        raise ValueError(f"Page {page_number} introuvable dans le PDF.")
    buf = io.BytesIO()
    images[0].save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF final aplati
# ---------------------------------------------------------------------------


def _draw_field(c, field: EsignField, signer: Optional[EsignSigner],
                page_w: float, page_h: float) -> None:
    """Dessine une zone remplie sur le canvas overlay d'une page."""
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader

    x_pt = field.x * page_w
    w_pt = field.w * page_w
    h_pt = field.h * page_h
    # Origine reportlab en bas-gauche ; y du champ = bord haut.
    y_pt = page_h - (field.y * page_h) - h_pt

    kind = field.kind

    if kind in (EsignFieldKind.SIGNATURE.value, EsignFieldKind.INITIALES.value):
        img_bytes = None
        if signer is not None:
            img_bytes = (
                signer.signature_image
                if kind == EsignFieldKind.SIGNATURE.value
                else signer.initials_image
            )
        if not img_bytes:
            return
        try:
            img = ImageReader(io.BytesIO(bytes(img_bytes)))
            c.drawImage(
                img,
                x_pt,
                y_pt,
                width=w_pt,
                height=h_pt,
                preserveAspectRatio=True,
                anchor="sw",
                mask="auto",
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "eSign : tampon image impossible (champ %s)", field.id
            )
        return

    value = (field.value_text or "").strip()
    if not value:
        return

    if kind == EsignFieldKind.CASE.value:
        # Case cochée : un X net dans la zone.
        c.setStrokeColor(colors.HexColor("#111827"))
        c.setLineWidth(1.2)
        side = min(w_pt, h_pt)
        cx, cy = x_pt, y_pt + (h_pt - side) / 2
        c.rect(cx, cy, side, side, fill=0, stroke=1)
        pad = side * 0.22
        c.line(cx + pad, cy + pad, cx + side - pad, cy + side - pad)
        c.line(cx + pad, cy + side - pad, cx + side - pad, cy + pad)
        return

    # date / texte → texte noir ajusté à la hauteur de la zone.
    font_size = max(7.0, min(12.0, h_pt * 0.55))
    c.setFillColor(colors.HexColor("#111827"))
    c.setFont("Helvetica", font_size)
    baseline = y_pt + (h_pt - font_size) / 2 + font_size * 0.18
    c.drawString(x_pt + 2, baseline, value[:200])


def _signer_full_name(s: EsignSigner) -> str:
    return f"{(s.first_name or '').strip()} {(s.last_name or '').strip()}".strip()


def _audit_pdf(
    doc: EsignDocument,
    signers: Sequence[EsignSigner],
    events: Sequence[EsignEvent],
    entreprise_name: Optional[str],
) -> bytes:
    """Page(s) d'audit annexée(s) au PDF final."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="Certificat de signature",
    )

    st_h1 = ParagraphStyle(
        "h1", fontName="Helvetica-Bold", fontSize=15, leading=19,
        textColor=colors.HexColor("#111827"), spaceAfter=4,
    )
    st_meta = ParagraphStyle(
        "meta", fontName="Helvetica", fontSize=8.5, leading=12,
        textColor=colors.HexColor("#374151"),
    )
    st_h2 = ParagraphStyle(
        "h2", fontName="Helvetica-Bold", fontSize=11, leading=14,
        textColor=colors.HexColor("#111827"), spaceBefore=10, spaceAfter=4,
    )
    st_cell = ParagraphStyle(
        "cell", fontName="Helvetica", fontSize=8, leading=11,
        textColor=colors.HexColor("#111827"),
    )
    st_cell_b = ParagraphStyle(
        "cellb", fontName="Helvetica-Bold", fontSize=8, leading=11,
        textColor=colors.HexColor("#111827"),
    )

    flow = [
        Paragraph("Certificat de signature électronique", st_h1),
        Paragraph(
            f"Document : <b>{doc.title}</b> (fichier « {doc.filename} », "
            f"{doc.page_count} page{'s' if doc.page_count > 1 else ''})",
            st_meta,
        ),
    ]
    if entreprise_name:
        flow.append(Paragraph(f"Entreprise : {entreprise_name}", st_meta))
    flow.append(
        Paragraph(
            f"Envoyé le {datetime_fr_ca(doc.sent_at)} · "
            f"Complété le {datetime_fr_ca(doc.completed_at)}",
            st_meta,
        )
    )
    if doc.sha256:
        flow.append(
            Paragraph(
                f"Empreinte SHA-256 du document original : {doc.sha256}",
                st_meta,
            )
        )

    flow.append(Paragraph("Signataires", st_h2))
    sig_rows = [[
        Paragraph("Signataire", st_cell_b),
        Paragraph("Authentification", st_cell_b),
        Paragraph("Ouvertures", st_cell_b),
        Paragraph("Signé", st_cell_b),
    ]]
    for s in signers:
        if s.declined_at:
            signed_txt = (
                f"REFUSÉ le {datetime_fr_ca(s.declined_at)}"
                + (f" — « {s.decline_reason} »" if s.decline_reason else "")
            )
        elif s.signed_at:
            signed_txt = (
                f"{datetime_fr_ca(s.signed_at)}"
                + (f"<br/>IP {s.signed_ip}" if s.signed_ip else "")
            )
        else:
            signed_txt = "—"
        if s.require_sms_auth:
            auth_txt = (
                f"Code SMS vérifié le {datetime_fr_ca(s.sms_verified_at)}"
                if s.sms_verified_at
                else "Code SMS requis (non vérifié)"
            )
        else:
            auth_txt = "Lien courriel"
        opens = (
            f"{s.open_count} — 1re le {datetime_fr_ca(s.opened_at)}"
            if s.open_count
            else "—"
        )
        sig_rows.append([
            Paragraph(
                f"<b>{_signer_full_name(s)}</b><br/>{s.email}"
                + (f"<br/>{s.phone}" if s.phone else ""),
                st_cell,
            ),
            Paragraph(auth_txt, st_cell),
            Paragraph(opens, st_cell),
            Paragraph(signed_txt, st_cell),
        ])
    sig_table = Table(
        sig_rows, colWidths=[52 * mm, 42 * mm, 40 * mm, 44 * mm]
    )
    sig_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9ca3af")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    flow.append(sig_table)

    if events:
        flow.append(Paragraph("Journal d'événements", st_h2))
        by_id = {s.id: s for s in signers}
        ev_rows = [[
            Paragraph("Date (Montréal)", st_cell_b),
            Paragraph("Événement", st_cell_b),
            Paragraph("Signataire", st_cell_b),
            Paragraph("IP", st_cell_b),
        ]]
        for ev in events:
            who = by_id.get(ev.signer_id) if ev.signer_id else None
            label = _EVENT_LABELS.get(ev.type, ev.type)
            if ev.detail:
                label = f"{label} — {ev.detail}"
            ev_rows.append([
                Paragraph(datetime_fr_ca(ev.created_at), st_cell),
                Paragraph(label, st_cell),
                Paragraph(_signer_full_name(who) if who else "—", st_cell),
                Paragraph(ev.ip or "—", st_cell),
            ])
        ev_table = Table(
            ev_rows, colWidths=[38 * mm, 76 * mm, 40 * mm, 24 * mm]
        )
        ev_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9ca3af")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        flow.append(ev_table)

    flow.append(Spacer(1, 8))
    flow.append(
        Paragraph(
            "Certificat généré automatiquement par Kratos eSign "
            "(Horizon Services Immobiliers). Ce document atteste des "
            "actions horodatées ci-dessus ; l'empreinte SHA-256 permet "
            "de vérifier l'intégrité du document original.",
            st_meta,
        )
    )

    pdf.build(flow)
    return buf.getvalue()


def build_final_pdf(
    doc: EsignDocument,
    signers: Sequence[EsignSigner],
    fields: Iterable[EsignField],
    events: Sequence[EsignEvent],
    entreprise_name: Optional[str] = None,
) -> bytes:
    """PDF final : original + zones fusionnées + page d'audit.

    Ne lève JAMAIS pour un champ isolé (best-effort par zone) ; une
    exception globale est laissée remonter — l'appelant décide du
    fallback (la signature en DB reste la source de vérité).
    """
    import hashlib

    from pypdf import PdfReader, PdfWriter
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas

    original = bytes(doc.pdf_blob)
    reader = PdfReader(io.BytesIO(original))
    writer = PdfWriter()

    signer_by_id = {s.id: s for s in signers}
    fields_by_page: dict[int, list[EsignField]] = {}
    for f in fields:
        fields_by_page.setdefault(int(f.page), []).append(f)

    sha16 = (doc.sha256 or hashlib.sha256(original).hexdigest())[:16]
    footer = (
        f"Kratos eSign · document #{doc.id} · SHA-256 {sha16} · "
        f"complété le {datetime_fr_ca(doc.completed_at)}"
    )

    for idx, page in enumerate(reader.pages):
        page_num = idx + 1
        box = page.mediabox
        page_w = float(box.width)
        page_h = float(box.height)

        overlay_buf = io.BytesIO()
        c = canvas.Canvas(overlay_buf, pagesize=(page_w, page_h))
        for field in fields_by_page.get(page_num, ()):  # zones de la page
            try:
                _draw_field(
                    c, field, signer_by_id.get(field.signer_id),
                    page_w, page_h,
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "eSign : zone %s ignorée sur la page %s",
                    field.id, page_num,
                )
        # Pied de page discret sur chaque page (traçabilité).
        c.setFont("Helvetica", 6.5)
        c.setFillColor(colors.HexColor("#6b7280"))
        c.drawString(12, 6, footer[:180])
        c.save()
        overlay_buf.seek(0)

        try:
            overlay_page = PdfReader(overlay_buf).pages[0]
            page.merge_page(overlay_page)
        except Exception:  # noqa: BLE001
            log.exception(
                "eSign : fusion overlay échouée (doc %s page %s)",
                doc.id, page_num,
            )
        writer.add_page(page)

    try:
        audit_bytes = _audit_pdf(doc, signers, events, entreprise_name)
        for p in PdfReader(io.BytesIO(audit_bytes)).pages:
            writer.add_page(p)
    except Exception:  # noqa: BLE001
        log.exception(
            "eSign : page d'audit non générée (doc %s) — PDF final "
            "livré sans annexe.",
            doc.id,
        )

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def final_pdf_filename(doc: EsignDocument) -> str:
    base = (doc.title or "document").strip() or "document"
    safe = "".join(
        ch if ch.isalnum() or ch in " -_." else "_" for ch in base
    ).strip()[:80]
    return f"{safe} — signé.pdf"
