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

## Permissions v2 (2026-07-24) — résolution unifiée

Bug d'origine : un employé avec les volets « entreprises (feuille de
temps) + immobilier » ne voyait pas Gestion d'entreprise — la tuile du
portail et le layout du pôle exigeaient un rôle owner/admin codé en dur.

**Règle unique, partout** : *on entre dans un pôle dès qu'AU MOINS UNE de
ses pages est accessible* (rôle ≥ seuil configuré OU exception
individuelle). Cette règle pilote :

- la tuile du sélecteur de portail (`login-form.tsx`, `canEnterVolet`) —
  qui mène à la PREMIÈRE page accessible (`firstAllowedPath`) ;
- le layout du pôle (`entreprises`/`immobilier`/`investisseur`) — plus
  aucun rôle codé en dur ;
- l'AccessGuard — racine de pôle refusée → redirection auto vers la
  première page accessible ; page profonde refusée → écran verrou avec
  bouton « Aller à mes pages » ;
- les routeurs API (`require_volet` → `user_has_volet_access`) — une
  exception de page ouvre aussi les API du volet (fini l'UI qui montre
  une page dont les données 403ent) ;
- `compute_access` dérive `volet:<v>` = « au moins une page visible »
  APRÈS application des exceptions.

**Whitelists d'emails supprimées** (`user.py`) : les volets viennent
uniquement de `volets_json` (page Utilisateurs / Permissions). Migration
one-shot au boot (`ensure_volets_whitelist_migration`) : les comptes
anciennement whitelistés gardent leurs volets, désormais en DB.

**Registre complété** : paie (admin), communications, suivis,
utilisateurs immobilier (admin), diagnostic, comparables, kanban
prospection, plan de suivi, /dev, /letmetalk, contact devlog public.
Entrée fantôme `entreprises.projets` retirée. ⚠️ `/app/paie` et
`/immobilier/utilisateurs` héritaient d'un seuil EMPLOYÉ — désormais
admin par défaut (reconfigurables dans Paramètres → Permissions).

## Actions v2 (2026-07-24) — couverture élargie

10 nouvelles capacités branchées (endpoint + grille « Actions
sensibles » + vue « par utilisateur ») :

| Capacité | Défaut | Endpoints |
|---|---|---|
| `timesheet.approve` / `timesheet.reopen` / `timesheet.delete` / `timesheet.facturer_qbo` | gestionnaire | timesheets.py (approve / reopen / delete / facturer-qbo) |
| `frais_gestion.facturer` / `frais_gestion.delete` | gestionnaire | immobilier_frais_gestion.py (facturer, facturer-groupe / delete facture) |
| `soumission.send` | employé | soumission_send.py |
| `contrat_gestion.send` | gestionnaire | contrats_gestion.py (send) |
| `qbo.push` | employé | facture_qbo.py, achat_qbo.py, soumission_qbo.py |
| `entreprise.delete` | **admin** ⚠️ (aucun garde de rôle avant) | entreprises.py (delete) |

`require_capability` honore désormais les **exceptions individuelles**
(`user_has_capability` : allow force l'accès, deny le retire, owner
jamais bloqué) — même règle que `compute_access`, donc la vue « par
utilisateur » et les endpoints disent toujours la même chose.
