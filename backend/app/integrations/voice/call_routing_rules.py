"""Règles d'acheminement des appels — logique PURE (bug 19, 2026-10-18).

Steven : « une personne qui peut être appelée doit pouvoir mettre ses
heures d'appel personnelles » et « pouvoir mettre plusieurs appelants
possibles : un client appelle pour un suivi du projet xyz → ça appelle
le responsable du chantier ».

Ce module ne touche pas à la base : il décrit les sujets d'appel, les
sortes de cibles, valide la liste ordonnée de cibles d'une règle,
choisit la règle applicable et découpe les destinations en ÉTAPES de
sonnerie. La résolution des cibles dynamiques (responsable du chantier
du moment, membres du projet, contact d'urgence de l'immeuble) et la
prise en compte des heures personnelles se font dans
``api/v1/endpoints/voice.py`` (``_resolve_rule_plan``), qui a accès à la
base et aux helpers existants.

Déroulé à l'appel (``_rule_transfer_twiml``) :

1. sujet déduit de la décision de Léa (ou du chemin direct) ;
2. règle du CHANTIER si l'appelant est rattaché à un projet qui en a
   une, sinon règle GÉNÉRALE du sujet, sinon routage historique ;
3. chaque cible est résolue en destinations (numéro mobile, et le
   navigateur « client:user_N » si la personne est en ligne), les
   personnes hors de leurs heures d'appel sont sautées si la règle
   respecte les heures ;
4. ``cascade`` : une étape par cible, dans l'ordre (chacune
   ``step_timeout_sec`` secondes, musique d'attente pour l'appelant) ;
   ``simultane`` : une seule étape avec tout le monde ;
5. personne ne décroche → boîte vocale + lead de rappel (flux existant).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

#: Sujets d'appel : (clé, libellé, explication affichée dans l'interface).
SUBJECTS: tuple[tuple[str, str, str], ...] = (
    (
        "suivi_projet",
        "Suivi de chantier",
        "Client existant qui appelle pour son projet (avancement, question, "
        "garantie) ou qui demande à parler à quelqu'un. Une règle par chantier "
        "prime sur la règle générale.",
    ),
    (
        "nouveau_client",
        "Nouveau client / soumission",
        "Prospect ou appelant inconnu qui veut parler à quelqu'un (remplace "
        "les « numéros closers » de la ligne).",
    ),
    (
        "urgence_locataire",
        "Urgence locataire",
        "Dégât d'eau, panne de chauffage, etc. Décocher « respecter les heures "
        "personnelles » pour qu'une urgence sonne aussi la nuit.",
    ),
    (
        "demande_locataire",
        "Demande de locataire",
        "Demande non urgente d'un locataire (réparation, question de bail).",
    ),
    (
        "general",
        "Autre appel",
        "Tout autre transfert : appelant connu sans chantier, transfert direct "
        "quand la secrétaire est désactivée.",
    ),
)
SUBJECT_KEYS: tuple[str, ...] = tuple(s[0] for s in SUBJECTS)
SUBJECT_LABELS: Dict[str, str] = {s[0]: s[1] for s in SUBJECTS}

#: Sortes de cibles : (clé, libellé, explication).
TARGET_KINDS: tuple[tuple[str, str, str], ...] = (
    (
        "project_responsible",
        "Responsable du chantier",
        "Le responsable désigné du projet de l'appelant, au moment de l'appel.",
    ),
    (
        "project_members",
        "Membres du projet",
        "Tous les membres actifs du projet de l'appelant (sonnés ensemble).",
    ),
    (
        "user",
        "Un utilisateur précis",
        "Une personne de l'équipe (son mobile, et son navigateur si elle est "
        "en ligne dans le portail).",
    ),
    (
        "immeuble_urgence",
        "Contact d'urgence de l'immeuble",
        "Le contact d'urgence de l'immeuble du locataire qui appelle.",
    ),
    (
        "line_default",
        "Numéros par défaut de la ligne",
        "Les numéros configurés sur la ligne pour ce sujet (suivi, closers, "
        "urgences ou transfert par défaut).",
    ),
    (
        "e164",
        "Numéro externe",
        "Un numéro de téléphone (bureau, réception, sous-traitant…).",
    ),
)
TARGET_KIND_KEYS: tuple[str, ...] = tuple(t[0] for t in TARGET_KINDS)
TARGET_KIND_LABELS: Dict[str, str] = {t[0]: t[1] for t in TARGET_KINDS}

MODES: tuple[str, ...] = ("cascade", "simultane")

#: Bornes du délai de sonnerie par étape (secondes) et nombre maximal
#: d'étapes d'une cascade (au-delà, l'appelant patiente trop longtemps).
MIN_STEP_TIMEOUT_SEC = 10
MAX_STEP_TIMEOUT_SEC = 45
DEFAULT_STEP_TIMEOUT_SEC = 20
MAX_STEPS = 6
MAX_TARGETS = 12

_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def normalize_e164(raw: Optional[str]) -> Optional[str]:
    """Numéro saisi librement → E.164 (``+1…``), ou None si invalide.
    10 chiffres nord-américains → ``+1`` ajouté ; 11 chiffres commençant
    par 1 → ``+`` ajouté."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    if str(raw).strip().startswith("+"):
        cand = "+" + digits
    elif len(digits) == 10:
        cand = "+1" + digits
    elif len(digits) == 11 and digits.startswith("1"):
        cand = "+" + digits
    else:
        cand = "+" + digits
    return cand if _E164_RE.match(cand) else None


def normalize_targets(raw: Any) -> List[Dict[str, Any]]:
    """Valide et normalise la liste ordonnée de cibles d'une règle.

    Accepte une liste de dicts (ou une chaîne JSON). Lève ``ValueError``
    avec un message en français prêt à afficher. Les doublons exacts sont
    retirés en gardant la première position.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError as exc:
            raise ValueError("Liste de cibles illisible.") from exc
    if raw is None:
        raw = []
    if not isinstance(raw, (list, tuple)):
        raise ValueError("La liste de cibles doit être une liste.")
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for pos, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Cible {pos} : format invalide.")
        kind = str(item.get("kind") or "").strip()
        if kind not in TARGET_KIND_KEYS:
            raise ValueError(f"Cible {pos} : sorte inconnue « {kind} ».")
        norm: Dict[str, Any] = {"kind": kind}
        if kind == "user":
            try:
                uid = int(item.get("user_id") or 0)
            except (TypeError, ValueError):
                uid = 0
            if uid <= 0:
                raise ValueError(f"Cible {pos} : choisir un utilisateur.")
            norm["user_id"] = uid
        elif kind == "e164":
            e164 = normalize_e164(item.get("e164"))
            if not e164:
                raise ValueError(
                    f"Cible {pos} : numéro invalide (format attendu +1 514 555 0199)."
                )
            norm["e164"] = e164
        label = item.get("label")
        if label is not None:
            label = str(label).strip()[:120]
            if label:
                norm["label"] = label
        key = (kind, norm.get("user_id"), norm.get("e164"))
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    if len(out) > MAX_TARGETS:
        raise ValueError(f"Au plus {MAX_TARGETS} cibles par règle.")
    return out


def dumps_targets(targets: Sequence[Dict[str, Any]]) -> str:
    return json.dumps(list(targets), ensure_ascii=False)


def loads_targets(raw: Optional[str]) -> List[Dict[str, Any]]:
    """Lecture tolérante du JSON stocké (jamais d'exception : une règle
    corrompue se comporte comme une règle sans cible)."""
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict) and d.get("kind") in TARGET_KIND_KEYS]


def clamp_step_timeout(value: Any) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = DEFAULT_STEP_TIMEOUT_SEC
    return max(MIN_STEP_TIMEOUT_SEC, min(MAX_STEP_TIMEOUT_SEC, v))


def select_rule(rules: Iterable[Any], *, project_id: Optional[int]) -> Optional[Any]:
    """Choisit la règle applicable parmi des règles DÉJÀ filtrées par
    sujet, ligne et ``active``.

    Une règle réservée au chantier de l'appelant prime sur une règle
    générale ; à portée égale, ``priority`` décroissante puis id croissant
    (la plus ancienne gagne). Une règle réservée à un AUTRE chantier n'est
    jamais prise."""
    specific: List[Any] = []
    general: List[Any] = []
    for r in rules or []:
        if not getattr(r, "active", True):
            continue
        rp = getattr(r, "project_id", None)
        if rp is None:
            general.append(r)
        elif project_id is not None and int(rp) == int(project_id):
            specific.append(r)

    def _key(r: Any):
        return (-int(getattr(r, "priority", 0) or 0), int(getattr(r, "id", 0) or 0))

    for bucket in (specific, general):
        if bucket:
            return sorted(bucket, key=_key)[0]
    return None


@dataclass
class PlannedTarget:
    """Une cible de la règle, résolue au moment de l'appel."""

    kind: str
    label: str
    destinations: List[str] = field(default_factory=list)
    user_id: Optional[int] = None
    #: Motif pour lequel la cible ne sonnera pas (hors heures, sans
    #: téléphone, aucun responsable…) — None si elle sonne.
    skipped: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "destinations": list(self.destinations),
            "user_id": self.user_id,
            "skipped": self.skipped,
        }


@dataclass
class RoutingPlan:
    """Résultat de la résolution d'une règle : qui sonne, dans quel ordre."""

    rule_id: Optional[int]
    mode: str
    step_timeout_sec: int
    targets: List[PlannedTarget] = field(default_factory=list)

    @property
    def steps(self) -> List[List[str]]:
        groups = [t.destinations for t in self.targets if t.destinations and not t.skipped]
        return build_steps(groups, self.mode)

    @property
    def flat(self) -> List[str]:
        out: List[str] = []
        for step in self.steps:
            for d in step:
                if d not in out:
                    out.append(d)
        return out

    @property
    def pstn(self) -> List[str]:
        """Numéros de téléphone seulement (sans les navigateurs)."""
        return [d for d in self.flat if not d.startswith("client:")]

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "mode": self.mode,
            "step_timeout_sec": self.step_timeout_sec,
            "targets": [t.as_dict() for t in self.targets],
            "steps": self.steps,
        }


def build_steps(groups: Sequence[Sequence[str]], mode: str) -> List[List[str]]:
    """Découpe les destinations en étapes de sonnerie.

    - ``cascade`` : une étape par groupe non vide, dans l'ordre ;
    - ``simultane`` : une seule étape avec toutes les destinations.
    Une destination déjà sonnée à une étape précédente n'est pas resonnée
    plus tard. Plafond ``MAX_STEPS`` étapes (les suivantes sont fusionnées
    dans la dernière pour ne perdre personne)."""
    seen: set = set()
    steps: List[List[str]] = []
    for group in groups or []:
        step: List[str] = []
        for d in group or []:
            d = (d or "").strip()
            if not d or d in seen:
                continue
            seen.add(d)
            step.append(d)
        if step:
            steps.append(step)
    if not steps:
        return []
    if mode != "cascade":
        return [[d for step in steps for d in step]]
    if len(steps) > MAX_STEPS:
        head, tail = steps[: MAX_STEPS - 1], steps[MAX_STEPS - 1 :]
        head.append([d for step in tail for d in step])
        steps = head
    return steps


def fit_forwarded(destinations: Sequence[str], max_len: int = 20) -> Optional[str]:
    """Valeur à écrire dans ``Call.forwarded_to_e164`` (VARCHAR(20)) :
    la liste jointe si elle tient, sinon le premier numéro de téléphone
    (les navigateurs « client:user_N » passent en dernier)."""
    dests = [d for d in destinations if d]
    if not dests:
        return None
    joined = ",".join(dests)
    if len(joined) <= max_len:
        return joined
    for d in dests:
        if not d.startswith("client:") and len(d) <= max_len:
            return d
    return dests[0][:max_len]


def line_default_field(subject: str) -> str:
    """Champ du PhoneNumber qui porte les numéros par défaut du sujet."""
    return {
        "suivi_projet": "followup_forward_e164",
        "nouveau_client": "closer_forward_e164",
        "urgence_locataire": "urgency_forward_e164",
        "demande_locataire": "urgency_forward_e164",
    }.get(subject, "forward_to_e164")
