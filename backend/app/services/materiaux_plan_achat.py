"""PLAN D'ACHAT d'un projet — le principe de batirarabais.ca appliqué à
notre liste de matériaux (retour Phil 2026-10-01) : « selon les phases
d'un projet, avec le prix des matériaux, décider du meilleur moment pour
acheter le stock ».

Pour chaque ligne encore à acheter :

- le meilleur prix du jour (tous magasins actifs) et le rabais en cours ;
- le PLUS BAS PRIX CONNU (historique des ``HISTORIQUE_JOURS`` derniers
  jours, tous magasins) : la référence « est-ce un bon prix ? » ;
- la DATE DE LA PHASE (il faut l'avoir avant) ;
- → un MOMENT : ``maintenant`` (rabais / au plus bas connu / la phase
  est imminente), ``attendre`` (prix au-dessus du plus bas connu et la
  phase est loin : l'alerte rabais quotidienne prévient), ``sans_prix``
  (rien de connu : à chercher au catalogue).

Et pour la liste entière : le plan « meilleur prix par ligne » (quel
magasin pour quoi, total par magasin) comparé à « tout au même magasin »
(un seul déplacement), avec l'économie entre les deux.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import select

from app.models.materiau import Magasin, MateriauOffre, MateriauPrixHistorique
from app.models.project_phase import ProjectPhase
from app.models.projet_materiau import ProjetMateriau
from app.services.materiaux_alertes import offre_en_rabais, prix_courant

#: Fenêtre de l'historique pour le « plus bas prix connu ».
HISTORIQUE_JOURS = 180
#: Au-delà de cet écart au-dessus du plus bas connu, on conseille d'attendre.
ECART_ATTENDRE = 0.05
#: À moins de ce nombre de jours de la phase, on n'attend plus.
JOURS_PHASE_IMMINENTE = 14


@dataclass
class PlusBas:
    prix: float
    magasin_id: int
    observe_le: Optional[date]


@dataclass
class Recommandation:
    ligne_id: int
    materiau_id: int
    materiau_name: str
    phase_id: Optional[int]
    quantity: float
    unit: Optional[str]
    #: maintenant | attendre | sans_prix
    moment: str
    raison: str
    magasin_id: Optional[int] = None
    magasin_name: Optional[str] = None
    unit_price: Optional[float] = None
    total: Optional[float] = None
    regular_price: Optional[float] = None
    on_sale: bool = False
    sale_end: Optional[date] = None
    url: Optional[str] = None
    plus_bas: Optional[float] = None
    plus_bas_magasin: Optional[str] = None
    plus_bas_le: Optional[date] = None
    #: Écart du prix du jour au plus bas connu (0,12 = 12 % plus cher).
    ecart_plus_bas: Optional[float] = None
    #: Économie du rabais vs prix régulier affiché (× quantité).
    economie_rabais: float = 0.0


@dataclass
class PhasePlan:
    phase_id: Optional[int]
    name: str
    start_date: Optional[date]
    jours_avant: Optional[int]
    #: Date limite d'achat conseillée (quelques jours avant la phase).
    acheter_avant: Optional[date]
    lignes: list[Recommandation] = field(default_factory=list)
    total_maintenant: float = 0.0
    total_attendre: float = 0.0
    nb_sans_prix: int = 0


@dataclass
class MagasinPlan:
    magasin_id: int
    magasin_name: str
    nb_lignes: int
    total: float
    #: Lignes de la liste que ce magasin ne couvre pas (sans prix chez lui).
    nb_manquantes: int = 0


@dataclass
class PlanAchat:
    phases: list[PhasePlan]
    #: Plan « meilleur prix par ligne » : total par magasin.
    par_magasin: list[MagasinPlan]
    total_meilleur: float
    nb_magasins: int
    #: Meilleure option « tout au même magasin » (couverture complète ou la
    #: plus large), et ce qu'elle coûte de plus.
    un_seul_magasin: Optional[MagasinPlan]
    economie_vs_un_seul: float
    nb_lignes: int
    nb_maintenant: int
    nb_attendre: int
    nb_sans_prix: int
    total_maintenant: float
    total_attendre: float
    economie_rabais: float


async def plus_bas_connus(
    db, materiau_ids: Iterable[int], magasins_actifs: set[int], jours: int = HISTORIQUE_JOURS,
) -> dict[int, PlusBas]:
    ids = list({int(i) for i in materiau_ids})
    if not ids:
        return {}
    depuis = datetime.now(timezone.utc) - timedelta(days=jours)
    rows = (await db.execute(
        select(
            MateriauPrixHistorique.materiau_id, MateriauPrixHistorique.magasin_id,
            MateriauPrixHistorique.unit_price, MateriauPrixHistorique.observed_at, MateriauPrixHistorique.created_at,
        ).where(MateriauPrixHistorique.materiau_id.in_(ids))
    )).all()
    out: dict[int, PlusBas] = {}
    for mid, mag_id, prix, observe, cree in rows:
        if mag_id not in magasins_actifs or prix is None or float(prix) <= 0:
            continue
        quand = observe or cree
        if quand is not None and quand.tzinfo is None:
            quand = quand.replace(tzinfo=timezone.utc)
        if quand is not None and quand < depuis:
            continue
        p = round(float(prix), 2)
        cur = out.get(mid)
        if cur is None or p < cur.prix - 0.005:
            out[mid] = PlusBas(prix=p, magasin_id=mag_id, observe_le=(quand.date() if quand else None))
    return out


def _nom(magasins: dict[int, Magasin], mid: Optional[int]) -> Optional[str]:
    if mid is None:
        return None
    m = magasins.get(mid)
    return m.name if m else f"#{mid}"


def recommander(
    ligne: ProjetMateriau,
    offres: Iterable[MateriauOffre],
    magasins: dict[int, Magasin],
    plus_bas: Optional[PlusBas],
    phase: Optional[ProjectPhase],
    today: Optional[date] = None,
) -> Recommandation:
    today = today or date.today()
    actifs = {mid for mid, m in magasins.items() if m.is_active}
    pc = prix_courant(ligne, offres, actifs)
    qty = float(ligne.quantity or 0)
    rec = Recommandation(
        ligne_id=ligne.id, materiau_id=ligne.materiau_id,
        materiau_name=(ligne.materiau.name if ligne.materiau else ""),
        phase_id=ligne.phase_id, quantity=qty, unit=ligne.unit, moment="sans_prix", raison="",
    )
    # Le candidat d'achat : le rabais s'il y en a un (jamais plus cher que
    # l'offre retenue), sinon l'offre retenue (magasin choisi ou la moins
    # chère).
    o = pc.rabais or pc.offre
    if o is None or o.unit_price is None:
        rec.raison = "Aucun prix connu : cherche-le au catalogue (loupe) ou saisis-le."
        return rec
    prix = round(float(o.unit_price), 2)
    rec.magasin_id, rec.magasin_name = o.magasin_id, _nom(magasins, o.magasin_id)
    rec.unit_price, rec.total = prix, round(prix * qty, 2)
    rec.regular_price = round(float(o.regular_price), 2) if o.regular_price is not None else None
    rec.on_sale, rec.sale_end, rec.url = offre_en_rabais(o, today), o.sale_end, o.url
    if rec.on_sale and rec.regular_price and rec.regular_price > prix:
        rec.economie_rabais = round((rec.regular_price - prix) * qty, 2)
    if plus_bas is not None:
        rec.plus_bas, rec.plus_bas_le = plus_bas.prix, plus_bas.observe_le
        rec.plus_bas_magasin = _nom(magasins, plus_bas.magasin_id)
        rec.ecart_plus_bas = round((prix - plus_bas.prix) / plus_bas.prix, 3) if plus_bas.prix > 0 else None

    jours = None
    if phase is not None and phase.start_date is not None:
        jours = (phase.start_date - today).days
    imminent = jours is not None and jours <= JOURS_PHASE_IMMINENTE
    au_plus_bas = rec.ecart_plus_bas is None or rec.ecart_plus_bas <= ECART_ATTENDRE

    if rec.on_sale:
        rec.moment = "maintenant"
        fin = f" jusqu'au {rec.sale_end.isoformat()}" if rec.sale_end else ""
        pct = f" (−{round((1 - prix / rec.regular_price) * 100)} % vs {rec.regular_price:.2f} $ régulier)" if rec.regular_price and rec.regular_price > prix else ""
        bas = "" if au_plus_bas else f" — déjà vu à {rec.plus_bas:.2f} $ chez {rec.plus_bas_magasin}"
        rec.raison = f"En rabais chez {rec.magasin_name}{fin}{pct}{bas}."
    elif imminent:
        rec.moment = "maintenant"
        quand = "commence aujourd'hui" if jours == 0 else ("a commencé" if jours < 0 else f"commence dans {jours} j")
        bas = f" Historiquement {round(rec.ecart_plus_bas * 100)} % moins cher ({rec.plus_bas:.2f} $ chez {rec.plus_bas_magasin}), mais pas le temps d'attendre." if not au_plus_bas else ""
        rec.raison = f"La phase {quand} : à acheter chez {rec.magasin_name} ({prix:.2f} $).{bas}"
    elif not au_plus_bas:
        rec.moment = "attendre"
        quand_phase = f"la phase est dans {jours} j" if jours is not None else "pas de date de phase"
        vu = f" le {rec.plus_bas_le.isoformat()}" if rec.plus_bas_le else ""
        rec.raison = (
            f"{prix:.2f} $ chez {rec.magasin_name}, {round(rec.ecart_plus_bas * 100)} % au-dessus du plus bas connu "
            f"({rec.plus_bas:.2f} $ chez {rec.plus_bas_magasin}{vu}) ; {quand_phase} : attendre un rabais (alerte automatique)."
        )
    else:
        rec.moment = "maintenant"
        ref = "au plus bas connu" if rec.plus_bas is not None else "meilleur prix du jour, sans historique"
        rec.raison = f"{prix:.2f} $ chez {rec.magasin_name} : {ref}."
    return rec


def _plan_magasins(
    lignes: list[ProjetMateriau], magasins: dict[int, Magasin],
) -> tuple[list[MagasinPlan], float, Optional[MagasinPlan], float]:
    actifs = {mid for mid, m in magasins.items() if m.is_active}
    par: dict[int, MagasinPlan] = {}
    total_meilleur = 0.0
    # Pour « tout au même magasin » : total si on achète TOUTE la liste
    # chez X (lignes sans prix chez X = manquantes).
    seul: dict[int, MagasinPlan] = {}
    n_lignes = 0
    for l in lignes:
        offres = [o for o in (l.materiau.offres if l.materiau else []) if o.unit_price is not None and o.magasin_id in actifs]
        if not offres:
            continue
        n_lignes += 1
        qty = float(l.quantity or 0)
        pc = prix_courant(l, offres, actifs)
        best = pc.rabais or pc.meilleure
        if best is not None:
            t = round(float(best.unit_price) * qty, 2)
            mp = par.setdefault(best.magasin_id, MagasinPlan(best.magasin_id, _nom(magasins, best.magasin_id) or "", 0, 0.0))
            mp.nb_lignes += 1
            mp.total = round(mp.total + t, 2)
            total_meilleur += t
        for mid in actifs:
            sp = seul.setdefault(mid, MagasinPlan(mid, _nom(magasins, mid) or "", 0, 0.0))
            o = next((x for x in offres if x.magasin_id == mid), None)
            if o is None:
                sp.nb_manquantes += 1
            else:
                sp.nb_lignes += 1
                sp.total = round(sp.total + float(o.unit_price) * qty, 2)
    candidats = [s for s in seul.values() if s.nb_lignes > 0]
    # Couverture complète d'abord, puis le moins cher ; sinon la plus large.
    complets = [s for s in candidats if s.nb_manquantes == 0]
    un_seul = min(complets, key=lambda s: s.total) if complets else (
        min(candidats, key=lambda s: (s.nb_manquantes, s.total)) if candidats else None
    )
    economie = round(un_seul.total - total_meilleur, 2) if (un_seul is not None and un_seul.nb_manquantes == 0) else 0.0
    liste = sorted(par.values(), key=lambda m: (-m.total, m.magasin_name))
    return liste, round(total_meilleur, 2), un_seul, max(0.0, economie)


async def plan_achat(
    db, lignes: list[ProjetMateriau], phases: list[ProjectPhase], magasins: dict[int, Magasin],
    today: Optional[date] = None,
) -> PlanAchat:
    today = today or date.today()
    a_acheter = [l for l in lignes if l.statut != "achete"]
    actifs = {mid for mid, m in magasins.items() if m.is_active}
    bas = await plus_bas_connus(db, [l.materiau_id for l in a_acheter], actifs)
    par_phase: dict[Optional[int], PhasePlan] = {}
    phases_map = {ph.id: ph for ph in phases}
    for ph in phases:
        j = (ph.start_date - today).days if ph.start_date else None
        par_phase[ph.id] = PhasePlan(
            phase_id=ph.id, name=ph.name, start_date=ph.start_date, jours_avant=j,
            acheter_avant=(ph.start_date - timedelta(days=3) if ph.start_date else None),
        )
    par_phase[None] = PhasePlan(phase_id=None, name="Sans phase", start_date=None, jours_avant=None, acheter_avant=None)
    plan = PlanAchat(
        phases=[], par_magasin=[], total_meilleur=0.0, nb_magasins=0, un_seul_magasin=None, economie_vs_un_seul=0.0,
        nb_lignes=len(a_acheter), nb_maintenant=0, nb_attendre=0, nb_sans_prix=0,
        total_maintenant=0.0, total_attendre=0.0, economie_rabais=0.0,
    )
    for l in a_acheter:
        key = l.phase_id if l.phase_id in par_phase else None
        rec = recommander(l, (l.materiau.offres if l.materiau else []), magasins, bas.get(l.materiau_id), phases_map.get(key), today)
        pp = par_phase[key]
        pp.lignes.append(rec)
        if rec.moment == "maintenant":
            pp.total_maintenant = round(pp.total_maintenant + (rec.total or 0), 2)
            plan.nb_maintenant += 1
        elif rec.moment == "attendre":
            pp.total_attendre = round(pp.total_attendre + (rec.total or 0), 2)
            plan.nb_attendre += 1
        else:
            pp.nb_sans_prix += 1
            plan.nb_sans_prix += 1
        plan.economie_rabais = round(plan.economie_rabais + rec.economie_rabais, 2)
    # Lignes d'une phase triées : à acheter maintenant d'abord, puis par montant.
    ordre_moment = {"maintenant": 0, "attendre": 1, "sans_prix": 2}
    for pp in par_phase.values():
        pp.lignes.sort(key=lambda r: (ordre_moment.get(r.moment, 9), -(r.total or 0), r.materiau_name))
    plan.phases = [par_phase[ph.id] for ph in phases if par_phase[ph.id].lignes] + (
        [par_phase[None]] if par_phase[None].lignes else []
    )
    plan.total_maintenant = round(sum(p.total_maintenant for p in plan.phases), 2)
    plan.total_attendre = round(sum(p.total_attendre for p in plan.phases), 2)
    plan.par_magasin, plan.total_meilleur, plan.un_seul_magasin, plan.economie_vs_un_seul = _plan_magasins(a_acheter, magasins)
    plan.nb_magasins = len(plan.par_magasin)
    return plan
