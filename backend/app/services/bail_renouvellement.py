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
import math
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import EmailAttachment, GraphMailer
from app.models.immobilier import (
    Bail,
    BailRenouvellement,
    BailRenouvellementStatus,
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


def arrondir_loyer(montant: float) -> float:
    """Nouveau loyer TOUJOURS arrondi au dollar SUPÉRIEUR (retour Phil
    2026-07-30 : 1 044,26 $ → 1 045 $). L'epsilon absorbe le bruit des
    flottants (1050.0000001 ne devient pas 1051)."""
    return float(math.ceil(round(montant, 2) - 1e-9))


def fin_reconduite(
    date_debut: Optional[date], date_fin: date
) -> date:
    """Fin de la période RECONDUITE (art. 1941 C.c.Q.) : un bail de
    12 mois se reconduit pour 12 mois → même jour un an plus tard, peu
    importe que le bail soit du 1er juillet au 30 juin ou non ; un bail
    plus court se reconduit pour la MÊME durée."""
    duree = (date_fin - date_debut).days if date_debut else 365
    if duree >= 360:
        try:
            return date_fin.replace(year=date_fin.year + 1)
        except ValueError:  # 29 février
            return date_fin.replace(year=date_fin.year + 1, day=28)
    return date_fin + timedelta(days=duree + 1)


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
        # Adresse du bureau (mandataire Horizon) — même adresse pour
        # toutes les compagnies de Phil.
        locateur_adresse="158 rue Maurice, Saint-Rémi (Québec) J0L 2L0",
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


def est_cycle_courant(
    r: BailRenouvellement, date_fin: Optional[date], today: date
) -> bool:
    """Un cycle est COURANT tant que le renouvellement qu'il vise n'est
    pas commencé (``nouvelle_date_debut`` future). Repli sur l'ancienne
    borne (avis dans les ~6,5 mois précédant la fin) pour les vieux
    cycles sans dates. Fix « pas jaune » 2026-07-31 : un avis envoyé
    TÔT (ex. bail reconduit jusqu'en 2028) restait invisible."""
    if r.status == "reconduit":
        return False
    if r.status in ("propose", "en_negociation"):
        # Avis envoyé, réponse attendue : TOUJOURS courant — même si la
        # période visée commence aujourd'hui ou est passée (retour Phil
        # 2026-07-31 : avis 2026→2027 sur bail 2028 restait gris).
        return True
    if (
        r.status in ("accepte", "repute_accepte")
        and r.applique_le is None
    ):
        # Accepté mais pas encore reporté sur le bail : le cycle reste
        # courant jusqu'à l'application (lazy, à la consultation) —
        # sinon un cycle dont la date effective vient de passer ne
        # serait JAMAIS appliqué.
        return True
    if r.nouvelle_date_debut is not None:
        return r.nouvelle_date_debut > today
    if date_fin is None:
        return True
    return r.avis_envoye_le >= date_fin - timedelta(days=200)


async def _existing_renouvellement_active(
    db: AsyncSession, bail: Bail
) -> Optional[BailRenouvellement]:
    """Renouvellement déjà créé pour le cycle courant ?"""
    today = date.today()
    rows = (
        await db.execute(
            select(BailRenouvellement)
            .where(BailRenouvellement.bail_id == bail.id)
            .order_by(BailRenouvellement.avis_envoye_le.desc())
        )
    ).scalars().all()
    for r in rows:
        if est_cycle_courant(r, bail.date_fin, today):
            return r
    return None


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
    locataire_nom: Optional[str] = None,
    logement_adresse: Optional[str] = None,
    loyer_actuel: Optional[float] = None,
) -> tuple[BailRenouvellement, bool, Optional[str], Optional[str]]:
    """Crée le renouvellement (si nécessaire) et envoie le PDF par courriel.

    Returns: (renouvellement, courriel_envoye, raison_si_non_envoye) —
    la raison remonte jusqu'à l'UI (retour Phil 2026-07-30 : « je ne
    l'ai jamais reçu », l'échec était silencieux).
    Idempotent : si un renouvellement actif existe déjà pour ce cycle et
    ``force=False``, on ne le redouble pas — on le retourne tel quel.
    """
    now_utc = datetime.now(timezone.utc)
    today = date.today()

    existing = await _existing_renouvellement_active(db, bail)
    if existing is not None and not force:
        return existing, False, "Un avis existe déjà pour ce cycle.", None


    # Crée le renouvellement
    obj = BailRenouvellement(
        bail_id=bail.id,
        avis_envoye_le=today,
        nouveau_loyer=nouveau_loyer,
        nouvelle_date_debut=nouvelle_date_debut
        or (bail.date_fin + timedelta(days=1) if bail.date_fin else None),
        # Défaut légal : reconduction de 12 mois (même jour un an plus
        # tard) — plus de champ vide sur le PDF.
        nouvelle_date_fin=nouvelle_date_fin
        or (
            fin_reconduite(bail.date_debut, bail.date_fin)
            if bail.date_fin
            else None
        ),
        status=BailRenouvellementStatus.PROPOSE.value,
        notes=motif,
    )
    obj.created_at = now_utc
    obj.updated_at = now_utc
    db.add(obj)
    await db.flush()

    # Génère le PDF officiel TAL-806 + document CONSERVÉ (suivi
    # envoyé/ouvert/signé sur la page Renouvellements — retour Phil
    # 2026-07-20, point 11) + envoi courriel avec lien de consultation.
    sent = False
    raison: Optional[str] = None
    ctx = await _build_tal_context_for_bail(
        db, bail, nouveau_loyer, obj.nouvelle_date_debut, obj.nouvelle_date_fin
    )
    if motif:
        ctx.motif_modification = motif
    # Overrides de la modal « Préparer » (retour Phil 2026-07-31 : tout
    # est pré-rempli mais modifiable) — l'adresse saisie remplace le
    # trio adresse/numéro/ville assemblé.
    if locataire_nom:
        ctx.locataire_nom = locataire_nom
    if logement_adresse:
        ctx.logement_adresse = logement_adresse
        ctx.logement_numero = None
        ctx.logement_ville = None
    if loyer_actuel is not None:
        ctx.bail_loyer_mensuel = float(loyer_actuel)

    # PDF modèle remplacé par l'utilisateur, s'il y en a un.
    template_bytes = None
    try:
        from sqlalchemy.orm import undefer

        from app.models.immobilier import ImmDocTemplate

        ov = (
            await db.execute(
                select(ImmDocTemplate)
                .options(undefer(ImmDocTemplate.pdf_blob))
                .where(ImmDocTemplate.type == "avis_modification")
            )
        ).scalar_one_or_none()
        if ov is not None:
            template_bytes = ov.pdf_blob
    except Exception:  # noqa: BLE001
        log.exception("Lecture du modèle avis_modification échouée")

    pdf_bytes = generate_tal_pdf("avis_modification", ctx, template_bytes)

    doc = None
    try:
        from app.api.v1.endpoints.immobilier_documents import save_document

        logement = await db.get(Logement, bail.logement_id)
        doc = await save_document(
            db,
            bail_id=bail.id,
            locataire_id=bail.locataire_id,
            immeuble_id=logement.immeuble_id if logement else None,
            doc_type="avis_modification",
            titre="Avis d'augmentation / modification du bail",
            params={
                "modif_mode": "nouveau_loyer" if nouveau_loyer else None,
                "nouveau_loyer": nouveau_loyer,
                "nouvelle_date_debut": str(obj.nouvelle_date_debut or ""),
                "nouvelle_date_fin": str(nouvelle_date_fin or ""),
                "motif": motif,
            },
            pdf=pdf_bytes,
            created_by_email=None,
        )
        if not doc.signature_token:
            doc.signature_token = secrets.token_urlsafe(32)
        # Lien cycle ↔ document (suivi + suppression liée + réponse en
        # ligne retrouvent le cycle par document_id).
        obj.document_id = doc.id
        await db.flush()
    except Exception:  # noqa: BLE001
        log.exception(
            "Sauvegarde du document de renouvellement échouée (bail %s)",
            bail.id,
        )

    expediteur: Optional[str] = None
    if not ctx.locataire_email:
        raison = "Le locataire n'a pas de courriel dans sa fiche."
    else:
        mailer = GraphMailer()
        expediteur = mailer.sender or None
        if not mailer.ready:
            raison = (
                "Microsoft 365 (Graph) n'est pas configuré — "
                "courriel impossible."
            )
        else:
            try:
                from app.services.public_links import public_base

                url = (
                    f"{public_base()}/sign-document/{doc.signature_token}"
                    if doc is not None and doc.signature_token
                    else None
                )
                subject = (
                    f"Avis de modification du bail — {ctx.logement_adresse or ''}"
                ).strip(" —")
                body_html = _render_email_body(ctx, url)
                # « Envoi certifié » : BCC à l'expéditeur pour archive +
                # demande d'accusé de lecture (read receipt) Outlook.
                bcc = (
                    [mailer.sender]
                    if bcc_to_sender and mailer.sender
                    else None
                )
                # Audit 2026-08-17 : porte UNIQUE des courriels au
                # locataire — profil d'expéditeur (les réponses vont au
                # gestionnaire) + trace d'audit + fil de la fiche.
                from app.services.locatif_mail import (
                    envoyer_au_locataire,
                )

                _fe, _fn, _rt = await envoyer_au_locataire(
                    db,
                    destinataires=[ctx.locataire_email],
                    sujet=subject,
                    corps_html=body_html,
                    type_envoi="avis_renouvellement",
                    locataire_id=bail.locataire_id,
                    locataire_nom=ctx.locataire_nom or None,
                    bail_id=bail.id,
                    immeuble_id=(
                        logement.immeuble_id if logement is not None else None
                    ),
                    resume_fiche=(
                        "Avis de modification du bail envoyé "
                        f"(à {ctx.locataire_email})"
                    ),
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
                expediteur = _fe or expediteur
                sent = True
                if doc is not None:
                    doc.envoye_le = datetime.now(timezone.utc)
                    doc.envoye_a = ctx.locataire_email[:320]
            except Exception as exc:  # noqa: BLE001
                raison = f"Envoi Microsoft Graph échoué : {exc}"[:300]
                log.exception(
                    "Échec envoi email renouvellement bail %s", bail.id
                )

    return obj, sent, raison, expediteur


def _render_email_body(ctx: TalContext, url: Optional[str] = None) -> str:
    nom = ctx.locataire_nom or "Madame, Monsieur,"
    adresse = ctx.logement_adresse or "votre logement"
    bloc_lien = (
        f"""
    <p style="margin:20px 0 6px 0">
      <a href="{url}" style="display:inline-block;background:#d89b3c;color:#111;
         padding:12px 20px;border-radius:8px;font-weight:bold;
         text-decoration:none">Consulter l'avis — accepter ou refuser</a>
    </p>
    <p style="margin:0 0 16px 0;font-size:12px;color:#555">Ou copiez ce lien : {url}</p>
    """
        if url
        else ""
    )
    return f"""
    <p>Bonjour {nom},</p>
    <p>Vous trouverez ci-joint l'avis officiel de modification de votre bail
    pour le logement situé au <b>{adresse}</b>.</p>
    {bloc_lien}
    <p>Vous pouvez répondre directement depuis le lien ci-dessus :
    accepter les modifications, annoncer votre départ à la fin du bail,
    ou refuser les modifications et renouveler votre bail. La dernière
    page du document ci-joint reprend ces trois choix.</p>
    <p>Vous disposez d'un délai d'un (1) mois à compter de la réception du
    présent avis pour répondre. À défaut de réponse, vous serez réputé avoir
    accepté les modifications proposées.</p>
    <p>N'hésitez pas à nous contacter pour toute question.</p>
    <p>Cordialement,<br/>Horizon Services Immobiliers</p>
    """.strip()


# « scan_and_send_due_renouvellements » (envoi AUTOMATIQUE des avis par
# cron/batch) supprimé — demande Phil 2026-07-10 : plus rien ne part vers
# un locataire sans un clic explicite. Seul chemin d'envoi restant :
# send_renouvellement_for_bail(), déclenché par le bouton de
# /immobilier/renouvellements (POST /baux/{id}/envoyer-renouvellement).
