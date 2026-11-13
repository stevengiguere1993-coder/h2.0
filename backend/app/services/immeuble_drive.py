"""Documents Drive d'un immeuble (Steven, 2026-11-13).

« Dans les fiches des immeubles, nous devrions avoir accès à toute la
documentation des immeubles que nous gardons à jour dans le Drive :
certificat de localisation, taxes scolaires, taxes municipales,
assurance, tous autres documents reçus. »

Le Drive d'Horizon suit une structure stable :

    <Compagnie> / « 1 - Immeuble(s) » / « <adresse> » / 1 - Taxes,
    2 - Assurances, 3 - Prêts…, 4 - Gestion locative, 5 - Opérations,
    6 - Achat

1. **Repérage du dossier** (`trouver_dossiers_candidats`) : les dossiers
   Drive des compagnies sont déjà reliés à leur fiche Kratos
   (``DriveEntityLink`` « Entreprise »). On liste, en deux appels Drive
   groupés, les sous-dossiers « Immeuble(s) » de toutes les compagnies
   puis leurs enfants, et on note chaque dossier contre l'adresse de
   l'immeuble (`score_dossier`) : même numéro civique OBLIGATOIRE et au
   moins un mot distinctif de la rue en commun (« rue », « avenue »,
   « sud »… ne comptent pas). Repli : recherche Drive des dossiers dont le
   nom contient le numéro civique. Le meilleur est « certain » quand il
   est seul à ce score, et plus encore s'il est rangé sous une compagnie
   propriétaire de l'immeuble. Le lien est un ``DriveEntityLink``
   « Immeuble » ordinaire : l'explorateur Drive existant le lit tel quel.
2. **Documents** (`documents_immeuble`) : le dossier relié est parcouru
   par niveaux (une requête Drive par niveau et par paquet de dossiers,
   profondeur et nombre bornés), puis chaque fichier est rangé dans une
   catégorie (`classer_document`) : d'abord par son NOM (un certificat
   rangé dans « Achat » reste un certificat), sinon par le chemin de son
   dossier. Les quatre documents « clés » demandés par Steven sont
   toujours montrés, même vides, pour voir d'un coup d'œil ce qui manque.

Lecture seule côté Drive : rien n'est créé, déplacé ni renommé.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_entity_link import DriveEntityLink
from app.models.immobilier import Immeuble, ImmeubleOwnership
from app.services import drive_api
from app.services.drive_api import FOLDER_MIME, _escape_q

log = logging.getLogger(__name__)

ENTITY_TYPE = "Immeuble"

# Bornes du parcours d'un dossier d'immeuble.
PROFONDEUR_MAX = 5
FICHIERS_MAX = 600
PARENTS_PAR_REQUETE = 30

# Cache de l'inventaire des dossiers d'immeubles (toutes compagnies).
_CACHE_INVENTAIRE_S = 600
_cache_inventaire: dict[str, Any] = {"t": 0.0, "data": None}

_CHAMPS = (
    "nextPageToken, files(id, name, mimeType, size, modifiedTime, "
    "createdTime, parents, webViewLink, iconLink)"
)


# ---------------------------------------------------------------------------
# Texte
# ---------------------------------------------------------------------------


def normaliser(texte: Optional[str]) -> str:
    """Minuscules, sans accents, ponctuation → espaces."""
    if not texte:
        return ""
    t = unicodedata.normalize("NFKD", texte)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("’", "'")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Mots qui ne distinguent pas une rue d'une autre.
_MOTS_GENERIQUES = {
    "rue", "avenue", "ave", "av", "boulevard", "boul", "bd", "blvd",
    "place", "pl", "chemin", "ch", "route", "rte", "montee", "rang",
    "cote", "croissant", "terrasse", "allee", "impasse", "promenade",
    "de", "des", "du", "la", "le", "les", "l", "d", "et", "a", "au", "aux",
    "est", "ouest", "nord", "sud", "e", "o", "n", "s",
    "st", "ste", "saint", "sainte",
    "app", "apt", "local", "suite", "unite",
    "qc", "quebec", "canada",
    "immeuble", "immeubles", "inc",
}


def numeros(texte: Optional[str]) -> set[str]:
    """Tous les nombres d'un texte, sans zéros de tête (« 0710 » → « 710 »)."""
    return {n.lstrip("0") or "0" for n in re.findall(r"\d+", texte or "")}


def premier_numero(adresse: Optional[str]) -> Optional[str]:
    m = re.search(r"\d+", adresse or "")
    return (m.group(0).lstrip("0") or "0") if m else None


def mots_distinctifs(texte: Optional[str]) -> set[str]:
    """Mots de 3 lettres et plus, hors mots génériques et nombres."""
    return {
        m
        for m in normaliser(texte).split()
        if len(m) >= 3 and not m.isdigit() and m not in _MOTS_GENERIQUES
    }


# ---------------------------------------------------------------------------
# Repérage du dossier d'un immeuble
# ---------------------------------------------------------------------------


def adresses_immeuble(imm: Any) -> list[str]:
    """Adresse principale puis secondaire (fiches fusionnées)."""
    out = []
    for a in (getattr(imm, "address", None), getattr(imm, "address_secondaire", None)):
        if a and a.strip():
            out.append(a.strip())
    return out


def score_dossier(nom_dossier: str, adresses: Iterable[str], ville: Optional[str] = None) -> int:
    """Note un nom de dossier contre les adresses d'un immeuble.

    0 = ne correspond pas. Le numéro civique est obligatoire, et au moins
    un mot distinctif de la rue doit se retrouver dans le nom du dossier.
    Chaque mot de rue en plus, la ville et la seconde adresse ajoutent des
    points (départage « 976 Place Sapinière » et « 957-978 Place
    Sapinière »).
    """
    nums_dossier = numeros(nom_dossier)
    mots_dossier = set(normaliser(nom_dossier).split())
    total = 0
    for adresse in adresses:
        civique = premier_numero(adresse)
        if not civique or civique not in nums_dossier:
            continue
        mots_rue = mots_distinctifs(adresse)
        communs = mots_rue & mots_dossier
        if not communs:
            continue
        pts = 10 + 3 * len(communs)
        # Tous les nombres de l'adresse (« 1 - 5 », « 957-978 ») retrouvés.
        nums_adresse = numeros(adresse)
        if nums_adresse and nums_adresse <= nums_dossier:
            pts += 2
        total += pts
    if total and ville:
        if mots_distinctifs(ville) & mots_dossier:
            total += 1
    return total


@dataclass
class DossierCandidat:
    id: str
    nom: str
    url: Optional[str] = None
    parent_nom: Optional[str] = None
    entreprise_id: Optional[int] = None
    score: int = 0
    sous_proprietaire: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nom": self.nom,
            "url": self.url,
            "parent_nom": self.parent_nom,
            "entreprise_id": self.entreprise_id,
            "score": self.score,
            "sous_proprietaire": self.sous_proprietaire,
        }


async def _service(db: AsyncSession, user_id: int):
    return await drive_api.get_drive_service(user_id, db)


async def _lister(
    service: Any,
    parents: list[str],
    *,
    dossiers_seulement: bool = False,
    limite: int = 2000,
) -> list[dict[str, Any]]:
    """Enfants directs de plusieurs dossiers, en requêtes groupées."""
    out: list[dict[str, Any]] = []
    for i in range(0, len(parents), PARENTS_PAR_REQUETE):
        paquet = parents[i : i + PARENTS_PAR_REQUETE]
        cond = " or ".join(f"'{_escape_q(p)}' in parents" for p in paquet)
        q = f"({cond}) and trashed = false"
        if dossiers_seulement:
            q += f" and mimeType = '{FOLDER_MIME}'"
        jeton: Optional[str] = None
        while True:
            res = await asyncio.to_thread(
                lambda j=jeton: service.files()
                .list(
                    q=q,
                    pageSize=1000,
                    pageToken=j,
                    fields=_CHAMPS,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            out.extend(res.get("files", []))
            jeton = res.get("nextPageToken")
            if not jeton or len(out) >= limite:
                break
        if len(out) >= limite:
            break
    return out


def _est_dossier_immeubles(nom: str) -> bool:
    n = normaliser(nom)
    return "immeuble" in n and "vente" not in n


async def _liens_entreprises(db: AsyncSession) -> dict[str, int]:
    rows = (
        await db.execute(
            select(DriveEntityLink.drive_folder_id, DriveEntityLink.entity_id).where(
                DriveEntityLink.entity_type == "Entreprise"
            )
        )
    ).all()
    return {str(r[0]): int(r[1]) for r in rows if r[0]}


async def inventaire_dossiers(
    db: AsyncSession, user_id: int, *, rafraichir: bool = False
) -> list[DossierCandidat]:
    """Dossiers d'immeubles de toutes les compagnies reliées à Drive.

    Deux niveaux sous chaque compagnie : ses sous-dossiers « Immeuble(s) »
    puis leurs enfants. Les dossiers « Immeuble(s) » eux-mêmes sont aussi
    candidats (compagnie à un seul immeuble rangé à plat).
    """
    maintenant = time.monotonic()
    if (
        not rafraichir
        and _cache_inventaire["data"] is not None
        and maintenant - _cache_inventaire["t"] < _CACHE_INVENTAIRE_S
    ):
        return list(_cache_inventaire["data"])

    liens = await _liens_entreprises(db)
    if not liens:
        return []
    service = await _service(db, user_id)
    niveau1 = await _lister(service, list(liens), dossiers_seulement=True)
    groupes = [d for d in niveau1 if _est_dossier_immeubles(d.get("name", ""))]
    ent_de: dict[str, Optional[int]] = {}
    nom_de: dict[str, str] = {}
    for g in groupes:
        parent = (g.get("parents") or [None])[0]
        ent_de[g["id"]] = liens.get(str(parent)) if parent else None
        nom_de[g["id"]] = g.get("name", "")
    candidats: list[DossierCandidat] = []
    for g in groupes:
        parent = (g.get("parents") or [None])[0]
        candidats.append(
            DossierCandidat(
                id=g["id"],
                nom=g.get("name", ""),
                url=g.get("webViewLink"),
                parent_nom=None,
                entreprise_id=liens.get(str(parent)) if parent else None,
            )
        )
    if groupes:
        niveau2 = await _lister(service, [g["id"] for g in groupes], dossiers_seulement=True)
        for d in niveau2:
            parent = (d.get("parents") or [None])[0]
            candidats.append(
                DossierCandidat(
                    id=d["id"],
                    nom=d.get("name", ""),
                    url=d.get("webViewLink"),
                    parent_nom=nom_de.get(str(parent)),
                    entreprise_id=ent_de.get(str(parent)),
                )
            )
    _cache_inventaire["t"] = maintenant
    _cache_inventaire["data"] = list(candidats)
    return candidats


async def _recherche_par_numero(
    db: AsyncSession, user_id: int, civique: str
) -> list[DossierCandidat]:
    """Repli : dossiers Drive dont le NOM contient le numéro civique."""
    service = await _service(db, user_id)
    q = (
        f"name contains '{_escape_q(civique)}' and mimeType = '{FOLDER_MIME}' "
        "and trashed = false"
    )
    res = await asyncio.to_thread(
        lambda: service.files()
        .list(
            q=q,
            pageSize=100,
            fields=_CHAMPS,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    return [
        DossierCandidat(id=f["id"], nom=f.get("name", ""), url=f.get("webViewLink"))
        for f in res.get("files", [])
    ]


async def entreprises_de(db: AsyncSession, imm: Immeuble) -> set[int]:
    ids: set[int] = set()
    if imm.owner_entreprise_id:
        ids.add(int(imm.owner_entreprise_id))
    rows = (
        await db.execute(
            select(ImmeubleOwnership.entreprise_id).where(
                ImmeubleOwnership.immeuble_id == imm.id
            )
        )
    ).all()
    ids.update(int(r[0]) for r in rows if r[0])
    return ids


def choisir(
    candidats: list[DossierCandidat],
    adresses: list[str],
    ville: Optional[str],
    proprietaires: set[int],
    deja_pris: set[str] = frozenset(),  # type: ignore[assignment]
) -> tuple[list[DossierCandidat], Optional[DossierCandidat]]:
    """Note et trie les candidats ; renvoie (classés, certain ou None).

    Un candidat sous une compagnie propriétaire prend +5. « Certain » =
    meilleur score strictement au-dessus du deuxième, dossier pas déjà
    relié à un autre immeuble.
    """
    vus: dict[str, DossierCandidat] = {}
    for c in candidats:
        s = score_dossier(c.nom, adresses, ville)
        if s <= 0:
            continue
        sous_prop = c.entreprise_id is not None and c.entreprise_id in proprietaires
        s += 5 if sous_prop else 0
        prev = vus.get(c.id)
        if prev is None or s > prev.score:
            vus[c.id] = DossierCandidat(
                id=c.id,
                nom=c.nom,
                url=c.url,
                parent_nom=c.parent_nom,
                entreprise_id=c.entreprise_id,
                score=s,
                sous_proprietaire=sous_prop,
            )
    classes = sorted(vus.values(), key=lambda c: (-c.score, c.nom))
    libres = [c for c in classes if c.id not in deja_pris]
    certain = None
    if libres:
        premier = libres[0]
        second = libres[1].score if len(libres) > 1 else 0
        if premier.score > second:
            certain = premier
    return classes[:8], certain


async def _dossiers_deja_relies(db: AsyncSession, sauf_immeuble: Optional[int] = None) -> set[str]:
    stmt = select(DriveEntityLink.drive_folder_id, DriveEntityLink.entity_id).where(
        DriveEntityLink.entity_type == ENTITY_TYPE
    )
    rows = (await db.execute(stmt)).all()
    return {str(r[0]) for r in rows if r[0] and int(r[1]) != sauf_immeuble}


async def trouver_dossiers_candidats(
    db: AsyncSession, user_id: int, imm: Immeuble, *, rafraichir: bool = False
) -> tuple[list[DossierCandidat], Optional[DossierCandidat]]:
    adresses = adresses_immeuble(imm)
    if not adresses:
        return [], None
    proprietaires = await entreprises_de(db, imm)
    pris = await _dossiers_deja_relies(db, sauf_immeuble=imm.id)
    inventaire = await inventaire_dossiers(db, user_id, rafraichir=rafraichir)
    classes, certain = choisir(inventaire, adresses, imm.city, proprietaires, pris)
    if not classes:
        civique = premier_numero(adresses[0])
        if civique and len(civique) >= 2:
            trouves = await _recherche_par_numero(db, user_id, civique)
            classes, certain = choisir(trouves, adresses, imm.city, proprietaires, pris)
            # Hors de la structure des compagnies : jamais relié d'office.
            certain = None
    return classes, certain


async def lien_immeuble(db: AsyncSession, immeuble_id: int) -> Optional[DriveEntityLink]:
    return (
        await db.execute(
            select(DriveEntityLink).where(
                DriveEntityLink.entity_type == ENTITY_TYPE,
                DriveEntityLink.entity_id == immeuble_id,
            )
        )
    ).scalar_one_or_none()


async def relier(
    db: AsyncSession,
    immeuble_id: int,
    dossier_id: str,
    dossier_nom: Optional[str],
    user_id: Optional[int],
) -> DriveEntityLink:
    """Crée ou re-cible le lien Drive de l'immeuble (sans commit)."""
    lien = await lien_immeuble(db, immeuble_id)
    if lien is None:
        lien = DriveEntityLink(
            entity_type=ENTITY_TYPE,
            entity_id=immeuble_id,
            drive_folder_id=dossier_id,
            drive_folder_name=dossier_nom,
            created_by_user_id=user_id,
        )
        db.add(lien)
    else:
        lien.drive_folder_id = dossier_id
        lien.drive_folder_name = dossier_nom
        lien.drive_folder_path = None
    await db.flush()
    return lien


# ---------------------------------------------------------------------------
# Classement des documents
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Categorie:
    cle: str
    libelle: str
    cle_document: bool = False


CATEGORIES: list[Categorie] = [
    Categorie("certificat_localisation", "Certificat de localisation", True),
    Categorie("taxes_municipales", "Taxes municipales", True),
    Categorie("taxes_scolaires", "Taxes scolaires", True),
    Categorie("assurance", "Assurance", True),
    Categorie("evaluation", "Évaluations"),
    Categorie("financement", "Prêts et financement"),
    Categorie("achat", "Achat et actes"),
    Categorie("gestion_locative", "Gestion locative"),
    Categorie("operations", "Opérations (Hydro, internet…)"),
    Categorie("autres", "Autres documents"),
]
_CATEGORIE_PAR_CLE = {c.cle: c for c in CATEGORIES}


def _contient(texte: str, *motifs: str) -> bool:
    return any(re.search(m, texte) for m in motifs)


def _categorie_du_texte(t: str) -> Optional[str]:
    """Catégorie déduite d'un texte normalisé (nom ou chemin), sinon None."""
    if _contient(t, r"\bcertificat\w* (de )?loc", r"\bcert\w* loc", r"\barpent"):
        return "certificat_localisation"
    if _contient(t, r"\bscolaire", r"\bcss\b", r"\bcentre de services", r"\bcommission scol"):
        return "taxes_scolaires"
    if _contient(t, r"\btaxe", r"\bmunicipa", r"\bfonci", r"\bcompte de tax"):
        return "taxes_municipales"
    if _contient(t, r"\bassur", r"\binsurance\b", r"\bpolice d", r"\bavenant"):
        return "assurance"
    if _contient(t, r"\bevaluation", r"\beval\b", r"\brole d"):
        return "evaluation"
    if _contient(
        t,
        r"\bpret", r"\bhypo", r"\bfinancement", r"\brefinanc", r"\bbanque",
        r"\bschl\b", r"\bdesjardins\b", r"\bbnc\b", r"\bacte de pret",
    ):
        return "financement"
    if _contient(
        t,
        r"\bachat", r"\bacte de vente", r"\bvente\b", r"\bpromesse", r"\bnotaire",
        r"\bdeclaration\w* du vendeur", r"\bdv\b", r"\boffre", r"\binspection",
    ):
        return "achat"
    if _contient(
        t, r"\bbail", r"\bbaux\b", r"\blocatai", r"\blocati", r"\breglement", r"\btal\b",
    ):
        return "gestion_locative"
    if _contient(
        t, r"\bhydro", r"\binternet", r"\benergir", r"\bgaz\b", r"\boperation",
        r"\bbell\b", r"\bvideotron", r"\bdeneig", r"\bentretien",
    ):
        return "operations"
    return None


def classer_document(nom: str, chemin: str = "") -> str:
    """Catégorie d'un fichier : par son nom d'abord, sinon par son dossier.

    Dans le chemin, c'est le dossier le PLUS PROCHE du fichier qui
    l'emporte (« 2 - Assurances / Taxes 2024 » → taxes).
    """
    par_nom = _categorie_du_texte(normaliser(re.sub(r"\.[A-Za-z0-9]{2,5}$", "", nom)))
    if par_nom:
        # Un fichier « Taxes 2025.pdf » rangé dans « Taxes scolaires » reste
        # scolaire : le dossier précise une taxe générique.
        if par_nom == "taxes_municipales" and chemin:
            for segment in reversed([s for s in chemin.split("/") if s.strip()]):
                if _categorie_du_texte(normaliser(segment)) == "taxes_scolaires":
                    return "taxes_scolaires"
        return par_nom
    for segment in reversed([s for s in chemin.split("/") if s.strip()]):
        cat = _categorie_du_texte(normaliser(segment))
        if cat:
            return cat
    return "autres"


def annee_document(nom: str, chemin: str = "") -> Optional[int]:
    """Année la plus récente citée dans le nom, sinon dans le chemin."""
    for texte in (nom, chemin):
        annees = [int(a) for a in re.findall(r"(?<!\d)(20[0-4]\d|19[89]\d)(?!\d)", texte or "")]
        if annees:
            return max(annees)
    return None


def _cle_tri(doc: dict[str, Any]) -> tuple[int, str]:
    return (doc.get("annee") or 0, doc.get("modifie_le") or "")


@dataclass
class ParcoursDossier:
    fichiers: list[dict[str, Any]] = field(default_factory=list)
    nb_dossiers: int = 0
    tronque: bool = False


async def parcourir(db: AsyncSession, user_id: int, racine_id: str) -> ParcoursDossier:
    """Tous les fichiers sous ``racine_id`` (par niveaux, bornés)."""
    service = await _service(db, user_id)
    out = ParcoursDossier()
    chemins: dict[str, str] = {racine_id: ""}
    niveau = [racine_id]
    profondeur = 0
    while niveau and profondeur <= PROFONDEUR_MAX:
        enfants = await _lister(service, niveau, limite=FICHIERS_MAX * 2)
        suivant: list[str] = []
        for f in enfants:
            parent = (f.get("parents") or [None])[0]
            base = chemins.get(str(parent), "")
            if f.get("mimeType") == FOLDER_MIME:
                if profondeur < PROFONDEUR_MAX:
                    chemins[f["id"]] = f"{base}/{f.get('name', '')}".strip("/")
                    suivant.append(f["id"])
                else:
                    out.tronque = True
                continue
            if len(out.fichiers) >= FICHIERS_MAX:
                out.tronque = True
                continue
            out.fichiers.append({**f, "_chemin": base})
        out.nb_dossiers += len(suivant)
        niveau = suivant
        profondeur += 1
    return out


def ranger(fichiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fichiers Drive → catégories (documents du plus récent au plus ancien)."""
    par_cat: dict[str, list[dict[str, Any]]] = {c.cle: [] for c in CATEGORIES}
    for f in fichiers:
        nom = f.get("name", "")
        chemin = f.get("_chemin", "")
        cat = classer_document(nom, chemin)
        par_cat[cat].append(
            {
                "id": f.get("id"),
                "nom": nom,
                "mime_type": f.get("mimeType"),
                "taille": int(f["size"]) if str(f.get("size") or "").isdigit() else None,
                "modifie_le": f.get("modifiedTime"),
                "url": f.get("webViewLink"),
                "icone": f.get("iconLink"),
                "dossier": chemin or None,
                "annee": annee_document(nom, chemin),
            }
        )
    resultat = []
    for c in CATEGORIES:
        docs = sorted(par_cat[c.cle], key=_cle_tri, reverse=True)
        if not docs and not c.cle_document:
            continue
        resultat.append(
            {
                "cle": c.cle,
                "libelle": c.libelle,
                "cle_document": c.cle_document,
                "nombre": len(docs),
                "documents": docs,
            }
        )
    return resultat


# Cache court des documents par dossier (navigation d'onglets).
_CACHE_DOCS_S = 120
_cache_docs: dict[str, tuple[float, dict[str, Any]]] = {}


async def documents_dossier(
    db: AsyncSession, user_id: int, dossier_id: str, *, rafraichir: bool = False
) -> dict[str, Any]:
    maintenant = time.monotonic()
    en_cache = _cache_docs.get(dossier_id)
    if en_cache and not rafraichir and maintenant - en_cache[0] < _CACHE_DOCS_S:
        return en_cache[1]
    parcours = await parcourir(db, user_id, dossier_id)
    data = {
        "categories": ranger(parcours.fichiers),
        "nombre_fichiers": len(parcours.fichiers),
        "nombre_dossiers": parcours.nb_dossiers,
        "tronque": parcours.tronque,
        "lu_le": datetime.utcnow().isoformat() + "Z",
    }
    _cache_docs[dossier_id] = (maintenant, data)
    if len(_cache_docs) > 200:
        for cle in sorted(_cache_docs, key=lambda k: _cache_docs[k][0])[:50]:
            _cache_docs.pop(cle, None)
    return data


def oublier_cache(dossier_id: Optional[str] = None) -> None:
    if dossier_id:
        _cache_docs.pop(dossier_id, None)
    else:
        _cache_docs.clear()
    _cache_inventaire["data"] = None
