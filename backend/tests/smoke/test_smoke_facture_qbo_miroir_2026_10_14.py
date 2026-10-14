"""Smoke — miroir QuickBooks d'une facture modifiée (2026-10-14).

Steven : « la facture 120 dans QB ne semble pas à jour par rapport à la
facture 120 de Kratos. Les paiements semblent bien enregistrés par
contre. » QuickBooks : 16 115,64 $, datée du 20 août ; Kratos :
15 965,88 $ (sous-total 13 886,39 $).

Causes :
1. une ligne modifiée sur une facture émise lançait le push QB AVANT la
   validation de la requête (la session n'est commitée qu'après la
   réponse) → QuickBooks recevait les lignes d'AVANT la modification ;
2. deux pushes rapprochés se disputaient la même Invoice (SyncToken) ;
3. un refus « Stale Object » (5010) ou « introuvable » faisait recréer
   une Invoice qui existait encore → doublon de numéro → sa PROPRE
   Invoice prise pour « une autre facture » → renumérotation et paiements
   déplacés ;
4. la date de l'Invoice QB prenait la date du jour à chaque renvoi ;
5. rien ne revérifiait les factures déjà reliées : l'écart restait ;
6. (filet du 2026-10-14, 21 h 41 UTC) la mise à jour « sparse » de
   l'Invoice laissait les LIGNES telles quelles : QuickBooks acceptait la
   requête et gardait 16 115,64 $. Seule une mise à jour COMPLÈTE (objet
   relu, lignes remplacées, taxes recalculées par QB) les change.

Couvre :
1. modifier / ajouter / supprimer une ligne par l'API met l'Invoice QB à
   jour avec les lignes ENREGISTRÉES, date QB inchangée ;
2. un paiement enregistré par l'API part dans QB dès la requête ;
3. SyncToken périmé (paiement imputé dans QB) → mise à jour rejouée avec
   le jeton à jour, rien de recréé, paiement QB intact ;
4. « introuvable » passager, ou un « 610 » de hasard dans le message →
   pas de recréation ;
5. Invoice vraiment supprimée de QB → recréée, signée, à la date
   d'émission ;
6. QB dit « introuvable » à la lecture mais refuse le doublon → sa propre
   Invoice est mise à jour, jamais renumérotée ;
7. plusieurs pushes rapprochés : une synchro à la fois, les suivants
   fondus ;
8. filet horaire : l'Invoice en retard est remise à jour (paiements,
   numéro, date conservés, journal), une Invoice retouchée dans QB est
   signalée sur la fiche sans être écrasée, totaux égaux / annulées /
   sans lignes laissés tranquilles ;
9. filet horaire : limite par passage, refus QB non rejoué sans fin,
   total QB différent après remise à jour complète signalé (détail au
   journal), fiche marquée du temps des mises à jour « sparse » retentée ;
10. mise à jour complète : corps sans les champs calculés par QB, lignes
    remplacées, date / mémo / courriel / conditions de QB conservés.

QuickBooks est simulé en mémoire : aucun appel réseau.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

import pytest
from sqlalchemy import delete, select

import app.integrations.quickbooks as qb_mod
import app.services.facture_qbo as fq
from app.integrations.quickbooks import QuickBooksError
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.facture import Facture
from app.models.facture_item import FactureItem
from app.models.payment import Payment
from app.services.qbo_auto_sync import push_facture_now
from tests.smoke.conftest import TestSessionLocal
from tests.smoke.test_smoke_facture_numero_pris_qb_2026_10_09 import FauxQB

EMISE_LE = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
ACTIONS_JOURNAL = (
    "facture.renumerotee",
    "facture.qbo_resynchronisee",
    "facture.qbo_ecart_persistant",
    "facture.qbo_ecart_a_verifier",
)


class QBMiroir(FauxQB):
    """FauxQB qui, comme la vraie compagnie, refuse un SyncToken périmé
    (5010), laisse les lignes telles quelles sur une mise à jour
    « sparse », remplace les lignes et efface les champs absents sur une
    mise à jour complète, recalcule le total (lignes + taxes) à chaque
    écriture et compte les écritures simultanées sur une Invoice."""

    #: Champs modifiables remis à zéro par une mise à jour COMPLÈTE quand
    #: le corps ne les renvoie pas (QuickBooks : « writable fields omitted
    #: from the request body are set to NULL »).
    EFFACES_SI_ABSENTS = (
        "TxnDate", "PrivateNote", "CustomerMemo", "BillEmail", "EmailStatus",
        "LinkedTxn", "DueDate", "ClassRef", "SalesTermRef", "CurrencyRef",
    )

    def __init__(self) -> None:
        super().__init__()
        self.en_cours = 0
        self.max_en_cours = 0
        #: Erreurs forcées à la MISE À JOUR, consommées une par une.
        self.erreurs_maj: list[str] = []
        #: get_invoice répond « introuvable » même si l'Invoice existe.
        self.lecture_introuvable = False
        #: Taxe calculée par QB au lieu de celle envoyée (compagnie AST).
        self.taxe_forcee: Optional[float] = None

    @staticmethod
    def _lignes(p: Dict[str, Any]) -> float:
        return round(
            sum(
                float(li.get("Amount") or 0)
                for li in p.get("Line") or []
                if li.get("DetailType") == "SalesItemLineDetail"
            ),
            2,
        )

    def _taxe(self, lignes: float) -> float:
        """TPS + TVQ calculées par QB sur les lignes (code de taxe de la
        compagnie), ou la taxe forcée (client exonéré)."""
        if self.taxe_forcee is not None:
            return self.taxe_forcee
        return round(round(lignes * 0.05, 2) + round(lignes * 0.09975, 2), 2)

    def _recalculer(self, inv: Dict[str, Any], paye: float) -> None:
        lignes = self._lignes(inv)
        inv["TxnTaxDetail"] = {"TotalTax": self._taxe(lignes)}
        inv["TotalAmt"] = round(lignes + inv["TxnTaxDetail"]["TotalTax"], 2)
        inv["Balance"] = round(inv["TotalAmt"] - paye, 2)

    async def create_invoice(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        p = copy.deepcopy(payload)
        self.en_cours += 1
        self.max_en_cours = max(self.max_en_cours, self.en_cours)
        try:
            await asyncio.sleep(0.01)
            if p.get("Id"):
                inv = self.invoices.get(str(p["Id"]))
                if inv is None:
                    raise QuickBooksError("Object Not Found (610)")
                if self.erreurs_maj:
                    raise QuickBooksError(self.erreurs_maj.pop(0))
                if str(p.get("SyncToken")) != str(inv.get("SyncToken")):
                    raise QuickBooksError(
                        "QBO 400 : {'Fault': {'Error': [{'Message': 'Stale "
                        "Object Error', 'Detail': 'Stale Object Error : You "
                        "and ... were working on this at the same time.', "
                        "'code': '5010'}]}}"
                    )
                self.mises_a_jour.append(p)
                paye = round(
                    float(inv.get("TotalAmt") or 0) - float(inv.get("Balance") or 0), 2
                )
                if p.get("sparse"):
                    # Comme la vraie compagnie (constaté sur la 120 le
                    # 2026-10-14) : une mise à jour « sparse » accepte la
                    # requête mais laisse les LIGNES telles quelles.
                    p.pop("Line", None)
                    p.pop("TxnTaxDetail", None)
                else:
                    # Mise à jour complète : lignes remplacées, champs
                    # modifiables absents du corps effacés, montants et
                    # taxes recalculés (jamais repris du corps).
                    for champ in ("TotalAmt", "Balance", "MetaData", "TxnTaxDetail"):
                        assert champ not in p, f"{champ} renvoyé dans la mise à jour"
                    for champ in self.EFFACES_SI_ABSENTS:
                        if champ not in p:
                            inv.pop(champ, None)
                inv.update({k: v for k, v in p.items() if k != "sparse"})
                self._recalculer(inv, paye)
                inv["SyncToken"] = str(int(inv.get("SyncToken") or 0) + 1)
                return {"Invoice": copy.deepcopy(inv)}
            if self.erreur_creation:
                raise QuickBooksError(self.erreur_creation)
            doc = str(p.get("DocNumber") or "")
            if doc in self.invisibles or self.par_numero(doc):
                raise QuickBooksError(
                    f"QBO 400 : Duplicate Document Number Error (6140) — {doc}"
                )
            iid = self._id()
            inv = {k: v for k, v in p.items() if k != "sparse"}
            inv.update({"Id": iid, "SyncToken": "0"})
            self._recalculer(inv, 0.0)
            self.invoices[iid] = inv
            self.creations.append(p)
            return {"Invoice": copy.deepcopy(inv)}
        finally:
            self.en_cours -= 1

    async def get_invoice(self, iid: str) -> Dict[str, Any]:
        if self.lecture_introuvable:
            raise QuickBooksError("Object Not Found (610)")
        return await super().get_invoice(iid)

    def payer_dans_qb(self, iid: str, montant: float) -> str:
        """Paiement imputé DANS QuickBooks : solde réduit et SyncToken
        avancé, comme le fait la vraie compagnie."""
        inv = self.invoices[iid]
        inv["Balance"] = round(float(inv["Balance"]) - montant, 2)
        inv["SyncToken"] = str(int(inv["SyncToken"]) + 1)
        pid = self._id()
        self.payments[pid] = {
            "Id": pid,
            "TotalAmt": montant,
            "Line": [
                {
                    "Amount": montant,
                    "LinkedTxn": [{"TxnId": iid, "TxnType": "Invoice"}],
                }
            ],
        }
        return pid


@pytest.fixture()
def qb(monkeypatch, run, db_setup):
    faux = QBMiroir()
    monkeypatch.setattr(fq, "get_qbo", lambda *a, **k: faux)
    monkeypatch.setattr(qb_mod, "get_qbo", lambda *a, **k: faux)
    # Compagnie à taxe automatisée : les lignes portent le code de taxe,
    # QuickBooks calcule TPS / TVQ (aucun TxnTaxDetail envoyé).
    monkeypatch.setitem(fq.settings.__dict__, "qbo_sales_tax_code", "5")
    fq._corrections_tentees.clear()
    crees: Dict[str, list[int]] = {"factures": [], "clients": []}
    faux.crees = crees  # type: ignore[attr-defined]
    yield faux

    async def _nettoyer() -> None:
        async with TestSessionLocal() as s:
            if crees["factures"]:
                fids = crees["factures"]
                await s.execute(delete(Payment).where(Payment.facture_id.in_(fids)))
                await s.execute(
                    delete(FactureItem).where(FactureItem.facture_id.in_(fids))
                )
                await s.execute(
                    delete(AuditLog).where(
                        AuditLog.action.in_(ACTIONS_JOURNAL),
                        AuditLog.entity_id.in_(fids),
                    )
                )
                await s.execute(delete(Facture).where(Facture.id.in_(fids)))
            if crees["clients"]:
                await s.execute(delete(Client).where(Client.id.in_(crees["clients"])))
            await s.commit()

    run(_nettoyer())
    fq._corrections_tentees.clear()


def _base() -> int:
    """Plage de numéros propre à chaque test (la base de test est
    partagée) : 120 → base + 120."""
    return 200000 + (uuid.uuid4().int % 800) * 1000


def _ligne_qb(description: str, montant: float) -> Dict[str, Any]:
    return {
        "DetailType": "SalesItemLineDetail",
        "Amount": montant,
        "Description": description,
        "SalesItemLineDetail": {"Qty": 1, "UnitPrice": montant, "ItemRef": {"value": "IT-1"}},
    }


def _seed(
    run,
    qb: QBMiroir,
    *,
    reference: str,
    lignes: list[tuple[str, float]],
    lignes_qb: Optional[list[tuple[str, float]]] = None,
    lier: bool = True,
    memo: bool = True,
    client_qb: str = "C-KRATOS",
    status: str = "sent",
    note_qb: Optional[str] = None,
) -> tuple[int, Optional[str]]:
    """Facture émise avec ses lignes et, si `lier`, son Invoice QB (lignes
    `lignes_qb` si QB est en retard, sinon les mêmes)."""
    sous_total = round(sum(m for _, m in lignes), 2)
    total = fq._total_attendu(sous_total)

    async def _go() -> int:
        async with TestSessionLocal() as s:
            cl = Client(name=f"Samuel {uuid.uuid4().hex[:6]}", qbo_customer_id="C-KRATOS")
            s.add(cl)
            await s.flush()
            fa = Facture(
                reference=reference,
                client_id=cl.id,
                status=status,
                issued_at=EMISE_LE,
                subtotal=sous_total,
                tps=round(sous_total * 0.05, 2),
                tvq=round(sous_total * 0.09975, 2),
                total=total,
                balance=total,
            )
            s.add(fa)
            await s.flush()
            for i, (desc, montant) in enumerate(lignes):
                s.add(
                    FactureItem(
                        facture_id=fa.id,
                        position=i,
                        description=desc,
                        quantity=1,
                        unit_price=montant,
                        total=montant,
                        kind="service",
                    )
                )
            await s.commit()
            qb.crees["clients"].append(cl.id)  # type: ignore[attr-defined]
            qb.crees["factures"].append(fa.id)  # type: ignore[attr-defined]
            return int(fa.id)

    fid = run(_go())
    if not lier:
        return fid, None
    qb_lignes = lignes_qb if lignes_qb is not None else lignes
    iid = qb._id()
    sous_qb = round(sum(m for _, m in qb_lignes), 2)
    total_qb = fq._total_attendu(sous_qb)
    inv: Dict[str, Any] = {
        "Id": iid,
        "SyncToken": "0",
        "DocNumber": reference,
        "CustomerRef": {"value": client_qb, "name": "Samuel"},
        "Line": [_ligne_qb(d, m) for d, m in qb_lignes],
        "TxnTaxDetail": {"TotalTax": round(total_qb - sous_qb, 2)},
        "TotalAmt": total_qb,
        "Balance": total_qb,
        "TxnDate": "2026-06-15",
        # Ce que QuickBooks renvoie aussi à la lecture : à conserver tel
        # quel (échéance, courriel, mémo client, conditions, devise…) ou à
        # ne pas lui renvoyer (métadonnées, totaux).
        "DueDate": "2026-07-15",
        "EmailStatus": "EmailSent",
        "CustomerMemo": {"value": "Merci de votre confiance."},
        "BillEmail": {"Address": "samuel@example.com"},
        "SalesTermRef": {"value": "3"},
        "CurrencyRef": {"value": "CAD", "name": "Canadian Dollar"},
        "LinkedTxn": [],
        "MetaData": {
            "CreateTime": "2026-06-15T10:00:00-07:00",
            "LastUpdatedTime": "2026-06-15T10:00:00-07:00",
        },
        "domain": "QBO",
        "sparse": False,
    }
    if memo:
        inv["PrivateNote"] = f"Kratos facture #{fid}"
    if note_qb:
        inv["PrivateNote"] = note_qb
    qb.invoices[iid] = inv

    async def _lier() -> None:
        async with TestSessionLocal() as s:
            fa = (await s.execute(select(Facture).where(Facture.id == fid))).scalar_one()
            fa.qbo_invoice_id = iid
            fa.qbo_sync_token = "0"
            fa.qbo_doc_number = reference
            await s.commit()

    run(_lier())
    return fid, iid


def _facture(run, fid: int) -> Facture:
    async def _go() -> Facture:
        async with TestSessionLocal() as s:
            return (await s.execute(select(Facture).where(Facture.id == fid))).scalar_one()

    return run(_go())


def _items(run, fid: int) -> list[FactureItem]:
    async def _go() -> list[FactureItem]:
        async with TestSessionLocal() as s:
            return list(
                (
                    await s.execute(
                        select(FactureItem)
                        .where(FactureItem.facture_id == fid)
                        .order_by(FactureItem.position)
                    )
                ).scalars()
            )

    return run(_go())


def _changer_montant(run, fid: int, montant: float) -> None:
    async def _go() -> None:
        async with TestSessionLocal() as s:
            it = (
                await s.execute(
                    select(FactureItem).where(FactureItem.facture_id == fid)
                )
            ).scalars().first()
            it.unit_price = montant
            it.total = montant
            await s.commit()

    run(_go())


def _sync(run, fid: int) -> Dict[str, Any]:
    async def _go() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            res = await fq.sync_facture_to_qbo(s, fid)
            await s.commit()
            return res

    return run(_go())


def _journal(run, fid: int, action: str) -> list[AuditLog]:
    async def _go() -> list[AuditLog]:
        async with TestSessionLocal() as s:
            return list(
                (
                    await s.execute(
                        select(AuditLog).where(
                            AuditLog.action == action, AuditLog.entity_id == fid
                        )
                    )
                ).scalars()
            )

    return run(_go())


def _attendre_taches(run) -> None:
    """Laisse finir les push QB lancés en tâche de fond par l'API."""

    async def _go() -> None:
        moi = asyncio.current_task()
        taches = [t for t in asyncio.all_tasks() if t is not moi and not t.done()]
        if taches:
            await asyncio.wait(taches, timeout=10)

    run(_go())


def _montants_qb(qb: QBMiroir, iid: str) -> list[float]:
    return [
        float(li["Amount"])
        for li in qb.invoices[iid]["Line"]
        if li.get("DetailType") == "SalesItemLineDetail"
    ]


# ── 1. Lignes modifiées par l'API : QB reçoit les lignes enregistrées ──


def test_modifier_une_ligne_met_qb_a_jour_avec_les_nouvelles_lignes(
    qb, run, client, auth_headers
):
    b = _base()
    fid, iid = _seed(run, qb, reference=str(b + 120), lignes=[("Travaux", 1000.0)])
    (item,) = _items(run, fid)

    r = client.patch(
        f"/api/v1/factures/{fid}/items/{item.id}",
        headers=auth_headers,
        json={"unit_price": 800.0},
    )
    assert r.status_code == 200, r.text
    _attendre_taches(run)

    # QB a les lignes ENREGISTRÉES (pas celles d'avant la requête).
    assert _montants_qb(qb, iid) == [800.0]
    assert qb.invoices[iid]["TotalAmt"] == fq._total_attendu(800.0)
    fa = _facture(run, fid)
    assert float(fa.total) == fq._total_attendu(800.0)
    assert fa.qbo_invoice_id == iid
    assert fa.qbo_sync_error is None
    assert qb.creations == []
    # Mise à jour COMPLÈTE (une mise à jour « sparse » laisse les lignes
    # telles quelles) ; la date de l'Invoice QB ne bouge pas.
    assert qb.mises_a_jour[-1]["sparse"] is False
    assert qb.mises_a_jour[-1]["TxnDate"] == "2026-06-15"
    assert qb.invoices[iid]["TxnDate"] == "2026-06-15"

    # Ligne ajoutée puis supprimée : même chose.
    r = client.post(
        f"/api/v1/factures/{fid}/items",
        headers=auth_headers,
        json={"description": "Extra", "quantity": 1, "unit_price": 50.0, "kind": "extra"},
    )
    assert r.status_code == 201, r.text
    _attendre_taches(run)
    assert _montants_qb(qb, iid) == [800.0, 50.0]

    r = client.delete(
        f"/api/v1/factures/{fid}/items/{r.json()['id']}", headers=auth_headers
    )
    assert r.status_code == 204, r.text
    _attendre_taches(run)
    assert _montants_qb(qb, iid) == [800.0]
    assert qb.invoices[iid]["TotalAmt"] == fq._total_attendu(800.0)
    assert qb.max_en_cours == 1


# ── 1 bis. Mise à jour COMPLÈTE : lignes remplacées, le reste conservé ──


def test_mise_a_jour_complete_remplace_les_lignes_et_garde_le_reste(qb, run):
    b = _base()
    fid, iid = _seed(
        run,
        qb,
        reference=str(b + 120),
        lignes=[("Travaux", 13886.39)],
        lignes_qb=[("Travaux", 14016.64)],
    )
    avant = copy.deepcopy(qb.invoices[iid])

    # L'ancienne façon (mise à jour « sparse ») : QB accepte et ne change
    # rien aux lignes — c'est ce qui laissait la 120 à 16 115,64 $.
    run(
        qb.create_invoice(
            {
                "Id": iid,
                "SyncToken": "0",
                "sparse": True,
                "Line": [_ligne_qb("Travaux", 13886.39)],
            }
        )
    )
    assert _montants_qb(qb, iid) == [14016.64]
    assert qb.invoices[iid]["TotalAmt"] == avant["TotalAmt"]

    res = _sync(run, fid)

    corps = qb.mises_a_jour[-1]
    assert corps["sparse"] is False and corps["Id"] == iid
    for champ in ("TotalAmt", "Balance", "MetaData", "TxnTaxDetail", "domain"):
        assert champ not in corps, champ
    assert [li["Amount"] for li in corps["Line"]] == [13886.39]
    assert corps["DocNumber"] == str(b + 120)
    inv = qb.invoices[iid]
    assert _montants_qb(qb, iid) == [13886.39]
    assert inv["TotalAmt"] == res["qbo_total"] == 15965.88
    assert res["qbo_sous_total"] == 13886.39
    assert res["qbo_taxe"] == round(15965.88 - 13886.39, 2)
    # Date, mémo, échéance, courriel, mémo client, conditions, devise et
    # statut d'envoi : ceux de QuickBooks, intacts.
    for champ in (
        "TxnDate", "PrivateNote", "DueDate", "BillEmail", "CustomerMemo",
        "SalesTermRef", "CurrencyRef", "EmailStatus",
    ):
        assert inv[champ] == avant[champ], champ
    assert qb.creations == []
    fa = _facture(run, fid)
    assert fa.qbo_sync_error is None
    assert fa.qbo_sync_token == "2"


# ── 2. Paiement enregistré par l'API : dans QB dès la requête ──


def test_un_paiement_enregistre_part_dans_qb_des_la_requete(
    qb, run, client, auth_headers
):
    b = _base()
    fid, iid = _seed(run, qb, reference=str(b + 120), lignes=[("Travaux", 1000.0)])

    r = client.post(
        f"/api/v1/factures/{fid}/payments",
        headers=auth_headers,
        json={"amount": 300.0, "method": "bank_transfer", "paid_at": "2026-10-14"},
    )
    assert r.status_code == 201, r.text
    _attendre_taches(run)

    assert len(qb.payments) == 1
    (pay,) = qb.payments.values()
    assert pay["Line"][0]["LinkedTxn"][0]["TxnId"] == iid
    assert float(pay["TotalAmt"]) == 300.0

    async def _paiement() -> Payment:
        async with TestSessionLocal() as s:
            return (
                await s.execute(select(Payment).where(Payment.facture_id == fid))
            ).scalar_one()

    assert run(_paiement()).qbo_payment_id == pay["Id"]
    # Le corps de la facture n'a pas été renvoyé pour autant.
    assert qb.mises_a_jour == []


# ── 3. SyncToken périmé : rejoué, rien de recréé ──


def test_jeton_perime_rejoue_la_mise_a_jour_sans_recreer(qb, run):
    b = _base()
    fid, iid = _seed(run, qb, reference=str(b + 120), lignes=[("Travaux", 1000.0)])
    # Paiement imputé dans QB depuis notre dernière synchro : le jeton
    # mémorisé (« 0 ») est périmé.
    qb.payer_dans_qb(iid, 300.0)
    assert qb.invoices[iid]["SyncToken"] == "1"
    _changer_montant(run, fid, 800.0)

    res = _sync(run, fid)

    fa = _facture(run, fid)
    assert fa.reference == str(b + 120)
    assert fa.qbo_invoice_id == iid
    assert fa.qbo_sync_token == "2"
    assert fa.qbo_sync_error is None
    assert res.get("sync_warning") is None
    assert res["qbo_total"] == fq._total_attendu(800.0)
    assert _montants_qb(qb, iid) == [800.0]
    assert qb.creations == []
    assert len(qb.invoices) == 1
    # Le paiement QB est resté imputé, le solde suit le nouveau total.
    assert len(qb.payments) == 1
    assert qb.invoices[iid]["Balance"] == round(fq._total_attendu(800.0) - 300.0, 2)
    assert _journal(run, fid, "facture.renumerotee") == []


# ── 4. « Introuvable » passager ou 610 de hasard : pas de recréation ──


def test_introuvable_passager_ne_recree_pas_l_invoice(qb, run):
    b = _base()
    fid, iid = _seed(run, qb, reference=str(b + 120), lignes=[("Travaux", 1000.0)])
    _changer_montant(run, fid, 800.0)

    # QB répond « introuvable » une fois alors que l'Invoice existe.
    qb.erreurs_maj = ["Object Not Found (610)"]
    res = _sync(run, fid)
    assert res.get("sync_warning") is None
    assert _facture(run, fid).qbo_invoice_id == iid
    assert _montants_qb(qb, iid) == [800.0]
    assert qb.creations == []

    # Un « 610 » de hasard (heure du Fault) n'est pas un code d'erreur :
    # l'échec est signalé, l'Invoice n'est pas recréée.
    _changer_montant(run, fid, 700.0)
    qb.erreurs_maj = [
        "QBO 500 : Internal Server Error intuit_tid 1-610-abc "
        "2026-10-14T10:00:00.610-07:00"
    ]
    res = _sync(run, fid)
    assert "Corps de la facture non mis à jour" in (res.get("sync_warning") or "")
    fa = _facture(run, fid)
    assert fa.qbo_invoice_id == iid
    assert "610" in (fa.qbo_sync_error or "")
    assert qb.creations == []
    assert _montants_qb(qb, iid) == [800.0]
    assert len(qb.invoices) == 1


# ── 5. Vraiment supprimée de QB : recréée, signée, à la date d'émission ──


def test_invoice_supprimee_dans_qb_est_recreee_a_la_date_d_emission(qb, run):
    b = _base()
    fid, iid = _seed(run, qb, reference=str(b + 120), lignes=[("Travaux", 1000.0)])
    del qb.invoices[iid]

    _sync(run, fid)

    fa = _facture(run, fid)
    assert fa.reference == str(b + 120)
    assert fa.qbo_invoice_id and fa.qbo_invoice_id != iid
    nouvelle = qb.invoices[fa.qbo_invoice_id]
    assert nouvelle["DocNumber"] == str(b + 120)
    assert nouvelle["PrivateNote"] == f"Kratos facture #{fid}"
    assert nouvelle["TxnDate"] == "2026-06-15"
    assert len(qb.creations) == 1
    assert _journal(run, fid, "facture.renumerotee") == []


# ── 6. QB incohérent (introuvable à la lecture, doublon à l'écriture) ──


def test_qb_refuse_le_doublon_de_sa_propre_invoice_sans_renumeroter(qb, run):
    b = _base()
    fid, iid = _seed(run, qb, reference=str(b + 120), lignes=[("Travaux", 1000.0)])
    qb.payer_dans_qb(iid, 300.0)  # jeton périmé
    qb.lecture_introuvable = True  # …et la relecture dit « introuvable »
    _changer_montant(run, fid, 800.0)

    res = _sync(run, fid)

    fa = _facture(run, fid)
    # Sa propre Invoice n'est pas « une autre facture » : mise à jour,
    # pas de renumérotation, pas de 2e Invoice, paiement intact.
    assert fa.reference == str(b + 120)
    assert fa.qbo_invoice_id == iid
    assert res["reference"] == str(b + 120)
    assert res.get("sync_note") is None
    assert qb.creations == []
    assert len(qb.invoices) == 1
    assert _montants_qb(qb, iid) == [800.0]
    assert len(qb.payments) == 1
    assert _journal(run, fid, "facture.renumerotee") == []


# ── 7. Pushes rapprochés : une synchro à la fois, les suivants fondus ──


def test_pushes_rapproches_sont_serialises_et_fondus(qb, run):
    b = _base()
    fid, iid = _seed(run, qb, reference=str(b + 120), lignes=[("Travaux", 1000.0)])
    _changer_montant(run, fid, 800.0)

    async def _trois() -> None:
        await asyncio.gather(
            push_facture_now(fid), push_facture_now(fid), push_facture_now(fid)
        )

    run(_trois())

    assert qb.max_en_cours == 1
    # Le 1er part, le 2e attend son tour, le 3e est fondu dans le 2e.
    assert len(qb.mises_a_jour) == 2
    assert _montants_qb(qb, iid) == [800.0]
    fa = _facture(run, fid)
    assert fa.qbo_sync_token == "2"
    assert fa.qbo_sync_error is None
    assert qb.creations == []


# ── 8. Filet horaire : factures en retard dans QB ──


def test_filet_remet_a_jour_les_factures_qb_en_retard(qb, run):
    b = _base()
    # A : la 120 — QB a encore les lignes d'avant la modification.
    fid_a, iid_a = _seed(
        run,
        qb,
        reference=str(b + 120),
        lignes=[("Travaux", 13886.39)],
        lignes_qb=[("Travaux", 14016.64)],
    )
    total_qb_avant = qb.invoices[iid_a]["TotalAmt"]
    pid_a = qb.payer_dans_qb(iid_a, 15665.89)

    async def _paiement_kratos() -> None:
        async with TestSessionLocal() as s:
            s.add(
                Payment(
                    facture_id=fid_a,
                    amount=15665.89,
                    method="bank_transfer",
                    paid_at=date(2026, 7, 2),
                    qbo_payment_id=pid_a,
                )
            )
            await s.commit()

    run(_paiement_kratos())
    # B : à jour. C : annulée dans QB. E : sans lignes (importée de QB).
    fid_b, iid_b = _seed(run, qb, reference=str(b + 121), lignes=[("OK", 500.0)])
    fid_c, iid_c = _seed(
        run, qb, reference=str(b + 122), lignes=[("Annulée", 500.0)],
        lignes_qb=[("Annulée", 900.0)], note_qb="Voided",
    )
    qb.invoices[iid_c]["TotalAmt"] = 0
    fid_e, iid_e = _seed(run, qb, reference=str(b + 124), lignes=[])
    qb.invoices[iid_e]["TotalAmt"] = 999.0
    # D : l'Invoice QB a été retouchée dans QuickBooks (autre client, autres
    # lignes, pas de signature) → à vérifier, jamais écrasée.
    fid_d, iid_d = _seed(
        run, qb, reference=str(b + 123), lignes=[("Travaux", 1000.0)],
        lignes_qb=[("Honoraires", 1500.0), ("Autre", 20.0)], memo=False,
        client_qb="C-AUTRE",
    )
    qb.invoices[iid_d]["CustomerRef"]["name"] = "Quelqu'un d'autre"
    avant_d = copy.deepcopy(qb.invoices[iid_d])

    res = run(fq.corriger_factures_en_retard_dans_qb())

    assert res["ecarts"] == 2
    assert res["corrigees"] == [str(b + 120)]
    assert res["a_verifier"] == [str(b + 123)]
    assert res["echecs"] == {}
    # A : lignes Kratos, total Kratos, numéro / date / signature / paiement
    # conservés, journal.
    inv_a = qb.invoices[iid_a]
    assert _montants_qb(qb, iid_a) == [13886.39]
    assert inv_a["TotalAmt"] == fq._total_attendu(13886.39) == 15965.88
    assert inv_a["DocNumber"] == str(b + 120)
    assert inv_a["TxnDate"] == "2026-06-15"
    assert inv_a["PrivateNote"] == f"Kratos facture #{fid_a}"
    assert inv_a["Balance"] == round(15965.88 - 15665.89, 2)
    assert len(qb.payments) == 1 and pid_a in qb.payments
    assert qb.creations == []
    fa_a = _facture(run, fid_a)
    assert fa_a.qbo_invoice_id == iid_a
    assert fa_a.qbo_sync_error is None
    (entree,) = _journal(run, fid_a, "facture.qbo_resynchronisee")
    assert f'"total_qb_avant": {total_qb_avant}' in entree.details_json
    assert '"total_kratos": 15965.88' in entree.details_json
    assert '"total_qb_apres": 15965.88' in entree.details_json
    # B, C, E : pas touchées.
    assert qb.invoices[iid_b]["SyncToken"] == "0"
    assert qb.invoices[iid_c]["SyncToken"] == "0"
    assert qb.invoices[iid_e]["SyncToken"] == "0"
    # D : signalée sur la fiche et au journal, QB intact.
    assert qb.invoices[iid_d] == avant_d
    fa_d = _facture(run, fid_d)
    assert "QuickBooks n'est pas à jour" in (fa_d.qbo_sync_error or "")
    assert "total QuickBooks 1 747,62 $, Kratos 1 149,75 $" in fa_d.qbo_sync_error
    assert "Renvoyer vers QuickBooks" in fa_d.qbo_sync_error
    assert len(_journal(run, fid_d, "facture.qbo_ecart_a_verifier")) == 1

    # Second passage : A est à jour, D déjà signalée → rien de nouveau.
    res = run(fq.corriger_factures_en_retard_dans_qb())
    assert res["ecarts"] == 1
    assert res["corrigees"] == [] and res["a_verifier"] == []
    assert res["deja_signalees"] == 1
    assert len(_journal(run, fid_a, "facture.qbo_resynchronisee")) == 1
    assert len(_journal(run, fid_d, "facture.qbo_ecart_a_verifier")) == 1
    assert qb.invoices[iid_d] == avant_d


# ── 9. Filet horaire : limite, refus QB, total QB différent ──


def test_filet_limite_par_passage_et_n_insiste_pas(qb, run):
    b = _base()
    fid_1, iid_1 = _seed(
        run, qb, reference=str(b + 120), lignes=[("A", 100.0)], lignes_qb=[("A", 90.0)]
    )
    fid_2, iid_2 = _seed(
        run, qb, reference=str(b + 121), lignes=[("B", 100.0)], lignes_qb=[("B", 90.0)]
    )

    res = run(fq.corriger_factures_en_retard_dans_qb(limite=1))
    assert res["ecarts"] == 2
    assert res["corrigees"] == [str(b + 120)]
    assert _montants_qb(qb, iid_2) == [90.0]

    res = run(fq.corriger_factures_en_retard_dans_qb(limite=1))
    assert res["corrigees"] == [str(b + 121)]
    assert _montants_qb(qb, iid_1) == [100.0]
    assert _montants_qb(qb, iid_2) == [100.0]

    # QB refuse la mise à jour : signalé sur la fiche, retenté une fois,
    # puis laissé tel quel (pas de martèlement toutes les heures).
    fid_3, iid_3 = _seed(
        run, qb, reference=str(b + 122), lignes=[("C", 100.0)], lignes_qb=[("C", 90.0)]
    )
    qb.erreurs_maj = ["QBO 400 : Business Validation Error (6000) — taxe"] * 5
    res = run(fq.corriger_factures_en_retard_dans_qb())
    assert res["corrigees"] == []
    assert "6000" in res["echecs"][str(b + 122)]
    assert "6000" in (_facture(run, fid_3).qbo_sync_error or "")
    res = run(fq.corriger_factures_en_retard_dans_qb())
    assert "6000" in res["echecs"][str(b + 122)]
    res = run(fq.corriger_factures_en_retard_dans_qb())
    assert res["echecs"] == {} and res["deja_tentees"] == 1
    assert len(qb.erreurs_maj) == 3
    assert _montants_qb(qb, iid_3) == [90.0]
    assert _journal(run, fid_3, "facture.qbo_resynchronisee") == []


def test_total_qb_different_apres_remise_a_jour_est_signale(qb, run):
    b = _base()
    fid, iid = _seed(
        run, qb, reference=str(b + 120), lignes=[("A", 100.0)], lignes_qb=[("A", 90.0)]
    )
    # QB calcule la taxe autrement (client exonéré) : le total ne rejoint
    # jamais celui de Kratos, même lignes remplacées.
    qb.taxe_forcee = 0.0

    res = run(fq.corriger_factures_en_retard_dans_qb())
    assert res["corrigees"] == []
    assert res["persistants"] == [str(b + 120)]
    assert _montants_qb(qb, iid) == [100.0]
    fa = _facture(run, fid)
    assert "QuickBooks calcule un autre total" in (fa.qbo_sync_error or "")
    assert "remise à jour complète" in fa.qbo_sync_error
    assert "total QuickBooks 100,00 $, Kratos 114,98 $" in fa.qbo_sync_error
    assert _journal(run, fid, "facture.qbo_resynchronisee") == []
    (entree,) = _journal(run, fid, "facture.qbo_ecart_persistant")
    assert '"total_qb_apres": 100.0' in entree.details_json
    assert '"sous_total_kratos": 100.0' in entree.details_json
    assert '"sous_total_qb_apres": 100.0' in entree.details_json
    assert '"taxe_qb_apres": 0.0' in entree.details_json

    # Déjà signalé : on ne renvoie pas la facture à chaque heure.
    n = len(qb.mises_a_jour)
    res = run(fq.corriger_factures_en_retard_dans_qb())
    assert res["persistants"] == [] and res["deja_signalees"] == 1
    assert len(qb.mises_a_jour) == n
    assert len(_journal(run, fid, "facture.qbo_ecart_persistant")) == 1


def test_fiche_marquee_du_temps_des_mises_a_jour_sparse_est_retentee(qb, run):
    """La 120 et la 113 portaient « …même après la remise à jour (…) »
    posé par le filet du 2026-10-14, qui n'avait pas remplacé les lignes
    (mise à jour sparse) : avec la mise à jour complète, elles sont
    reprises, pas laissées de côté comme « déjà signalées »."""
    b = _base()
    fid, iid = _seed(
        run,
        qb,
        reference=str(b + 120),
        lignes=[("Travaux", 13886.39)],
        lignes_qb=[("Travaux", 14016.64)],
    )
    marque = fq.marque_ecart_qb(qb.invoices[iid]["TotalAmt"], 15965.88)
    ancien = (
        "QuickBooks calcule un autre total que Kratos même après la remise à "
        f"jour ({marque}) : vérifier les taxes du client dans QuickBooks."
    )

    async def _marquer() -> None:
        async with TestSessionLocal() as s:
            fa = (await s.execute(select(Facture).where(Facture.id == fid))).scalar_one()
            fa.qbo_sync_error = ancien
            await s.commit()

    run(_marquer())

    res = run(fq.corriger_factures_en_retard_dans_qb())

    assert res["corrigees"] == [str(b + 120)]
    assert res["deja_signalees"] == 0
    assert _montants_qb(qb, iid) == [13886.39]
    assert qb.invoices[iid]["TotalAmt"] == 15965.88
    fa = _facture(run, fid)
    assert fa.qbo_sync_error is None
    assert len(_journal(run, fid, "facture.qbo_resynchronisee")) == 1
    assert _journal(run, fid, "facture.qbo_ecart_persistant") == []
