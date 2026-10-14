"""Smoke — pas de déduction d'acompte sans facture d'acompte émise (2026-10-14).

Steven : « Lorsqu'on crée une facture, s'il n'y a pas eu de facture de
dépôt, il ne devrait pas y avoir une déduction d'acompte sur la facture
finale. »

Cause : la facture d'acompte créée d'office à l'acceptation du devis
reste en BROUILLON tant qu'elle n'est pas envoyée (client sans courriel,
« Convertir en projet », rattrapage au démarrage). Ce brouillon comptait
pourtant comme un acompte reçu : la facture qui solde le contrat
déduisait tout l'acompte (« Moins acompte appliqué ») alors que le
client n'avait jamais été facturé de cet acompte.

Couvre :
1. acompte en brouillon → facture finale au plein montant, sans
   déduction ;
2. aucun acompte → aucune déduction ;
3. acompte envoyé, payé ou en retard → déduit comme avant ; annulé →
   pas déduit (inchangé) ;
4. acompte en brouillon au moment d'une facture d'avancement, puis
   envoyé → la facture finale déduit tout l'acompte ;
5. « État du contrat » : un brouillon n'est pas un acompte reçu, il est
   signalé à part (acompte_brouillon) ;
6. modifier la ligne « Moins acompte appliqué » (prix ou quantité) la
   garde en déduction — elle passait en ajout.
"""

from __future__ import annotations

import uuid
from typing import Optional

import pytest
from sqlalchemy import delete, select, update

from app.api.v1.endpoints.soumission_to_project import (
    provision_project_for_soumission,
)
from app.models.client import Client
from app.models.facture import Facture
from app.models.facture_item import FactureItem
from app.models.project import Project
from app.models.project_task import ProjectTask
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem
from tests.smoke.conftest import TestSessionLocal

#: Devis de 10 000 $ HT → acompte de 30 % = 3 000 $ HT.
ACOMPTE_HT = 3000.0


@pytest.fixture()
def chantier(run, db_setup):
    """Fabrique un devis accepté (deux lignes, 10 000 $ HT) + son projet,
    avec la facture d'acompte créée comme à l'acceptation, puis laissée
    dans le statut demandé (None = devis sans acompte). Nettoie tout
    après le test (la base de test est partagée)."""
    crees: list[dict] = []

    def _creer(acompte: Optional[str]) -> dict:
        async def _go() -> dict:
            async with TestSessionLocal() as s:
                tag = uuid.uuid4().hex[:8]
                cl = Client(name=f"Client acompte {tag}")
                s.add(cl)
                await s.flush()
                sm = Soumission(
                    reference=f"S-AC-{tag}",
                    title="Salle de bain",
                    client_id=cl.id,
                    status="accepted",
                    subtotal=10000,
                )
                s.add(sm)
                await s.flush()
                s.add_all(
                    [
                        SoumissionItem(
                            soumission_id=sm.id,
                            position=0,
                            description="Démolition",
                            quantity=1,
                            unit_price=4000,
                            total=4000,
                        ),
                        SoumissionItem(
                            soumission_id=sm.id,
                            position=1,
                            description="Céramique",
                            quantity=1,
                            unit_price=6000,
                            total=6000,
                        ),
                    ]
                )
                await s.flush()
                proj, depot = await provision_project_for_soumission(
                    s, sm, deposit_percentage=0 if acompte is None else 30
                )
                if acompte is None:
                    assert depot is None
                else:
                    assert depot is not None
                    depot.status = acompte
                await s.commit()
                ids = {
                    "client": cl.id,
                    "soumission": sm.id,
                    "projet": proj.id,
                    "depot": depot.id if depot is not None else None,
                }
                crees.append(ids)
                return ids

        return run(_go())

    yield _creer

    async def _nettoyer() -> None:
        async with TestSessionLocal() as s:
            for ids in crees:
                fac_ids = (
                    await s.execute(
                        select(Facture.id).where(
                            Facture.project_id == ids["projet"]
                        )
                    )
                ).scalars().all()
                if fac_ids:
                    await s.execute(
                        delete(FactureItem).where(
                            FactureItem.facture_id.in_(fac_ids)
                        )
                    )
                    await s.execute(
                        delete(Facture).where(Facture.id.in_(fac_ids))
                    )
                await s.execute(
                    delete(ProjectTask).where(
                        ProjectTask.project_id == ids["projet"]
                    )
                )
                await s.execute(delete(Project).where(Project.id == ids["projet"]))
                await s.execute(
                    delete(SoumissionItem).where(
                        SoumissionItem.soumission_id == ids["soumission"]
                    )
                )
                await s.execute(
                    delete(Soumission).where(Soumission.id == ids["soumission"])
                )
                await s.execute(delete(Client).where(Client.id == ids["client"]))
            await s.commit()

    run(_nettoyer())


def _facturer(client, headers, projet_id: int, pct: int = 100) -> int:
    r = client.post(
        f"/api/v1/projects/{projet_id}/convert-to-facture",
        json={
            "include_soumission": True,
            "soumission_percentage": pct,
            "include_hours": False,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


def _deduction(run, facture_id: int) -> float:
    """Montant HT déduit par les lignes « Moins acompte appliqué »."""

    async def _go() -> float:
        async with TestSessionLocal() as s:
            totaux = (
                await s.execute(
                    select(FactureItem.total).where(
                        FactureItem.facture_id == facture_id,
                        FactureItem.kind == "acompte_applique",
                    )
                )
            ).scalars().all()
            return round(-sum(float(t) for t in totaux), 2)

    return run(_go())


def _sous_total(run, facture_id: int) -> float:
    async def _go() -> float:
        async with TestSessionLocal() as s:
            fa = await s.get(Facture, facture_id)
            return round(float(fa.subtotal or 0), 2)

    return run(_go())


def _statut_depot(run, depot_id: int, statut: str) -> None:
    async def _go() -> None:
        async with TestSessionLocal() as s:
            await s.execute(
                update(Facture).where(Facture.id == depot_id).values(status=statut)
            )
            await s.commit()

    run(_go())


def test_acompte_en_brouillon_pas_deduit_sur_la_facture_finale(
    chantier, client, auth_headers, run
):
    ids = chantier("draft")

    fid = _facturer(client, auth_headers, ids["projet"])

    assert _deduction(run, fid) == 0.0
    assert _sous_total(run, fid) == 10000.0


def test_sans_acompte_aucune_deduction(chantier, client, auth_headers, run):
    ids = chantier(None)

    fid = _facturer(client, auth_headers, ids["projet"])

    assert _deduction(run, fid) == 0.0
    assert _sous_total(run, fid) == 10000.0


@pytest.mark.parametrize("statut", ["sent", "paid", "overdue"])
def test_acompte_emis_deduit_sur_la_facture_finale(
    chantier, client, auth_headers, run, statut
):
    ids = chantier(statut)

    fid = _facturer(client, auth_headers, ids["projet"])

    assert _deduction(run, fid) == ACOMPTE_HT
    assert _sous_total(run, fid) == 10000.0 - ACOMPTE_HT


def test_acompte_annule_pas_deduit(chantier, client, auth_headers, run):
    ids = chantier("void")

    fid = _facturer(client, auth_headers, ids["projet"])

    assert _deduction(run, fid) == 0.0


def test_acompte_envoye_deduit_au_prorata_puis_le_reste(
    chantier, client, auth_headers, run
):
    ids = chantier("sent")

    moitie = _facturer(client, auth_headers, ids["projet"], pct=50)
    finale = _facturer(client, auth_headers, ids["projet"], pct=100)

    assert _deduction(run, moitie) == 1500.0
    assert _deduction(run, finale) == 1500.0


def test_acompte_envoye_apres_une_facture_d_avancement(
    chantier, client, auth_headers, run
):
    ids = chantier("draft")

    moitie = _facturer(client, auth_headers, ids["projet"], pct=50)
    _statut_depot(run, ids["depot"], "sent")
    finale = _facturer(client, auth_headers, ids["projet"], pct=100)

    assert _deduction(run, moitie) == 0.0
    assert _deduction(run, finale) == ACOMPTE_HT


def test_etat_du_contrat_distingue_l_acompte_en_brouillon(
    chantier, client, auth_headers, run
):
    ids = chantier("draft")

    r = client.get(
        f"/api/v1/projects/{ids['projet']}/etat-contrat", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    etat = r.json()
    assert etat["acompte_recu"] == 0.0
    assert etat["acompte_restant"] == 0.0
    assert etat["acompte_brouillon"] == ACOMPTE_HT
    assert etat["facture_a_date"] == 0.0

    _statut_depot(run, ids["depot"], "sent")
    etat = client.get(
        f"/api/v1/projects/{ids['projet']}/etat-contrat", headers=auth_headers
    ).json()
    assert etat["acompte_recu"] == ACOMPTE_HT
    assert etat["acompte_restant"] == ACOMPTE_HT
    assert etat["acompte_brouillon"] == 0.0


def test_modifier_la_ligne_d_acompte_garde_la_deduction(
    chantier, client, auth_headers, run
):
    """La ligne « Moins acompte appliqué » est annoncée modifiable : l'UI
    renvoie le prix en valeur absolue, la ligne doit rester une
    déduction (avant : elle devenait un ajout de 2 000 $)."""
    ids = chantier("sent")
    fid = _facturer(client, auth_headers, ids["projet"])

    async def _ligne() -> int:
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(FactureItem.id).where(
                        FactureItem.facture_id == fid,
                        FactureItem.kind == "acompte_applique",
                    )
                )
            ).scalar_one()

    item_id = run(_ligne())
    r = client.patch(
        f"/api/v1/factures/{fid}/items/{item_id}",
        json={"unit_price": 2000},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == -2000.0
    assert _deduction(run, fid) == 2000.0
    assert _sous_total(run, fid) == 8000.0

    r = client.patch(
        f"/api/v1/factures/{fid}/items/{item_id}",
        json={"quantity": 0.5},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == -1000.0
