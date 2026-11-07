"""Documents de l'espace investisseur — règles communes à la console
admin et au portail (Steven, 2026-11-07 : « déposer des documents dans
leur espace investisseur et les visualiser »).

- Types acceptés : PDF, images (JPEG / PNG / WebP / HEIC), Word, Excel.
- Taille maximale : 25 Mo.
- Un document est PARTAGÉ (``destinataire_user_id`` NULL → tous les
  investisseurs de la compagnie) ou PRIVÉ (un seul compte). Un dépôt
  par l'investisseur est toujours privé à lui et signalé aux admins.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invest_portal import InvestDocument
from app.models.user import User

DOC_MAX_BYTES = 25 * 1024 * 1024

#: content-type accepté → extension de fichier servie.
TYPES_ACCEPTES: dict[str, str] = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}

#: Extension → content-type (quand le navigateur n'en envoie pas).
_PAR_EXTENSION = {v: k for k, v in TYPES_ACCEPTES.items()}
_PAR_EXTENSION["jpeg"] = "image/jpeg"

KIND_DEPOT = "invest_document_depose"


def type_de(file: UploadFile) -> str:
    """Content-type normalisé du fichier téléversé, ou 415."""
    ct = (file.content_type or "").split(";")[0].strip().lower()
    if ct not in TYPES_ACCEPTES:
        ext = (file.filename or "").rsplit(".", 1)[-1].lower()
        ct = _PAR_EXTENSION.get(ext, "")
    if ct not in TYPES_ACCEPTES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Type de fichier refusé — PDF, image (JPEG, PNG, WebP, HEIC), "
            "Word ou Excel seulement.",
        )
    return ct


async def lire_fichier(file: UploadFile) -> bytes:
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
    if len(blob) > DOC_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Document trop volumineux (max 25 Mo).",
        )
    return blob


def titre_de(filename: Optional[str], defaut: str = "document") -> str:
    base = (filename or defaut).rsplit("/", 1)[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return (base.strip() or defaut)[:255]


def nom_fichier(doc: InvestDocument) -> str:
    ext = TYPES_ACCEPTES.get((doc.content_type or "").lower(), "pdf")
    propre = "".join(
        ch for ch in (doc.title or "document") if ch.isalnum() or ch in "._- "
    ).strip() or "document"
    return f"{propre}.{ext}"


def entetes_inline(doc: InvestDocument) -> dict:
    return {"Content-Disposition": f'inline; filename="{nom_fichier(doc)}"'}


def _nom_user(u: Optional[User]) -> Optional[str]:
    if u is None:
        return None
    return f"{u.first_name or ''} {u.last_name or ''}".strip() or u.email


async def document_payload(
    db: AsyncSession,
    doc: InvestDocument,
    *,
    pour_user_id: Optional[int] = None,
    entreprise_name: Optional[str] = None,
    users: Optional[dict[int, User]] = None,
) -> dict:
    """Forme commune d'un document (console admin et portail)."""
    users = users if users is not None else {}

    async def _u(uid: Optional[int]) -> Optional[User]:
        if not uid:
            return None
        if uid not in users:
            users[uid] = await db.get(User, uid)
        return users[uid]

    dest = await _u(doc.destinataire_user_id)
    par = await _u(doc.uploaded_by_user_id)
    return {
        "id": doc.id,
        "entreprise_id": doc.entreprise_id,
        "entreprise_name": entreprise_name,
        "title": doc.title,
        "source": doc.source,
        "content_type": doc.content_type,
        "extension": TYPES_ACCEPTES.get(
            (doc.content_type or "").lower(), "pdf"
        ),
        "size_bytes": doc.size_bytes,
        "note": doc.note,
        "prive": doc.destinataire_user_id is not None,
        "destinataire_user_id": doc.destinataire_user_id,
        "destinataire_name": _nom_user(dest),
        "depose_par_investisseur": doc.source == "investisseur",
        "depose_par_name": _nom_user(par),
        "depose_par_moi": bool(
            pour_user_id and doc.uploaded_by_user_id == pour_user_id
        ),
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


async def documents_visibles(
    db: AsyncSession, entreprise_id: int, user_id: int
) -> list[InvestDocument]:
    """Documents d'une compagnie que CE compte peut voir : partagés +
    privés qui lui sont destinés (``user_id`` 0 = aperçu sans compte :
    partagés seulement)."""
    q = select(InvestDocument).where(
        InvestDocument.entreprise_id == entreprise_id
    )
    if user_id:
        q = q.where(
            (InvestDocument.destinataire_user_id.is_(None))
            | (InvestDocument.destinataire_user_id == user_id)
        )
    else:
        q = q.where(InvestDocument.destinataire_user_id.is_(None))
    return list(
        (await db.execute(q.order_by(InvestDocument.id.desc()))).scalars()
    )


def peut_voir(doc: InvestDocument, user_id: int) -> bool:
    """Sans préjuger de l'accès au projet : un privé n'est lisible que
    par son destinataire."""
    return doc.destinataire_user_id is None or (
        bool(user_id) and doc.destinataire_user_id == user_id
    )


async def prevenir_admins_du_depot(
    db: AsyncSession,
    *,
    doc: InvestDocument,
    deposant: User,
    entreprise_name: str,
) -> None:
    """Cloche + push aux admins : « X a déposé un document » — lien
    vers la console du projet."""
    from app.services.notifications import notify_role

    nom = _nom_user(deposant) or deposant.email
    try:
        await notify_role(
            db,
            min_role="admin",
            kind=KIND_DEPOT,
            title=f"Document déposé par {nom}",
            body=(
                f"« {doc.title} » dans l'espace investisseur de "
                f"{entreprise_name}"
                + (f" — {doc.note}" if doc.note else "")
            ),
            href=f"/investisseur/admin/projet/{doc.entreprise_id}",
        )
    except Exception:  # noqa: BLE001 — la notification ne bloque pas le dépôt
        import logging

        logging.getLogger(__name__).exception(
            "notification de dépôt investisseur échouée"
        )
