"""Entreprise — entité d'affaire (HSI, sociétés sœurs, partenariats…).

Sert de tronc au volet Gestion d'entreprises : chaque tâche, projet
ou suivi appartient à une entreprise. Les utilisateurs peuvent être
associés à plusieurs entreprises via EntreprisePartner avec un rôle
et un pourcentage d'ownership.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class Entreprise(Base, TimestampUpdateMixin):
    __tablename__ = "entreprises"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )

    # NEQ (numéro d'entreprise du Québec). Permet le lien avec REQ.
    neq: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )

    # Catégorie : gestion / construction / immobilier / autre.
    # Influence l'icône et certains workflows.
    type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="gestion",
        server_default="gestion",
    )

    # Couleur d'accent pour l'UI (badge entreprise dans les listes
    # de tâches multi-entreprises). Format hex « #aabbcc ».
    color_accent: Mapped[str] = mapped_column(
        String(7), nullable=False, default="#7c3aed",
        server_default="#7c3aed",
    )

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Lien Monday : board source pour la synchronisation des tâches.
    # NULL = entreprise gérée nativement dans h2.0.
    monday_board_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    monday_board_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # URL du dossier Google Drive lié à cette entreprise. Le bouton
    # « Drive » du header de la fiche y mène. NULL = pas configuré
    # encore (le bouton propose alors de coller l'URL).
    drive_folder_url: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True
    )

    # Ordre d'affichage dans la sidebar « Mes entreprises ». Modifiable
    # par drag & drop côté frontend. On alloue par pas de 1000 à la
    # création pour pouvoir insérer entre deux items sans renuméroter
    # tout le monde à chaque déplacement.
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", index=True
    )


class EntreprisePartner(Base):
    """Partenaire d'une entreprise — interne (User du portail) ou externe.

    Plusieurs partenaires peuvent posséder une entreprise (ex. 50/50
    Steven + Philippe). Le rôle décrit la fonction (associé,
    administrateur, gérant, prêteur…).

    `user_id` est optionnel : si le partenaire a un compte portail on
    le lie ; sinon on saisit `partner_name` + email à la main.
    """

    __tablename__ = "entreprise_partners"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Identité du partenaire (utilisé si user_id est null OU pour
    # surclasser le full_name auto issu de User).
    partner_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    partner_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    partner_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="associe",
        server_default="associe",
    )
    ownership_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True
    )


class EntrepriseLink(Base):
    """Lien externe (Drive, SharePoint, Dropbox…) attaché à une entreprise.

    Permet de pointer vers la documentation hébergée hors portail :
    statuts, procès-verbaux, contrats, P&L, comptes annuels, etc.
    """

    __tablename__ = "entreprise_links"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Catégorie pour l'icône : drive | sharepoint | dropbox | onenote |
    # notion | website | autre
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="autre",
        server_default="autre",
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
