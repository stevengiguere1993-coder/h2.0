"""Constantes & template pour le flow NDA investisseurs.

On garde tout en dur ici : nom de l'émetteur, durée d'engagement,
juridiction, et le boilerplate légal complet. Pas de configuration
exposée — si Phil veut ajuster un jour, on déplacera dans Settings.

Le texte est calqué sur un NDA québécois standard pour partage
d'opportunités d'investissement immobilier : 5 engagements
numérotés, durée 2 ans, juridiction Québec, valeur juridique de la
signature électronique.
"""

from __future__ import annotations

from typing import Optional


# Émetteur du NDA — entité Horizon qui partage l'information.
# Identique à BUYER_ENTITY_NAME dans offer_template.py pour rester
# cohérent visuellement entre les deux documents.
ISSUER_ENTITY_NAME = "Horizon Services Immobiliers inc."
ISSUER_ENTITY_ADDRESS = "Saint-Hubert (Québec)"

# Durée standard de l'engagement de confidentialité, en années.
NDA_DURATION_YEARS = 2

# Juridiction applicable — Québec pour toutes les ententes émises
# par Horizon.
NDA_JURISDICTION = "Québec"

# Mention sur la valeur juridique de la signature électronique
# (RLRQ c. C-1.1).
LEGAL_NOTICE = (
    "La signature électronique a la même valeur juridique qu'une "
    "signature manuscrite en vertu de la Loi concernant le cadre "
    "juridique des technologies de l'information (RLRQ c. C-1.1). "
    "Le destinataire reconnaît avoir lu, compris et accepté les "
    "termes de la présente entente en apposant son nom dans le "
    "formulaire de signature électronique."
)


# Engagements numérotés — texte du dispositif central de l'entente.
ENGAGEMENT_ITEMS: tuple[str, ...] = (
    "Garder strictement confidentielle toute information reçue de "
    "l'Émetteur relative à la Propriété ;",
    "Ne pas divulguer ces informations à des tiers sans le "
    "consentement écrit préalable de l'Émetteur ;",
    "Utiliser ces informations uniquement pour évaluer une "
    "éventuelle participation à l'investissement, et à aucune "
    "autre fin ;",
    "Ne pas approcher directement les propriétaires actuels, les "
    "locataires ou les contreparties sans l'accord de l'Émetteur ;",
    "Détruire ou retourner toute documentation reçue à la demande "
    "de l'Émetteur.",
)


def render_nda_text(
    investor_name: str,
    property_address: str,
    emission_date: str,
) -> str:
    """Rend le texte complet de l'entente sous forme de chaîne plain
    text (utile pour debug / preview rapide hors PDF).

    Les sections sont séparées par des doubles sauts de ligne. Le
    PDF (`nda_pdf.py`) reconstruit son propre rendu typographique —
    cette fonction sert surtout de référence canonique du contenu
    juridique et d'aperçu textuel utilisable dans les tests.
    """
    name = (investor_name or "").strip() or "____________"
    addr = (property_address or "").strip() or "____________"
    date = (emission_date or "").strip() or "____________"

    engagements = "\n".join(
        f"{i + 1}. {item}" for i, item in enumerate(ENGAGEMENT_ITEMS)
    )

    return (
        "ENTENTE DE CONFIDENTIALITÉ\n\n"
        f"Entre : {ISSUER_ENTITY_NAME} (l'« Émetteur »)\n"
        f"Et : {name} (le « Destinataire »)\n\n"
        "OBJET\n"
        "L'Émetteur s'apprête à transmettre au Destinataire des "
        "informations confidentielles concernant la propriété "
        f"située au {addr} (la « Propriété »), notamment des "
        "analyses financières, des données locatives, des "
        "évaluations et des stratégies de mise en valeur.\n\n"
        "ENGAGEMENT\n"
        "Le Destinataire s'engage à :\n"
        f"{engagements}\n\n"
        "DURÉE\n"
        f"La présente entente lie le Destinataire pour une période "
        f"de {_years_in_words(NDA_DURATION_YEARS)} "
        f"({NDA_DURATION_YEARS}) ans à compter de la date de "
        "signature, peu importe que l'investissement ait lieu ou "
        "non.\n\n"
        "JURIDICTION\n"
        f"Les tribunaux du {NDA_JURISDICTION} ont juridiction "
        "exclusive sur tout litige découlant de la présente "
        f"entente. Le droit applicable est celui du "
        f"{NDA_JURISDICTION}.\n\n"
        "SIGNATURE\n"
        f"Émise le {date} par {ISSUER_ENTITY_NAME}."
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
