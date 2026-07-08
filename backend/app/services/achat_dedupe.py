"""Déduplication automatique des achats.

Cause des doublons : un achat saisi dans Kratos est poussé vers QB puis
RÉ-IMPORTÉ par un pull → 2e achat identique. Cas vu en prod : un achat
« à payer » (Sur compte) part en Bill QB ; une fois payé on lui met le
mode réel (Chèque) ; le pull QB ré-importe une version « Sur compte »
SANS fournisseur ni description → 2 lignes, même n° de référence, même
montant, mais ce n'est qu'UN document.

Cette dédup est appelée AUTOMATIQUEMENT à la fin de chaque synchro QB
(`pull_new_bills_from_qbo`, `pull_costs`) — pas de bouton manuel. Elle ne
regroupe que des achats reliés par un signal FORT (même transaction QB,
même n° de facture fournisseur, ou même référence + même montant TTC), et
l'achat conservé hérite du mode de paiement RÉEL (jamais « sur compte »
quand un paiement a été fait).
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.achat import Achat


log = logging.getLogger(__name__)


def _normalize_ref(v: str) -> str:
    """Référence « canonique » : segments alphanumériques, séparateurs
    retirés, zéros de tête retirés par segment.

    Rona émet le MÊME reçu sous deux formats de numéro : un format « long »
    compte-client magasin (segments zéro-paddés + suffixe type -01, ex.
    « 76190-01156054-01 ») et le numéro de RÉCEPTION compact
    (« 76190-11560541 »). Les deux se réduisent à la même clé :
        76190-01156054-01 → 76190 | 1156054 | 1 → « 7619011560541 »
        76190-11560541    → 76190 | 11560541     → « 7619011560541 »
    ce qui permet de les reconnaître comme un seul document."""
    parts = re.split(r"[^0-9a-z]+", (v or "").strip().lower())
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        out.append(p.lstrip("0") or "0")
    return "".join(out)


def _is_padded_ref(a: Achat) -> bool:
    """Vrai si la référence de l'achat est le format « long » zéro-paddé
    (compte-client magasin Rona) — celui à SUPPRIMER au profit du numéro de
    réception compact. Détecté par la présence d'un segment à zéro de tête
    (ex. « 01156054 »)."""
    for v in (a.supplier_invoice_number, a.qbo_doc_number, a.reference):
        for seg in re.split(r"[^0-9a-z]+", (v or "").strip().lower()):
            if len(seg) > 1 and seg[0] == "0":
                return True
    return False


def _keeper_score(a: Achat) -> tuple:
    """Plus haut = plus « riche » → à conserver. Règle voulue : on garde
    l'achat PAYÉ avec un VRAI mode de paiement (pas « sur compte ») et le
    PLUS d'information sur la ligne (fournisseur, description, taxes). On
    préserve aussi en priorité un achat déjà refacturé (facture_item)."""
    pm = (a.payment_method or "").strip()
    return (
        1 if a.facture_item_id is not None else 0,  # déjà refacturé → garder
        1 if a.invoiced_at is not None else 0,
        1 if a.status == "paid" else 0,             # payé > non payé
        1 if pm and pm != "bill_to_pay" else 0,     # vrai paiement > sur compte
        # Numéro de RÉCEPTION compact > format « long » zéro-paddé
        # (compte-client magasin) : à statut égal, on garde la réception.
        0 if _is_padded_ref(a) else 1,
        1 if a.fournisseur_id is not None else 0,
        1 if a.sous_traitant_id is not None else 0,
        1 if (a.description or "").strip() else 0,
        1 if float(a.amount_taxes or 0) > 0 else 0,  # vrai split HT/taxes
        1 if a.project_id is not None else 0,
        1 if a.has_receipt_image else 0,
        1 if a.qbo_bill_payment_id else 0,
        -a.id,  # tie-break : garder le plus ancien (id min)
    )


def _ttc(a: Achat) -> float:
    return round(float(a.amount or 0) + float(a.amount_taxes or 0), 2)


def _tokens(a: Achat) -> set[str]:
    """Identifiants « parlants » de l'achat (référence interne, n° de
    facture fournisseur, n° de doc QB), normalisés."""
    out: set[str] = set()
    for v in (a.reference, a.supplier_invoice_number, a.qbo_doc_number):
        t = (v or "").strip().lower()
        if t:
            out.add(t)
    return out


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _merge_into_keeper(keeper: Achat, other: Achat) -> None:
    """Recopie sur l'achat conservé les infos présentes sur le doublon
    supprimé mais absentes du gardé (lien QB, fournisseur, projet,
    description…), et reflète l'état de paiement le PLUS avancé — avec le
    mode de paiement RÉEL, jamais « sur compte » si un paiement a eu lieu."""
    # Lien QB : ne jamais perdre la transaction QuickBooks rattachée.
    if not keeper.qbo_bill_id and other.qbo_bill_id:
        keeper.qbo_bill_id = other.qbo_bill_id
        keeper.qbo_sync_token = other.qbo_sync_token
        keeper.qbo_doc_number = other.qbo_doc_number or keeper.qbo_doc_number
    if not keeper.qbo_purchase_id and other.qbo_purchase_id:
        keeper.qbo_purchase_id = other.qbo_purchase_id
    if not keeper.qbo_bill_payment_id and other.qbo_bill_payment_id:
        keeper.qbo_bill_payment_id = other.qbo_bill_payment_id
    # Champs descriptifs : compléter ce qui manque sur le gardé.
    if keeper.fournisseur_id is None and other.fournisseur_id is not None:
        keeper.fournisseur_id = other.fournisseur_id
    if keeper.sous_traitant_id is None and other.sous_traitant_id is not None:
        keeper.sous_traitant_id = other.sous_traitant_id
    if keeper.project_id is None and other.project_id is not None:
        keeper.project_id = other.project_id
    if not (keeper.description or "").strip() and (other.description or "").strip():
        keeper.description = other.description
    if not (keeper.supplier_invoice_number or "").strip() and (
        other.supplier_invoice_number or ""
    ).strip():
        keeper.supplier_invoice_number = other.supplier_invoice_number
    if keeper.invoice_date is None and other.invoice_date is not None:
        keeper.invoice_date = other.invoice_date
    if not (keeper.receipt_url or "").strip() and (other.receipt_url or "").strip():
        keeper.receipt_url = other.receipt_url
    # État de paiement : on garde le plus avancé. Si l'un des deux porte un
    # mode de paiement RÉEL (pas « sur compte »), c'est lui qui fait foi
    # (la facture a fini par être payée par chèque / carte).
    if other.status == "paid" and keeper.status != "paid":
        keeper.status = "paid"
    if keeper.paid_at is None and other.paid_at is not None:
        keeper.paid_at = other.paid_at
    other_pm = (other.payment_method or "").strip()
    keeper_pm = (keeper.payment_method or "").strip()
    if other_pm and other_pm != "bill_to_pay" and (
        not keeper_pm or keeper_pm == "bill_to_pay"
    ):
        keeper.payment_method = other.payment_method


async def dedupe_achats(db: AsyncSession) -> int:
    """Supprime les achats en double, en conservant le plus complet.

    Trois signaux de regroupement, tous SÛRS (fusionnés par union-find,
    donc transitifs) :
      1. Même transaction QuickBooks — un Id présent dans ``qbo_bill_id``
         OU ``qbo_purchase_id`` (un achat poussé stocke l'Id de la Purchase
         dans qbo_bill_id, pas qbo_purchase_id).
      2. Même (fournisseur, n° de facture fournisseur).
      3. Même RÉFÉRENCE (reference / n° facture fournisseur / n° doc QB) ET
         même montant TTC — couvre le doublon « Sur compte » ré-importé
         sans fournisseur : la réf et le montant suffisent à l'identifier.
      4. Même FOURNISSEUR + même RÉFÉRENCE NORMALISÉE (zéros de tête et
         séparateurs retirés) ET montant TTC proche (≤ 1 %). Couvre le
         reçu Rona entré deux fois sous deux formats de numéro (compte-
         client « long » vs réception « compact ») avec un écart d'arrondi
         d'un cent — invisible pour le signal 3 (réf + TTC EXACTS).

    Retourne le nombre d'achats supprimés. Ne committe pas (l'appelant
    gère la transaction).
    """
    achats = list((await db.execute(select(Achat))).scalars().all())

    uf = _UnionFind()
    # Index : clé de signal → premier achat vu portant cette clé. On unionne
    # chaque nouvel achat avec ce représentant.
    rep: dict[str, int] = {}
    # Index du signal 4 : clé (fournisseur+réf normalisée) → achat témoin.
    # On garde l'achat (pas juste l'id) pour comparer les montants avant de
    # fusionner — garde-fou contre deux reçus RÉELLEMENT distincts qui
    # partageraient une réf normalisée par hasard.
    nref_rep: dict[str, Achat] = {}

    def link(key: str, aid: int) -> None:
        if key in rep:
            uf.union(rep[key], aid)
        else:
            rep[key] = aid
            uf.find(aid)

    def _amounts_close(x: Achat, y: Achat) -> bool:
        tx, ty = _ttc(x), _ttc(y)
        return abs(tx - ty) <= max(0.05, 0.01 * max(tx, ty))

    for a in achats:
        uf.find(a.id)
        # 1) Transaction QB (cross-champ).
        for qid in (a.qbo_bill_id, a.qbo_purchase_id):
            if qid:
                link(f"qb:{qid}", a.id)
        # 2) Fournisseur + n° facture fournisseur.
        inv = (a.supplier_invoice_number or "").strip().lower()
        if inv and a.fournisseur_id:
            link(f"inv:{a.fournisseur_id}:{inv}", a.id)
        # 3) Référence + montant TTC (identique = même document).
        ttc = _ttc(a)
        if ttc > 0:
            for tok in _tokens(a):
                link(f"tok:{tok}|{ttc:.2f}", a.id)
        # 4) Fournisseur + référence NORMALISÉE + montant proche (Rona).
        if a.fournisseur_id and ttc > 0:
            for tok in _tokens(a):
                nref = _normalize_ref(tok)
                if len(nref) < 4:
                    continue  # trop court → risque de collision, on ignore
                key = f"nref:{a.fournisseur_id}:{nref}"
                witness = nref_rep.get(key)
                if witness is None:
                    nref_rep[key] = a
                elif _amounts_close(a, witness):
                    uf.union(witness.id, a.id)

    # Reconstruit les groupes à partir des composantes connexes.
    comps: dict[int, list[Achat]] = defaultdict(list)
    for a in achats:
        comps[uf.find(a.id)].append(a)

    # Client QB (best-effort) pour supprimer AUSSI l'objet QuickBooks du
    # doublon perdant — sinon la dépense/facture reste en double dans QB
    # même après le regroupement côté Kratos. Résolu une seule fois ; None
    # si QBO indisponible → on nettoie seulement Kratos.
    qbo = None
    try:
        from app.integrations.quickbooks import get_qbo

        _q = get_qbo()
        await _q._load_refresh_from_db()
        if _q.ready:
            qbo = _q
    except Exception:  # noqa: BLE001
        qbo = None

    async def _delete_qbo_object(qid: str) -> None:
        """Supprime l'objet QB perdant (Purchase OU Bill). QB refuse de
        supprimer un objet rapproché/verrouillé (renvoie False) → garde-fou
        intégré. Best-effort, journalisé."""
        if not qbo or not qid:
            return
        try:
            ok = await qbo.delete_purchase(qid) or await qbo.delete_bill(qid)
            if ok:
                log.info("dedupe_achats: objet QB doublon %s supprimé", qid)
            else:
                log.warning(
                    "dedupe_achats: objet QB doublon %s non supprimé "
                    "(verrouillé/rapproché ou déjà absent)",
                    qid,
                )
        except Exception:  # noqa: BLE001
            log.warning(
                "dedupe_achats: échec suppression objet QB %s",
                qid, exc_info=True,
            )

    removed = 0
    for members in comps.values():
        if len(members) < 2:
            continue
        keeper = max(members, key=_keeper_score)
        for a in members:
            if a.id == keeper.id:
                continue
            # Id(s) QB du perdant, AVANT merge (le merge peut en transférer
            # au gardé s'il n'en a pas — dans ce cas on ne les supprime pas).
            loser_qids = {
                str(a.qbo_bill_id or ""),
                str(a.qbo_purchase_id or ""),
            }
            _merge_into_keeper(keeper, a)
            keeper_qids = {
                str(keeper.qbo_bill_id or ""),
                str(keeper.qbo_purchase_id or ""),
            }
            # On ne supprime dans QB que les objets du perdant que le gardé
            # n'a PAS adoptés (sinon on effacerait la transaction conservée).
            for qid in loser_qids:
                if qid and qid not in keeper_qids:
                    await _delete_qbo_object(qid)
            await db.delete(a)
            removed += 1
    if removed:
        await db.flush()
        log.info("dedupe_achats: %d doublon(s) supprimé(s)", removed)
    return removed
