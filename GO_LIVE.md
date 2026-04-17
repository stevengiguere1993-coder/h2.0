# Go-Live Checklist — Horizon Services Immobiliers (h2.0)

Ce document rassemble tout ce qui doit être fait par Steven **après** le
merge de la branche `claude/setup-project-env-Q8Ro7` dans `main` pour
que le site soit pleinement opérationnel.

---

## 0. Merger le code

1. Ouvrir la PR `claude/setup-project-env-Q8Ro7 → main`
2. Revue rapide, puis **Squash and merge**
3. Render va **auto-déployer** le service `h2-0` (backend) — laisser passer le build (~3 min)
4. Vérifier `https://h2-0.onrender.com/health` → `{"status":"healthy"}`
5. Vérifier `https://h2-0.onrender.com/docs` — la liste des endpoints doit inclure `/blog`, `/contact`, `/soumissions`, `/webhooks/form`, etc.

---

## 1. Variables d'environnement — service `h2-0`

Render → `h2-0` → **Environment** → ajouter / vérifier :

- `FRONTEND_ORIGINS=https://immohorizon.com,https://www.immohorizon.com,https://immohorizon.ca,https://www.immohorizon.ca`
- `ANTHROPIC_API_KEY` — copier depuis `bridge-public`
- `CLAUDE_MODEL=claude-sonnet-4-5`
- `MONDAY_API_TOKEN` — clé actuelle (temporaire, pour migration)
- `QUICKBOOKS_CLIENT_ID`, `QUICKBOOKS_CLIENT_SECRET`, `QBO_REFRESH_TOKEN`, `QBO_REALM_ID` — copier depuis `bridge-public`
- `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` — copier depuis `bridge-public`
- `MAIL_FROM_EMAIL=info@immohorizon.com`
- `MAIL_FROM_NAME=Horizon Services Immobiliers`
- `FORM_WEBHOOK_SECRET` — générer une chaîne aléatoire (ex: `openssl rand -hex 32`)
- `QBO_WEBHOOK_VERIFIER_TOKEN` — récupérer dans Intuit Developer console

Redeploy après modifications.

---

## 2. Créer le premier admin

Render → `h2-0` → **Shell** :

```bash
ADMIN_EMAIL="stevengiguere1993@gmail.com" ADMIN_PASSWORD="ChoisirUnMotDePasseSolide123!" \
  python -m app.scripts.create_admin
```

Vous pourrez vous connecter avec ce compte sur `/connexion` une fois
le frontend déployé.

---

## 3. Créer le service frontend `h2-0-web`

Render → **New +** → **Web Service** → connecter le repo `h2.0` :

| Champ | Valeur |
|---|---|
| Name | `h2-0-web` |
| Region | Oregon |
| Branch | `main` |
| Root Directory | `frontend` |
| Runtime | Node |
| Build | `npm install && npm run build` |
| Start | `npm run start` |
| Plan | Free |

Variables :

- `NODE_VERSION=20`
- `NEXT_PUBLIC_SITE_URL=https://immohorizon.com`
- `NEXT_PUBLIC_API_BASE_URL=https://h2-0.onrender.com`
- `NEXT_PUBLIC_DEFAULT_LOCALE=fr`
- `NEXT_PUBLIC_SEARCH_CONSOLE_VERIFICATION=df-YUga-WwjKVQGNgHeqbykIibgxiav5Wq4WbetFrMc`

---

## 4. Créer le cron SEO `h2-0-seo-daily`

Render → **New +** → **Cron Job** :

| Champ | Valeur |
|---|---|
| Name | `h2-0-seo-daily` |
| Root Directory | `backend` |
| Runtime | Python |
| Build | `pip install -r requirements.txt` |
| Command | `python -m app.jobs.seo_daily` |
| Schedule | `0 11 * * *` |

Variables : `DATABASE_URL`, `ANTHROPIC_API_KEY`, `CLAUDE_MODEL=claude-sonnet-4-5`, `SITE_URL=https://immohorizon.com`.

Pour tester tout de suite : onglet du cron → **Trigger Run**.

---

## 5. Migration Monday → Postgres (one-shot)

Render → `h2-0` → **Shell** :

```bash
python -m app.scripts.monday_migrate
```

Cela importe clients, contacts, employés, sous-traitants, projets,
soumissions, bons de travail, factures et achats dans Postgres. Safe
à re-lancer : chaque importer détecte les doublons.

---

## 6. DNS Squarespace

Quand `h2-0-web` est créé :

1. Render → `h2-0-web` → **Custom Domains** → ajouter les 4 domaines
   (`immohorizon.com`, `www.immohorizon.com`, `immohorizon.ca`, `www.immohorizon.ca`)
2. Squarespace → **Domains → immohorizon.com → DNS Settings → Custom Records**
   Ajouter les enregistrements affichés par Render
3. Repeat pour `immohorizon.ca`
4. Sur Render, pour `immohorizon.ca` / `www.immohorizon.ca`, configurer
   **Redirect to** → `https://immohorizon.com`

Propagation : 10 min à 24 h.

---

## 7. Google Search Console

1. Search Console → propriété `immohorizon.com` → **Vérifier**
   (le TXT est déjà dans le DNS si ajouté précédemment)
2. Soumettre le sitemap : `https://immohorizon.com/sitemap.xml`
3. Ajouter une propriété pour `immohorizon.ca` (même démarche, TXT différent)

---

## 8. Tests de santé end-to-end

- [ ] `https://immohorizon.com/` charge la landing FR
- [ ] `https://immohorizon.com/en` charge la landing EN
- [ ] `https://immohorizon.com/services/salle-de-bain` charge
- [ ] `https://immohorizon.com/blog` charge (vide au début, se remplit chaque jour)
- [ ] Soumettre le formulaire contact → référence retournée
- [ ] `/app/crm` (après connexion) affiche la soumission
- [ ] `https://immohorizon.com/sitemap.xml` liste les pages
- [ ] `https://immohorizon.com/robots.txt` pointe vers le sitemap
- [ ] Lancement manuel du cron SEO → 1 article apparaît dans `/blog`

---

## 9. Après-vérification — sécurité

- [ ] **Révoquer** la clé Monday partagée et **régénérer** dans
      Monday → Admin → API. Mettre à jour `MONDAY_API_TOKEN` sur Render.
- [ ] Supprimer les anciens services (`bridge-public`, `mondayagent`)
      une fois la migration confirmée fonctionnelle.
- [ ] Activer le 2FA sur Render, GitHub, Google Workspace.
