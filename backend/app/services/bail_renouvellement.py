"""Workflow de renouvellement automatique des baux résidentiels.

Au Québec, le bail résidentiel se renouvelle automatiquement à son
échéance, sauf avis contraire. Les délais légaux pour aviser le locataire
d'une **modification** (typiquement hausse de loyer) sont :

- Bail >= 12 mois : 3 à 6 mois avant l'échéance.
- Bail < 12 mois : 1 à 2 mois avant l'échéance.
- Bail à durée indéterminée : 1 à 2 mois avant la prise d'effet.

Stratégie :
- Cron quotidien scanne les baux ``actif`` dont la fin tombe dans une
  fenêtre 4-6 mois → crée un ``BailRenouvellement`` ``propose`` si pas
  déjà existant pour ce cycle, génère le PDF d'avis de modification,
  et l'envoie par courriel via Microsoft Graph (si configuré + locataire
  a un courriel). Stamp ``avis_envoye_le``.
- Idempotent : on regarde s'il existe déjà un renouvellement pour ce
  bail dont ``avis_envoye_le`` >= (date_fin - 6 mois). Si oui, skip.
- L'utilisateur peut aussi déclencher manuellement l'envoi pour un bail
  donné via l'endpoint ``POST /immobilier/baux/{id}/envoyer-renouvellement``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import EmailAttachment, GraphMailer
from app.models.immobilier import (
    Bail,
    BailRenouvellement,
    BailRenouvellementStatus,
    BailStatus,
    ImmeubleOwnership,
    Immeuble,
    Locataire,
    Logement,
)
from app.models.entreprise import Entreprise
from app.services.tal_forms import TalContext, generate_tal_pdf


log = logging.getLogger(__name__)


# Hausse par défaut suggérée si on ne peut pas la calculer (utilisé
# quand l'utilisateur déclenche depuis l'UI sans préciser).
DEFAULT_SUGGESTED_HIKE_PCT = 0.0  # neutre — l'utilisateur saisit


@dataclass
class RenouvellementResult:
    bails_scanned: int = 0
    avis_crees: int = 0
    courriels_envoyes: int = 0
    skipped: int = 0
    errors: List[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


async def _build_tal_context_for_bail(
    db: AsyncSession,
    bail: Bail,
    nouveau_loyer: Optional[float],
    nouvelle_date_debut: Optional[date],
    nouvelle_date_fin: Optional[date],
) -> TalContext:
    """Hydrate un TalContext à partir des objets liés au bail."""
    logement = await db.get(Logement, bail.logement_id)
    immeuble = (
        await db.get(Immeuble, logement.immeuble_id) if logement else None
    )
    locataire = await db.get(Locataire, bail.locataire_id)

    locateur_nom = None
    if immeuble is not None:
        # Premier propriétaire trouvé (cas multi-entreprise → on prend le
        # premier ; à raffiner si besoin avec un ordering metier).
        ownership = (
            await db.execute(
                select(ImmeubleOwnership).where(
                    ImmeubleOwnership.immeuble_id == immeuble.id
                )
            )
        ).scalars().first()
        if ownership is not None:
            ent = await db.get(Entreprise, ownership.entreprise_id)
            if ent is not None:
                locateur_nom = ent.name

    return TalContext(
        locateur_nom=locateur_nom,
        locataire_nom=locataire.full_name if locataire else None,
        locataire_email=locataire.email if locataire else None,
        logement_adresse=immeuble.address if immeuble else None,
        logement_numero=logement.numero if logement else None,
        logement_ville=immeuble.city if immeuble else None,
        bail_date_debut=bail.date_debut,
        bail_date_fin=bail.date_fin,
        bail_loyer_mensuel=float(bail.loyer_mensuel) if bail.loyer_mensuel else None,
        bail_chauffage_inclus=bool(bail.chauffage_inclus),
        bail_eau_chaude_inclus=bool(bail.eau_chaude_inclus),
        bail_electricite_inclus=bool(bail.electricite_inclus),
        bail_internet_inclus=bool(bail.internet_inclus),
        nouveau_loyer=nouveau_loyer,
        nouvelle_date_debut=nouvelle_date_debut or (
            bail.date_fin + timedelta(days=1) if bail.date_fin else None
        ),
        nouvelle_date_fin=nouvelle_date_fin,
        date_emission=date.today(),
    )


async def _existing_renouvellement_active(
    db: AsyncSession, bail: Bail
) -> Optional[BailRenouvellement]:
    """Renouvellement déjà créé pour le cycle courant ?"""
    cutoff = bail.date_fin - timedelta(days=200) if bail.date_fin else None
    q = select(BailRenouvellement).where(
        BailRenouvellement.bail_id == bail.id
    )
    if cutoff:
        q = q.where(BailRenouvellement.avis_envoye_le >= cutoff)
    return (
        await db.execute(q.order_by(BailRenouvellement.avis_envoye_le.desc()))
    ).scalars().first()


async def send_renouvellement_for_bail(
    db: AsyncSession,
    bail: Bail,
    nouveau_loyer: Optional[float] = None,
    nouvelle_date_debut: Optional[date] = None,
    nouvelle_date_fin: Optional[date] = None,
    motif: Optional[str] = None,
    force: bool = False,
    request_read_receipt: bool = False,
    bcc_to_sender: bool = True,
) -> tuple[BailRenouvellement, bool]:
    """Crée le renouvellement (si nécessaire) et envoie le PDF par courriel.

    Returns: (renouvellement, courriel_envoye_bool).
    Idempotent : si un renouvellement actif existe déjà pour ce cycle et
    ``force=False``, on ne le redouble pas — on le retourne tel quel.
    """
    now_utc = datetime.now(timezone.utc)
    today = date.today()

    existing = await _existing_renouvellement_active(db, bail)
    if existing is not None and not force:
        return existing, False

    # Crée le renouvellement
    obj = BailRenouvellement(
        bail_id=bail.id,
        avis_envoye_le=today,
        nouveau_loyer=nouveau_loyer,
        nouvelle_date_debut=nouvelle_date_debut
        or (bail.date_fin + timedelta(days=1) if bail.date_fin else None),
        nouvelle_date_fin=nouvelle_date_fin,
        status=BailRenouvellementStatus.PROPOSE.value,
        notes=motif,
    )
    obj.created_at = now_utc
    obj.updated_at = now_utc
    db.add(obj)
    await db.flush()

    # Génère le PDF + envoie email si possible
    sent = False
    ctx = await _build_tal_context_for_bail(
        db, bail, nouveau_loyer, obj.nouvelle_date_debut, nouvelle_date_fin
    )
    if motif:
        ctx.motif_modification = motif

    if ctx.locataire_email:
        mailer = GraphMailer()
        if mailer.ready:
            try:
                pdf_bytes = generate_tal_pdf("avis_modification", ctx)
                subject = (
                    f"Avis de modification du bail — {ctx.logement_adresse or ''}"
                ).strip(" —")
                body_html = _render_email_body(ctx)
                # « Envoi certifié » : BCC à l'expéditeur pour archive +
                # demande d'accusé de lecture (read receipt) Outlook.
                bcc = [mailer.sender] if bcc_to_sender and mailer.sender else None
                await mailer.send(
                    to=[ctx.locataire_email],
                    subject=subject,
                    html_body=body_html,
                    bcc=bcc,
                    request_read_receipt=request_read_receipt,
                    attachments=[
                        EmailAttachment(
                            name="avis-modification-bail.pdf",
                            content_bytes=pdf_bytes,
                            content_type="application/pdf",
                        )
                    ],
                )
                sent = True
            except Exception:  # noqa: BLE001
                log.exception(
                    "Échec envoi email renouvellement bail %s", bail.id
                )

    return obj, sent


def _render_email_body(ctx: TalContext) -> str:
    nom = ctx.locataire_nom or "Madame, Monsieur,"
    adresse = ctx.logement_adresse or "votre logement"
    return f"""
    <p>Bonjour {nom},</p>
    <p>Vous trouverez ci-joint l'avis officiel de modification de votre bail
    pour le logement situé au <b>{adresse}</b>.</p>
    <p>Vous disposez d'un délai d'un (1) mois à compter de la réception du
    présent avis pour répondre. À défaut de réponse, vous serez réputé avoir
    accepté les modifications proposées.</p>
    <p>N'hésitez pas à nous contacter pour toute question.</p>
    <p>Cordialement,<br/>{ctx.locateur_nom or 'Le locateur'}</p>
    """.strip()


async def scan_and_send_due_renouvellements(
    db: AsyncSession,
    today: date | None = None,
    fenetre_min_jours: int = 120,  # ~4 mois
    fenetre_max_jours: int = 180,  # ~6 mois
) -> RenouvellementResult:
    """Scan quotidien : envoie les avis pour les baux dont la fin tombe
    dans la fenêtre cible (4-6 mois par défaut)."""
    today = today or date.today()
    cutoff_min = today + timedelta(days=fenetre_min_jours)
    cutoff_max = today + timedelta(days=fenetre_max_jours)

    bails = (
        await db.execute(
            select(Bail).where(
                and_(
                    Bail.status == BailStatus.ACTIF.value,
                    Bail.date_fin >= cutoff_min,
                    Bail.date_fin <= cutoff_max,
                )
            )
        )
    ).scalars().all()

    res = RenouvellementResult(bails_scanned=len(bails))

    for bail in bails:
        try:
            existing = await _existing_renouvellement_active(db, bail)
            if existing is not None:
                res.skipped += 1
                continue
            obj, sent = await send_renouvellement_for_bail(db, bail)
            res.avis_crees += 1
            if sent:
                res.courriels_envoyes += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("Renouvellement bail %s failed", bail.id)
            assert res.errors is not None
            res.errors.append(f"bail {bail.id}: {exc!s}"[:240])

    if res.avis_crees:
        await db.commit()

    return res
