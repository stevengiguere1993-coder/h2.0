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
| 2     | Wrapper Drive API (list / upload / move / share / etc.)     | à venir |
| 3     | Composant `<DriveFolderExplorer>` réutilisable              | à venir |
| 4     | UI Conventions + Auto-upload + Mappings + Audit log         | à venir |
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
