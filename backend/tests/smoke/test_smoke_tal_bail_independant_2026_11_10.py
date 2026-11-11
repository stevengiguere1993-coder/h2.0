"""Smoke — bail officiel du TAL « indépendant », hors système Kratos (Phil 2026-11-10).

« Une page… bail indépendant… je vais rentrer les informations dans un genre de
petit formulaire puis ça va créer le bail. Ça va être mon environnement test et en
même temps un environnement pour créer un bail pour un ami… quelqu'un qui n'est
pas dans mon système. »

Verrouille, SANS aucun appel réseau :
- le petit formulaire passe par LE MÊME mapping que les baux Kratos (locateur
  nommé, locataires, caution, adresse découpée, pièces, durée, loyer) ;
- aucun lien Kratos : pas de bail, pas d'immeuble, pas de frais refacturé ;
- brouillon créé même incomplet (la validation dit ce qui manque) ;
- génération en simulation, PDF archivé sans rattachement, journal des appels ;
- signature : le locateur signe lui-même, jamais la personne qui prépare le bail ;
  fin de signature = PDF signé archivé, aucun bail à activer ;
- duplication, annulation, liste ;
- la clé de l'API n'apparaît jamais (erreur, journal, réponse HTTP).
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.integrations.tal import client as tal_client
from app.models.immobilier import FraisManuelGestion, ImmDocument
from app.models.tal_bail import TalTransmission
from app.services import tal_bail as svc
from tests.smoke.conftest import TestSessionLocal

BASE = "/api/v1/immobilier/tal-bail"
IDS: dict = {}

ESSENTIEL = {
    "libelle": "Bail de Marc",
    "locateur": {"nom": "Marc Tremblay", "telephone": "514-555-0199", "courriel": "marc@exemple.test", "adresse": "12 rue des Érables, Laval (Québec) H7A 1B2"},
    "locataires": [
        {"nom": "Julie Roy", "telephone": "438-555-0142", "courriel": "julie@exemple.test", "adresse": "88 avenue du Parc, Montréal H2V 4E1"},
        {"nom": "Sam Côté", "courriel": "sam@exemple.test"},
    ],
    "cautions": [{"nom": "Paul Roy", "courriel": "paul@exemple.test"}],
    "adresse": "4521 rue Saint-Denis", "appartement": "3", "ville": "Montréal", "code_postal": "H2J 2L4",
    "nb_pieces": 4.5, "date_debut": "2027-07-01", "date_fin": "2028-06-30", "loyer_mensuel": 1450,
    "jour_echeance": 1, "electricite_inclus": False, "chauffage_inclus": False, "internet_inclus": True,
}


def test_petit_formulaire_meme_mapping_que_les_baux_kratos(client, auth_headers, employee_headers):
    assert client.post(f"{BASE}/independants", headers=employee_headers, json=ESSENTIEL).status_code == 403
    r = client.post(f"{BASE}/independants", headers=auth_headers, json=ESSENTIEL)
    assert r.status_code == 201, r.text
    t = r.json()
    IDS["tid"] = t["id"]
    assert t["independant"] is True and t["bail_id"] is None and t["immeuble_id"] is None and t["locataire_id"] is None
    assert t["statut"] == "brouillon" and t["libelle"] == "Bail de Marc" and t["identifiant_utilisateur"] == f"kratos-ind-t{t['id']}"
    assert t["adresse"] == "4521 rue Saint-Denis, app. 3, Montréal"
    f = t["form"]
    # Locateur nommé (pas d'entreprise Kratos), il signe lui-même : pas de représentant.
    loc = f["locateurs"][0]
    assert loc["nom"] == "Marc Tremblay" and loc["courrielLocateur"] == "marc@exemple.test" and loc["noTelephone"] == "514-555-0199"
    assert loc["questionRepresentant"] == "false" and loc["representant"] == ""
    assert loc["adresse"][0]["NoCivique"] == "12" and loc["adresse"][0]["Municipalite"] == "Laval" and loc["adresse"][0]["CodePostal"] == "H7A 1B2"
    # Deux locataires → solidarité présumée ; caution en autre signataire.
    assert [x["nom"] for x in f["locataires"]] == ["Julie Roy", "Sam Côté"] and f["locataires"][0]["courrielLocataire"] == "julie@exemple.test"
    assert f["locataires"][0]["adresse"][0]["Rue"].lower().startswith("avenue du parc")
    assert f["estLocatairesEngagementSolidaire"] == "true" and f["possedeAutresSignataires"] == "true"
    assert f["autresSignataires"][0]["nom"] == "Paul Roy" and f["autresSignataires"][0]["qualite"] == "Caution"
    # Logement, durée, loyer : mêmes clés que le mapping Kratos.
    a = f["adresseLogement"][0]
    assert (a["NoCivique"], a["Rue"], a["Appartement"], a["Municipalite"], a["CodePostal"]) == ("4521", "rue Saint-Denis", "3", "Montréal", "H2J 2L4")
    assert f["nbPieces"] == "quatre-demi" and f["typeBail"] == "dureeFixe"
    assert f["dateDebutBail"] == "2027-07-01" and f["dateFinBail"] == "2028-06-30" and f["nbSemainesMoisAnnees"] == "1 an"
    assert f["coutLoyer"] == "1450.00" and f["coutTotalLoyer"] == "1450.00" and f["frequenceCoutLoyer"] == "mois" and f["termesPaiement"] == "permierJourMois"
    assert f["responsabiliteChauffage"] == "locataire"
    assert f["responsabiliteServicesTaxesCoutsConsommation"][0]["responsabiliteElectricite"] == "locataire"
    assert f["possedeAutresServicesConditionsRestriction"] == "true" and "Internet" in f["precisionAutresServicesConditionsRestriction"]
    # Blocs de signature vides, rapport valide, parties lisibles sans fiche Kratos.
    assert f["signatureLocataire1"][0]["NomComplet"] == "" and t["rapport"]["valide"] is True
    assert t["parties"]["locateurs"] == ["Marc Tremblay"] and t["parties"]["locataires"] == ["Julie Roy", "Sam Côté"]
    assert t["parties"]["cautions"] == ["Paul Roy"] and t["parties"]["loyer"] == "1450.00"
    # Les notes « à vérifier » ne parlent pas de fiches Kratos qui n'existent pas.
    notes = " | ".join(x["note"] for x in t["a_verifier"])
    assert "fiche" not in notes and "immeuble introuvable" not in notes

    # Brouillon créé même vide (comme un bail papier) : la validation dit ce qui manque.
    r = client.post(f"{BASE}/independants", headers=auth_headers, json={})
    assert r.status_code == 201, r.text
    vide = r.json()
    IDS["vide"] = vide["id"]
    assert vide["independant"] is True and vide["rapport"]["valide"] is False and vide["adresse"] is None
    assert any("locataires[0].nom" in e for e in vide["rapport"]["erreurs"])
    assert any("à saisir" in x["note"] for x in vide["a_verifier"])
    # Au mois + échéance le 15.
    r = client.post(f"{BASE}/independants", headers=auth_headers, json={**ESSENTIEL, "libelle": "Au mois", "au_mois": True, "date_fin": None, "jour_echeance": 15})
    f2 = r.json()["form"]
    IDS["au_mois"] = r.json()["id"]
    assert f2["typeBail"] == "dureeIndeterminee" and f2["dateDebutBailDureeIndeterminee"] == "2027-07-01"
    assert f2["termesPaiement"] == "autre" and f2["precisionAutresTermes"] == "Le 15 de chaque mois"


def test_liste_filtre_et_formulaire_enregistre(client, auth_headers, run):
    r = client.get(f"{BASE}/independants", headers=auth_headers)
    assert r.status_code == 200, r.text
    ids = [x["id"] for x in r.json()["items"]]
    assert IDS["tid"] in ids and IDS["vide"] in ids and all(x["independant"] for x in r.json()["items"])
    item = next(x for x in r.json()["items"] if x["id"] == IDS["tid"])
    assert item["parties"]["locataires"] == ["Julie Roy", "Sam Côté"] and item["signature"] is None and "form" not in item
    # Filtre de la liste générale.
    tous = client.get(f"{BASE}/transmissions", headers=auth_headers, params={"independant": True}).json()["items"]
    assert IDS["tid"] in [x["id"] for x in tous] and all(x["independant"] for x in tous)
    hors = client.get(f"{BASE}/transmissions", headers=auth_headers, params={"independant": False}).json()["items"]
    assert IDS["tid"] not in [x["id"] for x in hors]
    # L'écran du bail relit le formulaire enregistré (même forme que ?bail_id=).
    r = client.get(f"{BASE}/preparer", headers=auth_headers, params={"transmission_id": IDS["tid"]})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["form"]["locataires"][0]["nom"] == "Julie Roy" and p["contexte"]["independant"] is True and p["mode"] == "simulation"
    assert p["rapport"]["valide"] is True and [x["id"] for x in p["transmissions"]] == [IDS["tid"]] and p["cout_tal"] == 2.99
    assert client.get(f"{BASE}/preparer", headers=auth_headers).status_code == 422
    assert client.get(f"{BASE}/preparer", headers=auth_headers, params={"transmission_id": 999999}).status_code == 404

    # Une transmission liée à un bail Kratos ne s'ouvre pas par cette porte.
    async def _liee():
        async with TestSessionLocal() as s:
            t = TalTransmission(statut="brouillon", payload_json="{}")
            s.add(t)
            await s.commit()
            return t.id

    liee = run(_liee())
    assert client.get(f"{BASE}/preparer", headers=auth_headers, params={"transmission_id": liee}).status_code == 422
    assert client.post(f"{BASE}/independants", headers=auth_headers, json={"source_id": liee}).status_code == 422


def test_flux_simulation_sans_rattachement_ni_frais(client, auth_headers, run):
    tid = IDS["tid"]
    # Correction dans le formulaire complet : l'adresse affichée suit.
    det = client.get(f"{BASE}/transmissions/{tid}", headers=auth_headers).json()
    form = det["form"]
    form["adresseLogement"][0]["Appartement"] = "4"
    form["coutLoyer"] = "1500"
    form["coutTotalLoyer"] = "1500"
    r = client.patch(f"{BASE}/transmissions/{tid}", headers=auth_headers, json={"form": form})
    assert r.status_code == 200, r.text
    assert r.json()["adresse"] == "4521 rue Saint-Denis, app. 4, Montréal" and r.json()["rapport"]["valide"] is True
    # Confirmation obligatoire, puis génération en simulation.
    assert client.post(f"{BASE}/transmissions/{tid}/generer", headers=auth_headers, json={}).status_code == 422
    r = client.post(f"{BASE}/transmissions/{tid}/generer", headers=auth_headers, json={"confirme": True})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["statut"] == "transmise" and g["mode"] == "simulation" and g["cout"] == 0 and g["independant"] is True
    assert g["frais_manuel_id"] is None and g["frais_montant"] is None and g["short_guid"].startswith("SIM-")
    assert g["parties"]["loyer"] == "1500.00"      # « 1500 » saisi → format de l'exemple du TAL à l'envoi
    # Un formulaire incomplet ne part pas.
    r = client.post(f"{BASE}/transmissions/{IDS['vide']}/generer", headers=auth_headers, json={"confirme": True})
    assert r.status_code == 422, r.text
    # Journal des appels : étapes, sans le PDF.
    det = client.get(f"{BASE}/transmissions/{tid}", headers=auth_headers).json()
    j = det["journal"]
    assert j["appel"]["mode"] == "simulation" and j["appel"]["tentative"] == 1 and j["appel"]["langue"] == "fr"
    assert j["appel"]["chemin_frw111"] == "/api/v1/SIS/CreerFormulaireIndividu/{typeFormulaire}" and j["appel"]["url"].startswith("https://")
    assert j["frw111"]["short_guid"] == g["short_guid"] and j["frw122"]["no_confirmation"] == g["no_confirmation"]
    assert "%PDF" not in json.dumps(j) and j["frw122"]["documents"][0]["taille"] > 500

    async def _verif():
        async with TestSessionLocal() as s:
            doc = await s.get(ImmDocument, g["document_id"])
            blob = (await s.execute(select(ImmDocument.pdf_blob).where(ImmDocument.id == doc.id))).scalar_one()
            nb_frais = len((await s.execute(select(FraisManuelGestion))).scalars().all())
            return {"type": doc.type, "liens": (doc.bail_id, doc.locataire_id, doc.immeuble_id, doc.logement_id),
                    "pdf": bytes(blob[:5]), "titre": doc.titre, "nb_frais": nb_frais}

    v = run(_verif())
    assert v["type"] == "bail_tal" and v["liens"] == (None, None, None, None) and v["pdf"] == b"%PDF-"
    assert "4521 rue Saint-Denis" in v["titre"]
    IDS["nb_frais"] = v["nb_frais"]
    # Le formulaire d'un bail transmis ne se modifie plus.
    assert client.patch(f"{BASE}/transmissions/{tid}", headers=auth_headers, json={"form": form}).status_code == 409


def test_signature_le_locateur_signe_lui_meme(client, auth_headers, run):
    tid = IDS["tid"]
    r = client.post(f"{BASE}/transmissions/{tid}/signature", headers=auth_headers, json={})
    assert r.status_code == 201, r.text
    body = r.json()
    sig = body["signature"]
    noms = sorted(s["nom"] for s in sig["signataires"])
    assert noms == ["Julie Roy", "Marc Tremblay", "Paul Roy", "Sam Côté"], noms
    courriels = {s["nom"]: s["email"] for s in sig["signataires"]}
    assert courriels["Marc Tremblay"] == "marc@exemple.test"           # le locateur, pas la personne qui prépare
    assert not any((s["email"] or "").endswith("@test.local") for s in sig["signataires"])
    assert body["sans_courriel"] == []
    esign_id = body["esign_document_id"]
    # La liste montre l'avancement de la signature.
    item = next(x for x in client.get(f"{BASE}/independants", headers=auth_headers).json()["items"] if x["id"] == tid)
    assert item["signature"]["nb_signataires"] == 4 and item["esign_document_id"] == esign_id

    # Fin de signature : PDF signé archivé, aucun bail Kratos à activer, idempotent.
    async def _fin():
        async with TestSessionLocal() as s:
            r1 = await svc.apres_signature_complete(s, esign_id, pdf=b"%PDF-1.4 signe par tous")
            r2 = await svc.apres_signature_complete(s, esign_id, pdf=b"%PDF-1.4 signe par tous")
            doc = await s.get(ImmDocument, r1["document_signe_id"])
            return r1, r2, doc.type, (doc.bail_id, doc.immeuble_id), doc.signed_by_name

    r1, r2, type_doc, liens, signe_par = run(_fin())
    assert r1["independant"] is True and r1["bail_id"] is None and r2.get("deja") is True
    assert type_doc == "bail_tal_signe" and liens == (None, None) and "Marc Tremblay" in signe_par
    det = client.get(f"{BASE}/transmissions/{tid}", headers=auth_headers).json()
    assert det["signe_le"] and det["document_signe_id"] == r1["document_signe_id"]

    # Locateur représenté : c'est le représentant nommé au bail qui signe.
    sigs, manquants = svc.signataires_depuis_formulaire(
        {"locateurs": [{"nom": "Gestion ABC inc.", "questionRepresentant": "true", "representant": "Lise Gagnon", "courrielRepresentant": "lise@abc.test"},
                       {"nom": "Sans Courriel"}],
         "locataires": [{"nom": "Julie Roy", "courrielLocataire": "julie@exemple.test"}]},
        locateurs_signent=True,
    )
    assert [(s["nom_complet"], s["role"]) for s in sigs] == [("Julie Roy", "locataire"), ("Lise Gagnon", "locateur")]
    assert manquants == ["Sans Courriel (locateur)"]


def test_dupliquer_annuler_et_liste(client, auth_headers):
    r = client.post(f"{BASE}/independants", headers=auth_headers, json={"source_id": IDS["tid"], "libelle": "Copie"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["id"] != IDS["tid"] and c["statut"] == "brouillon" and c["libelle"] == "Copie" and c["short_guid"] is None
    assert c["form"]["coutLoyer"] == "1500.00" and c["form"]["locataires"][0]["nom"] == "Julie Roy" and c["document_id"] is None
    assert c["adresse"] == "4521 rue Saint-Denis, app. 4, Montréal" and c["journal"] is None
    # Annulé : hors de la liste par défaut, visible sur demande.
    assert client.post(f"{BASE}/transmissions/{c['id']}/annuler", headers=auth_headers).status_code == 200
    assert c["id"] not in [x["id"] for x in client.get(f"{BASE}/independants", headers=auth_headers).json()["items"]]
    assert c["id"] in [x["id"] for x in client.get(f"{BASE}/independants", headers=auth_headers, params={"inclure_annules": True}).json()["items"]]
    # Un bail transmis ne s'annule pas.
    assert client.post(f"{BASE}/transmissions/{IDS['tid']}/annuler", headers=auth_headers).status_code == 409


def test_la_cle_ne_sort_jamais(client, auth_headers, run, monkeypatch):
    secret = "SECRET-CLE-TAL-123456"

    # 1. Le client masque la clé si le TAL la renvoie dans son message d'erreur.
    vu: dict = {}

    class _Rep:
        status_code = 401
        text = '{"erreur": "cle ' + secret + ' invalide"}'

        def json(self):
            return json.loads(self.text)

    class _Http:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, content=None):
            vu.update(url=url, headers=headers, json=json)
            return _Rep()

    monkeypatch.setattr(tal_client.httpx, "AsyncClient", _Http)
    c = tal_client.ClientTal(tal_client.ConnexionTal(mode="reel", url="https://tal.exemple.test/api", cle=secret))
    with pytest.raises(tal_client.TalApiError) as ei:
        run(c.creer_formulaire({"coutLoyer": "1"}, identifiant_utilisateur="kratos-ind-t1"))
    assert secret not in str(ei.value) and secret not in str(ei.value.corps) and "***" in ei.value.message
    # Adresse et en-tête de la documentation du TAL ; le message dit quoi vérifier.
    assert ei.value.http_status == 401 and vu["url"] == "https://tal.exemple.test/api/api/v1/SIS/CreerFormulaireIndividu/53000BAIL"
    assert vu["headers"]["X-ClePartenaire"] == secret and vu["json"] == {"form": {"coutLoyer": "1"}}   # la clé ne part que dans l'en-tête
    assert vu["headers"]["Accept-Language"] == "fr-CA" and "clé refusée par le TAL" in ei.value.message

    # 2. Même si une erreur portait la clé, elle est masquée à l'écran, dans la fiche et au journal.
    class _Casse:
        simulation = False
        mode = tal_client.MODE_REEL

        async def creer_formulaire(self, form, *, langue=None, identifiant_utilisateur=None):
            raise tal_client.TalApiError("FRW111", f"HTTP 401 : clé {secret} refusée", http_status=401, corps={"detail": f"clé {secret} refusée"})

    async def _cx(db):
        return tal_client.ConnexionTal(mode="reel", url="https://tal.exemple.test/api", cle=secret), {}

    monkeypatch.setattr(svc, "_fabrique_client", lambda cx: _Casse())
    monkeypatch.setattr(svc, "charger_connexion", _cx)
    tid = IDS["au_mois"]
    r = client.post(f"{BASE}/transmissions/{tid}/generer", headers=auth_headers, json={"confirme": True})
    assert r.status_code == 502, r.text
    assert secret not in r.text and "***" in r.text
    det = client.get(f"{BASE}/transmissions/{tid}", headers=auth_headers).json()
    assert secret not in json.dumps(det, ensure_ascii=False)
    assert det["statut"] == "echec" and det["short_guid"] is None and "***" in det["erreur"]
    j = det["journal"]
    assert j["appel"]["mode"] == "reel" and j["appel"]["url"] == "https://tal.exemple.test/api" and j["appel"]["entete_cle"] == "X-ClePartenaire"
    assert j["frw111_erreur"]["http_status"] == 401 and "***" in j["frw111_erreur"]["message"] and "***" in j["frw111_erreur"]["corps"]["detail"]
    # Un échec avant le ShortGuid ne coûte rien : compteur intact, aucun frais.
    cpt = client.get(f"{BASE}/compteur", headers=auth_headers).json()
    assert cpt["total_reel_depuis_le_debut"] == 0 or cpt["gratuits_restants"] <= 10

    async def _frais():
        async with TestSessionLocal() as s:
            return len((await s.execute(select(FraisManuelGestion))).scalars().all())

    assert run(_frais()) == IDS["nb_frais"]


def test_formats_reels_des_reponses_du_tal(run, monkeypatch):
    """Exemples fournis par le TAL avec la clé (2026-11-10) : le numéro public du
    formulaire s'appelle ``noPublicForm`` ; le document porte ``fichier`` (base64) et
    ``_type`` ; pas de numéro de confirmation. Le corps du FRW111 est exactement
    l'objet de pré-remplissage ``{"form": {...}}``."""
    import base64

    pdf = b"%PDF-1.5 bail officiel de test"
    reponses = {
        "FRW111": {"noPublicSession": "07rUQYLu10OFHFglEOghJg", "noPublicForm": "Xs0S6bsB8UCSbK1F-HvUOw", "noTransactionChiffre": None},
        "FRW122": {
            "documents": [{"nom": "Bail de logement.pdf", "fichier": base64.b64encode(pdf).decode("ascii"), "_type": "genererPDF"}],
            "messages": [{"mnemonique": "TypeFormulaire", "message": "53000BAIL"}],
        },
    }
    appels: list = []

    class _Rep:
        status_code = 200
        text = ""

        def __init__(self, corps):
            self._corps = corps

        def json(self):
            return self._corps

    class _Http:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, content=None):
            appels.append((url, json, content, dict(headers or {})))
            return _Rep(reponses["FRW111" if "CreerFormulaireIndividu" in url else "FRW122"])

    monkeypatch.setattr(tal_client.httpx, "AsyncClient", _Http)
    c = tal_client.ClientTal(tal_client.ConnexionTal(mode="reel", url="https://tal.exemple.test/api", cle="cle-factice-123456"))

    async def _go():
        rc = await c.creer_formulaire({"coutLoyer": "1450"}, identifiant_utilisateur="kratos-ind-t7")
        rt = await c.declencher_transmission(rc.short_guid, langue="en", identifiant_utilisateur="kratos-ind-t7")
        return rc, rt

    rc, rt = run(_go())
    assert rc.short_guid == "Xs0S6bsB8UCSbK1F-HvUOw" and rc.no_public_session == "07rUQYLu10OFHFglEOghJg"
    # FRW111 : type de formulaire dans l'adresse, corps = le pré-remplissage et rien d'autre.
    base = "https://tal.exemple.test/api/api/v1/SIS"
    assert appels[0][0] == f"{base}/CreerFormulaireIndividu/53000BAIL" and appels[0][1] == {"form": {"coutLoyer": "1450"}}
    assert appels[0][3]["X-ClePartenaire"] == "cle-factice-123456" and appels[0][3]["Accept-Language"] == "fr-CA"
    # FRW122 : tout est dans l'adresse (numéro public + « transmission-personnalisee »), AUCUN corps ;
    # la langue demandée est celle du bail produit.
    assert appels[1][0] == f"{base}/DeclencherTransmissionPersonnalisee/Xs0S6bsB8UCSbK1F-HvUOw/transmission-personnalisee"
    assert appels[1][1] is None and appels[1][2] == b"" and "Content-Type" not in appels[1][3]
    assert appels[1][3]["X-ClePartenaire"] == "cle-factice-123456" and appels[1][3]["Accept-Language"] == "en-CA"
    d = rt.documents[0]
    assert d.nom == "Bail de logement.pdf" and d.type_source == "genererPDF" and d.octets() == pdf
    assert rt.messages == [{"mnemonique": "TypeFormulaire", "texte": "53000BAIL"}] and rt.no_confirmation is None

    # Une réponse sans numéro public est une erreur claire, jamais un faux succès.
    reponses["FRW111"] = {"noPublicSession": "x"}
    with pytest.raises(tal_client.TalApiError) as ei:
        run(c.creer_formulaire({"coutLoyer": "1"}))
    assert "noPublicForm" in ei.value.message


def test_adresse_de_l_api_en_https_seulement(client, auth_headers, run, monkeypatch):
    """La clé ne voyage jamais en clair : une adresse d'API en http est refusée à
    l'enregistrement, et le client refuse d'appeler une adresse non chiffrée."""
    avant = client.get(f"{BASE}/etat", headers=auth_headers).json()["connexion"]["api_url"]
    r = client.put(f"{BASE}/parametres", headers=auth_headers, json={"api_url": "http://api.tal.exemple.ca/frw"})
    assert r.status_code == 422 and "https" in r.json()["detail"]
    assert client.get(f"{BASE}/etat", headers=auth_headers).json()["connexion"]["api_url"] == avant
    # Une adresse en https passe, une adresse vide aussi (on peut poser la clé avant l'adresse).
    assert client.put(f"{BASE}/parametres", headers=auth_headers, json={"api_url": "HTTPS://api.tal.exemple.ca/frw/"}).status_code == 200
    assert client.put(f"{BASE}/parametres", headers=auth_headers, json={"api_url": ""}).status_code == 200
    # Adresse vide = adresse officielle de la documentation du TAL.
    assert client.get(f"{BASE}/etat", headers=auth_headers).json()["connexion"]["api_url"] == "https://formulaires.mtess.gouv.qc.ca"

    appels: list = []

    class _Http:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            appels.append(url)
            raise AssertionError("aucun appel ne doit partir vers une adresse non chiffrée")

    monkeypatch.setattr(tal_client.httpx, "AsyncClient", _Http)
    c = tal_client.ClientTal(tal_client.ConnexionTal(mode="reel", url="http://tal.exemple.test/api", cle="cle-factice-123456"))
    for appel in (c.creer_formulaire({"coutLoyer": "1450"}), c.declencher_transmission("Xs0S6bsB8UCSbK1F-HvUOw")):
        with pytest.raises(tal_client.TalApiError) as exc:
            run(appel)
        assert "https" in (str(exc.value) + str(getattr(exc.value, "message", "")))
    assert appels == []


def test_connexion_officielle_du_tal_sans_rien_saisir(client, auth_headers, run):
    """Documentation « APIdocPartenaires » (TAL, 3 nov. 2026) : adresse, en-tête et chemins sont
    les défauts de Kratos. Les anciennes hypothèses restées enregistrées (X-Api-Key, /FRW111/…)
    sont remplacées d'office ; un réglage identique à la documentation ne s'enregistre pas."""
    officiel = {
        "api_url": "https://formulaires.mtess.gouv.qc.ca",
        "entete_cle": "X-ClePartenaire",
        "chemin_frw111": "/api/v1/SIS/CreerFormulaireIndividu/{typeFormulaire}",
        "chemin_frw122": "/api/v1/SIS/DeclencherTransmissionPersonnalisee/{noPublicFormulaire}/{idTransmissionPerso}",
    }
    assert tal_client.ID_TRANSMISSION_PERSO == "transmission-personnalisee" and tal_client.VALEURS_OFFICIELLES == officiel
    # Ce que l'écran avait enregistré avant la documentation : les anciennes hypothèses.
    r = client.put(f"{BASE}/parametres", headers=auth_headers, json={
        "api_url": "", "entete_cle": "X-Api-Key", "chemin_frw111": "/FRW111/CreerFormulaireIndividu",
        "chemin_frw122": "/FRW122/DeclencherTransmissionPersonnalisee",
    })
    assert r.status_code == 200, r.text
    cx = r.json()["connexion"]
    assert {k: cx[k] for k in officiel} == officiel and cx["valeurs_officielles"] is True and cx["officiel"] == officiel
    assert cx["url_configuree"] is True

    async def _ligne():
        async with TestSessionLocal() as s:
            row = await svc._connexion_row(s)
            return (row.api_url, row.entete_cle, row.chemin_frw111, row.chemin_frw122)

    assert run(_ligne()) == (None, None, None, None)          # rien d'enregistré : la ligne suit la documentation

    # Une ancienne hypothèse posée directement en base est écartée à la lecture.
    async def _poser_ancien():
        async with TestSessionLocal() as s:
            row = await svc._connexion_row(s)
            row.entete_cle, row.chemin_frw111 = "x-api-key", "/FRW111/CreerFormulaireIndividu"
            await s.commit()

    run(_poser_ancien())
    cx = client.get(f"{BASE}/etat", headers=auth_headers).json()["connexion"]
    assert cx["entete_cle"] == "X-ClePartenaire" and cx["chemin_frw111"] == officiel["chemin_frw111"] and cx["valeurs_officielles"] is True
    # Un vrai réglage différent reste respecté, et se voit.
    r = client.put(f"{BASE}/parametres", headers=auth_headers, json={"entete_cle": "X-Autre-Cle"})
    assert r.json()["connexion"]["entete_cle"] == "X-Autre-Cle" and r.json()["connexion"]["valeurs_officielles"] is False
    r = client.put(f"{BASE}/parametres", headers=auth_headers, json={"entete_cle": "X-ClePartenaire", "chemin_frw111": ""})
    assert r.json()["connexion"]["valeurs_officielles"] is True and run(_ligne()) == (None, None, None, None)
    # Chemins : repères remplis et encodés ; un chemin saisi sans repère reçoit les valeurs à la suite.
    assert tal_client._chemin(officiel["chemin_frw111"], typeFormulaire="53000BAIL") == "/api/v1/SIS/CreerFormulaireIndividu/53000BAIL"
    assert tal_client._chemin("api/perso/Declencher/", noPublicFormulaire="a b/c", idTransmissionPerso="transmission-personnalisee") \
        == "/api/perso/Declencher/a%20b%2Fc/transmission-personnalisee"
    # Erreur du TAL au format {type, title, status, detail, instance} : titre et détail lisibles.
    msg = tal_client._message_erreur(400, json.dumps({"type": "x", "title": "Requête invalide", "status": 400, "detail": "Le champ nbPieces est invalide.",
                                                      "errors": {"form.nbPieces": ["Valeur inconnue."]}}))
    assert msg.startswith("HTTP 400 : Requête invalide · Le champ nbPieces est invalide.") and "form.nbPieces : Valeur inconnue." in msg
    assert tal_client._message_erreur(404, "").startswith("HTTP 404 — adresse introuvable") and tal_client._message_erreur(500, "") == "HTTP 500"


def test_montants_au_format_de_l_exemple_du_tal(run):
    """Exemple « DonneesJSON53000BAIL » : les montants (type « nombre ») partent avec un point et deux
    décimales (« 780.00 », imprimé « 780,00 ») ; les compteurs (type « number ») restent entiers."""
    from app.integrations.tal.schema import charger_schema_asset

    schema = charger_schema_asset()
    form = {
        "coutLoyer": "1450", "coutServices": "30,5", "coutTotalLoyer": 1480.5, "loyerMaximalImeublePretPourUsage": "",
        "nbTables": "2", "frequenceCoutLoyer": "mois", "montantLoyerPlusBasPaye12Mois": "sur demande",
        "soinsInfirmiers": [{"coutPrepose": "20", "heuresPrepose": "1"}],
        "totaux": [{"coutTotalServices": "20", "montantLoyerBase": "1000.00", "montantLoyerTotal": 1020}],
        "stationnementExterieur": [{"nbPlaces": "3", "emplacements": "A2,B1"}],
    }
    assert svc.normaliser_montants(form, schema) == 6
    assert form["coutLoyer"] == "1450.00" and form["coutServices"] == "30.50" and form["coutTotalLoyer"] == "1480.50"
    assert form["loyerMaximalImeublePretPourUsage"] == "" and form["montantLoyerPlusBasPaye12Mois"] == "sur demande"   # vide et texte : intacts
    assert form["nbTables"] == "2" and form["stationnementExterieur"][0]["nbPlaces"] == "3"                            # compteurs : intacts
    assert form["soinsInfirmiers"][0] == {"coutPrepose": "20.00", "heuresPrepose": "1"}
    assert form["totaux"][0] == {"coutTotalServices": "20.00", "montantLoyerBase": "1000.00", "montantLoyerTotal": "1020.00"}
    assert svc.normaliser_montants(form, schema) == 0                                                                  # déjà au format


def test_langue_du_bail_choisie_a_la_generation(client, auth_headers, run, monkeypatch):
    """Accept-Language : fr-CA produit le bail en français (défaut), en-CA en anglais. La langue se
    choisit à la génération, se garde sur le bail et part aux deux appels."""
    vus: list = []

    class _Faux:
        simulation = False
        mode = tal_client.MODE_REEL

        async def creer_formulaire(self, form, *, langue=None, identifiant_utilisateur=None):
            vus.append(("FRW111", langue, form.get("coutLoyer")))
            return tal_client.ReponseCreation(short_guid="Xs0S6bsB8UCSbK1F-HvUOw", brut={"noPublicForm": "Xs0S6bsB8UCSbK1F-HvUOw"})

        async def declencher_transmission(self, short_guid, *, langue=None, identifiant_utilisateur=None, form_pour_simulation=None):
            vus.append(("FRW122", langue, short_guid))
            pdf = tal_client.pdf_simulation(form_pour_simulation or {}, short_guid)
            import base64

            return tal_client.ReponseTransmission(
                no_confirmation=None,
                documents=[tal_client.DocumentTal(nom="Lease of a dwelling.pdf", contenu_base64=base64.b64encode(pdf).decode("ascii"), type_source="genererPDF")],
                messages=[{"mnemonique": "TypeFormulaire", "texte": "53000BAIL"}], brut={},
            )

    async def _cx(db):
        return tal_client.ConnexionTal(mode="reel", cle="cle-factice-123456"), {}

    monkeypatch.setattr(svc, "_fabrique_client", lambda cx: _Faux())
    monkeypatch.setattr(svc, "charger_connexion", _cx)
    r = client.post(f"{BASE}/independants", headers=auth_headers, json={
        "libelle": "Bail en anglais", "locateur": {"nom": "Marc Tremblay", "courriel": "marc@exemple.ca"},
        "locataires": [{"nom": "John Smith", "courriel": "john@exemple.ca"}],
        "adresse": "4521 rue Saint-Denis", "appartement": "9", "ville": "Montréal", "code_postal": "H2J 2L4", "nb_pieces": 3.5,
        "date_debut": "2027-07-01", "date_fin": "2028-06-30", "loyer_mensuel": 1200,
    })
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["langue"] == "fr"
    assert client.post(f"{BASE}/transmissions/{tid}/generer", headers=auth_headers, json={"confirme": True, "langue": "de"}).status_code == 422
    try:
        r = client.post(f"{BASE}/transmissions/{tid}/generer", headers=auth_headers, json={"confirme": True, "langue": "en"})
        assert r.status_code == 200, r.text
        g = r.json()
        assert g["statut"] == "transmise" and g["mode"] == "reel" and g["langue"] == "en"
        assert vus == [("FRW111", "en", "1200.00"), ("FRW122", "en", "Xs0S6bsB8UCSbK1F-HvUOw")]
        det = client.get(f"{BASE}/transmissions/{tid}", headers=auth_headers).json()
        assert det["journal"]["appel"]["langue"] == "en" and det["langue"] == "en"
    finally:
        # Les autres tests comptent les baux réels depuis le début : celui-ci ne reste pas.
        async def _ranger():
            async with TestSessionLocal() as s:
                t = await s.get(TalTransmission, tid)
                if t is not None:
                    await s.delete(t)
                    await s.commit()

        run(_ranger())

