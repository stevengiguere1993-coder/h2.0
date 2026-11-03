"""Produits/services QuickBooks de la facturation Kratos (frais de gestion,
relocation, frais manuels, heures refacturées) — RÉGLÉS DANS L'UI, jamais
codés en dur.

Phil 2026-11-02 : « le type de transaction et les détails de cette facture,
je ne peux rien changer dans Kratos… pour l'instant les factures c'est des
services non catégorisés ». Avant : chaque flux appelait
``ensure_item("Frais de gestion")`` qui créait un service rattaché au PREMIER
compte de revenus de QuickBooks (souvent « non catégorisé »).

Réglage ``automation_settings.frais_gestion_qbo`` :
    {"items": {"gestion": {"id", "name"}, "relocation": …, "manuel": …,
               "heures": …},
     "mode_facture": "mensuelle" | "distincte"}
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from app.models.automation_setting import AutomationSetting

KEY = "frais_gestion_qbo"

#: Types de ligne facturés par Kratos et leur libellé dans les Réglages.
TYPES_LIGNE = ("gestion", "relocation", "manuel", "heures")
LABELS = {
    "gestion": "Frais de gestion mensuels (% des loyers)",
    "relocation": "Frais de relocation (logement / chambre)",
    "manuel": "Frais manuels (libellé libre)",
    "heures": "Heures refacturées (feuille de temps)",
}
#: Service historique créé au besoin quand rien n'est réglé (rétro-compat).
NOMS_DEFAUT = {
    "gestion": ("Frais de gestion", "Frais de gestion immobilière mensuels"),
    "relocation": ("Frais de gestion", "Frais de gestion immobilière mensuels"),
    "manuel": ("Frais de gestion", "Frais de gestion immobilière mensuels"),
    "heures": ("Heures", "Heures de main-d'oeuvre refacturées"),
}
MODES_FACTURE = ("mensuelle", "distincte")
MODES_LABELS = {
    "mensuelle": "Facture du mois (ouverte, une par client et par mois — jamais envoyée par Kratos)",
    "distincte": "Facture distincte à chaque envoi (une nouvelle facture par clic)",
}


def _normaliser(cfg: Any) -> Dict[str, Any]:
    cfg = cfg if isinstance(cfg, dict) else {}
    items: Dict[str, Dict[str, str]] = {}
    for t, v in (cfg.get("items") or {}).items():
        if t in TYPES_LIGNE and isinstance(v, dict) and str(v.get("id") or "").strip():
            items[t] = {"id": str(v["id"]).strip(), "name": str(v.get("name") or "").strip()[:120]}
    mode = cfg.get("mode_facture") if cfg.get("mode_facture") in MODES_FACTURE else "mensuelle"
    return {"items": items, "mode_facture": mode}


async def charger_reglages(db) -> Dict[str, Any]:
    row = await db.get(AutomationSetting, KEY)
    if not row or not row.config_json:
        return _normaliser({})
    try:
        return _normaliser(json.loads(row.config_json))
    except Exception:  # noqa: BLE001
        return _normaliser({})


async def enregistrer_reglages(db, *, items: Dict[str, Any], mode_facture: str) -> Dict[str, Any]:
    """Remplace les réglages (validation faite par l'appelant). N'appelle
    pas commit."""
    propre = _normaliser({"items": items, "mode_facture": mode_facture})
    row = await db.get(AutomationSetting, KEY)
    if row is None:
        row = AutomationSetting(key=KEY, enabled=True)
        db.add(row)
    row.config_json = json.dumps(propre, ensure_ascii=False)
    await db.flush()
    return propre


def item_utilisable(item: Optional[Dict[str, Any]]) -> Optional[str]:
    """None si l'item peut porter une ligne de facture, sinon la raison."""
    if not item:
        return "introuvable dans QuickBooks"
    if str(item.get("Type") or "") == "Category":
        return "c'est une CATÉGORIE de la liste Produits et services, pas un produit ou un service"
    if item.get("Active") is False:
        return "il est inactif dans QuickBooks"
    return None


async def item_pour_ligne(
    qbo, reglages: Dict[str, Any], type_ligne: str, item_id: Optional[str] = None,
    *, cache: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Produit/service QuickBooks d'une ligne : celui choisi SUR la ligne,
    sinon celui réglé pour ce type de ligne, sinon le service historique
    (créé au besoin). Lève ValueError (→ 422) si l'item choisi n'est pas
    utilisable."""
    cache = cache if cache is not None else {}
    voulu = (item_id or "").strip() or ((reglages.get("items") or {}).get(type_ligne) or {}).get("id")
    if voulu:
        if voulu not in cache:
            it = await qbo.get_item(voulu)
            raison = item_utilisable(it)
            if raison:
                raise ValueError(
                    f"Produit/service QuickBooks #{voulu} inutilisable : {raison} — "
                    "choisis-en un autre dans la ligne ou dans Réglages → QuickBooks."
                )
            cache[voulu] = it
        return cache[voulu]
    nom, desc = NOMS_DEFAUT.get(type_ligne, NOMS_DEFAUT["gestion"])
    cle = f"defaut:{nom}"
    if cle not in cache:
        cache[cle] = await qbo.ensure_item(nom, description=desc)
    return cache[cle]


def resume_item(it: Dict[str, Any]) -> Dict[str, Any]:
    ref = it.get("IncomeAccountRef") or {}
    return {
        "id": str(it.get("Id") or ""),
        "name": str(it.get("Name") or ""),
        "type": str(it.get("Type") or ""),
        "income_account_id": str(ref.get("value") or "") or None,
        "income_account": str(ref.get("name") or "") or None,
        "description": str(it.get("Description") or "") or None,
    }


__all__ = [
    "KEY", "TYPES_LIGNE", "LABELS", "NOMS_DEFAUT", "MODES_FACTURE", "MODES_LABELS",
    "charger_reglages", "enregistrer_reglages", "item_pour_ligne", "item_utilisable", "resume_item",
]
