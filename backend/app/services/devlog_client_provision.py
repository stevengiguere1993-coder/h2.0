"""Provisioning client devlog à partir d'un lead.

Centralise la logique de conversion ``DevlogLead`` → ``DevlogClient``
qui était jusqu'ici dispersée entre l'endpoint
``POST /devlog/leads/{id}/convert`` et l'auto-flow d'acceptation de
soumission (``_ensure_client_for_soumission``). Un seul point d'entrée,
idempotent, audité.

Utilisé par :
  * ``POST /devlog/leads/{id}/convert`` — conversion explicite ;
  * ``_ensure_client_for_soumission`` — auto à l'acceptation d'une
    soumission ;
  * ``POST /devlog/soumissions`` (override) — auto à la création d'une
    soumission liée à un prospect, pour que la soumission finisse avec
    un ``client_id`` valide même en brouillon (sinon la fiche client
    n'affiche pas la soumission, car elle filtre sur ``client_id``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.models.devlog_client import DevlogClient
from app.models.devlog_lead import DevlogLead
from app.repositories.generic import GenericCrud
from app.services.audit import log_action


async def convert_lead_to_client(
    db,
    lead_id: int,
    *,
    user=None,
    audit_action: str = "devlog_lead.converted_to_client",
    audit_details_extra: Optional[dict] = None,
) -> Optional[DevlogClient]:
    """Convertit un lead en client (idempotent).

    * Si le lead n'existe pas → ``None``.
    * Si le lead a déjà un ``client_id`` qui pointe vers un client
      existant → retourne ce client tel quel (rien à faire).
    * Sinon : crée un ``DevlogClient`` à partir des champs du lead,
      remplit le lien bidirectionnel (``client.converted_from_lead_id``
      ↔ ``lead.client_id``), horodate ``client.converted_at``, met le
      lead en statut ``"won"`` et log l'action.

    ``audit_action`` permet aux callers de distinguer une conversion
    explicite (bouton "Convertir") d'une conversion implicite (création
    d'une soumission, acceptation, etc.). ``audit_details_extra`` est
    fusionné dans le payload du log (ex : ``{"soumission_id": 42}``).
    """
    lead = await GenericCrud(db, DevlogLead).get(lead_id)
    if lead is None:
        return None

    client_crud = GenericCrud(db, DevlogClient)
    if lead.client_id is not None:
        existing = await client_crud.get(lead.client_id)
        if existing is not None:
            return existing

    now = datetime.now(timezone.utc)
    client = DevlogClient(
        name=lead.name,
        company=lead.company,
        email=lead.email,
        phone=lead.phone,
        address=lead.address,
        notes=lead.project_summary,
        status="active",
        # Lien bidirectionnel prospect → client + horodatage de la
        # conversion. Permet a la fiche client d'afficher l'historique
        # complet (notes, soumissions, attachments du prospect) et le
        # badge "Prospect depuis ... Converti le ...".
        converted_from_lead_id=lead.id,
        converted_at=now,
    )
    db.add(client)
    await db.flush()
    await db.refresh(client)

    previous_lead_status = lead.status
    lead.client_id = client.id
    lead.status = "won"
    await db.flush()

    details: dict = {
        "lead_id": lead.id,
        "client_id": client.id,
        "previous_lead_status": previous_lead_status,
    }
    if audit_details_extra:
        details.update(audit_details_extra)

    try:
        await log_action(
            db,
            user=user,
            action=audit_action,
            entity_type="devlog_client",
            entity_id=client.id,
            details=details,
        )
    except Exception:
        # L'audit ne doit jamais empêcher la conversion (best-effort).
        pass

    return client

