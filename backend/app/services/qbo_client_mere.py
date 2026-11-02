"""Client MÈRE QuickBooks d'une fiche client Kratos.

Une seule règle pour tous les chemins qui rattachent un projet à son
client dans QuickBooks (sous-client du projet, factures, coûts, heures) :

1. le lien mémorisé sur la fiche (``Client.qbo_customer_id``), sauf s'il
   pointe un client QB au nom différent alors qu'un client au nom exact
   de la fiche existe, ou un client QB qui porte le nom exact d'une AUTRE
   fiche Kratos ;
2. le client QB au nom exact de la fiche ;
3. le client QB au même courriel (unique), sauf s'il porte le nom d'une
   AUTRE fiche Kratos ou y est relié ;
4. sinon, il est créé.

Pourquoi le point « autre fiche » (Steven 2026-11-02) : le projet
1660 Saint-Clément est passé de « MGV Développement inc. » à « Groupe
1660 Saint-Clément inc. » dans Kratos. Les deux compagnies ont le même
propriétaire, donc souvent le même courriel : faute de client QB au nom
du Groupe, le repli par courriel retombait sur MGV Développement, et le
sous-client du projet restait sous MGV au lieu de passer sous le Groupe.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client

log = logging.getLogger(__name__)


def _meme_nom(a: Optional[str], b: Optional[str]) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


async def appartient_a_une_autre_fiche(
    db: AsyncSession,
    client: Client,
    row: Optional[Dict[str, Any]],
    *,
    par_lien: bool = True,
) -> bool:
    """Vrai si le client QB ``row`` porte le nom exact d'une AUTRE fiche
    client Kratos (et pas celui de cette fiche), ou — ``par_lien`` — est
    relié à une autre fiche."""
    if not row:
        return False
    cid = str(row.get("Id") or "")
    nom = (row.get("DisplayName") or "").strip()
    if _meme_nom(nom, client.name):
        return False
    conds = []
    if cid and par_lien:
        conds.append(Client.qbo_customer_id == cid)
    if nom:
        conds.append(func.lower(Client.name) == nom.lower())
    if not conds:
        return False
    try:
        autre = (
            await db.execute(
                select(Client.id)
                .where(Client.id != client.id, or_(*conds))
                .limit(1)
            )
        ).first()
    except Exception:  # noqa: BLE001
        return False
    return autre is not None


async def _lien_de_la_fiche(
    db: AsyncSession, qbo: Any, client: Client
) -> Optional[Dict[str, Any]]:
    """Règle 1 : le client QB relié à la fiche, s'il tient encore."""
    if not client.qbo_customer_id:
        return None
    cust = await qbo.get_customer(client.qbo_customer_id)
    if cust is None or _meme_nom(cust.get("DisplayName"), client.name):
        return cust
    exact = await qbo.find_customer_by_name(client.name) if client.name else None
    if exact is not None:
        return exact
    if await appartient_a_une_autre_fiche(db, client, cust, par_lien=False):
        log.warning(
            "Client %s « %s » : le client QB lié (%s « %s ») est celui d'une "
            "autre fiche Kratos — lien ignoré.",
            client.id, client.name, cust.get("Id"), cust.get("DisplayName"),
        )
        return None
    return cust


async def trouver_client_mere_qbo(
    db: AsyncSession, qbo: Any, client: Client
) -> Optional[Dict[str, Any]]:
    """Client QB de la fiche, SANS rien créer (règles 1 à 3)."""
    cust = await _lien_de_la_fiche(db, qbo, client)
    if cust is None and client.name:
        cust = await qbo.find_customer_by_name(client.name)
    if cust is None and client.email:
        par_courriel = await qbo.find_customer_by_email(client.email)
        if par_courriel is not None and not await appartient_a_une_autre_fiche(
            db, client, par_courriel
        ):
            cust = par_courriel
    return cust


async def client_mere_qbo(
    db: AsyncSession, qbo: Any, client: Client, *, memoriser: bool = False
) -> Dict[str, Any]:
    """Client QB de la fiche (créé au besoin). ``memoriser`` : le lien est
    écrit sur la fiche (synchro du sous-client de projet, synchro de
    masse) ; les envois de factures / coûts ne font que le lire. Ne commit
    pas."""
    cust = await _lien_de_la_fiche(db, qbo, client)
    if cust is None:
        # Nom exact, courriel unique, sinon création (ensure_customer)…
        cust = await qbo.ensure_customer(
            display_name=client.name,
            email=client.email,
            phone=client.phone,
            billing_address=client.address,
        )
        # … mais jamais le client QB d'une AUTRE fiche, retrouvé par un
        # courriel partagé : on crée celui de cette fiche.
        if cust and await appartient_a_une_autre_fiche(db, client, cust):
            log.warning(
                "Client %s « %s » : le courriel mène au client QB d'une autre "
                "fiche (%s « %s ») — client QB créé pour cette fiche.",
                client.id, client.name, cust.get("Id"), cust.get("DisplayName"),
            )
            cust = await qbo.create_customer(
                display_name=client.name,
                email=client.email,
                phone=client.phone,
                billing_address=client.address,
            )
    cid = str((cust or {}).get("Id") or "")
    if memoriser and cid and client.qbo_customer_id != cid:
        client.qbo_customer_id = cid
        await db.flush()
    return cust
