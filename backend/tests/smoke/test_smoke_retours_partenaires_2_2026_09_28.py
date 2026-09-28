"""Smoke — retours partenaires 2026-09-28, 2e livraison :

4. création de PLUSIEURS logements d'un coup (doublons ignorés, valeurs
   communes, ordre naturel) ;
6. DÉBUT DE LA COLLECTE des loyers par immeuble : avant cette date, rien
   n'est attendu ni en retard, et le solde cumulé repart de là.
"""
from __future__ import annotations

from datetime import date

from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
)

from tests.smoke.conftest import TestSessionLocal


def _premier_du_mois_relatif(base: date, delta_mois: int) -> date:
    m = base.month - 1 + delta_mois
    return date(base.year + m // 12, m % 12 + 1, 1)


def test_creer_logements_en_lot(client, auth_headers, run):
    async def _imm():
        async with TestSessionLocal() as s:
            imm = Immeuble(name="Lot 2026-09-28", address="1 rue Lot", city="Montréal", is_active=True)
            s.add(imm)
            await s.flush()
            s.add(Logement(immeuble_id=imm.id, numero="3", status=LogementStatus.VACANT.value))
            await s.commit()
            return imm.id

    imm_id = run(_imm())
    r = client.post(
        f"/api/v1/immobilier/immeubles/{imm_id}/logements/lot",
        headers=auth_headers,
        json={
            "numeros": ["1", "2", "3", "10", " 2 ", "", "03"],
            "modele": {"nb_pieces_decimal": 4.5, "type": "residentiel", "etage": 1},
        },
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert [l["numero"] for l in d["crees"]] == ["1", "2", "10"], "ordre naturel, doublons écartés"
    assert d["ignores"] == ["3", "2", "03"], "déjà présent, doublon de liste, « 03 » = « 3 »"
    assert all(l["nb_pieces_decimal"] == 4.5 and l["etage"] == 1 for l in d["crees"])
    assert all(l["status"] == "vacant" for l in d["crees"])
    # La liste de l'immeuble : 1, 2, 3, 10.
    r2 = client.get(f"/api/v1/immobilier/immeubles/{imm_id}/logements", headers=auth_headers)
    assert [l["numero"] for l in r2.json()] == ["1", "2", "3", "10"]
    # Rien de fourni → 422.
    assert client.post(
        f"/api/v1/immobilier/immeubles/{imm_id}/logements/lot",
        headers=auth_headers, json={"numeros": [" "]},
    ).status_code == 422


def test_debut_de_collecte_par_immeuble(client, auth_headers, run):
    """Bail actif depuis 8 mois, collecte réglée au 1er du mois DERNIER :
    le mois d'avant n'a aucune ligne (ni retard ni vacant) ; le mois
    courant a une ligne dont le solde cumule 2 mois, pas 8."""
    today = date.today()
    collecte = _premier_du_mois_relatif(today, -1)
    avant = _premier_du_mois_relatif(today, -2)
    debut_bail = _premier_du_mois_relatif(today, -8)

    async def _seed():
        async with TestSessionLocal() as s:
            imm = Immeuble(name="Collecte 6646", address="6646 rue Érables", city="Montréal", is_active=True)
            s.add(imm)
            await s.flush()
            lg = Logement(immeuble_id=imm.id, numero="1", status=LogementStatus.OCCUPE.value)
            vac = Logement(immeuble_id=imm.id, numero="2", status=LogementStatus.VACANT.value)
            loc = Locataire(full_name="Locataire Collecte")
            s.add_all([lg, vac, loc])
            await s.flush()
            s.add(Bail(
                logement_id=lg.id, locataire_id=loc.id, status=BailStatus.ACTIF.value,
                loyer_mensuel=1000, date_debut=debut_bail,
                date_fin=_premier_du_mois_relatif(today, 12),
            ))
            await s.commit()
            return imm.id, lg.id

    imm_id, lg_id = run(_seed())

    # Réglage via l'API : le 15 du mois est ramené au 1er.
    r = client.patch(
        f"/api/v1/immobilier/immeubles/{imm_id}",
        headers=auth_headers, json={"collecte_depuis": collecte.replace(day=15).isoformat()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["collecte_depuis"] == collecte.isoformat()

    def _rows(mois: date):
        rr = client.get(
            f"/api/v1/immobilier/loyers/overview?mois={mois.strftime('%Y-%m')}",
            headers=auth_headers,
        )
        assert rr.status_code == 200, rr.text
        return [x for x in rr.json()["rows"] if x["immeuble_id"] == imm_id]

    # Mois AVANT la collecte : aucune ligne pour cet immeuble.
    assert _rows(avant) == []
    # Mois courant : une ligne pour le bail, solde = 2 mois (mois dernier
    # + mois courant), pas 8 ; le logement vacant apparaît aussi.
    rows = _rows(today.replace(day=1))
    bail_rows = [x for x in rows if x["bail_id"]]
    assert len(bail_rows) == 1
    assert bail_rows[0]["solde_total"] == 2000.0
    assert bail_rows[0]["etat"] in ("retard", "attente")
    assert any(x["etat"] == "vacant" for x in rows)

    # Sans réglage : le solde remonte plus loin (jusqu'au démarrage global
    # du pôle ou au début du bail) — donc strictement plus que 2 mois.
    r = client.patch(
        f"/api/v1/immobilier/immeubles/{imm_id}", headers=auth_headers,
        json={"collecte_depuis": None},
    )
    assert r.status_code == 200 and r.json()["collecte_depuis"] is None
    rows = _rows(today.replace(day=1))
    bail_rows = [x for x in rows if x["bail_id"]]
    assert bail_rows[0]["solde_total"] > 2000.0
