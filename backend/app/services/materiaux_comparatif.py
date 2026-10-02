"""COMPARATIF SEMAINE PAR SEMAINE des matériaux d'une liste de projet
(retour Phil 2026-10-01, principe batirarabais) : pour chaque ligne encore
à acheter, le meilleur prix de chaque semaine (tous magasins actifs, à
partir de l'historique des relevés — un prix reste valable jusqu'au
relevé suivant), le plus bas de la période, la tendance, le prix du jour
et l'avis IA du matériau. Pour la liste : son coût au meilleur prix
semaine par semaine et la meilleure semaine.

``avis_ia_comparatif`` demande à Gemini, à partir de ce tableau et des
dates de phases, le meilleur moment pour acheter (maintenant / attendre /
partiel), ce qu'il faut prendre tout de suite et ce qui peut attendre.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.models.materiau import Magasin, MateriauOffre, MateriauPrixHistorique
from app.models.project_phase import ProjectPhase
from app.models.projet_materiau import ProjetMateriau
from app.services.materiaux_analyse_ia import analyse_dict

log = logging.getLogger(__name__)

SEMAINES_DEFAUT = 8
SEMAINES_MAX = 26
#: Un prix relevé reste « valable » tant qu'aucun relevé plus récent ne le
#: remplace, mais pas au-delà de ce délai.
VALIDITE_JOURS = 120
#: ± sous ce seuil, la tendance est « stable ».
SEUIL_TENDANCE = 0.03


@dataclass
class Point:
    quand: date
    prix: float
    on_sale: bool
    sale_end: Optional[date]
    regular_price: Optional[float]


@dataclass
class CelluleSemaine:
    semaine: date
    meilleur_prix: Optional[float] = None
    meilleur_magasin_id: Optional[int] = None
    rabais: bool = False
    par_magasin: dict[int, float] = field(default_factory=dict)


@dataclass
class LigneComparatif:
    ligne_id: int
    materiau_id: int
    materiau_name: str
    phase_id: Optional[int]
    quantity: float
    unit: Optional[str]
    semaines: list[CelluleSemaine]
    courant_prix: Optional[float] = None
    courant_magasin_id: Optional[int] = None
    plus_bas_prix: Optional[float] = None
    plus_bas_magasin_id: Optional[int] = None
    plus_bas_semaine: Optional[date] = None
    #: baisse | stable | hausse | inconnue
    tendance: str = "inconnue"
    #: Écart du prix du jour au plus bas de la période (0,12 = +12 %).
    ecart_plus_bas: Optional[float] = None
    verdict_ia: Optional[str] = None
    avis_ia: Optional[str] = None
    prix_cible_ia: Optional[float] = None
    analyse_ia_at: Optional[datetime] = None


@dataclass
class Comparatif:
    semaines: list[date]
    magasins: list[dict]
    lignes: list[LigneComparatif]
    #: Σ quantité × meilleur prix de la semaine (lignes couvertes).
    totaux_semaine: list[Optional[float]]
    #: Nombre de lignes avec un prix cette semaine-là.
    couverture_semaine: list[int]
    total_courant: Optional[float]
    meilleure_semaine: Optional[date]
    nb_lignes: int


def lundi(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _date(v: Any) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


async def _points(
    db, materiau_ids: list[int], actifs: set[int], depuis: date,
) -> dict[tuple[int, int], list[Point]]:
    """(materiau_id, magasin_id) → relevés datés (historique), triés."""
    out: dict[tuple[int, int], list[Point]] = {}
    if not materiau_ids:
        return out
    rows = (await db.execute(
        select(
            MateriauPrixHistorique.materiau_id, MateriauPrixHistorique.magasin_id,
            MateriauPrixHistorique.unit_price, MateriauPrixHistorique.on_sale, MateriauPrixHistorique.sale_end,
            MateriauPrixHistorique.regular_price, MateriauPrixHistorique.observed_at, MateriauPrixHistorique.created_at,
        ).where(MateriauPrixHistorique.materiau_id.in_(materiau_ids))
    )).all()
    for mid, mag_id, prix, rabais, fin, reg, obs, cree in rows:
        if mag_id not in actifs or prix is None or float(prix) <= 0:
            continue
        q = _date(obs) or _date(cree)
        if q is None or q < depuis:
            continue
        out.setdefault((mid, mag_id), []).append(Point(
            quand=q, prix=round(float(prix), 2), on_sale=bool(rabais), sale_end=fin,
            regular_price=(round(float(reg), 2) if reg is not None else None),
        ))
    for k in out:
        out[k].sort(key=lambda p: p.quand)
    return out


def _prix_semaine(points: list[Point], semaine: date) -> Optional[tuple[float, bool]]:
    """Prix en vigueur cette semaine chez un magasin : le dernier relevé
    au plus tard le dimanche, pas plus vieux que VALIDITE_JOURS. Un rabais
    terminé avant le lundi laisse place au prix régulier s'il est connu."""
    dimanche = semaine + timedelta(days=6)
    cand = None
    for p in points:
        if p.quand <= dimanche:
            cand = p
        else:
            break
    if cand is None or (dimanche - cand.quand).days > VALIDITE_JOURS:
        return None
    if cand.on_sale and cand.sale_end is not None and cand.sale_end < semaine:
        if cand.regular_price:
            return cand.regular_price, False
        return None
    return cand.prix, cand.on_sale


def _tendance(cellules: list[CelluleSemaine]) -> str:
    vals = [c.meilleur_prix for c in cellules if c.meilleur_prix is not None]
    if len(vals) < 2:
        return "inconnue"
    recent = vals[-1]
    ref = vals[0] if len(vals) < 5 else vals[-5]
    if ref <= 0:
        return "inconnue"
    v = (recent - ref) / ref
    if v > SEUIL_TENDANCE:
        return "hausse"
    if v < -SEUIL_TENDANCE:
        return "baisse"
    return "stable"


async def comparatif_hebdo(
    db, lignes: list[ProjetMateriau], magasins: dict[int, Magasin],
    *, semaines: int = SEMAINES_DEFAUT, today: Optional[date] = None,
) -> Comparatif:
    today = today or date.today()
    n = max(1, min(SEMAINES_MAX, int(semaines)))
    courante = lundi(today)
    cols = [courante - timedelta(weeks=i) for i in range(n - 1, -1, -1)]
    actifs = {mid for mid, m in magasins.items() if m.is_active}
    a_acheter = [l for l in lignes if l.statut != "achete"]
    pts = await _points(db, [l.materiau_id for l in a_acheter], actifs, cols[0] - timedelta(days=VALIDITE_JOURS))
    # Le prix du jour des offres compte comme un relevé d'aujourd'hui (une
    # offre saisie à la main n'a pas forcément d'historique).
    for l in a_acheter:
        for o in (l.materiau.offres if l.materiau else []):
            if o.unit_price is None or o.magasin_id not in actifs:
                continue
            q = _date(o.observed_at) or today
            lst = pts.setdefault((l.materiau_id, o.magasin_id), [])
            if not any(p.quand == q and abs(p.prix - float(o.unit_price)) < 0.005 for p in lst):
                lst.append(Point(
                    quand=q, prix=round(float(o.unit_price), 2), on_sale=bool(o.on_sale), sale_end=o.sale_end,
                    regular_price=(round(float(o.regular_price), 2) if o.regular_price is not None else None),
                ))
                lst.sort(key=lambda p: p.quand)
    out_lignes: list[LigneComparatif] = []
    for l in a_acheter:
        cellules: list[CelluleSemaine] = []
        for w in cols:
            c = CelluleSemaine(semaine=w)
            for mag_id in actifs:
                r = _prix_semaine(pts.get((l.materiau_id, mag_id), []), w)
                if r is None:
                    continue
                prix, rabais = r
                c.par_magasin[mag_id] = prix
                if c.meilleur_prix is None or prix < c.meilleur_prix - 0.005 or (
                    abs(prix - c.meilleur_prix) < 0.005 and mag_id < (c.meilleur_magasin_id or 10**9)
                ):
                    c.meilleur_prix, c.meilleur_magasin_id, c.rabais = prix, mag_id, rabais
            cellules.append(c)
        lc = LigneComparatif(
            ligne_id=l.id, materiau_id=l.materiau_id, materiau_name=(l.materiau.name if l.materiau else ""),
            phase_id=l.phase_id, quantity=float(l.quantity or 0), unit=l.unit, semaines=cellules,
        )
        cur = cellules[-1]
        lc.courant_prix, lc.courant_magasin_id = cur.meilleur_prix, cur.meilleur_magasin_id
        bas = [c for c in cellules if c.meilleur_prix is not None]
        if bas:
            b = min(bas, key=lambda c: (c.meilleur_prix, c.semaine))
            lc.plus_bas_prix, lc.plus_bas_magasin_id, lc.plus_bas_semaine = b.meilleur_prix, b.meilleur_magasin_id, b.semaine
            if lc.courant_prix is not None and b.meilleur_prix:
                lc.ecart_plus_bas = round((lc.courant_prix - b.meilleur_prix) / b.meilleur_prix, 3)
        lc.tendance = _tendance(cellules)
        ia = analyse_dict(l.materiau) if l.materiau is not None else None
        if ia:
            lc.verdict_ia, lc.avis_ia, lc.prix_cible_ia = ia.get("verdict"), ia.get("resume"), ia.get("prix_cible")
            lc.analyse_ia_at = l.materiau.analyse_ia_at
        out_lignes.append(lc)
    totaux: list[Optional[float]] = []
    couverture: list[int] = []
    for i, _w in enumerate(cols):
        t, k = 0.0, 0
        for lc in out_lignes:
            p = lc.semaines[i].meilleur_prix
            if p is not None:
                t += p * lc.quantity
                k += 1
        totaux.append(round(t, 2) if k else None)
        couverture.append(k)
    nb = len(out_lignes)
    complets = [(t, w) for t, w, k in zip(totaux, cols, couverture) if t is not None and k == nb and nb > 0]
    meilleure = min(complets, key=lambda x: (x[0], x[1]))[1] if complets else None
    return Comparatif(
        semaines=cols,
        magasins=[{"id": m.id, "name": m.name} for m in sorted(magasins.values(), key=lambda m: (m.position, m.id)) if m.is_active],
        lignes=out_lignes, totaux_semaine=totaux, couverture_semaine=couverture,
        total_courant=totaux[-1], meilleure_semaine=meilleure, nb_lignes=nb,
    )


# ───────────────────────── Avis IA sur le moment d'achat ─────────────────────────

_CACHE: dict[int, tuple[str, float, dict]] = {}
_CACHE_S = 6 * 3600

_SYSTEM = (
    "Tu es acheteur de matériaux pour un entrepreneur en construction au Québec. On te donne, pour une "
    "liste d'achats de projet, le meilleur prix de chaque matériau semaine par semaine (toutes quincailleries "
    "confondues, R = en rabais), le prix du jour, le plus bas de la période, l'avis déjà rendu sur l'historique "
    "long de chaque matériau et les dates des phases du chantier. Tu conseilles QUAND acheter, en te basant "
    "uniquement sur ces données, avec prudence (peu de données → le dire). "
    "Tu réponds UNIQUEMENT en JSON valide, sans texte autour, sans balises markdown."
)


def _json(text: str) -> Any:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        return json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, flags=re.DOTALL)
        try:
            return json.loads(m.group(0)) if m else None
        except ValueError:
            return None


def _tableau_compact(cmp: Comparatif, magasins: dict[int, Magasin], phases: list[ProjectPhase]) -> str:
    sem = [w.isoformat() for w in cmp.semaines]
    lignes = [f"Semaines (lundi) : {', '.join(sem)}"]
    ph = {p.id: p for p in phases}
    for lc in cmp.lignes:
        cells = []
        for c in lc.semaines:
            if c.meilleur_prix is None:
                cells.append("—")
            else:
                nom = magasins[c.meilleur_magasin_id].name if c.meilleur_magasin_id in magasins else "?"
                cells.append(f"{c.meilleur_prix:.2f} {nom}{' R' if c.rabais else ''}")
        phase = ph.get(lc.phase_id)
        ph_s = f"phase « {phase.name} » le {phase.start_date.isoformat()}" if (phase and phase.start_date) else "phase sans date"
        ia = f" ; avis long terme : {lc.verdict_ia} ({lc.avis_ia})" if lc.verdict_ia else ""
        lignes.append(
            f"- {lc.materiau_name} × {lc.quantity:g}{(' ' + lc.unit) if lc.unit else ''} ({ph_s}) : "
            f"{' | '.join(cells)} ; plus bas {lc.plus_bas_prix if lc.plus_bas_prix is not None else '—'} ; tendance {lc.tendance}{ia}"
        )
    tot = ", ".join(f"{t:.2f}" if t is not None else "—" for t in cmp.totaux_semaine)
    lignes.append(f"Coût de la liste au meilleur prix, par semaine : {tot}")
    return "\n".join(lignes)


async def avis_ia_comparatif(
    db, project_id: int, cmp: Comparatif, magasins: dict[int, Magasin], phases: list[ProjectPhase],
    *, force: bool = False,
) -> dict:
    """Avis de Gemini sur le moment d'achat de la liste (cache 6 h par
    projet tant que le tableau ne change pas)."""
    from app.integrations.ai import complete, is_configured

    if not cmp.lignes:
        return {"disponible": False, "raison": "Aucune ligne à acheter."}
    if not is_configured():
        return {"disponible": False, "raison": "IA non configurée sur le serveur (GEMINI_API_KEY)."}
    tableau = _tableau_compact(cmp, magasins, phases)
    cle = hashlib.sha1(tableau.encode("utf-8")).hexdigest()
    hit = _CACHE.get(project_id)
    if hit and not force and hit[0] == cle and time.monotonic() - hit[1] < _CACHE_S:
        return hit[2]
    prompt = (
        f"Date du jour : {date.today().isoformat()}.\n\n{tableau}\n\n"
        "Réponds dans ce format exact :\n"
        '{"moment": "maintenant|attendre|partiel", "semaine_conseillee": "<lundi YYYY-MM-DD ou null>", '
        '"resume": "<3 phrases max, en français, pour l\'acheteur>", '
        '"acheter_maintenant": ["<nom de matériau>", ...], "attendre": ["<nom de matériau>", ...], '
        '"economie_estimee": <nombre ou null>}\n'
        "Règles : un matériau en rabais ou dont la phase est à moins de 14 jours s'achète maintenant ; un matériau "
        "nettement au-dessus de son plus bas récent, avec une phase lointaine, peut attendre ; « partiel » = une "
        "partie maintenant, le reste plus tard. economie_estimee = ce qu'on gagnerait à suivre ton conseil plutôt "
        "qu'à tout acheter aujourd'hui (null si impossible à chiffrer)."
    )
    try:
        res = await complete(prompt=prompt, system=_SYSTEM, max_tokens=600, temperature=0.0, thinking_budget=0)
    except Exception as exc:  # noqa: BLE001
        log.warning("Avis IA comparatif projet %s : %s", project_id, str(exc)[:200])
        return {"disponible": False, "raison": f"L'IA n'a pas répondu ({str(exc)[:120]})."}
    d = _json(res.text)
    if not isinstance(d, dict):
        return {"disponible": False, "raison": "Réponse de l'IA illisible."}
    moment = str(d.get("moment") or "").strip().lower()
    out = {
        "disponible": True,
        "moment": moment if moment in ("maintenant", "attendre", "partiel") else "partiel",
        "semaine_conseillee": (str(d.get("semaine_conseillee"))[:10] if d.get("semaine_conseillee") else None),
        "resume": str(d.get("resume") or "")[:600],
        "acheter_maintenant": [str(x)[:120] for x in (d.get("acheter_maintenant") or []) if isinstance(x, str)][:50],
        "attendre": [str(x)[:120] for x in (d.get("attendre") or []) if isinstance(x, str)][:50],
        "economie_estimee": (float(d["economie_estimee"]) if isinstance(d.get("economie_estimee"), (int, float)) else None),
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "modele": res.model,
    }
    _CACHE[project_id] = (cle, time.monotonic(), out)
    return out
