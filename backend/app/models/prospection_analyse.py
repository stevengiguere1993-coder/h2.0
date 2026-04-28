"""ProspectionAnalyse — analyse financière multi-logements (Québec).

Représente UNE simulation du calculateur financier (3 scénarios :
Achat conventionnel, Refinancement SCHL, Refinancement APH 50).
Chaque analyse capture les inputs saisis (prix, revenus, dépenses,
TGA, taux, frais de démarrage…) et les résultats calculés
(MDF, prêts, gain actionnaires).

Les calculs sont faits côté frontend (TypeScript pur, testé). Le
backend ne fait que persister inputs + résultats. Cela permet :
- Reproductibilité : même `inputs_json` redonne les mêmes résultats.
- Historique : on garde les analyses passées pour comparaison.
- Lien avec un lead : `lead_id` est nullable (analyse libre possible).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class ProspectionAnalyse(Base, TimestampUpdateMixin):
    __tablename__ = "prospection_analyses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Lien optionnel vers un lead (analyse libre possible).
    lead_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("prospection_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Nom de l'analyse (par défaut : adresse + date).
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Inputs du calculateur — JSON-encodé. Schéma : AnalyseInputs
    # (cf. frontend/src/lib/financial-calculator/types.ts).
    inputs_json: Mapped[str] = mapped_column(Text, nullable=False)

    # Résultats des 3 scénarios — JSON-encodé. Schéma : AnalyseResultats
    # (cf. frontend/src/lib/financial-calculator/types.ts).
    results_json: Mapped[str] = mapped_column(Text, nullable=False)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
