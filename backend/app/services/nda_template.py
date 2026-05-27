"""Constantes & template pour le flow NDA investisseurs.

Contenu calqué sur le modèle "NDA - MGV Développement - Modèle
générique v2" (11 articles + préambule + bloc signatures). On
garde tout en dur ici : émetteur, durée, juridiction, plancher de
dommages, et boilerplate légal complet. Pas de configuration
exposée — si Phil veut ajuster, on déplacera dans Settings.

Variables substituables :
    - investor_name           (Récepteur)
    - investor_type_clause    (« particulier » | « société par actions… »)
    - investor_address_clause (« résidant au … » | « ayant son siège au … »)
    - investor_representative_clause (vide si particulier)
    - property_address        (optionnel — encart « Opportunité visée »)
    - emission_date           (« Date d'effet »)
    - signed_name             (bloc signature Récepteur)
    - signed_at               (date de signature Récepteur)
"""

from __future__ import annotations

from typing import Optional


# Émetteur du NDA — MGV Développement (Phil & co).
ISSUER_ENTITY_NAME = "MGV DÉVELOPPEMENT INC."
ISSUER_ENTITY_ADDRESS = (
    "216 rue Louis-Lalande, Boucherville (Québec) J4B 2C1"
)
ISSUER_REPRESENTATIVE_NAME = "Philippe Meuser"
ISSUER_REPRESENTATIVE_TITLE = "Président"
ISSUER_EMAIL = "philippe.meuser@immohorizon.com"
ISSUER_PHONE = "438-998-9660"
ISSUER_INCORPORATION_LAW = (
    "Loi sur les sociétés par actions du Québec (RLRQ, c. S-31.1)"
)

# Durée standard de l'engagement de confidentialité, en années.
# Le NDA v2 utilise 24 mois pour la Durée et 24 mois additionnels
# pour la non-sollicitation / non-contournement.
NDA_DURATION_YEARS = 2

# Juridiction affichée dans la carte publique de signature (court).
NDA_JURISDICTION = "Québec"

# Venue exclusive pour les recours judiciaires — § 11.1 du PDF.
NDA_VENUE = "district judiciaire de Longueuil, province de Québec"

# Plancher de dommages-intérêts forfaitaires (§ 9.2 b) en CAD.
NDA_DAMAGES_FLOOR_CAD = 200_000

# Mention sur la valeur juridique de la signature électronique
# (RLRQ c. C-1.1). Conservée pour la page publique de signature.
LEGAL_NOTICE = (
    "La signature électronique a la même valeur juridique qu'une "
    "signature manuscrite en vertu de la Loi concernant le cadre "
    "juridique des technologies de l'information (RLRQ c. C-1.1). "
    "Le destinataire reconnaît avoir lu, compris et accepté les "
    "termes de la présente entente en apposant son nom dans le "
    "formulaire de signature électronique."
)


# Engagements numérotés de l'article 3 du NDA v2 — version courte
# pour l'affichage public de la carte (frontend Next.js). Le PDF
# utilise sa propre numérotation complète (3.1 … 3.6).
ENGAGEMENT_ITEMS: tuple[str, ...] = (
    "Utiliser les Informations Confidentielles exclusivement dans "
    "le cadre de l'évaluation de l'Opportunité, et à aucune autre "
    "fin ;",
    "Préserver la nature confidentielle des Informations "
    "Confidentielles avec au moins le même degré de soin qu'aux "
    "informations propres au Récepteur, et jamais sous le standard "
    "raisonnable ;",
    "Ne pas divulguer les Informations Confidentielles à des tiers "
    "autres que ses Représentants strictement requis et liés par "
    "des obligations de confidentialité au moins aussi strictes ;",
    "Ne pas copier, reproduire, télécharger, photographier ou "
    "conserver les Informations Confidentielles au-delà de ce qui "
    "est strictement nécessaire à l'évaluation ;",
    "Retourner ou détruire immédiatement, sur demande ou à la "
    "terminaison, toutes les Informations Confidentielles (et "
    "celles détenues par ses Représentants), et confirmer cette "
    "destruction par écrit ;",
    "Être pleinement responsable des actes et omissions de ses "
    "Représentants et prendre toutes les mesures nécessaires pour "
    "les empêcher de violer le présent Accord.",
)


# ------------------------------------------------------------------
# Placeholders pour les clauses « particulier vs société »
# ------------------------------------------------------------------
# Quand on ne dispose pas (encore) de l'information précise dans le
# modèle NDA, on injecte des placeholders crochetés que Phil peut
# remplir manuellement avant signature OU qui restent en clair dans
# le PDF pour que l'investisseur les complète à la main.
_INVESTOR_TYPE_PLACEHOLDER = (
    "[particulier OU société par actions légalement constituée en "
    "vertu de [loi applicable]]"
)
_INVESTOR_ADDRESS_PLACEHOLDER = (
    "[résidant OU ayant son siège] au _____________________"
)
_INVESTOR_REPRESENTATIVE_PLACEHOLDER = (
    "[représenté aux fins des présentes par "
    "_____________________, dûment autorisé tel qu'il le déclare "
    "en signant]"
)


def resolve_investor_clauses(
    investor_type_clause: Optional[str] = None,
    investor_address_clause: Optional[str] = None,
    investor_representative_clause: Optional[str] = None,
) -> tuple[str, str, str]:
    """Applique les fallback pour les clauses du Récepteur.

    Si la clause n'est pas fournie, on retombe sur le placeholder
    crocheté correspondant. Une chaîne vide signifie « omis
    volontairement » (utile pour `representative_clause` quand le
    Récepteur est un particulier).
    """

    def _resolve(value: Optional[str], placeholder: str) -> str:
        if value is None:
            return placeholder
        return value.strip()

    return (
        _resolve(investor_type_clause, _INVESTOR_TYPE_PLACEHOLDER),
        _resolve(investor_address_clause, _INVESTOR_ADDRESS_PLACEHOLDER),
        _resolve(
            investor_representative_clause,
            _INVESTOR_REPRESENTATIVE_PLACEHOLDER,
        ),
    )


def render_nda_text(
    investor_name: str,
    emission_date: str,
    property_address: Optional[str] = None,
    signed_name: Optional[str] = None,
    signed_at: Optional[str] = None,
    investor_type_clause: Optional[str] = None,
    investor_address_clause: Optional[str] = None,
    investor_representative_clause: Optional[str] = None,
) -> str:
    """Rend le texte complet de l'entente sous forme de chaîne
    plain-text (utile pour debug / preview rapide hors PDF).

    Les sections sont séparées par des doubles sauts de ligne. Le
    PDF (`nda_pdf.py`) reconstruit son propre rendu typographique —
    cette fonction sert surtout de référence canonique du contenu
    juridique et d'aperçu textuel utilisable dans les tests.
    """
    name = (investor_name or "").strip() or "____________"
    date = (emission_date or "").strip() or "____________"
    sname = (signed_name or "").strip() or "____________"
    sdate = (signed_at or "").strip() or "____________"

    type_cl, addr_cl, repr_cl = resolve_investor_clauses(
        investor_type_clause,
        investor_address_clause,
        investor_representative_clause,
    )

    receiver_block = f"ET {name}, {type_cl}, {addr_cl}"
    if repr_cl:
        receiver_block += f", {repr_cl}"
    receiver_block += " (ci-après le « Récepteur »);"

    opportunity_block = ""
    if property_address and property_address.strip():
        opportunity_block = (
            "OPPORTUNITÉ VISÉE\n"
            f"À titre informatif, l'Opportunité initialement visée "
            f"par les Parties concerne l'immeuble situé au "
            f"{property_address.strip()}. Les présentes obligations "
            f"s'appliquent néanmoins à toute Opportunité partagée "
            f"par MGV au Récepteur.\n\n"
        )

    damages_amount = f"{NDA_DAMAGES_FLOOR_CAD:,}".replace(",", " ")

    return (
        "ENTENTE DE CONFIDENTIALITÉ ET DE NON-CONTOURNEMENT\n\n"
        f"CET ACCORD est conclu en date du {date} (la « Date "
        f"d'effet »), entre :\n\n"
        f"{ISSUER_ENTITY_NAME}, société par actions légalement "
        f"constituée en vertu de la {ISSUER_INCORPORATION_LAW}, "
        f"ayant son siège au {ISSUER_ENTITY_ADDRESS}, représentée "
        f"aux fins des présentes par {ISSUER_REPRESENTATIVE_NAME}, "
        f"{ISSUER_REPRESENTATIVE_TITLE}, dûment autorisé tel qu'il "
        f"le déclare en signant (ci-après la « Société » ou "
        f"« MGV »);\n\n"
        f"{receiver_block}\n\n"
        "Collectivement désignés les « Parties ».\n\n"
        f"{opportunity_block}"
        "PRÉAMBULE\n"
        "ATTENDU QUE la Société est active dans l'investissement "
        "immobilier au Québec, incluant l'identification, l'analyse, "
        "l'acquisition, le développement et la gestion d'immeubles, "
        "ainsi que dans la création et la mise en œuvre de "
        "stratégies value-add;\n\n"
        "ATTENDU QUE la Société souhaite partager au Récepteur "
        "certaines Informations Confidentielles relatives à une ou "
        "plusieurs opportunités d'investissement immobilier (chacune, "
        "l'« Opportunité ») afin que le Récepteur puisse évaluer une "
        "participation potentielle, sous toute forme;\n\n"
        "ATTENDU QUE le Récepteur est susceptible, dans le cadre de "
        "sa propre activité, de partager certaines informations "
        "confidentielles à la Société;\n\n"
        "ATTENDU QUE les Parties souhaitent encadrer les conditions "
        "sous lesquelles ces informations seront divulguées, "
        "utilisées et protégées;\n\n"
        "EN CONTREPARTIE des engagements mutuels contenus aux "
        "présentes, les Parties conviennent de ce qui suit :\n\n"
        "1. OBJET\n"
        "L'objet du présent Accord est de permettre aux Parties de "
        "divulguer, échanger et discuter des Informations "
        "Confidentielles relatives à une ou plusieurs Opportunités "
        "d'investissement immobilier au Québec, afin que le "
        "Récepteur puisse évaluer une éventuelle participation, "
        "sous toute forme.\n\n"
        "2. DÉFINITION DES INFORMATIONS CONFIDENTIELLES\n"
        "Voir le PDF officiel pour la définition complète, les "
        "exclusions (2.2) et la définition de « Représentant » "
        "(2.3).\n\n"
        "3. ENGAGEMENTS DE LA PARTIE RÉCEPTRICE\n"
        + "\n".join(
            f"3.{i + 1} {item}" for i, item in enumerate(ENGAGEMENT_ITEMS)
        )
        + "\n\n"
        "4. NON-CONTOURNEMENT ET NON-SOLLICITATION\n"
        f"Engagement vingt-quatre (24) mois post-terminaison de ne "
        f"pas contourner la Société auprès du vendeur, des "
        f"courtiers, intermédiaires, partenaires, prêteurs ou "
        f"conseillers; ni présenter l'Opportunité à un tiers; ni "
        f"solliciter les locataires ou intervenants. Voir PDF "
        f"officiel pour le détail.\n\n"
        "5. AUCUNE DÉCLARATION NI GARANTIE\n"
        "Les Informations Confidentielles sont fournies « telles "
        "quelles » — aucune garantie d'exactitude.\n\n"
        "6. PROPRIÉTÉ DES INFORMATIONS\n"
        "Tous les droits demeurent la propriété exclusive de la "
        "Partie Divulgatrice.\n\n"
        "7. AUCUNE OBLIGATION DE TRANSACTION\n"
        "Le présent Accord ne crée aucune obligation de transaction.\n\n"
        "8. DURÉE ET RÉSILIATION\n"
        f"Durée de {_years_in_words(NDA_DURATION_YEARS)} "
        f"({NDA_DURATION_YEARS}) ans. Les obligations survivent à "
        f"la terminaison.\n\n"
        "9. RECOURS ET DOMMAGES\n"
        f"Dommages-intérêts forfaitaires d'un montant minimum de "
        f"{damages_amount} $ CAD par violation, sans préjudice des "
        f"autres recours (injonction, dommages additionnels, frais "
        f"juridiques).\n\n"
        "10. DIVULGATION OBLIGATOIRE\n"
        "Si tenu de divulguer par la loi, aviser immédiatement la "
        "Partie Divulgatrice avant divulgation.\n\n"
        "11. DISPOSITIONS GÉNÉRALES\n"
        f"Régi par les lois du Québec. Juridiction exclusive : "
        f"{NDA_VENUE}. Modifications par écrit, signature "
        f"électronique reconnue (RLRQ c. C-1.1), accord intégral, "
        f"rédigé en français.\n\n"
        "EN FOI DE QUOI, les Parties ont signé à la Date d'effet.\n\n"
        f"{ISSUER_ENTITY_NAME}\n"
        f"Par : {ISSUER_REPRESENTATIVE_NAME}\n"
        f"Titre : {ISSUER_REPRESENTATIVE_TITLE}\n"
        f"Date : {date}\n"
        f"Adresse : {ISSUER_ENTITY_ADDRESS}\n"
        f"Courriel : {ISSUER_EMAIL}\n"
        f"Téléphone : {ISSUER_PHONE}\n\n"
        "LE RÉCEPTEUR\n"
        f"Nom : {sname}\n"
        f"Date : {sdate}"
    )


def _years_in_words(n: int) -> str:
    """Retourne le nombre d'années en lettres pour le boilerplate.

    Couvre les valeurs probables (1 à 5). Au-delà, on retombe sur
    une représentation chiffrée — la fonction ne sert qu'au confort
    visuel de la phrase « pour une période de deux (2) ans ».
    """
    mapping = {
        1: "un",
        2: "deux",
        3: "trois",
        4: "quatre",
        5: "cinq",
    }
    return mapping.get(n, str(n))


def format_property_address(
    address: Optional[str],
    city: Optional[str] = None,
    postal_code: Optional[str] = None,
) -> str:
    """Helper de concaténation : adresse, ville, code postal."""
    parts = [p for p in (address, city, postal_code) if p]
    return ", ".join(parts) if parts else "____________"
