"""Registre central des PAGES de Kratos (refonte permissions 2026-07).

Source de vérité unique « qui voit quoi » : chaque page navigable de
l'intranet est déclarée ici avec son pôle (volet), son libellé français,
son seuil de rôle PAR DÉFAUT (= le comportement de la sidebar avant la
refonte → aucun changement visible au déploiement) et les préfixes de
routes frontend qu'elle couvre (fiches [id], sous-pages…).

Trois couches d'autorisation, combinées dans ``access_service`` :
  1. VOLET  — accès au pôle (``User.has_volet``), owner/admin = tous.
  2. PAGE   — seuil de rôle configurable par l'owner (table
              ``role_permissions``, clé ``page:<key>``, fallback ici).
  3. ACTION — capacités (``app.core.capabilities``), inchangées.
Exceptions individuelles par-dessus : ``user_access_overrides``.

Convention de clé : ``<volet>.<slug>`` (ex. ``construction.projets``).
``volet="general"`` = transverse (aucun check de volet, seuil de rôle
seulement). Ajouter une page = 1 entrée ici ; la grille Paramètres →
Permissions, /auth/me et le garde frontend la découvrent tout seuls.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Préfixe des clés de page dans la table role_permissions et le dict
#: ``access`` de /auth/me (``page:construction.projets``).
PAGE_KEY_PREFIX = "page:"

#: Pseudo-volet des pages transverses (pas de check de volet).
GENERAL = "general"

#: Libellés français des volets (UI grille + vue par utilisateur).
VOLET_LABELS: dict[str, str] = {
    "general": "Général",
    "construction": "Construction",
    "entreprises": "Gestion d'entreprise",
    "immobilier": "Gestion immobilière",
    "prospection": "Prospection",
    "investisseur": "Investisseurs",
    "developpement_logiciel": "Développement logiciel",
    "communication": "Téléphonie",
}


@dataclass(frozen=True)
class PageEntry:
    """Une page navigable dont la visibilité est configurable."""

    key: str
    label: str
    volet: str
    default_min_role: str
    #: Préfixes de chemins frontend (sans préfixe de locale) couverts par
    #: cette page — la route elle-même ET ses sous-pages/fiches.
    routes: tuple[str, ...]


def _p(
    key: str, label: str, volet: str, default_min_role: str, *routes: str
) -> PageEntry:
    return PageEntry(
        key=key,
        label=label,
        volet=volet,
        default_min_role=default_min_role,
        routes=tuple(routes),
    )


#: Défauts = comportement AVANT la refonte (minRole des sidebars ; volets des
#: layouts) → aucun changement visible au déploiement. Le matching frontend
#: prend le préfixe de route LE PLUS LONG qui matche le chemin courant ; un
#: chemin sans entrée = non régi (accessible, comportement historique).
PAGES: list[PageEntry] = [
    # ── Général (transverse — pas de volet, seuil de rôle seulement) ──
    _p("general.parametres", "Paramètres", GENERAL, "employee",
       "/parametres", "/app/parametres", "/prospection/parametres",
       "/entreprises/reglages"),
    _p("general.profil", "Mon profil", GENERAL, "employee", "/profil"),
    _p("general.mes_taches", "Mes tâches", GENERAL, "employee",
       "/mes-taches", "/entreprises/taches"),
    _p("general.utilisateurs", "Utilisateurs & rôles", GENERAL, "owner",
       "/app/utilisateurs"),
    # ── Construction ──
    _p("construction.accueil", "Accueil Construction", "construction",
       "employee", "/app"),
    _p("construction.crm", "CRM / Prospects", "construction", "manager",
       "/app/crm"),
    _p("construction.clients", "Clients", "construction", "manager",
       "/app/clients"),
    _p("construction.soumissions", "Soumissions", "construction", "manager",
       "/app/soumissions"),
    _p("construction.cockpit", "Vue d'ensemble", "construction", "manager",
       "/app/cockpit"),
    _p("construction.projets", "Projets", "construction", "employee",
       "/app/projets"),
    _p("construction.agenda", "Agenda", "construction", "employee",
       "/app/agenda"),
    _p("construction.bons_travail", "Bons de travail", "construction",
       "employee", "/app/bons"),
    _p("construction.punch", "Punch / Temps", "construction", "manager",
       "/app/punch"),
    _p("construction.facturation", "Facturation", "construction", "manager",
       "/app/facturation"),
    _p("construction.po", "Bons de commande (PO)", "construction", "manager",
       "/app/po"),
    _p("construction.achats", "Achats / dépenses", "construction", "manager",
       "/app/achats"),
    _p("construction.assignations", "Assignations", "construction",
       "manager", "/app/assignations"),
    _p("construction.conges", "Vacances & congés", "construction", "manager",
       "/app/conges"),
    _p("construction.employes", "Employés", "construction", "admin",
       "/app/employes"),
    _p("construction.sous_traitants", "Sous-traitants", "construction",
       "admin", "/app/sous-traitants"),
    _p("construction.fournisseurs", "Fournisseurs", "construction", "admin",
       "/app/fournisseurs"),
    _p("construction.services_catalogue", "Catalogue de services",
       "construction", "manager", "/app/services-catalogue"),
    _p("construction.templates_courriels", "Templates de courriels",
       "construction", "manager", "/app/templates-courriels"),
    _p("construction.relances", "Relances automatiques", "construction",
       "manager", "/app/relances"),
    _p("construction.mobile", "App mobile staff", "construction", "employee",
       "/m"),
    # ── Prospection ──
    _p("prospection.carte", "Carte", "prospection", "employee",
       "/prospection"),
    _p("prospection.aujourdhui", "Aujourd'hui", "prospection", "employee",
       "/prospection/aujourdhui"),
    _p("prospection.agenda", "Agenda Prospection", "prospection", "employee",
       "/prospection/agenda"),
    _p("prospection.leads", "Suivi de leads", "prospection", "employee",
       "/prospection/leads"),
    _p("prospection.analyses", "Analyses des leads", "prospection",
       "employee", "/prospection/analyses-leads"),
    _p("prospection.pipeline", "Pipeline", "prospection", "employee",
       "/prospection/pipeline"),
    _p("prospection.moyenne_locative", "Moyenne locative", "prospection",
       "employee", "/prospection/moyenne-locative"),
    _p("prospection.roles_fonciers", "Rôles fonciers", "prospection",
       "employee", "/prospection/immeubles-mtl"),
    _p("prospection.listes", "Listes (segments)", "prospection", "employee",
       "/prospection/lists"),
    _p("prospection.dashboard", "Dashboard Prospection", "prospection",
       "employee", "/prospection/dashboard"),
    _p("prospection.driveby", "Drive-by (mobile)", "prospection", "employee",
       "/m/prospection"),
    # ── Gestion immobilière ──
    _p("immobilier.vue_ensemble", "Vue d'ensemble locative", "immobilier",
       "employee", "/immobilier"),
    _p("immobilier.immeubles", "Immeubles", "immobilier", "employee",
       "/immobilier/immeubles"),
    _p("immobilier.logements", "Logements", "immobilier", "employee",
       "/immobilier/logements"),
    _p("immobilier.locataires", "Locataires", "immobilier", "employee",
       "/immobilier/locataires"),
    _p("immobilier.baux", "Baux & paiements", "immobilier", "employee",
       "/immobilier/baux"),
    _p("immobilier.locations", "Locations (relocation)", "immobilier",
       "employee", "/immobilier/locations"),
    _p("immobilier.finances", "Finances locatives", "immobilier", "employee",
       "/immobilier/finances"),
    _p("immobilier.renouvellements", "Renouvellements", "immobilier",
       "employee", "/immobilier/renouvellements"),
    _p("immobilier.depots", "Dépôts de garantie", "immobilier", "employee",
       "/immobilier/depots"),
    _p("immobilier.bons_travail", "Bons de travail (locatif)", "immobilier",
       "employee", "/immobilier/bons-travail"),
    # ── Gestion d'entreprise (comportement actuel : owner/admin + volet) ──
    _p("entreprises.accueil", "Entreprises", "entreprises", "admin",
       "/entreprises"),
    _p("entreprises.dashboards", "Tableaux de bord", "entreprises", "admin",
       "/entreprises/dashboards"),
    _p("entreprises.kratos", "Kratos · Cerveau", "entreprises", "admin",
       "/entreprises/kratos"),
    _p("entreprises.rencontres", "Rencontres", "entreprises", "admin",
       "/entreprises/rencontres"),
    _p("entreprises.feuille_de_temps", "Feuille de temps", "entreprises",
       "admin", "/entreprises/feuille-de-temps"),
    _p("entreprises.organigramme", "Organigramme", "entreprises", "admin",
       "/entreprises/organigramme"),
    _p("entreprises.distribution_taches", "Distribution des tâches",
       "entreprises", "admin", "/entreprises/distribution-taches"),
    _p("entreprises.vision", "Vision & stratégie", "entreprises", "admin",
       "/entreprises/vision"),
    _p("entreprises.comparatif", "Comparatif", "entreprises", "admin",
       "/entreprises/comparatif"),
    _p("entreprises.projets", "Projets (entreprises)", "entreprises",
       "admin", "/entreprises/projets"),
    _p("entreprises.contacts", "Contacts", "entreprises", "admin",
       "/entreprises/contacts"),
    _p("entreprises.abonnements", "Abonnements", "entreprises", "admin",
       "/entreprises/abonnements"),
    # ── Investisseurs ──
    _p("investisseur.portefeuille", "Mon portefeuille", "investisseur",
       "employee", "/investisseur"),
    # ── Développement logiciel (comportement actuel : owner/admin) ──
    _p("devlogiciel.accueil", "Accueil Dev logiciel",
       "developpement_logiciel", "admin", "/dev-logiciel"),
    _p("devlogiciel.crm", "CRM Dev", "developpement_logiciel", "admin",
       "/dev-logiciel/leads"),
    _p("devlogiciel.soumissions", "Soumissions Dev",
       "developpement_logiciel", "admin", "/dev-logiciel/soumissions"),
    _p("devlogiciel.contrats", "Contrats Dev", "developpement_logiciel",
       "admin", "/dev-logiciel/contrats"),
    _p("devlogiciel.clients", "Clients Dev", "developpement_logiciel",
       "admin", "/dev-logiciel/clients"),
    _p("devlogiciel.projets", "Projets Dev", "developpement_logiciel",
       "admin", "/dev-logiciel/projets"),
    _p("devlogiciel.agenda", "Agenda Dev", "developpement_logiciel", "admin",
       "/dev-logiciel/agenda"),
    _p("devlogiciel.heures", "Heures Dev", "developpement_logiciel", "admin",
       "/dev-logiciel/heures"),
    _p("devlogiciel.sous_traitants", "Sous-traitants Dev",
       "developpement_logiciel", "admin", "/dev-logiciel/sous-traitants"),
    _p("devlogiciel.facturation", "Facturation Dev",
       "developpement_logiciel", "admin", "/dev-logiciel/facturation"),
    # ── Téléphonie (une app à sections internes — une seule entrée) ──
    _p("communication.telephonie", "Téléphonie", "communication", "admin",
       "/telephonie"),
]

PAGES_BY_KEY: dict[str, PageEntry] = {p.key: p for p in PAGES}
