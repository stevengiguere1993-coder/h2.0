"""Lancer une tâche de fond APRÈS l'enregistrement (commit) de la requête.

Le problème (2026-11-13, deux tests de la CI échouaient au hasard avec « Auto-push
QBO achat N a échoué (silencieux): Achat N introuvable ») : un endpoint lançait
``asyncio.create_task(autopush_achat(id))`` — ou une ``BackgroundTask`` — AVANT que
la session de la requête soit validée. Or ``get_db`` ne valide qu'à la toute fin de
la requête, après l'envoi de la réponse et après les ``BackgroundTasks``. La tâche,
qui ouvre sa propre session, lisait donc parfois la base avant le commit : objet
« introuvable » à la création, anciennes valeurs à la modification. Elle abandonnait
en silence et le travail attendait le filet horaire.

``lancer_apres_commit(db, fabrique)`` retient la tâche et ne la lance qu'une fois la
transaction de ``db`` réellement validée :

- commit de la transaction → la tâche part, dans l'ordre des demandes ;
- rollback, ou session fermée sans commit → la tâche ne part jamais (rien n'a été
  enregistré, il n'y a rien à envoyer) ;
- libération d'un SAVEPOINT (``begin_nested``) → on attend encore : les données ne
  sont visibles des autres sessions qu'au commit de la transaction englobante ;
- aucune transaction en cours (tout est déjà validé) → la tâche part tout de suite.

``fabrique`` est une fonction SANS argument qui retourne la coroutine à exécuter
(``lambda: autopush_achat(achat_id)``) : la coroutine n'est créée qu'au lancement,
donc jamais « jamais attendue » si la transaction est annulée.

Les tâches lancées sont référencées tant qu'elles tournent : asyncio ne garde
qu'une référence faible vers ses tâches, une tâche détachée pouvait être ramassée
avant la fin.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, List, Optional, Set, Union

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

log = logging.getLogger(__name__)

Fabrique = Callable[[], Coroutine[Any, Any, Any]]

#: Clé de ``Session.info`` : les fabriques en attente du commit de cette session.
_CLE = "kratos_apres_commit"
#: Références fortes vers les tâches en vol (retirées quand elles finissent).
_EN_VOL: Set["asyncio.Task[Any]"] = set()


async def _proteger(fabrique: Fabrique) -> None:
    """Une tâche de fond n'a personne pour rattraper son exception : on la journalise."""
    try:
        await fabrique()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("Tâche de fond lancée après commit : erreur non rattrapée")


def lancer_en_fond(fabrique: Fabrique) -> Optional["asyncio.Task[Any]"]:
    """Lance ``fabrique()`` tout de suite en tâche de fond, référencée jusqu'à sa fin.
    Retourne la tâche, ou None s'il n'y a pas de boucle asyncio (rien n'est lancé)."""
    try:
        boucle = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("Tâche de fond non lancée : aucune boucle asyncio en cours")
        return None
    tache = boucle.create_task(_proteger(fabrique))
    _EN_VOL.add(tache)
    tache.add_done_callback(_EN_VOL.discard)
    return tache


def lancer_apres_commit(db: Union[AsyncSession, Session], fabrique: Fabrique) -> None:
    """Lance ``fabrique()`` en tâche de fond dès que la transaction en cours de ``db``
    est validée (voir le module). À appeler à la place de ``asyncio.create_task`` ou
    de ``BackgroundTasks.add_task`` quand la tâche relit, dans sa propre session, ce
    que la requête vient d'écrire."""
    session = db.sync_session if isinstance(db, AsyncSession) else db
    if not session.in_transaction():
        # Rien n'attend d'être validé : la base est à jour, on peut partir.
        lancer_en_fond(fabrique)
        return
    session.info.setdefault(_CLE, []).append(fabrique)


def en_attente(db: Union[AsyncSession, Session]) -> int:
    """Nombre de tâches retenues en attente du commit de ``db`` (diagnostic, tests)."""
    session = db.sync_session if isinstance(db, AsyncSession) else db
    return len(session.info.get(_CLE) or [])


@event.listens_for(Session, "after_commit")
def _apres_commit(session: Session) -> None:
    fabriques: Optional[List[Fabrique]] = session.info.get(_CLE)
    if not fabriques:
        return
    if session.in_nested_transaction():
        # Libération d'un SAVEPOINT : rien n'est encore visible des autres sessions.
        return
    a_lancer = list(fabriques)
    fabriques.clear()
    for fabrique in a_lancer:
        lancer_en_fond(fabrique)


@event.listens_for(Session, "after_transaction_end")
def _fin_de_transaction(session: Session, transaction: SessionTransaction) -> None:
    # Fin de la transaction RACINE sans commit (rollback, fermeture) : ce qui
    # attendait ne partira pas. Après un commit, la liste est déjà vide.
    if transaction.parent is None and not transaction.nested:
        fabriques = session.info.get(_CLE)
        if fabriques:
            fabriques.clear()


__all__ = ["lancer_apres_commit", "lancer_en_fond", "en_attente"]
