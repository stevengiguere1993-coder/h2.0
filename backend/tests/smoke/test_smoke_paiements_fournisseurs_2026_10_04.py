"""Smoke — paiements fournisseurs par dépôt direct Desjardins (Steven, 2026-10-04).

Onglet « Paiements » de la section Comptabilité : la technicienne prépare
un lot de factures QuickBooks, une AUTRE personne l'approuve avec sa double
authentification, un approbateur crée le fichier de dépôt direct (norme
005) à transmettre dans AccèsD Affaires, puis les paiements sont inscrits
dans QuickBooks.

Client QuickBooks factice : aucun appel réseau. L'heure des paiements est
figée au lundi 5 octobre 2026, 9 h (Toronto) ; les codes de double
authentification suivent la vraie horloge.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.models.entreprise import Entreprise
from app.models.notification import Notification
from app.models.paiement_fournisseur import FournisseurCompteBancaire, Utilisateur2FA
from app.models.qbo_connection import QboConnection
from app.models.user import User
from app.models.user_access_override import UserAccessOverride
from app.services import cpa005, totp
from app.services import paiements_fournisseurs as svc

from .conftest import TestSessionLocal

FIGE = datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)  # lundi 9 h à Toronto
DEPOT = "2026-10-07"  # mercredi : deux jours ouvrables après lundi matin
MOT_DE_PASSE = "smoke-paiements-x"
CLE_COFFRE = Fernet.generate_key().decode()


# ── Environnement ────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def _environnement():
    mp = pytest.MonkeyPatch()
    mp.setattr(settings, "subscription_encryption_key", CLE_COFFRE)
    mp.setattr(svc, "_maintenant", lambda: FIGE)
    yield
    mp.undo()


def _facture(bid: str, vid: str, nom: str, numero: str, total: float, solde: float, devise: str = "CAD"):
    return {
        "Id": bid,
        "VendorRef": {"value": vid, "name": nom},
        "DocNumber": numero,
        "TxnDate": "2026-09-20",
        "DueDate": "2026-10-20",
        "TotalAmt": total,
        "Balance": solde,
        "CurrencyRef": {"value": devise},
    }


class _FakeQbo:
    ready = True
    realm_id = "9130"

    def __init__(self) -> None:
        self.vendors = [
            {"Id": "56", "DisplayName": "Rona"},
            {"Id": "57", "DisplayName": "Ébénisterie Côté"},
        ]
        self.bills: Dict[str, Dict[str, Any]] = {
            b["Id"]: b
            for b in [
                _facture("300", "56", "Rona", "F-100", 1000.00, 1000.00),
                _facture("301", "56", "Rona", "F-101", 250.50, 250.50),
                _facture("302", "57", "Ébénisterie Côté", "EC-7", 4000.00, 1500.00),
                _facture("303", "56", "Rona", "F-102", 80.00, 80.00),
                _facture("304", "57", "Ébénisterie Côté", "EC-8", 99.00, 99.00, devise="USD"),
            ]
        }
        self.paiements: List[Dict[str, Any]] = []

    async def query_all(self, sql: str) -> List[Dict[str, Any]]:
        if "FROM Bill" in sql:
            return [dict(b) for b in self.bills.values() if b["Balance"] > 0]
        if "FROM Account" in sql:
            return [{"Id": "35", "Name": "Desjardins", "FullyQualifiedName": "Desjardins", "AccountType": "Bank"}]
        if "FROM Vendor" in sql:
            return list(self.vendors)
        return []

    async def query(self, sql: str) -> List[Dict[str, Any]]:
        if "FROM Vendor" in sql:
            vid = sql.split("Id = '", 1)[1].split("'", 1)[0]
            return [v for v in self.vendors if v["Id"] == vid]
        if "FROM BillPayment" in sql:
            doc = sql.split("DocNumber = '", 1)[1].split("'", 1)[0]
            return [p for p in self.paiements if p["DocNumber"] == doc]
        return []

    async def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        if account_id == "35":
            return {"Id": "35", "Name": "Desjardins", "FullyQualifiedName": "Desjardins", "AccountType": "Bank"}
        return {"Id": account_id, "Name": "Dépenses", "AccountType": "Expense"}

    async def get_bill(self, bill_id: str) -> Dict[str, Any]:
        return dict(self.bills[bill_id])

    async def create_bill_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        bp = {**json.loads(json.dumps(payload)), "Id": str(900 + len(self.paiements))}
        self.paiements.append(bp)
        for ligne in payload["Line"]:
            for lien in ligne["LinkedTxn"]:
                b = self.bills[lien["TxnId"]]
                b["Balance"] = round(b["Balance"] - ligne["Amount"], 2)
        return bp


@pytest.fixture()
def fake_qbo(monkeypatch) -> _FakeQbo:
    fake = _FakeQbo()
    # get_qbo est importé LOCALEMENT dans le service : patcher la source suffit.
    monkeypatch.setattr("app.integrations.quickbooks.get_qbo", lambda scope: fake)
    return fake


@pytest.fixture()
def inc(run) -> Dict[str, Any]:
    """Une inc avec SA compagnie QuickBooks connectée (scope inc:{id})."""

    async def _seed() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            e = Entreprise(name=f"9999-{uuid.uuid4().hex[:4]} Québec inc.")
            s.add(e)
            await s.flush()
            s.add(
                QboConnection(
                    scope=f"inc:{e.id}",
                    refresh_token="rt-smoke",
                    realm_id="9130",
                    environment="sandbox",
                    company_name="Inc Smoke",
                )
            )
            await s.commit()
            return {"id": e.id, "name": e.name}

    return run(_seed())


def _compte_utilisateur(run, role: str, *, comptabilite: bool = False) -> int:
    async def _seed() -> int:
        async with TestSessionLocal() as s:
            u = User(
                email=f"smoke-paiements-{role}-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password=get_password_hash(MOT_DE_PASSE),
                is_active=True,
                is_admin=role in ("owner", "admin"),
                role=role,
            )
            s.add(u)
            await s.flush()
            if comptabilite:
                # La technicienne : la section Comptabilité lui est ouverte
                # par exception, sans la capacité d'approuver.
                s.add(UserAccessOverride(user_id=u.id, key="page:entreprises.comptabilite", allow=True))
            await s.commit()
            return u.id

    return run(_seed())


def _entetes(user_id: int) -> Dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=str(user_id))}"}


@pytest.fixture(scope="module")
def equipe(client, run) -> Dict[str, Any]:
    ids = {
        "technicienne": _compte_utilisateur(run, "admin", comptabilite=True),
        "steven": _compte_utilisateur(run, "owner"),
        "phil": _compte_utilisateur(run, "owner"),
    }
    return {"ids": ids, "h": {k: _entetes(v) for k, v in ids.items()}, "secrets": {}}


def _activer_2fa(client, equipe, qui: str) -> str:
    h = equipe["h"][qui]
    r = client.post("/api/v1/paiements/2fa/debut", headers=h, json={"mot_de_passe": MOT_DE_PASSE})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    assert r.json()["uri"].startswith("otpauth://totp/Kratos:")
    assert (r.json()["qr"] or "").startswith("data:image/svg+xml")
    r = client.post("/api/v1/paiements/2fa/activer", headers=h, json={"code_2fa": totp.code(secret)})
    assert r.status_code == 200, r.text
    assert r.json()["actif"] is True
    equipe["secrets"][qui] = secret
    return secret


def _oublier_confirmation(run, user_id: int) -> None:
    """La confirmation de 5 minutes expire : le prochain geste redemande un code."""

    async def _do() -> None:
        async with TestSessionLocal() as s:
            ligne = (
                await s.execute(select(Utilisateur2FA).where(Utilisateur2FA.user_id == user_id))
            ).scalar_one()
            ligne.confirme_jusqu_a = None
            await s.commit()

    run(_do())


REGLAGES = {
    "numero_organisme": "0123456789",
    "nom_court": "Horizon inc",
    "nom_long": "Horizon Services Immobiliers",
    "retour_institution": "815",
    "retour_transit": "30001",
    "retour_compte": "1234567",
    "approbations_requises": 1,
    "prochain_numero_fichier": 7,
}


# ── Double authentification (RFC 6238) ──────────────────────────────


def test_totp_vecteurs_rfc6238():
    cle = b"12345678901234567890"
    # Annexe B de la RFC 6238 (SHA-1, 8 chiffres, pas de 30 s).
    for t, attendu in [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ]:
        assert totp.code_hotp(cle, t // 30, chiffres=8) == attendu
    secret = totp.nouveau_secret()
    assert len(secret) == 32 and "=" not in secret
    maintenant = 1_800_000_000.0
    pas = totp.pas_courant(maintenant)
    bon = totp.code(secret, pas)
    assert totp.verifier(secret, bon, maintenant=maintenant) == pas
    assert totp.verifier(secret, bon[:3] + " " + bon[3:], maintenant=maintenant) == pas
    # Un pas d'écart toléré, pas deux.
    assert totp.verifier(secret, totp.code(secret, pas - 1), maintenant=maintenant) == pas - 1
    assert totp.verifier(secret, totp.code(secret, pas - 2), maintenant=maintenant) is None
    # Un code déjà utilisé ne repasse pas.
    assert totp.verifier(secret, bon, maintenant=maintenant, dernier_pas=pas) is None
    assert totp.verifier(secret, "12345", maintenant=maintenant) is None


# ── Fichier norme 005 ─────────────────────────────────────────────────


EMETTEUR = cpa005.Emetteur(
    numero_organisme="0123456789",
    nom_court="Horizon inc",
    nom_long="Horizon Services Immobiliers",
    retour_institution="815",
    retour_transit="30001",
    retour_compte="1234567",
)


def _depot(i: int, montant: int = 1000) -> cpa005.Depot:
    return cpa005.Depot(
        montant_cents=montant + i,
        institution="815",
        transit="9000" + str(i % 10),
        compte=f"55{i:05d}",
        beneficiaire="Ébénisterie Côté & Fils" if i == 0 else f"Fournisseur {i}",
        reference=f"KRATOS L1-{i + 1}",
        information="FACT EC-7",
    )


def test_cpa005_positions_et_relecture():
    depots = [_depot(i) for i in range(7)]
    contenu = cpa005.generer(
        EMETTEUR, depots, numero_fichier=7, date_creation=date(2026, 10, 5), date_depot=date(2026, 10, 7)
    )
    assert contenu.endswith("\r\n")
    lignes = contenu.split("\r\n")[:-1]
    # En-tête, 2 enregistrements de dépôts (6 + 1 segments), fin.
    assert [l[0] for l in lignes] == ["A", "C", "C", "Z"]
    assert all(len(l) == 1464 for l in lignes)
    assert contenu.isascii()

    a = lignes[0]
    assert a[1:10] == "000000001"
    assert a[10:20] == "0123456789"
    assert a[20:24] == "0007"
    assert a[24:30] == "026278"  # 5 octobre 2026 = 278e jour
    assert a[30:35] == "81510"
    assert a[35:55] == " " * 20
    assert a[55:58] == "CAD"
    assert a[58:] == " " * 1406

    c = lignes[1]
    assert c[1:10] == "000000002" and c[10:24] == "01234567890007"
    s = c[24:264]
    assert s[0:3] == "460"
    assert s[3:13] == "0000001000"
    assert s[13:19] == "026280"
    assert s[19:28] == "081590000"
    assert s[28:40] == "5500000     "
    assert s[40:62] == "0" * 22 and s[62:65] == "000"
    assert s[65:80] == "HORIZON INC    "
    assert s[80:110] == "EBENISTERIE COTE FILS".ljust(30)
    assert s[110:140] == "HORIZON SERVICES IMMOBILIERS".ljust(30)
    assert s[140:150] == "0123456789"
    assert s[150:169] == "KRATOS L1-1".ljust(19)
    assert s[169:178] == "081530001"
    assert s[178:190] == "1234567     "
    assert s[190:205] == "FACT EC-7".ljust(15)
    assert s[205:229] == " " * 24 and s[229:240] == "0" * 11
    # Deuxième enregistrement : un seul segment, les cinq autres en blanc.
    c2 = lignes[2]
    assert c2[24:264].strip() and c2[264:] == " " * 1200

    z = lignes[3]
    assert z[1:10] == "000000004" and z[10:24] == "01234567890007"
    assert z[24:46] == "0" * 22
    assert int(z[46:60]) == sum(d.montant_cents for d in depots)
    assert int(z[60:68]) == 7
    assert z[68:112] == "0" * 44 and z[112:] == " " * 1352

    lu = cpa005.lire(contenu)
    assert lu["numero_fichier"] == 7 and lu["nombre"] == 7
    assert lu["date_creation"] == "2026-10-05" and lu["centre_traitement"] == "81510"
    assert lu["depots"][0]["beneficiaire"] == "EBENISTERIE COTE FILS"
    assert lu["depots"][0]["date_depot"] == "2026-10-07"
    assert lu["depots"][6]["montant_cents"] == 1006


def test_cpa005_refuse_les_donnees_invalides():
    base = dict(numero_fichier=1, date_creation=date(2026, 10, 5), date_depot=date(2026, 10, 7))
    with pytest.raises(cpa005.FichierInvalide):
        cpa005.generer(cpa005.Emetteur(**{**EMETTEUR.__dict__, "numero_organisme": "12345"}), [_depot(1)], **base)
    with pytest.raises(cpa005.FichierInvalide):
        cpa005.generer(EMETTEUR, [cpa005.Depot(**{**_depot(1).__dict__, "compte": "12AB"})], **base)
    with pytest.raises(cpa005.FichierInvalide):
        cpa005.generer(EMETTEUR, [cpa005.Depot(**{**_depot(1).__dict__, "montant_cents": 0})], **base)
    with pytest.raises(cpa005.FichierInvalide):
        cpa005.generer(EMETTEUR, [], **base)
    with pytest.raises(cpa005.FichierInvalide):
        cpa005.generer(EMETTEUR, [_depot(1)], **{**base, "numero_fichier": 10000})
    # Un fichier altéré ne se relit pas.
    contenu = cpa005.generer(EMETTEUR, [_depot(1)], **base)
    with pytest.raises(cpa005.FichierInvalide):
        cpa005.lire(contenu.replace("0000001001", "0000009001", 1))


def test_premiere_date_possible():
    # Lundi 9 h → mercredi ; lundi 13 h → jeudi ; vendredi 9 h → mardi ;
    # samedi → mercredi (reçu lundi matin).
    assert svc.premiere_date_possible(datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)) == date(2026, 10, 7)
    assert svc.premiere_date_possible(datetime(2026, 10, 5, 17, 0, tzinfo=timezone.utc)) == date(2026, 10, 8)
    assert svc.premiere_date_possible(datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc)) == date(2026, 10, 13)
    assert svc.premiere_date_possible(datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)) == date(2026, 10, 14)


# ── Parcours complet ──────────────────────────────────────────────────


def test_parcours_complet(client, run, equipe, inc, fake_qbo, auth_headers):
    h = equipe["h"]
    eid = inc["id"]
    base = f"/api/v1/paiements/entreprises/{eid}"

    # La section est fermée à un admin ordinaire (propriétaires seulement).
    assert client.get("/api/v1/paiements/entreprises", headers=auth_headers).status_code == 403

    # La technicienne voit les factures à payer de l'inc.
    r = client.get(f"{base}/factures", headers=h["technicienne"])
    assert r.status_code == 200, r.text
    factures = {f["qbo_bill_id"]: f for f in r.json()["factures"]}
    assert set(factures) == {"300", "301", "302", "303", "304"}
    assert factures["302"]["solde"] == 1500.0 and factures["302"]["compte"] is None
    assert factures["304"]["payable"] is False  # en dollars américains
    assert r.json()["premiere_date"] == DEPOT

    # Elle saisit les coordonnées de Rona : en attente, numéro jamais renvoyé.
    r = client.post(
        f"{base}/comptes",
        headers=h["technicienne"],
        json={"fournisseur_id": "56", "institution": "815", "transit": "90001", "numero_compte": "55-12345"},
    )
    assert r.status_code == 200, r.text
    compte = r.json()
    assert compte["statut"] == "en_attente" and compte["fournisseur"] == "Rona"
    assert compte["compte_fin"] == "2345" and "5512345" not in json.dumps(compte)
    async def _chiffre() -> str:
        async with TestSessionLocal() as s:
            return (await s.get(FournisseurCompteBancaire, compte["id"])).compte_chiffre
    assert "5512345" not in run(_chiffre())

    # Elle ne peut pas les approuver ; Steven non plus sans double authentification.
    assert client.post(f"/api/v1/paiements/comptes/{compte['id']}/approuver", headers=h["technicienne"]).status_code == 403
    r = client.post(f"/api/v1/paiements/comptes/{compte['id']}/approuver", headers=h["steven"])
    assert r.status_code == 403 and r.json()["deux_facteurs"] == "a_activer"

    # Steven active la double authentification (mot de passe redemandé).
    r = client.post("/api/v1/paiements/2fa/debut", headers=h["steven"], json={"mot_de_passe": "faux"})
    assert r.status_code == 403
    secret = _activer_2fa(client, equipe, "steven")
    # Avant d'approuver, Steven compare le numéro complet à sa source ;
    # la technicienne, elle, ne le revoit jamais.
    r = client.post(f"/api/v1/paiements/comptes/{compte['id']}/reveler", headers=h["technicienne"], json={})
    assert r.status_code == 403
    r = client.post(f"/api/v1/paiements/comptes/{compte['id']}/reveler", headers=h["steven"], json={})
    assert r.status_code == 200 and r.json()["numero_compte"] == "5512345"
    r = client.post(f"/api/v1/paiements/comptes/{compte['id']}/approuver", headers=h["steven"], json={})
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "approuve" and r.json()["decide_par"]

    # Lot : Rona (2 factures) + Ébénisterie Côté sans coordonnées.
    lot_in = {
        "date_paiement": DEPOT,
        "lignes": [
            {"qbo_bill_id": "300", "montant": 1000},
            {"qbo_bill_id": "301", "montant": 250.5},
            {"qbo_bill_id": "302", "montant": 500},
        ],
    }
    r = client.post(f"{base}/lots", headers=h["technicienne"], json=lot_in)
    assert r.status_code == 200, r.text
    lot = r.json()
    assert lot["statut"] == "brouillon" and lot["total"] == 1750.5 and lot["nb_lignes"] == 3
    # Montant plus grand que le solde : refusé.
    trop = {**lot_in, "lignes": [{"qbo_bill_id": "303", "montant": 80.01}]}
    assert client.post(f"{base}/lots", headers=h["technicienne"], json=trop).status_code == 409
    # Une facture déjà dans un lot ne va pas dans un autre.
    double = {**lot_in, "lignes": [{"qbo_bill_id": "300", "montant": 10}]}
    assert client.post(f"{base}/lots", headers=h["technicienne"], json=double).status_code == 409
    # Date trop proche : Desjardins doit recevoir le fichier deux jours ouvrables avant.
    tot = {**lot_in, "date_paiement": "2026-10-06"}
    r = client.post(f"{base}/lots", headers=h["technicienne"], json=tot)
    assert r.status_code == 422 and "7 octobre 2026" in r.json()["detail"]

    r = client.post(f"/api/v1/paiements/lots/{lot['id']}/soumettre", headers=h["technicienne"])
    assert r.status_code == 409 and r.json()["fournisseurs"] == ["Ébénisterie Côté"]
    r = client.put(
        f"/api/v1/paiements/lots/{lot['id']}",
        headers=h["technicienne"],
        json={**lot_in, "lignes": lot_in["lignes"][:2]},
    )
    assert r.status_code == 200 and r.json()["total"] == 1250.5
    r = client.post(f"/api/v1/paiements/lots/{lot['id']}/soumettre", headers=h["technicienne"])
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "soumis"
    assert all(l["compte"]["compte_fin"] == "2345" for l in r.json()["lignes"])

    # Les approbateurs sont prévenus.
    async def _notifs(user_id: int) -> List[str]:
        async with TestSessionLocal() as s:
            rows = (await s.execute(select(Notification).where(Notification.user_id == user_id))).scalars().all()
            return [n.title for n in rows]
    assert "Paiements à approuver" in run(_notifs(equipe["ids"]["steven"]))

    # La technicienne ne peut pas approuver ; Steven doit redonner un code.
    assert client.post(f"/api/v1/paiements/lots/{lot['id']}/approuver", headers=h["technicienne"]).status_code == 403
    _oublier_confirmation(run, equipe["ids"]["steven"])
    r = client.post(f"/api/v1/paiements/lots/{lot['id']}/approuver", headers=h["steven"], json={})
    assert r.status_code == 428 and r.json()["deux_facteurs"] == "requis"
    r = client.post(
        f"/api/v1/paiements/lots/{lot['id']}/approuver", headers=h["steven"], json={"code_2fa": "000000"}
    )
    assert r.status_code == 403 and r.json()["deux_facteurs"] == "invalide"
    r = client.post(
        f"/api/v1/paiements/lots/{lot['id']}/approuver",
        headers=h["steven"],
        json={"code_2fa": totp.code(secret, totp.pas_courant() + 1)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "approuve"
    assert r.json()["actions"]["creer_fichier"] is True

    # Fichier : réglages manquants d'abord, puis le fichier norme 005.
    r = client.post(f"/api/v1/paiements/lots/{lot['id']}/fichier", headers=h["steven"], json={})
    assert r.status_code == 409 and "numéro d'organisme" in r.json()["manque"]
    _activer_2fa(client, equipe, "phil")
    r = client.put(f"{base}/reglages", headers=h["technicienne"], json=REGLAGES)
    assert r.status_code == 403
    r = client.put(f"{base}/reglages", headers=h["steven"], json={**REGLAGES, "numero_organisme": "12"})
    assert r.status_code == 422 and "10 caractères" in r.json()["detail"]
    r = client.put(f"{base}/reglages", headers=h["steven"], json=REGLAGES)
    assert r.status_code == 200, r.text
    assert r.json()["manque"] == [] and r.json()["nom_court"] == "HORIZON INC"
    assert "Réglages du dépôt direct modifiés" in run(_notifs(equipe["ids"]["phil"]))

    r = client.post(f"/api/v1/paiements/lots/{lot['id']}/fichier", headers=h["steven"], json={})
    assert r.status_code == 200, r.text
    fichier = r.json()
    assert fichier["nom"] == "DRD-0123456789-0007.txt"
    lu = cpa005.lire(fichier["contenu"])
    # Deux factures de Rona = un seul dépôt.
    assert lu["nombre"] == 1 and lu["total_cents"] == 125050
    assert lu["depots"][0]["compte"] == "5512345" and lu["depots"][0]["transit"] == "90001"
    assert lu["depots"][0]["date_depot"] == DEPOT and lu["depots"][0]["information"] == "F-100 F-101"
    assert fichier["resume"]["depots"][0]["compte_fin"] == "2345"
    assert "5512345" not in json.dumps(fichier["resume"])
    # Redemander le fichier redonne exactement le même (même numéro).
    r = client.post(f"/api/v1/paiements/lots/{lot['id']}/fichier", headers=h["steven"], json={})
    assert r.status_code == 200 and r.json()["contenu"] == fichier["contenu"]
    assert client.get(f"{base}/reglages", headers=h["steven"]).json()["prochain_numero_fichier"] == 8

    # Transmis : un approbateur seulement. QuickBooks : compte bancaire requis.
    assert client.post(f"/api/v1/paiements/lots/{lot['id']}/transmis", headers=h["technicienne"]).status_code == 403
    r = client.post(f"/api/v1/paiements/lots/{lot['id']}/transmis", headers=h["steven"])
    assert r.status_code == 200 and r.json()["statut"] == "transmis"
    r = client.post(f"/api/v1/paiements/lots/{lot['id']}/quickbooks", headers=h["technicienne"])
    assert r.status_code == 409
    r = client.put(f"{base}/reglages", headers=h["steven"], json={**REGLAGES, "qbo_compte_banque_id": "35"})
    assert r.status_code == 200 and r.json()["qbo_compte_banque_nom"] == "Desjardins"
    r = client.post(f"/api/v1/paiements/lots/{lot['id']}/quickbooks", headers=h["technicienne"])
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "paye"
    assert len(fake_qbo.paiements) == 1
    bp = fake_qbo.paiements[0]
    assert bp["DocNumber"] == f"DRD-{lot['id']}-56" and bp["TotalAmt"] == 1250.5
    assert bp["CheckPayment"]["BankAccountRef"]["value"] == "35" and bp["TxnDate"] == DEPOT
    assert sorted(l["LinkedTxn"][0]["TxnId"] for l in bp["Line"]) == ["300", "301"]
    assert all(l["lien_paiement_qbo"] for l in r.json()["lignes"])
    # Les factures payées ne sont plus à payer.
    r = client.get(f"{base}/factures", headers=h["technicienne"])
    assert {f["qbo_bill_id"] for f in r.json()["factures"]} == {"302", "303", "304"}

    # Journal : chaque geste est inscrit.
    actions = [e["action"] for e in client.get(f"{base}/journal", headers=h["steven"]).json()]
    for a in ("compte_propose", "compte_revele", "compte_approuve", "lot_cree", "lot_soumis", "lot_approuve",
              "reglages_modifies", "fichier_cree", "fichier_transmis", "qbo_enregistre"):
        assert a in actions, a


def test_personne_n_approuve_son_propre_travail(client, run, equipe, inc, fake_qbo):
    h = equipe["h"]
    eid = inc["id"]
    base = f"/api/v1/paiements/entreprises/{eid}"
    for qui in ("steven", "phil"):
        if qui not in equipe["secrets"]:
            _activer_2fa(client, equipe, qui)

    # Phil saisit des coordonnées : il ne peut pas les approuver lui-même.
    r = client.post(
        f"{base}/comptes",
        headers=h["phil"],
        json={"fournisseur_id": "56", "institution": "815", "transit": "90001", "numero_compte": "7654321"},
    )
    assert r.status_code == 200, r.text
    c1 = r.json()["id"]
    r = client.post(f"/api/v1/paiements/comptes/{c1}/approuver", headers=h["phil"], json={})
    assert r.status_code == 403 and "autre personne" in r.json()["detail"]
    assert client.post(f"/api/v1/paiements/comptes/{c1}/approuver", headers=h["steven"], json={}).status_code == 200

    # Phil prépare un lot : il ne peut pas l'approuver, Steven oui.
    r = client.post(
        f"{base}/lots", headers=h["phil"], json={"date_paiement": DEPOT, "lignes": [{"qbo_bill_id": "303", "montant": 80}]}
    )
    assert r.status_code == 200, r.text
    lot_id = r.json()["id"]
    assert client.post(f"/api/v1/paiements/lots/{lot_id}/soumettre", headers=h["phil"]).status_code == 200
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/approuver", headers=h["phil"], json={})
    assert r.status_code == 403 and "préparé" in r.json()["detail"]
    detail = client.get(f"/api/v1/paiements/lots/{lot_id}", headers=h["phil"]).json()
    assert detail["actions"]["approuver"] is False and detail["a_prepare"] is True
    assert client.post(f"/api/v1/paiements/lots/{lot_id}/approuver", headers=h["steven"], json={}).status_code == 200

    # Les coordonnées de Rona changent après l'approbation : le fichier est refusé.
    r = client.post(
        f"{base}/comptes",
        headers=h["phil"],
        json={"fournisseur_id": "56", "institution": "815", "transit": "90002", "numero_compte": "1112223"},
    )
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/paiements/comptes/{r.json()['id']}/approuver", headers=h["steven"], json={}).status_code == 200
    statuts = {c["id"]: c["statut"] for c in client.get(f"{base}/comptes", headers=h["phil"]).json()}
    assert statuts[c1] == "remplace"
    r = client.put(f"{base}/reglages", headers=h["steven"], json=REGLAGES)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/fichier", headers=h["steven"], json={})
    assert r.status_code == 409 and "ont changé" in r.json()["detail"]

    # Remis en brouillon puis soumis de nouveau : le nouveau compte est pris.
    assert client.post(f"/api/v1/paiements/lots/{lot_id}/brouillon", headers=h["steven"]).status_code == 200
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/soumettre", headers=h["phil"])
    assert r.status_code == 200 and r.json()["lignes"][0]["compte"]["transit"] == "90002"

    # Refus : un motif est exigé.
    assert client.post(f"/api/v1/paiements/lots/{lot_id}/refuser", headers=h["steven"], json={}).status_code == 422
    r = client.post(
        f"/api/v1/paiements/lots/{lot_id}/refuser", headers=h["steven"], json={"commentaire": "Montant à vérifier"}
    )
    assert r.status_code == 200 and r.json()["statut"] == "refuse"
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/annuler", headers=h["phil"], json={})
    assert r.status_code == 200 and r.json()["statut"] == "annule"


def test_deux_approbations_exigees(client, run, equipe, inc, fake_qbo):
    h = equipe["h"]
    base = f"/api/v1/paiements/entreprises/{inc['id']}"
    for qui in ("steven", "phil"):
        if qui not in equipe["secrets"]:
            _activer_2fa(client, equipe, qui)
    assert client.put(f"{base}/reglages", headers=h["steven"], json={**REGLAGES, "approbations_requises": 2}).status_code == 200
    r = client.post(
        f"{base}/comptes",
        headers=h["technicienne"],
        json={"fournisseur_id": "57", "institution": "006", "transit": "12345", "numero_compte": "998877"},
    )
    assert client.post(f"/api/v1/paiements/comptes/{r.json()['id']}/approuver", headers=h["phil"], json={}).status_code == 200
    r = client.post(
        f"{base}/lots",
        headers=h["technicienne"],
        json={"date_paiement": DEPOT, "lignes": [{"qbo_bill_id": "302", "montant": 1500}]},
    )
    lot_id = r.json()["id"]
    assert client.post(f"/api/v1/paiements/lots/{lot_id}/soumettre", headers=h["technicienne"]).json()["approbations_requises"] == 2
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/approuver", headers=h["steven"], json={})
    assert r.status_code == 200 and r.json()["statut"] == "soumis"
    # La même personne ne compte qu'une fois.
    assert client.post(f"/api/v1/paiements/lots/{lot_id}/approuver", headers=h["steven"], json={}).status_code == 409
    r = client.post(f"/api/v1/paiements/lots/{lot_id}/approuver", headers=h["phil"], json={})
    assert r.status_code == 200 and r.json()["statut"] == "approuve"
    assert [d["decision"] for d in r.json()["decisions"]] == ["approuve", "approuve"]


# ── Le connecteur IA et le journal automatique ────────────────────────


def test_connecteur_ia_ecarte_et_numeros_masques():
    from app.api.v1.endpoints.activity import _resolve_list_spec
    from app.api.v1.endpoints.mcp_server import _ACTION_CHEMINS_INTERDITS, _api_catalogue
    from app.core.audit_middleware import _masquer
    from app.services.entity_serializers import serialize_entity

    assert "/api/v1/paiements/" in _ACTION_CHEMINS_INTERDITS
    chemins = {o["chemin"] for o in _api_catalogue({"recherche": "/paiements/", "offset": 0})["operations"]}
    assert not any(c.startswith("/api/v1/paiements/") for c in chemins)

    masque = _masquer({"numero_compte": "5512345", "code_2fa": "123456", "institution": "815"})
    assert masque == {"numero_compte": "•••", "code_2fa": "•••", "institution": "815"}

    spec = _resolve_list_spec("lots_paiement")
    assert spec is not None and spec.pole == "comptabilite"

    class _Lot:
        id = 3
        entreprise_id = 9
        statut = "soumis"
        date_paiement = date(2026, 10, 7)
        total_cents = 125050
        nb_lignes = 2

    out = serialize_entity("lot_paiement", _Lot(), level="summary")
    assert out["total"] == 1250.5 and out["statut"] == "soumis"
    assert not any("compte" in k for k in out)
