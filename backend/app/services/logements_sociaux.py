"""Logements sociaux et communautaires de l'île de Montréal (Phil
2026-09-28 : « faire un filtre pour exclure les logements sociaux »).

Deux signaux, cumulés dans ``mtl_property_units.logement_social`` (NULL =
pas connu comme social) :

1. le jeu de données ouvert de la Ville « Logements sociaux et
   communautaires » (HLM, OMHM, SHDM, coopératives, OBNL) : ~2 800
   projets avec le nom de rue (sans numéro civique), l'arrondissement ou
   la ville liée et le nombre de logements. Une unité du rôle est marquée
   quand (arrondissement/ville, rue, nombre de logements) coïncident ET
   qu'UN SEUL immeuble du rôle correspond (plusieurs immeubles de même
   taille sur la rue = ambigu, non marqué) — pour ne jamais exclure un
   immeuble privé ;
2. le nom du propriétaire collecté sur EvalWeb (Office d'habitation, SHDM,
   SHQ, coopérative d'habitation, habitations communautaires…), appliqué
   au fil des collectes ;
3. le code d'utilisation du rôle lui-même : 1010 « Logements sociaux et
   abordables » (Phil 2026-09-29 : un HLM de l'OMHM restait dans la liste
   jusqu'à la collecte de son propriétaire).
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from pathlib import Path
import json
import logging
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx
from sqlalchemy import bindparam, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.montreal_property_unit import MontrealPropertyUnit as U

log = logging.getLogger(__name__)

#: Code d'utilisation du rôle « Logements sociaux et abordables ».
CODE_UTILISATION_SOCIAL = "1010"

#: Fin du libellé des marquages déduits du NOM du propriétaire collecté
#: (« Coop · propriétaire ») — ceux-là survivent au recalcul du fichier.
SUFFIXE_PROPRIETAIRE = "· propriétaire"

#: CSV « Logements sociaux et communautaires » (donnees.montreal.ca).
LOGEMENTS_SOCIAUX_CSV_URL = (
    "https://donnees.montreal.ca/dataset/"
    "d26fad0f-2eae-44d5-88a0-2bc699fd2592/resource/"
    "bb380faa-1ba5-458b-b520-9e2287bcc07f/download/"
    "log_horsmarche_donneesouvertes_20241231.csv"
)

#: Copie du même fichier (édition 2024-12-31, licence ouverte de la Ville)
#: utilisée si le téléchargement échoue — le 2026-09-29, donnees.montreal.ca
#: a répondu 403 au serveur et aucun logement social n'a été marqué.
_COPIE_EMBARQUEE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "logements_sociaux_montreal_20241231.csv"
)

_TYPES_VOIE = frozenset({
    "rue", "r", "avenue", "av", "ave", "boulevard", "boul", "bd", "blvd",
    "chemin", "ch", "place", "pl", "montee", "croissant", "cr", "crois",
    "terrasse", "tsse", "allee", "carre", "square", "sq", "impasse",
    "promenade", "prom", "voie", "route", "rte", "rang", "autoroute", "aut",
    "cours", "cercle", "circle", "cote",
})
_PARTICULES = frozenset({"de", "du", "des", "d", "la", "le", "les", "l", "the"})
_DIRECTIONS = frozenset({
    "est", "ouest", "nord", "sud", "e", "o", "n", "s", "east", "west",
})


def _sans_accents(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _tokens(s: str) -> List[str]:
    s = _sans_accents(s or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)  # « (MTL) », « (SLR+MTL) »
    s = re.sub(r"[-–—'’.,/]", " ", s)
    return [t for t in s.split() if t]


def normaliser_rue(nom: Optional[str]) -> str:
    """« rue de Louvain Ouest  (MTL) » → « louvain » ; « 20e avenue » →
    « 20e » ; « boulevard Pie-IX » et « Pie IX » → « pie ix »."""
    toks = [t for t in _tokens(nom or "") if t not in _TYPES_VOIE]
    while toks and toks[0] in _PARTICULES:
        toks.pop(0)
    while len(toks) > 1 and toks[-1] in _DIRECTIONS:
        toks.pop()
    return " ".join(toks)


def normaliser_secteur(nom: Optional[str]) -> str:
    """Arrondissement ou ville liée : « Côte-des-Neiges–Notre-Dame-de-Grâce »
    et « Cote des Neiges Notre Dame de Grace » → même clé ; « Côte Saint-Luc »
    = « Côte-Saint-Luc »."""
    return " ".join(_tokens(nom or ""))


_CATEGORIES_PROPRIETAIRE: Tuple[Tuple[str, str], ...] = (
    (r"OFFICE (MUNICIPAL )?D HABITATION", "Office d'habitation"),
    (r"SOCIETE D HABITATION ET DE DEVELOPPEMENT", "SHDM"),
    (r"\bS ?H ?D ?M\b", "SHDM"),
    (r"SOCIETE D HABITATION DU QUEBEC", "SHQ"),
    (
        r"\bCOOP(ERATIVE)?\b.*\bHABITATION|\bHABITATION\b.*\bCOOP(ERATIVE)?\b",
        "Coop",
    ),
    (r"HABITATIONS? COMMUNAUTAIRES?|HABITATIONS? POPULAIRES?", "OBNL"),
    (
        r"\bOBNL\b|\bO ?S ?B ?L\b|ORGANISME SANS BUT LUCRATIF"
        r"|ORGANISATION SANS BUT LUCRATIF",
        "OBNL",
    ),
)


def categorie_proprietaire_social(nom: Optional[str]) -> Optional[str]:
    """« OFFICE MUNICIPAL D'HABITATION DE MONTRÉAL » → « Office
    d'habitation » ; None si le nom n'évoque pas un bailleur social."""
    if not nom:
        return None
    n = " ".join(_tokens(nom)).upper()
    for motif, categorie in _CATEGORIES_PROPRIETAIRE:
        if re.search(motif, n):
            return categorie
    return None


def categorie_depuis_proprietaires(owners: Iterable[Any]) -> Optional[str]:
    """Première catégorie sociale trouvée parmi des propriétaires
    (dicts ``{"name": …}`` du cache EvalWeb)."""
    for o in owners or []:
        nom = o.get("name") if isinstance(o, dict) else getattr(o, "name", None)
        cat = categorie_proprietaire_social(nom)
        if cat:
            return cat
    return None


def libelle_social(categorie: str, precision: str = "") -> str:
    """Valeur stockée (VARCHAR(64)) : « HLM · Saint-Sulpice »,
    « Coop · propriétaire »."""
    texte = f"{categorie} · {precision}" if precision else categorie
    return texte[:64]


def charger_projets(
    texte_csv: str,
) -> Dict[Tuple[str, str, int], Tuple[str, str]]:
    """CSV de la Ville (« ; ») → {(secteur, rue, nb logements): (type, projet)}."""
    rdr = csv.DictReader(io.StringIO(texte_csv), delimiter=";")
    projets: Dict[Tuple[str, str, int], Tuple[str, str]] = {}
    for row in rdr:
        try:
            nlog = int(float((row.get("nlog") or "0").strip() or 0))
        except ValueError:
            continue
        if nlog <= 0:
            continue
        secteur = (row.get("arrond") or "").strip() or (
            row.get("villelie") or ""
        ).strip()
        rue = normaliser_rue(row.get("nomrue"))
        if not secteur or not rue:
            continue
        cle = (normaliser_secteur(secteur), rue, nlog)
        typ = (row.get("type") or "").strip() or "Social"
        projets.setdefault(cle, (typ, (row.get("Projetnom") or "").strip()))
    return projets


def decoder_csv(brut: bytes) -> str:
    try:
        return brut.decode("utf-8-sig")
    except UnicodeDecodeError:
        return brut.decode("cp1252", errors="replace")


async def telecharger_csv(url: str = LOGEMENTS_SOCIAUX_CSV_URL) -> str:
    """Télécharge le fichier de la Ville — avec le même en-tête navigateur
    que l'import du rôle (sans lui, le site répond 403 au serveur)."""
    from app.integrations.roles_evaluation.montreal import USER_AGENT

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=30.0),
        headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"},
    ) as client:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
        return decoder_csv(r.content)


async def charger_texte_csv(
    url: str = LOGEMENTS_SOCIAUX_CSV_URL,
) -> Tuple[str, str]:
    """(texte, source) : le fichier à jour de la Ville, sinon la copie
    embarquée — le marquage ne doit plus échouer sur un 403."""
    try:
        texte = await telecharger_csv(url)
        if "nomrue" in texte[:2000]:
            return texte, "Ville de Montréal (en ligne)"
        log.warning("Fichier des logements sociaux inattendu — copie embarquée utilisée")
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Téléchargement des logements sociaux échoué (%s) — copie embarquée utilisée",
            exc,
        )
    return decoder_csv(_COPIE_EMBARQUEE.read_bytes()), "copie embarquée (2024-12-31)"


async def _ecrire_marquages(db: AsyncSession, marquages: Dict[str, str]) -> int:
    if not marquages:
        return 0
    # Table Core (pas l'entité) : un executemany paramétré par
    # « matricule » — la version ORM exigerait la clé primaire nommée.
    table = U.__table__
    stmt = (
        update(table)
        .where(table.c.matricule == bindparam("m"))
        .values(logement_social=bindparam("l"))
    )
    items = [{"m": m, "l": l} for m, l in marquages.items()]
    for i in range(0, len(items), 500):
        await db.execute(stmt, items[i : i + 500])
    return len(items)


async def marquer_depuis_proprietaires(db: AsyncSession) -> int:
    """Unités dont un propriétaire collecté est un bailleur social."""
    rows = (
        await db.execute(
            select(U.matricule, U.owners_json).where(
                U.logement_social.is_(None),
                U.owners_json.is_not(None),
                U.owners_json.notin_(["", "[]"]),
            )
        )
    ).all()
    marquages: Dict[str, str] = {}
    for mat, owners_json in rows:
        try:
            owners = json.loads(owners_json or "[]")
        except Exception:  # noqa: BLE001
            continue
        cat = categorie_depuis_proprietaires(owners)
        if cat:
            marquages[mat] = libelle_social(cat, "propriétaire")
    return await _ecrire_marquages(db, marquages)


async def marquer_logements_sociaux(
    db: AsyncSession, texte_csv: Optional[str] = None
) -> Dict[str, Any]:
    """Marque les unités du rôle qui correspondent à un projet du jeu de
    données de la Ville, puis celles dont le propriétaire collecté est un
    bailleur social. La partie « fichier » est RECALCULÉE à chaque passage
    (une règle plus stricte retire d'anciens marquages) ; les marquages
    par propriétaire sont gardés. Commit par l'appelant."""
    source = "fourni"
    if texte_csv is None:
        texte_csv, source = await charger_texte_csv()
    projets = charger_projets(texte_csv)
    nlogs = sorted({cle[2] for cle in projets})
    par_type: Dict[str, int] = {}
    table = U.__table__

    # 1. Remise à zéro des marquages « fichier ».
    await db.execute(
        update(table)
        .where(
            table.c.logement_social.is_not(None),
            ~table.c.logement_social.like(f"%{SUFFIXE_PROPRIETAIRE}"),
        )
        .values(logement_social=None)
    )

    # 1 bis. Le rôle le dit lui-même : code d'utilisation 1010.
    res_code = await db.execute(
        update(table)
        .where(
            table.c.code_utilisation == CODE_UTILISATION_SOCIAL,
            table.c.logement_social.is_(None),
        )
        .values(logement_social=libelle_social("Rôle", "logement social et abordable"))
    )
    marquees_code = int(res_code.rowcount or 0) if (res_code.rowcount or 0) > 0 else 0

    # 2. Unités de l'île dont le nombre de logements correspond à un projet
    #    — lues EN FLUX (~500 000 lignes : jamais tout en mémoire sur le
    #    serveur gratuit à 512 Mo).
    par_cle: Dict[Tuple[str, str, int], List[Tuple[str, Optional[str]]]] = (
        defaultdict(list)
    )
    sans_arrondissement = 0
    nb_candidates = 0
    if nlogs:
        flux = await db.stream(
            select(
                U.matricule,
                U.nom_rue,
                U.municipalite,
                U.arrondissement,
                U.nombre_logement,
                U.logement_social,
            )
            .where(
                U.region == "mtl-island",
                U.nombre_logement.in_(nlogs),
            )
            .execution_options(yield_per=5000)
        )
        async for mat, nom_rue, municipalite, arrondissement, nb, deja in flux:
            nb_candidates += 1
            if not arrondissement and normaliser_secteur(municipalite) == "montreal":
                # Montréal sans arrondissement : impossible de trancher
                # entre 19 arrondissements → on ne marque pas (relancer
                # l'import du rôle Ville, qui remplit l'arrondissement).
                sans_arrondissement += 1
                continue
            secteur = arrondissement or municipalite or ""
            cle = (
                normaliser_secteur(secteur),
                normaliser_rue(nom_rue),
                int(nb or 0),
            )
            if cle in projets:
                par_cle[cle].append((mat, deja))

    # 3. Strict : un projet ne marque qu'UN immeuble, et seulement si un
    #    seul immeuble du rôle a cette clé — sinon un plex privé voisin de
    #    même taille serait exclu à tort (Phil 2026-09-29).
    marquages: Dict[str, str] = {}
    ambigus = 0
    for cle, liste in par_cle.items():
        if len(liste) != 1:
            ambigus += 1
            continue
        mat, deja = liste[0]
        if deja:  # déjà marqué par le nom du propriétaire
            continue
        typ, projet = projets[cle]
        marquages[mat] = libelle_social(typ, projet)
        par_type[typ] = par_type.get(typ, 0) + 1
    marquees_csv = await _ecrire_marquages(db, marquages)
    marquees_prop = await marquer_depuis_proprietaires(db)
    await db.flush()
    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(U)
                .where(U.logement_social.is_not(None))
            )
        ).scalar_one()
        or 0
    )
    log.info(
        "Logements sociaux : %d projets, %d unités marquées (fichier), "
        "%d (code 1010 du rôle), %d projets ambigus, %d (propriétaire), "
        "%d au total",
        len(projets), marquees_csv, marquees_code, ambigus, marquees_prop, total,
    )
    return {
        "projets": len(projets),
        "unites_candidates": nb_candidates,
        "source": source,
        "marquees_fichier": marquees_csv,
        "marquees_code_role": marquees_code,
        "projets_ambigus": ambigus,
        "marquees_proprietaire": marquees_prop,
        "montreal_sans_arrondissement": sans_arrondissement,
        "total_marquees": total,
        "par_type": par_type,
    }
