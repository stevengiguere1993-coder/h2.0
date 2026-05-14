"""Kratos — suggère les rôles / tâches manquants d'une entreprise.

Sur un nœud `company` de l'organigramme, le bouton « Générer » appelle
ce service : il lit le but de l'entreprise (nom, type, description) et
ce qui est DÉJÀ couvert dans son sous-arbre, puis demande à l'IA
d'identifier les trous (rôles, départements, tâches, services
manquants).

Renvoie une liste de suggestions ``{label, kind, description}`` — non
persistées : l'utilisateur choisit lesquelles ajouter, une par une,
via l'endpoint de création de nœud classique.

Fallback heuristique local (par type d'entreprise) si l'IA est
indisponible — Kratos continue de proposer une structure de base.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entreprise import Entreprise
from app.models.org_node import OrgNode


log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
VALID_KINDS = {"dept", "role", "service", "task"}
VALID_TIERS = {"direction", "adjoint", "adjoint_virtuel"}


SYSTEM_PROMPT = """Tu es Kratos, l'architecte organisationnel d'un \
dirigeant qui gère plusieurs entreprises (immobilier, construction, \
gestion, prospection, développement). On te donne le BUT d'une \
entreprise et la liste des rôles / départements / tâches DÉJÀ couverts \
dans son organigramme. Tu identifies ce qui MANQUE pour que \
l'entreprise fonctionne réellement et atteigne son but.

Tu réponds UNIQUEMENT en JSON strict :
{
  "suggestions": [
    {
      "label": "Nom du rôle / département / tâche (max 80 caractères)",
      "kind": "dept" | "role" | "service" | "task",
      "description": "Pourquoi c'est nécessaire et ce que ça couvre (1-2 phrases)",
      "execution_tier": "direction" | "adjoint" | "adjoint_virtuel"
    }
  ]
}

Règles :
- 5 à 10 suggestions, classées de la plus critique à la moins critique.
- Ne répète JAMAIS un rôle/tâche déjà couvert (compare aux libellés \
fournis, même approximativement).
- Reste concret et adapté au but de CETTE entreprise précise — pas de \
rôles génériques creux.
- kind="dept" pour une grande fonction, "role" pour un poste, "task" \
pour une action concrète, "service" pour un service partagé/transverse.
- execution_tier : QUI doit prendre ça en charge.
  * "direction" — relève du dirigeant : stratégie, décisions, \
négociations clés, relations bancaires/partenaires. Non délégable.
  * "adjoint" — délégable à un adjoint humain : coordination, suivi, \
exécution qui demande du jugement ou du contact humain.
  * "adjoint_virtuel" — automatisable ou délégable à un adjoint \
virtuel (IA, outils) : saisie, relances, rapports, screening, \
tâches répétitives et procédurales.
- Chaque suggestion doit combler un vrai trou opérationnel ou \
stratégique."""


# Canevas de secours par type d'entreprise (fallback sans IA).
# Tuple : (label, kind, description, execution_tier).
_CANEVAS: dict[str, list[tuple[str, str, str, str]]] = {
    "immobilier": [
        ("Gestion locative", "dept",
         "Baux, renouvellements, communication avec les locataires.",
         "adjoint"),
        ("Réception des loyers", "role",
         "Encaissement, relances, suivi des retards de paiement.",
         "adjoint_virtuel"),
        ("Maintenance & réparations", "role",
         "Bons de travail, suivi des bris, coordination des fournisseurs.",
         "adjoint"),
        ("Comptabilité immeuble", "service",
         "Tenue de livres, taxes et états financiers par immeuble.",
         "adjoint_virtuel"),
        ("Acquisition", "role",
         "Analyse de leads, montage financier, négociation d'achat.",
         "direction"),
        ("Financement & refinancement", "task",
         "Suivi des hypothèques, dates de terme, marges de crédit.",
         "direction"),
        ("Assurances & conformité", "task",
         "Polices à jour, conformité municipale et réglementaire.",
         "adjoint"),
    ],
    "construction": [
        ("Estimation / soumissions", "role",
         "Chiffrage, rédaction des soumissions, suivi du taux d'acceptation.",
         "direction"),
        ("Chargé de projet", "role",
         "Planification de chantier, échéancier, coordination des équipes.",
         "adjoint"),
        ("Approvisionnement", "role",
         "Bons d'achat, relation fournisseurs, gestion des matériaux.",
         "adjoint"),
        ("Sous-traitants", "role",
         "Sélection, contrats et évaluation des sous-traitants.",
         "direction"),
        ("Facturation & paiements", "service",
         "Factures clients, comptes à recevoir et à payer.",
         "adjoint_virtuel"),
        ("Santé-sécurité (CNESST)", "task",
         "Conformité chantier, prévention et formation.",
         "adjoint"),
        ("Service après-vente", "task",
         "Suivi des déficiences et des garanties.",
         "adjoint"),
    ],
    "gestion": [
        ("Comptabilité", "service",
         "Tenue de livres, taxes, comptes payables et recevables.",
         "adjoint_virtuel"),
        ("Ressources humaines", "role",
         "Embauche, paie, congés et dossiers employés.",
         "adjoint"),
        ("Direction / stratégie", "role",
         "Vision, objectifs trimestriels et suivi des indicateurs.",
         "direction"),
        ("Juridique & conformité", "task",
         "Statuts, conventions d'actionnaires, contrats et assurances.",
         "direction"),
        ("Marketing & développement", "role",
         "Acquisition de clients et image de marque.",
         "adjoint"),
        ("Administration", "task",
         "Gestion documentaire, classement et fournisseurs internes.",
         "adjoint_virtuel"),
    ],
}
_DEFAULT_CANEVAS = _CANEVAS["gestion"]


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    for a, b in (
        ("é", "e"), ("è", "e"), ("ê", "e"), ("ë", "e"),
        ("à", "a"), ("â", "a"), ("ô", "o"), ("î", "i"),
        ("ï", "i"), ("ç", "c"), ("û", "u"), ("ù", "u"),
    ):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _collect_descendants(
    all_nodes: list[OrgNode], root_id: int
) -> list[OrgNode]:
    children_of: dict[Optional[int], list[OrgNode]] = {}
    for n in all_nodes:
        children_of.setdefault(n.parent_id, []).append(n)
    out: list[OrgNode] = []
    stack = list(children_of.get(root_id, []))
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(children_of.get(cur.id, []))
    return out


def _call_claude(
    label: str,
    ent: Optional[Entreprise],
    existing: list[OrgNode],
) -> list[dict]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY non configuré.")
    import anthropic

    name = ent.name if ent else label
    ent_type = (ent.type if ent else None) or "non précisé"
    description = (ent.description if ent else None) or "(aucune description)"
    covered = (
        "\n".join(f"- [{n.kind}] {n.label}" for n in existing[:80])
        or "(rien de couvert pour l'instant)"
    )
    user_prompt = (
        f"## Entreprise\n{name}\n"
        f"Type : {ent_type}\n"
        f"But / description : {description}\n\n"
        f"## Déjà couvert dans l'organigramme ({len(existing)} éléments)\n"
        f"{covered}\n\n"
        "## Demande\nIdentifie les rôles / départements / tâches "
        "MANQUANTS selon le schéma JSON."
    )
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = "\n".join(
        b.text for b in msg.content if b.type == "text"
    ).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    parsed = json.loads(raw)
    return list(parsed.get("suggestions") or [])


def _suggest_locally(
    ent: Optional[Entreprise], existing: list[OrgNode]
) -> list[dict]:
    ent_type = (ent.type if ent else "gestion") or "gestion"
    canevas = _CANEVAS.get(ent_type, _DEFAULT_CANEVAS)
    covered = {_norm(n.label) for n in existing}
    out: list[dict] = []
    for label, kind, desc, tier in canevas:
        if _norm(label) in covered:
            continue
        out.append(
            {
                "label": label,
                "kind": kind,
                "description": desc,
                "execution_tier": tier,
            }
        )
    return out


async def suggest_roles(db: AsyncSession, node_id: int) -> list[dict]:
    """Génère les suggestions de rôles/tâches manquants pour le nœud
    `node_id` (idéalement un nœud `company`). Ne persiste rien."""
    all_nodes = list(
        (await db.execute(select(OrgNode))).scalars().all()
    )
    by_id = {n.id: n for n in all_nodes}
    node = by_id.get(node_id)
    if node is None:
        raise ValueError("Nœud introuvable.")

    ent: Optional[Entreprise] = None
    if node.entreprise_id is not None:
        ent = (
            await db.execute(
                select(Entreprise).where(
                    Entreprise.id == node.entreprise_id
                )
            )
        ).scalar_one_or_none()

    existing = _collect_descendants(all_nodes, node_id)

    try:
        raw = _call_claude(node.label, ent, existing)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Suggestion de rôles → fallback local pour le nœud %s : %s",
            node_id,
            exc,
        )
        raw = _suggest_locally(ent, existing)

    # Validation + dédoublonnage contre ce qui existe déjà.
    covered = {_norm(n.label) for n in existing}
    seen: set[str] = set()
    out: list[dict] = []
    for s in raw:
        label = str(s.get("label") or "").strip()[:255]
        if not label:
            continue
        key = _norm(label)
        if key in covered or key in seen:
            continue
        seen.add(key)
        kind = str(s.get("kind") or "role").strip().lower()
        if kind not in VALID_KINDS:
            kind = "role"
        tier = str(s.get("execution_tier") or "").strip().lower()
        if tier not in VALID_TIERS:
            tier = None
        out.append(
            {
                "label": label,
                "kind": kind,
                "description": (
                    str(s.get("description") or "").strip()[:600] or None
                ),
                "execution_tier": tier,
            }
        )
    return out[:10]
