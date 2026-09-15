"""SoumissionAvenant — avenant (change order) d'un devis ACCEPTÉ.

Retour 2026-09-15 : en cours de projet estimé, le client change d'idée
(items ajoutés, modifiés, retirés) et la facturation progressive
dérivait. Désormais :

- le devis accepté est FIGÉ (soumission_items refuse toute écriture) ;
- chaque changement passe par un avenant numéroté (AV-1, AV-2…) qui
  applique ses opérations et en garde la trace (``changes_json``) ;
- le « contrat courant » = items actifs (non retirés) du devis, base
  unique de la facturation progressive.

Un item retiré n'est JAMAIS supprimé : il est marqué
``retire_par_avenant_id`` pour que l'historique « facturé à date » de
ses lignes de facture reste attaché (c'était la source de la dérive des
pourcentages). Nouvelle table + colonnes additives → create_all /
ajouter_colonnes_manquantes, aucune migration.
"""

from typing import Optional

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class SoumissionAvenant(Base, TimestampUpdateMixin):
    __tablename__ = "soumission_avenants"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    soumission_id: Mapped[int] = mapped_column(
        ForeignKey("soumissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Numéro séquentiel PAR soumission (1, 2, 3…) → référence "AV-1".
    numero: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reference: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Raison du changement, visible sur la fiche (« Client ajoute une
    #: salle d'eau au sous-sol »).
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    #: Journal détaillé des opérations appliquées (JSON) : liste de
    #: {op: ajout|retrait|modification, item_id, avant: {...}, apres: {...}}.
    changes_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    #: Impact HT de l'avenant sur le contrat (positif = le contrat
    #: augmente). Stocké pour l'affichage sans recalcul.
    impact_subtotal: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )

    created_by_email: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True
    )
