"""Documents PERSONNALISÉS de gestion locative (retour Steven 2026-07-20).

Règlement d'immeuble, contrat de chambreur… des modèles maison créés
depuis Paramètres → Modèles de documents, générés depuis un bail (mêmes
{variables} que les lettres, **gras** supporté) OU un PDF téléversé
utilisé tel quel. Le document généré est conservé (ImmDocument) puis
envoyable pour signature en ligne — ou par simple courriel avec suivi
d'ouverture si le modèle décoche « signature requise ».

    GET/POST/PUT/DELETE  /immobilier/docs-perso/modeles[/{id}]
    POST/DELETE          /immobilier/docs-perso/modeles/{id}/pdf
    GET                  /immobilier/docs-perso/modeles/{id}/apercu.pdf
    POST                 /immobilier/baux/{bail_id}/docs-perso/{id}
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.api.deps import CurrentUser, DBSession
from app.models.immobilier import Bail, ImmDocPersoModele
from app.services.tal_forms import (
    PERSO_VARIABLES,
    TalContext,
    generate_perso_pdf,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/immobilier", tags=["immobilier-docs-perso"])


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion immobilière » non autorisé.",
        )


# ─── Schemas ───────────────────────────────────────────────────────────


class ModeleRead(BaseModel):
    id: int
    nom: str
    titre: Optional[str] = None
    corps: Optional[str] = None
    signature_requise: bool = True
    pdf_filename: Optional[str] = None
    has_pdf: bool = False
    variables: List[str] = []


class ModeleWrite(BaseModel):
    nom: str = Field(..., min_length=1, max_length=120)
    titre: Optional[str] = Field(default=None, max_length=200)
    corps: Optional[str] = None
    signature_requise: bool = True


def _read(m: ImmDocPersoModele, has_pdf: bool) -> ModeleRead:
    return ModeleRead(
        id=m.id,
        nom=m.nom,
        titre=m.titre,
        corps=m.corps,
        signature_requise=bool(m.signature_requise),
        pdf_filename=m.pdf_filename,
        has_pdf=has_pdf,
        variables=list(PERSO_VARIABLES),
    )


def _paragraphes(corps: Optional[str]) -> list[str]:
    """Corps texte → paragraphes (séparés par une ligne vide)."""
    if not corps:
        return []
    return [p.strip() for p in corps.replace("\r\n", "\n").split("\n\n")]


# ─── CRUD des modèles ──────────────────────────────────────────────────


@router.get("/docs-perso/modeles", response_model=List[ModeleRead])
async def list_modeles(db: DBSession, user: CurrentUser) -> List[ModeleRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(ImmDocPersoModele).order_by(ImmDocPersoModele.nom.asc())
        )
    ).scalars().all()
    return [_read(m, m.pdf_filename is not None) for m in rows]


@router.post(
    "/docs-perso/modeles",
    response_model=ModeleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_modele(
    payload: ModeleWrite, db: DBSession, user: CurrentUser
) -> ModeleRead:
    _require_volet(user)
    dup = (
        await db.execute(
            select(ImmDocPersoModele).where(
                ImmDocPersoModele.nom == payload.nom.strip()
            )
        )
    ).scalars().first()
    if dup is not None:
        raise HTTPException(
            status_code=409, detail="Un modèle porte déjà ce nom."
        )
    obj = ImmDocPersoModele(
        nom=payload.nom.strip(),
        titre=(payload.titre or "").strip() or None,
        corps=payload.corps,
        signature_requise=payload.signature_requise,
        created_by_email=getattr(user, "email", None),
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _read(obj, False)


@router.put("/docs-perso/modeles/{modele_id}", response_model=ModeleRead)
async def update_modele(
    modele_id: int, payload: ModeleWrite, db: DBSession, user: CurrentUser
) -> ModeleRead:
    _require_volet(user)
    obj = await db.get(ImmDocPersoModele, modele_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Modèle introuvable.")
    obj.nom = payload.nom.strip()
    obj.titre = (payload.titre or "").strip() or None
    obj.corps = payload.corps
    obj.signature_requise = payload.signature_requise
    await db.commit()
    await db.refresh(obj)
    return _read(obj, obj.pdf_filename is not None)


@router.delete(
    "/docs-perso/modeles/{modele_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_modele(
    modele_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(ImmDocPersoModele, modele_id)
    if obj is not None:
        await db.delete(obj)
        await db.commit()


@router.post("/docs-perso/modeles/{modele_id}/pdf", response_model=ModeleRead)
async def upload_modele_pdf(
    modele_id: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> ModeleRead:
    """PDF utilisé TEL QUEL à la génération (pas de variables) — pour un
    règlement d'immeuble déjà mis en page, par exemple."""
    _require_volet(user)
    obj = await db.get(ImmDocPersoModele, modele_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Modèle introuvable.")
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Le fichier doit être un PDF.")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF trop volumineux (max 15 Mo).")
    obj.pdf_blob = data
    obj.pdf_filename = (file.filename or "modele.pdf")[:255]
    await db.commit()
    await db.refresh(obj)
    return _read(obj, True)


@router.delete(
    "/docs-perso/modeles/{modele_id}/pdf", response_model=ModeleRead
)
async def delete_modele_pdf(
    modele_id: int, db: DBSession, user: CurrentUser
) -> ModeleRead:
    """Retire le PDF téléversé — le modèle redevient un modèle TEXTE."""
    _require_volet(user)
    obj = await db.get(ImmDocPersoModele, modele_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Modèle introuvable.")
    obj.pdf_blob = None
    obj.pdf_filename = None
    await db.commit()
    await db.refresh(obj)
    return _read(obj, False)


# ─── Aperçu + génération depuis un bail ────────────────────────────────


async def _modele_avec_blob(db, modele_id: int) -> ImmDocPersoModele:
    obj = (
        await db.execute(
            select(ImmDocPersoModele)
            .options(undefer(ImmDocPersoModele.pdf_blob))
            .where(ImmDocPersoModele.id == modele_id)
        )
    ).scalars().first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Modèle introuvable.")
    return obj


def _demo_ctx() -> TalContext:
    debut = date.today().replace(day=1)
    return TalContext(
        locateur_nom="Horizon Services Immobiliers (exemple)",
        locateur_adresse="158 rue Maurice, Saint-Rémi (Québec) J0L 2L0",
        locataire_nom="Jean Tremblay (exemple)",
        logement_adresse="123 rue Exemple",
        logement_numero="App. 4",
        logement_ville="Montréal",
        bail_date_debut=debut,
        bail_date_fin=debut + timedelta(days=364),
        bail_loyer_mensuel=1250.0,
    )


def _rendre_pdf(obj: ImmDocPersoModele, ctx: TalContext) -> bytes:
    if obj.pdf_blob:
        return bytes(obj.pdf_blob)
    return generate_perso_pdf(
        obj.titre or obj.nom, _paragraphes(obj.corps), ctx
    )


@router.get("/docs-perso/modeles/{modele_id}/apercu.pdf")
async def apercu_modele(
    modele_id: int, db: DBSession, user: CurrentUser
):
    from fastapi import Response

    _require_volet(user)
    obj = await _modele_avec_blob(db, modele_id)
    pdf = _rendre_pdf(obj, _demo_ctx())
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="apercu-{obj.id}.pdf"'
        },
    )


class GenererResult(BaseModel):
    document_id: int
    titre: str
    signature_requise: bool


@router.post(
    "/baux/{bail_id}/docs-perso/{modele_id}",
    response_model=GenererResult,
)
async def generer_pour_bail(
    bail_id: int, modele_id: int, db: DBSession, user: CurrentUser
) -> GenererResult:
    """Génère le document pour un bail et le CONSERVE (ImmDocument) —
    il apparaît dans la section Documents, prêt à envoyer."""
    _require_volet(user)
    bail = await db.get(Bail, bail_id)
    if bail is None:
        raise HTTPException(status_code=404, detail="Bail introuvable.")
    obj = await _modele_avec_blob(db, modele_id)

    from app.api.v1.endpoints.immobilier_documents import save_document
    from app.api.v1.endpoints.immobilier_extras import _build_ctx_from_bail
    from app.schemas.immobilier_extras import TalFormRequest
    from app.models.immobilier import Logement

    ctx = await _build_ctx_from_bail(db, bail, TalFormRequest())
    pdf = _rendre_pdf(obj, ctx)

    logement = await db.get(Logement, bail.logement_id)
    doc = await save_document(
        db,
        bail_id=bail.id,
        locataire_id=bail.locataire_id,
        immeuble_id=logement.immeuble_id if logement else None,
        doc_type=(
            "personnalise" if obj.signature_requise else "personnalise_info"
        ),
        titre=obj.titre or obj.nom,
        params={"modele_id": obj.id, "modele_nom": obj.nom},
        pdf=pdf,
        created_by_email=getattr(user, "email", None),
    )
    await db.commit()
    return GenererResult(
        document_id=doc.id,
        titre=obj.titre or obj.nom,
        signature_requise=bool(obj.signature_requise),
    )
