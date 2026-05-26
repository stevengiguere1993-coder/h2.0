"""Webhook Meta Lead Ads — leads Facebook → kanban prospects h2.0.

Quand un prospect remplit un formulaire de pub Facebook (Lead Ads),
Meta nous notifie sur ce webhook. On récupère le détail du lead via
Graph API puis on crée une ``ContactRequest`` dans le volet
construction (``source="facebook"``), ce qui le fait apparaître dans
le kanban des nouveaux prospects.

Variables d'env requises :
- ``META_VERIFY_TOKEN`` : chaîne aléatoire choisie par toi, donnée
  à Meta lors de l'enregistrement du webhook. Sert au handshake
  initial pour prouver que notre serveur est bien la destination
  attendue.
- ``META_PAGE_ACCESS_TOKEN`` : token long-lived de la Page Facebook
  avec la permission ``leads_retrieval``. Sert à récupérer le détail
  d'un lead depuis Graph API à partir de son ``leadgen_id``.
- ``META_APP_SECRET`` (recommandé) : secret de l'App Meta. Si
  défini, on vérifie la signature HMAC ``X-Hub-Signature-256`` de
  chaque webhook entrant — Meta seul peut la générer. Sans ce
  secret, on accepte sans vérifier (utile en mise en route, à
  configurer ensuite).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from app.api.deps import DBSession
from app.models.contact_request import (
    ContactRequest,
    ContactRequestStatus,
    ProjectType,
)


log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

META_GRAPH_BASE = "https://graph.facebook.com/v18.0"


@router.get("/facebook-lead")
async def verify_facebook_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
) -> Response:
    """Handshake Meta lors de l'enregistrement du webhook.

    Meta envoie un GET ``?hub.mode=subscribe&hub.verify_token=…&
    hub.challenge=…``. On retourne le challenge tel quel si le token
    correspond à ``META_VERIFY_TOKEN``, sinon 403.
    """
    expected = (os.environ.get("META_VERIFY_TOKEN") or "").strip()
    if (
        hub_mode == "subscribe"
        and expected
        and hub_verify_token == expected
    ):
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, detail="Verification failed."
    )


def _verify_signature(raw_body: bytes, signature_header: str) -> bool:
    """Vérifie la signature HMAC-SHA256 d'un webhook Meta.

    Meta envoie ``X-Hub-Signature-256: sha256=<hex>``. Sans
    ``META_APP_SECRET`` configuré, on accepte (mais on logge) — utile
    en mise en route. À configurer dès que possible.
    """
    secret = (os.environ.get("META_APP_SECRET") or "").strip()
    if not secret:
        log.warning(
            "META_APP_SECRET absent — webhook Meta accepté sans "
            "vérification de signature."
        )
        return True
    if not signature_header.startswith("sha256="):
        return False
    expected = signature_header[len("sha256=") :]
    computed = hmac.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, expected)


async def _fetch_lead_detail(leadgen_id: str) -> Optional[Dict[str, Any]]:
    """Récupère le détail d'un lead via Graph API. Retourne ``None``
    si la requête échoue — on logge et on continue le traitement des
    autres leads du payload."""
    token = (os.environ.get("META_PAGE_ACCESS_TOKEN") or "").strip()
    if not token:
        log.warning(
            "META_PAGE_ACCESS_TOKEN absent — impossible de fetcher "
            "le lead %s",
            leadgen_id,
        )
        return None
    url = f"{META_GRAPH_BASE}/{leadgen_id}"
    params = {
        "access_token": token,
        "fields": "id,created_time,ad_id,form_id,field_data",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as exc:
        # raise_for_status() inclut la full URL (avec ?access_token=…)
        # dans le message d'exception — on extrait juste le code de
        # statut + le body pour ne JAMAIS leaker le token dans les logs.
        body = ""
        try:
            body = exc.response.text[:300]
        except Exception:  # noqa: BLE001
            pass
        log.warning(
            "Fetch lead %s failed: HTTP %s — %s",
            leadgen_id,
            exc.response.status_code,
            body,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        # Pour les autres erreurs (timeout, DNS, etc.), on log la classe
        # d'exception seulement — pas str(exc) qui peut éventuellement
        # contenir l'URL avec le token.
        log.warning(
            "Fetch lead %s failed: %s", leadgen_id, type(exc).__name__
        )
        return None


def _extract_field(
    field_data: List[Dict[str, Any]], *names: str
) -> Optional[str]:
    """Trouve dans ``field_data`` la première valeur pour l'un des
    noms de champ donnés (insensible à la casse / séparateurs).

    Meta retourne ``field_data`` sous la forme
    ``[{"name": "...", "values": ["..."]}, ...]`` — les noms peuvent
    varier d'un formulaire à l'autre.
    """
    targets = {n.lower().replace("-", "_").replace(" ", "_") for n in names}
    for fd in field_data or []:
        raw = (fd.get("name") or "").lower()
        norm = raw.replace("-", "_").replace(" ", "_")
        if norm in targets or raw in targets:
            values = fd.get("values") or []
            if values:
                return str(values[0])
    return None


_PROJECT_TYPE_MAP = {
    "cuisine": ProjectType.CUISINE.value,
    "salle_bain": ProjectType.SALLE_BAIN.value,
    "salle_de_bain": ProjectType.SALLE_BAIN.value,
    "multilogement": ProjectType.MULTILOGEMENT.value,
    "complete": ProjectType.RENOVATION_COMPLETE.value,
    "renovation_complete": ProjectType.RENOVATION_COMPLETE.value,
}


@router.post("/facebook-lead", status_code=status.HTTP_200_OK)
async def receive_facebook_lead(
    request: Request, db: DBSession
) -> dict:
    """Reçoit les notifications Lead Ads de Meta et crée les
    ``ContactRequest`` correspondants dans le volet construction.

    Meta exige une réponse 200 rapide ; on traite la boucle puis on
    laisse le DBSession committer en fin de requête. La requête est
    idempotente : un ``leadgen_id`` déjà vu (Meta retransmet parfois)
    ne crée pas de doublon.
    """
    raw = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    if not _verify_signature(raw, signature):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Bad signature."
        )

    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Invalid JSON."
        )

    if (body.get("object") or "") != "page":
        return {"received": 0}

    created = 0
    for entry in body.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "leadgen":
                continue
            value = change.get("value") or {}
            leadgen_id = str(value.get("leadgen_id") or "").strip()
            if not leadgen_id:
                continue

            # Idempotence : si on a déjà créé un CR pour ce leadgen_id,
            # on saute. On reconnaît à la signature « [leadgen_id=…] »
            # qu'on ajoute à la fin du message.
            existing = (
                await db.execute(
                    select(ContactRequest)
                    .where(
                        ContactRequest.source == "facebook",
                        ContactRequest.message.contains(
                            f"[leadgen_id={leadgen_id}]"
                        ),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue

            detail = await _fetch_lead_detail(leadgen_id)
            if detail is None:
                # Pas de token ou fetch en échec : on logge et on
                # passe. L'opérateur pourra relancer manuellement.
                continue
            field_data = detail.get("field_data") or []

            name = (
                _extract_field(field_data, "full_name", "name")
                or "Lead Facebook"
            )
            email = _extract_field(field_data, "email") or ""
            phone = _extract_field(
                field_data, "phone_number", "phone"
            ) or ""
            address = _extract_field(
                field_data, "adresse", "address", "street_address"
            )
            project_type_raw = (
                _extract_field(
                    field_data,
                    "type_de_projet",
                    "type_projet",
                    "project_type",
                    "type_travaux",
                )
                or ""
            ).lower()
            budget = _extract_field(
                field_data, "budget", "budget_range"
            )

            # Message lisible pour la fiche kanban — on dump tous les
            # champs captés, dans leur ordre d'apparition.
            lines: List[str] = [
                "Demande captée via formulaire Facebook (Lead Ads)."
            ]
            for fd in field_data:
                fname = fd.get("name") or ""
                fvalues = fd.get("values") or []
                if fname and fvalues:
                    lines.append(
                        f"- {fname} : "
                        f"{', '.join(str(v) for v in fvalues)}"
                    )
            ad_id = detail.get("ad_id") or value.get("ad_id")
            form_id = detail.get("form_id") or value.get("form_id")
            if ad_id:
                lines.append(f"- ad_id : {ad_id}")
            if form_id:
                lines.append(f"- form_id : {form_id}")
            lines.append("")
            lines.append(f"[leadgen_id={leadgen_id}]")
            message = "\n".join(lines)

            # Courriel synthétique si Facebook n'en fournit pas
            # (rare). Respecte la contrainte NOT NULL de la colonne
            # et reste identifiable côté CRM.
            if not email or "@" not in email:
                sanitized = (
                    "".join(
                        c for c in (phone or leadgen_id) if c.isalnum()
                    )
                    or leadgen_id
                )
                email = f"fb{sanitized}@facebook-lead.local"

            project_type = _PROJECT_TYPE_MAP.get(
                project_type_raw.replace(" ", "_"),
                ProjectType.AUTRE.value,
            )

            cr = ContactRequest(
                name=name[:255],
                email=email[:320],
                phone=phone[:50] if phone else None,
                address=address,
                project_type=project_type,
                budget_range=budget,
                message=message[:5000],
                locale="fr",
                source="facebook",
                gdpr_consent=True,
                marketing_consent=False,
                status=ContactRequestStatus.NEW.value,
            )
            db.add(cr)
            created += 1

    return {"received": created}
