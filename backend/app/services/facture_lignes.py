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


def kind_ligne_achat(achat_kind: Optional[str]) -> str:
    """Type d'une ligne d'achat refacturé : une facture de sous-traitant
    est un service ; matériel, outils et location d'outils sont des
    matériaux."""
    return KIND_SERVICE if (achat_kind or "") == "sub_invoice" else KIND_MATERIAUX


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
