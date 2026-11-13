"""Smoke — documents signés AVEC le bail (Phil 2026-11-13, points 7 et 8).

« Quand on envoie pour la signature du bail, on envoie l'autorisation de communication
électronique. » « Il faut que ça envoie le règlement d'immeuble à signer. »

Verrouille, sans aucun appel réseau :
- la page de signature que Kratos génère (zones dans la page, signatures sur la dernière page) ;
- l'enveloppe : le bail du TAL tel quel, suivi des documents joints, zones aux bonnes pages ;
- l'envoi : chaque locataire invité signe chaque document joint ; le locateur ne les signe pas ;
  pas de documents joints sans locataire invité ; une clé inconnue est refusée ;
- la signature complète de l'enveloppe ;
- bail Kratos : le consentement signé avec le bail entre au dossier, Kratos ne le redemande pas.
"""
from __future__ import annotations

import base64
import io
from datetime import date

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.integrations.tal import client as tal_client
from app.models.entreprise import Entreprise
from app.models.esign import EsignDocument, EsignField, EsignSigner
from app.models.immobilier import (
    Bail, BailStatus, ImmDocPersoModele, ImmDocument, Immeuble, Locataire, Logement, LogementStatus,
)
from app.services import tal_bail_annexes as ab
from tests.smoke.conftest import TestSessionLocal

BASE = "/api/v1/immobilier/tal-bail"
IDS: dict = {}

BAIL = {
    "libelle": "Bail avec documents joints",
    "locateur": {"nom": "Marc Tremblay", "courriel": "marc.tremblay@exemple.ca", "adresse": "12 rue des Érables, Laval (Québec) H7A 1B2"},
    "locataires": [{"nom": "Julie Roy", "courriel": "julie.roy@exemple.ca"}, {"nom": "Sam Côté", "courriel": "sam.cote@exemple.ca"}],
    "adresse": "777 rue Tango", "appartement": "9", "ville": "Montréal", "code_postal": "J5M 1A7",
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


def _png() -> str:
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (240, 80), (0, 0, 0, 0))
    ImageDraw.Draw(img).line([(10, 60), (90, 15), (150, 55), (230, 20)], fill=(10, 10, 60, 255), width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _pages(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


# ─── Pages générées et enveloppe ──────────────────────────────────────


def test_page_de_signature_et_enveloppe():
    deux = [(1, "Julie Roy"), (2, "Sam Côté")]
    pdf, zones = ab._page_de_signature("Règlement — signature", ["Je reconnais avoir reçu le règlement."], deux)
    assert _pages(pdf) == 1 and [(z["rang"], z["kind"]) for z in zones] == [(1, "signature"), (1, "date"), (2, "signature"), (2, "date")]
    for z in zones:
        assert z["page"] == 1 and 0 < z["x"] < 1 and 0 < z["y"] < 1 and z["x"] + z["w"] <= 1 and z["y"] + z["h"] <= 1
    # Les deux rangées ne se chevauchent pas et la signature est plus haute que large de 4 à 1 environ.
    s1, s2 = zones[0], zones[2]
    assert s1["y"] + s1["h"] < s2["y"] and s1["w"] > 0.4
    # Un texte long passe sur plusieurs pages ; les signatures restent sur la dernière.
    long_pdf, long_zones = ab._page_de_signature("Règlement", ["Article. " + "Le locataire respecte le règlement. " * 60] * 6, deux[:1])
    assert _pages(long_pdf) > 1 and {z["page"] for z in long_zones} == {_pages(long_pdf)}
    assert "Le locataire respecte" in PdfReader(io.BytesIO(long_pdf)).pages[0].extract_text()

    # Enveloppe : le bail tel quel, puis chaque document ; les zones suivent leur page.
    bail = tal_client.pdf_simulation({}, "SIM-annexe")
    a = ab.Annexe(cle="consentement", titre="Consentement", pdf=pdf, zones=zones)
    b = ab.Annexe(cle="modele:7", titre="Règlement", pdf=long_pdf, zones=long_zones)
    enveloppe, z_env, meta = ab.assembler(bail, [a, b])
    assert _pages(enveloppe) == 4 + 1 + _pages(long_pdf)
    assert meta == [{"cle": "consentement", "titre": "Consentement", "pages": [5, 5], "signature": True},
                    {"cle": "modele:7", "titre": "Règlement", "pages": [6, 5 + _pages(long_pdf)], "signature": True}]
    assert {z["page"] for z in z_env} == {5, 5 + _pages(long_pdf)}
    assert ab.assembler(bail, []) == (bail, [], [])
    assert _pages(ab.extraire_pages(enveloppe, 5, 5)) == 1 and _pages(ab.extraire_pages(enveloppe, 6, 99)) == _pages(long_pdf)

    assert ab.est_un_reglement("Règlement d'immeuble") and ab.est_un_reglement("REGLEMENTS 1660") and not ab.est_un_reglement("Contrat de chambreur")
    ctx = ab.contexte({"locateurs": [{"nom": "Marc Tremblay"}], "locataires": [{"nom": "Julie Roy"}, {"nom": "Sam Côté"}],
                       "adresseLogement": [{"NoCivique": "777", "Rue": "rue Tango", "Appartement": "9", "Municipalite": "Montréal"}],
                       "coutLoyer": "1450.00", "dateDebutBail": "2027-07-01", "dateFinBail": "2028-06-30"})
    assert ctx.locataire_nom == "Julie Roy, Sam Côté" and ctx.logement_adresse == "777 rue Tango" and ctx.logement_numero == "9"
    assert ctx.bail_loyer_mensuel == 1450.0 and ctx.bail_date_debut == date(2027, 7, 1) and ctx.locateur_nom == "Marc Tremblay"


# ─── Envoi d'un bail indépendant avec ses documents ───────────────────


def test_documents_proposes_avec_le_bail(client, auth_headers):
    # Deux modèles de documents : un règlement (à signer) et une note d'information (sans signature).
    r = client.post("/api/v1/immobilier/docs-perso/modeles", headers=auth_headers, json={
        "nom": "Règlement d'immeuble", "titre": "Règlement de l'immeuble",
        "corps": "Le locataire {locataire} du logement {logement} situé au {adresse} s'engage à respecter ce règlement.\n\n"
                 "Aucun bruit après 23 h.\n\nLes ordures se sortent le mardi.",
        "signature_requise": True,
    })
    assert r.status_code in (200, 201), r.text
    IDS["reglement"] = r.json()["id"]
    r = client.post("/api/v1/immobilier/docs-perso/modeles", headers=auth_headers, json={
        "nom": "Guide du locataire", "titre": "Guide du locataire", "corps": "Bienvenue chez vous.", "signature_requise": False,
    })
    assert r.status_code in (200, 201), r.text
    IDS["guide"] = r.json()["id"]

    r = client.post(f"{BASE}/independants", headers=auth_headers, json=BAIL)
    assert r.status_code == 201, r.text
    IDS["tid"] = tid = r.json()["id"]
    assert client.post(f"{BASE}/transmissions/{tid}/generer", headers=auth_headers, json={"confirme": True}).status_code == 200
    e = client.get(f"{BASE}/transmissions/{tid}/signature/personnes", headers=auth_headers).json()
    dispo = {a["cle"]: a for a in e["annexes"]}
    assert dispo["consentement"]["defaut"] is True and dispo["consentement"]["signature"] is True
    assert dispo[f"modele:{IDS['reglement']}"]["defaut"] is True, "un règlement se propose coché"
    assert dispo[f"modele:{IDS['guide']}"]["defaut"] is False and dispo[f"modele:{IDS['guide']}"]["signature"] is False
    assert e["annexes_envoyees"] == []


def test_envoi_du_bail_avec_ses_documents(client, auth_headers, run, faux_mailer):
    tid = IDS["tid"]
    url = f"{BASE}/transmissions/{tid}/signature/envoyer"
    # Une clé inconnue est refusée : rien ne part avec un document manquant.
    r = client.post(url, headers=auth_headers, json={"annexes": ["consentement", "modele:999999"]})
    assert r.status_code == 422 and "introuvable" in r.json()["detail"], r.text
    # Sans locataire invité, personne ne pourrait signer les documents joints.
    r = client.post(url, headers=auth_headers, json={"annexes": ["consentement"], "courriels": {"locataire:1": "", "locataire:2": ""}})
    assert r.status_code == 422 and "Aucun locataire" in r.json()["detail"], r.text
    assert faux_mailer.sent == []

    # Un PDF téléversé illisible (protégé, abîmé) est refusé clairement : rien ne part.
    async def _modele_abime(supprimer: int | None = None):
        async with TestSessionLocal() as db:
            if supprimer is not None:
                await db.delete(await db.get(ImmDocPersoModele, supprimer))
                await db.commit()
                return None
            m = ImmDocPersoModele(nom="Annexe abîmée", titre="Annexe abîmée", signature_requise=True,
                                  pdf_filename="abimee.pdf", pdf_blob=b"ceci n'est pas un PDF")
            db.add(m)
            await db.commit()
            return m.id

    abime = run(_modele_abime())
    r = client.post(url, headers=auth_headers, json={"annexes": ["consentement", f"modele:{abime}"]})
    assert r.status_code == 422 and "illisible" in r.json()["detail"] and "Annexe abîmée" in r.json()["detail"], r.text
    assert faux_mailer.sent == []
    run(_modele_abime(abime))

    cles = ["consentement", f"modele:{IDS['reglement']}", f"modele:{IDS['guide']}"]
    r = client.post(url, headers=auth_headers, json={"annexes": cles})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["envoyes"] == 3 and [a["cle"] for a in b["annexes"]] == cles
    consent, reglement, guide = b["annexes"]
    assert consent["pages"] == [5, 5] and reglement["pages"][0] == 6 and guide["pages"][0] == reglement["pages"][1] + 1
    assert guide["signature"] is False
    doc_id = b["esign_document_id"]
    IDS["doc"] = doc_id

    async def _etat():
        async with TestSessionLocal() as db:
            doc = await db.get(EsignDocument, doc_id)
            blob = (await db.execute(select(EsignDocument.pdf_blob).where(EsignDocument.id == doc_id))).scalar_one()
            signataires = (await db.execute(select(EsignSigner).where(EsignSigner.document_id == doc_id))).scalars().all()
            champs = (await db.execute(select(EsignField).where(EsignField.document_id == doc_id))).scalars().all()
            return doc.page_count, bytes(blob), signataires, champs, doc.message

    nb_pages, enveloppe, signataires, champs, message = run(_etat())
    # L'invitation annonce ce qui se signe à la suite du bail.
    assert "À la suite du bail" in message and "Règlement de l'immeuble" in message and consent["titre"] in message
    assert len(faux_mailer.sent) == 3
    assert nb_pages == guide["pages"][1] == _pages(enveloppe)
    texte = " ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(enveloppe)).pages[4:])
    assert "Consentement aux communications" in texte and "Julie Roy, Sam Côté" in texte
    assert "Aucun bruit après 23 h" in texte and "logement 9" in texte and "Bienvenue chez vous" in texte
    par_ref = {s.contact_ref: s for s in signataires}
    for ref in ("tal:locataire:1", "tal:locataire:2"):
        joints = [c for c in champs if c.signer_id == par_ref[ref].id and c.page > 4]
        # Chaque locataire signe et date le consentement, puis le règlement ; rien sur la note d'information.
        assert sorted((c.page, c.kind) for c in joints) == [(5, "date"), (5, "signature"), (reglement["pages"][1], "date"), (reglement["pages"][1], "signature")]
    assert not [c for c in champs if c.signer_id == par_ref["tal:locateur:1"].id and c.page > 4], "le locateur ne signe pas les documents joints"
    IDS["jetons"] = [s.signature_token for s in signataires]
    e = client.get(f"{BASE}/transmissions/{tid}/signature/personnes", headers=auth_headers).json()
    assert [a["titre"] for a in e["annexes_envoyees"]] == [consent["titre"], "Règlement de l'immeuble", "Guide du locataire"]


def test_signature_complete_de_l_enveloppe(client, auth_headers, run, faux_mailer):
    image = _png()
    for jeton in IDS["jetons"]:
        vu = client.get(f"/api/v1/public/esign/{jeton}").json()
        corps = {"signature_data_url": image, "consent": True}
        if any(f["mine"] and f["kind"] == "initiales" for f in vu["fields"]):
            corps["initials_data_url"] = image
        assert client.post(f"/api/v1/public/esign/{jeton}/sign", json=corps).status_code == 200
    e = client.get(f"{BASE}/transmissions/{IDS['tid']}/signature/personnes", headers=auth_headers).json()
    assert e["signature"]["statut"] == "complete" and e["document_signe_id"]

    async def _signe():
        async with TestSessionLocal() as db:
            blob = (await db.execute(select(ImmDocument.pdf_blob).where(ImmDocument.id == e["document_signe_id"]))).scalar_one()
            return bytes(blob)

    signe = run(_signe())
    # Le bail signé contient le bail, les documents joints et le certificat de signature.
    assert _pages(signe) > e["annexes_envoyees"][-1]["pages"][1]


# ─── Bail Kratos : le consentement signé avec le bail entre au dossier ─


def test_consentement_signe_avec_le_bail_verse_au_dossier(client, auth_headers, run, faux_mailer):
    from .test_smoke_tal_bail_2026_10_15 import CHAUFFAGE_CHOISI

    async def _seed():
        async with TestSessionLocal() as s:
            ent = Entreprise(name="INC Annexes Smoke")
            ent.siege_social = "100 rue du Siège, Montréal (Québec) H2X 1Y4"
            s.add(ent)
            await s.flush()
            imm = Immeuble(name="Immeuble Annexes", address="66 rue des Annexes", city="Montréal", postal_code="H2M 1Y7",
                           owner_entreprise_id=ent.id, is_active=True)
            s.add(imm)
            await s.flush()
            lg = Logement(immeuble_id=imm.id, numero="5", nb_pieces_decimal=3.5, status=LogementStatus.VACANT.value)
            loc = Locataire(full_name="Éva Annexe", email="eva.annexe@exemple.ca", phone="514-555-0808")
            s.add_all([lg, loc])
            await s.flush()
            bail = Bail(logement_id=lg.id, locataire_id=loc.id, date_debut=date(2027, 2, 1), date_fin=date(2028, 1, 31),
                        loyer_mensuel=1300.0, status=BailStatus.PROPOSE.value, jour_echeance=1)
            s.add(bail)
            await s.commit()
            return bail.id

    bail_id = run(_seed())
    r = client.post(f"{BASE}/transmissions", headers=auth_headers, json={"bail_id": bail_id, "surcharges": CHAUFFAGE_CHOISI})
    assert r.status_code == 201 and r.json()["rapport"]["valide"] is True, r.text
    tid = r.json()["id"]
    assert client.post(f"{BASE}/transmissions/{tid}/generer", headers=auth_headers, json={"confirme": True}).status_code == 200
    r = client.post(f"{BASE}/transmissions/{tid}/signature/envoyer", headers=auth_headers, json={"annexes": ["consentement"]})
    assert r.status_code == 200, r.text
    doc_id = r.json()["esign_document_id"]

    async def _jetons():
        async with TestSessionLocal() as db:
            return [s.signature_token for s in (await db.execute(select(EsignSigner).where(EsignSigner.document_id == doc_id))).scalars().all()]

    image = _png()
    for jeton in run(_jetons()):
        vu = client.get(f"/api/v1/public/esign/{jeton}").json()
        corps = {"signature_data_url": image, "consent": True}
        if any(f["mine"] and f["kind"] == "initiales" for f in vu["fields"]):
            corps["initials_data_url"] = image
        assert client.post(f"/api/v1/public/esign/{jeton}/sign", json=corps).status_code == 200

    async def _dossier():
        from app.api.v1.endpoints.immobilier_extras import envoyer_consentement_si_jamais_envoye

        async with TestSessionLocal() as db:
            docs = (await db.execute(select(ImmDocument).where(ImmDocument.bail_id == bail_id))).scalars().all()
            consentement = next((d for d in docs if d.type == "consentement_communications"), None)
            blob = None
            if consentement is not None:
                blob = (await db.execute(select(ImmDocument.pdf_blob).where(ImmDocument.id == consentement.id))).scalar_one()
            renvoye = await envoyer_consentement_si_jamais_envoye(db, bail_id, None)
            return {d.type for d in docs}, consentement, bytes(blob) if blob else b"", renvoye

    types, consentement, blob, renvoye = run(_dossier())
    assert "bail" in types and consentement is not None, types
    # Seul le locataire signe le consentement : son nom, pas celui du locateur.
    assert consentement.signed_at is not None and consentement.signed_by_name == "Éva Annexe"
    assert _pages(blob) == 1 and "Consentement aux communications" in (PdfReader(io.BytesIO(blob)).pages[0].extract_text() or "")
    assert renvoye is False, "un consentement déjà signé avec le bail n'est pas redemandé"
