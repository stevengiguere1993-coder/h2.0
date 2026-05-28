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
import re
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from app.api.deps import DBSession, RequireManager
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

    Bypass dev : si ``META_SKIP_SIGNATURE=1`` est posé, on accepte
    SANS vérifier. À utiliser UNIQUEMENT pour des tests manuels
    (replay curl avec un vrai leadgen_id) — JAMAIS en production
    long-terme, ça désactive la sécurité du webhook.
    """
    if (os.environ.get("META_SKIP_SIGNATURE") or "").strip() == "1":
        log.warning(
            "META_SKIP_SIGNATURE=1 — vérification HMAC désactivée "
            "(mode debug). Retire la variable d'env pour réactiver."
        )
        return True
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


def _normalize_field_name(s: str) -> str:
    """Normalise un nom (ou valeur) de champ pour matching robuste :
    bas-de-casse, accents stries, tout caractere non alphanumerique
    devient un underscore, runs d'underscores collapses.

    Ex: ``Quel type d'immeuble souhaitez-vous faire renover ?``
        -> ``quel_type_d_immeuble_souhaitez_vous_faire_renover``
    """
    import unicodedata

    no_accents = "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    ).lower()
    cleaned = "".join(c if c.isalnum() else "_" for c in no_accents)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


def _extract_field(
    field_data: List[Dict[str, Any]], *names: str
) -> Optional[str]:
    """Trouve dans ``field_data`` la premiere valeur dont le nom
    contient l'un des libelles donnes (match par sous-chaine sur
    nom normalise — accents stries, ponctuation -> underscore).

    Meta retourne ``field_data`` sous la forme
    ``[{"name": "...", "values": ["..."]}, ...]`` — les noms peuvent
    varier d'un formulaire a l'autre, parfois avec apostrophes /
    points d'interrogation / accents qui cassent le matching exact.
    """
    targets = [_normalize_field_name(n) for n in names if n]
    targets = [t for t in targets if t]
    for fd in field_data or []:
        norm = _normalize_field_name(fd.get("name") or "")
        if any(t in norm for t in targets):
            values = fd.get("values") or []
            if values:
                return str(values[0])
    return None


def _map_project_type(raw: Optional[str]) -> str:
    """Mappe une reponse texte FB/web vers une valeur de ProjectType.

    1. Lookup exact dans ``_PROJECT_TYPE_MAP`` apres normalisation.
    2. Heuristique : recherche de mots-cles (logement, duplex, cuisine,
       salle bain, etc.) dans la chaine normalisee.
    3. Defaut ``autre``.
    """
    if not raw:
        return ProjectType.AUTRE.value
    norm = _normalize_field_name(raw)
    if norm in _PROJECT_TYPE_MAP:
        return _PROJECT_TYPE_MAP[norm]
    # Heuristique mot-cle. Multilogement couvre toutes les options du
    # formulaire FB courant (duplex/triplex, 4-6 logements, etc.).
    if any(
        k in norm
        for k in ("logement", "duplex", "triplex", "immeuble", "multi")
    ):
        return ProjectType.MULTILOGEMENT.value
    if "salle" in norm and "bain" in norm:
        return ProjectType.SALLE_BAIN.value
    if "cuisine" in norm:
        return ProjectType.CUISINE.value
    if "complet" in norm:
        return ProjectType.RENOVATION_COMPLETE.value
    return ProjectType.AUTRE.value


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

            fields = _build_fields_from_lead_detail(
                detail, leadgen_id, value=value
            )
            cr = ContactRequest(
                **fields,
                locale="fr",
                source="facebook",
                gdpr_consent=True,
                marketing_consent=False,
                status=ContactRequestStatus.NEW.value,
            )
            db.add(cr)
            created += 1

    return {"received": created}


def _build_fields_from_lead_detail(
    detail: Dict[str, Any],
    leadgen_id: str,
    *,
    value: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Extrait + mappe les champs FB Lead Ads vers les colonnes d'un
    ContactRequest. Retourne un dict pret a appliquer (insert ou
    update). Utilise par le webhook initial et par l'endpoint de
    reprocess.
    """
    field_data = detail.get("field_data") or []
    value = value or {}

    # Coordonnees. Les variantes couvrent le formulaire site public
    # (full_name, email, phone) et le formulaire FB Lead Ads
    # francophone (nom_complet, e-mail, numero_de_telephone).
    name = (
        _extract_field(
            field_data, "nom_complet", "nom", "full_name", "name",
        )
        or "Lead Facebook"
    )
    email = (
        _extract_field(field_data, "e_mail", "email", "courriel") or ""
    )
    phone = (
        _extract_field(
            field_data,
            "numero_de_telephone", "numero_telephone",
            "telephone", "phone_number", "phone", "numero",
        )
        or ""
    )
    address = _extract_field(
        field_data, "adresse", "address", "street_address"
    )
    budget = _extract_field(field_data, "budget", "budget_range")

    # Type de projet : mapping explicite + heuristique de fallback.
    # Le formulaire FB courant ne propose que des options multilogement
    # (Duplex/Triplex, 4-6 logements, 7+ logements, plusieurs
    # immeubles) donc toute reponse contenant "logement", "duplex",
    # "triplex" ou "immeuble" tombe sur multilogement.
    pt_raw = _extract_field(
        field_data,
        "quel_type_d_immeuble",
        "type_d_immeuble",
        "type_de_projet",
        "type_projet",
        "project_type",
        "type_travaux",
    )
    project_type = _map_project_type(pt_raw)

    # Reponses qualifiantes (intention, urgence, decideur). On les
    # sort en tete du message pour qu'elles sautent aux yeux du
    # conseiller dans la fiche prospect.
    qualifiers: List[tuple[str, Optional[str]]] = [
        (
            "Propriétaire/décideur",
            _extract_field(
                field_data,
                "proprietaire_ou_decideur",
                "decideur",
                "proprietaire",
            ),
        ),
        ("Type d'immeuble", pt_raw),
        (
            "Intention",
            _extract_field(
                field_data,
                "qu_est_ce_qui_vous_amene",
                "intention",
            ),
        ),
        (
            "Échéancier",
            _extract_field(
                field_data,
                "quand_souhaiteriez_vous_demarrer",
                "quand_demarrer",
                "echeancier",
                "delai",
            ),
        ),
        (
            "Région",
            _extract_field(
                field_data, "dans_quel_region", "region",
            ),
        ),
    ]

    lines: List[str] = [
        "Demande captée via formulaire Facebook (Lead Ads).",
        "",
        "Qualification :",
    ]
    for label, val in qualifiers:
        if val:
            lines.append(f"- {label} : {val}")
    lines.append("")
    lines.append("Champs bruts :")
    for fd in field_data:
        fname = fd.get("name") or ""
        fvalues = fd.get("values") or []
        if fname and fvalues:
            lines.append(
                f"- {fname} : {', '.join(str(v) for v in fvalues)}"
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

    # Courriel synthetique si Facebook n'en fournit pas (rare).
    # Respecte la contrainte NOT NULL de la colonne et reste
    # identifiable cote CRM.
    if not email or "@" not in email:
        sanitized = (
            "".join(
                c for c in (phone or leadgen_id) if c.isalnum()
            )
            or leadgen_id
        )
        email = f"fb{sanitized}@facebook-lead.local"

    return {
        "name": name[:255],
        "email": email[:320],
        "phone": phone[:50] if phone else None,
        "address": address,
        "project_type": project_type,
        "budget_range": budget,
        "message": message[:5000],
    }


_LEADGEN_ID_RE = re.compile(r"\[leadgen_id=(\d+)\]")


@router.post("/facebook-lead/reprocess/{contact_request_id}")
async def reprocess_facebook_lead(
    contact_request_id: int,
    db: DBSession,
    user: RequireManager,
) -> dict:
    """Re-fetch le lead depuis Meta Graph API et re-applique le
    mapping courant sur le ``ContactRequest`` existant. Utile apres
    une mise a jour du mapping pour rafraichir un lead deja capte
    avec l'ancien code. Limite aux ``source=facebook`` qui contiennent
    encore leur ``leadgen_id`` dans le message.
    """
    cr = await db.get(ContactRequest, contact_request_id)
    if cr is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Prospect introuvable."
        )
    if cr.source != "facebook":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Ce prospect ne vient pas de Facebook.",
        )
    match = _LEADGEN_ID_RE.search(cr.message or "")
    if match is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "leadgen_id introuvable dans le message — impossible de "
            "re-fetcher depuis Meta.",
        )
    leadgen_id = match.group(1)

    detail = await _fetch_lead_detail(leadgen_id)
    if detail is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Echec du fetch Graph API — verifie META_PAGE_ACCESS_TOKEN "
            "et que le lead est toujours disponible cote Meta (90 jours).",
        )

    fields = _build_fields_from_lead_detail(detail, leadgen_id)
    for key, val in fields.items():
        setattr(cr, key, val)
    await db.flush()
    return {
        "reprocessed": True,
        "leadgen_id": leadgen_id,
        "contact_request_id": cr.id,
    }
