"""Retour arrière de la prime CNESST globale (PR #1819).

Base SQLite jetable avec les seules tables touchées, dans l'état laissé par
le réglage (taux vide = taux global, case décochée = aucune prime). Après
le retour, chaque taux est explicite et donne le même coût que le réglage
au code d'avant, qui lit un taux vide comme 0 % ; le barème est retiré.
"""

import asyncio
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from app.services import cnesst_retour  # noqa: E402

BAREME = {
    "paliers": [
        {"depuis": "2000-01-01", "taux": 0.0216},
        {"depuis": "2027-01-01", "taux": 0.0205},
    ]
}


async def _base(path, *, bareme=BAREME, avec_case=True):
    eng = create_async_engine(f"sqlite+aiosqlite:///{path}")
    case = ", cnesst_actif BOOLEAN NOT NULL DEFAULT 1" if avec_case else ""
    async with eng.begin() as c:
        await c.execute(
            text("CREATE TABLE automation_settings (key VARCHAR PRIMARY KEY, config_json TEXT)")
        )
        await c.execute(
            text(f"CREATE TABLE employes (id INTEGER PRIMARY KEY, cnesst_rate NUMERIC(6, 4){case})")
        )
        await c.execute(
            text(
                "CREATE TABLE employe_rate_history (id INTEGER PRIMARY KEY, "
                f"effective_date DATE, cnesst_rate NUMERIC(6, 4){case})"
            )
        )
        if bareme is not None:
            await c.execute(
                text("INSERT INTO automation_settings VALUES ('paie.cnesst', :c)"),
                {"c": json.dumps(bareme)},
            )
    return eng


async def _retour(eng):
    async with AsyncSession(eng) as s:
        n = await cnesst_retour.defaire_cnesst_global(s)
        await s.commit()
    return n


async def _taux(eng, table):
    async with eng.connect() as c:
        rows = (await c.execute(text(f"SELECT id, cnesst_rate FROM {table} ORDER BY id"))).all()
    return {i: (None if t is None else round(float(t), 4)) for i, t in rows}


async def _cles(eng):
    async with eng.connect() as c:
        return (await c.execute(text("SELECT key FROM automation_settings"))).scalars().all()


def test_taux_reecrits_et_bareme_retire(tmp_path, monkeypatch):
    monkeypatch.setattr(cnesst_retour, "aujourd_hui_local", lambda: date(2026, 10, 14))

    async def scenario():
        eng = await _base(tmp_path / "r.db")
        async with eng.begin() as c:
            await c.execute(
                text(
                    "INSERT INTO employes (id, cnesst_rate, cnesst_actif) VALUES "
                    "(1, NULL, 1), (2, 0.0105, 1), (3, NULL, 0)"
                )
            )
            await c.execute(
                text(
                    "INSERT INTO employe_rate_history (id, effective_date, cnesst_rate, cnesst_actif) VALUES "
                    "(10, '2026-01-01', NULL, 1), (11, '2027-03-01', NULL, 1), "
                    "(12, '1999-05-01', NULL, 1), (13, '2026-06-01', 0.03, 1), "
                    "(14, '2026-06-01', NULL, 0)"
                )
            )
        n = await _retour(eng)
        fiches = await _taux(eng, "employes")
        paliers = await _taux(eng, "employe_rate_history")
        cles = await _cles(eng)
        encore = await _retour(eng)
        await eng.dispose()
        return n, fiches, paliers, cles, encore

    n, fiches, paliers, cles, encore = asyncio.run(scenario())
    # Taux global d'aujourd'hui sur la fiche ; perso gardé ; décochée → 0.
    assert fiches == {1: 0.0216, 2: 0.0105, 3: 0.0}
    # Palier : taux global en vigueur à sa date (le premier couvre le passé).
    assert paliers == {10: 0.0216, 11: 0.0205, 12: 0.0216, 13: 0.03, 14: 0.0}
    assert n == 6
    assert cles == []
    assert encore is None


def test_sans_bareme_rien_ne_change(tmp_path):
    async def scenario():
        eng = await _base(tmp_path / "r.db", bareme=None)
        async with eng.begin() as c:
            await c.execute(text("INSERT INTO employes (id, cnesst_rate) VALUES (1, NULL)"))
        n = await _retour(eng)
        fiches = await _taux(eng, "employes")
        await eng.dispose()
        return n, fiches

    assert asyncio.run(scenario()) == (None, {1: None})


def test_sans_colonne_case_seul_le_bareme_part(tmp_path):
    async def scenario():
        eng = await _base(tmp_path / "r.db", avec_case=False)
        async with eng.begin() as c:
            await c.execute(text("INSERT INTO employes (id, cnesst_rate) VALUES (1, NULL)"))
        n = await _retour(eng)
        fiches = await _taux(eng, "employes")
        cles = await _cles(eng)
        await eng.dispose()
        return n, fiches, cles

    assert asyncio.run(scenario()) == (0, {1: None}, [])
