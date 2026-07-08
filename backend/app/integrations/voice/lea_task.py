"""Helper : créer une tâche d'entreprise depuis Léa (téléphone / web).

Léa parle à des appelants externes (locataires, prospects, clients).
Quand un appel mérite un suivi par l'équipe (ex. un locataire signale un
problème, ou un intake à recontacter), Léa peut créer une tâche
d'entreprise.

On NE réinvente pas la logique de routage : on réutilise
``kratos_router.route_text`` — déjà utilisé par le Kratos interne — qui
laisse l'IA choisir l'entreprise parmi la liste, crée la tâche, et
retombe sur un routeur local si l'IA est indisponible. Léa fournit juste
un résumé textuel de l'appel.

Ce module est volontairement ISOLÉ : tant qu'il n'est pas appelé depuis
le dispatcher d'appels (voice.py), il n'a aucun effet sur
les appels en direct.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


def _build_task_text(
    *,
    reason: str,
    caller_name: Optional[str] = None,
    caller_phone: Optional[str] = None,
    intent: Optional[str] = None,
) -> str:
    """Compose le texte envoyé au routeur Kratos à partir des éléments
    captés par Léa pendant l'appel. Format proche d'une note d'appel
    pour que l'IA de routage ait du contexte."""
    parts: list[str] = ["[Appel Léa]"]
    if intent:
        parts.append(f"Sujet : {intent}.")
    parts.append(reason.strip())
    who = []
    if caller_name:
        who.append(caller_name.strip())
    if caller_phone:
        who.append(caller_phone.strip())
    if who:
        parts.append(f"Appelant : {' · '.join(who)}.")
    return " ".join(p for p in parts if p)


async def create_task_from_call(
    db: AsyncSession,
    *,
    reason: str,
    caller_name: Optional[str] = None,
    caller_phone: Optional[str] = None,
    intent: Optional[str] = None,
) -> Optional[int]:
    """Crée une tâche d'entreprise à partir d'un appel Léa.

    Réutilise ``kratos_router.route_text`` (IA choisit l'entreprise +
    crée la tâche, fallback local si IA down). ``user=None`` car
    l'appelant est externe — la tâche est attribuée par le routage, pas
    par un utilisateur connecté.

    Retourne l'id du ``KratosMessage`` créé, ou ``None`` si le texte est
    vide / le routage échoue. Ne lève jamais : un échec de création de
    tâche ne doit pas faire planter un appel en cours.
    """
    text = (reason or "").strip()
    if not text:
        return None
    full = _build_task_text(
        reason=text,
        caller_name=caller_name,
        caller_phone=caller_phone,
        intent=intent,
    )
    try:
        from app.services.kratos_router import route_text

        msg = await route_text(db, None, full)
        return int(msg.id) if msg is not None else None
    except Exception as exc:  # noqa: BLE001
        log.warning("Léa create_task_from_call a échoué : %s", exc)
        return None


__all__ = ["create_task_from_call"]
