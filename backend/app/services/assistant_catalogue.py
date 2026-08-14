"""Catalogue des OUTILS de l'assistant IA Kratos (phase 1 — sans LLM).

C'est la fondation de l'agent à outils : chaque outil décrit UN geste
métier de la plateforme (« marquer un loyer payé », « créer une tâche »)
et son handler appelle les MÊMES fonctions/services que la saisie
manuelle — jamais de SQL direct qui contournerait les règles métier
(trop-payé réparti sur les mois suivants, score de paiement, gardes de
statut de bail, etc.).

Contrat d'un outil (``OutilAssistant``) :
  - ``id``          : identifiant stable snake_case ;
  - ``titre``       : libellé FR court (UI de la carte d'action) ;
  - ``description`` : rédigée POUR LE LLM de la phase 2 — quand utiliser
                      l'outil, ce que font les paramètres ;
  - ``parametres``  : schéma JSON strict (type object, required,
                      additionalProperties: false) — validé par
                      ``valider_params`` avant tout appel de handler ;
  - ``lecture``     : True = exécution directe autorisée ; False =
                      ÉCRITURE, qui passe obligatoirement par une carte
                      d'action confirmée par l'humain ;
  - ``permission``  : clé de PAGE du registre central
                      (``app.core.access_registry``) — l'outil est
                      refusé (et absent du catalogue) si l'utilisateur
                      n'a pas accès à cette page ;
  - ``handler``     : ``async (db, user, params, apercu_seulement)`` →
                      dict. Pour un outil d'écriture, le dict contient
                      TOUJOURS ``apercu`` (phrase FR décrivant ce qui VA
                      être fait) ; avec ``apercu_seulement=True`` le
                      handler VALIDE les paramètres et retourne l'aperçu
                      SANS rien écrire (c'est ce que la carte affiche).

Inspiré du registre de pages (``access_registry``) et du catalogue de
capacités des clés d'API (``api_capabilities``). L'ancien cerveau
``services/kratos_router.py`` n'est ni touché ni réutilisé.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.core.access_registry import PAGE_KEY_PREFIX, PAGES_BY_KEY
from app.models.immobilier import (
    Bail,
    BailStatus,
    FraisLocatif,
    Immeuble,
    Locataire,
    Logement,
    PaiementLoyer,
)
from app.models.user import User
from app.models.user_access_override import UserAccessOverride
from app.services.permissions_service import get_min_role


# ── Erreur de validation des paramètres ────────────────────────────


class ParamsInvalides(ValueError):
    """Paramètres d'outil invalides (message FR, exposé en 422)."""


# ── Petits helpers de format FR ────────────────────────────────────

_MOIS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def _mois_fr(d: date) -> str:
    """« août 2026 » — pour les aperçus lisibles."""
    return f"{_MOIS_FR[d.month - 1]} {d.year}"


def _montant_fr(v: float) -> str:
    """« 1 234,50 $ » (sans décimales inutiles : « 500 $ »)."""
    v = round(float(v), 2)
    if v == int(v):
        s = f"{int(v):,}".replace(",", " ")
    else:
        s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} $"


def _parse_mois(s: str) -> date:
    """« YYYY-MM » → 1er du mois. Erreur FR sinon."""
    try:
        return datetime.strptime(str(s) + "-01", "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ParamsInvalides(
            f"Mois invalide « {s} » — format attendu : YYYY-MM."
        )


def _parse_date(s: str, champ: str) -> date:
    """« YYYY-MM-DD » → date. Erreur FR sinon."""
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ParamsInvalides(
            f"Date invalide pour « {champ} » : « {s} » — format attendu : "
            "YYYY-MM-DD."
        )


def _aujourdhui() -> date:
    return datetime.now(timezone.utc).date()


# ── Validation du schéma JSON (strict, sans dépendance externe) ────
#
# Sous-ensemble volontairement simple de JSON Schema, suffisant pour le
# catalogue : type object, properties {type, enum, minimum,
# exclusiveMinimum, maximum, default}, required, additionalProperties
# false. Les formats date/mois sont validés dans les handlers (messages
# FR contextualisés). ``default`` est APPLIQUÉ (le handler reçoit des
# params complets).

_TYPES_JSON: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def valider_params(outil: "OutilAssistant", params: Any) -> dict:
    """Valide ``params`` contre ``outil.parametres`` et retourne le dict
    complété des valeurs par défaut. Lève ``ParamsInvalides`` (FR)."""
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ParamsInvalides("Les paramètres doivent être un objet JSON.")

    schema = outil.parametres
    props: dict[str, dict] = schema.get("properties", {})
    requis: list[str] = schema.get("required", [])

    inconnus = [k for k in params if k not in props]
    if inconnus:
        raise ParamsInvalides(
            f"Paramètre(s) inconnu(s) pour « {outil.id} » : "
            + ", ".join(sorted(inconnus))
            + "."
        )

    out: dict[str, Any] = {}
    for nom, spec in props.items():
        if nom in params and params[nom] is not None:
            val = params[nom]
            attendu = _TYPES_JSON.get(spec.get("type", "string"), (object,))
            # bool est un int en Python : ne jamais accepter True pour un
            # champ integer/number (et vice-versa un int pour un boolean).
            if isinstance(val, bool) and spec.get("type") != "boolean":
                raise ParamsInvalides(
                    f"« {nom} » : booléen reçu, {spec.get('type')} attendu."
                )
            if not isinstance(val, attendu):
                raise ParamsInvalides(
                    f"« {nom} » : type invalide ({type(val).__name__}), "
                    f"{spec.get('type')} attendu."
                )
            if "enum" in spec and val not in spec["enum"]:
                raise ParamsInvalides(
                    f"« {nom} » : valeur « {val} » hors choix permis "
                    f"({', '.join(str(v) for v in spec['enum'])})."
                )
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                if "minimum" in spec and val < spec["minimum"]:
                    raise ParamsInvalides(
                        f"« {nom} » : doit être ≥ {spec['minimum']}."
                    )
                if (
                    "exclusiveMinimum" in spec
                    and val <= spec["exclusiveMinimum"]
                ):
                    raise ParamsInvalides(
                        f"« {nom} » : doit être > {spec['exclusiveMinimum']}."
                    )
                if "maximum" in spec and val > spec["maximum"]:
                    raise ParamsInvalides(
                        f"« {nom} » : doit être ≤ {spec['maximum']}."
                    )
            if isinstance(val, str) and not val.strip() and nom in requis:
                raise ParamsInvalides(f"« {nom} » est requis.")
            out[nom] = val
        elif "default" in spec:
            out[nom] = spec["default"]

    manquants = [r for r in requis if r not in out]
    if manquants:
        raise ParamsInvalides(
            f"Paramètre(s) requis manquant(s) pour « {outil.id} » : "
            + ", ".join(manquants)
            + "."
        )
    return out


# ── Permission de PAGE d'un utilisateur (mêmes règles que l'UI) ────


async def utilisateur_a_acces_page(db, user: User, page_key: str) -> bool:
    """L'utilisateur voit-il la page ``page_key`` (ex.
    « immobilier.paiements ») ? — mêmes règles que ``compute_access``
    (permissions v2) pour UNE page : exception individuelle d'abord
    (allow force l'accès même sans volet, deny le retire — owner jamais
    bloqué), sinon rôle ≥ seuil configuré ET volet de la page."""
    from app.core.access_registry import GENERAL

    cle = f"{PAGE_KEY_PREFIX}{page_key}"
    row = (
        await db.execute(
            select(UserAccessOverride).where(
                UserAccessOverride.user_id == user.id,
                UserAccessOverride.key == cle,
            )
        )
    ).scalars().first()
    if row is not None:
        if row.allow:
            return True
        if user.role != "owner":
            return False

    page = PAGES_BY_KEY.get(page_key)
    if page is None:
        # Clé inconnue → refus (même prudence que get_min_role).
        return False
    role_ok = user.has_min_role(await get_min_role(cle))
    volet_ok = page.volet == GENERAL or page.volet in user.volets
    return role_ok and volet_ok


# ── Le type d'un outil ─────────────────────────────────────────────

Handler = Callable[..., Awaitable[dict]]


@dataclass(frozen=True)
class OutilAssistant:
    """Un outil du catalogue (voir le contrat en tête de module)."""

    id: str
    titre: str
    description: str
    parametres: dict
    lecture: bool
    permission: str
    handler: Handler

    def public(self) -> dict:
        """Représentation exposée par l'API (sans le handler) — c'est ce
        que le LLM de la phase 2 recevra comme définition d'outil."""
        return {
            "id": self.id,
            "titre": self.titre,
            "description": self.description,
            "parametres": self.parametres,
            "lecture": self.lecture,
            "permission": self.permission,
        }


# ── Helpers métier partagés par plusieurs handlers ─────────────────


async def _bail_contexte(db, bail: Bail) -> dict:
    """Locataire + logement + immeuble d'un bail (pour les aperçus)."""
    loc = await db.get(Locataire, bail.locataire_id)
    lg = await db.get(Logement, bail.logement_id)
    imm = await db.get(Immeuble, lg.immeuble_id) if lg else None
    return {
        "locataire_id": loc.id if loc else None,
        "locataire": loc.full_name if loc else "Locataire inconnu",
        "logement_id": lg.id if lg else None,
        "logement": lg.numero if lg else None,
        "immeuble_id": imm.id if imm else None,
        "immeuble": imm.name if imm else None,
    }


def _libelle_bail(ctx: dict) -> str:
    """« Daniel Drouin, 218 » (ou juste le nom si logement inconnu)."""
    if ctx.get("logement"):
        return f"{ctx['locataire']}, {ctx['logement']}"
    return str(ctx["locataire"])


async def _restant_du_mois(db, bail: Bail, mois: date) -> float:
    """Restant dû d'un mois : loyer + frais du mois − déjà payé —
    EXACTEMENT la même formule que ``create_paiement`` (endpoint
    immobilier), pour que l'aperçu annonce le montant que « Marquer
    payé » couvrirait à la main."""
    loyer = float(bail.loyer_mensuel or 0)
    frais = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(FraisLocatif.montant), 0))
                .where(
                    FraisLocatif.bail_id == bail.id,
                    FraisLocatif.mois_couvert == mois,
                )
            )
        ).scalar() or 0
    )
    deja = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(PaiementLoyer.montant), 0))
                .where(
                    PaiementLoyer.bail_id == bail.id,
                    PaiementLoyer.mois_couvert == mois,
                )
            )
        ).scalar() or 0
    )
    return round(loyer + frais - deja, 2)


async def _bail_ou_404(db, bail_id: int) -> Bail:
    bail = await db.get(Bail, bail_id)
    if bail is None:
        raise HTTPException(
            status_code=404, detail=f"Bail #{bail_id} introuvable."
        )
    return bail


async def _immeuble_ou_404(db, immeuble_id: int) -> Immeuble:
    imm = await db.get(Immeuble, immeuble_id)
    if imm is None:
        raise HTTPException(
            status_code=404, detail=f"Immeuble #{immeuble_id} introuvable."
        )
    return imm


async def _bail_actif_recent(db, *, locataire_id: int | None = None,
                             logement_id: int | None = None) -> Optional[Bail]:
    """Le bail ACTIF le plus récent d'un locataire ou d'un logement."""
    q = select(Bail).where(Bail.status == BailStatus.ACTIF.value)
    if locataire_id is not None:
        q = q.where(Bail.locataire_id == locataire_id)
    if logement_id is not None:
        q = q.where(Bail.logement_id == logement_id)
    q = q.order_by(Bail.date_debut.desc())
    return (await db.execute(q)).scalars().first()


# ═══════════════════════════════════════════════════════════════════
# Handlers de LECTURE
# ═══════════════════════════════════════════════════════════════════


async def _h_rechercher_locataire(
    db, user: User, params: dict, apercu_seulement: bool = False
) -> dict:
    """Nom / téléphone / courriel → fiches + bail actif (logement,
    immeuble, loyer). Recherche en mémoire sur les fiches (portefeuille
    à échelle humaine) : permet le match téléphone tous formats (mêmes
    normalisations que la détection de doublons de fiches)."""
    recherche = str(params["recherche"]).strip()
    if len(recherche) < 2:
        raise ParamsInvalides(
            "« recherche » : au moins 2 caractères sont requis."
        )
    terme = recherche.lower()
    chiffres = re.sub(r"\D", "", recherche)
    tel_cherche = chiffres[-10:] if len(chiffres) >= 7 else ""

    rows = (
        await db.execute(select(Locataire).order_by(Locataire.full_name))
    ).scalars().all()

    trouves: list[Locataire] = []
    for r in rows:
        nom_ok = terme in (r.full_name or "").lower()
        courriel_ok = terme in (r.email or "").lower()
        tel_ok = bool(tel_cherche) and tel_cherche in re.sub(
            r"\D", "", r.phone or ""
        )
        if nom_ok or courriel_ok or tel_ok:
            trouves.append(r)
        if len(trouves) >= 10:
            break

    resultats = []
    for loc in trouves:
        bail = await _bail_actif_recent(db, locataire_id=loc.id)
        fiche: dict[str, Any] = {
            "locataire_id": loc.id,
            "nom": loc.full_name,
            "courriel": loc.email,
            "telephone": loc.phone,
            "score_paiement": loc.paiement_score,
            "bail_actuel": None,
        }
        if bail is not None:
            ctx = await _bail_contexte(db, bail)
            fiche["bail_actuel"] = {
                "bail_id": bail.id,
                "immeuble": ctx["immeuble"],
                "immeuble_id": ctx["immeuble_id"],
                "logement": ctx["logement"],
                "logement_id": ctx["logement_id"],
                "loyer_mensuel": float(bail.loyer_mensuel or 0),
                "date_debut": bail.date_debut.isoformat(),
                "date_fin": bail.date_fin.isoformat(),
                "au_mois": bool(bail.au_mois),
            }
        resultats.append(fiche)

    return {"recherche": recherche, "nb": len(resultats),
            "resultats": resultats}


async def _h_rechercher_immeuble(
    db, user: User, params: dict, apercu_seulement: bool = False
) -> dict:
    """Nom / adresse / ville → immeubles visibles par l'utilisateur
    (mêmes règles d'affectation par employé que les pages du pôle)."""
    from app.core.permissions import visible_immeuble_ids

    recherche = str(params["recherche"]).strip()
    if len(recherche) < 2:
        raise ParamsInvalides(
            "« recherche » : au moins 2 caractères sont requis."
        )
    motif = f"%{recherche}%"
    q = (
        select(Immeuble)
        .where(
            Immeuble.is_active.is_(True),
            or_(
                Immeuble.name.ilike(motif),
                Immeuble.address.ilike(motif),
                Immeuble.city.ilike(motif),
            ),
        )
        .order_by(Immeuble.name)
        .limit(10)
    )
    rows = (await db.execute(q)).scalars().all()
    visibles = await visible_immeuble_ids(db, user)
    if visibles is not None:
        rows = [r for r in rows if r.id in visibles]

    return {
        "recherche": recherche,
        "nb": len(rows),
        "resultats": [
            {
                "immeuble_id": r.id,
                "nom": r.name,
                "adresse": r.address,
                "ville": r.city,
                "nb_logements": r.nb_logements,
                "gestion_externe": bool(r.gestion_externe),
            }
            for r in rows
        ],
    }


async def _h_solde_bail(
    db, user: User, params: dict, apercu_seulement: bool = False
) -> dict:
    """Solde cumulatif dû sur un bail — MÊME formule que la colonne
    « solde » de /loyers/overview : loyers échus depuis le démarrage du
    pôle + frais − paiements, borné à 0 (un bail au mois court sans
    égard à sa date de fin)."""
    from app.services.locatif_demarrage import get_demarrage

    bail: Optional[Bail] = None
    if params.get("bail_id") is not None:
        bail = await _bail_ou_404(db, int(params["bail_id"]))
    elif params.get("locataire_id") is not None:
        bail = await _bail_actif_recent(
            db, locataire_id=int(params["locataire_id"])
        )
    elif params.get("logement_id") is not None:
        bail = await _bail_actif_recent(
            db, logement_id=int(params["logement_id"])
        )
    else:
        raise ParamsInvalides(
            "Fournir « bail_id », « locataire_id » ou « logement_id »."
        )
    if bail is None:
        raise HTTPException(
            status_code=404,
            detail="Aucun bail actif trouvé pour ce locataire / logement.",
        )

    depuis = await get_demarrage()
    today = _aujourdhui()
    mois_courant = today.replace(day=1)

    # Mois échus — même règle que _mois_echus de /loyers/overview.
    debut = max(bail.date_debut.replace(day=1), depuis)
    fin = mois_courant
    if bail.date_fin and (
        not bail.au_mois or bail.status != BailStatus.ACTIF.value
    ):
        fin = min(fin, bail.date_fin.replace(day=1))
    if fin < debut:
        nb_mois = 0
    else:
        nb_mois = (fin.year - debut.year) * 12 + (fin.month - debut.month) + 1

    frais_total = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(FraisLocatif.montant), 0))
                .where(
                    FraisLocatif.bail_id == bail.id,
                    FraisLocatif.mois_couvert >= depuis,
                    FraisLocatif.mois_couvert <= mois_courant,
                )
            )
        ).scalar() or 0
    )
    paye_total = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(PaiementLoyer.montant), 0))
                .where(
                    PaiementLoyer.bail_id == bail.id,
                    PaiementLoyer.mois_couvert >= depuis,
                )
            )
        ).scalar() or 0
    )
    loyer = float(bail.loyer_mensuel or 0)
    solde = max(0.0, round(nb_mois * loyer + frais_total - paye_total, 2))

    ctx = await _bail_contexte(db, bail)
    return {
        "bail_id": bail.id,
        "locataire": ctx["locataire"],
        "logement": ctx["logement"],
        "immeuble": ctx["immeuble"],
        "loyer_mensuel": loyer,
        "statut_bail": bail.status,
        "solde_du": solde,
        "detail": {
            "mois_echus": nb_mois,
            "loyers_echus": round(nb_mois * loyer, 2),
            "frais": round(frais_total, 2),
            "paye": round(paye_total, 2),
            "depuis": depuis.isoformat(),
        },
    }


async def _h_loyers_du_mois(
    db, user: User, params: dict, apercu_seulement: bool = False
) -> dict:
    """État des loyers d'un mois — délègue à /loyers/overview (mêmes
    règles : reconduction tacite, gestion externe exclue, retards par
    jour d'échéance), puis filtre par immeuble si demandé."""
    # Import paresseux : l'endpoint EST le service de cette vue.
    from app.api.v1.endpoints.immobilier import loyers_overview

    overview = await loyers_overview(db, user, mois=params.get("mois"))
    rows = overview.rows
    immeuble_id = params.get("immeuble_id")
    if immeuble_id is not None:
        rows = [r for r in rows if r.immeuble_id == int(immeuble_id)]

    return {
        "mois": overview.mois,
        "nb_baux": len(rows),
        "total_attendu": round(
            sum(r.loyer_mensuel for r in rows), 2
        ) if immeuble_id is not None else overview.total_attendu,
        "total_recu": round(
            sum(r.montant_paye or 0 for r in rows), 2
        ) if immeuble_id is not None else overview.total_recu,
        "rows": [
            {
                "bail_id": r.bail_id,
                "immeuble": r.immeuble_name,
                "logement": r.logement_numero,
                "locataire": r.locataire_name,
                "loyer_mensuel": r.loyer_mensuel,
                "montant_paye": r.montant_paye,
                "etat": r.etat,
                "solde_total": r.solde_total,
            }
            for r in rows
        ],
    }


async def _h_baux_echeants(
    db, user: User, params: dict, apercu_seulement: bool = False
) -> dict:
    """Baux ACTIFS dont la date de fin tombe d'ici N mois (les baux au
    mois, reconduits automatiquement, sont exclus)."""
    horizon = int(params.get("horizon_mois", 6))
    today = _aujourdhui()
    # Ajout de mois calendaire (pas d'approximation en jours).
    mois_total = today.month - 1 + horizon
    annee = today.year + mois_total // 12
    mois = mois_total % 12 + 1
    import calendar

    jour = min(today.day, calendar.monthrange(annee, mois)[1])
    limite = date(annee, mois, jour)

    baux = (
        await db.execute(
            select(Bail)
            .where(
                Bail.status == BailStatus.ACTIF.value,
                Bail.au_mois.isnot(True),
                Bail.date_fin >= today,
                Bail.date_fin <= limite,
            )
            .order_by(Bail.date_fin.asc())
        )
    ).scalars().all()

    rows = []
    for b in baux:
        ctx = await _bail_contexte(db, b)
        rows.append(
            {
                "bail_id": b.id,
                "locataire": ctx["locataire"],
                "logement": ctx["logement"],
                "immeuble": ctx["immeuble"],
                "loyer_mensuel": float(b.loyer_mensuel or 0),
                "date_fin": b.date_fin.isoformat(),
            }
        )
    return {
        "horizon_mois": horizon,
        "jusqu_au": limite.isoformat(),
        "nb": len(rows),
        "rows": rows,
    }


async def _h_depenses_immeuble(
    db, user: User, params: dict, apercu_seulement: bool = False
) -> dict:
    """Dépenses d'exploitation d'un immeuble — délègue au listing du
    pôle (mêmes gardes de visibilité), filtre par année, et annualise
    comme le P&L (ponctuel ×1 dans son année, mensuel ×12, annuel ×1)."""
    from app.api.v1.endpoints.immobilier import list_depenses

    immeuble_id = int(params["immeuble_id"])
    annee = params.get("annee") or _aujourdhui().year
    imm = await _immeuble_ou_404(db, immeuble_id)
    depenses = await list_depenses(immeuble_id, db, user)

    rows = []
    total = 0.0
    for d in depenses:
        if d.frequence == "ponctuel":
            if d.date_depense is not None and d.date_depense.year != annee:
                continue
            annualise = float(d.montant)
        elif d.frequence == "mensuel":
            annualise = float(d.montant) * 12
        else:  # annuel
            annualise = float(d.montant)
        rows.append(
            {
                "depense_id": d.id,
                "categorie": d.categorie,
                "libelle": d.libelle,
                "montant": float(d.montant),
                "frequence": d.frequence,
                "is_pourcentage": bool(d.is_pourcentage),
                "taxable": bool(d.taxable),
                "date_depense": (
                    d.date_depense.isoformat() if d.date_depense else None
                ),
            }
        )
        # Les dépenses en % des loyers n'ont pas de montant fixe : hors
        # du total (même prudence que l'affichage de la fiche).
        if not d.is_pourcentage:
            total += annualise

    return {
        "immeuble_id": immeuble_id,
        "immeuble": imm.name,
        "annee": annee,
        "nb": len(rows),
        "total_annuel_estime": round(total, 2),
        "rows": rows,
    }


# ═══════════════════════════════════════════════════════════════════
# Handlers d'ÉCRITURE (aperçu obligatoire, exécution via les services
# existants — mêmes chemins que la saisie manuelle)
# ═══════════════════════════════════════════════════════════════════


async def _h_marquer_loyer_paye(
    db, user: User, params: dict, apercu_seulement: bool = False
) -> dict:
    """Marquer un loyer payé — exécute ``create_paiement`` (le même
    chemin que le bouton « Marquer payé ») : trop-payé réparti sur les
    mois suivants, flag de retard, score de paiement recalculé."""
    bail = await _bail_ou_404(db, int(params["bail_id"]))
    mois = _parse_mois(params["mois"])

    # Mêmes gardes de statut que create_paiement, appliquées dès
    # l'aperçu pour que la carte échoue AVANT la confirmation.
    if bail.status == BailStatus.PROPOSE.value:
        raise HTTPException(
            status_code=400,
            detail=(
                "Ce bail n'est pas actif — un paiement ne peut être "
                "enregistré que sur un bail actif."
            ),
        )
    if bail.status in (BailStatus.RESILIE.value, BailStatus.TERMINE.value):
        couvre = (
            bail.date_fin is not None
            and bail.date_debut is not None
            and bail.date_debut.replace(day=1)
            <= mois
            <= bail.date_fin.replace(day=1)
        )
        if not couvre:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Ce bail est terminé — un paiement ne peut viser "
                    "qu'un mois couvert par le bail."
                ),
            )

    montant = params.get("montant")
    if montant is None:
        # Défaut = le restant dû du mois (loyer + frais − déjà payé),
        # comme le « Marquer payé » en 1 clic.
        montant = await _restant_du_mois(db, bail, mois)
        if montant <= 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Rien à percevoir pour {_mois_fr(mois)} : le mois "
                    "est déjà couvert. Fournir « montant » pour forcer "
                    "un paiement supplémentaire."
                ),
            )
    montant = round(float(montant), 2)
    if montant <= 0:
        raise ParamsInvalides("« montant » : doit être supérieur à 0.")

    paye_le = (
        _parse_date(params["paye_le"], "paye_le")
        if params.get("paye_le")
        else _aujourdhui()
    )

    ctx = await _bail_contexte(db, bail)
    apercu = (
        f"Marquer payé : {_libelle_bail(ctx)} — {_montant_fr(montant)} "
        f"pour {_mois_fr(mois)}"
    )
    if apercu_seulement:
        return {"apercu": apercu}

    # EXÉCUTION : le même endpoint que la saisie manuelle.
    from app.api.v1.endpoints.immobilier import create_paiement
    from app.schemas.immobilier import PaiementLoyerCreate

    cree = await create_paiement(
        PaiementLoyerCreate(
            bail_id=bail.id,
            mois_couvert=mois,
            montant=montant,
            paye_le=paye_le,
            methode=params.get("methode"),
            reference=params.get("reference"),
            notes=params.get("notes"),
        ),
        db,
        user,
    )
    return {"apercu": apercu, "paiement": cree.model_dump(mode="json")}


#: Modèle parent par pôle pour ``creer_tache`` (aligné sur
#: ``create_task_for_pole`` du module activity).
_POLES_TACHE = ("entreprise", "devlog", "prospection", "construction")

_POLE_TACHE_LABELS = {
    "entreprise": "Gestion d'entreprises",
    "devlog": "Développement logiciel",
    "prospection": "Prospection",
    "construction": "Construction",
}


async def _parent_tache(db, pole: str, parent_id: int):
    """L'entité parente d'une tâche selon le pôle (None si introuvable)."""
    if pole == "entreprise":
        from app.models.entreprise import Entreprise

        return await db.get(Entreprise, parent_id)
    if pole == "devlog":
        from app.models.devlog_project import DevlogProject

        return await db.get(DevlogProject, parent_id)
    if pole == "prospection":
        from app.models.prospection_deal import ProspectionDeal

        return await db.get(ProspectionDeal, parent_id)
    from app.models.project import Project

    return await db.get(Project, parent_id)


async def _h_creer_tache(
    db, user: User, params: dict, apercu_seulement: bool = False
) -> dict:
    """Créer une tâche — exécute ``create_task_for_pole`` (le même
    service que le connecteur MCP et les endpoints de tâches)."""
    pole = params.get("pole", "entreprise")
    parent_id = int(params["parent_id"])
    titre = str(params["titre"]).strip()
    if not titre:
        raise ParamsInvalides("« titre » est requis.")

    parent = await _parent_tache(db, pole, parent_id)
    if parent is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Entité parente #{parent_id} introuvable dans le pôle "
                f"{_POLE_TACHE_LABELS[pole]}."
            ),
        )
    nom_parent = (
        getattr(parent, "name", None)
        or getattr(parent, "title", None)
        or getattr(parent, "address", None)
        or f"#{parent_id}"
    )

    echeance = (
        _parse_date(params["echeance"], "echeance")
        if params.get("echeance")
        else None
    )
    assigne = (params.get("assigne") or "").strip() or None

    apercu = (
        f"Créer la tâche « {titre} » pour {nom_parent} "
        f"({_POLE_TACHE_LABELS[pole]})"
    )
    if echeance is not None:
        apercu += f" — échéance le {echeance.isoformat()}"
    if assigne:
        apercu += f", assignée à {assigne}"

    if apercu_seulement:
        return {"apercu": apercu}

    # EXÉCUTION : le même service que la création manuelle / MCP.
    from app.api.v1.endpoints.activity import create_task_for_pole

    try:
        cree = await create_task_for_pole(
            db,
            user,
            pole=pole,
            parent_id=parent_id,
            title=titre,
            description=params.get("description"),
            due_date=echeance,
            assignee=assigne,
            via="assistant_ia",
        )
    except ValueError as exc:
        # Assigné introuvable / ambigu, pôle refusé… → 400 FR propre.
        raise HTTPException(status_code=400, detail=str(exc))
    return {"apercu": apercu, "tache": cree.model_dump(mode="json")}


_CATEGORIES_DEPENSE = (
    "taxes_municipales", "taxes_scolaires", "assurances", "energie",
    "entretien", "deneigement", "conciergerie", "gestion", "autre",
)

_LABELS_FREQUENCE = {
    "ponctuel": "ponctuelle",
    "mensuel": "mensuelle",
    "annuel": "annuelle",
}


async def _h_ajouter_depense_immeuble(
    db, user: User, params: dict, apercu_seulement: bool = False
) -> dict:
    """Ajouter une dépense d'exploitation — exécute ``create_depense``
    (mêmes gardes de visibilité d'immeuble que la fiche)."""
    immeuble_id = int(params["immeuble_id"])
    imm = await _immeuble_ou_404(db, immeuble_id)

    libelle = str(params["libelle"]).strip()
    if not libelle:
        raise ParamsInvalides("« libelle » est requis.")
    montant = round(float(params["montant"]), 2)
    categorie = params.get("categorie", "autre")
    frequence = params.get("frequence", "ponctuel")
    date_depense = (
        _parse_date(params["date_depense"], "date_depense")
        if params.get("date_depense")
        else None
    )

    apercu = (
        f"Ajouter la dépense {_LABELS_FREQUENCE[frequence]} "
        f"« {libelle} » ({categorie}) : {_montant_fr(montant)} — "
        f"{imm.name}"
    )
    if apercu_seulement:
        # Vérifier dès l'aperçu que l'utilisateur voit cet immeuble
        # (même garde que l'endpoint — sinon la confirmation échouerait).
        from app.api.v1.endpoints.immobilier import (
            _require_immeuble_visible,
        )

        await _require_immeuble_visible(db, user, immeuble_id)
        return {"apercu": apercu}

    from app.api.v1.endpoints.immobilier import DepenseCreate, create_depense

    cree = await create_depense(
        immeuble_id,
        DepenseCreate(
            categorie=categorie,
            libelle=libelle,
            montant=montant,
            frequence=frequence,
            is_pourcentage=bool(params.get("is_pourcentage", False)),
            taxable=bool(params.get("taxable", False)),
            date_depense=date_depense,
            notes=params.get("notes"),
        ),
        db,
        user,
    )
    return {"apercu": apercu, "depense": cree.model_dump(mode="json")}


_KINDS_EVALUATION = ("municipale", "marchande", "appraisal", "auto")

_LABELS_EVALUATION = {
    "municipale": "municipale",
    "marchande": "marchande",
    "appraisal": "professionnelle (appraisal)",
    "auto": "interne (auto)",
}


async def _h_ajouter_evaluation(
    db, user: User, params: dict, apercu_seulement: bool = False
) -> dict:
    """Ajouter une évaluation de valeur — exécute ``create_evaluation``
    (une seule évaluation de référence par immeuble, règle préservée)."""
    immeuble_id = int(params["immeuble_id"])
    imm = await _immeuble_ou_404(db, immeuble_id)
    valeur = round(float(params["valeur"]), 2)
    kind = params.get("kind", "marchande")
    date_evaluation = (
        _parse_date(params["date_evaluation"], "date_evaluation")
        if params.get("date_evaluation")
        else _aujourdhui()
    )

    apercu = (
        f"Ajouter une évaluation {_LABELS_EVALUATION[kind]} de "
        f"{_montant_fr(valeur)} au {date_evaluation.isoformat()} — "
        f"{imm.name}"
    )
    if params.get("is_reference"):
        apercu += " (nouvelle référence pour l'équité)"
    if apercu_seulement:
        return {"apercu": apercu}

    from app.api.v1.endpoints.immobilier import create_evaluation
    from app.schemas.immobilier import EvaluationCreate

    cree = await create_evaluation(
        EvaluationCreate(
            immeuble_id=immeuble_id,
            kind=kind,
            valeur=valeur,
            date_evaluation=date_evaluation,
            source=params.get("source"),
            notes=params.get("notes"),
            is_reference=bool(params.get("is_reference", False)),
        ),
        db,
        user,
    )
    return {"apercu": apercu, "evaluation": cree.model_dump(mode="json")}


_KINDS_NOTE = ("note", "appel", "courriel", "sms", "visite", "autre")


async def _h_ajouter_note_locataire(
    db, user: User, params: dict, apercu_seulement: bool = False
) -> dict:
    """Consigner une note au journal d'un locataire — exécute
    ``create_locataire_communication`` (fiche locataire)."""
    locataire_id = int(params["locataire_id"])
    loc = await db.get(Locataire, locataire_id)
    if loc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Locataire #{locataire_id} introuvable.",
        )
    contenu = str(params["contenu"]).strip()
    if not contenu:
        raise ParamsInvalides("« contenu » est requis.")
    kind = params.get("kind", "note")

    extrait = contenu if len(contenu) <= 80 else contenu[:77] + "…"
    apercu = (
        f"Ajouter une note ({kind}) à la fiche de {loc.full_name} : "
        f"« {extrait} »"
    )
    if apercu_seulement:
        return {"apercu": apercu}

    from app.api.v1.endpoints.immobilier import (
        create_locataire_communication,
    )
    from app.schemas.immobilier import LocataireCommunicationCreate

    cree = await create_locataire_communication(
        locataire_id,
        LocataireCommunicationCreate(kind=kind, contenu=contenu),
        db,
        user,
    )
    return {"apercu": apercu, "note": cree.model_dump(mode="json")}


async def _h_ajouter_frais_bail(
    db, user: User, params: dict, apercu_seulement: bool = False
) -> dict:
    """Ajouter un frais ponctuel au solde d'un bail — exécute
    ``create_frais`` (ex. 20 $ de frais de retard)."""
    bail = await _bail_ou_404(db, int(params["bail_id"]))
    # Même garde-fou que create_frais, appliqué dès l'aperçu : un frais
    # sur un bail non actif serait invisible partout.
    if bail.status != BailStatus.ACTIF.value:
        raise HTTPException(
            status_code=400,
            detail="Un frais ne s'ajoute que sur un bail actif.",
        )
    montant = round(float(params["montant"]), 2)
    libelle = str(params.get("libelle") or "Frais de retard").strip()
    mois = (
        _parse_mois(params["mois"])
        if params.get("mois")
        else _aujourdhui().replace(day=1)
    )

    ctx = await _bail_contexte(db, bail)
    apercu = (
        f"Ajouter un frais « {libelle} » de {_montant_fr(montant)} au "
        f"bail de {_libelle_bail(ctx)} pour {_mois_fr(mois)}"
    )
    if apercu_seulement:
        return {"apercu": apercu}

    from app.api.v1.endpoints.immobilier import FraisCreate, create_frais

    cree = await create_frais(
        bail.id,
        FraisCreate(mois_couvert=mois, montant=montant, libelle=libelle),
        db,
        user,
    )
    return {"apercu": apercu, "frais": cree.model_dump(mode="json")}


# ═══════════════════════════════════════════════════════════════════
# Le catalogue
# ═══════════════════════════════════════════════════════════════════

OUTILS: list[OutilAssistant] = [
    # ── LECTURE ────────────────────────────────────────────────────
    OutilAssistant(
        id="rechercher_locataire",
        titre="Rechercher un locataire",
        description=(
            "Retrouve des fiches de locataires par nom, téléphone ou "
            "courriel (max 10 résultats). Chaque fiche inclut le bail "
            "ACTIF actuel (immeuble, logement, loyer, dates) quand il y "
            "en a un. À utiliser en premier quand l'utilisateur parle "
            "d'un locataire par son nom (« mets Daniel Drouin payé ») "
            "pour obtenir le bail_id nécessaire aux autres outils. "
            "Paramètre « recherche » : le nom (partiel accepté), un "
            "numéro de téléphone (tous formats) ou un courriel."
        ),
        parametres={
            "type": "object",
            "properties": {
                "recherche": {
                    "type": "string",
                    "description": "Nom, téléphone ou courriel (≥ 2 caractères).",
                },
            },
            "required": ["recherche"],
            "additionalProperties": False,
        },
        lecture=True,
        permission="immobilier.locataires",
        handler=_h_rechercher_locataire,
    ),
    OutilAssistant(
        id="rechercher_immeuble",
        titre="Rechercher un immeuble",
        description=(
            "Retrouve des immeubles du portefeuille par nom, adresse ou "
            "ville (max 10 résultats, immeubles actifs seulement). À "
            "utiliser quand l'utilisateur désigne un immeuble par son "
            "adresse (« le 8900 ») pour obtenir l'immeuble_id des "
            "autres outils. Paramètre « recherche » : nom, adresse ou "
            "ville (partiel accepté)."
        ),
        parametres={
            "type": "object",
            "properties": {
                "recherche": {
                    "type": "string",
                    "description": "Nom, adresse ou ville (≥ 2 caractères).",
                },
            },
            "required": ["recherche"],
            "additionalProperties": False,
        },
        lecture=True,
        permission="immobilier.immeubles",
        handler=_h_rechercher_immeuble,
    ),
    OutilAssistant(
        id="solde_bail",
        titre="Solde dû d'un bail",
        description=(
            "Calcule le solde cumulatif dû sur un bail (loyers échus + "
            "frais − paiements, borné à 0 — même formule que la page "
            "Paiements). Fournir UN de : « bail_id » (précis), "
            "« locataire_id » ou « logement_id » (le bail actif le plus "
            "récent est retenu). Retourne aussi le détail du calcul "
            "(mois échus, frais, payé)."
        ),
        parametres={
            "type": "object",
            "properties": {
                "bail_id": {
                    "type": "integer",
                    "description": "Id du bail (prioritaire).",
                },
                "locataire_id": {
                    "type": "integer",
                    "description": "Id du locataire (bail actif retenu).",
                },
                "logement_id": {
                    "type": "integer",
                    "description": "Id du logement (bail actif retenu).",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        lecture=True,
        permission="immobilier.paiements",
        handler=_h_solde_bail,
    ),
    OutilAssistant(
        id="loyers_du_mois",
        titre="Loyers du mois",
        description=(
            "État des loyers d'un mois donné : qui a payé, qui est en "
            "retard, qui est en attente, avec les soldes cumulatifs — "
            "la même vue que la page Paiements. « mois » au format "
            "YYYY-MM (défaut : mois courant) ; « immeuble_id » pour "
            "restreindre à un immeuble (défaut : tout le portefeuille)."
        ),
        parametres={
            "type": "object",
            "properties": {
                "mois": {
                    "type": "string",
                    "description": "Mois YYYY-MM (défaut : mois courant).",
                },
                "immeuble_id": {
                    "type": "integer",
                    "description": "Restreindre à cet immeuble.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        lecture=True,
        permission="immobilier.paiements",
        handler=_h_loyers_du_mois,
    ),
    OutilAssistant(
        id="baux_echeants",
        titre="Baux qui échoient bientôt",
        description=(
            "Liste les baux ACTIFS dont la date de fin tombe d'ici N "
            "mois (« horizon_mois », défaut 6, max 24), triés par date "
            "de fin. Les baux « au mois » (reconduits automatiquement) "
            "sont exclus. Utile pour préparer les renouvellements ou "
            "répondre à « quels baux finissent bientôt ? »."
        ),
        parametres={
            "type": "object",
            "properties": {
                "horizon_mois": {
                    "type": "integer",
                    "description": "Fenêtre en mois (défaut 6).",
                    "minimum": 1,
                    "maximum": 24,
                    "default": 6,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        lecture=True,
        permission="immobilier.baux",
        handler=_h_baux_echeants,
    ),
    OutilAssistant(
        id="depenses_immeuble",
        titre="Dépenses d'un immeuble",
        description=(
            "Liste les dépenses d'exploitation d'un immeuble pour une "
            "année (« annee », défaut : année courante) avec un total "
            "annuel estimé (ponctuel compté dans son année, mensuel "
            "×12, annuel ×1 ; les dépenses en % des loyers sont listées "
            "mais hors total). « immeuble_id » requis — utiliser "
            "rechercher_immeuble d'abord si besoin."
        ),
        parametres={
            "type": "object",
            "properties": {
                "immeuble_id": {
                    "type": "integer",
                    "description": "Id de l'immeuble.",
                },
                "annee": {
                    "type": "integer",
                    "description": "Année (défaut : courante).",
                    "minimum": 2000,
                    "maximum": 2100,
                },
            },
            "required": ["immeuble_id"],
            "additionalProperties": False,
        },
        lecture=True,
        permission="immobilier.finances",
        handler=_h_depenses_immeuble,
    ),
    # ── ÉCRITURE (carte d'action + confirmation humaine) ───────────
    OutilAssistant(
        id="marquer_loyer_paye",
        titre="Marquer un loyer payé",
        description=(
            "Enregistre un paiement de loyer sur un bail pour un mois "
            "donné — même chemin que le bouton « Marquer payé » : un "
            "trop-payé est réparti sur les mois suivants, le retard est "
            "marqué selon le jour d'échéance du bail et le score de "
            "paiement du locataire est recalculé. « bail_id » requis "
            "(utiliser rechercher_locataire pour le trouver) ; « mois » "
            "YYYY-MM requis ; « montant » optionnel (défaut : le "
            "restant dû du mois = loyer + frais − déjà payé) ; "
            "« paye_le » date optionnelle (défaut : aujourd'hui) ; "
            "« methode » et « reference » optionnels."
        ),
        parametres={
            "type": "object",
            "properties": {
                "bail_id": {
                    "type": "integer",
                    "description": "Id du bail.",
                },
                "mois": {
                    "type": "string",
                    "description": "Mois couvert, format YYYY-MM.",
                },
                "montant": {
                    "type": "number",
                    "description": (
                        "Montant reçu (défaut : restant dû du mois)."
                    ),
                    "exclusiveMinimum": 0,
                },
                "paye_le": {
                    "type": "string",
                    "description": "Date du paiement YYYY-MM-DD (défaut : aujourd'hui).",
                },
                "methode": {
                    "type": "string",
                    "description": "Méthode (virement, chèque, comptant…).",
                },
                "reference": {
                    "type": "string",
                    "description": "Référence du paiement (n° de confirmation…).",
                },
                "notes": {
                    "type": "string",
                    "description": "Note libre sur le paiement.",
                },
            },
            "required": ["bail_id", "mois"],
            "additionalProperties": False,
        },
        lecture=False,
        permission="immobilier.paiements",
        handler=_h_marquer_loyer_paye,
    ),
    OutilAssistant(
        id="creer_tache",
        titre="Créer une tâche",
        description=(
            "Crée une tâche dans un pôle de Kratos — même service que "
            "la création manuelle. « pole » : entreprise (défaut), "
            "devlog, prospection ou construction. « parent_id » requis "
            "= l'entité qui porte la tâche selon le pôle (entreprise, "
            "projet devlog, deal de prospection, projet de chantier). "
            "« titre » requis ; « description », « echeance » "
            "(YYYY-MM-DD) et « assigne » (courriel, nom ou id d'un "
            "membre — défaut : l'utilisateur courant) optionnels."
        ),
        parametres={
            "type": "object",
            "properties": {
                "pole": {
                    "type": "string",
                    "description": "Pôle de la tâche.",
                    "enum": list(_POLES_TACHE),
                    "default": "entreprise",
                },
                "parent_id": {
                    "type": "integer",
                    "description": "Id de l'entité parente (selon le pôle).",
                },
                "titre": {
                    "type": "string",
                    "description": "Titre de la tâche.",
                },
                "description": {
                    "type": "string",
                    "description": "Détails de la tâche.",
                },
                "echeance": {
                    "type": "string",
                    "description": "Date d'échéance YYYY-MM-DD.",
                },
                "assigne": {
                    "type": "string",
                    "description": (
                        "Assigné : courriel, nom ou id d'un membre "
                        "(défaut : soi-même)."
                    ),
                },
            },
            "required": ["parent_id", "titre"],
            "additionalProperties": False,
        },
        lecture=False,
        permission="general.mes_taches",
        handler=_h_creer_tache,
    ),
    OutilAssistant(
        id="ajouter_depense_immeuble",
        titre="Ajouter une dépense d'immeuble",
        description=(
            "Ajoute une dépense d'exploitation à un immeuble (taxes, "
            "assurances, entretien, déneigement, énergie…) — même "
            "chemin que la fiche immeuble. « immeuble_id », « libelle » "
            "et « montant » requis. « categorie » (défaut autre), "
            "« frequence » : ponctuel (défaut, compté dans son année), "
            "mensuel (×12 au P&L) ou annuel. « date_depense » "
            "(YYYY-MM-DD), « taxable » (TPS+TVQ appliquées aux "
            "calculs), « is_pourcentage » (montant = % des loyers) et "
            "« notes » optionnels."
        ),
        parametres={
            "type": "object",
            "properties": {
                "immeuble_id": {
                    "type": "integer",
                    "description": "Id de l'immeuble.",
                },
                "libelle": {
                    "type": "string",
                    "description": "Libellé de la dépense.",
                },
                "montant": {
                    "type": "number",
                    "description": "Montant (ou % si is_pourcentage).",
                    "exclusiveMinimum": 0,
                },
                "categorie": {
                    "type": "string",
                    "description": "Catégorie de la dépense.",
                    "enum": list(_CATEGORIES_DEPENSE),
                    "default": "autre",
                },
                "frequence": {
                    "type": "string",
                    "description": "Fréquence (pilote l'annualisation).",
                    "enum": ["ponctuel", "mensuel", "annuel"],
                    "default": "ponctuel",
                },
                "date_depense": {
                    "type": "string",
                    "description": "Date YYYY-MM-DD (dépense ponctuelle).",
                },
                "taxable": {
                    "type": "boolean",
                    "description": "Appliquer TPS+TVQ dans les calculs.",
                    "default": False,
                },
                "is_pourcentage": {
                    "type": "boolean",
                    "description": "Montant exprimé en % des loyers.",
                    "default": False,
                },
                "notes": {
                    "type": "string",
                    "description": "Note libre.",
                },
            },
            "required": ["immeuble_id", "libelle", "montant"],
            "additionalProperties": False,
        },
        lecture=False,
        permission="immobilier.finances",
        handler=_h_ajouter_depense_immeuble,
    ),
    OutilAssistant(
        id="ajouter_evaluation",
        titre="Ajouter une évaluation",
        description=(
            "Ajoute un snapshot de valeur à un immeuble (évaluation "
            "municipale, marchande, appraisal pro ou estimation "
            "interne) — même chemin que la fiche immeuble. "
            "« immeuble_id » et « valeur » requis. « kind » (défaut "
            "marchande), « date_evaluation » (YYYY-MM-DD, défaut "
            "aujourd'hui), « source », « notes » et « is_reference » "
            "(en faire LA valeur de référence pour le calcul d'équité — "
            "les autres perdent le statut) optionnels."
        ),
        parametres={
            "type": "object",
            "properties": {
                "immeuble_id": {
                    "type": "integer",
                    "description": "Id de l'immeuble.",
                },
                "valeur": {
                    "type": "number",
                    "description": "Valeur estimée ($).",
                    "exclusiveMinimum": 0,
                },
                "kind": {
                    "type": "string",
                    "description": "Type d'évaluation.",
                    "enum": list(_KINDS_EVALUATION),
                    "default": "marchande",
                },
                "date_evaluation": {
                    "type": "string",
                    "description": "Date YYYY-MM-DD (défaut : aujourd'hui).",
                },
                "source": {
                    "type": "string",
                    "description": "Source (rôle municipal, courtier…).",
                },
                "notes": {
                    "type": "string",
                    "description": "Note libre.",
                },
                "is_reference": {
                    "type": "boolean",
                    "description": "Référence pour le calcul d'équité.",
                    "default": False,
                },
            },
            "required": ["immeuble_id", "valeur"],
            "additionalProperties": False,
        },
        lecture=False,
        permission="immobilier.immeubles",
        handler=_h_ajouter_evaluation,
    ),
    OutilAssistant(
        id="ajouter_note_locataire",
        titre="Ajouter une note à un locataire",
        description=(
            "Consigne une entrée au journal de communications d'un "
            "locataire (fiche locataire) — même chemin que la saisie "
            "manuelle ; l'auteur est l'utilisateur courant. "
            "« locataire_id » et « contenu » requis ; « kind » précise "
            "le type d'entrée : note (défaut), appel, courriel, sms, "
            "visite ou autre."
        ),
        parametres={
            "type": "object",
            "properties": {
                "locataire_id": {
                    "type": "integer",
                    "description": "Id du locataire.",
                },
                "contenu": {
                    "type": "string",
                    "description": "Contenu de la note.",
                },
                "kind": {
                    "type": "string",
                    "description": "Type d'entrée du journal.",
                    "enum": list(_KINDS_NOTE),
                    "default": "note",
                },
            },
            "required": ["locataire_id", "contenu"],
            "additionalProperties": False,
        },
        lecture=False,
        permission="immobilier.locataires",
        handler=_h_ajouter_note_locataire,
    ),
    OutilAssistant(
        id="ajouter_frais_bail",
        titre="Ajouter un frais à un bail",
        description=(
            "Ajoute un frais ponctuel au solde dû d'un bail ACTIF (ex. "
            "20 $ de frais de retard si le loyer est payé après le 15) "
            "— même chemin que la page Paiements ; le frais est réglé "
            "implicitement quand les paiements couvrent loyers + frais. "
            "« bail_id » et « montant » requis ; « libelle » (défaut "
            "« Frais de retard ») et « mois » (YYYY-MM, défaut mois "
            "courant) optionnels."
        ),
        parametres={
            "type": "object",
            "properties": {
                "bail_id": {
                    "type": "integer",
                    "description": "Id du bail (actif).",
                },
                "montant": {
                    "type": "number",
                    "description": "Montant du frais ($).",
                    "exclusiveMinimum": 0,
                },
                "libelle": {
                    "type": "string",
                    "description": "Libellé (défaut : Frais de retard).",
                    "default": "Frais de retard",
                },
                "mois": {
                    "type": "string",
                    "description": "Mois de rattachement YYYY-MM (défaut : courant).",
                },
            },
            "required": ["bail_id", "montant"],
            "additionalProperties": False,
        },
        lecture=False,
        permission="immobilier.paiements",
        handler=_h_ajouter_frais_bail,
    ),
]

#: id → outil (lookup rapide).
OUTILS_PAR_ID: dict[str, OutilAssistant] = {o.id: o for o in OUTILS}


async def outils_pour_utilisateur(db, user: User) -> list[OutilAssistant]:
    """Le catalogue FILTRÉ selon les permissions de page de
    l'utilisateur — c'est ce que le LLM recevra en phase 2 (un outil
    invisible ici est aussi refusé à l'exécution)."""
    visibles: list[OutilAssistant] = []
    # Cache local : plusieurs outils partagent la même clé de page.
    acces: dict[str, bool] = {}
    for outil in OUTILS:
        if outil.permission not in acces:
            acces[outil.permission] = await utilisateur_a_acces_page(
                db, user, outil.permission
            )
        if acces[outil.permission]:
            visibles.append(outil)
    return visibles


async def executer_outil(
    db,
    user: User,
    outil: OutilAssistant,
    params: Any,
    apercu_seulement: bool = False,
) -> dict:
    """Valide les paramètres (schéma strict + défauts) puis appelle le
    handler. NE vérifie PAS la permission — c'est le rôle de l'appelant
    (endpoints), qui la contrôle au bon moment (proposition ET
    confirmation)."""
    propres = valider_params(outil, params)
    return await outil.handler(db, user, propres, apercu_seulement)
