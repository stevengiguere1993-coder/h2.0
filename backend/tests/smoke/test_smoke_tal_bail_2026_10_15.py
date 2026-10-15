"""Smoke — bail de logement OFFICIEL par l'API du TAL (53000BAIL, Phil 2026-10-15).

Verrouille, SANS aucun appel réseau (mode simulation ou client factice) :
- le schéma embarqué se charge (409 champs, 407 uniques, 2 doublons du
  TAL), le formulaire vide a la forme du gabarit ;
- le validateur local refuse ce qui coûterait 2,99 $ pour rien : champ
  inconnu, clé hors domaine, trop d'occurrences, dates incohérentes,
  champ requis vide ;
- le mapping Kratos → TAL : locateur (entreprise propriétaire +
  représentant), locataire, caution, adresse découpée, nb de pièces,
  durée, loyer, échéance, responsabilités, section G depuis le bail
  précédent ; blocs de signature laissés vides ;
- le flux complet en simulation : brouillon → confirmation obligatoire →
  transmise, PDF archivé (imm_documents « bail_tal », jamais posé comme
  bail signé), 0 $, pas de frais ; double génération refusée ; un bail =
  un formulaire payé sauf remplacement explicite ;
- l'échec au FRW122 garde le ShortGuid et la relance ne refait JAMAIS le
  FRW111 ; en mode réel : coût 2,99 $ + frais 8,99 $ au propriétaire ;
- Paramètres : la clé API est chiffrée, jamais renvoyée, jamais dans
  l'audit ; refus sans coffre ; employé → 403 ;
- versions de schéma : téléversement + diff + activation ;
- cliquet IA : tables couvertes, liste MCP « tal_transmissions ».
"""
from __future__ import annotations

import base64
import copy
import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.integrations.tal import client as tal_client
from app.integrations.tal.schema import charger_schema_asset, squelette
from app.integrations.tal.validateur import valider
from app.models.entreprise import Entreprise
from app.models.immobilier import (
    Bail,
    BailStatus,
    FraisManuelGestion,
    ImmDocument,
    ImmLocataireContact,
    Immeuble,
    Locataire,
    LocationDossier,
    LocationDossierStatut,
    Logement,
    LogementStatus,
    PaiementLoyer,
)
from app.services import tal_bail as svc
from tests.smoke.conftest import TestSessionLocal

BASE = "/api/v1/immobilier/tal-bail"
IDS: dict = {}


# ─── Unités ─────────────────────────────────────────────────────────────


def test_schema_embarque_et_squelette():
    s = charger_schema_asset()
    assert s.type_formulaire == "53000BAIL"
    assert len(s.champs) == 409 and len(s.index) == 407
    assert sorted(f"{g}.{n}" for g, n in s.doublons) == [
        "locateurs.courrielLocateur", "locateurs.courrielRepresentant",
    ]
    assert {"locataires", "locateurs", "adresseLogement", "autresSignataires"} <= set(s.groupes())
    assert "trois-demi" in s.champ("nbPieces").cles_valeurs
    assert s.champ("responsabiliteChauffage").cles_valeurs == ["locateur", "locataire"]
    assert s.champ("responsabiliteGaz", "responsabiliteServicesTaxesCoutsConsommation").cles_valeurs == ["locateur", "locataire", "na"]
    f = squelette(s)
    assert isinstance(f["locataires"], list) and isinstance(f["locataires"][0]["adresse"], list)
    assert f["engagementAvertisseursFumeeLocateur"] is False
    assert f["dependancesIncluses"] == []
    assert f["nbPieces"] == "" and f["signatureLocataire1"][0]["EstSigne"] == ""
    r = valider(f, s)
    assert r.valide and r.nb_remplis == 0 and len(r.champs_vides) > 300


def test_validateur_refuse_ce_qui_couterait_cher():
    s = charger_schema_asset()
    f = squelette(s)
    f["nbPieces"] = "3.5"                       # libellé/valeur au lieu de la clé
    f["champInconnu"] = "x"
    f["locataires"] = [squelette(s)["locataires"][0] for _ in range(5)]
    f["typeBail"] = "dureeFixe"
    f["dateDebutBail"] = "2026-07-01"
    f["dateFinBail"] = "2026-06-30"
    f["typeChauffageLogement"] = ["electricite", "bois"]
    f["engagementAvertisseursFumeeLocateur"] = "oui"
    f["coutLoyer"] = "mille"
    f["locataires"][0]["noTelephone"] = "123"
    f["adresseLogement"][0]["CodePostal"] = "12345"
    r = valider(f, s, requis=["locateurs[0].nom"])
    txt = "\n".join(r.erreurs)
    assert not r.valide
    assert "nbPieces" in txt and "champInconnu" in txt
    assert "locataires : 5 occurrences, maximum 4" in txt
    assert "dateFinBail doit être après dateDebutBail" in txt
    assert "« bois »" in txt and "engagementAvertisseursFumeeLocateur" in txt
    assert "coutLoyer : nombre attendu" in txt
    assert "noTelephone" in txt and "CodePostal" in txt
    assert "locateurs[0].nom : champ requis" in txt
    assert "champInconnu" in r.champs_inconnus


def test_outils_de_mapping():
    a = svc.decouper_adresse("8900 rue Saint-Hubert app. 3, Montréal (Québec) H2M 1Y7")
    assert a == {
        "NoCivique": "8900", "Appartement": "3", "CodePostal": "H2M 1Y7", "Province": "Québec",
        "Municipalite": "Montréal", "Rue": "rue Saint-Hubert",
        "AdresseComplete": "8900 rue Saint-Hubert, app. 3, Montréal (Québec) H2M 1Y7",
    }
    b = svc.decouper_adresse("2420 boulevard Pie-IX", ville="Montréal", code_postal="h1v2e3", appartement="101")
    assert b["CodePostal"] == "H1V 2E3" and b["Appartement"] == "101" and b["Rue"] == "boulevard Pie-IX"
    assert svc.decouper_adresse("")["AdresseComplete"] == "" and svc.decouper_adresse("")["Province"] == ""
    assert svc.cle_nb_pieces(3.5) == ("trois-demi", "")
    assert svc.cle_nb_pieces(4) == ("quatre", "")
    assert svc.cle_nb_pieces(8) == ("autre", "8")
    assert svc.cle_nb_pieces(None) == ("", "")
    assert svc._duree_texte(date(2026, 7, 1), date(2027, 6, 30)) == "1 an"
    assert svc._duree_texte(date(2026, 11, 1), date(2027, 6, 30)) == "8 mois"
    assert svc._duree_texte(date(2026, 7, 1), date(2026, 7, 14)) == "2 semaines"
    assert svc._telephone("(514) 555-0101") == "514-555-0101"
    assert svc._telephone("1 514 555 0101") == "514-555-0101"
    assert svc._telephone("055-685-6750") == ""
    assert svc._montant(1150) == "1150" and svc._montant(1150.5) == "1150.50"


# ─── Données de test ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def tal_seed(run, seeded_users) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            ent = Entreprise(
                name="Horizon Immo Smoke INC", type="immobilier",
                contact_email="info@horizon-smoke.ca", contact_telephone="514 555 0101",
                siege_social="158 rue Maurice, Saint-Rémi (Québec) J0L 2L0",
            )
            s.add(ent)
            await s.flush()
            imm = Immeuble(
                name="Immeuble Smoke TAL Bail", address="8900 rue Saint-Hubert",
                city="Montréal", postal_code="H2M 1Y7", annee_construction=1960,
                owner_entreprise_id=ent.id, is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(immeuble_id=imm.id, numero="3", nb_pieces_decimal=3.5, status=LogementStatus.VACANT.value)
            lg2 = Logement(immeuble_id=imm.id, numero="4", nb_pieces_decimal=4.5, status=LogementStatus.VACANT.value)
            ancien = Locataire(full_name="Ancien Locataire", email="ancien@test.ca")
            alice = Locataire(
                full_name="Alice Test", email="alice@test.ca", phone="438-555-0202",
                ancienne_adresse="12 rue Ancienne app 4, Laval (Québec) H7N 1A1",
            )
            carl = Locataire(full_name="Carl Reel", email="carl@test.ca", phone="514-555-0303")
            s.add_all([lg, lg2, ancien, alice, carl])
            await s.flush()
            s.add(ImmLocataireContact(locataire_id=alice.id, role="garant", full_name="Bob Caution", email="bob@test.ca", phone="514-555-0404"))
            prec = Bail(
                logement_id=lg.id, locataire_id=ancien.id, date_debut=date(2025, 7, 1), date_fin=date(2026, 6, 30),
                loyer_mensuel=1000.0, status=BailStatus.TERMINE.value,
            )
            s.add(prec)
            await s.flush()
            s.add(PaiementLoyer(
                bail_id=prec.id, mois_couvert=date(2026, 6, 1), montant=1000.0, paye_le=date(2026, 6, 2),
                created_at=datetime.now(timezone.utc),
            ))
            bail = Bail(
                logement_id=lg.id, locataire_id=alice.id, date_debut=date(2026, 11, 1), date_fin=date(2027, 6, 30),
                loyer_mensuel=1150.0, status=BailStatus.PROPOSE.value, jour_echeance=1,
                chauffage_inclus=False, eau_chaude_inclus=True, electricite_inclus=False, internet_inclus=True,
            )
            bail2 = Bail(
                logement_id=lg2.id, locataire_id=carl.id, date_debut=date(2026, 12, 1), date_fin=date(2027, 11, 30),
                loyer_mensuel=1400.0, status=BailStatus.PROPOSE.value, jour_echeance=15, chauffage_inclus=True,
            )
            s.add_all([bail, bail2])
            await s.flush()
            d = LocationDossier(logement_id=lg.id, statut=LocationDossierStatut.BAIL_ENVOYE.value, nouveau_bail_id=bail.id)
            s.add(d)
            await s.flush()
            await s.commit()
            return {
                "ent_id": ent.id, "imm_id": imm.id, "lg_id": lg.id, "lg2_id": lg2.id,
                "alice_id": alice.id, "carl_id": carl.id, "bail_id": bail.id, "bail2_id": bail2.id,
                "prec_id": prec.id, "dossier_id": d.id,
            }

    return run(_seed())


# ─── Préparation (mapping) ──────────────────────────────────────────────


def test_preparer_remplit_depuis_kratos(client, auth_headers, tal_seed):
    r = client.get(f"{BASE}/preparer", headers=auth_headers, params={"bail_id": tal_seed["bail_id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    f = body["form"]
    # Locateur = entreprise propriétaire, représentée par la personne connectée.
    loc = f["locateurs"][0]
    assert loc["nom"] == "Horizon Immo Smoke INC"
    assert loc["noTelephone"] == "514-555-0101"
    assert loc["courrielLocateur"] == "info@horizon-smoke.ca"
    assert loc["questionRepresentant"] == "true" and loc["representant"]
    assert loc["adresse"][0]["Municipalite"] == "Saint-Rémi" and loc["adresse"][0]["CodePostal"] == "J0L 2L0"
    # Locataire + caution.
    assert len(f["locataires"]) == 1
    lt = f["locataires"][0]
    assert lt["nom"] == "Alice Test" and lt["courrielLocataire"] == "alice@test.ca"
    assert lt["noTelephone"] == "438-555-0202"
    assert lt["adresse"][0]["Municipalite"] == "Laval" and lt["adresse"][0]["Appartement"] == "4"
    assert f["possedeAutresSignataires"] == "true"
    assert f["autresSignataires"][0]["nom"] == "Bob Caution" and f["autresSignataires"][0]["qualite"] == "Caution"
    assert f["estLocatairesEngagementSolidaire"] == ""   # un seul locataire : laissé vide
    # Logement.
    adr = f["adresseLogement"][0]
    assert adr["NoCivique"] == "8900" and adr["Rue"] == "rue Saint-Hubert" and adr["Appartement"] == "3"
    assert adr["Municipalite"] == "Montréal" and adr["CodePostal"] == "H2M 1Y7"
    assert f["nbPieces"] == "trois-demi" and f["nbPiecesAutre"] == ""
    # Durée, loyer, échéance.
    assert f["typeBail"] == "dureeFixe" and f["dateDebutBail"] == "2026-11-01" and f["dateFinBail"] == "2027-06-30"
    assert f["nbSemainesMoisAnnees"] == "8 mois"
    assert f["coutLoyer"] == "1150" and f["coutTotalLoyer"] == "1150" and f["frequenceCoutLoyer"] == "mois"
    assert f["termesPaiement"] == "permierJourMois" and f["premierTermePaiement"] == "2026-11-01"
    assert f["modePaiement"] == "virementBancaire"
    # Responsabilités depuis les inclusions du bail.
    assert f["responsabiliteChauffage"] == "locataire"
    resp = f["responsabiliteServicesTaxesCoutsConsommation"][0]
    assert resp["responsabiliteElectricite"] == "locataire" and resp["responsabiliteEauChaude"] == "locateur"
    assert resp["responsabiliteChauffeEau"] == "locateur" and resp["responsabiliteGaz"] == "na"
    assert f["possedeAutresServicesConditionsRestriction"] == "true"
    assert "Internet" in f["precisionAutresServicesConditionsRestriction"]
    assert f["situationApplicableRestrictionsFixationLoyer"] == "aucun"   # immeuble de 1960
    # Section G depuis le bail précédent (1 000 $, dernier paiement 2026-06-02).
    assert f["situationApplicableAvisNouveauLocataire"] == "loyer"
    assert f["montantLoyerBailPrecedent"] == "1000" and f["montantDernierLoyerPaye"] == "1000"
    assert f["montantLoyerPlusBasPaye12Mois"] == "1000" and f["dateDernierPaiementLoyer"] == "2026-06-02"
    assert f["confirmationTransmissionAvisNouveauLocataire"] is True
    # Engagements : locateur coché, locataire laissé pour la signature ; blocs vides.
    assert f["engagementAvertisseursFumeeLocateur"] is True
    assert f["locataire1engagementAvertisseursFumeeLocataire"] is False
    assert f["signatureLocataire1"][0]["NomComplet"] == "" and f["signatureLocateurPrincipal"][0]["EstSigne"] == ""
    assert f["motPasseWF"] == ""
    # Origines et liste à vérifier.
    assert body["origine"]["coutLoyer"] == "donnees" and body["origine"]["modePaiement"] == "defaut"
    assert body["origine"]["locataire1engagementAvertisseursFumeeLocataire"] == "signature"
    chemins = {x["chemin"] for x in body["a_verifier"]}
    assert {"modePaiement", "motPasseWF", "responsabiliteServicesTaxesCoutsConsommation[0]"} <= chemins
    assert body["rapport"]["valide"] is True, body["rapport"]
    assert body["contexte"]["locateur"] == "Horizon Immo Smoke INC" and body["contexte"]["garants"] == ["Bob Caution"]
    assert body["mode"] == "simulation" and body["cout_tal"] == 2.99 and body["transmissions"] == []


def test_preparer_bail_au_15_et_chauffage_inclus(client, auth_headers, tal_seed):
    r = client.get(f"{BASE}/preparer", headers=auth_headers, params={"bail_id": tal_seed["bail2_id"]})
    assert r.status_code == 200, r.text
    f = r.json()["form"]
    assert f["termesPaiement"] == "autre" and f["precisionAutresTermes"] == "Le 15 de chaque mois"
    assert f["responsabiliteChauffage"] == "locateur"
    assert f["nbPieces"] == "quatre-demi" and f["nbSemainesMoisAnnees"] == "1 an"
    assert f["situationApplicableAvisNouveauLocataire"] == "aucunLoyer"   # jamais loué
    assert f["possedeAutresSignataires"] == "false"
    assert r.json()["rapport"]["valide"] is True
    assert client.get(f"{BASE}/preparer", headers=auth_headers, params={"bail_id": 999_999}).status_code == 404


# ─── Flux complet en simulation ─────────────────────────────────────────


def test_flux_simulation_complet(client, auth_headers, tal_seed, run):
    r = client.post(f"{BASE}/transmissions", headers=auth_headers, json={
        "bail_id": tal_seed["bail_id"], "dossier_id": tal_seed["dossier_id"],
        "surcharges": {"lieuPaiement": "Virement Interac", "dependancesIncluses": ["RemiseOuEspaceRangement"]},
    })
    assert r.status_code == 201, r.text
    t = r.json()
    IDS["t1"] = t["id"]
    assert t["statut"] == "brouillon" and t["bail_id"] == tal_seed["bail_id"]
    assert t["identifiant_utilisateur"] == f"kratos-b{tal_seed['bail_id']}-t{t['id']}"
    assert t["form"]["lieuPaiement"] == "Virement Interac" and t["form"]["dependancesIncluses"] == ["RemiseOuEspaceRangement"]
    assert t["rapport"]["valide"] is True and t["adresse"].startswith("8900 rue Saint-Hubert")

    # Un 2e brouillon pour le même bail REUTILISE le premier (pas de pile).
    r2 = client.post(f"{BASE}/transmissions", headers=auth_headers, json={"bail_id": tal_seed["bail_id"]})
    assert r2.status_code == 201 and r2.json()["id"] == t["id"]

    # Modifier le formulaire d'un brouillon : accepté, revalidé.
    form = t["form"]
    form["lieuPaiement"] = "Au bureau"
    r = client.patch(f"{BASE}/transmissions/{t['id']}", headers=auth_headers, json={"form": form})
    assert r.status_code == 200 and r.json()["form"]["lieuPaiement"] == "Au bureau"
    mauvais = copy.deepcopy(form)
    mauvais["nbPieces"] = "3½"
    r = client.patch(f"{BASE}/transmissions/{t['id']}", headers=auth_headers, json={"form": mauvais})
    assert r.status_code == 200 and r.json()["rapport"]["valide"] is False
    # Générer avec un formulaire invalide : rien ne part.
    r = client.post(f"{BASE}/transmissions/{t['id']}/generer", headers=auth_headers, json={"confirme": True})
    assert r.status_code == 422 and "validation locale" in json.dumps(r.json(), ensure_ascii=False)
    client.patch(f"{BASE}/transmissions/{t['id']}", headers=auth_headers, json={"form": form})

    # Confirmation obligatoire.
    r = client.post(f"{BASE}/transmissions/{t['id']}/generer", headers=auth_headers, json={})
    assert r.status_code == 422 and "2,99" in r.json()["detail"]

    r = client.post(f"{BASE}/transmissions/{t['id']}/generer", headers=auth_headers, json={"confirme": True})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["statut"] == "transmise" and g["mode"] == "simulation"
    assert g["short_guid"].startswith("SIM-") and g["no_confirmation"].startswith("SIM-CONF-")
    assert g["document_id"] and g["cout"] == 0.0 and g["frais_manuel_id"] is None
    assert g["messages"][0]["mnemonique"] == "SIMULATION"
    assert g["documents"][0]["type_source"] == "simulation" and g["documents"][0]["taille"] > 500
    assert g["genere_le"] and g["tentatives"] == 1

    async def _verif():
        async with TestSessionLocal() as s:
            doc = await s.get(ImmDocument, g["document_id"])
            bail = await s.get(Bail, tal_seed["bail_id"])
            dossier = await s.get(LocationDossier, tal_seed["dossier_id"])
            blob = (await s.execute(select(ImmDocument.pdf_blob).where(ImmDocument.id == doc.id))).scalar_one()
            return {
                "type": doc.type, "titre": doc.titre, "bail_id": doc.bail_id, "logement_id": doc.logement_id,
                "pdf": bytes(blob[:5]) if blob else None, "params": json.loads(doc.params_json),
                "bail_document_id": bail.document_id, "bail_status": bail.status, "dossier_statut": dossier.statut,
            }

    v = run(_verif())
    assert v["type"] == "bail_tal" and v["pdf"] == b"%PDF-" and v["bail_id"] == tal_seed["bail_id"]
    assert v["logement_id"] == tal_seed["lg_id"] and "Bail de logement (TAL)" in v["titre"]
    assert v["params"]["short_guid"] == g["short_guid"] and v["params"]["simulation"] is True
    # Le PDF du TAL n'est PAS signé : il ne devient pas « le bail signé »,
    # le bail reste proposé et la carte reste « Bail en signature ».
    assert v["bail_document_id"] is None and v["bail_status"] == "propose"
    assert v["dossier_statut"] == LocationDossierStatut.BAIL_ENVOYE.value

    # Plus de modification ni de seconde génération.
    assert client.patch(f"{BASE}/transmissions/{t['id']}", headers=auth_headers, json={"form": form}).status_code == 409
    r = client.post(f"{BASE}/transmissions/{t['id']}/generer", headers=auth_headers, json={"confirme": True})
    assert r.status_code == 409
    assert client.post(f"{BASE}/transmissions/{t['id']}/annuler", headers=auth_headers).status_code == 409

    # Un bail = un formulaire payé : refus sans « remplacer ».
    r = client.post(f"{BASE}/transmissions", headers=auth_headers, json={"bail_id": tal_seed["bail_id"]})
    assert r.status_code == 409 and r.json()["detail"]["details"]["transmission_id"] == t["id"]
    r = client.post(f"{BASE}/transmissions", headers=auth_headers, json={"bail_id": tal_seed["bail_id"], "remplacer": True})
    assert r.status_code == 201 and r.json()["id"] != t["id"] and r.json()["statut"] == "brouillon"
    IDS["t1bis"] = r.json()["id"]
    assert client.post(f"{BASE}/transmissions/{IDS['t1bis']}/annuler", headers=auth_headers).json()["statut"] == "annulee"

    r = client.get(f"{BASE}/transmissions", headers=auth_headers, params={"bail_id": tal_seed["bail_id"]})
    assert r.status_code == 200 and {x["statut"] for x in r.json()["items"]} == {"transmise", "annulee"}
    r = client.get(f"{BASE}/transmissions", headers=auth_headers, params={"dossier_id": tal_seed["dossier_id"], "statut": "transmise"})
    assert r.json()["total"] == 1
    assert client.get(f"{BASE}/transmissions", headers=auth_headers, params={"statut": "nimporte"}).status_code == 422
    det = client.get(f"{BASE}/transmissions/{t['id']}", headers=auth_headers).json()
    assert det["form"]["coutLoyer"] == "1150" and det["statut"] == "transmise"

    c = client.get(f"{BASE}/compteur", headers=auth_headers).json()
    assert c["nb_simulation"] >= 1 and c["nb_reel"] == 0 and c["gratuits_restants"] == 10 and c["cout_tal_estime"] == 0
    assert client.get(f"{BASE}/compteur", headers=auth_headers, params={"mois": "2026-13"}).status_code == 422
    e = client.get(f"{BASE}/etat", headers=auth_headers).json()
    assert e["connexion"]["mode"] == "simulation" and e["connexion"]["cle_configuree"] is False
    assert not ({"cle", "api_key", "cle_chiffree"} & set(e["connexion"].keys()))   # jamais la clé elle-même
    assert e["schema"]["nb_champs"] == 409 and e["compteur"]["mois"]


# ─── Signature interne (eSign) + suivi dans le kanban ─────────────────


def test_signature_esign_et_suivi_kanban(client, auth_headers, tal_seed, run):
    """Le PDF officiel part en signature avec l'outil eSign de Kratos :
    locataire + caution + représentant, en parallèle ; le kanban Locations
    montre la même donnée (bail TAL généré, signature lancée, qui/quand)."""
    tid = IDS["t1"]
    # Pas de signature sur un brouillon.
    brouillon = client.post(f"{BASE}/transmissions", headers=auth_headers, json={"bail_id": tal_seed["bail2_id"]}).json()
    r = client.post(f"{BASE}/transmissions/{brouillon['id']}/signature", headers=auth_headers, json={})
    assert r.status_code == 409
    assert client.post(f"{BASE}/transmissions/{brouillon['id']}/annuler", headers=auth_headers).status_code == 200
    assert client.get(f"{BASE}/transmissions/{tid}/signature", headers=auth_headers).status_code == 404

    r = client.post(f"{BASE}/transmissions/{tid}/signature", headers=auth_headers, json={"message": "Merci de signer."})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["cree"] is True and body["url"] == f"/entreprises/signature/{body['esign_document_id']}"
    sig = body["signature"]
    assert sig["statut"] == "brouillon" and sig["nb_signataires"] == 3 and sig["nb_signes"] == 0
    roles = {s["role"]: s for s in sig["signataires"]}
    assert roles["locataire"]["nom"] == "Alice Test" and roles["locataire"]["email"] == "alice@test.ca"
    assert roles["caution"]["nom"] == "Bob Caution"
    assert roles["locateur"]["email"] == "smoke-admin@example.com"
    assert body["sans_courriel"] == []
    # Idempotent : même document.
    r2 = client.post(f"{BASE}/transmissions/{tid}/signature", headers=auth_headers, json={})
    assert r2.status_code == 201 and r2.json()["cree"] is False and r2.json()["esign_document_id"] == body["esign_document_id"]
    assert client.get(f"{BASE}/transmissions/{tid}/signature", headers=auth_headers).json()["nb_signataires"] == 3
    # Le document eSign existe bien côté module Signature (PDF = celui du TAL).
    d = client.get(f"/api/v1/esign/documents/{body['esign_document_id']}", headers=auth_headers)
    assert d.status_code == 200, d.text
    assert d.json()["title"].startswith("Bail de logement") and d.json()["status"] == "brouillon"
    assert len(d.json()["signers"]) == 3
    det = client.get(f"{BASE}/transmissions/{tid}", headers=auth_headers).json()
    assert det["esign_document_id"] == body["esign_document_id"]

    # Kanban Locations : la carte porte le suivi (même donnée que la fiche).
    r = client.get("/api/v1/immobilier/locations/overview", headers=auth_headers, params={"immeuble_id": tal_seed["imm_id"]})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["rows"] if x["id"] == tal_seed["dossier_id"])
    assert row["statut"] == "bail_envoye" and row["nouveau_bail_document_id"] is None
    assert row["tal_transmission_id"] == tid and row["tal_statut"] == "transmise" and row["tal_mode"] == "simulation"
    assert row["tal_document_id"] and row["tal_genere_le"]
    assert row["esign_document_id"] == body["esign_document_id"] and row["esign_statut"] == "brouillon"
    assert row["nb_signataires"] == 3 and row["nb_signes"] == 0
    assert {s["nom"] for s in row["signataires"]} == {"Alice Test", "Bob Caution", roles["locateur"]["nom"]}
    assert all(s["signe_le"] is None for s in row["signataires"])


# ─── Échec FRW122 puis relance, en mode réel (client factice) ──────────


class _FauxClient:
    """Client TAL factice en mode réel : FRW111 répond, FRW122 échoue une
    première fois puis renvoie un PDF."""

    simulation = False
    mode = tal_client.MODE_REEL

    def __init__(self) -> None:
        self.creer_calls = 0
        self.declencher_calls = 0
        self.identifiants: list = []

    async def creer_formulaire(self, form, *, identifiant_utilisateur=None):
        self.creer_calls += 1
        self.identifiants.append(identifiant_utilisateur)
        assert form["locataires"][0]["nom"] == "Carl Reel"
        return tal_client.ReponseCreation(short_guid="TAL-ABC123", brut={"shortGuid": "TAL-ABC123"})

    async def declencher_transmission(self, short_guid, *, identifiant_utilisateur=None, form_pour_simulation=None):
        self.declencher_calls += 1
        assert short_guid == "TAL-ABC123"
        if self.declencher_calls == 1:
            raise tal_client.TalApiError("FRW122", "HTTP 500 : panne simulée", http_status=500)
        pdf = tal_client.pdf_simulation(form_pour_simulation or {}, short_guid)
        return tal_client.ReponseTransmission(
            no_confirmation="CONF-2026-0001",
            documents=[
                tal_client.DocumentTal(nom="recu.xml", contenu_base64=base64.b64encode(b"<xml/>").decode(), type_source="xml"),
                tal_client.DocumentTal(nom="53000BAIL.pdf", contenu_base64=base64.b64encode(pdf).decode(), type_source="genererPdf"),
            ],
            messages=[{"mnemonique": "OK", "texte": "Transmission réussie"}],
            brut={},
        )


def test_echec_frw122_garde_le_shortguid_et_relance_sans_second_frw111(client, auth_headers, tal_seed, run, monkeypatch):
    faux = _FauxClient()
    monkeypatch.setattr(svc, "_fabrique_client", lambda cx: faux)
    r = client.post(f"{BASE}/transmissions", headers=auth_headers, json={"bail_id": tal_seed["bail2_id"]})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    # Rien à relancer avant le premier envoi.
    assert client.post(f"{BASE}/transmissions/{tid}/relancer", headers=auth_headers, json={"confirme": True}).status_code == 409

    r = client.post(f"{BASE}/transmissions/{tid}/generer", headers=auth_headers, json={"confirme": True})
    assert r.status_code == 502, r.text
    assert r.json()["detail"]["etape"] == "FRW122"
    det = client.get(f"{BASE}/transmissions/{tid}", headers=auth_headers).json()
    assert det["statut"] == "forme_creee" and det["short_guid"] == "TAL-ABC123" and det["mode"] == "reel"
    assert "panne simulée" in det["erreur"] and det["tentatives"] == 1
    assert faux.creer_calls == 1 and faux.identifiants == [f"kratos-b{tal_seed['bail2_id']}-t{tid}"]
    # Le formulaire ne se modifie plus : un ShortGuid existe au TAL.
    assert client.patch(f"{BASE}/transmissions/{tid}", headers=auth_headers, json={"form": det["form"]}).status_code == 409

    r = client.post(f"{BASE}/transmissions/{tid}/relancer", headers=auth_headers, json={"confirme": True})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["statut"] == "transmise" and g["short_guid"] == "TAL-ABC123" and g["no_confirmation"] == "CONF-2026-0001"
    assert faux.creer_calls == 1 and faux.declencher_calls == 2       # JAMAIS un second FRW111
    assert g["cout"] == 2.99 and g["frais_montant"] == 8.99 and g["frais_manuel_id"]
    assert g["erreur"] is None and g["tentatives"] == 2
    assert [d["nom"] for d in g["documents"]] == ["recu.xml", "53000BAIL.pdf"]

    async def _verif():
        async with TestSessionLocal() as s:
            doc = await s.get(ImmDocument, g["document_id"])
            fm = await s.get(FraisManuelGestion, g["frais_manuel_id"])
            blob = (await s.execute(select(ImmDocument.pdf_blob).where(ImmDocument.id == doc.id))).scalar_one()
            return {"pdf": bytes(blob[:5]), "filename": doc.filename, "fm_imm": fm.immeuble_id,
                    "fm_libelle": fm.libelle, "fm_montant": float(fm.montant)}

    v = run(_verif())
    assert v["pdf"] == b"%PDF-" and v["filename"] == "53000BAIL.pdf"
    assert v["fm_imm"] == tal_seed["imm_id"] and v["fm_montant"] == 8.99
    assert v["fm_libelle"].startswith("Bail officiel TAL") and "Carl Reel" in v["fm_libelle"]

    c = client.get(f"{BASE}/compteur", headers=auth_headers).json()
    assert c["nb_reel"] == 1 and c["cout_tal_estime"] == 2.99 and c["frais_refactures"] == 8.99
    assert c["gratuits_restants"] == 9 and c["total_reel_depuis_le_debut"] == 1


def test_echec_frw111_sans_shortguid(client, auth_headers, tal_seed, run, monkeypatch):
    class _Casse:
        simulation = False
        mode = tal_client.MODE_REEL

        async def creer_formulaire(self, form, *, identifiant_utilisateur=None):
            raise tal_client.TalApiError("FRW111", "HTTP 401 : clé refusée", http_status=401)

    monkeypatch.setattr(svc, "_fabrique_client", lambda cx: _Casse())

    async def _bail():
        async with TestSessionLocal() as s:
            lg = Logement(immeuble_id=tal_seed["imm_id"], numero="5", nb_pieces_decimal=2.5)
            s.add(lg)
            await s.flush()
            b = Bail(logement_id=lg.id, locataire_id=tal_seed["carl_id"], date_debut=date(2027, 1, 1),
                     date_fin=date(2027, 12, 31), loyer_mensuel=900.0, status=BailStatus.PROPOSE.value)
            s.add(b)
            await s.flush()
            await s.commit()
            return b.id

    bail_id = run(_bail())
    tid = client.post(f"{BASE}/transmissions", headers=auth_headers, json={"bail_id": bail_id}).json()["id"]
    r = client.post(f"{BASE}/transmissions/{tid}/generer", headers=auth_headers, json={"confirme": True})
    assert r.status_code == 502 and r.json()["detail"]["etape"] == "FRW111"
    det = client.get(f"{BASE}/transmissions/{tid}", headers=auth_headers).json()
    assert det["statut"] == "echec" and det["short_guid"] is None and "clé refusée" in det["erreur"]
    # Un échec s'annule ; un brouillon suivant repart propre.
    assert client.post(f"{BASE}/transmissions/{tid}/annuler", headers=auth_headers).json()["statut"] == "annulee"


# ─── Paramètres et clé chiffrée ────────────────────────────────────────


def test_parametres_cle_chiffree_jamais_exposee(client, auth_headers, employee_headers, run, monkeypatch):
    from cryptography.fernet import Fernet

    from app.core.config import settings

    # Sans coffre : refus explicite de stocker la clé.
    monkeypatch.setattr(settings, "subscription_encryption_key", None)
    monkeypatch.setattr(settings, "drive_token_encryption_key", None)
    r = client.put(f"{BASE}/parametres", headers=auth_headers, json={"api_key": "SECRET-TAL-123"})
    assert r.status_code == 503 and "chiffrement" in r.json()["detail"]

    monkeypatch.setattr(settings, "drive_token_encryption_key", Fernet.generate_key().decode())
    r = client.put(f"{BASE}/parametres", headers=auth_headers, json={
        "tarif_recharge": 12.5, "mode": "simulation", "api_url": "https://api.tal.test/frw/",
        "entete_cle": "Ocp-Apim-Subscription-Key", "api_key": "SECRET-TAL-123", "representant_nom": "Philippe Meuser",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    dump = json.dumps(body, ensure_ascii=False)
    assert "SECRET-TAL-123" not in dump
    assert body["connexion"]["cle_configuree"] is True and body["connexion"]["source_cle"] == "kratos"
    assert body["connexion"]["api_url"] == "https://api.tal.test/frw"
    assert body["connexion"]["entete_cle"] == "Ocp-Apim-Subscription-Key" and body["connexion"]["cle_posee_le"]
    assert body["connexion"]["pret_pour_reel"] is False      # mode simulation
    assert body["config"]["tarif_recharge"] == 12.5 and body["config"]["representant_nom"] == "Philippe Meuser"
    assert body["defauts"]["tarif_recharge"] == 8.99

    # La clé déchiffrée est bien celle posée (côté serveur seulement).
    async def _cx():
        async with TestSessionLocal() as s:
            cx, infos = await svc.charger_connexion(s)
            return cx.cle, cx.url, infos["cle_dechiffrable"]

    cle, url, ok = run(_cx())
    assert cle == "SECRET-TAL-123" and url == "https://api.tal.test/frw" and ok is True

    # Le journal d'audit ne contient jamais la clé.
    async def _audit():
        from app.models.audit_log import AuditLog

        async with TestSessionLocal() as s:
            rows = (await s.execute(select(AuditLog).where(AuditLog.action == "tal_bail.parametres"))).scalars().all()
            return [r.details_json or "" for r in rows]

    details = run(_audit())
    assert details and all("SECRET-TAL-123" not in d for d in details)
    assert any('"cle_posee": true' in d for d in details)

    # Le représentant configuré prend le pas sur la personne connectée.
    r = client.get(f"{BASE}/preparer", headers=auth_headers, params={"bail_id": IDS.get("bail_pour_rep") or 0})
    assert r.status_code in (200, 404)

    # Employé : lecture 403 / écriture 403 (gestionnaire requis).
    assert client.put(f"{BASE}/parametres", headers=employee_headers, json={"tarif_recharge": 1}).status_code == 403
    assert client.get(f"{BASE}/etat", headers=employee_headers).status_code == 403

    # Effacer la clé, revenir au tarif par défaut.
    r = client.put(f"{BASE}/parametres", headers=auth_headers, json={"effacer_cle": True, "tarif_recharge": 8.99, "representant_nom": None})
    assert r.status_code == 200 and r.json()["connexion"]["cle_configuree"] is False
    assert r.json()["config"]["tarif_recharge"] == 8.99 and r.json()["config"]["representant_nom"] == ""


# ─── Versions de schéma ────────────────────────────────────────────────


def test_schema_televersement_diff_activation(client, auth_headers, employee_headers):
    import json as _json
    from pathlib import Path

    asset = _json.loads(sorted(Path("app/assets/tal").glob("53000BAIL_schema_*.json"))[-1].read_text(encoding="utf-8"))
    modifie = copy.deepcopy(asset)
    modifie["champs"] = [c for c in modifie["champs"] if c["nom"] != "nbPiecesAutre"]
    modifie["champs"].append({"nom": "nouveauChampTal", "type": "text", "label": {"fr": "Nouveau"}})
    modifie["structurePreRemplissage"]["form"]["nouveauChampTal"] = "<texte>"
    modifie["structurePreRemplissage"]["form"].pop("nbPiecesAutre", None)
    nb = next(c for c in modifie["champs"] if c["nom"] == "nbPieces")
    nb["valeursPossibles"].pop("sept-demi", None)

    assert client.post(f"{BASE}/schema", headers=employee_headers, json={"schema": modifie}).status_code == 403
    assert client.post(f"{BASE}/schema", headers=auth_headers, json={"schema": {"typeFormulaire": "AUTRE"}}).status_code == 422

    r = client.post(f"{BASE}/schema", headers=auth_headers, json={"schema": modifie, "version": "2027-01-15", "source": "test.json"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["actif"] is False and body["version"] == "2027-01-15"
    d = body["diff"]
    assert "nbPiecesAutre" in d["champs_retires"] and "nouveauChampTal" in d["champs_ajoutes"]
    assert any(m["champ"] == "nbPieces" and "valeurs_possibles" in m["changements"] for m in d["champs_modifies"])
    assert d["gabarit_ajoute"] == ["nouveauChampTal"] and d["gabarit_retire"] == ["nbPiecesAutre"] and d["identique"] is False
    sid = body["id"]

    versions = client.get(f"{BASE}/schema/versions", headers=auth_headers).json()
    assert versions[0]["embarque"] is True and versions[0]["actif"] is True
    assert any(v["id"] == sid and v["actif"] is False for v in versions)

    r = client.post(f"{BASE}/schema/{sid}/activer", headers=auth_headers)
    assert r.status_code == 200 and r.json()["actif"]["version"] == "2027-01-15"
    s = client.get(f"{BASE}/schema", headers=auth_headers).json()
    assert s["resume"]["version"] == "2027-01-15" and "nouveauChampTal" in s["gabarit"]
    assert any(c["nom"] == "nouveauChampTal" for c in s["champs"])
    # Le validateur suit le schéma actif : l'ancien champ devient inconnu.
    r = client.get(f"{BASE}/preparer", headers=auth_headers, params={"bail_id": 0})
    assert r.status_code == 404
    # Retour au fichier embarqué.
    assert client.post(f"{BASE}/schema/999999/activer", headers=auth_headers).status_code == 404
    r = client.post(f"{BASE}/schema/0/activer", headers=auth_headers)
    assert r.status_code == 200 and r.json()["actif"]["source"].startswith("asset:")


# ─── Cliquet IA + MCP ──────────────────────────────────────────────────


def test_cliquet_ia_et_liste_mcp(client, api_key_headers, tal_seed):
    from app.core.api_ia_couverture import TABLES_COUVERTES

    assert {"tal_schemas", "tal_connexion", "tal_transmissions"} <= TABLES_COUVERTES
    r = client.get("/api/v1/activity/entities/tal_transmissions", headers=api_key_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pole"] == "immobilier" and body["count"] >= 1
    item = body["items"][0]
    assert item["entity_type"] == "tal_transmission" and "statut" in item
    dump = json.dumps(body, ensure_ascii=False)
    assert "SECRET" not in dump and "coutLoyer" not in dump   # jamais le formulaire ni une clé
