"""Listes d'achats de matériaux : prix courants, résumé budgétaire et
ALERTES DE RABAIS (étape 3 du catalogue, 2026-09-25).

- ``prix_courant(ligne)``     : offre pertinente d'une ligne (magasin
                                choisi, sinon meilleur prix) + meilleur
                                prix du moment, tous magasins.
- ``rabais_en_cours(db)``     : lignes « à acheter » des chantiers ouverts
                                dont un magasin est en rabais aujourd'hui.
- ``alerter_rabais(db)``      : notifie les gestionnaires (cloche + push)
                                UNE fois par rabais (clé magasin:prix:fin
                                mémorisée sur la ligne), regroupé par
                                projet. Appelé après chaque relevé
                                automatique (cron quotidien et bouton
                                « Actualiser les prix »).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.materiau import Magasin, Materiau, MateriauOffre
from app.models.project import Project, ProjectStatus
from app.models.projet_materiau import ProjetMateriau

log = logging.getLogger(__name__)

#: Statuts de projet pour lesquels la liste d'achats est « vivante ».
STATUTS_OUVERTS: tuple[str, ...] = (
    ProjectStatus.PLANNED.value,
    ProjectStatus.READY_TO_START.value,
    ProjectStatus.IN_PROGRESS.value,
    ProjectStatus.SUSPENDED.value,
    ProjectStatus.CORRECTION.value,
)


#: Un rabais SANS date de fin n'est cru que s'il a été observé
#: récemment (sinon une offre dont le relevé échoue resterait « en
#: rabais » pour toujours).
RABAIS_SANS_FIN_MAX_JOURS = 30


def offre_en_rabais(o: MateriauOffre, today: Optional[date] = None) -> bool:
    """Rabais AFFICHÉ et encore valide."""
    if not o.on_sale or o.unit_price is None:
        return False
    today = today or date.today()
    if o.sale_end is not None:
        return o.sale_end >= today
    vu = o.observed_at.date() if o.observed_at else None
    return vu is not None and (today - vu).days <= RABAIS_SANS_FIN_MAX_JOURS


@dataclass
class PrixCourant:
    #: Offre retenue : celle du magasin choisi si elle a un prix, sinon la
    #: moins chère.
    offre: Optional[MateriauOffre]
    #: Offre la moins chère tous magasins (prix connu).
    meilleure: Optional[MateriauOffre]
    #: Offre en rabais la plus intéressante (prix le plus bas), s'il y en a.
    rabais: Optional[MateriauOffre]


def _prix(o: MateriauOffre) -> float:
    return round(float(o.unit_price), 2)


def prix_courant(
    ligne: ProjetMateriau,
    offres: Iterable[MateriauOffre],
    magasins_actifs: Optional[set[int]] = None,
) -> PrixCourant:
    """``magasins_actifs`` : ids des magasins actifs ; les offres des
    autres sont ignorées (comme au catalogue et au relevé). Égalité de
    prix départagée par l'id du magasin (ordre stable → clé d'alerte
    stable). Un « rabais » n'est retenu que s'il ne coûte pas plus cher
    que l'offre retenue : un solde chez un magasin plus cher n'en est
    pas un pour nous."""
    avec_prix = [
        o for o in offres
        if o.unit_price is not None
        and (magasins_actifs is None or o.magasin_id in magasins_actifs)
    ]
    tri = lambda o: (_prix(o), o.magasin_id)  # noqa: E731
    meilleure = min(avec_prix, key=tri) if avec_prix else None
    choisie = None
    if ligne.magasin_id is not None:
        choisie = next((o for o in avec_prix if o.magasin_id == ligne.magasin_id), None)
    retenue = choisie or meilleure
    plafond = _prix(retenue) if retenue is not None else None
    en_rabais = [
        o for o in avec_prix
        if offre_en_rabais(o) and (plafond is None or _prix(o) <= plafond + 0.005)
    ]
    rabais = min(en_rabais, key=tri) if en_rabais else None
    return PrixCourant(offre=retenue, meilleure=meilleure, rabais=rabais)


def economie_rabais(ligne: ProjetMateriau, o: MateriauOffre) -> float:
    """Économie du rabais pour NOUS : par rapport au prix prévu de la
    ligne (ce qu'on comptait payer), sinon au prix régulier affiché."""
    qty = float(ligne.quantity or 0)
    prix = _prix(o)
    if ligne.prix_prevu is not None:
        ref = round(float(ligne.prix_prevu), 2)
    elif o.regular_price is not None:
        ref = round(float(o.regular_price), 2)
    else:
        return 0.0
    return round((ref - prix) * qty, 2) if ref > prix else 0.0


def cle_rabais(o: MateriauOffre) -> str:
    return f"{o.magasin_id}:{_prix(o):.2f}:{o.sale_end.isoformat() if o.sale_end else ''}"


async def _lignes_ouvertes(db, project_id: Optional[int] = None) -> list[ProjetMateriau]:
    stmt = (
        select(ProjetMateriau)
        .join(Project, Project.id == ProjetMateriau.project_id)
        .where(
            ProjetMateriau.statut == "a_acheter",
            Project.status.in_(STATUTS_OUVERTS),
        )
        .options(
            selectinload(ProjetMateriau.materiau).selectinload(Materiau.offres),
        )
        .order_by(ProjetMateriau.project_id.asc(), ProjetMateriau.position.asc(), ProjetMateriau.id.asc())
    )
    if project_id is not None:
        stmt = stmt.where(ProjetMateriau.project_id == project_id)
    return list((await db.execute(stmt)).scalars().unique().all())


async def rabais_en_cours(db, project_id: Optional[int] = None) -> list[dict]:
    """Lignes « à acheter » dont un magasin est en rabais aujourd'hui.
    Une entrée par ligne (le rabais le plus bas), triée par économie."""
    lignes = await _lignes_ouvertes(db, project_id)
    if not lignes:
        return []
    ids = {l.project_id for l in lignes}
    projets = {
        p.id: p for p in (await db.execute(select(Project).where(Project.id.in_(ids)))).scalars().all()
    }
    magasins = {m.id: m for m in (await db.execute(select(Magasin))).scalars().all()}
    actifs = {mid for mid, m in magasins.items() if m.is_active}
    out: list[dict] = []
    for l in lignes:
        pc = prix_courant(l, l.materiau.offres if l.materiau else [], actifs)
        o = pc.rabais
        if o is None:
            continue
        qty = float(l.quantity or 0)
        prix = _prix(o)
        reg = round(float(o.regular_price), 2) if o.regular_price is not None else None
        economie = economie_rabais(l, o)
        p = projets.get(l.project_id)
        out.append({
            "ligne_id": l.id,
            "project_id": l.project_id,
            "project_name": (p.name if p else f"Projet {l.project_id}"),
            "materiau_id": l.materiau_id,
            "materiau_name": (l.materiau.name if l.materiau else ""),
            "quantity": qty,
            "unit": l.unit,
            "magasin_id": o.magasin_id,
            "magasin_name": (magasins[o.magasin_id].name if o.magasin_id in magasins else ""),
            "price": prix,
            "regular_price": reg,
            "sale_end": (o.sale_end.isoformat() if o.sale_end else None),
            "prix_prevu": (float(l.prix_prevu) if l.prix_prevu is not None else None),
            "economie": economie,
            "url": o.url,
            "deja_signale": (l.derniere_alerte_cle == cle_rabais(o)),
        })
    out.sort(key=lambda r: (-r["economie"], r["project_name"], r["materiau_name"]))
    return out


async def alerter_rabais(db) -> int:
    """Une notification par projet regroupant les NOUVEAUX rabais (lignes
    dont la clé de rabais a changé). Retourne le nombre de lignes
    signalées. Flush ; l'appelant committe."""
    from app.services.notifications import notify_role

    rabais = await rabais_en_cours(db)
    nouveaux = [r for r in rabais if not r["deja_signale"]]
    if not nouveaux:
        return 0
    lignes = {l.id: l for l in await _lignes_ouvertes(db)}
    par_projet: dict[int, list[dict]] = {}
    for r in nouveaux:
        par_projet.setdefault(r["project_id"], []).append(r)
    signales = 0
    for project_id, items in par_projet.items():
        nom = items[0]["project_name"]
        total = round(sum(i["economie"] for i in items), 2)
        details = []
        for i in items[:6]:
            fin = f" jusqu'au {i['sale_end']}" if i["sale_end"] else ""
            reg = f" (rég. {i['regular_price']:.2f} $)" if i["regular_price"] is not None else ""
            details.append(f"• {i['materiau_name']} : {i['price']:.2f} ${reg} chez {i['magasin_name']}{fin}")
        if len(items) > 6:
            details.append(f"… et {len(items) - 6} autre(s)")
        titre = (
            f"Rabais matériaux — {nom} : {len(items)} article(s)"
            + (f", économie ≈ {total:.2f} $" if total > 0 else "")
        )
        # Un point de sauvegarde par projet : notification ET clés
        # d'idempotence partent (ou tombent) ensemble.
        try:
            async with db.begin_nested():
                await notify_role(
                    db,
                    min_role="manager",
                    kind="materiau_rabais",
                    title=titre,
                    body="\n".join(details),
                    href=f"/app/projets/{project_id}#materiaux",
                )
                for i in items:
                    l = lignes.get(i["ligne_id"])
                    if l is None:
                        continue
                    l.derniere_alerte_cle = f"{i['magasin_id']}:{i['price']:.2f}:{i['sale_end'] or ''}"
                    signales += 1
                await db.flush()
        except Exception:  # noqa: BLE001 — l'alerte ne doit jamais casser le relevé
            log.exception("Alerte rabais matériaux : notification échouée (projet %s)", project_id)
            continue
    log.info("Alertes rabais matériaux : %s ligne(s) signalée(s) sur %s projet(s)", signales, len(par_projet))
    return signales
