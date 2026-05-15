"""Seed canonique du groupe — 6 pôles, rôles, tâches.

Crée la structure complète de l'organigramme à partir du document
« Les six pôles de l'entreprise » validé par le propriétaire :

  01 Construction          — Rénovation résidentielle et multilogement
  02 Développement IA      — Solutions logicielles et automatisation
  03 Gestion immobilière   — Locataires, immeubles, optimisation
  04 Acquisition           — Sourcing, analyse et fermeture de deals
  05 Gestion d'entreprise  — Vision, stratégie et opérations
  06 Comptabilité          — Tenue de livres et fonctions fiscales

**Idempotent et additif** : ne supprime jamais rien. Pour chaque nœud
attendu, on cherche un nœud existant avec le même `parent_id` + `label`
(comparaison insensible à la casse / aux accents) : s'il existe, on le
réutilise et on continue à seeder ses enfants. Sinon, on le crée. Les
nœuds déjà en place (ceux du seed `/seed-default` historique) sont
donc préservés ; on enrichit par-dessus.

Marquage Kratos : chaque tâche éligible à l'« adjoint virtuel » a son
`execution_tier="adjoint_virtuel"`. Les tâches CEO ont
`execution_tier="direction"`. Les tâches d'un poste à pourvoir ont
`execution_tier="adjoint"`.

Mes ajouts (tâches que le propriétaire n'avait pas listées) portent un
préfixe `💡` dans la description pour distinction visuelle.
"""

from typing import List, Optional

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.entreprise import Entreprise
from app.models.org_node import OrgNode
from app.schemas.org_node import OrgNodeRead


router = APIRouter(prefix="/org-nodes", tags=["org-nodes-seed-canonical"])


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _norm(s: Optional[str]) -> str:
    s = (s or "").strip().lower()
    for a, b in (
        ("é", "e"), ("è", "e"), ("ê", "e"), ("ë", "e"),
        ("à", "a"), ("â", "a"), ("ä", "a"),
        ("î", "i"), ("ï", "i"),
        ("ô", "o"), ("ö", "o"),
        ("ù", "u"), ("û", "u"), ("ü", "u"),
        ("ç", "c"),
    ):
        s = s.replace(a, b)
    return s


# --------------------------------------------------------------------------
# Structure canonique
#
# Chaque nœud est un dict :
#   label        : str (label du nœud)
#   kind         : str (dept | role | task | service)
#   tier         : str | None  (direction | adjoint | adjoint_virtuel)
#   note         : str | None  (description ; préfixe "💡" = proposition)
#   owner        : str | None  (assignee_external_name suggéré)
#   ent_match    : list[str] | None (noms à matcher pour entreprise_id,
#                  seulement utile sur les top-level dept)
#   children     : list[dict]
# --------------------------------------------------------------------------


# Légende des marqueurs de tâches dans la note :
KRATOS_NOTE = "🤖 Éligible Kratos — automatisable."
PROPOSAL_PREFIX = "💡 Proposition Claude — à valider. "
HIRE_NOTE = "🪑 Poste à pourvoir."

# Pour économiser la verbosité, helpers de construction.
def task(
    label: str,
    *,
    tier: Optional[str] = None,
    note: Optional[str] = None,
    state: Optional[str] = None,
    state_note: Optional[str] = None,
) -> dict:
    return {
        "label": label,
        "kind": "task",
        "tier": tier,
        "note": note,
        "owner": None,
        "ent_match": None,
        "state": state,
        "state_note": state_note,
        "children": [],
    }


def role(
    label: str,
    *,
    owner: Optional[str] = None,
    tier: Optional[str] = "adjoint",
    note: Optional[str] = None,
    children: Optional[list] = None,
) -> dict:
    return {
        "label": label,
        "kind": "role",
        "tier": tier,
        "owner": owner,
        "note": note,
        "ent_match": None,
        "state": None,
        "state_note": None,
        "children": children or [],
    }


def dept(label: str, *, ent_match: Optional[List[str]] = None, children: Optional[list] = None, note: Optional[str] = None) -> dict:
    return {
        "label": label,
        "kind": "dept",
        "tier": None,
        "owner": None,
        "note": note,
        "ent_match": ent_match,
        "state": None,
        "state_note": None,
        "children": children or [],
    }


# Helper short-form pour les tâches couvertes par le portail —
# pré-remplit state=fait et state_note. C'est l'audit Phase 3 :
# qu'est-ce qui est DÉJÀ construit dans le portail.
def done(label: str, where: str, **kwargs) -> dict:
    return task(label, state="fait", state_note=f"✓ {where}", **kwargs)


# --------------------------------------------------------------------------
# 6 pôles canoniques
# --------------------------------------------------------------------------

CANONICAL_STRUCTURE: List[dict] = [
    # ════════════════════════════════════════════════════════════════
    # PÔLE 01 — CONSTRUCTION
    # ════════════════════════════════════════════════════════════════
    dept(
        "Construction",
        ent_match=["Construction", "MGV Construction", "Horizon Construction", "Horizon Rénovations"],
        note="Rénovation résidentielle et multilogement — du lead au chantier fermé.",
        children=[
            role(
                "Closer",
                tier="adjoint",
                note=HIRE_NOTE + " KPI : taux de conversion · valeur vendue · délai de suivi. Rémunération : salaire + commission.",
                children=[
                    task("Trouver des leads"),
                    task("Qualifier les leads"),
                    task("Gérer ses leads"),
                    task("Entrer en contact avec le client"),
                    task("Effectuer le suivi des clients"),
                    task("Identifier les besoins des clients"),
                    done("Prendre rendez-vous avec le client", "Module Agenda /app/agenda"),
                    done("Prise de photos sur place", "Mobile /m/ (capture photos)"),
                    done("Prise de mesures sur place", "Mobile /m/measurements"),
                    done("Saisir l'information dans Kratos", "Module Kratos · Cerveau"),
                    done("Préparer les soumissions", "/app/soumissions (numérotation auto + items)"),
                    done("Effectuer le suivi des soumissions", "Kanban statuts /app/soumissions"),
                    task("Valider les soumissions avec le chargé de projet (en attendant l'autonomie complète)"),
                    task("Gérer les extras avant chantier (si applicable)"),
                    done("Préparer le contrat", "/app/contrats (PDF + envoi)"),
                    done("Faire signer le contrat", "Signature électronique /app/contrats"),
                    task("Transmettre le dossier fermé au chargé de projet"),
                    # Mes propositions
                    task("Préparer la trousse de vente (brochure, photos avant/après, témoignages)", note=PROPOSAL_PREFIX + "Outil de closing — réutilisable pour chaque pôle."),
                    # Tâches Kratos
                    task("Relancer automatiquement les leads froids (30/60/90 jours)", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Envoyer confirmation + itinéraire avant RDV", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Générer la soumission préliminaire à partir du template + mesures", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Relancer les soumissions envoyées (7 et 14 jours)", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Générer le contrat à partir du template", tier="adjoint_virtuel", note=KRATOS_NOTE),
                ],
            ),
            role(
                "Chargé de projet",
                owner="Employé en place (à promouvoir)",
                tier="adjoint",
                note="KPI : respect du budget · échéancier · satisfaction client. Rémunération : salaire + bonus de performance.",
                children=[
                    done("Ouvrir le projet dans le système", "/app/projets (conversion soumission → projet)"),
                    done("Planifier les chantiers", "/app/projets/{id}/agenda"),
                    task("Organiser ses équipes"),
                    task("Demander les permis"),
                    task("Aviser la RBQ"),
                    done("Gérer les fournisseurs", "/app/fournisseurs"),
                    done("Gérer les sous-traitants", "/app/sous-traitants"),
                    done("Gérer le staff", "/app/employes"),
                    task("Acheter le matériel"),
                    done("Faire les bons de commande (PO)", "/app/po (numérotation auto + QBO)"),
                    done("Effectuer le suivi des chantiers", "Kanban /app/projets (5 colonnes)"),
                    task("Gérer les extras et changements"),
                    task("Gérer les imprévus"),
                    task("Gérer les garanties et déficiences"),
                    task("Assurer la communication avec le client pendant le chantier"),
                    done("Gérer les budgets", "/app/projets/{id}/finances"),
                    done("Approuver les dépenses", "/app/achats (statut received/paid)"),
                    done("Suivre les coûts", "/app/projets/{id}/finances"),
                    task("Suivre les échéanciers"),
                    done("Approuver les factures", "/app/facturation + sync QBO"),
                    done("Transmettre les pièces à la comptabilité", "Sync QBO automatique sur factures + achats"),
                    task("Assurer la satisfaction client"),
                    task("Fermer le projet"),
                    # Mes propositions
                    task("Captation systématique de témoignages clients à la fermeture", note=PROPOSAL_PREFIX + "Devient matériel marketing réutilisable."),
                    task("Suivi garantie post-projet (3 mois et 12 mois)", note=PROPOSAL_PREFIX + "Réduit les déficiences non détectées."),
                    task("Onboarding nouveau sous-traitant (RBQ, CNESST, assurance)", note=PROPOSAL_PREFIX + "Vérification documentaire avant 1er chantier."),
                    # Tâches Kratos
                    task("Alertes deadlines RBQ / CNESST automatiques", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Classement automatique photos avant/après depuis l'app mobile", tier="adjoint_virtuel", note=KRATOS_NOTE),
                ],
            ),
            role(
                "Sous-traitants",
                owner="Externes — payés au contrat",
                tier=None,
                children=[
                    task("Exécuter les travaux"),
                    task("Respecter les échéanciers"),
                    task("Respecter les normes de qualité"),
                    task("Communiquer avec le chargé de projet"),
                ],
            ),
            role(
                "Employés (heures)",
                owner="Internes — payés à l'heure",
                tier=None,
                children=[
                    task("Exécuter les travaux"),
                    task("Respecter les échéanciers"),
                    task("Respecter les normes de qualité"),
                    task("Communiquer avec le chargé de projet"),
                    task("Entretenir les outils et l'équipement"),
                ],
            ),
            role(
                "CEO Construction",
                tier="direction",
                note="Owner — supervise l'ensemble.",
                children=[
                    task("Développer l'entreprise", tier="direction"),
                    task("Générer de nouveaux leads", tier="direction"),
                    task("Bâtir le réseau de sous-traitants", tier="direction"),
                    task("Superviser le closer et le chargé de projet", tier="direction"),
                    done("Vérifier la facturation", "Dashboard /app/facturation", tier="direction"),
                    task("Valider les paies", tier="direction"),
                    task("Vérifier le suivi de la qualité", tier="direction"),
                    task("Gérer la performance des équipes", tier="direction"),
                    task("Recruter du nouveau personnel", tier="direction"),
                    task("Gérer la conformité RBQ (cours, suivis)", tier="direction"),
                    task("Maintenir la conformité CNESST à jour", tier="direction"),
                    # Mes propositions
                    task("Veille concurrentielle (prix matériaux, updates RBQ)", tier="direction", note=PROPOSAL_PREFIX + "Hebdomadaire — protège la marge."),
                ],
            ),
        ],
    ),

    # ════════════════════════════════════════════════════════════════
    # PÔLE 02 — DÉVELOPPEMENT IA / LOGICIEL
    # ════════════════════════════════════════════════════════════════
    dept(
        "Développement IA",
        ent_match=["Développement", "Dev logiciel", "MGV Développement", "MC", "Horizon Dev"],
        note="Solutions logicielles, automatisation et livraison de produits.",
        children=[
            role(
                "Closer",
                tier="adjoint",
                note=HIRE_NOTE + " KPI : conversion · valeur vendue · délai de suivi. Rémunération : salaire + commission.",
                children=[
                    done("Trouver des leads", "/dev-logiciel/leads (CRM kanban)"),
                    done("Qualifier les leads", "/dev-logiciel/leads"),
                    done("Gérer le pipeline de ventes", "Kanban /dev-logiciel/leads"),
                    task("Entrer en contact avec les clients"),
                    task("Comprendre les besoins du client"),
                    task("Définir le scope du projet"),
                    task("Organiser les appels découverte"),
                    task("Préparer les démos et présentations"),
                    task("Faire les estimations préliminaires"),
                    done("Préparer les soumissions", "/dev-logiciel/soumissions"),
                    done("Effectuer le suivi des soumissions", "Kanban /dev-logiciel/soumissions"),
                    task("Négocier les contrats"),
                    task("Faire signer les contrats"),
                    done("Transmettre le dossier complet au chargé de projet", "Conversion lead → client + projet"),
                    task("Assurer la relation client avant le kickoff"),
                    task("Identifier les opportunités d'upsell"),
                    # Mes propositions
                    task("Suivi NPS post-livraison + détection upsell", note=PROPOSAL_PREFIX + "Source #1 de revenus récurrents."),
                    # Tâches Kratos
                    task("Questionnaire découverte automatique envoyé au lead", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Soumission préliminaire à partir d'un brief", tier="adjoint_virtuel", note=KRATOS_NOTE),
                ],
            ),
            role(
                "Chargé de projet",
                tier="adjoint",
                note=HIRE_NOTE + " KPI : budget · échéancier · satisfaction. Salaire + bonus.",
                children=[
                    task("Organiser le kickoff client"),
                    done("Créer le planning du projet", "/dev-logiciel/projets"),
                    task("Décomposer les tâches techniques"),
                    task("Assigner les tâches aux sous-traitants"),
                    task("Gérer les développeurs, designers et QA"),
                    done("Suivre l'avancement des tâches", "Kanban /dev-logiciel/projets (5 colonnes)"),
                    task("Gérer les échéanciers"),
                    done("Gérer les budgets et les heures", "/dev-logiciel/heures (saisie + total)"),
                    task("Prioriser les demandes"),
                    done("Maintenir Kratos à jour", "Module Kratos · Cerveau"),
                    task("Valider les livrables avant livraison"),
                    task("Tester les fonctionnalités principales"),
                    task("Gérer les changements de scope"),
                    task("Coordonner les mises en production"),
                    task("Gérer les urgences et les bugs critiques"),
                    task("Effectuer les suivis clients"),
                    task("Gérer les changements de besoin des clients"),
                    task("Assurer la satisfaction client"),
                    # Mes propositions
                    task("Documentation client à la livraison (manuel utilisateur)", note=PROPOSAL_PREFIX + "Réduit le support post-livraison."),
                    task("Gestion accès et permissions par client (sécurité)", note=PROPOSAL_PREFIX + "Indispensable B2B."),
                    task("Bibliothèque de templates réutilisables (composants, prompts)", note=PROPOSAL_PREFIX + "Capitalise sur chaque projet."),
                    # Tâches Kratos
                    task("Générer la doc client à partir des features livrées", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Alertes Slack/email sur bugs critiques", tier="adjoint_virtuel", note=KRATOS_NOTE),
                ],
            ),
            role(
                "Sous-traitants (devs / designers / QA)",
                owner="Externes — au contrat",
                tier=None,
                children=[
                    task("Développer les fonctionnalités"),
                    task("Corriger les bugs"),
                    task("Respecter les standards de code"),
                    task("Respecter les échéanciers"),
                    task("Communiquer les blocages rapidement"),
                    task("Documenter leur travail"),
                    task("Participer aux meetings nécessaires"),
                    task("Effectuer les tests techniques"),
                    task("Déployer les changements selon le processus établi"),
                    task("Faire les revues de code (si applicable)"),
                ],
            ),
            role(
                "CEO Dev IA",
                tier="direction",
                children=[
                    task("Développer la vision de l'entreprise", tier="direction"),
                    task("Trouver des partenariats stratégiques", tier="direction"),
                    task("Bâtir le réseau de contacts", tier="direction"),
                    task("Superviser le closer et le chargé de projet", tier="direction"),
                    task("Optimiser les processus internes", tier="direction"),
                    task("Gérer la croissance de l'entreprise", tier="direction"),
                    task("Recruter les talents clés", tier="direction"),
                    task("Vérifier la rentabilité des projets", tier="direction"),
                    task("Vérifier la qualité des livrables", tier="direction"),
                    task("Gérer les finances globales", tier="direction"),
                    task("Décider des orientations technologiques", tier="direction"),
                    task("Gérer les relations importantes (clients, investisseurs)", tier="direction"),
                    task("Développer la marque de l'entreprise", tier="direction"),
                    # Mes propositions
                    task("Veille technologique (sorties modèles, frameworks)", tier="direction", note=PROPOSAL_PREFIX + "Hebdomadaire."),
                ],
            ),
        ],
    ),

    # ════════════════════════════════════════════════════════════════
    # PÔLE 03 — GESTION IMMOBILIÈRE
    # ════════════════════════════════════════════════════════════════
    dept(
        "Gestion immobilière",
        ent_match=["Gestion Immo", "Gestion immobilière", "MGV Gestion"],
        note="Locataires, immeubles et optimisation du parc.",
        children=[
            role(
                "Gestionnaire immobilier",
                tier="adjoint",
                note=HIRE_NOTE + " " + PROPOSAL_PREFIX + "Poste manquant — remplace le « tout le reste » vague des sous-traitants gestion.",
                children=[
                    task("Tenir le registre des baux + avis 60/90 jours", note=PROPOSAL_PREFIX),
                    task("Réponse 24/7 aux urgences locataires (dispatch)", note=PROPOSAL_PREFIX),
                    task("Inspections annuelles obligatoires (alarme/CO/extincteurs)", note=PROPOSAL_PREFIX),
                    task("Optimisation énergétique des immeubles (audit annuel)", note=PROPOSAL_PREFIX),
                    task("Veille réglementaire TAL / Loi 31 / Régie", note=PROPOSAL_PREFIX),
                    # Tâches Kratos
                    done("Alertes automatiques retards de loyer", "Module loyers — alertes déjà branchées", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Génération avis (augmentation, renouvellement) à partir de templates", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Dispatch des urgences locataires (formulaire → notification)", tier="adjoint_virtuel", note=KRATOS_NOTE),
                ],
            ),
            role(
                "Sous-traitants gestion (Kyle / Kario)",
                owner="2 entreprises de gestion sous contrat",
                tier=None,
                children=[
                    task("Exécuter l'ensemble des travaux d'entretien et de gestion courante"),
                ],
            ),
            role(
                "CEO Gestion immobilière",
                tier="direction",
                note="KPI à ajouter : taux d'occupation · délai moyen de relocation · dépense d'entretien par porte · marge nette par immeuble.",
                children=[
                    done("S'assurer que les loyers rentrent", "Module loyers + alertes retards", tier="direction"),
                    task("Vérifier les vacances", tier="direction"),
                    task("S'assurer des augmentations de loyer", tier="direction"),
                    task("Gérer l'optimisation du parc", tier="direction"),
                    task("Suivi hebdomadaire des sous-traitants", tier="direction"),
                    task("Suivi de l'entretien des immeubles", tier="direction"),
                    task("Approuver certains travaux", tier="direction"),
                    # Mes propositions
                    task("Définir KPI mensuels du parc (occupation, relocation, marge)", tier="direction", note=PROPOSAL_PREFIX),
                ],
            ),
        ],
    ),

    # ════════════════════════════════════════════════════════════════
    # PÔLE 04 — ACQUISITION
    # ════════════════════════════════════════════════════════════════
    dept(
        "Acquisition",
        ent_match=["Prospection", "Acquisition", "Aguci", "Dev Immo"],
        note="Sourcing, analyse, due diligence et fermeture des deals immobiliers.",
        children=[
            role(
                "Prospecteur interne",
                owner="Zach (futur bras droit — voir pôle 05)",
                tier="adjoint",
                note="Rémunération : salaire + commission. À terme, sera promu Bras droit (pôle 05) ; ses tâches prospection passent au prospecteur externe / courtiers.",
                children=[
                    done("Trouver des leads", "Volet /prospection (carte + listes)"),
                    done("Faire des routes", "/prospection (carte) + /m/prospection (drive-by)"),
                    done("Faire du porte-à-porte", "Mobile /m/prospection (capture terrain)"),
                    task("Faire des cold calls"),
                    done("Établir le premier contact", "/prospection/leads"),
                    done("Qualifier les leads", "/prospection/leads (kanban)"),
                    task("Identifier la motivation du vendeur"),
                    task("Recueillir les informations de base"),
                    done("Faire les suivis avec les vendeurs", "/prospection/leads"),
                    task("Obtenir les documents préliminaires"),
                    task("Relancer les vendeurs"),
                    done("Alimenter Kratos", "Module Kratos · Cerveau"),
                    done("Assurer le suivi des leads", "Kanban /prospection/leads"),
                    task("Transférer les leads qualifiés à l'analyste"),
                    task("Assurer le suivi documentaire avec l'analyste"),
                    # Mes propositions
                    task("Veille off-market (réseaux fiscalistes, successions, courtiers)", note=PROPOSAL_PREFIX),
                    task("Carnet de visites partagé (immeubles vus / à revisiter)", note=PROPOSAL_PREFIX),
                ],
            ),
            role("Prospecteur externe", owner="Externes — commission", tier=None, children=[
                task("Envoyer des leads qualifiés à l'analyste"),
                task("Effectuer tout le travail en amont (qualification, documentation, suivi vendeur)"),
            ]),
            role("Courtiers immobiliers", owner="Externes — contrat", tier=None, children=[
                task("Envoyer des leads qualifiés à l'analyste"),
                task("Effectuer tout le travail en amont (qualification, documentation, suivi vendeur)"),
            ]),
            role("Courtier hypothécaire", owner="Externe — contrat", tier=None, children=[
                task("Gérer tout ce qui concerne le financement"),
                task("Vérifier les scénarios de l'analyste"),
            ]),
            role(
                "Analyste",
                tier="adjoint",
                note=HIRE_NOTE + " À pourvoir quand volume de deals le justifie. KPI à ajouter : nombre de deals analysés · taux d'offres acceptées · rendement projeté vs réalisé.",
                children=[
                    done("Analyse financière des deals", "/prospection/analyse + /prospection/analyses-leads"),
                    task("Analyse des loyers et optimisation"),
                    done("Analyse de rentabilité", "/prospection/analyse (modèle financier)"),
                    task("Analyse du marché"),
                    task("Validation des hypothèses"),
                    task("Préparation des modèles financiers"),
                    task("Préparation des scénarios"),
                    task("Communication avec les prospecteurs internes/externes"),
                    task("Communication avec les courtiers"),
                    task("Suivi des leads"),
                    task("Vérification des documents"),
                    task("Gestion du data room"),
                    task("Suivi des échéanciers transactionnels"),
                    task("Alimenter Kratos"),
                    task("Présentation des opportunités aux investisseurs et au CEO"),
                    # Mes propositions
                    task("Modèle financier standardisé versionné (template)", note=PROPOSAL_PREFIX + "Réutilisable, comparable d'un deal à l'autre."),
                    task("Suivi post-acquisition (KPI projection vs réalisé à 6/12 mois)", note=PROPOSAL_PREFIX),
                    # Tâches Kratos
                    task("Alertes nouveaux listings correspondant aux critères", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    done("Calcul automatique cap rate / IRR à partir d'un brief", "/prospection/analyse — calculs auto", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Data room — checklist automatique des documents manquants", tier="adjoint_virtuel", note=KRATOS_NOTE),
                ],
            ),
            role(
                "Investisseurs",
                owner="Les 3 propriétaires",
                tier="direction",
                children=[
                    task("Définir la stratégie d'acquisition", tier="direction"),
                    task("Visiter les immeubles", tier="direction"),
                    task("Participer aux inspections", tier="direction"),
                    task("Participer aux négociations", tier="direction"),
                    task("Faire les offres d'achat", tier="direction"),
                    task("Faire les contre-offres", tier="direction"),
                    task("Autoriser les conditions", tier="direction"),
                    task("Faire les due diligences", tier="direction"),
                    task("Vérifier le zonage", tier="direction"),
                    task("Vérifier l'urbanisme", tier="direction"),
                    task("Vérifier la stratégie de sortie", tier="direction"),
                    task("Vérifier les risques majeurs", tier="direction"),
                    task("Monter la stratégie du projet", tier="direction"),
                    task("Valider les budgets travaux", tier="direction"),
                    task("Obtenir des soumissions", tier="direction"),
                    task("Rencontrer les professionnels", tier="direction"),
                    task("Valider les projections financières", tier="direction"),
                    task("Trouver des investisseurs ou partenaires", tier="direction"),
                    task("Superviser la transition vers la gestion", tier="direction"),
                    task("Alimenter Kratos", tier="direction"),
                ],
            ),
            role(
                "CEO Acquisition",
                tier="direction",
                children=[
                    task("Développer le réseau stratégique", tier="direction"),
                    task("Trouver des sources de deals", tier="direction"),
                    task("Développer les relations avec courtiers et prêteurs", tier="direction"),
                    task("Superviser le pipeline d'acquisition", tier="direction"),
                    task("Superviser les analystes", tier="direction"),
                    task("Superviser les investisseurs et partenaires", tier="direction"),
                    task("Valider les acquisitions importantes", tier="direction"),
                    task("Gérer les relations investisseurs", tier="direction"),
                    task("Développer les capitaux", tier="direction"),
                    task("Structurer la croissance du parc immobilier", tier="direction"),
                    task("Développer les systèmes et processus", tier="direction"),
                    task("Gérer les partenariats stratégiques", tier="direction"),
                    task("Développer la vision globale", tier="direction"),
                ],
            ),
            role(
                "Professionnels externes",
                owner="Mandatés au contrat par transaction",
                tier=None,
                children=[
                    task("Notaire — achat des immeubles"),
                    task("Avocat — création des compagnies, conventions d'actionnaires"),
                    task("Inspecteur — rapport d'inspection"),
                    task("Évaluateur — rapport d'évaluation"),
                    task("Étude environnementale — rapport"),
                ],
            ),
        ],
    ),

    # ════════════════════════════════════════════════════════════════
    # PÔLE 05 — GESTION D'ENTREPRISE (transverse)
    # ════════════════════════════════════════════════════════════════
    dept(
        "Gestion d'entreprise",
        ent_match=None,  # Transverse — pas d'entreprise spécifique.
        note="Vision, stratégie, opérations et coordination globale du groupe.",
        children=[
            role(
                "CEO Groupe",
                owner="Les 3 propriétaires",
                tier="direction",
                children=[
                    task("Définir la vision de l'entreprise", tier="direction"),
                    task("Définir les stratégies de croissance", tier="direction"),
                    task("Définir les stratégies financières", tier="direction"),
                    task("Définir les stratégies de refinancement", tier="direction"),
                    task("Définir les stratégies fiscales avec les professionnels", tier="direction"),
                    task("Définir les stratégies d'acquisition", tier="direction"),
                    task("Définir les stratégies d'optimisation du parc", tier="direction"),
                    task("S'assurer du maintien des visions et des stratégies", tier="direction"),
                    task("Superviser la santé financière globale", tier="direction"),
                    task("Analyser les scénarios financiers du parc", tier="direction"),
                    task("Analyser les opportunités de refinancement", tier="direction"),
                    task("Autoriser les financements", tier="direction"),
                    task("Autoriser les investissements majeurs", tier="direction"),
                    task("Superviser les flux de liquidités globaux", tier="direction"),
                    task("Gérer les investisseurs", tier="direction"),
                    task("Entretenir les relations avocats / comptables / fiscalistes", tier="direction"),
                    task("Développer le réseau stratégique", tier="direction"),
                    task("Superviser le bras droit", tier="direction"),
                    task("Superviser l'adjoint administratif", tier="direction"),
                    task("Superviser la comptabilité", tier="direction"),
                    done("Vérifier les KPI des entreprises", "/entreprises/tableaux-de-bord", tier="direction"),
                    task("Vérifier les rapports financiers", tier="direction"),
                    done("Vérifier la mise à jour de Kratos", "Module Kratos · Cerveau", tier="direction"),
                    task("Vérifier les suivis importants", tier="direction"),
                    task("Vérifier les contrats", tier="direction"),
                    task("Développer les systèmes internes", tier="direction"),
                    task("Développer les processus", tier="direction"),
                    task("Développer les SOP", tier="direction"),
                    task("Optimiser l'organisation globale", tier="direction"),
                    task("Gérer Francostaffing (comptabilité)", tier="direction"),
                    # Mes propositions
                    task("Plan de continuité documenté (qui prend quoi si CEO out 2 semaines)", tier="direction", note=PROPOSAL_PREFIX),
                    task("Comité d'investisseurs structuré avant/après acquisitions", tier="direction", note=PROPOSAL_PREFIX),
                ],
            ),
            role(
                "Bras droit",
                owner="Zach (prospecteur à promouvoir — priorité immédiate)",
                tier="adjoint",
                note=PROPOSAL_PREFIX + "Fiche manquante dans le document original. Pivot de la mutualisation des ressources entre les 6 pôles.",
                children=[
                    task("Tenir le rituel hebdomadaire des 6 pôles (lundi 30 min)", note=PROPOSAL_PREFIX),
                    task("Consolider le tableau de bord groupe (KPI cross-entreprises)", note=PROPOSAL_PREFIX),
                    task("Superviser la mutualisation des ressources entre pôles", note=PROPOSAL_PREFIX),
                    task("Maintenir le plan de continuité opérationnel", note=PROPOSAL_PREFIX),
                    task("Suppléant signature pour documents non-corporatifs", note=PROPOSAL_PREFIX),
                    task("Audit interne périodique trimestriel (avec comptable externe)", note=PROPOSAL_PREFIX),
                ],
            ),
            role(
                "Adjoint administratif",
                owner="Mutualisé sur les 6 pôles — à pourvoir (ou fusionner avec Bras droit selon volume)",
                tier="adjoint",
                note="Rémunération : salaire. Sert TOUS les pôles — l'optimisation principale du groupe.",
                children=[
                    task("Gérer les relations avec les banques"),
                    task("Gérer les relations avec la SCHL"),
                    task("Coordonner évaluateur / phases env. / banque / SCHL"),
                    task("Préparer la documentation financière"),
                    task("Ouvrir les comptes bancaires et marges de crédit"),
                    task("Gérer les accès bancaires"),
                    task("Effectuer le suivi des comptes de banque"),
                    task("Vérifier que les cartes de crédit sont payées"),
                    task("Assurer les mises à jour annuelles légales"),
                    task("S'assurer que les états financiers sont faits"),
                    task("Coordonner les comptables"),
                    task("Superviser la refacturation intercompagnies"),
                    task("Vérifier les contrats"),
                    done("Coordonner les signatures", "Signature électronique /app/contrats"),
                    task("Gérer les renouvellements importants"),
                    task("Vérifier les documents corporatifs"),
                    task("Vérifier numéros d'entreprise, ClicSÉQUR, accès gouvernementaux, taxes"),
                    task("Mise à jour documentaire 2x par an"),
                    task("Suivre les refinancements"),
                    task("Suivre les assurances"),
                    task("Suivre les hypothèques"),
                    task("Suivre les renouvellements"),
                    task("Suivre les déclarations"),
                    task("Assurer le maintien de Kratos"),
                    done("Faire les suivis des tâches importantes", "/entreprises/taches"),
                    task("Ouvrir le courrier"),
                    task("Traiter les courriels"),
                    task("Organiser les documents"),
                    task("Classer la documentation"),
                    task("Maintenir le Drive organisé"),
                    task("Numériser les documents"),
                    task("Archiver les documents"),
                    task("Envoyer les documents à la comptabilité"),
                    done("Gérer les calendriers", "Module agenda + sync Google/Apple"),
                    done("Organiser les réunions", "/entreprises/rencontres"),
                    task("Effectuer le suivi des échéances"),
                    task("Faire les relances administratives"),
                    task("Gérer les tâches administratives récurrentes"),
                    # Tâches Kratos — énorme part de l'adjoint administratif est automatisable
                    task("Tri/classement automatique du courrier numérisé", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Réponses-type aux courriels standards", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Saisie automatique dans Kratos depuis pièces jointes", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Alertes contextuelles sur échéances (refi / assurance / hypothèque / taxes)", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    done("Génération comptes-rendus à partir de la dictée des rencontres", "/entreprises/rencontres + dictée + résumer + nettoyer", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Vérification mensuelle cartes de crédit (alertes paiement)", tier="adjoint_virtuel", note=KRATOS_NOTE),
                ],
            ),
            # Mes propositions transverses
            role(
                "Sécurité informatique et conformité Loi 25",
                tier="adjoint",
                note=HIRE_NOTE + " " + PROPOSAL_PREFIX + "Personne désignée aujourd'hui — peut être un contrat externe annuel.",
                children=[
                    task("Veille Loi 25 et obligations annuelles", note=PROPOSAL_PREFIX),
                    task("Audit sécurité des systèmes (Kratos, Drive, accès)", note=PROPOSAL_PREFIX),
                    task("Procédure de gestion d'incident (fuite de données)", note=PROPOSAL_PREFIX),
                    task("Formation annuelle de l'équipe", note=PROPOSAL_PREFIX),
                ],
            ),
            role(
                "Mutualisation entre pôles",
                tier=None,
                note=PROPOSAL_PREFIX + "Checklist transverse — rituels et passages de relais.",
                children=[
                    task("Rituel hebdomadaire des 6 pôles (lundi 30 min, format standard)", note=PROPOSAL_PREFIX),
                    task("Checklist Closer → Chargé de projet (Construction)", note=PROPOSAL_PREFIX),
                    task("Checklist Closer → Chargé de projet (Dev IA)", note=PROPOSAL_PREFIX),
                    task("Checklist Acquisition → Gestion immobilière (post-closing)", note=PROPOSAL_PREFIX),
                    task("Fiche Kratos — qui saisit quoi, à quelle étape, qui valide", note=PROPOSAL_PREFIX),
                ],
            ),
        ],
    ),

    # ════════════════════════════════════════════════════════════════
    # PÔLE 06 — COMPTABILITÉ (service transverse)
    # ════════════════════════════════════════════════════════════════
    dept(
        "Comptabilité",
        ent_match=None,  # Service transverse partagé.
        note="Tenue de livres, fiscalité et gestion financière courante. Sert les 6 pôles.",
        children=[
            role("Fiscaliste", owner="Externe — contrat", tier=None, children=[
                task("Conseiller sur l'ensemble des questions fiscales"),
            ]),
            role("Comptable externe", owner="Externe — contrat", tier=None, children=[
                task("Réaliser la fin d'année financière"),
            ]),
            role(
                "Francostaffing (tenue de livres)",
                owner="Sous-traitant — payé à l'heure",
                tier=None,
                children=[
                    task("Tenue de livres"),
                    task("Comptes payables par compagnie"),
                    task("Comptes recevables par compagnie"),
                    task("Facturation et refacturation"),
                    task("Suivi des paiements clients"),
                    task("Paie des employés et des sous-traitants"),
                    task("Vérification des heures facturables"),
                    task("Gestion des taxes"),
                    task("S'assurer que les loyers sont rentrés aux bonnes places"),
                    # Mes propositions
                    task("Réconciliation bancaire mensuelle", note=PROPOSAL_PREFIX + "À cadencer formellement."),
                    task("Refacturation intercompagnies systématique", note=PROPOSAL_PREFIX + "Mentionné côté adjoint, mais qui exécute ?"),
                    # Tâches Kratos
                    task("Catégorisation automatique des achats depuis Kratos", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Préparation des bordereaux de paie (calcul auto)", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Alertes taxes TPS/TVQ trimestrielles", tier="adjoint_virtuel", note=KRATOS_NOTE),
                    task("Génération automatique des écritures de refacturation intercompagnies", tier="adjoint_virtuel", note=KRATOS_NOTE),
                ],
            ),
        ],
    ),
]


# --------------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------------


class SeedResult(BaseModel):
    created: int
    reused: int
    total: int


@router.post(
    "/seed-poles-canonical",
    response_model=SeedResult,
    status_code=status.HTTP_200_OK,
    summary=(
        "Seed additif et idempotent de la structure canonique des 6 pôles "
        "(Construction, Dev IA, Gestion immobilière, Acquisition, "
        "Gestion d'entreprise, Comptabilité). Réutilise les nœuds "
        "existants par label, n'écrase rien."
    ),
)
async def seed_poles_canonical(
    db: DBSession, _: CurrentUser
) -> SeedResult:
    """Crée la structure complète issue du document de référence du
    propriétaire (6 pôles × rôles × tâches), enrichie des propositions
    Claude. Idempotent : si un nœud avec le même `parent_id` et le
    même `label` existe déjà, il est réutilisé. Les enfants sont seedés
    par-dessus."""
    entreprises_rows = (
        await db.execute(select(Entreprise))
    ).scalars().all()

    def find_ent(candidates: Optional[List[str]]) -> Optional[int]:
        if not candidates:
            return None
        norm_cands = [_norm(c) for c in candidates if c]
        for e in entreprises_rows:
            n = _norm(e.name)
            for c in norm_cands:
                if c and (c in n or n in c):
                    return e.id
        return None

    created = 0
    reused = 0
    total = 0

    async def _seed_children(items: List[dict], parent_id: Optional[int]) -> None:
        nonlocal created, reused, total
        # Position de départ : si parent a déjà des enfants, on continue
        # à la suite.
        existing_siblings = (
            await db.execute(
                select(OrgNode).where(OrgNode.parent_id == parent_id)
            )
        ).scalars().all()
        used_positions = {s.position for s in existing_siblings}
        by_norm_label = {_norm(s.label): s for s in existing_siblings}
        next_pos = (max(used_positions) + 1) if used_positions else 0

        for item in items:
            total += 1
            label = item["label"]
            existing = by_norm_label.get(_norm(label))
            if existing is not None:
                node = existing
                # On enrichit seulement les méta vides — on ne réécrit
                # PAS ce que l'utilisateur a déjà mis manuellement.
                if item.get("tier") and not node.execution_tier:
                    node.execution_tier = item["tier"]
                if item.get("note") and not node.description:
                    node.description = item["note"]
                if item.get("owner") and not (
                    node.assignee_external_name
                    or node.assignee_employe_id
                    or node.assignee_user_id
                ):
                    node.assignee_external_name = item["owner"]
                if item.get("state") and not node.state:
                    node.state = item["state"]
                if item.get("state_note") and not node.state_note:
                    node.state_note = item["state_note"]
                reused += 1
            else:
                ent_id = find_ent(item.get("ent_match"))
                node = OrgNode(
                    parent_id=parent_id,
                    position=next_pos,
                    kind=item["kind"],
                    label=label,
                    description=item.get("note"),
                    entreprise_id=ent_id,
                    assignee_external_name=item.get("owner"),
                    execution_tier=item.get("tier"),
                    state=item.get("state"),
                    state_note=item.get("state_note"),
                )
                db.add(node)
                await db.flush()
                created += 1
                next_pos += 1
            children = item.get("children") or []
            if children:
                await _seed_children(children, node.id)

    await _seed_children(CANONICAL_STRUCTURE, None)
    await db.commit()
    return SeedResult(created=created, reused=reused, total=total)
