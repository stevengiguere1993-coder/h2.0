"""Type des lignes de facture importées et règle « hors soumission de base ».

Retour Steven 2026-10-14 : « lorsque je crée une facture dans construction
et que j'importe de la main d'oeuvre et du matériel, il s'agit de services
et de matériaux, non pas d'extra ». Les trois imports (création depuis le
projet, « Ajouter des sources », import d'un bon de travail) posaient
kind="extra" en dur sur les heures et les achats.

Ce type « extra » servait surtout à NE PAS compter ces lignes dans
l'avancement de la soumission (cible cumulative, État du contrat, reste à
facturer, profit d'un forfaitaire). Les lignes importées prennent donc leur
vrai type — Service pour la main-d'œuvre et les sous-traitants, Matériaux
pour le matériel et les outils — et le caractère « hors soumission » devient
une marque séparée (FactureItem.hors_soumission), posée seulement quand le
projet de la facture a une soumission : sans soumission, il n'y a pas de
devis dont elles pourraient sortir.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import or_, select

from app.models.facture_item import FactureItem

log = logging.getLogger(__name__)

KIND_SERVICE = "service"
KIND_MATERIAUX = "materiaux"
KIND_EXTRA = "extra"

#: Marqueur one-shot (table applied_backfills) du reclassement des
#: brouillons existants.
CLE_RECLASSEMENT_BROUILLONS = "facture_lignes_importees_nature_v1"

#: Libellé client de la ligne unique qui additionne le matériel refacturé.
#: Steven 2026-10-17 : « les achats de matériels sur les factures
#: apparaissent comme facture -146. Tous les matériaux ajoutés devraient
#: s'additionner et apparaître sur une seule ligne. » Le détail des achats
#: regroupés reste consultable dans l'éditeur (FactureItemRead.achats).
LIBELLE_MATERIAUX = "Matériaux"

#: Marqueur one-shot du regroupement des lignes de matériel des brouillons.
CLE_REGROUPEMENT_MATERIAUX = "facture_lignes_materiaux_une_ligne_v1"


def kind_ligne_achat(achat_kind: Optional[str]) -> str:
    """Type d'une ligne d'achat refacturé : une facture de sous-traitant
    est un service ; matériel, outils et location d'outils sont des
    matériaux."""
    return KIND_SERVICE if (achat_kind or "") == "sub_invoice" else KIND_MATERIAUX


def cle_libelle(label: Optional[str]) -> str:
    """Clé de REGROUPEMENT des lignes d'achat : accents retirés, casse et
    espaces normalisés — « Matériel — Matériaux Divers » et « Matériel —
    Materiaux Divers » tombent sur la même ligne."""
    import unicodedata

    s = unicodedata.normalize("NFKD", label or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.lower().split())


def libelle_materiaux(entete: Optional[str] = None) -> str:
    """Libellé de la ligne « Matériaux » d'une facture. Sur la facture d'un
    bon de travail, la demande du bon coiffe la ligne, comme pour
    « Main-d'œuvre »."""
    return f"{entete}\n{LIBELLE_MATERIAUX}" if entete else LIBELLE_MATERIAUX


async def ligne_materiaux_existante(
    db, facture_id: int, libelle: str
) -> Optional[FactureItem]:
    """Ligne « Matériaux » déjà posée sur la facture par un import (au même
    libellé, et portant au moins un achat refacturé) : un achat importé plus
    tard s'y additionne au lieu d'ouvrir une nouvelle ligne."""
    from app.models.achat import Achat

    cle = cle_libelle(libelle)
    lignes = (
        await db.execute(
            select(FactureItem)
            .where(
                FactureItem.facture_id == facture_id,
                FactureItem.kind == KIND_MATERIAUX,
                FactureItem.soumission_item_id.is_(None),
                FactureItem.id.in_(
                    select(Achat.facture_item_id).where(
                        Achat.facture_item_id.is_not(None)
                    )
                ),
            )
            .order_by(FactureItem.position.asc(), FactureItem.id.asc())
        )
    ).scalars().all()
    for it in lignes:
        if cle_libelle(it.description) == cle:
            return it
    return None


def ajouter_au_montant(ligne: FactureItem, montant: float) -> None:
    """Additionne un achat à une ligne regroupée (quantité 1, prix = total)."""
    ligne.total = round(float(ligne.total or 0) + float(montant), 2)
    ligne.quantity = 1
    ligne.unit_price = ligne.total


def est_hors_soumission(
    kind: Optional[str], hors_soumission: Optional[bool]
) -> bool:
    """Vrai si la ligne ne compte PAS dans l'avancement de la soumission
    de base : un « extra », ou une ligne importée marquée hors soumission."""
    return (kind or "") == KIND_EXTRA or bool(hors_soumission)


def clause_hors_soumission():
    """``est_hors_soumission`` en SQL, pour les filtres et agrégats."""
    return or_(
        FactureItem.kind == KIND_EXTRA,
        FactureItem.hors_soumission.is_(True),
    )


async def projet_a_soumission(db, project_id: Optional[int]) -> bool:
    """Le projet est-il rattaché à une soumission ? Décide de la marque
    « hors soumission » des lignes importées sur ses factures."""
    if not project_id:
        return False
    from app.models.project import Project

    sid = (
        await db.execute(
            select(Project.soumission_id).where(Project.id == project_id)
        )
    ).scalar_one_or_none()
    return sid is not None


async def reclasser_lignes_importees_brouillons(db) -> int:
    """Reclasse les lignes « extra » IMPORTÉES (liées à des heures ou à des
    achats) des factures encore en BROUILLON : Service / Matériaux, avec la
    marque hors soumission si le projet a une soumission — exactement ce
    que l'import pose désormais. Les factures envoyées ou payées et les
    extras saisis à la main ne bougent pas. Ne commite pas."""
    from app.models.achat import Achat
    from app.models.facture import Facture, FactureStatus
    from app.models.project import Project
    from app.models.punch import Punch

    rows = (
        await db.execute(
            select(FactureItem, Project.soumission_id)
            .join(Facture, Facture.id == FactureItem.facture_id)
            .outerjoin(Project, Project.id == Facture.project_id)
            .where(
                Facture.status == FactureStatus.DRAFT.value,
                FactureItem.kind == KIND_EXTRA,
            )
        )
    ).all()
    if not rows:
        return 0
    ids = [int(it.id) for it, _sid in rows]
    lignes_heures = set(
        (
            await db.execute(
                select(Punch.facture_item_id).where(
                    Punch.facture_item_id.in_(ids)
                )
            )
        ).scalars().all()
    )
    # Une ligne fusionnée porte plusieurs achats au même descriptif — donc
    # au même préfixe (Matériel / Sous-traitant…) et au même type.
    nature_achats = {
        int(fid): kind_ligne_achat(kind)
        for fid, kind in (
            await db.execute(
                select(Achat.facture_item_id, Achat.kind).where(
                    Achat.facture_item_id.in_(ids)
                )
            )
        ).all()
    }
    n = 0
    for it, sid in rows:
        if int(it.id) in lignes_heures:
            it.kind = KIND_SERVICE
        elif int(it.id) in nature_achats:
            it.kind = nature_achats[int(it.id)]
        else:
            continue  # extra saisi à la main : on n'y touche pas
        it.hors_soumission = sid is not None
        n += 1
    if n:
        await db.flush()
    return n


async def reclasser_brouillons_une_fois(db) -> int:
    """Reclassement des brouillons, une seule fois (marqueur
    applied_backfills) : un choix fait ensuite à la main dans l'éditeur
    n'est jamais réécrasé. Commite."""
    from sqlalchemy import text

    deja = (
        await db.execute(
            text("SELECT 1 FROM applied_backfills WHERE key = :k"),
            {"k": CLE_RECLASSEMENT_BROUILLONS},
        )
    ).first()
    if deja is not None:
        return 0
    n = await reclasser_lignes_importees_brouillons(db)
    await db.execute(
        text(
            "INSERT INTO applied_backfills (key) VALUES (:k) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"k": CLE_RECLASSEMENT_BROUILLONS},
    )
    await db.commit()
    return n


#: Préfixes que les imports posaient devant chaque achat de matériel
#: (« Matériel — facture -146 »). Sert à reconnaître ces lignes dans les
#: brouillons ; une ligne renommée à la main n'est jamais touchée.
_PREFIXES_ANCIENS_MATERIEL = ("Matériel — ", "Outils — ", "Location d'outils — ")


def _entete_ligne_achat(description: str) -> tuple[bool, Optional[str]]:
    """(reconnue, entête) d'une ancienne ligne d'achat de matériel :
    l'entête est la demande du bon qui coiffait la ligne, s'il y en a."""
    for prefixe in _PREFIXES_ANCIENS_MATERIEL:
        if description.startswith(prefixe):
            return True, None
        i = description.find("\n" + prefixe)
        if i > 0:
            return True, description[:i]
    if cle_libelle(description.rsplit("\n", 1)[-1]) == cle_libelle(
        LIBELLE_MATERIAUX
    ):
        entete = description.rsplit("\n", 1)[0] if "\n" in description else None
        return True, entete
    return False, None


async def regrouper_materiaux_brouillons(db) -> int:
    """Dans les factures encore en BROUILLON, fusionne les lignes d'achats
    de matériel importés en UNE ligne « Matériaux » par facture (par bon
    pour la facture d'un bon), au total cumulé — exactement ce que l'import
    pose désormais. Sous-traitants, lignes saisies ou renommées à la main
    et factures envoyées : intacts. Retourne le nombre de lignes retirées
    par la fusion. Ne commite pas."""
    from app.models.achat import Achat
    from app.models.facture import Facture, FactureStatus

    rows = (
        await db.execute(
            select(FactureItem, Achat)
            .join(Facture, Facture.id == FactureItem.facture_id)
            .join(Achat, Achat.facture_item_id == FactureItem.id)
            .where(
                Facture.status == FactureStatus.DRAFT.value,
                FactureItem.kind == KIND_MATERIAUX,
                FactureItem.soumission_item_id.is_(None),
            )
            .order_by(
                FactureItem.facture_id.asc(),
                FactureItem.position.asc(),
                FactureItem.id.asc(),
                Achat.id.asc(),
            )
        )
    ).all()
    if not rows:
        return 0
    lignes: dict[int, FactureItem] = {}
    achats_par_ligne: dict[int, list] = {}
    for it, ac in rows:
        lignes[int(it.id)] = it
        achats_par_ligne.setdefault(int(it.id), []).append(ac)
    groupes: dict[tuple[int, str], list[FactureItem]] = {}
    for iid, it in lignes.items():
        achats = achats_par_ligne[iid]
        if any(kind_ligne_achat(a.kind) != KIND_MATERIAUX for a in achats):
            continue
        reconnue, entete = _entete_ligne_achat(it.description or "")
        if not reconnue:
            continue
        # Montant refacturé d'un achat seul sur sa ligne : le total de la
        # ligne (retouches à la main comprises).
        if len(achats) == 1 and achats[0].montant_refacture is None:
            achats[0].montant_refacture = float(it.total or 0)
        groupes.setdefault(
            (int(it.facture_id), cle_libelle(entete or "")), []
        ).append(it)
    retirees = 0
    for (_fid, _cle), items in groupes.items():
        cible = items[0]
        _reconnue, entete = _entete_ligne_achat(cible.description or "")
        total = round(sum(float(i.total or 0) for i in items), 2)
        cible.description = libelle_materiaux(entete)
        cible.unit = "lot"
        cible.quantity = 1
        cible.unit_price = total
        cible.total = total
        for autre in items[1:]:
            for ac in achats_par_ligne[int(autre.id)]:
                ac.facture_item_id = cible.id
            retirees += 1
        await db.flush()
        for autre in items[1:]:
            await db.delete(autre)
    if groupes:
        await db.flush()
    return retirees


async def regrouper_materiaux_une_fois(db) -> int:
    """Regroupement des brouillons, une seule fois (marqueur
    applied_backfills). Commite."""
    from sqlalchemy import text

    deja = (
        await db.execute(
            text("SELECT 1 FROM applied_backfills WHERE key = :k"),
            {"k": CLE_REGROUPEMENT_MATERIAUX},
        )
    ).first()
    if deja is not None:
        return 0
    n = await regrouper_materiaux_brouillons(db)
    await db.execute(
        text(
            "INSERT INTO applied_backfills (key) VALUES (:k) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"k": CLE_REGROUPEMENT_MATERIAUX},
    )
    await db.commit()
    return n
