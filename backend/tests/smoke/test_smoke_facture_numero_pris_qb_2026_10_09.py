"""Smoke — numéro de facture déjà pris dans QuickBooks (2026-10-09).

Steven, facture 152 de Connor (projet Hard wood Flooring) : « Dernière
synchro QuickBooks en échec : Une facture 152 existe déjà dans QuickBooks
et elle n'est pas de Kratos (9520-8955 Québec Inc., 14 510.53 $,
2026-10-05). […] Change le numéro de la facture Kratos (crayon […]) puis
resynchronise. » — « Il ne s'agit clairement pas de la même facture. Le
système aurait dû changer à 153 et tenter de renvoyer. Procéder ainsi de
suite jusqu'à ce que ça fonctionne. »

Cause : la facture a reçu son numéro pendant la panne du jeton QB
(vérification QB impossible), et la synchro bloquait ensuite sur le
conflit au lieu de renuméroter.

Couvre :
1. le numéro pris par une AUTRE facture QB → prochain numéro libre,
   nouvel envoi, la facture de l'autre client n'est jamais touchée ;
2. la boucle continue tant que le numéro est pris (QB ou Kratos) ;
3. QB refuse un numéro qu'aucune requête ne montre (doublon 6140) →
   renumérotation et nouvel essai ;
4. la MÊME facture (même client, même total) ou une facture signée
   Kratos → on s'y relie, sans renuméroter ;
5. enregistrer un paiement ne l'impute jamais à la facture d'un autre ;
6. l'import QB → Kratos ne relie plus une autre facture au même numéro
   (ni paiements ni statut « payée » volés) ;
7. le crayon refuse un numéro déjà pris dans QB en donnant le prochain
   numéro libre, et accepte un numéro libre (envoyé tel quel à QB) ;
8. bouton « Envoyer vers QuickBooks » : nouveau numéro renvoyé à l'écran,
   et un échec après renumérotation est bien enregistré sur la fiche
   (plus d'attente sans fin sur la ligne verrouillée).

QuickBooks est simulé en mémoire : aucun appel réseau.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from datetime import date
from typing import Any, Dict, Optional

import pytest
from sqlalchemy import delete, select, update

import app.integrations.quickbooks as qb_mod
import app.services.facture_qbo as fq
from app.integrations.quickbooks import QuickBooksError
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.facture import Facture
from app.models.numbering_counter import NumberingCounter
from app.models.payment import Payment
from tests.smoke.conftest import TestSessionLocal

AUTRE_CLIENT = "9520-8955 Québec Inc."


class FauxQB:
    """QuickBooks en mémoire : Invoices, Payments, refus des doublons de
    numéro (erreur 6140) comme la vraie compagnie."""

    def __init__(self) -> None:
        self.ready = True
        self.invoices: Dict[str, Dict[str, Any]] = {}
        #: Numéros refusés en double par QB mais qu'aucune requête ne
        #: retrouve (autre type de transaction, index en retard…).
        self.invisibles: set[str] = set()
        self.payments: Dict[str, Dict[str, Any]] = {}
        self.creations: list[Dict[str, Any]] = []
        self.mises_a_jour: list[Dict[str, Any]] = []
        #: Erreur QB forcée à la création (autre motif que le doublon).
        self.erreur_creation: Optional[str] = None
        # Ids propres à chaque instance : la base de test est partagée.
        self._n = 10_000_000 + (uuid.uuid4().int % 1_000_000) * 100

    def _id(self) -> str:
        self._n += 1
        return str(self._n)

    def ajouter(
        self,
        doc: str,
        *,
        client: str = AUTRE_CLIENT,
        customer_id: str = "C-AUTRE",
        total: float = 14510.53,
        balance: Optional[float] = None,
        memo: Optional[str] = None,
    ) -> str:
        iid = self._id()
        self.invoices[iid] = {
            "Id": iid,
            "SyncToken": "0",
            "DocNumber": doc,
            "CustomerRef": {"value": customer_id, "name": client},
            "TotalAmt": total,
            "Balance": total if balance is None else balance,
            "TxnDate": "2026-10-05",
            **({"PrivateNote": memo} if memo else {}),
        }
        return iid

    def par_numero(self, doc: str) -> list[Dict[str, Any]]:
        return [i for i in self.invoices.values() if i.get("DocNumber") == doc]

    async def _load_refresh_from_db(self) -> None:
        return None

    async def find_invoice_by_docnumber(self, doc: str) -> Optional[Dict[str, Any]]:
        doc = (doc or "").strip()
        if doc in self.invisibles:
            return None
        trouves = self.par_numero(doc)
        return copy.deepcopy(trouves[0]) if trouves else None

    async def ensure_customer(self, **kw: Any) -> Dict[str, Any]:
        return {"Id": "C-KRATOS", "DisplayName": kw.get("display_name")}

    async def ensure_item(self, name: str, description: Any = None) -> Dict[str, Any]:
        return {"Id": "IT-1"}

    async def ensure_class(self, name: str) -> Dict[str, Any]:
        return {"Id": "CL-1"}

    async def create_invoice(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        p = copy.deepcopy(payload)
        if p.get("Id"):
            inv = self.invoices.get(str(p["Id"]))
            if inv is None:
                raise QuickBooksError("Object Not Found (610)")
            self.mises_a_jour.append(p)
            inv.update({k: v for k, v in p.items() if k != "sparse"})
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
        total = round(sum(float(li.get("Amount") or 0) for li in p.get("Line") or []), 2)
        inv = {**p, "Id": iid, "SyncToken": "0", "TotalAmt": total, "Balance": total}
        self.invoices[iid] = inv
        self.creations.append(p)
        return {"Invoice": copy.deepcopy(inv)}

    async def get_invoice(self, iid: str) -> Dict[str, Any]:
        inv = self.invoices.get(str(iid))
        if inv is None:
            raise QuickBooksError("Object Not Found (610)")
        return {"Invoice": copy.deepcopy(inv)}

    async def ensure_payment_method(self, name: str) -> Dict[str, Any]:
        return {"Id": "PM-1"}

    async def find_account_by_name(self, name: str) -> None:
        return None

    async def create_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pid = self._id()
        self.payments[pid] = {**copy.deepcopy(payload), "Id": pid}
        return {"Payment": copy.deepcopy(self.payments[pid])}

    async def delete_payment(self, pid: str) -> bool:
        return self.payments.pop(str(pid), None) is not None

    async def _request(self, method: str, path: str, **kw: Any) -> Dict[str, Any]:
        pid = path.rsplit("/", 1)[-1]
        if path.startswith("/payment/") and pid in self.payments:
            return {"Payment": copy.deepcopy(self.payments[pid])}
        raise QuickBooksError("Object Not Found (610)")

    async def query(self, q: str) -> list[Dict[str, Any]]:
        if "FROM Invoice" in q:
            return [copy.deepcopy(i) for i in self.invoices.values()]
        if "FROM Payment" in q:
            return [copy.deepcopy(p) for p in self.payments.values()]
        return []


@pytest.fixture()
def faux_qb(monkeypatch, run, db_setup):
    faux = FauxQB()
    monkeypatch.setattr(fq, "get_qbo", lambda *a, **k: faux)
    monkeypatch.setattr(qb_mod, "get_qbo", lambda *a, **k: faux)

    crees: Dict[str, list[int]] = {"factures": [], "clients": []}

    async def _compteur() -> Optional[int]:
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(NumberingCounter.next_facture_number).where(
                        NumberingCounter.id == 1
                    )
                )
            ).scalar_one_or_none()

    avant = run(_compteur())
    faux.crees = crees  # type: ignore[attr-defined]
    yield faux

    async def _nettoyer() -> None:
        async with TestSessionLocal() as s:
            if crees["factures"]:
                await s.execute(
                    delete(Payment).where(Payment.facture_id.in_(crees["factures"]))
                )
                await s.execute(
                    delete(AuditLog).where(
                        AuditLog.action == "facture.renumerotee",
                        AuditLog.entity_id.in_(crees["factures"]),
                    )
                )
                await s.execute(
                    delete(Facture).where(Facture.id.in_(crees["factures"]))
                )
            if crees["clients"]:
                await s.execute(delete(Client).where(Client.id.in_(crees["clients"])))
            if avant is not None:
                await s.execute(
                    update(NumberingCounter)
                    .where(NumberingCounter.id == 1)
                    .values(next_facture_number=avant)
                )
            await s.commit()

    run(_nettoyer())


def _base() -> int:
    """Plage de numéros propre à chaque test (la base de test est
    partagée) : 152 → base + 152."""
    return 100000 + (uuid.uuid4().int % 800) * 1000


def _seed(
    run,
    faux: FauxQB,
    *,
    reference: str,
    compteur: int,
    total: float = 1000.0,
    client_qb: Optional[str] = "C-CONNOR",
    status: str = "sent",
) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            cl = Client(name=f"Connor {uuid.uuid4().hex[:6]}", qbo_customer_id=client_qb)
            s.add(cl)
            await s.flush()
            fa = Facture(
                reference=reference,
                client_id=cl.id,
                status=status,
                subtotal=total,
                total=total,
                balance=total,
            )
            s.add(fa)
            await s.flush()
            row = (
                await s.execute(select(NumberingCounter).where(NumberingCounter.id == 1))
            ).scalar_one_or_none()
            if row is None:
                s.add(NumberingCounter(id=1, next_facture_number=compteur))
            else:
                await s.execute(
                    update(NumberingCounter)
                    .where(NumberingCounter.id == 1)
                    .values(next_facture_number=compteur)
                )
            await s.commit()
            faux.crees["clients"].append(cl.id)  # type: ignore[attr-defined]
            faux.crees["factures"].append(fa.id)  # type: ignore[attr-defined]
            return int(fa.id)

    return run(_go())


def _facture(run, fid: int) -> Facture:
    async def _go() -> Facture:
        async with TestSessionLocal() as s:
            return (await s.execute(select(Facture).where(Facture.id == fid))).scalar_one()

    return run(_go())


def _sync(run, fid: int) -> Dict[str, Any]:
    async def _go() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            res = await fq.sync_facture_to_qbo(s, fid)
            await s.commit()
            return res

    return run(_go())


def _attendre_taches(run) -> None:
    """Laisse finir les push QB lancés en tâche de fond par l'API."""

    async def _go() -> None:
        moi = asyncio.current_task()
        taches = [t for t in asyncio.all_tasks() if t is not moi and not t.done()]
        if taches:
            await asyncio.wait(taches, timeout=10)

    run(_go())


def test_numero_pris_par_une_autre_facture_prend_le_suivant_et_renvoie(faux_qb, run):
    b = _base()
    etrangere = faux_qb.ajouter(str(b + 152))
    fid = _seed(run, faux_qb, reference=str(b + 152), compteur=b + 153)

    res = _sync(run, fid)

    fa = _facture(run, fid)
    assert fa.reference == str(b + 153)
    assert fa.qbo_invoice_id and fa.qbo_invoice_id != etrangere
    assert fa.qbo_doc_number == str(b + 153)
    assert fa.qbo_sync_error is None
    # Créée dans QB sous le nouveau numéro, signée Kratos.
    cree = faux_qb.invoices[fa.qbo_invoice_id]
    assert cree["DocNumber"] == str(b + 153)
    assert cree["PrivateNote"] == f"Kratos facture #{fid}"
    # La facture de l'autre client n'est jamais touchée.
    assert faux_qb.mises_a_jour == []
    assert faux_qb.invoices[etrangere]["CustomerRef"]["name"] == AUTRE_CLIENT
    assert faux_qb.invoices[etrangere]["DocNumber"] == str(b + 152)
    # Visible à l'écran, dans les notes internes et le journal.
    assert res["reference"] == str(b + 153)
    assert f"Numéro changé de {b + 152} à {b + 153}" in res["sync_note"]
    assert AUTRE_CLIENT in res["sync_note"]
    assert f"Numéro changé de {b + 152} à {b + 153}" in (fa.internal_notes or "")

    async def _journal() -> list[AuditLog]:
        async with TestSessionLocal() as s:
            return list(
                (
                    await s.execute(
                        select(AuditLog).where(
                            AuditLog.action == "facture.renumerotee",
                            AuditLog.entity_id == fid,
                        )
                    )
                ).scalars()
            )

    assert len(run(_journal())) == 1


def test_la_boucle_continue_tant_que_le_numero_est_pris(faux_qb, run):
    b = _base()
    faux_qb.ajouter(str(b + 152))
    faux_qb.ajouter(str(b + 153), client="Autre client", total=50.0)
    # Le 155 est déjà porté par une facture Kratos.
    _seed(run, faux_qb, reference=str(b + 155), compteur=b + 1)
    fid = _seed(run, faux_qb, reference=str(b + 152), compteur=b + 153)

    res = _sync(run, fid)

    fa = _facture(run, fid)
    # 153 pris dans QB (autre client), 154 libre.
    assert fa.reference == str(b + 154)
    assert faux_qb.invoices[fa.qbo_invoice_id]["DocNumber"] == str(b + 154)
    assert res["reference"] == str(b + 154)

    # Et si 154 et 155 sont pris à leur tour (QB, Kratos), on va au 156.
    faux_qb2 = faux_qb
    faux_qb2.ajouter(str(b + 1152))
    fid2 = _seed(run, faux_qb, reference=str(b + 1152), compteur=b + 154)
    _sync(run, fid2)
    assert _facture(run, fid2).reference == str(b + 156)


def test_doublon_refuse_par_qb_sans_etre_visible_renumerote(faux_qb, run):
    b = _base()
    # QB refuse le 152 (doublon 6140) mais aucune requête ne le montre.
    faux_qb.invisibles.add(str(b + 152))
    fid = _seed(run, faux_qb, reference=str(b + 152), compteur=b + 153)

    res = _sync(run, fid)

    fa = _facture(run, fid)
    assert fa.reference == str(b + 153)
    assert faux_qb.invoices[fa.qbo_invoice_id]["DocNumber"] == str(b + 153)
    assert "numéro de document en double" in res["sync_note"]


def test_la_meme_facture_est_reliee_sans_renumeroter(faux_qb, run):
    b = _base()
    # Saisie dans QB avant Kratos : même client, même total.
    meme = faux_qb.ajouter(
        str(b + 152), client="Connor", customer_id="C-CONNOR", total=1000.0
    )
    fid = _seed(run, faux_qb, reference=str(b + 152), compteur=b + 153)
    _sync(run, fid)
    fa = _facture(run, fid)
    assert fa.reference == str(b + 152)
    assert fa.qbo_invoice_id == meme
    assert faux_qb.creations == []

    # Signée Kratos (lien perdu) : reliée aussi, même à un autre client.
    signee = faux_qb.ajouter(
        str(b + 1152), memo="Kratos facture #999999", total=12.0
    )
    fid2 = _seed(run, faux_qb, reference=str(b + 1152), compteur=b + 153)
    _sync(run, fid2)
    fa2 = _facture(run, fid2)
    assert fa2.reference == str(b + 1152)
    assert fa2.qbo_invoice_id == signee


def test_un_paiement_ne_va_jamais_sur_la_facture_d_un_autre(faux_qb, run):
    b = _base()
    etrangere = faux_qb.ajouter(str(b + 152))
    fid = _seed(run, faux_qb, reference=str(b + 152), compteur=b + 153)

    async def _paiement_puis_push() -> None:
        async with TestSessionLocal() as s:
            s.add(
                Payment(
                    facture_id=fid,
                    amount=300.0,
                    method="bank_transfer",
                    paid_at=date(2026, 10, 9),
                )
            )
            await s.commit()
        async with TestSessionLocal() as s:
            await fq.push_facture_payments_only(s, fid)
            await s.commit()

    run(_paiement_puis_push())

    fa = _facture(run, fid)
    assert fa.reference == str(b + 153)
    assert fa.qbo_invoice_id != etrangere
    assert len(faux_qb.payments) == 1
    (pay,) = faux_qb.payments.values()
    lie = pay["Line"][0]["LinkedTxn"][0]["TxnId"]
    assert lie == fa.qbo_invoice_id
    assert lie != etrangere


def test_import_qb_ne_relie_plus_une_autre_facture_au_meme_numero(
    faux_qb, run, monkeypatch
):
    import app.services.facture_dedupe as dedupe

    async def _rien(db: Any) -> int:
        return 0

    monkeypatch.setattr(dedupe, "dedupe_factures", _rien)
    b = _base()
    # Facture d'un autre client, PAYÉE dans QB (solde 0, paiement QB).
    etrangere = faux_qb.ajouter(str(b + 152), balance=0)
    faux_qb.payments["P-ETR"] = {
        "Id": "P-ETR",
        "TxnDate": "2026-10-06",
        "TotalAmt": 14510.53,
        "Line": [
            {
                "Amount": 14510.53,
                "LinkedTxn": [{"TxnId": etrangere, "TxnType": "Invoice"}],
            }
        ],
    }
    fid = _seed(run, faux_qb, reference=str(b + 152), compteur=b + 153)
    # La même facture saisie dans QB (même client, même total) se relie.
    meme = faux_qb.ajouter(
        str(b + 1152), client="Connor", customer_id="C-CONNOR", total=1000.0
    )
    fid2 = _seed(run, faux_qb, reference=str(b + 1152), compteur=b + 153)

    async def _pull() -> None:
        from app.services.qbo_invoice_pull import pull_invoices_from_qbo

        async with TestSessionLocal() as s:
            await pull_invoices_from_qbo(s, dry_run=False)
            await s.commit()

    run(_pull())

    fa = _facture(run, fid)
    assert fa.qbo_invoice_id is None
    assert fa.status == "sent"

    async def _nb_paiements() -> int:
        async with TestSessionLocal() as s:
            return len(
                list(
                    (
                        await s.execute(select(Payment).where(Payment.facture_id == fid))
                    ).scalars()
                )
            )

    assert run(_nb_paiements()) == 0
    assert _facture(run, fid2).qbo_invoice_id == meme


def test_crayon_refuse_un_numero_pris_dans_qb_et_propose_le_libre(
    faux_qb, run, client, auth_headers
):
    b = _base()
    faux_qb.ajouter(str(b + 153))
    fid = _seed(run, faux_qb, reference=str(b + 152), compteur=b + 153)

    r = client.patch(
        f"/api/v1/factures/{fid}",
        headers=auth_headers,
        json={"reference": str(b + 153)},
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "déjà pris dans QuickBooks" in detail
    assert AUTRE_CLIENT in detail
    assert f"Le prochain numéro libre est {b + 154}." in detail
    assert _facture(run, fid).reference == str(b + 152)

    # Un numéro déjà porté par une facture Kratos : même suggestion.
    _seed(run, faux_qb, reference=str(b + 160), compteur=b + 153)
    r = client.patch(
        f"/api/v1/factures/{fid}",
        headers=auth_headers,
        json={"reference": str(b + 160)},
    )
    assert r.status_code == 409, r.text
    assert f"Le prochain numéro libre est {b + 154}." in r.json()["detail"]

    # Le numéro libre proposé passe, et part tel quel dans QB.
    r = client.patch(
        f"/api/v1/factures/{fid}",
        headers=auth_headers,
        json={"reference": str(b + 154)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["reference"] == str(b + 154)
    _attendre_taches(run)
    fa = _facture(run, fid)
    assert fa.reference == str(b + 154)
    assert fa.qbo_invoice_id
    assert faux_qb.invoices[fa.qbo_invoice_id]["DocNumber"] == str(b + 154)


def test_bouton_quickbooks_renvoie_le_nouveau_numero(
    faux_qb, run, client, auth_headers
):
    b = _base()
    faux_qb.ajouter(str(b + 152))
    fid = _seed(run, faux_qb, reference=str(b + 152), compteur=b + 153)

    r = client.post(f"/api/v1/factures/{fid}/qbo/sync", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reference"] == str(b + 153)
    assert body["qbo_doc_number"] == str(b + 153)
    assert f"Numéro changé de {b + 152} à {b + 153}" in body["sync_note"]


def test_echec_apres_renumerotation_est_enregistre_sur_la_fiche(
    faux_qb, run, client, auth_headers
):
    b = _base()
    faux_qb.ajouter(str(b + 152))
    faux_qb.erreur_creation = "QBO 400 : Business Validation Error (6000) — taxe"
    fid = _seed(run, faux_qb, reference=str(b + 152), compteur=b + 153)

    r = client.post(f"/api/v1/factures/{fid}/qbo/sync", headers=auth_headers)
    assert r.status_code == 400, r.text
    assert "6000" in r.json()["detail"]
    fa = _facture(run, fid)
    # Transaction annulée (numéro inchangé) et motif affiché sur la fiche.
    assert fa.reference == str(b + 152)
    assert "6000" in (fa.qbo_sync_error or "")

    # QB réparé : le nouvel essai renumérote et passe.
    faux_qb.erreur_creation = None
    r = client.post(f"/api/v1/factures/{fid}/qbo/sync", headers=auth_headers)
    assert r.status_code == 200, r.text
    fa = _facture(run, fid)
    assert fa.reference == str(b + 153)
    assert fa.qbo_sync_error is None
