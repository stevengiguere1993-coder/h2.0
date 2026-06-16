"""Loyers moyens SCHL — ingestion CSV + lookup par zone.

Le portail SCHL exporte des CSV au format pivot (une colonne par taille,
une ligne par zone). Le format évolue selon les exports ; cet ingest
est tolérant et accepte plusieurs en-têtes connus.

Format attendu après normalisation :
    CMA, Zone, Bedrooms (0-3), AvgRent, VacancyRate, SampleSize, Year

Mapping des intitulés SCHL → bedrooms (entier 0-3) :
    "Bachelor"   / "Studio"    -> 0  (1½)
    "1 Bedroom"  / "1 chambre" -> 1  (2½)
    "2 Bedroom"  / "2 chambres"-> 2  (3½)
    "3 Bedroom +"/ "3+ chambres"-> 3 (4½, 5½, 6½)

Les usagers QC raisonnent en 1½/2½/.../6½ ; on fait la conversion à
l'affichage côté frontend.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_rent import MarketRent

log = logging.getLogger(__name__)


# --------------------------- Normalisation ---------------------------


def _strip_accents(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


def normalize_zone(s: str) -> str:
    """Réduit un nom de zone SCHL à une forme canonique pour comparer
    avec un lead.city ou un nom de quartier."""
    if not s:
        return ""
    s = _strip_accents(s).lower().strip()
    s = re.sub(r"[–—\-]", " ", s)  # tirets variés → espace
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Brackets accepted in the SCHL CSV.
_BEDROOM_PATTERNS: list[tuple[str, int]] = [
    ("bachelor", 0),
    ("studio", 0),
    ("1 bedroom", 1),
    ("1 chambre", 1),
    ("2 bedroom", 2),
    ("2 chambres", 2),
    ("3 bedroom", 3),
    ("3+ bedroom", 3),
    ("3 chambres", 3),
    ("3+ chambres", 3),
]


def _parse_bedroom(label: str) -> Optional[int]:
    n = normalize_zone(label)
    for prefix, val in _BEDROOM_PATTERNS:
        if n.startswith(prefix):
            return val
    return None


def _parse_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    # Retire TOUS les espaces, y compris insécables (SCHL : « 1 268 »).
    s = re.sub(r"\s+", "", str(v)).replace("$", "").replace(",", "")
    if not s or s.lower() in ("n/a", "na", "**", "..", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_rent_loose(v: Any) -> Optional[float]:
    """Extrait un loyer d'une cellule SCHL (« 1 268 », « 2 092 $ », « ** »)."""
    if v is None:
        return None
    s = re.sub(r"\s+", "", str(v)).replace("$", "").replace(",", "")
    if not s or s in ("**", "..", "-"):
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def _parse_matrix_format(
    text: str, default_year: Optional[int]
) -> Optional[List[Dict[str, Any]]]:
    """Parse l'export HMIP « TableExport » : 1-2 lignes de titre, une
    ligne d'en-tête large (Studio / 1 chambre / 2 chambres / 3 chambres +
    / Total, avec une colonne de code de fiabilité après chaque valeur),
    une zone par ligne, des notes/source en pied. Retourne ``None`` si le
    fichier n'a pas cette forme (→ on tombe sur le parsing classique)."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return None

    # 1) Ligne d'en-tête : >= 2 libellés de chambres, et soit col0 vide,
    # soit des lignes de titre avant (pour ne pas confondre avec un wide
    # classique dont la 1re colonne est « CMA »).
    header_idx = None
    col_to_bed: Dict[int, int] = {}
    for i, row in enumerate(rows[:20]):
        beds = {
            ci: b
            for ci, cell in enumerate(row)
            if (b := _parse_bedroom(cell or "")) is not None
        }
        first = (row[0] if row else "").strip()
        if len(beds) >= 2 and (i >= 1 or not first):
            header_idx, col_to_bed = i, beds
            break
    if header_idx is None:
        return None

    # 2) Année : depuis les lignes de titre, sinon défaut.
    year = default_year
    for row in rows[:header_idx]:
        for cell in row:
            m = re.search(r"\b(20\d{2})\b", str(cell or ""))
            if m:
                year = int(m.group(1))
                break
        if year is not None and year != default_year:
            break
    if year is None:
        from datetime import datetime

        year = datetime.now().year

    # 3) CMA : depuis la 1re ligne de titre (avant un tiret), sinon Montréal.
    cma = "Montréal"
    if rows[0]:
        title = str(rows[0][0] or "")
        first = re.split(r"[–—\-]", title)[0].strip()
        if first:
            cma = first
    cma_norm = normalize_zone(cma)

    # 4) Données : zone en col0, valeurs aux colonnes de chambres.
    out: List[Dict[str, Any]] = []
    for row in rows[header_idx + 1:]:
        if not row:
            continue
        zone = (row[0] or "").strip()
        if not zone:
            continue
        zl = zone.lower()
        if zl.startswith(("note", "source", "**", "©", "+")):
            break  # pied de tableau
        z_norm = normalize_zone(zone)
        is_total = (
            z_norm == cma_norm
            or "ensemble" in zl
            or zl.startswith("total")
            or "rmr" in zl
        )
        zone_out = None if is_total else zone
        for ci, bed in col_to_bed.items():
            raw = row[ci] if ci < len(row) else ""
            rent = _parse_rent_loose(raw)
            if rent and 100 <= rent <= 10000:
                out.append(
                    {
                        "cma": cma,
                        "zone": zone_out,
                        "bedrooms": bed,
                        "avg_rent": rent,
                        "vacancy_rate": None,
                        "sample_size": None,
                        "year": year,
                    }
                )
    return out or None


def _parse_int(v: Any) -> Optional[int]:
    f = _parse_float(v)
    return int(f) if f is not None else None


# --------------------------- Lookup ---------------------------


async def lookup_rents(
    db: AsyncSession,
    *,
    cma: Optional[str] = None,
    zone: Optional[str] = None,
    year: Optional[int] = None,
) -> List[MarketRent]:
    """Recherche les 4 brackets de loyers pour une zone donnée.

    Stratégie en cascade :
    1. Match exact (CMA + zone + year)
    2. Fallback : CMA + zone (le plus récent)
    3. Fallback : CMA seul (le plus récent, zone null)

    Retourne 0..4 MarketRent (un par bracket si dispo).
    """
    if not cma:
        return []

    # Étape 1 : (cma, zone, year) si fourni
    if zone and year:
        rows = (
            await db.execute(
                select(MarketRent)
                .where(MarketRent.cma == cma)
                .where(MarketRent.zone == zone)
                .where(MarketRent.year == year)
                .order_by(MarketRent.bedrooms.asc())
            )
        ).scalars().all()
        if rows:
            return list(rows)

    # Étape 2 : (cma, zone) — la dernière année dispo
    if zone:
        rows = (
            await db.execute(
                select(MarketRent)
                .where(MarketRent.cma == cma)
                .where(MarketRent.zone == zone)
                .order_by(
                    MarketRent.year.desc(), MarketRent.bedrooms.asc()
                )
            )
        ).scalars().all()
        # Garde uniquement la dernière année
        if rows:
            latest = rows[0].year
            return [r for r in rows if r.year == latest]

    # Étape 3 : CMA agrégat (zone null), dernière année
    rows = (
        await db.execute(
            select(MarketRent)
            .where(MarketRent.cma == cma)
            .where(MarketRent.zone.is_(None))
            .order_by(
                MarketRent.year.desc(), MarketRent.bedrooms.asc()
            )
        )
    ).scalars().all()
    if rows:
        latest = rows[0].year
        return [r for r in rows if r.year == latest]
    return []


def best_match_for_lead(
    *, lead_city: Optional[str], available_zones: list[str]
) -> Optional[str]:
    """Trouve la zone SCHL qui matche le mieux le lead.city."""
    if not lead_city:
        return None
    target = normalize_zone(lead_city)
    if not target:
        return None
    # Match exact d'abord
    for z in available_zones:
        if normalize_zone(z) == target:
            return z
    # Match partiel : la zone contient la ville ou inversement
    for z in available_zones:
        nz = normalize_zone(z)
        if target in nz or nz in target:
            return z
    return None


# --------------------------- Ingestion ---------------------------


# En-têtes connus des CSV SCHL (varient selon la langue / l'export).
_CMA_KEYS = ("CMA", "RMR", "Region", "Région", "Geo", "Geographie")
_ZONE_KEYS = ("Zone", "Sub-Zone", "Sous-zone", "Quartier", "Neighbourhood")
_YEAR_KEYS = ("Year", "Annee", "Année", "Survey Year")
_BEDROOMS_KEYS = (
    "Bedrooms",
    "Bedroom Type",
    "Type",
    "Type de logement",
    "Chambres",
)
_RENT_KEYS = (
    "Average Rent",
    "Avg Rent",
    "Rent",
    "Loyer moyen",
    "Loyer",
)
_VAC_KEYS = (
    "Vacancy Rate",
    "Vacancy",
    "Taux d'inoccupation",
    "Taux inoccupation",
)
_SAMPLE_KEYS = ("Sample Size", "Sample", "Echantillon", "Échantillon")


def _pick(row: Dict[str, str], *keys: str) -> str:
    for k in keys:
        if k in row and row[k] is not None:
            v = str(row[k]).strip()
            if v:
                return v
    # Lookup case-insensitive en dernier recours
    lower = {k.lower(): v for k, v in row.items() if k}
    for k in keys:
        v = lower.get(k.lower())
        if v is not None:
            s = str(v).strip()
            if s:
                return s
    return ""


def _parse_long_format(
    row: Dict[str, str], default_year: int
) -> Optional[Dict[str, Any]]:
    """Format « long » : une ligne par (zone, bracket).

    Colonnes attendues : CMA, Zone, Bedrooms, AvgRent, VacancyRate,
    SampleSize, Year.
    """
    cma = _pick(row, *_CMA_KEYS)
    if not cma:
        return None
    zone = _pick(row, *_ZONE_KEYS) or None
    bedroom_label = _pick(row, *_BEDROOMS_KEYS)
    bedrooms = _parse_bedroom(bedroom_label)
    if bedrooms is None:
        return None
    rent = _parse_float(_pick(row, *_RENT_KEYS))
    vac = _parse_float(_pick(row, *_VAC_KEYS))
    sample = _parse_int(_pick(row, *_SAMPLE_KEYS))
    year_v = _parse_int(_pick(row, *_YEAR_KEYS)) or default_year
    return {
        "cma": cma,
        "zone": zone,
        "bedrooms": bedrooms,
        "avg_rent": rent,
        "vacancy_rate": vac,
        "sample_size": sample,
        "year": year_v,
    }


def _parse_wide_format(
    row: Dict[str, str], default_year: int
) -> List[Dict[str, Any]]:
    """Format « pivot » : une ligne par zone, une colonne par bracket.

    Détecte les colonnes dont l'en-tête commence par « Bachelor »,
    « 1 Bedroom », etc. Une ligne du CSV produit jusqu'à 4 entrées
    en sortie.
    """
    cma = _pick(row, *_CMA_KEYS)
    if not cma:
        return []
    zone = _pick(row, *_ZONE_KEYS) or None
    year_v = _parse_int(_pick(row, *_YEAR_KEYS)) or default_year
    out: List[Dict[str, Any]] = []
    for header, value in row.items():
        if not header:
            continue
        bedrooms = _parse_bedroom(header)
        if bedrooms is None:
            continue
        rent = _parse_float(value)
        if rent is None:
            continue
        out.append(
            {
                "cma": cma,
                "zone": zone,
                "bedrooms": bedrooms,
                "avg_rent": rent,
                "vacancy_rate": None,
                "sample_size": None,
                "year": year_v,
            }
        )
    return out


async def _bulk_upsert(
    db: AsyncSession, batch: Iterable[Dict[str, Any]]
) -> int:
    rows = list(batch)
    if not rows:
        return 0
    stmt = pg_insert(MarketRent).values(rows)
    update_cols = {
        c.name: getattr(stmt.excluded, c.name)
        for c in MarketRent.__table__.columns
        if c.name not in ("id",)
    }
    stmt = stmt.on_conflict_do_update(
        constraint="uq_market_rent", set_=update_cols
    )
    await db.execute(stmt)
    return len(rows)


def _decode_csv(b: bytes) -> str:
    """Décode un CSV en essayant UTF-8 (BOM toléré) puis cp1252/latin-1.
    Le décodage strict lève sur des octets invalides, ce qui fait basculer
    proprement vers l'encodage SCHL (Windows-1252)."""
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


async def ingest_csv(
    db: AsyncSession,
    csv_bytes: bytes,
    *,
    default_year: Optional[int] = None,
    batch_size: int = 1000,
) -> Dict[str, int]:
    """Ingère un CSV SCHL (long ou wide format).

    Args:
        default_year : utilisé si la colonne Year est absente du CSV.
            Si None et absent → on prend l'année courante.
    """
    # Detect encoding. Les exports SCHL/HMIP sont souvent en Windows-1252
    # (cp1252), pas en UTF-8 : un décodage UTF-8 corromprait les « é » et
    # surtout l'espace insécable des montants (« 1 268 » → loyer rejeté).
    text = _decode_csv(csv_bytes)

    if default_year is None:
        from datetime import datetime
        default_year = datetime.now().year

    # Format HMIP « TableExport » (titres + en-tête large valeur/code) ?
    matrix = _parse_matrix_format(text, default_year)
    if matrix:
        for start in range(0, len(matrix), batch_size):
            await _bulk_upsert(db, matrix[start:start + batch_size])
            await db.commit()
        log.info("CMHC ingest (matrix): rows=%d", len(matrix))
        return {"rows_processed": len(matrix), "rows_upserted": len(matrix)}

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV sans en-tête.")

    # Détection du format : si une colonne Bedrooms existe → long ;
    # sinon si on trouve des en-têtes type bracket → wide.
    fields_lower = [f.lower() for f in reader.fieldnames if f]
    has_bedroom_col = any(
        any(k.lower() in f for k in _BEDROOMS_KEYS)
        for f in fields_lower
    )

    processed = 0
    batch: List[Dict[str, Any]] = []
    for row in reader:
        if has_bedroom_col:
            parsed = _parse_long_format(row, default_year)
            if parsed is not None:
                batch.append(parsed)
                processed += 1
        else:
            for parsed in _parse_wide_format(row, default_year):
                batch.append(parsed)
                processed += 1
        if len(batch) >= batch_size:
            await _bulk_upsert(db, batch)
            batch.clear()
            await db.commit()
    if batch:
        await _bulk_upsert(db, batch)
        await db.commit()

    log.info("CMHC ingest: rows_processed=%d", processed)
    return {"rows_processed": processed, "rows_upserted": processed}
