"""Journal d'événements AUTOMATIQUE — chantier « IA au courant de
tout » (GO Phil 2026-09-02).

Chaque ÉCRITURE de l'API (POST/PUT/PATCH/DELETE réussie) est
journalisée dans AuditLog sans instrumenter les centaines d'endpoints
un par un : utilisateur (JWT), méthode, chemin, entité devinée du
chemin, et un extrait du corps JSON avec les champs sensibles masqués.
Les appels déjà journalisés finement par ``log_action`` coexistent —
le sommaire du jour agrège les deux.

Garde-fous :
- best-effort intégral : AUCUNE erreur d'audit ne casse la requête ;
- chemins sensibles/bruyants exclus (auth par mot de passe, webhooks
  Twilio, cron, MCP — qui journalise déjà ses écritures, public) ;
- mots de passe / clés / jetons masqués avant stockage ;
- le corps est capté au passage (jamais lu d'avance ni rejoué) ;
- l'entrée s'écrit une fois la requête ENTIÈREMENT terminée côté app
  (réponse envoyée, session DB rendue) — voir ``AuditMiddleware``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger(__name__)

_METHODES = {"POST", "PUT", "PATCH", "DELETE"}

#: Préfixes de chemin EXCLUS du journal automatique.
_EXCLUS = (
    "/api/v1/auth/login",
    "/api/v1/auth/mot-de-passe-oublie",
    "/api/v1/auth/reinitialiser-mot-de-passe",
    "/api/v1/auth/change-password",
    "/api/v1/mcp",       # journalise déjà ses écritures (cartes/outils)
    "/api/v1/cron",      # jobs machine (secret en query)
    "/api/v1/public",    # pas d'utilisateur (liens tokenisés)
    "/api/v1/voice/twilio",   # webhooks machine à fort volume
    "/api/v1/voice/incoming",
    "/api/v1/push",      # abonnements navigateur (bruit)
    "/api/v1/ai/ping",
    "/api/v1/audit",     # ne pas s'auto-journaliser
)

_CLES_SENSIBLES = re.compile(
    r"password|passe|api_key|apikey|token|secret|cle|key$"
    # Paiements fournisseurs : numéro de compte bancaire, code de double
    # authentification, réponse Interac (les clés VoPay tombent sous
    # « cle » et « secret »).
    r"|numero_compte|code_2fa|interac_reponse",
    re.I,
)

_MAX_EXTRAIT = 700
#: Au-delà de cette taille, le corps n'est plus conservé pour l'extrait
#: (téléversements de fichiers) : seule sa taille est journalisée.
_MAX_CORPS = 1024 * 1024


def _masquer(obj: Any, profondeur: int = 0) -> Any:
    if profondeur > 3:
        return "…"
    if isinstance(obj, dict):
        return {
            k: ("•••" if _CLES_SENSIBLES.search(str(k)) else _masquer(v, profondeur + 1))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_masquer(v, profondeur + 1) for v in obj[:20]]
    if isinstance(obj, str) and len(obj) > 200:
        return obj[:200] + "…"
    return obj


def _entite_du_chemin(path: str) -> tuple[str, Optional[int]]:
    """Devine (entity_type, entity_id) du chemin : les segments non
    numériques forment le type (ex. ``immobilier.baux.frais``), le
    DERNIER segment numérique est l'id."""
    segs = [s for s in path.split("/") if s]
    # retire le préfixe api/v1
    if segs[:2] == ["api", "v1"]:
        segs = segs[2:]
    mots: list[str] = []
    entity_id: Optional[int] = None
    for s in segs:
        if s.isdigit():
            entity_id = int(s)
        else:
            mots.append(s.replace("-", "_"))
    entity_type = ".".join(mots)[:64] or "api"
    return entity_type, entity_id


class AuditMiddleware:
    """Middleware ASGI « pur » (pas ``BaseHTTPMiddleware``).

    L'entrée s'écrit APRÈS que l'app aval a entièrement terminé la
    requête : réponse envoyée au client, dépendances FastAPI fermées
    (la session DB de la requête est commitée et rendue) et
    BackgroundTasks de l'endpoint exécutées. Zéro latence côté client
    (la réponse est déjà partie) et aucune course sur la base.

    Pourquoi plus ``BaseHTTPMiddleware`` + ``BackgroundTask`` : depuis
    Starlette 1.4, ce middleware retient l'app aval tant que SA réponse
    — tâche de fond incluse — n'est pas envoyée. L'écriture d'audit
    tournait donc PENDANT que la session de la requête tenait encore sa
    transaction ouverte : sous SQLite (tests) « database is locked »
    après 5 s d'attente → aucune entrée journalisée et chaque écriture
    API ralentie de 5 s (CI rouge sur main depuis #1719).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = request.url.path
        methode = request.method
        if (
            methode not in _METHODES
            or not path.startswith("/api/v1")
            or any(path.startswith(p) for p in _EXCLUS)
        ):
            await self.app(scope, receive, send)
            return

        # Capte le corps AU PASSAGE : l'endpoint le lit normalement, on
        # n'en garde une copie que jusqu'à _MAX_CORPS (au-delà, seule la
        # taille totale est journalisée).
        morceaux: list[bytes] = []
        retenu = 0
        octets = 0
        statut: Optional[int] = None

        async def _receive() -> Message:
            nonlocal retenu, octets
            message = await receive()
            if message["type"] == "http.request":
                bloc = message.get("body", b"") or b""
                octets += len(bloc)
                if bloc and retenu < _MAX_CORPS:
                    morceaux.append(bloc)
                    retenu += len(bloc)
            return message

        async def _send(message: Message) -> None:
            nonlocal statut
            if message["type"] == "http.response.start":
                statut = int(message.get("status", 0))
            await send(message)

        await self.app(scope, _receive, _send)

        if statut is None or statut >= 400:
            return
        auth = request.headers.get("authorization") or ""
        await self._journaliser(
            methode, auth, path, b"".join(morceaux), statut, octets
        )

    async def _journaliser(
        self,
        methode: str,
        auth: str,
        path: str,
        corps: bytes,
        statut: int,
        octets: int,
    ) -> None:
        try:
            await self._journaliser_brut(
                methode, auth, path, corps, statut, octets
            )
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            log.debug("audit auto raté pour %s: %s", path, exc)

    async def _journaliser_brut(
        self,
        methode: str,
        auth: str,
        path: str,
        corps: bytes,
        statut: int,
        octets: int,
    ) -> None:
        from app.core.security import decode_token
        from app.db.session import AsyncSessionLocal
        from app.models.audit_log import AuditLog
        from app.models.user import User

        # Utilisateur via le JWT (sans dépendance) — absent = requête
        # machine/clé API : on journalise quand même, sans user.
        user_id: Optional[int] = None
        user_email: Optional[str] = None
        if auth.lower().startswith("bearer "):
            sub = decode_token(auth[7:].strip())
            if sub and str(sub).isdigit():
                user_id = int(sub)

        extrait: Optional[dict] = None
        if octets:
            try:
                if len(corps) != octets:
                    raise ValueError("corps tronqué (> _MAX_CORPS)")
                data = json.loads(corps.decode("utf-8"))
                masque = _masquer(data)
                brut = json.dumps(masque, ensure_ascii=False, default=str)
                if len(brut) > _MAX_EXTRAIT:
                    brut = brut[:_MAX_EXTRAIT] + "…"
                    extrait = {"_tronque": True, "corps": brut}
                else:
                    extrait = masque if isinstance(masque, dict) else {
                        "corps": masque
                    }
            except Exception:  # noqa: BLE001 — multipart/binaire
                extrait = {"_type": "non-json", "octets": octets}

        entity_type, entity_id = _entite_du_chemin(path)
        details = {
            "auto": True,
            "methode": methode,
            "chemin": path,
            "statut": statut,
        }
        if extrait:
            details["corps"] = extrait

        async with AsyncSessionLocal() as db:
            if user_id is not None:
                u = await db.get(User, user_id)
                if u is not None:
                    user_email = u.email
            db.add(
                AuditLog(
                    user_id=user_id,
                    user_email=user_email,
                    action=f"api.{methode.lower()}",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    details_json=json.dumps(
                        details, ensure_ascii=False, default=str
                    ),
                )
            )
            await db.commit()
