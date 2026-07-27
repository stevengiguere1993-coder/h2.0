"""Smoke — page Communications locative (2026-07-27).

Vérifie avec un FAUX mailer (aucun vrai courriel) :
1. envoi « avis d'accès » à un immeuble → UN courriel PAR locataire à
   bail actif, variables remplies, audit + entrée fiche locataire ;
2. le locataire SANS courriel est rapporté (pas d'échec silencieux) ;
3. rappel de paiement : celui qui a payé le mois est SAUTÉ, l'autre
   reçoit SON montant ;
4. l'expéditeur des réglages est appliqué (from/nom/répondre-à) ;
5. l'audit filtre par type.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.immobilier import (
    Bail,
    BailStatus,
    ImmCommunication,
    Immeuble,
    Locataire,
    LocataireCommunication,
    Logement,
    LogementStatus,
    PaiementLoyer,
)

from .conftest import TestSessionLocal


class FakeMailer:
    ready = True

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, to, subject, html_body, **kw):
        self.sent.append(
            {
                "to": list(to),
                "subject": subject,
                "html": html_body,
                "reply_to": kw.get("reply_to"),
                "from_email": kw.get("from_email"),
                "from_name": kw.get("from_name"),
            }
        )


@pytest.fixture()
def fake_mailer(monkeypatch) -> FakeMailer:
    from app.api.v1.endpoints import immobilier_communications as mod

    fake = FakeMailer()
    monkeypatch.setattr(mod, "get_mailer", lambda: fake)
    return fake


@pytest.fixture(scope="module")
def comm_seed(run, seeded_users) -> dict:
    """1 immeuble, 3 baux actifs : Alice (email, loyer payé ce mois-ci),
    Bob (email, rien payé), Carl (PAS d'email)."""

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Smoke Comm", address="9 rue Courriel",
                city="Montréal", is_active=True,
            )
            s.add(imm)
            await s.flush()
            ids: dict = {"immeuble_id": imm.id}
            mois = datetime.now(timezone.utc).date().replace(day=1)
            for i, (nom, email, paye) in enumerate(
                [
                    ("Alice Comm", "alice@test.local", True),
                    ("Bob Comm", "bob@test.local", False),
                    ("Carl Comm", None, False),
                ],
                start=1,
            ):
                lg = Logement(
                    immeuble_id=imm.id, numero=str(100 + i),
                    status=LogementStatus.OCCUPE.value,
                )
                loc = Locataire(full_name=nom, email=email)
                s.add_all([lg, loc])
                await s.flush()
                bail = Bail(
                    logement_id=lg.id, locataire_id=loc.id,
                    date_debut=mois - timedelta(days=90),
                    date_fin=mois + timedelta(days=275),
                    loyer_mensuel=800.0 + i,
                    status=BailStatus.ACTIF.value,
                )
                s.add(bail)
                await s.flush()
                if paye:
                    s.add(
                        PaiementLoyer(
                            bail_id=bail.id, mois_couvert=mois,
                            montant=float(bail.loyer_mensuel),
                            paye_le=mois,
                            created_at=datetime.now(timezone.utc),
                        )
                    )
                ids[f"locataire_{nom.split()[0].lower()}"] = loc.id
            await s.commit()
            return ids

    return run(_seed())


def test_avis_acces_un_courriel_par_locataire(
    client, auth_headers, comm_seed, fake_mailer, run
):
    resp = client.post(
        "/api/v1/immobilier/communications/envoyer",
        headers=auth_headers,
        json={
            "type": "avis_acces",
            "immeuble_ids": [comm_seed["immeuble_id"]],
            "locataire_ids": [],
            "acces_date": date.today().isoformat(),
            "acces_plage": "entre 9 h et 12 h",
            "acces_motif": "inspection des détecteurs de fumée",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["envoyes"] == 2  # Alice + Bob
    assert data["sans_email"] == ["Carl Comm"]
    assert data["echecs"] == []

    # Un courriel PAR destinataire, jamais groupé.
    assert len(fake_mailer.sent) == 2
    assert all(len(m["to"]) == 1 for m in fake_mailer.sent)
    tos = {m["to"][0] for m in fake_mailer.sent}
    assert tos == {"alice@test.local", "bob@test.local"}
    # Variables du gabarit remplies (adresse dans le corps).
    assert any("9 rue Courriel" in m["html"] for m in fake_mailer.sent)

    async def _verif():
        from sqlalchemy import select

        async with TestSessionLocal() as s:
            audits = (
                await s.execute(
                    select(ImmCommunication).where(
                        ImmCommunication.immeuble_id
                        == comm_seed["immeuble_id"],
                        ImmCommunication.type == "avis_acces",
                    )
                )
            ).scalars().all()
            fiches = (
                await s.execute(
                    select(LocataireCommunication).where(
                        LocataireCommunication.locataire_id
                        == comm_seed["locataire_alice"],
                        LocataireCommunication.kind == "courriel",
                    )
                )
            ).scalars().all()
            return audits, fiches

    audits, fiches = run(_verif())
    assert len(audits) == 2  # une trace par courriel
    assert len({a.group_id for a in audits}) == 1  # même envoi
    assert len(fiches) >= 1  # visible sur la fiche du locataire


def test_rappel_paiement_saute_les_payes(
    client, auth_headers, comm_seed, fake_mailer
):
    resp = client.post(
        "/api/v1/immobilier/communications/envoyer",
        headers=auth_headers,
        json={
            "type": "rappel_paiement",
            "immeuble_ids": [comm_seed["immeuble_id"]],
            "locataire_ids": [],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ignores_payes"] == ["Alice Comm"]  # a payé → sautée
    assert data["envoyes"] == 1  # Bob seulement
    assert data["sans_email"] == ["Carl Comm"]
    # Le montant de Bob (802 $) est dans SON courriel.
    assert len(fake_mailer.sent) == 1
    assert "802" in fake_mailer.sent[0]["html"]


def test_expediteur_des_reglages_applique(
    client, auth_headers, comm_seed, fake_mailer
):
    resp = client.put(
        "/api/v1/immobilier/communications/reglages",
        headers=auth_headers,
        json={
            "from_email": "gestion@immohorizon.com",
            "from_name": "Kyle — Gestion Horizon",
            "reply_to": "kyle.gestion@gmail.com",
        },
    )
    assert resp.status_code == 200, resp.text

    resp2 = client.post(
        "/api/v1/immobilier/communications/envoyer",
        headers=auth_headers,
        json={
            "type": "demande_assurance",
            "immeuble_ids": [],
            "locataire_ids": [comm_seed["locataire_bob"]],
        },
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["envoyes"] == 1
    m = fake_mailer.sent[-1]
    assert m["from_email"] == "gestion@immohorizon.com"
    assert m["from_name"] == "Kyle — Gestion Horizon"
    assert m["reply_to"] == "kyle.gestion@gmail.com"

    # Remise à zéro des réglages pour ne pas polluer les autres tests.
    client.put(
        "/api/v1/immobilier/communications/reglages",
        headers=auth_headers,
        json={"from_email": "", "from_name": "", "reply_to": ""},
    )


def test_audit_filtrable_par_type(client, auth_headers, comm_seed):
    resp = client.get(
        "/api/v1/immobilier/communications?type=rappel_paiement",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows and all(r["type"] == "rappel_paiement" for r in rows)
    assert any(r["locataire_nom"] == "Bob Comm" for r in rows)


def test_envoyer_sans_cible_422(client, auth_headers, fake_mailer):
    resp = client.post(
        "/api/v1/immobilier/communications/envoyer",
        headers=auth_headers,
        json={"type": "demande_assurance", "immeuble_ids": [], "locataire_ids": []},
    )
    assert resp.status_code == 422
    assert fake_mailer.sent == []
