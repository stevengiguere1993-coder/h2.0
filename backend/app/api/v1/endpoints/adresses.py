"""Adresses déjà connues dans Kratos — pour le champ d'adresse partagé.

Steven (2026-11-03) : « Lorsqu'on entre un client via nouveau client dans
projet, l'adresse n'a rien qui apparaît. Il doit y avoir un choix
d'adresse parmi les adresses existantes. »

Une seule route, ``GET /adresses/connues``, qui réunit les adresses déjà
saisies dans la plateforme (immeubles du volet immobilier, projets,
clients) en une liste dédoublonnée. Le champ ``AddressInput`` du portail
la charge au focus et la filtre à mesure qu'on tape ; la saisie d'une
adresse neuve reste possible (Photon / OpenStreetMap par-dessus).

Visibilité : un employé ne voit que les immeubles et projets qui lui sont
affectés (``visible_immeuble_ids`` / ``visible_project_ids``) et aucune
adresse de client (la page Clients est gestionnaire+).
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.permissions import visible_immeuble_ids, visible_project_ids
from app.models.client import Client
from app.models.immobilier import Immeuble
from app.models.project import Project

router = APIRouter(prefix="/adresses", tags=["adresses"])


class AdresseConnue(BaseModel):
    """Une adresse déjà présente dans Kratos."""

    adresse: str
    #: ``immeuble`` | ``projet`` | ``client``
    source: str
    #: Nom de la fiche d'où vient l'adresse (immeuble, projet ou client).
    nom: Optional[str] = None


def cle_adresse(texte: str) -> str:
    """Clé de dédoublonnage : sans accents, minuscules, ponctuation et
    espaces repliés (« 710, Rue Legendre » == « 710 rue legendre »)."""
    sans_accents = "".join(
        c
        for c in unicodedata.normalize("NFKD", texte)
        if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", " ", sans_accents.lower()).strip()


def composer_adresse_immeuble(
    address: str, city: Optional[str], postal_code: Optional[str]
) -> str:
    """« 710 rue Legendre, Montréal, H2M 1S2 » — sans répéter la ville ou
    le code postal s'ils sont déjà dans l'adresse saisie."""
    morceaux = [address.strip()]
    for m in (city, postal_code):
        m = (m or "").strip()
        if m and cle_adresse(m) not in cle_adresse(address):
            morceaux.append(m)
    return ", ".join(morceaux)


def filtrer(adresses: List[AdresseConnue], q: str) -> List[AdresseConnue]:
    """Garde les adresses contenant chaque mot de ``q`` (sans accents)."""
    mots = [m for m in cle_adresse(q).split() if m]
    if not mots:
        return adresses
    return [
        a
        for a in adresses
        if all(m in cle_adresse(f"{a.adresse} {a.nom or ''}") for m in mots)
    ]


@router.get(
    "/connues",
    response_model=List[AdresseConnue],
    summary="Adresses déjà connues dans Kratos (immeubles, projets, clients)",
)
async def adresses_connues(
    db: DBSession,
    user: CurrentUser,
    q: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=1000),
) -> List[AdresseConnue]:
    """Liste dédoublonnée des adresses saisies dans la plateforme, pour
    choisir une adresse existante plutôt que la retaper. ``q`` filtre par
    mots (accents et casse ignorés). Immeubles d'abord, puis projets, puis
    clients ; un employé ne voit que ce qui lui est affecté."""
    vues: set[str] = set()
    out: List[AdresseConnue] = []

    def ajouter(adresse: Optional[str], source: str, nom: Optional[str]) -> None:
        texte = (adresse or "").strip()
        if not texte:
            return
        cle = cle_adresse(texte)
        if not cle or cle in vues:
            return
        vues.add(cle)
        out.append(AdresseConnue(adresse=texte, source=source, nom=nom))

    imm_ids = await visible_immeuble_ids(db, user)
    stmt = (
        select(
            Immeuble.id,
            Immeuble.name,
            Immeuble.address,
            Immeuble.address_secondaire,
            Immeuble.city,
            Immeuble.postal_code,
        )
        .where(Immeuble.is_active.is_(True))
        .order_by(Immeuble.name.asc())
    )
    if imm_ids is not None:
        stmt = stmt.where(Immeuble.id.in_(imm_ids or {0}))
    for _id, nom, address, secondaire, city, postal in (await db.execute(stmt)).all():
        ajouter(composer_adresse_immeuble(address or "", city, postal), "immeuble", nom)
        for extra in (secondaire or "").split("·"):
            if extra.strip():
                ajouter(composer_adresse_immeuble(extra, city, postal), "immeuble", nom)

    proj_ids = await visible_project_ids(db, user)
    stmt = (
        select(Project.id, Project.name, Project.address)
        .where(Project.address.is_not(None))
        .order_by(Project.created_at.desc())
    )
    if proj_ids is not None:
        stmt = stmt.where(Project.id.in_(proj_ids or {0}))
    for _id, nom, address in (await db.execute(stmt)).all():
        ajouter(address, "projet", nom)

    if user.has_min_role("manager"):
        stmt = (
            select(Client.id, Client.name, Client.address)
            .where(Client.address.is_not(None))
            .order_by(Client.name.asc())
        )
        for _id, nom, address in (await db.execute(stmt)).all():
            ajouter(address, "client", nom)

    return filtrer(out, q or "")[:limit]
