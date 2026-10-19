"""Échéance d'une facture client : jamais avant le jour de l'envoi.

Règle de Steven (2026-10-16, facture 160) : la date d'échéance d'une
facture est au minimum le jour où elle part chez le client. La 160 avait
été créée en brouillon le 14 octobre avec « Payable sur réception »
(échéance = jour de la création), puis envoyée le 16 : l'échéance était
restée au 14 et les rappels automatiques (4 jours après l'échéance)
seraient partis deux à trois jours après l'envoi.

Ce module centralise la règle :

- les conditions choisies (``Facture.due_in_days`` : 0 = sur réception,
  30 = net 30…) comptent à partir du jour de l'envoi, recalculé à chaque
  envoi ;
- une date personnalisée (``due_in_days`` vide) n'est jamais antérieure
  au jour de l'envoi (ni à aujourd'hui pour un brouillon) : refusée à la
  saisie, ramenée à ce jour-là à l'envoi.

Les jours sont des jours civils de Montréal (« Émise le » de la fiche).
Une échéance est un JOUR : elle est stockée à minuit UTC, comme le
sélecteur de date de la fiche, et se lit par sa date UTC (fiche, PDF,
courriel, QuickBooks).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.models.facture import Facture, FactureStatus

FUSEAU = ZoneInfo("America/Toronto")  # = heure de Montréal

#: Marqueur applied_backfills de la correction des factures déjà envoyées.
CLE_CORRECTION_ENVOYEES = "facture_echeance_jour_envoi_v1"

#: Conditions proposées sur la fiche facture (jours après l'envoi).
CONDITIONS_FICHE = (0, 10, 15, 30, 45, 60)


class EcheanceInvalide(ValueError):
    """Échéance saisie antérieure au minimum permis (message en français)."""


def aujourd_hui() -> date:
    return datetime.now(FUSEAU).date()


def _utc(moment: datetime) -> datetime:
    # SQLite (tests) relit les dates sans fuseau : elles sont en UTC.
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def jour_local(moment: Optional[datetime]) -> Optional[date]:
    """Jour civil (Montréal) d'un horodatage : une facture envoyée à
    22 h 45 le 16 est émise le 16, pas le 17 (UTC). Une date sans heure
    (minuit UTC pile : import QuickBooks, sélecteur de date) garde son
    jour."""
    if moment is None:
        return None
    utc = _utc(moment)
    if (utc.hour, utc.minute, utc.second, utc.microsecond) == (0, 0, 0, 0):
        return utc.date()
    return utc.astimezone(FUSEAU).date()


def jour_echeance(due_at: Optional[datetime]) -> Optional[date]:
    """Jour d'une échéance : sa date UTC, celle qu'affichent la fiche, le
    PDF, le courriel et QuickBooks."""
    if due_at is None:
        return None
    return _utc(due_at).date()


def echeance_du_jour(jour: date) -> datetime:
    """Valeur stockée pour une échéance tombant ce jour-là."""
    return datetime(jour.year, jour.month, jour.day, tzinfo=timezone.utc)


def conditions_deduites(
    depart: Optional[date], due_at: Optional[datetime]
) -> Optional[int]:
    """Conditions (jours) qui mènent du jour de départ à l'échéance quand
    elles correspondent à une option de la fiche ; sinon None (date
    personnalisée)."""
    if depart is None or due_at is None:
        return None
    ecart = (jour_echeance(due_at) - depart).days
    return ecart if ecart in CONDITIONS_FICHE else None


def jour_minimum(statut: Optional[str], emise_le: Optional[datetime]) -> Optional[date]:
    """Premier jour permis pour l'échéance : le jour de l'envoi d'une
    facture émise, aujourd'hui pour un brouillon. None : pas de borne
    (facture annulée, ou émise sans date d'émission connue)."""
    if (statut or FactureStatus.DRAFT.value) == FactureStatus.DRAFT.value:
        return aujourd_hui()
    if statut == FactureStatus.VOID.value:
        return None
    return jour_local(emise_le)


def normaliser_saisie(
    champs: dict[str, Any],
    *,
    statut: Optional[str],
    emise_le: Optional[datetime],
    actuelle: Optional[datetime] = None,
) -> dict[str, Any]:
    """Échéance saisie (création ou modification) → valeurs à enregistrer.

    - ``due_in_days`` (conditions) : l'échéance en découle, comptée depuis
      le jour de l'envoi (aujourd'hui pour un brouillon : elle sera
      recalculée à l'envoi) ;
    - ``due_at`` seul : date personnalisée, les conditions sont effacées.
      Renvoyée telle quelle (``actuelle`` = échéance enregistrée), elle ne
      touche à rien : ni refus, ni perte des conditions.

    Lève EcheanceInvalide si la date précède le jour minimum. Rien de
    saisi → dict vide."""
    jours = champs.get("due_in_days")
    if jours is not None:
        base = jour_minimum(statut, emise_le) or aujourd_hui()
        return {
            "due_in_days": int(jours),
            "due_at": echeance_du_jour(base + timedelta(days=int(jours))),
        }
    if "due_at" in champs:
        due = champs["due_at"]
        if due is None:
            return {"due_in_days": None, "due_at": None}
        jour = jour_echeance(due)
        if actuelle is not None and jour == jour_echeance(actuelle):
            return {"due_in_days": None} if "due_in_days" in champs else {}
        mini = jour_minimum(statut, emise_le)
        if jour is not None and mini is not None and jour < mini:
            if (statut or FactureStatus.DRAFT.value) == FactureStatus.DRAFT.value:
                raise EcheanceInvalide(
                    f"L'échéance ({jour.isoformat()}) ne peut pas précéder "
                    f"aujourd'hui ({mini.isoformat()}) : une facture est due "
                    "au plus tôt le jour de son envoi."
                )
            raise EcheanceInvalide(
                f"L'échéance ({jour.isoformat()}) ne peut pas précéder le "
                f"jour de l'envoi de la facture ({mini.isoformat()})."
            )
        return {"due_in_days": None, "due_at": echeance_du_jour(jour)}
    if "due_in_days" in champs:
        return {"due_in_days": None}
    return {}


def appliquer_a_l_envoi(fa: Facture) -> bool:
    """Échéance d'une facture qui part chez le client (``issued_at`` vient
    d'être posé) : jour de l'envoi + conditions, ou date personnalisée
    ramenée au jour de l'envoi si elle le précède. Retourne True si le
    jour d'échéance a changé."""
    jour = jour_local(fa.issued_at) or aujourd_hui()
    if fa.due_in_days is not None:
        cible = jour + timedelta(days=int(fa.due_in_days))
    elif fa.due_at is not None and jour_echeance(fa.due_at) < jour:
        cible = jour
    else:
        return False
    avant = jour_echeance(fa.due_at)
    fa.due_at = echeance_du_jour(cible)
    return avant != cible


async def corriger_echeances_envoyees(
    db, *, maintenant: Optional[datetime] = None
) -> list[dict[str, Any]]:
    """Factures déjà envoyées (envoyées / en retard) dont l'échéance
    précède le jour de l'envoi : échéance ramenée à ce jour-là. Une
    facture « en retard » qui ne l'est plus selon la nouvelle échéance
    redevient « envoyée » (le cron des rappels la repassera en retard le
    moment venu). Retourne les factures corrigées ; ne commite pas."""
    from sqlalchemy import select

    rows = (
        await db.execute(
            select(Facture)
            .where(
                Facture.status.in_(
                    (FactureStatus.SENT.value, FactureStatus.OVERDUE.value)
                ),
                Facture.issued_at.is_not(None),
                Facture.due_at.is_not(None),
            )
            .order_by(Facture.id)
        )
    ).scalars().all()
    maintenant = maintenant or datetime.now(timezone.utc)
    corrigees: list[dict[str, Any]] = []
    for fa in rows:
        jour = jour_local(fa.issued_at)
        avant = jour_echeance(fa.due_at)
        if jour is None or avant is None or avant >= jour:
            continue
        fa.due_at = echeance_du_jour(jour)
        # Même seuil que le cron des rappels (facture_reminders).
        if (
            fa.status == FactureStatus.OVERDUE.value
            and (maintenant - fa.due_at).days < 1
        ):
            fa.status = FactureStatus.SENT.value
        corrigees.append(
            {
                "id": int(fa.id),
                "reference": fa.reference,
                "avant": avant.isoformat(),
                "apres": jour.isoformat(),
                "qbo": bool(fa.qbo_invoice_id),
            }
        )
    await db.flush()
    return corrigees


async def deduire_conditions(db) -> int:
    """Factures d'avant l'enregistrement des conditions (``due_in_days``
    vide) : conditions déduites de l'écart entre l'échéance et le jour de
    départ — la création pour un brouillon (l'ancien code posait échéance
    = création + conditions), l'envoi pour les autres — quand il
    correspond à une option de la fiche. La fiche affiche alors « Payable
    sur réception », « Net 30 »… et un envoi les recompte. À lancer après
    corriger_echeances_envoyees. Retourne le nombre de factures touchées ;
    ne commite pas."""
    from sqlalchemy import select

    rows = (
        await db.execute(
            select(Facture).where(
                Facture.status != FactureStatus.VOID.value,
                Facture.due_in_days.is_(None),
                Facture.due_at.is_not(None),
            )
        )
    ).scalars().all()
    touches = 0
    for fa in rows:
        if fa.status == FactureStatus.DRAFT.value:
            depart = _utc(fa.created_at).date() if fa.created_at else None
        else:
            depart = jour_local(fa.issued_at)
        jours = conditions_deduites(depart, fa.due_at)
        if jours is not None:
            fa.due_in_days = jours
            touches += 1
    await db.flush()
    return touches


async def corriger_echeances_envoyees_une_fois(db) -> list[dict[str, Any]]:
    """Correction des factures déjà envoyées (et conditions des factures
    existantes), une seule fois (marqueur applied_backfills) : une échéance
    retouchée ensuite à la main n'est jamais réécrasée. Commite."""
    from sqlalchemy import text

    deja = (
        await db.execute(
            text("SELECT 1 FROM applied_backfills WHERE key = :k"),
            {"k": CLE_CORRECTION_ENVOYEES},
        )
    ).first()
    if deja is not None:
        return []
    corrigees = await corriger_echeances_envoyees(db)
    await deduire_conditions(db)
    await db.execute(
        text(
            "INSERT INTO applied_backfills (key) VALUES (:k) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"k": CLE_CORRECTION_ENVOYEES},
    )
    await db.commit()
    return corrigees
