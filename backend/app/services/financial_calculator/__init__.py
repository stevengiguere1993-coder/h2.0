"""Calculateur financier multi-logements (Québec) — port Python.

Parité 1:1 avec l'implémentation TypeScript dans
`frontend/src/lib/financial-calculator/`. Permet de tourner le
calcul backend sans dépendre du frontend (cron Centris auto-analyse,
batch jobs, etc.).

3 scénarios :
- Achat conventionnel
- Refinancement SCHL
- Refinancement APH 50

Mêmes formules, mêmes constantes, mêmes valeurs de référence
testées (Achat MDF ≈ 590 882 $, APH50 gain ≈ 238 842 $).
"""

from .calculator import calculer_analyse
from .types import (
    AnalyseInputs,
    AnalyseResultats,
    DepensesDetail,
    FraisDemarrageInputs,
    INPUTS_DEFAULTS,
    ScenarioId,
    ScenarioResultat,
)

__all__ = [
    "AnalyseInputs",
    "AnalyseResultats",
    "DepensesDetail",
    "FraisDemarrageInputs",
    "INPUTS_DEFAULTS",
    "ScenarioId",
    "ScenarioResultat",
    "calculer_analyse",
]
