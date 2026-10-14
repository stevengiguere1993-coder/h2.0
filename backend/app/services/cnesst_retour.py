"""Retour arrière de la prime CNESST globale (PR #1819).

En ligne, le réglage a converti les fiches : un taux égal au taux global
est devenu vide (« suit le taux global ») et un taux à 0 a décoché la case
``cnesst_actif``. Le code d'avant lit un taux vide comme 0 % : sans ce
retour, les employés qui suivaient le taux global perdraient leur prime.

Au démarrage, tant que le barème (clé ``paie.cnesst``) existe :
- case décochée → taux 0 ;
- case cochée sans taux personnalisé → le taux global que le réglage
  appliquait (sur un palier de taux : celui en vigueur à sa date ; sur la
  fiche : celui d'aujourd'hui) ;
- puis le barème est retiré. Le coût de chacun reste celui que calculait
  le réglage, et une remise en ligne du réglage refera la conversion.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional

from sqlalchemy import inspect, text

from app.services.punch_diner import aujourd_hui_local

log = logging.getLogger(__name__)

CNESST_KEY = "paie.cnesst"


def _paliers(config_json: Optional[str]) -> list[tuple[date, float]]:
    try:
        cfg = json.loads(config_json or "{}")
        out = [
            (date.fromisoformat(str(p["depuis"])), float(p["taux"]))
            for p in cfg.get("paliers") or []
        ]
    except (ValueError, KeyError, TypeError, AttributeError):
        log.warning("Barème CNESST illisible : taux vides laissés à 0 %")
        return []
    return sorted(out)


def _taux_au(paliers: list[tuple[date, float]], jour: date) -> float:
    taux = paliers[0][1]
    for depuis, t in paliers:
        if depuis <= jour:
            taux = t
    return taux


async def defaire_cnesst_global(db) -> Optional[int]:
    """Réécrit les taux CNESST explicites et retire le barème. Retourne le
    nombre de fiches et de paliers réécrits, ou None s'il n'y avait pas de
    barème. Ne commit pas."""
    row = (
        await db.execute(
            text("SELECT config_json FROM automation_settings WHERE key = :k"),
            {"k": CNESST_KEY},
        )
    ).first()
    if row is None:
        return None

    def _colonnes(session, table: str) -> set[str]:
        return {c["name"] for c in inspect(session.connection()).get_columns(table)}

    paliers = _paliers(row[0])
    n = 0
    for table in ("employes", "employe_rate_history"):
        if "cnesst_actif" not in await db.run_sync(_colonnes, table):
            continue
        res = await db.execute(
            text(f"UPDATE {table} SET cnesst_rate = 0 WHERE cnesst_actif = :non"),
            {"non": False},
        )
        n += res.rowcount or 0
        if not paliers:
            continue
        vides = f"UPDATE {table} SET cnesst_rate = :t WHERE cnesst_rate IS NULL AND cnesst_actif = :oui"
        if table == "employes":
            res = await db.execute(
                text(vides),
                {"t": _taux_au(paliers, aujourd_hui_local()), "oui": True},
            )
            n += res.rowcount or 0
            continue
        # Paliers de taux : le taux global en vigueur à leur date ; le
        # premier palier du barème couvre aussi tout ce qui le précède.
        for i, (depuis, taux) in enumerate(paliers):
            sql, params = vides, {"t": taux, "oui": True}
            if i > 0:
                sql += " AND effective_date >= :bas"
                params["bas"] = depuis
            if i + 1 < len(paliers):
                sql += " AND effective_date < :haut"
                params["haut"] = paliers[i + 1][0]
            res = await db.execute(text(sql), params)
            n += res.rowcount or 0

    await db.execute(
        text("DELETE FROM automation_settings WHERE key = :k"), {"k": CNESST_KEY}
    )
    return n
