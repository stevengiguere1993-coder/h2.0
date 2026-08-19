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
            "from_email": "info@immohorizon.com",
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
            "from_email": "info@immohorizon.com",
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


def test_de_qui_obligatoire_422(client, auth_headers, comm_seed, fake_mailer):
    """Sans expéditeur (ni payload ni réglages) → refus explicite, rien
    ne part (retour Phil : « le email est parti quand même »)."""
    resp = client.post(
        "/api/v1/immobilier/communications/envoyer",
        headers=auth_headers,
        json={
            "type": "demande_assurance",
            "immeuble_ids": [comm_seed["immeuble_id"]],
            "locataire_ids": [],
        },
    )
    assert resp.status_code == 422, resp.text
    assert "De qui" in resp.json()["detail"]
    assert fake_mailer.sent == []


def test_employe_ne_peut_pas_changer_l_expediteur(
    client, auth_headers, employee_headers, comm_seed, fake_mailer, run
):
    """Un non-manager envoie avec les DÉFAUTS des réglages — son payload
    from/reply-to est ignoré (pas d'usurpation d'expéditeur)."""
    import json as _json

    from app.models.user import User

    from .conftest import TestSessionLocal

    # L'employé de test doit avoir le volet immobilier.
    async def _volets():
        async with TestSessionLocal() as s:
            from sqlalchemy import select

            emp = (
                await s.execute(
                    select(User).where(User.role == "employee")
                )
            ).scalars().first()
            emp.volets_json = _json.dumps(["immobilier"])
            await s.commit()
            return emp.id

    run(_volets())
    client.put(
        "/api/v1/immobilier/communications/reglages",
        headers=auth_headers,
        json={
            "from_email": "gestion@immohorizon.com",
            "from_name": "Gestion Horizon",
            "reply_to": "kyle.gestion@gmail.com",
        },
    )
    resp = client.post(
        "/api/v1/immobilier/communications/envoyer",
        headers=employee_headers,
        json={
            "type": "demande_assurance",
            "immeuble_ids": [],
            "locataire_ids": [comm_seed["locataire_bob"]],
            "from_email": "pirate@evil.com",
            "from_name": "Faux Nom",
            "reply_to": "pirate@evil.com",
        },
    )
    assert resp.status_code == 200, resp.text
    m = fake_mailer.sent[-1]
    assert m["from_email"] == "gestion@immohorizon.com"  # payload ignoré
    assert m["reply_to"] == "kyle.gestion@gmail.com"
    client.put(
        "/api/v1/immobilier/communications/reglages",
        headers=auth_headers,
        json={"from_email": "", "from_name": "", "reply_to": ""},
    )


def test_destinataires_exposent_le_du_du_mois(
    client, auth_headers, comm_seed
):
    """Le bouton « Retards du mois » se nourrit de du_mois : Alice (payée)
    à 0, Bob avec son loyer dû."""
    resp = client.get(
        "/api/v1/immobilier/communications/destinataires",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    bloc = next(
        b for b in resp.json()
        if b["immeuble_id"] == comm_seed["immeuble_id"]
    )
    par_nom = {l["nom"]: l for l in bloc["locataires"]}
    assert par_nom["Alice Comm"]["du_mois"] == 0.0
    assert par_nom["Bob Comm"]["du_mois"] == 802.0


def test_envoi_via_profil_expediteur(
    client, auth_headers, comm_seed, fake_mailer
):
    """Profils d'expéditeurs approuvés (cas « deux gestionnaires ») :
    l'envoi avec profil=label applique l'expéditeur du profil ; un label
    inconnu est refusé."""
    resp = client.put(
        "/api/v1/immobilier/communications/reglages",
        headers=auth_headers,
        json={
            "from_email": "",
            "from_name": "",
            "reply_to": "",
            "profils": [
                {
                    "label": "Kyle",
                    "from_email": "gestion@immohorizon.com",
                    "from_name": "Kyle — Gestion Horizon",
                    "reply_to": "kyle.gestion@gmail.com",
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    assert [p["label"] for p in resp.json()["profils"]] == ["Kyle"]

    resp2 = client.post(
        "/api/v1/immobilier/communications/envoyer",
        headers=auth_headers,
        json={
            "type": "demande_assurance",
            "immeuble_ids": [],
            "locataire_ids": [comm_seed["locataire_bob"]],
            "profil": "Kyle",
        },
    )
    assert resp2.status_code == 200, resp2.text
    m = fake_mailer.sent[-1]
    assert m["from_email"] == "gestion@immohorizon.com"
    assert m["from_name"] == "Kyle — Gestion Horizon"
    assert m["reply_to"] == "kyle.gestion@gmail.com"

    resp3 = client.post(
        "/api/v1/immobilier/communications/envoyer",
        headers=auth_headers,
        json={
            "type": "demande_assurance",
            "immeuble_ids": [],
            "locataire_ids": [comm_seed["locataire_bob"]],
            "profil": "Inconnu",
        },
    )
    assert resp3.status_code == 422

    # Nettoyage pour les autres tests.
    client.put(
        "/api/v1/immobilier/communications/reglages",
        headers=auth_headers,
        json={"from_email": "", "from_name": "", "reply_to": "", "profils": []},
    )


def test_profil_par_defaut_applique_sans_choix(
    client, auth_headers, comm_seed, fake_mailer
):
    """Retour Phil v4 : le manager choisit un profil PAR DÉFAUT ; un envoi
    SANS `profil` explicite l'utilise. Le défaut doit exister parmi les
    profils (sinon ignoré à l'enregistrement)."""
    resp = client.put(
        "/api/v1/immobilier/communications/reglages",
        headers=auth_headers,
        json={
            "from_email": "",
            "from_name": "",
            "reply_to": "",
            "profils": [
                {
                    "label": "Bureau",
                    "from_email": "info@immohorizon.com",
                    "from_name": "Gestion Horizon",
                    "reply_to": "",
                },
                {
                    "label": "Kyle",
                    "from_email": "gestion@immohorizon.com",
                    "from_name": "Kyle — Gestion Horizon",
                    "reply_to": "kyle.gestion@gmail.com",
                },
            ],
            "profil_defaut": "Kyle",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["profil_defaut"] == "Kyle"

    # Envoi SANS profil → le défaut « Kyle » s'applique.
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
    m = fake_mailer.sent[-1]
    assert m["from_email"] == "gestion@immohorizon.com"
    assert m["reply_to"] == "kyle.gestion@gmail.com"

    # Un défaut hors liste est nettoyé (ignoré) à l'enregistrement.
    resp3 = client.put(
        "/api/v1/immobilier/communications/reglages",
        headers=auth_headers,
        json={
            "from_email": "",
            "from_name": "",
            "reply_to": "",
            "profils": [
                {
                    "label": "Kyle",
                    "from_email": "gestion@immohorizon.com",
                    "from_name": "",
                    "reply_to": "",
                }
            ],
            "profil_defaut": "Fantome",
        },
    )
    assert resp3.status_code == 200, resp3.text
    assert resp3.json()["profil_defaut"] == ""

    # Nettoyage.
    client.put(
        "/api/v1/immobilier/communications/reglages",
        headers=auth_headers,
        json={"from_email": "", "from_name": "", "reply_to": "", "profils": []},
    )


def test_redirect_all_to_staging(client, auth_headers, comm_seed, monkeypatch):
    """MAIL_REDIRECT_ALL_TO (staging) : le courriel part uniquement vers
    l'adresse de test, sujet préfixé avec le destinataire réel, cc/bcc
    vidés — vérifié sur le VRAI GraphMailer.send (pas le FakeMailer),
    en capturant l'appel HTTP Graph."""
    import app.integrations.email_graph as eg
    from app.api.v1.endpoints import immobilier_communications as mod

    envois = []

    class _FakeHTTP:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            class _R:
                status_code = 202
                text = ""

                def raise_for_status(self):
                    return None

                def json(self):
                    return {"access_token": "t", "expires_in": 3600}

            if "oauth2" in url:
                return _R()
            envois.append(kw.get("json"))
            return _R()

    mailer = eg.GraphMailer()
    mailer.tenant = "t"
    mailer.client_id = "c"
    mailer.client_secret = "s"
    mailer.sender = "info@immohorizon.com"
    monkeypatch.setattr(eg, "httpx", type("H", (), {"AsyncClient": _FakeHTTP}))
    monkeypatch.setattr(
        eg.settings, "mail_redirect_all_to", "phil.test@example.com"
    )
    monkeypatch.setattr(mod, "get_mailer", lambda: mailer)

    # Réglages minimaux pour passer la validation « De qui ».
    client.put(
        "/api/v1/immobilier/communications/reglages",
        headers=auth_headers,
        json={
            "from_email": "info@immohorizon.com",
            "from_name": "",
            "reply_to": "",
            "profils": [],
        },
    )
    r = client.post(
        "/api/v1/immobilier/communications/envoyer",
        headers=auth_headers,
        json={
            "type": "demande_assurance",
            "immeuble_ids": [],
            "locataire_ids": [comm_seed["locataire_bob"]],
        },
    )
    assert r.status_code == 200, r.text
    assert len(envois) == 1
    m = envois[0]["message"]
    dests = [x["emailAddress"]["address"] for x in m["toRecipients"]]
    assert dests == ["phil.test@example.com"]          # redirigé
    assert "bob@test.local" in m["subject"]            # destinataire réel visible
    assert m["subject"].startswith("[TEST")
    assert "ccRecipients" not in m
    assert "bccRecipients" not in m                    # pas de BCC superviseur

    # Nettoyage réglages.
    client.put(
        "/api/v1/immobilier/communications/reglages",
        headers=auth_headers,
        json={"from_email": "", "from_name": "", "reply_to": "", "profils": []},
    )


def test_gestion_externe_exclue_par_defaut(
    client, auth_headers, comm_seed, fake_mailer, run
):
    """« Comment ça l'immeuble 1-3-5 Elgin y apparaît ? Il est gestion
    externe pourtant » (retour Phil 2026-08-13), puis décision du
    2026-08-19 : la case « Inclure les immeubles en gestion externe »
    est RETIRÉE. Ces immeubles sortent TOUJOURS du sélecteur « À qui »
    et l'envoi les refuse même si la requête tente de les viser — le
    filtre est appliqué côté serveur, pas seulement à l'écran."""

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="1-3-5 Elgin (smoke externe)",
                address="1-3-5 rue Elgin",
                city="Montréal",
                is_active=True,
                gestion_externe=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="3",
                status=LogementStatus.OCCUPE.value,
            )
            loc = Locataire(
                full_name="Externe Comm", email="externe@test.local"
            )
            s.add_all([lg, loc])
            await s.flush()
            mois = datetime.now(timezone.utc).date().replace(day=1)
            s.add(
                Bail(
                    logement_id=lg.id, locataire_id=loc.id,
                    date_debut=mois - timedelta(days=90),
                    date_fin=mois + timedelta(days=275),
                    loyer_mensuel=950.0,
                    status=BailStatus.ACTIF.value,
                )
            )
            await s.commit()
            return {"immeuble_id": imm.id, "locataire_id": loc.id}

    ext = run(_seed())

    # (a) Par défaut : absent du sélecteur.
    blocs = client.get(
        "/api/v1/immobilier/communications/destinataires", headers=auth_headers
    ).json()
    assert all(b["immeuble_id"] != ext["immeuble_id"] for b in blocs)

    # (b) L'ancienne échappatoire ne rouvre plus rien : le paramètre
    # n'existe plus, le serveur filtre quoi qu'il arrive.
    blocs2 = client.get(
        "/api/v1/immobilier/communications/destinataires"
        "?inclure_gestion_externe=true",
        headers=auth_headers,
    ).json()
    assert all(b["immeuble_id"] != ext["immeuble_id"] for b in blocs2)

    # (c) Envoi visant l'immeuble externe : rien ne part.
    r = client.post(
        "/api/v1/immobilier/communications/envoyer",
        headers=auth_headers,
        json={
            "type": "demande_assurance",
            "immeuble_ids": [ext["immeuble_id"]],
            "locataire_ids": [],
            "from_email": "info@immohorizon.com",
        },
    )
    assert r.status_code == 422, r.text
    assert fake_mailer.sent == []

    # (d) Même en rejouant l'ancien drapeau dans le corps de la requête,
    # l'envoi reste refusé : la porte est condamnée côté serveur.
    r2 = client.post(
        "/api/v1/immobilier/communications/envoyer",
        headers=auth_headers,
        json={
            "type": "demande_assurance",
            "immeuble_ids": [ext["immeuble_id"]],
            "locataire_ids": [],
            "from_email": "info@immohorizon.com",
            "inclure_gestion_externe": True,
        },
    )
    assert r2.status_code == 422, r2.text
    assert fake_mailer.sent == []

    # (e) Viser le LOCATAIRE directement par son id ne contourne rien
    # non plus — c'est le chemin qu'un identifiant forgé emprunterait.
    r3 = client.post(
        "/api/v1/immobilier/communications/envoyer",
        headers=auth_headers,
        json={
            "type": "demande_assurance",
            "immeuble_ids": [],
            "locataire_ids": [ext["locataire_id"]],
            "from_email": "info@immohorizon.com",
        },
    )
    assert r3.status_code == 422, r3.text
    assert fake_mailer.sent == []


def test_historique_porte_le_suivi_du_document(client, auth_headers, run):
    """L'historique doit dire OÙ EN EST chaque envoi (retour Phil
    2026-08-19 : « il faut absolument que j'aie un suivi quelque part »).

    Un courriel simple ne peut rien dire de plus que « parti » —
    personne ne peut confirmer qu'il a été lu. Un envoi qui portait un
    DOCUMENT sait, lui, quand le lien a été ouvert et quand il a été
    signé : c'est ce qui tient devant un tribunal.
    """
    import uuid as _uuid
    from datetime import datetime, timezone

    from app.models.immobilier import ImmDocument

    marqueur = f"suivi-{_uuid.uuid4().hex[:8]}"

    async def _seed() -> None:
        async with TestSessionLocal() as s:
            ouvert = datetime(2026, 8, 18, 14, 30, tzinfo=timezone.utc)
            signe = datetime(2026, 8, 18, 14, 42, tzinfo=timezone.utc)
            # (a) document OUVERT mais pas encore signé
            d1 = ImmDocument(
                type="avis_reprise", titre="Reprise (suivi)",
                ouvert_le=ouvert,
            )
            # (b) document SIGNÉ
            d2 = ImmDocument(
                type="avis_reprise", titre="Reprise signée (suivi)",
                ouvert_le=ouvert, signed_at=signe,
                signed_by_name="Locataire Signeur",
            )
            # (c) document d'INFORMATION : aucune signature attendue
            d3 = ImmDocument(
                type="avis_acces", titre="Accès (suivi)", ouvert_le=ouvert,
            )
            s.add_all([d1, d2, d3])
            await s.flush()
            for i, doc in enumerate([d1, d2, d3, None]):
                s.add(
                    ImmCommunication(
                        group_id=str(_uuid.uuid4()),
                        type="document_signature" if doc else "libre",
                        sujet=f"{marqueur} {i}",
                        corps="<p>x</p>",
                        destinataire_email="suivi@test.local",
                        document_id=doc.id if doc else None,
                        created_at=datetime.now(timezone.utc),
                    )
                )
            await s.commit()

    run(_seed())
    r = client.get(
        f"/api/v1/immobilier/communications?q={marqueur}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    par_sujet = {x["sujet"]: x for x in r.json()}
    assert len(par_sujet) == 4, par_sujet

    ouvert_non_signe = par_sujet[f"{marqueur} 0"]
    assert ouvert_non_signe["document_ouvert_le"] is not None
    assert ouvert_non_signe["document_signe_le"] is None
    assert ouvert_non_signe["document_signature_requise"] is True

    signe = par_sujet[f"{marqueur} 1"]
    assert signe["document_signe_le"] is not None
    assert signe["document_signe_par"] == "Locataire Signeur"

    # Un document d'information est « ouvert », jamais « pas encore
    # signé » — ce serait un faux reproche.
    info = par_sujet[f"{marqueur} 2"]
    assert info["document_ouvert_le"] is not None
    assert info["document_signature_requise"] is False

    # Courriel simple : aucun suivi possible, et surtout aucune
    # invention de suivi.
    simple = par_sujet[f"{marqueur} 3"]
    assert simple["document_id"] is None
    assert simple["document_ouvert_le"] is None
    assert simple["document_signature_requise"] is False
