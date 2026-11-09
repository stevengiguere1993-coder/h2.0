"""Gestion d'entreprise → Performance du fonds (2026-11-06, v2 : projection année par année).

Phil : « il faut que tout ça soit annualisé… en ayant seulement l'année actuelle,
on ne peut pas voir la performance du fonds » ; « un fonds c'est toujours sur le
capital du fonds… il faut que ça reflète [le document] » ; « détention simple
pour commencer » ; cash-flow « basé sur les barèmes de la SCHL pour le moment ».

Le document « Le Fonds MGV d'investissements » (nov. 2026) :
- p. 11 : VAN = valeur des immeubles + cash − dettes ; stabilisé = revenus nets
  (barèmes SCHL) ÷ taux de cap du rapport ; en rénovation = coût du projet +
  plus-value linéaire vers la valeur future ;
- p. 14 : le gain d'une année = VAN fin − VAN début, fait de trois sources :
  loyers en hausse (valeur), capital remboursé, cash gardé ;
- p. 7-8 : « année à 15 % » = gain ÷ VAN de départ ; partage 7 % aux
  investisseurs, 3 % à nous, reste 70 / 30 ; les investisseurs gardent le même
  nombre de parts (le prix monte), nous recevons de NOUVELLES parts au nouveau
  prix. Reproduit la p. 8 : 10 M$ à 15 % → 11,5 / 13,2 / 15,2 / 17,5 / 20,1 M$ et
  notre part 3,9 / 7,7 / 11,3 / 14,8 / 18,1 % (voir le test) ;
- p. 9 : l'argent de nos holdings est traité comme celui d'un investisseur ;
- p. 16 : un nouvel investisseur entre au prix courant de la part (personne n'est
  dilué) ;
- p. 20 : frais de gestion du fonds 1,5 %/an de la VAN, payés en cash.

Détention simple : aucun refinancement, aucun cash sorti. Un prêt « intérêts
seulement » (prêteur B, privé) devient un prêt amorti (taux de renouvellement ou
taux par défaut, amortissement par défaut) à la fin de son terme, ou à la
stabilisation pour un immeuble en rénovation.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, List, Optional

from app.services import revenus_depenses as svc
from app.services.hypotheque_calc import taux_mensuel


def _r(x: Any) -> float:
    return round(float(x or 0.0), 2)


def _pct(num: float, den: float) -> Optional[float]:
    return _r(100.0 * num / den) if den and den > 0 else None


def _irr(flux: List[float]) -> Optional[float]:
    """Taux de rendement interne (%) de flux annuels (flux[0] = aujourd'hui) ; None si pas de signe mixte."""
    if len(flux) < 2 or all(f >= 0 for f in flux) or all(f <= 0 for f in flux):
        return None

    def van(r: float) -> float:
        return sum(f / (1.0 + r) ** t for t, f in enumerate(flux))

    lo, hi = -0.95, 10.0
    f_lo, f_hi = van(lo), van(hi)
    if f_lo * f_hi > 0:
        return None
    mid = lo
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = van(mid)
        if abs(f_mid) < 1e-6:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return _r(100.0 * mid)


def _annualise(multiple: float, annees: float) -> Optional[float]:
    if annees <= 0 or multiple <= 0:
        return None
    return _r(100.0 * (multiple ** (1.0 / annees) - 1.0))


# ─── Partage du gain (doc p. 7-9) ───────────────────────────────────────────

def partage_gain(gain: float, capital: float, regles: Dict[str, Any]) -> Dict[str, float]:
    """Règles de la section « Part des gains » (doc p. 7) : les premiers X % du
    capital aux investisseurs, les Y % suivants à nous, le reste partagé.
    Un gain négatif est porté en entier par les parts existantes (rien à nous)."""
    base = max(capital, 0.0)
    if gain <= 0:
        return {"gain": _r(gain), "tranche_investisseurs": 0.0, "tranche_nous": 0.0, "reste": 0.0,
                "part_nous": 0.0, "part_investisseurs": _r(gain)}
    t1 = min(gain, base * regles["seuil_investisseurs_pct"] / 100.0)
    t2 = min(max(gain - t1, 0.0), base * regles["tranche_nous_pct"] / 100.0)
    reste = max(gain - t1 - t2, 0.0)
    nous_reste = reste * regles["part_nous_pct"] / 100.0
    return {
        "gain": _r(gain), "tranche_investisseurs": _r(t1), "tranche_nous": _r(t2), "reste": _r(reste),
        "part_nous": _r(t2 + nous_reste), "part_investisseurs": _r(t1 + (reste - nous_reste)),
    }


def partager_annee(van_debut: float, capital_entre: float, gain: float, parts_total: float, parts_nous: float,
                   regles: Dict[str, Any]) -> Dict[str, float]:
    """Une fin d'exercice en parts (doc p. 8) : le capital entré dans l'année
    achète des parts au prix de départ ; la part des investisseurs fait monter
    le prix de TOUTES les parts existantes ; notre part est payée en nouvelles
    parts à ce nouveau prix. VAN fin = prix × parts, exactement."""
    prix_debut = (van_debut / parts_total) if parts_total > 0 else 0.0
    parts_entrees = (capital_entre / prix_debut) if prix_debut > 0 else 0.0
    parts_apres_entree = parts_total + parts_entrees
    p = partage_gain(gain, van_debut + capital_entre, regles)
    if parts_apres_entree > 0:
        prix_fin = (van_debut + capital_entre + p["part_investisseurs"]) / parts_apres_entree
    else:
        prix_fin = 0.0
    nouvelles = (p["part_nous"] / prix_fin) if prix_fin > 0 else 0.0
    parts_fin = parts_apres_entree + nouvelles
    return {
        **p, "prix_part_debut": prix_debut, "prix_part": prix_fin, "parts_entrees": parts_entrees,
        "nouvelles_parts_nous": nouvelles, "parts_total": parts_fin, "parts_nous": parts_nous + nouvelles,
        "pct_nous": (100.0 * (parts_nous + nouvelles) / parts_fin) if parts_fin > 0 else 0.0,
        "rendement_part_pct": (100.0 * (prix_fin / prix_debut - 1.0)) if prix_debut > 0 else 0.0,
    }


# ─── Prêts ──────────────────────────────────────────────────────────────────

def _pmt(solde: float, taux_pct: float, n_mois: int, composition: str) -> float:
    if solde <= 0 or n_mois <= 0:
        return 0.0
    i = taux_mensuel(taux_pct, composition)
    if i <= 0:
        return solde / n_mois
    return solde * i / (1.0 - (1.0 + i) ** (-n_mois))


def simuler_pret(p: Dict[str, Any], horizon: int, hyp: Dict[str, Any]) -> List[Dict[str, float]]:
    """Année par année (1..horizon) : service de dette, capital remboursé, solde en fin d'année.

    ``p`` : solde (début), taux_pct, mois_restants (amortissement restant),
    paiement_mensuel (sinon calculé), composition, interet_seulement,
    conversion_annee (prêt intérêts seulement → amorti à partir de cette année),
    fin_terme_annee (année dont la fin marque l'échéance du terme).
    Détention simple : le solde ne remonte jamais."""
    solde = max(float(p.get("solde") or 0.0), 0.0)
    taux = float(p.get("taux_pct") or 0.0)
    comp = p.get("composition") or "semi"
    io = bool(p.get("interet_seulement"))
    n_rest = int(p.get("mois_restants") or 0)
    pmt = float(p.get("paiement_mensuel") or 0.0)
    conv = p.get("conversion_annee")
    fin_terme = p.get("fin_terme_annee")
    renouv = float(hyp.get("taux_renouvellement_pct") or 0.0)
    out: List[Dict[str, float]] = []
    if not io and pmt <= 0 and n_rest > 0:
        pmt = _pmt(solde, taux, n_rest, comp)
    for n in range(1, horizon + 1):
        if solde <= 0.005:
            out.append({"service": 0.0, "capital": 0.0, "interets": 0.0, "solde": 0.0})
            continue
        if io and conv is not None and n >= conv:
            # Fin du prêt intérêts seulement : prêt amorti aux conditions par défaut (ou de renouvellement).
            io = False
            taux = renouv if renouv > 0 else float(hyp.get("taux_dette_defaut_pct") or 0.0)
            comp = "semi"
            n_rest = int(hyp.get("amortissement_defaut_ans") or 0) * 12
            pmt = _pmt(solde, taux, n_rest, comp)
        elif (not io) and fin_terme is not None and n == fin_terme + 1 and renouv > 0 and n_rest > 0:
            # Renouvellement du terme : nouveau taux, paiement recalculé sur l'amortissement restant.
            taux = renouv
            pmt = _pmt(solde, taux, n_rest, comp)
        service = capital = interets = 0.0
        if io:
            i = taux_mensuel(taux, comp) if taux > 0 else 0.0
            interets = solde * i * 12.0 if pmt <= 0 else pmt * 12.0
            service = interets
        else:
            i = taux_mensuel(taux, comp) if taux > 0 else 0.0
            for _ in range(12):
                if solde <= 0.005:
                    break
                it = solde * i
                princ = max(pmt - it, 0.0)
                if n_rest <= 1 or princ > solde:
                    princ = solde
                solde -= princ
                n_rest -= 1
                service += it + princ
                capital += princ
                interets += it
        out.append({"service": service, "capital": capital, "interets": interets, "solde": max(solde, 0.0)})
    return out


# ─── Un immeuble ────────────────────────────────────────────────────────────

def _projeter_immeuble(i: Dict[str, Any], bareme: Optional[Dict[str, Any]], prets: Optional[List[Dict[str, Any]]],
                       hyp: Dict[str, Any], annee_depart: int, horizon: int) -> Dict[str, Any]:
    notes: List[str] = []
    gl = hyp["croissance_loyers_pct"] / 100.0
    gd = hyp["croissance_depenses_pct"] / 100.0
    fp0 = svc.valeur_immeuble(i, bareme)
    schl = fp0.get("depenses_schl")
    reno = i["phase"] == "stabilisation"
    cout = float(fp0["cout_projet"] or 0.0)
    vf = float(i["valeur_future"] or 0.0)
    pa = svc.part_annee(i, annee_depart)
    acquis_an1 = bool(pa["acquise_cette_annee"])
    prorata1 = pa["part"] if acquis_an1 else 1.0

    # Rénovation : mois restants au début de l'an 1 → première fin d'année stabilisée.
    mois_prevus = max(int(i["mois_prevus"] or 1), 1)
    mois_ecoules = int(i["mois_ecoules"] or 0)
    n_stab = max(math.ceil((mois_prevus - mois_ecoules) / 12.0), 0) if reno else 0
    cap = (hyp["taux_cap_sortie_pct"] or 0.0) or float(i["taux_cap_pct"] or 0.0)
    if hyp["taux_cap_sortie_pct"] and i["taux_cap_pct"] and abs(hyp["taux_cap_sortie_pct"] - i["taux_cap_pct"]) > 1e-9:
        notes.append(f"Taux de cap de sortie du scénario ({hyp['taux_cap_sortie_pct']:g} %) au lieu de celui du rapport ({i['taux_cap_pct']:g} %).")

    # Revenus et dépenses de l'an 1 (barème SCHL) : part fixe indexée sur les dépenses, part en % des revenus.
    rb1 = float(i["loyers_bruts_mensuels"]) * 12.0
    source = fp0.get("source_revenus_nets")
    if schl:
        fixes1 = sum(float(schl.get(k) or 0.0) for k in ("taxes_municipales", "taxes_scolaires", "assurances", "energie", "concierge", "entretien"))
        prop1 = sum(float(schl.get(k) or 0.0) for k in ("inoccupation", "gestion", "autres_normalisations"))
        taux_prop = (prop1 / rb1) if rb1 > 0 else 0.0
    else:
        fixes1 = taux_prop = 0.0
        if rb1 <= 0:
            notes.append("Aucun loyer : revenus nets à zéro dans la projection.")
    loyers_stab = float(i.get("loyers_stabilises_mensuels") or 0.0) * 12.0
    if reno and loyers_stab <= 0:
        if cap > 0 and vf > 0:
            notes.append("Loyers stabilisés non saisis : après les travaux, revenus nets estimés = valeur future × taux de cap.")
        else:
            notes.append("Loyers stabilisés non saisis et pas de taux de cap : après les travaux, les loyers actuels indexés servent de revenus.")
    if not reno and cap <= 0 and source:
        notes.append("Pas de taux de cap : la valeur suit les revenus nets (valeur d'aujourd'hui × revenus nets ÷ revenus nets de l'an 1).")

    # Prêts : Kratos quand lié, sinon la dette de la fiche aux conditions de la fiche ou par défaut.
    if prets:
        liste = prets
    else:
        liste = [{
            "solde": float(i["dette"] or 0.0), "taux_pct": (float(i.get("taux_dette_pct") or 0.0) or hyp["taux_dette_defaut_pct"]),
            "mois_restants": int((float(i.get("amortissement_ans") or 0.0) or hyp["amortissement_defaut_ans"]) * 12),
            "paiement_mensuel": 0.0, "composition": "semi", "interet_seulement": bool(i.get("interet_seulement")),
            "conversion_annee": (n_stab + 1) if reno else 2, "fin_terme_annee": None,
        }]
        if float(i["dette"] or 0.0) > 0:
            notes.append("Dette sans hypothèque Kratos : " + (
                f"intérêts seulement puis prêt amorti à {liste[0]['taux_pct']:g} % sur {liste[0]['mois_restants'] // 12} ans"
                if liste[0]["interet_seulement"] else f"prêt amorti à {liste[0]['taux_pct']:g} % sur {liste[0]['mois_restants'] // 12} ans") + ".")
    sims = [simuler_pret(p, horizon, hyp) for p in liste]
    if any(p.get("interet_seulement") for p in liste):
        notes.append("Prêt intérêts seulement : devient un prêt amorti (taux de renouvellement ou par défaut, amortissement par défaut) "
                     "à la fin de son terme, ou à la stabilisation de l'immeuble.")

    dette0 = sum(float(p.get("solde") or 0.0) for p in liste)
    valeur0 = float(fp0["valeur"] or 0.0)
    rn1 = float(fp0["revenus_nets"] or 0.0) if source else 0.0
    annees: List[Dict[str, Any]] = []
    cf_cumule = capital_cumule = 0.0
    for n in range(1, horizon + 1):
        stabilise_n = (not reno) or (n >= n_stab)
        if reno and stabilise_n and loyers_stab > 0:
            rb = loyers_stab * (1.0 + gl) ** max(n - max(n_stab, 1), 0)
        else:
            rb = rb1 * (1.0 + gl) ** (n - 1)
        fixes = fixes1 * (1.0 + gd) ** (n - 1)
        if source == "saisis":
            rn = float(i["revenus_nets_annuels"]) * (1.0 + gl) ** (n - 1)
            depenses = max(rb - rn, 0.0)
        elif reno and stabilise_n and loyers_stab <= 0 and cap > 0 and vf > 0:
            rn = vf * cap / 100.0 * (1.0 + gl) ** max(n - max(n_stab, 1), 0)
            depenses = max(rb - rn, 0.0)
        else:
            depenses = fixes + rb * taux_prop
            rn = rb - depenses
        d = {"service": 0.0, "capital": 0.0, "interets": 0.0, "solde": 0.0}
        for s in sims:
            for k in d:
                d[k] += s[n - 1][k]
        # Valeur en fin d'année.
        if reno and not stabilise_n:
            avance = min(mois_ecoules + 12 * n, mois_prevus) / mois_prevus
            valeur = cout + (vf - cout) * avance if vf > 0 else cout
            methode = "coût + plus-value linéaire"
        elif reno and stabilise_n:
            if loyers_stab > 0 and cap > 0:
                valeur, methode = rn / (cap / 100.0), "revenus nets stabilisés ÷ taux de cap"
            elif vf > 0:
                valeur, methode = vf * (1.0 + gl) ** max(n - max(n_stab, 1), 0), "valeur future indexée"
            else:
                valeur, methode = cout, "coût du projet"
        elif cap > 0 and rn > 0:
            valeur, methode = rn / (cap / 100.0), "revenus nets ÷ taux de cap"
        else:
            valeur = valeur0 * (rn / rn1) if rn1 > 0 and rn > 0 else valeur0
            methode = "valeur d'aujourd'hui indexée sur les revenus nets"
        prorata = prorata1 if n == 1 else 1.0
        cash_flow = (rn - d["service"]) * prorata
        cf_cumule += cash_flow
        capital_cumule += d["capital"] * prorata
        annees.append({
            "annee": annee_depart + n - 1, "n": n, "en_renovation": bool(reno and not stabilise_n), "prorata": _r(100.0 * prorata),
            "revenus_bruts": _r(rb * prorata), "depenses": _r(depenses * prorata), "revenus_nets": _r(rn * prorata),
            "service_dette": _r(d["service"] * prorata), "interets": _r(d["interets"] * prorata), "capital_rembourse": _r(d["capital"] * prorata),
            "cash_flow": _r(cash_flow), "cash_flow_cumule": _r(cf_cumule), "solde": _r(d["solde"]),
            "valeur": _r(valeur), "methode": methode, "equite": _r(valeur - d["solde"]),
        })
    if acquis_an1:
        # Entre dans le fonds pendant l'an 1 : le capital de départ est la mise (coût − dette).
        equite0 = max(cout - dette0, 0.0)
        valeur_entree = cout
        if cout <= 0:
            notes.append("Acquisition de l'année sans coût de projet : capital de départ nul.")
    else:
        equite0 = valeur0 - dette0
        valeur_entree = valeur0
    eq_h = annees[-1]["equite"] if annees else equite0
    flux = [-equite0] + [a["cash_flow"] for a in annees]
    if annees:
        flux[-1] += eq_h
    tri = _irr(flux) if equite0 > 0 else None
    gain_total = eq_h + cf_cumule - equite0
    return {
        "id": i["id"], "nom": i["nom"] or "Sans nom", "kratos_immeuble_id": i.get("kratos_immeuble_id"),
        "dans_le_fonds": bool(i["dans_le_fonds"]), "phase": i["phase"], "acquise_cette_annee": acquis_an1,
        "date_acquisition": pa.get("date"), "annee_stabilisation": (annee_depart + n_stab - 1) if reno and n_stab >= 1 else None,
        "depart": {"valeur": _r(valeur0 if not acquis_an1 else cout), "cout_projet": _r(cout), "dette": _r(dette0), "equite": _r(equite0),
                   "revenus_nets": _r(rn1), "taux_cap_pct": _r(cap), "nb_prets": len([p for p in liste if (p.get("solde") or 0) > 0]),
                   "prets_kratos": bool(prets), "valeur_entree": _r(valeur_entree)},
        "annees": annees,
        "sommaire": {
            "equite_depart": _r(equite0), "equite_horizon": _r(eq_h), "cash_flow_cumule": _r(cf_cumule),
            "capital_rembourse": _r(capital_cumule), "plus_value": _r((annees[-1]["valeur"] if annees else valeur0) - valeur_entree),
            "gain_total": _r(gain_total), "multiple": (_r((eq_h + cf_cumule) / equite0) if equite0 > 0 else None),
            "rendement_total_pct": _pct(gain_total, equite0), "annualise_pct": (_annualise((eq_h + cf_cumule) / equite0, horizon) if equite0 > 0 else None),
            "tri_pct": tri,
        },
        "notes": notes,
    }


# ─── Le fonds ───────────────────────────────────────────────────────────────

def calculer_performance(data: Dict[str, Any], prets: Optional[Dict[int, List[Dict[str, Any]]]] = None,
                         achats: Optional[Dict[int, Dict[str, Any]]] = None, bareme: Optional[Dict[str, Any]] = None,
                         aujourd_hui: Optional[date] = None) -> Dict[str, Any]:
    """Projection du fonds (immeubles « dans le fonds ») et de chaque projet,
    selon les hypothèses ``projection`` du scénario."""
    d = svc.normaliser(data)
    hyp = d["projection"]
    regles = d["part_des_gains"]
    annee_depart = int(d["annee"])
    horizon = int(hyp["horizon_annees"])
    auj = aujourd_hui or date.today()
    prets = prets or {}
    achats = achats or {}
    projets = []
    for i in d["immeubles"]:
        kid = i.get("kratos_immeuble_id")
        projets.append(_projeter_immeuble(i, bareme, prets.get(kid) if kid else None, hyp, annee_depart, horizon))

    fonds_projets = [p for p in projets if p["dans_le_fonds"]]
    cash = float(d["fonds"]["cash"] or 0.0)
    van0 = sum(p["depart"]["equite"] for p in fonds_projets if not p["acquise_cette_annee"]) + cash
    valeur_prec = sum(p["depart"]["valeur"] for p in fonds_projets if not p["acquise_cette_annee"])
    prix_part0 = float(hyp["prix_part_depart"] or 0.0)
    parts_total = (van0 / prix_part0) if prix_part0 > 0 and van0 > 0 else 0.0
    parts_nous = parts_total * float(hyp["part_nos_holdings_depart_pct"] or 0.0) / 100.0
    van_prec = van0
    annees: List[Dict[str, Any]] = []
    flux = [-van0]
    cumul = {"cash_flow": 0.0, "frais_fonds": 0.0, "capital_rembourse": 0.0, "plus_value": 0.0, "gain": 0.0,
             "part_nous": 0.0, "part_investisseurs": 0.0, "capital_entre": 0.0}
    for n in range(1, horizon + 1):
        valeur = dettes = rb = dep = rn = service = capital = cf = 0.0
        capital_entre = cout_entrees = 0.0
        for p in fonds_projets:
            a = p["annees"][n - 1]
            valeur += a["valeur"]
            dettes += a["solde"]
            rb += a["revenus_bruts"]
            dep += a["depenses"]
            rn += a["revenus_nets"]
            service += a["service_dette"]
            capital += a["capital_rembourse"]
            cf += a["cash_flow"]
            if n == 1 and p["acquise_cette_annee"]:
                capital_entre += p["depart"]["equite"]
                cout_entrees += p["depart"]["valeur_entree"]
        frais_fonds = (van_prec + capital_entre) * float(d["fonds"]["taux_pct"] or 0.0) / 100.0
        cash_prec = cash
        cash = cash + cf - frais_fonds
        van = valeur + cash - dettes
        gain = van - van_prec - capital_entre
        base = van_prec + capital_entre
        part = partager_annee(van_prec, capital_entre, gain, parts_total, parts_nous, regles)
        parts_total, parts_nous = part["parts_total"], part["parts_nous"]
        plus_value = valeur - valeur_prec - cout_entrees
        flux.append(-capital_entre)
        for k, v in (("cash_flow", cf), ("frais_fonds", frais_fonds), ("capital_rembourse", capital), ("plus_value", plus_value),
                     ("gain", gain), ("part_nous", part["part_nous"]), ("part_investisseurs", part["part_investisseurs"]),
                     ("capital_entre", capital_entre)):
            cumul[k] += v
        annees.append({
            "annee": annee_depart + n - 1, "n": n,
            "revenus_bruts": _r(rb), "depenses": _r(dep), "revenus_nets": _r(rn), "service_dette": _r(service),
            "capital_rembourse": _r(capital), "frais_fonds": _r(frais_fonds), "cash_flow": _r(cf), "cash_net": _r(cf - frais_fonds), "cash": _r(cash),
            "valeur": _r(valeur), "dettes": _r(dettes), "van_debut": _r(van_prec), "capital_entre": _r(capital_entre), "van": _r(van),
            "gain": _r(gain), "rendement_pct": _pct(gain, base) if gain >= 0 else (_r(100.0 * gain / base) if base > 0 else None),
            "sources": {"plus_value": _r(plus_value), "capital_rembourse": _r(capital), "cash": _r(cash - cash_prec)},
            "partage": {k: _r(part[k]) for k in ("tranche_investisseurs", "tranche_nous", "reste", "part_nous", "part_investisseurs")},
            "prix_part": _r(part["prix_part"]), "rendement_part_pct": _r(part["rendement_part_pct"]),
            "parts_total": _r(part["parts_total"]), "parts_entrees": _r(part["parts_entrees"]), "nouvelles_parts_nous": _r(part["nouvelles_parts_nous"]),
            "parts_nous": _r(part["parts_nous"]), "pct_nous": _r(part["pct_nous"]),
        })
        van_prec, valeur_prec = van, valeur
    if annees:
        flux[-1] += annees[-1]["van"]
    rendements = [a["rendement_pct"] for a in annees if a["rendement_pct"] is not None]
    prod = 1.0
    for r_ in rendements:
        prod *= (1.0 + r_ / 100.0)
    prix_h = annees[-1]["prix_part"] if annees else prix_part0
    sommaire = {
        "van_depart": _r(van0), "van_horizon": _r(annees[-1]["van"] if annees else van0), "capital_entre": _r(cumul["capital_entre"]),
        "gain_total": _r(cumul["gain"]), "plus_value": _r(cumul["plus_value"]), "capital_rembourse": _r(cumul["capital_rembourse"]),
        "cash_flow_cumule": _r(cumul["cash_flow"]), "frais_fonds_cumules": _r(cumul["frais_fonds"]), "cash_horizon": _r(cash),
        "part_nous_total": _r(cumul["part_nous"]), "part_investisseurs_total": _r(cumul["part_investisseurs"]),
        "tri_pct": _irr(flux) if van0 > 0 else None,
        "rendement_moyen_pct": (_r(100.0 * (prod ** (1.0 / len(rendements)) - 1.0)) if rendements and prod > 0 else None),
        "prix_part_depart": _r(prix_part0), "prix_part_horizon": _r(prix_h),
        "rendement_part_annualise_pct": (_annualise(prix_h / prix_part0, horizon) if prix_part0 > 0 and prix_h > 0 else None),
        "parts_depart": _r(van0 / prix_part0 if prix_part0 > 0 else 0.0), "parts_horizon": _r(parts_total), "parts_nous_horizon": _r(parts_nous),
        "pct_nous_horizon": _r(100.0 * parts_nous / parts_total if parts_total > 0 else 0.0),
        "nb_immeubles": len(fonds_projets), "nb_hors_fonds": len(projets) - len(fonds_projets),
        "nb_acquisitions_an1": len([p for p in fonds_projets if p["acquise_cette_annee"]]),
    }

    # ── Historique (réel) : ce que Kratos a déjà pour reconstruire le passé, et ce qui manque.
    historique = []
    for p in projets:
        kid = p.get("kratos_immeuble_id")
        if not kid:
            continue
        a = achats.get(kid) or {}
        tous = a.get("prets") or []
        manques: List[str] = []
        if not a.get("date"):
            manques.append("date d'achat")
        if not (a.get("prix") or 0) > 0:
            manques.append("prix d'achat")
        refi = any(str(x.get("status") or "") == "refinancee" for x in tous)
        premier = None
        for x in tous:
            if x.get("date_debut") and (premier is None or x["date_debut"] < premier["date_debut"]):
                premier = x
        if a.get("date") and premier and premier["date_debut"] and (date.fromisoformat(premier["date_debut"]) - date.fromisoformat(a["date"])).days > 183:
            refi = True
        if refi or (a.get("date") and not premier):
            if not any(str(x.get("status") or "") == "refinancee" for x in tous):
                manques.append("prêt initial à l'achat (refinancé depuis)")
            manques.append("cash sorti aux refinancements")
        manques.append("travaux et frais payés, par date")
        historique.append({
            "id": p["id"], "nom": p["nom"], "kratos_immeuble_id": kid, "prix_achat": _r(a.get("prix") or 0.0), "date_achat": a.get("date"),
            "nb_prets": len(tous), "refinance": refi,
            "premier_pret": ({"montant": _r(premier.get("montant") or 0.0), "date": premier.get("date_debut"), "status": premier.get("status")} if premier else None),
            "manques": manques, "complet": not manques,
        })

    return {
        "annee_depart": annee_depart, "horizon": horizon, "hypotheses": hyp, "regles": regles, "aujourd_hui": auj.isoformat(),
        "fonds": {"annees": annees, "sommaire": sommaire, "cash_depart": _r(float(d["fonds"]["cash"] or 0.0)), "taux_frais_pct": float(d["fonds"]["taux_pct"] or 0.0)},
        "projets": projets, "historique": historique,
    }


__all__ = ["calculer_performance", "partage_gain", "partager_annee", "simuler_pret"]
