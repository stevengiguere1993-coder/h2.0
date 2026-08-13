"""Smoke — Miroir « loyer demandé » (2026-08-13).

Un logement OCCUPÉ affiche le loyer RÉEL du bail : quand un avis de
renouvellement est APPLIQUÉ, ou quand un bail est créé/modifié actif,
``Logement.loyer_demande`` suit le loyer courant. Quand le bail se
résilie, le prix de relocation porté par le dossier Locations fait foi
(le flux du kanban n'est pas touché).
"""
from __future__ import annotations

from datetime import date, timedelta


def _seed_occupe(run, *, numero: str, loyer: float, loyer_demande: float):
    """Immeuble → logement OCCUPÉ (loyer_demande DIVERGENT du bail)
    → locataire → bail actif. Retourne (immeuble_id, logement_id,
    locataire_id, bail_id)."""
    from app.models.immobilier import (
        Bail,
        BailStatus,
        Immeuble,
        Locataire,
        Logement,
        LogementStatus,
    )

    from .conftest import TestSessionLocal

    async def _s():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name=f"Sync loyer {numero}",
                address="9085 Avenue Millen",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id,
                numero=numero,
                status=LogementStatus.OCCUPE.value,
                loyer_demande=loyer_demande,
            )
            lo = Locataire(full_name=f"Locataire Sync {numero}")
            s.add_all([lg, lo])
            await s.flush()
            bail = Bail(
                logement_id=lg.id,
                locataire_id=lo.id,
                date_debut=date.today() - timedelta(days=250),
                date_fin=date.today() + timedelta(days=115),
                loyer_mensuel=loyer,
                status=BailStatus.ACTIF.value,
            )
            s.add(bail)
            await s.commit()
            return imm.id, lg.id, lo.id, bail.id

    return run(_s())


def _loyer_demande(run, logement_id: int):
    from app.models.immobilier import Logement

    from .conftest import TestSessionLocal

    async def _s():
        async with TestSessionLocal() as s:
            lg = await s.get(Logement, logement_id)
            return (
                float(lg.loyer_demande)
                if lg.loyer_demande is not None
                else None
            )

    return run(_s())


def test_avis_applique_synchronise_loyer_demande(client, auth_headers, run):
    """Avis accepté puis APPLIQUÉ (lazy, à la consultation de
    l'overview) → le bail ET Logement.loyer_demande prennent le
    nouveau loyer."""
    from app.models.immobilier import BailRenouvellement

    from .conftest import TestSessionLocal

    _imm, lg_id, _lo, bail_id = _seed_occupe(
        run, numero="S1", loyer=1400.0, loyer_demande=999.0
    )

    # Cycle ACCEPTÉ dont la date effective est déjà passée → la
    # consultation de l'overview applique l'avis au bail.
    async def _seed_ren():
        async with TestSessionLocal() as s:
            s.add(
                BailRenouvellement(
                    bail_id=bail_id,
                    avis_envoye_le=date.today() - timedelta(days=90),
                    nouveau_loyer=1450.0,
                    nouvelle_date_debut=date.today() - timedelta(days=1),
                    nouvelle_date_fin=date.today() + timedelta(days=364),
                    status="accepte",
                    reponse_le=date.today() - timedelta(days=80),
                )
            )
            await s.commit()

    run(_seed_ren())
    assert _loyer_demande(run, lg_id) == 999.0  # divergent avant

    rows = client.get(
        "/api/v1/immobilier/renouvellements/overview",
        headers=auth_headers,
    ).json()
    row = next((r for r in rows if r["bail_id"] == bail_id), None)
    assert row is not None, "ligne absente de l'overview"
    assert row["applique_le"] is not None
    assert row["bail_loyer_mensuel"] == 1450.0

    # Miroir : le loyer demandé du logement suit le loyer du bail.
    assert _loyer_demande(run, lg_id) == 1450.0


def test_creation_et_correction_bail_synchronisent(client, auth_headers, run):
    """Créer un bail ACTIF puis corriger son loyer → le logement
    occupé suit le loyer réel à chaque étape."""
    from app.models.immobilier import Immeuble, Locataire, Logement

    from .conftest import TestSessionLocal

    async def _seed():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Sync loyer S2",
                address="9085 Avenue Millen",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id,
                numero="S2",
                status="vacant",
                loyer_demande=777.0,
            )
            lo = Locataire(full_name="Locataire Sync S2")
            s.add_all([lg, lo])
            await s.commit()
            return lg.id, lo.id

    lg_id, lo_id = run(_seed())

    r = client.post(
        "/api/v1/immobilier/baux",
        headers=auth_headers,
        json={
            "logement_id": lg_id,
            "locataire_id": lo_id,
            "date_debut": str(date.today() - timedelta(days=10)),
            "date_fin": str(date.today() + timedelta(days=355)),
            "loyer_mensuel": 1200.0,
            "status": "actif",
        },
    )
    assert r.status_code == 201, r.text
    bail_id = r.json()["id"]
    assert _loyer_demande(run, lg_id) == 1200.0

    # Correction du loyer du bail actif → le miroir suit.
    p = client.patch(
        f"/api/v1/immobilier/baux/{bail_id}",
        headers=auth_headers,
        json={"loyer_mensuel": 1250.0},
    )
    assert p.status_code == 200, p.text
    assert _loyer_demande(run, lg_id) == 1250.0

    # La liste des logements expose le loyer RÉEL du bail actif
    # (BailRead n'expose pas immeuble_id — on le relit du logement).
    from app.models.immobilier import Logement as _Lg

    async def _imm_id():
        async with TestSessionLocal() as s:
            return (await s.get(_Lg, lg_id)).immeuble_id

    imm_id = run(_imm_id())
    lst = client.get(
        f"/api/v1/immobilier/immeubles/{imm_id}/logements",
        headers=auth_headers,
    )
    assert lst.status_code == 200, lst.text
    ligne = next((x for x in lst.json() if x["id"] == lg_id), None)
    assert ligne is not None
    assert ligne["loyer_actuel"] == 1250.0


def test_resiliation_le_dossier_de_relocation_fait_foi(
    client, auth_headers, run
):
    """Bail résilié avec un dossier de relocation DÉJÀ ouvert qui porte
    son propre prix affiché → le logement VACANT reprend ce prix (le
    flux Locations n'est pas cassé)."""
    _imm, lg_id, _lo, bail_id = _seed_occupe(
        run, numero="S3", loyer=1300.0, loyer_demande=1300.0
    )

    # Dossier de relocation ouvert avec un prix affiché de 1500 $.
    r = client.post(
        "/api/v1/immobilier/locations",
        headers=auth_headers,
        json={"bail_id": bail_id, "loyer_demande": 1500.0},
    )
    assert r.status_code in (200, 201), r.text

    # Fin immédiate sans avis (résiliation).
    res = client.post(
        f"/api/v1/immobilier/baux/{bail_id}/resilier",
        headers=auth_headers,
        json={
            "date_fin": str(date.today()),
            "ouvrir_relocation": True,
            "envoyer_avis": False,
        },
    )
    assert res.status_code == 200, res.text

    # Le prix de la relocation (dossier) fait foi sur la fiche.
    assert _loyer_demande(run, lg_id) == 1500.0
