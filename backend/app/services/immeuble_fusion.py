"""Fusion de deux fiches d'immeuble (retour Steven 2026-10-29).

Un 12 logements sur deux adresses (710 Legendre + 9085 Millen) avait été
saisi en deux fiches : hypothèque conjointe comptée deux fois, totaux en
double, deux listes de logements. Ici la fiche « source » est absorbée
par la fiche « cible » : tout ce qui pend à la source (logements et leurs
baux, hypothèques, évaluations, dépenses, documents, codes d'accès, bons
de travail, affectations d'employés…) est rattaché à la cible, l'adresse
de la source devient l'adresse secondaire de la cible, puis la source est
supprimée.

La liste des tables n'est PAS écrite à la main : toute colonne
``immeuble_id`` (ou clé étrangère vers ``imm_immeubles.id``) du modèle est
re-pointée, ce qui couvre aussi les tables à venir. Les tables où
``immeuble_id`` fait partie d'une clé unique (affectations d'employés,
comptes QuickBooks, parts d'hypothèque conjointe…) sont dédoublonnées
avant. Avant de supprimer la source, on vérifie que plus rien ne pointe
sur elle : une ligne oubliée ferait échouer la fusion plutôt que de
partir en silence avec la cascade.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from sqlalchemy import (
    Column,
    Table,
    UniqueConstraint,
    delete,
    func,
    select,
    tuple_,
    update,
)

from app.db.base import Base
from app.models.immobilier import (
    Bail,
    Hypotheque,
    HypothequeImmeuble,
    HypothequeTranche,
    Immeuble,
    ImmeubleCode,
    ImmeubleOwnership,
    Logement,
)

log = logging.getLogger(__name__)

TABLE_IMMEUBLES = "imm_immeubles"

#: Libellés affichés dans l'aperçu et le résumé (table → français).
LIBELLES: dict[str, str] = {
    "imm_logements": "logements",
    "imm_hypotheques": "hypothèques",
    "imm_hypotheque_immeubles": "parts d'hypothèque conjointe",
    "imm_evaluations": "évaluations",
    "immeuble_depenses": "dépenses",
    "imm_documents": "documents",
    "imm_immeuble_codes": "codes d'accès",
    "imm_maintenance_ordres": "ordres de maintenance",
    "bons_travail": "bons de travail",
    "user_immeubles": "affectations d'employés",
    "imm_communications": "communications",
    "imm_releves31": "relevés 31",
    "imm_factures_gestion": "factures de gestion",
    "imm_frais_manuels_gestion": "frais de gestion manuels",
    "imm_factures_externes": "factures externes",
    "contrats_gestion": "contrats de gestion",
    "inv_investissements": "investissements",
    "optimisation_projets": "projets d'optimisation",
    "qbo_compte_immeubles": "comptes QuickBooks",
    "qbo_comptes_loyers": "comptes de loyers QuickBooks",
    "imm_locataire_contacts": "contacts de locataires",
    "tal_transmissions": "transmissions TAL",
    "entreprise_tache_immeubles": "tâches d'entreprise",
    "prospection_deal_task_immeubles": "tâches de prospection",
    "imm_immeuble_ownerships": "parts de propriété",
}

#: Tables traitées à la main avant la passe générique.
_SPECIALES = {
    "imm_logements",
    "imm_hypotheques",
    "imm_hypotheque_immeubles",
    "imm_immeuble_ownerships",
}


class FusionImpossible(ValueError):
    """La fusion est refusée pour une raison que l'utilisateur peut corriger
    (numéros de logement en conflit, numéro trop long…)."""


def libelle(table: Table) -> str:
    return LIBELLES.get(table.name, table.name)


def cle_numero(numero: Optional[str]) -> str:
    """Même clé que ``create_logement`` : casse, espaces et tirets ignorés,
    zéros de tête retirés (« 04 » = « 4 »)."""
    cle = "".join(ch for ch in (numero or "").lower() if ch.isalnum())
    return re.sub(r"^0+(?=\d)", "", cle)


def _norm_adresse(adresse: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (adresse or "").strip().lower())


def _vide(valeur: Any) -> bool:
    return valeur is None or (isinstance(valeur, str) and not valeur.strip())


def colonnes_vers_immeuble() -> list[tuple[Table, Column]]:
    """Toutes les colonnes du modèle qui désignent un immeuble : clé
    étrangère vers ``imm_immeubles.id`` ou colonne nommée ``immeuble_id``
    (certaines, comme ``tal_transmissions``, n'ont pas de clé déclarée)."""
    out: list[tuple[Table, Column]] = []
    for table in Base.metadata.tables.values():
        if table.name == TABLE_IMMEUBLES:
            continue
        for col in table.columns:
            vise = any(
                fk.column.table.name == TABLE_IMMEUBLES for fk in col.foreign_keys
            )
            if vise or col.name == "immeuble_id":
                out.append((table, col))
    return out


def _cle_unique(table: Table, col: Column) -> Optional[list[Column]]:
    """Si ``col`` fait partie d'une clé primaire ou unique composée,
    renvoie les AUTRES colonnes de cette clé ; ``[]`` si ``col`` est unique
    à elle seule ; ``None`` si aucune contrainte."""
    if col.unique:
        return []
    contraintes = [table.primary_key] + [
        c for c in table.constraints if isinstance(c, UniqueConstraint)
    ]
    for c in contraintes:
        cols = list(c.columns)
        if any(x is col for x in cols) and len(cols) > 1:
            return [x for x in cols if x is not col]
    return None


async def _compter(db, table: Table, col: Column, immeuble_id: int) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(table).where(col == immeuble_id)
        )
    ).scalar_one()


async def _deplacer_colonne(
    db, table: Table, col: Column, source_id: int, cible_id: int
) -> tuple[int, int]:
    """Re-pointe ``col`` de la source vers la cible. Renvoie (déplacées,
    doublons retirés) — un doublon est une ligne de la source dont la clé
    unique existe déjà pour la cible (même employé affecté aux deux…)."""
    autres = _cle_unique(table, col)
    doublons = 0
    if autres is not None:
        if autres:
            deja = select(*autres).where(col == cible_id)
            cond = (
                tuple_(*autres).in_(deja) if len(autres) > 1 else autres[0].in_(deja)
            )
            res = await db.execute(delete(table).where(col == source_id, cond))
            doublons = res.rowcount or 0
        elif await _compter(db, table, col, cible_id):
            res = await db.execute(delete(table).where(col == source_id))
            doublons = res.rowcount or 0
    res = await db.execute(
        update(table).where(col == source_id).values({col.name: cible_id})
    )
    return (res.rowcount or 0), doublons


async def _logements(db, immeuble_id: int) -> list[Logement]:
    return list(
        (
            await db.execute(
                select(Logement)
                .where(Logement.immeuble_id == immeuble_id)
                .order_by(Logement.id)
            )
        ).scalars().all()
    )


async def _hypotheques(db, immeuble_id: int) -> list[Hypotheque]:
    return list(
        (
            await db.execute(
                select(Hypotheque)
                .where(Hypotheque.immeuble_id == immeuble_id)
                .order_by(Hypotheque.rang, Hypotheque.id)
            )
        ).scalars().all()
    )


def _conflits_numeros(
    logs_source: list[Logement], logs_cible: list[Logement], prefixe: str
) -> list[str]:
    cles_cible = {cle_numero(l.numero) for l in logs_cible}
    out: list[str] = []
    for l in logs_source:
        nouveau = f"{prefixe}{l.numero}" if prefixe else l.numero
        if cle_numero(nouveau) in cles_cible:
            out.append(nouveau)
    return out


def prefixe_suggere(source: Immeuble) -> str:
    """Numéro civique de la source + tiret (« 9085 rue Millen » → « 9085- »)."""
    m = re.match(r"\s*(\d+[A-Za-z]?)", source.address or "")
    return f"{m.group(1)}-" if m else ""


def _cle_hypotheque(h: Hypotheque) -> tuple[str, int]:
    return (
        re.sub(r"\s+", " ", (h.preteur or "").strip().lower()),
        int(round(float(h.montant_initial or 0))),
    )


def prix_achat_suggere(cible: Immeuble, source: Immeuble) -> Optional[float]:
    """Celui de la cible si la source n'en a pas ou a le même (prix du
    12 logements saisi deux fois) ; la somme si chacune porte sa moitié."""
    a = cible.purchase_price
    b = source.purchase_price
    if not b:
        return a
    if not a:
        return b
    if abs(float(a) - float(b)) < 0.005:
        return a
    return float(a) + float(b)


async def _resume(db, imm: Immeuble) -> dict:
    nb = await _compter(db, Logement.__table__, Logement.__table__.c.immeuble_id, imm.id)
    return {
        "id": imm.id,
        "name": imm.name,
        "address": imm.address,
        "address_secondaire": imm.address_secondaire,
        "nb_logements": nb,
        "purchase_price": imm.purchase_price,
    }


async def apercu_fusion(db, cible: Immeuble, source: Immeuble) -> dict:
    """Ce que la fusion déplacerait, sans rien changer."""
    a_deplacer: dict[str, int] = {}
    for table, col in colonnes_vers_immeuble():
        n = await _compter(db, table, col, source.id)
        if n:
            lib = libelle(table)
            a_deplacer[lib] = a_deplacer.get(lib, 0) + n
    nb_baux = (
        await db.execute(
            select(func.count(Bail.id))
            .join(Logement, Logement.id == Bail.logement_id)
            .where(Logement.immeuble_id == source.id)
        )
    ).scalar_one()
    if nb_baux:
        a_deplacer["baux"] = nb_baux

    logs_source = await _logements(db, source.id)
    logs_cible = await _logements(db, cible.id)
    conflits = _conflits_numeros(logs_source, logs_cible, "")

    hyps_cible = {_cle_hypotheque(h) for h in await _hypotheques(db, cible.id)}
    hyps_source = await _hypotheques(db, source.id)
    conjointes = {
        r[0]
        for r in (
            await db.execute(
                select(HypothequeImmeuble.hypotheque_id).where(
                    HypothequeImmeuble.hypotheque_id.in_([h.id for h in hyps_source])
                )
            )
        ).all()
    } if hyps_source else set()
    apercu_hyps = []
    en_double = 0
    for h in hyps_source:
        double = _cle_hypotheque(h) in hyps_cible
        en_double += int(double)
        apercu_hyps.append(
            {
                "id": h.id,
                "preteur": h.preteur,
                "montant_initial": float(h.montant_initial or 0),
                "paiement_mensuel": h.paiement_mensuel,
                "status": h.status,
                "conjointe": h.id in conjointes,
                "en_double": double,
            }
        )
    return {
        "cible": await _resume(db, cible),
        "source": await _resume(db, source),
        "a_deplacer": a_deplacer,
        "numeros_en_conflit": conflits,
        "prefixe_suggere": prefixe_suggere(source) if conflits else "",
        "hypotheques_source": apercu_hyps,
        "hypotheques_en_double": en_double,
        "purchase_price_suggere": prix_achat_suggere(cible, source),
    }


async def fusionner(
    db,
    cible: Immeuble,
    source: Immeuble,
    *,
    prefixe_numeros: Optional[str] = None,
    exclure_hypotheques: bool = False,
    purchase_price: Optional[float] = None,
) -> dict:
    """Absorbe ``source`` dans ``cible`` puis supprime ``source``. Lève
    ``FusionImpossible`` (rien n'est écrit) si des numéros de logement
    entreraient en conflit. Commit en fin de fusion."""
    if cible.id == source.id:
        raise FusionImpossible("Un immeuble ne se fusionne pas avec lui-même.")
    source_id, source_nom = source.id, source.name
    deplaces: dict[str, int] = {}

    def _ajouter(lib: str, n: int) -> None:
        if n:
            deplaces[lib] = deplaces.get(lib, 0) + n

    # 1. Logements : préfixe éventuel, adresse propre, puis rattachement.
    prefixe = (prefixe_numeros or "").strip()
    logs_source = await _logements(db, source_id)
    logs_cible = await _logements(db, cible.id)
    conflits = _conflits_numeros(logs_source, logs_cible, prefixe)
    if conflits:
        raise FusionImpossible(
            f"Numéros de logement déjà présents dans « {cible.name} » : "
            f"{', '.join(conflits)}. Donne un préfixe aux logements déplacés "
            f"(ex. « {prefixe_suggere(source) or '9085-'} »)."
        )
    trop_longs = [
        f"{prefixe}{l.numero}" for l in logs_source if len(f"{prefixe}{l.numero}") > 32
    ]
    if trop_longs:
        raise FusionImpossible(
            "Numéro de logement trop long après préfixe (32 caractères max) : "
            + ", ".join(trop_longs)
        )
    adresse_differente = _norm_adresse(source.address) != _norm_adresse(cible.address)
    for l in logs_source:
        if prefixe:
            l.numero = f"{prefixe}{l.numero}"
        if adresse_differente and _vide(l.adresse):
            l.adresse = (source.address or "").strip()[:255]
        l.immeuble_id = cible.id
    _ajouter("logements", len(logs_source))
    nb_baux = (
        await db.execute(
            select(func.count(Bail.id)).where(
                Bail.logement_id.in_([l.id for l in logs_source])
            )
        )
    ).scalar_one() if logs_source else 0
    _ajouter("baux", nb_baux)
    await db.flush()

    # 2. Hypothèques de la source : transférées, ou retirées si ce sont les
    #    mêmes que celles de la cible (conjointe saisie deux fois).
    hyps_source = await _hypotheques(db, source_id)
    hypotheques_exclues = 0
    if hyps_source and exclure_hypotheques:
        ids = [h.id for h in hyps_source]
        await db.execute(
            delete(HypothequeTranche).where(HypothequeTranche.hypotheque_id.in_(ids))
        )
        await db.execute(
            delete(HypothequeImmeuble).where(HypothequeImmeuble.hypotheque_id.in_(ids))
        )
        await db.execute(delete(Hypotheque).where(Hypotheque.id.in_(ids)))
        hypotheques_exclues = len(ids)
    else:
        for h in hyps_source:
            h.immeuble_id = cible.id
        _ajouter("hypothèques", len(hyps_source))
    await db.flush()

    # 2b. Parts d'hypothèque conjointe qui visaient la source : la part
    #     rejoint celle de la cible (ou devient la sienne). Une hypothèque
    #     qui ne couvre plus qu'un immeuble redevient simple (100 %).
    parts = list(
        (
            await db.execute(
                select(HypothequeImmeuble).where(
                    HypothequeImmeuble.immeuble_id == source_id
                )
            )
        ).scalars().all()
    )
    touchees = {p.hypotheque_id for p in parts}
    for p in parts:
        existante = (
            await db.execute(
                select(HypothequeImmeuble).where(
                    HypothequeImmeuble.hypotheque_id == p.hypotheque_id,
                    HypothequeImmeuble.immeuble_id == cible.id,
                )
            )
        ).scalar_one_or_none()
        if existante is not None:
            existante.part_pct = float(existante.part_pct) + float(p.part_pct)
            await db.delete(p)
        else:
            p.immeuble_id = cible.id
    await db.flush()
    for hid in touchees:
        restantes = list(
            (
                await db.execute(
                    select(HypothequeImmeuble).where(
                        HypothequeImmeuble.hypotheque_id == hid
                    )
                )
            ).scalars().all()
        )
        if len(restantes) < 2:
            for r in restantes:
                await db.delete(r)
    _ajouter("parts d'hypothèque conjointe", len(parts))
    await db.flush()

    # 3. Codes d'accès : à la suite de ceux de la cible.
    max_pos = (
        await db.execute(
            select(func.coalesce(func.max(ImmeubleCode.position), -1)).where(
                ImmeubleCode.immeuble_id == cible.id
            )
        )
    ).scalar_one()
    await db.execute(
        update(ImmeubleCode)
        .where(ImmeubleCode.immeuble_id == source_id)
        .values(position=ImmeubleCode.position + int(max_pos) + 1)
    )

    # 4. Propriété (INC) : si la cible a déjà ses parts, on garde les
    #    siennes telles quelles ; sinon celles de la source la suivent.
    nb_parts_cible = await _compter(
        db, ImmeubleOwnership.__table__, ImmeubleOwnership.__table__.c.immeuble_id, cible.id
    )
    if nb_parts_cible:
        res = await db.execute(
            delete(ImmeubleOwnership).where(ImmeubleOwnership.immeuble_id == source_id)
        )
        _ajouter("parts de propriété abandonnées (celles de la cible sont gardées)", res.rowcount or 0)
    else:
        n, _ = await _deplacer_colonne(
            db, ImmeubleOwnership.__table__, ImmeubleOwnership.__table__.c.immeuble_id, source_id, cible.id
        )
        _ajouter("parts de propriété", n)

    # 5. Passe générique : tout le reste.
    for table, col in colonnes_vers_immeuble():
        if table.name in _SPECIALES:
            continue
        n, doublons = await _deplacer_colonne(db, table, col, source_id, cible.id)
        _ajouter(libelle(table), n)
        _ajouter(f"{libelle(table)} (doublons retirés)", doublons)

    # 6. Champs de la cible.
    if adresse_differente:
        morceaux = [
            m.strip() for m in (cible.address_secondaire or "").split("·") if m.strip()
        ]
        for adr in [source.address, source.address_secondaire]:
            for m in (adr or "").split("·"):
                m = m.strip()
                if m and _norm_adresse(m) != _norm_adresse(cible.address) and m not in morceaux:
                    morceaux.append(m)
        cible.address_secondaire = (" · ".join(morceaux) or None)
        if cible.address_secondaire:
            cible.address_secondaire = cible.address_secondaire[:500]
    if cible.nb_logements is not None or source.nb_logements is not None:
        cible.nb_logements = (cible.nb_logements or 0) + (source.nb_logements or 0)
    for champ in ("superficie_terrain", "superficie_batiment"):
        a, b = getattr(cible, champ), getattr(source, champ)
        if a is not None or b is not None:
            setattr(cible, champ, float(a or 0) + float(b or 0))
    if purchase_price is not None:
        cible.purchase_price = purchase_price
    elif _vide(cible.purchase_price) and not _vide(source.purchase_price):
        cible.purchase_price = source.purchase_price
    for champ in (
        "purchase_date",
        "annee_construction",
        "matricule",
        "description",
        "urgence_phone",
        "city",
        "postal_code",
        "owner_entreprise_id",
        "owner_deal_id",
        "collecte_depuis",
        "gestionnaire_externe_nom",
        "gestionnaire_externe_contact",
        "cover_photo_url",
        "qbo_customer_id",
        "qbo_customer_name",
    ):
        if _vide(getattr(cible, champ, None)) and not _vide(getattr(source, champ, None)):
            setattr(cible, champ, getattr(source, champ))
    # Photo de couverture : celle de la source si la cible n'en a pas.
    if _vide(cible.cover_photo_url):
        blob_cible = (
            await db.execute(
                select(Immeuble.cover_photo_content_type).where(Immeuble.id == cible.id)
            )
        ).scalar_one_or_none()
        if not blob_cible:
            row = (
                await db.execute(
                    select(Immeuble.cover_photo_blob, Immeuble.cover_photo_content_type)
                    .where(Immeuble.id == source_id)
                )
            ).one_or_none()
            if row and row[0]:
                cible.cover_photo_blob = row[0]
                cible.cover_photo_content_type = row[1]
    await db.flush()

    # 7. Plus rien ne doit pointer sur la source avant de la supprimer.
    restes = []
    for table, col in colonnes_vers_immeuble():
        n = await _compter(db, table, col, source_id)
        if n:
            restes.append(f"{table.name}.{col.name} ({n})")
    if restes:
        raise RuntimeError(
            "Fusion interrompue, des lignes pointent encore sur l'immeuble "
            f"source : {', '.join(restes)}"
        )

    # 8. Suppression de la source (plus aucune dépendance).
    db.expunge(source)
    await db.execute(delete(Immeuble.__table__).where(Immeuble.__table__.c.id == source_id))
    await db.commit()
    await db.refresh(cible)
    log.info(
        "immeuble_fusion: %s (#%s) absorbé par %s (#%s) — %s",
        source_nom, source_id, cible.name, cible.id, deplaces,
    )
    return {
        "deplaces": deplaces,
        "hypotheques_exclues": hypotheques_exclues,
        "immeuble_supprime_id": source_id,
        "immeuble_supprime_nom": source_nom,
    }
