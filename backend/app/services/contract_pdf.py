"""Génère le PDF d'un contrat d'entreprise à prix coûtant majoré
(version Horizon du contrat APCHQ).

Rendu lorsque la soumission est de type ``kind="contract"``. Réutilise
l'infrastructure ReportLab de ``soumission_pdf`` (styles, constantes,
helpers). Les champs structurés proviennent de ``contract_data`` (JSON)
et les clauses générales G1-G20 sont reproduites ci-dessous.
"""

from __future__ import annotations

import io
import json
import logging
import os
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.contact_request import ContactRequest
from app.models.soumission import Soumission
from app.models.user import User
from app.services.soumission_pdf import (
    ACCENT_HEX,
    COMPANY_EMAIL,
    COMPANY_INSURANCE,
    COMPANY_NAME,
    COMPANY_RBQ,
    DARK_HEX,
    LINE_HEX,
    MUTED_HEX,
    _LOGO_PATH,
    _date,
    _lazy_reportlab,
    _money,
    _styles,
)

log = logging.getLogger(__name__)

# Coordonnées Horizon complètes (alignées avec le formulaire de
# contrat côté frontend — components/contract-form.tsx).
COMPANY_ADDRESS = "158 rue Maurice, Saint-Rémi (Québec) J0L 2L0"
COMPANY_TEL = "514-654-4053"


# ─── Clauses générales G1-G20 (transcrites du contrat APCHQ) ──────
# Chaque entrée : (niveau, titre, corps). niveau 0 = G#, niveau 1 =
# G#.#, niveau 2 = G#.#.#. Corps vide = simple titre de section.
GENERAL_CONDITIONS: list[tuple[int, str, str]] = [
    (0, "G1. AVIS ET DÉFAUTS", ""),
    (
        1,
        "G1.1 Validité de l'avis",
        "Tout avis requis en vertu du présent contrat est suffisant s'il "
        "est consigné dans un écrit et expédié par un mode de "
        "communication qui permet à la partie expéditrice de prouver que "
        "l'avis fut effectivement livré à la partie destinataire, à "
        "l'adresse indiquée au début du contrat.",
    ),
    (
        1,
        "G1.2 Avis et droit à un délai raisonnable",
        "Lorsqu'une partie constate le défaut de l'autre partie de "
        "respecter l'une ou l'autre des obligations lui incombant en "
        "vertu du présent contrat ou de la loi, elle doit mettre la "
        "partie défaillante en demeure de remédier à son défaut par "
        "l'envoi d'un avis écrit à cet effet. Un tel avis devra énoncer "
        "la nature du ou des défauts reprochés et donner à la partie "
        "défaillante un délai de sept (7) jours pour y remédier, à "
        "compter de la réception dudit avis. Advenant le cas où il sera "
        "impossible pour la partie défaillante de s'amender dans le délai "
        "imparti à l'avis de défaut, celle-ci devra établir que les "
        "mesures appropriées pour remédier à son ou ses défauts seront "
        "entreprises dans un délai raisonnable.",
    ),
    (
        1,
        "G1.3 Défauts de l'entrepreneur",
        "L'entrepreneur sera réputé être en défaut advenant la survenance "
        "de l'un ou l'autre des cas suivants :",
    ),
    (
        2,
        "G1.3.1",
        "S'il n'exécute pas les travaux prévus conformément au contrat, à "
        "la loi ou aux règles de l'art.",
    ),
    (
        2,
        "G1.3.2",
        "S'il tarde de façon indue à fournir la main-d'œuvre, l'outillage "
        "et l'équipement requis à la bonne réalisation des travaux, dans "
        "les délais prévus conformément au contrat.",
    ),
    (
        2,
        "G1.3.3",
        "S'il compromet la sécurité du chantier et de son personnel.",
    ),
    (
        1,
        "G1.4 Défauts du client",
        "Le client sera réputé être en défaut advenant la survenance de "
        "l'un ou l'autre des cas suivants :",
    ),
    (
        2,
        "G1.4.1",
        "Si la réalisation des travaux est interrompue pour une période "
        "de trente (30) jours ou plus à la suite de la décision du client "
        "à cet égard ou encore à la suite d'une ordonnance ou d'une "
        "décision d'un tribunal, d'un organisme ou d'une corporation de "
        "droit public et que telle ordonnance ou décision ne résulte pas "
        "de la faute ou de la négligence de l'entrepreneur.",
    ),
    (
        2,
        "G1.4.2",
        "Advenant tout défaut du client relativement au contrat dont "
        "notamment, celui de payer à l'échéance tout montant dû à "
        "l'entrepreneur conformément aux modalités de paiement stipulées "
        "au contrat.",
    ),
    (0, "G2. RÉSILIATION ET SUSPENSION PAR L'ENTREPRENEUR", ""),
    (
        1,
        "G2.1 Résiliation ou suspension avec avis pour cause de défaut",
        "Dans l'éventualité où le client néglige de corriger son ou ses "
        "défauts dans le délai imparti à un avis de défaut transmis "
        "conformément à l'article G1.2, l'entrepreneur peut, à son choix, "
        "suspendre ses travaux jusqu'à ce que le client ait remédié audit "
        "défaut, ou mettre fin au contrat, en transmettant à l'autre "
        "partie un avis écrit à cet effet. Le contrat qui sera ainsi "
        "résilié sera réputé l'avoir été à la date indiquée à l'avis de "
        "résiliation.",
    ),
    (
        2,
        "G2.1.1 Exception en cas de défaut de paiement du client",
        "Dans l'éventualité où le client serait en défaut de paiement, "
        "l'entrepreneur pourra immédiatement, dès l'envoi d'un avis de "
        "défaut conformément à l'article G1.2, suspendre les travaux et "
        "ce, jusqu'à ce que le client ait remédié audit défaut.",
    ),
    (
        1,
        "G2.2 Force majeure ou imprévus",
        "L'entrepreneur pourra suspendre les travaux prévus au contrat ou "
        "en demander la résiliation, pour cause de découvertes imprévues "
        "ou autre cause de force majeure et ce, sans nécessité d'avis au "
        "préalable. Sont réputées être une cause de force majeure, toutes "
        "causes ne dépendant pas de la volonté des parties au contrat, "
        "qu'elles n'ont pu raisonnablement avoir prévues, et notamment, "
        "mais sans limiter la généralité de ce qui précède, la survenance "
        "de l'un ou l'autre des événements suivants : accident "
        "inévitable, guerre, révolution, inondation, feu, grève ou autre "
        "conflit de travail, défaut de tout fournisseur de matériaux ou "
        "de services, absence des services d'utilité publique, retard "
        "dans les inspections par une société prévue ou, encore, tout "
        "règlement ou législation ou ordonnance de tout palier "
        "gouvernemental.",
    ),
    (
        1,
        "G2.3 Non-responsabilité",
        "Aucune responsabilité ne pourra être imputée à l'entrepreneur "
        "qui suspend les travaux conformément au contrat. Le cas échéant, "
        "toutes pénalités, dépenses, frais ou dommages encourus par une "
        "telle suspension de travaux, incluant notamment tous les frais "
        "causés par le retard, ne pourront être imputés à l'entrepreneur.",
    ),
    (
        1,
        "G2.4 Droit au paiement",
        "Dans l'éventualité où l'entrepreneur résilie le présent contrat "
        "pour cause de défaut du client, il aura droit, en plus d'être "
        "payé pour la valeur des travaux exécutés en date de la "
        "résiliation, d'être indemnisé par le client de toutes les pertes "
        "subies en raison de la résiliation du contrat. En tous temps "
        "pertinents, l'entrepreneur pourra conserver les acomptes et les "
        "versements déjà perçus du client, en compensation du préjudice "
        "subi, sans préjudice à tous autres droits et recours, notamment "
        "afin de récupérer tous dommages additionnels.",
    ),
    (0, "G3. RÉSILIATION PAR LE CLIENT", ""),
    (
        1,
        "G3.1 Résiliation avec avis en cas de défaut",
        "Dans l'éventualité où l'entrepreneur néglige de corriger son ou "
        "ses défauts dans le délai imparti à un avis de défaut transmis "
        "conformément à l'article G1.2, le client peut, à son choix, "
        "suspendre les versements progressifs dus à l'entrepreneur aux "
        "termes des modalités de paiement convenues au contrat et ce, "
        "jusqu'à ce que l'entrepreneur ait remédié audit défaut, ou "
        "encore, mettre fin au contrat en transmettant à l'entrepreneur "
        "un avis écrit à cet effet.",
    ),
    (
        1,
        "G3.2 Résiliation unilatérale",
        "Le client peut, de façon unilatérale et sans aucun motif, "
        "résilier le présent contrat en transmettant un avis de "
        "résiliation à cet effet à l'entrepreneur. Lorsque le client "
        "exerce son droit à la résiliation unilatérale, il doit payer à "
        "l'entrepreneur les frais et dépenses actuels, la valeur des "
        "travaux exécutés et la valeur des biens fournis, le tout en date "
        "de la résiliation du contrat. De plus, le client devra également "
        "payer à l'entrepreneur une indemnité additionnelle équivalente à "
        "vingt-cinq pour cent (25 %) de la valeur des travaux qui restent "
        "à exécuter en date de la résiliation, en sus de tout autre "
        "préjudice que l'entrepreneur pourra subir, à titre de pénalité. "
        "Pour les fins des présentes, le contrat sera réputé résilié à la "
        "date indiquée à l'avis de résiliation.",
    ),
    (0, "G4. RÉSILIATION DE PLEIN DROIT PAR LES PARTIES", ""),
    (
        0,
        "",
        "Le contrat pourra être résilié de plein droit, par l'une ou "
        "l'autre des parties, sans nécessité d'avis ni mise en demeure "
        "préalable, dans l'un ou l'autre des cas suivants :",
    ),
    (
        1,
        "G4.1 Faillite et insolvabilité",
        "Si l'une ou l'autre des parties devient insolvable, est déclarée "
        "en faillite ou encore que des procédures en faillite sont "
        "entreprises contre elle ou qu'une cession générale de ses biens "
        "au profit de l'ensemble de ses créanciers est prononcée.",
    ),
    (
        1,
        "G4.2 Syndic",
        "Si un séquestre, un syndic ou toute autre personne ayant des "
        "pouvoirs similaires est nommé afin de prendre, en tout ou en "
        "partie, les affaires ou les actifs de l'une ou l'autre des "
        "parties.",
    ),
    (
        1,
        "G4.3 Dissolution et liquidation",
        "Le cas échéant, advenant la dissolution ou la liquidation, "
        "volontaire ou forcée, d'une partie.",
    ),
    (
        0,
        "G5. RETARD DANS L'EXÉCUTION DES TRAVAUX",
        "L'entrepreneur ne sera pas responsable du retard dans "
        "l'exécution des travaux, si ce retard provient du défaut du "
        "client de remplir ses obligations en vertu du contrat, des "
        "présentes clauses générales, ou d'une force majeure ou encore, "
        "de la survenance de toute autre cause indépendante de la volonté "
        "de l'entrepreneur, à savoir, mais sans limitation : tout "
        "accident inévitable, guerre, révolution, inondation, feu, grève "
        "ou autre conflit de travail, défaut de tout fournisseur de "
        "matériaux ou de services, impossibilité d'obtenir des matériaux "
        "à des conditions raisonnables suivant les dispositions de la "
        "clause « substitution de matériaux » prévues aux clauses "
        "générales, impossibilité d'obtenir les services à des "
        "conditions raisonnables, absence des services d'utilité "
        "publique, retard dans les inspections par une société prévue "
        "ou, encore, tout règlement ou législation ou ordonnance de tout "
        "palier gouvernemental.",
    ),
    (
        0,
        "G6. PERMIS",
        "Le client informe l'entrepreneur qu'il a vérifié et s'est assuré "
        "que l'immeuble est conforme aux règlements municipaux de zonage "
        "et qu'il a obtenu, au besoin et selon le cas, l'autorisation "
        "spéciale ou le permis de la municipalité ou de toute autorité "
        "compétente pour construire, démolir, modifier, réparer ou "
        "agrandir ledit immeuble. Sur demande spécifique du client à cet "
        "effet, l'entrepreneur obtiendra tous les permis, licences et "
        "certificats nécessaires et exigibles par l'autorité compétente "
        "pour exécuter les travaux prévus au présent contrat. À moins "
        "d'entente à l'effet contraire, les frais inhérents à l'obtention "
        "de tels permis, licences ou certificats seront supportés par le "
        "client.",
    ),
    (0, "G7. ASSURANCES", ""),
    (
        1,
        "G7.1 Assurance responsabilité",
        "Avant le début des travaux, l'entrepreneur devra démontrer au "
        "client qu'il est muni d'une assurance de responsabilité civile "
        "adéquate concernant les travaux qu'il exécutera sur l'immeuble "
        "et devra, sur demande écrite du client, lui fournir une copie de "
        "sa police d'assurance.",
    ),
    (
        1,
        "G7.2 Assurance incendie",
        "À la demande de l'entrepreneur, le client s'engage à faire "
        "ajouter le nom de l'entrepreneur à sa police d'assurance "
        "incendie, afin que les pertes, s'il y a lieu, soient payables "
        "selon leurs intérêts respectifs. En outre, et avant l'exécution "
        "des travaux, le client s'engage à dénoncer ceux-ci par écrit à "
        "son assureur.",
    ),
    (
        0,
        "G8. ENTRETIEN DES LIEUX",
        "L'entrepreneur devra garder les lieux raisonnablement propres et "
        "prévenir toute accumulation de matériaux inutilisables ou "
        "autres. Les matériaux et les débris de construction "
        "récupérables appartiendront à l'entrepreneur, qui pourra en "
        "disposer comme il le souhaite.",
    ),
    (
        0,
        "G9. SUBSTITUTION DE MATÉRIAUX",
        "Advenant le cas où certains matériaux devant être utilisés dans "
        "l'exécution des travaux ne seraient plus disponibles dans les "
        "délais requis, ou à des conditions satisfaisantes, "
        "l'entrepreneur pourra y substituer d'autres matériaux de nature "
        "et de qualité équivalentes, à la condition cependant d'en aviser "
        "le client au moins 48 heures à l'avance. Dans une telle "
        "éventualité, le client aura alors l'opportunité de s'objecter à "
        "cette substitution. Dans ce dernier cas cependant, le client "
        "accepte d'avance, d'une part, tout retard dans la livraison de "
        "l'immeuble sans droit ni recours contre l'entrepreneur et "
        "convient également, d'autre part, d'assumer tout accroissement "
        "des coûts des matériaux concernés par la non-substitution.",
    ),
    (
        0,
        "G10. FRAIS DE SERVICES PUBLICS SUPPLÉMENTAIRES",
        "Advenant que par voie de législation, de réglementation ou de "
        "décision administrative, une autorité gouvernementale, "
        "paragouvernementale ou administrative décrète ou impose à "
        "l'entrepreneur, au regard de l'immeuble visé par les travaux "
        "prévus au contrat, de nouvelles taxes, de nouveaux frais ou "
        "d'autres coûts analogues liés aux services publics ou "
        "d'infrastructures, le client convient de défrayer ces frais ou "
        "de rembourser à l'entrepreneur le montant assumé par celui-ci "
        "pour le paiement de ceux-ci.",
    ),
    (0, "G11. SOL ET CONTAMINANTS", ""),
    (
        1,
        "G11.1 Sol contaminé",
        "Le client se déclare et se reconnaît responsable de la présence, "
        "sur l'immeuble, de polluants ou de contaminants tels que définis "
        "par la Loi sur la qualité de l'environnement. En conséquence, le "
        "client assumera tous les frais supplémentaires reliés à "
        "l'obligation de décontaminer l'immeuble visé par les travaux.",
    ),
    (
        1,
        "G11.2 Qualité du sol",
        "Advenant que, en raison de la nature ou de la qualité du sol, "
        "des travaux supplémentaires, imprévisibles lors de la signature "
        "du contrat, s'avéraient nécessaires, le client assumera tous les "
        "frais supplémentaires reliés à de tels travaux, lesquels sont "
        "non inclus dans le prix du contrat.",
    ),
    (
        0,
        "G12. RÉCEPTION DES TRAVAUX",
        "Le client est tenu de recevoir l'ouvrage à la fin des travaux. "
        "Celle-ci a lieu lorsque l'ouvrage est exécuté et que l'immeuble "
        "est en état de servir, conformément à l'usage auquel il est "
        "destiné. La livraison de l'immeuble et la réception des travaux "
        "seront confirmées dans le document intitulé « Attestation de "
        "réception des travaux », lequel devra être signé par "
        "l'entrepreneur et le client et joint au présent contrat à titre "
        "d'annexe, pour en faire partie intégrante.",
    ),
    (
        0,
        "G13. RÉSERVES",
        "L'entrepreneur accepte de reprendre, de corriger ou de "
        "parachever les travaux pour lesquels une réserve écrite apparaît "
        "sur l'Attestation de réception des travaux, dans la mesure où il "
        "en fait l'objet d'une entente écrite entre les parties, qui sera "
        "consignée dans l'Entente sur le parachèvement et la correction "
        "de travaux et jointe au contrat à titre d'annexe pour en faire "
        "partie intégrante.",
    ),
    (
        0,
        "G14. SÛRETÉ SUFFISANTE",
        "Au regard de l'article 2111 du Code civil du Québec et à la "
        "condition que l'entrepreneur soit dûment accrédité auprès d'un "
        "plan de garantie, le client reconnaît et accepte que ce plan de "
        "garantie constitue une sûreté suffisante garantissant "
        "l'exécution des obligations de l'entrepreneur en ce qui "
        "concerne : toute réserve faite pour la réparation ou la "
        "correction des malfaçons apparentes lors de la réception de "
        "l'immeuble ; le parachèvement des travaux, saisonniers ou non, "
        "sur l'immeuble, lorsque ces travaux sont visés et couverts par "
        "ladite garantie. En conséquence, le client s'engage à ne retenir "
        "aucune somme d'argent sur le prix du contrat.",
    ),
    (
        0,
        "G15. GARANTIES",
        "Les travaux exécutés par l'entrepreneur dans le cadre du contrat "
        "sont garantis conformément aux dispositions du Code civil du "
        "Québec applicables. Par ailleurs, l'entrepreneur transmettra au "
        "client les garanties des fabricants ou des fournisseurs "
        "concernant les matériaux, les produits ou les systèmes qu'il "
        "fournira en vertu du contrat. L'entrepreneur ne garantit ni la "
        "main-d'œuvre, ni les matériaux fournis par le client ou les "
        "sous-traitants engagés directement par celui-ci.",
    ),
    (
        0,
        "G16. RÈGLEMENT DES DIFFÉRENDS",
        "En cas de différends ou litiges résultant de l'interprétation ou "
        "de l'application du contrat, l'entrepreneur et le client "
        "pourront, d'un commun accord, convenir de soumettre les "
        "questions litigieuses à un médiateur qu'ils auront choisi. Il "
        "est alors convenu que les frais liés à une telle médiation "
        "seront partagés en parts égales entre l'entrepreneur et le "
        "client.",
    ),
    (
        0,
        "G17. MODIFICATION DES COÛTS DE LA MAIN-D'ŒUVRE",
        "Dans l'éventualité où des modifications aux conditions de "
        "travail prévues à la convention collective applicable au secteur "
        "visé par les travaux auraient pour effet d'augmenter les coûts "
        "de construction de l'entrepreneur, lesquels n'ont pu être prévus "
        "en date de la signature du contrat, ce dernier aura le droit, en "
        "justifiant une telle augmentation auprès du client, de réviser à "
        "la hausse le prix prévu au contrat.",
    ),
    (
        0,
        "G18. DEMANDE DE MODIFICATION",
        "Le client pourra demander des substitutions de matériaux ou des "
        "modifications aux travaux prévus aux présentes, sous réserve que "
        "toutes ces modifications soient consignées dans le document "
        "intitulé « Modification au contrat », lequel devra être signé "
        "par l'entrepreneur et le client et être joint au présent contrat "
        "à titre d'annexe, pour en faire partie intégrante.",
    ),
    (
        0,
        "G19. VISITE DU CHANTIER",
        "Lorsque telle mesure s'y prête, après le début de la réalisation "
        "des travaux et en tout temps avant la réception des travaux, le "
        "client devra obtenir l'autorisation de l'entrepreneur pour "
        "pouvoir visiter le chantier. Il devra respecter les normes de "
        "sécurité, ainsi que les normes et règlements applicables sur les "
        "chantiers de construction. Cette autorisation ne sera accordée "
        "que pendant les heures de travail du chantier.",
    ),
    (
        0,
        "G20. PREUVE DE SOLVABILITÉ",
        "Suite à une demande écrite à cet effet de l'entrepreneur, faite "
        "avant ou pendant la réalisation des travaux, le client doit lui "
        "fournir, dans les meilleurs délais, une preuve de solvabilité "
        "suffisante démontrant qu'il possède les dispositions "
        "financières qui lui permettront de rencontrer à l'échéance les "
        "termes de paiement prévus au contrat.",
    ),
]


def _cd_get(cd: dict, *path: str, default: Any = "") -> Any:
    """Accès défensif imbriqué dans contract_data."""
    cur: Any = cd
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur if cur is not None else default


async def _load(db: AsyncSession, soumission_id: int):
    sm = (
        await db.execute(
            select(Soumission).where(Soumission.id == soumission_id)
        )
    ).scalar_one_or_none()
    if sm is None:
        return None, None, None, ""
    contact: Optional[ContactRequest] = None
    if sm.contact_request_id:
        contact = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == sm.contact_request_id
                )
            )
        ).scalar_one_or_none()
    client: Optional[Client] = None
    if sm.client_id:
        client = (
            await db.execute(
                select(Client).where(Client.id == sm.client_id)
            )
        ).scalar_one_or_none()
    # Responsable du projet (chargé de projet Horizon).
    responsable = ""
    try:
        cd = json.loads(sm.contract_data) if sm.contract_data else {}
    except (TypeError, ValueError):
        cd = {}
    rid = cd.get("responsable_user_id") if isinstance(cd, dict) else None
    if rid:
        u = (
            await db.execute(select(User).where(User.id == int(rid)))
        ).scalar_one_or_none()
        if u is not None:
            responsable = (
                getattr(u, "display_name", None)
                or " ".join(
                    p
                    for p in [
                        getattr(u, "first_name", None),
                        getattr(u, "last_name", None),
                    ]
                    if p
                )
                or u.email
            )
    return sm, contact, client, responsable


def _render_bytes(
    sm: Soumission,
    contact: Optional[ContactRequest],
    client: Optional[Client],
    responsable: str,
) -> bytes:
    rl = _lazy_reportlab()
    colors = rl["colors"]
    mm = rl["mm"]
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Image = rl["Image"]
    DARK = colors.HexColor(DARK_HEX)
    MUTED = colors.HexColor(MUTED_HEX)
    ACCENT = colors.HexColor(ACCENT_HEX)
    LINE = colors.HexColor(LINE_HEX)

    try:
        cd: dict = json.loads(sm.contract_data) if sm.contract_data else {}
    except (TypeError, ValueError):
        cd = {}
    if not isinstance(cd, dict):
        cd = {}

    s = _styles(rl)
    # Style serré pour les clauses générales (texte fin du contrat).
    ParagraphStyle = rl["ParagraphStyle"]
    fine = ParagraphStyle(
        "fine",
        parent=s["small"],
        fontSize=7.6,
        leading=9.6,
        textColor=DARK,
        spaceAfter=3,
    )
    fine_h = ParagraphStyle(
        "fine_h",
        parent=s["small"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=DARK,
        spaceBefore=4,
    )
    sec = ParagraphStyle(
        "sec",
        parent=s["accent"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.white,
        spaceBefore=2,
    )

    buf = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=rl["letter"],
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Contrat {sm.reference}",
        author=COMPANY_NAME,
    )
    story: list = []

    def section_bar(txt: str) -> None:
        bar = Table([[Paragraph(txt, sec)]], colWidths=[doc.width])
        bar.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), ACCENT),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(Spacer(1, 8))
        story.append(bar)
        story.append(Spacer(1, 6))

    def field(label: str, val: str) -> None:
        story.append(
            Paragraph(
                f"<b>{label} :</b> {val or '—'}", s["body"]
            )
        )

    # ── En-tête ──
    left_cell: list = []
    if os.path.exists(_LOGO_PATH):
        try:
            left_cell.append(
                Image(_LOGO_PATH, width=26 * mm, height=26 * mm)
            )
            left_cell.append(Spacer(1, 4))
        except Exception as exc:  # noqa: BLE001
            log.warning("Logo non intégré au PDF contrat : %s", exc)
    left_cell.extend(
        [
            Paragraph(f"<b>{COMPANY_NAME}</b>", s["h2"]),
            Paragraph(COMPANY_ADDRESS, s["small"]),
            Paragraph(f"Tél. {COMPANY_TEL}", s["small"]),
            Paragraph(COMPANY_EMAIL, s["small"]),
            Paragraph(COMPANY_RBQ, s["small"]),
            Paragraph(COMPANY_INSURANCE, s["small"]),
        ]
    )
    right_cell = [
        Paragraph("CONTRAT D'ENTREPRISE", s["h1"]),
        Paragraph("À PRIX COÛTANT MAJORÉ", s["accent"]),
        Paragraph(f"N<sup>o</sup> {sm.reference}", s["accent"]),
        Paragraph(f"Émis le {_date(sm.created_at)}", s["small"]),
    ]
    header = Table(
        [[left_cell, right_cell]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ]
        )
    )
    story.append(header)

    # ── 1. Identification des parties ──
    section_bar("1.  IDENTIFICATION DES PARTIES")
    ent_lines = [
        Paragraph("<b>ENTREPRENEUR</b>", s["accent"]),
        Paragraph(f"<b>{COMPANY_NAME}</b>", s["body"]),
        Paragraph(COMPANY_ADDRESS, s["body"]),
        Paragraph(f"Tél. {COMPANY_TEL}", s["body"]),
        Paragraph(COMPANY_EMAIL, s["body"]),
        Paragraph(COMPANY_RBQ, s["small"]),
        Paragraph(COMPANY_INSURANCE, s["small"]),
        Paragraph(
            f"<b>Responsable du projet :</b> {responsable or '—'}",
            s["body"],
        ),
    ]
    cli_name = ""
    cli_email = ""
    cli_addr = ""
    if client is not None:
        cli_name = client.name or ""
        cli_email = client.email or ""
        cli_addr = client.address or ""
    elif contact is not None:
        cli_name = contact.name or ""
        cli_email = contact.email or ""
        cli_addr = contact.address or ""
    cli_lines = [
        Paragraph("<b>CLIENT</b>", s["accent"]),
        Paragraph(f"<b>{cli_name or 'Client à confirmer'}</b>", s["body"]),
    ]
    if cli_email:
        cli_lines.append(Paragraph(cli_email, s["body"]))
    if cli_addr:
        cli_lines.append(Paragraph(cli_addr, s["body"]))
    parties = Table(
        [[ent_lines, cli_lines]],
        colWidths=[doc.width * 0.5, doc.width * 0.5],
    )
    parties.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (1, 0), (1, 0), 12),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("LINEAFTER", (0, 0), (0, 0), 0.5, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (0, 0), 8),
            ]
        )
    )
    story.append(parties)

    # ── 2. Immeuble visé par les travaux ──
    section_bar("2.  IMMEUBLE VISÉ PAR LES TRAVAUX")
    field("Adresse du chantier", _cd_get(cd, "immeuble_address"))

    # ── 3. Objet du contrat ──
    section_bar("3.  OBJET DU CONTRAT")
    tt = _cd_get(cd, "type_travaux", default={})
    tt_sel = [
        lbl
        for key, lbl in (
            ("residentiel", "Résidentiel"),
            ("commercial", "Commercial"),
            ("condominium", "Condominium"),
        )
        if isinstance(tt, dict) and tt.get(key)
    ]
    if isinstance(tt, dict) and tt.get("autres"):
        tt_sel.append(
            f"Autres : {tt.get('autres_texte') or '—'}"
        )
    field("3.1  Type de travaux", ", ".join(tt_sel) or "—")
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>3.2  Description des travaux inclus</b>", s["body"]))
    story.append(
        Paragraph(
            (_cd_get(cd, "description") or "—").replace("\n", "<br/>"),
            s["body"],
        )
    )
    story.append(Spacer(1, 4))
    pr = _cd_get(cd, "prestation", default={})
    pr_sel = [
        lbl
        for key, lbl in (
            ("main_oeuvre", "La main-d'œuvre"),
            ("materiaux", "Les matériaux"),
            ("outillage", "L'outillage"),
            ("equipement", "L'équipement"),
        )
        if isinstance(pr, dict) and pr.get(key)
    ]
    if isinstance(pr, dict) and pr.get("autres"):
        pr_sel.append(f"Autres : {pr.get('autres_texte') or '—'}")
    field("3.3  Prestation de l'entrepreneur", ", ".join(pr_sel) or "—")
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "<b>3.4  Services</b> — qui fournit / paie le branchement",
            s["body"],
        )
    )
    svc = _cd_get(cd, "services", default={})
    svc_rows = [["Service", "Client", "Entrepreneur"]]

    def _mark(v: Any, party: str) -> str:
        return "X" if v == party else ""

    if isinstance(svc, dict):
        for key, lbl in (
            ("eau", "Eau"),
            ("electricite", "Électricité"),
            ("toilettes", "Toilettes"),
        ):
            v = svc.get(key)
            svc_rows.append(
                [lbl, _mark(v, "client"), _mark(v, "entrepreneur")]
            )
        for lk, vk in (
            ("autre1_label", "autre1"),
            ("autre2_label", "autre2"),
        ):
            lbl = svc.get(lk)
            if lbl:
                v = svc.get(vk)
                svc_rows.append(
                    [lbl, _mark(v, "client"), _mark(v, "entrepreneur")]
                )
    svc_tbl = Table(
        svc_rows,
        colWidths=[doc.width * 0.6, doc.width * 0.2, doc.width * 0.2],
    )
    svc_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.25, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(svc_tbl)
    story.append(Spacer(1, 4))
    story.append(
        Paragraph("<b>3.5  Exclusions au contrat</b>", s["body"])
    )
    story.append(
        Paragraph(
            (_cd_get(cd, "exclusions") or "—").replace("\n", "<br/>"),
            s["body"],
        )
    )

    # ── 4. Début et fin des travaux ──
    section_bar("4.  DÉBUT ET FIN DES TRAVAUX")
    field("Date de début", _cd_get(cd, "date_debut"))
    field("Date de fin", _cd_get(cd, "date_fin"))

    # ── 5. Prix du contrat ──
    section_bar("5.  PRIX DU CONTRAT")
    story.append(Paragraph("<b>5.1  Prix coûtant majoré</b>", s["body"]))
    if _cd_get(cd, "prix_kind") == "remuneration_fixe":
        story.append(
            Paragraph(
                "Le prix coûtant de l'ouvrage, majoré d'une rémunération "
                f"fixe de <b>{_cd_get(cd, 'prix_remuneration_fixe') or '—'} $</b>, "
                "plus les taxes applicables.",
                s["body"],
            )
        )
    else:
        story.append(
            Paragraph(
                "Le prix coûtant de l'ouvrage, majoré d'un pourcentage de "
                f"<b>{_cd_get(cd, 'prix_pourcentage') or '—'} %</b>, plus "
                "les taxes applicables.",
                s["body"],
            )
        )
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "<b>5.2  Coûts inclus dans le prix coûtant de l'ouvrage</b>",
            s["body"],
        )
    )
    cout = _cd_get(cd, "cout", default={})
    cout_labels = [
        ("salaires_mo", "Salaires et avantages — main-d'œuvre de chantier"),
        ("salaires_bureau", "Salaires et avantages — employés de bureau"),
        ("contributions", "Contributions, impôts et taxes"),
        ("subsistance", "Frais de subsistance et de déplacement"),
        ("materiaux", "Matériaux, fournitures, services et installations"),
        ("machinerie", "Machinerie, équipement et outillage"),
        ("sous_traitants", "Contrats et ententes — sous-traitants et fournisseurs"),
        ("inspections", "Inspections, expertises ou essais"),
        ("dechets", "Enlèvement des déchets et des débris"),
        ("communications", "Interurbains, communications, messagerie, photocopies"),
        ("financement", "Financement de la réalisation des travaux"),
    ]
    cout_sel = []
    if isinstance(cout, dict):
        for key, lbl in cout_labels:
            if cout.get(key):
                extra = ""
                if key == "salaires_mo" and cout.get("salaires_mo_taux"):
                    extra = f" ({cout.get('salaires_mo_taux')})"
                cout_sel.append(f"{lbl}{extra}")
        for k in ("autres1", "autres2", "autres3"):
            if cout.get(k):
                cout_sel.append(str(cout.get(k)))
    if cout_sel:
        for c in cout_sel:
            story.append(Paragraph(f"&bull; {c}", s["body"]))
    else:
        story.append(Paragraph("—", s["body"]))

    # ── 6. Modalités de paiement ──
    section_bar("6.  MODALITÉS DE PAIEMENT")
    acompte = _cd_get(cd, "acompte")
    field(
        "6.1  Acompte à la signature",
        f"{acompte} $" if acompte else "—",
    )
    vk = _cd_get(cd, "versements_kind", default="hebdomadaire")
    vk_label = {
        "hebdomadaire": "Hebdomadaire (vendredis)",
        "bimensuel": "Bi-mensuel (1er et 15 de chaque mois)",
        "mensuel": "Mensuel (1er de chaque mois)",
        "autres": f"Autres : {_cd_get(cd, 'versements_autres') or '—'}",
    }.get(vk, vk)
    field("6.2  Versements progressifs sur facturation", vk_label)
    im = _cd_get(cd, "interet_mois", default="2")
    ia = _cd_get(cd, "interet_annee", default="24")
    field(
        "6.4  Intérêts sur les arrérages",
        f"{im} % par mois, capitalisé mensuellement, soit {ia} % par année.",
    )

    # ── 7-12. Clauses du contrat ──
    section_bar("7.  CLAUSES GÉNÉRALES, ANNEXES ET FORMULAIRES")
    story.append(
        Paragraph(
            "Le client déclare qu'il a lu, qu'il comprend et qu'il accepte "
            "toutes et chacune des clauses apparaissant aux présentes, "
            "incluant les clauses générales, les annexes et les "
            "formulaires s'y rapportant, lesquels font partie intégrante "
            "du présent contrat. S'il y a contradiction ou conflit entre "
            "les clauses générales, un document annexé et le présent "
            "contrat, les parties conviennent que les dispositions des "
            "annexes ou du présent contrat auront préséance sur les "
            "clauses générales.",
            s["small"],
        )
    )
    section_bar("8.  AUTRE ENTENTE NULLE")
    story.append(
        Paragraph(
            "Le présent contrat annule toute autre entente écrite ou "
            "verbale antérieure.",
            s["small"],
        )
    )
    section_bar("9.  ENTRÉE EN VIGUEUR")
    story.append(
        Paragraph(
            "Le contrat entre en vigueur à la date de sa signature.",
            s["small"],
        )
    )
    section_bar("10.  RENSEIGNEMENTS PERSONNELS")
    story.append(
        Paragraph(
            "En vertu de la Loi sur la protection des renseignements "
            "personnels dans le secteur privé, le client consent "
            "librement à ce que l'entrepreneur recueille auprès de tiers "
            "ou communique à des tiers intéressés tout renseignement "
            "personnel pouvant être requis pour les fins du contrat.",
            s["small"],
        )
    )
    section_bar("11.  ÉLECTION DE DOMICILE")
    story.append(
        Paragraph(
            "Les parties conviennent, pour toute réclamation ou poursuite "
            "judiciaire pour quelque motif que ce soit relativement au "
            "contrat, de choisir le district judiciaire de "
            f"<b>{_cd_get(cd, 'election_domicile', default='Montréal')}</b>, "
            "province de Québec, Canada, comme lieu approprié pour "
            "l'audition de ces réclamations ou poursuites judiciaires.",
            s["small"],
        )
    )
    section_bar("12.  SOLIDARITÉ ET SIGNATURES")
    story.append(
        Paragraph(
            "Dans la mesure où plus d'une personne signe le présent "
            "contrat à titre de client, chacune se porte solidairement "
            "responsable l'une de l'autre de toutes les obligations "
            "incombant au client en vertu du présent contrat, des clauses "
            "générales, des annexes et des formulaires, et toutes se "
            "désignent mandataires les unes des autres.",
            s["small"],
        )
    )
    story.append(Spacer(1, 10))

    # ── Bloc signatures ──
    def _sig_cell(title: str, name: str, when: Any, img: Optional[bytes]):
        cell: list = [Paragraph(f"<b>{title}</b>", s["accent"])]
        if img:
            try:
                cell.append(
                    Image(io.BytesIO(img), width=46 * mm, height=18 * mm)
                )
            except Exception:  # noqa: BLE001
                pass
        else:
            cell.append(Spacer(1, 18))
        cell.append(
            Paragraph(
                "_______________________________", s["small"]
            )
        )
        cell.append(Paragraph(name or "Nom : ____________________", s["body"]))
        cell.append(
            Paragraph(
                f"Date : {_date(when) if when else '____________________'}",
                s["small"],
            )
        )
        return cell

    contractor_img = None
    client_img = None
    try:
        contractor_img = sm.contractor_signature_image
    except Exception:  # noqa: BLE001
        contractor_img = None
    try:
        client_img = sm.signature_image
    except Exception:  # noqa: BLE001
        client_img = None

    sig = Table(
        [
            [
                _sig_cell(
                    "ENTREPRENEUR — Horizon Services Immobiliers",
                    sm.contractor_signed_name or "",
                    sm.contractor_signed_at,
                    contractor_img,
                ),
                _sig_cell(
                    "CLIENT",
                    sm.signed_name or "",
                    sm.accepted_at,
                    client_img,
                ),
            ]
        ],
        colWidths=[doc.width * 0.5, doc.width * 0.5],
    )
    sig.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (1, 0), (1, 0), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(sig)

    # ── Clauses générales (page séparée) ──
    PageBreak = __import__(
        "reportlab.platypus", fromlist=["PageBreak"]
    ).PageBreak
    story.append(PageBreak())
    section_bar("CLAUSES GÉNÉRALES")
    for level, title, body in GENERAL_CONDITIONS:
        if title:
            story.append(Paragraph(title, fine_h))
        if body:
            indent = "&nbsp;" * (4 * level)
            story.append(Paragraph(f"{indent}{body}", fine))

    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            f"{COMPANY_NAME} &middot; {COMPANY_RBQ} &middot; "
            f"{COMPANY_INSURANCE} &middot; {COMPANY_EMAIL}",
            s["small"],
        )
    )

    doc.build(story)
    return buf.getvalue()


async def render_contract_pdf(
    db: AsyncSession, soumission_id: int
) -> Optional[tuple[Soumission, bytes]]:
    """Rend le PDF d'un contrat d'entreprise. Renvoie (soumission,
    bytes) ou None si la soumission n'existe pas."""
    sm, contact, client, responsable = await _load(db, soumission_id)
    if sm is None:
        return None
    pdf = _render_bytes(sm, contact, client, responsable)
    return sm, pdf
