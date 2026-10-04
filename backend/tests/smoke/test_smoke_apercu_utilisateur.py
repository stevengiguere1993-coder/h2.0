"""Smoke — aperçu « voir comme cet utilisateur » (lecture seule stricte).

Un admin/owner obtient, via ``POST /users/{id}/apercu``, un jeton émis AU
NOM d'un autre utilisateur (revendication ``apercu_par`` = id de l'admin)
pour voir Kratos exactement comme lui — sans mot de passe, sans se
déconnecter. Ces tests verrouillent le contrat ET les garde-fous :

- émission : 200 pour admin → employé ; 403 pour un employé (pas admin) ;
  403 vers un rang supérieur (admin → owner) ; 400 vers soi-même ; 400
  vers un compte désactivé ;
- lecture : /auth/me renvoie la fiche de l'utilisateur REGARDÉ avec
  ``apercu_par`` = l'admin et ``must_change_password`` forcé à False ;
  les GET (ex. /users) passent ;
- lecture SEULE : toute écriture (PATCH / POST / PUT / DELETE) avec le
  jeton → 403 et RIEN n'est modifié en DB ; impossible de chaîner un
  aperçu depuis un aperçu ;
- jeton normal : ``apercu_par`` est None ;
- journalisation ``user.apercu`` (qui a regardé qui) ;
- jeton forgé dont ``apercu_par`` n'est pas un entier → 401 ; utilisateur
  regardé désactivé APRÈS l'émission → 401 (l'inactivité est revérifiée
  à chaque requête, comme pour un jeton normal).

Réutilise les fixtures de ``conftest.py`` (client, auth_headers,
employee_headers, admin_id, employee_id, run). Un owner et un employé
inactif supplémentaires sont semés directement en DB, avec des courriels
distincts de ceux des autres modules (contrainte d'unicité, DB partagée
sur toute la session).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, get_password_hash
from app.models.audit_log import AuditLog
from app.models.user import User

from .conftest import EMPLOYEE_EMAIL, TestSessionLocal

OWNER_APERCU_EMAIL = "smoke-owner-apercu@example.com"
INACTIF_APERCU_EMAIL = "smoke-inactif-apercu@example.com"
DESACTIVE_APRES_EMAIL = "smoke-desactive-apres-apercu@example.com"
MDP_SEED = "Sm0keApercu!42"


# ── Helpers / fixtures ───────────────────────────────────────────────


def _seed_user(run, **champs) -> int:
    """Sème un utilisateur directement en DB et retourne son id."""

    async def _seed() -> int:
        async with TestSessionLocal() as session:
            u = User(hashed_password=get_password_hash(MDP_SEED), **champs)
            session.add(u)
            await session.flush()
            uid = u.id
            await session.commit()
            return uid

    return run(_seed())


def _lire_user(run, user_id: int) -> User:
    """Relit un utilisateur depuis une session neuve (état réel en DB)."""

    async def _get() -> User:
        async with TestSessionLocal() as session:
            return await session.get(User, user_id)

    return run(_get())


@pytest.fixture(scope="module")
def owner_apercu_id(run, seeded_users) -> int:
    """Owner semé en DB (rang 4 > admin) pour la garde de rang."""
    return _seed_user(
        run,
        email=OWNER_APERCU_EMAIL,
        is_active=True,
        is_admin=True,
        role="owner",
    )


@pytest.fixture(scope="module")
def inactif_apercu_id(run, seeded_users) -> int:
    """Employé DÉSACTIVÉ semé en DB : jamais utilisable en aperçu."""
    return _seed_user(
        run,
        email=INACTIF_APERCU_EMAIL,
        is_active=False,
        is_admin=False,
        role="employee",
    )


@pytest.fixture(scope="module")
def apercu_headers(client, auth_headers, employee_id) -> dict:
    """Jeton d'aperçu admin → employé, prêt à l'emploi en en-tête Bearer."""
    resp = client.post(
        f"/api/v1/users/{employee_id}/apercu", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── Cas 1 à 9 (spéc) ────────────────────────────────────────────────


def test_admin_obtient_un_jeton_d_apercu_pour_un_employe(
    client, auth_headers, employee_id
):
    """Cas 1 : admin → POST /users/{employé}/apercu → 200 avec un jeton
    bearer non vide, une durée > 0 et la fiche de l'utilisateur regardé."""
    resp = client.post(
        f"/api/v1/users/{employee_id}/apercu", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["email"] == EMPLOYEE_EMAIL
    assert body["user"]["id"] == employee_id
    assert body["user"]["role"] == "employee"


def test_me_avec_jeton_d_apercu_renvoie_l_utilisateur_regarde(
    client, apercu_headers, admin_id
):
    """Cas 2 : GET /auth/me avec le jeton d'aperçu = la fiche de l'employé,
    ``apercu_par`` = l'admin qui regarde, ``must_change_password`` forcé à
    False (jamais l'écran de changement de mot de passe en aperçu)."""
    resp = client.get("/api/v1/auth/me", headers=apercu_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == EMPLOYEE_EMAIL
    assert body["apercu_par"] == admin_id
    assert body["must_change_password"] is False
    assert body["role"] == "employee"


def test_lecture_permise_avec_jeton_d_apercu(client, apercu_headers):
    """Cas 3 : un GET (liste des utilisateurs) passe avec le jeton d'aperçu."""
    resp = client.get("/api/v1/users", headers=apercu_headers)
    assert resp.status_code == 200, resp.text
    assert any(u["email"] == EMPLOYEE_EMAIL for u in resp.json())


def test_ecriture_refusee_avec_jeton_d_apercu(
    client, apercu_headers, employee_headers
):
    """Cas 4 : PATCH /auth/me/theme avec le jeton d'aperçu → 403, et le
    thème de l'employé n'a PAS bougé (toujours « light » en DB)."""
    resp = client.patch(
        "/api/v1/auth/me/theme",
        headers=apercu_headers,
        json={"theme": "dark"},
    )
    assert resp.status_code == 403, resp.text
    assert "aperçu" in resp.json()["detail"].lower()
    me = client.get("/api/v1/auth/me", headers=employee_headers)
    assert me.status_code == 200, me.text
    assert me.json()["theme_preference"] == "light"


def test_employe_ne_peut_pas_emettre_d_apercu(
    client, employee_headers, employee_id
):
    """Cas 5 : un employé (pas admin) → 403 (RequireAdminRole), avant même
    la vérification « soi-même »."""
    resp = client.post(
        f"/api/v1/users/{employee_id}/apercu", headers=employee_headers
    )
    assert resp.status_code == 403, resp.text


def test_admin_ne_peut_pas_voir_comme_un_owner(
    client, auth_headers, owner_apercu_id
):
    """Cas 6 : rang strictement supérieur interdit — admin → owner → 403
    (_guard_rank). Sinon un admin verrait tout ce qu'un owner voit."""
    resp = client.post(
        f"/api/v1/users/{owner_apercu_id}/apercu", headers=auth_headers
    )
    assert resp.status_code == 403, resp.text


def test_admin_ne_peut_pas_se_voir_lui_meme(client, auth_headers, admin_id):
    """Cas 7 : POST /users/{soi-même}/apercu → 400."""
    resp = client.post(
        f"/api/v1/users/{admin_id}/apercu", headers=auth_headers
    )
    assert resp.status_code == 400, resp.text
    assert "propre compte" in resp.json()["detail"]


def test_compte_desactive_refuse_en_apercu(
    client, auth_headers, inactif_apercu_id
):
    """Cas 8 : un compte désactivé ne s'utilise pas en aperçu → 400."""
    resp = client.post(
        f"/api/v1/users/{inactif_apercu_id}/apercu", headers=auth_headers
    )
    assert resp.status_code == 400, resp.text
    assert "désactivé" in resp.json()["detail"]


def test_jeton_normal_sans_apercu_par(client, employee_headers):
    """Cas 9 : GET /auth/me avec un jeton normal → ``apercu_par`` is None."""
    resp = client.get("/api/v1/auth/me", headers=employee_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["apercu_par"] is None


# ── Durcissement (au-delà de la spéc) ───────────────────────────────


def test_impossible_de_chainer_un_apercu_depuis_un_apercu(
    client, apercu_headers, admin_id
):
    """Un jeton d'aperçu ne peut PAS en émettre un autre (POST bloqué en
    lecture seule) : pas de rebond d'aperçu en aperçu, pas d'escalade."""
    resp = client.post(
        f"/api/v1/users/{admin_id}/apercu", headers=apercu_headers
    )
    assert resp.status_code == 403, resp.text
    assert "aperçu" in resp.json()["detail"].lower()


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("PATCH", "/api/v1/auth/me/profile", {"first_name": "Pirate"}),
        (
            "POST",
            "/api/v1/auth/change-password",
            {"current_password": MDP_SEED, "new_password": "N0uveauMdp!99"},
        ),
        ("DELETE", "/api/v1/auth/me/avatar", None),
        ("PUT", "/api/v1/users/{employee_id}/projects", {"project_ids": []}),
    ],
    ids=["patch-profil", "post-mot-de-passe", "delete-avatar", "put-projets"],
)
def test_toute_methode_d_ecriture_refusee_en_apercu(
    client, apercu_headers, employee_id, method, path, body
):
    """Lecture seule STRICTE : PATCH, POST, PUT et DELETE sont refusés en
    403 par le garde d'aperçu lui-même (le détail le nomme — ce n'est pas
    un 403 de rôle), quels que soient les droits de l'utilisateur regardé."""
    resp = client.request(
        method,
        path.format(employee_id=employee_id),
        headers=apercu_headers,
        json=body,
    )
    assert resp.status_code == 403, resp.text
    assert "aperçu" in resp.json()["detail"].lower()


def test_rien_n_est_ecrit_en_db_en_apercu(
    client, apercu_headers, run, employee_id
):
    """Un essai de changement de mot de passe et de prénom avec le jeton
    d'aperçu laisse la ligne de l'employé INTACTE (hash + prénom)."""
    avant = _lire_user(run, employee_id)
    client.post(
        "/api/v1/auth/change-password",
        headers=apercu_headers,
        json={"current_password": MDP_SEED, "new_password": "N0uveauMdp!99"},
    )
    client.patch(
        "/api/v1/auth/me/profile",
        headers=apercu_headers,
        json={"first_name": "Pirate"},
    )
    apres = _lire_user(run, employee_id)
    assert apres.hashed_password == avant.hashed_password
    assert apres.first_name == avant.first_name
    assert apres.first_name != "Pirate"


def test_apercu_journalise_qui_regarde_qui(
    run, admin_id, employee_id, apercu_headers
):
    """Chaque émission écrit une ligne AuditLog ``user.apercu`` au nom de
    l'ADMIN (jamais de l'utilisateur regardé), ciblant l'employé, avec sa
    fiche (courriel, rôle, volets) dans les détails."""

    async def _rows() -> list[AuditLog]:
        async with TestSessionLocal() as session:
            return list(
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.action == "user.apercu",
                            AuditLog.entity_id == employee_id,
                        )
                    )
                ).scalars().all()
            )

    rows = run(_rows())
    assert rows, "aucune ligne d'audit user.apercu"
    for row in rows:
        assert row.user_id == admin_id
        assert row.entity_type == "user"
        details = json.loads(row.details_json or "{}")
        assert details["target_email"] == EMPLOYEE_EMAIL
        assert details["role"] == "employee"
        assert isinstance(details["volets"], list)


def test_jeton_forge_avec_apercu_par_non_entier_401(client, employee_id):
    """Un jeton signé mais dont ``apercu_par`` n'est pas convertible en
    entier est rejeté (401) — même en lecture : un ``apercu_par`` présent
    ne retombe jamais silencieusement dans le mode normal."""
    token = create_access_token(
        subject=str(employee_id), additional_claims={"apercu_par": "pas-un-id"}
    )
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401, resp.text


def test_apercu_invalide_si_l_utilisateur_regarde_est_desactive(
    client, auth_headers, run
):
    """L'inactivité est revérifiée à CHAQUE requête : un jeton d'aperçu
    émis, puis l'utilisateur regardé désactivé → 401, même en lecture."""
    uid = _seed_user(
        run,
        email=DESACTIVE_APRES_EMAIL,
        is_active=True,
        is_admin=False,
        role="employee",
    )
    emis = client.post(f"/api/v1/users/{uid}/apercu", headers=auth_headers)
    assert emis.status_code == 200, emis.text
    headers = {"Authorization": f"Bearer {emis.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    async def _desactiver() -> None:
        async with TestSessionLocal() as session:
            u = await session.get(User, uid)
            u.is_active = False
            await session.commit()

    run(_desactiver())
    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401, resp.text
