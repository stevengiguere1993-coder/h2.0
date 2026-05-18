"""Téléphonie — modèles SQL Phases 1-3.

Tables :

- **PhoneNumber** : un numéro qu'on possède chez le provider (Twilio
  pour l'instant, autre provider possible plus tard). Porte la stratégie
  de dispatch par défaut (`forward_to_e164` = mobile du user qui répond
  pour cette ligne, en attendant la secrétaire IA de la Phase 2).
- **Call** : une ligne par appel, entrant ou sortant. `provider_sid`
  est l'identifiant côté Twilio (CallSid). On y ajoute `recording_url`,
  `duration_sec`, `status` final, etc. quand Twilio nous notifie via le
  webhook `status_callback`.
- **CallRoute** : règles de routage par numéro (priorité décroissante).
  Match sur pattern `from_e164` (vide = match-tout). Action :
  `forward` / `voicemail` / `ai` (Phase 2). Non utilisé en Phase 1 sauf
  pour stocker la configuration ; le dispatch lit `PhoneNumber.forward_to_e164`.
- **CallTranscript** : transcription + résumé IA d'un appel. Vide en
  Phase 1, rempli en Phase 2 quand la secrétaire IA décroche.
"""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CallDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallStatus(str, Enum):
    # Aligné sur les statuts Twilio :
    # https://www.twilio.com/docs/voice/api/call-resource#call-status-values
    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    BUSY = "busy"
    NO_ANSWER = "no-answer"
    FAILED = "failed"
    CANCELED = "canceled"


class CallRouteAction(str, Enum):
    FORWARD = "forward"        # <Dial> vers forward_to_e164
    VOICEMAIL = "voicemail"    # boîte vocale IA (Phase 3)
    AI = "ai"                  # secrétaire IA (Phase 2)
    REJECT = "reject"          # raccroche poliment


class PhoneNumber(Base):
    """Un numéro qu'on possède chez le provider voix (Twilio)."""

    __tablename__ = "voice_phone_numbers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # E.164 : "+14388002979"
    e164: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="twilio")
    # Twilio IncomingPhoneNumber SID, ex. "PN…"
    provider_sid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    # Libellé interne (ex. "Ligne principale Horizon")
    label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Phase 1 : numéro vers lequel on transfère les appels entrants
    # quand aucune CallRoute ne matche. En Phase 2, la secrétaire IA
    # prend le relais et ce champ devient un fallback.
    forward_to_e164: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Phase 2 : si True, la secrétaire IA décroche et qualifie l'appel
    # avant de transférer. Sinon : transfert direct (comportement Phase 1).
    secretary_mode_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Optionnel : user_id à qui ce numéro « appartient » (statistiques,
    # affichage dans son tableau, etc.). NULL = pool partagé.
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    calls: Mapped[list["Call"]] = relationship(
        back_populates="phone_number",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Call(Base):
    """Une ligne par appel, entrant ou sortant."""

    __tablename__ = "voice_calls"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    phone_number_id: Mapped[int] = mapped_column(
        ForeignKey("voice_phone_numbers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Twilio CallSid, ex. "CA…"
    provider_sid: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)

    from_e164: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    to_e164: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # Si on a forwardé l'appel à un mobile, on le note ici. Permet de
    # savoir « qui a répondu » sans deviner depuis le statut.
    forwarded_to_e164: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    answered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    recording_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    recording_sid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # En Phase 2 : lien vers le user CRM dont on a deviné l'identité
    # depuis le numéro entrant (match contact / prospect / client).
    matched_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Phase 2 — secrétaire IA. Langue détectée au premier tour
    # ("fr-CA" / "en-US"), intent classifié à la fin, infos de rappel
    # capturées si l'appelant ne pouvait pas être transféré directement,
    # action finale prise par la secrétaire.
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="fr-CA")
    intent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    lead_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lead_callback_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    lead_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # contact_requests.id si la secrétaire a créé un lead CRM pour cet
    # appel (intent = callback / business connu hors heures).
    contact_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="SET NULL"), nullable=True
    )

    # Phase 3 — flags de routage pris à la décision initiale. Utiles
    # pour les stats (combien de spam bloqué, combien de VIP sonnés
    # direct, combien de voicemail hors heures).
    was_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    was_vip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    was_voicemail: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Transcription brute Twilio (Phase 3 voicemail) — distincte du
    # transcript IA de Phase 2 qui agrège les tours secrétaire.
    voicemail_transcription: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voicemail_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Phase 4 — lien CRM générique. `entity_type` ∈ {prospection_lead,
    # contact_request, client, contact, locataire} ; `entity_id` = id
    # dans la table concernée. Permet de journaliser un appel sortant
    # dans la bonne fiche, et d'afficher l'historique d'appels d'un
    # prospect/client.
    entity_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # Suggestion de suivi générée par l'IA après l'appel (Phase 4).
    followup_suggestion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Identification CRM de l'appelant entrant — sortie de
    # caller_identity.identify_caller(). Sert au reporting et à
    # afficher le bon badge dans le journal d'appels.
    caller_kind: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)

    phone_number: Mapped[PhoneNumber] = relationship(back_populates="calls")
    transcript: Mapped[Optional["CallTranscript"]] = relationship(
        back_populates="call",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    turns: Mapped[list["CallTurn"]] = relationship(
        back_populates="call",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CallTurn.turn_index",
    )


class CallRoute(Base):
    """Règle de routage par numéro (consultée en Phase 2+).

    Phase 1 : table créée mais inutilisée. Le dispatch utilise simplement
    `PhoneNumber.forward_to_e164`. On la garde pour ne pas avoir à
    migrer le schéma quand la Phase 2 arrive.
    """

    __tablename__ = "voice_call_routes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    phone_number_id: Mapped[int] = mapped_column(
        ForeignKey("voice_phone_numbers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Priorité — plus grand = évalué en premier.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Pattern E.164 ou préfixe ; NULL = match-tout (catch-all).
    from_pattern: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False, default="forward")
    # Selon `action` :
    #   forward   → numéro destinataire (E.164)
    #   voicemail → boîte cible (id ou nom de mailbox)
    #   ai        → identifiant de la persona IA à invoquer
    target: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CallTranscript(Base):
    """Transcription + résumé IA. Vide en Phase 1."""

    __tablename__ = "voice_call_transcripts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    call_id: Mapped[int] = mapped_column(
        ForeignKey("voice_calls.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Intent détecté par l'IA (Phase 2) : "soumission" / "support" /
    # "demarchage" / "rappel" / ...
    intent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    call: Mapped[Call] = relationship(back_populates="transcript")


class CallTurn(Base):
    """Un tour de parole pendant la conversation avec la secrétaire IA.

    `role` = 'user' (ce que l'appelant a dit, transcrit par Twilio) ou
    'assistant' (ce que la secrétaire a répondu). On indexe par
    (call_id, turn_index) pour rejouer l'historique facilement.
    """

    __tablename__ = "voice_call_turns"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    call_id: Mapped[int] = mapped_column(
        ForeignKey("voice_calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user|assistant
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Confidence de la transcription Twilio (0.0-1.0) pour les tours
    # 'user'. NULL pour 'assistant'.
    confidence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    call: Mapped[Call] = relationship(back_populates="turns")


class VoiceFilter(Base):
    """Filtre de routage Phase 3 — blocklist ou whitelist VIP.

    `kind = 'block'` : on rejette l'appel (Reject TwiML) avec une raison
    de busy. `kind = 'vip'` : on sonne direct chez `forward_to_e164`
    sans passer par la secrétaire IA.

    `pattern` = numéro E.164 exact (`+14385551234`) OU préfixe terminant
    par `*` (`+1438*` = tout 438) OU NULL = match-tout (utilisé pour
    une blocklist globale future, par défaut on l'évite). On compare
    avec `from_e164` de l'appel entrant.
    """

    __tablename__ = "voice_filters"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    phone_number_id: Mapped[int] = mapped_column(
        ForeignKey("voice_phone_numbers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # block|vip
    pattern: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VoiceBusinessHours(Base):
    """Heures d'ouverture Phase 3 (par numéro, par jour de semaine).

    `day_of_week` : 0 = lundi … 6 = dimanche (convention ISO Python
    `datetime.weekday()`). Une ligne = une plage horaire ; on peut en
    avoir plusieurs par jour (ex. 9h-12h + 13h-17h) en mettant deux
    lignes avec le même `day_of_week`.

    Si **aucune** ligne n'existe pour un PhoneNumber : ouvert 24/7
    (rétro-compat Phase 1/2). Sinon : ouvert seulement quand l'heure
    courante (`America/Montreal`) tombe dans au moins une plage du jour.
    """

    __tablename__ = "voice_business_hours"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    phone_number_id: Mapped[int] = mapped_column(
        ForeignKey("voice_phone_numbers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    open_time: Mapped[time] = mapped_column(Time, nullable=False)
    close_time: Mapped[time] = mapped_column(Time, nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="America/Montreal"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VoiceCallerIntel(Base):
    """Renseignements et compteurs anti-spam par numéro appelant.

    Une ligne par `from_e164` jamais vu. Sert à :
    - Cacher le résultat Twilio Lookup (`line_type`, `caller_name`) 30j
    - Compter les raccrochages-honeypot (<2 sec après greeting)
    - Stocker un ban manuel ou automatique (`banned_until`)
    - Mémoriser le dernier statut STIR/SHAKEN reçu

    Les compteurs glissants (calls/h, calls/jour) sont calculés à la
    volée depuis `voice_calls` (index sur `from_e164` + `started_at`).
    """

    __tablename__ = "voice_caller_intel"

    from_e164: Mapped[str] = mapped_column(
        String(20), primary_key=True, index=True
    )
    line_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    caller_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_lookup_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    spam_hangup_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    banned_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_verstat: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class VoiceClientPresence(Base):
    """Présence d'un user sur le Voice SDK (browser h2.0 ouvert).

    Le frontend POST `/voice/presence/ping` toutes les 30 sec quand le
    portail est ouvert. On considère qu'un user est "online et joignable"
    si `last_seen_at > now - 60s` ET `is_accepting_calls=True`.

    Au moment d'un transfert secrétaire → utilisateur humain, on liste
    les users online et on les ring tous via Twilio Voice SDK
    (`<Dial><Client>user_X</Client>...</Dial>`). Premier qui répond
    gagne. Si personne ne répond en 15 sec, fallback `forward_to_e164`.
    """

    __tablename__ = "voice_client_presence"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    is_accepting_calls: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )


class VoiceUsageDaily(Base):
    """Compteur de coût journalier — pour le cost cap automatique.

    Incrementé à chaque appel terminé (depuis le webhook /twilio/status).
    Si `cents_spent > DAILY_COST_CAP_CENTS` (env, défaut 500 = 5 $), on
    refuse les nouveaux appels en répondant un voicemail-only pour la
    journée. Auto-reset au changement de date (clé = `usage_date`).
    """

    __tablename__ = "voice_usage_daily"

    usage_date: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD
    cents_spent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calls_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    spam_blocked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
