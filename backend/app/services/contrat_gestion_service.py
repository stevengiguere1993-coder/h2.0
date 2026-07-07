"""Logique métier du contrat de gestion : gabarit, valeurs, auto-remplissage.

- `get_template_markdown` : texte du gabarit courant (singleton DB, ou
  valeur d'amorçage par défaut en repli).
- `resolve_body_markdown` : corps figé (`corps_markdown`) si le contrat
  a été signé, sinon rendu à la volée depuis le gabarit courant + les
  valeurs du contrat.
- `autofill_values` : pré-remplit les 7 champs depuis (1) le dernier
  contrat de la même entreprise — pour « se souvenir » du siège, du
  district, etc. —, puis (2) l'Entreprise détentrice + son partenaire
  principal, puis (3) l'immeuble courant.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contrat_gestion import (
    ContratGestion,
    ContratGestionStatus,
    ContratGestionTemplate,
)
from app.models.entreprise import Entreprise, EntreprisePartner
from app.models.immobilier import Immeuble, ImmeubleOwnership
from app.services.contrat_gestion_template import (
    DEFAULT_TEMPLATE_MARKDOWN,
    MANDATAIRE_COURRIEL,
    MANDATAIRE_REPRESENTANT,
    immeubles_to_markdown,
    render_contrat_markdown,
)


_MONTHS_FR_CA = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def _date_fr(d: Optional[datetime]) -> str:
    if d is None:
        return ""
    dd = d.date() if isinstance(d, datetime) else d
    return f"{dd.day} {_MONTHS_FR_CA[dd.month - 1]} {dd.year}"


async def get_template_markdown(db: AsyncSession) -> str:
    tpl = (
        await db.execute(
            select(ContratGestionTemplate).where(ContratGestionTemplate.id == 1)
        )
    ).scalar_one_or_none()
    if tpl and tpl.corps_markdown and tpl.corps_markdown.strip():
        return tpl.corps_markdown
    return DEFAULT_TEMPLATE_MARKDOWN


async def resolve_body_markdown(db: AsyncSession, contrat: ContratGestion) -> str:
    """Corps rendu du contrat : snapshot figé si présent, sinon à la volée."""
    if contrat.corps_markdown and contrat.corps_markdown.strip():
        return contrat.corps_markdown
    template_md = await get_template_markdown(db)
    return render_body(template_md, contrat)


def render_body(template_md: str, contrat: ContratGestion) -> str:
    """Substitue les placeholders du gabarit avec les valeurs du contrat."""
    effective_date = contrat.signed_at or contrat.sent_at or datetime.now(timezone.utc)
    return render_contrat_markdown(
        template_md,
        compagnie=contrat.compagnie,
        siege_social=contrat.siege_social,
        representant=contrat.representant_nom,
        titre=contrat.representant_titre,
        immeubles=immeubles_to_markdown(contrat.immeubles_adresses),
        district=contrat.district_judiciaire,
        courriel=contrat.mandant_courriel,
        lieu=contrat.lieu_signature,
        date=_date_fr(effective_date),
    )


async def _immeuble(db: AsyncSession, immeuble_id: int) -> Optional[Immeuble]:
    return (
        await db.execute(select(Immeuble).where(Immeuble.id == immeuble_id))
    ).scalar_one_or_none()


async def _owner_entreprise_id(
    db: AsyncSession, immeuble: Immeuble
) -> Optional[int]:
    """Entreprise détentrice principale de l'immeuble."""
    row = (
        await db.execute(
            select(ImmeubleOwnership.entreprise_id)
            .where(ImmeubleOwnership.immeuble_id == immeuble.id)
            .order_by(ImmeubleOwnership.ownership_pct.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row or immeuble.owner_entreprise_id


async def autofill_values(db: AsyncSession, immeuble_id: int) -> dict:
    """Valeurs de pré-remplissage pour un nouveau contrat sur cet immeuble."""
    immeuble = await _immeuble(db, immeuble_id)
    if immeuble is None:
        return {}

    values: dict = {
        "immeubles_adresses": _immeuble_address_line(immeuble),
        "lieu_signature": immeuble.city or "",
        # Signataire MGV (Mandataire) — signe en premier. Pré-rempli,
        # éditable.
        "mandataire_nom": MANDATAIRE_REPRESENTANT,
        "mandataire_courriel": MANDATAIRE_COURRIEL,
    }

    entreprise_id = await _owner_entreprise_id(db, immeuble)
    values["entreprise_id"] = entreprise_id

    # (1) Se souvenir : dernier contrat de la même entreprise.
    if entreprise_id:
        last = (
            await db.execute(
                select(ContratGestion)
                .where(ContratGestion.entreprise_id == entreprise_id)
                .order_by(ContratGestion.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last is not None:
            for field in (
                "compagnie", "siege_social", "representant_nom",
                "representant_titre", "district_judiciaire",
                "mandant_courriel", "lieu_signature",
            ):
                val = getattr(last, field, None)
                if val:
                    values[field] = val

    # (2) Entreprise + partenaire principal (si pas déjà rempli).
    if entreprise_id:
        ent = (
            await db.execute(
                select(Entreprise).where(Entreprise.id == entreprise_id)
            )
        ).scalar_one_or_none()
        if ent and not values.get("compagnie"):
            values["compagnie"] = ent.name
        partner = (
            await db.execute(
                select(EntreprisePartner)
                .where(EntreprisePartner.entreprise_id == entreprise_id)
                .order_by(EntreprisePartner.ownership_pct.desc().nullslast())
                .limit(1)
            )
        ).scalar_one_or_none()
        if partner:
            if not values.get("representant_nom") and partner.partner_name:
                values["representant_nom"] = partner.partner_name
            if not values.get("mandant_courriel") and partner.partner_email:
                values["mandant_courriel"] = partner.partner_email
            if not values.get("representant_titre") and partner.role:
                values["representant_titre"] = _role_to_title(partner.role)

    return values


def _immeuble_address_line(immeuble: Immeuble) -> str:
    parts = [immeuble.address]
    tail = ", ".join(p for p in [immeuble.city, immeuble.postal_code] if p)
    if tail:
        parts.append(tail)
    return ", ".join(parts)


def _role_to_title(role: str) -> str:
    mapping = {
        "administrateur": "administrateur",
        "gerant": "gérant",
        "associe": "associé",
        "president": "président",
    }
    return mapping.get((role or "").lower(), role or "")
