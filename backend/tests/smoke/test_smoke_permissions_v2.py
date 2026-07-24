"""Smoke — permissions v2 (2026-07-24) : la résolution d'accès unifiée.

Scénario d'origine (retour Phil) : un EMPLOYÉ avec les volets
entreprises (page feuille de temps seulement, par rôle) + immobilier
doit voir les deux pôles — plus aucun rôle codé en dur ni whitelist
d'emails :

- volets accordés → pages du volet selon le seuil de rôle ;
- exception de page (user_access_overrides) → la page s'ouvre ET le
  volet dérive à True (tuile + layout + API via user_has_volet_access) ;
- exception refusée → la page ferme (et le volet suit si plus rien) ;
- User.volets ne dépend plus de l'email (whitelists retirées) ;
- le registre couvre les pages auparavant orphelines (paie, etc.).
"""
import json

from sqlalchemy import delete

from app.core.access_registry import PAGES_BY_KEY
from app.models.user import DEFAULT_VOLETS, User
from app.models.user_access_override import UserAccessOverride
from app.services.access_service import (
    compute_access,
    user_has_volet_access,
)

from tests.smoke.conftest import TestSessionLocal


def _set_volets(run, user_id: int, volets):
    async def _do():
        async with TestSessionLocal() as s:
            u = await s.get(User, user_id)
            u.volets_json = json.dumps(volets) if volets is not None else None
            await s.commit()

    run(_do())


def _clear_overrides(run, user_id: int):
    async def _do():
        async with TestSessionLocal() as s:
            await s.execute(
                delete(UserAccessOverride).where(
                    UserAccessOverride.user_id == user_id
                )
            )
            await s.commit()

    run(_do())


def _access(run, user_id: int) -> dict:
    async def _do():
        async with TestSessionLocal() as s:
            u = await s.get(User, user_id)
            return await compute_access(s, u)

    return run(_do())


def test_employee_volet_grant_opens_pages(run, employee_id):
    """Le scénario Phil : employé + volets entreprises/immobilier →
    feuille de temps visible (seuil employé), pages admin fermées,
    les DEUX volets ouverts."""
    try:
        _set_volets(run, employee_id, ["entreprises", "immobilier"])
        access = _access(run, employee_id)
        assert access["page:entreprises.feuille_de_temps"] is True
        assert access["page:entreprises.kratos"] is False  # seuil admin
        assert access["volet:entreprises"] is True
        assert access["volet:immobilier"] is True
        # Volet non coché → fermé.
        assert access["volet:prospection"] is False
    finally:
        _set_volets(run, employee_id, None)


def test_page_override_opens_volet_and_api(run, employee_id):
    """Une exception de page SANS le volet ouvre la page, dérive le
    volet à True et ouvre les routeurs API (require_volet v2)."""
    try:
        _set_volets(run, employee_id, ["construction"])

        async def _grant():
            async with TestSessionLocal() as s:
                s.add(
                    UserAccessOverride(
                        user_id=employee_id,
                        key="page:entreprises.feuille_de_temps",
                        allow=True,
                    )
                )
                await s.commit()

        run(_grant())
        access = _access(run, employee_id)
        assert access["page:entreprises.feuille_de_temps"] is True
        assert access["volet:entreprises"] is True  # dérivé de la page

        async def _api_check():
            async with TestSessionLocal() as s:
                u = await s.get(User, employee_id)
                return await user_has_volet_access(s, u, "entreprises")

        assert run(_api_check()) is True
    finally:
        _clear_overrides(run, employee_id)
        _set_volets(run, employee_id, None)

    # Sans l'exception : volet et API fermés.
    _set_volets(run, employee_id, ["construction"])
    try:
        access = _access(run, employee_id)
        assert access["volet:entreprises"] is False

        async def _api_check2():
            async with TestSessionLocal() as s:
                u = await s.get(User, employee_id)
                return await user_has_volet_access(s, u, "entreprises")

        assert run(_api_check2()) is False
    finally:
        _set_volets(run, employee_id, None)


def test_deny_override_closes_page_and_volet(run, employee_id):
    """Une exception refusée ferme la page — et le volet suit quand
    plus aucune page n'y est accessible."""
    try:
        _set_volets(run, employee_id, ["entreprises"])

        async def _deny():
            async with TestSessionLocal() as s:
                s.add(
                    UserAccessOverride(
                        user_id=employee_id,
                        key="page:entreprises.feuille_de_temps",
                        allow=False,
                    )
                )
                await s.commit()

        run(_deny())
        access = _access(run, employee_id)
        assert access["page:entreprises.feuille_de_temps"] is False
        # Feuille de temps était la SEULE page employé du volet → fermé.
        assert access["volet:entreprises"] is False
    finally:
        _clear_overrides(run, employee_id)
        _set_volets(run, employee_id, None)


def test_volets_ignore_email_whitelists():
    """Les whitelists d'emails en dur sont retirées : un employé avec un
    email autrefois whitelisté n'a QUE ses volets configurés."""
    u = User(
        email="pmeuser@immohorizon.com",
        hashed_password="x",
        role="employee",
        volets_json=None,
    )
    assert sorted(u.volets) == sorted(DEFAULT_VOLETS)
    u2 = User(
        email="pmeuser@immohorizon.com",
        hashed_password="x",
        role="employee",
        volets_json=json.dumps(["immobilier"]),
    )
    assert u2.volets == ["immobilier"]


def test_registry_covers_orphan_pages():
    """Les pages qui héritaient silencieusement d'une racine de pôle ont
    leur entrée propre (et la bonne sévérité pour les sensibles)."""
    assert PAGES_BY_KEY["construction.paie"].default_min_role == "admin"
    assert (
        PAGES_BY_KEY["immobilier.utilisateurs"].default_min_role == "admin"
    )
    for key in (
        "construction.communications",
        "construction.suivis",
        "immobilier.diagnostic",
        "prospection.comparables",
        "prospection.kanban",
        "entreprises.plan_suivi",
        "general.dev_tools",
        "general.letmetalk",
        "general.devlog_contact",
    ):
        assert key in PAGES_BY_KEY, key
    # Entrée fantôme retirée (aucune page frontend correspondante).
    assert "entreprises.projets" not in PAGES_BY_KEY
