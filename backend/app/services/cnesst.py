"""Prime CNESST : taux global réglable dans Paramètres, exceptions par employé.

Steven (2026-10-14) : « la prime CNESST s'applique à tous les employés, de
base c'est la même. Il faudrait pouvoir l'ajuster dans les paramètres et
décocher une case dans la section employé, ou la changer manuellement s'il
avait un taux différent. »

Règle (coût horaire réel = base × (1 + CNESST + CCQ)) :

- **Taux global** (Paramètres → Prime CNESST) : un barème DATÉ, comme
  l'historique des taux d'un employé. Chaque palier vaut à partir de sa
  date et le premier couvre tout le passé. Changer le taux en janvier ne
  recoûte donc pas les heures punchées avant : un punch suit le taux en
  vigueur À SA DATE.
- **Fiche employé** : case « Prime CNESST » (cochée par défaut) et taux
  personnalisé facultatif (``employes.cnesst_actif`` /
  ``employes.cnesst_rate``, mêmes colonnes sur chaque palier de
  ``employe_rate_history``). Décochée → aucune prime ; taux personnalisé →
  il remplace le taux global ; vide → le taux global s'applique.

Stockage du barème : clé ``paie.cnesst`` d'``automation_settings``
(config JSON ``{"paliers": [{"depuis": "AAAA-MM-JJ", "taux": 0.0216}]}``,
taux en DÉCIMAL comme partout ailleurs), comme la date de démarrage
locative. Sans barème, le taux global vaut 0 % : exactement le calcul
d'avant ce réglage (un taux vide sur la fiche ne coûtait rien).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import func, select, update

from app.models.automation_setting import AutomationSetting
from app.models.employe import Employe
from app.models.employe_rate_history import EmployeRateHistory
from app.services.punch_diner import aujourd_hui_local

log = logging.getLogger(__name__)

#: Clé du barème dans ``automation_settings``.
CNESST_KEY = "paie.cnesst"

#: Date du palier créé à l'initialisation : il couvre tout le passé.
DEBUT_BAREME = date(2000, 1, 1)


@dataclass(frozen=True)
class PalierCnesst:
    """Taux global (DÉCIMAL) en vigueur à partir de ``depuis``."""

    depuis: date
    taux: float


@dataclass(frozen=True)
class BaremeCnesst:
    """Paliers du taux global, triés par date croissante (une date = un
    palier). Vide = aucun taux global (0 %)."""

    paliers: tuple[PalierCnesst, ...] = ()

    def taux_au(self, jour: Optional[date]) -> float:
        """Taux global en vigueur à ``jour`` : le palier le plus récent dont
        la date est ≤ ``jour`` ; avant le premier palier, le premier (il
        couvre le passé, comme la baseline des taux d'un employé).
        ``None`` → aujourd'hui (heure de Montréal)."""
        if not self.paliers:
            return 0.0
        if jour is None:
            jour = aujourd_hui_local()
        choisi = self.paliers[0]
        for p in self.paliers:
            if p.depuis <= jour:
                choisi = p
            else:
                break
        return choisi.taux

    @property
    def taux_actuel(self) -> float:
        return self.taux_au(None)

    def avec_palier(self, depuis: date, taux: float) -> "BaremeCnesst":
        """Barème avec ``taux`` à partir de ``depuis`` (remplace le palier
        de la même date s'il existe)."""
        autres = [p for p in self.paliers if p.depuis != depuis]
        autres.append(PalierCnesst(depuis, _arrondi(taux)))
        return BaremeCnesst(tuple(sorted(autres, key=lambda p: p.depuis)))

    def sans_palier(self, depuis: date) -> "BaremeCnesst":
        return BaremeCnesst(tuple(p for p in self.paliers if p.depuis != depuis))

    def en_json(self) -> dict[str, Any]:
        return {
            "paliers": [
                {"depuis": p.depuis.isoformat(), "taux": p.taux}
                for p in self.paliers
            ]
        }


def _arrondi(taux: Any) -> float:
    # Numeric(6, 4) en base : 4 décimales suffisent, 6 évitent les
    # artefacts de virgule flottante sans rien perdre.
    return round(float(taux), 6)


def taux_cnesst(
    actif: Optional[bool],
    perso: Any,
    bareme: Optional[BaremeCnesst],
    jour: Optional[date],
) -> float:
    """Prime CNESST (DÉCIMAL) d'une fiche ou d'un palier à ``jour`` :
    0 si la case est décochée, sinon le taux personnalisé s'il est saisi,
    sinon le taux global à cette date. ``actif`` à None (colonne pas encore
    posée) compte comme coché."""
    if actif is False:
        return 0.0
    if perso is not None:
        return float(perso)
    return bareme.taux_au(jour) if bareme is not None else 0.0


def bareme_depuis_config(cfg: Any) -> BaremeCnesst:
    """Barème lu d'une config JSON ; un palier illisible est ignoré."""
    bareme = BaremeCnesst()
    paliers = cfg.get("paliers") if isinstance(cfg, dict) else None
    for brut in paliers or []:
        try:
            depuis = date.fromisoformat(str(brut["depuis"]))
            taux = float(brut["taux"])
        except (KeyError, TypeError, ValueError):
            log.warning("Palier CNESST illisible ignoré : %r", brut)
            continue
        if not 0 <= taux <= 1:
            log.warning("Palier CNESST hors bornes ignoré : %r", brut)
            continue
        bareme = bareme.avec_palier(depuis, taux)
    return bareme


async def charger_bareme_cnesst(db) -> BaremeCnesst:
    """Barème du taux global (vide si jamais réglé)."""
    row = (
        await db.execute(
            select(AutomationSetting.config_json).where(
                AutomationSetting.key == CNESST_KEY
            )
        )
    ).first()
    if row is None or not row[0]:
        return BaremeCnesst()
    try:
        cfg = json.loads(row[0])
    except ValueError:
        log.warning("Barème CNESST illisible — aucun taux global appliqué")
        return BaremeCnesst()
    return bareme_depuis_config(cfg)


async def enregistrer_bareme_cnesst(
    db, bareme: BaremeCnesst, *, user_id: Optional[int] = None
) -> None:
    """Enregistre le barème. Ne commit pas."""
    from app.services.automation_state import set_automation_config

    await set_automation_config(db, CNESST_KEY, bareme.en_json(), user_id=user_id)


def config_cnesst(obj: Any) -> tuple[bool, Optional[float]]:
    """(case cochée, taux personnalisé) d'une fiche ou d'un palier, pour
    comparer avant / après une modification."""
    perso = getattr(obj, "cnesst_rate", None)
    return (
        getattr(obj, "cnesst_actif", True) is not False,
        _arrondi(perso) if perso is not None else None,
    )


async def aligner_paliers_cnesst(db, emp: Employe) -> int:
    """Recopie la prime CNESST de la fiche (case + taux personnalisé) sur
    le palier de taux en vigueur aujourd'hui et sur les paliers suivants.

    La fiche porte la config COURANTE ; sans cet alignement, décocher la
    case ne changerait rien pour un employé qui a un historique de taux
    (son coût suit ses paliers). Retourne le nombre de paliers modifiés."""
    paliers = (
        await db.execute(
            select(EmployeRateHistory)
            .where(EmployeRateHistory.employe_id == emp.id)
            .order_by(EmployeRateHistory.effective_date.asc())
        )
    ).scalars().all()
    if not paliers:
        return 0
    aujourd_hui = aujourd_hui_local()
    debut = 0
    for i, p in enumerate(paliers):
        if p.effective_date <= aujourd_hui:
            debut = i
    actif, perso = config_cnesst(emp)
    for p in paliers[debut:]:
        p.cnesst_actif = actif
        p.cnesst_rate = perso
    await db.flush()
    return len(paliers) - debut


async def _taux_le_plus_frequent(db) -> Any:
    """Taux CNESST (> 0) le plus fréquent sur les fiches des employés
    actifs, sinon de tous les employés ; None si aucune fiche n'en a."""
    for actifs_seulement in (True, False):
        stmt = (
            select(Employe.cnesst_rate)
            .where(Employe.cnesst_rate.is_not(None), Employe.cnesst_rate > 0)
            .group_by(Employe.cnesst_rate)
            .order_by(func.count(Employe.id).desc(), Employe.cnesst_rate.desc())
            .limit(1)
        )
        if actifs_seulement:
            stmt = stmt.where(Employe.active.is_(True))
        row = (await db.execute(stmt)).first()
        if row is not None:
            return row[0]
    return None


async def initialiser_cnesst_global(db) -> Optional[float]:
    """Mise en place du taux global, UNE fois (au démarrage, tant que le
    barème n'existe pas). Ne commit pas.

    Avant ce réglage, chaque fiche portait son propre taux (vide = 0 %).
    - Taux global de départ = le taux le plus fréquent sur les fiches des
      employés actifs (sinon de tous ; sinon 0 %), daté du 2000-01-01 pour
      couvrir tout le passé.
    - Fiche ou palier à ce taux → suit le taux global : même coût.
    - Taux différent → gardé comme taux personnalisé : même coût.
    - Taux 0 → case décochée : même coût.
    - Taux vide → suit le taux global : c'est la règle demandée (la prime
      s'applique à tous les employés ; on décoche la case pour exclure
      quelqu'un).

    Retourne le taux global de départ, ou None si le barème existait déjà.
    """
    deja = (
        await db.execute(
            select(AutomationSetting.key).where(AutomationSetting.key == CNESST_KEY)
        )
    ).first()
    if deja is not None:
        return None
    taux = await _taux_le_plus_frequent(db)
    depart = _arrondi(taux) if taux is not None else 0.0
    # La clé d'abord : si deux instances démarrent ensemble, la seconde
    # bute ici sur la clé primaire et tout est annulé de son côté (rien
    # n'est converti deux fois).
    db.add(
        AutomationSetting(
            key=CNESST_KEY,
            enabled=True,
            config_json=json.dumps(
                BaremeCnesst((PalierCnesst(DEBUT_BAREME, depart),)).en_json()
            ),
        )
    )
    await db.flush()
    for modele in (Employe, EmployeRateHistory):
        await db.execute(
            update(modele)
            .where(modele.cnesst_rate == 0)
            .values(cnesst_actif=False, cnesst_rate=None)
            .execution_options(synchronize_session=False)
        )
        if taux is not None:
            await db.execute(
                update(modele)
                .where(modele.cnesst_rate == taux)
                .values(cnesst_rate=None)
                .execution_options(synchronize_session=False)
            )
    return depart
