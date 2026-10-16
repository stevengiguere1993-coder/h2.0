"""Interrupteur « rappels suspendus » d'une facture (cron facture_reminders).

Une facture en retard dont les rappels sont suspendus passe bien au
statut « overdue » mais ne reçoit aucun courriel, et son historique de
rappels reste intact. Les autres factures en retard reçoivent le leur.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.jobs import facture_reminders as job
from app.models.facture import FactureStatus


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeDb:
    def __init__(self, factures, client):
        self._factures = factures
        self._client = client
        self._calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        self._calls += 1
        # 1er appel : la liste des factures ; ensuite : le client.
        if self._calls == 1:
            return _Result(self._factures)
        return _Result([self._client])

    async def commit(self):
        pass


class _Mailer:
    ready = True

    def __init__(self):
        self.sent = []

    async def send(self, **kwargs):
        self.sent.append(kwargs)


def _facture(ref, paused):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=ref,
        reference=ref,
        client_id=1,
        status=FactureStatus.SENT.value,
        due_at=now - timedelta(days=10),
        last_reminder_at=None,
        next_reminder_at=None,
        reminder_count=2 if paused else 0,
        reminders_paused=paused,
    )


def test_facture_suspendue_ne_recoit_aucun_rappel(monkeypatch):
    suspendue = _facture("F-PAUSE", True)
    active = _facture("F-ACTIVE", False)
    mailer = _Mailer()
    client = SimpleNamespace(email="client@example.com")

    async def _enabled(_key):
        return True

    async def _int(_key, _field, default):
        return default

    async def _pdf(_db, _id):
        return None

    async def _balance(_db, _fa):
        return 100.0

    import app.services.automation_state as automation_state

    monkeypatch.setattr(automation_state, "is_automation_enabled", _enabled)
    monkeypatch.setattr(automation_state, "get_automation_int", _int)
    monkeypatch.setattr(
        job, "AsyncSessionLocal", lambda: _FakeDb([suspendue, active], client)
    )
    monkeypatch.setattr(job, "get_mailer", lambda: mailer)
    monkeypatch.setattr(job, "render_facture_pdf", _pdf)
    monkeypatch.setattr(job, "_compute_balance", _balance)

    result = asyncio.run(job.run())

    assert result["reminders_sent"] == 1
    assert result["skipped_paused"] == 1
    assert [m["subject"] for m in mailer.sent] == ["Rappel — Facture F-ACTIVE"]
    # La facture suspendue est bien marquée en retard, sans toucher à
    # son historique de rappels.
    assert suspendue.status == FactureStatus.OVERDUE.value
    assert suspendue.reminder_count == 2
    assert suspendue.last_reminder_at is None
    assert suspendue.next_reminder_at is None
    assert active.reminder_count == 1
