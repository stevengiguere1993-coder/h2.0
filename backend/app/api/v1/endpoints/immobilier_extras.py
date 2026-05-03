"""Extensions immobilier — formulaires TAL, renouvellements, vue par
entreprise propriétaire."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import and_, func, select

from app.api.deps import CurrentUser, DBSession
from app.models.entreprise import Entreprise
from app.models.immobilier import (
    Bail,
    BailRenouvellement,
    BailStatus,
    Evaluation,
    EvaluationKind,
    Hypotheque,
    HypothequeStatus,
    Immeuble,
    ImmeubleOwnership,
    Logement,
    LogementStatus,
    Locataire,
)
from app.schemas.immobilier_extras import (
    EntrepriseImmobilierImmeubleItem,
    EntrepriseImmobilierSummary,
    EnvoyerRenouvellementRequest,
    EnvoyerRenouvellementResult,
    RenouvellementOverview,
    RenouvellementScanResult,
    TalFormRequest,
    TalFormType,
)
from app.services.bail_renouvellement import (
    scan_and_send_due_renouvellements,
    send_renouvellement_for_bail,
)
from app.services.tal_forms import (
    TalContext,
    available_form_types,
    generate_tal_pdf,
)


log = logging.getLogger(__name__)
router = APIRouter(prefix="/immobilier", tags=["immobilier"])


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion immobilière » non autorisé.",
        )


# ─── Catalogue des formulaires TAL ─────────────────────────────────────


_TAL_LABELS = {
    "avis_modification": (
        "Avis de modification du bail",
        "Avis officiel au locataire — hausse de loyer ou autre modification.",
    ),
    "avis_fin_bail": (
        "Avis de non-renouvellement",
        "Avis de reprise / éviction conformément aux articles 1959-1968 C.c.Q.",
    ),
    "rappel_paiement": (
        "Rappel amiable de paiement",
        "Premier rappel courtois pour un loyer en retard.",
    ),
    "mise_en_demeure": (
        "Mise en demeure (défaut de paiement)",
        "Mise en demeure formelle préalable à un recours TAL.",
    ),
    "sommaire_bail": (
        "Sommaire du bail",
        "Document interne récapitulant les conditions du bail courant.",
    ),
}


@router.get("/tal/forms", response_model=List[TalFormType])
async def list_tal_forms(user: CurrentUser) -> List[TalFormType]:
    _require_volet(user)
    out: List[TalFormType] = []
    for code in available_form_types():
        label, desc = _TAL_LABELS.get(code, (code.replace("_", " ").title(), ""))
        out.append(TalFormType(code=code, label=label, description=desc))
    return out


# ─── PDF generation pour un bail donné ─────────────────────────────────


async def _build_ctx_from_bail(
    db, bail: Bail, params: TalFormRequest
) -> TalContext:
    logement = await db.get(Logement, bail.logement_id)
    immeuble = await db.get(Immeuble, logement.immeuble_id) if logement else None
    locataire = await db.get(Locataire, bail.locataire_id)

    # Premier propriétaire enregistré comme locateur affiché
    locateur_nom = None
    if immeuble is not None:
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
        nouveau_loyer=params.nouveau_loyer,
        nouvelle_date_debut=params.nouvelle_date_debut
        or (bail.date_fin + timedelta(days=1) if bail.date_fin else None),
        nouvelle_date_fin=params.nouvelle_date_fin,
        motif_modification=params.motif,
        montant_du=params.montant_du,
        mois_concerne=params.mois_concerne,
        delai_paiement_jours=params.delai_paiement_jours or 10,
    )


@router.post("/baux/{bail_id}/tal/{form_type}.pdf")
async def generate_bail_tal_pdf(
    bail_id: int,
    form_type: str,
    payload: TalFormRequest,
    db: DBSession,
    user: CurrentUser,
) -> Response:
    _require_volet(user)
    if form_type not in available_form_types():
        raise HTTPException(status_code=400, detail="Type de formulaire inconnu.")
    bail = await db.get(Bail, bail_id)
    if bail is None:
        raise HTTPException(status_code=404, detail="Bail introuvable.")

    ctx = await _build_ctx_from_bail(db, bail, payload)
    pdf_bytes = generate_tal_pdf(form_type, ctx)
    filename = f"{form_type.replace('_', '-')}-bail-{bail_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


# ─── Renouvellements ──────────────────────────────────────────────────


@router.post(
    "/baux/{bail_id}/envoyer-renouvellement",
    response_model=EnvoyerRenouvellementResult,
)
async def envoyer_renouvellement(
    bail_id: int,
    payload: EnvoyerRenouvellementRequest,
    db: DBSession,
    user: CurrentUser,
) -> EnvoyerRenouvellementResult:
    """Génère + envoie l'avis de renouvellement pour un bail donné."""
    _require_volet(user)
    bail = await db.get(Bail, bail_id)
    if bail is None:
        raise HTTPException(status_code=404, detail="Bail introuvable.")

    obj, sent = await send_renouvellement_for_bail(
        db,
        bail,
        nouveau_loyer=payload.nouveau_loyer,
        nouvelle_date_debut=payload.nouvelle_date_debut,
        nouvelle_date_fin=payload.nouvelle_date_fin,
        motif=payload.motif,
        force=payload.force,
    )
    await db.commit()
    return EnvoyerRenouvellementResult(
        renouvellement_id=obj.id,
        courriel_envoye=sent,
        avis_envoye_le=obj.avis_envoye_le,
        nouveau_loyer=float(obj.nouveau_loyer) if obj.nouveau_loyer else None,
        nouvelle_date_debut=obj.nouvelle_date_debut,
        nouvelle_date_fin=obj.nouvelle_date_fin,
    )


@router.post(
    "/renouvellements/scan-batch",
    response_model=RenouvellementScanResult,
)
async def scan_renouvellements_now(
    db: DBSession, user: CurrentUser
) -> RenouvellementScanResult:
    """Déclenche manuellement le scan des baux à renouveler (4-6 mois)."""
    _require_volet(user)
    res = await scan_and_send_due_renouvellements(db)
    return RenouvellementScanResult(
        bails_scanned=res.bails_scanned,
        avis_crees=res.avis_crees,
        courriels_envoyes=res.courriels_envoyes,
        skipped=res.skipped,
        errors=res.errors or [],
    )


@router.get(
    "/renouvellements/overview",
    response_model=List[RenouvellementOverview],
)
async def renouvellements_overview(
    db: DBSession, user: CurrentUser
) -> List[RenouvellementOverview]:
    """Liste les baux actifs dont la fin tombe dans les 12 prochains mois,
    avec leur statut de renouvellement actuel."""
    _require_volet(user)
    today = date.today()
    horizon = today + timedelta(days=365)

    bails = (
        await db.execute(
            select(Bail).where(
                and_(
                    Bail.status == BailStatus.ACTIF.value,
                    Bail.date_fin >= today,
                    Bail.date_fin <= horizon,
                )
            ).order_by(Bail.date_fin.asc())
        )
    ).scalars().all()

    out: List[RenouvellementOverview] = []
    for b in bails:
        logement = await db.get(Logement, b.logement_id)
        immeuble = (
            await db.get(Immeuble, logement.immeuble_id) if logement else None
        )
        locataire = await db.get(Locataire, b.locataire_id)
        last_ren = (
            await db.execute(
                select(BailRenouvellement)
                .where(BailRenouvellement.bail_id == b.id)
                .order_by(BailRenouvellement.avis_envoye_le.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        delta = (b.date_fin - today).days
        if last_ren is not None:
            fenetre = "envoye"
        elif delta <= 90:
            fenetre = "imminente"
        elif 120 <= delta <= 180:
            fenetre = "a_envoyer"
        else:
            fenetre = "hors_fenetre"

        out.append(
            RenouvellementOverview(
                bail_id=b.id,
                immeuble_id=immeuble.id if immeuble else 0,
                immeuble_name=immeuble.name if immeuble else "—",
                logement_numero=logement.numero if logement else "—",
                locataire_nom=locataire.full_name if locataire else "—",
                locataire_email=locataire.email if locataire else None,
                bail_date_fin=b.date_fin,
                bail_loyer_mensuel=float(b.loyer_mensuel),
                jours_avant_fin=delta,
                fenetre=fenetre,
                avis_envoye_le=last_ren.avis_envoye_le if last_ren else None,
                nouveau_loyer=(
                    float(last_ren.nouveau_loyer)
                    if last_ren and last_ren.nouveau_loyer is not None
                    else None
                ),
                renouvellement_status=last_ren.status if last_ren else None,
            )
        )
    return out


# ─── Vue immobilier par entreprise propriétaire ────────────────────────


async def _compute_part_metrics(
    db, immeuble: Immeuble, ownership_pct: float
) -> tuple[int, int, float, float, float]:
    """Retourne (nb_actifs, nb_occ, revenu_part, valeur_part, balance_part)."""
    pct = ownership_pct / 100.0

    # Logements
    log_rows = (
        await db.execute(
            select(Logement.status, func.count(Logement.id))
            .where(Logement.immeuble_id == immeuble.id)
            .group_by(Logement.status)
        )
    ).all()
    sts = {st: int(n) for st, n in log_rows}
    nb_actifs = sum(
        n for st, n in sts.items() if st != LogementStatus.HORS_LOC.value
    )
    nb_occ = sts.get(LogementStatus.OCCUPE.value, 0)

    # Revenu mensuel total (Σ baux actifs)
    revenu = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(Bail.loyer_mensuel), 0))
                .join(Logement, Logement.id == Bail.logement_id)
                .where(
                    and_(
                        Logement.immeuble_id == immeuble.id,
                        Bail.status == BailStatus.ACTIF.value,
                    )
                )
            )
        ).scalar()
        or 0
    )

    # Valeur immeuble (eval la plus récente, fallback municipal puis prix achat)
    val = (
        await db.execute(
            select(Evaluation.valeur)
            .where(Evaluation.immeuble_id == immeuble.id)
            .order_by(Evaluation.date_evaluation.desc())
            .limit(1)
        )
    ).scalar()
    if val is None:
        val = (
            await db.execute(
                select(Evaluation.valeur)
                .where(
                    and_(
                        Evaluation.immeuble_id == immeuble.id,
                        Evaluation.kind == EvaluationKind.MUNICIPALE.value,
                    )
                )
                .order_by(Evaluation.date_evaluation.desc())
                .limit(1)
            )
        ).scalar()
    if val is None and immeuble.purchase_price is not None:
        val = immeuble.purchase_price
    valeur_imm = float(val) if val is not None else 0.0

    # Hypothèque active
    balance_hyp = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(Hypotheque.balance_actuelle), 0))
                .where(
                    and_(
                        Hypotheque.immeuble_id == immeuble.id,
                        Hypotheque.status == HypothequeStatus.ACTIVE.value,
                    )
                )
            )
        ).scalar()
        or 0
    )

    return (
        nb_actifs,
        nb_occ,
        round(revenu * pct, 2),
        round(valeur_imm * pct, 2),
        round(balance_hyp * pct, 2),
    )


@router.get(
    "/par-entreprise/{entreprise_id}",
    response_model=EntrepriseImmobilierSummary,
)
async def entreprise_immobilier_summary(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> EntrepriseImmobilierSummary:
    """Vue immobilière consolidée pour une entreprise propriétaire."""
    _require_volet(user)
    ent = await db.get(Entreprise, entreprise_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Entreprise introuvable.")

    ownerships = (
        await db.execute(
            select(ImmeubleOwnership).where(
                ImmeubleOwnership.entreprise_id == entreprise_id
            )
        )
    ).scalars().all()

    items: List[EntrepriseImmobilierImmeubleItem] = []
    total_nb_actifs = 0
    total_nb_occ = 0
    total_revenu = 0.0
    total_valeur = 0.0
    total_balance = 0.0

    for o in ownerships:
        imm = await db.get(Immeuble, o.immeuble_id)
        if imm is None:
            continue
        pct = float(o.ownership_pct or 0)
        nb_a, nb_o, rev_part, val_part, bal_part = await _compute_part_metrics(
            db, imm, pct
        )
        items.append(
            EntrepriseImmobilierImmeubleItem(
                immeuble_id=imm.id,
                name=imm.name,
                address=imm.address,
                city=imm.city,
                cover_photo_url=imm.cover_photo_url,
                ownership_pct=pct,
                nb_logements_actifs=nb_a,
                nb_logements_occupes=nb_o,
                revenu_mensuel_part=rev_part,
                valeur_part=val_part,
                balance_hyp_part=bal_part,
            )
        )
        total_nb_actifs += nb_a
        total_nb_occ += nb_o
        total_revenu += rev_part
        total_valeur += val_part
        total_balance += bal_part

    taux = (total_nb_occ / total_nb_actifs) if total_nb_actifs > 0 else 0.0
    return EntrepriseImmobilierSummary(
        entreprise_id=entreprise_id,
        nb_immeubles=len(items),
        nb_logements_actifs=total_nb_actifs,
        nb_logements_occupes=total_nb_occ,
        taux_occupation=round(taux, 4),
        revenu_mensuel_part=round(total_revenu, 2),
        revenu_annuel_part=round(total_revenu * 12, 2),
        valeur_portefeuille_part=round(total_valeur, 2),
        balance_hypothecaire_part=round(total_balance, 2),
        equity_part=round(total_valeur - total_balance, 2),
        immeubles=items,
    )
