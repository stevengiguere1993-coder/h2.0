"""Smoke — frais manuels de gestion PERSISTÉS (retour Phil 2026-08-10).

Avant : brouillons 100 % côté client → perdus en quittant la page.
Maintenant : POST /frais-manuels les stocke ; l'overview les re-sert
(type 'manuel', uid = id BD) jusqu'à facturation ou suppression.
"""
from __future__ import annotations

import pytest

from app.models.immobilier import Immeuble

from .conftest import TestSessionLocal


@pytest.fixture(scope="module")
def fm_seed(run, seeded_users) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Smoke FraisManuels",
                address="12 rue Gestion",
                is_active=True,
                frais_gestion_actif=True,
                frais_gestion_pct=10.0,
                qbo_customer_id="CUST-1",
                qbo_customer_name="Client Smoke",
            )
            s.add(imm)
            await s.commit()
            return {"immeuble_id": imm.id}

    return run(_seed())


def _row(overview: dict, immeuble_id: int) -> dict:
    return next(
        r for r in overview["rows"] if r["immeuble_id"] == immeuble_id
    )


def test_frais_manuel_persiste_puis_supprime(client, auth_headers, fm_seed):
    r = client.post(
        "/api/v1/immobilier/frais-gestion/frais-manuels",
        headers=auth_headers,
        json={
            "immeuble_id": fm_seed["immeuble_id"],
            "libelle": "Déplacement d'urgence",
            "montant": 75.5,
        },
    )
    assert r.status_code == 200, r.text
    fid = r.json()["id"]

    # « Retour sur la page » : l'overview re-sert le frais — il a survécu
    # au rechargement (c'était le bug).
    ov = client.get(
        "/api/v1/immobilier/frais-gestion", headers=auth_headers
    ).json()
    row = _row(ov, fm_seed["immeuble_id"])
    manuels = [t for t in row["a_facturer"] if t["type"] == "manuel"]
    assert len(manuels) == 1
    tx = manuels[0]
    assert tx["uid"] == fid
    assert tx["label"] == "Déplacement d'urgence"
    assert tx["montant"] == 75.5
    assert tx["facturable"] is True
    assert row["solde"] >= 75.5

    d = client.delete(
        f"/api/v1/immobilier/frais-gestion/frais-manuels/{fid}",
        headers=auth_headers,
    )
    assert d.status_code == 200, d.text

    ov2 = client.get(
        "/api/v1/immobilier/frais-gestion", headers=auth_headers
    ).json()
    row2 = _row(ov2, fm_seed["immeuble_id"])
    assert not [t for t in row2["a_facturer"] if t["type"] == "manuel"]


def test_frais_manuel_immeuble_inconnu(client, auth_headers):
    r = client.post(
        "/api/v1/immobilier/frais-gestion/frais-manuels",
        headers=auth_headers,
        json={"immeuble_id": 999999, "libelle": "X", "montant": 5},
    )
    assert r.status_code == 404
