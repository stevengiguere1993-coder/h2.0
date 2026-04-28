"""Importeur générique pour les rôles d'évaluation provinciaux.

Le ministère MAMH (Affaires municipales du Québec) publie chaque
année un rôle d'évaluation foncière agrégé. Format CSV avec mêmes
colonnes que MTL mais pour toutes les municipalités.

URL canonique : https://www.donneesquebec.ca/recherche/dataset/
                 roles-evaluation-fonciere-du-quebec

Stratégie :
- L'utilisateur télécharge le CSV provincial (~3-5 GB selon l'année)
  depuis donneesquebec.ca dans son navigateur, l'upload chunked
  vers Render (comme REQ).
- Le serveur stream-parse le CSV par lignes, filtre par liste de
  municipalités (Laval, Longueuil, Brossard…) pour ne garder que
  les unités dans le rayon 50 km autour de Montréal.
- Stocke dans `mtl_property_units` (table partagée) avec un champ
  `region` pour distinguer.

Note : on réutilise la même table que MTL plutôt que d'en créer
une nouvelle. Le champ `region` permet de filtrer côté UI.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Dict, Iterable, List, Optional, Set

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.montreal_property_unit import MontrealPropertyUnit

log = logging.getLogger(__name__)


# Municipalités dans un rayon ~50 km de Montréal.
# Ordre alphabétique. Les codes/noms doivent matcher la colonne
# « MUNICIPALITE » du CSV provincial (souvent un code numérique).
RIVE_SUD_CITIES: Set[str] = {
    # Longueuil et arrondissements
    "Longueuil", "Saint-Hubert", "Saint-Lambert",
    "Boucherville", "Brossard",
    # Vallée du Richelieu / proche
    "Saint-Bruno-de-Montarville", "Sainte-Julie",
    "Chambly", "Saint-Basile-le-Grand",
    "Beloeil", "McMasterville",
    "Saint-Mathieu-de-Beloeil", "Otterburn Park",
    # Champlain
    "Candiac", "La Prairie", "Saint-Constant",
    "Sainte-Catherine", "Saint-Philippe",
    "Saint-Jean-sur-Richelieu", "Saint-Mathias-sur-Richelieu",
}

LAVAL_CITIES: Set[str] = {
    "Laval",
    "Chomedey", "Sainte-Dorothée", "Pont-Viau", "Auteuil",
    "Vimont", "Sainte-Rose", "Saint-Vincent-de-Paul",
}

RIVE_NORD_CITIES: Set[str] = {
    # Couronne Nord
    "Terrebonne", "Mascouche", "Repentigny", "Charlemagne",
    "L'Assomption", "Lachenaie",
    # Laurentides Sud
    "Saint-Eustache", "Deux-Montagnes", "Sainte-Marthe-sur-le-Lac",
    "Saint-Joseph-du-Lac",
    "Boisbriand", "Sainte-Thérèse", "Blainville", "Lorraine",
    "Rosemère", "Bois-des-Filion",
    "Mirabel", "Saint-Sauveur",
    "Sainte-Anne-des-Plaines",
}

ALL_REGIONS = {
    "rive-sud": RIVE_SUD_CITIES,
    "laval": LAVAL_CITIES,
    "rive-nord": RIVE_NORD_CITIES,
}


def _normalize_city(s: str) -> str:
    """Lower + sans accents pour matching robuste."""
    import unicodedata

    if not s:
        return ""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(
        c for c in nfd if not unicodedata.combining(c)
    ).lower().strip()


def _build_match_set(cities: Iterable[str]) -> Set[str]:
    return {_normalize_city(c) for c in cities}


def _parse_int(v: str) -> Optional[int]:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _parse_float(v: str) -> Optional[float]:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _row_to_dict(row: Dict[str, str], region: str) -> Optional[Dict]:
    """Mêmes colonnes que MTL — on réutilise la structure."""
    matricule = (row.get("MATRICULE83") or "").strip()
    if not matricule:
        return None
    return {
        "matricule": matricule,
        "civique_debut": (row.get("CIVIQUE_DEBUT") or "").strip() or None,
        "civique_fin": (row.get("CIVIQUE_FIN") or "").strip() or None,
        "nom_rue": (row.get("NOM_RUE") or "").strip() or None,
        "suite_debut": (row.get("SUITE_DEBUT") or "").strip() or None,
        "municipalite": (row.get("MUNICIPALITE") or "").strip() or None,
        "nombre_logement": _parse_int(row.get("NOMBRE_LOGEMENT", "")),
        "annee_construction": _parse_int(
            row.get("ANNEE_CONSTRUCTION", "")
        ),
        "code_utilisation": (row.get("CODE_UTILISATION") or "").strip()
        or None,
        "libelle_utilisation": (
            row.get("LIBELLE_UTILISATION") or ""
        ).strip()
        or None,
        "categorie_uef": (
            row.get("CATEGORIE_UEF") or ""
        ).strip()
        or None,
        "superficie_terrain": _parse_float(
            row.get("SUPERFICIE_TERRAIN", "")
        ),
        "superficie_batiment": _parse_float(
            row.get("SUPERFICIE_BATIMENT", "")
        ),
        "region": region,
    }


async def _bulk_upsert(
    db: AsyncSession, batch: List[Dict]
) -> int:
    """Upsert ON CONFLICT (matricule). Retourne le nb de lignes."""
    if not batch:
        return 0
    stmt = pg_insert(MontrealPropertyUnit).values(batch)
    update_cols = {
        c.name: stmt.excluded[c.name]
        for c in MontrealPropertyUnit.__table__.columns
        if c.name not in ("matricule",)
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["matricule"], set_=update_cols
    )
    await db.execute(stmt)
    return len(batch)


async def ingest_provincial_csv(
    db: AsyncSession,
    csv_path: str,
    *,
    region: str,
    cities: Optional[Iterable[str]] = None,
    batch_size: int = 2000,
    max_rows: Optional[int] = None,
) -> dict:
    """Ingère le CSV provincial filtré par région + liste de villes.

    Args:
        csv_path : chemin local vers le CSV.
        region : « rive-sud », « laval », « rive-nord » ou autre.
        cities : si fourni, on garde uniquement les unités dont
                 MUNICIPALITE matche (insensible accents/casse).
                 Si None, on prend la liste pré-définie de la région.
        batch_size : nb de lignes par bulk insert.
        max_rows : limite pour tests (None = tout).

    Stream-parse le CSV (RAM bornée à ~10 Mo).
    """
    cities_used = (
        list(cities)
        if cities
        else list(ALL_REGIONS.get(region, set()))
    )
    match_set = _build_match_set(cities_used)
    log.info(
        "Ingest provincial : region=%s, %d villes",
        region,
        len(match_set),
    )

    total_seen = 0
    total_kept = 0
    batch: List[Dict] = []

    with open(csv_path, "r", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        for raw_row in reader:
            total_seen += 1
            if max_rows is not None and total_seen > max_rows:
                break

            mun = _normalize_city(
                raw_row.get("MUNICIPALITE") or ""
            )
            if match_set and mun not in match_set:
                continue

            row = _row_to_dict(raw_row, region)
            if row is None:
                continue
            batch.append(row)
            total_kept += 1

            if len(batch) >= batch_size:
                await _bulk_upsert(db, batch)
                batch.clear()

            if total_seen % 100_000 == 0:
                log.info(
                    "  %d lignes parcourues, %d gardées",
                    total_seen,
                    total_kept,
                )

    if batch:
        await _bulk_upsert(db, batch)

    log.info(
        "Ingest provincial fini : seen=%d kept=%d region=%s",
        total_seen,
        total_kept,
        region,
    )
    return {
        "rows_processed": total_seen,
        "rows_upserted": total_kept,
        "region": region,
    }
