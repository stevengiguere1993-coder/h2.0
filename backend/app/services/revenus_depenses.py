"""Revenus et dépenses de la SOCIÉTÉ DE GESTION (Gestion d'entreprise,
2026-11-04) — mode SIMULATION, aligné sur « Le Fonds MGV d'investissements »
(document de travail de Phil, Michael et Steven, novembre 2026).

La page modélise ce que MGV Développement / Horizon gagne en gérant le
fonds et son parc — pas les loyers du fonds. Un scénario = un JSON
d'hypothèses ; ce moteur reste la source unique du calcul (le mode réel,
branché sur Kratos et QuickBooks, viendra en opération).

Valeur du fonds (doc, p. 11-14) :
  VAN = valeur des immeubles + cash − toutes les dettes.
  • Stabilisé : valeur du dernier rapport d'évaluation ; entre deux, revenus
    nets à jour ÷ taux de capitalisation du rapport.
  • En rénovation : coût du projet (prix + travaux + frais connexes)
    + (valeur future − coût) × mois écoulés ÷ mois prévus.
  Les immeubles « hors fonds » (détenus ailleurs) ne comptent ni dans la VAN
  ni dans les frais du fonds, mais rapportent gestion locative, location,
  construction, maintenance.

Sources de revenus en CASH (doc, p. 20-21) :
  1. Gestion du fonds : 1,5 %/an de la VAN.
  2. Développement : sur le prix d'achat, par TRANCHES comme l'impôt
     (0–3 M 5 %, 3–6 M 4,5 %, 6–10 M 4 %, 10–15 M 3,5 %, 15–20 M 3 %, 20 M+ 2,5 %).
  3. Prospection : 2 % du prix, si prospecté par nous.
  4. Dépenses refacturées : coûtant + 10 % (la marge seulement).
  5. Construction : coûtant + 10 % (travaux initiaux en rénovation ; rénovations
     au roulement une fois stabilisé).
  6. Maintenance et appels de service : heures × (taux facturé − coût) + matériaux × marge.
  7. Gestion locative : 10 % des loyers bruts (immeubles sous-traités inclus
     ou non, au choix) + projection « et si on gérait plus ».
  8. Location : relocations (roulement ou nombre saisi) × frais.
Part des gains (doc, p. 7) : EN PARTS, pas en cash — calculée à part, hors
des totaux : 7 % aux investisseurs, 3 % suivants à nous, le reste 70/30.

Dépenses : frais fixes non refacturables, salaires + charges sociales de
l'employeur (≈ 14 % au Québec), associés (salaire avec charges = dépense ;
dividendes = distribution), sous-traitant de gestion (% des loyers des
immeubles non gérés à l'interne).
"""
from __future__ import annotations

import json
import uuid
from datetime import date
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
#: Barème du document (p. 21) : chaque taux s'applique à SA tranche seulement.
PALIERS_DEV_DEFAUT = [
    {"jusqua": 3_000_000, "pct": 5.0},
    {"jusqua": 6_000_000, "pct": 4.5},
    {"jusqua": 10_000_000, "pct": 4.0},
    {"jusqua": 15_000_000, "pct": 3.5},
    {"jusqua": 20_000_000, "pct": 3.0},
    {"jusqua": None, "pct": 2.5},
]
PHASES = ("stabilisation", "stabilise")


def annee_defaut() -> int:
    """Un scénario se planifie pour l'année qui vient (Phil : « je planifie pour 2027 »)."""
    return date.today().year + 1


def _date_iso(v: Any) -> Optional[str]:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        return None
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


def _r(x: float) -> float:
    return round(x + 0.0, 2)


def immeuble_vide(**kw: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:12], "nom": "", "kratos_immeuble_id": None,
        "dans_le_fonds": True, "gestion_interne": True,
        "nb_logements": 0, "nb_chambres": 0, "loyers_bruts_mensuels": 0.0,
        "phase": "stabilise",
        # Rénovation / acquisition.
        "acquisition_cette_annee": False, "prix_acquisition": 0.0, "prospecte_par_nous": True,
        "travaux_initiaux": 0.0, "frais_connexes": 0.0, "valeur_future": 0.0,
        "mois_prevus": 24, "mois_ecoules": 0,
        # Stabilisé.
        "valeur_rapport": 0.0, "annee_rapport": None, "taux_cap_pct": 0.0, "revenus_nets_annuels": 0.0,
        # Les deux.
        "dette": 0.0,
        #: Date de l'acquisition dans l'année du scénario (prorata) ; vide = 1er janvier.
        "date_acquisition": None,
        #: Alertes de l'import Kratos (loyers ou rapport manquants…), effaçables.
        "notes_import": [],
    }
    base.update(kw)
    return base


def scenario_defaut() -> Dict[str, Any]:
    """Hypothèses de départ (tous les chiffres sont modifiables dans la page)."""
    return normaliser({
        "annee": annee_defaut(),
        "fonds": {"cash": 0, "taux_pct": 1.5},
        "developpement": {"paliers": [dict(p) for p in PALIERS_DEV_DEFAUT]},
        "prospection": {"taux_pct": 2.0},
        "immeubles": [],
        "refacturation": {"marge_pct": 10.0, "lignes": []},
        "construction": {"marge_pct": 10.0, "pct_logements_renoves_par_an": 10.0, "cout_reno_logement": 15000},
        "maintenance": {"heures_par_an": 0, "cout_horaire": 50.0, "taux_facture": 75.0,
                        "materiaux_annuels": 0, "marge_materiaux_pct": 10.0},
        "gestion": {"taux_pct": 10.0, "facturer_sous_traites": True, "loyers_additionnels_mensuels": 0, "inclure_projection": False},
        "location": {"frais_logement": 600, "frais_chambre": 400, "taux_roulement_pct": 20.0,
                     "nb_relocations_logements": None, "nb_relocations_chambres": None},
        "part_des_gains": {"rendement_pct": 15.0, "seuil_investisseurs_pct": 7.0, "tranche_nous_pct": 3.0, "part_nous_pct": 30.0},
        "depenses": {
            "frais_fixes": [{"categorie": c, "libelle": "", "montant": 0, "periode": "an"} for c, _ in CATEGORIES_FRAIS_FIXES if c != "autre"],
            "charges_sociales_pct": 14.0,
            "salaires": [{"poste": p, "salaire_annuel": 0} for p in POSTES_DEFAUT],
            "associes": [{"nom": n, "salaire_annuel": 0, "dividendes_annuels": 0} for n in ASSOCIES_DEFAUT],
            "sous_traitance_gestion_pct": 0.0,
        },
    })


def normaliser(data: Any) -> Dict[str, Any]:
    """Rend un scénario propre et complet (valeurs numériques ≥ 0, listes
    typées, identifiants de lignes). Tolère un JSON partiel ou abîmé, y
    compris l'ancien format (valeur_parc / dettes saisis, gere_par_nous)."""
    d = data if isinstance(data, dict) else {}

    fonds = d.get("fonds") if isinstance(d.get("fonds"), dict) else {}
    dev = d.get("developpement") if isinstance(d.get("developpement"), dict) else {}
    paliers_in = dev.get("paliers") if isinstance(dev.get("paliers"), list) else PALIERS_DEV_DEFAUT
    paliers: List[Dict[str, Any]] = []
    for p in paliers_in:
        if not isinstance(p, dict):
            continue
        jusqua = p.get("jusqua")
        paliers.append({"jusqua": None if jusqua in (None, "") else _pos(jusqua), "pct": _pos(p.get("pct"))})
    if not paliers:
        paliers = [dict(p) for p in PALIERS_DEV_DEFAUT]
    paliers.sort(key=lambda p: (p["jusqua"] is None, p["jusqua"] or 0))

    prosp = d.get("prospection") if isinstance(d.get("prospection"), dict) else {}
    immeubles: List[Dict[str, Any]] = []
    for i in (d.get("immeubles") if isinstance(d.get("immeubles"), list) else []):
        if not isinstance(i, dict):
            continue
        phase = i.get("phase") if i.get("phase") in PHASES else "stabilise"
        interne = i.get("gestion_interne", i.get("gere_par_nous", True))
        kid = i.get("kratos_immeuble_id")
        try:
            kid = int(kid) if kid not in (None, "") else None
        except (TypeError, ValueError):
            kid = None
        annee = _opt_int(i.get("annee_rapport"))
        immeubles.append(immeuble_vide(
            id=_id(i.get("id")), nom=str(i.get("nom") or "")[:120], kratos_immeuble_id=kid,
            dans_le_fonds=bool(i.get("dans_le_fonds", True)), gestion_interne=bool(interne),
            nb_logements=int(_pos(i.get("nb_logements"))), nb_chambres=int(_pos(i.get("nb_chambres"))),
            loyers_bruts_mensuels=_pos(i.get("loyers_bruts_mensuels")), phase=phase,
            acquisition_cette_annee=bool(i.get("acquisition_cette_annee", False)),
            prix_acquisition=_pos(i.get("prix_acquisition")), prospecte_par_nous=bool(i.get("prospecte_par_nous", True)),
            travaux_initiaux=_pos(i.get("travaux_initiaux")), frais_connexes=_pos(i.get("frais_connexes")),
            valeur_future=_pos(i.get("valeur_future")),
            mois_prevus=max(1, int(_pos(i.get("mois_prevus"), 24) or 24)), mois_ecoules=int(_pos(i.get("mois_ecoules"))),
            valeur_rapport=_pos(i.get("valeur_rapport")), annee_rapport=annee if annee and annee > 1900 else None,
            taux_cap_pct=_pos(i.get("taux_cap_pct")), revenus_nets_annuels=_pos(i.get("revenus_nets_annuels")),
            dette=_pos(i.get("dette")), date_acquisition=_date_iso(i.get("date_acquisition")),
            notes_import=[str(n)[:200] for n in (i.get("notes_import") if isinstance(i.get("notes_import"), list) else [])][:6],
        ))

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
    pg = d.get("part_des_gains") if isinstance(d.get("part_des_gains"), dict) else {}
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

    annee = int(_pos(d.get("annee"), annee_defaut()) or annee_defaut())
    if not 2000 <= annee <= 2100:
        annee = annee_defaut()
    return {
        "annee": annee,
        "fonds": {"cash": _pos(fonds.get("cash")), "taux_pct": _pos(fonds.get("taux_pct"), 1.5)},
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
            "facturer_sous_traites": bool(gest.get("facturer_sous_traites", True)),
            "loyers_additionnels_mensuels": _pos(gest.get("loyers_additionnels_mensuels")),
            "inclure_projection": bool(gest.get("inclure_projection", False)),
        },
        "location": {
            "frais_logement": _pos(loc.get("frais_logement"), 600), "frais_chambre": _pos(loc.get("frais_chambre"), 400),
            "taux_roulement_pct": _pos(loc.get("taux_roulement_pct"), 20.0),
            "nb_relocations_logements": _opt_int(loc.get("nb_relocations_logements")),
            "nb_relocations_chambres": _opt_int(loc.get("nb_relocations_chambres")),
        },
        "part_des_gains": {
            "rendement_pct": _pos(pg.get("rendement_pct"), 15.0),
            "seuil_investisseurs_pct": _pos(pg.get("seuil_investisseurs_pct"), 7.0),
            "tranche_nous_pct": _pos(pg.get("tranche_nous_pct"), 3.0),
            "part_nous_pct": min(100.0, _pos(pg.get("part_nous_pct"), 30.0)),
        },
        "depenses": {
            "frais_fixes": frais_fixes, "charges_sociales_pct": _pos(dep.get("charges_sociales_pct"), 14.0),
            "salaires": salaires, "associes": associes,
            "sous_traitance_gestion_pct": _pos(dep.get("sous_traitance_gestion_pct")),
        },
    }


def frais_developpement(prix: float, paliers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Frais de développement par TRANCHES (doc p. 21 : « chaque taux
    s'applique à sa tranche seulement, comme l'impôt »). Renvoie le total et
    le détail par tranche."""
    reste = max(prix, 0.0)
    bas = 0.0
    total = 0.0
    tranches = []
    for p in paliers:
        if reste <= 0:
            break
        haut = p["jusqua"]
        largeur = reste if haut is None else max(0.0, min(reste, haut - bas))
        if largeur > 0:
            frais = largeur * _pos(p["pct"]) / 100.0
            total += frais
            tranches.append({"de": _r(bas), "a": None if haut is None else _r(haut), "montant": _r(largeur), "pct": _pos(p["pct"]), "frais": _r(frais)})
            reste -= largeur
        if haut is not None:
            bas = haut
    return {"total": _r(total), "tranches": tranches, "taux_effectif_pct": _r(100.0 * total / prix) if prix > 0 else 0.0}


def part_annee(i: Dict[str, Any], annee: int) -> Dict[str, Any]:
    """Part de l'année du scénario pendant laquelle l'immeuble est à nous.
    Acquisition conclue cette année avec une date → prorata au jour près
    (3 avril 2027 → 273 jours sur 365) ; sans date → 1er janvier (année
    entière) ; date avant l'année → année entière, mais plus de frais
    d'acquisition ; date après l'année → rien cette année."""
    jours_annee = 366 if (annee % 4 == 0 and (annee % 100 != 0 or annee % 400 == 0)) else 365
    if not i["acquisition_cette_annee"] or not i.get("date_acquisition"):
        return {"part": 1.0, "jours": jours_annee, "jours_annee": jours_annee, "acquise_cette_annee": bool(i["acquisition_cette_annee"]), "date": None}
    d = date.fromisoformat(i["date_acquisition"])
    if d.year < annee:
        return {"part": 1.0, "jours": jours_annee, "jours_annee": jours_annee, "acquise_cette_annee": False, "date": d.isoformat()}
    if d.year > annee:
        return {"part": 0.0, "jours": 0, "jours_annee": jours_annee, "acquise_cette_annee": False, "date": d.isoformat()}
    jours = (date(annee, 12, 31) - d).days + 1
    return {"part": jours / jours_annee, "jours": jours, "jours_annee": jours_annee, "acquise_cette_annee": True, "date": d.isoformat()}


def valeur_immeuble(i: Dict[str, Any]) -> Dict[str, Any]:
    """Valeur d'un immeuble selon le document (p. 11) : stabilisé = rapport,
    ou revenus nets ÷ taux de cap s'ils sont donnés ; en rénovation = coût
    du projet + plus-value linéaire vers la valeur future."""
    cout_projet = i["prix_acquisition"] + i["travaux_initiaux"] + i["frais_connexes"]
    if i["phase"] == "stabilisation":
        if i["valeur_future"] > 0 and i["mois_prevus"] > 0:
            avance = min(max(i["mois_ecoules"], 0), i["mois_prevus"]) / i["mois_prevus"]
            valeur = cout_projet + (i["valeur_future"] - cout_projet) * avance
            methode = f"coût du projet + plus-value linéaire ({i['mois_ecoules']}/{i['mois_prevus']} mois)"
        else:
            valeur = cout_projet
            methode = "coût du projet (pas de valeur future donnée)"
        return {
            "cout_projet": _r(cout_projet), "valeur": _r(valeur), "valeur_a_terme": _r(i["valeur_future"] or cout_projet),
            "plus_value_prevue": _r((i["valeur_future"] - cout_projet) if i["valeur_future"] > 0 else 0.0), "methode": methode,
        }
    if i["revenus_nets_annuels"] > 0 and i["taux_cap_pct"] > 0:
        valeur = i["revenus_nets_annuels"] / (i["taux_cap_pct"] / 100.0)
        methode = f"revenus nets {i['revenus_nets_annuels']:,.0f} $ ÷ taux de cap {i['taux_cap_pct']:g} %"
    else:
        valeur = i["valeur_rapport"]
        methode = f"dernier rapport d'évaluation{(' (' + str(i['annee_rapport']) + ')') if i['annee_rapport'] else ''}"
    return {"cout_projet": _r(cout_projet), "valeur": _r(valeur), "valeur_a_terme": _r(valeur), "plus_value_prevue": 0.0, "methode": methode}


def calculer(data: Dict[str, Any]) -> Dict[str, Any]:
    """Résultats annuels d'un scénario normalisé."""
    d = normaliser(data)
    fonds, dev, prosp = d["fonds"], d["developpement"], d["prospection"]
    constr, maint, gest, loc, pg, dep = d["construction"], d["maintenance"], d["gestion"], d["location"], d["part_des_gains"], d["depenses"]
    immeubles = d["immeubles"]
    avert: List[str] = []

    # Parc : valeur, dette, équité par immeuble ; totaux du fonds (immeubles « dans le fonds »).
    annee = d["annee"]
    parts = {i["id"]: part_annee(i, annee) for i in immeubles}
    fiches = []
    valeur_parc = dettes = valeur_a_terme = equite_ponderee = 0.0
    for i in immeubles:
        v = valeur_immeuble(i)
        equite = v["valeur"] - i["dette"]
        pa = parts[i["id"]]
        fiches.append({"id": i["id"], "nom": i["nom"] or "Sans nom", "dans_le_fonds": i["dans_le_fonds"], "phase": i["phase"],
                       **v, "dette": _r(i["dette"]), "equite": _r(equite),
                       "part_annee": _r(100.0 * pa["part"]), "jours": pa["jours"], "jours_annee": pa["jours_annee"],
                       "date_acquisition": pa["date"], "acquise_cette_annee": pa["acquise_cette_annee"],
                       "notes_import": list(i.get("notes_import") or [])})
        if i["dans_le_fonds"] and pa["part"] > 0:
            valeur_parc += v["valeur"]
            dettes += i["dette"]
            valeur_a_terme += v["valeur_a_terme"]
            equite_ponderee += equite * pa["part"]
            if equite < 0:
                avert.append(f"{i['nom'] or 'Un immeuble'} : la dette dépasse la valeur (équité négative).")
    van = valeur_parc + fonds["cash"] - dettes
    van_a_terme = valeur_a_terme + fonds["cash"] - dettes
    # Frais du fonds au prorata : un immeuble acquis le 3 avril ne rapporte
    # que 273/365 de son équité dans l'année (Phil 2026-11-04).
    van_ponderee = equite_ponderee + fonds["cash"]
    if van < 0:
        avert.append("La valeur nette du fonds est négative : aucun frais de gestion du fonds.")
    rev_fonds = max(van_ponderee, 0.0) * fonds["taux_pct"] / 100.0

    # 2-3. Développement (par tranches) et prospection, acquisitions de l'année dans le fonds.
    lignes_dev, lignes_prosp = [], []
    rev_dev = rev_prosp = 0.0
    for i in immeubles:
        if not i["dans_le_fonds"] or not parts[i["id"]]["acquise_cette_annee"] or i["prix_acquisition"] <= 0:
            continue
        fd = frais_developpement(i["prix_acquisition"], dev["paliers"])
        rev_dev += fd["total"]
        lignes_dev.append({"immeuble": i["nom"] or "Sans nom", "prix": _r(i["prix_acquisition"]), "frais": fd["total"],
                           "taux_effectif_pct": fd["taux_effectif_pct"], "tranches": fd["tranches"]})
        if i["prospecte_par_nous"]:
            fp = i["prix_acquisition"] * prosp["taux_pct"] / 100.0
            rev_prosp += fp
            lignes_prosp.append({"immeuble": i["nom"] or "Sans nom", "prix": _r(i["prix_acquisition"]), "frais": _r(fp)})

    # 4. Dépenses refacturées : marge seulement.
    avance = sum(l["montant_annuel"] for l in d["refacturation"]["lignes"])
    rev_refact = avance * d["refacturation"]["marge_pct"] / 100.0

    # 5. Construction : rénovation (travaux initiaux) + parc stabilisé (rénovations au roulement), fonds ou hors fonds.
    travaux_stab = sum(i["travaux_initiaux"] for i in immeubles if i["phase"] == "stabilisation")
    logements_stabilises = sum(i["nb_logements"] for i in immeubles if i["phase"] == "stabilise")
    logements_stabilises_ponderes = sum(i["nb_logements"] * parts[i["id"]]["part"] for i in immeubles if i["phase"] == "stabilise")
    nb_renos = logements_stabilises_ponderes * constr["pct_logements_renoves_par_an"] / 100.0
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

    # 7. Gestion locative : loyers des immeubles gérés à l'interne (+ sous-traités si on les facture aussi).
    internes = [i for i in immeubles if i["gestion_interne"]]
    sous_traites = [i for i in immeubles if not i["gestion_interne"]]
    loyers_internes = sum(i["loyers_bruts_mensuels"] * parts[i["id"]]["part"] for i in internes) * 12.0
    loyers_sous_traites = sum(i["loyers_bruts_mensuels"] * parts[i["id"]]["part"] for i in sous_traites) * 12.0
    base_gestion = loyers_internes + (loyers_sous_traites if gest["facturer_sous_traites"] else 0.0)
    rev_gestion = base_gestion * gest["taux_pct"] / 100.0
    rev_projection = gest["loyers_additionnels_mensuels"] * 12.0 * gest["taux_pct"] / 100.0

    # 8. Location : relocations sur les portes gérées à l'interne (roulement ou nombres saisis) × frais.
    logements_internes = sum(i["nb_logements"] for i in internes)
    chambres_internes = sum(i["nb_chambres"] for i in internes)
    logements_internes_ponderes = sum(i["nb_logements"] * parts[i["id"]]["part"] for i in internes)
    chambres_internes_ponderees = sum(i["nb_chambres"] * parts[i["id"]]["part"] for i in internes)
    reloc_log_calc = int(round(logements_internes_ponderes * loc["taux_roulement_pct"] / 100.0))
    reloc_ch_calc = int(round(chambres_internes_ponderees * loc["taux_roulement_pct"] / 100.0))
    reloc_log = loc["nb_relocations_logements"] if loc["nb_relocations_logements"] is not None else reloc_log_calc
    reloc_ch = loc["nb_relocations_chambres"] if loc["nb_relocations_chambres"] is not None else reloc_ch_calc
    rev_location = reloc_log * loc["frais_logement"] + reloc_ch * loc["frais_chambre"]

    revenus = [
        {"key": "fonds", "revenu": _r(rev_fonds), "van": _r(van), "van_ponderee": _r(van_ponderee), "taux_pct": fonds["taux_pct"]},
        {"key": "developpement", "revenu": _r(rev_dev), "lignes": lignes_dev},
        {"key": "prospection", "revenu": _r(rev_prosp), "lignes": lignes_prosp, "taux_pct": prosp["taux_pct"]},
        {"key": "refacturation", "revenu": _r(rev_refact), "montant_avance": _r(avance), "marge_pct": d["refacturation"]["marge_pct"]},
        {"key": "construction", "revenu": _r(rev_constr), "travaux_stabilisation": _r(travaux_stab),
         "revenu_stabilisation": _r(rev_constr_stab), "logements_stabilises": logements_stabilises,
         "nb_renovations": _r(nb_renos), "volume_renovations": _r(volume_renos), "revenu_renovations": _r(rev_constr_renos)},
        {"key": "maintenance", "revenu": _r(rev_maint), "marge_heures": _r(marge_heures), "marge_materiaux": _r(marge_materiaux),
         "volume_facture": _r(volume_maint)},
        {"key": "gestion", "revenu": _r(rev_gestion), "loyers_internes_annuels": _r(loyers_internes),
         "loyers_sous_traites_annuels": _r(loyers_sous_traites), "base_annuelle": _r(base_gestion),
         "nb_internes": len(internes), "nb_sous_traites": len(sous_traites),
         "sous_traites": [i["nom"] or "Sans nom" for i in sous_traites]},
        {"key": "gestion_projection", "revenu": _r(rev_projection), "inclus": gest["inclure_projection"],
         "loyers_additionnels_annuels": _r(gest["loyers_additionnels_mensuels"] * 12.0)},
        {"key": "location", "revenu": _r(rev_location), "relocations_logements": reloc_log, "relocations_chambres": reloc_ch,
         "relocations_logements_calculees": reloc_log_calc, "relocations_chambres_calculees": reloc_ch_calc,
         "logements_internes": logements_internes, "chambres_internes": chambres_internes},
    ]
    for s in revenus:
        s["label"] = SECTIONS_LABELS[s["key"]]
    total_revenus = sum(s["revenu"] for s in revenus if s["key"] != "gestion_projection" or gest["inclure_projection"])
    total_revenus_avec_projection = sum(s["revenu"] for s in revenus)
    for s in revenus:
        s["part_pct"] = _r(100.0 * s["revenu"] / total_revenus) if total_revenus > 0 and (s["key"] != "gestion_projection" or gest["inclure_projection"]) else 0.0

    # Part des gains (en parts, hors totaux) — doc p. 7 : 7 % aux investisseurs, 3 % à nous, le reste 70/30.
    gain = max(van, 0.0) * pg["rendement_pct"] / 100.0
    t1 = min(gain, max(van, 0.0) * pg["seuil_investisseurs_pct"] / 100.0)
    t2 = min(max(gain - t1, 0.0), max(van, 0.0) * pg["tranche_nous_pct"] / 100.0)
    reste = max(gain - t1 - t2, 0.0)
    nous_reste = reste * pg["part_nous_pct"] / 100.0
    part_nous = t2 + nous_reste
    part_investisseurs = t1 + (reste - nous_reste)
    nb_holdings = max(1, len(dep["associes"]) or 3)
    prorates = [f for f in fiches if f["acquise_cette_annee"] and f["date_acquisition"] and f["part_annee"] < 100.0]

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
    sous_traitance = loyers_sous_traites * dep["sous_traitance_gestion_pct"] / 100.0
    total_masse_salariale = total_salaires_bruts + total_charges + total_associes_salaires + total_associes_charges
    total_depenses = total_frais_fixes + total_masse_salariale + sous_traitance
    benefice = total_revenus - total_depenses
    benefice_retenu = benefice - total_dividendes
    if total_dividendes > max(benefice, 0.0):
        avert.append("Les dividendes des associés dépassent le bénéfice : ils puiseraient dans les réserves.")

    # Point mort : ce qu'il manque, converti en VAN du fonds ou en loyers sous gestion.
    reste_sans_fonds = total_depenses - (total_revenus - rev_fonds)
    van_necessaire = (reste_sans_fonds / (fonds["taux_pct"] / 100.0)) if (fonds["taux_pct"] > 0 and reste_sans_fonds > 0) else 0.0
    reste_sans_gestion = total_depenses - (total_revenus - rev_gestion)
    loyers_mensuels_necessaires = (reste_sans_gestion / (gest["taux_pct"] / 100.0) / 12.0) if (gest["taux_pct"] > 0 and reste_sans_gestion > 0) else 0.0

    return {
        "parc": {
            "immeubles": fiches,
            "valeur": _r(valeur_parc), "dettes": _r(dettes), "equite": _r(valeur_parc - dettes), "cash": _r(fonds["cash"]),
            "van": _r(van), "van_ponderee": _r(van_ponderee), "valeur_a_terme": _r(valeur_a_terme), "van_a_terme": _r(van_a_terme),
            "annee": annee, "nb_prorates": len(prorates),
            "nb_dans_le_fonds": sum(1 for i in immeubles if i["dans_le_fonds"]),
            "nb_hors_fonds": sum(1 for i in immeubles if not i["dans_le_fonds"]),
            "nb_en_renovation": sum(1 for i in immeubles if i["dans_le_fonds"] and i["phase"] == "stabilisation"),
        },
        "revenus": revenus,
        "part_des_gains": {
            "van": _r(van), "rendement_pct": pg["rendement_pct"], "gain": _r(gain),
            "tranche_investisseurs": _r(t1), "tranche_nous": _r(t2), "reste": _r(reste),
            "part_nous": _r(part_nous), "part_investisseurs": _r(part_investisseurs),
            "par_holding": _r(part_nous / nb_holdings), "nb_holdings": nb_holdings,
            "pct_du_gain_nous": _r(100.0 * part_nous / gain) if gain > 0 else 0.0,
        },
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
            "sous_traitance_gestion": _r(sous_traitance),
            "loyers_sous_traites_annuels": _r(loyers_sous_traites),
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
            "loyers_mensuels_sous_gestion_actuels": _r(base_gestion / 12.0),
        },
        "avertissements": avert,
    }


def resume(resultats: Dict[str, Any]) -> Dict[str, Any]:
    """Petit résumé stocké avec le scénario (liste, lecture MCP)."""
    t = resultats.get("totaux") or {}
    return {
        "revenus": t.get("revenus"), "depenses": t.get("depenses"), "benefice": t.get("benefice"),
        "marge_pct": t.get("marge_pct"), "dividendes": t.get("dividendes"),
        "van": (resultats.get("parc") or {}).get("van"),
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
        "prorata_note": (
            "Une acquisition conclue dans l'année est comptée au prorata des jours restants (ex. 3 avril → 273 jours sur 365) "
            "pour la gestion locative, les relocations, les rénovations au roulement, les frais du fonds et le sous-traitant. "
            "Les frais de développement et de prospection sont dus en entier à l'acquisition."
        ),
        "valorisation_note": (
            "Document du fonds (p. 11) : VAN = valeur des immeubles + cash − dettes. Stabilisé = valeur du dernier "
            "rapport, ou revenus nets ÷ taux de capitalisation du rapport. En rénovation = coût du projet "
            "(prix + travaux + frais connexes) + plus-value linéaire vers la valeur future, au prorata des mois écoulés."
        ),
    }


def charger(txt: Optional[str]) -> Dict[str, Any]:
    try:
        return normaliser(json.loads(txt) if txt else {})
    except Exception:  # noqa: BLE001
        return scenario_defaut()


__all__ = [
    "CATEGORIES_FRAIS_FIXES", "POSTES_DEFAUT", "ASSOCIES_DEFAUT", "PALIERS_DEV_DEFAUT", "SECTIONS_REVENUS",
    "immeuble_vide", "scenario_defaut", "normaliser", "frais_developpement", "valeur_immeuble", "part_annee", "annee_defaut", "calculer",
    "resume", "referentiel", "charger",
]
