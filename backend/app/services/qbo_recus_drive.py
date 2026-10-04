"""Reçus QuickBooks → Google Drive (chantier Phil 2026-10-04).

Chaque compagnie QuickBooks connectée à une entreprise Kratos (scope
« inc:{entreprise_id} ») est interrogée : ses pièces jointes image/PDF
liées à une DÉPENSE (Purchase : dépense, chèque, carte de crédit ;
Bill : facture fournisseur) sont copiées dans le Drive de l'entreprise :

    <dossier Drive de l'entreprise> / Factures / 2026 / Octobre /
        2026-10-03 Rona 2134,02$.pdf

Règles décidées avec Phil :
- noms de mois en français (« Octobre ») ;
- fournisseur absent → « Fournisseur inconnu » ;
- dépenses seulement (pas les factures de vente) ;
- pas de doublon : une pièce jointe déjà traitée (table
  ``qbo_recus_drive``) n'est jamais recopiée ; un fichier portant déjà
  EXACTEMENT le même nom (date + fournisseur + montant) dans le dossier
  du mois n'est pas recréé.
- pièce jointe sans transaction liée (reçu téléversé mais pas encore
  rapproché) → sous-dossier « À classer » du mois de son téléversement.

Deux usages : rattrapage (depuis le 1er janvier 2026, bouton de la
page « Reçus QuickBooks ») et nuit (méga-cron ``all-daily`` : les trois
derniers jours, pour couvrir les reçus joints en retard). Un mode
``simulation`` liste ce qui serait copié sans toucher au Drive.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_convention import DriveConvention
from app.models.drive_entity_link import DriveEntityLink
from app.models.entreprise import Entreprise
from app.models.qbo_connection import QboConnection
from app.models.qbo_recu_drive import QboRecuDrive
from app.models.qbo_token import QboToken

log = logging.getLogger(__name__)

MOIS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]
DOSSIER_FACTURES = "Factures"
DOSSIER_A_CLASSER = "À classer"
FOURNISSEUR_INCONNU = "Fournisseur inconnu"
#: Types de transaction QuickBooks considérés comme des DÉPENSES.
TXN_DEPENSES = ("Purchase", "Bill")
#: Pièces jointes acceptées (reçus) : extension → type MIME.
_EXT_CTYPE = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".gif": "image/gif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
_CTYPE_EXT = {v: k for k, v in _EXT_CTYPE.items()}
_CTYPE_EXT["image/jpeg"] = ".jpg"
_MAX_OCTETS = 25 * 1024 * 1024
DEBUT_PAR_DEFAUT = date(2026, 1, 1)
#: Fenêtre de la nuit : la veille + marge pour les reçus joints en retard.
JOURS_FENETRE_NUIT = 3

#: État du dernier run (lecture par la page) — un seul run à la fois.
DERNIER_RUN: Dict[str, Any] = {
    "en_cours": False,
    "lance_a": None,
    "termine_a": None,
    "simulation": None,
    "declencheur": None,
    "progression": None,
    "rapport": None,
}


# ──────────────────────────────────────────────────────────────────────
# Utilitaires purs
# ──────────────────────────────────────────────────────────────────────


def folder_id_depuis_url(url: Optional[str]) -> Optional[str]:
    """Identifiant d'un dossier Drive depuis son URL (ou l'id brut)."""
    if not url:
        return None
    u = url.strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", u)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", u)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", u):
        return u
    return None


def normaliser_nom(s: Optional[str]) -> str:
    """Clé de comparaison d'un nom de dossier Drive : sans accent, sans
    casse, sans préfixe numérique « 2 - », sans ponctuation finale. Les
    dossiers de Phil sont numérotés (« 1 - MGV Investissements inc »,
    « 2 - Factures ») : on doit les reconnaître sans créer un doublon."""
    t = unicodedata.normalize("NFKD", s or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.casefold().strip()
    t = re.sub(r"^\d+\s*[-–—.:)]\s*", "", t)  # « 2 - Factures » → « factures »
    t = re.sub(r"[^\w\s]+", " ", t)  # ponctuation → espace (« inc. » → « inc »)
    return " ".join(t.split())


def montant_texte(montant: Optional[float]) -> str:
    """2134.02 → « 2134,02$ » (virgule décimale, sans espace de milliers)."""
    if montant is None:
        return "0,00$"
    return f"{float(montant):.2f}".replace(".", ",") + "$"


def nettoyer_nom(s: Optional[str]) -> str:
    """Nom de fournisseur sûr pour un nom de fichier."""
    t = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s or "")
    t = " ".join(t.split()).strip(" .")
    return t[:80] or FOURNISSEUR_INCONNU


def nom_fichier(d: date, fournisseur: Optional[str], montant: Optional[float], ext: str) -> str:
    return f"{d.isoformat()} {nettoyer_nom(fournisseur)} {montant_texte(montant)}{ext}"


def extension_de(att: Dict[str, Any]) -> Optional[str]:
    """Extension du reçu depuis le nom de fichier QB ou son ContentType ;
    None si ce n'est pas une image / un PDF."""
    name = (att.get("FileName") or "").lower().strip()
    for ext in _EXT_CTYPE:
        if name.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    ctype = (att.get("ContentType") or "").lower().split(";")[0].strip()
    return _CTYPE_EXT.get(ctype)


def _date_iso(v: Any) -> Optional[date]:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def infos_transaction(txn_type: str, txn: Dict[str, Any]) -> Dict[str, Any]:
    """Date, fournisseur, montant d'une dépense QuickBooks."""
    d = _date_iso(txn.get("TxnDate"))
    if txn_type == "Bill":
        vendeur = (txn.get("VendorRef") or {}).get("name")
    else:
        ent = txn.get("EntityRef") or {}
        vendeur = ent.get("name") if (ent.get("type") or "Vendor") == "Vendor" else None
    montant = txn.get("TotalAmt")
    try:
        montant = round(float(montant), 2) if montant is not None else None
    except (TypeError, ValueError):
        montant = None
    return {"date": d, "fournisseur": (vendeur or "").strip() or FOURNISSEUR_INCONNU, "montant": montant}


# ──────────────────────────────────────────────────────────────────────
# Entreprises prêtes (connexion QuickBooks + dossier Drive)
# ──────────────────────────────────────────────────────────────────────

#: Type d'entité des liens Drive de la fiche entreprise (<EntityDriveSection>).
ENTITY_TYPE_ENTREPRISE = "Entreprise"
#: Connexion QuickBooks historique du pôle Construction (Horizon Services
#: Immobiliers) — table qbo_tokens, pas qbo_connections.
SCOPE_CONSTRUCTION = "construction"


def scope_de(e: Entreprise) -> str:
    """Scope QuickBooks de l'entreprise : choix enregistré, sinon sa
    propre compagnie « inc:{id} »."""
    return (getattr(e, "qbo_scope", None) or "").strip() or f"inc:{e.id}"


async def changer_scope(db: AsyncSession, entreprise_id: int, scope: Optional[str]) -> str:
    """Enregistre la connexion QuickBooks à utiliser pour une entreprise :
    None / « inc:{id} » = la sienne, « construction » = celle d'Horizon."""
    e = await db.get(Entreprise, entreprise_id)
    if e is None:
        raise ValueError("Entreprise introuvable.")
    s = (scope or "").strip()
    if s in ("", f"inc:{e.id}"):
        e.qbo_scope = None
    elif s == SCOPE_CONSTRUCTION:
        e.qbo_scope = SCOPE_CONSTRUCTION
    else:
        raise ValueError("Connexion inconnue : « construction » ou vide.")
    await db.commit()
    return scope_de(e)
#: Cache de la découverte automatique (entreprise_id → (folder_id|None, ts)).
_DECOUVERTE: Dict[int, tuple] = {}
_DECOUVERTE_TTL = 600.0


def url_dossier(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


async def _dossier_entreprise(
    db: AsyncSession,
    e: Entreprise,
    liens: Dict[int, DriveEntityLink],
    convention: Optional[DriveConvention],
    drive_user_id: Optional[int],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(folder_id, url, source) du dossier Drive de l'entreprise, dans
    l'ordre : URL collée sur la fiche → lien « Documents Drive » de la
    fiche → découverte dans le dossier parent de la convention Entreprise
    (un sous-dossier qui porte le nom de l'entreprise ; le lien est alors
    enregistré pour de bon). Phil 2026-10-04 : « on devrait avoir l'URL
    du dossier partagé pour chacune des entreprises »."""
    fid = folder_id_depuis_url(getattr(e, "drive_folder_url", None))
    if fid:
        return fid, getattr(e, "drive_folder_url", None), "fiche"
    lien = liens.get(e.id)
    if lien is not None and lien.drive_folder_id:
        return lien.drive_folder_id, url_dossier(lien.drive_folder_id), "lien"
    parent = getattr(convention, "parent_folder_drive_id", None) if convention else None
    if not parent or drive_user_id is None:
        return None, None, None
    import time as _time

    cache = _DECOUVERTE.get(e.id)
    if cache and _time.monotonic() - cache[1] < _DECOUVERTE_TTL:
        fid = cache[0]
        return (fid, url_dossier(fid), "convention") if fid else (None, None, None)
    try:
        from app.services.drive_api import FOLDER_MIME, list_folder_contents

        voulu = normaliser_nom(e.name)
        trouve: Optional[Dict[str, Any]] = None
        token: Optional[str] = None
        for _ in range(20):
            page = await list_folder_contents(drive_user_id, db, parent, page_size=200, page_token=token)
            for f in page.get("files") or []:
                if f.get("mimeType") == FOLDER_MIME and normaliser_nom(f.get("name")) == voulu:
                    trouve = f
                    break
            token = page.get("next_page_token")
            if trouve or not token:
                break
    except Exception as exc:  # noqa: BLE001
        log.warning("Découverte du dossier Drive de %s impossible : %s", e.name, exc)
        _DECOUVERTE[e.id] = (None, _time.monotonic())
        return None, None, None
    if trouve is None:
        _DECOUVERTE[e.id] = (None, _time.monotonic())
        return None, None, None
    fid = str(trouve["id"])
    # On enregistre le lien : la section « Documents Drive » de la fiche
    # et la copie des reçus pointent désormais le même dossier.
    try:
        db.add(
            DriveEntityLink(
                entity_type=ENTITY_TYPE_ENTREPRISE,
                entity_id=e.id,
                drive_folder_id=fid,
                drive_folder_name=trouve.get("name"),
                convention_id=convention.id if convention else None,
            )
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        log.warning("Lien Drive de %s non enregistré : %s", e.name, exc)
    _DECOUVERTE[e.id] = (fid, _time.monotonic())
    return fid, url_dossier(fid), "convention"


async def entreprises_etat(db: AsyncSession) -> List[Dict[str, Any]]:
    """Toutes les entreprises actives avec leur état de préparation :
    connexion QuickBooks (scope inc:{id}), dossier Drive, compteurs."""
    from app.services.drive_auto_upload_dispatcher import resolve_drive_owner_user_id

    liens = {
        int(l.entity_id): l
        for l in (
            await db.execute(
                select(DriveEntityLink).where(DriveEntityLink.entity_type == ENTITY_TYPE_ENTREPRISE)
            )
        ).scalars().all()
    }
    convention = (
        await db.execute(
            select(DriveConvention)
            .where(
                DriveConvention.entity_type == ENTITY_TYPE_ENTREPRISE,
                DriveConvention.active.is_(True),
                DriveConvention.parent_folder_drive_id.is_not(None),
            )
            .order_by(DriveConvention.priority.desc(), DriveConvention.id.asc())
        )
    ).scalars().first()
    drive_user_id = await resolve_drive_owner_user_id(db) if convention else None
    ents = (
        await db.execute(
            select(Entreprise)
            .where(Entreprise.is_active.is_(True))
            .order_by(Entreprise.position.asc(), Entreprise.id.asc())
        )
    ).scalars().all()
    conns = {
        c.scope: c
        for c in (
            await db.execute(
                select(QboConnection).where(QboConnection.scope.like("inc:%"))
            )
        ).scalars().all()
    }
    # Connexion Construction (Horizon) : table historique qbo_tokens.
    tok = (await db.execute(select(QboToken).where(QboToken.id == 1))).scalar_one_or_none()
    construction = {
        "connectee": bool(tok and tok.refresh_token and tok.realm_id),
        "company_name": (getattr(tok, "company_name", None) if tok else None) or "Horizon (Construction)",
        "realm_id": tok.realm_id if tok else None,
    }
    stats = {
        int(eid): (int(n), last)
        for eid, n, last in (
            await db.execute(
                select(
                    QboRecuDrive.entreprise_id,
                    func.count(QboRecuDrive.id),
                    func.max(QboRecuDrive.created_at),
                )
                .where(QboRecuDrive.statut == "copie")
                .group_by(QboRecuDrive.entreprise_id)
            )
        ).all()
        if eid is not None
    }
    out: List[Dict[str, Any]] = []
    for e in ents:
        scope = scope_de(e)
        if scope == SCOPE_CONSTRUCTION:
            qbo_ok = construction["connectee"]
            qbo_nom = construction["company_name"]
            qbo_realm = construction["realm_id"]
        else:
            c = conns.get(scope)
            qbo_ok = bool(c and c.realm_id and c.refresh_token)
            qbo_nom = c.company_name if c else None
            qbo_realm = c.realm_id if c else None
        folder, url, source = await _dossier_entreprise(db, e, liens, convention, drive_user_id)
        n, last = stats.get(e.id, (0, None))
        out.append(
            {
                "entreprise_id": e.id,
                "name": e.name,
                "qbo_scope": scope,
                "qbo_connectee": qbo_ok,
                "qbo_company_name": qbo_nom,
                "qbo_realm_id": qbo_realm,
                "qbo_construction_disponible": construction["connectee"],
                "drive_folder_url": url,
                "drive_folder_id": folder,
                "drive_source": source,
                "prete": bool(qbo_ok and folder),
                "copies": n,
                "derniere_copie": last.isoformat() if last else None,
            }
        )
    return out


# ──────────────────────────────────────────────────────────────────────
# Drive : arborescence Factures / année / mois (avec cache par run)
# ──────────────────────────────────────────────────────────────────────


class _Drive:
    """Accès Drive pour un run : listing des dossiers en cache, création
    des dossiers manquants (jamais en simulation)."""

    def __init__(self, user_id: int, db: AsyncSession, simulation: bool) -> None:
        self.user_id = user_id
        self.db = db
        self.simulation = simulation
        self._contenu: Dict[str, List[Dict[str, Any]]] = {}
        self.dossiers_crees: List[str] = []
        self.dossiers_a_creer: List[str] = []

    async def contenu(self, folder_id: str) -> List[Dict[str, Any]]:
        if folder_id in self._contenu:
            return self._contenu[folder_id]
        from app.services.drive_api import list_folder_contents

        files: List[Dict[str, Any]] = []
        token: Optional[str] = None
        for _ in range(50):
            page = await list_folder_contents(
                self.user_id, self.db, folder_id, page_size=200, page_token=token
            )
            files.extend(page.get("files") or [])
            token = page.get("next_page_token")
            if not token:
                break
        self._contenu[folder_id] = files
        return files

    def _ajouter(self, folder_id: str, f: Dict[str, Any]) -> None:
        self._contenu.setdefault(folder_id, []).append(f)

    async def sous_dossier(self, parent_id: str, nom: str, chemin: str) -> Optional[str]:
        """Id du sous-dossier ``nom`` de ``parent_id`` (comparaison sans
        casse ni accents superflus) ; créé s'il manque. None en
        simulation quand il faudrait le créer."""
        from app.services.drive_api import FOLDER_MIME, create_folder

        voulu = normaliser_nom(nom)
        for f in await self.contenu(parent_id):
            if f.get("mimeType") == FOLDER_MIME and normaliser_nom(f.get("name")) == voulu:
                return str(f["id"])
        if self.simulation:
            if chemin not in self.dossiers_a_creer:
                self.dossiers_a_creer.append(chemin)
            return None
        cree = await create_folder(self.user_id, self.db, parent_id, nom)
        self._ajouter(parent_id, cree)
        self._contenu[str(cree["id"])] = []
        self.dossiers_crees.append(chemin)
        return str(cree["id"])

    async def dossier_mois(self, racine_id: str, nom_entreprise: str, d: date, a_classer: bool = False) -> Optional[str]:
        base = f"{nom_entreprise} / {DOSSIER_FACTURES}"
        fid = await self.sous_dossier(racine_id, DOSSIER_FACTURES, base)
        if fid is None:
            return None
        annee = str(d.year)
        fid = await self.sous_dossier(fid, annee, f"{base} / {annee}")
        if fid is None:
            return None
        mois = MOIS_FR[d.month - 1]
        fid = await self.sous_dossier(fid, mois, f"{base} / {annee} / {mois}")
        if fid is None or not a_classer:
            return fid
        return await self.sous_dossier(fid, DOSSIER_A_CLASSER, f"{base} / {annee} / {mois} / {DOSSIER_A_CLASSER}")

    async def fichier_existant(self, folder_id: str, nom: str) -> Optional[str]:
        voulu = nom.strip().casefold()
        for f in await self.contenu(folder_id):
            if (f.get("name") or "").strip().casefold() == voulu:
                return str(f["id"])
        return None

    async def televerser(self, folder_id: str, nom: str, contenu: bytes, mime: Optional[str]) -> str:
        from app.services.drive_api import upload_file

        meta = await upload_file(self.user_id, self.db, folder_id, nom, contenu, mime)
        self._ajouter(folder_id, meta)
        return str(meta.get("id") or "")


# ──────────────────────────────────────────────────────────────────────
# Exécution
# ──────────────────────────────────────────────────────────────────────


def _nouveau_rapport_entreprise(e: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "entreprise_id": e["entreprise_id"],
        "name": e["name"],
        "qbo_company_name": e.get("qbo_company_name"),
        "pieces_jointes": 0,
        "copies": 0,
        "prevus": 0,
        "a_classer": 0,
        "ignores_deja_traites": 0,
        "ignores_drive": 0,
        "hors_periode": 0,
        "non_recu": 0,
        "hors_depenses": 0,
        "erreurs": 0,
        "messages": [],
        "apercu": [],
    }


async def _traiter_entreprise(
    db: AsyncSession,
    e: Dict[str, Any],
    drive: _Drive,
    *,
    depuis: date,
    jusqua: date,
    simulation: bool,
    declencheur: str,
    rapport: Dict[str, Any],
) -> None:
    from app.integrations.quickbooks import QuickBooksClient, QuickBooksError

    qbo = QuickBooksClient(scope=e["qbo_scope"])
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        rapport["erreurs"] += 1
        rapport["messages"].append("QuickBooks : connexion absente ou jeton invalide — reconnecte la compagnie.")
        return
    realm = str(qbo.realm_id or e.get("qbo_realm_id") or "")
    racine = e["drive_folder_id"]

    try:
        atts = await qbo.query_all("SELECT * FROM attachable")
    except QuickBooksError as exc:
        rapport["erreurs"] += 1
        rapport["messages"].append(f"QuickBooks : lecture des pièces jointes impossible ({str(exc)[:160]}).")
        return
    rapport["pieces_jointes"] = len(atts)

    deja = {
        (a, t, i)
        for a, t, i in (
            await db.execute(
                select(QboRecuDrive.attachable_id, QboRecuDrive.txn_type, QboRecuDrive.txn_id).where(
                    QboRecuDrive.realm_id == realm
                )
            )
        ).all()
    }
    # Plusieurs pièces jointes sur la MÊME dépense (recto / verso, deux
    # pages) : même date, fournisseur et montant → la 2e s'appelle
    # « … 2134,02$ (2).pdf » au lieu d'être prise pour un doublon.
    pieces_par_txn: Dict[tuple, List[str]] = {}
    for a, t, i in deja:
        if t:
            pieces_par_txn.setdefault((t, i), []).append(a)

    def nom_indexe(nom: str, t: str, i: str, att_id: str) -> str:
        if not t:
            return nom
        lst = pieces_par_txn.setdefault((t, i), [])
        if att_id not in lst:
            lst.append(att_id)
        rang = lst.index(att_id) + 1
        if rang <= 1:
            return nom
        racine, ext = re.match(r"^(.*?)(\.[A-Za-z0-9]+)?$", nom).groups()
        return f"{racine} ({rang}){ext or ''}"

    cache_txn: Dict[tuple, Optional[Dict[str, Any]]] = {}
    cache_contenu: Dict[str, Optional[bytes]] = {}

    async def contenu_de(att_id: str) -> Optional[bytes]:
        if att_id not in cache_contenu:
            cache_contenu[att_id] = await qbo.download_attachable(att_id)
        return cache_contenu[att_id]

    for idx, att in enumerate(atts):
        DERNIER_RUN["progression"] = {
            "entreprise": e["name"],
            "piece": idx + 1,
            "pieces_jointes": len(atts),
            "copies": rapport["copies"] + rapport["prevus"],
        }
        att_id = str(att.get("Id") or "")
        if not att_id:
            continue
        ext = extension_de(att)
        if ext is None:
            rapport["non_recu"] += 1
            continue
        mime = _EXT_CTYPE.get(ext)
        refs = [
            (str((r.get("EntityRef") or {}).get("type") or ""), str((r.get("EntityRef") or {}).get("value") or ""))
            for r in (att.get("AttachableRef") or [])
        ]
        refs_toutes = [(t, v) for t, v in refs if v]
        refs = [(t, v) for t, v in refs_toutes if t in TXN_DEPENSES]
        if refs_toutes and not refs:
            # Liée seulement à autre chose qu'une dépense (facture de
            # vente, paiement…) : hors scope, pas « à classer ».
            rapport["hors_depenses"] += 1
            continue

        # Pièce jointe sans transaction liée → « À classer » du mois de dépôt.
        cibles: List[Dict[str, Any]] = []
        if not refs:
            d_depot = _date_iso(((att.get("MetaData") or {}).get("CreateTime")))
            if d_depot is None:
                rapport["non_recu"] += 1
                continue
            base = re.sub(r"\.[A-Za-z0-9]+$", "", att.get("FileName") or "reçu")
            cibles.append(
                {
                    "txn_type": "",
                    "txn_id": "",
                    "date": d_depot,
                    "fournisseur": FOURNISSEUR_INCONNU,
                    "montant": None,
                    "nom": f"{d_depot.isoformat()} {nettoyer_nom(base)}{ext}",
                    "a_classer": True,
                }
            )
        else:
            for t, v in refs:
                if (att_id, t, v) in deja:
                    rapport["ignores_deja_traites"] += 1
                    continue
                if (t, v) not in cache_txn:
                    try:
                        cache_txn[(t, v)] = await (qbo.get_bill(v) if t == "Bill" else qbo.get_purchase(v))
                    except QuickBooksError as exc:
                        cache_txn[(t, v)] = None
                        rapport["erreurs"] += 1
                        rapport["messages"].append(f"{t} {v} : lecture impossible ({str(exc)[:120]}).")
                txn = cache_txn[(t, v)]
                if txn is None:
                    continue
                info = infos_transaction(t, txn)
                if info["date"] is None:
                    rapport["non_recu"] += 1
                    continue
                cibles.append(
                    {
                        "txn_type": t,
                        "txn_id": v,
                        "date": info["date"],
                        "fournisseur": info["fournisseur"],
                        "montant": info["montant"],
                        "nom": nom_indexe(
                            nom_fichier(info["date"], info["fournisseur"], info["montant"], ext), t, v, att_id
                        ),
                        "a_classer": False,
                    }
                )

        for c in cibles:
            if (att_id, c["txn_type"], c["txn_id"]) in deja:
                rapport["ignores_deja_traites"] += 1
                continue
            if not (depuis <= c["date"] <= jusqua):
                rapport["hors_periode"] += 1
                continue
            try:
                dossier = await drive.dossier_mois(racine, e["name"], c["date"], a_classer=c["a_classer"])
            except Exception as exc:  # noqa: BLE001
                rapport["erreurs"] += 1
                rapport["messages"].append(f"Drive : dossier du mois inaccessible ({str(exc)[:160]}).")
                return
            existant = await drive.fichier_existant(dossier, c["nom"]) if dossier else None
            ligne = QboRecuDrive(
                entreprise_id=e["entreprise_id"],
                realm_id=realm,
                attachable_id=att_id,
                txn_type=c["txn_type"],
                txn_id=c["txn_id"],
                date_recu=c["date"],
                fournisseur=c["fournisseur"],
                montant=c["montant"],
                nom_fichier=c["nom"],
                drive_folder_id=dossier,
                declencheur=declencheur,
            )
            if len(rapport["apercu"]) < 300:
                rapport["apercu"].append(
                    {
                        "date": c["date"].isoformat(),
                        "fournisseur": c["fournisseur"],
                        "montant": c["montant"],
                        "nom": c["nom"],
                        "dossier": f"{DOSSIER_FACTURES}/{c['date'].year}/{MOIS_FR[c['date'].month - 1]}"
                        + (f"/{DOSSIER_A_CLASSER}" if c["a_classer"] else ""),
                        "statut": "doublon_drive" if existant else ("prevu" if simulation else "copie"),
                    }
                )
            if existant:
                rapport["ignores_drive"] += 1
                if not simulation:
                    ligne.statut = "ignore_doublon"
                    ligne.drive_file_id = existant
                    ligne.detail = "Un fichier du même nom existait déjà dans le dossier du mois."
                    db.add(ligne)
                    deja.add((att_id, c["txn_type"], c["txn_id"]))
                continue
            if c["a_classer"]:
                rapport["a_classer"] += 1
            if simulation:
                rapport["prevus"] += 1
                continue
            contenu = await contenu_de(att_id)
            if not contenu or len(contenu) > _MAX_OCTETS:
                rapport["erreurs"] += 1
                rapport["messages"].append(f"{c['nom']} : téléchargement QuickBooks vide ou trop gros.")
                continue
            try:
                fid = await drive.televerser(dossier, c["nom"], contenu, mime)
            except Exception as exc:  # noqa: BLE001
                rapport["erreurs"] += 1
                rapport["messages"].append(f"{c['nom']} : téléversement Drive échoué ({str(exc)[:120]}).")
                continue
            ligne.statut = "copie"
            ligne.drive_file_id = fid
            db.add(ligne)
            deja.add((att_id, c["txn_type"], c["txn_id"]))
            rapport["copies"] += 1
            if rapport["copies"] % 25 == 0:
                await db.commit()
    await db.commit()


async def executer(
    db: AsyncSession,
    *,
    entreprise_ids: Optional[List[int]] = None,
    depuis: Optional[date] = None,
    jusqua: Optional[date] = None,
    simulation: bool = True,
    declencheur: str = "rattrapage",
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Copie (ou simule) les reçus de chaque entreprise prête. Renvoie
    le rapport ; il est aussi gardé dans ``DERNIER_RUN``."""
    from app.services.drive_auto_upload_dispatcher import resolve_drive_owner_user_id

    depuis = depuis or DEBUT_PAR_DEFAUT
    jusqua = jusqua or date.today()
    if DERNIER_RUN.get("en_cours"):
        return {"ok": False, "erreur": "Un run est déjà en cours."}
    DERNIER_RUN.update(
        en_cours=True,
        lance_a=datetime.now(timezone.utc).isoformat(),
        termine_a=None,
        simulation=simulation,
        declencheur=declencheur,
        progression=None,
        rapport=None,
    )
    rapport: Dict[str, Any] = {
        "ok": True,
        "simulation": simulation,
        "declencheur": declencheur,
        "depuis": depuis.isoformat(),
        "jusqua": jusqua.isoformat(),
        "entreprises": [],
        "non_pretes": [],
        "dossiers_crees": [],
        "dossiers_a_creer": [],
        "totaux": {"copies": 0, "prevus": 0, "ignores": 0, "erreurs": 0},
    }
    try:
        owner = await resolve_drive_owner_user_id(db, user_id)
        if owner is None:
            rapport["ok"] = False
            rapport["erreur"] = "Aucun compte Google Drive connecté dans Kratos (Paramètres → Drive)."
            return rapport
        drive = _Drive(owner, db, simulation)
        etats = await entreprises_etat(db)
        for e in etats:
            if entreprise_ids and e["entreprise_id"] not in entreprise_ids:
                continue
            if not e["prete"]:
                manque = []
                if not e["qbo_connectee"]:
                    manque.append("connexion QuickBooks")
                if not e["drive_folder_id"]:
                    manque.append("dossier Drive")
                rapport["non_pretes"].append({"entreprise_id": e["entreprise_id"], "name": e["name"], "manque": manque})
                continue
            r = _nouveau_rapport_entreprise(e)
            try:
                await _traiter_entreprise(
                    db, e, drive, depuis=depuis, jusqua=jusqua, simulation=simulation,
                    declencheur=declencheur, rapport=r,
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("Reçus QB → Drive : %s", e["name"])
                r["erreurs"] += 1
                r["messages"].append(f"Interrompu : {str(exc)[:200]}")
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
            rapport["entreprises"].append(r)
            t = rapport["totaux"]
            t["copies"] += r["copies"]
            t["prevus"] += r["prevus"]
            t["ignores"] += r["ignores_deja_traites"] + r["ignores_drive"]
            t["erreurs"] += r["erreurs"]
        rapport["dossiers_crees"] = drive.dossiers_crees
        rapport["dossiers_a_creer"] = drive.dossiers_a_creer
        return rapport
    finally:
        DERNIER_RUN.update(
            en_cours=False,
            termine_a=datetime.now(timezone.utc).isoformat(),
            progression=None,
            rapport=rapport,
        )


async def executer_en_arriere_plan(**kwargs: Any) -> None:
    """Lance ``executer`` dans sa propre session (bouton de la page)."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            await executer(db, **kwargs)
        except Exception:  # noqa: BLE001
            log.exception("Reçus QB → Drive : run en arrière-plan échoué")


def lancer_en_arriere_plan(**kwargs: Any) -> None:
    asyncio.create_task(executer_en_arriere_plan(**kwargs))


async def executer_pour_cron(db: AsyncSession) -> Dict[str, Any]:
    """Nuit : la veille + marge (reçus joints en retard), toutes les
    entreprises prêtes, sans simulation. Idempotent (mémoire + nom)."""
    from app.services.cron_guard import claim_cron_run

    if not await claim_cron_run(db, "qbo-recus-drive", 20 * 3600):
        return {"skipped": "run trop récent (< 20 h)"}
    auj = date.today()
    r = await executer(
        db,
        depuis=auj - timedelta(days=JOURS_FENETRE_NUIT),
        jusqua=auj,
        simulation=False,
        declencheur="cron",
    )
    return {
        "ok": r.get("ok"),
        "copies": r.get("totaux", {}).get("copies"),
        "ignores": r.get("totaux", {}).get("ignores"),
        "erreurs": r.get("totaux", {}).get("erreurs"),
        "non_pretes": [x["name"] for x in r.get("non_pretes", [])],
    }


async def journal(
    db: AsyncSession, *, entreprise_id: Optional[int] = None, limit: int = 100
) -> List[Dict[str, Any]]:
    stmt = select(QboRecuDrive).order_by(QboRecuDrive.created_at.desc(), QboRecuDrive.id.desc()).limit(limit)
    if entreprise_id:
        stmt = stmt.where(QboRecuDrive.entreprise_id == entreprise_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "entreprise_id": r.entreprise_id,
            "date_recu": r.date_recu.isoformat() if r.date_recu else None,
            "fournisseur": r.fournisseur,
            "montant": float(r.montant) if r.montant is not None else None,
            "nom_fichier": r.nom_fichier,
            "txn_type": r.txn_type,
            "statut": r.statut,
            "detail": r.detail,
            "declencheur": r.declencheur,
            "drive_file_id": r.drive_file_id,
            "drive_url": f"https://drive.google.com/file/d/{r.drive_file_id}/view" if r.drive_file_id else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
