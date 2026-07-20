"""Schemas Pydantic pour les extensions immobilier (TAL forms,
renouvellements automatiques, vue par entreprise propriétaire)."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Formulaires TAL ──────────────────────────────────────────────────


class TalFormType(BaseModel):
    code: str
    label: str
    description: str
    #: True = formulaire OFFICIEL du TAL (PDF gouvernemental rempli).
    officiel: bool = False
    #: False = envoi par simple courriel avec PDF joint, sans signature.
    signature_requise: bool = True
    #: True = lettre maison dont le TEXTE est éditable (gabarit).
    texte_modifiable: bool = False
    #: PDF modèle remplacé par l'utilisateur (imm_doc_templates).
    custom_filename: Optional[str] = None
    custom_uploaded_at: Optional[datetime] = None


class TalFormRequest(BaseModel):
    """Paramètres optionnels pour générer un PDF.

    Si non fournis, on utilise les valeurs courantes du bail / locataire /
    immeuble. Permet à l'utilisateur de saisir un nouveau loyer / nouvelle
    date sans modifier le bail courant.
    """
    # avis_modification (TAL-806) — une des 3 formes de hausse
    modif_mode: Optional[str] = Field(default=None, max_length=24)
    nouveau_loyer: Optional[float] = Field(default=None, ge=0)
    hausse_montant: Optional[float] = Field(default=None, ge=0)
    hausse_pct: Optional[float] = Field(default=None, ge=0, le=100)
    nouvelle_date_debut: Optional[date] = None
    nouvelle_date_fin: Optional[date] = None
    motif: Optional[str] = None  # « Autre(s) modification(s) »

    # rappel_paiement (avis de retard — paiement immédiat)
    montant_du: Optional[float] = Field(default=None, ge=0)
    mois_concerne: Optional[date] = None

    # avis_non_reconduction (TAL-807 — avis du locataire)
    depart_date: Optional[date] = None

    # avis_reprise (TAL-809, art. 1960 C.c.Q.)
    reprise_date: Optional[date] = None
    reprise_beneficiaire: Optional[str] = Field(default=None, max_length=255)
    reprise_lien: Optional[str] = Field(default=None, max_length=255)

    # avis_travaux_majeurs (TAL-808, art. 1922-1923 C.c.Q.)
    travaux_description: Optional[str] = None
    travaux_date_debut: Optional[date] = None
    travaux_duree_valeur: Optional[str] = Field(default=None, max_length=16)
    travaux_duree_unite: Optional[str] = Field(default=None, max_length=16)
    travaux_evacuation: bool = False
    travaux_evacuation_du: Optional[date] = None
    travaux_evacuation_au: Optional[date] = None
    travaux_indemnite: Optional[float] = Field(default=None, ge=0)
    travaux_conditions: Optional[str] = None

    # avis_acces (art. 1931-1933 C.c.Q.)
    acces_date: Optional[date] = None
    acces_plage: Optional[str] = Field(default=None, max_length=128)
    acces_motif: Optional[str] = Field(default=None, max_length=500)

    # reponse_cession (TAL-828, art. 1871 / 1978.2 C.c.Q.)
    cession_decision: Optional[str] = Field(default=None, max_length=16)
    cession_date: Optional[date] = None
    cession_accepte: bool = True  # héritage (anciens documents)
    cession_motif_refus: Optional[str] = None


# ─── Renouvellement workflow ──────────────────────────────────────────


class EnvoyerRenouvellementRequest(BaseModel):
    """Déclenchement manuel d'un avis de renouvellement pour un bail.

    L'utilisateur peut spécifier la hausse soit en valeur absolue
    (`nouveau_loyer`), soit en pourcentage du loyer courant
    (`hausse_pct`), soit en montant additionnel (`hausse_montant`). Si
    plusieurs sont fournis, `nouveau_loyer` prime > `hausse_pct` >
    `hausse_montant`.

    `request_read_receipt=True` ajoute la demande d'accusé de lecture
    Microsoft Graph + envoie une copie BCC à l'expéditeur pour archive.
    Vaut « envoi certifié » dans la pratique courante (preuve d'envoi
    + accusé de lecture du locataire).
    """
    nouveau_loyer: Optional[float] = Field(default=None, ge=0)
    hausse_pct: Optional[float] = Field(default=None, ge=-50, le=200)
    hausse_montant: Optional[float] = Field(default=None, ge=-2000, le=5000)
    nouvelle_date_debut: Optional[date] = None
    nouvelle_date_fin: Optional[date] = None
    motif: Optional[str] = None
    force: bool = False
    request_read_receipt: bool = False
    bcc_to_sender: bool = True


class EnvoyerRenouvellementResult(BaseModel):
    renouvellement_id: int
    courriel_envoye: bool
    avis_envoye_le: date
    nouveau_loyer: Optional[float] = None
    nouvelle_date_debut: Optional[date] = None
    nouvelle_date_fin: Optional[date] = None


class RenouvellementOverview(BaseModel):
    """Item d'aperçu pour la page Renouvellements (liste).

    Joint le bail + logement + locataire + dernier renouvellement
    en un seul aller-retour.
    """
    model_config = ConfigDict(from_attributes=True)

    bail_id: int
    immeuble_id: int
    immeuble_name: str
    logement_id: Optional[int] = None
    logement_numero: str
    locataire_id: Optional[int] = None
    locataire_nom: str
    locataire_email: Optional[str] = None
    bail_date_fin: date
    bail_loyer_mensuel: float
    jours_avant_fin: int
    fenetre: str  # "imminente" | "a_envoyer" | "envoye" | "hors_fenetre"
    avis_envoye_le: Optional[date] = None
    nouveau_loyer: Optional[float] = None
    renouvellement_status: Optional[str] = None
    # Suivi du DOCUMENT d'avis (TAL-806 conservé dans imm_documents) :
    # envoyé → ouvert (1re consultation du lien) → signé.
    avis_doc_envoye_le: Optional[datetime] = None
    avis_doc_ouvert_le: Optional[datetime] = None
    avis_doc_signed_at: Optional[datetime] = None


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
