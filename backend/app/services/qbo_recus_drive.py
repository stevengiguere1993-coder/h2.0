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
import secrets
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, update
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
#: Nom canonique du dossier de chaque mois : « 01 - Janvier » … le
#: préfixe numérique garde les mois en ordre (Phil 2026-10-04).
MOIS_DOSSIER = [f"{i:02d} - {m}" for i, m in enumerate(MOIS_FR, 1)]
DOSSIER_FACTURES = "Factures"
#: Pièces sans aucune information (pas de dépense liée) : dossier au même
#: niveau que les mois, sous l'année (Phil 2026-10-04). Remplace l'ancien
#: « À classer » qui vivait dans chaque mois.
DOSSIER_NON_CLASSE = "Non classé"
DOSSIER_A_CLASSER = "À classer"  # ancien nom, migré vers « Non classé »
#: Fournisseur absent de la dépense : « ND », la date et le montant
#: restent dans le nom et le reçu est classé dans son mois.
FOURNISSEUR_INCONNU = "ND"
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
#: Nuit : on demande à QuickBooks les pièces jointes AJOUTÉES OU MODIFIÉES
#: depuis N jours (marge pour un cron raté), quelle que soit la date du
#: reçu — un reçu de janvier déposé hier est classé dans Janvier (Phil
#: 2026-10-04 : « pas besoin de rescanner 3 jours ou toute l'année »).
JOURS_PIECES_NUIT = 2
#: Ancienne fenêtre par date de transaction (conservée pour le rattrapage).
JOURS_FENETRE_NUIT = 3
DATE_MIN = date(2000, 1, 1)


def _pieces_modifiees_depuis(atts: List[Dict[str, Any]], depuis: datetime) -> List[Dict[str, Any]]:
    """Filtre local : pièces jointes dont MetaData.CreateTime ou
    LastUpdatedTime ≥ ``depuis`` (repli quand QuickBooks refuse le WHERE)."""
    out = []
    for a in atts:
        md = a.get("MetaData") or {}
        for k in ("LastUpdatedTime", "CreateTime"):
            v = md.get(k)
            if not v:
                continue
            try:
                t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            except ValueError:
                continue
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if t >= depuis:
                out.append(a)
                break
    return out

#: État du dernier run (lecture par la page) — un seul run à la fois.
DERNIER_RUN: Dict[str, Any] = {
    "en_cours": False,
    "run_id": None,
    "lance_a": None,
    "termine_a": None,
    "simulation": None,
    "declencheur": None,
    "progression": None,
    "rapport": None,
    "arret_demande": False,
}


def demander_arret() -> bool:
    """Bouton « Arrêter » : le run en cours s'interrompt proprement à la
    prochaine pièce jointe (ce qui est déjà copié reste copié)."""
    if not DERNIER_RUN.get("en_cours"):
        return False
    DERNIER_RUN["arret_demande"] = True
    return True


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


def normaliser_nom(s: Optional[str], garder_prefixe: bool = False) -> str:
    """Clé de comparaison d'un nom de dossier Drive : sans accent, sans
    casse, sans préfixe numérique « 2 - » (sauf ``garder_prefixe``, pour
    les mots-clés : « 2026 - Reçus » doit garder 2026), sans ponctuation.
    Les dossiers de Phil sont numérotés (« 1 - MGV Investissements inc »,
    « 2 - Factures ») : on doit les reconnaître sans créer un doublon."""
    t = unicodedata.normalize("NFKD", s or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.casefold().strip()
    if not garder_prefixe:
        t = re.sub(r"^\d+\s*[-–—.:)]\s*", "", t)  # « 2 - Factures » → « factures »
    t = re.sub(r"[^\w\s]+", " ", t)  # ponctuation → espace (« inc. » → « inc »)
    return " ".join(t.split())


#: Mots-clés qui désignent un dossier existant équivalent (comparés sur
#: le nom normalisé) : « 2 - Factures et reçus » vaut « Factures ».
MOTS_FACTURES = ("facture", "factures", "facturation", "recu", "recus", "depense", "depenses", "invoice", "invoices", "receipt", "receipts")
#: Mots qui signalent un dossier de RENVOI ou d'archives, pas un dossier
#: de classement (« 2026 & avant : Voir Impôts ») — jamais reconnu par
#: mot-clé (Phil 2026-10-04, simulation Immobilier Meuser 1).
MOTS_EXCLUS = ("voir", "avant", "ancien", "anciens", "anciennes", "archive", "archives", "old", "backup", "sauvegarde")
#: Au-delà de ce nombre de mots, un nom n'est plus un simple dossier de
#: classement (« 1 - Factures 2026 » = 2 mots ; « 2026 & avant : Voir Impôts » = 4).
MAX_MOTS_MOTCLE = 3
_MOTS_LIAISON = {"et", "de", "des", "du", "d", "la", "le", "les", "l", "and", "of", "the", "a", "au", "aux"}
ABREV_MOIS = {
    "Janvier": ("janv", "jan"), "Février": ("fev", "feb"), "Mars": ("mar",), "Avril": ("avr", "apr"),
    "Mai": ("may",), "Juin": ("jun",), "Juillet": ("juil", "jul"), "Août": ("aou", "aug"),
    "Septembre": ("sept", "sep"), "Octobre": ("oct",), "Novembre": ("nov",), "Décembre": ("dec",),
}


def correspond_dossier(nom_existant: Optional[str], voulu: str) -> int:
    """Score de correspondance d'un dossier existant avec le dossier voulu
    (« Factures », « 2026 », « Octobre ») : 2 = même nom normalisé,
    1 = contient le mot-clé (« 2 - Factures et reçus », « 2026 - Reçus »,
    « 10 - Octobre 2026 »), 0 = rien. Phil 2026-10-04 : « il faut que le
    système voie si un dossier peut déjà correspondre »."""
    n = normaliser_nom(nom_existant)
    v = normaliser_nom(voulu)
    if not n or not v:
        return 0
    if n == v:
        return 2
    # Mots-clés sur le nom COMPLET (préfixe gardé) : « 2026 - Reçus ».
    mots = set(normaliser_nom(nom_existant, garder_prefixe=True).split())
    # Longueur jugée sans le préfixe numérique ni les mots de liaison :
    # « 2 - Factures et reçus » = 2 mots ; « 2026 & avant : Voir Impôts » = 4.
    significatifs = [m for m in n.split() if m not in _MOTS_LIAISON]
    if len(significatifs) > MAX_MOTS_MOTCLE or (mots & set(MOTS_EXCLUS)):
        return 0
    if v == "factures":
        return 1 if (mots & set(MOTS_FACTURES)) else 0
    if v.isdigit():  # année
        # Un intervalle d'années (« 2026-2027 », « 2025 à 2026 ») est un
        # dossier d'exercice financier, pas l'année calendrier : on crée
        # un vrai « 2026 » à côté (Phil 2026-10-04, Immobilier Meuser 1).
        annees = {m for m in mots if re.fullmatch(r"(19|20)\d{2}", m)}
        if len(annees) > 1:
            return 0
        return 1 if v in mots else 0
    mois_voulu = next((m for m in MOIS_FR if normaliser_nom(m) == v), None)
    if mois_voulu:  # mois : nom complet ou abréviation, p. ex. « 10 - Oct 2026 »
        if v in mots:
            return 1
        return 1 if any(m == a or m.startswith(v[:4]) for m in mots for a in ABREV_MOIS.get(mois_voulu, ())) else 0
    return 0


def sans_prefixe_numerique(nom: Optional[str]) -> bool:
    """Vrai si le nom de dossier ne commence pas par un chiffre (« Septembre »)."""
    return not re.match(r"^\s*\d", nom or "")


_RE_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_RE_MONTANT = re.compile(r"\$?\s*(\d[\d\s]*(?:[.,]\d{1,2})?)\s*\$?")


def cle_recu(nom_fichier: Optional[str]) -> Optional[tuple]:
    """(date, fournisseur normalisé, montant) lus dans un nom de fichier,
    quelle que soit la ponctuation : « 2026-06-08: BOULET:$476.00.pdf »
    et « 2026-06-08 Boulet 476,00$.pdf » donnent la même clé → même reçu
    (règle Phil : même date, même fournisseur, exactement le même prix)."""
    if not nom_fichier:
        return None
    base = re.sub(r"\.[A-Za-z0-9]+$", "", nom_fichier.strip())
    base = re.sub(r"\s*\(\d+\)$", "", base)  # « … (2) »
    m = _RE_DATE.search(base)
    if not m:
        return None
    d = m.group(1)
    reste = base[: m.start()] + " " + base[m.end():]
    # Montant : un nombre avec $ devant ou derrière, le plus à droite.
    montant = None
    for mm in re.finditer(r"\$\s*(\d[\d\s]*(?:[.,]\d{1,2})?)|(\d[\d\s]*(?:[.,]\d{1,2})?)\s*\$", reste):
        brut = (mm.group(1) or mm.group(2) or "").replace(" ", "").replace(",", ".")
        try:
            montant = round(float(brut), 2)
            reste = reste[: mm.start()] + " " + reste[mm.end():]
        except ValueError:
            continue
    if montant is None:
        return None
    fournisseur = normaliser_nom(re.sub(r"[:;,_]+", " ", reste), garder_prefixe=True)
    return (d, fournisseur, montant)


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
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """(folder_id, url, source) du dossier Drive de l'entreprise, dans
    l'ordre : URL collée sur la fiche → lien « Documents Drive » de la
    fiche → découverte dans le dossier parent de la convention Entreprise
    (un sous-dossier qui porte le nom de l'entreprise ; le lien est alors
    enregistré pour de bon). Phil 2026-10-04 : « on devrait avoir l'URL
    du dossier partagé pour chacune des entreprises »."""
    fid = folder_id_depuis_url(getattr(e, "drive_folder_url", None))
    if fid:
        return fid, getattr(e, "drive_folder_url", None), "fiche", None
    lien = liens.get(e.id)
    if lien is not None and lien.drive_folder_id:
        return lien.drive_folder_id, url_dossier(lien.drive_folder_id), "lien", lien.drive_folder_name
    parent = getattr(convention, "parent_folder_drive_id", None) if convention else None
    if not parent or drive_user_id is None:
        return None, None, None, None
    import time as _time

    cache = _DECOUVERTE.get(e.id)
    if cache and _time.monotonic() - cache[1] < _DECOUVERTE_TTL:
        fid = cache[0]
        return (fid, url_dossier(fid), "convention", cache[2]) if fid else (None, None, None, None)
    try:
        from app.services.drive_api import FOLDER_MIME, list_folder_contents

        voulu = normaliser_nom(e.name)
        # Numéro d'entreprise (« 9520-8955 », « 9417-1287 ») : s'il est
        # dans le nom Kratos ET dans le nom du dossier, c'est le même
        # (« 3 - 9520-8955 Qc inc. (Vincent & …) »).
        numeros = set(re.findall(r"\d{4}-\d{4}", e.name or ""))
        trouve: Optional[Dict[str, Any]] = None
        token: Optional[str] = None
        for _ in range(20):
            page = await list_folder_contents(drive_user_id, db, parent, page_size=200, page_token=token)
            for f in page.get("files") or []:
                if f.get("mimeType") != FOLDER_MIME:
                    continue
                nom_f = f.get("name") or ""
                if normaliser_nom(nom_f) == voulu or (
                    numeros and numeros & set(re.findall(r"\d{4}-\d{4}", nom_f))
                ):
                    trouve = f
                    break
            token = page.get("next_page_token")
            if trouve or not token:
                break
    except Exception as exc:  # noqa: BLE001
        log.warning("Découverte du dossier Drive de %s impossible : %s", e.name, exc)
        _DECOUVERTE[e.id] = (None, _time.monotonic(), None)
        return None, None, None, None
    if trouve is None:
        _DECOUVERTE[e.id] = (None, _time.monotonic(), None)
        return None, None, None, None
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
    _DECOUVERTE[e.id] = (fid, _time.monotonic(), trouve.get("name"))
    return fid, url_dossier(fid), "convention", trouve.get("name")


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
        folder, url, source, nom_dossier = await _dossier_entreprise(db, e, liens, convention, drive_user_id)
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
                "drive_folder_name": nom_dossier,
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
        #: Dossiers EXISTANTS reconnus sous un autre nom (« Factures » →
        #: « 2 - Factures et reçus ») : affichés dans le rapport pour
        #: vérification avant la copie.
        self.dossiers_reconnus: List[str] = []
        #: Dossiers de mois renommés pour porter le préfixe numérique
        #: (« Septembre » → « 09 - Septembre ») ; en simulation : à renommer.
        self.dossiers_renommes: List[str] = []
        self.dossiers_a_renommer: List[str] = []

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
        fid, _ = await self.sous_dossier_nomme(parent_id, nom, chemin)
        return fid

    async def trouver(self, parent_id: str, nom: str) -> Optional[Dict[str, Any]]:
        """Meilleur sous-dossier EXISTANT équivalent à ``nom`` (score de
        ``correspond_dossier``), sans rien créer ; None s'il n'y en a pas."""
        from app.services.drive_api import FOLDER_MIME

        meilleur: Optional[Dict[str, Any]] = None
        meilleur_score = 0
        for f in await self.contenu(parent_id):
            if f.get("mimeType") != FOLDER_MIME:
                continue
            score = correspond_dossier(f.get("name"), nom)
            if score > meilleur_score or (
                score == meilleur_score and score > 0 and (f.get("name") or "") < (meilleur.get("name") or "")
            ):
                meilleur, meilleur_score = f, score
        return meilleur

    async def renommer_mois(self, dossier: Dict[str, Any], mois_canonique: str, chemin_parent: str) -> str:
        """Un dossier de mois sans chiffre devant (« Septembre ») prend le
        nom canonique (« 09 - Septembre ») pour rester en ordre. Retourne
        le nom (réel ou futur)."""
        from app.services.drive_api import rename_file

        reel = str(dossier.get("name") or "")
        if not sans_prefixe_numerique(reel) or reel == mois_canonique:
            return reel
        rec = f"{chemin_parent} : « {reel} » → « {mois_canonique} »"
        if self.simulation:
            if rec not in self.dossiers_a_renommer:
                self.dossiers_a_renommer.append(rec)
            return reel
        await rename_file(self.user_id, self.db, str(dossier["id"]), mois_canonique)
        dossier["name"] = mois_canonique
        self.dossiers_renommes.append(rec)
        return mois_canonique

    async def deplacer(self, fichier: Dict[str, Any], de_id: str, vers_id: str) -> None:
        from app.services.drive_api import move_file

        await move_file(self.user_id, self.db, str(fichier["id"]), vers_id, de_id)
        self._contenu[de_id] = [f for f in self._contenu.get(de_id, []) if f.get("id") != fichier.get("id")]
        fichier["parents"] = [vers_id]
        self._ajouter(vers_id, fichier)

    async def sous_dossier_nomme(self, parent_id: str, nom: str, chemin: str) -> tuple:
        """(id, nom réel) du sous-dossier équivalent à ``nom`` dans
        ``parent_id`` (correspondance par score) ; créé s'il manque.
        (None, nom) en simulation quand il faudrait le créer."""
        from app.services.drive_api import create_folder

        meilleur = await self.trouver(parent_id, nom)
        if meilleur is not None:
            reel = str(meilleur.get("name") or nom)
            if nom in MOIS_DOSSIER:
                reel = await self.renommer_mois(meilleur, nom, chemin.rsplit(" / ", 1)[0])
            if normaliser_nom(reel) != normaliser_nom(nom):
                rec = f"{chemin} → « {reel} »"
                if rec not in self.dossiers_reconnus:
                    self.dossiers_reconnus.append(rec)
            return str(meilleur["id"]), reel
        if self.simulation:
            if chemin not in self.dossiers_a_creer:
                self.dossiers_a_creer.append(chemin)
            return None, nom
        cree = await create_folder(self.user_id, self.db, parent_id, nom)
        self._ajouter(parent_id, cree)
        self._contenu[str(cree["id"])] = []
        self.dossiers_crees.append(chemin)
        return str(cree["id"]), nom

    async def dossier_annee(self, racine_id: str, nom_entreprise: str, annee: int) -> tuple:
        """(id, chemin réel) du dossier Factures / <année> (créé au besoin)."""
        fid, reel = await self.sous_dossier_nomme(racine_id, DOSSIER_FACTURES, f"{nom_entreprise} / {DOSSIER_FACTURES}")
        chemin = f"{nom_entreprise} / {reel}"
        if fid is None:
            return None, chemin
        fid, reel = await self.sous_dossier_nomme(fid, str(annee), f"{chemin} / {annee}")
        return fid, f"{chemin} / {reel}"

    async def dossier_mois(self, racine_id: str, nom_entreprise: str, d: date, non_classe: bool = False) -> Optional[str]:
        """Dossier du mois « 10 - Octobre » (créé au besoin), ou « Non
        classé » au même niveau que les mois pour une pièce sans dépense
        liée. Les chemins du rapport portent les VRAIS noms des dossiers
        reconnus (« 2 - Factures »), pas le libellé générique (Phil 2026-10-04)."""
        fid, chemin = await self.dossier_annee(racine_id, nom_entreprise, d.year)
        if fid is None:
            return None
        nom = DOSSIER_NON_CLASSE if non_classe else MOIS_DOSSIER[d.month - 1]
        fid, _ = await self.sous_dossier_nomme(fid, nom, f"{chemin} / {nom}")
        return fid

    async def migrer_a_classer(self, racine_id: str, nom_entreprise: str, rapport: Dict[str, Any]) -> List[tuple]:
        """Ancien classement : « À classer » dans chaque mois. Nouveau :
        « Non classé » sous l'année (Phil 2026-10-04). Déplace les fichiers
        trouvés, met le dossier vide à la corbeille, numérote les mois
        sans chiffre. Ne crée rien si Factures / année n'existent pas.
        Retourne [(file_id, nouveau_dossier_id)] pour la mémoire."""
        from app.services.drive_api import FOLDER_MIME, trash_file

        deplaces: List[tuple] = []
        factures = await self.trouver(racine_id, DOSSIER_FACTURES)
        if factures is None:
            return deplaces
        chemin_f = f"{nom_entreprise} / {factures.get('name')}"
        for an in list(await self.contenu(str(factures["id"]))):
            if an.get("mimeType") != FOLDER_MIME:
                continue
            m_an = re.search(r"\b((?:19|20)\d{2})\b", an.get("name") or "")
            if not m_an or correspond_dossier(an.get("name"), m_an.group(1)) == 0:
                continue
            chemin_an = f"{chemin_f} / {an.get('name')}"
            non_classe_id: Optional[str] = None
            for mois in list(await self.contenu(str(an["id"]))):
                if mois.get("mimeType") != FOLDER_MIME:
                    continue
                canon = next((c for c in MOIS_DOSSIER if correspond_dossier(mois.get("name"), c) > 0), None)
                if canon is None:
                    continue
                nom_mois = await self.renommer_mois(mois, canon, chemin_an)
                for sous in list(await self.contenu(str(mois["id"]))):
                    if sous.get("mimeType") != FOLDER_MIME or correspond_dossier(sous.get("name"), DOSSIER_A_CLASSER) != 2:
                        continue
                    chemin_ac = f"{chemin_an} / {nom_mois} / {sous.get('name')}"
                    fichiers = [f for f in await self.contenu(str(sous["id"])) if f.get("mimeType") != FOLDER_MIME]
                    sous_dossiers = [f for f in await self.contenu(str(sous["id"])) if f.get("mimeType") == FOLDER_MIME]
                    if self.simulation:
                        rapport["infos"].append(
                            f"« {chemin_ac} » : {len(fichiers)} fichier(s) à déplacer vers « {DOSSIER_NON_CLASSE} »"
                            + (" puis dossier à mettre à la corbeille." if not sous_dossiers else ".")
                        )
                        rapport["non_classes_deplaces"] += len(fichiers)
                        continue
                    if fichiers and non_classe_id is None:
                        non_classe_id, _ = await self.sous_dossier_nomme(
                            str(an["id"]), DOSSIER_NON_CLASSE, f"{chemin_an} / {DOSSIER_NON_CLASSE}"
                        )
                    for f in fichiers:
                        await self.deplacer(f, str(sous["id"]), str(non_classe_id))
                        deplaces.append((str(f["id"]), str(non_classe_id)))
                    rapport["non_classes_deplaces"] += len(fichiers)
                    if not sous_dossiers:
                        await trash_file(self.user_id, self.db, str(sous["id"]))
                        self._contenu[str(mois["id"])] = [
                            x for x in self._contenu.get(str(mois["id"]), []) if x.get("id") != sous.get("id")
                        ]
                    rapport["infos"].append(
                        f"« {chemin_ac} » : {len(fichiers)} fichier(s) déplacé(s) vers « {DOSSIER_NON_CLASSE} »"
                        + (" ; dossier mis à la corbeille." if not sous_dossiers else ".")
                    )
        return deplaces

    async def fichier_existant(self, folder_id: str, nom: str) -> Optional[str]:
        """Fichier déjà présent dans le dossier du mois : même nom, sinon
        même reçu (date + fournisseur + montant lus dans le nom, toute
        ponctuation confondue : « 2026-06-08: BOULET:$476.00.pdf »)."""
        voulu = nom.strip().casefold()
        for f in await self.contenu(folder_id):
            n = (f.get("name") or "").strip()
            if n.casefold() == voulu:
                return str(f["id"])
        # « … (2).pdf » = 2e pièce jointe de la MÊME dépense : volontairement
        # distincte de la 1re → nom exact seulement, pas la clé.
        if re.search(r"\(\d+\)\.[A-Za-z0-9]+$", nom.strip()):
            return None
        cle = cle_recu(nom)
        if cle is None:
            return None
        for f in await self.contenu(folder_id):
            if f.get("mimeType") == "application/vnd.google-apps.folder":
                continue
            if cle_recu(f.get("name")) == cle:
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
        "non_classes": 0,
        "non_classes_deplaces": 0,
        "ignores_deja_traites": 0,
        "ignores_drive": 0,
        "hors_periode": 0,
        "non_recu": 0,
        "hors_depenses": 0,
        "txn_supprimees": 0,
        "erreurs": 0,
        "messages": [],
        "infos": [],
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
    pieces_depuis: Optional[datetime] = None,
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

    # Ancien classement « À classer » dans les mois → « Non classé » sous
    # l'année, et mois numérotés. Fait avant la copie, à chaque run.
    try:
        deplaces = await drive.migrer_a_classer(racine, e["name"], rapport)
        if deplaces and not simulation:
            for file_id, dossier_id in deplaces:
                await db.execute(
                    update(QboRecuDrive)
                    .where(QboRecuDrive.drive_file_id == file_id)
                    .values(drive_folder_id=dossier_id)
                )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        rapport["erreurs"] += 1
        rapport["messages"].append(f"Drive : migration des « À classer » impossible ({str(exc)[:160]}).")

    try:
        if pieces_depuis is not None:
            # Seulement ce qui a bougé dans QuickBooks depuis la date :
            # filtre serveur si QB l'accepte, sinon liste complète filtrée ici.
            borne = pieces_depuis.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            try:
                atts = await qbo.query_all(
                    f"SELECT * FROM attachable WHERE MetaData.LastUpdatedTime >= '{borne}'"
                )
            except QuickBooksError:
                atts = _pieces_modifiees_depuis(await qbo.query_all("SELECT * FROM attachable"), pieces_depuis)
        else:
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
        if DERNIER_RUN.get("arret_demande"):
            rapport["messages"].append("Arrêté à la demande de l'utilisateur.")
            rapport["arrete"] = True
            break
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

        # Pièce jointe sans transaction liée (aucune info) → « Non classé »
        # de l'année de dépôt, au même niveau que les mois.
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
                    "non_classe": True,
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
                        msg = str(exc)
                        if re.search(r"inactive|introuvable|not found|deleted|supprim", msg, re.I):
                            # Dépense supprimée / rendue inactive dans QuickBooks :
                            # la pièce jointe subsiste mais n'a plus de dépense.
                            # Ce n'est pas une erreur (simulation Phil 2026-10-04).
                            rapport["txn_supprimees"] += 1
                        else:
                            rapport["erreurs"] += 1
                            rapport["messages"].append(f"{t} {v} : lecture impossible ({msg[:120]}).")
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
                        "non_classe": False,
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
                dossier = await drive.dossier_mois(racine, e["name"], c["date"], non_classe=c["non_classe"])
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
                run_id=DERNIER_RUN.get("run_id"),
            )
            if len(rapport["apercu"]) < 300:
                rapport["apercu"].append(
                    {
                        "date": c["date"].isoformat(),
                        "fournisseur": c["fournisseur"],
                        "montant": c["montant"],
                        "nom": c["nom"],
                        "dossier": f"{DOSSIER_FACTURES}/{c['date'].year}/"
                        + (DOSSIER_NON_CLASSE if c["non_classe"] else MOIS_DOSSIER[c["date"].month - 1]),
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
            if c["non_classe"]:
                rapport["non_classes"] += 1
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
    pieces_depuis_jours: Optional[int] = None,
) -> Dict[str, Any]:
    """Copie (ou simule) les reçus de chaque entreprise prête. Renvoie
    le rapport ; il est aussi gardé dans ``DERNIER_RUN``."""
    from app.services.drive_auto_upload_dispatcher import resolve_drive_owner_user_id

    pieces_depuis: Optional[datetime] = None
    if pieces_depuis_jours is not None:
        # Mode « ce qui a bougé dans QuickBooks » : aucune limite sur la
        # date du reçu (un reçu de janvier déposé hier compte).
        pieces_depuis = datetime.now(timezone.utc) - timedelta(days=max(1, pieces_depuis_jours))
        depuis = depuis or DATE_MIN
        jusqua = jusqua or (date.today() + timedelta(days=1))
    depuis = depuis or DEBUT_PAR_DEFAUT
    jusqua = jusqua or date.today()
    if DERNIER_RUN.get("en_cours"):
        return {"ok": False, "erreur": "Un run est déjà en cours."}
    run_id = secrets.token_hex(6)
    DERNIER_RUN.update(
        en_cours=True,
        run_id=run_id,
        lance_a=datetime.now(timezone.utc).isoformat(),
        termine_a=None,
        simulation=simulation,
        declencheur=declencheur,
        progression=None,
        rapport=None,
        arret_demande=False,
    )
    rapport: Dict[str, Any] = {
        "ok": True,
        "run_id": run_id,
        "simulation": simulation,
        "declencheur": declencheur,
        "depuis": depuis.isoformat(),
        "jusqua": jusqua.isoformat(),
        "pieces_depuis": pieces_depuis.isoformat() if pieces_depuis else None,
        "entreprises": [],
        "non_pretes": [],
        "dossiers_crees": [],
        "dossiers_a_creer": [],
        "dossiers_reconnus": [],
        "dossiers_renommes": [],
        "dossiers_a_renommer": [],
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
                    declencheur=declencheur, rapport=r, pieces_depuis=pieces_depuis,
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
            if r.get("arrete"):
                rapport["arrete"] = True
                break
        rapport["dossiers_crees"] = drive.dossiers_crees
        rapport["dossiers_a_creer"] = drive.dossiers_a_creer
        rapport["dossiers_reconnus"] = drive.dossiers_reconnus
        rapport["dossiers_renommes"] = drive.dossiers_renommes
        rapport["dossiers_a_renommer"] = drive.dossiers_a_renommer
        return rapport
    finally:
        DERNIER_RUN.update(
            en_cours=False,
            termine_a=datetime.now(timezone.utc).isoformat(),
            progression=None,
            rapport=rapport,
            arret_demande=False,
        )


async def runs_recents(db: AsyncSession, limit: int = 10) -> List[Dict[str, Any]]:
    """Imports réels récents (un par run_id) : pour « Annuler cet import »."""
    rows = (
        await db.execute(
            select(
                QboRecuDrive.run_id,
                QboRecuDrive.declencheur,
                func.min(QboRecuDrive.created_at),
                func.count(QboRecuDrive.id),
                func.count(QboRecuDrive.drive_file_id),
            )
            .where(QboRecuDrive.run_id.is_not(None))
            .group_by(QboRecuDrive.run_id, QboRecuDrive.declencheur)
            .order_by(func.min(QboRecuDrive.created_at).desc())
            .limit(limit)
        )
    ).all()
    out = []
    for run_id, decl, debut, n, n_fichiers in rows:
        copies = (
            await db.execute(
                select(func.count(QboRecuDrive.id)).where(
                    QboRecuDrive.run_id == run_id, QboRecuDrive.statut == "copie"
                )
            )
        ).scalar_one()
        out.append(
            {
                "run_id": run_id,
                "declencheur": decl,
                "debut": debut.isoformat() if debut else None,
                "lignes": int(n),
                "copies": int(copies or 0),
            }
        )
    return out


async def annuler_run(
    db: AsyncSession, run_id: str, *, user_id: Optional[int] = None
) -> Dict[str, Any]:
    """« Annuler cet import » : les fichiers copiés par ce run sont mis à la
    corbeille du Drive (récupérables 30 jours) et la mémoire du run est
    effacée, pour pouvoir recommencer proprement. Les dossiers créés
    restent (vides, sans effet)."""
    from app.services.drive_api import trash_file
    from app.services.drive_auto_upload_dispatcher import resolve_drive_owner_user_id

    if DERNIER_RUN.get("en_cours"):
        return {"ok": False, "erreur": "Attends la fin (ou l'arrêt) du run en cours."}
    rows = (
        await db.execute(select(QboRecuDrive).where(QboRecuDrive.run_id == run_id))
    ).scalars().all()
    if not rows:
        return {"ok": False, "erreur": "Import introuvable (déjà annulé ?)."}
    owner = await resolve_drive_owner_user_id(db, user_id)
    corbeille = 0
    erreurs: List[str] = []
    for r in rows:
        if r.statut == "copie" and r.drive_file_id and owner is not None:
            try:
                await trash_file(owner, db, r.drive_file_id)
                corbeille += 1
            except Exception as exc:  # noqa: BLE001
                erreurs.append(f"{r.nom_fichier} : {str(exc)[:120]}")
                continue
        await db.delete(r)
    await db.commit()
    return {
        "ok": True,
        "run_id": run_id,
        "fichiers_corbeille": corbeille,
        "lignes_effacees": len(rows) - len(erreurs),
        "erreurs": erreurs,
    }


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
    """Nuit : les pièces jointes AJOUTÉES OU MODIFIÉES dans QuickBooks
    depuis 2 jours (quelle que soit la date du reçu), toutes les
    entreprises prêtes, sans simulation. Idempotent (mémoire + nom)."""
    from app.services.cron_guard import claim_cron_run

    if not await claim_cron_run(db, "qbo-recus-drive", 20 * 3600):
        return {"skipped": "run trop récent (< 20 h)"}
    r = await executer(
        db,
        simulation=False,
        declencheur="cron",
        pieces_depuis_jours=JOURS_PIECES_NUIT,
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
