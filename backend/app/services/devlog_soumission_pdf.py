"""Génère le PDF d'une soumission devis_dev — VUE CLIENT uniquement.

Deux sections affichées au client :

1. **Frais Mensuels Récurrents** — encadré avec le montant mensuel
   final et la liste des libellés (PAS de coûts internes, PAS de prix
   par item, PAS de marge).
2. **Investissement initial** (titre marketing — on n'utilise plus
   « Frais de mise en oeuvre ») — liste des features avec leur
   ``prix_client`` (déjà calculé par ``compute_devis``), liste des
   frais fixes idem, puis le total final.

⚠️ Aucun élément interne (heures, taux horaires, marges, commission
closer, coûts unitaires) ne doit fuiter ici — c'est ce qui est envoyé
au prospect.

Pattern inspiré de ``app.services.offer_pdf`` (PR #445).
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.devlog_client import DevlogClient
from app.models.devlog_soumission import DevlogSoumission
from app.models.devlog_soumission_item import DevlogSoumissionItem
from app.services.devlog_devis_calc import compute_devis


log = logging.getLogger(__name__)


_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "logo.png",
)


BUYER_ENTITY_NAME = "Horizon Services Immobiliers"
BUYER_ENTITY_TAGLINE = "Pôle Développement logiciel"
LEGAL_NOTICE = (
    "Signature électronique conforme à la Loi sur la protection des "
    "renseignements personnels et les documents électroniques (PIPEDA) "
    "et à la Loi concernant le cadre juridique des technologies de "
    "l'information (Québec)."
)


def _fmt_money(n: Any) -> str:
    """Format canadien français : « 1 234,56 $ »."""
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    # Format avec séparateur de milliers (espace insécable) et virgule
    # décimale, à la française canadienne.
    s = f"{v:,.2f}"  # "1,234.56"
    s = s.replace(",", " ").replace(".", ",")
    return f"{s} $"


def _lazy_reportlab() -> dict[str, Any]:
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
        "Paragraph": Paragraph,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
    }


def _styles(rl: dict[str, Any]):
    PS = rl["ParagraphStyle"]
    base = rl["getSampleStyleSheet"]()
    colors = rl["colors"]
    dark = colors.HexColor("#111111")
    muted = colors.HexColor("#6b6b6b")
    accent = colors.HexColor("#1e40af")  # bleu Horizon dev
    return {
        "title": PS(
            "title",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=dark,
        ),
        "subtitle": PS(
            "subtitle",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=10,
            leading=13,
            textColor=muted,
        ),
        "section": PS(
            "section",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.white,
            backColor=accent,
            leftIndent=4,
            rightIndent=4,
            spaceBefore=8,
            spaceAfter=4,
            borderPadding=4,
        ),
        "body": PS(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=dark,
        ),
        "body_bold": PS(
            "body_bold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=dark,
        ),
        "small": PS(
            "small",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=muted,
        ),
        "legal": PS(
            "legal",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=11,
            textColor=muted,
        ),
        "big_amount": PS(
            "big_amount",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=accent,
        ),
    }


async def _load(
    db: AsyncSession, soumission_id: int
) -> tuple[Optional[DevlogSoumission], list[DevlogSoumissionItem], Optional[DevlogClient]]:
    soumission = (
        await db.execute(
            select(DevlogSoumission).where(DevlogSoumission.id == soumission_id)
        )
    ).scalar_one_or_none()
    if soumission is None:
        return None, [], None
    items = list(
        (
            await db.execute(
                select(DevlogSoumissionItem)
                .where(DevlogSoumissionItem.soumission_id == soumission_id)
                .order_by(
                    DevlogSoumissionItem.position.asc(),
                    DevlogSoumissionItem.id.asc(),
                )
            )
        ).scalars().all()
    )
    client: Optional[DevlogClient] = None
    if soumission.client_id is not None:
        client = (
            await db.execute(
                select(DevlogClient).where(DevlogClient.id == soumission.client_id)
            )
        ).scalar_one_or_none()
    return soumission, items, client


def _render_bytes(
    soumission: DevlogSoumission,
    items: list[DevlogSoumissionItem],
    client: Optional[DevlogClient],
) -> bytes:
    rl = _lazy_reportlab()
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Image = rl["Image"]
    mm = rl["mm"]
    colors = rl["colors"]

    devis = compute_devis(soumission, items)
    recurring = devis.get("recurring", {})
    initial = devis.get("initial", {})

    buf = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=rl["A4"],
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Soumission devlog {soumission.id}",
        author=BUYER_ENTITY_NAME,
    )
    s = _styles(rl)
    story: list = []

    # --- Header ---
    left_block: list = []
    if os.path.exists(_LOGO_PATH):
        try:
            left_block.append(Image(_LOGO_PATH, width=22 * mm, height=22 * mm))
        except Exception:
            pass
    left_block.extend([
        Paragraph(f"<b>{BUYER_ENTITY_NAME}</b>", s["body"]),
        Paragraph(BUYER_ENTITY_TAGLINE, s["small"]),
    ])
    right_block = [
        Paragraph("<b>SOUMISSION</b>", s["title"]),
        Paragraph("Développement logiciel", s["subtitle"]),
        Paragraph(
            f"N° {soumission.id} &middot; "
            f"Émise le {datetime.utcnow().strftime('%Y-%m-%d')}",
            s["small"],
        ),
    ]
    header = Table([[left_block, right_block]], colWidths=["55%", "45%"])
    header.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ])
    )
    story.append(header)
    story.append(Spacer(1, 10))

    # --- 1. Client ---
    story.append(Paragraph("CLIENT", s["section"]))
    if client is not None:
        client_lines = [client.name]
        if client.company:
            client_lines.append(client.company)
        if client.address:
            client_lines.append(client.address)
        story.append(Paragraph(" &middot; ".join(client_lines), s["body"]))
    else:
        story.append(Paragraph("À confirmer", s["body"]))
    if soumission.title:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Projet :</b> {soumission.title}", s["body"]))
    if soumission.summary:
        story.append(Spacer(1, 4))
        story.append(Paragraph(soumission.summary, s["body"]))

    # --- 2. Section Frais Mensuels Récurrents (si présents) ---
    recurring_items_breakdown = recurring.get("items_breakdown") or []
    total_monthly_client = float(recurring.get("total_client_amount") or 0)
    tps_rec = float(recurring.get("tps_amount") or 0)
    tvq_rec = float(recurring.get("tvq_amount") or 0)
    total_monthly_taxe = float(recurring.get("total_client_amount_taxe") or 0)
    if recurring_items_breakdown or total_monthly_client > 0:
        story.append(Paragraph("FRAIS MENSUELS RÉCURRENTS", s["section"]))
        # Encadré « X $ / mois » (TTC — taxes incluses)
        encadre = Table(
            [[
                Paragraph(
                    f"<b>{_fmt_money(total_monthly_taxe)} / mois</b>",
                    s["big_amount"],
                )
            ]],
            colWidths=["100%"],
        )
        encadre.setStyle(
            TableStyle([
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#1e40af")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eff6ff")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ])
        )
        story.append(encadre)
        story.append(Spacer(1, 4))

        # Détail des taxes (TPS / TVQ) sous l'encadré récurrent
        if total_monthly_client > 0:
            tax_rows = [
                [
                    Paragraph("Sous-total mensuel", s["body"]),
                    Paragraph(_fmt_money(total_monthly_client), s["body"]),
                ],
                [
                    Paragraph("TPS (5%)", s["body"]),
                    Paragraph(_fmt_money(tps_rec), s["body"]),
                ],
                [
                    Paragraph("TVQ (9,975%)", s["body"]),
                    Paragraph(_fmt_money(tvq_rec), s["body"]),
                ],
                [
                    Paragraph("<b>Total mensuel TTC</b>", s["body_bold"]),
                    Paragraph(
                        f"<b>{_fmt_money(total_monthly_taxe)}</b>",
                        s["body_bold"],
                    ),
                ],
            ]
            tax_table = Table(tax_rows, colWidths=["72%", "28%"])
            tax_table.setStyle(
                TableStyle([
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.HexColor("#1e40af")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ])
            )
            story.append(tax_table)
            story.append(Spacer(1, 4))

        client_recurring_desc = (
            soumission.client_recurring_description or ""
        ).strip()
        if client_recurring_desc:
            story.append(Paragraph(client_recurring_desc, s["body"]))
        elif recurring_items_breakdown:
            story.append(Paragraph("Inclut :", s["body"]))
            for it in recurring_items_breakdown:
                desc = (it.get("description") or "").strip() or "—"
                story.append(Paragraph(f"&bull; {desc}", s["body"]))

    # --- 3. Section Investissement initial ---
    features_client = initial.get("features_client") or []
    frais_fixes_client = initial.get("frais_fixes_client") or []
    total_initial = float(initial.get("total_final") or 0)
    tps_init = float(initial.get("tps_amount") or 0)
    tvq_init = float(initial.get("tvq_amount") or 0)
    total_initial_taxe = float(initial.get("total_final_taxe") or 0)

    if features_client or frais_fixes_client or total_initial > 0:
        story.append(Paragraph("INVESTISSEMENT INITIAL", s["section"]))

        rows: list[list[Any]] = []
        rows.append([
            Paragraph("<b>Description</b>", s["body_bold"]),
            Paragraph("<b>Montant</b>", s["body_bold"]),
        ])
        for feat in features_client:
            desc = (feat.get("description") or "").strip() or "—"
            prix = float(feat.get("prix_client") or 0)
            rows.append([
                Paragraph(desc, s["body"]),
                Paragraph(_fmt_money(prix), s["body"]),
            ])
        if frais_fixes_client:
            # Petit séparateur visuel : titre « Frais fixes » avant
            # les frais fixes du client.
            rows.append([
                Paragraph("<b>Frais fixes</b>", s["body_bold"]),
                Paragraph("", s["body"]),
            ])
            for ff in frais_fixes_client:
                desc = (ff.get("description") or "").strip() or "—"
                prix = float(ff.get("prix_client") or 0)
                rows.append([
                    Paragraph(desc, s["body"]),
                    Paragraph(_fmt_money(prix), s["body"]),
                ])
        rows.append([
            Paragraph("<b>Sous-total</b>", s["body_bold"]),
            Paragraph(
                f"<b>{_fmt_money(total_initial)}</b>", s["body_bold"]
            ),
        ])
        rows.append([
            Paragraph("TPS (5%)", s["body"]),
            Paragraph(_fmt_money(tps_init), s["body"]),
        ])
        rows.append([
            Paragraph("TVQ (9,975%)", s["body"]),
            Paragraph(_fmt_money(tvq_init), s["body"]),
        ])
        rows.append([
            Paragraph("<b>Total TTC</b>", s["body_bold"]),
            Paragraph(
                f"<b>{_fmt_money(total_initial_taxe)}</b>", s["body_bold"]
            ),
        ])

        table = Table(rows, colWidths=["72%", "28%"])
        # Indice des lignes spéciales : sous-total (4 lignes avant la
        # fin), Total TTC (dernière ligne).
        subtotal_row = len(rows) - 4
        ttc_row = len(rows) - 1
        table.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("LINEABOVE", (0, subtotal_row), (-1, subtotal_row), 0.5, colors.HexColor("#1e40af")),
                ("LINEABOVE", (0, ttc_row), (-1, ttc_row), 1, colors.HexColor("#1e40af")),
                ("BACKGROUND", (0, ttc_row), (-1, ttc_row), colors.HexColor("#eff6ff")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, subtotal_row - 1), [colors.white, colors.HexColor("#fafafa")]),
            ])
        )
        story.append(table)

    # --- Conditions ---
    story.append(Spacer(1, 10))
    story.append(Paragraph("CONDITIONS", s["section"]))
    conditions_txt = (
        "Cette soumission est valide pour 30 jours suivant la date "
        "d'émission. L'acceptation par signature électronique vaut "
        "engagement contractuel ; un contrat détaillé suivra pour "
        "préciser les modalités d'exécution, les jalons et les "
        "garanties applicables."
    )
    story.append(Paragraph(conditions_txt, s["body"]))

    # --- Signatures ---
    story.append(Spacer(1, 10))
    story.append(Paragraph("SIGNATURES", s["section"]))
    signed_at_txt = (
        soumission.signed_at.strftime("%Y-%m-%d")
        if getattr(soumission, "signed_at", None)
        else None
    )
    signed_name_txt = getattr(soumission, "signed_name", None)
    client_sig_text = (
        f"Signé par {signed_name_txt} le {signed_at_txt}"
        if signed_at_txt and signed_name_txt
        else "(en attente de signature)"
    )
    sig_table = Table(
        [
            [
                Paragraph("<b>Client</b>", s["body"]),
                Paragraph(f"<b>{BUYER_ENTITY_NAME}</b>", s["body"]),
            ],
            [
                Paragraph(client_sig_text, s["small"]),
                Paragraph(
                    f"{BUYER_ENTITY_NAME}<br/>"
                    f"Émis le {datetime.utcnow().strftime('%Y-%m-%d')}",
                    s["small"],
                ),
            ],
        ],
        colWidths=["50%", "50%"],
    )
    sig_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEABOVE", (0, 1), (-1, 1), 0.5, colors.HexColor("#999999")),
            ("TOPPADDING", (0, 1), (-1, 1), 18),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(sig_table)

    # --- Mentions légales ---
    story.append(Spacer(1, 12))
    story.append(Paragraph(LEGAL_NOTICE, s["legal"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Document généré par le portail Horizon le "
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}.",
        s["legal"],
    ))

    doc.build(story)
    return buf.getvalue()


async def generate_devis_pdf(
    db: AsyncSession, soumission_id: int
) -> bytes:
    """Rend le PDF de la soumission devis_dev (vue client uniquement)."""
    soumission, items, client = await _load(db, soumission_id)
    if soumission is None:
        raise ValueError(f"Soumission {soumission_id} introuvable.")
    if not getattr(soumission, "is_devis_dev", False):
        raise ValueError(
            "Seules les soumissions au nouveau format devis_dev "
            "peuvent générer un PDF."
        )
    return _render_bytes(soumission, items, client)


def _render_signed_bytes(
    soumission: DevlogSoumission,
    items: list[DevlogSoumissionItem],
    client: Optional[DevlogClient],
) -> bytes:
    """Variante de ``_render_bytes`` avec un cartouche très visible
    « SIGNÉ ÉLECTRONIQUEMENT » en haut de la première page + IP +
    horodatage précis. Le reste du document est identique au PDF
    normal (qui mentionne déjà nom + date dans la section Signatures).

    Implémentation : on inline une copie du builder pour pouvoir
    glisser le cartouche en tout début de story sans casser
    ``_render_bytes`` (utilisé par le PDF non-signé / preview public).
    """
    rl = _lazy_reportlab()
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    mm = rl["mm"]
    colors = rl["colors"]
    SimpleDocTemplate = rl["SimpleDocTemplate"]

    base_pdf = _render_bytes(soumission, items, client)
    # Si reportlab n'est pas dispo, on retombe sur le PDF de base.
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore
        from reportlab.pdfgen import canvas  # type: ignore
    except Exception:
        log.warning(
            "pypdf indisponible — PDF signé sans bandeau overlay."
        )
        return base_pdf

    # Construit un overlay 1-page : bandeau en haut.
    signed_at = getattr(soumission, "signed_at", None)
    signed_name = getattr(soumission, "signed_name", None) or "—"
    signed_ip = getattr(soumission, "signed_ip", None) or "—"
    signed_at_txt = (
        signed_at.strftime("%Y-%m-%d à %H:%M UTC")
        if signed_at is not None
        else "—"
    )

    overlay_buf = io.BytesIO()
    page_w_pt, page_h_pt = rl["A4"]
    c = canvas.Canvas(overlay_buf, pagesize=rl["A4"])
    # Bandeau vert tout en haut de la page.
    band_h = 16 * mm
    band_y = page_h_pt - band_h
    c.setFillColor(colors.HexColor("#059669"))  # emerald-600
    c.rect(0, band_y, page_w_pt, band_h, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(
        15 * mm,
        band_y + band_h - 6 * mm,
        "✓ SOUMISSION SIGNÉE ÉLECTRONIQUEMENT",
    )
    c.setFont("Helvetica", 8)
    c.drawString(
        15 * mm,
        band_y + 4 * mm,
        f"Le {signed_at_txt} — Par : {signed_name} — IP : {signed_ip}",
    )
    c.save()
    overlay_buf.seek(0)

    reader_base = PdfReader(io.BytesIO(base_pdf))
    reader_overlay = PdfReader(overlay_buf)
    writer = PdfWriter()
    overlay_page = reader_overlay.pages[0]
    for idx, page in enumerate(reader_base.pages):
        if idx == 0:
            try:
                page.merge_page(overlay_page)
            except Exception:
                log.exception(
                    "Overlay PDF signé fusion impossible (page 0)"
                )
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


async def generate_signed_pdf(
    db: AsyncSession, soumission_id: int
) -> bytes:
    """Rend le PDF *signé* de la soumission — appelé au moment de la
    signature publique. Le PDF contient le bandeau « ✓ SIGNÉ ÉLECTRO-
    NIQUEMENT » + IP + horodatage en plus du document normal (qui
    inclut déjà la section Signatures avec nom + date).

    À stocker dans ``DevlogSoumission.signed_pdf_blob`` pour pouvoir
    le servir tel quel via ``GET /devlog/soumissions/{id}/signed-pdf``
    (audit immuable — pas de recalcul à chaque téléchargement)."""
    soumission, items, client = await _load(db, soumission_id)
    if soumission is None:
        raise ValueError(f"Soumission {soumission_id} introuvable.")
    if not getattr(soumission, "is_devis_dev", False):
        raise ValueError(
            "Seules les soumissions devis_dev ont un PDF signé."
        )
    return _render_signed_bytes(soumission, items, client)
