"""Generate a PDF for a Facture — mirrors soumission_pdf layout with
the word FACTURE and an optional due date / balance block.

When ``include_statement=True`` is passed to :func:`render_facture_pdf`,
an « État de compte » page (full project ledger) is appended after
the facture page so the client receives un seul PDF.
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
from sqlalchemy.orm import undefer

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
    _logo_light_source,
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
    client_name: Optional[str]
    lines: List[StatementLine]
    contract_total: float
    billed_to_date: float
    paid_to_date: float
    remaining_balance: float
    # Part des factures qui sont des EXTRAS (hors soumission de base :
    # heures T&M, achats/matériel, ajouts hors-contrat). Sert à montrer
    # une ligne dédiée pour que le solde se réconcilie (le client n'est
    # pas « en trop-payé » : son solde = total facturé − total payé).
    extras_billed: float = 0.0
    # Langue de rendu du relevé : « fr » (défaut) ou « en ».
    lang: str = "fr"

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
    # undefer(signature_image) : la colonne BLOB est `deferred` ; on la
    # charge explicitement ici car le rendu PDF (sync) y accède — un
    # lazy-load en contexte async lèverait une erreur greenlet.
    fa = (
        await db.execute(
            select(Facture)
            .where(Facture.id == facture_id)
            .options(undefer(Facture.signature_image))
        )
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


# Factures « envoyées » au client : on exclut les brouillons (jamais
# transmis) et les factures annulées (void). L'état de compte ne doit
# montrer au client que les factures qu'il a réellement reçues.
_CLIENT_FACTURE_STATUSES = (
    FactureStatus.SENT.value,
    FactureStatus.PAID.value,
    FactureStatus.OVERDUE.value,
)

# L'état de compte est un document client : statuts de facture et modes
# de paiement sont affichés dans la langue du client, jamais en code
# brut anglais (« PAID », « bank_transfer »).
_FACTURE_STATUS_LABELS = {
    "fr": {
        "draft": "Brouillon",
        "sent": "Envoyée",
        "paid": "Payée",
        "overdue": "En retard",
        "void": "Annulée",
    },
    "en": {
        "draft": "Draft",
        "sent": "Sent",
        "paid": "Paid",
        "overdue": "Overdue",
        "void": "Void",
    },
}
_PAYMENT_METHOD_LABELS = {
    "fr": {
        "cash": "Argent comptant",
        "credit_card": "Carte de crédit",
        "debit_card": "Carte de débit",
        "check": "Chèque",
        "bank_transfer": "Virement bancaire",
        "other": "Autre",
    },
    "en": {
        "cash": "Cash",
        "credit_card": "Credit card",
        "debit_card": "Debit card",
        "check": "Cheque",
        "bank_transfer": "Bank transfer",
        "other": "Other",
    },
}


async def _build_statement(
    db: AsyncSession,
    project: Project,
    force_lang: Optional[str] = None,
) -> Statement:
    """État de compte d'un projet : ses factures envoyées + les
    paiements reçus, en ordre chronologique, avec les totaux. La langue
    suit celle du client, sauf si `force_lang` l'impose (le relevé
    annexé aux factures reste en français)."""
    sm: Optional[Soumission] = None
    if project.soumission_id:
        sm = (
            await db.execute(
                select(Soumission).where(
                    Soumission.id == project.soumission_id
                )
            )
        ).scalar_one_or_none()

    # Client + langue de rendu.
    client: Optional[Client] = None
    if project.client_id:
        client = (
            await db.execute(
                select(Client).where(Client.id == project.client_id)
            )
        ).scalar_one_or_none()
    lang = force_lang or (getattr(client, "language", None) or "fr")
    if lang not in ("fr", "en"):
        lang = "fr"
    is_en = lang == "en"
    status_labels = _FACTURE_STATUS_LABELS[lang]
    method_labels = _PAYMENT_METHOD_LABELS[lang]

    factures = list(
        (
            await db.execute(
                select(Facture)
                .where(
                    Facture.project_id == project.id,
                    Facture.status.in_(_CLIENT_FACTURE_STATUSES),
                )
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
        status = status_labels.get(
            (f.status or "").lower(), (f.status or "").upper() or None
        )
        lines.append(
            StatementLine(
                kind="facture",
                when=when,
                label=(
                    f"Invoice {f.reference}"
                    if is_en
                    else f"Facture {f.reference}"
                ),
                amount=float(f.total or 0),
                detail=status,
            )
        )
    for p in payments:
        # Map facture_id → reference pour un libellé lisible
        ref = next(
            (f.reference for f in factures if f.id == p.facture_id),
            None,
        )
        method = method_labels.get(
            (p.method or "").lower(), (p.method or "").replace("_", " ")
        )
        detail_parts = [method]
        if p.reference:
            detail_parts.append(
                f"ref. {p.reference}" if is_en else f"réf. {p.reference}"
            )
        if is_en:
            label = (
                f"Payment received — Invoice {ref}"
                if ref
                else "Payment received"
            )
        else:
            label = (
                f"Paiement reçu — Facture {ref}"
                if ref
                else "Paiement reçu"
            )
        lines.append(
            StatementLine(
                kind="payment",
                when=p.paid_at,
                label=label,
                amount=float(p.amount or 0),
                detail=" · ".join(x for x in detail_parts if x),
            )
        )
    # Tri chronologique global, factures avant paiements le même jour.
    lines.sort(key=lambda x: (x.when, 0 if x.kind == "facture" else 1))

    contract_total = float(sm.total or 0) if sm else 0.0
    billed_to_date = round(sum(float(f.total or 0) for f in factures), 2)
    paid_to_date = round(sum(float(p.amount or 0) for p in payments), 2)

    # Part « extras » du facturé (taxes incluses). On répartit le total
    # de chaque facture entre contrat et extras au prorata des lignes
    # (FactureItem.kind == "extra"), via le ratio TTC/HT de la facture.
    extras_billed = 0.0
    if facture_ids:
        item_rows = (
            await db.execute(
                select(
                    FactureItem.facture_id,
                    FactureItem.total,
                    FactureItem.kind,
                ).where(FactureItem.facture_id.in_(facture_ids))
            )
        ).all()
        extra_ht_by_fac: dict[int, float] = {}
        for _fid, _it_total, _it_kind in item_rows:
            if (_it_kind or "") == "extra":
                extra_ht_by_fac[_fid] = extra_ht_by_fac.get(_fid, 0.0) + float(
                    _it_total or 0
                )
        for f in factures:
            ex_ht = extra_ht_by_fac.get(f.id, 0.0)
            if ex_ht <= 0:
                continue
            sub = float(f.subtotal or 0)
            ratio = (float(f.total or 0) / sub) if sub > 0 else 1.0
            extras_billed += ex_ht * ratio
        extras_billed = round(extras_billed, 2)

    # Solde réel = ce qui a été FACTURÉ (contrat + extras) moins le payé.
    # Avant on calculait contrat − payé, ce qui affichait un faux
    # « trop-payé » dès qu'il y avait des extras sur les factures.
    remaining = round(billed_to_date - paid_to_date, 2)

    return Statement(
        project_name=project.name,
        soumission_reference=sm.reference if sm else None,
        client_name=client.name if client is not None else None,
        lines=lines,
        contract_total=round(contract_total, 2),
        billed_to_date=billed_to_date,
        paid_to_date=paid_to_date,
        remaining_balance=remaining,
        extras_billed=extras_billed,
        lang=lang,
    )


async def _load_statement(
    db: AsyncSession, fa: Facture
) -> Optional[Statement]:
    """État de compte du projet rattaché à `fa`. None si la facture
    n'est pas liée à un projet."""
    if fa.project_id is None:
        return None
    project = (
        await db.execute(
            select(Project).where(Project.id == fa.project_id)
        )
    ).scalar_one_or_none()
    if project is None:
        return None
    # Le relevé annexé à une facture reste en français (la facture
    # elle-même l'est) ; seul le relevé autonome suit la langue client.
    return await _build_statement(db, project, force_lang="fr")


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

    story.append(Paragraph("MODES DE PAIEMENT ACCEPTÉS", s["accent"]))
    story.append(Paragraph(
        "&bull; <b>Dépôt direct</b> (paiement de la facture)<br/>"
        "&bull; <b>Virement Interac</b>",
        s["small"],
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Informations pour dépôt direct", s["accent"]))
    story.append(Paragraph(
        f"Entreprise : <b>{COMPANY_NAME}</b><br/>"
        "Institution : <b>815</b><br/>"
        "Transit : <b>92004</b><br/>"
        "Compte : <b>0935973</b>",
        s["small"],
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Virement Interac : <b>admin@immohorizon.com</b>",
        s["small"],
    ))
    story.append(Spacer(1, 6))
    if tax_gst or tax_qst:
        tps_line = f"TPS : <b>{tax_gst}</b>" if tax_gst else ""
        tvq_line = f"TVQ : <b>{tax_qst}</b>" if tax_qst else ""
        sep = "<br/>" if tps_line and tvq_line else ""
        story.append(Paragraph(f"{tps_line}{sep}{tvq_line}", s["small"]))
        story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Les taxes TPS (5 %) et TVQ (9,975 %) sont applicables. "
        "Paiement dû à la date d'échéance indiquée ci-dessus.",
        s["small"],
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "<b>Tout retard de paiement après l'échéance est facturé "
        "à 2 % par mois (24 % par an), conformément à nos "
        "conditions générales.</b>",
        s["small"],
    ))

    # Facture finale : texte de reconnaissance + bloc de signature du
    # client. Le client confirme que la soumission de base est
    # complétée; les travaux supplémentaires sont par entente.
    if getattr(fa, "is_final", False):
        story.append(Spacer(1, 16))
        story.append(Paragraph("FACTURE FINALE", s["accent"]))
        story.append(Paragraph(
            "En signant cette facture finale, le client reconnaît que "
            "la totalité des travaux prévus à la soumission de base a "
            "été complétée à sa satisfaction. Tout travail "
            "supplémentaire est facturé séparément, par entente "
            "mutuelle entre le client et "
            f"{COMPANY_NAME}.",
            s["small"],
        ))
        story.append(Spacer(1, 10))
        sig_cell: list = [Paragraph("<b>CLIENT</b>", s["accent"])]
        sig_img = getattr(fa, "signature_image", None)
        if sig_img:
            try:
                sig_cell.append(
                    Image(io.BytesIO(sig_img), width=46 * mm, height=18 * mm)
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Signature image illisible: %s", exc)
                sig_cell.append(Spacer(1, 18))
        else:
            sig_cell.append(Spacer(1, 18))
        sig_cell.append(
            Paragraph("_______________________________", s["small"])
        )
        sig_cell.append(Paragraph(
            fa.signed_name or "Nom : ____________________", s["body"]
        ))
        sig_cell.append(Paragraph(
            f"Date : {_date(fa.signed_at)}"
            if fa.signed_at
            else "Date : ____________________",
            s["small"],
        ))
        sig_tbl = Table([[sig_cell]], colWidths=[doc.width * 0.55])
        sig_tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(sig_tbl)

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

        st_data = [["Date", "Description", "Détail", "Facturé", "Payé"]]
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
        recap_rows.append(
            ["Total facturé", _money(statement.billed_to_date)]
        )
        if statement.extras_billed > 0:
            recap_rows.append(
                ["dont extras (hors contrat)", _money(statement.extras_billed)]
            )
        recap_rows.extend([
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
    # Fallback hardcodé si QBO non configuré ou indisponible. Évite que
    # la section Modalités de la facture sorte sans TPS/TVQ.
    fallback_gst = "783649148TQ0001"
    fallback_qst = "1228151242TQ0001"
    try:
        from app.integrations.quickbooks import get_qbo
        qbo = get_qbo()
        if not qbo.ready:
            return fallback_gst, fallback_qst
        nums = await qbo.tax_registration_numbers()
        gst = nums.get("gst") or fallback_gst
        qst = nums.get("qst") or fallback_qst
        return gst, qst
    except Exception as exc:
        log.warning("Could not fetch QBO tax numbers: %s", exc)
        return fallback_gst, fallback_qst


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


def _render_statement_bytes(statement: Statement) -> bytes:
    """Rend l'état de compte d'un projet dans un PDF autonome — le
    relevé que le client peut consulter : factures envoyées, paiements
    reçus, total des factures et solde dû."""
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

    ParagraphStyle = rl["ParagraphStyle"]
    base = rl["getSampleStyleSheet"]()
    # Titre « ÉTAT DE COMPTE » plus court que la facture : 18 pt pour
    # tenir sur une ligne dans la cellule droite de l'en-tête.
    s = {
        "h1": ParagraphStyle(
            "h1", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=18, leading=22, textColor=DARK,
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

    # Le relevé est rendu dans la langue du client (fr par défaut).
    lang = statement.lang if statement.lang in ("fr", "en") else "fr"
    _T = {
        "fr": {
            "doc_title": "État de compte",
            "title": "ÉTAT DE COMPTE",
            "issued": "Émis le",
            "client": "CLIENT",
            "project": "Projet :",
            "quote": "Soumission :",
            "h_date": "Date",
            "h_desc": "Description",
            "h_detail": "Détail",
            "h_debit": "Facturé",
            "h_credit": "Payé",
            "empty": "Aucune facture envoyée au client pour ce projet.",
            "total_invoiced": "Total des factures",
            "extras_billed": "dont extras (hors contrat)",
            "amount_paid": "Montant payé",
            "balance_due": "Solde dû",
        },
        "en": {
            "doc_title": "Account statement",
            "title": "ACCOUNT STATEMENT",
            "issued": "Issued on",
            "client": "CLIENT",
            "project": "Project:",
            "quote": "Quote:",
            "h_date": "Date",
            "h_desc": "Description",
            "h_detail": "Detail",
            "h_debit": "Invoiced",
            "h_credit": "Paid",
            "empty": "No invoice sent to the client for this project.",
            "total_invoiced": "Total invoiced",
            "extras_billed": "incl. extras (off-contract)",
            "amount_paid": "Amount paid",
            "balance_due": "Balance due",
        },
    }
    tr = _T[lang]

    buf = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buf, pagesize=rl["letter"],
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=tr["doc_title"], author=COMPANY_NAME,
    )
    story: list = []

    left_cell: list = []
    _logo_src = _logo_light_source()
    if _logo_src is not None:
        try:
            left_cell.append(
                Image(_logo_src, width=28 * mm, height=28 * mm)
            )
            left_cell.append(Spacer(1, 4))
        except Exception as exc:
            log.warning("Could not embed logo in statement PDF: %s", exc)
    left_cell.extend([
        Paragraph(f"<b>{COMPANY_NAME}</b>", s["h2"]),
        Paragraph(COMPANY_RBQ, s["small"]),
        Paragraph(f"{COMPANY_SITE} &middot; {COMPANY_EMAIL}", s["small"]),
    ])
    right_cell: list = [
        Paragraph(tr["title"], s["h1"]),
        Paragraph(f"{tr['issued']} {_date(datetime.utcnow())}", s["small"]),
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

    info: list[str] = []
    if statement.client_name:
        info.append(f"<b>{statement.client_name}</b>")
    if statement.project_name:
        info.append(f"{tr['project']} {statement.project_name}")
    if statement.soumission_reference:
        info.append(f"{tr['quote']} {statement.soumission_reference}")
    if info:
        story.append(Paragraph(tr["client"], s["accent"]))
        for line in info:
            story.append(Paragraph(line, s["body"]))
        story.append(Spacer(1, 12))

    if statement.lines:
        st_data = [[
            tr["h_date"], tr["h_desc"], tr["h_detail"],
            tr["h_debit"], tr["h_credit"],
        ]]
        for ln in statement.lines:
            if ln.kind == "facture":
                debit, credit = ln.amount, 0.0
            else:
                debit, credit = 0.0, ln.amount
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
    else:
        story.append(Paragraph(f"<i>{tr['empty']}</i>", s["small"]))
    story.append(Spacer(1, 12))

    # Récap client : total des factures envoyées, montant déjà payé,
    # et solde restant dû (total facturé − payé).
    solde_du = round(statement.billed_to_date - statement.paid_to_date, 2)
    recap_rows = [
        [tr["total_invoiced"], _money(statement.billed_to_date)],
    ]
    if statement.extras_billed > 0:
        recap_rows.append(
            [tr["extras_billed"], _money(statement.extras_billed)]
        )
    recap_rows.extend([
        [tr["amount_paid"], _money(statement.paid_to_date)],
        [tr["balance_due"], _money(solde_du)],
    ])
    recap_tbl = Table(
        recap_rows, colWidths=[doc.width * 0.30, doc.width * 0.20],
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
    story.append(Spacer(1, 16))
    story.append(Paragraph(
        f"{COMPANY_NAME} &middot; {COMPANY_RBQ} &middot; {COMPANY_EMAIL}",
        s["small"],
    ))

    doc.build(story)
    return buf.getvalue()


async def render_statement_pdf(
    db: AsyncSession, project_id: int
) -> Optional[tuple[Project, bytes]]:
    """Génère le PDF autonome « État de compte » d'un projet. None si
    le projet est introuvable."""
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        return None
    statement = await _build_statement(db, project)
    return project, _render_statement_bytes(statement)
