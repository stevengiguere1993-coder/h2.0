"""Serveur MCP « remote » de Kratos — connecteur custom pour Claude.

Expose, EN LECTURE SEULE, l'activité Kratos de l'utilisateur propriétaire
d'une clé d'API (`krts_...`) au protocole Model Context Protocol (MCP),
transport « Streamable HTTP » (JSON-RPC 2.0 sur un POST unique). C'est ce
que consomment les connecteurs custom de claude.ai / Claude Code / Cowork.

Pourquoi une implémentation JSON-RPC native plutôt que le SDK FastMCP ?
  - Kratos est en PRODUCTION. La priorité absolue est de NE JAMAIS casser
    le démarrage de l'app. Monter une sous-application ASGI FastMCP impose
    de propager son `lifespan` (sinon le session-manager n'est pas
    initialisé) : un couplage fragile au cœur du cycle de vie de l'app.
    FastMCP est par ailleurs passé en 3.x (refonte d'API) en 2026 et
    tirerait des dépendances supplémentaires au `pip install` — un risque
    de cassure du déploiement Render.
  - Le protocole « Streamable HTTP » est un standard ouvert simple : un
    POST JSON-RPC sur une seule URL. Pour 3 outils en lecture seule, le
    coder nativement supprime TOUTE dépendance externe et TOUT couplage au
    lifespan → impossible de casser le startup. C'est aussi un simple
    `APIRouter` : si son montage échoue, l'app démarre quand même (le
    montage est de toute façon entouré d'un try/except dans main.py).

Authentification (connecteur « authless » côté Claude) :
  La clé voyage dans le PATH : `…/api/v1/mcp/{api_key}`. claude.ai ne
  permet pas d'en-tête custom fiable pour un connecteur, mais accepte une
  URL dédiée. À chaque requête on valide la clé (hash SHA-256 + lookup
  `api_keys` active/non expirée), on charge le User, et on scope TOUS les
  outils à cet utilisateur. Clé invalide → erreur JSON-RPC d'auth propre.

Outils exposés (tous en LECTURE SEULE, aucune mutation) :
  - kratos_my_activity   : activité d'un jour (tâches tous pôles + audit).
  - kratos_my_summary    : résumé en français de l'activité d'un jour.
  - kratos_activity_range: activité agrégée sur une plage from/to.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from app.api.api_key_deps import API_KEY_PREFIX, hash_api_key
from app.api.v1.endpoints.activity import (
    _build_summary,
    _collect_audit,
    _collect_tasks,
    _resolve_window,
)
from app.db.session import AsyncSessionLocal
from app.models.api_key import ApiKey
from app.models.user import User

logger = logging.getLogger(__name__)


# Version du protocole MCP annoncée au handshake. claude.ai (connecteurs
# custom) parle « 2025-06-18 » ; on renvoie la version demandée par le
# client si elle est fournie, sinon ce défaut, pour rester compatible.
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

# Métadonnées du serveur renvoyées à l'`initialize`.
SERVER_NAME = "kratos-activity"
SERVER_VERSION = "1.0.0"


router = APIRouter(prefix="/mcp", tags=["mcp"])


# ── Définition des outils (lecture seule) ──────────────────────────
#
# Descriptions soignées : c'est ce qui permet à Claude de savoir QUAND
# appeler chaque outil. Toutes les dates sont au format YYYY-MM-DD, fuseau
# America/Toronto ; le défaut est « aujourd'hui ».

_DATE_PROP = {
    "type": "string",
    "description": (
        "Date au format YYYY-MM-DD (fuseau America/Toronto). "
        "Optionnel : par défaut, la journée d'aujourd'hui."
    ),
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "kratos_my_activity",
        "description": (
            "Renvoie l'activité Kratos de l'utilisateur pour une journée : "
            "toutes les tâches complétées / créées / modifiées sur tous les "
            "pôles (dev logiciel, entreprise, prospection, ventes, chantier) "
            "ainsi que les entrées du journal d'audit (soumissions, factures, "
            "etc.). Utilise cet outil quand on te demande « qu'est-ce que j'ai "
            "fait aujourd'hui / tel jour » ou un détail de l'activité d'une "
            "journée précise. Lecture seule."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"date": _DATE_PROP},
            "additionalProperties": False,
        },
    },
    {
        "name": "kratos_my_summary",
        "description": (
            "Renvoie un RÉSUMÉ en français, prêt à lire, de l'activité Kratos "
            "de l'utilisateur pour une journée (nombre de tâches complétées par "
            "pôle, créées, modifiées, soumissions/factures envoyées…). Utilise "
            "cet outil quand on veut une synthèse rapide d'une journée plutôt "
            "que le détail. Lecture seule."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"date": _DATE_PROP},
            "additionalProperties": False,
        },
    },
    {
        "name": "kratos_activity_range",
        "description": (
            "Renvoie l'activité Kratos agrégée sur une PLAGE de dates "
            "(paramètres `from` et `to`, inclus, format YYYY-MM-DD, fuseau "
            "America/Toronto) : tâches tous pôles, audit et résumé en français. "
            "Utilise cet outil pour « cette semaine », « du X au Y », un bilan "
            "sur plusieurs jours. Lecture seule."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "from": {
                    "type": "string",
                    "description": "Début de plage, YYYY-MM-DD (inclus).",
                },
                "to": {
                    "type": "string",
                    "description": "Fin de plage, YYYY-MM-DD (inclus).",
                },
            },
            "required": ["from", "to"],
            "additionalProperties": False,
        },
    },
]

_TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


# ── Authentification par clé d'API (clé dans le path) ──────────────


async def _user_from_key(db, raw_key: str) -> Optional[User]:
    """Valide une clé `krts_...` et retourne le User propriétaire (actif),
    ou None si la clé est absente / invalide / révoquée / expirée / sans
    utilisateur actif. Met à jour `last_used_at` (best-effort).

    Réutilise exactement la même logique de validation que la dépendance
    d'auth `get_user_from_api_key` (hash SHA-256, lookup `api_keys` active,
    contrôle d'expiration en UTC, User actif)."""
    from datetime import timezone

    from sqlalchemy import select

    if not raw_key or not raw_key.startswith(API_KEY_PREFIX):
        return None

    key_hash = hash_api_key(raw_key)
    stmt = select(ApiKey).where(
        ApiKey.key_hash == key_hash,
        ApiKey.is_active.is_(True),
    )
    api_key = (await db.execute(stmt)).scalar_one_or_none()
    if api_key is None:
        return None

    now = datetime.now(timezone.utc)
    if api_key.expires_at is not None:
        expires_at = api_key.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            return None

    user = await db.get(User, api_key.user_id)
    if user is None or not user.is_active:
        return None

    # Traçabilité du dernier usage — best-effort, ne bloque jamais l'auth.
    try:
        api_key.last_used_at = now
        await db.flush()
        await db.commit()
    except Exception:
        pass

    return user


# ── Construction des résultats d'outils (réutilise activity.py) ────


async def _activity_payload(
    db,
    user: User,
    *,
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict[str, Any]:
    """Calcule l'activité (tâches + audit + résumé) en réutilisant la
    logique des endpoints `/activity/me`. Retourne un dict JSON-sérialisable
    scopé à `user`."""
    start, end = _resolve_window(date, date_from, date_to)
    single_day = (end - start) <= timedelta(days=1)

    tasks = await _collect_tasks(db, user, start, end)
    audit = await _collect_audit(db, user, start, end)
    summary = _build_summary(tasks, audit, start, end, single_day)

    return {
        "user_email": user.email,
        "timezone": "America/Toronto",
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "summary": summary,
        "tasks": [
            {
                "pole": t.pole,
                "title": t.title,
                "status": t.status,
                "is_completed": t.is_completed,
                "completed_at": (
                    t.completed_at.isoformat() if t.completed_at else None
                ),
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                "reasons": t.reasons,
            }
            for t in tasks
        ],
        "audit": [
            {
                "action": a.action,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
                "summary": a.summary,
            }
            for a in audit
        ],
    }


async def _call_tool(db, user: User, name: str, arguments: dict[str, Any]) -> Any:
    """Exécute un outil et retourne sa valeur (dict ou str). Lève
    KeyError/ValueError pour un outil inconnu ou des arguments invalides."""
    arguments = arguments or {}
    if name == "kratos_my_activity":
        return await _activity_payload(db, user, date=arguments.get("date"))
    if name == "kratos_my_summary":
        payload = await _activity_payload(db, user, date=arguments.get("date"))
        # On ne renvoie que le résumé texte pour cet outil.
        return {
            "period_start": payload["period_start"],
            "period_end": payload["period_end"],
            "summary": payload["summary"],
        }
    if name == "kratos_activity_range":
        date_from = arguments.get("from")
        date_to = arguments.get("to")
        if not date_from or not date_to:
            raise ValueError("Les paramètres `from` et `to` (YYYY-MM-DD) sont requis.")
        return await _activity_payload(
            db, user, date_from=date_from, date_to=date_to
        )
    raise KeyError(name)


# ── Helpers JSON-RPC 2.0 ───────────────────────────────────────────


def _rpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _content_text(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


async def _handle_rpc(
    db, user: User, message: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Traite un message JSON-RPC MCP et retourne la réponse JSON-RPC, ou
    None pour une notification (pas de réponse attendue). `user` est déjà
    authentifié et toutes les données sont scopées à lui."""
    import json

    method = message.get("method")
    req_id = message.get("id")

    # Notifications (« notifications/initialized », « notifications/* ») :
    # pas de réponse JSON-RPC.
    if method is not None and method.startswith("notifications/"):
        return None
    if method == "initialized":  # tolérance legacy
        return None

    if method == "initialize":
        params = message.get("params") or {}
        client_proto = params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION
        return _rpc_result(
            req_id,
            {
                "protocolVersion": client_proto,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Outils en lecture seule sur l'activité Kratos de "
                    f"{user.email} : tâches (tous pôles) et journal d'audit, "
                    "par jour ou par plage de dates (fuseau America/Toronto)."
                ),
            },
        )

    if method in ("ping",):
        return _rpc_result(req_id, {})

    if method == "tools/list":
        return _rpc_result(req_id, {"tools": TOOLS})

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in _TOOLS_BY_NAME:
            return _rpc_error(req_id, -32602, f"Outil inconnu : {name}")
        try:
            value = await _call_tool(db, user, name, arguments)
        except ValueError as exc:
            # Erreur « métier » → on la renvoie comme résultat d'outil en
            # erreur (isError), pas comme erreur JSON-RPC protocolaire.
            result = _content_text(str(exc))
            result["isError"] = True
            return _rpc_result(req_id, result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP tools/call %s a échoué : %s", name, exc)
            result = _content_text(f"Erreur interne lors de l'appel de {name}.")
            result["isError"] = True
            return _rpc_result(req_id, result)

        text = value if isinstance(value, str) else json.dumps(
            value, ensure_ascii=False, default=str
        )
        result = _content_text(text)
        # `structuredContent` : pratique pour les clients qui le supportent.
        if isinstance(value, dict):
            result["structuredContent"] = value
        return _rpc_result(req_id, result)

    # Méthode non supportée.
    if req_id is None:
        return None
    return _rpc_error(req_id, -32601, f"Méthode non supportée : {method}")


# ── Endpoint Streamable HTTP (POST + GET) ──────────────────────────


def _unauthorized() -> JSONResponse:
    """Réponse 401 propre (clé invalide). On renvoie un corps JSON-RPC
    d'erreur ET le bon statut HTTP pour que les clients MCP comprennent."""
    return JSONResponse(
        status_code=401,
        content=_rpc_error(None, -32001, "Clé d'API invalide ou manquante."),
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/{api_key}")
async def mcp_streamable_http(
    request: Request,
    api_key: str = Path(..., description="Clé d'API krts_... scoping la session."),
) -> JSONResponse:
    """Point d'entrée Streamable HTTP du serveur MCP.

    URL du connecteur : `https://<host>/api/v1/mcp/krts_xxx`. Reçoit un
    message JSON-RPC (ou un batch) ; valide la clé du path ; route vers le
    handler ; renvoie la/les réponses JSON-RPC. Lecture seule."""
    # Auth : clé dans le path. Session DB dédiée (on n'est pas dans le
    # graphe de dépendances FastAPI classique ici).
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=_rpc_error(None, -32700, "JSON invalide (parse error)."),
        )

    async with AsyncSessionLocal() as db:
        user = await _user_from_key(db, api_key)
        if user is None:
            return _unauthorized()

        # Batch JSON-RPC (liste) ou message unique.
        if isinstance(body, list):
            responses: list[dict[str, Any]] = []
            for msg in body:
                if not isinstance(msg, dict):
                    continue
                resp = await _handle_rpc(db, user, msg)
                if resp is not None:
                    responses.append(resp)
            # Que des notifications → 202 sans corps.
            if not responses:
                return JSONResponse(status_code=202, content=None)
            return JSONResponse(content=responses)

        if not isinstance(body, dict):
            return JSONResponse(
                status_code=400,
                content=_rpc_error(None, -32600, "Requête JSON-RPC invalide."),
            )

        resp = await _handle_rpc(db, user, body)
        if resp is None:
            # Notification : 202 Accepted, pas de corps JSON-RPC.
            return JSONResponse(status_code=202, content=None)
        return JSONResponse(content=resp)


@router.get("/{api_key}")
async def mcp_streamable_http_get(
    api_key: str = Path(..., description="Clé d'API krts_... scoping la session."),
) -> JSONResponse:
    """GET sur l'endpoint Streamable HTTP. Le transport Streamable HTTP
    réserve le GET à l'ouverture d'un flux SSE serveur→client (notifications
    non sollicitées). Ce serveur est sans état et ne pousse rien : on
    répond proprement par 405 (méthode non autorisée pour le GET) après
    avoir tout de même validé la clé pour ne pas fuiter d'info."""
    async with AsyncSessionLocal() as db:
        user = await _user_from_key(db, api_key)
        if user is None:
            return _unauthorized()
    return JSONResponse(
        status_code=405,
        content=_rpc_error(
            None, -32000, "Streaming SSE non supporté ; utilisez POST (JSON-RPC)."
        ),
        headers={"Allow": "POST"},
    )
