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

import csv
import io
import json
import logging
import re
import unicodedata
from datetime import date as _date
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

log = logging.getLogger(__name__)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Integer, and_, func, or_, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement

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
    #: « HLM · Saint-Sulpice », « Coop · propriétaire »… ; None = pas connu
    #: comme logement social (Phil 2026-09-28).
    logement_social: Optional[str] = None
    #: Années entières écoulées depuis l'inscription au rôle du 1er
    #: propriétaire (« le propriétaire l'a depuis combien de temps ? »).
    proprietaire_depuis_annees: Optional[int] = None


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
    #: Unités retirées par « Exclure les logements sociaux » (None si la
    #: case n'est pas cochée) — Phil 2026-09-29 : « ça change rien au
    #: nombre ».
    sociaux_exclus: Optional[int] = None


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


class _CiviqueInt(FunctionElement):
    """Numéro civique (VARCHAR) → entier, sans jamais faire échouer la
    requête sur une valeur non numérique (« 12A ») : NULL dans ce cas."""

    type = Integer()
    name = "civique_int"
    inherit_cache = True


@compiles(_CiviqueInt)
def _civique_int_defaut(element, compiler, **kw):  # SQLite (tests)
    arg = compiler.process(list(element.clauses)[0], **kw)
    return f"CAST(NULLIF(TRIM({arg}), '') AS INTEGER)"


@compiles(_CiviqueInt, "postgresql")
def _civique_int_pg(element, compiler, **kw):
    arg = compiler.process(list(element.clauses)[0], **kw)
    return (
        f"(CASE WHEN TRIM({arg}) <> '' AND TRIM({arg}) !~ '[^0-9]' "
        f"AND length(TRIM({arg})) <= 9 THEN CAST(TRIM({arg}) AS INTEGER) END)"
    )


_MOIS_FR = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12,
}


def _date_inscription(texte: Optional[str]) -> Optional[_date]:
    """« 2017-03-15 », « 15/03/2017 », « 15 mars 2017 » → date (None si
    illisible)."""
    if not texte:
        return None
    t = (
        unicodedata.normalize("NFD", str(texte))
        .encode("ascii", "ignore")
        .decode()
        .strip()
        .lower()
    )
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", t)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = re.search(r"(\d{1,2})(?:er)?\s+([a-z]+)\s+(\d{4})", t)
            if m and m.group(2) in _MOIS_FR:
                d, mo, y = int(m.group(1)), _MOIS_FR[m.group(2)], int(m.group(3))
            else:
                m = re.search(r"\b((?:19|20)\d{2})\b", t)
                if not m:
                    return None
                y, mo, d = int(m.group(1)), 7, 1
    try:
        return _date(y, mo, d)
    except ValueError:
        return None


def _annees_ecoulees(inscrit: _date) -> int:
    """Années entières écoulées depuis ``inscrit`` (0 si dans le futur)."""
    today = _date.today()
    if inscrit > today:
        return 0
    return today.year - inscrit.year - (
        (today.month, today.day) < (inscrit.month, inscrit.day)
    )


def _annees_depuis(texte: Optional[str]) -> Optional[int]:
    """« 2017-03-15 » → années entières écoulées (None si illisible). Sert
    à « propriétaire depuis N ans » (Phil 2026-09-28)."""
    d = _date_inscription(texte)
    return _annees_ecoulees(d) if d else None


def date_inscription_min(owners) -> Optional[_date]:
    """Plus ancienne date d'inscription parmi les propriétaires collectés
    (dicts EvalWeb ``{"name", "inscription_date"}``) : un copropriétaire
    ajouté plus tard ne rajeunit pas la détention de l'immeuble."""
    dates = []
    for o in owners or []:
        if isinstance(o, dict):
            d = _date_inscription(o.get("inscription_date"))
            if d:
                dates.append(d)
    return min(dates) if dates else None


async def _completer_proprietaire_depuis(db) -> int:
    """Rattrapage : unités dont le propriétaire a été collecté avant la
    colonne ``proprietaire_depuis`` (ou par un chemin qui ne la remplit
    pas). Appelé seulement quand le filtre « propriétaire depuis » sert."""
    from sqlalchemy import bindparam, update

    rows = (
        await db.execute(
            select(MontrealPropertyUnit.matricule, MontrealPropertyUnit.owners_json)
            .where(
                MontrealPropertyUnit.proprietaire_depuis.is_(None),
                MontrealPropertyUnit.owners_json.is_not(None),
                MontrealPropertyUnit.owners_json.notin_(["", "[]"]),
            )
            .limit(20000)
        )
    ).all()
    items = []
    for mat, owners_json in rows:
        try:
            d = date_inscription_min(json.loads(owners_json or "[]"))
        except Exception:  # noqa: BLE001
            d = None
        if d:
            items.append({"m": mat, "d": d})
    if not items:
        return 0
    table = MontrealPropertyUnit.__table__
    stmt = (
        update(table)
        .where(table.c.matricule == bindparam("m"))
        .values(proprietaire_depuis=bindparam("d"))
    )
    for i in range(0, len(items), 500):
        await db.execute(stmt, items[i : i + 500])
    await db.commit()
    return len(items)


#: Codes d'utilisation du rôle « résidences pour aînés » : 1541 personnes
#: retraitées NON autonomes (dont CHSLD), 1543 autonomes (RPA), 1549 autres
#: (Phil 2026-09-29 : « ça ne m'intéresse pas »).
CODES_RESIDENCES_AINES = ("1541", "1543", "1549")


def _filtres_mtl(
    *,
    min_logements: Optional[int] = None,
    max_logements: Optional[int] = None,
    min_annee: Optional[int] = None,
    max_annee: Optional[int] = None,
    min_superficie_terrain: Optional[float] = None,
    municipalite: Optional[str] = None,
    region: Optional[str] = None,
    distance_band: Optional[str] = None,
    nom_rue_contains: Optional[str] = None,
    arrondissement: Optional[str] = None,
    codes_utilisation: Optional[List[str]] = None,
    exclure_sociaux: bool = False,
    numero_civique: Optional[str] = None,
    proprietaire_min_annees: Optional[int] = None,
    exclure_residences_aines: bool = False,
) -> list:
    """Conditions SQL des filtres de la page « Immeubles MTL » — UNE
    seule implémentation pour la liste, le compte et l'export CSV."""
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
    if nom_rue_contains and nom_rue_contains.strip():
        brut = nom_rue_contains.strip()
        # « 2420 Pie-IX » tapé dans le champ rue : le numéro devient le
        # filtre de numéro civique (Phil 2026-09-29).
        m_adr = re.match(r"^(\d+)[a-zA-Z]?\s*[,\s]\s*(\S.*)$", brut)
        if m_adr and not (numero_civique or "").strip():
            numero_civique, brut = m_adr.group(1), m_adr.group(2).strip()
        from app.integrations.roles_evaluation.montreal import normalize_street

        # Tolérant : accents, tirets, type de voie, « St »/« Ste »
        # (« pie ix » trouve « boulevard Pie-IX », « St-Clément » trouve
        # « rue Saint-Clément ») via la clé normalisée `search_key`
        # (« <civique>|<rue normalisée> »).
        cle = normalize_street(brut)
        cle = re.sub(r"\bste\b", "sainte", cle)
        cle = re.sub(r"\bst\b", "saint", cle)
        toks = cle.split()
        conds = [MontrealPropertyUnit.nom_rue.ilike(f"%{brut}%")]
        if toks:
            conds.append(
                MontrealPropertyUnit.search_key.like(f"%|%{'%'.join(toks)}%")
            )
        filters.append(or_(*conds))
    if proprietaire_min_annees:
        # « Propriétaire depuis au moins N ans » (Phil 2026-09-29) : ne
        # garde que les propriétaires COLLECTÉS (la date d'inscription
        # n'existe que sur la fiche montreal.ca).
        t = _date.today()
        try:
            borne = t.replace(year=t.year - proprietaire_min_annees)
        except ValueError:  # 29 février
            borne = t.replace(year=t.year - proprietaire_min_annees, day=28)
        filters.append(MontrealPropertyUnit.proprietaire_depuis <= borne)
    m_num = re.search(r"\d+", numero_civique or "")
    if m_num:
        # Numéro de porte (Phil 2026-09-29 : « disons 1660 ») : le début
        # du civique, ou une plage « 1660-1672 » qui le contient.
        num = int(m_num.group(0)[:9])
        debut = _CiviqueInt(MontrealPropertyUnit.civique_debut)
        fin = _CiviqueInt(MontrealPropertyUnit.civique_fin)
        filters.append(
            or_(
                debut == num,
                and_(debut <= num, fin >= num, fin - debut <= 400),
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

    if exclure_residences_aines:
        filters.append(
            or_(
                MontrealPropertyUnit.code_utilisation.is_(None),
                MontrealPropertyUnit.code_utilisation.notin_(
                    list(CODES_RESIDENCES_AINES)
                ),
            )
        )

    if exclure_sociaux:
        # HLM, coops, OBNL, SHDM… marqués par services/logements_sociaux
        # (Phil 2026-09-28 : « un filtre pour exclure les logements
        # sociaux »).
        filters.append(MontrealPropertyUnit.logement_social.is_(None))

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
            from app.integrations.roles_evaluation.montreal import (
                MUNICIPALITE_CODES,
            )

            # MTL_ISLAND_CITIES est normalisée SANS accents (« montreal ») :
            # une ligne « Montréal » (avec accent, comme l'écrit l'import
            # de la Ville) ne matchait pas → on ajoute les noms accentués
            # en minuscules (Phil 2026-09-28).
            noms_ile = set(MTL_ISLAND_CITIES) | {
                n.lower() for n in MUNICIPALITE_CODES.values()
            }
            filters.append(
                or_(
                    MontrealPropertyUnit.region == "mtl-island",
                    func.lower(MontrealPropertyUnit.municipalite).in_(
                        sorted(noms_ile)
                    ),
                    # Codes bruts d'un import antérieur à la conversion
                    # en noms (« 50 » = Montréal) — Phil 2026-09-28.
                    MontrealPropertyUnit.municipalite.in_(
                        list(MUNICIPALITE_CODES.keys())
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

    return filters


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
    exclure_sociaux: bool = Query(
        default=False,
        description="Exclut les unités marquées logement social "
        "(HLM, coops, OBNL, SHDM, Office d'habitation).",
    ),
    numero_civique: Optional[str] = Query(
        default=None,
        description="Numéro de porte (ex. 1660) — trouve aussi les plages "
        "« 1660-1672 ».",
    ),
    proprietaire_min_annees: Optional[int] = Query(
        default=None,
        ge=0,
        le=150,
        description="Propriétaire depuis au moins N ans (propriétaires "
        "collectés seulement).",
    ),
    exclure_residences_aines: bool = Query(
        default=False,
        description="Exclut les résidences pour aînés (codes d'utilisation "
        "1541, 1543, 1549 : RPA, CHSLD).",
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

    if proprietaire_min_annees:
        await _completer_proprietaire_depuis(db)
    filtres_kwargs = dict(
        min_logements=min_logements,
        max_logements=max_logements,
        min_annee=min_annee,
        max_annee=max_annee,
        min_superficie_terrain=min_superficie_terrain,
        municipalite=municipalite,
        region=region,
        distance_band=distance_band,
        nom_rue_contains=nom_rue_contains,
        arrondissement=arrondissement,
        codes_utilisation=codes_utilisation,
        exclure_sociaux=exclure_sociaux,
        numero_civique=numero_civique,
        proprietaire_min_annees=proprietaire_min_annees,
        exclure_residences_aines=exclure_residences_aines,
    )
    filters = _filtres_mtl(**filtres_kwargs)

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
                    depuis_d = r.proprietaire_depuis or date_inscription_min(
                        owners_data
                    )
                    d.proprietaire_depuis_annees = (
                        _annees_ecoulees(depuis_d) if depuis_d else None
                    )
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
    sociaux_exclus: Optional[int] = None
    if exclure_sociaux:
        base = _filtres_mtl(**{**filtres_kwargs, "exclure_sociaux": False})
        sociaux_exclus = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(MontrealPropertyUnit)
                    .where(*base, MontrealPropertyUnit.logement_social.is_not(None))
                )
            ).scalar()
            or 0
        )
    return ListResponse(
        total=total, properties=out, sociaux_exclus=sociaux_exclus
    )


_COLONNES_EXPORT = [
    "Matricule",
    "Adresse",
    "Numéro civique (début)",
    "Numéro civique (fin)",
    "Rue",
    "Suite",
    "Municipalité",
    "Arrondissement",
    "Région",
    "Nombre de logements",
    "Année de construction",
    "Code d'utilisation",
    "Utilisation",
    "Catégorie",
    "Superficie terrain (m²)",
    "Superficie bâtiment (m²)",
    "Propriétaires",
    "Adresse postale des propriétaires",
    "Statut des propriétaires",
    "Téléphone des propriétaires",
    "NEQ des propriétaires",
    "Inscription des propriétaires",
    "Propriétaire depuis (ans)",
    "Propriétaires vérifiés le",
    "Déjà un lead",
    "Logement social",
]


def _noms_proprietaires(owners_json: Optional[str]) -> Tuple[str, str]:
    """« Nom 1 | Nom 2 » et leurs dates d'inscription, depuis le cache
    EvalWeb (best-effort, jamais d'exception)."""
    if not owners_json:
        return "", ""
    try:
        data = json.loads(owners_json)
    except Exception:  # noqa: BLE001
        return "", ""
    noms, dates = [], []
    for o in data or []:
        if not isinstance(o, dict) or not o.get("name"):
            continue
        noms.append(str(o.get("name")).strip())
        dates.append(str(o.get("inscription_date") or "").strip())
    return " | ".join(noms), " | ".join(dates)


def _details_proprietaires(owners_json: Optional[str]) -> Dict[str, str]:
    """Adresse postale, statut, téléphone et NEQ des propriétaires collectés
    (Phil 2026-09-28 : « le nom du propriétaire ainsi que l'adresse »),
    dans l'ordre des noms, joints par « | » (best-effort, jamais
    d'exception)."""
    vide = {"adresses": "", "statuts": "", "telephones": "", "neqs": ""}
    if not owners_json:
        return vide
    try:
        data = json.loads(owners_json)
    except Exception:  # noqa: BLE001
        return vide
    cols: Dict[str, List[str]] = {k: [] for k in vide}
    for o in data or []:
        if not isinstance(o, dict) or not o.get("name"):
            continue
        cols["adresses"].append(str(o.get("postal_address") or "").strip())
        cols["statuts"].append(str(o.get("statut") or "").strip())
        cols["telephones"].append(str(o.get("phone") or "").strip())
        cols["neqs"].append(str(o.get("req_neq") or "").strip())
    return {k: (" | ".join(v) if any(v) else "") for k, v in cols.items()}


class MatriculesACollecterOut(BaseModel):
    """Matricules que l'extension doit consulter sur montreal.ca."""

    matricules: List[str] = Field(default_factory=list)
    #: Unités qui matchent les filtres (avec ou sans propriétaire connu).
    total: int = 0
    #: … dont propriétaire déjà connu (owners_json non vide).
    deja_connus: int = 0
    plafond: int = 0
    tronque: bool = False


@router.get("/matricules", response_model=MatriculesACollecterOut)
async def matricules_a_collecter(
    db: DBSession,
    _: CurrentUser,
    min_logements: Optional[int] = Query(default=None, ge=0),
    max_logements: Optional[int] = Query(default=None, ge=0),
    min_annee: Optional[int] = Query(default=None, ge=1700),
    max_annee: Optional[int] = Query(default=None, le=2100),
    min_superficie_terrain: Optional[float] = Query(default=None, ge=0),
    municipalite: Optional[str] = Query(default=None),
    region: Optional[str] = Query(
        default=None, pattern="^(mtl-island|laval|rive-sud|rive-nord)$"
    ),
    distance_band: Optional[str] = Query(
        default=None,
        pattern="^(mtl_only|under_30|30_to_40|40_to_50|over_50)$",
    ),
    nom_rue_contains: Optional[str] = Query(default=None),
    arrondissement: Optional[str] = Query(default=None),
    codes_utilisation: Optional[List[str]] = Query(default=None),
    exclure_sociaux: bool = Query(default=False),
    numero_civique: Optional[str] = Query(default=None),
    proprietaire_min_annees: Optional[int] = Query(default=None, ge=0, le=150),
    exclure_residences_aines: bool = Query(default=False),
    sans_proprietaire: bool = Query(default=True),
    limite: int = Query(default=5000, ge=1, le=20000),
) -> MatriculesACollecterOut:
    """Collecte EN LOT des propriétaires (Phil 2026-09-28 : « 12 à 24
    logements pour commencer, on peut choisir un quartier ») : mêmes
    filtres que la page Immeubles MTL ; par défaut seulement les unités
    SANS propriétaire connu, triées par matricule, plafonnées (l'extension
    les consulte une à une sur montreal.ca)."""
    if proprietaire_min_annees:
        await _completer_proprietaire_depuis(db)
    filters = _filtres_mtl(
        min_logements=min_logements,
        max_logements=max_logements,
        min_annee=min_annee,
        max_annee=max_annee,
        min_superficie_terrain=min_superficie_terrain,
        municipalite=municipalite,
        region=region,
        distance_band=distance_band,
        nom_rue_contains=nom_rue_contains,
        arrondissement=arrondissement,
        codes_utilisation=codes_utilisation,
        exclure_sociaux=exclure_sociaux,
        numero_civique=numero_civique,
        proprietaire_min_annees=proprietaire_min_annees,
        exclure_residences_aines=exclure_residences_aines,
    )
    sans_owner = or_(
        MontrealPropertyUnit.owners_json.is_(None),
        MontrealPropertyUnit.owners_json == "",
        MontrealPropertyUnit.owners_json == "[]",
    )
    total = (
        await db.execute(
            select(func.count()).select_from(MontrealPropertyUnit).where(*filters)
        )
    ).scalar_one() or 0
    inconnus = (
        await db.execute(
            select(func.count())
            .select_from(MontrealPropertyUnit)
            .where(*filters, sans_owner)
        )
    ).scalar_one() or 0
    q = (
        select(MontrealPropertyUnit.matricule)
        .where(*filters, MontrealPropertyUnit.matricule.is_not(None))
        .order_by(MontrealPropertyUnit.matricule.asc())
        .limit(limite + 1)
    )
    if sans_proprietaire:
        q = q.where(sans_owner)
    rows = [r[0] for r in (await db.execute(q)).all() if r[0]]
    tronque = len(rows) > limite
    return MatriculesACollecterOut(
        matricules=rows[:limite],
        total=int(total),
        deja_connus=int(total) - int(inconnus),
        plafond=limite,
        tronque=tronque,
    )


@router.get("/export.csv")
async def export_properties_csv(
    db: DBSession,
    _: CurrentUser,
    min_logements: Optional[int] = Query(default=None, ge=0),
    max_logements: Optional[int] = Query(default=None, ge=0),
    min_annee: Optional[int] = Query(default=None, ge=1700),
    max_annee: Optional[int] = Query(default=None, le=2100),
    min_superficie_terrain: Optional[float] = Query(default=None, ge=0),
    municipalite: Optional[str] = Query(default=None),
    region: Optional[str] = Query(
        default=None, pattern="^(mtl-island|laval|rive-sud|rive-nord)$"
    ),
    distance_band: Optional[str] = Query(
        default=None,
        pattern="^(mtl_only|under_30|30_to_40|40_to_50|over_50)$",
    ),
    nom_rue_contains: Optional[str] = Query(default=None),
    arrondissement: Optional[str] = Query(default=None),
    codes_utilisation: Optional[List[str]] = Query(default=None),
    exclure_sociaux: bool = Query(default=False),
    numero_civique: Optional[str] = Query(default=None),
    proprietaire_min_annees: Optional[int] = Query(default=None, ge=0, le=150),
    exclure_residences_aines: bool = Query(default=False),
) -> StreamingResponse:
    """TOUTES les unités qui matchent les filtres, en CSV (BOM + « ; »,
    lisible dans Excel), en flux : ~940 000 lignes passent sans
    charger la base en mémoire (demande Phil 2026-09-22 : « donne-moi
    ce fichier »). Mêmes filtres que la page ; tri par matricule."""
    if proprietaire_min_annees:
        await _completer_proprietaire_depuis(db)
    filters = _filtres_mtl(
        min_logements=min_logements,
        max_logements=max_logements,
        min_annee=min_annee,
        max_annee=max_annee,
        min_superficie_terrain=min_superficie_terrain,
        municipalite=municipalite,
        region=region,
        distance_band=distance_band,
        nom_rue_contains=nom_rue_contains,
        arrondissement=arrondissement,
        codes_utilisation=codes_utilisation,
        exclure_sociaux=exclure_sociaux,
        numero_civique=numero_civique,
        proprietaire_min_annees=proprietaire_min_annees,
        exclure_residences_aines=exclure_residences_aines,
    )
    # Matricules déjà en lead (quelques milliers) — chargés une fois.
    deja_leads = {
        m
        for (m,) in (
            await db.execute(
                select(ProspectionLead.matricule).where(
                    ProspectionLead.matricule.is_not(None),
                    ProspectionLead.archived.is_(False),
                )
            )
        ).all()
        if m
    }

    from app.db.session import AsyncSessionLocal

    def _ligne(p: MontrealPropertyUnit) -> list:
        noms, dates = _noms_proprietaires(p.owners_json)
        det = _details_proprietaires(p.owners_json)
        depuis_d = p.proprietaire_depuis or (
            min(
                (x for x in (_date_inscription(t) for t in dates.split(" | ")) if x),
                default=None,
            )
            if dates
            else None
        )
        depuis = _annees_ecoulees(depuis_d) if depuis_d else None
        return [
            p.matricule,
            _full_addr(p) or "",
            p.civique_debut or "",
            p.civique_fin or "",
            p.nom_rue or "",
            p.suite_debut or "",
            p.municipalite or "",
            p.arrondissement or "",
            p.region or "",
            p.nombre_logement if p.nombre_logement is not None else "",
            p.annee_construction if p.annee_construction is not None else "",
            p.code_utilisation or "",
            p.libelle_utilisation or "",
            p.categorie_uef or "",
            float(p.superficie_terrain) if p.superficie_terrain is not None else "",
            float(p.superficie_batiment) if p.superficie_batiment is not None else "",
            noms,
            det["adresses"],
            det["statuts"],
            det["telephones"],
            det["neqs"],
            dates,
            depuis if depuis is not None else "",
            (
                p.owners_fetched_at.date().isoformat()
                if p.owners_fetched_at
                else ""
            ),
            "oui" if p.matricule in deja_leads else "non",
            p.logement_social or "",
        ]

    async def _flux():
        # Session DÉDIÉE : celle de la requête est refermée avant que
        # le flux ne coule (dépendance FastAPI avec yield).
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(_COLONNES_EXPORT)
        yield "\ufeff" + buf.getvalue()
        dernier = ""
        async with AsyncSessionLocal() as s:
            while True:
                stmt = select(MontrealPropertyUnit)
                for f in filters:
                    stmt = stmt.where(f)
                stmt = (
                    stmt.where(MontrealPropertyUnit.matricule > dernier)
                    .order_by(MontrealPropertyUnit.matricule.asc())
                    .limit(5000)
                )
                rows = (await s.execute(stmt)).scalars().all()
                if not rows:
                    break
                buf = io.StringIO()
                w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
                for p in rows:
                    w.writerow(_ligne(p))
                yield buf.getvalue()
                dernier = rows[-1].matricule
                s.expunge_all()

    nom = f"kratos_roles-fonciers_{_date.today().isoformat()}.csv"
    return StreamingResponse(
        _flux(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{nom}"',
            "Cache-Control": "no-store",
        },
    )


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
    summary="État de la table mtl_property_units (lecture seule).",
)
async def mtl_diagnostics(
    db: DBSession, _: CurrentUser
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
async def mtl_health(db: DBSession, _: CurrentUser) -> MtlHealth:
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
