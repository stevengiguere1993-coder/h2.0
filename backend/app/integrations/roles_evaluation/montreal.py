"""Rôle d'évaluation foncière de la Ville de Montréal.

Source : `donnees.montreal.ca/dataset/unites-evaluation-fonciere`
(CSV public, ~500k unités, libre de droits).

Deux flots :
- `ingest_csv()` : télécharge le CSV depuis l'open data, parse et
  insère/met-à-jour la table `mtl_property_units` (idempotent via PK
  matricule). Long (qq minutes), à exécuter manuellement via l'endpoint
  admin une fois par an quand la ville publie le nouveau rôle.
- `lookup_by_address()` : recherche rapide à partir d'une adresse
  saisie côté frontend (« 4520 Boulevard Saint-Laurent ») → retourne
  le matricule, le nb de logements, l'année de construction et les
  superficies.

⚠ Ce dataset NE contient PAS le nom du propriétaire (vie privée).
Pour le propriétaire, on combine avec REQ (corporations) ou via la
recherche manuelle dans l'app evalweb de la Ville (boutons externes).
"""

from __future__ import annotations

import asyncio
import csv
import logging
import re
import tempfile
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.montreal_property_unit import MontrealPropertyUnit

log = logging.getLogger(__name__)

# URL publique du CSV (ressource fixe du dataset, ~150-200 Mo).
MTL_CSV_URL = (
    "https://donnees.montreal.ca/dataset/"
    "4ad6baea-4d2c-460f-a8bf-5d000db498f7/resource/"
    "2b9dfc3d-91d3-48de-b32c-a2a6d9417079/download/"
    "uniteevaluationfonciere.csv"
)

# UA navigateur — le CDN bloque les UA python-httpx/curl par défaut.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


# --------------------------- Normalisation ---------------------------


_TYPE_VOIE_RE = re.compile(
    r"^(rue|avenue|av|boulevard|boul|bd|chemin|ch|"
    r"place|pl|allée|allee|cote|côte|"
    r"ruelle|carre|carré|impasse|terrasse)\s+",
    re.IGNORECASE,
)

_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_SPACES_RE = re.compile(r"\s+")


def _strip_accents(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


def normalize_street(name: str) -> str:
    """Réduit un nom de rue à une forme canonique.

    « Boulevard Saint-Laurent » et « boul. saint-laurent » donnent tous
    deux « saint laurent » — la clé de jointure côté adresse.
    """
    if not name:
        return ""
    s = _strip_accents(name).lower().strip()
    # Strip punctuation FIRST so "boul." matches the voie regex which
    # only handles trailing whitespace, not periods.
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACES_RE.sub(" ", s).strip()
    s = _TYPE_VOIE_RE.sub("", s)
    s = _SPACES_RE.sub(" ", s).strip()
    return s


def make_search_key(civic: str | int, street: str) -> str:
    """Clé de recherche : `<civique>|<rue normalisée>`."""
    c = str(civic).strip().lstrip("0") or "0"
    return f"{c}|{normalize_street(street)}"


# --------------------------- Lookup ---------------------------


async def lookup_by_address(
    db: AsyncSession,
    address: str,
) -> Optional[Dict[str, Any]]:
    """Recherche dans le rôle Montréal à partir d'une adresse type
    « 4520 Boulevard Saint-Laurent ».

    Retourne un dict prêt à fusionner avec `ProspectionLead` :
        {
            "matricule": "...",
            "nb_logements": 8,
            "annee_construction": 1962,
            "superficie_terrain": 365.0,
            "superficie_batiment": 450.0,
            "libelle_utilisation": "Logement",
        }
    None si pas de match.
    """
    if not address:
        return None
    parts = address.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    civic_raw, rue = parts[0], parts[1]
    m = re.match(r"^(\d+)", civic_raw)
    if not m:
        return None
    civic = m.group(1)
    key = make_search_key(civic, rue)

    row = (
        await db.execute(
            select(MontrealPropertyUnit).where(
                MontrealPropertyUnit.search_key == key
            )
        )
    ).scalars().first()
    if row is None:
        return None
    return {
        "matricule": row.matricule,
        "nb_logements": row.nombre_logement,
        "annee_construction": row.annee_construction,
        "superficie_terrain": (
            float(row.superficie_terrain)
            if row.superficie_terrain is not None
            else None
        ),
        "superficie_batiment": (
            float(row.superficie_batiment)
            if row.superficie_batiment is not None
            else None
        ),
        "libelle_utilisation": row.libelle_utilisation,
    }


# --------------------------- Ingestion ---------------------------


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


def _row_to_dict(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    matricule = (row.get("MATRICULE83") or "").strip()
    if not matricule:
        return None
    civic = (row.get("CIVIQUE_DEBUT") or "").strip()
    rue = (row.get("NOM_RUE") or "").strip()
    return {
        "matricule": matricule,
        "civique_debut": civic or None,
        "civique_fin": (row.get("CIVIQUE_FIN") or "").strip() or None,
        "nom_rue": rue or None,
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
        "categorie_uef": (row.get("CATEGORIE_UEF") or "").strip() or None,
        "superficie_terrain": _parse_float(
            row.get("SUPERFICIE_TERRAIN", "")
        ),
        "superficie_batiment": _parse_float(
            row.get("SUPERFICIE_BATIMENT", "")
        ),
        "search_key": (
            make_search_key(civic, rue) if civic and rue else None
        ),
        # Tag explicite « mtl-island » pour distinguer du rôle provincial
        # (rive-sud/laval/rive-nord) ingéré par un autre flow.
        "region": "mtl-island",
    }


async def _bulk_upsert(
    db: AsyncSession, batch: Iterable[Dict[str, Any]]
) -> int:
    rows: List[Dict[str, Any]] = list(batch)
    if not rows:
        return 0
    stmt = pg_insert(MontrealPropertyUnit).values(rows)
    update_cols = {
        c.name: getattr(stmt.excluded, c.name)
        for c in MontrealPropertyUnit.__table__.columns
        if c.name != "matricule"
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["matricule"], set_=update_cols
    )
    # Retry sur connection drop (Render free coupe les conn idles
    # pendant les longs imports). pool_pre_ping reconnecte au prochain
    # acquire, mais il faut rollback puis ré-essayer.
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            await db.execute(stmt)
            return len(rows)
        except Exception as exc:
            msg = str(exc).lower()
            transient = (
                "connection" in msg
                and ("closed" in msg or "does not exist" in msg)
            ) or "ssl connection has been closed" in msg
            if not transient:
                raise
            last_err = exc
            log.warning(
                "Bulk upsert connection drop (attempt %d/3): %s",
                attempt + 1,
                exc,
            )
            try:
                await db.rollback()
            except Exception:
                pass
            await asyncio.sleep(2 * (attempt + 1))
    if last_err:
        raise last_err
    return 0


async def _download_csv_to_tempfile(url: str) -> str:
    """Télécharge le CSV en streaming dans un fichier temporaire et
    retourne le chemin. Le fichier est laissé en place (l'appelant
    s'occupe du cleanup s'il le souhaite, ou on laisse l'OS le purger
    à la fin du process)."""
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".csv", prefix="mtl_eval_"
    )
    headers = {"User-Agent": USER_AGENT, "Accept": "text/csv"}
    timeout = httpx.Timeout(600.0, connect=30.0)
    bytes_total = 0
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True
        ) as http:
            async with http.stream("GET", url, headers=headers) as r:
                r.raise_for_status()
                async for chunk in r.aiter_bytes(chunk_size=65536):
                    tmp.write(chunk)
                    bytes_total += len(chunk)
        tmp.flush()
    finally:
        tmp.close()
    log.info("Montreal CSV downloaded: %d bytes -> %s", bytes_total, tmp.name)
    return tmp.name


async def ingest_csv(
    db: AsyncSession,
    *,
    url: str = MTL_CSV_URL,
    batch_size: int = 1000,
    max_rows: Optional[int] = None,
    csv_path: Optional[str] = None,
) -> Dict[str, int]:
    """Télécharge et ingère le CSV Montréal.

    Idempotent : sur ré-import, ON CONFLICT (matricule) → UPDATE.

    Args:
        max_rows : utile pour les tests/timeout (bornage). None = tout
            le CSV (~500k lignes, qq minutes).
        csv_path : si fourni, saute le téléchargement et lit ce fichier
            local (utile en dev / pour rejouer un import).
    """
    path = csv_path or await _download_csv_to_tempfile(url)
    processed = 0
    upserted = 0
    batch: List[Dict[str, Any]] = []

    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = _row_to_dict(row)
            if parsed is None:
                continue
            batch.append(parsed)
            processed += 1
            if max_rows and processed >= max_rows:
                break
            if len(batch) >= batch_size:
                upserted += await _bulk_upsert(db, batch)
                batch.clear()
                await db.commit()
        if batch:
            upserted += await _bulk_upsert(db, batch)
            await db.commit()

    log.info(
        "Montreal eval ingest: processed=%d upserted=%d",
        processed,
        upserted,
    )
    return {"rows_processed": processed, "rows_upserted": upserted}
