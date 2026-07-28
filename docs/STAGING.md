# Environnement de test — dev.immohorizon.com

Environnement de STAGING identique à la production, à 0 $/mois :
le nouveau code se merge d'abord sur la branche `dev`, se teste sur
**dev.immohorizon.com**, puis — après le GO — se pousse sur `main`
(production, immohorizon.com).

```
branche dev  → h2-0-dev (API) + h2-0-web-dev (site) → dev.immohorizon.com
branche main → h2-0     (API) + h2-0-web     (site) → immohorizon.com
```

## Garanties de sécurité (déjà codées)

| Chose                | Production            | Staging (dev)                          |
|----------------------|-----------------------|----------------------------------------|
| Base de données      | Postgres Render       | **Neon gratuite, séparée** — jamais la prod |
| Courriels (M365)     | Envoyés pour vrai     | **Capturés** (journalisés, rien ne part) — `MAIL_CAPTURE_ONLY=true` |
| QuickBooks           | Synchronisé           | **Débranché** (aucune clé posée)       |
| Twilio (SMS/appels)  | Actifs                | **Débranchés** (aucune clé posée)      |
| Crons (rappels…)     | Actifs                | **Aucun cron** en staging              |
| Interface            | Normale               | Bandeau jaune « ENVIRONNEMENT DE TEST » |

Le mode capture (`MAIL_CAPTURE_ONLY`) rend le mailer « prêt » : tous les
flux d'envoi (communications, signatures, rappels) se testent au complet —
le succès s'affiche, l'audit s'écrit, mais AUCUN courriel ne part. Les
courriels capturés sont visibles dans les logs Render du service
`h2-0-dev` (préfixe `[MAIL CAPTURÉ — staging]`).

## Mise en place — ~15 minutes de clics (une seule fois)

### 1. La base de données de test (Neon, gratuite) — 5 min
1. Va sur **https://neon.tech** → « Sign up » (avec le compte GitHub, c'est 2 clics).
2. Crée un projet (nom : `kratos-staging`, région : US East/Ohio — proche d'Oregon ça va).
3. Sur le tableau de bord du projet, copie la **Connection string**
   (commence par `postgresql://…neon.tech/…`). Garde-la pour l'étape 3.

> Le backend crée toutes ses tables tout seul au premier démarrage
> (init_db) — rien d'autre à faire côté base.

### 2. Les deux services Render — 5 min
1. **https://dashboard.render.com** → bouton **New → Blueprint**.
2. Choisis le repo `h2.0` → Render lit `render.yaml` et propose la liste
   des services. Les services existants (h2-0, h2-0-web, crons) sont
   reconnus ; les DEUX NOUVEAUX sont `h2-0-dev` et `h2-0-web-dev`.
3. Approuve la création. (S'il demande des valeurs pour `DATABASE_URL` /
   `JWT_SECRET` de h2-0-dev, passe à l'étape 3.)

*Alternative si le Blueprint chicane* : crée les 2 services à la main
(New → Web Service → repo h2.0) en recopiant les réglages de la section
STAGING de `render.yaml` (branche **dev**, rootDir backend/frontend,
plan **Free**).

### 3. Les variables du backend de test — 2 min
Dans Render → service **h2-0-dev** → onglet **Environment** :
- `DATABASE_URL` = la connection string Neon de l'étape 1
- `JWT_SECRET` = n'importe quelle longue chaîne aléatoire (PAS celle de
  prod — les sessions de test restent séparées)
- (facultatif) `GEMINI_API_KEY` / `GROQ_API_KEY` = mêmes valeurs que le
  service h2-0, si on veut tester les features IA en staging

### 4. Le domaine dev.immohorizon.com — 3 min
1. Render → service **h2-0-web-dev** → **Settings → Custom Domains** →
   ajoute `dev.immohorizon.com`. Render affiche la cible CNAME
   (`h2-0-web-dev.onrender.com`).
2. **Cloudflare** (le DNS du domaine) → zone immohorizon.com → **DNS →
   Add record** : type `CNAME`, nom `dev`, cible
   `h2-0-web-dev.onrender.com`, proxy activé ou non (les deux marchent).
3. Retour dans Render : le domaine passe « Verified » après quelques
   minutes, certificat HTTPS automatique.

### 5. Premier compte sur le staging
La base de test est VIDE (aucun locataire réel). Ouvre
dev.immohorizon.com, crée ton compte — le premier compte peut être promu
admin comme au lancement de la prod. Ensuite ajoute un immeuble/locataire
bidon pour tester.

## Au quotidien (rien à faire — pour référence)

- Claude merge le nouveau code sur `dev` → déploiement auto sur
  dev.immohorizon.com (~3 min).
- Phil teste (premier accès après une pause : ~50 s de réveil, c'est le
  plan gratuit qui dort).
- GO → Claude merge `dev` dans `main` → production.
- La branche `dev` est resynchronisée sur `main` après chaque promotion.

## Notes

- Les services free s'endorment après ~15 min sans trafic : 0 $ en
  permanence, ~50 s d'attente au premier clic. Pour un staging toujours
  chaud : passer h2-0-dev (et/ou h2-0-web-dev) au plan Starter
  (7 $ US/mois chacun) dans Render — réversible en un clic.
- Neon gratuit dort aussi et se réveille en ~1 s — transparent.
- Pour tester avec des données réalistes, demander à Claude un script de
  copie prod → staging (à la demande, jamais automatique).
