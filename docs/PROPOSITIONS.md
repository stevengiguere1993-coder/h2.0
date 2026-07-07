# Propositions — changements risqués NON exécutés cette nuit

> Compagnon de `AUDIT_RAPPORT.md`. Chaque proposition : description, bénéfice, risque,
> effort, priorité (P0 = urgent → P3 = un jour), et plan d'exécution pas à pas.
> Rien de ce qui est listé ici n'a été modifié dans le code cette nuit.

## P-01 — Environnement de STAGING : tester une branche avant de merger dans `main` (P0)

**Le besoin (Phil)** : « tester mes branches quelque part avant de les push sur le main ».

**État des lieux (vérifié cette nuit)** :
- La prod tourne sur Render : `h2-0` (API FastAPI) + `h2-0-web` (Next.js) + crons, tous branchés sur `main` (`render.yaml` + deploy hooks via `.github/workflows/deploy.yml`).
- Vercel déploie bien des *previews* par PR, mais elles sont **protégées par SSO Vercel** (302 vers vercel.com/sso-api) : Phil ne peut pas les ouvrir, et le projet Vercel (`monagentmonday-proxy`) n'est de toute façon pas le vrai front de prod.
- Il n'existe aujourd'hui **aucun** environnement où cliquer dans l'app sur une branche.

**Proposition (option recommandée — paire de services staging sur Render)** :
1. Créer une branche permanente `staging` sur GitHub.
2. Dans le dashboard Render : dupliquer les deux services web →
   - `h2-0-staging` (runtime python, rootDir `backend`, branch `staging`, mêmes build/start commands) ;
   - `h2-0-web-staging` (runtime node, rootDir `frontend`, branch `staging`, env `NEXT_PUBLIC_API_BASE_URL=https://h2-0-staging.onrender.com`).
3. **Base de données séparée obligatoire** : créer un Postgres Render dédié staging (ou une DB `kratos_staging` sur la même instance) et pointer `DATABASE_URL` du backend staging dessus. **Jamais la DB de prod.** Au premier boot, `init_db`/`ensure_*` créent le schéma ; se connecter et créer un utilisateur test.
4. Renseigner uniquement les env vars nécessaires au test (JWT_SECRET distinct ; laisser vides les clés QBO/Twilio/Graph pour éviter tout envoi réel depuis staging — le code les traite déjà en best-effort).
5. Flux d'utilisation : je pousse la branche de travail → `git push origin ma-branche:staging --force` (ou PR ma-branche→staging mergée) → Render redéploie staging → Phil clique sur `https://h2-0-web-staging.onrender.com` → si OK, merge vers `main`.
- **Bénéfice** : test réel cliquable, isolé de la prod, réutilisable pour toutes les grosses tâches.
- **Risque** : quasi nul (services isolés). Coût : 0 $ sur plan free (avec cold starts ~30-60 s) ou ~14 $/mois pour deux services starter sans sommeil.
- **Effort** : ~30-45 min dans le dashboard Render (je ne peux pas le faire moi-même — pas d'accès au dashboard ; je peux préparer le `render.yaml` si tu préfères la voie Blueprint).
- **Alternative A** : Render *Preview Environments* par PR (automatique, mais fonctionnalité payante et DB par preview à gérer).
- **Alternative B** : désactiver la protection SSO des previews Vercel (Settings → Deployment Protection) — utile pour le FRONT seul, mais les previews pointeraient sur l'API de prod : à réserver aux changements purement visuels.

**Pour la branche de cette nuit** (`refactor/nuit-audit-2026-07-06`) : une PR *draft* sera ouverte — la CI (tsc + lint + 79 tests) y tourne déjà ; dès que le staging existe, `git push origin refactor/nuit-audit-2026-07-06:staging` permet de cliquer dans l'app avant merge.

---

## P-02 — 🔴 FK cassée qui casse `init_db` en prod depuis 26 jours (P0 — le plus important de la nuit)

**Le bug (prouvé empiriquement)** : `backend/app/models/immobilier.py:609` déclare `ForeignKey("immeubles.id")` alors que la table s'appelle `imm_immeubles` (`immobilier.py:104`). C'est la **seule** FK cassée du schéma (56 tables-cibles vérifiées). Conséquence : `Base.metadata.create_all()` lève `NoReferencedTableError`, donc **`init_db()` plante dès son début** (`session.py:485`) et l'erreur est **avalée silencieusement** au boot (`main.py:43-45`, log `warning`).

**Introduit le 2026-06-10** (commit `e8a15f28`, PR #784 « dépenses par immeuble + P&L »). **~26 jours** que `init_db` ne finit plus. Le schéma prod ne tient QUE grâce aux filets `ensure_critical_columns` + `ensure_*_tables` — c'est fragile, et ça explique la prolifération de ces filets.

**Symptômes actuels en prod** (probables, à cause de la panne) :
- Table **`immeuble_depenses` jamais créée** (même PR, aucun `ensure_*_tables` ne la couvre) → la page « dépenses par immeuble / P&L annuel » de la Gestion locative est probablement en **erreur 500 depuis 26 jours**.
- Toute **colonne** ajoutée à `init_db` après le 2026-06-10 et absente de `ensure_critical_columns` **manque en prod** → risque de 500 épars.

**Le fix (une ligne)** : `ForeignKey("immeubles.id"...)` → `ForeignKey("imm_immeubles.id"...)`.

**Pourquoi je ne l'ai PAS appliqué cette nuit (malgré la sévérité)** : corriger la FK **réarme `init_db` en entier** au prochain déploiement, pour la 1re fois depuis 26 jours. L'analyse détaillée (verdict archivé) confirme que **tout est additif et non destructif** (la migration destructrice d'avril est morte/commentée, aucun DELETE), MAIS **3 backfills one-shot** vont s'exécuter pour la 1re fois, dont un **visible pour les utilisateurs** — ce qui viole la consigne « rien ne change pour l'utilisateur ». Et ce risque **n'est pas testable sur staging** (DB staging vierge → `init_db` y tourne proprement ; le risque n'existe que sur la vraie DB prod de 26 jours). Donc : déploiement **supervisé**, pas un merge silencieux.

**Les 3 backfills one-shot à trancher AVANT déploiement** (gardés par la table `applied_backfills`, qui n'existe pas encore en prod → aucun marqueur posé → ils tourneront) :
1. **🔴 Rotation 90° de TOUS les reçus** (`session.py:1969-1992`, marqueur `rotate_existing_receipts_cw90_v1`) : conçu pour des reçus scannés AVANT une correction d'orientation. Les reçus scannés **depuis le 2026-06-10 sont déjà droits** → ils seraient **pivotés à tort** (couchés). Cosmétique, non destructif, mais **visible**. **Recommandation : neutraliser ce backfill** avant le déploiement en pré-insérant son marqueur dans `applied_backfills` (voir plan), OU re-pivoter à la main le petit lot de reçus des ~26 derniers jours après coup.
2. **is_billable par type de projet** (`session.py:1935-1954`, marqueur `achat_is_billable_by_project_type_v1`) : écrase le flag « refacturable » de tous les achats liés à un projet. Les ajustements manuels faits depuis 26 jours seront **écrasés une fois**. Réversible (booléen). À valider avec Phil : des achats ont-ils été cochés/décochés à la main récemment ?
3. **Retag facture_items 'extra'** (`session.py:2002-2034`, marqueur `retag_extra_facture_items_v1`) : bien ciblé par préfixe, corrige un vrai bug de calcul. Bas risque, laisser tourner.

**Bénéfice** : répare le moteur de migration au boot (fin de la dépendance aux filets), crée `immeuble_depenses` (P&L locatif remonte), crée les colonnes manquantes (moins de 500).
**Risque** : moyen au 1er déploiement (uniquement les 3 backfills ci-dessus) ; nul ensuite. **Effort** : 10 min de code + un déploiement surveillé.

**Plan d'exécution (supervisé, quand Phil est dispo)** :
1. Sur la branche, corriger la FK (1 ligne) + ajouter un smoke test qui vérifie que `Base.metadata.create_all()` passe (garde-fou anti-régression).
2. **Neutraliser la rotation des reçus** : ajouter dans `init_db`, juste après la création de `applied_backfills` (l.1923-1927), un `INSERT INTO applied_backfills(key) VALUES ('rotate_existing_receipts_cw90_v1') ON CONFLICT DO NOTHING` **conditionnel** (seulement si des reçus existent déjà — ils existent), pour que la rotation soit sautée. (Alternative : re-pivoter à la main après coup.)
3. Décider avec Phil pour `is_billable` (#2) : neutraliser aussi, ou laisser réappliquer le défaut.
4. Déployer à un moment calme, surveiller le boot, **vérifier** : `immeuble_depenses` créée, page P&L locatif OK, orientation de quelques reçus récents OK.

---

## P-04 — 🔴 Escalade de privilège admin → owner (création de compte + set-password) (P0)

**Le problème (vérifié)** : deux chemins permettent à un compte **admin** (rang 3) de franchir la frontière vers **owner** (rang 4, le rang maximum : gestion des users/rôles, import/purge de données) :
1. **Création ex nihilo** : `POST /auth/register` (gardé par le legacy `CurrentAdmin`) et `POST /users` (gardé par `RequireAdminRole`) acceptent un `UserCreate.role` contrôlé par l'appelant, appliqué tel quel par `UserRepository.create` — aucune comparaison de rang. Un admin crée un compte `role='owner'` avec un mot de passe qu'il choisit, puis se connecte dessus (`auth.py:78`, `users.py:226`, `repositories/user.py:77-88`).
2. **Réinitialisation** : `POST /users/{id}/set-password` (`users.py:413`), `force_password_change` (l.516) et `update_volets` (l.310) sont gardés par `RequireAdminRole` (admin **ou** owner) et ne comparent jamais le rôle de la **cible** : un admin réinitialise le mot de passe d'un owner et se connecte en owner.

L'asymétrie est flagrante : `update_role` (promotion d'un compte existant) exige pourtant `RequireOwner`.

**Bénéfice** : ferme une escalade de privilège interne réelle et atteignable.
**Risque** : touche le comportement des permissions (des flux d'admin légitimes existent). Faible si on ne bloque que « rôle cible/créé ≥ le sien ».
**Effort** : petit-moyen.
**Priorité** : **P0**.

**Plan d'exécution** :
1. `set-password` / `force_password_change` / `update_volets` : avant l'écriture, `if ROLE_RANK[u.role] > ROLE_RANK[actor.role]: 403 « impossible d'agir sur un compte de rang supérieur »`. *(Ce point 1 est assez borné pour être fait dès cette nuit ; le reste ci-dessous reste supervisé.)*
2. `create_user` et `register` : `if data.role and ROLE_RANK[data.role] > ROLE_RANK[actor.role]: 403`.
3. Idéalement, passer `/auth/register` sous `RequireOwner` (ou le supprimer : c'est un doublon de `POST /users`).
4. Ajouter un test qui vérifie qu'un admin ne peut ni créer un owner ni lui reset le mot de passe.
5. Brancher l'audit log (voir corrections de nuit `users.py`) sur ces transitions.

---

## P-03 — Landing pages SEO : 5 pages `/services/{slug}` inexistantes → 404 sur ~275 pages (P1)

**Le problème (vérifié)** : `SEO_SERVICES` contient 8 slugs mais seules 3 pages `/services` existent (`cuisine`, `salle-de-bain`, `multilogement`). Sur `renovation/[service]/[city]/page.tsx`, le CTA « Voir le service complet » (l.148, avec un cast `as "/services"` qui trahit le problème) **et** le breadcrumb JSON-LD (l.96) sont émis pour les 8 services. Pour les 5 manquants (`complete`, `agrandissement`, `sous-sol`, `fenetres`, `terrasse`) × 55 villes = **~275 landing pages** avec CTA mort (404) et données structurées cassées — précisément les pages dont l'unique but est le SEO. `sitemap.ts` ne liste d'ailleurs que les 3 pages réelles.

**Bénéfice** : supprime les 404 crawlés par Google (warnings Search Console) et les CTA morts sur les pages d'acquisition.
**Risque** : comportement visible → décision produit.
**Effort** : moyen (créer 5 pages) ou petit (relink).
**Priorité** : **P1**.

**Plan d'exécution** :
1. **Option A (préférée si le contenu existe)** : créer les 5 pages `/services/{slug}` (elles boostent aussi le SEO).
2. **Option B (rapide)** : ne rendre le CTA `/services/{slug}` et le breadcrumb niveau 2 **que** si le slug ∈ whitelist des 3 pages réelles ; sinon lier vers le pilier `/services` (ou omettre le niveau 2).
3. Dériver la whitelist d'une source unique partagée avec `sitemap.ts` pour éviter la récurrence.

---

## P-05 — Durcissement sécurité transverse : CORS, JWT, crypto, secrets, XSS, extension (P2)

**Regroupe** plusieurs constats sécurité indépendants, tous « non-cette-nuit » car ils touchent des contrats, des dépendances ou une coordination externe :
- **CORS trop ouvert** (`main.py:251`) : `allow_origin_regex` accepte tout `*.onrender.com` + toute extension Chrome, avec `allow_credentials=True` et `allow_headers=['*']`.
- **JWT irrévocables + crypto en fin de vie** (`security.py`, `requirements.txt`) : pas de `jti`/révocation (token volé valide 24 h–30 j) ; `python-jose` (CVE 2024) et `passlib` abandonné ; expiry contredit par `render.yaml`.
- **Refresh token QBO en clair / race de rotation** (`quickbooks.py:189`) : singleton sans `asyncio.Lock` → deux refresh concurrents peuvent persister un token invalidé.
- **Whitelists d'emails hardcodées côté client** (`telephonie/page.tsx:51`, `dev/page.tsx:16`).
- **NDA injecté sans DOMPurify** (`sign-nda:343`).
- **Extension injectée sur tout Render + postMessage sans contrôle d'origine** (`manifest.json:38`, `content-h20.js`).

**Bénéfice** : réduit nettement la surface d'attaque (interne et publique).
**Risque** : variable ; CORS/whitelists exigent des IDs/hosts réels, JWT-révocation est un changement d'architecture.
**Effort** : moyen (par lot).
**Priorité** : **P2**.

**Plan d'exécution** :
1. CORS : `^https://(h2-0|h2-0-web)(-[a-z0-9]+)?\.onrender\.com$` + `chrome-extension://<ID exact>` (obtenir l'ID de l'extension Horizon).
2. QBO : ajouter `self._refresh_lock` (double-checked) dans `_access()`.
3. Crypto (court terme) : épingler `python-jose>=3.4` (ou migrer PyJWT), remplacer `passlib` par `bcrypt` direct, aligner `render.yaml` sur 1440.
4. Whitelists : exposer un flag/rôle serveur via `/auth/me`, retirer les listes en dur.
5. NDA : `DOMPurify` avant injection + vérifier l'échappement backend des champs interpolés.
6. Extension : restreindre le match au host exact du front + valider `event.origin`.
7. JWT-révocation (long terme) : `jti` + table de révocation, ou rotation du `jwt_secret` par user.

---

## P-06 — Chaos des backfills de boot : `init_db` rejoue des migrations non bornées à chaque démarrage (P2)

**Le problème (vérifié)** : une douzaine de backfills full-scan sont rejoués à **chaque boot** (`session.py:1720-1961`) au lieu du pattern `applied_backfills` one-shot **déjà présent dans le même fichier** (utilisé seulement 3 fois). Conséquences : coût de boot croissant avec les données, fenêtre de verrous `ACCESS EXCLUSIVE` à chaque déploiement, et surtout **des UPDATE qui mutent des lignes futures non bornées** — le rétro-lien projects↔soumissions heuristique (l.1888, mauvaise liaison possible), et le backfill « bons legacy→interne » (l.308, sort un bon du flux signature). Même famille que l'incident d'avril 2026 (bloc désactivé l.1606-1615).

**Bénéfice** : boot plus rapide, moins de verrous, fin des mutations silencieuses de données futures.
**Risque** : toucher de nombreux backfills ; garder les nettoyages volontairement auto-réparateurs (orphelins).
**Effort** : moyen.
**Priorité** : **P2** (dépend de P-02 pour que `init_db` tourne à nouveau).

**Plan d'exécution** :
1. Migrer chaque UPDATE **stable** vers une clé `applied_backfills` (`project_soumission_retrolink_v1`, `bons_legacy_interne_v1`, …).
2. Pour les nettoyages récurrents volontaires (orphelins facture_item_id), ajouter les index manquants.
3. Défense-en-profondeur : partager la clé `claim_cron_run('facture-reminders')` entre l'endpoint et le mega-cron all-daily (`cron_runner.py:626`).

---

## P-07 — Trois guards admin divergents + `_require_volet` copié 6× → une seule couche d'autorisation (P1)

**Le problème (vérifié)** : `deps.py:79` — `get_current_admin` (legacy, `is_admin` seul) coexiste avec `get_current_admin_role` (rang ≥ 3) et `get_current_admin_or_owner`. Un user `is_admin=TRUE` / `role='manager'` passe les ~50 endpoints encore sur `CurrentAdmin` (dont la gestion des rôles, QBO, la téléphonie) mais est refusé ailleurs : **le périmètre admin dépend du guard choisi par fichier, pas du rôle**. En parallèle, `_require_volet` est copié à l'identique dans 6 endpoints (`immobilier.py:113`, `entreprises.py:37`, …) et appelé à la main dans ~30 routes (oubli = fuite d'accès inter-volet silencieuse).

**Bénéfice** : périmètre d'autorisation cohérent et structurellement garanti (Depends au niveau router, pas d'appel manuel).
**Risque** : changement d'autorisation visible → tester sur les comptes réels d'abord.
**Effort** : moyen.
**Priorité** : **P1**.

**Plan d'exécution** :
1. Faire de `get_current_admin` un alias strict de `_require_min_role('admin')` (supprimer la branche `is_admin`), puis déprécier la colonne `is_admin`.
2. Créer `require_volet(name)` (factory → Depends 403) dans `deps.py`, l'appliquer au niveau router (`dependencies=[...]`), remplacer les 6 copies.
3. Tests d'autorisation sur les endpoints sensibles (user_roles, qbo_oauth, voice).

---

## P-08 — Refactoring de `session.py` (3018 l.) et du contrat transactionnel `get_db` (P2)

**Le problème (vérifié)** : `session.py` est le moteur de migration maison (pas d'Alembic) et concentre plusieurs dettes : ~25 colonnes **dupliquées** entre `critical_columns` et `additive_columns` (l.144, dérive de type/défaut garantie), le bloc `init_db` en une transaction unique (voir P-02), et surtout `get_db` (l.43) qui **committe systématiquement en fin de requête, y compris les GET** — contrat transactionnel implicite qui persiste toute mutation ORM « pour voir » (ex. `read_offer` mute et flush sur un GET public, `public_offer.py:147`).

**Bénéfice** : une seule source de définition de colonnes, contrat transactionnel explicite, fichier maintenable.
**Risque** : élevé — changer `get_db` casserait les endpoints qui comptent (volontairement ou non) sur l'auto-commit (ex. `api_key_deps` last_used_at) → cartographier d'abord.
**Effort** : moyen à élevé.
**Priorité** : **P2**.

**Plan d'exécution** :
1. Constante unique `COLUMNS = {...}` avec flag `critical=True/False`, consommée par `ensure_critical_columns` et `init_db`.
2. Cartographier tous les endpoints qui dépendent de l'auto-commit.
3. Introduire deux dépendances `DBSession` (RW, commit explicite) / `DBSessionRO` (lecture seule) et migrer progressivement ; corriger `read_offer` (calculer l'expiration sans muter) et `sign_offer` (commit explicite).

---

## P-09 — Filet de tests API/HTTP (invariants d'ordre de routers, auth, CRUD) (P2)

**Le problème (vérifié)** : la couverture actuelle = 6 fichiers de tests de calculs purs, **0 test d'API/HTTP**. Or `router.py:186` porte ~15 contraintes d'ordre d'`include_router` uniquement dans des commentaires (`punch_ops` avant `punch_router`, `prospection_lists` avant `/prospection/{lead_id}`, …) : un simple réordonnancement (tri d'imports) casse des endpoints en 422/404 **sans échec CI**.

**Bénéfice** : verrouille des invariants aujourd'hui invisibles ; ouvre la voie à couvrir auth et facturation (les corrections de nuit sur les machines à états gagneraient un filet).
**Risque** : nul (ajout de tests).
**Effort** : petit pour le smoke d'ordre, moyen pour la couverture auth/CRUD.
**Priorité** : **P2**.

**Plan d'exécution** :
1. Test smoke : construire l'app, vérifier que `app.router` résout une liste de paths sensibles (`/api/v1/punch/me`, `/prospection/lists`, `/factures/1/payments`) vers le bon `endpoint.__name__`.
2. Étendre progressivement aux flux corrigés cette nuit (guards de statut public_soumission/facture_send, garde de rang set-password).

---

## P-10 — Flux signature par token : expiration, périmètre chrome, punches concurrents (P2)

**Le problème (vérifié)** : les liens de signature tokenisés (`public_soumission`, `public_bon`, factures) **n'expirent jamais** et `valid_until` n'est pas appliqué — une soumission périmée par date reste signable à vie (engagement contractuel sur des prix qui ne tiennent plus). Par ailleurs 6 routes de signature (`/bon`, `/soumission`, `/sign-bail`, `/sign-devlog`, `/sign-nda`, `/sign-offer`) sont absentes de `PORTAL_PREFIXES` → un destinataire externe voit la nav marketing enroulée autour de la page de signature. Enfin, aucune contrainte DB n'empêche deux punches ouverts simultanés (check applicatif seul).

**Bénéfice** : cohérence et sécurité des flux de signature (les documents les plus sensibles, signés par des clients).
**Risque** : comportement visible (l'expiration peut bloquer un client légitime en retard → valider avec Phil).
**Effort** : moyen.
**Priorité** : **P2**.

**Plan d'exécution** :
1. `public_accept` : `if valid_until and now > valid_until → 409 « Soumission expirée »` (à valider).
2. Politique d'expiration/rotation des `signature_token`.
3. Ajouter les 6 routes à `PORTAL_PREFIXES` (idéalement dérivées d'une source unique).
4. Index unique partiel `punches(employe_id) WHERE ended_at IS NULL` (via `ensure_critical_columns`).

---

## P-11 — Alignement des guards d'écriture (projets, factures, immobilier) sur RequireManager + scope (P1)

**Le problème (vérifié)** : la politique maison est `AuthWrite = RequireManager` (business.py) pour tout le CRUD, mais les endpoints d'**action** l'outrepassent avec `CurrentUser` : `projects.py:380` (DELETE projet, sans vérif de rôle **ni** de visibilité), `facture_items.py` (éditer/supprimer les lignes d'une facture, même PAYÉE), `project_to_facture`, `facture_send`, `bon_send`. Côté immobilier, `_require_immeuble_visible` est appliqué de façon incohérente : `DELETE picker` (l.326) et `list_baux_for_immeuble` (l.2117) lisent/mutent hors périmètre. Bref, la surface d'attaque interne dépend du fichier.

**Bénéfice** : ferme les escalades internes employé→manager sur des écritures financières et destructives.
**Risque** : décision métier — le kanban projets fait des PUT (des employés déplacent-ils des cartes ?). Serrer PUT/DELETE change un contrat de comportement potentiellement utilisé.
**Effort** : moyen (inventaire d'usage + alignement).
**Priorité** : **P1**.

**Plan d'exécution** :
1. Inventorier l'usage réel (télémétrie / logs) des PUT projet par des employés.
2. Aligner : `DELETE projet` + mutations facture/envoi → `RequireManager` ; `DELETE picker` + `list_baux` → `_require_volet` + `_require_immeuble_visible` ; filtrer dossier/état-de-compte locataire via `visible_immeuble_ids`.
3. `PUT projet` : trancher avec Phil (garde de statut sur les lignes de facture payée en priorité).

---

## P-12 — Numérotation unifiée des références (collision BT-…/BON-… à la seconde → 500) (P2)

**Le problème (vérifié)** : plusieurs générateurs `strftime("%y%m%d-%H%M%S")` cohabitent (`business.py:229`, `projects.py:444`, `immobilier.py:799`) pour une colonne `reference` **UNIQUE** : deux bons créés dans la même seconde → `IntegrityError` → 500 brut sur `POST /projects/{id}/correction-bon` (drop silencieux côté auto). Le repo se le documente lui-même (`tests/smoke/test_smoke_bons.py`). Le pattern atomique `next_facture_number` existe pour les factures mais pas pour les bons.

**Bénéfice** : élimine un 500 latent + un drop silencieux ; source unique de numérotation.
**Risque** : introduit un helper partagé + retry (nouvelle logique de contrôle).
**Effort** : moyen.
**Priorité** : **P2**.

**Plan d'exécution** :
1. Factoriser `generate_bt_reference(db)` (retry sur collision : suffixe `-2` / re-strftime) utilisé par `projects.py` **et** `business.py`.
2. Entourer `POST correction-bon` d'un catch `IntegrityError` → retry. Format visible inchangé (`String(32)` a la place pour un suffixe).

---

## P-13 — Idempotence des envois et imports (relances loyer, import-sources facture) (P2)

**Le problème (vérifié)** : plusieurs actions à effet externe ou financier ne sont pas idempotentes et s'exposent au double-clic / au retry réseau : `relancer_loyer` (`immobilier.py:2503`, double courriel + double ligne de niveau, email envoyé **avant** le commit) et `import-sources` facture devlog (`devlog.py:2056`, somme de toutes les heures à chaque appel → total gonflé). La vraie clé d'idempotence de l'import exige des colonnes `source_project_id`/`source_soumission_id` inexistantes → **migration**.

**Bénéfice** : évite double courriel au locataire (preuve TAL) et double-facturation au client.
**Risque** : effet visible (email) + migration de schéma (piège `ensure_critical_columns`) + décision refuse-vs-replace en tenant compte des imports multi-projets légitimes.
**Effort** : moyen.
**Priorité** : **P2**.

**Plan d'exécution** :
1. `relancer_loyer` : verrou pessimiste (SELECT FOR UPDATE sur le bail) ou contrainte unique partielle + upsert, email **après** le commit, court-circuit si relance même niveau < N minutes.
2. `import-sources` : concevoir la clé `(invoice_id, source_kind, project/soumission_id)` + migration des colonnes `source_*` (via `ensure_critical_columns`) + décider refuse-vs-replace.
3. (Cf. aussi `facture_import` FOR UPDATE — TOCTOU sur les imports concurrents, à traiter avec tests Postgres.)

---

## P-14 — « PDF = reflet de la fiche » : sources de calcul communes + taux depuis `core/taxes.py` (P3)

**Le problème (vérifié)** : la règle « le PDF doit refléter la fiche » est fragilisée par des calculs dupliqués. L'**état de compte PDF** locataire recopie ~50 lignes de la fiche dossier (`immobilier.py:1926` vs 1676) avec deux calculs séparés de `loyer_actuel`/`depot_total`/`total_paye`. `compute_invoice_totals` (le calcul **officiel** des totaux de facture devlog) vit dans le module PDF (`devlog_invoice_pdf.py:82`). Et les taux TPS/TVQ sont re-hardcodés dans 12+ fichiers hors de `core/taxes.py` (« source unique de vérité »).

**Bénéfice** : une évolution d'un côté ne fait plus diverger le montant affiché de celui du PDF remis au client/locataire.
**Risque** : touche des surfaces visibles (PDF + fiche) → test de non-régression, montant par montant (les sites diffèrent dans l'ordre d'arrondi ; `test_finance_math` est épinglé).
**Effort** : moyen.
**Priorité** : **P3** (le changement de taux QC est quasi inexistant, d'où la priorité modérée).

**Plan d'exécution** :
1. Extraire `_load_locataire_dossier(db, id)` consommé par la fiche **et** le PDF.
2. Déplacer `compute_invoice_totals` vers `devlog_devis_calc.py` (re-export depuis le module PDF pour compat).
3. Remplacer les littéraux de taux par `TAX_FACTOR`/`TVQ_RATE`/`TPS_RATE`, en **préservant l'ordre d'arrondi de chaque site** (ne PAS toucher aux littéraux SQL de `session.py` où la reconstruction naïve casserait le ratio).

---

## P-15 — Nettoyage de code mort archi-confirmé (backend + frontend) (P2)

**Le problème (vérifié)** : plusieurs modules sont morts en runtime, confirmés par grep : `monday_bridge.py` + `monday_client.py` (importés seulement par un script de migration terminée), `teams_sync_auto.py` (doublonne `teams_meeting_sync`, déclenché par rien), les scripts one-shot Monday (`import_monday*.py`, 692+611 l.) et **3 chemins de bootstrap admin divergents** (`backend/scripts/create_admin.py` + `init_admin.py` vs `backend/app/scripts/create_admin.py`). Côté frontend, 4 composants orphelins supprimables + le **widget Léa détaché** (`lea-chat-widget.tsx`, backend câblé → **régression probable**, une feature publique détachée).

**Bénéfice** : allège la surface (intégration, bundle, hotspots de merge) ; surtout, tranche le sort du widget Léa.
**Risque** : suppressions de fichiers → confirmer qu'aucune relance de migration Monday n'est prévue et que personne ne tape encore `python -m scripts.create_admin` ; **le widget Léa exige un arbitrage** (le remonter = UX publique visible, le supprimer = destruction d'une feature).
**Effort** : petit (par lot).
**Priorité** : **P2**.

**Plan d'exécution** :
1. Signaler à Phil le widget Léa (non monté, backend câblé) → décider **remonter vs supprimer**.
2. Supprimer les 4 orphelins frontend (`json-ld`, `portal-corner`, `measurement-import-modal`, `analysis-defaults-modal`) — noter qu'ils sont référencés dans `ARCHITECTURE.md` (mettre le doc à jour).
3. Supprimer `monday_bridge.py`, `monday_client.py`, `import_monday*.py`, `backend/scripts/create_admin.py`, `init_admin.py`, `teams_sync_auto.py` (+ sa ligne `RENDER_CRONS.md`), en gardant `app/scripts/create_admin.py` comme unique bootstrap.

---

## P-16 — Pages publiques à token : squelette et gestion d'erreur communs (P2)

**Le problème (vérifié)** : ~10 pages publiques à token (`bon`, `soumission`, `contrat-signature`, `sign-*`, `pay-invoice`, …) réimplémentent le même squelette copié-collé (fetch token → états loading/error/signé → SignaturePad → footer RBQ), avec `money`/`fmtDate` redéfinis à l'identique. La dérive est déjà visible : `soumission/[token]` a un `extractError()` qui remonte le vrai message FastAPI, mais `bon`/`contrat-signature`/`sign-devlog` avalent tout en « réessaie » générique (un refus légitime « déjà signé / expiré » pousse le client à re-soumettre en boucle).

**Bénéfice** : source unique → plus de dérive entre flux clients critiques + messages d'erreur utiles partout.
**Risque** : comportement visible sur des flux clients → test de non-régression avant.
**Effort** : moyen-élevé.
**Priorité** : **P2**.

**Plan d'exécution** :
1. Extraire `usePublicTokenResource` + `PublicPageShell` + `SignatureCard`, centraliser `money`/`fmtDate` et `extractError()`.
2. Migrer les ~10 pages en adaptateurs ; vérifier que chaque refus backend (409/422) affiche son détail.

---

## P-17 — Fichiers géants : découper les pages de 8082 / 6766 lignes (P1 pour le mort, P3 pour le reste)

**Le problème (vérifié)** : `dev-logiciel/projets/[id]/page.tsx` (8082 l.) contient **~4000 lignes de composants d'onglets jamais rendus** (vestige de la fusion construction→devlog : `PhotosTab`, `TasksTab`, `RecapTab`, `ChantierAgendaTab`, etc., 0 référence JSX, aucun export → archi-mort confirmé). Au-delà, plusieurs fichiers dépassent 4000-8000 lignes (voir baseline §3), illisibles et hotspots de merge permanents.

**Bénéfice** : ~8082 → ~4000 lignes immédiatement (suppression du mort, risque runtime nul) ; puis lisibilité et vélocité.
**Risque** : la **suppression du mort** est sûre mais mérite une PR dédiée + revue ; le **découpage** du reste est un refactor plus large à étaler.
**Effort** : moyen (suppression) puis continu (découpage).
**Priorité** : **P1** pour la suppression des ~4000 lignes mortes ; **P3** pour le découpage des fichiers vivants.

**Plan d'exécution** :
1. PR dédiée : supprimer les composants d'onglets non câblés + leurs types (grep JSX = 0 pour chacun ; `ProjectTeamSection` mort transitivement).
2. Ensuite, extraire les gros onglets vivants (`Summary`, `DevlogFinances`, …) en fichiers séparés, un par PR.

---

## P-18 — Helper `public_base()` unique (dédup de `_public_base_url` sur ~10 services d'envoi) (P3)

**Le problème (vérifié)** : la construction de l'URL publique de base (pour les liens dans les courriels) est recopiée à l'identique dans une dizaine de services d'envoi (`bail_sign`, `bon_send`, `devlog`, `devlog_invoice_send`, `devlog_soumission_send`, `facture_send`, `nda_send`, `offer_send`, `purchase_agreement_send`, `soumission_send`). Deux variantes `_public_base_url` divergent légèrement.

**Pourquoi NON fait cette nuit** : c'était sur ma liste « à corriger », mais la factorisation touche ~10 fichiers d'envoi (dont 3 déjà modifiés cette nuit pour les gardes d'état de facturation). Pour respecter la consigne « option la plus sûre et la plus réversible » et garder le diff de la nuit chirurgical, je l'ai **déféré** : un helper partagé bien fait mérite sa propre PR isolée plutôt que d'être noyé dans le lot de correctifs.

**Bénéfice** : source unique pour les liens publics (fin de la dérive entre courriels).
**Risque** : faible (copies strictement identiques) mais large surface → PR dédiée + vérif d'un courriel de chaque type.
**Effort** : faible-moyen. **Priorité** : P3.

**Plan** : créer `app/services/public_links.py::public_base()` ; importer dans les copies STRICTEMENT identiques ; laisser les 2 `_public_base_url` divergents pour une revue séparée (comprendre la divergence avant d'unifier).
