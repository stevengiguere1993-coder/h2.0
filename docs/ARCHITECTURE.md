# Architecture Kratos

> **Quoi** : Kratos est la plateforme interne (intranet) du groupe Horizon, servie sous le domaine
> **immohorizon.com**. Elle couvre 6+ pôles d'activité (Construction, Prospection immobilière,
> Gestion locative, Dev logiciel, Gestion d'entreprise/QG, Investisseurs) plus un site public SEO,
> une PWA mobile terrain et une téléphonie IA (« Léa »).
>
> **Stack** : backend **FastAPI async** (SQLAlchemy 2 + asyncpg) sur **Postgres Render** ·
> frontend **Next.js 15 + Tailwind + next-intl** (fr/en) · **extension navigateur Chrome MV3**
> (scraping assisté) · **VPS de scraping Hetzner** (FastAPI + Playwright) · intégrations
> QuickBooks Online, Microsoft Graph, Twilio, Stripe, Google Drive, cascade IA Gemini→Anthropic→Groq.
>
> **Date du document** : 2026-07-06 (généré à partir d'une cartographie du repo en 8 zones).

---

## 1. Vue d'ensemble (diagramme)

```
        ┌───────────────────────────┐      ┌─────────────────────────────┐
        │ Navigateur desktop        │      │ PWA mobile                  │
        │ · site public SEO         │      │ · /m (terrain, bottom-nav)  │
        │ · portails internes       │      │ · /mes-taches (cartes Keep) │
        │   /app /prospection       │      │ · /telephonie (softphone)   │
        │   /immobilier /entreprises│      └──────────────┬──────────────┘
        └──────────────┬────────────┘                     │
                       │ HTTPS                            │
                       ▼                                  ▼
        ┌──────────────────────────────────────────────────────────────┐
        │ FRONTEND Next.js 15 — Render « h2-0-web » (Node 20, free)    │
        │ next-intl fr/en · rewrite /api/* → backend (same-origin,     │
        │ zéro CORS pour le portail) · pages publiques à token         │
        └──────────────────────────────┬───────────────────────────────┘
                                       │ /api/v1/*  (authedFetch, JWT Bearer)
   ┌───────────────────┐               ▼
   │ Extension Chrome  │  X-Extension-Key   ┌───────────────────────────────┐
   │ MV3 (montreal.ca, ├───────────────────►│ API FastAPI — Render « h2-0 » │
   │ centris.ca)       │ /api/v1/extension/*│ /api/v1/* (~150 routers)      │
   └───────────────────┘                    │ /mcp/{key} (serveur MCP)      │
   ┌───────────────────┐  X-Cron-Secret     └───────┬───────────┬───────────┘
   │ GitHub Actions    ├───────────────────────────►│           │
   │ cron-jobs.yml     │ POST /api/v1/cron/run/*    │           ▼
   │ keep-alive.yml    │ (+ cron-job.org all-daily/ │   ┌───────────────┐
   └───────────────────┘        all-hourly)         │   │ Postgres      │
   ┌───────────────────┐                            │   │ (Render)      │
   │ Crons Render      │  python -m app.jobs.<job>  │   │ 178 tables    │
   │ (dashboard +      ├───────────────────────────►│   └───────────────┘
   │  render.yaml)     │                            │
   └───────────────────┘                            ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │ INTÉGRATIONS EXTERNES (sortantes et webhooks entrants)             │
   │ · QuickBooks Online (OAuth2, push/pull, webhook signé)             │
   │ · Microsoft Graph (mail info@, rencontres Teams + transcripts)     │
   │ · Twilio (voix Léa, ~15 webhooks TwiML signés, SDK WebRTC)         │
   │ · IA : cascade Gemini → Anthropic → Groq (+ Groq Whisper)          │
   │ · Google Drive (OAuth par user, conventions de dossiers)           │
   │ · Stripe (Checkout factures devlog, webhook signé)                 │
   │ · Meta Lead Ads (webhook), Banque du Canada, Nominatim, ORS        │
   │ · VPS Hetzner scraper.immohorizon.com (Playwright headed + Xvfb,   │
   │   X-API-Key) : EvalWeb / Centris / Numeriq                         │
   └────────────────────────────────────────────────────────────────────┘
```

---

## 2. Flux de déploiement

**Push sur `main` → prod**, sans clone local :

1. `.github/workflows/deploy.yml` : à chaque push sur `main`, POST des **Render Deploy Hooks**
   (`RENDER_DEPLOY_HOOK_URL` = backend **h2-0**, `_WEB` optionnel = frontend **h2-0-web**).
   Le fichier `.render-trigger` sert à forcer un redeploy.
2. Render build : backend `pip install -r requirements.txt` + `Aptfile` (tesseract-ocr, poppler)
   puis `uvicorn app.main:app` (healthcheck `/health`, sans BDD) ; frontend build Next.js
   (heap plafonné ~460 Mo, plan free, `images unoptimized`).
3. Au boot backend, le **lifespan** lie le port immédiatement (contrainte Render « no open ports »)
   puis lance en tâche de fond `_run_startup_tasks` : `init_db` → `ensure_critical_columns` →
   5 `ensure_*_tables` → backfills → 3 seeders Drive → bootstrap Twilio — chaque étape best-effort.

**CI** — `.github/workflows/ci.yml` :
- `frontend-typecheck` (**tsc**) : **seul job bloquant**.
- lint frontend : informatif (`continue-on-error`).
- `backend-tests` (`pytest -q`, Python 3.11, env factice) : informatif également — 6 fichiers de
  tests purs (moteurs financiers, parseurs). Le build Next a `ignoreBuildErrors` +
  `ignoreDuringBuilds` : la CI est le seul garde-fou.

**Crons — 4 mécanismes concurrents** (⚠️ voir Incohérences §10.2) :

| Mécanisme | Où | Jobs |
|---|---|---|
| Blueprint `render.yaml` (racine) | déclare h2-0, h2-0-web + **6 crons** `python -m app.jobs.<module>` | seo-daily (11:00 UTC), facture-reminders (12:30), devlog-facture-reminders (13:30), follow-up-reminders (horaire), punch-auto-close (03:00), kratos-problems-daily (10:00) |
| Crons Render **manuels** (dashboard) | documentés dans `RENDER_CRONS.md` — qui affirme que Render **ne lit pas** render.yaml | rental-scrape-daily (06:00), sales-task-reminders, soumission-reminders, teams-sync-auto (horaire), loyer-relances, unassigned-day-alerts, seo-daily, follow-up-reminders |
| GitHub Actions `cron-jobs.yml` | 02:00 UTC quotidien + `workflow_dispatch` — `curl POST /api/v1/cron/run/*` avec header **X-Cron-Secret** | unassigned-day-alerts, follow-up-reminders, facture-reminders, appointment-reminders |
| Mega-crons HTTP `cron_runner.py` | ~16 endpoints `POST /api/v1/cron/run/*` (X-Cron-Secret ou `?secret=`), pensés pour **cron-job.org** | `all-daily` (11 sous-jobs, claim 6h) et `all-hourly` (sync calendriers, dédup achats/factures, pulls + autopush QBO) |

`keep-alive.yml` pingue `/health` + `immohorizon.com` toutes les 10 min contre les cold starts du
free tier. L'anti-doublon `claim_cron_run` (upsert Postgres atomique) ne couvre **que** le chemin
HTTP `/cron/run/*` — pas les crons Render `python -m`.

---

## 3. Structure des dossiers

```
backend/
  app/
    main.py               # Entrée FastAPI : CORS, montage /api/v1 + MCP, lifespan (startup best-effort)
    api/
      deps.py             # Guards JWT (CurrentUser, RequireManager/AdminRole/AdminOrOwner/Owner, CurrentAdmin legacy)
      api_key_deps.py     # Auth clés API krts_ (SHA-256, scopes par pôle)
      v1/router.py        # Agrégateur ~150 include_router — ORDRE d'enregistrement sensible
      v1/endpoints/       # ~140 fichiers, un par ressource REST (de 32 à 5482 lignes)
    models/               # 130 modules SQLAlchemy = 178 tables (déclaratif 2.0, quasi sans relationship())
    schemas/              # 24 fichiers Pydantic seulement — la majorité des DTOs vit inline dans les endpoints
    services/             # 116 fichiers : logique métier, moteurs financiers, 13 générateurs PDF + 1 PPTX
    repositories/         # 6 fichiers « textbook » (Client/Project/User/ContactRequest + GenericCrud) — à moitié orphelins
    jobs/                 # 16 jobs cron (cibles python -m ou appelés par cron_runner)
    integrations/         # ~30 clients externes : ai/ (cascade), quickbooks, email_graph, voice/ (Twilio/Léa),
                          #   rental/ (Kijiji/LesPAC), roles_evaluation/ (MTL/provincial), req, cmhc, centris…
    automations/          # catalog.py : registre statique des 19 automatisations (hub /automations)
    core/                 # config (pydantic-settings), security (JWT/bcrypt), permissions, taxes, finance_math
    db/                   # base.py (Base + mixins) et session.py (3018 lignes : engine + MIGRATION MAISON + seeds)
    scripts/              # CLI bootstrap (create_admin, twilio_bootstrap, monday_migrate)
    templates/            # PPTX offre d'investissement (horizon_v1/v2 + mapping JSON)
    assets/               # logo.png, mgv_signature.png (embarqués dans les PDF)
  scripts/                # 2e package de CLI one-shot (imports Monday, rôles fonciers, REQ, rental_scrape_daily)
  alembic/                # Scaffolding complet mais versions/ VIDE — Alembic inactif
  tests/                  # 6 fichiers de tests purs (finance, devis, TRI, plexflow) — exécutés en CI

frontend/
  src/
    app/[locale]/         # Site public SEO (racine, piliers, renovation/[service]/[city], blog)
                          # + portails : app/ (Construction+admin), prospection/, immobilier/,
                          #   entreprises/ (QG), dev-logiciel/, m/ (PWA), mes-taches/, telephonie/
                          # + pages publiques à token : bon/, facture/, contrat-signature/,
                          #   promesse-achat/, devlog/{nps,pay-invoice,sign-soumission}, sign-*/
    components/           # 82 composants partagés (répertoire PLAT, 34 300 lignes, tous pôles mélangés)
    lib/                  # auth.ts (authedFetch = hub API), api.ts, blog.ts, tax.ts, task-config.ts…
    i18n/                 # routing.ts (pathnames fr/en), navigation.ts, request.ts
    hooks/                # use-current-user.ts
  messages/{fr,en}.json   # i18n du site vitrine SEULEMENT (le portail est hardcodé FR)
  public/                 # sw.js + 3 manifests PWA (app, /mes-taches, /telephonie), icônes

browser-extension/        # Chrome MV3 « Horizon h2.0 Helper » : content-evalweb.js, content-centris.js,
                          #   background.js → POST /api/v1/extension/* (X-Extension-Key)
scraping_vps/             # FastAPI + Playwright sur VPS Hetzner (Docker, Xvfb, Chrome headed) :
                          #   /scrape/{evalweb-owners,centris-search,centris-detail,numeriq-comparables} (X-API-Key)
render.yaml               # Blueprint Render racine (h2-0, h2-0-web, 6 crons) — voir contradiction RENDER_CRONS.md
RENDER_CRONS.md, DEPLOYMENT.md, CLAUDE.md, docs/  # Docs opérationnelles
```

---

## 4. Modules par pôle

> Neuf « pôles » ressortent de la cartographie : core/infra, construction, prospection,
> immobilier/locatif, devlog, gestion d'entreprise (QG), public/SEO, mobile, plus une famille
> transverse (« multi » : agenda, Drive, téléphonie, contacts). **Aucun module « courtage » dédié
> n'existe dans le repo** — le plus proche est le volet Investisseur (`investissements.py`,
> `inv_*`) et les promesses d'achat côté Prospection.

### 4.1 Core / infra (transverse)

| Chemin | Rôle |
|---|---|
| `backend/app/main.py` | Entrée FastAPI, CORS, montage api_router + MCP (double : `/mcp/{key}` et `/api/v1/mcp/{key}`), lifespan startup best-effort |
| `backend/app/core/config.py` | Settings pydantic-settings (env + .env, singleton lru_cache) |
| `backend/app/core/security.py` | Bcrypt + JWT HS256 (create/verify/decode) |
| `backend/app/core/permissions.py` | Visibilité par rôle : `visible_project_ids` / `visible_immeuble_ids` (None = tout voir pour manager+) |
| `backend/app/db/session.py` | Engine async, `get_db` (commit auto), **et tout le moteur de migration maison** (§6) |
| `backend/app/api/deps.py` + `api_key_deps.py` | Guards JWT + clés API (§7) |
| endpoints `auth, users, user_roles, api_keys, audit, notifications, push, search, dashboard, help, kratos, automations, ai, copilote, cron_runner` | Comptes, rôles fonctionnels, clés krts_, journal d'audit, cloche, WebPush, recherche globale, KPIs, bouton Aide (cascade IA), routeur d'intentions Kratos, hub automatisations, déclencheurs cron HTTP |
| endpoints `drive_auth, drive_files, drive_conventions, drive_auto_uploads, drive_page_modules` | Intégration Google Drive (OAuth par user, navigation, conventions de dossiers, auto-upload des PDF) |
| endpoints `qbo_oauth, qbo_token, qbo_account_map, qbo_bulk, qbo_webhook` | Plomberie QuickBooks (OAuth, tokens, mapping comptes, migration de masse, webhook) |
| services `audit, notifications, secret_vault, welcome_email, changelog_audit, cron_guard, entity_serializers, api_capabilities, numbering` | Helpers transverses : audit log, notifs, chiffrement Fernet, idempotence crons, sérialiseurs pour l'API/MCP, numérotation atomique |
| services `drive_*` (10 fichiers) | Wrapper Drive API, OAuth, moteur + hooks + seeders de conventions, dispatcher d'auto-upload |
| `backend/app/integrations/ai/` | Cascade IA `complete()/chat()/embed()` : Gemini (défaut) → Anthropic (claude-sonnet-4-6) → Groq (llama-3.3-70b) |
| `backend/app/integrations/{email_graph, ms_graph_meetings, webpush}.py` | Mailer Graph (info@immohorizon.com), rencontres Teams + transcripts, WebPush VAPID |
| models `user, api_key, audit_log, automation_setting, cron_run, notification, push_subscription, help_request` | Tables socle |
| `frontend/src/lib/auth.ts` | **Hub API du portail** : token localStorage `hsi_access_token`, `authedFetch` (Bearer + retry cold-start + auto-logout 401), `hasMinRole` |
| `frontend/src/app/[locale]/app/parametres/` | Administration : réglages, audit log, clés API/MCP, Drive, migration QBO |
| `frontend/src/app/[locale]/{connexion,profil,installer,dev}/` | Login, profil, guide d'installation PWA, mode dev (whitelist emails) |

### 4.2 Construction (pôle historique, portail `/app`)

| Chemin | Rôle |
|---|---|
| endpoints `contact.py`, `crm_columns, follow_ups, sales_tasks, appointments, acquisition` | CRM entrant (formulaire public → kanban), colonnes custom, relances/suivis, tâches CRM, RDV prospects, entonnoir |
| endpoints `clients, soumissions*` (`soumission_items/status/send/qbo/to_client/to_project`, `soumissions_aggregates`), `service_templates, measurements` | Clients, devis construction (lignes, statuts, envoi PDF, push QBO Estimate, conversion prospect→client et soumission→projet + facture dépôt 25 %), templates de services, relevés de mesures |
| endpoints `projects, project_{phases,tasks,members,finances,photos,billables,to_facture}, subcontractor_contracts, cockpit` | Projets/chantiers : phases multi-assignées, checklist, visibilité, ventilation projeté vs réel + état de compte PDF, refacturation, contrats sous-traitants, cockpit chargé de projet |
| endpoints `factures*` (`facture_items/import/send/qbo`, `payments`), `numbering` | Factures : lignes, progress billing, envoi, push QBO Invoice, paiements partiels, numérotation alignée QBO |
| endpoints `achats*` (`achat_payment/qbo/receipt`), `purchase_order*`, `fournisseurs` (via business.py) | Achats matériaux (reçus scannés, Bill/Purchase QBO), bons de commande PO, fournisseurs |
| endpoints `bon_items, bon_send, public_bon` | Bons de travail (kind construction/interne — refonte 2026-06) : lignes coût/facturé, envoi + signature publique |
| endpoints `punch_ops, timesheets (ST), leave_requests, employes` | Punch géolocalisé, feuilles de temps sous-traitants, congés, employés (auto-création User) |
| endpoints `webhooks_meta, business.py` | Leads Facebook → ContactRequest ; fabrique CRUD générique `make_crud_router` (12 routers) |
| services `soumission_pdf → facture_pdf / bon_pdf / contract_pdf` | Famille PDF construction (seule famille qui réutilise une infra commune) ; contrat APCHQ G1-G20 |
| services `*_qbo*` (`achat_qbo, facture_qbo, soumission_qbo, labour_qbo, qbo_{auto_sync,bulk_sync,cost_pull,invoice_pull,payment_classify,project_resolve}`) | Push/pull QuickBooks : Bills, Purchases, Invoices, Estimates, coûts main-d'œuvre, résolution sous-client→Job |
| services `relance_engine, follow_up, appointment_mail, contact_request*, achat_{dedupe,billable_correct,payment}, facture_dedupe, receipt_rotate, project_auto_status, employe_rates` | Cadences de relance, règles de suivi, emails RDV, dédup post-sync QBO, correction refacturation, rotation reçus, taux horaires historisés |
| models `contact_request(+photo), client(+document), soumission(+item), project(+phase/task/photo/member/correction/assignees), facture(+item), payment, achat, purchase_order(+item), bon_travail(+item), punch, employe(+rate_history), sous_traitant(+timesheet), fournisseur, follow_up, sales_task, relance_*, cadence_step, email_template, note_template, measurement(+photo), numbering_counter, qbo_*` | 178 tables dont le gros bloc construction (sans préfixe SQL) |
| `frontend/.../app/` (59 pages) | Portail : crm, clients, soumissions (quote **et** contract), projets (`[id]` = 6766 lignes, record), facturation, achats, po, bons, punch, employés, sous-traitants, fournisseurs, agenda (3099), cockpit, congés, paie, relances |
| jobs `facture_reminders, soumission_reminders, appointment_reminders, unassigned_day_alerts, punch_auto_close` | Rappels escaladants, relances devis, alertes assignation, fermeture auto des punchs |

### 4.3 Prospection immobilière (portail `/prospection`)

| Chemin | Rôle |
|---|---|
| endpoints `prospection.py` (cœur), `prospection_{deals,lists,analyses,analyse_extract,analysis_defaults}` | Leads drive-by (photos, conversion, moyenne locative par zone), pipeline deals DnD façon Monday + tâches, listes/segments, analyses financières (inputs/résultats JSON), extraction Claude, défauts du calculateur |
| endpoints `lead_analyses.py` (~3000 l.) | Fiches d'analyse : extraction IA multipart, CRUD, PDF, offre d'investissement, TRI |
| endpoints `mtl_properties, admin_data, comparables, rental_comparables, extension` | 500k unités du rôle foncier MTL (+ provincial), ingestion REQ/Centris, comps de vente, comparables de loyers (médiane/P25/P75), réception extension Chrome |
| endpoints `ndas, offers, purchase_agreements(+milestones,+template)` + `public_{nda,offer,purchase_agreement}` | NDA investisseurs, offres d'achat simples, promesses d'achat duProprio (signature 2 étapes acheteur→vendeur) |
| services `financial_calculator/` (port 1:1 du TS frontend), `lead_analysis_finance` (réplique Excel SCHL/APH, 1426 l.), `lead_tri_calc` (TRI au centime), `prospection_scoring` | **3 moteurs de calcul** + scoring heuristique 0-100 |
| services `lead_extraction(+_groq), lead_validation, centris_triage, owner_enrichment, call_recording_summary` | Extraction annonces (regex+OCR ∥ Gemini), validation plausibilité, triage Centris, enrichissement propriétaires (REQ/Canada411), résumé d'appels |
| services `nda_{pdf,send,template}, offer_{pdf,send,template}, purchase_agreement_{pdf,send}, lead_analysis_pdf, offre_investissement_pptx` | Générateurs de documents (PDF + deck PPTX depuis template horizon_v2) |
| integrations `roles_evaluation/ (montreal, montreal_owner=EvalWeb, quebec_regional), req/companies, rental/{kijiji,lespac,parsing}, cmhc/rents, centris/scraper, classifieds/phones, canada411, bank_of_canada, scraping_proxy` | Ingestion rôles fonciers, REQ (~1M corporations), scrapers loyers, SCHL, proxy vers le VPS Playwright |
| models `prospection_lead(+photo/list/transaction), prospection_deal(+task/assignee/immeuble), lead_analysis, prospection_analyse, prospection_analysis_default, nda, offer, purchase_agreement(+template), mtl/montreal_property_unit, req_company, rental_listing, sold_comparable, market_rent, centris_listing` | Préfixe `prospection_` partiel |
| `frontend/.../prospection/` (33 pages) | Leads (tableau/kanban), fiche `[id]` (découpée en sous-composants `_*`), analyses, pipeline, moyenne locative façon Zipplex, comparables, immeubles-mtl, listes, agenda, paramètres (sources scraping, analyse) |
| composants `LeadAnalysisDetailModal` (167 Ko !), `OffreInvestissementWizard` (53 Ko) | Plus gros composants du frontend |
| jobs/scripts `rental_scrape_daily, follow_up_reminders, sales_task_reminders, import_{montreal_roles,provincial_xml_zip,req_zip,monday_prospection}` | Cron scraping quotidien + CLI d'ingestion lourde |

### 4.4 Immobilier / gestion locative (portail `/immobilier`)

| Chemin | Rôle |
|---|---|
| endpoints `immobilier.py` (monolithe, garde `_require_volet` route par route), `immobilier_extras, investissements, public_bail` | Immeubles + ownership multi-entreprises, logements, baux, loyers, dépenses, maintenance, KPIs cashflow ; formulaires TAL, renouvellements ; volet Investisseur (investissements + distributions) ; signature publique de bail |
| services `bail_{sign,signed_pdf,renouvellement,renew_tasks}, tal_forms, plexflow_import` | Signature électronique de bail, PDF d'archive, fenêtres légales QC de renouvellement (avis + tâches QG), lettres TAL PDF, parseur rent-roll PlexFlow |
| models `immobilier.py` (tout-en-un : Immeuble, Logement, Locataire, Bail, BailRenouvellement, PaiementLoyer, Hypotheque… préfixe `imm_`), `user_immeuble, investissement (inv_)` | Volet en un fichier |
| `frontend/.../immobilier/` (13 pages) | Vue d'ensemble, immeubles (fiche 1775 l.), baux & relances loyers, locataires (fiche 360°), finances, renouvellements, dépôts de garantie, bons-travail (miroir lecture seule), diagnostic |
| `frontend/.../investisseur/` | Portail investisseur (portefeuille, DPI/TVPI, distributions) |
| job `loyer_relances` | Cron : cloche managers+ des loyers en retard |

### 4.5 Dev logiciel (« devlog » — écrans internes dans `/app`, pages client à token sous `/devlog`)

| Chemin | Rôle |
|---|---|
| endpoint `devlog.py` (4156 l., 13 routers) + `devlog_notes_ai` | Méga-module : clients, leads kanban, soumissions devis_dev (items/sections/modules/automations), factures, time-entries, sous-traitants + fabrique CRUD interne (via GenericCrud) |
| endpoints `devlog_project_{finances,members,phases,photos,purchases,recap,recurring_services,tasks}, devlog_soumission_defaults` | Familles nested projet (miroir du pôle construction) + défauts globaux des devis |
| endpoints `public_devlog_{contact,invoice,nps,soumission}` | Formulaire public, facture + Stripe Checkout, NPS, signature de soumission |
| services `devlog_devis_calc` (invariant « prix de ligne autonome », PR #932), `devlog_{soumission,invoice}_pdf/send, devlog_stripe, devlog_client_provision, devlog_project_provision, devlog_contract_signed_hook` | Moteur de chiffrage, PDF/envoi, paiement Stripe, conversions lead→client et contrat signé + dépôt payé→projet démarré |
| models `devlog_*` (21 modules, préfixe SQL `devlog_`) | Miroirs assumés : `devlog_lead ≈ contact_request`, `devlog_soumission ≈ soumission` — étanchéité des pôles voulue |
| `frontend/.../app/soumissions|facturation|projets` (kind quote\|contract) | **Pas de portail dédié** : les écrans internes devlog sont fusionnés dans `/app` |
| `frontend/.../devlog/{nps,pay-invoice,sign-soumission}/[token]` + `contrat-signature/[token]` + `dev-logiciel/contact` | Pages client publiques |
| jobs `devlog_facture_reminders, devlog_nps_dispatch, devlog_weekly_client_report` | Relances 4 paliers, NPS J+7, récap hebdo client |

### 4.6 Gestion d'entreprise / QG (portail `/entreprises`)

| Chemin | Rôle |
|---|---|
| endpoints `entreprises, entreprise_extras, entreprise_partners_links, org_nodes(+org_seed_canonical), raci, rencontres(+_teams), subscriptions, timesheets, contacts` | Entreprises + tâches kanban QG, templates récurrents + snapshots financiers + value plan, partenaires, organigramme (seed canonique 6 pôles), matrice RACI, rencontres CA (résumés IA, transcripts Teams), abonnements + coffre à mots de passe (ACL nominative), feuilles de temps bi-hebdo multi-employés, rolodex |
| services `qg_*` (`daily_pulse, global_pulse, insights, visions, recurrence, smart_assign, embeddings, compliance_catalog`), `kratos_{router,local_router,problem_detector}, task_auto_score, org_role_suggester, rencontre_{ai,teams_sync}` | Couche IA du QG : briefings, insights, visions SMART, matérialisation des récurrences, scoring ICE, secrétaire virtuel Kratos (intents), détection de problèmes, résumés de rencontres |
| models `entreprise(+partner/link/finance/recurrence/tache/+assignee/+immeuble), org_node, raci, rencontre, subscription(+vault_access), timesheet, qg_strategic (9 tables qg_), qg_embedding, kratos_{message,problem}, contact(+hide), teams_meeting_import, leave_request` | Préfixe `qg_` partiel |
| `frontend/.../entreprises/` (24 pages) | Dashboard QG, fiche + pilotage entreprise, tâches (kanban + cartes Keep), organigramme, distribution des tâches (RACI), contacts, abonnements, feuille de temps, rencontres, vision, kratos, réglages — layout à sidebar inline qui **exporte** QGTopbar/useEntreprisesLayout |
| `frontend/.../mes-taches/` | PWA distincte (manifest/scope propres) qui réutilise la page entreprises/taches en vue Cartes |
| job `kratos_problems_daily` | Cron 06h : 3-5 problèmes IA par entreprise |

### 4.7 Public / SEO (site vitrine immohorizon.com)

| Chemin | Rôle |
|---|---|
| `frontend/.../[locale]/page.tsx` + `{a-propos,contact,services/*,mentions-legales,confidentialite}` | Homepage marketing + pages statiques (Loi 25) |
| 5 pages piliers (`construction-renovation-montreal` codée main, 4 autres via `seo-pillar-template`) | ~2500 mots, hub de maillage |
| `renovation/[service]/[city]` + `lib/seo-locations.ts` | **432 landing pages géo** SSG (54 villes × 8 services, FAQ substituées) |
| `blog/` + endpoint `blog.py` + model `seo_article` + job `seo_daily` | 3 articles SEO/jour générés par la cascade IA (Claude), ISR 3600 s |
| endpoint `contact.py` (POST public) + `lea_web.py` + model `lea_chat` | Formulaire multipart (honeypot, rate-limit IP) ; chat public Léa (même IA que le téléphone) |
| `sitemap.ts, robots.ts, layout.tsx` (JSON-LD LocalBusiness), `middleware.ts` (next-intl) | SEO technique, hreflang fr/en |

### 4.8 Mobile (PWA `/m`)

| Chemin | Rôle |
|---|---|
| endpoint `mobile.py` | API PWA employé : `/mobile/me`, punch start/stop, congés, tâches, projets, bons (⚠️ duplique punch_ops.py) |
| `frontend/.../m/` (20 pages) | Accueil punch/agenda, punch, intervention terrain `[id]`, prospection mobile, crm, po, congés (`conge`/`conges`), bottom-nav 5 onglets, safe-area iOS |
| `frontend/public/sw.js` + 3 manifests | Service worker network-first API / cache-first statics ; 3 PWA installables (racine, /mes-taches, /telephonie) |

### 4.9 Téléphonie / voice (« Léa »)

| Chemin | Rôle |
|---|---|
| endpoint `voice.py` (**5482 l., plus gros fichier du backend**) | Webhooks Twilio (~15 : voice, secretary, status, voicemail + transcription, queue, whisper, SDK), endpoints internes (historique, filtres, heures d'ouverture) |
| `integrations/voice/` (12 modules) | `secretary.py` (Léa, moteur tour-par-tour IA, 9 actions), `routing` (blocklist→VIP→heures→IA→transfert), `spam_filter` (STIR/SHAKEN, honeypot, auto-ban), `twilio_provider` (sans SDK, signature HMAC-SHA1), `voice_sdk` (tokens WebRTC), `lookup` (Lookup v2 + cache 30 j), `caller_identity` (matching CRM cross-pôles), `lead_outbound` (Léa rappelle un lead 60 s après création), `lea_task` |
| model `voice.py` | PhoneNumber, Call, CallRoute, CallTranscript, CallTurn, VoiceFilter, VoiceBusinessHours… (préfixe `voice_`, rare usage de relationship()) |
| composants `voice-console` (Twilio Voice SDK WebRTC), `dial-pad`, `call-*` + portail `/telephonie` | Softphone intégré au portail (VoiceConsole monté globalement dans app/layout) |

---

## 5. Points d'entrée

### 5.1 Routes publiques (SANS auth — token opaque dans l'URL ou pas de protection)

| Endpoint backend | Page frontend | Rôle |
|---|---|---|
| `POST /api/v1/auth/login` | `/connexion` | Seule route d'auth publique (register = admin-only) |
| `POST /api/v1/contact` + `/contact/by-token/{token}` | `/contact` | Formulaire site construction (multipart, photos) — pas de rate-limit visible côté POST |
| `GET /api/v1/blog/*` | `/blog` | Articles SEO lecture seule |
| `/api/v1/lea-web/*` | widget (débranché) | Chat public Léa, session token urlsafe(32) |
| `GET /api/v1/calendar/my-agenda.ics?token=` | — | Flux ICS perso (404 si token inconnu) |
| `/api/v1/public/soumissions/{token}` | `/soumission/[token]` | Accept/reject soumission construction |
| `/api/v1/public/factures/{token}` | `/facture/[token]` | Consultation + e-signature facture |
| `/api/v1/public/bons/{token}` | `/bon/[token]` | Signature bon de travail |
| `/api/v1/public/contracts/{token}` | `/contrat-signature/[token]` | Signature contrat d'entreprise |
| `/api/v1/public/baux/{token}` | `/sign-bail/[token]` | Signature bail locataire |
| `/api/v1/public/ndas/{token}` | `/sign-nda/[token]` | Signature NDA investisseur |
| `/api/v1/public/offers/{token}` | `/sign-offer/[token]` | Accept/refuse offre d'achat |
| `/api/v1/public/purchase-agreements/buyer\|seller/{token}` | `/promesse-achat/{acheteur,vendeur}/[token]` | Promesse d'achat 2 étapes |
| `/api/v1/public/devlog/contact` | `/dev-logiciel/contact` | Lead devlog (honeypot + rate-limit IP in-memory) |
| `/api/v1/public/devlog/invoices/{token}` | `/devlog/pay-invoice/[token]` | Facture + Stripe Checkout (**token sans expiration**) |
| `/api/v1/public/devlog/nps/{token}` | `/devlog/nps/[token]` | NPS post-livraison |
| `/api/v1/public/devlog/soumissions/{token}` + `contracts/{token}` | `/devlog/sign-soumission/[token]`, `/sign-devlog/[token]` | Signature devis/contrat devlog |
| `GET /api/v1/push/vapid-public-key` | — | Clé publique VAPID |
| `GET /`, `GET /health`, `GET /api/v1/ping` | — | Info, sonde Render, réveil combiné |

### 5.2 API à clé krts_ / MCP — ⚠️ CONTRATS FIGÉS (ne pas toucher)

| Chemin | Contrat |
|---|---|
| `endpoints/mcp_server.py` — monté sur `/mcp/{api_key}` **ET** `/api/v1/mcp/{api_key}` | Serveur MCP Streamable HTTP (JSON-RPC 2.0), ~15 tools `kratos_*`, lecture scopée à la clé dans l'URL — connecteur des Claude de Phil |
| `endpoints/activity.py` — `/api/v1/activity/*` | API externe clé krts_ (Bearer ou `X-API-Key`), scopes par pôle via `require_scope` |
| `endpoints/api_keys.py` + `services/api_capabilities.py` | Gestion des clés et **source de vérité des scopes** |
| `endpoints/extension.py` — `/api/v1/extension/*` | Contrat avec l'extension Chrome déployée (`X-Extension-Key`) |
| `endpoints/cron_runner.py` — `/api/v1/cron/run/*` | Contrat avec GitHub Actions / cron-job.org (`X-Cron-Secret`) |

### 5.3 Webhooks entrants (publics par contrat — signatures vérifiées)

| Endpoint | Émetteur | Protection |
|---|---|---|
| `POST /api/v1/webhooks/stripe` | Stripe | `Stripe-Signature` |
| `POST /api/v1/qbo/webhook` (+ `/webhooks/qbo` legacy) | Intuit QBO | `intuit-signature` HMAC-SHA256 du corps brut |
| `GET/POST /api/v1/webhooks/facebook-lead` | Meta Lead Ads | `META_VERIFY_TOKEN` handshake |
| `POST /api/v1/webhooks/form` | Formulaires externes | `x-webhook-secret` |
| `POST /api/v1/voice/twilio/*` (~15 callbacks) | Twilio | `X-Twilio-Signature` HMAC-SHA1 |
| `GET /api/v1/qbo/callback` | Redirect OAuth Intuit | state HMAC signé + TTL 5 min |

### 5.4 Crons (voir §2 pour les 4 mécanismes)

Récapitulatif des jobs et de leurs déclencheurs connus :

| Job | render.yaml | Dashboard (RENDER_CRONS.md) | GH Actions | all-daily/hourly |
|---|:-:|:-:|:-:|:-:|
| seo_daily | ✓ 11:00 | ✓ | | |
| facture_reminders | ✓ 12:30 | | ✓ 02:00 | ✓ (**3× schedulé**) |
| devlog_facture_reminders | ✓ 13:30 | | | ✓ |
| follow_up_reminders | ✓ horaire | ✓ 13:00 | ✓ 02:00 | |
| punch_auto_close | ✓ 03:00 | | | |
| kratos_problems_daily | ✓ 10:00 | | | |
| rental_scrape_daily | | ✓ 06:00 | | |
| sales_task_reminders, soumission_reminders, loyer_relances, teams_sync_auto | | ✓ | | |
| unassigned_day_alerts | | ✓ | ✓ | ✓ |
| appointment_reminders | | | ✓ | ✓ |
| qg (pulse/insights/récurrence), bail-renouvellement(s/-tasks), calendar-feeds-sync, devlog_nps_dispatch, dédup/pulls QBO | | | | ✓ |
| devlog_weekly_client_report | — | — | — | **aucun déclencheur versionné** (cron-job.org externe présumé) |

### 5.5 Scripts one-shot / CLI

| Script | Usage |
|---|---|
| `app/scripts/create_admin.py`, `scripts/create_admin.py`, `scripts/init_admin.py` | Bootstrap admin (**3 variantes**) |
| `app/scripts/monday_migrate.py` | Import Monday one-shot (migration terminée). NB : `scripts/import_monday*.py` supprimés le 2026-07-07 (morts, cf. P-15). |
| `scripts/import_montreal_roles.py`, `import_provincial_xml_zip.py`, `import_req_zip.py` | Ingestions lourdes (rôle MTL ~500k, provincial 3-5 Go, REQ ~1M) via Render Shell / VPS |
| `scripts/rental_scrape_daily.py` | Cible du cron scraping loyers |
| `app/scripts/twilio_bootstrap.py` | Auto au boot si credentials présents (webhooks numéro) |

---

## 6. Le système de migration maison (PAS d'Alembic actif)

Le scaffolding Alembic existe (`alembic.ini`, `env.py` async, import de tous les modèles) mais
**`alembic/versions/` est vide** : aucune migration versionnée n'a jamais été générée. README et
ARCHITECTURE_PHASE1.md qui affirment « Migrations: Alembic » sont périmés. **Tout le cycle de vie
du schéma s'exécute au boot**, dans `backend/app/db/session.py` (3018 lignes) :

1. **`init_db()`** : `Base.metadata.create_all` (crée les tables des 130 modèles importés par
   `models/__init__.py`) puis une liste géante **`additive_columns`** (~250-400 tuples
   `ALTER TABLE … ADD COLUMN IF NOT EXISTS`) exécutée dans une **grosse transaction** — plus des
   seeds (barèmes SCHL/APH, taxes de bienvenue, défauts devis) et des backfills métier.
2. **`ensure_critical_columns()`** : filet de sécurité — répète certains ALTER, mais **une
   transaction par colonne**. Raison d'être : si un ALTER rate dans la grosse transaction
   d'init_db, tout ce qui suit est annulé silencieusement.
3. **`ensure_*_tables()`** (5 : raci, immobilier_aux, timesheet, project_corrections, relance) :
   création ciblée de tables en transactions isolées.
4. Backfills et rotation d'images exécutés à **chaque** démarrage (idempotence affirmée).

**Règles à respecter (piège documenté)** :

- **Toute nouvelle colonne DOIT être ajoutée dans `ensure_critical_columns`** (transaction isolée).
  L'ajouter seulement dans `additive_columns` ne suffit pas : si un autre ALTER de la grosse
  transaction échoue, votre colonne n'est jamais créée → **500 en prod alors que la CI est verte**
  (la CI ne touche pas la BDD réelle).
- **Toute nouvelle table** : déclarer le modèle **et** l'importer dans `models/__init__.py`
  (sinon `create_all` ne la voit pas) ; pour les cas sensibles, ajouter un `ensure_*_tables` dédié.
- **Additif seulement** : jamais de DROP/RENAME/ALTER TYPE au boot ; les colonnes obsolètes restent.
- Les backfills doivent être **idempotents** (relancés à chaque boot).
- Ne pas générer de migration Alembic : elle ne serait jamais exécutée.

---

## 7. Auth

**JWT (portail)** — `core/security.py` + `api/deps.py` :
- HS256, `sub` = user id, expiration 24 h par défaut (⚠️ `ACCESS_TOKEN_EXPIRE_MINUTES=30` traîne
  dans render.yaml backend et .env.example — si la var existe sur Render, les sessions durent 30 min).
- Hiérarchie de rôles `owner > admin > manager > employee` (`ROLE_RANK`, `has_min_role`).
- Guards : `CurrentUser` (connecté actif), `RequireManager`, `RequireAdminRole`,
  `RequireAdminOrOwner`, `RequireOwner`.
- **Trois variantes « admin » coexistent** avec des sémantiques différentes :
  1. `get_current_admin` (**legacy**, « kept for backward compatibility ») : passe si `is_admin`
     OU rôle admin — encore utilisé par auth.register, numbering, qbo_token, voice, prospection…
  2. `get_current_admin_role` : `min_role=admin` (admin et owner).
  3. `get_current_admin_or_owner` : liste stricte.
- Accès par volet : `user.volets_json` + helper `_require_volet` (copié dans 6 fichiers) ;
  visibilité fine employee via `project_members` / `user_immeubles` (`core/permissions.py`).

**Clés API `krts_` (API externe + MCP)** — `api/api_key_deps.py` :
- Clé transmise en Bearer ou `X-API-Key` (ou dans l'URL pour le MCP `/mcp/{key}`).
- Stockée hashée **SHA-256**, active + non expirée, **scopes par pôle**
  (catalogue `services/api_capabilities.py`), `last_used_at` maintenu best-effort.
- Gestion des clés par JWT via `endpoints/api_keys.py`.

**Autres secrets partagés** : `X-Cron-Secret` (crons HTTP), `X-Extension-Key` (extension Chrome),
`X-API-Key` (VPS scraping), signatures Stripe/Intuit/Twilio/Meta pour les webhooks.

---

## 8. Conventions

### 8.1 Conventions observées (état réel, hétérogène)

- Un fichier d'endpoint par ressource, prefix déclaré dans le fichier, enregistrement centralisé
  dans `router.py` — mais **l'ordre d'enregistrement est significatif** (≥10 commentaires
  « DOIT être avant ») et 9-10 fichiers dépassent 800 lignes avec la logique métier dans les vues.
- Services = modules de **fonctions async** prenant une `AsyncSession` (style dominant, ~110
  fichiers) ; 4 services/repositories « classes textbook » legacy subsistent.
- Modèles : déclaratif SQLAlchemy 2.0 (`Mapped[]`), un modèle par fichier, docstrings FR riches ;
  quasi **aucun `relationship()`** (FK entiers nus, jointures manuelles) ; préfixes SQL par pôle
  inégaux (`imm_`, `qg_`, `devlog_`, `voice_`, `prospection_`… construction sans préfixe).
- DTOs Pydantic : minorité dans `schemas/`, majorité **inline dans les endpoints**.
- JSON : majoritairement `Text` + `json.dumps` manuel (43 colonnes `*_json`), JSONB natif minoritaire.
- Frontend : ~100 % client-side (`"use client"`, zéro SSR portail), data-fetching via `authedFetch`,
  pages monolithiques (35 fichiers > 1000 lignes), types API redéfinis inline par page.
- Nommage FR/EN mélangé partout (Achat vs PurchaseOrder, facture_send vs devlog_invoice_send).
- Docstrings et commentaires majoritairement en **français**.

### 8.2 LA convention cible (celle qui domine déjà — à appliquer à tout nouveau code)

1. **Endpoints minces** : le fichier d'endpoint valide/autorise et délègue ; la logique métier va
   dans `backend/app/services/` (module de fonctions async prenant `AsyncSession`).
2. **Schémas Pydantic dans `backend/app/schemas/`** (pas de BaseModel inline dans les endpoints).
3. **Un modèle par fichier dans `backend/app/models/`**, importé dans `models/__init__.py`,
   docstring FR, préfixe SQL du pôle, mixins Timestamp de `db/base.py`.
4. Nouvelle colonne/table → règles de migration du §6 (`ensure_critical_columns` obligatoire).
5. **Pages portail dans `frontend/src/app/[locale]/<pole>/`** ; sous-composants co-localisés
   `_nom.tsx` quand la page grossit (pattern prospection/[id]) — viser < 1000 lignes par page.
6. **Composants partagés dans `frontend/src/components/`**, configs partagées dans `lib/`
   (`task-config.ts`, `tax.ts` = sources uniques).
7. **Tous les appels API du portail via `authedFetch`** (`lib/auth.ts`) ; fetch brut réservé aux
   pages publiques à token.
8. Layouts de pôle : déléguer la sidebar à un composant (pattern app/prospection), ThemeProvider
   + ConfirmProvider, navigation via `@/i18n/navigation`.
9. Auth backend : guards par rôle de `deps.py` (`RequireManager`/`RequireAdminRole`/…) — **ne plus
   utiliser `CurrentAdmin` legacy** ; taux de taxes uniquement via `core/taxes.py`.
10. Docstrings/commentaires **en français** ; emails via `integrations/email_graph.get_mailer` ;
    idempotence des jobs via `cron_guard.claim_cron_run`.

---

## 9. Incohérences structurelles (consolidées des 8 zones)

### 9.1 Schéma & migrations
- `db/session.py` (3018 l.) viole son rôle : moteur de migration + seeds métier (SCHL, taxes de
  bienvenue, défauts devis) + backfills + rotation d'images de reçus, et **couplage db → services**
  (référence les barèmes de `lead_analysis_finance`).
- ~25 colonnes présentes À LA FOIS dans `additive_columns` et `ensure_critical_columns`
  (redondance volontaire mais sans convention écrite sur la source de vérité).
- Alembic fantôme : scaffolding complet, zéro version ; README/ARCHITECTURE_PHASE1.md et même le
  commentaire d'init_db (« use Alembic migrations instead ») contredisent la réalité.
- Logique de données au boot : backfill `bons_travail.kind='interne'` et rotation CW90 relancés à
  chaque démarrage ; `print()` au lieu du logger dans init_db.

### 9.2 Scheduling des crons (le plus gros risque opérationnel)
- **Contradiction documentaire** : render.yaml (blueprint, 6 crons) vs RENDER_CRONS.md (« Render
  ne lit PAS render.yaml, crons créés à la main »). Impossible de savoir depuis le repo ce qui
  tourne réellement ; `follow-up-reminders` existe dans 3 sources avec 3 horaires différents.
- `facture_reminders` schedulé **3 fois** ; l'anti-doublon `claim_cron_run` ne couvre pas le chemin
  `python -m` des crons Render.
- Jobs orphelins/doublons : `ical_sync_all.py` réimplémenté
  inline dans cron_runner (garde `is_automation_enabled` ajoutée le 2026-07-07, P-09/vague 1),
  2 jobs Teams quasi identiques (dont un référence un workflow GH inexistant).
  NB : `monday_bridge.py` (0 importeur) supprimé le 2026-07-07 (P-15).
- `loyer_relances` et `teams_sync_auto` : sans garde et absents du catalogue d'automatisations ;
  horaires du catalogue désynchronisés du scheduling réel ; `devlog_weekly_client_report` et
  `bail-renouvellements` sans déclencheur versionné.
- `cron_runner.py` (~900 l.) : logique métier inline dupliquée entre all-daily et all-hourly.

### 9.3 Auth & autorisation
- 3 guards admin à sémantiques différentes, choix arbitraire par endpoint ; `CurrentAdmin` legacy
  encore utilisé par ~5 fichiers.
- `_require_volet` copié-collé dans 6 fichiers au lieu d'une dépendance partagée ; dans
  `immobilier.py` la garde est appliquée à la main sur 60+ handlers avec au moins une route sans garde.
- 2 fabriques CRUD génériques aux politiques divergentes : `business.make_crud_router` (manager+)
  vs la fabrique interne de devlog.py (ouverte à tout user).
- `m/layout.tsx` fait son auth avec getToken/getMe bruts (pas useCurrentUser) et redirige sans
  préfixe de locale.

### 9.4 Duplication structurelle inter-pôles
- Familles nested `project_*` (construction) vs `devlog_project_*` : mêmes patterns CRUD dupliqués.
- **2 API de punch parallèles** : `mobile.py` vs `punch_ops.py` (résolution User→Employe, EmployeMini
  et ouverture/fermeture dupliquées).
- Le flux « document signable par token » est réimplémenté **~6-8 fois** (nda, offer,
  purchase_agreement, contract, facture, soumission, bon, bail) — mêmes schémas, zéro abstraction ;
  idem côté frontend (~6 pages token au squelette recopié).
- Pattern push-QBO répété dans 4 fichiers quasi identiques (achat/client/facture/soumission_qbo).
- 5 tables photo-BYTEA quasi identiques ; 4 systèmes de suivi du temps ; 2 moteurs d'analyse
  financière prospection + 2 modèles d'offre d'achat ; 2 enums `PaymentMethod` homonymes
  incompatibles (achat.py vs payment.py) ; 2 agendas complets au frontend (app 3099 l. +
  prospection 1209 l.) ; règles légales de renouvellement de bail encodées dans 2 services.
- PDF : `_lazy_reportlab` ×7, `_money/_fmt_money` ×12, `_public_base()` ×11, styles/couleurs
  redéfinis partout — seule la famille construction réutilise l'infra de soumission_pdf.

### 9.5 Nommage & langues
- FR/EN mélangé sur les mêmes concepts (facture_send vs devlog_invoice_send ; Achat vs
  PurchaseOrder ; prospection_analyse_ vs prospection_analysis_) ; docstrings EN/FR selon le fichier.
- `contact.py` vs `contacts.py` (deux domaines différents) ; `payment.py` : classe Payment,
  table `facture_payments` ; `m/conge` vs `m/conges` ; préfixes SQL inégaux
  (`immeuble_depenses` viole le `imm_` de son propre fichier).

### 9.6 Organisation des couches
- Logique métier massive dans les endpoints : voice.py 5482 l., devlog.py 4156 l. (13 routers,
  devlog_notes_ai extrait « pour éviter les conflits de merge »), lead_analyses, prospection,
  mtl_properties, project_finances, timesheets > 800 l. ; `_compute_billed_amount` (argent à fort
  enjeu) vit dans un endpoint — seul test du repo qui importe la couche API.
- Couche repositories à moitié orpheline (6 fichiers utilisés par une poignée d'endpoints) ;
  `services/__init__.py` et `repositories/__init__.py` n'exportent que les 3 modules legacy ;
  `models/__init__.py.__all__` désynchronisé.
- `business.py` héberge des jobs background throttlés par variables globales module-level ;
  `soumission_status.py` importe un helper depuis `public_soumission.py` (couplage
  endpoint→endpoint) ; finance_math/taxes rangés dans `core/` et ratio TPS/TVQ re-hardcodé en SQL
  dans session.py et en constantes locales dans soumission_to_project.py.
- Routage fragile : ordre d'include_router significatif ; `purchase_agreements.py` seul router
  sans prefix ; `org_seed_canonical.py` réutilise le prefix d'org_nodes ; MCP monté deux fois ;
  deux blocs d'import du même package dans router.py.
- 2 specs métier `.md` dans `services/` ; whitelists d'emails hardcodées dans `models/user.py` et
  `dev/page.tsx` ; convention singleton id=1 répétée sans helper (5 tables).

### 9.7 Frontend
- 35 fichiers > 1000 lignes (record `app/projets/[id]` 6766) ; types API redéfinis inline
  (`type Project` recopié ~10-15 fois avec des shapes divergentes).
- Layouts hétérogènes : immobilier (790 l.) et entreprises (929 l.) embarquent leur sidebar inline ;
  entreprises/layout **exporte** QGTopbar/useEntreprisesLayout consommés par ~15 pages (layout
  utilisé comme librairie) ; squelette ThemeProvider/ConfirmProvider recopié 4×.
- `routing.ts` (pathnames next-intl) a dérivé de l'arborescence réelle → 6 casts `as never`/`as any` ;
  2 implémentations de redirect locale-aware ; `href as any` disséminé.
- `mes-taches/page.tsx` importe le module page d'une autre route (fragile) ;
  sous-composants `_*.tsx` seulement dans prospection ; `error.tsx` sur 3 routes seulement ;
  stub « Section en développement » accessible en nav (entreprises/reglages/equipe).
- Garde-fous désactivés : `ignoreBuildErrors` + `ignoreDuringBuilds`, eslint no-unused-vars/
  no-explicit-any off, **aucun test frontend** (vitest installé, jamais utilisé).
- Composants orphelins : 4 supprimés le 2026-07-07 (analysis-defaults-modal, json-ld,
  measurement-import-modal, portal-corner — P-15). Reste **lea-chat-widget** (prétend être monté,
  backend câblé → arbitrage Phil : remonter vs supprimer). JSON-LD LocalBusiness n'est plus défini
  qu'une fois (buildPillarJsonLd de seo-pillar-template) depuis le retrait de l'orpheline ; pilier
  construction-renovation-montreal codé à la main vs template partagé (et son commentaire sur le
  footer est faux).
- i18n cosmétique : messages fr/en couvrent le site vitrine seulement, portail hardcodé FR ;
  `robots.ts` disallow des routes inexistantes (/admin, /login) mais laisse crawlables les vrais
  préfixes portail ; appels tiers directs client-side (photon.komoot.io, unpkg.com Leaflet).

### 9.8 Config, docs & branding périmés
- `backend/render.yaml` périmé (service « construction-management-api » vs h2-0 réel, ~25 env vars
  manquantes, `ACCESS_TOKEN_EXPIRE_MINUTES=30` contradictoire) ; `.env.example` idem (10 vars sur ~70).
- Branding incohérent : app = « Horizon Services Immobiliers API », docstring = « Construction
  Management API », produit = Kratos ; domaines hardcodés mixtes dans config.py.
- Docstrings périmées (roles_evaluation/__init__, _gemini.py, mapping PPTX avec _changelog_v3/v4,
  scraping_vps/app.py annonce des endpoints inexistants) ; `CLAUDE_MODEL`/`settings.claude_model`
  sans consommateur (la cascade lit `AI_MODEL`, global à tous les providers — piège).
- Assets binaires dupliqués (logo.png = LOGO-HORIZON-BLANC-FONDNOIR (1).jpg au octet près ;
  Gemini_Generated_Image… en double racine/public).

### 9.9 Sécurité incohérente
- CORS : `allow_origin_regex` accepte **toute** extension Chrome et **toute** app *.onrender.com
  avec `allow_credentials=True`.
- Politiques de chiffrement contradictoires : drive_oauth accepte un fallback base64 non chiffré,
  secret_vault le refuse explicitement ; `qbo_token.refresh_token` stocké **en clair** alors que
  Drive et Abonnements chiffrent en Fernet.
- Endpoints de debug en prod (`/debug-extract-url`, 2 routes health OCR redondantes dans
  lead_analyses.py).

---

## 10. Complétude de la cartographie

**Verdict (clé `critique` du JSON)** : couverture **~97 %**. Le backend est exhaustif (139-140
endpoints, ~130 modèles, schémas, services, jobs, intégrations, scripts et tests tous mappés),
ainsi que l'infra (workflows, extension, scraping_vps, docs). **Tous les trous sont côté frontend** :

| Chemin manquant | Importance |
|---|---|
| `frontend/src/app/[locale]/dev-logiciel/` (portail complet sauf contact/) — ~19 pages : leads, soumissions, contrats, facturation, projets, heures, sous-traitants, clients, agenda, layout | **Le plus gros trou** : un pôle entier de l'intranet non cartographié (la carte n'en couvre que le formulaire public) |
| `frontend/src/app/[locale]/telephonie/` (layout, page, _client-shell) | La page qui assemble le softphone Léa — les composants sont mappés, pas la route |
| `sign-bail/[token]`, `sign-nda/[token]`, `sign-offer/[token]`, `sign-devlog/[token]` | 4 surfaces publiques de signature sans auth — importantes pour le mapping sécurité |
| `soumission/[token]/page.tsx` | Pendant frontend de public_soumission.py (couvert côté backend) |
| `valider-demande/[token]/page.tsx` | Page publique de validation à token |
| `renovation-multilogement-montreal/`, `renovation-salle-de-bain-montreal/` | 2 pages piliers SEO (cosmétique) |
| `frontend/package.json`, `tsconfig.json`, `postcss.config.mjs`, `.eslintrc.cjs`, `.env.example` | Config frontend partielle (mineur) |
| `entreprises/InsightsOverviewCard.tsx` | Composant co-localisé orphelin de la carte (très mineur) |

> Note : ce document mentionne quand même les pages `sign-*`, `soumission/[token]` et le portail
> dev-logiciel là où d'autres zones les référencent indirectement — mais leur contenu réel n'a pas
> été inspecté par la cartographie.

---

*Document généré le 2026-07-06 à partir de la cartographie en 8 zones (noyau backend, endpoints A/B,
modèles+schémas, services+repositories, jobs+intégrations, frontend portail, frontend public+lib).
Matière première de l'audit : `C:\tmp\kratos_audit_leads.json` (130 pistes consolidées).*
