# Render Cron Jobs — Configuration

Ce projet utilise plusieurs scripts Python qui doivent tourner périodiquement
sur Render. Aucun cron n'est configuré automatiquement (Render ne lit pas
de `render.yaml` dans ce repo) — il faut les créer manuellement dans le
Dashboard Render.

## Comment créer un cron sur Render

1. **Render Dashboard** → New → Cron Job
2. **Name** : `rental-scrape-daily` (ou autre)
3. **Region** : même région que ton service backend
4. **Branch** : `main`
5. **Build Command** : laisser vide (réutilise l'image du backend)
6. **Schedule** : voir tableau ci-dessous (cron expression UTC)
7. **Command** : voir tableau ci-dessous
8. **Environment** : ajoute les mêmes vars que ton service backend
   (DATABASE_URL, JWT_SECRET, ANTHROPIC_API_KEY si requis…)

## Crons recommandés

| Nom | Schedule (UTC) | Heure locale (EDT) | Command | Pourquoi |
|---|---|---|---|---|
| `rental-scrape-daily` | `0 6 * * *` | 02h00 | `cd ~/project/src/backend && python -m scripts.rental_scrape_daily` | Comparables loyers Kijiji + LesPAC + tentative Centris (à vendre), cleanup > 30j |
| `req-data-freshness` | `0 8 1 * *` | 04h00 le 1er du mois | (manuel) | Rappel mensuel de réimporter le ZIP REQ |
| `mtl-roles-yearly` | `0 8 15 1 *` | 04h00 le 15 janvier | `cd ~/project/src/backend && python -m scripts.import_montreal_roles` | Le rôle MTL est publié vers le 15 janvier |

## Crons existants (pas dans le scope rental)

| Nom | Schedule | Command | Source |
|---|---|---|---|
| `seo-daily` | `0 11 * * *` | `python -m app.jobs.seo_daily` | `app/jobs/seo_daily.py` |
| `sales-task-reminders` | `0 13 * * 1-5` | `python -m app.jobs.sales_task_reminders` | `app/jobs/sales_task_reminders.py` |
| `follow-up-reminders` | `0 13 * * *` | `python -m app.jobs.follow_up_reminders` | `app/jobs/follow_up_reminders.py` |
| `unassigned-day-alerts` | `0 21 * * 0-4` | `python -m app.jobs.unassigned_day_alerts` | la veille en fin de journée |
| `soumission-reminders` | `0 13 * * 1-5` | `python -m app.jobs.soumission_reminders` | nudge clients |
| `teams-sync-auto` | `0 * * * *` | `python -m app.jobs.teams_sync_auto` | capture auto des transcriptions Teams (toutes les heures) |
| `loyer-relances` | `0 13 * * 1-5` | `python -m app.jobs.loyer_relances` | rappel cloche des loyers en retard du mois |

## Tester localement avant de déployer

Tous les scripts sont auto-suffisants. En local :

```bash
cd backend
DATABASE_URL=postgres://localhost/h2 \
JWT_SECRET=dev-secret \
python -m scripts.rental_scrape_daily
```

## Lancer manuellement depuis Render Shell

Sans avoir à attendre le prochain cron :

```bash
cd ~/project/src/backend
python -m scripts.rental_scrape_daily
```

## Coût Render

Les Cron Jobs sur Render Free tier :
- ~750 minutes/mois inclus
- `rental_scrape_daily` prend ~10 min × 30 jours = 300 min/mois
- Largement dans les limites

Sur le plan payant : ~7 $ /mois par worker continu. Les crons restent
gratuits dans le quota.
