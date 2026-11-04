"""Reçu d'un achat → pièce jointe (Attachable) de sa transaction QuickBooks.

Règle (Steven, 2026-11-04 — A-520, A-462, #539) : « le PDF devrait
toujours se joindre dans les pièces jointes quand ça part de Kratos et
qu'il est présent ». Avant, la pièce ne partait QU'à la création de la
transaction QB (``did_create``). Or l'achat part dans QB dès sa
sauvegarde (auto-push) et le PDF arrive par un second envoi quelques
secondes plus tard (``POST /achats/{id}/receipt``) qui ne déclenchait
rien côté QB ; les re-synchros suivantes ne joignaient plus → jamais de
pièce dans QuickBooks.

Un seul garde-fou : ``Achat.qbo_attachable_id`` = Id de l'Attachable QB
qui porte le reçu (toutes les parts d'un reçu divisé le partagent).
- NULL + reçu présent + transaction QB liée → à joindre ;
- posé → déjà dans QB, on ne téléverse pas une 2ᵉ fois.
Anti-doublon pour les achats d'avant la colonne (pièce jointe à la
création) et les reçus déposés directement dans QB puis importés : avant
de téléverser sur une transaction QB existante, on relit ses Attachables ;
s'il y en a déjà un (image / PDF), on s'y RELIE au lieu de téléverser.

Trois chemins appellent ``joindre_recu`` :
1. la synchro (``services/achat_qbo.py``) — création OU mise à jour ;
2. l'arrivée, le remplacement ou la rotation du reçu dans Kratos
   (``endpoints/achat_receipt.py`` → ``joindre_recu_en_fond``) ; un
   remplacement téléverse la nouvelle version et retire l'ancienne ;
3. le filet horaire ``rattraper_pieces_qbo`` (``qbo_nets``) qui rattrape
   les achats liés à QB avec un reçu et sans pièce — dont tout le stock
   existant au déploiement.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.quickbooks import QuickBooksError, get_qbo
from app.models.achat import Achat

log = logging.getLogger(__name__)

#: Valeur posée quand QB a accepté le téléversement sans renvoyer d'Id
#: lisible : la pièce est dans QB, on ne doit pas la renvoyer.
ID_INCONNU = "inconnu"


# ── Attachables QB ────────────────────────────────────────────────────


def _refs(att: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(type, id) des transactions qu'un Attachable QB accompagne."""
    out: List[Tuple[str, str]] = []
    for ref in att.get("AttachableRef") or []:
        ent = ref.get("EntityRef") or {}
        t = str(ent.get("type") or "").lower()
        v = str(ent.get("value") or "")
        if t and v:
            out.append((t, v))
    return out


async def lister_attachables(qbo: Any) -> List[Dict[str, Any]]:
    """Tous les Attachables de la compagnie (paginé quand le client le
    permet). ``[]`` si QuickBooks ne répond pas — on téléverse alors
    plutôt que de laisser la pièce manquer."""
    lire = getattr(qbo, "query_all", None)
    try:
        if lire is not None:
            return list(await lire("SELECT * FROM attachable"))
        return list(await qbo.list_attachables())
    except QuickBooksError:
        return []
    except Exception:  # noqa: BLE001
        log.warning("Lecture des Attachables QB échouée", exc_info=True)
        return []


def index_attachables(
    atts: Iterable[Dict[str, Any]],
) -> Dict[Tuple[str, str], List[str]]:
    """(type, id de transaction) → Ids des Attachables image / PDF."""
    from app.services.qbo_cost_pull import _attachable_ctype

    idx: Dict[Tuple[str, str], List[str]] = {}
    for att in atts:
        aid = str(att.get("Id") or "")
        if not aid or _attachable_ctype(att) is None:
            continue
        for cle in _refs(att):
            idx.setdefault(cle, []).append(aid)
    return idx


def _id_attachable(reponse: Any) -> Optional[str]:
    """Id de l'Attachable créé, d'après la réponse de /upload."""
    if not isinstance(reponse, dict):
        return None
    for item in reponse.get("AttachableResponse") or []:
        att = (item or {}).get("Attachable") or {}
        if att.get("Id"):
            return str(att["Id"])
    att = reponse.get("Attachable") or {}
    return str(att["Id"]) if att.get("Id") else None


def _poser(parts: Sequence[Achat], attachable_id: Optional[str]) -> None:
    for p in parts:
        p.qbo_attachable_id = attachable_id


# ── Transaction QB d'un achat ─────────────────────────────────────────


async def transaction_qb(
    qbo: Any, achat: Achat
) -> Optional[Tuple[str, str]]:
    """(« Bill » | « Purchase », Id QB) de la transaction qui porte
    l'achat, ou None s'il n'est pas (encore) dans QuickBooks.
    ``qbo_bill_id`` peut pointer un Bill OU une Purchase (achat poussé
    depuis Kratos) : on devine par le mode de paiement puis on vérifie
    auprès de QB ; ``qbo_purchase_id`` (dépense importée) est une
    Purchase."""
    from app.services.achat_qbo import PAID_METHODS

    if achat.qbo_purchase_id:
        return ("Purchase", str(achat.qbo_purchase_id))
    qid = str(achat.qbo_bill_id or "").strip()
    if not qid:
        return None
    ordre = (
        ("Purchase", "Bill")
        if achat.payment_method in PAID_METHODS
        else ("Bill", "Purchase")
    )
    for t in ordre:
        try:
            if t == "Bill":
                await qbo.get_bill(qid)
            else:
                await qbo.get_purchase(qid)
            return (t, qid)
        except Exception:  # noqa: BLE001
            continue
    return None


# ── Joindre ───────────────────────────────────────────────────────────


async def joindre_recu(
    db: AsyncSession,
    qbo: Any,
    parts: Sequence[Achat],
    *,
    type_qb: str,
    id_qb: str,
    forcer: bool = False,
    index: Optional[Dict[Tuple[str, str], List[str]]] = None,
) -> Dict[str, Any]:
    """Joint le reçu des ``parts`` (un reçu divisé = UNE pièce, portée par
    la première part qui l'a) à la transaction QB ``(type_qb, id_qb)``.

    ``forcer`` téléverse sans regarder ce que QB porte déjà : création de
    la transaction, remplacement du reçu. Sinon : déjà joint
    (``qbo_attachable_id``) → rien ; QB a déjà une pièce image / PDF sur
    la transaction → on s'y relie ; sinon on téléverse.

    Retour : ``statut`` ∈ sans_recu | deja | relie | joint | erreur,
    ``attachable_id``, ``erreur``.
    """
    porteur = next((p for p in parts if p.receipt_image_content_type), None)
    if porteur is None:
        return {"statut": "sans_recu", "attachable_id": None, "erreur": None}

    if not forcer:
        deja = next(
            (str(p.qbo_attachable_id) for p in parts if p.qbo_attachable_id),
            None,
        )
        if deja:
            _poser(parts, deja)
            return {"statut": "deja", "attachable_id": deja, "erreur": None}
        if index is None:
            index = index_attachables(await lister_attachables(qbo))
        existants = index.get((type_qb.lower(), str(id_qb))) or []
        if existants:
            _poser(parts, existants[0])
            log.info(
                "Achat %s : QB %s %s porte déjà la pièce %s → reliée",
                parts[0].id, type_qb, id_qb, existants[0],
            )
            return {
                "statut": "relie",
                "attachable_id": existants[0],
                "erreur": None,
            }

    # `receipt_image` est une colonne deferred : y accéder sans l'avoir
    # chargée déclenche un SELECT implicite, interdit sur une
    # AsyncSession (MissingGreenlet). On ne la lit qu'après un refresh.
    try:
        await db.refresh(porteur, attribute_names=["receipt_image"])
        contenu = bytes(porteur.receipt_image) if porteur.receipt_image else None
    except Exception as exc:  # noqa: BLE001
        log.warning("Refresh receipt_image failed: %s", exc)
        return {
            "statut": "erreur",
            "attachable_id": None,
            "erreur": f"refresh: {exc}"[:200],
        }
    if not contenu:
        return {"statut": "sans_recu", "attachable_id": None, "erreur": None}

    ctype = porteur.receipt_image_content_type or "application/octet-stream"
    ext = "pdf" if "pdf" in ctype else ("png" if "png" in ctype else "jpg")
    nom = f"facture-A{parts[0].id}.{ext}"
    try:
        reponse = await qbo.upload_attachment(
            entity_type=type_qb,
            entity_id=str(id_qb),
            file_name=nom,
            content_type=ctype,
            content=contenu,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Receipt upload failed for Achat %s -> QBO %s %s: %s",
            parts[0].id, type_qb, id_qb, exc,
        )
        return {
            "statut": "erreur",
            "attachable_id": None,
            "erreur": str(exc)[:200],
        }
    aid = _id_attachable(reponse) or ID_INCONNU
    _poser(parts, aid)
    log.info(
        "Attached receipt to QBO %s %s (file=%s, attachable=%s)",
        type_qb, id_qb, nom, aid,
    )
    return {"statut": "joint", "attachable_id": aid, "erreur": None}


async def joindre_recu_achat(
    db: AsyncSession,
    qbo: Any,
    achat_id: int,
    *,
    forcer: bool = False,
    retirer: Optional[str] = None,
    index: Optional[Dict[Tuple[str, str], List[str]]] = None,
) -> Dict[str, Any]:
    """Chemin autonome (reçu arrivé après la synchro, filet, bouton) :
    charge l'achat et ses parts, retrouve sa transaction QB et joint.
    ``retirer`` : ancienne pièce QB à enlever après un remplacement
    réussi (best-effort)."""
    from app.services.achat_divise import parts_du_groupe

    achat = (
        await db.execute(select(Achat).where(Achat.id == achat_id))
    ).scalar_one_or_none()
    if achat is None:
        return {"statut": "introuvable", "attachable_id": None, "erreur": None}
    parts = await parts_du_groupe(db, achat)
    if not parts:
        return {
            "statut": "sans_transaction",
            "attachable_id": None,
            "erreur": None,
        }
    txn = await transaction_qb(qbo, parts[0])
    if txn is None:
        return {
            "statut": "sans_transaction",
            "attachable_id": None,
            "erreur": None,
        }
    res = await joindre_recu(
        db, qbo, parts, type_qb=txn[0], id_qb=txn[1], forcer=forcer, index=index
    )
    if (
        retirer
        and retirer != ID_INCONNU
        and res["statut"] == "joint"
        and res["attachable_id"] != retirer
    ):
        await retirer_piece_qb(qbo, retirer)
    return res


async def joindre_maintenant(db: AsyncSession, achat_id: int) -> Dict[str, Any]:
    """Bouton / API « joindre maintenant » : même travail que la tâche de
    fond, dans la requête. Lève ``AchatSyncError`` si QB n'est pas prêt."""
    from app.services.achat_qbo import AchatSyncError

    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not getattr(qbo, "ready", False):
        raise AchatSyncError(
            "QuickBooks n'est pas configuré (client id / secret / "
            "refresh token / realm)."
        )
    return await joindre_recu_achat(db, qbo, achat_id)


async def retirer_piece_qb(qbo: Any, attachable_id: Optional[str]) -> bool:
    """Enlève une pièce de QuickBooks (best-effort, jamais bloquant)."""
    if not attachable_id or attachable_id == ID_INCONNU:
        return False
    try:
        return bool(await qbo.delete_attachable(str(attachable_id)))
    except Exception:  # noqa: BLE001
        log.warning(
            "Retrait de la pièce QB %s échoué", attachable_id, exc_info=True
        )
        return False


# ── Tâches de fond (après l'arrivée / le retrait du reçu dans Kratos) ──


async def joindre_recu_en_fond(
    achat_id: int,
    *,
    retirer: Optional[str] = None,
    forcer: bool = False,
    essais: int = 8,
    pause: float = 3.0,
) -> Optional[Dict[str, Any]]:
    """Après l'arrivée du reçu dans Kratos. L'achat vient souvent d'être
    créé et son auto-push QB est peut-être encore en cours : on attend
    la transaction QB quelques fois (sous le même verrou que la synchro)
    avant d'abandonner — le filet horaire rattrape de toute façon."""
    from app.db.session import AsyncSessionLocal
    from app.services.achat_qbo import verrou_achat

    qbo = get_qbo()
    try:
        await qbo._load_refresh_from_db()
    except Exception:  # noqa: BLE001
        log.warning("QBO indisponible pour joindre le reçu %s", achat_id)
        return None
    if not getattr(qbo, "ready", False):
        return None
    for essai in range(max(1, essais)):
        try:
            async with AsyncSessionLocal() as db:
                row = (
                    await db.execute(
                        select(
                            Achat.id,
                            Achat.groupe_id,
                            Achat.receipt_image_content_type,
                            Achat.qbo_bill_id,
                            Achat.qbo_purchase_id,
                        ).where(Achat.id == achat_id)
                    )
                ).first()
                if row is None:
                    return None  # achat supprimé entre-temps
                if row[2] and (row[3] or row[4]):
                    async with verrou_achat(int(row[0]), row[1]):
                        res = await joindre_recu_achat(
                            db, qbo, achat_id, forcer=forcer, retirer=retirer
                        )
                        await db.commit()
                    log.info(
                        "Achat %s : reçu → QB (%s)", achat_id, res.get("statut")
                    )
                    return res
        except Exception:  # noqa: BLE001
            log.warning(
                "Achat %s : jonction du reçu à QB échouée (essai %d)",
                achat_id, essai + 1, exc_info=True,
            )
        if essai < essais - 1:
            await asyncio.sleep(pause)
    log.info(
        "Achat %s : reçu non joint à QB (pas encore de transaction QB) — "
        "le filet horaire s'en charge",
        achat_id,
    )
    return None


async def retirer_piece_qb_en_fond(attachable_id: Optional[str]) -> None:
    """Après la suppression du reçu dans Kratos : la pièce quitte aussi
    la transaction QB (Kratos est la source du reçu)."""
    if not attachable_id or attachable_id == ID_INCONNU:
        return
    qbo = get_qbo()
    try:
        await qbo._load_refresh_from_db()
    except Exception:  # noqa: BLE001
        return
    if not getattr(qbo, "ready", False):
        return
    await retirer_piece_qb(qbo, attachable_id)


# ── Filet horaire / rattrapage ────────────────────────────────────────


async def rattraper_pieces_qbo(*, limit: int = 100) -> Dict[str, Any]:
    """Achats liés à QB, avec reçu, sans pièce connue → relie (QB l'a
    déjà) ou téléverse. Une session par achat : un échec n'annule pas les
    autres. Couvre le stock existant au déploiement (pièces jointes à la
    création avant la colonne → reliées, jamais doublées)."""
    from app.db.session import AsyncSessionLocal
    from app.services.achat_divise import premieres_parts

    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not getattr(qbo, "ready", False):
        return {"skipped": "qbo_not_ready"}

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Achat.id, Achat.groupe_id)
                .where(
                    Achat.receipt_image_content_type.is_not(None),
                    Achat.qbo_attachable_id.is_(None),
                    or_(
                        Achat.qbo_bill_id.is_not(None),
                        Achat.qbo_purchase_id.is_not(None),
                    ),
                    Achat.status.in_(("received", "paid")),
                )
                .order_by(Achat.id.desc())
                .limit(max(1, int(limit)))
            )
        ).all()
    ids = premieres_parts((int(r[0]), r[1]) for r in rows)
    out: Dict[str, Any] = {
        "candidats": len(ids),
        "joints": 0,
        "relies": 0,
        "deja": 0,
        "sans_transaction": 0,
        "erreurs": 0,
    }
    if not ids:
        return out

    index = index_attachables(await lister_attachables(qbo))
    for aid in ids:
        try:
            async with AsyncSessionLocal() as s:
                res = await joindre_recu_achat(s, qbo, aid, index=index)
                await s.commit()
            statut = str(res.get("statut") or "")
            if statut == "joint":
                out["joints"] += 1
            elif statut == "relie":
                out["relies"] += 1
            elif statut == "deja":
                out["deja"] += 1
            elif statut in ("sans_transaction", "introuvable", "sans_recu"):
                out["sans_transaction"] += 1
            else:
                out["erreurs"] += 1
                log.warning(
                    "Achat %s : pièce non jointe à QB (%s)",
                    aid, res.get("erreur"),
                )
        except Exception:  # noqa: BLE001
            out["erreurs"] += 1
            log.warning("Achat %s : rattrapage de la pièce QB échoué", aid, exc_info=True)
    return out
