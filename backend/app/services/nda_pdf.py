"""Génère le PDF d'une Entente de confidentialité et de
non-contournement (NDA — modèle MGV Développement v2).

Deux variantes :
- `render_nda_pdf` (PDF de prévisualisation, bloc Récepteur vide,
  image MGV affichée mais zone signature investisseur en blanc)
- `generate_signed_nda_pdf` (PDF post-signature, bloc Récepteur
  rempli avec nom + email + date + mention « Signée électronique-
  ment », et bandeau emerald-600 en haut + hash SHA-256 du document)

Le PDF signé est stocké dans `NDA.signed_pdf_blob` au moment de la
signature publique (cf. `public_nda.py::sign_nda`). Pattern repris
de la PR #497 (devlog_soumission_pdf.generate_signed_pdf).

Document légal multi-pages — version v2 qui remplace l'ancien
modèle Horizon Services Immobiliers (5 sections) par le modèle
MGV Développement (11 articles + préambule + bloc signatures).

Structure :
- Header (logo + titre)
- Bloc d'ouverture (Date d'effet, identification des Parties)
- PRÉAMBULE (ATTENDU QUE … + EN CONTREPARTIE)
- 11 articles numérotés (avec sous-articles et listes (a)(b)(c)...)
- Bloc signatures (MGV à gauche, Récepteur à droite)
- Mentions légales en pied

⚠️ Aucune référence à l'adresse de la propriété n'apparaît dans
le NDA rendu. Le NDA est signé AVANT que MGV identifie
l'Opportunité à l'investisseur. Faire apparaître l'adresse de
l'immeuble dans le NDA défait son propre objet.

ReportLab pur Python — pas de dépendance système, compatible
Render Free comme `offer_pdf.py`. SimpleDocTemplate gère
automatiquement le page break sur les 11+ pages prévues.
"""

from __future__ import annotations

import io
import logging
import os
import re
import unicodedata
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.nda import NDA
from app.models.prospection_deal import ProspectionDeal
from app.services.nda_template import (
    ENGAGEMENT_ITEMS,
    ISSUER_EMAIL,
    ISSUER_ENTITY_ADDRESS,
    ISSUER_ENTITY_NAME,
    ISSUER_INCORPORATION_LAW,
    ISSUER_PHONE,
    ISSUER_REPRESENTATIVE_NAME,
    ISSUER_REPRESENTATIVE_TITLE,
    LEGAL_NOTICE,
    NDA_DAMAGES_FLOOR_CAD,
    NDA_DURATION_YEARS,
    NDA_VENUE,
    resolve_investor_clauses,
)


log = logging.getLogger(__name__)


_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "logo.png",
)

# Image de signature manuscrite MGV. Le fichier n'existe pas encore
# dans le repo — Phil le déposera dans `backend/app/assets/` dans
# une PR ultérieure. Si absent, le bloc signature MGV affiche
# simplement un espace vide (pas de placeholder texte).
MGV_SIGNATURE_IMAGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "mgv_signature.png",
)

# Mois français-CA pour formater la date d'effet et la date MGV
# au format « 27 mai 2026 » plutôt que « 2026-05-27 ».
_MONTHS_FR_CA = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


# Cache du fichier RGB pré-converti — on évite de refaire la
# conversion PIL à chaque génération de PDF (5+ par minute possible
# en cas de relance massive). Le chemin est lazy-resolved à la
# première utilisation et conservé jusqu'au prochain restart Render.
_MGV_SIGNATURE_RGB_CACHE: Optional[str] = None


def _prepare_mgv_signature_rgb_file() -> Optional[str]:
    """Pré-convertit `mgv_signature.png` (RGBA) en RGB sur disque et
    retourne le chemin du fichier prêt-à-consommer par reportlab.

    Pourquoi cette approche fichier (vs BytesIO mémoire) :
    après PR #524, le pattern « PIL → BytesIO → reportlab.Image(buf) »
    ne semble TOUJOURS pas fonctionner en prod Render — le PDF arrive
    sans la signature manuscrite. reportlab reconstruit en interne un
    ImageReader, et selon les versions un BytesIO peut être consommé
    une seule fois (premier `doc.build()` OK, suivants KO). En passant
    par un chemin de fichier RGB stable, reportlab ouvre lui-même le
    fichier à chaque build — c'est le pattern qui fonctionne pour le
    logo (`_LOGO_PATH`) qui s'affiche, lui, correctement.

    Retourne le path du PNG RGB temporaire, ou None si :
    - le fichier source n'existe pas (asset pas déployé)
    - PIL n'est pas installé
    - la conversion échoue (PNG corrompu)
    Dans ces trois cas, l'appelant retombe sur le `Spacer` fallback.
    """
    global _MGV_SIGNATURE_RGB_CACHE
    if _MGV_SIGNATURE_RGB_CACHE and os.path.exists(_MGV_SIGNATURE_RGB_CACHE):
        return _MGV_SIGNATURE_RGB_CACHE

    src = MGV_SIGNATURE_IMAGE_PATH
    if not os.path.exists(src):
        log.warning(
            "[NDA_PDF] Image signature MGV ABSENTE du disque "
            "(path=%s). Le PDF sera généré sans signature manuscrite "
            "(fallback Spacer). Vérifier que `backend/app/assets/"
            "mgv_signature.png` est bien commité et déployé.",
            src,
        )
        return None

    dst = src.replace(".png", "_rgb.png")
    # Si le fichier RGB existe déjà sur disque (générée par un
    # process précédent), on le réutilise sans toucher PIL.
    if os.path.exists(dst):
        log.info("[NDA_PDF] Réutilisation cache RGB signature (%s)", dst)
        _MGV_SIGNATURE_RGB_CACHE = dst
        return dst

    try:
        from PIL import Image as PILImage  # type: ignore
    except Exception as exc:
        log.warning(
            "[NDA_PDF] PIL/Pillow indisponible — impossible de "
            "convertir mgv_signature.png en RGB : %s. Fallback Spacer.",
            exc,
        )
        return None

    try:
        pil = PILImage.open(src)
        log.info(
            "[NDA_PDF] mgv_signature.png chargée : mode=%s size=%s",
            pil.mode,
            pil.size,
        )
        if pil.mode != "RGB":
            bg = PILImage.new("RGB", pil.size, (255, 255, 255))
            if pil.mode == "P":
                pil = pil.convert("RGBA")
            if pil.mode in ("RGBA", "LA"):
                alpha = pil.split()[-1]
                bg.paste(pil, mask=alpha)
            else:
                bg.paste(pil.convert("RGB"))
            pil = bg
        pil.save(dst, format="PNG")
        log.info(
            "[NDA_PDF] Conversion RGB de mgv_signature.png réussie "
            "→ %s (%d octets)",
            dst,
            os.path.getsize(dst),
        )
        _MGV_SIGNATURE_RGB_CACHE = dst
        return dst
    except Exception as exc:
        log.exception(
            "[NDA_PDF] Conversion PNG signature MGV échouée (%s): %s. "
            "Fallback Spacer activé pour ce build.",
            src,
            exc,
        )
        return None


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


def _date_fr(d) -> str:
    if d is None:
        return "____________"
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%Y-%m-%d")


def _date_fr_ca_long(d) -> str:
    """Formate une date au format français-CA long, ex: « 27 mai 2026 ».

    Utilisé pour la Date d'effet et la date MGV du bloc signature
    afin d'éviter le format ISO austère côté investisseur.
    """
    if d is None:
        return "____________"
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.day} {_MONTHS_FR_CA[d.month - 1]} {d.year}"


def _styles(rl: dict[str, Any]):
    PS = rl["ParagraphStyle"]
    base = rl["getSampleStyleSheet"]()
    colors = rl["colors"]
    dark = colors.HexColor("#111111")
    muted = colors.HexColor("#6b6b6b")
    # Bleu Horizon — distingue visuellement le NDA de l'Offre d'achat
    # (qui utilise un vert #2f7d32).
    accent = colors.HexColor("#1d4ed8")
    return {
        "title": PS(
            "title",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=dark,
            alignment=1,  # centré
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
            spaceBefore=10,
            spaceAfter=4,
            borderPadding=4,
        ),
        "subsection": PS(
            "subsection",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=dark,
            spaceBefore=4,
            spaceAfter=2,
        ),
        "preamble": PS(
            "preamble",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=dark,
            alignment=1,  # centré
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": PS(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=dark,
            alignment=4,  # justifié
            spaceAfter=4,
        ),
        "body_l1": PS(
            "body_l1",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=dark,
            leftIndent=14,
            alignment=4,
            spaceAfter=3,
        ),
        "body_l2": PS(
            "body_l2",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=dark,
            leftIndent=28,
            alignment=4,
            spaceAfter=3,
        ),
        "opportunity": PS(
            "opportunity",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=10,
            leading=13,
            textColor=dark,
            backColor=colors.HexColor("#eff6ff"),
            borderColor=accent,
            borderWidth=0.5,
            borderPadding=6,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "small": PS(
            "small",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=dark,
        ),
        "small_muted": PS(
            "small_muted",
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
    }


async def _load(
    db: AsyncSession, nda_id: int
) -> tuple[Optional[NDA], Optional[ProspectionDeal]]:
    nda = (
        await db.execute(select(NDA).where(NDA.id == nda_id))
    ).scalar_one_or_none()
    if nda is None:
        return None, None
    deal = (
        await db.execute(
            select(ProspectionDeal).where(
                ProspectionDeal.id == nda.deal_id
            )
        )
    ).scalar_one_or_none()
    return nda, deal


def _render_bytes(
    nda: NDA,
    deal: Optional[ProspectionDeal],
    *,
    force_signed_block: bool = False,
) -> bytes:
    """Rend le PDF du NDA.

    `force_signed_block=True` : utilisé par `generate_signed_nda_pdf`
    pour remplir le bloc Récepteur (nom, courriel, date, mention
    « Signée électroniquement ») même si `nda.signed_at` n'est pas
    encore committé en DB (cas du pipeline post-signature publique).
    """
    rl = _lazy_reportlab()
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Image = rl["Image"]
    mm = rl["mm"]
    colors = rl["colors"]

    buf = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=rl["A4"],
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Entente de confidentialité {nda.id}",
        author=ISSUER_ENTITY_NAME,
    )
    s = _styles(rl)
    story: list = []

    # Date d'effet : utilisée à la fois dans l'entête (« CET ACCORD
    # est conclu en date du … ») et dans la colonne MGV du bloc
    # signatures (auto-remplie — Phil ne signe pas une seconde fois
    # côté investisseur). Format long « 27 mai 2026 ».
    emission_date_obj = nda.sent_at or nda.signed_at or datetime.utcnow()
    emission_date = _date_fr_ca_long(emission_date_obj)
    investor_name = (
        nda.investor_name.strip()
        if nda.investor_name and nda.investor_name.strip()
        else "____________"
    )
    type_cl, addr_cl, repr_cl = resolve_investor_clauses(None, None, None)
    damages_amount = f"{NDA_DAMAGES_FLOOR_CAD:,}".replace(",", " ")
    # NOTE: `deal` est désormais inutilisé pour le rendu (l'adresse de
    # la propriété n'est PLUS injectée dans le NDA). On le garde dans
    # la signature pour rétrocompat et pour permettre, à terme,
    # d'éventuels métadonnées non-juridiques (ex: référence interne).
    del deal  # silence linter

    # --- Header logo + titre ---
    if os.path.exists(_LOGO_PATH):
        try:
            header_logo = Image(_LOGO_PATH, width=20 * mm, height=20 * mm)
            header = Table(
                [[
                    header_logo,
                    Paragraph(f"<b>{ISSUER_ENTITY_NAME}</b>", s["small"]),
                ]],
                colWidths=[24 * mm, "*"],
            )
            header.setStyle(
                TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ])
            )
            story.append(header)
            story.append(Spacer(1, 6))
        except Exception:
            pass

    story.append(Paragraph(
        "ENTENTE DE CONFIDENTIALITÉ ET DE NON-CONTOURNEMENT",
        s["title"],
    ))
    story.append(Spacer(1, 10))

    # --- Bloc d'ouverture : Date d'effet et Parties ---
    story.append(Paragraph(
        f"CET ACCORD est conclu en date du <b>{emission_date}</b> "
        f"(la « <b>Date d'effet</b> »), entre :",
        s["body"],
    ))
    story.append(Spacer(1, 6))

    story.append(Paragraph(
        f"<b>{ISSUER_ENTITY_NAME}</b>, société par actions "
        f"légalement constituée en vertu de la "
        f"{ISSUER_INCORPORATION_LAW}, ayant son siège au "
        f"{ISSUER_ENTITY_ADDRESS}, représentée aux fins des "
        f"présentes par {ISSUER_REPRESENTATIVE_NAME}, "
        f"{ISSUER_REPRESENTATIVE_TITLE}, dûment autorisé tel "
        f"qu'il le déclare en signant (ci-après la « Société » ou "
        f"« <b>MGV</b> »);",
        s["body"],
    ))
    story.append(Spacer(1, 4))

    receiver_paragraph = (
        f"<b>ET {investor_name}</b>, {type_cl}, {addr_cl}"
    )
    if repr_cl:
        receiver_paragraph += f", {repr_cl}"
    receiver_paragraph += " (ci-après le « <b>Récepteur</b> »);"
    story.append(Paragraph(receiver_paragraph, s["body"]))
    story.append(Spacer(1, 4))

    story.append(Paragraph(
        "Collectivement désignés les « <b>Parties</b> ».",
        s["body"],
    ))

    # --- Préambule ---
    story.append(Spacer(1, 8))
    story.append(Paragraph("PRÉAMBULE", s["preamble"]))
    for clause in [
        "ATTENDU QUE la Société est active dans l'investissement "
        "immobilier au Québec, incluant l'identification, l'analyse, "
        "l'acquisition, le développement et la gestion d'immeubles, "
        "ainsi que dans la création et la mise en œuvre de "
        "stratégies value-add;",
        "ATTENDU QUE la Société souhaite partager au Récepteur "
        "certaines Informations Confidentielles (telles que définies "
        "ci-après) relatives à une ou plusieurs opportunités "
        "d'investissement immobilier (chacune, l'« <b>Opportunité</b> » "
        "et collectivement les « <b>Opportunités</b> ») afin que le "
        "Récepteur puisse évaluer une participation potentielle, sous "
        "toute forme (investisseur passif, partenaire actif, "
        "co-acquéreur, courtier, intermédiaire, conseiller "
        "professionnel, ou autre rôle);",
        "ATTENDU QUE le Récepteur est susceptible, dans le cadre de "
        "sa propre activité, de partager certaines informations "
        "confidentielles à la Société;",
        "ATTENDU QUE les Parties souhaitent encadrer les conditions "
        "sous lesquelles ces informations seront divulguées, "
        "utilisées et protégées;",
    ]:
        story.append(Paragraph(clause, s["body"]))

    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "<b>EN CONTREPARTIE</b> des engagements mutuels contenus aux "
        "présentes, les Parties conviennent de ce qui suit :",
        s["body"],
    ))

    # --- Article 1 ---
    story.append(Paragraph("1. OBJET", s["section"]))
    story.append(Paragraph(
        "L'objet du présent Accord est de permettre aux Parties de "
        "divulguer, échanger et discuter des Informations "
        "Confidentielles relatives à une ou plusieurs Opportunités "
        "d'investissement immobilier au Québec, afin que le "
        "Récepteur puisse évaluer une éventuelle participation, "
        "sous toute forme.",
        s["body"],
    ))

    # --- Article 2 ---
    story.append(Paragraph(
        "2. DÉFINITION DES INFORMATIONS CONFIDENTIELLES",
        s["section"],
    ))
    story.append(Paragraph(
        "<b>2.1</b> Le terme « <b>Informations Confidentielles</b> » "
        "désigne toute information, de quelque nature et sous "
        "quelque forme que ce soit (écrite, orale, électronique, "
        "visuelle, ou autre), divulguée par une Partie (la « <b>Partie "
        "Divulgatrice</b> ») à l'autre Partie (la « <b>Partie "
        "Réceptrice</b> ») dans le cadre du présent Accord, incluant "
        "notamment et sans s'y limiter :",
        s["body"],
    ))
    for letter, text in [
        ("a", "L'adresse, l'identité, la description physique et "
              "juridique, et la localisation de tout immeuble visé "
              "par une Opportunité;"),
        ("b", "Le prix d'achat, les conditions financières, la "
              "structure de financement et la structure de la "
              "transaction;"),
        ("c", "Le registre des locataires (rent-roll), les baux, "
              "les loyers, les conditions de location, et toute "
              "information relative aux locataires;"),
        ("d", "Les états financiers, les revenus, les dépenses, les "
              "projections financières, le NOI, les taux de "
              "capitalisation, les ratios financiers, et toute "
              "analyse financière relative à l'Opportunité;"),
        ("e", "Les stratégies value-add, les plans de rénovation, "
              "les plans de développement, les budgets de travaux, "
              "et les échéanciers associés;"),
        ("f", "L'identité et les coordonnées du vendeur, des "
              "courtiers, des intermédiaires, des partenaires, des "
              "prêteurs, des conseillers professionnels et de tout "
              "tiers impliqué dans l'Opportunité;"),
        ("g", "Le fait même que la Société évalue, négocie, "
              "considère ou s'intéresse à une Opportunité "
              "particulière;"),
        ("h", "Toute présentation, deck d'investisseur, mémo, plan "
              "d'affaires, analyse, ou tout autre document préparé "
              "ou transmis par la Société;"),
        ("i", "Tous les termes, conditions et négociations relatifs "
              "à l'Opportunité, ainsi que leur progression;"),
        ("j", "Toute autre information, donnée ou document divulgué "
              "dans le cadre de l'Opportunité, qu'il soit "
              "explicitement identifié comme confidentiel ou non."),
    ]:
        story.append(Paragraph(f"({letter}) {text}", s["body_l1"]))

    story.append(Paragraph(
        "<b>2.2</b> Sont exclus de la définition d'Informations "
        "Confidentielles :",
        s["body"],
    ))
    for letter, text in [
        ("a", "Les informations qui étaient déjà généralement "
              "connues du public ou accessibles à celui-ci au "
              "moment de la divulgation;"),
        ("b", "Les informations devenues publiques après la "
              "divulgation, sans qu'il y ait eu bris du présent "
              "Accord par la Partie Réceptrice ou ses "
              "Représentants;"),
        ("c", "Les informations reçues légitimement d'un tiers sans "
              "obligation de confidentialité et sans bris d'une "
              "obligation de confidentialité;"),
        ("d", "Les informations dont la divulgation est "
              "expressément autorisée par écrit par la Partie "
              "Divulgatrice;"),
        ("e", "Les informations développées indépendamment par la "
              "Partie Réceptrice sans utilisation des Informations "
              "Confidentielles."),
    ]:
        story.append(Paragraph(f"({letter}) {text}", s["body_l1"]))

    story.append(Paragraph(
        "<b>2.3</b> Le terme « <b>Représentant</b> » désigne, à "
        "l'égard d'une Partie, ses administrateurs, dirigeants, "
        "employés, mandataires, courtiers, partenaires d'affaires, "
        "conseillers juridiques, conseillers financiers, "
        "comptables, banquiers et autres conseillers professionnels.",
        s["body"],
    ))

    # --- Article 3 ---
    story.append(Paragraph(
        "3. ENGAGEMENTS DE LA PARTIE RÉCEPTRICE", s["section"]
    ))
    story.append(Paragraph(
        "La Partie Réceptrice s'engage à :", s["body"]
    ))
    for i, raw in enumerate(ENGAGEMENT_ITEMS, start=1):
        story.append(Paragraph(f"<b>3.{i}</b> {raw}", s["body"]))

    # --- Article 4 ---
    story.append(Paragraph(
        "4. NON-CONTOURNEMENT ET NON-SOLLICITATION", s["section"]
    ))
    story.append(Paragraph(
        "<b>4.1 Non-contournement.</b> La Partie Réceptrice "
        "s'engage, pendant la durée du présent Accord et pour une "
        "période additionnelle de <b>vingt-quatre (24) mois</b> "
        "suivant sa terminaison, à ne pas, directement ou "
        "indirectement (incluant par l'entremise d'un tiers, d'une "
        "société affiliée, d'un mandataire, ou de toute autre "
        "personne agissant pour son compte) :",
        s["body"],
    ))
    for letter, text in [
        ("a", "Approcher, contacter, négocier ou conclure une "
              "transaction avec le vendeur, le propriétaire ou les "
              "actionnaires d'un immeuble visé par une Opportunité, "
              "sans la participation et l'autorisation écrite "
              "préalable de la Société;"),
        ("b", "Approcher, contacter ou solliciter tout courtier, "
              "intermédiaire, partenaire, prêteur ou conseiller "
              "dont l'identité a été divulguée dans le cadre d'une "
              "Opportunité, dans le but de poursuivre, faciliter "
              "ou conclure une transaction concurrente ou parallèle "
              "à l'Opportunité;"),
        ("c", "Présenter, divulguer, partager ou offrir "
              "l'Opportunité (en tout ou en partie) à un tiers "
              "(incluant tout investisseur, acheteur, partenaire ou "
              "société) sans l'autorisation écrite préalable de la "
              "Société;"),
        ("d", "Soumettre une offre d'achat, signer une promesse "
              "d'achat ou conclure toute entente relative à un "
              "immeuble visé par une Opportunité, pour son propre "
              "compte ou pour le compte d'un tiers, sans la "
              "participation de la Société."),
    ]:
        story.append(Paragraph(f"({letter}) {text}", s["body_l1"]))

    story.append(Paragraph(
        "<b>4.2 Non-sollicitation.</b> La Partie Réceptrice "
        "s'engage, pendant la durée du présent Accord et pour une "
        "période additionnelle de vingt-quatre (24) mois suivant "
        "sa terminaison, à ne pas solliciter les locataires d'un "
        "immeuble visé par une Opportunité, ni les autres "
        "partenaires, investisseurs ou intervenants impliqués dans "
        "une Opportunité.",
        s["body"],
    ))

    # --- Article 5 ---
    story.append(Paragraph(
        "5. AUCUNE DÉCLARATION NI GARANTIE", s["section"]
    ))
    story.append(Paragraph(
        "La Partie Réceptrice reconnaît que la Partie Divulgatrice "
        "(ni ses Représentants) ne fait aucune déclaration ni ne "
        "donne aucune garantie, expresse ou implicite, quant à "
        "l'exactitude, l'exhaustivité ou la fiabilité des "
        "Informations Confidentielles. La Partie Divulgatrice n'est "
        "pas responsable des décisions prises par la Partie "
        "Réceptrice sur la base des Informations Confidentielles.",
        s["body"],
    ))

    # --- Article 6 ---
    story.append(Paragraph("6. PROPRIÉTÉ DES INFORMATIONS", s["section"]))
    story.append(Paragraph(
        "Tous les droits, titres et intérêts relatifs aux "
        "Informations Confidentielles, ainsi qu'à tous les supports "
        "les contenant, demeurent la propriété exclusive de la "
        "Partie Divulgatrice. Le présent Accord ne concède aucun "
        "droit de licence, de propriété intellectuelle ou de "
        "quelque autre nature à la Partie Réceptrice.",
        s["body"],
    ))

    # --- Article 7 ---
    story.append(Paragraph(
        "7. AUCUNE OBLIGATION DE TRANSACTION", s["section"]
    ))
    story.append(Paragraph(
        "Le présent Accord ne crée aucune obligation pour la "
        "Société de conclure une transaction avec la Partie "
        "Réceptrice, ni pour la Partie Réceptrice d'investir dans "
        "ou de participer à l'Opportunité.",
        s["body"],
    ))

    # --- Article 8 ---
    story.append(Paragraph("8. DURÉE ET RÉSILIATION", s["section"]))
    duree_lettres = (
        "vingt-quatre" if NDA_DURATION_YEARS == 2 else str(NDA_DURATION_YEARS * 12)
    )
    duree_mois = NDA_DURATION_YEARS * 12
    story.append(Paragraph(
        f"<b>8.1</b> Le présent Accord entre en vigueur à la Date "
        f"d'effet et demeure en vigueur pour une période de "
        f"<b>{duree_lettres} ({duree_mois}) mois</b> (la "
        f"« <b>Durée</b> »), sauf renouvellement écrit par les "
        f"Parties.",
        s["body"],
    ))
    story.append(Paragraph(
        "<b>8.2</b> Nonobstant la Durée, les obligations de "
        "confidentialité, de non-contournement, de non-sollicitation, "
        "ainsi que les obligations de retour ou destruction des "
        "Informations Confidentielles, survivent à la terminaison de "
        "l'Accord pour la période prévue à chaque article (ou à "
        "défaut, pour vingt-quatre (24) mois suivant la terminaison).",
        s["body"],
    ))

    # --- Article 9 ---
    story.append(Paragraph("9. RECOURS ET DOMMAGES", s["section"]))
    story.append(Paragraph(
        "<b>9.1</b> La Partie Réceptrice reconnaît expressément que "
        "toute violation du présent Accord, et en particulier des "
        "articles 3 (Engagements), 4 (Non-contournement et "
        "non-sollicitation), et 6 (Propriété), causerait à la "
        "Société un préjudice grave, imprévisible et potentiellement "
        "irréparable, ne pouvant être adéquatement compensé par des "
        "dommages-intérêts seuls.",
        s["body"],
    ))
    story.append(Paragraph(
        "<b>9.2</b> En cas de violation du présent Accord par la "
        "Partie Réceptrice ou ses Représentants, la Société pourra "
        "obtenir, sans préjudice de ses autres recours et de "
        "manière cumulative :",
        s["body"],
    ))
    for letter, text in [
        ("a", "Une injonction (provisoire, interlocutoire ou "
              "permanente), une ordonnance d'exécution en nature ou "
              "toute autre mesure équivalente, sans avoir à fournir "
              "de cautionnement, afin de faire cesser immédiatement "
              "la violation;"),
        ("b", f"<b>Des dommages-intérêts forfaitaires d'un montant "
              f"minimum de DEUX CENT MILLE DOLLARS "
              f"({damages_amount}&nbsp;$ CAD) par violation</b>, "
              f"payables immédiatement à la Société sur preuve de "
              f"la violation, à titre de plancher pour le préjudice "
              f"subi par la Société (les Parties reconnaissent que "
              f"ce montant constitue une estimation raisonnable et "
              f"anticipée du préjudice minimum subi);"),
        ("c", "Des dommages-intérêts additionnels correspondant au "
              "préjudice réel subi par la Société au-delà du "
              "forfait prévu en (b), incluant notamment toute perte "
              "de profit, perte d'opportunité, perte de commission "
              "ou frais de gestion que la Société aurait perçus si "
              "la transaction avait été conclue avec sa "
              "participation;"),
        ("d", "Le remboursement intégral de tous les frais et "
              "honoraires (juridiques, judiciaires, "
              "extrajudiciaires, expertises, et autres) engagés par "
              "la Société pour faire valoir ses droits aux termes "
              "du présent Accord."),
    ]:
        story.append(Paragraph(f"({letter}) {text}", s["body_l1"]))

    story.append(Paragraph(
        "<b>9.3</b> La Partie Réceptrice indemnisera la Société et "
        "la mettra à couvert, à compter de la Date d'effet, de "
        "toutes réclamations, demandes, actions, causes d'action, "
        "dommages-intérêts directs ou indirects, pertes, frais, "
        "responsabilités ou dépenses que la Société peut engager ou "
        "subir, ou qui peuvent être intentés contre elle, si la "
        "Partie Réceptrice ou ses Représentants violent une "
        "modalité ou condition du présent Accord.",
        s["body"],
    ))

    # --- Article 10 ---
    story.append(Paragraph("10. DIVULGATION OBLIGATOIRE", s["section"]))
    story.append(Paragraph(
        "Si la Partie Réceptrice est légalement tenue (par loi, "
        "ordonnance judiciaire, ou autorité réglementaire) de "
        "divulguer des Informations Confidentielles, elle devra :",
        s["body"],
    ))
    for letter, text in [
        ("a", "Aviser immédiatement et par écrit la Partie "
              "Divulgatrice avant toute divulgation, dans la mesure "
              "permise par la loi;"),
        ("b", "Coopérer avec la Partie Divulgatrice pour permettre "
              "à celle-ci de demander une ordonnance de protection "
              "ou tout autre recours approprié;"),
        ("c", "Ne divulguer que la portion strictement requise par "
              "la loi."),
    ]:
        story.append(Paragraph(f"({letter}) {text}", s["body_l1"]))

    # --- Article 11 ---
    story.append(Paragraph("11. DISPOSITIONS GÉNÉRALES", s["section"]))
    for sub, text in [
        ("11.1 Lois applicables et juridiction.",
         f"Le présent Accord est régi et interprété selon les lois "
         f"en vigueur dans la province de Québec et les lois du "
         f"Canada qui y sont applicables. Les Parties se soumettent "
         f"à la juridiction exclusive des tribunaux compétents du "
         f"<b>{NDA_VENUE}</b>, pour toute procédure judiciaire ou "
         f"quasi judiciaire relative au présent Accord."),
        ("11.2 Avis.",
         "Tout avis aux termes du présent Accord sera transmis par "
         "écrit aux coordonnées indiquées sur la première page du "
         "présent Accord, ou par courriel à l'adresse fournie par la "
         "Partie destinataire. Tout avis sera réputé reçu à la date "
         "de la confirmation de livraison ou de lecture."),
        ("11.3 Modification.",
         "Aucune modification du présent Accord ne sera valable à "
         "moins qu'elle ne soit constatée par un écrit signé par les "
         "deux Parties."),
        ("11.4 Renonciation.",
         "Le fait pour une Partie de ne pas exercer un droit, "
         "pouvoir ou privilège aux termes du présent Accord ne "
         "constitue pas une renonciation à ce droit, et l'exercice "
         "ponctuel ou partiel d'un tel droit ne constitue pas une "
         "renonciation à un exercice ultérieur."),
        ("11.5 Cession.",
         "Aucune Partie ne peut céder ses droits ou obligations aux "
         "termes du présent Accord sans le consentement écrit "
         "préalable de l'autre Partie."),
        ("11.6 Intégralité de l'accord.",
         "Le présent Accord constitue l'intégralité de l'entente "
         "entre les Parties à l'égard de son objet, et remplace "
         "toute communication, négociation, déclaration, promesse ou "
         "entente antérieure, verbale ou écrite."),
        ("11.7 Successeurs.",
         "Le présent Accord lie les Parties ainsi que leurs "
         "successeurs, ayants droit, héritiers et représentants "
         "légaux respectifs."),
        ("11.8 Exemplaires et signature électronique.",
         "Le présent Accord peut être signé en plusieurs "
         "exemplaires, chacun constituant un original mais formant "
         "tous ensemble un seul et même document. Le présent Accord "
         "peut être signé électroniquement (via Authentisign, "
         "Docusign, Adobe Sign ou tout autre service de signature "
         "électronique reconnu), et toute signature électronique "
         "aura la même valeur qu'une signature manuscrite "
         "conformément à la Loi concernant le cadre juridique des "
         "technologies de l'information (RLRQ, c. C-1.1)."),
        ("11.9 Divisibilité.",
         "Si une disposition du présent Accord est jugée invalide, "
         "nulle ou inexécutoire, les autres dispositions demeurent "
         "en vigueur et pleinement exécutoires."),
        ("11.10 Langue.",
         "Les Parties confirment avoir expressément demandé que le "
         "présent Accord soit rédigé en langue française."),
        ("11.11 Préambule et titres.",
         "Le préambule fait partie intégrante du présent Accord. "
         "Les titres utilisés dans le présent Accord ne servent "
         "qu'à des fins de référence et n'ont aucune valeur "
         "interprétative."),
    ]:
        story.append(Paragraph(f"<b>{sub}</b> {text}", s["body"]))

    # --- Signatures ---
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<b>EN FOI DE QUOI</b>, les Parties, par l'entremise de "
        "leurs représentants dûment autorisés, ont signé le présent "
        "Accord à la Date d'effet.",
        s["body"],
    ))
    story.append(Spacer(1, 10))

    # Zone réservée à la signature manuscrite MGV : si le fichier
    # `assets/mgv_signature.png` existe, on l'affiche au-dessus du
    # nom. Sinon (ou si l'image plante au chargement / décodage),
    # on laisse un Spacer vide de même hauteur — pas de placeholder
    # texte « [signature] ». Cette robustesse est CRITIQUE : le NDA
    # doit TOUJOURS pouvoir être généré et envoyé même sans l'image.
    #
    # Cause racine du bug `identity=[ImageReader@... broken]` :
    # reportlab ne parse pas correctement les PNG avec canal alpha
    # (RGBA). On pré-convertit donc le PNG en RGB sur disque (pattern
    # similaire au `_LOGO_PATH` qui s'affiche correctement) — voir
    # `_prepare_mgv_signature_rgb_file` pour le rationale détaillé.
    mgv_signature_block: Any
    mgv_signature_block = Spacer(1, 22 * mm)
    sig_path = _prepare_mgv_signature_rgb_file()
    if sig_path is not None:
        try:
            mgv_signature_block = Image(
                sig_path,
                width=70 * mm,
                height=22 * mm,
                kind="proportional",
            )
            log.info(
                "[NDA_PDF] Image signature MGV chargée pour NDA %s "
                "(path=%s)",
                nda.id,
                sig_path,
            )
        except Exception as exc:
            log.warning(
                "[NDA_PDF] Image signature MGV illisible par reportlab "
                "(%s) — fallback Spacer activé. Erreur: %s",
                sig_path,
                exc,
            )
            mgv_signature_block = Spacer(1, 22 * mm)
    else:
        log.warning(
            "[NDA_PDF] Pas de signature MGV pour NDA %s — fallback "
            "Spacer activé (voir logs précédents pour la cause).",
            nda.id,
        )

    sig_left = [
        Paragraph(f"<b>{ISSUER_ENTITY_NAME}</b>", s["small"]),
        Spacer(1, 6),
        mgv_signature_block,
        Spacer(1, 4),
        Paragraph(f"Par : {ISSUER_REPRESENTATIVE_NAME}", s["small"]),
        Paragraph(f"Titre : {ISSUER_REPRESENTATIVE_TITLE}", s["small"]),
        Paragraph(
            f"Date : {emission_date}",
            s["small"],
        ),
        Paragraph(f"Adresse : {ISSUER_ENTITY_ADDRESS}", s["small"]),
        Paragraph(f"Courriel : {ISSUER_EMAIL}", s["small"]),
        Paragraph(f"Téléphone : {ISSUER_PHONE}", s["small"]),
    ]

    # Le bloc Récepteur est rempli automatiquement dès que le NDA est
    # signé via la page publique (signed_name + signed_at posés par
    # le endpoint POST /public/ndas/{token}/sign). `force_signed_block`
    # permet à `generate_signed_nda_pdf` de forcer le remplissage
    # dans le même flush DB que la signature.
    is_signed = force_signed_block or bool(
        nda.signed_at and nda.signed_name
    )
    signed_at_label = (
        _date_fr_ca_long(nda.signed_at) if nda.signed_at else "_____________________"
    )
    signed_name_label = (
        nda.signed_name if nda.signed_name else "_____________________"
    )
    email_label = (
        nda.investor_email
        if is_signed and nda.investor_email
        else "_____________________"
    )
    if is_signed:
        # Mention italique stylisée pour distinguer visuellement la
        # signature électronique d'une signature manuscrite.
        signature_label = (
            "<i>&#10004; Signée électroniquement</i>"
        )
    else:
        signature_label = "_____________________"
    sig_right = [
        Paragraph("<b>LE RÉCEPTEUR</b>", s["small"]),
        Spacer(1, 6),
        Paragraph(f"Nom : {signed_name_label}", s["small"]),
        Paragraph(f"Adresse courriel : {email_label}", s["small"]),
        Paragraph(f"Date : {signed_at_label}", s["small"]),
        Paragraph(f"Signature : {signature_label}", s["small"]),
    ]

    sig_table = Table(
        [[sig_left, sig_right]],
        colWidths=["50%", "50%"],
    )
    sig_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.HexColor("#999999")),
            ("TOPPADDING", (0, 0), (-1, 0), 10),
        ])
    )
    story.append(sig_table)

    # --- Mentions légales en pied ---
    story.append(Spacer(1, 12))
    story.append(Paragraph(LEGAL_NOTICE, s["legal"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Document généré par le portail Horizon le "
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}.",
        s["legal"],
    ))

    # `doc.build` peut planter si reportlab échoue sur un Paragraph
    # (XML mal formé suite à un input inattendu) ou sur l'image MGV.
    # On loggue l'exception avec le contexte NDA pour faciliter le
    # debug, puis on remonte une ValueError descriptive — le service
    # `nda_send.py` la convertit en NDASendError, et le endpoint
    # POST /ndas/{id}/send la convertit en HTTP 502 avec message
    # clair (au lieu d'un "Internal Server Error" générique).
    try:
        doc.build(story)
    except Exception as exc:
        log.exception(
            "Rendu PDF NDA %s échoué (deal=%s) : %s",
            nda.id,
            nda.deal_id,
            exc,
        )
        raise ValueError(
            f"Rendu du PDF NDA échoué : {type(exc).__name__}: {exc}"
        ) from exc
    return buf.getvalue()


async def render_nda_pdf(db: AsyncSession, nda_id: int) -> bytes:
    nda, deal = await _load(db, nda_id)
    if nda is None:
        raise ValueError(f"NDA {nda_id} introuvable")
    return _render_bytes(nda, deal)


def _render_signed_bytes(
    nda: NDA, deal: Optional[ProspectionDeal]
) -> bytes:
    """Variante post-signature : bloc Récepteur rempli + bandeau
    emerald-600 en haut de la première page (« SIGNÉE ÉLECTRONIQUE-
    MENT — {nom} le {date} à {HH:MM} UTC depuis IP {ip} ») + hash
    SHA-256 du document de base ajouté en pied du bandeau pour
    intégrité.

    Pattern repris de `devlog_soumission_pdf._render_signed_bytes` :
    on génère d'abord le PDF de base avec `force_signed_block=True`,
    puis on overlay un bandeau via reportlab.canvas + pypdf.
    """
    import hashlib

    base_pdf = _render_bytes(nda, deal, force_signed_block=True)
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore
        from reportlab.pdfgen import canvas  # type: ignore
    except Exception:
        log.warning(
            "[NDA_PDF] pypdf indisponible — PDF signé sans bandeau "
            "overlay (NDA %s).",
            nda.id,
        )
        return base_pdf

    rl = _lazy_reportlab()
    mm = rl["mm"]
    colors = rl["colors"]

    signed_at = nda.signed_at
    signed_name = (nda.signed_name or "—").strip() or "—"
    signed_ip = (nda.signed_ip or "—").strip() or "—"
    if signed_at is not None:
        signed_at_long = _date_fr_ca_long(signed_at)
        signed_at_clock = signed_at.strftime("%H:%M UTC")
    else:
        signed_at_long = "—"
        signed_at_clock = "—"

    pdf_hash_short = hashlib.sha256(base_pdf).hexdigest()[:16]

    overlay_buf = io.BytesIO()
    page_w_pt, page_h_pt = rl["A4"]
    c = canvas.Canvas(overlay_buf, pagesize=rl["A4"])
    band_h = 18 * mm
    band_y = page_h_pt - band_h
    c.setFillColor(colors.HexColor("#059669"))  # emerald-600
    c.rect(0, band_y, page_w_pt, band_h, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(
        15 * mm,
        band_y + band_h - 6 * mm,
        "✓ SIGNEE ELECTRONIQUEMENT",
    )
    c.setFont("Helvetica", 8)
    c.drawString(
        15 * mm,
        band_y + band_h - 11 * mm,
        f"{signed_name} le {signed_at_long} a {signed_at_clock} "
        f"depuis IP {signed_ip}",
    )
    c.drawString(
        15 * mm,
        band_y + 3 * mm,
        f"Hash du document (SHA-256, 16 premiers caracteres) : "
        f"{pdf_hash_short}",
    )
    c.save()
    overlay_buf.seek(0)

    try:
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
                        "[NDA_PDF] Overlay bandeau emerald échoué "
                        "(NDA %s, page 0)",
                        nda.id,
                    )
            writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception as exc:
        log.exception(
            "[NDA_PDF] Fusion overlay signé échouée (NDA %s) — "
            "retour au PDF de base avec bloc Récepteur rempli. Erreur: %s",
            nda.id,
            exc,
        )
        return base_pdf


async def generate_signed_nda_pdf(
    db: AsyncSession, nda_id: int
) -> bytes:
    """Rend le PDF *signé* du NDA — appelé au moment de la signature
    publique (POST /public/ndas/{token}/sign).

    Le PDF contient :
    - Bloc Récepteur rempli (nom, courriel, date, « Signée électr. »)
    - Bandeau emerald-600 plein largeur en haut de la 1ère page
      avec horodatage + IP + hash SHA-256 du document de base
    - Tout le reste identique au PDF non-signé

    À stocker dans `NDA.signed_pdf_blob` pour pouvoir le servir tel
    quel via `GET /ndas/{id}/signed-pdf` (audit immuable — pas de
    re-rendu à chaque téléchargement).
    """
    nda, deal = await _load(db, nda_id)
    if nda is None:
        raise ValueError(f"NDA {nda_id} introuvable")
    return _render_signed_bytes(nda, deal)


def signed_nda_pdf_filename(nda: NDA) -> str:
    """Nom de fichier canonique du PDF *signé* d'un NDA.

    Format : `Entente_Confidentialite_MGV_{Nom_Investisseur}_SIGNEE.pdf`.
    """
    slug = _slugify_investor(nda.investor_name)
    suffix = slug if slug else str(nda.id)
    return f"Entente_Confidentialite_MGV_{suffix}_SIGNEE.pdf"


def _slugify_investor(name: Optional[str]) -> str:
    """Convertit un nom d'investisseur en slug ASCII pour nom de fichier.

    Ex: "Jean-Pierre Tremblay-Côté" -> "Jean_Pierre_Tremblay_Cote".
    Retire les accents (NFKD + drop des combining marks), remplace
    les espaces/tirets/apostrophes par `_`, supprime tout caractère
    non alphanumérique restant, compresse les `_` consécutifs.
    """
    if not name or not name.strip():
        return ""
    # Décomposer les caractères accentués puis retirer les marques.
    decomposed = unicodedata.normalize("NFKD", name.strip())
    ascii_only = "".join(
        ch for ch in decomposed if not unicodedata.combining(ch)
    )
    # Remplacer espaces, tirets, apostrophes par `_`.
    underscored = re.sub(r"[\s\-'’]+", "_", ascii_only)
    # Supprimer tout caractère non `[A-Za-z0-9_]`.
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", underscored)
    # Compresser les `_` consécutifs et trim.
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned


def nda_pdf_filename(nda: NDA) -> str:
    """Nom de fichier canonique du PDF d'un NDA.

    Format : `Entente_Confidentialite_MGV_{Nom_Investisseur}.pdf`.
    Si l'investor_name est absent (cas brouillon), fallback sur l'id
    interne : `Entente_Confidentialite_MGV_{id}.pdf`.
    """
    slug = _slugify_investor(nda.investor_name)
    suffix = slug if slug else str(nda.id)
    return f"Entente_Confidentialite_MGV_{suffix}.pdf"
