"""Gabarit par défaut du contrat de gestion + rendu des placeholders.

Le texte ci-dessous reproduit la « Convention de gestion immobilière »
de MGV Développement inc. Les 7 champs variables (+ lieu + date) sont
des marqueurs `{{PLACEHOLDER}}` substitués à la génération.

Le côté **Mandataire** (MGV / Philippe Meuser, président) est fixe :
il n'est pas éditable par contrat, seulement via le gabarit global.

Ce texte sert de valeur d'amorçage (`seed`) de la table singleton
`contrat_gestion_template`. Une fois amorcé, Phil peut le modifier en
tout temps depuis les Paramètres — la constante ci-dessous n'est plus
lue (sauf pour un immeuble jamais amorcé / repli).
"""

from __future__ import annotations

import html as _html
import re
from typing import Optional


# ----- Émetteur (Mandataire) — fixe -----
MANDATAIRE_NOM = "MGV DÉVELOPPEMENT INC."
MANDATAIRE_SIEGE = "1707 Rue des Harfangs, Saint-Lin-Laurentides J5M 1A7"
MANDATAIRE_REPRESENTANT = "Philippe Meuser"
MANDATAIRE_TITRE = "président"
MANDATAIRE_COURRIEL = "info@immohorizon.com"


# Marqueurs reconnus dans le gabarit (pour l'aide UI + validation).
PLACEHOLDERS = (
    "COMPAGNIE",
    "SIEGE_SOCIAL",
    "REPRESENTANT",
    "TITRE",
    "IMMEUBLES",
    "DISTRICT",
    "COURRIEL",
    "LIEU",
    "DATE",
)


DEFAULT_TEMPLATE_MARKDOWN = """\
# CONVENTION DE GESTION IMMOBILIÈRE

CETTE CONVENTION DE GESTION EST SIGNÉE À {{LIEU}}, QC

EN DATE DU : {{DATE}}

**ENTRE :**

**{{COMPAGNIE}}**, personne morale dûment constituée en vertu de la loi, ayant son siège social au {{SIEGE_SOCIAL}}, représentée par {{REPRESENTANT}}, {{TITRE}}, dûment autorisé(e) à agir aux fins des présentes, tel qu'il le déclare.

(ci-après désigné(e) : le « Mandant »)

**ET :**

**MGV DÉVELOPPEMENT INC.**, personne morale dûment constituée en vertu de la loi, ayant son siège social au 1707 Rue des Harfangs, Saint-Lin-Laurentides J5M 1A7, représentée par son président, Philippe Meuser, dûment autorisé à agir aux fins des présentes, tel qu'il le déclare.

(ci-après désignée : le « Mandataire »)

ATTENDU QUE le Mandant est propriétaire de terrains comprenant tous leurs accessoires, circonstances et dépendances, ainsi que des bâtiments qui y sont construits et comportant des logements, dont ceux portant les adresses civiques suivantes :

{{IMMEUBLES}}

(ci-après collectivement désignés : l'« Immeuble »);

ATTENDU QUE le Mandant désire confier au Mandataire le mandat d'administrer, de gérer et de superviser l'ensemble des opérations, la gestion courante et le bon fonctionnement de tous les aspects de l'Immeuble et des affaires du Mandant qui s'y rattachent, incluant les aspects financiers, juridiques, bancaires et corporatifs décrits aux présentes ;

ATTENDU QUE le Mandant convient de retenir les services complets (« clé en main ») du Mandataire et que le Mandataire accepte, le tout selon les modalités et conditions prévues à la présente Convention de gestion (ci-après désignée : la « Convention »).

## 1. Offre de service

Le Préambule, ainsi que l'Offre de service jointe à la présente sous l'Annexe « A », font partie intégrante de la Convention.

## 2. Nomination du Mandataire

En vertu de la Convention, le Mandataire est nommé agent par le Mandant pour administrer et superviser les opérations, ainsi que pour assurer la gestion courante et complète de tous les aspects de l'Immeuble et des affaires du Mandant qui s'y rapportent, y compris, sans limiter ce qui précède, la location des logements, l'entreposage et le stationnement, la gestion financière et comptable, le suivi bancaire et hypothécaire, les mises à jour juridiques annuelles et la reddition de comptes aux partenaires, le tout selon les modalités et conditions prévues dans la Convention.

## 3. Terme

3.1. **Durée et Renouvellement :** La Convention est d'une durée initiale d'un (1) an débutant le premier jour du mois suivant sa signature. À la fin de la durée initiale, celle-ci sera automatiquement renouvelée pour des périodes successives d'un an, à moins que l'une des parties ne fournisse un avis écrit de non-renouvellement au moins 60 jours avant la fin de la période en cours.

3.2. **Ajustement des Frais :** Les termes et conditions de la Convention peuvent être révisés annuellement à la date de renouvellement automatique, moyennant l'envoi au Mandant par le Mandataire d'un préavis écrit de 90 jours avant la fin de la période en cours.

3.3. **Conditions de Résiliation :** En cas de résiliation anticipée de la Convention par le Mandant avant la fin de la durée initiale ou de l'un de ses renouvellements, le Mandant sera responsable du paiement des frais de gestion pour le reste de la période contractuelle en cours, sauf dans le cas où la Convention est résiliée au motif que toutes les unités de logement visées sont aliénées par le Mandant à un tiers de bonne foi ou à une société dont il ne détient pas le contrôle.

## 4. Responsabilités et devoirs du Mandataire

4.1. Le Mandataire s'engage, aux frais du Mandant, à prendre les mesures pour faire exécuter les services nécessaires et accessoires en vue d'assurer le fonctionnement et l'entretien de l'Immeuble ainsi que la bonne administration des affaires du Mandant.

4.2. Le Mandataire utilisera ses meilleurs efforts commerciaux à l'égard de ce qui suit :

- Négocier, signer, exécuter, prolonger, modifier, annuler ou résilier, au nom du Mandant, tous les baux et les contrats d'entretien et de maintenance ;
- Être le point de contact et de communication entre les locataires et le Mandant, pour identifier et gérer les besoins de chacun ;
- Donner tous les avis et relevés devant être fournis aux locataires en vertu des baux et tous les autres avis nécessaires pour préserver les droits et avantages du Mandant ;
- Percevoir, pour le compte et au nom du Mandant, les loyers et tous les montants exigibles des locataires (loyers additionnels, dépôts, frais indirects et autres) ;
- Préparer la publicité appropriée en vue de louer les logements, s'il y a lieu ;
- Vérifier le plumitif du Tribunal administratif du logement et le dossier de crédit des éventuels locataires ;
- Négocier et conclure tous les contrats de services et d'entreprise avec les entrepreneurs et sous-traitants ;
- Superviser les services d'entretien et de nettoyage, garder les aires communes propres et exemptes de neige et de glace, assurer l'entretien paysager et l'enlèvement des ordures ;
- Le cas échéant, superviser et gérer tous les travaux majeurs de réparation, de transformation et de rénovation de l'Immeuble, sous réserve des budgets approuvés par le Mandant ;
- Coordonner les refinancements hypothécaires, les renouvellements de prêts et les démarches auprès des institutions financières, et effectuer les mises à jour et renouvellements bancaires annuels ;
- Assurer la reddition de comptes ainsi que les communications et rapports périodiques auprès des actionnaires et partenaires passifs du Mandant ;
- Coordonner la tenue de livres et la préparation des états financiers annuels du Mandant, incluant la liaison avec la firme comptable externe mandatée à cette fin ;
- Gérer les comptes de services publics (Hydro-Québec, gaz, eau, etc.) et les assurances relatives à l'Immeuble ;
- Effectuer les mises à jour juridiques annuelles, incluant la production de la déclaration de mise à jour annuelle au Registraire des entreprises du Québec ;
- Gérer les relations avec les fournisseurs, assureurs, institutions financières et autres tiers, et assurer le suivi administratif courant des affaires du Mandant.

## 5. Frais et Honoraires du Mandataire

5.1. Pour et en considération de la gestion, de l'administration et de l'opération de l'Immeuble ainsi que des services complets rendus par le Mandataire, le Mandant convient de payer les frais et honoraires apparaissant à l'Offre de services ci-jointe (Annexe « A »), plus les taxes applicables.

5.2. Le Mandataire facturera ses frais et honoraires au Mandant chaque mois, entre le 1er et le 10e jour du mois suivant celui durant lequel les services facturés ont été rendus.

5.3. Les factures du Mandataire sont payables sur réception et portent intérêt au taux de 24 % l'an à compter du 15e jour suivant la date de facturation. Le Mandant autorise expressément le Mandataire à opérer compensation entre les sommes qu'il lui doit et les sommes qui lui sont dues, et ainsi à payer ses factures mensuelles à même les sommes que le Mandataire détient pour lui (par exemple : les loyers perçus).

5.4. Le Mandant convient de payer une pénalité équivalente à 25 % de toutes sommes dues au Mandataire advenant le cas où ce dernier doit retenir les services d'un avocat afin de recouvrer les sommes dues par le Mandant.

5.5. Dans l'éventualité où, à la suite de la signature d'un bail, un locataire se désiste, le Mandant s'engage à payer au Mandataire les honoraires de location prévus à l'Annexe « A ». Les honoraires de location sont toujours dus à la suite de la signature d'un bail à un nouveau locataire.

## 6. Perception des loyers

6.1. Dans l'éventualité où le Mandant perçoit les loyers ou une partie des loyers directement de ses locataires, il doit aviser sans délai le Mandataire de tout retard de paiement.

6.2. Dans l'éventualité où le Mandataire perçoit les loyers, il devra transférer au Mandant les loyers perçus, déduction faite des frais de gestion et des honoraires du Mandataire, au plus tard le 10e jour du mois ou, si les loyers sont perçus après cette date, dans un délai raisonnable après leur perception.

## 7. Les méthodes de gestion

7.1. Le Mandant consent à fournir et mettre à la disposition du Mandataire toute information liée à l'Immeuble et à ses affaires et l'autorise à y avoir pleinement accès pour accomplir ses obligations.

7.2. Le Mandant consent à s'abstenir de donner des instructions directement aux employés, entrepreneurs, sous-traitants ou fournisseurs impliqués dans l'exploitation et l'administration de l'Immeuble. De telles instructions seront transmises par écrit au Mandataire, qui s'engage à les acheminer à la personne idoine.

7.3. Le Mandant autorise le Mandataire à apposer un autocollant portant son nom et son numéro de téléphone sur les portes ou fenêtres extérieures de l'Immeuble.

## 8. Responsabilité du Mandant

8.1. Il est expressément convenu que le Mandataire ne procédera à aucune pratique discriminatoire dans la sélection des locataires.

8.2. Le Mandataire n'est pas responsable du choix du locataire au-delà des vérifications convenues (plumitif au Tribunal administratif du logement et dossier de crédit). Le Mandant assume l'entière responsabilité des dommages pouvant découler du choix des locataires et dégage le Mandataire de toute responsabilité à cet égard.

8.3. Le Mandant s'engage à prendre fait et cause pour le Mandataire et à le tenir indemne de toutes réclamations, dommages, frais et honoraires découlant directement ou indirectement des services du Mandataire et de l'exécution de la Convention.

8.4. Le Mandant s'engage à honorer les engagements contractés de bonne foi par le Mandataire, en son nom, relativement à la réalisation de la Convention.

8.5. Le Mandant s'engage à ne pas vendre ni autrement aliéner un actif ou un loyer résultant de l'exploitation de l'Immeuble sans en aviser préalablement le Mandataire par écrit. S'il aliène une ou plusieurs unités à un tiers de bonne foi ou à une personne morale dont il ne détient pas le contrôle, il pourra mettre fin à la Convention en payant au Mandataire l'équivalent de trois mois de frais de gestion pour les unités aliénées.

## 9. Délégation générale de pouvoir

Le Mandant autorise expressément le Mandataire et ses représentants autorisés, pendant la durée de la Convention, à agir pour et en son nom et à signer tout document, dans le meilleur intérêt du Mandant, dans le cadre de la réalisation de la Convention, y compris, sans limitation, à le représenter auprès du Tribunal administratif du logement, des institutions financières (démarches de financement et de refinancement), du Registraire des entreprises du Québec et des fournisseurs de services publics.

## 10. Absence de responsabilité

10.1. Nonobstant les dispositions de la Convention, le Mandataire ne sera en aucun cas tenu responsable envers le Mandant d'un retard dans la perception des loyers ou autres montants dus par les locataires ou tiers, ni des dommages ou pertes affectant l'Immeuble, les équipements ou autres actifs.

10.2. Le Mandataire ne sera pas non plus tenu responsable d'un retard dans l'accomplissement de ses obligations si un tel retard résulte d'une force majeure, d'un cas fortuit, d'un accident, d'une grève, d'un lock-out, de lois ou règlements restrictifs, ou de toute autre condition indépendante de sa volonté ou d'un acte imputable au Mandant.

## 11. Solidarité

Si le terme « Mandant » désigne plus d'une personne, chacune d'elles est solidairement responsable de l'exécution des obligations contenues dans le présent mandat, dans tout document qui y est relié et dans toute convention de modification.

## 12. Élection de domicile

Les parties conviennent, pour toute réclamation et/ou poursuite judiciaire relativement au présent mandat, de choisir le district judiciaire de {{DISTRICT}}, province de Québec, Canada, comme lieu approprié pour l'audition de ces réclamations ou poursuites, à l'exclusion de tout autre district judiciaire.

## 13. Défaut et résiliation

13.1. Dans l'éventualité où l'une des parties serait en défaut aux termes de la Convention, l'autre partie devra lui transmettre par écrit un avis détaillant tel défaut. Si, à l'expiration d'un délai de dix (10) jours, le défaut n'est pas remédié, la partie ayant donné l'avis pourra mettre fin à la Convention ou, s'il s'agit du Mandataire, suspendre l'exécution du mandat pendant trente (30) jours.

13.2. En cas de défaut du Mandant menant à la résiliation, le Mandant sera responsable du paiement au Mandataire des frais de gestion pour le reste de la période contractuelle en cours.

13.3. En cas de défaut du Mandataire menant à la résiliation, le Mandant sera responsable du paiement des frais de gestion jusqu'au dernier jour du mois précédant la date de résiliation.

## 14. Effets de la terminaison ou de la résiliation de la Convention

Le Mandataire remettra au Mandant tous les fichiers, registres et autres documents relatifs à l'Immeuble ou à ses affaires. Le Mandant s'engage à payer au Mandataire toutes les dépenses et frais liés à la gestion et à la reproduction de tels documents.

## 15. Avis

15.1. Tous les avis mentionnés dans la Convention doivent être écrits et transmis par envoi recommandé, messager, huissier ou courriel aux adresses mentionnées à la page frontispice ou aux adresses courriel suivantes : Au Mandataire : MGV Développement inc. — info@immohorizon.com; Au Mandant : {{COURRIEL}}.

15.2. L'une ou l'autre des parties peut notifier à l'autre un changement d'adresse selon l'une des méthodes énumérées à l'article 15.1.

## 16. Dispositions générales

16.1. Les expressions « aux présentes », « cette Convention », « mandat » et autres expressions similaires réfèrent à l'entièreté de la Convention.

16.2. Nul ne peut céder, en totalité ou en partie, ses droits ou obligations dans la Convention sauf de la manière qui y est prévue, sous peine de nullité.

16.3. Les délais stipulés sont de rigueur et de déchéance. Si un délai expire un samedi, un dimanche ou un jour férié, il sera prorogé au jour non férié suivant.

16.4. Chacun des articles doit être interprété séparément et l'invalidité de l'un n'a pas pour effet d'invalider la totalité de la Convention.

16.5. Sous réserve de l'article 3.2, la Convention ne peut être modifiée que par un écrit signé par toutes les parties. Le silence, la négligence ou le retard d'une partie à exercer un droit ne constitue pas une renonciation.

16.6. La Convention lie les parties ainsi que leurs successeurs et ayants droit respectifs.

16.7. Selon le contexte, le singulier comprend le pluriel et le masculin comprend le féminin, et vice versa.

16.8. Les titres et sous-titres n'y sont insérés que pour faciliter la lecture et ne servent pas à l'interpréter.

## 17. Acceptation des présentes

Le Mandant accepte les conditions énumérées ci-dessus, se déclare satisfait de celles-ci, reconnaît qu'elles ne lui ont pas été imposées, qu'il a pu les négocier et qu'il a eu l'opportunité d'obtenir un avis externe avant de signer le présent mandat.

EN FOI DE QUOI, les parties ont signé à l'endroit et à la date mentionnés à l'entête de la Convention.

## ANNEXE « A » — OFFRE DE SERVICES

**Frais d'ouverture de dossier**

50 $ par nouvelle unité de logement enregistrée avec MGV Développement inc. jusqu'à 50 unités; 25 $ par unité supplémentaire.

**Frais de gestion — 10 % (service complet « clé en main »)**

Un frais mensuel de 10 % de la valeur locative des baux et des logements vacants, excluant les rabais et gratuités accordés par le Mandant (minimum de 250 $/mois/immeuble), plus taxes applicables. Ce taux de 10 % reflète la prise en charge complète et intégrée des affaires du Mandant par le Mandataire, incluant :

- Instauration et application des règlements d'immeuble
- Collecte et dépôt des loyers, registre mensuel
- Obtention de la preuve d'assurance responsabilité des locataires et de la preuve d'inscription Hydro-Québec
- Suivi des loyers en délinquance et recouvrement
- Communications avec les locataires et suivi des plaintes
- Services d'urgence pour les appels téléphoniques
- Production et distribution des avis de renouvellement et d'augmentation de loyer, relevés 31 et autres lettres (excluant la grille d'évaluation du Tribunal administratif du logement)
- Gestion des demandes de services des locataires
- Gestion des soumissions de sous-traitance (entretien ménager des aires communes, tonte de pelouse et déneigement)
- Inspection des lieux avant le départ des locataires et évaluation des dommages
- Coordination des refinancements hypothécaires, renouvellements de prêts et démarches auprès des institutions financières
- Mises à jour et renouvellements bancaires annuels
- Reddition de comptes et communications/rapports périodiques aux actionnaires et partenaires passifs
- Coordination des états financiers annuels et liaison avec la firme comptable externe
- Gestion des comptes de services publics (Hydro-Québec, etc.) et des assurances de l'Immeuble
- Mises à jour juridiques annuelles (déclaration de mise à jour annuelle au Registraire des entreprises du Québec)
- Gestion des relations avec les fournisseurs, assureurs et institutions financières
- Tenue de livres

**Tenue de livres**

33 $ / heure — tenue de livres réalisée à l'interne par le Mandataire (catégorisation, rapprochements, tenue des registres comptables), plus taxes applicables.

**États financiers**

Les états financiers annuels sont sous-traités à une firme comptable externe. Les honoraires de cette firme sont facturés au Mandant, au coût, en sus des frais de gestion.

**Frais de location**

50 % d'un mois de loyer par unité de logement louée (minimum 600 $ pour un logement, 400 $ pour une chambre), plus les frais de déplacement au taux de 55 $ l'heure (facturés jusqu'à un maximum équivalent à un mois de loyer), incluant :

- Le premier déplacement est gratuit dans un rayon de moins de 30 km
- Publicité
- Gestion des visites et sélection des locataires
- Enquête de crédit complète (les frais du fournisseur d'enquête sont à la charge du Mandant, en sus)
- Préparation et signature du bail, des annexes et des règlements d'immeuble
- Prise de photos et constat des lieux, remise des clés

**Services à l'unité**

- Déplacement et représentation au Tribunal administratif du logement (l'immeuble doit être détenu par une société par actions) : 110 $/heure, minimum de 3 heures facturées
- Gestion et révision d'un dossier pour le Tribunal administratif du logement : 200 $ / dossier
- Gestion de sinistres et des sous-traitants (entretien ménager des aires communes, la tonte, le déneigement, comptable, etc.) : 10 % de la facture
- Négociation et rédaction, le cas échéant, de la résiliation de bail, indépendamment du résultat : 110 $/heure
- Déplacement d'urgence à l'immeuble : 65 $/heure, minimum de 3 heures facturées

**Services administratifs (autres que les services de base)**

Gestion de soumissions, rédaction de la grille d'augmentation des loyers du Tribunal administratif du logement et autres services administratifs non compris dans les services de base : 65 $/heure (minimum de 1 heure facturée).

**Services juridiques, bancaires et administratifs — débours de tiers**

Frais du Tribunal administratif du logement, huissier, frais postaux, bail électronique ou papier, frais de prélèvements automatiques et autres débours de tiers : aux frais du Mandant plus frais de gestion.

**Services d'entretien, réparation et déplacement**

- Travaux d'entretien courant : 55 $/heure (minimum de 1 heure facturée)
- Travaux majeurs : sur demande
- Travaux en urgence : 65 $/heure (minimum de 3 heures facturées)
- Matériaux : montant de la facture plus 10 %
- Déplacements : 55 $/heure (minimum de 1 heure facturée)

**Nos services sont déductibles d'impôt !**

Tous les montants ci-dessus s'entendent avant taxes applicables (TPS/TVQ).
"""


def render_contrat_markdown(
    template_md: str,
    *,
    compagnie: Optional[str] = None,
    siege_social: Optional[str] = None,
    representant: Optional[str] = None,
    titre: Optional[str] = None,
    immeubles: Optional[str] = None,
    district: Optional[str] = None,
    courriel: Optional[str] = None,
    lieu: Optional[str] = None,
    date: Optional[str] = None,
) -> str:
    """Substitue les marqueurs `{{PLACEHOLDER}}` du gabarit.

    Les valeurs manquantes deviennent un souligné « à compléter »
    (comme sur le contrat papier) plutôt que de laisser le marqueur
    brut visible.
    """

    def _v(value: Optional[str]) -> str:
        v = (value or "").strip()
        return v if v else "_______________________"

    mapping = {
        "COMPAGNIE": _v(compagnie),
        "SIEGE_SOCIAL": _v(siege_social),
        "REPRESENTANT": _v(representant),
        "TITRE": _v(titre),
        "IMMEUBLES": _v(immeubles),
        "DISTRICT": _v(district),
        "COURRIEL": _v(courriel),
        "LIEU": _v(lieu),
        "DATE": _v(date),
    }

    def _sub(match: "re.Match[str]") -> str:
        key = match.group(1).strip()
        return mapping.get(key, match.group(0))

    return re.sub(r"\{\{\s*([A-Z_]+)\s*\}\}", _sub, template_md)


def immeubles_to_markdown(adresses: Optional[str]) -> str:
    """Transforme un bloc « une adresse par ligne » en liste markdown."""
    if not adresses:
        return ""
    lines = [ln.strip() for ln in adresses.splitlines() if ln.strip()]
    if not lines:
        return ""
    return "\n".join(f"- {_html.unescape(ln)}" for ln in lines)
