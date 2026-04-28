"""Scraper Centris — multi-logements à vendre.

Centris (centris.ca) est l'agrégateur officiel des courtiers
immobiliers du Québec. Anti-bot agressif (Cloudflare + Datadome).

Stratégies disponibles :
1. **HTTP direct** : tente `httpx` avec des headers réalistes. Marche
   parfois pour la liste de recherche (paginated SPA mais avec
   `__NEXT_DATA__` dans le HTML initial). Retourne 403 ou 503 si
   Cloudflare bloque.
2. **Manual paste** : l'utilisateur copie le HTML d'une page de
   résultats Centris depuis son navigateur (où il est déjà
   « humain ») et le colle dans une textarea. On parse côté serveur.
   100% fiable, indépendant du blocage côté serveur.
3. **Playwright** (différé — nécessite Render Pro 2 GB+) : automation
   navigateur headless. Bypasse Cloudflare en exécutant la JS.

Ce module expose :
- `parse_listings_html(html)` : parse une page de résultats Centris
- `try_fetch_listings(url)` : tente le HTTP direct, retourne le HTML
  ou lève si bloqué
"""
