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
- le corps est rejoué en aval (le endpoint le relit normalement).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from starlette.background import BackgroundTask, BackgroundTasks
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

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
    r"password|passe|api_key|apikey|token|secret|cle|key$", re.I
)

_MAX_EXTRAIT = 700


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


async def _executer(tache) -> None:
    """Exécute une BackgroundTask existante (chaînage best-effort)."""
    try:
        await tache()
    except Exception as exc:  # noqa: BLE001
        log.debug("background chaîné en échec : %s", exc)


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (
            request.method not in _METHODES
            or not path.startswith("/api/v1")
            or any(path.startswith(p) for p in _EXCLUS)
        ):
            return await call_next(request)

        # Lit le corps puis le REJOUE pour l'endpoint aval.
        corps: bytes = b""
        try:
            corps = await request.body()

            async def _receive():
                return {
                    "type": "http.request",
                    "body": corps,
                    "more_body": False,
                }

            request._receive = _receive  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            corps = b""

        response = await call_next(request)

        if response.status_code >= 400:
            return response

        # Écrit APRÈS l'envoi de la réponse (BackgroundTask) : zéro
        # latence ajoutée, et la session de la requête est déjà rendue
        # (pas de course sur la base — notamment SQLite en test).
        methode = request.method
        auth = request.headers.get("authorization") or ""
        statut = response.status_code
        tache = BackgroundTask(
            self._journaliser, methode, auth, path, corps, statut
        )
        if response.background is None:
            response.background = tache
        else:
            groupe = BackgroundTasks()
            groupe.add_task(_executer, response.background)
            groupe.add_task(_executer, tache)
            response.background = groupe
        return response

    async def _journaliser(
        self, methode: str, auth: str, path: str, corps: bytes, statut: int
    ) -> None:
        try:
            await self._journaliser_brut(methode, auth, path, corps, statut)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            log.debug("audit auto raté pour %s: %s", path, exc)

    async def _journaliser_brut(
        self, methode: str, auth: str, path: str, corps: bytes, statut: int
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
        if corps:
            try:
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
                extrait = {"_type": "non-json", "octets": len(corps)}

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
