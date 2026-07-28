# Environnement de test (staging)

**Adresse du staging : https://h2-0-web-dev.onrender.com**

Le nouveau code se merge d'abord sur la branche `dev`, se teste sur le
staging, puis — après le GO — se pousse sur `main` (production,
immohorizon.com).

```
branche dev  → h2-0-dev (API) + h2-0-web-dev (site) → h2-0-web-dev.onrender.com
branche main → h2.0     (API) + h2.0-0-web   (site) → immohorizon.com
```

> Pas de domaine dev.immohorizon.com : le plan gratuit Render limite à
> 2 domaines personnalisés par workspace et la prod les utilise déjà
> (immohorizon.com + www). L'URL onrender.com est équivalente (HTTPS
> inclus) — à mettre en favori. Pour débloquer plus de domaines :
> workspace Professional (~19 $ US/mois), pas justifié.

## Garanties de sécurité (déjà codées)

| Chose                | Production            | Staging (dev)                          |
|----------------------|-----------------------|----------------------------------------|
| Base de données      | Postgres Render (h2-0db) | **kratos-staging** (Render Basic-256mb, ~6 $/mois) — séparée, jamais la prod |
| Courriels (M365)     | Envoyés aux vrais destinataires | **Tous redirigés vers Phil** (`MAIL_REDIRECT_ALL_TO`) — sujet préfixé « [TEST → destinataire réel] », cc/bcc vidés |
| QuickBooks           | Synchronisé           | **Débranché** (aucune clé posée)       |
| Twilio (SMS/appels)  | Actifs                | **Débranchés** (aucune clé posée)      |
| Crons (rappels…)     | Actifs                | **Aucun cron** en staging              |
| Interface            | Normale               | Bandeau jaune « ENVIRONNEMENT DE TEST » |

La redirection courriel : chaque envoi du staging part POUR VRAI, mais
uniquement vers l'adresse configurée (`MAIL_REDIRECT_ALL_TO`) — Phil
reçoit le courriel exact que le locataire/client aurait reçu, avec le
destinataire original dans le sujet. Personne d'autre ne reçoit rien
(cc/bcc vidés, copie superviseur sautée). Variante silencieuse
disponible : `MAIL_CAPTURE_ONLY=true` (journalise sans rien envoyer).

## Mise en place — ~15 minutes de clics (une seule fois)

> ⚠️ On crée les 2 services **à la main** (PAS via « Blueprint ») : les
> services de prod n'ont pas été créés par blueprint, et une instance
> Blueprint essaierait de les DUPLIQUER (double backend, crons en double
> → doubles courriels de rappel). Création manuelle = zéro risque.
>
> Fais tout ça dans le même workspace Render que ta production (celui où
> tu vois le service `h2-0`).

### 1. La base de données de test (Render, ~7 $ US/mois) — 3 min
> Pourquoi pas la gratuite ? Le Postgres GRATUIT de Render s'autodétruit
> après 30 jours — le staging casserait chaque mois. La plus petite base
> payante Render (~7 $ US/mois) est pérenne et reste 100 % dans le setup
> actuel. (Alternative 0 $ si jamais : Neon.tech, gratuit et pérenne,
> mais c'est un compte externe de plus.)

1. Render → **+ New → Postgres**.
2. Name : `kratos-staging` · Region : **Oregon (US West)** (même que le
   reste) · Plan : le plus petit payant (**Basic-256mb**, ~7 $ US/mois).
3. **Create Database**, attends ~1 min qu'elle soit « Available ».
4. Sur la page de la base, section **Connections** : copie
   l'**Internal Database URL** (commence par `postgresql://…`). Garde-la
   pour l'étape 2.

> Le backend crée toutes ses tables tout seul au premier démarrage —
> rien d'autre à faire côté base.

### 2. Le service BACKEND de test — 5 min, écran par écran
1. Render → **+ New → Web Service**.
2. Écran « Source Code » : clique la ligne
   **stevengiguere1993-coder / h2.0**.
3. Le formulaire de configuration s'ouvre. Remplis EXACTEMENT :

| Champ              | Valeur                                       |
|--------------------|----------------------------------------------|
| Name               | `h2-0-dev`                                   |
| Project            | (laisser tel quel, ou choisir H2.0 WEB SERVICE) |
| Language           | Python 3 (normalement détecté tout seul)     |
| Branch             | **`dev`** ⚠️ dérouler — le défaut est main   |
| Region             | Oregon (US West)                             |
| Root Directory     | `backend`                                    |
| Build Command      | `pip install -r requirements.txt`            |
| Start Command      | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Instance Type      | **Free**                                     |

4. Plus bas, section **Environment Variables** : bouton « + Add
   Environment Variable », une ligne par variable du tableau ci-dessous.
   (Pour les 3 valeurs AZURE : ouvre dans un AUTRE onglet le service
   **h2-0** → Environment → clique l'œil pour révéler → copie-colle.)
5. Bouton **Deploy Web Service** tout en bas. Le premier build prend
   5-10 min ; à la fin le statut passe « Live ».

| Clé | Valeur |
|-----|--------|
| `PYTHON_VERSION` | `3.11.11` |
| `ENV` | `staging` |
| `DATABASE_URL` | l'**Internal Database URL** de `kratos-staging` (étape 1) |
| `JWT_SECRET` | une longue chaîne aléatoire (PAS celle de prod) |
| `FRONTEND_ORIGINS` | `https://dev.immohorizon.com,https://h2-0-web-dev.onrender.com` |
| `MAIL_REDIRECT_ALL_TO` | `phil.meuser@hotmail.com` |
| `MAIL_FROM_EMAIL` | `info@immohorizon.com` |
| `MAIL_FROM_NAME` | `Horizon (TEST)` |
| `AZURE_TENANT_ID` | même valeur que le service h2-0 (Environment) |
| `AZURE_CLIENT_ID` | même valeur que le service h2-0 |
| `AZURE_CLIENT_SECRET` | même valeur que le service h2-0 |

> Les 3 clés Azure servent UNIQUEMENT à ce que les courriels de test
> puissent partir (vers ton adresse). NE PAS copier les clés
> QuickBooks/Twilio/Monday — c'est voulu, ces intégrations restent
> débranchées en staging.

### 3. Le service FRONTEND de test — 4 min
Même chemin : **+ New → Web Service** → ligne
**stevengiguere1993-coder / h2.0**, puis :

| Champ              | Valeur                          |
|--------------------|---------------------------------|
| Name               | `h2-0-web-dev`                  |
| Language           | Node                            |
| Branch             | **`dev`**                       |
| Region             | Oregon                          |
| Root Directory     | `frontend`                      |
| Build Command      | `npm install && npm run build`  |
| Start Command      | `npm run start`                 |
| Instance Type      | **Free**                        |

Environment Variables :

| Clé | Valeur |
|-----|--------|
| `NODE_VERSION` | `20` |
| `NEXT_PUBLIC_SITE_URL` | `https://dev.immohorizon.com` |
| `NEXT_PUBLIC_API_BASE_URL` | `https://h2-0-dev.onrender.com` |
| `NEXT_PUBLIC_DEFAULT_LOCALE` | `fr` |
| `NEXT_PUBLIC_ENV_BADGE` | `Environnement de test` |

### 4. Le domaine dev.immohorizon.com — 3 min
1. Render → service **h2-0-web-dev** → **Settings → Custom Domains** →
   ajoute `dev.immohorizon.com`. Render affiche la cible CNAME.
2. **Cloudflare** → zone immohorizon.com → **DNS → Add record** :
   type `CNAME`, nom `dev`, cible `h2-0-web-dev.onrender.com`.
3. Retour dans Render : le domaine passe « Verified » après quelques
   minutes, certificat HTTPS automatique.

### 5. Premier compte sur le staging (bootstrap owner)
L'inscription Kratos est réservée aux admins → sur la base NEUVE, le
premier compte se crée par BOOTSTRAP : poser sur **h2-0-dev** les
variables `BOOTSTRAP_ADMIN_EMAIL` + `BOOTSTRAP_ADMIN_PASSWORD` → au
prochain démarrage, si la table users est VIDE, un compte owner est créé
avec ces identifiants. Sans effet dès qu'un utilisateur existe (donc
inoffensif en prod). Ensuite : connexion sur le staging avec ces
identifiants, puis créer les immeubles/locataires bidon.

## Au quotidien (rien à faire — pour référence)

- Claude merge le nouveau code sur `dev` → déploiement auto sur
  dev.immohorizon.com (~3 min).
- Phil teste (premier accès après une pause : ~50 s de réveil, c'est le
  plan gratuit qui dort).
- GO → Claude merge `dev` dans `main` → production.
- La branche `dev` est resynchronisée sur `main` après chaque promotion.

## Notes

- Les services free s'endorment après ~15 min sans trafic : 0 $ en
  permanence, ~50 s d'attente au premier clic. (Le staging n'est PAS
  dans le workflow keep-alive — c'est voulu.) Pour un staging toujours
  chaud : plan Starter (7 $ US/mois) dans Render, réversible en un clic.
- Pour tester avec des données réalistes, demander à Claude un script de
  copie prod → staging (à la demande, jamais automatique).
