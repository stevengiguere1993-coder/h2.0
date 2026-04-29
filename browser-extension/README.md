# Horizon h2.0 Helper — Extension navigateur

Extension Chrome/Edge qui scrape automatiquement le rôle d'évaluation
de Montréal (montreal.ca) et les annonces Centris (centris.ca) depuis
ton vrai navigateur, et envoie les données au backend h2.0.

**Pourquoi une extension ?** montreal.ca utilise reCAPTCHA v3 invisible
et Centris utilise Cloudflare/Datadome. Ces protections bloquent les
scrapers automatiques sur VPS mais laissent passer ton vrai navigateur
(qui a une historique Google + IP résidentielle légitime).

## Installation (1 fois, ~2 min)

1. Ouvre Chrome ou Edge
2. Va sur `chrome://extensions/` (ou `edge://extensions/`)
3. Active **Mode développeur** (toggle en haut à droite)
4. Clique **Charger l'extension non empaquetée**
5. Sélectionne le dossier `browser-extension/` de ce repo
6. L'icône Horizon apparaît dans la barre d'extensions

## Configuration (1 fois)

1. Clique sur l'icône Horizon dans la barre d'extensions
2. Remplis :
   - **Backend URL** : `https://h2-0.onrender.com` (production)
     ou `http://localhost:8000` (dev local)
   - **API Key** : récupère-la dans h2.0 → Paramètres → Extension
     (admin uniquement)
3. Clique **Enregistrer** puis **Tester** — tu dois voir « ✅ Connexion OK »

## Utilisation

### Rôle d'évaluation Montréal

1. Va sur https://montreal.ca/role-evaluation-fonciere
2. Cherche ton matricule (Par matricule → 6 sous-champs → Rechercher)
3. Sur la **fiche détaillée** (étape 4 du flow), un toast vert apparaît
   en haut à droite : « ✅ N proprio(s) envoyé(s) à h2.0 »
4. Dans h2.0, ouvre la modale Immeuble MTL pour ce matricule — les
   propriétaires sont déjà là (avec enrichissement REQ + Canada411).

### Centris

1. Navigue sur centris.ca comme d'habitude
2. Sur chaque fiche d'annonce, l'extension détecte et envoie les
   données à h2.0 (toast vert)
3. Si l'annonce est rentable au calculateur, h2.0 crée un lead
   automatiquement avec le tag `centris-interessant`.

## Côté serveur

Set la variable d'environnement `EXTENSION_API_KEY` sur le backend
(la même valeur que celle entrée dans la popup). Cette clé est
partagée — tous les utilisateurs du browser extension utilisent la
même.

Pour générer une clé sécurisée :

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Endpoints backend

- `POST /api/v1/extension/ping` — test de connexion (requiert
  `X-Extension-Key`)
- `POST /api/v1/extension/evalweb-owners` — reçoit les owners
  scrapés (matricule + owners[])
- `GET /api/v1/extension/evalweb-owners/{matricule}` — frontend polle
  ici (cache TTL 10 min)
- `POST /api/v1/extension/centris-listing` — reçoit une annonce
  Centris (mls_id + détails)
- `GET /api/v1/extension/centris-listing/{mls_id}` — récupère une
  annonce du cache

## Troubleshooting

### Le toast apparaît jamais sur Montréal
- Vérifie que tu es bien sur la fiche détaillée (étape 4 avec
  « 1. Identification de l'unité » + « 2. Propriétaire »)
- Ouvre la console DevTools (F12) → onglet Console → cherche
  `[h2.0 EvalWeb]` pour voir les logs du content script

### « ❌ Backend URL non configurée »
- Clique l'icône extension → re-enregistre la config

### « ❌ HTTP 401 »
- L'API key dans la popup ne match pas `EXTENSION_API_KEY` côté serveur
- Vérifie avec l'admin h2.0 que la clé est la bonne
