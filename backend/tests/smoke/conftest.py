"""Fixtures des smoke tests d'API (SQLite async, sans réseau).

Architecture :
- Les env vars factices sont posées par ``tests/conftest.py`` (parent),
  AVANT tout import de l'app — DATABASE_URL pointe déjà sur un fichier
  SQLite temporaire quand ce module importe ``app.main``.
- JSONB est compilé en « JSON » sous SQLite (3 modèles utilisent JSONB :
  devlog_soumission_defaults, lead_analysis, prospection_analysis_default).
- Un SEUL event loop pour toute la session de tests : l'engine async
  (aiosqlite) garde ses connexions liées au loop qui les a créées —
  un loop par test casserait le pool. Les tests sont écrits en SYNC et
  passent par ``SyncClient`` / ``run`` qui délèguent au loop partagé.
- Client HTTP : ``httpx.AsyncClient(transport=ASGITransport(app))`` SANS
  lifespan — les tâches de démarrage (init_db / ensure_*) sont pensées
  Postgres et ne tournent pas ici. ``get_db`` est overridé vers une
  session de test (même comportement commit/rollback que la prod).
- Seeds : un admin + un employé (mot de passe connu, hash passlib) et
  une clé d'API ``krts_…`` insérée directement en DB (hash SHA-256),
  comme le ferait POST /api-keys.

NE MODIFIE AUCUN CODE DE PRODUCTION — fixtures de test uniquement.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import pytest

# ── 1) Compilation SQLite des types Postgres-only ───────────────────
# À enregistrer AVANT tout create_all. JSONB n'existe pas sous SQLite ;
# on le compile en JSON (le sérialiseur/désérialiseur JSON de SQLAlchemy
# fonctionne pareil). DDL + lecture/écriture couverts.
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, D103
    return "JSON"


# ── 2) Imports de l'app (env déjà posé par tests/conftest.py) ───────
import app.models  # noqa: F401 — enregistre TOUS les modèles sur Base.metadata
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.api_key_deps import hash_api_key
from app.core.security import create_access_token, get_password_hash
from app.db.base import Base
from app.db.session import engine as app_engine
from app.db.session import get_db
from app.main import app as fastapi_app
from app.models.api_key import ApiKey
from app.models.user import User


# ── Constantes de seed (réutilisées par les tests) ──────────────────

ADMIN_EMAIL = "smoke-admin@example.com"
ADMIN_PASSWORD = "Sm0keAdmin!42"
EMPLOYEE_EMAIL = "smoke-employe@example.com"
EMPLOYEE_PASSWORD = "Sm0keEmploye!42"
API_KEY_PLAINTEXT = "krts_smoketest0123456789abcdefghijklmnopqrstuv"


# ── Session factory de test (même fichier SQLite que l'app) ─────────
# On réutilise l'engine de l'app (il pointe déjà sur le SQLite de test
# via DATABASE_URL) : un seul pool de connexions, un seul loop.
TestSessionLocal = async_sessionmaker(
    app_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def _override_get_db():
    """Réplique le contrat de ``app.db.session.get_db`` (commit en fin de
    requête, rollback sur exception) sur la session de test."""
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


fastapi_app.dependency_overrides[get_db] = _override_get_db


# ── Event loop unique pour toute la session ─────────────────────────


@pytest.fixture(scope="session")
def loop():
    lp = asyncio.new_event_loop()
    yield lp
    # Draine les éventuelles tâches fire-and-forget encore en vol
    # (autoscore IA, notifications…) avant de fermer proprement.
    try:
        pending = asyncio.all_tasks(lp)
        for t in pending:
            t.cancel()
        if pending:
            lp.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        lp.run_until_complete(app_engine.dispose())
    finally:
        lp.close()


@pytest.fixture(scope="session")
def run(loop):
    """Helper : exécute une coroutine sur le loop partagé (seed DB, etc.)."""

    def _run(coro):
        return loop.run_until_complete(coro)

    return _run


# ── Base de données : création du schéma + seeds ────────────────────


def _stub_unresolved_fk_targets() -> list[str]:
    """Filet DÉFENSIF : ajoute au metadata une table STUB pour chaque cible
    de ForeignKey introuvable, afin que ``create_all`` puisse trier.

    En fonctionnement normal, cette fonction ne stubbe RIEN (retourne
    ``[]``) : le schéma du modèle est cohérent. Elle reste comme garde
    anti-crash au cas où une FK cassée réapparaîtrait — auquel cas
    ``test_smoke_schema.py`` échoue et signale la régression (une FK
    orpheline fait replanter ``init_db`` en prod, cf. P-02, l'incident
    ``immeubles``→``imm_immeubles`` corrigé le 2026-07-07).

    Boucle générique : tant que le tri des tables lève
    NoReferencedTableError, on stubbe la table manquante (max 10).
    Retourne la liste des tables stubbées (pour trace/debug)."""
    from sqlalchemy import Column, Integer, Table
    from sqlalchemy.exc import NoReferencedTableError

    stubbed: list[str] = []
    for _ in range(10):
        try:
            Base.metadata.sorted_tables  # force la résolution des FK
            break
        except NoReferencedTableError as exc:
            missing = getattr(exc, "table_name", None)
            if not missing or missing in Base.metadata.tables:
                raise
            Table(missing, Base.metadata, Column("id", Integer, primary_key=True))
            stubbed.append(missing)
    return stubbed


@pytest.fixture(scope="session")
def db_setup(run):
    _stub_unresolved_fk_targets()

    async def _create_all():
        async with app_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    run(_create_all())
    yield


@pytest.fixture(scope="session")
def seeded_users(run, db_setup) -> dict:
    """Crée admin + employé + clé d'API directement en DB. Retourne les ids."""

    async def _seed() -> dict:
        async with TestSessionLocal() as session:
            admin = User(
                email=ADMIN_EMAIL,
                hashed_password=get_password_hash(ADMIN_PASSWORD),
                is_active=True,
                is_admin=True,
                role="admin",
            )
            employee = User(
                email=EMPLOYEE_EMAIL,
                hashed_password=get_password_hash(EMPLOYEE_PASSWORD),
                is_active=True,
                is_admin=False,
                role="employee",
            )
            session.add_all([admin, employee])
            await session.flush()

            api_key = ApiKey(
                user_id=admin.id,
                key_hash=hash_api_key(API_KEY_PLAINTEXT),
                key_prefix=API_KEY_PLAINTEXT[:12],
                label="Smoke tests",
                is_active=True,
            )
            session.add(api_key)
            await session.flush()
            ids = {
                "admin_id": admin.id,
                "employee_id": employee.id,
                "api_key_id": api_key.id,
            }
            await session.commit()
            return ids

    return run(_seed())


# ── Client HTTP synchrone (wrapper du AsyncClient httpx) ────────────


class SyncClient:
    """Adapte httpx.AsyncClient à des tests SYNC via le loop partagé.

    Après chaque requête, cède une itération au loop (`sleep(0)`) pour
    laisser démarrer/mourir les éventuels ``asyncio.create_task`` lancés
    par les endpoints (fire-and-forget best-effort)."""

    def __init__(self, client: httpx.AsyncClient, loop) -> None:
        self._client = client
        self._loop = loop

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        resp = self._loop.run_until_complete(
            self._client.request(method, url, **kwargs)
        )
        self._loop.run_until_complete(asyncio.sleep(0))
        return resp

    def get(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("POST", url, **kw)

    def patch(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("PATCH", url, **kw)

    def delete(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("DELETE", url, **kw)


@pytest.fixture(scope="session")
def client(loop, seeded_users) -> SyncClient:
    transport = httpx.ASGITransport(app=fastapi_app)
    async_client = httpx.AsyncClient(
        transport=transport, base_url="http://smoketest"
    )
    yield SyncClient(async_client, loop)
    loop.run_until_complete(async_client.aclose())


# ── Auth helpers ─────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def admin_id(seeded_users) -> int:
    return seeded_users["admin_id"]


@pytest.fixture(scope="session")
def employee_id(seeded_users) -> int:
    return seeded_users["employee_id"]


@pytest.fixture(scope="session")
def auth_headers(admin_id) -> dict:
    """JWT admin généré via les fonctions de sécurité de l'app."""
    token = create_access_token(subject=str(admin_id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def employee_headers(employee_id) -> dict:
    token = create_access_token(subject=str(employee_id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def api_key_headers() -> dict:
    """Auth par clé d'API krts_… (connecteur / MCP)."""
    return {"Authorization": f"Bearer {API_KEY_PLAINTEXT}"}
