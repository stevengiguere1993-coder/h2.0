"""ANALYSE IA des derniers prix relevés (retour Phil 2026-10-01) : « afin
de savoir si c'est le meilleur moment, l'IA doit faire une analyse des
derniers prix que nous avons scrapés ».

Pour chaque matériau du catalogue qui a des prix, on donne à l'IA les
relevés des 6 derniers mois (par magasin : date, prix, rabais) et les
offres du jour ; elle répond, par matériau :

    verdict          bon_moment | attendre | neutre
    tendance         baisse | stable | hausse
    frequence_rabais « en rabais ~1 semaine sur 4 chez Rona »
    prochain_rabais  « probable avant la fin octobre (cycle de 5 sem.) »
    prix_cible       prix à viser (plus bas récurrent), ou null
    resume           une phrase pour l'acheteur

Résultat stocké sur ``materiaux.analyse_ia`` (JSON) + ``analyse_ia_at``,
lu par le catalogue et par le plan d'achat des projets. Refait par le job
de nuit hebdomadaire (``materiaux_hebdo``) ; bouton manuel au catalogue.
Sans clé IA : rien n'est écrit, rien ne casse.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.materiau import Magasin, Materiau, MateriauPrixHistorique

log = logging.getLogger(__name__)

HISTORIQUE_JOURS = 180
#: Matériaux par appel IA (un prompt compact, une réponse JSON par lot).
LOT = 8
#: Points d'historique au plus par matériau dans le prompt.
MAX_POINTS = 40
VERDICTS = {"bon_moment", "attendre", "neutre"}
TENDANCES = {"baisse", "stable", "hausse"}

_SYSTEM = (
    "Tu es analyste d'achats pour un entrepreneur en construction au Québec. "
    "On te donne, pour des matériaux, l'historique des prix relevés chez des quincailleries "
    "(Home Depot, Rona, BMR, Canac, Patrick Morin) et les prix du jour. Tu juges si c'est un "
    "bon moment pour acheter, en te basant UNIQUEMENT sur ces données : niveau actuel vs plus "
    "bas et vs habituel, fréquence et profondeur des rabais, saisonnalité évidente. "
    "Prudent : peu de données → verdict neutre et dis-le. "
    "Tu réponds UNIQUEMENT en JSON valide, sans texte autour, sans balises markdown."
)


def analyse_dict(m: Materiau) -> Optional[dict]:
    if not m.analyse_ia:
        return None
    try:
        d = json.loads(m.analyse_ia)
        return d if isinstance(d, dict) else None
    except ValueError:
        return None


def _json(text: Optional[str]) -> Any:
    if not text:
        return None
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        return json.loads(t)
    except ValueError:
        m = re.search(r"[\[{].*[\]}]", t, flags=re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except ValueError:
            return None


def _compacter(points: list[tuple[datetime, str, float, bool]]) -> list[str]:
    """« 2026-08-12 Rona 21.99 R » — au plus MAX_POINTS, répartis sur la
    période (on garde toujours le plus ancien et le plus récent)."""
    pts = sorted(points, key=lambda p: p[0])
    if len(pts) > MAX_POINTS:
        pas = len(pts) / MAX_POINTS
        pts = [pts[int(i * pas)] for i in range(MAX_POINTS - 1)] + [pts[-1]]
    return [f"{d.date().isoformat()} {mag} {p:.2f}{' R' if r else ''}" for d, mag, p, r in pts]


def _bloc_materiau(m: Materiau, magasins: dict[int, Magasin], hist: list[tuple[datetime, str, float, bool]]) -> str:
    today = [
        f"{magasins[o.magasin_id].name if o.magasin_id in magasins else o.magasin_id} {float(o.unit_price):.2f}"
        + (f" (rabais, régulier {float(o.regular_price):.2f}" + (f", fin {o.sale_end.isoformat()}" if o.sale_end else "") + ")" if o.on_sale else "")
        for o in m.offres
        if o.unit_price is not None and (o.magasin_id not in magasins or magasins[o.magasin_id].is_active)
    ]
    lignes = [f"### id={m.id} — {m.name}" + (f" ({m.unit})" if m.unit else "")]
    lignes.append("Prix du jour : " + ("; ".join(today) if today else "aucun"))
    lignes.append(f"Historique ({len(hist)} relevés, 6 mois, R = en rabais) : " + ("; ".join(_compacter(hist)) if hist else "aucun"))
    return "\n".join(lignes)


def _normaliser(d: Any, ids: set[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    items = d.get("analyses") if isinstance(d, dict) else d
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            mid = int(it.get("id") or it.get("materiau_id"))
        except (TypeError, ValueError):
            continue
        if mid not in ids:
            continue
        verdict = str(it.get("verdict") or "neutre").strip().lower()
        tendance = str(it.get("tendance") or "stable").strip().lower()
        try:
            cible = float(it.get("prix_cible")) if it.get("prix_cible") not in (None, "", "null") else None
        except (TypeError, ValueError):
            cible = None
        out[mid] = {
            "verdict": verdict if verdict in VERDICTS else "neutre",
            "tendance": tendance if tendance in TENDANCES else "stable",
            "frequence_rabais": (str(it.get("frequence_rabais") or "")[:160] or None),
            "prochain_rabais": (str(it.get("prochain_rabais") or "")[:160] or None),
            "prix_cible": (round(cible, 2) if cible and cible > 0 else None),
            "resume": (str(it.get("resume") or "")[:300] or None),
        }
    return out


async def _historique(db, ids: list[int], magasins: dict[int, Magasin]) -> dict[int, list[tuple[datetime, str, float, bool]]]:
    depuis = datetime.now(timezone.utc) - timedelta(days=HISTORIQUE_JOURS)
    rows = (await db.execute(
        select(
            MateriauPrixHistorique.materiau_id, MateriauPrixHistorique.magasin_id, MateriauPrixHistorique.unit_price,
            MateriauPrixHistorique.on_sale, MateriauPrixHistorique.observed_at, MateriauPrixHistorique.created_at,
        ).where(MateriauPrixHistorique.materiau_id.in_(ids))
    )).all()
    out: dict[int, list] = {i: [] for i in ids}
    for mid, mag_id, prix, rabais, obs, cree in rows:
        quand = obs or cree
        if quand is None or prix is None:
            continue
        if quand.tzinfo is None:
            quand = quand.replace(tzinfo=timezone.utc)
        if quand < depuis:
            continue
        mag = magasins.get(mag_id)
        if mag is not None and not mag.is_active:
            continue
        out[mid].append((quand, mag.name if mag else str(mag_id), float(prix), bool(rabais)))
    return out


async def analyser_lot(db, materiaux: list[Materiau], magasins: dict[int, Magasin]) -> dict[int, dict]:
    """Un appel IA pour un lot de matériaux. Renvoie {id: analyse}. Ne
    persiste pas (l'appelant écrit et committe)."""
    from app.integrations.ai import complete

    ids = [m.id for m in materiaux]
    hist = await _historique(db, ids, magasins)
    blocs = "\n\n".join(_bloc_materiau(m, magasins, hist.get(m.id, [])) for m in materiaux)
    prompt = (
        f"Date du jour : {datetime.now(timezone.utc).date().isoformat()}.\n\n"
        f"{blocs}\n\n"
        "Pour CHAQUE matériau ci-dessus, réponds dans ce format exact :\n"
        '{"analyses": [{"id": <id>, "verdict": "bon_moment|attendre|neutre", "tendance": "baisse|stable|hausse", '
        '"frequence_rabais": "<court, ou null>", "prochain_rabais": "<court, ou null>", "prix_cible": <nombre ou null>, '
        '"resume": "<une phrase pour l\'acheteur, en français>"}]}\n'
        "Règles : « bon_moment » si le prix du jour est au plus bas connu ou en rabais net ; « attendre » si le prix du "
        "jour est nettement au-dessus de ce qu'on voit régulièrement et que des rabais reviennent ; « neutre » si les "
        "données ne permettent pas de trancher (dis-le dans le résumé). prix_cible = le prix bas qui revient, pas un rêve."
    )
    res = await complete(prompt=prompt, system=_SYSTEM, max_tokens=220 * len(materiaux) + 200, temperature=0.0, thinking_budget=0)
    return _normaliser(_json(res.text), set(ids))


DERNIERE_ANALYSE: dict = {"en_cours": False, "lance_a": None, "termine_a": None, "stats": None}


async def analyser_tout(
    db, *, limit: int = 200, max_age_days: Optional[float] = 6, materiau_id: Optional[int] = None, stats_live: Optional[dict] = None,
) -> dict:
    """Analyse les matériaux actifs ayant au moins un prix, jamais
    analysés d'abord puis les plus anciens ; ceux analysés depuis moins
    de ``max_age_days`` jours sont sautés. Commit par lot."""
    from app.integrations.ai import is_configured

    stats = stats_live if stats_live is not None else {}
    stats.update({"total": 0, "analyses": 0, "lots": 0, "erreurs": 0, "skipped": None})
    if not is_configured():
        stats["skipped"] = "IA non configurée (GEMINI_API_KEY)"
        return stats
    magasins = {m.id: m for m in (await db.execute(select(Magasin))).scalars().all()}
    stmt = (
        select(Materiau).where(Materiau.is_active.is_(True))
        .options(selectinload(Materiau.offres))
        .order_by(Materiau.analyse_ia_at.asc().nulls_first(), Materiau.id.asc())
    )
    if materiau_id is not None:
        stmt = stmt.where(Materiau.id == materiau_id)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)) if max_age_days else None
    todo: list[Materiau] = []
    for m in (await db.execute(stmt)).scalars().unique().all():
        if not any(o.unit_price is not None for o in m.offres):
            continue
        if cutoff is not None and materiau_id is None and m.analyse_ia_at is not None:
            a = m.analyse_ia_at if m.analyse_ia_at.tzinfo else m.analyse_ia_at.replace(tzinfo=timezone.utc)
            if a > cutoff:
                continue
        todo.append(m)
        if len(todo) >= limit:
            break
    stats["total"] = len(todo)
    for i in range(0, len(todo), LOT):
        lot = todo[i:i + LOT]
        try:
            res = await analyser_lot(db, lot, magasins)
        except Exception as exc:  # noqa: BLE001
            stats["erreurs"] += 1
            log.warning("Analyse IA prix : lot échoué (%s)", str(exc)[:200])
            if stats["erreurs"] >= 3:
                stats["skipped"] = "3 lots en erreur : arrêt (quota IA ?)"
                break
            continue
        now = datetime.now(timezone.utc)
        for m in lot:
            a = res.get(m.id)
            if a is None:
                continue
            m.analyse_ia = json.dumps(a, ensure_ascii=False)
            m.analyse_ia_at = now
            stats["analyses"] += 1
        stats["lots"] += 1
        await db.commit()
        await asyncio.sleep(0)
    return stats


async def analyser_tout_en_arriere_plan(**kwargs) -> None:
    from app.db.session import AsyncSessionLocal

    if DERNIERE_ANALYSE.get("en_cours"):
        return
    live: dict = {}
    DERNIERE_ANALYSE.update(en_cours=True, lance_a=datetime.now(timezone.utc).isoformat(), termine_a=None, stats=live)
    try:
        async with AsyncSessionLocal() as db:
            await analyser_tout(db, stats_live=live, **kwargs)
    except Exception as exc:  # noqa: BLE001
        log.exception("Analyse IA des prix en arrière-plan échouée")
        live["error"] = str(exc)[:300]
    finally:
        DERNIERE_ANALYSE.update(en_cours=False, termine_a=datetime.now(timezone.utc).isoformat())
