"""Gestion d'entreprise → Performance du fonds (v3, 2026-11-09 : refinancements, cash remis,
fourchette d'incertitude ; v2 du 2026-11-06 : projection année par année).

Phil : « il faut que tout ça soit annualisé » ; « un fonds c'est toujours sur le
capital du fonds… il faut que ça reflète [le document] » ; puis (2026-11-09) :
« on a beaucoup d'argent qui dort… on ferait des acquisitions… faudrait quasiment
le voir comme si on l'avait remboursé » ; « on ne peut pas savoir d'avance le taux
d'intérêt et le taux de capitalisation → prendre ceux du dernier rapport ou du
dernier financement… avec un plus ou moins » ; « deux prêts financés le même jour
n'auront pas du tout le même taux » ; « les amortissements varient d'un prêt à
l'autre ».

Le document « Le Fonds MGV d'investissements » (nov. 2026) :
- p. 11 : VAN = valeur des immeubles + cash − dettes ; stabilisé = revenus nets
  (barèmes SCHL) ÷ taux de cap du rapport ; en rénovation = coût du projet +
  plus-value linéaire vers la valeur future ;
- p. 12 : au refi, nouveau prêt sur la valeur stabilisée, le cash sort ;
- p. 14 : le gain d'une année = VAN fin − VAN début : loyers en hausse (valeur),
  capital remboursé, cash gardé ;
- p. 7-8 : « année à 15 % » = gain ÷ VAN de départ ; partage 7 % / 3 % / 70-30 ;
  les investisseurs gardent leurs parts (le prix monte), nous recevons de nouvelles
  parts au nouveau prix. Reproduit la p. 8 (test) ;
- p. 9 : l'argent de nos holdings est traité comme celui d'un investisseur ;
- p. 17 : le cash des refis sert à racheter des parts ;
- p. 20 : frais de gestion du fonds 1,5 %/an de la VAN, payés en cash.

Règles de projection :
- Aucun taux global : à l'échéance de son terme, chaque prêt garde SON taux (dernier
  financement). Un prêt intérêts seulement (prêteur B, privé) qui devient une
  hypothèque, et une dette sans hypothèque Kratos ni conditions saisies, prennent
  les conditions MOYENNES des hypothèques conventionnelles du fonds (taux et
  amortissement pondérés par le solde), dites clairement dans les notes.
- Refinancement (option) : à l'échéance du terme d'un prêt, à la stabilisation d'un
  immeuble en rénovation, ou à une cadence fixe pour un prêt sans terme connu, le
  prêt est remplacé par un nouveau à X % de la valeur de l'immeuble (frais en %) ;
  le cash sorti est remis aux investisseurs (compté comme rendement, « comme si on
  l'avait remboursé ») ou gardé dans le fonds.
- Incertitude : ± N points appliqués aux taux de cap des années futures et aux taux
  des prêts renouvelés / nouveaux → fourchette prudente / favorable autour du
  scénario central.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from app.services import revenus_depenses as svc
from app.services.hypotheque_calc import taux_mensuel

#: Quand le fonds n'a AUCUNE hypothèque conventionnelle connue, conditions de repli, toujours
#: écrites dans les notes de l'immeuble concerné (jamais silencieuses).
REPLI_PRET = {"taux_pct": 5.0, "amortissement_mois": 300}


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
                   regles: Dict[str, Any], distributions: float = 0.0) -> Dict[str, float]:
    """Une fin d'exercice en parts (doc p. 8) : le capital entré dans l'année achète
    des parts au prix de départ ; la part des investisseurs fait monter le prix de
    TOUTES les parts existantes (moins le cash qui leur a été remis) ; notre part est
    payée en nouvelles parts à ce nouveau prix. Prix × parts = VAN de fin, exactement.
    ``distributions`` = cash remis aux porteurs de parts pendant l'année (compté dans
    le gain, sorti de la VAN) : il revient par part et entre dans le rendement de la part."""
    prix_debut = (van_debut / parts_total) if parts_total > 0 else 0.0
    parts_entrees = (capital_entre / prix_debut) if prix_debut > 0 else 0.0
    parts_apres_entree = parts_total + parts_entrees
    p = partage_gain(gain, van_debut + capital_entre, regles)
    if parts_apres_entree > 0:
        prix_fin = max((van_debut + capital_entre + p["part_investisseurs"] - distributions) / parts_apres_entree, 0.0)
    else:
        prix_fin = 0.0
    nouvelles = (p["part_nous"] / prix_fin) if prix_fin > 0 else 0.0
    parts_fin = parts_apres_entree + nouvelles
    dist_par_part = (distributions / parts_apres_entree) if parts_apres_entree > 0 else 0.0
    return {
        **p, "prix_part_debut": prix_debut, "prix_part": prix_fin, "parts_entrees": parts_entrees,
        "nouvelles_parts_nous": nouvelles, "parts_total": parts_fin, "parts_nous": parts_nous + nouvelles,
        "pct_nous": (100.0 * (parts_nous + nouvelles) / parts_fin) if parts_fin > 0 else 0.0,
        "distribution_par_part": dist_par_part,
        "rendement_part_pct": (100.0 * ((prix_fin + dist_par_part) / prix_debut - 1.0)) if prix_debut > 0 else 0.0,
    }


# ─── Prêts ──────────────────────────────────────────────────────────────────

def _pmt(solde: float, taux_pct: float, n_mois: int, composition: str) -> float:
    if solde <= 0 or n_mois <= 0:
        return 0.0
    i = taux_mensuel(taux_pct, composition)
    if i <= 0:
        return solde / n_mois
    return solde * i / (1.0 - (1.0 + i) ** (-n_mois))


def conditions_moyennes(prets_par_immeuble: Dict[int, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Taux et amortissement moyens (pondérés par le solde) des hypothèques
    CONVENTIONNELLES du fonds — la référence pour un prêt inconnu ou pour la suite
    d'un prêt intérêts seulement (Phil : « prendre ceux du dernier financement »)."""
    poids = taux = amort = 0.0
    n = 0
    for liste in (prets_par_immeuble or {}).values():
        for p in liste:
            solde = float(p.get("solde") or 0.0)
            if p.get("interet_seulement") or solde <= 0 or not p.get("taux_pct") or not p.get("amortissement_mois"):
                continue
            poids += solde
            taux += solde * float(p["taux_pct"])
            amort += solde * float(p["amortissement_mois"])
            n += 1
    if poids <= 0:
        return {**REPLI_PRET, "nb_prets": 0, "source": f"aucune hypothèque conventionnelle connue dans le fonds : hypothèse {REPLI_PRET['taux_pct']:g} % sur {REPLI_PRET['amortissement_mois'] // 12} ans"}
    t, a = taux / poids, int(round(amort / poids))
    return {"taux_pct": round(t, 3), "amortissement_mois": a, "nb_prets": n,
            "source": f"moyenne pondérée des {n} hypothèque{'s' if n > 1 else ''} conventionnelle{'s' if n > 1 else ''} du fonds : {t:.2f} % sur {a // 12} ans"}


class PretSim:
    """Un prêt rejoué année par année (détention simple ou avec refinancements)."""

    def __init__(self, p: Dict[str, Any], reference: Dict[str, Any], variation: float = 0.0):
        self.solde = max(float(p.get("solde") or 0.0), 0.0)
        self.taux = float(p.get("taux_pct") or 0.0)
        self.comp = p.get("composition") or "semi"
        self.io = bool(p.get("interet_seulement"))
        self.n_rest = int(p.get("mois_restants") or 0)
        self.pmt = float(p.get("paiement_mensuel") or 0.0)
        self.fin_terme = p.get("fin_terme_annee")          # année dont la FIN est l'échéance du terme (0 = déjà échu)
        self.conv = p.get("conversion_annee")              # prêt IO sans terme connu : année où il devient amorti
        self.kratos = bool(p.get("kratos", True))
        self.ref = reference
        self.var = float(variation or 0.0)
        self.dernier_renouvellement = 0
        self.evenements: List[Dict[str, Any]] = []
        if not self.io and self.pmt <= 0 and self.n_rest > 0:
            self.pmt = _pmt(self.solde, self.taux, self.n_rest, self.comp)

    def echeance(self, n: int, cadence: int) -> bool:
        """Le terme (ou la période intérêts seulement) se termine-t-il juste avant l'année n ?"""
        if self.solde <= 0.005:
            return False
        if self.fin_terme is not None:
            if n == self.fin_terme + 1:
                return True
            # Après la première échéance : renouvellement à chaque cadence.
            return cadence > 0 and n > self.fin_terme + 1 and (n - 1 - self.fin_terme) % cadence == 0
        if self.io:
            return self.conv is not None and n == self.conv
        return cadence > 0 and n > 1 and (n - 1) % cadence == 0

    def debut_annee(self, n: int, valeur_prec: float, refi: Optional[Dict[str, Any]], stabilise: bool, cadence: int) -> Optional[Dict[str, Any]]:
        """Au début de l'année n : renouvellement du terme, fin d'un prêt intérêts
        seulement, refinancement si l'option est active et l'immeuble stabilisé."""
        if not self.echeance(n, cadence):
            return None
        etait_io = self.io
        # Taux de la suite : le sien pour une hypothèque conventionnelle (dernier financement), la
        # référence du fonds pour un prêt intérêts seulement ; ± l'incertitude.
        taux_suite = (self.taux if (not etait_io and self.taux > 0) else float(self.ref["taux_pct"])) + self.var
        taux_suite = max(taux_suite, 0.0)
        ev: Dict[str, Any] = {"annee_index": n, "type": "renouvellement", "ancien_solde": self.solde, "taux_pct": round(taux_suite, 3),
                              "nouveau_pret": self.solde, "cash_sorti": 0.0, "frais": 0.0}
        if etait_io:
            ev["type"] = "conversion"
            self.io = False
            self.n_rest = int(self.ref["amortissement_mois"])
        if refi and refi.get("actif") and stabilise and valeur_prec > 0:
            nouveau = valeur_prec * float(refi["ltv_pct"]) / 100.0
            frais = nouveau * float(refi.get("frais_pct") or 0.0) / 100.0
            if nouveau - frais > self.solde + 0.5:
                ev.update({"type": "refinancement", "nouveau_pret": nouveau, "cash_sorti": nouveau - frais - self.solde, "frais": frais,
                           "ltv_pct": float(refi["ltv_pct"]), "valeur": valeur_prec})
                self.solde = nouveau
                self.n_rest = int(self.ref["amortissement_mois"])
        self.taux = taux_suite
        self.comp = "semi"
        if self.n_rest <= 0:
            self.n_rest = int(self.ref["amortissement_mois"])
        self.pmt = _pmt(self.solde, self.taux, self.n_rest, self.comp)
        self.dernier_renouvellement = n
        self.evenements.append(ev)
        return ev

    def annee(self) -> Dict[str, float]:
        """Douze mois : service de dette, intérêts, capital remboursé, solde de fin."""
        service = capital = interets = 0.0
        if self.solde <= 0.005:
            return {"service": 0.0, "capital": 0.0, "interets": 0.0, "solde": 0.0}
        i = taux_mensuel(self.taux, self.comp) if self.taux > 0 else 0.0
        if self.io:
            interets = (self.pmt * 12.0) if self.pmt > 0 else self.solde * i * 12.0
            return {"service": interets, "capital": 0.0, "interets": interets, "solde": self.solde}
        for _ in range(12):
            if self.solde <= 0.005:
                break
            it = self.solde * i
            princ = max(self.pmt - it, 0.0)
            if self.n_rest <= 1 or princ > self.solde:
                princ = self.solde
            self.solde -= princ
            self.n_rest -= 1
            service += it + princ
            capital += princ
            interets += it
        return {"service": service, "capital": capital, "interets": interets, "solde": max(self.solde, 0.0)}


def simuler_pret(p: Dict[str, Any], horizon: int, reference: Optional[Dict[str, Any]] = None, variation: float = 0.0,
                 valeurs: Optional[List[float]] = None, refi: Optional[Dict[str, Any]] = None,
                 stabilise: Optional[Callable[[int], bool]] = None, cadence: int = 0) -> List[Dict[str, Any]]:
    """Un prêt seul, année par année (tests et outils) : ``valeurs[n-1]`` = valeur de
    l'immeuble au début de l'année n (pour les refinancements)."""
    sim = PretSim(p, reference or dict(REPLI_PRET), variation)
    out = []
    for n in range(1, horizon + 1):
        v = valeurs[n - 1] if valeurs and len(valeurs) >= n else 0.0
        ev = sim.debut_annee(n, v, refi, stabilise(n) if stabilise else True, cadence)
        a = sim.annee()
        a["evenement"] = ev
        out.append(a)
    return out


# ─── Un immeuble ────────────────────────────────────────────────────────────

def _projeter_immeuble(i: Dict[str, Any], bareme: Optional[Dict[str, Any]], prets: Optional[List[Dict[str, Any]]],
                       hyp: Dict[str, Any], reference: Dict[str, Any], annee_depart: int, horizon: int,
                       variation: float = 0.0) -> Dict[str, Any]:
    notes: List[str] = []
    gl = hyp["croissance_loyers_pct"] / 100.0
    gd = hyp["croissance_depenses_pct"] / 100.0
    refi = hyp.get("refinancement") or {}
    cadence = int(refi.get("cadence_ans") or 0) if refi.get("actif") else 0
    fp0 = svc.valeur_immeuble(i, bareme)
    schl = fp0.get("depenses_schl")
    reno = i["phase"] == "stabilisation"
    cout = float(fp0["cout_projet"] or 0.0)
    vf = float(i["valeur_future"] or 0.0)
    pa = svc.part_annee(i, annee_depart)
    acquis_an1 = bool(pa["acquise_cette_annee"])
    prorata1 = pa["part"] if acquis_an1 else 1.0

    mois_prevus = max(int(i["mois_prevus"] or 1), 1)
    mois_ecoules = int(i["mois_ecoules"] or 0)
    n_stab = max(math.ceil((mois_prevus - mois_ecoules) / 12.0), 0) if reno else 0
    cap0 = float(i["taux_cap_pct"] or 0.0)
    cap = (cap0 + variation) if cap0 > 0 else 0.0
    if variation and cap0 > 0:
        notes.append(f"Taux de cap des années futures : {cap:.2f} % ({cap0:g} % du rapport {'+' if variation > 0 else '−'} {abs(variation):g} point).")

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

    # Prêts : Kratos quand lié ; sinon la dette de la fiche aux conditions de la fiche, sinon la référence du fonds.
    if prets:
        liste = [dict(p, kratos=True) for p in prets]
    else:
        dette = float(i["dette"] or 0.0)
        taux_fiche = float(i.get("taux_dette_pct") or 0.0)
        amort_fiche = int(float(i.get("amortissement_ans") or 0.0) * 12)
        io = bool(i.get("interet_seulement"))
        liste = [{
            "solde": dette, "taux_pct": taux_fiche or float(reference["taux_pct"]),
            "mois_restants": amort_fiche or int(reference["amortissement_mois"]), "amortissement_mois": amort_fiche or int(reference["amortissement_mois"]),
            "paiement_mensuel": 0.0, "composition": "semi", "interet_seulement": io,
            "conversion_annee": (n_stab + 1) if reno else 2, "fin_terme_annee": None, "kratos": False,
        }]
        if dette > 0:
            if io:
                notes.append("Dette sans hypothèque Kratos, intérêts seulement" + (f" à {taux_fiche:g} %" if taux_fiche else f" ({reference['source']})")
                             + " ; devient une hypothèque amortie à la stabilisation.")
            elif taux_fiche and amort_fiche:
                notes.append(f"Dette sans hypothèque Kratos : conditions de la fiche, {taux_fiche:g} % sur {amort_fiche // 12} ans.")
            else:
                notes.append(f"Dette sans hypothèque Kratos et conditions non saisies dans la fiche : {reference['source']}.")
    sims = [PretSim(p, reference, variation) for p in liste]
    if any(p.get("interet_seulement") for p in liste):
        notes.append(f"Prêt intérêts seulement : à la fin de son terme (ou à la stabilisation), il devient une hypothèque amortie aux conditions de référence du fonds ({reference['source']}).")

    dette0 = sum(float(p.get("solde") or 0.0) for p in liste)
    valeur0 = float(fp0["valeur"] or 0.0)
    rn1 = float(fp0["revenus_nets"] or 0.0) if source else 0.0
    annees: List[Dict[str, Any]] = []
    cf_cumule = capital_cumule = cash_refi_cumule = frais_refi_cumule = 0.0
    valeur_prec = cout if acquis_an1 else valeur0
    for n in range(1, horizon + 1):
        stabilise_n = (not reno) or (n >= n_stab)
        # Début d'année : échéances, conversions, refinancements (sur la valeur de fin d'année précédente).
        evenements = []
        for s in sims:
            stabilise_debut = (not reno) or (n >= n_stab + 1)   # stabilisé à la fin de l'année précédente
            ev = s.debut_annee(n, valeur_prec, refi, stabilise_debut, cadence)
            if ev:
                evenements.append(ev)
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
            a = s.annee()
            for k in d:
                d[k] += a[k]
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
        cash_refi = sum(e["cash_sorti"] for e in evenements)
        frais_refi = sum(e["frais"] for e in evenements)
        cf_cumule += cash_flow
        capital_cumule += d["capital"] * prorata
        cash_refi_cumule += cash_refi
        frais_refi_cumule += frais_refi
        annees.append({
            "annee": annee_depart + n - 1, "n": n, "en_renovation": bool(reno and not stabilise_n), "prorata": _r(100.0 * prorata),
            "revenus_bruts": _r(rb * prorata), "depenses": _r(depenses * prorata), "revenus_nets": _r(rn * prorata),
            "service_dette": _r(d["service"] * prorata), "interets": _r(d["interets"] * prorata), "capital_rembourse": _r(d["capital"] * prorata),
            "cash_flow": _r(cash_flow), "cash_flow_cumule": _r(cf_cumule), "solde": _r(d["solde"]),
            "valeur": _r(valeur), "methode": methode, "equite": _r(valeur - d["solde"]),
            "cash_refi": _r(cash_refi), "frais_refi": _r(frais_refi),
            "evenements": [{**e, "annee": annee_depart + n - 1, "ancien_solde": _r(e["ancien_solde"]), "nouveau_pret": _r(e["nouveau_pret"]),
                            "cash_sorti": _r(e["cash_sorti"]), "frais": _r(e["frais"]), "valeur": _r(e.get("valeur") or 0.0)} for e in evenements],
        })
        valeur_prec = valeur
    if acquis_an1:
        equite0 = max(cout - dette0, 0.0)
        valeur_entree = cout
        if cout <= 0:
            notes.append("Acquisition de l'année sans coût de projet : capital de départ nul.")
    else:
        equite0 = valeur0 - dette0
        valeur_entree = valeur0
    eq_h = annees[-1]["equite"] if annees else equite0
    # Flux du projet : capital de départ, puis cash-flow + cash sorti aux refis, équité à l'horizon.
    flux = [-equite0] + [a["cash_flow"] + a["cash_refi"] for a in annees]
    if annees:
        flux[-1] += eq_h
    tri = _irr(flux) if equite0 > 0 else None
    gain_total = eq_h + cf_cumule + cash_refi_cumule - equite0
    nb_refis = sum(1 for a in annees for e in a["evenements"] if e["type"] == "refinancement")
    return {
        "id": i["id"], "nom": i["nom"] or "Sans nom", "kratos_immeuble_id": i.get("kratos_immeuble_id"),
        "dans_le_fonds": bool(i["dans_le_fonds"]), "phase": i["phase"], "acquise_cette_annee": acquis_an1,
        "date_acquisition": pa.get("date"), "annee_stabilisation": (annee_depart + n_stab - 1) if reno and n_stab >= 1 else None,
        "depart": {"valeur": _r(valeur0 if not acquis_an1 else cout), "cout_projet": _r(cout), "dette": _r(dette0), "equite": _r(equite0),
                   "revenus_nets": _r(rn1), "taux_cap_pct": _r(cap0), "nb_prets": len([p for p in liste if (p.get("solde") or 0) > 0]),
                   "prets_kratos": bool(prets), "valeur_entree": _r(valeur_entree)},
        "annees": annees,
        "sommaire": {
            "equite_depart": _r(equite0), "equite_horizon": _r(eq_h), "cash_flow_cumule": _r(cf_cumule),
            "cash_refi_cumule": _r(cash_refi_cumule), "frais_refi_cumules": _r(frais_refi_cumule), "nb_refinancements": nb_refis,
            "capital_rembourse": _r(capital_cumule), "plus_value": _r((annees[-1]["valeur"] if annees else valeur0) - valeur_entree),
            "gain_total": _r(gain_total), "multiple": (_r((eq_h + cf_cumule + cash_refi_cumule) / equite0) if equite0 > 0 else None),
            "rendement_total_pct": _pct(gain_total, equite0),
            "annualise_pct": (_annualise((eq_h + cf_cumule + cash_refi_cumule) / equite0, horizon) if equite0 > 0 else None),
            "tri_pct": tri,
        },
        "notes": notes,
    }


# ─── Le fonds ───────────────────────────────────────────────────────────────

def _calculer(d: Dict[str, Any], prets: Dict[int, List[Dict[str, Any]]], bareme: Optional[Dict[str, Any]],
              reference: Dict[str, Any], variation: float) -> Dict[str, Any]:
    hyp = d["projection"]
    regles = d["part_des_gains"]
    annee_depart = int(d["annee"])
    horizon = int(hyp["horizon_annees"])
    refi = hyp.get("refinancement") or {}
    cash_remis = bool(refi.get("cash_remis", True))
    projets = [_projeter_immeuble(i, bareme, prets.get(i.get("kratos_immeuble_id")) if i.get("kratos_immeuble_id") else None,
                                  hyp, reference, annee_depart, horizon, variation) for i in d["immeubles"]]
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
    cumul = {k: 0.0 for k in ("cash_flow", "frais_fonds", "capital_rembourse", "plus_value", "gain", "part_nous", "part_investisseurs",
                              "capital_entre", "cash_refi", "frais_refi", "distributions")}
    nb_refis = 0
    for n in range(1, horizon + 1):
        valeur = dettes = rb = dep = rn = service = capital = cf = cash_refi = frais_refi = 0.0
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
            cash_refi += a["cash_refi"]
            frais_refi += a["frais_refi"]
            nb_refis += sum(1 for e in a["evenements"] if e["type"] == "refinancement")
            if n == 1 and p["acquise_cette_annee"]:
                capital_entre += p["depart"]["equite"]
                cout_entrees += p["depart"]["valeur_entree"]
        frais_fonds = (van_prec + capital_entre) * float(d["fonds"]["taux_pct"] or 0.0) / 100.0
        cash_net = cf - frais_fonds
        cash_prec = cash
        if cash_remis:
            # Phil : « de l'argent qui dort… le voir comme si on l'avait remboursé » : le cash de l'année
            # et le cash des refis sont remis aux porteurs de parts ; une année négative puise dans la réserve.
            distributions = cash_refi + max(cash_net, 0.0)
            cash = cash + min(cash_net, 0.0)
        else:
            distributions = 0.0
            cash = cash + cash_net + cash_refi
        van = valeur + cash - dettes
        gain = van - van_prec - capital_entre + distributions
        base = van_prec + capital_entre
        part = partager_annee(van_prec, capital_entre, gain, parts_total, parts_nous, regles, distributions)
        parts_total, parts_nous = part["parts_total"], part["parts_nous"]
        plus_value = valeur - valeur_prec - cout_entrees
        flux.append(distributions - capital_entre)
        for k, v in (("cash_flow", cf), ("frais_fonds", frais_fonds), ("capital_rembourse", capital), ("plus_value", plus_value), ("gain", gain),
                     ("part_nous", part["part_nous"]), ("part_investisseurs", part["part_investisseurs"]), ("capital_entre", capital_entre),
                     ("cash_refi", cash_refi), ("frais_refi", frais_refi), ("distributions", distributions)):
            cumul[k] += v
        annees.append({
            "annee": annee_depart + n - 1, "n": n,
            "revenus_bruts": _r(rb), "depenses": _r(dep), "revenus_nets": _r(rn), "service_dette": _r(service),
            "capital_rembourse": _r(capital), "frais_fonds": _r(frais_fonds), "cash_flow": _r(cf), "cash_net": _r(cash_net),
            "cash_refi": _r(cash_refi), "frais_refi": _r(frais_refi), "distributions": _r(distributions), "cash": _r(cash),
            "valeur": _r(valeur), "dettes": _r(dettes), "van_debut": _r(van_prec), "capital_entre": _r(capital_entre), "van": _r(van),
            "gain": _r(gain), "rendement_pct": (_r(100.0 * gain / base) if base > 0 else None),
            "sources": {"plus_value": _r(plus_value), "capital_rembourse": _r(capital), "cash": _r(cash - cash_prec + distributions)},
            "partage": {k: _r(part[k]) for k in ("tranche_investisseurs", "tranche_nous", "reste", "part_nous", "part_investisseurs")},
            "prix_part": _r(part["prix_part"]), "distribution_par_part": round(part["distribution_par_part"], 4),
            "rendement_part_pct": _r(part["rendement_part_pct"]),
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
    dist_par_part_total = sum(a["distribution_par_part"] for a in annees)
    # Rendement annualisé d'une part = TRI des flux d'un investisseur : −prix au départ, cash remis par part chaque
    # année, prix de la part à l'horizon (le cash remis tôt compte plus qu'une simple somme).
    flux_part = [-prix_part0] + [a["distribution_par_part"] for a in annees]
    if annees:
        flux_part[-1] += prix_h
    sommaire = {
        "van_depart": _r(van0), "van_horizon": _r(annees[-1]["van"] if annees else van0), "capital_entre": _r(cumul["capital_entre"]),
        "gain_total": _r(cumul["gain"]), "plus_value": _r(cumul["plus_value"]), "capital_rembourse": _r(cumul["capital_rembourse"]),
        "cash_flow_cumule": _r(cumul["cash_flow"]), "frais_fonds_cumules": _r(cumul["frais_fonds"]), "cash_horizon": _r(cash),
        "cash_refi_total": _r(cumul["cash_refi"]), "frais_refi_total": _r(cumul["frais_refi"]), "nb_refinancements": nb_refis,
        "distributions_total": _r(cumul["distributions"]), "cash_remis": cash_remis,
        "part_nous_total": _r(cumul["part_nous"]), "part_investisseurs_total": _r(cumul["part_investisseurs"]),
        "tri_pct": _irr(flux) if van0 > 0 else None,
        "rendement_moyen_pct": (_r(100.0 * (prod ** (1.0 / len(rendements)) - 1.0)) if rendements and prod > 0 else None),
        "prix_part_depart": _r(prix_part0), "prix_part_horizon": _r(prix_h), "distributions_par_part": _r(dist_par_part_total),
        "rendement_part_annualise_pct": (_irr(flux_part) if prix_part0 > 0 else None),
        "valeur_totale_par_part": _r(prix_h + dist_par_part_total),
        "parts_depart": _r(van0 / prix_part0 if prix_part0 > 0 else 0.0), "parts_horizon": _r(parts_total), "parts_nous_horizon": _r(parts_nous),
        "pct_nous_horizon": _r(100.0 * parts_nous / parts_total if parts_total > 0 else 0.0),
        "nb_immeubles": len(fonds_projets), "nb_hors_fonds": len(projets) - len(fonds_projets),
        "nb_acquisitions_an1": len([p for p in fonds_projets if p["acquise_cette_annee"]]),
    }
    return {"projets": projets, "annees": annees, "sommaire": sommaire}


def calculer_performance(data: Dict[str, Any], prets: Optional[Dict[int, List[Dict[str, Any]]]] = None,
                         achats: Optional[Dict[int, Dict[str, Any]]] = None, bareme: Optional[Dict[str, Any]] = None,
                         aujourd_hui: Optional[date] = None) -> Dict[str, Any]:
    """Projection du fonds (immeubles « dans le fonds ») et de chaque projet, selon
    les hypothèses ``projection`` du scénario, avec la fourchette prudente / favorable."""
    d = svc.normaliser(data)
    hyp = d["projection"]
    auj = aujourd_hui or date.today()
    prets = prets or {}
    achats = achats or {}
    reference = conditions_moyennes(prets)
    central = _calculer(d, prets, bareme, reference, 0.0)
    pts = float(hyp.get("incertitude_points") or 0.0)
    fourchette = None
    if pts > 0:
        cles = ("van_horizon", "tri_pct", "rendement_moyen_pct", "prix_part_horizon", "rendement_part_annualise_pct",
                "pct_nous_horizon", "distributions_total", "gain_total")
        prudent = _calculer(d, prets, bareme, reference, +pts)["sommaire"]
        favorable = _calculer(d, prets, bareme, reference, -pts)["sommaire"]
        fourchette = {"points": pts, "prudent": {k: prudent[k] for k in cles}, "favorable": {k: favorable[k] for k in cles}}

    # ── Historique (réel) : ce que Kratos a déjà pour reconstruire le passé, et ce qui manque.
    historique = []
    for p in central["projets"]:
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
        "annee_depart": int(d["annee"]), "horizon": int(hyp["horizon_annees"]), "hypotheses": hyp, "regles": d["part_des_gains"],
        "aujourd_hui": auj.isoformat(), "reference_prets": reference,
        "fonds": {"annees": central["annees"], "sommaire": central["sommaire"], "cash_depart": _r(float(d["fonds"]["cash"] or 0.0)),
                  "taux_frais_pct": float(d["fonds"]["taux_pct"] or 0.0), "fourchette": fourchette},
        "projets": central["projets"], "historique": historique,
    }


__all__ = ["calculer_performance", "partage_gain", "partager_annee", "simuler_pret", "conditions_moyennes", "PretSim", "REPLI_PRET"]
