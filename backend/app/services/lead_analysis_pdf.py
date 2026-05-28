"""Génère le PDF complet d'une `LeadAnalysis` — export d'aide à la
décision pour les associés et collaborateurs prospection.

Layout A4 portrait, polices Helvetica/Helvetica-Bold, accent bleu
Horizon (#1d4ed8) cohérent avec `nda_pdf.py`. Pagination automatique
via `SimpleDocTemplate` + pied de page sur chaque page (`onLaterPages`
+ `onFirstPage`).

Sections (dans cet ordre) :
    1. En-tête (logo + titre + identité de l'immeuble)
    2. Informations financières — état actuel
    3. Typologie des logements
    4. Inputs manuels d'analyse
    5. Composition MDF prêteur B
    6. Scénarios de financement (4 encarts)
    7. Meilleur scénario refi (avec RCI/PVI calculés)
    8. Validation (warnings post-extraction)
    9. Sources & attachments

ReportLab pur Python — pas de dépendance système, compatible Render
Free. Aucune persistance : on régénère à la volée à chaque export.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_analysis import (
    LeadAnalysis,
    LeadAnalysisAttachment,
)


log = logging.getLogger(__name__)


_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "logo.png",
)

# Mois français-CA pour formater la date de génération au format
# « 28 mai 2026 » plutôt que « 2026-05-28 ».
_MONTHS_FR_CA = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)

# Ordre canonique des typologies dans le tableau.
_TYPO_ORDER = ("1.5", "2.5", "3.5", "4.5", "5.5", "6.5", "7.5", "8.5")


def _lazy_reportlab() -> Dict[str, Any]:
    from reportlab.lib import colors  # type: ignore
    from reportlab.lib.pagesizes import A4  # type: ignore
    from reportlab.lib.styles import (  # type: ignore
        ParagraphStyle,
        getSampleStyleSheet,
    )
    from reportlab.lib.units import mm  # type: ignore
    from reportlab.platypus import (  # type: ignore
        Image,
        KeepTogether,
        PageBreak,
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
        "KeepTogether": KeepTogether,
        "PageBreak": PageBreak,
        "Paragraph": Paragraph,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
    }


def _money(n: Optional[float | int]) -> str:
    """Format français-CA, ex. « 1 234 567 $ » (entier). Identique au
    helper `formatMoney` côté frontend."""
    if n is None:
        return "—"
    try:
        rounded = round(float(n))
    except (TypeError, ValueError):
        return "—"
    sign = "-" if rounded < 0 else ""
    abs_str = f"{abs(rounded):,}".replace(",", " ")
    return f"{sign}{abs_str} $"


def _money_decimal(n: Optional[float | int]) -> str:
    """Format avec décimales pour montants précis (mensualités)."""
    if n is None:
        return "—"
    try:
        return f"{float(n):,.2f} $".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _pct(n: Optional[float | int], decimals: int = 2) -> str:
    if n is None:
        return "—"
    try:
        return f"{float(n):.{decimals}f} %"
    except (TypeError, ValueError):
        return "—"


def _int(n: Optional[float | int]) -> str:
    if n is None:
        return "—"
    try:
        return str(int(n))
    except (TypeError, ValueError):
        return "—"


def _str(s: Optional[str]) -> str:
    if s is None or not str(s).strip():
        return "—"
    return str(s)


def _date_fr_ca_long(d) -> str:
    """Formate une date au format français-CA long, ex: « 28 mai 2026 »."""
    if d is None:
        return "—"
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.day} {_MONTHS_FR_CA[d.month - 1]} {d.year}"


def _styles(rl: Dict[str, Any]):
    PS = rl["ParagraphStyle"]
    base = rl["getSampleStyleSheet"]()
    colors = rl["colors"]
    dark = colors.HexColor("#111111")
    muted = colors.HexColor("#6b6b6b")
    # Bleu Horizon — cohérent avec `nda_pdf.py`.
    accent = colors.HexColor("#1d4ed8")
    return {
        "title": PS(
            "title", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=18, leading=22,
            textColor=dark, alignment=1,
        ),
        "subtitle": PS(
            "subtitle", parent=base["Normal"],
            fontName="Helvetica-Oblique", fontSize=10, leading=13,
            textColor=muted, alignment=1,
        ),
        "section": PS(
            "section", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=11, leading=14,
            textColor=colors.white, backColor=accent,
            leftIndent=4, rightIndent=4,
            spaceBefore=10, spaceAfter=4, borderPadding=4,
        ),
        "subsection": PS(
            "subsection", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=10, leading=13,
            textColor=dark, spaceBefore=6, spaceAfter=2,
        ),
        "body": PS(
            "body", parent=base["Normal"],
            fontName="Helvetica", fontSize=10, leading=13,
            textColor=dark, spaceAfter=3,
        ),
        "small": PS(
            "small", parent=base["Normal"],
            fontName="Helvetica", fontSize=9, leading=12,
            textColor=dark,
        ),
        "small_muted": PS(
            "small_muted", parent=base["Normal"],
            fontName="Helvetica", fontSize=8, leading=11,
            textColor=muted,
        ),
        "info_ok": PS(
            "info_ok", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=10, leading=13,
            textColor=colors.HexColor("#065f46"),
            backColor=colors.HexColor("#d1fae5"),
            borderColor=colors.HexColor("#10b981"),
            borderWidth=0.5, borderPadding=6,
            spaceBefore=4, spaceAfter=4,
        ),
    }


def _table_two_col(rl, rows, *, s):
    """Tableau 2 colonnes (libellé / valeur) avec style cohérent."""
    Paragraph = rl["Paragraph"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    mm = rl["mm"]
    colors = rl["colors"]

    data = [
        [Paragraph(str(k), s["small"]), Paragraph(str(v), s["small"])]
        for k, v in rows
    ]
    if not data:
        return None
    t = Table(data, colWidths=[70 * mm, "*"])
    t.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25,
             colors.HexColor("#e2e2e2")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
    )
    return t


def _safe_json_load(raw: Optional[str]) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


def _ecart_pct(asking: Optional[float], eval_muni: Optional[float]) -> str:
    """Écart % entre prix demandé et évaluation municipale."""
    try:
        a = float(asking or 0)
        e = float(eval_muni or 0)
        if e <= 0 or a <= 0:
            return "—"
        return f"{((a - e) / e) * 100:+.1f} %"
    except Exception:  # noqa: BLE001
        return "—"


def _loyer_mois_moyen(
    revenus_bruts: Optional[float], nb_log: Optional[int]
) -> str:
    try:
        r = float(revenus_bruts or 0)
        n = int(nb_log or 0)
        if r <= 0 or n <= 0:
            return "—"
        return _money(r / 12.0 / n)
    except Exception:  # noqa: BLE001
        return "—"


def _draw_footer(canvas, doc, *, address_label: str):
    """Pied de page : adresse + numéro de page + date."""
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColorRGB(0.42, 0.42, 0.42)
    page_w, page_h = doc.pagesize
    bottom_y = 10  # mm équivalent ≈ 28 pt
    canvas.drawString(
        20 * 2.83465,  # 20 mm
        bottom_y,
        f"Fiche d'analyse — {address_label[:70]}",
    )
    canvas.drawRightString(
        page_w - 20 * 2.83465,
        bottom_y,
        f"Page {doc.page}",
    )
    canvas.restoreState()


def _depenses_rows(
    rec: LeadAnalysis, results: Optional[dict]
) -> List[tuple]:
    """Lignes du tableau des dépenses (état actuel — sans inoccupation,
    cohérent avec ce que l'utilisateur a saisi)."""
    rows: List[tuple] = []
    rows.append(("Taxes municipales", _money(rec.taxes_municipales)))
    rows.append(("Taxes scolaires", _money(rec.taxes_scolaires)))
    rows.append(("Assurances", _money(rec.assurances)))
    rows.append(("Énergie", _money(rec.energie)))
    rows.append(("Autres dépenses", _money(rec.depenses_autres)))
    # Inoccupation : pris depuis les résultats si dispo (sinon défaut 3 %).
    inocc_pct = None
    if results:
        try:
            inocc_pct = float(results.get("taux_inoccupation_pct") or 0) * 100
        except Exception:  # noqa: BLE001
            inocc_pct = None
    if inocc_pct is None:
        inocc_pct = 3.0
    rows.append(("Taux d'inoccupation", _pct(inocc_pct, decimals=1)))
    return rows


def _typology_section(rl, typology: Dict[str, int], *, s) -> Any:
    """Tableau typologie horizontal."""
    Paragraph = rl["Paragraph"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    mm = rl["mm"]
    colors = rl["colors"]

    if not isinstance(typology, dict) or not typology:
        return Paragraph("Aucune typologie renseignée.", s["small_muted"])

    items = []
    total = 0
    for typo in _TYPO_ORDER:
        qty = int(typology.get(typo, 0) or 0)
        items.append((typo, qty))
        total += qty
    # Inclut les typologies hors ordre canonique éventuelles.
    extras = sorted(
        k for k in typology.keys()
        if k not in _TYPO_ORDER and int(typology.get(k, 0) or 0) > 0
    )
    for typo in extras:
        qty = int(typology.get(typo, 0) or 0)
        items.append((typo, qty))
        total += qty

    header_row = [Paragraph(f"<b>{k}</b>", s["small"]) for k, _ in items]
    value_row = [Paragraph(str(v), s["small"]) for _, v in items]
    header_row.append(Paragraph("<b>Total</b>", s["small"]))
    value_row.append(Paragraph(f"<b>{total}</b>", s["small"]))

    n = len(header_row)
    col_w = (170 / n) * mm
    t = Table([header_row, value_row], colWidths=[col_w] * n)
    t.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("BACKGROUND", (0, 0), (-1, 0),
             colors.HexColor("#eff6ff")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5,
             colors.HexColor("#93c5fd")),
            ("BOX", (0, 0), (-1, -1), 0.25,
             colors.HexColor("#e2e2e2")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    return t


def _scenario_card(
    rl, scen: Optional[dict], *, s, frais_demarrage_total: float
):
    """Encart d'un scénario : LTV, amort, RCD, revenus nets, financement,
    MDF/équité, mensualité, surplus."""
    Paragraph = rl["Paragraph"]
    KeepTogether = rl["KeepTogether"]
    Spacer = rl["Spacer"]

    if not scen:
        return Paragraph("Scénario non calculé.", s["small_muted"])

    ltv = scen.get("ltv")
    amort = scen.get("amort_annees")
    rcd = scen.get("rcd")
    revenus_net = scen.get("revenus_net")
    financement = scen.get("financement")
    paiement = scen.get("paiement_mensuel_actuel")
    cashflow = scen.get("cashflow_annuel")
    mdf_nec = scen.get("mdf_necessaire")
    equite = scen.get("equite_a_la_fin")

    surplus_mois = None
    try:
        if revenus_net is not None and paiement is not None:
            surplus_mois = float(revenus_net) / 12.0 - float(paiement)
    except Exception:  # noqa: BLE001
        surplus_mois = None

    fonds_necessaires = None
    if mdf_nec is not None:
        try:
            fonds_necessaires = float(mdf_nec) + float(
                frais_demarrage_total or 0
            )
        except Exception:  # noqa: BLE001
            fonds_necessaires = None

    rows = [
        ("LTV",
         f"{float(ltv) * 100:.0f} %" if ltv is not None else "—"),
        ("Amortissement",
         f"{int(amort)} ans" if amort is not None else "—"),
        ("RCD", f"{float(rcd):.2f}" if rcd is not None else "—"),
        ("Revenus nets", _money(revenus_net)),
        ("Prêt hypothécaire max", _money(financement)),
    ]
    if mdf_nec is not None:
        rows.append(("MDF requise", _money(mdf_nec)))
        if fonds_necessaires is not None:
            rows.append(
                ("Fonds nécessaires (MDF + frais démarrage)",
                 _money(fonds_necessaires))
            )
    if equite is not None:
        rows.append(("Équité dégagée au refi", _money(equite)))
    rows.append(("Mensualité hypothécaire",
                 _money_decimal(paiement)))
    if surplus_mois is not None:
        rows.append(("Surplus mensuel",
                     _money_decimal(surplus_mois)))
    if cashflow is not None:
        rows.append(("Cashflow annuel", _money(cashflow)))

    label = scen.get("label") or scen.get("name") or "Scénario"
    title = Paragraph(f"<b>{label}</b>", s["subsection"])
    table = _table_two_col(rl, rows, s=s)
    return KeepTogether([title, table or Spacer(1, 4), Spacer(1, 4)])


def _format_warning_severity(sev: Optional[str]) -> str:
    return {
        "error": "Erreur",
        "warning": "Avertissement",
        "info": "Info",
    }.get((sev or "").lower(), "Info")


def _compute_rci_pvi(
    rec: LeadAnalysis, results: Optional[dict]
) -> tuple[Optional[float], Optional[float]]:
    """RCI = équité refi / MDF achat (% capital récupéré).
       PVI = financement refi - prix d'acquisition (prise de valeur)."""
    if not results:
        return None, None
    scenarios = results.get("scenarios") or {}
    best = results.get("best_refi") or {}
    best_program = best.get("program")
    chosen = None
    for key in ("refi_aph_100", "refi_aph_50", "refi_schl"):
        scen = scenarios.get(key)
        if scen and scen.get("label") == best_program:
            chosen = scen
            break
    # Si pas de match exact, prend celui avec la plus haute équité.
    if chosen is None:
        for key in ("refi_aph_100", "refi_aph_50", "refi_schl"):
            scen = scenarios.get(key)
            if scen and scen.get("equite_a_la_fin") is not None:
                if chosen is None or (
                    float(scen.get("equite_a_la_fin") or 0)
                    > float(chosen.get("equite_a_la_fin") or 0)
                ):
                    chosen = scen

    achat = scenarios.get("achat") or {}
    mdf_achat = achat.get("mdf_necessaire")
    prix_acq = results.get("prix_acquisition")

    rci = None
    pvi = None
    if chosen is not None:
        equite = chosen.get("equite_a_la_fin")
        financement = chosen.get("financement")
        try:
            if mdf_achat and float(mdf_achat) > 0 and equite is not None:
                rci = (float(equite) / float(mdf_achat)) * 100.0
        except Exception:  # noqa: BLE001
            rci = None
        try:
            if financement is not None and prix_acq is not None:
                pvi = float(financement) - float(prix_acq)
        except Exception:  # noqa: BLE001
            pvi = None
    return rci, pvi


async def _load(
    db: AsyncSession, analysis_id: int
) -> tuple[Optional[LeadAnalysis], List[LeadAnalysisAttachment]]:
    rec = await db.get(LeadAnalysis, analysis_id)
    if rec is None:
        return None, []
    atts = list(
        (
            await db.execute(
                select(LeadAnalysisAttachment)
                .where(
                    LeadAnalysisAttachment.lead_analysis_id == analysis_id
                )
                .order_by(LeadAnalysisAttachment.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return rec, atts


def _render_bytes(
    rec: LeadAnalysis,
    attachments: List[LeadAnalysisAttachment],
) -> bytes:
    """Rend le PDF complet d'une `LeadAnalysis`."""
    rl = _lazy_reportlab()
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Image = rl["Image"]
    mm = rl["mm"]
    colors = rl["colors"]

    buf = io.BytesIO()
    address_label = (rec.address or f"Lead #{rec.id}").strip() or f"Lead #{rec.id}"
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=rl["A4"],
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title=f"Fiche d'analyse {rec.id}",
        author="MGV Développement",
    )
    s = _styles(rl)
    story: list = []

    # ── En-tête ─────────────────────────────────────────────────
    if os.path.exists(_LOGO_PATH):
        try:
            header_logo = Image(_LOGO_PATH, width=20 * mm, height=20 * mm)
            header = Table(
                [[
                    header_logo,
                    Paragraph(
                        "<b>MGV Développement</b><br/>"
                        "<font size=7 color='#6b6b6b'>Pôle Prospection</font>",
                        s["small"],
                    ),
                ]],
                colWidths=[24 * mm, "*"],
            )
            header.setStyle(
                TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")])
            )
            story.append(header)
            story.append(Spacer(1, 6))
        except Exception:  # noqa: BLE001
            pass

    story.append(Paragraph(
        "FICHE D'ANALYSE D'OPPORTUNITÉ", s["title"]
    ))
    story.append(Paragraph(
        f"Générée le {_date_fr_ca_long(datetime.utcnow())}",
        s["subtitle"],
    ))
    story.append(Spacer(1, 10))

    # ── Identité de l'immeuble ──────────────────────────────────
    identity_rows: List[tuple] = []
    addr_full_parts = [rec.address, rec.city, rec.postal_code]
    addr_full = ", ".join(p for p in addr_full_parts if p and p.strip())
    identity_rows.append(("Adresse complète", _str(addr_full)))
    identity_rows.append(("Province", _str(rec.province)))
    identity_rows.append(("Type de bâtiment", _str(rec.type_batiment)))
    identity_rows.append(
        ("Année de construction", _int(rec.annee_construction))
    )
    identity_rows.append(("Nombre de logements", _int(rec.nb_logements)))
    identity_rows.append(
        ("Stationnements", _int(rec.nb_stationnements))
    )
    if rec.superficie_batiment:
        identity_rows.append(
            ("Superficie bâtiment", f"{rec.superficie_batiment} pi²")
        )
    if rec.superficie_terrain:
        identity_rows.append(
            ("Superficie terrain", f"{rec.superficie_terrain} pi²")
        )
    identity_rows.append(("Courtier", _str(rec.courtier_nom)))
    identity_rows.append(
        ("Contact courtier", _str(rec.courtier_contact))
    )
    identity_rows.append(("Source — Extracteur", _str(rec.model_used)))
    first_url = None
    if rec.source_urls:
        for line in rec.source_urls.splitlines():
            line = line.strip()
            if line:
                first_url = line
                break
    identity_rows.append(("Source — URL principale", _str(first_url)))

    t = _table_two_col(rl, identity_rows, s=s)
    if t is not None:
        story.append(t)
    story.append(Spacer(1, 4))

    # ── Informations financières — état actuel ─────────────────
    results = _safe_json_load(rec.analysis_results_json)
    story.append(Paragraph(
        "INFORMATIONS FINANCIÈRES — ÉTAT ACTUEL", s["section"]
    ))
    fin_rows: List[tuple] = []
    fin_rows.append(("Prix demandé", _money(rec.asking_price)))
    fin_rows.append(
        ("Évaluation municipale", _money(rec.evaluation_municipale))
    )
    fin_rows.append(
        ("Écart prix / évaluation",
         _ecart_pct(
             float(rec.asking_price) if rec.asking_price else None,
             float(rec.evaluation_municipale)
             if rec.evaluation_municipale else None,
         ))
    )
    fin_rows.append(("Revenus bruts annuels", _money(rec.revenus_bruts)))
    fin_rows.append(
        ("Loyer moyen mensuel (calculé)",
         _loyer_mois_moyen(
             float(rec.revenus_bruts) if rec.revenus_bruts else None,
             rec.nb_logements,
         ))
    )
    for label, val in _depenses_rows(rec, results):
        fin_rows.append((label, val))
    # NOI et cap rate calculés à partir du scénario achat si dispo.
    if results:
        scen_achat = (results.get("scenarios") or {}).get("achat") or {}
        revenus_net = scen_achat.get("revenus_net")
        if revenus_net is not None:
            fin_rows.append(
                ("Revenus nets (NOI — scénario achat)",
                 _money(revenus_net))
            )
        try:
            if (
                revenus_net is not None
                and rec.asking_price
                and float(rec.asking_price) > 0
            ):
                cap = float(revenus_net) / float(rec.asking_price) * 100.0
                fin_rows.append(
                    ("Cap rate (sur prix demandé)",
                     _pct(cap, decimals=2))
                )
        except Exception:  # noqa: BLE001
            pass

    t = _table_two_col(rl, fin_rows, s=s)
    if t is not None:
        story.append(t)

    # ── Typologie des logements ─────────────────────────────────
    story.append(Paragraph(
        "TYPOLOGIE DES LOGEMENTS", s["section"]
    ))
    typology = _safe_json_load(rec.typology_json) or {}
    story.append(_typology_section(rl, typology, s=s))
    story.append(Spacer(1, 6))

    # ── Inputs manuels d'analyse ───────────────────────────────
    story.append(Paragraph(
        "INPUTS MANUELS D'ANALYSE", s["section"]
    ))
    inputs_rows: List[tuple] = [
        ("Taux d'intérêt refi",
         _pct(rec.taux_interet_refi_pct, decimals=3)),
        ("Taux d'intérêt prêteur B (pendant projet)",
         _pct(rec.taux_interet_preteur_b_projet_pct, decimals=3)),
        ("% MDF prêteur B",
         _pct(rec.mdf_preteur_b_pct, decimals=2)),
        ("TGA (taux global d'actualisation)",
         _pct(rec.tga_pct, decimals=3)),
        ("Taux d'intérêt achat",
         _pct(rec.taux_interet_achat_pct, decimals=3)),
        ("Durée du projet",
         f"{rec.duree_projet_annees} ans"
         if rec.duree_projet_annees else "—"),
        ("Réduction énergie",
         _pct(rec.reduction_energie_pct, decimals=1)),
        ("Nb logements ajoutés", _int(rec.nb_logements_ajoutes)),
        ("Nb thermopompes ajoutées",
         _int(rec.nb_thermopompes_ajoutees)),
        ("Ajout WiFi",
         "Oui" if rec.ajout_wifi else
         ("Non" if rec.ajout_wifi is False else "—")),
        ("Frais de développement", _money(rec.frais_developpement)),
        ("Frais de négociations", _money(rec.frais_negociations)),
        ("Travaux estimés", _money(rec.travaux_estimes)),
    ]
    # Inoccupation (depuis résultats si dispo).
    if results and results.get("taux_inoccupation_pct") is not None:
        try:
            inocc = float(results.get("taux_inoccupation_pct")) * 100
            inputs_rows.append(
                ("Taux d'inoccupation", _pct(inocc, decimals=1))
            )
        except Exception:  # noqa: BLE001
            pass
    t = _table_two_col(rl, inputs_rows, s=s)
    if t is not None:
        story.append(t)

    # ── Composition MDF prêteur B ───────────────────────────────
    story.append(Paragraph(
        "COMPOSITION MDF PRÊTEUR B", s["section"]
    ))
    if results:
        fd = results.get("frais_demarrage") or {}
        fd_total = float(results.get("frais_demarrage_total") or 0)
        mdf_pct_amt = float(results.get("mdf_pct_prix_achat") or 0)
        mdf_total = float(results.get("mdf_preteur_b") or 0)

        frais_rows: List[tuple] = [
            ("Évaluateur 1", _money(fd.get("evaluateur"))),
            ("Évaluateur 2", _money(fd.get("evaluateur_2"))),
            ("Inspection", _money(fd.get("inspection"))),
            ("Avocat", _money(fd.get("avocat"))),
            ("Notaire 1", _money(fd.get("notaire"))),
            ("Notaire 2", _money(fd.get("notaire_2"))),
            ("Rapport efficacité énergétique",
             _money(fd.get("rapport_efficacite"))),
            ("Courtier hypothécaire 1",
             _money(fd.get("courtier_hypothecaire_1"))),
            ("Courtier hypothécaire 2",
             _money(fd.get("courtier_hypothecaire_2"))),
            ("Taxes de bienvenue (calculées)",
             _money(fd.get("taxes_bienvenue"))),
            ("Frais de développement",
             _money(fd.get("frais_developpement"))),
            ("Frais de négociations",
             _money(fd.get("frais_negociations"))),
            ("Frais de travaux", _money(fd.get("frais_travaux"))),
            ("Intérêts pendant projet (portage)",
             _money(fd.get("interets"))),
            ("Revenus nets pendant projet",
             _money(fd.get("revenus_nets_pendant_projet"))),
            ("Total frais de démarrage", f"<b>{_money(fd_total)}</b>"),
            ("MDF (% × prix d'achat)", _money(mdf_pct_amt)),
            ("MDF prêteur B totale",
             f"<b>{_money(mdf_total)}</b>"),
        ]
        # Convertit la dernière ligne pour permettre le HTML bold.
        wrapped = [
            (Paragraph(k, s["small"]), Paragraph(str(v), s["small"]))
            for k, v in frais_rows
        ]
        # On rebâtit le tableau directement pour permettre le rendu HTML.
        t = Table(wrapped, colWidths=[70 * mm, "*"])
        t.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25,
                 colors.HexColor("#e2e2e2")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("BACKGROUND", (0, -3), (-1, -3),
                 colors.HexColor("#eff6ff")),
                ("BACKGROUND", (0, -1), (-1, -1),
                 colors.HexColor("#eff6ff")),
            ])
        )
        story.append(t)
    else:
        story.append(Paragraph(
            "L'analyse financière n'a pas encore été lancée — "
            "les frais de démarrage seront calculés au prochain "
            "« Lancer l'analyse ».",
            s["small_muted"],
        ))

    # ── Scénarios de financement ────────────────────────────────
    story.append(Paragraph(
        "SCÉNARIOS DE FINANCEMENT", s["section"]
    ))
    if results:
        scenarios = results.get("scenarios") or {}
        fd_total = float(results.get("frais_demarrage_total") or 0)
        for key in ("achat", "refi_schl", "refi_aph_50", "refi_aph_100"):
            scen = scenarios.get(key)
            if scen is None:
                continue
            story.append(_scenario_card(
                rl, scen, s=s, frais_demarrage_total=fd_total
            ))
    else:
        story.append(Paragraph(
            "Aucun scénario calculé — lance l'analyse financière "
            "depuis la fiche pour générer les 4 scénarios.",
            s["small_muted"],
        ))

    # ── Meilleur scénario refi ──────────────────────────────────
    story.append(Paragraph(
        "MEILLEUR SCÉNARIO REFI", s["section"]
    ))
    if results:
        best = results.get("best_refi") or {}
        program = best.get("program") or rec.best_refi_program
        amount = best.get("amount") or rec.best_refi_amount
        rci, pvi = _compute_rci_pvi(rec, results)
        best_rows: List[tuple] = [
            ("Programme retenu", _str(program)),
            ("Équité dégagée", _money(amount)),
            ("RCI (% capital récupéré)",
             _pct(rci, decimals=1) if rci is not None else "—"),
            ("PVI (prise de valeur de l'immeuble)",
             _money(pvi) if pvi is not None else "—"),
        ]
        # Justification : RCD du programme retenu.
        scenarios = results.get("scenarios") or {}
        for k in ("refi_aph_100", "refi_aph_50", "refi_schl"):
            sc = scenarios.get(k)
            if sc and sc.get("label") == program:
                best_rows.append(
                    ("Justification — RCD",
                     f"{float(sc.get('rcd') or 0):.2f}")
                )
                best_rows.append(
                    ("Justification — LTV",
                     f"{float(sc.get('ltv') or 0) * 100:.0f} %")
                )
                break
        t = _table_two_col(rl, best_rows, s=s)
        if t is not None:
            story.append(t)
    else:
        story.append(Paragraph(
            "Pas encore de meilleur scénario — lance l'analyse.",
            s["small_muted"],
        ))

    # ── Validation ──────────────────────────────────────────────
    story.append(Paragraph("VALIDATION", s["section"]))
    warnings = rec.validation_warnings or []
    if not warnings:
        story.append(Paragraph(
            "Aucune anomalie détectée par le validateur post-extraction.",
            s["info_ok"],
        ))
    else:
        rows = [[
            Paragraph("<b>Sévérité</b>", s["small"]),
            Paragraph("<b>Champ</b>", s["small"]),
            Paragraph("<b>Message</b>", s["small"]),
        ]]
        for w in warnings:
            sev = _format_warning_severity(w.get("severity"))
            rows.append([
                Paragraph(sev, s["small"]),
                Paragraph(_str(w.get("field")), s["small"]),
                Paragraph(_str(w.get("message")), s["small"]),
            ])
        t = Table(rows, colWidths=[28 * mm, 38 * mm, "*"])
        t.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0),
                 colors.HexColor("#fef3c7")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25,
                 colors.HexColor("#e2e2e2")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ])
        )
        story.append(t)

    # ── Sources & attachments ──────────────────────────────────
    story.append(Paragraph(
        "SOURCES &amp; ATTACHMENTS", s["section"]
    ))
    if rec.source_urls and rec.source_urls.strip():
        story.append(Paragraph("<b>URLs sources</b>", s["subsection"]))
        for line in rec.source_urls.splitlines():
            line = line.strip()
            if not line:
                continue
            story.append(Paragraph(line, s["small"]))
    else:
        story.append(Paragraph(
            "Aucune URL source.", s["small_muted"]
        ))

    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "<b>Fichiers joints</b>", s["subsection"]
    ))
    if attachments:
        att_rows = [[
            Paragraph("<b>Nom</b>", s["small"]),
            Paragraph("<b>Type MIME</b>", s["small"]),
            Paragraph("<b>Taille</b>", s["small"]),
        ]]
        for att in attachments:
            size_kb = (att.size_bytes or 0) / 1024.0
            size_str = (
                f"{size_kb:.1f} KB" if size_kb < 1024
                else f"{size_kb / 1024:.2f} MB"
            )
            att_rows.append([
                Paragraph(_str(att.filename), s["small"]),
                Paragraph(_str(att.content_type), s["small"]),
                Paragraph(size_str, s["small"]),
            ])
        t = Table(att_rows, colWidths=["55%", "30%", "15%"])
        t.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0),
                 colors.HexColor("#eff6ff")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25,
                 colors.HexColor("#e2e2e2")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ])
        )
        story.append(t)
    else:
        story.append(Paragraph(
            "Aucun fichier joint.", s["small_muted"]
        ))

    # ── Build avec pied de page sur chaque page ────────────────
    def _on_page(canvas, doc):
        _draw_footer(canvas, doc, address_label=address_label)

    try:
        doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    except Exception as exc:
        log.exception(
            "Rendu PDF fiche analyse %s échoué : %s", rec.id, exc
        )
        raise ValueError(
            f"Rendu du PDF de la fiche d'analyse échoué : "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return buf.getvalue()


def _slugify_address(addr: Optional[str], fallback_id: int) -> str:
    """Convertit l'adresse en slug ASCII pour le nom de fichier.
    Ex. « 1234 rue Sainte-Catherine, Montréal » → « 1234_rue_Sainte_Catherine_Montreal ».
    """
    if not addr or not addr.strip():
        return str(fallback_id)
    decomposed = unicodedata.normalize("NFKD", addr.strip())
    ascii_only = "".join(
        ch for ch in decomposed if not unicodedata.combining(ch)
    )
    underscored = re.sub(r"[\s\-,'’]+", "_", ascii_only)
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", underscored)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or str(fallback_id)


def lead_analysis_pdf_filename(rec: LeadAnalysis) -> str:
    """Nom de fichier canonique : `Fiche_Analyse_{slug}_{id}.pdf`."""
    slug = _slugify_address(rec.address, rec.id)
    return f"Fiche_Analyse_{slug}_{rec.id}.pdf"


async def generate_lead_analysis_pdf(
    db: AsyncSession, analysis_id: int
) -> bytes:
    """Génère à la volée le PDF complet de l'analyse — pas de stockage
    en BDD (l'export reflète toujours l'état courant)."""
    rec, atts = await _load(db, analysis_id)
    if rec is None:
        raise ValueError(f"LeadAnalysis {analysis_id} introuvable")
    return _render_bytes(rec, atts)
