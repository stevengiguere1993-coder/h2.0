"""Inventaire interne — entrées, comptes et sorties vers un projet
(Steven 2026-10-18).

Une SORTIE charge le projet par un achat de nature « inventaire »
(``Achat.kind = KIND_INVENTAIRE``) plutôt que par une table à part : elle
suit toute la machinerie des achats sans rien dupliquer — coût réel du
projet (onglet Finances), onglet et page « À refacturer », import sur la
facture (ligne « Matériaux », majoration comprise), dé-refacturation quand
la facture est supprimée. Ce qui la distingue d'un achat chez un
fournisseur :

- montant = quantité × coût unitaire moyen, HORS TAXES et sans taxes : les
  taxes ont été payées (et récupérées) à l'achat du stock ;
- statut « payé », sans mode de paiement : personne à payer ;
- jamais poussée dans QuickBooks (garde dans ``sync_achat_to_qbo``) : le
  stock y est entré à son achat ;
- « à refacturer » par défaut selon la même règle qu'un achat saisi
  (projet à contrat ou bon de travail), cochable à la main ensuite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.achat import KIND_INVENTAIRE, Achat, AchatStatus
from app.models.inventaire import InventaireArticle, InventaireMouvement
from app.models.project import Project
from app.models.soumission import Soumission

TYPE_ENTREE = "entree"
TYPE_AJUSTEMENT = "ajustement"
TYPE_SORTIE = "sortie"

MONTREAL = ZoneInfo("America/Montreal")


class InventaireErreur(ValueError):
    """Refus métier (stock insuffisant, coût inconnu, sortie déjà
    refacturée…) — rendu en 409 par l'endpoint, message tel quel."""


DEJA_REFACTUREE = (
    "Cette sortie d'inventaire est déjà refacturée sur une facture : "
    "retire-la de la facture avant de l'annuler."
)


def _qte(v) -> float:
    return round(float(v or 0), 3)


def _cout(v) -> Optional[float]:
    return None if v is None else float(v)


def _fmt_qte(q: float) -> str:
    return f"{q:g}".replace(".", ",")


def cout_moyen(
    qte_avant: float,
    cout_avant: Optional[float],
    qte_entree: float,
    cout_entree: Optional[float],
) -> Optional[float]:
    """Coût unitaire moyen pondéré après une entrée. Sans prix à l'entrée,
    le coût courant est gardé ; sans stock en main ou sans coût connu, le
    prix de l'entrée devient le coût."""
    if cout_entree is None:
        return cout_avant
    if cout_avant is None or qte_avant <= 0:
        return round(float(cout_entree), 4)
    total = qte_avant + qte_entree
    return round((qte_avant * cout_avant + qte_entree * cout_entree) / total, 4)


def libelle_sortie(article: InventaireArticle, quantite: float) -> str:
    """Description de l'achat créé sur le projet — c'est ce qu'on lit dans
    les achats du projet, « À refacturer » et le détail de la ligne
    « Matériaux » de la facture."""
    unite = (article.unit or "").strip()
    return (
        f"Inventaire interne — {article.name} × {_fmt_qte(quantite)}"
        + (f" {unite}" if unite else "")
    )


async def refacturable_par_defaut(db: AsyncSession, project: Project) -> bool:
    """Même règle qu'un achat saisi sans choix explicite (création d'un
    achat, business.py) : refacturable sur le mini-projet d'un BON DE
    TRAVAIL ou un projet à CONTRAT ; estimé, forfaitaire ou sans
    soumission → coût du projet, cochable à la main."""
    if (project.kind or "") == "bon_travail":
        return True
    if not project.soumission_id:
        return False
    kind = (
        await db.execute(
            select(Soumission.kind).where(Soumission.id == project.soumission_id)
        )
    ).scalar_one_or_none()
    return kind == "contract"


async def entrer(
    db: AsyncSession,
    article: InventaireArticle,
    quantite: float,
    *,
    cout_unitaire: Optional[float] = None,
    note: Optional[str] = None,
    user_id: Optional[int] = None,
) -> InventaireMouvement:
    """Ajoute au stock (achat de réapprovisionnement, retour de chantier,
    stock initial) et recalcule le coût moyen."""
    q = _qte(quantite)
    if q <= 0:
        raise InventaireErreur("La quantité ajoutée doit être plus grande que 0.")
    avant = float(article.quantite or 0)
    article.cout_unitaire = cout_moyen(
        avant, _cout(article.cout_unitaire), q, cout_unitaire
    )
    article.quantite = _qte(avant + q)
    mv = InventaireMouvement(
        article_id=article.id,
        type=TYPE_ENTREE,
        quantite=q,
        cout_unitaire=cout_unitaire,
        note=note,
        created_by_user_id=user_id,
    )
    db.add(mv)
    await db.flush()
    return mv


async def ajuster(
    db: AsyncSession,
    article: InventaireArticle,
    quantite_comptee: float,
    *,
    note: Optional[str] = None,
    user_id: Optional[int] = None,
) -> Optional[InventaireMouvement]:
    """Corrige le stock d'après un compte réel. L'écart est tracé ; rien
    n'est écrit si le compte égale déjà le stock."""
    compte = _qte(quantite_comptee)
    if compte < 0:
        raise InventaireErreur("Le compte ne peut pas être négatif.")
    ecart = _qte(compte - float(article.quantite or 0))
    if ecart == 0:
        return None
    article.quantite = compte
    mv = InventaireMouvement(
        article_id=article.id,
        type=TYPE_AJUSTEMENT,
        quantite=ecart,
        cout_unitaire=article.cout_unitaire,
        note=note,
        created_by_user_id=user_id,
    )
    db.add(mv)
    await db.flush()
    return mv


async def sortir(
    db: AsyncSession,
    article: InventaireArticle,
    project: Project,
    quantite: float,
    *,
    cout_unitaire: Optional[float] = None,
    is_billable: Optional[bool] = None,
    note: Optional[str] = None,
    user_id: Optional[int] = None,
) -> tuple[InventaireMouvement, Achat]:
    """Sort du stock vers un projet et charge le projet : achat
    « inventaire » au coût moyen (ou au coût donné), hors taxes."""
    q = _qte(quantite)
    if q <= 0:
        raise InventaireErreur("La quantité sortie doit être plus grande que 0.")
    if not article.is_active:
        raise InventaireErreur(
            f"« {article.name} » est désactivé : réactive-le avant de le sortir."
        )
    en_main = float(article.quantite or 0)
    if q > en_main + 1e-9:
        unite = f" {article.unit}" if (article.unit or "").strip() else ""
        raise InventaireErreur(
            f"Stock insuffisant : il reste {_fmt_qte(en_main)}{unite} de "
            f"« {article.name} ». Ajuste le compte avant d'en sortir plus."
        )
    cout = cout_unitaire if cout_unitaire is not None else _cout(article.cout_unitaire)
    if cout is None:
        raise InventaireErreur(
            f"Coût unitaire inconnu pour « {article.name} » : indique-le, "
            "c'est ce qui est chargé au projet."
        )
    if article.cout_unitaire is None:
        article.cout_unitaire = cout

    maintenant = datetime.now(timezone.utc)
    mv = InventaireMouvement(
        article_id=article.id,
        type=TYPE_SORTIE,
        quantite=-q,
        cout_unitaire=cout,
        project_id=project.id,
        note=note,
        created_by_user_id=user_id,
    )
    db.add(mv)
    await db.flush()

    achat = Achat(
        # Référence propre à la sortie : lisible dans les listes d'achats
        # et jamais confondue avec un autre document par la déduplication.
        reference=f"INV-{mv.id}",
        project_id=project.id,
        kind=KIND_INVENTAIRE,
        description=libelle_sortie(article, q),
        amount=round(q * cout, 2),
        amount_taxes=0,
        amount_tps=0,
        amount_tvq=0,
        invoice_date=maintenant.astimezone(MONTREAL).date(),
        status=AchatStatus.PAID.value,
        received_at=maintenant,
        paid_at=maintenant,
        notes=note,
        is_billable=(
            is_billable
            if is_billable is not None
            else await refacturable_par_defaut(db, project)
        ),
        # Choix explicite à la sortie = verrou contre les automatismes,
        # comme pour un achat saisi.
        billable_manual=is_billable is not None,
    )
    db.add(achat)
    await db.flush()
    mv.achat_id = achat.id
    article.quantite = _qte(en_main - q)
    await db.flush()
    return mv, achat


async def annuler_sortie(db: AsyncSession, mv: InventaireMouvement) -> None:
    """Annule une sortie : la marchandise revient en stock et l'achat du
    projet disparaît — refusé si la sortie est déjà sur une facture."""
    if mv.type != TYPE_SORTIE:
        raise InventaireErreur(
            "Seule une sortie s'annule ; corrige une entrée par un ajustement."
        )
    achat = await db.get(Achat, mv.achat_id) if mv.achat_id else None
    if achat is not None and achat.invoiced_at is not None:
        raise InventaireErreur(DEJA_REFACTUREE)
    await _remettre(db, mv)
    if achat is not None:
        await db.delete(achat)
    await db.flush()


async def remettre_en_stock_achat(db: AsyncSession, achat: Achat) -> int:
    """Achat « inventaire » supprimé depuis les achats (fiche, liste) : la
    marchandise revient en stock et la sortie quitte l'historique, pour que
    le stock ne compte pas un matériel que plus aucun projet ne porte.
    Refusé si l'achat est déjà sur une facture, comme l'annulation."""
    if (achat.kind or "") != KIND_INVENTAIRE:
        return 0
    if achat.invoiced_at is not None:
        raise InventaireErreur(DEJA_REFACTUREE)
    mvs = (
        await db.execute(
            select(InventaireMouvement).where(
                InventaireMouvement.achat_id == achat.id,
                InventaireMouvement.type == TYPE_SORTIE,
            )
        )
    ).scalars().all()
    for mv in mvs:
        await _remettre(db, mv)
    await db.flush()
    return len(mvs)


async def _remettre(db: AsyncSession, mv: InventaireMouvement) -> None:
    article = await db.get(InventaireArticle, mv.article_id)
    if article is not None:
        # quantite d'une sortie est négative : la retrancher la rajoute.
        article.quantite = _qte(float(article.quantite or 0) - float(mv.quantite))
    await db.delete(mv)
