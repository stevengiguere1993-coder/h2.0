"""Smoke — paiement automatique des fournisseurs par VoPay (Steven, 2026-10-05).

« L'idée est de ne pas faire les virements nous-mêmes. Juste approuver et
que tout se fasse par la suite ! » : une entreprise qui active le paiement
automatique fait payer ses lots par VoPay. À la dernière approbation,
Kratos prélève le total dans le compte de l'entreprise, paie chaque
fournisseur (dépôt direct ou Interac), puis inscrit les paiements dans
QuickBooks.

Faux VoPay et faux QuickBooks : aucun appel réseau. L'horloge des
paiements part du lundi 5 octobre 2026, 9 h (Toronto) et avance à la
demande ; les codes de double authentification suivent la vraie horloge.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import settings
from app.integrations import vopay
from app.integrations.vopay import Adresse, Statut, VoPay, VoPayErreur, VoPayIncertain
from app.models.entreprise import Entreprise
from app.models.notification import Notification
from app.models.paiement_fournisseur import (
    LotPaiement,
    LotPaiementLigne,
    PaiementOperation,
    PaiementReglage,
    Utilisateur2FA,
)
from app.models.qbo_connection import QboConnection
from app.services import paiements_auto as pa
from app.services import paiements_fournisseurs as svc
from app.services.secret_vault import decrypt_secret

from .conftest import TestSessionLocal
from .test_smoke_paiements_fournisseurs_2026_10_04 import (
    _FakeQbo,
    _activer_2fa,
    _compte_utilisateur,
    _entetes,
    _facture,
)

FIGE = datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)  # lundi 9 h à Toronto
AUJOURDHUI = "2026-10-05"
CLE_COFFRE = Fernet.generate_key().decode()
HORLOGE = [FIGE]


# ── Environnement ────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def _environnement():
    mp = pytest.MonkeyPatch()
    mp.setattr(settings, "subscription_encryption_key", CLE_COFFRE)
    mp.setattr(svc, "_maintenant", lambda: HORLOGE[0])
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def _horloge():
    HORLOGE[0] = FIGE
    yield
    HORLOGE[0] = FIGE


@pytest.fixture(autouse=True)
def _menage(run, db_setup):
    yield

    async def _do() -> None:
        from sqlalchemy import update

        async with TestSessionLocal() as s:
            await s.execute(
                update(PaiementOperation).where(PaiementOperation.statut.in_(pa.OPS_OUVERTES)).values(statut="annule")
            )
            await s.execute(
                update(LotPaiement)
                .where(LotPaiement.envoi_auto.is_(True), LotPaiement.statut.in_(pa.LOTS_EN_COURS))
                .values(statut="annule")
            )
            await s.commit()

    run(_do())


def _avancer(**delta: float) -> None:
    HORLOGE[0] = HORLOGE[0] + timedelta(**delta)


class _FakeVoPay:
    """VoPay factice : garde les transactions créées et refuse une clé
    d'idempotence déjà vue, comme VoPay."""

    def __init__(self) -> None:
        self.connexions: List[Dict[str, Any]] = []
        self.appels: List[Tuple[str, Dict[str, Any]]] = []
        self.transactions: Dict[str, Dict[str, Any]] = {}
        self.par_cle: Dict[str, str] = {}
        #: Exceptions à lever au prochain appel de création, par sorte.
        self.pannes: Dict[str, List[Exception]] = {}
        #: Sortes dont la prochaine création réussit chez VoPay, mais dont
        #: la réponse se perd.
        self.reponses_perdues: set = set()
        #: Refus au prochain paiement d'un bénéficiaire (par nom).
        self.refus: Dict[str, Exception] = {}
        self.refus_cles: Optional[Exception] = None
        self._n = 7000

    async def solde(self) -> Dict[str, Any]:
        self.appels.append(("solde", {}))
        if self.refus_cles:
            raise self.refus_cles
        return {"Success": True, "AccountBalance": "1500.00", "AvailableFunds": "1250.50"}

    async def _creer(self, sorte: str, kw: Dict[str, Any]) -> str:
        self.appels.append((sorte, dict(kw)))
        if self.pannes.get(sorte):
            raise self.pannes[sorte].pop(0)
        if kw.get("nom") in self.refus:
            raise self.refus.pop(kw["nom"])
        if kw["cle"] in self.par_cle:
            raise VoPayErreur("Duplicate request: IdempotencyKey already used.", code="2002")
        self._n += 1
        tid = str(self._n)
        self.par_cle[kw["cle"]] = tid
        self.transactions[tid] = {"sorte": sorte, "statut": "pending", "raison": None, **kw}
        if sorte in self.reponses_perdues:
            self.reponses_perdues.discard(sorte)
            raise VoPayIncertain("VoPay n'a pas répondu à la demande.")
        return tid

    async def prelever(self, **kw: Any) -> str:
        return await self._creer("prelevement", kw)

    async def deposer(self, **kw: Any) -> str:
        return await self._creer("depot", kw)

    async def envoyer_interac(self, **kw: Any) -> str:
        return await self._creer("interac", kw)

    async def statut(self, sorte: str, transaction_id: str) -> Statut:
        self.appels.append(("statut", {"sorte": sorte, "tid": transaction_id}))
        t = self.transactions.get(transaction_id)
        if t is None:
            raise VoPayErreur("Transaction inconnue.", temporaire=True)
        return Statut(brut=t["statut"], etat=vopay.etat(t["statut"]), raison=t["raison"])

    def creees(self, sorte: str) -> List[Dict[str, Any]]:
        return [t for t in self.transactions.values() if t["sorte"] == sorte]

    def regler(self, statut: str, *, sorte: str, nom: Optional[str] = None, raison: Optional[str] = None) -> None:
        for t in self.creees(sorte):
            if nom is None or t.get("nom") == nom:
                t["statut"] = statut
                t["raison"] = raison

    def nb(self, sorte: str) -> int:
        return sum(1 for s, _ in self.appels if s == sorte)


@pytest.fixture()
def fake_vopay(monkeypatch) -> _FakeVoPay:
    fake = _FakeVoPay()

    def _connexion(account_id: str, cle: str, secret: str, environnement: str, sous_compte: Optional[str] = None):
        fake.connexions.append(
            {"account_id": account_id, "cle": cle, "secret": secret, "environnement": environnement}
        )
        return fake

    monkeypatch.setattr(pa, "connexion", _connexion)
    return fake


ADRESSES = {
    "56": {"Line1": "220, chemin du Tremblay", "City": "Boucherville", "CountrySubDivisionCode": "QC",
           "PostalCode": "J4B 6Z6", "Country": "Canada"},
    "57": {"Line1": "45, rue des Érables", "City": "Granby", "CountrySubDivisionCode": "Québec",
           "PostalCode": "j2g8c1"},
}


@pytest.fixture()
def fake_qbo(monkeypatch) -> _FakeQbo:
    fake = _FakeQbo()
    for v in fake.vendors:
        v["BillAddr"] = dict(ADRESSES[v["Id"]])
    monkeypatch.setattr("app.integrations.quickbooks.get_qbo", lambda scope: fake)
    return fake


@pytest.fixture()
def inc(run) -> Dict[str, Any]:
    async def _seed() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            e = Entreprise(name=f"9999-{uuid.uuid4().hex[:4]} Québec inc.")
            s.add(e)
            await s.flush()
            s.add(
                QboConnection(
                    scope=f"inc:{e.id}", refresh_token="rt-smoke", realm_id="9130",
                    environment="sandbox", company_name="Inc Smoke",
                )
            )
            await s.commit()
            return {"id": e.id, "name": e.name}

    return run(_seed())


@pytest.fixture(scope="module")
def equipe(client, run) -> Dict[str, Any]:
    ids = {
        "technicienne": _compte_utilisateur(run, "admin", comptabilite=True),
        "steven": _compte_utilisateur(run, "owner"),
        "phil": _compte_utilisateur(run, "owner"),
    }
    out = {"ids": ids, "h": {k: _entetes(v) for k, v in ids.items()}, "secrets": {}}
    for qui in ("steven", "phil"):
        _activer_2fa(client, out, qui)
    return out


def _confirmer(run, *user_ids: int) -> None:
    """Les gestes sensibles passent sans nouveau code (confirmation récente)."""

    async def _do() -> None:
        async with TestSessionLocal() as s:
            for uid in user_ids:
                ligne = (
                    await s.execute(select(Utilisateur2FA).where(Utilisateur2FA.user_id == uid))
                ).scalar_one()
                ligne.confirme_jusqu_a = datetime(2030, 1, 1, tzinfo=timezone.utc)
            await s.commit()

    run(_do())


def _oublier(run, user_id: int) -> None:
    async def _do() -> None:
        async with TestSessionLocal() as s:
            ligne = (
                await s.execute(select(Utilisateur2FA).where(Utilisateur2FA.user_id == user_id))
            ).scalar_one()
            ligne.confirme_jusqu_a = None
            await s.commit()

    run(_do())


def _notifs(run, user_id: int) -> List[str]:
    async def _do() -> List[str]:
        async with TestSessionLocal() as s:
            rows = (await s.execute(select(Notification).where(Notification.user_id == user_id))).scalars().all()
            return [n.title for n in rows]

    return run(_do())


def _operations(run, lot_id: int) -> List[PaiementOperation]:
    async def _do() -> List[PaiementOperation]:
        async with TestSessionLocal() as s:
            return list(
                (
                    await s.execute(
                        select(PaiementOperation).where(PaiementOperation.lot_id == lot_id).order_by(PaiementOperation.id)
                    )
                ).scalars().all()
            )

    return run(_do())


def _journal(run, lot_id: int) -> List[str]:
    from app.models.paiement_fournisseur import PaiementEvenement

    async def _do() -> List[str]:
        async with TestSessionLocal() as s:
            rows = (
                await s.execute(select(PaiementEvenement).where(PaiementEvenement.lot_id == lot_id))
            ).scalars().all()
            return [r.action for r in rows]

    return run(_do())


REGLAGES_AUTO = {
    "numero_organisme": "0123456789",
    "nom_court": "Horizon inc",
    "nom_long": "Horizon Services Immobiliers",
    "retour_institution": "815",
    "retour_transit": "30001",
    "retour_compte": "1234567",
    "approbations_requises": 1,
    "prochain_numero_fichier": 1,
    "qbo_compte_banque_id": "35",
    "auto_actif": True,
    "auto_environnement": "production",
    "vopay_account_id": "horizon-inc",
    "vopay_cle": "cle-api-0123456789",
    "vopay_secret": "secret-partage-0123456789",
    "adresse": "123, rue Principale",
    "ville": "Granby",
    "province": "Québec",
    "code_postal": "j2g 1a1",
    "interac_question": "Nom de notre entreprise ?",
    "interac_reponse": "Horizon2026",
}


def _activer_auto(client, run, equipe, eid: int, **changes: Any) -> Dict[str, Any]:
    _confirmer(run, equipe["ids"]["steven"])
    r = client.put(
        f"/api/v1/paiements/entreprises/{eid}/reglages",
        headers=equipe["h"]["steven"],
        json={**REGLAGES_AUTO, **changes},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _coordonnees(client, run, equipe, eid: int, mode: str = "depot_direct") -> None:
    """La technicienne saisit les coordonnées de Rona et d'Ébénisterie
    Côté ; Steven les approuve."""
    h = equipe["h"]
    _confirmer(run, equipe["ids"]["steven"])
    corps = {
        "depot_direct": {
            "56": {"institution": "815", "transit": "90001", "numero_compte": "5512345"},
            "57": {"institution": "006", "transit": "12345", "numero_compte": "998877665"},
        },
        "interac": {
            "56": {"interac_destinataire": "comptes@rona.ca"},
            "57": {"interac_destinataire": "450 555-1234"},
        },
    }[mode]
    for vid, champs in corps.items():
        r = client.post(
            f"/api/v1/paiements/entreprises/{eid}/comptes",
            headers=h["technicienne"],
            json={"fournisseur_id": vid, "mode": mode, **champs},
        )
        assert r.status_code == 200, r.text
        r = client.post(f"/api/v1/paiements/comptes/{r.json()['id']}/approuver", headers=h["steven"], json={})
        assert r.status_code == 200, r.text


LIGNES = [
    {"qbo_bill_id": "300", "montant": 1000},
    {"qbo_bill_id": "301", "montant": 250.5},
    {"qbo_bill_id": "302", "montant": 500},
]


def _lot_soumis(client, equipe, eid: int, *, mode: str = "depot_direct", date: str = AUJOURDHUI,
                lignes: Optional[List[Dict[str, Any]]] = None) -> int:
    h = equipe["h"]
    r = client.post(
        f"/api/v1/paiements/entreprises/{eid}/lots",
        headers=h["technicienne"],
        json={"date_paiement": date, "mode": mode, "lignes": lignes or LIGNES},
    )
    assert r.status_code == 200, r.text
    lot_id = r.json()["id"]
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/soumettre", headers=h["technicienne"])
    assert r.status_code == 200, r.text
    return lot_id


def _approuver(client, run, equipe, lot_id: int) -> Dict[str, Any]:
    _confirmer(run, equipe["ids"]["phil"])
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/approuver", headers=equipe["h"]["phil"], json={})
    assert r.status_code == 200, r.text
    return r.json()


def _detail(client, equipe, lot_id: int, qui: str = "steven") -> Dict[str, Any]:
    r = client.get(f"/api/v1/paiements/lots/{lot_id}", headers=equipe["h"][qui])
    assert r.status_code == 200, r.text
    return r.json()


def _passer(run, **delta: float) -> None:
    """Le temps passe, puis la boucle de fond fait un passage."""
    if delta:
        _avancer(**delta)
    run(pa.passer())


# ── Client VoPay (httpx simulé) ──────────────────────────────────────


def test_client_vopay_signature_formulaire_et_erreurs(run, monkeypatch):
    recues: List[httpx.Request] = []
    reponses: List[httpx.Response] = []

    def _gerer(request: httpx.Request) -> httpx.Response:
        recues.append(request)
        return reponses.pop(0)

    transport = httpx.MockTransport(_gerer)
    vp = VoPay("compte-1", "cle-1", "secret-1", "test", transport=transport)
    monkeypatch.setattr(VoPay, "jours", staticmethod(lambda maintenant=None: ["2026-10-05", "2026-10-04"]))
    adresse = Adresse("123, rue Principale", "Granby", "QC", "J2G 1A1")
    args = dict(
        montant_cents=125050, nom="Horizon inc.", adresse=adresse, institution="815", transit="30001",
        compte="1234567", reference="KRATOS-L1-P1", note="Lot 1", cle="cle-idem-1",
    )

    import hashlib

    assert vp.signature("2026-10-05") == hashlib.sha1(b"cle-1secret-12026-10-05").hexdigest()

    # Prélèvement accepté : formulaire complet, numéro de transaction rendu.
    reponses.append(httpx.Response(200, json={"Success": True, "ErrorMessage": "", "TransactionID": 1122}))
    assert run(vp.prelever(**args)) == "1122"
    envoye = dict(httpx.QueryParams(recues[-1].content.decode()))
    assert str(recues[-1].url) == "https://earthnode-dev.vopay.com/api/v2/eft/fund"
    assert envoye["Amount"] == "1250.50" and envoye["IdempotencyKey"] == "cle-idem-1"
    assert envoye["AccountNumber"] == "1234567" and envoye["Province"] == "QC" and envoye["Country"] == "CA"
    assert envoye["Signature"] == vp.signature("2026-10-05") and envoye["AccountID"] == "compte-1"

    # Signature refusée (fuseau de VoPay) : nouvel essai avec la date de Vancouver.
    reponses.extend([
        httpx.Response(200, json={"Success": False, "ErrorMessage": "Invalid signature", "ErrorCode": "1000"}),
        httpx.Response(200, json={"Success": True, "TransactionID": "1123"}),
    ])
    assert run(vp.prelever(**args)) == "1123"
    assert dict(httpx.QueryParams(recues[-1].content.decode()))["Signature"] == vp.signature("2026-10-04")

    # Refus clair : rien n'a été créé.
    reponses.append(httpx.Response(400, json={"Success": False, "ErrorMessage": "Invalid account", "ErrorCode": "2010"}))
    with pytest.raises(VoPayErreur) as exc:
        run(vp.deposer(**args))
    assert exc.value.code == "2010" and not exc.value.temporaire

    # Erreur interne pendant une création : peut-être créée.
    reponses.append(httpx.Response(500, json={"Success": False, "ErrorMessage": "Internal error"}))
    with pytest.raises(VoPayIncertain):
        run(vp.deposer(**args))
    reponses.append(httpx.Response(502, text="<html>Bad gateway</html>"))
    with pytest.raises(VoPayIncertain):
        run(vp.prelever(**args))
    # Page illisible avec un 4xx : rien n'a été créé.
    reponses.append(httpx.Response(404, text="introuvable"))
    with pytest.raises(VoPayErreur):
        run(vp.prelever(**args))
    # Solde insuffisant : erreur 3001.
    reponses.append(httpx.Response(200, json={"Success": False, "ErrorMessage": "Insufficient balance", "ErrorCode": "3001"}))
    with pytest.raises(VoPayErreur) as exc:
        run(vp.envoyer_interac(
            montant_cents=1000, nom="Rona", destinataire="comptes@rona.ca", question="Q ?", reponse="R123",
            message="Paiement", expediteur="Horizon", reference="KRATOS-L1-F56-1", cle="cle-idem-2",
        ))
    assert exc.value.solde
    envoye = dict(httpx.QueryParams(recues[-1].content.decode()))
    assert envoye["EmailAddress"] == "comptes@rona.ca" and "PhoneNumber" not in envoye
    assert str(recues[-1].url).endswith("/interac/bulk-payout")

    # Statut : lu dans la transaction (route « transaction »), même imbriqué.
    reponses.append(httpx.Response(200, json={"Success": True, "Status": "ok", "Transaction": {
        "TransactionStatus": "failed", "FailureReason": "NSF"}}))
    st = run(vp.statut("prelevement", "1122"))
    assert (st.brut, st.etat, st.raison) == ("failed", "echoue", "NSF")
    assert recues[-1].method == "GET" and "eft/fund/transaction" in str(recues[-1].url)
    assert recues[-1].url.params["TransactionID"] == "1122"

    # VoPay injoignable : rien n'est parti.
    def _panne(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé")

    vp2 = VoPay("compte-1", "cle-1", "secret-1", "production", transport=httpx.MockTransport(_panne))
    with pytest.raises(VoPayErreur) as exc:
        run(vp2.prelever(**args))
    assert exc.value.temporaire

    def _lent(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("trop long")

    vp3 = VoPay("compte-1", "cle-1", "secret-1", "production", transport=httpx.MockTransport(_lent))
    with pytest.raises(VoPayIncertain):
        run(vp3.prelever(**args))
    with pytest.raises(VoPayErreur):
        run(vp3.statut("depot", "1"))

    assert vopay.etat("sent") == "en_cours" and vopay.etat("Successful") == "reussi"
    assert vopay.etat("cancellation requested") == "en_cours" and vopay.etat("declined") == "echoue"
    assert vopay.soldes({"AccountBalance": "1,500.00", "AvailableFunds": 12}) == {"solde": 1500.0, "disponible": 12.0}


def test_jours_de_signature():
    # Le soir à Vancouver, la date UTC est déjà le lendemain.
    assert VoPay.jours(datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)) == ["2026-10-05", "2026-10-04"]
    assert VoPay.jours(datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)) == ["2026-10-05"]


def test_adresses_canadiennes():
    assert svc.province_canadienne("Québec") == "QC"
    assert svc.province_canadienne("qc") == "QC"
    assert svc.province_canadienne("P.Q.") == "QC"
    assert svc.province_canadienne("Nouvelle-Écosse") == "NS"
    assert svc.province_canadienne("Île-du-Prince-Édouard") == "PE"
    assert svc.province_canadienne("Vermont") is None
    assert svc.code_postal_canadien("h2x1y4") == "H2X 1Y4"
    assert svc.code_postal_canadien("H2X-1Y4") == "H2X 1Y4"
    assert svc.code_postal_canadien("12345") is None
    assert pa.adresse_qbo({"BillAddr": ADRESSES["57"]}) == Adresse("45, rue des Érables", "Granby", "QC", "J2G 8C1")
    assert pa.adresse_qbo({"BillAddr": {**ADRESSES["56"], "Country": "USA"}}) is None
    assert pa.adresse_qbo({"BillAddr": {"Line1": "1 rue A", "City": "Laval"}}) is None
    assert pa.adresse_qbo({}) is None


def test_connecteur_ia_et_masquage():
    from app.api.v1.endpoints.mcp_server import _ACTION_CHEMINS_INTERDITS
    from app.core.audit_middleware import _masquer
    from app.services.entity_serializers import serialize_entity

    for chemin in (
        "/api/v1/paiements/lots/3/auto/reessayer",
        "/api/v1/paiements/lots/3/paiements/56/retirer",
        "/api/v1/paiements/entreprises/9/vopay/tester",
    ):
        assert any(chemin.startswith(p) for p in _ACTION_CHEMINS_INTERDITS)
    masque = _masquer({"vopay_cle": "k", "vopay_secret": "s", "interac_reponse": "r", "vopay_account_id": "a"})
    assert masque == {"vopay_cle": "•••", "vopay_secret": "•••", "interac_reponse": "•••", "vopay_account_id": "a"}

    class _Lot:
        id = 3
        entreprise_id = 9
        statut = "echec"
        date_paiement = datetime(2026, 10, 5).date()
        total_cents = 125050
        nb_lignes = 2
        envoi_auto = True
        auto_environnement = "production"
        auto_erreur = "NSF"

    out = serialize_entity("lot_paiement", _Lot(), level="summary")
    assert out["envoi_auto"] is True and out["auto_erreur"] == "NSF" and out["statut"] == "echec"


# ── Réglages ─────────────────────────────────────────────────────────


def test_reglages_vopay(client, run, equipe, inc, fake_qbo, fake_vopay):
    h = equipe["h"]
    eid = inc["id"]
    url = f"/api/v1/paiements/entreprises/{eid}/reglages"
    _confirmer(run, equipe["ids"]["steven"])

    # La technicienne n'a pas accès aux réglages.
    assert client.put(url, headers=h["technicienne"], json=REGLAGES_AUTO).status_code == 403

    # Activer sans adresse : refusé, avec ce qui manque.
    r = client.put(url, headers=h["steven"], json={**REGLAGES_AUTO, "adresse": "", "ville": None})
    assert r.status_code == 422 and r.json()["manque_auto"] == ["adresse de l'entreprise"]
    # Clés refusées par VoPay : refusé, rien d'enregistré.
    fake_vopay.refus_cles = VoPayErreur("Invalid key", code="1000")
    r = client.put(url, headers=h["steven"], json=REGLAGES_AUTO)
    assert r.status_code == 422 and "VoPay refuse ces clés" in r.json()["detail"]
    assert client.get(url, headers=h["steven"]).json()["auto_actif"] is False
    fake_vopay.refus_cles = None
    # Code postal invalide : message clair.
    r = client.put(url, headers=h["steven"], json={**REGLAGES_AUTO, "code_postal": "12345"})
    assert r.status_code == 422 and "Code postal" in r.json()["detail"]

    r = client.put(url, headers=h["steven"], json=REGLAGES_AUTO)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["auto_actif"] is True and out["auto_environnement"] == "production"
    assert out["vopay_cles"] is True and out["interac_reponse"] is True
    assert out["province"] == "QC" and out["code_postal"] == "J2G 1A1" and out["auto_manque"] == []
    for secret in ("cle-api-0123456789", "secret-partage-0123456789", "Horizon2026"):
        assert secret not in r.text
    # Les clés ont été vérifiées chez VoPay, en production.
    assert fake_vopay.connexions[-1] == {
        "account_id": "horizon-inc", "cle": "cle-api-0123456789",
        "secret": "secret-partage-0123456789", "environnement": "production",
    }

    async def _reglage() -> PaiementReglage:
        async with TestSessionLocal() as s:
            return (await s.execute(select(PaiementReglage).where(PaiementReglage.entreprise_id == eid))).scalar_one()

    reg = run(_reglage())
    assert reg.vopay_cle_chiffree != "cle-api-0123456789"
    assert decrypt_secret(reg.vopay_cle_chiffree) == "cle-api-0123456789"
    assert decrypt_secret(reg.interac_reponse_chiffree) == "Horizon2026"

    # Phil est prévenu ; le journal le dit.
    assert "Réglages des paiements modifiés" in _notifs(run, equipe["ids"]["phil"])
    r = client.get(f"/api/v1/paiements/entreprises/{eid}/journal", headers=h["steven"])
    assert any("paiement automatique activé" in (j["detail"] or "") for j in r.json())

    # Un ancien formulaire (sans les champs VoPay) ne change rien au paiement automatique.
    anciens = {k: v for k, v in REGLAGES_AUTO.items() if k in (
        "numero_organisme", "nom_court", "nom_long", "retour_institution", "retour_transit",
        "retour_compte", "approbations_requises", "prochain_numero_fichier", "qbo_compte_banque_id")}
    r = client.put(url, headers=h["steven"], json=anciens)
    assert r.status_code == 200 and r.json()["auto_actif"] is True and r.json()["vopay_cles"] is True
    # Clés vides : gardées, sans nouvelle vérification.
    n = fake_vopay.nb("solde")
    r = client.put(url, headers=h["steven"], json={**REGLAGES_AUTO, "vopay_cle": "", "vopay_secret": None})
    assert r.status_code == 200 and r.json()["vopay_cles"] is True and fake_vopay.nb("solde") == n

    # Tester les clés enregistrées : approbateur seulement.
    assert client.post(f"/api/v1/paiements/entreprises/{eid}/vopay/tester", headers=h["technicienne"]).status_code == 403
    r = client.post(f"/api/v1/paiements/entreprises/{eid}/vopay/tester", headers=h["steven"])
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "environnement": "production", "solde": 1500.0, "disponible": 1250.5}

    # Les entreprises et les factures le savent : la date peut être aujourd'hui.
    ent = {e["entreprise_id"]: e for e in client.get("/api/v1/paiements/entreprises", headers=h["technicienne"]).json()}
    assert ent[eid]["paiement_auto"] is True and ent[eid]["auto_environnement"] == "production"
    r = client.get(f"/api/v1/paiements/entreprises/{eid}/factures", headers=h["technicienne"])
    assert r.json()["paiement_auto"] is True and r.json()["premiere_date"] == AUJOURDHUI

    # Effacer le compte VoPay désactive le paiement automatique.
    r = client.put(url, headers=h["steven"], json={**REGLAGES_AUTO, "auto_actif": None, "vopay_effacer": True})
    assert r.status_code == 200, r.text
    assert r.json()["auto_actif"] is False and r.json()["vopay_cles"] is False and r.json()["vopay_account_id"] is None


# ── Parcours complet : dépôt direct, production ──────────────────────


def test_paiement_automatique_depot_direct(client, run, equipe, inc, fake_qbo, fake_vopay):
    h = equipe["h"]
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid)
    _coordonnees(client, run, equipe, eid)
    lot_id = _lot_soumis(client, equipe, eid)

    # Avant l'approbation, le lot annonce le paiement automatique.
    d = _detail(client, equipe, lot_id, "phil")
    assert d["auto_entreprise"] is True and d["envoi_auto"] is False and d["auto"] is None

    # Phil approuve : le prélèvement part tout de suite.
    d = _approuver(client, run, equipe, lot_id)
    assert d["statut"] == "prelevement" and d["statut_libelle"] == "Prélèvement en cours"
    assert d["envoi_auto"] is True and d["auto_environnement"] == "production"
    assert d["actions"]["creer_fichier"] is False and d["actions"]["annuler"] is False
    prelevement = d["auto"]["prelevement"]
    assert prelevement["statut"] == "en_cours" and prelevement["montant"] == 1750.5
    [p] = fake_vopay.creees("prelevement")
    assert p["montant_cents"] == 175050 and p["nom"] == inc["name"]
    assert (p["institution"], p["transit"], p["compte"]) == ("815", "30001", "1234567")
    assert p["adresse"] == Adresse("123, rue Principale", "Granby", "QC", "J2G 1A1")
    assert p["reference"] == f"KRATOS-L{lot_id}-P1" and prelevement["transaction_id"] == fake_vopay.par_cle[p["cle"]]
    # Le fichier et l'envoi manuels ne s'appliquent pas.
    assert client.post(f"/api/v1/paiements/lots/{lot_id}/fichier", headers=h["steven"], json={}).status_code == 409
    # Le lot ne s'annule plus : l'argent est en route.
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/annuler", headers=h["steven"], json={"motif": "test"})
    assert r.status_code == 409
    # Les factures restent réservées à ce lot.
    r = client.post(
        f"/api/v1/paiements/entreprises/{eid}/lots", headers=h["technicienne"],
        json={"date_paiement": AUJOURDHUI, "lignes": [{"qbo_bill_id": "300", "montant": 10}]},
    )
    assert r.status_code == 409

    # Prélèvement encore en cours : rien ne bouge.
    _passer(run, minutes=31)
    assert _detail(client, equipe, lot_id)["statut"] == "prelevement"
    assert fake_vopay.nb("depot") == 0

    # VoPay confirme le prélèvement : un dépôt par fournisseur.
    fake_vopay.regler("successful", sorte="prelevement")
    _passer(run, minutes=31)
    d = _detail(client, equipe, lot_id)
    assert d["statut"] == "envoi" and d["preleve_le"]
    depots = {t["nom"]: t for t in fake_vopay.creees("depot")}
    assert set(depots) == {"Rona", "Ébénisterie Côté"}
    assert depots["Rona"]["montant_cents"] == 125050 and depots["Rona"]["compte"] == "5512345"
    assert depots["Rona"]["adresse"] == Adresse("220, chemin du Tremblay", "Boucherville", "QC", "J4B 6Z6")
    assert depots["Ébénisterie Côté"]["montant_cents"] == 50000
    assert (depots["Ébénisterie Côté"]["institution"], depots["Ébénisterie Côté"]["transit"]) == ("006", "12345")
    assert depots["Rona"]["note"].startswith(f"Lot Kratos n° {lot_id} : ")
    assert {f["fournisseur"]: f["operation"]["statut"] for f in d["auto"]["paiements_auto"]} == {
        "Rona": "en_cours", "Ébénisterie Côté": "en_cours"}

    # Un seul paiement réussi : le lot attend l'autre.
    fake_vopay.regler("successful", sorte="depot", nom="Rona")
    _passer(run, minutes=31)
    assert _detail(client, equipe, lot_id)["statut"] == "envoi"

    # Les deux : payé, inscrit dans QuickBooks.
    fake_vopay.regler("successful", sorte="depot")
    _passer(run, minutes=31)
    d = _detail(client, equipe, lot_id)
    assert d["statut"] == "paye", d
    assert d["auto_erreur"] is None and d["actions"]["enregistrer_qbo"] is False
    paiements = {p["DocNumber"]: p for p in fake_qbo.paiements}
    assert set(paiements) == {f"VOP-{lot_id}-56", f"VOP-{lot_id}-57"}
    assert paiements[f"VOP-{lot_id}-56"]["TotalAmt"] == 1250.5 and paiements[f"VOP-{lot_id}-56"]["TxnDate"] == AUJOURDHUI
    assert "transaction VoPay" in paiements[f"VOP-{lot_id}-56"]["PrivateNote"]
    assert fake_qbo.bills["300"]["Balance"] == 0 and fake_qbo.bills["302"]["Balance"] == 1000.0
    assert "Fournisseurs payés" in _notifs(run, equipe["ids"]["technicienne"])

    # Jamais de double paiement : d'autres passages ne renvoient rien.
    _passer(run, hours=3)
    _passer(run, hours=3)
    assert fake_vopay.nb("prelevement") == 1 and fake_vopay.nb("depot") == 2
    ops = _operations(run, lot_id)
    assert len({o.cle_idempotence for o in ops}) == len(ops) == 3
    assert {"vopay_envoye", "vopay_reussi", "paiements_termines", "qbo_enregistre"} <= set(_journal(run, lot_id))


# ── Interac, environnement de test ───────────────────────────────────


def test_paiement_automatique_interac_en_test(client, run, equipe, inc, fake_qbo, fake_vopay):
    h = equipe["h"]
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid, auto_environnement="test")
    _coordonnees(client, run, equipe, eid, mode="interac")
    lot_id = _lot_soumis(client, equipe, eid, mode="interac")
    d = _approuver(client, run, equipe, lot_id)
    assert d["statut"] == "prelevement" and d["auto_environnement"] == "test"
    assert d["virements"] == [] and d["actions"]["preparer_envoi"] is False
    assert all(c["environnement"] == "test" for c in fake_vopay.connexions)

    fake_vopay.regler("successful", sorte="prelevement")
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/auto/verifier", headers=h["technicienne"])
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "envoi"
    virements = {t["nom"]: t for t in fake_vopay.creees("interac")}
    assert virements["Rona"]["destinataire"] == "comptes@rona.ca"
    assert virements["Rona"]["message"] == "Paiement des factures F-100, F-101"
    assert virements["Ébénisterie Côté"]["destinataire"] == "4505551234"
    assert virements["Rona"]["question"] == "Nom de notre entreprise ?" and virements["Rona"]["reponse"] == "Horizon2026"
    assert virements["Rona"]["expediteur"] == inc["name"]

    # « sent » : le fournisseur n'a pas encore accepté.
    fake_vopay.regler("sent", sorte="interac")
    _passer(run, minutes=6)
    assert _detail(client, equipe, lot_id)["statut"] == "envoi"
    fake_vopay.regler("successful", sorte="interac")
    _passer(run, minutes=6)
    d = _detail(client, equipe, lot_id)
    assert d["statut"] == "paye" and d["statut_libelle"] == "Terminé (test)"
    # Environnement de test : rien dans QuickBooks, les factures restent à payer.
    assert fake_qbo.paiements == []
    assert "test_termine" in _journal(run, lot_id)
    r = client.get(f"/api/v1/paiements/entreprises/{eid}/factures", headers=h["technicienne"])
    assert {f["qbo_bill_id"]: f["lot_id"] for f in r.json()["factures"]}["300"] is None
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/quickbooks", headers=h["steven"])
    assert r.status_code == 409


def test_lot_de_test_abandonne(client, run, equipe, inc, fake_qbo, fake_vopay):
    h = equipe["h"]
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid, auto_environnement="test")
    _coordonnees(client, run, equipe, eid)
    lot_id = _lot_soumis(client, equipe, eid)
    d = _approuver(client, run, equipe, lot_id)
    assert d["statut"] == "prelevement" and d["actions"]["annuler"] is True
    # Changer d'environnement pendant qu'un paiement est en route : refusé.
    _confirmer(run, equipe["ids"]["steven"])
    r = client.put(
        f"/api/v1/paiements/entreprises/{eid}/reglages", headers=h["steven"],
        json={**REGLAGES_AUTO, "auto_environnement": "production"},
    )
    assert r.status_code == 409 and f"n° {lot_id}" in r.json()["detail"]
    # Un lot de test s'abandonne (aucun argent réel), avec un motif.
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/annuler", headers=h["steven"], json={})
    assert r.status_code == 422
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/annuler", headers=h["steven"], json={"motif": "Fin du test"})
    assert r.status_code == 200 and r.json()["statut"] == "annule"
    assert {o.statut for o in _operations(run, lot_id)} == {"annule"}
    # Plus rien en route : la production peut être activée.
    r = client.put(
        f"/api/v1/paiements/entreprises/{eid}/reglages", headers=h["steven"],
        json={**REGLAGES_AUTO, "auto_environnement": "production"},
    )
    assert r.status_code == 200 and r.json()["auto_environnement"] == "production"


# ── Prélèvement refusé ───────────────────────────────────────────────


def test_prelevement_refuse_puis_reessaye(client, run, equipe, inc, fake_qbo, fake_vopay):
    h = equipe["h"]
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid)
    _coordonnees(client, run, equipe, eid)
    lot_id = _lot_soumis(client, equipe, eid)
    _approuver(client, run, equipe, lot_id)

    fake_vopay.regler("failed", sorte="prelevement", raison="NSF : fonds insuffisants")
    _passer(run, minutes=31)
    d = _detail(client, equipe, lot_id)
    assert d["statut"] == "echec" and "NSF" in d["auto_erreur"]
    assert d["actions"]["reessayer_auto"] is True and d["actions"]["annuler"] is True
    assert d["actions"]["remettre_en_brouillon"] is True
    assert fake_vopay.nb("depot") == 0
    assert "Prélèvement refusé" in _notifs(run, equipe["ids"]["technicienne"])
    assert "Prélèvement refusé" in _notifs(run, equipe["ids"]["steven"])
    # La technicienne ne voit pas le bouton et ne peut pas réessayer.
    assert _detail(client, equipe, lot_id, "technicienne")["actions"]["reessayer_auto"] is False
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/auto/reessayer", headers=h["technicienne"], json={})
    assert r.status_code == 403
    # Steven réessaie : code de double authentification exigé.
    _oublier(run, equipe["ids"]["steven"])
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/auto/reessayer", headers=h["steven"], json={})
    assert r.status_code == 428 and r.json()["deux_facteurs"] == "requis"
    _confirmer(run, equipe["ids"]["steven"])
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/auto/reessayer", headers=h["steven"], json={})
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "prelevement"
    prelevements = [o for o in _operations(run, lot_id) if o.sorte == "prelevement"]
    assert [o.statut for o in prelevements] == ["echoue", "en_cours"]
    assert prelevements[0].cle_idempotence != prelevements[1].cle_idempotence
    assert prelevements[1].reference == f"KRATOS-L{lot_id}-P2"


def test_prelevement_refuse_remis_en_brouillon(client, run, equipe, inc, fake_qbo, fake_vopay):
    h = equipe["h"]
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid)
    _coordonnees(client, run, equipe, eid)
    lot_id = _lot_soumis(client, equipe, eid)
    fake_vopay.pannes["prelevement"] = [VoPayErreur("Compte de l'entreprise invalide", code="2010")]
    d = _approuver(client, run, equipe, lot_id)
    assert d["statut"] == "echec" and "invalide" in d["auto_erreur"]
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/brouillon", headers=h["steven"])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["statut"] == "brouillon" and d["envoi_auto"] is False and d["auto_erreur"] is None


# ── Paiement refusé : retiré (l'argent revient) ou réessayé ─────────


def _lot_en_envoi(client, run, equipe, eid: int, fake_vopay: _FakeVoPay) -> int:
    _activer_auto(client, run, equipe, eid)
    _coordonnees(client, run, equipe, eid)
    lot_id = _lot_soumis(client, equipe, eid)
    _approuver(client, run, equipe, lot_id)
    fake_vopay.regler("successful", sorte="prelevement")
    return lot_id


def test_paiement_refuse_retire_et_retour(client, run, equipe, inc, fake_qbo, fake_vopay):
    h = equipe["h"]
    eid = inc["id"]
    lot_id = _lot_en_envoi(client, run, equipe, eid, fake_vopay)
    # Le dépôt à Ébénisterie Côté est refusé tout de suite, celui de Rona part.
    fake_vopay.refus["Ébénisterie Côté"] = VoPayErreur("Invalid account number", code="2010")
    _passer(run, minutes=31)
    d = _detail(client, equipe, lot_id)
    assert d["statut"] == "envoi"
    par_nom = {f["fournisseur"]: f for f in d["auto"]["paiements_auto"]}
    cote, rona = par_nom["Ébénisterie Côté"], par_nom["Rona"]
    assert rona["operation"]["statut"] == "en_cours"
    assert cote["operation"]["statut"] == "echoue" and "Invalid account number" in cote["operation"]["erreur"]
    assert cote["peut_retirer"] is True and cote["operation"]["peut_reessayer"] is True
    assert rona["peut_retirer"] is False
    assert "Paiement refusé" in _notifs(run, equipe["ids"]["steven"])

    # L'autre est payé : le lot attend la décision pour le refusé.
    fake_vopay.regler("successful", sorte="depot")
    _passer(run, minutes=31)
    assert _detail(client, equipe, lot_id)["statut"] == "envoi"

    # La technicienne ne peut pas retirer ; Steven, avec motif et code.
    url = f"/api/v1/paiements/lots/{lot_id}/paiements/{cote['fournisseur_id']}/retirer"
    assert client.post(url, headers=h["technicienne"], json={"motif": "x"}).status_code == 403
    _confirmer(run, equipe["ids"]["steven"])
    assert client.post(url, headers=h["steven"], json={}).status_code == 422
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/paiements/{rona['fournisseur_id']}/retirer",
                    headers=h["steven"], json={"motif": "x"})
    assert r.status_code == 409  # déjà payé
    r = client.post(url, headers=h["steven"], json={"motif": "Compte fermé, on paiera par chèque"})
    assert r.status_code == 200, r.text
    d = r.json()
    # Le reste est payé : inscrit dans QuickBooks, lot payé ; le montant retiré revient à l'entreprise.
    assert d["statut"] == "paye", d
    assert [l["fournisseur"] for l in d["lignes"]] == [rona["fournisseur"]] * len(d["lignes"])
    retour = d["auto"]["retours"][0]
    assert retour["statut"] == "en_cours" and retour["montant"] == cote["montant"]
    [r_vopay] = [t for t in fake_vopay.creees("depot") if t["reference"].startswith(f"KRATOS-L{lot_id}-R")]
    assert (r_vopay["institution"], r_vopay["transit"], r_vopay["compte"]) == ("815", "30001", "1234567")
    assert r_vopay["nom"] == inc["name"] and r_vopay["montant_cents"] == int(round(cote["montant"] * 100))
    assert [p["DocNumber"] for p in fake_qbo.paiements] == [f"VOP-{lot_id}-{rona['fournisseur_id']}"]
    # Ses factures redeviennent à payer ; celles de Rona sont payées.
    r = client.get(f"/api/v1/paiements/entreprises/{eid}/factures", headers=h["technicienne"])
    libres = {f["qbo_bill_id"]: f["lot_id"] for f in r.json()["factures"]}
    assert libres["302"] is None and "300" not in libres and "301" not in libres
    # Le retour est suivi jusqu'au bout.
    fake_vopay.regler("successful", sorte="depot")
    _passer(run, minutes=31)
    assert _detail(client, equipe, lot_id)["auto"]["retours"][0]["statut"] == "reussi"
    assert "paiement_retire" in _journal(run, lot_id)


def test_paiement_refuse_reessaye_avec_nouvelles_coordonnees(client, run, equipe, inc, fake_qbo, fake_vopay):
    h = equipe["h"]
    eid = inc["id"]
    lot_id = _lot_en_envoi(client, run, equipe, eid, fake_vopay)
    _passer(run, minutes=31)
    fake_vopay.regler("failed", sorte="depot", nom="Ébénisterie Côté", raison="Account closed")
    fake_vopay.regler("successful", sorte="depot", nom="Rona")
    _passer(run, minutes=31)
    d = _detail(client, equipe, lot_id)
    cote = {f["fournisseur"]: f for f in d["auto"]["paiements_auto"]}["Ébénisterie Côté"]
    op_id = cote["operation"]["id"]
    assert cote["operation"]["statut"] == "echoue" and "Account closed" in cote["operation"]["erreur"]

    # Nouvelles coordonnées : saisies par la technicienne, approuvées par Phil.
    r = client.post(
        f"/api/v1/paiements/entreprises/{eid}/comptes", headers=h["technicienne"],
        json={"fournisseur_id": "57", "institution": "815", "transit": "77777", "numero_compte": "4444444"},
    )
    assert r.status_code == 200, r.text
    _confirmer(run, equipe["ids"]["phil"])
    r = client.post(f"/api/v1/paiements/comptes/{r.json()['id']}/approuver", headers=h["phil"], json={})
    assert r.status_code == 200, r.text

    # Steven réessaie : les factures sont relues, le dépôt part au nouveau compte.
    _confirmer(run, equipe["ids"]["steven"])
    r = client.post(
        f"/api/v1/paiements/lots/{lot_id}/auto/reessayer", headers=h["steven"], json={"operation_id": op_id}
    )
    assert r.status_code == 200, r.text
    nouveau = [t for t in fake_vopay.creees("depot") if t["nom"] == "Ébénisterie Côté"][-1]
    assert (nouveau["transit"], nouveau["compte"]) == ("77777", "4444444")
    assert nouveau["reference"] == f"KRATOS-L{lot_id}-F57-2"
    d = r.json()
    assert {l["compte"]["transit"] for l in d["lignes"] if l["fournisseur_id"] == "57"} == {"77777"}
    # Déjà repris : un deuxième essai sur l'ancienne opération est refusé.
    r = client.post(
        f"/api/v1/paiements/lots/{lot_id}/auto/reessayer", headers=h["steven"], json={"operation_id": op_id}
    )
    assert r.status_code == 409
    fake_vopay.regler("successful", sorte="depot")
    _passer(run, minutes=31)
    assert _detail(client, equipe, lot_id)["statut"] == "paye"


def test_facture_payee_ailleurs_bloque_le_paiement(client, run, equipe, inc, fake_qbo, fake_vopay):
    eid = inc["id"]
    lot_id = _lot_en_envoi(client, run, equipe, eid, fake_vopay)
    # Quelqu'un paie la facture de Rona directement dans QuickBooks entre-temps.
    fake_qbo.bills["301"]["Balance"] = 0
    _passer(run, minutes=31)
    d = _detail(client, equipe, lot_id)
    rona = {f["fournisseur"]: f for f in d["auto"]["paiements_auto"]}["Rona"]
    assert rona["operation"]["statut"] == "echoue" and "déjà été payée" in rona["operation"]["erreur"]
    # Rien n'est parti chez VoPay pour Rona.
    assert [t["nom"] for t in fake_vopay.creees("depot")] == ["Ébénisterie Côté"]


# ── Réponse perdue : même clé, puis vérification ─────────────────────


def test_reponse_perdue_reprise_avec_la_meme_cle(client, run, equipe, inc, fake_qbo, fake_vopay):
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid)
    _coordonnees(client, run, equipe, eid)
    lot_id = _lot_soumis(client, equipe, eid)
    # La demande ne s'est pas rendue : reprise avec la même clé, acceptée.
    fake_vopay.pannes["prelevement"] = [VoPayIncertain("VoPay n'a pas répondu à la demande.")]
    d = _approuver(client, run, equipe, lot_id)
    assert d["auto"]["prelevement"]["statut"] == "incertain"
    _passer(run, minutes=5)
    assert fake_vopay.nb("prelevement") == 1  # pas avant 10 minutes
    _passer(run, minutes=6)
    [op] = _operations(run, lot_id)
    assert op.statut == "en_cours" and op.tentatives == 2
    cles = [kw["cle"] for s, kw in fake_vopay.appels if s == "prelevement"]
    assert cles == [op.cle_idempotence, op.cle_idempotence]
    assert len(fake_vopay.creees("prelevement")) == 1


def test_reponse_perdue_puis_verifiee_par_un_approbateur(client, run, equipe, inc, fake_qbo, fake_vopay):
    h = equipe["h"]
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid)
    _coordonnees(client, run, equipe, eid)
    lot_id = _lot_soumis(client, equipe, eid)
    # Le prélèvement est créé chez VoPay, mais la réponse se perd ; la
    # reprise avec la même clé est refusée (doublon) : un approbateur vérifie.
    fake_vopay.reponses_perdues.add("prelevement")
    _approuver(client, run, equipe, lot_id)
    _passer(run, minutes=11)
    d = _detail(client, equipe, lot_id)
    op = d["auto"]["prelevement"]
    assert op["statut"] == "a_verifier" and op["peut_resoudre"] is True
    assert d["auto"]["a_verifier"] == 1 and d["statut"] == "prelevement"
    assert len(fake_vopay.creees("prelevement")) == 1  # jamais deux prélèvements
    assert "Paiement à vérifier dans VoPay" in _notifs(run, equipe["ids"]["phil"])
    assert _detail(client, equipe, lot_id, "technicienne")["auto"]["prelevement"]["peut_resoudre"] is False

    url = f"/api/v1/paiements/lots/{lot_id}/operations/{op['id']}/resoudre"
    assert client.post(url, headers=h["technicienne"], json={"parti": True, "transaction_id": "1"}).status_code == 403
    _confirmer(run, equipe["ids"]["steven"])
    r = client.post(url, headers=h["steven"], json={"parti": True})
    assert r.status_code == 422 and "numéro de transaction" in r.json()["detail"]
    [tid] = list(fake_vopay.transactions)
    fake_vopay.regler("successful", sorte="prelevement")
    r = client.post(url, headers=h["steven"], json={"parti": True, "transaction_id": f" {tid} "})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["auto"]["prelevement"]["statut"] == "reussi" and d["auto"]["prelevement"]["transaction_id"] == tid
    assert d["statut"] == "envoi" and len(fake_vopay.creees("depot")) == 2


def test_reponse_perdue_pas_partie(client, run, equipe, inc, fake_qbo, fake_vopay):
    h = equipe["h"]
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid)
    _coordonnees(client, run, equipe, eid)
    lot_id = _lot_soumis(client, equipe, eid)
    fake_vopay.pannes["prelevement"] = [VoPayIncertain("perdue"), VoPayIncertain("perdue encore")]
    _approuver(client, run, equipe, lot_id)
    _passer(run, minutes=11)
    op = _detail(client, equipe, lot_id)["auto"]["prelevement"]
    assert op["statut"] == "a_verifier"
    _confirmer(run, equipe["ids"]["steven"])
    r = client.post(
        f"/api/v1/paiements/lots/{lot_id}/operations/{op['id']}/resoudre", headers=h["steven"], json={"parti": False}
    )
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "echec" and r.json()["actions"]["reessayer_auto"] is True


def test_envoi_interrompu_devient_incertain(client, run, equipe, inc, fake_qbo, fake_vopay):
    """Serveur arrêté pendant l'envoi : l'opération reste « envoi », puis
    est reprise avec la même clé."""
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid)
    _coordonnees(client, run, equipe, eid)
    lot_id = _lot_soumis(client, equipe, eid)
    fake_vopay.pannes["prelevement"] = [VoPayErreur("Service unavailable", temporaire=True)]
    _approuver(client, run, equipe, lot_id)
    [op] = _operations(run, lot_id)
    assert op.statut == "a_envoyer" and op.tentatives == 1

    async def _envoi() -> None:
        async with TestSessionLocal() as s:
            o = await s.get(PaiementOperation, op.id)
            o.statut = "envoi"
            o.prochain_essai = HORLOGE[0] + timedelta(minutes=15)
            await s.commit()

    run(_envoi())
    _passer(run, minutes=16)
    [op] = _operations(run, lot_id)
    assert op.statut == "incertain" and op.incertain_le is not None
    _passer(run, minutes=11)
    [op] = _operations(run, lot_id)
    assert op.statut == "en_cours"
    assert {kw["cle"] for s, kw in fake_vopay.appels if s == "prelevement"} == {op.cle_idempotence}


def test_vopay_injoignable_reessaye_plus_tard(client, run, equipe, inc, fake_qbo, fake_vopay):
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid)
    _coordonnees(client, run, equipe, eid)
    lot_id = _lot_soumis(client, equipe, eid)
    fake_vopay.pannes["prelevement"] = [
        VoPayErreur("VoPay ne répond pas pour l'instant.", temporaire=True),
        VoPayErreur("Insufficient balance", code="3001"),
    ]
    _approuver(client, run, equipe, lot_id)
    [op] = _operations(run, lot_id)
    assert op.statut == "a_envoyer" and "ne répond pas" in op.erreur
    _passer(run, minutes=6)
    [op] = _operations(run, lot_id)
    assert op.statut == "a_envoyer" and "Solde ou limite" in op.erreur
    _passer(run, minutes=10)
    assert fake_vopay.nb("prelevement") == 2  # 15 minutes après le deuxième essai
    _passer(run, minutes=6)
    [op] = _operations(run, lot_id)
    assert op.statut == "en_cours" and op.tentatives == 3


# ── Ce qui attend : date future, adresse manquante, réglages ────────


def test_date_future_attend(client, run, equipe, inc, fake_qbo, fake_vopay):
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid)
    _coordonnees(client, run, equipe, eid)
    lot_id = _lot_soumis(client, equipe, eid, date="2026-10-07")
    d = _approuver(client, run, equipe, lot_id)
    assert d["statut"] == "approuve" and d["statut_libelle"] == "Paiement prévu" and d["envoi_auto"] is True
    assert fake_vopay.nb("prelevement") == 0
    _passer(run, days=1)
    assert fake_vopay.nb("prelevement") == 0
    _passer(run, days=1)
    assert fake_vopay.nb("prelevement") == 1
    assert _detail(client, equipe, lot_id)["statut"] == "prelevement"


def test_adresse_manquante_bloque_avant_le_prelevement(client, run, equipe, inc, fake_qbo, fake_vopay):
    h = equipe["h"]
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid)
    _coordonnees(client, run, equipe, eid)
    del fake_qbo.vendors[1]["BillAddr"]
    lot_id = _lot_soumis(client, equipe, eid)
    d = _approuver(client, run, equipe, lot_id)
    assert d["statut"] == "approuve" and "Ébénisterie Côté" in d["auto_erreur"]
    assert d["actions"]["reessayer_auto"] is True
    assert fake_vopay.nb("prelevement") == 0
    assert "Paiement automatique en attente" in _notifs(run, equipe["ids"]["steven"])
    # Toujours bloqué au passage suivant : pas de nouvelle notification.
    nb = _notifs(run, equipe["ids"]["steven"]).count("Paiement automatique en attente")
    _passer(run, minutes=31)
    assert _notifs(run, equipe["ids"]["steven"]).count("Paiement automatique en attente") == nb
    # L'adresse est complétée dans QuickBooks : Steven relance tout de suite.
    fake_qbo.vendors[1]["BillAddr"] = dict(ADRESSES["57"])
    _confirmer(run, equipe["ids"]["steven"])
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/auto/reessayer", headers=h["steven"], json={})
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "prelevement" and r.json()["auto_erreur"] is None


def test_auto_desactive_avant_le_jour_du_lot(client, run, equipe, inc, fake_qbo, fake_vopay):
    h = equipe["h"]
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid)
    _coordonnees(client, run, equipe, eid)
    lot_id = _lot_soumis(client, equipe, eid, date="2026-10-06")
    _approuver(client, run, equipe, lot_id)
    _activer_auto(client, run, equipe, eid, auto_actif=False)
    _passer(run, days=1)
    d = _detail(client, equipe, lot_id)
    assert d["statut"] == "approuve" and "désactivé" in d["auto_erreur"]
    assert fake_vopay.nb("prelevement") == 0
    # Un approbateur l'annule (rien n'est parti).
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/annuler", headers=h["steven"], json={"motif": "Payé autrement"})
    assert r.status_code == 200 and r.json()["statut"] == "annule"


def test_entreprise_sans_paiement_automatique_inchangee(client, run, equipe, inc, fake_qbo, fake_vopay):
    """Sans le réglage, le lot suit le parcours manuel (fichier de dépôt)."""
    eid = inc["id"]
    _activer_auto(client, run, equipe, eid, auto_actif=False)
    _coordonnees(client, run, equipe, eid)
    r = client.get(f"/api/v1/paiements/entreprises/{eid}/factures", headers=equipe["h"]["technicienne"])
    assert r.json()["paiement_auto"] is False and r.json()["premiere_date"] == "2026-10-07"
    lot_id = _lot_soumis(client, equipe, eid, date="2026-10-07")
    d = _approuver(client, run, equipe, lot_id)
    assert d["statut"] == "approuve" and d["envoi_auto"] is False and d["actions"]["creer_fichier"] is True
    _passer(run, days=3)
    assert fake_vopay.appels == [] or all(s == "solde" for s, _ in fake_vopay.appels)
    assert _detail(client, equipe, lot_id)["statut"] == "approuve"
