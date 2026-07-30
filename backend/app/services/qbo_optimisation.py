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

import logging
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

#: kind exposé par l'API → familles de comptes.
_KINDS = {
    "depense": _ACCOUNT_TYPES,
    "financement": _ACCOUNT_TYPES_FINANCEMENT,
    "banque": _ACCOUNT_TYPES_BANQUE,
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
