"""Smoke — catalogue de matériaux : l'extraction des prix ne bloque plus
(bug 15, Steven 2026-10-03 : « Catalogue à travailler, extraction bloque »).

Avant : les trois domaines d'un relevé partageaient UNE AsyncSession
(« another operation is in progress » tuait la course au hasard et
perdait tout ce qui avait été lu), un VPS injoignable faisait attendre le
délai réseau pour CHAQUE offre Rona/BMR, et une course (bouton ou cron)
sans durée maximale ni bouton d'arrêt laissait « déjà en cours » pendant
des heures.

Couvre :
1. relevé avec une session par domaine : un domaine qui bloque (VPS
   injoignable) n'est interrogé qu'une fois, ses autres offres sont
   marquées ; les autres domaines lisent leurs prix (historique écrit) ;
   stats en direct (examinées, lus, échecs, dernier) ;
2. arrêt à la demande : la course est annulée, l'état « en cours » libéré,
   les stats disent « arrêté » ;
3. durée maximale : une course trop longue s'arrête d'elle-même ;
4. route POST /materiaux/prix/arreter : rien en cours → ``arrete`` faux ;
   course en cours → ``arrete`` vrai et état libéré ; GET …/etat porte
   ``duree_s`` ; un employé n'a pas le droit.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.materiau import Magasin, Materiau, MateriauOffre, MateriauPrixHistorique
from app.services import materiaux_prix_auto as mpa
from app.services import prix_magasins as pm
from app.services.materiaux_import import norm_key
from tests.smoke.conftest import TestSessionLocal

PAGE_PRIX = (
    '<html><head><script type="application/ld+json">'
    '{"@type": "Product", "name": "Vis à bois 2 po", '
    '"offers": {"@type": "Offer", "price": "12.99", "priceCurrency": "CAD"}}'
    "</script></head><body>ok</body></html>"
)

URLS = [
    "https://www.lit-ok.test/produit/vis-2po-1",
    "https://www.lit-ok.test/produit/vis-2po-2",
    "https://www.bloque.test/p/1",
    "https://www.bloque.test/p/2",
    "https://www.bloque.test/p/3",
    "https://www.sans-prix.test/p/1",
]


@pytest.fixture()
def jeu(run, db_setup) -> dict:
    """Un magasin et six matériaux, chacun avec une offre liée : deux pages
    lisibles, trois sur un site que le VPS ne sert pas, une sans prix."""

    async def _go() -> dict:
        async with TestSessionLocal() as s:
            tag = uuid.uuid4().hex[:8]
            mag = Magasin(name=f"Quincaillerie test {tag}", is_active=True)
            s.add(mag)
            await s.flush()
            ids: list[int] = []
            for i, url in enumerate(URLS):
                m = Materiau(name=f"Matériau {tag} {i}", name_key=norm_key(f"Matériau {tag} {i}"), is_active=True)
                s.add(m)
                await s.flush()
                off = MateriauOffre(materiau_id=m.id, magasin_id=mag.id, url=url, source="manual")
                s.add(off)
                await s.flush()
                ids.append(off.id)
            await s.commit()
            return {"magasin_id": mag.id, "offre_ids": ids}

    return run(_go())


def test_releve_une_session_par_domaine_et_court_circuit(run, jeu, monkeypatch):
    appels: list[str] = []

    async def faux_fetch(url: str):
        appels.append(url)
        dom = pm.domain_of(url)
        if dom == "bloque.test":
            raise pm.FetchBlocked("VPS de scraping injoignable (test) : ce site exige un navigateur.")
        if dom == "sans-prix.test":
            return "<html><body>rien ici</body></html>", "http"
        return PAGE_PRIX, "http"

    monkeypatch.setattr(mpa, "fetch_page", faux_fetch)
    monkeypatch.setattr(mpa, "PAUSE_PAR_DOMAINE", 0.0)
    live: dict = {}

    async def _go() -> dict:
        async with TestSessionLocal() as db:
            return await mpa.relever_tout(
                db, magasin_id=jeu["magasin_id"], session_factory=TestSessionLocal, stats_live=live,
            )

    stats = run(_go())
    assert stats is live
    assert stats["offres"] == 6 and stats["examinees"] == 6
    assert stats["ok"] == 2 and stats["echecs"] == 4 and stats["changes"] == 2
    assert stats["dernier"] is not None and stats["dernier"]["a"]
    # Le site bloqué n'a été interrogé qu'UNE fois : les deux autres offres
    # ont été marquées sans attendre un délai réseau chacune.
    assert sum(1 for u in appels if "bloque.test" in u) == 1
    assert stats["par_domaine"]["bloque.test"] == {"ok": 0, "echecs": 3}
    assert stats["par_domaine"]["lit-ok.test"] == {"ok": 2, "echecs": 0}

    async def _verifier() -> None:
        async with TestSessionLocal() as s:
            offres = (await s.execute(
                select(MateriauOffre).where(MateriauOffre.id.in_(jeu["offre_ids"])).order_by(MateriauOffre.id)
            )).scalars().all()
            par_url = {o.url: o for o in offres}
            for url in URLS[:2]:
                o = par_url[url]
                assert float(o.unit_price) == 12.99 and o.source == "auto" and o.fetch_error is None
                assert o.page_title == "Vis à bois 2 po"
                hist = (await s.execute(
                    select(MateriauPrixHistorique).where(MateriauPrixHistorique.materiau_id == o.materiau_id)
                )).scalars().all()
                assert len(hist) == 1 and float(hist[0].unit_price) == 12.99
            for url in URLS[2:5]:
                o = par_url[url]
                assert o.unit_price is None
                assert o.fetch_checked_at is not None
                assert "VPS de scraping injoignable" in (o.fetch_error or "")
            o = par_url[URLS[5]]
            assert o.unit_price is None and "Aucun prix" in (o.fetch_error or "")

    run(_verifier())


def _course_longue(monkeypatch, drapeau: dict):
    """Remplace la course par une attente de 30 s (annulable)."""

    async def faux_relever_tout(db, **kwargs):
        drapeau["lance"] = True
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr(mpa, "relever_tout", faux_relever_tout)


def test_arret_a_la_demande_libere_l_etat(run, db_setup, monkeypatch):
    drapeau: dict = {}
    _course_longue(monkeypatch, drapeau)

    async def _go() -> dict:
        assert not mpa.DERNIER_RELEVE["en_cours"]
        tache = mpa.lancer_releve_en_fond()
        assert tache is not None
        await asyncio.sleep(0.05)
        assert mpa.DERNIER_RELEVE["en_cours"] is True and drapeau.get("lance")
        assert mpa.lancer_releve_en_fond() is None  # un seul run à la fois
        assert mpa.annuler_releve() is True
        stats = await tache
        assert mpa.DERNIER_RELEVE["en_cours"] is False
        assert mpa.DERNIER_RELEVE["termine_a"]
        return stats

    stats = run(_go())
    assert stats["annule"] is True and "Arrêté à la demande" in stats["error"]
    assert mpa.annuler_releve() is False  # plus rien à arrêter


def test_duree_maximale_libere_l_etat(run, db_setup, monkeypatch):
    drapeau: dict = {}
    _course_longue(monkeypatch, drapeau)
    monkeypatch.setattr(mpa, "DUREE_MAX_RELEVE_S", 0.2)

    async def _go() -> dict:
        tache = mpa.lancer_releve_en_fond()
        assert tache is not None
        return await tache

    stats = run(_go())
    assert "durée maximale" in stats["error"] and not stats.get("annule")
    assert mpa.DERNIER_RELEVE["en_cours"] is False


def test_route_arreter_et_etat(run, client, auth_headers, employee_headers, db_setup, monkeypatch):
    # Rien en cours : la route répond sans rien casser.
    r = client.post("/api/v1/materiaux/prix/arreter", json={"job": "releve"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["arrete"] is False and r.json()["en_cours"] is False
    # Un employé ne pilote pas le catalogue.
    r = client.post("/api/v1/materiaux/prix/arreter", json={"job": "recherche"}, headers=employee_headers)
    assert r.status_code == 403
    # Job inconnu refusé.
    r = client.post("/api/v1/materiaux/prix/arreter", json={"job": "autre"}, headers=auth_headers)
    assert r.status_code == 422

    drapeau: dict = {}
    _course_longue(monkeypatch, drapeau)

    async def _lancer():
        tache = mpa.lancer_releve_en_fond()
        await asyncio.sleep(0.05)
        return tache

    tache = run(_lancer())
    assert tache is not None and mpa.DERNIER_RELEVE["en_cours"]
    r = client.get("/api/v1/materiaux/prix/etat", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["en_cours"] is True and isinstance(r.json()["duree_s"], int)
    assert r.json()["duree_max_s"] == mpa.DUREE_MAX_RELEVE_S
    # Relancer pendant la course : refusé, avec la raison et la durée.
    r = client.post("/api/v1/materiaux/prix/relever-tout", json={}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["lance"] is False and "déjà en cours" in r.json()["raison"]

    r = client.post("/api/v1/materiaux/prix/arreter", json={"job": "releve"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["arrete"] is True and r.json()["en_cours"] is False
    assert r.json()["stats"]["annule"] is True
    run(tache)
    r = client.get("/api/v1/materiaux/prix/etat", headers=auth_headers)
    assert r.json()["en_cours"] is False and r.json()["stats"]["annule"] is True


def test_duree_lisible_et_avec_duree():
    assert mpa.duree_lisible(42) == "42 s"
    assert mpa.duree_lisible(540) == "9 min"
    assert mpa.duree_lisible(7320) == "2 h 02 min"
    debut = datetime(2026, 10, 18, 2, 0, tzinfo=timezone.utc)
    fin = datetime(2026, 10, 18, 2, 9, tzinfo=timezone.utc)
    etat = {"en_cours": False, "lance_a": debut.isoformat(), "termine_a": fin.isoformat(), "stats": {"ok": 1}}
    out = mpa.avec_duree(etat)
    assert out["duree_s"] == 540 and out["stats"] == {"ok": 1}
    assert out is not etat and out["stats"] is not etat["stats"]
    assert mpa.avec_duree({"en_cours": False, "lance_a": None})["duree_s"] is None
