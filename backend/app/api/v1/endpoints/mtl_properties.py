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

import json
import logging
import unicodedata
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, status

log = logging.getLogger(__name__)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select

from app.api.deps import CurrentAdmin, CurrentUser, DBSession
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


class AddressSuggestion(BaseModel):
    """Suggestion compacte pour autocomplete d'adresse."""

    matricule: str
    civique: Optional[str]
    nom_rue: Optional[str]
    municipalite: Optional[str]
    label: str  # ex. "261 mont-royal — Montréal"


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
    owner_names: Optional[List[str]] = None  # Liste des noms (compact
                                              # pour affichage liste)
    owner_inscription_dates: Optional[List[str]] = None  # Dates parallèles
                                                          # (idx aligné avec
                                                          # owner_names)


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
    region: Optional[str] = Query(
        default=None,
        pattern="^(mtl-island|laval|rive-sud|rive-nord)$",
        description="Filtre par région. mtl-island = île de Montréal "
        "(MTL + arrondissements), laval, rive-sud, rive-nord.",
    ),
    distance_band: Optional[str] = Query(
        default=None,
        pattern="^(mtl_only|under_30|30_to_40|40_to_50|over_50)$",
        description="Filtre par distance depuis le centre-ville MTL : "
        "mtl_only (île de Montréal seulement), under_30 (< 30 km), "
        "30_to_40, 40_to_50, over_50 (> 50 km).",
    ),
    nom_rue_contains: Optional[str] = Query(default=None),
    arrondissement: Optional[str] = Query(
        default=None,
        description="Filtre par arrondissement de la Ville de Montréal "
        "(ex: « Le Plateau-Mont-Royal », « Ville-Marie »). Ne s'applique "
        "qu'aux unités avec municipalite='Montréal'.",
    ),
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
    if region:
        # Le filtre par région DOIT s'appuyer sur le nom de municipalité,
        # pas sur le label `region` stocké en row. Pourquoi : l'import
        # provincial XML (1 134 fichiers) écrit `region="quebec"` pour
        # tout (993 K rows), l'import legacy Ville de Montréal écrit NULL
        # ou "mtl-island". Si on filtre sur `region == "mtl-island"`, on
        # rate les ~700 K unités MTL importées via le ZIP provincial dont
        # le label est "quebec".
        from sqlalchemy import func as sa_func

        # Liste des municipalités par région (raw names, avec accents).
        # MTL : île + arrondissements/villes liées.
        MTL_RAW = [
            "Montréal", "Montréal-Est", "Westmount", "Côte-Saint-Luc",
            "Hampstead", "Montréal-Ouest", "Mont-Royal", "Outremont",
            "Dorval", "Pointe-Claire", "Kirkland", "Beaconsfield",
            "Baie-D'Urfé", "Sainte-Anne-de-Bellevue", "Senneville",
            "L'Île-Bizard", "L'Île-Bizard-Sainte-Geneviève",
        ]
        from app.integrations.roles_evaluation.quebec_regional import (
            LAVAL_CITIES,
            RIVE_NORD_CITIES,
            RIVE_SUD_CITIES,
        )

        def _variants(names) -> list[str]:
            """Génère lowercase avec ET sans accents pour matcher la DB."""
            out: set[str] = set()
            for n in names:
                low = n.strip().lower()
                out.add(low)
                nfd = unicodedata.normalize("NFD", low)
                stripped = "".join(
                    ch for ch in nfd if not unicodedata.combining(ch)
                )
                out.add(stripped)
            return sorted(out)

        region_to_names = {
            "mtl-island": MTL_RAW,
            "laval": list(LAVAL_CITIES),
            "rive-sud": list(RIVE_SUD_CITIES),
            "rive-nord": list(RIVE_NORD_CITIES),
        }
        names = region_to_names.get(region)
        if names:
            # Match : lower(municipalite) IN (variantes avec/sans accents).
            filters.append(
                sa_func.lower(MontrealPropertyUnit.municipalite).in_(
                    _variants(names)
                )
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

    if arrondissement:
        # Filtre par arrondissement (Ville de MTL uniquement).
        filters.append(
            MontrealPropertyUnit.arrondissement == arrondissement.strip()
        )

    # Filtre par distance depuis le centre-ville MTL via la table
    # quebec_distances. Matching insensible à la casse sur le nom de
    # municipalité tel que stocké (avec accents préservés du CSV).
    # Pour les bandes proches (mtl_only, under_30), on inclut aussi
    # les unités taggées region='mtl-island' (rétro-compat avec les
    # imports faits avant la refonte distance).
    if distance_band:
        from app.integrations.roles_evaluation.quebec_distances import (
            _DIST_KM_RAW,
        )

        if distance_band == "mtl_only":
            mn, mx = 0.0, 0.0
        elif distance_band == "under_30":
            mn, mx = 0.0, 30.0
        elif distance_band == "30_to_40":
            mn, mx = 30.0, 40.0
        elif distance_band == "40_to_50":
            mn, mx = 40.0, 50.0
        else:  # over_50
            mn, mx = None, None

        if distance_band == "over_50":
            close_lower = {
                k.lower()
                for k, dist in _DIST_KM_RAW.items()
                if dist <= 50
            }
            if close_lower:
                filters.append(
                    func.lower(MontrealPropertyUnit.municipalite).notin_(
                        list(close_lower)
                    )
                )
        elif distance_band == "mtl_only":
            # Île de Montréal stricte : whitelist explicite des 15
            # municipalités sur l'île (Montréal + 14 villes liées).
            # NB : un seuil de distance ≤ N km capture aussi Laval,
            # Longueuil, Brossard, Boucherville, Charlemagne… qui sont
            # toutes hors-île — d'où la whitelist.
            from app.integrations.roles_evaluation.quebec_distances import (
                MTL_ISLAND_CITIES,
            )
            # Défensif : inclut aussi tout row dont `arrondissement`
            # est non-null. Couvre le cas où l'import provincial a
            # écrit le nom de l'arrondissement dans `municipalite`
            # (ex. « Le Plateau-Mont-Royal » plutôt que « Montréal »)
            # — autrement Montréal proper « disparaît » de la liste.
            filters.append(
                or_(
                    MontrealPropertyUnit.region == "mtl-island",
                    func.lower(MontrealPropertyUnit.municipalite).in_(
                        list(MTL_ISLAND_CITIES)
                    ),
                    MontrealPropertyUnit.arrondissement.is_not(None),
                )
            )
        else:
            originals_lower = [
                k.lower()
                for k, dist in _DIST_KM_RAW.items()
                if mn is not None and mx is not None and mn <= dist <= mx
            ]
            band_filters = []
            if originals_lower:
                band_filters.append(
                    func.lower(MontrealPropertyUnit.municipalite).in_(
                        originals_lower
                    )
                )
            # Pour la tranche under_30, on inclut aussi les unités
            # taggées 'mtl-island' (cas legacy : MTL importé avant
            # qu'on ne propage la région ou avec un nom de
            # municipalité = arrondissement non encore ajouté au dict).
            # Et : tout row avec `arrondissement` non null = MTL proper.
            if distance_band == "under_30":
                band_filters.append(
                    MontrealPropertyUnit.region == "mtl-island"
                )
                band_filters.append(
                    MontrealPropertyUnit.arrondissement.is_not(None)
                )
            if band_filters:
                filters.append(or_(*band_filters))
            else:
                filters.append(MontrealPropertyUnit.matricule.is_(None))

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
        # Extrait les noms + dates d'inscription des owners depuis
        # owners_json (best-effort). Listes parallèles : idx N du nom
        # correspond à idx N de la date.
        if r.owners_json:
            try:
                owners_data = json.loads(r.owners_json)
                pairs = [
                    (
                        (o.get("name") or "").strip(),
                        (o.get("inscription_date") or "").strip() or None,
                    )
                    for o in owners_data
                    if o.get("name")
                ]
                if pairs:
                    d.owner_names = [n for n, _ in pairs]
                    d.owner_inscription_dates = [dt for _, dt in pairs]
                else:
                    d.owner_names = None
                    d.owner_inscription_dates = None
            except Exception:
                d.owner_names = None
                d.owner_inscription_dates = None
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
    "/address-search",
    response_model=List[AddressSuggestion],
    summary="Autocomplete d'adresse depuis le rôle d'évaluation Montréal.",
)
async def address_search(
    db: DBSession,
    _: CurrentUser,
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(default=15, ge=1, le=50),
) -> List[AddressSuggestion]:
    """Recherche d'adresses par sous-chaîne. Match sur civique + nom_rue
    concaténés (ex. « 261 mont »). Utilisé par le combobox de la fiche
    lead pour proposer des adresses existantes au lieu de saisie libre."""
    cleaned = q.strip()
    if not cleaned:
        return []

    # On cherche les tokens séparément : un nombre = civique, le reste = rue
    tokens = [t for t in cleaned.split() if t]
    civic_token = next((t for t in tokens if t[:1].isdigit()), None)
    street_tokens = [t for t in tokens if t != civic_token]

    filters = []
    if civic_token:
        filters.append(MontrealPropertyUnit.civique_debut.ilike(f"{civic_token}%"))
    if street_tokens:
        for st in street_tokens:
            filters.append(MontrealPropertyUnit.nom_rue.ilike(f"%{st}%"))
    if not filters:
        return []

    stmt = (
        select(MontrealPropertyUnit)
        .where(*filters)
        .order_by(
            MontrealPropertyUnit.nom_rue.asc(),
            MontrealPropertyUnit.civique_debut.asc(),
        )
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    out: List[AddressSuggestion] = []
    for r in rows:
        civic = (r.civique_debut or "").strip()
        rue = (r.nom_rue or "").strip()
        ville = (r.municipalite or "Montréal").strip()
        full = " ".join(x for x in [civic, rue] if x)
        label = f"{full} — {ville}" if full else ville
        out.append(
            AddressSuggestion(
                matricule=r.matricule,
                civique=civic or None,
                nom_rue=rue or None,
                municipalite=ville,
                label=label,
            )
        )
    return out


# Cache TTL en mémoire pour /utilisation-types — l'endpoint GROUP BY
# sur ~1 M lignes coûte 1-3 s. La liste change rarement (seulement
# après un import de rôle), donc on cache 5 min par valeur de
# min_logements (None inclus).
_UTILISATION_CACHE: Dict[Tuple[Optional[int]], Tuple[float, List["UtilisationType"]]] = {}
_UTILISATION_CACHE_TTL_S = 300.0


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
    Cache 5 min en mémoire — la liste change rarement.
    """
    import time as _time

    cache_key: Tuple[Optional[int]] = (min_logements,)
    cached = _UTILISATION_CACHE.get(cache_key)
    now = _time.monotonic()
    if cached is not None and (now - cached[0]) < _UTILISATION_CACHE_TTL_S:
        return cached[1]

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
    result = [
        UtilisationType(
            code=str(code),
            libelle=libelle,
            count=int(count or 0),
        )
        for code, libelle, count in rows
    ]
    _UTILISATION_CACHE[cache_key] = (now, result)
    return result


@router.get(
    "/arrondissements",
    summary="Liste les arrondissements de Montréal présents en DB.",
)
async def arrondissements_list(
    db: DBSession,
    _: CurrentUser,
) -> List[dict]:
    """Retourne les arrondissements distincts (Ville de MTL) avec
    le compte d'unités. Utilisé par le frontend pour peupler le
    filtre dropdown. Trié par nom alphabétique."""
    rows = (
        await db.execute(
            select(
                MontrealPropertyUnit.arrondissement,
                func.count().label("cnt"),
            )
            .where(MontrealPropertyUnit.arrondissement.is_not(None))
            .group_by(MontrealPropertyUnit.arrondissement)
            .order_by(MontrealPropertyUnit.arrondissement.asc())
        )
    ).all()
    return [{"name": str(name), "count": int(cnt or 0)} for name, cnt in rows]


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
    # Champs ajoutés par l'enrichissement auto
    phone: Optional[str] = None
    phone_source: Optional[str] = None  # "req" | "canada411"
    req_neq: Optional[str] = None
    req_status: Optional[str] = None
    req_forme_juridique: Optional[str] = None
    req_address: Optional[str] = None
    req_ville: Optional[str] = None
    req_code_postal: Optional[str] = None
    c411_address: Optional[str] = None


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

    # Si pas dans owners_json, vérifie le cache mémoire de l'extension
    # navigateur. L'extension peut avoir POST récemment des owners
    # qui n'ont pas pu être persistés (ex. si la propagation aux
    # leads a eu un soucis). On lit le cache direct, et on persiste
    # à la volée pour les prochaines requêtes.
    if not refresh:
        try:
            from app.api.v1.endpoints.extension import _cache_get, _owners_cache
            ext_data = _cache_get(_owners_cache, matricule)
        except Exception:
            ext_data = None
        if ext_data and ext_data.get("owners"):
            ext_owners = ext_data["owners"]
            # Persiste à la volée pour les prochaines lectures
            try:
                p.owners_json = json.dumps(ext_owners, ensure_ascii=False)
                p.owners_fetched_at = datetime.now(timezone.utc)
                await db.flush()
            except Exception:
                pass
            return EvalWebResponse(
                matricule=matricule,
                owners=[EvalWebOwnerOut(**o) for o in ext_owners],
                fetched_at=(
                    p.owners_fetched_at.isoformat()
                    if p.owners_fetched_at
                    else None
                ),
                cached=True,
            )

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

    # 1) Si le VPS de scraping (Playwright) est configuré, on
    # l'utilise — beaucoup plus fiable que le scrape httpx direct.
    # 2) Fallback : scrape direct via httpx (best-effort).
    from app.integrations import scraping_proxy

    owners: Optional[list] = None
    if scraping_proxy.vps_available():
        try:
            owners = await scraping_proxy.scrape_evalweb_owners(matricule)
        except Exception as exc:
            log.warning(
                "VPS scraping failed for %s: %s — fallback httpx",
                matricule,
                exc,
            )
            owners = None

    if not owners:
        try:
            owners = await scrape_owners(matricule)
        except EvalWebError as exc:
            raise HTTPException(502, str(exc)) from exc

    if not owners:
        raise HTTPException(
            502,
            "Aucun propriétaire trouvé. Utilise « Saisir manuellement » "
            "pour copier la section depuis EvalWeb.",
        )

    # Cache.
    # Enrichissement auto : REQ pour les corps + Canada411 pour le tel.
    from app.services.owner_enrichment import enrich_owners as _enrich

    enriched = await _enrich(db, owners)

    p.owners_json = json.dumps(enriched, ensure_ascii=False)
    p.owners_fetched_at = datetime.now(timezone.utc)
    await _propagate_owners_to_lead(db, matricule, enriched)
    await db.flush()

    return EvalWebResponse(
        matricule=matricule,
        owners=[EvalWebOwnerOut(**o) for o in enriched],
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

    # Téléphone enrichi (REQ ou Canada411) → on le pousse au lead
    # SAUF si le lead a déjà un téléphone (saisi manuellement).
    for o in owners:
        if o.get("phone") and not lead.owner_phone:
            lead.owner_phone = str(o["phone"])[:50]
            break

    # NEQ enrichi → on le pousse au lead si on l'a trouvé via REQ
    for o in owners:
        if o.get("req_neq") and not lead.owner_neq:
            lead.owner_neq = str(o["req_neq"])[:32]
            break


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

    # Enrichissement auto : REQ + Canada411 pour chaque owner.
    from app.services.owner_enrichment import enrich_owners as _enrich

    enriched = await _enrich(db, owners)

    p.owners_json = json.dumps(enriched, ensure_ascii=False)
    p.owners_fetched_at = datetime.now(timezone.utc)
    await _propagate_owners_to_lead(db, matricule, enriched)
    await db.flush()

    return EvalWebResponse(
        matricule=matricule,
        owners=[EvalWebOwnerOut(**o) for o in enriched],
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


# --------------------------- Backfill admin ---------------------------


class BackfillResponse(BaseModel):
    total_leads: int
    already_filled: int
    matched: int
    ambiguous: int
    no_match: int
    sample_unmatched: List[str] = []


def _parse_address_for_search(addr: str) -> tuple[Optional[str], List[str]]:
    """Extrait le 1er token numérique (civique) + tokens texte (rue)."""
    tokens = [t for t in (addr or "").split() if t]
    civic = next((t for t in tokens if t[:1].isdigit()), None)
    street = [t for t in tokens if t != civic and len(t) >= 2]
    return civic, street


@router.post(
    "/backfill-leads",
    response_model=BackfillResponse,
    summary="Backfill matricule + ville + adresse normalisée pour les "
    "leads existants depuis le rôle d'évaluation Montréal.",
)
async def backfill_leads_from_mtl(
    db: DBSession,
    _: CurrentAdmin,
    limit: int = Query(default=2000, ge=1, le=10000),
) -> BackfillResponse:
    """Pour chaque ProspectionLead avec une adresse texte, tente de
    matcher dans MontrealPropertyUnit et remplit matricule, city,
    superficie, nb_logements, annee si manquants. N'écrase pas les
    valeurs déjà set par l'utilisateur."""
    leads = (
        await db.execute(
            select(ProspectionLead)
            .where(ProspectionLead.archived.is_(False))
            .limit(limit)
        )
    ).scalars().all()

    total = len(leads)
    already = 0
    matched = 0
    ambiguous = 0
    no_match = 0
    unmatched_sample: List[str] = []

    for lead in leads:
        # Si déjà bien rempli (matricule + city), on saute
        if lead.matricule and lead.city:
            already += 1
            continue
        if not lead.address or not lead.address.strip():
            no_match += 1
            continue

        civic, street_toks = _parse_address_for_search(lead.address)
        filters = []
        if civic:
            filters.append(MontrealPropertyUnit.civique_debut.ilike(f"{civic}%"))
        if street_toks:
            for st in street_toks:
                filters.append(MontrealPropertyUnit.nom_rue.ilike(f"%{st}%"))
        if not filters:
            no_match += 1
            if len(unmatched_sample) < 20:
                unmatched_sample.append(lead.address[:80])
            continue

        # Cherche jusqu'à 5 matches pour détecter ambiguïté
        rows = (
            await db.execute(
                select(MontrealPropertyUnit).where(*filters).limit(5)
            )
        ).scalars().all()

        if len(rows) == 0:
            no_match += 1
            if len(unmatched_sample) < 20:
                unmatched_sample.append(lead.address[:80])
            continue
        if len(rows) > 1:
            ambiguous += 1
            continue

        p = rows[0]
        # Met à jour seulement les champs manquants
        if not lead.matricule:
            lead.matricule = p.matricule
        if not lead.city and p.municipalite:
            lead.city = p.municipalite
        if lead.nb_logements is None and p.nombre_logement is not None:
            lead.nb_logements = p.nombre_logement
        if lead.annee_construction is None and p.annee_construction is not None:
            lead.annee_construction = p.annee_construction
        if lead.superficie_terrain is None and p.superficie_terrain is not None:
            lead.superficie_terrain = float(p.superficie_terrain)
        # Normalise l'adresse au format MTL (civique + nom_rue)
        normalized = " ".join(
            x for x in [(p.civique_debut or "").strip(), (p.nom_rue or "").strip()] if x
        )
        if normalized:
            lead.address = normalized
        matched += 1

    await db.flush()
    return BackfillResponse(
        total_leads=total,
        already_filled=already,
        matched=matched,
        ambiguous=ambiguous,
        no_match=no_match,
        sample_unmatched=unmatched_sample,
    )


# ── Diagnostic : que contient la DB ? ────────────────────────────


class DiagBucket(BaseModel):
    municipalite: Optional[str]
    region: Optional[str]
    count: int


class DiagArrondBucket(BaseModel):
    arrondissement: Optional[str]
    count: int


class MtlDiagnostics(BaseModel):
    """Que contient actuellement la table `mtl_property_units` ?

    Utile quand l'utilisateur ne voit plus de données pour une ville
    (ex. Montréal proper). Affiche :
      - total cumul
      - répartition par `region`
      - top 30 municipalités (sorted desc)
      - répartition par arrondissement pour Montréal proper
    """
    total: int
    by_region: List[DiagBucket]
    top_municipalites: List[DiagBucket]
    montreal_arrondissements: List[DiagArrondBucket]


@router.get(
    "/diagnostics",
    response_model=MtlDiagnostics,
    summary="État de la table mtl_property_units (admin).",
)
async def mtl_diagnostics(
    db: DBSession, _: CurrentAdmin
) -> MtlDiagnostics:
    """Retourne un état détaillé de ce qui est en DB. Utiliser
    pour vérifier si Montréal proper / les villes liées sont bien
    importées."""
    total = (
        await db.execute(select(func.count(MontrealPropertyUnit.matricule)))
    ).scalar_one()

    by_region_rows = (
        await db.execute(
            select(
                MontrealPropertyUnit.region,
                func.count(MontrealPropertyUnit.matricule),
            ).group_by(MontrealPropertyUnit.region)
        )
    ).all()

    top_muni_rows = (
        await db.execute(
            select(
                MontrealPropertyUnit.municipalite,
                MontrealPropertyUnit.region,
                func.count(MontrealPropertyUnit.matricule).label("c"),
            )
            .group_by(
                MontrealPropertyUnit.municipalite,
                MontrealPropertyUnit.region,
            )
            .order_by(func.count(MontrealPropertyUnit.matricule).desc())
            .limit(30)
        )
    ).all()

    arrond_rows = (
        await db.execute(
            select(
                MontrealPropertyUnit.arrondissement,
                func.count(MontrealPropertyUnit.matricule),
            )
            .where(
                func.lower(MontrealPropertyUnit.municipalite) == "montréal"
            )
            .group_by(MontrealPropertyUnit.arrondissement)
            .order_by(func.count(MontrealPropertyUnit.matricule).desc())
        )
    ).all()

    return MtlDiagnostics(
        total=int(total or 0),
        by_region=[
            DiagBucket(municipalite=None, region=r, count=int(c))
            for r, c in by_region_rows
        ],
        top_municipalites=[
            DiagBucket(municipalite=m, region=r, count=int(c))
            for m, r, c in top_muni_rows
        ],
        montreal_arrondissements=[
            DiagArrondBucket(arrondissement=a, count=int(c))
            for a, c in arrond_rows
        ],
    )


# --------------------------------------------------------------------------
# Health check : statut combiné BD + lien VPS Hetzner (scraping EvalWeb)
# --------------------------------------------------------------------------


class MtlHealth(BaseModel):
    db_total_units: int
    db_montreal_units: int
    db_has_data: bool
    vps_configured: bool
    vps_url_set: bool
    vps_key_set: bool
    vps_reachable: bool
    summary: str


@router.get(
    "/health",
    response_model=MtlHealth,
    summary="Diagnostic combiné BD + lien VPS Hetzner (scraping)",
)
async def mtl_health(db: DBSession, _: CurrentAdmin) -> MtlHealth:
    """Identifie en 1 appel si le problème vient :
    - de la BD vide (montreal_property_units sans rows), OU
    - du VPS Hetzner non joignable (URL/clé manquantes ou serveur down).
    """
    from app.integrations import scraping_proxy

    total = (
        await db.execute(select(func.count(MontrealPropertyUnit.matricule)))
    ).scalar_one()
    mtl_count = (
        await db.execute(
            select(func.count(MontrealPropertyUnit.matricule)).where(
                func.lower(MontrealPropertyUnit.municipalite) == "montréal"
            )
        )
    ).scalar_one()

    vps_url_set = bool(scraping_proxy.VPS_URL)
    vps_key_set = bool(scraping_proxy.VPS_KEY)
    vps_configured = vps_url_set and vps_key_set
    vps_reachable = False
    if vps_configured:
        try:
            vps_reachable = await scraping_proxy.is_vps_healthy()
        except Exception:  # noqa: BLE001
            vps_reachable = False

    db_has_data = int(total or 0) > 0
    # Résumé humain pour debug rapide
    parts: list[str] = []
    if not db_has_data:
        parts.append("⚠️ BD vide (aucune unité importée)")
    else:
        parts.append(
            f"✓ BD : {int(total)} unités ({int(mtl_count)} à Montréal)"
        )
    if not vps_url_set:
        parts.append("⚠️ SCRAPING_VPS_URL non configurée")
    elif not vps_key_set:
        parts.append("⚠️ SCRAPING_VPS_KEY non configurée")
    elif not vps_reachable:
        parts.append("⚠️ VPS injoignable (URL ok mais /health KO)")
    else:
        parts.append("✓ VPS Hetzner joignable")
    summary = " · ".join(parts)

    return MtlHealth(
        db_total_units=int(total or 0),
        db_montreal_units=int(mtl_count or 0),
        db_has_data=db_has_data,
        vps_configured=vps_configured,
        vps_url_set=vps_url_set,
        vps_key_set=vps_key_set,
        vps_reachable=vps_reachable,
        summary=summary,
    )
