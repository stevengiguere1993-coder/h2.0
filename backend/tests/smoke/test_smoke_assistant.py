"""Smoke — Assistant IA phase 1 (catalogue d'outils + cartes d'action).

Vérifie la fondation SANS LLM :
- le catalogue est FILTRÉ selon les permissions de page de l'utilisateur
  (admin = tout ; employé sans volet immobilier = créer_tache seulement) ;
- un outil de LECTURE s'exécute directement et retourne le résultat ;
- une ÉCRITURE passe par une carte : proposée (rien d'écrit) →
  confirmée (l'effet RÉEL existe en base — le paiement est créé par le
  MÊME chemin que la saisie manuelle) ; l'audit porte la mention « par
  Kratos IA au nom de … » ;
- une carte annulée n'écrit RIEN ;
- la carte d'un utilisateur ne peut pas être confirmée par un autre
  (403) ;
- des paramètres invalides donnent un 422/400 propre (message FR).

NE MODIFIE AUCUN CODE DE PRODUCTION — tests uniquement.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, get_password_hash
from app.models.assistant import AssistantAction
from app.models.audit_log import AuditLog
from app.models.immobilier import (
    Bail,
    BailStatus,
    FraisLocatif,
    Immeuble,
    Locataire,
    LocataireCommunication,
    Logement,
    LogementStatus,
    PaiementLoyer,
)
from app.models.user import User
from app.services.assistant_catalogue import OUTILS, OUTILS_PAR_ID

from .conftest import TestSessionLocal


def _mois_courant() -> str:
    return datetime.now(timezone.utc).date().strftime("%Y-%m")


# ── Seeds ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def dossier_assistant(run, seeded_users) -> dict:
    """Immeuble + logement + locataire + bail ACTIF (500 $/mois, sans
    aucun paiement) — le terrain de jeu des outils de l'assistant."""

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Smoke Assistant",
                address="8900 Assistant",
                city="Montréal",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id,
                numero="218",
                status=LogementStatus.OCCUPE.value,
            )
            loc = Locataire(
                full_name="Daniel Drouin Assistant",
                email="daniel.assistant@example.com",
                phone="514 555-8218",
            )
            s.add_all([lg, loc])
            await s.flush()
            debut = datetime.now(timezone.utc).date().replace(day=1)
            debut = debut.replace(year=debut.year - 1)
            bail = Bail(
                logement_id=lg.id,
                locataire_id=loc.id,
                date_debut=debut,
                date_fin=debut + timedelta(days=730),
                loyer_mensuel=500.0,
                status=BailStatus.ACTIF.value,
            )
            s.add(bail)
            await s.flush()
            out = {
                "immeuble_id": imm.id,
                "logement_id": lg.id,
                "locataire_id": loc.id,
                "bail_id": bail.id,
            }
            await s.commit()
            return out

    return run(_seed())


@pytest.fixture(scope="module")
def autre_admin_headers(run, seeded_users) -> dict:
    """Un SECOND compte admin (toutes permissions) — pour prouver que la
    carte d'un utilisateur ne peut pas être confirmée par un autre, même
    pleinement autorisé (le 403 vient de la propriété, pas du rôle)."""

    async def _seed() -> int:
        async with TestSessionLocal() as s:
            u = User(
                email="smoke-assistant-admin2@example.com",
                hashed_password=get_password_hash("Sm0keAdmin2!42"),
                is_active=True,
                is_admin=True,
                role="admin",
            )
            s.add(u)
            await s.commit()
            return u.id

    uid = run(_seed())
    token = create_access_token(subject=str(uid))
    return {"Authorization": f"Bearer {token}"}


# ── Catalogue filtré par permission ──────────────────────────────────


def test_catalogue_admin_voit_les_12_outils(client, auth_headers):
    resp = client.get("/api/v1/assistant/outils", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    outils = resp.json()
    assert {o["id"] for o in outils} == set(OUTILS_PAR_ID)
    assert len(outils) == len(OUTILS) == 12
    for o in outils:
        # Définition complète prête pour le LLM — jamais le handler.
        assert o["titre"] and o["description"] and o["permission"]
        assert o["parametres"]["type"] == "object"
        assert isinstance(o["lecture"], bool)
        assert "handler" not in o


def test_catalogue_employe_est_filtre(client, employee_headers):
    """L'employé (sans volet immobilier, rôle < gestionnaire) ne voit
    AUCUN outil immobilier — seule la création de tâche (page « Mes
    tâches », transverse, seuil employé) lui reste."""
    resp = client.get("/api/v1/assistant/outils", headers=employee_headers)
    assert resp.status_code == 200, resp.text
    assert {o["id"] for o in resp.json()} == {"creer_tache"}


def test_catalogue_exige_authentification(client):
    resp = client.get("/api/v1/assistant/outils")
    assert resp.status_code == 401


# ── Lecture directe ──────────────────────────────────────────────────


def test_lecture_directe_rechercher_locataire(
    client, auth_headers, dossier_assistant
):
    resp = client.post(
        "/api/v1/assistant/outils/rechercher_locataire/executer",
        headers=auth_headers,
        json={"params": {"recherche": "Drouin Assistant"}},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["nb"] >= 1
    fiche = next(
        r
        for r in data["resultats"]
        if r["locataire_id"] == dossier_assistant["locataire_id"]
    )
    # Le bail ACTIF courant est joint à la fiche (bail_id exploitable
    # ensuite par marquer_loyer_paye / solde_bail).
    assert fiche["bail_actuel"]["bail_id"] == dossier_assistant["bail_id"]
    assert fiche["bail_actuel"]["loyer_mensuel"] == 500.0


def test_lecture_directe_par_telephone(
    client, auth_headers, dossier_assistant
):
    """Le téléphone matche quel que soit le format saisi."""
    resp = client.post(
        "/api/v1/assistant/outils/rechercher_locataire/executer",
        headers=auth_headers,
        json={"params": {"recherche": "(514) 555-8218"}},
    )
    assert resp.status_code == 200, resp.text
    ids = [r["locataire_id"] for r in resp.json()["resultats"]]
    assert dossier_assistant["locataire_id"] in ids


def test_lecture_solde_bail(client, auth_headers, dossier_assistant):
    resp = client.post(
        "/api/v1/assistant/outils/solde_bail/executer",
        headers=auth_headers,
        json={"params": {"locataire_id": dossier_assistant["locataire_id"]}},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["bail_id"] == dossier_assistant["bail_id"]
    assert data["loyer_mensuel"] == 500.0
    # Aucun paiement encore : le solde = mois échus × 500 + 0 − 0.
    assert data["solde_du"] == data["detail"]["loyers_echus"]


def test_lecture_refusee_sans_permission(
    client, employee_headers, dossier_assistant
):
    """Le même filtre que le catalogue s'applique à l'EXÉCUTION."""
    resp = client.post(
        "/api/v1/assistant/outils/rechercher_locataire/executer",
        headers=employee_headers,
        json={"params": {"recherche": "Drouin"}},
    )
    assert resp.status_code == 403, resp.text


def test_ecriture_refusee_en_execution_directe(
    client, auth_headers, dossier_assistant
):
    """Un outil d'écriture ne s'exécute JAMAIS directement (400) — il
    passe par une carte d'action confirmée."""
    resp = client.post(
        "/api/v1/assistant/outils/marquer_loyer_paye/executer",
        headers=auth_headers,
        json={
            "params": {
                "bail_id": dossier_assistant["bail_id"],
                "mois": _mois_courant(),
            }
        },
    )
    assert resp.status_code == 400, resp.text
    assert "ÉCRITURE" in resp.text or "criture" in resp.text


# ── Écriture : proposée → confirmée écrit RÉELLEMENT ────────────────


def test_ecriture_proposee_puis_confirmee(
    client, auth_headers, dossier_assistant, run
):
    bail_id = dossier_assistant["bail_id"]
    mois = _mois_courant()

    # 1) Proposition : la carte est créée, l'aperçu est lisible, et
    #    RIEN n'est écrit.
    resp = client.post(
        "/api/v1/assistant/actions",
        headers=auth_headers,
        json={
            "outil": "marquer_loyer_paye",
            "params": {"bail_id": bail_id, "mois": mois},
        },
    )
    assert resp.status_code == 201, resp.text
    carte = resp.json()
    assert carte["statut"] == "proposee"
    assert "Daniel Drouin Assistant" in carte["apercu"]
    assert "500 $" in carte["apercu"]

    async def _nb_paiements() -> int:
        async with TestSessionLocal() as s:
            rows = (
                await s.execute(
                    select(PaiementLoyer).where(
                        PaiementLoyer.bail_id == bail_id
                    )
                )
            ).scalars().all()
            return len(rows)

    assert run(_nb_paiements()) == 0, "la proposition ne doit rien écrire"

    # 2) Confirmation : l'exécution passe par create_paiement (le même
    #    chemin que la saisie manuelle) — le paiement EXISTE en base.
    resp = client.post(
        f"/api/v1/assistant/actions/{carte['id']}/confirmer",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    confirmee = resp.json()
    assert confirmee["statut"] == "confirmee"
    assert confirmee["erreur"] is None
    assert confirmee["executee_le"] is not None
    assert confirmee["resultat"]["paiement"]["montant"] == 500.0

    async def _verifie() -> tuple[int, float, bool]:
        async with TestSessionLocal() as s:
            rows = (
                await s.execute(
                    select(PaiementLoyer).where(
                        PaiementLoyer.bail_id == bail_id
                    )
                )
            ).scalars().all()
            audits = (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.action == "assistant.action_confirmee",
                        AuditLog.entity_id == carte["id"],
                    )
                )
            ).scalars().all()
            mention = any(
                "par Kratos IA au nom de" in (a.details_json or "")
                for a in audits
            )
            return len(rows), float(rows[0].montant) if rows else 0.0, mention

    nb, montant, mention = run(_verifie())
    assert nb == 1, "la confirmation doit créer LE paiement"
    assert montant == 500.0
    assert mention, "l'audit doit porter « par Kratos IA au nom de … »"

    # 3) Une carte déjà confirmée ne se reconfirme pas.
    resp = client.post(
        f"/api/v1/assistant/actions/{carte['id']}/confirmer",
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text


def test_confirmation_echoue_proprement(
    client, auth_headers, dossier_assistant, run
):
    """Si le service métier refuse à l'exécution, la carte passe
    « echouee » avec l'erreur FR — pas de 500, rien d'écrit à moitié."""
    bail_id = dossier_assistant["bail_id"]

    resp = client.post(
        "/api/v1/assistant/actions",
        headers=auth_headers,
        json={
            "outil": "marquer_loyer_paye",
            # Montant explicite : la proposition passe même si le mois
            # courant vient d'être couvert par le test précédent.
            "params": {
                "bail_id": bail_id,
                "mois": _mois_courant(),
                "montant": 50.0,
            },
        },
    )
    assert resp.status_code == 201, resp.text
    carte = resp.json()

    # Le bail se RÉSILIE entre la proposition et la confirmation, avec
    # une date de fin qui ne couvre plus le mois visé.
    async def _resilier():
        async with TestSessionLocal() as s:
            bail = await s.get(Bail, bail_id)
            ancienne_fin = bail.date_fin
            bail.status = BailStatus.RESILIE.value
            bail.date_fin = bail.date_debut
            await s.commit()
            return ancienne_fin

    ancienne_fin = run(_resilier())
    try:
        resp = client.post(
            f"/api/v1/assistant/actions/{carte['id']}/confirmer",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["statut"] == "echouee"
        assert data["erreur"], "l'erreur FR doit être consignée"
    finally:
        # Remettre le bail actif pour les tests suivants.
        async def _reactiver():
            async with TestSessionLocal() as s:
                bail = await s.get(Bail, bail_id)
                bail.status = BailStatus.ACTIF.value
                bail.date_fin = ancienne_fin
                await s.commit()

        run(_reactiver())


# ── Annulée n'écrit rien ─────────────────────────────────────────────


def test_annulation_n_ecrit_rien(
    client, auth_headers, dossier_assistant, run
):
    bail_id = dossier_assistant["bail_id"]
    resp = client.post(
        "/api/v1/assistant/actions",
        headers=auth_headers,
        json={
            "outil": "ajouter_frais_bail",
            "params": {"bail_id": bail_id, "montant": 20.0},
        },
    )
    assert resp.status_code == 201, resp.text
    carte = resp.json()
    assert "20 $" in carte["apercu"]

    resp = client.post(
        f"/api/v1/assistant/actions/{carte['id']}/annuler",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["statut"] == "annulee"

    async def _nb_frais() -> int:
        async with TestSessionLocal() as s:
            rows = (
                await s.execute(
                    select(FraisLocatif).where(
                        FraisLocatif.bail_id == bail_id
                    )
                )
            ).scalars().all()
            return len(rows)

    assert run(_nb_frais()) == 0, "une carte annulée n'écrit RIEN"

    # Une carte annulée ne peut plus être confirmée.
    resp = client.post(
        f"/api/v1/assistant/actions/{carte['id']}/confirmer",
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text


# ── La carte d'un autre : 403 ────────────────────────────────────────


def test_confirmation_par_un_autre_utilisateur_403(
    client, auth_headers, autre_admin_headers, dossier_assistant, run
):
    resp = client.post(
        "/api/v1/assistant/actions",
        headers=auth_headers,
        json={
            "outil": "ajouter_note_locataire",
            "params": {
                "locataire_id": dossier_assistant["locataire_id"],
                "contenu": "Note proposée par l'assistant (test).",
            },
        },
    )
    assert resp.status_code == 201, resp.text
    carte = resp.json()

    # L'AUTRE admin (pleinement autorisé côté permissions) ne peut ni
    # confirmer ni annuler la carte : elle ne lui appartient pas.
    resp = client.post(
        f"/api/v1/assistant/actions/{carte['id']}/confirmer",
        headers=autre_admin_headers,
    )
    assert resp.status_code == 403, resp.text
    resp = client.post(
        f"/api/v1/assistant/actions/{carte['id']}/annuler",
        headers=autre_admin_headers,
    )
    assert resp.status_code == 403, resp.text

    async def _nb_notes() -> int:
        async with TestSessionLocal() as s:
            rows = (
                await s.execute(
                    select(LocataireCommunication).where(
                        LocataireCommunication.locataire_id
                        == dossier_assistant["locataire_id"]
                    )
                )
            ).scalars().all()
            return len(rows)

    assert run(_nb_notes()) == 0

    # Il ne la voit pas non plus dans SON historique.
    resp = client.get(
        "/api/v1/assistant/actions", headers=autre_admin_headers
    )
    assert resp.status_code == 200
    assert carte["id"] not in [a["id"] for a in resp.json()]

    # L'auteur, lui, la voit toujours proposée — et peut la confirmer.
    resp = client.get(
        "/api/v1/assistant/actions?statut=proposee", headers=auth_headers
    )
    assert resp.status_code == 200
    assert carte["id"] in [a["id"] for a in resp.json()]

    resp = client.post(
        f"/api/v1/assistant/actions/{carte['id']}/confirmer",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["statut"] == "confirmee"
    assert run(_nb_notes()) == 1


# ── Params invalides → 422/400 propre ────────────────────────────────


def test_outil_inconnu_404(client, auth_headers):
    resp = client.post(
        "/api/v1/assistant/outils/outil_fantome/executer",
        headers=auth_headers,
        json={"params": {}},
    )
    assert resp.status_code == 404, resp.text
    resp = client.post(
        "/api/v1/assistant/actions",
        headers=auth_headers,
        json={"outil": "outil_fantome", "params": {}},
    )
    assert resp.status_code == 404, resp.text


def test_params_requis_manquants_422(client, auth_headers, dossier_assistant):
    resp = client.post(
        "/api/v1/assistant/actions",
        headers=auth_headers,
        json={
            "outil": "marquer_loyer_paye",
            "params": {"bail_id": dossier_assistant["bail_id"]},
        },
    )
    assert resp.status_code == 422, resp.text
    assert "mois" in resp.text


def test_param_inconnu_422(client, auth_headers, dossier_assistant):
    resp = client.post(
        "/api/v1/assistant/actions",
        headers=auth_headers,
        json={
            "outil": "marquer_loyer_paye",
            "params": {
                "bail_id": dossier_assistant["bail_id"],
                "mois": _mois_courant(),
                "pourboire": 5,
            },
        },
    )
    assert resp.status_code == 422, resp.text
    assert "pourboire" in resp.text


def test_mois_malforme_422(client, auth_headers, dossier_assistant):
    resp = client.post(
        "/api/v1/assistant/actions",
        headers=auth_headers,
        json={
            "outil": "marquer_loyer_paye",
            "params": {
                "bail_id": dossier_assistant["bail_id"],
                "mois": "2026-13",
            },
        },
    )
    assert resp.status_code == 422, resp.text
    assert "YYYY-MM" in resp.text


def test_montant_negatif_422(client, auth_headers, dossier_assistant):
    resp = client.post(
        "/api/v1/assistant/actions",
        headers=auth_headers,
        json={
            "outil": "ajouter_frais_bail",
            "params": {
                "bail_id": dossier_assistant["bail_id"],
                "montant": -20,
            },
        },
    )
    assert resp.status_code == 422, resp.text


def test_bail_introuvable_404(client, auth_headers):
    resp = client.post(
        "/api/v1/assistant/actions",
        headers=auth_headers,
        json={
            "outil": "marquer_loyer_paye",
            "params": {"bail_id": 987654321, "mois": _mois_courant()},
        },
    )
    assert resp.status_code == 404, resp.text


def test_lecture_via_carte_400(client, auth_headers):
    """Un outil de LECTURE ne crée pas de carte : il s'exécute direct."""
    resp = client.post(
        "/api/v1/assistant/actions",
        headers=auth_headers,
        json={"outil": "rechercher_locataire", "params": {"recherche": "x"}},
    )
    assert resp.status_code == 400, resp.text


def test_historique_filtre_par_statut_invalide_400(client, auth_headers):
    resp = client.get(
        "/api/v1/assistant/actions?statut=zombie", headers=auth_headers
    )
    assert resp.status_code == 400, resp.text
