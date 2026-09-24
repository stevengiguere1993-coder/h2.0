"""Trace LISIBLE des calculs d'une analyse — onglet « Détails des calculs ».

Phil 2026-09-24 : « la clarté des calculs n'est vraiment pas top, il
manque énormément de détails dans la section détails des calculs. Je
veux que tout y soit. »

Chaque SECTION = une étape du moteur (``lead_analysis_finance``) ;
chaque LIGNE = un poste, sa FORMULE écrite avec les nombres réels, la
valeur, et sa PROVENANCE (fiche / paramètre / calcul). Rien n'est
recalculé ici autrement que pour ÉCRIRE la formule : les valeurs
viennent des résultats du moteur. La trace est persistée dans
``analysis_results_json`` sous ``details_calculs`` et affichée telle
quelle par la fiche.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from app.services.lead_analysis_finance import (
    BAREME,
    FRAIS_FIXES,
    PCT_COURTIERS,
    TAXES_BIENVENUE_MTL_BRACKETS,
    DepensesBreakdown,
    FinanceResults,
    ScenarioResult,
)

log = logging.getLogger(__name__)


# ─── Formatage (français, lisible dans une formule) ───────────────


def _m(x: Any) -> str:
    """Montant : « 8 760 $ », « 5,95 $ », « -1 234 $ »."""
    try:
        v = float(x or 0)
    except (TypeError, ValueError):
        return "—"
    if abs(v) < 100 and abs(v - round(v)) >= 0.005:
        s = f"{abs(v):,.2f}"
    else:
        s = f"{abs(round(v)):,.0f}"
    s = s.replace(",", " ").replace(".", ",")
    return f"{'-' if v < 0 else ''}{s} $"


def _p(frac: Any) -> str:
    """Fraction → pourcentage : 0.0425 → « 4,25 % », 0.05 → « 5 % »."""
    try:
        v = float(frac or 0) * 100.0
    except (TypeError, ValueError):
        return "—"
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{s.replace('.', ',')} %"


def _n(x: Any, dec: int = 0) -> str:
    try:
        v = float(x or 0)
    except (TypeError, ValueError):
        return "—"
    s = f"{v:,.{dec}f}".replace(",", " ").replace(".", ",")
    return s


def _f(x: Any) -> str:
    """Facteur : 1.0609 → « 1,0609 »."""
    return _n(x, 4)


def ligne(
    label: str,
    formule: Optional[str],
    valeur: Any,
    *,
    source: str = "calcul",
    unite: str = "$",
    gras: bool = False,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Une ligne de la trace. ``unite`` : « $ » | « % » | « x » | « n » |
    « txt » (valeur déjà textuelle)."""
    if unite == "$":
        txt = _m(valeur)
        num: Any = round(float(valeur or 0), 2)
    elif unite == "%":
        txt = _p(valeur)
        num = float(valeur or 0)
    elif unite == "x":
        txt = _f(valeur)
        num = float(valeur or 0)
    elif unite == "n":
        txt = _n(valeur)
        num = float(valeur or 0)
    else:
        txt = str(valeur if valeur is not None else "—")
        num = None
    return {
        "label": label,
        "formule": formule,
        "valeur": num,
        "valeur_txt": txt,
        "source": source,
        "gras": gras,
        "note": note,
    }


def section(
    titre: str, lignes: List[Dict[str, Any]], note: Optional[str] = None
) -> Dict[str, Any]:
    return {"titre": titre, "note": note, "lignes": lignes}


# ─── Sections ─────────────────────────────────────────────────────


def _bareme_effectif(res: FinanceResults) -> Dict[str, float]:
    b = dict(BAREME)
    for k, v in (res.inputs.bareme_overrides or {}).items():
        if v is not None:
            b[k] = float(v)
    return b


def _section_fiche(res: FinanceResults) -> Dict[str, Any]:
    i = res.inputs
    nb = int(i.nombre_logements or 0)
    L: List[Dict[str, Any]] = [
        ligne("Prix d'achat (acte de vente)", None, i.prix_achat, source="fiche", gras=True),
    ]
    if res.cashback_montant > 0:
        L.append(ligne("Cashback reçu au notaire", None, res.cashback_montant, source="fiche"))
        L.append(
            ligne(
                "Coût réel de l'immeuble",
                f"{_m(i.prix_achat)} − {_m(res.cashback_montant)}",
                res.prix_reel,
            )
        )
    L += [
        ligne("Nombre de logements", None, nb, source="fiche", unite="n"),
        ligne("Revenus bruts annuels (fiche)", None, i.revenus_annuels, source="fiche"),
        ligne(
            "Loyer moyen actuel ($/mois)",
            f"{_m(i.revenus_annuels)} ÷ 12 ÷ {nb} log." if nb else None,
            (i.revenus_annuels / 12.0 / nb) if nb else 0.0,
        ),
        ligne("Taxes municipales", None, i.taxes_municipales, source="fiche"),
        ligne("Taxes scolaires", None, i.taxes_scolaires, source="fiche"),
        ligne("Assurances", None, i.assurances, source="fiche"),
        ligne("Énergie (base, avant réduction)", None, i.energie, source="fiche"),
        ligne(
            "Autres dépenses",
            None,
            i.depenses_autres,
            source="fiche",
            note=(
                "Montant DÉCLARÉ sur la fiche (extraction de l'annonce ou "
                "saisie), pris tel quel. Il s'ajoute au barème normalisé "
                "(concierge, entretien, gestion, autres normalisations) : si "
                "le vendeur y a déjà inclus l'entretien, la conciergerie ou la "
                "gestion, ces postes sont comptés deux fois — à vérifier."
            ),
        ),
        ligne("Travaux estimés", None, i.frais_travaux, source="fiche"),
        ligne("Frais de développement", None, i.frais_developpement, source="fiche"),
        ligne("Frais de négociations", None, i.frais_negociations, source="fiche"),
    ]
    strat = {
        "preteur_b": "Prêteur B + optimisation + refinancement",
        "traditionnel": "Institution traditionnelle",
        "residentiel": "Résidentiel (cashflow)",
    }.get(i.strategie or "preteur_b", i.strategie or "preteur_b")
    L.append(ligne("Stratégie d'acquisition", None, strat, source="fiche", unite="txt"))
    L.append(ligne("Durée du projet (phase prêteur B)", None, f"{i.duree_projet_annees} an(s)", source="fiche", unite="txt"))
    if i.chantier_actif:
        L.append(ligne("Croissance des loyers (organique)", None, i.croissance_loyers, source="fiche", unite="%"))
        L.append(ligne("Croissance des dépenses", None, i.croissance_depenses, source="fiche", unite="%"))
    if (i.balance_vente_montant or 0) > 0:
        L.append(ligne("Balance de vente (montant)", None, i.balance_vente_montant, source="fiche"))
        L.append(ligne("Balance de vente (taux)", None, i.balance_vente_taux_pct, source="fiche", unite="%"))
    if i.unites:
        opt = sum(1 for u in i.unites if isinstance(u, dict) and u.get("optimiser", True))
        L.append(
            ligne(
                "Unités détaillées",
                None,
                f"{len(i.unites)} unité(s), {opt} à optimiser — "
                + ("optimisation PRÉ-achat" if i.optimisation_pre_achat else "optimisation POST-achat (au refi)"),
                source="fiche",
                unite="txt",
            )
        )
    return section(
        "1 · Données de la fiche",
        L,
        "Ce que la fiche fournit (extraction automatique de l'annonce ou saisie manuelle). Aucun calcul ici.",
    )


def _section_parametres(res: FinanceResults) -> Dict[str, Any]:
    i = res.inputs
    b = _bareme_effectif(res)
    nb = int(i.nombre_logements or 0)
    seuil = int(i.seuil_bascule_bareme_log or 12)
    grand = nb >= seuil
    L: List[Dict[str, Any]] = [
        ligne("TGA (taux global d'actualisation)", None, i.tga, source="paramètre", unite="%"),
        ligne("Taux d'intérêt à l'achat", None, i.taux_interet_achat, source="paramètre", unite="%"),
        ligne("Taux d'intérêt au refinancement", None, i.taux_interet_refi, source="paramètre", unite="%"),
        ligne("Taux du prêteur B pendant le projet", None, i.taux_interet_preteur_b_projet, source="paramètre", unite="%"),
        ligne("Mise de fonds prêteur B", None, i.mdf_preteur_b_pct if i.mdf_preteur_b_pct is not None else 0.25, source="paramètre", unite="%"),
        ligne("Taux d'inoccupation", None, i.taux_inoccupation_pct, source="paramètre", unite="%"),
        ligne("Réduction d'énergie au refi", None, i.reduction_energie_pct, source="paramètre", unite="%"),
        ligne("WiFi ajouté au refi", None, "oui" if i.wifi_ajoute else "non", source="paramètre", unite="txt"),
        ligne("Thermopompes ajoutées (APH)", None, i.nb_thermopompes_ajoutees, source="paramètre", unite="n"),
        ligne("Logements ajoutés au refi", None, i.nb_logements_ajoutes, source="paramètre", unite="n"),
        ligne("Loyer abordable (APH 100 pts, $/mois)", None, i.nouveau_loyer_abordable, source="paramètre"),
        ligne("Ratio de logements abordables (APH 100 pts)", None, i.ratio_abordabilite_aph, source="paramètre", unite="%"),
        ligne(
            "Barème — seuil petit / grand immeuble",
            f"{nb} logements {'≥' if grand else '<'} {seuil} → tarifs « {'grand' if grand else 'petit'} immeuble »",
            f"{seuil} logements",
            source="paramètre",
            unite="txt",
        ),
        ligne("Barème — concierge ($/logement/an)", f"petit {_m(b['concierge_lt12'])} · grand {_m(b['concierge_gte12'])}", b["concierge_gte12"] if grand else b["concierge_lt12"], source="paramètre"),
        ligne("Barème — entretien ($/logement/an)", None, b["entretien"], source="paramètre"),
        ligne("Barème — gestion (% des revenus)", f"petit {_p(b['gestion_lt12'])} · grand {_p(b['gestion_gte12'])}", b["gestion_gte12"] if grand else b["gestion_lt12"], source="paramètre", unite="%"),
        ligne("Barème — autres normalisations (% des revenus)", None, b.get("autres_normalisations_pct", 0.01), source="paramètre", unite="%"),
        ligne("Barème — WiFi", f"{_m(b['wifi_par_log'])}/logement/mois + internet fixe {_m(b['internet_fixe'])}/mois", f"{_m(b['wifi_par_log'])} + {_m(b['internet_fixe'])}", source="paramètre", unite="txt"),
        ligne("Barème — thermopompe ($/an chacune)", None, b["thermopompe"], source="paramètre"),
    ]
    for s in (res.achat, res.refi_schl, res.refi_aph_50, res.refi_aph_100):
        if s is None:
            continue
        c = s.config
        L.append(
            ligne(
                f"Scénario {c.label}",
                None,
                f"prêt/valeur {_p(c.ltv)} · amortissement {c.amort_annees} ans · RCD {_n(c.rcd, 2)}",
                source="paramètre",
                unite="txt",
            )
        )
    return section(
        "2 · Paramètres du modèle",
        L,
        "Réglables dans Paramètres → Prospection (défauts globaux) ou sur la fiche. Le barème normalisé est celui de la SCHL.",
    )


def _section_typologie(res: FinanceResults) -> Optional[Dict[str, Any]]:
    i = res.inputs
    t = res.typology
    parts = []
    nb_prix = 0
    for typo, qty in (i.typologie or {}).items():
        if qty and qty > 0:
            prix = float((i.typologie_prix or {}).get(typo, 0) or 0)
            if prix > 0:
                parts.append(f"{qty} × {_m(prix)} ({typo})")
                nb_prix += qty
    if not parts and not i.unites:
        return None
    L: List[Dict[str, Any]] = []
    if parts:
        L.append(
            ligne(
                "Loyer cible pondéré (H13, $/mois)",
                f"({' + '.join(parts)}) ÷ {nb_prix} log. avec prix",
                t.h13_loyer_pondere,
                note="Les logements sans prix saisi ne comptent pas dans la moyenne.",
            )
        )
    nb = int(i.nombre_logements or 0)
    L.append(
        ligne(
            "Logements abordables (APH 100 pts)",
            f"arrondi sup. de {_p(i.ratio_abordabilite_aph)} × {nb}",
            t.nb_abordables,
            unite="n",
        )
    )
    L.append(ligne("Logements au loyer du marché (PDM)", f"{nb} − {t.nb_abordables}", t.nb_pdm, unite="n"))
    if t.nb_pdm > 0 and parts:
        L.append(
            ligne(
                "Loyer moyen PDM ($/mois)",
                f"moyenne des {t.nb_pdm} unités les plus chères de la typologie",
                t.nouveau_loyer_moyen_pdm,
            )
        )
    if i.unites:
        cl = float(i.croissance_loyers or 0.0) if i.chantier_actif else 0.0
        fac = (1 + cl) ** max(0, int(i.duree_projet_annees or 0))
        actuel = sum(float(u.get("loyer_actuel") or 0) for u in i.unites if isinstance(u, dict))
        au_refi = 0.0
        for u in i.unites:
            if not isinstance(u, dict):
                continue
            if u.get("optimiser", True):
                au_refi += float(u.get("loyer_cible") or 0) * (fac if i.optimisation_pre_achat else 1.0)
            else:
                au_refi += float(u.get("loyer_actuel") or 0) * fac
        L.append(ligne("Unités — somme des loyers actuels ($/mois)", None, actuel, source="fiche"))
        L.append(
            ligne(
                "Unités — somme des loyers au refi ($/mois)",
                f"cible si optimisée, sinon actuel × {_f(fac)} (croissance {_p(cl)} sur {i.duree_projet_annees} an(s))",
                au_refi,
            )
        )
        if i.nb_logements_ajoutes > 0:
            L.append(
                ligne(
                    "Unités ajoutées au refi ($/mois)",
                    f"{i.nb_logements_ajoutes} × loyer cible pondéré {_m(t.h13_loyer_pondere)}",
                    i.nb_logements_ajoutes * t.h13_loyer_pondere,
                )
            )
    return section("3 · Typologie et loyers cibles", L)


def _lignes_depenses(
    res: FinanceResults,
    s: ScenarioResult,
    *,
    is_refi: bool,
    is_aph: bool,
    facteur: float,
) -> List[Dict[str, Any]]:
    i = res.inputs
    b = _bareme_effectif(res)
    d: DepensesBreakdown = s.depenses
    nb = int(s.nb_log)
    seuil = int(i.seuil_bascule_bareme_log or 12)
    grand = nb >= seuil
    conc = b["concierge_gte12"] if grand else b["concierge_lt12"]
    gest = b["gestion_gte12"] if grand else b["gestion_lt12"]
    idx = f" × {_f(facteur)}" if abs(facteur - 1.0) > 1e-9 else ""
    rev = s.revenus_totaux
    L = [
        ligne("Inoccupation", f"{_p(i.taux_inoccupation_pct)} × {_m(rev)}", d.inoccupation),
        ligne("Taxes municipales", f"fiche {_m(i.taxes_municipales)}{idx}", d.taxes_municipales, source="fiche" if not idx else "calcul"),
        ligne("Taxes scolaires", f"fiche {_m(i.taxes_scolaires)}{idx}", d.taxes_scolaires, source="fiche" if not idx else "calcul"),
        ligne("Assurances", f"fiche {_m(i.assurances)}{idx}", d.assurances, source="fiche" if not idx else "calcul"),
        ligne(
            "Énergie",
            (f"fiche {_m(i.energie)} × (1 − {_p(i.reduction_energie_pct)}){idx}" if is_refi else f"fiche {_m(i.energie)}"),
            d.energie,
            source="fiche" if (not is_refi and not idx) else "calcul",
        ),
        ligne("Concierge (barème)", f"{nb} log. × {_m(conc)}", d.concierge),
        ligne("Entretien (barème)", f"{nb} log. × {_m(b['entretien'])}", d.entretien),
        ligne("Gestion (barème)", f"{_p(gest)} × {_m(rev)}", d.gestion),
    ]
    if is_refi:
        L.append(
            ligne(
                "WiFi (barème)",
                (f"{_m(b['wifi_par_log'])} × {nb} log. × 12 + {_m(b['internet_fixe'])} × 12" if i.wifi_ajoute else "non ajouté"),
                d.wifi,
            )
        )
        L.append(
            ligne(
                "Thermopompes (barème, APH seulement)",
                (f"{i.nb_thermopompes_ajoutees} × {_m(b['thermopompe'])}" if is_aph else "scénario non APH → 0"),
                d.thermopompes,
            )
        )
    L.append(
        ligne(
            "Autres normalisations (barème)",
            f"{_p(b.get('autres_normalisations_pct', 0.01))} × {_m(rev)}",
            d.autres_normalisations,
        )
    )
    L.append(
        ligne(
            "Autres dépenses (fiche)",
            f"fiche {_m(i.depenses_autres)}{idx}",
            d.autres,
            source="fiche" if not idx else "calcul",
        )
    )
    if (d.interets_balance_vente or 0) > 0:
        L.append(ligne("Intérêts de la balance de vente", None, d.interets_balance_vente))
    L.append(ligne("Total des dépenses", "somme des postes ci-dessus", d.total, gras=True))
    return L


def _lignes_valeur(
    res: FinanceResults, s: ScenarioResult, *, achat: bool
) -> List[Dict[str, Any]]:
    i = res.inputs
    c = s.config
    taux = i.taux_interet_achat if achat else i.taux_interet_refi
    L = [
        ligne("Revenus nets d'opération (RNO)", f"{_m(s.revenus_totaux)} − {_m(s.depenses.total)}", s.revenus_net, gras=True),
        ligne("Valeur économique (TGA)", f"{_m(s.revenus_net)} ÷ {_p(i.tga)}", s.valeur_eco_tga),
        ligne("Prêt maximal selon le TGA", f"{_m(s.valeur_eco_tga)} × {_p(c.ltv)}", s.hyp_max_tga),
        ligne("Paiement annuel maximal (RCD)", f"{_m(s.revenus_net)} ÷ {_n(c.rcd, 2)}", s.paiement_hyp_max),
        ligne(
            "Prêt maximal selon le RCD",
            f"valeur actuelle d'un paiement de {_m(s.paiement_hyp_max / 12.0)}/mois à {_p(taux)} sur {c.amort_annees} ans (composition canadienne)",
            s.hyp_max_rcd,
        ),
        ligne("Valeur économique (RCD)", f"{_m(s.hyp_max_rcd)} ÷ {_p(c.ltv)}", s.valeur_eco_rcd),
    ]
    if achat and s.valeur_marchande is not None:
        L.append(ligne("Valeur marchande (prix d'achat)", None, s.valeur_marchande, source="fiche"))
        L.append(
            ligne(
                "Valeur retenue",
                f"min({_m(s.valeur_marchande)} ; {_m(s.valeur_eco_rcd)} ; {_m(s.valeur_eco_tga)})",
                s.valeur_retenue,
                gras=True,
            )
        )
    else:
        L.append(
            ligne(
                "Valeur retenue",
                f"min({_m(s.valeur_eco_rcd)} ; {_m(s.valeur_eco_tga)})",
                s.valeur_retenue,
                gras=True,
            )
        )
    L.append(ligne("Financement (prêt accordé)", f"{_m(s.valeur_retenue)} × {_p(c.ltv)}", s.financement, gras=True))
    L.append(
        ligne(
            "Paiement mensuel",
            f"prêt {_m(s.financement)} à {_p(taux)} sur {c.amort_annees} ans",
            s.paiement_mensuel_actuel,
        )
    )
    L.append(
        ligne(
            "Cashflow annuel",
            f"{_m(s.revenus_net)} − 12 × {_m(s.paiement_mensuel_actuel)}",
            s.cashflow_annuel,
        )
    )
    return L


def _revenus_lignes(res: FinanceResults, s: ScenarioResult, quel: str) -> List[Dict[str, Any]]:
    i = res.inputs
    t = res.typology
    nb = int(s.nb_log)
    if quel == "achat":
        if i.optimisation_pre_achat and i.unites:
            form = "somme des unités (cible si optimisée, sinon actuel) × 12"
        else:
            form = "revenus bruts de la fiche"
        L = [ligne("Revenus totaux", form, s.revenus_totaux, source="fiche" if form.startswith("revenus") else "calcul", gras=True)]
        L.append(ligne("Loyer moyen ($/mois)", f"{_m(s.revenus_totaux)} ÷ 12 ÷ {nb}", s.loyer_mois))
        return L
    if quel == "aph100":
        if i.unites:
            form = (
                f"{t.nb_abordables} unités les moins chères au loyer abordable {_m(i.nouveau_loyer_abordable)} + les autres à leur loyer au refi, × 12"
            )
        else:
            form = (
                f"({t.nb_abordables} × {_m(i.nouveau_loyer_abordable)} + {t.nb_pdm} × {_m(t.nouveau_loyer_moyen_pdm)}) × 12"
            )
    else:
        if i.unites:
            form = "somme des loyers des unités au refi (section 3) × 12"
        else:
            form = f"{_m(t.h13_loyer_pondere)} × {nb} log. × 12"
    return [
        ligne("Nombre de logements au refi", f"{i.nombre_logements} + {i.nb_logements_ajoutes} ajouté(s)", nb, unite="n"),
        ligne("Revenus totaux", form, s.revenus_totaux, gras=True),
        ligne("Loyer moyen ($/mois)", f"{_m(s.revenus_totaux)} ÷ 12 ÷ {nb}", s.loyer_mois),
    ]


def _section_scenario(
    res: FinanceResults, s: ScenarioResult, numero: str, quel: str
) -> Dict[str, Any]:
    i = res.inputs
    achat = quel == "achat"
    is_aph = quel in ("aph50", "aph100")
    cd = float(i.croissance_depenses or 0.0) if i.chantier_actif else 0.0
    facteur = 1.0 if achat else (1 + cd) ** max(0, int(i.duree_projet_annees or 0))
    L = _revenus_lignes(res, s, quel)
    L += _lignes_depenses(res, s, is_refi=not achat, is_aph=is_aph, facteur=facteur)
    L += _lignes_valeur(res, s, achat=achat)
    if achat:
        L.append(
            ligne(
                "Mise de fonds nécessaire (prix d'acquisition − prêt)",
                f"{_m(res.prix_acquisition)} − {_m(s.financement)}",
                s.mdf_necessaire,
                gras=True,
            )
        )
    else:
        L.append(
            ligne(
                "Équité à la fin (prêt refi − prix d'acquisition)",
                f"{_m(s.financement)} − {_m(res.prix_acquisition)}",
                s.equite_a_la_fin,
                gras=True,
            )
        )
    note = None
    if not achat and abs(facteur - 1.0) > 1e-9:
        note = (
            f"Dépenses réelles indexées de {_p(cd)}/an sur {i.duree_projet_annees} an(s) "
            f"(facteur {_f(facteur)}) ; le barème normalisé est recalculé sur les revenus du scénario."
        )
    return section(f"{numero} · Scénario {s.config.label}", L, note)


def _section_frais(res: FinanceResults) -> Dict[str, Any]:
    i = res.inputs
    fr = res.frais_demarrage
    mdf = i.mdf_preteur_b_pct if i.mdf_preteur_b_pct is not None else 0.25
    pc = dict(PCT_COURTIERS)
    for k, v in (i.pct_courtiers_overrides or {}).items():
        if v is not None:
            pc[k] = float(v)
    ff = dict(FRAIS_FIXES)
    for k, v in (i.frais_fixes_overrides or {}).items():
        if v is not None:
            ff[k] = float(v)
    ov = i.frais_demarrage_overrides or {}
    masques = set(i.frais_masques or [])
    fin = set(i.frais_demarrage_financables or [])
    best_aph = res.refi_aph_100 if res.refi_aph_100 is not None else res.refi_aph_50
    base_c1 = (1 - mdf) * i.prix_achat if i.chantier_actif else i.prix_achat
    pret_init = i.prix_achat * res.achat.config.ltv
    # Frais finançables (pour la formule des intérêts de portage).
    fin_total = 0.0
    for k, v in fr.__dict__.items():
        if k in ("frais_custom", "interets"):
            continue
        if k in fin:
            fin_total += float(v or 0)
    for c in fr.frais_custom:
        if str(c.get("id", "")) in fin:
            fin_total += float(c.get("montant", 0) or 0)

    # Paliers des taxes de bienvenue.
    brackets = i.taxes_bienvenue_brackets or TAXES_BIENVENUE_MTL_BRACKETS
    paliers = []
    bas = 0.0
    prix = float(i.prix_achat or 0)
    for haut, taux in brackets:
        if prix <= bas:
            break
        tranche = min(prix, haut) - bas
        paliers.append(f"{_m(tranche)} × {_p(taux)}")
        if prix <= haut:
            break
        bas = haut

    formules: Dict[str, str] = {
        "courtier_hypothecaire_1": f"{_p(pc['courtier_hypothecaire_1'])} × {_m(base_c1)} ({'prêt prêteur B' if i.chantier_actif else 'prix'})",
        "courtier_hypothecaire_2": f"{_p(pc['courtier_hypothecaire_2'])} × prêt du meilleur APH {_m(best_aph.financement)}",
        "taxes_bienvenue": "paliers Montréal : " + " + ".join(paliers) if paliers else "paliers Montréal",
        "evaluateur": "montant fixe (paramètre)",
        "evaluateur_2": "montant fixe (paramètre)",
        "inspection": "montant fixe (paramètre)",
        "avocat": "montant fixe (paramètre)",
        "notaire": "montant fixe (paramètre)",
        "notaire_2": "montant fixe (paramètre)",
        "rapport_efficacite": "montant fixe (paramètre)",
        "frais_developpement": "fiche",
        "frais_negociations": "fiche",
        "frais_travaux": "fiche (travaux estimés)",
        "frais_dossier_preteur": f"{_p(i.frais_dossier_preteur_pct)} × prêt initial {_m(pret_init)} ({_m(i.prix_achat)} × {_p(res.achat.config.ltv)})",
        "interets": f"(1 − {_p(mdf)}) × ({_m(i.prix_achat)} + frais finançables {_m(fin_total)}) × {_p(i.taux_interet_preteur_b_projet)} × {i.duree_projet_annees} an(s)",
        "interets_balance_vente": f"{_m(i.balance_vente_montant)} × {_p(i.balance_vente_taux_pct)} × {i.duree_projet_annees} an(s)",
        "detention": "réserve saisie sur la fiche",
        "revenus_nets_pendant_projet": f"− RNO à l'achat {_m(res.achat.revenus_net)} × {i.duree_projet_annees} an(s) (négatif = coût, positif = revenus perdus)",
    }
    labels: Dict[str, str] = {
        "courtier_hypothecaire_1": "Courtier hypothécaire 1",
        "courtier_hypothecaire_2": "Courtier hypothécaire 2 (refi)",
        "taxes_bienvenue": "Taxes de bienvenue",
        "evaluateur": "Évaluateur agréé",
        "evaluateur_2": "Évaluateur agréé 2",
        "inspection": "Inspection",
        "avocat": "Avocat",
        "notaire": "Notaire",
        "notaire_2": "Notaire 2",
        "rapport_efficacite": "Rapport d'efficacité énergétique",
        "frais_developpement": "Frais de développement",
        "frais_negociations": "Frais de négociations",
        "frais_travaux": "Travaux estimés",
        "frais_dossier_preteur": "Frais de dossier du prêteur B",
        "interets": "Intérêts de portage pendant le projet",
        "interets_balance_vente": "Intérêts de la balance de vente",
        "detention": "Détention",
        "revenus_nets_pendant_projet": "Revenus nets pendant le projet",
    }
    L: List[Dict[str, Any]] = []
    cash_total = 0.0
    finance_total = 0.0
    for k, label in labels.items():
        v = float(getattr(fr, k, 0.0) or 0.0)
        src = "calcul"
        form = formules.get(k)
        note = None
        if k in masques:
            form = "poste masqué dans Paramètres"
            src = "paramètre"
        elif ov.get(k) is not None:
            form = "saisi manuellement sur la fiche"
            src = "fiche"
        elif k in ("evaluateur", "evaluateur_2", "inspection", "avocat", "notaire", "notaire_2", "rapport_efficacite"):
            src = "paramètre"
        elif k in ("frais_developpement", "frais_negociations", "frais_travaux", "detention"):
            src = "fiche"
        if k in fin:
            note = f"finançable par le prêteur B : {_p(mdf)} en cash ({_m(v * mdf)}), le reste ({_m(v * (1 - mdf))}) ajouté au prêt"
            cash_total += v * mdf
            finance_total += v * (1 - mdf)
        else:
            cash_total += v
        if v == 0 and k in ("interets_balance_vente", "detention") and src == "calcul":
            continue
        L.append(ligne(label, form, v, source=src, note=note))
    for c in fr.frais_custom:
        v = float(c.get("montant", 0) or 0)
        typ = c.get("type_montant", "fixe")
        val = c.get("valeur", 0)
        if typ == "pct_prix_achat":
            form = f"{_n(val, 2)} % × prix {_m(i.prix_achat)}"
        elif typ == "pct_financement":
            form = f"{_n(val, 2)} % × prêt du meilleur APH {_m(best_aph.financement)}"
        else:
            form = "montant fixe (paramètre)"
        cid = str(c.get("id", ""))
        note = None
        if cid in fin:
            note = f"finançable : {_p(mdf)} en cash, le reste ajouté au prêt"
            cash_total += v * mdf
            finance_total += v * (1 - mdf)
        else:
            cash_total += v
        L.append(ligne(str(c.get("label_fr") or cid), form, v, source="paramètre", note=note))
    L.append(ligne("Total des frais de démarrage", "somme des postes", fr.total, gras=True))
    L.append(ligne("dont payés en cash", "postes non finançables à 100 % + postes finançables × MDF %", cash_total))
    L.append(ligne("dont ajoutés au prêt du prêteur B", "postes finançables × (1 − MDF %)", finance_total))
    return section(
        "5 · Frais de démarrage",
        L,
        "Un poste « fiche » a été saisi ou surchargé sur la fiche ; « paramètre » = défaut global de Paramètres → Prospection.",
    )


def _section_mdf(res: FinanceResults) -> Dict[str, Any]:
    i = res.inputs
    mdf = i.mdf_preteur_b_pct if i.mdf_preteur_b_pct is not None else 0.25
    assise = mdf * i.prix_achat
    frais_cash = res.mdf_preteur_b - assise + res.cashback_montant + res.balance_vente_retenue
    L = [
        ligne("Assise (MDF % × prix)", f"{_p(mdf)} × {_m(i.prix_achat)}", assise),
    ]
    if res.cashback_montant > 0:
        L.append(ligne("− Cashback reçu au notaire", None, -res.cashback_montant, source="fiche"))
    if res.balance_vente_retenue > 0:
        L.append(ligne("− Balance de vente (le vendeur finance une partie de la mise de fonds)", None, -res.balance_vente_retenue, source="fiche"))
    L.append(ligne("+ Frais de démarrage payés en cash", "section 5", frais_cash))
    L.append(
        ligne(
            "= Mise de fonds prêteur B (cash à sortir)",
            f"{_m(assise)}"
            + (f" − {_m(res.cashback_montant)}" if res.cashback_montant > 0 else "")
            + (f" − {_m(res.balance_vente_retenue)}" if res.balance_vente_retenue > 0 else "")
            + f" + {_m(frais_cash)}",
            res.mdf_preteur_b,
            gras=True,
        )
    )
    L.append(ligne("Prêt du prêteur B sur le prix", f"(1 − {_p(mdf)}) × {_m(i.prix_achat)}", res.pret_preteur_b_sur_prix))
    L.append(ligne("+ Frais financés par le prêteur B", "section 5", res.pret_preteur_b_frais_finances))
    L.append(ligne("= Prêt du prêteur B total", f"{_m(res.pret_preteur_b_sur_prix)} + {_m(res.pret_preteur_b_frais_finances)}", res.pret_preteur_b_total, gras=True))
    L.append(
        ligne(
            "Prix d'acquisition (total dépensé)",
            f"coût réel {_m(res.prix_reel)} + frais de démarrage {_m(res.frais_demarrage.total)}",
            res.prix_acquisition,
            gras=True,
            note="C'est ce que le refinancement doit rembourser pour que tout le cash ressorte.",
        )
    )
    return section("6 · Mise de fonds et prêt du prêteur B", L)


def _section_verdict(res: FinanceResults) -> Dict[str, Any]:
    i = res.inputs
    L: List[Dict[str, Any]] = []
    cands = [("refi_schl", res.refi_schl), ("refi_aph_50", res.refi_aph_50), ("refi_aph_100", res.refi_aph_100)]
    meilleur = None
    for key, s in cands:
        if s is None:
            L.append(ligne("SCHL Abordabilité + Efficacité (100 pts)", "scénario non applicable (aucun logement abordable)", "—", unite="txt"))
            continue
        eq = s.equite_a_la_fin or 0.0
        L.append(
            ligne(
                f"{s.config.label} — équité à la fin",
                f"prêt refi {_m(s.financement)} − prix d'acquisition {_m(res.prix_acquisition)}",
                eq,
            )
        )
        if meilleur is None or eq > (meilleur[1].equite_a_la_fin or 0.0):
            meilleur = (key, s)
    if meilleur:
        L.append(ligne("Meilleur scénario (automatique)", "équité la plus élevée", meilleur[1].config.label, unite="txt"))
    if i.refi_retenu:
        L.append(ligne("Référence choisie sur la fiche", None, i.refi_retenu, source="fiche", unite="txt"))
    L.append(ligne("Scénario retenu pour le verdict", None, res.best_refi_program, unite="txt", gras=True))
    L.append(
        ligne(
            "Argent dégagé au refinancement",
            "équité à la fin du scénario retenu (négatif = il manque du cash)",
            res.best_refi_amount,
            gras=True,
        )
    )
    return section("7 · Refinancement et verdict", L)


def _section_traditionnel(res: FinanceResults) -> Optional[Dict[str, Any]]:
    tr = res.traditionnel
    if not tr:
        return None
    i = res.inputs
    labels = tr.get("labels") or {}
    prog = tr.get("programme_retenu")
    L: List[Dict[str, Any]] = [
        ligne(
            "Programme d'achat retenu",
            "choisi sur la fiche" if i.programme_achat else "automatique : le prêt le plus élevé",
            labels.get(prog, prog),
            unite="txt",
            source="fiche" if i.programme_achat else "calcul",
        ),
        ligne("Horizon de détention", None, f"{tr.get('horizon')} an(s)", unite="txt", source="fiche"),
    ]
    detail = tr.get("detail_mdf_par_programme") or {}
    for p, s in (tr.get("achat") or {}).items():
        if not s:
            continue
        d = detail.get(p) or {}
        L.append(
            ligne(
                f"{labels.get(p, p)} — prêt à l'achat",
                f"valeur retenue {_m(s.get('valeur_retenue'))} × {_p(s.get('ltv'))}",
                s.get("financement"),
            )
        )
        L.append(
            ligne(
                f"{labels.get(p, p)} — cash total à sortir",
                f"({_m(i.prix_achat)} − {_m(s.get('financement'))})"
                + (f" − cashback {_m(d.get('cashback'))}" if (d.get("cashback") or 0) > 0 else "")
                + (f" − balance de vente {_m(d.get('balance_vente'))}" if (d.get("balance_vente") or 0) > 0 else "")
                + f" + frais cash {_m(d.get('frais_cash'))}",
                d.get("total_cash"),
                gras=(p == prog),
            )
        )
    L += [
        ligne("Prêt retenu", None, tr.get("pret_retenu"), gras=True),
        ligne(
            f"Solde du prêt à l'an {tr.get('horizon')}",
            f"amortissement du prêt {_m(tr.get('pret_retenu'))} à {_p(i.taux_interet_achat)} pendant {tr.get('horizon')} an(s)",
            tr.get("solde_retenu_an_h"),
        ),
        ligne("Capital remboursé pendant la détention", f"{_m(tr.get('pret_retenu'))} − {_m(tr.get('solde_retenu_an_h'))}", tr.get("capital_rembourse")),
        ligne(
            f"Dette à rembourser à l'an {tr.get('horizon')}",
            f"solde {_m(tr.get('solde_retenu_an_h'))} + balance de vente {_m(tr.get('balance_vente'))} + frais roulés dans le prêt {_m(tr.get('frais_finances'))}",
            tr.get("dette_an_h"),
        ),
        ligne("Cash injecté à l'achat", "mise de fonds nette + frais payés cash", tr.get("cash_injecte")),
    ]
    for p, s in (tr.get("refi") or {}).items():
        if not s:
            continue
        L.append(
            ligne(
                f"{labels.get(p, p)} — argent net dégagé au refi",
                f"nouveau prêt {_m(s.get('financement'))} − dette {_m(tr.get('dette_an_h'))} − cash injecté {_m(tr.get('cash_injecte'))}",
                s.get("equite_a_la_fin"),
            )
        )
    br = tr.get("best_refi") or {}
    L.append(ligne("Référence de refinancement", None, br.get("label"), unite="txt", gras=True))
    L.append(ligne("Argent net dégagé (référence)", None, br.get("argent_dispo"), gras=True))
    return section(
        "8 · Institution traditionnelle (achat, détention, refinancement)",
        L,
        "Les revenus et dépenses de chaque colonne de refinancement sont détaillés dans les sections de scénarios ; la projection année par année est dans l'onglet Projections.",
    )


def _section_residentiel(res: FinanceResults) -> Optional[Dict[str, Any]]:
    r = res.residentiel
    if not r:
        return None
    i = res.inputs
    dd = r.get("depenses_detail") or {}
    L: List[Dict[str, Any]] = [
        ligne("Prêt (ratio prêt-valeur × prix)", f"{_p(r.get('ltv'))} × {_m(i.prix_achat)}", r.get("pret_retenu")),
        ligne("Prime d'assurance prêt", f"{_m(r.get('pret_retenu'))} × {_p(r.get('taux_prime'))}", r.get("prime_assurance")),
        ligne("Prêt total", f"{_m(r.get('pret_retenu'))} + {_m(r.get('prime_assurance'))}", r.get("pret_total"), gras=True),
        ligne("Paiement mensuel", f"prêt {_m(r.get('pret_total'))} à {_p(r.get('taux_interet'))} sur {r.get('amort_annees')} ans", r.get("paiement_mensuel")),
        ligne("Hypothèque annuelle", f"12 × {_m(r.get('paiement_mensuel'))}", r.get("hypotheque_annuelle")),
        ligne("Dépenses réelles — taxes municipales", None, dd.get("taxes_municipales"), source="fiche"),
        ligne("Dépenses réelles — taxes scolaires", None, dd.get("taxes_scolaires"), source="fiche"),
        ligne("Dépenses réelles — assurances", None, dd.get("assurances"), source="fiche"),
        ligne("Dépenses réelles — énergie", None, dd.get("energie"), source="fiche"),
        ligne("Dépenses réelles — autres", None, dd.get("autres"), source="fiche"),
    ]
    for lg in dd.get("lignes") or []:
        L.append(ligne(f"Dépenses réelles — {lg.get('label')}", None, lg.get("montant"), source="fiche"))
    L += [
        ligne("Total des dépenses réelles", "somme", r.get("depenses_reelles"), gras=True),
        ligne("Dépenses supplémentaires après optimisation", None, r.get("depenses_optimisation_supp"), source="fiche"),
        ligne("Revenus actuels", None, r.get("revenus_actuels"), source="fiche"),
        ligne("Revenus optimisés", "somme des unités (cible si optimisée)", r.get("revenus_optimises")),
        ligne("RNO actuel", f"{_m(r.get('revenus_actuels'))} − {_m(r.get('depenses_reelles'))}", r.get("rno_actuel")),
        ligne("RNO optimisé", f"{_m(r.get('revenus_optimises'))} − {_m(r.get('depenses_optimisees'))}", r.get("rno_optimise")),
        ligne("Cashflow actuel", f"{_m(r.get('rno_actuel'))} − {_m(r.get('hypotheque_annuelle'))}", r.get("cashflow_actuel"), gras=True),
        ligne("Cashflow optimisé", f"{_m(r.get('rno_optimise'))} − {_m(r.get('hypotheque_annuelle'))}", r.get("cashflow_optimise"), gras=True),
        ligne("Cash total à l'achat", "mise de fonds nette + frais payés cash", r.get("mdf_cash")),
        ligne("Rendement cash optimisé", f"{_m(r.get('cashflow_optimise'))} ÷ {_m(r.get('mdf_cash'))}", r.get("rendement_cash_optimise"), unite="%"),
    ]
    return section("8 · Résidentiel (cashflow)", L)


def construire_trace(res: FinanceResults) -> List[Dict[str, Any]]:
    """Toutes les sections, dans l'ordre de lecture."""
    sections: List[Dict[str, Any]] = [
        _section_fiche(res),
        _section_parametres(res),
    ]
    typo = _section_typologie(res)
    if typo:
        sections.append(typo)
    sections.append(_section_scenario(res, res.achat, "4a", "achat"))
    sections.append(_section_scenario(res, res.refi_schl, "4b", "schl"))
    sections.append(_section_scenario(res, res.refi_aph_50, "4c", "aph50"))
    if res.refi_aph_100 is not None:
        sections.append(_section_scenario(res, res.refi_aph_100, "4d", "aph100"))
    sections.append(_section_frais(res))
    sections.append(_section_mdf(res))
    sections.append(_section_verdict(res))
    trad = _section_traditionnel(res)
    if trad:
        sections.append(trad)
    resi = _section_residentiel(res)
    if resi:
        sections.append(resi)
    return sections


def trace_sure(res: FinanceResults) -> Optional[List[Dict[str, Any]]]:
    """La trace ne doit JAMAIS faire échouer un calcul : None en cas
    d'erreur (journalisée)."""
    try:
        return construire_trace(res)
    except Exception as exc:  # noqa: BLE001
        log.warning("Trace des calculs indisponible : %s", exc, exc_info=True)
        return None


__all__ = ["construire_trace", "trace_sure"]

# ``math`` gardé pour les paliers (inf) — évite un import inutile ailleurs.
_ = math.inf
