# Plan de test — branche `claude/funny-newton-XDLdY` (juin 2026)

Couvre les 3 chantiers de la branche / PR #684 :
**1) Téléphonie (appels sortants + droits)**, **2) Édition des mesures**,
**3) SEO-geo (P1, P3–P6)**.

Format : **Étapes → Résultat attendu**. Connecte-toi en **Propriétaire**
sauf indication contraire.

---

## 0. Pré-requis (avant de tester)

- [ ] **Déployer `h2-0` (API) puis le web** sur Render depuis le commit de tête.
  Le `init_db` du lifespan ajoute les colonnes additives :
  `users.phone_e164`, `users.voice_enabled`, `calls.outbound_result_processed`,
  `contact_requests.lost_reason`. (Pas de migration Alembic.)
- [ ] **Twilio** : credentials actifs + un **numéro de téléphone actif** dans
  la base (section A indisponible sinon).
- [ ] **2 téléphones** sous la main pour la section A : *ton* mobile (agent)
  et un *2e* numéro jouant le « prospect ».
- [ ] (Optionnel) Vérifier les env : `VOICE_RECORD_OUTBOUND` (def. `true`),
  `VOICE_OUTBOUND_CONSENT_SAY`, `OUTBOUND_NO_ANSWER_SMS`.

> ⚠️ La section A modifie le **TwiML du chemin d'appel en production** et
> n'est pas testable hors Twilio. À faire avec de vrais appels.

---

## A. Téléphonie — appels sortants ⭐ (Twilio requis)

### A1 — Droit d'accès (`voice_enabled`)
1. **Employé sans droit** : en admin, `/app/utilisateurs` → sélectionne un
   employé → bascule **Téléphonie = OFF**. Reconnecte-toi en tant que lui,
   ouvre une fiche prospect, clique **Appeler**.
   - *Attendu :* refus **403 `no_voice_access`**, message clair « ton compte
     n'a pas accès à la téléphonie ».
2. **Accorder le droit** : en admin, bascule **Téléphonie = ON** pour lui.
   Il réessaie.
   - *Attendu :* l'appel n'est plus bloqué par le droit (passe à l'étape A2).
3. **Owner / admin** : avec ton compte Propriétaire (droit implicite).
   - *Attendu :* accès même si le flag `voice_enabled` est à false.

### A2 — Le mobile de l'utilisateur connecté sonne
4. **Sans numéro** : profil de l'utilisateur **sans** mobile renseigné →
   clique **Appeler**.
   - *Attendu :* **400 `no_user_phone`** → message « Ajoute ton numéro de
     mobile dans ton profil pour passer des appels (Profil → Mobile). »
5. **Renseigner le mobile** : **Profil → Mobile (click-to-call)**, saisis
   successivement `514-961-9015`, `(514) 961-9015`, `+15149619015`,
   enregistre.
   - *Attendu :* à chaque fois normalisé/enregistré en **E.164**
     (`+15149619015`).
6. **Appel réel** : ouvre une fiche prospect → **Appeler**.
   - *Attendu :* **ton** mobile sonne (« Ton mobile va sonner — décroche »).
     Tu décroches → la ligne du **prospect** est composée.
7. **Numéro géré par admin** : en admin, `/app/utilisateurs` → un user →
   champ **Mobile relié** → saisis un numéro → enregistre.
   - *Attendu :* le numéro est mémorisé (normalisé E.164) ; cet utilisateur
     peut appeler sans avoir touché à son profil.

### A3 — Annonce de consentement (Loi 25)
8. Le « prospect » (2e téléphone) **décroche** un appel sortant.
   - *Attendu :* une **annonce de consentement** se joue (whisper) **avant**
     la mise en relation (texte = `VOICE_OUTBOUND_CONSENT_SAY`). Désactivée
     si `VOICE_RECORD_OUTBOUND=false`.

### A4 — Automatisation post-appel
9. **Bascule de statut** : prospect en **« Nouveau »**, lance l'appel.
   - *Attendu :* passe à **« À rappeler »** dès la création de l'appel.
10. **Appel abouti** : prospect décroche, conversation, raccrochage.
    - *Attendu :* journalisé dans **SUIVIS & RELANCES** (`FollowUp` type
      *appel*) ; **aucun SMS** auto.
11. **Non-réponse** : prospect ne décroche pas (sonnerie vide / occupé).
    - *Attendu :* **SMS automatique** envoyé au prospect
      (`OUTBOUND_NO_ANSWER_SMS`) **+** appel journalisé.
12. **Idempotence** : (si reproductible) Twilio rejoue le callback de
    résultat.
    - *Attendu :* **un seul** SMS et **un seul** log (garde
      `outbound_result_processed`).
13. **Enregistrement + résumé** : avec `VOICE_RECORD_OUTBOUND=true`, sur un
    appel laissé sur messagerie.
    - *Attendu :* enregistrement capté + **résumé IA** visible (résumé du
      message vocal).

### A5 — Motif de perte
14. Fiche prospect → menu de **statut** → groupe **« Refusé / Perdu »** →
    choisis **« Information de contact erroné »**.
    - *Attendu :* statut forcé à **`lost`** ; le **motif s'affiche** sur la
      fiche.
15. Rebascule le prospect vers un statut actif (≠ perdu).
    - *Attendu :* le **motif est effacé** (cohérence).

---

## B. Mesures sauvegardées — édition (aucune dépendance externe)

> Volet **Construction → Calculateur de superficie / « Mesures
> sauvegardées »** sur une fiche client ou prospect.

### B1 — Relevé de pièce (checklist)
16. Sur une carte type **« Cuisine 175,8 ft² »**, clique le **crayon** *ou*
    le **chiffre de superficie**.
    - *Attendu :* le formulaire de relevé s'ouvre **pré-rempli** (type
      verrouillé, toutes les valeurs présentes), titre **« Modifier »**.
17. Modifie un champ (ex. **Plancher**) → **Mettre à jour**.
    - *Attendu :* l'**aire principale se recalcule** ; la carte reflète la
      nouvelle valeur.
18. Rouvre, change quelque chose, clique **Annuler**.
    - *Attendu :* aucune modification conservée.

### B2 — Mesure simple (polygone / mur / photo)
19. Sur une mesure **polygone** ou **mur**, clique le crayon.
    - *Attendu :* modal compact ; édition **libellé / aire / hauteur de mur
      (mur seulement) / notes** → **Mettre à jour** met la carte à jour.
20. Sur une mesure **sur photo**.
    - *Attendu :* l'unité affichée est **`ft`** (longueur), pas `ft²` ;
      libellé = « Longueur max ».

### B3 — Persistance & lisibilité
21. Après une édition, **recharge la page**.
    - *Attendu :* les changements sont **persistés** (PATCH sauvegardé).
22. Bascule **thème clair** puis **sombre** sur ces cartes.
    - *Attendu :* tout le texte reste **lisible** (règle CLAUDE.md), aucun
      blanc-sur-blanc / noir-sur-noir.

---

## C. SEO-geo (vérifiable après déploiement)

### C1 — Sitemap découvre les articles (P1)
23. Ouvre **`/sitemap.xml`**.
    - *Attendu :* présence des **`/blog/{slug}`** (FR) **et** des
      **`/en/blog/{slug}`** (articles EN), en plus des 12 pages cœur et des
      **432** pages géo.
24. **Résilience** : si l'API blog est momentanément down au build.
    - *Attendu :* le sitemap renvoie quand même cœur + 432 géo (pas de
      crash, juste sans les articles).

### C2 — Breadcrumb JSON-LD (P3)
25. Ouvre une page géo, ex. **`/renovation/cuisine/brossard`** → code source.
    - *Attendu :* le `@graph` JSON-LD contient **`BreadcrumbList`**
      (Accueil → Cuisine → *Cuisine à Brossard*), en plus de `Service` et
      `FAQPage`.
26. Passe l'URL au **Google Rich Results Test**.
    - *Attendu :* `Service`, `FAQPage` et `BreadcrumbList` détectés sans
      erreur.

### C3 — Maillage géo ↔ blog (P4)
27. Page géo dont la ville+service a des articles (ex. cuisine + une grande
    ville déjà couverte par le cron).
    - *Attendu :* section **« Guides — {service} à {ville} »** avec jusqu'à
      **4** liens d'articles pertinents.
28. Page géo **sans** article correspondant encore.
    - *Attendu :* la section **n'apparaît pas** (pas de bloc vide).

### C4 — Pagination du blog (P6)
29. Ouvre **`/blog`**.
    - *Attendu :* **24** articles max ; bouton **« Suivant → »**.
30. **« Suivant → »** puis **« ← Précédent »**.
    - *Attendu :* `/blog?page=2` charge la suite ; retour OK ; sur la
      dernière page, **« Suivant »** disparaît.

### C5 — Harmonisation Saint-Bruno (P5)
31. Après quelques runs du cron SEO, vérifie un article Saint-Bruno + la page
    `/renovation/{service}/saint-bruno`.
    - *Attendu :* `target_city` = **« Saint-Bruno-de-Montarville »** ; la
      section Guides de la page géo **fait le lien** (mêmes libellés).

---

## D. Régression / smoke (rapide)

32. **Voix entrante** : un appel entrant vers le numéro principal.
    - *Attendu :* la secrétaire IA répond comme avant (non régressé par les
      ajouts sortants).
33. **Profil** : enregistrer prénom/nom/couleur (sans toucher au mobile).
    - *Attendu :* sauvegarde OK, rien d'écrasé.
34. **`/app/utilisateurs`** : autres bascules (rôle, assignation).
    - *Attendu :* inchangées.

---

## Déjà vérifié automatiquement (pas à refaire)

- `tsc` : **aucune nouvelle erreur** (les 2 erreurs sur la route
  `renovation` préexistent sur `main`).
- `next lint` : propre sur les fichiers touchés.
- Backend : syntaxe OK ; ordre des routes blog correct
  (`/blog/sitemap` déclaré avant `/blog/{slug}`).

## Critère de merge

- **Bloquant** : section **A** (appels réels) verte — c'est le « à tester
  avec un vrai appel avant merge » que tu avais noté.
- Sections **B** et **C** : vertes (peu risquées, mais à confirmer en prod).
- Si A n'est pas testable tout de suite, option : sortir B + C sur une PR
  isolée et merger, en gardant A en attente.
