"""Période de paie — fréquence et jours, réglables (Steven, 2026-11-10).

« Permettre dans les paramètres de choisir la fréquence de période de paie
et de quel jour à quel jour. Ex : en ce moment du dimanche au samedi, mais
selon le système de paie on est du lundi au dimanche. […] le rapport de
paie est sur 2 semaines, mais la paie est rendue à la semaine. »

Réglage unique dans ``AutomationSetting("periode_paie")`` (``config_json``) :

- ``frequence`` : ``hebdomadaire`` (7 jours) ou ``aux_2_semaines`` (14) ;
- ``jour_debut`` : premier jour de la période, 0 = lundi … 6 = dimanche
  (la période finit la veille de ce jour, 6 ou 13 jours plus loin) ;
- ``debut_reference`` : le premier jour d'UNE période connue. Il fixe
  quelle semaine ouvre une période aux 2 semaines ; il est toujours
  ramené sur ``jour_debut`` ;
- ``jours_coupure`` / ``jours_versement`` : la coupure des ajustements et
  le versement, en jours après la fin de la période.

Sans réglage : l'ancien cycle (aux 2 semaines, dimanche → samedi,
période du 19 avril au 2 mai 2026, coupure +3 j, versement +5 j).

Les journées sont celles de Montréal : un punch commencé à 21 h le
dimanche reste dans la journée du dimanche.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from app.models.automation_setting import AutomationSetting

KEY = "periode_paie"

FREQUENCES: dict[str, int] = {"hebdomadaire": 7, "aux_2_semaines": 14}
FREQUENCES_LABELS: dict[str, str] = {
    "hebdomadaire": "Hebdomadaire (7 jours)",
    "aux_2_semaines": "Aux 2 semaines (14 jours)",
}

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")

#: Ancien cycle codé en dur : période du dimanche 19 avril au samedi 2 mai
#: 2026, versée le jeudi 7 mai.
DEBUT_REFERENCE_HISTORIQUE = date(2026, 4, 19)

DEFAUT: dict[str, Any] = {
    "frequence": "aux_2_semaines",
    "jour_debut": 6,
    "debut_reference": DEBUT_REFERENCE_HISTORIQUE.isoformat(),
    "jours_coupure": 3,
    "jours_versement": 5,
}

DELAI_MAX_JOURS = 31


@dataclass(frozen=True)
class Reglages:
    frequence: str
    jour_debut: int
    debut_reference: date
    jours_coupure: int
    jours_versement: int

    @property
    def jours(self) -> int:
        return FREQUENCES[self.frequence]

    @property
    def jour_fin(self) -> int:
        return (self.jour_debut + 6) % 7

    @property
    def libelle_jours(self) -> str:
        return f"{JOURS[self.jour_debut]} → {JOURS[self.jour_fin]}"

    def en_dict(self) -> dict[str, Any]:
        return {
            "frequence": self.frequence,
            "jour_debut": self.jour_debut,
            "debut_reference": self.debut_reference.isoformat(),
            "jours_coupure": self.jours_coupure,
            "jours_versement": self.jours_versement,
        }


@dataclass(frozen=True)
class Periode:
    debut: date
    fin: date
    coupure: date
    versement: date
    #: (début, fin) de chaque semaine de la période, dans l'ordre.
    semaines: tuple[tuple[date, date], ...]

    def semaine_de(self, jour: date) -> int:
        """Index (0, 1) de la semaine qui contient ``jour``."""
        return min((jour - self.debut).days // 7, len(self.semaines) - 1)


def aligner_sur_jour(jour: date, jour_debut: int) -> date:
    """Le dernier ``jour_debut`` (0 = lundi) tombant au plus tard ``jour``."""
    return jour - timedelta(days=(jour.weekday() - jour_debut) % 7)


def _entier(v: Any, defaut: int, mini: int, maxi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return defaut
    return n if mini <= n <= maxi else defaut


def normaliser(cfg: Any) -> Reglages:
    """Réglages complets et cohérents, quelle que soit la config stockée."""
    cfg = cfg if isinstance(cfg, dict) else {}
    frequence = cfg.get("frequence")
    if frequence not in FREQUENCES:
        frequence = DEFAUT["frequence"]
    jour_debut = _entier(cfg.get("jour_debut"), DEFAUT["jour_debut"], 0, 6)
    try:
        ref = date.fromisoformat(str(cfg.get("debut_reference") or ""))
    except ValueError:
        ref = DEBUT_REFERENCE_HISTORIQUE
    return Reglages(
        frequence=frequence,
        jour_debut=jour_debut,
        debut_reference=aligner_sur_jour(ref, jour_debut),
        jours_coupure=_entier(
            cfg.get("jours_coupure"), DEFAUT["jours_coupure"], 0, DELAI_MAX_JOURS
        ),
        jours_versement=_entier(
            cfg.get("jours_versement"), DEFAUT["jours_versement"], 0, DELAI_MAX_JOURS
        ),
    )


async def charger_reglages(db) -> Reglages:
    row = await db.get(AutomationSetting, KEY)
    if not row or not row.config_json:
        return normaliser({})
    try:
        return normaliser(json.loads(row.config_json))
    except Exception:  # noqa: BLE001
        return normaliser({})


async def enregistrer_reglages(
    db, cfg: dict[str, Any], *, user_id: Optional[int] = None
) -> Reglages:
    """Enregistre (validation faite par l'appelant). N'appelle pas commit."""
    propre = normaliser(cfg)
    row = await db.get(AutomationSetting, KEY)
    if row is None:
        row = AutomationSetting(key=KEY, enabled=True)
        db.add(row)
    row.config_json = json.dumps(propre.en_dict(), ensure_ascii=False)
    if user_id is not None:
        row.updated_by_user_id = user_id
    await db.flush()
    return propre


def periode_contenant(jour: date, r: Reglages) -> Periode:
    """La période de paie qui contient ``jour``."""
    n = r.jours
    debut = r.debut_reference + timedelta(
        days=((jour - r.debut_reference).days // n) * n
    )
    fin = debut + timedelta(days=n - 1)
    semaines = tuple(
        (debut + timedelta(days=7 * i), debut + timedelta(days=7 * i + 6))
        for i in range(n // 7)
    )
    return Periode(
        debut=debut,
        fin=fin,
        coupure=fin + timedelta(days=r.jours_coupure),
        versement=fin + timedelta(days=r.jours_versement),
        semaines=semaines,
    )


def periode_a_afficher(aujourd_hui: date, r: Reglages) -> Periode:
    """La période qui vient de finir tant qu'elle n'est pas versée, sinon
    la période en cours."""
    courante = periode_contenant(aujourd_hui, r)
    precedente = periode_contenant(courante.debut - timedelta(days=1), r)
    if aujourd_hui <= precedente.versement:
        return precedente
    return courante
