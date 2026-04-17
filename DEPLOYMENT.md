# Déploiement — h2.0 sur Render + DNS Squarespace

Ce guide couvre les 3 services Render (backend, frontend, cron) et la
bascule du domaine `immohorizon.com` depuis Squarespace vers Render.

---

## 1. Backend `h2-0` (déjà déployé)

Le service existe et est live à `https://h2-0.onrender.com`.

**À ajouter / vérifier** dans Render → Service `h2-0` → Environment :

| Variable | Source |
|---|---|
| `FRONTEND_ORIGINS` | `https://immohorizon.com,https://www.immohorizon.com,https://immohorizon.ca,https://www.immohorizon.ca` |
| `ANTHROPIC_API_KEY` | copier depuis `bridge-public` |
| `MONDAY_API_TOKEN` | clé Monday (temporaire, pour migration) |
| `QUICKBOOKS_CLIENT_ID` | copier depuis `bridge-public` |
| `QUICKBOOKS_CLIENT_SECRET` | copier depuis `bridge-public` |
| `QBO_REFRESH_TOKEN` | copier depuis `bridge-public` |
| `QBO_REALM_ID` | copier depuis `bridge-public` |
| `AZURE_TENANT_ID` | copier depuis `bridge-public` |
| `AZURE_CLIENT_ID` | copier depuis `bridge-public` |
| `AZURE_CLIENT_SECRET` | copier depuis `bridge-public` |
| `MAIL_FROM_EMAIL` | `info@immohorizon.com` |
| `MAIL_FROM_NAME` | `Horizon Services Immobiliers` |

À la fin de la migration Monday, supprimer `MONDAY_API_TOKEN` et
**révoquer la clé** dans Monday → Admin → API.

---

## 2. Frontend `h2-0-web` (à créer)

Dans Render → **New +** → **Web Service** → connecter le repo `h2.0`.

| Champ | Valeur |
|---|---|
| Name | `h2-0-web` |
| Region | Oregon |
| Branch | `main` (on merge quand prêt) |
| Root Directory | `frontend` |
| Runtime | Node |
| Build Command | `npm install && npm run build` |
| Start Command | `npm run start` |
| Plan | Free |

**Environment variables** :

| Variable | Valeur |
|---|---|
| `NODE_VERSION` | `20` |
| `NEXT_PUBLIC_SITE_URL` | `https://immohorizon.com` |
| `NEXT_PUBLIC_API_BASE_URL` | `https://h2-0.onrender.com` |
| `NEXT_PUBLIC_DEFAULT_LOCALE` | `fr` |
| `NEXT_PUBLIC_SEARCH_CONSOLE_VERIFICATION` | `df-YUga-WwjKVQGNgHeqbykIibgxiav5Wq4WbetFrMc` |

---

## 3. Cron SEO quotidien `h2-0-seo-daily` (à créer)

Dans Render → **New +** → **Cron Job** :

| Champ | Valeur |
|---|---|
| Name | `h2-0-seo-daily` |
| Region | Oregon |
| Branch | `main` |
| Root Directory | `backend` |
| Runtime | Python |
| Build | `pip install -r requirements.txt` |
| Command | `python -m app.jobs.seo_daily` |
| Schedule | `0 11 * * *` (07 h Montréal) |

Variables : `DATABASE_URL`, `ANTHROPIC_API_KEY`, `CLAUDE_MODEL=claude-sonnet-4-5`, `SITE_URL=https://immohorizon.com`.

---

## 4. DNS Squarespace → Render

Une fois `h2-0-web` créé :

1. Render → `h2-0-web` → **Custom Domains** → ajouter :
   - `immohorizon.com`
   - `www.immohorizon.com`
   - `immohorizon.ca`
   - `www.immohorizon.ca`

2. Render affiche les enregistrements DNS cibles.

3. Dans Squarespace → **Domains** → chaque domaine → **DNS Settings**
   → **Custom Records**, ajouter les enregistrements fournis par
   Render (généralement un `A` sur l'apex vers les IP Render, et un
   `CNAME www` vers `<service>.onrender.com`).

4. Propagation : 10 min à 24 h. Vérifier dans Render que chaque
   domaine passe au statut **Verified**.

5. **Redirection .ca → .com** : dans Render, configurer `immohorizon.ca`
   avec « Redirect to » vers `https://immohorizon.com`. Alternative :
   gérer la redirection côté Next.js via `next.config.ts`.

---

## 5. Vérification Google Search Console

Le site insère déjà la balise meta `google-site-verification` dans le
`<head>`. Après déploiement :

1. Search Console → propriété `immohorizon.com` → **Vérifier**.
2. Soumettre le sitemap : `https://immohorizon.com/sitemap.xml`.

---

## 6. Checklist post-déploiement

- [ ] `https://h2-0.onrender.com/health` → 200 OK
- [ ] `https://immohorizon.com/` charge la landing FR
- [ ] `https://immohorizon.com/en` charge la landing EN
- [ ] Soumission du formulaire contact crée une ligne dans `contact_requests`
- [ ] `https://immohorizon.com/sitemap.xml` liste les pages FR + EN
- [ ] `https://immohorizon.com/robots.txt` pointe vers le sitemap
- [ ] Search Console : propriété vérifiée
- [ ] `immohorizon.ca` redirige vers `.com` (301)
