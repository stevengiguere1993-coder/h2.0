"""Smoke — retours partenaires 2026-09-28 (Gestion immobilière) :

- tri NATUREL des numéros de logement (« le 10 se plaçait après le 1 ») ;
- chambres vs logements : un logement loué en chambres compte pour ses
  chambres dans la vue d'ensemble ET la fiche immeuble (mêmes chiffres).
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
from app.services.locatif_chambres import cle_tri_numero, trier_par_numero

from tests.smoke.conftest import TestSessionLocal


def test_cle_tri_naturel():
    nums = ["10", "2", "1", "9", "101-B", "101-A", "A", "04", "3", "b", "11"]
    assert [x for x in sorted(nums, key=cle_tri_numero)] == [
        "1", "2", "3", "04", "9", "10", "11", "101-A", "101-B", "A", "b",
    ]
    assert cle_tri_numero("8906 - C") == cle_tri_numero("8906-c")
    assert cle_tri_numero(None) == cle_tri_numero("")
    assert [d["numero"] for d in trier_par_numero([{"numero": "10"}, {"numero": "9"}])] == ["9", "10"]


def _seed(run):
    async def _s():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Tri Chambres 2026-09-28", address="1 rue Tri",
                city="Montréal", is_active=True,
            )
            s.add(imm)
            await s.flush()
            lgs = {}
            for numero, statut in (
                ("10", LogementStatus.OCCUPE.value),
                ("2", LogementStatus.VACANT.value),
                ("1", LogementStatus.OCCUPE.value),
                ("9", LogementStatus.VACANT.value),
                ("101-A", LogementStatus.VACANT.value),
            ):
                lg = Logement(immeuble_id=imm.id, numero=numero, status=statut)
                s.add(lg)
                lgs[numero] = lg
            # Le « 1 » est loué EN CHAMBRES : 4 chambres, 2 louées.
            lgs["1"].location_en_chambres = True
            lgs["1"].nb_chambres = 4
            await s.flush()
            for nom in ("Chambreur A", "Chambreur B"):
                loc = Locataire(full_name=nom)
                s.add(loc)
                await s.flush()
                s.add(Bail(
                    logement_id=lgs["1"].id, locataire_id=loc.id,
                    status=BailStatus.ACTIF.value, loyer_mensuel=600,
                    au_mois=True, date_debut=date(2026, 1, 1), date_fin=date(2026, 12, 31),
                ))
            loc = Locataire(full_name="Locataire 10")
            s.add(loc)
            await s.flush()
            s.add(Bail(
                logement_id=lgs["10"].id, locataire_id=loc.id,
                status=BailStatus.ACTIF.value, loyer_mensuel=1200,
                date_debut=date(2026, 1, 1), date_fin=date(2026, 12, 31),
            ))
            await s.commit()
            return imm.id

    return run(_s())


def test_liste_logements_ordre_naturel_et_chambres(client, auth_headers, run):
    imm_id = _seed(run)
    r = client.get(f"/api/v1/immobilier/immeubles/{imm_id}/logements", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert [l["numero"] for l in r.json()] == ["1", "2", "9", "10", "101-A"]

    # Vue d'ensemble du pôle : 5 portes, 2 occupées ; 1 logement en
    # chambres = 4 chambres dont 2 occupées.
    r = client.get("/api/v1/immobilier/immeubles", headers=auth_headers)
    assert r.status_code == 200, r.text
    item = next(x for x in r.json() if x["id"] == imm_id)
    assert item["nb_logements_actifs"] == 5
    assert item["nb_logements_occupes"] == 2
    assert item["nb_logements_en_chambres"] == 1
    assert item["nb_chambres"] == 4
    assert item["nb_chambres_occupees"] == 2

    # Fiche immeuble : EXACTEMENT les mêmes chiffres (sections miroir).
    r = client.get(f"/api/v1/immobilier/immeubles/{imm_id}/financials", headers=auth_headers)
    assert r.status_code == 200, r.text
    f = r.json()
    assert (f["nb_logements_en_chambres"], f["nb_chambres"], f["nb_chambres_occupees"]) == (1, 4, 2)
    assert (f["nb_logements_actifs"], f["nb_logements_occupes"]) == (5, 2)
