"""Parseur du « rent roll » copié-collé depuis PlexFlow.

PlexFlow n'offre pas d'export propre : l'utilisateur copie la page
« Property » d'une ou plusieurs compagnies et la colle telle quelle. Le
texte ressemble à :

    8900 St-Hubert inc

    Shared with you Property
    0 95% 15 $11,220 00
    8900 Rue St-Hubert, Montréal (Québec) H2M 1Y6
    8900, Rue Saint-Hubert
    Montréal, H2M 1Y6
    Unit	Rent	Status	Payment
    777 - A
    Junior Rosier
    $550
     Active

     Received
    +$550.34
    ...

Structure :
- une ligne « nom de compagnie » précède « Shared with you Property »
  (sauf quand une même compagnie a plusieurs immeubles : les blocs
  suivants n'ont pas de ligne nom — on conserve la compagnie courante) ;
- ligne KPI : « 0 <occ>% <nb_unités> $<revenu> <cents> » ;
- 1 à 3 lignes d'adresse (la forme structurée « rue » + « ville,
  code postal » est privilégiée) ;
- l'en-tête « Unit Rent Status Payment » ;
- puis les logements, un bloc de lignes par unité.

Le parseur est volontairement tolérant et dépendance-free (testable
sans la DB). Les cas ambigus produisent des `warnings` plutôt que des
plantages, et le bail n'est créé que lorsque locataire + loyer + statut
sont clairs (le reste devient un logement seul, signalé).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

PROP_MARK = "shared with you property"

# Valeurs possibles de la colonne « Status » (statut du bail).
STATUS_PRIMARY = {
    "active",
    "vacant",
    "scheduled",
    "reserved",
    "pending",
    "expired",
    "terminated",
}

# Lignes « de queue » d'une unité (après le statut) : renouvellement,
# paiement, montant. Sert à savoir où s'arrête une unité.
TRAILING_WORDS = {
    "received",
    "incomplete",
    "upcoming",
    "scheduled",
    "won't renew",
    "wont renew",
    "renewed",
    "pending",
    "notice given",
    "n/a",
    "na",
}

_AMOUNT_RE = re.compile(r"^[+-]?\$[\d,]")
_POSTAL_RE = re.compile(r"^(.*),\s*([A-Za-z]\d[A-Za-z]\s?\d[A-Za-z]\d)\s*$")
_KPI_RE = re.compile(r"^\d+\s+(\d+)%\s+(\d+)\s+\$([\d,]+)\s+(\d+)\b")
_MONEY_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)")


@dataclass
class ParsedUnit:
    numero: str
    tenant: Optional[str] = None
    rent: Optional[float] = None
    status: str = "vacant"  # active | vacant | scheduled | ...
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedBuilding:
    address: str
    city: Optional[str] = None
    postal_code: Optional[str] = None
    kpi_units: Optional[int] = None
    kpi_occupancy: Optional[float] = None  # 0..1
    kpi_revenue: Optional[float] = None
    units: list[ParsedUnit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedCompany:
    name: str
    buildings: list[ParsedBuilding] = field(default_factory=list)


def _is_trailing(line: str) -> bool:
    low = line.strip().lower()
    if not low:
        return True
    if low in TRAILING_WORDS:
        return True
    if low == "-":
        return True
    if _AMOUNT_RE.match(line.strip()):
        return True
    return False


def _parse_money(text: str) -> Optional[float]:
    m = _MONEY_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _clean_numero(numero: str, appt: Optional[str]) -> str:
    """Nettoie le n° d'unité. PlexFlow tronque parfois (« Stationne... »,
    « 3 - D (Pe... ») : si une étiquette « Appt # X » plus parlante existe
    et que le numéro est tronqué, on l'utilise."""
    num = numero.strip()
    truncated = num.endswith("...")
    if truncated and appt:
        derived = appt.split("#", 1)[-1].strip()
        # On évite de remplacer par un « 0 » peu utile.
        if derived and derived != "0":
            return derived
    return num.rstrip(". ").strip() or num


def _parse_units(unit_lines: list[str]) -> list[ParsedUnit]:
    units: list[ParsedUnit] = []
    i, n = 0, len(unit_lines)
    while i < n:
        numero = unit_lines[i].strip()
        i += 1
        if not numero:
            continue
        appt: Optional[str] = None
        if i < n and unit_lines[i].strip().lower().startswith("appt #"):
            appt = unit_lines[i].strip()
            i += 1
        # Lignes avant le statut : [locataire?, loyer?]
        pre: list[str] = []
        status: Optional[str] = None
        while i < n:
            cur = unit_lines[i].strip()
            if cur.lower() in STATUS_PRIMARY:
                status = cur.lower()
                i += 1
                break
            pre.append(cur)
            i += 1
        # Consomme la queue (paiement/renouvellement/montant) jusqu'à la
        # prochaine unité.
        while i < n and _is_trailing(unit_lines[i]):
            i += 1

        tenant: Optional[str] = None
        rent: Optional[float] = None
        for x in pre:
            xs = x.strip()
            if xs.startswith("$"):
                rent = _parse_money(xs)
            elif xs in ("-", ""):
                continue
            else:
                tenant = xs if tenant is None else f"{tenant}, {xs}"

        unit = ParsedUnit(
            numero=_clean_numero(numero, appt),
            tenant=tenant,
            rent=rent,
            status=status or "vacant",
        )
        if status is None:
            unit.warnings.append("statut illisible — logement créé vacant")
        units.append(unit)
    return units


def _parse_address(address_lines: list[str]) -> tuple[str, Optional[str], Optional[str]]:
    city: Optional[str] = None
    postal: Optional[str] = None
    for a in address_lines:
        low = a.lower()
        if "(québec)" in low or "(quebec)" in low:
            continue
        m = _POSTAL_RE.match(a)
        if m:
            city = m.group(1).strip()
            postal = m.group(2).strip()
            break
    # Rue = première ligne qui n'est ni l'en-tête « (Québec) » ni la
    # ligne ville/code postal.
    street = ""
    for a in address_lines:
        low = a.lower()
        if "(québec)" in low or "(quebec)" in low:
            continue
        if _POSTAL_RE.match(a):
            continue
        street = a.strip()
        break
    if not street and address_lines:
        street = address_lines[0].strip()
    return street, city, postal


def parse_plexflow(raw: str) -> tuple[list[ParsedCompany], list[str]]:
    """Parse le texte collé. Retourne (compagnies, warnings globaux)."""
    warnings: list[str] = []
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    prop_idxs = [i for i, ln in enumerate(lines) if ln.lower() == PROP_MARK]
    if not prop_idxs:
        return [], ["Aucun bloc « Shared with you Property » détecté."]

    companies: list[ParsedCompany] = []
    by_name: dict[str, ParsedCompany] = {}
    current: Optional[ParsedCompany] = None

    for idx, p in enumerate(prop_idxs):
        prev = lines[p - 1] if p > 0 else None
        # Nouvelle compagnie si la ligne précédente n'est pas une ligne de
        # queue d'unité (donc un vrai nom de compagnie).
        if prev is not None and prev.lower() != PROP_MARK and not _is_trailing(prev):
            name = prev.strip().rstrip(",").strip()
            key = name.lower()
            if key not in by_name:
                current = ParsedCompany(name=name)
                by_name[key] = current
                companies.append(current)
            else:
                current = by_name[key]
        if current is None:
            current = ParsedCompany(name="(compagnie inconnue)")
            companies.append(current)

        # Bornes du bloc immeuble : jusqu'au prochain « Property », en
        # excluant la ligne nom de la compagnie suivante si présente.
        next_p = prop_idxs[idx + 1] if idx + 1 < len(prop_idxs) else len(lines)
        end = next_p
        if next_p < len(lines):
            cand = lines[next_p - 1]
            if cand.lower() != PROP_MARK and not _is_trailing(cand):
                end = next_p - 1
        block = lines[p + 1 : end]
        if not block:
            continue

        building = _parse_building(block, warnings)
        if building is not None:
            current.buildings.append(building)

    return companies, warnings


def _parse_building(block: list[str], warnings: list[str]) -> Optional[ParsedBuilding]:
    kpi_units = kpi_occ = kpi_rev = None
    start = 0
    km = _KPI_RE.match(block[0]) if block else None
    if km:
        kpi_occ = int(km.group(1)) / 100.0
        kpi_units = int(km.group(2))
        kpi_rev = float(km.group(3).replace(",", "")) + int(km.group(4)) / 100.0
        start = 1

    # Trouve l'en-tête « Unit … Rent … » qui sépare adresse et logements.
    header_idx = None
    for j in range(start, len(block)):
        low = block[j].lower()
        if low.startswith("unit") and "rent" in low and "status" in low:
            header_idx = j
            break
    if header_idx is None:
        warnings.append("Bloc ignoré : en-tête « Unit/Rent/Status » introuvable.")
        return None

    address_lines = block[start:header_idx]
    unit_lines = block[header_idx + 1 :]
    street, city, postal = _parse_address(address_lines)
    units = _parse_units(unit_lines)

    b = ParsedBuilding(
        address=street,
        city=city,
        postal_code=postal,
        kpi_units=kpi_units,
        kpi_occupancy=kpi_occ,
        kpi_revenue=kpi_rev,
        units=units,
    )
    if kpi_units is not None and kpi_units != len(units):
        b.warnings.append(
            f"PlexFlow annonce {kpi_units} logements mais {len(units)} "
            "ont été lus — vérifie l'aperçu."
        )
    return b
