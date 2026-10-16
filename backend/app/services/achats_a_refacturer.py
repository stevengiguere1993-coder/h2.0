"""Achats à refacturer — filet anti-perte (Steven 2026-10-16).

« J'ai besoin d'un endroit dans Kratos qui me mentionne quand un reçu
d'achat est ajouté après la facture finale dans un projet, quand un BT
est fermé et que l'achat n'a pas été refacturé dans la facture du BT.
On doit s'assurer que tout est refacturé ou qu'on autorise qu'il ne le
soit pas. »

Deux cas détectés (lecture seule, rien n'est modifié ici) :

1. ``apres_facture_finale`` — un achat refacturable (``is_billable``),
   pas encore refacturé (``invoiced_at`` NULL), créé APRÈS l'émission de
   la première facture finale ÉMISE (ni brouillon ni annulée) de son
   projet. Seuls les reçus arrivés après coup sont signalés : ce qui
   précédait la facture finale a été vu au moment de la monter.
2. ``bt_ferme`` — un achat du projet lié d'un bon de travail FERMÉ
   (statut « facturé ») qui n'a pas été refacturé. Même règle que
   l'import d'un bon : tout achat d'un BT se refacture, sauf ceux
   marqués « non refacturable » à la main.

Un achat sort de la liste dès qu'il est versé sur une facture
(``invoiced_at`` posé) ou qu'un humain autorise explicitement de ne pas
le refacturer (``refacturation_dispense_at`` + is_billable=False).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.achat import Achat, AchatStatus
from app.models.bon_travail import BonTravail, BonTravailStatus
from app.models.facture import Facture, FactureStatus
from app.models.project import Project
from app.models.project_subcontractor_contract import (
    ProjectSubcontractorContract,
)

MOTIF_APRES_FACTURE_FINALE = "apres_facture_finale"
MOTIF_BT_FERME = "bt_ferme"

#: Statuts de facture qui ne comptent pas comme « émise ».
_FACTURE_NON_EMISE = (FactureStatus.DRAFT.value, FactureStatus.VOID.value)


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite rend des datetimes naïfs : on les lit en UTC pour comparer."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _non_refacture():
    """Achat actif pas encore versé sur une facture ni dispensé."""
    return and_(
        Achat.invoiced_at.is_(None),
        Achat.refacturation_dispense_at.is_(None),
        or_(Achat.status.is_(None), Achat.status != AchatStatus.CANCELLED.value),
    )


async def _finales_par_projet(db: AsyncSession) -> dict[int, dict[str, Any]]:
    """Première facture finale ÉMISE de chaque projet → sa date de
    référence (émission, sinon création) et sa référence."""
    rows = (
        await db.execute(
            select(
                Facture.id,
                Facture.project_id,
                Facture.reference,
                Facture.issued_at,
                Facture.created_at,
            ).where(
                Facture.is_final.is_(True),
                Facture.project_id.is_not(None),
                Facture.status.notin_(_FACTURE_NON_EMISE),
            )
        )
    ).all()
    out: dict[int, dict[str, Any]] = {}
    for fid, pid, ref, issued, created in rows:
        quand = _utc(issued) or _utc(created)
        if quand is None:
            continue
        cur = out.get(int(pid))
        if cur is None or quand < cur["date"]:
            out[int(pid)] = {"facture_id": int(fid), "reference": ref, "date": quand}
    return out


async def detecter(db: AsyncSession) -> list[dict[str, Any]]:
    """Liste des achats à refacturer (les deux cas), du plus récent au
    plus ancien. Un achat n'apparaît qu'une fois (le cas BT prime)."""
    lignes: dict[int, dict[str, Any]] = {}

    # ── Cas 2 : bons de travail fermés ────────────────────────────────
    bons = (
        await db.execute(
            select(BonTravail, Project)
            .join(Project, Project.id == BonTravail.project_id)
            .where(
                BonTravail.status == BonTravailStatus.FACTURE.value,
                Project.kind == "bon_travail",
            )
        )
    ).all()
    bon_par_projet = {int(p.id): (b, p) for b, p in bons}
    if bon_par_projet:
        achats_bt = (
            await db.execute(
                select(Achat).where(
                    Achat.project_id.in_(list(bon_par_projet)),
                    _non_refacture(),
                    # Exclus à la main = choix humain déjà fait.
                    not_(
                        and_(
                            Achat.is_billable.is_(False),
                            Achat.billable_manual.is_(True),
                        )
                    ),
                )
            )
        ).scalars().all()
        fac_ids = {int(b.facture_id) for b, _ in bons if b.facture_id}
        fac_refs: dict[int, str] = {}
        if fac_ids:
            fac_refs = {
                int(i): r
                for i, r in (
                    await db.execute(
                        select(Facture.id, Facture.reference).where(
                            Facture.id.in_(fac_ids)
                        )
                    )
                ).all()
            }
        for a in achats_bt:
            bon, proj = bon_par_projet[int(a.project_id)]
            lignes[int(a.id)] = {
                "achat": a,
                "motif": MOTIF_BT_FERME,
                "project": proj,
                "bon_id": int(bon.id),
                "bon_reference": bon.reference,
                "bon_titre": bon.title,
                "facture_id": int(bon.facture_id) if bon.facture_id else None,
                "facture_reference": fac_refs.get(int(bon.facture_id or 0)),
                "facture_date": None,
            }

    # ── Cas 1 : reçus ajoutés après la facture finale ─────────────────
    finales = await _finales_par_projet(db)
    if finales:
        achats_fin = (
            await db.execute(
                select(Achat).where(
                    Achat.project_id.in_(list(finales)),
                    Achat.is_billable.is_(True),
                    _non_refacture(),
                )
            )
        ).scalars().all()
        projets: dict[int, Project] = {}
        pids = {int(a.project_id) for a in achats_fin if int(a.id) not in lignes}
        if pids:
            projets = {
                int(p.id): p
                for p in (
                    await db.execute(select(Project).where(Project.id.in_(pids)))
                ).scalars().all()
            }
        for a in achats_fin:
            if int(a.id) in lignes:
                continue
            fin = finales[int(a.project_id)]
            cree = _utc(a.created_at)
            if cree is None or cree <= fin["date"]:
                continue
            lignes[int(a.id)] = {
                "achat": a,
                "motif": MOTIF_APRES_FACTURE_FINALE,
                "project": projets.get(int(a.project_id)),
                "bon_id": None,
                "bon_reference": None,
                "bon_titre": None,
                "facture_id": fin["facture_id"],
                "facture_reference": fin["reference"],
                "facture_date": fin["date"],
            }

    # Montant refacturable estimé (même calcul que l'import sur facture).
    from app.api.v1.endpoints.facture_import import _compute_billed_amount

    paires = {
        (int(l["achat"].project_id), int(l["achat"].sous_traitant_id))
        for l in lignes.values()
        if l["achat"].kind == "sub_invoice" and l["achat"].sous_traitant_id
    }
    contrats: dict[tuple[int, int], ProjectSubcontractorContract] = {}
    if paires:
        rows = (
            await db.execute(
                select(ProjectSubcontractorContract).where(
                    ProjectSubcontractorContract.project_id.in_(
                        {p for p, _ in paires}
                    )
                )
            )
        ).scalars().all()
        contrats = {
            (int(c.project_id), int(c.sous_traitant_id)): c
            for c in rows
            if c.sous_traitant_id is not None
        }
    for l in lignes.values():
        a = l["achat"]
        par_st = {}
        if a.sous_traitant_id:
            c = contrats.get((int(a.project_id), int(a.sous_traitant_id)))
            if c is not None:
                par_st = {int(a.sous_traitant_id): c}
        l["montant_refacturable"], l["regle"] = _compute_billed_amount(a, {}, par_st)

    return sorted(
        lignes.values(),
        key=lambda l: _utc(l["achat"].created_at) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


async def compter(db: AsyncSession) -> int:
    return len(await detecter(db))
