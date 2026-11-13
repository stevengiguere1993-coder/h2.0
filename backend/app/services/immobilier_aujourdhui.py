"""Page « Aujourd'hui » d'Immobilier — une seule liste de choses à faire.

Refonte d'Immobilier, lot 1 (Steven, 2026-11-13 : « mettre tout ce qui
est recommandé pour toutes les étapes »). Règle R5 de la refonte : une
alerte se lit à UN endroit. Cette page réunit ce que la vue d'ensemble
montrait en quatre compteurs (loyers en retard, avis de renouvellement,
maintenance urgente, dépôts à rendre) ET ce qui n'apparaissait que sur
d'autres pages (baux signés à importer, logements à louer, preuves
d'assurance et consentements à relancer).

Ce module ne fait QUE composer les lignes à partir de chiffres déjà
calculés par les vues existantes (aucune règle métier ici) : le compte
affiché est donc toujours celui de la page où la ligne mène.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: Délais avant de proposer une relance.
JOURS_RELANCE_ASSURANCE = 14
JOURS_RELANCE_CONSENTEMENT = 7


@dataclass
class Ligne:
    cle: str
    nb: int
    titre: str
    detail: Optional[str]
    #: "urgent" (rouge), "attention" (ambre), "info" (neutre).
    ton: str
    #: Page où la ligne mène, déjà filtrée quand la page le permet.
    href: str
    bouton: str = "Voir"


@dataclass
class Chiffres:
    """Ce que les vues existantes ont compté."""

    loyers_nb: int = 0
    loyers_total: float = 0.0
    avis_en_retard: int = 0
    avis_a_envoyer: int = 0
    #: « Félix Gauthier, log. 7 » quand il n'y en a qu'un.
    avis_qui: Optional[str] = None
    baux_a_importer: int = 0
    baux_a_importer_immeubles: int = 0
    baux_a_importer_qui: Optional[str] = None
    a_louer: int = 0
    #: Jours écoulés depuis le départ le plus ancien (None = personne
    #: n'est encore parti).
    a_louer_jours_max: Optional[int] = None
    bons_ouverts: int = 0
    bons_urgents: int = 0
    depots_nb: int = 0
    depots_total: float = 0.0
    assurances_a_relancer: int = 0
    consentements_a_relancer: int = 0
    #: Sources qui n'ont pas pu être lues (clé de ligne).
    indisponibles: list[str] = field(default_factory=list)


def montant(n: float) -> str:
    """« 4 500 $ » : sans cents quand le montant est rond, espace
    insécable entre les milliers (format fr-CA)."""
    arrondi = round(float(n), 2)
    entier = int(arrondi)
    cents = int(round((arrondi - entier) * 100))
    milliers = f"{entier:,}".replace(",", " ")
    if cents:
        return f"{milliers},{cents:02d} $"
    return f"{milliers} $"


def _pl(n: int, singulier: str, pluriel: str) -> str:
    return f"{n} {singulier if n == 1 else pluriel}"


#: Libellé court de chaque ligne quand il n'y a rien à faire.
RIEN = {
    "loyers": "loyers en retard",
    "renouvellements": "avis de renouvellement",
    "baux_a_importer": "baux signés à importer",
    "a_louer": "logements à louer",
    "bons_travail": "bons de travail",
    "depots": "dépôts à rendre",
}

#: Libellé d'une source qui n'a pas pu être lue.
LIBELLES = {
    **RIEN,
    "assurances": "preuves d'assurance",
    "consentements": "consentements",
}


def nb_urgent(c: Chiffres) -> int:
    """Ce qui presse (pastille rouge du menu) : loyers à encaisser, avis
    de renouvellement en retard, bons de travail urgents."""
    return c.loyers_nb + c.avis_en_retard + c.bons_urgents


def composer(c: Chiffres) -> tuple[list[Ligne], list[str]]:
    """Les lignes à faire (dans l'ordre d'affichage) et la liste « rien à
    signaler ». Une source illisible ne produit ni l'un ni l'autre."""
    lignes: list[Ligne] = []
    rien: list[str] = []

    def _rien(cle: str) -> None:
        if cle not in c.indisponibles:
            rien.append(RIEN[cle])

    if c.loyers_nb > 0:
        lignes.append(
            Ligne(
                cle="loyers",
                nb=c.loyers_nb,
                titre=_pl(c.loyers_nb, "loyer à encaisser", "loyers à encaisser"),
                detail=(
                    f"{montant(c.loyers_total)} en retard"
                    if c.loyers_total > 0.005
                    else None
                ),
                ton="urgent",
                href="/immobilier/paiements?etat=retard",
            )
        )
    else:
        _rien("loyers")

    nb_avis = c.avis_en_retard + c.avis_a_envoyer
    if nb_avis > 0:
        if c.avis_en_retard > 0:
            titre = _pl(
                c.avis_en_retard,
                "avis de renouvellement en retard",
                "avis de renouvellement en retard",
            )
            detail = c.avis_qui if nb_avis == 1 else None
            if c.avis_a_envoyer > 0:
                detail = _pl(c.avis_a_envoyer, "autre à envoyer", "autres à envoyer")
        else:
            titre = _pl(
                c.avis_a_envoyer,
                "avis de renouvellement à envoyer",
                "avis de renouvellement à envoyer",
            )
            detail = c.avis_qui if nb_avis == 1 else None
        lignes.append(
            Ligne(
                cle="renouvellements",
                nb=nb_avis,
                titre=titre,
                detail=detail,
                ton="urgent" if c.avis_en_retard > 0 else "attention",
                href="/immobilier/renouvellements",
                bouton="Préparer",
            )
        )
    else:
        _rien("renouvellements")

    if c.baux_a_importer > 0:
        if c.baux_a_importer == 1 and c.baux_a_importer_qui:
            detail: Optional[str] = c.baux_a_importer_qui
        elif c.baux_a_importer_immeubles > 1:
            detail = f"dans {c.baux_a_importer_immeubles} immeubles"
        else:
            detail = "dans un immeuble" if c.baux_a_importer_immeubles == 1 else None
        lignes.append(
            Ligne(
                cle="baux_a_importer",
                nb=c.baux_a_importer,
                titre=_pl(
                    c.baux_a_importer,
                    "bail signé à importer",
                    "baux signés à importer",
                ),
                detail=detail,
                ton="attention",
                href="/immobilier/baux",
            )
        )
    else:
        _rien("baux_a_importer")

    if c.a_louer > 0:
        if c.a_louer_jours_max is None:
            detail = "départs à venir"
        elif c.a_louer == 1:
            detail = f"libre depuis {_pl(c.a_louer_jours_max, 'jour', 'jours')}"
        else:
            detail = (
                "le plus ancien libre depuis "
                f"{_pl(c.a_louer_jours_max, 'jour', 'jours')}"
            )
        lignes.append(
            Ligne(
                cle="a_louer",
                nb=c.a_louer,
                titre=_pl(c.a_louer, "logement à louer", "logements à louer"),
                detail=detail,
                ton="attention",
                href="/immobilier/locations",
            )
        )
    else:
        _rien("a_louer")

    if c.bons_ouverts > 0:
        lignes.append(
            Ligne(
                cle="bons_travail",
                nb=c.bons_ouverts,
                titre=_pl(
                    c.bons_ouverts,
                    "bon de travail ouvert",
                    "bons de travail ouverts",
                ),
                detail=(
                    f"dont {_pl(c.bons_urgents, 'urgent', 'urgents')}"
                    if c.bons_urgents > 0
                    else "aucun urgent"
                ),
                ton="urgent" if c.bons_urgents > 0 else "info",
                href="/immobilier/bons-travail",
            )
        )
    else:
        _rien("bons_travail")

    if c.depots_nb > 0:
        lignes.append(
            Ligne(
                cle="depots",
                nb=c.depots_nb,
                titre=_pl(c.depots_nb, "dépôt à rendre", "dépôts à rendre"),
                detail=montant(c.depots_total) if c.depots_total > 0.005 else None,
                ton="attention",
                href="/immobilier/depots",
            )
        )
    else:
        _rien("depots")

    # Assurances et consentements : seulement quand il y en a à relancer
    # (jamais dans « rien à signaler », pour ne pas allonger la liste).
    if c.assurances_a_relancer > 0:
        lignes.append(
            Ligne(
                cle="assurances",
                nb=c.assurances_a_relancer,
                titre=_pl(
                    c.assurances_a_relancer,
                    "preuve d'assurance à relancer",
                    "preuves d'assurance à relancer",
                ),
                detail=(
                    f"demandée depuis plus de {JOURS_RELANCE_ASSURANCE} jours"
                    if c.assurances_a_relancer == 1
                    else f"demandées depuis plus de {JOURS_RELANCE_ASSURANCE} jours"
                ),
                ton="info",
                href="/immobilier/renouvellements?onglet=assurances",
            )
        )
    if c.consentements_a_relancer > 0:
        lignes.append(
            Ligne(
                cle="consentements",
                nb=c.consentements_a_relancer,
                titre=_pl(
                    c.consentements_a_relancer,
                    "consentement à relancer",
                    "consentements à relancer",
                ),
                detail=(
                    f"envoyé depuis plus de {JOURS_RELANCE_CONSENTEMENT} jours"
                    if c.consentements_a_relancer == 1
                    else f"envoyés depuis plus de {JOURS_RELANCE_CONSENTEMENT} jours"
                ),
                ton="info",
                href="/immobilier/renouvellements?onglet=consentements",
            )
        )
    return lignes, rien
