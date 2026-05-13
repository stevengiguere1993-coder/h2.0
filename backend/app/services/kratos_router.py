"""Kratos — service de routage d'intentions.

Reçoit un texte libre dicté/collé/tapé par l'utilisateur, le passe à
Claude pour en extraire une intention structurée (kind + entité cible
+ résumé + action proposée), puis applique le routage en créant
l'objet cible (tâche d'entreprise, note sur un lead, etc.).

Étapes :
  1. Construit un contexte minimal des entités du moment (liste des
     entreprises actives + leurs ids, leads récents, etc.) → permet à
     Claude de matcher « 9417-1287 » sur l'entreprise réelle.
  2. Appelle Claude avec le texte + le contexte + un schéma JSON.
  3. Parse la réponse.
  4. Si confidence élevée → exécute le routage et enregistre status="routed".
     Sinon → status="needs_review", l'UI propose la confirmation manuelle.

Intents supportés en Phase 1 :
  - entreprise_task       → crée un EntrepriseTache
  - lead_note             → ajoute aux notes d'une LeadAnalysis
  - prospection_lead_note → ajoute aux notes d'un ProspectionLead
  - note                  → stocke uniquement dans l'inbox Kratos
  - unknown               → idem note mais marqué needs_review

Phase 2+ ajoutera tenant_followup, project_note, calendar_event, etc.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entreprise import Entreprise
from app.models.entreprise_tache import EntrepriseTache, TacheStatus
from app.models.kratos_message import (
    KratosIntentKind,
    KratosMessage,
    KratosMessageStatus,
)
from app.models.lead_analysis import LeadAnalysis
from app.models.prospection_lead import ProspectionLead
from app.models.user import User


log = logging.getLogger(__name__)


KRATOS_MODEL = "claude-sonnet-4-6"


SYSTEM_PROMPT = """Tu es Kratos, le cerveau-secrétaire virtuel d'un \
dirigeant qui gère plusieurs entreprises (gestion locative + courtage \
immobilier + construction). L'utilisateur te dicte/tape/colle des \
notes, suivis, courriels, idées. Tu reconnais l'intention et tu \
extrais une structure JSON pour router l'entrée vers le bon endroit.

Tu réponds UNIQUEMENT en JSON strict, sans texte avant ni après, \
sans markdown.

Schéma de sortie :
{
  "kind": "entreprise_task" | "lead_note" | "prospection_lead_note" | "note" | "unknown",
  "summary": "résumé court (max 200 caractères) de l'entrée — pour un courriel, résume la réponse",
  "title": "titre court si c'est une tâche (max 120 car), sinon null",
  "entreprise_id": id numérique de l'entreprise mentionnée (parmi la liste fournie), ou null,
  "lead_analysis_id": id numérique de la LeadAnalysis mentionnée, ou null,
  "prospection_lead_id": id numérique du ProspectionLead mentionné, ou null,
  "confidence": "high" | "medium" | "low",
  "reason": "phrase courte expliquant le choix"
}

Règles :
- Si le texte ressemble à un COURRIEL reçu (entête From: / De: / Subject: / Objet:, ou si le \
contexte « Indices courriel détectés » ci-dessous est fourni), il s'agit d'une réponse à un \
suivi : route obligatoirement vers lead_note ou prospection_lead_note quand un candidat \
est suggéré (lead trouvé par email/téléphone/adresse). Si plusieurs candidats, choisis le \
plus probable avec confidence=medium et explique dans reason.
- Si le texte parle d'un suivi/relance/note sur un lead immobilier \
existant dans la liste, kind=lead_note ou prospection_lead_note.
- Si le texte décrit une action à faire / problème à régler / chose \
à vérifier pour une entreprise, kind=entreprise_task avec un titre.
- Si l'intention n'est pas claire ou que rien ne matche, kind=note ou \
unknown avec confidence=low.
- confidence=low quand le mapping vers entreprise/lead est incertain — \
l'UI demandera confirmation à l'utilisateur."""


@dataclass
class RoutingContext:
    """Contexte injecté dans le prompt pour aider Claude à matcher."""

    entreprises: list[Entreprise]
    leads: list[LeadAnalysis]
    prospection_leads: list[ProspectionLead]


@dataclass
class RoutingResult:
    """Résultat du routage. Toujours créé même si l'IA échoue (status
    needs_review). Le caller persiste le KratosMessage et applique
    l'action si pertinent."""

    kind: str
    summary: str
    title: Optional[str]
    entreprise_id: Optional[int]
    lead_analysis_id: Optional[int]
    prospection_lead_id: Optional[int]
    confidence: str
    reason: str
    raw_json: dict


EMAIL_HEADER_RE = re.compile(
    r"^\s*(?:From|De|Sender|Expéditeur)\s*:\s*", re.I | re.M
)
EMAIL_SUBJECT_RE = re.compile(
    r"^\s*(?:Subject|Objet)\s*:\s*(.+)$", re.I | re.M
)
EMAIL_ADDRESS_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)
PHONE_RE = re.compile(
    r"(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}"
)


def _detect_email_signals(text: str) -> dict:
    """Détecte si le texte ressemble à un courriel reçu/transféré.

    Retourne un dict avec :
      - is_email : bool (true si entête From/De: présent)
      - emails   : list[str] (toutes les adresses détectées)
      - phones   : list[str] (numéros normalisés à 10 chiffres)
      - subject  : str | None (extrait du Subject/Objet si présent)
    """
    is_email = bool(EMAIL_HEADER_RE.search(text))
    emails_raw = EMAIL_ADDRESS_RE.findall(text)
    # Dédoublonne + normalise lowercase.
    seen: list[str] = []
    for e in emails_raw:
        el = e.lower().strip()
        if el not in seen:
            seen.append(el)
    phones_raw = PHONE_RE.findall(text)
    phones_norm: list[str] = []
    for p in phones_raw:
        digits = re.sub(r"\D", "", p)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10 and digits not in phones_norm:
            phones_norm.append(digits)
    subj_m = EMAIL_SUBJECT_RE.search(text)
    subject = subj_m.group(1).strip()[:200] if subj_m else None
    return {
        "is_email": is_email or (len(seen) > 0 and len(text) > 200),
        "emails": seen[:5],
        "phones": phones_norm[:5],
        "subject": subject,
    }


async def _match_leads_by_contact(
    db: AsyncSession, emails: list[str], phones: list[str]
) -> tuple[list[LeadAnalysis], list[ProspectionLead]]:
    """Cherche les leads dont les coordonnées matchent (email ou
    téléphone). Permet de pointer Claude vers le bon candidat plutôt
    que de lui filer la liste complète."""
    leads_hits: list[LeadAnalysis] = []
    pleads_hits: list[ProspectionLead] = []

    if emails:
        from sqlalchemy import or_

        # LeadAnalysis.courtier_contact est un texte libre — on cherche
        # par "contains" sur chaque email.
        for e in emails:
            rows = (
                await db.execute(
                    select(LeadAnalysis).where(
                        LeadAnalysis.courtier_contact.ilike(f"%{e}%")
                    )
                )
            ).scalars().all()
            for r in rows:
                if r not in leads_hits:
                    leads_hits.append(r)
            # ProspectionLead a owner_email dédié.
            rows2 = (
                await db.execute(
                    select(ProspectionLead).where(
                        ProspectionLead.owner_email.ilike(e)
                    )
                )
            ).scalars().all()
            for r in rows2:
                if r not in pleads_hits:
                    pleads_hits.append(r)

    if phones:
        for p in phones:
            # On cherche les 7 derniers chiffres pour tolérer les
            # formats (514) 555-1234 / 5145551234 / 514.555.1234.
            tail = p[-7:]
            rows = (
                await db.execute(
                    select(LeadAnalysis).where(
                        LeadAnalysis.courtier_contact.ilike(f"%{tail}%")
                    )
                )
            ).scalars().all()
            for r in rows:
                if r not in leads_hits:
                    leads_hits.append(r)
            rows2 = (
                await db.execute(
                    select(ProspectionLead).where(
                        ProspectionLead.owner_phone.ilike(f"%{tail}%")
                    )
                )
            ).scalars().all()
            for r in rows2:
                if r not in pleads_hits:
                    pleads_hits.append(r)

    return leads_hits[:5], pleads_hits[:5]


async def _gather_context(
    db: AsyncSession, user: Optional[User]
) -> RoutingContext:
    """Charge un sous-ensemble léger des entités utiles au matching.
    On limite à 50/50/50 pour garder le prompt sous contrôle ; en
    pratique ça couvre la grande majorité des cas (entreprises actives,
    leads récents)."""
    ents = (
        await db.execute(
            select(Entreprise)
            .where(Entreprise.is_active.is_(True))
            .order_by(Entreprise.name.asc())
            .limit(50)
        )
    ).scalars().all()
    leads = (
        await db.execute(
            select(LeadAnalysis)
            .order_by(LeadAnalysis.id.desc())
            .limit(50)
        )
    ).scalars().all()
    pleads = (
        await db.execute(
            select(ProspectionLead)
            .order_by(ProspectionLead.id.desc())
            .limit(50)
        )
    ).scalars().all()
    return RoutingContext(
        entreprises=list(ents),
        leads=list(leads),
        prospection_leads=list(pleads),
    )


def _format_context(ctx: RoutingContext) -> str:
    parts: list[str] = []
    if ctx.entreprises:
        lines = [f"- #{e.id} {e.name}" for e in ctx.entreprises]
        parts.append("## Entreprises actives\n" + "\n".join(lines))
    if ctx.leads:
        lines = []
        for l in ctx.leads[:30]:
            addr = l.address or "—"
            city = f", {l.city}" if l.city else ""
            lines.append(f"- #{l.id} {addr}{city}")
        parts.append("## Leads d'analyse (Prospection)\n" + "\n".join(lines))
    if ctx.prospection_leads:
        lines = []
        for pl in ctx.prospection_leads[:30]:
            addr = pl.address or "—"
            lines.append(f"- #{pl.id} {addr}")
        parts.append("## Leads du Pipeline\n" + "\n".join(lines))
    return "\n\n".join(parts) if parts else "(aucun contexte chargé)"


async def _call_claude(
    text: str,
    ctx: RoutingContext,
    *,
    email_signals: Optional[dict] = None,
    email_lead_matches: Optional[list[LeadAnalysis]] = None,
    email_plead_matches: Optional[list[ProspectionLead]] = None,
) -> dict:
    """Appelle Claude et retourne le dict parsé. Lève si l'IA n'est
    pas configurée — le caller gère le fallback (status=needs_review,
    kind=unknown).

    Si `email_signals` est fourni, on injecte un bloc « Indices courriel
    détectés » dans le prompt avec les candidats identifiés par
    email/téléphone — Claude saura router en priorité sur ces leads."""
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY non configuré.")
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    extra = ""
    if email_signals and email_signals.get("is_email"):
        lines = ["## Indices courriel détectés"]
        if email_signals.get("subject"):
            lines.append(f"Objet : {email_signals['subject']}")
        if email_signals.get("emails"):
            lines.append(
                "Adresses détectées : " + ", ".join(email_signals["emails"])
            )
        if email_signals.get("phones"):
            lines.append(
                "Téléphones détectés : " + ", ".join(email_signals["phones"])
            )
        if email_lead_matches:
            lines.append("Leads d'analyse correspondant (priorité) :")
            for l in email_lead_matches:
                addr = l.address or "—"
                contact = l.courtier_contact or ""
                lines.append(f"  - #{l.id} {addr} — {contact[:80]}")
        if email_plead_matches:
            lines.append("Leads du Pipeline correspondant (priorité) :")
            for pl in email_plead_matches:
                addr = pl.address or "—"
                lines.append(
                    f"  - #{pl.id} {addr} — {pl.owner_email or ''} / {pl.owner_phone or ''}"
                )
        if not email_lead_matches and not email_plead_matches:
            lines.append(
                "(aucun lead trouvé par email/téléphone — propose `note` "
                "ou kind=unknown avec confidence=low.)"
            )
        extra = "\n".join(lines) + "\n\n"

    user_prompt = (
        f"## Contexte (entités disponibles)\n{_format_context(ctx)}\n\n"
        f"{extra}"
        f"## Entrée utilisateur\n{text.strip()}\n\n"
        "Retourne le JSON strict selon le schéma."
    )
    msg = client.messages.create(
        model=KRATOS_MODEL,
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = "\n".join(b.text for b in msg.content if b.type == "text").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    return json.loads(raw)


def _parse_routing(raw: dict) -> RoutingResult:
    kind = str(raw.get("kind") or "note").strip()
    valid_kinds = {k.value for k in KratosIntentKind}
    if kind not in valid_kinds:
        kind = KratosIntentKind.UNKNOWN.value

    def _int(v: Any) -> Optional[int]:
        if v is None:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    confidence = str(raw.get("confidence") or "low").lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "low"

    return RoutingResult(
        kind=kind,
        summary=str(raw.get("summary") or "")[:500],
        title=(str(raw.get("title")).strip() if raw.get("title") else None),
        entreprise_id=_int(raw.get("entreprise_id")),
        lead_analysis_id=_int(raw.get("lead_analysis_id")),
        prospection_lead_id=_int(raw.get("prospection_lead_id")),
        confidence=confidence,
        reason=str(raw.get("reason") or "")[:300],
        raw_json=raw,
    )


async def _apply_routing(
    db: AsyncSession,
    user: Optional[User],
    routing: RoutingResult,
    original_text: str,
) -> tuple[Optional[str], Optional[int]]:
    """Applique le routage (création de l'objet cible). Retourne
    (target_type, target_id) ou (None, None) si pas d'action."""

    if routing.kind == KratosIntentKind.ENTREPRISE_TASK.value:
        if routing.entreprise_id is None:
            return None, None
        title = routing.title or routing.summary[:120] or "Note Kratos"
        tache = EntrepriseTache(
            entreprise_id=routing.entreprise_id,
            title=title[:255],
            description=original_text[:5000],
            status=TacheStatus.TODO.value,
            created_by_user_id=user.id if user else None,
        )
        db.add(tache)
        await db.flush()
        return "entreprise_tache", int(tache.id)

    if routing.kind == KratosIntentKind.LEAD_NOTE.value:
        if routing.lead_analysis_id is None:
            return None, None
        lead = (
            await db.execute(
                select(LeadAnalysis).where(
                    LeadAnalysis.id == routing.lead_analysis_id
                )
            )
        ).scalar_one_or_none()
        if lead is None:
            return None, None
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        addition = f"\n\n--- Kratos {stamp} ---\n{original_text.strip()}"
        lead.notes = (lead.notes or "") + addition
        await db.flush()
        return "lead_analysis", int(lead.id)

    if routing.kind == KratosIntentKind.PROSPECTION_LEAD_NOTE.value:
        if routing.prospection_lead_id is None:
            return None, None
        plead = (
            await db.execute(
                select(ProspectionLead).where(
                    ProspectionLead.id == routing.prospection_lead_id
                )
            )
        ).scalar_one_or_none()
        if plead is None:
            return None, None
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        addition = f"\n\n--- Kratos {stamp} ---\n{original_text.strip()}"
        existing = getattr(plead, "notes", None) or ""
        plead.notes = existing + addition  # type: ignore[attr-defined]
        await db.flush()
        return "prospection_lead", int(plead.id)

    # note / unknown → pas d'action, juste stockage dans l'inbox
    return None, None


async def route_text(
    db: AsyncSession,
    user: Optional[User],
    text: str,
) -> KratosMessage:
    """Pipeline complet : route + persiste un KratosMessage."""
    text_clean = (text or "").strip()
    if not text_clean:
        raise ValueError("Texte vide.")

    ctx = await _gather_context(db, user)

    # Détection courriel + pré-matching par adresse/téléphone (Phase 2).
    email_signals = _detect_email_signals(text_clean)
    lead_matches: list[LeadAnalysis] = []
    plead_matches: list[ProspectionLead] = []
    if email_signals["is_email"] and (
        email_signals["emails"] or email_signals["phones"]
    ):
        lead_matches, plead_matches = await _match_leads_by_contact(
            db, email_signals["emails"], email_signals["phones"]
        )

    # Appel IA (avec fallback heuristique LOCAL si Claude échoue).
    try:
        raw = await _call_claude(
            text_clean,
            ctx,
            email_signals=email_signals if email_signals["is_email"] else None,
            email_lead_matches=lead_matches if email_signals["is_email"] else None,
            email_plead_matches=plead_matches if email_signals["is_email"] else None,
        )
        routing = _parse_routing(raw)
        ia_ok = True
    except Exception as exc:  # noqa: BLE001
        log.warning("Kratos IA fallback → routeur local : %s", exc)
        # Plutôt que de marquer en `unknown / needs_review`, on délègue
        # au routeur heuristique local. Kratos continue à classer même
        # si Claude est down / quota dépassé / clé manquante.
        from app.services.kratos_local_router import route_locally

        local = await route_locally(db, text_clean)
        routing = RoutingResult(
            kind=local.kind,
            summary=local.summary,
            title=local.title,
            entreprise_id=local.entreprise_id,
            lead_analysis_id=local.lead_analysis_id,
            prospection_lead_id=local.prospection_lead_id,
            confidence=local.confidence,
            reason=f"Fallback local (Claude indisponible) : {local.reason}",
            raw_json={"fallback": "local", "reason": local.reason},
        )
        ia_ok = True  # le local a routé, on applique normalement

    # Routage seulement si confidence >= medium.
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    if ia_ok and routing.confidence in ("high", "medium"):
        target_type, target_id = await _apply_routing(
            db, user, routing, text_clean
        )

    # needs_review si :
    #   - confidence=low,
    #   - ou routage tenté mais target absent (cible non trouvée),
    #   - ou kind=unknown.
    needs_review = (
        routing.confidence == "low"
        or routing.kind == KratosIntentKind.UNKNOWN.value
        or (
            routing.kind != KratosIntentKind.NOTE.value
            and target_id is None
        )
    )
    status = (
        KratosMessageStatus.NEEDS_REVIEW.value
        if needs_review
        else KratosMessageStatus.ROUTED.value
    )

    msg = KratosMessage(
        user_id=user.id if user else None,
        original_text=text_clean[:10_000],
        intent_kind=routing.kind,
        intent_json=json.dumps(routing.raw_json, default=str)[:5000],
        summary=routing.summary,
        target_type=target_type,
        target_id=target_id,
        status=status,
        processed_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    await db.flush()
    return msg
