"""Endpoints publics (sans auth) : le locataire consulte et signe un
document locatif (avis TAL, trousse…) via un lien tokenisé
``/document/{token}``. Miroir léger de public_bail.py."""

from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.api.deps import DBSession
from app.models.immobilier import Bail, ImmDocument, Locataire
from app.services.tal_forms import SIGNATURE_NON_REQUISE

log = logging.getLogger(__name__)

router = APIRouter(prefix="/public/documents", tags=["public-documents"])


class PublicDocument(BaseModel):
    titre: str
    type: str
    locataire_name: Optional[str]
    envoye_le: Optional[datetime]
    signed_at: Optional[datetime]
    signed_by_name: Optional[str]
    #: False = document en CONSULTATION seule (avis de retard, accès…) —
    #: la page publique masque le bloc signature ; l'ouverture reste
    #: horodatée (suivi d'ouverture universel, retour Phil 2026-07-20).
    signature_requise: bool = True
    #: v3 — avis de modification du bail : le locataire peut REFUSER en
    #: ligne (art. 1945 C.c.Q. : un mois pour répondre).
    refus_possible: bool = False
    refuse_le: Optional[date] = None
    #: v4 — avis de modification : la signature exige un CHOIX parmi
    #: accepte / quitte / refuse (page « Réponse du locataire »).
    choix_requis: bool = False
    choix: Optional[str] = None
    #: v7 — délai d'un mois écoulé sans réponse : réputé accepté, le
    #: document reste consultable mais la signature est fermée.
    repute_accepte_le: Optional[date] = None
    #: v7 — la copie signée vient d'être transmise par courriel (posé
    #: seulement dans la réponse du POST /signer).
    copie_envoyee: Optional[bool] = None
    #: v8 — raison de l'échec d'envoi de la copie (déboguer le « je ne
    #: la reçois pas » de Phil).
    copie_erreur: Optional[str] = None
    company_name: str = "Horizon Services Immobiliers"
    company_email: str = "info@immohorizon.com"


class SignDocument(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    signature_image_data_url: Optional[str] = Field(
        default=None, max_length=2_000_000
    )
    #: v4 — réponse à un avis de modification : accepte | quitte |
    #: refuse. Requis pour ces avis, ignoré pour le reste.
    choix: Optional[str] = Field(
        default=None, pattern=r"^(accepte|quitte|refuse)$"
    )


def _decode_data_url(
    data_url: Optional[str],
) -> tuple[Optional[bytes], Optional[str]]:
    if not data_url or not data_url.startswith("data:"):
        return None, None
    try:
        header, b64 = data_url.split(",", 1)
        ct = "image/png"
        if ":" in header:
            after = header.split(":", 1)[1]
            ct = after.split(";", 1)[0] if ";" in after else after
        raw = base64.b64decode(b64, validate=False)
        if len(raw) > 1_500_000:
            return None, None
        return raw, ct
    except Exception:  # noqa: BLE001
        return None, None


async def _load(db: AsyncSession, token: str) -> ImmDocument:
    doc = (
        await db.execute(
            select(ImmDocument).where(
                ImmDocument.signature_token == token
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Lien invalide ou expiré."
        )
    return doc


async def _cycle_du_doc(db: AsyncSession, doc: ImmDocument):
    """Cycle de renouvellement lié à un avis de modification — par
    ``document_id`` d'abord, sinon le dernier cycle du bail."""
    from app.models.immobilier import BailRenouvellement

    if doc.type != "avis_modification":
        return None
    r = (
        await db.execute(
            select(BailRenouvellement).where(
                BailRenouvellement.document_id == doc.id
            )
        )
    ).scalars().first()
    if r is None and doc.bail_id:
        r = (
            await db.execute(
                select(BailRenouvellement)
                .where(BailRenouvellement.bail_id == doc.bail_id)
                .order_by(
                    BailRenouvellement.avis_envoye_le.desc(),
                    BailRenouvellement.id.desc(),
                )
            )
        ).scalars().first()
    # Art. 1945 C.c.Q. : un mois sans réponse = réputé accepté. La
    # transition se fait aussi ICI (le locataire peut ouvrir le lien
    # avant que le staff consulte la page Suivis annuels).
    if r is not None and r.status == "propose":
        from app.api.v1.endpoints.immobilier_extras import _plus_un_mois

        deadline = _plus_un_mois(r.avis_envoye_le)
        if date.today() > deadline:
            r.status = "repute_accepte"
            r.reponse_le = deadline
            await db.commit()
    return r


async def _to_public(db: AsyncSession, doc: ImmDocument) -> PublicDocument:
    locataire: Optional[Locataire] = None
    if doc.locataire_id:
        locataire = await db.get(Locataire, doc.locataire_id)
    elif doc.bail_id:
        bail = await db.get(Bail, doc.bail_id)
        if bail:
            locataire = await db.get(Locataire, bail.locataire_id)
    cycle = await _cycle_du_doc(db, doc)
    refuse_le = None
    refus_possible = False
    choix_requis = False
    choix = None
    repute_accepte_le = None
    if cycle is not None:
        if cycle.status == "repute_accepte":
            repute_accepte_le = cycle.reponse_le
        if cycle.status == "refuse":
            refuse_le = cycle.reponse_le
            choix = "refuse"
        elif cycle.status == "depart":
            choix = "quitte"
        elif cycle.status in ("accepte", "repute_accepte") and (
            doc.signed_at is not None
        ):
            choix = "accepte"
        elif doc.signed_at is None and cycle.status in (
            "propose",
            "en_negociation",
        ):
            refus_possible = True
            choix_requis = True
    return PublicDocument(
        titre=doc.titre,
        type=doc.type,
        locataire_name=locataire.full_name if locataire else None,
        envoye_le=doc.envoye_le,
        signed_at=doc.signed_at,
        signed_by_name=doc.signed_by_name,
        signature_requise=doc.type not in SIGNATURE_NON_REQUISE,
        refus_possible=refus_possible,
        refuse_le=refuse_le,
        choix_requis=choix_requis,
        choix=choix,
        repute_accepte_le=repute_accepte_le,
    )


@router.get("/{token}", response_model=PublicDocument)
async def public_read(token: str, db: DBSession) -> PublicDocument:
    doc = await _load(db, token)
    # Preuve d'ouverture : première consultation horodatée.
    if doc.ouvert_le is None:
        doc.ouvert_le = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(doc)
    return await _to_public(db, doc)


@router.get("/{token}/pdf")
async def public_pdf(token: str, db: DBSession) -> Response:
    doc = (
        await db.execute(
            select(ImmDocument)
            .options(undefer(ImmDocument.pdf_blob))
            .where(ImmDocument.signature_token == token)
        )
    ).scalar_one_or_none()
    if doc is None or not doc.pdf_blob:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Lien invalide ou expiré."
        )
    return Response(
        content=doc.pdf_blob,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="document.pdf"'},
    )


class RefuserDocument(BaseModel):
    motif: Optional[str] = Field(default=None, max_length=2000)


@router.post("/{token}/refuser", response_model=PublicDocument)
async def public_refuse(
    token: str, data: RefuserDocument, db: DBSession
) -> PublicDocument:
    """Le locataire REFUSE la modification proposée (art. 1945
    C.c.Q.). Le cycle passe « refuse » — côté locateur, la ligne monte
    en rouge avec la deadline de fixation TAL (1 mois, art. 1947)."""
    doc = await _load(db, token)
    if doc.signed_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Ce document a déjà été signé (accepté).",
        )
    cycle = await _cycle_du_doc(db, doc)
    if cycle is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Ce document ne peut pas être refusé en ligne.",
        )
    if cycle.status == "refuse":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Le refus a déjà été enregistré.",
        )
    cycle.status = "refuse"
    cycle.reponse_le = date.today()
    cycle.refus_motif = (data.motif or "").strip()[:2000] or None
    await db.commit()
    await db.refresh(doc)
    return await _to_public(db, doc)


@router.post("/{token}/signer", response_model=PublicDocument)
async def public_sign(
    token: str, data: SignDocument, request: Request, db: DBSession
) -> PublicDocument:
    doc = await _load(db, token)
    if doc.signed_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Ce document est déjà signé.",
        )
    if doc.type in SIGNATURE_NON_REQUISE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Ce document ne requiert pas de signature.",
        )
    # v7 — après le délai d'un mois, le locataire est réputé avoir
    # accepté : la signature est fermée (le document reste consultable).
    cycle_avant = await _cycle_du_doc(db, doc)
    if (
        doc.type == "avis_modification"
        and cycle_avant is not None
        and cycle_avant.status == "repute_accepte"
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                "Le délai de réponse d'un (1) mois est écoulé — vous "
                "êtes réputé avoir accepté les modifications (art. 1945 "
                "C.c.Q.). La signature n'est plus possible."
            ),
        )
    doc.signed_at = datetime.now(timezone.utc)
    doc.signed_by_name = data.name.strip()[:255]
    raw_ip = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else None
    )
    if raw_ip:
        doc.signature_ip = raw_ip.split(",")[0].strip()[:64]
    sig, ct = _decode_data_url(data.signature_image_data_url)
    if sig:
        doc.signature_image = sig
        doc.signature_image_content_type = ct
    # v4 — signer un AVIS DE MODIFICATION consigne la RÉPONSE choisie
    # (page « Réponse du locataire ») : accepte / quitte (départ à la
    # fin du bail) / refuse (les modifications, et renouvelle). Le PDF
    # conservé est estampillé — X sur le choix, signature, date, IP.
    cycle = cycle_avant
    if cycle is not None and cycle.status in (
        "propose",
        "en_negociation",
    ):
        choix = data.choix or "accepte"
        cycle.status = {
            "accepte": "accepte",
            "quitte": "depart",
            "refuse": "refuse",
        }[choix]
        cycle.reponse_le = date.today()
        if choix == "quitte":
            # Le locataire annonce OFFICIELLEMENT son départ : même
            # effet que « Non renouvelé » — un dossier de relocation
            # s'ouvre (la ligne devient mauve, actions bloquées).
            try:
                await _ouvrir_dossier_relocation(db, doc)
            except Exception:  # noqa: BLE001 — la réponse prime
                log.exception(
                    "Ouverture du dossier de relocation échouée "
                    "(doc %s)", doc.id
                )
        try:
            await _estampiller_pdf(db, doc, choix)
        except Exception:  # noqa: BLE001 — la réponse prime sur le PDF
            log.exception(
                "Estampillage de la page réponse échoué (doc %s)", doc.id
            )
    await db.commit()
    await db.refresh(doc)
    # Copie signée transmise APRÈS le commit — le résultat est affiché
    # au locataire (retour Phil : « je ne la reçois toujours pas »,
    # l'échec était invisible).
    copie_ok = False
    copie_err: Optional[str] = None
    if doc.type == "avis_modification":
        try:
            await _envoyer_copie_signee(db, doc)
            copie_ok = True
        except Exception as exc:  # noqa: BLE001
            copie_err = str(exc)[:200]
            log.exception(
                "Envoi de la copie signée échoué (doc %s)", doc.id
            )
    pub = await _to_public(db, doc)
    pub.copie_envoyee = copie_ok
    pub.copie_erreur = copie_err
    return pub


async def _ouvrir_dossier_relocation(db, doc: ImmDocument) -> None:
    """Réponse « je quitte » signée → dossier de relocation (comme le
    bouton « Non renouvelé »), s'il n'y en a pas déjà un d'actif."""
    from app.models.immobilier import LocationDossier

    if not doc.bail_id:
        return
    bail = await db.get(Bail, doc.bail_id)
    if bail is None or not bail.logement_id:
        return
    existant = (
        await db.execute(
            select(LocationDossier).where(
                LocationDossier.logement_id == bail.logement_id,
                LocationDossier.statut.notin_(["annule", "reloue"]),
            )
        )
    ).scalars().first()
    if existant is not None:
        return
    db.add(
        LocationDossier(
            logement_id=bail.logement_id,
            bail_id=bail.id,
            statut="avis_recu",
        )
    )


async def _envoyer_copie_signee(db, doc: ImmDocument) -> None:
    """Envoie au locataire la version SIGNÉE (estampillée) de l'avis —
    sa preuve à lui, annoncée sur la page publique."""
    from sqlalchemy.orm import undefer

    from app.api.v1.endpoints.immobilier_documents import (
        _resolve_destinataire,
    )
    from app.integrations.email_graph import EmailAttachment, GraphMailer

    locataire, dest = await _resolve_destinataire(db, doc, None)
    mailer = GraphMailer()
    if not mailer.ready:
        raise RuntimeError("Microsoft Graph n'est pas configuré.")
    if not dest:
        raise RuntimeError("Le locataire n'a pas de courriel.")
    d2 = (
        await db.execute(
            select(ImmDocument)
            .options(undefer(ImmDocument.pdf_blob))
            .where(ImmDocument.id == doc.id)
        )
    ).scalar_one()
    if not d2.pdf_blob:
        raise RuntimeError("PDF signé introuvable.")
    nom = (locataire.full_name if locataire else "") or "Madame, Monsieur"
    await mailer.send(
        to=[dest],
        subject="Merci d'avoir signé — votre copie de l'avis",
        html_body=(
            f"<p>Bonjour {nom},</p>"
            "<p>Merci d'avoir signé ! Voici votre version signée de "
            "l'avis — conservez-la pour vos dossiers.</p>"
            "<p>Cordialement,<br/>Horizon Services Immobiliers</p>"
        ),
        attachments=[
            EmailAttachment(
                name="avis-modification-signe.pdf",
                content_bytes=d2.pdf_blob,
                content_type="application/pdf",
            )
        ],
    )


async def _estampiller_pdf(db, doc: ImmDocument, choix: str) -> None:
    """Remplace la page « Réponse du locataire » du PDF conservé par la
    version estampillée (choix coché, signature, date, IP) — le
    locataire ne peut modifier aucune autre partie du document."""
    from sqlalchemy.orm import undefer

    from app.services.tal_officiel import estampiller_page_reponse

    d2 = (
        await db.execute(
            select(ImmDocument)
            .options(undefer(ImmDocument.pdf_blob))
            .where(ImmDocument.id == doc.id)
        )
    ).scalar_one()
    if not d2.pdf_blob:
        return
    quand = datetime.now(timezone.utc).astimezone(
        ZoneInfo("America/Toronto")
    )
    d2.pdf_blob = estampiller_page_reponse(
        d2.pdf_blob,
        locataire_nom=doc.signed_by_name,
        choix=choix,
        signature_png=doc.signature_image,
        signe_le_txt=quand.strftime("%Y-%m-%d %H:%M %Z"),
        ip=doc.signature_ip,
    )
