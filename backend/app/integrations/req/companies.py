"""Ingestion + lookup des corporations du Registraire des entreprises.

Source : « Données ouvertes du Registraire des entreprises » du Québec.
L'utilisateur télécharge le ZIP depuis le portail (Cloudflare laisse
passer un humain mais bloque les requêtes serveur), nous l'envoie via
l'endpoint admin, et on ingère.

Le ZIP contient plusieurs CSV. Le plus important est `entreprise.csv`
qui liste toutes les corporations actives avec leur NEQ, nom, statut
et adresse de domicile / siège.

Schémas REQ documentés ici :
https://www.donneesquebec.ca/recherche/dataset/registre-des-entreprises
"""

from __future__ import annotations

import csv
import io
import logging
import re
import unicodedata
import zipfile
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.req_company import ReqCompany

log = logging.getLogger(__name__)


# Le REQ utilise plusieurs noms de fichiers historiques. On essaie
# l'ensemble des candidats connus.
ENTREPRISE_CSV_NAMES = (
    "entreprise.csv",
    "Entreprise.csv",
    "ENTREPRISE.csv",
)
ADRESSE_CSV_NAMES = (
    "adresse.csv",
    "Adresse.csv",
    "ADRESSE.csv",
    "adresses.csv",
)


# ----------------------------- Normalisation -----------------------------


_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_SPACES_RE = re.compile(r"\s+")
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(inc|ltd|ltee|ltée|enr|sec|senc|sa|cie|corp|"
    r"corporation|holdings?|gp)\b\.?",
    re.IGNORECASE,
)


def _strip_accents(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


def normalize_company_name(name: str) -> str:
    """Réduit un nom de compagnie à une forme canonique.

    « Gestion 9123-4567 Québec Inc. » et « gestion 9123 4567 quebec »
    matchent.
    """
    if not name:
        return ""
    s = _strip_accents(name).lower().strip()
    s = _LEGAL_SUFFIX_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACES_RE.sub(" ", s).strip()
    return s


# ----------------------------- Lookup -----------------------------


async def lookup_by_name(
    db: AsyncSession, name: str, *, limit: int = 10
) -> List[ReqCompany]:
    """Recherche les corporations dont le nom matche (LIKE %term%).

    Insensible aux accents/casse via la colonne `nom_normalized`.
    """
    if not name:
        return []
    norm = normalize_company_name(name)
    if not norm:
        return []
    stmt = (
        select(ReqCompany)
        .where(ReqCompany.nom_normalized.like(f"%{norm}%"))
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def lookup_by_neq(
    db: AsyncSession, neq: str
) -> Optional[ReqCompany]:
    if not neq:
        return None
    return (
        await db.execute(
            select(ReqCompany).where(ReqCompany.neq == neq.strip())
        )
    ).scalars().first()


async def lookup_by_address(
    db: AsyncSession, address: str, city: Optional[str], *, limit: int = 20
) -> List[ReqCompany]:
    """Cherche les corporations dont le siège social correspond à
    l'adresse fournie. Utile pour identifier le propriétaire d'un
    multi-logement détenu par une compagnie à numéro qui a son siège
    à la même adresse.
    """
    if not address:
        return []
    addr = address.strip()
    if len(addr) < 4:
        return []
    stmt = select(ReqCompany).where(ReqCompany.adresse.ilike(f"%{addr}%"))
    if city:
        stmt = stmt.where(
            or_(
                ReqCompany.ville.ilike(f"%{city.strip()}%"),
                ReqCompany.ville.is_(None),
            )
        )
    return list((await db.execute(stmt.limit(limit))).scalars().all())


# ----------------------------- Ingestion -----------------------------


def _pick(row: Dict[str, str], *keys: str) -> str:
    """Récupère la première valeur non vide parmi plusieurs noms de
    colonne possibles (le REQ a renommé ses colonnes plusieurs fois)."""
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _entreprise_row_to_dict(
    row: Dict[str, str], adresses: Dict[str, Dict[str, str]]
) -> Optional[Dict[str, Any]]:
    neq = _pick(row, "NEQ", "neq")
    if not neq:
        return None
    nom = _pick(row, "NOM_ASSUJ", "NOM_ENTREPRISE", "nom", "Nom")
    statut = _pick(
        row, "STAT_IMMAT", "STATUT", "statut", "STAT_ENTREPRISE"
    )
    forme = _pick(
        row, "TYP_FORME_JURI", "FORME_JURIDIQUE", "forme_juridique"
    )
    date_imm = _pick(
        row, "DAT_IMMAT_ENTRP", "DATE_IMMAT", "date_immatriculation"
    )

    adr = adresses.get(neq) or {}
    return {
        "neq": neq,
        "nom": nom or None,
        "nom_normalized": normalize_company_name(nom) or None,
        "statut": statut or None,
        "forme_juridique": forme or None,
        "date_immatriculation": date_imm or None,
        "adresse": adr.get("adresse"),
        "ville": adr.get("ville"),
        "code_postal": adr.get("code_postal"),
    }


def _parse_adresses(
    csv_text: str,
) -> Dict[str, Dict[str, str]]:
    """Parse `adresse.csv` et garde l'adresse de domicile (la plus
    récente) par NEQ. Le fichier liste plusieurs adresses par
    entreprise (siège, domicile, etc.) ; on privilégie « DOMICILE »."""
    out: Dict[str, Dict[str, str]] = {}
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        neq = _pick(row, "NEQ", "neq")
        if not neq:
            continue
        type_adr = _pick(row, "COD_TYPE_ADR", "TYPE_ADRESSE", "type")
        # On prend toutes les adresses, mais on écrase si on trouve
        # plus tard un type "DOMICILE" ou "SIEGE".
        adresse = _pick(
            row, "ADR_LIGN1_ADR", "ADRESSE_LIGNE1", "adresse"
        )
        ville = _pick(row, "NOM_VILLE", "VILLE", "ville")
        code_postal = _pick(row, "COD_POSTAL", "CODE_POSTAL", "code_postal")

        existing = out.get(neq)
        # Priorité : DOMICILE > SIEGE > tout autre
        new_priority = 0
        if "DOMI" in type_adr.upper():
            new_priority = 2
        elif "SIEGE" in type_adr.upper() or "SIÈGE" in type_adr.upper():
            new_priority = 1

        if existing and existing.get("_priority", 0) >= new_priority:
            continue
        out[neq] = {
            "adresse": adresse or None,
            "ville": ville or None,
            "code_postal": code_postal or None,
            "_priority": new_priority,
        }
    # Nettoie les marqueurs de priorité
    for v in out.values():
        v.pop("_priority", None)
    return out


async def _bulk_upsert(
    db: AsyncSession, batch: Iterable[Dict[str, Any]]
) -> int:
    rows: List[Dict[str, Any]] = list(batch)
    if not rows:
        return 0
    stmt = pg_insert(ReqCompany).values(rows)
    update_cols = {
        c.name: getattr(stmt.excluded, c.name)
        for c in ReqCompany.__table__.columns
        if c.name not in ("neq", "imported_at")
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["neq"], set_=update_cols
    )
    await db.execute(stmt)
    return len(rows)


async def ingest_zip(
    db: AsyncSession,
    zip_bytes: bytes,
    *,
    batch_size: int = 2000,
    max_rows: Optional[int] = None,
) -> Dict[str, int]:
    """Ingère un ZIP REQ téléchargé manuellement.

    Le ZIP doit contenir au moins `entreprise.csv`. Si `adresse.csv`
    est présent, on enrichit chaque entreprise avec son adresse de
    domicile/siège.

    Idempotent : ON CONFLICT (neq) → UPDATE.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        log.info("REQ ZIP contient %d fichiers : %s", len(names), names[:10])

        # Adresses (optionnel)
        adresses: Dict[str, Dict[str, str]] = {}
        for cand in ADRESSE_CSV_NAMES:
            if cand in names:
                with zf.open(cand) as fh:
                    text = fh.read().decode("utf-8", errors="replace")
                adresses = _parse_adresses(text)
                log.info("REQ : %d adresses parsées", len(adresses))
                break

        # Entreprises (obligatoire)
        ent_name: Optional[str] = None
        for cand in ENTREPRISE_CSV_NAMES:
            if cand in names:
                ent_name = cand
                break
        if ent_name is None:
            raise ValueError(
                "Aucun fichier entreprise.csv trouvé dans le ZIP REQ. "
                f"Contenu : {names[:20]}"
            )

        processed = 0
        upserted = 0
        batch: List[Dict[str, Any]] = []
        with zf.open(ent_name) as fh:
            text_stream = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
            reader = csv.DictReader(text_stream)
            for row in reader:
                parsed = _entreprise_row_to_dict(row, adresses)
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
        "REQ ingest: processed=%d upserted=%d", processed, upserted
    )
    return {"rows_processed": processed, "rows_upserted": upserted}
