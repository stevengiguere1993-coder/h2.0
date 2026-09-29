"""Smoke — feuille de temps : les fiches du module Entreprises apparaissent
automatiquement dans la liste des compagnies (Phil 2026-09-29 : « la page
feuille de temps ne rajoute pas automatiquement les nouvelles entreprises,
Groupe 1660 Saint-Clément devrait y être »)."""
from __future__ import annotations

from sqlalchemy import select, update

from app.api.v1.endpoints.timesheets import _cle_label, _meme_compagnie
from app.models.entreprise import Entreprise
from app.models.timesheet import TimesheetCompany

from tests.smoke.conftest import TestSessionLocal


def test_cles_de_rapprochement():
    assert _cle_label("Côte-Saint-Luc Inc.") == _cle_label("cote-saint-luc inc")
    assert _meme_compagnie(_cle_label("9417-1287"), _cle_label("9417-1287 Québec inc."))
    assert _meme_compagnie("bgv", "bgv")
    assert not _meme_compagnie("bgv", "bgv immobilier")  # trop court pour extrapoler
    assert not _meme_compagnie("immo bgvm", "immo meuser")


def test_entreprises_ajoutees_automatiquement(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            e1 = Entreprise(name="Groupe 1660 Saint-Clément")
            e2 = Entreprise(name="Ancienne INC fermée", is_active=False)
            # Déjà dans la liste initiale des compagnies (« BGV ») → liaison,
            # pas de doublon.
            e3 = Entreprise(name="BGV")
            # Compagnie saisie à la main sous une forme courte → reconnue.
            e4 = Entreprise(name="9417-1287 Québec inc.")
            s.add_all([e1, e2, e3, e4])
            await s.commit()
            return e1.id, e2.id, e3.id, e4.id

    id1, id2, id3, id4 = run(_seed())

    r = client.get(
        "/api/v1/timesheets/companies?include_inactive=true", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    par_label = {c["label"]: c for c in rows}
    assert par_label["Groupe 1660 Saint-Clément"]["entreprise_id"] == id1
    assert par_label["Groupe 1660 Saint-Clément"]["is_active"] is True
    assert "Ancienne INC fermée" not in par_label  # fiche inactive : jamais créée
    assert [c for c in rows if _cle_label(c["label"]) == "bgv"] == [par_label["BGV"]]
    assert par_label["BGV"]["entreprise_id"] == id3
    # « 9417-1287 » (liste initiale) reconnue et renommée au nom de la fiche.
    assert "9417-1287" not in par_label
    assert par_label["9417-1287 Québec inc."]["entreprise_id"] == id4
    assert sum(1 for c in rows if c["label"].startswith("9417-1287")) == 1

    # Renommage + désactivation de la fiche → la compagnie suit.
    async def _modifier():
        async with TestSessionLocal() as s:
            await s.execute(
                update(Entreprise)
                .where(Entreprise.id == id1)
                .values(name="Groupe 1660 Saint-Clément inc.")
            )
            await s.execute(
                update(Entreprise).where(Entreprise.id == id4).values(is_active=False)
            )
            await s.commit()

    run(_modifier())
    r = client.get(
        "/api/v1/timesheets/companies?include_inactive=true", headers=auth_headers
    )
    rows = r.json()
    par_id = {c["entreprise_id"]: c for c in rows if c["entreprise_id"]}
    assert par_id[id1]["label"] == "Groupe 1660 Saint-Clément inc."
    assert par_id[id4]["is_active"] is False

    # Idempotent : un second passage ne crée rien.
    async def _compte():
        async with TestSessionLocal() as s:
            return len((await s.execute(select(TimesheetCompany))).scalars().all())

    n1 = run(_compte())
    client.get("/api/v1/timesheets/companies?include_inactive=true", headers=auth_headers)
    assert run(_compte()) == n1
