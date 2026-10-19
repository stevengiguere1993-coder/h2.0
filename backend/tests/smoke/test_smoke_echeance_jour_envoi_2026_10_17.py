"""Smoke — échéance au minimum le jour de l'envoi (2026-10-17).

Steven, facture 160 : « date d'échéance devrait être au minimum la
journée envoyé ». Créée en brouillon le 14 octobre avec « Payable sur
réception » (échéance = jour de la création), envoyée le 16 au soir :
l'échéance était restée au 14 (« Date personnalisée ») et les rappels
automatiques seraient partis deux à trois jours après l'envoi.

Couvre :
1. jour d'envoi = jour de Montréal (22 h 45 le 16 = le 16, pas le 17) ;
2. à l'envoi, les conditions comptent depuis le jour de l'envoi et une
   date personnalisée antérieure y est ramenée, AVANT le rendu du PDF ;
3. saisie : une date avant le jour de l'envoi (aujourd'hui pour un
   brouillon) est refusée avec la raison, une date renvoyée telle quelle
   ne bloque rien et garde les conditions ;
4. correction unique des factures déjà envoyées (dont un cas 160) et
   conditions déduites des factures existantes (« sur réception »,
   « net 30 »…).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.client import Client
from app.models.facture import Facture, FactureStatus
from app.services import facture_echeance as ech
from tests.smoke.conftest import TestSessionLocal

UTC = timezone.utc
#: Envoi de la 160 : 16 octobre 22 h 45 à Montréal.
ENVOI_160 = datetime(2026, 10, 17, 2, 45, 45, tzinfo=UTC)


def _jour(iso: str | None) -> str | None:
    return iso[:10] if iso else None


# ── 1) Jours civils ────────────────────────────────────────────────


def test_jour_local_est_le_jour_de_montreal():
    assert ech.jour_local(ENVOI_160) == date(2026, 10, 16)
    # Date sans heure (import QuickBooks, sélecteur) : garde son jour.
    assert ech.jour_local(datetime(2026, 10, 14, tzinfo=UTC)) == date(2026, 10, 14)
    # SQLite relit sans fuseau : c'est de l'UTC.
    assert ech.jour_local(datetime(2026, 10, 17, 2, 45)) == date(2026, 10, 16)
    assert ech.jour_local(None) is None
    assert ech.echeance_du_jour(date(2026, 10, 16)) == datetime(
        2026, 10, 16, tzinfo=UTC
    )


def test_conditions_deduites():
    """Import QuickBooks et factures existantes : « sur réception »,
    « net 30 »… retrouvés depuis l'écart entre départ et échéance."""
    jour = date(2026, 10, 1)
    assert ech.conditions_deduites(jour, datetime(2026, 10, 1, tzinfo=UTC)) == 0
    assert ech.conditions_deduites(jour, datetime(2026, 10, 31, tzinfo=UTC)) == 30
    assert ech.conditions_deduites(jour, datetime(2026, 10, 8, tzinfo=UTC)) is None
    assert ech.conditions_deduites(None, datetime(2026, 10, 8, tzinfo=UTC)) is None
    assert ech.conditions_deduites(jour, None) is None


# ── 2) Règle appliquée à l'envoi ───────────────────────────────────


def _facture(**kw) -> Facture:
    return Facture(reference="X", status=FactureStatus.SENT.value, **kw)


def test_envoi_cas_160_sur_reception():
    fa = _facture(
        issued_at=ENVOI_160,
        due_at=datetime(2026, 10, 14, 18, 3, tzinfo=UTC),
        due_in_days=0,
    )
    assert ech.appliquer_a_l_envoi(fa) is True
    assert fa.due_at == datetime(2026, 10, 16, tzinfo=UTC)


def test_envoi_conditions_comptees_depuis_l_envoi():
    fa = _facture(
        issued_at=ENVOI_160,
        due_at=datetime(2026, 11, 13, tzinfo=UTC),  # création + 30
        due_in_days=30,
    )
    ech.appliquer_a_l_envoi(fa)
    assert fa.due_at == datetime(2026, 11, 15, tzinfo=UTC)


def test_envoi_date_personnalisee():
    # Antérieure à l'envoi (ancien brouillon) → ramenée au jour de l'envoi.
    fa = _facture(issued_at=ENVOI_160, due_at=datetime(2026, 10, 14, 18, tzinfo=UTC))
    assert ech.appliquer_a_l_envoi(fa) is True
    assert fa.due_at == datetime(2026, 10, 16, tzinfo=UTC)
    # Postérieure → gardée telle quelle.
    plus_tard = datetime(2026, 10, 30, tzinfo=UTC)
    fa = _facture(issued_at=ENVOI_160, due_at=plus_tard)
    assert ech.appliquer_a_l_envoi(fa) is False
    assert fa.due_at == plus_tard
    # Sans échéance : rien n'est inventé.
    fa = _facture(issued_at=ENVOI_160)
    assert ech.appliquer_a_l_envoi(fa) is False
    assert fa.due_at is None


# ── 3) Saisie ──────────────────────────────────────────────────────


@pytest.fixture()
def le_16_octobre(monkeypatch):
    monkeypatch.setattr(ech, "aujourd_hui", lambda: date(2026, 10, 16))


def test_saisie_brouillon(le_16_octobre):
    brouillon = {"statut": FactureStatus.DRAFT.value, "emise_le": None}
    with pytest.raises(ech.EcheanceInvalide, match=r"aujourd'hui \(2026-10-16\)"):
        ech.normaliser_saisie(
            {"due_at": datetime(2026, 10, 15, tzinfo=UTC)}, **brouillon
        )
    assert ech.normaliser_saisie(
        {"due_at": datetime(2026, 10, 16, tzinfo=UTC)}, **brouillon
    ) == {"due_in_days": None, "due_at": datetime(2026, 10, 16, tzinfo=UTC)}
    assert ech.normaliser_saisie({"due_in_days": 30}, **brouillon) == {
        "due_in_days": 30,
        "due_at": datetime(2026, 11, 15, tzinfo=UTC),
    }
    assert ech.normaliser_saisie({"client_note": "x"}, **brouillon) == {}


def test_saisie_facture_envoyee(le_16_octobre):
    envoyee = {"statut": FactureStatus.SENT.value, "emise_le": ENVOI_160}
    with pytest.raises(
        ech.EcheanceInvalide, match=r"jour de l'envoi de la facture \(2026-10-16\)"
    ):
        ech.normaliser_saisie(
            {"due_at": datetime(2026, 10, 15, tzinfo=UTC)}, **envoyee
        )
    # Conditions : comptées depuis le jour de l'envoi.
    assert ech.normaliser_saisie({"due_in_days": 15}, **envoyee)["due_at"] == (
        datetime(2026, 10, 31, tzinfo=UTC)
    )
    # Échéance renvoyée telle quelle (formulaire) : ni refus ni perte des
    # conditions, même si elle précède l'envoi (donnée ancienne).
    ancienne = datetime(2026, 10, 14, 18, 3, tzinfo=UTC)
    assert (
        ech.normaliser_saisie(
            {"due_at": datetime(2026, 10, 14, tzinfo=UTC)},
            **envoyee,
            actuelle=ancienne,
        )
        == {}
    )
    # Facture annulée : pas de borne.
    assert ech.normaliser_saisie(
        {"due_at": datetime(2026, 1, 1, tzinfo=UTC)},
        statut=FactureStatus.VOID.value,
        emise_le=ENVOI_160,
    )["due_at"] == datetime(2026, 1, 1, tzinfo=UTC)


def _iso(jour: date) -> str:
    return ech.echeance_du_jour(jour).isoformat()


def test_api_creation_et_modification(client, auth_headers):
    aujourd_hui = ech.aujourd_hui()
    hier = aujourd_hui - timedelta(days=1)

    r = client.post(
        "/api/v1/factures", json={"due_at": _iso(hier)}, headers=auth_headers
    )
    assert r.status_code == 422, r.text
    assert "ne peut pas précéder aujourd'hui" in r.json()["detail"]

    r = client.post("/api/v1/factures", json={"due_in_days": 0}, headers=auth_headers)
    assert r.status_code == 201, r.text
    fa = r.json()
    assert fa["due_in_days"] == 0
    assert _jour(fa["due_at"]) == aujourd_hui.isoformat()

    url = f"/api/v1/factures/{fa['id']}"
    r = client.patch(url, json={"due_at": _iso(hier)}, headers=auth_headers)
    assert r.status_code == 422, r.text

    r = client.patch(url, json={"due_in_days": 30}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["due_in_days"] == 30
    assert _jour(r.json()["due_at"]) == (aujourd_hui + timedelta(days=30)).isoformat()

    # La même date renvoyée garde les conditions.
    r = client.patch(url, json={"due_at": r.json()["due_at"]}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["due_in_days"] == 30

    # Date personnalisée : les conditions sont effacées.
    plus_tard = aujourd_hui + timedelta(days=12)
    r = client.patch(url, json={"due_at": _iso(plus_tard)}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["due_in_days"] is None
    assert _jour(r.json()["due_at"]) == plus_tard.isoformat()


# ── Envoi par l'API ────────────────────────────────────────────────


class FakeMailer:
    ready = True
    sender = "facturation@immohorizon.com"

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, **kw):
        self.sent.append(kw)


@pytest.fixture()
def envoi(monkeypatch):
    """Courriel et PDF simulés ; mémorise les dates vues au rendu.
    QuickBooks n'est pas branché ici : la facture part sans y passer."""
    import app.services.facture_send as service

    mailer = FakeMailer()
    rendus: list[dict] = []

    async def _rendu(db, facture_id, include_statement=False):
        fa = await db.get(Facture, facture_id)
        rendus.append(
            {
                "emise": ech.jour_local(fa.issued_at),
                "echeance": ech.jour_echeance(fa.due_at),
            }
        )
        return fa, b"%PDF-1.4"

    monkeypatch.setattr(service, "get_mailer", lambda: mailer)
    monkeypatch.setattr(service, "render_facture_pdf", _rendu)
    return mailer, rendus


def _brouillon(run, *, cree_il_y_a: int, **kw) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            tag = uuid.uuid4().hex[:8]
            cl = Client(name=f"Client échéance {tag}", email=f"{tag}@example.com")
            s.add(cl)
            await s.flush()
            cree = datetime.now(UTC) - timedelta(days=cree_il_y_a)
            fa = Facture(
                reference=f"ECH-{tag}",
                client_id=cl.id,
                status=FactureStatus.DRAFT.value,
                created_at=cree,
                **kw,
            )
            s.add(fa)
            await s.commit()
            return fa.id

    return run(_go())


def test_envoi_ancien_brouillon_sur_reception(client, auth_headers, run, db_setup, envoi):
    mailer, rendus = envoi
    il_y_a_2_jours = datetime.now(UTC) - timedelta(days=2)
    fid = _brouillon(run, cree_il_y_a=2, due_at=il_y_a_2_jours)

    r = client.post(
        f"/api/v1/factures/{fid}/send",
        json={"to": ["client@example.com"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    aujourd_hui = ech.aujourd_hui()
    assert r.json()["status"] == FactureStatus.SENT.value
    assert _jour(r.json()["due_at"]) == aujourd_hui.isoformat()
    # Le PDF joint porte déjà le jour de l'envoi (émission et échéance).
    assert rendus[-1] == {"emise": aujourd_hui, "echeance": aujourd_hui}
    assert f"<strong>Échéance :</strong> {aujourd_hui.isoformat()}" in (
        mailer.sent[-1]["html_body"]
    )


def test_envoi_conditions_et_renvoi(client, auth_headers, run, db_setup, envoi):
    _, rendus = envoi
    cree = ech.aujourd_hui() - timedelta(days=5)
    fid = _brouillon(
        run,
        cree_il_y_a=5,
        due_at=ech.echeance_du_jour(cree + timedelta(days=30)),
        due_in_days=30,
    )
    url = f"/api/v1/factures/{fid}/send"
    r = client.post(url, json={"to": ["client@example.com"]}, headers=auth_headers)
    assert r.status_code == 200, r.text
    attendu = (ech.aujourd_hui() + timedelta(days=30)).isoformat()
    assert _jour(r.json()["due_at"]) == attendu
    assert rendus[-1]["echeance"].isoformat() == attendu

    # Facture payée renvoyée (copie au client) : ses dates ne bougent pas.
    async def _payee():
        async with TestSessionLocal() as s:
            fa = await s.get(Facture, fid)
            fa.status = FactureStatus.PAID.value
            fa.issued_at = datetime(2026, 9, 1, 15, tzinfo=UTC)
            fa.due_at = datetime(2026, 10, 1, tzinfo=UTC)
            await s.commit()

    run(_payee())
    r = client.post(url, json={"to": ["client@example.com"]}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == FactureStatus.PAID.value
    assert _jour(r.json()["due_at"]) == "2026-10-01"
    assert _jour(r.json()["issued_at"]) == "2026-09-01"


def test_brouillon_marque_envoye_a_la_main(client, auth_headers, run, db_setup):
    fid = _brouillon(
        run, cree_il_y_a=3, due_at=datetime.now(UTC) - timedelta(days=3), due_in_days=0
    )
    r = client.patch(
        f"/api/v1/factures/{fid}",
        json={"status": FactureStatus.SENT.value},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert _jour(r.json()["due_at"]) == ech.aujourd_hui().isoformat()


# ── 4) Correction des factures déjà envoyées ───────────────────────


def test_correction_des_factures_envoyees(run, db_setup):
    """Exécutée puis annulée (rollback) : la base de test est partagée."""

    async def _go():
        async with TestSessionLocal() as s:
            tag = uuid.uuid4().hex[:6]

            def _fa(suffixe, **kw):
                fa = Facture(reference=f"COR-{tag}-{suffixe}", **kw)
                s.add(fa)
                return fa

            cas_160 = _fa(
                "160",
                status=FactureStatus.SENT.value,
                issued_at=ENVOI_160,
                due_at=datetime(2026, 10, 14, 18, 3, tzinfo=UTC),
                qbo_invoice_id="QB-160",
            )
            net_30 = _fa(
                "N30",
                status=FactureStatus.SENT.value,
                issued_at=datetime(2026, 10, 10, 15, tzinfo=UTC),
                due_at=datetime(2026, 11, 9, tzinfo=UTC),
            )
            en_retard = _fa(
                "RET",
                status=FactureStatus.OVERDUE.value,
                issued_at=datetime(2026, 10, 16, 14, tzinfo=UTC),
                due_at=datetime(2026, 10, 10, tzinfo=UTC),
            )
            payee = _fa(
                "PAY",
                status=FactureStatus.PAID.value,
                issued_at=ENVOI_160,
                due_at=datetime(2026, 10, 1, tzinfo=UTC),
            )
            brouillon_net_30 = _fa(
                "BR",
                status=FactureStatus.DRAFT.value,
                created_at=datetime(2026, 10, 14, 17, tzinfo=UTC),
                due_at=datetime(2026, 11, 13, 17, tzinfo=UTC),
            )
            brouillon_libre = _fa(
                "BRL",
                status=FactureStatus.DRAFT.value,
                created_at=datetime(2026, 10, 14, 17, tzinfo=UTC),
                due_at=datetime(2026, 10, 20, tzinfo=UTC),
            )
            await s.flush()

            corrigees = await ech.corriger_echeances_envoyees(
                s, maintenant=datetime(2026, 10, 16, 20, tzinfo=UTC)
            )
            par_ref = {c["reference"]: c for c in corrigees}
            assert par_ref[cas_160.reference] == {
                "id": cas_160.id,
                "reference": cas_160.reference,
                "avant": "2026-10-14",
                "apres": "2026-10-16",
                "qbo": True,
            }
            assert cas_160.due_at == datetime(2026, 10, 16, tzinfo=UTC)
            assert net_30.reference not in par_ref
            assert net_30.due_at == datetime(2026, 11, 9, tzinfo=UTC)
            # Plus en retard selon la nouvelle échéance → « envoyée ».
            assert par_ref[en_retard.reference]["apres"] == "2026-10-16"
            assert en_retard.status == FactureStatus.SENT.value
            # Payée : hors correction.
            assert payee.reference not in par_ref
            assert payee.due_at == datetime(2026, 10, 1, tzinfo=UTC)

            # Conditions déduites : la 160 corrigée est « sur réception »,
            # l'envoyée net 30 et le brouillon net 30 (depuis la création)
            # le deviennent ; une date sans option reste personnalisée.
            assert await ech.deduire_conditions(s) >= 3
            assert cas_160.due_in_days == 0
            assert net_30.due_in_days == 30
            assert brouillon_net_30.due_in_days == 30
            assert brouillon_libre.due_in_days is None
            assert payee.due_in_days is None
            await s.rollback()

    run(_go())


def test_correction_en_retard_qui_le_reste(run, db_setup):
    async def _go():
        async with TestSessionLocal() as s:
            fa = Facture(
                reference=f"COR-{uuid.uuid4().hex[:6]}",
                status=FactureStatus.OVERDUE.value,
                issued_at=datetime(2026, 10, 1, 14, tzinfo=UTC),
                due_at=datetime(2026, 9, 25, tzinfo=UTC),
            )
            s.add(fa)
            await s.flush()
            await ech.corriger_echeances_envoyees(
                s, maintenant=datetime(2026, 10, 16, 20, tzinfo=UTC)
            )
            assert fa.due_at == datetime(2026, 10, 1, tzinfo=UTC)
            assert fa.status == FactureStatus.OVERDUE.value
            await s.rollback()

    run(_go())
