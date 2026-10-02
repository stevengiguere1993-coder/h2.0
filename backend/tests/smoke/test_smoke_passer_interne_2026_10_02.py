"""Smoke — bascule gestion externe → interne (Phil 2026-10-02 : « mon
partner a créé un immeuble en gestion externe par erreur … Repasser en
gestion interne exige un bail pour chaque unité occupée »). L'assistant
liste les unités occupées sans bail (préremplies), crée les baux d'un
coup, libère les unités décochées et bascule l'immeuble — tout ou rien."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
)

from tests.smoke.conftest import TestSessionLocal


def _seed(run) -> dict:
    async def _go():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Externe par erreur", address="99 rue de la Bascule",
                city="Montréal", is_active=True, gestion_externe=True,
                gestionnaire_externe_nom="Vailla",
            )
            s.add(imm)
            await s.flush()
            lgs = [
                Logement(immeuble_id=imm.id, numero="3", status=LogementStatus.OCCUPE.value,
                         locataire_externe_nom="Bruno Christofaro",
                         locataire_externe_depuis=date(2025, 7, 1), loyer_demande=950),
                Logement(immeuble_id=imm.id, numero="5", status=LogementStatus.OCCUPE.value,
                         locataire_externe_nom="Marina Noumoav"),
                Logement(immeuble_id=imm.id, numero="9", status=LogementStatus.OCCUPE.value),
                Logement(immeuble_id=imm.id, numero="10", status=LogementStatus.VACANT.value),
            ]
            s.add_all(lgs)
            await s.commit()
            return {"imm": imm.id, "lg": {lg.numero: lg.id for lg in lgs}}

    return run(_go())


def test_bascule_refusee_puis_assistant(client, auth_headers, run):
    ids = _seed(run)
    base = f"/api/v1/immobilier/immeubles/{ids['imm']}"

    # 1. La bascule directe est refusée et nomme les unités.
    r = client.patch(base, headers=auth_headers, json={"gestion_externe": False})
    assert r.status_code == 409, r.text
    assert "3 (Bruno Christofaro)" in r.text and "5 (Marina Noumoav)" in r.text
    assert "assistant" in r.text

    # 2. L'assistant liste les unités occupées sans bail, préremplies.
    r = client.get(f"{base}/unites-sans-bail", headers=auth_headers)
    assert r.status_code == 200, r.text
    unites = r.json()
    assert [u["numero"] for u in unites] == ["3", "5", "9"]
    assert unites[0]["locataire_externe_nom"] == "Bruno Christofaro"
    assert unites[0]["locataire_externe_depuis"] == "2025-07-01"
    assert unites[0]["loyer_demande"] == 950.0
    assert unites[2]["locataire_externe_nom"] is None

    today = date.today()
    fin = date(today.year + 1, 6, 30)
    baux = [
        {"logement_id": ids["lg"]["3"], "locataire_nom": "Bruno Christofaro",
         "loyer_mensuel": 950, "date_debut": "2025-07-01", "date_fin": str(fin)},
        {"logement_id": ids["lg"]["5"], "locataire_nom": "Marina Noumoav",
         "loyer_mensuel": 1100, "date_debut": str(today.replace(day=1)),
         "date_fin": str(fin), "jour_echeance": 1},
    ]

    # 3. Tout ou rien : l'unité 9 reste occupée sans bail → refus, rien
    #    n'est enregistré (l'immeuble reste externe, aucun bail créé).
    r = client.post(f"{base}/passer-interne", headers=auth_headers,
                    json={"baux": baux, "liberer_logement_ids": []})
    assert r.status_code == 409, r.text
    assert "9" in r.text
    r = client.get(base, headers=auth_headers)
    assert r.json()["gestion_externe"] is True

    async def _nb_baux():
        async with TestSessionLocal() as s:
            return len((await s.execute(
                select(Bail).where(Bail.logement_id.in_(list(ids["lg"].values())))
            )).scalars().all())

    assert run(_nb_baux()) == 0

    # 4. Baux pour 3 et 5, unité 9 libérée → bascule.
    r = client.post(f"{base}/passer-interne", headers=auth_headers,
                    json={"baux": baux, "liberer_logement_ids": [ids["lg"]["9"]]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["immeuble"]["gestion_externe"] is False
    assert d["baux_crees"] == 2 and d["locataires_crees"] == 2 and d["logements_liberes"] == 1

    async def _apres():
        async with TestSessionLocal() as s:
            imm = await s.get(Immeuble, ids["imm"])
            lg3 = await s.get(Logement, ids["lg"]["3"])
            lg9 = await s.get(Logement, ids["lg"]["9"])
            baux_ = (await s.execute(
                select(Bail).where(Bail.logement_id.in_([ids["lg"]["3"], ids["lg"]["5"]]))
            )).scalars().all()
            noms = []
            for b in baux_:
                loc = await s.get(Locataire, b.locataire_id)
                noms.append((b.logement_id, loc.full_name, float(b.loyer_mensuel), b.status))
            return imm, lg3, lg9, sorted(noms)

    imm, lg3, lg9, noms = run(_apres())
    assert imm.gestion_externe is False and imm.gestionnaire_externe_nom is None
    assert lg3.status == LogementStatus.OCCUPE.value and lg3.locataire_externe_nom is None
    assert lg9.status == LogementStatus.VACANT.value and lg9.locataire_externe_nom is None
    assert noms == sorted([
        (ids["lg"]["3"], "Bruno Christofaro", 950.0, BailStatus.ACTIF.value),
        (ids["lg"]["5"], "Marina Noumoav", 1100.0, BailStatus.ACTIF.value),
    ])

    # 5. Déjà interne → refus explicite.
    r = client.post(f"{base}/passer-interne", headers=auth_headers, json={"baux": []})
    assert r.status_code == 409
