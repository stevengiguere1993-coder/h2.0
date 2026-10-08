"""Smoke — lot locatif du 2026-10-08 (rencontre Phil / gestionnaire) :

1. frais de relocation au contrat (400 $ chambre / 600 $ logement) nés du
   BAIL, peu importe la porte ; défauts globaux ; ligne ignorable ;
2. (frais / crédit : fenêtre partagée côté front) crédit possible sur un
   bail terminé pour un mois couvert ;
3. versements du mois distincts dans le suivi des loyers ;
4. suppression d'un locataire parti avec purge explicite ;
5. dépôt gardé : décision à la fin du bail, statuts de la page Dépôts,
   fiche locataire ;
6. TRI : taux d'actualisation persisté, VAN et multiple par horizon.
"""
from __future__ import annotations

import json
from datetime import date

from app.models.immobilier import Immeuble, Locataire, Logement
from app.models.lead_analysis import LeadAnalysis

from tests.smoke.conftest import TestSessionLocal


def _seed(run, *, nom: str, sous_contrat: bool = True, chambres: bool = False) -> dict:
    async def _s() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name=nom, address=f"1 rue {nom}", is_active=True,
                frais_gestion_actif=sous_contrat, frais_gestion_pct=10.0,
                qbo_customer_id="CUST-LOT", qbo_customer_name="Client Lot",
            )
            s.add(imm)
            await s.flush()
            lg = Logement(immeuble_id=imm.id, numero="1", status="vacant", location_en_chambres=chambres)
            lg2 = Logement(immeuble_id=imm.id, numero="2", status="vacant")
            loc = Locataire(full_name=f"Locataire {nom}")
            loc2 = Locataire(full_name=f"Nouveau {nom}")
            s.add_all([lg, lg2, loc, loc2])
            await s.commit()
            return {"immeuble_id": imm.id, "logement_id": lg.id, "logement2_id": lg2.id,
                    "locataire_id": loc.id, "locataire2_id": loc2.id}

    return run(_s())


def _bail(client, headers, logement_id, locataire_id, *, status="actif", debut="2026-01-01",
          fin="2026-12-31", loyer=900, depot=None) -> dict:
    body = {
        "logement_id": logement_id, "locataire_id": locataire_id, "date_debut": debut,
        "date_fin": fin, "loyer_mensuel": loyer, "status": status, "jour_echeance": 1,
    }
    if depot is not None:
        body["depot_garantie"] = depot
    r = client.post("/api/v1/immobilier/baux", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _reloc_tx(client, headers, immeuble_id) -> list:
    ov = client.get("/api/v1/immobilier/frais-gestion", headers=headers).json()
    row = next(r for r in ov["rows"] if r["immeuble_id"] == immeuble_id)
    return [tx for tx in row.get("a_facturer") or [] if tx["type"] == "relocation"], ov


def test_relocation_nee_du_bail_defauts_et_ignorer(client, auth_headers, run):
    seed = _seed(run, nom="Reloc", chambres=True)
    # Bail créé DIRECTEMENT (porte fiche / page Baux) sur une unité en chambres.
    b = _bail(client, auth_headers, seed["logement_id"], seed["locataire_id"])
    txs, ov = _reloc_tx(client, auth_headers, seed["immeuble_id"])
    assert ov["defauts_relocation"] == {"logement": 600.0, "chambre": 400.0}
    assert len(txs) == 1 and txs[0]["montant"] == 400.0 and txs[0]["facturable"] is True
    dossier_id = txs[0]["dossier_id"]
    # Le même locataire qui re-signe sur la même unité : pas une relocation.
    client.patch(f"/api/v1/immobilier/baux/{b['id']}", headers=auth_headers, json={"status": "termine"})
    _bail(client, auth_headers, seed["logement_id"], seed["locataire_id"], debut="2027-01-01", fin="2027-12-31")
    txs, _ = _reloc_tx(client, auth_headers, seed["immeuble_id"])
    assert [tx["dossier_id"] for tx in txs] == [dossier_id]
    # Défauts globaux modifiables (Réglages) → le logement complet suit.
    r = client.patch("/api/v1/immobilier/frais-gestion/defauts", headers=auth_headers, json={"logement": 650})
    assert r.status_code == 200 and r.json()["logement"] == 650.0
    _bail(client, auth_headers, seed["logement2_id"], seed["locataire2_id"])
    txs, _ = _reloc_tx(client, auth_headers, seed["immeuble_id"])
    assert sorted(tx["montant"] for tx in txs) == [400.0, 650.0]
    # Ignorer un frais non approprié → disparaît, ligne « ignorée » dans l'historique.
    r = client.post(f"/api/v1/immobilier/frais-gestion/relocations/{dossier_id}/ignorer", headers=auth_headers)
    assert r.status_code == 200, r.text
    txs, ov = _reloc_tx(client, auth_headers, seed["immeuble_id"])
    assert [tx["montant"] for tx in txs] == [650.0]
    hist = [h for h in ov["historique"] if h["facture_id"] == r.json()["facture_id"]]
    assert hist and hist[0]["ignoree"] is True and hist[0]["montant"] == 0.0
    # La poubelle rétablit la transaction.
    assert client.delete(f"/api/v1/immobilier/frais-gestion/factures/{r.json()['facture_id']}", headers=auth_headers).status_code == 200
    txs, _ = _reloc_tx(client, auth_headers, seed["immeuble_id"])
    assert sorted(tx["montant"] for tx in txs) == [400.0, 650.0]
    client.patch("/api/v1/immobilier/frais-gestion/defauts", headers=auth_headers, json={"logement": 600})


def test_credit_sur_bail_termine_et_versements_distincts(client, auth_headers, run):
    seed = _seed(run, nom="Credit", sous_contrat=False)
    today = date.today()
    mois = today.replace(day=1)
    fin = mois.replace(year=mois.year + 1)
    b = _bail(client, auth_headers, seed["logement_id"], seed["locataire_id"],
              debut=mois.isoformat(), fin=fin.isoformat())
    bid = b["id"]
    # Deux versements partiels sur le mois courant → deux lignes distinctes.
    j1 = mois.replace(day=3).isoformat()
    j2 = mois.replace(day=15).isoformat()
    for montant, quand in ((400, j1), (300, j2)):
        r = client.post("/api/v1/immobilier/paiements", headers=auth_headers,
                        json={"bail_id": bid, "mois_couvert": mois.isoformat(), "montant": montant, "paye_le": quand, "methode": "virement"})
        assert r.status_code in (200, 201), r.text
    ov = client.get(f"/api/v1/immobilier/loyers/overview?mois={mois.strftime('%Y-%m')}", headers=auth_headers).json()
    row = next(r for r in ov["rows"] if r["bail_id"] == bid)
    assert row["etat"] == "partiel" and row["montant_paye"] == 700.0
    assert [(p["montant"], p["paye_le"]) for p in row["paiements"]] == [(400.0, j1), (300.0, j2)]
    # Bail terminé : crédit de règlement sur un mois couvert OK, hors période refusé.
    client.patch(f"/api/v1/immobilier/baux/{bid}", headers=auth_headers, json={"status": "termine"})
    r = client.post(f"/api/v1/immobilier/baux/{bid}/frais", headers=auth_headers,
                    json={"mois_couvert": mois.isoformat(), "montant": -200, "libelle": "Crédit de règlement"})
    assert r.status_code == 201, r.text
    hors = fin.replace(year=fin.year + 1)
    r = client.post(f"/api/v1/immobilier/baux/{bid}/frais", headers=auth_headers,
                    json={"mois_couvert": hors.isoformat(), "montant": -200, "libelle": "Hors bail"})
    assert r.status_code == 400 and "couvert" in r.json()["detail"]


def test_suppression_locataire_parti_avec_purge(client, auth_headers, run):
    seed = _seed(run, nom="Purge", sous_contrat=False)
    b = _bail(client, auth_headers, seed["logement_id"], seed["locataire_id"], debut="2026-01-01", fin="2026-06-30")
    client.post("/api/v1/immobilier/paiements", headers=auth_headers,
                json={"bail_id": b["id"], "mois_couvert": "2026-02-01", "montant": 900, "paye_le": "2026-02-01"})
    lid = seed["locataire_id"]
    # Bail encore actif → refus même avec purge.
    r = client.delete(f"/api/v1/immobilier/locataires/{lid}?force=true&purger=true", headers=auth_headers)
    assert r.status_code == 409 and "ACTIF" in r.json()["detail"]
    client.patch(f"/api/v1/immobilier/baux/{b['id']}", headers=auth_headers, json={"status": "termine"})
    # Parti : force seul → 409 qui propose la purge ; avec purge → supprimé.
    r = client.delete(f"/api/v1/immobilier/locataires/{lid}?force=true", headers=auth_headers)
    assert r.status_code == 409 and "purger=true" in r.json()["detail"]
    r = client.delete(f"/api/v1/immobilier/locataires/{lid}?force=true&purger=true", headers=auth_headers)
    assert r.status_code == 204, r.text
    assert client.get(f"/api/v1/immobilier/locataires/{lid}", headers=auth_headers).status_code == 404


def test_depot_garde_a_la_fin_du_bail_et_page_depots(client, auth_headers, run):
    seed = _seed(run, nom="Depot", sous_contrat=False)
    b = _bail(client, auth_headers, seed["logement_id"], seed["locataire_id"], depot=600)
    bid = b["id"]

    def _row():
        # Filtré sur l'immeuble : les totaux ne mélangent pas les autres tests.
        ov = client.get(
            f"/api/v1/immobilier/depots/overview?immeuble_id={seed['immeuble_id']}",
            headers=auth_headers,
        ).json()
        return next(r for r in ov["rows"] if r["bail_id"] == bid), ov

    row, _ = _row()
    assert row["statut"] == "detenu" and row["montant"] == 600.0
    # Fin immédiate : « il perd son dépôt » (gardé en partie, motif).
    r = client.post(f"/api/v1/immobilier/baux/{bid}/resilier", headers=auth_headers,
                    json={"date_fin": date.today().isoformat(), "ouvrir_relocation": True, "envoyer_avis": False,
                          "depot_decision": "garder", "depot_montant_garde": 400, "depot_motif": "Parti sans préavis"})
    assert r.status_code == 200, r.text
    row, ov = _row()
    assert row["statut"] == "a_rendre" and row["reste_a_rendre"] == 200.0
    assert row["depot_saisi_montant"] == 400.0 and row["depot_saisi_motif"] == "Parti sans préavis"
    assert ov["total_a_rendre"] == 200.0 and ov["total_saisi"] == 400.0
    # Tout garder → statut « saisi », onglet Gardés.
    r = client.patch(f"/api/v1/immobilier/baux/{bid}", headers=auth_headers,
                     json={"depot_saisi_le": date.today().isoformat(), "depot_saisi_montant": 600, "depot_saisi_motif": "Dommages"})
    assert r.status_code == 200, r.text
    row, ov = _row()
    assert row["statut"] == "saisi" and ov["nb_saisi"] >= 1 and ov["total_a_rendre"] == 0.0
    # Fiche locataire : le bail porte la retenue (miroir).
    d = client.get(f"/api/v1/immobilier/locataires/{seed['locataire_id']}/dossier", headers=auth_headers).json()
    bail = next(x for x in d["baux"] if x["id"] == bid)
    assert bail["depot_saisi_montant"] == 600.0 and bail["depot_saisi_motif"] == "Dommages"
    # Annuler la retenue → « à rendre » (le départ est acté).
    r = client.patch(f"/api/v1/immobilier/baux/{bid}", headers=auth_headers,
                     json={"depot_saisi_le": None, "depot_saisi_montant": None, "depot_saisi_motif": None})
    assert r.status_code == 200
    row, _ = _row()
    assert row["statut"] == "a_rendre" and row["reste_a_rendre"] == 600.0
    # « Déjà rendu » à la résiliation d'un autre bail.
    b2 = _bail(client, auth_headers, seed["logement2_id"], seed["locataire2_id"], depot=500)
    r = client.post(f"/api/v1/immobilier/baux/{b2['id']}/resilier", headers=auth_headers,
                    json={"date_fin": date.today().isoformat(), "envoyer_avis": False, "depot_decision": "deja_rendu"})
    assert r.status_code == 200
    ov = client.get(
        f"/api/v1/immobilier/depots/overview?immeuble_id={seed['immeuble_id']}", headers=auth_headers
    ).json()
    assert next(x for x in ov["rows"] if x["bail_id"] == b2["id"])["statut"] == "rendu"


def test_tri_taux_actualisation_et_van(client, auth_headers, run):
    async def _c():
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(
                address="12 rue VAN", city="Montréal", asking_price=1_000_000, nb_logements=8,
                typology_json=json.dumps({"4.5": 8}), revenus_bruts=96_000, taxes_municipales=10_000,
                taxes_scolaires=800, assurances=4_000, energie=0, depenses_autres=0,
                loyers_projetes_json=json.dumps({"4.5": 1400}), taux_interet_refi_pct=4.0, tga_pct=4.0,
                duree_projet_annees=2,
            )
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec.id

    fid = run(_c())
    base = f"/api/v1/lead-analyses/{fid}"
    assert client.post(f"{base}/run-financial-analysis", headers=auth_headers).status_code == 200
    inp = client.get(f"{base}/tri-inputs", headers=auth_headers).json()
    assert "taux_actualisation" in inp["manual_fields"] and inp["inputs"]["taux_actualisation"] == 0.10
    body = {**inp["inputs"], "capital": 300_000.0, "taux_actualisation": 0.08}
    d = client.post(f"{base}/tri", headers=auth_headers, json=body).json()
    assert set(d["van"].keys()) == set(d["tri"].keys()) == set(d["van_projet"].keys())
    assert d["intrants"]["taux_actualisation"] == 0.08
    # VAN = somme actualisée des flux ; multiple = tout ce qui ressort ÷ capital.
    h2 = d["horizons_list"][-1]
    flux = d["flux"][str(h2)]
    van_attendue = sum(cf / (1.08 ** t) for t, cf in enumerate(flux))
    assert abs(d["van"][f"an{h2}"] - van_attendue) < 1e-6
    assert abs(d["multiple"][f"an{h2}"] - sum(flux[1:]) / 300_000.0) < 1e-9
    # Persisté : relu à 8 %.
    assert client.get(f"{base}/tri-inputs", headers=auth_headers).json()["inputs"]["taux_actualisation"] == 0.08
