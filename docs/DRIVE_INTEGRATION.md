# Intégration Google Drive — Kratos

> Objectif : permettre aux utilisateurs Kratos de gérer les fichiers de
> l'entreprise stockés sur Google Drive directement depuis les pages de
> l'application (deals, projets, clients, soumissions), sans avoir à
> ouvrir l'onglet Drive en parallèle.

## Vision d'ensemble

L'intégration repose sur trois briques :

1. **OAuth user-driven** — chaque utilisateur Kratos connecte SON compte
   Google. Les tokens (access + refresh) sont chiffrés en base avec
   Fernet et utilisés pour agir au nom de l'utilisateur sur son Drive.
2. **Drive Conventions** — règles configurables qui automatisent la
   création et le rattachement de dossiers Drive aux entités Kratos.
   Exemples : « tout nouveau deal Prospection crée un dossier
   `/Pipeline/<nom>` en clonant le template Analyse », « tout projet
   construction → dossier `/Projets/<numero> - <adresse>` avec
   sous-dossiers Plans/Photos/Factures ».
3. **Auto-upload des PDFs Kratos** — chaque document généré par Kratos
   (fiche analyse, NDA signé, soumission, offre PPTX, facture Dev
   logiciel) peut être déposé automatiquement dans le bon sous-dossier
   Drive selon des règles configurables.

L'utilisateur final voit un composant `<DriveFolderExplorer>` sur chaque
page entité, qui présente l'arborescence du dossier Drive lié avec des
actions inline (upload, renommer, déplacer, supprimer, prévisualiser,
partager).

## État des phases

| Phase | Périmètre                                                   | Statut |
| ----- | ----------------------------------------------------------- | ------ |
| **1** | Foundation OAuth + 5 tables + page Settings minimaliste     | livré (juin 2026) |
| **2** | Wrapper Drive API (list / upload / move / share / etc.)     | livré (juin 2026) |
| **3** | Composant `<DriveFolderExplorer>` réutilisable              | livré (juin 2026) |
| **4** | UI Conventions + moteur d'application manuelle              | livré (juin 2026) |
| 5     | Event listeners SQLAlchemy → exécution des Conventions      | à venir |
| 6     | Hooks d'auto-upload sur les services de génération PDF      | à venir |
| 7     | Intégration de `<DriveFolderExplorer>` sur les pages entité | à venir |

## Phase 1 — Ce qui est livré

- 5 tables : `drive_user_tokens`, `drive_conventions`,
  `drive_entity_links`, `drive_auto_uploads`, `drive_audit_logs`.
- Service `app.services.drive_oauth` (OAuth 2.0, chiffrement Fernet,
  refresh auto, révocation).
- 4 endpoints `/api/v1/drive/auth/*` :
  - `GET  /url` — URL Google de consentement (admin/owner only).
  - `GET  /callback` — endpoint public appelé par Google.
  - `GET  /status` — `{connected, google_email, expires_at}`.
  - `POST /disconnect` — révocation + suppression.
- Page `/app/parametres/drive` avec la section « Connexion Google Drive »
  active, et 4 sections roadmap grisées.

Phil peut connecter son compte Google et voir son email associé. C'est
tout pour la Phase 1 — aucune navigation Drive, aucune écriture de
fichiers.

## Procédure de configuration

### 1. Google Cloud Console — créer un projet OAuth

1. Aller sur [Google Cloud Console](https://console.cloud.google.com/).
2. Créer un nouveau projet (ou utiliser un projet existant) — ex.
   « Kratos Drive ».
3. Activer l'API Google Drive :
   `APIs & Services → Library → Google Drive API → Enable`.
4. Configurer le consent screen :
   `APIs & Services → OAuth consent screen`.
   - **User type** : External
   - **App name** : Kratos
   - **User support email** : `info@immohorizon.com`
   - **Developer contact** : `info@immohorizon.com`
   - **Authorized domains** : `immohorizon.com`, `onrender.com`
   - **Scopes** : ajouter
     - `https://www.googleapis.com/auth/drive.file`
     - `https://www.googleapis.com/auth/userinfo.email`
     - `openid`
   - **Test users** : ajouter les 3 partners Kratos :
     - `philippe.meuser@immohorizon.com`
     - `sgiguere@immohorizon.com`
     - `mvilliard@immohorizon.com`

   Comme les comptes sont Gmail perso avec adresse business (pas
   Workspace), on reste en mode « Testing » → pas besoin de Verification
   Google. La whitelist limite l'accès aux 3 emails ci-dessus.

5. Créer les credentials OAuth :
   `APIs & Services → Credentials → Create Credentials → OAuth client ID`.
   - **Application type** : Web application
   - **Name** : Kratos backend
   - **Authorized redirect URIs** :
     - `https://h2-0.onrender.com/api/v1/drive/auth/callback`
     - (optionnel local dev) `http://localhost:8000/api/v1/drive/auth/callback`

6. Noter le **Client ID** et le **Client Secret** affichés.

### 2. Générer la clé de chiffrement Fernet

Les tokens Drive sont chiffrés en base avec Fernet (AES-128-CBC + HMAC).
Générer une clé unique pour la prod :

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Garder précieusement la valeur retournée — si elle est perdue, tous les
tokens stockés deviennent illisibles et les utilisateurs devront se
reconnecter.

### 3. Configurer les variables d'environnement Render

Sur le service `h2-0` (backend Render), ajouter :

| Variable                       | Valeur                                                                 |
| ------------------------------ | ---------------------------------------------------------------------- |
| `GOOGLE_CLIENT_ID`             | Client ID de l'étape 1.5                                               |
| `GOOGLE_CLIENT_SECRET`         | Client Secret de l'étape 1.5                                           |
| `DRIVE_TOKEN_ENCRYPTION_KEY`   | Clé Fernet de l'étape 2                                                |
| `GOOGLE_REDIRECT_URI`          | (optionnel) override si Kratos change de domaine. Défaut : `https://h2-0.onrender.com/api/v1/drive/auth/callback` |

> **Important** : sans `DRIVE_TOKEN_ENCRYPTION_KEY`, le backend fonctionne
> mais log un WARNING et stocke les tokens en base64 NON CHIFFRÉ. C'est
> acceptable en dev, jamais en prod.

### 4. Premier connect

1. Redéployer le backend après ajout des env vars.
2. Aller sur `https://kratos.immohorizon.com/fr/app/parametres/drive`.
3. Cliquer sur « Connecter mon compte Google ».
4. Choisir le compte Google sur l'écran de consentement.
5. Accepter les permissions (lecture/écriture des fichiers créés ou
   ouverts par Kratos).
6. Retour automatique sur la page Drive avec le badge vert
   « Connecté en tant que `<email>` ».

## Architecture des données

### `drive_user_tokens`

Un seul token actif par utilisateur (unique sur `user_id`). Stocke
access + refresh chiffrés. Renouvelé automatiquement à T-60s de
l'expiration.

### `drive_conventions`

Règles « entité Kratos → dossier Drive ». Configurées Phase 4, exécutées
Phase 5 par des event listeners SQLAlchemy. Champs principaux :

- `entity_type` : `prospection_deal`, `project`, `devlog_project`,
  `client`, `soumission`, etc.
- `trigger_event` : `created` ou `status_changed`.
- `parent_folder_drive_id` + `folder_name_template` : où et comment
  nommer le nouveau dossier (placeholders `{nom}`, `{numero}`, etc.).
- `template_folder_to_copy_drive_id` : id d'un dossier modèle à cloner.
- `subfolders_to_create` (JSON) : sous-dossiers à créer dedans.
- `status_to_parent_map` (JSON) : pour les conventions
  `status_changed`, mapping `{statut: drive_parent_id}` qui déplace le
  dossier selon le nouveau statut.

### `drive_entity_links`

La table consultée à chaque rendu de page entité. Une ligne par couple
`(entity_type, entity_id)`. Caches `drive_folder_name` /
`drive_folder_path` rafraîchis à chaque navigation pour des breadcrumbs
corrects sans appel API.

### `drive_auto_uploads`

Règles de dépôt automatique des PDFs générés par Kratos. Champs
principaux :

- `document_type` : `fiche_analyse`, `nda_signed`, `soumission_pdf`,
  `offre_pptx`, `facture_pdf`.
- `subfolder_path_template` + `file_name_template` : chemin et nom du
  fichier (placeholders supportés).
- `overwrite_strategy` : `overwrite`, `version`, `keep_both`.

### `drive_audit_logs`

Journal dédié des actions Drive. Séparé du `audit_logs` général pour ne
pas polluer le volume (navigation peut générer beaucoup d'événements).
Toute mutation Drive depuis Kratos doit y poser une ligne avec
`success=True/False` et `error_message` en cas d'échec.

## Sécurité

- **Whitelist Google** : seuls les 3 emails partners peuvent passer
  l'écran de consentement OAuth tant qu'on reste en mode Testing.
- **State HMAC** : le `state` du flow OAuth est signé avec `jwt_secret`
  et porte le `user_id` + un nonce + un TTL de 10 min. Empêche les
  attaques CSRF et le replay.
- **Tokens chiffrés** : access + refresh stockés en Fernet (clé à 32
  bytes). Aucun token n'apparaît en clair dans les logs SQL.
- **Scope minimal** : `drive.file` ne donne accès qu'aux fichiers créés
  ou ouverts via Kratos — pas à l'intégralité du Drive de
  l'utilisateur.
- **Permission Kratos** : tous les endpoints `/drive/auth/*` (sauf
  `/callback`) sont protégés par `RequireAdminOrOwner`.

## Limites Phase 1

La Phase 1 livre la fondation seulement. Sont explicitement HORS scope
et reportés aux Phases suivantes :

- Aucune UI pour gérer les Conventions, Auto-uploads, Mappings, Audit
  log (Phase 4).
- Aucun composant `<DriveFolderExplorer>` (Phase 3).
- Aucun wrapper Drive API (`list_folder`, `upload`, etc. — Phase 2).
- Aucune intégration sur les pages entités (deals, projets, etc. —
  Phase 7).

Phil peut connecter son compte Google et voir son email associé. C'est
exactement le périmètre Phase 1.

## Phase 2 — Wrapper Drive API

La Phase 2 ajoute un wrapper complet de l'API Google Drive v3 sous
forme de service Python (`app.services.drive_api`) plus un router
REST (`/api/v1/drive/...`). Tous les endpoints sont protégés
`RequireAdminOrOwner` ; le `user_id` Kratos extrait du JWT est utilisé
pour récupérer le bon refresh_token et agir au nom de l'utilisateur.

### Endpoints

**Listing & métadonnées**

- `GET  /api/v1/drive/folders/{folder_id}/files` — liste paginée
  (`page_size`, `page_token`, `order_by`).
- `GET  /api/v1/drive/files/{file_id}/metadata` — métadonnées
  complètes.
- `GET  /api/v1/drive/folders/{folder_id}/path` — breadcrumbs
  racine → dossier courant.

**Upload**

- `POST /api/v1/drive/folders/{folder_id}/upload` — multipart/form-data,
  champ `file`. Retourne `DriveFile`.

**Download / Export / Preview**

- `GET  /api/v1/drive/files/{file_id}/download` — stream binaire.
  Header `Content-Disposition` RFC 5987 (accents OK).
- `GET  /api/v1/drive/files/{file_id}/export?format=pdf` — pour
  Google Docs / Sheets / Slides. Formats : `pdf`, `docx`, `xlsx`,
  `pptx`, `odt`, `csv`, `html`.
- `GET  /api/v1/drive/files/{file_id}/preview-url` — retourne
  `{preview_url: "https://drive.google.com/file/d/{id}/preview"}`
  prêt à embed en iframe.

**Mutations**

- `PATCH  /api/v1/drive/files/{file_id}` — body
  `{name?, parent_folder_id?, old_parent_folder_id?}`. Renomme et/ou
  déplace selon les champs présents.
- `DELETE /api/v1/drive/files/{file_id}` — trash par défaut.
  `?permanent=true` pour suppression définitive.
- `POST   /api/v1/drive/files/{file_id}/restore` — restaure depuis la
  corbeille.

**Dossiers**

- `POST /api/v1/drive/folders/{folder_id}/subfolders` — body
  `{name}`. Crée un sous-dossier.
- `POST /api/v1/drive/folders/{source_folder_id}/copy` — body
  `{parent_folder_id, new_name?}`. Copie récursive (profondeur max 5).

**Recherche**

- `GET /api/v1/drive/search?q={query}&parent_folder_id={id}` —
  cherche par nom OU contenu (Drive `fullText`).

**Partage**

- `GET    /api/v1/drive/files/{file_id}/permissions` — liste.
- `POST   /api/v1/drive/files/{file_id}/share` — body
  `{email, role, send_notification, message}`. Rôles : `reader`,
  `commenter`, `writer`.
- `DELETE /api/v1/drive/files/{file_id}/permissions/{permission_id}` —
  révoque.

### Exceptions custom

Définies dans `app.services.drive_exceptions` :

| Exception                | HTTP | Sémantique                                                |
| ------------------------ | ---- | --------------------------------------------------------- |
| `DriveAuthError`         | 401  | User non connecté ou token invalide / expiré              |
| `DriveNotFoundError`     | 404  | Fichier ou dossier introuvable (ou hors scope `drive.file`) |
| `DrivePermissionError`   | 403  | Google a refusé (permissions insuffisantes)               |
| `DriveExportRequired`    | 409  | Fichier Google natif — passer par `/export`               |
| `DriveQuotaExceeded`     | 429  | Quota ou rate limit dépassé                               |
| `DriveAPIError`          | 502  | Autre erreur Drive non catégorisée                        |

Toutes wrappent l'exception Google originale sur `.original` et
exposent un message lisible en français côté `.message`.

### Audit log

Toutes les opérations posent une ligne dans `drive_audit_logs` :
`action` (verbe précis : `list_folder`, `get_metadata`, `upload`,
`download`, `export`, `rename`, `move`, `trash`, `delete_permanent`,
`restore`, `create_folder`, `copy_folder_recursive`, `search`,
`share`, `list_permissions`, `revoke_permission`, `get_folder_path`),
`drive_file_id`, `drive_file_name`, `details` (JSON), `success`,
`error_message`.

### Copie récursive

Drive API v3 ne supporte PAS la copie de dossier nativement. Le
wrapper `copy_folder_recursive` :

1. Crée un dossier vide dans le parent cible ;
2. Liste les enfants directs du dossier source ;
3. Pour chaque enfant : si dossier → récursion (profondeur + 1) ;
   sinon → `files.copy()` avec le nouveau parent.

Garde-fou : profondeur max **5** niveaux pour éviter une boucle
infinie sur un cycle pathologique. Cette fonction est utilisée
Phase 4 par le mécanisme « copier le template » des Drive Conventions.

### Limites Drive API à connaître

- **Scope `drive.file`** : on ne voit que les fichiers créés ou ouverts
  via Kratos. Un fichier déposé manuellement sur le Drive sera invisible
  tant que l'utilisateur ne l'a pas explicitement ouvert via Kratos
  (Drive Picker — Phase 3 ou 4).
- **Recherche non récursive** : Google ne permet pas de chercher dans
  les descendants d'un dossier en un seul appel ; `?parent_folder_id`
  filtre uniquement les ENFANTS DIRECTS.
- **Quota** : 1 000 requêtes / 100 secondes / user (par défaut). Au-delà,
  on retourne `DriveQuotaExceeded` (HTTP 429).

### Tests curl

Préparer un token Kratos admin/owner connecté à Drive, et l'ID d'un
dossier de test sur ton Drive. Variables :

```bash
TOKEN="<JWT_KRATOS>"
BASE="https://h2-0.onrender.com/api/v1/drive"
FOLDER="<DRIVE_FOLDER_ID>"
```

**Lister le contenu d'un dossier**

```bash
curl -s "$BASE/folders/$FOLDER/files" \
  -H "Authorization: Bearer $TOKEN" | jq
```

**Créer un sous-dossier**

```bash
curl -s -X POST "$BASE/folders/$FOLDER/subfolders" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Phase 2"}' | jq
```

**Upload un petit fichier**

```bash
echo "hello kratos" > /tmp/hello.txt
curl -s -X POST "$BASE/folders/$FOLDER/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/hello.txt" | jq
# → noter l'id retourné, ex. FILE_ID=...
FILE_ID="<ID_RETOURNÉ>"
```

**Renommer**

```bash
curl -s -X PATCH "$BASE/files/$FILE_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"hello-renamed.txt"}' | jq
```

**Déplacer**

```bash
NEW_PARENT="<AUTRE_FOLDER_ID>"
curl -s -X PATCH "$BASE/files/$FILE_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"parent_folder_id\":\"$NEW_PARENT\"}" | jq
```

**Download**

```bash
curl -s -L "$BASE/files/$FILE_ID/download" \
  -H "Authorization: Bearer $TOKEN" -o /tmp/dl.txt
cat /tmp/dl.txt  # → hello kratos
```

**URL de preview (iframe)**

```bash
curl -s "$BASE/files/$FILE_ID/preview-url" \
  -H "Authorization: Bearer $TOKEN" | jq
```

**Recherche**

```bash
curl -s "$BASE/search?q=hello" \
  -H "Authorization: Bearer $TOKEN" | jq
```

**Partage**

```bash
curl -s -X POST "$BASE/files/$FILE_ID/share" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email":"sgiguere@immohorizon.com","role":"reader","send_notification":false}' | jq
curl -s "$BASE/files/$FILE_ID/permissions" \
  -H "Authorization: Bearer $TOKEN" | jq
```

**Trash + Restore**

```bash
curl -s -X DELETE "$BASE/files/$FILE_ID" \
  -H "Authorization: Bearer $TOKEN" -w "%{http_code}\n"
curl -s -X POST "$BASE/files/$FILE_ID/restore" \
  -H "Authorization: Bearer $TOKEN" | jq
```

**Delete permanent (à n'utiliser qu'en test)**

```bash
curl -s -X DELETE "$BASE/files/$FILE_ID?permanent=true" \
  -H "Authorization: Bearer $TOKEN" -w "%{http_code}\n"
```

## Limites Phase 2

- Aucune UI frontend (Phase 3 — composant `<DriveFolderExplorer>`).
- Aucune Drive Convention exécutée automatiquement (Phase 4-5).
- Aucun auto-upload de PDF Kratos (Phase 6).
- Aucune intégration sur les pages entités, deals ou projets (Phase 7).

Phase 2 = backend wrapper + endpoints REST. Phil valide via curl
ci-dessus, et la Phase 3 brancherait l'UI dessus.

## Phase 4 — UI Conventions + Moteur d'application manuelle

La Phase 4 livre :

- Un **moteur d'exécution** côté backend
  (`app.services.drive_conventions_engine`) capable d'appliquer une
  convention à une entité existante (création de dossier Drive,
  copie d'un template, création des sous-dossiers, persistance d'un
  `DriveEntityLink`).
- 8 endpoints REST (`/api/v1/drive/conventions/*` et
  `/api/v1/drive/entity-links/*`) — admin/owner only.
- Une **UI complète** sur `/parametres/drive` qui transforme les
  sections "Conventions" et "Liens existants" en sections actives
  (tableau, modale CRUD avec aperçu, modale "Tester").
- Un **seeder idempotent** au boot qui ajoute 4 conventions par
  défaut inactives, que Phil active une à une après avoir configuré
  le `parent_folder_drive_id` correspondant.

> Phase 4 ≠ Phase 5. Les **hooks automatiques** ("à la création d'un
> deal, applique la convention X") sont volontairement reportés à
> la Phase 5. Pour l'instant, l'application se fait **uniquement via
> le bouton "Tester"** sur la page Conventions, qui appelle
> `POST /api/v1/drive/conventions/{id}/apply`.

### Service moteur — surface

```python
from app.services import drive_conventions_engine as engine

# 1. Lister les types d'entités supportées (alimente le wizard UI).
types = await engine.get_supported_entity_types()
# → [{"key": "ProspectionDeal", "label": "Deal Pipeline (Prospection)",
#     "variables": [{"key": "address", "label": "Adresse", ...}]}, ...]

# 2. Résoudre un template (sans créer de dossier — utile pour preview).
name = await engine.resolve_folder_name(
    "{address}, {city}", "ProspectionDeal", 42, db
)
# → "1660 Saint-Clément, Montréal"

# 3. Appliquer une convention à une entité existante.
link = await engine.apply_convention_to_entity(
    convention_id=3,
    entity_type="ProspectionDeal",
    entity_id=42,
    user_id=current_user.id,
    db=db,
)
# Crée le dossier Drive (+ template copié si défini + sous-dossiers)
# et persiste un DriveEntityLink dans la table drive_entity_links.
```

Le moteur lève des exceptions custom (`ConventionNotFound`,
`EntityAlreadyLinked`, `UnsupportedEntityType`,
`ConventionMisconfigured`, ...) que l'endpoint REST mappe vers les
codes HTTP appropriés (404, 409, 400, ...).

### Endpoints REST

**Conventions CRUD** (admin/owner only)

- `GET    /api/v1/drive/conventions` — filtres `entity_type`, `active`.
- `GET    /api/v1/drive/conventions/{id}`
- `POST   /api/v1/drive/conventions` — création (toujours inactive
  par défaut via `active=False` côté schéma).
- `PATCH  /api/v1/drive/conventions/{id}` — modifie les champs
  fournis.
- `DELETE /api/v1/drive/conventions/{id}` — **soft delete** :
  positionne `active=False` pour préserver les `DriveEntityLink` qui
  référencent cette convention.

**Action d'application**

- `POST /api/v1/drive/conventions/{id}/apply` — body
  `{entity_type, entity_id}`. Crée le dossier Drive + sous-dossiers
  et retourne le `DriveEntityLink` créé + l'URL Drive prête à ouvrir.

**Métadonnées**

- `GET /api/v1/drive/conventions/supported-entity-types` — liste des
  types d'entités supportées avec leurs variables disponibles.

**Entity links** (admin/owner only)

- `GET    /api/v1/drive/entity-links` — filtres `entity_type`,
  `entity_id`.
- `POST   /api/v1/drive/entity-links` — lien manuel sans convention
  (rattache un dossier Drive existant à une entité Kratos).
- `DELETE /api/v1/drive/entity-links/{id}` — supprime le lien Kratos.
  Le dossier Drive reste intact côté Google.

Toutes les mutations posent un audit log dans la table générique
`audit_logs` (action `drive_convention.create`, `.update`,
`.soft_delete`, `.apply`, `drive_entity_link.create`, `.delete`).

### Conventions seedées par défaut

Au boot, 4 conventions sont créées (idempotent — vérifie l'existence
par `(name, entity_type)` avant insert) :

1. **Deal Pipeline → 0 - En cours** (`ProspectionDeal`)
2. **Nouveau client Dev Log → Clients Dev** (`DevlogClient`)
3. **Nouveau projet Dev Log** (`DevlogProject`)
4. **Nouveau projet Construction** (`ConstructionProject`)

Toutes ont `active=False` et `parent_folder_drive_id=None` — Phil les
configure une à une dans l'UI avant de les activer.

### Comment Phil teste

1. Sur `/parametres/drive`, scroller jusqu'à **"Conventions de dossiers"**.
2. Cliquer sur le crayon d'une convention seedée (ex. *Deal Pipeline*).
3. Remplir le **dossier parent Drive (ID)** — copié depuis l'URL
   Drive — puis cocher *Active* et enregistrer.
4. Cliquer sur l'icône *Play* (▶) de la convention dans le tableau.
5. Saisir l'ID d'un `ProspectionDeal` existant (ex. 42).
6. **Appliquer** — un dossier `{address}, {city}` est créé dans le
   parent, avec les sous-dossiers `Photos / Soumissions / ...`.
7. Vérifier dans la section **"Liens existants"** que la ligne
   apparaît, puis cliquer sur le lien externe pour ouvrir le dossier
   directement dans Drive.

### Variables supportées par type d'entité

| Type d'entité          | Variables                                                       |
| ---------------------- | --------------------------------------------------------------- |
| `ProspectionDeal`      | `{address}`, `{city}`, `{postal_code}`, `{date_creation}`       |
| `DevlogProject`        | `{nom_projet}`, `{nom_client}`, `{date_creation}`               |
| `DevlogClient`         | `{nom_client}`, `{date_creation}`                               |
| `ProspectionLead`      | `{address}`, `{city}`, `{date_creation}`                        |
| `ConstructionProject`  | `{address}`, `{nom_projet}`, `{date_creation}`                  |

Les placeholders non résolus (variable absente OU valeur vide) sont
**laissés tels quels** dans le nom final avec un warning loggé. Pas
de crash — Phil peut corriger le template a posteriori.

## Limites Phase 4

- Aucun hook automatique sur création/changement de statut d'entité
  (Phase 5 — event listeners SQLAlchemy).
- Aucun mapping `status → folder_parent` exécuté (champ
  `status_to_parent_map` exposé en lecture/écriture API mais ignoré
  par le moteur Phase 4).
- Aucun auto-upload de PDF Kratos (Phase 6).
- Aucune intégration `<DriveFolderExplorer>` sur les pages entité
  (Phase 7).

Phase 4 = UI Conventions + moteur d'application manuelle. Phil
configure ses règles, les teste sur des entités existantes, et voit
les liens persistés s'accumuler dans la section "Liens existants".

## Phase 5 — Hooks automatiques (`created` + `status_changed`)

La Phase 5 branche les conventions Phase 4 sur les événements métier
de Kratos. Aucun event listener SQLAlchemy magique : on appelle
explicitement le hook depuis chaque endpoint qui crée une entité
supportée, juste après le `db.flush()` / `db.commit()`. Ce design
garde la chaîne de causalité lisible (un coup d'œil au endpoint
suffit pour savoir si l'auto-création Drive est en place) et permet
le pattern « best-effort » sans surprise.

### Service `drive_conventions_hooks`

Nouveau module : `backend/app/services/drive_conventions_hooks.py`
exposant deux fonctions async :

- `on_entity_created(entity_type, entity_id, user_id, db)` —
  cherche la convention active `trigger_event='created'` de plus
  haute priorité pour `entity_type`, et délègue à
  `drive_conventions_engine.apply_convention_to_entity`. Retourne
  le `DriveEntityLink` créé ou `None`. JAMAIS d'exception.

- `on_entity_status_changed(entity_type, entity_id, old_status,
  new_status, user_id, db)` — cherche la convention active
  `trigger_event='status_changed'`, lit
  `status_to_parent_map[new_status]`, et déplace le dossier lié
  via `drive_api.move_file`. Retourne `True/False`. JAMAIS
  d'exception.

### Contrat best-effort

Aucune erreur Drive (réseau, quota, auth, convention mal
configurée) ne doit jamais bloquer la création d'une entité
Kratos. Le hook :

1. Capture toute exception via un `try/except` global ;
2. Logge un warning (`log.exception`) ;
3. Pose un audit log :
   - `drive_convention.auto_applied` — succès
   - `drive_convention.auto_skipped` — pré-conditions manquantes
     (pas de connexion Drive, parent_folder_drive_id vide, etc.)
   - `drive_convention.auto_failed` — exception au moment de
     l'appel API Drive
   - `drive_convention.auto_moved` / `.auto_move_skipped` /
     `.auto_move_failed` pour le hook `status_changed`
4. Retourne `None` / `False`.

Le pattern d'intégration côté endpoint est uniforme :

```python
db.add(deal)
await db.flush()
await db.refresh(deal)

try:
    from app.services.drive_conventions_hooks import on_entity_created
    await on_entity_created(
        entity_type="ProspectionDeal",
        entity_id=deal.id,
        user_id=user.id,
        db=db,
    )
except Exception:
    log.exception("drive hook 'created' a echoue (non bloquant)")

return deal
```

### Endpoints instrumentés

| Entité Kratos        | Endpoint                                       |
| -------------------- | ---------------------------------------------- |
| `ProspectionDeal`    | `POST /api/v1/prospection/deals`               |
| `ProspectionDeal`    | `POST /api/v1/lead-analyses/{id}/convert-to-deal` |
| `DevlogProject`      | `POST /api/v1/devlog/projects`                 |
| `DevlogProject`      | Provisionning auto sur soumission acceptée (`_provision_project_for_soumission`) |
| `DevlogClient`       | `POST /api/v1/devlog/clients`                  |
| `ConstructionProject`| `POST /api/v1/projects`                        |
| `ProspectionLead`    | `POST /api/v1/prospection/leads`               |

### Idempotence

Le hook `on_entity_created` vérifie d'abord qu'aucun
`DriveEntityLink` n'existe pour `(entity_type, entity_id)`. Si un
lien existe (par exemple parce que Phil a déjà appliqué une
convention manuellement, ou parce que le frontend a fait un double
POST), le hook return `None` silencieusement — pas de dossier
dupliqué.

Le hook `on_entity_status_changed` ne crée jamais de dossier
rétroactivement : si l'entité n'a pas encore de lien Drive, le
hook return `False` immédiatement.

### Comment Phil active l'auto

Sur `/parametres/drive` → section Conventions :

1. Éditer la convention (par exemple « Deal Pipeline → 0 - En
   cours »).
2. Changer le champ « Événement déclencheur » de **Manuel** à
   **À la création**.
3. Vérifier que `parent_folder_drive_id` et `folder_name_template`
   sont remplis.
4. Cocher **Active**, sauvegarder.
5. Au prochain deal créé, Kratos crée le dossier Drive
   automatiquement (3-8 secondes de latence côté requête à cause
   de l'appel Drive API).

L'auto reste désactivable à tout moment via le toggle « Actif »
dans le tableau de la page Conventions.

### Performance

L'appel Drive API bloque la requête HTTP de création d'entité
(latence Drive + nombre de sous-dossiers à créer). Mesure observée
en Phase 4 : ~2-3 secondes pour un dossier vide, ~5-8 secondes
pour un dossier avec 5 sous-dossiers (chaque sous-dossier =
1 round-trip Drive). Pas optimisé Phase 5 — un déport vers une
task queue est laissé pour une phase ultérieure si la latence
devient bloquante.

### Limites Phase 5

- Pas d'auto-upload des PDFs Kratos vers le dossier créé (Phase 6).
- Pas d'intégration `<DriveFolderExplorer>` directement sur les
  fiches deal/projet (Phase 7).
- Pas de hook sur la suppression / archive d'entités.
- Pas d'UI dédiée pour éditer le mapping `status_to_parent_map`
  d'une convention `status_changed` (l'édition passe par
  `PATCH /api/v1/drive/conventions/{id}` direct via curl ou
  Postman pour l'instant).
- Pas de retry en cas d'échec réseau ponctuel (Phil peut relancer
  manuellement via le bouton « Tester » Phase 4).

Phase 5 = hooks `created` + `status_changed` branchés sur les
endpoints principaux, best-effort, audit log complet.

---

## Phase 7 — Sections Drive sur les pages d'entités

Objectif : afficher le dossier Drive d'une entité **directement sur sa
fiche** (page deal, client, projet, soumission, contrat, etc.) au lieu
de devoir passer par `/parametres/drive`. Phil active chaque type de
page via un toggle dans les paramètres ; tant qu'un type n'est pas
activé, sa section reste totalement invisible.

### Architecture

**Composant générique `<EntityDriveSection>`**
(`frontend/src/components/drive/EntityDriveSection.tsx`)

Props : `{ entityType: string; entityId: number; title?: string;
className?: string }`. Déposé en bas de chaque page d'entité. 100 %
autonome et défensif — ne crash jamais la page hôte.

Flux :

1. `GET /api/v1/drive/page-modules/{entityType}/status`
   → `{active, display_title, has_convention}`.
2. Si `active === false` → le composant **ne rend rien** (même pas un
   titre). Le pré-câblage est donc invisible tant que Phil n'a pas
   activé le type.
3. Si actif → `GET /api/v1/drive/entity-links?entity_type=X&entity_id=Y`.
   - Lien existant → titre + `<DriveFolderExplorer folderId=...>`
     (réutilise le composant Phase 3).
   - Aucun lien → encart "Cette entité n'a pas encore de dossier Drive
     lié" + 2 boutons :
     - **Lier un dossier existant** → modale (saisie de l'ID Drive) →
       `POST /api/v1/drive/entity-links`.
     - **Créer auto via convention** → visible seulement si une
       convention active existe pour le type → `POST
       /api/v1/drive/conventions/{id}/apply`.

États gérés : loading (skeleton), 401 (encart "Drive non connecté" +
lien vers Paramètres), erreur réseau (bouton Réessayer).

**Table `drive_page_modules`**
(`backend/app/models/drive_page_module.py`)

Une ligne par `entity_type` : `active` (défaut False), `display_title`
(nullable → "Documents Drive" par défaut), `display_order`,
`created_at`, `updated_at`, `created_by_user_id`. Créée au boot via
`Base.metadata.create_all` (import dans `models/__init__.py`).

**Endpoints**
(`backend/app/api/v1/endpoints/drive_page_modules.py`, admin/owner)

- `GET   /api/v1/drive/page-modules` — liste + stat `linked_count`
  (nb `DriveEntityLink` par type).
- `GET   /api/v1/drive/page-modules/{entity_type}/status` — statut
  minimal consommé par le composant. Si la ligne n'existe pas →
  `{active: false}` (jamais un 404).
- `PATCH /api/v1/drive/page-modules/{entity_type}` — upsert du toggle
  et/ou du titre (auto-crée la ligne si absente). Audit log.
- `POST  /api/v1/drive/page-modules` — création explicite. Audit log.

**Seed au boot** (`backend/app/services/drive_page_modules_seed.py`,
idempotent) : 1 ligne `active=False` par type :
`ProspectionDeal`, `DevlogClient`, `DevlogProject`, `DevlogSoumission`,
`DevlogContract`, `ConstructionProject`, `ProspectionLead`,
`Entreprise`.

### UI Settings

Sur `/parametres/drive`, deux sections distinctes :

1. **Sections Drive par page** (Phase 7) : tableau
   (Type entité | Titre affiché | Dossiers liés | Statut + Actions)
   avec un toggle Activer/Désactiver par ligne (PATCH) et un bouton
   crayon pour éditer le titre affiché. Bouton refresh pour
   recharger les stats.
2. **Liens enregistrés** (ex « Liens existants » Phase 4) : la liste
   brute des `DriveEntityLink`, juste re-titrée.

### Pages câblées

| Page | entity_type |
|---|---|
| `prospection/pipeline/[id]/page.tsx` | `ProspectionDeal` |
| `dev-logiciel/clients/[id]/page.tsx` | `DevlogClient` |
| `dev-logiciel/projets/[id]/page.tsx` | `DevlogProject` |
| `dev-logiciel/soumissions/[id]/page.tsx` | `DevlogSoumission` |
| `dev-logiciel/contrats/[id]/page.tsx` | `DevlogContract` |
| `app/projets/[id]/page.tsx` (Construction) | `ConstructionProject` |
| `prospection/[id]/page.tsx` (lead drive-by) | `ProspectionLead` |
| `entreprises/[id]/page.tsx` | `Entreprise` |

> Note : `DevlogSoumission`, `DevlogContract` et `Entreprise` n'ont pas
> (encore) de convention dans le registry du moteur Phase 4 — sur ces
> pages, seul le bouton « Lier un dossier existant » s'affiche tant
> qu'aucune convention n'est créée pour ces types.

### Câbler une nouvelle page (procédure, 5-10 min)

1. **Backend** : ajouter l'`entity_type` à la liste `_DEFAULT_MODULES`
   dans `backend/app/services/drive_page_modules_seed.py` (le seed le
   créera inactif au prochain boot). Optionnel : ajouter un libellé FR
   dans `PAGE_MODULE_LABELS` (page Settings) pour un tableau lisible.
2. **Frontend** : sur la page cible, importer le composant
   (`import { EntityDriveSection } from
   "@/components/drive/EntityDriveSection";`) et déposer
   `<EntityDriveSection entityType="MonType" entityId={obj.id} />`
   vers la fin du contenu (avant les modales/footer), gardé par
   l'objet chargé (`{obj ? <EntityDriveSection .../> : null}`).
3. **Activer** : aller dans `/parametres/drive` > « Sections Drive par
   page » > toggle « Activer » sur la ligne du type.

Aucune migration ni redéploiement spécial : le composant reste
invisible tant que le toggle n'est pas activé, donc le pré-câblage est
sans risque.

### Limites Phase 7

- Une seule section Drive par page (pas de multi-dossiers).
- Pas de personnalisation au-delà du titre affiché.
- Pas d'auto-upload des PDFs Kratos (Phase 6).
