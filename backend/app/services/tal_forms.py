"""Génération PDF des documents locatifs (TAL + lettres maison).

Depuis 2026-07-17 (exigence Phil), les 5 avis encadrés par un formulaire
du TAL utilisent **exactement les PDF officiels**, remplis champ par
champ — voir ``tal_officiel.py`` :

- ``avis_modification``      (TAL-806)  ``avis_non_reconduction`` (TAL-807)
- ``avis_travaux_majeurs``   (TAL-808)  ``avis_reprise``          (TAL-809)
- ``reponse_cession``        (TAL-828)

Ce module conserve les 2 LETTRES maison (aucun formulaire TAL n'existe),
générées reportlab, envoyées par courriel SANS signature :

- ``rappel_paiement`` : avis de retard — paiement exigé IMMÉDIATEMENT.
- ``avis_acces`` : accès au logement, préavis 24 h (art. 1931-1933).

Retirés (2026-07-17) : mise_en_demeure (« on n'envoie pas de mise en
demeure au Québec »), sommaire_bail (inutile), trousse_bail (bail = en
pause, licence Publications du Québec ou service externe à venir).

API : ``generate_tal_pdf(form_type, context)`` → ``bytes`` PDF.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# --- Modèle de contexte typé ------------------------------------------------


@dataclass
class TalContext:
    """Contexte commun à tous les formulaires.

    Tous les champs sont optionnels — le générateur affiche « [À compléter] »
    si une valeur est manquante, pour que l'utilisateur voie clairement ce
    qu'il doit corriger sur le PDF avant signature.
    """

    # Locateur (entreprise propriétaire)
    locateur_nom: Optional[str] = None
    locateur_adresse: Optional[str] = None
    locateur_telephone: Optional[str] = None
    locateur_courriel: Optional[str] = None

    # Locataire
    locataire_nom: Optional[str] = None
    locataire_email: Optional[str] = None

    # Logement
    logement_adresse: Optional[str] = None
    logement_numero: Optional[str] = None  # ex. Apt 3
    logement_ville: Optional[str] = None

    # Bail courant
    bail_date_debut: Optional[date] = None
    bail_date_fin: Optional[date] = None
    bail_loyer_mensuel: Optional[float] = None
    bail_chauffage_inclus: bool = False
    bail_eau_chaude_inclus: bool = False
    bail_electricite_inclus: bool = False
    bail_internet_inclus: bool = False

    # Dépôt de garantie (héritage — plus utilisé depuis le retrait de la
    # trousse bail, conservé pour les anciens params sauvegardés)
    depot_garantie: Optional[float] = None

    # Avis de modification TAL-806 : une des 3 formes de hausse
    # (modif_mode 'nouveau_loyer' | 'hausse_montant' | 'hausse_pct',
    # inféré du champ fourni si absent) + renouvellement + autres modifs.
    modif_mode: Optional[str] = None
    nouveau_loyer: Optional[float] = None
    hausse_montant: Optional[float] = None
    hausse_pct: Optional[float] = None
    nouvelle_date_debut: Optional[date] = None
    nouvelle_date_fin: Optional[date] = None
    motif_modification: Optional[str] = None  # « Autre(s) modification(s) »

    # Avis de retard (rappel_paiement) — paiement IMMÉDIAT exigé.
    montant_du: Optional[float] = None
    mois_concerne: Optional[date] = None  # ex. 2025-04 → "avril 2025"

    # Non-reconduction du bail par le locataire (TAL-807)
    depart_date: Optional[date] = None  # défaut : fin du bail

    # Reprise du logement (avis_reprise — TAL-809, art. 1960 CcQ)
    reprise_date: Optional[date] = None  # si bail à durée indéterminée
    reprise_beneficiaire: Optional[str] = None
    reprise_lien: Optional[str] = None  # ex. « moi-même », « mon père »

    # Travaux majeurs (avis_travaux_majeurs — TAL-808, art. 1922-1923)
    travaux_description: Optional[str] = None
    travaux_date_debut: Optional[date] = None
    travaux_duree_valeur: Optional[str] = None  # ex. « 2 »
    travaux_duree_unite: Optional[str] = None  # jours | semaines | mois
    travaux_evacuation: bool = False
    travaux_evacuation_du: Optional[date] = None
    travaux_evacuation_au: Optional[date] = None
    travaux_indemnite: Optional[float] = None  # offerte si évacuation
    travaux_conditions: Optional[str] = None  # autres conditions

    # Accès au logement (avis_acces — art. 1931-1933 CcQ)
    acces_date: Optional[date] = None
    acces_plage: Optional[str] = None  # ex. « entre 9 h et 12 h »
    acces_motif: Optional[str] = None

    # Réponse à un avis de cession de bail (TAL-828, art. 1871/1978.2) :
    # cession_decision 'accepte' | 'refus_serieux' | 'refus_autre'.
    cession_decision: Optional[str] = None
    cession_date: Optional[date] = None  # date de cession de l'avis reçu
    cession_accepte: bool = True  # héritage (anciens params)
    cession_motif_refus: Optional[str] = None

    # Date du document (default = aujourd'hui à la génération)
    date_emission: Optional[date] = None


# --- Helpers de mise en forme ---------------------------------------------


_MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _fmt_date(d: Optional[date]) -> str:
    if d is None:
        return "[À compléter]"
    return f"{d.day} {_MOIS_FR[d.month - 1]} {d.year}"


def _fmt_mois(d: Optional[date]) -> str:
    if d is None:
        return "[À compléter]"
    return f"{_MOIS_FR[d.month - 1]} {d.year}"


def _fmt_money(n: Optional[float]) -> str:
    if n is None:
        return "[À compléter]"
    return f"{n:,.2f} $".replace(",", " ").replace(".", ",")


def _fmt_or(value: Optional[str]) -> str:
    return value if value else "[À compléter]"


def _fmt_adresse_complete(ctx: TalContext) -> str:
    parts: list[str] = []
    if ctx.logement_adresse:
        a = ctx.logement_adresse
        if ctx.logement_numero:
            a = f"{a}, {ctx.logement_numero}"
        parts.append(a)
    if ctx.logement_ville:
        parts.append(ctx.logement_ville)
    return ", ".join(parts) if parts else "[Adresse à compléter]"


def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TalTitle",
            parent=base["Title"],
            fontSize=15,
            leading=18,
            alignment=TA_CENTER,
            spaceAfter=14,
            textColor=colors.HexColor("#0a0a0b"),
        ),
        "h2": ParagraphStyle(
            "TalH2",
            parent=base["Heading2"],
            fontSize=11,
            leading=14,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor("#0a0a0b"),
        ),
        "body": ParagraphStyle(
            "TalBody",
            parent=base["BodyText"],
            fontSize=10.5,
            leading=15,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
        ),
        "right": ParagraphStyle(
            "TalRight",
            parent=base["BodyText"],
            fontSize=10.5,
            leading=15,
            alignment=TA_RIGHT,
        ),
        "small": ParagraphStyle(
            "TalSmall",
            parent=base["BodyText"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#555555"),
        ),
    }


def _header_block(ctx: TalContext, styles: dict) -> list:
    """En-tête commun : locateur en haut-gauche, date en haut-droite."""
    today = ctx.date_emission or date.today()
    locateur_lines = [
        _fmt_or(ctx.locateur_nom),
        _fmt_or(ctx.locateur_adresse),
    ]
    if ctx.locateur_telephone:
        locateur_lines.append(f"Tél. {ctx.locateur_telephone}")
    if ctx.locateur_courriel:
        locateur_lines.append(ctx.locateur_courriel)
    left = "<br/>".join(locateur_lines)
    right = _fmt_date(today)
    table = Table(
        [
            [
                Paragraph(left, styles["small"]),
                Paragraph(right, styles["right"]),
            ]
        ],
        colWidths=[10 * cm, 7 * cm],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return [table, Spacer(1, 0.5 * cm)]


def _destinataire(ctx: TalContext, styles: dict) -> list:
    nom = _fmt_or(ctx.locataire_nom)
    addr = _fmt_adresse_complete(ctx)
    body = (
        f"<b>Destinataire :</b><br/>{nom}<br/>{addr}"
    )
    return [Paragraph(body, styles["body"]), Spacer(1, 0.3 * cm)]


def _signature_block(ctx: TalContext, styles: dict) -> list:
    """Bloc de clôture des lettres SANS signature en ligne : nom du
    locateur en toutes lettres (la lettre part par courriel telle
    quelle, personne n'y appose de signature électronique)."""
    return [
        Spacer(1, 1.2 * cm),
        Paragraph(
            f"{_fmt_or(ctx.locateur_nom)}<br/>Le locateur",
            styles["small"],
        ),
    ]


# --- Lettres maison à GABARIT ÉDITABLE -------------------------------------
# Le texte des 2 lettres (retard, accès) est modifiable depuis Paramètres →
# Modèles de documents (retour Phil 2026-07-20, point 1). L'override vit dans
# automation_settings (clé ``immo.gabarit.<type>``) : {"titre": str,
# "paragraphes": [str, ...]}. Placeholders {variable} remplacés par les
# valeurs du bail ; **gras** → <b>gras</b>.

GABARITS_DEFAUT: dict[str, dict] = {
    "rappel_paiement": {
        # Exigence Phil 2026-07-17 : paiement IMMÉDIAT, pas de délai.
        "titre": "AVIS DE RETARD — LOYER IMPAYÉ",
        "paragraphes": [
            "Selon nos registres, le loyer du mois de **{mois}** pour le "
            "logement situé au **{adresse}**, d'un montant de "
            "**{montant}**, n'a toujours pas été acquitté.",
            "Le loyer est payable le premier jour du mois. **Vous devez "
            "acquitter ce montant IMMÉDIATEMENT.**",
            "À défaut de paiement, nous nous réservons tous les recours "
            "prévus par la loi, y compris une demande au Tribunal "
            "administratif du logement en recouvrement du loyer et, si le "
            "retard dépasse trois semaines, en résiliation du bail "
            "(art. 1971 du Code civil du Québec).",
        ],
    },
    "avis_acces": {
        "titre": "AVIS D'ACCÈS AU LOGEMENT",
        "paragraphes": [
            "Conformément aux articles 1931 et suivants du Code civil du "
            "Québec, je vous avise de mon intention d'accéder au logement "
            "situé au **{adresse}** le **{date}**, {plage}.",
            "Motif : {motif}.",
            "Le présent avis vous est transmis au moins vingt-quatre (24) "
            "heures à l'avance. La visite aura lieu entre 9 h et 21 h (ou "
            "entre 7 h et 19 h s'il s'agit de travaux), conformément aux "
            "articles 1932 et 1933 du Code civil du Québec. Si le moment "
            "proposé vous convient mal, communiquez avec moi pour convenir "
            "d'un autre moment.",
        ],
    },
}

#: Variables disponibles par lettre (affichées dans l'éditeur).
GABARIT_VARIABLES: dict[str, list[str]] = {
    "rappel_paiement": ["mois", "montant", "adresse", "locataire", "locateur"],
    "avis_acces": ["date", "plage", "motif", "adresse", "locataire", "locateur"],
}


def _lettre_variables(form_type: str, ctx: TalContext) -> dict[str, str]:
    communes = {
        "adresse": _fmt_adresse_complete(ctx),
        "locataire": _fmt_or(ctx.locataire_nom),
        "locateur": _fmt_or(ctx.locateur_nom),
    }
    if form_type == "rappel_paiement":
        return {
            **communes,
            "mois": _fmt_mois(ctx.mois_concerne),
            "montant": _fmt_money(ctx.montant_du),
        }
    if form_type == "avis_acces":
        return {
            **communes,
            "date": _fmt_date(ctx.acces_date),
            "plage": ctx.acces_plage or "durant la journée",
            "motif": _fmt_or(ctx.acces_motif),
        }
    return communes


def _rendre_paragraphe(texte: str, variables: dict[str, str]) -> str:
    for k, v in variables.items():
        texte = texte.replace("{" + k + "}", v)
    # **gras** → balise reportlab ; échappement minimal des chevrons.
    texte = texte.replace("<", "&lt;").replace(">", "&gt;")
    import re as _re

    return _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", texte)


def _build_lettre(
    form_type: str,
    ctx: TalContext,
    styles: dict,
    gabarit: Optional[dict] = None,
) -> list:
    defaut = GABARITS_DEFAUT[form_type]
    titre = (gabarit or {}).get("titre") or defaut["titre"]
    paragraphes = (gabarit or {}).get("paragraphes") or defaut["paragraphes"]
    variables = _lettre_variables(form_type, ctx)

    flow: list = []
    flow.extend(_header_block(ctx, styles))
    flow.append(Paragraph(str(titre), styles["title"]))
    flow.extend(_destinataire(ctx, styles))
    for p in paragraphes:
        texte = _rendre_paragraphe(str(p), variables)
        if texte.strip():
            flow.append(Paragraph(texte, styles["body"]))
    flow.extend(_signature_block(ctx, styles))
    return flow


#: Lettres maison (reportlab, gabarit éditable via _build_lettre). Les 5
#: formulaires officiels sont servis par tal_officiel.fill_official_pdf.
_LETTRES = tuple(GABARITS_DEFAUT.keys())


# --- Documents PERSONNALISÉS (règlement d'immeuble, contrat de chambreur…) --
# Retour Steven 2026-07-20 (point 5) : modèles maison créés depuis
# Paramètres → Modèles de documents, générés depuis un bail avec les mêmes
# {variables} que les lettres, envoyables pour signature.

#: Variables disponibles dans les documents personnalisés.
PERSO_VARIABLES: list[str] = [
    "locataire", "locateur", "adresse", "ville", "logement",
    "loyer", "bail_debut", "bail_fin", "date",
]


def _perso_variables(ctx: TalContext) -> dict[str, str]:
    return {
        "locataire": _fmt_or(ctx.locataire_nom),
        "locateur": _fmt_or(ctx.locateur_nom),
        "adresse": _fmt_adresse_complete(ctx),
        "ville": _fmt_or(ctx.logement_ville),
        "logement": _fmt_or(ctx.logement_numero),
        "loyer": _fmt_money(ctx.bail_loyer_mensuel),
        "bail_debut": _fmt_date(ctx.bail_date_debut),
        "bail_fin": _fmt_date(ctx.bail_date_fin),
        "date": _fmt_date(ctx.date_emission or date.today()),
    }


def generate_perso_pdf(
    titre: str, paragraphes: list[str], ctx: TalContext
) -> bytes:
    """Document personnalisé : même mise en page que les lettres maison
    (en-tête locateur/date, destinataire, corps justifié, clôture)."""
    styles = _build_styles()
    variables = _perso_variables(ctx)
    flow: list = []
    flow.extend(_header_block(ctx, styles))
    flow.append(Paragraph(str(titre), styles["title"]))
    flow.extend(_destinataire(ctx, styles))
    for p in paragraphes:
        texte = _rendre_paragraphe(str(p), variables)
        if texte.strip():
            flow.append(Paragraph(texte, styles["body"]))
    flow.extend(_signature_block(ctx, styles))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=str(titre),
        author="h2.0 — Horizon Services Immobiliers",
    )
    doc.build(flow)
    return buf.getvalue()

#: Types dont l'envoi se fait par simple courriel avec PDF joint — AUCUNE
#: signature en ligne (exigence Phil 2026-07-17, points 4 et 7).
#: « releve31 » : copie du Relevé 31 téléversée puis remise au locataire
#: (consultation seule, ouverture horodatée).
#: « personnalise_info » : document personnalisé SANS signature (le modèle
#: décoche « signature requise ») — courriel avec PDF joint + suivi
#: d'ouverture seulement. « personnalise » (avec signature) n'y est pas.
SIGNATURE_NON_REQUISE = {
    "rappel_paiement", "avis_acces", "releve31", "personnalise_info",
}


def available_form_types() -> list[str]:
    from app.services.tal_officiel import OFFICIAL_FORMS

    return [*OFFICIAL_FORMS.keys(), *_LETTRES]


def generate_tal_pdf(
    form_type: str,
    ctx: TalContext,
    template_bytes: Optional[bytes] = None,
    gabarit: Optional[dict] = None,
) -> bytes:
    """Génère le PDF demandé — formulaire OFFICIEL rempli pour les 5
    types TAL, lettre reportlab sinon. Lève KeyError si inconnu.

    ``template_bytes`` : PDF modèle de remplacement (imm_doc_templates)
    pour les formulaires officiels ; ignoré pour les lettres.
    ``gabarit`` : override {titre, paragraphes} pour les lettres
    (automation_settings ``immo.gabarit.<type>``) ; ignoré sinon."""
    from app.services.tal_officiel import fill_official_pdf, is_official

    if is_official(form_type):
        return fill_official_pdf(form_type, ctx, template_bytes)

    if form_type not in GABARITS_DEFAUT:
        raise KeyError(form_type)
    styles = _build_styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=form_type.replace("_", " ").upper(),
        author="h2.0 — Horizon Services Immobiliers",
    )
    flow = _build_lettre(form_type, ctx, styles, gabarit)
    doc.build(flow)
    return buf.getvalue()
