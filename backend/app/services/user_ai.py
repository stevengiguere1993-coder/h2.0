"""IA personnelle — routage des appels IA vers la clé DE L'UTILISATEUR
et brief quotidien (« chacun son IA », vision Phil 2026-09-01).

Règles :
- Un utilisateur AVEC une connexion IA active → ses appels IA passent
  par SON fournisseur/sa clé, avec son brief du jour injecté en
  contexte (c'est la « mémoire » de son IA).
- Sans connexion : ``complete_for_user`` retourne None et l'appelant
  garde son comportement historique (clé maison) — le mode strict
  « pas de clé = pas d'IA » s'activera au GO de Phil.
- L'IA des appels téléphoniques (Groq, webhooks) n'est PAS routée ici.
- Le brief lit Kratos AVEC LES PERMISSIONS de l'utilisateur
  (utilisateur_a_acces_page — permissions v2).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.ai._anthropic import AnthropicProvider
from app.integrations.ai._base import AIProviderError, CompletionResult
from app.integrations.ai._gemini import GeminiProvider
from app.integrations.ai._openai import OpenAIProvider
from app.models.user import User
from app.models.user_ai import UserAiBrief, UserAiConfig

log = logging.getLogger(__name__)

PROVIDERS_PERSO = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}


async def get_config(
    db: AsyncSession, user_id: int
) -> Optional[UserAiConfig]:
    return (
        await db.execute(
            select(UserAiConfig).where(UserAiConfig.user_id == user_id)
        )
    ).scalar_one_or_none()


def _provider_for(cfg: UserAiConfig):
    cls = PROVIDERS_PERSO.get((cfg.provider or "").strip().lower())
    if cls is None:
        return None
    return cls(api_key=cfg.api_key)


async def get_user_ai(db: AsyncSession, user_id: int):
    """(provider, config) de l'IA personnelle, ou None si pas branchée."""
    cfg = await get_config(db, user_id)
    if cfg is None or not cfg.actif or not (cfg.api_key or "").strip():
        return None
    prov = _provider_for(cfg)
    if prov is None:
        return None
    return prov, cfg


async def dernier_brief(
    db: AsyncSession, user_id: int
) -> Optional[UserAiBrief]:
    return (
        await db.execute(
            select(UserAiBrief)
            .where(UserAiBrief.user_id == user_id)
            .order_by(UserAiBrief.jour.desc(), UserAiBrief.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def complete_for_user(
    db: AsyncSession,
    user: User,
    *,
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: float = 0.3,
    avec_brief: bool = True,
) -> Optional[CompletionResult]:
    """Appel IA via la clé PERSONNELLE de l'utilisateur. None si pas
    d'IA branchée (l'appelant retombe sur le comportement historique).
    Lève AIProviderError si l'appel échoue — l'appelant décide."""
    pair = await get_user_ai(db, user.id)
    if pair is None:
        return None
    prov, cfg = pair
    sys_parts = []
    if avec_brief:
        brief = await dernier_brief(db, user.id)
        if brief is not None:
            sys_parts.append(
                "Contexte Kratos (ton brief du "
                f"{brief.jour.isoformat()}) :\n{brief.contenu[:6000]}"
            )
    if system:
        sys_parts.append(system)
    return await prov.complete(
        prompt=prompt,
        system="\n\n".join(sys_parts) or None,
        max_tokens=max_tokens,
        temperature=temperature,
        model=(cfg.model or None),
    )


# ─── Brief quotidien ─────────────────────────────────────────────────


async def _digest_pour(db: AsyncSession, user: User) -> str:
    """Compile l'état de Kratos VISIBLE PAR cet utilisateur (chaque
    section est gardée par sa permission de page + best-effort)."""
    from app.services.assistant_catalogue import utilisateur_a_acces_page

    today = datetime.now(timezone.utc).date()
    lignes: list[str] = [f"État de Kratos au {today.isoformat()}."]

    async def _garde(page_key: str) -> bool:
        try:
            return await utilisateur_a_acces_page(db, user, page_key)
        except Exception:  # noqa: BLE001 — permission indisponible = non
            return False

    # ── Prospection : analyses de leads ──
    if await _garde("prospection.analyses"):
        try:
            from app.models.lead_analysis import LeadAnalysis

            rows = (
                await db.execute(
                    select(
                        LeadAnalysis.status, func.count(LeadAnalysis.id)
                    ).group_by(LeadAnalysis.status)
                )
            ).all()
            if rows:
                lignes.append(
                    "Prospection — analyses de leads : "
                    + ", ".join(f"{n} {s}" for s, n in rows)
                )
        except Exception:  # noqa: BLE001
            pass

    # ── Locatif : paiements du mois ──
    if await _garde("immobilier.paiements"):
        try:
            from app.api.v1.endpoints.immobilier import loyers_overview

            ov = await loyers_overview(db, user, mois=None)
            lignes.append(
                f"Gestion locative ({ov.mois}) : {ov.nb_retards} en "
                f"retard, {ov.nb_payes} payés, {ov.nb_attente} en "
                f"attente, {getattr(ov, 'nb_vacants', 0)} vacants, "
                f"solde dû total {ov.total_solde_du:,.0f} $."
            )
        except Exception:  # noqa: BLE001
            pass

    # ── Construction : soumissions + projets ──
    if await _garde("construction.soumissions"):
        try:
            from app.models.soumission import Soumission

            rows = (
                await db.execute(
                    select(
                        Soumission.status, func.count(Soumission.id)
                    ).group_by(Soumission.status)
                )
            ).all()
            if rows:
                lignes.append(
                    "Construction — soumissions : "
                    + ", ".join(f"{n} {s}" for s, n in rows)
                )
        except Exception:  # noqa: BLE001
            pass

    # ── Entreprises : tâches ouvertes de l'utilisateur ──
    if await _garde("entreprises.taches"):
        try:
            from app.models.entreprise_tache import EntrepriseTache

            n_ouvertes = (
                await db.execute(
                    select(func.count(EntrepriseTache.id)).where(
                        EntrepriseTache.status != "done"
                    )
                )
            ).scalar() or 0
            lignes.append(
                f"Gestion d'entreprise : {n_ouvertes} tâches ouvertes."
            )
        except Exception:  # noqa: BLE001
            pass

    # ── Communications récentes (7 jours) ──
    try:
        from app.models.email_log import EmailLog

        depuis = datetime.now(timezone.utc) - timedelta(days=7)
        n_emails = (
            await db.execute(
                select(func.count(EmailLog.id)).where(
                    EmailLog.created_at >= depuis
                )
            )
        ).scalar() or 0
        lignes.append(f"Communications : {n_emails} courriels (7 jours).")
    except Exception:  # noqa: BLE001
        pass

    return "\n".join(lignes)


# Alias PUBLIC du digest — consommé par le serveur MCP (outil
# ``kratos_mon_brief``) : le Claude Max de l'utilisateur reçoit le
# digest compilé (permissions respectées) et écrit le brief LUI-MÊME,
# sur son abonnement — zéro coût API (retour Phil 2026-09-02).
async def digest_pour_utilisateur(db: AsyncSession, user: User) -> str:
    return await _digest_pour(db, user)


async def construire_brief(
    db: AsyncSession, user: User
) -> Optional[UserAiBrief]:
    """Génère (ou régénère) le brief du JOUR pour un utilisateur avec
    son IA personnelle. None si pas d'IA branchée."""
    pair = await get_user_ai(db, user.id)
    if pair is None:
        return None
    prov, cfg = pair

    digest = await _digest_pour(db, user)
    prenom = (user.first_name or "").strip() or user.email
    res = await prov.complete(
        prompt=(
            "Voici l'état compilé de la plateforme Kratos visible par "
            f"{prenom} aujourd'hui :\n\n{digest}\n\n"
            "Écris SON brief quotidien : 5 à 10 puces, français, "
            "direct, en le tutoyant. Commence par ce qui demande une "
            "action (retards, décisions en attente), termine par une "
            "vue d'ensemble. Pas de préambule."
        ),
        system=(
            "Tu es l'assistant personnel de ce membre de l'équipe "
            "Horizon sur la plateforme Kratos (immobilier, "
            "construction, prospection, gestion d'entreprise). Sois "
            "concret et actionnable."
        ),
        max_tokens=900,
        temperature=0.4,
        model=(cfg.model or None),
    )

    today = datetime.now(timezone.utc).date()
    existant = (
        await db.execute(
            select(UserAiBrief).where(
                UserAiBrief.user_id == user.id,
                UserAiBrief.jour == today,
            )
        )
    ).scalar_one_or_none()
    if existant is not None:
        existant.contenu = res.text
        existant.digest = digest
        existant.provider = res.provider
        existant.model = res.model
        brief = existant
    else:
        brief = UserAiBrief(
            user_id=user.id,
            jour=today,
            contenu=res.text,
            digest=digest,
            provider=res.provider,
            model=res.model,
        )
        db.add(brief)
    await db.flush()
    return brief


async def generer_briefs_quotidiens(db: AsyncSession) -> dict:
    """Cron 1×/jour : un brief par utilisateur avec IA active (et
    brief_actif). Best-effort par utilisateur — une clé morte n'arrête
    pas les autres."""
    configs = (
        await db.execute(
            select(UserAiConfig).where(
                UserAiConfig.actif.is_(True),
                UserAiConfig.brief_actif.is_(True),
            )
        )
    ).scalars().all()
    ok, echecs = 0, []
    for cfg in configs:
        user = await db.get(User, cfg.user_id)
        if user is None:
            continue
        try:
            if await construire_brief(db, user) is not None:
                ok += 1
                await db.commit()
        except AIProviderError as exc:
            await db.rollback()
            echecs.append({"user_id": cfg.user_id, "erreur": str(exc)[:200]})
            log.warning("Brief IA échoué pour user %s: %s", cfg.user_id, exc)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            echecs.append({"user_id": cfg.user_id, "erreur": str(exc)[:200]})
            log.exception("Brief IA — erreur inattendue user %s", cfg.user_id)
    return {"generes": ok, "echecs": echecs, "configs": len(configs)}
