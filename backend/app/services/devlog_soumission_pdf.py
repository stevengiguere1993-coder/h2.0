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
from app.models.devlog_soumission_module import DevlogSoumissionModule
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


# --- Palette (alignée sur la page web publique de signature) ----------
# slate / blue / emerald de Tailwind, repris à l'identique pour que le
# PDF et la page web racontent la même histoire visuelle.
_DARK = "#0f172a"        # slate-900
_MUTED = "#475569"       # slate-600
_FAINT = "#64748b"       # slate-500
_LINE = "#e2e8f0"        # slate-200 (séparateurs)
_BLUE = "#1d4ed8"        # blue-700 (accent initial)
_BLUE_DARK = "#1e3a8a"   # blue-900 (total TTC)
_BLUE_BORDER = "#bfdbfe"  # blue-200
_BLUE_SOFT = "#eff6ff"   # blue-50 (cartouche / total)
_CARD_BG = "#f8fafc"     # slate-50 (fond de carte module)
_CARD_BORDER = "#e2e8f0"  # slate-200 (bordure carte)
_EMERALD = "#047857"     # emerald-700
_EMERALD_DARK = "#064e3b"  # emerald-900
_EMERALD_BADGE = "#059669"  # emerald-600 (badge « Offert »)
_EMERALD_BORDER = "#a7f3d0"  # emerald-200
_EMERALD_SOFT = "#ecfdf5"  # emerald-50


def _styles(rl: dict[str, Any]):
    PS = rl["ParagraphStyle"]
    base = rl["getSampleStyleSheet"]()
    colors = rl["colors"]
    dark = colors.HexColor(_DARK)
    muted = colors.HexColor(_MUTED)
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
        # Titre de section léger : petites capitales colorées, pas de
        # bandeau plein. Couleur surchargée par section (bleu/émeraude).
        "section": PS(
            "section",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor(_BLUE),
            spaceBefore=2,
            spaceAfter=2,
        ),
        "section_emerald": PS(
            "section_emerald",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor(_EMERALD),
            spaceBefore=2,
            spaceAfter=2,
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
        # Gros montant centré des cartouches (couleur surchargée).
        "big_amount": PS(
            "big_amount",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=26,
            leading=30,
            alignment=1,  # centré
            textColor=colors.HexColor(_BLUE),
        ),
        "big_amount_emerald": PS(
            "big_amount_emerald",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=26,
            leading=30,
            alignment=1,
            textColor=colors.HexColor(_EMERALD),
        ),
        # Légende du cartouche (au-dessus / en-dessous du gros montant).
        "amount_cap_blue": PS(
            "amount_cap_blue",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            alignment=1,
            textColor=colors.HexColor(_BLUE),
        ),
        "amount_cap_emerald": PS(
            "amount_cap_emerald",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            alignment=1,
            textColor=colors.HexColor(_EMERALD),
        ),
        # En-tête de carte module : nom (gras, foncé) à gauche.
        "module_name": PS(
            "module_name",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            textColor=dark,
        ),
        # Prix du module (gras, bleu) à droite.
        "module_price": PS(
            "module_price",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            alignment=2,  # aligné à droite
            textColor=colors.HexColor(_BLUE),
        ),
        # Fonctionnalités en sous-puces discrètes.
        "feature": PS(
            "feature",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12.5,
            leftIndent=8,
            textColor=muted,
        ),
        # Variante émeraude des sous-puces (modules offerts).
        "feature_green": PS(
            "feature_green",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12.5,
            leftIndent=8,
            textColor=colors.HexColor(_EMERALD_DARK),
        ),
        # Nom d'un module offert (gras, émeraude foncé).
        "free_name": PS(
            "free_name",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor(_EMERALD_DARK),
        ),
        # Prix d'un module offert (« 0,00 $ », émeraude, à droite).
        "free_price": PS(
            "free_price",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            alignment=2,
            textColor=colors.HexColor(_EMERALD),
        ),
        # Condition de gratuité, italique émeraude.
        "free_cond": PS(
            "free_cond",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor(_EMERALD),
        ),
        # Lignes du récap de taxes.
        "tax_label": PS(
            "tax_label",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=muted,
        ),
        "tax_amount": PS(
            "tax_amount",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            alignment=2,
            textColor=dark,
        ),
    }


async def _load(
    db: AsyncSession, soumission_id: int
) -> tuple[
    Optional[DevlogSoumission],
    list[DevlogSoumissionItem],
    Optional[DevlogClient],
    list[DevlogSoumissionModule],
]:
    soumission = (
        await db.execute(
            select(DevlogSoumission).where(DevlogSoumission.id == soumission_id)
        )
    ).scalar_one_or_none()
    if soumission is None:
        return None, [], None, []
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
    # Modules (Phase 2) — passés à ``compute_devis`` pour appliquer
    # sélection + gratuité. Liste vide => chemin legacy inchangé.
    modules = list(
        (
            await db.execute(
                select(DevlogSoumissionModule).where(
                    DevlogSoumissionModule.soumission_id == soumission_id
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
    return soumission, items, client, modules


def _tax_recap_table(
    rl: dict[str, Any],
    s: dict[str, Any],
    subtotal: float,
    tps: float,
    tvq: float,
    total_ttc: float,
    *,
    subtotal_label: str = "Sous-total",
    ttc_label: str = "Total TTC",
    accent: str = _BLUE,
    total_bg: str = _BLUE_SOFT,
    total_fg: str = _BLUE_DARK,
    border: str = _BLUE_BORDER,
) -> Any:
    """Récap de taxes net, façon page web : table encadrée fine, lignes
    sous-total / TPS / TVQ discrètes, puis ligne Total TTC mise en valeur
    (fond pâle coloré, gras). Alignement des montants à droite.

    Couleurs surchargeables pour la variante émeraude (frais mensuels)."""
    Paragraph = rl["Paragraph"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    colors = rl["colors"]

    def _amt(style_color, text):
        ps = rl["ParagraphStyle"](
            "amt_tmp",
            parent=s["tax_amount"],
            textColor=colors.HexColor(style_color),
        )
        return Paragraph(text, ps)

    rows = [
        [
            Paragraph(subtotal_label, s["tax_label"]),
            Paragraph(_fmt_money(subtotal), s["tax_amount"]),
        ],
        [
            Paragraph("TPS (5%)", s["tax_label"]),
            Paragraph(_fmt_money(tps), s["tax_amount"]),
        ],
        [
            Paragraph("TVQ (9,975%)", s["tax_label"]),
            Paragraph(_fmt_money(tvq), s["tax_amount"]),
        ],
        [
            Paragraph(
                f"<b>{ttc_label}</b>",
                rl["ParagraphStyle"](
                    "ttc_lbl",
                    parent=s["tax_label"],
                    fontName="Helvetica-Bold",
                    fontSize=10.5,
                    textColor=colors.HexColor(total_fg),
                ),
            ),
            _amt(total_fg, f"<b>{_fmt_money(total_ttc)}</b>"),
        ],
    ]
    t = Table(rows, colWidths=["68%", "32%"])
    last = len(rows) - 1
    t.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor(border)),
            ("LINEBELOW", (0, 0), (-1, last - 1), 0.4, colors.HexColor(_LINE)),
            ("BACKGROUND", (0, last), (-1, last), colors.HexColor(total_bg)),
            ("LINEABOVE", (0, last), (-1, last), 0.75, colors.HexColor(accent)),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    return t


def _amount_box(
    rl: dict[str, Any],
    s: dict[str, Any],
    amount: float,
    caption_top: str,
    caption_bottom: str,
    *,
    emerald: bool = False,
) -> Any:
    """Grand cartouche « prix vedette » centré, calqué sur la page web :
    petite légende en capitales au-dessus, gros montant au centre, puis
    une légende discrète en dessous. Bordure colorée (2px) + fond pâle.

    ``emerald=True`` => habillage vert (frais mensuels) ; sinon bleu
    (investissement initial)."""
    Paragraph = rl["Paragraph"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    colors = rl["colors"]

    if emerald:
        cap_style = s["amount_cap_emerald"]
        amt_style = s["big_amount_emerald"]
        border = _EMERALD_BORDER
        bg = _EMERALD_SOFT
    else:
        cap_style = s["amount_cap_blue"]
        amt_style = s["big_amount"]
        border = _BLUE_BORDER
        bg = _BLUE_SOFT

    cell: list = []
    if caption_top:
        cell.append(Paragraph(caption_top.upper(), cap_style))
    cell.append(Paragraph(_fmt_money(amount), amt_style))
    if caption_bottom:
        cell.append(Paragraph(caption_bottom, cap_style))
    box = Table([[cell]], colWidths=["100%"])
    box.setStyle(
        TableStyle([
            ("BOX", (0, 0), (-1, -1), 1.5, colors.HexColor(border)),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    return box


def _render_flat_initial(
    rl: dict[str, Any],
    s: dict[str, Any],
    story: list,
    features_client: list[dict[str, Any]],
    frais_fixes_client: list[dict[str, Any]],
    total_initial: float,
    tps_init: float,
    tvq_init: float,
    total_initial_taxe: float,
) -> None:
    """Rendu LEGACY (sans modules) — liste plate de fonctionnalités.

    Chemin emprunté par toute soumission qui n'a PAS de modules
    (rétrocompat). On garde la liste plate description / montant, mais on
    l'habille du même langage visuel que le reste (table encadrée fine,
    en-tête slate, montants à droite) puis on ferme par le récap de taxes
    net partagé avec le rendu par module."""
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    colors = rl["colors"]

    rows: list[list[Any]] = []
    rows.append([
        Paragraph("<b>Description</b>", s["body_bold"]),
        Paragraph("<b>Montant</b>", s["module_price"]),
    ])
    body_start = len(rows)
    for feat in features_client:
        desc = (feat.get("description") or "").strip() or "—"
        prix = float(feat.get("prix_client") or 0)
        rows.append([
            Paragraph(desc, s["body"]),
            Paragraph(_fmt_money(prix), s["tax_amount"]),
        ])
    ff_header_idx = None
    if frais_fixes_client:
        # Petit séparateur visuel : titre « Frais fixes » avant
        # les frais fixes du client.
        ff_header_idx = len(rows)
        rows.append([
            Paragraph("<b>Frais fixes</b>", s["body_bold"]),
            Paragraph("", s["body"]),
        ])
        for ff in frais_fixes_client:
            desc = (ff.get("description") or "").strip() or "—"
            prix = float(ff.get("prix_client") or 0)
            rows.append([
                Paragraph(desc, s["body"]),
                Paragraph(_fmt_money(prix), s["tax_amount"]),
            ])
    body_end = len(rows) - 1

    table = Table(rows, colWidths=["68%", "32%"])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor(_CARD_BORDER)),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor(_LINE)),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if body_end >= body_start:
        style.append(
            ("ROWBACKGROUNDS", (0, body_start), (-1, body_end),
             [colors.white, colors.HexColor("#fafafa")])
        )
    if ff_header_idx is not None:
        style.append(
            ("BACKGROUND", (0, ff_header_idx), (-1, ff_header_idx),
             colors.HexColor("#f1f5f9"))
        )
        style.append(
            ("LINEABOVE", (0, ff_header_idx), (-1, ff_header_idx),
             0.4, colors.HexColor(_LINE))
        )
    table.setStyle(TableStyle(style))
    story.append(table)
    story.append(Spacer(1, 8))

    # Récap de taxes net (même style que le rendu par module).
    story.append(
        _tax_recap_table(
            rl, s, total_initial, tps_init, tvq_init, total_initial_taxe
        )
    )


def _render_modules_initial(
    rl: dict[str, Any],
    s: dict[str, Any],
    story: list,
    features_client: list[dict[str, Any]],
    frais_fixes_client: list[dict[str, Any]],
    modules_detail: list[dict[str, Any]],
    total_initial: float,
    tps_init: float,
    tvq_init: float,
    total_initial_taxe: float,
) -> None:
    """Rendu « PAR MODULE » (refonte 2026-06, Phase 5) — VUE CLIENT.

    Regroupe l'investissement initial par module RETENU :

    * Un sous-bloc par module sélectionné et payant : nom du module,
      ses fonctionnalités (description + prix client), prix du module.
    * Une section « Inclus gratuitement » regroupant les modules offerts
      (gratuité « module → module » déclenchée) : mention « Offert »,
      prix 0.
    * Les fonctionnalités SANS module (``module_id`` NULL) restent
      listées dans un bloc « Autres fonctionnalités », pour ne rien
      perdre.
    * Les frais fixes (toujours hors module) suivent comme avant.
    * Les totaux (sous-total / TPS / TVQ / TTC) ferment la section,
      réutilisés tels quels depuis ``compute_devis``.

    ⚠️ On ne montre JAMAIS au client : les heures de dev, les tâches du
    chargé de projet (``manager_task``, global, déjà fondu dans les
    totaux), les coûts internes. Un module NON sélectionné n'apparaît
    pas (il est exclu du total). Cohérent avec le PDF signé figé qui ne
    reflète que la sélection au moment de la signature."""
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    KeepTogether = rl["KeepTogether"]
    colors = rl["colors"]

    # Prix client par feature, indexé par id (depuis features_client, qui
    # ne contient que les features RETENUES — module sélectionné ou hors
    # module ; les features offertes y sont présentes avec prix 0).
    price_by_id: dict[Any, float] = {}
    for f in features_client:
        fid = f.get("id")
        if fid is not None:
            price_by_id[fid] = float(f.get("prix_client") or 0)

    # Ids des modules réellement connus (présents dans modules_detail).
    # Une feature dont le module_id n'est PAS connu (cas limite : item
    # rattaché à un module non chargé) bascule en « hors module » pour
    # ne jamais disparaître de l'affichage tout en restant dans le total.
    known_module_ids = {
        m.get("id") for m in modules_detail if m.get("id") is not None
    }

    # Index id -> nom de module (sur TOUS les modules connus, même non
    # sélectionnés) : sert à afficher la condition de gratuité « Si le
    # module "<déclencheur>" est sélectionné » dans la section offerte.
    name_by_module_id: dict[Any, str] = {}
    for m in modules_detail:
        mid = m.get("id")
        if mid is not None:
            name_by_module_id[mid] = (m.get("name") or "Module").strip() or "Module"

    # Regroupe les features RETENUES par module_id ; ``None`` = hors
    # module. On itère features_client (déjà filtré par la sélection),
    # donc un module non sélectionné n'apparaît jamais ici.
    feats_by_module: dict[Any, list[dict[str, Any]]] = {}
    for f in features_client:
        mid = f.get("module_id")
        if mid not in known_module_ids:
            mid = None
        feats_by_module.setdefault(mid, []).append(f)

    def _feature_flowables(
        feats: list[dict[str, Any]], green: bool
    ) -> list[Any]:
        """Sous-puces de fonctionnalités — VUE CLIENT : descriptions
        seules (le client achète un module, pas des lignes détaillées).
        Aucun prix par fonctionnalité ; seul le prix du module fait foi.
        Puces colorées discrètes, comme la page web."""
        style = s["feature_green"] if green else s["feature"]
        bullet = "&#8226;"  # • puce
        out: list[Any] = []
        for feat in feats:
            desc = (feat.get("description") or "").strip() or "—"
            out.append(Paragraph(f"{bullet}&nbsp;&nbsp;{desc}", style))
        return out

    def _module_card(
        name: str,
        feats: list[dict[str, Any]],
        prix_module: float,
        *,
        free: bool = False,
        condition: Optional[str] = None,
    ) -> Any:
        """Carte « module » calquée sur la page web : encadré arrondi
        (bordure fine + léger fond), en-tête avec le nom à gauche (gras)
        et le prix à droite (gras), puis les fonctionnalités en sous-puces
        discrètes SANS prix. Gardée ensemble (KeepTogether) pour ne pas
        couper une carte en plein milieu.

        Variante ``free`` : fond/bordure émeraude, badge « Offert »,
        condition de gratuité italique, prix « 0,00 $ »."""
        # En-tête : nom à gauche, prix (ou badge « Offert ») à droite.
        if free:
            name_p = Paragraph(name, s["free_name"])
            right_p = _offert_badge(rl, s)
        else:
            name_p = Paragraph(name, s["module_name"])
            right_p = Paragraph(_fmt_money(prix_module), s["module_price"])
        header = Table(
            [[name_p, right_p]], colWidths=["68%", "32%"]
        )
        header.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ])
        )

        inner: list[Any] = [header]
        if condition:
            inner.append(Spacer(1, 2))
            inner.append(Paragraph(condition, s["free_cond"]))
        feat_flows = _feature_flowables(feats, green=free)
        if feat_flows:
            inner.append(Spacer(1, 4))
            inner.extend(feat_flows)
        if free:
            inner.append(Spacer(1, 3))
            inner.append(Paragraph(_fmt_money(0), s["free_price"]))

        card = Table([[inner]], colWidths=["100%"])
        if free:
            border = _EMERALD_BORDER
            bg = _EMERALD_SOFT
        else:
            border = _CARD_BORDER
            bg = _CARD_BG
        card.setStyle(
            TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor(border)),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ])
        )
        return KeepTogether([card, Spacer(1, 6)])

    # --- Modules RETENUS et PAYANTS -------------------------------------
    # On respecte l'ordre de ``modules_detail``. On n'affiche que les
    # modules ``selected`` et non ``offert`` ici ; les offerts vont dans
    # « Inclus gratuitement », les non sélectionnés sont omis.
    paid_modules = [
        m
        for m in modules_detail
        if m.get("selected") and not m.get("offert")
    ]
    free_modules = [
        m
        for m in modules_detail
        if m.get("selected") and m.get("offert")
    ]

    for m in paid_modules:
        mid = m.get("id")
        name = (m.get("name") or "Module").strip() or "Module"
        feats = feats_by_module.get(mid, [])
        prix_module = float(m.get("prix_client") or 0)
        story.append(_module_card(name, feats, prix_module))

    # --- Fonctionnalités HORS module (module_id NULL) -------------------
    orphan_feats = feats_by_module.get(None, [])
    if orphan_feats:
        story.append(_orphan_block(rl, s, orphan_feats, price_by_id))

    # --- Section « Inclus gratuitement » --------------------------------
    if free_modules:
        story.append(Spacer(1, 4))
        story.append(Paragraph("INCLUS GRATUITEMENT", s["section_emerald"]))
        story.append(Spacer(1, 2))
        for m in free_modules:
            mid = m.get("id")
            name = (m.get("name") or "Module").strip() or "Module"
            feats = feats_by_module.get(mid, [])
            # Condition de gratuité : nom du module déclencheur (celui
            # dont la sélection rend ce module offert).
            trigger_id = m.get("free_when_module_id")
            condition: Optional[str] = None
            if trigger_id is not None:
                trigger_name = name_by_module_id.get(trigger_id)
                if trigger_name:
                    condition = (
                        f"(Si le module « {trigger_name} » est sélectionné)"
                    )
            story.append(
                _module_card(
                    name, feats, 0.0, free=True, condition=condition
                )
            )

    # --- Frais fixes (toujours hors module) -----------------------------
    if frais_fixes_client:
        ff_rows: list[list[Any]] = []
        ff_rows.append([
            Paragraph("<b>Frais fixes</b>", s["body_bold"]),
            Paragraph("", s["body"]),
        ])
        for ff in frais_fixes_client:
            desc = (ff.get("description") or "").strip() or "—"
            prix = float(ff.get("prix_client") or 0)
            ff_rows.append([
                Paragraph(f"&#8226;&nbsp;&nbsp;{desc}", s["body"]),
                Paragraph(_fmt_money(prix), s["tax_amount"]),
            ])
        ff_table = Table(ff_rows, colWidths=["68%", "32%"])
        ff_table.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor(_CARD_BORDER)),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.HexColor(_LINE)),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(Spacer(1, 2))
        story.append(ff_table)
        story.append(Spacer(1, 6))

    # --- Totaux ---------------------------------------------------------
    story.append(Spacer(1, 2))
    story.append(
        _tax_recap_table(
            rl, s, total_initial, tps_init, tvq_init, total_initial_taxe
        )
    )


def _offert_badge(rl: dict[str, Any], s: dict[str, Any]) -> Any:
    """Petit badge « Offert » (texte blanc sur pastille émeraude), façon
    page web. Rendu via une mini-table d'une cellule pour le fond et le
    padding serré ; alignée à droite par la cellule hôte."""
    Paragraph = rl["Paragraph"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    colors = rl["colors"]

    badge_style = rl["ParagraphStyle"](
        "offert_badge",
        parent=s["body"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        alignment=1,
        textColor=colors.white,
    )
    pill = Table(
        [[Paragraph("Offert", badge_style)]],
        colWidths=[42],
        hAlign="RIGHT",
    )
    pill.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(_EMERALD_BADGE)),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    return pill


def _orphan_block(
    rl: dict[str, Any],
    s: dict[str, Any],
    orphan_feats: list[dict[str, Any]],
    price_by_id: dict[Any, float],
) -> Any:
    """Bloc « Autres fonctionnalités » — features retenues sans module
    (``module_id`` NULL). Présenté comme un petit bloc à part (PAS une
    carte de module) : titre clair, sous-puces de descriptions, et le
    prix agrégé du bloc aligné à droite en bas. VUE CLIENT : pas de prix
    ligne par ligne, cohérent avec les modules."""
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    KeepTogether = rl["KeepTogether"]
    colors = rl["colors"]

    total_orphan = 0.0
    feat_flows: list[Any] = []
    for feat in orphan_feats:
        desc = (feat.get("description") or "").strip() or "—"
        fid = feat.get("id")
        prix = (
            price_by_id.get(fid)
            if fid is not None
            else float(feat.get("prix_client") or 0)
        )
        total_orphan += float(prix or 0)
        feat_flows.append(
            Paragraph(f"&#8226;&nbsp;&nbsp;{desc}", s["feature"])
        )

    # En-tête : titre à gauche, prix agrégé à droite.
    header = Table(
        [[
            Paragraph("Autres fonctionnalités", s["module_name"]),
            Paragraph(_fmt_money(total_orphan), s["module_price"]),
        ]],
        colWidths=["68%", "32%"],
    )
    header.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    inner: list[Any] = [header]
    if feat_flows:
        inner.append(Spacer(1, 4))
        inner.extend(feat_flows)

    card = Table([[inner]], colWidths=["100%"])
    card.setStyle(
        TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor(_CARD_BORDER)),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ffffff")),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ])
    )
    return KeepTogether([card, Spacer(1, 6)])


def _render_bytes(
    soumission: DevlogSoumission,
    items: list[DevlogSoumissionItem],
    client: Optional[DevlogClient],
    modules: Optional[list[DevlogSoumissionModule]] = None,
) -> bytes:
    rl = _lazy_reportlab()
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Image = rl["Image"]
    mm = rl["mm"]
    colors = rl["colors"]

    devis = compute_devis(soumission, items, modules)
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
        story.append(Spacer(1, 8))
        story.append(
            Paragraph("FRAIS MENSUELS RÉCURRENTS", s["section_emerald"])
        )
        story.append(Spacer(1, 3))
        # Grand cartouche vedette VERT (émeraude), comme la page web :
        # légende + gros montant TTC mensuel + « par mois ».
        story.append(
            _amount_box(
                rl,
                s,
                total_monthly_taxe,
                "Total mensuel taxes incluses",
                "par mois",
                emerald=True,
            )
        )

        # Inclusions (description libre ou liste de libellés) — puces
        # émeraude discrètes, façon page web.
        client_recurring_desc = (
            soumission.client_recurring_description or ""
        ).strip()
        if client_recurring_desc:
            story.append(Spacer(1, 6))
            story.append(Paragraph(client_recurring_desc, s["body"]))
        elif recurring_items_breakdown:
            story.append(Spacer(1, 6))
            story.append(Paragraph("<b>Inclut</b>", s["body_bold"]))
            story.append(Spacer(1, 2))
            for it in recurring_items_breakdown:
                desc = (it.get("description") or "").strip() or "—"
                story.append(
                    Paragraph(f"&#8226;&nbsp;&nbsp;{desc}", s["feature_green"])
                )

        # Détail des taxes (récap émeraude, même composant que l'initial)
        if total_monthly_client > 0:
            story.append(Spacer(1, 6))
            story.append(
                _tax_recap_table(
                    rl,
                    s,
                    total_monthly_client,
                    tps_rec,
                    tvq_rec,
                    total_monthly_taxe,
                    subtotal_label="Sous-total mensuel",
                    ttc_label="Total mensuel TTC",
                    accent=_EMERALD,
                    total_bg=_EMERALD_SOFT,
                    total_fg=_EMERALD_DARK,
                    border=_EMERALD_BORDER,
                )
            )

    # --- 3. Section Investissement initial ---
    features_client = initial.get("features_client") or []
    frais_fixes_client = initial.get("frais_fixes_client") or []
    modules_detail = initial.get("modules") or []
    total_initial = float(initial.get("total_final") or 0)
    tps_init = float(initial.get("tps_amount") or 0)
    tvq_init = float(initial.get("tvq_amount") or 0)
    total_initial_taxe = float(initial.get("total_final_taxe") or 0)

    # ``has_modules`` distingue le rendu « par module » (refonte 2026-06,
    # Phase 5) du chemin LEGACY (liste plate de fonctionnalités). On ne
    # bascule en mode module QUE si la soumission a réellement des
    # modules : une soumission sans modules produit un PDF strictement
    # identique à avant (rétrocompat).
    has_modules = bool(modules_detail)

    if features_client or frais_fixes_client or total_initial > 0:
        story.append(Spacer(1, 10))
        story.append(Paragraph("INVESTISSEMENT INITIAL", s["section"]))
        story.append(Spacer(1, 3))

        # Grand cartouche vedette BLEU : le total TTC, payé une seule fois,
        # bien en évidence en tête de section (comme la page web). Le
        # détail par module / liste plate et les totaux suivent dessous.
        story.append(
            _amount_box(
                rl,
                s,
                total_initial_taxe,
                "Total taxes incluses",
                "payé une seule fois",
            )
        )
        story.append(Spacer(1, 8))

        if has_modules:
            _render_modules_initial(
                rl,
                s,
                story,
                features_client,
                frais_fixes_client,
                modules_detail,
                total_initial,
                tps_init,
                tvq_init,
                total_initial_taxe,
            )
        else:
            _render_flat_initial(
                rl,
                s,
                story,
                features_client,
                frais_fixes_client,
                total_initial,
                tps_init,
                tvq_init,
                total_initial_taxe,
            )

    # --- Conditions ---
    story.append(Spacer(1, 10))
    story.append(Paragraph("CONDITIONS", s["section"]))
    story.append(Spacer(1, 3))
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
    story.append(Spacer(1, 3))
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
    soumission, items, client, modules = await _load(db, soumission_id)
    if soumission is None:
        raise ValueError(f"Soumission {soumission_id} introuvable.")
    if not getattr(soumission, "is_devis_dev", False):
        raise ValueError(
            "Seules les soumissions au nouveau format devis_dev "
            "peuvent générer un PDF."
        )
    return _render_bytes(soumission, items, client, modules)


def _render_signed_bytes(
    soumission: DevlogSoumission,
    items: list[DevlogSoumissionItem],
    client: Optional[DevlogClient],
    modules: Optional[list[DevlogSoumissionModule]] = None,
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

    base_pdf = _render_bytes(soumission, items, client, modules)
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
    soumission, items, client, modules = await _load(db, soumission_id)
    if soumission is None:
        raise ValueError(f"Soumission {soumission_id} introuvable.")
    if not getattr(soumission, "is_devis_dev", False):
        raise ValueError(
            "Seules les soumissions devis_dev ont un PDF signé."
        )
    return _render_signed_bytes(soumission, items, client, modules)
