"""PDF « Planification des travaux » destiné au CLIENT (retour 2026-09-23).

Depuis l'onglet Planification d'un projet : un document propre avec les
phases et leurs dates prévues (début → fin, durée en jours), suivi d'un
visuel agenda mois par mois où chaque phase apparaît en couleur sur ses
journées. VOLONTAIREMENT sans heures, sans coûts, sans assignés, sans
notes internes : c'est la version client.

Fin d'une phase = début + durée (jours) − 1, inclusivement — même règle
que l'onglet (une phase de 1 jour commence et finit le même jour).
"""

from __future__ import annotations

import calendar
import io
import logging
import math
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.project import Project
from app.models.project_phase import ProjectPhase
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

#: Couleurs des phases (texte blanc lisible dessus, ≥ 4.5:1).
PHASE_COLORS = [
    "#1d4ed8", "#b45309", "#047857", "#7c3aed",
    "#be185d", "#0e7490", "#4d7c0f", "#9a3412",
]

_MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
    "août", "septembre", "octobre", "novembre", "décembre",
]
_JOURS_COURT = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
#: Nombre maximal de mois dessinés dans l'agenda (au-delà, on tronque et
#: on le dit) — un projet ne s'étale pas sur des années de calendrier.
MAX_MONTHS = 12


def _date_fr(d: Optional[date]) -> str:
    if not d:
        return "—"
    return f"{_JOURS_COURT[d.weekday()]} {d.day} {_MOIS[d.month - 1]} {d.year}"


def phase_bounds(ph: ProjectPhase) -> Optional[tuple[date, date, int]]:
    """(début, fin inclusive, durée en jours) — None si la phase n'est
    pas datée."""
    if not ph.start_date:
        return None
    dur = ph.duration_days
    days = max(1, int(math.ceil(float(dur)))) if dur else 1
    start = ph.start_date
    return start, start + timedelta(days=days - 1), days


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_bytes(
    project: Project,
    client: Optional[Client],
    phases: list[ProjectPhase],
) -> bytes:
    rl = _lazy_reportlab()
    colors = rl["colors"]
    mm = rl["mm"]
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Image = rl["Image"]
    PageBreak = rl["PageBreak"]
    ParagraphStyle = rl["ParagraphStyle"]
    DARK = colors.HexColor(DARK_HEX)
    MUTED = colors.HexColor(MUTED_HEX)
    ACCENT = colors.HexColor(ACCENT_HEX)
    LINE = colors.HexColor(LINE_HEX)
    WEEKEND = colors.HexColor("#f3f4f6")
    base = rl["getSampleStyleSheet"]()
    s: dict[str, Any] = {
        "h1": ParagraphStyle(
            "h1", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=18, leading=22, textColor=DARK,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=11, leading=14, textColor=DARK, spaceBefore=6,
        ),
        "month": ParagraphStyle(
            "month", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=13, leading=16, textColor=DARK, spaceBefore=10,
            spaceAfter=4,
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
        "th": ParagraphStyle(
            "th", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8.5, leading=11, textColor=MUTED,
        ),
        "day": ParagraphStyle(
            "day", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8, leading=9, textColor=DARK,
        ),
        "daymuted": ParagraphStyle(
            "daymuted", parent=base["Normal"], fontName="Helvetica",
            fontSize=8, leading=9, textColor=colors.HexColor("#9ca3af"),
        ),
    }
    bar_styles = [
        ParagraphStyle(
            f"bar{i}", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=6.5, leading=8, textColor=colors.white,
            backColor=colors.HexColor(hx), borderPadding=(1, 2, 1, 2),
            spaceBefore=3,
        )
        for i, hx in enumerate(PHASE_COLORS)
    ]

    buf = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buf, pagesize=rl["letter"],
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Planification — {project.name}", author=COMPANY_NAME,
    )
    story: list = []

    # ── En-tête ────────────────────────────────────────────────────
    left_cell: list = []
    if os.path.exists(_LOGO_PATH):
        try:
            left_cell.append(Image(_LOGO_PATH, width=26 * mm, height=26 * mm))
            left_cell.append(Spacer(1, 4))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not embed logo: %s", exc)
    left_cell.extend([
        Paragraph(f"<b>{COMPANY_NAME}</b>", s["h2"]),
        Paragraph(COMPANY_RBQ, s["small"]),
        Paragraph(f"{COMPANY_SITE} &middot; {COMPANY_EMAIL}", s["small"]),
    ])
    right_cell: list = [
        Paragraph("PLANIFICATION DES TRAVAUX", s["h1"]),
        Paragraph("Dates prévues des phases", s["accent"]),
        Paragraph(
            f"Émis le {_date_fr(datetime.now().date())}", s["small"]
        ),
    ]
    head = Table([[left_cell, right_cell]], colWidths=[80 * mm, 100 * mm])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(head)
    story.append(Spacer(1, 8))

    # ── Projet / client ───────────────────────────────────────────
    info_rows = [[
        Paragraph("PROJET", s["th"]),
        Paragraph("CLIENT", s["th"]),
    ], [
        [
            Paragraph(f"<b>{_escape(project.name)}</b>", s["body"]),
            Paragraph(_escape(project.address or ""), s["small"]),
        ],
        [
            Paragraph(
                f"<b>{_escape(client.name)}</b>" if client else "—",
                s["body"],
            ),
            Paragraph(
                _escape((client.address or "") if client else ""), s["small"]
            ),
        ],
    ]]
    info = Table(info_rows, colWidths=[90 * mm, 90 * mm])
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
    ]))
    story.append(info)
    story.append(Spacer(1, 10))

    # ── Phases datées, ordonnées par début ─────────────────────────
    dated: list[tuple[ProjectPhase, date, date, int]] = []
    undated: list[ProjectPhase] = []
    for ph in phases:
        b = phase_bounds(ph)
        if b is None:
            undated.append(ph)
        else:
            dated.append((ph, b[0], b[1], b[2]))
    dated.sort(key=lambda t: (t[1], t[0].position, t[0].id))

    story.append(Paragraph("Phases et dates prévues", s["h2"]))
    if not dated and not undated:
        story.append(Paragraph("Aucune phase planifiée pour l'instant.", s["body"]))
    else:
        rows: list = [[
            Paragraph("", s["th"]),
            Paragraph("PHASE", s["th"]),
            Paragraph("DÉBUT", s["th"]),
            Paragraph("FIN", s["th"]),
            Paragraph("DURÉE", s["th"]),
        ]]
        for i, (ph, start, end, days) in enumerate(dated):
            rows.append([
                Paragraph(str(i + 1), bar_styles[i % len(bar_styles)]),
                Paragraph(_escape(ph.name), s["body"]),
                Paragraph(_date_fr(start), s["body"]),
                Paragraph(_date_fr(end), s["body"]),
                Paragraph(f"{days} jour{'s' if days > 1 else ''}", s["body"]),
            ])
        for ph in undated:
            rows.append([
                Paragraph("", s["body"]),
                Paragraph(_escape(ph.name), s["body"]),
                Paragraph("à planifier", s["small"]),
                Paragraph("—", s["small"]),
                Paragraph("—", s["small"]),
            ])
        t = Table(rows, colWidths=[9 * mm, 77 * mm, 36 * mm, 36 * mm, 22 * mm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t)
        if dated:
            first = min(d[1] for d in dated)
            last = max(d[2] for d in dated)
            story.append(Spacer(1, 6))
            story.append(Paragraph(
                f"Travaux prévus du <b>{_date_fr(first)}</b> au "
                f"<b>{_date_fr(last)}</b>.", s["body"],
            ))

    # ── Agenda mois par mois ──────────────────────────────────────
    if dated:
        first = min(d[1] for d in dated)
        last = max(d[2] for d in dated)
        months: list[tuple[int, int]] = []
        y, m = first.year, first.month
        while (y, m) <= (last.year, last.month) and len(months) < MAX_MONTHS:
            months.append((y, m))
            m += 1
            if m > 12:
                m, y = 1, y + 1
        truncated = (y, m) <= (last.year, last.month)

        story.append(PageBreak())
        story.append(Paragraph("Agenda des travaux", s["h1"]))
        story.append(Paragraph(
            "Chaque couleur correspond à une phase (numéro dans le tableau).",
            s["small"],
        ))
        # Légende
        legend_cells: list = []
        for i, (ph, _s, _e, _d) in enumerate(dated):
            legend_cells.append([
                Paragraph(str(i + 1), bar_styles[i % len(bar_styles)]),
                Paragraph(_escape(ph.name), s["small"]),
            ])
        if legend_cells:
            per_row = 2
            legend_rows = [
                sum(legend_cells[r:r + per_row], [])
                for r in range(0, len(legend_cells), per_row)
            ]
            for row in legend_rows:
                while len(row) < per_row * 2:
                    row.extend([Paragraph("", s["small"]), Paragraph("", s["small"])])
            lg = Table(legend_rows, colWidths=[8 * mm, 82 * mm] * per_row)
            lg.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            story.append(Spacer(1, 4))
            story.append(lg)

        col_w = 180 * mm / 7
        for (yy, mm_) in months:
            story.append(Paragraph(
                f"{_MOIS[mm_ - 1].capitalize()} {yy}", s["month"]
            ))
            weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(yy, mm_)
            grid: list = [[Paragraph(j.upper(), s["th"]) for j in _JOURS_COURT]]
            style_cmds = [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 1), (-1, -1), 0.4, LINE),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
            for wi, week in enumerate(weeks, start=1):
                row: list = []
                for di, dnum in enumerate(week):
                    if dnum == 0:
                        row.append(Paragraph("", s["daymuted"]))
                        continue
                    day = date(yy, mm_, dnum)
                    cell: list = [Paragraph(str(dnum), s["day"])]
                    active = [
                        i for i, (_ph, st, en, _d) in enumerate(dated)
                        if st <= day <= en
                    ]
                    shown = active[:3]
                    for i in shown:
                        cell.append(Paragraph(
                            f"{i + 1} · {_escape(dated[i][0].name)[:18]}",
                            bar_styles[i % len(bar_styles)],
                        ))
                    if len(active) > 3:
                        cell.append(Paragraph(
                            f"+{len(active) - 3}", s["daymuted"]
                        ))
                    row.append(cell)
                    if di >= 5:
                        style_cmds.append(
                            ("BACKGROUND", (di, wi), (di, wi), WEEKEND)
                        )
                grid.append(row)
            cal = Table(
                grid, colWidths=[col_w] * 7,
                rowHeights=[8 * mm] + [None] * len(weeks),
            )
            cal.setStyle(TableStyle(style_cmds))
            story.append(cal)
        if truncated:
            story.append(Spacer(1, 6))
            story.append(Paragraph(
                f"Agenda limité aux {MAX_MONTHS} premiers mois ; le tableau "
                "ci-dessus reste complet.", s["small"],
            ))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Ces dates sont prévisionnelles et peuvent être ajustées selon la "
        "météo, les livraisons et les imprévus de chantier. Nous vous "
        "tiendrons informé de tout changement.", s["small"],
    ))

    doc.build(story)
    return buf.getvalue()


async def render_planification_client_pdf(
    db: AsyncSession, project_id: int
) -> Optional[tuple[Project, bytes]]:
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        return None
    client: Optional[Client] = None
    if project.client_id:
        client = (
            await db.execute(select(Client).where(Client.id == project.client_id))
        ).scalar_one_or_none()
    phases = list(
        (
            await db.execute(
                select(ProjectPhase)
                .where(ProjectPhase.project_id == project_id)
                .order_by(ProjectPhase.position.asc(), ProjectPhase.id.asc())
            )
        ).scalars().all()
    )
    return project, _render_bytes(project, client, phases)
