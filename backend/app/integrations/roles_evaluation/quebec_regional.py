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
import os
import tempfile
import zipfile
from typing import Dict, Iterable, List, Optional, Set, Tuple


# Aliases de noms de colonnes — les CSV des rôles QC varient :
# - MAMH provincial : MATRICULE83, NOM_RUE, MUNICIPALITE...
# - Certaines villes : MAT_LOG, NOMMUN, MUN, NM_MUN, etc.
# - Format MAMH RL-codes (Manuel d'évaluation foncière) :
#   RL0301A=matricule, RL0302A=civique, RL0304A=rue...
_COL_ALIASES: Dict[str, Tuple[str, ...]] = {
    "matricule": (
        "MATRICULE83", "MATRICULE", "MAT_LOG", "NOMAT",
        "MAT_BATIMENT", "MAT", "ID_UEV", "RL0301A",
    ),
    "civique_debut": (
        "CIVIQUE_DEBUT", "CIV_DEB", "NO_CIV", "NO_CIVIQUE",
        "RL0302A",
    ),
    "civique_fin": (
        "CIVIQUE_FIN", "CIV_FIN", "RL0303A",
    ),
    "nom_rue": (
        "NOM_RUE", "RUE", "ODONYME", "GENERIQUE", "RL0304A",
    ),
    "suite_debut": (
        "SUITE_DEBUT", "APP_DEB", "SUITE", "APPARTEMENT", "RL0305A",
    ),
    "municipalite": (
        "MUNICIPALITE", "MUN", "NOMMUN", "NOM_MUN", "NM_MUN",
        "LIB_MUN", "MUN_LIB", "MUNI_NOM", "MUNICIPALITE_LOC",
        "MUN_NAME",
    ),
    "nombre_logement": (
        "NOMBRE_LOGEMENT", "NB_LOGEMENT", "NB_LOG", "NBLOGEMENT",
        "RL0501A",
    ),
    "annee_construction": (
        "ANNEE_CONSTRUCTION", "ANNEE_CONST", "ANNEE", "ANNEE_BAT",
        "RL0402A",
    ),
    "code_utilisation": (
        "CODE_UTILISATION", "USAGE", "CODE_USAGE", "USAGE_CODE",
        "RL0506A",
    ),
    "libelle_utilisation": (
        "LIBELLE_UTILISATION", "LIB_USAGE", "USAGE_LIB",
        "DESC_USAGE", "USAGE_DESC",
    ),
    "categorie_uef": (
        "CATEGORIE_UEF", "CAT_UEV", "CATEGORIE",
    ),
    "superficie_terrain": (
        "SUPERFICIE_TERRAIN", "SUP_TERRAIN", "SUPERF_TER",
        "RL0601A",
    ),
    "superficie_batiment": (
        "SUPERFICIE_BATIMENT", "SUP_BATIMENT", "SUPERF_BAT",
        "RL0602A",
    ),
}


def _detect_encoding_and_delim(path: str) -> Tuple[str, str, List[str]]:
    """Détecte encodage + délimiteur + headers d'un CSV.

    Retourne (encoding, delimiter, headers).
    Essaie utf-8 → cp1252 → latin-1 (les exports QC sont souvent
    en cp1252). Délimiteur via comptage sur la 1ère ligne.
    """
    sample_text = ""
    encoding_used = "utf-8"
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc, newline="") as fh:
                sample_text = fh.read(8192)
            encoding_used = enc
            if sample_text:
                break
        except UnicodeDecodeError:
            continue

    first_line = sample_text.split("\n", 1)[0] if sample_text else ""
    counts = {
        ",": first_line.count(","),
        ";": first_line.count(";"),
        "\t": first_line.count("\t"),
        "|": first_line.count("|"),
    }
    delim, top_count = max(counts.items(), key=lambda kv: kv[1])
    if top_count == 0:
        delim = ","

    headers: List[str] = []
    if first_line:
        try:
            headers = next(
                csv.reader(io.StringIO(first_line), delimiter=delim)
            )
        except StopIteration:
            headers = []
    return encoding_used, delim, headers


def _build_field_map(headers: List[str]) -> Dict[str, str]:
    """Pour chaque champ canonique (matricule, municipalite…), trouve
    le 1er header qui matche un alias. Retourne {canonique: header_réel}.
    Si aucun alias ne matche, le canonique est absent du dict."""
    headers_upper = {h.strip().upper(): h for h in headers}
    out: Dict[str, str] = {}
    for canonical, aliases in _COL_ALIASES.items():
        for alias in aliases:
            if alias in headers_upper:
                out[canonical] = headers_upper[alias]
                break
    return out

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


def _row_to_dict(
    row: Dict[str, str], region: str, fmap: Dict[str, str]
) -> Optional[Dict]:
    """Construit un dict d'unité depuis une ligne CSV en utilisant le
    field map détecté. Retourne None si la ligne n'a pas de matricule."""
    def _g(canonical: str) -> str:
        col = fmap.get(canonical)
        if not col:
            return ""
        return (row.get(col) or "").strip()

    matricule = _g("matricule")
    if not matricule:
        return None
    return {
        "matricule": matricule,
        "civique_debut": _g("civique_debut") or None,
        "civique_fin": _g("civique_fin") or None,
        "nom_rue": _g("nom_rue") or None,
        "suite_debut": _g("suite_debut") or None,
        "municipalite": _g("municipalite") or None,
        "nombre_logement": _parse_int(_g("nombre_logement")),
        "annee_construction": _parse_int(_g("annee_construction")),
        "code_utilisation": _g("code_utilisation") or None,
        "libelle_utilisation": _g("libelle_utilisation") or None,
        "categorie_uef": _g("categorie_uef") or None,
        "superficie_terrain": _parse_float(_g("superficie_terrain")),
        "superficie_batiment": _parse_float(_g("superficie_batiment")),
        "region": region,
    }


async def _bulk_upsert(
    db: AsyncSession, batch: List[Dict]
) -> int:
    """Upsert ON CONFLICT (matricule). Retourne le nb de lignes.

    Dédoublonne le batch sur `matricule` (last-write-wins) avant l'INSERT
    pour éviter CardinalityViolationError de Postgres : ON CONFLICT
    DO UPDATE refuse qu'un même matricule apparaisse 2× dans le même
    INSERT (ça arrive quand un XML MAMH contient plusieurs UEV avec
    le même matricule, ou quand une unité chevauche plusieurs fichiers).
    """
    if not batch:
        return 0
    by_mat: Dict[str, Dict] = {}
    for row in batch:
        mat = row.get("matricule")
        if mat:
            by_mat[mat] = row  # last wins
    deduped = list(by_mat.values())
    if not deduped:
        return 0
    stmt = pg_insert(MontrealPropertyUnit).values(deduped)
    update_cols = {
        c.name: stmt.excluded[c.name]
        for c in MontrealPropertyUnit.__table__.columns
        if c.name not in ("matricule",)
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["matricule"], set_=update_cols
    )
    await db.execute(stmt)
    return len(deduped)


async def _ingest_one_xml(
    db: AsyncSession,
    xml_path: str,
    *,
    region: str,
    match_set: Set[str],
    batch_size: int,
    max_rows: Optional[int],
    seen_so_far: int,
    kept_so_far: int,
) -> Tuple[int, int]:
    """Ingère un XML format MAMH (rôle d'évaluation foncière du Québec).

    Le schéma utilise des balises avec codes du Manuel d'évaluation
    foncière (RL0301A=matricule, RL0506A=usage, etc.). On parcourt en
    streaming via iterparse() pour gérer les gros fichiers (~100 Mo).

    Le code municipalité MAMH est extrait du nom de fichier
    (RL{code5}_AAAA.xml ou RLNR{code3}_AAAA.xml) — on remappe vers
    le nom via la table mam_code_to_name (best-effort).
    """
    import xml.etree.ElementTree as ET
    from app.integrations.roles_evaluation.mamh_codes import (
        code_to_name,
        code_from_filename,
    )

    municipalite_from_filename = code_to_name(
        code_from_filename(os.path.basename(xml_path))
    )

    # Tags candidates pour la balise "unité d'évaluation"
    UNIT_BOUNDARY_TAGS = {
        "RLUEx", "RLUEv", "RLUEV", "UEV", "UniteEvaluation",
        "RLUEvale", "RLUE", "Unite",
    }

    seen_new = 0
    kept_new = 0
    batch: List[Dict] = []

    # Stack pour suivre la profondeur. On accumule les RLxxxxA dans
    # le current_unit dict et on flush au end-tag de boundary.
    current_unit: Dict[str, str] = {}
    current_depth = 0
    boundary_depth: Optional[int] = None

    # Si on n'a pas trouvé de boundary tag, fallback : utiliser tous
    # les éléments dont les enfants directs contiennent un RL0301A.

    try:
        for event, elem in ET.iterparse(xml_path, events=("start", "end")):
            # Strip namespace si présent
            tag = elem.tag.split("}", 1)[-1] if "}" in elem.tag else elem.tag

            if event == "start":
                current_depth += 1
                if tag in UNIT_BOUNDARY_TAGS and boundary_depth is None:
                    boundary_depth = current_depth
                    current_unit = {}
            elif event == "end":
                # Si c'est un code RL et on est dans une unité, accumule
                if (
                    boundary_depth is not None
                    and current_depth > boundary_depth
                    and tag.startswith("RL")
                    and elem.text
                ):
                    current_unit[tag.upper()] = elem.text.strip()

                if tag in UNIT_BOUNDARY_TAGS and current_depth == boundary_depth:
                    # Flush l'unité accumulée
                    seen_new += 1
                    if (
                        max_rows is not None
                        and (seen_so_far + seen_new) > max_rows
                    ):
                        elem.clear()
                        break

                    if current_unit:
                        # Build le row dict avec _row_to_dict via fmap
                        # construit depuis les codes RL trouvés
                        fmap = _build_field_map(list(current_unit.keys()))
                        row = _row_to_dict(current_unit, region, fmap)
                        if row is not None:
                            # Si pas de municipalité dans le XML, prendre
                            # celle déduite du nom de fichier
                            if not row.get("municipalite") and municipalite_from_filename:
                                row["municipalite"] = municipalite_from_filename
                            mun_norm = _normalize_city(row.get("municipalite") or "")
                            if not match_set or mun_norm in match_set:
                                batch.append(row)
                                kept_new += 1
                                if len(batch) >= batch_size:
                                    await _bulk_upsert(db, batch)
                                    batch.clear()
                    current_unit = {}
                    boundary_depth = None
                    elem.clear()
                else:
                    # Libère la mémoire des éléments terminaux non-boundary
                    if current_depth > (boundary_depth or 0):
                        pass  # on garde tant qu'on n'a pas flushé l'unité
                    else:
                        elem.clear()
                current_depth -= 1

                if seen_new % 50_000 == 0 and seen_new > 0:
                    log.info(
                        "  XML %s : %d unités parcourues, %d gardées",
                        os.path.basename(xml_path),
                        seen_so_far + seen_new,
                        kept_so_far + kept_new,
                    )
    except ET.ParseError as exc:
        log.warning(
            "XML parse error in %s: %s — file skipped",
            os.path.basename(xml_path),
            exc,
        )
        return seen_new, kept_new

    if batch:
        await _bulk_upsert(db, batch)
    return seen_new, kept_new


async def _ingest_one_csv(
    db: AsyncSession,
    csv_path: str,
    *,
    region: str,
    match_set: Set[str],
    batch_size: int,
    max_rows: Optional[int],
    seen_so_far: int,
    kept_so_far: int,
) -> tuple[int, int]:
    """Ingère un seul CSV et retourne (seen_new, kept_new).
    Stream-parse, RAM bornée. Auto-détecte encodage + délimiteur +
    aliases de colonnes."""
    seen_new = 0
    kept_new = 0
    batch: List[Dict] = []

    encoding, delim, headers = _detect_encoding_and_delim(csv_path)
    fmap = _build_field_map(headers)
    log.info(
        "  CSV %s : encoding=%s, delim=%r, headers=%d, mappés=%s",
        os.path.basename(csv_path),
        encoding,
        delim,
        len(headers),
        sorted(fmap.keys()),
    )
    if "matricule" not in fmap:
        log.warning(
            "    ⚠ Pas de colonne matricule trouvée — fichier ignoré. "
            "Colonnes vues : %s",
            headers[:20],
        )
        return 0, 0

    municipalite_col = fmap.get("municipalite")
    with open(csv_path, "r", encoding=encoding, errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delim)
        for raw_row in reader:
            seen_new += 1
            if max_rows is not None and (seen_so_far + seen_new) > max_rows:
                break
            if match_set and municipalite_col:
                mun = _normalize_city(raw_row.get(municipalite_col) or "")
                if mun not in match_set:
                    continue
            row = _row_to_dict(raw_row, region, fmap)
            if row is None:
                continue
            batch.append(row)
            kept_new += 1
            if len(batch) >= batch_size:
                await _bulk_upsert(db, batch)
                batch.clear()
            total = seen_so_far + seen_new
            if total % 100_000 == 0:
                log.info(
                    "  %d lignes parcourues, %d gardées",
                    total,
                    kept_so_far + kept_new,
                )
    if batch:
        await _bulk_upsert(db, batch)
    return seen_new, kept_new


async def ingest_provincial_csv(
    db: AsyncSession,
    csv_path: str,
    *,
    region: str,
    cities: Optional[Iterable[str]] = None,
    batch_size: int = 2000,
    max_rows: Optional[int] = None,
) -> dict:
    """Ingère le rôle provincial filtré par région + liste de villes.

    Accepte un CSV brut OU un ZIP qui contient un ou plusieurs CSV
    (le format publié par Données Québec : Roles_Donnees_Ouvertes_*.zip
    contient typiquement un fichier par groupe de municipalités).

    Args:
        csv_path : chemin local vers le CSV ou le ZIP.
        region : « rive-sud », « laval », « rive-nord » ou autre.
        cities : si fourni, on garde uniquement les unités dont
                 MUNICIPALITE matche (insensible accents/casse).
                 Si None, on prend la liste pré-définie de la région.
        batch_size : nb de lignes par bulk insert.
        max_rows : limite pour tests (None = tout).
    """
    cities_used = (
        list(cities)
        if cities
        else list(ALL_REGIONS.get(region, set()))
    )
    match_set = _build_match_set(cities_used)
    log.info(
        "Ingest provincial : region=%s, %d villes, source=%s",
        region,
        len(match_set),
        os.path.basename(csv_path),
    )

    total_seen = 0
    total_kept = 0
    diagnostics: List[dict] = []

    is_zip = zipfile.is_zipfile(csv_path)
    if is_zip:
        with tempfile.TemporaryDirectory(
            prefix="role_unzip_"
        ) as tmpdir, zipfile.ZipFile(csv_path) as zf:
            all_members = zf.namelist()
            csv_members = [
                n for n in all_members if n.lower().endswith(".csv")
            ]
            xml_members = [
                n for n in all_members if n.lower().endswith(".xml")
            ]
            log.info(
                "ZIP détecté : %d entrées (%d CSV, %d XML). Tous : %s",
                len(all_members),
                len(csv_members),
                len(xml_members),
                all_members[:10],
            )
            if not csv_members and not xml_members:
                diagnostics.append(
                    {
                        "file": "(zip)",
                        "error": (
                            f"Aucun .csv ou .xml dans le ZIP. Entrées : "
                            f"{', '.join(all_members[:10])}"
                        ),
                    }
                )
            # CSV first (Ville-de-MTL style)
            for name in csv_members:
                zf.extract(name, tmpdir)
                local_path = os.path.join(tmpdir, name)
                enc, delim, headers = _detect_encoding_and_delim(local_path)
                fmap = _build_field_map(headers)
                diagnostics.append(
                    {
                        "file": os.path.basename(name),
                        "encoding": enc,
                        "delimiter": repr(delim),
                        "headers_seen": headers[:25],
                        "columns_mapped": sorted(fmap.keys()),
                        "has_matricule": "matricule" in fmap,
                    }
                )
                seen_new, kept_new = await _ingest_one_csv(
                    db,
                    local_path,
                    region=region,
                    match_set=match_set,
                    batch_size=batch_size,
                    max_rows=max_rows,
                    seen_so_far=total_seen,
                    kept_so_far=total_kept,
                )
                total_seen += seen_new
                total_kept += kept_new
                if max_rows is not None and total_seen >= max_rows:
                    break
            # XML (format MAMH RL-codes)
            for name in xml_members:
                if max_rows is not None and total_seen >= max_rows:
                    break
                zf.extract(name, tmpdir)
                local_path = os.path.join(tmpdir, name)
                from app.integrations.roles_evaluation.mamh_codes import (
                    code_from_filename,
                    code_to_name,
                )
                base = os.path.basename(name)
                code = code_from_filename(base)
                mun = code_to_name(code)
                # Skip les fichiers de l'île de Montréal (codes MAMH 66xxx)
                # car le format de matricule MAMH (18 chars) diffère du
                # feed Ville de Montréal (10-12 chars) — sinon on aurait
                # 2 entrées DB pour la même propriété physique. MTL est
                # ingéré séparément via /admin/data/mtl-roles/import.
                if code and code.startswith("66"):
                    diagnostics.append(
                        {
                            "file": base,
                            "encoding": "skipped",
                            "delimiter": "(MTL via feed dédié)",
                            "headers_seen": [
                                f"code_mamh={code}",
                                f"municipalite={mun or 'Île de MTL'}",
                                "skip_reason=use VdM feed for MTL",
                            ],
                            "columns_mapped": [],
                            "has_matricule": False,
                        }
                    )
                    log.info(
                        "  Skip %s (île de MTL — utiliser le feed VdM dédié)",
                        base,
                    )
                    continue
                diagnostics.append(
                    {
                        "file": base,
                        "encoding": "xml",
                        "delimiter": "(MAMH XML)",
                        "headers_seen": [
                            f"code_mamh={code or '?'}",
                            f"municipalite={mun or '(non mappée)'}",
                        ],
                        "columns_mapped": ["xml_mamh"],
                        "has_matricule": True,
                    }
                )
                seen_new, kept_new = await _ingest_one_xml(
                    db,
                    local_path,
                    region=region,
                    match_set=match_set,
                    batch_size=batch_size,
                    max_rows=max_rows,
                    seen_so_far=total_seen,
                    kept_so_far=total_kept,
                )
                total_seen += seen_new
                total_kept += kept_new
    else:
        enc, delim, headers = _detect_encoding_and_delim(csv_path)
        fmap = _build_field_map(headers)
        diagnostics.append(
            {
                "file": os.path.basename(csv_path),
                "encoding": enc,
                "delimiter": repr(delim),
                "headers_seen": headers[:25],
                "columns_mapped": sorted(fmap.keys()),
                "has_matricule": "matricule" in fmap,
            }
        )
        seen_new, kept_new = await _ingest_one_csv(
            db,
            csv_path,
            region=region,
            match_set=match_set,
            batch_size=batch_size,
            max_rows=max_rows,
            seen_so_far=0,
            kept_so_far=0,
        )
        total_seen = seen_new
        total_kept = kept_new

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
        "diagnostics": diagnostics,
    }
