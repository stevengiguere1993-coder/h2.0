"""Kratos — routeur local sans IA (fallback).

Détecte l'intent et la cible par règles heuristiques pures. Activé
quand Claude est indisponible (clé manquante, timeout, quota) pour
que Kratos continue à classer correctement les entrées au lieu de
tout mettre en `unknown / needs_review`.

Stratégie :
  1. Signaux courriel (From:/email/phone) → matching DB sur leads.
  2. Verbes d'action (rappelle, envoie, vérifie, …) → task.
  3. Mots-clés « note / pour info / observation » → note.
  4. Mention explicite d'une entreprise (par nom substring) →
     contextualise la tâche.
  5. Sinon → kind=note, confidence=low.

Le résumé est généré par extraction simple : première phrase
< 200 caractères, ou troncature soft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entreprise import Entreprise
from app.models.entreprise_tache import EntrepriseTache
from app.models.kratos_message import KratosIntentKind
from app.models.lead_analysis import LeadAnalysis
from app.models.prospection_lead import ProspectionLead


# Verbes/expressions qui signalent une TÂCHE à exécuter.
TASK_VERB_PATTERNS = [
    r"\brappel(?:le|er|ons|ons-(?:nous|moi))\b",
    r"\benvoi(?:e|er|ons)\b",
    r"\bv[eé]rif(?:ie|ier|ions)\b",
    r"\bdemand(?:e|er|ons)\b",
    r"\bappel(?:le|er|ons)\b",
    r"\bcontact(?:e|er|ons)\b",
    r"\bplanif(?:ie|ier|ions)\b",
    r"\bpr[eé]par(?:e|er|ons)\b",
    r"\benvoyer\b",
    r"\bdoit\b",
    r"\bil faut\b",
    r"\bà faire\b",
    r"\btodo\b",
    r"\btâche\b",
    r"\btache\b",
    r"\bcr[eé]er\b",
    r"\borganis(?:er|ons)\b",
]
TASK_VERB_RE = re.compile("|".join(TASK_VERB_PATTERNS), re.I)

# Mots-clés qui signalent une simple NOTE (pas d'action).
NOTE_KEYWORD_RE = re.compile(
    r"\b(pour info|fyi|observation|note(?:r|z)?|à savoir|à noter)\b", re.I
)

# Mots-clés qui signalent un SUIVI / NOTE sur un lead.
LEAD_KEYWORD_RE = re.compile(
    r"\b(suivi|relance|réponse|reponse|courtier|courriel|email|"
    r"propriétaire|proprietaire|locataire|inscription|listing|"
    r"vendeur|annonce)\b",
    re.I,
)

EMAIL_HEADER_RE = re.compile(
    r"^\s*(?:From|De|Sender|Expéditeur)\s*:\s*", re.I | re.M
)
EMAIL_ADDRESS_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)
PHONE_RE = re.compile(
    r"(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}"
)


@dataclass
class LocalRouting:
    kind: str
    summary: str
    title: Optional[str]
    entreprise_id: Optional[int]
    lead_analysis_id: Optional[int]
    prospection_lead_id: Optional[int]
    confidence: str  # "high" | "medium" | "low"
    reason: str


def _summary(text: str) -> str:
    """Première phrase ≤ 200 caractères, ou troncature."""
    t = text.strip().replace("\n", " ")
    t = re.sub(r"\s+", " ", t)
    # Coupe à la première ponctuation forte.
    m = re.match(r"^(.{20,200}?[.!?])(?:\s|$)", t)
    if m:
        return m.group(1).strip()
    return t[:200].strip()


def _title_from_task(text: str) -> str:
    """Génère un titre court à partir du texte d'une tâche."""
    s = _summary(text)
    # Capitalize première lettre, max 120 car.
    s = s.strip().rstrip(".!?,;:")
    if s:
        s = s[0].upper() + s[1:]
    return s[:120] or "Tâche Kratos"


def _normalize(s: str) -> str:
    s = s.lower().strip()
    # Retire accents simples pour le matching.
    accents = {
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "à": "a", "â": "a", "ä": "a",
        "ï": "i", "î": "i",
        "ô": "o", "ö": "o",
        "ù": "u", "û": "u", "ü": "u",
        "ç": "c",
    }
    return "".join(accents.get(c, c) for c in s)


async def _match_entreprise(
    db: AsyncSession, text: str
) -> Optional[Entreprise]:
    """Cherche le nom de l'entreprise dans le texte (substring case-
    insensitive après normalisation). Privilégie le match le plus
    long. Retourne None si aucun nom > 4 char ne matche."""
    ents = (
        await db.execute(
            select(Entreprise).where(Entreprise.is_active.is_(True))
        )
    ).scalars().all()
    norm_text = _normalize(text)
    best: Optional[tuple[Entreprise, int]] = None
    for e in ents:
        name = (e.name or "").strip()
        if len(name) < 4:
            continue
        if _normalize(name) in norm_text:
            if best is None or len(name) > best[1]:
                best = (e, len(name))
    return best[0] if best else None


async def _match_lead_by_address(
    db: AsyncSession, text: str
) -> tuple[Optional[LeadAnalysis], Optional[ProspectionLead]]:
    """Cherche une adresse de lead mentionnée dans le texte. Match
    sur les 5+ premiers chiffres + nom de rue. Privilégie le match
    le plus précis (le plus long)."""
    norm_text = _normalize(text)
    best_la: Optional[tuple[LeadAnalysis, int]] = None
    best_pl: Optional[tuple[ProspectionLead, int]] = None

    leads = (
        await db.execute(
            select(LeadAnalysis).order_by(LeadAnalysis.id.desc()).limit(100)
        )
    ).scalars().all()
    for l in leads:
        if not l.address or len(l.address) < 5:
            continue
        if _normalize(l.address)[:30] in norm_text:
            score = min(len(l.address), 30)
            if best_la is None or score > best_la[1]:
                best_la = (l, score)

    pleads = (
        await db.execute(
            select(ProspectionLead).order_by(ProspectionLead.id.desc()).limit(100)
        )
    ).scalars().all()
    for pl in pleads:
        if not pl.address or len(pl.address) < 5:
            continue
        if _normalize(pl.address)[:30] in norm_text:
            score = min(len(pl.address), 30)
            if best_pl is None or score > best_pl[1]:
                best_pl = (pl, score)

    return (
        best_la[0] if best_la else None,
        best_pl[0] if best_pl else None,
    )


async def _match_lead_by_contact(
    db: AsyncSession, text: str
) -> tuple[Optional[LeadAnalysis], Optional[ProspectionLead]]:
    """Match par email ou téléphone détecté dans le texte."""
    emails = [e.lower() for e in EMAIL_ADDRESS_RE.findall(text)]
    phones_raw = PHONE_RE.findall(text)
    phones = []
    for p in phones_raw:
        digits = re.sub(r"\D", "", p)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            phones.append(digits)

    best_la: Optional[LeadAnalysis] = None
    best_pl: Optional[ProspectionLead] = None

    if emails:
        for e in emails:
            la = (
                await db.execute(
                    select(LeadAnalysis).where(
                        LeadAnalysis.courtier_contact.ilike(f"%{e}%")
                    )
                )
            ).scalar_one_or_none()
            if la and best_la is None:
                best_la = la
            pl = (
                await db.execute(
                    select(ProspectionLead).where(
                        ProspectionLead.owner_email.ilike(e)
                    )
                )
            ).scalar_one_or_none()
            if pl and best_pl is None:
                best_pl = pl

    if phones and (best_la is None or best_pl is None):
        for p in phones:
            tail = p[-7:]
            if best_la is None:
                la = (
                    await db.execute(
                        select(LeadAnalysis).where(
                            LeadAnalysis.courtier_contact.ilike(f"%{tail}%")
                        )
                    )
                ).scalar_one_or_none()
                if la:
                    best_la = la
            if best_pl is None:
                pl = (
                    await db.execute(
                        select(ProspectionLead).where(
                            ProspectionLead.owner_phone.ilike(f"%{tail}%")
                        )
                    )
                ).scalar_one_or_none()
                if pl:
                    best_pl = pl

    return best_la, best_pl


async def route_locally(
    db: AsyncSession, text: str
) -> LocalRouting:
    """Pipeline complet du routeur local. Toujours retourne un
    LocalRouting (jamais d'exception), même si rien ne matche."""
    summary = _summary(text)
    is_email = bool(EMAIL_HEADER_RE.search(text)) or (
        len(EMAIL_ADDRESS_RE.findall(text)) > 0 and len(text) > 200
    )

    # 1. Email → essaye de matcher un lead par contact d'abord.
    if is_email:
        la, pl = await _match_lead_by_contact(db, text)
        if la is not None:
            return LocalRouting(
                kind=KratosIntentKind.LEAD_NOTE.value,
                summary=summary,
                title=None,
                entreprise_id=None,
                lead_analysis_id=la.id,
                prospection_lead_id=None,
                confidence="medium",
                reason="Format courriel + lead trouvé par contact (matching local).",
            )
        if pl is not None:
            return LocalRouting(
                kind=KratosIntentKind.PROSPECTION_LEAD_NOTE.value,
                summary=summary,
                title=None,
                entreprise_id=None,
                lead_analysis_id=None,
                prospection_lead_id=pl.id,
                confidence="medium",
                reason="Format courriel + lead Pipeline trouvé par contact (local).",
            )

    # 2. Match par adresse mentionnée dans le texte.
    la, pl = await _match_lead_by_address(db, text)
    if la is not None and LEAD_KEYWORD_RE.search(text):
        return LocalRouting(
            kind=KratosIntentKind.LEAD_NOTE.value,
            summary=summary,
            title=None,
            entreprise_id=None,
            lead_analysis_id=la.id,
            prospection_lead_id=None,
            confidence="medium",
            reason="Adresse de lead + mot-clé suivi détectés (local).",
        )
    if pl is not None and LEAD_KEYWORD_RE.search(text):
        return LocalRouting(
            kind=KratosIntentKind.PROSPECTION_LEAD_NOTE.value,
            summary=summary,
            title=None,
            entreprise_id=None,
            lead_analysis_id=None,
            prospection_lead_id=pl.id,
            confidence="medium",
            reason="Adresse de lead Pipeline + mot-clé suivi (local).",
        )

    # 3. Détection tâche d'entreprise par verbes/mots-clés.
    if TASK_VERB_RE.search(text) and not NOTE_KEYWORD_RE.search(text):
        ent = await _match_entreprise(db, text)
        return LocalRouting(
            kind=KratosIntentKind.ENTREPRISE_TASK.value,
            summary=summary,
            title=_title_from_task(text),
            entreprise_id=ent.id if ent else None,
            lead_analysis_id=None,
            prospection_lead_id=None,
            confidence="medium" if ent else "low",
            reason=(
                f"Verbe d'action détecté + entreprise « {ent.name} » matchée."
                if ent
                else "Verbe d'action détecté mais aucune entreprise identifiée."
            ),
        )

    # 4. Fallback : note libre.
    return LocalRouting(
        kind=KratosIntentKind.NOTE.value,
        summary=summary,
        title=None,
        entreprise_id=None,
        lead_analysis_id=None,
        prospection_lead_id=None,
        confidence="low",
        reason="Aucun signal d'action ou de cible identifié (local).",
    )
