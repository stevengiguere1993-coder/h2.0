# Roadmap — Gestion immobilière + Construction (vision Steven, juin 2026)

Plan de route découpé en **phases** et **sous-phases**, pour avancer par
petits incréments (chaque sous-phase = 1 PR testable). Légende effort :
**S** (heures), **M** (1-2 jours), **L** (plusieurs jours / dépend
d'externe). « ⚠ Externe » = nécessite une décision, un compte ou des
identifiants de Steven.

---

## Systèmes de référence (inspiration)

Logiciels de gestion locative performants dont on s'inspire (je ne m'y
connecte pas — je connais leurs fonctionnalités) :

- **AppFolio / Buildium** : comptabilité en fiducie (trust accounting)
  native, portail locataire (paiement en ligne, demandes de maintenance),
  owner statements, virements automatiques aux propriétaires.
- **DoorLoop / RentManager** : workflow bons de travail ↔ fournisseurs,
  rappels de retard automatiques, e-signature de baux.
- **Hemlane / Avail** : avis de renouvellement + augmentation, screening
  locataire, communications centralisées.
- **Stessa** : tableau de bord financier par immeuble, lien bancaire.

**Éléments « best of » retenus pour Kratos :**
1. Rent roll **par immeuble** (les locataires vivent dans la fiche
   immeuble, pas dans un menu séparé) ✅ confirme ton intuition.
2. Trust accounting (fonds de fiducie) + un compte d'encaissement unique.
3. E-signature baux + renouvellements + avis d'augmentation conformes
   (Québec : TAL — Tribunal administratif du logement).
4. Bons de travail reliés aux fournisseurs, convertibles en
   projet/facture, avec autorisation client de l'estimé.
5. Rappels de retard automatiques + relances.

---

## PHASE 1 — Import & gestion de base des immeubles (EN COURS)

- [x] 1.1 Import PlexFlow (immeubles + logements + locataires + baux) — copier-coller, aperçu, mapping compagnie. **S/M** ✅
- [x] 1.2 Matching compagnie tolérant + mapping manuel (BGV, Millen). ✅
- [x] 1.3 Supprimer un immeuble (fiche, avec confirmation). ✅
- [x] 1.4 Changer l'entreprise propriétaire d'un immeuble. ✅
- [x] 1.5 Renommer une compagnie. ✅
- [x] 1.6 Photo de l'immeuble (ajout/changement dans la fiche). ✅
- [ ] 1.7 Enrichir l'import : dates réelles de bail, dépôt, courriel/téléphone locataire (collage enrichi ou saisie). **M**
- [ ] 1.8 Dédoublonnage intelligent + ré-import « mettre à jour si existe ». **M**

## PHASE 2 — Locataires, baux, communications

- [ ] 2.1 Sortir « Locataires » du menu latéral → vue par immeuble (rent roll dans la fiche). **S**
- [ ] 2.2 Fiche locataire complète (contacts, historique paiements, score). **M**
- [ ] 2.3 Lieux/baux : gestion fine des baux par logement. **M**
- [ ] 2.4 E-signature de bail (réutiliser le module de signature existant — sign-nda/sign-offer). **M**
- [ ] 2.5 Renouvellement de bail + signature. **M**
- [ ] 2.6 Avis d'augmentation conformes TAL (génération + envoi). **M/L**
- [ ] 2.7 Communications locataires (journal + envoi courriel/SMS). **M** (SMS ⚠ Externe : téléphonie)

## PHASE 3 — Paiements & fiducie (loyers) ⚠ Externe (QuickBooks)

- [ ] 3.1 Compte d'encaissement unique : config + rattachement. **M**
- [ ] 3.2 Connexion QuickBooks Online (OAuth, multi-compagnies). **L ⚠** (app QBO + accès comptable)
- [ ] 3.3 Confirmation auto de réception des loyers via ligne d'opération bancaire → classement « fonds de fiducie » dans QBO. **L ⚠**
- [ ] 3.4 Virements automatiques à date X vers les bons comptes par compagnie. **L ⚠**
- [ ] 3.5 Avis de retard automatiques après X jours. **M**

## PHASE 4 — Bons de travail ↔ Construction

- [ ] 4.1 Créer un bon de travail depuis la gestion immobilière (réparation sur un immeuble/logement). **M**
- [ ] 4.2 Le bon de travail atterrit dans le volet Construction ; un responsable le gère. **M**
- [ ] 4.3 Convertir la compagnie propriétaire en **client** si pas déjà inscrite. **S/M**
- [ ] 4.4 Budget/estimé lié au bon de travail ; envoi au client/responsable pour **autorisation**. **M**
- [ ] 4.5 Transformer le bon de travail → **projet** OU le garder bon de travail → **facture**. **M**

## PHASE 5 — Leads construction + téléphonie ⚠ Externe (téléphonie)

- [ ] 5.1 Nouveau lead → courriel auto de confirmation « on vous rappelle bientôt », envoyé depuis l'identité de l'entreprise. **S/M ⚠** (identité d'envoi)
- [ ] 5.2 (plus tard) Prise de RV automatique une fois les calendriers connectés.

## PHASE 6 — Calendriers employés (construction) ⚠ Externe (OAuth)

- [ ] 6.1 Courriel à tous les employés construction : instructions pour connecter leurs calendriers à Kratos. **S**
- [ ] 6.2 Connexion calendriers : Google **(API OK)**, Microsoft/Outlook **(API OK)**, Apple **(⚠ CalDAV + mot de passe app, pas d'API officielle)**. **L ⚠**
- [ ] 6.3 Logique de disponibilité : un événement dans un autre calendrier = « occupé » sans révéler le motif. **M**
- [ ] 6.4 Export bidirectionnel : un RV **client** pris dans Kratos est poussé dans les autres calendriers avec toutes les infos (les phases de projet sont exclues pour l'instant). **M/L ⚠**

---

## Ce qui nécessite une décision/des identifiants de Steven

1. **QuickBooks** : créer/partager l'app QBO (OAuth), confirmer le compte
   comptable multi-compagnies, définir le mapping compagnie → compte et
   les classes « fiducie ». (Phase 3)
2. **Téléphonie / identité d'envoi courriel** : depuis quelle adresse/n°
   les courriels « entreprise » partent. (Phases 2.7, 5.1)
3. **Calendriers** : quels fournisseurs (Google/Microsoft/Apple), et
   accepter qu'Apple soit limité (CalDAV). (Phase 6)
4. **Conformité TAL** : valider les gabarits d'avis d'augmentation /
   renouvellement. (Phase 2.6)

## Ordre conseillé

Phase 1 (finir) → 2.1/2.2 (rent roll par immeuble) → 4 (bons de travail,
gros levier opérationnel) → 5.1 (courriel lead, rapide) → 2.4-2.6
(signatures/avis) → 6 (calendriers) → 3 (QuickBooks, le plus lourd).
