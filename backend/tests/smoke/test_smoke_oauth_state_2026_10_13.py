"""Smoke — state OAuth refusé une fois sur 8 (QuickBooks, Google Drive), 2026-10-13.

Le state signé vaut base64(raw + b"|" + signature HMAC-SHA256). La
vérification coupait au DERNIER « | » ; or la signature, binaire et
longue de 32 octets, contient elle-même l'octet « | » environ une fois
sur 8 (1 − (255/256)^32 ≈ 11,8 %). La coupe tombait alors dans la
signature et un state valide était refusé : retour « qbo=error:
invalid_state » pour QuickBooks, même refus pour Google Drive. En CI,
test_callback_oauth_leve_l_etat_a_reconnecter échouait selon la seconde
où il tournait.

Couvre, pour les deux flux :
1. un state valide est accepté, y compris quand sa signature contient
   l'octet « | » ;
2. un state à la signature modifiée ou tronquée reste refusé.
"""

from __future__ import annotations

import base64
import time

from app.api.v1.endpoints.qbo_oauth import _sign_state as signer_qbo
from app.api.v1.endpoints.qbo_oauth import _verify_state as verifier_qbo
from app.services.drive_oauth import _sign_state as signer_drive
from app.services.drive_oauth import verify_state as verifier_drive

# Sur 200 nonces, la probabilité qu'aucune signature ne contienne « | »
# est d'environ 1e-11 : le cas fautif est toujours couvert.
_NONCES = [f"nonce-{i}" for i in range(200)]


def _decoder(state: str) -> bytes:
    return base64.urlsafe_b64decode(state + "=" * (-len(state) % 4))


def _encoder(decoded: bytes) -> str:
    return base64.urlsafe_b64encode(decoded).decode().rstrip("=")


def _states_qbo() -> list[str]:
    ts = int(time.time())
    return [signer_qbo(n, ts, "construction") for n in _NONCES]


def _states_drive() -> list[str]:
    ts = int(time.time())
    return [signer_drive(7, n, ts) for n in _NONCES]


def test_state_qbo_valide_accepte_meme_avec_pipe_dans_la_signature():
    states = _states_qbo()
    avec_pipe = [s for s in states if b"|" in _decoder(s)[-32:]]
    assert avec_pipe, "aucune signature avec « | » : le cas n'est pas couvert"
    refuses = [s for s in states if verifier_qbo(s) != "construction"]
    assert refuses == [], f"{len(refuses)} states valides refusés sur {len(states)}"


def test_state_drive_valide_accepte_meme_avec_pipe_dans_la_signature():
    states = _states_drive()
    avec_pipe = [s for s in states if b"|" in _decoder(s)[-32:]]
    assert avec_pipe, "aucune signature avec « | » : le cas n'est pas couvert"
    refuses = [s for s in states if verifier_drive(s) != 7]
    assert refuses == [], f"{len(refuses)} states valides refusés sur {len(states)}"


def test_state_falsifie_ou_tronque_refuse():
    for state in _states_qbo()[:20] + _states_drive()[:20]:
        decoded = _decoder(state)
        modifie = decoded[:-1] + bytes([decoded[-1] ^ 0x01])
        for mauvais in (_encoder(modifie), _encoder(decoded[:-1]), state[:10], ""):
            assert verifier_qbo(mauvais) is None
            assert verifier_drive(mauvais) is None
