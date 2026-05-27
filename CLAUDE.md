# CLAUDE.md

Notes de travail pour Claude Code sur ce repo (h2.0 — Horizon Services Immobiliers).

## Workflow Git — merge automatique

Quand je termine une tâche de code (feature, fix, refactor) :

1. Commit + push sur la branche de session
2. Création de la PR vers `main`
3. Merge automatique de la PR (méthode `merge`, pour rester cohérent avec le pattern existant `Merge: <résumé>` ou `<titre> (#XXX)`)

### Conditions pour merger automatiquement
- La tâche est **explicitement terminée** (pas un commit intermédiaire / spike / debug).
- Le code semble cohérent (pas de syntax error évident, pas de TODO non résolu critique).
- Si une CI / type-check / test échoue ou est suspect, on s'arrête et on signale avant de merger.

### Ce qui reste hors limite
- Force-push sur `main`
- `--no-verify`, `--no-gpg-sign` ou autre bypass de hooks
- Merger une PR qu'un humain a explicitement marquée en review ou bloquée

## Structure du repo

- `backend/` — FastAPI + PostgreSQL + SQLAlchemy async + Alembic
- `frontend/` — Next.js 15 + TypeScript + Tailwind + next-intl (FR/EN)
- `render.yaml` — Blueprint Render (1 API, 1 web, 1 cron quotidien)

Le portail interne s'appelle **Kratos** et est découpé en **volets** (construction,
prospection, immobilier, devlog, gestion locative, courtage, etc.). L'utilisateur
indique généralement dans quel volet on travaille.

## Statuts pipeline construction (`ContactRequestStatus`)

Ordre : `new` → `contacted` → `rdv_prevu` → `qualified` → `quoted` → `won` / `lost` / `spam`.
La colonne `status` en DB est `String(32)` (varchar libre), pas un enum natif PostgreSQL —
ajouter une valeur ne nécessite pas de migration Alembic.
