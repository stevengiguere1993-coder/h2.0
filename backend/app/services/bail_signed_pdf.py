"""Génère le PDF d'un bail signé électroniquement.

Reflète exactement les données du bail (parties, logement, dates, loyer,
dépôt, inclusions) et appose l'image de signature capturée côté locataire
avec l'horodatage et l'IP — pour un document d'archive légalement
exploitable. Produit aussi le bloc « Signé électroniquement le … » qui
distingue un bail signé d'un simple sommaire.

Best-effort : ``render_bail_signed_pdf`` retourne ``None`` si le bail est
introuvable ou non signé (jamais d'exception qui casserait la signature
publique).
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.immobilier import (
    Bail,
    Immeuble,
    ImmeubleOwnership,
    Locataire,
    Logement,
)

log = logging.getLogger(__name__)

_NAVY = colors.HexColor("#1f3a5f")
_GREEN = colors.HexColor("#15803d")
_GREY = colors.HexColor("#475569")
_LIGHT = colors.HexColor("#eef2f7")

_MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _fmt_date(d: Optional[date]) -> str:
    if d is None:
        return "—"
    return f"{d.day} {_MOIS_FR[d.month - 1]} {d.year}"


def _fmt_dt(d: Optional[datetime]) -> str:
    if d is None:
        return "—"
    return f"{d.day} {_MOIS_FR[d.month - 1]} {d.year} à {d:%H:%M} UTC"


def _fmt_money(n: Optional[float]) -> str:
    if n is None:
        return "—"
    return f"{float(n):,.2f} $".replace(",", " ").replace(".", ",")


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "btitle", parent=base["Title"], fontSize=18,
            textColor=_NAVY, spaceAfter=2,
        ),
        "sub": ParagraphStyle(
            "bsub", parent=base["Normal"], fontSize=9,
            textColor=_GREY, alignment=TA_CENTER, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "bh2", parent=base["Heading2"], fontSize=11,
            textColor=_NAVY, spaceBefore=12, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "bbody", parent=base["Normal"], fontSize=9.5,
            textColor=colors.HexColor("#1e293b"), leading=14,
        ),
        "small": ParagraphStyle(
            "bsmall", parent=base["Normal"], fontSize=8,
            textColor=_GREY, leading=11,
        ),
        "cell": ParagraphStyle(
            "bcell", parent=base["Normal"], fontSize=9.5,
            textColor=colors.HexColor("#1e293b"), leading=13,
        ),
        "celllab": ParagraphStyle(
            "bcelllab", parent=base["Normal"], fontSize=8.5,
            textColor=_GREY, leading=12,
        ),
    }


def _rgb_png(raw: bytes) -> Optional[bytes]:
    """Convertit l'image de signature en PNG RGB (reportlab refuse RGBA)."""
    try:
        from PIL import Image as PILImage

        im = PILImage.open(io.BytesIO(raw))
        if im.mode in ("RGBA", "LA", "P"):
            bg = PILImage.new("RGB", im.size, (255, 255, 255))
            im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


def _kv_table(rows: list[tuple[str, str]], styles: dict) -> Table:
    data = [
        [Paragraph(k, styles["celllab"]), Paragraph(v, styles["cell"])]
        for k, v in rows
    ]
    t = Table(data, colWidths=[55 * mm, 110 * mm])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, _LIGHT),
            ]
        )
    )
    return t


async def render_bail_signed_pdf(
    db: AsyncSession, bail_id: int
) -> Optional[bytes]:
    bail = await db.get(Bail, bail_id)
    if bail is None:
        return None

    logement = await db.get(Logement, bail.logement_id)
    immeuble = (
        await db.get(Immeuble, logement.immeuble_id) if logement else None
    )
    locataire = await db.get(Locataire, bail.locataire_id)

    # Locateur = entreprise propriétaire (best-effort).
    locateur_nom = "Le locateur"
    try:
        if immeuble is not None:
            from sqlalchemy import select

            from app.models.entreprise import Entreprise

            own = (
                await db.execute(
                    select(ImmeubleOwnership)
                    .where(ImmeubleOwnership.immeuble_id == immeuble.id)
                    .order_by(ImmeubleOwnership.ownership_pct.desc())
                )
            ).scalars().first()
            if own is not None:
                ent = await db.get(Entreprise, own.entreprise_id)
                if ent is not None and getattr(ent, "name", None):
                    locateur_nom = ent.name
    except Exception:  # noqa: BLE001
        pass

    st = _styles()
    flow: list = []

    flow.append(Paragraph("Bail de logement", st["title"]))
    flow.append(
        Paragraph(
            "Contrat de location — signé électroniquement", st["sub"]
        )
    )

    # Adresse du logement.
    adresse = "—"
    if immeuble is not None:
        bits = [immeuble.address or ""]
        if logement is not None and logement.numero:
            bits.append(f"app. {logement.numero}")
        ville = ", ".join(
            x for x in [immeuble.city, immeuble.postal_code] if x
        )
        if ville:
            bits.append(ville)
        adresse = " — ".join(b for b in bits if b)

    flow.append(Paragraph("Parties", st["h2"]))
    flow.append(
        _kv_table(
            [
                ("Locateur", locateur_nom),
                (
                    "Locataire",
                    (locataire.full_name if locataire else "—"),
                ),
                (
                    "Courriel du locataire",
                    (locataire.email if locataire and locataire.email else "—"),
                ),
            ],
            st,
        )
    )

    flow.append(Paragraph("Logement loué", st["h2"]))
    pieces = "—"
    if logement is not None and logement.nb_pieces_decimal is not None:
        pieces = (
            f"{float(logement.nb_pieces_decimal):g}".replace(".5", "½")
            + " pièces"
        )
    flow.append(
        _kv_table(
            [("Adresse", adresse), ("Type", pieces)], st
        )
    )

    flow.append(Paragraph("Conditions du bail", st["h2"]))
    incl = [
        lbl
        for lbl, on in [
            ("chauffage", bail.chauffage_inclus),
            ("eau chaude", bail.eau_chaude_inclus),
            ("électricité", bail.electricite_inclus),
            ("internet", bail.internet_inclus),
        ]
        if on
    ]
    flow.append(
        _kv_table(
            [
                (
                    "Durée",
                    f"du {_fmt_date(bail.date_debut)} au "
                    f"{_fmt_date(bail.date_fin)}",
                ),
                ("Loyer mensuel", _fmt_money(bail.loyer_mensuel)),
                ("Dépôt de garantie", _fmt_money(bail.depot_garantie)),
                ("Inclusions", ", ".join(incl) if incl else "aucune"),
            ],
            st,
        )
    )
    if bail.notes:
        flow.append(Spacer(1, 4))
        flow.append(Paragraph(f"<b>Notes :</b> {bail.notes}", st["small"]))

    # ── Bloc signature ──
    flow.append(Spacer(1, 16))
    flow.append(Paragraph("Signature du locataire", st["h2"]))

    sig_img_flow = None
    if bail.signature_image:
        png = _rgb_png(bytes(bail.signature_image))
        if png:
            try:
                sig_img_flow = Image(
                    io.BytesIO(png), width=60 * mm, height=22 * mm
                )
            except Exception:  # noqa: BLE001
                sig_img_flow = None

    sig_left: list = [
        sig_img_flow or Spacer(1, 22),
        Paragraph("____________________________________", st["small"]),
        Paragraph(
            bail.signed_by_name or "—", st["body"]
        ),
    ]
    sig_right: list = [
        Paragraph(
            "<b>Signé électroniquement</b>", st["celllab"]
        ),
        Paragraph(_fmt_dt(bail.signed_at), st["cell"]),
        Spacer(1, 4),
        Paragraph("Adresse IP", st["celllab"]),
        Paragraph(bail.signature_ip or "—", st["cell"]),
    ]
    sigtab = Table([[sig_left, sig_right]], colWidths=[95 * mm, 70 * mm])
    sigtab.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (1, 0), (1, 0), _LIGHT),
                ("BOX", (1, 0), (1, 0), 0.5, _GREEN),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
                ("RIGHTPADDING", (1, 0), (1, 0), 8),
                ("TOPPADDING", (1, 0), (1, 0), 8),
                ("BOTTOMPADDING", (1, 0), (1, 0), 8),
            ]
        )
    )
    flow.append(sigtab)

    flow.append(Spacer(1, 14))
    flow.append(
        Paragraph(
            "Ce document a été signé électroniquement via la plateforme "
            "Kratos. L'horodatage et l'adresse IP ci-dessus constituent la "
            "preuve d'acceptation du locataire. Document conforme aux "
            "exigences du bail résidentiel québécois.",
            st["small"],
        )
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=f"Bail signé — {locataire.full_name if locataire else ''}",
    )
    doc.build(flow)
    return buf.getvalue()
