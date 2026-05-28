"""Génère un .pptx d'offre d'investissement Horizon depuis une
`LeadAnalysis` + un input humain de stratégie value-add.

Approche :
    * Le template `horizon_v2.pptx` (par défaut, configurable via env var
      `OFFRE_INVEST_TEMPLATE`) est une copie du deck 1660 Saint-Clément
      version updated (16 slides, avec slide TENDANCES en pos. 11).
      Les valeurs littérales (montants, phrases, %, ...) servent de
      "placeholders" identifiables — une chaîne dans le template = une
      variable du mapping `horizon_v2.mapping.json`.
    * On effectue une substitution `string.replace` au niveau des runs et
      cellules de tableau pour préserver polices, couleurs, charts, layout.
    * Les variables sont catégorisées en 3 sources :
        - `auto`     : extrait direct de `LeadAnalysis` (~30 champs)
        - `hybrid`   : recalculé depuis le moteur d'analyse financière +
                       inputs value-add (loyers projetés, AT/RT, etc.)
        - `human`    : saisi par l'utilisateur dans le wizard (tagline,
                       bullets opportunité, libellés, qualificatif, etc.)
    * Les photos remplacent les blobs existants en gardant le rectangle
      (4 slots : cover, exterieur, carte, tendances).
    * Logique conditionnelle :
        - Équité refi négative → libellé « Remboursement du partenaire »
          + pourcentage au lieu de montant $
        - Taxes scolaires == 0 → libellé "(inclus scolaire)" préservé

Versioning :
    * v1 (horizon_v1.pptx) : conservé pour rétrocompatibilité MVP PR #532
    * v2 (horizon_v2.pptx) : NOUVEAU défaut (slide TENDANCES + ~10 vars)
    * Env var `OFFRE_INVEST_TEMPLATE` (défaut: 'horizon_v2') permet de
      switcher.

Limites :
    * Les recalculs hybrides utilisent les RÉSULTATS DÉJÀ PERSISTÉS dans
      `analysis_results_json` (le run-financial-analysis le plus récent)
      + des ajustements simples pour les value-add (nouveau loyer moyen,
      revenus, RCI/PVI). Pas de recalcul temps-réel du moteur SCHL/APH.
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


def _resolve_template_paths() -> Tuple[Path, Path, str]:
    """Résout le couple (template.pptx, mapping.json, version) selon
    l'env var ``OFFRE_INVEST_TEMPLATE`` (défaut: ``horizon_v2``).

    Fallback : si le template demandé n'existe pas sur disque, on
    retombe sur ``horizon_v2`` puis ``horizon_v1`` pour ne jamais
    bloquer la génération (utile en cas de déploiement partiel).
    """
    version = os.environ.get("OFFRE_INVEST_TEMPLATE", "horizon_v2").strip()
    if not version:
        version = "horizon_v2"
    candidates = [version, "horizon_v2", "horizon_v1"]
    seen: set = set()
    for v in candidates:
        if v in seen:
            continue
        seen.add(v)
        pptx = _TEMPLATE_DIR / f"{v}.pptx"
        mapping = _TEMPLATE_DIR / f"{v}.mapping.json"
        if pptx.exists() and mapping.exists():
            return pptx, mapping, v
    # Aucun template valide — on retourne quand même les chemins v2
    # pour produire une erreur explicite côté caller.
    return (
        _TEMPLATE_DIR / "horizon_v2.pptx",
        _TEMPLATE_DIR / "horizon_v2.mapping.json",
        "horizon_v2",
    )


# ─── Catalogue des rénovations ──────────────────────────────────────


# Catalogue de rénovations exposé au wizard frontend. Le service
# substitue dans les 16 slots `reno_item_0` ... `reno_item_15` de la
# slide 8 (FINANCES OPTIMISATION) par les items cochés. Les slots
# non utilisés sont vidés (string vide).
RENOVATIONS_CATALOGUE: List[str] = [
    "Fondation",
    "Brique",
    "Portes/fenêtres",
    "Balcons/escaliers",
    "Sous-sol",
    "Toit/sous-toit",
    "Drain entrée extérieur",
    "Chauffe-eau",
    "Panneau électrique à vérifier et corriger",
    "Finir appartement",
    "Rénovations intérieures générales",
    "Entretien extérieur général",
    "Détecteur de fumée et monoxydes",
    "Vermines",
    "Rajout d'un mur",
    "Conversion chauffage",
    "Insonorisation",
    "Plomberie majeure",
    "Électricité majeure",
    "Cuisine complète",
    "Salle de bain complète",
]


# Slots disponibles dans le template v2 (16 lignes du tableau renos)
_RENO_SLOT_COUNT = 16


# Placeholders à remplacer dans le template v2 — mêmes que dans le
# mapping JSON. Si le mapping change, ces valeurs doivent suivre.
_RENO_TEMPLATE_PLACEHOLDERS = [
    "Fondation",
    "Brique",
    "Portes et fenêtres",
    "Balcons et escaliers",
    "Sous-sol",
    "Toit et sous-toit",
    "Drain entrée extérieur",
    "Chauffe-eau",
    "Panneau électrique à vérifier et corriger",
    "Finir appartement 5 1/2 ",
    "Finir appartement 7 1/2",
    "Rénovations intérieures générales",
    "Entretien extérieur général",
    "Détecteur de fumée et monoxydes",
    "Vermines",
    "Rajout d'un mur",
]


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


def _money_long_signed(n: Optional[float]) -> str:
    """Ex: ` -65 000$` ou `347 373$` (avec espace devant si négatif —
    correspond au format du template pour la cellule équité)."""
    if n is None:
        return "—"
    rounded = int(round(n))
    if rounded < 0:
        abs_str = str(abs(rounded))
        with_sep = re.sub(r"\B(?=(\d{3})+(?!\d))", " ", abs_str)
        return f" -{with_sep}$"
    return _money_long(n)


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


def _money_payed_or_annotated(
    value: Optional[float],
    paid_M: Optional[float],
    annotation: Optional[str],
) -> str:
    """Si annotation fournie (saisie humaine), on l'utilise telle quelle
    après la valeur. Sinon, format par défaut '{val} (payé X.XM)'."""
    if annotation and annotation.strip():
        base = _money_long(value) if value else ""
        ann = annotation.strip()
        return f"{base} {ann}".strip() if base else ann
    return _money_payed(value, paid_M)


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
    qualificatif_projet: str = ""
    bullet_opp_1: str = ""
    bullet_opp_2: str = ""
    levier_principal_phrase: str = ""
    bullet_opp_3: str = ""  # Backward-compat (PR #532) — mappé sur levier_principal
    bullet_opp_4: str = ""

    # Gain potentiel callout (slide 4)
    gain_potentiel_callout: str = ""
    gain_potentiel_auto: bool = True

    # Annotation valeur marchande (slide 5)
    valeur_marchande_annotation: str = ""

    # Phase 2 du Gantt (slide 6)
    phase2_label: str = ""

    conversion_chambres: bool = False
    nb_chambres_total: int = 0
    loyer_par_chambre: float = 0.0

    conversion_chauffage: str = "aucun"  # aucun | gaz_to_elec | elec_to_thermo
    ajout_logement_type: str = ""
    ajout_logement_loyer: float = 0.0
    optimisation_loyers_std: bool = True

    programme_schl: str = "aph_50"  # aph_50 | aph_100 | aucun

    ajout_thermopompes: int = 0
    ajout_wifi: bool = False

    # Catalogue rénovations (v2)
    renovations_selectionnees: List[str] = field(default_factory=list)
    autres_renovations: str = ""

    # Backward-compat (PR #532) : ancien input texte libre
    liste_renovations: str = ""

    # Tendances slide 12
    tendances_callout: str = ""

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "ValueAddStrategy":
        if not d:
            return cls()
        # Backward-compat : si bullet_opp_3 fourni mais pas
        # levier_principal_phrase, on utilise bullet_opp_3.
        levier = str(
            d.get("levier_principal_phrase")
            or d.get("bullet_opp_3", "")
            or ""
        )[:200]
        renovations_sel_raw = d.get("renovations_selectionnees") or []
        if isinstance(renovations_sel_raw, str):
            renovations_sel_raw = [
                x.strip()
                for x in renovations_sel_raw.split(",")
                if x.strip()
            ]
        renovations_sel = [
            str(x)[:80]
            for x in renovations_sel_raw
            if x
        ][:32]
        return cls(
            tagline_cover=str(d.get("tagline_cover", "") or "")[:200],
            qualificatif_projet=str(d.get("qualificatif_projet", "") or "")[:30],
            bullet_opp_1=str(d.get("bullet_opp_1", "") or "")[:200],
            bullet_opp_2=str(d.get("bullet_opp_2", "") or "")[:200],
            levier_principal_phrase=levier,
            bullet_opp_3=levier,  # alias
            bullet_opp_4=str(d.get("bullet_opp_4", "") or "")[:200],
            gain_potentiel_callout=str(
                d.get("gain_potentiel_callout", "") or ""
            )[:30],
            gain_potentiel_auto=bool(d.get("gain_potentiel_auto", True)),
            valeur_marchande_annotation=str(
                d.get("valeur_marchande_annotation", "") or ""
            )[:80],
            phase2_label=str(d.get("phase2_label", "") or "")[:40],
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
            renovations_selectionnees=renovations_sel,
            autres_renovations=str(d.get("autres_renovations", "") or "")[:500],
            liste_renovations=str(d.get("liste_renovations", "") or "")[:5000],
            tendances_callout=str(d.get("tendances_callout", "") or "")[:20],
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
    mapping = {
        "SCHL standard": "refi_schl",
        "SCHL Efficacité énergétique (50 pts)": "refi_aph_50",
        "SCHL Abordabilité + Efficacité (100 pts)": "refi_aph_100",
    }
    key = mapping.get(program, "refi_aph_50")
    return scenarios.get(key) or scenarios.get("refi_aph_50") or scenarios.get(
        "refi_schl"
    )


def _suggest_phase2_label(strat: ValueAddStrategy) -> str:
    """Suggère le libellé de la phase 2 du Gantt selon les leviers
    value-add cochés."""
    if strat.phase2_label:
        return strat.phase2_label
    if strat.conversion_chambres:
        return "Création chambres"
    if strat.conversion_chauffage and strat.conversion_chauffage != "aucun":
        return "Conversion chauffage"
    return "Rencontres"


def _calc_value_add(
    rec: LeadAnalysis, strat: ValueAddStrategy
) -> Dict[str, float]:
    """Calcule les agrégats value-add à partir des inputs humains et auto."""
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

    nouveau_loyer_moyen = 0.0
    if results:
        typo = results.get("typology") or {}
        nouveau_loyer_moyen = float(typo.get("h13_loyer_pondere", 0) or 0)
        if not nouveau_loyer_moyen:
            best = _best_refi_scenario(results)
            if best:
                nouveau_loyer_moyen = float(best.get("loyer_mois", 0) or 0)

    if not nouveau_loyer_moyen:
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

    rci_pct = 0.0
    pvi_montant = 0.0
    if results:
        best_amount = float((results.get("best_refi") or {}).get("amount", 0) or 0)
        mdf_preteur_b = float(results.get("mdf_preteur_b", 0) or 0)
        if mdf_preteur_b > 0:
            rci_pct = (best_amount / mdf_preteur_b) * 100.0
        pvi_montant = delta_valeur

    # Gain potentiel callout = delta valeur marchande (auto) OU saisi humain
    gain_potentiel_value = delta_valeur

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
        "gain_potentiel_value": gain_potentiel_value,
    }


def _equity_refi_pct(
    equity_neg: float,
    mdf_initial: float,
) -> str:
    """Cas équité négative : on affiche le % du capital du partenaire
    qui peut être remboursé (au lieu d'un montant négatif).

    Formule : pct = (mdf_initial + equity_neg) / mdf_initial
        - equity_neg est négatif (ex: -65 000$)
        - mdf_initial est l'investissement requis du partenaire (ex: 500 000$)
        - Résultat ≈ 87% → arrondi à 5% près = 85 ou 90%
    """
    if mdf_initial <= 0:
        return "—"
    remboursable = max(0.0, mdf_initial + equity_neg)
    pct = (remboursable / mdf_initial) * 100.0
    # Arrondi à 5% près pour un affichage sobre (90%, 85%, 95%)
    pct_rounded = round(pct / 5.0) * 5
    return f"Jusqu’à {int(pct_rounded)}%"


def _build_substitutions(
    rec: LeadAnalysis,
    strat: ValueAddStrategy,
) -> List[Tuple[int, str, str, str]]:
    """Construit la liste (slide_idx, find, replace, dupe_strategy)."""
    va = _calc_value_add(rec, strat)
    results = None
    if rec.analysis_results_json:
        try:
            results = json.loads(rec.analysis_results_json)
        except Exception:
            results = None

    achat = (results or {}).get("scenarios", {}).get("achat", {}) or {}
    aph50 = (results or {}).get("scenarios", {}).get("refi_aph_50", {}) or {}
    aph100 = (results or {}).get("scenarios", {}).get("refi_aph_100", {}) or {}

    asking = float(rec.asking_price or 0)
    revenus = float(rec.revenus_bruts or 0)
    nb_log_actuel = int(rec.nb_logements or 0)

    compact = _typology_compact(rec.typology_json)
    nb_vacants = _typology_nb_vacants(rec.typology_json)

    address_full = _full_address(rec)

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
    # Équité dégagée : SIGNÉ pour la cellule (peut être négatif → 5271)
    equite_aph50_signed = pret_max_aph50 - pret_max_achat
    equite_aph100_signed = pret_max_aph100 - pret_max_achat
    depenses_operations_refi = float(aph50.get("revenus_totaux", 0) or 0) - revenus_nets_aph50

    # Logique conditionnelle équité refi du best
    best_scenario = _best_refi_scenario(results) or {}
    best_pret_max = float(best_scenario.get("financement", 0) or pret_max_aph50)
    best_equite = best_pret_max - pret_max_achat if asking else 0.0
    is_equity_negative = best_equite < 0
    if is_equity_negative:
        label_callout_refi = "Remboursement du partenaire"
        # TextBox 18 affiche "Jusqu'à\n{valeur}" : on remplace juste le
        # montant par un pourcentage. Le préfixe "Jusqu'à" reste dans
        # le template (paragraphe séparé).
        valeur_callout_refi_tb18 = _equity_refi_pct(
            best_equite, investissement_requis_val
        ).replace("Jusqu’à ", "")
    else:
        label_callout_refi = "Équité dégagée"
        valeur_callout_refi_tb18 = _money_long(max(0.0, best_equite))

    # WiFi / Thermopompes lines for slide 9 (refi)
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
    qualificatif = (strat.qualificatif_projet or "solide").strip() or "solide"
    tagline = (
        strat.tagline_cover
        or f"De l'achat au refinancement : un projet immobilier {qualificatif} à {quartier}"
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
        strat.levier_principal_phrase
        or "Marge significative de création de valeur via optimisation",
        strat.bullet_opp_4
        or f"Demande forte | Secteur {quartier}",
    ]

    # Gain potentiel callout
    if strat.gain_potentiel_auto or not strat.gain_potentiel_callout:
        gain_callout = _money_plus(va.get("gain_potentiel_value", 0))
    else:
        gain_callout = strat.gain_potentiel_callout

    # Phrase d'immeuble
    phrase_immeuble = f"Immeuble de {nb_log_actuel} logements" if nb_log_actuel else "Immeuble multilogements"
    nb_logements_phrase = f"{nb_log_actuel} logements" if nb_log_actuel else "—"
    if compact:
        phrase_typologie = f"{nb_log_actuel} logements\n {compact}\n{nb_vacants} vacants"
    else:
        phrase_typologie = f"{nb_log_actuel} logements"

    paid_M = (asking / 1_000_000.0) if asking else None

    # Phase 2 label (Gantt slide 5)
    phase2_label = _suggest_phase2_label(strat)

    # Taxes scolaires conditional label (slide 7)
    taxes_scolaires_val = float(rec.taxes_scolaires or 0)
    if taxes_scolaires_val <= 0:
        taxes_municipales_label = "Taxes municipales (inclus scolaire)"
    else:
        taxes_municipales_label = "Taxes municipales"

    # Tendances slide 11
    tendances_secteur = (rec.city or "").strip() or "le secteur"
    tendances_source_label = (
        f"Zipplex, données Q1 2026 — secteur {tendances_secteur}"
    )
    tendances_callout = strat.tendances_callout or "+0$"

    # Catalogue rénovations slide 8 — on substitue les 16 placeholders
    # par les items cochés. Les slots non utilisés sont vidés.
    renos_finaux: List[str] = list(strat.renovations_selectionnees or [])
    # Backward-compat : si l'utilisateur a saisi le texte libre legacy
    # (PR #532), on essaie de splitter par newline et fusionner.
    if not renos_finaux and strat.liste_renovations:
        renos_finaux = [
            l.strip()
            for l in strat.liste_renovations.split("\n")
            if l.strip()
        ]
    # Ajouter le free-text « autres rénovations » (split par newline)
    if strat.autres_renovations:
        for line in strat.autres_renovations.split("\n"):
            line = line.strip()
            if line:
                renos_finaux.append(line)
    # Padding ou troncature aux 16 slots disponibles
    while len(renos_finaux) < _RENO_SLOT_COUNT:
        renos_finaux.append("")
    renos_finaux = renos_finaux[:_RENO_SLOT_COUNT]

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
        (3, "+ 497 100$", gain_callout, "first"),
        # Slide 4 (Plan création de valeur — avant/après)
        (4, "1800$", _money_short(va["nouveau_loyer_moyen"]), "first"),
        (4, "171 600$", _money_long(va["nouveaux_revenus_an"]), "first"),
        (4, "2 882 305$  (+1 685 305$)", _money_with_delta(va["nouvelle_valeur_marchande"], va["delta_valeur"]), "first"),
        (4, "953$", _money_short(va["loyer_moyen_actuel"]), "first"),
        (4, "91 500$", _money_long(revenus), "first"),
        (4, "1 697 100$ (payé 1.2M)", _money_payed_or_annotated(va["ancienne_valeur_marchande"], paid_M, strat.valeur_marchande_annotation), "first"),
        # Slide 5 (Échéancier Gantt — phase 2 label)
        (5, "Création chambres", phase2_label, "first"),
        # Slide 7 (FINANCES ACHAT)
        (7, "1 200 000$", _money_long(asking), "all"),
        (7, "375 000$", _money_long(frais_demarrage_total), "all"),
        (7, "91 500$", _money_long(revenus), "first"),
        (7, "953$", _money_short(va["loyer_moyen_actuel"]), "first"),
        (7, "8,00%", _percent_2(rec.taux_interet_preteur_b_projet_pct), "first"),
        (7, "2 745$", _money_long(achat_dep.get("inoccupation")), "first"),
        (7, "Taxes municipales (inclus scolaire)", taxes_municipales_label, "first"),
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
        # Équité cellules : SIGNÉES (peuvent être négatives). Note :
        # le TextBox 18 contient aussi « 347 373$ » sur un paragraphe
        # séparé (préfixe « Jusqu'à » sur le paragraphe précédent).
        # Cas positif : on remplace partout (cellule + TextBox 18) par
        #   le montant signé.
        # Cas négatif : la cellule reçoit le montant signé négatif,
        #   mais le TextBox 18 doit afficher un pourcentage. On utilise
        #   donc une stratégie en 2 temps :
        #     1) la cellule (premier match) reçoit le montant signé
        #     2) le TextBox 18 (deuxième match) reçoit le pourcentage
        #   via une 2e substitution dédiée. Pour ça, en cas négatif on
        #   substitue d'abord la cellule (« first ») puis on cible le
        #   TextBox 18 (qui contiendra encore « 347 373$ » non remplacé)
        #   avec une 2e règle.
        (9, "347 373$", _money_long_signed(equite_aph50_signed), "first"),
        (9, "347 373$", valeur_callout_refi_tb18, "first"),  # TB18 — reste après cell hit
        (9, "239 220$", _money_long_signed(equite_aph100_signed), "first"),
        # Libellé du callout (TextBox 29 + en-tête de cellule "Équité dégagée")
        (9, "Équité dégagée", label_callout_refi, "all"),
        # Slide 10 (RCI/PVI — Bourse vs Horizon)
        (10, "675 000$", _money_long(investissement_requis_val), "all"),
        (10, "817 000$", _money_long(valeur_annee_2), "first"),
        (10, "1 750 000$", _money_long(valeur_annee_10), "first"),
        (10, "780 000$", _money_long(equite_an2_court), "first"),
        # Slide 11 (TENDANCES — NOUVEAU)
        (11, "Zipplex, données Q1 2026 — secteur Mercier-Hochelaga-Maisonneuve", tendances_source_label, "first"),
        (11, "+900$", tendances_callout, "first"),
    ]

    # Slide 8 : catalogue rénovations — substitue les 16 placeholders
    # par les items cochés (ou vide string si rien).
    for i, placeholder in enumerate(_RENO_TEMPLATE_PLACEHOLDERS):
        replacement = renos_finaux[i] if i < len(renos_finaux) else ""
        out.append((8, placeholder, replacement, "first"))

    return out


# ─── PPTX manipulation ──────────────────────────────────────────────


def _safe_replace_in_text_frame(text_frame, find: str, replace: str) -> int:
    """Replace `find` by `replace` inside a text frame while preserving runs."""
    if not find or find == replace:
        return 0
    count = 0
    for para in text_frame.paragraphs:
        for run in para.runs:
            if find in run.text:
                run.text = run.text.replace(find, replace)
                count += 1
                return count
    for para in text_frame.paragraphs:
        full_text = "".join(r.text for r in para.runs)
        if find in full_text:
            new_full = full_text.replace(find, replace, 1)
            if para.runs:
                para.runs[0].text = new_full
                for r in para.runs[1:]:
                    r.text = ""
                count += 1
                return count
    full = text_frame.text
    if find in full:
        new_full = full.replace(find, replace, 1)
        text_frame.text = new_full
        return 1
    return 0


def _replace_in_slide(slide, find: str, replace: str, dupe_strategy: str) -> int:
    """Walk all shapes in slide and replace."""
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


def get_renovations_catalogue() -> List[str]:
    """Expose le catalogue de rénovations au frontend (pour le wizard).
    Utilisé par le endpoint GET /lead-analyses/offre-investissement/catalogue."""
    return list(RENOVATIONS_CATALOGUE)


async def generate_offre_investissement_pptx(
    db: AsyncSession,
    analysis_id: int,
    value_add_strategy: Optional[Dict[str, Any]] = None,
    photos: Optional[List[bytes]] = None,
    photo_attachment_ids: Optional[List[int]] = None,
) -> Tuple[bytes, str]:
    """Generate a .pptx investment offer for the given lead analysis.

    Args:
        db: AsyncSession.
        analysis_id: LeadAnalysis id.
        value_add_strategy: human inputs from the wizard (or None for defaults).
        photos: list of raw image bytes (cover, exterieur, carte, tendances).
        photo_attachment_ids: list of LeadAnalysisAttachment ids.

    Returns:
        (pptx_bytes, template_version) : le `.pptx` généré + la version
        du template utilisée (ex: "horizon_v2", "horizon_v1").

    Raises:
        ValueError: if the analysis is not found or the template is missing.
    """
    rec = await db.get(LeadAnalysis, analysis_id)
    if rec is None:
        raise ValueError(f"LeadAnalysis {analysis_id} introuvable")

    template_path, mapping_path, template_version = _resolve_template_paths()
    if not template_path.exists():
        raise ValueError(
            f"Template introuvable : {template_path}. "
            f"Vérifiez le déploiement des assets."
        )

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
    prs = Presentation(str(template_path))

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
        "Offre PPTX generated (%s): %s subs applied, %s skipped (analysis %s)",
        template_version,
        applied,
        skipped,
        analysis_id,
    )

    # Apply photo substitutions
    try:
        with open(mapping_path, "r", encoding="utf-8") as f:
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
    return buf.getvalue(), template_version
