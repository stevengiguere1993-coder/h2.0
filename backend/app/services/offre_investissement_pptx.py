"""Génère un .pptx d'offre d'investissement Horizon depuis une
`LeadAnalysis` + un input humain de stratégie value-add.

Approche :
    * Le template `horizon_v1.pptx` est une copie du deck 1660 Saint-Clément.
      Les valeurs littérales (montants, phrases, %, ...) servent de
      "placeholders" identifiables — une chaîne dans le template = une
      variable du mapping `horizon_v1.mapping.json`.
    * On effectue une substitution `string.replace` au niveau des runs et
      cellules de tableau pour préserver polices, couleurs, charts, layout.
    * Les variables sont catégorisées en 3 sources :
        - `auto`     : extrait direct de `LeadAnalysis` (~30 champs)
        - `hybrid`   : recalculé depuis le moteur d'analyse financière +
                       inputs value-add (loyers projetés, AT/RT, etc.)
        - `human`    : saisi par l'utilisateur dans le wizard (tagline,
                       bullets opportunité, libellés)
    * Les photos remplacent les blobs existants en gardant le rectangle.

Limites MVP :
    * Les recalculs hybrides utilisent les RÉSULTATS DÉJÀ PERSISTÉS dans
      `analysis_results_json` (le run-financial-analysis le plus récent)
      + des ajustements simples pour les value-add (nouveau loyer moyen,
      revenus, RCI/PVI). Pas de recalcul temps-réel du moteur SCHL/APH —
      réservé pour Phase 2.
    * Une seule template (Horizon v1). Aucune variation par typologie.
    * Pas de génération de charts dynamiques (les charts du template
      restent en l'état — visuellement cohérents pour les ordres de
      grandeur similaires).
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_analysis import LeadAnalysis, LeadAnalysisAttachment


log = logging.getLogger(__name__)


_TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent
    / "templates"
    / "offre_investissement"
)
_TEMPLATE_PATH = _TEMPLATE_DIR / "horizon_v1.pptx"
_MAPPING_PATH = _TEMPLATE_DIR / "horizon_v1.mapping.json"


# ─── Formatters ─────────────────────────────────────────────────────


def _money_long(n: Optional[float]) -> str:
    """Ex: `1 200 000$`."""
    if n is None:
        return "—"
    rounded = int(round(n))
    sign = "-" if rounded < 0 else ""
    abs_str = str(abs(rounded))
    with_sep = re.sub(r"\B(?=(\d{3})+(?!\d))", " ", abs_str)
    return f"{sign}{with_sep}$"


def _money_long_with_space(n: Optional[float]) -> str:
    """Ex: `2 449 959 $` (espace avant $)."""
    return _money_long(n)[:-1] + " $"


def _money_long_lead_space(n: Optional[float]) -> str:
    """Ex: ` 2 465 059$` (espace devant — comme dans le template)."""
    return " " + _money_long(n)


def _money_short(n: Optional[float]) -> str:
    """Ex: `1800$`."""
    if n is None:
        return "—"
    return f"{int(round(n))}$"


def _money_an(n: Optional[float]) -> str:
    """Ex: `91 500 $/an`."""
    if n is None:
        return "—"
    rounded = int(round(n))
    abs_str = str(abs(rounded))
    with_sep = re.sub(r"\B(?=(\d{3})+(?!\d))", " ", abs_str)
    sign = "-" if rounded < 0 else ""
    return f"{sign}{with_sep} $/an"


def _money_plus(n: Optional[float]) -> str:
    """Ex: `+ 497 100$`."""
    if n is None:
        return "—"
    return f"+ {_money_long(n)}"


def _money_short_M(n: Optional[float]) -> str:
    """Ex: `1,2 M$` (1 décimale) pour les montants en millions."""
    if n is None:
        return "—"
    val_m = n / 1_000_000.0
    s = f"{val_m:.1f}".rstrip("0").rstrip(".")
    if not s or s == "-":
        s = "0"
    return f"{s.replace('.', ',')} M$"


def _money_approx_M(n: Optional[float]) -> str:
    """Ex: `~1,68 M$` (2 décimales)."""
    if n is None:
        return "—"
    val_m = n / 1_000_000.0
    return f"~{val_m:.2f}".replace(".", ",") + " M$"


def _money_with_delta(value: Optional[float], delta: Optional[float]) -> str:
    """Ex: `2 882 305$  (+1 685 305$)`."""
    if value is None:
        return "—"
    base = _money_long(value)
    if delta is None:
        return base
    sign = "+" if delta >= 0 else ""
    return f"{base}  ({sign}{_money_long(delta)})"


def _money_payed(value: Optional[float], paid_M: Optional[float]) -> str:
    """Ex: `1 697 100$ (payé 1.2M)`."""
    base = _money_long(value)
    if paid_M is None:
        return base
    paid_s = f"{paid_M / 1_000_000.0:.1f}".rstrip("0").rstrip(".")
    return f"{base} (payé {paid_s}M)"


def _percent_approx(n: Optional[float]) -> str:
    """Ex: `~121 %`."""
    if n is None:
        return "—"
    return f"~{int(round(n))} %"


def _percent_2(n: Optional[float]) -> str:
    """Ex: `8,00%`."""
    if n is None:
        return "—"
    return f"{n:.2f}".replace(".", ",") + "%"


def _percent_2_fr(n: Optional[float]) -> str:
    """Ex: `3,75%`."""
    if n is None:
        return "—"
    s = f"{n:.2f}".rstrip("0").rstrip(".")
    return f"{s.replace('.', ',')}%"


def _percent_0(n: Optional[float]) -> str:
    """Ex: `100%`."""
    if n is None:
        return "—"
    return f"{int(round(n))}%"


# ─── Input dataclass ────────────────────────────────────────────────


@dataclass
class ValueAddStrategy:
    """Inputs humains du wizard (tagline + bullets + flags value-add)."""

    tagline_cover: str = ""
    bullet_opp_1: str = ""
    bullet_opp_2: str = ""
    bullet_opp_3: str = ""
    bullet_opp_4: str = ""

    conversion_chambres: bool = False
    nb_chambres_total: int = 0
    loyer_par_chambre: float = 0.0

    conversion_chauffage: str = "aucun"  # aucun | gaz_to_elec | elec_to_thermo
    ajout_logement_type: str = ""  # ex: "3.5"
    ajout_logement_loyer: float = 0.0
    optimisation_loyers_std: bool = True

    programme_schl: str = "aph_50"  # aph_50 | aph_100 | aucun

    ajout_thermopompes: int = 0
    ajout_wifi: bool = False

    liste_renovations: str = ""

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "ValueAddStrategy":
        if not d:
            return cls()
        return cls(
            tagline_cover=str(d.get("tagline_cover", "") or "")[:200],
            bullet_opp_1=str(d.get("bullet_opp_1", "") or "")[:200],
            bullet_opp_2=str(d.get("bullet_opp_2", "") or "")[:200],
            bullet_opp_3=str(d.get("bullet_opp_3", "") or "")[:200],
            bullet_opp_4=str(d.get("bullet_opp_4", "") or "")[:200],
            conversion_chambres=bool(d.get("conversion_chambres", False)),
            nb_chambres_total=int(d.get("nb_chambres_total", 0) or 0),
            loyer_par_chambre=float(d.get("loyer_par_chambre", 0) or 0),
            conversion_chauffage=str(
                d.get("conversion_chauffage", "aucun") or "aucun"
            ),
            ajout_logement_type=str(d.get("ajout_logement_type", "") or ""),
            ajout_logement_loyer=float(d.get("ajout_logement_loyer", 0) or 0),
            optimisation_loyers_std=bool(
                d.get("optimisation_loyers_std", True)
            ),
            programme_schl=str(d.get("programme_schl", "aph_50") or "aph_50"),
            ajout_thermopompes=int(d.get("ajout_thermopompes", 0) or 0),
            ajout_wifi=bool(d.get("ajout_wifi", False)),
            liste_renovations=str(d.get("liste_renovations", "") or "")[:5000],
        )


# ─── Build context ──────────────────────────────────────────────────


def _typology_compact(typology_json: Optional[str]) -> str:
    """`{'3.5':2,'4.5':4}` → `2x3½ | 4x4½`."""
    if not typology_json:
        return ""
    try:
        d = json.loads(typology_json)
    except Exception:
        return ""
    parts = []
    for k in ("1.5", "2.5", "3.5", "4.5", "5.5", "6.5", "7.5", "8.5"):
        v = int(d.get(k, 0) or 0)
        if v > 0:
            half = "½" if k.endswith(".5") else ""
            integer = k.split(".")[0]
            parts.append(f"{v}x{integer}{half}")
    return " | ".join(parts)


def _typology_nb_vacants(typology_json: Optional[str]) -> int:
    """Nombre estimé de logements vacants — placeholder pour MVP."""
    return 0


def _full_address(rec: LeadAnalysis) -> str:
    bits: list[str] = []
    if rec.address:
        bits.append(rec.address.strip())
    if rec.city:
        bits.append(rec.city.strip())
    return ", ".join(bits) if bits else "Adresse à confirmer"


def _best_refi_scenario(results: Optional[dict]) -> Optional[dict]:
    """Retourne le scénario de refi qui a donné le best_refi (équité max)."""
    if not results:
        return None
    scenarios = results.get("scenarios") or {}
    program = (results.get("best_refi") or {}).get("program") or ""
    # Map program label → scenario key
    mapping = {
        "SCHL standard": "refi_schl",
        "SCHL Efficacité énergétique (50 pts)": "refi_aph_50",
        "SCHL Abordabilité + Efficacité (100 pts)": "refi_aph_100",
    }
    key = mapping.get(program, "refi_aph_50")
    return scenarios.get(key) or scenarios.get("refi_aph_50") or scenarios.get(
        "refi_schl"
    )


def _calc_value_add(
    rec: LeadAnalysis, strat: ValueAddStrategy
) -> Dict[str, float]:
    """Calcule les agrégats value-add à partir des inputs humains et auto.

    Renvoie : nouveau_loyer_moyen, nouveaux_revenus_an, nouvelle_valeur_marchande,
    delta_revenus_an, delta_valeur_marchande.

    Stratégie MVP simplifiée : on prend l'`analysis_results_json` du run le
    plus récent comme source de vérité (déjà calculé par le moteur). Si pas
    présent, on utilise les loyers projetés JSON du lead.
    """
    results = None
    if rec.analysis_results_json:
        try:
            results = json.loads(rec.analysis_results_json)
        except Exception:
            results = None

    nb_log = int(rec.nb_logements or 0) + (
        1 if strat.ajout_logement_type else 0
    )
    revenus_actuels = float(rec.revenus_bruts or 0)
    loyer_moyen_actuel = (
        revenus_actuels / 12.0 / nb_log
        if nb_log > 0 and revenus_actuels > 0
        else 0.0
    )

    # Try to get the typology aggregates from the engine results first
    nouveau_loyer_moyen = 0.0
    if results:
        typo = results.get("typology") or {}
        nouveau_loyer_moyen = float(typo.get("h13_loyer_pondere", 0) or 0)
        # Fallback to best refi scenario loyer_mois
        if not nouveau_loyer_moyen:
            best = _best_refi_scenario(results)
            if best:
                nouveau_loyer_moyen = float(best.get("loyer_mois", 0) or 0)

    if not nouveau_loyer_moyen:
        # Heuristic from value-add inputs (MVP fallback)
        if strat.conversion_chambres and strat.loyer_par_chambre > 0:
            nouveau_loyer_moyen = strat.loyer_par_chambre * max(
                1, strat.nb_chambres_total // max(1, nb_log)
            )
        else:
            nouveau_loyer_moyen = loyer_moyen_actuel * 1.5

    nouveaux_revenus_an = 0.0
    if results:
        best = _best_refi_scenario(results)
        if best:
            nouveaux_revenus_an = float(best.get("revenus_totaux", 0) or 0)
    if not nouveaux_revenus_an:
        nouveaux_revenus_an = nouveau_loyer_moyen * 12.0 * nb_log

    # Nouvelle valeur marchande = valeur_retenue du best refi
    nouvelle_valeur_marchande = 0.0
    ancienne_valeur_marchande = 0.0
    if results:
        scenarios = results.get("scenarios") or {}
        achat = scenarios.get("achat") or {}
        ancienne_valeur_marchande = float(achat.get("valeur_retenue", 0) or 0)
        best = _best_refi_scenario(results)
        if best:
            nouvelle_valeur_marchande = float(
                best.get("valeur_retenue", 0) or 0
            )

    delta_revenus_an = nouveaux_revenus_an - revenus_actuels
    delta_valeur = nouvelle_valeur_marchande - ancienne_valeur_marchande

    # RCI / PVI from results
    rci_pct = 0.0
    pvi_montant = 0.0
    if results:
        best_amount = float((results.get("best_refi") or {}).get("amount", 0) or 0)
        mdf_preteur_b = float(results.get("mdf_preteur_b", 0) or 0)
        # Équité dégagée vs MDF investi → RCI %
        if mdf_preteur_b > 0:
            rci_pct = (best_amount / mdf_preteur_b) * 100.0
        pvi_montant = delta_valeur

    return {
        "nb_log": nb_log,
        "loyer_moyen_actuel": loyer_moyen_actuel,
        "nouveau_loyer_moyen": nouveau_loyer_moyen,
        "revenus_actuels_an": revenus_actuels,
        "nouveaux_revenus_an": nouveaux_revenus_an,
        "ancienne_valeur_marchande": ancienne_valeur_marchande,
        "nouvelle_valeur_marchande": nouvelle_valeur_marchande,
        "delta_revenus_an": delta_revenus_an,
        "delta_valeur": delta_valeur,
        "rci_pct": rci_pct,
        "pvi_montant": pvi_montant,
    }


def _build_substitutions(
    rec: LeadAnalysis,
    strat: ValueAddStrategy,
) -> Dict[str, Tuple[List[str], List[str]]]:
    """Construit le dict { find_str -> (var_value, dupe_strategy) }.

    Retourne en réalité une liste (find, replace, dupe_strategy) sous forme
    de tuple (filtrée plus tard pour ne pas substituer si replace == find).
    """
    va = _calc_value_add(rec, strat)
    results = None
    if rec.analysis_results_json:
        try:
            results = json.loads(rec.analysis_results_json)
        except Exception:
            results = None

    # Achat scenario (for slide 8 = depenses + financement)
    achat = (results or {}).get("scenarios", {}).get("achat", {}) or {}
    aph50 = (results or {}).get("scenarios", {}).get("refi_aph_50", {}) or {}
    aph100 = (results or {}).get("scenarios", {}).get("refi_aph_100", {}) or {}

    asking = float(rec.asking_price or 0)
    revenus = float(rec.revenus_bruts or 0)
    nb_log_actuel = int(rec.nb_logements or 0)

    # Phrase typologie compacte
    compact = _typology_compact(rec.typology_json)
    nb_vacants = _typology_nb_vacants(rec.typology_json)

    address_full = _full_address(rec)

    # Inputs financiers achat (depenses breakdown)
    achat_dep = achat.get("depenses", {}) or {}

    investissement_requis_val = float(rec.mdf_preteur_b or va.get("delta_valeur", 0) or 0)
    if not investissement_requis_val and results:
        investissement_requis_val = float(
            results.get("mdf_preteur_b", 0) or 0
        )
    fonds_necessaires_achat_val = investissement_requis_val

    frais_demarrage_total = 0.0
    if results:
        frais_demarrage_total = float(
            results.get("frais_demarrage_total", 0) or 0
        )

    pret_max_achat = float(achat.get("financement", 0) or asking * 0.75)
    mdf_achat = max(0.0, asking - pret_max_achat) if asking else 0.0

    # APH 50/100 specifics
    revenus_nets_aph50 = float(aph50.get("revenus_net", 0) or 0)
    revenus_nets_aph100 = float(aph100.get("revenus_net", 0) or 0)
    valeur_eco_aph50 = float(aph50.get("valeur_retenue", 0) or 0)
    valeur_eco_aph100 = float(aph100.get("valeur_retenue", 0) or 0)
    pret_max_aph50 = float(aph50.get("financement", 0) or 0)
    pret_max_aph100 = float(aph100.get("financement", 0) or 0)
    equite_aph50 = max(0.0, pret_max_aph50 - pret_max_achat)
    equite_aph100 = max(0.0, pret_max_aph100 - pret_max_achat)
    depenses_operations_refi = float(aph50.get("revenus_totaux", 0) or 0) - revenus_nets_aph50

    # WiFi / Thermopompes lines for slide 10
    if strat.ajout_wifi or rec.ajout_wifi:
        ligne_wifi = "OUI"
    else:
        ligne_wifi = "NON"
    if strat.ajout_thermopompes or (rec.nb_thermopompes_ajoutees or 0):
        ligne_thermopompes = f"OUI ({strat.ajout_thermopompes or rec.nb_thermopompes_ajoutees})"
    else:
        ligne_thermopompes = "NON"

    reduction_energie = float(
        strat.conversion_chauffage == "elec_to_thermo" and 100
        or (rec.reduction_energie_pct or 0)
    )

    # Bourse projection (S&P 10% annualisé)
    valeur_annee_2 = investissement_requis_val * (1.10 ** 2)
    valeur_annee_10 = investissement_requis_val * (1.10 ** 10)
    equite_an2_court = pret_max_aph50 - asking if asking else 0

    # Tagline + bullets fallbacks
    quartier = (rec.city or "le secteur").strip()
    tagline = (
        strat.tagline_cover
        or f"De l'achat au refinancement : un projet immobilier solide à {quartier}"
    )
    bullets = [
        strat.bullet_opp_1
        or (
            f"Offre d'achat acceptée sous la valeur municipale"
            if rec.evaluation_municipale and asking < float(rec.evaluation_municipale)
            else "Acquisition à fort potentiel d'optimisation"
        ),
        strat.bullet_opp_2
        or f"Loyers moyens actuels {_money_short(va['loyer_moyen_actuel'])} | "
        f"Cible {_money_short(va['nouveau_loyer_moyen'])}",
        strat.bullet_opp_3
        or "Marge significative de création de valeur via optimisation",
        strat.bullet_opp_4
        or f"Demande forte | Secteur {quartier}",
    ]

    # Phrase d'immeuble
    phrase_immeuble = f"Immeuble de {nb_log_actuel} logements" if nb_log_actuel else "Immeuble multilogements"
    nb_logements_phrase = f"{nb_log_actuel} logements" if nb_log_actuel else "—"
    if compact:
        phrase_typologie = f"{nb_log_actuel} logements\n {compact}\n{nb_vacants} vacants"
    else:
        phrase_typologie = f"{nb_log_actuel} logements"

    paid_M = (asking / 1_000_000.0) if asking else None

    # Construct substitutions list — each entry: (find, replace, dupe_strategy)
    # dupe_strategy: "first" (only first occurrence) | "all" (all occurrences)
    out: List[Tuple[int, str, str, str]] = [
        # Slide 0
        (0, "De l’achat au refinancement : un projet immobilier solide à Hochelaga-Maisonneuve", tagline, "first"),
        (0, "1660 Rue Saint-Clément, Montréal", address_full, "all"),
        # Slide 1
        (1, "1660 Rue Saint-Clément, Montréal", address_full, "first"),
        (1, "Immeuble de 8 logements", phrase_immeuble, "first"),
        (1, "675 000$", _money_long(investissement_requis_val), "first"),
        (1, "~121 %", _percent_approx(va["rci_pct"]), "first"),
        (1, "~1,68 M$", _money_approx_M(va["pvi_montant"]), "first"),
        # Slide 2
        (2, "1,2 M$", _money_short_M(asking), "first"),
        (2, "91 500 $/an", _money_an(revenus), "first"),
        (2, "171 600 $/an", _money_an(va["nouveaux_revenus_an"]), "first"),
        (2, "8 logements\n 2 × 3½ | 4 × 4½ | 1 × 5½ | 1 × 7½\n2 vacants", phrase_typologie, "first"),
        (2, "8 logements", nb_logements_phrase, "first"),
        # Slide 3
        (3, "Offre d’achat acceptée 29% sous la valeur municipale", bullets[0], "first"),
        (3, "Loyers moyens actuels 953$ | Marché 1800$", bullets[1], "first"),
        (3, "+ 94% de manque à gagner en convertissant en chambres", bullets[2], "first"),
        (3, "Demande pour chambres en forte hausse | Secteur Hochelaga", bullets[3], "first"),
        (3, "+ 497 100$", _money_plus(va["delta_revenus_an"]), "first"),
        # Slide 4
        (4, "1800$", _money_short(va["nouveau_loyer_moyen"]), "first"),
        (4, "171 600$", _money_long(va["nouveaux_revenus_an"]), "first"),
        (4, "2 882 305$  (+1 685 305$)", _money_with_delta(va["nouvelle_valeur_marchande"], va["delta_valeur"]), "first"),
        (4, "953$", _money_short(va["loyer_moyen_actuel"]), "first"),
        (4, "91 500$", _money_long(revenus), "first"),
        (4, "1 697 100$ (payé 1.2M)", _money_payed(va["ancienne_valeur_marchande"], paid_M), "first"),
        # Slide 7 (FINANCES ACHAT)
        (7, "1 200 000$", _money_long(asking), "all"),
        (7, "375 000$", _money_long(frais_demarrage_total), "all"),
        (7, "91 500$", _money_long(revenus), "first"),
        (7, "953$", _money_short(va["loyer_moyen_actuel"]), "first"),
        (7, "8,00%", _percent_2(rec.taux_interet_preteur_b_projet_pct), "first"),
        (7, "2 745$", _money_long(achat_dep.get("inoccupation")), "first"),
        (7, "12 086$", _money_long(achat_dep.get("taxes_municipales")), "first"),
        (7, "7 000$", _money_long(achat_dep.get("assurances")), "first"),
        (7, "2000$", _money_long(achat_dep.get("energie")), "first"),
        (7, "3 889$", _money_long(achat_dep.get("gestion")), "first"),
        (7, "4 880$", _money_long(achat_dep.get("entretien")), "first"),
        (7, "1 720$", _money_long(achat_dep.get("concierge")), "first"),
        (7, "58 800$", _money_long(achat.get("revenus_net")), "first"),
        (7, "900 000$", _money_long(pret_max_achat), "all"),
        (7, "300 000$", _money_long(mdf_achat), "first"),
        (7, "675 000$", _money_long(fonds_necessaires_achat_val), "all"),
        # Slide 9 (REFINANCEMENT)
        (9, "41 997$", _money_long(depenses_operations_refi), "first"),
        (9, "1788$", _money_short(va["nouveau_loyer_moyen"]), "first"),
        (9, "171 600$", _money_long(va["nouveaux_revenus_an"]), "first"),
        (9, "OUI – 1920$", ligne_wifi, "first"),
        (9, "OUI (2) – 380$", ligne_thermopompes, "first"),
        (9, "100%", _percent_0(reduction_energie), "first"),
        (9, "3,75%", _percent_2_fr(rec.taux_interet_refi_pct), "first"),
        (9, "129 603$", _money_long(revenus_nets_aph50), "first"),
        (9, "113 576$", _money_long(revenus_nets_aph100), "first"),
        (9, "2 882 305$", _money_long(valeur_eco_aph50), "all"),
        (9, " 2 465 059$", _money_long_lead_space(valeur_eco_aph100), "first"),
        (9, "2 449 959 $", _money_long_with_space(pret_max_aph50), "first"),
        (9, "2 449 959$", _money_long(pret_max_aph50), "all"),
        (9, "2 341 806$", _money_long(pret_max_aph100), "first"),
        (9, "347 373$", _money_long(equite_aph50), "all"),
        (9, "239 220$", _money_long(equite_aph100), "first"),
        # Slide 10 (RCI/PVI)
        (10, "675 000$", _money_long(investissement_requis_val), "all"),
        (10, "817 000$", _money_long(valeur_annee_2), "first"),
        (10, "1 750 000$", _money_long(valeur_annee_10), "first"),
        (10, "780 000$", _money_long(equite_an2_court), "first"),
    ]

    return out


# ─── PPTX manipulation ──────────────────────────────────────────────


def _safe_replace_in_text_frame(text_frame, find: str, replace: str) -> int:
    """Replace `find` by `replace` inside a text frame while preserving runs.

    Returns number of replacements done.
    """
    if not find or find == replace:
        return 0
    count = 0
    # Strategy A: try replacing in a single run (most common — preserves formatting)
    for para in text_frame.paragraphs:
        for run in para.runs:
            if find in run.text:
                run.text = run.text.replace(find, replace)
                count += 1
                return count
    # Strategy B: concatenate paragraph runs and replace there if found
    for para in text_frame.paragraphs:
        full_text = "".join(r.text for r in para.runs)
        if find in full_text:
            new_full = full_text.replace(find, replace, 1)
            # Put everything in the first run, blank the rest. This preserves
            # the paragraph-level alignment but collapses run-level formatting
            # within the affected paragraph. Acceptable for our placeholders
            # which are usually single-formatted spans.
            if para.runs:
                para.runs[0].text = new_full
                for r in para.runs[1:]:
                    r.text = ""
                count += 1
                return count
    # Strategy C: multi-paragraph match (e.g. "8 logements\n 2x...")
    full = text_frame.text
    if find in full:
        new_full = full.replace(find, replace, 1)
        # Rewriting `text_frame.text` is destructive (drops formatting). We
        # only do it as last resort.
        text_frame.text = new_full
        return 1
    return 0


def _replace_in_slide(slide, find: str, replace: str, dupe_strategy: str) -> int:
    """Walk all shapes in slide and replace.

    dupe_strategy:
        - "first": stop after 1 replacement
        - "all": replace every occurrence found across shapes
    """
    if not find:
        return 0
    total = 0
    for shape in slide.shapes:
        if shape.has_text_frame:
            n = _safe_replace_in_text_frame(shape.text_frame, find, replace)
            total += n
            if total > 0 and dupe_strategy == "first":
                return total
        if shape.has_table:
            for row in shape.table.rows:
                for cell in row.cells:
                    n = _safe_replace_in_text_frame(cell.text_frame, find, replace)
                    total += n
                    if total > 0 and dupe_strategy == "first":
                        return total
    return total


def _replace_photo(slide, shape_name: str, new_blob: bytes) -> bool:
    """Replace a Picture shape's underlying image while keeping geometry."""
    try:
        for shape in slide.shapes:
            if shape.name == shape_name and shape.shape_type == 13:  # PICTURE
                # python-pptx exposes shape.image but to swap the blob we
                # rewrite the underlying relationship. Easiest approach: keep
                # geometry, remove old, add new at same position.
                left, top, width, height = (
                    shape.left,
                    shape.top,
                    shape.width,
                    shape.height,
                )
                sp = shape._element
                sp.getparent().remove(sp)
                slide.shapes.add_picture(
                    io.BytesIO(new_blob),
                    left,
                    top,
                    width=width,
                    height=height,
                )
                return True
    except Exception as exc:
        log.warning("photo replacement failed for %s: %s", shape_name, exc)
    return False


# ─── Public API ─────────────────────────────────────────────────────


def _slugify_address(addr: Optional[str], fallback_id: int) -> str:
    if not addr or not addr.strip():
        return str(fallback_id)
    decomposed = unicodedata.normalize("NFKD", addr.strip())
    ascii_only = "".join(
        ch for ch in decomposed if not unicodedata.combining(ch)
    )
    underscored = re.sub(r"[\s\-,'’]+", "_", ascii_only)
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", underscored)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or str(fallback_id)


def offre_investissement_pptx_filename(rec: LeadAnalysis) -> str:
    slug = _slugify_address(rec.address, rec.id)
    today = datetime.now().strftime("%Y-%m-%d")
    return f"Offre_Investissement_{slug}_{today}.pptx"


async def generate_offre_investissement_pptx(
    db: AsyncSession,
    analysis_id: int,
    value_add_strategy: Optional[Dict[str, Any]] = None,
    photos: Optional[List[bytes]] = None,
    photo_attachment_ids: Optional[List[int]] = None,
) -> bytes:
    """Generate a .pptx investment offer for the given lead analysis.

    Args:
        db: AsyncSession.
        analysis_id: LeadAnalysis id.
        value_add_strategy: human inputs from the wizard (or None for defaults).
        photos: list of raw image bytes (cover, exterieur, carte).
        photo_attachment_ids: list of LeadAnalysisAttachment ids — alternative
            to `photos`, fetched from DB.

    Returns:
        bytes : the generated .pptx file.

    Raises:
        ValueError: if the analysis is not found or the template is missing.
    """
    rec = await db.get(LeadAnalysis, analysis_id)
    if rec is None:
        raise ValueError(f"LeadAnalysis {analysis_id} introuvable")
    if not _TEMPLATE_PATH.exists():
        raise ValueError(
            f"Template introuvable : {_TEMPLATE_PATH}. "
            f"Vérifiez le déploiement des assets."
        )

    # Lazy import — keep the pptx dep optional at startup
    from pptx import Presentation  # type: ignore

    strat = ValueAddStrategy.from_dict(value_add_strategy)

    # Resolve photos
    resolved_photos: List[bytes] = []
    if photos:
        resolved_photos.extend(photos)
    if photo_attachment_ids:
        from sqlalchemy import select

        q = select(LeadAnalysisAttachment).where(
            LeadAnalysisAttachment.id.in_(photo_attachment_ids),
            LeadAnalysisAttachment.lead_analysis_id == rec.id,
        )
        result = await db.execute(q)
        for att in result.scalars().all():
            resolved_photos.append(att.blob)

    # Open template
    prs = Presentation(str(_TEMPLATE_PATH))

    # Apply text substitutions
    substitutions = _build_substitutions(rec, strat)
    applied = 0
    skipped = 0
    for slide_idx, find, replace, dupe_strategy in substitutions:
        if not find or find == replace:
            skipped += 1
            continue
        if slide_idx >= len(prs.slides):
            continue
        slide = prs.slides[slide_idx]
        n = _replace_in_slide(slide, find, replace, dupe_strategy)
        if n:
            applied += n
        else:
            skipped += 1
    log.info(
        "Offre PPTX generated: %s subs applied, %s skipped (analysis %s)",
        applied,
        skipped,
        analysis_id,
    )

    # Apply photo substitutions
    try:
        with open(_MAPPING_PATH, "r", encoding="utf-8") as f:
            mapping = json.load(f)
        photo_slots = (mapping.get("photos") or {}).get("slots") or []
    except Exception:
        photo_slots = []
    for i, slot in enumerate(photo_slots):
        if i >= len(resolved_photos):
            break
        slide_idx = int(slot.get("slide", 0))
        shape_name = slot.get("shape_name", "")
        if slide_idx >= len(prs.slides):
            continue
        _replace_photo(prs.slides[slide_idx], shape_name, resolved_photos[i])

    # Serialize
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
