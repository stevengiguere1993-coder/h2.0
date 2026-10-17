"""Atomic sequential numbering for factures + soumissions.

Lit-incrémente-renvoie un compteur unique par type pour générer la
prochaine référence. L'opération est faite via UPDATE … RETURNING
pour rester correcte en cas d'accès concurrent (deux managers qui
créent une facture en même temps).

Utilisation :
    ref = await next_facture_number(db)  # ex. "97"
    ref = await next_soumission_number(db)  # ex. "1011"

Les valeurs sont écrites brutes, sans préfixe — on s'aligne sur la
convention QuickBooks (DocNumber = "97", "98"…). Si un préfixe est
souhaité plus tard, on l'ajoute à la lecture.
"""

from __future__ import annotations

import re
import logging

from typing import Literal, Optional

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.numbering_counter import NumberingCounter


log = logging.getLogger(__name__)


async def _ensure_row(db: AsyncSession) -> NumberingCounter:
    row = (
        await db.execute(select(NumberingCounter).where(NumberingCounter.id == 1))
    ).scalar_one_or_none()
    if row is None:
        await db.execute(
            insert(NumberingCounter).values(
                id=1, next_facture_number=1, next_soumission_number=1
            )
        )
        await db.flush()
        row = (
            await db.execute(
                select(NumberingCounter).where(NumberingCounter.id == 1)
            )
        ).scalar_one()
    return row


async def _next(
    db: AsyncSession, kind: Literal["facture", "soumission", "po"]
) -> int:
    """Atomic read+increment via UPDATE … RETURNING.

    Sur Postgres on aurait pu utiliser une SEQUENCE, mais une table
    config-modifiable par l'admin (UI Paramètres) est plus pratique :
    elle permet de réinitialiser la valeur si on change d'année,
    si on bascule QB sandbox→prod, etc.
    """
    await _ensure_row(db)
    if kind == "facture":
        column = NumberingCounter.next_facture_number
    elif kind == "soumission":
        column = NumberingCounter.next_soumission_number
    else:
        column = NumberingCounter.next_po_number
    stmt = (
        update(NumberingCounter)
        .where(NumberingCounter.id == 1)
        .values({column: column + 1})
        .returning(column)
    )
    result = await db.execute(stmt)
    new_value = int(result.scalar_one())
    await db.flush()
    # new_value est le compteur APRÈS incrément. Le numéro qu'on vient
    # d'attribuer est new_value - 1.
    return new_value - 1


async def next_facture_number(db: AsyncSession) -> str:
    n = await _next(db, "facture")
    return str(n)


#: Préfixe des références PROVISOIRES de facture. Un brouillon ne
#: consomme AUCUN numéro de la séquence : le vrai numéro n'est attribué
#: qu'à l'ENVOI (ou à la première sortie de l'état brouillon). Sans ça,
#: une facture de dépôt créée automatiquement puis envoyée des semaines
#: plus tard (ou jamais) créait des trous dans la numérotation
#: QuickBooks — mauvais en cas d'audit (retour 2026-09-12, point 9).
PROVISIONAL_FACTURE_PREFIX = "BR-"


def provisional_facture_reference() -> str:
    """Référence provisoire unique pour un brouillon (ex. « BR-a1b2c3 »)."""
    import secrets as _secrets

    return f"{PROVISIONAL_FACTURE_PREFIX}{_secrets.token_hex(3)}"


def is_provisional_facture_reference(ref: Optional[str]) -> bool:
    return (ref or "").startswith(PROVISIONAL_FACTURE_PREFIX)


#: Numéros sautés à la dernière attribution (pour le message à l'écran) :
#: {facture_id: ["145"]}.
NUMEROS_SAUTES: dict = {}
#: Nombre maximal de numéros sautés en une attribution. Large : une
#: plage entière peut être prise dans Kratos (factures importées de
#: QuickBooks avec leur DocNumber) et la vérification locale est gratuite.
MAX_SAUTS = 500


async def numero_pris_dans_kratos(db: AsyncSession, ref: str, *, sauf_id=None):
    """La facture Kratos qui porte déjà cette référence (sinon None)."""
    from app.models.facture import Facture

    stmt = select(Facture.id, Facture.project_id).where(Facture.reference == ref)
    if sauf_id is not None:
        stmt = stmt.where(Facture.id != sauf_id)
    return (await db.execute(stmt)).first()


#: Numéro d'une facture du pôle logiciel : « INV-2026-00161 » → 161.
_RE_NUMERO_DEVLOG = re.compile(r"^INV-\d{4}-(\d+)$")


def numero_compteur_de_reference(ref: Optional[str]) -> Optional[int]:
    """Numéro issu du compteur porté par une référence de facture : la
    référence est le numéro tout nu (« 173 », comme le compteur les
    attribue et comme QuickBooks les numérote) ou une facture du pôle
    logiciel (« INV-2026-00173 »). Tout autre libellé (« BR-… »
    provisoire, « ECH-57986972 », « FA-173 » saisi à la main…) n'est PAS
    un numéro du compteur et ne doit jamais le faire sauter."""
    r = (ref or "").strip()
    if r.isdigit():
        return int(r)
    m = _RE_NUMERO_DEVLOG.match(r)
    return int(m.group(1)) if m else None


async def plus_haut_numero_facture_kratos(db: AsyncSession) -> int:
    """Le plus haut numéro porté par une facture de Kratos : factures de
    construction (référence numérique, les brouillons « BR-… » exclus) et
    factures du pôle logiciel (« INV-2026-00161 » → 161, même compteur)."""
    from app.models.facture import Facture

    plus_haut = 0
    for ref in (await db.execute(select(Facture.reference))).scalars().all():
        n = numero_compteur_de_reference(ref)
        if n is not None and n > plus_haut:
            plus_haut = n
    try:
        from app.models.devlog_invoice import DevlogInvoice

        numeros = (await db.execute(select(DevlogInvoice.number))).scalars().all()
    except Exception:  # noqa: BLE001 — table absente (tests partiels)
        numeros = []
    for num in numeros:
        n = numero_compteur_de_reference(num)
        if n is not None and n > plus_haut:
            plus_haut = n
    return plus_haut


#: Au-delà, une « référence » n'est pas un numéro de facture (date collée,
#: numéro de téléphone…) : on ne recale jamais le compteur dessus. Même
#: plafond que le réglage manuel (NumberingUpdate, le=999_999_999).
NUMERO_FACTURE_MAX = 999_999_999


async def cible_compteur_factures(
    db: AsyncSession, *, consulter_qb: bool = True
) -> dict:
    """Ce que devrait valoir au minimum le compteur de factures : plus
    haut numéro existant (Kratos, et QuickBooks s'il répond) + 1. Lecture
    seule."""
    kratos_max = min(await plus_haut_numero_facture_kratos(db), NUMERO_FACTURE_MAX)
    qb_max: Optional[int] = None
    if consulter_qb:
        from app.services.facture_qbo import plus_haut_numero_facture_qb

        qb_max = await plus_haut_numero_facture_qb()
        if qb_max is not None:
            qb_max = min(qb_max, NUMERO_FACTURE_MAX)
    return {
        "kratos_max": kratos_max,
        "qb_max": qb_max,
        "qb_consulte": qb_max is not None,
        "cible": max(kratos_max, qb_max or 0) + 1,
    }


async def aligner_compteur_factures(
    db: AsyncSession, *, consulter_qb: bool = True
) -> dict:
    """Recale le compteur de factures sur le plus haut numéro existant + 1,
    entre Kratos et QuickBooks (Steven 2026-10-17 : « quand des factures
    se créent dans QB, le compteur ne se met pas à jour dans Kratos […] le
    compteur doit toujours être 1 plus haut que QB ou Kratos, le plus
    élevé des deux »). Le compteur n'est jamais ABAISSÉ ici (un numéro
    attribué reste consommé) ; le recyclage après suppression reste à
    part. Si QB ne répond pas, seul Kratos compte et on réessaie au
    prochain passage. Flush mais ne committe pas."""
    await _ensure_row(db)
    avant = int(
        (
            await db.execute(
                select(NumberingCounter.next_facture_number).where(
                    NumberingCounter.id == 1
                )
            )
        ).scalar_one()
        or 1
    )
    cible_info = await cible_compteur_factures(db, consulter_qb=consulter_qb)
    kratos_max = cible_info["kratos_max"]
    qb_max = cible_info["qb_max"]
    cible = cible_info["cible"]
    apres = avant
    if cible > avant:
        await db.execute(
            update(NumberingCounter)
            .where(NumberingCounter.id == 1)
            .values(next_facture_number=cible)
        )
        await db.flush()
        apres = cible
        log.warning(
            "Compteur de factures recalé de %s à %s (plus haut numéro : "
            "Kratos %s, QuickBooks %s)",
            avant, cible, kratos_max,
            qb_max if qb_max is not None else "non consulté",
        )
    return {
        "avant": avant,
        "apres": apres,
        "kratos_max": kratos_max,
        "qb_max": qb_max,
        "qb_consulte": qb_max is not None,
    }


async def aligner_compteur_factures_une_session() -> dict:
    """Même recalage dans une session à lui (démarrage, filet horaire).
    Commite."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        res = await aligner_compteur_factures(db)
        await db.commit()
    return res


async def ensure_facture_number(db: AsyncSession, fa) -> bool:
    """Attribue le VRAI numéro séquentiel à une facture qui n'en a pas
    encore (référence vide ou provisoire « BR-… »). Renvoie True si un
    numéro a été attribué. Flush mais ne committe pas."""
    ref = (getattr(fa, "reference", None) or "").strip()
    if ref and not is_provisional_facture_reference(ref):
        return False
    await attribuer_numero_libre(db, fa)
    return True


async def attribuer_numero_libre(db: AsyncSession, fa) -> list[str]:
    """Donne à la facture le PROCHAIN numéro libre de la séquence, qu'elle
    ait déjà un numéro ou non. Renvoie les numéros sautés. Flush mais ne
    committe pas.

    Sert à la première numérotation (ensure_facture_number) et à la
    renumérotation automatique quand QuickBooks refuse le numéro (déjà
    pris par une autre facture, Steven 2026-10-09).

    Le compteur est d'abord recalé au-dessus du plus haut numéro existant,
    Kratos et QuickBooks confondus (aligner_compteur_factures). Puis deux
    garde-fous — jamais deux factures différentes sous le même numéro :
    - Kratos (incident facture 149, 2026-10-03) : une facture importée
      de QuickBooks (synchro QB → Kratos) garde son DocNumber comme
      référence ; le compteur, lui, ne le sait pas. Si le candidat est
      déjà pris par une facture Kratos, on le saute (sinon l'UPDATE
      échouait sur la contrainte d'unicité `ix_factures_reference` et
      l'envoi plantait).
    - QuickBooks (incident facture 145, 2026-10-01) : si le numéro est
      DÉJÀ pris dans QB par une facture qui n'est pas de Kratos (saisie
      à la main pour un autre projet), on le saute aussi."""
    # D'abord au-dessus de tout ce qui existe (Kratos ET QuickBooks) : une
    # facture saisie directement dans QB ne doit jamais laisser le compteur
    # derrière elle.
    try:
        await aligner_compteur_factures(db)
    except Exception as exc:  # noqa: BLE001
        log.warning("Recalage du compteur de factures impossible : %s", exc)
    sautes: list[str] = []
    cand = None
    for _ in range(MAX_SAUTS):
        cand = await next_facture_number(db)
        local = await numero_pris_dans_kratos(db, cand, sauf_id=getattr(fa, "id", None))
        if local is not None:
            sautes.append(cand)
            log.warning(
                "Numéro de facture %s sauté : déjà porté par la facture Kratos #%s",
                cand, local[0],
            )
            continue
        try:
            from app.services.facture_qbo import numero_pris_hors_kratos

            pris = await numero_pris_hors_kratos(db, cand)
        except Exception:  # noqa: BLE001
            pris = None
        if pris is None:
            break
        sautes.append(cand)
        log.warning(
            "Numéro de facture %s sauté : déjà utilisé dans QuickBooks par une "
            "facture hors Kratos (%s)", cand,
            (pris.get("CustomerRef") or {}).get("name"),
        )
    else:
        raise ValueError(
            f"Impossible d'attribuer un numéro de facture : les {MAX_SAUTS} "
            f"numéros à partir de {sautes[0] if sautes else cand} sont déjà "
            "pris (Kratos ou QuickBooks). Vérifier le compteur dans Paramètres."
        )
    fa.reference = cand
    if sautes:
        NUMEROS_SAUTES[getattr(fa, "id", None)] = sautes
    await db.flush()
    return sautes


async def apercu_prochain_numero_libre(
    db: AsyncSession, *, sauf_id=None, max_essais: int = 50
) -> Optional[str]:
    """Le numéro que la prochaine attribution donnerait, SANS consommer le
    compteur : prochain de la séquence, en sautant ceux déjà pris dans
    Kratos ou dans QuickBooks. Sert à suggérer un numéro quand celui saisi
    à la main est refusé. None si aucun dans la fenêtre."""
    await _ensure_row(db)
    n = int(
        (
            await db.execute(
                select(NumberingCounter.next_facture_number).where(
                    NumberingCounter.id == 1
                )
            )
        ).scalar_one()
        or 1
    )
    # Même point de départ que l'attribution réelle : au-dessus de tout ce
    # qui existe dans Kratos et QuickBooks (lecture seule ici).
    try:
        n = max(n, (await cible_compteur_factures(db))["cible"])
    except Exception as exc:  # noqa: BLE001
        log.warning("Recalage (aperçu) du compteur de factures impossible : %s", exc)
    from app.services.facture_qbo import numero_pris_hors_kratos

    for k in range(max_essais):
        cand = str(n + k)
        if await numero_pris_dans_kratos(db, cand, sauf_id=sauf_id) is not None:
            continue
        try:
            pris = await numero_pris_hors_kratos(db, cand)
        except Exception:  # noqa: BLE001
            pris = None
        if pris is None:
            return cand
    return None


async def next_soumission_number(db: AsyncSession) -> str:
    n = await _next(db, "soumission")
    return str(n)


async def next_po_number(db: AsyncSession) -> str:
    """Numérotation PO format `PO-0027` (préfixe + zero-pad 4 chiffres).
    Cohérent avec ce que la cie utilise déjà (PO-0026, PO-0025, …)."""
    n = await _next(db, "po")
    return f"PO-{n:04d}"


def _ref_num(ref: Optional[str]) -> Optional[int]:
    """Numéro entier d'une référence (« 173 », « FA-173 »… → 173).
    None si la référence ne se termine pas par un nombre."""
    m = re.search(r"(\d+)\s*$", (ref or "").strip())
    return int(m.group(1)) if m else None


async def _recycle_deleted_number(
    db: AsyncSession,
    *,
    counter_column,
    deleted_reference: Optional[str],
    remaining_refs: list[Optional[str]],
) -> Optional[int]:
    """Recycle le numéro d'un document SUPPRIMÉ : recale le compteur sur
    (max des numéros restants + 1) pour que le prochain document reprenne
    le numéro libéré au lieu de continuer la séquence.

    Garde-fous :
    - jamais SOUS le numéro supprimé (l'historique QuickBooks peut être
      plus long que Kratos — on ne veut pas retomber sur un DocNumber
      déjà pris dans QB) ;
    - jamais AU-DESSUS du compteur courant (on recycle, on n'avance pas) ;
    - un trou « du milieu » reste un trou (seule la fin de séquence se
      recycle — supprimer la dernière facture 173 → la prochaine est 173).
    """
    deleted_num = _ref_num(deleted_reference)
    if deleted_num is None:
        return None
    max_num = 0
    for ref in remaining_refs:
        n = _ref_num(ref)
        if n is not None and n > max_num:
            max_num = n
    new_next = max(max_num + 1, deleted_num)
    row = await _ensure_row(db)
    current = int(
        (
            await db.execute(
                select(counter_column).where(NumberingCounter.id == 1)
            )
        ).scalar_one()
    )
    _ = row
    if new_next >= current:
        return None  # rien à recycler (suppression « du milieu »)
    await db.execute(
        update(NumberingCounter)
        .where(NumberingCounter.id == 1)
        .values({counter_column: new_next})
    )
    await db.flush()
    return new_next


async def resync_facture_counter(
    db: AsyncSession, deleted_reference: Optional[str]
) -> Optional[int]:
    """Après suppression d'une facture, recycle son numéro : supprimer la
    dernière facture « 173 » fait que la prochaine créée reprend 173."""
    from app.models.facture import Facture

    refs = list(
        (await db.execute(select(Facture.reference))).scalars().all()
    )
    return await _recycle_deleted_number(
        db,
        counter_column=NumberingCounter.next_facture_number,
        deleted_reference=deleted_reference,
        remaining_refs=refs,
    )


async def resync_soumission_counter(
    db: AsyncSession, deleted_reference: Optional[str]
) -> Optional[int]:
    """Même recyclage pour les soumissions supprimées."""
    from app.models.soumission import Soumission

    refs = list(
        (await db.execute(select(Soumission.reference))).scalars().all()
    )
    return await _recycle_deleted_number(
        db,
        counter_column=NumberingCounter.next_soumission_number,
        deleted_reference=deleted_reference,
        remaining_refs=refs,
    )


async def resync_po_counter(db: AsyncSession) -> int:
    """Recale `next_po_number` sur (max numéro restant + 1).

    Appelé après suppression d'un PO pour recycler son numéro :
    si on supprime le dernier PO-0030, le prochain créé sera PO-0030.
    Si on supprime un PO « du milieu », le compteur reste à max+1
    et le numéro supprimé reste un trou (acceptable).
    """
    from app.models.purchase_order import PurchaseOrder

    rows = (
        await db.execute(select(PurchaseOrder.reference))
    ).scalars().all()
    max_num = 0
    for ref in rows:
        if not ref:
            continue
        # Format "PO-0027" → 27.
        tail = ref.split("-")[-1] if "-" in ref else ref
        try:
            n = int(tail)
        except ValueError:
            continue
        if n > max_num:
            max_num = n
    new_next = max_num + 1
    await _ensure_row(db)
    await db.execute(
        update(NumberingCounter)
        .where(NumberingCounter.id == 1)
        .values(next_po_number=new_next)
    )
    await db.flush()
    return new_next
