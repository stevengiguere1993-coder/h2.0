"""Import Excel d'un immeuble complet — Gestion locative.

    GET  /immobilier/import-excel/modele  → modèle .xlsx à remplir
    POST /immobilier/import-excel         → upload + création tout-ou-rien

Le POST crée en UNE transaction : immeuble (+ ownership 100 % à
l'entreprise choisie), hypothèques, logements, locataires et baux. La
moindre erreur de fichier → 400 avec la liste complète (feuille + ligne),
rien n'est créé.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.models.entreprise import Entreprise
from app.models.immobilier import (
    Bail,
    BailStatus,
    Hypotheque,
    HypothequeStatus,
    Immeuble,
    ImmeubleOwnership,
    Locataire,
    Logement,
    LogementStatus,
)
from app.services.hypotheque_calc import taux_mensuel
from app.services.immeuble_excel import (
    ImportErreurs,
    generate_template,
    parse_workbook,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/immobilier", tags=["immobilier-import"])

_XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
_MAX_BYTES = 5 * 1024 * 1024  # 5 Mo — largement assez pour un formulaire


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion immobilière » non autorisé.",
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/import-excel/modele")
async def download_modele(user: CurrentUser) -> Response:
    _require_volet(user)
    blob = generate_template()
    return Response(
        content=blob,
        media_type=_XLSX_MIME,
        headers={
            "Content-Disposition": (
                'attachment; filename="modele-immeuble-kratos.xlsx"'
            )
        },
    )


class ImportResult(BaseModel):
    immeuble_id: int
    immeuble_name: str
    nb_hypotheques: int
    nb_logements: int
    nb_locataires: int
    nb_baux: int


@router.post("/import-excel", response_model=ImportResult)
async def import_excel(
    db: DBSession,
    user: CurrentUser,
    entreprise_id: int = Form(...),
    file: UploadFile = File(...),
) -> ImportResult:
    _require_volet(user)

    ent = await db.get(Entreprise, entreprise_id)
    if ent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entreprise propriétaire introuvable.",
        )

    blob = await file.read()
    if len(blob) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Fichier trop volumineux (max 5 Mo).",
        )

    try:
        data = parse_workbook(blob)
    except ImportErreurs as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"erreurs": exc.erreurs},
        )

    # Garde-fou métier : au plus UN bail actif/futur par logement (les
    # baux passés deviennent « terminé » et peuvent se cumuler).
    today = date.today()
    actifs_par_logement: dict[str, int] = {}
    for b in data.baux:
        if b.date_fin >= today:
            k = b.logement_numero.lower()
            actifs_par_logement[k] = actifs_par_logement.get(k, 0) + 1
    doubles = [k for k, n in actifs_par_logement.items() if n > 1]
    if doubles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "erreurs": [
                    f"Logement « {k} » : plusieurs baux actifs (en cours ou "
                    "futurs) — un seul bail actif par logement."
                    for k in doubles
                ]
            },
        )

    # ── Création (une seule transaction, commit à la fin) ──
    imm_data = dict(data.immeuble)
    addr = imm_data.get("address") or ""
    city = imm_data.get("city")
    imm = Immeuble(**imm_data, name=f"{addr}, {city}" if city else addr)
    imm.created_at = _now()
    imm.updated_at = _now()
    db.add(imm)
    await db.flush()

    db.add(
        ImmeubleOwnership(
            immeuble_id=imm.id,
            entreprise_id=entreprise_id,
            ownership_pct=100.0,
        )
    )

    for h in data.hypotheques:
        pmt = h.paiement_mensuel
        if (
            pmt is None
            and h.taux_pct is not None
            and h.amortissement_mois
            and h.montant_initial > 0
        ):
            # Même math que la fiche : paiement calculé depuis le principal.
            principal = (
                h.balance_actuelle
                if h.balance_actuelle is not None
                else h.montant_initial
            )
            i = taux_mensuel(h.taux_pct, h.composition_interets)
            if i > 0:
                pmt = round(
                    principal * i / (1.0 - (1.0 + i) ** (-h.amortissement_mois)),
                    2,
                )
            elif h.amortissement_mois:
                pmt = round(principal / h.amortissement_mois, 2)
        db.add(
            Hypotheque(
                immeuble_id=imm.id,
                rang=h.rang,
                preteur=h.preteur,
                montant_initial=h.montant_initial,
                balance_actuelle=h.balance_actuelle,
                taux_pct=h.taux_pct,
                type_taux=h.type_taux,
                composition_interets=h.composition_interets,
                amortissement_mois=h.amortissement_mois,
                date_debut=h.date_debut,
                date_fin_terme=h.date_fin_terme,
                paiement_mensuel=pmt,
                status=HypothequeStatus.ACTIVE.value,
            )
        )

    logements_par_numero: dict[str, Logement] = {}
    for lg in data.logements:
        obj = Logement(
            immeuble_id=imm.id,
            numero=lg.numero,
            nb_pieces_decimal=lg.nb_pieces_decimal,
            nb_chambres=lg.nb_chambres,
            nb_sdb=lg.nb_sdb,
            superficie_pi2=lg.superficie_pi2,
            etage=lg.etage,
            loyer_demande=lg.loyer_demande,
            notes=lg.notes,
            status=LogementStatus.VACANT.value,
        )
        db.add(obj)
        logements_par_numero[lg.numero.lower()] = obj
    await db.flush()

    nb_locataires = 0
    nb_baux = 0
    for b in data.baux:
        logement = logements_par_numero[b.logement_numero.lower()]
        locataire = Locataire(
            full_name=b.full_name,
            email=b.email,
            phone=b.phone,
            notes=b.notes,
        )
        db.add(locataire)
        await db.flush()
        nb_locataires += 1

        if b.date_fin < today:
            bail_status = BailStatus.TERMINE.value
        elif b.date_debut > today:
            bail_status = BailStatus.PROPOSE.value
        else:
            bail_status = BailStatus.ACTIF.value
        db.add(
            Bail(
                logement_id=logement.id,
                locataire_id=locataire.id,
                date_debut=b.date_debut,
                date_fin=b.date_fin,
                loyer_mensuel=b.loyer_mensuel,
                depot_garantie=b.depot_garantie,
                status=bail_status,
            )
        )
        nb_baux += 1
        if bail_status == BailStatus.ACTIF.value:
            logement.status = LogementStatus.OCCUPE.value
        elif (
            bail_status == BailStatus.PROPOSE.value
            and logement.status == LogementStatus.VACANT.value
        ):
            logement.status = LogementStatus.RESERVE.value

    await db.commit()
    await db.refresh(imm)
    log.info(
        "Import Excel immeuble #%s (« %s ») par user #%s : %s hypo, %s "
        "logements, %s baux",
        imm.id, imm.name, user.id, len(data.hypotheques),
        len(data.logements), nb_baux,
    )
    return ImportResult(
        immeuble_id=imm.id,
        immeuble_name=imm.name,
        nb_hypotheques=len(data.hypotheques),
        nb_logements=len(data.logements),
        nb_locataires=nb_locataires,
        nb_baux=nb_baux,
    )
