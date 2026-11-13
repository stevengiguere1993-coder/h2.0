"""Smoke — relais entre connexions QuickBooks d'une même compagnie
(2026-11-13).

Steven : « Je reçois souvent des demandes de permission pour Intuit
QuickBooks […] s'assurer que les connexions des reçus envoyés vers le
Drive restent activées sauf si un humain le désactive ».

Constat en prod : Horizon Services Immobiliers avait DEUX connexions vers
la même compagnie QuickBooks (realm) — Construction (saine) et « inc:4 »
(reçus → Drive), refusée par Intuit depuis le 2026-10-09 : plus aucune
copie de reçus et un bouton « Reconnecter » permanent.

Couvre :
1. ``choisir_relais`` : une connexion refusée est relayée par une
   connexion saine du même realm (Construction d'abord), jamais par une
   autre compagnie ;
2. un client dont le jeton est refusé renouvelle par la connexion saine
   au lieu d'échouer, et le jeton tourné est écrit sur la ligne SAINE ;
3. une fois marquée, la ligne refusée n'est plus présentée à Intuit ;
4. sans connexion jumelle, l'erreur « à reconnecter » reste ;
5. le cron quotidien rapporte « relais par … » au lieu de « à
   reconnecter ».
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

import app.integrations.quickbooks as qb
from app.models.qbo_connection import QboConnection
from tests.smoke.conftest import TestSessionLocal
from tests.smoke.test_smoke_qbo_jeton_unique_2026_10_09 import (  # noqa: F401
    REALM,
    SCOPE_INC,
    _ligne_construction,
    _ligne_inc,
    intuit,
)


def test_choisir_relais_regles():
    mort = {"realm_id": "R1", "refresh_token": "x", "reconnect_required_at": 1}
    sain = {"realm_id": "R1", "refresh_token": "y", "reconnect_required_at": None}
    autre = {"realm_id": "R2", "refresh_token": "z", "reconnect_required_at": None}
    assert qb.choisir_relais("inc:4", {"inc:4": mort, "construction": sain}) == "construction"
    assert (
        qb.choisir_relais(
            "inc:4", {"inc:4": mort, "inc:9": dict(sain), "construction": dict(sain)}
        )
        == "construction"
    )
    assert qb.choisir_relais("inc:4", {"inc:4": mort, "inc:9": sain}) == "inc:9"
    # Jamais une autre compagnie.
    assert qb.choisir_relais("inc:4", {"inc:4": mort, "construction": autre}) is None
    # Connexion saine : pas de relais.
    assert qb.choisir_relais("construction", {"construction": sain, "inc:4": dict(sain)}) is None
    # Jumelle elle-même refusée : pas de relais.
    assert qb.choisir_relais("inc:4", {"inc:4": mort, "construction": dict(mort)}) is None


def _seed_inc(run, realm: str = REALM) -> None:
    async def seed() -> None:
        async with TestSessionLocal() as s:
            await s.execute(delete(QboConnection).where(QboConnection.scope == SCOPE_INC))
            s.add(
                QboConnection(
                    scope=SCOPE_INC,
                    refresh_token="rt-mort",
                    realm_id=realm,
                    environment="sandbox",
                    company_name="Horizon (reçus)",
                )
            )
            await s.commit()

    run(seed())


def test_jeton_refuse_relaye_par_la_connexion_saine(intuit, run):
    _seed_inc(run)

    async def scenario() -> None:
        cli = qb.get_qbo(SCOPE_INC)
        await cli._load_refresh_from_db()
        await cli.query("select * from Customer")
        # Le jeton mort a été présenté une fois, puis celui de Construction.
        assert intuit.presentes == ["rt-mort", "rt-0"]
        assert intuit.api_auth[-1] == "Bearer at-1"

        # Échéance suivante : la ligne marquée n'est plus présentée.
        cli.tokens.access_expires_at = 0.0
        await cli.query("select * from Customer")
        assert intuit.presentes == ["rt-mort", "rt-0", "rt-1"]

        # Le client partagé de Construction relit la ligne : aucun conflit.
        construction = qb.get_qbo()
        await construction.forcer_renouvellement()
        assert intuit.presentes[-1] == "rt-2"

    run(scenario())
    assert run(_ligne_construction()).refresh_token == "rt-3"
    inc = run(_ligne_inc())
    assert inc.refresh_token == "rt-mort"
    assert inc.reconnect_required_at is not None


def test_sans_jumelle_la_reconnexion_reste_demandee(intuit, run):
    _seed_inc(run, realm="autre-compagnie")

    async def scenario() -> None:
        cli = qb.get_qbo(SCOPE_INC)
        await cli._load_refresh_from_db()
        with pytest.raises(qb.QuickBooksReconnexionRequise):
            await cli.query("select * from Customer")

    run(scenario())
    assert run(_ligne_inc()).reconnect_required_at is not None
    assert run(_ligne_construction()).refresh_token == "rt-0"


def test_cron_rapporte_le_relais(intuit, run):
    _seed_inc(run)

    async def marquer() -> None:
        async with TestSessionLocal() as s:
            row = (
                await s.execute(select(QboConnection).where(QboConnection.scope == SCOPE_INC))
            ).scalar_one()
            row.reconnect_required_at = datetime.now(timezone.utc)
            await s.commit()

    run(marquer())
    out = run(qb.garder_connexions_vivantes())
    assert out["construction"] == "ok"
    assert out[SCOPE_INC] == "relais par construction"
