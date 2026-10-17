"""Smoke — heures et achats importés : Service / Matériaux, pas « Extra » (2026-10-14).

Steven : « lorsque je crée une facture dans construction et que
j'importe de la main d'oeuvre et du matériel, il s'agit de services et
de matériaux, non pas d'extra ».

Les trois imports (création depuis le projet, « Ajouter des sources »,
import d'un bon de travail) posaient kind="extra" en dur. Ils posent
maintenant le vrai type — Service pour la main-d'œuvre et les
sous-traitants, Matériaux pour le matériel — et, quand le projet de la
facture a une soumission, la marque hors_soumission qui garde l'effet
comptable d'« extra » (ne pas gruger la cible du devis).

Couvre :
1. création depuis un projet SANS soumission → Service / Matériaux, pas
   hors soumission, et rien dans les « extras » des finances ;
2. création depuis un projet AVEC soumission → Service / Matériaux hors
   soumission : la facture d'avancement suivante facture encore tout le
   devis, l'État du contrat et les finances les comptent en extras ;
3. « Ajouter des sources » et import d'un bon → mêmes types, marque selon
   le projet de la facture ;
4. éditeur : le type « materiaux » est accepté, la marque se bascule, une
   ligne rattachée au devis n'est jamais hors soumission ;
5. reclassement one-shot des brouillons existants (extras importés
   seulement ; factures envoyées et extras saisis à la main intacts).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest
from sqlalchemy import delete, select, update

from app.models.achat import Achat
from app.models.bon_travail import BonTravail
from app.models.client import Client
from app.models.employe import Employe
from app.models.facture import Facture
from app.models.facture_item import FactureItem
from app.models.project import Project
from app.models.punch import Punch
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem
from app.services.facture_lignes import reclasser_lignes_importees_brouillons
from tests.smoke.conftest import TestSessionLocal

#: 10 h approuvées à 100 $/h (taux de facturation de l'employé).
MAIN_OEUVRE = 1000.0
#: Matériel 200 $ + 10 % ; sous-traitant 500 $ au coûtant.
MATERIEL = 220.0
SOUS_TRAITANT = 500.0
DEVIS = 10000.0


@pytest.fixture()
def chantier(run, db_setup):
    """Projet (avec ou sans devis accepté de 10 000 $ HT) + 10 h
    approuvées + un achat de matériel et une facture de sous-traitant
    refacturables. Nettoie tout après le test (base partagée)."""
    crees: list[dict] = []

    def _creer(avec_soumission: bool) -> dict:
        async def _go() -> dict:
            async with TestSessionLocal() as s:
                tag = uuid.uuid4().hex[:8]
                cl = Client(name=f"Client lignes {tag}")
                s.add(cl)
                await s.flush()
                sm_id: Optional[int] = None
                if avec_soumission:
                    sm = Soumission(
                        reference=f"S-LI-{tag}",
                        title="Salle de bain",
                        client_id=cl.id,
                        status="accepted",
                        subtotal=DEVIS,
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
                    sm_id = sm.id
                proj = Project(
                    name=f"Chantier lignes {tag}",
                    client_id=cl.id,
                    soumission_id=sm_id,
                )
                s.add(proj)
                emp = Employe(full_name=f"Ouvrier {tag}", billing_rate=100)
                s.add(emp)
                await s.flush()
                debut = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
                for h in (4.0, 6.0):
                    s.add(
                        Punch(
                            employe_id=emp.id,
                            project_id=proj.id,
                            started_at=debut,
                            ended_at=debut.replace(hour=12 + int(h)),
                            hours=h,
                            approved=True,
                        )
                    )
                s.add_all(
                    [
                        Achat(
                            project_id=proj.id,
                            description="Céramique et colle",
                            amount=200,
                            kind="material",
                            is_billable=True,
                            markup_percent=10,
                        ),
                        Achat(
                            project_id=proj.id,
                            description="Électricien",
                            amount=500,
                            kind="sub_invoice",
                            is_billable=True,
                            markup_percent=0,
                        ),
                    ]
                )
                await s.commit()
                ids = {
                    "client": cl.id,
                    "soumission": sm_id,
                    "projet": proj.id,
                    "employe": emp.id,
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
                await s.execute(
                    delete(BonTravail).where(
                        BonTravail.client_id == ids["client"]
                    )
                )
                await s.execute(
                    delete(Punch).where(Punch.employe_id == ids["employe"])
                )
                await s.execute(
                    delete(Achat).where(Achat.project_id == ids["projet"])
                )
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
                    delete(Project).where(Project.client_id == ids["client"])
                )
                await s.execute(delete(Employe).where(Employe.id == ids["employe"]))
                if ids["soumission"]:
                    await s.execute(
                        delete(SoumissionItem).where(
                            SoumissionItem.soumission_id == ids["soumission"]
                        )
                    )
                    await s.execute(
                        delete(Soumission).where(
                            Soumission.id == ids["soumission"]
                        )
                    )
                await s.execute(delete(Client).where(Client.id == ids["client"]))
            await s.commit()

    run(_nettoyer())


def _creer_facture(client, headers, projet_id: int, **sources) -> int:
    corps = {
        "include_soumission": False,
        "include_hours": False,
        "include_achats": False,
    }
    corps.update(sources)
    r = client.post(
        f"/api/v1/projects/{projet_id}/convert-to-facture",
        json=corps,
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


def _lignes(client, headers, facture_id: int) -> dict[str, dict]:
    """Lignes de la facture, indexées par un libellé court."""
    r = client.get(f"/api/v1/factures/{facture_id}/items", headers=headers)
    assert r.status_code == 200, r.text
    out: dict[str, dict] = {}
    for it in r.json():
        d = it["description"]
        if "Main-d'œuvre" in d:
            out["main_oeuvre"] = it
        elif "Sous-traitant" in d:
            out["sous_traitant"] = it
        elif d.rsplit("\n", 1)[-1] == "Matériaux":
            out["materiel"] = it
        else:
            out[d] = it
    return out


def _types(lignes: dict[str, dict]) -> dict[str, tuple[str, bool, float]]:
    return {
        k: (v["kind"], v["hors_soumission"], v["total"])
        for k, v in lignes.items()
        if k in ("main_oeuvre", "materiel", "sous_traitant")
    }


def _envoyer(run, facture_id: int) -> None:
    """Statut « envoyée » posé en base (sans courriel ni QuickBooks)."""

    async def _go() -> None:
        async with TestSessionLocal() as s:
            await s.execute(
                update(Facture)
                .where(Facture.id == facture_id)
                .values(status="sent")
            )
            await s.commit()

    run(_go())


def test_projet_sans_soumission_service_et_materiaux(
    chantier, client, auth_headers, run
):
    ids = chantier(avec_soumission=False)

    fid = _creer_facture(
        client,
        auth_headers,
        ids["projet"],
        include_hours=True,
        include_achats=True,
    )

    assert _types(_lignes(client, auth_headers, fid)) == {
        "main_oeuvre": ("service", False, MAIN_OEUVRE),
        "materiel": ("materiaux", False, MATERIEL),
        "sous_traitant": ("service", False, SOUS_TRAITANT),
    }

    # Pas de devis : ce sont les travaux eux-mêmes, pas des extras.
    _envoyer(run, fid)
    fin = client.get(
        f"/api/v1/projects/{ids['projet']}/finances", headers=auth_headers
    ).json()
    assert fin["extras_billed_amount"] == 0.0
    assert fin["invoiced_amount_ex_tax"] == MAIN_OEUVRE + MATERIEL + SOUS_TRAITANT


def test_projet_avec_soumission_hors_soumission_sans_gruger_le_devis(
    chantier, client, auth_headers, run
):
    ids = chantier(avec_soumission=True)

    tm = _creer_facture(
        client,
        auth_headers,
        ids["projet"],
        include_hours=True,
        include_achats=True,
    )
    assert _types(_lignes(client, auth_headers, tm)) == {
        "main_oeuvre": ("service", True, MAIN_OEUVRE),
        "materiel": ("materiaux", True, MATERIEL),
        "sous_traitant": ("service", True, SOUS_TRAITANT),
    }

    # La facture d'avancement suivante facture encore TOUT le devis : les
    # heures et achats importés ne réduisent pas la cible cumulative.
    devis = _creer_facture(
        client,
        auth_headers,
        ids["projet"],
        include_soumission=True,
        soumission_percentage=100,
    )
    lignes_devis = _lignes(client, auth_headers, devis)
    assert round(sum(v["total"] for v in lignes_devis.values()), 2) == DEVIS

    etat = client.get(
        f"/api/v1/projects/{ids['projet']}/etat-contrat", headers=auth_headers
    ).json()
    assert etat["facture_a_date"] == DEVIS
    assert etat["extras_factures"] == MAIN_OEUVRE + MATERIEL + SOUS_TRAITANT
    assert etat["surfactures"] == []

    _envoyer(run, tm)
    fin = client.get(
        f"/api/v1/projects/{ids['projet']}/finances", headers=auth_headers
    ).json()
    assert fin["extras_billed_amount"] == MAIN_OEUVRE + MATERIEL + SOUS_TRAITANT


@pytest.mark.parametrize("avec_soumission", [False, True])
def test_ajouter_des_sources(
    chantier, client, auth_headers, avec_soumission
):
    ids = chantier(avec_soumission=avec_soumission)
    fid = _creer_facture(client, auth_headers, ids["projet"])

    r = client.post(
        f"/api/v1/factures/{fid}/import-sources",
        json={"include_hours": True, "include_achats": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 3

    assert _types(_lignes(client, auth_headers, fid)) == {
        "main_oeuvre": ("service", avec_soumission, MAIN_OEUVRE),
        "materiel": ("materiaux", avec_soumission, MATERIEL),
        "sous_traitant": ("service", avec_soumission, SOUS_TRAITANT),
    }


@pytest.mark.parametrize("avec_soumission", [False, True])
def test_import_d_un_bon(
    chantier, client, auth_headers, run, avec_soumission
):
    ids = chantier(avec_soumission=avec_soumission)
    fid = _creer_facture(client, auth_headers, ids["projet"])

    async def _bon() -> int:
        """Bon complété dont le projet lié porte 3 h et un achat."""
        async with TestSessionLocal() as s:
            tag = uuid.uuid4().hex[:8]
            proj = Project(
                name=f"BT {tag}", client_id=ids["client"], kind="bon_travail"
            )
            s.add(proj)
            await s.flush()
            bon = BonTravail(
                reference=f"BT-LI-{tag}",
                title="Robinet",
                client_id=ids["client"],
                project_id=proj.id,
                status="complete_a_refacturer",
            )
            s.add(bon)
            debut = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
            s.add(
                Punch(
                    employe_id=ids["employe"],
                    project_id=proj.id,
                    started_at=debut,
                    ended_at=debut.replace(hour=15),
                    hours=3,
                    approved=True,
                )
            )
            s.add(
                Achat(
                    project_id=proj.id,
                    description="Robinet",
                    amount=100,
                    kind="material",
                    is_billable=True,
                    markup_percent=0,
                )
            )
            await s.commit()
            return bon.id

    bon_id = run(_bon())
    r = client.post(
        f"/api/v1/factures/{fid}/import-bon",
        json={"bon_id": bon_id},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    lignes = _lignes(client, auth_headers, fid)
    # Heures d'un projet de bon : max(100 $, 90 $) × 3 h.
    assert _types(lignes) == {
        "main_oeuvre": ("service", avec_soumission, 300.0),
        "materiel": ("materiaux", avec_soumission, 100.0),
    }

    # Projet du bon (la fixture nettoie la facture et les punchs).
    async def _nettoyer_bon() -> None:
        async with TestSessionLocal() as s:
            bon = await s.get(BonTravail, bon_id)
            pid = bon.project_id
            await s.execute(delete(Achat).where(Achat.project_id == pid))
            await s.execute(delete(Punch).where(Punch.project_id == pid))
            await s.execute(delete(BonTravail).where(BonTravail.id == bon_id))
            await s.execute(delete(Project).where(Project.id == pid))
            await s.commit()

    run(_nettoyer_bon())


def test_editeur_type_materiaux_et_marque(chantier, client, auth_headers):
    ids = chantier(avec_soumission=True)
    fid = _creer_facture(
        client,
        auth_headers,
        ids["projet"],
        include_soumission=True,
        soumission_percentage=50,
    )

    # Ligne manuelle « Matériaux », hors soumission.
    r = client.post(
        f"/api/v1/factures/{fid}/items",
        json={
            "description": "Quincaillerie",
            "quantity": 1,
            "unit_price": 80,
            "kind": "materiaux",
            "hors_soumission": True,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    manuelle = r.json()
    assert (manuelle["kind"], manuelle["hors_soumission"]) == ("materiaux", True)

    # Basculer la marque : la ligne compte de nouveau dans le devis.
    r = client.patch(
        f"/api/v1/factures/{fid}/items/{manuelle['id']}",
        json={"hors_soumission": False},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["hors_soumission"] is False
    assert r.json()["kind"] == "materiaux"

    # Une ligne rattachée au devis n'est jamais hors soumission.
    lie = next(
        v
        for v in _lignes(client, auth_headers, fid).values()
        if v["soumission_item_id"]
    )
    r = client.patch(
        f"/api/v1/factures/{fid}/items/{lie['id']}",
        json={"hors_soumission": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["hors_soumission"] is False

    # Type inconnu toujours refusé.
    r = client.patch(
        f"/api/v1/factures/{fid}/items/{lie['id']}",
        json={"kind": "materiel"},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_reclassement_des_brouillons_existants(
    chantier, client, auth_headers, run
):
    """Factures créées AVANT le correctif (lignes « extra ») : seuls les
    brouillons sont reclassés, et seulement leurs lignes importées."""
    avec = chantier(avec_soumission=True)
    sans = chantier(avec_soumission=False)
    brouillon_avec = _creer_facture(
        client, auth_headers, avec["projet"], include_hours=True, include_achats=True
    )
    brouillon_sans = _creer_facture(
        client, auth_headers, sans["projet"], include_hours=True, include_achats=True
    )
    envoyee = _creer_facture(client, auth_headers, sans["projet"])

    async def _ancien_etat() -> int:
        """Remet les lignes importées comme l'ancien code les créait, et
        ajoute un extra manuel + une ligne importée sur une facture
        envoyée."""
        async with TestSessionLocal() as s:
            await s.execute(
                update(FactureItem)
                .where(FactureItem.facture_id.in_([brouillon_avec, brouillon_sans]))
                .values(kind="extra", hors_soumission=False)
            )
            manuel = FactureItem(
                facture_id=brouillon_sans,
                position=99,
                description="Ajout d'une prise",
                quantity=1,
                unit_price=150,
                total=150,
                kind="extra",
            )
            importee_envoyee = FactureItem(
                facture_id=envoyee,
                position=0,
                description="Main-d'œuvre",
                unit="h",
                quantity=1,
                unit_price=90,
                total=90,
                kind="extra",
            )
            s.add_all([manuel, importee_envoyee])
            await s.flush()
            # La ligne de la facture envoyée porte un punch (importée).
            punch = (
                await s.execute(
                    select(Punch).where(Punch.employe_id == sans["employe"])
                )
            ).scalars().first()
            s.add(
                Punch(
                    employe_id=sans["employe"],
                    project_id=sans["projet"],
                    started_at=punch.started_at,
                    hours=1,
                    approved=True,
                    invoiced_at=punch.started_at,
                    facture_item_id=importee_envoyee.id,
                )
            )
            await s.execute(
                update(Facture).where(Facture.id == envoyee).values(status="sent")
            )
            await s.commit()
            return manuel.id

    manuel_id = run(_ancien_etat())

    async def _reclasser() -> int:
        async with TestSessionLocal() as s:
            n = await reclasser_lignes_importees_brouillons(s)
            await s.commit()
            return n

    assert run(_reclasser()) == 6

    assert _types(_lignes(client, auth_headers, brouillon_avec)) == {
        "main_oeuvre": ("service", True, MAIN_OEUVRE),
        "materiel": ("materiaux", True, MATERIEL),
        "sous_traitant": ("service", True, SOUS_TRAITANT),
    }
    lignes_sans = _lignes(client, auth_headers, brouillon_sans)
    assert _types(lignes_sans) == {
        "main_oeuvre": ("service", False, MAIN_OEUVRE),
        "materiel": ("materiaux", False, MATERIEL),
        "sous_traitant": ("service", False, SOUS_TRAITANT),
    }
    # Extra saisi à la main et facture envoyée : intacts.
    assert lignes_sans["Ajout d'une prise"]["id"] == manuel_id
    assert lignes_sans["Ajout d'une prise"]["kind"] == "extra"
    assert _lignes(client, auth_headers, envoyee)["main_oeuvre"]["kind"] == "extra"

    # Rejouer ne change plus rien.
    assert run(_reclasser()) == 0
