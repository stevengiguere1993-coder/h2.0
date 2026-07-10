# Système d'autorisations Kratos (refonte 2026-07-10)

> PRs : #1167 (P1 registre), #1168 (P2 enforcement), #1169 (P3 page
> Permissions). Géré depuis **Paramètres → Permissions** (owner).

## Architecture — 3 couches + exceptions

| Couche | Question | Source | Appliquée où |
|---|---|---|---|
| **Volet** | A-t-il accès au PÔLE ? | `User.volets_json` (owner/admin = tous) | 66 routeurs API (`require_volet`), layouts de pôle |
| **Page** | Peut-il VOIR cette page ? | Registre `core/access_registry.py` (68 pages) + seuil de rôle configurable (table `role_permissions`, clé `page:<key>`) | AccessGuard (8 layouts), menus (sidebars/navs), calcul `/auth/me` |
| **Capacité** | Peut-il FAIRE cette action ? | `core/capabilities.py` + `role_permissions` | `require_capability` sur les endpoints sensibles, masquage UI |
| **Exceptions** | Cas particuliers par personne | `user_access_overrides` (allow/deny par clé, owner jamais bloqué) | Calcul `/auth/me` (donc partout) |

`/auth/me` renvoie le dict `access` complet (`volet:x`, `page:<key>`,
capacités). Le frontend ne duplique AUCUNE règle : il consomme `access` +
l'access-map (`GET /permissions/access-map`) pour matcher les routes
(préfixe le plus long). **Fail-open** : un chemin non régi ou un accès non
chargé laisse passer — on ne bloque que sur refus explicite.

## Couverture (vérifiée 2026-07-10)

- **Frontend** : 197 routes réelles, **160 régies** par le registre. Les 37
  non régies sont toutes des pages PUBLIQUES par design (marketing,
  signatures par token `sign-*`/`[token]`, /connexion, /installer, /blog)
  ou gardées autrement (/dev → capacité `devlog.access`).
- **Backend** : 66 routeurs métier gardés par volet — Construction 33,
  Construction+Immobilier 8 (bons, achats, mesures), Prospection 9,
  Prospection+Investisseurs 9 (offres, NDA, comparables, promesses),
  Immobilier 3, Entreprises 3, Investisseurs 1. Devlog : déjà gardé
  owner/admin (`_devlog_admin_only`), inchangé.

## Non gardé volontairement (à réévaluer au besoin)

- `voice` (téléphonie) : gardé par la capacité `telephonie.access`
  (défaut admin) plutôt que par le volet `communication` — éviter de
  bloquer un manager à qui la capacité a été accordée sans le volet.
- `employes`, `timesheets`, `leave_requests` : flux employé (demandes de
  congés, feuille de temps) — une garde de volet `entreprises` bloquerait
  les employés terrain. Restent CurrentUser/RequireManager.
- `relances`, `clients`, `contacts`, `contract_sign`,
  `subcontractor_contracts`, `agenda*` : transverses ou partagés flous.
- Routeurs publics (`public_*`, webhooks, cron, extension) : sans auth par
  design (tokens opaques / signatures).

## Ajouter une page au registre

1 entrée dans `backend/app/core/access_registry.py` (clé, libellé FR,
volet, seuil défaut, préfixes de routes). Le seed au boot, la grille de
Paramètres → Permissions, `/auth/me`, l'AccessGuard et les menus la
découvrent automatiquement.

## Pièges connus

- Une page listée dans un menu doit avoir ses préfixes dans `routes` du
  registre, sinon l'item de menu reste visible (fail-open) mais la page
  n'est pas configurable.
- `general.*` = pas de check de volet (transverse), seuil de rôle
  seulement.
- Le cache des seuils (permissions_service) a un TTL de 30 s : un
  changement dans la grille peut mettre jusqu'à 30 s à s'appliquer côté
  API (l'UI, elle, recharge `/auth/me` à la navigation).
