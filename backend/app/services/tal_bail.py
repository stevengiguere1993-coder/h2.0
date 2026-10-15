"""Bail de logement officiel (TAL, formulaire 53000BAIL) — service.

Trois responsabilités :

1. **Mapping Kratos → formulaire TAL** (``preparer``) : tout ce que Kratos
   sait (immeuble, logement, locataire, garants, bail proposé, bail
   précédent, propriétaire) est posé dans le formulaire VIDE du schéma
   actif ; les clés de ``valeursPossibles`` sont utilisées telles quelles
   (jamais les libellés). Chaque champ garde son origine (donnée Kratos,
   défaut Paramètres, laissé pour la signature, inconnu) et les défauts
   sont listés « à vérifier » pour l'écran de confirmation. Les blocs de
   signature restent vides : la signature se fait ensuite avec l'outil
   eSign de Kratos (décision Phil 2026-10-15).
2. **Génération** (``generer``) : validation locale stricte → FRW111
   (ShortGuid, sauvegardé AVANT d'aller plus loin) → FRW122 (PDF base64)
   → archivage tel quel dans ``imm_documents`` (type « bail_tal »,
   verrouillé, jamais modifié) → coût TAL (2,99 $ en mode réel) → frais
   refacturé au propriétaire (8,99 $ par défaut, Paramètres) → audit.
   Jamais deux FRW111 pour une même transmission : un échec au FRW122 se
   relance avec le même ShortGuid.
3. **Connexion** : table ``tal_connexion`` (mode, URL, en-tête, chemins,
   clé CHIFFRÉE via ``secret_vault``) avec repli sur les variables
   d'environnement ``TAL_*``. La clé n'est jamais relue par l'API.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.integrations.tal.client import (
    MODE_REEL,
    MODE_SIMULATION,
    MODES,
    ClientTal,
    ConnexionTal,
    TalApiError,
    connexion_depuis_env,
)
from app.integrations.tal.schema import SchemaTal, charger_schema, squelette
from app.integrations.tal.validateur import Rapport, valider
from app.models.entreprise import Entreprise
from app.models.immobilier import (
    Bail,
    BailStatus,
    FraisManuelGestion,
    ImmDocument,
    ImmeubleOwnership,
    ImmLocataireContact,
    Immeuble,
    Locataire,
    Logement,
    PaiementLoyer,
)
from app.models.tal_bail import STATUTS_OUVERTS, TalConnexion, TalTransmission

log = logging.getLogger(__name__)

CONFIG_KEY = "tal_bail"
#: Coût facturé par le TAL pour chaque formulaire transmis (avant taxes).
COUT_TAL = 2.99
#: Formulaires gratuits au total (contrat), puis 2,99 $ chacun.
GRATUITS_TOTAL = 10
#: Type du document archivé (imm_documents). Distinct de « bail » : le
#: PDF du TAL n'est PAS signé — « bail » reste le bail signé au dossier.
DOC_TYPE = "bail_tal"

DEFAUTS: dict[str, Any] = {
    #: Frais refacturé au propriétaire par bail GÉNÉRÉ (mode réel) — file
    #: d'attente Facturation (frais manuels de gestion). 0 = aucun frais.
    "tarif_recharge": 8.99,
    "frais_auto": True,
    "libelle_frais": "Bail officiel TAL — {adresse} ({locataire})",
    #: Défauts du formulaire quand Kratos n'a pas la donnée.
    "mode_paiement_defaut": "virementBancaire",
    "chauffage_defaut": "electricite",
    "logement_sans_fumee": True,
    "animaux_defaut": False,
    "province_defaut": "Québec",
    #: Représentant du locateur pour la signature (Horizon). Vide = la
    #: personne qui génère le bail.
    "representant_nom": "",
    "representant_courriel": "",
    #: Champs que Kratos exige remplis avant tout appel (chemins).
    "requis": (
        "locateurs[0].nom,locataires[0].nom,adresseLogement[0].Rue,"
        "adresseLogement[0].Municipalite,coutLoyer,typeBail"
    ),
}

_NB_PIECES: dict[float, str] = {
    1.0: "un", 1.5: "un-demi", 2.0: "deux", 2.5: "deux-demi", 3.0: "trois",
    3.5: "trois-demi", 4.0: "quatre", 4.5: "quatre-demi", 5.0: "cinq",
    5.5: "cinq-demi", 6.0: "six", 6.5: "six-demi", 7.0: "sept", 7.5: "sept-demi",
}
_CP_RE = re.compile(r"\b([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z])\s?(\d[ABCEGHJ-NPRSTV-Z]\d)\b", re.I)
_APP_RE = re.compile(r"(?:\b(?:app\.?|apt\.?|appartement|appt\.?|unit[ée]?|logement|suite)\s*#?\s*|#\s*)([0-9]+[A-Za-z]?(?:-[0-9A-Za-z]+)?)\b", re.I)
_PROVINCE_RE = re.compile(r"\(?\b(qu[ée]bec|qc)\b\)?", re.I)
_CIVIQUE_RE = re.compile(r"^\s*(\d+[A-Za-z]?(?:\s?-\s?\d+[A-Za-z]?)?)\s*[,\s]\s*(.+)$")


# ─── Erreurs ───────────────────────────────────────────────────────────


class TalBailError(Exception):
    http_status = 400

    def __init__(self, message: str, *, http_status: Optional[int] = None, details: Any = None):
        super().__init__(message)
        self.message = message
        if http_status is not None:
            self.http_status = http_status
        self.details = details


class FormulaireInvalide(TalBailError):
    http_status = 422


class TransmissionFermee(TalBailError):
    http_status = 409


# ─── Configuration métier (Paramètres) ────────────────────────────────


def fusionner_config(cfg: Optional[dict[str, Any]]) -> dict[str, Any]:
    out = dict(DEFAUTS)
    for k, v in (cfg or {}).items():
        if v is not None and v != "":
            out[k] = v
    try:
        out["tarif_recharge"] = max(0.0, round(float(out["tarif_recharge"]), 2))
    except (TypeError, ValueError):
        out["tarif_recharge"] = DEFAUTS["tarif_recharge"]
    out["frais_auto"] = bool(out.get("frais_auto", True))
    out["logement_sans_fumee"] = bool(out.get("logement_sans_fumee", True))
    out["animaux_defaut"] = bool(out.get("animaux_defaut", False))
    return out


async def charger_config() -> dict[str, Any]:
    from app.services.automation_state import get_automation_config

    return fusionner_config(await get_automation_config(CONFIG_KEY))


def chemins_requis(config: dict[str, Any]) -> list[str]:
    brut = config.get("requis") or ""
    if isinstance(brut, list):
        return [str(x).strip() for x in brut if str(x).strip()]
    return [p.strip() for p in str(brut).split(",") if p.strip()]


# ─── Connexion (clé chiffrée) ─────────────────────────────────────────


async def _connexion_row(db: AsyncSession) -> Optional[TalConnexion]:
    return (
        await db.execute(
            select(TalConnexion).options(undefer(TalConnexion.cle_chiffree)).order_by(TalConnexion.id).limit(1)
        )
    ).scalars().first()


async def charger_connexion(db: Optional[AsyncSession]) -> tuple[ConnexionTal, dict[str, Any]]:
    """Connexion effective : la ligne ``tal_connexion`` (Paramètres) complète
    ou remplace les variables d'environnement ; la clé stockée est
    déchiffrée en mémoire. Retourne aussi des infos d'état (sans la clé)."""
    from app.services.secret_vault import decrypt_secret, vault_available

    cx = connexion_depuis_env()
    infos: dict[str, Any] = {
        "source_cle": "env" if cx.cle else None,
        "cle_posee_le": None,
        "cle_posee_par": None,
        "coffre_disponible": vault_available(),
        "cle_dechiffrable": bool(cx.cle),
    }
    if db is None:
        return cx, infos
    try:
        row = await _connexion_row(db)
    except Exception as exc:  # noqa: BLE001 — table absente au premier démarrage
        log.warning("tal_connexion illisible : %s", exc)
        return cx, infos
    if row is None:
        return cx, infos
    if row.mode in MODES:
        cx.mode = row.mode
    if row.api_url:
        cx.url = row.api_url.strip().rstrip("/")
    if row.entete_cle:
        cx.entete_cle = row.entete_cle.strip()
    if row.chemin_frw111:
        cx.chemin_frw111 = row.chemin_frw111.strip()
    if row.chemin_frw122:
        cx.chemin_frw122 = row.chemin_frw122.strip()
    chiffree = row.cle_chiffree
    if chiffree:
        infos["cle_posee_le"] = row.cle_posee_le
        infos["cle_posee_par"] = row.cle_posee_par
        try:
            cx.cle = decrypt_secret(chiffree)
            infos["source_cle"] = "kratos"
            infos["cle_dechiffrable"] = True
        except Exception as exc:  # noqa: BLE001
            log.warning("clé TAL indéchiffrable : %s", exc)
            infos["source_cle"] = "kratos"
            infos["cle_dechiffrable"] = False
            if not cx.cle:
                cx.cle = ""
    return cx, infos


async def enregistrer_connexion(
    db: AsyncSession,
    *,
    mode: Optional[str] = None,
    api_url: Optional[str] = None,
    entete_cle: Optional[str] = None,
    chemin_frw111: Optional[str] = None,
    chemin_frw122: Optional[str] = None,
    api_key: Optional[str] = None,
    effacer_cle: bool = False,
    user_email: Optional[str] = None,
) -> TalConnexion:
    """Upsert de la ligne unique. ``api_key`` (clair) est chiffrée tout de
    suite — refus explicite si aucun coffre n'est configuré."""
    from app.services.secret_vault import VaultNotConfigured, encrypt_secret

    row = await _connexion_row(db)
    if row is None:
        row = TalConnexion()
        db.add(row)
    now = datetime.now(timezone.utc)
    if mode is not None:
        m = (mode or "").strip().lower()
        if m not in MODES:
            raise TalBailError(f"Mode inconnu « {mode} » (simulation | reel).", http_status=422)
        row.mode = m
    if api_url is not None:
        row.api_url = api_url.strip().rstrip("/")[:500] or None
    if entete_cle is not None:
        row.entete_cle = entete_cle.strip()[:64] or None
    if chemin_frw111 is not None:
        row.chemin_frw111 = chemin_frw111.strip()[:255] or None
    if chemin_frw122 is not None:
        row.chemin_frw122 = chemin_frw122.strip()[:255] or None
    if effacer_cle:
        row.cle_chiffree = None
        row.cle_posee_le = None
        row.cle_posee_par = None
    elif api_key is not None and api_key.strip():
        try:
            row.cle_chiffree = encrypt_secret(api_key.strip())
        except VaultNotConfigured as exc:
            raise TalBailError(
                "Aucune clé de chiffrement sur le serveur (SUBSCRIPTION_ENCRYPTION_KEY "
                "ou DRIVE_TOKEN_ENCRYPTION_KEY) : la clé du TAL ne peut pas être "
                "stockée en clair — refus.",
                http_status=503,
            ) from exc
        row.cle_posee_le = now
        row.cle_posee_par = user_email
    row.updated_at = now
    row.updated_by_email = user_email
    await db.flush()
    return row


def _fabrique_client(connexion: ConnexionTal) -> ClientTal:
    """Indirection pour les tests (client factice sans réseau)."""
    return ClientTal(connexion)


# ─── Petits outils de mapping ─────────────────────────────────────────


def cle_nb_pieces(nb: Any) -> tuple[str, str]:
    """3.5 → (« trois-demi », ""), 8 → (« autre », « 8 »), None → ("", "")."""
    if nb is None or nb == "":
        return "", ""
    try:
        v = round(float(nb) * 2) / 2
    except (TypeError, ValueError):
        return "autre", str(nb)
    cle = _NB_PIECES.get(v)
    if cle:
        return cle, ""
    texte = f"{v:g}".replace(".5", "½")
    return "autre", texte


def decouper_adresse(
    texte: Optional[str],
    *,
    ville: Optional[str] = None,
    code_postal: Optional[str] = None,
    appartement: Optional[str] = None,
    province: str = "Québec",
) -> dict[str, str]:
    """« 8900 rue Saint-Hubert app. 3, Montréal (Québec) H2M 1Y7 » → les
    sept champs d'adresse du TAL. Ce qui n'est pas reconnu reste dans
    ``Rue`` plutôt que d'être perdu."""
    brut = (texte or "").strip()
    cp = (code_postal or "").strip().upper()
    m = _CP_RE.search(brut)
    if m:
        if not cp:
            cp = f"{m.group(1).upper()} {m.group(2).upper()}"
        brut = (brut[: m.start()] + " " + brut[m.end():]).strip(" ,")
    if cp and len(cp) == 6:
        cp = cp[:3] + " " + cp[3:]
    app = (appartement or "").strip()
    ma = _APP_RE.search(brut)
    if ma:
        if not app:
            app = ma.group(1)
        brut = (brut[: ma.start()] + " " + brut[ma.end():]).strip(" ,")
    prov = province
    mp = _PROVINCE_RE.search(brut)
    if mp:
        brut = (brut[: mp.start()] + " " + brut[mp.end():]).strip(" ,")
    morceaux = [p.strip() for p in re.split(r"\s*,\s*", brut) if p.strip()]
    rue_part = morceaux[0] if morceaux else ""
    municipalite = (ville or "").strip()
    if not municipalite and len(morceaux) >= 2:
        municipalite = morceaux[1]
    civique, rue = "", rue_part
    mc = _CIVIQUE_RE.match(rue_part)
    if mc:
        civique = re.sub(r"\s", "", mc.group(1))
        rue = mc.group(2).strip(" ,")
    rue = re.sub(r"\s{2,}", " ", rue).strip()
    if not (civique or rue or municipalite or cp or app):
        return {k: "" for k in ("NoCivique", "Appartement", "CodePostal", "Province", "Municipalite", "Rue", "AdresseComplete")}
    complete = " ".join(p for p in [civique, rue] if p)
    if app:
        complete += f", app. {app}"
    if municipalite:
        complete += f", {municipalite}"
    if prov:
        complete += f" ({prov})"
    if cp:
        complete += f" {cp}"
    return {
        "NoCivique": civique,
        "Appartement": app,
        "CodePostal": cp,
        "Province": prov if (civique or rue or municipalite) else "",
        "Municipalite": municipalite,
        "Rue": rue,
        "AdresseComplete": complete.strip(" ,"),
    }


def _telephone(v: Any) -> str:
    chiffres = re.sub(r"\D", "", str(v or ""))
    if len(chiffres) == 11 and chiffres.startswith("1"):
        chiffres = chiffres[1:]
    # Plan de numérotation nord-américain : indicatif et central ne
    # commencent jamais par 0 ou 1 (ex. « 055-… » lu sur une fiche = faux).
    if len(chiffres) != 10 or chiffres[0] in "01" or chiffres[3] in "01":
        return ""
    return f"{chiffres[:3]}-{chiffres[3:6]}-{chiffres[6:]}"


def _montant(v: Any) -> str:
    if v is None or v == "":
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:.0f}" if abs(f - round(f)) < 0.005 else f"{f:.2f}"


def _iso(d: Any) -> str:
    if isinstance(d, (date, datetime)):
        return d.strftime("%Y-%m-%d")
    return str(d) if d else ""


def _duree_texte(debut: Optional[date], fin: Optional[date]) -> str:
    """« 1er juillet → 30 juin » = 12 mois (la fin est le dernier jour
    inclus) ; sinon un nombre de semaines ou de jours."""
    if not debut or not fin or fin <= debut:
        return ""
    lendemain = fin + timedelta(days=1)
    if lendemain.day == debut.day:
        mois = (lendemain.year - debut.year) * 12 + (lendemain.month - debut.month)
        if mois >= 1:
            if mois % 12 == 0:
                n = mois // 12
                return f"{n} an" if n == 1 else f"{n} ans"
            return f"{mois} mois"
    jours = (lendemain - debut).days
    if jours % 7 == 0:
        n = jours // 7
        return f"{n} semaine" if n == 1 else f"{n} semaines"
    return f"{jours} jours"


def _vide(v: Any) -> bool:
    return v is None or v == "" or v == []


# ─── Contexte Kratos ──────────────────────────────────────────────────


@dataclass
class ContexteBail:
    bail: Bail
    logement: Logement
    immeuble: Optional[Immeuble]
    locataire: Optional[Locataire]
    colocataires: list[ImmLocataireContact] = field(default_factory=list)
    garants: list[ImmLocataireContact] = field(default_factory=list)
    entreprise: Optional[Entreprise] = None
    bail_precedent: Optional[Bail] = None
    loyer_plus_bas_12_mois: Optional[float] = None
    dernier_paiement_le: Optional[date] = None
    representant_nom: str = ""
    representant_courriel: str = ""

    def resume(self) -> dict[str, Any]:
        return {
            "bail_id": self.bail.id,
            "bail_statut": self.bail.status,
            "bail_document_id": self.bail.document_id,
            "logement_id": self.logement.id,
            "logement_numero": self.logement.numero,
            "immeuble_id": self.immeuble.id if self.immeuble else None,
            "immeuble_nom": self.immeuble.name if self.immeuble else None,
            "adresse": adresse_logement_texte(self),
            "locataire_id": self.locataire.id if self.locataire else None,
            "locataire_nom": self.locataire.full_name if self.locataire else None,
            "colocataires": [c.full_name for c in self.colocataires],
            "garants": [c.full_name for c in self.garants],
            "locateur": self.entreprise.name if self.entreprise else None,
            "bail_precedent_id": self.bail_precedent.id if self.bail_precedent else None,
            "bail_precedent_loyer": (
                float(self.bail_precedent.loyer_mensuel) if self.bail_precedent and self.bail_precedent.loyer_mensuel is not None else None
            ),
            "representant": self.representant_nom,
        }


def adresse_logement_texte(ctx: ContexteBail) -> str:
    im = ctx.immeuble
    base = (im.address if im else "") or ""
    num = ctx.logement.numero if ctx.logement else ""
    txt = base
    if num:
        txt += f", app. {num}"
    if im and im.city:
        txt += f", {im.city}"
    return txt.strip(" ,")


async def charger_contexte(db: AsyncSession, bail_id: int, *, user=None, config: Optional[dict[str, Any]] = None) -> ContexteBail:
    bail = await db.get(Bail, bail_id)
    if bail is None:
        raise TalBailError("Bail introuvable.", http_status=404)
    logement = await db.get(Logement, bail.logement_id)
    if logement is None:
        raise TalBailError("Logement du bail introuvable.", http_status=404)
    immeuble = await db.get(Immeuble, logement.immeuble_id)
    locataire = await db.get(Locataire, bail.locataire_id) if bail.locataire_id else None
    contacts: list[ImmLocataireContact] = []
    if locataire is not None:
        contacts = (
            await db.execute(
                select(ImmLocataireContact)
                .where(ImmLocataireContact.locataire_id == locataire.id, ImmLocataireContact.actif.is_(True))
                .order_by(ImmLocataireContact.id)
            )
        ).scalars().all()
    entreprise: Optional[Entreprise] = None
    if immeuble is not None:
        ent_id = (
            await db.execute(
                select(ImmeubleOwnership.entreprise_id)
                .where(ImmeubleOwnership.immeuble_id == immeuble.id)
                .order_by(ImmeubleOwnership.ownership_pct.desc())
                .limit(1)
            )
        ).scalar_one_or_none() or immeuble.owner_entreprise_id
        if ent_id:
            entreprise = await db.get(Entreprise, int(ent_id))
    # Bail précédent sur le même logement (section G — avis au nouveau
    # locataire : loyer le plus bas des 12 derniers mois, dernier loyer).
    debut = bail.date_debut
    precedent: Optional[Bail] = None
    plus_bas: Optional[float] = None
    dernier_paiement: Optional[date] = None
    if debut is not None:
        anciens = (
            await db.execute(
                select(Bail)
                .where(
                    Bail.logement_id == logement.id,
                    Bail.id != bail.id,
                    Bail.date_debut < debut,
                    Bail.status.in_([BailStatus.ACTIF.value, BailStatus.TERMINE.value, BailStatus.RESILIE.value]),
                )
                .order_by(Bail.date_fin.desc(), Bail.id.desc())
            )
        ).scalars().all()
        if anciens:
            precedent = anciens[0]
            fenetre = debut - timedelta(days=365)
            dans_fenetre = [
                float(b.loyer_mensuel) for b in anciens
                if b.loyer_mensuel is not None and b.date_fin is not None and b.date_fin >= fenetre
            ]
            if dans_fenetre:
                plus_bas = min(dans_fenetre)
            dernier_paiement = (
                await db.execute(
                    select(func.max(PaiementLoyer.paye_le)).where(
                        PaiementLoyer.bail_id == precedent.id, PaiementLoyer.paye_le.isnot(None)
                    )
                )
            ).scalar_one_or_none()
    cfg = config or DEFAUTS
    rep_nom = (cfg.get("representant_nom") or "").strip()
    rep_courriel = (cfg.get("representant_courriel") or "").strip()
    if user is not None:
        if not rep_nom:
            rep_nom = (getattr(user, "display_name", None) or "").strip()
        if not rep_courriel:
            rep_courriel = (getattr(user, "email", None) or "").strip()
    return ContexteBail(
        bail=bail, logement=logement, immeuble=immeuble, locataire=locataire,
        colocataires=[c for c in contacts if c.role == "colocataire"],
        garants=[c for c in contacts if c.role == "garant"],
        entreprise=entreprise, bail_precedent=precedent,
        loyer_plus_bas_12_mois=plus_bas, dernier_paiement_le=dernier_paiement,
        representant_nom=rep_nom, representant_courriel=rep_courriel,
    )


# ─── Construction du formulaire ───────────────────────────────────────


@dataclass
class Prepare:
    form: dict[str, Any]
    origine: dict[str, str]                 # chemin → donnees | defaut | signature | inconnu
    a_verifier: list[dict[str, str]]        # {chemin, note}

    def as_dict(self) -> dict[str, Any]:
        return {"form": self.form, "origine": self.origine, "a_verifier": self.a_verifier}


def _occurrence(schema: SchemaTal, groupe: str) -> dict[str, Any]:
    gab = schema.gabarit_groupe(groupe) or {}
    from app.integrations.tal.schema import _squelette_vide  # noqa: PLC0415

    return {k: _squelette_vide(v) for k, v in gab.items()}


def construire_formulaire(schema: SchemaTal, ctx: ContexteBail, config: dict[str, Any]) -> Prepare:
    form = squelette(schema)
    origine: dict[str, str] = {}
    a_verifier: list[dict[str, str]] = []
    cfg = fusionner_config(config)
    province = cfg.get("province_defaut") or "Québec"

    def poser(chemin: str, valeur: Any, *, kind: str = "donnees", note: str = "") -> None:
        if chemin in form or "[" in chemin:
            _ecrire(form, chemin, valeur)
            origine[chemin] = kind
            if kind in ("defaut", "inconnu"):
                a_verifier.append({"chemin": chemin, "note": note or ("valeur par défaut" if kind == "defaut" else "à compléter")})

    def defaut(chemin: str, valeur: Any, note: str = "") -> None:
        poser(chemin, valeur, kind="defaut", note=note)

    def inconnu(chemin: str, note: str) -> None:
        poser(chemin, form.get(chemin, ""), kind="inconnu", note=note)

    bail, lg, im = ctx.bail, ctx.logement, ctx.immeuble

    # ── A. Locateur ────────────────────────────────────────────────
    loc = _occurrence(schema, "locateurs")
    ent = ctx.entreprise
    if ent is not None:
        loc["nom"] = ent.name or ""
        origine["locateurs[0].nom"] = "donnees"
        tel = _telephone(getattr(ent, "contact_telephone", None))
        if tel:
            loc["noTelephone"] = tel
            origine["locateurs[0].noTelephone"] = "donnees"
        if getattr(ent, "contact_email", None):
            loc["courrielLocateur"] = ent.contact_email.strip()
            loc["courrielMandant"] = ent.contact_email.strip()
            origine["locateurs[0].courrielLocateur"] = "donnees"
        adr_src = getattr(ent, "siege_social", None)
        if adr_src:
            loc["adresse"] = [decouper_adresse(adr_src, province=province)]
            origine["locateurs[0].adresse"] = "donnees"
        elif im is not None:
            loc["adresse"] = [decouper_adresse(im.address, ville=im.city, code_postal=im.postal_code, province=province)]
            origine["locateurs[0].adresse"] = "defaut"
            a_verifier.append({"chemin": "locateurs[0].adresse", "note": "siège social absent de la fiche entreprise — adresse de l'immeuble utilisée"})
    else:
        a_verifier.append({"chemin": "locateurs[0].nom", "note": "aucune entreprise propriétaire liée à l'immeuble"})
        origine["locateurs[0].nom"] = "inconnu"
    if ctx.representant_nom:
        loc["questionRepresentant"] = "true"
        loc["representant"] = ctx.representant_nom
        loc["courrielRepresentant"] = ctx.representant_courriel
        origine["locateurs[0].representant"] = "donnees"
    else:
        loc["questionRepresentant"] = "false"
    form["locateurs"] = [loc]

    # ── B. Locataires (max 4) ──────────────────────────────────────
    locataires: list[dict[str, Any]] = []
    if ctx.locataire is not None:
        o = _occurrence(schema, "locataires")
        o["nom"] = ctx.locataire.full_name or ""
        o["noTelephone"] = _telephone(ctx.locataire.phone)
        o["courrielLocataire"] = (ctx.locataire.email or "").strip()
        o["questionRepresentant"] = "false"
        if ctx.locataire.ancienne_adresse:
            o["adresse"] = [decouper_adresse(ctx.locataire.ancienne_adresse, province=province)]
            origine["locataires[0].adresse"] = "donnees"
        else:
            a_verifier.append({"chemin": "locataires[0].adresse", "note": "adresse actuelle du locataire inconnue (fiche : adresse précédente vide)"})
            origine["locataires[0].adresse"] = "inconnu"
        origine["locataires[0].nom"] = "donnees"
        locataires.append(o)
    else:
        a_verifier.append({"chemin": "locataires[0].nom", "note": "aucun locataire sur le bail"})
    for c in ctx.colocataires[: max(0, 4 - len(locataires))]:
        o = _occurrence(schema, "locataires")
        o["nom"] = c.full_name
        o["noTelephone"] = _telephone(c.phone)
        o["courrielLocataire"] = (c.email or "").strip()
        o["questionRepresentant"] = "false"
        i = len(locataires)
        origine[f"locataires[{i}].nom"] = "donnees"
        a_verifier.append({"chemin": f"locataires[{i}].adresse", "note": "adresse du colocataire inconnue"})
        locataires.append(o)
    form["locataires"] = locataires or [_occurrence(schema, "locataires")]
    if len(locataires) >= 2:
        defaut("estLocatairesEngagementSolidaire", "true", "plusieurs locataires : solidarité présumée")
    else:
        origine["estLocatairesEngagementSolidaire"] = "signature"

    # ── Autres signataires (cautions) ─────────────────────────────
    if ctx.garants:
        poser("possedeAutresSignataires", "true")
        autres = []
        for g in ctx.garants[:2]:
            o = _occurrence(schema, "autresSignataires")
            o["nom"] = g.full_name
            o["qualite"] = "Caution"
            o["courriel"] = (g.email or "").strip()
            autres.append(o)
            a_verifier.append({"chemin": f"autresSignataires[{len(autres) - 1}].adresse", "note": "adresse de la caution inconnue"})
        form["autresSignataires"] = autres
        origine["autresSignataires"] = "donnees"
    else:
        defaut("possedeAutresSignataires", "false", "aucun garant sur la fiche locataire")

    # ── C. Logement ───────────────────────────────────────────────
    if im is not None:
        form["adresseLogement"] = [decouper_adresse(im.address, ville=im.city, code_postal=im.postal_code, appartement=lg.numero, province=province)]
        origine["adresseLogement"] = "donnees"
        if not im.postal_code and not form["adresseLogement"][0].get("CodePostal"):
            a_verifier.append({"chemin": "adresseLogement[0].CodePostal", "note": "code postal absent de la fiche immeuble"})
    else:
        a_verifier.append({"chemin": "adresseLogement", "note": "immeuble introuvable"})
    cle, autre = cle_nb_pieces(getattr(lg, "nb_pieces_decimal", None))
    if cle:
        poser("nbPieces", cle)
        if autre:
            poser("nbPiecesAutre", autre)
    else:
        inconnu("nbPieces", "nombre de pièces absent de la fiche du logement")
    defaut("logementLoueFinsHabitation", "true", "habitation seulement")
    defaut("logementCoproprieteDivise", "false")
    defaut("appareilsInclusLoyer", "false", "aucun appareil déclaré")
    defaut("meublesInclusLoyer", "false", "aucun meuble déclaré")
    poser("dependancesIncluses", [], kind="inconnu", note="stationnement / rangement : à cocher si inclus")

    # ── D. Durée du bail ─────────────────────────────────────────
    if getattr(bail, "au_mois", None):
        poser("typeBail", "dureeIndeterminee")
        poser("dateDebutBailDureeIndeterminee", _iso(bail.date_debut))
    else:
        poser("typeBail", "dureeFixe")
        poser("dateDebutBail", _iso(bail.date_debut))
        poser("dateFinBail", _iso(bail.date_fin))
        poser("nbSemainesMoisAnnees", _duree_texte(bail.date_debut, bail.date_fin))

    # ── E. Loyer ──────────────────────────────────────────────────
    poser("frequenceCoutLoyer", "mois")
    poser("coutLoyer", _montant(bail.loyer_mensuel))
    defaut("bailIncluServices", "false", "loyer sans services facturés à part")
    poser("coutTotalLoyer", _montant(bail.loyer_mensuel))
    defaut("subventionPaiementLoyer", "false")
    poser("premierTermePaiement", _iso(bail.date_debut))
    jour = int(getattr(bail, "jour_echeance", 1) or 1)
    if jour == 1:
        poser("termesPaiement", "permierJourMois")
    else:
        poser("termesPaiement", "autre")
        poser("precisionAutresTermes", f"Le {jour} de chaque mois")
    defaut("modePaiement", cfg.get("mode_paiement_defaut") or "virementBancaire", "mode de paiement par défaut (Paramètres)")
    origine["locataireAccepteRemiseChequePostdates"] = "signature"
    inconnu("lieuPaiement", "lieu de paiement (ou mode électronique) à préciser")

    # ── F. Services et conditions ────────────────────────────────
    poser("possedeRemiseReglementImmeuble", "", kind="inconnu", note="règlement de l'immeuble remis ? (oui/non + date)")
    defaut("possederServiceConciergerie", "false")
    chauffage = cfg.get("chauffage_defaut") or "electricite"
    defaut("typeChauffageLogement", [chauffage], "type de chauffage par défaut (Paramètres)")
    poser("responsabiliteChauffage", "locateur" if bail.chauffage_inclus else "locataire")
    resp = _occurrence(schema, "responsabiliteServicesTaxesCoutsConsommation")
    resp.update({
        "responsabiliteGaz": "na",
        "responsabiliteElectricite": "locateur" if bail.electricite_inclus else "locataire",
        "responsabiliteChauffeEau": "locateur" if bail.eau_chaude_inclus else "na",
        "responsabiliteEauChaude": "locateur" if bail.eau_chaude_inclus else "locataire",
        "responsabiliteTaxeConsommationEau": "locateur",
        "responsabiliteDeneigementStationnement": "locateur",
        "responsabiliteDeneigementBalcon": "locataire",
        "responsabiliteDeneigementEntree": "locateur",
        "responsabiliteDeneigementEscalier": "locateur",
    })
    form["responsabiliteServicesTaxesCoutsConsommation"] = [resp]
    origine["responsabiliteServicesTaxesCoutsConsommation[0].responsabiliteElectricite"] = "donnees"
    origine["responsabiliteServicesTaxesCoutsConsommation[0].responsabiliteEauChaude"] = "donnees"
    for k in ("responsabiliteGaz", "responsabiliteChauffeEau", "responsabiliteTaxeConsommationEau",
              "responsabiliteDeneigementStationnement", "responsabiliteDeneigementBalcon",
              "responsabiliteDeneigementEntree", "responsabiliteDeneigementEscalier"):
        origine[f"responsabiliteServicesTaxesCoutsConsommation[0].{k}"] = "defaut"
    a_verifier.append({"chemin": "responsabiliteServicesTaxesCoutsConsommation[0]", "note": "répartition gaz / chauffe-eau / taxe d'eau / déneigement par défaut"})
    defaut("logementSansFumee", "true" if cfg.get("logement_sans_fumee", True) else "false", "règle maison (Paramètres)")
    defaut("locatairePossedeDroitAnimaux", "true" if cfg.get("animaux_defaut") else "false", "règle maison (Paramètres)")
    inconnu("locatairePossedeDroitAccesTerrain", "accès au terrain : oui/non")
    if bail.internet_inclus:
        poser("possedeAutresServicesConditionsRestriction", "true")
        poser("precisionAutresServicesConditionsRestriction", "Internet inclus dans le loyer.")
    else:
        defaut("possedeAutresServicesConditionsRestriction", "false")
    defaut("possedeDocumentsJoindreBail", "false")
    defaut("possedeServicesAdditionnelsBail", "false")
    annee = getattr(im, "annee_construction", None) if im is not None else None
    if annee and bail.date_debut and int(annee) >= bail.date_debut.year - 5:
        poser("situationApplicableRestrictionsFixationLoyer", "estLogementImmeubleMoins5ans")
        a_verifier.append({"chemin": "dateImmeublePretHabitation", "note": f"immeuble de {annee} : date « prêt pour l'habitation » à saisir"})
        origine["dateImmeublePretHabitation"] = "inconnu"
    else:
        defaut("situationApplicableRestrictionsFixationLoyer", "aucun", "immeuble de plus de 5 ans (ou année inconnue)")

    # ── G. Avis au nouveau locataire ──────────────────────────────
    prec = ctx.bail_precedent
    if prec is not None and prec.date_fin is not None and bail.date_debut is not None and prec.date_fin >= bail.date_debut - timedelta(days=365):
        poser("situationApplicableAvisNouveauLocataire", "loyer")
        plus_bas = ctx.loyer_plus_bas_12_mois if ctx.loyer_plus_bas_12_mois is not None else prec.loyer_mensuel
        poser("montantLoyerPlusBasPaye12Mois", _montant(plus_bas))
        poser("frequenceLoyerPlusBasPaye12Mois", "mois")
        if ctx.dernier_paiement_le:
            poser("dateDernierPaiementLoyer", _iso(ctx.dernier_paiement_le))
        else:
            inconnu("dateDernierPaiementLoyer", "date du dernier loyer payé par l'ancien locataire")
        poser("montantDernierLoyerPaye", _montant(prec.loyer_mensuel))
        poser("frequenceDernierLoyer", "mois")
        poser("montantLoyerBailPrecedent", _montant(prec.loyer_mensuel))
        poser("frequenceLoyerBailPrecedent", "mois")
        defaut("estMemeBienServicesConditions", "true", "mêmes biens/services/conditions que le bail précédent")
        poser("confirmationTransmissionAvisNouveauLocataire", True)
        poser("locateur1confirmationLocateurAvisNouveauLocataire", True)
    else:
        defaut("situationApplicableAvisNouveauLocataire", "aucunLoyer", "aucun loyer payé dans les 12 derniers mois (pas de bail précédent connu)")

    # ── Engagements du locateur (cases) ───────────────────────────
    poser("engagementAvertisseursFumeeLocateur", True)
    poser("locateur1engagementAvertisseursFumeeLocateurs", True)
    # Cases du locataire : recueillies à la signature (eSign), pas cochées
    # à sa place.
    for k in list(form.keys()):
        if k.startswith(("locataire", "autreSignataire")) and isinstance(form.get(k), bool):
            origine[k] = "signature"
        if k.startswith("signature") and isinstance(form.get(k), list):
            origine[k] = "signature"
    inconnu("locataire1logementResidenceFamiliale", "résidence familiale (conjoint) : question au locataire")
    inconnu("motPasseWF", "mot de passe WF : rôle à confirmer avec le TAL")
    return Prepare(form=form, origine=origine, a_verifier=a_verifier)


def _ecrire(form: dict[str, Any], chemin: str, valeur: Any) -> None:
    """« a », « g[0].k » ou « g[0].sub[0].k » → écrit dans form."""
    parts = re.split(r"\.(?![^\[]*\])", chemin)
    cur: Any = form
    for i, part in enumerate(parts):
        m = re.match(r"^([A-Za-z0-9_]+)(?:\[(\d+)\])?$", part)
        if not m:
            return
        key, idx = m.group(1), m.group(2)
        last = i == len(parts) - 1
        if idx is None:
            if last:
                cur[key] = valeur
                return
            cur = cur.setdefault(key, {})
        else:
            lst = cur.setdefault(key, [])
            n = int(idx)
            while len(lst) <= n:
                lst.append({})
            if last:
                lst[n] = valeur
                return
            cur = lst[n]


def appliquer_surcharges(form: dict[str, Any], surcharges: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Surcharges « chemin → valeur » posées par l'utilisateur sur le
    formulaire préparé (override Phil 2026-10-15)."""
    for chemin, valeur in (surcharges or {}).items():
        _ecrire(form, str(chemin), valeur)
    return form


async def preparer(
    db: AsyncSession, bail_id: int, *, user=None, surcharges: Optional[dict[str, Any]] = None
) -> tuple[Prepare, Rapport, ContexteBail, SchemaTal, dict[str, Any]]:
    config = await charger_config()
    schema = await charger_schema(db)
    ctx = await charger_contexte(db, bail_id, user=user, config=config)
    prep = construire_formulaire(schema, ctx, config)
    if surcharges:
        appliquer_surcharges(prep.form, surcharges)
        for k in surcharges:
            prep.origine[str(k)] = "utilisateur"
    rapport = valider(prep.form, schema, requis=chemins_requis(config))
    if ctx.bail.document_id is not None:
        rapport.avertissements.append("Ce bail a déjà un document au dossier (bail signé ?) — un nouveau formulaire coûte 2,99 $.")
    if (ctx.immeuble is not None) and getattr(ctx.immeuble, "gestion_externe", False):
        rapport.avertissements.append("Immeuble en gestion externe : la relocation ne passe normalement pas par Kratos.")
    return prep, rapport, ctx, schema, config


# ─── Transmissions ────────────────────────────────────────────────────


def _json(v: Any) -> Optional[str]:
    return json.dumps(v, ensure_ascii=False, default=str) if v is not None else None


def _charger_json(txt: Optional[str], defaut: Any) -> Any:
    if not txt:
        return defaut
    try:
        return json.loads(txt)
    except Exception:  # noqa: BLE001
        return defaut


def resume_transmission(t: TalTransmission, *, avec_form: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": t.id,
        "bail_id": t.bail_id,
        "dossier_id": t.dossier_id,
        "logement_id": t.logement_id,
        "immeuble_id": t.immeuble_id,
        "locataire_id": t.locataire_id,
        "adresse": t.adresse,
        "statut": t.statut,
        "mode": t.mode,
        "schema_version": t.schema_version,
        "identifiant_utilisateur": t.identifiant_utilisateur,
        "short_guid": t.short_guid,
        "no_confirmation": t.no_confirmation,
        "messages": _charger_json(t.messages_json, []),
        "documents": _charger_json(t.documents_json, []),
        "document_id": t.document_id,
        "esign_document_id": t.esign_document_id,
        "cout": float(t.cout) if t.cout is not None else None,
        "frais_manuel_id": t.frais_manuel_id,
        "frais_montant": float(t.frais_montant) if t.frais_montant is not None else None,
        "erreur": t.erreur,
        "tentatives": t.tentatives,
        "genere_le": t.genere_le.isoformat() if t.genere_le else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "created_by_email": t.created_by_email,
        "rapport": _charger_json(t.rapport_json, None),
        "a_verifier": _charger_json(t.a_verifier_json, []),
    }
    if avec_form:
        out["form"] = _charger_json(t.payload_json, {})
    return out


async def creer_transmission(
    db: AsyncSession,
    *,
    bail_id: int,
    user,
    dossier_id: Optional[int] = None,
    surcharges: Optional[dict[str, Any]] = None,
    form: Optional[dict[str, Any]] = None,
    remplacer: bool = False,
) -> tuple[TalTransmission, Rapport]:
    """Brouillon : formulaire préparé (ou fourni) + rapport. Refuse s'il
    existe déjà une transmission TRANSMISE pour ce bail (un bail = un
    formulaire payé) sauf ``remplacer`` explicite ; réutilise un brouillon
    ouvert plutôt que d'en empiler."""
    prep, rapport, ctx, schema, config = await preparer(db, bail_id, user=user, surcharges=surcharges)
    if form is not None:
        prep.form = form
        rapport = valider(form, schema, requis=chemins_requis(config))
    existantes = (
        await db.execute(
            select(TalTransmission).where(TalTransmission.bail_id == bail_id).order_by(TalTransmission.id.desc())
        )
    ).scalars().all()
    transmise = next((t for t in existantes if t.statut == "transmise"), None)
    if transmise is not None and not remplacer:
        raise TransmissionFermee(
            f"Un bail officiel a déjà été généré pour ce bail (transmission #{transmise.id}). "
            "Un nouveau formulaire sera facturé 2,99 $ : confirme le remplacement.",
            details={"transmission_id": transmise.id},
        )
    ouverte = next((t for t in existantes if t.statut in ("brouillon", "echec")), None)
    now = datetime.now(timezone.utc)
    if ouverte is not None:
        t = ouverte
    else:
        t = TalTransmission(bail_id=bail_id, created_by_user_id=getattr(user, "id", None), created_by_email=getattr(user, "email", None))
        t.created_at = now
        db.add(t)
    t.dossier_id = dossier_id if dossier_id is not None else t.dossier_id
    t.logement_id = ctx.logement.id
    t.immeuble_id = ctx.immeuble.id if ctx.immeuble else None
    t.locataire_id = ctx.locataire.id if ctx.locataire else None
    t.adresse = adresse_logement_texte(ctx)[:500]
    t.statut = "brouillon"
    t.erreur = None
    t.schema_version = schema.version
    t.payload_json = _json(prep.form)
    t.rapport_json = _json(rapport.as_dict())
    t.a_verifier_json = _json(prep.a_verifier)
    t.updated_at = now
    await db.flush()
    if not t.identifiant_utilisateur:
        t.identifiant_utilisateur = f"kratos-b{bail_id}-t{t.id}"
    return t, rapport


async def remplacer_formulaire(db: AsyncSession, t: TalTransmission, form: dict[str, Any]) -> Rapport:
    if t.statut not in STATUTS_OUVERTS or t.short_guid:
        raise TransmissionFermee("Le formulaire ne se modifie plus une fois créé au TAL (ShortGuid attribué) ou transmis — crée une nouvelle transmission.")
    schema = await charger_schema(db)
    config = await charger_config()
    rapport = valider(form, schema, requis=chemins_requis(config))
    t.payload_json = _json(form)
    t.rapport_json = _json(rapport.as_dict())
    t.schema_version = schema.version
    t.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return rapport


async def valider_transmission(db: AsyncSession, t: TalTransmission) -> Rapport:
    schema = await charger_schema(db)
    config = await charger_config()
    form = _charger_json(t.payload_json, {})
    rapport = valider(form, schema, requis=chemins_requis(config))
    t.rapport_json = _json(rapport.as_dict())
    await db.flush()
    return rapport


def _libelle_frais(config: dict[str, Any], t: TalTransmission, ctx_nom_locataire: str) -> str:
    gabarit = config.get("libelle_frais") or DEFAUTS["libelle_frais"]
    try:
        txt = gabarit.format(adresse=t.adresse or "", locataire=ctx_nom_locataire or "")
    except Exception:  # noqa: BLE001
        txt = f"Bail officiel TAL — {t.adresse or ''}"
    return re.sub(r"\s+", " ", txt).strip(" —-()")[:255] or "Bail officiel TAL"


async def generer(
    db: AsyncSession,
    t: TalTransmission,
    *,
    user,
    connexion: Optional[ConnexionTal] = None,
    client: Optional[ClientTal] = None,
) -> TalTransmission:
    """FRW111 (si pas encore de ShortGuid) puis FRW122 ; archive le PDF,
    pose le coût et le frais. Commits PROGRESSIFS : le ShortGuid est
    sauvé dès qu'il existe (jamais de second formulaire facturé)."""
    from app.services.audit import log_action

    if t.statut == "transmise":
        raise TransmissionFermee("Ce bail officiel a déjà été généré et archivé.", details={"document_id": t.document_id})
    if t.statut == "annulee":
        raise TransmissionFermee("Transmission annulée — crée une nouvelle demande.")
    form = _charger_json(t.payload_json, None)
    if not isinstance(form, dict) or not form:
        raise FormulaireInvalide("Formulaire vide.")
    schema = await charger_schema(db)
    config = await charger_config()
    rapport = valider(form, schema, requis=chemins_requis(config))
    t.rapport_json = _json(rapport.as_dict())
    if not rapport.valide:
        await db.flush()
        raise FormulaireInvalide("Le formulaire ne passe pas la validation locale — rien n'a été envoyé au TAL.", details=rapport.as_dict())
    if connexion is None:
        connexion, _infos = await charger_connexion(db)
    client = client or _fabrique_client(connexion)
    t.mode = client.mode
    t.tentatives = int(t.tentatives or 0) + 1
    t.erreur = None
    now = datetime.now(timezone.utc)

    if not t.short_guid:
        try:
            rc = await client.creer_formulaire(form, identifiant_utilisateur=t.identifiant_utilisateur)
        except TalApiError as exc:
            t.statut = "echec"
            t.erreur = str(exc)
            t.updated_at = now
            await db.commit()
            await log_action(db, user=user, action="tal_bail.echec", entity_type="tal_transmission", entity_id=t.id,
                             details={"etape": exc.etape, "message": exc.message, "http_status": exc.http_status, "mode": t.mode})
            await db.commit()
            raise
        t.short_guid = rc.short_guid
        t.statut = "forme_creee"
        t.updated_at = now
        await db.commit()  # le ShortGuid ne doit jamais se perdre

    try:
        rt = await client.declencher_transmission(t.short_guid, identifiant_utilisateur=t.identifiant_utilisateur, form_pour_simulation=form)
    except TalApiError as exc:
        t.statut = "forme_creee"
        t.erreur = str(exc)
        t.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await log_action(db, user=user, action="tal_bail.echec", entity_type="tal_transmission", entity_id=t.id,
                         details={"etape": exc.etape, "message": exc.message, "http_status": exc.http_status, "short_guid": t.short_guid, "mode": t.mode})
        await db.commit()
        raise

    pdf: Optional[bytes] = None
    nom_pdf = "bail.pdf"
    docs_resume: list[dict[str, Any]] = []
    for d in rt.documents:
        try:
            octets = d.octets()
        except Exception:  # noqa: BLE001
            docs_resume.append({"nom": d.nom, "type_source": d.type_source, "taille": None, "erreur": "base64 illisible"})
            continue
        docs_resume.append({"nom": d.nom, "type_source": d.type_source, "taille": len(octets)})
        if pdf is None and octets[:5] == b"%PDF-":
            pdf, nom_pdf = octets, d.nom
    t.messages_json = _json(rt.messages)
    t.documents_json = _json(docs_resume)
    t.no_confirmation = rt.no_confirmation
    if pdf is None:
        t.statut = "forme_creee"
        t.erreur = "La réponse du TAL ne contient aucun PDF lisible — relance possible avec le même ShortGuid."
        t.updated_at = datetime.now(timezone.utc)
        await db.commit()
        raise TalApiError("FRW122", t.erreur, corps=docs_resume)

    # Archive TEL QUEL (PDF verrouillé : jamais modifié).
    locataire = await db.get(Locataire, t.locataire_id) if t.locataire_id else None
    doc = ImmDocument(
        bail_id=t.bail_id,
        locataire_id=t.locataire_id,
        immeuble_id=t.immeuble_id,
        logement_id=t.logement_id,
        type=DOC_TYPE,
        titre=(f"Bail de logement (TAL) — {t.adresse}" if t.adresse else "Bail de logement (TAL)")[:255],
        source="genere",
        filename=(nom_pdf or "bail.pdf")[:255],
        params_json=_json({
            "transmission_id": t.id, "short_guid": t.short_guid, "no_confirmation": t.no_confirmation,
            "mode": t.mode, "schema_version": t.schema_version, "simulation": client.simulation,
        }),
        pdf_blob=pdf,
        created_by_email=getattr(user, "email", None),
    )
    db.add(doc)
    await db.flush()
    t.document_id = doc.id
    t.statut = "transmise"
    t.genere_le = datetime.now(timezone.utc)
    t.updated_at = t.genere_le
    t.erreur = None
    t.cout = 0.0 if client.simulation else COUT_TAL

    # Frais refacturé au propriétaire (mode réel seulement).
    t.frais_manuel_id = None
    t.frais_montant = None
    tarif = float(config.get("tarif_recharge") or 0)
    if not client.simulation and config.get("frais_auto", True) and tarif > 0 and t.immeuble_id:
        fm = FraisManuelGestion(
            immeuble_id=t.immeuble_id,
            libelle=_libelle_frais(config, t, locataire.full_name if locataire else ""),
            montant=round(tarif, 2),
            created_by_user_id=getattr(user, "id", None),
            created_at=t.genere_le,
        )
        db.add(fm)
        await db.flush()
        t.frais_manuel_id = fm.id
        t.frais_montant = round(tarif, 2)

    await log_action(
        db, user=user, action="tal_bail.genere", entity_type="tal_transmission", entity_id=t.id,
        details={
            "bail_id": t.bail_id, "dossier_id": t.dossier_id, "mode": t.mode, "short_guid": t.short_guid,
            "no_confirmation": t.no_confirmation, "document_id": t.document_id, "cout": t.cout,
            "frais_montant": t.frais_montant, "duree_ms": rt.duree_ms,
            "messages": [m.get("mnemonique") for m in rt.messages if isinstance(m, dict)],
        },
    )
    await db.commit()
    return t


async def annuler(db: AsyncSession, t: TalTransmission, *, user) -> TalTransmission:
    from app.services.audit import log_action

    if t.statut == "transmise":
        raise TransmissionFermee("Un bail transmis (et facturé) ne s'annule pas — il reste au dossier.")
    t.statut = "annulee"
    t.updated_at = datetime.now(timezone.utc)
    await log_action(db, user=user, action="tal_bail.annulee", entity_type="tal_transmission", entity_id=t.id,
                     details={"bail_id": t.bail_id, "short_guid": t.short_guid})
    await db.flush()
    return t


# ─── Compteur mensuel ─────────────────────────────────────────────────


def _bornes_mois(mois: Optional[str]) -> tuple[datetime, datetime, str]:
    today = datetime.now(timezone.utc)
    if mois:
        m = re.match(r"^(\d{4})-(\d{2})$", mois.strip())
        if not m:
            raise TalBailError("Mois attendu au format AAAA-MM.", http_status=422)
        y, mo = int(m.group(1)), int(m.group(2))
        if not 1 <= mo <= 12:
            raise TalBailError("Mois attendu au format AAAA-MM (01 à 12).", http_status=422)
    else:
        y, mo = today.year, today.month
    debut = datetime(y, mo, 1, tzinfo=timezone.utc)
    fin = datetime(y + (mo // 12), (mo % 12) + 1, 1, tzinfo=timezone.utc)
    return debut, fin, f"{y:04d}-{mo:02d}"


async def compteur(db: AsyncSession, mois: Optional[str] = None, *, config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    debut, fin, libelle = _bornes_mois(mois)
    cfg = config or await charger_config()
    rows = (
        await db.execute(
            select(TalTransmission).where(
                TalTransmission.statut == "transmise",
                TalTransmission.genere_le >= debut,
                TalTransmission.genere_le < fin,
            )
        )
    ).scalars().all()
    reel = [t for t in rows if t.mode == MODE_REEL]
    simul = [t for t in rows if t.mode != MODE_REEL]
    total_reel = (
        await db.execute(
            select(func.count(TalTransmission.id)).where(
                TalTransmission.statut == "transmise", TalTransmission.mode == MODE_REEL
            )
        )
    ).scalar_one() or 0
    ouvertes = (
        await db.execute(
            select(func.count(TalTransmission.id)).where(TalTransmission.statut.in_(list(STATUTS_OUVERTS)))
        )
    ).scalar_one() or 0
    return {
        "mois": libelle,
        "nb_transmises": len(rows),
        "nb_reel": len(reel),
        "nb_simulation": len(simul),
        "cout_tal_estime": round(sum(float(t.cout or 0) for t in reel), 2),
        "cout_unitaire": COUT_TAL,
        "frais_refactures": round(sum(float(t.frais_montant or 0) for t in reel), 2),
        "tarif_recharge": cfg.get("tarif_recharge"),
        "total_reel_depuis_le_debut": int(total_reel),
        "gratuits_restants": max(0, GRATUITS_TOTAL - int(total_reel)),
        "transmissions_ouvertes": int(ouvertes),
    }


__all__ = [
    "CONFIG_KEY", "COUT_TAL", "DOC_TYPE", "DEFAUTS", "GRATUITS_TOTAL",
    "TalBailError", "FormulaireInvalide", "TransmissionFermee",
    "fusionner_config", "charger_config", "chemins_requis",
    "charger_connexion", "enregistrer_connexion",
    "cle_nb_pieces", "decouper_adresse",
    "ContexteBail", "charger_contexte", "construire_formulaire", "appliquer_surcharges", "preparer",
    "resume_transmission", "creer_transmission", "remplacer_formulaire", "valider_transmission",
    "generer", "annuler", "compteur",
]
