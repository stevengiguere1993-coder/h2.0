"""Dédoublonnage des unités de l'île de Montréal (Phil 2026-09-28 : « il y
en aurait donc 24 029 dans ma base de données des 8 et plus ? »).

Deux imports décrivent les mêmes bâtiments avec deux formats de
matricule :

* rôle provincial MAMH : ``66023-9939-11-8086-8`` (code de municipalité
  + matricule), ou ``66023-9939-11-8086-8-001-0002`` avec suffixes ;
* fichier de la Ville de Montréal : ``9939-11-8086-8-000-0000`` (toujours
  7 groupes, ``region = 'mtl-island'``).

Le fichier de la Ville est LA source pour l'île (plus frais, noms de
municipalité justes). Une ligne provinciale de l'agglomération (code
``66xxx``) dont la clé — le matricule sans le code de municipalité —
correspond à une ligne Ville est une « jumelle » : on reporte sur la
ligne Ville ce que la jumelle aurait de plus (propriétaires collectés,
arrondissement), on rattache les leads qui pointaient sur elle, puis on
la supprime. Les lignes provinciales SANS jumelle sont laissées.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.montreal_property_unit import MontrealPropertyUnit as U
from app.models.prospection_lead import ProspectionLead as L

log = logging.getLogger(__name__)

_V = aliased(U, name="v")


def _cle_courte(col):
    """``66023-9939-11-8086-8`` → ``9939-11-8086-8``."""
    return func.substr(col, 7)


def _cle_longue(col):
    """``66023-9939-11-8086-8`` → ``9939-11-8086-8-000-0000``."""
    return func.substr(col, 7) + "-000-0000"


def _est_provinciale_agglo(col, region_col=None):
    """Ligne du rôle provincial pour une municipalité de l'agglomération
    de Montréal (codes MAMH ``66xxx``)."""
    conds = [func.substr(col, 1, 2) == "66", func.substr(col, 6, 1) == "-"]
    if region_col is not None:
        conds.append(func.coalesce(region_col, "") != "mtl-island")
    return and_(*conds)


def _a_une_jumelle_ville(col):
    """EXISTS une ligne Ville dont le matricule est la clé courte ou longue
    (deux EXISTS séparés : chacun s'appuie sur l'index de la clé primaire)."""
    return or_(
        exists().where(and_(_V.region == "mtl-island", _V.matricule == _cle_courte(col))),
        exists().where(and_(_V.region == "mtl-island", _V.matricule == _cle_longue(col))),
    )


def _a_des_proprietaires(col):
    return and_(col.is_not(None), col.notin_(["", "[]"]))


async def compter_jumelles(db: AsyncSession) -> Dict[str, Any]:
    """Analyse sans rien modifier."""
    prov = _est_provinciale_agglo(U.matricule, U.region)
    jum = _a_une_jumelle_ville(U.matricule)

    async def _n(*conds) -> int:
        return int(
            (await db.execute(select(func.count()).select_from(U).where(*conds))).scalar_one()
            or 0
        )

    jumelles = await _n(prov, jum)
    jumelles_8_plus = await _n(prov, jum, U.nombre_logement >= 8)
    avec_proprietaires = await _n(prov, jum, _a_des_proprietaires(U.owners_json))
    orphelines = await _n(prov, ~jum)
    leads = int(
        (
            await db.execute(
                select(func.count())
                .select_from(L)
                .where(
                    L.matricule.is_not(None),
                    _est_provinciale_agglo(L.matricule),
                    _a_une_jumelle_ville(L.matricule),
                )
            )
        ).scalar_one()
        or 0
    )
    ville = await _n(U.region == "mtl-island")
    ville_8_plus = await _n(U.region == "mtl-island", U.nombre_logement >= 8)
    return {
        "jumelles": jumelles,
        "jumelles_8_plus": jumelles_8_plus,
        "avec_proprietaires": avec_proprietaires,
        "leads_a_rattacher": leads,
        "provinciales_sans_jumelle": orphelines,
        "ville_total": ville,
        "ville_8_plus": ville_8_plus,
    }


async def _ligne_ville(db: AsyncSession, matricule_prov: str) -> Optional[U]:
    court = matricule_prov[6:]
    return (
        (
            await db.execute(
                select(U).where(
                    U.region == "mtl-island",
                    U.matricule.in_([court, court + "-000-0000"]),
                )
            )
        )
        .scalars()
        .first()
    )


async def fusionner_jumelles(db: AsyncSession) -> Dict[str, Any]:
    """Reporte propriétaires/arrondissement, rattache les leads, supprime
    les jumelles provinciales. Commit par l'appelant."""
    avant = await compter_jumelles(db)
    prov = _est_provinciale_agglo(U.matricule, U.region)
    jum = _a_une_jumelle_ville(U.matricule)

    # 1. Ce que la jumelle a de plus → ligne Ville (rare : quelques lignes).
    proprietaires_reportes = 0
    arrondissements_reportes = 0
    a_reporter = (
        await db.execute(
            select(U.matricule, U.owners_json, U.owners_fetched_at, U.arrondissement).where(
                prov,
                jum,
                or_(_a_des_proprietaires(U.owners_json), U.arrondissement.is_not(None)),
            )
        )
    ).all()
    for mat, owners_json, fetched_at, arrondissement in a_reporter:
        ville = await _ligne_ville(db, mat)
        if ville is None:
            continue
        if owners_json and owners_json not in ("", "[]") and not (
            ville.owners_json and ville.owners_json not in ("", "[]")
        ):
            ville.owners_json = owners_json
            ville.owners_fetched_at = fetched_at
            proprietaires_reportes += 1
        if arrondissement and not ville.arrondissement:
            ville.arrondissement = arrondissement
            arrondissements_reportes += 1
    await db.flush()

    # 2. Leads qui pointaient sur une jumelle → matricule Ville.
    leads_rattaches = 0
    leads = (
        (
            await db.execute(
                select(L).where(
                    L.matricule.is_not(None),
                    _est_provinciale_agglo(L.matricule),
                    _a_une_jumelle_ville(L.matricule),
                )
            )
        )
        .scalars()
        .all()
    )
    for lead in leads:
        ville = await _ligne_ville(db, lead.matricule or "")
        if ville is not None:
            lead.matricule = ville.matricule
            leads_rattaches += 1
    await db.flush()

    # 3. Suppression des jumelles (une seule instruction, ensembliste).
    res = await db.execute(delete(U).where(prov, jum))
    supprimees = int(res.rowcount or 0) if res.rowcount is not None and res.rowcount >= 0 else avant["jumelles"]
    await db.flush()
    log.info(
        "Dédoublonnage île de Montréal : %d jumelles supprimées, %d propriétaires reportés, %d leads rattachés",
        supprimees, proprietaires_reportes, leads_rattaches,
    )
    return {
        **avant,
        "supprimees": supprimees,
        "proprietaires_reportes": proprietaires_reportes,
        "arrondissements_reportes": arrondissements_reportes,
        "leads_rattaches": leads_rattaches,
    }
