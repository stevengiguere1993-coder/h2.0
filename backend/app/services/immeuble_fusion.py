"""Fusion de deux fiches d'immeuble (retour Steven 2026-10-29).

Un 12 logements sur deux adresses (710 Legendre + 9085 Millen) avait été
saisi en deux fiches : hypothèque conjointe comptée deux fois, totaux en
double, deux listes de logements. Ici la fiche « source » est absorbée
par la fiche « cible » : tout ce qui pend à la source (logements et leurs
baux, hypothèques, évaluations, dépenses, documents, codes d'accès, bons
de travail, affectations d'employés…) est rattaché à la cible, l'adresse
de la source devient l'adresse secondaire de la cible, puis la source est
supprimée.

Retour Steven 2026-11-13 (« il compte 2 adresses donc les suffixes
existants restent les mêmes ; le prix d'achat et l'hypothèque ont été
divisés par 2, ils devront s'additionner lors de la fusion ») :

- un numéro de logement n'est en conflit qu'à la MÊME adresse civique :
  le « 1 » du 9085 Millen et le « 1 » du 710 Legendre peuvent coexister,
  chacun avec son adresse ;
- précision du même jour (« il peut y avoir par exemple 710-1 à 710-2,
  selon ce qui est déjà entré dans chacun des immeubles ; je voulais
  seulement dire de ne pas remplacer 710 Legendre par 9085 Millen ») : le
  préfixe PROPOSÉ est le numéro civique de la fiche ABSORBÉE (« 710- » →
  « 710-1 »), dès que les deux fiches portent les mêmes numéros ; il est
  facultatif hors conflit à la même adresse, et un second préfixe,
  facultatif, s'applique aux logements de la fiche gardée (« 9085- ») ;
- le prix d'achat suggéré est la SOMME des deux fiches ;
- les hypothèques d'un même prêteur (même taux) s'additionnent en un seul
  prêt (montant, versement, solde, tranches) ;
- « l'action est irréversible » : ``fusionner(..., simuler=True)`` fait
  toute la fusion dans la transaction, relève la fiche résultante
  (adresses, logements, hypothèques, prix) puis ANNULE tout — c'est
  l'aperçu affiché avant la confirmation ;
- « au niveau de la valeur actuelle le montant n'est pas bon » (après la
  fusion du 9085 Millen / 710 Legendre) : chaque fiche portait la MOITIÉ
  de l'évaluation agréée et de la valeur municipale ; déplacées telles
  quelles, la fiche gardait deux évaluations « de référence » et n'en
  affichait qu'une moitié. Les évaluations de même type et de même date
  s'additionnent (``evaluations="additionner"``), et il ne reste jamais
  qu'UNE référence après une fusion ;
- « l'adresse dans le haut devrait être présentée 9085 Millen / 710
  Legendre, Montréal » : le nom de la fiche fusionnée porte les deux
  adresses (``app.services.immeuble_nom``) tant qu'il était automatique,
  ou le nom choisi dans la fenêtre (``name``).

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
    Evaluation,
    Hypotheque,
    HypothequeImmeuble,
    HypothequeTranche,
    Immeuble,
    ImmeubleCode,
    ImmeubleOwnership,
    Logement,
)

from app.services.immeuble_nom import nom_automatique, nom_est_automatique
from app.services.immeuble_valeur import evaluation_municipale, evaluation_retenue

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


def norm_adresse(adresse: Optional[str]) -> str:
    """Adresse comparable : casse, ponctuation et espaces ignorés
    (« 710, Rue Legendre Est » = « 710 rue legendre est »)."""
    return " ".join(re.sub(r"[^\w]+", " ", (adresse or "").lower()).split())


_norm_adresse = norm_adresse


def adresse_effective(lg: Logement, imm: Immeuble) -> str:
    """Adresse civique d'un logement : la sienne, sinon celle de l'immeuble."""
    return (lg.adresse or "").strip() or (imm.address or "").strip()


def cle_logement(numero: Optional[str], adresse: Optional[str]) -> tuple[str, str]:
    """Deux logements sont le même s'ils ont le même numéro À LA MÊME
    adresse civique (immeuble à deux adresses : deux « 1 » distincts)."""
    return (_norm_adresse(adresse), cle_numero(numero))


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
    logs_source: list[Logement],
    source: Immeuble,
    logs_cible: list[Logement],
    cible: Immeuble,
    prefixe: str,
    prefixe_cible: str = "",
) -> list[str]:
    """Numéros de la source qui existent déjà dans la cible à la même
    adresse civique (après préfixes éventuels)."""
    cles_cible = {
        cle_logement(
            _numero_cible(l, cible, prefixe_cible), adresse_effective(l, cible)
        )
        for l in logs_cible
    }
    out: list[str] = []
    for l in logs_source:
        nouveau = f"{prefixe}{l.numero}" if prefixe else l.numero
        if cle_logement(nouveau, adresse_effective(l, source)) in cles_cible:
            out.append(nouveau)
    return out


def _numero_cible(l: Logement, cible: Immeuble, prefixe_cible: str) -> str:
    """Numéro d'un logement de la cible après son préfixe facultatif. Le
    préfixe (numéro civique de la cible) ne vise que les logements à
    l'adresse principale : ceux d'une adresse déjà absorbée gardent le leur."""
    if prefixe_cible and _norm_adresse(adresse_effective(l, cible)) == _norm_adresse(
        cible.address
    ):
        return f"{prefixe_cible}{l.numero}"
    return l.numero


def numeros_communs(
    logs_source: list[Logement], logs_cible: list[Logement]
) -> list[str]:
    """Numéros de la source portés aussi par un logement de la cible,
    quelle que soit l'adresse : sans préfixe, la fiche fusionnée aurait
    deux « 1 » que seule leur adresse distingue."""
    cles_cible = {cle_numero(l.numero) for l in logs_cible}
    return [l.numero for l in logs_source if cle_numero(l.numero) in cles_cible]


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
    """La SOMME des deux fiches : chacune porte sa part du prix (Steven
    2026-11-13, 812 500 $ + 812 500 $ pour le 9085 Millen / 710 Legendre).
    Un prix saisi deux fois en entier se corrige dans le champ."""
    a = cible.purchase_price
    b = source.purchase_price
    if not b:
        return a
    if not a:
        return b
    return float(a) + float(b)


def _meme_taux(a: Hypotheque, b: Hypotheque) -> bool:
    if a.taux_pct is None or b.taux_pct is None:
        return True
    return abs(float(a.taux_pct) - float(b.taux_pct)) < 1e-6


async def _ids_conjointes(db, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    return {
        r[0]
        for r in (
            await db.execute(
                select(HypothequeImmeuble.hypotheque_id).where(
                    HypothequeImmeuble.hypotheque_id.in_(ids)
                )
            )
        ).all()
    }


async def paires_a_additionner(
    db, hyps_cible: list[Hypotheque], hyps_source: list[Hypotheque]
) -> dict[int, Hypotheque]:
    """{id hypothèque source: hypothèque de la cible avec laquelle elle
    s'additionne} — même prêteur, même taux, aucune des deux conjointe ;
    à rang égal d'abord. Une hypothèque de la cible ne reçoit qu'une
    moitié."""
    conj = await _ids_conjointes(
        db, [h.id for h in hyps_cible] + [h.id for h in hyps_source]
    )
    libres = [h for h in hyps_cible if h.id not in conj]
    out: dict[int, Hypotheque] = {}
    for hs in hyps_source:
        if hs.id in conj:
            continue
        candidates = [
            hc
            for hc in libres
            if _cle_hypotheque(hc)[0] == _cle_hypotheque(hs)[0] and _meme_taux(hc, hs)
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda hc: (hc.rang != hs.rang, hc.id))
        choisie = candidates[0]
        out[hs.id] = choisie
        libres.remove(choisie)
    return out


def _somme(a: Any, b: Any) -> Optional[float]:
    """Somme de deux montants ; None si l'un manque (le calcul reprend
    alors la valeur dérivée de l'échéancier au lieu d'un total faux)."""
    if a is None or b is None:
        return None
    return round(float(a) + float(b), 2)


async def _additionner_hypotheque(db, cible_h: Hypotheque, source_h: Hypotheque) -> None:
    """Ajoute la moitié ``source_h`` au prêt ``cible_h`` puis la supprime."""
    montant_source = float(source_h.montant_initial or 0)
    cible_h.montant_initial = round(float(cible_h.montant_initial or 0) + montant_source, 2)
    cible_h.balance_actuelle = _somme(cible_h.balance_actuelle, source_h.balance_actuelle)
    if cible_h.paiement_mensuel is not None or source_h.paiement_mensuel is not None:
        cible_h.paiement_mensuel = _somme(cible_h.paiement_mensuel, source_h.paiement_mensuel)
    for champ in (
        "taux_pct", "type_taux", "amortissement_mois", "composition_interets",
        "type_pret", "mode_remboursement", "date_debut", "date_fin_terme",
    ):
        if _vide(getattr(cible_h, champ)) and not _vide(getattr(source_h, champ)):
            setattr(cible_h, champ, getattr(source_h, champ))
    note = (
        f"Fusion de fiches : additionnée avec l'hypothèque #{source_h.id} "
        f"({(source_h.preteur or '').strip()}, {_montant(montant_source)})"
    )
    cible_h.notes = f"{cible_h.notes.rstrip()}\n\n{note}" if cible_h.notes else note
    await db.execute(
        update(HypothequeTranche)
        .where(HypothequeTranche.hypotheque_id == source_h.id)
        .values(hypotheque_id=cible_h.id)
    )
    await db.flush()
    source_id = source_h.id
    db.expunge(source_h)
    await db.execute(delete(Hypotheque).where(Hypotheque.id == source_id))


MODES_HYPOTHEQUES = ("additionner", "transferer", "exclure")
#: Évaluations de même type et de même date dans les deux fiches :
#: « additionner » (chaque fiche portait sa part), « exclure » (la même
#: évaluation saisie en entier des deux côtés : celle de la cible reste
#: seule) ou « transferer » (telles quelles).
MODES_EVALUATIONS = ("additionner", "transferer", "exclure")


def _montant(v: Any) -> str:
    """« 1 580 000,00 $ »."""
    return f"{float(v or 0):,.2f}".replace(",", " ").replace(".", ",") + " $"


async def _evaluations(db, immeuble_id: int) -> list[Evaluation]:
    return list(
        (
            await db.execute(
                select(Evaluation)
                .where(Evaluation.immeuble_id == immeuble_id)
                .order_by(Evaluation.date_evaluation.desc(), Evaluation.id)
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
    )


def paires_evaluations(
    evals_cible: list[Evaluation], evals_source: list[Evaluation]
) -> dict[int, Evaluation]:
    """{id évaluation source: évaluation de la cible de même TYPE et de
    même DATE} — la même évaluation, dont chaque fiche portait sa part.
    Une évaluation de la cible ne reçoit qu'une moitié ; à choix égal,
    celle du même montant d'abord."""
    libres = list(evals_cible)
    out: dict[int, Evaluation] = {}
    for es in evals_source:
        candidates = [
            ec
            for ec in libres
            if ec.kind == es.kind and ec.date_evaluation == es.date_evaluation
        ]
        if not candidates:
            continue
        candidates.sort(
            key=lambda ec: (abs(float(ec.valeur or 0) - float(es.valeur or 0)), ec.id)
        )
        choisie = candidates[0]
        out[es.id] = choisie
        libres.remove(choisie)
    return out


async def _retirer_evaluation(db, e: Evaluation) -> None:
    eid = e.id
    db.expunge(e)
    await db.execute(delete(Evaluation).where(Evaluation.id == eid))


async def _additionner_evaluation(db, cible_e: Evaluation, source_e: Evaluation) -> None:
    """Ajoute la part ``source_e`` à l'évaluation ``cible_e`` puis la supprime."""
    part_cible = float(cible_e.valeur or 0)
    part_source = float(source_e.valeur or 0)
    cible_e.valeur = round(part_cible + part_source, 2)
    if cible_e.taux_cap is None and source_e.taux_cap is not None:
        cible_e.taux_cap = source_e.taux_cap
    if _vide(cible_e.source) and not _vide(source_e.source):
        cible_e.source = source_e.source
    if source_e.is_reference:
        cible_e.is_reference = True
    note = (
        f"Fusion de fiches : {_montant(part_cible)} + {_montant(part_source)} "
        f"(évaluation #{source_e.id} de la fiche absorbée)."
    )
    cible_e.notes = f"{cible_e.notes.rstrip()}\n\n{note}" if cible_e.notes else note
    await db.flush()
    await _retirer_evaluation(db, source_e)


async def _garder_une_reference(db, immeuble_id: int, ids_cible_avant: set[int]) -> int:
    """Une seule évaluation « de référence » par immeuble : celle que la
    cible avait déjà, sinon la plus récente. Renvoie le nombre retiré."""
    refs = [e for e in await _evaluations(db, immeuble_id) if e.is_reference]
    if len(refs) < 2:
        return 0
    gardee = max(
        refs, key=lambda e: (e.id in ids_cible_avant, e.date_evaluation, e.id)
    )
    autres = [e.id for e in refs if e.id != gardee.id]
    await db.execute(
        update(Evaluation).where(Evaluation.id.in_(autres)).values(is_reference=False)
    )
    await db.flush()
    return len(autres)


def adresse_secondaire_fusionnee(cible: Immeuble, source: Immeuble) -> Optional[str]:
    """Les adresses secondaires de la cible après absorption de la source
    (séparées par « · »), sans répéter son adresse principale."""
    if _norm_adresse(source.address) == _norm_adresse(cible.address):
        return cible.address_secondaire
    morceaux = [
        m.strip() for m in (cible.address_secondaire or "").split("·") if m.strip()
    ]
    for adr in [source.address, source.address_secondaire]:
        for m in (adr or "").split("·"):
            m = m.strip()
            if m and _norm_adresse(m) != _norm_adresse(cible.address) and m not in morceaux:
                morceaux.append(m)
    return " · ".join(morceaux)[:500] or None


def nom_fusionne(cible: Immeuble, source: Immeuble) -> str:
    """Le nom de la fiche après la fusion : les deux adresses (« 9085
    Millen / 710 Legendre, Montréal ») si la fusion lui ajoute une adresse
    et que son nom n'était que son adresse ; un nom personnalisé est gardé."""
    nouvelle = adresse_secondaire_fusionnee(cible, source)
    if (nouvelle or "") == (cible.address_secondaire or ""):
        return cible.name
    if not nom_est_automatique(
        cible.name, cible.address, cible.city, cible.address_secondaire
    ):
        return cible.name
    return (
        nom_automatique(cible.address, cible.city or source.city, nouvelle)
        or cible.name
    )


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
    conflits = _conflits_numeros(logs_source, source, logs_cible, cible, "")
    communs = numeros_communs(logs_source, logs_cible)

    liste_cible = await _hypotheques(db, cible.id)
    hyps_cible = {_cle_hypotheque(h) for h in liste_cible}
    hyps_source = await _hypotheques(db, source.id)
    conjointes = await _ids_conjointes(db, [h.id for h in hyps_source])
    paires = await paires_a_additionner(db, liste_cible, hyps_source)
    apercu_hyps = []
    en_double = 0
    for h in hyps_source:
        double = _cle_hypotheque(h) in hyps_cible
        en_double += int(double)
        avec = paires.get(h.id)
        apercu_hyps.append(
            {
                "id": h.id,
                "preteur": h.preteur,
                "montant_initial": float(h.montant_initial or 0),
                "paiement_mensuel": h.paiement_mensuel,
                "status": h.status,
                "conjointe": h.id in conjointes,
                "en_double": double,
                "additionnable_avec": avec.id if avec is not None else None,
                "montant_additionne": (
                    float(avec.montant_initial or 0) + float(h.montant_initial or 0)
                    if avec is not None
                    else None
                ),
            }
        )
    evals_cible = await _evaluations(db, cible.id)
    evals_source = await _evaluations(db, source.id)
    paires_eval = paires_evaluations(evals_cible, evals_source)
    apercu_evals = []
    for e in evals_source:
        avec_e = paires_eval.get(e.id)
        apercu_evals.append(
            {
                "id": e.id,
                "kind": e.kind,
                "valeur": float(e.valeur or 0),
                "date_evaluation": e.date_evaluation,
                "is_reference": bool(e.is_reference),
                "additionnable_avec": avec_e.id if avec_e is not None else None,
                "valeur_cible": (
                    float(avec_e.valeur or 0) if avec_e is not None else None
                ),
                "valeur_additionnee": (
                    round(float(avec_e.valeur or 0) + float(e.valeur or 0), 2)
                    if avec_e is not None
                    else None
                ),
            }
        )
    return {
        "cible": await _resume(db, cible),
        "source": await _resume(db, source),
        "a_deplacer": a_deplacer,
        "evaluations_source": apercu_evals,
        "evaluations_additionnables": len(paires_eval),
        # Nom de la fiche fusionnée : les deux adresses dans le titre.
        "nom_suggere": nom_fusionne(cible, source),
        "numeros_en_conflit": conflits,
        "numeros_communs": communs,
        "numeros_source": [l.numero for l in logs_source],
        "numeros_cible": [l.numero for l in logs_cible],
        # Le préfixe est le numéro civique de CHAQUE fiche pour ses propres
        # logements : « 710- » pour ceux du 710 Legendre, jamais « 9085- ».
        "prefixe_suggere": prefixe_suggere(source) if (conflits or communs) else "",
        "prefixe_cible_suggere": prefixe_suggere(cible),
        "hypotheques_source": apercu_hyps,
        "hypotheques_en_double": en_double,
        "hypotheques_additionnables": len(paires),
        "purchase_price_suggere": prix_achat_suggere(cible, source),
    }


async def fusionner(
    db,
    cible: Immeuble,
    source: Immeuble,
    *,
    prefixe_numeros: Optional[str] = None,
    prefixe_numeros_cible: Optional[str] = None,
    exclure_hypotheques: bool = False,
    hypotheques: Optional[str] = None,
    evaluations: Optional[str] = None,
    purchase_price: Optional[float] = None,
    name: Optional[str] = None,
    simuler: bool = False,
) -> dict:
    """Absorbe ``source`` dans ``cible`` puis supprime ``source``. Lève
    ``FusionImpossible`` (rien n'est écrit) si des numéros de logement
    entreraient en conflit. Commit en fin de fusion.

    ``prefixe_numeros`` se pose devant les numéros des logements de la
    SOURCE (« 710- » → « 710-1 »), ``prefixe_numeros_cible`` devant ceux de
    la cible (« 9085- ») ; vides = numéros inchangés. Dans tous les cas
    chaque logement garde son adresse civique.

    ``hypotheques`` : « additionner » (les moitiés d'un même prêteur se
    fondent en un prêt), « transferer » (telles quelles), « exclure »
    (saisies en double, retirées). Absent = « exclure » si
    ``exclure_hypotheques``, sinon « transferer ».

    ``evaluations`` : « additionner » (les évaluations de même type et de
    même date se fondent en une seule, chaque fiche en portait sa part),
    « exclure » (la même évaluation saisie en entier des deux côtés : celle
    de la source est retirée) ou « transferer » (telles quelles, défaut).
    Dans tous les cas il ne reste qu'UNE évaluation de référence.

    ``name`` : nom de la fiche fusionnée. Absent, un nom encore automatique
    (l'adresse) devient « 9085 Millen / 710 Legendre, Montréal » ; un nom
    personnalisé ne bouge pas.

    ``simuler`` : tout est fait dans la transaction, la fiche résultante
    est relevée (clé ``resultat``) puis la transaction est ANNULÉE."""
    if cible.id == source.id:
        raise FusionImpossible("Un immeuble ne se fusionne pas avec lui-même.")
    mode_hyp = hypotheques or ("exclure" if exclure_hypotheques else "transferer")
    if mode_hyp not in MODES_HYPOTHEQUES:
        raise FusionImpossible(f"Choix d'hypothèques inconnu : « {mode_hyp} ».")
    mode_eval = evaluations or "transferer"
    if mode_eval not in MODES_EVALUATIONS:
        raise FusionImpossible(f"Choix d'évaluations inconnu : « {mode_eval} ».")
    # Relevé AVANT tout changement d'adresse : le nom suit-il les adresses ?
    nom_apres = (name or "").strip()[:255] or nom_fusionne(cible, source)
    source_id, source_nom = source.id, source.name
    deplaces: dict[str, int] = {}

    def _ajouter(lib: str, n: int) -> None:
        if n:
            deplaces[lib] = deplaces.get(lib, 0) + n

    # 1. Logements : préfixe éventuel, adresse propre, puis rattachement.
    prefixe = (prefixe_numeros or "").strip()
    prefixe_cible = (prefixe_numeros_cible or "").strip()
    logs_source = await _logements(db, source_id)
    logs_cible = await _logements(db, cible.id)
    conflits = _conflits_numeros(
        logs_source, source, logs_cible, cible, prefixe, prefixe_cible
    )
    if conflits:
        raise FusionImpossible(
            f"Numéros de logement déjà présents à la même adresse dans « {cible.name} » : "
            f"{', '.join(conflits)}. Donne un préfixe aux logements déplacés "
            f"(ex. « {prefixe_suggere(source) or '9085-'} »)."
        )
    trop_longs = [
        f"{prefixe}{l.numero}" for l in logs_source if len(f"{prefixe}{l.numero}") > 32
    ] + [
        n
        for n in (_numero_cible(l, cible, prefixe_cible) for l in logs_cible)
        if len(n) > 32
    ]
    if trop_longs:
        raise FusionImpossible(
            "Numéro de logement trop long après préfixe (32 caractères max) : "
            + ", ".join(trop_longs)
        )
    adresse_differente = _norm_adresse(source.address) != _norm_adresse(cible.address)
    if prefixe_cible:
        renumerotes = 0
        for l in logs_cible:
            nouveau = _numero_cible(l, cible, prefixe_cible)
            if nouveau != l.numero:
                l.numero = nouveau
                renumerotes += 1
        _ajouter("logements de la fiche gardée renumérotés", renumerotes)
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
    hypotheques_additionnees = 0
    if hyps_source and mode_hyp == "additionner":
        paires = await paires_a_additionner(
            db, await _hypotheques(db, cible.id), hyps_source
        )
        for h in hyps_source:
            avec = paires.get(h.id)
            if avec is not None:
                await _additionner_hypotheque(db, avec, h)
                hypotheques_additionnees += 1
            else:
                h.immeuble_id = cible.id
                _ajouter("hypothèques", 1)
    elif hyps_source and mode_hyp == "exclure":
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

    # 2c. Évaluations : la même évaluation (type + date) portée en deux
    #     parts s'additionne ; le reste suit par la passe générique.
    evals_cible = await _evaluations(db, cible.id)
    evals_source = await _evaluations(db, source_id)
    ids_eval_cible = {e.id for e in evals_cible}
    cible_a_reference = any(e.is_reference for e in evals_cible)
    evaluations_additionnees = 0
    evaluations_exclues = 0
    if evals_source and mode_eval != "transferer":
        paires_eval = paires_evaluations(evals_cible, evals_source)
        for e in evals_source:
            avec_e = paires_eval.get(e.id)
            if avec_e is None:
                continue
            if mode_eval == "additionner":
                await _additionner_evaluation(db, avec_e, e)
                evaluations_additionnees += 1
            else:
                # Saisie en double : celle de la cible reste, et reprend le
                # rôle de référence si la cible n'en avait aucune.
                if e.is_reference and not cible_a_reference:
                    avec_e.is_reference = True
                    cible_a_reference = True
                await db.flush()
                await _retirer_evaluation(db, e)
                evaluations_exclues += 1
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

    # 5b. Une seule évaluation de référence (celle de la cible d'abord).
    await db.flush()
    await _garder_une_reference(db, cible.id, ids_eval_cible)

    # 6. Champs de la cible.
    if adresse_differente:
        cible.address_secondaire = adresse_secondaire_fusionnee(cible, source)
    if nom_apres:
        cible.name = nom_apres
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
    if simuler:
        await db.flush()
        resultat = await etat_fiche(db, cible)
        await db.rollback()
        return {
            "deplaces": deplaces,
            "hypotheques_exclues": hypotheques_exclues,
            "hypotheques_additionnees": hypotheques_additionnees,
            "evaluations_additionnees": evaluations_additionnees,
            "evaluations_exclues": evaluations_exclues,
            "immeuble_supprime_id": source_id,
            "immeuble_supprime_nom": source_nom,
            "resultat": resultat,
        }
    await db.commit()
    await db.refresh(cible)
    log.info(
        "immeuble_fusion: %s (#%s) absorbé par %s (#%s) — %s",
        source_nom, source_id, cible.name, cible.id, deplaces,
    )
    return {
        "deplaces": deplaces,
        "hypotheques_exclues": hypotheques_exclues,
        "hypotheques_additionnees": hypotheques_additionnees,
        "evaluations_additionnees": evaluations_additionnees,
        "evaluations_exclues": evaluations_exclues,
        "immeuble_supprime_id": source_id,
        "immeuble_supprime_nom": source_nom,
    }


async def etat_fiche(db, imm: Immeuble) -> dict:
    """La fiche telle qu'elle est dans la transaction en cours : adresses,
    logements (groupés par adresse civique, ordre naturel), hypothèques et
    totaux. Valeurs simples seulement : sert d'aperçu avant un rollback."""
    from app.services.locatif_chambres import cle_tri_numero

    adresse_princ = (imm.address or "").strip()
    logs = await _logements(db, imm.id)
    lignes = [
        {
            "id": l.id,
            "numero": l.numero,
            "adresse": adresse_effective(l, imm),
            "status": l.status,
        }
        for l in logs
    ]
    lignes.sort(
        key=lambda x: (
            _norm_adresse(x["adresse"]) != _norm_adresse(adresse_princ),
            _norm_adresse(x["adresse"]),
            cle_tri_numero(x["numero"]),
        )
    )
    hyps = await _hypotheques(db, imm.id)
    parts = {
        hid: float(pct)
        for hid, pct in (
            await db.execute(
                select(HypothequeImmeuble.hypotheque_id, HypothequeImmeuble.part_pct).where(
                    HypothequeImmeuble.immeuble_id == imm.id
                )
            )
        ).all()
    }
    lignes_h = [
        {
            "id": h.id,
            "preteur": h.preteur,
            "rang": h.rang,
            "montant_initial": float(h.montant_initial or 0),
            "paiement_mensuel": (
                float(h.paiement_mensuel) if h.paiement_mensuel is not None else None
            ),
            "taux_pct": float(h.taux_pct) if h.taux_pct is not None else None,
            "part_pct": parts.get(h.id, 100.0),
        }
        for h in hyps
    ]
    evals = await _evaluations(db, imm.id)
    retenue = evaluation_retenue(evals)
    municipale = evaluation_municipale(evals)
    lignes_e = [
        {
            "id": e.id,
            "kind": e.kind,
            "valeur": float(e.valeur or 0),
            "date_evaluation": e.date_evaluation,
            "is_reference": bool(e.is_reference),
        }
        for e in evals
    ]
    return {
        "id": imm.id,
        "name": imm.name,
        "address": imm.address,
        "address_secondaire": imm.address_secondaire,
        "nb_logements": imm.nb_logements,
        "purchase_price": (
            float(imm.purchase_price) if imm.purchase_price is not None else None
        ),
        "evaluations": lignes_e,
        "valeur_actuelle": float(retenue.valeur) if retenue is not None else None,
        "valeur_municipale": (
            float(municipale.valeur) if municipale is not None else None
        ),
        "logements": lignes,
        "hypotheques": lignes_h,
        "total_hypotheques": round(
            sum(h["montant_initial"] * h["part_pct"] / 100 for h in lignes_h), 2
        ),
        "total_paiements_mensuels": round(
            sum((h["paiement_mensuel"] or 0) * h["part_pct"] / 100 for h in lignes_h), 2
        ),
    }
