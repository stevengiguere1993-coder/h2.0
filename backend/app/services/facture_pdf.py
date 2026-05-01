"""Generate a PDF for a Facture — mirrors soumission_pdf layout with
the word FACTURE and an optional due date / balance block.

When the facture is linked to a project that comes from an accepted
soumission, the PDF includes a « Récapitulatif du contrat » block
showing the soumission total, the cumulative billed-to-date and
paid-to-date across siblings factures, and the remaining contract
balance.

When ``include_statement=True`` is passed to :func:`render_facture_pdf`,
an « État de compte » page (full project ledger) is appended after
the facture page so the client receives a single PDF.
"""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.facture import Facture, FactureStatus
from app.models.facture_item import FactureItem
from app.models.payment import Payment
from app.models.project import Project
from app.models.soumission import Soumission
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


@dataclass
class ContractSummary:
    """Synthèse contrat affichée sur la facture PDF quand celle-ci est
    rattachée à un projet venant d'une soumission acceptée."""

    soumission_reference: str
    contract_total: float    # soumission.total (TTC)
    billed_to_date: float    # somme des factures non-void liées au projet
    paid_to_date: float      # somme des paiements sur ces factures
    remaining_balance: float # contract_total - paid_to_date


@dataclass
class StatementLine:
    kind: str   # "facture" | "payment"
    when: date
    label: str
    amount: float  # facture: total positif; payment: positif (encaissé)
    detail: Optional[str] = None


@dataclass
class Statement:
    project_name: Optional[str]
    soumission_reference: Optional[str]
    lines: List[StatementLine]
    contract_total: float
    billed_to_date: float
    paid_to_date: float
    remaining_balance: float

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


async def _load_contract_summary(
    db: AsyncSession, fa: Facture
) -> Optional[ContractSummary]:
    """Compute le récapitulatif contrat pour `fa` si elle est liée à
    un projet qui vient d'une soumission acceptée. Retourne None
    sinon (facture isolée, projet sans soumission, etc.)."""
    if fa.project_id is None:
        return None
    project = (
        await db.execute(
            select(Project).where(Project.id == fa.project_id)
        )
    ).scalar_one_or_none()
    if project is None or project.soumission_id is None:
        return None
    sm = (
        await db.execute(
            select(Soumission).where(Soumission.id == project.soumission_id)
        )
    ).scalar_one_or_none()
    if sm is None or sm.total is None:
        return None

    # Toutes les factures non-VOID liées au projet (y compris la
    # facture courante) : on additionne leur total pour avoir
    # « Total déjà facturé ».
    sibling_rows = (
        await db.execute(
            select(Facture.id, Facture.total).where(
                Facture.project_id == project.id,
                Facture.status != FactureStatus.VOID.value,
            )
        )
    ).all()
    sibling_ids = [r[0] for r in sibling_rows]
    billed_to_date = round(
        sum(float(t or 0) for _, t in sibling_rows), 2
    )

    # Total des paiements sur ces factures.
    paid_to_date = 0.0
    if sibling_ids:
        pay_rows = (
            await db.execute(
                select(Payment.amount).where(
                    Payment.facture_id.in_(sibling_ids)
                )
            )
        ).all()
        paid_to_date = round(
            sum(float(a or 0) for (a,) in pay_rows), 2
        )

    contract_total = round(float(sm.total), 2)
    remaining = round(contract_total - paid_to_date, 2)
    return ContractSummary(
        soumission_reference=sm.reference,
        contract_total=contract_total,
        billed_to_date=billed_to_date,
        paid_to_date=paid_to_date,
        remaining_balance=remaining,
    )


async def _load_statement(
    db: AsyncSession, fa: Facture
) -> Optional[Statement]:
    """Construit l'état de compte (toutes les factures + paiements
    pour le projet de `fa`). None si la facture n'est pas liée à un
    projet."""
    if fa.project_id is None:
        return None

    project = (
        await db.execute(
            select(Project).where(Project.id == fa.project_id)
        )
    ).scalar_one_or_none()
    if project is None:
        return None

    sm: Optional[Soumission] = None
    if project.soumission_id:
        sm = (
            await db.execute(
                select(Soumission).where(
                    Soumission.id == project.soumission_id
                )
            )
        ).scalar_one_or_none()

    factures = list(
        (
            await db.execute(
                select(Facture)
                .where(Facture.project_id == project.id)
                .order_by(Facture.issued_at.asc(), Facture.id.asc())
            )
        )
        .scalars()
        .all()
    )
    facture_ids = [f.id for f in factures]
    payments: list[Payment] = []
    if facture_ids:
        payments = list(
            (
                await db.execute(
                    select(Payment)
                    .where(Payment.facture_id.in_(facture_ids))
                    .order_by(Payment.paid_at.asc(), Payment.id.asc())
                )
            )
            .scalars()
            .all()
        )

    lines: List[StatementLine] = []
    for f in factures:
        when = (f.issued_at.date() if f.issued_at else f.created_at.date())
        label = f"Facture {f.reference}"
        detail = f.status.upper() if f.status else None
        lines.append(
            StatementLine(
                kind="facture",
                when=when,
                label=label,
                amount=float(f.total or 0),
                detail=detail,
            )
        )
    for p in payments:
        # Map facture_id → reference pour un libellé lisible
        ref = next(
            (f.reference for f in factures if f.id == p.facture_id),
            None,
        )
        method = (p.method or "").replace("_", " ")
        detail_parts = [method]
        if p.reference:
            detail_parts.append(f"réf. {p.reference}")
        lines.append(
            StatementLine(
                kind="payment",
                when=p.paid_at,
                label=(
                    f"Paiement reçu — Facture {ref}"
                    if ref
                    else "Paiement reçu"
                ),
                amount=float(p.amount or 0),
                detail=" · ".join(p for p in detail_parts if p),
            )
        )
    # Tri chronologique global, factures avant paiements le même jour.
    lines.sort(key=lambda x: (x.when, 0 if x.kind == "facture" else 1))

    contract_total = float(sm.total or 0) if sm else 0.0
    billed_to_date = round(
        sum(float(f.total or 0) for f in factures
            if f.status != FactureStatus.VOID.value),
        2,
    )
    paid_to_date = round(
        sum(float(p.amount or 0) for p in payments), 2
    )
    remaining = round(
        (contract_total or billed_to_date) - paid_to_date, 2
    )

    return Statement(
        project_name=project.name,
        soumission_reference=sm.reference if sm else None,
        lines=lines,
        contract_total=round(contract_total, 2),
        billed_to_date=billed_to_date,
        paid_to_date=paid_to_date,
        remaining_balance=remaining,
    )


def _render_bytes(
    fa: Facture,
    items: list[FactureItem],
    client: Optional[Client],
    *,
    tax_gst: Optional[str] = None,
    tax_qst: Optional[str] = None,
    contract: Optional[ContractSummary] = None,
    statement: Optional[Statement] = None,
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

    # Récapitulatif du contrat — affiché quand la facture est liée à
    # une soumission acceptée. Permet au client de voir d'un coup
    # d'œil le total contracté, le déjà facturé/payé et le solde
    # restant à venir sur le contrat global.
    if contract is not None:
        story.append(Paragraph(
            f"RÉCAPITULATIF DU CONTRAT — Soumission {contract.soumission_reference}",
            s["accent"],
        ))
        recap_rows = [
            ["Total du contrat", _money(contract.contract_total)],
            ["Total déjà facturé", _money(contract.billed_to_date)],
            ["Total déjà payé", _money(contract.paid_to_date)],
            ["Solde du contrat", _money(contract.remaining_balance)],
        ]
        recap_tbl = Table(
            recap_rows,
            colWidths=[doc.width * 0.30, doc.width * 0.20],
        )
        recap_tbl.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("TEXTCOLOR", (0, 0), (-1, -2), MUTED),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, -1), (-1, -1), DARK),
            ("LINEABOVE", (0, -1), (-1, -1), 0.5, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        recap_wrap = Table(
            [["", recap_tbl]],
            colWidths=[doc.width * 0.50, doc.width * 0.50],
        )
        recap_wrap.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(recap_wrap)
        story.append(Spacer(1, 14))

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
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "<b>Tout retard de paiement après l'échéance est facturé "
        "à 2 % par mois (24 % par an), conformément à nos "
        "conditions générales.</b>",
        s["small"],
    ))
    story.append(Spacer(1, 16))
    story.append(Paragraph(
        f"{COMPANY_NAME} &middot; {COMPANY_RBQ} &middot; {COMPANY_EMAIL}",
        s["small"],
    ))

    # État de compte appendé après la page facture, sur une nouvelle
    # page. Le client reçoit ainsi un seul PDF avec la facture +
    # l'historique complet du contrat.
    if statement is not None and statement.lines:
        story.append(rl["PageBreak"]())
        story.append(Paragraph("ÉTAT DE COMPTE", s["h1"]))
        if statement.project_name:
            story.append(
                Paragraph(f"Projet : {statement.project_name}", s["small"])
            )
        if statement.soumission_reference:
            story.append(Paragraph(
                f"Soumission : {statement.soumission_reference}", s["small"],
            ))
        if client is not None:
            story.append(
                Paragraph(f"Client : {client.name}", s["small"])
            )
        story.append(
            Paragraph(f"Émis le {_date(datetime.utcnow())}", s["small"])
        )
        story.append(Spacer(1, 12))

        st_data = [["Date", "Description", "Détail", "Débit", "Crédit"]]
        running = 0.0
        for ln in statement.lines:
            if ln.kind == "facture":
                debit = ln.amount
                credit = 0.0
                running += debit
            else:  # payment
                debit = 0.0
                credit = ln.amount
                running -= credit
            st_data.append([
                _date(ln.when),
                Paragraph(ln.label, s["body"]),
                Paragraph(ln.detail or "", s["small"]),
                _money(debit) if debit else "",
                _money(credit) if credit else "",
            ])
        st_tbl = Table(
            st_data,
            colWidths=[
                doc.width * 0.13, doc.width * 0.34,
                doc.width * 0.23, doc.width * 0.15,
                doc.width * 0.15,
            ],
            repeatRows=1,
        )
        st_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                [colors.white, colors.HexColor("#fafafa")]),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, ACCENT),
            ("FONTSIZE", (0, 1), (-1, -1), 9.0),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(st_tbl)
        story.append(Spacer(1, 12))

        # Totaux de l'état de compte
        recap_rows = []
        if statement.contract_total > 0:
            recap_rows.append(
                ["Total du contrat", _money(statement.contract_total)]
            )
        recap_rows.extend([
            ["Total facturé", _money(statement.billed_to_date)],
            ["Total payé", _money(statement.paid_to_date)],
            [
                "Solde à venir",
                _money(statement.remaining_balance),
            ],
        ])
        recap_tbl = Table(
            recap_rows,
            colWidths=[doc.width * 0.30, doc.width * 0.20],
        )
        recap_tbl.setStyle(TableStyle([
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
        recap_wrap = Table(
            [["", recap_tbl]],
            colWidths=[doc.width * 0.50, doc.width * 0.50],
        )
        recap_wrap.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(recap_wrap)

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
    db: AsyncSession,
    facture_id: int,
    *,
    include_statement: bool = False,
) -> Optional[tuple[Facture, bytes]]:
    """Génère le PDF d'une facture. Si ``include_statement=True``,
    une page « État de compte » récapitulant toutes les factures et
    paiements du projet est appendée."""
    fa, items, client = await _load(db, facture_id)
    if fa is None:
        return None
    gst, qst = await _fetch_tax_numbers()
    contract = await _load_contract_summary(db, fa)
    statement = (
        await _load_statement(db, fa) if include_statement else None
    )
    pdf = _render_bytes(
        fa, items, client,
        tax_gst=gst, tax_qst=qst,
        contract=contract,
        statement=statement,
    )
    return fa, pdf
