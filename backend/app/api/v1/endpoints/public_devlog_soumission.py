"""Endpoints publics (no auth) — signature d'une soumission devis_dev.

Flow client :

    GET  /api/v1/public/devlog/soumissions/{token}        -> JSON
    GET  /api/v1/public/devlog/soumissions/{token}/pdf    -> PDF
    POST /api/v1/public/devlog/soumissions/{token}/sign   -> {signed_name, accept}

Le token est opaque (32 octets URL-safe) et fait office
d'authentification + audit trail (IP + nom + heure capturés).

Si ``accept=True`` → ``status='acceptee'`` ; si ``accept=False`` →
``status='refusee'``. Idempotent : un appel ``sign`` sur une
soumission déjà signée ou refusée renvoie l'état courant sans
réécrire (pas de 409 — pattern aligné sur ``public_contracts``).

⚠️ La réponse JSON publique exclut tout détail interne (coûts,
marges, taux, heures). On expose la vue client de ``compute_devis``
uniquement (libellés + ``prix_client`` + total).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.models.devlog_client import DevlogClient
from app.models.devlog_soumission import DevlogSoumission
from app.models.devlog_soumission_item import DevlogSoumissionItem
from app.services.audit import log_action
from app.services.devlog_devis_calc import compute_devis
from app.services.devlog_soumission_pdf import generate_devis_pdf


router = APIRouter(prefix="/public/devlog/soumissions", tags=["devlog-public"])


# --------------------------- Schemas ---------------------------


class _PublicRecurringItem(BaseModel):
    """Item récurrent — vue client : libellé uniquement (pas de prix
    par item, pas de coût)."""

    description: str


class _PublicRecurringBlock(BaseModel):
    """Encadré « X $ / mois » + liste des libellés."""

    total_client_amount: float
    items: list[_PublicRecurringItem]
    description: Optional[str] = None  # client_recurring_description override


class _PublicFeatureClient(BaseModel):
    description: str
    prix_client: float


class _PublicFraisFixeClient(BaseModel):
    description: str
    prix_client: float


class _PublicInitialBlock(BaseModel):
    features: list[_PublicFeatureClient]
    frais_fixes: list[_PublicFraisFixeClient]
    total_final: float


class PublicDevisPreview(BaseModel):
    """Vue client filtrée — aucun coût interne / marge / taux."""

    recurring: _PublicRecurringBlock
    initial: _PublicInitialBlock


class PublicSoumission(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    title: str
    client_name: Optional[str]
    client_address: Optional[str]
    sent_at: Optional[datetime]
    signed_at: Optional[datetime]
    signed_name: Optional[str]
    devis: PublicDevisPreview


class SignRequest(BaseModel):
    signed_name: str = Field(..., min_length=2, max_length=255)
    accept: bool


# --------------------------- Helpers ---------------------------


def _client_ip(request: Request) -> Optional[str]:
    raw = (
        request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else None)
    )
    if raw:
        return raw.split(",")[0].strip()[:64]
    return None


async def _load_by_token(
    db: AsyncSession, token: str
) -> DevlogSoumission:
    soumission = (
        await db.execute(
            select(DevlogSoumission).where(
                DevlogSoumission.signature_token == token
            )
        )
    ).scalar_one_or_none()
    if soumission is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Lien invalide ou expiré."
        )
    if not getattr(soumission, "is_devis_dev", False):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Lien invalide."
        )
    return soumission


async def _load_client(
    db: AsyncSession, client_id: Optional[int]
) -> Optional[DevlogClient]:
    if client_id is None:
        return None
    return (
        await db.execute(
            select(DevlogClient).where(DevlogClient.id == client_id)
        )
    ).scalar_one_or_none()


async def _load_items(
    db: AsyncSession, soumission_id: int
) -> list[DevlogSoumissionItem]:
    return list(
        (
            await db.execute(
                select(DevlogSoumissionItem)
                .where(DevlogSoumissionItem.soumission_id == soumission_id)
                .order_by(
                    DevlogSoumissionItem.position.asc(),
                    DevlogSoumissionItem.id.asc(),
                )
            )
        ).scalars().all()
    )


def _to_public_devis(devis: dict[str, Any], soumission: DevlogSoumission) -> PublicDevisPreview:
    """Filtre la sortie de ``compute_devis`` pour ne garder QUE les
    informations destinées au client. Aucun coût interne / marge / taux
    / heures ne doit subsister ici."""
    rec = devis.get("recurring") or {}
    init = devis.get("initial") or {}
    return PublicDevisPreview(
        recurring=_PublicRecurringBlock(
            total_client_amount=float(rec.get("total_client_amount") or 0),
            items=[
                _PublicRecurringItem(description=str(it.get("description") or ""))
                for it in (rec.get("items_breakdown") or [])
            ],
            description=(soumission.client_recurring_description or None),
        ),
        initial=_PublicInitialBlock(
            features=[
                _PublicFeatureClient(
                    description=str(f.get("description") or ""),
                    prix_client=float(f.get("prix_client") or 0),
                )
                for f in (init.get("features_client") or [])
            ],
            frais_fixes=[
                _PublicFraisFixeClient(
                    description=str(ff.get("description") or ""),
                    prix_client=float(ff.get("prix_client") or 0),
                )
                for ff in (init.get("frais_fixes_client") or [])
            ],
            total_final=float(init.get("total_final") or 0),
        ),
    )


async def _to_public(
    db: AsyncSession, soumission: DevlogSoumission
) -> PublicSoumission:
    client = await _load_client(db, soumission.client_id)
    items = await _load_items(db, soumission.id)
    devis = compute_devis(soumission, items)
    return PublicSoumission(
        id=soumission.id,
        status=soumission.status,
        title=soumission.title,
        client_name=(client.name if client else None),
        client_address=(client.address if client else None),
        sent_at=getattr(soumission, "sent_at", None),
        signed_at=getattr(soumission, "signed_at", None),
        signed_name=getattr(soumission, "signed_name", None),
        devis=_to_public_devis(devis, soumission),
    )


# --------------------------- Routes ---------------------------


@router.get(
    "/{token}",
    response_model=PublicSoumission,
    summary="Détails publics de la soumission (page de signature)",
)
async def read_public_soumission(
    token: str, db: DBSession
) -> PublicSoumission:
    soumission = await _load_by_token(db, token)
    return await _to_public(db, soumission)


@router.get(
    "/{token}/pdf",
    summary="PDF inline (page publique)",
)
async def public_soumission_pdf(
    token: str, db: DBSession
) -> Response:
    soumission = await _load_by_token(db, token)
    pdf_bytes = await generate_devis_pdf(db, soumission.id)
    filename = f"soumission-devlog-{soumission.id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post(
    "/{token}/sign",
    response_model=PublicSoumission,
    summary="Signer (accepter) ou refuser la soumission",
)
async def sign_public_soumission(
    token: str,
    data: SignRequest,
    request: Request,
    db: DBSession,
) -> PublicSoumission:
    soumission = await _load_by_token(db, token)
    # Idempotent : si déjà finalisée, on renvoie l'état courant.
    if soumission.status in ("acceptee", "refusee"):
        return await _to_public(db, soumission)

    soumission.signed_name = data.signed_name.strip()[:255]
    soumission.signed_at = datetime.now(timezone.utc)
    soumission.signed_ip = _client_ip(request)
    soumission.status = "acceptee" if data.accept else "refusee"
    await db.flush()
    await db.refresh(soumission)

    # Audit trail (action publique - user=None, IP capturee dans details).
    await log_action(
        db,
        user=None,
        action=(
            "devlog_soumission.signed"
            if data.accept
            else "devlog_soumission.refused"
        ),
        entity_type="devlog_soumission",
        entity_id=soumission.id,
        details={
            "signed_name": soumission.signed_name,
            "signed_ip": soumission.signed_ip,
            "accept": data.accept,
        },
    )

    # Notification interne best-effort (ne fait pas échouer la signature).
    try:
        from app.services.notifications import notify_role

        if data.accept:
            await notify_role(
                db,
                min_role="manager",
                kind="devlog.soumission.signed",
                title=f"Soumission devlog #{soumission.id} acceptée",
                body=f"Acceptée par {soumission.signed_name}.",
                href=f"/dev-logiciel/soumissions/{soumission.id}",
            )
        else:
            await notify_role(
                db,
                min_role="manager",
                kind="devlog.soumission.rejected",
                title=f"Soumission devlog #{soumission.id} refusée",
                body=f"Refusée par {soumission.signed_name}.",
                href=f"/dev-logiciel/soumissions/{soumission.id}",
            )
    except Exception:
        pass

    return await _to_public(db, soumission)
