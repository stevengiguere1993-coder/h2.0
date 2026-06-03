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

import logging
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
from app.models.devlog_soumission_module import DevlogSoumissionModule
from app.services.audit import log_action
from app.services.devlog_devis_calc import compute_devis
from app.services.devlog_soumission_pdf import (
    generate_devis_pdf,
    generate_signed_pdf,
)


router = APIRouter(prefix="/public/devlog/soumissions", tags=["devlog-public"])


# --------------------------- Schemas ---------------------------


class _PublicRecurringItem(BaseModel):
    """Item récurrent — vue client : libellé uniquement (pas de prix
    par item, pas de coût)."""

    description: str


class _PublicRecurringBlock(BaseModel):
    """Encadré « X $ / mois » + liste des libellés.

    ⚠️ ``total_client_amount`` est HT (sous-total avant taxes). Pour
    afficher le montant payé chaque mois par le client il faut utiliser
    ``total_client_amount_taxe`` (TTC, taxes Québec incluses). Avant la
    refonte mai 2026 #496 le frontend public utilisait à tort le HT —
    d'où l'écart visible entre la page publique et le PDF / vue admin.
    """

    total_client_amount: float
    items: list[_PublicRecurringItem]
    description: Optional[str] = None  # client_recurring_description override
    # Taxes Québec — TPS 5%, TVQ 9,975%. Toujours servies pour que le
    # frontend public puisse afficher le détail proprement.
    tps_amount: float = 0.0
    tvq_amount: float = 0.0
    tps_pct: float = 5.0
    tvq_pct: float = 9.975
    total_client_amount_taxe: float = 0.0


class _PublicFeatureClient(BaseModel):
    description: str
    prix_client: float


class _PublicFraisFixeClient(BaseModel):
    description: str
    prix_client: float


class _PublicModuleFeature(BaseModel):
    """Fonctionnalité d'un module — vue client : libellé + prix.

    ⚠️ Aucune heure, aucun coût interne. On ne sert JAMAIS les tâches
    du chargé de projet (``manager_task``) côté client."""

    description: str
    prix_client: float


class _PublicModule(BaseModel):
    """Module présenté au client (regroupement de fonctionnalités).

    * ``optional`` : le client peut le cocher/décocher (tous optionnels
      par défaut — pas de notion « obligatoire » dans le modèle).
    * ``selected`` : état courant (sert d'état initial des cases).
    * ``offert`` : module rendu gratuit par la règle « module → module »
      (un module déclencheur sélectionné). Prix client = 0, montré dans
      la section « Inclus gratuitement ».
    """

    id: int
    name: str
    selected: bool
    optional: bool = True
    offert: bool = False
    free_when_module_id: Optional[int] = None
    prix_client: float = 0.0
    features: list[_PublicModuleFeature]


class _PublicInitialBlock(BaseModel):
    """Bloc « Investissement initial » — facturé en one-shot.

    Idem : ``total_final`` reste le HT, et ``total_final_taxe`` est le
    TTC (taxes Québec incluses) à montrer au client comme prix final.
    """

    features: list[_PublicFeatureClient]
    frais_fixes: list[_PublicFraisFixeClient]
    total_final: float
    tps_amount: float = 0.0
    tvq_amount: float = 0.0
    tps_pct: float = 5.0
    tvq_pct: float = 9.975
    total_final_taxe: float = 0.0
    # --- Vue par MODULES (refonte 2026-06, Phase 4) -----------------
    # Présent uniquement si la soumission a des modules ; vide en mode
    # legacy (le frontend retombe alors sur la liste plate features /
    # frais_fixes ci-dessus — rétrocompat stricte). Les modules NON
    # sélectionnés n'apparaissent PAS dans ``features`` ci-dessus (ils
    # sont exclus du total) mais restent listés ici pour que le client
    # puisse les (re)cocher. Les modules offerts apparaissent ici avec
    # ``offert=True`` et ``prix_client=0``.
    modules: list[_PublicModule] = []
    # Y a-t-il au moins un module ? Permet au frontend de basculer en
    # mode « sélection interactive » sans ambiguïté.
    has_modules: bool = False


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
    # Sélection finale des modules au moment de la signature (Phase 4).
    # ``None`` => on garde la sélection déjà persistée (rétrocompat :
    # une soumission sans modules ignore ce champ). Liste vide => le
    # client a tout décoché.
    selected_module_ids: Optional[list[int]] = None


class SelectionRequest(BaseModel):
    """Mise à jour de la sélection des modules par le client (Phase 4).

    ``selected_module_ids`` = ids des modules cochés. Tout module non
    listé est marqué ``selected=False``. Idempotent / rejouable tant que
    la soumission n'est pas finalisée."""

    selected_module_ids: list[int] = Field(default_factory=list)


class PreviewRequest(SelectionRequest):
    """Recalcul à la volée (sans persistance) pour la sélection courante."""


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


async def _load_modules(
    db: AsyncSession, soumission_id: int
) -> list[DevlogSoumissionModule]:
    """Modules (Phase 2) — passés à ``compute_devis`` pour la sélection
    et la gratuité. Vide => chemin legacy (totaux inchangés)."""
    return list(
        (
            await db.execute(
                select(DevlogSoumissionModule).where(
                    DevlogSoumissionModule.soumission_id == soumission_id
                )
            )
        ).scalars().all()
    )


def _to_public_devis(
    devis: dict[str, Any],
    soumission: DevlogSoumission,
    items: Optional[list[DevlogSoumissionItem]] = None,
) -> PublicDevisPreview:
    """Filtre la sortie de ``compute_devis`` pour ne garder QUE les
    informations destinées au client. Aucun coût interne / marge / taux
    / heures ne doit subsister ici."""
    rec = devis.get("recurring") or {}
    init = devis.get("initial") or {}

    # --- Vue par modules ------------------------------------------------
    # ``init["modules"]`` (calculé par compute_devis) porte name / selected
    # / offert / free_when_module_id / prix_client. On rapatrie le
    # prix_client PAR FEATURE depuis ``features_client`` (indexé par id).
    feature_price_by_id: dict[Any, float] = {}
    for f in init.get("features_client") or []:
        fid = f.get("id")
        if fid is not None:
            feature_price_by_id[fid] = float(f.get("prix_client") or 0)

    # Liste COMPLÈTE des fonctionnalités par module, construite à partir
    # des items bruts (kind=feature uniquement). On ne se fie PAS au
    # ``features`` de compute_devis qui est vide pour un module non
    # sélectionné (ses items sont exclus du calcul) : le client doit voir
    # ce qu'il (re)cocherait. ⚠️ On EXCLUT explicitement ``manager_task``
    # — les tâches du chargé de projet ne sont jamais montrées au client.
    feat_descr_by_module: dict[int, list[DevlogSoumissionItem]] = {}
    if items:
        for it in items:
            kind = getattr(it, "item_kind", "feature") or "feature"
            if kind != "feature":
                continue
            mid = getattr(it, "module_id", None)
            if mid is None:
                continue
            feat_descr_by_module.setdefault(int(mid), []).append(it)

    public_modules: list[_PublicModule] = []
    for m in init.get("modules") or []:
        mid = m.get("id")
        if mid is None:
            continue
        is_free = bool(m.get("offert"))
        mod_features: list[_PublicModuleFeature] = []
        for it in feat_descr_by_module.get(int(mid), []):
            # Prix client par feature : 0 si module offert ou non
            # sélectionné (absent de features_client), sinon la part
            # calculée par compute_devis.
            fid = getattr(it, "id", None)
            prix = 0.0 if is_free else feature_price_by_id.get(fid, 0.0)
            mod_features.append(
                _PublicModuleFeature(
                    description=str(getattr(it, "description", "") or ""),
                    prix_client=float(prix),
                )
            )
        public_modules.append(
            _PublicModule(
                id=int(mid),
                name=str(m.get("name") or "Module"),
                selected=bool(m.get("selected")),
                # Tous les modules sont optionnels (pas de champ
                # « obligatoire » dans le modèle) -> tous décochables.
                optional=True,
                offert=is_free,
                free_when_module_id=m.get("free_when_module_id"),
                prix_client=float(m.get("prix_client") or 0),
                features=mod_features,
            )
        )

    return PublicDevisPreview(
        recurring=_PublicRecurringBlock(
            total_client_amount=float(rec.get("total_client_amount") or 0),
            items=[
                _PublicRecurringItem(description=str(it.get("description") or ""))
                for it in (rec.get("items_breakdown") or [])
            ],
            description=(soumission.client_recurring_description or None),
            tps_amount=float(rec.get("tps_amount") or 0),
            tvq_amount=float(rec.get("tvq_amount") or 0),
            tps_pct=float(rec.get("tps_pct") or 5.0),
            tvq_pct=float(rec.get("tvq_pct") or 9.975),
            total_client_amount_taxe=float(
                rec.get("total_client_amount_taxe") or 0
            ),
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
            tps_amount=float(init.get("tps_amount") or 0),
            tvq_amount=float(init.get("tvq_amount") or 0),
            tps_pct=float(init.get("tps_pct") or 5.0),
            tvq_pct=float(init.get("tvq_pct") or 9.975),
            total_final_taxe=float(init.get("total_final_taxe") or 0),
            modules=public_modules,
            has_modules=len(public_modules) > 0,
        ),
    )


def _apply_selection_override(
    modules: list[DevlogSoumissionModule],
    selected_module_ids: Optional[list[int]],
) -> None:
    """Applique IN-MEMORY une sélection client sur les modules chargés.

    Si ``selected_module_ids`` est ``None``, on ne touche à rien (on
    garde l'état persisté). Sinon, chaque module est ``selected=True``
    si son id figure dans la liste, ``False`` sinon. Mute les instances
    en place — à utiliser soit pour un preview (sans commit), soit juste
    avant de persister la sélection définitive."""
    if selected_module_ids is None:
        return
    wanted = {int(x) for x in selected_module_ids}
    for m in modules:
        m.selected = m.id in wanted


async def _to_public(
    db: AsyncSession,
    soumission: DevlogSoumission,
    selected_module_ids: Optional[list[int]] = None,
) -> PublicSoumission:
    client = await _load_client(db, soumission.client_id)
    items = await _load_items(db, soumission.id)
    modules = await _load_modules(db, soumission.id)
    # Override de sélection (preview interactif) : on mute les instances
    # chargées AVANT le calcul. Sans commit ici => purement éphémère pour
    # le preview ; pour la persistance, l'appelant commit ensuite.
    _apply_selection_override(modules, selected_module_ids)
    devis = compute_devis(soumission, items, modules)
    return PublicSoumission(
        id=soumission.id,
        status=soumission.status,
        title=soumission.title,
        client_name=(client.name if client else None),
        client_address=(client.address if client else None),
        sent_at=getattr(soumission, "sent_at", None),
        signed_at=getattr(soumission, "signed_at", None),
        signed_name=getattr(soumission, "signed_name", None),
        devis=_to_public_devis(devis, soumission, items),
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


@router.post(
    "/{token}/preview",
    response_model=PublicSoumission,
    summary="Recalcul à la volée des totaux pour une sélection (sans persister)",
)
async def preview_public_soumission(
    token: str,
    data: PreviewRequest,
    db: DBSession,
) -> PublicSoumission:
    """Recalcule les totaux (initial, taxes, total) pour la sélection de
    modules envoyée — SANS rien persister. Le token authentifie ; on
    refuse si la soumission est déjà signée/refusée (figée)."""
    soumission = await _load_by_token(db, token)
    if soumission.status in ("acceptee", "refusee"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cette soumission est déjà finalisée.",
        )
    # Calcule la vue publique avec la sélection demandée, mais sans
    # commit : les mutations in-memory sont jetées en fin de requête.
    return await _to_public(
        db, soumission, selected_module_ids=data.selected_module_ids
    )


@router.post(
    "/{token}/select",
    response_model=PublicSoumission,
    summary="Persister la sélection de modules du client",
)
async def select_public_soumission(
    token: str,
    data: SelectionRequest,
    db: DBSession,
) -> PublicSoumission:
    """Persiste la sélection courante des modules (état ``selected``).
    Utilisable avant la signature. Refuse si déjà finalisée."""
    soumission = await _load_by_token(db, token)
    if soumission.status in ("acceptee", "refusee"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cette soumission est déjà finalisée.",
        )
    modules = await _load_modules(db, soumission.id)
    _apply_selection_override(modules, data.selected_module_ids)
    await db.flush()
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

    # Persistance de la sélection finale (Phase 4) AVANT de figer le PDF
    # signé : on aligne l'état ``selected`` de chaque module sur ce que
    # le client a coché. ``None`` => on garde la sélection déjà
    # persistée (rétrocompat : soumission sans modules => no-op).
    if data.selected_module_ids is not None:
        modules = await _load_modules(db, soumission.id)
        _apply_selection_override(modules, data.selected_module_ids)
        await db.flush()

    soumission.signed_name = data.signed_name.strip()[:255]
    soumission.signed_at = datetime.now(timezone.utc)
    soumission.signed_ip = _client_ip(request)
    soumission.status = "acceptee" if data.accept else "refusee"
    await db.flush()
    await db.refresh(soumission)

    # PDF signé — figé au moment de la signature publique pour servir de
    # preuve d'audit immuable (IP + horodatage + nom dans un bandeau
    # vert proéminent). Stocké en BYTEA dans ``signed_pdf_blob`` ; le
    # endpoint admin ``GET /devlog/soumissions/{id}/signed-pdf`` le
    # restitue tel quel sans recalcul. Best-effort : si la génération
    # échoue (lib reportlab/pypdf indisponible), on n'échoue pas la
    # signature (la trace texte signed_at / signed_name / signed_ip
    # reste suffisante pour l'audit).
    if data.accept:
        try:
            pdf_bytes = await generate_signed_pdf(db, soumission.id)
            soumission.signed_pdf_blob = pdf_bytes
            await db.flush()
        except Exception:
            log_pdf = logging.getLogger(__name__)
            log_pdf.exception(
                "génération PDF signé soumission %s a échoué",
                soumission.id,
            )

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

    # Auto-flow closing : sur acceptation publique, on convertit le
    # prospect lié en client et on provisionne le projet — sinon la
    # soumission acceptée reste orpheline côté CRM. Best-effort : si
    # une étape rate, on n'échoue pas la signature (le client a déjà
    # signé, sa signature ne doit jamais être perdue).
    if data.accept:
        try:
            from app.api.v1.endpoints.devlog import (
                _ensure_client_for_soumission,
                _provision_project_for_soumission,
            )

            await _ensure_client_for_soumission(db, soumission, user=None)
            await _provision_project_for_soumission(
                db, soumission, user=None
            )
        except Exception:
            log_exc = logging.getLogger(__name__)
            log_exc.exception(
                "auto-flow soumission %s post-signature a échoué",
                soumission.id,
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
