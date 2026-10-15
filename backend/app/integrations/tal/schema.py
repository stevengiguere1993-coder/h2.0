"""Schéma du formulaire TAL 53000BAIL — chargé depuis le fichier JSON fourni
par le TAL (``structurePreRemplissage`` + ``champs``), versionné.

Le schéma actif vient de la table ``tal_schemas`` (dernier téléversé
actif) ; à défaut, du fichier embarqué ``app/assets/tal/53000BAIL_schema_*.json``.
Le fichier du TAL est une structure de données (noms de champs, types,
valeurs permises) — pas le formulaire protégé par le droit d'auteur.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "tal"
TYPE_FORMULAIRE = "53000BAIL"

#: Types de champs du TAL → famille de validation.
TYPES_TEXTE = {"text", "textarea"}
TYPES_NOMBRE = {"nombre", "number"}
TYPES_DATE = {"date"}
TYPES_CHOIX_UNIQUE = {"radio", "listederoulante", "select"}
TYPES_CHOIX_MULTIPLE = {"checkbox"}
TYPES_SPECIAUX = {"email", "tel", "codepostal", "customfile"}


@dataclass(frozen=True)
class ChampTal:
    nom: str
    type: str
    groupe: Optional[str]           # ex. "locataires", "locataires.adresse", None = racine
    repetable: Optional[bool]
    max_occurrences: Optional[int]
    nom_domaine: Optional[str]
    valeurs_possibles: Optional[dict]  # clé → {fr, en} ou bool
    label_fr: Optional[str]
    label_en: Optional[str]

    @property
    def cle(self) -> tuple[str, str]:
        return (self.groupe or "", self.nom)

    @property
    def est_booleen(self) -> bool:
        """Case à cocher sans liste de valeurs (le gabarit porte true/false)."""
        return self.type == "checkbox" and not self.valeurs_possibles

    @property
    def cles_valeurs(self) -> list[str]:
        return list((self.valeurs_possibles or {}).keys())


@dataclass
class SchemaTal:
    type_formulaire: str
    version: str
    source: str                      # "asset:<fichier>" | "tal_schemas:<id>"
    gabarit: dict[str, Any]          # structurePreRemplissage.form
    champs: list[ChampTal]
    index: dict[tuple[str, str], ChampTal] = field(default_factory=dict)
    doublons: list[tuple[str, str]] = field(default_factory=list)

    def champ(self, nom: str, groupe: Optional[str] = None) -> Optional[ChampTal]:
        return self.index.get((groupe or "", nom))

    def champs_racine(self) -> list[ChampTal]:
        return [c for c in self.champs if not c.groupe]

    def groupes(self) -> list[str]:
        return sorted({c.groupe.split(".")[0] for c in self.champs if c.groupe})

    def gabarit_groupe(self, groupe: str) -> Optional[dict[str, Any]]:
        """Squelette d'UNE occurrence d'un groupe (ex. locataires → dict
        avec nom, noTelephone, …, adresse: [ {…} ])."""
        racine, _, sous = groupe.partition(".")
        v = self.gabarit.get(racine)
        if not (isinstance(v, list) and v and isinstance(v[0], dict)):
            return None
        occ = v[0]
        if sous:
            sv = occ.get(sous)
            if isinstance(sv, list) and sv and isinstance(sv[0], dict):
                return sv[0]
            return None
        return occ

    def resume(self) -> dict[str, Any]:
        return {
            "type_formulaire": self.type_formulaire,
            "version": self.version,
            "source": self.source,
            "nb_champs": len(self.champs),
            "nb_champs_uniques": len(self.index),
            "doublons": [f"{g}.{n}" if g else n for g, n in self.doublons],
            "groupes": self.groupes(),
            "domaines": sorted({c.nom_domaine for c in self.champs if c.nom_domaine}),
            "types": sorted({c.type for c in self.champs}),
            "champs_fichier": [c.nom for c in self.champs if c.type == "customfile"],
        }


def _squelette_vide(valeur_gabarit: Any) -> Any:
    """Valeur « vide » d'un champ du gabarit : "" pour un texte / une
    sélection, [] pour une liste, False pour une case à cocher, et un
    squelette récursif pour les groupes."""
    if isinstance(valeur_gabarit, bool):
        return False
    if isinstance(valeur_gabarit, list):
        if valeur_gabarit and isinstance(valeur_gabarit[0], dict):
            return [{k: _squelette_vide(v) for k, v in valeur_gabarit[0].items()}]
        return []
    if isinstance(valeur_gabarit, dict):
        return {k: _squelette_vide(v) for k, v in valeur_gabarit.items()}
    return ""


def squelette(schema: SchemaTal) -> dict[str, Any]:
    """Le formulaire VIDE, exactement dans la forme du gabarit du TAL
    (comme « Bail de logement (vierge) ») : on remplit par-dessus."""
    return {k: _squelette_vide(v) for k, v in schema.gabarit.items()}


def construire_schema(data: dict[str, Any], *, version: str, source: str) -> SchemaTal:
    """Construit le schéma depuis le JSON du TAL ; lève ValueError s'il
    n'a pas la forme attendue (typeFormulaire, structurePreRemplissage.form,
    champs)."""
    if not isinstance(data, dict):
        raise ValueError("Le schéma doit être un objet JSON.")
    tf = str(data.get("typeFormulaire") or "")
    if tf != TYPE_FORMULAIRE:
        raise ValueError(f"typeFormulaire attendu « {TYPE_FORMULAIRE} », reçu « {tf} ».")
    form = ((data.get("structurePreRemplissage") or {}).get("form"))
    if not isinstance(form, dict) or not form:
        raise ValueError("structurePreRemplissage.form manquant ou vide.")
    brut = data.get("champs")
    if not isinstance(brut, list) or not brut:
        raise ValueError("Section « champs » manquante ou vide.")
    champs: list[ChampTal] = []
    index: dict[tuple[str, str], ChampTal] = {}
    doublons: list[tuple[str, str]] = []
    for c in brut:
        if not isinstance(c, dict) or not c.get("nom"):
            continue
        label = c.get("label") or {}
        ch = ChampTal(
            nom=str(c["nom"]),
            type=str(c.get("type") or "text").lower(),
            groupe=(str(c["groupe"]) if c.get("groupe") else None),
            repetable=c.get("repetable"),
            max_occurrences=(int(c["maxOccurrences"]) if c.get("maxOccurrences") else None),
            nom_domaine=c.get("nomDomaine"),
            valeurs_possibles=(c.get("valeursPossibles") or None),
            label_fr=(label.get("fr") if isinstance(label, dict) else None),
            label_en=(label.get("en") if isinstance(label, dict) else None),
        )
        champs.append(ch)
        if ch.cle in index:
            doublons.append(ch.cle)
            continue  # le premier gagne (le TAL liste 2 champs deux fois)
        index[ch.cle] = ch
    return SchemaTal(
        type_formulaire=tf, version=version, source=source, gabarit=form,
        champs=champs, index=index, doublons=doublons,
    )


def charger_schema_asset() -> SchemaTal:
    """Le schéma embarqué le plus récent (nom de fichier trié)."""
    fichiers = sorted(_ASSETS_DIR.glob("53000BAIL_schema_*.json"))
    if not fichiers:
        raise FileNotFoundError("Aucun schéma 53000BAIL embarqué dans app/assets/tal.")
    f = fichiers[-1]
    m = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
    data = json.loads(f.read_text(encoding="utf-8"))
    return construire_schema(data, version=(m.group(1) if m else f.stem), source=f"asset:{f.name}")


async def charger_schema(db=None) -> SchemaTal:
    """Schéma ACTIF : la version téléversée active (table tal_schemas) si
    elle existe, sinon le fichier embarqué. Best-effort : une base
    indisponible renvoie le fichier embarqué."""
    if db is not None:
        try:
            from sqlalchemy import select

            from app.models.tal_bail import TalSchema

            row = (
                await db.execute(
                    select(TalSchema.id, TalSchema.version, TalSchema.json_text)
                    .where(TalSchema.actif.is_(True), TalSchema.type_formulaire == TYPE_FORMULAIRE)
                    .order_by(TalSchema.id.desc())
                )
            ).first()
            if row is not None and row[2]:
                return construire_schema(
                    json.loads(row[2]), version=row[1], source=f"tal_schemas:{row[0]}"
                )
        except Exception:  # noqa: BLE001
            pass
    return charger_schema_asset()


def comparer_schemas(ancien: SchemaTal, nouveau: SchemaTal) -> dict[str, Any]:
    """Ce qui change entre deux versions : champs ajoutés / retirés /
    modifiés (type, répétable, occurrences, valeurs permises) — c'est ce
    qu'on a 15 jours pour absorber."""
    a, b = ancien.index, nouveau.index

    def nom(k: tuple[str, str]) -> str:
        return f"{k[0]}.{k[1]}" if k[0] else k[1]

    ajoutes = sorted(nom(k) for k in b.keys() - a.keys())
    retires = sorted(nom(k) for k in a.keys() - b.keys())
    modifies = []
    for k in sorted(a.keys() & b.keys()):
        ca, cb = a[k], b[k]
        diff = {}
        for attr in ("type", "repetable", "max_occurrences", "nom_domaine"):
            if getattr(ca, attr) != getattr(cb, attr):
                diff[attr] = [getattr(ca, attr), getattr(cb, attr)]
        if set(ca.cles_valeurs) != set(cb.cles_valeurs):
            diff["valeurs_possibles"] = [ca.cles_valeurs, cb.cles_valeurs]
        if diff:
            modifies.append({"champ": nom(k), "changements": diff})
    gab_a, gab_b = set(ancien.gabarit.keys()), set(nouveau.gabarit.keys())
    return {
        "ancienne_version": ancien.version,
        "nouvelle_version": nouveau.version,
        "champs_ajoutes": ajoutes,
        "champs_retires": retires,
        "champs_modifies": modifies,
        "gabarit_ajoute": sorted(gab_b - gab_a),
        "gabarit_retire": sorted(gab_a - gab_b),
        "identique": not (ajoutes or retires or modifies or (gab_a ^ gab_b)),
    }


def iter_champs(champs: Iterable[ChampTal], groupe: Optional[str]) -> list[ChampTal]:
    return [c for c in champs if (c.groupe or None) == (groupe or None)]


__all__ = [
    "TYPE_FORMULAIRE",
    "ChampTal",
    "SchemaTal",
    "squelette",
    "construire_schema",
    "charger_schema_asset",
    "charger_schema",
    "comparer_schemas",
    "iter_champs",
]
