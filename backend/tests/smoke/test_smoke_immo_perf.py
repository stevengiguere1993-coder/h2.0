"""Smoke — perf immobilier : renouvellements/overview (fix N+1) et
maintenance-rollup (fix filtre année en SQL).

Ces deux endpoints ont été optimisés (chargement groupé in_() au lieu de
N+1, borne d'année poussée en SQL). Ces tests garantissent que le
comportement observable est INCHANGÉ : mêmes 200, même contenu, même
résolution du « dernier renouvellement » par bail, et exclusion correcte
des bons de travail hors de l'année ciblée.

On seed directement en DB (via la session de test) pour contrôler
``created_at`` (server_default = now()) — impossible à fixer via l'API —
et pour poser plusieurs baux d'un coup (le vrai test du N+1).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.bon_travail import BonTravail
from app.models.immobilier import (
    Bail,
    BailRenouvellement,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
)

from .conftest import TestSessionLocal


@pytest.fixture(scope="module")
def immo_perf_seed(run, seeded_users) -> dict:
    """Seed minimal : 1 immeuble, 2 logements/locataires/baux (dont un avec
    un renouvellement) + 2 bons internes (un dans l'année, un l'an dernier).
    Retourne les ids utiles aux assertions."""

    today = date.today()
    this_year = today.year

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Smoke Perf",
                address="123 rue Perf",
                is_active=True,
            )
            s.add(imm)
            await s.flush()

            log_a = Logement(
                immeuble_id=imm.id,
                numero="1",
                status=LogementStatus.OCCUPE.value,
            )
            log_b = Logement(
                immeuble_id=imm.id,
                numero="2",
                status=LogementStatus.OCCUPE.value,
            )
            s.add_all([log_a, log_b])
            await s.flush()

            loc_a = Locataire(full_name="Alice Smoke", email="alice@smoke.test")
            loc_b = Locataire(full_name="Bob Smoke", email=None)
            s.add_all([loc_a, loc_b])
            await s.flush()

            # Deux baux actifs dont la fin tombe dans les 12 prochains mois →
            # tous deux visibles dans /renouvellements/overview.
            bail_a = Bail(
                logement_id=log_a.id,
                locataire_id=loc_a.id,
                date_debut=today - timedelta(days=200),
                date_fin=today + timedelta(days=60),  # imminente (<= 90 j)
                loyer_mensuel=1000,
                status=BailStatus.ACTIF.value,
            )
            bail_b = Bail(
                logement_id=log_b.id,
                locataire_id=loc_b.id,
                date_debut=today - timedelta(days=100),
                date_fin=today + timedelta(days=150),  # a_envoyer (120-180 j)
                loyer_mensuel=1200,
                status=BailStatus.ACTIF.value,
            )
            s.add_all([bail_a, bail_b])
            await s.flush()

            # Deux renouvellements sur le bail A → on doit retenir le plus
            # récent (avis_envoye_le desc). Le bail B n'en a aucun.
            ren_old = BailRenouvellement(
                bail_id=bail_a.id,
                avis_envoye_le=today - timedelta(days=40),
                nouveau_loyer=1010,
                status="propose",
            )
            ren_new = BailRenouvellement(
                bail_id=bail_a.id,
                avis_envoye_le=today - timedelta(days=10),
                nouveau_loyer=1050,
                status="accepte",
            )
            s.add_all([ren_old, ren_new])

            # Bons de travail internes : un dans l'année courante (compté),
            # un l'an dernier (exclu par la borne SQL).
            bon_in = BonTravail(
                reference=f"BT-SMKP-{uuid.uuid4().hex[:10]}",
                title="Réparation dans l'année",
                kind="interne",
                status="draft",
                immeuble_id=imm.id,
                logement_id=log_a.id,
                amount=500,
                created_at=datetime(this_year, 6, 15, tzinfo=timezone.utc),
            )
            bon_old = BonTravail(
                reference=f"BT-SMKP-{uuid.uuid4().hex[:10]}",
                title="Réparation l'an dernier",
                kind="interne",
                status="draft",
                immeuble_id=imm.id,
                logement_id=None,  # communs
                amount=999,
                created_at=datetime(
                    this_year - 1, 6, 15, tzinfo=timezone.utc
                ),
            )
            s.add_all([bon_in, bon_old])
            await s.flush()

            ids = {
                "immeuble_id": imm.id,
                "logement_a": log_a.id,
                "logement_b": log_b.id,
                "bail_a": bail_a.id,
                "bail_b": bail_b.id,
                "this_year": this_year,
                "bon_in_amount": 500.0,
            }
            await s.commit()
            return ids

    return run(_seed())


def test_renouvellements_overview_ok(client, auth_headers, immo_perf_seed):
    """L'aperçu renvoie 200 + les deux baux, avec la bonne résolution du
    dernier renouvellement (le plus récent) et des jointures groupées."""
    resp = client.get(
        "/api/v1/immobilier/renouvellements/overview", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert isinstance(rows, list)

    by_bail = {r["bail_id"]: r for r in rows}
    ra = by_bail.get(immo_perf_seed["bail_a"])
    rb = by_bail.get(immo_perf_seed["bail_b"])
    assert ra is not None and rb is not None

    # Forme du contrat (clés présentes).
    for key in (
        "immeuble_id",
        "immeuble_name",
        "logement_numero",
        "locataire_nom",
        "bail_date_fin",
        "bail_loyer_mensuel",
        "jours_avant_fin",
        "fenetre",
    ):
        assert key in ra

    # Bail A : un renouvellement existe → fenêtre "envoye", et on retient le
    # PLUS RÉCENT (nouveau_loyer 1050, status accepte), pas l'ancien (1010).
    assert ra["fenetre"] == "envoye"
    assert ra["renouvellement_status"] == "accepte"
    assert ra["nouveau_loyer"] == 1050.0
    assert ra["locataire_nom"] == "Alice Smoke"
    assert ra["immeuble_name"] == "Immeuble Smoke Perf"

    # Bail B : aucun renouvellement → pas "envoye", pas de loyer proposé.
    assert rb["fenetre"] != "envoye"
    assert rb["avis_envoye_le"] is None
    assert rb["nouveau_loyer"] is None
    assert rb["locataire_email"] is None


def test_maintenance_rollup_year_window(client, auth_headers, immo_perf_seed):
    """Le roll-up ne compte que les bons de l'année ciblée (borne SQL) — le
    bon de l'an dernier est exclu."""
    imm_id = immo_perf_seed["immeuble_id"]
    resp = client.get(
        f"/api/v1/immobilier/maintenance-rollup?immeuble_id={imm_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1  # un seul immeuble ciblé

    entry = data[0]
    assert entry["immeuble_id"] == imm_id
    # Seul le bon de l'année (500 $) compte ; celui de l'an dernier (999 $)
    # est écarté par la fenêtre SQL.
    assert entry["count"] == 1
    assert entry["total"] == immo_perf_seed["bon_in_amount"]

    # Requête explicite sur l'an dernier → doit inclure le bon de 999 $
    # (et exclure celui de cette année) : prouve que la borne suit `year`.
    last_year = immo_perf_seed["this_year"] - 1
    resp2 = client.get(
        f"/api/v1/immobilier/maintenance-rollup"
        f"?immeuble_id={imm_id}&year={last_year}",
        headers=auth_headers,
    )
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert len(data2) == 1
    assert data2[0]["count"] == 1
    assert data2[0]["total"] == 999.0
