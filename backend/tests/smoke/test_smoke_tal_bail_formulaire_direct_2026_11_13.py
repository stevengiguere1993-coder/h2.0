"""Smoke — bail indépendant : le nouveau bail s'ouvre directement sur le formulaire (Phil 2026-11-13).

« La page nouveau bail indépendant sert un peu à rien, dans la page 1 formulaire on retrouve
toutes les mêmes affaires, devrions-nous pas arriver direct sur la page 1 formulaire ? »
« Même si c'est des baux indépendants, je pourrais venir sélectionner un de nos immeubles,
ça rajoute les infos automatiquement (compagnie détentrice, adresse). Ça reste complètement
indépendant du reste de la gestion locative. »
« Lors du bail 2, la rue ne s'est pas importée. »

Verrouille, sans aucun appel réseau :
- le formulaire d'un nouveau bail se lit sans rien écrire en base ;
- le brouillon naît du formulaire complet (POST /independants avec ``form``) ;
- les personnes du formulaire entrent au carnet, et le carnet revient prêt à remplir une
  personne (adresse déjà découpée) ;
- un de nos immeubles remplit le locateur et l'adresse, sans garder aucun lien ;
- une adresse avec un numéro civique mais sans rue est signalée avant l'envoi.
"""
from __future__ import annotations

from sqlalchemy import func, select

from app.models.entreprise import Entreprise
from app.models.immobilier import Immeuble, Logement
from app.models.tal_bail import TalTransmission
from app.services import tal_bail as svc
from tests.smoke.conftest import TestSessionLocal

BASE = "/api/v1/immobilier/tal-bail"
IDS: dict = {}


def _nb_transmissions(run) -> int:
    async def _n():
        async with TestSessionLocal() as s:
            return (await s.execute(select(func.count(TalTransmission.id)))).scalar_one()

    return run(_n())


def test_formulaire_d_un_nouveau_bail_sans_rien_ecrire(client, auth_headers, employee_headers, run):
    avant = _nb_transmissions(run)
    assert client.get(f"{BASE}/independants/nouveau", headers=employee_headers).status_code == 403
    r = client.get(f"{BASE}/independants/nouveau", headers=auth_headers)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["transmissions"] == [] and p["contexte"]["independant"] is True and p["mode"] == "simulation"
    assert isinstance(p["carnet"], list) and p["regles"] and "coutLoyer" in p["requis"]
    f = p["form"]
    # Formulaire complet, réglages par défaut posés, rien d'inventé sur les personnes.
    assert f["locateurs"][0]["nom"] == "" and f["locataires"][0]["nom"] == "" and "adresseLogement" in f
    assert f["modePaiement"] == "virementBancaire" and p["rapport"]["valide"] is False
    assert _nb_transmissions(run) == avant, "lire le formulaire ne crée pas de brouillon"
    IDS["form"] = f


def test_brouillon_cree_depuis_le_formulaire_complet(client, auth_headers, run):
    f = IDS["form"]
    f["locateurs"][0].update({"nom": "Marc Tremblay", "courrielLocateur": "marc.tremblay@exemple.ca", "noTelephone": "514-555-0199",
                              "questionRepresentant": "false"})
    f["locateurs"][0]["adresse"][0].update({"NoCivique": "1707", "Rue": "", "Municipalite": "Montréal", "Province": "Québec", "CodePostal": "J5M 1A7"})
    f["locataires"][0].update({"nom": "Julie Roy", "courrielLocataire": "julie.roy@exemple.ca"})
    f["adresseLogement"][0].update({"NoCivique": "777", "Rue": "rue Tango", "Appartement": "7", "Municipalite": "Montréal", "CodePostal": "J5M 1A7"})
    f.update({"nbPieces": "quatre-demi", "typeBail": "dureeFixe", "nbSemainesMoisAnnees": "12", "dateDebutBail": "2026-12-01", "dateFinBail": "",
              "coutLoyer": "1850", "coutTotalLoyer": "", "frequenceCoutLoyer": "mois", "typeChauffageLogement": ["electricite"],
              "situationApplicableAvisNouveauLocataire": "aucunLoyer"})
    r = client.post(f"{BASE}/independants", headers=auth_headers, json={"form": f})
    assert r.status_code == 201, r.text
    t = r.json()
    IDS["tid"] = t["id"]
    assert t["independant"] is True and t["statut"] == "brouillon" and t["bail_id"] is None and t["immeuble_id"] is None
    assert t["adresse"] == "777 rue Tango, app. 7, Montréal"
    g = t["form"]
    # Le formulaire fourni est gardé, complété de ce qui se calcule seul.
    assert g["locataires"][0]["nom"] == "Julie Roy" and g["nbSemainesMoisAnnees"] == "12 mois"
    assert g["dateFinBail"] == "2027-11-30" and g["coutTotalLoyer"] == "1850.00"
    # Le numéro civique sans rue du locateur (bail 2 de Steven) est signalé avant l'envoi.
    assert t["rapport"]["valide"] is True
    assert any("locateur 1" in a and "sans nom de rue" in a for a in t["rapport"]["avertissements"])
    assert not any("logement" in a and "sans nom de rue" in a for a in t["rapport"]["avertissements"])
    # Un formulaire vide est refusé.
    assert client.post(f"{BASE}/independants", headers=auth_headers, json={"form": {}}).status_code == 422

    # Les personnes sont au carnet, prêtes à remplir un prochain bail (adresse découpée).
    p = client.get(f"{BASE}/preparer", headers=auth_headers, params={"transmission_id": t["id"]}).json()
    carnet = {c["nom"]: c for c in p["carnet"]}
    assert {"Marc Tremblay", "Julie Roy"} <= set(carnet)
    marc = carnet["Marc Tremblay"]
    assert marc["role"] == "locateur" and marc["courriel"] == "marc.tremblay@exemple.ca"
    assert marc["adresse"]["NoCivique"] == "1707" and marc["adresse"]["Municipalite"] == "Montréal" and marc["adresse"]["CodePostal"] == "J5M 1A7"
    assert carnet["Julie Roy"]["adresse"] is None      # aucune adresse saisie : rien à découper

    # Une correction dans le formulaire suit au carnet.
    g["locataires"][0]["noTelephone"] = "438-555-0142"
    r = client.patch(f"{BASE}/transmissions/{t['id']}", headers=auth_headers, json={"form": g})
    assert r.status_code == 200, r.text
    p = client.get(f"{BASE}/independants/nouveau", headers=auth_headers).json()
    assert next(c for c in p["carnet"] if c["nom"] == "Julie Roy")["telephone"] == "438-555-0142"


def test_personnes_du_formulaire_pour_le_carnet():
    form = {
        "locateurs": [{"nom": "Gestion ABC inc.", "courrielLocateur": "info@abc.ca", "noTelephone": "514-555-0100",
                       "adresse": [{"NoCivique": "12", "Rue": "rue des Érables", "Appartement": "", "Municipalite": "Laval",
                                    "Province": "Québec", "CodePostal": "H7A 1B2"}]}],
        "locataires": [{"nom": "Julie Roy", "courrielLocataire": "julie@exemple.ca"}, {"nom": ""}],
        "possedeAutresSignataires": "false", "autresSignataires": [{"nom": "Paul Roy", "courriel": "paul@exemple.ca"}],
    }
    gens = svc.personnes_pour_carnet(form)
    assert [(p["nom"], p["role"]) for p in gens] == [("Gestion ABC inc.", "locateur"), ("Julie Roy", "locataire")]
    assert gens[0]["adresse"] == "12 rue des Érables, Laval (Québec) H7A 1B2" and gens[0]["telephone"] == "514-555-0100"
    form["possedeAutresSignataires"] = "true"
    assert [p["role"] for p in svc.personnes_pour_carnet(form)] == ["locateur", "locataire", "caution"]
    assert svc.personnes_pour_carnet(None) == []


def test_un_de_nos_immeubles_remplit_le_locateur_et_l_adresse(client, auth_headers, employee_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            ent = Entreprise(name="Groupe 8900 Saint-Hubert inc.")
            ent.siege_social = "100 rue du Siège, Montréal (Québec) H2X 1Y4"
            ent.contact_email = "compta@groupe8900.ca"
            s.add(ent)
            await s.flush()
            imm = Immeuble(name="8900 Saint-Hubert", address="8900 rue Saint-Hubert", city="Montréal", postal_code="H2M 1Y7",
                           is_active=True, owner_entreprise_id=ent.id)
            s.add(imm)
            await s.flush()
            lg = Logement(immeuble_id=imm.id, numero="3")
            lg.nb_pieces_decimal = 4.5
            s.add(lg)
            autre = Immeuble(name="Autre immeuble", address="1 rue Ailleurs", is_active=True)
            s.add(autre)
            await s.flush()
            lg_autre = Logement(immeuble_id=autre.id, numero="9")
            s.add(lg_autre)
            await s.commit()
            return imm.id, lg.id, lg_autre.id

    imm_id, lg_id, lg_autre_id = run(_seed())
    avant = _nb_transmissions(run)
    url = f"{BASE}/prefill/immeuble/{imm_id}"
    assert client.get(url, headers=employee_headers).status_code == 403
    assert client.get(f"{BASE}/prefill/immeuble/999999", headers=auth_headers).status_code == 404

    d = client.get(url, headers=auth_headers).json()
    assert d["locateur"] == "Groupe 8900 Saint-Hubert inc." and d["immeuble"]["adresse"] == "8900 rue Saint-Hubert, Montréal, H2M 1Y7"
    assert [x["numero"] for x in d["logements"]] == ["3"]
    v = d["valeurs"]
    assert set(v) == {"locateurs", "adresseLogement"}, "sans logement choisi, le nombre de pièces n'est pas touché"
    loc = v["locateurs"][0]
    assert loc["nom"] == "Groupe 8900 Saint-Hubert inc." and loc["courrielLocateur"] == "compta@groupe8900.ca"
    assert (loc["adresse"][0]["NoCivique"], loc["adresse"][0]["Rue"], loc["adresse"][0]["CodePostal"]) == ("100", "rue du Siège", "H2X 1Y4")
    a = v["adresseLogement"][0]
    assert (a["NoCivique"], a["Rue"], a["Appartement"], a["Municipalite"], a["CodePostal"]) == ("8900", "rue Saint-Hubert", "", "Montréal", "H2M 1Y7")

    # Avec le logement : numéro d'appartement et nombre de pièces.
    d = client.get(url, headers=auth_headers, params={"logement_id": lg_id}).json()
    assert d["valeurs"]["adresseLogement"][0]["Appartement"] == "3" and d["valeurs"]["nbPieces"] == "quatre-demi"
    # Le logement d'un autre immeuble est refusé.
    assert client.get(url, headers=auth_headers, params={"logement_id": lg_autre_id}).status_code == 404
    # Rien n'est créé ni lié : le bail reste indépendant de la gestion locative.
    assert _nb_transmissions(run) == avant
