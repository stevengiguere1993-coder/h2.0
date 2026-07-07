"""Smoke — invariants d'ORDRE des routers (P-09).

``app/api/v1/router.py`` porte ~15 contraintes d'ordre d'``include_router``
UNIQUEMENT sous forme de commentaires : certains routers à path littéral
(ex. ``/punch/me``, ``/prospection/lists``) DOIVENT être enregistrés AVANT
le router CRUD générique qui expose ``/{item_id}`` sur le même préfixe.
Un simple réordonnancement (tri automatique des imports, refactor) casse
ces endpoints en 404/422 SANS aucun échec CI — c'est précisément ce trou
que ce filet ferme.

Principe : pour une liste de paths sensibles, on résout la route via le
routage RÉEL de l'app (dispatch ASGI, qui pose ``scope["route"]`` avant
d'exécuter l'endpoint) et on asserte que la fonction gagnante est bien
celle attendue — identifiée par (nom, MODULE). Le module est essentiel :
des noms génériques comme ``list_items``/``get_item`` existent dans 15-20
routers, donc le seul nom ne prouverait pas que le BON router a gagné le
match. Le couple (nom, module) le prouve.

Ces tests FIGENT l'état correct actuel : ils passent sur le code présent
et n'échoueront que si l'ordre d'``include_router`` régresse.
"""

from __future__ import annotations

import asyncio

import pytest

from app.main import app as fastapi_app


# ── Résolution de route via le dispatch ASGI réel ───────────────────
# On n'essaie PAS de reconstruire les chemins à la main (le router de
# cette version de FastAPI utilise des _IncludedRouter lazy dont les
# préfixes se recomposent de façon non triviale). On laisse plutôt l'app
# router la requête EXACTEMENT comme en prod : FastAPI pose
# ``scope["route"]`` = l'APIRoute gagnante juste avant d'appeler
# l'endpoint. On lit ce contrat public (aucune API privée), sans avoir
# besoin d'un token valide : la garde d'auth s'exécute APRÈS la
# résolution de route, donc un 401 n'empêche pas ``scope["route"]``
# d'être renseigné.


async def _resolve(path: str, method: str):
    """Route ``method path`` à travers l'app et retourne (nom, module) de
    l'endpoint gagnant, ou ``None`` si aucune route ne matche (404)."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
        "root_path": "",
        "app": fastapi_app,
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):  # noqa: ANN001 — on ignore la réponse
        return None

    # L'endpoint peut lever (DB absente, 401, etc.) : peu importe, la
    # résolution de route a déjà eu lieu et ``scope["route"]`` est posé.
    try:
        await fastapi_app(scope, receive, send)
    except Exception:  # noqa: BLE001 — on ne teste QUE le routage
        pass

    route = scope.get("route")
    if route is None or not hasattr(route, "endpoint"):
        return None
    return (route.endpoint.__name__, route.endpoint.__module__)


def _resolve_sync(loop, path: str, method: str):
    return loop.run_until_complete(_resolve(path, method))


# ── Table des invariants d'ordre (path, method) → (fonction, module) ──
# Chaque ligne correspond à une contrainte d'ordre COMMENTÉE dans
# router.py. La colonne module prouve que le router littéral a gagné le
# match face au router CRUD générique du même préfixe.
ORDER_INVARIANTS = [
    # punch_ops AVANT punch_router (business) : sinon "/me", "/weekly"
    # sont coercés en int par /{item_id} → 422.
    ("/api/v1/punch/me", "GET", "punch_me", "app.api.v1.endpoints.punch_ops"),
    ("/api/v1/punch/weekly", "GET", "weekly_report", "app.api.v1.endpoints.punch_ops"),
    ("/api/v1/punch/clock-in", "POST", "clock_in", "app.api.v1.endpoints.punch_ops"),
    # payments AVANT facture_items : /factures/{id}/payments ne doit PAS
    # être avalé par /factures/{id}/items.
    (
        "/api/v1/factures/5/payments",
        "GET",
        "list_payments",
        "app.api.v1.endpoints.payments",
    ),
    (
        "/api/v1/factures/5/items",
        "GET",
        "list_items",
        "app.api.v1.endpoints.facture_items",
    ),
    # achat_receipt AVANT achats_router (business) : /achats/{id}/receipt
    # ne doit pas voir "receipt" parsé comme int par /achats/{item_id}.
    (
        "/api/v1/achats/5/receipt",
        "GET",
        "download_receipt",
        "app.api.v1.endpoints.achat_receipt",
    ),
    # agenda_unified AVANT agenda_router (business) : /agenda/unified
    # littéral avant /agenda/{item_id}.
    (
        "/api/v1/agenda/unified",
        "GET",
        "unified_agenda",
        "app.api.v1.endpoints.agenda_unified",
    ),
    # prospection_lists / prospection_deals / prospection_analyse_extract
    # AVANT prospection.router : littéraux avant /prospection/{lead_id}.
    (
        "/api/v1/prospection/lists",
        "GET",
        "list_all",
        "app.api.v1.endpoints.prospection_lists",
    ),
    (
        "/api/v1/prospection/deals",
        "GET",
        "list_deals",
        "app.api.v1.endpoints.prospection_deals",
    ),
    (
        "/api/v1/prospection/analyses/extract",
        "POST",
        "extract_inputs",
        "app.api.v1.endpoints.prospection_analyse_extract",
    ),
    # entreprise_extras / entreprise_partners_links AVANT entreprises.router :
    # /entreprises/finance/* et /entreprises/partners avant /entreprises/{id}.
    (
        "/api/v1/entreprises/finance/summaries",
        "GET",
        "list_finance_summaries",
        "app.api.v1.endpoints.entreprise_extras",
    ),
    (
        "/api/v1/entreprises/partners",
        "POST",
        "create_partner",
        "app.api.v1.endpoints.entreprise_partners_links",
    ),
    # immobilier_extras AVANT immobilier.router : /immobilier/tal/* et
    # /immobilier/renouvellements/* avant les routes génériques.
    (
        "/api/v1/immobilier/tal/forms",
        "GET",
        "list_tal_forms",
        "app.api.v1.endpoints.immobilier_extras",
    ),
    # rencontres_teams AVANT rencontres.router : /rencontres/teams-sync/*
    # ne doit pas être avalé par /rencontres/{id}.
    (
        "/api/v1/rencontres/teams-sync/status",
        "GET",
        "teams_sync_status",
        "app.api.v1.endpoints.rencontres_teams",
    ),
]


@pytest.mark.parametrize(
    "path,method,func_name,func_module",
    ORDER_INVARIANTS,
    ids=[f"{m} {p}" for p, m, *_ in ORDER_INVARIANTS],
)
def test_sensitive_path_resolves_to_expected_endpoint(
    loop, path, method, func_name, func_module
):
    """Le path littéral résout vers SON endpoint, pas vers le CRUD générique."""
    resolved = _resolve_sync(loop, path, method)
    assert resolved is not None, (
        f"{method} {path} ne résout vers AUCUNE route (404) — un router a "
        f"probablement changé de préfixe ou disparu."
    )
    got_name, got_module = resolved
    assert (got_name, got_module) == (func_name, func_module), (
        f"{method} {path} devrait résoudre vers {func_name} "
        f"({func_module}) mais résout vers {got_name} ({got_module}). "
        f"Régression probable de l'ordre d'include_router dans "
        f"app/api/v1/router.py (le CRUD générique avale le path littéral)."
    )


# ── Contre-épreuves : le CRUD générique reste joignable pour les IDs ──
# On vérifie que les paths génériques /{id} tombent bien sur le router
# CRUD (module « propriétaire » du préfixe). Cela garantit que déplacer
# les littéraux devant NE casse PAS le CRUD, et que le match numérique
# n'est pas capturé par un sous-router littéral.
GENERIC_FALLBACKS = [
    # /punch/{id} numérique → punch_router (business), pas punch_ops.
    ("/api/v1/punch/5", "GET", "app.api.v1.endpoints.business"),
    # /prospection/{lead_id} numérique → prospection.router.
    ("/api/v1/prospection/5", "GET", "app.api.v1.endpoints.prospection"),
]


@pytest.mark.parametrize(
    "path,method,func_module",
    GENERIC_FALLBACKS,
    ids=[f"{m} {p}" for p, m, *_ in GENERIC_FALLBACKS],
)
def test_generic_id_path_falls_back_to_crud_router(
    loop, path, method, func_module
):
    """Un ID numérique tombe bien sur le router CRUD générique du préfixe."""
    resolved = _resolve_sync(loop, path, method)
    assert resolved is not None, f"{method} {path} ne résout vers aucune route."
    _got_name, got_module = resolved
    assert got_module == func_module, (
        f"{method} {path} devrait tomber sur le router CRUD "
        f"({func_module}) mais résout vers {got_module}."
    )
