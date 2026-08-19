"""Porte UNIQUE des courriels vers un LOCATAIRE (audit 2026-08-17).

Avant : six chemins d'envoi coexistaient, chacun avec ses propres règles.
Deux écarts en découlaient, invisibles depuis l'écran mais bien réels
pour le locataire ET pour le suivi :

1. **Expéditeur** — seules la page Communications et la demande de preuve
   d'assurance lisaient le PROFIL D'EXPÉDITEUR configuré (nom affiché +
   ``reply_to`` du gestionnaire). Les avis TAL, le bail à signer, l'avis
   de renouvellement, le DPA et la relance de loyer partaient de la boîte
   générique : le locataire voyait un autre nom, et sa RÉPONSE n'arrivait
   pas chez le gestionnaire.
2. **Trace** — le principe posé pour la page Communications (« chaque
   courriel laisse une ligne d'audit ET une entrée sur la fiche du
   locataire ») n'était tenu que par deux chemins sur six. L'avis de
   renouvellement et le bail à signer ne laissaient rien du tout dans
   l'historique du locataire.

Tout envoi vers un locataire passe désormais par ``envoyer_au_locataire``
qui garantit les trois invariants d'un coup : profil d'expéditeur,
journal d'audit ``imm_communications``, fil de la fiche locataire.

⚠️ Règle absolue INCHANGÉE : cette fonction n'est jamais appelée par un
cron. Rien ne part vers un locataire sans un clic humain.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


class EnvoiLocataireError(RuntimeError):
    """Envoi impossible (mailer non configuré, destinataire absent…)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def envoyer_au_locataire(
    db: AsyncSession,
    *,
    destinataires: Sequence[str],
    sujet: str,
    corps_html: str,
    type_envoi: str,
    locataire_id: Optional[int] = None,
    locataire_nom: Optional[str] = None,
    bail_id: Optional[int] = None,
    immeuble_id: Optional[int] = None,
    immeuble_nom: Optional[str] = None,
    document_id: Optional[int] = None,
    auteur_email: Optional[str] = None,
    resume_fiche: Optional[str] = None,
    attachments: Optional[Iterable[Any]] = None,
    bcc: Optional[Sequence[str]] = None,
    request_read_receipt: bool = False,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Envoie UN courriel à un locataire et le trace deux fois.

    Retourne le triplet d'expéditeur réellement utilisé
    ``(from_email, from_name, reply_to)`` — utile aux appelants qui
    l'affichent (« envoyé par … ») ou le journalisent.

    Lève ``EnvoiLocataireError`` si le mailer n'est pas configuré ou si
    aucun destinataire n'est fourni : l'appelant traduit en 4xx/5xx selon
    son contexte. N'appelle PAS ``commit`` — la transaction reste à
    l'appelant (les traces suivent le sort de son geste).
    """
    from app.api.v1.endpoints.immobilier_communications import (
        expediteur_defaut,
    )
    from app.integrations.email_graph import get_mailer
    from app.models.immobilier import (
        ImmCommunication,
        LocataireCommunication,
    )

    dest = [a.strip() for a in (destinataires or []) if a and a.strip()]
    if not dest:
        raise EnvoiLocataireError(
            "Aucun courriel destinataire (ajoute un courriel au "
            "locataire)."
        )

    mailer = get_mailer()
    if not mailer.ready:
        raise EnvoiLocataireError(
            "Mailer non configuré (AZURE_* / MAIL_FROM_EMAIL)."
        )

    from_email, from_name, reply_to = await expediteur_defaut()

    kwargs: dict[str, Any] = {
        "to": list(dest),
        "subject": sujet,
        "html_body": corps_html,
        "from_email": from_email,
        "from_name": from_name,
        # Repli sur la boîte système : une réponse doit TOUJOURS
        # atterrir quelque part de lisible.
        "reply_to": reply_to or mailer.sender,
    }
    if attachments:
        kwargs["attachments"] = list(attachments)
    if bcc:
        kwargs["bcc"] = list(bcc)
    if request_read_receipt:
        # « Envoi certifié » de l'avis de renouvellement : accusé de
        # lecture Outlook demandé au locataire.
        kwargs["request_read_receipt"] = True
    await mailer.send(**kwargs)

    async def _tracer(objet, quoi: str) -> None:
        """Pose UNE trace dans un point de reprise (SAVEPOINT).

        Le courriel est DÉJÀ parti quand on arrive ici : une trace qui
        échoue ne doit ni remonter en erreur, ni — surtout — empoisonner
        la transaction de l'appelant. Un simple ``try`` autour de
        ``db.add`` ne protège de rien : l'INSERT ne part qu'au ``flush``,
        donc l'erreur explose plus tard, chez l'appelant (bug du
        2026-08-19 : un ``group_id`` de 36 caractères dans une colonne
        de 32 faisait échouer CHAQUE trace, ce qui annulait au passage
        le jeton de signature déjà envoyé au locataire — lien mort dans
        sa boîte, et « internal server error » à l'écran).
        """
        try:
            async with db.begin_nested():
                db.add(objet)
        except Exception:  # noqa: BLE001 — la trace ne casse jamais l'envoi
            log.exception("Trace %s échouée (%s)", quoi, type_envoi)

    # 1) Journal d'audit de la page Communications.
    # ⚠️ group_id : MÊME format que la page Communications
    # (``secrets.token_hex(8)`` = 16 caractères). La colonne est un
    # VARCHAR(32) — un uuid4 avec tirets (36) ne rentre pas, et SQLite
    # (tests) ne fait pas respecter la longueur, donc rien ne le signale
    # avant la production.
    await _tracer(
        ImmCommunication(
            group_id=secrets.token_hex(8),
            type=type_envoi[:32],
            sujet=sujet[:255],
            corps=corps_html,
            locataire_id=locataire_id,
            bail_id=bail_id,
            immeuble_id=immeuble_id,
            document_id=document_id,
            locataire_nom=(locataire_nom or None)
            and locataire_nom[:255],
            immeuble_nom=(immeuble_nom or None) and immeuble_nom[:255],
            destinataire_email=dest[0][:320],
            from_email=(from_email or None) and from_email[:320],
            created_by_email=(auteur_email or None) and auteur_email[:256],
            created_at=_now(),
        ),
        "ImmCommunication",
    )

    # 2) Fil de la fiche du locataire.
    if locataire_id is not None:
        await _tracer(
            LocataireCommunication(
                locataire_id=locataire_id,
                kind="courriel",
                contenu=(resume_fiche or sujet)[:2000],
                auteur=(auteur_email or None) and auteur_email[:255],
            ),
            "LocataireCommunication",
        )

    return from_email, from_name, reply_to
