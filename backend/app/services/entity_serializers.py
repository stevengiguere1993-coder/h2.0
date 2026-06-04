"""Sérialiseurs d'entités métier — fondation réutilisable.

Objectif : transformer un objet ORM en ``dict`` JSON exposant les
**champs métier clés** (titre lisible, statut, montant, client/entité
liée, dates…) plutôt qu'un simple identifiant. Utilisé pour enrichir
l'activité (``GET /activity/me``) et, à terme, d'autres surfaces API /
MCP qui veulent renvoyer du contexte exploitable sans round-trip.

Principes :
  - **Défensif avant tout.** Chaque champ est lu via ``getattr(obj,
    "champ", None)`` — un modèle qui évolue (colonne renommée /
    supprimée) ne doit JAMAIS faire planter la sérialisation. On ne
    suppose l'existence d'aucun attribut.
  - **Deux niveaux.** ``level="summary"`` = champs essentiels pour les
    listes (activité). ``level="full"`` = vue détaillée (prévue pour
    plus tard ; remplie partiellement ici). ``summary`` est l'important.
  - **Registre.** ``serialize_entity(entity_type, obj, level)`` route
    vers le bon sérialiseur via ``SERIALIZERS``. Un type inconnu retourne
    un fallback minimal (id + type) plutôt qu'une exception.
  - **JSON-safe.** Les ``datetime`` sont rendus en ISO 8601 (str), les
    ``Decimal`` en ``float``, pour rester directement sérialisables par
    FastAPI / json sans encodeur custom.

Aucune I/O ici : ces fonctions opèrent sur des objets DÉJÀ chargés. Elles
ne déclenchent pas de requête (on lit des colonnes simples, pas des
relations paresseuses) pour rester sûres dans un contexte async.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Optional


# ── Helpers JSON-safe & lecture défensive ──────────────────────────


def _get(obj: Any, *names: str) -> Any:
    """Premier attribut non-None parmi ``names`` (lecture défensive).

    Permet de couvrir des modèles aux noms de champ divergents (ex.
    ``title`` vs ``name``) sans brancher partout. Retourne None si aucun
    n'existe / tous None."""
    for name in names:
        val = getattr(obj, name, None)
        if val is not None:
            return val
    return None


def _iso(value: Any) -> Optional[str]:
    """``datetime``/``date`` → chaîne ISO 8601, sinon None. Ne lève jamais."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        try:
            return value.isoformat()
        except Exception:
            return None
    # Déjà une chaîne (ou autre) : on renvoie tel quel si c'est du texte.
    if isinstance(value, str):
        return value
    return None


def _num(value: Any) -> Optional[float]:
    """``Decimal``/``int``/``float`` → ``float`` JSON-safe, sinon None."""
    if value is None:
        return None
    if isinstance(value, bool):  # un bool n'est pas un montant
        return None
    if isinstance(value, Decimal):
        try:
            return float(value)
        except Exception:
            return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _str(value: Any) -> Optional[str]:
    """Coerce en chaîne non vide, sinon None. Ne lève jamais."""
    if value is None:
        return None
    try:
        s = str(value).strip()
    except Exception:
        return None
    return s or None


# ── Sérialiseurs par entité ────────────────────────────────────────
#
# Signature uniforme : ``serialize_<entity>(obj, level="summary") -> dict``.
# Le dict ``summary`` porte toujours au minimum : ``entity_type``, ``id``,
# ``label`` (titre lisible), ``pole`` quand c'est pertinent. ``full``
# ajoute le détail.


def serialize_devlog_soumission(obj: Any, level: str = "summary") -> dict:
    """Soumission (devis) du pôle Développement logiciel.

    Champs métier : titre (= « numéro » lisible), client/lead cible,
    statut, montant. La soumission n'a pas de colonne ``numero`` dédiée :
    le ``title`` fait office d'identifiant humain. Le client n'étant pas
    une relation chargée par défaut, on expose les ids cibles + le nom du
    client/lead s'il a été préchargé (``client``/``lead``)."""
    data: dict[str, Any] = {
        "entity_type": "devlog_soumission",
        "id": getattr(obj, "id", None),
        "label": _str(_get(obj, "title")),
        "title": _str(_get(obj, "title")),
        "pole": "devlog",
        "status": _str(_get(obj, "status")),
        # Montant total (TTC tel que stocké) — colonne ``amount``.
        "amount": _num(_get(obj, "amount")),
        # Cibles : on expose les ids (toujours dispo) + le nom si la
        # relation a été préchargée (sinon None, jamais d'I/O ici).
        "client_id": _get(obj, "client_id"),
        "lead_id": _get(obj, "lead_id"),
        "client_name": _client_name(obj),
    }
    if level == "full":
        data.update(
            {
                "is_devis_dev": bool(getattr(obj, "is_devis_dev", False)),
                "summary": _str(_get(obj, "summary")),
                "sent_at": _iso(_get(obj, "sent_at")),
                "signed_at": _iso(_get(obj, "signed_at")),
                "signed_name": _str(_get(obj, "signed_name")),
                "created_at": _iso(_get(obj, "created_at")),
                "updated_at": _iso(_get(obj, "updated_at")),
            }
        )
    return _drop_none(data)


def _client_name(obj: Any) -> Optional[str]:
    """Nom du client/lead lié à une soumission, SI la relation est déjà
    chargée (best-effort, aucune I/O). On tente plusieurs attributs
    courants pour rester robuste aux variations de modèle."""
    for rel in ("client", "lead"):
        target = getattr(obj, rel, None)
        if target is not None:
            name = _get(target, "name", "full_name", "nom", "title", "email")
            if name is not None:
                return _str(name)
    return None


def _serialize_task_common(
    obj: Any,
    *,
    entity_type: str,
    pole: str,
    title_attrs: tuple[str, ...],
    status: Optional[str],
    is_completed: Optional[bool],
    assignee: Any,
    level: str,
) -> dict:
    """Tronc commun de sérialisation d'une tâche (les 5 modèles).

    Les modèles divergent sur le nom du champ titre (``title`` vs
    ``name``), la forme du statut (chaîne libre vs booléen ``done``) et
    l'assignation (user_id vs employe_id). L'appelant normalise ces
    différences et passe les valeurs déjà résolues."""
    data: dict[str, Any] = {
        "entity_type": entity_type,
        "id": getattr(obj, "id", None),
        "label": _str(_get(obj, *title_attrs)),
        "title": _str(_get(obj, *title_attrs)),
        "pole": pole,
        "status": _str(status),
        "is_completed": bool(is_completed) if is_completed is not None else None,
        "assignee": assignee,
        "due_date": _iso(_get(obj, "due_date")),
        "updated_at": _iso(_get(obj, "updated_at")),
    }
    if level == "full":
        data.update(
            {
                "description": _str(_get(obj, "description", "notes")),
                "priority": _str(_get(obj, "priority")),
                "created_at": _iso(_get(obj, "created_at")),
                "completed_at": _iso(_get(obj, "completed_at", "done_at")),
            }
        )
    return _drop_none(data)


def serialize_devlog_project_task(obj: Any, level: str = "summary") -> dict:
    """Tâche d'un projet de développement (pôle Développement logiciel).

    Statut chaîne (``a_faire``/``en_cours``/``termine``) ; complétée =
    statut ``termine``. Assignée via ``assignee_user_id``."""
    status = _str(_get(obj, "status"))
    return _serialize_task_common(
        obj,
        entity_type="devlog_project_task",
        pole="devlog",
        title_attrs=("title", "name"),
        status=status,
        is_completed=(status == "termine"),
        assignee=_assignee_user(obj),
        level=level,
    )


def serialize_entreprise_tache(obj: Any, level: str = "summary") -> dict:
    """Tâche du pôle Gestion d'entreprises.

    Statut chaîne (vocabulaire kanban) ; complétée = statut ``done``.
    Assignée via ``assignee_user_id``."""
    status = _str(_get(obj, "status"))
    return _serialize_task_common(
        obj,
        entity_type="entreprise_tache",
        pole="entreprise",
        title_attrs=("title", "name"),
        status=status,
        is_completed=(status == "done"),
        assignee=_assignee_user(obj),
        level=level,
    )


def serialize_prospection_deal_task(obj: Any, level: str = "summary") -> dict:
    """Tâche attachée à un deal du Pipeline Prospection.

    Le titre est porté par ``name`` (pas ``title``). Statut chaîne ;
    complétée = statut ``done``. Assignée via ``assignee_user_id``."""
    status = _str(_get(obj, "status"))
    return _serialize_task_common(
        obj,
        entity_type="prospection_deal_task",
        pole="prospection",
        title_attrs=("name", "title"),
        status=status,
        is_completed=(status == "done"),
        assignee=_assignee_user(obj),
        level=level,
    )


def serialize_sales_task(obj: Any, level: str = "summary") -> dict:
    """Tâche du CRM (ventes) — pôle Prospection côté API.

    Cycle de vie booléen : ``done``/``done_at`` (pas de statut chaîne).
    On dérive un statut lisible. Assignée à des employés (M2M) — on ne
    déréférence pas la relation ici (best-effort, sans I/O)."""
    done = bool(getattr(obj, "done", False))
    return _serialize_task_common(
        obj,
        entity_type="sales_task",
        pole="prospection",
        title_attrs=("title", "name"),
        status="done" if done else "open",
        is_completed=done,
        assignee=None,
        level=level,
    )


def serialize_project_task(obj: Any, level: str = "summary") -> dict:
    """Tâche d'un chantier (pôle Construction).

    Cycle de vie booléen : ``done``/``done_at``. Assignée à un employé
    via ``assignee_id`` (id seulement ; le nom requiert une jointure
    qu'on ne fait pas ici)."""
    done = bool(getattr(obj, "done", False))
    data = _serialize_task_common(
        obj,
        entity_type="project_task",
        pole="construction",
        title_attrs=("title", "name"),
        status="done" if done else "open",
        is_completed=done,
        assignee=None,
        level=level,
    )
    # Id d'employé assigné (sans résoudre le nom — pas d'I/O).
    emp_id = _get(obj, "assignee_id")
    if emp_id is not None:
        data["assignee_employe_id"] = emp_id
    return data


def _assignee_user(obj: Any) -> Optional[dict]:
    """Représentation minimale de l'assigné quand c'est un ``User`` lié
    par ``assignee_user_id``. On expose l'id systématiquement ; le nom /
    courriel seulement si la relation ``assignee`` a été préchargée."""
    uid = _get(obj, "assignee_user_id")
    if uid is None:
        return None
    out: dict[str, Any] = {"user_id": uid}
    target = getattr(obj, "assignee", None)
    if target is not None:
        name = _get(target, "full_name", "name", "email")
        if name is not None:
            out["name"] = _str(name)
    return out


def serialize_prospection_deal(obj: Any, level: str = "summary") -> dict:
    """Deal du Pipeline Prospection (opportunité sur un immeuble).

    Le modèle est volontairement minimal : adresse (sert de label),
    priorité (= étape pipeline), position. Des valeurs « riches » (prix,
    nombre de logements) vivent dans la fiche d'analyse liée
    (``lead_analysis``) — on les expose si la relation est préchargée,
    de façon best-effort et sans I/O."""
    data: dict[str, Any] = {
        "entity_type": "prospection_deal",
        "id": getattr(obj, "id", None),
        "label": _str(_get(obj, "address")),
        "address": _str(_get(obj, "address")),
        "pole": "prospection",
        # Le pipeline n'a pas de colonne « stage » : la priorité joue ce
        # rôle d'étape (urgent → ... → termine / abandonne).
        "status": _str(_get(obj, "priority")),
        "priority": _str(_get(obj, "priority")),
    }
    # Valeurs clés issues de l'analyse liée, si préchargée.
    analysis = getattr(obj, "lead_analysis", None)
    if analysis is not None:
        price = _num(
            _get(analysis, "asking_price", "price", "prix", "purchase_price")
        )
        units = _get(analysis, "num_units", "nb_logements", "units", "nb_units")
        if price is not None:
            data["price"] = price
        if units is not None:
            data["units"] = units
    if level == "full":
        data.update(
            {
                "drive_folder_url": _str(_get(obj, "drive_folder_url")),
                "lead_analysis_id": _get(obj, "lead_analysis_id"),
                "created_at": _iso(_get(obj, "created_at")),
                "updated_at": _iso(_get(obj, "updated_at")),
            }
        )
    return _drop_none(data)


def serialize_entreprise(obj: Any, level: str = "summary") -> dict:
    """Entreprise (entité d'affaire du pôle Gestion d'entreprises).

    Champs métier : nom (label), type/catégorie, NEQ. Le « contact
    principal » n'est pas une colonne directe (les partenaires vivent
    dans ``EntreprisePartner``) — on l'expose si une relation
    ``partners`` est préchargée, best-effort."""
    data: dict[str, Any] = {
        "entity_type": "entreprise",
        "id": getattr(obj, "id", None),
        "label": _str(_get(obj, "name")),
        "name": _str(_get(obj, "name")),
        "pole": "entreprise",
        "type": _str(_get(obj, "type")),
        "neq": _str(_get(obj, "neq")),
    }
    contact = _primary_contact(obj)
    if contact is not None:
        data["primary_contact"] = contact
    if level == "full":
        data.update(
            {
                "description": _str(_get(obj, "description")),
                "is_active": bool(getattr(obj, "is_active", True)),
                "is_parent_company": bool(
                    getattr(obj, "is_parent_company", False)
                ),
                "drive_folder_url": _str(_get(obj, "drive_folder_url")),
                "created_at": _iso(_get(obj, "created_at")),
                "updated_at": _iso(_get(obj, "updated_at")),
            }
        )
    return _drop_none(data)


def _primary_contact(obj: Any) -> Optional[dict]:
    """Contact principal d'une entreprise, SI ``partners`` est préchargé.
    On prend le premier partenaire nommé (best-effort, sans I/O)."""
    partners = getattr(obj, "partners", None)
    if not partners:
        return None
    try:
        first = partners[0]
    except (TypeError, IndexError):
        return None
    name = _get(first, "partner_name", "full_name", "name")
    email = _get(first, "partner_email", "email")
    if name is None and email is None:
        return None
    out: dict[str, Any] = {}
    if name is not None:
        out["name"] = _str(name)
    if email is not None:
        out["email"] = _str(email)
    role = _get(first, "role")
    if role is not None:
        out["role"] = _str(role)
    return out or None


# ── Registre + façade ──────────────────────────────────────────────


def _drop_none(data: dict) -> dict:
    """Retire les clés à valeur None pour alléger la charge utile, tout
    en GARDANT toujours ``entity_type`` et ``id`` (identité de l'objet)."""
    keep = {"entity_type", "id"}
    return {k: v for k, v in data.items() if v is not None or k in keep}


#: Registre ``entity_type`` → fonction de sérialisation. Les clés
#: correspondent aux ``entity_type`` déjà utilisés par l'endpoint
#: d'activité (``devlog_project_task``, ``entreprise_tache``, …) pour un
#: branchement direct, plus les entités métier de plus haut niveau.
SERIALIZERS: dict[str, Callable[..., dict]] = {
    "devlog_soumission": serialize_devlog_soumission,
    "devlog_project_task": serialize_devlog_project_task,
    "entreprise_tache": serialize_entreprise_tache,
    "prospection_deal_task": serialize_prospection_deal_task,
    "sales_task": serialize_sales_task,
    "project_task": serialize_project_task,
    "prospection_deal": serialize_prospection_deal,
    "entreprise": serialize_entreprise,
}


def serialize_entity(
    entity_type: str,
    obj: Any,
    level: str = "summary",
) -> dict:
    """Façade : sérialise ``obj`` selon son ``entity_type`` via le
    registre. Type inconnu / objet None → fallback minimal (jamais une
    exception). C'est le point d'entrée recommandé pour les appelants
    qui veulent enrichir un item d'activité.

    Ne lève jamais : un sérialiseur qui planterait (modèle inattendu)
    retombe sur le fallback identité, pour ne JAMAIS casser la réponse
    d'activité dont c'est un simple enrichissement."""
    if obj is None:
        return {"entity_type": entity_type, "id": None}
    fn = SERIALIZERS.get(entity_type)
    if fn is None:
        return {"entity_type": entity_type, "id": getattr(obj, "id", None)}
    try:
        return fn(obj, level=level)
    except Exception:
        # Enrichissement best-effort : on ne casse jamais l'appelant.
        return {"entity_type": entity_type, "id": getattr(obj, "id", None)}
