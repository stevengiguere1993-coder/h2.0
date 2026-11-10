"""Admin locative (Phil 2026-11-10) — carnet de contacts et avis de renouvellement
pour des baux HORS SYSTÈME (personnes qui ne sont pas des locataires Kratos).

- **Contacts** : le carnet de cette section seulement. Toute personne nommée
  dans un bail indépendant ou un avis y entre d'elle-même (« une fois une
  personne créée, je peux venir la sélectionner la fois d'après ») ; rien ne
  touche aux fiches locataires, aux loyers ni à la facturation de Kratos.
- **Avis de renouvellement** : le formulaire officiel TAL-806 (avis
  d'augmentation de loyer et de modification d'une autre condition du bail),
  rempli par LE MÊME générateur que « Suivis annuels », envoyé par la même
  porte de courriel et répondu sur la même page publique (accepter / refuser /
  quitter). L'avis porte TOUJOURS la date du jour de son envoi : elle n'est
  jamais saisie, et un avis envoyé ne se modifie plus.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_locatif import AVIS_MODES, CONTACT_ROLES, AdmLocAvis, AdmLocContact
from app.models.immobilier import ImmDocument

log = logging.getLogger(__name__)

DOC_TYPE_AVIS = "avis_modification"
#: Statuts où le locataire a répondu (ou est réputé l'avoir fait) : l'avis est figé.
STATUTS_REPONDUS: tuple[str, ...] = ("accepte", "refuse", "depart", "repute_accepte")


class AdminLocatifError(Exception):
    http_status = 400

    def __init__(self, message: str, *, http_status: Optional[int] = None):
        super().__init__(message)
        self.message = message
        if http_status is not None:
            self.http_status = http_status


# ─── Petits outils ────────────────────────────────────────────────────


def _texte(v: Any, n: int = 255) -> Optional[str]:
    t = str(v or "").strip()[:n]
    return t or None


def _nombre(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _date(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _cle(v: Any) -> str:
    """Clé de comparaison d'un texte : sans casse, sans accents, espaces réduits —
    faite en Python pour donner le même résultat sur toutes les bases."""
    import unicodedata

    brut = unicodedata.normalize("NFKD", str(v or ""))
    return " ".join("".join(c for c in brut if not unicodedata.combining(c)).casefold().split())


def aujourd_hui() -> date:
    """La date du jour À MONTRÉAL (un avis envoyé le 30 à 21 h ne porte pas le 1er)."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Toronto")).date()
    except Exception:  # noqa: BLE001 — pas de base de fuseaux : heure normale de l'Est
        return (datetime.now(timezone.utc) - timedelta(hours=5)).date()


def _decaler_mois(d: date, mois: int) -> date:
    """Même jour ``mois`` mois plus tard (ou plus tôt) ; 31 → dernier jour d'un mois court."""
    total = d.year * 12 + (d.month - 1) + mois
    y, m = divmod(total, 12)
    for jour in (d.day, 30, 29, 28):
        try:
            return date(y, m + 1, jour)
        except ValueError:
            continue
    return date(y, m + 1, 28)


# ─── Contacts ─────────────────────────────────────────────────────────


def resume_contact(c: AdmLocContact) -> dict[str, Any]:
    return {
        "id": c.id, "nom": c.nom, "telephone": c.telephone, "courriel": c.courriel, "adresse": c.adresse,
        "role": c.role, "notes": c.notes, "actif": bool(c.actif),
        "created_by_email": c.created_by_email,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


async def lister_contacts(
    db: AsyncSession, *, q: Optional[str] = None, inclure_archives: bool = False, limit: int = 500
) -> list[AdmLocContact]:
    # Carnet de petite taille : le filtre et le tri se font en Python (recherche sans
    # casse ni accents, identique sur toutes les bases).
    stmt = select(AdmLocContact)
    if not inclure_archives:
        stmt = stmt.where(AdmLocContact.actif.is_(True))
    rows = list((await db.execute(stmt)).scalars().all())
    terme = _cle(q)
    if terme:
        rows = [c for c in rows if any(terme in _cle(x) for x in (c.nom, c.courriel, c.telephone, c.adresse))]
    rows.sort(key=lambda c: (_cle(c.nom), c.id))
    return rows[:limit]


async def creer_contact(db: AsyncSession, *, user, champs: dict[str, Any]) -> AdmLocContact:
    nom = _texte(champs.get("nom"))
    if not nom:
        raise AdminLocatifError("Le nom du contact est requis.", http_status=422)
    role = champs.get("role") if champs.get("role") in CONTACT_ROLES else None
    now = datetime.now(timezone.utc)
    c = AdmLocContact(
        nom=nom, telephone=_texte(champs.get("telephone"), 40), courriel=_texte(champs.get("courriel"), 320),
        adresse=_texte(champs.get("adresse"), 500), role=role, notes=_texte(champs.get("notes"), 4000),
        actif=True, created_by_email=getattr(user, "email", None),
    )
    c.created_at = now
    c.updated_at = now
    db.add(c)
    await db.flush()
    return c


async def modifier_contact(db: AsyncSession, c: AdmLocContact, champs: dict[str, Any]) -> AdmLocContact:
    if "nom" in champs:
        nom = _texte(champs.get("nom"))
        if not nom:
            raise AdminLocatifError("Le nom du contact est requis.", http_status=422)
        c.nom = nom
    for k, n in (("telephone", 40), ("courriel", 320), ("adresse", 500), ("notes", 4000)):
        if k in champs:
            setattr(c, k, _texte(champs.get(k), n))
    if "role" in champs:
        c.role = champs.get("role") if champs.get("role") in CONTACT_ROLES else None
    if "actif" in champs and champs.get("actif") is not None:
        c.actif = bool(champs.get("actif"))
    c.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return c


async def memoriser_personnes(db: AsyncSession, personnes: list[dict[str, Any]], *, user) -> list[int]:
    """Chaque personne NOMMÉE d'un bail indépendant ou d'un avis entre au carnet,
    ou met sa fiche à jour (dernières coordonnées saisies). Même nom + courriel
    différent = une autre personne (homonyme). Retourne les ids touchés."""
    touches: list[int] = []
    carnet = list((await db.execute(select(AdmLocContact).order_by(AdmLocContact.id))).scalars().all())
    for p in personnes or []:
        if not isinstance(p, dict):
            continue
        nom = _texte(p.get("nom"))
        if not nom:
            continue
        courriel = _texte(p.get("courriel"), 320)
        meme_nom = [c for c in carnet if _cle(c.nom) == _cle(nom)]
        cible: Optional[AdmLocContact] = None
        if courriel:
            cible = next((c for c in meme_nom if _cle(c.courriel) == _cle(courriel)), None)
            if cible is None:
                cible = next((c for c in meme_nom if not (c.courriel or "").strip()), None)
        elif meme_nom:
            cible = meme_nom[0]
        if cible is None:
            cible = await creer_contact(db, user=user, champs={**p, "nom": nom})
            carnet.append(cible)
        else:
            maj: dict[str, Any] = {"actif": True}
            for k in ("telephone", "courriel", "adresse"):
                if _texte(p.get(k), 500):
                    maj[k] = p.get(k)
            if p.get("role") in CONTACT_ROLES:
                maj["role"] = p.get("role")
            await modifier_contact(db, cible, maj)
        touches.append(cible.id)
    return touches


# ─── Avis de renouvellement (TAL-806) ─────────────────────────────────


def adresse_avis(a: AdmLocAvis) -> str:
    base = (a.logement_adresse or "").strip()
    if (a.logement_numero or "").strip():
        base += f", app. {a.logement_numero.strip()}"
    if (a.logement_ville or "").strip():
        base += f", {a.logement_ville.strip()}"
    return base.strip(" ,")


def titre_avis(a: AdmLocAvis) -> str:
    adr = adresse_avis(a)
    return (f"Avis de modification du bail — {adr}" if adr else "Avis de modification du bail")[:255]


def nouvelle_periode_defaut(fin: Optional[date]) -> tuple[Optional[date], Optional[date]]:
    """Reconduction d'un an : du lendemain de la fin au même jour un an plus tard."""
    if not fin:
        return None, None
    debut = fin + timedelta(days=1)
    return debut, _decaler_mois(debut, 12) - timedelta(days=1)


def fenetre_legale(a: AdmLocAvis, *, aujourd: Optional[date] = None) -> Optional[dict[str, Any]]:
    """Quand l'avis doit être donné (art. 1942 C.c.Q.) — information, jamais un blocage :
    bail de 12 mois ou plus → de 6 à 3 mois avant la fin ; moins de 12 mois → de 2 à 1 mois ;
    durée indéterminée → de 2 à 1 mois avant la modification. (Chambre : 20 à 10 jours.)"""
    auj = aujourd or aujourd_hui()
    if a.bail_date_fin:
        long_terme = bool(a.bail_date_debut) and (a.bail_date_fin - a.bail_date_debut).days >= 360
        if long_terme or not a.bail_date_debut:
            du, au, regle = _decaler_mois(a.bail_date_fin, -6), _decaler_mois(a.bail_date_fin, -3), "bail de 12 mois ou plus : de 6 à 3 mois avant la fin"
        else:
            du, au, regle = _decaler_mois(a.bail_date_fin, -2), _decaler_mois(a.bail_date_fin, -1), "bail de moins de 12 mois : de 2 à 1 mois avant la fin"
    elif a.nouvelle_date_debut:
        du, au, regle = _decaler_mois(a.nouvelle_date_debut, -2), _decaler_mois(a.nouvelle_date_debut, -1), "bail à durée indéterminée : de 2 à 1 mois avant la modification"
    else:
        return None
    ref = a.avis_envoye_le or auj
    etat = "avant" if ref < du else ("apres" if ref > au else "dans")
    return {"du": du.isoformat(), "au": au.isoformat(), "regle": regle, "etat": etat}


def contexte_avis(a: AdmLocAvis, *, date_emission: Optional[date] = None):
    from app.services.tal_forms import TalContext

    return TalContext(
        locateur_nom=a.locateur_nom, locateur_adresse=a.locateur_adresse, locateur_telephone=a.locateur_telephone,
        locateur_courriel=a.locateur_courriel,
        locataire_nom=a.locataire_nom, locataire_email=a.locataire_courriel,
        logement_adresse=a.logement_adresse, logement_numero=a.logement_numero, logement_ville=a.logement_ville,
        bail_date_debut=a.bail_date_debut, bail_date_fin=a.bail_date_fin,
        bail_loyer_mensuel=(float(a.loyer_actuel) if a.loyer_actuel is not None else None),
        modif_mode=a.modif_mode,
        nouveau_loyer=(float(a.nouveau_loyer) if a.nouveau_loyer is not None else None),
        hausse_montant=(float(a.hausse_montant) if a.hausse_montant is not None else None),
        hausse_pct=(float(a.hausse_pct) if a.hausse_pct is not None else None),
        nouvelle_date_debut=a.nouvelle_date_debut, nouvelle_date_fin=a.nouvelle_date_fin,
        motif_modification=a.autres_modifications,
        date_emission=date_emission or aujourd_hui(),
    )


async def _modele_avis(db: AsyncSession) -> Optional[bytes]:
    """PDF modèle TAL-806 remplacé dans Paramètres → Modèles de documents, s'il y en a un."""
    try:
        from sqlalchemy.orm import undefer

        from app.models.immobilier import ImmDocTemplate

        ov = (
            await db.execute(
                select(ImmDocTemplate).options(undefer(ImmDocTemplate.pdf_blob)).where(ImmDocTemplate.type == DOC_TYPE_AVIS)
            )
        ).scalar_one_or_none()
        return ov.pdf_blob if ov is not None else None
    except Exception:  # noqa: BLE001
        log.exception("Lecture du modèle avis_modification échouée")
        return None


async def generer_pdf(db: AsyncSession, a: AdmLocAvis, *, user, date_emission: Optional[date] = None) -> ImmDocument:
    """(Re)génère le PDF officiel de l'avis et le range dans ``imm_documents``
    sans aucun rattachement Kratos. Daté du jour (ou du jour de l'envoi)."""
    from app.services.tal_forms import generate_tal_pdf

    pdf = generate_tal_pdf(DOC_TYPE_AVIS, contexte_avis(a, date_emission=date_emission), await _modele_avis(db))
    params = {
        "admin_locatif_avis_id": a.id, "independant": True,
        "locataire_nom": a.locataire_nom, "locateur_nom": a.locateur_nom,
    }
    doc: Optional[ImmDocument] = await db.get(ImmDocument, a.document_id) if a.document_id else None
    if doc is None:
        from app.api.v1.endpoints.immobilier_documents import save_document

        doc = await save_document(
            db, bail_id=None, locataire_id=None, immeuble_id=None, doc_type=DOC_TYPE_AVIS,
            titre=titre_avis(a), params=params, pdf=pdf, created_by_email=getattr(user, "email", None),
        )
        a.document_id = doc.id
    else:
        doc.pdf_blob = pdf
        doc.titre = titre_avis(a)
        doc.params_json = json.dumps(params, default=str)
    await db.flush()
    return doc


_CHAMPS_TEXTE: tuple[tuple[str, int], ...] = (
    ("libelle", 255), ("locateur_nom", 255), ("locateur_adresse", 500), ("locateur_telephone", 40),
    ("locateur_courriel", 320), ("locataire_nom", 255), ("locataire_courriel", 320),
    ("logement_adresse", 500), ("logement_numero", 32), ("logement_ville", 128), ("autres_modifications", 4000),
)
_CHAMPS_DATE: tuple[str, ...] = ("bail_date_debut", "bail_date_fin", "nouvelle_date_debut", "nouvelle_date_fin")
_CHAMPS_NOMBRE: tuple[str, ...] = ("loyer_actuel", "nouveau_loyer", "hausse_montant", "hausse_pct")


def _appliquer(a: AdmLocAvis, champs: dict[str, Any]) -> None:
    for k, n in _CHAMPS_TEXTE:
        if k in champs:
            setattr(a, k, _texte(champs.get(k), n))
    for k in _CHAMPS_DATE:
        if k in champs:
            setattr(a, k, _date(champs.get(k)))
    for k in _CHAMPS_NOMBRE:
        if k in champs:
            v = _nombre(champs.get(k))
            setattr(a, k, (max(v, 0.0) if v is not None else None))
    if "modif_mode" in champs:
        a.modif_mode = champs.get("modif_mode") if champs.get("modif_mode") in AVIS_MODES else None
    # Une seule forme de hausse à la fois (comme les trois cases du formulaire).
    if a.modif_mode == "nouveau_loyer":
        a.hausse_montant = a.hausse_pct = None
    elif a.modif_mode == "hausse_montant":
        a.nouveau_loyer = a.hausse_pct = None
    elif a.modif_mode == "hausse_pct":
        a.nouveau_loyer = a.hausse_montant = None
    # Nouvelle période : par défaut, reconduction d'un an après la fin du bail.
    if a.bail_date_fin and not a.nouvelle_date_debut and not a.nouvelle_date_fin:
        a.nouvelle_date_debut, a.nouvelle_date_fin = nouvelle_periode_defaut(a.bail_date_fin)


def _personnes_de_l_avis(a: AdmLocAvis) -> list[dict[str, Any]]:
    return [
        {"nom": a.locateur_nom, "telephone": a.locateur_telephone, "courriel": a.locateur_courriel,
         "adresse": a.locateur_adresse, "role": "locateur"},
        {"nom": a.locataire_nom, "courriel": a.locataire_courriel, "role": "locataire"},
    ]


async def creer_avis(db: AsyncSession, *, user, champs: dict[str, Any]) -> AdmLocAvis:
    now = datetime.now(timezone.utc)
    a = AdmLocAvis(status="brouillon", created_by_user_id=getattr(user, "id", None), created_by_email=getattr(user, "email", None))
    a.created_at = now
    a.updated_at = now
    _appliquer(a, champs)
    db.add(a)
    await db.flush()
    await generer_pdf(db, a, user=user)
    await memoriser_personnes(db, _personnes_de_l_avis(a), user=user)
    return a


async def modifier_avis(db: AsyncSession, a: AdmLocAvis, *, user, champs: dict[str, Any]) -> AdmLocAvis:
    if a.status != "brouillon":
        raise AdminLocatifError(
            "Un avis envoyé ne se modifie plus : il fait foi tel qu'il est parti. Annule-le et prépare un nouvel avis.",
            http_status=409,
        )
    _appliquer(a, champs)
    a.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await generer_pdf(db, a, user=user)
    await memoriser_personnes(db, _personnes_de_l_avis(a), user=user)
    return a


async def envoyer_avis(db: AsyncSession, a: AdmLocAvis, *, user, courriel: Optional[str] = None) -> dict[str, Any]:
    """Envoie l'avis au locataire (lien de réponse en ligne), par la porte
    unique des courriels aux locataires. Premier envoi : le PDF est refait à
    la date DU JOUR et le délai d'un mois de réponse commence. Renvoi d'un avis
    déjà parti : même document, même date — seul le lien repart."""
    from app.api.v1.endpoints.immobilier_documents import EnvoyerSignatureRequest, envoyer_signature
    from app.services.audit import log_action

    if a.status in STATUTS_REPONDUS:
        raise AdminLocatifError("Le locataire a déjà répondu à cet avis.", http_status=409)
    if a.status == "annule":
        raise AdminLocatifError("Cet avis est annulé — prépare un nouvel avis.", http_status=409)
    dest = (courriel or a.locataire_courriel or "").strip()
    if not dest:
        raise AdminLocatifError("Aucun courriel pour le locataire : ajoute-le à l'avis avant d'envoyer.", http_status=422)
    if not (a.locataire_nom or "").strip() or not (a.locateur_nom or "").strip() or not (a.logement_adresse or "").strip():
        raise AdminLocatifError("Nom du locateur, nom du locataire et adresse du logement sont requis pour envoyer l'avis.", http_status=422)
    if not a.modif_mode and not (a.autres_modifications or "").strip():
        raise AdminLocatifError("L'avis ne propose aucune modification : indique la hausse de loyer ou une autre modification.", http_status=422)
    if a.modif_mode:
        valeur = {"nouveau_loyer": a.nouveau_loyer, "hausse_montant": a.hausse_montant, "hausse_pct": a.hausse_pct}.get(a.modif_mode)
        if valeur is None or float(valeur) <= 0:
            raise AdminLocatifError(
                "Il manque le montant de la hausse (ou le nouveau loyer) : complète l'avis avant de l'envoyer.", http_status=422
            )
    try:
        requete = EnvoyerSignatureRequest(email=dest)
    except Exception as exc:  # noqa: BLE001 — adresse refusée par la validation
        raise AdminLocatifError(f"Courriel du locataire invalide : {dest}", http_status=422) from exc
    premier_envoi = a.status == "brouillon"
    jour = aujourd_hui()
    if premier_envoi:
        await generer_pdf(db, a, user=user, date_emission=jour)
    if not a.document_id:
        raise AdminLocatifError("PDF de l'avis introuvable.", http_status=404)
    await db.commit()
    resultat = await envoyer_signature(a.document_id, requete, db, user)
    await db.refresh(a)
    if premier_envoi:
        a.status = "propose"
        a.avis_envoye_le = jour
    a.envoye_a = dest[:320]
    a.updated_at = datetime.now(timezone.utc)
    await log_action(
        db, user=user, action=("admin_locatif.avis_envoye" if premier_envoi else "admin_locatif.avis_renvoye"),
        entity_type="adm_loc_avis", entity_id=a.id,
        details={"envoye_a": dest, "document_id": a.document_id, "avis_envoye_le": a.avis_envoye_le.isoformat() if a.avis_envoye_le else None},
    )
    await db.commit()
    return {"envoye_a": dest, "premier_envoi": premier_envoi, "url": resultat.url}


async def annuler_avis(db: AsyncSession, a: AdmLocAvis, *, user) -> AdmLocAvis:
    from app.services.audit import log_action

    if a.status in STATUTS_REPONDUS:
        raise AdminLocatifError("Le locataire a déjà répondu : cet avis reste au dossier.", http_status=409)
    etait_envoye = a.status == "propose"
    a.status = "annule"
    a.updated_at = datetime.now(timezone.utc)
    if a.document_id:
        doc = await db.get(ImmDocument, a.document_id)
        if doc is not None:
            doc.signature_token = None       # le lien envoyé cesse de fonctionner
    await log_action(db, user=user, action="admin_locatif.avis_annule", entity_type="adm_loc_avis", entity_id=a.id,
                     details={"etait_envoye": etait_envoye})
    await db.flush()
    return a


def _plus_un_mois(d: date) -> date:
    return _decaler_mois(d, 1)


async def actualiser_delais(db: AsyncSession, avis: list[AdmLocAvis]) -> None:
    """Art. 1945 C.c.Q. : un mois sans réponse = réputé accepté (même règle que
    le cycle de renouvellement Kratos)."""
    auj = aujourd_hui()
    change = False
    for a in avis:
        if a.status == "propose" and a.avis_envoye_le and auj > _plus_un_mois(a.avis_envoye_le):
            a.status = "repute_accepte"
            a.reponse_le = _plus_un_mois(a.avis_envoye_le)
            change = True
    if change:
        await db.flush()


def resume_avis(a: AdmLocAvis, doc: Optional[ImmDocument] = None) -> dict[str, Any]:
    def _f(v: Any) -> Optional[float]:
        return float(v) if v is not None else None

    def _d(v: Optional[date]) -> Optional[str]:
        return v.isoformat() if v else None

    out: dict[str, Any] = {
        "id": a.id, "libelle": a.libelle, "titre": titre_avis(a), "adresse": adresse_avis(a),
        "locateur_nom": a.locateur_nom, "locateur_adresse": a.locateur_adresse, "locateur_telephone": a.locateur_telephone,
        "locateur_courriel": a.locateur_courriel, "locataire_nom": a.locataire_nom, "locataire_courriel": a.locataire_courriel,
        "logement_adresse": a.logement_adresse, "logement_numero": a.logement_numero, "logement_ville": a.logement_ville,
        "bail_date_debut": _d(a.bail_date_debut), "bail_date_fin": _d(a.bail_date_fin), "loyer_actuel": _f(a.loyer_actuel),
        "modif_mode": a.modif_mode, "nouveau_loyer": _f(a.nouveau_loyer), "hausse_montant": _f(a.hausse_montant),
        "hausse_pct": _f(a.hausse_pct), "nouvelle_date_debut": _d(a.nouvelle_date_debut), "nouvelle_date_fin": _d(a.nouvelle_date_fin),
        "autres_modifications": a.autres_modifications,
        "status": a.status, "avis_envoye_le": _d(a.avis_envoye_le), "reponse_le": _d(a.reponse_le), "refus_motif": a.refus_motif,
        "echeance_reponse": _d(_plus_un_mois(a.avis_envoye_le)) if a.avis_envoye_le else None,
        "document_id": a.document_id, "envoye_a": a.envoye_a,
        "fenetre": fenetre_legale(a),
        "created_by_email": a.created_by_email,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
    if doc is not None:
        out["document"] = {
            "envoye_le": doc.envoye_le.isoformat() if doc.envoye_le else None,
            "ouvert_le": doc.ouvert_le.isoformat() if doc.ouvert_le else None,
            "signed_at": doc.signed_at.isoformat() if doc.signed_at else None,
            "signed_by_name": doc.signed_by_name,
        }
    return out


async def lister_avis(db: AsyncSession, *, inclure_annules: bool = False, limit: int = 300) -> list[dict[str, Any]]:
    stmt = select(AdmLocAvis).order_by(AdmLocAvis.id.desc()).limit(limit)
    if not inclure_annules:
        stmt = stmt.where(AdmLocAvis.status != "annule")
    rows = list((await db.execute(stmt)).scalars().all())
    await actualiser_delais(db, rows)
    ids = [a.document_id for a in rows if a.document_id]
    docs: dict[int, ImmDocument] = {}
    if ids:
        for d in (await db.execute(select(ImmDocument).where(ImmDocument.id.in_(ids)))).scalars().all():
            docs[d.id] = d
    return [resume_avis(a, docs.get(a.document_id) if a.document_id else None) for a in rows]


__all__ = [
    "AdminLocatifError", "DOC_TYPE_AVIS", "STATUTS_REPONDUS", "aujourd_hui",
    "resume_contact", "lister_contacts", "creer_contact", "modifier_contact", "memoriser_personnes",
    "adresse_avis", "titre_avis", "nouvelle_periode_defaut", "fenetre_legale", "contexte_avis", "generer_pdf",
    "creer_avis", "modifier_avis", "envoyer_avis", "annuler_avis", "actualiser_delais", "resume_avis", "lister_avis",
]
