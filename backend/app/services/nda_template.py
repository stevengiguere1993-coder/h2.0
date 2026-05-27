"""Constantes & template pour le flow NDA investisseurs.

Contenu calqué sur le modèle "NDA - MGV Développement - Modèle
générique v2" (11 articles + préambule + bloc signatures). On
garde tout en dur ici : émetteur, durée, juridiction, plancher de
dommages, et boilerplate légal complet. Pas de configuration
exposée — si Phil veut ajuster, on d��placera dans Settings.

Variables substituables :
    - investor_name           (Récepteur)
    - investor_type_clause    (« particulier » | « société par actions… »)
    - investor_address_clause (« résidant au ��� » | « ayant son siège au … »)
    - investor_representative_clause (vide si particulier)
    - property_address        (optionnel — encart « Opportunité visée »)
    - emission_date           (« Date d'effet ��)
    - signed_name             (bloc signature Récepteur)
    - signed_at               (date de signature Récepteur)
"""

from __future__ import annotations

from typing import Optional


# Émetteur du NDA — MGV Développement (Phil & co).
ISSUER_ENTITY_NAME = "MGV DÉVELOPPEMENT INC."
ISSUER_ENTITY_ADDRESS = (
    "216 rue Louis-Lalande, Boucherville (Québec) J4B 2C1"
)
ISSUER_REPRESENTATIVE_NAME = "Philippe Meuser"
ISSUER_REPRESENTATIVE_TITLE = "Président"
ISSUER_EMAIL = "philippe.meuser@immohorizon.com"
ISSUER_PHONE = "438-998-9660"
ISSUER_INCORPORATION_LAW = (
    "Loi sur les sociétés par actions du Québec (RLRQ, c. S-31.1)"
)

# Durée standard de l'engagement de confidentialité, en années.
# Le NDA v2 utilise 24 mois pour la Durée et 24 mois additionnels
# pour la non-sollicitation / non-contournement.
NDA_DURATION_YEARS = 2

# Juridiction affichée dans la carte publique de signature (court).
NDA_JURISDICTION = "Québec"

# Venue exclusive pour les recours judiciaires — § 11.1 du PDF.
NDA_VENUE = "district judiciaire de Longueuil, province de Québec"

# Plancher de dommages-intérêts forfaitaires (§ 9.2 b) en CAD.
NDA_DAMAGES_FLOOR_CAD = 200_000

# Mention sur la valeur juridique de la signature électronique
# (RLRQ c. C-1.1). Conservée pour la page publique de signature.
LEGAL_NOTICE = (
    "La signature électronique a la même valeur juridique qu'une "
    "signature manuscrite en vertu de la Loi concernant le cadre "
    "juridique des technologies de l'information (RLRQ c. C-1.1). "
    "Le destinataire reconna��t avoir lu, compris et accepté les "
    "termes de la présente entente en apposant son nom dans le "
    "formulaire de signature ��lectronique."
)


# Engagements numérotés de l'article 3 du NDA v2 — version courte
# pour l'affichage public de la carte (frontend Next.js). Le PDF
# utilise sa propre numérotation complète (3.1 … 3.6).
ENGAGEMENT_ITEMS: tuple[str, ...] = (
    "Utiliser les Informations Confidentielles exclusivement dans "
    "le cadre de l'évaluation de l'Opportunité, et à aucune autre "
    "fin ;",
    "Préserver la nature confidentielle des Informations "
    "Confidentielles avec au moins le même degré de soin qu'aux "
    "informations propres au Récepteur, et jamais sous le standard "
    "raisonnable ;",
    "Ne pas divulguer les Informations Confidentielles à des tiers "
    "autres que ses Représentants strictement requis et liés par "
    "des obligations de confidentialité au moins aussi strictes ;",
    "Ne pas copier, reproduire, télécharger, photographier ou "
    "conserver les Informations Confidentielles au-delà de ce qui "
    "est strictement nécessaire à l'évaluation ;",
    "Retourner ou détruire immédiatement, sur demande ou à la "
    "terminaison, toutes les Informations Confidentielles (et "
    "celles détenues par ses Représentants), et confirmer cette "
    "destruction par écrit ;",
    "Être pleinement responsable des actes et omissions de ses "
    "Représentants et prendre toutes les mesures nécessaires pour "
    "les empêcher de violer le présent Accord.",
)


# ------------------------------------------------------------------
# Placeholders pour les clauses « particulier vs société »
# ------------------------------------------------------------------
# Quand on ne dispose pas (encore) de l'information précise dans le
# modèle NDA, on injecte des placeholders crochetés que Phil peut
# remplir manuellement avant signature OU qui restent en clair dans
# le PDF pour que l'investisseur les compl��te à la main.
_INVESTOR_TYPE_PLACEHOLDER = (
    "[particulier OU société par actions légalement constituée en "
    "vertu de [loi applicable]]"
)
_INVESTOR_ADDRESS_PLACEHOLDER = (
    "[résidant OU ayant son siège] au _____________________"
)
_INVESTOR_REPRESENTATIVE_PLACEHOLDER = (
    "[représenté aux fins des présentes par "
    "_____________________, dûment autorisé tel qu'il le déclare "
    "en signant]"
)


def resolve_investor_clauses(
    investor_type_clause: Optional[str] = None,
    investor_address_clause: Optional[str] = None,
    investor_representative_clause: Optional[str] = None,
) -> tuple[str, str, str]:
    """Applique les fallback pour les clauses du Récepteur.

    Si la clause n'est pas fournie, on retombe sur le placeholder
    crocheté correspondant. Une chaîne vide signifie « omis
    volontairement » (utile pour `representative_clause` quand le
    Récepteur est un particulier).
    """

    def _resolve(value: Optional[str], placeholder: str) -> str:
        if value is None:
            return placeholder
        return value.strip()

    return (
        _resolve(investor_type_clause, _INVESTOR_TYPE_PLACEHOLDER),
        _resolve(investor_address_clause, _INVESTOR_ADDRESS_PLACEHOLDER),
        _resolve(
            investor_representative_clause,
            _INVESTOR_REPRESENTATIVE_PLACEHOLDER,
        ),
    )


def render_nda_text(
    investor_name: str,
    emission_date: str,
    property_address: Optional[str] = None,
    signed_name: Optional[str] = None,
    signed_at: Optional[str] = None,
    investor_type_clause: Optional[str] = None,
    investor_address_clause: Optional[str] = None,
    investor_representative_clause: Optional[str] = None,
) -> str:
    """Rend le texte complet de l'entente sous forme de chaîne
    plain-text (utile pour debug / preview rapide hors PDF).

    Les sections sont séparées par des doubles sauts de ligne. Le
    PDF (`nda_pdf.py`) reconstruit son propre rendu typographique —
    cette fonction sert surtout de référence canonique du contenu
    juridique et d'aperçu textuel utilisable dans les tests.
    """
    name = (investor_name or "").strip() or "____________"
    date = (emission_date or "").strip() or "____________"
    sname = (signed_name or "").strip() or "____________"
    sdate = (signed_at or "").strip() or "____________"

    type_cl, addr_cl, repr_cl = resolve_investor_clauses(
        investor_type_clause,
        investor_address_clause,
        investor_representative_clause,
    )

    receiver_block = f"ET {name}, {type_cl}, {addr_cl}"
    if repr_cl:
        receiver_block += f", {repr_cl}"
    receiver_block += " (ci-après le « Récepteur »);"

    opportunity_block = ""
    if property_address and property_address.strip():
        opportunity_block = (
            "OPPORTUNITÉ VISÉE\n"
            f"À titre informatif, l'Opportunité initialement visée "
            f"par les Parties concerne l'immeuble situé au "
            f"{property_address.strip()}. Les présentes obligations "
            f"s'appliquent néanmoins à toute Opportunité partagée "
            f"par MGV au Récepteur.\n\n"
        )

    damages_amount = f"{NDA_DAMAGES_FLOOR_CAD:,}".replace(",", " ")

    return (
        "ENTENTE DE CONFIDENTIALITÉ ET DE NON-CONTOURNEMENT\n\n"
        f"CET ACCORD est conclu en date du {date} (la « Date "
        f"d'effet »), entre :\n\n"
        f"{ISSUER_ENTITY_NAME}, société par actions légalement "
        f"constituée en vertu de la {ISSUER_INCORPORATION_LAW}, "
        f"ayant son siège au {ISSUER_ENTITY_ADDRESS}, représentée "
        f"aux fins des présentes par {ISSUER_REPRESENTATIVE_NAME}, "
        f"{ISSUER_REPRESENTATIVE_TITLE}, dûment autorisé tel qu'il "
        f"le déclare en signant (ci-après la « Société » ou "
        f"« MGV »);\n\n"
        f"{receiver_block}\n\n"
        "Collectivement désignés les �� Parties ».\n\n"
        f"{opportunity_block}"
        "PRÉAMBULE\n"
        "ATTENDU QUE la Société est active dans l'investissement "
        "immobilier au Québec, incluant l'identification, l'analyse, "
        "l'acquisition, le développement et la gestion d'immeubles, "
        "ainsi que dans la cr��ation et la mise en œuvre de "
        "stratégies value-add;\n\n"
        "ATTENDU QUE la Société souhaite partager au Récepteur "
        "certaines Informations Confidentielles relatives à une ou "
        "plusieurs opportunités d'investissement immobilier (chacune, "
        "l'« Opportunité ») afin que le Récepteur puisse évaluer une "
        "participation potentielle, sous toute forme;\n\n"
        "ATTENDU QUE le Récepteur est susceptible, dans le cadre de "
        "sa propre activité, de partager certaines informations "
        "confidentielles à la Société;\n\n"
        "ATTENDU QUE les Parties souhaitent encadrer les conditions "
        "sous lesquelles ces informations seront divulguées, "
        "utilisées et protégées;\n\n"
        "EN CONTREPARTIE des engagements mutuels contenus aux "
        "présentes, les Parties conviennent de ce qui suit :\n\n"
        "1. OBJET\n"
        "L'objet du présent Accord est de permettre aux Parties de "
        "divulguer, échanger et discuter des Informations "
        "Confidentielles relatives à une ou plusieurs Opportunit��s "
        "d'investissement immobilier au Québec, afin que le "
        "Récepteur puisse évaluer une éventuelle participation, "
        "sous toute forme.\n\n"
        "2. DÉFINITION DES INFORMATIONS CONFIDENTIELLES\n"
        "Voir le PDF officiel pour la définition complète, les "
        "exclusions (2.2) et la définition de « Représentant » "
        "(2.3).\n\n"
        "3. ENGAGEMENTS DE LA PARTIE RÉCEPTRICE\n"
        + "\n".join(
            f"3.{i + 1} {item}" for i, item in enumerate(ENGAGEMENT_ITEMS)
        )
        + "\n\n"
        "4. NON-CONTOURNEMENT ET NON-SOLLICITATION\n"
        f"Engagement vingt-quatre (24) mois post-terminaison de ne "
        f"pas contourner la Sociét�� auprès du vendeur, des "
        f"courtiers, intermédiaires, partenaires, prêteurs ou "
        f"conseillers; ni présenter l'Opportunité à un tiers; ni "
        f"solliciter les locataires ou intervenants. Voir PDF "
        f"officiel pour le détail.\n\n"
        "5. AUCUNE DÉCLARATION NI GARANTIE\n"
        "Les Informations Confidentielles sont fournies « telles "
        "quelles » ��� aucune garantie d'exactitude.\n\n"
        "6. PROPRIÉTÉ DES INFORMATIONS\n"
        "Tous les droits demeurent la propriété exclusive de la "
        "Partie Divulgatrice.\n\n"
        "7. AUCUNE OBLIGATION DE TRANSACTION\n"
        "Le présent Accord ne crée aucune obligation de transaction.\n\n"
        "8. DURÉE ET RÉSILIATION\n"
        f"Durée de {_years_in_words(NDA_DURATION_YEARS)} "
        f"({NDA_DURATION_YEARS}) ans. Les obligations survivent à "
        f"la terminaison.\n\n"
        "9. RECOURS ET DOMMAGES\n"
        f"Dommages-intérêts forfaitaires d'un montant minimum de "
        f"{damages_amount} $ CAD par violation, sans préjudice des "
        f"autres recours (injonction, dommages additionnels, frais "
        f"juridiques).\n\n"
        "10. DIVULGATION OBLIGATOIRE\n"
        "Si tenu de divulguer par la loi, aviser immédiatement la "
        "Partie Divulgatrice avant divulgation.\n\n"
        "11. DISPOSITIONS GÉNÉRALES\n"
        f"Régi par les lois du Québec. Juridiction exclusive : "
        f"{NDA_VENUE}. Modifications par écrit, signature "
        f"électronique reconnue (RLRQ c. C-1.1), accord int��gral, "
        f"rédigé en français.\n\n"
        "EN FOI DE QUOI, les Parties ont signé à la Date d'effet.\n\n"
        f"{ISSUER_ENTITY_NAME}\n"
        f"Par : {ISSUER_REPRESENTATIVE_NAME}\n"
        f"Titre : {ISSUER_REPRESENTATIVE_TITLE}\n"
        f"Date : {date}\n"
        f"Adresse : {ISSUER_ENTITY_ADDRESS}\n"
        f"Courriel : {ISSUER_EMAIL}\n"
        f"Téléphone : {ISSUER_PHONE}\n\n"
        "LE RÉCEPTEUR\n"
        f"Nom : {sname}\n"
        f"Date : {sdate}"
    )


def _years_in_words(n: int) -> str:
    """Retourne le nombre d'années en lettres pour le boilerplate.

    Couvre les valeurs probables (1 à 5). Au-delà, on retombe sur
    une représentation chiffrée — la fonction ne sert qu'au confort
    visuel de la phrase « pour une période de deux (2) ans ».
    """
    mapping = {
        1: "un",
        2: "deux",
        3: "trois",
        4: "quatre",
        5: "cinq",
    }
    return mapping.get(n, str(n))


def render_nda_markdown(
    investor_name: str,
    emission_date: str,
    property_address: Optional[str] = None,
    signed_name: Optional[str] = None,
    signed_at: Optional[str] = None,
    investor_type_clause: Optional[str] = None,
    investor_address_clause: Optional[str] = None,
    investor_representative_clause: Optional[str] = None,
) -> str:
    """Rend le texte complet de l'entente sous forme de Markdown.

    Destiné à l'affichage sur la page publique de signature : le
    frontend utilise `marked` pour convertir en HTML. Contient tous
    les articles (1-11 + sous-articles a, b, c…) avec mise en forme
    minimale (titres `##`, gras `**`, listes `-`).

    Le PDF (`nda_pdf.py`) reste la version juridique de référence ;
    cette fonction est strictement isomorphe au contenu du PDF.
    """
    name = (investor_name or "").strip() or "____________"
    date = (emission_date or "").strip() or "____________"
    sname = (signed_name or "").strip() or "____________"
    sdate = (signed_at or "").strip() or "____________"

    type_cl, addr_cl, repr_cl = resolve_investor_clauses(
        investor_type_clause,
        investor_address_clause,
        investor_representative_clause,
    )

    receiver_block = f"**ET {name}**, {type_cl}, {addr_cl}"
    if repr_cl:
        receiver_block += f", {repr_cl}"
    receiver_block += " (ci-après le « **Récepteur** »);"

    opportunity_block = ""
    if property_address and property_address.strip():
        opportunity_block = (
            f"\n> **Opportunité visée :** à titre informatif, "
            f"l'Opportunité initialement considérée par les Parties "
            f"concerne l'immeuble situé au "
            f"**{property_address.strip()}**. Les obligations du "
            f"présent Accord s'appliquent néanmoins à toute "
            f"Opportunité partagée par MGV au Récepteur.\n"
        )

    damages_amount = f"{NDA_DAMAGES_FLOOR_CAD:,}".replace(",", " ")
    duree_lettres = "vingt-quatre" if NDA_DURATION_YEARS == 2 else str(
        NDA_DURATION_YEARS * 12
    )
    duree_mois = NDA_DURATION_YEARS * 12

    engagements_md = "\n".join(
        f"**3.{i + 1}** {item}" for i, item in enumerate(ENGAGEMENT_ITEMS)
    )

    return f"""# ENTENTE DE CONFIDENTIALITÉ ET DE NON-CONTOURNEMENT

CET ACCORD est conclu en date du **{date}** (la « **Date d'effet** »), entre :

**{ISSUER_ENTITY_NAME}**, société par actions légalement constituée en vertu de la {ISSUER_INCORPORATION_LAW}, ayant son siège au {ISSUER_ENTITY_ADDRESS}, représentée aux fins des présentes par {ISSUER_REPRESENTATIVE_NAME}, {ISSUER_REPRESENTATIVE_TITLE}, dûment autorisé tel qu'il le déclare en signant (ci-après la « Société » ou « **MGV** »);

{receiver_block}

Collectivement désignés les « **Parties** ».
{opportunity_block}
## PRÉAMBULE

ATTENDU QUE la Société est active dans l'investissement immobilier au Québec, incluant l'identification, l'analyse, l'acquisition, le développement et la gestion d'immeubles, ainsi que dans la création et la mise en œuvre de stratégies value-add;

ATTENDU QUE la Société souhaite partager au Récepteur certaines Informations Confidentielles (telles que définies ci-après) relatives à une ou plusieurs opportunités d'investissement immobilier (chacune, l'« **Opportunité** » et collectivement les « **Opportunités** ») afin que le Récepteur puisse évaluer une participation potentielle, sous toute forme (investisseur passif, partenaire actif, co-acquéreur, courtier, intermédiaire, conseiller professionnel, ou autre rôle);

ATTENDU QUE le Récepteur est susceptible, dans le cadre de sa propre activité, de partager certaines informations confidentielles à la Société;

ATTENDU QUE les Parties souhaitent encadrer les conditions sous lesquelles ces informations seront divulguées, utilisées et protégées;

**EN CONTREPARTIE** des engagements mutuels contenus aux présentes, les Parties conviennent de ce qui suit :

## 1. OBJET

L'objet du présent Accord est de permettre aux Parties de divulguer, échanger et discuter des Informations Confidentielles relatives à une ou plusieurs Opportunités d'investissement immobilier au Québec, afin que le Récepteur puisse évaluer une éventuelle participation, sous toute forme.

## 2. DÉFINITION DES INFORMATIONS CONFIDENTIELLES

**2.1** Le terme « **Informations Confidentielles** » désigne toute information, de quelque nature et sous quelque forme que ce soit (écrite, orale, électronique, visuelle, ou autre), divulguée par une Partie (la « **Partie Divulgatrice** ») à l'autre Partie (la « **Partie Réceptrice** ») dans le cadre du présent Accord, incluant notamment et sans s'y limiter :

- (a) L'adresse, l'identité, la description physique et juridique, et la localisation de tout immeuble visé par une Opportunité;
- (b) Le prix d'achat, les conditions financières, la structure de financement et la structure de la transaction;
- (c) Le registre des locataires (rent-roll), les baux, les loyers, les conditions de location, et toute information relative aux locataires;
- (d) Les états financiers, les revenus, les dépenses, les projections financières, le NOI, les taux de capitalisation, les ratios financiers, et toute analyse financière relative à l'Opportunité;
- (e) Les stratégies value-add, les plans de rénovation, les plans de développement, les budgets de travaux, et les échéanciers associés;
- (f) L'identité et les coordonnées du vendeur, des courtiers, des intermédiaires, des partenaires, des prêteurs, des conseillers professionnels et de tout tiers impliqué dans l'Opportunité;
- (g) Le fait même que la Société évalue, négocie, considère ou s'intéresse à une Opportunité particulière;
- (h) Toute présentation, deck d'investisseur, mémo, plan d'affaires, analyse, ou tout autre document préparé ou transmis par la Société;
- (i) Tous les termes, conditions et négociations relatifs à l'Opportunité, ainsi que leur progression;
- (j) Toute autre information, donnée ou document divulgué dans le cadre de l'Opportunité, qu'il soit explicitement identifié comme confidentiel ou non.

**2.2** Sont exclus de la définition d'Informations Confidentielles :

- (a) Les informations qui étaient déjà généralement connues du public ou accessibles à celui-ci au moment de la divulgation;
- (b) Les informations devenues publiques après la divulgation, sans qu'il y ait eu bris du présent Accord par la Partie Réceptrice ou ses Représentants;
- (c) Les informations reçues légitimement d'un tiers sans obligation de confidentialité et sans bris d'une obligation de confidentialité;
- (d) Les informations dont la divulgation est expressément autorisée par écrit par la Partie Divulgatrice;
- (e) Les informations développées indépendamment par la Partie Réceptrice sans utilisation des Informations Confidentielles.

**2.3** Le terme « **Représentant** » désigne, à l'égard d'une Partie, ses administrateurs, dirigeants, employés, mandataires, courtiers, partenaires d'affaires, conseillers juridiques, conseillers financiers, comptables, banquiers et autres conseillers professionnels.

## 3. ENGAGEMENTS DE LA PARTIE RÉCEPTRICE

La Partie Réceptrice s'engage à :

{engagements_md}

## 4. NON-CONTOURNEMENT ET NON-SOLLICITATION

**4.1 Non-contournement.** La Partie Réceptrice s'engage, pendant la durée du présent Accord et pour une période additionnelle de **vingt-quatre (24) mois** suivant sa terminaison, à ne pas, directement ou indirectement (incluant par l'entremise d'un tiers, d'une société affiliée, d'un mandataire, ou de toute autre personne agissant pour son compte) :

- (a) Approcher, contacter, négocier ou conclure une transaction avec le vendeur, le propriétaire ou les actionnaires d'un immeuble visé par une Opportunité, sans la participation et l'autorisation écrite préalable de la Société;
- (b) Approcher, contacter ou solliciter tout courtier, intermédiaire, partenaire, prêteur ou conseiller dont l'identité a été divulguée dans le cadre d'une Opportunité, dans le but de poursuivre, faciliter ou conclure une transaction concurrente ou parallèle à l'Opportunité;
- (c) Présenter, divulguer, partager ou offrir l'Opportunité (en tout ou en partie) à un tiers (incluant tout investisseur, acheteur, partenaire ou société) sans l'autorisation écrite préalable de la Société;
- (d) Soumettre une offre d'achat, signer une promesse d'achat ou conclure toute entente relative à un immeuble visé par une Opportunité, pour son propre compte ou pour le compte d'un tiers, sans la participation de la Société.

**4.2 Non-sollicitation.** La Partie Réceptrice s'engage, pendant la durée du présent Accord et pour une période additionnelle de vingt-quatre (24) mois suivant sa terminaison, à ne pas solliciter les locataires d'un immeuble visé par une Opportunité, ni les autres partenaires, investisseurs ou intervenants impliqués dans une Opportunité.

## 5. AUCUNE DÉCLARATION NI GARANTIE

La Partie Réceptrice reconnaît que la Partie Divulgatrice (ni ses Représentants) ne fait aucune déclaration ni ne donne aucune garantie, expresse ou implicite, quant à l'exactitude, l'exhaustivité ou la fiabilité des Informations Confidentielles. La Partie Divulgatrice n'est pas responsable des décisions prises par la Partie Réceptrice sur la base des Informations Confidentielles.

## 6. PROPRIÉTÉ DES INFORMATIONS

Tous les droits, titres et intérêts relatifs aux Informations Confidentielles, ainsi qu'à tous les supports les contenant, demeurent la propriété exclusive de la Partie Divulgatrice. Le présent Accord ne concède aucun droit de licence, de propriété intellectuelle ou de quelque autre nature à la Partie Réceptrice.

## 7. AUCUNE OBLIGATION DE TRANSACTION

Le présent Accord ne crée aucune obligation pour la Société de conclure une transaction avec la Partie Réceptrice, ni pour la Partie Réceptrice d'investir dans ou de participer à l'Opportunité.

## 8. DURÉE ET RÉSILIATION

**8.1** Le présent Accord entre en vigueur à la Date d'effet et demeure en vigueur pour une période de **{duree_lettres} ({duree_mois}) mois** (la « **Durée** »), sauf renouvellement écrit par les Parties.

**8.2** Nonobstant la Durée, les obligations de confidentialité, de non-contournement, de non-sollicitation, ainsi que les obligations de retour ou destruction des Informations Confidentielles, survivent à la terminaison de l'Accord pour la période prévue à chaque article (ou à défaut, pour vingt-quatre (24) mois suivant la terminaison).

## 9. RECOURS ET DOMMAGES

**9.1** La Partie Réceptrice reconnaît expressément que toute violation du présent Accord, et en particulier des articles 3 (Engagements), 4 (Non-contournement et non-sollicitation), et 6 (Propriété), causerait à la Société un préjudice grave, imprévisible et potentiellement irréparable, ne pouvant être adéquatement compensé par des dommages-intérêts seuls.

**9.2** En cas de violation du présent Accord par la Partie Réceptrice ou ses Représentants, la Société pourra obtenir, sans préjudice de ses autres recours et de manière cumulative :

- (a) Une injonction (provisoire, interlocutoire ou permanente), une ordonnance d'exécution en nature ou toute autre mesure équivalente, sans avoir à fournir de cautionnement, afin de faire cesser immédiatement la violation;
- (b) **Des dommages-intérêts forfaitaires d'un montant minimum de DEUX CENT MILLE DOLLARS ({damages_amount} $ CAD) par violation**, payables immédiatement à la Société sur preuve de la violation, à titre de plancher pour le préjudice subi par la Société (les Parties reconnaissent que ce montant constitue une estimation raisonnable et anticipée du préjudice minimum subi);
- (c) Des dommages-intérêts additionnels correspondant au préjudice réel subi par la Société au-delà du forfait prévu en (b), incluant notamment toute perte de profit, perte d'opportunité, perte de commission ou frais de gestion que la Société aurait perçus si la transaction avait été conclue avec sa participation;
- (d) Le remboursement intégral de tous les frais et honoraires (juridiques, judiciaires, extrajudiciaires, expertises, et autres) engagés par la Société pour faire valoir ses droits aux termes du présent Accord.

**9.3** La Partie Réceptrice indemnisera la Société et la mettra à couvert, à compter de la Date d'effet, de toutes réclamations, demandes, actions, causes d'action, dommages-intérêts directs ou indirects, pertes, frais, responsabilités ou dépenses que la Société peut engager ou subir, ou qui peuvent être intentés contre elle, si la Partie Réceptrice ou ses Représentants violent une modalité ou condition du présent Accord.

## 10. DIVULGATION OBLIGATOIRE

Si la Partie Réceptrice est légalement tenue (par loi, ordonnance judiciaire, ou autorité réglementaire) de divulguer des Informations Confidentielles, elle devra :

- (a) Aviser immédiatement et par écrit la Partie Divulgatrice avant toute divulgation, dans la mesure permise par la loi;
- (b) Coopérer avec la Partie Divulgatrice pour permettre à celle-ci de demander une ordonnance de protection ou tout autre recours approprié;
- (c) Ne divulguer que la portion strictement requise par la loi.

## 11. DISPOSITIONS GÉNÉRALES

**11.1 Lois applicables et juridiction.** Le présent Accord est régi et interprété selon les lois en vigueur dans la province de Québec et les lois du Canada qui y sont applicables. Les Parties se soumettent à la juridiction exclusive des tribunaux compétents du **{NDA_VENUE}**, pour toute procédure judiciaire ou quasi judiciaire relative au présent Accord.

**11.2 Avis.** Tout avis aux termes du présent Accord sera transmis par écrit aux coordonnées indiquées sur la première page du présent Accord, ou par courriel à l'adresse fournie par la Partie destinataire. Tout avis sera réputé reçu à la date de la confirmation de livraison ou de lecture.

**11.3 Modification.** Aucune modification du présent Accord ne sera valable à moins qu'elle ne soit constatée par un écrit signé par les deux Parties.

**11.4 Renonciation.** Le fait pour une Partie de ne pas exercer un droit, pouvoir ou privilège aux termes du présent Accord ne constitue pas une renonciation à ce droit, et l'exercice ponctuel ou partiel d'un tel droit ne constitue pas une renonciation à un exercice ultérieur.

**11.5 Cession.** Aucune Partie ne peut céder ses droits ou obligations aux termes du présent Accord sans le consentement écrit préalable de l'autre Partie.

**11.6 Intégralité de l'accord.** Le présent Accord constitue l'intégralité de l'entente entre les Parties à l'égard de son objet, et remplace toute communication, négociation, déclaration, promesse ou entente antérieure, verbale ou écrite.

**11.7 Successeurs.** Le présent Accord lie les Parties ainsi que leurs successeurs, ayants droit, héritiers et représentants légaux respectifs.

**11.8 Exemplaires et signature électronique.** Le présent Accord peut être signé en plusieurs exemplaires, chacun constituant un original mais formant tous ensemble un seul et même document. Le présent Accord peut être signé électroniquement (via Authentisign, Docusign, Adobe Sign ou tout autre service de signature électronique reconnu), et toute signature électronique aura la même valeur qu'une signature manuscrite conformément à la Loi concernant le cadre juridique des technologies de l'information (RLRQ, c. C-1.1).

**11.9 Divisibilité.** Si une disposition du présent Accord est jugée invalide, nulle ou inexécutoire, les autres dispositions demeurent en vigueur et pleinement exécutoires.

**11.10 Langue.** Les Parties confirment avoir expressément demandé que le présent Accord soit rédigé en langue française.

**11.11 Préambule et titres.** Le préambule fait partie intégrante du présent Accord. Les titres utilisés dans le présent Accord ne servent qu'à des fins de référence et n'ont aucune valeur interprétative.

---

**EN FOI DE QUOI**, les Parties, par l'entremise de leurs représentants dûment autorisés, ont signé le présent Accord à la Date d'effet.

**{ISSUER_ENTITY_NAME}**
Par : {ISSUER_REPRESENTATIVE_NAME}
Titre : {ISSUER_REPRESENTATIVE_TITLE}
Date : {date}
Adresse : {ISSUER_ENTITY_ADDRESS}
Courriel : {ISSUER_EMAIL}
Téléphone : {ISSUER_PHONE}

**LE RÉCEPTEUR**
Nom : {sname}
Date : {sdate}
"""


def format_property_address(
    address: Optional[str],
    city: Optional[str] = None,
    postal_code: Optional[str] = None,
) -> str:
    """Helper de concaténation : adresse, ville, code postal."""
    parts = [p for p in (address, city, postal_code) if p]
    return ", ".join(parts) if parts else "____________"
