"""Smoke — lot de bugs du 2026-10-18 (gestion locative, mvilliard) :

- bug 4 : « je ne peux changer les montants perçus et percevable » →
  versement corrigé EN PLACE (PATCH /paiements/{id}) et loyer DÛ du mois
  fixé à la main (PUT /baux/{id}/loyer-mois) ;
- bugs 5 et 6 : versements partiels distincts, datés, corrigeables, et
  « pouvoir dire qu'ils ne sont pas en retard » (en_retard tranché) ;
- bug 10 : rabais de 500 $ sur les 3 premiers mois d'un bail à 1 500 $.
"""
from __future__ import annotations

from datetime import date

from app.models.immobilier import Immeuble, Locataire, Logement

from tests.smoke.conftest import TestSessionLocal


def _mois(d: date, delta: int) -> date:
    m = d.month - 1 + delta
    return date(d.year + m // 12, m % 12 + 1, 1)


def _seed(run, *, nom: str) -> dict:
    async def _s() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(name=nom, address=f"1 rue {nom}", is_active=True)
            s.add(imm)
            await s.flush()
            lg = Logement(immeuble_id=imm.id, numero="1", status="vacant")
            loc = Locataire(full_name=f"Locataire {nom}")
            s.add_all([lg, loc])
            await s.commit()
            return {"immeuble_id": imm.id, "logement_id": lg.id, "locataire_id": loc.id}

    return run(_s())


def _bail(client, headers, seed, *, debut: date, loyer: float, **extra) -> dict:
    body = {
        "logement_id": seed["logement_id"], "locataire_id": seed["locataire_id"],
        "date_debut": debut.isoformat(), "date_fin": _mois(debut, 12).isoformat(),
        "loyer_mensuel": loyer, "status": "actif", "jour_echeance": 1, **extra,
    }
    r = client.post("/api/v1/immobilier/baux", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _row(client, headers, bail_id: int, mois: date) -> dict:
    r = client.get(f"/api/v1/immobilier/loyers/overview?mois={mois.strftime('%Y-%m')}", headers=headers)
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["rows"] if x["bail_id"] == bail_id)


def _payer(client, headers, bail_id: int, mois: date, montant: float, paye_le: date) -> dict:
    r = client.post("/api/v1/immobilier/paiements", headers=headers, json={
        "bail_id": bail_id, "mois_couvert": mois.isoformat(), "montant": montant,
        "paye_le": paye_le.isoformat(), "methode": "Interac",
    })
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_versements_partiels_corriges_en_place(client, auth_headers, run):
    seed = _seed(run, nom="Versements")
    today = date.today()
    m0 = today.replace(day=1)
    m_1 = _mois(m0, -1)
    b = _bail(client, auth_headers, seed, debut=m_1, loyer=930)
    bid = b["id"]
    # Patrick et Thérèse : 465 $ puis 465 $ — deux dépôts datés distincts.
    p1 = _payer(client, auth_headers, bid, m_1, 465, m_1)
    p2 = _payer(client, auth_headers, bid, m_1, 465, m_1.replace(day=20))
    assert p1["cree_par"] and p2["cree_par"]
    row = _row(client, auth_headers, bid, m_1)
    assert row["etat"] == "paye" and row["montant_paye"] == 930.0
    assert [(p["montant"], p["paye_le"]) for p in row["paiements"]] == [
        (465.0, m_1.isoformat()), (465.0, m_1.replace(day=20).isoformat()),
    ]
    # Le 2e dépôt, reçu le 20, est calculé « en retard »…
    assert row["paiements"][1]["en_retard"] is True
    # …et on peut trancher qu'il ne l'est pas (entente) — la trace reste.
    r = client.patch(f"/api/v1/immobilier/paiements/{p2['id']}", headers=auth_headers,
                     json={"en_retard": False})
    assert r.status_code == 200, r.text
    assert r.json()["en_retard"] is False and r.json()["modifie_par"]
    # Corriger le MONTANT seul ne ré-évalue pas le retard tranché.
    r = client.patch(f"/api/v1/immobilier/paiements/{p2['id']}", headers=auth_headers,
                     json={"montant": 400})
    assert r.status_code == 200 and r.json()["en_retard"] is False
    row = _row(client, auth_headers, bid, m_1)
    assert row["etat"] == "partiel" and row["montant_paye"] == 865.0
    assert row["paiements"][1]["modifie_par"] and row["paiements"][1]["en_retard"] is False
    # La fiche locataire montre les deux versements, la trace et le retard.
    dossier = client.get(f"/api/v1/immobilier/locataires/{seed['locataire_id']}/dossier",
                         headers=auth_headers).json()
    pmts = {p["id"]: p for p in dossier["paiements"]}
    assert pmts[p2["id"]]["montant"] == 400.0 and pmts[p2["id"]]["modifie_par"]
    assert dossier["nb_retards"] == 0
    # Changer la DATE recalcule le retard (reçu le 1er → à temps).
    r = client.patch(f"/api/v1/immobilier/paiements/{p2['id']}", headers=auth_headers,
                     json={"paye_le": m_1.isoformat(), "montant": 465})
    assert r.status_code == 200 and r.json()["en_retard"] is False
    # Un versement imputé au mauvais mois se déplace.
    r = client.patch(f"/api/v1/immobilier/paiements/{p2['id']}", headers=auth_headers,
                     json={"mois_couvert": m0.isoformat()})
    assert r.status_code == 200 and r.json()["mois_couvert"] == m0.isoformat()
    assert _row(client, auth_headers, bid, m_1)["montant_paye"] == 465.0
    assert _row(client, auth_headers, bid, m0)["montant_paye"] == 465.0
    # Supprimer UN versement (pas tout le mois).
    r = client.delete(f"/api/v1/immobilier/paiements/{p2['id']}", headers=auth_headers)
    assert r.status_code == 204
    assert _row(client, auth_headers, bid, m0)["paiements"] == []
    assert len(_row(client, auth_headers, bid, m_1)["paiements"]) == 1
    # Garde-fous.
    assert client.patch(f"/api/v1/immobilier/paiements/{p1['id']}", headers=auth_headers,
                        json={"montant": 0}).status_code == 422
    assert client.patch("/api/v1/immobilier/paiements/999999", headers=auth_headers,
                        json={"montant": 10}).status_code == 404


def test_loyer_du_du_mois_fixe_a_la_main(client, auth_headers, run):
    seed = _seed(run, nom="DuMois")
    m0 = date.today().replace(day=1)
    m_2 = _mois(m0, -2)
    b = _bail(client, auth_headers, seed, debut=m_2, loyer=900)
    bid = b["id"]
    url = f"/api/v1/immobilier/baux/{bid}/loyer-mois"
    # Demi-mois : le dû du mois passe à 405 $, le loyer du bail ne bouge pas.
    r = client.put(url, headers=auth_headers, json={"mois": m_2.strftime("%Y-%m"), "montant_du": 405})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["du_mois"] == 405.0 and out["ajustement"]["montant"] == -495.0
    assert out["ajustement"]["origine"] == "ajustement_mois"
    row = _row(client, auth_headers, bid, m_2)
    assert row["loyer_mensuel"] == 900.0
    assert [(f["montant"], f["origine"]) for f in row["frais_mois"]] == [(-495.0, "ajustement_mois")]
    # Refixer remplace la ligne (jamais deux ajustements sur le mois).
    r = client.put(url, headers=auth_headers, json={"mois": m_2.strftime("%Y-%m"), "montant_du": 450, "motif": "Entente"})
    assert r.status_code == 200 and r.json()["du_mois"] == 450.0
    row = _row(client, auth_headers, bid, m_2)
    assert [(f["montant"], f["libelle"]) for f in row["frais_mois"]] == [(-450.0, "Entente")]
    # Payer le dû fixé solde le mois.
    _payer(client, auth_headers, bid, m_2, 450, m_2)
    assert _row(client, auth_headers, bid, m_2)["etat"] == "paye"
    # Revenir au loyer du bail retire la ligne.
    r = client.put(url, headers=auth_headers, json={"mois": m_2.strftime("%Y-%m"), "montant_du": 900})
    assert r.status_code == 200 and r.json()["ajustement"] is None
    assert _row(client, auth_headers, bid, m_2)["frais_mois"] == []
    # Avec un frais du mois (+20), l'ajustement compense pour tomber pile.
    m_1 = _mois(m0, -1)
    r = client.post(f"/api/v1/immobilier/baux/{bid}/frais", headers=auth_headers,
                    json={"mois_couvert": m_1.isoformat(), "montant": 20, "libelle": "Frais de retard"})
    assert r.status_code == 201, r.text
    r = client.put(url, headers=auth_headers, json={"mois": m_1.strftime("%Y-%m"), "montant_du": 500})
    assert r.status_code == 200 and r.json()["du_mois"] == 500.0
    assert r.json()["ajustement"]["montant"] == -420.0
    # L'ajustement se retire aussi comme une ligne ordinaire.
    aj_id = r.json()["ajustement"]["id"]
    assert client.delete(f"/api/v1/immobilier/frais/{aj_id}", headers=auth_headers).status_code == 204
    # Garde-fous.
    assert client.put(url, headers=auth_headers, json={"mois": "2026/07", "montant_du": 1}).status_code == 400
    assert client.put("/api/v1/immobilier/baux/999999/loyer-mois", headers=auth_headers,
                      json={"mois": m0.strftime("%Y-%m"), "montant_du": 1}).status_code == 404
    # La fiche locataire montre les lignes des mois dans son historique.
    dossier = client.get(f"/api/v1/immobilier/locataires/{seed['locataire_id']}/dossier",
                         headers=auth_headers).json()
    assert [f["libelle"] for f in dossier["frais"]] == ["Frais de retard"]


def test_rabais_sur_les_premiers_mois(client, auth_headers, run):
    seed = _seed(run, nom="Rabais")
    m0 = date.today().replace(day=1)
    m_1 = _mois(m0, -1)
    # « Rabais de 500 $ pour les 3 premiers mois, ensuite 1 500 $ / mois. »
    b = _bail(client, auth_headers, seed, debut=m_1, loyer=1500,
              rabais_mensuel=500, rabais_nb_mois=3)
    bid = b["id"]
    assert b["rabais_mensuel"] == 500.0 and b["rabais_nb_mois"] == 3
    for i, m in enumerate((m_1, m0, _mois(m0, 1)), start=1):
        row = _row(client, auth_headers, bid, m)
        assert [(f["montant"], f["origine"], f["libelle"]) for f in row["frais_mois"]] == [
            (-500.0, "rabais_bail", f"Rabais de loyer ({i}/3)")
        ], (m, row["frais_mois"])
    # 4e mois : loyer plein.
    assert _row(client, auth_headers, bid, _mois(m0, 2))["frais_mois"] == []
    # Solde au mois courant : 2 × (1 500 − 500) — le rabais d'un mois
    # FUTUR ne réduit pas le solde d'aujourd'hui.
    assert _row(client, auth_headers, bid, m0)["solde_total"] == 2000.0
    # Un versement de 3 000 $ couvre les trois mois au loyer réduit.
    _payer(client, auth_headers, bid, m_1, 3000, m_1)
    for m in (m_1, m0, _mois(m0, 1)):
        row = _row(client, auth_headers, bid, m)
        assert row["etat"] == "paye" and row["montant_paye"] == 1000.0, (m, row)
    assert _row(client, auth_headers, bid, m0)["solde_total"] == 0.0
    # Le crédit du rabais ne se retire pas comme un frais : il vit sur le bail.
    rabais_id = _row(client, auth_headers, bid, m_1)["frais_mois"][0]["id"]
    r = client.delete(f"/api/v1/immobilier/frais/{rabais_id}", headers=auth_headers)
    assert r.status_code == 409 and "bail" in r.json()["detail"]
    # Changer le rabais sur le bail régénère les crédits.
    r = client.patch(f"/api/v1/immobilier/baux/{bid}", headers=auth_headers,
                     json={"rabais_mensuel": 400, "rabais_nb_mois": 2, "rabais_motif": "Promo signature"})
    assert r.status_code == 200, r.text
    assert [(f["montant"], f["libelle"]) for f in _row(client, auth_headers, bid, m0)["frais_mois"]] == [
        (-400.0, "Promo signature (2/2)")
    ]
    assert _row(client, auth_headers, bid, _mois(m0, 1))["frais_mois"] == []
    # Exposé partout : tableau des baux, fiche locataire, fiche logement.
    suivi = client.get(f"/api/v1/immobilier/suivi-baux?logement_id={seed['logement_id']}",
                       headers=auth_headers).json()
    srow = next(x for x in suivi if x["bail_id"] == bid)
    assert srow["rabais_mensuel"] == 400.0 and srow["rabais_nb_mois"] == 2
    dossier = client.get(f"/api/v1/immobilier/locataires/{seed['locataire_id']}/dossier",
                         headers=auth_headers).json()
    dbail = next(x for x in dossier["baux"] if x["id"] == bid)
    assert dbail["rabais_mensuel"] == 400.0 and dbail["rabais_motif"] == "Promo signature"
    assert sorted(f["origine"] for f in dossier["frais"]) == ["rabais_bail", "rabais_bail"]
    lg = client.get(f"/api/v1/immobilier/logements/{seed['logement_id']}/dossier",
                    headers=auth_headers).json()
    assert any(x.get("rabais_nb_mois") == 2 for x in lg.get("baux", []) + [lg.get("bail_actif") or {}])
    # Retirer le rabais efface ses crédits.
    r = client.patch(f"/api/v1/immobilier/baux/{bid}", headers=auth_headers, json={"rabais_mensuel": None})
    assert r.status_code == 200 and r.json()["rabais_mensuel"] is None and r.json()["rabais_nb_mois"] is None
    for m in (m_1, m0):
        assert _row(client, auth_headers, bid, m)["frais_mois"] == []


def test_rabais_suit_le_debut_du_bail(client, auth_headers, run):
    seed = _seed(run, nom="RabaisDebut")
    m0 = date.today().replace(day=1)
    b = _bail(client, auth_headers, seed, debut=_mois(m0, -3), loyer=1200,
              rabais_mensuel=100, rabais_nb_mois=1)
    bid = b["id"]
    assert _row(client, auth_headers, bid, _mois(m0, -3))["frais_mois"][0]["montant"] == -100.0
    # Sans « premier mois » explicite, le rabais suit la date de début.
    r = client.patch(f"/api/v1/immobilier/baux/{bid}", headers=auth_headers,
                     json={"date_debut": _mois(m0, -2).isoformat()})
    assert r.status_code == 200, r.text
    assert _row(client, auth_headers, bid, _mois(m0, -2))["frais_mois"][0]["montant"] == -100.0
    # Premier mois explicite : il prime.
    r = client.patch(f"/api/v1/immobilier/baux/{bid}", headers=auth_headers,
                     json={"rabais_debut": m0.isoformat()})
    assert r.status_code == 200, r.text
    assert _row(client, auth_headers, bid, _mois(m0, -2))["frais_mois"] == []
    assert _row(client, auth_headers, bid, m0)["frais_mois"][0]["montant"] == -100.0
