# Séquence de test — tout ce qui a été livré (session juin 2026)

À exécuter **après déploiement de `h2-0`** sur Render. Connecte-toi en
**Propriétaire** (Zachary/Steven). Format : **Étapes → Résultat attendu**.

---

## A. Rôles & accès (PR #618, #619, #620)

1. **Tous les volets** — Connecte-toi, va à l'accueil du portail.
   - *Attendu :* tu vois toutes les pastilles : Construction, Prospection,
     Dév logiciel, Entreprises, Immobilier, Investisseurs, Téléphonie.
2. **Zachary** — Mets Zachary **Administrateur** dans `/app/utilisateurs`,
   il se reconnecte.
   - *Attendu :* il voit et accède à tout, mode DEV inclus.
3. **Manager/employé** — Un compte gestionnaire/employé.
   - *Attendu :* accès inchangé (limité à ses volets).

## B. Lisibilité couleurs — mode clair (PR #607, #624)

4. Active le **thème clair**. Va dans **Paie**, génère un rapport.
   - *Attendu :* les heures (Sem. 1 / Sem. 2) sont **lisibles** (texte
     foncé), plus de blanc sur blanc.

## C. Courriel de RDV (PR #602)

5. Crée un RDV (agenda) lié à un prospect, à **9 h**.
   - *Attendu :* le courriel affiche « dimanche 7 juin 2026 **à 9 h 00
     (heure de Montréal)** » — en français, pas en UTC.

## D. Suivi / session (PR #603)

6. Laisse expirer ta session, puis enregistre un suivi.
   - *Attendu :* message clair « Session expirée — reconnecte-toi (ta
     note reste saisie) », **la note n'est pas perdue**.

## E. Import PlexFlow (PR #622, #626)

7. **Immobilier → Immeubles → Importer PlexFlow.** Colle un bloc PlexFlow.
   **Prévisualiser**.
   - *Attendu :* aperçu par compagnie/immeuble/logement ; nb logements et
     baux cohérents avec les KPI PlexFlow.
8. **Matching** — Compagnies « 9417-1287 Québec Inc. », « 8900 St-Hubert
   inc », « 9520-8955 Québec inc ».
   - *Attendu :* affichées **« rattachée »** (vert) automatiquement.
9. **Mapping manuel** — Pour « 9510-7520 Québec inc. », ouvre le menu
   déroulant, choisis **BGV**.
   - *Attendu :* passe à « rattachée » ; l'aperçu se rafraîchit.
10. **Importer pour de vrai.**
    - *Attendu :* immeubles + logements + locataires + baux créés ;
      compteur de résultat affiché.
11. **Idempotence** — Réimporte le même bloc.
    - *Attendu :* immeubles déjà présents marqués **« déjà importé »** et
      **non dupliqués**.

## F. Fiche immeuble (PR #625, #628)

12. Ouvre un immeuble importé.
    - *Attendu :* logements, baux, locataires visibles dans les onglets.
13. **Changer propriétaire** — Sélecteur « Propriétaire » → autre entreprise.
    - *Attendu :* l'immeuble bascule sous la nouvelle compagnie.
14. **Photo** — Clique la vignette, choisis une image.
    - *Attendu :* la photo s'affiche ; bouton « Retirer » fonctionne.
15. **Supprimer** — Bouton « Supprimer » → confirmation → confirmer.
    - *Attendu :* modale d'avertissement (cascade) ; après confirmation,
      retour à la liste, immeuble disparu.

## G. Compagnies & navigation (PR #623, #628, #630)

16. **Baux & paiements** — Sélectionne une compagnie dans la sidebar.
    - *Attendu :* seuls **ses** immeubles s'affichent (plus tous mélangés).
17. **Renommer compagnie** — Sélecteur d'entreprise → crayon → nouveau nom.
    - *Attendu :* le nom est mis à jour partout.
18. **Menu Locataires** — Regarde le menu latéral immobilier.
    - *Attendu :* « Locataires » **absent** du menu ; les locataires se
      voient dans la fiche immeuble.

## H. Lead construction (PR #631)

19. Soumets une **demande de soumission** via le formulaire public (avec
    une vraie adresse courriel à toi).
    - *Attendu :* tu reçois un courriel « demande bien reçue, on vous
      téléphonera sous peu » (FR ou EN selon la langue), depuis
      `info@immohorizon.com`.

## I. Polices / build (PR #621)

20. Vérifie que le **déploiement Render réussit** et que les polices
    s'affichent normalement.
    - *Attendu :* plus d'échec de build sur `fonts.gstatic.com`.

---

## Non couvert (phases à venir)

- **Phase 4** — Bons de travail ↔ Construction (à construire).
- **Phase 3** — QuickBooks / fiducie (⚠ nécessite identifiants QBO).
- **Phase 6** — Calendriers employés (⚠ nécessite OAuth Google/Microsoft).
- **Phases 2.4-2.6** — Signatures de bail/renouvellement, avis
  d'augmentation (à construire).
- **Phase 1.7** — Enrichir l'import (dates de bail réelles, dépôt,
  contacts locataire).
