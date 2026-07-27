"""Smoke — DÉMARRAGE de la gestion locative (2026-07-27).

Retour Phil : « je commence pour vrai — tout ce qui est avant le
1er juillet 2026 ne doit plus être vrai ». Un locataire qui traînait des
mois impayés AVANT la date repart à 0 $.

Vérifie que la date est un vrai réglage (pas une constante) et qu'elle
borne réellement l'argent : solde cumulatif de la vue Loyers, historique
de paiements du bail, et fiche locataire.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
    PaiementLoyer,
)
from app.services.locatif_demarrage import (
    DEFAULT_DEMARRAGE,
    parse_demarrage,
)

from .conftest import TestSessionLocal


def _mois(d: date, delta: int) -> date:
    """1er du mois, décalé de ``delta`` mois."""
    y, m = d.year, d.month + delta
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return date(y, m, 1)


@pytest.fixture(scope="module")
def bail_seed(run, seeded_users) -> dict:
    """1 bail actif de 1 000 $/mois commencé il y a 6 mois, AUCUN paiement :
    tous les mois échus sont donc dus."""

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Smoke Démarrage",
                address="1 rue Reset",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id,
                numero="101",
                status=LogementStatus.OCCUPE.value,
            )
            loc = Locataire(full_name="Rémi Reset")
            s.add_all([lg, loc])
            await s.flush()
            debut = _mois(datetime.now(timezone.utc).date(), -6)
            bail = Bail(
                logement_id=lg.id,
                locataire_id=loc.id,
                date_debut=debut,
                date_fin=debut + timedelta(days=365),
                loyer_mensuel=1000.0,
                status=BailStatus.ACTIF.value,
            )
            s.add(bail)
            await s.flush()
            # Un paiement d'un vieux mois (avant tout démarrage récent) :
            # il ne doit PAS compter quand la date de démarrage est après.
            s.add(
                PaiementLoyer(
                    bail_id=bail.id,
                    mois_couvert=debut,
                    montant=1000.0,
                    paye_le=debut,
                    created_at=datetime.now(timezone.utc),
                )
            )
            await s.commit()
            return {
                "immeuble_id": imm.id,
                "bail_id": bail.id,
                "locataire_id": loc.id,
                "debut": debut,
            }

    return run(_seed())


def _set_demarrage(client, headers, d: date) -> None:
    resp = client.put(
        "/api/v1/immobilier/demarrage",
        headers=headers,
        json={"date": d.isoformat()},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["date"] == d.replace(day=1).isoformat()


# ── Le réglage lui-même ────────────────────────────────────────────────


def test_parse_demarrage_defaut_et_normalisation():
    assert parse_demarrage({}) == DEFAULT_DEMARRAGE
    assert parse_demarrage({"date": "zzz"}) == DEFAULT_DEMARRAGE
    # Toute date est ramenée au 1er du mois.
    assert parse_demarrage({"date": "2027-03-17"}) == date(2027, 3, 1)


def test_demarrage_par_defaut_1er_juillet_2026(client, auth_headers):
    resp = client.get("/api/v1/immobilier/demarrage", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["date"] == "2026-07-01"


def test_demarrage_modifiable_et_persiste(client, auth_headers):
    _set_demarrage(client, auth_headers, date(2026, 9, 15))
    resp = client.get("/api/v1/immobilier/demarrage", headers=auth_headers)
    assert resp.json()["date"] == "2026-09-01"
    _set_demarrage(client, auth_headers, date(2026, 7, 1))  # remise à zéro


# ── L'effet réel : les soldes repartent de la date ─────────────────────


def test_solde_ne_remonte_pas_avant_le_demarrage(
    client, auth_headers, bail_seed
):
    """Bail de 1 000 $/mois sans paiement : avec un démarrage au mois
    courant, un seul mois est dû ; en reculant de 3 mois, 4 le sont."""
    mois_courant = datetime.now(timezone.utc).date().replace(day=1)

    def solde() -> float:
        resp = client.get(
            f"/api/v1/immobilier/loyers/overview?mois="
            f"{mois_courant.strftime('%Y-%m')}",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        row = next(
            r for r in data["rows"] if r["bail_id"] == bail_seed["bail_id"]
        )
        assert data["solde_depuis"] is not None  # exposé à l'UI
        return row["solde_total"]

    _set_demarrage(client, auth_headers, mois_courant)
    assert solde() == 1000.0

    _set_demarrage(client, auth_headers, _mois(mois_courant, -3))
    assert solde() == 4000.0

    # Retour au défaut pour ne pas polluer les autres tests.
    _set_demarrage(client, auth_headers, DEFAULT_DEMARRAGE)


def test_historique_paiements_borne_par_le_demarrage(
    client, auth_headers, bail_seed
):
    """Le paiement du 1er mois du bail disparaît des historiques (bail +
    fiche locataire) dès que le démarrage est postérieur, et revient si on
    recule la date."""
    bail_id = bail_seed["bail_id"]
    loc_id = bail_seed["locataire_id"]
    mois_courant = datetime.now(timezone.utc).date().replace(day=1)

    _set_demarrage(client, auth_headers, mois_courant)
    resp = client.get(
        f"/api/v1/immobilier/baux/{bail_id}/paiements", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
    dossier = client.get(
        f"/api/v1/immobilier/locataires/{loc_id}/dossier", headers=auth_headers
    )
    assert dossier.status_code == 200, dossier.text
    assert dossier.json()["total_paye"] == 0.0

    _set_demarrage(client, auth_headers, bail_seed["debut"])
    resp2 = client.get(
        f"/api/v1/immobilier/baux/{bail_id}/paiements", headers=auth_headers
    )
    assert len(resp2.json()) == 1
    dossier2 = client.get(
        f"/api/v1/immobilier/locataires/{loc_id}/dossier", headers=auth_headers
    )
    assert dossier2.json()["total_paye"] == 1000.0

    _set_demarrage(client, auth_headers, DEFAULT_DEMARRAGE)
