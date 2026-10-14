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

## Catalogue de matériaux

Le mega-cron `all-daily` inclut `materiaux-prix` : relevé quotidien des prix chez les détaillants pour toute offre avec lien produit non vérifiée depuis 20 h (rabais et date de fin compris).

**Job de nuit hebdomadaire** (`materiaux-hebdo-nuit`, 2026-10-01) : lancé par le mega-cron `all-hourly` la première heure entre 02:00 et 05:59 (Montréal) où le dernier run date de plus de 6 jours (verrou `cron_runs`). Enchaîne : relevé COMPLET de toutes les offres avec lien (rabais et dates de fin), recherche des prix de base manquants (jusqu'à 300 couples), alertes de rabais, puis analyse IA de l'historique 6 mois par matériau (verdict bon moment / attendre, tendance, fréquence des rabais, prix cible → `materiaux.analyse_ia`, lu par le catalogue et le plan d'achat des projets). Rien à configurer dans cron-job.org tant que `all-hourly` tourne. Forcer : `POST /api/v1/cron/run/materiaux-hebdo?secret=…` (`&wait=true` pour attendre la fin). État : `GET /api/v1/materiaux/prix/analyser/etat`.

## Connexions QuickBooks gardées vivantes (dans le méga-cron `all-daily`, 2026-10-09)

Sous-job `qbo-connexions-vivantes`, avant les autres jobs QuickBooks du
jour : le jeton de chaque connexion enregistrée (Construction,
`qbo_tokens` id=1, et chaque ligne de `qbo_connections`) est renouvelé.
Intuit périme un refresh token inutilisé environ 100 jours : aucune
connexion n'expire donc faute d'usage. Une connexion qu'Intuit refuse
(`invalid_grant`) est marquée « à reconnecter » (`reconnect_required_at`,
badge rouge et bouton « Reconnecter » dans Paramètres → Comptabilité) puis
sautée jusqu'à la reconnexion. Restent hors de portée de Kratos : la durée
maximale de 5 ans d'une autorisation Intuit et une déconnexion faite
depuis QuickBooks. Le jeton de référence est TOUJOURS celui de la base,
relu sous verrou de ligne à chaque renouvellement (incident 2026-10-09 :
un 2e client faisait tourner le jeton dans le dos du client partagé).

## Reçus QuickBooks → Drive (dans le méga-cron `all-daily`, 2026-10-04)

Sous-job `qbo-recus-drive` : pour chaque entreprise dont la compagnie
QuickBooks est connectée (scope `inc:{entreprise_id}`) et dont la fiche a
un dossier Drive, les reçus (pièces jointes image/PDF) de DÉPENSES
AJOUTÉS OU MODIFIÉS dans QuickBooks depuis 2 jours (quelle que soit la
date du reçu) sont copiés dans
`<Drive entreprise>/Factures/<année>/<MM - Mois>/AAAA-MM-JJ Fournisseur 2134,02$.ext`
(fournisseur absent → « ND » ; pièce sans dépense liée → son MOIS par date de
dépôt, nommée `AAAA-MM-JJ <nom d'origine>` ; seule une pièce sans aucune date
va dans `Factures/<année>/Non classé`, au même niveau que les mois — Steven
2026-10-04 : « mettre les factures dans le mois même si le prix ou le
fournisseur n'est pas là »).
À chaque run, AVANT la copie, reclassement du Drive : les anciens « À classer »
sont vidés (fichier daté → son mois, sans date → « Non classé ») puis mis à la
corbeille, les fichiers datés de « Non classé » rejoignent leur mois, les mois
sans chiffre devant sont renommés (« 09 - Septembre »). Chaque déplacement est
noté dans le rapport et dans la mémoire (`detail`). Une entreprise qui a un
dossier Drive mais pas de connexion QuickBooks est reclassée aussi (sans copie).
Un reçu copié « brut » puis rattaché à une dépense est renommé avec elle, pas
recopié (recopié seulement si le fichier brut n'est plus dans le Drive) ;
« Annuler cet import » rétablit alors son nom d'origine au lieu de le jeter.
Anti-doublon : table `qbo_recus_drive` + même nom déjà présent dans le
dossier du mois. Rattrapage / simulation / « Reclasser » : page Paramètres →
Drive → « Reçus QuickBooks → Drive » (`POST /api/v1/qbo-recus-drive/executer`,
`POST /api/v1/qbo-recus-drive/reclasser`).

