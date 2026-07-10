"""Import QB → Kratos des coûts d'un projet (Bills + Purchases).

RÈGLE : on n'importe un coût QuickBooks (facture fournisseur « Bill » à
payer, ou dépense « Purchase » cash/chèque/CC) QUE s'il est rattaché à un
PROJET — c.-à-d. qu'une de ses lignes a un `CustomerRef` pointant vers le
sous-client (Job) d'un projet Kratos (`Project.qbo_job_id`). Sinon il est
ignoré. Idempotent : dédup par `qbo_bill_id` / `qbo_purchase_id`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.achat import Achat
from app.models.fournisseur import Fournisseur
from app.models.project import Project
from app.models.soumission import Soumission

log = logging.getLogger(__name__)

# Taille maximale d'un reçu importé depuis QB (aligne la limite d'upload
# Kratos). Extensions acceptées quand QB ne fournit pas de ContentType.
_MAX_RECEIPT_BYTES = 15 * 1024 * 1024
_RECEIPT_EXT_CTYPE = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
}


def _attachable_ctype(att: dict) -> Optional[str]:
    """Content-type d'un Attachable QB : champ ContentType, sinon déduit de
    l'extension du FileName. None si ce n'est pas un reçu (image/PDF)."""
    ctype = (att.get("ContentType") or "").lower().strip()
    if ctype.startswith("image/") or ctype == "application/pdf":
        return ctype
    name = (att.get("FileName") or "").lower()
    for ext, mapped in _RECEIPT_EXT_CTYPE.items():
        if name.endswith(ext):
            return mapped
    return None


async def _import_qbo_receipts(db: AsyncSession, qbo: Any) -> int:
    """Importe dans Kratos les reçus (pièces jointes image/PDF) déposés sur
    les dépenses / factures fournisseurs QB liées à un achat qui n'a PAS
    encore de reçu. N'écrase jamais un reçu existant. Retourne le nombre de
    reçus importés."""
    # Candidats relus depuis la DB (et non depuis les index construits en
    # début de run) : couvre AUSSI les achats importés dans CE passage —
    # sinon leur reçu n'arrivait qu'au passage suivant. `qbo_bill_id` peut
    # pointer un Bill OU une Purchase (achat poussé depuis Kratos) → on
    # l'inscrit sous les deux types.
    rows = (
        await db.execute(
            select(Achat).where(
                (
                    Achat.qbo_bill_id.is_not(None)
                    | Achat.qbo_purchase_id.is_not(None)
                ),
                Achat.receipt_image_content_type.is_(None),
            )
        )
    ).scalars().all()
    candidates: dict[tuple[str, str], Achat] = {}
    for a in rows:
        if a.qbo_bill_id:
            candidates[("bill", str(a.qbo_bill_id))] = a
            candidates[("purchase", str(a.qbo_bill_id))] = a
        if a.qbo_purchase_id:
            candidates.setdefault(("purchase", str(a.qbo_purchase_id)), a)
    if not candidates:
        return 0

    attachables = await qbo.list_attachables()
    if not attachables:
        return 0

    imported = 0
    done: set[int] = set()
    for att in attachables:
        att_id = str(att.get("Id") or "")
        if not att_id:
            continue
        ctype = _attachable_ctype(att)
        if ctype is None:
            continue
        for ref in att.get("AttachableRef") or []:
            ent = ref.get("EntityRef") or {}
            key = (
                str(ent.get("type") or "").lower(),
                str(ent.get("value") or ""),
            )
            achat = candidates.get(key)
            if achat is None or achat.id in done:
                continue
            content = await qbo.download_attachable(att_id)
            if not content or len(content) > _MAX_RECEIPT_BYTES:
                continue
            achat.receipt_image = content
            achat.receipt_image_content_type = ctype
            done.add(achat.id)
            imported += 1
            log.info(
                "Reçu QB %s (%s) importé sur achat %s",
                att_id,
                att.get("FileName") or ctype,
                achat.id,
            )
    if imported:
        await db.flush()
    return imported


async def _fournisseur_id_for(
    db: AsyncSession,
    fourn_by_name: dict[str, int],
    vendor_name: Optional[str],
    vendor_qbo_id: Optional[str] = None,
) -> Optional[int]:
    """Id du Fournisseur Kratos pour un vendor QB — CRÉÉ s'il n'existe pas
    (le fournisseur travaille sur un projet Kratos, il doit exister dans
    Kratos ; avant, l'achat importé restait avec « Aucun » fournisseur)."""
    key = (vendor_name or "").strip().lower()
    if not key:
        return None
    fid = fourn_by_name.get(key)
    if fid:
        return fid
    f = Fournisseur(
        name=(vendor_name or "").strip()[:255],
        qbo_vendor_id=str(vendor_qbo_id) if vendor_qbo_id else None,
        active=True,
    )
    db.add(f)
    await db.flush()
    fourn_by_name[key] = int(f.id)
    log.info("Fournisseur créé depuis QB : %s (#%s)", f.name, f.id)
    return int(f.id)


def _txn_description(txn: dict) -> Optional[str]:
    """Description lisible d'un Bill/Purchase QB : description de la
    première ligne de dépense, sinon le mémo privé."""
    for line in txn.get("Line") or []:
        if line.get("DetailType") == "AccountBasedExpenseLineDetail":
            d = line.get("Description")
            if d:
                return str(d)[:1000]
    note = txn.get("PrivateNote")
    return str(note)[:1000] if note else None


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(s: Any) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _project_for_txn(
    txn: dict, proj_by_job: dict[str, Project]
) -> Optional[Project]:
    for line in txn.get("Line") or []:
        for key in (
            "AccountBasedExpenseLineDetail",
            "ItemBasedExpenseLineDetail",
        ):
            d = line.get(key) or {}
            cref = (d.get("CustomerRef") or {}).get("value")
            if cref and str(cref) in proj_by_job:
                return proj_by_job[str(cref)]
    return None


def _txn_customer_refs(txn: dict) -> set[str]:
    """Tous les CustomerRef présents sur les lignes (pour savoir si une
    dépense touche un client donné)."""
    out: set[str] = set()
    for line in txn.get("Line") or []:
        for key in (
            "AccountBasedExpenseLineDetail",
            "ItemBasedExpenseLineDetail",
        ):
            d = line.get(key) or {}
            cref = (d.get("CustomerRef") or {}).get("value")
            if cref:
                out.add(str(cref))
    return out


def _local_name_of(row: dict) -> str:
    fqn = row.get("FullyQualifiedName") or ""
    seg = fqn.split(":")[-1] if fqn else (row.get("DisplayName") or "")
    return seg.strip().lower()


async def _resolve_converted_job_id(
    qbo, project: Project, parent_id: str, active_ids: Optional[set[str]]
) -> Optional[str]:
    """Si `project.qbo_job_id` est PÉRIMÉ (sous-client converti en PROJET
    dans QB, ancien id supprimé), retrouve le nouvel id sous le client
    parent par nom/adresse. Ne CRÉE rien et ne retombe PAS sur le parent
    (contrairement à resolve_project_customer_id, trop lourd/side-effect
    pour un pull en lecture). Renvoie None si rien de sûr — l'appelant
    garde alors l'id existant.

    `active_ids` = ensemble des Customer.Id ACTIFS (résolu une fois) pour
    éviter une requête QB par projet ; None = on ne sait pas → on ne
    répare pas (prudent)."""
    jid = (getattr(project, "qbo_job_id", None) or "").strip()
    if not jid or active_ids is None:
        return None
    if jid in active_ids:
        return None  # encore valide → rien à réparer
    try:
        subs = await qbo.find_subcustomers(parent_id)
    except Exception:  # noqa: BLE001
        return None
    targets = [
        t
        for t in (
            (getattr(project, "address", None) or "").strip().lower(),
            (project.name or "").strip().lower(),
        )
        if t
    ]
    for row in subs:
        if not row.get("Id"):
            continue
        ln = _local_name_of(row)
        if not ln:
            continue
        for t in targets:
            if (
                ln == t
                or ln.startswith(t)
                or t.startswith(ln)
                or t in ln
                or ln in t
            ):
                return str(row["Id"])
    usable = [r for r in subs if r.get("Id")]
    if len(usable) == 1:
        return str(usable[0]["Id"])
    return None


async def pull_project_costs_from_qbo(
    db: AsyncSession,
    *,
    since_days: int = 180,
    dry_run: bool = False,
    client_id: Optional[int] = None,
) -> dict:
    from app.integrations.quickbooks import QuickBooksError, get_qbo

    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        return {"error": "QuickBooks non connecté (OAuth)."}

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=since_days)
    ).strftime("%Y-%m-%d")
    try:
        bills = await qbo.query(
            f"SELECT * FROM Bill WHERE TxnDate >= '{cutoff}' "
            "ORDER BY TxnDate DESC MAXRESULTS 1000"
        )
        purchases = await qbo.query(
            f"SELECT * FROM Purchase WHERE TxnDate >= '{cutoff}' "
            "ORDER BY TxnDate DESC MAXRESULTS 1000"
        )
    except QuickBooksError as exc:
        return {"error": f"Requête QB échouée : {exc}"}

    # Mode de paiement réel des Bills payés (chèque / carte) déduit des
    # BillPayments QB → on ne laisse jamais un Bill payé en « Sur compte ».
    try:
        from app.services.qbo_payment_classify import (
            build_paid_bill_method_index,
        )

        paid_bill_methods = await build_paid_bill_method_index(qbo, db)
    except Exception:  # noqa: BLE001
        paid_bill_methods = {}

    # Achats déjà liés par qbo_bill_id (objet complet → on peut refléter
    # le PAIEMENT QB → Kratos sur un Bill déjà importé).
    existing_bill: dict[str, Achat] = {
        str(a.qbo_bill_id): a
        for a in (
            await db.execute(
                select(Achat).where(Achat.qbo_bill_id.is_not(None))
            )
        ).scalars().all()
    }
    existing_purchase: dict[str, Achat] = {
        str(a.qbo_purchase_id): a
        for a in (
            await db.execute(
                select(Achat).where(Achat.qbo_purchase_id.is_not(None))
            )
        ).scalars().all()
    }
    # Compte de paiement QB (Id) → mode de paiement Horizon exact
    # (cc_olivier, cheque_horizon…). Sert à refléter le rapprochement : quand
    # une dépense est rapprochée dans QB, on remonte la carte/compte réel.
    try:
        from app.services.qbo_payment_classify import _account_id_to_method

        purchase_acct_methods = await _account_id_to_method(qbo, db)
    except Exception:  # noqa: BLE001
        purchase_acct_methods = {}
    pstmt = select(Project).where(Project.qbo_job_id.is_not(None))
    if client_id is not None:
        pstmt = pstmt.where(Project.client_id == client_id)
    _projects = list((await db.execute(pstmt)).scalars().all())
    proj_by_job: dict[str, Project] = {
        str(p.qbo_job_id): p for p in _projects
    }

    # RÉPARATION des qbo_job_id PÉRIMÉS (sous-client converti en projet QB) :
    # sans ça, les coûts du projet converti pointent vers le nouvel id, que
    # proj_by_job ne connaît pas → « sans projet », jamais importés (cas
    # 8900 St-Hubert). On résout une fois l'ensemble des Customer.Id actifs,
    # puis pour chaque projet dont l'id est périmé on retrouve le nouvel id
    # sous le client parent (par nom/adresse). Best-effort, borné.
    active_ids: Optional[set[str]] = None
    try:
        active_ids = {
            str(c["Id"])
            for c in await qbo.query(
                "SELECT Id FROM Customer MAXRESULTS 1000"
            )
            if c.get("Id")
        }
    except Exception:  # noqa: BLE001
        active_ids = None
    if active_ids is not None and _projects:
        from app.models.client import Client as _ClientM

        _cids = {p.client_id for p in _projects if p.client_id}
        _parents = (
            {
                c.id: c
                for c in (
                    await db.execute(
                        select(_ClientM).where(_ClientM.id.in_(_cids))
                    )
                ).scalars().all()
            }
            if _cids
            else {}
        )
        _resolved: dict[int, str] = {}
        _repaired = 0
        for p in _projects:
            cur = str(p.qbo_job_id or "")
            cl = _parents.get(p.client_id) if p.client_id else None
            parent = (getattr(cl, "qbo_customer_id", None) or "") if cl else ""
            newid = None
            if parent:
                try:
                    newid = await _resolve_converted_job_id(
                        qbo, p, str(parent), active_ids
                    )
                except Exception:  # noqa: BLE001
                    newid = None
            if newid and newid != cur:
                _repaired += 1
                if not dry_run:
                    p.qbo_job_id = newid
                _resolved[p.id] = newid
            elif cur:
                _resolved[p.id] = cur
        if _repaired and not dry_run:
            await db.flush()
        # Reconstruit le mapping avec les ids réparés (couvre le converti).
        proj_by_job = {
            _resolved[p.id]: p for p in _projects if _resolved.get(p.id)
        }
    # Refs QB du client (parent + sous-clients) : ne garder que ses
    # dépenses dans l'aperçu détaillé scopé.
    client_refs: Optional[set[str]] = None
    if client_id is not None:
        from app.models.client import Client

        client = (
            await db.execute(select(Client).where(Client.id == client_id))
        ).scalar_one_or_none()
        client_refs = set(proj_by_job.keys())
        if client and client.qbo_customer_id:
            client_refs.add(str(client.qbo_customer_id))
    fourn_by_name: dict[str, int] = {
        (n or "").strip().lower(): i
        for i, n in (
            await db.execute(select(Fournisseur.id, Fournisseur.name))
        ).all()
    }
    # Type de facturation par soumission → défaut « refacturable » des coûts
    # importés. Un CONTRAT (kind=contract, prix coûtant majoré) ou un devis
    # ESTIMÉ → refacturable. Forfaitaire ou inconnu → non refacturable.
    # (Vaut seulement à l'import QB → Kratos.)
    soum_ids = {
        p.soumission_id
        for p in proj_by_job.values()
        if p.soumission_id
    }
    billing_by_soum: dict[int, str] = {}
    if soum_ids:
        for sid, kind, pk in (
            await db.execute(
                select(
                    Soumission.id,
                    Soumission.kind,
                    Soumission.pricing_kind,
                ).where(Soumission.id.in_(soum_ids))
            )
        ).all():
            # Aligné sur _billing_kind (endpoints/projects.py) : contrat
            # l'emporte, sinon le pricing_kind.
            billing_by_soum[sid] = (
                "contrat" if kind == "contract" else (pk or "forfaitaire")
            )

    def _is_billable(proj: Project) -> bool:
        bk = (
            billing_by_soum.get(proj.soumission_id)
            if proj.soumission_id
            else None
        )
        # Refacturable par défaut UNIQUEMENT pour un CONTRAT (prix coûtant
        # majoré). ESTIMÉ et FORFAITAIRE → NON refacturable : le prix donné
        # au client couvre les dépenses, on ne les refacture pas par défaut
        # (cochable à la main au besoin).
        return bk == "contrat"

    now = datetime.now(timezone.utc)
    stats = {
        "dry_run": dry_run,
        "scope": "client" if client_id is not None else "all",
        "total_qbo": len(bills) + len(purchases),
        "bills_imported": 0,
        "purchases_imported": 0,
        "skipped_existing": 0,
        "skipped_no_project": 0,
        "paid_synced": 0,
        "reconciled_synced": 0,
    }
    preview: list[dict] = []

    # ── Bills (factures fournisseurs à payer) ──
    for b in bills:
        bid = str(b.get("Id") or "")
        if not bid:
            continue
        # Scope client : ne garder que les dépenses qui touchent une de
        # ses refs QB (parent / sous-clients).
        if client_refs is not None and _txn_customer_refs(b).isdisjoint(
            client_refs
        ):
            continue
        total = _num(b.get("TotalAmt"))
        balance = _num(b.get("Balance"))
        paid = balance == 0
        vendor = (b.get("VendorRef") or {}).get("name")
        doc = str(b.get("DocNumber") or "")
        if bid in existing_purchase and bid not in existing_bill:
            # Garde symétrique : déjà présent via `qbo_purchase_id`.
            stats["skipped_existing"] += 1
            preview.append(
                {"type": "bill", "qbo_id": bid, "amount": total,
                 "vendor": vendor, "status": "deja_importe"}
            )
            continue
        if bid in existing_bill:
            # Déjà importé → on reflète le PAIEMENT QB (Bill soldé) ET les
            # MODIFICATIONS faites dans QB (montant, description).
            ach = existing_bill[bid]
            updated = False
            # Fournisseur : backfill s'il manque, ET reflet d'un CHANGEMENT
            # de fournisseur fait dans QB (avant, seul le backfill existait —
            # changer le fournisseur d'une facture dans QB ne se voyait pas).
            if not dry_run and vendor:
                _fid = await _fournisseur_id_for(
                    db,
                    fourn_by_name,
                    vendor,
                    (b.get("VendorRef") or {}).get("value"),
                )
                if _fid and ach.fournisseur_id != _fid:
                    ach.fournisseur_id = _fid
                    updated = True
                    await db.flush()
            # Date de facture : reflète un changement de TxnDate fait dans QB
            # (la branche Purchase le faisait déjà, pas celle des Bills).
            _new_date = _parse_date(b.get("TxnDate"))
            if not dry_run and _new_date and _new_date != ach.invoice_date:
                ach.invoice_date = _new_date
                updated = True
            # Reflète les MODIFS faites dans QB (montant / description) sur un
            # coût ORIGINAIRE de QB — stocké en TTC, SANS ventilation de taxe
            # côté Kratos (amount_taxes == 0). On ne touche PAS un achat
            # « maître Kratos » (amount = HT + amount_taxes) pour ne pas
            # écraser sa ventilation. Corrige : « une facture à payer / un
            # reçu modifié dans QB ne se met pas à jour dans les dépenses ».
            if not dry_run and float(ach.amount_taxes or 0) == 0:
                new_desc = _txn_description(b)
                if total and round(float(ach.amount or 0), 2) != round(
                    float(total), 2
                ):
                    ach.amount = total
                    updated = True
                if new_desc and (ach.description or "") != new_desc:
                    ach.description = new_desc
                    updated = True
                if updated:
                    await db.flush()
            # RÉAFFECTATION DE PROJET : l'utilisateur a imputé (ou ré-imputé)
            # cette facture à un projet dans QB (CustomerRef de ligne) APRÈS
            # son import → on reflète le project_id sur l'achat existant,
            # sinon elle n'apparaît jamais dans les dépenses du projet (cas
            # 8900 : facture déjà dans Kratos sans projet, imputée ensuite
            # dans QB). On n'EFFACE jamais un projet (une facture QB sans
            # CustomerRef ne retire pas un lien possiblement posé à la main).
            proj_link = _project_for_txn(b, proj_by_job)
            if (
                not dry_run
                and proj_link is not None
                and ach.project_id != proj_link.id
            ):
                first_link = ach.project_id is None
                ach.project_id = proj_link.id
                # Défaut « à refacturer » du projet cible UNIQUEMENT au
                # premier rattachement (même sémantique qu'un import neuf) et
                # si pas déjà refacturé ; un simple déplacement de projet ne
                # touche pas le choix existant.
                if first_link and ach.invoiced_at is None:
                    ach.is_billable = _is_billable(proj_link)
                updated = True
                await db.flush()
            if paid and ach.status != "paid":
                if not dry_run:
                    ach.status = "paid"
                    ach.paid_at = ach.paid_at or now
                    # Classe selon le paiement réel : un Bill payé ne reste
                    # pas « Sur compte ».
                    real_pm = paid_bill_methods.get(bid)
                    if real_pm and (ach.payment_method or "bill_to_pay") in (
                        "",
                        "bill_to_pay",
                    ):
                        ach.payment_method = real_pm
                    await db.flush()
                stats["paid_synced"] += 1
                pv_status = "paiement_synchro"
            elif updated:
                stats["updated_from_qbo"] = (
                    stats.get("updated_from_qbo", 0) + 1
                )
                pv_status = "maj_qbo"
            else:
                stats["skipped_existing"] += 1
                pv_status = "deja_importe"
            preview.append(
                {"type": "bill", "qbo_id": bid, "amount": total,
                 "vendor": vendor, "status": pv_status}
            )
            continue
        proj = _project_for_txn(b, proj_by_job)
        if proj is None:
            stats["skipped_no_project"] += 1
            preview.append(
                {"type": "bill", "qbo_id": bid, "amount": total,
                 "vendor": vendor, "status": "sans_projet"}
            )
            continue
        preview.append(
            {"type": "bill", "qbo_id": bid, "project_id": proj.id,
             "amount": total, "paid": paid, "vendor": vendor,
             "status": "a_importer"}
        )
        if not dry_run:
            db.add(
                Achat(
                    # Fournisseur lié — CRÉÉ dans Kratos s'il n'existait
                    # pas (il travaille sur un projet Kratos).
                    fournisseur_id=await _fournisseur_id_for(
                        db,
                        fourn_by_name,
                        vendor,
                        (b.get("VendorRef") or {}).get("value"),
                    ),
                    project_id=proj.id,
                    is_billable=_is_billable(proj),
                    description=_txn_description(b),
                    amount=total,
                    status="paid" if paid else "received",
                    # Bill payé → mode réel (chèque/carte) déduit de QB ;
                    # sinon « Sur compte » (à payer).
                    payment_method=(
                        paid_bill_methods.get(bid) or "bill_to_pay"
                        if paid
                        else "bill_to_pay"
                    ),
                    received_at=now,
                    paid_at=now if paid else None,
                    invoice_date=_parse_date(b.get("TxnDate")),
                    supplier_invoice_number=doc or None,
                    qbo_bill_id=bid,
                    qbo_doc_number=doc or None,
                )
            )
            await db.flush()
        stats["bills_imported"] += 1

    # ── Purchases (dépenses payées : cash / chèque / CC) ──
    for p in purchases:
        pid = str(p.get("Id") or "")
        if not pid:
            continue
        if client_refs is not None and _txn_customer_refs(p).isdisjoint(
            client_refs
        ):
            continue
        total = _num(p.get("TotalAmt"))
        vendor = (p.get("EntityRef") or {}).get("name")
        doc = str(p.get("DocNumber") or "")
        # Anti-doublon : un Achat poussé DEPUIS Kratos vers QB stocke
        # l'Id de la Purchase dans `qbo_bill_id` (cf. achat_qbo.py), PAS
        # dans `qbo_purchase_id`. On vérifie donc les DEUX champs, sinon
        # la dépense ré-importée crée un doublon de l'achat d'origine.
        # Achat déjà lié (poussé depuis Kratos → qbo_bill_id, ou importé →
        # qbo_purchase_id). Au lieu de sauter, on REFLÈTE le rapprochement
        # QB → Kratos : date + mode de paiement réel (compte de la dépense).
        # Corrige « la dépense a été rapprochée dans QB mais Kratos gardait
        # l'ancienne date / la mauvaise carte », sans jamais re-pousser.
        existing = existing_bill.get(pid) or existing_purchase.get(pid)
        if existing is not None:
            updated: list[str] = []
            new_date = _parse_date(p.get("TxnDate"))
            if new_date and new_date != existing.invoice_date:
                if not dry_run:
                    existing.invoice_date = new_date
                updated.append("date")
            acc_id = (p.get("AccountRef") or {}).get("value")
            new_method = (
                purchase_acct_methods.get(str(acc_id)) if acc_id else None
            )
            if new_method and new_method != (existing.payment_method or ""):
                if not dry_run:
                    existing.payment_method = new_method
                updated.append("mode de paiement")
            # Backfill : fournisseur manquant sur l'achat lié.
            if not dry_run and existing.fournisseur_id is None and vendor:
                existing.fournisseur_id = await _fournisseur_id_for(
                    db,
                    fourn_by_name,
                    vendor,
                    (p.get("EntityRef") or {}).get("value"),
                )
                updated.append("fournisseur")
            # Reflète les MODIFS QB (montant / description) sur une dépense
            # ORIGINAIRE de QB (TTC, sans ventilation de taxe Kratos). On ne
            # touche PAS un achat maître-Kratos (amount = HT + amount_taxes).
            if float(existing.amount_taxes or 0) == 0:
                new_desc = _txn_description(p)
                if total and round(float(existing.amount or 0), 2) != round(
                    float(total), 2
                ):
                    if not dry_run:
                        existing.amount = total
                    updated.append("montant")
                if new_desc and (existing.description or "") != new_desc:
                    if not dry_run:
                        existing.description = new_desc
                    updated.append("description")
            # RÉAFFECTATION DE PROJET (cf. branche Bill) : dépense imputée à
            # un projet dans QB après son import → refléter le project_id.
            # Jamais d'effacement de projet.
            proj_link = _project_for_txn(p, proj_by_job)
            if (
                proj_link is not None
                and existing.project_id != proj_link.id
            ):
                first_link = existing.project_id is None
                if not dry_run:
                    existing.project_id = proj_link.id
                    if first_link and existing.invoiced_at is None:
                        existing.is_billable = _is_billable(proj_link)
                updated.append("projet")
            if not dry_run:
                # Rafraîchit le SyncToken pour un achat poussé depuis Kratos
                # (évite un « stale token » au prochain push).
                tok = p.get("SyncToken")
                if tok is not None and pid in existing_bill:
                    existing.qbo_sync_token = str(tok)
                if updated:
                    await db.flush()
            if updated:
                stats["reconciled_synced"] += 1
            else:
                stats["skipped_existing"] += 1
            preview.append(
                {"type": "purchase", "qbo_id": pid, "amount": total,
                 "vendor": vendor,
                 "status": "rapproche_maj" if updated else "deja_importe"}
            )
            continue
        proj = _project_for_txn(p, proj_by_job)
        if proj is None:
            stats["skipped_no_project"] += 1
            preview.append(
                {"type": "purchase", "qbo_id": pid, "amount": total,
                 "vendor": vendor, "status": "sans_projet"}
            )
            continue
        ptype = str(p.get("PaymentType") or "")
        pm = {
            "Cash": "comptant",
            "Check": "cheque",
            "CreditCard": "cc",
        }.get(ptype)
        preview.append(
            {"type": "purchase", "qbo_id": pid, "project_id": proj.id,
             "amount": total, "vendor": vendor, "status": "a_importer"}
        )
        if not dry_run:
            db.add(
                Achat(
                    # Fournisseur lié — CRÉÉ dans Kratos s'il n'existait
                    # pas (il travaille sur un projet Kratos).
                    fournisseur_id=await _fournisseur_id_for(
                        db,
                        fourn_by_name,
                        vendor,
                        (p.get("EntityRef") or {}).get("value"),
                    ),
                    project_id=proj.id,
                    is_billable=_is_billable(proj),
                    description=_txn_description(p),
                    amount=total,
                    status="paid",
                    payment_method=pm,
                    received_at=now,
                    paid_at=now,
                    invoice_date=_parse_date(p.get("TxnDate")),
                    supplier_invoice_number=doc or None,
                    qbo_purchase_id=pid,
                    qbo_doc_number=doc or None,
                )
            )
            await db.flush()
        stats["purchases_imported"] += 1

    if not dry_run:
        # Correction « refacturable » : sur un projet à CONTRAT / ESTIMÉ, les
        # coûts liés à QB et PAS encore refacturés doivent être « à
        # refacturer » (et le rester jusqu'à la refacturation). Rattrape les
        # coûts importés avec l'ancien défaut erroné.
        from sqlalchemy import update as _upd

        billable_proj_ids = [
            p.id for p in proj_by_job.values() if _is_billable(p)
        ]
        if billable_proj_ids:
            await db.execute(
                _upd(Achat)
                .where(
                    Achat.project_id.in_(billable_proj_ids),
                    Achat.invoiced_at.is_(None),
                    Achat.is_billable.is_(False),
                    (
                        Achat.qbo_bill_id.is_not(None)
                        | Achat.qbo_purchase_id.is_not(None)
                    ),
                )
                .values(is_billable=True)
            )
            await db.flush()

        # Filet automatique : supprime tout doublon résiduel après import.
        from app.services.achat_dedupe import dedupe_achats

        stats["deduped"] = await dedupe_achats(db)

        # Import des REÇUS QB → Kratos : si une pièce jointe (image/PDF)
        # est déposée sur la dépense/facture fournisseur dans QuickBooks
        # et que l'achat Kratos correspondant n'a PAS encore de reçu, on
        # la télécharge et on la stocke sur l'achat. On n'écrase jamais un
        # reçu déjà présent côté Kratos. Une seule query Attachable par
        # run ; sautée s'il n'y a aucun achat candidat.
        stats["receipts_imported"] = await _import_qbo_receipts(db, qbo)

    if dry_run:
        # Scopé client : on montre TOUT (à importer / déjà importé / sans
        # projet). Global : seulement les lignes à importer (taille bornée).
        stats["preview"] = (
            preview[:300]
            if client_id is not None
            else [p for p in preview if p.get("status") == "a_importer"][:200]
        )
    return stats
