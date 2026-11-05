"""Gestion d'entreprise → Performance du fonds et des projets (2026-11-05, v1).

Phil : « commençons par ça ! au début pas de registre d'investisseurs, mais
surtout les rendements par projet et ceux du fonds ».

PRÉVU = la fiche de l'immeuble dans le scénario « Revenus et dépenses »
(coût du projet, valeur future ou rapport, revenus nets SCHL, dette).
RÉEL = Kratos : prix et date d'achat, loyers de toutes les unités, dépenses
réelles, rapport d'évaluation et taux de cap, dette DU JOUR, hypothèques
(capital initial, paiement).

Rendements volontairement simples et lisibles :
- mise de fonds = coût du projet − hypothèque initiale ;
- cash-flow = revenus nets SCHL − service de dette annuel ;
- gain d'équité = équité (valeur − dette du jour) − mise de fonds ;
- rendement total = gain ÷ mise ; cash-on-cash = cash-flow ÷ mise ;
- annualisé = (équité ÷ mise) ^ (1 / années depuis l'achat) − 1.
Le fonds = les immeubles « dans le fonds » ; part des gains sur le gain RÉEL
avec les règles du document (7 % investisseurs, 3 % à nous, reste 70/30).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from app.services import revenus_depenses as svc


def _r(x: Any) -> float:
    return round(float(x or 0.0), 2)


def _pct(num: float, den: float) -> Optional[float]:
    return _r(100.0 * num / den) if den and den > 0 else None


def _annees(depuis: Optional[str], au: date) -> Optional[float]:
    if not depuis:
        return None
    try:
        d = date.fromisoformat(str(depuis)[:10])
    except ValueError:
        return None
    a = (au - d).days / 365.25
    return round(a, 2) if a > 0 else None


def _annualise(multiple: float, annees: Optional[float]) -> Optional[float]:
    """Rendement annualisé (%) d'un multiple (valeur finale ÷ mise) ; None sous 3 mois."""
    if annees is None or annees < 0.25 or multiple <= 0:
        return None
    return _r(100.0 * (multiple ** (1.0 / annees) - 1.0))


def partage_gain(gain: float, capital: float, regles: Dict[str, Any]) -> Dict[str, float]:
    """Mêmes règles que la section « Part des gains » du scénario (doc p. 7), appliquées au gain RÉEL."""
    g, base = max(gain, 0.0), max(capital, 0.0)
    t1 = min(g, base * regles["seuil_investisseurs_pct"] / 100.0)
    t2 = min(max(g - t1, 0.0), base * regles["tranche_nous_pct"] / 100.0)
    reste = max(g - t1 - t2, 0.0)
    nous_reste = reste * regles["part_nous_pct"] / 100.0
    return {
        "gain": _r(g), "tranche_investisseurs": _r(t1), "tranche_nous": _r(t2), "reste": _r(reste),
        "part_nous": _r(t2 + nous_reste), "part_investisseurs": _r(t1 + (reste - nous_reste)),
    }


def _projet(i: Dict[str, Any], item: Optional[Dict[str, Any]], hypo: Optional[Dict[str, float]],
            achat: Optional[Dict[str, Any]], bareme: Optional[Dict[str, Any]], aujourd_hui: date) -> Dict[str, Any]:
    notes: List[str] = []
    # ── Prévu (scénario)
    fp = svc.valeur_immeuble(i, bareme)
    cout_prevu = fp["cout_projet"] if fp["cout_projet"] > 0 else 0.0
    valeur_prevue = fp["valeur_a_terme"] if i["phase"] == "stabilisation" else fp["valeur"]
    prevu = {
        "cout_projet": _r(cout_prevu), "valeur": _r(valeur_prevue), "revenus_nets": fp.get("revenus_nets"),
        "dette": _r(i["dette"]), "equite": _r(valeur_prevue - i["dette"]),
        "mise_de_fonds": _r(max(cout_prevu - i["dette"], 0.0)) if cout_prevu > 0 else None,
    }
    # ── Réel (Kratos)
    reel: Optional[Dict[str, Any]] = None
    if item is not None:
        prix = float((achat or {}).get("prix") or 0.0)
        date_achat = (achat or {}).get("date")
        travaux = i["travaux_initiaux"] + i["frais_connexes"]
        cout_reel = prix + travaux if prix > 0 else 0.0
        taux_cap = float(item.get("taux_cap_pct") or 0.0) or i["taux_cap_pct"]
        r = svc.immeuble_vide(
            nom=i["nom"], nb_logements=int(item.get("nb_logements") or i["nb_logements"]), phase="stabilise",
            loyers_bruts_mensuels=float(item.get("loyers_bruts_mensuels") or 0.0),
            taxes_municipales=float(item.get("taxes_municipales") or 0.0), taxes_scolaires=float(item.get("taxes_scolaires") or 0.0),
            assurances=float(item.get("assurances") or 0.0), energie=float(item.get("energie") or 0.0),
            valeur_rapport=float(item.get("valeur_rapport") or 0.0), annee_rapport=item.get("annee_rapport"),
            taux_cap_pct=taux_cap, dette=float(item.get("dette") or 0.0),
        )
        fr = svc.valeur_immeuble(r, bareme)
        if i["phase"] == "stabilisation":
            # En rénovation : les loyers ne sont pas stabilisés, la valeur par les revenus ne veut rien dire.
            # Réel = dernier rapport d'évaluation, sinon le coût du projet.
            rapport = float(item.get("valeur_rapport") or 0.0)
            fr = dict(fr, valeur=_r(rapport) if rapport > 0 else _r(prix + travaux),
                      methode=("en rénovation : dernier rapport d'évaluation" + (f" ({item.get('annee_rapport')})" if item.get("annee_rapport") else ""))
                      if rapport > 0 else "en rénovation : coût du projet (aucun rapport)")
        hyp_init = float((hypo or {}).get("initial") or 0.0)
        refinance = cout_reel > 0 and hyp_init >= cout_reel
        service_dette = float((hypo or {}).get("paiement_annuel") or 0.0)
        mise = max(cout_reel - hyp_init, 0.0) if cout_reel > 0 else None
        revenus_nets = fr.get("revenus_nets")
        cash_flow = (revenus_nets - service_dette) if revenus_nets is not None else None
        equite = fr["valeur"] - r["dette"]
        annees = _annees(date_achat, aujourd_hui)
        gain = (equite - mise) if mise is not None else None
        reel = {
            "prix_achat": _r(prix), "date_achat": date_achat, "annees": annees, "travaux_et_frais": _r(travaux),
            "cout_projet": _r(cout_reel), "hypotheque_initiale": _r(hyp_init), "mise_de_fonds": (_r(mise) if mise is not None else None),
            "valeur": fr["valeur"], "methode_valeur": fr["methode"], "revenus_nets": revenus_nets,
            "service_dette": _r(service_dette), "cash_flow": (_r(cash_flow) if cash_flow is not None else None),
            "dette": _r(r["dette"]), "equite": _r(equite), "gain": (_r(gain) if gain is not None else None),
            "rendement_total_pct": (_pct(gain, mise) if gain is not None and mise else None),
            "cash_on_cash_pct": (_pct(cash_flow, mise) if cash_flow is not None and mise else None),
            "annualise_pct": (_annualise(equite / mise, annees) if mise else None),
            "capital_recupere": refinance,
        }
        if refinance:
            notes.append("Hypothèque actuelle ≥ coût du projet : la mise de fonds a été entièrement récupérée (refinancement). "
                         "Rendements sur mise non calculables — le gain est l'équité d'aujourd'hui.")
        if i["phase"] == "stabilisation":
            notes.append("En rénovation : valeur réelle = dernier rapport (les loyers ne sont pas stabilisés) ; revenus nets réels indicatifs.")
        if prix <= 0:
            notes.append("Prix d'achat absent dans Kratos (fiche de l'immeuble) : mise de fonds et rendements réels impossibles.")
        if not date_achat:
            notes.append("Date d'achat absente dans Kratos : pas de rendement annualisé.")
        if hyp_init <= 0:
            notes.append("Aucune hypothèque dans Kratos : mise de fonds = coût du projet au complet.")
        if fr["valeur"] <= 0:
            notes.append("Ni rapport d'évaluation ni taux de cap dans Kratos : valeur réelle inconnue.")
        elif fr.get("source_revenus_nets") and taux_cap <= 0:
            notes.append("Taux de cap absent : la valeur réelle est celle du rapport, pas des revenus nets.")
    else:
        notes.append("Immeuble pas lié à Kratos : prévu seulement.")
    ecart = None
    if reel:
        ecart = {
            "valeur": _r(reel["valeur"] - prevu["valeur"]),
            "revenus_nets": (_r(reel["revenus_nets"] - prevu["revenus_nets"]) if reel["revenus_nets"] is not None and prevu["revenus_nets"] is not None else None),
            "dette": _r(reel["dette"] - prevu["dette"]), "equite": _r(reel["equite"] - prevu["equite"]),
        }
    return {
        "id": i["id"], "nom": i["nom"] or "Sans nom", "kratos_immeuble_id": i.get("kratos_immeuble_id"),
        "dans_le_fonds": i["dans_le_fonds"], "phase": i["phase"], "prevu": prevu, "reel": reel, "ecart": ecart, "notes": notes,
    }


def calculer_performance(data: Dict[str, Any], items: Dict[int, Dict[str, Any]], hypos: Dict[int, Dict[str, float]],
                         achats: Dict[int, Dict[str, Any]], bareme: Optional[Dict[str, Any]] = None,
                         aujourd_hui: Optional[date] = None) -> Dict[str, Any]:
    d = svc.normaliser(data)
    auj = aujourd_hui or date.today()
    projets = []
    for i in d["immeubles"]:
        kid = i.get("kratos_immeuble_id")
        projets.append(_projet(i, items.get(kid) if kid else None, hypos.get(kid) if kid else None,
                               achats.get(kid) if kid else None, bareme, auj))

    # ── Fonds : immeubles « dans le fonds », réel quand disponible, sinon prévu.
    capital = valeur = dettes = cash_flow = 0.0
    annees_pond = 0.0
    nb_reels = nb_prevus = 0
    for p in projets:
        if not p["dans_le_fonds"]:
            continue
        src = p["reel"] if p["reel"] and p["reel"]["valeur"] > 0 else p["prevu"]
        if src is p["reel"]:
            nb_reels += 1
        else:
            nb_prevus += 1
        mise = src.get("mise_de_fonds") or 0.0
        capital += mise
        valeur += src["valeur"]
        dettes += src["dette"]
        if src.get("cash_flow") is not None:
            cash_flow += src["cash_flow"]
        if src is p["reel"] and src.get("annees"):
            annees_pond += mise * src["annees"]
    cash = d["fonds"]["cash"]
    van = valeur - dettes + cash
    gain = van - capital
    annees_moy = (annees_pond / capital) if capital > 0 and annees_pond > 0 else None
    fonds = {
        "nb_immeubles": nb_reels + nb_prevus, "nb_reels": nb_reels, "nb_prevus": nb_prevus,
        "capital_investi": _r(capital), "valeur": _r(valeur), "dettes": _r(dettes), "cash": _r(cash), "van": _r(van),
        "gain": _r(gain), "rendement_total_pct": _pct(gain, capital), "annees_moyennes": (round(annees_moy, 2) if annees_moy else None),
        "annualise_pct": (_annualise(van / capital, annees_moy) if capital > 0 and annees_moy else None),
        "cash_flow_annuel": _r(cash_flow), "cash_on_cash_pct": _pct(cash_flow, capital),
        "part_des_gains": partage_gain(gain, capital, d["part_des_gains"]),
        "regles": d["part_des_gains"],
    }
    return {"projets": projets, "fonds": fonds, "aujourd_hui": auj.isoformat(), "annee_scenario": d["annee"]}


__all__ = ["calculer_performance", "partage_gain"]
