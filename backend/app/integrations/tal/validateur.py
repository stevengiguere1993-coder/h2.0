"""Validation LOCALE et stricte d'un formulaire 53000BAIL avant tout appel
au TAL : types, valeurs permises (les CLÉS, jamais les libellés), nombre
maximal d'occurrences, forme des groupes, champs inconnus. Un formulaire
qui ne passe pas ne part pas — on n'a que 10 essais gratuits.

Le TAL n'impose aucun champ obligatoire (Phil 2026-10-15 : « comme un
bail papier ») : les champs vides sont RAPPORTÉS, pas bloquants, sauf la
liste « requis » réglable dans Paramètres.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from .schema import (
    TYPES_CHOIX_MULTIPLE,
    TYPES_CHOIX_UNIQUE,
    TYPES_DATE,
    TYPES_NOMBRE,
    TYPES_TEXTE,
    ChampTal,
    SchemaTal,
)

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")
_CODE_POSTAL_RE = re.compile(r"^[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z] ?\d[ABCEGHJ-NPRSTV-Z]\d$", re.IGNORECASE)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NOMBRE_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")
_TEXTE_MAX = 2000


@dataclass
class Rapport:
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    champs_vides: list[str] = field(default_factory=list)
    champs_inconnus: list[str] = field(default_factory=list)
    nb_remplis: int = 0

    @property
    def valide(self) -> bool:
        return not self.erreurs

    def as_dict(self) -> dict[str, Any]:
        return {
            "valide": self.valide,
            "erreurs": self.erreurs,
            "avertissements": self.avertissements,
            "champs_vides": self.champs_vides,
            "champs_inconnus": self.champs_inconnus,
            "nb_remplis": self.nb_remplis,
        }


def _vide(v: Any) -> bool:
    return v is None or v == "" or v == [] or v is False


def _valider_scalaire(champ: ChampTal, valeur: Any, chemin: str, r: Rapport) -> None:
    """Un champ scalaire (racine ou dans un groupe)."""
    if _vide(valeur):
        if champ.type == "checkbox" and champ.est_booleen:
            return  # False = non coché, c'est une valeur
        r.champs_vides.append(chemin)
        return
    r.nb_remplis += 1
    t = champ.type
    if champ.est_booleen:
        if not isinstance(valeur, bool):
            r.erreurs.append(f"{chemin} : case à cocher → true/false attendu, reçu {valeur!r}.")
        return
    if t in TYPES_CHOIX_UNIQUE or (t == "checkbox" and champ.valeurs_possibles):
        cles = champ.cles_valeurs
        if t in TYPES_CHOIX_MULTIPLE:
            if not isinstance(valeur, list):
                r.erreurs.append(f"{chemin} : liste de clés attendue, reçu {valeur!r}.")
                return
            for v in valeur:
                if str(v) not in cles:
                    r.erreurs.append(f"{chemin} : « {v} » n'est pas une valeur permise ({', '.join(cles)}).")
            if len(set(map(str, valeur))) != len(valeur):
                r.erreurs.append(f"{chemin} : valeurs en double.")
            return
        v = valeur
        if isinstance(v, bool):
            v = "true" if v else "false"
        if cles and str(v) not in cles:
            r.erreurs.append(f"{chemin} : « {valeur} » n'est pas une valeur permise ({', '.join(cles)}).")
        elif not cles:
            r.avertissements.append(f"{chemin} : domaine « {champ.nom_domaine or '?'} » sans liste de valeurs connue — « {valeur} » envoyé tel quel.")
        return
    if t in TYPES_DATE:
        if not isinstance(valeur, str) or not _DATE_RE.match(valeur):
            r.erreurs.append(f"{chemin} : date attendue au format AAAA-MM-JJ, reçu {valeur!r}.")
            return
        try:
            date.fromisoformat(valeur)
        except ValueError:
            r.erreurs.append(f"{chemin} : date invalide « {valeur} ».")
        return
    if t in TYPES_NOMBRE:
        if isinstance(valeur, bool) or not (isinstance(valeur, (int, float)) or (isinstance(valeur, str) and _NOMBRE_RE.match(valeur.strip()))):
            r.erreurs.append(f"{chemin} : nombre attendu, reçu {valeur!r}.")
        return
    if t == "email":
        if not isinstance(valeur, str) or not _EMAIL_RE.match(valeur.strip()):
            r.erreurs.append(f"{chemin} : courriel invalide « {valeur} ».")
        return
    if t == "tel":
        chiffres = re.sub(r"\D", "", str(valeur))
        if len(chiffres) not in (10, 11):
            r.erreurs.append(f"{chemin} : numéro de téléphone invalide « {valeur} » (10 chiffres).")
        return
    if t == "codepostal":
        if not isinstance(valeur, str) or not _CODE_POSTAL_RE.match(valeur.strip()):
            r.erreurs.append(f"{chemin} : code postal canadien attendu (ex. H1T 3X1), reçu « {valeur} ».")
        return
    if t == "customfile":
        r.avertissements.append(f"{chemin} : pièce jointe — format d'envoi à confirmer avec le TAL (champ laissé tel quel).")
        return
    if t in TYPES_TEXTE:
        if not isinstance(valeur, str):
            r.erreurs.append(f"{chemin} : texte attendu, reçu {type(valeur).__name__}.")
        elif len(valeur) > _TEXTE_MAX:
            r.avertissements.append(f"{chemin} : texte très long ({len(valeur)} caractères).")
        return
    # Type inconnu du validateur : on laisse passer avec un avertissement.
    r.avertissements.append(f"{chemin} : type « {t} » non reconnu par le validateur, valeur envoyée telle quelle.")


def _valider_groupe(schema: SchemaTal, groupe: str, valeur: Any, chemin: str, r: Rapport) -> None:
    gab = schema.gabarit_groupe(groupe)
    champs_groupe = {c.nom: c for c in schema.champs if c.groupe == groupe}
    if gab is None:
        r.avertissements.append(f"{chemin} : groupe absent du gabarit, non validé.")
        return
    if not isinstance(valeur, list):
        r.erreurs.append(f"{chemin} : une liste d'occurrences est attendue.")
        return
    exemple = next(iter(champs_groupe.values()), None)
    max_occ = (exemple.max_occurrences if exemple and exemple.repetable else 1) or 1
    if len(valeur) > max_occ:
        r.erreurs.append(f"{chemin} : {len(valeur)} occurrences, maximum {max_occ}.")
    for i, occ in enumerate(valeur):
        if not isinstance(occ, dict):
            r.erreurs.append(f"{chemin}[{i}] : objet attendu.")
            continue
        for k, v in occ.items():
            sous = f"{chemin}[{i}].{k}"
            if k not in gab:
                r.champs_inconnus.append(sous)
                r.erreurs.append(f"{sous} : champ inconnu du gabarit.")
                continue
            if isinstance(gab[k], list) and gab[k] and isinstance(gab[k][0], dict):
                _valider_groupe(schema, f"{groupe}.{k}", v, sous, r)
                continue
            champ = champs_groupe.get(k)
            if champ is None:
                # Présent dans le gabarit mais sans fiche « champs » : type
                # déduit du gabarit.
                if _vide(v):
                    r.champs_vides.append(sous)
                elif isinstance(gab[k], bool) and not isinstance(v, bool):
                    r.erreurs.append(f"{sous} : true/false attendu.")
                else:
                    r.nb_remplis += 1
                continue
            _valider_scalaire(champ, v, sous, r)


def valider(form: dict[str, Any], schema: SchemaTal, *, requis: Optional[list[str]] = None) -> Rapport:
    """Valide ``form`` (l'objet qui sera envoyé sous « form ») contre le
    schéma. ``requis`` : chemins (ex. « locataires[0].nom »,
    « coutLoyer ») qui ne peuvent pas être vides (réglage Kratos)."""
    r = Rapport()
    if not isinstance(form, dict):
        r.erreurs.append("Le formulaire doit être un objet.")
        return r
    gab = schema.gabarit
    for k, v in form.items():
        if k not in gab:
            r.champs_inconnus.append(k)
            r.erreurs.append(f"{k} : champ inconnu du gabarit TAL (version {schema.version}).")
            continue
        if isinstance(gab[k], list) and gab[k] and isinstance(gab[k][0], dict):
            _valider_groupe(schema, k, v, k, r)
            continue
        champ = schema.champ(k)
        if champ is None:
            # Présent dans le gabarit mais pas décrit : type déduit.
            if _vide(v):
                r.champs_vides.append(k)
            elif isinstance(gab[k], bool) and not isinstance(v, bool):
                r.erreurs.append(f"{k} : true/false attendu.")
            elif isinstance(gab[k], list) and not isinstance(v, list):
                r.erreurs.append(f"{k} : liste attendue.")
            else:
                r.nb_remplis += 1
            continue
        _valider_scalaire(champ, v, k, r)
    # Cohérences métier simples (elles coûtent 2,99 $ quand on se trompe).
    if form.get("typeBail") == "dureeFixe":
        if _vide(form.get("dateDebutBail")) or _vide(form.get("dateFinBail")):
            r.avertissements.append("Bail à durée fixe sans date de début ou de fin.")
        elif str(form.get("dateFinBail")) <= str(form.get("dateDebutBail")):
            r.erreurs.append("dateFinBail doit être après dateDebutBail.")
    if form.get("typeBail") == "dureeIndeterminee" and _vide(form.get("dateDebutBailDureeIndeterminee")):
        r.avertissements.append("Bail à durée indéterminée sans date de début.")
    if form.get("bailIncluServices") in ("true", True) and _vide(form.get("coutServices")):
        r.avertissements.append("Le loyer inclut des services mais coutServices est vide.")
    for chemin in requis or []:
        v = _lire_chemin(form, chemin)
        if _vide(v):
            r.erreurs.append(f"{chemin} : champ requis par Kratos (Paramètres) et vide.")
    return r


def _lire_chemin(form: dict[str, Any], chemin: str) -> Any:
    """« locataires[0].adresse[0].CodePostal » → valeur (None si absent)."""
    cur: Any = form
    for part in re.split(r"\.(?![^\[]*\])", chemin):
        m = re.match(r"^([A-Za-z0-9_]+)(?:\[(\d+)\])?$", part)
        if not m or not isinstance(cur, dict):
            return None
        cur = cur.get(m.group(1))
        if m.group(2) is not None:
            if not isinstance(cur, list) or int(m.group(2)) >= len(cur):
                return None
            cur = cur[int(m.group(2))]
    return cur


__all__ = ["Rapport", "valider"]
