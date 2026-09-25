"""Import du catalogue de matériaux depuis un classeur Excel (retour
2026-09-25 : fichier « FACTURE_OLIVIER.xlsx », matériaux achetés sur les
projets passés, un onglet par projet).

Deux formes d'onglets reconnues :

1. **Liste** : en-tête ``MATÉRIAUX | DÉTAILLANT | PRIX UNITAIRE | qte …`` —
   une ligne par achat, prix UNITAIRE connu.
2. **Matrice** : première ligne = noms de magasins en colonnes, colonne A
   = matériau (ou une catégorie quand la ligne n'a aucun montant), cellules
   = montant payé chez ce magasin (quantité inconnue → prix indicatif).

Les noms de magasins sont ramenés à une forme canonique (« home depot »,
« Home depot  », « homedepot » → « Home Depot »). Les matériaux sont
dédoublonnés par nom normalisé. Les prix importés sont marqués
``source="import"`` SANS date d'observation : ce sont des prix d'archive,
à vérifier avant d'acheter — le comparatif les affiche comme tels.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.materiau import (
    Magasin,
    Materiau,
    MateriauOffre,
    MateriauPrixHistorique,
)

log = logging.getLogger(__name__)

#: Alias → nom canonique de magasin.
STORE_ALIASES: dict[str, str] = {
    "home depot": "Home Depot", "homedepot": "Home Depot", "the home depot": "Home Depot",
    "rona": "Rona", "rona inc": "Rona",
    "reno depot": "Réno-Dépôt", "reno-depot": "Réno-Dépôt", "renodepot": "Réno-Dépôt",
    "bmr": "BMR", "canac": "Canac", "lowes": "Lowe's", "lowe's": "Lowe's",
    "patrick morin": "Patrick Morin", "patrick morin inc": "Patrick Morin",
    "eco depot": "Éco-Dépôt", "eco-depot": "Éco-Dépôt", "ecodepot": "Éco-Dépôt",
    "eco depot ceramique": "Éco-Dépôt",
    "prosol": "Prosol", "lumen": "Lumen", "home hardware": "Home Hardware",
    "amazon": "Amazon", "ikea": "Ikea", "gh berger": "GH Berger",
    "metal action": "Métal Action", "bain depot": "Bain Dépôt", "bain depot 3": "Bain Dépôt",
    "betonel": "Bétonel", "couvre-plancher": "Couvre-Plancher", "couvre plancher": "Couvre-Plancher",
    "quincaillerie t et l": "Quincaillerie T et L",
    "quincaillerie notre dame": "Quincaillerie Notre-Dame",
    "l villeneuve": "L. Villeneuve", "plomberie atg": "Plomberie ATG",
    "le geant du conteneur": "Le Géant du Conteneur",
    "centre de renovation ile perrot": "Centre de rénovation Île-Perrot",
    "moulin st-andre": "Moulin St-André", "moulin st andre": "Moulin St-André",
    "outil pi": "Outil Pi", "got-junk": "Got-Junk", "got junk": "Got-Junk",
    "horizon": "Horizon (interne)", "centre du petit moteur": "Centre du petit moteur",
    "centre du comptoir coupe d'or": "Centre du comptoir", "baignoire budget": "Baignoire Budget",
    "gagnon la grande quincaillerie": "Gagnon la grande quincaillerie",
    "porte et moulure": "Porte et Moulure",
    "les couvres planchers carriere inc": "Les Couvre-Planchers Carrière",
}

#: Titres de section acceptés comme CATÉGORIE dans les feuilles matrice
#: (égalité exacte après normalisation). Tout autre libellé sans montant
#: est ignoré — sinon un item sans prix (« Porte douche ») devenait une
#: catégorie.
_CATEGORY_LABELS = {
    "electricite", "materiaux", "materiel", "quincaillerie", "plomberie",
    "peinture", "outillage", "outils", "gypse", "isolation", "plancher",
    "planchers", "bois", "ceramique", "porte", "portes", "fenetre",
    "fenetres", "moulure", "moulures", "cuisine", "salle de bain",
    "toiture", "ventilation", "chauffage", "beton", "location", "divers",
    "nettoyage", "luminaire", "luminaires", "eclairage", "armoire",
    "armoires", "comptoir", "comptoirs", "demolition", "finition",
}

#: Lignes de « liste » qui ne sont pas des matériaux.
_SKIP_NAMES = {"total", "frais gestion", "frais de gestion", "sous-total", "grand total"}
_SKIP_PREFIXES = ("sous-traitance", "sous traitance", "main-d", "main d")


def norm_key(value: Optional[str]) -> str:
    """Clé de dédoublonnage : minuscules, sans accents, ponctuation et
    espaces multiples réduits, guillemets unifiés."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("¨", '"').replace("//", "/").lower()
    text = re.sub(r"[\s ]+", " ", text)
    return text.strip(" .,;:-")


def canonical_store(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    key = re.sub(r"[^a-z0-9' \-]", "", norm_key(raw)).strip()
    if not key:
        return None
    for k in (key, key.replace("-", " "), key.replace(" ", "-")):
        if k in STORE_ALIASES:
            return STORE_ALIASES[k]
    # Inconnu : on garde le libellé propre (première lettre en majuscule).
    return " ".join(w.capitalize() for w in raw.split())


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = v.replace("$", "").replace(" ", "").replace(",", ".")
        try:
            return float(t)
        except ValueError:
            return None
    return None


def parse_workbook(content: bytes) -> list[dict]:
    """Lit toutes les feuilles et retourne des lignes normalisées :
    ``{materiau, magasin, prix_unitaire, qte, projet, categorie, type}``
    où ``type`` ∈ {unitaire, montant}."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    rows: list[dict] = []
    for ws in wb.worksheets:
        try:
            first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
        except StopIteration:
            continue
        hdr = [norm_key(c) for c in first]
        if "materiaux" in hdr and "detaillant" in hdr:
            rows.extend(_parse_list_sheet(ws, hdr))
            continue
        # Feuille MATRICE : seules les colonnes qui sont des magasins
        # CONNUS comptent (pas « Total », « En stock », « Colonne8 »…).
        stores = [
            (canonical_store(c) if c else None) for c in first
        ]
        stores = [st if st in STORE_ALIASES.values() else None for st in stores]
        if len([st for st in stores if st]) >= 3:
            rows.extend(_parse_matrix_sheet(ws, stores))
    return rows


def _parse_list_sheet(ws, hdr: list[str]) -> Iterable[dict]:
    im = hdr.index("materiaux")
    ist = hdr.index("detaillant")
    ip = hdr.index("prix unitaire") if "prix unitaire" in hdr else None
    iq = hdr.index("qte") if "qte" in hdr else None
    projet = ws.title.strip()
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r:
            continue
        name = str(r[im] or "").strip() if im < len(r) else ""
        store = canonical_store(r[ist]) if ist < len(r) else None
        price = _num(r[ip]) if ip is not None and ip < len(r) else None
        if not name or not store or not price or price <= 0:
            continue
        key = norm_key(name)
        if key in _SKIP_NAMES or key.startswith(_SKIP_PREFIXES):
            continue
        qty = _num(r[iq]) if iq is not None and iq < len(r) else None
        yield {
            "materiau": name, "magasin": store, "prix_unitaire": round(price, 2),
            "qte": qty, "projet": projet, "categorie": None, "type": "unitaire",
        }


def _parse_matrix_sheet(ws, stores: list[Optional[str]]) -> Iterable[dict]:
    projet = ws.title.strip()
    categorie: Optional[str] = None
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not r[0]:
            continue
        name = str(r[0]).strip()
        vals = [
            (stores[i], _num(v))
            for i, v in enumerate(r)
            if i > 0 and i < len(stores) and stores[i]
        ]
        vals = [(s, v) for s, v in vals if v and v > 0]
        if not vals:
            # Ligne sans montant chez un magasin : titre de section
            # (« Électricité ») si c'est un libellé de catégorie connu.
            key = norm_key(name).strip(" :")
            if key in _CATEGORY_LABELS:
                categorie = name.strip(" :").capitalize()
            continue
        for s, v in vals:
            yield {
                "materiau": name, "magasin": s, "prix_unitaire": round(v, 2),
                "qte": None, "projet": projet, "categorie": categorie,
                "type": "montant",
            }


async def import_rows(
    db: AsyncSession, rows: list[dict], *, source_label: str = "fichier"
) -> dict:
    """Crée / met à jour magasins, matériaux, offres (source=import) et
    historique. Idempotent : même fichier deux fois → aucune duplication
    (l'historique n'est réécrit que si le prix change). Flush, ne
    committe pas."""
    stats = {
        "lignes": len(rows), "magasins_crees": 0, "materiaux_crees": 0,
        "offres_creees": 0, "offres_mises_a_jour": 0, "offres_inchangees": 0,
        "offres_conservees_manuel": 0,
    }
    if not rows:
        return stats

    stores_by_name: dict[str, Magasin] = {
        m.name: m for m in (await db.execute(select(Magasin))).scalars().all()
    }
    mats_by_key: dict[str, Materiau] = {
        m.name_key: m for m in (await db.execute(select(Materiau))).scalars().all()
    }
    offres_by_pair: dict[tuple[int, int], MateriauOffre] = {
        (o.materiau_id, o.magasin_id): o
        for o in (await db.execute(select(MateriauOffre))).scalars().all()
    }

    # Une seule valeur par couple matériau × magasin : le prix UNITAIRE
    # prime sur un montant global ; à type égal, la dernière ligne gagne.
    best: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (norm_key(r["materiau"]), r["magasin"])
        cur = best.get(key)
        if cur is None or (cur["type"] == "montant" and r["type"] == "unitaire") or cur["type"] == r["type"]:
            best[key] = r

    for (mkey, store_name), r in best.items():
        store = stores_by_name.get(store_name)
        if store is None:
            store = Magasin(name=store_name)
            db.add(store)
            await db.flush()
            stores_by_name[store_name] = store
            stats["magasins_crees"] += 1
        mat = mats_by_key.get(mkey)
        if mat is None:
            mat = Materiau(
                name=r["materiau"][:255], name_key=mkey[:255],
                categorie=(r.get("categorie") or None),
            )
            db.add(mat)
            await db.flush()
            mats_by_key[mkey] = mat
            stats["materiaux_crees"] += 1
        elif not mat.categorie and r.get("categorie"):
            mat.categorie = r["categorie"]

        note = f"Historique projet {r['projet']} ({source_label})"
        off = offres_by_pair.get((mat.id, store.id))
        if r["type"] == "montant":
            # Montant payé, quantité inconnue → PAS un prix unitaire. On
            # retient seulement que ce magasin vend ce matériau.
            if off is None:
                off = MateriauOffre(
                    materiau_id=mat.id, magasin_id=store.id, unit_price=None,
                    source="import", observed_at=None,
                    note=(f"{note} — montant payé {r['prix_unitaire']:.2f} $, "
                          "quantité inconnue")[:255],
                )
                db.add(off)
                await db.flush()
                offres_by_pair[(mat.id, store.id)] = off
                stats["offres_creees"] += 1
            else:
                stats["offres_inchangees"] += 1
            continue
        price = float(r["prix_unitaire"])
        if off is None:
            off = MateriauOffre(
                materiau_id=mat.id, magasin_id=store.id, unit_price=price,
                source="import", observed_at=None, note=note[:255],
            )
            db.add(off)
            await db.flush()
            offres_by_pair[(mat.id, store.id)] = off
            stats["offres_creees"] += 1
            db.add(MateriauPrixHistorique(
                materiau_id=mat.id, magasin_id=store.id, unit_price=price,
                source="import", observed_at=None, note=note[:255],
            ))
            continue
        if off.source != "import":
            # Un prix saisi à la main ou relevé automatiquement est plus
            # récent qu'un fichier d'archive : on ne l'écrase pas.
            stats["offres_conservees_manuel"] += 1
            continue
        if off.unit_price is not None and abs(float(off.unit_price) - price) < 0.005:
            stats["offres_inchangees"] += 1
            continue
        off.unit_price = price
        off.note = note[:255]
        stats["offres_mises_a_jour"] += 1
        db.add(MateriauPrixHistorique(
            materiau_id=mat.id, magasin_id=store.id, unit_price=price,
            source="import", observed_at=None, note=note[:255],
        ))
    await db.flush()
    return stats
