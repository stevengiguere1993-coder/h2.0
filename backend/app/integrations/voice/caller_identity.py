"""Identification CRM de l'appelant entrant.

À chaque appel entrant, on cherche le `from_e164` dans nos tables CRM :

- **prospection_lead.owner_phone** → lead immobilier déjà repéré
- **contact_request.phone** → demande de soumission Web précédente
- **clients.phone** → client actif (projet en cours)
- **imm_locataires.phone** → locataire d'un de nos immeubles

Le résultat alimente le greeting et le system prompt de la secrétaire
pour qu'elle :
- Accueille la personne par son nom
- Fasse référence au contexte connu (votre cuisine, votre logement…)
- Route vers le bon volet (locataire → support urgence, client → chargé
  de projet, lead → qualification)

Le matching tolère les variations de format (`5146191111`, `(514) 619-1111`,
`+15146191111`) en normalisant à 10 derniers chiffres pour la comparaison.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.contact_request import ContactRequest
from app.models.immobilier import Locataire
from app.models.prospection_lead import ProspectionLead


class CallerKind(str, Enum):
    LEAD_PROSPECTION = "lead_prospection"   # propriétaire repéré
    LEAD_WEB = "lead_web"                   # ancienne demande web
    CLIENT = "client"                        # projet en cours
    LOCATAIRE = "locataire"                  # locataire d'un immeuble
    UNKNOWN = "unknown"


@dataclass
class IdentifiedCaller:
    kind: CallerKind
    entity_id: Optional[int]
    name: Optional[str]
    context: Optional[str]  # Phrase résumant le contexte pour le prompt IA


def _last10(s: str) -> str:
    """Garde les 10 derniers chiffres pour comparaison tolérante."""
    digits = "".join(c for c in (s or "") if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


async def identify_caller(
    db: AsyncSession, from_e164: str
) -> IdentifiedCaller:
    """Cherche dans les 4 tables CRM. Priorité : client > locataire >
    lead prospection > lead web. Premier match gagne.

    On utilise la comparaison `last10` au lieu de l'égalité stricte
    parce que les téléphones en base sont souvent mal formatés
    (`(514) 619-1111`, `514-619-1111`, etc.).
    """
    last10 = _last10(from_e164)
    if not last10:
        return IdentifiedCaller(CallerKind.UNKNOWN, None, None, None)

    # 1. Client actif (projet en cours = priorité max)
    client = await _find_with_phone(db, Client, "phone", last10)
    if client is not None:
        return IdentifiedCaller(
            CallerKind.CLIENT,
            client.id,
            client.name,
            f"Client actuel d'Horizon (projet en cours).",
        )

    # 2. Locataire (urgences possibles)
    loc = await _find_with_phone(db, Locataire, "phone", last10)
    if loc is not None:
        return IdentifiedCaller(
            CallerKind.LOCATAIRE,
            loc.id,
            loc.full_name,
            "Locataire d'un de nos immeubles — pouvant signaler une "
            "urgence (fuite, chauffage, etc.) ou poser une question "
            "administrative.",
        )

    # 3. Lead Prospection (propriétaire repéré, owner_phone)
    pl = await _find_with_phone(db, ProspectionLead, "owner_phone", last10)
    if pl is not None:
        owner_name = getattr(pl, "owner_name", None) or "propriétaire"
        return IdentifiedCaller(
            CallerKind.LEAD_PROSPECTION,
            pl.id,
            owner_name,
            f"Lead Prospection : {owner_name} — propriétaire que nous "
            "avons repéré et démarché auparavant.",
        )

    # 4. Lead Web (ancien ContactRequest)
    cr = await _find_with_phone(db, ContactRequest, "phone", last10)
    if cr is not None:
        return IdentifiedCaller(
            CallerKind.LEAD_WEB,
            cr.id,
            cr.name,
            f"Lead Web : {cr.name} a rempli notre formulaire (sujet : "
            f"{cr.project_type}). Demande initiale : "
            f"{(cr.message or '')[:200]}.",
        )

    return IdentifiedCaller(CallerKind.UNKNOWN, None, None, None)


async def _find_with_phone(
    db: AsyncSession, model, attr: str, last10: str
):
    """Cherche `model` avec la colonne `attr` dont les 10 derniers
    chiffres matchent. Utilise une fonction SQL pour faire la comparaison
    côté DB (évite de charger toute la table en mémoire).

    Best-effort : si la table n'existe pas encore ou si la requête
    plante (colonne typo, etc.), retourne None plutôt que de faire
    crasher tout le flow inbound.
    """
    if not last10:
        return None
    col = getattr(model, attr, None)
    if col is None:
        return None
    try:
        # PostgreSQL : regexp_replace pour ne garder que les chiffres,
        # right(...) pour les 10 derniers. Index-less mais correct sur
        # nos volumes (< 10k lignes par table).
        digits_expr = func.regexp_replace(col, r"[^0-9]", "", "g")
        last10_expr = func.right(digits_expr, 10)
        stmt = select(model).where(last10_expr == last10).limit(1)
        return (await db.execute(stmt)).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "caller_identity lookup failed on %s.%s: %s",
            getattr(model, "__tablename__", "?"), attr, exc,
        )
        return None


# ---------------------------------------------------------------------
# Adaptation du greeting selon le kind
# ---------------------------------------------------------------------


def build_personalized_greeting(caller: IdentifiedCaller) -> str:
    """Greeting que Léa joue après identification — adapté à l'audience."""
    first = (caller.name or "").split(" ")[0] if caller.name else ""

    if caller.kind == CallerKind.CLIENT:
        return (
            f"Bonjour{' ' + first if first else ''}, c'est Léa d'Horizon. "
            "Je vois que vous êtes client chez nous. Comment puis-je vous "
            "aider ?"
        )
    if caller.kind == CallerKind.LOCATAIRE:
        return (
            f"Bonjour{' ' + first if first else ''}, c'est Léa d'Horizon. "
            "S'agit-il d'une urgence concernant votre logement, ou d'une "
            "question administrative ?"
        )
    if caller.kind == CallerKind.LEAD_PROSPECTION:
        return (
            f"Bonjour{' ' + first if first else ''}, c'est Léa d'Horizon. "
            "Que puis-je faire pour vous ?"
        )
    if caller.kind == CallerKind.LEAD_WEB:
        return (
            f"Bonjour{' ' + first if first else ''}, c'est Léa d'Horizon. "
            "Je vois que vous nous aviez écrit pour votre projet. Steven "
            "a-t-il eu la chance de vous rappeler, ou puis-je vous aider ?"
        )
    return (
        "Bonjour, Horizon Services Immobiliers. Comment puis-je vous aider ?"
    )


def build_identity_context_block(caller: IdentifiedCaller) -> str:
    """Bloc à injecter dans le system prompt de la secrétaire."""
    if caller.kind == CallerKind.UNKNOWN or not caller.context:
        return "Appelant inconnu (pas trouvé dans le CRM)."
    return (
        f"APPELANT IDENTIFIÉ ({caller.kind.value}) : "
        f"{caller.name or 'sans nom'}. {caller.context}"
    )
