"""Vue d'ensemble des dépenses de la construction (bug 14, Steven
2026-10-03 : « vue d'ensemble des dépenses construction général et
calculer coût à l'heure vs entrée de fonds »).

Pour une période, mois par mois, avec les données de Kratos :

- HEURES : punchs fermés des employés (heures payées, dîner déjà retiré),
  comptés au jour de leur début, heure de Montréal ;
- MAIN-D'ŒUVRE : heures × coût horaire réel daté de l'employé (taux +
  CNESST + CCQ selon le régime du punch), le même calcul que l'onglet
  Finances d'un projet ;
- ACHATS hors taxes : matériaux et achats reliés à un projet ou à un
  client, factures de sous-traitants, shop et frais généraux (achats
  reliés à aucun projet ni client). Datés de la facture du fournisseur,
  sinon de leur réception. Les achats annulés sont exclus, comme les
  sorties d'inventaire interne (le stock a été payé à son achat). Comme
  sur la fiche projet, le hors taxes = total payé ÷ 1,14975 (taxes
  récupérables) ;
- ENTRÉES DE FONDS : paiements reçus des clients sur les factures, à leur
  date ; la part hors taxes suit le ratio sous-total ÷ total de la facture.

Coût à l'heure = (main-d'œuvre + achats) ÷ heures ; entrées à l'heure =
entrées hors taxes ÷ heures ; écart à l'heure = entrées − coût. Les taxes
sont exclues des deux côtés : elles reviennent au gouvernement.

``vue_quickbooks`` ajoute ce que Kratos ne voit pas (paie au grand livre,
loyer, assurances, véhicules…) : le P&L QuickBooks de la construction, en
lecture seule, ramené aux mêmes heures.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.taxes import ht_from_ttc
from app.models.achat import KIND_INVENTAIRE, Achat, AchatStatus
from app.models.employe import Employe
from app.models.facture import Facture
from app.models.payment import Payment
from app.models.punch import Punch
from app.services.punch_diner import aujourd_hui_local, bornes_jour_utc, jour_local

log = logging.getLogger(__name__)

#: Connexion QuickBooks de la construction (connexion historique).
SCOPE_QBO = "construction"

#: Catégories de dépenses, dans l'ordre d'affichage.
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("main_oeuvre", "Main-d'œuvre"),
    ("materiaux", "Matériaux et achats des projets"),
    ("sous_traitants", "Sous-traitants"),
    ("frais_generaux", "Shop et frais généraux"),
)

#: Durée maximale d'une période (≈ 3 ans) : borne les requêtes.
MAX_JOURS = 1100

#: Postes QuickBooks affichés (les plus gros d'abord).
MAX_POSTES_QBO = 12


class PeriodeInvalide(ValueError):
    """Période refusée (message en français, rendu en 422)."""


def periode(debut: Optional[date], fin: Optional[date]) -> tuple[date, date]:
    """Période demandée, par défaut les 12 derniers mois (mois courant
    compris, jusqu'à aujourd'hui)."""
    if fin is None:
        fin = aujourd_hui_local()
    if debut is None:
        mois = fin.year * 12 + fin.month - 1 - 11
        debut = date(mois // 12, mois % 12 + 1, 1)
    if debut > fin:
        raise PeriodeInvalide("La date de début doit précéder la date de fin.")
    if (fin - debut).days > MAX_JOURS:
        raise PeriodeInvalide("La période ne peut pas dépasser trois ans.")
    return debut, fin


def mois_de_la_periode(debut: date, fin: date) -> list[tuple[str, date, date]]:
    """Mois couverts : (clé « AAAA-MM », premier jour, dernier jour), bornés
    à la période (un mois entamé n'en couvre que la partie demandée)."""
    out: list[tuple[str, date, date]] = []
    d = debut.replace(day=1)
    while d <= fin:
        suivant = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        out.append(
            (f"{d.year:04d}-{d.month:02d}", max(d, debut), min(suivant - timedelta(days=1), fin))
        )
        d = suivant
    return out


def categorie_achat(
    kind: Optional[str],
    sous_traitant_id: Optional[int],
    project_id: Optional[int],
    client_id: Optional[int],
) -> str:
    """Facture de sous-traitant → sous_traitants ; achat relié à aucun
    projet ni client (atelier, camion, outillage) → frais_generaux ; le
    reste → materiaux."""
    if (kind or "") == "sub_invoice" or sous_traitant_id is not None:
        return "sous_traitants"
    if project_id is None and client_id is None:
        return "frais_generaux"
    return "materiaux"


def part_hors_taxes(montant: float, sous_total: Any, total: Any) -> float:
    """Part hors taxes d'un paiement : au prorata de sa facture (sous-total
    ÷ total). Facture sans sous-total (import QuickBooks) : taxes du Québec
    retirées."""
    st = float(sous_total) if sous_total is not None else None
    tt = float(total) if total is not None else None
    if st is not None and tt is not None and tt > 0 and 0 <= st <= tt:
        return montant * st / tt
    return ht_from_ttc(montant)


def par_heure(montant: float, heures: float) -> Optional[float]:
    return round(montant / heures, 2) if heures > 0 else None


def _ecart(entrees_h: Optional[float], cout_h: Optional[float]) -> Optional[float]:
    if entrees_h is None or cout_h is None:
        return None
    return round(entrees_h - cout_h, 2)


async def _punchs(db: AsyncSession, debut: date, fin: date) -> list[Any]:
    """Punchs fermés de la période (jour de début, heure de Montréal)."""
    a = bornes_jour_utc(debut)[0]
    b = bornes_jour_utc(fin)[1]
    return list(
        (
            await db.execute(
                select(
                    Punch.employe_id, Punch.started_at, Punch.hours, Punch.regime
                ).where(
                    Punch.ended_at.is_not(None),
                    Punch.hours.is_not(None),
                    Punch.started_at >= a,
                    Punch.started_at < b,
                )
            )
        ).all()
    )


async def heures_par_mois(db: AsyncSession, debut: date, fin: date) -> dict[str, float]:
    """Heures travaillées par mois « AAAA-MM » (punchs fermés)."""
    out = {cle: 0.0 for cle, _, _ in mois_de_la_periode(debut, fin)}
    for p in await _punchs(db, debut, fin):
        cle = jour_local(p.started_at).strftime("%Y-%m")
        if cle in out:
            out[cle] += float(p.hours or 0)
    return out


async def vue_ensemble(db: AsyncSession, debut: date, fin: date) -> dict[str, Any]:
    """Dépenses, heures, coût à l'heure et entrées de fonds de la période,
    au total et mois par mois (voir le docstring du module)."""
    from app.services.cnesst import charger_bareme_cnesst
    from app.services.employe_rates import load_rate_periods, resolve_real_cost

    mois = mois_de_la_periode(debut, fin)
    seaux: dict[str, dict[str, float]] = {
        cle: {
            "heures": 0.0,
            "main_oeuvre": 0.0,
            "materiaux": 0.0,
            "sous_traitants": 0.0,
            "frais_generaux": 0.0,
            "achats_ttc": 0.0,
            "entrees_ttc": 0.0,
            "entrees_ht": 0.0,
        }
        for cle, _, _ in mois
    }

    def seau(jour: Optional[date]) -> Optional[dict[str, float]]:
        if jour is None or not (debut <= jour <= fin):
            return None
        return seaux.get(jour.strftime("%Y-%m"))

    # ── Heures et main-d'œuvre (coût réel daté, comme la fiche projet) ──
    punchs = await _punchs(db, debut, fin)
    emp_ids = {p.employe_id for p in punchs if p.employe_id is not None}
    employes: dict[int, Employe] = {}
    if emp_ids:
        employes = {
            e.id: e
            for e in (
                await db.execute(select(Employe).where(Employe.id.in_(emp_ids)))
            ).scalars().all()
        }
    taux_moyen = float(
        (await db.execute(select(func.coalesce(func.avg(Employe.hourly_rate), 35.0)))).scalar_one()
        or 35.0
    )
    periodes = await load_rate_periods(db, emp_ids)
    bareme = await charger_bareme_cnesst(db)
    avec_heures: set[int] = set()
    for p in punchs:
        jour = jour_local(p.started_at)
        s = seau(jour)
        if s is None:
            continue
        heures = float(p.hours or 0)
        cout = resolve_real_cost(
            periodes.get(p.employe_id or -1, []),
            jour,
            employes.get(p.employe_id),
            taux_moyen,
            regime=p.regime,
            cnesst=bareme,
        )
        s["heures"] += heures
        s["main_oeuvre"] += heures * cout
        if heures > 0 and p.employe_id is not None:
            avec_heures.add(p.employe_id)

    # ── Achats hors taxes ───────────────────────────────────────────────
    a = bornes_jour_utc(debut)[0]
    b = bornes_jour_utc(fin)[1]
    achats = (
        await db.execute(
            select(
                Achat.kind,
                Achat.sous_traitant_id,
                Achat.project_id,
                Achat.client_id,
                Achat.amount,
                Achat.amount_taxes,
                Achat.invoice_date,
                Achat.received_at,
                Achat.created_at,
            ).where(
                Achat.status != AchatStatus.CANCELLED.value,
                Achat.kind != KIND_INVENTAIRE,
                or_(
                    and_(
                        Achat.invoice_date.is_not(None),
                        Achat.invoice_date >= debut,
                        Achat.invoice_date <= fin,
                    ),
                    and_(
                        Achat.invoice_date.is_(None),
                        Achat.received_at.is_not(None),
                        Achat.received_at >= a,
                        Achat.received_at < b,
                    ),
                    and_(
                        Achat.invoice_date.is_(None),
                        Achat.received_at.is_(None),
                        Achat.created_at >= a,
                        Achat.created_at < b,
                    ),
                ),
            )
        )
    ).all()
    for r in achats:
        jour = r.invoice_date or (
            jour_local(r.received_at) if r.received_at is not None else None
        ) or (jour_local(r.created_at) if r.created_at is not None else None)
        s = seau(jour)
        if s is None:
            continue
        ttc = float(r.amount or 0) + float(r.amount_taxes or 0)
        cat = categorie_achat(r.kind, r.sous_traitant_id, r.project_id, r.client_id)
        s[cat] += ht_from_ttc(ttc)
        s["achats_ttc"] += ttc

    # ── Entrées de fonds : paiements reçus des clients ─────────────────
    paiements = (
        await db.execute(
            select(Payment.amount, Payment.paid_at, Facture.subtotal, Facture.total)
            .join(Facture, Facture.id == Payment.facture_id)
            .where(Payment.paid_at >= debut, Payment.paid_at <= fin)
        )
    ).all()
    nb_paiements = 0
    for r in paiements:
        s = seau(r.paid_at)
        if s is None:
            continue
        montant = float(r.amount or 0)
        s["entrees_ttc"] += montant
        s["entrees_ht"] += part_hors_taxes(montant, r.subtotal, r.total)
        nb_paiements += 1

    # ── Assemblage ─────────────────────────────────────────────────────
    def ligne(v: dict[str, float]) -> dict[str, Any]:
        achats_ht = v["materiaux"] + v["sous_traitants"] + v["frais_generaux"]
        depenses = v["main_oeuvre"] + achats_ht
        cout_h = par_heure(depenses, v["heures"])
        entrees_h = par_heure(v["entrees_ht"], v["heures"])
        return {
            "heures": round(v["heures"], 2),
            "main_oeuvre": round(v["main_oeuvre"], 2),
            "materiaux": round(v["materiaux"], 2),
            "sous_traitants": round(v["sous_traitants"], 2),
            "frais_generaux": round(v["frais_generaux"], 2),
            "achats": round(achats_ht, 2),
            "achats_ttc": round(v["achats_ttc"], 2),
            "depenses": round(depenses, 2),
            "cout_heure": cout_h,
            "cout_main_oeuvre_heure": par_heure(v["main_oeuvre"], v["heures"]),
            "entrees_ttc": round(v["entrees_ttc"], 2),
            "entrees_ht": round(v["entrees_ht"], 2),
            "entrees_heure": entrees_h,
            "ecart_heure": _ecart(entrees_h, cout_h),
            "resultat": round(v["entrees_ht"] - depenses, 2),
        }

    total = {k: sum(v[k] for v in seaux.values()) for k in next(iter(seaux.values()))}
    out = ligne(total)
    depenses = out["depenses"]
    out.update(
        {
            "debut": debut,
            "fin": fin,
            "employes": len(avec_heures),
            "nb_paiements": nb_paiements,
            "categories": [
                {
                    "cle": cle,
                    "libelle": libelle,
                    "montant": out[cle],
                    "par_heure": par_heure(out[cle], out["heures"]),
                    "part_pct": round(out[cle] / depenses * 100, 1) if depenses > 0 else 0.0,
                }
                for cle, libelle in CATEGORIES
            ],
            "mois": [
                {"mois": cle, "debut": d, "fin": f, **ligne(seaux[cle])}
                for cle, d, f in mois
            ],
        }
    )
    return out


async def vue_quickbooks(db: AsyncSession, debut: date, fin: date) -> dict[str, Any]:
    """Toutes les dépenses comptabilisées dans le QuickBooks de la
    construction (P&L, comptabilité d'exercice) et leur coût à l'heure
    sur les heures punchées dans Kratos. Lecture seule ; QuickBooks non
    connecté ou en erreur → ``connecte`` / ``erreur``, jamais d'exception."""
    from app.integrations.quickbooks import QuickBooksReconnexionRequise
    from app.services import qbo_optimisation

    heures_mois = await heures_par_mois(db, debut, fin)
    heures = sum(heures_mois.values())
    out: dict[str, Any] = {
        "debut": debut,
        "fin": fin,
        "connecte": True,
        "erreur": None,
        "heures": round(heures, 2),
        "depenses": 0.0,
        "revenus": 0.0,
        "cout_heure": None,
        "revenus_heure": None,
        "postes": [],
        "mois": [],
    }
    try:
        cf = await qbo_optimisation.cashflow_mensuel(
            SCOPE_QBO, debut.isoformat(), fin.isoformat()
        )
    except (RuntimeError, QuickBooksReconnexionRequise):
        out["connecte"] = False
        out["erreur"] = (
            "QuickBooks n'est pas connecté pour la construction "
            "(Paramètres → Intégrations)."
        )
        return out
    except Exception as exc:  # noqa: BLE001 — la page reste lisible
        log.warning("dépenses construction — P&L QuickBooks illisible : %s", exc)
        out["erreur"] = f"QuickBooks n'a pas répondu : {exc}"
        return out

    tot = cf.get("total") or {}
    depenses = float(tot.get("depenses") or 0)
    revenus = float(tot.get("revenus") or 0)
    out.update(
        {
            "depenses": round(depenses, 2),
            "revenus": round(revenus, 2),
            "cout_heure": par_heure(depenses, heures),
            "revenus_heure": par_heure(revenus, heures),
            "postes": [
                {"nom": d.get("nom") or "—", "montant": round(float(d.get("montant") or 0), 2)}
                for d in sorted(
                    (d for d in tot.get("details") or [] if d.get("type") == "depense"),
                    key=lambda d: -float(d.get("montant") or 0),
                )[:MAX_POSTES_QBO]
            ],
        }
    )
    for m in cf.get("mois") or []:
        cle = (m.get("debut") or "")[:7] or None
        h = heures_mois.get(cle, 0.0) if cle else 0.0
        dep = float(m.get("depenses") or 0)
        out["mois"].append(
            {
                "mois": cle,
                "libelle": m.get("mois") or cle or "",
                "depenses": round(dep, 2),
                "revenus": round(float(m.get("revenus") or 0), 2),
                "heures": round(h, 2),
                "cout_heure": par_heure(dep, h),
            }
        )
    return out
