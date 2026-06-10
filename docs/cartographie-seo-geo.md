# Cartographie SEO-GEO — immohorizon.com

> Carte de l'architecture SEO locale (geo) du site public Horizon Services
> Immobiliers. Régénérée le **2026-06-10** à partir des sources de vérité :
> `frontend/src/lib/seo-locations.ts`, `frontend/src/app/sitemap.ts`,
> `frontend/src/app/[locale]/renovation/[service]/[city]/page.tsx` et
> `backend/app/jobs/seo_daily.py`.

Domaine : `https://immohorizon.com` · Locales : **FR** (défaut, sans préfixe)
et **EN** (`/en`).

---

## 1. Vue d'ensemble — 3 couches

| Couche | Type | Volumétrie | Indexation |
|---|---|---|---|
| **A. Pages pilier** | Pages éditoriales Montréal, mots-clés concurrentiels | **5** | Sitemap, `priority 1.0`, weekly |
| **B. Pages géo programmatiques** | `/renovation/{service}/{city}`, pré-rendues | **432** (54 villes × 8 services) | Sitemap, `priority 0.8`, monthly |
| **C. Moteur d'articles IA** | Blog généré par cron (`seo_daily`) | jusqu'à **~3 456** combinaisons | ⚠️ **pas au sitemap** (voir §10) |

---

## 2. Couverture géographique — 54 villes

Source : `SEO_CITIES` dans `seo-locations.ts`. Chaque ville porte `slug`,
`name`, `region`, `area` et **3 villes voisines** (maillage interne).

| Région | Nb | Villes |
|---|---|---|
| **Île de Montréal** | 22 | Montréal, Westmount, Outremont, Saint-Laurent, Anjou, LaSalle, Verdun, Rosemont, Plateau-Mont-Royal, Villeray, Mile End, Griffintown, Hochelaga, Ahuntsic, Ville-Marie, Sud-Ouest, Mercier, Notre-Dame-de-Grâce, Côte-des-Neiges, Saint-Léonard, Montréal-Nord, Lachine |
| **Rive-Sud** | 12 | Longueuil, Brossard, Boucherville, Saint-Lambert, La Prairie, Candiac, Chambly, Saint-Bruno-de-Montarville, Saint-Hubert, Saint-Constant, Châteauguay, Delson |
| **Rive-Nord** | 10 | Laval, Terrebonne, Repentigny, Mascouche, Blainville, Sainte-Thérèse, Saint-Eustache, Boisbriand, Mirabel, Rosemère |
| **West Island** | 7 | Pointe-Claire, Dollard-des-Ormeaux, Pierrefonds, Beaconsfield, Kirkland, Dorval, L'Île-Bizard |
| **Vaudreuil-Soulanges** | 3 | Vaudreuil-Dorion, Pincourt, L'Île-Perrot |

---

## 3. Catalogue de services — 8

Source : `SEO_SERVICES`. Chaque service porte `description`, `scope[]`,
3 `priceRanges` (fourchettes 2026) et 3 entrées `faq` (avec `{city}`
substitué à la volée).

| # | Slug | Libellé | Fourchette repère |
|---|---|---|---|
| 1 | `salle-de-bain` | Salle de bain | 12 k$ – 55 k$ |
| 2 | `cuisine` | Cuisine | 15 k$ – 120 k$ |
| 3 | `multilogement` | Multilogement | 6 k$ – 55 k$ |
| 4 | `complete` | Rénovation complète | 60 k$ – 500 k$+ |
| 5 | `agrandissement` | Agrandissement | 150 k$ – 400 k$ |
| 6 | `sous-sol` | Finition de sous-sol | 25 k$ – 110 k$ |
| 7 | `fenetres` | Changement de fenêtres | 650 $/u – 45 k$ |
| 8 | `terrasse` | Terrasse et patio | 8 k$ – 60 k$ |

---

## 4. Matrice & patrons d'URL

```
Couche B (432 pages)   /renovation/{service}/{city}
                       ex. /renovation/cuisine/brossard
                       → generateStaticParams() = 8 × 54 = 432 (pré-rendu)

Couche A (5 pages)     /construction-renovation-montreal
                       /entrepreneur-general-montreal
                       /renovation-cuisine-montreal
                       /renovation-salle-de-bain-montreal
                       /renovation-multilogement-montreal

Couche C (blog)        /blog                 (index, listArticles limit=20)
                       /blog/{slug}          ex. /blog/renovation-cuisine-laval-prix-2026
```

---

## 5. Pages pilier (couche A)

5 pages, toutes `priority 1.0` / `weekly` au sitemap, ciblant les requêtes
têtes de Montréal. Chacune existe physiquement sous
`src/app/[locale]/<slug>/`. Gabarit partagé : `components/seo-pillar-template.tsx`.

---

## 6. Moteur d'articles IA (couche C) — `backend/app/jobs/seo_daily.py`

Cron Render quotidien. Cascade IA `complete()` : Gemini (gratuit) →
Anthropic → Groq (coût ≈ 0 $/mois).

- **Villes ciblées** : 54 (miroir de la couche B ; seul écart de libellé :
  « Saint-Bruno » côté cron vs « Saint-Bruno-de-Montarville » côté front).
- **Services** : 8 FR + 8 EN.
- **Angles SEO** (clé de la diversité de requêtes) :
  - **FR (5)** : présentation · `prix-2026` · `comment-choisir-entrepreneur`
    · `erreurs-a-eviter` · `delais-et-permis`
  - **EN (3)** : overview · `cost-2026` · `how-to-choose-contractor`
- **Volumétrie théorique** : FR 54×8×5 = **2 160** + EN 54×8×3 = **1 296**
  → **~3 456 articles** uniques avant rotation.
- **Débit** : `SEO_DAILY_ARTICLES_PER_RUN = 3` / jour (round-robin sur les
  slots jamais générés). Couverture complète ≈ **3,1 ans** au rythme actuel.

---

## 7. Données structurées (JSON-LD)

| Page | Schemas émis |
|---|---|
| `/renovation/{service}/{city}` | `Service` (+ `areaServed: City`, `provider: GeneralContractor`) **et** `FAQPage` (3 Q/R) |
| Pages pilier | via gabarit pilier |
| `/blog/{slug}` | à confirmer (Article/BlogPosting recommandé) |

❌ **Pas de `BreadcrumbList`** sur les pages géo — voir §10.

---

## 8. Maillage interne

Chaque page `/renovation/{service}/{city}` pointe vers :
- **3 villes voisines** (même service) — via `city.nearby`.
- **7 autres services** (même ville).
- `/contact` et `/services/{service}`.

→ ~12 liens internes sortants contextualisés par page. Bon pour le geo, mais
le graphe reste **cloisonné par couche** : les 432 pages géo ne pointent pas
vers les articles de blog correspondants, et inversement.

---

## 9. Sitemap & robots

- **`sitemap.ts`** : 12 pages cœur × 2 locales + 432 pages géo (FR seule).
  Les pages géo ne sont émises **que pour la locale par défaut**.
- **`robots.ts`** : `allow /` ; `disallow` `/connexion`, `/login`, `/admin`,
  `/api/`. Sitemap + host déclarés.

---

## 10. Écarts & plan d'action — état

| # | Écart constaté | Impact | Statut |
|---|---|---|---|
| **P1** | Les ~3 456 articles IA n'étaient PAS au sitemap (seul `/blog` y figurait). | 🔴 Élevé | ✅ **Fait** — `sitemap.ts` async + endpoint `GET /blog/sitemap` ; chaque `/blog/{slug}` (FR et `/en/...`) est listé. |
| **P2** | Pages géo uniquement en FR ; pas de hreflang. | 🟠 Moyen | ⏸️ **Différé** — le gabarit `renovation` et les données `seo-locations.ts` sont 100 % en français. Émettre des URLs `/en/...` afficherait du texte FR (mauvaise langue + duplication) → **chantier de traduction de contenu**, pas un câblage. |
| **P3** | Pas de `BreadcrumbList` JSON-LD sur les pages géo. | 🟠 Moyen | ✅ **Fait** — nœud `BreadcrumbList` (Accueil → service → ville) ajouté au `@graph`. |
| **P4** | Pages géo ↔ articles de blog non reliés. | 🟡 Faible-moyen | ✅ **Fait** — section « Guides » sur chaque page géo (filtres API `service`/`city`). |
| **P5** | Libellé ville front/back divergent. | 🟢 Faible | ✅ **Fait** — `seo_daily.py` utilise « Saint-Bruno-de-Montarville ». |
| **P6** | Index blog plafonné → contenu profond peu maillé. | 🟡 Faible-moyen | ✅ **Fait** — pagination `?page=` (24/page, Précédent/Suivant). |

> Les commentaires « 80 / 400 pages » historiques dans `sitemap.ts` et
> `seo-locations.ts` ont été corrigés : le compte réel est **432** pages géo.
>
> **Reste à faire (P2)** : produire les variantes EN (copy du gabarit +
> traductions des 8 services dans `seo-locations.ts`), puis émettre les
> `/en/renovation/...` au sitemap avec `alternates.languages` FR/EN.
