"""Smoke — signature du bail officiel du TAL pilotée depuis Gestion immobilière (Phil 2026-11-11).

« J'aimerais que tout se contrôle uniquement à partir de gestion immobilière… que ça
l'envoie automatiquement aussitôt que je clique sur envoyer, donc ça vient mettre au bon
endroit toutes les initiales, toutes les signatures demandées… de là je peux faire le
suivi, les renvoyer, changer le courriel, les annuler… indépendant de la section
signature déjà créée. »

Verrouille, SANS aucun appel réseau :
- le gabarit des zones : cohérent avec l'empreinte relevée sur le vrai bail, zones dans la
  page et sans chevauchement, engagements facultatifs paraphés seulement s'ils sont pris ;
- le refus de poser des zones sur un PDF qui n'est pas le formulaire connu ;
- l'envoi en un geste : zones posées pour chaque personne invitée, invitations parties,
  personne sans courriel jamais invitée, courriel corrigé à l'envoi sans toucher au
  formulaire transmis ;
- le suivi depuis Gestion immobilière : renvoyer, corriger un courriel (l'ancien lien
  meurt), annuler, renvoyer de nouveau ;
- l'indépendance : le document n'apparaît ni dans la section Signature ni dans la banque
  de contacts d'affaires ;
- la signature complète : le PDF signé devient le bail signé de la transmission.
"""
from __future__ import annotations

import base64
import io
import json

import pytest
from sqlalchemy import select

from app.integrations.tal import client as tal_client
from app.integrations.tal import gabarit_signature as gab
from app.models.esign import EsignDocument, EsignField, EsignSigner
from app.models.immobilier import ImmDocument
from app.models.tal_bail import TalTransmission
from app.services import tal_bail as svc
from app.services import tal_bail_signature as sig
from tests.smoke.conftest import TestSessionLocal

BASE = "/api/v1/immobilier/tal-bail"
IDS: dict = {}

BAIL = {
    "libelle": "Bail à signer en ligne",
    "locateur": {"nom": "Marc Tremblay", "telephone": "514-555-0199", "courriel": "marc.tremblay@exemple.ca", "adresse": "12 rue des Érables, Laval (Québec) H7A 1B2"},
    "locataires": [
        {"nom": "Julie Roy", "telephone": "438-555-0142", "courriel": "julie.roy@exemple.ca", "adresse": "88 avenue du Parc, Montréal H2V 4E1"},
        {"nom": "Sam Côté"},                       # pas de courriel : jamais invité d'office
    ],
    "cautions": [{"nom": "Paul Roy", "courriel": "paul.roy@exemple.ca"}],
    "adresse": "4521 rue Saint-Denis", "appartement": "7", "ville": "Montréal", "code_postal": "H2J 2L4",
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


def _chevauche(a: gab.Zone, b: gab.Zone) -> bool:
    return a.page == b.page and a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


# ─── Le gabarit ───────────────────────────────────────────────────────


def test_gabarit_coherent_avec_le_formulaire_officiel():
    # Ce que le gabarit prévoit = ce qui a été compté sur le vrai bail et sur le bail d'essai du TAL.
    assert gab.empreinte_du_gabarit() == gab.EMPREINTE
    # Deux lignes par partie, pas plus ; chaque zone tient dans sa page ; aucune ne recouvre une autre.
    for z in gab.GABARIT:
        assert z.partie in gab.PARTIES and 0 <= z.rang <= gab.MAX_PAR_PARTIE and 1 <= z.page <= gab.PAGES_FORMULAIRE
        assert z.x >= 0 and z.y >= 0 and z.x + z.w <= gab.LARGEUR and z.y + z.h <= gab.HAUTEUR and z.w > 20 and z.h >= 12
        f = gab.fractions(z)
        assert 0 <= f["x"] < 1 and 0 <= f["y"] < 1 and 0 < f["w"] <= 1 and 0 < f["h"] <= 1
    zones = list(gab.GABARIT)
    for i, a in enumerate(zones):
        for b in zones[i + 1:]:
            assert not _chevauche(a, b), (a, b)
    # Le pied de chaque page du formulaire porte les initiales des quatre parties.
    for page in range(1, 5):
        assert sorted((z.partie, z.rang) for z in gab.GABARIT if z.cle == "pied" and z.page == page) == [
            ("locataire", 1), ("locataire", 2), ("locateur", 1), ("locateur", 2)]


def test_pdf_hors_gabarit_refuse():
    from reportlab.pdfgen import canvas

    officiel = tal_client.pdf_simulation({"locataires": [{"nom": "A"}]}, "SIM-gabarit")
    v = gab.verifier_gabarit(officiel)
    assert v.ok is True and v.pages == 4 and v.motif is None
    assert gab.verifier_gabarit(b"pas un pdf").ok is False

    def pdf(pages: int, taille=(612, 1008), libelles=()) -> bytes:
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=taille)
        for _ in range(pages):
            for i, lib in enumerate(libelles):
                c.drawString(40, 900 - 14 * i, lib)
            c.showPage()
        c.save()
        return buf.getvalue()

    court = gab.verifier_gabarit(pdf(1))
    assert court.ok is False and "1 page" in court.motif
    # Bon nombre de pages, mauvais format : ce n'est pas le formulaire.
    lettre = gab.verifier_gabarit(pdf(4, taille=(612, 792)))
    assert lettre.ok is False and "format" in lettre.motif
    # Bon format, mais pas les cases attendues (formulaire changé) : aucune zone posée à l'aveugle.
    vide = gab.verifier_gabarit(pdf(4))
    assert vide.ok is False and "page 1" in vide.motif and "Initiales du locateur" in vide.motif
    # Une annexe avec ses propres cases de signature (Annexe 6) : hors gabarit.
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter()
    for p in PdfReader(io.BytesIO(officiel)).pages:
        w.add_page(p)
    for p in PdfReader(io.BytesIO(pdf(1, libelles=("Initiales du locataire",)))).pages:
        w.add_page(p)
    buf = io.BytesIO()
    w.write(buf)
    annexe = gab.verifier_gabarit(buf.getvalue())
    assert annexe.ok is False and "page 5" in annexe.motif


def test_zones_selon_le_bail_et_les_personnes_invitees():
    deux = {"locataires": [{"nom": "Julie Roy"}, {"nom": "Sam Côté"}]}
    tous = {("locateur", 1), ("locataire", 1), ("locataire", 2), ("autre", 1)}

    def cles(form, presents):
        return sorted({z.cle for z in gab.zones_a_poser(form, presents)})

    # Bail tout simple : pied de page, avertisseurs de fumée, avis (G), signatures (H), caution.
    assert cles(deux, tous) == ["autre", "avis", "fumee", "pied", "signatures"]
    base = gab.zones_a_poser(deux, tous)
    par_personne = {}
    for z in base:
        par_personne.setdefault((z.partie, z.rang), []).append(z)
    assert set(par_personne) == tous
    # Locataire : 4 pieds de page + fumée + signature et date à l'avis et aux signatures.
    assert sorted(z.kind for z in par_personne[("locataire", 2)]) == ["date", "date"] + ["initiales"] * 5 + ["signature", "signature"]
    # La date commune des avertisseurs de fumée va à la première personne de la partie.
    assert [z.rang for z in base if z.cle == "fumee" and z.kind == "date" and z.partie == "locataire"] == [1]
    # Caution : sa signature et sa date, rien d'autre.
    assert sorted(z.kind for z in par_personne[("autre", 1)]) == ["date", "signature"]
    # Personne sans courriel : ses cases restent libres ; la date commune passe au suivant.
    sans_julie = gab.zones_a_poser(deux, tous - {("locataire", 1)})
    assert not [z for z in sans_julie if (z.partie, z.rang) == ("locataire", 1)]
    assert [z.rang for z in sans_julie if z.cle == "fumee" and z.kind == "date" and z.partie == "locataire"] == [2]
    # Engagements facultatifs : paraphés seulement s'ils sont pris.
    assert "cheques" in cles({**deux, "locataireAccepteRemiseChequePostdates": True}, tous)
    assert "cheques" not in cles({**deux, "locataireAccepteRemiseChequePostdates": False}, tous)
    assert "reglement" in cles({**deux, "possedeRemiseReglementImmeuble": "true"}, tous)
    assert "reglement" not in cles({**deux, "possedeRemiseReglementImmeuble": "false"}, tous)
    assert "copropriete" not in cles({**deux, "possedeRemiseReglementImmeubleCoproprieteDivise": "true"}, tous)
    assert "copropriete" in cles({**deux, "logementCoproprieteDivise": "true", "possedeRemiseReglementImmeubleCoproprieteDivise": "true"}, tous)
    assert "solidaire" in cles({**deux, "estLocatairesEngagementSolidaire": "true"}, tous)
    assert "solidaire" not in cles({**deux, "estLocatairesEngagementSolidaire": "false"}, tous)
    assert "solidaire" not in cles({"locataires": [{"nom": "Julie Roy"}], "estLocatairesEngagementSolidaire": "true"}, tous)
    # Avis de résidence familiale : une seule ligne, pour le locataire qui donne l'avis.
    famille = [z for z in gab.zones_a_poser({**deux, "locataire2logementResidenceFamiliale": "true"}, tous) if z.cle == "famille"]
    assert sorted((z.partie, z.rang, z.kind) for z in famille) == [("locataire", 2, "date"), ("locataire", 2, "signature")]
    assert "famille" not in cles({**deux, "locataire2logementResidenceFamiliale": "true"}, tous - {("locataire", 2)})


def test_qui_signe_selon_le_bail():
    form = {
        "locateurs": [{"nom": "Gestion ABC inc.", "questionRepresentant": "true", "representant": "Lise Gagnon", "courrielRepresentant": "lise@abc.ca"},
                      {"nom": "Marc Tremblay", "courrielLocateur": "marc@exemple.ca"}],
        "locataires": [{"nom": "Julie Roy", "courrielLocataire": "julie@exemple.ca", "noTelephone": "438-555-0142"}, {"nom": ""}, {"nom": "Sam Côté"}],
        "possedeAutresSignataires": "true", "autresSignataires": [{"nom": "Paul Roy", "qualite": "Caution", "courriel": "paul@exemple.ca"}],
    }
    # Bail indépendant : chaque locateur signe lui-même, ou son représentant nommé.
    ind = {p["cle"]: p for p in svc.personnes_a_signer(form, independant=True)}
    assert list(ind) == ["locateur:1", "locateur:2", "locataire:1", "locataire:2", "autre:1"]
    assert ind["locateur:1"]["nom"] == "Lise Gagnon" and ind["locateur:1"]["pour"] == "Gestion ABC inc." and ind["locateur:1"]["courriel"] == "lise@abc.ca"
    assert ind["locateur:2"]["nom"] == "Marc Tremblay" and ind["locateur:2"]["pour"] is None
    # Le rang suit les personnes NOMMÉES : Sam est le 2e locataire, sans courriel.
    assert ind["locataire:2"]["nom"] == "Sam Côté" and ind["locataire:2"]["courriel"] == "" and ind["autre:1"]["role"] == "caution"
    # Bail géré par Horizon : un seul signataire côté locateur, le représentant.
    gere = svc.personnes_a_signer(form, independant=False, representant_nom="Phil Test", representant_courriel="phil@exemple.ca")
    locateurs = [p for p in gere if p["partie"] == "locateur"]
    assert len(locateurs) == 1 and locateurs[0]["nom"] == "Lise Gagnon" and locateurs[0]["rang"] == 1
    sans_rep = svc.personnes_a_signer({"locateurs": [{"nom": "Immeubles XYZ"}], "locataires": []}, independant=False,
                                      representant_nom="Phil Test", representant_courriel="phil@exemple.ca")
    assert [(p["nom"], p["courriel"], p["pour"]) for p in sans_rep] == [("Phil Test", "phil@exemple.ca", "Immeubles XYZ")]
    # La voie historique (liste des invitables + personnes sans courriel) dit la même chose.
    invites, manquants = svc.signataires_depuis_formulaire(form, locateurs_signent=True)
    assert [s["nom_complet"] for s in invites] == ["Julie Roy", "Paul Roy", "Lise Gagnon", "Marc Tremblay"] and manquants == ["Sam Côté (locataire)"]
    assert svc.lire_reference_signataire(svc.reference_signataire("caution", 2)) == ("caution", "autre", 2)
    assert svc.lire_reference_signataire("tal:locataire") == ("locataire", "locataire", None)      # ancien format
    assert svc.lire_reference_signataire("contact:12") == (None, None, None)


# ─── Envoi en un geste, depuis Gestion immobilière ────────────────────


def test_bail_genere_pret_a_signer(client, auth_headers, employee_headers):
    r = client.post(f"{BASE}/independants", headers=auth_headers, json=BAIL)
    assert r.status_code == 201, r.text
    t = r.json()
    IDS["tid"] = tid = t["id"]
    assert t["rapport"]["valide"] is True, t["rapport"]
    # Avant la génération : qui signera se voit déjà, mais rien ne part.
    avant = client.get(f"{BASE}/transmissions/{tid}/signature/personnes", headers=auth_headers)
    assert avant.status_code == 200, avant.text
    assert avant.json()["envoi_possible"] is False and "pas encore été généré" in avant.json()["motif"]
    assert client.post(f"{BASE}/transmissions/{tid}/signature/envoyer", headers=auth_headers, json={}).status_code == 409
    r = client.post(f"{BASE}/transmissions/{tid}/generer", headers=auth_headers, json={"confirme": True})
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "transmise" and r.json()["mode"] == "simulation"
    # Réservé aux gestionnaires de Gestion immobilière.
    assert client.get(f"{BASE}/transmissions/{tid}/signature/personnes", headers=employee_headers).status_code == 403
    assert client.post(f"{BASE}/transmissions/{tid}/signature/envoyer", headers=employee_headers, json={}).status_code == 403

    e = client.get(f"{BASE}/transmissions/{tid}/signature/personnes", headers=auth_headers).json()
    assert e["envoi_possible"] is True and e["motif"] is None and e["signature"] is None and e["max_par_partie"] == 2
    p = {x["cle"]: x for x in e["personnes"]}
    assert list(p) == ["locateur:1", "locataire:1", "locataire:2", "autre:1"]
    assert p["locateur:1"]["nom"] == "Marc Tremblay" and p["locateur:1"]["courriel"] == "marc.tremblay@exemple.ca"
    assert p["locataire:2"]["nom"] == "Sam Côté" and p["locataire:2"]["courriel"] == "" and p["autre:1"]["role"] == "caution"


def test_envoi_impossible_sans_courriel_valide(client, auth_headers):
    tid = IDS["tid"]
    # Sans service de courriel : rien ne part, et c'est dit. Le brouillon sera remplacé au prochain essai.
    r = client.post(f"{BASE}/transmissions/{tid}/signature/envoyer", headers=auth_headers, json={})
    assert r.status_code == 502 and "ne sont pas parties" in r.json()["detail"], r.text
    e = client.get(f"{BASE}/transmissions/{tid}/signature/personnes", headers=auth_headers).json()
    assert e["signature"]["statut"] == "brouillon" and e["signature"]["peut_envoyer"] is True and e["signature"]["peut_annuler"] is False
    assert all(s["envoye_le"] is None for s in e["signature"]["signataires"])
    # Courriel mal écrit : refusé avant toute création.
    r = client.post(f"{BASE}/transmissions/{tid}/signature/envoyer", headers=auth_headers, json={"courriels": {"locataire:2": "sam-sans-arobase"}})
    assert r.status_code == 422 and "Sam Côté" in r.json()["detail"], r.text
    # Tous les courriels retirés : personne à inviter.
    vides = {"locateur:1": "", "locataire:1": "", "locataire:2": "", "autre:1": ""}
    r = client.post(f"{BASE}/transmissions/{tid}/signature/envoyer", headers=auth_headers, json={"courriels": vides})
    assert r.status_code == 422 and len(r.json()["detail"]["details"]["sans_courriel"]) == 4, r.text


def test_envoi_en_un_geste_zones_posees(client, auth_headers, run, faux_mailer):
    tid = IDS["tid"]
    r = client.post(f"{BASE}/transmissions/{tid}/signature/envoyer", headers=auth_headers, json={"message": "Merci de signer d'ici vendredi."})
    assert r.status_code == 200, r.text
    b = r.json()
    IDS["doc1"] = doc_id = b["esign_document_id"]
    # Sam n'a pas de courriel : il ne reçoit rien, ses cases restent libres.
    assert b["envoyes"] == 3 and b["erreurs"] == [] and b["sans_courriel"] == ["Sam Côté (locataire)"]
    assert sorted(m["to"][0] for m in faux_mailer.sent) == ["julie.roy@exemple.ca", "marc.tremblay@exemple.ca", "paul.roy@exemple.ca"]
    assert all("Signature requise" in m["subject"] and "Merci de signer d'ici vendredi." in m["html_body"] for m in faux_mailer.sent)
    s = b["signature"]
    assert s["statut"] == "envoye" and s["nb_signataires"] == 3 and s["peut_annuler"] is True and s["peut_envoyer"] is False
    assert {x["role"]: (x["partie"], x["rang"]) for x in s["signataires"]} == {
        "locateur": ("locateur", 1), "locataire": ("locataire", 1), "caution": ("autre", 1)}
    assert all(x["envoye_le"] and x["peut_renvoyer"] and x["peut_modifier"] for x in s["signataires"])

    async def _zones():
        async with TestSessionLocal() as db:
            doc = await db.get(EsignDocument, doc_id)
            du_bail = (await db.execute(select(EsignDocument.id).where(EsignDocument.filename == f"bail-tal-{tid}.pdf"))).scalars().all()
            signataires = (await db.execute(select(EsignSigner).where(EsignSigner.document_id == doc_id))).scalars().all()
            champs = (await db.execute(select(EsignField).where(EsignField.document_id == doc_id))).scalars().all()
            t = await db.get(TalTransmission, tid)
            return doc, du_bail, signataires, champs, t.payload_json

    doc, du_bail, signataires, champs, payload = run(_zones())
    assert du_bail == [doc_id]                                # le brouillon resté en panne a été remplacé, pas empilé
    assert doc.origine == "bail_tal" and doc.page_count == 4 and doc.status == "envoye" and doc.use_signing_order is False
    assert all(sg.signature_token for sg in signataires)
    IDS["jetons1"] = {sg.email: sg.signature_token for sg in signataires}
    par = {sg.contact_ref: [c for c in champs if c.signer_id == sg.id] for sg in signataires}
    assert set(par) == {"tal:locateur:1", "tal:locataire:1", "tal:caution:1"}
    # Locateur : 4 pieds de page + avertisseurs de fumée (initiales et date) + avis (G) + signatures (H).
    assert sorted(c.kind for c in par["tal:locateur:1"]) == ["date"] * 3 + ["initiales"] * 5 + ["signature"] * 2
    # Locataire 1 : pareil, plus les initiales de l'engagement solidaire (deux locataires au bail).
    assert sorted(c.kind for c in par["tal:locataire:1"]) == ["date"] * 3 + ["initiales"] * 6 + ["signature"] * 2
    assert sorted(c.kind for c in par["tal:caution:1"]) == ["date", "signature"]
    assert all(c.required and 1 <= c.page <= 4 and 0 <= c.x < 1 and 0 <= c.y < 1 for c in champs)
    # La signature du locataire en section H tombe sur SA ligne du formulaire (page 4, 2e colonne).
    h = [c for c in par["tal:locataire:1"] if c.kind == "signature" and c.page == 4 and abs(c.y * 1008 - 243) < 1]
    assert len(h) == 1 and abs(h[0].x * 612 - 302) < 1 and abs(h[0].w * 612 - 166) < 1
    # Le formulaire transmis au TAL n'a pas bougé.
    assert json.loads(payload)["locataires"][1].get("courrielLocataire", "") == ""
    # Un second clic ne crée pas un second envoi.
    r2 = client.post(f"{BASE}/transmissions/{tid}/signature/envoyer", headers=auth_headers, json={})
    assert r2.status_code == 409 and "déjà en signature" in r2.json()["detail"]
    assert len(faux_mailer.sent) == 3


def test_independant_de_la_section_signature(client, auth_headers):
    doc_id = IDS["doc1"]
    # Le document existe, mais ce n'est pas un document de la section Signature de Gestion d'entreprise.
    assert client.get(f"/api/v1/esign/documents/{doc_id}", headers=auth_headers).status_code == 200
    for groupe in (None, "en_cours", "signes"):
        liste = client.get("/api/v1/esign/documents", headers=auth_headers, params={"group": groupe} if groupe else None)
        assert liste.status_code == 200, liste.text
        assert doc_id not in [d["id"] for d in liste.json()]
        assert not [d for d in liste.json() if d["filename"].startswith("bail-tal-")]
    # Les signataires d'un bail n'entrent pas dans la banque de contacts d'affaires.
    contacts = client.get("/api/v1/contacts/all", headers=auth_headers)
    assert contacts.status_code == 200, contacts.text
    assert not [c for c in contacts.json() if c.get("source") == "esign_signer" and (c.get("email") or "").endswith("@exemple.ca")]
    # Le suivi se lit dans Gestion immobilière : liste des baux et écran du bail.
    item = next(x for x in client.get(f"{BASE}/independants", headers=auth_headers).json()["items"] if x["id"] == IDS["tid"])
    assert item["signature"]["statut"] == "envoye" and "url" not in item["signature"]


def test_suivi_renvoyer_corriger_annuler(client, auth_headers, run, faux_mailer):
    tid = IDS["tid"]
    s = client.get(f"{BASE}/transmissions/{tid}/signature/personnes", headers=auth_headers).json()["signature"]
    qui = {x["role"]: x for x in s["signataires"]}
    base = f"{BASE}/transmissions/{tid}/signature"
    # Renvoyer l'invitation à une seule personne.
    r = client.post(f"{base}/signataires/{qui['locataire']['id']}/renvoyer", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert len(faux_mailer.sent) == 1 and faux_mailer.sent[0]["to"] == ["julie.roy@exemple.ca"] and faux_mailer.sent[0]["subject"].startswith("Rappel")
    # Corriger un courriel : l'invitation part à la nouvelle adresse, l'ancien lien meurt.
    ancien_jeton = IDS["jetons1"]["paul.roy@exemple.ca"]
    assert client.get(f"/api/v1/public/esign/{ancien_jeton}").status_code == 200
    r = client.patch(f"{base}/signataires/{qui['caution']['id']}", headers=auth_headers, json={"courriel": "pas un courriel"})
    assert r.status_code == 422, r.text
    r = client.patch(f"{base}/signataires/{qui['caution']['id']}", headers=auth_headers, json={"courriel": "Paul.Nouveau@exemple.ca"})
    assert r.status_code == 200, r.text
    caution = next(x for x in r.json()["signature"]["signataires"] if x["role"] == "caution")
    assert caution["email"] == "paul.nouveau@exemple.ca" and caution["ouvert_le"] is None
    assert faux_mailer.sent[-1]["to"] == ["paul.nouveau@exemple.ca"] and len(faux_mailer.sent) == 2
    assert client.get(f"/api/v1/public/esign/{ancien_jeton}").status_code == 404
    # Un signataire d'un autre document ne se pilote pas par ce bail.
    assert client.post(f"{base}/signataires/999999/renvoyer", headers=auth_headers).status_code == 404
    assert client.patch(f"{base}/signataires/999999", headers=auth_headers, json={"courriel": "x@exemple.ca"}).status_code == 404
    # Annuler : les liens cessent de fonctionner, le bail peut repartir en signature.
    jeton_julie = IDS["jetons1"]["julie.roy@exemple.ca"]
    r = client.post(f"{base}/annuler", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["signature"]["statut"] == "annule" and r.json()["signature"]["peut_envoyer"] is True
    assert client.get(f"/api/v1/public/esign/{jeton_julie}").status_code == 410
    assert client.post(f"{base}/annuler", headers=auth_headers).status_code == 409
    assert client.post(f"{base}/signataires/{qui['locataire']['id']}/renvoyer", headers=auth_headers).status_code == 409


def test_nouvel_envoi_avec_courriel_ajoute_puis_signature_complete(client, auth_headers, run, faux_mailer):
    tid = IDS["tid"]
    # Le courriel de Sam est inscrit au moment de l'envoi : il signe en ligne, sur SA ligne (2e locataire).
    r = client.post(f"{BASE}/transmissions/{tid}/signature/envoyer", headers=auth_headers,
                    json={"courriels": {"locataire:2": "sam.cote@exemple.ca", "autre:1": "paul.nouveau@exemple.ca"}})
    assert r.status_code == 200, r.text
    b = r.json()
    doc_id = b["esign_document_id"]
    assert doc_id != IDS["doc1"] and b["envoyes"] == 4 and b["sans_courriel"] == []
    assert sorted(m["to"][0] for m in faux_mailer.sent) == ["julie.roy@exemple.ca", "marc.tremblay@exemple.ca", "paul.nouveau@exemple.ca", "sam.cote@exemple.ca"]

    async def _etat():
        async with TestSessionLocal() as db:
            ancien = await db.get(EsignDocument, IDS["doc1"])
            signataires = (await db.execute(select(EsignSigner).where(EsignSigner.document_id == doc_id).order_by(EsignSigner.order_index))).scalars().all()
            champs = (await db.execute(select(EsignField).where(EsignField.document_id == doc_id))).scalars().all()
            lien = await sig.lien_de_suivi(db, doc_id)
            return ancien, signataires, champs, lien, await sig.lien_de_suivi(db, 999999)

    ancien, signataires, champs, lien, lien_inconnu = run(_etat())
    assert ancien is not None and ancien.status == "annule" and ancien.origine == "bail_tal"      # l'envoi annulé reste au dossier
    assert lien == "/immobilier/admin-locative?onglet=baux" and lien_inconnu is None
    sam = next(sg for sg in signataires if sg.email == "sam.cote@exemple.ca")
    assert sam.contact_ref == "tal:locataire:2"
    zones_sam = [c for c in champs if c.signer_id == sam.id]
    assert sorted(c.kind for c in zones_sam) == ["date"] * 2 + ["initiales"] * 6 + ["signature"] * 2
    h = [c for c in zones_sam if c.kind == "signature" and abs(c.y * 1008 - 273) < 1]
    assert len(h) == 1 and abs(h[0].x * 612 - 302) < 1                                          # 2e rangée de la section H

    # Chaque personne signe par son lien : une signature et des initiales tracées une fois, posées partout.
    image = _png()
    for i, sg in enumerate(signataires):
        vu = client.get(f"/api/v1/public/esign/{sg.signature_token}")
        assert vu.status_code == 200, vu.text
        miens = [f for f in vu.json()["fields"] if f["mine"]]
        assert miens and vu.json()["page_count"] == 4
        corps = {"signature_data_url": image, "consent": True}
        if any(f["kind"] == "initiales" for f in miens):
            corps["initials_data_url"] = image
        r = client.post(f"/api/v1/public/esign/{sg.signature_token}/sign", json=corps)
        assert r.status_code == 200, r.text
        assert r.json()["completed"] is (i == len(signataires) - 1)

    e = client.get(f"{BASE}/transmissions/{tid}/signature/personnes", headers=auth_headers).json()
    assert e["signature"]["statut"] == "complete" and e["signature"]["nb_signes"] == 4 and e["signature"]["peut_annuler"] is False
    assert e["signe_le"] and e["document_signe_id"]
    # Le PDF signé (bail + certificat) est archivé comme bail signé, hors de tout dossier Kratos.
    async def _signe():
        async with TestSessionLocal() as db:
            d = await db.get(ImmDocument, e["document_signe_id"])
            blob = (await db.execute(select(ImmDocument.pdf_blob).where(ImmDocument.id == d.id))).scalar_one()
            return d.type, bytes(blob)

    type_doc, blob = run(_signe())
    from pypdf import PdfReader

    assert type_doc == "bail_tal_signe" and blob.startswith(b"%PDF-") and len(PdfReader(io.BytesIO(blob)).pages) >= 5
    # Les copies finales partent aux signataires.
    assert any(m["subject"].startswith("Document signé") and m.get("attachments") for m in faux_mailer.sent)
    # Un bail signé ne repart pas en signature.
    r = client.post(f"{BASE}/transmissions/{tid}/signature/envoyer", headers=auth_headers, json={})
    assert r.status_code == 409 and "déjà signé" in r.json()["detail"]


def test_refus_quand_le_formulaire_ne_suit_pas_le_gabarit(client, auth_headers, run):
    # Trois locataires : le formulaire officiel n'a que deux lignes de signature par partie.
    trois = {**BAIL, "libelle": "Trois locataires", "locataires": BAIL["locataires"] + [{"nom": "Léa Roy", "courriel": "lea.roy@exemple.ca"}]}
    r = client.post(f"{BASE}/independants", headers=auth_headers, json=trois)
    assert r.status_code == 201, r.text
    t3 = r.json()["id"]
    assert client.post(f"{BASE}/transmissions/{t3}/generer", headers=auth_headers, json={"confirme": True}).status_code == 200
    e = client.get(f"{BASE}/transmissions/{t3}/signature/personnes", headers=auth_headers).json()
    assert e["envoi_possible"] is False and "3 locataires" in e["motif"] and len(e["personnes"]) == 5
    r = client.post(f"{BASE}/transmissions/{t3}/signature/envoyer", headers=auth_headers, json={})
    assert r.status_code == 422 and "à la main" in r.json()["detail"], r.text

    # Un PDF qui n'est pas le formulaire connu, ou un bail en anglais : aucune zone posée à l'aveugle.
    r = client.post(f"{BASE}/independants", headers=auth_headers, json={**BAIL, "libelle": "Autre gabarit"})
    autre = r.json()["id"]
    g = client.post(f"{BASE}/transmissions/{autre}/generer", headers=auth_headers, json={"confirme": True}).json()

    async def _changer(pdf=None, langue=None):
        async with TestSessionLocal() as db:
            if pdf is not None:
                d = await db.get(ImmDocument, g["document_id"])
                d.pdf_blob = pdf
            if langue is not None:
                t = await db.get(TalTransmission, autre)
                t.langue = langue
            await db.commit()

    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 1008))
    for _ in range(4):
        c.drawString(72, 900, "Formulaire refait par le TAL")
        c.showPage()
    c.save()
    officiel = tal_client.pdf_simulation({}, "SIM-en")
    run(_changer(pdf=buf.getvalue()))
    e = client.get(f"{BASE}/transmissions/{autre}/signature/personnes", headers=auth_headers).json()
    assert e["envoi_possible"] is False and "ne correspond pas au formulaire connu" in e["motif"]
    r = client.post(f"{BASE}/transmissions/{autre}/signature/envoyer", headers=auth_headers, json={})
    assert r.status_code == 422 and "impossible" in r.json()["detail"], r.text
    assert client.get(f"{BASE}/transmissions/{autre}", headers=auth_headers).json()["esign_document_id"] is None
    run(_changer(pdf=officiel, langue="en"))
    e = client.get(f"{BASE}/transmissions/{autre}/signature/personnes", headers=auth_headers).json()
    assert e["envoi_possible"] is False and "français" in e["motif"]
    run(_changer(langue="fr"))
    assert client.get(f"{BASE}/transmissions/{autre}/signature/personnes", headers=auth_headers).json()["envoi_possible"] is True
