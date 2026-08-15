"""Validation bancaire des loyers — QuickBooks en LECTURE SEULE.

2e validation des loyers (décision Phil + partenaires 2026-08-14), SANS
IA : l'adjointe publie les encaissements bancaires dans QuickBooks en
les catégorisant au compte « Loyer à remettre - {immeuble} » (un compte
du plan comptable par immeuble). Ce service :

1. DÉCOUVRE ces comptes (nom qui matche « loyer à remettre », insensible
   casse/accents) et SUGGÈRE le ou LES immeubles correspondants par
   similarité de nom/adresse (« 9085 Millen & 710 Legendre » suggère les
   deux ; un nom générique type « fiducie » suggère la case « tous les
   immeubles ») — la confirmation reste humaine (Paramètres). Un compte
   couvre N immeubles (``qbo_compte_immeubles``) ou tous
   (``tous_les_immeubles``) ;
2. SYNCHRONISE les écritures publiées qui touchent les comptes mappés
   via le rapport GeneralLedger (fenêtre glissante, idempotent par
   (type, id QBO, compte)) — le rapport couvre TOUT ce qui est publié
   (Deposits, écritures de journal, reçus de vente…), contrairement aux
   requêtes d'entités qui obligeraient à énumérer chaque type. Chaque
   ligne est classée par son TYPE d'écriture — pas par le signe du
   montant (sur un compte de PASSIF, un dépôt est un crédit et le signe
   dépend de la représentation du GeneralLedger) : Dépôt / Paiement /
   Reçu de vente = ENTRÉE à rapprocher (montant en valeur absolue) ;
   Dépense / Chèque / Virement / Facture fournisseur = SORTIE, conservée
   pour info (statut « ignoree ») mais jamais comptée comme un loyer.
   La synchro retourne un RAPPORT détaillé par compte (lues / importées /
   mises à jour / ignorées, avec la raison) ;
3. RAPPROCHE chaque entrée d'un bail/mois de façon DÉTERMINISTE
   (montant == loyer du mois ou dû restant frais inclus — y compris la
   somme de PLUSIEURS mois échus consécutifs impayés (locataire qui
   règle 2 mois d'un coup) —, proximité de date, texte payeur extrait du
   mémo Interac vs nom du locataire / alias confirmés). Un seul candidat
   plausible → rapproché auto ; plusieurs → « ambigu » (aucun
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
    QboCompteImmeuble,
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

#: Nom de compte générique (fiducie qui reçoit les virements de TOUS les
#: locataires) → on suggère la case « tous les immeubles internes ».
_MOTIF_TOUS = re.compile(r"\b(fiducie|fonds|trust)\b")

# ── Classification par TYPE d'écriture (jamais par signe) ──────────────
# Libellés NORMALISÉS (via ``_norm``) — le GeneralLedger sort les types
# en anglais (API brute) ou en français (compagnie francophone).

#: ENTRÉE d'argent = dépôt de loyer, candidate au rapprochement.
_TYPES_ENTREE = {
    "deposit", "depot",
    "payment", "paiement", "receive payment", "paiement recu",
    "sales receipt", "salesreceipt", "recu de vente",
}
#: SORTIE d'argent = remise aux immeubles / dépense — conservée pour
#: info (statut « ignoree »), jamais comptée comme un loyer.
_TYPES_SORTIE = {
    "expense", "depense",
    "cheque", "check", "chq",
    "transfer", "virement",
    "bill", "facture fournisseur",
    "bill payment", "bill payment check", "billpaymentcheck",
    "paiement de facture", "paiement de factures",
}
#: Écriture de journal : le type ne dit pas le sens — le SIGNE du
#: montant naturel tranche (compte de passif : crédit = positif =
#: encaissement ; débit = négatif = remise).
_TYPES_JOURNAL = {
    "journal entry", "journalentry", "journal",
    "ecriture de journal", "ecriture du journal",
}


def classifier_type(txn_type: str, montant: float) -> Tuple[str, Optional[str]]:
    """Classe une écriture par son TYPE → ("entree" | "sortie" |
    "ecartee", raison). Le montant (naturel, signé) ne sert qu'aux
    écritures de journal (créditeur = entrée) et au filtre montant nul."""
    if abs(montant) <= _TOL:
        return "ecartee", "montant_nul"
    t = _norm(txn_type)
    if t in _TYPES_ENTREE:
        return "entree", None
    if t in _TYPES_SORTIE:
        return "sortie", "sortie_argent"
    if t in _TYPES_JOURNAL:
        if montant > 0:
            return "entree", None
        return "sortie", "sortie_argent"
    return "ecartee", "type_non_reconnu"


#: Payeur entre barres obliques d'un mémo Interac réel :
#: « Virement Interac de /DRISSA KONE / » → « DRISSA KONE ».
_MOTIF_PAYEUR = re.compile(r"/\s*([^/]+?)\s*(?:/|$)")


def extraire_payeur(nom: str, memo: str) -> Optional[str]:
    """Nom du payeur d'une écriture : le segment entre « / » du mémo
    (convention des virements Interac), sinon la colonne Nom du GL.
    Retourne None quand rien d'exploitable."""
    for source in (memo or "", nom or ""):
        if "/" not in source:
            continue
        for brut in _MOTIF_PAYEUR.findall(source):
            payeur = brut.strip()
            # Au moins une lettre — écarte les fragments de date « 31/07 ».
            if payeur and re.search(r"[a-zA-Z]", _norm(payeur)):
                return payeur[:255]
    nom = (nom or "").strip()
    return nom[:255] if nom else None


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


def _suggerer_immeubles(
    nom_compte: str, immeubles: List[Immeuble]
) -> Tuple[List[int], bool, float]:
    """Suggestion DÉTERMINISTE des immeubles d'un compte « Loyer à
    remettre » : numéro civique + similarité de nom/adresse. Un nom qui
    cite deux adresses (« 9085 Millen & 710 Legendre ») suggère LES DEUX
    immeubles ; un nom générique (fiducie/fonds) ne suggère rien mais
    propose la case « tous les immeubles ».
    Retourne (immeuble_ids triés par score, suggestion_tous, meilleur
    score 0..1)."""
    ncompte = _norm(nom_compte)
    # Compte fourre-tout (fiducie des virements Interac de tous les
    # locataires) : aucune adresse à matcher → case « tous ».
    if _MOTIF_TOUS.search(ncompte):
        return [], True, 0.0

    # Partie « X » après le motif (sinon le nom complet).
    cible_brute = _MOTIF_COMPTE.split(ncompte, maxsplit=1)
    cible = (cible_brute[-1] if cible_brute else "").strip() or ncompte
    cible_tokens = _tokens_adresse(cible)
    cible_norm = " ".join(cible_tokens) or cible
    cible_nums = set(re.findall(r"\d+", cible))

    scores: List[Tuple[int, float, frozenset]] = []
    for imm in immeubles:
        source = f"{imm.name or ''} {imm.address or ''} {imm.city or ''}"
        src_tokens = _tokens_adresse(source)
        src_norm = " ".join(src_tokens)
        src_nums = set(re.findall(r"\d+", _norm(source)))

        score = 0.0
        # Numéro civique identique = signal fort. Chaque immeuble matche
        # SON numéro dans le nom du compte (9085 → Millen, 710 →
        # Legendre) — c'est ce qui permet la suggestion multiple.
        civiques = frozenset(cible_nums & src_nums)
        if civiques:
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
        scores.append((imm.id, score, civiques))

    retenus = [s for s in scores if s[1] >= 0.5]
    # Deux immeubles INDISCERNABLES (même évidence civique — ou aucune —
    # et scores quasi ex æquo) → on écarte les deux : l'ambiguïté revient
    # à l'humain, jamais de pronostic. Deux immeubles matchés par des
    # numéros DIFFÉRENTS du nom de compte restent tous deux suggérés.
    suggeres = [
        (iid, score)
        for iid, score, civ in retenus
        if not any(
            aid != iid and acov == civ and abs(ascore - score) < 0.05
            for aid, ascore, acov in retenus
        )
    ]
    suggeres.sort(key=lambda s: (-s[1], s[0]))
    meilleur_score = max((s[1] for s in scores), default=0.0)
    return [iid for iid, _s in suggeres], False, round(meilleur_score, 3)


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


async def liens_par_compte(db) -> Dict[int, List[int]]:
    """{compte_id: [immeuble_id, …]} — liens N-N confirmés."""
    out: Dict[int, List[int]] = {}
    for cid, iid in (
        await db.execute(
            select(
                QboCompteImmeuble.compte_id, QboCompteImmeuble.immeuble_id
            ).order_by(QboCompteImmeuble.immeuble_id)
        )
    ).all():
        out.setdefault(int(cid), []).append(int(iid))
    return out


async def immeubles_du_compte(
    db, compte: QboCompteLoyer,
    liens: Optional[Dict[int, List[int]]] = None,
) -> List[int]:
    """Immeubles COUVERTS par un compte : tous les internes mappables si
    ``tous_les_immeubles``, sinon les liens confirmés."""
    if compte.tous_les_immeubles:
        return [i.id for i in await _immeubles_mappables(db)]
    if liens is None:
        liens = await liens_par_compte(db)
    return liens.get(compte.id, [])


def _compte_mappe(
    compte: QboCompteLoyer, liens: Dict[int, List[int]]
) -> bool:
    """Un compte est synchronisable s'il couvre au moins un immeuble."""
    return bool(
        compte.tous_les_immeubles or liens.get(compte.id)
    )


def suggestion_a_la_volee(
    compte: QboCompteLoyer,
    liens: Dict[int, List[int]],
    immeubles: List[Immeuble],
) -> Optional[Dict[str, Any]]:
    """Suggestion recalculée À LA LECTURE quand rien n'est stocké — un
    compte découvert avant que la suggestion « tous » / multi-immeubles
    existe garde sinon une fiche muette et la case fiducie n'est jamais
    proposée (c'est exactement ce qui a laissé le compte Fiducie — et
    tous les Interac — hors synchro). Ne persiste rien.

    Retourne {"immeuble_ids", "tous", "score"} ou None si un humain a
    déjà confirmé le compte ou si une suggestion stockée existe."""
    if _compte_mappe(compte, liens):
        return None
    if compte.suggestion_tous or compte.suggestion_immeubles_json:
        return None
    ids, tous, score = _suggerer_immeubles(
        compte.qbo_account_name or "", immeubles
    )
    if not ids and not tous:
        return None
    return {"immeuble_ids": ids, "tous": tous, "score": score}


async def decouvrir_comptes(db, qbo=None) -> List[QboCompteLoyer]:
    """Interroge le plan comptable QBO (lecture seule), stocke les
    comptes dont le nom matche « loyer à remettre » et pose une
    SUGGESTION d'immeubles (liste — un nom peut citer deux adresses — ou
    case « tous » pour un compte fiducie) sur ceux pas encore confirmés.
    Idempotent (upsert par qbo_account_id). Ne commit pas."""
    import json

    if qbo is None:
        qbo = await qbo_locatif()
    rows = await qbo.query(
        "SELECT Id, Name, FullyQualifiedName FROM Account "
        "WHERE Active = true MAXRESULTS 1000"
    )
    immeubles = await _immeubles_mappables(db)
    liens = await liens_par_compte(db)

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
            await db.flush()  # id nécessaire pour _compte_mappe
            existants[acc_id] = compte
        else:
            compte.qbo_account_name = nom
        # Suggestion seulement tant qu'aucun humain n'a confirmé.
        if not _compte_mappe(compte, liens):
            sugg_ids, sugg_tous, score = _suggerer_immeubles(
                nom, immeubles
            )
            compte.suggestion_immeubles_json = (
                json.dumps(sugg_ids) if sugg_ids else None
            )
            compte.suggestion_tous = sugg_tous
            # Legacy : meilleure suggestion unique (compat).
            compte.suggestion_immeuble_id = (
                sugg_ids[0] if sugg_ids else None
            )
            compte.suggestion_score = score
        out.append(compte)
    await db.flush()
    return out


# ── 2) Synchro des transactions publiées (GeneralLedger) ───────────────


def _parse_montant(raw: Any) -> float:
    """Montant d'une cellule de rapport — tolère les DEUX locales que
    QuickBooks sert selon la compagnie : « 1,350.00 » (anglo) et
    « 1 350,00 $ » (fr-CA : espace — souvent insécable — pour les
    milliers, VIRGULE décimale), plus les négatifs entre parenthèses.
    L'ancien parseur anglo-seulement rendait 0 sur le format fr-CA →
    116/116 lignes « montant nul » à la synchro du 2026-08-14."""
    s = str(raw or "").strip()
    if not s:
        return 0.0
    negatif = s.startswith("(") and s.endswith(")")
    if negatif:
        s = s[1:-1]
    s = s.replace("$", "")
    # Espace simple, insécable (U+00A0) et fine insécable (U+202F).
    for espace in (" ", " ", " "):
        s = s.replace(espace, "")
    if "," in s and "." in s:
        # Le séparateur le plus à droite est la décimale.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Virgule suivie de 1-2 chiffres en fin = décimale fr-CA ;
        # sinon séparateur de milliers anglo (« 1,350 »).
        if re.search(r",\d{1,2}$", s):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if negatif else v


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
        # Compagnie dont le GL sort en Débit / Crédit (aucune colonne
        # Montant) — on indexe les deux pour recomposer le montant.
        if titre == "debit":
            idx.setdefault("debit_amt", i)
        if titre == "credit":
            idx.setdefault("credit_amt", i)
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


def parse_general_ledger(
    report: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Rapport GeneralLedger (filtré sur UN compte) → écritures agrégées
    par (type, id QBO), CLASSÉES PAR TYPE (jamais par signe) :

    - retour[0] : écritures à persister — [{"txn_type", "txn_id",
      "date", "montant" (valeur absolue), "sens" ("entree"|"sortie"),
      "ignore_raison", "description", "payeur", "doc_num"}] ;
    - retour[1] : ventilation des lignes ÉCARTÉES (jamais persistées) —
      {"lues": total écritures, "montant_nul": n, "type_non_reconnu": n,
      "types_inconnus": [libellés]}.
    """
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
        cell_montant = _val(cols, "subt_nat_amount").get("value")
        montant = _parse_montant(cell_montant)
        if not str(cell_montant or "").strip():
            # Pas de colonne Montant (ou cellule vide) : GL servi en
            # Débit / Crédit. Montant NATUREL d'un compte de passif =
            # crédit (encaissement) − débit (remise).
            credit = _parse_montant(_val(cols, "credit_amt").get("value"))
            debit = _parse_montant(_val(cols, "debit_amt").get("value"))
            if credit or debit:
                montant = round(credit - debit, 2)
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
            # une seule transaction, montants (naturels) sommés.
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
                "payeur": extraire_payeur(nom, memo),
                "doc_num": doc,
            }

    entrees: List[Dict[str, Any]] = []
    ecartees: Dict[str, Any] = {
        "lues": len(agreges),
        #: Lignes de détail trouvées AVANT interprétation — si > 0 avec
        #: lues = 0, le format du rapport n'est pas celui attendu.
        "lignes_brutes": len(lignes),
        "montant_nul": 0,
        "type_non_reconnu": 0,
        "types_inconnus": [],
        #: Instrumentation pour le rapport : le format RÉEL reçu —
        #: c'est ce qui a permis de comprendre le « 116 montants nuls »
        #: (colonne Montant non reconnue) sans accès aux réponses QBO.
        "colonnes": [
            f"{c.get('ColTitle') or ''}|{c.get('ColType') or ''}"
            for c in (report.get("Columns") or {}).get("Column") or []
        ],
        "exemple": (
            [str(c.get("value") or "") for c in lignes[0]]
            if lignes else []
        ),
    }
    for e in agreges.values():
        sens, raison = classifier_type(e["txn_type"], e["montant"])
        if sens == "ecartee":
            ecartees[raison] += 1
            if (
                raison == "type_non_reconnu"
                and e["txn_type"] not in ecartees["types_inconnus"]
            ):
                ecartees["types_inconnus"].append(e["txn_type"])
            continue
        # Montant TOUJOURS en valeur absolue — le sens est porté par le
        # type, pas par le signe (représentation GL d'un compte de passif).
        e["montant"] = round(abs(e["montant"]), 2)
        e["sens"] = sens
        e["ignore_raison"] = raison
        entrees.append(e)
    return entrees, ecartees


async def synchroniser_transactions(
    db, qbo=None, *, jours: int = FENETRE_SYNC_JOURS
) -> Dict[str, Any]:
    """Importe (lecture seule) les écritures publiées des comptes MAPPÉS
    sur la fenêtre glissante, IDEMPOTENT par (type, id, compte), puis
    relance le rapprochement déterministe. Ne commit pas.

    Retourne un RAPPORT DÉTAILLÉ (« 0 importée » sans explication est
    inacceptable) : totaux + par compte lues / importées / mises à jour /
    ignorées, avec la ventilation des raisons (sortie d'argent, montant
    nul, déjà importée, type non reconnu + libellés inconnus) — et la
    liste des comptes SAUTÉS avec leur raison (désactivé / sans
    immeuble) : c'est souvent LÀ que dorment les transactions attendues
    (ex. la fiducie qui reçoit tous les Interac, jamais activée)."""
    liens = await liens_par_compte(db)
    tous_comptes = (
        await db.execute(
            select(QboCompteLoyer).order_by(QboCompteLoyer.qbo_account_name)
        )
    ).scalars().all()
    comptes: List[QboCompteLoyer] = []
    comptes_ignores: List[Dict[str, Any]] = []
    for c in tous_comptes:
        if not c.actif:
            comptes_ignores.append({
                "compte_id": c.id,
                "compte_nom": c.qbo_account_name,
                "raison": "désactivé — coche « Actif » dans Paramètres "
                          "pour lire ses transactions",
            })
        elif not _compte_mappe(c, liens):
            comptes_ignores.append({
                "compte_id": c.id,
                "compte_nom": c.qbo_account_name,
                "raison": "aucun immeuble relié (ni la case « tous les "
                          "immeubles »)",
            })
        else:
            comptes.append(c)
    stats: Dict[str, Any] = {
        "comptes": 0,
        "importees": 0,
        "mises_a_jour": 0,
        "ignorees": 0,
        "details": [],
        "comptes_ignores": comptes_ignores,
    }
    if not comptes:
        return stats
    if qbo is None:
        qbo = await qbo_locatif()

    aujourdhui = datetime.now(timezone.utc).date()
    debut = (aujourdhui - timedelta(days=jours)).isoformat()
    fin = aujourdhui.isoformat()

    for compte in comptes:
        detail: Dict[str, Any] = {
            "compte_id": compte.id,
            "compte_nom": compte.qbo_account_name,
            "lues": 0,
            "importees": 0,
            "mises_a_jour": 0,
            "ignorees": 0,
            "raisons": {
                "sortie_argent": 0,
                "montant_nul": 0,
                "deja_importee": 0,
                "type_non_reconnu": 0,
            },
            "types_non_reconnus": [],
            "erreur": None,
        }
        stats["details"].append(detail)
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
            detail["erreur"] = str(exc)[:300]
            continue
        stats["comptes"] += 1
        entrees, ecartees = parse_general_ledger(report)
        detail["lues"] = ecartees["lues"]
        detail["raisons"]["montant_nul"] = ecartees["montant_nul"]
        detail["raisons"]["type_non_reconnu"] = ecartees[
            "type_non_reconnu"
        ]
        detail["types_non_reconnus"] = ecartees["types_inconnus"]
        detail["ignorees"] += (
            ecartees["montant_nul"] + ecartees["type_non_reconnu"]
        )
        # QuickBooks a répondu mais rien n'a été interprété alors que le
        # rapport contient des lignes → format inattendu, à SIGNALER
        # plutôt que d'afficher un « 0 lue » silencieux.
        if ecartees["lues"] == 0:
            if ecartees["lignes_brutes"] > 0:
                detail["erreur"] = (
                    "Rapport reçu avec des lignes, mais aucune n'a pu "
                    "être interprétée (type/id/date manquants) — format "
                    "GeneralLedger inattendu, à signaler. Colonnes "
                    f"reçues : {', '.join(ecartees['colonnes'])} ; "
                    f"première ligne : {ecartees['exemple']}"
                )
            elif (report.get("Rows") or {}).get("Row"):
                detail["erreur"] = (
                    "Rapport reçu avec des sections mais aucune ligne de "
                    "détail — format GeneralLedger inattendu, à signaler."
                )
        elif ecartees["montant_nul"] == ecartees["lues"]:
            # 100 % des écritures à 0 $ = la colonne Montant du rapport
            # n'est pas reconnue (ou son format de nombre) — montrer le
            # format réel plutôt qu'un décompte muet.
            detail["erreur"] = (
                "Toutes les lignes lues ont un montant nul — la colonne "
                "Montant du rapport n'est probablement pas reconnue. "
                f"Colonnes reçues : {', '.join(ecartees['colonnes'])} ; "
                f"première ligne : {ecartees['exemple']}"
            )

        # Compte mono-immeuble : l'immeuble est connu d'avance ; multi /
        # « tous » : il sera dérivé du bail au rapprochement.
        imm_ids = await immeubles_du_compte(db, compte, liens)
        immeuble_defaut = imm_ids[0] if len(imm_ids) == 1 else None

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
            est_sortie = e["sens"] == "sortie"
            if est_sortie:
                detail["ignorees"] += 1
                detail["raisons"]["sortie_argent"] += 1
            txn = existantes.get((e["txn_type"], e["txn_id"]))
            if txn is None:
                db.add(
                    QboTransactionLoyer(
                        qbo_txn_type=e["txn_type"],
                        qbo_txn_id=e["txn_id"],
                        qbo_account_id=compte.qbo_account_id,
                        compte_id=compte.id,
                        immeuble_id=immeuble_defaut,
                        date_txn=e["date"],
                        montant=e["montant"],
                        sens=e["sens"],
                        description=e["description"],
                        payeur=e["payeur"],
                        doc_num=e["doc_num"],
                        # Sortie d'argent (virement de remise…) : gardée
                        # pour le fil bancaire, JAMAIS candidate au
                        # rapprochement — pas un loyer.
                        statut="ignoree" if est_sortie else "non_rapproche",
                        ignore_raison=e["ignore_raison"],
                    )
                )
                if not est_sortie:
                    stats["importees"] += 1
                    detail["importees"] += 1
            else:
                # Écriture modifiée dans QBO → refléter, et remettre le
                # rapprochement AUTO à zéro (il est rejoué plus bas avec
                # les données fraîches). Une confirmation MANUELLE n'est
                # jamais écrasée.
                change = (
                    float(txn.montant or 0) != e["montant"]
                    or txn.date_txn != e["date"]
                    or (txn.description or None) != e["description"]
                )
                if change:
                    txn.date_txn = e["date"]
                    txn.montant = e["montant"]
                    txn.description = e["description"]
                    txn.payeur = e["payeur"]
                    txn.doc_num = e["doc_num"]
                    if not est_sortie and txn.rapproche_par != "manuel":
                        txn.statut = "non_rapproche"
                        txn.bail_id = None
                        txn.mois_couvert = None
                        txn.mois_couvert_fin = None
                        txn.rapproche_par = None
                    if not est_sortie:
                        stats["mises_a_jour"] += 1
                        detail["mises_a_jour"] += 1
                elif not est_sortie:
                    detail["raisons"]["deja_importee"] += 1
                if txn.payeur is None and e["payeur"]:
                    txn.payeur = e["payeur"]
        compte.derniere_synchro_le = datetime.now(timezone.utc)
        await db.flush()
        await rapprocher_compte(db, compte, liens=liens)
    await db.flush()
    stats["ignorees"] = sum(d["ignorees"] for d in stats["details"])
    return stats


# ── 3) Rapprochement DÉTERMINISTE (aucun LLM) ──────────────────────────


def _mois_prec(m: date) -> date:
    return date(m.year - (1 if m.month == 1 else 0),
                12 if m.month == 1 else m.month - 1, 1)


def _mois_suiv(m: date) -> date:
    return date(m.year + (1 if m.month == 12 else 0),
                1 if m.month == 12 else m.month + 1, 1)


def mois_couverts_txn(txn: QboTransactionLoyer) -> List[date]:
    """Mois couverts par une transaction rapprochée : [mois_couvert] ou
    l'intervalle mois_couvert..mois_couvert_fin (paiement multi-mois)."""
    if not txn.mois_couvert:
        return []
    out = [txn.mois_couvert]
    fin = txn.mois_couvert_fin
    m = txn.mois_couvert
    while fin and m < fin and len(out) < 24:  # garde-fou
        m = _mois_suiv(m)
        out.append(m)
    return out


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


#: Fenêtre de rattrapage du rapprochement MULTI-MOIS (mois échus
#: consécutifs impayés réglés d'un coup).
_MULTI_MOIS_FENETRE = 12


def _match_multi_mois(
    bail: Bail,
    m0: date,
    montant: float,
    paye_map: Dict[Tuple[int, date], float],
    frais_map: Dict[Tuple[int, date], float],
) -> Optional[Tuple[date, date]]:
    """Paiement de rattrapage : le montant règle-t-il la somme des dus
    (loyers + frais, moins le déjà payé) de PLUSIEURS mois consécutifs
    impayés du bail ? → (premier mois, dernier mois) ou None.

    Déterministe : on balaie les mois du plus ancien (m0 - 12 mois) au
    mois suivant la date (même tolérance que le mois adjacent) ; le
    premier enchaînement de ≥ 2 mois impayés consécutifs dont le cumul
    tombe pile sur le montant gagne — la dette la plus ancienne
    d'abord."""
    loyer = float(bail.loyer_mensuel or 0)
    if loyer <= 0:
        return None

    def _du_restant(m: date) -> float:
        du = loyer + frais_map.get((bail.id, m), 0.0)
        return round(du - paye_map.get((bail.id, m), 0.0), 2)

    fenetre: List[date] = []
    m = m0
    for _ in range(_MULTI_MOIS_FENETRE):
        m = _mois_prec(m)
        fenetre.insert(0, m)
    fenetre.append(m0)
    fenetre.append(_mois_suiv(m0))

    for i, debut in enumerate(fenetre):
        if not _bail_couvre(bail, debut) or _du_restant(debut) <= _TOL:
            continue
        cumul = 0.0
        for m in fenetre[i:]:
            if not _bail_couvre(bail, m):
                break
            dr = _du_restant(m)
            if dr <= _TOL:
                break  # rupture de consécutivité (mois réglé)
            cumul = round(cumul + dr, 2)
            if abs(cumul - montant) <= _TOL and m > debut:
                return debut, m
            if cumul > montant + _TOL:
                break
        # Départ le plus ancien uniquement : si le cumul depuis la
        # première dette ne colle pas, on ne « saute » pas de mois
        # (jamais de pronostic sur quel retard est réglé).
        return None
    return None


def _match_deterministe(
    txn: QboTransactionLoyer,
    baux: List[Bail],
    locataires: Dict[int, Locataire],
    aliases: List[QboAliasPayeur],
    paye_map: Dict[Tuple[int, date], float],
    frais_map: Dict[Tuple[int, date], float],
) -> Tuple[str, Optional[int], Optional[date], Optional[date]]:
    """→ (statut, bail_id, mois_couvert, mois_couvert_fin). Règles :

    1. CANDIDATS PLAUSIBLES par montant × date : pour chaque bail, pour
       le mois de la date (puis mois précédent, puis suivant — le
       débordement toléré), plausible si montant == loyer du mois, ==
       loyer + frais, ou == dû restant (> 0). Premier mois plausible
       retenu par bail (préférence : mois de la date). À défaut, le
       montant peut régler PLUSIEURS mois échus consécutifs impayés
       d'un coup (cf. ``_match_multi_mois``) — le candidat couvre alors
       un intervalle de mois.
    2. TEXTE PAYEUR (extrait du mémo Interac quand disponible) : un
       alias confirmé restreint aux baux visés ; sinon le nom du
       locataire. La restriction ne s'applique que si elle laisse au
       moins un candidat.
    3. Un seul bail candidat → rapproché AUTO ; plusieurs → « ambigu »
       (pas de pronostic) ; aucun → « non rapproché »."""
    m0 = txn.date_txn.replace(day=1)
    mois_ordre = [m0, _mois_prec(m0), _mois_suiv(m0)]
    montant = float(txn.montant or 0)

    plausibles: List[Tuple[Bail, date, date]] = []
    for bail in baux:
        trouve = False
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
                plausibles.append((bail, m, m))
                trouve = True
                break  # préférence de mois : le premier plausible suffit
        if not trouve:
            multi = _match_multi_mois(bail, m0, montant, paye_map, frais_map)
            if multi is not None:
                plausibles.append((bail, multi[0], multi[1]))

    desc = _norm_payeur(txn.payeur or txn.description or "")
    if desc and plausibles:
        alias_baux = {
            a.bail_id
            for a in aliases
            if _alias_correspond(desc, a.texte_normalise)
        }
        if alias_baux:
            restreints = [
                p for p in plausibles if p[0].id in alias_baux
            ]
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
                    p for p in plausibles if p[0].id in nom_baux
                ]
                if restreints:
                    plausibles = restreints

    baux_distincts = {b.id for b, _d, _f in plausibles}
    if len(baux_distincts) == 1:
        bail, debut, fin = plausibles[0]
        return (
            "rapproche", bail.id, debut,
            fin if fin != debut else None,
        )
    if not baux_distincts:
        return "non_rapproche", None, None, None
    return "ambigu", None, None, None


async def _baux_des_immeubles(
    db, immeuble_ids: List[int]
) -> Tuple[List[Bail], Dict[int, int]]:
    """(baux des immeubles, {logement_id: immeuble_id}) — l'UNION des
    baux de tous les immeubles couverts par le compte."""
    if not immeuble_ids:
        return [], {}
    logement_imm = {
        int(lid): int(iid)
        for lid, iid in (
            await db.execute(
                select(Logement.id, Logement.immeuble_id).where(
                    Logement.immeuble_id.in_(immeuble_ids)
                )
            )
        ).all()
    }
    if not logement_imm:
        return [], {}
    baux = list(
        (
            await db.execute(
                select(Bail).where(
                    Bail.logement_id.in_(list(logement_imm.keys())),
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
    return baux, logement_imm


async def rapprocher_compte(
    db,
    compte: QboCompteLoyer,
    *,
    liens: Optional[Dict[int, List[int]]] = None,
    forcer: bool = False,
) -> int:
    """Rejoue le rapprochement déterministe des transactions du compte
    (candidats = UNION des baux des immeubles reliés — ou de tous les
    internes si ``tous_les_immeubles``). Les confirmations humaines
    (``rapproche_par='manuel'``) ne sont JAMAIS écrasées ; les sorties
    d'argent (statut « ignoree ») non plus — pas des loyers.

    Par défaut, un rapprochement AUTO déjà posé est STABLE (marquer les
    mois payés ensuite ne le défait pas) : seules les transactions non
    rapprochées / ambiguës sont rejouées — la synchro remet un statut à
    zéro quand l'écriture change dans QBO. ``forcer=True`` (re-mapping
    du compte) rejoue tout sauf le manuel. Retourne le nombre de
    transactions rapprochées auto. Ne commit pas."""
    immeuble_ids = await immeubles_du_compte(db, compte, liens)
    if not immeuble_ids:
        return 0
    conditions = [
        QboTransactionLoyer.compte_id == compte.id,
        QboTransactionLoyer.statut != "ignoree",
        func.coalesce(QboTransactionLoyer.rapproche_par, "auto")
        != "manuel",
    ]
    if not forcer:
        conditions.append(QboTransactionLoyer.statut != "rapproche")
    txns = list(
        (
            await db.execute(
                select(QboTransactionLoyer).where(*conditions)
            )
        ).scalars().all()
    )
    if not txns:
        return 0
    baux, logement_imm = await _baux_des_immeubles(db, immeuble_ids)
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

    baux_by_id = {b.id: b for b in baux}
    immeuble_defaut = immeuble_ids[0] if len(immeuble_ids) == 1 else None
    n_auto = 0
    for txn in txns:
        statut, bail_id, mois, mois_fin = _match_deterministe(
            txn, baux, locataires, aliases, paye_map, frais_map
        )
        txn.statut = statut
        txn.bail_id = bail_id
        txn.mois_couvert = mois
        txn.mois_couvert_fin = mois_fin
        txn.rapproche_par = "auto" if statut == "rapproche" else None
        # L'immeuble vient du BAIL une fois rapproché (indispensable sur
        # un compte multi-immeubles/fiducie) ; sinon celui du compte
        # quand il n'en couvre qu'un seul.
        if bail_id is not None:
            b = baux_by_id.get(bail_id)
            txn.immeuble_id = (
                logement_imm.get(b.logement_id) if b else immeuble_defaut
            )
        else:
            txn.immeuble_id = immeuble_defaut
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
    txn.mois_couvert_fin = None
    txn.rapproche_par = "manuel"

    # L'alias appris = le PAYEUR extrait du mémo Interac quand il existe
    # (stable de mois en mois), sinon la description complète.
    alias = _norm_payeur(txn.payeur or txn.description or "")[:255]
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

    liens = await liens_par_compte(db)
    comptes = [
        c
        for c in (
            await db.execute(
                select(QboCompteLoyer).where(
                    QboCompteLoyer.actif.is_(True)
                )
            )
        ).scalars().all()
        if _compte_mappe(c, liens)
    ]
    if not comptes:
        vide["active"] = True
        return vide

    # Immeubles couverts (UNION des liens de chaque compte — tous les
    # internes pour un compte fiducie) : actifs, PAS en gestion externe.
    comptes_by_id = {c.id: c for c in comptes}
    couverts_par_compte: Dict[int, List[int]] = {}
    imm_ids: set = set()
    for c in comptes:
        ids = await immeubles_du_compte(db, c, liens)
        couverts_par_compte[c.id] = ids
        imm_ids.update(ids)
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
    } if imm_ids else {}
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

    # Transactions de la fenêtre (bornée large : synchro + 30 j) — par
    # COMPTE (une txn d'un compte multi-immeubles/fiducie n'a pas
    # d'immeuble tant qu'elle n'est pas rapprochée). Les sorties
    # d'argent (statut « ignoree ») ne sortent jamais ici.
    plancher = aujourdhui - timedelta(days=FENETRE_SYNC_JOURS + 30)
    txns = list(
        (
            await db.execute(
                select(QboTransactionLoyer).where(
                    QboTransactionLoyer.compte_id.in_(
                        list(comptes_by_id.keys())
                    ),
                    QboTransactionLoyer.statut != "ignoree",
                    QboTransactionLoyer.date_txn >= plancher,
                )
            )
        ).scalars().all()
    )

    # ✓✓ / ⚠ par bail pour le mois affiché. Un paiement MULTI-MOIS
    # (rattrapage de 2 mois d'un coup) valide CHACUN des mois couverts.
    rapprochees_mois: Dict[int, List[QboTransactionLoyer]] = {}
    for t in txns:
        if (
            t.statut == "rapproche"
            and t.bail_id
            and month_start in mois_couverts_txn(t)
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

    # Encart 1 : encaissés (banque) non marqués (Kratos). Un paiement
    # multi-mois sort UNE ligne par mois couvert non marqué.
    encaisses: List[Dict[str, Any]] = []
    for t in txns:
        if t.statut != "rapproche" or not t.bail_id or not t.mois_couvert:
            continue
        imm = immeubles.get(t.immeuble_id or 0)
        for m in mois_couverts_txn(t):
            if (t.bail_id, m) in mois_marques:
                continue
            encaisses.append(
                {
                    "txn_id": t.id,
                    "immeuble_id": t.immeuble_id,
                    "immeuble_name": imm.name if imm else "",
                    "bail_id": t.bail_id,
                    **_infos_bail(t.bail_id),
                    "mois_couvert": m.isoformat(),
                    "date_txn": t.date_txn.isoformat(),
                    "montant": float(t.montant or 0),
                    "description": t.description,
                }
            )
    encaisses.sort(
        key=lambda x: (x["immeuble_name"], x["date_txn"], x["mois_couvert"])
    )

    # Encart 2 : ambiguës / non rapprochées, avec les baux candidats de
    # TOUS les immeubles couverts par le compte de la transaction (union
    # — un compte fiducie propose les baux de tous les internes).
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
        compte = comptes_by_id.get(t.compte_id)
        imm_compte = [
            i for i in couverts_par_compte.get(t.compte_id, [])
            if i in immeubles
        ]
        if not imm_compte:
            continue
        imm = immeubles.get(t.immeuble_id or 0)
        candidats = [
            c for iid in imm_compte for c in candidats_par_imm.get(iid, [])
        ]
        a_traiter.append(
            {
                "txn_id": t.id,
                "immeuble_id": t.immeuble_id,
                # Compte multi-immeubles : pas d'immeuble tant que rien
                # n'est rapproché — on affiche le nom du compte QBO.
                "immeuble_name": (
                    imm.name
                    if imm
                    else (compte.qbo_account_name if compte else "")
                ),
                "statut": t.statut,
                "date_txn": t.date_txn.isoformat(),
                "montant": float(t.montant or 0),
                "description": t.description,
                "payeur": t.payeur,
                "candidats": sorted(
                    candidats,
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


# ── 6) Fil bancaire (visualiseur — données déjà en base, zéro appel QBO) ─


async def lister_transactions(
    db,
    *,
    immeuble_id: Optional[int] = None,
    statut: Optional[str] = None,
) -> Dict[str, Any]:
    """Fil des transactions synchronisées (fenêtre 90 jours, tri date
    desc) pour le visualiseur « Voir le fil bancaire » : chaque ligne
    avec son rapprochement (bail/locataire/mois couverts + ✓✓ si les
    mois sont aussi marqués payés dans Kratos), les candidats pour les
    ambiguës/non rapprochées, et les sorties d'argent ignorées (mention
    informative). AUCUN appel QuickBooks — lecture de la base seulement.
    """
    liens = await liens_par_compte(db)
    comptes = {
        c.id: c
        for c in (
            await db.execute(select(QboCompteLoyer))
        ).scalars().all()
    }
    couverts_par_compte: Dict[int, List[int]] = {}
    for c in comptes.values():
        couverts_par_compte[c.id] = await immeubles_du_compte(
            db, c, liens
        )

    plancher = (
        datetime.now(timezone.utc).date()
        - timedelta(days=FENETRE_SYNC_JOURS)
    )
    txns = list(
        (
            await db.execute(
                select(QboTransactionLoyer)
                .where(QboTransactionLoyer.date_txn >= plancher)
                .order_by(
                    QboTransactionLoyer.date_txn.desc(),
                    QboTransactionLoyer.id.desc(),
                )
            )
        ).scalars().all()
    )
    # Filtres simples (volumes faibles — 90 jours).
    if statut:
        txns = [t for t in txns if t.statut == statut]
    if immeuble_id is not None:
        txns = [
            t
            for t in txns
            if t.immeuble_id == immeuble_id
            or (
                t.immeuble_id is None
                and immeuble_id in couverts_par_compte.get(t.compte_id, [])
            )
        ]

    # Référentiels pour l'affichage (immeubles couverts + baux visés).
    imm_ids = {i for ids in couverts_par_compte.values() for i in ids}
    imm_ids.update(t.immeuble_id for t in txns if t.immeuble_id)
    immeubles = {
        i.id: i
        for i in (
            await db.execute(
                select(Immeuble).where(Immeuble.id.in_(list(imm_ids)))
            )
        ).scalars().all()
    } if imm_ids else {}
    baux, logement_imm = await _baux_des_immeubles(
        db, [i for i in imm_ids if immeubles.get(i)]
    )
    bail_ids = {b.id for b in baux} | {
        t.bail_id for t in txns if t.bail_id
    }
    baux_manquants = [
        bid for bid in bail_ids if bid not in {b.id for b in baux}
    ]
    if baux_manquants:
        for b in (
            await db.execute(
                select(Bail).where(Bail.id.in_(baux_manquants))
            )
        ).scalars().all():
            baux.append(b)
    baux_by_id = {b.id: b for b in baux}
    logements = {
        l.id: l
        for l in (
            await db.execute(
                select(Logement).where(
                    Logement.id.in_(
                        [b.logement_id for b in baux]
                    )
                )
            )
        ).scalars().all()
    } if baux else {}
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

    # Mois marqués payés (1re validation) des baux visés → ✓✓.
    mois_marques: set = set()
    if bail_ids:
        for bid, m in (
            await db.execute(
                select(
                    PaiementLoyer.bail_id, PaiementLoyer.mois_couvert
                ).where(PaiementLoyer.bail_id.in_(list(bail_ids)))
            )
        ).all():
            mois_marques.add((bid, m))

    # Candidats (baux ACTIFS) par immeuble — pour le sélecteur des
    # ambiguës directement dans le fil.
    candidats_par_imm: Dict[int, List[Dict[str, Any]]] = {}
    for b in baux:
        lg = logements.get(b.logement_id)
        if lg is None or b.status != BailStatus.ACTIF.value:
            continue
        loc = locataires.get(b.locataire_id)
        candidats_par_imm.setdefault(lg.immeuble_id, []).append(
            {
                "bail_id": b.id,
                "locataire_name": loc.full_name if loc else None,
                "logement_numero": lg.numero if lg else None,
                "loyer_mensuel": float(b.loyer_mensuel or 0),
            }
        )

    out: List[Dict[str, Any]] = []
    for t in txns:
        compte = comptes.get(t.compte_id)
        imm = immeubles.get(t.immeuble_id or 0)
        bail = baux_by_id.get(t.bail_id or 0)
        loc = (
            locataires.get(bail.locataire_id)
            if bail and bail.locataire_id
            else None
        )
        lg = logements.get(bail.logement_id) if bail else None
        mois = mois_couverts_txn(t)
        candidats: List[Dict[str, Any]] = []
        if t.statut in ("ambigu", "non_rapproche"):
            candidats = sorted(
                (
                    c
                    for iid in couverts_par_compte.get(t.compte_id, [])
                    for c in candidats_par_imm.get(iid, [])
                ),
                key=lambda c: (
                    c["logement_numero"] or "",
                    c["locataire_name"] or "",
                ),
            )
        out.append(
            {
                "txn_id": t.id,
                "date_txn": t.date_txn.isoformat(),
                "montant": float(t.montant or 0),
                "sens": t.sens,
                "statut": t.statut,
                "ignore_raison": t.ignore_raison,
                "rapproche_par": t.rapproche_par,
                "payeur": t.payeur,
                "description": t.description,
                "doc_num": t.doc_num,
                "compte_id": t.compte_id,
                "compte_nom": (
                    compte.qbo_account_name if compte else ""
                ),
                "immeuble_id": t.immeuble_id,
                "immeuble_name": imm.name if imm else None,
                "bail_id": t.bail_id,
                "locataire_id": loc.id if loc else None,
                "locataire_name": loc.full_name if loc else None,
                "logement_numero": lg.numero if lg else None,
                "mois_couverts": [m.isoformat() for m in mois],
                # ✓✓ : rapprochée ET chaque mois couvert marqué payé.
                "valide": bool(
                    t.statut == "rapproche"
                    and t.bail_id
                    and mois
                    and all((t.bail_id, m) in mois_marques for m in mois)
                ),
                "candidats": candidats,
            }
        )

    return {
        "transactions": out,
        "immeubles": sorted(
            (
                {"id": i.id, "name": i.name}
                for i in immeubles.values()
            ),
            key=lambda x: x["name"] or "",
        ),
    }
