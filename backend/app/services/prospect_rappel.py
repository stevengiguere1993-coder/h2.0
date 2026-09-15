"""Prospect sans réponse à un appel SORTANT → « À rappeler ».

Retour 2026-09-12, point 2 : quand on tente d'appeler un prospect et
qu'il ne répond pas,

1. sa fiche passe dans la colonne « À rappeler » du pipeline (statut
   ``a_rappeler``) — seulement s'il est encore en amont (new /
   contacted / a_rappeler : on ne fait jamais reculer un dossier
   rendu au RDV ou plus loin) ;
2. un SMS part à son numéro, et un courriel s'il en a un :
   - 1ʳᵉ tentative : « nous avons tenté de vous joindre, nous vous
     rappellerons » ;
   - 2ᵉ tentative et suivantes : « nous attendons votre retour
     d'appel » ;
3. une trace FollowUp (outcome ``no_answer``) journalise le tout —
   c'est aussi elle qui compte les tentatives.

Déclenché par le webhook Twilio ``outbound-dial-result`` (résultat du
<Dial> vers la cible). Best-effort : ne lève jamais.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

#: Statuts encore « en amont » — seuls eux basculent vers À rappeler.
_STATUTS_AMONT = ("new", "contacted", "a_rappeler")


def _sms_body(attempt: int, callback_number: str) -> str:
    if attempt <= 1:
        return (
            "Horizon Services Immobiliers : nous avons tenté de vous "
            "joindre au sujet de votre demande. Nous vous rappellerons "
            "sous peu. Vous pouvez aussi répondre à ce message."
        )
    return (
        "Horizon Services Immobiliers : nous avons tenté de vous "
        "joindre à nouveau, sans succès. Nous attendons votre retour "
        f"d'appel au {callback_number}. Merci !"
    )


def _email_body(attempt: int, name: str, callback_number: str) -> tuple[str, str]:
    """(sujet, corps HTML) — vouvoiement, selon la tentative."""
    prenom = (name or "").strip().split(" ")[0] or ""
    salutation = f"Bonjour {prenom}," if prenom else "Bonjour,"
    if attempt <= 1:
        sujet = "Nous avons tenté de vous joindre — Horizon Services Immobiliers"
        corps = (
            f"<p>{salutation}</p>"
            "<p>Nous avons tenté de vous joindre par téléphone au sujet "
            "de votre demande, sans succès.</p>"
            "<p>Nous tenterons de vous rappeler sous peu. Vous pouvez "
            "aussi répondre directement à ce courriel ou nous appeler "
            f"au {callback_number}.</p>"
        )
    else:
        sujet = "Nous attendons votre retour d'appel — Horizon Services Immobiliers"
        corps = (
            f"<p>{salutation}</p>"
            "<p>Nous avons tenté de vous joindre à nouveau par "
            "téléphone, sans succès.</p>"
            "<p>Nous attendons votre retour d'appel au "
            f"{callback_number} — ou répondez simplement à ce courriel "
            "pour nous indiquer le meilleur moment pour vous joindre.</p>"
        )
    corps += (
        "<p style='margin-top:24px;color:#555;font-size:12px'>"
        "Horizon Services Immobiliers<br>RBQ 5868-5991-01 — "
        "info@immohorizon.com</p>"
    )
    return sujet, (
        "<div style='font-family:Helvetica,Arial,sans-serif;color:#111;"
        f"line-height:1.5;max-width:640px'>{corps}</div>"
    )


async def handle_missed_prospect_call(
    db: AsyncSession,
    *,
    target_e164: str,
    call=None,
) -> bool:
    """Traite un appel sortant SANS RÉPONSE vers ``target_e164``.
    Renvoie True si la cible était un prospect (traitement fait)."""
    try:
        from app.models.contact_request import ContactRequest
        from app.models.follow_up import FollowUp

        prospect: Optional[ContactRequest] = None
        if (
            call is not None
            and getattr(call, "entity_type", None) == "contact_request"
            and getattr(call, "entity_id", None)
        ):
            prospect = await db.get(ContactRequest, int(call.entity_id))
        if prospect is None and (target_e164 or "").startswith("+"):
            from app.integrations.voice.caller_identity import (
                CallerKind,
                identify_caller,
            )

            ident = await identify_caller(db, target_e164)
            if ident.kind == CallerKind.LEAD_WEB and ident.entity_id:
                prospect = await db.get(
                    ContactRequest, int(ident.entity_id)
                )
        if prospect is None:
            return False

        # 1. Colonne « À rappeler » — jamais de recul d'un dossier avancé.
        if (prospect.status or "") in _STATUTS_AMONT:
            prospect.status = "a_rappeler"

        # 2. Tentative n° = traces « no_answer » déjà posées + 1.
        prior = (
            await db.execute(
                select(func.count(FollowUp.id)).where(
                    FollowUp.subject_type == "prospect",
                    FollowUp.subject_id == prospect.id,
                    FollowUp.outcome == "no_answer",
                )
            )
        ).scalar_one()
        attempt = int(prior or 0) + 1

        # Numéro à rappeler = notre ligne principale.
        callback = ""
        try:
            from app.models.voice import PhoneNumber

            pn = (
                await db.execute(
                    select(PhoneNumber)
                    .where(PhoneNumber.active.is_(True))
                    .order_by(PhoneNumber.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            callback = pn.e164 if pn else ""
        except Exception:  # noqa: BLE001
            pn = None

        # 3. SMS au prospect (best-effort).
        sms_ok = False
        if pn is not None and (target_e164 or "").startswith("+"):
            try:
                from app.api.v1.endpoints.voice import _twilio_provider
                from app.models.voice import VoiceSms

                provider = _twilio_provider()
                data = await provider.send_sms(
                    from_e164=pn.e164,
                    to_e164=target_e164,
                    body=_sms_body(attempt, callback or pn.e164),
                )
                db.add(
                    VoiceSms(
                        phone_number_id=pn.id,
                        provider_sid=str(data.get("sid") or ""),
                        direction="outbound",
                        status=str(data.get("status") or "queued"),
                        from_e164=pn.e164,
                        to_e164=target_e164,
                        body=_sms_body(attempt, callback or pn.e164),
                        sent_at=datetime.now(timezone.utc),
                        caller_kind="lead_web",
                        entity_type="contact_request",
                        entity_id=prospect.id,
                    )
                )
                sms_ok = True
            except Exception:  # noqa: BLE001
                log.exception(
                    "SMS « à rappeler » échoué (prospect %s)", prospect.id
                )

        # 4. Courriel si on en a un de livrable.
        email_ok = False
        try:
            from app.integrations.email_graph import get_mailer
            from app.services.appointment_mail import is_deliverable_email

            mailer = get_mailer()
            if mailer.ready and is_deliverable_email(prospect.email):
                sujet, corps = _email_body(
                    attempt, prospect.name or "", callback or ""
                )
                await mailer.send(
                    to=[prospect.email],
                    subject=sujet,
                    html_body=corps,
                    reply_to=mailer.sender,
                )
                email_ok = True
        except Exception:  # noqa: BLE001
            log.exception(
                "Courriel « à rappeler » échoué (prospect %s)", prospect.id
            )

        # 5. Trace au journal de suivi (sert aussi de compteur).
        envois = []
        if sms_ok:
            envois.append("SMS")
        if email_ok:
            envois.append("courriel")
        db.add(
            FollowUp(
                subject_type="prospect",
                subject_id=prospect.id,
                kind="auto",
                direction="outbound",
                outcome="no_answer",
                notes=(
                    f"Appel sans réponse (tentative {attempt}) — "
                    + (
                        " + ".join(envois) + " envoyé"
                        + ("s" if len(envois) > 1 else "")
                        if envois
                        else "aucun envoi (ni SMS ni courriel possibles)"
                    )
                    + ". Prospect classé « À rappeler »."
                ),
                overdue_notified=True,
            )
        )
        await db.flush()
        log.info(
            "Prospect %s → À rappeler (tentative %s, sms=%s, email=%s)",
            prospect.id, attempt, sms_ok, email_ok,
        )
        return True
    except Exception:  # noqa: BLE001 — jamais bloquant pour le webhook
        log.exception("handle_missed_prospect_call a échoué")
        return False
