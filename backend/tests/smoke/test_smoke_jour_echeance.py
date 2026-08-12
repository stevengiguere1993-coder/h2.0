"""Smoke — JOUR D'ÉCHÉANCE du loyer, par bail (bail TAL « Ou le ___ »).

Avant : tout le pôle présumait le loyer dû le 1er et faisait tomber le
retard le 5, en dur. Le garage du 8900 St-Hubert est payable le 12 — il
apparaissait donc faussement « en retard » du 5 au 12, chaque mois.

Vérifie :
- (a) un bail payable le 12 n'est PAS en retard le 8, alors qu'un bail
  payable le 1er l'est — sur la règle pure ET sur /loyers/overview ;
- (b) le défaut vaut 1 (aucun changement pour les baux existants) ;
- (c) la validation refuse 0 et 31, en français.
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
)
from app.services.loyer_echeance import (
    date_echeance,
    paiement_en_retard,
    seuil_retard,
)

from .conftest import TestSessionLocal


def _en_retard(today: date, mois: date, jour: int) -> bool:
    """Même comparaison que /loyers/overview (bail sans paiement)."""
    return today > seuil_retard(mois, jour)


# ── (a) La règle pure : le 8, un bail au 12 n'est pas en retard ───────


def test_bail_payable_le_12_pas_en_retard_le_8():
    mois = date(2026, 8, 1)
    le_8 = date(2026, 8, 8)
    # Bail « normal » (le 1er) : seuil au 5 → en retard le 8.
    assert _en_retard(le_8, mois, 1) is True
    # Le garage payable le 12 : seuil au 16 → PAS en retard le 8.
    assert _en_retard(le_8, mois, 12) is False


def test_bail_payable_le_12_devient_en_retard_apres_son_delai():
    mois = date(2026, 8, 1)
    assert seuil_retard(mois, 12) == date(2026, 8, 16)
    assert _en_retard(date(2026, 8, 16), mois, 12) is False  # jour même
    assert _en_retard(date(2026, 8, 17), mois, 12) is True


def test_seuil_par_defaut_identique_a_lancien_seuil_global():
    """Sans jour d'échéance, on retrouve EXACTEMENT le 5 du mois."""
    for mois in (date(2026, 1, 1), date(2026, 2, 1), date(2027, 12, 1)):
        assert seuil_retard(mois, 1) == mois.replace(day=5)
        assert seuil_retard(mois, None) == mois.replace(day=5)


def test_jour_borne_au_dernier_jour_du_mois():
    """Un jour au-delà du mois court (février) ne lève jamais."""
    assert date_echeance(date(2027, 2, 1), 28) == date(2027, 2, 28)
    # Année bissextile : le 28 reste le 28 (borne haute du champ).
    assert date_echeance(date(2028, 2, 1), 28) == date(2028, 2, 28)
    # Valeur aberrante en base → repli sur le 1er, jamais d'exception.
    assert date_echeance(date(2026, 2, 1), 31) == date(2026, 2, 1)


def test_flag_en_retard_a_la_creation_dun_paiement():
    """Même ancrage pour le flag posé à l'encaissement (grâce 5 jours)."""
    mois = date(2026, 8, 1)
    # Bail au 1er : payé le 6 → à temps, le 7 → en retard (règle d'avant).
    assert paiement_en_retard(mois, date(2026, 8, 6), 1) is False
    assert paiement_en_retard(mois, date(2026, 8, 7), 1) is True
    # Bail au 12 : le 8 est même EN AVANCE, le 18 est en retard.
    assert paiement_en_retard(mois, date(2026, 8, 8), 12) is False
    assert paiement_en_retard(mois, date(2026, 8, 17), 12) is False
    assert paiement_en_retard(mois, date(2026, 8, 18), 12) is True
    assert paiement_en_retard(mois, None, 12) is False


# ── (a bis) L'effet réel dans /loyers/overview ────────────────────────


@pytest.fixture(scope="module")
def baux_echeance(run, seeded_users) -> dict:
    """Deux baux actifs sans aucun paiement dans le même immeuble :
    l'un payable le 1er, l'autre le 12 (le garage)."""

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Smoke Échéance",
                address="8900 St-Hubert",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            debut = datetime.now(timezone.utc).date().replace(day=1)
            debut = debut.replace(year=debut.year - 1)
            out: dict = {"immeuble_id": imm.id}
            for numero, jour, cle in (
                ("Logement 1", 1, "bail_le_1er"),
                ("Garage", 12, "bail_le_12"),
            ):
                lg = Logement(
                    immeuble_id=imm.id,
                    numero=numero,
                    status=LogementStatus.OCCUPE.value,
                )
                loc = Locataire(full_name=f"Locataire {numero}")
                s.add_all([lg, loc])
                await s.flush()
                bail = Bail(
                    logement_id=lg.id,
                    locataire_id=loc.id,
                    date_debut=debut,
                    date_fin=debut + timedelta(days=730),
                    loyer_mensuel=1000.0,
                    status=BailStatus.ACTIF.value,
                    jour_echeance=jour,
                )
                s.add(bail)
                await s.flush()
                out[cle] = bail.id
            await s.commit()
            return out

    return run(_seed())


def test_overview_applique_le_seuil_par_bail(
    client, auth_headers, baux_echeance
):
    """L'état renvoyé par l'API suit le seuil DU BAIL, pas un 5 global.

    Avec l'ancien seuil global, le bail au 12 serait « retard » dès le 6
    du mois alors que la règle dit « attente » jusqu'au 16.
    """
    today = datetime.now(timezone.utc).date()
    mois = today.replace(day=1)
    resp = client.get(
        f"/api/v1/immobilier/loyers/overview?mois={mois.strftime('%Y-%m')}",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    rows = {r["bail_id"]: r for r in resp.json()["rows"]}

    for cle, jour in (("bail_le_1er", 1), ("bail_le_12", 12)):
        row = rows[baux_echeance[cle]]
        attendu = "retard" if _en_retard(today, mois, jour) else "attente"
        assert row["etat"] == attendu, (
            f"{cle} (échéance le {jour}) : attendu {attendu}, "
            f"reçu {row['etat']} — seuil {seuil_retard(mois, jour)}, "
            f"aujourd'hui {today}"
        )


# ── (b) Le défaut vaut 1 ──────────────────────────────────────────────


def test_defaut_vaut_1_en_base_et_dans_lapi(
    client, auth_headers, baux_echeance, run
):
    """Un bail créé SANS jour d'échéance est payable le 1er."""

    async def _logement_et_locataire() -> tuple[int, int]:
        async with TestSessionLocal() as s:
            lg = Logement(
                immeuble_id=baux_echeance["immeuble_id"],
                numero="Défaut",
                status=LogementStatus.VACANT.value,
            )
            loc = Locataire(full_name="Locataire Défaut")
            s.add_all([lg, loc])
            await s.commit()
            return lg.id, loc.id

    logement_id, locataire_id = run(_logement_et_locataire())
    debut = date(2030, 1, 1)
    resp = client.post(
        "/api/v1/immobilier/baux",
        headers=auth_headers,
        json={
            "logement_id": logement_id,
            "locataire_id": locataire_id,
            "date_debut": debut.isoformat(),
            "date_fin": (debut + timedelta(days=364)).isoformat(),
            "loyer_mensuel": 900.0,
            "status": BailStatus.ACTIF.value,
        },
    )
    assert resp.status_code == 201, resp.text
    bail = resp.json()
    assert bail["jour_echeance"] == 1

    # Modifiable après coup (formulaires d'édition de bail).
    patch = client.patch(
        f"/api/v1/immobilier/baux/{bail['id']}",
        headers=auth_headers,
        json={"jour_echeance": 12},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["jour_echeance"] == 12

    # `null` explicite = « ne touche pas » (la colonne est NOT NULL).
    neutre = client.patch(
        f"/api/v1/immobilier/baux/{bail['id']}",
        headers=auth_headers,
        json={"jour_echeance": None, "loyer_mensuel": 950.0},
    )
    assert neutre.status_code == 200, neutre.text
    assert neutre.json()["jour_echeance"] == 12
    assert neutre.json()["loyer_mensuel"] == 950.0


# ── (c) La validation refuse 0 et 31 ──────────────────────────────────


@pytest.mark.parametrize("jour", [0, 31, -3, 29])
def test_validation_refuse_les_jours_hors_bornes(
    client, auth_headers, baux_echeance, jour
):
    resp = client.post(
        "/api/v1/immobilier/baux",
        headers=auth_headers,
        json={
            "logement_id": 1,
            "locataire_id": 1,
            "date_debut": "2031-01-01",
            "date_fin": "2031-12-31",
            "loyer_mensuel": 900.0,
            "jour_echeance": jour,
        },
    )
    assert resp.status_code == 422, resp.text
    assert "entre 1 et 28" in resp.text


@pytest.mark.parametrize("jour", [0, 31])
def test_validation_refuse_aussi_a_la_modification(
    client, auth_headers, baux_echeance, jour
):
    resp = client.patch(
        f"/api/v1/immobilier/baux/{baux_echeance['bail_le_12']}",
        headers=auth_headers,
        json={"jour_echeance": jour},
    )
    assert resp.status_code == 422, resp.text
    assert "entre 1 et 28" in resp.text
