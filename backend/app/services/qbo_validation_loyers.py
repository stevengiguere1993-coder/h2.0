"""Validation bancaire des loyers — QuickBooks en LECTURE SEULE.

2e validation des loyers (décision Phil + partenaires 2026-08-14), SANS
IA : l'adjointe publie les encaissements bancaires dans QuickBooks en
les catégorisant au compte « Loyer à remettre - {immeuble} » (un compte
du plan comptable par immeuble). Ce service :

1. DÉCOUVRE ces comptes (nom qui matche « loyer à remettre », insensible
   casse/accents) et SUGGÈRE l'immeuble correspondant par similarité de
   nom/adresse — la confirmation reste humaine (Paramètres) ;
2. SYNCHRONISE les écritures publiées qui touchent les comptes mappés
   via le rapport GeneralLedger (fenêtre glissante, idempotent par
   (type, id QBO, compte)) — le rapport couvre TOUT ce qui est publié
   (Deposits, écritures de journal, reçus de vente…), contrairement aux
   requêtes d'entités qui obligeraient à énumérer chaque type ;
3. RAPPROCHE chaque transaction d'un bail/mois de façon DÉTERMINISTE
   (montant == loyer du mois ou dû restant frais inclus, proximité de
   date, texte payeur vs nom du locataire / alias confirmés). Un seul
   candidat plausible → rapproché auto ; plusieurs → « ambigu » (aucun
   pronostic) ; aucun → « non rapproché » ;
4. Apprend un ALIAS de payeur quand un humain confirme un rapprochement
   ambigu — la même provenance se rapproche seule le mois suivant ;
5. Calcule l'ÉTAT affiché dans le pôle locatif : ✓✓ « Validé banque »,
   ⚠ « Payé — sans trace bancaire » (après N jours, réglable) et
   l'encart « Encaissés non marqués ».

⚠️ AUCUNE écriture dans QuickBooks. AUCUN appel LLM. AUCUN courriel.
La logique existante des paiements (1re validation, saisie manuelle)
n'est pas touchée — ceci est une couche par-dessus.

Réglages (Paramètres → Gestion locative → Validation bancaire) dans
``automation_settings`` clé ``immo.validation_bancaire`` :
``{"active": bool, "alerte_jours": int}`` — défaut inactif, 5 jours.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select

from app.models.immobilier import (
    Bail,
    BailStatus,
    FraisLocatif,
    Immeuble,
    Locataire,
    Logement,
    PaiementLoyer,
)
from app.models.qbo_loyers import (
    QboAliasPayeur,
    QboCompteLoyer,
    QboTransactionLoyer,
)

log = logging.getLogger(__name__)

#: Clé de config (automation_settings) — réglée dans Paramètres.
VALIDATION_KEY = "immo.validation_bancaire"
#: « ⚠ Payé — sans trace bancaire » après N jours (défaut, réglable).
DEFAUT_ALERTE_JOURS = 5
#: Fenêtre glissante de la synchro (jours).
FENETRE_SYNC_JOURS = 90
#: Tolérance de comparaison des montants ($).
_TOL = 0.01

#: Nom de compte reconnu : « loyer à remettre » / « loyers a remettre »…
_MOTIF_COMPTE = re.compile(r"loyers?\s+a\s+remettre")


# ── Normalisation de texte ─────────────────────────────────────────────


def _norm(s: str) -> str:
    """minuscules, sans accents, ponctuation → espace, espaces aplatis."""
    s = "".join(
        c
        for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _norm_payeur(s: str) -> str:
    """Normalisation du texte PAYEUR : comme ``_norm`` mais sans les
    suites de chiffres (n° de référence/confirmation qui changent à
    chaque virement) — l'alias appris reste stable de mois en mois."""
    return " ".join(re.sub(r"\d+", " ", _norm(s)).split())


#: Abréviations de voirie courantes — dépliées pour la similarité
#: (« St-Hubert » côté QBO vs « Rue Saint-Hubert » côté Kratos).
_ABREVIATIONS = {
    "st": "saint",
    "ste": "sainte",
    "boul": "boulevard",
    "blvd": "boulevard",
    "av": "avenue",
    "ave": "avenue",
    "ch": "chemin",
}

#: Mots sans signal pour identifier un immeuble.
_MOTS_VIDES = {
    "rue", "avenue", "boulevard", "chemin", "place", "montreal",
    "quebec", "app", "apt", "loyer", "loyers", "remettre",
}


def _tokens_adresse(s: str) -> List[str]:
    out: List[str] = []
    for t in _norm(s).split():
        t = _ABREVIATIONS.get(t, t)
        if t and t not in _MOTS_VIDES:
            out.append(t)
    return out


# ── Config ─────────────────────────────────────────────────────────────


async def get_validation_config() -> Dict[str, Any]:
    """Config de la feature. FAIL-CLOSED : inactif par défaut — aucune
    pastille tant que Phil n'a pas activé la validation bancaire."""
    from app.services.automation_state import get_automation_config

    cfg = await get_automation_config(VALIDATION_KEY)
    try:
        jours = int(cfg.get("alerte_jours", DEFAUT_ALERTE_JOURS))
    except (TypeError, ValueError):
        jours = DEFAUT_ALERTE_JOURS
    if jours < 1:
        jours = DEFAUT_ALERTE_JOURS
    return {
        "active": bool(cfg.get("active", False)),
        "alerte_jours": jours,
    }


# ── Client QuickBooks (scope locatif, lecture seule) ───────────────────


async def qbo_locatif():
    """Connexion QBO du pôle locatif : scope « immobilier », sinon
    « entreprise » (même compagnie chez Phil — même repli que les frais
    de gestion). RuntimeError si aucune connexion."""
    from app.integrations.quickbooks import get_qbo

    qbo = get_qbo("immobilier")
    await qbo._load_refresh_from_db()  # noqa: SLF001 — même package
    if not qbo.ready:
        qbo = get_qbo("entreprise")
        await qbo._load_refresh_from_db()  # noqa: SLF001
    if not qbo.ready:
        raise RuntimeError(
            "Aucun QuickBooks connecté pour le locatif — Paramètres → "
            "Comptabilité → « QuickBooks — autres pôles »."
        )
    return qbo


# ── 1) Découverte des comptes + suggestion d'immeuble ──────────────────


def _suggerer_immeuble(
    nom_compte: str, immeubles: List[Immeuble]
) -> Tuple[Optional[int], float]:
    """Suggestion DÉTERMINISTE de l'immeuble pour un compte « Loyer à
    remettre - X » : numéro civique + similarité de nom/adresse.
    Retourne (immeuble_id | None, score 0..1)."""
    # Partie « X » après le motif (sinon le nom complet).
    cible_brute = _MOTIF_COMPTE.split(_norm(nom_compte), maxsplit=1)
    cible = (cible_brute[-1] if cible_brute else "").strip() or _norm(
        nom_compte
    )
    cible_tokens = _tokens_adresse(cible)
    cible_norm = " ".join(cible_tokens) or cible
    cible_nums = set(re.findall(r"\d+", cible))

    meilleur: Optional[int] = None
    meilleur_score = 0.0
    second_score = 0.0
    for imm in immeubles:
        source = f"{imm.name or ''} {imm.address or ''} {imm.city or ''}"
        src_tokens = _tokens_adresse(source)
        src_norm = " ".join(src_tokens)
        src_nums = set(re.findall(r"\d+", _norm(source)))

        score = 0.0
        # Numéro civique identique = signal fort.
        if cible_nums and cible_nums & src_nums:
            score += 0.6
        # Recouvrement de mots (rue…) OU ressemblance globale.
        mots_cible = [t for t in cible_tokens if not t.isdigit()]
        if mots_cible:
            commun = sum(1 for t in mots_cible if t in src_tokens)
            part_mots = commun / len(mots_cible)
        else:
            part_mots = 0.0
        ratio = SequenceMatcher(None, cible_norm, src_norm).ratio()
        score += 0.4 * max(part_mots, ratio)

        if score > meilleur_score + 1e-9:
            second_score = meilleur_score
            meilleur_score = score
            meilleur = imm.id
        elif score > second_score:
            second_score = score
    # Deux immeubles quasi ex æquo (même n° civique, noms voisins) →
    # AUCUNE suggestion : l'ambiguïté revient à l'humain (Paramètres),
    # jamais de pronostic (même règle que le rapprochement).
    if (
        meilleur is not None
        and meilleur_score >= 0.5
        and (second_score < 0.5 or meilleur_score - second_score >= 0.05)
    ):
        return meilleur, round(meilleur_score, 3)
    return None, round(meilleur_score, 3)


async def _immeubles_mappables(db) -> List[Immeuble]:
    """Immeubles proposables au mapping : actifs, PAS en gestion externe
    (la perception y est déléguée — feature exclue)."""
    return list(
        (
            await db.execute(
                select(Immeuble).where(
                    Immeuble.is_active.is_(True),
                    Immeuble.gestion_externe.isnot(True),
                )
            )
        ).scalars().all()
    )


async def decouvrir_comptes(db, qbo=None) -> List[QboCompteLoyer]:
    """Interroge le plan comptable QBO (lecture seule), stocke les
    comptes dont le nom matche « loyer à remettre » et pose une
    SUGGESTION d'immeuble sur ceux pas encore confirmés. Idempotent
    (upsert par qbo_account_id). Ne commit pas."""
    if qbo is None:
        qbo = await qbo_locatif()
    rows = await qbo.query(
        "SELECT Id, Name, FullyQualifiedName FROM Account "
        "WHERE Active = true MAXRESULTS 1000"
    )
    immeubles = await _immeubles_mappables(db)

    existants = {
        c.qbo_account_id: c
        for c in (
            await db.execute(select(QboCompteLoyer))
        ).scalars().all()
    }
    out: List[QboCompteLoyer] = []
    for r in rows:
        nom = str(r.get("Name") or r.get("FullyQualifiedName") or "")
        if not _MOTIF_COMPTE.search(_norm(nom)):
            continue
        acc_id = str(r.get("Id") or "")
        if not acc_id:
            continue
        compte = existants.get(acc_id)
        if compte is None:
            compte = QboCompteLoyer(
                qbo_account_id=acc_id,
                qbo_account_name=nom,
                created_at=datetime.now(timezone.utc),
            )
            db.add(compte)
            existants[acc_id] = compte
        else:
            compte.qbo_account_name = nom
        # Suggestion seulement tant qu'aucun humain n'a confirmé.
        if compte.immeuble_id is None:
            sugg, score = _suggerer_immeuble(nom, immeubles)
            compte.suggestion_immeuble_id = sugg
            compte.suggestion_score = score
        out.append(compte)
    await db.flush()
    return out


# ── 2) Synchro des transactions publiées (GeneralLedger) ───────────────


def _parse_montant(raw: Any) -> float:
    s = str(raw or "0").replace(",", "").replace("$", "").strip()
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _colonnes_gl(report: Dict[str, Any]) -> Dict[str, int]:
    """Index des colonnes du rapport GeneralLedger par ColType (repli
    sur le titre) → {"tx_date": 0, "txn_type": 1, …}."""
    cols = (report.get("Columns") or {}).get("Column") or []
    idx: Dict[str, int] = {}
    for i, c in enumerate(cols):
        ctype = str(c.get("ColType") or "").strip().lower()
        titre = _norm(str(c.get("ColTitle") or ""))
        if ctype:
            idx.setdefault(ctype, i)
        if "date" in titre:
            idx.setdefault("tx_date", i)
        if "type" in titre:
            idx.setdefault("txn_type", i)
        if titre in ("nom", "name"):
            idx.setdefault("name", i)
        if "memo" in titre or "description" in titre:
            idx.setdefault("memo", i)
        if "montant" in titre or "amount" in titre:
            idx.setdefault("subt_nat_amount", i)
        if "no" == titre or "num" in titre:
            idx.setdefault("doc_num", i)
    return idx


def _lignes_gl(node: Any, out: List[List[Dict[str, Any]]]) -> None:
    """Collecte récursivement les lignes de détail (type=Data) d'un
    rapport GL — chaque ligne = la liste de ses ColData."""
    if isinstance(node, list):
        for r in node:
            _lignes_gl(r, out)
        return
    if not isinstance(node, dict):
        return
    cols = node.get("ColData")
    if isinstance(cols, list) and cols and node.get("type") == "Data":
        out.append(cols)
    sous = (node.get("Rows") or {}).get("Row")
    if sous:
        _lignes_gl(sous, out)


def parse_general_ledger(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rapport GeneralLedger (filtré sur UN compte) → écritures agrégées
    par (type, id QBO) : [{"txn_type", "txn_id", "date", "montant",
    "description", "doc_num"}]. Les montants ≤ 0 (remises, contre-
    passations) sont ignorés — on ne suit que les encaissements."""
    idx = _colonnes_gl(report)
    lignes: List[List[Dict[str, Any]]] = []
    _lignes_gl((report.get("Rows") or {}).get("Row") or [], lignes)

    def _val(cols: List[Dict[str, Any]], cle: str) -> Dict[str, Any]:
        i = idx.get(cle)
        if i is None or i >= len(cols):
            return {}
        return cols[i] or {}

    agreges: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for cols in lignes:
        type_cell = _val(cols, "txn_type")
        txn_type = str(type_cell.get("value") or "").strip()
        txn_id = str(type_cell.get("id") or "").strip()
        date_raw = str(_val(cols, "tx_date").get("value") or "")[:10]
        montant = _parse_montant(_val(cols, "subt_nat_amount").get("value"))
        if not txn_type or not txn_id or not date_raw:
            continue
        try:
            d = date.fromisoformat(date_raw)
        except ValueError:
            continue
        nom = str(_val(cols, "name").get("value") or "").strip()
        memo = str(_val(cols, "memo").get("value") or "").strip()
        desc = " — ".join(p for p in (nom, memo) if p) or None
        doc = str(_val(cols, "doc_num").get("value") or "").strip() or None
        cle = (txn_type, txn_id)
        if cle in agreges:
            # Même écriture, plusieurs lignes sur le même compte →
            # une seule transaction, montants sommés.
            agreges[cle]["montant"] = round(
                agreges[cle]["montant"] + montant, 2
            )
        else:
            agreges[cle] = {
                "txn_type": txn_type,
                "txn_id": txn_id,
                "date": d,
                "montant": round(montant, 2),
                "description": desc,
                "doc_num": doc,
            }
    return [e for e in agreges.values() if e["montant"] > _TOL]


async def synchroniser_transactions(
    db, qbo=None, *, jours: int = FENETRE_SYNC_JOURS
) -> Dict[str, int]:
    """Importe (lecture seule) les écritures publiées des comptes MAPPÉS
    sur la fenêtre glissante, IDEMPOTENT par (type, id, compte), puis
    relance le rapprochement déterministe. Ne commit pas."""
    comptes = list(
        (
            await db.execute(
                select(QboCompteLoyer).where(
                    QboCompteLoyer.actif.is_(True),
                    QboCompteLoyer.immeuble_id.is_not(None),
                )
            )
        ).scalars().all()
    )
    stats = {"comptes": 0, "importees": 0, "mises_a_jour": 0}
    if not comptes:
        return stats
    if qbo is None:
        qbo = await qbo_locatif()

    aujourdhui = datetime.now(timezone.utc).date()
    debut = (aujourdhui - timedelta(days=jours)).isoformat()
    fin = aujourdhui.isoformat()

    for compte in comptes:
        try:
            report = await qbo.report(
                "GeneralLedger",
                start_date=debut,
                end_date=fin,
                account=str(compte.qbo_account_id),
                columns="tx_date,txn_type,doc_num,name,memo,subt_nat_amount",
            )
        except Exception as exc:  # noqa: BLE001 — un compte ne bloque pas les autres
            log.warning(
                "GeneralLedger compte %s (%s) : %s",
                compte.qbo_account_id, compte.qbo_account_name, exc,
            )
            continue
        stats["comptes"] += 1
        entrees = parse_general_ledger(report)

        existantes = {
            (t.qbo_txn_type, t.qbo_txn_id): t
            for t in (
                await db.execute(
                    select(QboTransactionLoyer).where(
                        QboTransactionLoyer.compte_id == compte.id
                    )
                )
            ).scalars().all()
        }
        for e in entrees:
            txn = existantes.get((e["txn_type"], e["txn_id"]))
            if txn is None:
                db.add(
                    QboTransactionLoyer(
                        qbo_txn_type=e["txn_type"],
                        qbo_txn_id=e["txn_id"],
                        qbo_account_id=compte.qbo_account_id,
                        compte_id=compte.id,
                        immeuble_id=compte.immeuble_id,
                        date_txn=e["date"],
                        montant=e["montant"],
                        description=e["description"],
                        doc_num=e["doc_num"],
                        statut="non_rapproche",
                    )
                )
                stats["importees"] += 1
            else:
                # Écriture modifiée dans QBO → refléter ; le
                # rapprochement (auto) est rejoué plus bas.
                change = (
                    float(txn.montant or 0) != e["montant"]
                    or txn.date_txn != e["date"]
                    or (txn.description or None) != e["description"]
                )
                if change:
                    txn.date_txn = e["date"]
                    txn.montant = e["montant"]
                    txn.description = e["description"]
                    txn.doc_num = e["doc_num"]
                    stats["mises_a_jour"] += 1
                # L'immeuble du compte a pu être re-mappé.
                if txn.immeuble_id != compte.immeuble_id:
                    txn.immeuble_id = compte.immeuble_id
        compte.derniere_synchro_le = datetime.now(timezone.utc)
        await db.flush()
        await rapprocher_compte(db, compte)
    await db.flush()
    return stats


# ── 3) Rapprochement DÉTERMINISTE (aucun LLM) ──────────────────────────


def _mois_prec(m: date) -> date:
    return date(m.year - (1 if m.month == 1 else 0),
                12 if m.month == 1 else m.month - 1, 1)


def _mois_suiv(m: date) -> date:
    return date(m.year + (1 if m.month == 12 else 0),
                1 if m.month == 12 else m.month + 1, 1)


def _bail_couvre(bail: Bail, m: date) -> bool:
    """Le bail couvre-t-il le 1er du mois ``m`` ? (mêmes règles que le
    suivi des loyers : bail au mois = courant sans égard à date_fin tant
    qu'il est actif ; terminé/résilié = borné à sa fin)."""
    if bail.status == BailStatus.PROPOSE.value:
        return False
    if bail.date_debut and bail.date_debut.replace(day=1) > m:
        return False
    if bail.date_fin and m > bail.date_fin.replace(day=1):
        if bail.au_mois and bail.status == BailStatus.ACTIF.value:
            return True
        return False
    return True


def _alias_correspond(desc: str, alias: str) -> bool:
    if not desc or not alias:
        return False
    return alias == desc or alias in desc or desc in alias


def _nom_correspond(desc: str, nom_locataire: str) -> bool:
    """Le texte payeur désigne-t-il ce locataire ? Nom complet en
    sous-chaîne, ou TOUS ses mots (≥ 3 lettres) présents."""
    nom = _norm_payeur(nom_locataire)
    if not desc or not nom:
        return False
    if nom in desc:
        return True
    mots = [t for t in nom.split() if len(t) >= 3]
    if not mots:
        return False
    desc_mots = set(desc.split())
    return all(t in desc_mots for t in mots)


def _match_deterministe(
    txn: QboTransactionLoyer,
    baux: List[Bail],
    locataires: Dict[int, Locataire],
    aliases: List[QboAliasPayeur],
    paye_map: Dict[Tuple[int, date], float],
    frais_map: Dict[Tuple[int, date], float],
) -> Tuple[str, Optional[int], Optional[date]]:
    """→ (statut, bail_id, mois_couvert). Règles (dans l'ordre) :

    1. CANDIDATS PLAUSIBLES par montant × date : pour chaque bail, pour
       le mois de la date (puis mois précédent, puis suivant — le
       débordement toléré), plausible si montant == loyer du mois, ==
       loyer + frais, ou == dû restant (> 0). Premier mois plausible
       retenu par bail (préférence : mois de la date).
    2. TEXTE PAYEUR : un alias confirmé restreint aux baux visés ;
       sinon le nom du locataire. La restriction ne s'applique que si
       elle laisse au moins un candidat.
    3. Un seul bail candidat → rapproché AUTO ; plusieurs → « ambigu »
       (pas de pronostic) ; aucun → « non rapproché »."""
    m0 = txn.date_txn.replace(day=1)
    mois_ordre = [m0, _mois_prec(m0), _mois_suiv(m0)]
    montant = float(txn.montant or 0)

    plausibles: List[Tuple[Bail, date]] = []
    for bail in baux:
        for m in mois_ordre:
            if not _bail_couvre(bail, m):
                continue
            loyer = float(bail.loyer_mensuel or 0)
            if loyer <= 0:
                continue
            frais = frais_map.get((bail.id, m), 0.0)
            paye = paye_map.get((bail.id, m), 0.0)
            du_mois = round(loyer + frais, 2)
            du_restant = round(du_mois - paye, 2)
            if (
                abs(montant - loyer) <= _TOL
                or abs(montant - du_mois) <= _TOL
                or (du_restant > _TOL and abs(montant - du_restant) <= _TOL)
            ):
                plausibles.append((bail, m))
                break  # préférence de mois : le premier plausible suffit

    desc = _norm_payeur(txn.description or "")
    if desc and plausibles:
        alias_baux = {
            a.bail_id
            for a in aliases
            if _alias_correspond(desc, a.texte_normalise)
        }
        if alias_baux:
            restreints = [(b, m) for b, m in plausibles if b.id in alias_baux]
            if restreints:
                plausibles = restreints
        else:
            nom_baux = {
                b.id
                for b in baux
                if b.locataire_id in locataires
                and _nom_correspond(
                    desc, locataires[b.locataire_id].full_name or ""
                )
            }
            if nom_baux:
                restreints = [
                    (b, m) for b, m in plausibles if b.id in nom_baux
                ]
                if restreints:
                    plausibles = restreints

    baux_distincts = {b.id for b, _m in plausibles}
    if len(baux_distincts) == 1:
        bail, m = plausibles[0]
        return "rapproche", bail.id, m
    if not baux_distincts:
        return "non_rapproche", None, None
    return "ambigu", None, None


async def _baux_de_l_immeuble(db, immeuble_id: int) -> List[Bail]:
    log_ids = [
        int(r[0])
        for r in (
            await db.execute(
                select(Logement.id).where(
                    Logement.immeuble_id == immeuble_id
                )
            )
        ).all()
    ]
    if not log_ids:
        return []
    return list(
        (
            await db.execute(
                select(Bail).where(
                    Bail.logement_id.in_(log_ids),
                    Bail.status.in_(
                        [
                            BailStatus.ACTIF.value,
                            BailStatus.RESILIE.value,
                            BailStatus.TERMINE.value,
                        ]
                    ),
                )
            )
        ).scalars().all()
    )


async def rapprocher_compte(db, compte: QboCompteLoyer) -> int:
    """Rejoue le rapprochement déterministe de TOUTES les transactions
    non confirmées manuellement du compte. Les confirmations humaines
    (``rapproche_par='manuel'``) ne sont JAMAIS écrasées. Retourne le
    nombre de transactions rapprochées auto. Ne commit pas."""
    if compte.immeuble_id is None:
        return 0
    txns = list(
        (
            await db.execute(
                select(QboTransactionLoyer).where(
                    QboTransactionLoyer.compte_id == compte.id,
                    func.coalesce(
                        QboTransactionLoyer.rapproche_par, "auto"
                    )
                    != "manuel",
                )
            )
        ).scalars().all()
    )
    if not txns:
        return 0
    baux = await _baux_de_l_immeuble(db, compte.immeuble_id)
    bail_ids = [b.id for b in baux]
    locataires: Dict[int, Locataire] = {}
    aliases: List[QboAliasPayeur] = []
    paye_map: Dict[Tuple[int, date], float] = {}
    frais_map: Dict[Tuple[int, date], float] = {}
    if bail_ids:
        for loc in (
            await db.execute(
                select(Locataire).where(
                    Locataire.id.in_(
                        [b.locataire_id for b in baux if b.locataire_id]
                    )
                )
            )
        ).scalars().all():
            locataires[loc.id] = loc
        aliases = list(
            (
                await db.execute(
                    select(QboAliasPayeur).where(
                        QboAliasPayeur.bail_id.in_(bail_ids)
                    )
                )
            ).scalars().all()
        )
        for bid, m, total in (
            await db.execute(
                select(
                    PaiementLoyer.bail_id,
                    PaiementLoyer.mois_couvert,
                    func.sum(PaiementLoyer.montant),
                )
                .where(PaiementLoyer.bail_id.in_(bail_ids))
                .group_by(
                    PaiementLoyer.bail_id, PaiementLoyer.mois_couvert
                )
            )
        ).all():
            paye_map[(bid, m)] = float(total or 0)
        for bid, m, total in (
            await db.execute(
                select(
                    FraisLocatif.bail_id,
                    FraisLocatif.mois_couvert,
                    func.sum(FraisLocatif.montant),
                )
                .where(FraisLocatif.bail_id.in_(bail_ids))
                .group_by(FraisLocatif.bail_id, FraisLocatif.mois_couvert)
            )
        ).all():
            frais_map[(bid, m)] = float(total or 0)

    n_auto = 0
    for txn in txns:
        statut, bail_id, mois = _match_deterministe(
            txn, baux, locataires, aliases, paye_map, frais_map
        )
        txn.statut = statut
        txn.bail_id = bail_id
        txn.mois_couvert = mois
        txn.rapproche_par = "auto" if statut == "rapproche" else None
        if statut == "rapproche":
            n_auto += 1
    await db.flush()
    return n_auto


# ── 4) Confirmation humaine d'un rapprochement + alias appris ──────────


async def confirmer_transaction(
    db,
    txn: QboTransactionLoyer,
    bail_id: int,
    mois_couvert: Optional[date] = None,
) -> QboTransactionLoyer:
    """Confirme le bail d'une transaction ambiguë/non rapprochée ET
    apprend l'alias payeur (texte normalisé → bail) pour que la même
    provenance se rapproche seule le mois suivant. Ne commit pas."""
    txn.statut = "rapproche"
    txn.bail_id = bail_id
    txn.mois_couvert = (
        mois_couvert.replace(day=1)
        if mois_couvert
        else txn.date_txn.replace(day=1)
    )
    txn.rapproche_par = "manuel"

    alias = _norm_payeur(txn.description or "")[:255]
    if alias:
        existe = (
            await db.execute(
                select(QboAliasPayeur).where(
                    QboAliasPayeur.texte_normalise == alias,
                    QboAliasPayeur.bail_id == bail_id,
                )
            )
        ).scalar_one_or_none()
        if existe is None:
            db.add(
                QboAliasPayeur(
                    texte_normalise=alias,
                    bail_id=bail_id,
                    created_at=datetime.now(timezone.utc),
                )
            )
    await db.flush()
    return txn


# ── 5) État pour l'UI (pastilles + encart) ─────────────────────────────


async def etat_validation(db, mois: date) -> Dict[str, Any]:
    """Tout ce que le pôle locatif affiche pour un mois donné :

    - ``validations`` (par bail du mois) : ``valide`` (✓✓ un paiement
      marqué a sa transaction rapprochée — tooltip date/montant QBO) ou
      ``sans_trace`` (⚠ marqué payé depuis > N jours sans trace) ;
    - ``encaisses_non_marques`` : transactions rapprochées à un bail
      dont le mois n'est PAS marqué payé dans Kratos ;
    - ``a_traiter`` : ambiguës / non rapprochées, avec les baux
      candidats de l'immeuble (le choix confirme ET apprend l'alias).

    Feature inactive → ``{"active": False}`` et RIEN d'autre (zéro
    bruit). Les immeubles non mappés ne sortent jamais."""
    cfg = await get_validation_config()
    vide: Dict[str, Any] = {
        "active": False,
        "alerte_jours": cfg["alerte_jours"],
        "validations": [],
        "encaisses_non_marques": [],
        "a_traiter": [],
    }
    if not cfg["active"]:
        return vide

    comptes = list(
        (
            await db.execute(
                select(QboCompteLoyer).where(
                    QboCompteLoyer.actif.is_(True),
                    QboCompteLoyer.immeuble_id.is_not(None),
                )
            )
        ).scalars().all()
    )
    if not comptes:
        vide["active"] = True
        return vide

    # Immeubles couverts : mappés, actifs, PAS en gestion externe.
    imm_ids = {c.immeuble_id for c in comptes if c.immeuble_id}
    immeubles = {
        i.id: i
        for i in (
            await db.execute(
                select(Immeuble).where(
                    Immeuble.id.in_(list(imm_ids)),
                    Immeuble.is_active.is_(True),
                    Immeuble.gestion_externe.isnot(True),
                )
            )
        ).scalars().all()
    }
    if not immeubles:
        vide["active"] = True
        return vide

    month_start = mois.replace(day=1)
    aujourdhui = datetime.now(timezone.utc).date()

    # Baux des immeubles couverts (+ locataires / logements pour l'UI).
    logements = {
        l.id: l
        for l in (
            await db.execute(
                select(Logement).where(
                    Logement.immeuble_id.in_(list(immeubles.keys()))
                )
            )
        ).scalars().all()
    }
    baux = list(
        (
            await db.execute(
                select(Bail).where(
                    Bail.logement_id.in_(list(logements.keys())),
                    Bail.status.in_(
                        [
                            BailStatus.ACTIF.value,
                            BailStatus.RESILIE.value,
                            BailStatus.TERMINE.value,
                        ]
                    ),
                )
            )
        ).scalars().all()
    ) if logements else []
    baux_by_id = {b.id: b for b in baux}
    locataires = {
        loc.id: loc
        for loc in (
            await db.execute(
                select(Locataire).where(
                    Locataire.id.in_(
                        [b.locataire_id for b in baux if b.locataire_id]
                    )
                )
            )
        ).scalars().all()
    } if baux else {}

    def _imm_du_bail(b: Bail) -> Optional[Immeuble]:
        lg = logements.get(b.logement_id)
        return immeubles.get(lg.immeuble_id) if lg else None

    def _infos_bail(bid: Optional[int]) -> Dict[str, Any]:
        b = baux_by_id.get(bid or 0)
        if b is None:
            return {"locataire_name": None, "logement_numero": None}
        loc = locataires.get(b.locataire_id)
        lg = logements.get(b.logement_id)
        return {
            "locataire_name": loc.full_name if loc else None,
            "logement_numero": lg.numero if lg else None,
        }

    bail_ids = list(baux_by_id.keys())

    # Paiements marqués (1re validation) du mois affiché.
    paiements_mois: Dict[int, List[PaiementLoyer]] = {}
    if bail_ids:
        for p in (
            await db.execute(
                select(PaiementLoyer).where(
                    PaiementLoyer.bail_id.in_(bail_ids),
                    PaiementLoyer.mois_couvert == month_start,
                )
            )
        ).scalars().all():
            paiements_mois.setdefault(p.bail_id, []).append(p)

    # Mois marqués payés (tous mois confondus) — pour l'encart.
    mois_marques: set = set()
    if bail_ids:
        for bid, m in (
            await db.execute(
                select(
                    PaiementLoyer.bail_id, PaiementLoyer.mois_couvert
                ).where(PaiementLoyer.bail_id.in_(bail_ids))
            )
        ).all():
            mois_marques.add((bid, m))

    # Transactions de la fenêtre (bornée large : synchro + 30 j).
    plancher = aujourdhui - timedelta(days=FENETRE_SYNC_JOURS + 30)
    txns = list(
        (
            await db.execute(
                select(QboTransactionLoyer).where(
                    QboTransactionLoyer.immeuble_id.in_(
                        list(immeubles.keys())
                    ),
                    QboTransactionLoyer.date_txn >= plancher,
                )
            )
        ).scalars().all()
    )

    # ✓✓ / ⚠ par bail pour le mois affiché.
    rapprochees_mois: Dict[int, List[QboTransactionLoyer]] = {}
    for t in txns:
        if (
            t.statut == "rapproche"
            and t.bail_id
            and t.mois_couvert == month_start
        ):
            rapprochees_mois.setdefault(t.bail_id, []).append(t)

    validations: List[Dict[str, Any]] = []
    for b in baux:
        if _imm_du_bail(b) is None:
            continue
        ps = [p for p in paiements_mois.get(b.id, []) if p.paye_le]
        if not ps:
            continue  # pas marqué payé → la 2e validation n'a rien à dire
        ts = rapprochees_mois.get(b.id, [])
        if ts:
            validations.append(
                {
                    "bail_id": b.id,
                    "statut": "valide",
                    "date_txn": max(t.date_txn for t in ts).isoformat(),
                    "montant": round(
                        sum(float(t.montant or 0) for t in ts), 2
                    ),
                }
            )
        else:
            paye_le = max(p.paye_le for p in ps)
            if (aujourdhui - paye_le).days > cfg["alerte_jours"]:
                validations.append(
                    {
                        "bail_id": b.id,
                        "statut": "sans_trace",
                        "paye_le": paye_le.isoformat(),
                    }
                )

    # Encart 1 : encaissés (banque) non marqués (Kratos).
    encaisses: List[Dict[str, Any]] = []
    for t in txns:
        if t.statut != "rapproche" or not t.bail_id or not t.mois_couvert:
            continue
        if (t.bail_id, t.mois_couvert) in mois_marques:
            continue
        imm = immeubles.get(t.immeuble_id or 0)
        encaisses.append(
            {
                "txn_id": t.id,
                "immeuble_id": t.immeuble_id,
                "immeuble_name": imm.name if imm else "",
                "bail_id": t.bail_id,
                **_infos_bail(t.bail_id),
                "mois_couvert": t.mois_couvert.isoformat(),
                "date_txn": t.date_txn.isoformat(),
                "montant": float(t.montant or 0),
                "description": t.description,
            }
        )
    encaisses.sort(key=lambda x: (x["immeuble_name"], x["date_txn"]))

    # Encart 2 : ambiguës / non rapprochées, avec les baux candidats.
    candidats_par_imm: Dict[int, List[Dict[str, Any]]] = {}
    for b in baux:
        imm = _imm_du_bail(b)
        if imm is None or b.status != BailStatus.ACTIF.value:
            continue
        infos = _infos_bail(b.id)
        candidats_par_imm.setdefault(imm.id, []).append(
            {
                "bail_id": b.id,
                "locataire_name": infos["locataire_name"],
                "logement_numero": infos["logement_numero"],
                "loyer_mensuel": float(b.loyer_mensuel or 0),
            }
        )
    a_traiter: List[Dict[str, Any]] = []
    for t in txns:
        if t.statut not in ("ambigu", "non_rapproche"):
            continue
        imm = immeubles.get(t.immeuble_id or 0)
        if imm is None:
            continue
        a_traiter.append(
            {
                "txn_id": t.id,
                "immeuble_id": t.immeuble_id,
                "immeuble_name": imm.name,
                "statut": t.statut,
                "date_txn": t.date_txn.isoformat(),
                "montant": float(t.montant or 0),
                "description": t.description,
                "candidats": sorted(
                    candidats_par_imm.get(imm.id, []),
                    key=lambda c: (
                        c["logement_numero"] or "",
                        c["locataire_name"] or "",
                    ),
                ),
            }
        )
    a_traiter.sort(key=lambda x: (x["immeuble_name"], x["date_txn"]))

    return {
        "active": True,
        "alerte_jours": cfg["alerte_jours"],
        "validations": validations,
        "encaisses_non_marques": encaisses,
        "a_traiter": a_traiter,
    }
