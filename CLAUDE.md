# CLAUDE.md

Notes de travail pour Claude Code sur ce repo (h2.0 — Horizon Services Immobiliers).

## Workflow Git — merge sans demander la permission

Quand le code est prêt à partir en production, je commit + push + PR + merge
**de mon propre chef**, sans demander « tu veux que je merge ? » à
l'utilisateur. C'est mon jugement qui décide du bon moment, pas le sien.

### Quand merger
- Le code répond à la demande de l'utilisateur et tient debout.
- Pas de TODO / debug / spike laissé en place.
- La syntaxe / le type-check / les tests rapides que j'ai pu lancer
  passent.

### Quand ne PAS merger (et le dire à l'utilisateur)
- Le code échoue à la CI, au type-check, ou aux tests.
- J'ai une incertitude réelle sur la justesse du changement.
- L'utilisateur m'a explicitement dit « ne push pas tout de suite » ou
  « attend mon test » pour cette tâche.
- Le changement touche `main` directement (force-push, reset, etc.) ou
  a un blast radius hors du scope demandé.

### Méthode de merge
- Méthode `merge` (pas squash, pas rebase) — cohérent avec le pattern
  existant `<titre> (#XXX)` ou `Merge: <résumé>`.
- Un seul PR par tâche logique terminée. Plusieurs petits commits dans
  la même tâche restent groupés.

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
