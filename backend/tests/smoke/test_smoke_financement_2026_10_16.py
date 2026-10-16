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
    assert b["type_label"] == "Bail principal (exploitant)"

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
    assert pars[IDS["b103"]]["loyer"] == 1475 and pars[IDS["b103"]]["type_label"] == "Bail principal (exploitant)"
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
    # Projection de départ = loyers des baux (source « bail »), loyer demandé sinon.
    proj = d["projection"]["logements"]
    assert proj[str(fin_seed["l101"])] == {"loyer": 1000, "source": "bail", "note": ""}
    assert proj[str(fin_seed["l102"])]["source"] == "demande" and proj[str(fin_seed["l102"])]["loyer"] == 950
    tb = d["tableau_de_bord"]
    assert tb["reel_mensuel"] == 1000 and tb["paralleles_mensuel"] == 2775 and tb["pieces_fournies"] == 0
    assert tb["jours_avant_echeance"] in (44, 45) and len(tb["pieces_manquantes"]) == tb["pieces_requises"]
    assert d["journal"][0]["type"] == "statut"
    # Le rent roll du dossier porte la colonne projection (séparée, marquée).
    rr = d["rent_roll"]
    assert rr["projection"] is not None and {l["numero"]: l["projection"]["source"] for l in rr["lignes"]}["101"] == "bail"
    assert rr["totaux"]["projection_mensuelle"] == 1000 + 950 + 1400

    # Projection manuelle + vacance.
    r = client.put(f"{FIN}/dossiers/{d['id']}/projection", headers=auth_headers, json={
        "logements": {str(fin_seed["l101"]): {"loyer": 1200, "source": "manuel", "note": "après rénovation"},
                      str(fin_seed["l102"]): {"loyer": 1000, "source": "marche"}},
        "hypotheses": {"vacance_pct": 3},
    })
    assert r.status_code == 200, r.text
    tb = r.json()["tableau_de_bord"]
    assert tb["projection_mensuelle"] == 1200 + 1000 + 1400 and tb["ecart_projection_pct"] == 260.0
    assert tb["projection_annuelle"] == round(3600 * 12 * 0.97, 2)
    assert client.put(f"{FIN}/dossiers/{d['id']}/projection", headers=auth_headers, json={"logements": {"1": {"loyer": -5}}}).status_code == 422
    # L'export du dossier a la colonne projection, en PDF aussi.
    r = client.get(f"{FIN}/dossiers/{d['id']}/rent-roll", headers=auth_headers, params={"fmt": "csv"})
    assert r.status_code == 200 and "Projection — loyer (estimation)" in r.content.decode("utf-8-sig")
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
