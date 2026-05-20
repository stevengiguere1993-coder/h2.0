"""Historique des taux horaires d'un employé.

Problème résolu : quand on change le salaire d'un employé, les
punchs PASSÉS ne doivent PAS être recoûtés au nouveau taux. Le coût
réel d'un projet (rentabilité) doit refléter le taux en vigueur À
LA DATE du punch.

Modèle : une ligne = une période de taux qui DÉBUTE à
`effective_date`. Pour coûter un punch daté D, on prend la ligne
avec le plus grand `effective_date <= D`. La 1re ligne (baseline)
est créée automatiquement avec les taux courants de l'employé au
moment du tout premier changement, datée de son embauche, pour que
tous les punchs antérieurs au 1er changement gardent le bon taux.

Les taux `cnesst_rate` / `ccq_rate` sont stockés en DÉCIMAL
(0.0216 = 2,16 %), comme sur le modèle Employe.
"""

from datetime import date
from typing import Optional

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class EmployeRateHistory(Base, TimestampMixin):
    __tablename__ = "employe_rate_history"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    employe_id: Mapped[int] = mapped_column(
        ForeignKey("employes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Date d'entrée en vigueur de ce taux. Le taux s'applique à tout
    # punch daté >= effective_date (et < effective_date de la période
    # suivante).
    effective_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )
    # Taux coûtant (ce qu'Horizon paie).
    hourly_rate: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0
    )
    # Taux facturable client. NULL = même que hourly_rate.
    billing_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    # Majorations en décimal.
    cnesst_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 4), nullable=True
    )
    ccq_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 4), nullable=True
    )
    is_ccq: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Note libre : « augmentation annuelle », « passage CCQ », etc.
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<EmployeRateHistory(employe_id={self.employe_id}, "
            f"effective_date={self.effective_date}, "
            f"hourly_rate={self.hourly_rate})>"
        )
