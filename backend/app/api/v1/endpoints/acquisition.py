"""Tableau Acquisition — entonnoir (funnel) à partir des données réelles.

Vue « système d'acquisition » : combien de leads entrent, combien sont
contactés / qualifiés / rendez-vous / soumissionnés / gagnés, et le taux
de conversion. S'appuie sur le pipeline `ContactRequestStatus` (CRM
construction) + quelques métriques téléphonie (appels, leads captés par
Léa). Réservé owner/admin.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import DBSession, RequireAdminOrOwner
from app.models.contact_request import ContactRequest, ContactRequestStatus
from app.models.voice import Call

router = APIRouter(prefix="/acquisition", tags=["acquisition"])

# Étapes de l'entonnoir, dans l'ordre. Chaque étape = nombre de leads
# AYANT ATTEINT ce stade (cumulatif vers la conversion).
_FUNNEL_ORDER = [
    ContactRequestStatus.NEW.value,
    ContactRequestStatus.CONTACTED.value,
    ContactRequestStatus.RDV_PREVU.value,
    ContactRequestStatus.QUALIFIED.value,
    ContactRequestStatus.QUOTED.value,
    ContactRequestStatus.WON.value,
]
_FUNNEL_LABELS = {
    "new": "Nouveaux leads",
    "contacted": "Contactés",
    "rdv_prevu": "RDV prévu",
    "qualified": "Qualifiés",
    "quoted": "Soumissionnés",
    "won": "Gagnés",
}
# Rang d'avancement : un lead « won » a forcément passé tous les stades.
_RANK = {s: i for i, s in enumerate(_FUNNEL_ORDER)}


@router.get("/funnel")
async def acquisition_funnel(
    db: DBSession,
    user: RequireAdminOrOwner,
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """Entonnoir d'acquisition sur les `days` derniers jours."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        await db.execute(
            select(ContactRequest.status, func.count())
            .where(ContactRequest.created_at >= cutoff)
            .group_by(ContactRequest.status)
        )
    ).all()
    by_status: dict[str, int] = {s: 0 for s in _RANK}
    spam = 0
    lost = 0
    for status_val, n in rows:
        if status_val == ContactRequestStatus.SPAM.value:
            spam += int(n)
        elif status_val == ContactRequestStatus.LOST.value:
            lost += int(n)
        elif status_val in by_status:
            by_status[status_val] = int(n)

    # Cumulatif : un lead à un stade avancé a traversé les précédents.
    # On compte aussi les "lost" comme ayant été au moins "contactés".
    raw_counts = list(by_status.values())
    stages = []
    total_real = sum(raw_counts) + lost  # hors spam
    for i, key in enumerate(_FUNNEL_ORDER):
        reached = sum(raw_counts[i:])
        if key == "contacted":
            reached += lost  # un lead perdu a quand même été engagé
        stages.append(
            {
                "key": key,
                "label": _FUNNEL_LABELS[key],
                "count": reached,
            }
        )

    won = by_status.get("won", 0)
    conversion_rate = round(100.0 * won / total_real, 1) if total_real else 0.0

    # Métriques téléphonie (Léa) sur la même fenêtre.
    calls_total = (
        await db.execute(
            select(func.count(Call.id)).where(Call.started_at >= cutoff)
        )
    ).scalar_one() or 0
    calls_lead = (
        await db.execute(
            select(func.count(Call.id)).where(
                Call.started_at >= cutoff,
                Call.intent.in_(["callback", "intake_construction"]),
            )
        )
    ).scalar_one() or 0

    return {
        "days": days,
        "total_leads": total_real,
        "spam_filtered": spam,
        "lost": lost,
        "won": won,
        "conversion_rate": conversion_rate,
        "stages": stages,
        "voice": {
            "calls_total": int(calls_total),
            "leads_captured": int(calls_lead),
        },
    }
