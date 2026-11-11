"""Règles d'affichage du formulaire 53000BAIL — quels champs s'appliquent selon les réponses.

Le formulaire du TAL est conditionnel (« Veuillez préciser… » ne vaut que si la question
au-dessus dit oui, la date de début d'un bail à durée indéterminée ne vaut que pour ce type
de bail, le courriel du représentant ne vaut que si la personne est représentée…). Le schéma
que le TAL fournit ne porte pas ces conditions : elles sont écrites ICI, une seule fois.

Deux usages, une seule source :
- l'écran du bail reçoit ces règles et MASQUE les champs qui ne s'appliquent pas (fini les
  trois courriels, les deux « Date de début », les blocs de stationnement non cochés) ;
- Kratos VIDE ces champs avant d'enregistrer et d'envoyer. Le TAL imprime tout ce qu'il
  reçoit : au premier bail réel (2026-11-11), la date de début « durée indéterminée » remplie
  par erreur s'est imprimée sur un bail à durée fixe.

Une règle : ``{"cible": champ, "si": [conditions]}`` (toutes les conditions doivent tenir), et
``"groupe"`` quand la cible est un champ d'une occurrence (la condition se lit alors dans la
même occurrence). Conditions :
- ``{"champ": c, "vaut": [v…]}``     la valeur (true/false lus comme du texte) est dans la liste ;
- ``{"champ": c, "pas": [v…]}``      la valeur n'est pas dans la liste ;
- ``{"champ": c, "contient": v}``    la liste cochée contient v ;
- ``{"champ": c, "rempli": True}``   le champ a une réponse ;
- ``{"groupe": g, "nommes_min": n}`` au moins n occurrences du groupe ont un nom.
"""

from __future__ import annotations

from typing import Any, Optional

OUI = ["true"]


def _si(champ: str, *valeurs: str) -> dict[str, Any]:
    return {"champ": champ, "vaut": list(valeurs)}


def _contient(champ: str, valeur: str) -> dict[str, Any]:
    return {"champ": champ, "contient": valeur}


def _rempli(champ: str) -> dict[str, Any]:
    return {"champ": champ, "rempli": True}


_MEUBLES = [_si("meublesInclusLoyer", "true")]
_REPRESENTE = [_si("questionRepresentant", "true")]
_PAS_REPRESENTE = [{"champ": "questionRepresentant", "pas": ["true"]}]
_G = "situationApplicableAvisNouveauLocataire"
_F = "situationApplicableRestrictionsFixationLoyer"

REGLES: list[dict[str, Any]] = [
    # ── A. Parties ────────────────────────────────────────────────
    {"cible": "estLocatairesEngagementSolidaire", "si": [{"groupe": "locataires", "nommes_min": 2}]},
    {"cible": "autresSignataires", "si": [_si("possedeAutresSignataires", "true")]},
    # Une personne représentée : son représentant et les deux courriels qui vont avec ;
    # sinon, son seul courriel.
    *[{"groupe": g, "cible": c, "si": _REPRESENTE}
      for g in ("locateurs", "locataires") for c in ("representant", "courrielRepresentant", "courrielMandant")],
    {"groupe": "locateurs", "cible": "courrielLocateur", "si": _PAS_REPRESENTE},
    {"groupe": "locataires", "cible": "courrielLocataire", "si": _PAS_REPRESENTE},
    # ── B. Logement et accessoires ────────────────────────────────
    {"cible": "nbPiecesAutre", "si": [_si("nbPieces", "autre")]},
    {"cible": "precisionLocationMixte", "si": [_si("logementLoueFinsHabitation", "false")]},
    {"cible": "stationnementExterieur", "si": [_contient("dependancesIncluses", "StationnementExterieur")]},
    {"cible": "stationnementInterieur", "si": [_contient("dependancesIncluses", "StationnementInterieur")]},
    {"cible": "remiseEspaceRangement", "si": [_contient("dependancesIncluses", "RemiseOuEspaceRangement")]},
    {"cible": "listeAppareilsInclusLoyer", "si": [_si("appareilsInclusLoyer", "true")]},
    {"cible": "autresAppareilsInclus", "si": [_si("appareilsInclusLoyer", "true"), _contient("listeAppareilsInclusLoyer", "autre")]},
    {"cible": "listeMeublesInclusLoyer", "si": _MEUBLES},
    {"cible": "nbTables", "si": [*_MEUBLES, _contient("listeMeublesInclusLoyer", "tables")]},
    {"cible": "nbChaises", "si": [*_MEUBLES, _contient("listeMeublesInclusLoyer", "chaises")]},
    {"cible": "nbCommodes", "si": [*_MEUBLES, _contient("listeMeublesInclusLoyer", "commodes")]},
    {"cible": "nbCanapes", "si": [*_MEUBLES, _contient("listeMeublesInclusLoyer", "canapes")]},
    {"cible": "nbFauteuils", "si": [*_MEUBLES, _contient("listeMeublesInclusLoyer", "fauteuils")]},
    {"cible": "nbLits", "si": [*_MEUBLES, _contient("listeMeublesInclusLoyer", "lits")]},
    {"cible": "formatLits", "si": [*_MEUBLES, _contient("listeMeublesInclusLoyer", "lits")]},
    {"cible": "autresMeublesInclus", "si": [*_MEUBLES, _contient("listeMeublesInclusLoyer", "autre")]},
    # ── C. Durée ──────────────────────────────────────────────────
    {"cible": "nbSemainesMoisAnnees", "si": [{"champ": "typeBail", "pas": ["dureeIndeterminee"]}]},
    {"cible": "dateDebutBail", "si": [{"champ": "typeBail", "pas": ["dureeIndeterminee"]}]},
    {"cible": "dateFinBail", "si": [{"champ": "typeBail", "pas": ["dureeIndeterminee"]}]},
    {"cible": "dateDebutBailDureeIndeterminee", "si": [_si("typeBail", "dureeIndeterminee")]},
    # ── D. Loyer ──────────────────────────────────────────────────
    {"cible": "coutServices", "si": [_si("bailIncluServices", "true")]},
    {"cible": "preciserSubventionPaiementLoyer", "si": [_si("subventionPaiementLoyer", "true")]},
    {"cible": "precisionAutresTermes", "si": [_si("termesPaiement", "autre")]},
    {"cible": "precisionAutresModePaiement", "si": [_si("modePaiement", "autre")]},
    {"cible": "locataireAccepteRemiseChequePostdates", "si": [_si("modePaiement", "cheque", "chequePostDate")]},
    # ── E. Services et conditions ─────────────────────────────────
    {"cible": "dateRemiseReglementImmeuble", "si": [_si("possedeRemiseReglementImmeuble", "true")]},
    {"cible": "possedeRemiseReglementImmeubleCoproprieteDivise", "si": [_si("logementCoproprieteDivise", "true")]},
    {"cible": "dateRemiseReglementCoproprieteDivise",
     "si": [_si("logementCoproprieteDivise", "true"), _si("possedeRemiseReglementImmeubleCoproprieteDivise", "true")]},
    {"cible": "reglementImmeubleJointBail", "si": [_si("possedeReglementImmeubleJointBail", "true")]},
    {"cible": "precisionsServicesConcierge", "si": [_si("possederServiceConciergerie", "true")]},
    {"cible": "coordonneesConcierge", "si": [_si("possederServiceConciergerie", "true")]},
    {"cible": "precisionLogementSansFumee", "si": [_rempli("logementSansFumee")]},
    {"cible": "precisionLocatairePossedeDroitAccesTerrain", "si": [_rempli("locatairePossedeDroitAccesTerrain")]},
    {"cible": "precisionLocatairePossedeDroitAnimaux", "si": [_rempli("locatairePossedeDroitAnimaux")]},
    {"cible": "precisionAutresServicesConditionsRestriction", "si": [_si("possedeAutresServicesConditionsRestriction", "true")]},
    {"cible": "DescriptionDocumentsJointsBail", "si": [_si("possedeDocumentsJoindreBail", "true")]},
    {"cible": "DocumentsJointsBail", "si": [_si("possedeDocumentsJoindreBail", "true")]},
    # ── F. Restrictions à la fixation du loyer ────────────────────
    {"cible": "dateImmeublePretHabitation", "si": [_si(_F, "estLogementImmeubleMoins5ans")]},
    {"cible": "dateImmeublePretHabitationAffectation", "si": [_si(_F, "estLogementImmeubleChangementAffectation5ans")]},
    {"cible": "loyerMaximalImeublePretPourUsage",
     "si": [_si(_F, "estLogementImmeubleMoins5ans", "estLogementImmeubleChangementAffectation5ans")]},
    # ── G. Avis au nouveau locataire ──────────────────────────────
    {"cible": "montantLoyerPlusBasPaye12Mois", "si": [_si(_G, "loyer")]},
    {"cible": "frequenceLoyerPlusBasPaye12Mois", "si": [_si(_G, "loyer")]},
    {"cible": "precisionAutreFrequencePlusBasLoyer", "si": [_si(_G, "loyer"), _si("frequenceLoyerPlusBasPaye12Mois", "autre")]},
    {"cible": "dateDernierPaiementLoyer", "si": [_si(_G, "aucunLoyer")]},
    {"cible": "montantDernierLoyerPaye", "si": [_si(_G, "aucunLoyer")]},
    {"cible": "frequenceDernierLoyer", "si": [_si(_G, "aucunLoyer")]},
    {"cible": "precisionAutreFrequenceDernierLoyer", "si": [_si(_G, "aucunLoyer"), _si("frequenceDernierLoyer", "autre")]},
    {"cible": "montantLoyerBailPrecedent", "si": [_si(_G, "residencePriveeAines")]},
    {"cible": "frequenceLoyerBailPrecedent", "si": [_si(_G, "residencePriveeAines")]},
    {"cible": "precisionAutreFrequenceLoyerBailPrecedent",
     "si": [_si(_G, "residencePriveeAines"), _si("frequenceLoyerBailPrecedent", "autre")]},
    {"cible": "estMemeBienServicesConditions", "si": [_rempli(_G)]},
    {"cible": "modificationsApporteesBienServicesConditions", "si": [_rempli(_G), _si("estMemeBienServicesConditions", "false")]},
    {"cible": "confirmationTransmissionAvisNouveauLocataire", "si": [_rempli(_G)]},
]


def _texte(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return "" if v is None else str(v)


def _vide(v: Any) -> bool:
    return v is None or v == "" or v == [] or v is False


def _condition_tient(cond: dict[str, Any], form: dict[str, Any], occurrence: Optional[dict[str, Any]]) -> bool:
    if "groupe" in cond and "nommes_min" in cond:
        occs = form.get(cond["groupe"])
        nommes = sum(1 for o in (occs if isinstance(occs, list) else []) if isinstance(o, dict) and str(o.get("nom") or "").strip())
        return nommes >= int(cond["nommes_min"])
    source = occurrence if occurrence is not None else form
    v = source.get(cond.get("champ")) if isinstance(source, dict) else None
    if "vaut" in cond:
        return _texte(v) in cond["vaut"]
    if "pas" in cond:
        return _texte(v) not in cond["pas"]
    if "contient" in cond:
        return isinstance(v, list) and cond["contient"] in [str(x) for x in v]
    if cond.get("rempli"):
        return not _vide(v)
    return True


def s_applique(regle: dict[str, Any], form: dict[str, Any], occurrence: Optional[dict[str, Any]] = None) -> bool:
    return all(_condition_tient(c, form, occurrence) for c in regle.get("si") or [])


def _valeur_vide(modele: Any) -> Any:
    """Même forme que le squelette du schéma : "" / [] / False / une occurrence vide."""
    if isinstance(modele, bool):
        return False
    if isinstance(modele, list):
        if modele and isinstance(modele[0], dict):
            return [{k: _valeur_vide(v) for k, v in modele[0].items()}]
        return []
    if isinstance(modele, dict):
        return {k: _valeur_vide(v) for k, v in modele.items()}
    return ""


def _est_vide_profond(v: Any) -> bool:
    if isinstance(v, list):
        return all(_est_vide_profond(x) for x in v)
    if isinstance(v, dict):
        return all(_est_vide_profond(x) for x in v.values())
    return _vide(v)


def vider_inapplicables(form: dict[str, Any], gabarit: dict[str, Any]) -> list[str]:
    """Vide, sur place, chaque champ qu'une règle déclare sans objet pour ce formulaire.
    Retourne les chemins vidés (ceux qui contenaient quelque chose). Plusieurs passes : vider
    une réponse peut en rendre d'autres sans objet (« meubles inclus : non » → liste, nombres)."""
    vides: list[str] = []
    for _passe in range(4):
        avant = len(vides)
        for regle in REGLES:
            cible, groupe = regle["cible"], regle.get("groupe")
            if groupe:
                occs = form.get(groupe)
                modele = (gabarit.get(groupe) or [{}])[0] if isinstance(gabarit.get(groupe), list) and gabarit.get(groupe) else {}
                for i, occ in enumerate(occs if isinstance(occs, list) else []):
                    if not isinstance(occ, dict) or cible not in occ or s_applique(regle, form, occ):
                        continue
                    if not _est_vide_profond(occ[cible]):
                        occ[cible] = _valeur_vide(modele.get(cible, ""))
                        vides.append(f"{groupe}[{i}].{cible}")
                continue
            if cible not in form or s_applique(regle, form):
                continue
            if not _est_vide_profond(form[cible]):
                form[cible] = _valeur_vide(gabarit.get(cible, form[cible]))
                vides.append(cible)
        if len(vides) == avant:
            break
    return vides


__all__ = ["REGLES", "s_applique", "vider_inapplicables"]
