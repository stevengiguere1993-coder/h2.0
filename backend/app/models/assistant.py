"""Assistant IA Kratos — actions proposées en attente de confirmation.

Phase 1 (fondation SANS LLM) : chaque ÉCRITURE demandée à l'assistant
passe par une « carte d'action » : l'outil valide les paramètres et
produit un aperçu lisible (« Marquer payé : Daniel Drouin, 218 — 500 $
pour août 2026 »), la ligne est créée au statut ``proposee``, et RIEN
n'est écrit tant que l'utilisateur n'a pas confirmé. À la confirmation,
le handler de l'outil exécute les MÊMES services que la saisie manuelle.

Cycle de vie : proposee → confirmee (exécutée avec succès)
                        → annulee   (refusée par l'utilisateur)
                        → echouee   (exécution en erreur ; ``erreur`` rempli)

Nouvelle table → ``ensure_assistant_tables`` (db/session.py), création
idempotente au boot dans sa propre transaction (règle maison : jamais de
migration Alembic, sinon 500 en prod avec CI verte).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin

#: Statuts valides d'une action (voir le cycle de vie ci-dessus).
STATUTS_ACTION = ("proposee", "confirmee", "annulee", "echouee")


class AssistantAction(Base, TimestampUpdateMixin):
    """Une action d'ÉCRITURE proposée par l'assistant, à confirmer.

    Seul l'utilisateur qui a proposé l'action (``user_id``) peut la
    confirmer ou l'annuler — et sa permission de page est re-vérifiée au
    moment de la confirmation (pas seulement à la proposition).
    """

    __tablename__ = "assistant_actions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    #: L'utilisateur AU NOM DE QUI l'outil agira (ses permissions).
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    #: Id de l'outil du catalogue (``assistant_catalogue.OUTILS``),
    #: ex. « marquer_loyer_paye ».
    outil: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    #: Paramètres de l'appel, JSON sérialisé (house style : colonnes
    #: ``*_json`` en Text, cf. AuditLog.details_json).
    params_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )

    #: Phrase FR lisible décrivant ce qui VA être fait — c'est ce que la
    #: carte affiche à l'utilisateur avant qu'il confirme.
    apercu: Mapped[str] = mapped_column(Text, nullable=False)

    statut: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default="proposee", server_default="proposee", index=True,
    )

    #: Résultat JSON du handler après une confirmation réussie.
    resultat_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    #: Message d'erreur FR si l'exécution a échoué (statut ``echouee``).
    erreur: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    #: Horodatage de l'exécution (confirmée OU échouée).
    executee_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
