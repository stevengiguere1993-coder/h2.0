"""Schemas Pydantic pour les extensions immobilier (TAL forms,
renouvellements automatiques, vue par entreprise propriétaire)."""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Formulaires TAL ──────────────────────────────────────────────────


class TalFormType(BaseModel):
    code: str
    label: str
    description: str


class TalFormRequest(BaseModel):
    """Paramètres optionnels pour générer un PDF.

    Si non fournis, on utilise les valeurs courantes du bail / locataire /
    immeuble. Permet à l'utilisateur de saisir un nouveau loyer / nouvelle
    date sans modifier le bail courant.
    """
    nouveau_loyer: Optional[float] = Field(default=None, ge=0)
    nouvelle_date_debut: Optional[date] = None
    nouvelle_date_fin: Optional[date] = None
    motif: Optional[str] = None
    montant_du: Optional[float] = Field(default=None, ge=0)
    mois_concerne: Optional[date] = None
    delai_paiement_jours: Optional[int] = Field(default=None, ge=1, le=60)


# ─── Renouvellement workflow ──────────────────────────────────────────


class EnvoyerRenouvellementRequest(BaseModel):
    """Déclenchement manuel d'un avis de renouvellement pour un bail."""
    nouveau_loyer: Optional[float] = Field(default=None, ge=0)
    nouvelle_date_debut: Optional[date] = None
    nouvelle_date_fin: Optional[date] = None
    motif: Optional[str] = None
    force: bool = False


class EnvoyerRenouvellementResult(BaseModel):
    renouvellement_id: int
    courriel_envoye: bool
    avis_envoye_le: date
    nouveau_loyer: Optional[float] = None
    nouvelle_date_debut: Optional[date] = None
    nouvelle_date_fin: Optional[date] = None


class RenouvellementScanResult(BaseModel):
    bails_scanned: int = 0
    avis_crees: int = 0
    courriels_envoyes: int = 0
    skipped: int = 0
    errors: List[str] = Field(default_factory=list)


class RenouvellementOverview(BaseModel):
    """Item d'aperçu pour la page Renouvellements (liste).

    Joint le bail + logement + locataire + dernier renouvellement
    en un seul aller-retour.
    """
    model_config = ConfigDict(from_attributes=True)

    bail_id: int
    immeuble_id: int
    immeuble_name: str
    logement_numero: str
    locataire_nom: str
    locataire_email: Optional[str] = None
    bail_date_fin: date
    bail_loyer_mensuel: float
    jours_avant_fin: int
    fenetre: str  # "imminente" | "a_envoyer" | "envoye" | "hors_fenetre"
    avis_envoye_le: Optional[date] = None
    nouveau_loyer: Optional[float] = None
    renouvellement_status: Optional[str] = None


# ─── Vue immobilier par entreprise ─────────────────────────────────────


class EntrepriseImmobilierImmeubleItem(BaseModel):
    """Immeuble apparaissant dans le portefeuille d'une entreprise."""
    model_config = ConfigDict(from_attributes=True)

    immeuble_id: int
    name: str
    address: str
    city: Optional[str] = None
    cover_photo_url: Optional[str] = None
    ownership_pct: float
    nb_logements_actifs: int = 0
    nb_logements_occupes: int = 0
    revenu_mensuel_part: float = 0.0  # revenu × ownership_pct
    valeur_part: Optional[float] = None
    balance_hyp_part: Optional[float] = None


class EntrepriseImmobilierSummary(BaseModel):
    """KPIs immobilier consolidés pour une entreprise propriétaire."""
    entreprise_id: int
    nb_immeubles: int = 0
    nb_logements_actifs: int = 0
    nb_logements_occupes: int = 0
    taux_occupation: float = 0.0
    revenu_mensuel_part: float = 0.0
    revenu_annuel_part: float = 0.0
    valeur_portefeuille_part: float = 0.0
    balance_hypothecaire_part: float = 0.0
    equity_part: float = 0.0  # valeur - balance
    immeubles: List[EntrepriseImmobilierImmeubleItem] = Field(default_factory=list)
