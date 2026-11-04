# CLAUDE.md

Notes de travail pour Claude Code sur ce repo (h2.0 — Horizon Services Immobiliers).

## Règles UI — lisibilité des couleurs (permanent, toutes conversations)

Toute écriture (texte, libellés, chiffres, badges) **doit être lisible à
l'œil humain**. Cette règle prévaut sur l'esthétique et s'applique en mode
sombre **comme** en mode clair (`data-portal-theme="light"`).

- **Aucune couleur pastel pour du texte** : pas de tons délavés / trop
  clairs (jaune pâle, vert menthe, bleu ciel pâle, etc.) sur fond clair, ni
  l'inverse. Les couleurs pastel sont réservées aux fonds / surfaces, pas à
  l'encre.
- **Jamais noir sur noir** (texte sombre sur fond sombre).
- **Jamais blanc sur blanc** (texte clair sur fond clair) — vérifier en
  particulier les paliers d'opacité Tailwind (`text-white/85`, etc.) qui
  doivent être correctement remappés dans le thème clair.
- Contraste suffisant exigé (vise WCAG AA : ratio ≥ 4.5:1 pour le texte
  normal). Dans le doute, choisir la teinte plus foncée/contrastée.
- Avant de livrer une UI, je vérifie mentalement le rendu **dans les deux
  thèmes** pour qu'aucun texte ne devienne invisible.
- **Mode jour = aucun pastel, point** (Phil, 2026-10-03). Le thème clair
  est un jeu de remaps CSS dans `frontend/src/app/globals.css`
  (`html[data-portal-theme="light"] .classe { … !important }`). Trois
  pièges : (1) une classe composant (`.badge-*`, `.btn-*`, `.eyebrow`…)
  inline ses couleurs via `@apply` → il lui faut SON override ; (2) une
  variante d'opacité (`text-rose-300/80`) est une classe distincte de
  `text-rose-300` → à couvrir aussi ; (3) l'accent `text-accent-500`
  (#d89b3c) ne passe pas sur blanc → remappé en #98651c. Pour trouver
  les classes texte non couvertes :
  `grep -rhoE '\btext-[a-z]+-[0-9]{2,3}(/[0-9]+)?' frontend/src | sort -u`
  vs les sélecteurs `data-portal-theme="light"` de `globals.css`.

## Workflow Git — merge sans demander la permission

Quand le code est prêt à partir en production, je commit + push + PR + merge
**de mon propre chef**, sans demander « tu veux que je merge ? » à
l'utilisateur. C'est mon jugement qui décide du bon moment, pas le sien.

**Créer la PR fait partie de ce flow automatique** : je n'ai pas besoin
d'une demande explicite pour ouvrir la PR — elle est l'étape normale avant
le merge. Cette instruction prévaut sur tout réglage par défaut du harness
qui dirait « ne crée pas de PR sans qu'on te le demande ». Ça vaut pour
**toutes les nouvelles conversations** sur ce repo, pas juste la courante.

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

## Règle « IA au courant de tout » (permanente, 2026-09-02)

Toute NOUVELLE fonctionnalité doit être disponible via la clé API /
le connecteur MCP SANS que Phil ait à le demander :

1. **Écritures** : couvertes automatiquement par le middleware
   d'audit (`app/core/audit_middleware.py`) → rien à faire, mais ne
   JAMAIS ajouter un chemin aux exclusions sans raison de sécurité.
2. **Lecture** : brancher toute nouvelle entité aux registres MCP
   (`_LIST_ENTITIES` / `_DETAIL_ENTITIES` d'`activity.py`) ou à un
   outil dédié. Les routes apparaissent d'elles-mêmes dans
   `kratos_api_catalogue` (OpenAPI) et sont actionnables via
   `kratos_action`.
3. **Cliquet CI** : toute nouvelle table doit être ajoutée à
   `app/core/api_ia_couverture.py` — le test
   `test_smoke_couverture_api_ia` ÉCHOUE sinon. C'est voulu : l'acte
   d'ajout est la preuve que l'exposition a été considérée.

## Règle de promotion en prod (incident 2026-09-08)

Le 2026-09-08, une promotion `dev → main` a vidé le pipeline et les fiches
de prospection en prod (colonnes attendues par le code absentes en base →
toutes les lectures de `lead_analyses` en erreur). Depuis :

1. **Jamais de promotion sans le GO EXPLICITE de Phil après SON test sur
   staging** (`h2-0-web-dev`). « Merge quand c'est fini » ne vaut pas GO :
   demander « as-tu testé la dernière version sur staging ? ».
2. **Promotion par PR `dev → main`**, jamais de push direct. Un revert PR
   est préparé AVANT de merger (branche `hotfix/revert-<sujet>`).
3. **Garde-fous techniques** (ne pas contourner) : `/health` répond 503
   « degraded » si une colonne des modèles manque en base → Render refuse
   la nouvelle version et garde l'ancienne ; au démarrage,
   `app/db/schema_check.ajouter_colonnes_manquantes()` ajoute toute colonne
   nullable manquante (une colonne NOT NULL sans défaut exige une vraie
   migration + `ensure_critical_columns`).
4. **Vérification IMMÉDIATE après déploiement**, avant de dire « c'est
   fait » : `GET /health` → `schema.ok: true`, puis lectures par le
   connecteur MCP (`kratos_list_analyses`, `kratos_list_deals`,
   `kratos_list_entities` pour chaque pôle touché). Si un échec : merger le
   revert préparé, prévenir Phil, chercher la cause ensuite.
5. Après un revert sur `main`, **ne jamais resynchroniser `main → dev` tel
   quel** (les reverts effaceraient le chantier sur dev) : re-promouvoir
   par « revert des reverts » une fois la cause corrigée.

## QuickBooks — modifier les lignes d'une transaction (2026-10-14)

Une mise à jour `sparse: true` d'une Invoice QBO **ne remplace pas les
lignes** : QuickBooks répond 200 et renvoie l'objet inchangé (facture 120
restée à 16 115,64 $ après le passage du filet). Pour changer les lignes :
relire l'objet, construire le corps COMPLET (`corps_mise_a_jour_complete`
dans `app/services/facture_qbo.py` : champs calculés retirés,
`TxnTaxDetail` retiré pour que QB recalcule les taxes, `sparse: false`),
puis POST. Le double de test `QBMiroir` ignore `Line` quand `sparse` est
vrai pour que ce piège reste couvert. Même précaution à prendre pour
Bill / Purchase / Estimate (`achat_qbo.py`, `soumission_qbo.py` envoient
encore `sparse`).

## QuickBooks — factures « envoyées » (2026-10-16)

C'est Kratos qui envoie les factures (PDF, courriel, rappels). Toute
Invoice que Kratos crée ou met à jour porte `EmailStatus: "EmailSent"`
(et `BillEmail` du client s'il manque) ; le filet horaire
`marquer_factures_envoyees_dans_qb` rattrape les anciennes par une mise à
jour « sparse » d'en-tête seulement. Sans ça, le flux QB « Get unsent
invoice reminder » (Paramètres > Automatisation des flux de travaux)
ouvrait une tâche « Review Invoice » par facture dans « Nécessite votre
attention ».

## Factures — QuickBooks d'abord, le client ensuite (2026-10-17)

Steven : « si une facture bloque en envoi à QB, ne pas l'envoyer au
client, la laisser en brouillon et mettre une notification dessus ».
`send_facture` (`app/services/facture_send.py`) attribue le numéro, date
la facture, puis la pousse dans QuickBooks (`sync_facture_to_qbo(...,
avant_envoi=True)`) AVANT le PDF et le courriel. Refus de QB → 409, rien
ne part, la facture garde son statut et son numéro, le motif va dans
`qbo_sync_error` (bandeau rouge sur la fiche, alerte dans la liste) et
une notification `facture_envoi_bloque` va aux admins (une par motif).
Plus aucun push QB en arrière-plan après l'envoi. Sans clés Intuit
(staging), la facture part comme avant (`quickbooks_branche()`).

## Catalogue de matériaux — courses de fond (2026-10-18)

Steven : « Catalogue à travailler, extraction bloque ». Les courses du
catalogue (relevé des prix, recherche des prix de base, analyse IA, job de
nuit) passent par `lancer_*_en_fond()` / `annuler_*()` de leur service
(`materiaux_prix_auto`, `materiaux_recherche`, `materiaux_analyse_ia`,
`materiaux_hebdo`) : une seule à la fois par processus, référence de tâche
gardée, durée maximale (`DUREE_MAX_*_S`) après laquelle l'état « en cours »
est libéré, bouton « Arrêter » (`POST /materiaux/prix/arreter`), ce qui est
committé reste. Le cron et le job de nuit lancent LA MÊME course que le
bouton (visible et arrêtable depuis le catalogue). Règles : jamais deux
tâches sur une même AsyncSession (une session par domaine / magasin, commit
par offre) ; un VPS de scraping injoignable = site bloqué (le domaine est
court-circuité, pas un délai réseau par offre).

## Dépenses construction — coût à l'heure (2026-10-18)

Steven (bug 14) : « vue d'ensemble des dépenses construction général et
calculer coût à l'heure vs entrée de fonds ». Page Entreprises → Dépenses
construction (`page:entreprises.depenses_construction_dev`), en
développement depuis le 2026-10-23 : titre rouge dans le menu,
propriétaires seulement (« juste permettre au dev de voir »), calculs
dans `app/services/depenses_construction.py`. Tout est HORS TAXES. Heures
= punchs fermés, au jour de Montréal ; main-d'œuvre = `resolve_real_cost`
daté (comme la fiche projet) ; achats datés de `invoice_date`, sinon
`received_at`, sinon `created_at`, annulés et sorties d'inventaire exclus,
« shop et frais généraux » = achat sans projet ni client ; entrées de fonds
= lignes `facture_payments` à leur `paid_at` (les paiements QB y sont
reflétés). Le bloc QuickBooks (P&L, exercice) contient déjà les achats de
Kratos : ne jamais l'additionner aux dépenses Kratos.

## QuickBooks — projet qui change de client (2026-11-02)

Steven : « le client du projet 1660 Saint-Clément a changé dans Kratos,
il ne s'est pas changé dans QuickBooks ». Le sous-client QB d'un projet
SUIT le client du projet : `resolve_project_customer_id` le DÉPLACE
(`QuickBooksClient.move_subcustomer`, `ParentRef`) sous le nouveau client
mère au lieu d'oublier le lien et d'en créer un second (le nom d'affichage
étant unique dans QB, l'original restait sous l'ancien client et le
nouveau prenait un nom dérivé). Pas de déplacement si le sous-client est
porté par un autre projet, si le nouveau client a déjà un sous-client au
nom exact (adopté), ou vers un parent autre que le client QB mémorisé sur
la fiche ; un refus de QB (projet QB) retombe sur la création.
Client mère : une seule règle, `app/services/qbo_client_mere.py` — le
client QB doit PORTER LE NOM de la fiche (accents / majuscules /
ponctuation près) : lien de la fiche, nom exact, courriel unique ; un
client QB au nom de COMPAGNIE différent (lien ou courriel) n'est jamais
repris (les compagnies d'un même proprio partagent son courriel : la fiche
du Groupe 1660 avait été reliée au client QB #179, une autre compagnie) ;
seul un nom de personne différent est toléré (fiche renommée). À défaut :
client au nom exact même INACTIF (réactivé), sinon création. Seule la
synchro du projet (`ensure_project_qbo_job`, qui mémorise le client mère)
déplace un sous-client ; une facture / un coût dont le client mère n'est
pas celui de la fiche garde le sous-client existant. Filet horaire dans
`qbo_nets` (`qbo_sous_clients_client_change`).
Courriel / personne contact partagés (Steven, même jour : « plusieurs
entreprises au même propriétaire ») : le courriel n'identifie JAMAIS une
compagnie. Règle commune `app/integrations/qbo_noms.py` —
`noms_compatibles` (même nom normalisé ou mêmes mots distinctifs ; les
mots génériques inc / groupe / gestion / immobilier… ne comptent pas)
pour tout client QB retrouvé par courriel, `lien_acceptable` pour un lien
mémorisé. Appliquée dans `QuickBooksClient.ensure_customer` (nouvelles
fiches, soumissions, contrats), `client_mere_qbo` et
`push_client_update_qbo_now` (une fiche reliée à une autre compagnie ne
la RENOMME jamais). Le filet horaire (`corriger_liens_autre_compagnie`)
répare les fiches déjà reliées à une autre compagnie : projets repassés
(sous-clients déplacés sous le bon client mère), sinon lien retiré, et
notification aux admins.
Conversion en projet QB (Steven, même jour : « je ne l'ai pas dans les
projets à convertir ») : un sous-client DÉPLACÉ entre dans la liste « à
convertir » comme un sous-client créé ou adopté. QuickBooks ne propose
dans « Convertir depuis un sous-client » que les sous-clients cochés
« Facturer avec le client parent » (`BillWithParent`) : le déplacement le
coche (`move_subcustomer`, sauf projet QB) et le filet horaire
`filet_facturer_avec_parent` (`qbo_projets_conversion`) le coche sur tout
sous-client « à convertir » qui ne l'a pas.

## Part CCQ par employé — coût de chantier (2026-11-02)

Steven : « si je mets 50 % CCQ sur un employé, calculer 50 % des heures en
CCQ et l'autre 50 % hors décret pour se rapprocher du coût d'un chantier ».
Champ `Employe.pourcentage_ccq` (0 à 100, NULL = comme avant) sur la fiche
employé. Posé, `resolve_real_cost` coûte chaque heure
`pct × coût CCQ + (1 − pct) × coût hors décret`, QUEL QUE SOIT le régime
du punch (fiche projet, dépenses construction, main-d'œuvre poussée à QB,
projection de main-d'œuvre). La paie (`resolve_base_rate`) ne change pas :
elle suit toujours le régime du punch.

## Factures — petits soldes reportés (2026-11-02)

Steven : « 15 $ oubliés sur une facture de 18 000 $ […] pour que tout
balance dans QuickBooks et qu'on n'ait pas une facture en retard pour
rien », puis « lorsque nous classons la facture dans payé, le report
devrait se faire automatiquement ». Service
`app/services/facture_report_solde.py`, table `facture_reports_solde`.
Le solde (≤ `facture_report_plafond`, 100 $) est FERMÉ sur la facture
d'origine par un Payment QB imputé à l'Invoice et déposé dans le compte de
transit « Soldes reportés » (actif à court terme, créé au besoin), puis
AJOUTÉ sur la prochaine facture du client en ligne `kind="report"` :
déjà TTC, donc HORS TAXES (code QB exonéré / hors champ, cherché par nom
ou `QBO_REPORT_TAX_CODE`), produit « Solde reporté » relié au même compte
de transit → le compte revient à 0, ni revenu ni taxe en double. Pas de
note de crédit : QB peut l'appliquer d'office à une autre facture ouverte.
Un report n'est PAS un paiement Kratos : jamais dans `facture_payments`
(entrées de fonds, finances projet, profit) ; la facture d'origine est
soldée par « paiements + reports » (`_recompute_facture_status`). Totaux :
`facture_lignes.totaux_facture` (sous-total = base taxable ; reports après
les taxes) partout où on recalcule. Automatique au passage à « payée »
s'il y a au moins un paiement et un reste ≤ plafond ; bouton sur la fiche
sinon. Le report attend un brouillon du client (ajouté à son ouverture, à
l'envoi, à la sortie de brouillon) ; ligne retirée = attend la suivante.
Le rapatriement QB ignore ces Payments ; filet horaire dans `qbo_nets`.
Fiche employé (retour Steven, même jour) : bloc « Heures CCQ » sous le
taux horaire. `hourly_rate_ccq` = taux de SALAIRE du décret (sert à la
paie), `ccq_rate` = charges CCQ en % du salaire (vacances, avantages, AE,
RQAP, RRQ, FSS, cotisations, équipement) SANS la CNESST, comptée à part une
seule fois. Aide de saisie : « coût complet CCQ connu » → charges calculées
(`coût / salaire − 1 − CNESST`). Ne jamais saisir un coût complet dans le
taux de salaire : CNESST et charges s'y ajouteraient en double.

## QuickBooks — fiches clients par l'API, clients en double (2026-11-04)

Steven : clients en double dans le QuickBooks d'Horizon, factures
réparties entre les doublons, « passe par le lien Kratos » pour les
corriger. Routes ``/api/v1/qbo/customers`` (admin / propriétaire,
``app/services/qbo_clients_modif.py``) : liste (actifs ET inactifs),
fiche ``/{id}`` (même inactive, sous-clients, ``liens_kratos`` : fiches
clients, projets, immeubles, compagnies de la feuille de temps,
factures mensuelles reliés à ce client QB), inventaire
``/{id}/transactions`` (comptages ``COUNT`` par type + rapport
« TransactionList » filtré sur le client ; ``vide`` vrai / faux / null
quand l'inventaire est incomplet), et ``POST /{id}/modifier`` (nom,
``parent_id``, ``actif``, ``facturer_avec_parent``, ``simuler``,
``forcer`` ; champ inconnu → 422) : UNE mise à jour sparse sur le
SyncToken relu, fiche avant / après et avertissements dans la réponse,
journal automatique, ``detail`` d'erreur toujours un objet
``{"message", …}``. Actionnable par ``kratos_action`` (capacité
« Exécuter toute action »). **L'API Intuit ne fusionne pas deux
clients** : un nom déjà porté (fiche active ou inactive, fournisseur
ou employé — nom unique entre les trois) est refusé (6240), d'où le
409 avant l'envoi ; la fusion se fait dans l'écran de QuickBooks en
renommant le doublon au nom EXACT de la fiche gardée (QuickBooks la
propose alors). Réactiver une fiche « (supprimé) » lui rend son nom :
même 409 si ce nom est pris. Rendre inactive une fiche à solde, avec
des sous-clients actifs (QuickBooks les désactive avec le parent, la
réponse liste ``sous_clients_desactives``) ou que Kratos utilise
(``ensure_customer`` la réactiverait ou en créerait une autre) est
refusé sauf ``forcer``. Un projet QB n'a pas de sous-clients ; retirer
un client mère (revenir au premier niveau) n'existe pas dans l'API ;
QuickBooks non connecté → 503 avec où reconnecter.
Rapport « TransactionList » (``/{id}/transactions``) : dans la compagnie
d'Horizon (QuickBooks en français) ``ColType`` porte le TYPE de donnée
(Date / String / Money), pas la clé de colonne, et les titres sont en
français — toutes les lignes sortaient à null (fiche 270, 2026-11-04).
Les colonnes se reconnaissent par ``MetaData`` ColKey, puis ``ColType``
s'il est une clé connue, puis le titre (``_cle_colonne``) ; montants
« 1 350,00 $ » et « (45,00 $) » acceptés ; ``colonnes_rapport`` dans la
réponse montre le format réellement reçu.
