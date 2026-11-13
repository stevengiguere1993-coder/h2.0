"""Smoke — corriger un bail déjà généré (Phil 2026-11-13, point 13).

« Je sais qu'on est déjà chargé au TAL, mais des fois quand je révise le bail avant d'envoyer
pour signature, je me rends compte d'une erreur. Faudrait pouvoir le modifier, avec une alerte :
vous serez chargé une 2e fois, puis que je puisse venir modifier le bail. »

Un PDF du TAL ne se modifie pas : la correction ouvre un NOUVEAU brouillon rempli comme le bail
généré ; l'ancien est marqué remplacé, reste compté, ne se signe plus et sort des listes.
Refusé si le bail est signé ou en cours de signature. Aucun appel réseau.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models.entreprise import Entreprise
from app.models.immobilier import Bail, BailStatus, Immeuble, Locataire, Logement, LogementStatus
from app.models.tal_bail import TalTransmission
from tests.smoke.conftest import TestSessionLocal

BASE = "/api/v1/immobilier/tal-bail"
IDS: dict = {}

BAIL = {
    "libelle": "Bail à corriger",
    "locateur": {"nom": "Marc Tremblay", "courriel": "marc.tremblay@exemple.ca", "adresse": "12 rue des Érables, Laval (Québec) H7A 1B2"},
    "locataires": [{"nom": "Julie Roy", "courriel": "julie.roy@exemple.ca"}],
    "adresse": "777 rue Tango", "appartement": "7", "ville": "Montréal", "code_postal": "J5M 1A7",
    "nb_pieces": 4.5, "date_debut": "2027-07-01", "date_fin": "2028-06-30", "loyer_mensuel": 1450,
    "chauffage_type": "electricite", "avis_situation": "loyer", "avis_montant": 1400, "avis_frequence": "mois",
}


class _Mailer:
    ready = True
    sender = "systeme@immohorizon.com"

    def __init__(self):
        self.sent: list = []

    async def send(self, **kw):
        self.sent.append(kw)


@pytest.fixture()
def faux_mailer(monkeypatch):
    import app.services.esign_send as envoi

    fake = _Mailer()
    monkeypatch.setattr(envoi, "get_mailer", lambda: fake)
    return fake


def _generer(client, auth_headers, tid: int) -> dict:
    r = client.post(f"{BASE}/transmissions/{tid}/generer", headers=auth_headers, json={"confirme": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_corriger_un_bail_independant_genere(client, auth_headers, employee_headers):
    r = client.post(f"{BASE}/independants", headers=auth_headers, json=BAIL)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    # Un brouillon se modifie directement : rien à « corriger ».
    assert client.post(f"{BASE}/transmissions/{tid}/corriger", headers=auth_headers).status_code == 409
    ancien = _generer(client, auth_headers, tid)
    assert ancien["statut"] == "transmise" and ancien["remplacee_par_id"] is None
    assert client.post(f"{BASE}/transmissions/{tid}/corriger", headers=employee_headers).status_code == 403

    r = client.post(f"{BASE}/transmissions/{tid}/corriger", headers=auth_headers)
    assert r.status_code == 201, r.text
    neuf = r.json()
    IDS["ancien"], IDS["neuf"] = tid, neuf["id"]
    # Nouveau brouillon, rempli comme le bail généré, prêt à être corrigé.
    assert neuf["id"] != tid and neuf["statut"] == "brouillon" and neuf["independant"] is True and neuf["remplace_id"] == tid
    assert neuf["libelle"] == "Bail à corriger" and neuf["rapport"]["valide"] is True
    assert neuf["form"]["locataires"][0]["nom"] == "Julie Roy" and neuf["form"]["coutLoyer"] == "1450.00"
    assert neuf["short_guid"] is None and neuf["document_id"] is None
    # L'ancien reste généré (le TAL l'a produit, il compte) mais il est marqué remplacé.
    vieux = client.get(f"{BASE}/transmissions/{tid}", headers=auth_headers).json()
    assert vieux["statut"] == "transmise" and vieux["remplacee_par_id"] == neuf["id"] and vieux["document_id"]
    # Il sort de la liste des baux, ne se corrige pas deux fois, ne part plus en signature.
    ids = [x["id"] for x in client.get(f"{BASE}/independants", headers=auth_headers).json()["items"]]
    assert neuf["id"] in ids and tid not in ids
    assert tid in [x["id"] for x in client.get(f"{BASE}/independants", headers=auth_headers, params={"inclure_annules": True}).json()["items"]]
    assert client.post(f"{BASE}/transmissions/{tid}/corriger", headers=auth_headers).status_code == 409
    e = client.get(f"{BASE}/transmissions/{tid}/signature/personnes", headers=auth_headers).json()
    assert e["envoi_possible"] is False and "remplacé" in e["motif"]
    assert client.post(f"{BASE}/transmissions/{tid}/signature/envoyer", headers=auth_headers, json={}).status_code == 422
    # Les deux générations comptent au compteur (ici en simulation).
    assert client.get(f"{BASE}/compteur", headers=auth_headers).json()["nb_transmises"] >= 1


def test_le_bail_corrige_se_modifie_et_se_genere(client, auth_headers):
    neuf = IDS["neuf"]
    form = client.get(f"{BASE}/transmissions/{neuf}", headers=auth_headers).json()["form"]
    form["coutLoyer"] = "1500"
    form["coutTotalLoyer"] = ""
    r = client.patch(f"{BASE}/transmissions/{neuf}", headers=auth_headers, json={"form": form})
    assert r.status_code == 200, r.text
    assert r.json()["form"]["coutTotalLoyer"] == "1500.00" and r.json()["rapport"]["valide"] is True
    g = _generer(client, auth_headers, neuf)
    assert g["statut"] == "transmise" and g["parties"]["loyer"] == "1500.00" and g["remplacee_par_id"] is None
    assert g["document_id"] != client.get(f"{BASE}/transmissions/{IDS['ancien']}", headers=auth_headers).json()["document_id"]


def test_pas_de_correction_pendant_ni_apres_la_signature(client, auth_headers, run, faux_mailer):
    neuf = IDS["neuf"]
    r = client.post(f"{BASE}/transmissions/{neuf}/signature/envoyer", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    # Des personnes ont le bail en main : il faut d'abord annuler l'envoi.
    r = client.post(f"{BASE}/transmissions/{neuf}/corriger", headers=auth_headers)
    assert r.status_code == 409 and "annule d'abord" in r.json()["detail"]
    assert client.post(f"{BASE}/transmissions/{neuf}/signature/annuler", headers=auth_headers).status_code == 200
    r = client.post(f"{BASE}/transmissions/{neuf}/corriger", headers=auth_headers)
    assert r.status_code == 201, r.text
    troisieme = r.json()["id"]

    # Un bail signé ne se corrige plus.
    _generer(client, auth_headers, troisieme)

    async def _signer():
        from datetime import datetime, timezone

        async with TestSessionLocal() as s:
            t = await s.get(TalTransmission, troisieme)
            t.signe_le = datetime.now(timezone.utc)
            await s.commit()

    run(_signer())
    r = client.post(f"{BASE}/transmissions/{troisieme}/corriger", headers=auth_headers)
    assert r.status_code == 409 and "signé" in r.json()["detail"]


def test_corriger_un_bail_kratos(client, auth_headers, run):
    """Bail d'un de nos immeubles : la correction rouvre un brouillon pour le MÊME bail."""
    from .test_smoke_tal_bail_2026_10_15 import CHAUFFAGE_CHOISI

    async def _seed():
        async with TestSessionLocal() as s:
            ent = Entreprise(name="INC Correction Smoke")
            ent.siege_social = "100 rue du Siège, Montréal (Québec) H2X 1Y4"
            s.add(ent)
            await s.flush()
            imm = Immeuble(name="Immeuble Correction", address="55 rue de la Correction", city="Montréal", postal_code="H2M 1Y7",
                           owner_entreprise_id=ent.id, is_active=True)
            s.add(imm)
            await s.flush()
            lg = Logement(immeuble_id=imm.id, numero="2", nb_pieces_decimal=3.5, status=LogementStatus.VACANT.value)
            loc = Locataire(full_name="Dora Correction", email="dora@test.ca", phone="514-555-0707")
            s.add_all([lg, loc])
            await s.flush()
            bail = Bail(logement_id=lg.id, locataire_id=loc.id, date_debut=date(2027, 1, 1), date_fin=date(2027, 12, 31),
                        loyer_mensuel=1200.0, status=BailStatus.PROPOSE.value, jour_echeance=1)
            s.add(bail)
            await s.commit()
            return bail.id

    bail_id = run(_seed())
    r = client.post(f"{BASE}/transmissions", headers=auth_headers, json={"bail_id": bail_id, "surcharges": CHAUFFAGE_CHOISI})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["rapport"]["valide"] is True, r.json()["rapport"]
    _generer(client, auth_headers, tid)

    r = client.post(f"{BASE}/transmissions/{tid}/corriger", headers=auth_headers)
    assert r.status_code == 201, r.text
    neuf = r.json()
    assert neuf["bail_id"] == bail_id and neuf["statut"] == "brouillon" and neuf["id"] != tid and neuf["independant"] is False
    assert neuf["form"]["coutLoyer"] == "1200.00" and neuf["form"]["typeChauffageLogement"] == ["electricite"]

    async def _vieux():
        async with TestSessionLocal() as s:
            t = await s.get(TalTransmission, tid)
            return t.statut, t.remplacee_par_id

    assert run(_vieux()) == ("transmise", neuf["id"])
    # L'écran repart du brouillon corrigé (remplacement confirmé) et le génère.
    form = neuf["form"]
    form["coutLoyer"] = "1250"
    form["coutTotalLoyer"] = ""
    r = client.post(f"{BASE}/transmissions", headers=auth_headers, json={"bail_id": bail_id, "form": form, "remplacer": True})
    assert r.status_code == 201 and r.json()["id"] == neuf["id"], r.text
    assert _generer(client, auth_headers, neuf["id"])["statut"] == "transmise"
