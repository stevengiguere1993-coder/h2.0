"""Smoke — gardes d'état des flux de signature publics (soumission).

Vérifie que les endpoints publics refusent (409) une transition d'état
invalide au lieu de la laisser passer :

- ``public_reject`` sur une soumission déjà ACCEPTÉE → 409 (on ne peut
  pas basculer une soumission signée en « refusée » via le lien public).
- ``public_accept`` rejoué sur une soumission déjà ACCEPTÉE → 409 (pas
  de ré-acceptation : sinon écrasement de la signature + double provision
  projet/facture).

On seed la soumission DIRECTEMENT en DB (avec un ``signature_token``) via
la session de test partagée, puis on frappe les routes publiques (aucune
auth requise — le token fait foi).
"""

import uuid

from app.models.soumission import Soumission, SoumissionStatus

from tests.smoke.conftest import TestSessionLocal


def _seed_accepted_soumission(run) -> str:
    """Crée une soumission déjà ACCEPTÉE et retourne son signature_token."""

    token = "smk-guard-" + uuid.uuid4().hex

    async def _seed() -> str:
        async with TestSessionLocal() as session:
            sm = Soumission(
                reference=f"SM-SMK-{uuid.uuid4().hex[:10]}",
                title="Soumission smoke — garde d'état",
                status=SoumissionStatus.ACCEPTED.value,
                signature_token=token,
                signed_name="Client Déjà Signé",
            )
            session.add(sm)
            await session.commit()
        return token

    return run(_seed())


def test_public_reject_on_accepted_returns_409(client, run):
    token = _seed_accepted_soumission(run)
    resp = client.post(f"/api/v1/public/soumissions/{token}/reject", json={})
    assert resp.status_code == 409, resp.text


def test_public_accept_replay_on_accepted_returns_409(client, run):
    token = _seed_accepted_soumission(run)
    # Rejoue une acceptation avec une signature tracée valide : la garde
    # d'état doit trancher (409) AVANT même la validation de la signature.
    resp = client.post(
        f"/api/v1/public/soumissions/{token}/accept",
        json={
            "name": "Client Rejoueur",
            "signature_image_data_url": (
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
                "CAYAAAAfFcSJAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
            ),
        },
    )
    assert resp.status_code == 409, resp.text
