"""Mode de calcul des heures d'une personne (Steven, 2026-11-10 / 13).

« Choisir dans la fiche par quel système de calcul de leurs heures nous
passons. Attention : les employés qui utilisent le punch actuellement
doivent rester en punch construction (déjà définir le calcul par punch, je
décocherais la case au besoin). »

``User.mode_heures`` :

- ``punch`` : punch construction (fiche Employé, rapport de paie par punch) ;
- ``feuille`` : feuille de temps (heures par jour + ce qui a été fait) ;
- ``les_deux`` : les deux comptent dans la paie ;
- NULL : mode par défaut, déduit — ``punch`` dès qu'une fiche Employé
  (Construction) porte le courriel du compte, sinon ``feuille``. Personne
  qui punche aujourd'hui ne change donc de mode sans qu'on décoche.

Le mode décide de ce qui entre dans le rapport de paie (punchs et / ou
feuilles approuvées), du suivi et des rappels de feuille de temps.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

from sqlalchemy import func, select

from app.models.employe import Employe
from app.models.user import User

MODES = ("punch", "feuille", "les_deux")
MODES_LABELS = {
    "punch": "Punch construction",
    "feuille": "Feuille de temps",
    "les_deux": "Punch construction et feuille de temps",
}


def normaliser(mode: Optional[str]) -> Optional[str]:
    return mode if mode in MODES else None


def depuis_cases(punch: bool, feuille: bool) -> str:
    if punch and feuille:
        return "les_deux"
    return "feuille" if feuille else "punch"


def mode_effectif(user: User, a_fiche_employe: bool) -> str:
    stocke = normaliser(getattr(user, "mode_heures", None))
    if stocke:
        return stocke
    return "punch" if a_fiche_employe else "feuille"


def compte_punch(mode: str) -> bool:
    return mode in ("punch", "les_deux")


def compte_feuille(mode: str) -> bool:
    return mode in ("feuille", "les_deux")


async def emails_avec_fiche(db, emails: Iterable[str]) -> set[str]:
    """Courriels (minuscules) qui ont une fiche Employé active."""
    cles = sorted({(e or "").lower() for e in emails if e})
    if not cles:
        return set()
    rows = (
        await db.execute(
            select(func.lower(Employe.email)).where(
                func.lower(Employe.email).in_(cles), Employe.active.is_(True)
            )
        )
    ).scalars().all()
    return {r for r in rows if r}


async def modes_pour(db, users: Iterable[User]) -> Dict[int, str]:
    """{user_id: mode effectif}."""
    users = list(users)
    fiches = await emails_avec_fiche(db, [u.email for u in users])
    return {
        u.id: mode_effectif(u, (u.email or "").lower() in fiches) for u in users
    }
