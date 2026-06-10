# État du produit — **Kratos** / Horizon Services Immobiliers (juin 2026)

Synthèse au **2026-06-10**, à partir de l'historique Git **complet**
(**1666 commits, 3 janv. → 10 juin 2026**, du PR #1 à ~#772), des modèles,
endpoints, crons et intégrations.

---

## 0. Genèse & trajectoire (du PR #1 à aujourd'hui)

**L'idée fondatrice** (visible dès les premiers modèles d'avril :
*« add core business models to replace Monday boards »*) :
**sortir du patchwork Monday.com** et tout réunir dans un système maison
unique. Une couche `monday_bridge` a servi de pont pendant la migration,
puis Kratos a internalisé chaque board en module natif.

| Période | Commits | Ce qui se construit |
|---|---|---|
| **Janv–févr. 2026** | ~40 | Amorçage : dépôt, **authentification**, fondations. |
| **Avril 2026** | ~570 | **Le grand build.** Scaffold Next.js bilingue, portail interne, modèles métier « pour remplacer Monday » : soumissions, projets, punch, factures, achats, employés/paie, prospection, immobilier, SEO/blog. |
| **Mai 2026** | ~910 | **Industrialisation & intégrations.** QuickBooks (massif), Google Drive, Dev logiciel, modèles stratégiques **QG**, copilote IA, maturité **téléphonie/softphone**. |
| **Juin 2026** | ~150 | Affinage : appels **sortants** click-to-call, édition des mesures, **SEO-geo**, durcissement. |

> Lecture : en ~10 semaines effectives (avril→juin), Horizon est passé d'un
> assemblage d'outils (Monday + manuel) à un **ERP/CRM multi-métiers
> intégré**. La vélocité est très élevée (souvent plusieurs PR/jour, &gt;770
> PR au total).

---

## 1. L'idée générale

**Kratos** est le **système d'exploitation interne unique** d'Horizon : un
ERP/CRM maison qui couvre *toute* la chaîne de valeur de l'entreprise, de la
génération de leads à la facturation et la comptabilité, sur **plusieurs
métiers** sous un même toit :

- **Construction / rénovation** (le cœur historique),
- **Prospection immobilière** (achat d'immeubles),
- **Gestion locative** (immeubles, baux, locataires),
- **Dev logiciel** (une agence dans l'agence, avec son propre CRM),
- **Investisseur / courtage** (offres, promesses d'achat, NDA),
- **Gestion d'entreprise** (tâches, copilote IA, pilotage stratégique),
- **Téléphonie IA** (secrétaire « Léa », appels, SMS),
- **Site public + SEO-geo** (acquisition).

Le tout est traversé par une couche **IA** (cascade gratuite Gemini →
Anthropic → Groq) qui automatise le contenu, la qualification, les résumés
et le pilotage. La promesse : **un seul interlocuteur logiciel**, zéro
ressaisie, et de l'automatisation partout où c'est répétitif.

---

## 2. Architecture & infra

- **Backend** : FastAPI + SQLAlchemy async + PostgreSQL. ~110 modules
  d'endpoints, ~140 modèles, ~150 services métier.
- **Frontend** : Next.js 15 + TypeScript + Tailwind + next-intl (FR/EN).
- **Hébergement (Render)** : 1 API, 1 web, **6 crons** (SEO, relances
  factures, relances devlog, relances suivis horaires, fermeture punch,
  détection de problèmes Kratos).
- **Schéma DB** : additif au démarrage (`init_db` + `ALTER` idempotents),
  **pas d'Alembic** pour la plupart des colonnes → simple, mais voir §7.

---

## 3. Cartographie des volets & maturité

| Volet | Couvre | Maturité |
|---|---|---|
| **Construction** | leads→soumissions→projets→bons→factures→achats, punch, paie, sous-traitants | 🟢 Solide |
| **Comptabilité / QBO** | sync QuickBooks (achats, factures, taxes, classes, paiements) | 🟢 Solide (57 PR de durcissement) |
| **Google Drive** | arborescence auto, conventions de nommage, auto-upload, liens entités | 🟢 Solide (48 PR) |
| **Dev logiciel** | CRM complet : clients, contrats, devis, factures Stripe, NPS, projets | 🟢 Solide |
| **Prospection** | leads, deals, analyses, listes, données immeubles MTL, scoring | 🟡 En place |
| **Immobilier / locatif** | immeubles, logements, baux, locataires, import PlexFlow, loyers marché | 🟡 En place, en consolidation |
| **Téléphonie (Voice)** | secrétaire IA, entrant/sortant, softphone, SMS, voicemail, résumés | 🟡 En place, **sortant non testé en réel** |
| **Investisseur / courtage** | offres, promesses d'achat, NDA, signatures | 🟡 En place |
| **Gestion d'entreprise / Copilote** | org, tâches, insights IA, pouls stratégique (QG) | 🔵 Jeune |
| **SEO-geo public** | 432 pages géo, moteur d'articles IA, sitemap | 🟢 Solide (vient d'être durci) |

---

## 4. Intégrations externes

QuickBooks Online · Google Drive · Twilio (Voice + SMS) · Meta (webhooks
leads) · Stripe (devlog) · Centris · CMHC · Banque du Canada · Monday ·
Nominatim/OpenRouteService (géocodage) · cascade IA (Gemini/Anthropic/Groq).

---

## 5. Chantiers de la branche courante (`claude/funny-newton-XDLdY`)

1. **Téléphonie** : click-to-call sur le mobile de l'agent connecté + droit
   d'accès par utilisateur (admin) + automatisation post-appel (statut, SMS
   non-réponse idempotent, enregistrement + résumé) + motif de perte.
2. **Mesures** : édition d'une mesure sauvegardée (clic → modifier).
3. **SEO-geo** : cartographie + P1 (sitemap articles), P3 (breadcrumb), P4
   (maillage géo↔blog), P5, P6 (pagination).

> ⚠️ Cette branche **mélange** des changements à risque (chemin d'appel
> Twilio en prod, **non testés en réel**) avec des changements sûrs (mesures,
> SEO). Voir §7 « rendre facile ».

---

## 6. Ce qui reste à faire (priorisé)

### Court terme (fonctionnel)
- **Téléphonie — « qui a appelé »** : la ligne `Call` ne mémorise pas
  l'agent qui lance un appel sortant → l'onglet Communications ne peut pas
  l'afficher. *(Demande explicite en cours — prêt à implémenter.)*
- **Téléphonie — valider en réel** : passer la **section A** du plan de test
  (`docs/plan-de-test-...md`) avec de vrais appels avant merge.
- **SEO P2** : vraies pages **EN** (traduction du gabarit `renovation` + des
  données `seo-locations.ts`) → marché anglophone (West Island).

### Moyen terme (consolidation)
- **Gestion locative** : finir le cycle (renouvellements de baux, avis,
  états de compte locataire) — modèles présents, parcours à compléter.
- **Copilote / QG** : passer de « jeune » à « utile au quotidien » (actions
  concrètes depuis les insights, pas juste de l'affichage).
- **Prospection** : industrialiser scoring + enrichissement propriétaires.

---

## 7. Ce qui serait utile à **automatiser & rendre facile**

C'est ici que se trouve le plus gros levier de productivité.

1. **Tests automatisés (le manque #1).** Aujourd'hui la validation est
   **manuelle** (séquences de test en Markdown). À mettre en place :
   - **pytest** sur la logique pure (calculs d'argent/taxes, normalisation
     E.164, idempotence des webhooks, bascules de statut, filtres API) ;
   - **Playwright** sur 5–6 parcours critiques (login, créer soumission,
     click-to-call, import PlexFlow, signer un document).
   → Transforme chaque « plan de test » en **garde-fou rejouable**.

2. **CI qui bloque vraiment.** Le `tsc` du repo a des **erreurs
   préexistantes** (routes typées next-intl) → le filet est troué. Nettoyer
   ces erreurs puis rendre `tsc`/lint/pytest **bloquants** sur chaque PR.

3. **PRs petites et par sujet.** Une seule branche longue accumule
   mesures + SEO + téléphonie. Adopter **1 sujet = 1 branche = 1 PR** évite
   de retenir du code sûr derrière du code à tester (cas actuel).

4. **Migrations versionnées (Alembic).** Le schéma additif au boot est
   pratique mais fragile (ordre, types, rollback). Des migrations rendent
   les déploiements **prévisibles et réversibles**.

5. **Santé & déploiement.** Healthcheck `/health` + smoke post-deploy
   (le sitemap dépend de l'API, les crons supposent le schéma à jour) pour
   détecter une régression **avant** les utilisateurs.

6. **Observabilité des crons.** 6 crons tournent en silence. Un mini-tableau
   « dernier run / succès / volume » (la table `cron_runs` existe déjà)
   rendrait les automatisations **visibles et fiables**.

7. **Automatisations métier à fort ROI** (dans l'esprit déjà en place) :
   - relances **devis/soumissions** comme les factures ;
   - **résumé d'appel → tâche de suivi** auto (boucler voix ↔ CRM) ;
   - **rapprochement bancaire** QBO assisté ;
   - **avis de renouvellement de bail** automatiques (locatif).

---

## 8. Risques à garder en tête

- **Chemin d'appel Twilio en prod non testé** sur la branche courante.
- **Filet de test troué** (manuel + `tsc` non bloquant).
- **Dépendances externes nombreuses** (QBO, Drive, Twilio, Meta) → surface
  de panne large, d'où l'intérêt de l'observabilité (#6).
- **Branche fourre-tout** → blast radius difficile à cerner par déploiement.
