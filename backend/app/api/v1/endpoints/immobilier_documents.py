"""Documents locatifs conservés (avis TAL, trousse bail, DPA…).

    GET    /immobilier/baux/{bail_id}/documents
    GET    /immobilier/locataires/{locataire_id}/documents
    GET    /immobilier/documents/{id}/pdf
    DELETE /immobilier/documents/{id}
    POST   /immobilier/documents/{id}/envoyer-signature

Chaque génération (Générer ▾ / envoi DPA) enregistre le PDF + ses
paramètres dans ``imm_documents`` ; l'envoi pour signature crée un lien
public tokenisé /document/{token} (page publique + preuve d'ouverture +
signature — voir public_document.py).
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.api.deps import CurrentUser, DBSession
from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.immobilier import (
    Bail,
    ImmDocument,
    Locataire,
    LocataireCommunication,
)
from app.services.public_links import public_base
from app.services.tal_forms import SIGNATURE_NON_REQUISE

log = logging.getLogger(__name__)

router = APIRouter(prefix="/immobilier", tags=["immobilier-documents"])


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion immobilière » non autorisé.",
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentRead(BaseModel):
    id: int
    bail_id: Optional[int]
    locataire_id: Optional[int]
    type: str
    titre: str
    params: dict = {}
    created_at: Optional[datetime] = None
    envoye_le: Optional[datetime] = None
    envoye_a: Optional[str] = None
    ouvert_le: Optional[datetime] = None
    signed_at: Optional[datetime] = None
    signed_by_name: Optional[str] = None


def _doc_read(d: ImmDocument) -> DocumentRead:
    params: dict = {}
    if d.params_json:
        try:
            parsed = json.loads(d.params_json)
            if isinstance(parsed, dict):
                params = parsed
        except Exception:  # noqa: BLE001
            pass
    return DocumentRead(
        id=d.id,
        bail_id=d.bail_id,
        locataire_id=d.locataire_id,
        type=d.type,
        titre=d.titre,
        params=params,
        created_at=d.created_at,
        envoye_le=d.envoye_le,
        envoye_a=d.envoye_a,
        ouvert_le=d.ouvert_le,
        signed_at=d.signed_at,
        signed_by_name=d.signed_by_name,
    )


async def save_document(
    db,
    *,
    bail_id: Optional[int],
    locataire_id: Optional[int],
    immeuble_id: Optional[int],
    doc_type: str,
    titre: str,
    params: Optional[dict],
    pdf: bytes,
    created_by_email: Optional[str],
) -> ImmDocument:
    """Enregistre un document généré (appelé par les endpoints de
    génération — extras TAL, DPA). Flush seulement : le commit appartient
    à l'appelant."""
    obj = ImmDocument(
        bail_id=bail_id,
        locataire_id=locataire_id,
        immeuble_id=immeuble_id,
        type=doc_type,
        titre=titre,
        params_json=(
            json.dumps(params, default=str) if params else None
        ),
        pdf_blob=pdf,
        created_by_email=created_by_email,
    )
    db.add(obj)
    await db.flush()
    return obj


@router.get("/baux/{bail_id}/documents", response_model=List[DocumentRead])
async def list_bail_documents(
    bail_id: int, db: DBSession, user: CurrentUser
) -> List[DocumentRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(ImmDocument)
            .where(ImmDocument.bail_id == bail_id)
            .order_by(ImmDocument.created_at.desc(), ImmDocument.id.desc())
        )
    ).scalars().all()
    return [_doc_read(d) for d in rows]


@router.get(
    "/locataires/{locataire_id}/documents",
    response_model=List[DocumentRead],
)
async def list_locataire_documents(
    locataire_id: int, db: DBSession, user: CurrentUser
) -> List[DocumentRead]:
    """Documents du locataire : les siens (DPA…) + ceux de ses baux."""
    _require_volet(user)
    bail_ids = [
        r[0]
        for r in (
            await db.execute(
                select(Bail.id).where(Bail.locataire_id == locataire_id)
            )
        ).all()
    ]
    cond = ImmDocument.locataire_id == locataire_id
    if bail_ids:
        cond = cond | ImmDocument.bail_id.in_(bail_ids)
    rows = (
        await db.execute(
            select(ImmDocument)
            .where(cond)
            .order_by(ImmDocument.created_at.desc(), ImmDocument.id.desc())
        )
    ).scalars().all()
    return [_doc_read(d) for d in rows]


@router.get("/documents/{doc_id}/pdf")
async def get_document_pdf(
    doc_id: int, db: DBSession, user: CurrentUser
):
    _require_volet(user)
    from fastapi.responses import Response

    d = (
        await db.execute(
            select(ImmDocument)
            .options(undefer(ImmDocument.pdf_blob))
            .where(ImmDocument.id == doc_id)
        )
    ).scalar_one_or_none()
    if d is None or not d.pdf_blob:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    fname = f"{d.type.replace('_', '-')}-{d.id}.pdf"
    return Response(
        content=d.pdf_blob,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{fname}"'
        },
    )


@router.delete(
    "/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_document(
    doc_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    d = await db.get(ImmDocument, doc_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    if d.signed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un document signé ne peut pas être supprimé.",
        )
    await db.delete(d)
    await db.commit()


async def _resolve_destinataire(
    db, d: ImmDocument, email: Optional[str]
) -> tuple[Optional[Locataire], str]:
    """Destinataire d'un envoi : email explicite sinon le courriel du
    locataire (direct ou via le bail). 400 si aucun."""
    locataire: Optional[Locataire] = None
    if d.locataire_id:
        locataire = await db.get(Locataire, d.locataire_id)
    elif d.bail_id:
        bail = await db.get(Bail, d.bail_id)
        if bail:
            locataire = await db.get(Locataire, bail.locataire_id)
    dest = (email or "").strip() or (
        (locataire.email or "").strip() if locataire else ""
    )
    if not dest:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Aucun courriel destinataire — ajoute un courriel au "
                "locataire ou fournis-en un."
            ),
        )
    return locataire, dest


class EnvoyerSignatureRequest(BaseModel):
    email: Optional[EmailStr] = None  # défaut : courriel du locataire


class EnvoyerSignatureResult(BaseModel):
    document_id: int
    envoye_a: str
    envoye_le: datetime
    url: str


def _mail_html(titre: str, locataire_name: str, url: str) -> str:
    first = (locataire_name or "").strip().split(" ")[0] or "Bonjour"
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p>Bonjour {first},</p>
  <p>Un document vous est transmis pour consultation et signature :
     <strong>{titre}</strong>.</p>
  <p style="margin:20px 0 6px 0">
    <a href="{url}" style="display:inline-block;background:#d89b3c;color:#111;
       padding:12px 20px;border-radius:8px;font-weight:bold;
       text-decoration:none">Consulter et signer le document</a>
  </p>
  <p style="margin:0 0 16px 0;font-size:12px;color:#555">Ou copiez ce lien : {url}</p>
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers<br>info@immohorizon.com
  </p>
</div>
"""


@router.post(
    "/documents/{doc_id}/envoyer-signature",
    response_model=EnvoyerSignatureResult,
)
async def envoyer_signature(
    doc_id: int,
    payload: EnvoyerSignatureRequest,
    db: DBSession,
    user: CurrentUser,
) -> EnvoyerSignatureResult:
    """Envoie le document au locataire pour signature en ligne (lien
    public tokenisé). Envoi MANUEL uniquement — rien d'automatique."""
    _require_volet(user)
    d = await db.get(ImmDocument, doc_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    if d.signed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ce document est déjà signé.",
        )
    if d.type in SIGNATURE_NON_REQUISE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Ce document ne requiert pas de signature — utilise "
                "l'envoi par courriel."
            ),
        )

    locataire, dest = await _resolve_destinataire(db, d, payload.email)

    if not d.signature_token:
        d.signature_token = secrets.token_urlsafe(32)
        await db.flush()
    url = f"{public_base()}/sign-document/{d.signature_token}"

    mailer = get_mailer()
    try:
        await mailer.send(
            to=[dest],
            subject=(
                f"{d.titre} — Horizon Services Immobiliers"
            ),
            html_body=_mail_html(
                d.titre,
                locataire.full_name if locataire else "",
                url,
            ),
            reply_to=mailer.sender,
        )
    except Exception as exc:  # noqa: BLE001 — réseau/Graph
        log.exception("Envoi document %s échoué", doc_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Envoi courriel échoué : {exc}",
        )

    d.envoye_le = _now()
    d.envoye_a = dest[:320]

    # Journal des communications du locataire (best-effort).
    if locataire is not None:
        try:
            db.add(
                LocataireCommunication(
                    locataire_id=locataire.id,
                    kind="courriel",
                    contenu=(
                        f"Document envoyé pour signature : {d.titre} "
                        f"(à {dest})"
                    ),
                    auteur=user.email,
                )
            )
        except Exception:  # noqa: BLE001
            pass

    await db.commit()
    await db.refresh(d)
    return EnvoyerSignatureResult(
        document_id=d.id,
        envoye_a=dest,
        envoye_le=d.envoye_le,
        url=url,
    )


class EnvoyerCourrielResult(BaseModel):
    document_id: int
    envoye_a: str
    envoye_le: datetime


def _mail_html_piece_jointe(titre: str, locataire_name: str, doc_type: str) -> str:
    first = (locataire_name or "").strip().split(" ")[0] or "Bonjour"
    ligne_extra = ""
    if doc_type == "rappel_paiement":
        ligne_extra = (
            "<p><strong>Le paiement de votre loyer est exigé "
            "immédiatement.</strong></p>"
        )
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p>Bonjour {first},</p>
  <p>Veuillez trouver ci-joint le document suivant :
     <strong>{titre}</strong>.</p>
  {ligne_extra}
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers<br>info@immohorizon.com
  </p>
</div>
"""


@router.post(
    "/documents/{doc_id}/envoyer-courriel",
    response_model=EnvoyerCourrielResult,
)
async def envoyer_courriel(
    doc_id: int,
    payload: EnvoyerSignatureRequest,
    db: DBSession,
    user: CurrentUser,
) -> EnvoyerCourrielResult:
    """Envoie le document par SIMPLE COURRIEL avec le PDF en pièce
    jointe — pour les documents sans signature (avis de retard, avis
    d'accès…). Envoi MANUEL uniquement."""
    _require_volet(user)
    d = (
        await db.execute(
            select(ImmDocument)
            .options(undefer(ImmDocument.pdf_blob))
            .where(ImmDocument.id == doc_id)
        )
    ).scalar_one_or_none()
    if d is None or not d.pdf_blob:
        raise HTTPException(status_code=404, detail="Document introuvable.")

    locataire, dest = await _resolve_destinataire(db, d, payload.email)

    mailer = get_mailer()
    try:
        await mailer.send(
            to=[dest],
            subject=f"{d.titre} — Horizon Services Immobiliers",
            html_body=_mail_html_piece_jointe(
                d.titre,
                locataire.full_name if locataire else "",
                d.type,
            ),
            reply_to=mailer.sender,
            attachments=[
                EmailAttachment(
                    name=f"{d.type.replace('_', '-')}.pdf",
                    content_bytes=d.pdf_blob,
                    content_type="application/pdf",
                )
            ],
        )
    except Exception as exc:  # noqa: BLE001 — réseau/Graph
        log.exception("Envoi courriel document %s échoué", doc_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Envoi courriel échoué : {exc}",
        )

    d.envoye_le = _now()
    d.envoye_a = dest[:320]

    if locataire is not None:
        try:
            db.add(
                LocataireCommunication(
                    locataire_id=locataire.id,
                    kind="courriel",
                    contenu=(
                        f"Document envoyé par courriel : {d.titre} "
                        f"(à {dest})"
                    ),
                    auteur=user.email,
                )
            )
        except Exception:  # noqa: BLE001
            pass

    await db.commit()
    await db.refresh(d)
    return EnvoyerCourrielResult(
        document_id=d.id, envoye_a=dest, envoye_le=d.envoye_le
    )
