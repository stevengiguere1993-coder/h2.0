"""Client MÈRE QuickBooks d'une fiche client Kratos.

Une seule règle pour tous les chemins qui rattachent un projet à son
client dans QuickBooks (sous-client du projet, factures, coûts, heures) :
le client QB doit PORTER LE NOM de la fiche (aux accents, majuscules et
ponctuation près).

1. le lien mémorisé sur la fiche (``Client.qbo_customer_id``) s'il est
   actif et porte ce nom ;
2. sinon le client QB à ce nom (``ensure_customer`` : nom exact, puis
   courriel unique, puis création) ;
3. un client QB retrouvé par le lien ou le courriel mais qui porte un
   AUTRE nom n'est gardé que si ce nom est celui d'une personne (fiche
   renommée : « Tremblay Jean » → « Jean Tremblay ») et d'aucune autre
   fiche Kratos. Un nom de compagnie différent est celui d'une autre
   compagnie (même propriétaire, même courriel) : jamais repris ;
4. à défaut : le client QB à ce nom, même INACTIF (réactivé), sinon il
   est créé.

Pourquoi (Steven 2026-11-02) : le projet 1660 Saint-Clément est passé de
« MGV Développement inc. » à « Groupe 1660 Saint-Clément inc. » dans
Kratos. La fiche du Groupe était reliée au client QB #179, qui n'est pas
« Groupe 1660 Saint-Clément inc. » (introuvable dans la liste des clients
QB) : les compagnies de Philippe Meuser partagent son courriel, et le
repli par courriel avait relié la fiche à une autre de ses compagnies.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client

log = logging.getLogger(__name__)

#: Mots qui font d'un nom celui d'une compagnie (forme normalisée).
_MARQUES_COMPAGNIE = {
    "inc", "ltee", "ltd", "limitee", "limited", "senc", "senrl", "enr",
    "corp", "corporation", "cie", "groupe", "group", "gestion", "immobilier",
    "immobiliere", "immobilieres", "holding", "holdings", "fiducie",
    "construction", "constructions", "developpement", "developpements",
    "investissement", "investissements", "societe", "entreprise",
    "entreprises", "llc", "co", "services", "syndicat", "copropriete",
}


def nom_norm(value: Optional[str]) -> str:
    """Nom comparable : minuscules, sans accents, ponctuation réduite à un
    espace (« Saint-Clément inc. » ≡ « saint clement inc »)."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.lower()).split())


def _meme_nom(a: Optional[str], b: Optional[str]) -> bool:
    return nom_norm(a) == nom_norm(b)


def est_compagnie(nom: Optional[str]) -> bool:
    mots = nom_norm(nom).split()
    return any(m in _MARQUES_COMPAGNIE for m in mots) or any(
        m.isdigit() and len(m) >= 4 for m in mots
    )


def _actif(row: Optional[Dict[str, Any]]) -> bool:
    return bool(row) and row.get("Active") is not False


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


async def _garde_autre_nom(
    db: AsyncSession, client: Client, row: Optional[Dict[str, Any]], *, origine: str
) -> bool:
    """Un client QB au nom DIFFÉRENT de la fiche (retrouvé par le lien ou
    le courriel) n'est gardé que s'il porte un nom de personne qui n'est
    celui d'aucune autre fiche Kratos."""
    if not row:
        return False
    if _meme_nom(row.get("DisplayName"), client.name):
        return True
    if est_compagnie(row.get("DisplayName")) or await appartient_a_une_autre_fiche(
        db, client, row, par_lien=(origine == "courriel")
    ):
        log.warning(
            "Client %s « %s » : le client QB %s « %s » (%s) porte un autre nom "
            "de compagnie — ignoré.",
            client.id, client.name, row.get("Id"), row.get("DisplayName"), origine,
        )
        return False
    return True


async def _lien_de_la_fiche(
    db: AsyncSession, qbo: Any, client: Client
) -> Optional[Dict[str, Any]]:
    """Règle 1 : le client QB relié à la fiche, s'il tient encore."""
    if not client.qbo_customer_id:
        return None
    cust = await qbo.get_customer(client.qbo_customer_id)
    if not _actif(cust):
        return None
    if _meme_nom(cust.get("DisplayName"), client.name):
        return cust
    exact = await qbo.find_customer_by_name(client.name) if client.name else None
    if _actif(exact):
        return exact
    if await _garde_autre_nom(db, client, cust, origine="lien de la fiche"):
        return cust
    return None


async def _par_nom_meme_inactif(qbo: Any, client: Client) -> Optional[Dict[str, Any]]:
    """Client QB de premier niveau au nom de la fiche (accents près), actif
    de préférence, sinon INACTIF (réactivé)."""
    voulu = nom_norm(client.name)
    if not voulu:
        return None
    try:
        rows: List[Dict[str, Any]] = await qbo.all_customers_any()
    except Exception as exc:  # noqa: BLE001
        log.warning("Liste des clients QB (inactifs compris) : %s", exc)
        return None
    trouves = [
        r for r in rows
        if not (r.get("ParentRef") or {}).get("value")
        and nom_norm(r.get("DisplayName")) == voulu
    ]
    if not trouves:
        return None
    trouves.sort(key=lambda r: (not _actif(r), int(r["Id"]) if str(r.get("Id", "")).isdigit() else 0))
    row = trouves[0]
    if not _actif(row):
        log.warning(
            "Client %s « %s » : client QB %s inactif à ce nom — réactivé.",
            client.id, client.name, row.get("Id"),
        )
        row = await qbo.set_customer_active(str(row["Id"]), True) or row
    return row


def _nom_deja_pris(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "6240" in msg or "duplicate" in msg or "already" in msg or "existe" in msg


async def trouver_client_mere_qbo(
    db: AsyncSession, qbo: Any, client: Client
) -> Optional[Dict[str, Any]]:
    """Client QB de la fiche, SANS rien créer (inactif au nom exact :
    réactivé)."""
    cust = await _lien_de_la_fiche(db, qbo, client)
    if cust is None and client.name:
        cust = await qbo.find_customer_by_name(client.name)
    if cust is None and client.email:
        par_courriel = await qbo.find_customer_by_email(client.email)
        if await _garde_autre_nom(db, client, par_courriel, origine="courriel"):
            cust = par_courriel
    if cust is None:
        cust = await _par_nom_meme_inactif(qbo, client)
    return cust


async def client_mere_qbo(
    db: AsyncSession, qbo: Any, client: Client, *, memoriser: bool = False
) -> Dict[str, Any]:
    """Client QB de la fiche (créé au besoin). ``memoriser`` : le lien est
    écrit sur la fiche (synchro du sous-client de projet, synchro de
    masse) ; les envois de factures / coûts ne font que le lire. Ne commit
    pas."""
    from app.integrations.quickbooks import QuickBooksError

    cust = await _lien_de_la_fiche(db, qbo, client)
    if cust is None:
        # Nom exact, courriel unique, sinon création (ensure_customer)…
        try:
            cust = await qbo.ensure_customer(
                display_name=client.name,
                email=client.email,
                phone=client.phone,
                billing_address=client.address,
            )
        except QuickBooksError as exc:
            # Nom déjà pris : un client INACTIF porte ce nom.
            if not _nom_deja_pris(exc):
                raise
            cust = None
        # … mais jamais une autre compagnie retrouvée par le courriel.
        if cust and not await _garde_autre_nom(db, client, cust, origine="courriel"):
            cust = None
    if cust is None:
        cust = await _par_nom_meme_inactif(qbo, client)
    if cust is None:
        cust = await qbo.create_customer(
            display_name=client.name,
            email=client.email,
            phone=client.phone,
            billing_address=client.address,
        )
        log.warning(
            "Client %s « %s » : client QB créé (%s).",
            client.id, client.name, (cust or {}).get("Id"),
        )
    cid = str((cust or {}).get("Id") or "")
    if memoriser and cid and client.qbo_customer_id != cid:
        log.warning(
            "Client %s « %s » : lien QB %s → %s.",
            client.id, client.name, client.qbo_customer_id, cid,
        )
        client.qbo_customer_id = cid
        await db.flush()
    return cust
