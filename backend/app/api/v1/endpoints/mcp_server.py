"""Serveur MCP « remote » de Kratos — connecteur custom pour Claude.

Expose l'activité Kratos de l'utilisateur propriétaire d'une clé d'API
(`krts_...`) au protocole Model Context Protocol (MCP), transport
« Streamable HTTP » (JSON-RPC 2.0 sur un POST unique). C'est ce que
consomment les connecteurs custom de claude.ai / Claude Code / Cowork.

Permissions PAR PÔLE : la clé porte des ``scopes`` (``<pole>:<capability>``).
Les outils de LECTURE ne renvoient que l'activité des pôles autorisés
(``<pole>:activity:read``) ; l'outil d'ÉCRITURE ``kratos_create_task``
exige ``<pole>:tasks:create``. RÉTROCOMPAT : une clé sans scopes lit tous
les pôles (mais ne peut rien écrire).

Pourquoi une implémentation JSON-RPC native plutôt que le SDK FastMCP ?
  - Kratos est en PRODUCTION. La priorité absolue est de NE JAMAIS casser
    le démarrage de l'app. Monter une sous-application ASGI FastMCP impose
    de propager son `lifespan` (sinon le session-manager n'est pas
    initialisé) : un couplage fragile au cœur du cycle de vie de l'app.
  - Le protocole « Streamable HTTP » est un standard ouvert simple : un
    POST JSON-RPC sur une seule URL. Le coder nativement supprime TOUTE
    dépendance externe et TOUT couplage au lifespan → impossible de casser
    le startup. C'est aussi un simple `APIRouter` : si son montage échoue,
    l'app démarre quand même (try/except dans main.py).

Authentification (connecteur « authless » côté Claude) :
  La clé voyage dans le PATH : `…/api/v1/mcp/{api_key}`. À chaque requête
  on valide la clé (hash SHA-256 + lookup `api_keys` active/non expirée),
  on charge le User, on récupère ses scopes, et on scope TOUS les outils à
  cet utilisateur. Clé invalide → erreur JSON-RPC d'auth propre.

Outils exposés :
  - kratos_my_activity   : activité d'un jour (tâches pôles autorisés + audit).
  - kratos_my_summary    : résumé en français de l'activité d'un jour.
  - kratos_activity_range: activité agrégée sur une plage from/to.
  - kratos_create_task   : crée une tâche dans un pôle (capacité requise).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from app.api.api_key_deps import API_KEY_PREFIX, hash_api_key
from app.api.v1.endpoints.activity import (
    _DETAIL_ENTITIES,
    _build_summary,
    _collect_audit,
    _collect_tasks,
    _resolve_window,
    create_task_for_pole,
    load_entity_full,
)
from app.db.session import AsyncSessionLocal
from app.models.api_key import ApiKey
from app.models.user import User
from app.services.api_capabilities import (
    POLE_LABELS,
    POLE_SLUGS,
    key_has_scope,
    readable_poles,
)

logger = logging.getLogger(__name__)


class _ScopeCtx:
    """Adaptateur minimal exposant ``has_scope`` à partir d'une liste de
    scopes brute, pour réutiliser ``load_entity_full`` (qui attend un objet
    de contexte) côté MCP, où l'on ne manipule que les scopes."""

    __slots__ = ("scopes",)

    def __init__(self, scopes: Optional[list[str]]):
        self.scopes = scopes

    def has_scope(self, scope: str) -> bool:
        return key_has_scope(self.scopes, scope)


# Version du protocole MCP annoncée au handshake. claude.ai (connecteurs
# custom) parle « 2025-06-18 » ; on renvoie la version demandée par le
# client si elle est fournie, sinon ce défaut, pour rester compatible.
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

# Métadonnées du serveur renvoyées à l'`initialize`.
SERVER_NAME = "kratos-activity"
SERVER_VERSION = "1.1.0"


router = APIRouter(prefix="/mcp", tags=["mcp"])


# ── Définition des outils ──────────────────────────────────────────
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

# Outils de lecture (toujours présents tant qu'au moins un pôle est lisible).
_READ_TOOLS: list[dict[str, Any]] = [
    {
        "name": "kratos_my_activity",
        "description": (
            "Renvoie l'activité Kratos de l'utilisateur pour une journée : "
            "tâches complétées / créées / modifiées sur les pôles autorisés "
            "par la clé, ainsi que les entrées du journal d'audit. Utilise cet "
            "outil quand on te demande « qu'est-ce que j'ai fait aujourd'hui / "
            "tel jour ». Lecture seule."
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
            "de l'utilisateur pour une journée. Utilise cet outil pour une "
            "synthèse rapide d'une journée plutôt que le détail. Lecture seule."
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
            "America/Toronto). Utilise cet outil pour « cette semaine », « du X "
            "au Y », un bilan sur plusieurs jours. Lecture seule."
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

# Outil d'écriture (présent seulement si la clé peut créer une tâche dans
# au moins un pôle). La description liste les pôles autorisés au handshake.
_CREATE_TASK_TOOL_NAME = "kratos_create_task"


def _create_task_tool(creatable_poles: list[str]) -> dict[str, Any]:
    labels = ", ".join(POLE_LABELS.get(p, p) for p in creatable_poles)
    return {
        "name": _CREATE_TASK_TOOL_NAME,
        "description": (
            "Crée une tâche Kratos dans un pôle, assignée à l'utilisateur. "
            f"Pôles autorisés pour cette clé : {labels}. Fournis `pole` (un "
            "de ces slugs), `parent_id` (l'ID de l'entité parente : projet "
            "devlog, entreprise, deal de prospection, ou projet de chantier "
            "selon le pôle), et `title`. `description` et `due_date` "
            "(YYYY-MM-DD) sont optionnels. Écriture — n'utilise cet outil que "
            "sur demande explicite de créer/ajouter une tâche."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pole": {
                    "type": "string",
                    "enum": creatable_poles,
                    "description": "Slug du pôle où créer la tâche.",
                },
                "parent_id": {
                    "type": "integer",
                    "description": (
                        "ID de l'entité parente : projet devlog / entreprise / "
                        "deal de prospection / projet de chantier selon le pôle."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "Titre de la tâche (requis).",
                },
                "description": {
                    "type": "string",
                    "description": "Description de la tâche (optionnel).",
                },
                "due_date": {
                    "type": "string",
                    "description": "Échéance YYYY-MM-DD (optionnel).",
                },
            },
            "required": ["pole", "parent_id", "title"],
            "additionalProperties": False,
        },
    }


# ── Outils de lecture détail (JSON full d'une entité par id) ───────
#
# Chaque outil prend un id, vérifie le scope du pôle (via load_entity_full)
# et renvoie le JSON « full » de l'entité. Présents seulement si le pôle
# correspondant est lisible par la clé.

_GET_SOUMISSION_TOOL = "kratos_get_soumission"
_GET_TASK_TOOL = "kratos_get_task"
_GET_DEAL_TOOL = "kratos_get_deal"
_GET_ENTREPRISE_TOOL = "kratos_get_entreprise"

#: Pôle gouvernant le scope de chaque outil get (pour décider de l'afficher).
_GET_TOOL_POLE: dict[str, str] = {
    _GET_SOUMISSION_TOOL: "devlog",
    _GET_TASK_TOOL: "_any_task",   # plusieurs pôles possibles
    _GET_DEAL_TOOL: "prospection",
    _GET_ENTREPRISE_TOOL: "entreprise",
}

#: Types de tâche reconnus par kratos_get_task → entity_type de détail.
_TASK_TYPE_CHOICES = (
    "devlog_project_task",
    "entreprise_tache",
    "prospection_deal_task",
    "sales_task",
    "project_task",
)


def _get_detail_tools() -> list[dict[str, Any]]:
    """Définitions statiques des 4 outils de lecture détail."""
    return [
        {
            "name": _GET_SOUMISSION_TOOL,
            "description": (
                "Renvoie le JSON DÉTAILLÉ d'une soumission (devis) du pôle "
                "Développement logiciel par son `id` : client/lead, statut, "
                "modules + fonctionnalités + tâches du chargé de projet, "
                "montants (HT, TPS, TVQ, TTC), taux, dates, lien public. "
                "Lecture seule."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Id de la soumission devlog.",
                    }
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        {
            "name": _GET_TASK_TOOL,
            "description": (
                "Renvoie le JSON DÉTAILLÉ d'une tâche par son `id` et son "
                "`type` (description, statut, assigné, échéance, priorité, "
                "pôle, dates). `type` est l'un des modèles de tâche : "
                f"{', '.join(_TASK_TYPE_CHOICES)}. Lecture seule."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Id de la tâche.",
                    },
                    "type": {
                        "type": "string",
                        "enum": list(_TASK_TYPE_CHOICES),
                        "description": "Modèle de tâche (entity_type).",
                    },
                },
                "required": ["id", "type"],
                "additionalProperties": False,
            },
        },
        {
            "name": _GET_DEAL_TOOL,
            "description": (
                "Renvoie le JSON DÉTAILLÉ d'un deal du Pipeline Prospection "
                "par son `id` : adresse, étape pipeline, et données clés de "
                "l'analyse financière liée si disponibles. Lecture seule."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Id du deal de prospection.",
                    }
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        {
            "name": _GET_ENTREPRISE_TOOL,
            "description": (
                "Renvoie le JSON DÉTAILLÉ d'une entreprise du pôle Gestion "
                "d'entreprises par son `id` : nom, type, NEQ, partenaires, "
                "description, statut. Lecture seule."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Id de l'entreprise.",
                    }
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    ]


def _can_read_pole(scopes: Optional[list[str]], pole: str) -> bool:
    """La clé peut-elle lire (détail ou activité) ce pôle ? Couvre la
    rétrocompat (clé sans scopes → tous les pôles via readable_poles)."""
    return pole in readable_poles(scopes)


def _get_tools_for_scopes(scopes: Optional[list[str]]) -> list[dict[str, Any]]:
    """Sous-ensemble des 4 outils get exposés selon les pôles lisibles."""
    tools: list[dict[str, Any]] = []
    for tool in _get_detail_tools():
        name = tool["name"]
        if name == _GET_TASK_TOOL:
            # Disponible si au moins un pôle portant des tâches est lisible.
            poles = {
                _DETAIL_ENTITIES[t][1]
                for t in _TASK_TYPE_CHOICES
                if t in _DETAIL_ENTITIES
            }
            if any(_can_read_pole(scopes, p) for p in poles):
                tools.append(tool)
        else:
            pole = _GET_TOOL_POLE[name]
            if _can_read_pole(scopes, pole):
                tools.append(tool)
    return tools


def _tools_for_scopes(scopes: Optional[list[str]]) -> list[dict[str, Any]]:
    """Liste des outils exposés à cette clé, selon ses scopes. Les outils de
    lecture apparaissent si au moins un pôle est lisible ; l'outil de
    création apparaît si au moins un pôle autorise la création de tâche."""
    tools: list[dict[str, Any]] = []
    if readable_poles(scopes):
        tools.extend(_READ_TOOLS)
        tools.extend(_get_tools_for_scopes(scopes))
    creatable = [
        slug for slug in POLE_SLUGS
        if key_has_scope(scopes, f"{slug}:tasks:create")
    ]
    if creatable:
        tools.append(_create_task_tool(creatable))
    return tools


# ── Authentification par clé d'API (clé dans le path) ──────────────


async def _context_from_key(
    db, raw_key: str
) -> tuple[Optional[User], Optional[list[str]]]:
    """Valide une clé `krts_...` et retourne (User propriétaire actif,
    scopes), ou (None, None) si la clé est absente / invalide / révoquée /
    expirée / sans utilisateur actif. Met à jour `last_used_at` (best-effort).

    Réutilise exactement la même logique de validation que la dépendance
    d'auth `get_api_context`."""
    from datetime import timezone

    from sqlalchemy import select

    if not raw_key or not raw_key.startswith(API_KEY_PREFIX):
        return None, None

    key_hash = hash_api_key(raw_key)
    stmt = select(ApiKey).where(
        ApiKey.key_hash == key_hash,
        ApiKey.is_active.is_(True),
    )
    api_key = (await db.execute(stmt)).scalar_one_or_none()
    if api_key is None:
        return None, None

    now = datetime.now(timezone.utc)
    if api_key.expires_at is not None:
        expires_at = api_key.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            return None, None

    user = await db.get(User, api_key.user_id)
    if user is None or not user.is_active:
        return None, None

    scopes = api_key.scopes

    # Traçabilité du dernier usage — best-effort, ne bloque jamais l'auth.
    try:
        api_key.last_used_at = now
        await db.flush()
        await db.commit()
    except Exception:
        pass

    return user, scopes


# ── Construction des résultats d'outils (réutilise activity.py) ────


async def _activity_payload(
    db,
    user: User,
    allowed_poles: set[str],
    *,
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict[str, Any]:
    """Calcule l'activité (tâches + audit + résumé) pour les pôles
    autorisés, en réutilisant la logique des endpoints `/activity/me`."""
    start, end = _resolve_window(date, date_from, date_to)
    single_day = (end - start) <= timedelta(days=1)

    tasks = await _collect_tasks(db, user, start, end, allowed_poles=allowed_poles)
    audit = await _collect_audit(db, user, start, end, allowed_poles=allowed_poles)
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


async def _get_entity_detail(
    db,
    scopes: Optional[list[str]],
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Charge le JSON « full » d'une entité pour les outils kratos_get_*.

    Détermine l'``entity_type`` à partir du nom de l'outil (et du `type`
    fourni pour les tâches), valide l'`id`, délègue à ``load_entity_full``
    (qui vérifie le scope de pôle). Lève ValueError pour un argument
    invalide, un type de tâche inconnu, un scope manquant ou une entité
    introuvable (l'appelant transforme ValueError en réponse `isError`)."""
    raw_id = arguments.get("id")
    if raw_id is None:
        raise ValueError("`id` (identifiant de l'entité) est requis.")
    try:
        entity_id = int(raw_id)
    except (TypeError, ValueError):
        raise ValueError("`id` doit être un entier.")

    if name == _GET_SOUMISSION_TOOL:
        entity_type = "devlog_soumission"
    elif name == _GET_DEAL_TOOL:
        entity_type = "prospection_deal"
    elif name == _GET_ENTREPRISE_TOOL:
        entity_type = "entreprise"
    elif name == _GET_TASK_TOOL:
        entity_type = str(arguments.get("type") or "").strip()
        if entity_type not in _TASK_TYPE_CHOICES:
            raise ValueError(
                "`type` doit être l'un de : "
                + ", ".join(_TASK_TYPE_CHOICES)
                + "."
            )
    else:  # pragma: no cover - garde-fou
        raise KeyError(name)

    ctx = _ScopeCtx(scopes)
    try:
        return await load_entity_full(db, ctx, entity_type, entity_id)
    except PermissionError as exc:
        raise ValueError(str(exc))
    except LookupError as exc:
        raise ValueError(str(exc))
    except ValueError:
        # « unknown » remonté par load_entity_full — ne devrait pas arriver
        # ici (types contrôlés ci-dessus), mais on reste robuste.
        raise ValueError(f"Type d'entité inconnu : « {entity_type} ».")


async def _call_tool(
    db,
    user: User,
    scopes: Optional[list[str]],
    name: str,
    arguments: dict[str, Any],
) -> Any:
    """Exécute un outil et retourne sa valeur (dict ou str). Lève
    KeyError/ValueError pour un outil inconnu, des arguments invalides, ou
    une capacité non accordée."""
    arguments = arguments or {}
    allowed = readable_poles(scopes)

    if name == "kratos_my_activity":
        return await _activity_payload(db, user, allowed, date=arguments.get("date"))
    if name == "kratos_my_summary":
        payload = await _activity_payload(db, user, allowed, date=arguments.get("date"))
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
            db, user, allowed, date_from=date_from, date_to=date_to
        )

    # ── Outils de lecture détail (JSON full d'une entité par id) ──
    if name in (
        _GET_SOUMISSION_TOOL,
        _GET_TASK_TOOL,
        _GET_DEAL_TOOL,
        _GET_ENTREPRISE_TOOL,
    ):
        return await _get_entity_detail(db, scopes, name, arguments)
    if name == _CREATE_TASK_TOOL_NAME:
        pole = str(arguments.get("pole") or "").strip().lower()
        if pole not in POLE_LABELS:
            raise ValueError(f"Pôle inconnu : « {arguments.get('pole')} ».")
        if not key_has_scope(scopes, f"{pole}:tasks:create"):
            raise ValueError(
                f"Capacité « Créer une tâche » non activée pour le pôle "
                f"« {POLE_LABELS[pole]} » sur cette clé d'API."
            )
        parent_id = arguments.get("parent_id")
        if parent_id is None:
            raise ValueError("`parent_id` (ID de l'entité parente) est requis.")
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            raise ValueError("`parent_id` doit être un entier.")
        title = str(arguments.get("title") or "").strip()
        if not title:
            raise ValueError("`title` (titre de la tâche) est requis.")
        due_raw = arguments.get("due_date")
        due_date = None
        if due_raw:
            from datetime import date as _date_cls
            try:
                due_date = _date_cls.fromisoformat(str(due_raw))
            except ValueError:
                raise ValueError("`due_date` doit être au format YYYY-MM-DD.")
        created = await create_task_for_pole(
            db,
            user,
            pole=pole,
            parent_id=parent_id,
            title=title,
            description=(arguments.get("description") or None),
            due_date=due_date,
            via="mcp",
        )
        # On commit explicitement : on est hors du graphe FastAPI (session
        # gérée à la main dans l'endpoint Streamable HTTP).
        await db.commit()
        return {
            "created": True,
            "pole": created.pole,
            "entity_type": created.entity_type,
            "entity_id": created.entity_id,
            "title": created.title,
            "status": created.status,
        }
    raise KeyError(name)


# ── Helpers JSON-RPC 2.0 ───────────────────────────────────────────


def _rpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _content_text(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


async def _handle_rpc(
    db,
    user: User,
    scopes: Optional[list[str]],
    message: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Traite un message JSON-RPC MCP et retourne la réponse JSON-RPC, ou
    None pour une notification (pas de réponse attendue). `user` est déjà
    authentifié ; `scopes` détermine les outils disponibles et leurs droits."""
    import json

    method = message.get("method")
    req_id = message.get("id")

    if method is not None and method.startswith("notifications/"):
        return None
    if method == "initialized":  # tolérance legacy
        return None

    if method == "initialize":
        params = message.get("params") or {}
        client_proto = params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION
        readable = sorted(readable_poles(scopes))
        readable_labels = ", ".join(POLE_LABELS.get(p, p) for p in readable) or "aucun"
        return _rpc_result(
            req_id,
            {
                "protocolVersion": client_proto,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Outils sur l'activité Kratos de "
                    f"{user.email}. Pôles lisibles par cette clé : "
                    f"{readable_labels}. Lecture par jour ou par plage de "
                    "dates (fuseau America/Toronto) ; création de tâche dans "
                    "les pôles explicitement autorisés."
                ),
            },
        )

    if method in ("ping",):
        return _rpc_result(req_id, {})

    if method == "tools/list":
        return _rpc_result(req_id, {"tools": _tools_for_scopes(scopes)})

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        available = {t["name"] for t in _tools_for_scopes(scopes)}
        if name not in available:
            return _rpc_error(
                req_id, -32602,
                f"Outil indisponible pour cette clé : {name}",
            )
        try:
            value = await _call_tool(db, user, scopes, name, arguments)
        except ValueError as exc:
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
        if isinstance(value, dict):
            result["structuredContent"] = value
        return _rpc_result(req_id, result)

    if req_id is None:
        return None
    return _rpc_error(req_id, -32601, f"Méthode non supportée : {method}")


# ── Endpoint Streamable HTTP (POST + GET) ──────────────────────────


def _unauthorized() -> JSONResponse:
    """Réponse 401 propre (clé invalide)."""
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
    handler ; renvoie la/les réponses JSON-RPC."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=_rpc_error(None, -32700, "JSON invalide (parse error)."),
        )

    async with AsyncSessionLocal() as db:
        user, scopes = await _context_from_key(db, api_key)
        if user is None:
            return _unauthorized()

        if isinstance(body, list):
            responses: list[dict[str, Any]] = []
            for msg in body:
                if not isinstance(msg, dict):
                    continue
                resp = await _handle_rpc(db, user, scopes, msg)
                if resp is not None:
                    responses.append(resp)
            if not responses:
                return JSONResponse(status_code=202, content=None)
            return JSONResponse(content=responses)

        if not isinstance(body, dict):
            return JSONResponse(
                status_code=400,
                content=_rpc_error(None, -32600, "Requête JSON-RPC invalide."),
            )

        resp = await _handle_rpc(db, user, scopes, body)
        if resp is None:
            return JSONResponse(status_code=202, content=None)
        return JSONResponse(content=resp)


@router.get("/{api_key}")
async def mcp_streamable_http_get(
    api_key: str = Path(..., description="Clé d'API krts_... scoping la session."),
) -> JSONResponse:
    """GET sur l'endpoint Streamable HTTP. Ce serveur est sans état et ne
    pousse rien : on répond 405 après avoir validé la clé (pas de fuite)."""
    async with AsyncSessionLocal() as db:
        user, _ = await _context_from_key(db, api_key)
        if user is None:
            return _unauthorized()
    return JSONResponse(
        status_code=405,
        content=_rpc_error(
            None, -32000, "Streaming SSE non supporté ; utilisez POST (JSON-RPC)."
        ),
        headers={"Allow": "POST"},
    )
