"""Send a Facture to a client: generate PDF + email via Microsoft Graph.

QuickBooks d'abord, le client ensuite (Steven 2026-10-17 : « si une
facture bloque en envoi à QB, par exemple à cause de son numéro, ne pas
envoyer cette facture au client. La laisser dans brouillon et mettre une
notification dessus »). La facture est créée ou mise à jour dans
QuickBooks AVANT le rendu du PDF et le courriel : le client reçoit
exactement la facture que QuickBooks a acceptée, sous le même numéro. Si
QuickBooks la refuse, rien ne part : elle garde son statut, le motif est
posé sur sa fiche et les admins sont prévenus dans la cloche Kratos.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.facture import Facture, FactureStatus
from app.services.facture_echeance import appliquer_a_l_envoi
from app.services.facture_pdf import render_facture_pdf
from app.services.public_links import public_base

log = logging.getLogger(__name__)

#: États « ouverts » : l'envoi (re)passe la facture à SENT et la date du
#: jour (émission, échéance).
_STATUTS_ENVOI = (
    FactureStatus.DRAFT.value,
    FactureStatus.SENT.value,
    FactureStatus.OVERDUE.value,
)


class FactureSendError(Exception):
    pass


class FactureBloqueeQB(FactureSendError):
    """Le numéro ou QuickBooks a bloqué la facture : elle n'est PAS partie
    au client. Le message dit pourquoi et où le motif est affiché."""


#: Notification de la cloche Kratos : facture retenue par QuickBooks.
KIND_ENVOI_BLOQUE = "facture_envoi_bloque"


def motif_court(motif: Optional[str]) -> str:
    """La raison lisible d'un refus, sans le détail technique que
    QuickBooksError ajoute après (« QBO refus : <raison> — QBO POST
    /invoice failed: 400 (intuit_tid=…) {…} »)."""
    m = (motif or "").strip()
    if m.startswith("QBO refus : "):
        m = m[len("QBO refus : "):]
    return m.split(" — QBO ", 1)[0].strip()[:300]


async def noter_envoi_bloque(
    facture_id: int,
    motif: str,
    *,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
) -> None:
    """Pose le refus SUR la facture (affiché sur sa fiche et dans la liste)
    et prévient les admins dans la cloche Kratos, une seule fois par motif
    (un nouvel essai refusé pour la même raison n'ajoute rien). Session
    FRAÎCHE : celle de l'envoi vient d'être annulée.

    ``reference`` / ``notes`` : numéro atteint pendant l'essai (attribué à
    l'envoi, ou changé parce que QuickBooks l'avait déjà pour une autre
    facture) et notes internes qui le racontent. Le numéro est gardé : le
    prochain envoi reprend le même, et retrouve l'Invoice que QuickBooks
    aurait créée sans répondre (délai dépassé) au lieu d'en créer une
    deuxième sous un autre numéro."""
    from app.db.session import AsyncSessionLocal
    from app.models.client import Client
    from app.services.notifications import notify_role
    from app.services.numbering import (
        is_provisional_facture_reference,
        numero_pris_dans_kratos,
    )

    texte = (motif or "").strip()[:500] or "QuickBooks a refusé la facture."
    try:
        async with AsyncSessionLocal() as db:
            fa = (
                await db.execute(select(Facture).where(Facture.id == facture_id))
            ).scalar_one_or_none()
            if fa is None:
                return
            ref = (reference or "").strip()
            if (
                ref
                and ref != fa.reference
                and not is_provisional_facture_reference(ref)
                and await numero_pris_dans_kratos(db, ref, sauf_id=fa.id) is None
            ):
                fa.reference = ref
                if notes is not None:
                    fa.internal_notes = notes
            deja_signale = motif_court(fa.qbo_sync_error) == motif_court(texte)
            fa.qbo_sync_error = texte
            if not deja_signale:
                client = (
                    await db.get(Client, fa.client_id) if fa.client_id else None
                )
                numero = (
                    "" if is_provisional_facture_reference(fa.reference)
                    else f" {fa.reference}"
                )
                brouillon = fa.status == FactureStatus.DRAFT.value
                await notify_role(
                    db,
                    min_role="admin",
                    kind=KIND_ENVOI_BLOQUE,
                    title=(
                        f"Facture{numero} non "
                        f"{'envoyée' if brouillon else 'renvoyée'} au client : "
                        "refusée par QuickBooks"
                    ),
                    body=(
                        (f"{client.name} — " if client is not None else "")
                        + (motif_court(texte) or texte)
                        + (
                            ". Elle reste en brouillon : corrige le problème, "
                            "puis renvoie-la au client."
                            if brouillon
                            else ". Corrige le problème, puis renvoie-la."
                        )
                    ),
                    href=f"/app/facturation/{fa.id}",
                    push=False,
                )
            await db.commit()
    except Exception:  # noqa: BLE001 — l'envoi est déjà refusé à l'écran
        log.warning(
            "Facture %s : refus QuickBooks non enregistré sur la fiche",
            facture_id,
            exc_info=True,
        )


async def _numeroter_et_dater(db: AsyncSession, fa: Facture) -> None:
    # Numéro DÉFINITIF attribué à l'ENVOI : un brouillon porte une
    # référence provisoire (« BR-… ») qui ne consomme pas la séquence —
    # on attribue le vrai numéro ICI, AVANT le rendu du PDF (qui
    # l'imprime) et l'objet du courriel. Pas de trous QuickBooks si un
    # brouillon traîne ou est supprimé (audit).
    from app.services.numbering import ensure_facture_number

    await ensure_facture_number(db, fa)
    # « Émise le » = dernière fois où la facture a été envoyée au client :
    # remis à jour à CHAQUE envoi (y compris les renvois), et AVANT le rendu
    # pour que le PDF et le courriel portent le jour réel d'expédition.
    # L'échéance suit : jamais avant ce jour-là, conditions comptées depuis
    # l'envoi (facture 160, 2026-10-16 : créée le 14 « sur réception »,
    # envoyée le 16, échéance restée au 14). Une facture payée ou annulée
    # renvoyée garde ses dates. Rien n'est validé si QuickBooks refuse la
    # facture ; sans QuickBooks, rien n'est validé si le courriel échoue.
    if fa.status in _STATUTS_ENVOI:
        fa.issued_at = datetime.now(timezone.utc)
        appliquer_a_l_envoi(fa)
        await db.flush()


async def _preparer_l_envoi(db: AsyncSession, fa: Facture) -> bool:
    """Numéro définitif, dates d'envoi, puis QuickBooks, AVANT le rendu
    du PDF et le courriel.

    Renvoie True si QuickBooks a reçu la facture : la transaction est
    alors validée (numéro et lien QB restent même si le courriel échoue
    ensuite, le prochain envoi met à jour la même Invoice). False si
    QuickBooks n'est pas branché ici (staging, tests) : la facture part
    comme avant ; False aussi pour une facture annulée, que QuickBooks ne
    reçoit pas. Lève FactureBloqueeQB si le numéro ou QuickBooks bloque :
    rien n'est envoyé, la facture garde son statut (un brouillon reste un
    brouillon) et le motif est posé sur sa fiche."""
    from app.core.essai import EffetExterneBloque
    from app.services.facture_qbo import quickbooks_branche, sync_facture_to_qbo
    from app.services.qbo_auto_sync import verrou_facture

    if not quickbooks_branche():
        await _numeroter_et_dater(db, fa)
        return False
    facture_id = int(fa.id)
    # Une synchro QB à la fois par facture (push d'une modification,
    # filet horaire) ; commit DANS le verrou pour que la suivante relise
    # ce qui vient d'être enregistré.
    async with verrou_facture(facture_id):
        try:
            await _numeroter_et_dater(db, fa)
            # QuickBooks d'abord : il reçoit la facture avec ses lignes, sa
            # date et son échéance d'envoi. Un numéro qu'il a déjà pour une
            # autre facture est remplacé par le prochain libre ICI, avant le
            # PDF : le client reçoit le numéro de QuickBooks.
            res = await sync_facture_to_qbo(db, facture_id, avant_envoi=True)
        except EffetExterneBloque:
            # Mode essai de l'aperçu : réponse « rien n'est sorti » du
            # gestionnaire de l'application, pas un refus de QuickBooks.
            raise
        except Exception as exc:  # noqa: BLE001 — tout refus retient la facture
            reference = notes = statut = None
            try:
                reference, notes, statut = fa.reference, fa.internal_notes, fa.status
            except Exception:  # noqa: BLE001 — session déjà invalidée
                pass
            # Annulée AVANT d'écrire le motif : la ligne de la facture et le
            # compteur sont verrouillés par cette transaction, la session
            # fraîche les attendrait sans fin.
            await db.rollback()
            motif = str(exc).strip() or type(exc).__name__
            log.error(
                "Facture %s NON envoyée au client, QuickBooks ne l'a pas "
                "acceptée : %s",
                facture_id, motif,
            )
            await noter_envoi_bloque(
                facture_id, motif, reference=reference, notes=notes
            )
            raise FactureBloqueeQB(
                _message_bloquee(reference, statut, motif)
            ) from exc
        await db.commit()
    # Facture annulée renvoyée : QuickBooks n'y touche pas.
    return not (isinstance(res, dict) and res.get("skipped"))


def _message_bloquee(
    reference: Optional[str], statut: Optional[str], motif: str
) -> str:
    from app.services.numbering import is_provisional_facture_reference

    numero = (
        f" {reference}"
        if reference and not is_provisional_facture_reference(reference)
        else ""
    )
    if statut == FactureStatus.DRAFT.value:
        return (
            f"Facture{numero} non envoyée au client : QuickBooks ne l'a pas "
            f"acceptée ({motif_court(motif) or motif}). Elle reste en "
            "brouillon, le motif est affiché sur sa fiche."
        )
    return (
        f"Facture{numero} non renvoyée au client : QuickBooks ne l'a pas "
        f"acceptée ({motif_court(motif) or motif}). Le motif est affiché sur "
        "sa fiche."
    )


def _ref_courriel(fa: Facture) -> str:
    """Référence AFFICHABLE dans un courriel : jamais la référence
    provisoire « BR-… » (ceinture de sécurité — le numéro définitif est
    normalement attribué avant tout envoi, retour 2026-09-16)."""
    from app.services.numbering import is_provisional_facture_reference

    ref = (fa.reference or "").strip()
    if not ref or is_provisional_facture_reference(ref):
        log.error(
            "Facture %s : référence provisoire « %s » au moment de "
            "l'envoi — le numéro aurait dû être attribué avant.",
            fa.id, ref,
        )
        return ""
    return ref


def _default_subject(fa: Facture) -> str:
    ref = _ref_courriel(fa)
    return f"Facture {ref} — Horizon Services Immobiliers".strip(" —")


def _default_body_html(fa: Facture, intro: Optional[str]) -> str:
    intro_html = ""
    if intro:
        safe = intro.replace("\n", "<br>")
        intro_html = f"<p style=\"margin:0 0 16px 0\">{safe}</p>"
    total_line = ""
    if fa.total is not None:
        total_line = (
            f"<p style=\"margin:0 0 8px 0\"><strong>Total :</strong> "
            f"{float(fa.total):,.2f} $ CAD</p>".replace(",", " ")
        )
    due_line = ""
    if fa.due_at:
        due_line = (
            f"<p style=\"margin:0 0 8px 0\"><strong>Échéance :</strong> "
            f"{fa.due_at.date().isoformat()}</p>"
        )
    # Facture finale : bloc d'invitation à signer en ligne.
    sign_block = ""
    if fa.is_final and fa.signature_token:
        sign_url = f"{public_base()}/facture/{fa.signature_token}"
        sign_block = f"""\
  <p style="margin:8px 0 16px 0">
    Cette <strong>facture finale</strong> confirme l'achèvement des
    travaux de la soumission de base. Merci de la réviser et de la
    signer en ligne :
  </p>
  <p style="margin:0 0 6px 0">
    <a href="{sign_url}"
       style="display:inline-block;background:#d89b3c;color:#111;
              padding:12px 20px;border-radius:8px;font-weight:bold;
              text-decoration:none">Voir et signer la facture</a>
  </p>
  <p style="margin:0 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {sign_url}
  </p>"""
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p style="margin:0 0 16px 0">Bonjour,</p>
  {intro_html}
  <p style="margin:0 0 16px 0">
    Vous trouverez ci-joint la facture
    <strong>{_ref_courriel(fa) or ""}</strong>.
  </p>
  {total_line}
  {due_line}
  {sign_block}
  <p style="margin:16px 0 0 0">
    Merci de confirmer la réception. Pour toute question, n'hésitez pas
    à nous joindre.
  </p>
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers<br>
    RBQ 5868-5991-01<br>
    info@immohorizon.com &middot; immohorizon.com
  </p>
</div>
"""


async def send_facture(
    db: AsyncSession,
    facture_id: int,
    *,
    to: Iterable[str],
    cc: Optional[Iterable[str]] = None,
    subject: Optional[str] = None,
    message: Optional[str] = None,
    include_statement: bool = False,
) -> Facture:
    """Envoie la facture au client (PDF + courriel), après l'avoir fait
    accepter par QuickBooks (``_preparer_l_envoi``). Lève FactureBloqueeQB
    si QuickBooks la refuse : rien n'est envoyé. Valide (commit) la
    transaction de l'appelant dès que QuickBooks a accepté la facture."""
    mailer = get_mailer()
    if not mailer.ready:
        raise FactureSendError(
            "Microsoft Graph mailer is not configured (AZURE_* / MAIL_FROM_EMAIL)."
        )
    # Vérifié AVANT QuickBooks : rien n'y part si le courriel ne peut pas
    # partir.
    recipients = [a.strip() for a in to if a and a.strip()]
    if not recipients:
        raise FactureSendError("Au moins un destinataire est requis.")

    _fa0 = (
        await db.execute(select(Facture).where(Facture.id == facture_id))
    ).scalar_one_or_none()
    if _fa0 is None:
        raise FactureSendError(f"Facture {facture_id} introuvable.")
    _ref_avant = (_fa0.reference or "").strip()
    dans_qb = await _preparer_l_envoi(db, _fa0)
    # Un objet saisi à la main peut encore contenir la référence
    # PROVISOIRE (« Facture BR-0a7 ») : l'interface la pré-remplissait
    # avant l'attribution du numéro (retour 2026-09-24). On la remplace
    # par le numéro définitif — jamais de « BR-… » dans un courriel. Même
    # chose pour un numéro que QuickBooks avait déjà (renuméroté ci-dessus).
    if subject:
        from app.services.numbering import is_provisional_facture_reference

        _ref_apres = (_fa0.reference or "").strip()
        if _ref_avant and _ref_avant != _ref_apres:
            if is_provisional_facture_reference(_ref_avant):
                subject = subject.replace(_ref_avant, _ref_apres)
            else:
                subject = re.sub(
                    rf"(?<!\w){re.escape(_ref_avant)}(?!\w)",
                    lambda _m: _ref_apres,
                    subject,
                )
        if is_provisional_facture_reference(subject.replace("Facture ", "").strip()):
            subject = None

    rendered = await render_facture_pdf(
        db, facture_id, include_statement=include_statement,
    )
    if rendered is None:
        raise FactureSendError(f"Facture {facture_id} introuvable.")
    fa, pdf_bytes = rendered

    # Facture finale : jeton de signature généré au premier envoi
    # (jamais régénéré, pour ne pas invalider un lien déjà transmis).
    if fa.is_final and not fa.signature_token:
        fa.signature_token = secrets.token_urlsafe(32)
        await db.flush()

    cc_list = [a.strip() for a in (cc or []) if a and a.strip()]
    subj = subject or _default_subject(fa)
    body_html = _default_body_html(fa, message)
    attachment_name = (
        f"facture-{fa.reference}-avec-etat.pdf"
        if include_statement
        else f"facture-{fa.reference}.pdf"
    )
    attachment = EmailAttachment(
        name=attachment_name,
        content_bytes=pdf_bytes,
        content_type="application/pdf",
    )

    try:
        await mailer.send(
            to=recipients,
            subject=subj,
            html_body=body_html,
            cc=cc_list or None,
            reply_to=mailer.sender,
            attachments=[attachment],
        )
    except Exception as exc:
        log.exception("Graph send failed for facture %s", facture_id)
        raise FactureSendError(
            f"Envoi courriel échoué: {exc}"
            + (
                f" (la facture {fa.reference} est déjà dans QuickBooks : "
                "relance l'envoi, la même facture sera mise à jour)"
                if dans_qb
                else ""
            )
        ) from exc

    # Garde d'état : on ne (re)bascule en SENT que depuis un état
    # « ouvert » (brouillon / déjà envoyée / en retard). Renvoyer une
    # facture PAYÉE ou ANNULÉE n'écrase PAS son statut — sinon une
    # facture payée re-rentrerait dans le cron de relances (SENT/OVERDUE)
    # ou une facture VOID reviendrait active. Le courriel part toujours.
    if fa.status in _STATUTS_ENVOI:
        fa.status = FactureStatus.SENT.value
        await db.flush()

    # Facture d'un BON DE TRAVAIL envoyée au client → le bon passe en
    # « facturé » (kanban à jour), quel que soit son stade dans le
    # cycle interne (brouillon, accepté, planifié, à refacturer).
    # Annulé et statuts legacy signés ne bougent pas.
    # Bons IMPORTÉS dans cette facture (facturation multi-bons) : ils
    # passent « facturé » maintenant seulement — pas à l'import dans un
    # brouillon (Phil 2026-10-02).
    try:
        from app.models.bon_travail import (
            BonTravail as _BTi,
            BonTravailStatus as _BSti,
        )

        # SAVEPOINT : une erreur ici (ex. colonne pas encore ajoutée en
        # base) ne doit jamais avorter la transaction de l'envoi.
        async with db.begin_nested():
            for _bi in (
                await db.execute(
                    select(_BTi).where(
                        _BTi.facture_id == fa.id,
                        _BTi.status == _BSti.COMPLETE_A_REFACTURER.value,
                    )
                )
            ).scalars().all():
                _bi.status = _BSti.FACTURE.value
    except Exception:  # noqa: BLE001
        log.warning("Bons importés → facturé : échec pour la facture %s", fa.id, exc_info=True)

    try:
      async with db.begin_nested():
            if fa.project_id:
                from sqlalchemy import select as _sel_bt

                from app.models.bon_travail import (
                    BonTravail as _BT,
                    BonTravailStatus as _BSt,
                )

                for _b in (
                    await db.execute(
                        _sel_bt(_BT).where(
                            _BT.project_id == fa.project_id,
                            _BT.status.in_(
                                [
                                    _BSt.DRAFT.value,
                                    _BSt.ACCEPTE_A_PLANIFIER.value,
                                    _BSt.PLANIFIE.value,
                                    _BSt.COMPLETE_A_REFACTURER.value,
                                ]
                            ),
                        )
                    )
                ).scalars():
                    _b.status = _BSt.FACTURE.value
                await db.flush()
    except Exception:  # noqa: BLE001
        log.warning("Bons du projet → facturé : échec pour la facture %s", fa.id, exc_info=True)

    await db.refresh(fa)
    return fa
