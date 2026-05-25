"""Hook post-signature contrat — pôle Développement logiciel.

Quand un client signe électroniquement un contrat
(``POST /public/devlog/contracts/{token}/sign``), on déclenche en
best-effort 4 actions side-effect indépendantes :

    1. Email de bienvenue au client (Microsoft Graph)
    2. Notification Teams interne (webhook Adaptive Card)
    3. Création d'un repo GitHub privé pour le projet (REST API)
    4. Push QBO (client + estimate basée sur la soumission liée)

Chaque action est encapsulée dans son propre ``try/except`` : un échec
ne casse pas les autres, et surtout n'invalide jamais la signature
(qui est juridiquement engageante côté client). Les horodatages de
succès sont stockés sur ``DevlogContract`` (``welcome_email_sent_at``,
``teams_notified_at``, ``github_repo_url``, ``qbo_pushed_at``) — ce
qui rend le hook idempotent : ré-appeler ``on_contract_signed`` ne
relance que les actions encore non effectuées.

Toutes les actions sont aussi auditées via ``log_action`` (succès,
échec, skip).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.devlog_client import DevlogClient
from app.models.devlog_contract import DevlogContract
from app.models.devlog_project import DevlogProject
from app.models.devlog_soumission import DevlogSoumission
from app.services.audit import log_action


log = logging.getLogger(__name__)


# Domaine de production utilisé pour fabriquer les liens internes
# affichés dans la notification Teams (fiche projet, contrat, etc.).
_INTERNAL_BASE_URL = "https://kratos.immohorizon.com"


def _public_base_url() -> str:
    """URL publique côté frontend — alignée sur ``_public_base_url``
    dans ``endpoints/devlog.py``. Utilisée pour les liens internes vers
    la fiche projet / contrat dans la notification Teams.
    """
    return (
        os.getenv("PUBLIC_SITE_URL") or _INTERNAL_BASE_URL
    ).rstrip("/")


def _slugify(value: str) -> str:
    """Slugifie une chaîne pour usage dans un nom de repo GitHub.

    - lowercase + ASCII uniquement
    - séparateurs non-alphanum → '-'
    - dédoublonne les '-' consécutifs et trim '-' aux extrémités
    """
    if not value:
        return ""
    # Translittération basique pour conserver les accents fr → ASCII.
    try:
        import unicodedata

        value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    except Exception:  # noqa: BLE001
        pass
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value


async def _load_client(
    db: AsyncSession, contract: DevlogContract
) -> Optional[DevlogClient]:
    if contract.client_id is None:
        return None
    return (
        await db.execute(
            select(DevlogClient).where(DevlogClient.id == contract.client_id)
        )
    ).scalar_one_or_none()


async def _load_project(
    db: AsyncSession, contract: DevlogContract
) -> Optional[DevlogProject]:
    """Récupère le projet lié au contrat — soit via ``project_id``
    direct, soit via la soumission liée. Best-effort, peut retourner
    None (auquel cas on utilise le titre du contrat comme nom projet)."""
    if contract.project_id is not None:
        project = (
            await db.execute(
                select(DevlogProject).where(
                    DevlogProject.id == contract.project_id
                )
            )
        ).scalar_one_or_none()
        if project is not None:
            return project
    if contract.soumission_id is not None:
        project = (
            await db.execute(
                select(DevlogProject).where(
                    DevlogProject.soumission_id == contract.soumission_id
                )
            )
        ).scalar_one_or_none()
        if project is not None:
            return project
    return None


async def _load_soumission(
    db: AsyncSession, contract: DevlogContract
) -> Optional[DevlogSoumission]:
    if contract.soumission_id is None:
        return None
    return (
        await db.execute(
            select(DevlogSoumission).where(
                DevlogSoumission.id == contract.soumission_id
            )
        )
    ).scalar_one_or_none()


# ----------------------------------------------------------------------
# 1) Email de bienvenue au client
# ----------------------------------------------------------------------


async def _send_welcome_email(
    db: AsyncSession,
    contract: DevlogContract,
    client: Optional[DevlogClient],
    project_name: str,
) -> None:
    """Email court à l'adresse du client signataire — best-effort."""
    if getattr(contract, "welcome_email_sent_at", None) is not None:
        log.info(
            "welcome email already sent for contract %s — skip", contract.id
        )
        return

    to_email = client.email if client else None
    if not to_email:
        log.info(
            "welcome email skipped for contract %s — no client email",
            contract.id,
        )
        await log_action(
            db,
            user=None,
            action="devlog_contract.welcome_email.skipped",
            entity_type="devlog_contract",
            entity_id=contract.id,
            details={"reason": "no_client_email"},
        )
        return

    try:
        from app.integrations.email_graph import get_mailer

        mailer = get_mailer()
        if not mailer.ready:
            log.info(
                "welcome email skipped for contract %s — mailer not configured",
                contract.id,
            )
            await log_action(
                db,
                user=None,
                action="devlog_contract.welcome_email.skipped",
                entity_type="devlog_contract",
                entity_id=contract.id,
                details={"reason": "mailer_not_configured"},
            )
            return

        first_name = ((client.name or "").split(" ")[0] if client else "") or "bonjour"
        signed_name = contract.signed_name or (client.name if client else "")
        company = client.company if client else None
        company_line = f" pour {company}" if company else ""

        # Récap des prochaines étapes — adapté selon que le dépôt est
        # déjà payé ou pas (le contrat peut être signé AVANT ou APRÈS
        # le dépôt).
        if contract.deposit_paid_at is None and contract.deposit_required_cents:
            amount_str = f"{contract.deposit_required_cents / 100:,.2f} $"
            next_steps_html = f"""
              <li><strong>Dépôt initial</strong> : {amount_str} à verser pour
              déclencher le démarrage des travaux.</li>
              <li><strong>Kick-off</strong> : rencontre de lancement
              planifiée dès réception du dépôt.</li>
              <li><strong>Suivi</strong> : un membre de l'équipe te
              contactera pour caler les modalités de communication
              (Teams, courriel, point hebdo).</li>
            """
        else:
            next_steps_html = """
              <li><strong>Kick-off</strong> : rencontre de lancement
              planifiée dans les prochains jours.</li>
              <li><strong>Suivi</strong> : un membre de l'équipe te
              contactera pour caler les modalités de communication
              (Teams, courriel, point hebdo).</li>
              <li><strong>Livraisons</strong> : on partagera les
              jalons du projet et les premiers livrables au fur et à
              mesure.</li>
            """

        html = f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p>Bonjour {first_name},</p>
  <p>Merci d'avoir signé le contrat <strong>{contract.title}</strong>{company_line}.
  Toute l'équipe d'Horizon Services Immobiliers est ravie de démarrer
  <strong>{project_name}</strong> avec toi.</p>

  <p><strong>Prochaines étapes :</strong></p>
  <ul>
    {next_steps_html}
  </ul>

  <p style="font-size:13px;color:#555">
    Une copie signée du contrat est disponible sur ton lien personnel.
    Pour toute question, réponds simplement à ce courriel — il atterrira
    directement chez l'équipe.
  </p>

  <p style="margin-top:24px">À très vite,<br>
    L'équipe Horizon Services Immobiliers
  </p>

  <p style="margin-top:24px;color:#888;font-size:12px">
    Horizon Services Immobiliers<br>
    RBQ 5868-5991-01 — info@immohorizon.com
  </p>
</div>
"""
        subject = (
            f"Bienvenue chez Horizon — votre projet {project_name} démarre !"
        )
        await mailer.send(to=[to_email], subject=subject, html_body=html)
        contract.welcome_email_sent_at = datetime.now(timezone.utc)
        await db.flush()
        log.info(
            "welcome email sent to %s for contract %s", to_email, contract.id
        )
        await log_action(
            db,
            user=None,
            action="devlog_contract.welcome_email.sent",
            entity_type="devlog_contract",
            entity_id=contract.id,
            details={
                "to": to_email,
                "signed_name": signed_name,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "welcome email failed for contract %s: %s", contract.id, exc
        )
        await log_action(
            db,
            user=None,
            action="devlog_contract.welcome_email.failed",
            entity_type="devlog_contract",
            entity_id=contract.id,
            details={"error": str(exc)[:500]},
        )


# ----------------------------------------------------------------------
# 2) Notification Teams (webhook Adaptive Card)
# ----------------------------------------------------------------------


async def _notify_teams(
    db: AsyncSession,
    contract: DevlogContract,
    client: Optional[DevlogClient],
    project_name: str,
    soumission: Optional[DevlogSoumission],
) -> None:
    """POST sur le webhook Teams configuré via ``TEAMS_WEBHOOK_URL_DEVLOG``.

    Si la variable d'env n'est pas définie : no-op silencieux + log info.
    Si le POST échoue : warning + audit log, mais on continue. La carte
    est minimaliste (titre + faits client/projet/montant + lien fiche).
    """
    if getattr(contract, "teams_notified_at", None) is not None:
        log.info(
            "teams notif already sent for contract %s — skip", contract.id
        )
        return

    webhook_url = os.getenv("TEAMS_WEBHOOK_URL_DEVLOG")
    if not webhook_url:
        log.info(
            "teams notif skipped for contract %s — no webhook configured",
            contract.id,
        )
        await log_action(
            db,
            user=None,
            action="devlog_contract.teams_notify.skipped",
            entity_type="devlog_contract",
            entity_id=contract.id,
            details={"reason": "no_webhook"},
        )
        return

    try:
        client_name = (client.name if client else None) or "Client inconnu"
        company = client.company if client else None
        amount_str: Optional[str] = None
        if soumission is not None and soumission.amount is not None:
            try:
                amount_str = f"{float(soumission.amount):,.2f} $"
            except (TypeError, ValueError):
                amount_str = None
        base = _public_base_url()
        contract_link = f"{base}/fr/app/dev-logiciel/contrats/{contract.id}"

        facts = [
            {"name": "Client", "value": client_name},
        ]
        if company:
            facts.append({"name": "Entreprise", "value": company})
        facts.append({"name": "Projet", "value": project_name})
        facts.append({"name": "Contrat", "value": f"#{contract.id} — {contract.title}"})
        if amount_str:
            facts.append({"name": "Montant", "value": amount_str})
        if contract.signed_name:
            facts.append({"name": "Signé par", "value": contract.signed_name})

        # On utilise le format MessageCard classique (encore supporté par
        # Teams webhooks Office 365), plus tolérant que les Adaptive Cards
        # pour un webhook entrant simple.
        card = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": f"Contrat signé — {client_name}",
            "themeColor": "0E7C66",
            "title": f"Contrat signé — {client_name}",
            "sections": [
                {
                    "activityTitle": project_name,
                    "activitySubtitle": (
                        f"Signé le {contract.signed_at.strftime('%d/%m/%Y %H:%M')}"
                        if contract.signed_at
                        else "Signé à l'instant"
                    ),
                    "facts": facts,
                    "markdown": True,
                }
            ],
            "potentialAction": [
                {
                    "@type": "OpenUri",
                    "name": "Ouvrir la fiche contrat",
                    "targets": [{"os": "default", "uri": contract_link}],
                }
            ],
        }

        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(webhook_url, json=card)
            if r.status_code >= 400:
                raise RuntimeError(
                    f"Teams webhook returned {r.status_code}: {r.text[:200]}"
                )

        contract.teams_notified_at = datetime.now(timezone.utc)
        await db.flush()
        log.info("teams notif sent for contract %s", contract.id)
        await log_action(
            db,
            user=None,
            action="devlog_contract.teams_notify.sent",
            entity_type="devlog_contract",
            entity_id=contract.id,
            details={"client": client_name, "amount": amount_str},
        )
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "teams notif failed for contract %s: %s", contract.id, exc
        )
        await log_action(
            db,
            user=None,
            action="devlog_contract.teams_notify.failed",
            entity_type="devlog_contract",
            entity_id=contract.id,
            details={"error": str(exc)[:500]},
        )


# ----------------------------------------------------------------------
# 3) Création d'un repo GitHub privé
# ----------------------------------------------------------------------


def _build_repo_name(
    client: Optional[DevlogClient],
    project_name: str,
    contract_id: int,
) -> str:
    """Format : ``client-{slug_client}-{slug_project}-{contract_id}``,
    tronqué à 100 chars (limite GitHub) en gardant le suffixe id pour
    garantir l'unicité.
    """
    client_part = ""
    if client is not None:
        client_part = _slugify(client.company or client.name or "")
    if not client_part:
        client_part = "sans-client"
    project_part = _slugify(project_name) or "projet"
    suffix = f"-{contract_id}"
    # Budget des 100 chars : prefix "client-" (7) + suffix.
    budget = 100 - len("client-") - len(suffix)
    middle = f"{client_part}-{project_part}"
    if len(middle) > budget:
        middle = middle[:budget].rstrip("-")
    name = f"client-{middle}{suffix}"
    return name


async def _create_github_repo(
    db: AsyncSession,
    contract: DevlogContract,
    client: Optional[DevlogClient],
    project_name: str,
) -> None:
    """Crée un repo GitHub privé pour le projet client.

    Settings :
      * ``GITHUB_AUTOMATION_TOKEN`` — PAT avec scope ``repo``
      * ``GITHUB_AUTOMATION_ORG`` — si défini, crée le repo dans
        l'organisation au lieu du compte personnel

    Si ``GITHUB_AUTOMATION_TOKEN`` est absent → no-op silencieux.
    Si le POST échoue (409 nom déjà pris, 401 token invalide, etc.) →
    warning + audit log, mais on continue. En cas de succès on stocke
    l'URL HTML sur ``contract.github_repo_url``.
    """
    if getattr(contract, "github_repo_url", None):
        log.info(
            "github repo already provisioned for contract %s — skip",
            contract.id,
        )
        return

    token = os.getenv("GITHUB_AUTOMATION_TOKEN")
    if not token:
        log.info(
            "github repo creation skipped for contract %s — no token",
            contract.id,
        )
        await log_action(
            db,
            user=None,
            action="devlog_contract.github_repo.skipped",
            entity_type="devlog_contract",
            entity_id=contract.id,
            details={"reason": "no_token"},
        )
        return

    org = os.getenv("GITHUB_AUTOMATION_ORG") or None
    repo_name = _build_repo_name(client, project_name, contract.id)
    client_name = (client.name if client else None) or "client"
    description = f"Projet {project_name} pour {client_name}"

    url = (
        f"https://api.github.com/orgs/{org}/repos"
        if org
        else "https://api.github.com/user/repos"
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={
                    "name": repo_name,
                    "private": True,
                    "description": description[:350],
                    "auto_init": True,
                },
            )
            if r.status_code >= 400:
                raise RuntimeError(
                    f"GitHub API {r.status_code}: {r.text[:300]}"
                )
            data = r.json()

        html_url = data.get("html_url") or ""
        if html_url and hasattr(contract, "github_repo_url"):
            contract.github_repo_url = html_url[:512]
            await db.flush()

        log.info(
            "github repo %s created for contract %s", html_url, contract.id
        )
        await log_action(
            db,
            user=None,
            action="devlog_contract.github_repo.created",
            entity_type="devlog_contract",
            entity_id=contract.id,
            details={
                "repo_name": repo_name,
                "html_url": html_url,
                "org": org,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "github repo creation failed for contract %s: %s",
            contract.id,
            exc,
        )
        await log_action(
            db,
            user=None,
            action="devlog_contract.github_repo.failed",
            entity_type="devlog_contract",
            entity_id=contract.id,
            details={
                "repo_name": repo_name,
                "error": str(exc)[:500],
            },
        )


# ----------------------------------------------------------------------
# 4) Push QBO (client + estimate)
# ----------------------------------------------------------------------


async def _push_to_qbo(
    db: AsyncSession,
    contract: DevlogContract,
    client: Optional[DevlogClient],
    soumission: Optional[DevlogSoumission],
) -> None:
    """Push best-effort vers QuickBooks Online.

    Stratégie pragmatique pour ce premier jet :
      * Si une soumission est liée → on crée le client + une estimate
        QBO basique avec le montant total de la soumission (une ligne
        unique « {titre de la soumission} »). On NE clone PAS le détail
        des items (la soumission devlog a un format spécifique
        ``devis_dev`` avec marges circulaires + sections mensuel /
        mise en oeuvre — un mapping ligne-à-ligne fidèle exige un
        chantier dédié).
      * Sans soumission → on ne crée que le client (ensure_customer).

    Toute l'intégration QBO existante est réutilisée
    (``app.integrations.quickbooks.get_qbo``). Si QBO n'est pas
    configuré (token / realm absents) → log + audit ``qbo_push_pending``
    pour marquer la dette, et on continue.
    """
    if getattr(contract, "qbo_pushed_at", None) is not None:
        log.info("qbo push already done for contract %s — skip", contract.id)
        return

    try:
        from app.integrations.quickbooks import (
            QuickBooksError,
            get_qbo,
        )

        qbo = get_qbo()
        # Charge les tokens persistés (pattern aligné sur
        # ``soumission_qbo.sync_soumission_to_qbo``).
        await qbo._load_refresh_from_db()
        if not qbo.ready:
            log.info(
                "qbo push pending for contract %s — qbo not configured",
                contract.id,
            )
            await log_action(
                db,
                user=None,
                action="devlog_contract.qbo_push_pending",
                entity_type="devlog_contract",
                entity_id=contract.id,
                details={
                    "reason": "qbo_not_configured",
                    "note": (
                        "QBO push stub — intégration complète à valider "
                        "avec Phil/Michael avant prod."
                    ),
                },
            )
            return

        # 1) Customer.
        display_name = (
            (client.company if client else None)
            or (client.name if client else None)
            or contract.title
        )
        email = client.email if client else None
        phone = client.phone if client else None
        address = client.address if client else None

        customer = await qbo.ensure_customer(
            display_name=display_name[:100],
            email=email,
            phone=phone,
            billing_address=address,
        )
        customer_id = str(customer.get("Id") or "")
        if not customer_id:
            raise QuickBooksError(
                "QBO customer creation did not return an Id."
            )

        estimate_id: Optional[str] = None
        doc_number: Optional[str] = None

        # 2) Estimate (best-effort, seulement si on a un montant).
        if soumission is not None and soumission.amount is not None:
            try:
                amount = round(float(soumission.amount), 2)
            except (TypeError, ValueError):
                amount = 0.0
            if amount > 0:
                line_name = (
                    (soumission.title or contract.title or "Projet")
                    .strip()[:100]
                )
                qbo_item = await qbo.ensure_item(
                    line_name, description=soumission.title
                )
                item_id = str(qbo_item.get("Id") or "")
                line: dict = {
                    "DetailType": "SalesItemLineDetail",
                    "Amount": amount,
                    "Description": (
                        soumission.title or contract.title or "Projet"
                    )[:4000],
                    "SalesItemLineDetail": {
                        "Qty": 1,
                        "UnitPrice": amount,
                    },
                }
                if item_id:
                    line["SalesItemLineDetail"]["ItemRef"] = {"value": item_id}
                payload = {
                    "CustomerRef": {"value": customer_id},
                    "Line": [line],
                    "TxnDate": datetime.now(timezone.utc).date().isoformat(),
                    "PrivateNote": (
                        f"Push automatique post-signature contrat "
                        f"#{contract.id} ({contract.title})."
                    )[:4000],
                }
                estimate = await qbo.create_estimate(payload)
                estimate_id = str(estimate.get("Id") or "") or None
                doc_number = str(estimate.get("DocNumber") or "") or None

        contract.qbo_pushed_at = datetime.now(timezone.utc)
        await db.flush()
        log.info(
            "qbo push ok for contract %s (customer=%s estimate=%s)",
            contract.id,
            customer_id,
            estimate_id,
        )
        await log_action(
            db,
            user=None,
            action="devlog_contract.qbo_push.sent",
            entity_type="devlog_contract",
            entity_id=contract.id,
            details={
                "qbo_customer_id": customer_id,
                "qbo_estimate_id": estimate_id,
                "qbo_doc_number": doc_number,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("qbo push failed for contract %s: %s", contract.id, exc)
        await log_action(
            db,
            user=None,
            action="devlog_contract.qbo_push.failed",
            entity_type="devlog_contract",
            entity_id=contract.id,
            details={"error": str(exc)[:500]},
        )


# ----------------------------------------------------------------------
# Orchestrateur public
# ----------------------------------------------------------------------


async def on_contract_signed(
    contract: DevlogContract,
    db: AsyncSession,
) -> None:
    """Déclenche les 4 actions side-effect post-signature contrat.

    Chaque action est encapsulée dans son propre ``try/except`` — un
    échec ne casse pas les autres. La fonction ne lève jamais : si
    l'orchestration elle-même crash (improbable), on log et on
    retourne. La signature reste juridiquement valide quoi qu'il
    arrive.
    """
    try:
        client = await _load_client(db, contract)
        project = await _load_project(db, contract)
        soumission = await _load_soumission(db, contract)
        project_name = (
            (project.name if project else None)
            or contract.title
            or "Projet logiciel"
        )

        # 1) Email de bienvenue au client.
        try:
            await _send_welcome_email(db, contract, client, project_name)
        except Exception:  # noqa: BLE001
            log.exception(
                "welcome email step crashed for contract %s", contract.id
            )

        # 2) Notification Teams.
        try:
            await _notify_teams(
                db, contract, client, project_name, soumission
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "teams notify step crashed for contract %s", contract.id
            )

        # 3) Création repo GitHub.
        try:
            await _create_github_repo(db, contract, client, project_name)
        except Exception:  # noqa: BLE001
            log.exception(
                "github repo step crashed for contract %s", contract.id
            )

        # 4) Push QBO.
        try:
            await _push_to_qbo(db, contract, client, soumission)
        except Exception:  # noqa: BLE001
            log.exception(
                "qbo push step crashed for contract %s", contract.id
            )
    except Exception:  # noqa: BLE001
        # Garde-fou : on ne laisse jamais remonter une exception qui
        # empêcherait la signature de réussir côté caller.
        log.exception(
            "on_contract_signed crashed for contract %s", contract.id
        )
