"""Offre d'investissement (.pptx) — générateur v3 (Phil, 2026-10-08).

Refonte complète après l'audit des deux pitch decks finaux de Phil
(1660 Saint-Clément, 2420 Pie-IX) : le résultat généré demandait « beaucoup
d'ajustement et de travail ». Le but : *quand je génère, je n'ai pas ou
presque rien à changer ensuite.*

Principes
---------
- Le gabarit ``horizon_v3.pptx`` est la copie du deck final le plus récent
  (2420 Pie-IX, 16 diapos) où les photos propres au deal sont remplacées
  par des pastilles neutres. Chaque forme, cellule et graphique propre au
  deal est REMPLI PAR SON NOM (plus de « rechercher / remplacer » de
  littéraux) : un oubli est détecté et remonté (``misses``) au lieu de
  laisser fuir un chiffre du gabarit.
- Les chiffres viennent de la fiche d'analyse et de ses résultats
  persistés (``analysis_results_json`` : scénarios d'achat et de
  refinancement, frais de démarrage, coût du projet) et du moteur de TRI
  investisseur (``lead_tri_calc.compute_tri``) pour les diapos 2, 11 et
  13 — mêmes intrants que l'onglet TRI de la fiche.
- Les textes qui ne se déduisent pas des chiffres (accroche, puces,
  leviers, jalons, rénovations, secteur…) sont PROPOSÉS par
  ``proposer_intrants`` et modifiables dans l'assistant avant génération.
- L'échéancier (diapo 6) est calculé : en-têtes de colonnes, cases
  colorées des activités, losanges / carrés / connecteurs placés d'après
  les dates des jalons, repère « AUJOURD'HUI ».

Structure du gabarit (indices de diapos 0-based) — cf. docstring de
``_remplir_*`` pour chaque diapo.
"""
from __future__ import annotations

import copy
import io
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "offre_investissement"
TEMPLATE_VERSION = "horizon_v3"
#: Version logique du service (journal d'audit).
SERVICE_VERSION = "v6"

#: Catalogue de rénovations proposées dans l'assistant (cochables).
RENOVATIONS_CATALOGUE: List[str] = [
    "Toit",
    "Fondation",
    "Brique",
    "Portes/fenêtres",
    "Balcons/escaliers",
    "Escalier de secours",
    "Sous-sol",
    "Drain entrée extérieur",
    "Chauffe-eau",
    "Panneau électrique",
    "Garages",
    "Rajout de murs",
    "Achat d'électros et matériel",
    "Finir appartement",
    "Rénovations intérieures générales",
    "Entretien extérieur général",
    "Détecteurs de fumée et monoxyde",
    "Vermines",
    "Conversion chauffage",
    "Insonorisation",
    "Plomberie majeure",
    "Électricité majeure",
    "Cuisine complète",
    "Salle de bain complète",
]

#: Emplacements de photos du gabarit : clé → (index de diapo, nom de la
#: forme, libellé). Sans photo fournie, la pastille neutre du gabarit
#: reste en place (visible, donc impossible à oublier).
PHOTO_SLOTS: List[Tuple[str, int, str, str]] = [
    ("cover", 0, "Picture 33", "Couverture (diapo 1)"),
    ("resume_1", 1, "Picture 13", "Résumé — photo du haut (diapo 2)"),
    ("resume_2", 1, "Picture 8", "Résumé — photo du milieu (diapo 2)"),
    ("resume_3", 1, "Picture 5", "Résumé — photo du bas (diapo 2)"),
    ("presentation", 2, "Picture 5", "Présentation du projet — photo ou plan (diapo 3)"),
    ("centris", 3, "Picture 76", "Capture Centris du comparable (diapo 4)"),
    ("avant", 4, "Picture 10", "Avant (diapo 5)"),
    ("apres", 4, "Picture 15", "Après (diapo 5)"),
    ("zipplex", 11, "Picture 3", "Capture Zipplex — moyenne du secteur (diapo 12)"),
]

_MOIS = [
    "", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet",
    "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]
_MOIS_COURT = [
    "", "Janv", "Fév", "Mars", "Avril", "Mai", "Juin", "Juil", "Août",
    "Sept", "Oct", "Nov", "Déc",
]

#: Jalons de l'échéancier : clé, libellé par défaut, phase, ligne du
#: Gantt (index de ligne de « Table 1 »), décalage en mois.
JALONS_DEFAUT: List[Tuple[str, str, int, str]] = [
    ("m1_1", "Lettre de financement", 2, "+2 mois après le début"),
    ("m1_2", "Passage au notaire", 3, "+3 mois"),
    ("m2_1", "Ententes avec les locataires", 4, "notaire + 3 mois"),
    ("m2_2", "Fin des travaux majeurs", 5, "notaire + 6 mois"),
    ("m2_3", "Fin des travaux appartements", 6, "notaire + 8 mois"),
    ("m2_4", "Locations et stabilisation", 7, "notaire + 9 mois"),
    ("m3_1", "Remboursement des partenaires", 8, "notaire + durée du projet"),
]

_PROGRAMMES = {
    "refi_schl": ("SCHL STANDARD", "SCHL STANDARD", "Standard"),
    "refi_aph_50": ("SCHL EFFICACITÉ 50 PTS", "SCHL APH 50 PTS", "50 pts efficacité énergétique"),
    "refi_aph_100": ("SCHL APH 100 PTS", "SCHL APH 100 PTS", "100 pts abordabilité + efficacité"),
    "achat": ("CONVENTIONNEL", "CONVENTIONNEL", "Refinancement conventionnel"),
}

_STRATEGIES = {
    "preteur_b": "Prêteur B",
    "traditionnel": "Institution financière",
    "residentiel": "Résidentiel",
    "assumation": "Assumation hypothécaire",
}

#: Libellés des postes de frais de démarrage (diapo 9, « Frais autres »).
_FRAIS_LABELS: List[Tuple[str, str]] = [
    ("courtier_hypothecaire_1", "Courtier hypothécaire achat"),
    ("courtier_hypothecaire_2", "Courtier hypothécaire refin"),
    ("taxes_bienvenue", "Taxes bienvenue"),
    ("evaluateur", "Évaluateur"),
    ("evaluateur_2", "Évaluateur 2"),
    ("inspection", "Inspection"),
    ("avocat", "Avocat"),
    ("notaire", "Notaire"),
    ("notaire_2", "Notaire 2"),
    ("rapport_efficacite", "Rapport efficacité"),
    ("frais_dossier_preteur", "Frais de dossier prêteur"),
    ("interets_balance_vente", "Intérêt BPV"),
    ("detention", "Détention"),
]

_JAUNE = "F8D956"
_BLANC = "FFFFFF"
_TEAL = "009999"


# ─── Formats ─────────────────────────────────────────────────────────


def _f(v: Any) -> float:
    try:
        if v is None or v == "":
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def money(n: Any, *, signe: bool = False) -> str:
    """« 1 800 000$ » (style des decks de Phil) ; négatif « -534 884$ »."""
    v = int(round(_f(n)))
    s = f"{abs(v):,}".replace(",", " ")
    if v < 0:
        return f"-{s}$"
    if signe and v > 0:
        return f"+{s}$"
    return f"{s}$"


def money_an(n: Any) -> str:
    return f"{f'{int(round(_f(n))):,}'.replace(',', ' ')} $/an"


def money_M(n: Any) -> str:
    """« 1,8 M$ » au-dessus du million, sinon « 950 000$ »."""
    v = _f(n)
    if abs(v) >= 1_000_000:
        s = f"{v / 1_000_000:.1f}".replace(".", ",")
        if s.endswith(",0"):
            s = s[:-2]
        return f"{s} M$"
    return money(v)


def money_k(n: Any) -> str:
    return f"{int(round(_f(n) / 1000.0))}k"


def pct(x: Any, dec: int = 0, *, espace: bool = False) -> str:
    """Fraction → « 80% » / « 7,85% » ; ``espace`` → « 37,5 % »."""
    v = _f(x) * 100.0
    s = f"{v:.{dec}f}".replace(".", ",")
    return f"{s} %" if espace else f"{s}%"


def ratio(x: Any) -> str:
    return f"{_f(x):.2f}".replace(".", ",")


def _fmt_mois(d: date) -> str:
    return f"{_MOIS[d.month]} {d.year}"


def _add_months(d: date, n: int) -> date:
    total = d.month - 1 + n
    return date(d.year + total // 12, total % 12 + 1, 1)


def _parse_date(s: Any, defaut: Optional[date] = None) -> Optional[date]:
    if isinstance(s, date):
        return s
    if not s:
        return defaut
    try:
        return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return defaut


def _mois_index(d: date, origine: date) -> int:
    return (d.year - origine.year) * 12 + (d.month - origine.month)


def _typologie_texte(typology_json: Optional[str]) -> str:
    """{"5.5": 2, "6.5": 6} → « 2 x 5 ½ + 6 x 6 ½ »."""
    try:
        d = json.loads(typology_json or "{}")
    except (TypeError, ValueError):
        return ""
    parts = []
    for k in sorted(d, key=lambda x: _f(x)):
        n = int(_f(d.get(k)))
        if n <= 0:
            continue
        entier = str(k).split(".")[0]
        parts.append(f"{n} x {entier} ½")
    return " + ".join(parts)


def _slug(addr: Optional[str], fallback_id: int) -> str:
    s = (addr or "").strip()
    if not s:
        return f"analyse_{fallback_id}"
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_-]+", "_", s).strip("_")
    return s[:60] or f"analyse_{fallback_id}"


def offre_investissement_pptx_filename(rec: Any) -> str:
    return (
        f"Offre_Investissement_{_slug(getattr(rec, 'address', None), getattr(rec, 'id', 0))}"
        f"_{date.today().isoformat()}.pptx"
    )


# ─── Intrants de l'assistant ─────────────────────────────────────────


@dataclass
class Jalon:
    date: str = ""
    label: str = ""


@dataclass
class DeckInputs:
    """Ce que l'assistant demande (tout est pré-rempli par
    ``proposer_intrants`` ; l'utilisateur ajuste)."""

    # Diapo 1
    tagline: str = ""
    presente_par: str = "Horizon Services Immobiliers"
    # Diapo 2
    projet_sous_titre: str = "Acquisition & optimisation"
    investissement_requis: Optional[float] = None
    pct_parts: Optional[float] = None  # fraction (0.5)
    # Diapo 3
    nb_etages: Optional[int] = None
    superficie_text: str = ""
    unites_note: str = ""
    frais_energetiques_text: str = ""
    stationnements_text: str = ""
    # Diapo 4
    bullets: List[str] = field(default_factory=list)
    comparable_phrase: str = ""
    comparable_url: str = ""
    valeur_comparable: Optional[float] = None
    # Diapo 5
    leviers: List[str] = field(default_factory=list)
    # Diapo 6
    date_debut: str = ""
    jalons: Dict[str, Jalon] = field(default_factory=dict)
    # Diapo 9
    renovations: List[str] = field(default_factory=list)
    # Diapo 12
    tendances_secteur: str = ""
    tendances_source: str = ""
    # Diapo 14
    contingence_pct: float = 10.0
    fonds_roulement_mois: int = 4

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "DeckInputs":
        d = dict(d or {})
        jalons_raw = d.pop("jalons", None) or {}
        jalons: Dict[str, Jalon] = {}
        if isinstance(jalons_raw, dict):
            for k, v in jalons_raw.items():
                if isinstance(v, dict):
                    jalons[str(k)] = Jalon(date=str(v.get("date") or ""), label=str(v.get("label") or ""))
        obj = cls()
        for k, v in d.items():
            if not hasattr(obj, k) or k == "jalons":
                continue
            cur = getattr(obj, k)
            if isinstance(cur, bool):
                setattr(obj, k, bool(v))
            elif isinstance(cur, int) and not isinstance(cur, bool) and v is not None and v != "":
                try:
                    setattr(obj, k, int(_f(v)))
                except (TypeError, ValueError):
                    pass
            elif isinstance(cur, float) and v is not None and v != "":
                setattr(obj, k, _f(v))
            elif cur is None:
                if v is None or v == "":
                    setattr(obj, k, None)
                elif k == "nb_etages":
                    setattr(obj, k, int(_f(v)))
                else:
                    setattr(obj, k, _f(v))
            elif isinstance(cur, list):
                setattr(obj, k, [str(x) for x in (v or []) if str(x).strip()])
            else:
                setattr(obj, k, "" if v is None else str(v))
        obj.jalons = jalons
        return obj

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["jalons"] = {k: asdict(v) for k, v in self.jalons.items()}
        return d


# ─── Données du deck (fiche + résultats + TRI) ──────────────────────


def _charger_resultats(rec: Any) -> Dict[str, Any]:
    raw = getattr(rec, "analysis_results_json", None)
    if not raw:
        raise ValueError(
            "Lance d'abord l'analyse financière de la fiche : le deck "
            "s'appuie sur ses scénarios."
        )
    try:
        res = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Résultats d'analyse illisibles — relance l'analyse.") from exc
    if not isinstance(res, dict) or not res.get("scenarios"):
        raise ValueError("Résultats d'analyse incomplets — relance l'analyse.")
    if not isinstance(res.get("cout_projet"), dict) or not isinstance(res.get("frais_demarrage"), dict):
        # Résultats persistés par une version antérieure du moteur (avant
        # le coût du projet du 2026-10-07) : plutôt qu'imprimer des zéros,
        # on demande un recalcul (un clic sur « Lancer l'analyse »).
        raise ValueError(
            "Résultats d'analyse d'une version antérieure — relance "
            "l'analyse (onglet Analyse → Lancer l'analyse) avant de générer le deck."
        )
    return res


def _scenario_par_label(scenarios: Dict[str, Any], label: Optional[str]) -> Optional[Dict[str, Any]]:
    if not label:
        return None
    for k, s in scenarios.items():
        if isinstance(s, dict) and k.startswith("refi_") and s.get("label") == label:
            return s
    return None


def _refis(res: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
    """(scénario de refi retenu, second scénario, source) — prêteur B ou
    institution traditionnelle."""
    trad = res.get("traditionnel")
    if isinstance(trad, dict) and isinstance(trad.get("refi"), dict):
        refi = {k: v for k, v in trad["refi"].items() if isinstance(v, dict)}
        best_key = (trad.get("best_refi") or {}).get("key")
        best = refi.get(best_key) if best_key else None
        if best is None and refi:
            best = max(refi.values(), key=lambda s: _f(s.get("equite_a_la_fin")))
        autres = [s for k, s in refi.items() if s is not best]
        second = max(autres, key=lambda s: _f(s.get("equite_a_la_fin"))) if autres else None
        return best, second, "traditionnel"
    scen = {k: v for k, v in (res.get("scenarios") or {}).items() if isinstance(v, dict)}
    refi = {k: v for k, v in scen.items() if k.startswith("refi_")}
    best = _scenario_par_label(refi, (res.get("best_refi") or {}).get("program"))
    if best is None and refi:
        best = max(refi.values(), key=lambda s: _f(s.get("equite_a_la_fin")))
    autres = [s for s in refi.values() if s is not best]
    second = max(autres, key=lambda s: _f(s.get("equite_a_la_fin"))) if autres else None
    return best, second, "preteur_b"


def _programme(scen: Optional[Dict[str, Any]]) -> Tuple[str, str, str]:
    if not scen:
        return ("—", "—", "")
    return _PROGRAMMES.get(str(scen.get("name") or ""), (str(scen.get("label") or "—").upper(), str(scen.get("label") or "—"), ""))


async def _tri_pour_deck(
    db: Any, rec: Any, res: Dict[str, Any], capital: Optional[float], pct_parts: Optional[float]
) -> Dict[str, Any]:
    """TRI investisseur avec les mêmes dérivations que l'onglet TRI de la
    fiche (intrants auto + manuels persistés, défauts configurables)."""
    # Import tardif : ces dérivations vivent dans le module d'endpoints
    # (elles alimentent l'onglet TRI) ; l'endpoint du deck importe ce
    # service à l'exécution, donc aucun import circulaire au chargement.
    from app.api.v1.endpoints.lead_analyses import (
        _amortissement_tri,
        _annee_refi_de,
        _derive_tri_auto_inputs,
        _load_tri_defaults,
        _persisted_manual_inputs,
    )
    from app.services.lead_tri_calc import compute_tri

    auto = _derive_tri_auto_inputs(res)
    amort = _amortissement_tri(res, rec)
    defaults = await _load_tri_defaults(db) if db is not None else {}
    manual = _persisted_manual_inputs(rec, defaults)
    cap = _f(capital) if capital else _f(manual.get("capital"))
    if cap <= 0:
        cap = _f((res.get("cout_projet") or {}).get("cash_total"))
    pct_val = _f(pct_parts) if pct_parts else _f(manual.get("pct"))
    tri = compute_tri(
        prix=auto["prix"], rpv_achat=auto["rpv_achat"], pret_constr=auto["pret_constr"],
        mdf=auto["mdf"], capital=cap, pct=pct_val, loyers2=auto["loyers2"], dep2=auto["dep2"],
        valeur2=auto["valeur2"], rpv_refi=auto["rpv_refi"], cr_loyers=manual["cr_loyers"],
        cr_dep=manual["cr_dep"], annee_refi=_annee_refi_de(rec),
        taux_achat=amort.get("taux_achat") or None, amort_achat=amort.get("amort_achat") or None,
        amortissement_initial=bool(amort.get("amortissement_initial")),
        taux_refi=amort.get("taux_refi") or None, amort_refi=amort.get("amort_refi") or None,
    )
    tri["capital"] = cap
    tri["pct"] = pct_val
    return tri


def construire_donnees(rec: Any, res: Dict[str, Any], tri: Dict[str, Any]) -> Dict[str, Any]:
    """Toutes les valeurs du deck, déjà résolues (une seule source de
    vérité pour la génération et l'aperçu de l'assistant)."""
    scen = {k: v for k, v in (res.get("scenarios") or {}).items() if isinstance(v, dict)}
    achat = scen.get("achat") or {}
    best, second, source = _refis(res)
    trad = res.get("traditionnel") if source == "traditionnel" else None
    strategie = str(res.get("strategie") or getattr(rec, "strategie_acquisition", None) or "preteur_b")
    cout = res.get("cout_projet") or {}
    prix = _f(res.get("prix_achat") or getattr(rec, "asking_price", None))
    nb_log = int(_f(getattr(rec, "nb_logements", None)) or _f(achat.get("nb_log")))
    revenus = _f(getattr(rec, "revenus_bruts", None) or achat.get("revenus_totaux"))
    loyer_moyen = revenus / 12.0 / nb_log if nb_log else 0.0
    duree = int(_f(getattr(rec, "duree_projet_annees", None)) or 2)
    horizons = [int(h) for h in (tri.get("horizons_list") or [duree, duree + 5, duree + 10])]
    h0 = horizons[0]

    # Frais de démarrage (dict des postes) selon la branche.
    if trad:
        frais = dict(trad.get("frais_demarrage") or {})
        frais_total = _f(trad.get("frais_demarrage_total"))
    else:
        frais = dict(res.get("frais_demarrage") or {})
        frais_total = _f(res.get("frais_demarrage_total"))
    frais_custom = frais.pop("frais_custom", None) or []

    # Bloc achat / financement.
    if trad:
        prog_achat = (trad.get("achat") or {}).get(trad.get("programme_retenu") or "") or {}
        ltv_achat = _f(prog_achat.get("ltv"))
        rcd_achat = ratio(prog_achat.get("rcd")) if prog_achat.get("rcd") else "N/A"
        type_pret = f"Amorti {int(_f(prog_achat.get('amort_annees')) or 25)} ans"
        valeur_eco_achat = _f(prog_achat.get("valeur_retenue")) or prix
        pret_max = _f(trad.get("pret_retenu"))
        mdf = _f((trad.get("detail_mdf_par_programme") or {}).get(trad.get("programme_retenu") or "", {}).get("mdf_brute")) or _f(trad.get("mdf_cash"))
        taux_achat = _f(res.get("taux_interet_achat"))
    else:
        mdf_pct = _f(res.get("mdf_preteur_b_pct"))
        ltv_achat = 1.0 - mdf_pct if mdf_pct else _f(achat.get("ltv"))
        rcd_achat = "N/A"
        type_pret = "Intérêt seul."
        valeur_eco_achat = prix
        # Prêt hypothécaire sur le PRIX (les frais financés sont un prêt
        # à part, « ***Certains frais financés ») — comme dans le deck
        # final 2420 (1 440 000$ = 80 % × 1,8 M$).
        pret_max = (
            _f((res.get("pret_preteur_b") or {}).get("sur_prix"))
            or _f((res.get("pret_preteur_b") or {}).get("total"))
            or prix * ltv_achat
        )
        mdf = _f(res.get("mdf_pct_prix_achat")) or (prix * mdf_pct)
        taux_achat = _f(res.get("taux_interet_preteur_b_projet")) or _f(res.get("taux_interet_achat"))
    fonds = _f(cout.get("cash_total")) or _f(res.get("mdf_preteur_b"))
    balance_vente = _f(cout.get("balance_vente")) or _f((res.get("balance_vente") or {}).get("montant"))

    # Dépenses normalisées à l'achat.
    dep = dict(achat.get("depenses") or {})
    autres_dep = sum(_f(dep.get(k)) for k in dep if k not in (
        "inoccupation", "taxes_municipales", "taxes_scolaires", "assurances", "energie",
        "gestion", "entretien", "concierge",
    ))
    depenses_lignes = [
        (f"Inoccupation ({pct(res.get('taux_inoccupation_pct') or 0.03)})", _f(dep.get("inoccupation"))),
        ("Taxes municipales", _f(dep.get("taxes_municipales"))),
        ("Taxes scolaires", _f(dep.get("taxes_scolaires"))),
        ("Assurances (estimé)", _f(dep.get("assurances"))),
        ("Énergie", _f(dep.get("energie"))),
        ("Gestion", _f(dep.get("gestion"))),
        ("Entretien", _f(dep.get("entretien"))),
        ("Autres normalisations", autres_dep),
        ("Concierge", _f(dep.get("concierge"))),
    ]

    # Frais autres (diapo 9) : postes non nuls, intérêts nets regroupés.
    interets_nets = _f(frais.get("interets")) + _f(frais.get("revenus_nets_pendant_projet"))
    frais_autres: List[Tuple[str, float]] = []
    for key, label in _FRAIS_LABELS:
        v = _f(frais.get(key))
        if abs(v) >= 0.5:
            frais_autres.append((label, v))
    if abs(interets_nets) >= 0.5:
        frais_autres.append(("Intérêt – Revenus", interets_nets))
    for c in frais_custom:
        if isinstance(c, dict) and abs(_f(c.get("montant"))) >= 0.5:
            frais_autres.append((str(c.get("label_fr") or c.get("id") or "Poste")[:40], _f(c.get("montant"))))
    frais_autres_total = sum(v for _l, v in frais_autres)
    dev = _f(frais.get("frais_developpement"))
    nego = _f(frais.get("frais_negociations"))
    travaux = _f(frais.get("frais_travaux")) or _f(getattr(rec, "travaux_estimes", None))

    # Refi.
    titre_prog, label_prog, sous_titre_prog = _programme(best)
    nouveau_loyer = _f(best.get("loyer_mois")) if best else 0.0
    nouveaux_revenus = _f(best.get("revenus_totaux")) if best else 0.0
    valeur_refi = _f(best.get("valeur_retenue")) if best else 0.0
    pret_refi = _f(best.get("financement")) if best else 0.0
    equite = _f(best.get("equite_a_la_fin")) if best else 0.0
    reduction_energie = _f(getattr(rec, "reduction_energie_pct", None)) / 100.0
    energie = _f(getattr(rec, "energie", None))
    nb_thermo = int(_f(getattr(rec, "nb_thermopompes_ajoutees", None)))
    wifi = bool(getattr(rec, "ajout_wifi", True) if getattr(rec, "ajout_wifi", None) is not None else True)

    def _scen_vue(s: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not s:
            return {"label": "—", "ltv": "—", "rcd": "—", "revenus_net": "—", "amort": "—",
                    "valeur": "—", "pret": "—", "equite": "—"}
        return {
            "label": _programme(s)[1],
            "ltv": pct(s.get("ltv")),
            "rcd": ratio(s.get("rcd")),
            "revenus_net": money(s.get("revenus_net")),
            "amort": f"{int(_f(s.get('amort_annees')))} ans",
            "valeur": money(s.get("valeur_retenue")),
            "pret": money(s.get("financement")),
            "equite": money(s.get("equite_a_la_fin")),
        }

    hz = tri.get("horizons") or {}
    tri_vals = tri.get("tri") or {}
    capital = _f(tri.get("capital"))
    pct_parts = _f(tri.get("pct"))
    par_horizon = []
    for h in horizons:
        d = hz.get(str(h)) or {}
        cash = _f(d.get("cash_investisseur"))
        parts = _f(d.get("valeur_parts"))
        par_horizon.append({
            "annee": h, "cash": cash, "parts": parts, "patrimoine": cash + parts,
            "tri": tri_vals.get(f"an{h}"), "valeur": _f(d.get("valeur_immeuble")),
            "equite": _f(d.get("equite")),
        })

    return {
        "adresse": (getattr(rec, "address", None) or "").strip(),
        "ville": (getattr(rec, "city", None) or "").strip(),
        "adresse_complete": ", ".join(x for x in [(getattr(rec, "address", None) or "").strip(), (getattr(rec, "city", None) or "").strip()] if x),
        "prix": prix, "nb_log": nb_log, "revenus": revenus, "loyer_moyen": loyer_moyen,
        "annee_construction": getattr(rec, "annee_construction", None),
        "typologie": _typologie_texte(getattr(rec, "typology_json", None)),
        "superficie": _f(getattr(rec, "superficie_batiment", None)),
        "stationnements": int(_f(getattr(rec, "nb_stationnements", None))),
        "energie": energie, "energie_apres": energie * (1.0 - reduction_energie),
        "duree": duree, "horizons": horizons, "h0": h0,
        "strategie": strategie, "strategie_label": _STRATEGIES.get(strategie, strategie),
        "taux_achat": taux_achat, "taux_refi": _f(res.get("taux_interet_refi")),
        "ltv_achat": ltv_achat, "rcd_achat": rcd_achat, "type_pret": type_pret,
        "revenus_net_achat": _f(achat.get("revenus_net")),
        "valeur_eco_achat": valeur_eco_achat, "pret_max": pret_max, "mdf": mdf,
        "fonds_necessaires": fonds, "balance_vente": balance_vente,
        "frais_total": frais_total, "frais_autres": frais_autres,
        "frais_autres_total": frais_autres_total, "dev": dev, "nego": nego, "travaux": travaux,
        "depenses_lignes": depenses_lignes,
        "refi": {
            "titre": titre_prog, "label": label_prog, "sous_titre": sous_titre_prog,
            "depenses": _f(best.get("depenses_total")) if best else 0.0,
            "nouveau_loyer": nouveau_loyer, "nouveaux_revenus": nouveaux_revenus,
            "nb_log": int(_f(best.get("nb_log"))) if best else nb_log,
            "valeur": valeur_refi, "pret": pret_refi, "equite": equite,
            "wifi": wifi, "nb_thermo": nb_thermo, "reduction_energie": reduction_energie,
            "scenario_1": _scen_vue(best), "scenario_2": _scen_vue(second),
        },
        "tri": {"capital": capital, "pct": pct_parts, "horizons": par_horizon},
        "valeur_eco_tga_achat": _f(achat.get("valeur_eco_tga")),
    }


def proposer_intrants(rec: Any, d: Dict[str, Any], existants: Optional[Dict[str, Any]] = None) -> DeckInputs:
    """Intrants proposés (tout pré-rempli) ; ``existants`` (dict partiel)
    écrase les propositions champ par champ."""
    ville = d["ville"] or "Montréal"
    debut = date.today().replace(day=1)
    notaire = _add_months(debut, 3)
    duree = int(d["duree"] or 2)
    jalons = {
        "m1_1": Jalon(_add_months(debut, 2).isoformat(), "Lettre de financement"),
        "m1_2": Jalon(notaire.isoformat(), "Passage au notaire"),
        "m2_1": Jalon(_add_months(notaire, 3).isoformat(), "Ententes avec les locataires"),
        "m2_2": Jalon(_add_months(notaire, 6).isoformat(), "Fin des travaux majeurs"),
        "m2_3": Jalon(_add_months(notaire, 8).isoformat(), "Fin des travaux appartements"),
        "m2_4": Jalon(_add_months(notaire, 9).isoformat(), "Locations et stabilisation"),
        "m3_1": Jalon(_add_months(notaire, 12 * duree).isoformat(), "Remboursement des partenaires"),
    }
    comparable = d["valeur_eco_tga_achat"]
    if comparable <= d["prix"]:
        comparable = 0.0
    comparable = float(int(round(comparable / 10_000.0)) * 10_000) if comparable else 0.0
    gain_loyer = d["refi"]["nouveau_loyer"] - d["loyer_moyen"]
    bullets = [
        f"Immeuble de {d['nb_log']} logements acquis sous la valeur économique ({money(d['prix'])})",
        f"Loyers moyens actuels sous le marché ({money(d['loyer_moyen'])}/mois)",
        f"Potentiel d'optimisation à {money(d['refi']['nouveau_loyer'])}/mois (+{money(max(gain_loyer, 0))}) via rénovations ciblées",
        f"Demande forte | Secteur {ville}",
    ]
    stationnements = d["stationnements"]
    trimestre = (date.today().month - 1) // 3 + 1
    base = DeckInputs(
        tagline=f"De l'achat au refinancement: un projet immobilier exceptionnel à {ville}",
        investissement_requis=round(d["tri"]["capital"]) if d["tri"]["capital"] else round(d["fonds_necessaires"]),
        pct_parts=d["tri"]["pct"] or 0.5,
        nb_etages=None,
        superficie_text=(f"{int(round(d['superficie']))} pi²" if d["superficie"] else "À confirmer"),
        unites_note=(f"{stationnements} stationnements" if stationnements else ""),
        frais_energetiques_text=("Propriétaire" if d["energie"] > 0 else "Locataires"),
        stationnements_text=(str(stationnements) if stationnements else "Aucun"),
        bullets=bullets,
        comparable_phrase=(f"Comparable du secteur à {money_M(comparable)}" if comparable else ""),
        comparable_url="",
        valeur_comparable=comparable or None,
        leviers=["📈 Optimisation des loyers", "🛠️ Rénovations ciblées", "💡 Réduction des dépenses", "🏅 Ajout de services"],
        date_debut=debut.isoformat(),
        jalons=jalons,
        renovations=[],
        tendances_secteur=ville,
        tendances_source=f"Zipplex, données Q{trimestre} {date.today().year}",
        contingence_pct=10.0,
        fonds_roulement_mois=4,
    )
    if existants:
        merged = base.to_dict()
        for k, v in existants.items():
            if k == "jalons" and isinstance(v, dict):
                for jk, jv in v.items():
                    if isinstance(jv, dict) and jk in merged["jalons"]:
                        merged["jalons"][jk].update({kk: vv for kk, vv in jv.items() if vv not in (None, "")})
            elif v is not None:
                merged[k] = v
        return DeckInputs.from_dict(merged)
    return base


def apercu(d: Dict[str, Any]) -> Dict[str, Any]:
    """Chiffres clés affichés dans l'assistant (ce qui sera imprimé)."""
    return {
        "adresse": d["adresse_complete"], "prix": d["prix"], "nb_logements": d["nb_log"],
        "revenus": d["revenus"], "loyer_moyen": round(d["loyer_moyen"]),
        "strategie": d["strategie_label"], "frais_demarrage": d["frais_total"],
        "pret_max": d["pret_max"], "mdf": d["mdf"], "fonds_necessaires": d["fonds_necessaires"],
        "balance_vente": d["balance_vente"],
        "refi_programme": d["refi"]["label"], "refi_valeur": d["refi"]["valeur"],
        "refi_pret": d["refi"]["pret"], "refi_equite": d["refi"]["equite"],
        "nouveau_loyer": d["refi"]["nouveau_loyer"], "nouveaux_revenus": d["refi"]["nouveaux_revenus"],
        "capital": d["tri"]["capital"], "pct_parts": d["tri"]["pct"],
        "tri": [{"annee": h["annee"], "tri": h["tri"], "cash": h["cash"], "parts": h["parts"], "patrimoine": h["patrimoine"]} for h in d["tri"]["horizons"]],
    }


# ─── Accès aux formes (python-pptx) ──────────────────────────────────


class _Filler:
    """Remplissage par nom de forme ; chaque cible introuvable est notée
    (``misses``) au lieu de laisser le texte du gabarit en place."""

    def __init__(self, prs: Any) -> None:
        self.prs = prs
        self.misses: List[str] = []
        self.remplis = 0

    # -- recherche -----------------------------------------------------
    def shape(self, idx: int, name: str) -> Any:
        try:
            slide = self.prs.slides[idx]
        except IndexError:
            self.misses.append(f"diapo {idx + 1} absente")
            return None
        for sh in slide.shapes:
            if sh.name == name:
                return sh
        self.misses.append(f"diapo {idx + 1} : forme « {name} » introuvable")
        return None

    # -- texte ---------------------------------------------------------
    @staticmethod
    def _style_run(run: Any, *, bold: Optional[bool] = None, size: Optional[float] = None,
                   color: Optional[str] = None) -> None:
        from pptx.dml.color import RGBColor
        from pptx.util import Pt

        if bold is not None:
            run.font.bold = bold
        if size is not None:
            run.font.size = Pt(size)
        if color:
            run.font.color.rgb = RGBColor.from_string(color)

    def para(self, tf: Any, idx: int, text: str, *, keep_runs: int = 1, bold: Optional[bool] = None,
             size: Optional[float] = None, color: Optional[str] = None, where: str = "") -> bool:
        """Écrit ``text`` dans le 1er run du paragraphe ``idx`` (format
        conservé), vide les runs suivants. Crée le paragraphe / run au
        besoin (copie du format du dernier paragraphe)."""
        paras = list(tf.paragraphs)
        while idx >= len(paras):
            tf.add_paragraph()
            paras = list(tf.paragraphs)
            if len(paras) >= 2:
                # Copie des propriétés de paragraphe (alignement…) du précédent.
                prev, new = paras[-2]._p, paras[-1]._p
                ppr = prev.find("{http://schemas.openxmlformats.org/drawingml/2006/main}pPr")
                if ppr is not None:
                    new.insert(0, copy.deepcopy(ppr))
        p = paras[idx]
        runs = list(p.runs)
        if not runs:
            # Nouveau run : on hérite du format d'un run voisin si possible.
            modele = None
            for q in paras:
                if q.runs:
                    modele = q.runs[0]
                    break
            r = p.add_run()
            r.text = text
            if modele is not None:
                r.font.bold = modele.font.bold
                r.font.size = modele.font.size
                try:
                    if modele.font.color is not None and modele.font.color.type is not None:
                        if modele.font.color.type == 1:
                            r.font.color.rgb = modele.font.color.rgb
                        else:
                            r.font.color.theme_color = modele.font.color.theme_color
                except Exception:  # noqa: BLE001
                    pass
            self._style_run(r, bold=bold, size=size, color=color)
        else:
            runs[0].text = text
            for r in runs[1:]:
                r.text = ""
            self._style_run(runs[0], bold=bold, size=size, color=color)
        self.remplis += 1
        return True

    def runs(self, tf: Any, idx: int, textes: List[str], where: str = "") -> bool:
        """Écrit plusieurs runs sur le paragraphe ``idx`` (formats des runs
        existants conservés ; manquants dupliqués du dernier)."""
        paras = list(tf.paragraphs)
        if idx >= len(paras):
            self.misses.append(f"{where} : paragraphe {idx} absent")
            return False
        p = paras[idx]
        runs = list(p.runs)
        if not runs:
            return self.para(tf, idx, "".join(textes), where=where)
        while len(runs) < len(textes):
            last = runs[-1]._r
            new = copy.deepcopy(last)
            last.addnext(new)
            runs = list(p.runs)
        for i, r in enumerate(runs):
            r.text = textes[i] if i < len(textes) else ""
        self.remplis += 1
        return True

    def clear_paras(self, tf: Any, from_idx: int) -> None:
        for p in list(tf.paragraphs)[from_idx:]:
            for r in p.runs:
                r.text = ""

    def text(self, idx: int, name: str, text: str, para_idx: int = 0, **style: Any) -> bool:
        sh = self.shape(idx, name)
        if sh is None or not sh.has_text_frame:
            if sh is not None:
                self.misses.append(f"diapo {idx + 1} : « {name} » sans texte")
            return False
        return self.para(sh.text_frame, para_idx, text, where=f"diapo {idx + 1} « {name} »", **style)

    # -- tableaux ------------------------------------------------------
    def table(self, idx: int, name: str) -> Any:
        sh = self.shape(idx, name)
        if sh is None:
            return None
        if not getattr(sh, "has_table", False):
            self.misses.append(f"diapo {idx + 1} : « {name} » n'est pas un tableau")
            return None
        return sh

    def cell(self, tbl_shape: Any, r: int, c: int, text: str, *, para_idx: int = 0, where: str = "",
             **style: Any) -> bool:
        tbl = tbl_shape.table
        if r >= len(tbl.rows) or c >= len(tbl.columns):
            self.misses.append(f"{where} : cellule [{r}][{c}] hors tableau")
            return False
        cell = tbl.cell(r, c)
        ok = self.para(cell.text_frame, para_idx, text, where=f"{where} [{r}][{c}]", **style)
        if para_idx == 0:
            self.clear_paras(cell.text_frame, 1)
        return ok

    def cell_runs(self, tbl_shape: Any, r: int, c: int, textes: List[str], *, where: str = "") -> bool:
        tbl = tbl_shape.table
        if r >= len(tbl.rows) or c >= len(tbl.columns):
            self.misses.append(f"{where} : cellule [{r}][{c}] hors tableau")
            return False
        cell = tbl.cell(r, c)
        ok = self.runs(cell.text_frame, 0, textes, where=f"{where} [{r}][{c}]")
        self.clear_paras(cell.text_frame, 1)
        return ok

    @staticmethod
    def cell_clear(tbl_shape: Any, r: int, c: int) -> None:
        tbl = tbl_shape.table
        if r < len(tbl.rows) and c < len(tbl.columns):
            for p in tbl.cell(r, c).text_frame.paragraphs:
                for run in p.runs:
                    run.text = ""

    @staticmethod
    def cell_fill(tbl_shape: Any, r: int, c: int, rgb: Optional[str]) -> None:
        from pptx.dml.color import RGBColor

        cell = tbl_shape.table.cell(r, c)
        if rgb:
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor.from_string(rgb)
        else:
            cell.fill.background()

    # -- graphiques ----------------------------------------------------
    def chart(self, idx: int, name: str, categories: List[str], series: List[Tuple[str, List[float]]],
              title: Optional[str] = None) -> bool:
        from pptx.chart.data import CategoryChartData

        sh = self.shape(idx, name)
        if sh is None:
            return False
        if not getattr(sh, "has_chart", False):
            self.misses.append(f"diapo {idx + 1} : « {name} » n'est pas un graphique")
            return False
        cd = CategoryChartData()
        cd.categories = categories
        for s_name, vals in series:
            cd.add_series(s_name, [float(v) for v in vals])
        try:
            sh.chart.replace_data(cd)
        except Exception as exc:  # noqa: BLE001
            self.misses.append(f"diapo {idx + 1} : données de « {name} » non remplacées ({exc})")
            return False
        if title is not None and sh.chart.has_title:
            self.para(sh.chart.chart_title.text_frame, 0, title, where=f"titre « {name} »")
        self.remplis += 1
        return True

    # -- formes --------------------------------------------------------
    def delete(self, idx: int, name: str, *, optional: bool = False) -> bool:
        try:
            slide = self.prs.slides[idx]
        except IndexError:
            return False
        for sh in slide.shapes:
            if sh.name == name:
                el = sh._element
                el.getparent().remove(el)
                return True
        if not optional:
            self.misses.append(f"diapo {idx + 1} : « {name} » à supprimer introuvable")
        return False

    # -- images --------------------------------------------------------
    def picture(self, idx: int, name: str, blob: bytes) -> bool:
        from pptx.oxml.ns import qn

        sh = self.shape(idx, name)
        if sh is None:
            return False
        if sh.shape_type != 13:
            self.misses.append(f"diapo {idx + 1} : « {name} » n'est pas une image")
            return False
        prepared = _preparer_image(blob, sh.width / float(sh.height) if sh.height else 1.0)
        if prepared is None:
            self.misses.append(f"diapo {idx + 1} : image « {name} » illisible")
            return False
        slide = self.prs.slides[idx]
        blip = sh._element.blipFill.blip
        old_rid = blip.rEmbed
        _part, rid = slide.part.get_or_add_image_part(io.BytesIO(prepared))
        blip.rEmbed = rid
        src_rect = sh._element.blipFill.find(qn("a:srcRect"))
        if src_rect is not None:
            sh._element.blipFill.remove(src_rect)
        if old_rid and old_rid != rid:
            try:
                slide.part.rels.pop(old_rid)
            except KeyError:
                pass
        self.remplis += 1
        return True


def _preparer_image(blob: bytes, aspect: float) -> Optional[bytes]:
    """Recadre au centre à l'aspect de la forme et réduit (≤ 1800 px),
    JPEG 85 — PNG conservé si transparent."""
    try:
        from PIL import Image, ImageOps

        try:
            import pillow_heif  # type: ignore

            pillow_heif.register_heif_opener()
        except Exception:  # noqa: BLE001
            pass
        img = Image.open(io.BytesIO(blob))
        img = ImageOps.exif_transpose(img)
        alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        img = img.convert("RGBA" if alpha else "RGB")
        w, h = img.size
        if w <= 0 or h <= 0:
            return None
        cur = w / float(h)
        if aspect > 0 and abs(cur - aspect) > 0.01:
            if cur > aspect:
                nw = int(round(h * aspect))
                x0 = (w - nw) // 2
                img = img.crop((x0, 0, x0 + nw, h))
            else:
                nh = int(round(w / aspect))
                y0 = (h - nh) // 2
                img = img.crop((0, y0, w, y0 + nh))
        img.thumbnail((1800, 1800))
        out = io.BytesIO()
        if alpha:
            img.save(out, "PNG", optimize=True)
        else:
            img.save(out, "JPEG", quality=85, optimize=True)
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.warning("Image du deck illisible : %s", exc)
        return None


# ─── Remplissage diapo par diapo ─────────────────────────────────────


def _remplir_diapo_1(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    F.text(0, "ZoneTexte 5", inp.tagline or f"De l'achat au refinancement: un projet immobilier exceptionnel à {d['ville'] or 'Montréal'}")
    F.text(0, "ZoneTexte 6", d["adresse_complete"] or "Adresse à confirmer")
    F.text(0, "ZoneTexte 7", inp.presente_par or "Horizon Services Immobiliers", para_idx=1)


def _remplir_diapo_2(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    F.text(1, "TextBox 30", inp.projet_sous_titre or "Acquisition & optimisation", para_idx=1)
    F.text(1, "TextBox 30", f"Immeuble de {d['nb_log']} logements", para_idx=2)
    F.text(1, "TextBox 31", d["adresse_complete"] or "Adresse à confirmer", para_idx=1)
    F.text(1, "TextBox 36", f"Refinancement {d['h0']} ans | ", para_idx=1)
    cap = d["tri"]["capital"]
    F.text(1, "TextBox 34", money(cap), para_idx=1)
    F.text(1, "TextBox 34", f"🏷️ {pct(d['tri']['pct'])} des parts du projet", para_idx=2)
    hz = d["tri"]["horizons"]
    tri_txt = [("n/d" if h["tri"] is None else pct(h["tri"], 1, espace=True)) for h in hz]
    F.text(1, "TextBox 37", f" TRI* {hz[0]['annee']} ans :  {tri_txt[0]} |  ", para_idx=1)
    F.text(1, "TextBox 37", f"TRI {hz[1]['annee']} ans : {tri_txt[1]} |", para_idx=2)
    F.text(1, "TextBox 37", f"TRI {hz[2]['annee']} ans : {tri_txt[2]}", para_idx=3)


def _remplir_diapo_3(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    t11 = F.table(2, "Table 11")
    if t11 is not None:
        F.cell(t11, 0, 1, money_M(d["prix"]), where="diapo 3 Table 11")
        F.cell(t11, 1, 1, money_an(d["revenus"]), where="diapo 3 Table 11")
        F.cell(t11, 2, 1, money_an(d["refi"]["nouveaux_revenus"]), where="diapo 3 Table 11")
    t12 = F.table(2, "Table 12")
    if t12 is not None:
        tf = t12.table.cell(0, 1).text_frame
        F.para(tf, 0, f"{d['nb_log']} logements", where="diapo 3 unités")
        F.para(tf, 1, f" {d['typologie']} " if d["typologie"] else " Typologie à confirmer ", where="diapo 3 unités")
        F.para(tf, 2, inp.unites_note or "", where="diapo 3 unités")
        F.cell(t12, 1, 1, str(inp.nb_etages) if inp.nb_etages else "À confirmer", where="diapo 3 Table 12")
        F.cell(t12, 2, 1, inp.superficie_text or "À confirmer", where="diapo 3 Table 12")
        F.cell(t12, 3, 1, str(d["annee_construction"]) if d["annee_construction"] else "À confirmer", where="diapo 3 Table 12")
        F.cell(t12, 4, 1, inp.frais_energetiques_text or ("Propriétaire" if d["energie"] > 0 else "Locataires"), where="diapo 3 Table 12")
        F.cell(t12, 5, 1, inp.stationnements_text or (str(d["stationnements"]) if d["stationnements"] else "Aucun"), where="diapo 3 Table 12")


def _remplir_diapo_4(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    sh = F.shape(3, "TextBox 30")
    if sh is not None and sh.has_text_frame:
        tf = sh.text_frame
        bullets = [b for b in inp.bullets if b.strip()][:4]
        for i in range(4):
            F.para(tf, i, bullets[i] if i < len(bullets) else "", where="diapo 4 puces")
        phrase = inp.comparable_phrase.strip()
        url = inp.comparable_url.strip()
        F.runs(tf, 4, [f"{phrase} " if phrase else "", url], where="diapo 4 comparable")
        F.clear_paras(tf, 5)
    prix = d["prix"]
    comparable = _f(inp.valeur_comparable)
    valeur_refi = d["refi"]["valeur"]
    F.chart(3, "Chart 79", ["Avant", "Après refi"], [("PDM", [prix, valeur_refi or prix])])
    gain = comparable - prix if comparable > 0 else 0.0
    F.chart(3, "Chart 85", ["Valeur d'achat", "Valeur réelle"],
            [("Prix payé", [prix, prix]), ("Écart comparable", [0.0, max(gain, 0.0)])])
    if gain > 0:
        F.text(3, "TextBox 6", money(gain, signe=True))
    else:
        F.delete(3, "TextBox 6")
        F.delete(3, "Straight Arrow Connector 3", optional=True)


def _remplir_diapo_5(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    comparable = _f(inp.valeur_comparable)
    reference = comparable if comparable > 0 else d["prix"]
    t8 = F.table(4, "Table 8")
    if t8 is not None:
        F.cell(t8, 1, 1, money(d["loyer_moyen"]), where="diapo 5 Avant")
        F.cell(t8, 2, 1, money(d["revenus"]), where="diapo 5 Avant")
        F.cell(t8, 3, 1, f"{money(reference)} (payé {money_M(d['prix'])})" if comparable > 0 else money(d["prix"]), where="diapo 5 Avant")
        F.cell(t8, 4, 1, money(d["energie"]), where="diapo 5 Avant")
    t12 = F.table(4, "Table 12")
    if t12 is not None:
        F.cell(t12, 1, 1, money(d["refi"]["nouveau_loyer"]), where="diapo 5 Après")
        F.cell(t12, 2, 1, money(d["refi"]["nouveaux_revenus"]), where="diapo 5 Après")
        delta = d["refi"]["valeur"] - reference
        F.cell_runs(t12, 3, 1, [f"{money(d['refi']['valeur'])}  ", f"({money(delta, signe=True)})"], where="diapo 5 Après")
        F.cell(t12, 4, 1, money(d["energie_apres"]), where="diapo 5 Après")
    t18 = F.table(4, "Table 18")
    if t18 is not None:
        leviers = [x for x in inp.leviers if x.strip()] or ["📈 Optimisation des loyers", "🛠️ Rénovations ciblées", "💡 Réduction des dépenses", "🏅 Ajout de services"]
        positions = [(1, 0), (1, 1), (2, 0), (2, 1)]
        for i, (r, c) in enumerate(positions):
            F.cell(t18, r, c, leviers[i] if i < len(leviers) else "", where="diapo 5 leviers")


def _dates_jalons(inp: DeckInputs, d: Dict[str, Any]) -> Tuple[date, Dict[str, Tuple[date, str]]]:
    debut = _parse_date(inp.date_debut, date.today()).replace(day=1)  # type: ignore[union-attr]
    notaire = _add_months(debut, 3)
    duree = int(d["duree"] or 2)
    defauts = {
        "m1_1": (_add_months(debut, 2), "Lettre de financement"),
        "m1_2": (notaire, "Passage au notaire"),
        "m2_1": (_add_months(notaire, 3), "Ententes avec les locataires"),
        "m2_2": (_add_months(notaire, 6), "Fin des travaux majeurs"),
        "m2_3": (_add_months(notaire, 8), "Fin des travaux appartements"),
        "m2_4": (_add_months(notaire, 9), "Locations et stabilisation"),
        "m3_1": (_add_months(notaire, 12 * duree), "Remboursement des partenaires"),
    }
    out: Dict[str, Tuple[date, str]] = {}
    for k, (dd, lab) in defauts.items():
        j = inp.jalons.get(k)
        dj = _parse_date(j.date if j else None, dd) or dd
        dj = max(dj.replace(day=1), debut)
        out[k] = (dj, (j.label.strip() if j and j.label.strip() else lab))
    return debut, out


def _remplir_diapo_6(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    """Échéancier calculé : en-têtes, cases colorées, losanges / carrés /
    connecteurs placés par date, repère AUJOURD'HUI."""
    from pptx.util import Emu

    debut, jal = _dates_jalons(inp, d)
    m = {k: _mois_index(v[0], debut) for k, v in jal.items()}
    T = max(m["m3_1"], 8)
    for k in m:
        m[k] = min(max(m[k], 0), T)
    # 10 colonnes (c2..c11) : 7 mois, puis [7..a], [a+1..T-1], [T].
    a = max(7, m["m2_4"])
    if a >= T:
        a = max(7, T - 1)
    plages: List[Tuple[int, int]] = [(i, i) for i in range(7)]
    plages.append((7, a))
    plages.append((a + 1, T - 1))
    plages.append((T, T))

    def _mois(i: int) -> date:
        return _add_months(debut, i)

    def _libelle(p: Tuple[int, int], court: bool) -> str:
        s, e = p
        if e < s:
            return "—"
        ds, de = _mois(s), _mois(e)
        if s == e:
            return _MOIS_COURT[ds.month] if court else _fmt_mois(ds)
        if court:
            if ds.year != de.year:
                # Plage qui change d'année : « Nov 27 - Déc 28 ».
                return f"{_MOIS_COURT[ds.month]} {ds.year % 100} - {_MOIS_COURT[de.month]} {de.year % 100}"
            return f"{_MOIS_COURT[ds.month]} - {_MOIS_COURT[de.month]}"
        return f"{_fmt_mois(ds)} – {_fmt_mois(de)}"

    t1 = F.table(5, "Table 1")
    if t1 is None:
        return
    tbl = t1.table
    # Ligne 1 : mois par colonne.
    for i, p in enumerate(plages):
        F.cell(t1, 1, 2 + i, _libelle(p, True), where="diapo 6 mois")
    # Ligne 0 : groupes (c2-3, c4-5, c6-8, c9, c10-11).
    groupes = [(2, (0, 1)), (4, (2, 3)), (6, (4, 6)), (9, (7, 7)), (10, (8, 9))]
    for col, (i0, i1) in groupes:
        s = plages[i0][0]
        e = plages[i1][1]
        F.cell(t1, 0, col, _libelle((s, e), False) if e >= s else "", where="diapo 6 périodes")
    # Cases colorées : période par activité.
    periodes = {
        2: (0, m["m1_1"]),
        3: (m["m1_2"], m["m1_2"]),
        4: (m["m1_2"], m["m2_1"]),
        5: (m["m1_2"], m["m2_2"]),
        6: (m["m1_2"], m["m2_3"]),
        7: (m["m1_2"], m["m2_4"]),
        8: (T, T),
    }
    for row, (s, e) in periodes.items():
        for i, (ps, pe) in enumerate(plages):
            actif = pe >= ps and not (pe < s or ps > e)
            F.cell_fill(t1, row, 2 + i, _TEAL if actif else None)

    # Géométrie : colonnes et lignes rendues.
    x0 = t1.left
    col_x: List[int] = []
    acc = x0
    for c in tbl.columns:
        col_x.append(acc)
        acc += c.width
    col_w = [c.width for c in tbl.columns]
    n_rows = len(tbl.rows)
    row_h = t1.height / float(n_rows)
    y0 = t1.top

    def _x_mois(i: int) -> int:
        for ci, (ps, pe) in enumerate(plages):
            if pe >= ps and ps <= i <= pe:
                frac = (i - ps + 0.5) / float(pe - ps + 1)
                return int(col_x[2 + ci] + col_w[2 + ci] * frac)
        return int(col_x[11] + col_w[11] * 0.5)

    def _y_row(r: int) -> int:
        return int(y0 + row_h * (r + 0.5))

    def _place(name: str, cx: int, cy: int) -> Any:
        sh = F.shape(5, name)
        if sh is None:
            return None
        sh.left = int(cx - sh.width / 2)
        sh.top = int(cy - sh.height / 2)
        return sh

    def _label(name: str, diamond: Any) -> None:
        sh = F.shape(5, name)
        if sh is None or diamond is None:
            return
        largeur_diapo = F.prs.slide_width
        left = diamond.left + diamond.width + Emu(36000)
        if left + sh.width > largeur_diapo - Emu(180000):
            left = diamond.left - sh.width - Emu(36000)
        sh.left = int(left)
        sh.top = int(diamond.top + Emu(36000))

    def _connect(name: str, x_from: int, x_to: int, cy: int) -> None:
        sh = F.shape(5, name)
        if sh is None:
            return
        try:
            sh.begin_x, sh.begin_y, sh.end_x, sh.end_y = int(x_from), int(cy), int(x_to), int(cy)
        except Exception:  # noqa: BLE001
            sh.left, sh.top, sh.width, sh.height = int(x_from), int(cy), int(max(x_to - x_from, 0)), 0

    losanges = {
        "m1_1": ("Flowchart: Decision 34", "TextBox 46", 2),
        "m1_2": ("Flowchart: Decision 35", "TextBox 47", 3),
        "m2_1": ("Flowchart: Decision 36", "TextBox 45", 4),
        "m2_2": ("Flowchart: Decision 37", "TextBox 44", 5),
        "m2_3": ("Flowchart: Decision 38", "TextBox 43", 6),
        "m2_4": ("Flowchart: Decision 39", "TextBox 42", 7),
        "m3_1": ("Flowchart: Decision 40", "TextBox 41", 8),
    }
    placed: Dict[str, Any] = {}
    for k, (dname, lname, row) in losanges.items():
        sh = _place(dname, _x_mois(m[k]), _y_row(row))
        placed[k] = sh
        _label(lname, sh)
    carres = {
        "Rectangle 48": (2, 0, "Straight Connector 54", "m1_1"),
        "Rectangle 49": (4, m["m1_2"], "Straight Connector 57", "m2_1"),
        "Rectangle 50": (5, m["m1_2"], "Straight Connector 60", "m2_2"),
        "Rectangle 51": (6, m["m1_2"], "Straight Connector 66", "m2_3"),
        "Rectangle 52": (7, m["m1_2"], "Straight Connector 69", "m2_4"),
    }
    for sname, (row, mois_dep, cname, cible) in carres.items():
        sq = _place(sname, _x_mois(mois_dep), _y_row(row))
        diamond = placed.get(cible)
        if sq is not None and diamond is not None:
            x_from = sq.left + sq.width
            x_to = diamond.left
            if x_to < x_from:
                x_to = x_from
            _connect(cname, x_from, x_to, _y_row(row))

    # Repère AUJOURD'HUI.
    today = date.today()
    mi = _mois_index(today.replace(day=1), debut)
    ligne = F.shape(5, "Straight Connector 74")
    etiquette = F.shape(5, "TextBox 75")
    if 0 <= mi <= T and ligne is not None and etiquette is not None:
        # Position dans le mois (jour / 30) à l'intérieur de sa colonne.
        for ci, (ps, pe) in enumerate(plages):
            if pe >= ps and ps <= mi <= pe:
                frac = (mi - ps + min(today.day, 30) / 31.0) / float(pe - ps + 1)
                x = int(col_x[2 + ci] + col_w[2 + ci] * frac)
                break
        else:
            x = _x_mois(mi)
        try:
            ligne.begin_x, ligne.end_x = x, x
        except Exception:  # noqa: BLE001
            ligne.left = x
        etiquette.left = int(x - etiquette.width / 2)
    else:
        F.delete(5, "Straight Connector 74", optional=True)
        F.delete(5, "TextBox 75", optional=True)

    # Tableaux de jalons.
    t6 = F.table(5, "Table 6")
    if t6 is not None:
        F.cell(t6, 1, 0, f"M1.1 – {_fmt_mois(jal['m1_1'][0])}", where="diapo 6 jalons")
        F.cell(t6, 1, 1, jal["m1_1"][1], where="diapo 6 jalons")
        F.cell(t6, 2, 0, f"M1.2 – {_fmt_mois(jal['m1_2'][0])}", where="diapo 6 jalons")
        F.cell(t6, 2, 1, jal["m1_2"][1], where="diapo 6 jalons")
    t12 = F.table(5, "Table 12")
    if t12 is not None:
        for i, k in enumerate(["m2_1", "m2_2", "m2_3", "m2_4"], start=1):
            F.cell(t12, i, 0, f"M2.{i} – {_fmt_mois(jal[k][0])}", where="diapo 6 jalons")
            F.cell(t12, i, 1, jal[k][1], where="diapo 6 jalons")
    t21 = F.table(5, "Table 21")
    if t21 is not None:
        F.cell(t21, 1, 0, f"M3.1 – {_fmt_mois(jal['m3_1'][0])}", where="diapo 6 jalons")
        F.cell(t21, 1, 1, jal["m3_1"][1], where="diapo 6 jalons")


def _remplir_diapo_7(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    texte = {
        "preteur_b": "Financement prêteur B",
        "traditionnel": "Financement institutionnel",
        "residentiel": "Financement résidentiel",
        "assumation": "Assumation de l'hypothèque",
    }.get(d["strategie"], "Financement conventionnel")
    F.text(6, "TextBox 3", texte, para_idx=3)


def _remplir_diapo_8(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    t2 = F.table(7, "Table 2")
    if t2 is None:
        return
    w = "diapo 8 Table 2"
    F.cell(t2, 2, 1, money(d["prix"]), where=w)
    F.cell(t2, 3, 1, money(d["frais_total"]), where=w)
    F.cell(t2, 4, 1, str(d["nb_log"]), where=w)
    F.cell(t2, 5, 1, money(d["revenus"]), where=w)
    F.cell(t2, 6, 1, money(d["loyer_moyen"]), where=w)
    F.cell(t2, 7, 1, pct(d["taux_achat"], 2), where=w)
    for i, (label, val) in enumerate(d["depenses_lignes"]):
        F.cell(t2, 2 + i, 3, label, where=w)
        F.cell(t2, 2 + i, 4, money(val), where=w)
    F.cell(t2, 2, 7, d["strategie_label"], where=w)
    F.cell(t2, 3, 7, pct(d["ltv_achat"]), where=w)
    F.cell(t2, 4, 7, d["rcd_achat"], where=w)
    F.cell(t2, 5, 7, money(d["revenus_net_achat"]), where=w)
    F.cell(t2, 6, 7, d["type_pret"], where=w)
    F.cell(t2, 7, 7, money(d["valeur_eco_achat"]), where=w)
    F.cell(t2, 8, 7, money(d["pret_max"]), where=w)
    F.cell(t2, 9, 7, money(d["mdf"]), where=w)
    F.cell(t2, 10, 7, money(d["fonds_necessaires"]), where=w)
    F.text(7, "TextBox 15", d["strategie_label"])
    F.text(7, "TextBox 16", money(d["valeur_eco_achat"]))
    F.text(7, "TextBox 17", money(d["pret_max"]))
    F.text(7, "TextBox 18", money(d["fonds_necessaires"]))
    F.text(7, "Speech Bubble: Oval 38", f"Récupérés en {d['h0']} ans")
    bv = d["balance_vente"]
    if bv > 0:
        F.text(7, "Rectangle 1",
               f"Balance de vente de {money(bv)} qui fait passer l'investissement de "
               f"{money_k(d['fonds_necessaires'] + bv)} à {money_k(d['fonds_necessaires'])}!")
    else:
        F.delete(7, "Rectangle 1")


def _remplir_diapo_9(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    t2 = F.table(8, "Table 2")
    if t2 is None:
        return
    w = "diapo 9 Table 2"
    n_rows = len(t2.table.rows)
    style_item = dict(bold=False, size=10, color=_BLANC)
    style_total = dict(bold=True, size=10, color=_JAUNE)
    style_note = dict(bold=False, size=8, color=_BLANC)

    # Rénovations (colonnes 0/1) : items puis Total puis note.
    renos = [r for r in inp.renovations if r.strip()]
    max_items = n_rows - 4
    if len(renos) > max_items:
        renos = renos[: max_items - 1] + [f"+ {len(renos) - (max_items - 1)} autres postes"]
    for r in range(2, n_rows):
        F.cell_clear(t2, r, 0)
        F.cell_clear(t2, r, 1)
    for i, label in enumerate(renos):
        F.cell(t2, 2 + i, 0, label, where=w, **style_item)
    rt = 2 + len(renos)
    F.cell(t2, rt, 0, " Total", where=w, **style_total)
    F.cell(t2, rt, 1, money(d["travaux"]), where=w, **style_total)
    F.cell(t2, rt + 1, 0, "***Certains frais financés", where=w, **style_note)

    # Développement (colonnes 3/4).
    F.cell(t2, 2, 4, money(d["dev"]), where=w)
    F.cell(t2, 3, 4, money(d["nego"]), where=w)
    F.cell(t2, 4, 4, money(d["dev"] + d["nego"]), where=w)

    # Frais autres (colonnes 6/7) : postes puis Total puis note.
    postes = list(d["frais_autres"])
    max_postes = n_rows - 4
    if len(postes) > max_postes:
        tete = sorted(postes, key=lambda x: -abs(x[1]))[: max_postes - 1]
        reste = [p for p in postes if p not in tete]
        postes = [p for p in postes if p in tete] + [("Autres postes", sum(v for _l, v in reste))]
    for r in range(2, n_rows):
        F.cell_clear(t2, r, 6)
        F.cell_clear(t2, r, 7)
    for i, (label, val) in enumerate(postes):
        F.cell(t2, 2 + i, 6, label, where=w, **style_item)
        F.cell(t2, 2 + i, 7, money(val), where=w, **style_item)
    ft = 2 + len(postes)
    F.cell(t2, ft, 6, "Total", where=w, **style_total)
    F.cell(t2, ft, 7, money(d["frais_autres_total"]), where=w, **style_total)
    F.cell(t2, ft + 1, 6, "***Certains frais financés", where=w, **style_note)
    F.text(8, "TextBox 8", money(d["frais_total"]))


def _remplir_diapo_10(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    r = d["refi"]
    t2 = F.table(9, "Table 2")
    if t2 is None:
        return
    w = "diapo 10 Table 2"
    F.cell(t2, 1, 0, f"Informations financières ({r['label']})", where=w)
    F.cell(t2, 2, 1, money(r["depenses"]), where=w)
    F.cell(t2, 3, 1, money(r["nouveau_loyer"]), where=w)
    F.cell(t2, 4, 1, money(r["nouveaux_revenus"]), where=w)
    F.cell(t2, 5, 1, str(r["nb_log"]), where=w)
    F.cell(t2, 6, 1, "OUI" if r["wifi"] else "NON", where=w)
    F.cell(t2, 7, 1, f"OUI ({r['nb_thermo']})" if r["nb_thermo"] > 0 else "NON", where=w)
    F.cell(t2, 8, 1, pct(r["reduction_energie"]), where=w)
    F.cell(t2, 9, 1, pct(d["taux_refi"], 2), where=w)
    for col, s in ((4, r["scenario_1"]), (7, r["scenario_2"])):
        F.cell(t2, 2, col, s["label"], where=w)
        F.cell(t2, 3, col, s["ltv"], where=w)
        F.cell(t2, 4, col, s["rcd"], where=w)
        F.cell(t2, 5, col, s["revenus_net"], where=w)
        F.cell(t2, 6, col, s["amort"], where=w)
        F.cell(t2, 7, col, s["valeur"], where=w)
        F.cell(t2, 8, col, s["pret"], where=w)
        F.cell(t2, 9, col, s["equite"], where=w)
    F.text(9, "TextBox 15", r["titre"])
    F.text(9, "TextBox 16", money(r["valeur"]), para_idx=1)
    F.text(9, "TextBox 17", money(r["pret"]), para_idx=1)
    F.text(9, "TextBox 18", money(r["equite"]), para_idx=1)
    F.text(9, "TextBox 26", r["sous_titre"] or r["label"], para_idx=1)


def _remplir_diapo_11(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    hz = d["tri"]["horizons"]
    cap = d["tri"]["capital"]
    F.text(10, "TextBox 80", f"Année {hz[0]['annee']}")
    F.text(10, "TextBox 6", f"Année {hz[1]['annee']}")
    F.text(10, "TextBox 9", f"Année {hz[2]['annee']}")
    t83 = F.table(10, "Table 83")
    if t83 is None:
        return
    w = "diapo 11 Table 83"
    F.cell(t83, 0, 1, money(cap), where=w)
    F.cell(t83, 2, 1, "0$", where=w)
    F.cell(t83, 4, 1, money(cap), where=w)
    F.cell(t83, 6, 1, money(cap), where=w)
    F.cell(t83, 8, 1, "—", where=w)
    tf = t83.table.cell(4, 0).text_frame
    F.runs(tf, 1, [" ", f"({pct(d['tri']['pct'])} des parts)"], where=w)
    for i, h in enumerate(hz):
        c = 2 + i
        F.cell(t83, 0, c, "0$", where=w)
        F.cell(t83, 2, c, money(h["cash"]), where=w)
        F.cell(t83, 4, c, money(h["parts"]), where=w)
        F.cell(t83, 6, c, money(h["patrimoine"]), where=w)
        F.cell(t83, 8, c, "n/d" if h["tri"] is None else pct(h["tri"], 1), where=w)


def _remplir_diapo_12(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    ville = (inp.tendances_secteur or d["ville"] or "Montréal").strip()
    F.text(11, "Title 1", f"TENDANCES — {ville.upper()}")
    avant = d["loyer_moyen"]
    apres = d["refi"]["nouveau_loyer"]
    hausse = (apres / avant - 1.0) if avant > 0 else 0.0
    F.chart(11, "Chart 20", ["Année 0", f"Année {d['h0']}"], [("PDM", [avant, apres])],
            title=f"Croissance projetée de la moyenne locative (+{int(round(hausse * 100))} % en {d['h0']} ans)")
    source = (inp.tendances_source or "Zipplex").strip()
    F.text(11, "TextBox 25", f"{source} — secteur {ville}")
    delta = apres - avant
    F.text(11, "Speech Bubble: Oval 27", money(int(round(delta / 100.0)) * 100, signe=True))


def _remplir_diapo_13(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    hz = d["tri"]["horizons"]
    cap = d["tri"]["capital"]
    cumul_cash = sum(h["cash"] for h in hz)
    F.chart(
        12, "Chart 6",
        ["Année 0", f"Année {hz[0]['annee']}", f"Année {hz[2]['annee']}"],
        [
            ("Capital investi/recupéré", [-cap, hz[0]["cash"], cumul_cash]),
            ("Équité dans l'immeuble", [cap, hz[0]["equite"], hz[2]["equite"]]),
            ("Valeurs de l'immeubles", [d["prix"], hz[0]["valeur"], hz[2]["valeur"]]),
        ],
    )
    F.text(12, "TextBox 47", f"Après {d['h0']} ans, l'immeuble s'autofinance entièrement et continue de prendre de la valeur avec le temps.", para_idx=1)


def _remplir_diapo_14(F: _Filler, d: Dict[str, Any], inp: DeckInputs) -> None:
    sh = F.shape(13, "TextBox 20")
    if sh is not None and sh.has_text_frame:
        F.runs(sh.text_frame, 0, ["Marge de contingence ", f"{int(round(_f(inp.contingence_pct) or 10))}%"], where="diapo 14 contingence")
    F.text(13, "TextBox 10", f"{int(_f(inp.fonds_roulement_mois) or 4)} mois", para_idx=1)


# ─── API publique ─────────────────────────────────────────────────────


def template_path() -> Path:
    return TEMPLATE_DIR / f"{TEMPLATE_VERSION}.pptx"


def get_renovations_catalogue() -> List[str]:
    return list(RENOVATIONS_CATALOGUE)


def photo_slots() -> List[Dict[str, Any]]:
    return [{"key": k, "slide": idx + 1, "label": label} for k, idx, _n, label in PHOTO_SLOTS]


async def preparer_deck(db: Any, rec: Any, inputs_partiels: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Résultats + TRI + intrants proposés (pour l'assistant et la
    génération). Lève ``ValueError`` si l'analyse n'a pas tourné."""
    res = _charger_resultats(rec)
    inp_part = inputs_partiels or {}
    tri = await _tri_pour_deck(db, rec, res, inp_part.get("investissement_requis"), inp_part.get("pct_parts"))
    d = construire_donnees(rec, res, tri)
    inp = proposer_intrants(rec, d, inp_part)
    # Le capital / % affichés et imprimés sont ceux retenus.
    d["tri"]["capital"] = _f(tri.get("capital"))
    d["tri"]["pct"] = _f(tri.get("pct"))
    return {"donnees": d, "inputs": inp, "tri": tri, "resultats": res}


async def generer_deck(
    db: Any,
    rec: Any,
    inputs: Optional[Dict[str, Any]] = None,
    photos: Optional[Dict[str, bytes]] = None,
) -> Tuple[bytes, Dict[str, Any]]:
    """Génère le .pptx. Retourne ``(octets, meta)`` ; ``meta['misses']``
    liste les cibles du gabarit introuvables (vide = tout rempli)."""
    from pptx import Presentation

    chemin = template_path()
    if not chemin.exists():
        raise ValueError(f"Gabarit introuvable : {chemin}")
    prep = await preparer_deck(db, rec, inputs)
    d, inp = prep["donnees"], prep["inputs"]
    prs = Presentation(str(chemin))
    F = _Filler(prs)
    for fn in (
        _remplir_diapo_1, _remplir_diapo_2, _remplir_diapo_3, _remplir_diapo_4, _remplir_diapo_5,
        _remplir_diapo_6, _remplir_diapo_7, _remplir_diapo_8, _remplir_diapo_9, _remplir_diapo_10,
        _remplir_diapo_11, _remplir_diapo_12, _remplir_diapo_13, _remplir_diapo_14,
    ):
        try:
            fn(F, d, inp)
        except Exception as exc:  # noqa: BLE001
            log.exception("Deck : %s a échoué", fn.__name__)
            F.misses.append(f"{fn.__name__} : {type(exc).__name__}: {str(exc)[:160]}")
    photos_ok: List[str] = []
    for key, idx, name, _label in PHOTO_SLOTS:
        blob = (photos or {}).get(key)
        if blob:
            if F.picture(idx, name, blob):
                photos_ok.append(key)
    out = io.BytesIO()
    prs.save(out)
    meta = {
        "template_version": TEMPLATE_VERSION,
        "service_version": SERVICE_VERSION,
        "misses": list(F.misses),
        "remplis": F.remplis,
        "photos": photos_ok,
        "apercu": apercu(d),
    }
    if F.misses:
        log.warning("Deck %s : %d cible(s) manquée(s) — %s", getattr(rec, "id", "?"), len(F.misses), "; ".join(F.misses[:8]))
    return out.getvalue(), meta
