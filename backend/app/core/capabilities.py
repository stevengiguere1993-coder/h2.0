"""Registre des capacités configurables (permissions gérables depuis
Paramètres → Permissions).

Chaque capacité a un **rôle minimum requis par défaut** = le comportement
actuellement codé en dur. Ce défaut est semé dans la table
``role_permissions`` au démarrage (idempotent, ne réécrase jamais un choix
de l'owner). L'owner peut ensuite ajuster le rôle minimum depuis l'UI, et le
garde ``require_capability`` le lit dynamiquement.

⚠️ Ne déclarer ici QUE des capacités effectivement branchées sur un endpoint
via ``require_capability("<id>")`` — sinon la grille afficherait un
interrupteur sans effet. Ajouter une capacité = 1 entrée ici + brancher
l'endpoint correspondant. Les 4 rôles hiérarchiques (owner>admin>manager>
employee) restent le socle ; « qui peut » = seuil (rôle minimum).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.user import ROLE_RANK

#: Rôles valides, du plus bas au plus haut (pour l'UI + validation).
ROLES_ASCENDING = ["employee", "manager", "admin", "owner"]


@dataclass(frozen=True)
class Capability:
    """Une action dont le rôle minimum requis est configurable."""

    id: str
    label: str
    description: str
    category: str
    default_min_role: str


#: Catalogue des capacités configurables. Démarre par les ACTIONS SENSIBLES
#: (choix de Phil) ; l'accès aux pôles viendra dans un second temps.
CAPABILITIES: list[Capability] = [
    Capability(
        id="project.delete",
        label="Supprimer un projet",
        description=(
            "Effacer définitivement un projet de construction (action "
            "destructive, irréversible côté utilisateur)."
        ),
        category="Projets",
        default_min_role="manager",
    ),
    # Sous-entités de projet. Défauts = comportement actuel (phase/tâche
    # étaient sans garde de rôle = employé ; membre = gestionnaire).
    Capability(
        id="project.phase.delete",
        label="Supprimer une phase de projet",
        description="Effacer une phase d'un projet.",
        category="Projets",
        default_min_role="employee",
    ),
    Capability(
        id="project.task.delete",
        label="Supprimer une tâche de projet",
        description="Effacer une tâche d'un projet.",
        category="Projets",
        default_min_role="employee",
    ),
    Capability(
        id="project.member.remove",
        label="Retirer un membre d'un projet",
        description="Retirer un membre de l'équipe assignée à un projet.",
        category="Projets",
        default_min_role="manager",
    ),
    Capability(
        id="contrat_gestion.delete",
        label="Supprimer un contrat de gestion",
        description=(
            "Effacer un contrat de gestion immobilière, y compris un "
            "contrat déjà signé (le PDF signé reste archivé dans Drive)."
        ),
        category="Contrat de gestion",
        default_min_role="manager",
    ),
    Capability(
        id="contrat_gestion.template_edit",
        label="Modifier le modèle de contrat par défaut",
        description=(
            "Éditer le gabarit global de la convention de gestion "
            "(s'applique à tous les immeubles)."
        ),
        category="Contrat de gestion",
        default_min_role="admin",
    ),
    # ─── Gestion immobilière — suppressions destructives / financières.
    # Défaut = « employé » car ces actions étaient jusqu'ici ouvertes à
    # tout utilisateur du volet immobilier (aucun changement au
    # déploiement). Phil peut les remonter (gestionnaire/admin) ici.
    Capability(
        id="immeuble.delete",
        label="Supprimer un immeuble",
        description="Effacer définitivement un immeuble et ses données.",
        category="Gestion immobilière",
        default_min_role="employee",
    ),
    Capability(
        id="logement.delete",
        label="Supprimer un logement",
        description="Effacer une unité locative d'un immeuble.",
        category="Gestion immobilière",
        default_min_role="employee",
    ),
    Capability(
        id="bail.delete",
        label="Supprimer un bail",
        description="Effacer un bail (document financier/légal).",
        category="Gestion immobilière",
        default_min_role="employee",
    ),
    Capability(
        id="locataire.delete",
        label="Supprimer un locataire",
        description="Effacer une fiche locataire.",
        category="Gestion immobilière",
        default_min_role="employee",
    ),
    Capability(
        id="paiement_loyer.delete",
        label="Supprimer un paiement de loyer",
        description="Effacer un paiement de loyer enregistré.",
        category="Gestion immobilière",
        default_min_role="employee",
    ),
    Capability(
        id="hypotheque.delete",
        label="Supprimer une hypothèque",
        description="Effacer un enregistrement d'hypothèque.",
        category="Gestion immobilière",
        default_min_role="employee",
    ),
    Capability(
        id="depense.delete",
        label="Supprimer une dépense d'immeuble",
        description="Effacer une dépense (impacte le P&L de l'immeuble).",
        category="Gestion immobilière",
        default_min_role="employee",
    ),
    Capability(
        id="evaluation.delete",
        label="Supprimer une évaluation",
        description="Effacer une évaluation de valeur d'immeuble.",
        category="Gestion immobilière",
        default_min_role="employee",
    ),
    # ─── Facturation & envois de documents aux clients. Défaut = « employé »
    # car ces actions étaient jusqu'ici ouvertes à tout utilisateur connecté
    # (CurrentUser). Aucun changement au déploiement ; Phil peut les remonter
    # (gestionnaire/admin) depuis Paramètres → Permissions.
    Capability(
        id="facture.send",
        label="Envoyer une facture au client",
        description="Envoyer une facture par courriel (PDF joint) à un client.",
        category="Facturation & envois",
        default_min_role="employee",
    ),
    Capability(
        id="bon.send",
        label="Envoyer un bon de travail pour signature",
        description=(
            "Envoyer un bon de travail au client (PDF + lien de signature "
            "en ligne)."
        ),
        category="Facturation & envois",
        default_min_role="employee",
    ),
    Capability(
        id="project.to_facture",
        label="Facturer un projet",
        description=(
            "Créer une facture à partir d'un projet (report des heures "
            "pointées en lignes de facture)."
        ),
        category="Facturation & envois",
        default_min_role="employee",
    ),
    # ─── Feuille de temps (Gestion d'entreprise) — permissions v2
    # (2026-07-24). Défauts « gestionnaire » = comportement actuel
    # (_is_manager inline remplacé par la garde configurable).
    Capability(
        id="timesheet.approve",
        label="Approuver une feuille de temps",
        description=(
            "Approuver la feuille soumise d'un employé (déclenche les "
            "soldes de paie et de refacturation)."
        ),
        category="Feuille de temps",
        default_min_role="manager",
    ),
    Capability(
        id="timesheet.reopen",
        label="Rouvrir une feuille soumise/approuvée",
        description=(
            "Remettre une feuille de temps en brouillon pour correction."
        ),
        category="Feuille de temps",
        default_min_role="manager",
    ),
    Capability(
        id="timesheet.delete",
        label="Supprimer une feuille de temps",
        description="Effacer définitivement une feuille de temps.",
        category="Feuille de temps",
        default_min_role="manager",
    ),
    Capability(
        id="timesheet.facturer_qbo",
        label="Facturer la refacturation (QuickBooks)",
        description=(
            "Créer la facture QuickBooks du solde de refacturation "
            "d'une compagnie."
        ),
        category="Feuille de temps",
        default_min_role="manager",
    ),
    # ─── Facturation immobilière (page Facturation du locatif).
    Capability(
        id="frais_gestion.facturer",
        label="Créer une facture de frais de gestion",
        description=(
            "Créer la facture QuickBooks des frais de gestion / "
            "relocation / frais manuels d'un propriétaire."
        ),
        category="Facturation immobilière",
        default_min_role="manager",
    ),
    Capability(
        id="frais_gestion.delete",
        label="Décocher une facture de gestion",
        description=(
            "Supprimer une ligne facturée (la transaction redevient à "
            "facturer) — après suppression de la facture dans QuickBooks."
        ),
        category="Facturation immobilière",
        default_min_role="manager",
    ),
    # ─── Envois & QuickBooks transverses. Défauts = comportement actuel
    # (soumission/QBO étaient ouverts à tout utilisateur connecté ;
    # contrat de gestion exigeait gestionnaire).
    Capability(
        id="soumission.send",
        label="Envoyer une soumission au client",
        description=(
            "Envoyer une soumission de construction par courriel (PDF + "
            "lien de signature)."
        ),
        category="Facturation & envois",
        default_min_role="employee",
    ),
    Capability(
        id="contrat_gestion.send",
        label="Envoyer un contrat de gestion pour signature",
        description=(
            "Envoyer la convention de gestion immobilière aux parties "
            "pour signature en ligne."
        ),
        category="Contrat de gestion",
        default_min_role="manager",
    ),
    Capability(
        id="qbo.push",
        label="Pousser vers QuickBooks",
        description=(
            "Créer/pousser des factures et dépenses dans QuickBooks "
            "depuis les fiches (constructions, achats, soumissions)."
        ),
        category="Facturation & envois",
        default_min_role="employee",
    ),
    # ─── Gestion d'entreprise. ⚠️ Défaut « admin » : la suppression
    # d'une entreprise n'avait AUCUN garde de rôle (volet seulement) —
    # verrou volontaire (permissions v2).
    Capability(
        id="entreprise.delete",
        label="Supprimer une entreprise",
        description=(
            "Effacer une entreprise du QG (fiches, tâches et historique "
            "associés)."
        ),
        category="Gestion d'entreprise",
        default_min_role="admin",
    ),
    # ─── Accès à des pôles/pages sensibles (remplace les listes d'emails
    # codées en dur côté client — P-05d). Défaut « admin » = comportement
    # actuel (l'accès était owner/admin + quelques emails). Exposé au front
    # via un flag calculé dans /auth/me (pas de garde d'endpoint ici).
    Capability(
        id="telephonie.access",
        label="Accéder au pôle Téléphonie",
        description=(
            "Voir et utiliser la console d'appels (Communications / "
            "Téléphonie)."
        ),
        category="Accès aux pôles",
        default_min_role="admin",
    ),
    Capability(
        id="devlog.access",
        label="Accéder à la page Dev / outils",
        description="Voir la page interne de développement / outils (/dev).",
        category="Accès aux pôles",
        default_min_role="admin",
    ),
]

CAPABILITIES_BY_ID: dict[str, Capability] = {c.id: c for c in CAPABILITIES}


def is_valid_role(role: str) -> bool:
    return role in ROLE_RANK
