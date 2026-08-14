"""Relevé annuel PDF d'un investisseur (Portail Investisseur v2).

Une page sobre par année : KPIs du portefeuille au 31 décembre (ou à
aujourd'hui pour l'année courante), flux de l'année, détail par
compagnie. Généré à la demande — jamais stocké.
"""

from __future__ import annotations

import io
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


def _money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f} $".replace(",", " ")


async def build_releve_pdf(
    db: AsyncSession, user: User, year: int, portefeuille: dict
) -> bytes:
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

    from app.models.invest_portal import InvestFlux, InvestParticipation
    from sqlalchemy import select

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=f"Relevé annuel {year}",
    )
    st_h1 = ParagraphStyle(
        "h1", fontName="Helvetica-Bold", fontSize=17, leading=21,
        textColor=colors.HexColor("#111827"),
    )
    st_meta = ParagraphStyle(
        "meta", fontName="Helvetica", fontSize=9.5, leading=13,
        textColor=colors.HexColor("#4b5563"),
    )
    st_h2 = ParagraphStyle(
        "h2", fontName="Helvetica-Bold", fontSize=12, leading=15,
        textColor=colors.HexColor("#111827"), spaceBefore=14,
        spaceAfter=5,
    )
    st_cell = ParagraphStyle(
        "cell", fontName="Helvetica", fontSize=9, leading=12,
        textColor=colors.HexColor("#111827"),
    )
    st_cell_b = ParagraphStyle(
        "cellb", fontName="Helvetica-Bold", fontSize=9, leading=12,
        textColor=colors.HexColor("#111827"),
    )

    name = (
        f"{user.first_name or ''} {user.last_name or ''}".strip()
        or user.email
    )
    flow = [
        Paragraph(f"Relevé annuel {year}", st_h1),
        Paragraph(
            f"{name} · préparé le "
            f"{date.today().strftime('%Y-%m-%d')} · "
            "Horizon Services Immobiliers",
            st_meta,
        ),
        Spacer(1, 8),
    ]

    # ── KPIs du portefeuille (valeurs actuelles) ──
    kpi_rows = [
        [
            Paragraph("Capital actuellement investi", st_cell),
            Paragraph(_money(portefeuille["capital_actuel"]), st_cell_b),
        ],
        [
            Paragraph("Capital investi au total", st_cell),
            Paragraph(
                _money(portefeuille["capital_investi_total"]), st_cell_b
            ),
        ],
        [
            Paragraph("Capital remboursé", st_cell),
            Paragraph(_money(portefeuille["capital_rembourse"]), st_cell_b),
        ],
        [
            Paragraph("Distributions reçues", st_cell),
            Paragraph(
                _money(portefeuille["distributions_recues"]), st_cell_b
            ),
        ],
        [
            Paragraph("Valeur des parts", st_cell),
            Paragraph(_money(portefeuille["valeur_parts"]), st_cell_b),
        ],
        [
            Paragraph("TRI réalisé", st_cell),
            Paragraph(
                f"{portefeuille['tri_pct']} %"
                if portefeuille["tri_pct"] is not None
                else "—",
                st_cell_b,
            ),
        ],
    ]
    t = Table(kpi_rows, colWidths=[95 * mm, 75 * mm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(t)

    # ── Projets ──
    flow.append(Paragraph("Vos projets", st_h2))
    proj_rows = [[
        Paragraph("Compagnie", st_cell_b),
        Paragraph("Part", st_cell_b),
        Paragraph("Capital actuel", st_cell_b),
        Paragraph("Valeur des parts", st_cell_b),
        Paragraph("TRI", st_cell_b),
    ]]
    for p in portefeuille["projets"]:
        proj_rows.append([
            Paragraph(p["entreprise_name"], st_cell),
            Paragraph(f"{p['parts_pct']:g} %", st_cell),
            Paragraph(_money(p["capital_actuel"]), st_cell),
            Paragraph(_money(p["valeur_parts"]), st_cell),
            Paragraph(
                f"{p['tri_pct']} %" if p["tri_pct"] is not None else "—",
                st_cell,
            ),
        ])
    t = Table(
        proj_rows, colWidths=[62 * mm, 20 * mm, 30 * mm, 32 * mm, 26 * mm]
    )
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(t)

    # ── Flux de l'année ──
    flux_rows = [[
        Paragraph("Date", st_cell_b),
        Paragraph("Compagnie", st_cell_b),
        Paragraph("Type", st_cell_b),
        Paragraph("Montant", st_cell_b),
    ]]
    labels = {
        "apport": "Apport de capital",
        "remboursement": "Remboursement de capital",
        "dividende": "Distribution",
        "sortie": "Sortie",
    }
    ent_names = {
        p["entreprise_id"]: p["entreprise_name"]
        for p in portefeuille["projets"]
    }
    rows = (
        await db.execute(
            select(InvestFlux, InvestParticipation)
            .join(
                InvestParticipation,
                InvestParticipation.id == InvestFlux.participation_id,
            )
            .where(InvestParticipation.user_id == user.id)
            .order_by(InvestFlux.date_flux)
        )
    ).all()
    for f, part in rows:
        if f.date_flux.year != year:
            continue
        flux_rows.append([
            Paragraph(f.date_flux.isoformat(), st_cell),
            Paragraph(
                ent_names.get(part.entreprise_id, "—"), st_cell
            ),
            Paragraph(labels.get(f.type, f.type), st_cell),
            Paragraph(_money(float(f.montant)), st_cell),
        ])
    flow.append(Paragraph(f"Mouvements de {year}", st_h2))
    if len(flux_rows) == 1:
        flow.append(
            Paragraph(f"Aucun mouvement en {year}.", st_meta)
        )
    else:
        t = Table(
            flux_rows, colWidths=[28 * mm, 70 * mm, 42 * mm, 30 * mm]
        )
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(t)

    flow.append(Spacer(1, 10))
    flow.append(
        Paragraph(
            "Les valeurs de parts reposent sur l'évaluation de référence "
            "des immeubles moins la balance hypothécaire au moment de la "
            "génération. Le TRI est calculé sur les flux datés réels "
            "(méthode XIRR). Document informatif — ne constitue pas un "
            "avis fiscal.",
            st_meta,
        )
    )
    pdf.build(flow)
    return buf.getvalue()
