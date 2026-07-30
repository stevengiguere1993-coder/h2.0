"""Lecture QuickBooks pour les projets d'OPTIMISATION — 100 % lecture.

Deux besoins :
- lister les comptes de DÉPENSE du plan comptable (pour mapper les
  enveloppes de budget dans l'UI) ;
- totaliser le dépensé réel par compte sur une période (rapport
  ProfitAndLoss — couvre Bills, Purchases, écritures de journal…).

⚠️ Ce module n'ÉCRIT jamais dans QuickBooks et ne touche pas au flux
Construction : il consomme ``get_qbo(scope)`` en lecture seule.
"""
from __future__ import annotations

import json
import logging
import unicodedata
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

#: Types de comptes proposés au mapping des budgets (dépenses + immos —
#: les travaux capitalisables vivent souvent en Fixed Asset).
_ACCOUNT_TYPES = (
    "Expense",
    "Other Expense",
    "Cost of Goods Sold",
    "Fixed Asset",
)

#: Entrées d'argent qui FINANCENT une enveloppe (prêt, marge, apport,
#: subvention…) — on front la dépense, on se fait rembourser ensuite.
_ACCOUNT_TYPES_FINANCEMENT = (
    "Income",
    "Other Income",
    "Long Term Liability",
    "Other Current Liability",
    "Equity",
)

#: Comptes bancaires (solde courant affiché sur le budget).
_ACCOUNT_TYPES_BANQUE = ("Bank",)

#: Compte d'hypothèque du cashflow (capital = passif long terme).
_ACCOUNT_TYPES_HYPOTHEQUE = ("Long Term Liability",)

#: Avances des actionnaires — passif (dû à l'actionnaire) ou équité.
_ACCOUNT_TYPES_AVANCES = (
    "Other Current Liability",
    "Long Term Liability",
    "Equity",
)

#: kind exposé par l'API → familles de comptes.
_KINDS = {
    "depense": _ACCOUNT_TYPES,
    "financement": _ACCOUNT_TYPES_FINANCEMENT,
    "banque": _ACCOUNT_TYPES_BANQUE,
    "hypotheque": _ACCOUNT_TYPES_HYPOTHEQUE,
    "avances": _ACCOUNT_TYPES_AVANCES,
}


async def solde_compte(scope: str, account_id: str) -> Optional[float]:
    """Solde COURANT d'un compte QBO (``CurrentBalance``) — None si le
    compte est introuvable. Lecture seule."""
    from app.integrations.quickbooks import get_qbo

    qbo = get_qbo(scope)
    if not await _ready(qbo) or not account_id:
        return None
    safe = str(account_id).replace("'", "")
    rows = await qbo.query(
        f"SELECT Id, Name, CurrentBalance FROM Account WHERE Id = '{safe}'"
    )
    for r in rows:
        try:
            return float(r.get("CurrentBalance") or 0)
        except (TypeError, ValueError):
            return None
    return None


async def lister_comptes_depense(
    scope: str, kind: str = "depense"
) -> List[Dict[str, Any]]:
    """Plan comptable de la connexion ``scope``, filtré par famille
    (``depense`` | ``financement`` | ``banque``) → [{"id", "name",
    "fully_qualified_name", "account_type", "classification"}].
    RuntimeError si non connecté."""
    from app.integrations.quickbooks import get_qbo

    qbo = get_qbo(scope)
    if not await _ready(qbo):
        raise RuntimeError(
            f"QuickBooks n'est pas connecté pour « {scope} » "
            "(Paramètres → Intégrations)."
        )
    types_sql = ", ".join(
        f"'{t}'" for t in _KINDS.get(kind, _ACCOUNT_TYPES)
    )
    rows = await qbo.query(
        "SELECT Id, Name, FullyQualifiedName, AccountType, Classification "
        f"FROM Account WHERE Active = true AND AccountType IN ({types_sql}) "
        "MAXRESULTS 1000"
    )
    out = [
        {
            "id": str(r.get("Id")),
            "name": r.get("Name") or "",
            "fully_qualified_name": r.get("FullyQualifiedName")
            or r.get("Name")
            or "",
            "account_type": r.get("AccountType") or "",
            "classification": r.get("Classification") or "",
        }
        for r in rows
    ]
    out.sort(key=lambda x: x["fully_qualified_name"].lower())
    return out


def _walk_rows(node: Any, totals: Dict[str, float]) -> None:
    """Parcourt récursivement les Rows d'un rapport QBO et accumule
    {account_id: total} pour chaque ligne de détail portant un compte."""
    if isinstance(node, dict):
        rows = node.get("Rows", {}).get("Row") if "Rows" in node else None
        if rows:
            for r in rows:
                _walk_rows(r, totals)
        cols = node.get("ColData")
        if isinstance(cols, list) and cols:
            acc_id = cols[0].get("id")
            if acc_id:
                raw = (cols[-1].get("value") or "").replace(",", "")
                try:
                    totals[str(acc_id)] = totals.get(str(acc_id), 0.0) + float(raw)
                except ValueError:
                    pass
        # Les groupes (Header/Summary) contiennent parfois leurs propres
        # Rows imbriquées déjà couvertes ci-dessus — rien d'autre à faire.
    elif isinstance(node, list):
        for r in node:
            _walk_rows(r, totals)


async def depenses_par_compte(
    scope: str,
    date_debut: Optional[str],
    date_fin: Optional[str],
) -> Dict[str, float]:
    """Total dépensé par compte (id) entre les deux dates, toutes
    transactions confondues, via le rapport ProfitAndLoss (accrual).

    Un compte absent du rapport n'a simplement rien dépensé (0)."""
    from app.integrations.quickbooks import get_qbo

    qbo = get_qbo(scope)
    if not await _ready(qbo):
        raise RuntimeError(
            f"QuickBooks n'est pas connecté pour « {scope} » "
            "(Paramètres → Intégrations)."
        )
    params: Dict[str, str] = {"accounting_method": "Accrual"}
    if date_debut:
        params["start_date"] = date_debut
    if date_fin:
        params["end_date"] = date_fin
    report = await qbo.report("ProfitAndLoss", **params)
    totals: Dict[str, float] = {}
    _walk_rows(report.get("Rows", {}).get("Row") or [], totals)

    # Les TRAVAUX capitalisés (Fixed Asset) ne passent pas au P&L — on
    # complète par le bilan sur la même période (variation des immos).
    try:
        bs = await qbo.report(
            "BalanceSheet",
            accounting_method="Accrual",
            **({"start_date": date_debut} if date_debut else {}),
            **({"end_date": date_fin} if date_fin else {}),
        )
        _walk_rows(bs.get("Rows", {}).get("Row") or [], totals)
    except Exception as exc:  # noqa: BLE001 — le P&L reste utilisable
        log.info("Rapport BalanceSheet indisponible (%s) — P&L seul.", exc)
    return totals


def _groupes_pnl(node: Any, out: Dict[str, float]) -> None:
    """Relève les TOTAUX de section d'un rapport ProfitAndLoss :
    {"Income": …, "Expenses": …, "NetIncome": …}. QBO marque chaque
    section d'un ``group`` et porte son total dans ``Summary``."""
    if isinstance(node, list):
        for r in node:
            _groupes_pnl(r, out)
        return
    if not isinstance(node, dict):
        return
    groupe = node.get("group")
    somme = (node.get("Summary") or {}).get("ColData")
    if groupe and isinstance(somme, list) and somme:
        brut = (somme[-1].get("value") or "").replace(",", "").replace("$", "")
        try:
            out[str(groupe)] = float(brut)
        except ValueError:
            pass
    sous = (node.get("Rows") or {}).get("Row")
    if sous:
        _groupes_pnl(sous, out)


def _groupes_pnl_colonnes(
    node: Any, out: Dict[str, List[float]]
) -> None:
    """Comme ``_groupes_pnl`` mais garde TOUTES les colonnes du Summary
    (rapport mensuel : une valeur par mois + le total en dernier)."""
    if isinstance(node, list):
        for r in node:
            _groupes_pnl_colonnes(r, out)
        return
    if not isinstance(node, dict):
        return
    groupe = node.get("group")
    somme = (node.get("Summary") or {}).get("ColData")
    if groupe and isinstance(somme, list) and len(somme) > 1:
        vals: List[float] = []
        for cell in somme[1:]:  # [0] = libellé (« Total Income »…)
            brut = (
                (cell.get("value") or "0")
                .replace(",", "")
                .replace("$", "")
                .strip()
            )
            try:
                vals.append(float(brut) if brut else 0.0)
            except ValueError:
                vals.append(0.0)
        out[str(groupe)] = vals
    sous = (node.get("Rows") or {}).get("Row")
    if sous:
        _groupes_pnl_colonnes(sous, out)


#: Sections du P&L → sens du montant dans le cashflow.
_SECTIONS_REVENUS = {"Income", "OtherIncome"}
_SECTIONS_DEPENSES = {"Expenses", "COGS", "OtherExpenses"}


def _comptes_par_colonne(
    node: Any,
    out: List[Dict[str, Any]],
    section: Optional[str] = None,
) -> None:
    """Collecte les lignes de DÉTAIL (une par compte) d'un P&L mensuel :
    [{"nom", "type": "revenu"|"depense", "vals": [une valeur par
    colonne]}]. La section (Income, Expenses…) se propage en descendant
    l'arborescence."""
    if isinstance(node, list):
        for r in node:
            _comptes_par_colonne(r, out, section)
        return
    if not isinstance(node, dict):
        return
    section_ici = node.get("group") or section
    cols = node.get("ColData")
    if isinstance(cols, list) and len(cols) > 1 and node.get("type") == "Data":
        if section_ici in _SECTIONS_REVENUS or section_ici in _SECTIONS_DEPENSES:
            vals: List[float] = []
            for cell in cols[1:]:
                brut = (
                    (cell.get("value") or "0")
                    .replace(",", "")
                    .replace("$", "")
                    .strip()
                )
                try:
                    vals.append(float(brut) if brut else 0.0)
                except ValueError:
                    vals.append(0.0)
            nom = (cols[0].get("value") or "").strip()
            if nom and any(abs(v) >= 0.005 for v in vals):
                out.append(
                    {
                        "nom": nom,
                        "type": "revenu"
                        if section_ici in _SECTIONS_REVENUS
                        else "depense",
                        "vals": vals,
                    }
                )
    sous = (node.get("Rows") or {}).get("Row")
    if sous:
        _comptes_par_colonne(sous, out, section_ici)


def _soldes_par_compte_colonnes(
    node: Any, out: Dict[str, Dict[str, Any]]
) -> None:
    """Collecte les lignes de détail d'un BILAN mensuel :
    {account_id: {"nom", "vals": [solde de fin de chaque colonne]}}."""
    if isinstance(node, list):
        for r in node:
            _soldes_par_compte_colonnes(r, out)
        return
    if not isinstance(node, dict):
        return
    cols = node.get("ColData")
    if (
        isinstance(cols, list)
        and len(cols) > 1
        and node.get("type") == "Data"
        and cols[0].get("id")
    ):
        vals: List[float] = []
        for cell in cols[1:]:
            brut = (
                (cell.get("value") or "0")
                .replace(",", "")
                .replace("$", "")
                .strip()
            )
            try:
                vals.append(float(brut) if brut else 0.0)
            except ValueError:
                vals.append(0.0)
        out[str(cols[0].get("id"))] = {
            "nom": (cols[0].get("value") or "").strip(),
            "vals": vals,
        }
    sous = (node.get("Rows") or {}).get("Row")
    if sous:
        _soldes_par_compte_colonnes(sous, out)


def _assembler_avances(
    titres: List[str],
    series: Dict[str, Dict[str, Any]],
    selection: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Avances des actionnaires : pour chaque compte suivi, le solde
    courant et le flux mensuel (variation du solde de bilan). ``titres``
    inclut le mois de RÉFÉRENCE en tête — le 1er mois affiché est donc
    titres[1] et sa variation = vals[1] − vals[0]."""
    comptes: List[Dict[str, Any]] = []
    total = 0.0
    for c in selection:
        cid = str(c.get("id"))
        entry = series.get(cid) or {}
        nom = entry.get("nom") or c.get("name") or cid
        vals: List[float] = entry.get("vals") or []
        mois = [
            {
                "mois": titres[i],
                "variation": round(vals[i] - vals[i - 1], 2),
                "solde": round(vals[i], 2),
            }
            for i in range(1, min(len(titres), len(vals)))
        ]
        solde = round(vals[-1], 2) if vals else 0.0
        total += solde
        comptes.append(
            {"id": cid, "nom": nom, "solde": solde, "mois": mois}
        )
    comptes.sort(key=lambda x: -abs(float(x["solde"])))
    return {"comptes": comptes, "total": round(total, 2)}


async def _bilan_mensuel(
    scope: str,
    date_debut: Optional[str],
    date_fin: Optional[str],
) -> tuple:
    """Rapport BalanceSheet ventilé PAR MOIS, demandé un mois avant
    ``date_debut`` pour disposer d'une colonne de référence (sans elle,
    la variation du 1er mois serait incalculable). → (titres, series).
    Lecture seule."""
    from app.integrations.quickbooks import get_qbo

    qbo = get_qbo(scope)
    if not await _ready(qbo):
        raise RuntimeError(
            f"QuickBooks n'est pas connecté pour « {scope} »."
        )
    params: Dict[str, str] = {
        "accounting_method": "Accrual",
        "summarize_column_by": "Month",
    }
    if date_debut:
        d = date.fromisoformat(date_debut)
        ref = (d.replace(day=1) - timedelta(days=1)).replace(day=1)
        params["start_date"] = ref.isoformat()
    if date_fin:
        params["end_date"] = date_fin
    report = await qbo.report("BalanceSheet", **params)
    colonnes = (report.get("Columns") or {}).get("Column") or []
    titres = [
        (c.get("ColTitle") or "").strip() or f"Mois {i}"
        for i, c in enumerate(colonnes[1:], start=1)
    ]
    series: Dict[str, Dict[str, Any]] = {}
    _soldes_par_compte_colonnes(
        report.get("Rows", {}).get("Row") or [], series
    )
    # Certains fichiers ajoutent une colonne « Total » finale — on la
    # jette (un bilan n'a pas de total de période).
    if titres and titres[-1].lower() in ("total", "totaux"):
        titres = titres[:-1]
        for e in series.values():
            e["vals"] = e["vals"][: len(titres)]
    return titres, series


def _norm(s: str) -> str:
    """minuscules sans accents — pour matcher « actionnaire »."""
    return "".join(
        c
        for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn"
    )


async def avances_actionnaires(
    scope: str,
    date_debut: Optional[str],
    date_fin: Optional[str],
    accounts_json: Optional[str] = None,
) -> Dict[str, Any]:
    """Encadré « Avances des actionnaires » : solde courant + flux de
    changement mensuel de chaque compte suivi. Sélection manuelle via
    ``accounts_json`` ([{"id","name"}]) sinon auto-détection par nom
    (« actionnaire » / « shareholder ») dans le passif et l'équité."""
    selection: List[Dict[str, str]] = []
    auto = True
    if accounts_json:
        try:
            brut = json.loads(accounts_json)
        except Exception:  # noqa: BLE001 — JSON invalide = auto
            brut = []
        selection = [
            {"id": str(c.get("id")), "name": str(c.get("name") or "")}
            for c in brut
            if isinstance(c, dict) and c.get("id")
        ]
        auto = not selection
    if not selection:
        plan = await lister_comptes_depense(scope, "avances")
        selection = [
            {"id": c["id"], "name": c["name"]}
            for c in plan
            if "actionnaire" in _norm(c["fully_qualified_name"])
            or "shareholder" in _norm(c["fully_qualified_name"])
        ]
        auto = True
    if not selection:
        return {"comptes": [], "total": 0.0, "selection": [], "auto": True}
    titres, series = await _bilan_mensuel(scope, date_debut, date_fin)
    out = _assembler_avances(titres, series, selection)
    out["selection"] = [c["id"] for c in selection]
    out["auto"] = auto
    return out


def _assembler_cashflow(
    titres: List[str],
    groupes: Dict[str, List[float]],
    comptes: Optional[List[Dict[str, Any]]] = None,
    hypotheque: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Combine les colonnes mensuelles du P&L en lignes de cashflow :
    ``titres`` = libellés de colonnes SANS la première (une par mois,
    la dernière étant « Total »)."""
    n = len(titres)

    def _serie(*cles: str) -> List[float]:
        out = [0.0] * n
        for cle in cles:
            vals = groupes.get(cle) or []
            for i in range(min(n, len(vals))):
                out[i] += vals[i]
        return out

    revenus = _serie("Income", "OtherIncome")
    depenses = _serie("Expenses", "COGS", "OtherExpenses")
    net = groupes.get("NetIncome")
    hyp = [0.0] * n
    for i in range(min(n, len(hypotheque or []))):
        hyp[i] = float((hypotheque or [])[i])
    # Écart = revenus − dépenses − hypothèque (capital remboursé, lu
    # du bilan — le P&L ne voit que les intérêts).
    ecarts = [
        (net[i] if net and i < len(net) else revenus[i] - depenses[i])
        - hyp[i]
        for i in range(n)
    ]
    def _details(i: int) -> List[Dict[str, Any]]:
        """Comptes non nuls de la colonne ``i`` — revenus d'abord."""
        out: List[Dict[str, Any]] = []
        for c in comptes or []:
            v = c["vals"][i] if i < len(c["vals"]) else 0.0
            if abs(v) >= 0.005:
                out.append(
                    {"nom": c["nom"], "type": c["type"], "montant": round(v, 2)}
                )
        out.sort(key=lambda x: (x["type"] != "revenu", -abs(x["montant"])))
        return out

    mois = [
        {
            "mois": titres[i],
            "revenus": round(revenus[i], 2),
            "depenses": round(depenses[i], 2),
            "hypotheque": round(hyp[i], 2),
            "ecart": round(ecarts[i], 2),
            "details": _details(i),
        }
        for i in range(n - 1)  # la dernière colonne est le total
    ]
    total = {
        "revenus": round(revenus[-1], 2) if n else 0.0,
        "depenses": round(depenses[-1], 2) if n else 0.0,
        "hypotheque": round(hyp[-1], 2) if n else 0.0,
        "ecart": round(ecarts[-1], 2) if n else 0.0,
        "details": _details(n - 1) if n else [],
    }
    return {"mois": mois, "total": total}


async def cashflow_mensuel(
    scope: str,
    date_debut: Optional[str],
    date_fin: Optional[str],
    hypotheque_account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Cashflow d'opération PAR MOIS (revenus, dépenses, écart) lu du
    rapport ProfitAndLoss ventilé mensuellement + total de période.
    Lecture seule."""
    from app.integrations.quickbooks import get_qbo

    qbo = get_qbo(scope)
    if not await _ready(qbo):
        raise RuntimeError(
            f"QuickBooks n'est pas connecté pour « {scope} »."
        )
    params: Dict[str, str] = {
        "accounting_method": "Accrual",
        "summarize_column_by": "Month",
    }
    if date_debut:
        params["start_date"] = date_debut
    if date_fin:
        params["end_date"] = date_fin
    report = await qbo.report("ProfitAndLoss", **params)

    colonnes = (report.get("Columns") or {}).get("Column") or []
    titres = [
        (c.get("ColTitle") or "").strip() or f"Mois {i}"
        for i, c in enumerate(colonnes[1:], start=1)  # [0] = libellés
    ]
    groupes: Dict[str, List[float]] = {}
    _groupes_pnl_colonnes(report.get("Rows", {}).get("Row") or [], groupes)
    comptes: List[Dict[str, Any]] = []
    _comptes_par_colonne(
        report.get("Rows", {}).get("Row") or [], comptes
    )

    # Colonne Hypothèque : baisse mensuelle du compte de passif choisi
    # (capital remboursé), lue du bilan et alignée À DROITE sur les
    # mois du P&L (les deux rapports couvrent la même période).
    hyp: Optional[List[float]] = None
    if hypotheque_account_id:
        try:
            _, series = await _bilan_mensuel(scope, date_debut, date_fin)
            entry = series.get(str(hypotheque_account_id))
            vals = (entry or {}).get("vals") or []
            variations = [
                vals[i - 1] - vals[i] for i in range(1, len(vals))
            ]
            nb_mois = max(0, len(titres) - 1)
            hyp = [0.0] * nb_mois
            m = min(nb_mois, len(variations))
            for j in range(m):
                hyp[nb_mois - 1 - j] = variations[len(variations) - 1 - j]
            hyp.append(sum(hyp))  # colonne Total
        except Exception as exc:  # noqa: BLE001 — cashflow sans hyp
            log.info("hypothèque cashflow (%s): %s", scope, exc)
            hyp = None
    return _assembler_cashflow(titres, groupes, comptes, hyp)


async def rentabilite(
    scope: str,
    date_debut: Optional[str],
    date_fin: Optional[str],
) -> Dict[str, float]:
    """Rentabilité de la compagnie sur la période : revenus totaux,
    dépenses totales et résultat net (négatif = la compagnie a coûté
    plus qu'elle n'a rapporté). Lecture seule."""
    from app.integrations.quickbooks import get_qbo

    qbo = get_qbo(scope)
    if not await _ready(qbo):
        raise RuntimeError(
            f"QuickBooks n'est pas connecté pour « {scope} »."
        )
    params: Dict[str, str] = {"accounting_method": "Accrual"}
    if date_debut:
        params["start_date"] = date_debut
    if date_fin:
        params["end_date"] = date_fin
    report = await qbo.report("ProfitAndLoss", **params)
    groupes: Dict[str, float] = {}
    _groupes_pnl(report.get("Rows", {}).get("Row") or [], groupes)

    revenus = groupes.get("Income", 0.0) + groupes.get("OtherIncome", 0.0)
    depenses = (
        groupes.get("Expenses", 0.0)
        + groupes.get("COGS", 0.0)
        + groupes.get("OtherExpenses", 0.0)
    )
    net = groupes.get("NetIncome")
    if net is None:
        net = revenus - depenses
    return {
        "revenus": round(revenus, 2),
        "depenses": round(depenses, 2),
        "net": round(net, 2),
    }


async def _ready(qbo: Any) -> bool:
    """True si la connexion a un refresh token (DB ou env)."""
    try:
        if qbo.ready:
            return True
        await qbo._load_refresh_from_db()  # noqa: SLF001 — même package
        return bool(qbo.ready)
    except Exception:  # noqa: BLE001
        return False
