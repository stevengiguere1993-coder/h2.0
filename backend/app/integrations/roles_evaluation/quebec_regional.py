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
    + retry sur drop connexion (Render free coupe les conn idles).
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

    import asyncio as _asyncio

    last_err: Optional[Exception] = None
    for attempt in range(6):
        try:
            await db.execute(stmt)
            return len(deduped)
        except Exception as exc:
            msg = str(exc).lower()
            transient = (
                "recovery mode" in msg
                or "not yet accepting" in msg
                or "consistent recovery" in msg
                or "starting up" in msg
                or "shutting down" in msg
                or ("connection" in msg
                    and ("closed" in msg or "does not exist" in msg
                         or "refused" in msg))
                or "ssl connection has been closed" in msg
            )
            if not transient:
                raise
            last_err = exc
            log.warning(
                "Provincial bulk upsert transient error "
                "(attempt %d/6): %s",
                attempt + 1,
                exc,
            )
            try:
                await db.rollback()
            except Exception:
                pass
            await _asyncio.sleep(5 * (attempt + 1))
    if last_err:
        raise last_err
    return 0


def _mamh_xml_unit_to_row(
    unit: Dict[str, str],
    *,
    code_mun: str,
    region: str,
    municipalite_from_filename: Optional[str],
) -> Optional[Dict]:
    """Convertit un dict de codes RL (capturés sous une balise <RLUEx>)
    en row pour `mtl_property_units`. Retourne None si le matricule
    ne peut pas être construit (unité ignorée).

    Le matricule global = `<code_mamh>-<RL0104A>-<RL0104B>-<RL0104C>`
    (jusqu'à 6 segments pour les unités de copropriété/condo).
    Fallback : `<code_mamh>-uev-<RL0103Ax>` si RL0104 absent.
    """
    # 1. Matricule — concaténation du code MAMH + segments RL0104A..F
    segs: List[str] = []
    for letter in "ABCDEFGH":
        v = (unit.get(f"RL0104{letter}") or "").strip()
        if not v:
            break
        segs.append(v)

    if segs:
        matricule = "-".join([code_mun] + segs)
    else:
        uev = (unit.get("RL0103AX") or "").strip()
        if not uev:
            return None
        matricule = f"{code_mun}-uev-{uev}"

    # 2. Adresse — RL0101x : Ax civique, Ex type voie, Fx particule,
    #    Gx nom voie, Hx suite/logement.
    civique = (unit.get("RL0101AX") or "").strip() or None
    type_voie = (unit.get("RL0101EX") or "").strip()
    particule = (unit.get("RL0101FX") or "").strip()
    nom_voie = (unit.get("RL0101GX") or "").strip()
    nom_rue_parts = [p for p in (type_voie, particule, nom_voie) if p]
    nom_rue = " ".join(nom_rue_parts) or None
    suite = (unit.get("RL0101HX") or "").strip() or None

    return {
        "matricule": matricule[:32],  # tronque pour respecter String(32)
        "civique_debut": (civique or None) if civique is None else civique[:16],
        "civique_fin": None,
        "nom_rue": nom_rue[:255] if nom_rue else None,
        "suite_debut": suite[:32] if suite else None,
        "municipalite": municipalite_from_filename,
        "nombre_logement": _parse_int(unit.get("RL0311A") or ""),
        "annee_construction": _parse_int(unit.get("RL0307A") or ""),
        "code_utilisation": (
            (unit.get("RL0105A") or "").strip()[:16] or None
        ),
        "libelle_utilisation": None,
        "categorie_uef": (unit.get("RL0307B") or "").strip()[:64] or None,
        "superficie_terrain": _parse_float(unit.get("RL0301A") or ""),
        "superficie_batiment": _parse_float(unit.get("RL0308A") or ""),
        "region": region,
    }


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
    sample_out: Optional[Dict] = None,
) -> Tuple[int, int]:
    """Ingère un XML format MAMH (rôle d'évaluation foncière du Québec).

    Schéma MAMH 2.9 (RL.xsd). Les balises pertinentes pour notre
    modèle `mtl_property_units` sont :
      - <RLUEx>                    boundary d'une unité d'évaluation
      - <RL0101>/<RL0101x>         adresse
        - <RL0101Ax>               numéro civique
        - <RL0101Ex>               type de voie (CH, RUE, BD…)
        - <RL0101Fx>               particule directionnelle (M, N…)
        - <RL0101Gx>               nom de la voie
        - <RL0101Hx>               numéro de suite/logement (optionnel)
      - <RL0103>/<RL0103x>/<RL0103Ax>  numéro UEV unique (id de la rangée)
      - <RL0104A/B/C[/D/E/F]>      segments du matricule (3 pour simple,
                                    6 pour condo/co-propriété)
      - <RL0105A>                  code utilisation (1000=résidentiel,
                                    9100=vacant, 6000=commercial…)
      - <RL0301A>                  superficie terrain (m²)
      - <RL0307A>                  année de construction
      - <RL0307B>                  type construction (R/E/…)
      - <RL0308A>                  superficie bâtiment (m²)
      - <RL0311A>                  nombre de logements
      - <RL0402A>                  valeur terrain ($)
      - <RL0403A>                  valeur bâtiment ($)
      - <RL0404A>                  valeur immeuble ($)

    Le code MAMH municipalité (5 chiffres) est extrait du nom de fichier
    (RL{code5}_AAAA.xml ou RLNR{code3}_AAAA.xml) et sert à la fois au
    nom de la municipalité (table mam_codes) et au préfixe du matricule
    pour garantir l'unicité globale entre municipalités.
    """
    import xml.etree.ElementTree as ET
    from app.integrations.roles_evaluation.mamh_codes import (
        code_to_name,
        code_from_filename,
    )

    code_mun = code_from_filename(os.path.basename(xml_path)) or "00000"
    municipalite_from_filename = code_to_name(code_mun)

    UNIT_BOUNDARY_TAG = "RLUEx"

    seen_new = 0
    kept_new = 0
    batch: List[Dict] = []

    # On accumule les RL** rencontrés sous la balise <RLUEx> dans
    # current_unit. À la fin du <RLUEx>, on construit la row via
    # _mamh_xml_unit_to_row() et on l'ajoute au batch.
    current_unit: Dict[str, str] = {}
    current_depth = 0
    boundary_depth: Optional[int] = None

    # IMPORTANT : pour les gros XML (Montréal ~1 GB non-compressé), il faut
    # libérer le root du document régulièrement, sinon iterparse accumule
    # tous les <RLUEx> sous le root jusqu'à OOM. Pattern canonique : on
    # récupère le root via next() puis on appelle root.clear() après
    # chaque unité flushée.
    root = None
    try:
        context = ET.iterparse(xml_path, events=("start", "end"))
        try:
            _, root = next(context)
        except StopIteration:
            return seen_new, kept_new
        # Le root vient juste de subir un événement 'start' → depth=1
        current_depth = 1
        for event, elem in context:
            # Strip namespace si présent
            tag = elem.tag.split("}", 1)[-1] if "}" in elem.tag else elem.tag

            if event == "start":
                current_depth += 1
                if tag == UNIT_BOUNDARY_TAG and boundary_depth is None:
                    boundary_depth = current_depth
                    current_unit = {}
            elif event == "end":
                # Si c'est un code RL et on est dans une unité, accumule.
                # Note : avec le schéma 2.9, certains codes apparaissent
                # plusieurs fois dans une même unité (ex. <RL0504x> répété
                # pour chaque catégorie d'évaluation). On garde la 1ère
                # occurrence (souvent la plus pertinente — cat « I/T/B »
                # sur la valeur de l'immeuble).
                if (
                    boundary_depth is not None
                    and current_depth > boundary_depth
                    and tag.startswith("RL")
                    and elem.text
                ):
                    key = tag.upper()
                    if key not in current_unit:
                        text = elem.text.strip()
                        if text:
                            current_unit[key] = text

                if tag == UNIT_BOUNDARY_TAG and current_depth == boundary_depth:
                    # Flush l'unité accumulée
                    seen_new += 1
                    if (
                        max_rows is not None
                        and (seen_so_far + seen_new) > max_rows
                    ):
                        elem.clear()
                        break

                    if current_unit:
                        row = _mamh_xml_unit_to_row(
                            current_unit,
                            code_mun=code_mun,
                            region=region,
                            municipalite_from_filename=(
                                municipalite_from_filename
                            ),
                        )
                        if row is not None:
                            mun_norm = _normalize_city(row.get("municipalite") or "")
                            if not match_set or mun_norm in match_set:
                                batch.append(row)
                                kept_new += 1
                                if (
                                    sample_out is not None
                                    and "first_matricule" not in sample_out
                                ):
                                    sample_out["first_matricule"] = row.get(
                                        "matricule"
                                    )
                                    sample_out["first_municipalite"] = row.get(
                                        "municipalite"
                                    )
                                if len(batch) >= batch_size:
                                    await _bulk_upsert(db, batch)
                                    batch.clear()
                    current_unit = {}
                    boundary_depth = None
                    elem.clear()
                    # Libère les références accumulées sous le root après
                    # CHAQUE unité flushée — sinon le root garde tous les
                    # <RLUEx> en mémoire et OOM sur les gros XML.
                    if root is not None:
                        root.clear()
                else:
                    # Libère la mémoire des éléments terminaux non-boundary
                    if current_depth > (boundary_depth or 0):
                        pass  # on garde tant qu'on n'a pas flushé l'unité
                    else:
                        elem.clear()
                current_depth -= 1

                if seen_new % 5_000 == 0 and seen_new > 0:
                    log.info(
                        "  XML %s : %d unités parcourues, %d gardées",
                        os.path.basename(xml_path),
                        seen_so_far + seen_new,
                        kept_so_far + kept_new,
                    )
                    try:
                        from app.integrations.roles_evaluation._progress import (
                            update_progress,
                        )
                        update_progress(
                            current_file=os.path.basename(xml_path),
                            rows_so_far=seen_so_far + seen_new,
                        )
                    except Exception:
                        pass
    except ET.ParseError as exc:
        log.warning(
            "XML parse error in %s: %s — file skipped",
            os.path.basename(xml_path),
            exc,
        )
        if batch:
            try:
                await _bulk_upsert(db, batch)
            except Exception:
                pass
        return seen_new, kept_new
    except MemoryError as exc:
        # Si on OOM malgré root.clear() (XML pathologique), on log et on
        # retourne ce qu'on a déjà accumulé pour ne pas tuer le worker.
        log.exception(
            "MemoryError on %s after %d units: %s",
            os.path.basename(xml_path),
            seen_new,
            exc,
        )
        if batch:
            try:
                await _bulk_upsert(db, batch)
            except Exception:
                pass
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
            if total > 0 and total % 5_000 == 0:
                log.info(
                    "  %d lignes parcourues, %d gardées",
                    total,
                    kept_so_far + kept_new,
                )
                try:
                    from app.integrations.roles_evaluation._progress import (
                        update_progress,
                    )
                    update_progress(
                        current_file=os.path.basename(csv_path),
                        rows_so_far=total,
                    )
                except Exception:
                    pass
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
    max_km_from_mtl: Optional[float] = 50.0,
    max_xml_uncompressed_mb: Optional[float] = None,
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
        max_km_from_mtl : seuil maximum en km depuis le centre-ville
                 de Montréal pour conserver une unité. Default 50 km
                 — restreint le volume au périmètre métropolitain
                 pour tenir dans Postgres free 1 Go (~500 K-1 M
                 unités au lieu de ~5 M nationales).
                 None = pas de filtre distance (tout le QC).
        max_xml_uncompressed_mb : si défini, skip les XML dont la
                 taille décompressée dépasse ce seuil. Sert sur Render
                 Free (512 MB RAM) où Montréal/Laval (~600-1000 MB de
                 XML) déclenchent un OOM-kill du worker. Sur Hetzner
                 ou un Render plan payant, laisser None (pas de skip).
    """
    cities_used = (
        list(cities)
        if cities
        else list(ALL_REGIONS.get(region, set()))
    )
    match_set = _build_match_set(cities_used)

    # Filtre par distance MTL : on construit un set des noms et codes
    # MAMH des municipalités à ≤ max_km_from_mtl. Sert au double niveau :
    # - skip total des fichiers XML dont le code MAMH est hors-périmètre
    # - filtre ligne par ligne pour CSV via match sur le nom municipalité
    distance_set: Optional[Set[str]] = None
    distance_codes: Optional[Set[str]] = None
    if max_km_from_mtl is not None:
        from app.integrations.roles_evaluation.quebec_distances import (
            _DIST_KM_RAW,
        )
        from app.integrations.roles_evaluation.mamh_codes import (
            _CODE_TO_NAME,
        )

        # Noms normalisés des villes ≤ max_km
        in_radius_originals = {
            k for k, dist in _DIST_KM_RAW.items() if dist <= max_km_from_mtl
        }
        distance_set = {_normalize_city(k) for k in in_radius_originals}

        # Codes MAMH dont la municipalité est ≤ max_km
        distance_codes = {
            code
            for code, name in _CODE_TO_NAME.items()
            if _normalize_city(name) in distance_set
        }
        log.info(
            "Filtre distance MTL ≤ %.0f km : %d municipalités, %d codes MAMH",
            max_km_from_mtl,
            len(distance_set),
            len(distance_codes),
        )
        # Si pas de cities explicites, on utilise le distance_set comme
        # filter pour les CSV (filtre ligne par ligne sur la municipalité)
        if not match_set and distance_set:
            match_set = set(distance_set)

    log.info(
        "Ingest provincial : region=%s, %d villes filter, source=%s, max_km=%s",
        region,
        len(match_set),
        os.path.basename(csv_path),
        max_km_from_mtl,
    )

    total_seen = 0
    total_kept = 0
    diagnostics: List[dict] = []

    is_zip = zipfile.is_zipfile(csv_path)
    if is_zip:
        with tempfile.TemporaryDirectory(
            prefix="role_unzip_"
        ) as tmpdir, zipfile.ZipFile(csv_path) as zf:
            # On utilise infolist() pour avoir la taille décompressée
            # de chaque entrée — sert à trier par taille croissante
            # (les petites villes complètent en premier, maximisant
            # ce qui est ingéré avant un éventuel OOM-kill sur Render
            # Free) et à skip les fichiers > seuil si configuré.
            infos = zf.infolist()
            csv_infos = [
                i for i in infos if i.filename.lower().endswith(".csv")
            ]
            xml_infos = [
                i for i in infos if i.filename.lower().endswith(".xml")
            ]
            xml_infos.sort(key=lambda i: i.file_size)
            csv_members = [i.filename for i in csv_infos]
            xml_members = [i.filename for i in xml_infos]
            xml_size_by_name = {i.filename: i.file_size for i in xml_infos}
            log.info(
                "ZIP détecté : %d entrées (%d CSV, %d XML, "
                "tri XML par taille croissante). Tous : %s",
                len(infos),
                len(csv_members),
                len(xml_members),
                [i.filename for i in infos[:10]],
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
                from app.integrations.roles_evaluation.mamh_codes import (
                    code_from_filename,
                    code_to_name,
                )
                base = os.path.basename(name)
                code = code_from_filename(base)
                mun = code_to_name(code)

                # Filtre distance : skip le fichier entier si son code
                # MAMH n'est pas dans le périmètre. Évite d'extraire
                # +parser des XML inutiles (gain RAM/CPU/disk).
                if (
                    distance_codes is not None
                    and (not code or code not in distance_codes)
                ):
                    diagnostics.append(
                        {
                            "file": base,
                            "encoding": "skipped",
                            "delimiter": (
                                f"hors-périmètre (>{max_km_from_mtl} km MTL)"
                            ),
                            "headers_seen": [
                                f"code_mamh={code or '?'}",
                                f"municipalite={mun or '(non mappée)'}",
                            ],
                            "columns_mapped": [],
                            "has_matricule": False,
                        }
                    )
                    continue

                # Skip par taille (Render Free 512 MB) : Montréal RL66023
                # fait ~1 GB décompressé et OOM-kill le worker. On le
                # laisse passer sur Hetzner (max_xml_uncompressed_mb=None).
                xml_size = xml_size_by_name.get(name, 0)
                if (
                    max_xml_uncompressed_mb is not None
                    and xml_size > max_xml_uncompressed_mb * 1024 * 1024
                ):
                    size_mb = xml_size / (1024 * 1024)
                    log.warning(
                        "Skip %s (%.0f MB > %.0f MB seuil) — utiliser "
                        "le script Hetzner import_provincial_xml_zip.py",
                        base,
                        size_mb,
                        max_xml_uncompressed_mb,
                    )
                    diagnostics.append(
                        {
                            "file": base,
                            "encoding": "skipped",
                            "delimiter": (
                                f"trop volumineux ({size_mb:.0f} MB > "
                                f"{max_xml_uncompressed_mb:.0f} MB seuil "
                                f"Render). Utiliser Hetzner CLI."
                            ),
                            "headers_seen": [
                                f"code_mamh={code or '?'}",
                                f"municipalite={mun or '(non mappée)'}",
                                f"size_mb={size_mb:.0f}",
                            ],
                            "columns_mapped": [],
                            "has_matricule": False,
                        }
                    )
                    continue

                zf.extract(name, tmpdir)
                local_path = os.path.join(tmpdir, name)
                # Try/except par fichier : si un XML pathologique crash
                # (parse error, OOM, etc.), on log et on continue avec
                # le suivant — sinon l'utilisateur perd tout l'import.
                try:
                    sample_out: Dict = {}
                    seen_new, kept_new = await _ingest_one_xml(
                        db,
                        local_path,
                        region=region,
                        match_set=match_set,
                        batch_size=batch_size,
                        max_rows=max_rows,
                        seen_so_far=total_seen,
                        kept_so_far=total_kept,
                        sample_out=sample_out,
                    )
                    total_seen += seen_new
                    total_kept += kept_new
                    diagnostics.append(
                        {
                            "file": base,
                            "encoding": "xml",
                            "delimiter": "(MAMH XML)",
                            "headers_seen": [
                                f"code_mamh={code or '?'}",
                                f"municipalite={mun or '(non mappée)'}",
                                f"units_seen={seen_new}",
                                f"units_kept={kept_new}",
                                f"sample_matricule={sample_out.get('first_matricule', '(none)')}",
                            ],
                            "columns_mapped": ["xml_mamh"],
                            "has_matricule": True,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    log.exception(
                        "Échec ingestion XML %s : %s", base, exc
                    )
                    diagnostics.append(
                        {
                            "file": base,
                            "error": (
                                f"{type(exc).__name__}: {str(exc)[:200]}"
                            ),
                        }
                    )
                # Supprime le fichier extrait pour libérer du disque tout
                # de suite — un ZIP de tout le Québec décompressé tient
                # ~5 GB sinon.
                try:
                    os.unlink(local_path)
                except OSError:
                    pass
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
