"""PDF d'un AVENANT (change order) de devis accepté — retour Phil
2026-09-30 : l'original signé reste intact, chaque avenant a son propre
document à faire signer par le client.

Contenu : en-tête Horizon (même charte que la soumission), « AVENANT
AV-n au devis N° X », client, raison du changement, tableau des
changements (ajout / retrait / modification : avant → après), montant du
contrat avant, impact, contrat après (HT, taxes, total), bloc de
signature du client quand l'avenant est signé.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.models.soumission import Soumission
from app.models.soumission_avenant import SoumissionAvenant
from app.models.soumission_item import SoumissionItem
from app.services.soumission_pdf import (
    ACCENT_HEX,
    COMPANY_EMAIL,
    COMPANY_INSURANCE,
    COMPANY_NAME,
    COMPANY_RBQ,
    COMPANY_SITE,
    DARK_HEX,
    LINE_HEX,
    MUTED_HEX,
    _date,
    _fetch_tax_numbers,
    _ink_black,
    _lazy_reportlab,
    _load,
    _logo_light_source,
    _money,
    _multiline_markup,
    _styles,
)

log = logging.getLogger(__name__)

TPS = 0.05
TVQ = 0.09975

OP_LABELS = {"ajout": "Ajout", "retrait": "Retrait", "modification": "Modification"}


def _changes(av: SoumissionAvenant) -> list[dict]:
    try:
        data = json.loads(av.changes_json or "[]")
    except (TypeError, ValueError):
        return []
    return [c for c in data if isinstance(c, dict)]


def _fmt_line(snap: Optional[dict]) -> str:
    if not snap:
        return "—"
    q = float(snap.get("quantity") or 0)
    up = float(snap.get("unit_price") or 0)
    t = float(snap.get("total") or 0)
    unit = f" {snap.get('unit')}" if snap.get("unit") else ""
    return f"{q:g}{unit} × {_money(up)} = <b>{_money(t)}</b>"


async def contrat_apres_ht(db: AsyncSession, soumission_id: int) -> float:
    """Sous-total HT du contrat COURANT (items non retirés)."""
    rows = (
        await db.execute(
            select(SoumissionItem).where(
                SoumissionItem.soumission_id == soumission_id,
                SoumissionItem.retire_par_avenant_id.is_(None),
            )
        )
    ).scalars().all()
    total = 0.0
    for it in rows:
        total += float(it.total) if it.total is not None else float(it.quantity) * float(it.unit_price)
    return round(total, 2)


async def montants_avenant(db: AsyncSession, av: SoumissionAvenant) -> dict[str, float]:
    """Contrat avant / impact / après pour CET avenant : « après » = contrat
    tel qu'il était juste après cet avenant (les avenants suivants ne
    comptent pas), reconstruit depuis le contrat courant."""
    courant = await contrat_apres_ht(db, av.soumission_id)
    suivants = (
        await db.execute(
            select(SoumissionAvenant.impact_subtotal).where(
                SoumissionAvenant.soumission_id == av.soumission_id,
                SoumissionAvenant.numero > av.numero,
            )
        )
    ).scalars().all()
    apres = round(courant - sum(float(x or 0) for x in suivants), 2)
    impact = round(float(av.impact_subtotal or 0), 2)
    avant = round(apres - impact, 2)
    tps = round(apres * TPS, 2)
    tvq = round(apres * TVQ, 2)
    return {
        "contrat_avant": avant, "impact": impact, "contrat_apres": apres,
        "tps": tps, "tvq": tvq, "total_apres": round(apres + tps + tvq, 2),
    }


def _render_bytes(
    av: SoumissionAvenant,
    sm: Soumission,
    contact,
    client,
    montants: dict[str, float],
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

    buf = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buf, pagesize=rl["letter"],
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Avenant {av.reference} — Soumission {sm.reference}", author=COMPANY_NAME,
    )
    s = _styles(rl)
    story: list = []

    left_cell: list = []
    src = _logo_light_source()
    if src is not None:
        try:
            left_cell.append(Image(src, width=28 * mm, height=28 * mm))
            left_cell.append(Spacer(1, 4))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not embed logo in PDF: %s", exc)
    left_cell.extend([
        Paragraph(f"<b>{COMPANY_NAME}</b>", s["h2"]),
        Paragraph(COMPANY_RBQ, s["small"]),
        Paragraph(COMPANY_INSURANCE, s["small"]),
        Paragraph(f"{COMPANY_SITE} &middot; {COMPANY_EMAIL}", s["small"]),
    ])
    if tax_gst:
        left_cell.append(Paragraph(f"TPS : {tax_gst}", s["small"]))
    if tax_qst:
        left_cell.append(Paragraph(f"TVQ : {tax_qst}", s["small"]))
    right_cell = [
        Paragraph("AVENANT", s["h1"]),
        Paragraph(f"{av.reference} au devis N<sup>o</sup> {sm.reference}", s["accent"]),
        Paragraph(f"Émis le {_date(av.created_at)}", s["small"]),
    ]
    if getattr(sm, "accepted_at", None):
        right_cell.append(Paragraph(f"Devis accepté le {_date(sm.accepted_at)}", s["small"]))
    header = Table([[left_cell, right_cell]], colWidths=[doc.width * 0.55, doc.width * 0.45])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    story.append(header)
    story.append(Spacer(1, 14))

    if contact is not None:
        lines = [f"<b>{contact.name}</b>"] + [x for x in (contact.email, contact.phone, contact.address) if x]
    elif client is not None:
        lines = [f"<b>{client.name}</b>"]
        rep = getattr(client, "representative", None)
        if rep:
            lines.append(f"À l'attention de {rep}")
        lines += [x for x in (client.email, client.phone, client.address) if x]
    else:
        lines = ["<b>Client à confirmer</b>"]
    story.append(Paragraph("ADRESSÉ À", s["accent"]))
    for line in lines:
        story.append(Paragraph(line, s["body"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"Modification au contrat : {sm.title}", s["h2"]))
    if av.note:
        story.append(Paragraph(_multiline_markup(av.note), s["body"]))
    story.append(Spacer(1, 10))

    data = [["Changement", "Description", "Avant", "Après"]]
    for c in _changes(av):
        op = str(c.get("op") or "")
        avant, apres = c.get("avant"), c.get("apres")
        desc = (apres or avant or {}).get("description") or ""
        if op == "modification" and avant and apres and avant.get("description") != apres.get("description"):
            desc = f"{avant.get('description')} → {apres.get('description')}"
        data.append([
            Paragraph(f"<b>{OP_LABELS.get(op, op)}</b>", s["body"]),
            Paragraph(_multiline_markup(desc), s["body"]),
            Paragraph(_fmt_line(avant) if op != "ajout" else "—", s["body"]),
            Paragraph(_fmt_line(apres) if op != "retrait" else "<b>Retiré</b>", s["body"]),
        ])
    if len(data) == 1:
        data.append([Paragraph("<i>Aucun changement détaillé.</i>", s["small"]), "", "", ""])
    tbl = Table(data, colWidths=[doc.width * 0.16, doc.width * 0.40, doc.width * 0.22, doc.width * 0.22], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, ACCENT),
        ("LINEABOVE", (0, -1), (-1, -1), 0.25, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 10))

    impact = montants["impact"]
    rows = [
        ["Contrat avant cet avenant (HT)", _money(montants["contrat_avant"])],
        [("Impact de l'avenant (HT)"), ("+" if impact >= 0 else "−") + _money(abs(impact))],
        ["Contrat après cet avenant (HT)", _money(montants["contrat_apres"])],
        ["TPS (5 %)", _money(montants["tps"])],
        ["TVQ (9,975 %)", _money(montants["tvq"])],
        ["TOTAL DU CONTRAT CAD", _money(montants["total_apres"])],
    ]
    totals = Table(rows, colWidths=[doc.width * 0.34, doc.width * 0.18])
    totals.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, -2), MUTED),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"), ("TEXTCOLOR", (0, 1), (-1, 1), DARK),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, -1), (-1, -1), 11),
        ("TEXTCOLOR", (0, -1), (-1, -1), DARK), ("LINEABOVE", (0, -1), (-1, -1), 0.75, DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    wrap = Table([["", totals]], colWidths=[doc.width * 0.48, doc.width * 0.52])
    wrap.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(wrap)
    story.append(Spacer(1, 16))

    story.append(Paragraph("CONDITIONS", s["accent"]))
    story.append(Paragraph(
        "Le présent avenant modifie le devis accepté identifié ci-dessus ; toutes les "
        "autres conditions du devis demeurent inchangées. Les taxes TPS (5 %) et "
        "TVQ (9,975 %) sont applicables. La signature de cet avenant vaut acceptation "
        "des changements et du nouveau montant du contrat.",
        s["small"],
    ))

    sig_bytes = None
    try:
        sig_bytes = av.signature_image
    except Exception:  # noqa: BLE001
        sig_bytes = None
    if av.signature_status == "signe" and sig_bytes:
        story.append(Spacer(1, 18))
        story.append(Paragraph("SIGNATURE DU CLIENT", s["accent"]))
        # L'image est validée AVANT le build (reportlab la lit
        # paresseusement au build : une image corrompue ferait échouer
        # tout le PDF, signature comprise).
        try:
            from PIL import Image as PILImage

            inked = _ink_black(sig_bytes)
            PILImage.open(io.BytesIO(inked)).load()
            img = Image(io.BytesIO(inked), width=60 * mm, height=24 * mm)
            img.hAlign = "LEFT"
            story.append(img)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not embed client signature in avenant PDF: %s", exc)
        story.append(Paragraph("_______________________________", s["small"]))
        story.append(Paragraph(f"Signé par <b>{av.signed_name or 'Client'}</b>", s["body"]))
        if av.signed_at:
            story.append(Paragraph(f"Le {_date(av.signed_at)}", s["small"]))
        if av.signed_ip:
            story.append(Paragraph(f"IP : {av.signed_ip}", s["small"]))

    story.append(Spacer(1, 16))
    story.append(Paragraph(
        f"{COMPANY_NAME} &middot; {COMPANY_RBQ} &middot; {COMPANY_INSURANCE} &middot; {COMPANY_EMAIL}",
        s["small"],
    ))
    doc.build(story)
    return buf.getvalue()


async def load_avenant(db: AsyncSession, avenant_id: int) -> Optional[SoumissionAvenant]:
    return (
        await db.execute(
            select(SoumissionAvenant)
            .where(SoumissionAvenant.id == avenant_id)
            .options(undefer(SoumissionAvenant.signature_image))
        )
    ).scalar_one_or_none()


async def render_avenant_pdf(
    db: AsyncSession, avenant_id: int
) -> Optional[tuple[SoumissionAvenant, Soumission, bytes]]:
    av = await load_avenant(db, avenant_id)
    if av is None:
        return None
    sm, _items, contact, client = await _load(db, av.soumission_id)
    if sm is None:
        return None
    montants = await montants_avenant(db, av)
    gst, qst = await _fetch_tax_numbers()
    pdf = _render_bytes(av, sm, contact, client, montants, tax_gst=gst, tax_qst=qst)
    return av, sm, pdf


def avenant_pdf_filename(av: SoumissionAvenant, sm: Soumission, *, signe: bool = False) -> str:
    return f"avenant-{av.reference}-soumission-{sm.reference}{'-signe' if signe else ''}.pdf"
