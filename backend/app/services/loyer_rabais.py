"""Rabais sur les premiers mois d'un bail et loyer DÛ fixé à la main.

Deux demandes du lot de bugs du 2026-10-18 :

- bug 10 (mvilliard, /immobilier/logements/115) : « le locataire a un
  rabais de 500 $ pour les 3 premiers mois, ensuite il va être à
  1 500 $ / mois » ;
- bug 4 (mvilliard, /immobilier/locataires/57) : « je ne peux changer
  les montants perçus et percevable ».

Le loyer du bail reste le loyer PLEIN (c'est lui qui figure au bail
TAL, dans les avis d'augmentation, le rent roll, les relevés). Ce qui
change d'un mois à l'autre se matérialise en lignes ``FraisLocatif``
NÉGATIVES (crédits) ou positives, que TOUT le pôle additionne déjà au
loyer pour obtenir le dû du mois : suivi des loyers, solde cumulatif,
répartition d'un trop-payé, exports, relances, validation bancaire,
assistant. Aucun calcul n'a eu à changer — c'est le point.

- ``synchroniser_rabais_bail`` régénère, à partir des paramètres du
  bail (``rabais_mensuel`` × ``rabais_nb_mois`` depuis ``rabais_debut``),
  un crédit d'origine ``ORIGINE_RABAIS`` par mois. Idempotent : les
  crédits précédents du même bail sont remplacés.
- ``fixer_du_mois`` pose UNE ligne d'origine ``ORIGINE_AJUSTEMENT`` sur
  le mois pour que le dû du mois (loyer + toutes les lignes du mois)
  tombe exactement sur le montant voulu ; la ligne précédente du même
  mois est remplacée, et elle disparaît si le montant voulu redevient
  le dû naturel.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.immobilier import Bail, FraisLocatif

#: Crédit généré par le rabais paramétré sur le bail.
ORIGINE_RABAIS = "rabais_bail"
#: Ligne posée quand le loyer dû d'un mois est fixé à la main.
ORIGINE_AJUSTEMENT = "ajustement_mois"

#: Borne de sécurité, alignée sur le schéma (``rabais_nb_mois`` ≤ 36).
RABAIS_NB_MOIS_MAX = 36


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mois_suivant(m: date) -> date:
    return date(m.year + (1 if m.month == 12 else 0), 1 if m.month == 12 else m.month + 1, 1)


def rabais_actif(bail: Bail) -> bool:
    """Le bail porte-t-il un rabais complet (montant > 0 ET nb de mois) ?"""
    montant = float(getattr(bail, "rabais_mensuel", None) or 0)
    nb = int(getattr(bail, "rabais_nb_mois", None) or 0)
    return montant > 0.005 and nb > 0


def mois_rabais(bail: Bail) -> List[date]:
    """1ers de mois couverts par le rabais (vide si pas de rabais)."""
    if not rabais_actif(bail):
        return []
    debut = getattr(bail, "rabais_debut", None) or bail.date_debut
    if debut is None:
        return []
    m = debut.replace(day=1)
    nb = min(int(bail.rabais_nb_mois or 0), RABAIS_NB_MOIS_MAX)
    out: List[date] = []
    for _ in range(nb):
        out.append(m)
        m = _mois_suivant(m)
    return out


def libelle_rabais(bail: Bail, index: int, total: int) -> str:
    base = (getattr(bail, "rabais_motif", None) or "").strip() or "Rabais de loyer"
    return f"{base} ({index}/{total})"[:128]


async def synchroniser_rabais_bail(db: AsyncSession, bail: Bail) -> List[FraisLocatif]:
    """Remplace les crédits de rabais du bail par ceux que décrivent ses
    paramètres courants. Sans rabais → tout est retiré. Ne commit pas."""
    existants = (
        await db.execute(
            select(FraisLocatif).where(
                FraisLocatif.bail_id == bail.id,
                FraisLocatif.origine == ORIGINE_RABAIS,
            )
        )
    ).scalars().all()
    for f in existants:
        await db.delete(f)
    mois = mois_rabais(bail)
    crees: List[FraisLocatif] = []
    montant = round(-abs(float(bail.rabais_mensuel or 0)), 2)
    for i, m in enumerate(mois, start=1):
        f = FraisLocatif(
            bail_id=bail.id,
            mois_couvert=m,
            montant=montant,
            libelle=libelle_rabais(bail, i, len(mois)),
            origine=ORIGINE_RABAIS,
            created_by_email=None,
            created_at=_now(),
        )
        db.add(f)
        crees.append(f)
    await db.flush()
    return crees


async def fixer_du_mois(
    db: AsyncSession,
    bail: Bail,
    mois: date,
    montant_du: float,
    *,
    motif: Optional[str] = None,
    par: Optional[str] = None,
) -> Optional[FraisLocatif]:
    """Fixe le loyer DÛ du mois à ``montant_du`` (bug 4 : « percevable »).

    Le dû du mois = loyer du bail + toutes les lignes du mois (frais,
    crédits, rabais). On remplace la ligne d'ajustement du mois par
    celle qui fait tomber ce total sur ``montant_du`` ; si l'écart est
    nul, aucune ligne ne reste. Retourne la ligne posée (ou None).
    Ne commit pas."""
    mois = mois.replace(day=1)
    lignes = (
        await db.execute(
            select(FraisLocatif).where(
                FraisLocatif.bail_id == bail.id,
                FraisLocatif.mois_couvert == mois,
            )
        )
    ).scalars().all()
    autres = 0.0
    for f in lignes:
        if f.origine == ORIGINE_AJUSTEMENT:
            await db.delete(f)
        else:
            autres += float(f.montant or 0)
    loyer = float(bail.loyer_mensuel or 0)
    ecart = round(float(montant_du) - loyer - autres, 2)
    await db.flush()
    if abs(ecart) < 0.005:
        return None
    lib = (motif or "").strip() or (
        f"Loyer du mois fixé à {float(montant_du):,.2f} $".replace(",", " ")
    )
    f = FraisLocatif(
        bail_id=bail.id,
        mois_couvert=mois,
        montant=ecart,
        libelle=lib[:128],
        origine=ORIGINE_AJUSTEMENT,
        created_by_email=par,
        created_at=_now(),
    )
    db.add(f)
    await db.flush()
    return f
