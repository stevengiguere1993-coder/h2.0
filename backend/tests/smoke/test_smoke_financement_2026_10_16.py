"""Smoke — Financement + baux parallèles (Phil 2026-10-16).

- un bail PARALLÈLE (sous-location, bail principal) est un vrai contrat
  HORS du quotidien : statut « parallele », coexiste avec le bail standard
  de l'unité, invisible dans Baux en vigueur, Paiements, Dépôts,
  Locataires et la recherche ; l'unité qu'il occupe seul n'est pas
  « vacante » ;
- rent roll d'un immeuble (json, pdf, xlsx, csv) : une ligne par unité
  depuis les baux enregistrés, section parallèles à part, totaux par
  catégorie, choix des catégories, colonne projection marquée ;
- dossier de financement : checklist standard, pièces fournies/envoyées,
  journal, projection pro forma, tableau de bord, paquet PDF (rent roll +
  pièces de l'immeuble seulement) ;
- bail officiel TAL d'un bail parallèle : le locateur est celui nommé sur
  le bail ;
- cliquet IA + liste MCP « financements ».
"""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.immobilier import (
    Bail,
    BailStatus,
    ImmDocument,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
)
from tests.smoke.conftest import TestSessionLocal

FIN = "/api/v1/immobilier/financement"
IDS: dict = {}


@pytest.fixture(scope="module")
def fin_seed(run, seeded_users) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(name="Immeuble Smoke Financement", address="4500 rue Prêteur", city="Montréal",
                           postal_code="H2X 1A1", annee_construction=1975, is_active=True)
            s.add(imm)
            await s.flush()
            l101 = Logement(immeuble_id=imm.id, numero="101", nb_pieces_decimal=4.5, status=LogementStatus.OCCUPE.value, loyer_demande=1000)
            l102 = Logement(immeuble_id=imm.id, numero="102", nb_pieces_decimal=3.5, status=LogementStatus.VACANT.value, loyer_demande=950)
            l103 = Logement(immeuble_id=imm.id, numero="103", nb_pieces_decimal=5.5, status=LogementStatus.VACANT.value, loyer_demande=1400)
            s.add_all([l101, l102, l103])
            jean = Locataire(full_name="Jean Standard", email="jean@test.ca", phone="514-555-1111")
            occ = Locataire(full_name="Sophie Occupante", email="sophie@test.ca", categorie="parallele")
            s.add_all([jean, occ])
            await s.flush()
            b_std = Bail(logement_id=l101.id, locataire_id=jean.id, date_debut=date(2026, 7, 1), date_fin=date(2027, 6, 30),
                         loyer_mensuel=1000.0, status=BailStatus.ACTIF.value, chauffage_inclus=True)
            # Bail parallèle EN VIGUEUR sur la même unité (sous-location de l'exploitant).
            b_par = Bail(logement_id=l101.id, locataire_id=occ.id, date_debut=date(2026, 8, 1), date_fin=date(2027, 7, 31),
                         loyer_mensuel=1300.0, status=BailStatus.PARALLELE.value, categorie="parallele",
                         parallele_type="sous_location", parallele_locateur="Opérateur ABC inc.",
                         parallele_locateur_courriel="abc@operateur.test", parallele_locateur_telephone="514 555 2222")
            s.add_all([b_std, b_par])
            await s.flush()
            await s.commit()
            return {"imm_id": imm.id, "l101": l101.id, "l102": l102.id, "l103": l103.id, "jean": jean.id,
                    "occ": occ.id, "b_std": b_std.id, "b_par": b_par.id}

    return run(_seed())


# ─── Baux parallèles : hors du quotidien ──────────────────────────────


def test_bail_parallele_hors_du_quotidien(client, auth_headers, fin_seed, run):
    imm = fin_seed["imm_id"]
    # Page Baux en vigueur : l'unité 101 montre le bail standard, jamais le parallèle.
    r = client.get("/api/v1/immobilier/suivi-baux", headers=auth_headers, params={"immeuble_id": imm})
    assert r.status_code == 200, r.text
    rows = {x["logement_numero"]: x for x in r.json()}
    assert rows["101"]["bail_id"] == fin_seed["b_std"] and rows["101"]["locataire_nom"] == "Jean Standard"
    assert rows["101"]["prochain_bail_id"] is None
    # Baux de la fiche immeuble : le parallèle n'y est pas.
    r = client.get(f"/api/v1/immobilier/immeubles/{imm}/baux", headers=auth_headers)
    assert r.status_code == 200 and {b["id"] for b in r.json()} == {fin_seed["b_std"]}
    # Locataires du quotidien et recherche : l'occupante parallèle n'y est pas.
    r = client.get("/api/v1/immobilier/locataires", headers=auth_headers, params={"search": "Occupante"})
    assert r.status_code == 200 and r.json() == []
    r = client.get("/api/v1/immobilier/locataires", headers=auth_headers, params={"search": "Jean Standard"})
    assert r.status_code == 200 and len(r.json()) == 1
    # Dépôts : aucune ligne pour le bail parallèle.
    r = client.get("/api/v1/immobilier/depots/overview", headers=auth_headers, params={"immeuble_id": imm})
    assert r.status_code == 200
    assert all(x["bail_id"] != fin_seed["b_par"] for x in r.json()["rows"])
    # Financement : la liste des baux parallèles le montre, lui seul.
    r = client.get(f"{FIN}/immeubles/{imm}/baux-paralleles", headers=auth_headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [x["id"] for x in items] == [fin_seed["b_par"]]
    assert items[0]["en_vigueur"] is True and items[0]["locateur_bail" if "locateur_bail" in items[0] else "parallele_locateur"] == "Opérateur ABC inc."
    assert items[0]["locataire_nom"] == "Sophie Occupante" and items[0]["type_label"] == "Sous-location"


def test_creer_bail_parallele_depuis_financement(client, auth_headers, fin_seed, run):
    imm = fin_seed["imm_id"]
    # Type inconnu / statut inconnu / dates : refus propres.
    base = {"logement_id": fin_seed["l103"], "locataire": {"full_name": "Marc Sous-Locataire", "email": "marc@test.ca"},
            "parallele_locateur": "Opérateur ABC inc.", "date_debut": "2026-09-01", "date_fin": "2027-08-31", "loyer_mensuel": 1450}
    assert client.post(f"{FIN}/baux-paralleles", headers=auth_headers, json={**base, "parallele_type": "nimporte"}).status_code == 422
    assert client.post(f"{FIN}/baux-paralleles", headers=auth_headers, json={**base, "statut": "actif"}).status_code == 422
    assert client.post(f"{FIN}/baux-paralleles", headers=auth_headers, json={**base, "date_fin": "2026-01-01"}).status_code == 422
    # Création : bail parallèle en vigueur sur l'unité 103 (seule), nouvel occupant hors quotidien.
    r = client.post(f"{FIN}/baux-paralleles", headers=auth_headers, json={**base, "parallele_type": "bail_principal", "internet_inclus": True})
    assert r.status_code == 201, r.text
    b = r.json()
    IDS["b103"] = b["id"]
    assert b["status"] == "parallele" and b["categorie"] == "parallele" and b["parallele_type"] == "bail_principal"
    assert b["locataire_nom"] == "Marc Sous-Locataire" and b["locataire_categorie"] == "parallele"
    assert b["type_label"] == "Bail principal (le locataire sous-loue)"

    async def _etat():
        async with TestSessionLocal() as s:
            lg = await s.get(Logement, fin_seed["l103"])
            lo = (await s.execute(select(Locataire).where(Locataire.full_name == "Marc Sous-Locataire"))).scalars().one()
            return lg.status, lo.categorie

    statut_103, cat = run(_etat())
    # L'unité est OCCUPÉE (quelqu'un y vit) — jamais « vacante » ni en relocation.
    assert statut_103 == LogementStatus.OCCUPE.value and cat == "parallele"
    # … mais pour le quotidien, l'unité n'a pas de bail : la page Baux la montre sans bail courant.
    rows = {x["logement_numero"]: x for x in client.get("/api/v1/immobilier/suivi-baux", headers=auth_headers, params={"immeuble_id": imm}).json()}
    assert rows["103"]["bail_id"] is None and rows["103"]["prochain_bail_id"] is None
    # Un bail STANDARD proposé pour un autre locataire sur la 103 passe (pas de 409) : les deux coexistent.
    r = client.post("/api/v1/immobilier/baux", headers=auth_headers, json={
        "logement_id": fin_seed["l103"], "locataire_id": fin_seed["jean"], "date_debut": "2027-09-01", "date_fin": "2028-08-31",
        "loyer_mensuel": 1500, "status": "propose",
    })
    assert r.status_code == 201, r.text
    IDS["b103_std"] = r.json()["id"]
    # Le statut « parallele » est réservé aux baux parallèles.
    r = client.post("/api/v1/immobilier/baux", headers=auth_headers, json={
        "logement_id": fin_seed["l102"], "locataire_id": fin_seed["jean"], "date_debut": "2027-01-01", "date_fin": "2027-12-31",
        "loyer_mensuel": 900, "status": "parallele",
    })
    assert r.status_code == 422
    # Modifier : changer le loyer et terminer.
    r = client.patch(f"{FIN}/baux-paralleles/{IDS['b103']}", headers=auth_headers, json={"loyer_mensuel": 1475, "parallele_note": "indexé"})
    assert r.status_code == 200 and r.json()["loyer_mensuel"] == 1475 and r.json()["parallele_note"] == "indexé"
    assert client.patch(f"{FIN}/baux-paralleles/{fin_seed['b_std']}", headers=auth_headers, json={"loyer_mensuel": 1}).status_code == 404


# ─── Rent roll ────────────────────────────────────────────────────────


def test_rent_roll_json_et_exports(client, auth_headers, fin_seed):
    imm = fin_seed["imm_id"]
    r = client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers)
    assert r.status_code == 200, r.text
    rr = r.json()
    assert rr["immeuble"]["nom"] == "Immeuble Smoke Financement"
    lignes = {l["numero"]: l for l in rr["lignes"]}
    assert list(lignes) == ["101", "102", "103"]
    assert lignes["101"]["occupation"] == "occupe" and lignes["101"]["loyer"] == 1000 and lignes["101"]["locataire"] == "Jean Standard"
    assert lignes["101"]["inclusions"] == ["chauffage"] and lignes["101"]["nb_paralleles"] == 1 and lignes["101"]["categorie"] == "standard"
    assert lignes["102"]["occupation"] == "vacant" and lignes["102"]["loyer"] is None
    assert lignes["103"]["occupation"] == "parallele_seulement" and lignes["103"]["loyer"] is None
    assert lignes["103"]["prochain"]["bail_id"] == IDS["b103_std"] and lignes["103"]["prochain"]["loyer"] == 1500
    pars = {p["bail_id"]: p for p in rr["paralleles"]}
    assert set(pars) == {fin_seed["b_par"], IDS["b103"]}
    assert pars[fin_seed["b_par"]]["locateur_bail"] == "Opérateur ABC inc." and pars[fin_seed["b_par"]]["loyer"] == 1300
    assert pars[IDS["b103"]]["loyer"] == 1475 and pars[IDS["b103"]]["type_label"] == "Bail principal (le locataire sous-loue)"
    t = rr["totaux"]
    assert t["nb_unites"] == 3 and t["nb_occupees"] == 2 and t["nb_vacantes"] == 1
    assert t["mensuel_standard"] == 1000 and t["annuel_standard"] == 12000
    assert t["nb_paralleles"] == 2 and t["mensuel_paralleles"] == 2775
    assert t["categories"] == ["standard", "parallele"] and rr["projection"] is None

    # Sans les parallèles / parallèles seulement.
    r = client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers, params={"inclure_paralleles": "false"})
    assert r.json()["paralleles"] == [] and r.json()["totaux"]["categories"] == ["standard"]
    r = client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers, params={"inclure_standards": "false"})
    assert r.json()["lignes"] == [] and r.json()["totaux"]["categories"] == ["parallele"] and len(r.json()["paralleles"]) == 2
    assert client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers, params={"inclure_standards": "false", "inclure_paralleles": "false"}).status_code == 422

    # Exports : PDF, Excel, CSV.
    r = client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers, params={"fmt": "pdf"})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-" and "rent-roll" in r.headers["content-disposition"]
    r = client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers, params={"fmt": "pdf", "inclure_standards": "false"})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    r = client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers, params={"fmt": "xlsx"})
    assert r.status_code == 200 and r.content[:2] == b"PK"
    r = client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers, params={"fmt": "csv"})
    assert r.status_code == 200
    csv = r.content.decode("utf-8-sig")
    assert csv.splitlines()[0].startswith("Catégorie;Unité;Pièces;Occupation;Locataire;Locateur du bail")
    assert "Parallèle;101" in csv and "Opérateur ABC inc." in csv and "TOTAL baux standards" in csv and "TOTAL baux parallèles" in csv
    assert client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers, params={"fmt": "docx"}).status_code == 400
    assert client.get(f"{FIN}/immeubles/999999/rent-roll", headers=auth_headers).status_code == 404


# ─── Unité louée en chambres : une ligne, total des chambres ──────────


def test_rent_roll_unite_en_chambres(client, auth_headers, run):
    """Phil 2026-10-16 (1660 Saint-Clément) : une unité louée en chambres
    reste UNE ligne du rent roll, avec le total des loyers des chambres et les
    vrais baux de chambre comme pièces — pas de bail inventé pour l'unité."""

    async def _seed():
        async with TestSessionLocal() as s:
            imm = Immeuble(name="Immeuble Smoke Chambres", address="1660 rue Chambres", city="Montréal", is_active=True)
            s.add(imm)
            await s.flush()
            u1 = Logement(immeuble_id=imm.id, numero="1", nb_pieces_decimal=5.5, status=LogementStatus.OCCUPE.value, location_en_chambres=True)
            u2 = Logement(immeuble_id=imm.id, numero="2", nb_pieces_decimal=4.5, status=LogementStatus.OCCUPE.value)
            a, b, c = Locataire(full_name="Anne Chambre"), Locataire(full_name="Bruno Chambre"), Locataire(full_name="Claire Entier")
            s.add_all([u1, u2, a, b, c])
            await s.flush()
            s.add_all([
                Bail(logement_id=u1.id, locataire_id=a.id, date_debut=date(2026, 1, 1), date_fin=date(2026, 12, 31), loyer_mensuel=500.0,
                     status=BailStatus.ACTIF.value, au_mois=True, chauffage_inclus=True),
                Bail(logement_id=u1.id, locataire_id=b.id, date_debut=date(2026, 3, 1), date_fin=date(2027, 2, 28), loyer_mensuel=550.0,
                     status=BailStatus.ACTIF.value, au_mois=True, internet_inclus=True),
                Bail(logement_id=u2.id, locataire_id=c.id, date_debut=date(2026, 7, 1), date_fin=date(2027, 6, 30), loyer_mensuel=1200.0,
                     status=BailStatus.ACTIF.value),
            ])
            await s.flush()
            await s.commit()
            return imm.id

    imm = run(_seed())
    r = client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers)
    assert r.status_code == 200, r.text
    rr = r.json()
    assert len(rr["lignes"]) == 2                         # 2 unités, pas 3 baux
    l1 = next(l for l in rr["lignes"] if l["numero"] == "1")
    assert l1["occupation"] == "occupe_chambres" and l1["loyer"] == 1050 and l1["bail_id"] is None
    assert l1["locataire"] == "2 chambres : Anne Chambre, Bruno Chambre"
    assert [b["loyer"] for b in l1["baux"]] == [500, 550] and l1["document_signe"] is False
    assert l1["inclusions"] == ["chauffage", "internet"] and l1["au_mois"] is True and l1["date_fin"] is None
    assert "prochain" not in l1
    t = rr["totaux"]
    assert t["nb_unites"] == 2 and t["nb_occupees"] == 2 and t["mensuel_standard"] == 2250
    r = client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers, params={"fmt": "csv"})
    csv = r.content.decode("utf-8-sig")
    assert "Occupé · 2 chambres" in csv and "2 chambres : Anne Chambre, Bruno Chambre" in csv
    r = client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers, params={"fmt": "pdf"})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"


# ─── Bail principal : le locataire loue l'unité et sous-loue les chambres ──


def test_rent_roll_bail_principal_locataire_qui_sous_loue(client, auth_headers, run):
    """Phil 2026-10-16 (cas Jacques) : Jacques loue toute l'unité 3 500 $,
    paie ce loyer, et sous-loue les chambres par Horizon. Son bail
    (parallèle, type bail principal, locateur = le propriétaire) est LE bail
    de l'unité dans le rent roll ; les baux de chambre sont ses
    sous-locations, hors du revenu du propriétaire."""
    from app.models.entreprise import Entreprise

    async def _seed():
        async with TestSessionLocal() as s:
            ent = Entreprise(name="Proprio Smoke INC", type="immobilier", contact_email="proprio@smoke.test",
                             siege_social="1 rue du Siège, Montréal (Québec) H1A 1A1")
            s.add(ent)
            await s.flush()
            imm = Immeuble(name="Immeuble Smoke Jacques", address="1660 rue Principal", city="Montréal", owner_entreprise_id=ent.id, is_active=True)
            s.add(imm)
            await s.flush()
            u1 = Logement(immeuble_id=imm.id, numero="1", nb_pieces_decimal=5.5, status=LogementStatus.OCCUPE.value, location_en_chambres=True)
            jacques = Locataire(full_name="Jacques Principal", email="jacques@test.ca", categorie="parallele")
            r1, r2 = Locataire(full_name="Rita Chambre"), Locataire(full_name="Sam Chambre")
            s.add_all([u1, jacques, r1, r2])
            await s.flush()
            s.add_all([
                Bail(logement_id=u1.id, locataire_id=r1.id, date_debut=date(2026, 1, 1), date_fin=date(2026, 12, 31), loyer_mensuel=500.0, status=BailStatus.ACTIF.value, au_mois=True),
                Bail(logement_id=u1.id, locataire_id=r2.id, date_debut=date(2026, 2, 1), date_fin=date(2027, 1, 31), loyer_mensuel=550.0, status=BailStatus.ACTIF.value, au_mois=True),
            ])
            principal = Bail(logement_id=u1.id, locataire_id=jacques.id, date_debut=date(2026, 1, 1), date_fin=date(2026, 12, 31), loyer_mensuel=3500.0,
                             status=BailStatus.PARALLELE.value, categorie="parallele", parallele_type="bail_principal", parallele_locateur=None)
            s.add(principal)
            await s.flush()
            await s.commit()
            return imm.id, principal.id, u1.id

    imm, principal_id, u1 = run(_seed())
    rr = client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers).json()
    assert len(rr["lignes"]) == 1
    l = rr["lignes"][0]
    assert l["categorie"] == "bail_principal" and l["bail_id"] == principal_id and l["locataire"] == "Jacques Principal"
    assert l["loyer"] == 3500 and l["occupation"] == "occupe" and l["baux"] == []
    assert [s["loyer"] for s in l["sous_locations"]] == [500, 550] and "sous-loue 2 chambres" in l["mention"]
    assert rr["paralleles"] == []                      # le bail principal est SUR la ligne, pas en section à part
    t = rr["totaux"]
    assert t["mensuel_standard"] == 3500 and t["nb_paralleles"] == 0 and t["nb_occupees"] == 1
    csv = client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers, params={"fmt": "csv"}).content.decode("utf-8-sig")
    assert "Bail principal;1;" in csv and "Sous-location du locataire;1;" in csv and "Occupé · bail principal (2 sous-locations)" in csv
    assert client.get(f"{FIN}/immeubles/{imm}/rent-roll", headers=auth_headers, params={"fmt": "pdf"}).content[:5] == b"%PDF-"
    # Le bail officiel TAL de Jacques : locateur = le propriétaire, clause de sous-location écrite.
    r = client.get("/api/v1/immobilier/tal-bail/preparer", headers=auth_headers, params={"bail_id": principal_id})
    assert r.status_code == 200, r.text
    f = r.json()["form"]
    assert f["locateurs"][0]["nom"] == "Proprio Smoke INC" and f["locataires"][0]["nom"] == "Jacques Principal" and f["coutLoyer"] == "3500"
    assert f["possedeAutresServicesConditionsRestriction"] == "true" and "sous-louer les chambres" in f["precisionAutresServicesConditionsRestriction"]
    # Création par l'API sans locateur nommé → le propriétaire.
    r = client.post(f"{FIN}/baux-paralleles", headers=auth_headers, json={
        "logement_id": u1, "locataire": {"full_name": "Autre Principal"}, "parallele_type": "bail_principal",
        "date_debut": "2027-01-01", "date_fin": "2027-12-31", "loyer_mensuel": 3600, "statut": "propose",
    })
    assert r.status_code == 201, r.text
    assert r.json()["parallele_locateur"] is None and r.json()["locateur_effectif"] == "Propriétaire"


# ─── Dossier de financement ───────────────────────────────────────────


def test_dossier_checklist_projection_paquet(client, auth_headers, employee_headers, fin_seed, run):
    imm = fin_seed["imm_id"]
    assert client.get(f"{FIN}/dossiers", headers=employee_headers).status_code == 403
    r = client.post(f"{FIN}/dossiers", headers=auth_headers, json={
        "immeuble_id": imm, "type": "refinancement", "preteur": "Banque Smoke", "courtier": "Courtier X",
        "montant_demande": 850000, "taux_pct": 4.75, "terme_mois": 60, "date_echeance": str(date.today() + timedelta(days=45)),
    })
    assert r.status_code == 201, r.text
    d = r.json()
    IDS["dossier"] = d["id"]
    assert d["titre"].startswith("Refinancement — Immeuble Smoke Financement") and d["statut"] == "preparation"
    assert d["immeuble_nom"] == "Immeuble Smoke Financement" and d["inclure_standards"] is True
    types = [p["type"] for p in d["pieces"]]
    assert types[0] == "rent_roll" and "baux_paralleles" in types and "releve_hypothecaire" in types and "etats_financiers" in types
    assert all(p["fournie"] is False for p in d["pieces"])
    # Départ : toutes les unités « fixes » (telles quelles) — aucun loyer visé.
    assert d["projection"]["logements"] == {}
    assert all(l["cible"]["mode"] == "fixe" and l["cible"]["statut"] == "fixe" for l in d["rent_roll"]["lignes"])
    tb = d["tableau_de_bord"]
    assert tb["reel_mensuel"] == 1000 and tb["paralleles_mensuel"] == 2775 and tb["pieces_fournies"] == 0
    assert tb["jours_avant_echeance"] in (44, 45) and len(tb["pieces_manquantes"]) == tb["pieces_requises"]
    assert d["journal"][0]["type"] == "statut"
    # Sans unité à ajuster : pas de colonne « loyer visé ».
    assert d["rent_roll"]["projection"] is None and tb["nb_a_ajuster"] == 0 and tb["vise_mensuel"] == 1000

    # Projection manuelle + vacance.
    # Unités à ajuster (loyer visé) en lot + vacance.
    r = client.put(f"{FIN}/dossiers/{d['id']}/projection", headers=auth_headers, json={
        "logements": {str(fin_seed["l101"]): {"mode": "ajuster", "loyer": 1200, "note": "après rénovation"},
                      str(fin_seed["l102"]): {"mode": "ajuster", "loyer": 1000},
                      str(fin_seed["l103"]): {"mode": "fixe", "loyer": 5000}},
        "hypotheses": {"vacance_pct": 3},
    })
    assert r.status_code == 200, r.text
    tb = r.json()["tableau_de_bord"]
    # Visé = 101 : 1 200 (au lieu de 1 000) + 102 : 1 000 (vacant) ; 103 fixe sans bail standard → rien.
    assert tb["projection_mensuelle"] == 1200 + 1000 and tb["ecart_projection_pct"] == 120.0 and tb["nb_a_ajuster"] == 2
    assert tb["projection_annuelle"] == round(2200 * 12 * 0.97, 2) and tb["vise_mensuel"] == 2200
    assert str(fin_seed["l103"]) not in r.json()["projection"]["logements"]  # fixe = rien à retenir
    assert client.put(f"{FIN}/dossiers/{d['id']}/projection", headers=auth_headers, json={"logements": {"1": {"mode": "ajuster", "loyer": -5}}}).status_code == 422
    assert client.put(f"{FIN}/dossiers/{d['id']}/projection", headers=auth_headers, json={"logements": {"1": {"mode": "bidon", "loyer": 5}}}).status_code == 422
    # L'export du dossier a la colonne « loyer visé » (objectif, pas un bail), en PDF aussi.
    r = client.get(f"{FIN}/dossiers/{d['id']}/rent-roll", headers=auth_headers, params={"fmt": "csv"})
    txt = r.content.decode("utf-8-sig")
    assert r.status_code == 200 and "Loyer visé (objectif du propriétaire, pas un bail)" in txt and "À faire" in txt and "LOYERS VISÉS" in txt
    r = client.get(f"{FIN}/dossiers/{d['id']}/rent-roll", headers=auth_headers, params={"fmt": "pdf"})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"

    # Pièces : marquer envoyée, rattacher un document importé de l'immeuble, refuser un document d'ailleurs.
    piece_rr = next(p for p in d["pieces"] if p["type"] == "rent_roll")
    r = client.patch(f"{FIN}/pieces/{piece_rr['id']}", headers=auth_headers, json={"envoye": True})
    assert r.status_code == 200 and r.json()["fournie"] is True and r.json()["envoye_le"]
    import reportlab  # noqa: F401 — PDF réel pour le paquet
    from app.integrations.tal.client import pdf_simulation

    pdf = pdf_simulation({"locateurs": [{"nom": "Test"}]}, "SIM-FIN")
    r = client.post("/api/v1/immobilier/documents/import", headers=auth_headers,
                    data={"type": "autre", "titre": "Compte de taxes 2026", "immeuble_id": str(imm)},
                    files={"file": ("taxes.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    r = client.get(f"{FIN}/immeubles/{imm}/documents", headers=auth_headers)
    assert r.status_code == 200 and any(x["id"] == doc_id and x["titre"] == "Compte de taxes 2026" for x in r.json()["items"])
    piece_taxes = next(p for p in d["pieces"] if p["type"] == "taxes")
    r = client.patch(f"{FIN}/pieces/{piece_taxes['id']}", headers=auth_headers, json={"document_id": doc_id})
    assert r.status_code == 200 and r.json()["fournie"] is True
    # Un document d'un autre immeuble ne se rattache pas.
    r2 = client.post("/api/v1/immobilier/documents/import", headers=auth_headers,
                     data={"type": "autre", "titre": "Ailleurs", "immeuble_id": "999999"},
                     files={"file": ("x.pdf", pdf, "application/pdf")})
    autre_doc = r2.json()["id"]
    assert client.patch(f"{FIN}/pieces/{piece_taxes['id']}", headers=auth_headers, json={"document_id": autre_doc}).status_code == 422
    r = client.post(f"{FIN}/dossiers/{d['id']}/pieces", headers=auth_headers, json={"type": "autre", "libelle": "Lettre d'intention"})
    assert r.status_code == 201 and r.json()["ordre"] == len(d["pieces"])
    assert client.delete(f"{FIN}/pieces/{r.json()['id']}", headers=auth_headers).status_code == 204

    # Journal + statut (date de dépôt posée automatiquement).
    r = client.post(f"{FIN}/dossiers/{d['id']}/journal", headers=auth_headers, json={"type": "envoi", "texte": "Dossier envoyé au courtier."})
    assert r.status_code == 201
    r = client.patch(f"{FIN}/dossiers/{d['id']}", headers=auth_headers, json={"statut": "envoye"})
    assert r.status_code == 200 and r.json()["statut"] == "envoye" and r.json()["date_depot"] == date.today().isoformat()
    assert r.json()["journal"][0]["texte"].startswith("Statut : preparation → envoye")
    assert client.patch(f"{FIN}/dossiers/{d['id']}", headers=auth_headers, json={"statut": "bidon"}).status_code == 422

    # Paquet PDF : rent roll + pièce de l'immeuble ; la pièce d'ailleurs est refusée dans le rapport.
    r = client.get(f"{FIN}/dossiers/{d['id']}/paquet.pdf", headers=auth_headers, params={"documents": f"{doc_id},{autre_doc}", "rent_roll": "true"})
    assert r.status_code == 200, r.text
    assert r.content[:5] == b"%PDF-"
    from pypdf import PdfReader

    assert len(PdfReader(io.BytesIO(r.content)).pages) >= 2
    rapport = json.loads(r.headers["x-kratos-paquet"])
    assert any(x["id"] == doc_id and x["ok"] for x in rapport) and any(x["id"] == autre_doc and not x["ok"] for x in rapport)
    assert client.get(f"{FIN}/dossiers/{d['id']}/paquet.pdf", headers=auth_headers, params={"rent_roll": "false"}).status_code == 422

    # Liste + suppression.
    r = client.get(f"{FIN}/dossiers", headers=auth_headers, params={"immeuble_id": imm})
    assert r.status_code == 200 and r.json()["total"] == 1 and r.json()["items"][0]["nb_pieces_fournies"] == 2
    assert client.get(f"{FIN}/dossiers/{d['id']}", headers=auth_headers).status_code == 200


def test_unites_fixes_ou_a_ajuster_et_statuts(client, auth_headers, fin_seed):
    """Phil 2026-10-21 : je choisis les unités FIXES (telles quelles, baux et
    avis visibles, rien à changer) ; pour les autres j'écris le loyer visé ;
    le rent roll suit ; les avis de renouvellement et nouveaux baux se créent
    au moment venu pour atteindre ce montant. Le statut de l'objectif vient
    des baux et des avis réels — jamais l'inverse."""
    did = IDS["dossier"]

    def ligne(d, num):
        return next(l for l in d["rent_roll"]["lignes"] if l["numero"] == num)

    # Tout fixe d'abord.
    r = client.put(f"{FIN}/dossiers/{did}/projection", headers=auth_headers, json={"logements": {}, "hypotheses": {"vacance_pct": 0}})
    assert r.status_code == 200 and r.json()["tableau_de_bord"]["nb_a_ajuster"] == 0
    # 101 : occupé 1 000 $ → visé 1 200 $ : à faire.
    r = client.patch(f"{FIN}/dossiers/{did}/unites/{fin_seed['l101']}", headers=auth_headers, json={"mode": "ajuster", "loyer": 1200})
    assert r.status_code == 200, r.text
    d = r.json()
    c = ligne(d, "101")["cible"]
    assert c["mode"] == "ajuster" and c["loyer_vise"] == 1200 and c["statut"] == "a_faire" and c["ecart"] == 200
    assert ligne(d, "101")["projection"]["loyer"] == 1200 and ligne(d, "101")["loyer"] == 1000  # le bail n'a pas bougé
    assert ligne(d, "102")["cible"]["statut"] == "fixe" and ligne(d, "102")["projection"]["loyer"] is None
    assert d["journal"][0]["texte"] == "Unité 101 : à ajuster, loyer visé 1200.00 $."
    # À ajuster sans montant encore : « loyer visé à indiquer ».
    r = client.patch(f"{FIN}/dossiers/{did}/unites/{fin_seed['l102']}", headers=auth_headers, json={"mode": "ajuster"})
    assert r.status_code == 200 and ligne(r.json(), "102")["cible"]["statut"] == "a_definir"
    # 103 : un bail standard PROPOSÉ à 1 500 $ existe déjà → bail en signature.
    r = client.patch(f"{FIN}/dossiers/{did}/unites/{fin_seed['l103']}", headers=auth_headers, json={"loyer": 1500})
    assert r.status_code == 200 and ligne(r.json(), "103")["cible"]["statut"] == "bail_en_signature"
    # 101 : visé 900 $ ≤ loyer en vigueur → atteint.
    r = client.patch(f"{FIN}/dossiers/{did}/unites/{fin_seed['l101']}", headers=auth_headers, json={"loyer": 900})
    assert r.status_code == 200 and ligne(r.json(), "101")["cible"]["statut"] == "atteint"
    # Avis de renouvellement RÉEL envoyé au locataire en place à 1 200 $ → avis envoyé.
    assert client.patch(f"{FIN}/dossiers/{did}/unites/{fin_seed['l101']}", headers=auth_headers, json={"loyer": 1200}).status_code == 200
    r = client.post(f"/api/v1/immobilier/baux/{fin_seed['b_std']}/envoyer-renouvellement", headers=auth_headers, json={"nouveau_loyer": 1200})
    assert r.status_code == 200, r.text
    d = client.get(f"{FIN}/dossiers/{did}", headers=auth_headers).json()
    c = ligne(d, "101")["cible"]
    assert c["statut"] == "avis_envoye" and c["renouvellement"]["nouveau_loyer"] == 1200 and c["renouvellement"]["statut"] == "propose"
    assert d["tableau_de_bord"]["nb_a_ajuster"] == 3 and d["tableau_de_bord"]["projection_mensuelle"] == 1200 + 1500
    csv = client.get(f"{FIN}/dossiers/{did}/rent-roll", headers=auth_headers, params={"fmt": "csv"}).content.decode("utf-8-sig")
    assert "Avis envoyé" in csv and "Bail en signature" in csv and "Loyer visé à indiquer" in csv
    assert client.get(f"{FIN}/dossiers/{did}/rent-roll", headers=auth_headers, params={"fmt": "pdf"}).content[:5] == b"%PDF-"
    # Retour à fixe : l'objectif disparaît, le loyer en vigueur reste.
    r = client.patch(f"{FIN}/dossiers/{did}/unites/{fin_seed['l101']}", headers=auth_headers, json={"mode": "fixe"})
    assert r.status_code == 200 and ligne(r.json(), "101")["cible"]["statut"] == "fixe"
    assert str(fin_seed["l101"]) not in r.json()["projection"]["logements"] and ligne(r.json(), "101")["loyer"] == 1000
    # Refus propres.
    assert client.patch(f"{FIN}/dossiers/{did}/unites/999999", headers=auth_headers, json={"loyer": 1}).status_code == 404
    assert client.patch(f"{FIN}/dossiers/{did}/unites/{fin_seed['l102']}", headers=auth_headers, json={"mode": "bidon"}).status_code == 422
    assert client.patch(f"{FIN}/dossiers/{did}/unites/{fin_seed['l102']}", headers=auth_headers, json={"loyer": 0}).status_code == 422


# ─── Bail officiel TAL d'un bail parallèle ────────────────────────────


def test_tal_prepare_le_locateur_du_bail_parallele(client, auth_headers, fin_seed):
    r = client.get("/api/v1/immobilier/tal-bail/preparer", headers=auth_headers, params={"bail_id": fin_seed["b_par"]})
    assert r.status_code == 200, r.text
    f = r.json()["form"]
    assert f["locateurs"][0]["nom"] == "Opérateur ABC inc."
    assert f["locateurs"][0]["courrielLocateur"] == "abc@operateur.test" and f["locateurs"][0]["noTelephone"] == "514-555-2222"
    assert f["locataires"][0]["nom"] == "Sophie Occupante" and f["coutLoyer"] == "1300"
    assert r.json()["contexte"]["locateur"] == "Opérateur ABC inc." and r.json()["contexte"]["bail_categorie"] == "parallele"
    assert any(x["chemin"] == "locateurs[0].adresse" for x in r.json()["a_verifier"])


# ─── Cliquet IA + MCP ──────────────────────────────────────────────────


def test_cliquet_et_mcp_financements(client, api_key_headers, fin_seed):
    from app.core.api_ia_couverture import TABLES_COUVERTES

    assert {"imm_financements", "imm_financement_pieces", "imm_financement_journal"} <= TABLES_COUVERTES
    r = client.get("/api/v1/activity/entities/financements", headers=api_key_headers)
    assert r.status_code == 200, r.text
    assert r.json()["pole"] == "immobilier" and r.json()["count"] >= 1
    item = r.json()["items"][0]
    assert item["entity_type"] == "imm_financement" and item["preteur"] == "Banque Smoke"
    assert "projection" not in item
