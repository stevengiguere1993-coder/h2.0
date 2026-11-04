"""Revenus et dépenses de la SOCIÉTÉ DE GESTION (Gestion d'entreprise,
2026-11-04) — mode SIMULATION.

Brainstorm Phil 2026-11-04 : « on va bientôt construire un fonds immobilier,
j'aimerais savoir une fois en place ça va être quoi nos revenus et nos
dépenses ». La page modélise ce que la société de gestion (Horizon / le
commandité) gagne en gérant le fonds et son parc — pas les loyers du fonds.

Mode simulation : tout vient des hypothèses saisies (un scénario = un JSON).
Mode réel (plus tard) : les mêmes sections se rempliront depuis Kratos et
QuickBooks ; ce moteur reste la source unique du calcul.

Sources de revenus (annuel) :
  1. Frais de gestion du fonds : VAN (valeur du parc + cash − dettes) × taux.
  2. Frais de développement : prix d'acquisition × % du palier
     (0–3 M : 5 %, 3–6 M : 4,5 %, 6–10 M : 4 %, 10–15 M : 3,5 %, 15 M+ : 3 %),
     pour les acquisitions de l'année.
  3. Frais de prospection : prix d'acquisition × 2 % si prospecté par nous.
  4. Dépenses refacturées : montants avancés × marge (cost-plus).
  5. Construction : phase de stabilisation = travaux initiaux × marge ;
     parc stabilisé = logements × % rénovés par an × coût d'une rénovation × marge.
  6. Maintenance et appels de service : heures × (taux facturé − coût horaire)
     + matériaux × marge.
  7. Gestion locative : loyers bruts des immeubles gérés par nous × taux,
     + projection (loyers additionnels par mois) comptée à part.
  8. Location : relocations (roulement × portes, ou nombre saisi) × frais.
Les revenus cost-plus sont comptés en MARGE NETTE : les coûts refacturés
n'apparaissent ni en revenu ni en dépense (demande de Phil).

Dépenses : frais fixes non refacturables par catégorie, salaires des
postes + charges sociales de l'employeur (RRQ, AE, RQAP, FSS, CNESST,
normes du travail ≈ 14 % au Québec, modifiable), associés = salaire
(avec charges) et dividendes (distribution, après bénéfice).
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

CATEGORIES_FRAIS_FIXES: List[tuple[str, str]] = [
    ("abonnements", "Droits d'adhésion et abonnements (non rechargés)"),
    ("activites", "Activités"),
    ("representation", "Frais de représentation"),
    ("honoraires", "Honoraires professionnels non refacturables"),
    ("fournitures", "Fournitures de bureau"),
    ("deplacements", "Frais de déplacement"),
    ("informatique", "Services informatiques"),
    ("autre", "Autre"),
]
CATEGORIES_LABELS = dict(CATEGORIES_FRAIS_FIXES)
POSTES_DEFAUT = [
    "Comptabilité", "Adjointe administrative", "Prospecteur",
    "Créateur de contenu", "Gestionnaire immobilier",
]
ASSOCIES_DEFAUT = ["Philippe", "Steven", "Michael"]
PALIERS_DEV_DEFAUT = [
    {"jusqua": 3_000_000, "pct": 5.0},
    {"jusqua": 6_000_000, "pct": 4.5},
    {"jusqua": 10_000_000, "pct": 4.0},
    {"jusqua": 15_000_000, "pct": 3.5},
    {"jusqua": None, "pct": 3.0},
]
PHASES = ("stabilisation", "stabilise")
PERIODES = ("mois", "an")

SECTIONS_REVENUS = [
    ("fonds", "Frais de gestion du fonds"),
    ("developpement", "Frais de développement"),
    ("prospection", "Frais de prospection"),
    ("refacturation", "Dépenses refacturées (cost-plus)"),
    ("construction", "Construction (cost-plus)"),
    ("maintenance", "Maintenance et appels de service"),
    ("gestion", "Gestion locative"),
    ("gestion_projection", "Gestion locative — projection"),
    ("location", "Frais de location"),
]
SECTIONS_LABELS = dict(SECTIONS_REVENUS)


def _f(v: Any, defaut: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return defaut
    if x != x:  # NaN
        return defaut
    return x


def _pos(v: Any, defaut: float = 0.0) -> float:
    return max(0.0, _f(v, defaut))


def _opt_int(v: Any) -> Optional[int]:
    if v in (None, ""):
        return None
    try:
        return max(0, int(round(float(v))))
    except (TypeError, ValueError):
        return None


def _id(v: Any) -> str:
    s = str(v or "").strip()
    return s[:40] if s else uuid.uuid4().hex[:12]


def scenario_defaut() -> Dict[str, Any]:
    """Hypothèses de départ (tous les chiffres sont modifiables dans la page)."""
    return normaliser({
        "fonds": {"valeur_parc": 0, "cash": 0, "dettes": 0, "taux_pct": 1.5},
        "developpement": {"paliers": [dict(p) for p in PALIERS_DEV_DEFAUT]},
        "prospection": {"taux_pct": 2.0},
        "immeubles": [],
        "refacturation": {"marge_pct": 10.0, "lignes": []},
        "construction": {"marge_pct": 10.0, "pct_logements_renoves_par_an": 10.0, "cout_reno_logement": 15000},
        "maintenance": {"heures_par_an": 0, "cout_horaire": 50.0, "taux_facture": 75.0,
                        "materiaux_annuels": 0, "marge_materiaux_pct": 10.0},
        "gestion": {"taux_pct": 10.0, "loyers_additionnels_mensuels": 0, "inclure_projection": False},
        "location": {"frais_logement": 600, "frais_chambre": 400, "taux_roulement_pct": 20.0,
                     "nb_relocations_logements": None, "nb_relocations_chambres": None},
        "depenses": {
            "frais_fixes": [{"categorie": c, "libelle": "", "montant": 0, "periode": "an"} for c, _ in CATEGORIES_FRAIS_FIXES if c != "autre"],
            "charges_sociales_pct": 14.0,
            "salaires": [{"poste": p, "salaire_annuel": 0} for p in POSTES_DEFAUT],
            "associes": [{"nom": n, "salaire_annuel": 0, "dividendes_annuels": 0} for n in ASSOCIES_DEFAUT],
        },
    })


def normaliser(data: Any) -> Dict[str, Any]:
    """Rend un scénario propre et complet (valeurs numériques ≥ 0, listes
    typées, identifiants de lignes). Tolère un JSON partiel ou abîmé."""
    d = data if isinstance(data, dict) else {}

    fonds = d.get("fonds") if isinstance(d.get("fonds"), dict) else {}
    dev = d.get("developpement") if isinstance(d.get("developpement"), dict) else {}
    paliers_in = dev.get("paliers") if isinstance(dev.get("paliers"), list) else PALIERS_DEV_DEFAUT
    paliers: List[Dict[str, Any]] = []
    for p in paliers_in:
        if not isinstance(p, dict):
            continue
        jusqua = p.get("jusqua")
        paliers.append({
            "jusqua": None if jusqua in (None, "") else _pos(jusqua),
            "pct": _pos(p.get("pct")),
        })
    if not paliers:
        paliers = [dict(p) for p in PALIERS_DEV_DEFAUT]
    # Tri par plafond croissant, le palier « et plus » (None) en dernier.
    paliers.sort(key=lambda p: (p["jusqua"] is None, p["jusqua"] or 0))

    prosp = d.get("prospection") if isinstance(d.get("prospection"), dict) else {}
    immeubles: List[Dict[str, Any]] = []
    for i in (d.get("immeubles") if isinstance(d.get("immeubles"), list) else []):
        if not isinstance(i, dict):
            continue
        phase = i.get("phase") if i.get("phase") in PHASES else "stabilise"
        immeubles.append({
            "id": _id(i.get("id")),
            "nom": str(i.get("nom") or "")[:120],
            "nb_logements": int(_pos(i.get("nb_logements"))),
            "nb_chambres": int(_pos(i.get("nb_chambres"))),
            "loyers_bruts_mensuels": _pos(i.get("loyers_bruts_mensuels")),
            "gere_par_nous": bool(i.get("gere_par_nous", True)),
            "phase": phase,
            "acquisition_cette_annee": bool(i.get("acquisition_cette_annee", False)),
            "prix_acquisition": _pos(i.get("prix_acquisition")),
            "prospecte_par_nous": bool(i.get("prospecte_par_nous", True)),
            "travaux_initiaux": _pos(i.get("travaux_initiaux")),
        })

    refact = d.get("refacturation") if isinstance(d.get("refacturation"), dict) else {}
    lignes_refact = []
    for l in (refact.get("lignes") if isinstance(refact.get("lignes"), list) else []):
        if isinstance(l, dict):
            lignes_refact.append({"id": _id(l.get("id")), "libelle": str(l.get("libelle") or "")[:120],
                                  "montant_annuel": _pos(l.get("montant_annuel"))})

    constr = d.get("construction") if isinstance(d.get("construction"), dict) else {}
    maint = d.get("maintenance") if isinstance(d.get("maintenance"), dict) else {}
    gest = d.get("gestion") if isinstance(d.get("gestion"), dict) else {}
    loc = d.get("location") if isinstance(d.get("location"), dict) else {}
    dep = d.get("depenses") if isinstance(d.get("depenses"), dict) else {}

    frais_fixes = []
    for l in (dep.get("frais_fixes") if isinstance(dep.get("frais_fixes"), list) else []):
        if not isinstance(l, dict):
            continue
        cat = l.get("categorie") if l.get("categorie") in CATEGORIES_LABELS else "autre"
        frais_fixes.append({
            "id": _id(l.get("id")), "categorie": cat, "libelle": str(l.get("libelle") or "")[:120],
            "montant": _pos(l.get("montant")), "periode": l.get("periode") if l.get("periode") in PERIODES else "an",
        })
    salaires = []
    for s in (dep.get("salaires") if isinstance(dep.get("salaires"), list) else []):
        if isinstance(s, dict):
            salaires.append({"id": _id(s.get("id")), "poste": str(s.get("poste") or "")[:120],
                             "salaire_annuel": _pos(s.get("salaire_annuel"))})
    associes = []
    for a in (dep.get("associes") if isinstance(dep.get("associes"), list) else []):
        if isinstance(a, dict):
            associes.append({"id": _id(a.get("id")), "nom": str(a.get("nom") or "")[:120],
                             "salaire_annuel": _pos(a.get("salaire_annuel")),
                             "dividendes_annuels": _pos(a.get("dividendes_annuels"))})

    return {
        "fonds": {
            "valeur_parc": _pos(fonds.get("valeur_parc")), "cash": _pos(fonds.get("cash")),
            "dettes": _pos(fonds.get("dettes")), "taux_pct": _pos(fonds.get("taux_pct"), 1.5),
        },
        "developpement": {"paliers": paliers},
        "prospection": {"taux_pct": _pos(prosp.get("taux_pct"), 2.0)},
        "immeubles": immeubles,
        "refacturation": {"marge_pct": _pos(refact.get("marge_pct"), 10.0), "lignes": lignes_refact},
        "construction": {
            "marge_pct": _pos(constr.get("marge_pct"), 10.0),
            "pct_logements_renoves_par_an": _pos(constr.get("pct_logements_renoves_par_an"), 10.0),
            "cout_reno_logement": _pos(constr.get("cout_reno_logement"), 15000),
        },
        "maintenance": {
            "heures_par_an": _pos(maint.get("heures_par_an")), "cout_horaire": _pos(maint.get("cout_horaire"), 50.0),
            "taux_facture": _pos(maint.get("taux_facture"), 75.0), "materiaux_annuels": _pos(maint.get("materiaux_annuels")),
            "marge_materiaux_pct": _pos(maint.get("marge_materiaux_pct"), 10.0),
        },
        "gestion": {
            "taux_pct": _pos(gest.get("taux_pct"), 10.0),
            "loyers_additionnels_mensuels": _pos(gest.get("loyers_additionnels_mensuels")),
            "inclure_projection": bool(gest.get("inclure_projection", False)),
        },
        "location": {
            "frais_logement": _pos(loc.get("frais_logement"), 600), "frais_chambre": _pos(loc.get("frais_chambre"), 400),
            "taux_roulement_pct": _pos(loc.get("taux_roulement_pct"), 20.0),
            "nb_relocations_logements": _opt_int(loc.get("nb_relocations_logements")),
            "nb_relocations_chambres": _opt_int(loc.get("nb_relocations_chambres")),
        },
        "depenses": {
            "frais_fixes": frais_fixes, "charges_sociales_pct": _pos(dep.get("charges_sociales_pct"), 14.0),
            "salaires": salaires, "associes": associes,
        },
    }


def taux_developpement(prix: float, paliers: List[Dict[str, Any]]) -> float:
    """% du palier dans lequel tombe le prix d'acquisition (le taux
    s'applique au prix ENTIER, pas par tranche)."""
    for p in paliers:
        if p["jusqua"] is None or prix <= p["jusqua"]:
            return _pos(p["pct"])
    return _pos(paliers[-1]["pct"]) if paliers else 0.0


def _r(x: float) -> float:
    return round(x + 0.0, 2)


def calculer(data: Dict[str, Any]) -> Dict[str, Any]:
    """Résultats annuels d'un scénario normalisé."""
    d = normaliser(data)
    fonds, dev, prosp = d["fonds"], d["developpement"], d["prospection"]
    constr, maint, gest, loc, dep = d["construction"], d["maintenance"], d["gestion"], d["location"], d["depenses"]
    immeubles = d["immeubles"]
    geres = [i for i in immeubles if i["gere_par_nous"]]
    avert: List[str] = []

    # 1. Frais de gestion du fonds.
    van = fonds["valeur_parc"] + fonds["cash"] - fonds["dettes"]
    if van < 0:
        avert.append("La valeur nette du fonds est négative : aucun frais de gestion du fonds.")
    rev_fonds = max(van, 0.0) * fonds["taux_pct"] / 100.0

    # 2-3. Développement et prospection sur les acquisitions de l'année.
    lignes_dev, lignes_prosp = [], []
    rev_dev = rev_prosp = 0.0
    for i in immeubles:
        if not i["acquisition_cette_annee"] or i["prix_acquisition"] <= 0:
            continue
        pct = taux_developpement(i["prix_acquisition"], dev["paliers"])
        frais = i["prix_acquisition"] * pct / 100.0
        rev_dev += frais
        lignes_dev.append({"immeuble": i["nom"] or "Sans nom", "prix": _r(i["prix_acquisition"]), "pct": pct, "frais": _r(frais)})
        if i["prospecte_par_nous"]:
            fp = i["prix_acquisition"] * prosp["taux_pct"] / 100.0
            rev_prosp += fp
            lignes_prosp.append({"immeuble": i["nom"] or "Sans nom", "prix": _r(i["prix_acquisition"]), "frais": _r(fp)})

    # 4. Dépenses refacturées : marge seulement.
    avance = sum(l["montant_annuel"] for l in d["refacturation"]["lignes"])
    rev_refact = avance * d["refacturation"]["marge_pct"] / 100.0

    # 5. Construction : stabilisation (travaux initiaux) + parc stabilisé (rénovations au roulement).
    travaux_stab = sum(i["travaux_initiaux"] for i in immeubles if i["phase"] == "stabilisation")
    logements_stabilises = sum(i["nb_logements"] for i in immeubles if i["phase"] == "stabilise")
    nb_renos = logements_stabilises * constr["pct_logements_renoves_par_an"] / 100.0
    volume_renos = nb_renos * constr["cout_reno_logement"]
    rev_constr_stab = travaux_stab * constr["marge_pct"] / 100.0
    rev_constr_renos = volume_renos * constr["marge_pct"] / 100.0
    rev_constr = rev_constr_stab + rev_constr_renos

    # 6. Maintenance : marge sur les heures + marge sur les matériaux.
    marge_heures = maint["heures_par_an"] * max(maint["taux_facture"] - maint["cout_horaire"], 0.0)
    if maint["taux_facture"] < maint["cout_horaire"]:
        avert.append("Maintenance : le taux facturé est plus bas que le coût horaire — marge horaire à zéro.")
    marge_materiaux = maint["materiaux_annuels"] * maint["marge_materiaux_pct"] / 100.0
    rev_maint = marge_heures + marge_materiaux
    volume_maint = maint["heures_par_an"] * maint["taux_facture"] + maint["materiaux_annuels"] * (1 + maint["marge_materiaux_pct"] / 100.0)

    # 7. Gestion locative : immeubles gérés par nous ; projection à part.
    loyers_geres_annuels = sum(i["loyers_bruts_mensuels"] for i in geres) * 12.0
    rev_gestion = loyers_geres_annuels * gest["taux_pct"] / 100.0
    rev_projection = gest["loyers_additionnels_mensuels"] * 12.0 * gest["taux_pct"] / 100.0
    non_geres = [i["nom"] or "Sans nom" for i in immeubles if not i["gere_par_nous"]]

    # 8. Location : relocations au roulement (ou nombres saisis) × frais.
    logements_geres = sum(i["nb_logements"] for i in geres)
    chambres_geres = sum(i["nb_chambres"] for i in geres)
    reloc_log_calc = int(round(logements_geres * loc["taux_roulement_pct"] / 100.0))
    reloc_ch_calc = int(round(chambres_geres * loc["taux_roulement_pct"] / 100.0))
    reloc_log = loc["nb_relocations_logements"] if loc["nb_relocations_logements"] is not None else reloc_log_calc
    reloc_ch = loc["nb_relocations_chambres"] if loc["nb_relocations_chambres"] is not None else reloc_ch_calc
    rev_location = reloc_log * loc["frais_logement"] + reloc_ch * loc["frais_chambre"]

    revenus = [
        {"key": "fonds", "revenu": _r(rev_fonds), "van": _r(van), "taux_pct": fonds["taux_pct"]},
        {"key": "developpement", "revenu": _r(rev_dev), "lignes": lignes_dev},
        {"key": "prospection", "revenu": _r(rev_prosp), "lignes": lignes_prosp, "taux_pct": prosp["taux_pct"]},
        {"key": "refacturation", "revenu": _r(rev_refact), "montant_avance": _r(avance), "marge_pct": d["refacturation"]["marge_pct"]},
        {"key": "construction", "revenu": _r(rev_constr), "travaux_stabilisation": _r(travaux_stab),
         "revenu_stabilisation": _r(rev_constr_stab), "logements_stabilises": logements_stabilises,
         "nb_renovations": _r(nb_renos), "volume_renovations": _r(volume_renos), "revenu_renovations": _r(rev_constr_renos)},
        {"key": "maintenance", "revenu": _r(rev_maint), "marge_heures": _r(marge_heures), "marge_materiaux": _r(marge_materiaux),
         "volume_facture": _r(volume_maint)},
        {"key": "gestion", "revenu": _r(rev_gestion), "loyers_geres_annuels": _r(loyers_geres_annuels),
         "nb_immeubles_geres": len(geres), "non_geres": non_geres},
        {"key": "gestion_projection", "revenu": _r(rev_projection), "inclus": gest["inclure_projection"],
         "loyers_additionnels_annuels": _r(gest["loyers_additionnels_mensuels"] * 12.0)},
        {"key": "location", "revenu": _r(rev_location), "relocations_logements": reloc_log, "relocations_chambres": reloc_ch,
         "relocations_logements_calculees": reloc_log_calc, "relocations_chambres_calculees": reloc_ch_calc,
         "logements_geres": logements_geres, "chambres_geres": chambres_geres},
    ]
    for s in revenus:
        s["label"] = SECTIONS_LABELS[s["key"]]
    total_revenus = sum(s["revenu"] for s in revenus if s["key"] != "gestion_projection" or gest["inclure_projection"])
    total_revenus_avec_projection = sum(s["revenu"] for s in revenus)
    for s in revenus:
        s["part_pct"] = _r(100.0 * s["revenu"] / total_revenus) if total_revenus > 0 and (s["key"] != "gestion_projection" or gest["inclure_projection"]) else 0.0

    # Dépenses.
    par_categorie: Dict[str, float] = {c: 0.0 for c, _ in CATEGORIES_FRAIS_FIXES}
    for l in dep["frais_fixes"]:
        annuel = l["montant"] * (12.0 if l["periode"] == "mois" else 1.0)
        par_categorie[l["categorie"]] = par_categorie.get(l["categorie"], 0.0) + annuel
    total_frais_fixes = sum(par_categorie.values())
    taux_ch = dep["charges_sociales_pct"] / 100.0
    salaires = []
    total_salaires_bruts = total_charges = 0.0
    for s in dep["salaires"]:
        charges = s["salaire_annuel"] * taux_ch
        total_salaires_bruts += s["salaire_annuel"]
        total_charges += charges
        salaires.append({"poste": s["poste"], "brut": _r(s["salaire_annuel"]), "charges": _r(charges), "total": _r(s["salaire_annuel"] + charges)})
    associes = []
    total_associes_salaires = total_associes_charges = total_dividendes = 0.0
    for a in dep["associes"]:
        charges = a["salaire_annuel"] * taux_ch
        total_associes_salaires += a["salaire_annuel"]
        total_associes_charges += charges
        total_dividendes += a["dividendes_annuels"]
        associes.append({"nom": a["nom"], "salaire_brut": _r(a["salaire_annuel"]), "charges": _r(charges),
                         "cout_salaire": _r(a["salaire_annuel"] + charges), "dividendes": _r(a["dividendes_annuels"])})
    total_masse_salariale = total_salaires_bruts + total_charges + total_associes_salaires + total_associes_charges
    total_depenses = total_frais_fixes + total_masse_salariale
    benefice = total_revenus - total_depenses
    benefice_retenu = benefice - total_dividendes
    if total_dividendes > max(benefice, 0.0):
        avert.append("Les dividendes des associés dépassent le bénéfice : ils puiseraient dans les réserves.")

    # Point mort : ce qu'il manque, converti en VAN du fonds ou en loyers sous gestion.
    reste_sans_fonds = total_depenses - (total_revenus - (rev_fonds if True else 0.0))
    van_necessaire = (reste_sans_fonds / (fonds["taux_pct"] / 100.0)) if (fonds["taux_pct"] > 0 and reste_sans_fonds > 0) else 0.0
    reste_sans_gestion = total_depenses - (total_revenus - rev_gestion)
    loyers_mensuels_necessaires = (reste_sans_gestion / (gest["taux_pct"] / 100.0) / 12.0) if (gest["taux_pct"] > 0 and reste_sans_gestion > 0) else 0.0

    return {
        "revenus": revenus,
        "depenses": {
            "frais_fixes_par_categorie": [
                {"categorie": c, "label": CATEGORIES_LABELS[c], "montant": _r(m)} for c, m in par_categorie.items() if m > 0
            ],
            "total_frais_fixes": _r(total_frais_fixes),
            "salaires": salaires,
            "total_salaires_bruts": _r(total_salaires_bruts),
            "total_charges_sociales": _r(total_charges + total_associes_charges),
            "associes": associes,
            "total_associes_salaires": _r(total_associes_salaires + total_associes_charges),
            "total_masse_salariale": _r(total_masse_salariale),
            "total_dividendes": _r(total_dividendes),
            "total": _r(total_depenses),
            "charges_sociales_pct": dep["charges_sociales_pct"],
        },
        "totaux": {
            "revenus": _r(total_revenus),
            "revenus_avec_projection": _r(total_revenus_avec_projection),
            "depenses": _r(total_depenses),
            "benefice": _r(benefice),
            "marge_pct": _r(100.0 * benefice / total_revenus) if total_revenus > 0 else None,
            "dividendes": _r(total_dividendes),
            "benefice_retenu": _r(benefice_retenu),
            "revenus_mensuels": _r(total_revenus / 12.0),
            "depenses_mensuelles": _r(total_depenses / 12.0),
        },
        "point_mort": {
            "couvert": benefice >= 0,
            "van_necessaire": _r(van_necessaire),
            "van_actuelle": _r(van),
            "loyers_mensuels_sous_gestion_necessaires": _r(loyers_mensuels_necessaires),
            "loyers_mensuels_sous_gestion_actuels": _r(loyers_geres_annuels / 12.0),
        },
        "avertissements": avert,
    }


def resume(resultats: Dict[str, Any]) -> Dict[str, Any]:
    """Petit résumé stocké avec le scénario (liste, lecture MCP)."""
    t = resultats.get("totaux") or {}
    return {
        "revenus": t.get("revenus"), "depenses": t.get("depenses"), "benefice": t.get("benefice"),
        "marge_pct": t.get("marge_pct"), "dividendes": t.get("dividendes"),
        "van_necessaire": (resultats.get("point_mort") or {}).get("van_necessaire"),
    }


def referentiel() -> Dict[str, Any]:
    return {
        "categories_frais_fixes": [{"key": c, "label": l} for c, l in CATEGORIES_FRAIS_FIXES],
        "sections_revenus": [{"key": k, "label": l} for k, l in SECTIONS_REVENUS],
        "paliers_defaut": [dict(p) for p in PALIERS_DEV_DEFAUT],
        "postes_defaut": list(POSTES_DEFAUT),
        "associes_defaut": list(ASSOCIES_DEFAUT),
        "charges_sociales_note": (
            "Charges de l'employeur en plus du salaire brut : RRQ, assurance-emploi, RQAP, FSS, CNESST et "
            "normes du travail — autour de 14 % au Québec pour une petite entreprise. Modifiable."
        ),
    }


def charger(txt: Optional[str]) -> Dict[str, Any]:
    try:
        return normaliser(json.loads(txt) if txt else {})
    except Exception:  # noqa: BLE001
        return scenario_defaut()


__all__ = [
    "CATEGORIES_FRAIS_FIXES", "POSTES_DEFAUT", "ASSOCIES_DEFAUT", "PALIERS_DEV_DEFAUT", "SECTIONS_REVENUS",
    "scenario_defaut", "normaliser", "taux_developpement", "calculer", "resume", "referentiel", "charger",
]
