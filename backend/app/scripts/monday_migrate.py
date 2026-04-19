"""
One-shot Monday.com -> Postgres migration.

Reads the priority boards from both Horizon workspaces and upserts rows
into our own tables. Safe to re-run: every target has a stable
`(reference OR name)` key used for idempotency.

Invocation (Render cron or local):
    python -m app.scripts.monday_migrate

The script is intentionally conservative: it NEVER writes back to Monday.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select

from app.db.session import AsyncSessionLocal, close_db, init_db
from app.integrations.monday_client import MondayClient
from app.models.achat import Achat
from app.models.agenda_event import AgendaEvent
from app.models.bon_travail import BonTravail
from app.models.client import Client
from app.models.employe import Employe
from app.models.facture import Facture
from app.models.fournisseur import Fournisseur
from app.models.project import Project
from app.models.punch import Punch
from app.models.soumission import Soumission

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("monday_migrate")


# Board mapping - discovered during exploration
BOARDS = {
    # Horizon Construction
    "clients": 18398667742,
    "crm_soumissions": 18400565505,
    "devis_clients": 18399132469,
    "projets": 18398627396,
    "employes_partenaires": 18399095747,
    "agenda_equipe": 18399085942,
    "calendrier_construction": 18399084844,
    "bons_travail_master": 18398991355,
    "taches_terrain": 18398667794,
    "temps_punch": 18398991301,
    "facturation_client": 18398627138,
    "achats_po": 18399085935,
    # Horizon Services Immo
    "contacts": 7714696742,
    "sous_traitants": 18370835771,
    "suivi_heures": 18296007862,
    "prospection_deal": 7714284220,
}


# Characters stripped from numeric-looking Monday values.
_NUMERIC_STRIP = (",", "$", " ", "\u00a0", "\u202f")


def parse_numeric(val: Optional[str]) -> Optional[float]:
    if not val:
        return None
    cleaned = val
    for ch in _NUMERIC_STRIP:
        cleaned = cleaned.replace(ch, "")
    cleaned = cleaned.replace(",", ".").strip()
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def col_text(item: Dict[str, Any], column_id: str) -> Optional[str]:
    for c in item.get("column_values") or []:
        if c.get("id") == column_id:
            txt = c.get("text")
            return txt if txt else None
    return None


def col_any_text(item: Dict[str, Any], *column_ids: str) -> Optional[str]:
    """First non-empty text across a list of candidate column ids."""
    for cid in column_ids:
        v = col_text(item, cid)
        if v:
            return v
    return None


def parse_date(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


async def import_clients(session, items: List[Dict[str, Any]]) -> int:
    existing = {
        name.lower().strip(): c
        for c, in (await session.execute(select(Client))).all()
        for name in [c.name]
    }
    created = 0
    for it in items:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        if name.lower() in existing:
            continue
        session.add(Client(name=name))
        created += 1
    await session.flush()
    return created


async def import_employes(session, items: List[Dict[str, Any]], is_partner: bool = False) -> int:
    existing = {
        e.full_name.lower().strip()
        for e, in (await session.execute(select(Employe))).all()
    }
    created = 0
    for it in items:
        name = (it.get("name") or "").strip()
        if not name or name.lower() in existing:
            continue
        session.add(
            Employe(
                full_name=name,
                email=col_any_text(it, "email", "courriel"),
                phone=col_any_text(it, "phone", "telephone", "tel"),
                role=col_any_text(it, "role", "poste", "fonction"),
                is_partner=is_partner,
            )
        )
        created += 1
    await session.flush()
    return created


async def import_fournisseurs(session, items: List[Dict[str, Any]]) -> int:
    existing = {
        f.name.lower().strip()
        for f, in (await session.execute(select(Fournisseur))).all()
    }
    created = 0
    for it in items:
        name = (it.get("name") or "").strip()
        if not name or name.lower() in existing:
            continue
        session.add(
            Fournisseur(
                name=name,
                email=col_any_text(it, "email", "courriel"),
                phone=col_any_text(it, "phone", "telephone"),
                category=col_any_text(it, "category", "type"),
            )
        )
        created += 1
    await session.flush()
    return created


async def import_projets(session, items: List[Dict[str, Any]]) -> int:
    # Projects in our schema require a client; we create an "Import Monday"
    # placeholder client if none can be matched.
    placeholder = (
        await session.execute(select(Client).where(Client.name == "Import Monday"))
    ).scalar_one_or_none()
    if placeholder is None:
        placeholder = Client(name="Import Monday")
        session.add(placeholder)
        await session.flush()

    existing_names = {
        p.name.lower().strip()
        for p, in (await session.execute(select(Project))).all()
    }
    created = 0
    for it in items:
        name = (it.get("name") or "").strip()
        if not name or name.lower() in existing_names:
            continue
        session.add(Project(name=name, client_id=placeholder.id))
        created += 1
    await session.flush()
    return created


async def import_soumissions(session, items: List[Dict[str, Any]]) -> int:
    existing = {
        s.reference for s, in (await session.execute(select(Soumission))).all()
    }
    created = 0
    for it in items:
        monday_id = str(it.get("id"))
        reference = f"MND-{monday_id}"
        if reference in existing:
            continue
        total = parse_numeric(col_any_text(it, "total", "montant", "numbers"))
        session.add(
            Soumission(
                reference=reference,
                title=(it.get("name") or "Soumission")[:255],
                total=total,
                status="draft",
            )
        )
        created += 1
    await session.flush()
    return created


async def import_bons(session, items: List[Dict[str, Any]]) -> int:
    existing = {
        b.reference for b, in (await session.execute(select(BonTravail))).all()
    }
    created = 0
    for it in items:
        monday_id = str(it.get("id"))
        reference = f"BT-MND-{monday_id}"
        if reference in existing:
            continue
        session.add(
            BonTravail(
                reference=reference,
                title=(it.get("name") or "Bon de travail")[:255],
                amount=parse_numeric(col_any_text(it, "amount", "montant", "numbers")),
                status="draft",
            )
        )
        created += 1
    await session.flush()
    return created


async def import_factures(session, items: List[Dict[str, Any]]) -> int:
    existing = {f.reference for f, in (await session.execute(select(Facture))).all()}
    created = 0
    for it in items:
        monday_id = str(it.get("id"))
        reference = f"INV-MND-{monday_id}"
        if reference in existing:
            continue
        total = parse_numeric(col_any_text(it, "total", "montant", "numbers"))
        session.add(
            Facture(
                reference=reference,
                total=total,
                balance=total,
                status="draft",
            )
        )
        created += 1
    await session.flush()
    return created


async def import_achats(session, items: List[Dict[str, Any]]) -> int:
    existing = {a.reference for a, in (await session.execute(select(Achat))).all()}
    created = 0
    for it in items:
        monday_id = str(it.get("id"))
        reference = f"PO-MND-{monday_id}"
        if reference in existing:
            continue
        session.add(
            Achat(
                reference=reference,
                description=(it.get("name") or "")[:500],
                amount=parse_numeric(col_any_text(it, "amount", "montant", "numbers")),
                status="draft",
            )
        )
        created += 1
    await session.flush()
    return created


async def run() -> int:
    try:
        await init_db()
    except Exception as exc:
        log.warning("init_db soft-failed: %s", exc)

    try:
        async with MondayClient() as monday:
            report: Dict[str, int] = {}

            async def _import(board_name: str, board_id: int, importer) -> None:
                log.info("Fetching board %s (%s)", board_name, board_id)
                items = await monday.paged_items(board_id)
                log.info("  %d items retrieved", len(items))
                async with AsyncSessionLocal() as session:
                    created = await importer(session, items)
                    await session.commit()
                report[board_name] = created
                log.info("  %d new rows inserted", created)

            await _import("clients", BOARDS["clients"], import_clients)
            await _import("contacts", BOARDS["contacts"], import_clients)
            await _import("employes", BOARDS["employes_partenaires"],
                          lambda s, i: import_employes(s, i, is_partner=False))
            await _import("sous_traitants", BOARDS["sous_traitants"], import_fournisseurs)
            await _import("projets", BOARDS["projets"], import_projets)
            await _import("soumissions", BOARDS["crm_soumissions"], import_soumissions)
            await _import("devis", BOARDS["devis_clients"], import_soumissions)
            await _import("bons_travail", BOARDS["bons_travail_master"], import_bons)
            await _import("factures", BOARDS["facturation_client"], import_factures)
            await _import("achats", BOARDS["achats_po"], import_achats)

        log.info("Migration report: %s", json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        log.exception("Migration failed: %s", exc)
        return 1


def main() -> int:
    try:
        return asyncio.run(run())
    finally:
        try:
            asyncio.run(close_db())
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
