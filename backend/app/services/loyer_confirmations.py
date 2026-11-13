"""Confirmation de paiement de loyer envoyée au locataire, LA NUIT.

Steven (2026-11-13, point 14 ; bug 206 « envoyer aux locataires
confirmation de reçu de paiement ») : « lorsque nous avons enregistré un
paiement et qu'il n'y a pas de correctif au courant de la journée, dans
la nuit, envoyer une confirmation de paiement au locataire (si le
locataire n'a pas de courriel, envoyer un message texte) ».

Fonctionnement :

- une boucle démarrée avec l'application (comme le brief du matin : les
  crons Render ne tournent pas) passe toutes les 10 minutes et, une fois
  par nuit après l'heure réglée (défaut 2 h, Montréal), confirme les
  versements SAISIS LA VEILLE ;
- comme l'envoi part la nuit, il reflète l'état FINAL de la journée : un
  versement corrigé dans la journée est confirmé à son montant corrigé,
  un versement supprimé n'est confirmé à personne ;
- un seul message par bail (deux dépôts le même jour = un courriel qui
  liste les deux) ;
- courriel si le locataire en a un (porte unique ``envoyer_au_locataire`` :
  profil d'expéditeur, journal Communications, fil de la fiche), sinon
  texto à son cellulaire, sinon rien (« aucun ») ;
- chaque versement confirmé est marqué (``confirmation_envoyee_le``,
  ``confirmation_canal``) : jamais deux confirmations pour le même.

Garde-fous : seuls les versements saisis par une personne (``cree_par``)
et reçus dans les ``JOURS_MAX_RECUL`` jours précédant la saisie sont
confirmés (rattraper un vieux mois en novembre n'envoie pas « reçu le
1er juillet ») ; rien d'antérieur à ``ACTIF_DEPUIS`` (mise en service) ;
baux parallèles et immeubles en gestion externe exclus ; aucun texto hors
production (le staging redirige les courriels, pas les textos).
Automatisation « loyer_confirmations » (Paramètres → Automatisations) :
se coupe d'un clic.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

JOB = "loyer_confirmations"
FUSEAU = ZoneInfo("America/Toronto")
#: Mise en service : aucun versement saisi avant ce jour n'est confirmé.
ACTIF_DEPUIS = date(2026, 11, 13)
#: Nuits de rattrapage (application arrêtée une nuit, envoi échoué).
JOURS_RATTRAPAGE = 3
#: Un versement « reçu » plus de N jours avant sa saisie est un
#: rattrapage d'historique : pas de confirmation.
JOURS_MAX_RECUL = 10
HEURE_DEFAUT = 2
_PREMIER_PASSAGE_S = 120.0
_INTERVALLE_S = 600.0
_MIN_INTERVALLE_S = 20 * 3600

_MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
    "septembre", "octobre", "novembre", "décembre",
)
_MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
)


def argent(n: float) -> str:
    """1234.5 → « 1 234,50 $ »."""
    s = f"{float(n):,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} $"


def mois_fr(d: date) -> str:
    return f"{_MOIS[d.month - 1]} {d.year}"


def jour_fr(d: date) -> str:
    return f"{d.day}{'er' if d.day == 1 else ''} {_MOIS[d.month - 1]} {d.year}"


def _echapper(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fenetre(now_local: datetime) -> tuple[datetime, datetime]:
    """Versements à confirmer : saisis entre le début de J−3 (rattrapage,
    jamais avant la mise en service) et le début d'AUJOURD'HUI, à l'heure
    de Montréal. Bornes en UTC."""
    minuit = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    debut = minuit - timedelta(days=JOURS_RATTRAPAGE)
    plancher = datetime(
        ACTIF_DEPUIS.year, ACTIF_DEPUIS.month, ACTIF_DEPUIS.day, tzinfo=FUSEAU
    )
    debut = max(debut, plancher)
    return debut.astimezone(timezone.utc), minuit.astimezone(timezone.utc)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo is not None else d.replace(tzinfo=timezone.utc)


def versement_admissible(p, debut_utc: datetime, fin_utc: datetime) -> bool:
    """Le versement se confirme-t-il cette nuit ?"""
    if getattr(p, "confirmation_envoyee_le", None) is not None:
        return False
    if p.paye_le is None or float(p.montant or 0) <= 0.005:
        return False
    if not (getattr(p, "cree_par", None) or "").strip():
        return False
    if p.created_at is None:
        return False
    cree = _aware(p.created_at)
    if not (debut_utc <= cree < fin_utc):
        return False
    saisi_le = cree.astimezone(FUSEAU).date()
    return p.paye_le >= saisi_le - timedelta(days=JOURS_MAX_RECUL)


def sujet(versements: list) -> str:
    mois = sorted({p.mois_couvert for p in versements})
    if len(mois) == 1:
        return f"Confirmation de paiement — loyer de {mois_fr(mois[0])}"
    return "Confirmation de paiement de loyer"


def corps_html(nom: str, adresse: str, versements: list) -> str:
    total = round(sum(float(p.montant or 0) for p in versements), 2)
    lignes = "".join(
        f"<li><strong>{_echapper(argent(float(p.montant)))}</strong> reçu le "
        f"{_echapper(jour_fr(p.paye_le))} — loyer de "
        f"{_echapper(mois_fr(p.mois_couvert))}</li>"
        for p in versements
    )
    total_html = (
        f"<p>Total reçu : <strong>{_echapper(argent(total))}</strong></p>"
        if len(versements) > 1
        else ""
    )
    mois_en = ", ".join(
        f"{_MONTHS[m.month - 1]} {m.year}"
        for m in sorted({p.mois_couvert for p in versements})
    )
    return (
        f"<p>Bonjour {_echapper(nom)},</p>"
        "<p>Nous confirmons avoir bien reçu votre paiement de loyer"
        f"{' pour le ' + _echapper(adresse) if adresse else ''} :</p>"
        f"<ul>{lignes}</ul>{total_html}"
        "<p>Merci! Si vous constatez une erreur, répondez simplement à ce "
        "courriel.</p>"
        "<p style=\"color:#555555;font-size:13px\">English — This confirms we "
        f"received your rent payment of ${total:,.2f} ({_echapper(mois_en)}). "
        "Thank you! If anything looks wrong, simply reply to this email.</p>"
    )


def corps_sms(adresse: str, versements: list) -> str:
    total = round(sum(float(p.montant or 0) for p in versements), 2)
    mois = ", ".join(mois_fr(m) for m in sorted({p.mois_couvert for p in versements}))
    lieu = f" ({adresse})" if adresse else ""
    return (
        f"Confirmation : nous avons bien reçu votre paiement de loyer de "
        f"{argent(total)} pour {mois}{lieu}. Merci! / Rent payment received, "
        "thank you."
    ).replace(" ", " ")


def _e164(raw: Optional[str]) -> str:
    """Cellulaire nord-américain → +1XXXXXXXXXX ('' si inutilisable)."""
    s = (raw or "").strip()
    chiffres = "".join(c for c in s if c.isdigit())
    if s.startswith("+"):
        return f"+{chiffres}" if len(chiffres) >= 10 else ""
    if len(chiffres) == 10:
        return f"+1{chiffres}"
    if len(chiffres) == 11 and chiffres.startswith("1"):
        return f"+{chiffres}"
    return ""


async def _envoyer_sms(db: AsyncSession, numero: str, texte: str, locataire_id: int) -> bool:
    """Texto par la ligne principale (Twilio). Faux si rien n'est parti."""
    from app.core.config import settings

    if not settings.is_production:
        # Le staging redirige les courriels vers une boîte de test, pas
        # les textos : aucun vrai locataire ne doit en recevoir d'ici.
        return False
    from app.integrations.voice import get_voice_provider
    from app.models.voice import PhoneNumber, VoiceSms

    pn = (
        await db.execute(
            select(PhoneNumber)
            .where(PhoneNumber.active.is_(True))
            .order_by(PhoneNumber.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if pn is None:
        return False
    provider = get_voice_provider()
    data = await provider.send_sms(from_e164=pn.e164, to_e164=numero, body=texte)
    db.add(
        VoiceSms(
            phone_number_id=pn.id,
            provider_sid=str(data.get("sid") or ""),
            direction="outbound",
            status=str(data.get("status") or "queued"),
            from_e164=pn.e164,
            to_e164=numero,
            body=texte,
            sent_at=datetime.now(timezone.utc),
            caller_kind="locataire",
            entity_type="locataire",
            entity_id=locataire_id,
        )
    )
    return True


async def envoyer_confirmations(
    db: AsyncSession, now_local: Optional[datetime] = None
) -> dict[str, Any]:
    """Confirme les versements de la veille. Un commit par bail : un envoi
    réussi reste marqué même si le suivant échoue."""
    from app.integrations.email_graph import get_mailer
    from app.models.immobilier import (
        Bail,
        Immeuble,
        Locataire,
        LocataireCommunication,
        Logement,
        PaiementLoyer,
    )
    from app.services.appointment_mail import is_deliverable_email
    from app.services.locatif_mail import envoyer_au_locataire

    now_local = now_local or datetime.now(FUSEAU)
    debut_utc, fin_utc = fenetre(now_local)
    rapport: dict[str, Any] = {
        "courriels": 0, "textos": 0, "sans_coordonnees": 0, "echecs": 0,
        "versements": 0,
    }
    if fin_utc <= debut_utc:
        return rapport

    candidats = (
        await db.execute(
            select(PaiementLoyer)
            .where(
                PaiementLoyer.confirmation_envoyee_le.is_(None),
                PaiementLoyer.created_at >= debut_utc - timedelta(days=1),
            )
            .order_by(PaiementLoyer.bail_id, PaiementLoyer.paye_le, PaiementLoyer.id)
        )
    ).scalars().all()
    par_bail: dict[int, list] = {}
    for p in candidats:
        if versement_admissible(p, debut_utc, fin_utc):
            par_bail.setdefault(p.bail_id, []).append(p)
    if not par_bail:
        return rapport

    mailer_pret = bool(getattr(get_mailer(), "ready", False))
    for bail_id, versements in par_bail.items():
        try:
            bail = await db.get(Bail, bail_id)
            if bail is None or (getattr(bail, "categorie", None) or "standard") != "standard":
                continue
            loc = await db.get(Locataire, bail.locataire_id)
            lg = await db.get(Logement, bail.logement_id)
            imm = await db.get(Immeuble, lg.immeuble_id) if lg is not None else None
            if loc is None or imm is None or bool(getattr(imm, "gestion_externe", False)):
                continue
            adresse = imm.name or ""
            if lg is not None and lg.numero:
                adresse = f"{adresse}, log. {lg.numero}" if adresse else f"log. {lg.numero}"
            total = round(sum(float(p.montant or 0) for p in versements), 2)
            resume = (
                f"Confirmation de paiement envoyée automatiquement : "
                f"{argent(total)} ("
                + ", ".join(mois_fr(m) for m in sorted({p.mois_couvert for p in versements}))
                + ")"
            )
            canal: Optional[str] = None
            numero = _e164(loc.phone)
            if is_deliverable_email(loc.email):
                if not mailer_pret:
                    # Courriel non configuré : on réessaiera une autre nuit.
                    rapport["echecs"] += 1
                    continue
                await envoyer_au_locataire(
                    db,
                    destinataires=[loc.email],
                    sujet=sujet(versements),
                    corps_html=corps_html(loc.full_name or "", adresse, versements),
                    type_envoi="confirmation_paiement",
                    locataire_id=loc.id,
                    locataire_nom=loc.full_name,
                    bail_id=bail.id,
                    immeuble_id=imm.id,
                    immeuble_nom=imm.name,
                    auteur_email="Kratos (automatique)",
                    resume_fiche=f"{resume} (à {loc.email})",
                )
                canal = "courriel"
                rapport["courriels"] += 1
            elif numero and await _envoyer_sms(
                db, numero, corps_sms(adresse, versements), loc.id
            ):
                db.add(
                    LocataireCommunication(
                        locataire_id=loc.id,
                        kind="sms",
                        contenu=f"{resume} (texto au {numero})"[:2000],
                        auteur="Kratos (automatique)",
                    )
                )
                canal = "sms"
                rapport["textos"] += 1
            else:
                canal = "aucun"
                rapport["sans_coordonnees"] += 1
            quand = datetime.now(timezone.utc)
            for p in versements:
                p.confirmation_envoyee_le = quand
                p.confirmation_canal = canal
            rapport["versements"] += len(versements)
            await db.commit()
        except Exception:  # noqa: BLE001 — un bail en échec n'arrête pas les autres
            log.exception("Confirmation de paiement échouée (bail %s)", bail_id)
            rapport["echecs"] += 1
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
    return rapport


def est_du(now_local: datetime, heure: int) -> bool:
    """La nuit : à partir de l'heure réglée et jusqu'à 7 h (un démarrage
    en plein jour n'envoie rien — on attend la nuit suivante)."""
    return heure <= now_local.hour < max(heure + 1, 7)


async def envoyer_si_du(now_local: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    from app.db.session import AsyncSessionLocal
    from app.services.automation_state import get_automation_int, is_automation_enabled
    from app.services.cron_guard import claim_cron_run

    if not await is_automation_enabled(JOB):
        return None
    now_local = now_local or datetime.now(FUSEAU)
    heure = await get_automation_int(JOB, "heure", HEURE_DEFAUT)
    if not est_du(now_local, min(heure, 6)):
        return None
    async with AsyncSessionLocal() as db:
        if not await claim_cron_run(db, JOB, _MIN_INTERVALLE_S):
            return None
        rapport = await envoyer_confirmations(db, now_local)
        await db.commit()
        log.info("confirmations de paiement : %s", rapport)
        return rapport


async def boucle() -> None:
    """Boucle de fond démarrée avec l'app. Jamais sous pytest."""
    import sys

    if "pytest" in sys.modules:
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
            log.warning("Boucle confirmations de paiement : itération échouée", exc_info=True)


__all__ = [
    "ACTIF_DEPUIS",
    "JOB",
    "FUSEAU",
    "argent",
    "boucle",
    "corps_html",
    "corps_sms",
    "envoyer_confirmations",
    "envoyer_si_du",
    "est_du",
    "fenetre",
    "sujet",
    "versement_admissible",
]
