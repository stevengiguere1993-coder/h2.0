"""Paiements fournisseurs par dépôt direct Desjardins ou virement Interac
(Comptabilité).

Demande Steven (2026-10-04) : une technicienne comptable fait les
paiements des entreprises sans accès aux comptes bancaires et sans
pouvoir détourner de fonds. Kratos reproduit Plooto :

1. Préparer (accès à la page Paiements) : choisir les factures ouvertes
   lues dans le QuickBooks de l'entreprise, former un lot, saisir les
   coordonnées bancaires d'un fournisseur, soumettre.
2. Approuver (capacité ``paiements.approuver`` + double authentification) :
   jamais la personne qui a préparé le lot ou saisi les coordonnées. Le
   nombre d'approbateurs exigé est un réglage de l'entreprise (1 ou 2).
3. Créer le fichier de dépôt direct (norme 005) : un approbateur, avec sa
   double authentification. Il le transmet lui-même dans AccèsD Affaires ;
   la technicienne n'a jamais ce droit chez Desjardins.
4. Inscrire les paiements dans QuickBooks (un paiement de facture par
   fournisseur), une fois le fichier transmis.

Virements Interac (Steven, 2026-10-04 : « parfois, nous devons faire des
virements Interac ») : un lot peut se payer par Interac plutôt que par
dépôt direct. Desjardins n'accepte pas de fichier pour Interac : après
l'approbation, un approbateur prépare l'envoi (double authentification,
soldes relus dans QuickBooks), envoie chaque virement lui-même dans
AccèsD Affaires au destinataire approuvé, puis l'indique dans Kratos. Le
destinataire (courriel ou cellulaire) suit la même règle qu'un compte
bancaire : saisi par l'une, approuvé par une autre.

Paiement automatique (Steven, 2026-10-05 : « l'idée est de ne pas faire
les virements nous-mêmes. Juste approuver et que tout se fasse par la
suite ! ») : une entreprise qui l'active dans ses réglages fait payer ses
lots par VoPay, sans fichier ni virement dans AccèsD. À la dernière
approbation, le lot est confié à ``paiements_auto`` : prélèvement du total
dans le compte Desjardins de l'entreprise le jour du lot, paiement de
chaque fournisseur, puis inscription dans QuickBooks.

Garde-fous : coordonnées bancaires chiffrées, jamais renvoyées en clair
(sauf dans le fichier) ; une coordonnée n'est utilisée qu'approuvée ; si
elle change après la soumission, le fichier (ou l'envoi Interac) est
refusé ; les soldes sont relus dans QuickBooks avant le fichier ou
l'envoi (pas de double paiement) ; le connecteur IA ne peut rien faire
ici (chemin bloqué dans ``mcp_server``) ; chaque geste est inscrit au
journal des paiements.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.models.entreprise import Entreprise
from app.models.paiement_fournisseur import (
    FournisseurCompteBancaire,
    LotPaiement,
    LotPaiementApprobation,
    LotPaiementLigne,
    PaiementEvenement,
    PaiementOperation,
    PaiementReglage,
    Utilisateur2FA,
)
from app.models.user import User
from app.services import cpa005, totp
from app.services.permissions_service import user_has_capability
from app.services.qbo_recus_drive import SCOPE_CONSTRUCTION
from app.services.recu_qbo_saisie import (
    SaisieErreur,
    _entreprise_connectee,
    entreprises as entreprises_qbo,
    lien_qbo,
    message_qbo,
)
from app.services.secret_vault import VaultNotConfigured, decrypt_secret, encrypt_secret

log = logging.getLogger(__name__)

TZ = ZoneInfo("America/Toronto")
CAPACITE_APPROUVER = "paiements.approuver"
#: Après un code valide, les gestes sensibles passent sans nouveau code.
CONFIRMATION_2FA = timedelta(minutes=5)
#: Norme 005 : la date du dépôt ne peut dépasser la date de création de 14 jours.
JOURS_MAX_AVANCE = 14
#: Lien des notifications (onglet Paiements de Comptabilité).
HREF = "/entreprises/comptabilite/paiements"

#: Façons de payer : fichier de dépôt direct, ou virements Interac
#: envoyés un à un dans AccèsD Affaires.
MODES = ("depot_direct", "interac")
#: Desjardins limite les virements Interac envoyés par une entreprise à
#: 25 000 $ par virement et par période de 24 heures (AccèsD Affaires).
LIMITE_INTERAC_CENTS = 2_500_000

#: Paiement automatique : « prelevement » (compte de l'entreprise en cours
#: de prélèvement), « envoi » (fournisseurs en cours de paiement) et
#: « echec » (prélèvement refusé, aucun argent n'a bougé).
STATUTS_ACTIFS = (
    "brouillon", "soumis", "approuve", "fichier_cree", "a_envoyer", "transmis",
    "prelevement", "envoi", "echec",
)
LIBELLES_STATUT = {
    "brouillon": "Brouillon",
    "soumis": "À approuver",
    "approuve": "Approuvé",
    "fichier_cree": "Fichier créé",
    "a_envoyer": "Virements à envoyer",
    "transmis": "Transmis à Desjardins",
    "paye": "Payé",
    "refuse": "Refusé",
    "annule": "Annulé",
    "prelevement": "Prélèvement en cours",
    "envoi": "Paiements en cours",
    "echec": "Prélèvement refusé",
}
LIBELLES_STATUT_INTERAC = {**LIBELLES_STATUT, "transmis": "Virements envoyés"}
LIBELLES_STATUT_AUTO = {
    **LIBELLES_STATUT,
    "approuve": "Paiement prévu",
    "transmis": "Fournisseurs payés",
}
#: Lots payés automatiquement que Kratos ne peut plus arrêter : l'argent
#: est en route.
STATUTS_AUTO_EN_ROUTE = ("prelevement", "envoi")


# ──────────────────────────────────────────────────────────────────────
# Erreurs et petits outils
# ──────────────────────────────────────────────────────────────────────


class PaiementErreur(Exception):
    """Erreur présentable telle quelle à l'utilisateur."""

    def __init__(self, message: str, statut: int = 422, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.statut = statut
        self.extra = extra


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite (tests) rend des dates sans fuseau : ce sont des UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    v = _utc(dt)
    return v.isoformat() if v else None


def _aujourdhui() -> date:
    return _maintenant().astimezone(TZ).date()


def cents(montant: Any) -> int:
    try:
        d = Decimal(str(montant if montant is not None else 0))
    except InvalidOperation:
        return 0
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dollars(valeur_cents: int) -> float:
    return round(int(valeur_cents) / 100, 2)


def _argent(valeur_cents: int) -> str:
    entier, reste = divmod(int(valeur_cents), 100)
    return f"{entier:,}".replace(",", " ") + f",{reste:02d} $"


def _date_lisible(jour: date) -> str:
    mois = [
        "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre",
    ]
    return f"{jour.day} {mois[jour.month - 1]} {jour.year}"


def _jour_qbo(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _jours_ouvrables_apres(jour: date, n: int) -> date:
    d = jour
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def premiere_date_possible(maintenant: Optional[datetime] = None) -> date:
    """Desjardins doit recevoir le fichier au plus tard à midi, deux jours
    ouvrables avant la date du dépôt. Les jours fériés ne sont pas comptés."""
    local = (maintenant or _maintenant()).astimezone(TZ)
    jour = local.date()
    if jour.weekday() >= 5:
        # Reçu la fin de semaine = reçu lundi matin.
        while jour.weekday() >= 5:
            jour += timedelta(days=1)
        return _jours_ouvrables_apres(jour, 2)
    return _jours_ouvrables_apres(jour, 2 if local.hour < 12 else 3)


def _verifier_date_depot(jour: date, *, maintenant: Optional[datetime] = None) -> None:
    if jour.weekday() >= 5:
        raise PaiementErreur("La date du dépôt doit être un jour ouvrable (lundi à vendredi).")
    premiere = premiere_date_possible(maintenant)
    if jour < premiere:
        raise PaiementErreur(
            "Desjardins doit recevoir le fichier au plus tard à midi, deux jours "
            f"ouvrables avant le dépôt : choisis le {_date_lisible(premiere)} ou après."
        )
    limite = (maintenant or _maintenant()).astimezone(TZ).date() + timedelta(days=JOURS_MAX_AVANCE)
    if jour > limite:
        raise PaiementErreur(
            f"Le dépôt ne peut pas être prévu plus de {JOURS_MAX_AVANCE} jours après "
            f"la création du fichier (au plus tard le {_date_lisible(limite)})."
        )


def _verifier_date(mode: str, jour: date, *, auto: bool = False) -> None:
    """Dépôt direct : règles de Desjardins pour le fichier. Interac, ou
    paiement automatique (Kratos lance le paiement ce jour-là) : la date ne
    peut pas être passée."""
    if mode != "interac" and not auto:
        _verifier_date_depot(jour)
    elif jour < _aujourdhui():
        raise PaiementErreur(
            "La date du paiement est passée : choisis aujourd'hui ou plus tard."
            if auto
            else "La date prévue de l'envoi est passée : choisis aujourd'hui ou plus tard."
        )


def _quand(lot: LotPaiement) -> str:
    if lot.mode == "interac":
        return f"virements Interac prévus le {_date_lisible(lot.date_paiement)}"
    return f"dépôt le {_date_lisible(lot.date_paiement)}"


_COURRIEL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def destinataire_interac(valeur: Any) -> str:
    """Courriel (mis en minuscules) ou numéro de cellulaire canadien
    (10 chiffres, le 1 du début retiré)."""
    s = str(valeur or "").strip()
    if "@" in s:
        s = s.lower()
        if len(s) > 254 or not _COURRIEL.fullmatch(s):
            raise ValueError("Courriel du destinataire Interac invalide.")
        return s
    chiffres = re.sub(r"\D", "", s)
    if len(chiffres) == 11 and chiffres.startswith("1"):
        chiffres = chiffres[1:]
    if len(chiffres) != 10:
        raise ValueError(
            "Destinataire Interac : un courriel, ou un numéro de cellulaire à 10 chiffres."
        )
    return chiffres


_PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
_NOMS_PROVINCES = {
    "quebec": "QC", "pq": "QC", "que": "QC", "ontario": "ON", "alberta": "AB",
    "colombie-britannique": "BC", "british columbia": "BC", "manitoba": "MB",
    "nouveau-brunswick": "NB", "new brunswick": "NB", "terre-neuve-et-labrador": "NL",
    "newfoundland and labrador": "NL", "nouvelle-ecosse": "NS", "nova scotia": "NS",
    "territoires du nord-ouest": "NT", "northwest territories": "NT", "nunavut": "NU",
    "ile-du-prince-edouard": "PE", "prince edward island": "PE", "saskatchewan": "SK",
    "yukon": "YT",
}
_CODE_POSTAL = re.compile(r"[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]\d[ABCEGHJ-NPRSTV-Z]\d")


def province_canadienne(valeur: Any) -> Optional[str]:
    """« QC », « Québec », « Quebec »… → code de deux lettres (ou None)."""
    s = unicodedata.normalize("NFKD", str(valeur or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[\s.]+", " ", s).strip().lower()
    compact = s.replace(" ", "")
    if compact.upper() in _PROVINCES:
        return compact.upper()
    return _NOMS_PROVINCES.get(s) or _NOMS_PROVINCES.get(s.replace(" ", "-")) or _NOMS_PROVINCES.get(compact)


def code_postal_canadien(valeur: Any) -> Optional[str]:
    """« h2x1y4 » → « H2X 1Y4 » (ou None si ce n'est pas un code postal)."""
    s = re.sub(r"[\s\-]", "", str(valeur or "")).upper()
    return f"{s[:3]} {s[3:]}" if _CODE_POSTAL.fullmatch(s) else None


def destinataire_lisible(destinataire: Optional[str]) -> str:
    d = destinataire or ""
    if len(d) == 10 and d.isdigit():
        return f"{d[:3]} {d[3:6]}-{d[6:]}"
    return d or "—"


async def _noms(db: AsyncSession, ids: Iterable[Optional[int]]) -> Dict[int, str]:
    uniques = sorted({i for i in ids if i})
    if not uniques:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(uniques)))).scalars().all()
    return {u.id: u.display_name for u in rows}


async def _evenement(
    db: AsyncSession,
    action: str,
    *,
    user: Optional[User] = None,
    entreprise_id: Optional[int] = None,
    lot_id: Optional[int] = None,
    compte_id: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    db.add(
        PaiementEvenement(
            action=action,
            user_id=user.id if user else None,
            entreprise_id=entreprise_id,
            lot_id=lot_id,
            compte_id=compte_id,
            detail=detail,
        )
    )


async def _entreprise_qbo(db: AsyncSession, entreprise_id: int) -> Tuple[Entreprise, str, Dict[str, Any]]:
    try:
        return await _entreprise_connectee(db, entreprise_id)
    except SaisieErreur as exc:
        raise PaiementErreur(exc.message, exc.statut) from exc


async def _entreprise(db: AsyncSession, entreprise_id: int) -> Entreprise:
    e = await db.get(Entreprise, entreprise_id)
    if e is None or not e.is_active:
        raise PaiementErreur("Entreprise introuvable.", 404)
    return e


def _qbo(scope: str) -> Any:
    # Import local : les tests remplacent ``get_qbo`` à la source.
    from app.integrations.quickbooks import get_qbo

    return get_qbo(scope)


def _erreur_qbo(exc: Exception) -> PaiementErreur:
    return PaiementErreur(f"QuickBooks ne répond pas : {message_qbo(exc)}", 502)


def _lien_paiement_qbo(etat: Dict[str, Any], txn_id: Optional[str]) -> Optional[str]:
    if not txn_id:
        return None
    hote = (
        "https://app.sandbox.qbo.intuit.com"
        if (etat.get("environment") or "").lower() == "sandbox"
        else "https://app.qbo.intuit.com"
    )
    url = f"{hote}/app/billpayment?txnId={txn_id}"
    if etat.get("realm_id"):
        url += f"&deeplinkcompanyid={etat['realm_id']}"
    return url


# ──────────────────────────────────────────────────────────────────────
# Double authentification
# ──────────────────────────────────────────────────────────────────────


async def _ligne_2fa(db: AsyncSession, user_id: int) -> Optional[Utilisateur2FA]:
    return (
        await db.execute(select(Utilisateur2FA).where(Utilisateur2FA.user_id == user_id))
    ).scalar_one_or_none()


def _secret_2fa(ligne: Utilisateur2FA) -> str:
    try:
        return decrypt_secret(ligne.secret_chiffre)
    except (VaultNotConfigured, ValueError) as exc:
        raise PaiementErreur(
            "La clé de chiffrement de Kratos est absente ou a changé : la double "
            "authentification ne peut pas être vérifiée.",
            503,
        ) from exc


def _mot_de_passe_ok(user: User, mot_de_passe: str) -> bool:
    try:
        return bool(mot_de_passe) and verify_password(mot_de_passe, user.hashed_password or "")
    except Exception:  # noqa: BLE001 — empreinte illisible = refus
        return False


async def etat_2fa(db: AsyncSession, user: User) -> Dict[str, Any]:
    ligne = await _ligne_2fa(db, user.id)
    actif = bool(ligne and ligne.actif)
    jusqu = _utc(ligne.confirme_jusqu_a) if ligne else None
    return {
        "actif": actif,
        "active_le": _iso(ligne.active_le) if ligne and actif else None,
        "confirme_jusqu_a": jusqu.isoformat() if actif and jusqu and jusqu > _maintenant() else None,
    }


async def debut_2fa(db: AsyncSession, user: User, mot_de_passe: str) -> Dict[str, Any]:
    """Nouvelle clé à scanner. Le mot de passe est redemandé : une session
    volée (ou le connecteur IA) ne peut pas s'inscrire à la place de la
    personne et obtenir la clé."""
    if not _mot_de_passe_ok(user, mot_de_passe):
        raise PaiementErreur("Mot de passe incorrect.", 403)
    ligne = await _ligne_2fa(db, user.id)
    if ligne is not None and ligne.actif:
        raise PaiementErreur("La double authentification est déjà active.", 409)
    secret = totp.nouveau_secret()
    try:
        chiffre = encrypt_secret(secret)
    except VaultNotConfigured as exc:
        raise PaiementErreur(
            "Aucune clé de chiffrement n'est configurée sur le serveur : la double "
            "authentification ne peut pas être activée.",
            503,
        ) from exc
    if ligne is None:
        db.add(Utilisateur2FA(user_id=user.id, secret_chiffre=chiffre, actif=False))
    else:
        ligne.secret_chiffre = chiffre
        ligne.dernier_pas = None
        ligne.confirme_jusqu_a = None
    await db.commit()
    lien = totp.uri(secret, user.email)
    return {"secret": secret, "uri": lien, "qr": totp.qr_svg(lien)}


async def activer_2fa(db: AsyncSession, user: User, code: str) -> Dict[str, Any]:
    ligne = await _ligne_2fa(db, user.id)
    if ligne is None:
        raise PaiementErreur("Affiche d'abord le code QR à scanner.", 409)
    if ligne.actif:
        raise PaiementErreur("La double authentification est déjà active.", 409)
    pas = totp.verifier(_secret_2fa(ligne), code)
    if pas is None:
        raise PaiementErreur(
            "Code invalide. Tape le code à 6 chiffres affiché par l'application "
            "(l'heure du téléphone doit être à jour)."
        )
    maintenant = _maintenant()
    ligne.actif = True
    ligne.active_le = maintenant
    ligne.dernier_pas = pas
    ligne.confirme_jusqu_a = maintenant + CONFIRMATION_2FA
    await _evenement(db, "2fa_activee", user=user)
    await db.commit()
    return await etat_2fa(db, user)


async def desactiver_2fa(db: AsyncSession, user: User, mot_de_passe: str, code: str) -> Dict[str, Any]:
    if not _mot_de_passe_ok(user, mot_de_passe):
        raise PaiementErreur("Mot de passe incorrect.", 403)
    ligne = await _ligne_2fa(db, user.id)
    if ligne is None or not ligne.actif:
        raise PaiementErreur("La double authentification n'est pas active.", 409)
    if totp.verifier(_secret_2fa(ligne), code, dernier_pas=ligne.dernier_pas) is None:
        raise PaiementErreur("Code de double authentification invalide ou déjà utilisé.", 403)
    await db.delete(ligne)
    await _evenement(db, "2fa_desactivee", user=user)
    await db.commit()
    return {"actif": False, "active_le": None, "confirme_jusqu_a": None}


async def exiger_2fa(db: AsyncSession, user: User, code: Optional[str]) -> None:
    """Geste sensible : double authentification active, et un code valide
    (ou un code valide il y a moins de 5 minutes)."""
    ligne = await _ligne_2fa(db, user.id)
    if ligne is None or not ligne.actif:
        raise PaiementErreur(
            "Active d'abord la double authentification (onglet Sécurité).",
            403,
            deux_facteurs="a_activer",
        )
    maintenant = _maintenant()
    if not code:
        jusqu = _utc(ligne.confirme_jusqu_a)
        if jusqu and jusqu > maintenant:
            return
        raise PaiementErreur(
            "Code de double authentification requis.", 428, deux_facteurs="requis"
        )
    pas = totp.verifier(_secret_2fa(ligne), code, dernier_pas=ligne.dernier_pas)
    if pas is None:
        raise PaiementErreur(
            "Code de double authentification invalide ou déjà utilisé.",
            403,
            deux_facteurs="invalide",
        )
    ligne.dernier_pas = pas
    ligne.confirme_jusqu_a = maintenant + CONFIRMATION_2FA
    await db.flush()


async def peut_approuver(db: AsyncSession, user: User) -> bool:
    return await user_has_capability(db, user, CAPACITE_APPROUVER)


async def moi(db: AsyncSession, user: User) -> Dict[str, Any]:
    return {
        "user_id": user.id,
        "peut_approuver": await peut_approuver(db, user),
        "deux_facteurs": await etat_2fa(db, user),
    }


async def _approbateurs(db: AsyncSession, exclus: Iterable[Optional[int]]) -> List[int]:
    """Comptes actifs qui ont la capacité d'approuver (hors ``exclus``)."""
    sans = {i for i in exclus if i}
    users = (await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
    return [u.id for u in users if u.id not in sans and await peut_approuver(db, u)]


async def _notifier(db: AsyncSession, user_ids: Iterable[Optional[int]], titre: str, corps: str) -> None:
    """Cloche + notification poussée ; jamais bloquant."""
    from app.services.notifications import notify

    for uid in sorted({i for i in user_ids if i}):
        try:
            await notify(db, user_id=uid, kind="paiements", title=titre, body=corps, href=HREF)
        except Exception:  # noqa: BLE001
            log.exception("Notification paiements impossible (user %s)", uid)


# ──────────────────────────────────────────────────────────────────────
# Entreprises et réglages du dépôt direct
# ──────────────────────────────────────────────────────────────────────


def _manque_fichier(r: Optional[PaiementReglage]) -> List[str]:
    if r is None:
        return ["numéro d'organisme", "nom court", "nom long", "compte bancaire de l'entreprise"]
    manque = []
    if not r.numero_organisme:
        manque.append("numéro d'organisme")
    if not r.nom_court:
        manque.append("nom court")
    if not r.nom_long:
        manque.append("nom long")
    if not (r.retour_institution and r.retour_transit and r.retour_compte):
        manque.append("compte bancaire de l'entreprise")
    return manque


def auto_actif(r: Optional[PaiementReglage]) -> bool:
    """Paiement automatique par VoPay activé pour l'entreprise."""
    return bool(r is not None and r.auto_actif)


def manque_auto(r: Optional[PaiementReglage], *, interac: bool = False) -> List[str]:
    """Ce qu'il manque pour payer automatiquement (``interac`` : un lot payé
    par virements Interac)."""
    if r is None:
        manque = ["clés VoPay", "compte bancaire de l'entreprise", "adresse de l'entreprise", "compte bancaire QuickBooks"]
        return manque + (["question et réponse Interac"] if interac else [])
    manque = []
    if not (r.vopay_account_id and r.vopay_cle_chiffree and r.vopay_secret_chiffre):
        manque.append("clés VoPay")
    if not (r.retour_institution and r.retour_transit and r.retour_compte):
        manque.append("compte bancaire de l'entreprise")
    if not (r.adresse and r.ville and province_canadienne(r.province) and code_postal_canadien(r.code_postal)):
        manque.append("adresse de l'entreprise")
    if not r.qbo_compte_banque_id:
        manque.append("compte bancaire QuickBooks")
    if interac and not (r.interac_question and r.interac_reponse_chiffree):
        manque.append("question et réponse Interac")
    return manque


async def _reglage(db: AsyncSession, entreprise_id: int, *, verrou: bool = False) -> Optional[PaiementReglage]:
    q = select(PaiementReglage).where(PaiementReglage.entreprise_id == entreprise_id)
    if verrou:
        q = q.with_for_update()
    return (await db.execute(q)).scalar_one_or_none()


async def entreprises(db: AsyncSession) -> List[Dict[str, Any]]:
    """Entreprises, connexion QuickBooks, dépôt direct prêt, en attente."""
    base = await entreprises_qbo(db)
    reglages = {
        r.entreprise_id: r for r in (await db.execute(select(PaiementReglage))).scalars().all()
    }
    lots = dict(
        (
            await db.execute(
                select(LotPaiement.entreprise_id, func.count(LotPaiement.id))
                .where(LotPaiement.statut == "soumis")
                .group_by(LotPaiement.entreprise_id)
            )
        ).all()
    )
    comptes = dict(
        (
            await db.execute(
                select(FournisseurCompteBancaire.entreprise_id, func.count(FournisseurCompteBancaire.id))
                .where(FournisseurCompteBancaire.statut == "en_attente")
                .group_by(FournisseurCompteBancaire.entreprise_id)
            )
        ).all()
    )
    for e in base:
        eid = e["entreprise_id"]
        e["depot_direct_pret"] = not _manque_fichier(reglages.get(eid))
        e["paiement_auto"] = auto_actif(reglages.get(eid))
        e["auto_environnement"] = (reglages[eid].auto_environnement or "test") if e["paiement_auto"] else None
        e["lots_a_approuver"] = int(lots.get(eid, 0))
        e["comptes_a_approuver"] = int(comptes.get(eid, 0))
    return base


def _reglage_dict(r: Optional[PaiementReglage]) -> Dict[str, Any]:
    return {
        "numero_organisme": r.numero_organisme if r else None,
        "centre_traitement": r.centre_traitement if r else cpa005.CENTRE_DESJARDINS,
        "code_transaction": r.code_transaction if r else cpa005.CODE_COMPTES_FOURNISSEURS,
        "nom_court": r.nom_court if r else None,
        "nom_long": r.nom_long if r else None,
        "retour_institution": r.retour_institution if r else "815",
        "retour_transit": r.retour_transit if r else None,
        "retour_compte": r.retour_compte if r else None,
        "approbations_requises": r.approbations_requises if r else 1,
        "prochain_numero_fichier": r.prochain_numero_fichier if r else 1,
        "qbo_compte_banque_id": r.qbo_compte_banque_id if r else None,
        "qbo_compte_banque_nom": r.qbo_compte_banque_nom if r else None,
        "manque": _manque_fichier(r),
        "modifie_le": _iso(r.updated_at) if r else None,
        # Paiement automatique (VoPay). Les clés et la réponse Interac ne
        # sont jamais renvoyées : seulement si elles sont saisies.
        "auto_actif": auto_actif(r),
        "auto_environnement": (r.auto_environnement if r else None) or "test",
        "vopay_account_id": r.vopay_account_id if r else None,
        "vopay_cles": bool(r and r.vopay_cle_chiffree and r.vopay_secret_chiffre),
        "vopay_sous_compte": r.vopay_sous_compte if r else None,
        "adresse": r.adresse if r else None,
        "ville": r.ville if r else None,
        "province": r.province if r else "QC",
        "code_postal": r.code_postal if r else None,
        "interac_question": r.interac_question if r else None,
        "interac_reponse": bool(r and r.interac_reponse_chiffree),
        "auto_manque": manque_auto(r),
        "auto_manque_interac": manque_auto(r, interac=True),
    }


async def reglages(db: AsyncSession, entreprise_id: int) -> Dict[str, Any]:
    e = await _entreprise(db, entreprise_id)
    out = _reglage_dict(await _reglage(db, e.id))
    out["entreprise_id"] = e.id
    out["comptes_banque_qbo"] = []
    out["erreur_qbo"] = None
    try:
        _, scope, _ = await _entreprise_qbo(db, e.id)
        comptes = await _qbo(scope).query_all(
            "SELECT * FROM Account WHERE AccountType = 'Bank' AND Active = true"
        )
        out["comptes_banque_qbo"] = sorted(
            (
                {"id": str(c.get("Id")), "nom": c.get("FullyQualifiedName") or c.get("Name") or "—"}
                for c in comptes
                if c.get("Id")
            ),
            key=lambda c: c["nom"].casefold(),
        )
    except PaiementErreur as exc:
        out["erreur_qbo"] = exc.message
    except Exception as exc:  # noqa: BLE001
        out["erreur_qbo"] = _erreur_qbo(exc).message
    return out


def _chiffres(nom: str, longueur_min: int, longueur_max: Optional[int] = None):
    longueur_max = longueur_max or longueur_min

    def valider(v: Any) -> str:
        s = re.sub(r"[\s\-]", "", str(v or ""))
        if not s.isdigit() or not longueur_min <= len(s) <= longueur_max:
            attendu = (
                f"{longueur_min} chiffres"
                if longueur_min == longueur_max
                else f"de {longueur_min} à {longueur_max} chiffres"
            )
            raise ValueError(f"{nom} : {attendu}.")
        return s

    return valider


class ReglagesIn(BaseModel):
    """Les champs du dépôt direct sont facultatifs : une entreprise qui ne
    paie que par Interac règle ses approbations et son compte QuickBooks
    sans entente de dépôt direct. ``manque`` dit ce qu'il faut pour un
    fichier."""

    numero_organisme: Optional[str] = None
    centre_traitement: str = cpa005.CENTRE_DESJARDINS
    code_transaction: str = cpa005.CODE_COMPTES_FOURNISSEURS
    nom_court: Optional[str] = Field(default=None, max_length=60)
    nom_long: Optional[str] = Field(default=None, max_length=120)
    retour_institution: Optional[str] = None
    retour_transit: Optional[str] = None
    retour_compte: Optional[str] = None
    approbations_requises: int = Field(default=1, ge=1, le=2)
    prochain_numero_fichier: int = Field(default=1, ge=1, le=9999)
    qbo_compte_banque_id: Optional[str] = Field(default=None, max_length=64)
    code_2fa: Optional[str] = Field(default=None, max_length=12)
    #: Paiement automatique (VoPay). Un champ absent ne change rien. Les
    #: clés et la réponse Interac ne sont jamais renvoyées : vides, elles
    #: sont gardées ; ``vopay_effacer`` retire le compte VoPay.
    auto_actif: Optional[bool] = None
    auto_environnement: Optional[str] = None
    vopay_account_id: Optional[str] = Field(default=None, max_length=64)
    vopay_cle: Optional[str] = Field(default=None, max_length=256)
    vopay_secret: Optional[str] = Field(default=None, max_length=256)
    vopay_sous_compte: Optional[str] = Field(default=None, max_length=64)
    vopay_effacer: bool = False
    adresse: Optional[str] = Field(default=None, max_length=120)
    ville: Optional[str] = Field(default=None, max_length=60)
    province: Optional[str] = Field(default=None, max_length=40)
    code_postal: Optional[str] = Field(default=None, max_length=10)
    interac_question: Optional[str] = Field(default=None, max_length=40)
    interac_reponse: Optional[str] = Field(default=None, max_length=25)

    @field_validator("auto_environnement")
    @classmethod
    def _environnement(cls, v: Optional[str]) -> Optional[str]:
        s = (v or "").strip().lower()
        if not s:
            return None
        if s not in ("test", "production"):
            raise ValueError("Environnement VoPay : « test » ou « production ».")
        return s

    @field_validator("vopay_account_id", "vopay_sous_compte")
    @classmethod
    def _identifiant(cls, v: Optional[str]) -> Optional[str]:
        s = (v or "").strip()
        if not s:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_.@\-]{1,64}", s):
            raise ValueError("Identifiant de compte VoPay invalide.")
        return s

    @field_validator("vopay_cle", "vopay_secret")
    @classmethod
    def _cle(cls, v: Optional[str]) -> Optional[str]:
        s = (v or "").strip()
        if s and (len(s) < 8 or re.search(r"\s", s)):
            raise ValueError("Clé VoPay invalide : colle-la telle quelle depuis le portail VoPay.")
        return s or None

    @field_validator("adresse", "ville", "interac_question")
    @classmethod
    def _texte(cls, v: Optional[str]) -> Optional[str]:
        return re.sub(r"\s+", " ", v or "").strip() or None

    @field_validator("province")
    @classmethod
    def _province(cls, v: Optional[str]) -> Optional[str]:
        if not (v or "").strip():
            return None
        p = province_canadienne(v)
        if not p:
            raise ValueError("Province : code de deux lettres (QC, ON…).")
        return p

    @field_validator("code_postal")
    @classmethod
    def _code_postal(cls, v: Optional[str]) -> Optional[str]:
        if not (v or "").strip():
            return None
        c = code_postal_canadien(v)
        if not c:
            raise ValueError("Code postal canadien invalide (ex. H2X 1Y4).")
        return c

    @field_validator("interac_reponse")
    @classmethod
    def _reponse(cls, v: Optional[str]) -> Optional[str]:
        s = (v or "").strip()
        if not s:
            return None
        if not re.fullmatch(r"[A-Za-z0-9]{3,25}", s):
            raise ValueError("Réponse Interac : de 3 à 25 lettres ou chiffres, sans espace ni accent.")
        return s

    @field_validator("numero_organisme")
    @classmethod
    def _organisme(cls, v: Optional[str]) -> Optional[str]:
        s = re.sub(r"\s", "", v or "").upper()
        if not s:
            return None
        if not re.fullmatch(r"[A-Z0-9]{10}", s):
            raise ValueError("Numéro d'organisme : les 10 caractères remis par la caisse.")
        return s

    @field_validator("centre_traitement")
    @classmethod
    def valider_centre(cls, v: str) -> str:
        return _chiffres("Centre de traitement", 5)(v)

    @field_validator("code_transaction")
    @classmethod
    def valider_code(cls, v: str) -> str:
        return _chiffres("Code de transaction", 3)(v)

    @field_validator("retour_institution")
    @classmethod
    def valider_institution(cls, v: Optional[str]) -> Optional[str]:
        return _chiffres("Institution", 3)(v) if (v or "").strip() else None

    @field_validator("retour_transit")
    @classmethod
    def valider_transit(cls, v: Optional[str]) -> Optional[str]:
        return _chiffres("Transit", 5)(v) if (v or "").strip() else None

    @field_validator("retour_compte")
    @classmethod
    def valider_compte(cls, v: Optional[str]) -> Optional[str]:
        return _chiffres("Numéro de compte", 1, 12)(v) if (v or "").strip() else None

    @field_validator("nom_court", "nom_long")
    @classmethod
    def _nom(cls, v: Optional[str], info) -> Optional[str]:
        longueur = 15 if info.field_name == "nom_court" else 30
        return cpa005.texte(v or "", longueur).strip() or None


#: Colonnes du paiement automatique dans les réglages.
_COLONNES_AUTO = (
    "auto_actif", "auto_environnement", "vopay_account_id", "vopay_cle_chiffree",
    "vopay_secret_chiffre", "vopay_sous_compte", "adresse", "ville", "province",
    "code_postal", "interac_question", "interac_reponse_chiffree",
)
#: Changer l'une d'elles pendant qu'un paiement est en route empêcherait
#: Kratos de le suivre chez VoPay.
_CONNEXION_VOPAY = ("auto_environnement", "vopay_account_id", "vopay_sous_compte")


def _chiffrer(valeur: str) -> str:
    try:
        return encrypt_secret(valeur)
    except VaultNotConfigured as exc:
        raise PaiementErreur(
            "Aucune clé de chiffrement n'est configurée sur le serveur : impossible "
            "d'enregistrer les clés VoPay.",
            503,
        ) from exc


def _en_clair(valeur: Optional[str]) -> str:
    try:
        return decrypt_secret(valeur or "")
    except (VaultNotConfigured, ValueError) as exc:
        raise PaiementErreur(
            "La clé de chiffrement de Kratos est absente ou a changé : saisis de nouveau "
            "les clés VoPay.",
            409,
        ) from exc


def _ancien_secret(valeur: Optional[str]) -> Optional[str]:
    """Secret enregistré, en clair (None s'il est illisible) : ressaisir la
    même clé n'est pas un changement."""
    if not valeur:
        return None
    try:
        return decrypt_secret(valeur)
    except (VaultNotConfigured, ValueError):
        return None


def _meme(colonne: str, a: Any, b: Any) -> bool:
    if colonne == "auto_actif":
        return bool(a) == bool(b)
    if colonne == "auto_environnement":
        return (a or "test") == (b or "test")
    return a == b


async def _paiements_en_route(db: AsyncSession, entreprise_id: int) -> List[int]:
    """Lots dont un paiement automatique est en route chez VoPay."""
    lots = set(
        (
            await db.execute(
                select(LotPaiement.id).where(
                    LotPaiement.entreprise_id == entreprise_id,
                    LotPaiement.envoi_auto.is_(True),
                    LotPaiement.statut.in_(STATUTS_AUTO_EN_ROUTE),
                )
            )
        ).scalars().all()
    )
    lots |= set(
        (
            await db.execute(
                select(PaiementOperation.lot_id).where(
                    PaiementOperation.entreprise_id == entreprise_id,
                    PaiementOperation.statut.in_(("a_envoyer", "envoi", "incertain", "a_verifier", "en_cours")),
                )
            )
        ).scalars().all()
    )
    return sorted(lots)


async def modifier_reglages(
    db: AsyncSession, entreprise_id: int, user: User, donnees: ReglagesIn
) -> Dict[str, Any]:
    """Réglages des paiements : approbateur + double authentification
    (le compte de l'entreprise reçoit les dépôts refusés et, en paiement
    automatique, il est prélevé : il ne doit pas pouvoir être détourné).
    Les autres approbateurs sont prévenus."""
    e = await _entreprise(db, entreprise_id)
    await exiger_2fa(db, user, donnees.code_2fa)
    r = await _reglage(db, e.id, verrou=True)
    # Une nouvelle ligne n'est ajoutée qu'une fois tout vérifié : un refus
    # ne laisse pas de réglages à moitié remplis.
    nouveau = r is None
    if r is None:
        r = PaiementReglage(entreprise_id=e.id)
    avant = _reglage_dict(r) if r.id else {}

    banque_nom = r.qbo_compte_banque_nom
    if donnees.qbo_compte_banque_id and donnees.qbo_compte_banque_id != r.qbo_compte_banque_id:
        _, scope, _ = await _entreprise_qbo(db, e.id)
        try:
            compte = await _qbo(scope).get_account(donnees.qbo_compte_banque_id)
        except Exception as exc:  # noqa: BLE001
            raise _erreur_qbo(exc) from exc
        if not compte or compte.get("AccountType") != "Bank":
            raise PaiementErreur("Ce compte QuickBooks n'est pas un compte bancaire.")
        banque_nom = compte.get("FullyQualifiedName") or compte.get("Name")
    elif not donnees.qbo_compte_banque_id:
        banque_nom = None

    champs = {
        "numero_organisme": donnees.numero_organisme,
        "centre_traitement": donnees.centre_traitement,
        "code_transaction": donnees.code_transaction,
        "nom_court": donnees.nom_court,
        "nom_long": donnees.nom_long,
        "retour_institution": donnees.retour_institution,
        "retour_transit": donnees.retour_transit,
        "retour_compte": donnees.retour_compte,
        "approbations_requises": donnees.approbations_requises,
        "prochain_numero_fichier": donnees.prochain_numero_fichier,
        "qbo_compte_banque_id": donnees.qbo_compte_banque_id or None,
        "qbo_compte_banque_nom": banque_nom,
    }
    changes = [k for k, v in champs.items() if avant.get(k) != v and k != "qbo_compte_banque_nom"]

    # Paiement automatique : état visé, vérifié avant de toucher aux réglages.
    fournis = donnees.model_fields_set
    apres: Dict[str, Any] = {k: getattr(r, k) for k in _COLONNES_AUTO}
    for k in ("vopay_account_id", "vopay_sous_compte", "adresse", "ville", "province", "code_postal", "interac_question"):
        if k in fournis:
            apres[k] = getattr(donnees, k)
    if donnees.auto_environnement:
        apres["auto_environnement"] = donnees.auto_environnement
    if donnees.auto_actif is not None:
        apres["auto_actif"] = donnees.auto_actif
    en_clair: Dict[str, str] = {}
    if donnees.vopay_effacer:
        apres.update(
            auto_actif=False, vopay_account_id=None, vopay_cle_chiffree=None,
            vopay_secret_chiffre=None, vopay_sous_compte=None,
        )
    else:
        for champ, colonne in (("vopay_cle", "vopay_cle_chiffree"), ("vopay_secret", "vopay_secret_chiffre")):
            valeur = getattr(donnees, champ)
            if valeur and valeur != _ancien_secret(getattr(r, colonne)):
                apres[colonne] = _chiffrer(valeur)
                en_clair[champ] = valeur
    if donnees.interac_reponse and donnees.interac_reponse != _ancien_secret(r.interac_reponse_chiffree):
        apres["interac_reponse_chiffree"] = _chiffrer(donnees.interac_reponse)
    changes_auto = [k for k in _COLONNES_AUTO if not _meme(k, apres[k], getattr(r, k))]

    if r.id and (
        donnees.vopay_effacer
        or any(k in changes_auto for k in _CONNEXION_VOPAY)
        or any(k in changes for k in ("retour_institution", "retour_transit", "retour_compte"))
    ):
        en_route = await _paiements_en_route(db, e.id)
        if en_route:
            raise PaiementErreur(
                "Des paiements VoPay sont en route (lot "
                + ", ".join(f"n° {i}" for i in en_route)
                + ") : attends qu'ils soient terminés avant de changer le compte VoPay, "
                "son environnement ou le compte bancaire de l'entreprise.",
                409,
            )
    if apres["auto_actif"]:
        vise = {**apres, **champs}
        manque = manque_auto(SimpleNamespace(**vise))  # type: ignore[arg-type]
        if manque:
            raise PaiementErreur(
                "Pour activer le paiement automatique, il manque : " + ", ".join(manque) + ".",
                422,
                manque_auto=manque,
            )
        if not r.auto_actif or any(
            k in changes_auto for k in (*_CONNEXION_VOPAY, "vopay_cle_chiffree", "vopay_secret_chiffre")
        ):
            # Les clés doivent fonctionner avant qu'un lot ne s'en serve.
            from app.services import paiements_auto

            await paiements_auto.verifier_connexion(
                apres["vopay_account_id"],
                en_clair.get("vopay_cle") or _en_clair(apres["vopay_cle_chiffree"]),
                en_clair.get("vopay_secret") or _en_clair(apres["vopay_secret_chiffre"]),
                apres["auto_environnement"] or "test",
                apres["vopay_sous_compte"],
            )

    if nouveau:
        db.add(r)
    for k, v in champs.items():
        setattr(r, k, v)
    for k in changes_auto:
        setattr(r, k, apres[k])
    r.modifie_par_user_id = user.id
    if changes or changes_auto:
        libelles = {
            "numero_organisme": "numéro d'organisme",
            "centre_traitement": "centre de traitement",
            "code_transaction": "code de transaction",
            "nom_court": "nom court",
            "nom_long": "nom long",
            "retour_institution": "compte bancaire de l'entreprise",
            "retour_transit": "compte bancaire de l'entreprise",
            "retour_compte": "compte bancaire de l'entreprise",
            "approbations_requises": "approbations requises",
            "prochain_numero_fichier": "numéro du prochain fichier",
            "qbo_compte_banque_id": "compte QuickBooks",
            "auto_actif": "paiement automatique " + ("activé" if r.auto_actif else "désactivé"),
            "auto_environnement": "VoPay en "
            + ("production (argent réel)" if r.auto_environnement == "production" else "environnement de test"),
            "vopay_account_id": "compte VoPay",
            "vopay_sous_compte": "compte VoPay",
            "vopay_cle_chiffree": "clés VoPay",
            "vopay_secret_chiffre": "clés VoPay",
            "adresse": "adresse de l'entreprise",
            "ville": "adresse de l'entreprise",
            "province": "adresse de l'entreprise",
            "code_postal": "adresse de l'entreprise",
            "interac_question": "question Interac",
            "interac_reponse_chiffree": "réponse Interac",
        }
        quoi = ", ".join(dict.fromkeys(libelles[k] for k in (*changes, *changes_auto)))
        await _evenement(db, "reglages_modifies", user=user, entreprise_id=e.id, detail=quoi)
        await db.flush()
        await _notifier(
            db,
            await _approbateurs(db, [user.id]),
            "Réglages des paiements modifiés",
            f"{e.name} : {quoi}, par {user.display_name}.",
        )
    await db.commit()
    return await reglages(db, e.id)


# ──────────────────────────────────────────────────────────────────────
# Fournisseurs et coordonnées de paiement (compte bancaire ou Interac)
# ──────────────────────────────────────────────────────────────────────


async def fournisseurs(db: AsyncSession, entreprise_id: int) -> List[Dict[str, Any]]:
    """Fournisseurs actifs du QuickBooks de l'entreprise."""
    _, scope, _ = await _entreprise_qbo(db, entreprise_id)
    try:
        rows = await _qbo(scope).query_all("SELECT * FROM Vendor WHERE Active = true")
    except Exception as exc:  # noqa: BLE001
        raise _erreur_qbo(exc) from exc
    out = [
        {"id": str(v["Id"]), "nom": v.get("DisplayName") or "—"}
        for v in rows
        if v.get("Id")
    ]
    return sorted(out, key=lambda v: v["nom"].casefold())


def _libelle_compte(c: FournisseurCompteBancaire) -> str:
    """« compte finissant par 2345 » ou « virement Interac à x@y.ca »."""
    if c.mode == "interac":
        return f"virement Interac à {destinataire_lisible(c.interac_destinataire)}"
    return f"compte finissant par {c.compte_fin}"


def _sorte(c: FournisseurCompteBancaire) -> str:
    return "Interac" if c.mode == "interac" else "bancaires"


def _resume_compte(
    c: FournisseurCompteBancaire, noms: Optional[Dict[int, str]] = None
) -> Dict[str, Any]:
    """Coordonnées telles qu'un lot ou une facture les montre (masquées)."""
    out: Dict[str, Any] = {
        "mode": c.mode,
        "statut": c.statut,
        "institution": c.institution,
        "transit": c.transit,
        "compte_fin": c.compte_fin,
        "interac_destinataire": c.interac_destinataire,
        "approuve_le": _iso(c.decide_le),
    }
    if noms is not None:
        out["approuve_par"] = noms.get(c.decide_par_user_id or 0)
    return out


def _compte_dict(
    c: FournisseurCompteBancaire, noms: Dict[int, str], comptes_kratos: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    kratos = (comptes_kratos or {}).get(c.interac_destinataire or "") if c.mode == "interac" else None
    return {
        "id": c.id,
        "entreprise_id": c.entreprise_id,
        "fournisseur_id": c.qbo_vendor_id,
        "fournisseur": c.fournisseur_nom,
        "mode": c.mode,
        "institution": c.institution,
        "transit": c.transit,
        "compte_fin": c.compte_fin,
        "interac_destinataire": c.interac_destinataire,
        # Fraude interne la plus simple : le courriel d'un employé à la
        # place de celui du fournisseur. Signalé à qui approuve, sans
        # bloquer (un employé peut aussi être fournisseur).
        "alerte": (
            f"Ce courriel est celui du compte Kratos de {kratos} : vérifie que c'est voulu."
            if kratos
            else None
        ),
        "source": c.source,
        "statut": c.statut,
        "propose_par_id": c.propose_par_user_id,
        "propose_par": noms.get(c.propose_par_user_id or 0),
        "propose_le": _iso(c.propose_le),
        "decide_par": noms.get(c.decide_par_user_id or 0),
        "decide_le": _iso(c.decide_le),
        "motif": c.motif,
    }


async def _courriels_kratos(db: AsyncSession) -> Dict[str, str]:
    """Courriel (minuscules) → nom, pour tous les comptes Kratos."""
    users = (await db.execute(select(User))).scalars().all()
    return {(u.email or "").strip().lower(): u.display_name for u in users if u.email}


async def comptes(db: AsyncSession, entreprise_id: int) -> List[Dict[str, Any]]:
    await _entreprise(db, entreprise_id)
    rows = (
        await db.execute(
            select(FournisseurCompteBancaire)
            .where(FournisseurCompteBancaire.entreprise_id == entreprise_id)
            .order_by(FournisseurCompteBancaire.propose_le.desc(), FournisseurCompteBancaire.id.desc())
        )
    ).scalars().all()
    noms = await _noms(db, [x for c in rows for x in (c.propose_par_user_id, c.decide_par_user_id)])
    kratos = await _courriels_kratos(db) if any(c.mode == "interac" for c in rows) else {}
    return [_compte_dict(c, noms, kratos) for c in rows]


def _mode(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in MODES:
        raise ValueError("Façon de payer inconnue : dépôt direct ou virement Interac.")
    return v


class CompteIn(BaseModel):
    """Un compte bancaire (dépôt direct) ou un destinataire Interac."""

    fournisseur_id: str = Field(min_length=1, max_length=64)
    mode: str = "depot_direct"
    institution: Optional[str] = None
    transit: Optional[str] = None
    numero_compte: Optional[str] = None
    interac_destinataire: Optional[str] = Field(default=None, max_length=255)
    source: Optional[str] = Field(default=None, max_length=255)

    @field_validator("mode")
    @classmethod
    def _valider_mode(cls, v: str) -> str:
        return _mode(v) or "depot_direct"

    @model_validator(mode="after")
    def _selon_le_mode(self) -> "CompteIn":
        if self.mode == "interac":
            self.interac_destinataire = destinataire_interac(self.interac_destinataire)
            self.institution = self.transit = self.numero_compte = None
        else:
            self.institution = _chiffres("Institution", 3)(self.institution)
            self.transit = _chiffres("Transit", 5)(self.transit)
            self.numero_compte = _chiffres("Numéro de compte", 1, 12)(self.numero_compte)
            self.interac_destinataire = None
        return self


async def proposer_compte(
    db: AsyncSession, entreprise_id: int, user: User, donnees: CompteIn
) -> Dict[str, Any]:
    """Nouvelles coordonnées d'un fournisseur (compte bancaire ou
    destinataire Interac) : en attente jusqu'à ce qu'une AUTRE personne
    les approuve. Le nom vient de QuickBooks."""
    e, scope, _ = await _entreprise_qbo(db, entreprise_id)
    vid = donnees.fournisseur_id.strip()
    if not vid.isdigit():
        raise PaiementErreur("Fournisseur QuickBooks invalide.")
    try:
        trouves = await _qbo(scope).query(f"SELECT * FROM Vendor WHERE Id = '{vid}'")
    except Exception as exc:  # noqa: BLE001
        raise _erreur_qbo(exc) from exc
    if not trouves:
        raise PaiementErreur("Ce fournisseur n'existe pas dans le QuickBooks de l'entreprise.", 404)
    nom = trouves[0].get("DisplayName") or "—"
    interac = donnees.mode == "interac"
    attente = (
        await db.execute(
            select(FournisseurCompteBancaire.id).where(
                FournisseurCompteBancaire.entreprise_id == e.id,
                FournisseurCompteBancaire.qbo_vendor_id == vid,
                FournisseurCompteBancaire.mode == donnees.mode,
                FournisseurCompteBancaire.statut == "en_attente",
            )
        )
    ).first()
    if attente:
        raise PaiementErreur(
            f"Des coordonnées {'Interac' if interac else 'bancaires'} de {nom} attendent déjà "
            "d'être approuvées : retire-les d'abord.",
            409,
        )
    c = FournisseurCompteBancaire(
        entreprise_id=e.id,
        qbo_vendor_id=vid,
        fournisseur_nom=nom[:255],
        mode=donnees.mode,
        source=(donnees.source or "").strip() or None,
        statut="en_attente",
        propose_par_user_id=user.id,
    )
    if interac:
        c.interac_destinataire = donnees.interac_destinataire
        detail = f"{nom} : virement Interac à {destinataire_lisible(c.interac_destinataire)}"
    else:
        assert donnees.numero_compte is not None
        try:
            c.compte_chiffre = encrypt_secret(donnees.numero_compte)
        except VaultNotConfigured as exc:
            raise PaiementErreur(
                "Aucune clé de chiffrement n'est configurée sur le serveur : impossible "
                "d'enregistrer des coordonnées bancaires.",
                503,
            ) from exc
        c.institution = donnees.institution
        c.transit = donnees.transit
        c.compte_fin = donnees.numero_compte[-4:]
        detail = f"{nom} : institution {c.institution}, transit {c.transit}, compte finissant par {c.compte_fin}"
    db.add(c)
    await db.flush()
    await _evenement(db, "compte_propose", user=user, entreprise_id=e.id, compte_id=c.id, detail=detail)
    await _notifier(
        db,
        await _approbateurs(db, [user.id]),
        f"Coordonnées {_sorte(c)} à approuver",
        f"{nom} ({e.name}), saisies par {user.display_name}.",
    )
    await db.commit()
    kratos = await _courriels_kratos(db) if interac else {}
    return _compte_dict(c, await _noms(db, [user.id]), kratos)


async def _compte(db: AsyncSession, compte_id: int) -> FournisseurCompteBancaire:
    c = (
        await db.execute(
            select(FournisseurCompteBancaire)
            .where(FournisseurCompteBancaire.id == compte_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if c is None:
        raise PaiementErreur("Coordonnées introuvables.", 404)
    return c


async def approuver_compte(
    db: AsyncSession, compte_id: int, user: User, code_2fa: Optional[str]
) -> Dict[str, Any]:
    c = await _compte(db, compte_id)
    if c.statut != "en_attente":
        raise PaiementErreur("Ces coordonnées ne sont plus en attente.", 409)
    if c.propose_par_user_id == user.id:
        raise PaiementErreur(
            "Tu as saisi ces coordonnées : une autre personne doit les approuver.", 403
        )
    await exiger_2fa(db, user, code_2fa)
    # Les nouvelles coordonnées remplacent les anciennes du même mode : un
    # destinataire Interac ne remplace pas un compte bancaire.
    anciens = (
        await db.execute(
            select(FournisseurCompteBancaire).where(
                FournisseurCompteBancaire.entreprise_id == c.entreprise_id,
                FournisseurCompteBancaire.qbo_vendor_id == c.qbo_vendor_id,
                FournisseurCompteBancaire.mode == c.mode,
                FournisseurCompteBancaire.statut == "approuve",
            )
        )
    ).scalars().all()
    for ancien in anciens:
        ancien.statut = "remplace"
    c.statut = "approuve"
    c.decide_par_user_id = user.id
    c.decide_le = _maintenant()
    await _evenement(
        db,
        "compte_approuve",
        user=user,
        entreprise_id=c.entreprise_id,
        compte_id=c.id,
        detail=f"{c.fournisseur_nom} : {_libelle_compte(c)}"
        + (" (remplace les anciennes coordonnées)" if anciens else ""),
    )
    await _notifier(
        db,
        [c.propose_par_user_id],
        f"Coordonnées {_sorte(c)} approuvées",
        f"{c.fournisseur_nom} : {_libelle_compte(c)}.",
    )
    await db.commit()
    return _compte_dict(c, await _noms(db, [c.propose_par_user_id, user.id]))


async def refuser_compte(
    db: AsyncSession, compte_id: int, user: User, motif: str
) -> Dict[str, Any]:
    c = await _compte(db, compte_id)
    if c.statut != "en_attente":
        raise PaiementErreur("Ces coordonnées ne sont plus en attente.", 409)
    motif = (motif or "").strip()
    if not motif:
        raise PaiementErreur("Indique pourquoi tu refuses ces coordonnées.")
    c.statut = "refuse"
    c.decide_par_user_id = user.id
    c.decide_le = _maintenant()
    c.motif = motif[:2000]
    await _evenement(
        db, "compte_refuse", user=user, entreprise_id=c.entreprise_id, compte_id=c.id,
        detail=f"{c.fournisseur_nom} ({_libelle_compte(c)}) : {motif[:500]}",
    )
    await _notifier(
        db, [c.propose_par_user_id], f"Coordonnées {_sorte(c)} refusées", f"{c.fournisseur_nom} : {motif[:200]}"
    )
    await db.commit()
    return _compte_dict(c, await _noms(db, [c.propose_par_user_id, user.id]))


async def retirer_compte(db: AsyncSession, compte_id: int, user: User) -> Dict[str, Any]:
    """Retire une demande en attente (sa personne ou un approbateur) ou un
    compte approuvé (approbateur) : il ne sert plus aux prochains lots."""
    c = await _compte(db, compte_id)
    approbateur = await peut_approuver(db, user)
    if c.statut == "en_attente":
        if c.propose_par_user_id != user.id and not approbateur:
            raise PaiementErreur("Seule la personne qui a saisi la demande peut la retirer.", 403)
    elif c.statut == "approuve":
        if not approbateur:
            raise PaiementErreur("Seul un approbateur peut retirer un compte approuvé.", 403)
    else:
        raise PaiementErreur("Ces coordonnées ne sont déjà plus utilisées.", 409)
    c.statut = "retire"
    await _evenement(
        db, "compte_retire", user=user, entreprise_id=c.entreprise_id, compte_id=c.id,
        detail=f"{c.fournisseur_nom} : {_libelle_compte(c)}",
    )
    await db.commit()
    return _compte_dict(c, await _noms(db, [c.propose_par_user_id, c.decide_par_user_id]))


async def reveler_compte(
    db: AsyncSession, compte_id: int, user: User, code_2fa: Optional[str]
) -> Dict[str, Any]:
    """Numéro de compte complet, pour le comparer à sa source (spécimen de
    chèque, appel au fournisseur) avant d'approuver : les 4 derniers
    chiffres ne suffisent pas à repérer un compte substitué. Approbateur +
    double authentification ; chaque lecture est inscrite au journal."""
    c = await _compte(db, compte_id)
    if c.statut not in ("en_attente", "approuve"):
        raise PaiementErreur("Ces coordonnées ne sont plus utilisées.", 409)
    if c.mode != "depot_direct" or not c.compte_chiffre:
        raise PaiementErreur("Un destinataire Interac est déjà affiché en entier.", 409)
    await exiger_2fa(db, user, code_2fa)
    try:
        numero = decrypt_secret(c.compte_chiffre)
    except (VaultNotConfigured, ValueError) as exc:
        raise PaiementErreur(
            "La clé de chiffrement de Kratos est absente ou a changé : les "
            "coordonnées bancaires sont illisibles.",
            503,
        ) from exc
    await _evenement(
        db, "compte_revele", user=user, entreprise_id=c.entreprise_id, compte_id=c.id,
        detail=f"{c.fournisseur_nom} : compte finissant par {c.compte_fin}",
    )
    await db.commit()
    return {"id": c.id, "numero_compte": numero}


async def _comptes_par_fournisseur(
    db: AsyncSession, entreprise_id: int, statuts: Sequence[str], mode: str = "depot_direct"
) -> Dict[str, FournisseurCompteBancaire]:
    rows = (
        await db.execute(
            select(FournisseurCompteBancaire)
            .where(
                FournisseurCompteBancaire.entreprise_id == entreprise_id,
                FournisseurCompteBancaire.mode == mode,
                FournisseurCompteBancaire.statut.in_(list(statuts)),
            )
            .order_by(FournisseurCompteBancaire.id.asc())
        )
    ).scalars().all()
    out: Dict[str, FournisseurCompteBancaire] = {}
    for c in rows:
        # Un compte approuvé l'emporte sur une demande en attente.
        if c.qbo_vendor_id not in out or c.statut == "approuve":
            out[c.qbo_vendor_id] = c
    return out


# ──────────────────────────────────────────────────────────────────────
# Factures à payer (QuickBooks)
# ──────────────────────────────────────────────────────────────────────


async def _factures_ouvertes(scope: str) -> Dict[str, Dict[str, Any]]:
    try:
        rows = await _qbo(scope).query_all("SELECT * FROM Bill WHERE Balance > '0'")
    except Exception as exc:  # noqa: BLE001
        raise _erreur_qbo(exc) from exc
    return {str(b["Id"]): b for b in rows if b.get("Id") is not None}


async def _factures_dans_lots(
    db: AsyncSession, entreprise_id: int, sauf_lot: Optional[int] = None
) -> Dict[str, int]:
    q = (
        select(LotPaiementLigne.qbo_bill_id, LotPaiement.id)
        .join(LotPaiement, LotPaiement.id == LotPaiementLigne.lot_id)
        .where(LotPaiement.entreprise_id == entreprise_id, LotPaiement.statut.in_(STATUTS_ACTIFS))
    )
    if sauf_lot is not None:
        q = q.where(LotPaiement.id != sauf_lot)
    return {bill_id: lot_id for bill_id, lot_id in (await db.execute(q)).all()}


def _devise(bill: Dict[str, Any]) -> str:
    return str(((bill.get("CurrencyRef") or {}).get("value")) or "CAD").upper()


async def factures_a_payer(db: AsyncSession, entreprise_id: int) -> Dict[str, Any]:
    e, scope, etat = await _entreprise_qbo(db, entreprise_id)
    auto = auto_actif(await _reglage(db, e.id))
    bills = await _factures_ouvertes(scope)
    comptes_f = await _comptes_par_fournisseur(db, e.id, ("approuve", "en_attente"))
    interac_f = await _comptes_par_fournisseur(db, e.id, ("approuve", "en_attente"), "interac")
    dans_lots = await _factures_dans_lots(db, e.id)
    achats: Dict[str, int] = {}
    if scope == SCOPE_CONSTRUCTION and bills:
        from app.models.achat import Achat

        achats = {
            str(bid): aid
            for aid, bid in (
                await db.execute(select(Achat.id, Achat.qbo_bill_id).where(Achat.qbo_bill_id.in_(list(bills))))
            ).all()
        }
    out: List[Dict[str, Any]] = []
    for bid, b in bills.items():
        vendor = b.get("VendorRef") or {}
        vid = str(vendor.get("value") or "")
        c = comptes_f.get(vid)
        ci = interac_f.get(vid)
        devise = _devise(b)
        out.append(
            {
                "qbo_bill_id": bid,
                "fournisseur_id": vid or None,
                "fournisseur": vendor.get("name") or "—",
                "numero": b.get("DocNumber"),
                "date": b.get("TxnDate"),
                "echeance": b.get("DueDate"),
                "total": dollars(cents(b.get("TotalAmt"))),
                "solde": dollars(cents(b.get("Balance"))),
                "devise": devise,
                "lien_qbo": lien_qbo(etat.get("environment"), etat.get("realm_id"), "Bill", bid),
                "compte": _resume_compte(c) if c else None,
                "interac": _resume_compte(ci) if ci else None,
                "lot_id": dans_lots.get(bid),
                "achat_construction_id": achats.get(bid),
                "payable": bool(vid) and devise == "CAD",
            }
        )
    out.sort(key=lambda f: (f["echeance"] or f["date"] or "9999", f["fournisseur"].casefold()))
    return {
        "entreprise": {"entreprise_id": e.id, "name": e.name, "qbo_company_name": etat.get("company_name")},
        "factures": out,
        # Paiement automatique : Kratos paie le jour choisi, dès aujourd'hui.
        "premiere_date": (_aujourdhui() if auto else premiere_date_possible()).isoformat(),
        "aujourdhui": _aujourdhui().isoformat(),
        "limite_interac": dollars(LIMITE_INTERAC_CENTS),
        "paiement_auto": auto,
    }


# ──────────────────────────────────────────────────────────────────────
# Lots
# ──────────────────────────────────────────────────────────────────────


class LigneIn(BaseModel):
    qbo_bill_id: str = Field(min_length=1, max_length=64)
    montant: float = Field(gt=0)


class LotIn(BaseModel):
    date_paiement: date
    #: « depot_direct » ou « interac ». Absent : dépôt direct à la création,
    #: mode inchangé à la modification.
    mode: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=2000)
    lignes: List[LigneIn] = Field(min_length=1, max_length=200)

    @field_validator("mode")
    @classmethod
    def _valider_mode(cls, v: Optional[str]) -> Optional[str]:
        return _mode(v)


async def _lot(db: AsyncSession, lot_id: int, *, verrou: bool = False) -> LotPaiement:
    q = select(LotPaiement).where(LotPaiement.id == lot_id)
    if verrou:
        q = q.with_for_update()
    lot = (await db.execute(q)).scalar_one_or_none()
    if lot is None:
        raise PaiementErreur("Lot introuvable.", 404)
    return lot


async def _lignes(db: AsyncSession, lot_id: int) -> List[LotPaiementLigne]:
    return list(
        (
            await db.execute(
                select(LotPaiementLigne).where(LotPaiementLigne.lot_id == lot_id).order_by(LotPaiementLigne.id)
            )
        ).scalars().all()
    )


def _verifier_lignes_contre_qbo(
    lignes: Sequence[Tuple[str, int]],
    bills: Dict[str, Dict[str, Any]],
    dans_lots: Dict[str, int],
) -> None:
    """Chaque facture est encore à payer, en dollars canadiens, pour au
    moins le montant prévu, et n'est dans aucun autre lot en cours."""
    vus = set()
    for bid, montant in lignes:
        if bid in vus:
            raise PaiementErreur("Une facture est en double dans le lot.")
        vus.add(bid)
        b = bills.get(bid)
        if b is None:
            raise PaiementErreur(
                "Une facture du lot n'est plus à payer dans QuickBooks (payée, supprimée "
                "ou modifiée) : retire-la du lot.",
                409,
                qbo_bill_id=bid,
            )
        nom = ((b.get("VendorRef") or {}).get("name")) or "ce fournisseur"
        numero = b.get("DocNumber") or bid
        if not (b.get("VendorRef") or {}).get("value"):
            raise PaiementErreur(f"La facture {numero} n'a pas de fournisseur dans QuickBooks.")
        if _devise(b) != "CAD":
            raise PaiementErreur(f"La facture {numero} de {nom} n'est pas en dollars canadiens.")
        if montant <= 0:
            raise PaiementErreur(f"Montant invalide pour la facture {numero}.")
        if montant > cents(b.get("Balance")):
            raise PaiementErreur(
                f"La facture {numero} de {nom} n'a plus que {_argent(cents(b.get('Balance')))} à payer.",
                409,
                qbo_bill_id=bid,
            )
        if bid in dans_lots:
            raise PaiementErreur(
                f"La facture {numero} de {nom} est déjà dans le lot n° {dans_lots[bid]}.", 409
            )


async def _construire_lignes(
    db: AsyncSession, entreprise_id: int, scope: str, donnees: LotIn, sauf_lot: Optional[int] = None
) -> List[LotPaiementLigne]:
    bills = await _factures_ouvertes(scope)
    paires = [(l.qbo_bill_id.strip(), cents(l.montant)) for l in donnees.lignes]
    _verifier_lignes_contre_qbo(paires, bills, await _factures_dans_lots(db, entreprise_id, sauf_lot))
    out = []
    for bid, montant in paires:
        b = bills[bid]
        vendor = b.get("VendorRef") or {}
        out.append(
            LotPaiementLigne(
                qbo_bill_id=bid,
                qbo_vendor_id=str(vendor.get("value")),
                fournisseur_nom=str(vendor.get("name") or "—")[:255],
                numero_facture=(str(b.get("DocNumber"))[:64] if b.get("DocNumber") else None),
                date_facture=_jour_qbo(b.get("TxnDate")),
                echeance=_jour_qbo(b.get("DueDate")),
                solde_cents=cents(b.get("Balance")),
                montant_cents=montant,
            )
        )
    return out


def _totaux(lot: LotPaiement, lignes: Sequence[LotPaiementLigne]) -> None:
    lot.total_cents = sum(int(l.montant_cents) for l in lignes)
    lot.nb_lignes = len(lignes)


async def creer_lot(db: AsyncSession, entreprise_id: int, user: User, donnees: LotIn) -> Dict[str, Any]:
    e, scope, _ = await _entreprise_qbo(db, entreprise_id)
    mode = donnees.mode or "depot_direct"
    r = await _reglage(db, e.id)
    _verifier_date(mode, donnees.date_paiement, auto=auto_actif(r))
    lignes = await _construire_lignes(db, e.id, scope, donnees)
    lot = LotPaiement(
        entreprise_id=e.id,
        statut="brouillon",
        mode=mode,
        date_paiement=donnees.date_paiement,
        note=(donnees.note or "").strip() or None,
        approbations_requises=r.approbations_requises if r else 1,
        cree_par_user_id=user.id,
    )
    _totaux(lot, lignes)
    db.add(lot)
    await db.flush()
    for l in lignes:
        l.lot_id = lot.id
        db.add(l)
    await _evenement(
        db, "lot_cree", user=user, entreprise_id=e.id, lot_id=lot.id,
        detail=f"{lot.nb_lignes} facture(s), {_argent(lot.total_cents)}, {_quand(lot)}",
    )
    await db.commit()
    return await detail_lot(db, lot.id, user)


async def modifier_lot(db: AsyncSession, lot_id: int, user: User, donnees: LotIn) -> Dict[str, Any]:
    lot = await _lot(db, lot_id, verrou=True)
    if lot.statut != "brouillon":
        raise PaiementErreur("Seul un brouillon se modifie : remets d'abord le lot en brouillon.", 409)
    _, scope, _ = await _entreprise_qbo(db, lot.entreprise_id)
    mode = donnees.mode or lot.mode
    _verifier_date(mode, donnees.date_paiement, auto=auto_actif(await _reglage(db, lot.entreprise_id)))
    lignes = await _construire_lignes(db, lot.entreprise_id, scope, donnees, sauf_lot=lot.id)
    await db.execute(delete(LotPaiementLigne).where(LotPaiementLigne.lot_id == lot.id))
    for l in lignes:
        l.lot_id = lot.id
        db.add(l)
    lot.mode = mode
    lot.date_paiement = donnees.date_paiement
    lot.note = (donnees.note or "").strip() or None
    _totaux(lot, lignes)
    await _evenement(
        db, "lot_modifie", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
        detail=f"{lot.nb_lignes} facture(s), {_argent(lot.total_cents)}, {_quand(lot)}",
    )
    await db.commit()
    return await detail_lot(db, lot.id, user)


def _par_fournisseur(lignes: Sequence[LotPaiementLigne]) -> Dict[str, List[LotPaiementLigne]]:
    """Lignes regroupées par fournisseur, dans l'ordre du lot."""
    groupes: Dict[str, List[LotPaiementLigne]] = {}
    for l in lignes:
        groupes.setdefault(l.qbo_vendor_id, []).append(l)
    return groupes


def _verifier_limite_interac(lignes: Sequence[LotPaiementLigne]) -> None:
    trop = sorted(
        g[0].fournisseur_nom
        for g in _par_fournisseur(lignes).values()
        if sum(int(l.montant_cents) for l in g) > LIMITE_INTERAC_CENTS
    )
    if trop:
        raise PaiementErreur(
            f"Un virement Interac est limité à {_argent(LIMITE_INTERAC_CENTS)} : paie "
            + ", ".join(trop)
            + " par dépôt direct, ou réduis le montant.",
            409,
        )


async def soumettre(db: AsyncSession, lot_id: int, user: User) -> Dict[str, Any]:
    """Le lot part aux approbateurs. Les soldes sont relus dans QuickBooks
    et les coordonnées approuvées de chaque fournisseur (compte bancaire ou
    destinataire Interac, selon le lot) sont figées."""
    lot = await _lot(db, lot_id, verrou=True)
    if lot.statut != "brouillon":
        raise PaiementErreur("Ce lot a déjà été soumis.", 409)
    e, scope, _ = await _entreprise_qbo(db, lot.entreprise_id)
    lignes = await _lignes(db, lot.id)
    if not lignes:
        raise PaiementErreur("Le lot est vide.")
    r = await _reglage(db, lot.entreprise_id)
    _verifier_date(lot.mode, lot.date_paiement, auto=auto_actif(r))
    bills = await _factures_ouvertes(scope)
    _verifier_lignes_contre_qbo(
        [(l.qbo_bill_id, int(l.montant_cents)) for l in lignes],
        bills,
        await _factures_dans_lots(db, lot.entreprise_id, lot.id),
    )
    interac = lot.mode == "interac"
    approuves = await _comptes_par_fournisseur(db, lot.entreprise_id, ("approuve",), lot.mode)
    sans = sorted({l.fournisseur_nom for l in lignes if l.qbo_vendor_id not in approuves})
    if sans:
        raise PaiementErreur(
            f"Coordonnées {'Interac' if interac else 'bancaires'} approuvées manquantes pour : "
            + ", ".join(sans)
            + ".",
            409,
            fournisseurs=sans,
        )
    if interac:
        _verifier_limite_interac(lignes)
    for l in lignes:
        l.compte_bancaire_id = approuves[l.qbo_vendor_id].id
        l.solde_cents = cents(bills[l.qbo_bill_id].get("Balance"))
    lot.statut = "soumis"
    lot.soumis_par_user_id = user.id
    lot.soumis_le = _maintenant()
    lot.approbations_requises = r.approbations_requises if r else 1
    await db.execute(delete(LotPaiementApprobation).where(LotPaiementApprobation.lot_id == lot.id))
    await _evenement(db, "lot_soumis", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id)
    await _notifier(
        db,
        await _approbateurs(db, [user.id, lot.cree_par_user_id]),
        "Paiements à approuver",
        f"{e.name} : {lot.nb_lignes} facture(s), {_argent(lot.total_cents)}, {_quand(lot)}.",
    )
    await db.commit()
    return await detail_lot(db, lot.id, user)


async def remettre_en_brouillon(db: AsyncSession, lot_id: int, user: User) -> Dict[str, Any]:
    lot = await _lot(db, lot_id, verrou=True)
    if lot.statut not in ("soumis", "refuse", "approuve", "echec"):
        raise PaiementErreur("Ce lot ne peut plus revenir en brouillon.", 409)
    if lot.statut in ("approuve", "echec") and not await peut_approuver(db, user):
        raise PaiementErreur("Seul un approbateur peut remettre en brouillon un lot approuvé.", 403)
    lot.statut = "brouillon"
    lot.approuve_le = None
    # Paiement automatique : redécidé à la prochaine approbation.
    lot.envoi_auto = None
    lot.auto_environnement = None
    lot.auto_erreur = None
    lot.auto_prochain_essai = None
    lot.auto_tentatives = None
    for l in await _lignes(db, lot.id):
        l.compte_bancaire_id = None
    await db.execute(delete(LotPaiementApprobation).where(LotPaiementApprobation.lot_id == lot.id))
    await _evenement(db, "lot_en_brouillon", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id)
    await db.commit()
    return await detail_lot(db, lot.id, user)


def _a_prepare(lot: LotPaiement, user: User) -> bool:
    return user.id in (lot.cree_par_user_id, lot.soumis_par_user_id)


async def approuver(
    db: AsyncSession, lot_id: int, user: User, code_2fa: Optional[str], commentaire: Optional[str]
) -> Dict[str, Any]:
    lot = await _lot(db, lot_id, verrou=True)
    if lot.statut != "soumis":
        raise PaiementErreur("Ce lot n'attend pas d'approbation.", 409)
    if _a_prepare(lot, user):
        raise PaiementErreur("Tu as préparé ce lot : une autre personne doit l'approuver.", 403)
    deja = (
        await db.execute(
            select(LotPaiementApprobation.id).where(
                LotPaiementApprobation.lot_id == lot.id, LotPaiementApprobation.user_id == user.id
            )
        )
    ).first()
    if deja:
        raise PaiementErreur("Tu as déjà donné ton approbation pour ce lot.", 409)
    await exiger_2fa(db, user, code_2fa)
    db.add(
        LotPaiementApprobation(
            lot_id=lot.id, user_id=user.id, decision="approuve",
            commentaire=(commentaire or "").strip()[:2000] or None,
        )
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise PaiementErreur("Tu as déjà donné ton approbation pour ce lot.", 409) from exc
    nb = (
        await db.execute(
            select(func.count(LotPaiementApprobation.id)).where(
                LotPaiementApprobation.lot_id == lot.id, LotPaiementApprobation.decision == "approuve"
            )
        )
    ).scalar_one()
    complet = nb >= max(1, lot.approbations_requises)
    if complet:
        lot.statut = "approuve"
        lot.approuve_le = _maintenant()
        # Paiement automatique : décidé ici, selon les réglages du moment.
        lot.envoi_auto = auto_actif(await _reglage(db, lot.entreprise_id)) or None
    await _evenement(
        db, "lot_approuve", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
        detail=f"approbation {nb} sur {lot.approbations_requises}"
        + (", paiement automatique par VoPay" if complet and lot.envoi_auto else ""),
    )
    e = await db.get(Entreprise, lot.entreprise_id)
    await _notifier(
        db,
        [lot.cree_par_user_id, lot.soumis_par_user_id],
        "Paiements approuvés" if complet else "Paiements : une approbation reçue",
        f"{e.name if e else 'Lot'} : {_argent(lot.total_cents)}, approuvé par {user.display_name}"
        + ("." if complet else f" ({nb} sur {lot.approbations_requises}).")
        + (f" Kratos paie les fournisseurs à partir du {_date_lisible(lot.date_paiement)}." if complet and lot.envoi_auto else ""),
    )
    await db.commit()
    if complet and lot.envoi_auto:
        # Le prélèvement part tout de suite si la date du lot est arrivée.
        from app.services import paiements_auto

        await paiements_auto.demarrer(db, lot.id)
    return await detail_lot(db, lot.id, user)


async def refuser(db: AsyncSession, lot_id: int, user: User, commentaire: str) -> Dict[str, Any]:
    lot = await _lot(db, lot_id, verrou=True)
    if lot.statut != "soumis":
        raise PaiementErreur("Ce lot n'attend pas d'approbation.", 409)
    if _a_prepare(lot, user):
        raise PaiementErreur("Tu as préparé ce lot : retire-le plutôt (remettre en brouillon).", 403)
    commentaire = (commentaire or "").strip()
    if not commentaire:
        raise PaiementErreur("Indique pourquoi tu refuses ce lot.")
    await db.execute(
        delete(LotPaiementApprobation).where(
            LotPaiementApprobation.lot_id == lot.id, LotPaiementApprobation.user_id == user.id
        )
    )
    db.add(
        LotPaiementApprobation(lot_id=lot.id, user_id=user.id, decision="refuse", commentaire=commentaire[:2000])
    )
    lot.statut = "refuse"
    await _evenement(
        db, "lot_refuse", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id, detail=commentaire[:500]
    )
    await _notifier(
        db,
        [lot.cree_par_user_id, lot.soumis_par_user_id],
        "Paiements refusés",
        f"Lot n° {lot.id} refusé par {user.display_name} : {commentaire[:200]}",
    )
    await db.commit()
    return await detail_lot(db, lot.id, user)


def _information(numeros: Sequence[Optional[str]]) -> str:
    """Ce que le fournisseur peut voir avec le dépôt : ses numéros de
    facture, en 15 caractères (le « + » n'existe pas dans la norme)."""
    nums = [n.strip() for n in numeros if n and n.strip()]
    if not nums:
        return ""
    autres = len(nums) - 1
    for essai in (f"FACT {' '.join(nums)}", " ".join(nums), f"FACT {nums[0]} ET {autres}"):
        if len(essai) <= 15:
            return essai
    suite = f" ET {autres}" if autres else ""
    return nums[0][: 15 - len(suite)] + suite


async def _contenu_fichier(
    db: AsyncSession, lot: LotPaiement, r: PaiementReglage, numero: int, date_creation: date
) -> str:
    lignes = await _lignes(db, lot.id)
    groupes: Dict[Tuple[str, Optional[int]], List[LotPaiementLigne]] = {}
    for l in lignes:
        groupes.setdefault((l.qbo_vendor_id, l.compte_bancaire_id), []).append(l)
    depots: List[cpa005.Depot] = []
    for k, ((_vid, compte_id), groupe) in enumerate(groupes.items(), start=1):
        c = await db.get(FournisseurCompteBancaire, compte_id) if compte_id else None
        if c is None or c.statut != "approuve":
            raise PaiementErreur(
                f"Les coordonnées bancaires de {groupe[0].fournisseur_nom} ont changé depuis la "
                "soumission : remets le lot en brouillon et soumets-le de nouveau.",
                409,
            )
        try:
            numero_compte = decrypt_secret(c.compte_chiffre)
        except (VaultNotConfigured, ValueError) as exc:
            raise PaiementErreur(
                "La clé de chiffrement de Kratos est absente ou a changé : les "
                "coordonnées bancaires sont illisibles.",
                503,
            ) from exc
        depots.append(
            cpa005.Depot(
                montant_cents=sum(int(l.montant_cents) for l in groupe),
                institution=c.institution,
                transit=c.transit,
                compte=numero_compte,
                beneficiaire=c.fournisseur_nom,
                reference=f"KRATOS L{lot.id}-{k}",
                information=_information([l.numero_facture for l in groupe]),
            )
        )
    emetteur = cpa005.Emetteur(
        numero_organisme=r.numero_organisme or "",
        nom_court=r.nom_court or "",
        nom_long=r.nom_long or "",
        retour_institution=r.retour_institution or "",
        retour_transit=r.retour_transit or "",
        retour_compte=r.retour_compte or "",
        centre_traitement=r.centre_traitement,
        code_transaction=r.code_transaction,
    )
    try:
        return cpa005.generer(
            emetteur, depots, numero_fichier=numero, date_creation=date_creation, date_depot=lot.date_paiement
        )
    except cpa005.FichierInvalide as exc:
        raise PaiementErreur(str(exc)) from exc


def _resume_fichier(contenu: str) -> Dict[str, Any]:
    """Relecture du fichier, sans les numéros de compte complets."""
    lu = cpa005.lire(contenu)
    return {
        "numero_fichier": lu["numero_fichier"],
        "numero_organisme": lu["numero_organisme"],
        "date_creation": lu["date_creation"],
        "centre_traitement": lu["centre_traitement"],
        "devise": lu["devise"],
        "nombre": lu["nombre"],
        "total": dollars(lu["total_cents"]),
        "depots": [
            {
                "beneficiaire": d["beneficiaire"],
                "montant": dollars(d["montant_cents"]),
                "date_depot": d["date_depot"],
                "institution": d["institution"],
                "transit": d["transit"],
                "compte_fin": d["compte"][-4:],
                "information": d["information"],
                "reference": d["reference"],
            }
            for d in lu["depots"]
        ],
    }


async def creer_fichier(
    db: AsyncSession,
    lot_id: int,
    user: User,
    code_2fa: Optional[str],
    date_paiement: Optional[date] = None,
) -> Dict[str, Any]:
    """Fichier de dépôt direct du lot approuvé (approbateur + double
    authentification). Le premier appel lui donne son numéro ; les appels
    suivants redonnent exactement le même fichier."""
    lot = await _lot(db, lot_id, verrou=True)
    if lot.envoi_auto:
        raise PaiementErreur("Ce lot est payé automatiquement par VoPay : il n'a pas de fichier de dépôt.", 409)
    if lot.mode == "interac":
        raise PaiementErreur("Ce lot se paie par virements Interac : il n'a pas de fichier de dépôt.", 409)
    if lot.statut not in ("approuve", "fichier_cree"):
        raise PaiementErreur("Le lot doit être approuvé avant de créer le fichier.", 409)
    await exiger_2fa(db, user, code_2fa)
    r = await _reglage(db, lot.entreprise_id, verrou=True)
    manque = _manque_fichier(r)
    if manque:
        raise PaiementErreur(
            "Complète les réglages du dépôt direct : " + ", ".join(manque) + ".", 409, manque=manque
        )
    assert r is not None
    if lot.statut == "fichier_cree":
        contenu = await _contenu_fichier(db, lot, r, int(lot.fichier_numero or 0), lot.fichier_date or _aujourdhui())
        if hashlib.sha256(contenu.encode("ascii")).hexdigest() != lot.fichier_sha256:
            raise PaiementErreur(
                "Les données ont changé depuis la création du fichier : annule ce lot et refais-le.", 409
            )
        await _evenement(db, "fichier_retelecharge", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id)
    else:
        if date_paiement and date_paiement != lot.date_paiement:
            _verifier_date_depot(date_paiement)
            await _evenement(
                db, "date_modifiee", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
                detail=f"{_date_lisible(lot.date_paiement)} → {_date_lisible(date_paiement)}",
            )
            lot.date_paiement = date_paiement
        _verifier_date_depot(lot.date_paiement)
        # Pas de double paiement : les factures sont relues dans QuickBooks.
        _, scope, _ = await _entreprise_qbo(db, lot.entreprise_id)
        lignes = await _lignes(db, lot.id)
        _verifier_lignes_contre_qbo(
            [(l.qbo_bill_id, int(l.montant_cents)) for l in lignes],
            await _factures_ouvertes(scope),
            await _factures_dans_lots(db, lot.entreprise_id, lot.id),
        )
        numero = int(r.prochain_numero_fichier or 1)
        aujourdhui = _aujourdhui()
        contenu = await _contenu_fichier(db, lot, r, numero, aujourdhui)
        r.prochain_numero_fichier = numero % 9999 + 1
        lot.statut = "fichier_cree"
        lot.fichier_numero = numero
        lot.fichier_date = aujourdhui
        lot.fichier_sha256 = hashlib.sha256(contenu.encode("ascii")).hexdigest()
        lot.fichier_cree_par_user_id = user.id
        lot.fichier_cree_le = _maintenant()
        await _evenement(
            db, "fichier_cree", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
            detail=f"fichier n° {numero:04d}, {_argent(lot.total_cents)}",
        )
    resume = _resume_fichier(contenu)
    await db.commit()
    return {
        "nom": f"DRD-{r.numero_organisme}-{int(lot.fichier_numero or 0):04d}.txt",
        "contenu": contenu,
        "resume": resume,
    }


async def marquer_transmis(db: AsyncSession, lot_id: int, user: User) -> Dict[str, Any]:
    lot = await _lot(db, lot_id, verrou=True)
    if lot.mode == "interac":
        raise PaiementErreur("Ce lot se paie par virements Interac : indique plutôt chaque virement envoyé.", 409)
    if lot.statut != "fichier_cree":
        raise PaiementErreur("Crée d'abord le fichier de ce lot.", 409)
    lot.statut = "transmis"
    lot.transmis_par_user_id = user.id
    lot.transmis_le = _maintenant()
    await _evenement(
        db, "fichier_transmis", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
        detail=f"fichier n° {int(lot.fichier_numero or 0):04d}",
    )
    await _notifier(
        db,
        [lot.cree_par_user_id, lot.soumis_par_user_id],
        "Paiements transmis à Desjardins",
        f"Lot n° {lot.id} : {_argent(lot.total_cents)}, dépôt le {_date_lisible(lot.date_paiement)}.",
    )
    await db.commit()
    return await detail_lot(db, lot.id, user)


# ──────────────────────────────────────────────────────────────────────
# Virements Interac
# ──────────────────────────────────────────────────────────────────────


def _message_interac(numeros: Sequence[Optional[str]]) -> str:
    """Message joint au virement : ce que le fournisseur verra."""
    nums = list(dict.fromkeys(n.strip() for n in numeros if n and n.strip()))
    if not nums:
        return "Paiement de facture"
    if len(nums) == 1:
        return f"Paiement de la facture {nums[0]}"
    for k in range(len(nums), 0, -1):
        reste = len(nums) - k
        texte = "Paiement des factures " + ", ".join(nums[:k])
        if reste:
            texte += f" et {reste} autre{'s' if reste > 1 else ''}"
        if len(texte) <= 140:
            return texte
    return f"Paiement de {len(nums)} factures"


async def _lot_interac(db: AsyncSession, lot_id: int, statut: str, message: str) -> LotPaiement:
    lot = await _lot(db, lot_id, verrou=True)
    if lot.mode != "interac" or lot.statut != statut:
        raise PaiementErreur(message, 409)
    return lot


async def preparer_envoi(
    db: AsyncSession, lot_id: int, user: User, code_2fa: Optional[str]
) -> Dict[str, Any]:
    """Après l'approbation, un approbateur prépare l'envoi des virements
    Interac (double authentification) : les soldes sont relus dans
    QuickBooks (pas de double paiement) et chaque destinataire doit être
    encore celui qui a été approuvé. Il envoie ensuite chaque virement
    lui-même dans AccèsD Affaires : Desjardins n'accepte pas de fichier
    pour Interac."""
    lot = await _lot(db, lot_id, verrou=True)
    if lot.envoi_auto:
        raise PaiementErreur("Ce lot est payé automatiquement par VoPay : Kratos envoie les virements.", 409)
    if lot.mode != "interac":
        raise PaiementErreur("Ce lot se paie par dépôt direct : crée plutôt son fichier.", 409)
    if lot.statut != "approuve":
        raise PaiementErreur("Le lot doit être approuvé avant l'envoi des virements.", 409)
    await exiger_2fa(db, user, code_2fa)
    _, scope, _ = await _entreprise_qbo(db, lot.entreprise_id)
    lignes = await _lignes(db, lot.id)
    _verifier_lignes_contre_qbo(
        [(l.qbo_bill_id, int(l.montant_cents)) for l in lignes],
        await _factures_ouvertes(scope),
        await _factures_dans_lots(db, lot.entreprise_id, lot.id),
    )
    _verifier_limite_interac(lignes)
    groupes = _par_fournisseur(lignes)
    for groupe in groupes.values():
        compte_id = groupe[0].compte_bancaire_id
        c = await db.get(FournisseurCompteBancaire, compte_id) if compte_id else None
        if c is None or c.mode != "interac" or c.statut != "approuve":
            raise PaiementErreur(
                f"Les coordonnées Interac de {groupe[0].fournisseur_nom} ont changé depuis la "
                "soumission : remets le lot en brouillon et soumets-le de nouveau.",
                409,
            )
    lot.statut = "a_envoyer"
    lot.envoi_prepare_par_user_id = user.id
    lot.envoi_prepare_le = _maintenant()
    await _evenement(
        db, "envoi_prepare", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
        detail=f"{len(groupes)} virement(s), {_argent(lot.total_cents)}",
    )
    await db.commit()
    return await detail_lot(db, lot.id, user)


async def _virements_termines(db: AsyncSession, lot: LotPaiement, user: User) -> None:
    """Tous les virements restants sont envoyés : le lot passe à « transmis »."""
    lot.statut = "transmis"
    lot.transmis_par_user_id = user.id
    lot.transmis_le = _maintenant()
    await _evenement(
        db, "virements_envoyes", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
        detail=_argent(lot.total_cents),
    )
    await _notifier(
        db,
        [lot.cree_par_user_id, lot.soumis_par_user_id],
        "Virements Interac envoyés",
        f"Lot n° {lot.id} : {_argent(lot.total_cents)}. Les paiements peuvent être inscrits dans QuickBooks.",
    )


async def marquer_envoye(
    db: AsyncSession, lot_id: int, user: User, fournisseur_id: str, reference: Optional[str]
) -> Dict[str, Any]:
    """L'approbateur a envoyé le virement d'un fournisseur dans AccèsD
    Affaires (toutes ses factures du lot, en un virement)."""
    lot = await _lot_interac(db, lot_id, "a_envoyer", "Ce lot n'a pas de virements Interac à envoyer.")
    lignes = await _lignes(db, lot.id)
    groupe = _par_fournisseur(lignes).get(fournisseur_id)
    if not groupe:
        raise PaiementErreur("Ce fournisseur n'est pas dans le lot.", 404)
    nom = groupe[0].fournisseur_nom
    if all(l.envoye_le for l in groupe):
        raise PaiementErreur(f"Le virement à {nom} est déjà indiqué comme envoyé.", 409)
    ref = re.sub(r"\s+", " ", reference or "").strip()[:64] or None
    maintenant = _maintenant()
    for l in groupe:
        l.envoye_le = maintenant
        l.envoye_par_user_id = user.id
        l.reference_interac = ref
    c = await db.get(FournisseurCompteBancaire, groupe[0].compte_bancaire_id) if groupe[0].compte_bancaire_id else None
    await _evenement(
        db, "interac_envoye", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
        detail=f"{nom} : {_argent(sum(int(l.montant_cents) for l in groupe))}"
        + (f" à {destinataire_lisible(c.interac_destinataire)}" if c else "")
        + (f", référence {ref}" if ref else ""),
    )
    if all(l.envoye_le for l in lignes):
        await _virements_termines(db, lot, user)
    await db.commit()
    return await detail_lot(db, lot.id, user)


async def retirer_virement(
    db: AsyncSession, lot_id: int, user: User, fournisseur_id: str, motif: str
) -> Dict[str, Any]:
    """Retire du lot le virement d'un fournisseur qui n'est pas encore
    envoyé (refusé par AccèsD, destinataire à corriger, montant au-delà de
    la limite du jour…) : ses factures redeviennent à payer."""
    lot = await _lot_interac(
        db, lot_id, "a_envoyer", "Seul un virement d'un lot en cours d'envoi peut être retiré."
    )
    motif = (motif or "").strip()
    if not motif:
        raise PaiementErreur("Indique pourquoi tu retires ce virement.")
    lignes = await _lignes(db, lot.id)
    groupe = _par_fournisseur(lignes).get(fournisseur_id)
    if not groupe:
        raise PaiementErreur("Ce fournisseur n'est pas dans le lot.", 404)
    if any(l.envoye_le for l in groupe):
        raise PaiementErreur("Ce virement est indiqué comme envoyé : il ne peut plus être retiré.", 409)
    ids = {l.id for l in groupe}
    restantes = [l for l in lignes if l.id not in ids]
    await db.execute(delete(LotPaiementLigne).where(LotPaiementLigne.id.in_(list(ids))))
    _totaux(lot, restantes)
    await _evenement(
        db, "virement_retire", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
        detail=f"{groupe[0].fournisseur_nom} : {_argent(sum(int(l.montant_cents) for l in groupe))}, "
        f"motif : {motif[:500]}",
    )
    if not restantes:
        lot.statut = "annule"
        lot.annule_par_user_id = user.id
        lot.annule_le = _maintenant()
        lot.motif_annulation = motif[:2000]
        await _evenement(
            db, "lot_annule", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
            detail="dernier virement retiré",
        )
    elif all(l.envoye_le for l in restantes):
        await _virements_termines(db, lot, user)
    await db.commit()
    return await detail_lot(db, lot.id, user)


async def _paiements_vopay_reussis(db: AsyncSession, lot_id: int) -> Dict[str, PaiementOperation]:
    """Paiement automatique : dernier paiement réussi de chaque fournisseur."""
    rows = (
        await db.execute(
            select(PaiementOperation)
            .where(
                PaiementOperation.lot_id == lot_id,
                PaiementOperation.sorte == "paiement",
                PaiementOperation.statut == "reussi",
            )
            .order_by(PaiementOperation.id)
        )
    ).scalars().all()
    return {op.qbo_vendor_id or "": op for op in rows}


async def inscrire_qbo(db: AsyncSession, lot: LotPaiement, user: Optional[User]) -> List[LotPaiementLigne]:
    """Un paiement de facture QuickBooks par fournisseur, depuis le compte
    bancaire choisi dans les réglages. Reprend là où il s'est arrêté : un
    paiement déjà créé (même numéro de document) n'est pas recréé. Un
    virement Interac est daté du jour où il a été envoyé ; un paiement
    automatique, du jour où VoPay l'a confirmé. Rend les lignes qui restent
    à inscrire ; le lot passe à « payé » quand il n'en reste plus. Ne valide
    pas la transaction."""
    interac = lot.mode == "interac"
    r = await _reglage(db, lot.entreprise_id)
    if r is None or not r.qbo_compte_banque_id:
        raise PaiementErreur(
            "Choisis dans les réglages le compte bancaire QuickBooks d'où partent les paiements.", 409
        )
    _, scope, _ = await _entreprise_qbo(db, lot.entreprise_id)
    qbo = _qbo(scope)
    lignes = await _lignes(db, lot.id)
    vopay = await _paiements_vopay_reussis(db, lot.id) if lot.envoi_auto else {}
    groupes: Dict[str, List[LotPaiementLigne]] = {}
    for l in lignes:
        if not l.qbo_bill_payment_id:
            groupes.setdefault(l.qbo_vendor_id, []).append(l)
    for vid, groupe in groupes.items():
        if lot.envoi_auto:
            op = vopay.get(vid)
            if op is None:
                for l in groupe:
                    l.erreur_qbo = "Le paiement VoPay de ce fournisseur n'est pas confirmé."
                continue
            doc = f"VOP-{lot.id}-{vid}"[:21]
            date_txn = (_utc(op.termine_le) or _maintenant()).astimezone(TZ).date()
            note = (
                f"Paiement VoPay ({'virement Interac' if interac else 'dépôt direct'}), "
                f"lot Kratos n° {lot.id}, transaction VoPay {op.transaction_id or '—'}"
            )
        elif interac:
            doc = f"INT-{lot.id}-{vid}"[:21]
            envoye = _utc(groupe[0].envoye_le) or _maintenant()
            date_txn = envoye.astimezone(TZ).date()
            ref = groupe[0].reference_interac
            note = f"Virement Interac, lot Kratos n° {lot.id}" + (f", référence {ref}" if ref else "")
        else:
            doc = f"DRD-{lot.id}-{vid}"[:21]
            date_txn = lot.date_paiement
            note = (
                f"Dépôt direct Desjardins, lot Kratos n° {lot.id}, "
                f"fichier n° {int(lot.fichier_numero or 0):04d}"
            )
        try:
            existants = await qbo.query(f"SELECT * FROM BillPayment WHERE DocNumber = '{doc}'")
            if existants:
                bp_id = str(existants[0].get("Id"))
            else:
                for l in groupe:
                    bill = await qbo.get_bill(l.qbo_bill_id)
                    if cents(bill.get("Balance")) < int(l.montant_cents):
                        raise PaiementErreur(
                            f"La facture {l.numero_facture or l.qbo_bill_id} a déjà été payée en "
                            "tout ou en partie dans QuickBooks : vérifie avant d'inscrire ce paiement."
                        )
                total = sum(int(l.montant_cents) for l in groupe)
                bp = await qbo.create_bill_payment(
                    {
                        "VendorRef": {"value": vid},
                        "PayType": "Check",
                        "CheckPayment": {"BankAccountRef": {"value": r.qbo_compte_banque_id}},
                        "TotalAmt": dollars(total),
                        "TxnDate": date_txn.isoformat(),
                        "DocNumber": doc,
                        "PrivateNote": note,
                        "Line": [
                            {
                                "Amount": dollars(int(l.montant_cents)),
                                "LinkedTxn": [{"TxnId": l.qbo_bill_id, "TxnType": "Bill"}],
                            }
                            for l in groupe
                        ],
                    }
                )
                bp_id = str(bp.get("Id"))
        except PaiementErreur as exc:
            for l in groupe:
                l.erreur_qbo = exc.message
            continue
        except Exception as exc:  # noqa: BLE001
            for l in groupe:
                l.erreur_qbo = message_qbo(exc)
            continue
        for l in groupe:
            l.qbo_bill_payment_id = bp_id
            l.erreur_qbo = None
    restantes = [l for l in lignes if not l.qbo_bill_payment_id]
    if not restantes:
        lot.statut = "paye"
        lot.paye_le = _maintenant()
    # Les reprises automatiques ne remplissent pas le journal : l'erreur est
    # affichée sur le lot.
    if user is not None or not restantes:
        await _evenement(
            db, "qbo_enregistre" if not restantes else "qbo_partiel", user=user,
            entreprise_id=lot.entreprise_id, lot_id=lot.id,
            detail=None if not restantes else f"{len(restantes)} facture(s) à reprendre",
        )
    return restantes


async def enregistrer_qbo(db: AsyncSession, lot_id: int, user: User) -> Dict[str, Any]:
    """Inscrit (ou reprend) les paiements du lot dans QuickBooks."""
    lot = await _lot(db, lot_id, verrou=True)
    interac = lot.mode == "interac"
    if lot.statut != "transmis":
        raise PaiementErreur(
            "Les fournisseurs doivent d'abord être payés."
            if lot.envoi_auto
            else "Les virements Interac doivent d'abord être envoyés."
            if interac
            else "Le fichier doit avoir été transmis à Desjardins.",
            409,
        )
    if lot.envoi_auto and lot.auto_environnement == "test":
        raise PaiementErreur("Lot payé dans l'environnement de test VoPay : rien n'est inscrit dans QuickBooks.", 409)
    await inscrire_qbo(db, lot, user)
    if lot.envoi_auto and lot.statut == "paye":
        lot.auto_erreur = None
        lot.auto_prochain_essai = None
    await db.commit()
    return await detail_lot(db, lot.id, user)


async def annuler(db: AsyncSession, lot_id: int, user: User, motif: Optional[str]) -> Dict[str, Any]:
    lot = await _lot(db, lot_id, verrou=True)
    # Un lot de test (environnement de test VoPay, aucun argent réel) peut
    # être abandonné en cours de route.
    test_en_route = bool(lot.envoi_auto) and lot.auto_environnement == "test" and lot.statut in STATUTS_AUTO_EN_ROUTE
    if lot.statut in STATUTS_AUTO_EN_ROUTE and not test_en_route:
        raise PaiementErreur(
            "Le paiement de ce lot est en route chez VoPay : il ne peut plus être annulé. "
            "Un paiement refusé peut être retiré du lot.",
            409,
        )
    if lot.statut not in ("brouillon", "soumis", "refuse", "approuve", "fichier_cree", "a_envoyer", "echec") and not test_en_route:
        raise PaiementErreur("Ce lot ne peut plus être annulé dans Kratos.", 409)
    if (lot.statut in ("approuve", "fichier_cree", "a_envoyer", "echec") or test_en_route) and not await peut_approuver(db, user):
        raise PaiementErreur("Seul un approbateur peut annuler un lot approuvé.", 403)
    if lot.statut == "a_envoyer" and any(l.envoye_le for l in await _lignes(db, lot.id)):
        raise PaiementErreur(
            "Des virements de ce lot sont déjà envoyés : retire plutôt ceux qui ne le sont pas.", 409
        )
    motif = (motif or "").strip()
    if lot.statut == "fichier_cree" and not motif:
        raise PaiementErreur("Indique pourquoi tu annules un lot dont le fichier est créé.")
    if lot.statut == "a_envoyer" and not motif:
        raise PaiementErreur("Indique pourquoi tu annules ces virements.")
    if test_en_route and not motif:
        raise PaiementErreur("Indique pourquoi tu abandonnes ce lot de test.")
    if test_en_route:
        from app.services import paiements_auto

        await paiements_auto.annuler_operations_test(db, lot)
    lot.statut = "annule"
    lot.annule_par_user_id = user.id
    lot.annule_le = _maintenant()
    lot.motif_annulation = motif[:2000] or None
    await _evenement(
        db, "lot_annule", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id, detail=motif[:500] or None
    )
    await db.commit()
    return await detail_lot(db, lot.id, user)


# ──────────────────────────────────────────────────────────────────────
# Lectures
# ──────────────────────────────────────────────────────────────────────


def _lot_resume(lot: LotPaiement, noms: Dict[int, str]) -> Dict[str, Any]:
    if lot.envoi_auto:
        libelles = LIBELLES_STATUT_AUTO
    else:
        libelles = LIBELLES_STATUT_INTERAC if lot.mode == "interac" else LIBELLES_STATUT
    libelle = libelles.get(lot.statut, lot.statut)
    if lot.envoi_auto and lot.auto_environnement == "test" and lot.statut in ("transmis", "paye"):
        libelle = "Terminé (test)"
    return {
        "id": lot.id,
        "entreprise_id": lot.entreprise_id,
        "mode": lot.mode,
        "statut": lot.statut,
        "statut_libelle": libelle,
        "envoi_auto": bool(lot.envoi_auto),
        "auto_environnement": lot.auto_environnement,
        "auto_erreur": lot.auto_erreur,
        "preleve_le": _iso(lot.preleve_le),
        "date_paiement": lot.date_paiement.isoformat(),
        "total": dollars(lot.total_cents),
        "nb_lignes": lot.nb_lignes,
        "note": lot.note,
        "approbations_requises": lot.approbations_requises,
        "cree_par": noms.get(lot.cree_par_user_id or 0),
        "cree_le": _iso(lot.created_at),
        "soumis_le": _iso(lot.soumis_le),
        "approuve_le": _iso(lot.approuve_le),
        "fichier_numero": lot.fichier_numero,
        "fichier_cree_le": _iso(lot.fichier_cree_le),
        "envoi_prepare_le": _iso(lot.envoi_prepare_le),
        "transmis_le": _iso(lot.transmis_le),
        "paye_le": _iso(lot.paye_le),
        "annule_le": _iso(lot.annule_le),
    }


async def lots(
    db: AsyncSession, entreprise_id: int, *, statut: Optional[str] = None, limit: int = 50
) -> List[Dict[str, Any]]:
    await _entreprise(db, entreprise_id)
    q = select(LotPaiement).where(LotPaiement.entreprise_id == entreprise_id)
    if statut == "en_cours":
        q = q.where(LotPaiement.statut.in_(STATUTS_ACTIFS))
    elif statut:
        q = q.where(LotPaiement.statut == statut)
    rows = (await db.execute(q.order_by(LotPaiement.id.desc()).limit(limit))).scalars().all()
    noms = await _noms(db, [l.cree_par_user_id for l in rows])
    return [_lot_resume(l, noms) for l in rows]


async def detail_lot(db: AsyncSession, lot_id: int, user: User) -> Dict[str, Any]:
    lot = await _lot(db, lot_id)
    lignes = await _lignes(db, lot.id)
    decisions = (
        await db.execute(
            select(LotPaiementApprobation)
            .where(LotPaiementApprobation.lot_id == lot.id)
            .order_by(LotPaiementApprobation.id)
        )
    ).scalars().all()
    evenements = (
        await db.execute(
            select(PaiementEvenement)
            .where(PaiementEvenement.lot_id == lot.id)
            .order_by(PaiementEvenement.id.desc())
            .limit(100)
        )
    ).scalars().all()
    compte_ids = {l.compte_bancaire_id for l in lignes if l.compte_bancaire_id}
    comptes_l = (
        {
            c.id: c
            for c in (
                await db.execute(
                    select(FournisseurCompteBancaire).where(FournisseurCompteBancaire.id.in_(list(compte_ids)))
                )
            ).scalars().all()
        }
        if compte_ids
        else {}
    )
    noms = await _noms(
        db,
        [
            lot.cree_par_user_id, lot.soumis_par_user_id, lot.fichier_cree_par_user_id,
            lot.envoi_prepare_par_user_id, lot.transmis_par_user_id, lot.annule_par_user_id,
            *[d.user_id for d in decisions], *[ev.user_id for ev in evenements],
            *[c.decide_par_user_id for c in comptes_l.values()],
            *[l.envoye_par_user_id for l in lignes],
        ],
    )
    etat: Dict[str, Any] = {}
    try:
        _, _, etat = await _entreprise_qbo(db, lot.entreprise_id)
    except PaiementErreur:
        pass
    approbateur = await peut_approuver(db, user)
    a_prepare = _a_prepare(lot, user)
    a_decide = any(d.user_id == user.id for d in decisions)
    s = lot.statut
    interac = lot.mode == "interac"
    envoyes = any(l.envoye_le for l in lignes)
    # Paiement automatique (VoPay).
    r = await _reglage(db, lot.entreprise_id)
    auto = bool(lot.envoi_auto)
    test = auto and lot.auto_environnement == "test"
    suivi_auto: Optional[Dict[str, Any]] = None
    if auto:
        from app.services import paiements_auto

        suivi_auto = await paiements_auto.detail(db, lot, lignes, approbateur)
    ops_ouvertes = bool(
        suivi_auto and any(o["statut"] in ("a_envoyer", "envoi", "incertain", "en_cours") for o in suivi_auto["operations"])
    )
    virements: List[Dict[str, Any]] = []
    if interac:
        # Un virement par fournisseur, vers le destinataire figé à la
        # soumission : ce que l'approbateur saisit dans AccèsD.
        for vid, groupe in _par_fournisseur(lignes).items():
            premiere = groupe[0]
            c = comptes_l.get(premiere.compte_bancaire_id or 0)
            total = sum(int(l.montant_cents) for l in groupe)
            virements.append(
                {
                    "fournisseur_id": vid,
                    "fournisseur": premiere.fournisseur_nom,
                    "destinataire": c.interac_destinataire if c else None,
                    "destinataire_statut": c.statut if c else None,
                    "montant": dollars(total),
                    "nb_factures": len(groupe),
                    "message": _message_interac([l.numero_facture for l in groupe]),
                    "depasse_limite": total > LIMITE_INTERAC_CENTS,
                    "envoye_le": _iso(premiere.envoye_le),
                    "envoye_par": noms.get(premiere.envoye_par_user_id or 0),
                    "reference": premiere.reference_interac,
                }
            )
    out = _lot_resume(lot, noms)
    out.update(
        {
            "soumis_par": noms.get(lot.soumis_par_user_id or 0),
            "fichier_date": lot.fichier_date.isoformat() if lot.fichier_date else None,
            "fichier_cree_par": noms.get(lot.fichier_cree_par_user_id or 0),
            "envoi_prepare_par": noms.get(lot.envoi_prepare_par_user_id or 0),
            "transmis_par": noms.get(lot.transmis_par_user_id or 0),
            "annule_par": noms.get(lot.annule_par_user_id or 0),
            "motif_annulation": lot.motif_annulation,
            "lignes": [
                {
                    "id": l.id,
                    "qbo_bill_id": l.qbo_bill_id,
                    "fournisseur_id": l.qbo_vendor_id,
                    "fournisseur": l.fournisseur_nom,
                    "numero_facture": l.numero_facture,
                    "date_facture": l.date_facture.isoformat() if l.date_facture else None,
                    "echeance": l.echeance.isoformat() if l.echeance else None,
                    "solde": dollars(l.solde_cents),
                    "montant": dollars(l.montant_cents),
                    "lien_qbo": lien_qbo(etat.get("environment"), etat.get("realm_id"), "Bill", l.qbo_bill_id),
                    "compte": (
                        _resume_compte(comptes_l[l.compte_bancaire_id], noms)
                        if l.compte_bancaire_id in comptes_l
                        else None
                    ),
                    "envoye_le": _iso(l.envoye_le),
                    "envoye_par": noms.get(l.envoye_par_user_id or 0),
                    "reference_interac": l.reference_interac,
                    "qbo_bill_payment_id": l.qbo_bill_payment_id,
                    "lien_paiement_qbo": _lien_paiement_qbo(etat, l.qbo_bill_payment_id),
                    "erreur_qbo": l.erreur_qbo,
                }
                for l in lignes
            ],
            "decisions": [
                {
                    "par": noms.get(d.user_id or 0),
                    "decision": d.decision,
                    "commentaire": d.commentaire,
                    "le": _iso(d.created_at),
                }
                for d in decisions
            ],
            "journal": [
                {"action": ev.action, "detail": ev.detail, "par": noms.get(ev.user_id or 0), "le": _iso(ev.created_at)}
                for ev in evenements
            ],
            "virements": virements if not auto else [],
            "limite_interac": dollars(LIMITE_INTERAC_CENTS),
            # Paiement automatique : réglage actuel de l'entreprise (pour un
            # lot pas encore approuvé) et suivi du lot payé par VoPay.
            "auto_entreprise": auto_actif(r),
            "auto_environnement_entreprise": ((r.auto_environnement if r else None) or "test") if auto_actif(r) else None,
            "auto_erreur": lot.auto_erreur,
            "auto_prochain_essai": _iso(lot.auto_prochain_essai) if lot.auto_erreur else None,
            "auto": suivi_auto,
            "actions": {
                "modifier": s == "brouillon",
                "soumettre": s == "brouillon",
                "remettre_en_brouillon": s in ("soumis", "refuse") or (s in ("approuve", "echec") and approbateur),
                "approuver": s == "soumis" and approbateur and not a_prepare and not a_decide,
                "refuser": s == "soumis" and approbateur and not a_prepare,
                "creer_fichier": not auto and not interac and s in ("approuve", "fichier_cree") and approbateur,
                "marquer_transmis": not auto and not interac and s == "fichier_cree" and approbateur,
                "preparer_envoi": not auto and interac and s == "approuve" and approbateur,
                "marquer_envoye": not auto and interac and s == "a_envoyer" and approbateur,
                "enregistrer_qbo": s == "transmis" and not test,
                "annuler": s in ("brouillon", "soumis", "refuse")
                or (s in ("approuve", "fichier_cree", "echec") and approbateur)
                or (s == "a_envoyer" and approbateur and not envoyes)
                or (test and s in STATUTS_AUTO_EN_ROUTE and approbateur),
                "reessayer_auto": auto and approbateur and (s == "echec" or (s == "approuve" and bool(lot.auto_erreur))),
                "verifier_auto": auto
                and (s in STATUTS_AUTO_EN_ROUTE or ops_ouvertes or (s in ("approuve", "transmis") and bool(lot.auto_erreur))),
            },
            "a_prepare": a_prepare,
        }
    )
    return out


async def journal(db: AsyncSession, entreprise_id: int, *, limit: int = 100) -> List[Dict[str, Any]]:
    await _entreprise(db, entreprise_id)
    rows = (
        await db.execute(
            select(PaiementEvenement)
            .where(PaiementEvenement.entreprise_id == entreprise_id)
            .order_by(PaiementEvenement.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    noms = await _noms(db, [r.user_id for r in rows])
    return [
        {
            "action": r.action,
            "detail": r.detail,
            "lot_id": r.lot_id,
            "par": noms.get(r.user_id or 0),
            "le": _iso(r.created_at),
        }
        for r in rows
    ]
