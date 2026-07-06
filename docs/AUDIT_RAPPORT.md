# Audit & refactoring Kratos — nuit du 5 au 6 juillet 2026

> Rapport produit par Claude (session de nuit autonome, branche `refactor/nuit-audit-2026-07-06`).
> Objectif : code plus propre, documenté, optimisé, **sans aucun changement visible pour les utilisateurs**.
> Ce document se lit de haut en bas : résumé, méthode, baseline, constats, actions, propositions.

## 1. Résumé exécutif

*(rédigé en fin de nuit — voir dernière section)*

## 2. Méthode et garde-fous

- **Branche isolée** : `refactor/nuit-audit-2026-07-06`, jamais mergée dans `main` sans validation de Phil.
- **Gate avant chaque commit** : `tsc --noEmit` (frontend) + `pytest` complet (backend) doivent être verts ; le lint ne doit jamais être pire que la baseline.
- **Interdits respectés** : aucun `.env`/secret touché, aucune migration/modification de schéma BD, aucune désinstallation de dépendance sans vérification exhaustive des usages, aucun major bump, aucun changement aux contrats de l'API MCP/clé API.
- **Dans le doute → rien modifié**, consigné dans `docs/PROPOSITIONS.md`.
- Un commit = un module ou un correctif, format `[pôle][type] description` (types : refactor, fix, cleanup, docs, perf, test).

## 3. Baseline (état de référence avant tout changement)

Mesurée sur `main` @ `4f115df7` (2026-07-05, soir).

| Vérification | Résultat | Détail |
|---|---|---|
| Backend `pytest` | ✅ 49/49 | 11 s — uniquement des tests de calculs purs (`backend/tests/services/`) |
| Frontend `tsc --noEmit` | ✅ propre | |
| Frontend `next build` | ✅ | build de prod complet |
| Frontend `next lint` | ⚠️ erreurs préexistantes | `no-html-link-for-pages` ×~23 dans `DriveFolderExplorer.tsx:1697` (+ warnings hooks dans `LeadAnalysisDetailModal.tsx`) — non bloquant en CI |

Couverture de tests avant : **6 fichiers de tests, 49 tests, 0 test d'API/HTTP** (aucun filet sur l'auth, le CRUD, la facturation, les contrats MCP).

### Plus gros fichiers (dette de taille, à ne PAS réécrire cette nuit)

| Fichier | Lignes |
|---|---|
| `frontend/.../dev-logiciel/projets/[id]/page.tsx` | 8 082 |
| `frontend/.../app/projets/[id]/page.tsx` | 6 766 |
| `backend/app/api/v1/endpoints/voice.py` | 5 482 |
| `frontend/src/components/leads/LeadAnalysisDetailModal.tsx` | 4 668 |
| `backend/app/api/v1/endpoints/devlog.py` | 4 156 |
| `backend/app/api/v1/endpoints/immobilier.py` | 4 045 |
| `backend/app/api/v1/endpoints/lead_analyses.py` | 3 411 |
| `backend/app/db/session.py` | 3 018 |

Volume total : ~344 000 lignes de source (py + ts + tsx), 925 fichiers suivis par git.

## 4. Constats de l'audit

*(alimenté au fil de la nuit — voir sections par dimension)*

## 5. Actions réalisées (commits)

*(liste finale en fin de nuit)*

## 6. Bugs corrigés vs bugs documentés

*(liste finale en fin de nuit)*

## 7. Propositions non exécutées

Voir `docs/PROPOSITIONS.md` (changements risqués : migrations, réécritures massives, major bumps, contrats MCP).

## 8. Prochaines étapes recommandées

*(en fin de nuit)*
