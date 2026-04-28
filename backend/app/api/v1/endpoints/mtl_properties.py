"""Listing + filtrage des unités d'évaluation foncière de Montréal.

Lecture de la table `mtl_property_units` (peuplée via le rôle
d'évaluation Montréal). Permet à l'utilisateur de filtrer 500k
unités par nb logements / quartier / année / superficie pour
identifier des cibles d'acquisition (ex: tous les 20+ logements).

Pour chaque propriété trouvée, on peut :
- Identifier les corporations REQ avec adresse postale matchant
  la propriété (heuristique « owner-occupant » ou siège déclaré).
- Convertir en ProspectionLead (pipeline de prospection).
"""

from __future__ import annotations

import unicodedata
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select

from app.api.deps import CurrentUser, DBSession
from app.models.montreal_property_unit import MontrealPropertyUnit
from app.models.prospection_lead import (
    ProspectionLead,
    ProspectionLeadKind,
    ProspectionLeadStatus,
    ProspectionOwnerKind,
)
from app.models.req_company import ReqCompany
from app.services.prospection_scoring import apply_score

router = APIRouter(prefix="/prospection/mtl-properties", tags=["mtl-properties"])


# --------------------------- Schemas ---------------------------


class MtlPropertyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    matricule: str
    civique_debut: Optional[str]
    civique_fin: Optional[str]
    nom_rue: Optional[str]
    suite_debut: Optional[str]
    municipalite: Optional[str]
    nombre_logement: Optional[int]
    annee_construction: Optional[int]
    code_utilisation: Optional[str]
    libelle_utilisation: Optional[str]
    categorie_uef: Optional[str]
    superficie_terrain: Optional[float]
    superficie_batiment: Optional[float]
    # Computed
    full_address: Optional[str] = None
    already_lead: bool = False  # True si un ProspectionLead a déjà
                                  # ce matricule
    has_owner_data: bool = False  # True si on a déjà des proprios
                                    # parsés depuis EvalWeb


class OwnerCandidate(BaseModel):
    """Une corporation REQ avec un siège qui matche l'adresse de
    l'immeuble, donc potentiellement la proprio."""

    neq: str
    nom: Optional[str]
    statut: Optional[str]
    forme_juridique: Optional[str]
    adresse: Optional[str]
    ville: Optional[str]
    code_postal: Optional[str]
    telephone: Optional[str]


class ListResponse(BaseModel):
    total: int
    properties: List[MtlPropertyRead]


class ConvertIn(BaseModel):
    matricule: str = Field(..., min_length=1)
    owner_neq: Optional[str] = None  # NEQ du proprio si identifié


# --------------------------- Helpers ---------------------------


def _strip_accents(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


def _full_addr(p: MontrealPropertyUnit) -> str:
    civic = p.civique_debut or ""
    rue = p.nom_rue or ""
    parts = [civic.strip(), rue.strip()]
    return " ".join(x for x in parts if x).strip()


# --------------------------- Endpoints ---------------------------


@router.get("", response_model=ListResponse)
async def list_properties(
    db: DBSession,
    _: CurrentUser,
    min_logements: Optional[int] = Query(default=None, ge=0),
    max_logements: Optional[int] = Query(default=None, ge=0),
    min_annee: Optional[int] = Query(default=None, ge=1700),
    max_annee: Optional[int] = Query(default=None, le=2100),
    min_superficie_terrain: Optional[float] = Query(default=None, ge=0),
    municipalite: Optional[str] = Query(default=None),
    nom_rue_contains: Optional[str] = Query(default=None),
    codes_utilisation: Optional[List[str]] = Query(
        default=None,
        description="Liste de codes d'utilisation à inclure. "
        "Ex: ?codes_utilisation=1000&codes_utilisation=1099 pour "
        "logements unifamiliaux + multi.",
    ),
    sort_by: str = Query(
        default="nombre_logement_desc",
        pattern="^(nombre_logement_desc|nombre_logement_asc|"
        "annee_construction_asc|annee_construction_desc|"
        "superficie_terrain_desc|matricule_asc)$",
    ),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> ListResponse:
    """Filtre + paginate. Ne retourne JAMAIS plus de 1000 lignes
    par requête (sinon le navigateur crash sur 500k objets)."""

    # On bâtit la liste des conditions une seule fois pour les
    # appliquer à la requête principale ET au count.
    filters = []
    if min_logements is not None:
        filters.append(MontrealPropertyUnit.nombre_logement >= min_logements)
    if max_logements is not None:
        filters.append(MontrealPropertyUnit.nombre_logement <= max_logements)
    if min_annee is not None:
        filters.append(
            MontrealPropertyUnit.annee_construction >= min_annee
        )
    if max_annee is not None:
        filters.append(
            MontrealPropertyUnit.annee_construction <= max_annee
        )
    if min_superficie_terrain is not None:
        filters.append(
            MontrealPropertyUnit.superficie_terrain >= min_superficie_terrain
        )
    if municipalite:
        filters.append(
            MontrealPropertyUnit.municipalite == municipalite.strip()
        )
    if nom_rue_contains:
        filters.append(
            MontrealPropertyUnit.nom_rue.ilike(
                f"%{nom_rue_contains.strip()}%"
            )
        )
    if codes_utilisation:
        # Filtre IN (codes) — accepte plusieurs codes pour cocher
        # plusieurs types simultanément.
        cleaned = [c.strip() for c in codes_utilisation if c.strip()]
        if cleaned:
            filters.append(
                MontrealPropertyUnit.code_utilisation.in_(cleaned)
            )

    stmt = select(MontrealPropertyUnit)
    for f in filters:
        stmt = stmt.where(f)

    # Tri
    order_map = {
        "nombre_logement_desc": MontrealPropertyUnit.nombre_logement.desc(),
        "nombre_logement_asc": MontrealPropertyUnit.nombre_logement.asc(),
        "annee_construction_asc": MontrealPropertyUnit.annee_construction.asc(),
        "annee_construction_desc": MontrealPropertyUnit.annee_construction.desc(),
        "superficie_terrain_desc": MontrealPropertyUnit.superficie_terrain.desc(),
        "matricule_asc": MontrealPropertyUnit.matricule.asc(),
    }
    stmt = stmt.order_by(order_map[sort_by]).offset(offset).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()

    # Total count avec les mêmes filtres (séparé, pour paginer)
    count_stmt = select(func.count()).select_from(MontrealPropertyUnit)
    for f in filters:
        count_stmt = count_stmt.where(f)
    total = int((await db.execute(count_stmt)).scalar() or 0)

    # Quels matricules sont déjà dans nos leads ? Une seule query.
    matricules = [r.matricule for r in rows]
    already_set: set[str] = set()
    if matricules:
        existing = (
            await db.execute(
                select(ProspectionLead.matricule).where(
                    ProspectionLead.matricule.in_(matricules),
                    ProspectionLead.archived.is_(False),
                )
            )
        ).all()
        already_set = {m for (m,) in existing if m}

    out: List[MtlPropertyRead] = []
    for r in rows:
        d = MtlPropertyRead.model_validate(r)
        d.full_address = _full_addr(r) or None
        d.already_lead = r.matricule in already_set
        d.has_owner_data = bool(r.owners_json)
        if d.superficie_terrain is not None:
            d.superficie_terrain = float(d.superficie_terrain)
        if d.superficie_batiment is not None:
            d.superficie_batiment = float(d.superficie_batiment)
        out.append(d)
    return ListResponse(total=total, properties=out)


class UtilisationType(BaseModel):
    code: str
    libelle: Optional[str]
    count: int


@router.get(
    "/utilisation-types",
    response_model=List[UtilisationType],
    summary="Liste les codes d'utilisation distincts présents dans la "
    "table avec le nombre d'immeubles pour chacun. Sert à peupler le "
    "filtre cochable côté frontend.",
)
async def utilisation_types(
    db: DBSession,
    _: CurrentUser,
    min_logements: Optional[int] = Query(default=None, ge=0),
) -> List[UtilisationType]:
    """Le `min_logements` optionnel permet de ne retourner que les
    types présents dans le périmètre courant (ex: si on filtre déjà
    20+ logements, on ne montre que les types pertinents).

    Trié par count desc — les types les plus courants en premier.
    """
    stmt = (
        select(
            MontrealPropertyUnit.code_utilisation,
            MontrealPropertyUnit.libelle_utilisation,
            func.count().label("count"),
        )
        .where(MontrealPropertyUnit.code_utilisation.is_not(None))
        .group_by(
            MontrealPropertyUnit.code_utilisation,
            MontrealPropertyUnit.libelle_utilisation,
        )
        .order_by(func.count().desc())
    )
    if min_logements is not None:
        stmt = stmt.where(
            MontrealPropertyUnit.nombre_logement >= min_logements
        )
    rows = (await db.execute(stmt)).all()
    return [
        UtilisationType(
            code=str(code),
            libelle=libelle,
            count=int(count or 0),
        )
        for code, libelle, count in rows
    ]


@router.get(
    "/{matricule}/owner-candidates",
    response_model=List[OwnerCandidate],
)
async def owner_candidates(
    matricule: str,
    db: DBSession,
    _: CurrentUser,
) -> List[OwnerCandidate]:
    """Cherche dans `req_companies` des corporations dont l'adresse
    de domicile / siège matche l'adresse de la propriété.

    Heuristique : on prend l'adresse civique « 4520 Saint-Laurent »
    et on cherche les corps avec adresse contenant ces tokens.
    """
    p = (
        await db.execute(
            select(MontrealPropertyUnit).where(
                MontrealPropertyUnit.matricule == matricule
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "Propriété introuvable")

    addr = _full_addr(p)
    if not addr:
        return []

    # Match LIKE %civic% AND %rue% pour réduire le bruit
    civic = (p.civique_debut or "").strip()
    rue = (p.nom_rue or "").strip()
    rue_norm = _strip_accents(rue).lower()

    # On cherche d'abord par adresse exacte avec civique + rue
    rows = (
        await db.execute(
            select(ReqCompany)
            .where(
                and_(
                    ReqCompany.adresse.ilike(f"%{civic}%"),
                    ReqCompany.adresse.ilike(f"%{rue_norm[:20]}%"),
                )
            )
            .limit(20)
        )
    ).scalars().all()

    return [OwnerCandidate.model_validate(r) for r in rows]


class EvalWebOwnerOut(BaseModel):
    name: str
    statut: Optional[str] = None
    postal_address: Optional[str] = None
    inscription_date: Optional[str] = None
    conditions: Optional[str] = None


class EvalWebResponse(BaseModel):
    matricule: str
    owners: List[EvalWebOwnerOut]
    fetched_at: Optional[str] = None
    cached: bool = False


class EvalWebManualPaste(BaseModel):
    text: str = Field(min_length=10, max_length=20000)


@router.get(
    "/{matricule}/owner-evalweb",
    response_model=EvalWebResponse,
    summary="Récupère les propriétaires depuis EvalWeb (rôle MTL). "
    "Cache le résultat sur la propriété.",
)
async def owner_evalweb(
    matricule: str,
    db: DBSession,
    _: CurrentUser,
    refresh: bool = False,
    cache_only: bool = False,
) -> EvalWebResponse:
    """Scrape la page EvalWeb pour cette propriété — donne les
    propriétaires (personnes physiques + corps) tels qu'inscrits au
    rôle. ~3-5 secondes par appel.

    Mis en cache dans `mtl_property_units.owners_json`. Pour
    rafraîchir, passer `?refresh=true`.
    """
    import json
    from datetime import datetime, timezone

    from app.integrations.roles_evaluation.montreal_owner import (
        EvalWebError,
        scrape_owners,
    )

    p = (
        await db.execute(
            select(MontrealPropertyUnit).where(
                MontrealPropertyUnit.matricule == matricule
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "Propriété introuvable")

    # Cache hit : retourne directement sauf si refresh demandé.
    if not refresh and p.owners_json:
        try:
            cached_owners = json.loads(p.owners_json)
            return EvalWebResponse(
                matricule=matricule,
                owners=[EvalWebOwnerOut(**o) for o in cached_owners],
                fetched_at=(
                    p.owners_fetched_at.isoformat()
                    if p.owners_fetched_at
                    else None
                ),
                cached=True,
            )
        except Exception:
            # Cache corrompu → on re-scrape.
            pass

    # cache_only : si pas de cache, on retourne une réponse vide
    # plutôt que de déclencher un scrape coûteux. Utilisé par la
    # modal pour pré-charger les données existantes sans déclencher
    # de fetch automatique.
    if cache_only:
        return EvalWebResponse(
            matricule=matricule,
            owners=[],
            fetched_at=None,
            cached=False,
        )

    # Scrape EvalWeb.
    try:
        owners = await scrape_owners(matricule)
    except EvalWebError as exc:
        raise HTTPException(502, str(exc)) from exc

    # Cache.
    p.owners_json = json.dumps(owners, ensure_ascii=False)
    p.owners_fetched_at = datetime.now(timezone.utc)
    await _propagate_owners_to_lead(db, matricule, owners)
    await db.flush()

    return EvalWebResponse(
        matricule=matricule,
        owners=[EvalWebOwnerOut(**o) for o in owners],
        fetched_at=p.owners_fetched_at.isoformat(),
        cached=False,
    )


async def _propagate_owners_to_lead(
    db, matricule: str, owners: list[dict]
) -> None:
    """Si un lead actif existe déjà pour ce matricule, met à jour ses
    champs owner_* depuis les données EvalWeb. Idempotent — on
    n'écrase que si le lead n'a pas déjà des infos plus précises
    (NEQ corporation, par ex.)."""
    if not owners:
        return
    lead = (
        await db.execute(
            select(ProspectionLead).where(
                ProspectionLead.matricule == matricule,
                ProspectionLead.archived.is_(False),
            )
        )
    ).scalar_one_or_none()
    if lead is None:
        return

    # On n'écrase pas si le lead a déjà un NEQ (corp identifiée via REQ).
    if lead.owner_neq:
        return

    names = [o.get("name", "").strip() for o in owners if o.get("name")]
    if names:
        lead.owner_name = (" / ".join(names))[:255]
    first_addr = owners[0].get("postal_address")
    if first_addr and not lead.owner_address:
        lead.owner_address = first_addr[:500]
    statuts = [(o.get("statut") or "").lower() for o in owners]
    if any("morale" in s for s in statuts):
        lead.owner_kind = ProspectionOwnerKind.CORPORATION.value
    elif any("physique" in s for s in statuts):
        lead.owner_kind = ProspectionOwnerKind.PARTICULIER.value


@router.post(
    "/{matricule}/owner-evalweb-manual",
    response_model=EvalWebResponse,
    summary="Parse + cache la section Propriétaire collée manuellement "
    "depuis EvalWeb. Fallback quand le scraping auto ne marche pas.",
)
async def owner_evalweb_manual(
    matricule: str,
    body: EvalWebManualPaste,
    db: DBSession,
    _: CurrentUser,
) -> EvalWebResponse:
    """L'utilisateur ouvre la page EvalWeb dans son navigateur, copie
    la section « Propriétaire » (texte plat) et la colle dans la
    modal. On parse + on cache comme l'endpoint auto.

    Indépendant de la structure HTML d'EvalWeb — résiste aux
    changements du site de la Ville.
    """
    import json
    from datetime import datetime, timezone

    from app.integrations.roles_evaluation.montreal_owner import (
        parse_owners_from_text,
    )

    p = (
        await db.execute(
            select(MontrealPropertyUnit).where(
                MontrealPropertyUnit.matricule == matricule
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "Propriété introuvable")

    owners = parse_owners_from_text(body.text)
    if not owners:
        raise HTTPException(
            400,
            "Aucun propriétaire détecté dans le texte. Vérifie que tu "
            "as collé la section commençant par « Nom ».",
        )

    p.owners_json = json.dumps(owners, ensure_ascii=False)
    p.owners_fetched_at = datetime.now(timezone.utc)
    await _propagate_owners_to_lead(db, matricule, owners)
    await db.flush()

    return EvalWebResponse(
        matricule=matricule,
        owners=[EvalWebOwnerOut(**o) for o in owners],
        fetched_at=p.owners_fetched_at.isoformat(),
        cached=False,
    )


@router.post(
    "/{matricule}/convert-to-lead",
    summary="Crée un ProspectionLead à partir d'une propriété MTL.",
    status_code=status.HTTP_201_CREATED,
)
async def convert_to_lead(
    matricule: str,
    db: DBSession,
    user: CurrentUser,
    owner_neq: Optional[str] = None,
) -> dict:
    """Crée un nouveau lead de prospection à partir des données du
    rôle d'évaluation. Si `owner_neq` fourni, on enrichit aussi avec
    le proprio via la table req_companies."""

    p = (
        await db.execute(
            select(MontrealPropertyUnit).where(
                MontrealPropertyUnit.matricule == matricule
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "Propriété introuvable")

    # Empêche les doublons sur le même matricule
    existing = (
        await db.execute(
            select(ProspectionLead.id).where(
                ProspectionLead.matricule == matricule,
                ProspectionLead.archived.is_(False),
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            409,
            f"Cette propriété est déjà un lead (#{existing}).",
        )

    address = _full_addr(p) or None
    name = address or f"Matricule {matricule}"

    # Priorité owner :
    # 1. NEQ REQ fourni → corporation enrichie depuis req_companies
    # 2. Sinon, si owners_json EvalWeb existe → personne physique
    #    (concatène les noms multiples si plusieurs propriétaires)
    # 3. Sinon, INCONNU
    owner_kind = ProspectionOwnerKind.INCONNU.value
    owner_name = None
    owner_phone = None
    owner_address = None
    if owner_neq:
        corp = (
            await db.execute(
                select(ReqCompany).where(ReqCompany.neq == owner_neq)
            )
        ).scalar_one_or_none()
        if corp:
            owner_kind = ProspectionOwnerKind.CORPORATION.value
            owner_name = corp.nom
            owner_phone = corp.telephone
            owner_address = corp.adresse
    elif p.owners_json:
        try:
            import json as _json

            cached = _json.loads(p.owners_json) or []
            if cached:
                # Si plusieurs proprios, on concatène les noms
                # ("Geremia, Roberto / Biggs, Doug").
                names = [
                    o.get("name", "").strip()
                    for o in cached
                    if o.get("name")
                ]
                owner_name = " / ".join(names) if names else None
                # On prend l'adresse postale du premier propriétaire.
                owner_address = cached[0].get("postal_address")
                # Statut : si tous sont « Personne physique » → particulier,
                # si l'un est « Personne morale » → corporation.
                statuts = [
                    (o.get("statut") or "").lower() for o in cached
                ]
                if any("morale" in s for s in statuts):
                    owner_kind = ProspectionOwnerKind.CORPORATION.value
                elif any("physique" in s for s in statuts):
                    owner_kind = ProspectionOwnerKind.PARTICULIER.value
        except Exception:
            pass

    lead = ProspectionLead(
        created_by_user_id=user.id,
        name=name[:255],
        kind=ProspectionLeadKind.MULTILOGEMENT.value,
        address=address,
        city=p.municipalite,
        matricule=p.matricule,
        nb_logements=p.nombre_logement,
        annee_construction=p.annee_construction,
        superficie_terrain=(
            float(p.superficie_terrain)
            if p.superficie_terrain is not None
            else None
        ),
        owner_kind=owner_kind,
        owner_name=owner_name,
        owner_phone=owner_phone,
        owner_address=owner_address,
        owner_neq=owner_neq,
        status=ProspectionLeadStatus.A_CONTACTER.value,
    )
    apply_score(lead)
    db.add(lead)
    await db.flush()
    await db.refresh(lead)

    return {
        "lead_id": lead.id,
        "matricule": matricule,
        "name": lead.name,
    }
