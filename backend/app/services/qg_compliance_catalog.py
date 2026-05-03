"""Bibliothèque de templates de tâches récurrentes Québec.

Chaque entrée définit une obligation comptable / fiscale / réglementaire
courante d'une entreprise québécoise, avec sa cadence par défaut. L'utilisateur
peut en importer un sous-ensemble en un clic depuis l'UI Pilotage.

Les fréquences sont calibrées pour donner du lead time raisonnable :
- TPS/TVQ : trimestre civil (1er du mois), avec lead 30j (déclaration due
  fin du mois suivant le trimestre).
- T2 fédérale + CO-17 provinciale : annuelle, calée sur la fin d'exercice
  + 6 mois (l'utilisateur ajustera la date).
- REQ : annuelle, mise à jour annuelle obligatoire au Registraire QC.
- DAS (déductions à la source) : mensuelle, due le 15 du mois suivant.
- T4 / Relevé 1 : annuelle (fin février).
- CNESST : annuelle (déclaration salaires en mars).
- Rapprochement bancaire, états financiers internes : mensuels.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ComplianceTemplate:
    code: str           # identifiant stable
    label: str          # nom affiché à l'utilisateur
    description: str
    departement: str
    every_n: int
    unit: str           # jour | semaine | mois | annee
    lead_days: int
    impact: int         # 1-10 ICE par défaut
    confidence: int
    effort: int


# Catalogue ordonné par catégorie pour l'affichage UI.
COMPLIANCE_TEMPLATES: tuple[ComplianceTemplate, ...] = (
    # --- Fiscalité fédérale + provinciale ---
    ComplianceTemplate(
        code="tps_tvq_trimestriel",
        label="Déclaration TPS/TVQ trimestrielle",
        description=(
            "Calcul, paiement et transmission de la déclaration TPS/TVQ "
            "via Mon dossier (Revenu Québec). Due fin du mois suivant le "
            "trimestre civil."
        ),
        departement="Compta",
        every_n=3,
        unit="mois",
        lead_days=30,
        impact=9,
        confidence=10,
        effort=4,
    ),
    ComplianceTemplate(
        code="t2_co17_annuel",
        label="Déclaration T2 (fédéral) + CO-17 (Québec)",
        description=(
            "Production des déclarations corporatives annuelles. Échéance "
            "6 mois après la fin d'exercice. Idéalement préparé par le "
            "comptable externe."
        ),
        departement="Compta",
        every_n=1,
        unit="annee",
        lead_days=90,
        impact=10,
        confidence=10,
        effort=7,
    ),
    ComplianceTemplate(
        code="req_annuel",
        label="Mise à jour annuelle Registraire des entreprises (REQ)",
        description=(
            "Confirmer / modifier l'information au Registraire des "
            "entreprises du Québec. Frais ~98 $. Pénalités si retard."
        ),
        departement="Admin",
        every_n=1,
        unit="annee",
        lead_days=45,
        impact=8,
        confidence=10,
        effort=2,
    ),
    ComplianceTemplate(
        code="acomptes_provisionnels_t",
        label="Acomptes provisionnels trimestriels (corporatifs)",
        description=(
            "Versement trimestriel des acomptes d'impôt sur le revenu "
            "(ARC + Revenu Québec) pour éviter les intérêts."
        ),
        departement="Compta",
        every_n=3,
        unit="mois",
        lead_days=14,
        impact=8,
        confidence=9,
        effort=2,
    ),

    # --- Paie ---
    ComplianceTemplate(
        code="das_mensuel",
        label="Versement DAS (déductions à la source)",
        description=(
            "Remise mensuelle des DAS fédérales (ARC) et provinciales "
            "(Revenu QC). Due le 15 du mois suivant."
        ),
        departement="Paie",
        every_n=1,
        unit="mois",
        lead_days=10,
        impact=10,
        confidence=10,
        effort=2,
    ),
    ComplianceTemplate(
        code="t4_releve1_annuel",
        label="Production T4 + Relevé 1 (paie annuelle)",
        description=(
            "Émission des feuillets T4 (ARC) et Relevé 1 (RQ) aux employés "
            "et à l'autorité. Dernier jour de février."
        ),
        departement="Paie",
        every_n=1,
        unit="annee",
        lead_days=30,
        impact=9,
        confidence=10,
        effort=4,
    ),
    ComplianceTemplate(
        code="cnesst_annuel",
        label="Déclaration annuelle CNESST",
        description=(
            "Déclaration de la masse salariale assurable et paiement "
            "de la cotisation CNESST. Due 15 mars."
        ),
        departement="Paie",
        every_n=1,
        unit="annee",
        lead_days=21,
        impact=8,
        confidence=10,
        effort=3,
    ),
    ComplianceTemplate(
        code="cnesst_acompte",
        label="Acompte CNESST périodique",
        description=(
            "Versement périodique des cotisations CNESST en cours d'année "
            "(à intégrer avec la paie habituelle)."
        ),
        departement="Paie",
        every_n=1,
        unit="mois",
        lead_days=10,
        impact=7,
        confidence=9,
        effort=1,
    ),

    # --- Compta interne / opérations ---
    ComplianceTemplate(
        code="rapprochement_bancaire",
        label="Rapprochement bancaire mensuel",
        description=(
            "Concilier le compte bancaire avec les écritures comptables "
            "et corriger les écarts."
        ),
        departement="Compta",
        every_n=1,
        unit="mois",
        lead_days=5,
        impact=7,
        confidence=10,
        effort=3,
    ),
    ComplianceTemplate(
        code="etats_financiers_mensuels",
        label="Saisie snapshot financier mensuel",
        description=(
            "Mettre à jour le snapshot finance dans h2.0 (revenu, EBITDA, "
            "trésorerie, valorisation estimée) pour le mois écoulé."
        ),
        departement="Compta",
        every_n=1,
        unit="mois",
        lead_days=7,
        impact=8,
        confidence=10,
        effort=2,
    ),
    ComplianceTemplate(
        code="revue_kpi_trimestriel",
        label="Revue de performance trimestrielle",
        description=(
            "Compare réel vs plan de valeur, ajuste les drivers, "
            "communique aux parties prenantes."
        ),
        departement="Direction",
        every_n=3,
        unit="mois",
        lead_days=10,
        impact=9,
        confidence=8,
        effort=4,
    ),

    # --- Assurance et permis ---
    ComplianceTemplate(
        code="renouvellement_assurance",
        label="Renouvellement police d'assurance",
        description=(
            "Comparer les renouvellements, ajuster les couvertures "
            "(responsabilité civile, immeubles, cybersécurité, etc.)."
        ),
        departement="Admin",
        every_n=1,
        unit="annee",
        lead_days=60,
        impact=8,
        confidence=9,
        effort=3,
    ),
    ComplianceTemplate(
        code="renouvellement_permis",
        label="Renouvellement permis et licences",
        description=(
            "Vérifier les permis municipaux, RBQ, ACQ, OACIQ et autres "
            "selon le secteur d'activité."
        ),
        departement="Admin",
        every_n=1,
        unit="annee",
        lead_days=45,
        impact=7,
        confidence=9,
        effort=2,
    ),
)


def get_by_codes(codes: list[str]) -> list[ComplianceTemplate]:
    """Retourne les templates correspondant aux codes (préserve l'ordre catalogue)."""
    wanted = set(codes)
    return [t for t in COMPLIANCE_TEMPLATES if t.code in wanted]


def first_day_next_month(today: date) -> date:
    """Calcule le 1er du mois suivant — utile pour fixer next_due par défaut."""
    if today.month == 12:
        return today.replace(year=today.year + 1, month=1, day=1)
    return today.replace(month=today.month + 1, day=1)
