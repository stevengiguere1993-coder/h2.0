"""Types + barèmes du calculateur. Mirroir de
`frontend/src/lib/financial-calculator/types.ts` et `defaults.ts`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

ScenarioId = Literal["achat", "schl", "aph50"]


@dataclass
class FraisDemarrageInputs:
    courtierHypo1: Optional[float] = None  # 1% prixAchat si None
    courtierHypo2: Optional[float] = None  # 1% prêt refi si None
    taxesBienvenue: float = 0.0
    evaluateur1: float = 1500.0
    evaluateur2: float = 1500.0
    inspection: float = 1700.0
    avocat: float = 4000.0
    notaire1: float = 1600.0
    notaire2: float = 1600.0
    rapportEfficacite: float = 4500.0
    fraisDeveloppement: float = 60000.0
    fraisNegociation: float = 60000.0
    fraisTravaux: float = 60000.0
    interets: Optional[float] = None  # calculé si None
    revenusNets: Optional[float] = None  # calculé si None


@dataclass
class AnalyseInputs:
    adresse: str = ""
    prixAchat: float = 0.0
    nombreLogements: int = 0
    revenusAnnuels: float = 0.0
    taxesMunicipales: float = 0.0
    taxesScolaires: float = 0.0
    assurances: float = 0.0
    energie: float = 0.0
    autresDepenses: float = 0.0
    logementsAjoutes: int = 0
    thermopompesAjoutees: int = 0
    wifi: bool = False
    reductionCoutEnergie: float = 0.0
    nouveauLoyerMoyen: float = 0.0
    nombreAnneesPortage: int = 2
    fraisDemarrage: FraisDemarrageInputs = field(
        default_factory=FraisDemarrageInputs
    )
    tga: float = 0.04
    tauxInteretAchat: float = 0.04
    tauxInteretRefi: float = 0.0375


def INPUTS_DEFAULTS() -> AnalyseInputs:
    """Instance par défaut (helper, équivalent du objet
    INPUTS_DEFAULTS en TS)."""
    return AnalyseInputs()


@dataclass
class DepensesDetail:
    inoccupation: float = 0.0
    taxesMunicipales: float = 0.0
    taxesScolaires: float = 0.0
    assurances: float = 0.0
    energie: float = 0.0
    concierge: float = 0.0
    entretien: float = 0.0
    gestion: float = 0.0
    wifi: float = 0.0
    thermopompes: float = 0.0
    autres: float = 0.0
    total: float = 0.0


@dataclass
class ScenarioResultat:
    id: ScenarioId
    label: str
    fraisDemarrageTotal: float
    prixAcquisition: float
    revenusTotaux: float
    depensesNormalisees: DepensesDetail
    revenusNets: float
    valeurEconomiqueTGA: float
    paiementHypoMax: float
    hypothequeMaxRCD: float
    valeurEconomiqueRCD: float
    valeurMarchande: float
    valeurRetenue: float
    ratioCouvertureDette: float
    ratioPretValeur: float
    amortissementAnnees: int
    tauxInteret: float
    pretAccorde: float
    miseDeFonds: Optional[float] = None
    gainActionnaires: Optional[float] = None


@dataclass
class AnalyseResultats:
    achat: ScenarioResultat
    schl: ScenarioResultat
    aph50: ScenarioResultat
    inputsEffectifs: AnalyseInputs


# Barèmes Québec multi-logements
BAREMES = {
    "conciergeBas": 215.0,
    "conciergeHaut": 365.0,
    "conciergeSeuil": 12,
    "entretien": 610.0,
    "gestionBas": 0.0425,
    "gestionHaut": 0.05,
    "gestionSeuil": 12,
    "wifiParLogParMois": 5.0,
    "wifiInternetParMois": 120.0,
    "thermopompeParUniteParAn": 190.0,
    "inoccupationPct": 0.03,
}


SCENARIO_PARAMS: dict[ScenarioId, dict] = {
    "achat": {
        "label": "Achat conventionnel",
        "ratioCouvertureDette": 1.2,
        "ratioPretValeur": 0.75,
        "amortissementAnnees": 25,
    },
    "schl": {
        "label": "Refinancement SCHL",
        "ratioCouvertureDette": 1.3,
        "ratioPretValeur": 0.85,
        "amortissementAnnees": 35,
    },
    "aph50": {
        "label": "Refinancement APH 50",
        "ratioCouvertureDette": 1.1,
        "ratioPretValeur": 0.85,
        "amortissementAnnees": 40,
    },
}
