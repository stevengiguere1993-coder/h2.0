# Audit & refactoring Kratos — nuit du 5 au 6 juillet 2026

> Rapport produit par Claude (session de nuit autonome, branche `refactor/nuit-audit-2026-07-06`).
> Objectif : code plus propre, documenté, optimisé, **sans aucun changement visible pour les utilisateurs**.
> Ce document se lit de haut en bas : résumé, méthode, baseline, constats, actions, propositions.

## 1. Résumé exécutif

*(rédigé en fin de nuit — voir dernière section)*

## 2. Méthode et garde-fous

- **Branche isolée** : `refactor/nuit-audit-2026-07-06`, jamais mergée dans `main` sans validation de Phil.
- **Gate avant chaque commit** : `tsc --noEmit` (frontend) + `pytest` complet (backend) doivent être verts ; le lint ne doit jamais être pire que la baseline.
- **Interdits respectés** : aucun `.env`/secret touché, aucune migration/modification de schéma BD, aucune désinstallation de dépendance sans vérification exhaustive des usages, aucun major bump, aucun changement aux contrats de l'API MCP/clé API.
- **Dans le doute → rien modifié**, consigné dans `docs/PROPOSITIONS.md`.
- Un commit = un module ou un correctif, format `[pôle][type] description` (types : refactor, fix, cleanup, docs, perf, test).

## 3. Baseline (état de référence avant tout changement)

Mesurée sur `main` @ `4f115df7` (2026-07-05, soir).

| Vérification | Résultat | Détail |
|---|---|---|
| Backend `pytest` | ✅ 49/49 | 11 s — uniquement des tests de calculs purs (`backend/tests/services/`) |
| Frontend `tsc --noEmit` | ✅ propre | |
| Frontend `next build` | ✅ | build de prod complet |
| Frontend `next lint` | ⚠️ erreurs préexistantes | `no-html-link-for-pages` ×~23 dans `DriveFolderExplorer.tsx:1697` (+ warnings hooks dans `LeadAnalysisDetailModal.tsx`) — non bloquant en CI |

Couverture de tests avant : **6 fichiers de tests, 49 tests, 0 test d'API/HTTP** (aucun filet sur l'auth, le CRUD, la facturation, les contrats MCP).

### Plus gros fichiers (dette de taille, à ne PAS réécrire cette nuit)

| Fichier | Lignes |
|---|---|
| `frontend/.../dev-logiciel/projets/[id]/page.tsx` | 8 082 |
| `frontend/.../app/projets/[id]/page.tsx` | 6 766 |
| `backend/app/api/v1/endpoints/voice.py` | 5 482 |
| `frontend/src/components/leads/LeadAnalysisDetailModal.tsx` | 4 668 |
| `backend/app/api/v1/endpoints/devlog.py` | 4 156 |
| `backend/app/api/v1/endpoints/immobilier.py` | 4 045 |
| `backend/app/api/v1/endpoints/lead_analyses.py` | 3 411 |
| `backend/app/db/session.py` | 3 018 |

Volume total : ~344 000 lignes de source (py + ts + tsx), 925 fichiers suivis par git.

## 4. Constats de l'audit

L'audit a couvert **9 zones** (5 backend, 4 frontend/scraping/extension) × 6 dimensions (code-mort, duplication, bug, sécurité, perf, qualité), chaque piste étant ensuite passée à une **contre-expertise adversariale** (un second modèle tente de réfuter chaque constat sur le code réel). Sur les **61 findings vérifiés individuellement**, **2 ont été réfutés** (constats factuellement faux, voir la sous-section finale) et **59 confirmés** — dont plusieurs **rétrogradés** par la contre-expertise (sévérité baissée et/ou action « corriger cette nuit » requalifiée en « documenter » quand le fix n'était en réalité ni invisible ni sans risque). S'y ajoutent **34 pistes documentées** non vérifiées individuellement (toujours action = documenter). Ce filtrage a de la valeur : sur les findings initialement marqués « P0 » ou « fix cette nuit », la contre-expertise en a discrètement désamorcé une bonne partie (ex. « job de relances devlog jamais déclenché » = faux ; « double-dépense QBO sur PO » = déjà protégé par le dédup DocNumber ; « refresh token QBO bricke l'intégration » = fenêtre de course bien plus étroite que P0). Au net : **30 correctifs sûrs retenus pour cette nuit** (29 distincts — un doublon signalé), **55 items renvoyés en propositions/documentation** (`PROPOSITIONS.md` + worklist), regroupés en 15 propositions thématiques (P-03 à P-17).

### 4.1 Comptage des findings retenus (sévérité effective × dimension)

Sévérité effective = `corrected_severity` de la contre-expertise si présente, sinon la sévérité d'origine. Inclut les 59 vérifiés-confirmés + les 34 documentés non vérifiés.

| Dimension | P0 | P1 | P2 | P3 | P4 | Total |
|---|---|---|---|---|---|---|
| **bug** | 2 | 4 | 8 | 10 | 1 | 25 |
| **sécurité** | 3 | 4 | 9 | 6 | 0 | 22 |
| **duplication** | 0 | 0 | 5 | 6 | 2 | 13 |
| **code-mort** | 0 | 2 | 5 | 3 | 0 | 10 |
| **perf** | 0 | 0 | 3 | 5 | 1 | 9 |
| **qualité** | 0 | 1 | 2 | 3 | 0 | 6 |
| **Total** | **5** | **11** | **32** | **33** | **4** | **85** |

Lecture : la masse est en P2/P3 (dette et durcissements), mais **5 P0** et **11 P1** méritent attention — presque tous en sécurité (escalades de privilège) et en bug d'intégrité (machines à états de facturation/signature).

### 4.2 Findings retenus par dimension

Légende : `→ corrigé cette nuit` = correctif backend/frontend sûr et invisible ; `→ documenté` = renvoyé en proposition (risque, décision produit, migration ou réécriture large).

#### Sécurité

- **[P0] auth.py:78 / users.py:226 — Escalade admin → owner via /auth/register et POST /users.** `UserCreate.role` est contrôlé par l'appelant : un compte *admin* (rang 3) peut créer ex nihilo un compte *owner* (rang 4) avec un mot de passe choisi, puis s'y connecter — franchissant la frontière que `update_role` (RequireOwner) protège pourtant. Aucune comparaison de rang. → documenté (P-04).
- **[P0] users.py:413 — set-password sans garde sur le rôle de la cible.** Gardé par RequireAdminRole (admin OU owner), l'endpoint ne compare jamais le rôle de la cible : un admin peut réinitialiser le mot de passe d'un *owner* et se connecter en owner. Même trou sur `force_password_change` et `update_volets`. → corrigé cette nuit (check de rang avant écriture).
- **[P1] users.py:283 — Aucun audit log sur les mutations de comptes** (création, rôle, volets, désactivation, suppression, set-password). Impossible de savoir qui a promu/désactivé/réinitialisé qui, alors que le reste du pôle devlog logge tout. → corrigé cette nuit (login/register → documenté).
- **[P1] create_admin.py:47 — Compte admin promu OWNER en silence.** Le script pose `is_admin=True` sans écrire `role`, donc le backfill de boot (`is_admin=TRUE AND role=employee → owner`) le promeut owner. → corrigé cette nuit (poser `role='admin'`).
- **[P1] deps.py:79 — Trois guards admin divergents.** `get_current_admin` (legacy, `is_admin` seul) accorde ~50 endpoints (gestion des rôles, QBO, téléphonie) que les guards par rôle refusent ailleurs. Le périmètre admin dépend du guard choisi par fichier. → documenté (P-07).
- **[P1] projets/facture — écritures gardées par simple CurrentUser** (projects.py:380 delete, facture_items.py, project_to_facture.py, facture_send.py, bon_send.py) alors que la politique maison est RequireManager. Un employé peut supprimer un projet ou éditer les lignes d'une facture payée. → documenté (P-11 ; décision métier, le kanban fait des PUT).
- **[P2] punch_ops.py:141 — GET /punch/debug « admin only » gardé par CurrentUser** : dump des emails (PII) des 50 premières fiches employé à tout compte connecté. → corrigé cette nuit (RequireAdminRole).
- **[P2] immobilier.py:326 — DELETE picker sans _require_volet ni scope** : tout user peut désactiver n'importe quel immeuble. → documenté (P-11).
- **[P2] immobilier.py:2117 — visibilité employé (_require_immeuble_visible) appliquée de façon incohérente** : baux/dossier locataire lisibles hors périmètre. → documenté (P-11).
- **[P2] immobilier.py:2503 — relancer_loyer sans idempotence** : double courriel + désync du niveau sur double-clic/retry ; email envoyé avant le commit. → documenté (P-13).
- **[P2] main.py:251 — CORS credentialed ouvert à tout *.onrender.com et toute extension Chrome** (`allow_credentials=True`, `allow_headers=['*']`). → documenté (P-05).
- **[P2] security.py:90 — JWT irrévocables 24 h/30 j sur python-jose + passlib non maintenus** ; expiry contredit par render.yaml. → documenté (P-05).
- **[P2] quickbooks.py:189 — Race sur la rotation du refresh_token QBO** (singleton sans verrou) : deux refresh concurrents peuvent persister un token déjà invalidé → synchro cassée. (Réévalué P0→P2 : fenêtre de course étroite.) → documenté (P-05).
- **[P2] telephonie/dev — whitelist d'emails hardcodée + gate client-side seul.** → documenté (P-05).
- **[P2] robots.ts:11 — les shells du portail interne ne sont pas en disallow** → URLs internes indexables par Google. → documenté.
- **[P3] kratos.py:155 — IDOR sur les messages Kratos** (confirm/discard par id sans vérifier l'appartenance). Le volet « problèmes » est org-wide par design → pas de fix trivial. → documenté.
- **[P3] scraping_vps/app.py:83 — require_api_key laisse tout passer si la clé est vide, sans warning au boot** (risque borné par l'infra docker-compose/bind localhost). → documenté.
- **[P3] valider-demande:31 — champ interne intake_data (blob Léa) exposé dans le payload public.** → documenté.
- **[P3] sign-nda:343 — HTML du NDA injecté via dangerouslySetInnerHTML sans DOMPurify** (stored-XSS conditionné au backend). → documenté (P-05).
- **[P3] browser-extension/manifest.json:38 — content script injecté sur tout *.onrender.com + postMessage sans contrôle d'origine.** → documenté (P-05).

#### Bug

- **[P0] session.py:484 — init_db neutralisé et rollback silencieux.** La FK cassée (`immeubles.id` au lieu de `imm_immeubles.id`) fait lever `create_all` à chaque boot → tout le bloc ALTER/backfill/seed (l.487-3006) ne s'exécute jamais ; par ailleurs il tourne en une seule transaction dont le premier échec avorte tout en silence. → documenté (déjà couvert par P-02).
- **[P1] session.py:308 — backfill « bons legacy→interne » avec WHERE non stable** : mute tout bon *construction* futur (créé hors-UI) en *interne* à chaque boot, sortant un bon envoyé du flux signature. → documenté (gater par applied_backfills).
- **[P1] public_soumission.py:534 — public_reject sans garde d'état** : une soumission acceptée (projet + facture d'acompte déjà émis) peut être basculée en REJECTED via le vieux lien courriel. → corrigé cette nuit (409 aligné sur public_bon).
- **[P1] public_soumission.py:274 — public_accept re-jouable** : re-POST accept écrase la signature (preuve légale) et, en concurrence, crée 2 projets + 2 factures d'acompte (pas d'unique sur `soumission_id`). → corrigé cette nuit (ajouter ACCEPTED à la garde 409).
- **[P1] facture_send.py:155 — re-envoi force status=SENT sans regarder l'état** : une facture PAYÉE re-envoyée redevient « sent » et re-rentre dans le cron de relances (le client payé reçoit des rappels) ; idem soumission signée et bon signé. → corrigé cette nuit (garde d'état sur les 3 services send_*).
- **[P1] project_to_facture.py:191 — facturation progressive : already_billed compte les factures VOID** → après annulation d'une facture d'étape, delta = 0 → blocage/sous-facturation. → corrigé cette nuit (exclure VOID).
- **[P1] follow_up_reminders.py:116 — alerte SLA « lead non rappelé » re-spammée à chaque run horaire** pour tous les leads sans follow-up auto (sources Meta/téléphone à haut volume). (Réévalué P0→P1.) → corrigé cette nuit (dédup sur Notification existante).
- **[P1] cron_runner.py:756 — le toggle « Synchro iCal » du hub est inopérant** : les vrais chemins prod n'appellent jamais `is_automation_enabled` ; couper le toggle ne coupe rien. → corrigé cette nuit (garde fail-open).
- **[P2] facture_import.py:183 / project_to_facture.py:270 — import punches/achats sans verrou** : deux requêtes concurrentes facturent deux fois les mêmes heures/achats (TOCTOU). → documenté (FOR UPDATE + tests, pas un patch aveugle).
- **[P2] devlog.py:2056 — import-sources facture sans idempotence** : double-facturation possible ; la vraie clé d'idempotence exige une migration. → documenté (P-13).
- **[P2] projects.py:444 — générateur BT-AAMMJJ-HHMMSS dupliqué** : collision à la seconde → IntegrityError 500 (colonne unique), drop silencieux côté auto. → documenté (P-12).
- **[P2] facture_dedupe.py:133 — fusion de doublons de factures perd paiements/items** quand les deux côtés portent des paiements. → documenté.
- **[P2] session.py:1888 — rétro-lien projects↔soumissions heuristique rejoué à chaque boot** (mauvaise liaison possible, re-liaison forcée). → documenté (P-06).
- **[P2] global-search.tsx:63 — race « fetch dans useEffect »** : réponses hors-ordre écrasent les résultats à jour (recherche topbar, partout). → corrigé cette nuit (flag de fraîcheur).
- **[P2] blog.ts:21 — listArticles/getArticle sans try/catch** → /blog en 500 quand le backend est down (cold start Render). → corrigé cette nuit (try/catch + [] / null).
- **[P2] public-chrome.tsx:16 — 6 routes de signature tokenisées absentes de PORTAL_PREFIXES** → nav marketing autour d'une page de signature externe. → documenté (P-10).
- **[P1] auth.ts:136 — authedFetch rejoue aveuglément toute mutation POST/PUT/DELETE sur erreur réseau** → doublons (factures, etc.), pas d'idempotency-key backend. → corrigé cette nuit (ne retenter que GET/HEAD).
- **[P3] session.py:1873 — ventilation TPS/TVQ au boot écrase en 0,00 $ les achats aux taxes pas encore saisies** (WHERE non borné). (Réévalué P2→P3.) → corrigé cette nuit (AND amount_taxes IS NOT NULL).
- **[P3] purchase_order_actions.py:322 — convert-to-achat non idempotent** (un PO FULFILLED reste convertible → doublons de lignes Achat ; QBO déjà protégé par DocNumber). (Réévalué P1→P3.) → documenté.
- **[P3] purchase_order_actions.py:400 — autopush QBO via asyncio.create_task sans référence** (task GC-able). (Réévalué P2→P3.) → corrigé cette nuit (BackgroundTasks).
- **[P3] devlog.py:797 — PATCH générique permet status='payee' en contournant paid_at et l'audit .paid.** → documenté.
- **[P3] sources/page.tsx:315 — provPollRef jamais nettoyé au démontage** (fuite d'interval + requêtes fantômes). → corrigé cette nuit.
- **[P3] DriveFolderExplorer.tsx:1698 — locale /fr/ hardcodée** dans un lien (mauvaise locale en 'en'). → corrigé cette nuit (Link next-intl).
- **[P3] DriveFolderExplorer.tsx:515 — race de navigation Drive** : liste ≠ dossier du breadcrumb (incohérence UI, pas de corruption). (Réévalué P2→P3.) → documenté.
- **[P3] dev-logiciel/projets/[id]/page.tsx:229 — auto-save : une modif faite pendant un save en vol n'est pas re-planifiée** (fenêtre de perte). → corrigé cette nuit.
- **[P3] auth.ts:158 — sur 401, redirection PUIS `return res`** (la page traite quand même le 401) ; AbortError re-fetché. (Réévalué P1→P3.) → documenté.
- **[P1] renovation/[service]/[city]/page.tsx:148 — landing SEO pointent vers 5 pages /services inexistantes (404)** : CTA mort + breadcrumb JSON-LD cassé sur ~275 pages. → documenté (P-03 ; décision produit).

#### Duplication

- **[P2] session.py:144 — ~25 colonnes dupliquées entre critical_columns et additive_columns** (dérive de type/défaut garantie à terme). → documenté (P-08).
- **[P2] immobilier.py:1926 — état de compte PDF vs fiche locataire : ~50 lignes de fetch/totaux dupliquées** (risque PDF ≠ fiche). → documenté (P-14).
- **[P2] project_to_facture.py:262 — blocs punches+achats→items dupliqués** entre project_to_facture et facture_import (~140 lignes), 3e variante dans bon_send. (Réévalué : fix non trivial, divergences kind='extra'.) → documenté.
- **[P2] dev-logiciel/facturation/[id]/page.tsx:43 — TPS_RATE/TVQ_RATE redéclarés en local** au lieu d'importer lib/tax.ts (3 pages). → corrigé cette nuit (display-only, valeurs identiques).
- **[P2] bon/[token]:1 — ~10 pages publiques à token réimplémentent le même squelette** copié-collé. → documenté (P-16).
- **[P3] devlog.py:1753 — _public_base_url réimplémenté localement** (Nème copie du helper). → corrigé cette nuit (copies strictement identiques seulement).
- **[P3] immobilier.py:113 / entreprises.py:37 — _require_volet copié dans 6 endpoints** (devrait être une factory Depends). → documenté (P-07).
- **[P3] immobilier.py:2632 — fenêtre légale QC de renouvellement encodée en 3 endroits divergents.** → documenté.
- **[P3] facture_reminders.py:135 — taux TPS/TVQ re-hardcodés dans 12+ fichiers** hors de core/taxes.py. (Réévalué P1→P3 ; changement de taxe quasi inexistant.) → documenté (P-14).
- **[P3] construction-renovation-montreal:1 — page pilier SEO réimplémente le squelette de seo-pillar-template** au lieu de le consommer. → documenté.
- **[P3] dev/page.tsx:16 — DEV_ALLOWED_EMAILS dupliqué à l'identique** entre dev/page et login-form. → corrigé cette nuit.
- **[P4] session.py:1875 — taux 5.0/14.975 re-hardcodés en SQL.** (Réévalué P3→P4 ; reconstruction naïve casserait le ratio.) → documenté.
- **[P4] public_soumission.py:166 — taux 0.05/0.09975 re-hardcodés dans la vue publique** (mais identiques au PDF). (Réévalué P3→P4.) → documenté.

#### Code-mort

- **[P1] dev-logiciel/projets/[id]/page.tsx:969 — ~4000 lignes de composants d'onglets jamais rendus** dans le fichier de 8082 lignes (vestige de la fusion construction→devlog). → documenté (P-17 ; grosse suppression, PR dédiée).
- **[P2] lea-chat-widget.tsx:78 — widget Léa détaché (aucun montage, backend câblé = régression probable) + 4 autres composants orphelins (~40 Ko).** (Action réévaluée fix→document : Léa exige un arbitrage.) → documenté (les 4 autres sont supprimables).
- **[P2] monday_bridge.py:1 — monday_bridge + monday_client morts en runtime** (seul un script de migration terminée les importe). → documenté (P-15).
- **[P2] teams_sync_auto.py:1 — doublonne teams_meeting_sync, déclenché par rien.** → documenté (P-15).
- **[P2] backend/scripts/:1 — scripts one-shot Monday (692+611 l.) + create_admin/init_admin legacy** non référencés par le déploiement. → documenté (P-15).
- **[P3] project_to_facture.py:108 — _build_ref() (FAC-…-HHMMSS) : générateur de référence mort.** → corrigé cette nuit (6 lignes).
- **[P3] config.py:135 — settings.claude_model sans aucun consommateur** (CLAUDE_MODEL poussé 3× par render.yaml en pure perte). → corrigé cette nuit (extra='ignore' → suppression invisible).
- **[P3] json-ld.tsx:19 — orphelin (aucun import) + référence /og-image.jpg inexistant.** (Action réévaluée fix→document : documenté dans ARCHITECTURE.md + TODO vivant.) → documenté.
- **[P3] entreprises/reglages/equipe/page.tsx:20 — page stub « Section en développement » toujours routée** dans la nav. → documenté.

#### Perf

- **[P2] catalog.py:130 — catalogue d'automatisations désynchronisé (horaires faux)** : punch_auto_close « 23h » vs 22 h réel, facture_reminders « 08h30 » vs 02:00 UTC. (Champ purement descriptif.) → corrigé cette nuit (2 libellés).
- **[P2] evalweb.py:145 — screenshots debug écrits dans /tmp à chaque scrape, jamais nettoyés, sans flag** (borné par écrasement + taille disque). (Réévalué P2→P3.) → corrigé cette nuit (gate SCRAPE_DEBUG).
- **[P3] immobilier_extras.py:277 — renouvellements_overview : N+1 (4 requêtes par bail).** (Réévalué P2→P3.) → corrigé cette nuit (batch in_(), pattern voisin).
- **[P3] immobilier.py:1016 — maintenance_rollup charge tout l'historique puis filtre l'année en Python.** → corrigé cette nuit (borne SQL).
- **[P3] LeadAnalysisDetailModal.tsx:736 — useMemo hero dépend de `data` entier → JSON.parse à chaque frappe.** → corrigé cette nuit (deps étroites).
- **[P3] comparables.py:401 — ingestion des comparables : ~2 requêtes par item sur mtl_property_units (500k lignes).** → documenté.
- **[P3] LeadAnalysisDetailModal.tsx:3306 — fraisRows useMemo : 3 JSON.stringify dans les deps à chaque render.** → documenté.
- **[P4] notifications.py:67 — notify_role charge tous les users et filtre le rôle en Python.** (Réévalué P3→P4 ; volume faible, dédup existante côté callers.) → documenté.
- **[P4] telephonie/page.tsx:1432 — marquage lu des SMS : un POST par message non lu** (auto-limité, non rejoué). (Réévalué P3→P4.) → documenté.

#### Qualité

- **[P2] router.py:186 — ~15 contraintes d'ordre d'enregistrement de routers portées uniquement par des commentaires** (un réordonnancement casse des endpoints en 422/404 sans échec CI). → documenté (P-09 ; test smoke).
- **[P3] session.py:43 — get_db committe systématiquement en fin de requête, y compris les GET** (contrat transactionnel implicite dangereux). → documenté (P-08).
- **[P3] public_offer.py:147 — read_offer (GET public) mute le statut et flush** (écriture sur un GET, dépend de l'auto-commit). → documenté (P-08).
- **[P3] devlog_invoice_pdf.py:82 — compute_invoice_totals (calcul officiel des totaux) vit dans le module PDF.** (Réévalué P1→P3 ; housekeeping.) → documenté (P-14).
- **[P3] dev-logiciel/projets/[id]/page.tsx:5657 — taux horaire 75 $/h en dur dans un libellé, désynchronisé du calcul backend.** → documenté.
- **[P3] auth.ts:164 — la redirection 401 n'attache pas ?next= → l'utilisateur perd sa page.** → documenté.

### 4.3 Réfutés / écartés par la contre-expertise

- **« Job de relances des factures Dév. logiciel jamais déclenché en prod (argent non collecté) » — RÉFUTÉ.** Faux : `render.yaml:206-215` définit bien un cron Render Blueprint `h2-0-devlog-facture-reminders` (13:30 UTC = 09:30 Montréal, exactement l'horaire annoncé au catalogue). Les factures SONT relancées chaque jour ; le « fix » proposé aurait créé un second déclencheur → doublons de courriels.
- **« AI_MODEL appliqué à tous les providers casse le provider primaire (Gemini) » — RÉFUTÉ (comme bug vivant).** `AI_MODEL` n'est défini nulle part dans la config déployée → chaque provider retombe sur son défaut, Gemini fonctionne. La casse exige un footgun auto-infligé (poser `AI_MODEL=claude-*` en gardant `AI_PROVIDER=gemini`) ; et le piège est **déjà documenté** dans `ARCHITECTURE.md:570`. Design-smell documenté, pas un bug P1.

Par ailleurs, plusieurs findings ont été **conservés mais rétrogradés** par la contre-expertise (voir mentions « Réévalué » ci-dessus) : le fix « double-dépense QBO sur PO » (déjà protégé par le dédup DocNumber), le « refresh token QBO qui bricke l'intégration » (P0→P2, fenêtre de course étroite), le « spam SLA » (P0→P1), la « ventilation TPS/TVQ » (P2→P3), et plusieurs refactors « fix cette nuit » requalifiés en « documenter » quand le correctif s'est avéré toucher un contrat, un schéma ou une décision produit (ex. facture_import FOR UPDATE, import-sources devlog, guards d'écriture projets, duplication des blocs de facturation).

## 5. Actions réalisées (commits)

*(liste finale en fin de nuit)*

## 6. Bugs corrigés vs bugs documentés

*(liste finale en fin de nuit)*

## 7. Propositions non exécutées

Voir `docs/PROPOSITIONS.md` (changements risqués : migrations, réécritures massives, major bumps, contrats MCP).

## 8. Prochaines étapes recommandées

*(en fin de nuit)*
