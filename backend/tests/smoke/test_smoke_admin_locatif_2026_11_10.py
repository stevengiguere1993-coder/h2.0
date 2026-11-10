"""Smoke — Admin locative (Phil 2026-11-10) : carnet de contacts, avis de renouvellement
hors système, registre des baux générés et coût mensuel du TAL.

« Appelle cette nouvelle section : Admin locative. Car tu vas y mettre aussi la
possibilité d'envoyer des avis de renouvellement… crée une genre de mini base de
données des contacts dans cette section uniquement… la liste des baux utilisés, par
qui, pour quel immeuble, quand… un résumé par mois de combien ça devrait me coûter
au TAL. »

Verrouille, SANS réseau :
- contacts : création, recherche, modification, retrait ; les personnes d'un bail
  indépendant ou d'un avis entrent seules au carnet (sans doublon) ;
- avis : PDF officiel TAL-806 sans rattachement Kratos, reconduction d'un an par
  défaut, fenêtre légale ; un avis envoyé ne se modifie plus ; l'avis porte la date
  du jour de l'envoi (jamais saisie) ; envoi par la porte unique des courriels ;
- réponse du locataire sur la page publique (accepte / refuse), délai d'un mois
  → réputé accepté ; annuler tue le lien ;
- registre : qui, quand, immeuble ou adresse, mode ; les 10 premiers baux réels à
  0 $, les suivants à 2,99 $ + taxes, par mois.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.admin_locatif import AdmLocAvis
from app.models.immobilier import ImmDocument
from app.models.tal_bail import TalTransmission
from app.services import admin_locatif as adm
from app.services import tal_bail as tal
from tests.smoke.conftest import TestSessionLocal

BASE = "/api/v1/immobilier/admin-locative"
TAL = "/api/v1/immobilier/tal-bail"
IDS: dict = {}


class _Mailer:
    ready = True
    sender = "systeme@immohorizon.com"

    def __init__(self):
        self.sent: list = []

    async def send(self, **kw):
        self.sent.append(kw)


@pytest.fixture()
def faux_mailer():
    import app.integrations.email_graph as eg

    fake = _Mailer()
    ancien = eg.get_mailer
    eg.get_mailer = lambda: fake  # type: ignore[assignment]
    try:
        yield fake
    finally:
        eg.get_mailer = ancien  # type: ignore[assignment]


def test_carnet_de_contacts(client, auth_headers, employee_headers):
    assert client.get(f"{BASE}/contacts", headers=employee_headers).status_code == 403
    assert client.post(f"{BASE}/contacts", headers=auth_headers, json={"telephone": "514-555-0100"}).status_code == 422
    r = client.post(f"{BASE}/contacts", headers=auth_headers, json={
        "nom": "  Marc Tremblay ", "telephone": "514-555-0199", "courriel": "marc@exemple.test",
        "adresse": "12 rue des Érables, Laval", "role": "locateur", "notes": "Ami de Phil",
    })
    assert r.status_code == 201, r.text
    c = r.json()
    IDS["marc"] = c["id"]
    assert c["nom"] == "Marc Tremblay" and c["role"] == "locateur" and c["actif"] is True and c["created_by_email"]
    # Recherche par nom, courriel ou adresse.
    for q in ("tremb", "MARC@", "érables"):
        ids = [x["id"] for x in client.get(f"{BASE}/contacts", headers=auth_headers, params={"q": q}).json()["items"]]
        assert c["id"] in ids, q
    assert client.get(f"{BASE}/contacts", headers=auth_headers, params={"q": "zzz-inconnu"}).json()["total"] == 0
    # Modification, rôle inconnu ignoré, nom vide refusé.
    r = client.patch(f"{BASE}/contacts/{c['id']}", headers=auth_headers, json={"telephone": "438-555-0000", "role": "pirate"})
    assert r.status_code == 200 and r.json()["telephone"] == "438-555-0000" and r.json()["role"] is None
    assert client.patch(f"{BASE}/contacts/{c['id']}", headers=auth_headers, json={"nom": "  "}).status_code == 422
    assert client.patch(f"{BASE}/contacts/999999", headers=auth_headers, json={"nom": "x"}).status_code == 404


def test_un_bail_independant_alimente_le_carnet_sans_doublon(client, auth_headers):
    essentiel = {
        "libelle": "Bail de Marc",
        "locateur": {"nom": "marc tremblay", "telephone": "514-555-0199", "courriel": "marc@exemple.test", "adresse": "99 boul. Neuf, Laval"},
        "locataires": [{"nom": "Julie Roy", "courriel": "julie@exemple.test", "telephone": "438-555-0142"}, {"nom": "Sam Côté"}],
        "cautions": [{"nom": "Paul Roy", "courriel": "paul@exemple.test"}],
        "adresse": "4521 rue Saint-Denis", "ville": "Montréal", "loyer_mensuel": 1450, "date_debut": "2027-07-01", "date_fin": "2028-06-30",
    }
    assert client.post(f"{TAL}/independants", headers=auth_headers, json=essentiel).status_code == 201
    items = client.get(f"{BASE}/contacts", headers=auth_headers).json()["items"]
    par_nom = {x["nom"].lower(): x for x in items}
    # Marc existait : même fiche, coordonnées mises à jour, rôle posé ; pas de doublon.
    assert [x["id"] for x in items if x["nom"].lower() == "marc tremblay"] == [IDS["marc"]]
    assert par_nom["marc tremblay"]["adresse"] == "99 boul. Neuf, Laval" and par_nom["marc tremblay"]["role"] == "locateur"
    assert par_nom["julie roy"]["role"] == "locataire" and par_nom["julie roy"]["courriel"] == "julie@exemple.test"
    assert par_nom["sam côté"]["courriel"] is None and par_nom["paul roy"]["role"] == "caution"
    # Deuxième bail avec les mêmes personnes : toujours une fiche chacune.
    assert client.post(f"{TAL}/independants", headers=auth_headers, json=essentiel).status_code == 201
    noms = [x["nom"].lower() for x in client.get(f"{BASE}/contacts", headers=auth_headers).json()["items"]]
    assert all(noms.count(n) == 1 for n in ("marc tremblay", "julie roy", "sam côté", "paul roy"))
    # Homonyme avec un autre courriel = une autre personne.
    client.post(f"{TAL}/independants", headers=auth_headers, json={**essentiel, "locataires": [{"nom": "Julie Roy", "courriel": "autre.julie@exemple.test"}], "cautions": []})
    julies = [x for x in client.get(f"{BASE}/contacts", headers=auth_headers, params={"q": "julie roy"}).json()["items"]]
    assert sorted(x["courriel"] for x in julies) == ["autre.julie@exemple.test", "julie@exemple.test"]
    # Retiré du carnet : absent par défaut, visible sur demande, réactivé s'il resert.
    assert client.delete(f"{BASE}/contacts/{par_nom['paul roy']['id']}", headers=auth_headers).json()["actif"] is False
    assert "paul roy" not in [x["nom"].lower() for x in client.get(f"{BASE}/contacts", headers=auth_headers).json()["items"]]
    assert "paul roy" in [x["nom"].lower() for x in client.get(f"{BASE}/contacts", headers=auth_headers, params={"inclure_archives": True}).json()["items"]]


AVIS = {
    "libelle": "Renouvellement Julie 2027",
    "locateur_nom": "Marc Tremblay", "locateur_adresse": "12 rue des Érables, Laval (Québec) H7A 1B2", "locateur_telephone": "514-555-0199",
    "locataire_nom": "Julie Roy", "locataire_courriel": "julie@exemple.ca",
    "logement_adresse": "4521 rue Saint-Denis", "logement_numero": "3", "logement_ville": "Montréal",
    "bail_date_debut": "2026-07-01", "bail_date_fin": "2027-06-30", "loyer_actuel": 1450,
    "modif_mode": "nouveau_loyer", "nouveau_loyer": 1495,
}


def test_avis_brouillon_pdf_officiel_et_regles(client, auth_headers, employee_headers, run):
    assert client.post(f"{BASE}/avis", headers=employee_headers, json=AVIS).status_code == 403
    r = client.post(f"{BASE}/avis", headers=auth_headers, json=AVIS)
    assert r.status_code == 201, r.text
    a = r.json()
    IDS["avis"] = a["id"]
    assert a["status"] == "brouillon" and a["avis_envoye_le"] is None and a["document_id"]
    assert a["adresse"] == "4521 rue Saint-Denis, app. 3, Montréal" and a["titre"].startswith("Avis de modification du bail")
    # Reconduction d'un an par défaut : du lendemain de la fin au même jour un an plus tard.
    assert a["nouvelle_date_debut"] == "2027-07-01" and a["nouvelle_date_fin"] == "2028-06-30"
    # Fenêtre légale (bail de 12 mois) : de 6 à 3 mois avant la fin.
    assert a["fenetre"]["du"] == "2026-12-30" and a["fenetre"]["au"] == "2027-03-30" and "6 à 3 mois" in a["fenetre"]["regle"]

    async def _doc():
        async with TestSessionLocal() as s:
            d = await s.get(ImmDocument, a["document_id"])
            blob = (await s.execute(select(ImmDocument.pdf_blob).where(ImmDocument.id == d.id))).scalar_one()
            return d.type, (d.bail_id, d.locataire_id, d.immeuble_id), bytes(blob[:5]), d.signature_token, d.titre

    type_doc, liens, pdf, jeton, titre = run(_doc())
    assert type_doc == "avis_modification" and liens == (None, None, None) and pdf == b"%PDF-" and jeton is None
    assert "4521 rue Saint-Denis" in titre
    # Brouillon : modifiable ; une seule forme de hausse à la fois.
    r = client.patch(f"{BASE}/avis/{a['id']}", headers=auth_headers, json={"modif_mode": "hausse_pct", "hausse_pct": 3.1, "autres_modifications": "Stationnement retiré."})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["modif_mode"] == "hausse_pct" and m["hausse_pct"] == 3.1 and m["nouveau_loyer"] is None and m["document_id"] == a["document_id"]
    # Le locateur et le locataire de l'avis sont au carnet.
    noms = [x["nom"].lower() for x in client.get(f"{BASE}/contacts", headers=auth_headers).json()["items"]]
    assert "marc tremblay" in noms and "julie roy" in noms
    # Bail court et bail à durée indéterminée.
    court = adm.fenetre_legale(AdmLocAvis(bail_date_debut=date(2027, 1, 1), bail_date_fin=date(2027, 6, 30)), aujourd=date(2027, 5, 15))
    assert court["du"] == "2027-04-30" and court["au"] == "2027-05-30" and court["etat"] == "dans"
    indet = adm.fenetre_legale(AdmLocAvis(nouvelle_date_debut=date(2027, 9, 1)), aujourd=date(2027, 5, 1))
    assert indet["du"] == "2027-07-01" and indet["au"] == "2027-08-01" and indet["etat"] == "avant"
    assert adm.fenetre_legale(AdmLocAvis()) is None
    # Le PDF se lit par la route des documents (celle du bouton « PDF » de la page).
    pdf = client.get(f"/api/v1/immobilier/documents/{a['document_id']}/pdf", headers=auth_headers)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    # Courriel invalide : refus clair, rien ne part, l'avis reste un brouillon.
    r = client.post(f"{BASE}/avis/{a['id']}/envoyer", headers=auth_headers, json={"courriel": "pas-un-courriel"})
    assert r.status_code == 422 and "invalide" in r.json()["detail"]
    assert client.get(f"{BASE}/avis/{a['id']}", headers=auth_headers).json()["status"] == "brouillon"
    # Envoi refusé tant qu'il manque l'essentiel.
    vide = client.post(f"{BASE}/avis", headers=auth_headers, json={"locataire_nom": "Sans Courriel"}).json()
    IDS["avis_vide"] = vide["id"]
    assert client.post(f"{BASE}/avis/{vide['id']}/envoyer", headers=auth_headers, json={}).status_code == 422
    # Une forme de hausse choisie sans son montant : refus clair aussi, rien ne part.
    sans_montant = client.post(f"{BASE}/avis", headers=auth_headers, json={
        "locateur_nom": "Marc Tremblay", "locataire_nom": "Luc Petit", "locataire_courriel": "luc@exemple.ca",
        "logement_adresse": "12 rue des Lilas", "modif_mode": "hausse_montant"}).json()
    r = client.post(f"{BASE}/avis/{sans_montant['id']}/envoyer", headers=auth_headers, json={})
    assert r.status_code == 422 and "montant" in r.json()["detail"]
    assert client.post(f"{BASE}/avis/{sans_montant['id']}/annuler", headers=auth_headers).json()["status"] == "annule"


def test_envoi_date_du_jour_et_reponse_du_locataire(client, auth_headers, run, faux_mailer):
    aid = IDS["avis"]
    r = client.post(f"{BASE}/avis/{aid}/envoyer", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    a = r.json()
    jour = adm.aujourd_hui().isoformat()
    # L'avis porte la date du jour de l'envoi ; le délai d'un mois de réponse commence.
    assert a["status"] == "propose" and a["avis_envoye_le"] == jour and a["envoye_a"] == "julie@exemple.ca"
    assert a["echeance_reponse"] == adm._plus_un_mois(adm.aujourd_hui()).isoformat() and a["envoi"]["premier_envoi"] is True
    assert a["document"]["envoye_le"] and a["document"]["signed_at"] is None
    # Parti par la porte unique des courriels : destinataire explicite, lien de réponse, salutation par le prénom.
    assert len(faux_mailer.sent) == 1
    envoi = faux_mailer.sent[0]
    assert envoi["to"] == ["julie@exemple.ca"] and "Avis de modification du bail" in envoi["subject"]
    assert "Bonjour Julie," in envoi["html_body"] and "/sign-document/" in envoi["html_body"]
    # Bail hors système : le courriel dit au nom de qui l'avis part.
    assert "de la part de <strong>Marc Tremblay</strong>" in envoi["html_body"]
    jeton = a["envoi"]["url"].rsplit("/", 1)[-1]
    # Un avis envoyé ne se modifie plus.
    assert client.patch(f"{BASE}/avis/{aid}", headers=auth_headers, json={"nouveau_loyer": 2000}).status_code == 409
    # Renvoi : même document, même date — seul le lien repart.
    r2 = client.post(f"{BASE}/avis/{aid}/envoyer", headers=auth_headers, json={"courriel": "julie.nouveau@exemple.ca"})
    assert r2.status_code == 200 and r2.json()["envoi"]["premier_envoi"] is False and r2.json()["avis_envoye_le"] == jour
    assert r2.json()["envoi"]["url"].endswith(jeton) and faux_mailer.sent[-1]["to"] == ["julie.nouveau@exemple.ca"]

    # Page publique : le locataire voit l'avis, doit choisir, puis accepte en signant.
    vue = client.get(f"/api/v1/public/documents/{jeton}")
    assert vue.status_code == 200, vue.text
    v = vue.json()
    assert v["type"] == "avis_modification" and v["choix_requis"] is True and v["refus_possible"] is True and v["locataire_name"] == "Julie Roy"
    assert client.get(f"/api/v1/public/documents/{jeton}/pdf").status_code == 200
    s = client.post(f"/api/v1/public/documents/{jeton}/signer", json={"name": "Julie Roy", "choix": "accepte"})
    assert s.status_code == 200, s.text
    assert s.json()["choix"] == "accepte" and s.json()["signed_at"] and s.json()["copie_envoyee"] is True
    # La copie signée part à l'adresse où l'avis a été envoyé (pas de fiche locataire à qui la demander).
    assert faux_mailer.sent[-1]["to"] == ["julie.nouveau@exemple.ca"] and faux_mailer.sent[-1].get("attachments")
    det = client.get(f"{BASE}/avis/{aid}", headers=auth_headers).json()
    assert det["status"] == "accepte" and det["reponse_le"] == date.today().isoformat() and det["document"]["signed_by_name"] == "Julie Roy"
    # Répondu : ni renvoi, ni annulation.
    assert client.post(f"{BASE}/avis/{aid}/envoyer", headers=auth_headers, json={}).status_code == 409
    assert client.post(f"{BASE}/avis/{aid}/annuler", headers=auth_headers).status_code == 409


def test_refus_delai_d_un_mois_et_annulation(client, auth_headers, run, faux_mailer):
    # Refus motivé sur la page publique.
    a = client.post(f"{BASE}/avis", headers=auth_headers, json={**AVIS, "libelle": "Refus"}).json()
    env = client.post(f"{BASE}/avis/{a['id']}/envoyer", headers=auth_headers, json={}).json()
    jeton = env["envoi"]["url"].rsplit("/", 1)[-1]
    r = client.post(f"/api/v1/public/documents/{jeton}/refuser", json={"motif": "Hausse trop élevée"})
    assert r.status_code == 200, r.text
    det = client.get(f"{BASE}/avis/{a['id']}", headers=auth_headers).json()
    assert det["status"] == "refuse" and det["refus_motif"] == "Hausse trop élevée"

    # Un mois sans réponse : réputé accepté (art. 1945 C.c.Q.), à la lecture de la liste.
    b = client.post(f"{BASE}/avis", headers=auth_headers, json={**AVIS, "libelle": "Silence"}).json()
    client.post(f"{BASE}/avis/{b['id']}/envoyer", headers=auth_headers, json={})

    async def _vieillir():
        async with TestSessionLocal() as s:
            x = await s.get(AdmLocAvis, b["id"])
            x.avis_envoye_le = adm.aujourd_hui() - timedelta(days=40)
            await s.commit()

    run(_vieillir())
    liste = client.get(f"{BASE}/avis", headers=auth_headers).json()
    silence = next(x for x in liste["items"] if x["id"] == b["id"])
    assert silence["status"] == "repute_accepte" and silence["reponse_le"] == silence["echeance_reponse"]

    # Annuler un avis envoyé : il sort de la liste et son lien cesse de fonctionner.
    c = client.post(f"{BASE}/avis", headers=auth_headers, json={**AVIS, "libelle": "Annulé"}).json()
    env_c = client.post(f"{BASE}/avis/{c['id']}/envoyer", headers=auth_headers, json={}).json()
    jeton_c = env_c["envoi"]["url"].rsplit("/", 1)[-1]
    assert client.get(f"/api/v1/public/documents/{jeton_c}").status_code == 200
    assert client.post(f"{BASE}/avis/{c['id']}/annuler", headers=auth_headers).json()["status"] == "annule"
    assert client.get(f"/api/v1/public/documents/{jeton_c}").status_code == 404
    ids = [x["id"] for x in client.get(f"{BASE}/avis", headers=auth_headers).json()["items"]]
    assert c["id"] not in ids and a["id"] in ids
    assert c["id"] in [x["id"] for x in client.get(f"{BASE}/avis", headers=auth_headers, params={"inclure_annules": True}).json()["items"]]
    assert client.post(f"{BASE}/avis/{c['id']}/envoyer", headers=auth_headers, json={}).status_code == 409


def test_registre_des_baux_et_cout_mensuel_du_tal(client, auth_headers, employee_headers, run):
    assert client.get(f"{BASE}/registre", headers=employee_headers).status_code == 403

    # 12 baux officiels (mode réel) et 2 simulations, posés directement : 11 en mars, 1 en avril.
    async def _seed():
        async with TestSessionLocal() as s:
            await s.execute(TalTransmission.__table__.delete())
            for i in range(12):
                quand = datetime(2031, 3 if i < 11 else 4, 1 + i, 15, 0, tzinfo=timezone.utc)
                s.add(TalTransmission(
                    statut="transmise", mode="reel", independant=(i % 2 == 0), libelle=(f"Essai {i}" if i % 2 == 0 else None),
                    adresse=f"{100 + i} rue du Registre, Montréal", genere_le=quand, cout=2.99,
                    frais_montant=(8.99 if i % 2 else None), created_by_email="phil@test.local", short_guid=f"REG-{i}",
                    payload_json='{"locateurs": [{"nom": "Marc Tremblay"}], "locataires": [{"nom": "Julie Roy"}]}',
                ))
            for i in range(2):
                s.add(TalTransmission(statut="transmise", mode="simulation", independant=True, adresse="Simulation",
                                      genere_le=datetime(2031, 3, 20 + i, 15, 0, tzinfo=timezone.utc), cout=0, payload_json="{}"))
            s.add(TalTransmission(statut="brouillon", mode="simulation", independant=True, payload_json="{}"))   # pas généré : hors registre
            await s.commit()

    async def _ranger():
        # Les autres tests du bail officiel comptent les baux réels depuis le début :
        # ce test ne laisse rien derrière lui.
        async with TestSessionLocal() as s:
            await s.execute(TalTransmission.__table__.delete())
            await s.commit()

    run(_seed())
    try:
        _verifier_registre(client, auth_headers, run)
    finally:
        run(_ranger())


def _verifier_registre(client, auth_headers, run):
    r = client.get(f"{BASE}/registre", headers=auth_headers, params={"annee": 2031})
    assert r.status_code == 200, r.text
    reg = r.json()
    assert reg["annee"] == 2031 and 2031 in reg["annees"] and len(reg["mois"]) == 12 and len(reg["items"]) == 14
    mars = next(m for m in reg["mois"] if m["mois"] == "2031-03")
    avril = next(m for m in reg["mois"] if m["mois"] == "2031-04")
    # Les 10 premiers baux réels sont gratuits ; le 11e (mars) et le 12e (avril) sont facturés 2,99 $ + taxes.
    assert mars["nb_reel"] == 11 and mars["nb_gratuits"] == 10 and mars["nb_factures"] == 1 and mars["nb_simulation"] == 2
    assert mars["redevances"] == 2.99 and mars["tps"] == 0.15 and mars["tvq"] == 0.3 and mars["total"] == 3.44
    assert avril["nb_reel"] == 1 and avril["nb_gratuits"] == 0 and avril["nb_factures"] == 1 and avril["total"] == 3.44
    assert reg["totaux"]["nb_reel"] == 12 and reg["totaux"]["nb_factures"] == 2 and reg["totaux"]["redevances"] == 5.98
    assert reg["totaux"]["total"] == 6.88 and reg["totaux"]["frais_refactures"] == round(8.99 * 6, 2)
    assert reg["gratuits_utilises"] == 10 and reg["gratuits_restants"] == 0 and reg["total_reel_depuis_le_debut"] == 12
    assert reg["cout_unitaire"] == 2.99 and reg["forfait_licence"] == 300.0 and reg["tps_pct"] == 5.0 and reg["tvq_pct"] == 9.975
    # Qui, quoi, quand : le plus récent d'abord.
    premier = reg["items"][0]
    assert premier["mois"] == "2031-04" and premier["gratuit"] is False and premier["cout_tal"] == 2.99 and premier["rang_reel"] == 12
    assert premier["par"] == "phil@test.local" and premier["locataire_nom"] == "Julie Roy" and premier["locateur_nom"] == "Marc Tremblay"
    assert premier["adresse"].endswith("rue du Registre, Montréal")
    gratuits = [x for x in reg["items"] if x["gratuit"]]
    assert len(gratuits) == 10 and all(x["cout_tal"] == 0 for x in gratuits)
    simul = [x for x in reg["items"] if x["mode"] == "simulation"]
    assert len(simul) == 2 and all(x["cout_tal"] == 0 and x["rang_reel"] is None for x in simul)
    # Une autre année : rien, mais les compteurs globaux restent.
    autre = client.get(f"{BASE}/registre", headers=auth_headers, params={"annee": 2030}).json()
    assert autre["items"] == [] and autre["totaux"]["total"] == 0 and autre["gratuits_restants"] == 0
    # Le compteur du service TAL compte les mêmes baux réels.
    cpt = run(_compteur())
    assert cpt["total_reel_depuis_le_debut"] == 12


def _compteur():
    async def _go():
        async with TestSessionLocal() as s:
            return await tal.compteur(s, "2031-03")

    return _go()
