"""Brief du matin par courriel (Phil, 2026-10-15).

Problème : la routine claude.ai de Phil (« Horizon — Ma journée », lun.-ven.
05 h) lit Kratos par le connecteur MCP, mais le connecteur n'est pas
attaché de façon fiable aux sessions planifiées (« Kratos n'a pas été lu
ce matin »). Les crons Render de Kratos, eux, ne tournent pas (toutes les
automatisations affichent « jamais exécutée »).

Solution autonome : une boucle démarrée AVEC l'application (comme les
filets QBO) envoie chaque matin, à l'heure réglée (Paramètres →
Automatisations → « Brief du matin par courriel », défaut 04 h 30
Montréal, jours ouvrables), le digest Kratos de chaque destinataire par
courriel. La routine n'a plus qu'à lire ce courriel dans Outlook (un
connecteur de première partie, toujours attaché) ; le connecteur Kratos
devient un plus, pas une dépendance.

Destinataires : par défaut, les utilisateurs qui possèdent une clé API
active (ce sont eux qui branchent des Claude) ; remplaçables par la liste
``destinataires`` (courriels) de la configuration de l'automatisation.
Idempotent par jour (``claim_cron_run``). Jamais de contenu hors des
permissions de l'utilisateur : le digest est celui de ``kratos_mon_brief``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

JOB = "brief_matin"
FUSEAU = ZoneInfo("America/Toronto")
_PREMIER_PASSAGE_S = 60.0
_INTERVALLE_S = 300.0
#: Deux envois ne peuvent pas être à moins de 20 h d'écart (un par jour).
_MIN_INTERVALLE_S = 20 * 3600

_JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
    "septembre", "octobre", "novembre", "décembre",
)


def date_lisible(d: datetime) -> str:
    return f"{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]} {d.year}"


def sujet_du_jour(d: datetime) -> str:
    return f"Kratos — brief du {date_lisible(d)}"


async def destinataires(db: AsyncSession, config: Optional[dict[str, Any]] = None) -> list:
    """Utilisateurs à servir : liste ``destinataires`` (courriels) de la
    configuration si présente, sinon les propriétaires d'une clé API
    active (non expirée)."""
    from app.models.api_key import ApiKey
    from app.models.user import User

    cfg = config or {}
    emails = [str(e).strip().lower() for e in (cfg.get("destinataires") or []) if str(e).strip()]
    if emails:
        rows = (
            await db.execute(select(User).where(User.email.in_(emails)))
        ).scalars().all()
    else:
        now = datetime.now(timezone.utc)
        rows = (
            await db.execute(
                select(User)
                .join(ApiKey, ApiKey.user_id == User.id)
                .where(
                    ApiKey.is_active.is_(True),
                    (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now),
                )
            )
        ).scalars().unique().all()
    vus: set[str] = set()
    out = []
    for u in rows:
        email = (getattr(u, "email", "") or "").strip().lower()
        if not email or email in vus or not getattr(u, "is_active", True):
            continue
        vus.add(email)
        out.append(u)
    return out


def _echapper(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def construire_html(digest: str, prenom: str, quand: datetime) -> str:
    lignes = [l.strip() for l in (digest or "").splitlines() if l.strip()]
    titre = lignes[0] if lignes else f"État de Kratos au {quand.date().isoformat()}"
    puces = "".join(f"<li>{_echapper(l)}</li>" for l in lignes[1:])
    return (
        f"<p>Bonjour {_echapper(prenom)},</p>"
        f"<p>Voici l'état de Kratos ce {_echapper(date_lisible(quand))} "
        f"(généré automatiquement à {quand.strftime('%H:%M')}, heure de Montréal).</p>"
        f"<p><strong>{_echapper(titre)}</strong></p>"
        f"<ul>{puces}</ul>"
        "<p style=\"color:#666;font-size:12px\">Ce courriel est produit par Kratos pour tes "
        "routines (Claude peut le lire dans Outlook : sujet « Kratos — brief du … »). "
        "Réglages : Paramètres → Automatisations → Brief du matin par courriel. "
        "<a href=\"https://immohorizon.com/app\">Ouvrir Kratos</a></p>"
    )


async def envoyer_brief(
    db: AsyncSession, *, quand: Optional[datetime] = None, config: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Envoie le brief à chaque destinataire. Renvoie {envoyes, destinataires,
    erreurs}. N'appelle pas commit."""
    from app.integrations.email_graph import get_mailer
    from app.services.audit import log_action
    from app.services.automation_state import get_automation_config
    from app.services.user_ai import digest_pour_utilisateur

    quand = quand or datetime.now(FUSEAU)
    cfg = config if config is not None else await get_automation_config(JOB)
    users = await destinataires(db, cfg)
    rapport: dict[str, Any] = {"envoyes": 0, "destinataires": [u.email for u in users], "erreurs": []}
    if not users:
        rapport["erreurs"].append("aucun destinataire (aucune clé API active, aucune liste configurée)")
        return rapport
    mailer = get_mailer()
    if not mailer.ready:
        rapport["erreurs"].append("Mailer Microsoft 365 non configuré")
        return rapport
    sujet = sujet_du_jour(quand)
    for u in users:
        try:
            digest = await digest_pour_utilisateur(db, u)
            prenom = (
                getattr(u, "first_name", None) or getattr(u, "full_name", None)
                or getattr(u, "name", None) or u.email
            ).split()[0]
            await mailer.send(to=[u.email], subject=sujet, html_body=construire_html(digest, prenom, quand))
            rapport["envoyes"] += 1
            await log_action(
                db, user=u, action="brief_matin.envoye", entity_type="user",
                entity_id=getattr(u, "id", None), details={"sujet": sujet},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("brief du matin : envoi à %s échoué", u.email, exc_info=True)
            rapport["erreurs"].append(f"{u.email} : {type(exc).__name__}: {str(exc)[:160]}")
    return rapport


def est_du(now_local: datetime, heure: int, minute: int, jours_ouvrables: bool) -> bool:
    """Vrai si on a dépassé l'heure d'envoi du jour (et que c'est un jour
    servi). L'idempotence par jour est assurée ailleurs (claim_cron_run)."""
    if jours_ouvrables and now_local.weekday() >= 5:
        return False
    return (now_local.hour, now_local.minute) >= (heure, minute)


async def envoyer_si_du(now_local: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """Point d'entrée de la boucle : envoie une fois par jour, après l'heure
    réglée. None si rien à faire."""
    from app.db.session import AsyncSessionLocal
    from app.services.automation_state import (
        get_automation_config,
        get_automation_int,
        is_automation_enabled,
    )
    from app.services.cron_guard import claim_cron_run

    if not await is_automation_enabled(JOB):
        return None
    now_local = now_local or datetime.now(FUSEAU)
    heure = await get_automation_int(JOB, "heure", 4)
    minute = await get_automation_int(JOB, "minute", 30)
    cfg = await get_automation_config(JOB)
    jours_ouvrables = str(cfg.get("jours_ouvrables", "1")) not in ("0", "false", "False")
    if not est_du(now_local, heure, minute % 60, jours_ouvrables):
        return None
    async with AsyncSessionLocal() as db:
        if not await claim_cron_run(db, JOB, _MIN_INTERVALLE_S):
            return None
        rapport = await envoyer_brief(db, quand=now_local, config=cfg)
        await db.commit()
        log.info("brief du matin envoyé : %s", rapport)
        return rapport


async def boucle() -> None:
    """Boucle de fond démarrée avec l'app (comme les filets QBO) : premier
    passage ~1 min après le boot, puis toutes les 5 minutes. Jamais sous
    pytest : la boucle travaillerait en parallèle des tests sur la base
    de test (4 tests du registre des courtiers tombaient)."""
    import sys

    if "pytest" in sys.modules:
        log.info("brief du matin : boucle désactivée (tests)")
        return
    delay = _PREMIER_PASSAGE_S
    while True:
        try:
            await asyncio.sleep(delay)
            delay = _INTERVALLE_S
            await envoyer_si_du()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.warning("Boucle brief du matin : itération échouée", exc_info=True)


__all__ = [
    "JOB",
    "FUSEAU",
    "sujet_du_jour",
    "date_lisible",
    "destinataires",
    "construire_html",
    "envoyer_brief",
    "est_du",
    "envoyer_si_du",
    "boucle",
]
