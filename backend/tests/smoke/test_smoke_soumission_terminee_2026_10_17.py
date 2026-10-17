"""Smoke — projet terminé → soumission dans « Terminées » (2026-10-17).

Steven : « Dans soumission, lorsqu'un projet relié à une soumission est
terminé, mettre la soumission dans la colonne soumission terminée. »

La colonne « Archivée » du tableau des soumissions devient « Terminées »
(drapeau ``archived_at``, le statut accepted est conservé). Couvre :
1. projet livré → soumission dans « Terminées » ;
2. projet rouvert → elle revient dans « Acceptées » ;
3. sauvegarder un projet déjà livré ne remet pas une soumission sortie à
   la main ;
4. soumission reliée à deux projets → terminée au dernier livré ;
5. projet déjà livré relié après coup, ou créé livré → terminée ;
6. facture finale soldée (projet livré par le paiement) → terminée ;
7. rattrapage des projets déjà livrés, une seule fois ;
8. le changement de colonne ne touche pas ``updated_at`` (le tableau de
   bord date par lui les ventes acceptées sans ``accepted_at``).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

import pytest
from sqlalchemy import delete, select, text, update

from app.api.v1.endpoints.soumission_to_project import (
    provision_project_for_soumission,
)
from app.models.client import Client
from app.models.facture import Facture
from app.models.payment import Payment
from app.models.project import Project
from app.models.project_task import ProjectTask
from app.models.soumission import Soumission
from app.services.project_auto_status import (
    CLE_RATTRAPAGE_SOUMISSIONS_TERMINEES,
    archive_soumissions_of_delivered_projects_once,
)
from tests.smoke.conftest import TestSessionLocal


@pytest.fixture()
def chantier(run, db_setup):
    """Fabrique un client + un devis accepté, et (par défaut) son projet
    créé comme à l'acceptation. Nettoie tout après le test (la base de
    test est partagée), y compris les projets ajoutés par le test."""
    crees: list[dict] = []

    def _creer(avec_projet: bool = True) -> dict:
        async def _go() -> dict:
            async with TestSessionLocal() as s:
                tag = uuid.uuid4().hex[:8]
                cl = Client(name=f"Client terminée {tag}")
                s.add(cl)
                await s.flush()
                sm = Soumission(
                    reference=f"S-TE-{tag}",
                    title="Cuisine",
                    client_id=cl.id,
                    status="accepted",
                    subtotal=10000,
                    total=11497.5,
                )
                s.add(sm)
                await s.flush()
                projet_id: Optional[int] = None
                if avec_projet:
                    proj, _ = await provision_project_for_soumission(
                        s, sm, deposit_percentage=0
                    )
                    projet_id = proj.id
                await s.commit()
                ids = {"client": cl.id, "soumission": sm.id, "projet": projet_id}
                crees.append(ids)
                return ids

        return run(_go())

    yield _creer

    async def _nettoyer() -> None:
        async with TestSessionLocal() as s:
            for ids in crees:
                projets = (
                    await s.execute(
                        select(Project.id).where(
                            Project.soumission_id == ids["soumission"]
                        )
                    )
                ).scalars().all()
                fac_ids = (
                    await s.execute(
                        select(Facture.id).where(Facture.project_id.in_(projets))
                    )
                ).scalars().all()
                if fac_ids:
                    await s.execute(
                        delete(Payment).where(Payment.facture_id.in_(fac_ids))
                    )
                    await s.execute(delete(Facture).where(Facture.id.in_(fac_ids)))
                await s.execute(
                    delete(ProjectTask).where(ProjectTask.project_id.in_(projets))
                )
                await s.execute(delete(Project).where(Project.id.in_(projets)))
                await s.execute(
                    delete(Soumission).where(Soumission.id == ids["soumission"])
                )
                await s.execute(delete(Client).where(Client.id == ids["client"]))
            await s.commit()

    run(_nettoyer())


#: Ancienne date de modification : un changement de colonne doit la garder.
MODIFIEE_LE = datetime(2025, 1, 15, 12, 0, 0)


def _soumission(run, soumission_id: int) -> dict:
    async def _go() -> dict:
        async with TestSessionLocal() as s:
            sm = await s.get(Soumission, soumission_id)
            return {
                "terminee": sm.archived_at is not None,
                "status": sm.status,
                "modifiee_le": sm.updated_at.replace(tzinfo=None),
            }

    return run(_go())


def _vieillir(run, soumission_id: int) -> None:
    async def _go() -> None:
        async with TestSessionLocal() as s:
            await s.execute(
                update(Soumission)
                .where(Soumission.id == soumission_id)
                .values(updated_at=MODIFIEE_LE)
            )
            await s.commit()

    run(_go())


def _statut_projet(client, headers, projet_id: int, statut: str) -> None:
    r = client.put(
        f"/api/v1/projects/{projet_id}", json={"status": statut}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == statut


def _nouveau_projet(client, headers, **champs) -> int:
    r = client.post(
        "/api/v1/projects",
        json={"name": f"Projet {uuid.uuid4().hex[:6]}", **champs},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_projet_livre_soumission_dans_terminees(chantier, client, auth_headers, run):
    ids = chantier()
    _vieillir(run, ids["soumission"])
    assert _soumission(run, ids["soumission"])["terminee"] is False

    _statut_projet(client, auth_headers, ids["projet"], "delivered")

    sm = _soumission(run, ids["soumission"])
    assert sm["terminee"] is True
    assert sm["status"] == "accepted"  # le vrai statut est conservé
    assert sm["modifiee_le"] == MODIFIEE_LE


def test_projet_rouvert_soumission_revient_dans_acceptees(
    chantier, client, auth_headers, run
):
    ids = chantier()
    _statut_projet(client, auth_headers, ids["projet"], "delivered")
    _vieillir(run, ids["soumission"])

    _statut_projet(client, auth_headers, ids["projet"], "in_progress")

    sm = _soumission(run, ids["soumission"])
    assert sm["terminee"] is False
    assert sm["status"] == "accepted"
    assert sm["modifiee_le"] == MODIFIEE_LE


def test_projet_deja_livre_sauvegarde_respecte_le_choix_manuel(
    chantier, client, auth_headers, run
):
    ids = chantier()
    _statut_projet(client, auth_headers, ids["projet"], "delivered")
    r = client.patch(
        f"/api/v1/soumissions/{ids['soumission']}/archive",
        json={"archived": False},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = client.put(
        f"/api/v1/projects/{ids['projet']}",
        json={"name": "Cuisine renommée"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    _statut_projet(client, auth_headers, ids["projet"], "delivered")

    assert _soumission(run, ids["soumission"])["terminee"] is False


def test_soumission_a_deux_projets_terminee_au_dernier_livre(
    chantier, client, auth_headers, run
):
    ids = chantier()
    second = _nouveau_projet(
        client, auth_headers, soumission_id=ids["soumission"]
    )

    _statut_projet(client, auth_headers, ids["projet"], "delivered")
    assert _soumission(run, ids["soumission"])["terminee"] is False

    _statut_projet(client, auth_headers, second, "delivered")
    assert _soumission(run, ids["soumission"])["terminee"] is True


def test_projet_deja_livre_relie_apres_coup(chantier, client, auth_headers, run):
    ids = chantier(avec_projet=False)
    projet = _nouveau_projet(client, auth_headers, status="delivered")

    r = client.put(
        f"/api/v1/projects/{projet}",
        json={"soumission_id": ids["soumission"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    assert _soumission(run, ids["soumission"])["terminee"] is True


def test_projet_cree_livre_avec_sa_soumission(chantier, client, auth_headers, run):
    ids = chantier(avec_projet=False)

    _nouveau_projet(
        client, auth_headers, status="delivered", soumission_id=ids["soumission"]
    )

    assert _soumission(run, ids["soumission"])["terminee"] is True


def test_facture_finale_soldee_termine_la_soumission(
    chantier, client, auth_headers, run
):
    ids = chantier()

    async def _facture_finale() -> int:
        async with TestSessionLocal() as s:
            fa = Facture(
                reference=f"F-TE-{uuid.uuid4().hex[:8]}",
                project_id=ids["projet"],
                client_id=ids["client"],
                status="sent",
                subtotal=1000,
                total=1000,
                is_final=True,
            )
            s.add(fa)
            await s.commit()
            return fa.id

    facture_id = run(_facture_finale())
    r = client.post(
        f"/api/v1/factures/{facture_id}/payments",
        json={"amount": 1000, "paid_at": date.today().isoformat()},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    async def _statut() -> str:
        async with TestSessionLocal() as s:
            return (await s.get(Project, ids["projet"])).status

    assert run(_statut()) == "delivered"
    assert _soumission(run, ids["soumission"])["terminee"] is True


def test_rattrapage_des_projets_deja_livres_une_seule_fois(chantier, run):
    livre = chantier()
    en_cours = chantier()
    sans_projet = chantier(avec_projet=False)

    async def _preparer() -> None:
        async with TestSessionLocal() as s:
            # Table créée par init_db en prod (absente du schéma de test).
            await s.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS applied_backfills ("
                    "key VARCHAR(120) PRIMARY KEY, "
                    "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            await s.execute(
                text("DELETE FROM applied_backfills WHERE key = :k"),
                {"k": CLE_RATTRAPAGE_SOUMISSIONS_TERMINEES},
            )
            # Livré AVANT la règle : le drapeau n'a jamais été posé.
            await s.execute(
                update(Project)
                .where(Project.id == livre["projet"])
                .values(status="delivered")
            )
            await s.commit()

    async def _rattraper() -> int:
        async with TestSessionLocal() as s:
            return await archive_soumissions_of_delivered_projects_once(s)

    run(_preparer())
    _vieillir(run, livre["soumission"])
    assert run(_rattraper()) >= 1
    assert _soumission(run, livre["soumission"])["terminee"] is True
    assert _soumission(run, livre["soumission"])["modifiee_le"] == MODIFIEE_LE
    assert _soumission(run, en_cours["soumission"])["terminee"] is False
    assert _soumission(run, sans_projet["soumission"])["terminee"] is False

    # Sortie à la main ensuite : le rattrapage ne l'y remet jamais.
    async def _sortir() -> None:
        async with TestSessionLocal() as s:
            await s.execute(
                update(Soumission)
                .where(Soumission.id == livre["soumission"])
                .values(archived_at=None)
            )
            await s.commit()

    run(_sortir())
    assert run(_rattraper()) == 0
    assert _soumission(run, livre["soumission"])["terminee"] is False
