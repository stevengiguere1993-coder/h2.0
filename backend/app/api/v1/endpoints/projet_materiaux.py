"""Liste d'achats de MATÉRIAUX d'un projet (étape 3 du catalogue,
2026-09-25).

    GET    /projects/{id}/materiaux              lignes + prix courants +
                                                 résumé (prévu, meilleur
                                                 prix du jour, acheté,
                                                 coûtant soumission,
                                                 budgets de phases)
    POST   /projects/{id}/materiaux              ajouter une ligne
                                                 (matériau existant ou
                                                 nouveau)
    PATCH  /projects/{id}/materiaux/{ligne_id}   quantité, phase, magasin,
                                                 prix prévu, statut
                                                 (acheté + prix payé)
    DELETE /projects/{id}/materiaux/{ligne_id}
    POST   /projects/{id}/materiaux/creer-po     bon de commande (PO) pour
                                                 un magasin à partir des
                                                 lignes à acheter
    GET    /materiaux/rabais                     rabais du jour sur les
                                                 lignes à acheter de tous
                                                 les chantiers ouverts
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.core.permissions import visible_project_ids
from app.models.achat import Achat
from app.models.employe import Employe
from app.models.fournisseur import Fournisseur
from app.models.materiau import Magasin, Materiau, MateriauOffre
from app.models.project import Project
from app.models.project_phase import ProjectPhase
from app.models.projet_materiau import ProjetMateriau
from app.models.purchase_order import PurchaseOrder, PurchaseOrderStatus
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.soumission_item import SoumissionItem
from app.services.materiaux_alertes import (
    offre_en_rabais,
    prix_courant,
    rabais_en_cours,
)
from app.services.materiaux_import import categorie_standard, categoriser_par_nom, norm_key
from app.services.numbering import next_po_number

router = APIRouter(prefix="/projects", tags=["projet-materiaux"])
rabais_router = APIRouter(prefix="/materiaux", tags=["projet-materiaux"])


# ───────────────────────────── Schémas ─────────────────────────────

class OffreCourante(BaseModel):
    magasin_id: int
    magasin_name: str
    unit_price: float
    regular_price: Optional[float] = None
    on_sale: bool = False
    sale_end: Optional[date] = None
    url: Optional[str] = None
    observed_at: Optional[datetime] = None


class LigneRead(BaseModel):
    id: int
    project_id: int
    phase_id: Optional[int] = None
    materiau_id: int
    materiau_name: str
    categorie: Optional[str] = None
    quantity: float
    unit: Optional[str] = None
    magasin_id: Optional[int] = None
    magasin_name: Optional[str] = None
    prix_prevu: Optional[float] = None
    total_prevu: Optional[float] = None
    #: Offre retenue aujourd'hui (magasin choisi, sinon la moins chère).
    courant: Optional[OffreCourante] = None
    total_courant: Optional[float] = None
    #: Meilleur prix du jour tous magasins.
    meilleur: Optional[OffreCourante] = None
    #: Rabais du jour le plus bas (s'il y en a un).
    rabais: Optional[OffreCourante] = None
    statut: str
    prix_paye: Optional[float] = None
    total_paye: Optional[float] = None
    achete_le: Optional[date] = None
    purchase_order_id: Optional[int] = None
    achat_id: Optional[int] = None
    notes: Optional[str] = None
    position: int = 0


class PhaseResume(BaseModel):
    phase_id: Optional[int] = None
    name: str
    budget: Optional[float] = None
    prevu: float = 0
    courant: float = 0
    paye: float = 0
    nb_lignes: int = 0


class ListeResume(BaseModel):
    nb_lignes: int = 0
    nb_a_acheter: int = 0
    nb_achetes: int = 0
    nb_rabais: int = 0
    #: Σ quantité × prix prévu (toutes lignes).
    total_prevu: float = 0
    #: Σ quantité × prix courant (lignes à acheter) + Σ payé (achetées).
    total_courant: float = 0
    #: Σ quantité × prix payé (lignes achetées).
    total_paye: float = 0
    #: Σ quantité × meilleur prix du jour (lignes à acheter).
    total_meilleur: float = 0
    #: Économie si on achète tout au meilleur prix vs le prévu.
    economie_possible: float = 0
    #: Coûtant matériaux de la soumission liée (Σ qté × coût matériau).
    coutant_materiaux_soumission: Optional[float] = None
    #: Σ des budgets de phases renseignés.
    budget_phases: Optional[float] = None
    par_phase: List[PhaseResume] = []


class ListeRead(BaseModel):
    lignes: List[LigneRead]
    phases: List[PhaseResume]
    resume: ListeResume


class LigneCreate(BaseModel):
    materiau_id: Optional[int] = None
    #: Créer le matériau au vol s'il n'existe pas dans le catalogue.
    new_name: Optional[str] = Field(default=None, max_length=255)
    new_categorie: Optional[str] = Field(default=None, max_length=80)
    phase_id: Optional[int] = None
    quantity: float = Field(default=1, gt=0)
    unit: Optional[str] = Field(default=None, max_length=32)
    magasin_id: Optional[int] = None
    prix_prevu: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = Field(default=None, max_length=255)


class LigneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phase_id: Optional[int] = None
    quantity: Optional[float] = Field(default=None, gt=0)
    unit: Optional[str] = Field(default=None, max_length=32)
    magasin_id: Optional[int] = None
    prix_prevu: Optional[float] = Field(default=None, ge=0)
    statut: Optional[str] = Field(default=None, pattern="^(a_acheter|achete)$")
    prix_paye: Optional[float] = Field(default=None, ge=0)
    achete_le: Optional[date] = None
    achat_id: Optional[int] = None
    notes: Optional[str] = Field(default=None, max_length=255)
    position: Optional[int] = Field(default=None, ge=0)
    #: Champs à remettre à NULL (phase_id, magasin_id, prix_prevu…).
    clear: List[str] = Field(default_factory=list)


class CreerPoBody(BaseModel):
    magasin_id: int
    #: Sous-ensemble de lignes ; vide = toutes les lignes « à acheter »
    #: dont le magasin choisi est celui-ci (ou sans magasin choisi et
    #: dont ce magasin est le moins cher).
    ligne_ids: List[int] = Field(default_factory=list)
    assigned_employe_id: Optional[int] = None
    payment_method: Optional[str] = Field(default=None, max_length=32)


class CreerPoResult(BaseModel):
    purchase_order_id: int
    reference: str
    nb_lignes: int
    total: float


class RabaisRead(BaseModel):
    ligne_id: int
    project_id: int
    project_name: str
    materiau_id: int
    materiau_name: str
    quantity: float
    unit: Optional[str] = None
    magasin_id: int
    magasin_name: str
    price: float
    regular_price: Optional[float] = None
    sale_end: Optional[str] = None
    prix_prevu: Optional[float] = None
    economie: float = 0
    url: Optional[str] = None
    deja_signale: bool = False


# ───────────────────────────── Helpers ─────────────────────────────

async def _projet_visible(db, project_id: int, user) -> Project:
    visible = await visible_project_ids(db, user)
    if visible is not None and project_id not in visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


def _offre_courante(o: Optional[MateriauOffre], magasins: dict[int, Magasin]) -> Optional[OffreCourante]:
    if o is None or o.unit_price is None:
        return None
    m = magasins.get(o.magasin_id)
    return OffreCourante(
        magasin_id=o.magasin_id,
        magasin_name=(m.name if m else f"#{o.magasin_id}"),
        unit_price=float(o.unit_price),
        regular_price=(float(o.regular_price) if o.regular_price is not None else None),
        on_sale=offre_en_rabais(o),
        sale_end=o.sale_end,
        url=o.url,
        observed_at=o.observed_at,
    )


def _actifs(magasins: dict[int, Magasin]) -> set[int]:
    return {mid for mid, m in magasins.items() if m.is_active}


def _ligne_read(l: ProjetMateriau, magasins: dict[int, Magasin]) -> LigneRead:
    offres = l.materiau.offres if l.materiau else []
    pc = prix_courant(l, offres, _actifs(magasins))
    qty = float(l.quantity or 0)
    prevu = float(l.prix_prevu) if l.prix_prevu is not None else None
    paye = float(l.prix_paye) if l.prix_paye is not None else None
    courant = _offre_courante(pc.offre, magasins)
    mag = magasins.get(l.magasin_id) if l.magasin_id else None
    return LigneRead(
        id=l.id,
        project_id=l.project_id,
        phase_id=l.phase_id,
        materiau_id=l.materiau_id,
        materiau_name=(l.materiau.name if l.materiau else ""),
        categorie=(l.materiau.categorie if l.materiau else None),
        quantity=qty,
        unit=l.unit,
        magasin_id=l.magasin_id,
        magasin_name=(mag.name if mag else None),
        prix_prevu=prevu,
        total_prevu=(round(qty * prevu, 2) if prevu is not None else None),
        courant=courant,
        total_courant=(round(qty * courant.unit_price, 2) if courant else None),
        meilleur=_offre_courante(pc.meilleure, magasins),
        rabais=_offre_courante(pc.rabais, magasins),
        statut=l.statut,
        prix_paye=paye,
        total_paye=(round(qty * paye, 2) if paye is not None else None),
        achete_le=l.achete_le,
        purchase_order_id=l.purchase_order_id,
        achat_id=l.achat_id,
        notes=l.notes,
        position=l.position,
    )


async def _magasins_map(db) -> dict[int, Magasin]:
    return {m.id: m for m in (await db.execute(select(Magasin))).scalars().all()}


async def _lignes(db, project_id: int) -> list[ProjetMateriau]:
    stmt = (
        select(ProjetMateriau)
        .where(ProjetMateriau.project_id == project_id)
        .options(selectinload(ProjetMateriau.materiau).selectinload(Materiau.offres))
        .order_by(ProjetMateriau.position.asc(), ProjetMateriau.id.asc())
    )
    return list((await db.execute(stmt)).scalars().unique().all())


async def _ligne(db, project_id: int, ligne_id: int) -> ProjetMateriau:
    stmt = (
        select(ProjetMateriau)
        .where(ProjetMateriau.id == ligne_id, ProjetMateriau.project_id == project_id)
        .options(selectinload(ProjetMateriau.materiau).selectinload(Materiau.offres))
    )
    l = (await db.execute(stmt)).scalar_one_or_none()
    if l is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ligne introuvable")
    return l


async def _coutant_soumission(db, project: Project) -> Optional[float]:
    if not project.soumission_id:
        return None
    total = (
        await db.execute(
            select(func.coalesce(func.sum(SoumissionItem.quantity * SoumissionItem.cost_material_per_unit), 0)).where(
                SoumissionItem.soumission_id == project.soumission_id,
                SoumissionItem.retire_par_avenant_id.is_(None),
                SoumissionItem.cost_material_per_unit.is_not(None),
            )
        )
    ).scalar_one()
    return round(float(total or 0), 2)


async def _phases(db, project_id: int) -> list[ProjectPhase]:
    return list((await db.execute(
        select(ProjectPhase).where(ProjectPhase.project_id == project_id)
        .order_by(ProjectPhase.position.asc(), ProjectPhase.id.asc())
    )).scalars().all())


def _resume(lignes: list[LigneRead], phases: list[ProjectPhase], coutant: Optional[float]) -> tuple[ListeResume, list[PhaseResume]]:
    par_phase: dict[Optional[int], PhaseResume] = {}
    for ph in phases:
        par_phase[ph.id] = PhaseResume(
            phase_id=ph.id, name=ph.name,
            budget=(float(ph.budget) if ph.budget is not None else None),
        )
    par_phase[None] = PhaseResume(phase_id=None, name="Sans phase")
    r = ListeResume(nb_lignes=len(lignes))
    for l in lignes:
        key = l.phase_id if l.phase_id in par_phase else None
        pr = par_phase[key]
        pr.nb_lignes += 1
        if l.total_prevu is not None:
            r.total_prevu += l.total_prevu
            pr.prevu += l.total_prevu
        if l.statut == "achete":
            r.nb_achetes += 1
            paye = l.total_paye if l.total_paye is not None else (l.total_prevu or 0)
            r.total_paye += paye
            r.total_courant += paye
            pr.paye += paye
            pr.courant += paye
        else:
            r.nb_a_acheter += 1
            if l.rabais is not None:
                r.nb_rabais += 1
            cur = l.total_courant if l.total_courant is not None else (l.total_prevu or 0)
            r.total_courant += cur
            pr.courant += cur
            if l.meilleur is not None:
                tm = round(l.quantity * l.meilleur.unit_price, 2)
                r.total_meilleur += tm
                if l.total_prevu is not None and l.total_prevu > tm:
                    r.economie_possible += round(l.total_prevu - tm, 2)
            elif l.total_prevu is not None:
                r.total_meilleur += l.total_prevu
    for k in ("total_prevu", "total_courant", "total_paye", "total_meilleur", "economie_possible"):
        setattr(r, k, round(getattr(r, k), 2))
    for pr in par_phase.values():
        pr.prevu, pr.courant, pr.paye = round(pr.prevu, 2), round(pr.courant, 2), round(pr.paye, 2)
    r.coutant_materiaux_soumission = coutant
    budgets = [float(ph.budget) for ph in phases if ph.budget is not None]
    r.budget_phases = round(sum(budgets), 2) if budgets else None
    liste = [par_phase[ph.id] for ph in phases]
    if par_phase[None].nb_lignes:
        liste.append(par_phase[None])
    r.par_phase = liste
    return r, [par_phase[ph.id] for ph in phases]


async def _liste_read(db, project: Project) -> ListeRead:
    magasins = await _magasins_map(db)
    lignes = [_ligne_read(l, magasins) for l in await _lignes(db, project.id)]
    phases = await _phases(db, project.id)
    resume, phases_out = _resume(lignes, phases, await _coutant_soumission(db, project))
    return ListeRead(lignes=lignes, phases=phases_out, resume=resume)


# ───────────────────────────── Routes ─────────────────────────────

@router.get("/{project_id}/materiaux", response_model=ListeRead)
async def liste_materiaux(project_id: int, db: DBSession, user: CurrentUser) -> ListeRead:
    p = await _projet_visible(db, project_id, user)
    return await _liste_read(db, p)


@router.post("/{project_id}/materiaux", response_model=ListeRead, status_code=201)
async def ajouter_ligne(project_id: int, data: LigneCreate, db: DBSession, user: CurrentUser) -> ListeRead:
    p = await _projet_visible(db, project_id, user)
    if data.materiau_id is not None:
        m = (await db.execute(
            select(Materiau).where(Materiau.id == data.materiau_id).options(selectinload(Materiau.offres))
        )).scalar_one_or_none()
        if m is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Matériau introuvable")
    elif data.new_name and data.new_name.strip():
        name = data.new_name.strip()
        key = norm_key(name)
        m = (await db.execute(
            select(Materiau).where(Materiau.name_key == key).options(selectinload(Materiau.offres))
        )).scalars().first()
        if m is None:
            cat = categorie_standard(data.new_categorie) if data.new_categorie else categoriser_par_nom(name)
            m = Materiau(name=name, name_key=key, categorie=cat, unit=data.unit)
            db.add(m)
            await db.flush()
            await db.refresh(m, attribute_names=["offres"])
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "materiau_id ou new_name requis")
    if data.phase_id is not None:
        ph = (await db.execute(select(ProjectPhase).where(
            ProjectPhase.id == data.phase_id, ProjectPhase.project_id == project_id
        ))).scalar_one_or_none()
        if ph is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Phase introuvable sur ce projet")
    if data.magasin_id is not None:
        if (await db.execute(select(Magasin.id).where(Magasin.id == data.magasin_id))).scalar_one_or_none() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Magasin introuvable")
    pos = (await db.execute(
        select(func.coalesce(func.max(ProjetMateriau.position), -1)).where(ProjetMateriau.project_id == project_id)
    )).scalar_one()
    l = ProjetMateriau(
        project_id=project_id, phase_id=data.phase_id, materiau_id=m.id,
        quantity=data.quantity, unit=(data.unit or m.unit), magasin_id=data.magasin_id,
        notes=data.notes, position=int(pos) + 1,
    )
    # Prix prévu = instantané du prix courant (magasin choisi, sinon le
    # moins cher) sauf si fourni explicitement.
    if data.prix_prevu is not None:
        l.prix_prevu = data.prix_prevu
    else:
        pc = prix_courant(l, m.offres, _actifs(await _magasins_map(db)))
        if pc.offre is not None:
            l.prix_prevu = float(pc.offre.unit_price)
    db.add(l)
    await db.flush()
    return await _liste_read(db, p)


@router.patch("/{project_id}/materiaux/{ligne_id}", response_model=ListeRead)
async def modifier_ligne(
    project_id: int, ligne_id: int, data: LigneUpdate, db: DBSession, user: CurrentUser
) -> ListeRead:
    p = await _projet_visible(db, project_id, user)
    l = await _ligne(db, project_id, ligne_id)
    if data.phase_id is not None:
        ph = (await db.execute(select(ProjectPhase).where(
            ProjectPhase.id == data.phase_id, ProjectPhase.project_id == project_id
        ))).scalar_one_or_none()
        if ph is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Phase introuvable sur ce projet")
        l.phase_id = data.phase_id
    if data.magasin_id is not None:
        if (await db.execute(select(Magasin.id).where(Magasin.id == data.magasin_id))).scalar_one_or_none() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Magasin introuvable")
        changement_magasin = l.magasin_id != data.magasin_id
        l.magasin_id = data.magasin_id
        # Nouveau magasin choisi → le prix prévu suit son prix courant,
        # sauf si un prix prévu est posé dans la même requête.
        if changement_magasin and data.prix_prevu is None:
            pc = prix_courant(l, l.materiau.offres if l.materiau else [])
            if pc.offre is not None and pc.offre.magasin_id == data.magasin_id:
                l.prix_prevu = float(pc.offre.unit_price)
    if data.achat_id is not None:
        a = (await db.execute(select(Achat.id, Achat.project_id).where(Achat.id == data.achat_id))).first()
        if a is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Achat introuvable")
        if a.project_id is not None and a.project_id != project_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cet achat appartient à un autre projet")
    for champ in ("quantity", "unit", "prix_prevu", "prix_paye", "achete_le", "achat_id", "notes", "position"):
        v = getattr(data, champ)
        if v is not None:
            setattr(l, champ, v)
    if data.statut is not None and data.statut != l.statut:
        l.statut = data.statut
        if data.statut == "achete":
            if l.prix_paye is None:
                pc = prix_courant(l, l.materiau.offres if l.materiau else [], _actifs(await _magasins_map(db)))
                l.prix_paye = (
                    float(pc.offre.unit_price) if pc.offre is not None
                    else (float(l.prix_prevu) if l.prix_prevu is not None else None)
                )
            if l.achete_le is None:
                l.achete_le = date.today()
        else:
            l.prix_paye, l.achete_le = None, None
    for champ in data.clear:
        if champ in ("phase_id", "magasin_id", "prix_prevu", "prix_paye", "achete_le", "achat_id", "notes", "purchase_order_id"):
            setattr(l, champ, None)
    await db.flush()
    return await _liste_read(db, p)


@router.delete("/{project_id}/materiaux/{ligne_id}", response_model=ListeRead)
async def supprimer_ligne(project_id: int, ligne_id: int, db: DBSession, user: CurrentUser) -> ListeRead:
    p = await _projet_visible(db, project_id, user)
    l = await _ligne(db, project_id, ligne_id)
    await db.delete(l)
    await db.flush()
    return await _liste_read(db, p)


async def _fournisseur_pour_magasin(db, magasin: Magasin) -> Fournisseur:
    """Fournisseur (comptable) du même nom que le magasin ; créé s'il
    manque, pour que le PO puisse devenir un Achat poussé à QuickBooks."""
    f = (await db.execute(
        select(Fournisseur)
        .where(func.lower(func.trim(Fournisseur.name)) == magasin.name.strip().lower())
        .order_by(Fournisseur.id.asc())
    )).scalars().first()
    if f is None:
        f = Fournisseur(name=magasin.name.strip(), website=magasin.website, category="materiaux")
        db.add(f)
        await db.flush()
    return f


@router.post("/{project_id}/materiaux/creer-po", response_model=CreerPoResult, status_code=201)
async def creer_po(project_id: int, data: CreerPoBody, db: DBSession, user: RequireManager) -> CreerPoResult:
    """Réservé aux gestionnaires (comme POST /purchase-orders)."""
    p = await _projet_visible(db, project_id, user)
    magasin = (await db.execute(select(Magasin).where(Magasin.id == data.magasin_id))).scalar_one_or_none()
    if magasin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Magasin introuvable")
    if data.assigned_employe_id is not None:
        if (await db.execute(select(Employe.id).where(Employe.id == data.assigned_employe_id))).scalar_one_or_none() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Employé introuvable")
    # Verrou sur les lignes du projet : deux clics simultanés ne doivent
    # pas produire deux PO avec les mêmes articles.
    verrou = (
        select(ProjetMateriau)
        .where(
            ProjetMateriau.project_id == project_id,
            ProjetMateriau.statut == "a_acheter",
            ProjetMateriau.purchase_order_id.is_(None),
        )
        .options(selectinload(ProjetMateriau.materiau).selectinload(Materiau.offres))
        .order_by(ProjetMateriau.position.asc(), ProjetMateriau.id.asc())
        .with_for_update(of=ProjetMateriau)
    )
    lignes = list((await db.execute(verrou)).scalars().unique().all())
    actifs = _actifs(await _magasins_map(db))
    if data.ligne_ids:
        voulues = set(data.ligne_ids)
        lignes = [l for l in lignes if l.id in voulues]
    else:
        retenues = []
        for l in lignes:
            if l.magasin_id == magasin.id:
                retenues.append(l)
            elif l.magasin_id is None:
                pc = prix_courant(l, l.materiau.offres if l.materiau else [], actifs)
                if pc.offre is not None and pc.offre.magasin_id == magasin.id:
                    retenues.append(l)
        lignes = retenues
    if not lignes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Aucune ligne à commander chez ce magasin.")
    fournisseur = await _fournisseur_pour_magasin(db, magasin)
    po = PurchaseOrder(
        reference=await next_po_number(db),
        fournisseur_id=fournisseur.id,
        project_id=project_id,
        assigned_employe_id=data.assigned_employe_id,
        description=f"Matériaux — {p.name} — {magasin.name}",
        payment_method=data.payment_method,
        status=PurchaseOrderStatus.DRAFT.value,
        notes="Généré depuis la liste d'achats de matériaux du projet.",
    )
    db.add(po)
    await db.flush()
    total = 0.0
    for i, l in enumerate(lignes):
        offres = l.materiau.offres if l.materiau else []
        o = next((x for x in offres if x.magasin_id == magasin.id and x.unit_price is not None), None)
        prix = float(o.unit_price) if o is not None else (float(l.prix_prevu) if l.prix_prevu is not None else 0.0)
        qty = float(l.quantity or 0)
        t = round(qty * prix, 2)
        total += t
        db.add(PurchaseOrderItem(
            purchase_order_id=po.id, position=i,
            description=(l.materiau.name if l.materiau else f"Matériau {l.materiau_id}")[:500],
            unit=l.unit, quantity=qty, unit_price=prix, total=t,
        ))
        l.purchase_order_id = po.id
        # La ligne part chez CE magasin, quel que soit le choix précédent.
        l.magasin_id = magasin.id
    po.amount_max = round(total, 2)
    await db.flush()
    return CreerPoResult(purchase_order_id=po.id, reference=po.reference, nb_lignes=len(lignes), total=round(total, 2))


@rabais_router.get("/rabais", response_model=List[RabaisRead])
async def rabais_du_jour(
    db: DBSession, user: CurrentUser,
    project_id: Optional[int] = Query(default=None),
) -> List[RabaisRead]:
    """Rabais en cours sur les matériaux encore à acheter des chantiers
    ouverts (ceux que l'alerte quotidienne signale)."""
    rows = await rabais_en_cours(db, project_id)
    visible = await visible_project_ids(db, user)
    if visible is not None:
        rows = [r for r in rows if r["project_id"] in visible]
    return [RabaisRead(**r) for r in rows]
