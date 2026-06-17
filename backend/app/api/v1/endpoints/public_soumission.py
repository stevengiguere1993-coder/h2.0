"""Public (no-auth) endpoints so a client can view & e-sign a
soumission from a unique tokenized link sent by email.

    GET  /api/v1/public/soumissions/{token}          -> JSON details
    GET  /api/v1/public/soumissions/{token}/pdf      -> inline PDF
    POST /api/v1/public/soumissions/{token}/accept   -> mark accepted
    POST /api/v1/public/soumissions/{token}/reject   -> mark rejected

The token is opaque and acts as both authentication and audit
trail — the signed IP and name are captured when accepted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.models.client import Client
from app.models.contact_request import ContactRequest, ContactRequestStatus
from app.models.soumission import Soumission, SoumissionStatus
from app.models.soumission_item import SoumissionItem
from app.services.soumission_pdf import render_soumission_pdf


router = APIRouter(prefix="/public/soumissions", tags=["public-soumissions"])

log = logging.getLogger(__name__)


class PublicItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    position: int
    description: str
    unit: Optional[str]
    quantity: float
    unit_price: float
    total: float


class PublicSoumission(BaseModel):
    reference: str
    title: str
    description: Optional[str]
    client_note: Optional[str] = None
    status: str
    valid_until: Optional[datetime]
    signed_name: Optional[str]
    items: list[PublicItem]
    subtotal: float
    tps: float
    tvq: float
    total: float
    company_name: str = "Horizon Services Immobiliers"
    company_rbq: str = "RBQ 5868-5991-01"
    company_email: str = "info@immohorizon.com"
    pricing_kind: str = "forfaitaire"  # "forfaitaire" | "estime"


class AcceptRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    # Drawn signature, sent as a data URL ("data:image/png;base64,…").
    # Optional for backward compat (a typed name still works).
    signature_image_data_url: Optional[str] = Field(
        default=None, max_length=2_000_000
    )


def _decode_data_url(data_url: Optional[str]) -> tuple[Optional[bytes], Optional[str]]:
    """Parse a 'data:...;base64,...' URL and return (bytes, content_type).
    Returns (None, None) if the input is None or malformed."""
    import base64
    if not data_url:
        return None, None
    if not data_url.startswith("data:"):
        return None, None
    try:
        header, b64 = data_url.split(",", 1)
        # header looks like "data:image/png;base64"
        content_type = "image/png"
        if ":" in header:
            after_colon = header.split(":", 1)[1]
            if ";" in after_colon:
                content_type = after_colon.split(";", 1)[0]
            else:
                content_type = after_colon or content_type
        raw = base64.b64decode(b64, validate=False)
        if len(raw) > 1_500_000:  # ~1.5 MB cap
            return None, None
        return raw, content_type
    except Exception:
        return None, None


class RejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


async def _load_by_token(
    db: AsyncSession, token: str
) -> Soumission:
    sm = (
        await db.execute(
            select(Soumission).where(Soumission.signature_token == token)
        )
    ).scalar_one_or_none()
    if sm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lien invalide ou expiré.",
        )
    return sm


@router.get(
    "/{token}",
    response_model=PublicSoumission,
    summary="Read the soumission attached to a public signature token",
)
async def public_read(token: str, db: DBSession) -> PublicSoumission:
    sm = await _load_by_token(db, token)
    # Suivi d'ouverture : marque la première visite + incrémente le
    # compteur, MAIS avec un débounce de 5 min pour éviter de compter
    # plusieurs visites quand la page web déclenche des re-fetchs
    # rapprochés (React StrictMode, embed PDF, rechargement mobile,
    # navigation arrière/avant). Best-effort — n'interrompt jamais
    # le rendu.
    try:
        now = datetime.now(timezone.utc)
        last = sm.client_last_opened_at
        if last is None or (now - last).total_seconds() > 300:
            if sm.client_opened_at is None:
                sm.client_opened_at = now
            sm.client_last_opened_at = now
            sm.client_open_count = (sm.client_open_count or 0) + 1
            await db.flush()
    except Exception:  # noqa: BLE001
        pass
    rows = list(
        (
            await db.execute(
                select(SoumissionItem)
                .where(SoumissionItem.soumission_id == sm.id)
                .order_by(
                    SoumissionItem.position.asc(), SoumissionItem.id.asc()
                )
            )
        ).scalars().all()
    )
    # Recompute totals from items so the client view is always
    # consistent with what the staff sees.
    subtotal = 0.0
    for it in rows:
        if it.total is not None:
            subtotal += float(it.total)
        else:
            subtotal += float(it.quantity) * float(it.unit_price)
    subtotal = round(subtotal, 2)
    tps = round(subtotal * 0.05, 2)
    tvq = round(subtotal * 0.09975, 2)
    total = round(subtotal + tps + tvq, 2)
    return PublicSoumission(
        reference=sm.reference,
        title=sm.title,
        description=sm.description,
        client_note=sm.client_note,
        status=sm.status,
        valid_until=sm.valid_until,
        signed_name=sm.signed_name,
        items=[PublicItem.model_validate(r) for r in rows],
        subtotal=subtotal,
        tps=tps,
        tvq=tvq,
        total=total,
        pricing_kind=getattr(sm, "pricing_kind", "forfaitaire") or "forfaitaire",
    )


@router.get(
    "/{token}/pdf",
    summary="Inline PDF preview for the public link",
)
async def public_pdf(token: str, db: DBSession) -> Response:
    sm = await _load_by_token(db, token)
    rendered = await render_soumission_pdf(db, sm.id)
    if rendered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF introuvable.")
    _, pdf_bytes = rendered
    filename = f"soumission-{sm.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


async def _auto_send_deposit_facture(facture_id: int) -> None:
    """Envoie au client la facture d'acompte générée à la signature :
    status → sent + courriel + PDF, puis push QBO (si auto-sync). Best-
    effort — n'interrompt jamais le flux de signature."""
    from app.db.session import AsyncSessionLocal
    from app.models.client import Client
    from app.models.facture import Facture, FactureStatus
    from app.services.facture_send import send_facture

    try:
        async with AsyncSessionLocal() as db:
            fa = (
                await db.execute(
                    select(Facture).where(Facture.id == facture_id)
                )
            ).scalar_one_or_none()
            if fa is None or fa.status != FactureStatus.DRAFT.value:
                return
            email = None
            if fa.client_id:
                cl = (
                    await db.execute(
                        select(Client).where(Client.id == fa.client_id)
                    )
                ).scalar_one_or_none()
                email = (cl.email or "").strip() if cl and cl.email else None
            if not email:
                log.info(
                    "Acompte %s : pas de courriel client → non envoyé",
                    facture_id,
                )
                return
            await send_facture(
                db,
                facture_id,
                to=[email],
                message=(
                    "Bonjour, voici votre facture d'acompte suite à "
                    "l'acceptation de votre soumission. Merci !"
                ),
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        log.warning(
            "Auto-envoi facture d'acompte %s échoué", facture_id,
            exc_info=True,
        )
        return
    # Facture maintenant ENVOYÉE → on la pousse vers QBO (si auto-sync ON).
    try:
        from app.services.qbo_auto_sync import autopush_facture

        await autopush_facture(facture_id)
    except Exception:  # noqa: BLE001
        log.warning("Autopush QBO acompte %s échoué", facture_id)


@router.post(
    "/{token}/accept",
    response_model=PublicSoumission,
    summary="Client accepts the soumission online",
)
async def public_accept(
    token: str,
    data: AcceptRequest,
    request: Request,
    db: DBSession,
    bg: BackgroundTasks,
) -> PublicSoumission:
    sm = await _load_by_token(db, token)
    if sm.status in (
        SoumissionStatus.REJECTED.value,
        SoumissionStatus.EXPIRED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette soumission n'est plus active.",
        )
    # Signature tracée OBLIGATOIRE : on refuse l'acceptation tant qu'aucun
    # tracé n'est fourni (le nom seul ne suffit pas). Validé avant toute
    # mutation pour ne rien persister en cas de refus.
    sig_bytes, sig_ct = _decode_data_url(data.signature_image_data_url)
    if not sig_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La signature tracée est obligatoire.",
        )

    now = datetime.now(timezone.utc)
    sm.status = SoumissionStatus.ACCEPTED.value
    if sm.accepted_at is None:
        sm.accepted_at = now
    sm.signed_name = data.name.strip()[:255]
    raw_ip = (
        request.headers.get("x-forwarded-for") or (
            request.client.host if request.client else None
        )
    )
    # x-forwarded-for can chain multiple hops (CF + Render + client),
    # easily exceeding the VARCHAR(64) column. Keep only the first
    # (original client) IP and cap the length defensively.
    if raw_ip:
        raw_ip = raw_ip.split(",")[0].strip()[:64]
    sm.signed_ip = raw_ip

    # Cœur de l'acceptation (statut + nom + IP) : ces colonnes existent
    # toujours, ce flush DOIT réussir. Tout le reste est best-effort et
    # ISOLÉ par SAVEPOINT (`begin_nested`) pour qu'un échec d'effet de
    # bord n'avorte JAMAIS la transaction principale ni ne renvoie un
    # HTTP 500 au client.
    await db.flush()

    # Signature tracée : écrite via UPDATE isolé. On ne passe pas par
    # l'attribut ORM pour ne pas « salir » sm — si la colonne BYTEA
    # manque sur une vieille base, le SAVEPOINT seul est annulé et le
    # reste de la transaction survit (la signature reste exigée côté
    # client ; seul son archivage image dégrade).
    try:
        async with db.begin_nested():
            await db.execute(
                update(Soumission)
                .where(Soumission.id == sm.id)
                .values(
                    signature_image=sig_bytes,
                    signature_image_content_type=sig_ct,
                )
            )
    except Exception:  # noqa: BLE001
        log.warning(
            "Signature image non stockée pour soumission %s", sm.id,
            exc_info=True,
        )

    # Propagation prospect → client (WON + auto-création client).
    try:
        async with db.begin_nested():
            if sm.contact_request_id:
                cr = (
                    await db.execute(
                        select(ContactRequest).where(
                            ContactRequest.id == sm.contact_request_id
                        )
                    )
                ).scalar_one_or_none()
                if cr is not None:
                    cr.status = ContactRequestStatus.WON.value
                    existing = (
                        await db.execute(
                            select(Client).where(
                                Client.contact_request_id == cr.id
                            )
                        )
                    ).scalar_one_or_none()
                    if existing is None:
                        client = Client(
                            name=cr.name,
                            email=cr.email,
                            phone=cr.phone,
                            address=cr.address,
                            contact_request_id=cr.id,
                        )
                        db.add(client)
                        await db.flush()
                        if sm.client_id is None:
                            sm.client_id = client.id
                    elif sm.client_id is None:
                        sm.client_id = existing.id
    except Exception:  # noqa: BLE001
        log.warning(
            "Propagation client échouée pour soumission %s", sm.id,
            exc_info=True,
        )

    # Auto-création du projet + facture d'acompte dès la signature en
    # ligne. La facture est ensuite ENVOYÉE automatiquement au client
    # (status sent + courriel) — plus besoin de cliquer « Envoyer ».
    deposit_facture_id: Optional[int] = None
    try:
        async with db.begin_nested():
            from app.api.v1.endpoints.soumission_to_project import (
                provision_project_for_soumission,
            )
            _proj, _dep = await provision_project_for_soumission(
                db, sm, notify_qbo=True
            )
            if _dep is not None:
                deposit_facture_id = _dep.id
    except Exception:  # noqa: BLE001
        # Best-effort : ne pas bloquer la signature client si la
        # création du projet échoue. L'admin pourra relancer
        # manuellement.
        log.warning(
            "Provision projet échouée pour soumission %s", sm.id,
            exc_info=True,
        )

    # Envoi automatique de la facture d'acompte au client, à la signature.
    if deposit_facture_id is not None:
        bg.add_task(_auto_send_deposit_facture, deposit_facture_id)

    # Devis accepté en ligne → import QuickBooks (Customer + Estimate),
    # fail-closed via l'interrupteur QBO auto-sync, idempotent. Lancé
    # après le commit de la requête.
    from app.services.qbo_auto_sync import autopush_soumission

    bg.add_task(autopush_soumission, sm.id)

    # Contrat signé par le client → on archive le PDF signé (les deux
    # signatures) dans les documents de la fiche client. Best-effort.
    if getattr(sm, "kind", "quote") == "contract" and sm.client_id:
        try:
            async with db.begin_nested():
                from app.models.client_document import ClientDocument

                rendered = await render_soumission_pdf(db, sm.id)
                if rendered is not None:
                    _, pdf_bytes = rendered
                    db.add(
                        ClientDocument(
                            client_id=sm.client_id,
                            name=f"contrat-{sm.reference}-signe.pdf",
                            content_type="application/pdf",
                            source="contract",
                            soumission_id=sm.id,
                            blob=pdf_bytes,
                        )
                    )
        except Exception:  # noqa: BLE001
            log.warning(
                "Archivage PDF contrat échoué pour soumission %s", sm.id,
                exc_info=True,
            )

    await db.flush()
    await db.refresh(sm)

    # Envoi au client de son PDF signé (preuve avec sa signature tracée
    # rendue dessus). Best-effort : un échec d'envoi ne bloque jamais la
    # signature. S'applique aux soumissions comme aux contrats.
    try:
        recipient: Optional[str] = None
        if sm.client_id:
            cl = await db.get(Client, sm.client_id)
            if cl is not None:
                recipient = cl.email
        if not recipient and sm.contact_request_id:
            cr = (
                await db.execute(
                    select(ContactRequest).where(
                        ContactRequest.id == sm.contact_request_id
                    )
                )
            ).scalar_one_or_none()
            if cr is not None:
                recipient = cr.email
        if recipient:
            from app.integrations.email_graph import (
                EmailAttachment,
                get_mailer,
            )

            mailer = get_mailer()
            if mailer.ready:
                rendered = await render_soumission_pdf(db, sm.id)
                if rendered is not None:
                    _, pdf_bytes = rendered
                    is_contract = getattr(sm, "kind", "quote") == "contract"
                    label = "contrat" if is_contract else "soumission"
                    accord = "" if is_contract else "e"
                    await mailer.send(
                        to=[recipient],
                        subject=(
                            f"Votre {label} signé{accord} — {sm.reference}"
                        ),
                        html_body=(
                            "<p>Bonjour,</p>"
                            f"<p>Merci d'avoir signé votre {label} "
                            f"<b>{sm.reference}</b>. Vous trouverez en "
                            "pièce jointe le PDF avec votre signature.</p>"
                            "<p>L'équipe Horizon Services Immobiliers</p>"
                        ),
                        reply_to=mailer.sender,
                        attachments=[
                            EmailAttachment(
                                name=f"{label}-{sm.reference}-signe.pdf",
                                content_bytes=pdf_bytes,
                                content_type="application/pdf",
                            )
                        ],
                    )
    except Exception:  # noqa: BLE001
        log.warning(
            "Envoi du PDF signé au client échoué pour soumission %s",
            sm.id,
            exc_info=True,
        )

    # Notify managers+ that the quote was signed online (best-effort,
    # isolé pour ne pas avorter la transaction au commit final).
    try:
        async with db.begin_nested():
            from app.services.notifications import notify_role

            await notify_role(
                db,
                min_role="manager",
                kind="soumission.accepted",
                title=f"Soumission acceptée — {sm.reference}",
                body=f"Signée par {sm.signed_name} en ligne.",
                href=f"/app/soumissions/{sm.id}",
            )
    except Exception:  # noqa: BLE001
        log.warning(
            "Notification soumission acceptée échouée pour %s", sm.id,
            exc_info=True,
        )

    return await public_read(token, db)


@router.post(
    "/{token}/reject",
    response_model=PublicSoumission,
    summary="Client rejects the soumission online",
)
async def public_reject(
    token: str,
    data: RejectRequest,
    db: DBSession,
) -> PublicSoumission:
    sm = await _load_by_token(db, token)
    sm.status = SoumissionStatus.REJECTED.value
    # Append the reason to the internal notes for staff visibility.
    if data.reason:
        reason = data.reason.strip()
        prefix = "[Refus client] "
        new_note = f"{prefix}{reason}"
        sm.notes = f"{sm.notes}\n{new_note}" if sm.notes else new_note

    # Propagate to prospect as "lost".
    if sm.contact_request_id:
        cr = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == sm.contact_request_id
                )
            )
        ).scalar_one_or_none()
        if cr is not None:
            cr.status = ContactRequestStatus.LOST.value

    await db.flush()
    await db.refresh(sm)
    return await public_read(token, db)
