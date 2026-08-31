"""Smoke — normalisation du claim VAPID ``sub`` (bug prod 2026-08-31 :
``VAPID_SUBJECT`` sans préfixe mailto: → py-vapid refusait chaque envoi
et aucune notification push ne partait, en silence)."""
from __future__ import annotations

from app.integrations.webpush import _vapid_subject


def test_vapid_subject_normalise(monkeypatch):
    # Adresse nue → préfixée mailto: (le cas qui cassait la prod).
    monkeypatch.setenv("VAPID_SUBJECT", "info@immohorizon.com")
    assert _vapid_subject() == "mailto:info@immohorizon.com"

    # Déjà conforme → inchangé.
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:admin@immohorizon.com")
    assert _vapid_subject() == "mailto:admin@immohorizon.com"
    monkeypatch.setenv("VAPID_SUBJECT", "https://immohorizon.com")
    assert _vapid_subject() == "https://immohorizon.com"

    # Vide ou absent → défaut valide.
    monkeypatch.setenv("VAPID_SUBJECT", "   ")
    assert _vapid_subject() == "mailto:info@immohorizon.com"
    monkeypatch.delenv("VAPID_SUBJECT", raising=False)
    assert _vapid_subject() == "mailto:info@immohorizon.com"
