"""Smoke — suite des retours de Phil du 2026-09-15 : le mois de bascule
d'un transfert est dû une seule fois, un seul bail actif par unité, et
le journal d'audit couvre baux et locataires."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models.immobilier import (
    Bail,
    BailStatus,
    Locataire,
    LogementStatus,
)

from .conftest import TestSessionLocal
from .test_smoke_audit_2026_09_15 import _PDF, TODAY, _mk_immeuble


def test_transfert_mi_mois_le_mois_de_bascule_est_du_une_fois(
    client, auth_headers, run
):
    """Transfert le 15 : l'ancien bail garde son mois entier, le nouveau
    bail ne réclame rien ce mois-là (« Rien dû (bascule) »)."""
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, lg2) = await _mk_immeuble(s, "Audit Bascule")
            marie = Locataire(full_name="Marie Bascule")
            s.add(marie)
            await s.flush()
            b = Bail(
                logement_id=lg1.id, locataire_id=marie.id,
                date_debut=TODAY - timedelta(days=200),
                date_fin=TODAY + timedelta(days=165),
                loyer_mensuel=1100.0, status=BailStatus.ACTIF.value,
            )
            s.add(b)
            lg1.status = LogementStatus.OCCUPE.value
            await s.commit()
            return {"lg2": lg2.id, "bail": b.id}

    ids = run(_seed())
    mois = TODAY.replace(day=1)
    bascule = mois.replace(day=15)
    r = client.post(
        f"/api/v1/immobilier/baux/{ids['bail']}/transferer",
        headers=auth_headers,
        json={
            "nouveau_logement_id": ids["lg2"],
            "date_transfert": str(bascule),
            "loyer_mensuel": 1300.0,
        },
    )
    assert r.status_code == 201, r.text
    nb = r.json()["nouveau_bail_id"]
    rdoc = client.post(
        f"/api/v1/immobilier/baux/{nb}/document", headers=auth_headers,
        files={"file": ("bail.pdf", _PDF, "application/pdf")},
    )
    assert rdoc.status_code in (200, 201), rdoc.text
    ov = client.get(
        f"/api/v1/immobilier/loyers/overview?mois={mois.strftime('%Y-%m')}",
        headers=auth_headers,
    ).json()
    rows = {x["bail_id"]: x for x in ov["rows"] if x.get("bail_id")}
    if bascule > TODAY:
        # Transfert encore à venir ce mois-ci : l'ancien bail réclame
        # son mois entier.
        assert rows[ids["bail"]]["loyer_mensuel"] == 1100.0
    assert rows[nb]["loyer_mensuel"] == 0.0
    assert rows[nb]["transfert_bascule"] is True
    assert rows[nb]["etat"] == "paye"
    # Le mois suivant : le nouveau bail réclame son loyer normalement.
    suivant = (mois + timedelta(days=32)).replace(day=1)
    ov2 = client.get(
        f"/api/v1/immobilier/loyers/overview?mois={suivant.strftime('%Y-%m')}",
        headers=auth_headers,
    ).json()
    row2 = next(x for x in ov2["rows"] if x.get("bail_id") == nb)
    assert row2["loyer_mensuel"] == 1300.0
    assert row2["transfert_bascule"] is False


def test_un_seul_bail_actif_par_unite(client, auth_headers, run):
    """Un bail (proposé ou actif) ne peut pas commencer tant que le
    locataire en place n'est pas parti — sauf en chambres."""
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, lg2) = await _mk_immeuble(s, "Audit UnBail")
            alice = Locataire(full_name="Alice En Place")
            bob = Locataire(full_name="Bob Presse")
            s.add_all([alice, bob])
            await s.flush()
            s.add(Bail(
                logement_id=lg1.id, locataire_id=alice.id,
                date_debut=TODAY - timedelta(days=100),
                date_fin=TODAY + timedelta(days=90),
                loyer_mensuel=1000.0, status=BailStatus.ACTIF.value,
            ))
            lg1.status = LogementStatus.OCCUPE.value
            lg2.location_en_chambres = True
            s.add(Bail(
                logement_id=lg2.id, locataire_id=alice.id,
                date_debut=TODAY - timedelta(days=100),
                date_fin=TODAY + timedelta(days=265),
                loyer_mensuel=500.0, au_mois=True,
                status=BailStatus.ACTIF.value,
            ))
            await s.commit()
            return {"lg1": lg1.id, "lg2": lg2.id, "bob": bob.id}

    ids = run(_seed())
    # Proposé qui chevauche le bail d'Alice → 409 qui dit quoi faire.
    r = client.post(
        "/api/v1/immobilier/baux", headers=auth_headers,
        json={
            "logement_id": ids["lg1"], "locataire_id": ids["bob"],
            "date_debut": str(TODAY + timedelta(days=30)),
            "date_fin": str(TODAY + timedelta(days=395)),
            "loyer_mensuel": 1000, "status": "propose",
        },
    )
    assert r.status_code == 409, r.text
    assert "Alice En Place" in r.text
    assert "un seul bail actif" in r.text.lower()
    # Après son départ (fin du bail) : accepté.
    r = client.post(
        "/api/v1/immobilier/baux", headers=auth_headers,
        json={
            "logement_id": ids["lg1"], "locataire_id": ids["bob"],
            "date_debut": str(TODAY + timedelta(days=91)),
            "date_fin": str(TODAY + timedelta(days=456)),
            "loyer_mensuel": 1000, "status": "propose",
        },
    )
    assert r.status_code in (200, 201), r.text
    bail_bob = r.json()["id"]
    # Déplacer les dates du proposé sur la période d'Alice → 409.
    r = client.patch(
        f"/api/v1/immobilier/baux/{bail_bob}", headers=auth_headers,
        json={"date_debut": str(TODAY + timedelta(days=10))},
    )
    assert r.status_code == 409, r.text
    # Chambres : plusieurs baux cohabitent.
    r = client.post(
        "/api/v1/immobilier/baux", headers=auth_headers,
        json={
            "logement_id": ids["lg2"], "locataire_id": ids["bob"],
            "date_debut": str(TODAY + timedelta(days=1)),
            "date_fin": str(TODAY + timedelta(days=366)),
            "loyer_mensuel": 450, "status": "propose",
        },
    )
    assert r.status_code in (200, 201), r.text


def test_journal_d_audit_des_baux_et_locataires(client, auth_headers, run):
    from app.models.audit_log import AuditLog

    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, lg2) = await _mk_immeuble(s, "Audit Journal")
            await s.commit()
            return {"lg1": lg1.id, "lg2": lg2.id}

    ids = run(_seed())
    r = client.post(
        "/api/v1/immobilier/locataires", headers=auth_headers,
        json={"full_name": "Journal Locataire"},
    )
    loc_id = r.json()["id"]
    client.patch(
        f"/api/v1/immobilier/locataires/{loc_id}", headers=auth_headers,
        json={"phone": "514 555-9999"},
    )
    r = client.post(
        "/api/v1/immobilier/baux", headers=auth_headers,
        json={
            "logement_id": ids["lg1"], "locataire_id": loc_id,
            "date_debut": str(TODAY - timedelta(days=30)),
            "date_fin": str(TODAY + timedelta(days=335)),
            "loyer_mensuel": 900, "status": "actif",
        },
    )
    bail_id = r.json()["id"]
    prochain = (TODAY.replace(day=1) + timedelta(days=40)).replace(day=1)
    r = client.post(
        f"/api/v1/immobilier/baux/{bail_id}/transferer", headers=auth_headers,
        json={
            "nouveau_logement_id": ids["lg2"],
            "date_transfert": str(prochain),
            "loyer_mensuel": 950.0,
        },
    )
    assert r.status_code == 201, r.text
    nb = r.json()["nouveau_bail_id"]
    r = client.post(
        f"/api/v1/immobilier/baux/{nb}/annuler-transfert", headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    async def _actions():
        async with TestSessionLocal() as s:
            rows = (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.action.in_([
                            "locataires.created", "locataires.updated",
                            "baux.created", "baux.transfere",
                            "baux.transfert_annule",
                        ])
                    )
                )
            ).scalars().all()
            return {(row.action, row.entity_id) for row in rows}

    actions = run(_actions())
    assert ("locataires.created", loc_id) in actions
    assert ("locataires.updated", loc_id) in actions
    assert ("baux.created", bail_id) in actions
    assert ("baux.transfere", bail_id) in actions
    assert ("baux.transfert_annule", nb) in actions
