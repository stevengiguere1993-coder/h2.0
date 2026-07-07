"""Catalogue statique des automatisations — SOURCE DE VÉRITÉ unique.

Chaque entrée décrit une automatisation du portail : sa clé stable
(`key`), son libellé, sa catégorie, son déclencheur (cron + horaire, ou
événement), et une description courte. L'état dynamique (activé/coupé,
dernière exécution) est fusionné à l'exécution depuis la base
(`automation_settings` + `cron_runs`).

Pour ajouter une automatisation au registre : une ligne ici. Les jobs
cron lisent leur `key` via `is_automation_enabled(key)` (fail-open).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Category = Literal["relance", "rapport", "synchro", "courriel", "telephonie"]
Trigger = Literal["cron", "evenement"]


@dataclass(frozen=True)
class Param:
    """Paramètre éditable d'une automatisation (rendu en input dans le hub)."""
    key: str
    label: str
    type: Literal["int"]
    default: int
    help: str = ""


@dataclass(frozen=True)
class Automation:
    key: str
    label: str
    category: Category
    trigger: Trigger
    # Horaire cron lisible (None pour les automatisations événementielles).
    schedule: str | None
    description: str
    # True = on/off pris en charge en v1 (jobs cron câblés au garde-fou).
    controllable: bool = True
    # Paramètres éditables depuis le hub (lus par le job, fail-safe).
    params: tuple[Param, ...] = field(default_factory=tuple)


# NB : `key` des jobs cron = nom du module dans app/jobs/ → sert aussi à
# retrouver la dernière exécution dans `cron_runs` quand le job y écrit.
CATALOG: tuple[Automation, ...] = (
    # ---- Relances / rappels ----
    Automation(
        "follow_up_reminders", "Relances de suivi", "relance", "cron",
        "Toutes les heures",
        "Relance automatique des suivis (leads / contacts) arrivés à échéance.",
    ),
    Automation(
        "facture_reminders", "Rappels de factures", "relance", "cron",
        "Tous les jours · 02:00 UTC (matin)",
        "Courriel de rappel aux clients pour les factures impayées / à échéance.",
        params=(
            Param(
                "cadence_days", "Cadence des rappels (jours)", "int", 4,
                "Délai entre deux rappels pour une même facture en retard.",
            ),
        ),
    ),
    Automation(
        "devlog_facture_reminders", "Rappels factures (Dév. logiciel)",
        "relance", "cron", "Tous les jours · 09h30",
        "Rappels de factures pour le volet développement logiciel.",
    ),
    Automation(
        "soumission_reminders", "Rappels de soumissions", "relance", "cron",
        "Quotidien",
        "Relance les clients dont la soumission est en attente de réponse.",
        params=(
            Param(
                "cadence_days", "Relancer après (jours)", "int", 5,
                "Nombre de jours sans réponse avant d'envoyer la relance.",
            ),
        ),
    ),
    Automation(
        "appointment_reminders", "Rappels de rendez-vous", "relance", "cron",
        "Quotidien",
        "Rappel automatique des rendez-vous / visites à venir.",
    ),
    Automation(
        "sales_task_reminders", "Rappels de tâches de vente", "relance",
        "cron", "Quotidien",
        "Rappelle aux closers leurs tâches de vente en attente.",
    ),
    # ---- Rapports / alertes ----
    Automation(
        "kratos_problems_daily", "Rapport problèmes Kratos", "rapport",
        "cron", "Tous les jours · 06h00",
        "Synthèse quotidienne des problèmes détectés dans le portail Kratos.",
    ),
    Automation(
        "unassigned_day_alerts", "Alertes journées non assignées", "rapport",
        "cron", "Quotidien",
        "Alerte quand des journées de chantier n'ont personne d'assigné.",
    ),
    Automation(
        "devlog_weekly_client_report", "Rapport client hebdo (Dév.)",
        "rapport", "cron", "Hebdomadaire",
        "Envoi du rapport d'avancement hebdomadaire aux clients logiciel.",
    ),
    Automation(
        "devlog_nps_dispatch", "Envoi NPS (Dév. logiciel)", "rapport",
        "cron", "Périodique",
        "Envoie les sondages de satisfaction (NPS) aux clients logiciel.",
    ),
    Automation(
        "seo_daily", "SEO quotidien", "rapport", "cron",
        "Tous les jours · 07h00",
        "Tâches SEO automatiques (contenu / indexation) du site public.",
    ),
    # ---- Synchros ----
    Automation(
        "ical_sync_all", "Synchro calendriers iCal", "synchro", "cron",
        "Périodique",
        "Synchronise les calendriers iCal externes avec l'agenda.",
    ),
    Automation(
        "teams_meeting_sync", "Synchro réunions Teams", "synchro", "cron",
        "Périodique",
        "Importe les réunions Microsoft Teams dans le portail.",
    ),
    Automation(
        "punch_auto_close", "Fermeture auto des punchs", "synchro", "cron",
        "Tous les jours · 22h00",
        "Ferme automatiquement les punchs d'employés laissés ouverts.",
    ),
    # ---- Courriels événementiels (informational en v1) ----
    Automation(
        "welcome_email", "Courriel de bienvenue", "courriel", "evenement",
        None,
        "Envoyé automatiquement à la création d'un compte / client.",
        controllable=False,
    ),
    Automation(
        "contact_request_mail", "Accusé de demande de contact", "courriel",
        "evenement", None,
        "Confirmation envoyée quand un prospect remplit le formulaire de contact.",
        controllable=False,
    ),
    Automation(
        "appointment_mail", "Confirmation de rendez-vous", "courriel",
        "evenement", None,
        "Invitation calendrier (.ics) + courriel à la prise / réassignation d'un RDV.",
        controllable=False,
    ),
    # ---- Téléphonie / Léa (réglée dans le volet Téléphonie) ----
    Automation(
        "voice_secretary", "Secrétaire IA (Léa)", "telephonie", "evenement",
        None,
        "Décroche, qualifie et route les appels. Réglée dans Téléphonie → Numéros.",
        controllable=False,
    ),
    Automation(
        "voice_lead_callback", "Rappel auto des leads", "telephonie",
        "evenement", None,
        "Rappel automatique des leads manqués. Réglé dans Téléphonie → Numéros.",
        controllable=False,
    ),
)

CATALOG_BY_KEY = {a.key: a for a in CATALOG}
