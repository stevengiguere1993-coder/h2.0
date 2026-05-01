"""
Database session configuration for async SQLAlchemy.

Provides:
- Async engine configuration
- Session factory
- Dependency injection for FastAPI
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


# Create async engine
# Use async_database_url to ensure postgresql+asyncpg:// format
engine = create_async_engine(
    settings.async_database_url,
    echo=settings.is_development,  # Log SQL in development
    pool_pre_ping=True,  # Verify connections before use
    pool_size=5,
    max_overflow=10,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides an async database session.

    Usage in FastAPI:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...

    Yields:
        AsyncSession: Database session that auto-closes after use
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database tables.

    Note: In production, use Alembic migrations instead.
    This is primarily for development/testing.
    """
    from app.db.base import Base
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Idempotent column additions for schema evolutions where a new
        # column is added to an already-existing table. `create_all` only
        # creates missing tables, never alters existing ones, so we patch
        # those gaps here until we introduce Alembic migrations.
        additive_columns = (
            ("sous_traitants", "competence_rating", "INTEGER"),
            ("sous_traitants", "availability_rating", "INTEGER"),
            ("sous_traitants", "punctuality_rating", "INTEGER"),
            ("sous_traitants", "quality_rating", "INTEGER"),
            ("soumissions", "qbo_estimate_id", "VARCHAR(64)"),
            ("soumissions", "qbo_doc_number", "VARCHAR(64)"),
            ("soumissions", "qbo_sync_token", "VARCHAR(32)"),
            ("factures", "qbo_invoice_id", "VARCHAR(64)"),
            ("factures", "qbo_doc_number", "VARCHAR(64)"),
            ("factures", "qbo_sync_token", "VARCHAR(32)"),
            ("projects", "contact_request_id", "INTEGER"),
            ("projects", "soumission_id", "INTEGER"),
            ("projects", "status", "VARCHAR(32) NOT NULL DEFAULT 'planned'"),
            ("projects", "address", "VARCHAR(500)"),
            ("projects", "description", "TEXT"),
            ("projects", "notes", "TEXT"),
            ("projects", "start_date", "DATE"),
            ("projects", "end_date", "DATE"),
            ("projects", "budget", "NUMERIC(12, 2)"),
            ("projects", "updated_at", "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"),
            ("punches", "contact_request_id", "INTEGER"),
            ("clients", "email", "VARCHAR(320)"),
            ("clients", "phone", "VARCHAR(50)"),
            ("clients", "address", "VARCHAR(500)"),
            ("clients", "notes", "TEXT"),
            ("clients", "contact_request_id", "INTEGER"),
            ("achats", "receipt_image", "BYTEA"),
            ("achats", "receipt_image_content_type", "VARCHAR(100)"),
            ("factures", "last_reminder_at", "TIMESTAMP WITH TIME ZONE"),
            ("factures", "reminder_count", "INTEGER NOT NULL DEFAULT 0"),
            ("soumissions", "signature_token", "VARCHAR(64)"),
            ("soumissions", "signed_name", "VARCHAR(255)"),
            ("soumissions", "signed_ip", "VARCHAR(64)"),
            ("bons_travail", "signature_token", "VARCHAR(64)"),
            ("soumissions", "property_address", "VARCHAR(500)"),
            ("soumission_items", "tps_applicable", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("soumission_items", "tvq_applicable", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("soumission_items", "kind", "VARCHAR(16) NOT NULL DEFAULT 'service'"),
            ("contact_requests", "kanban_column", "VARCHAR(64)"),
            ("soumissions", "signature_image", "BYTEA"),
            ("soumissions", "signature_image_content_type", "VARCHAR(100)"),
            ("bons_travail", "signature_image", "BYTEA"),
            ("bons_travail", "signature_image_content_type", "VARCHAR(100)"),
            ("users", "role", "VARCHAR(16) NOT NULL DEFAULT 'employee'"),
            ("project_tasks", "phase_id", "INTEGER"),
            ("agenda_events", "contact_request_id", "INTEGER"),
            ("agenda_events", "reminder_sent_at", "TIMESTAMP WITH TIME ZONE"),
            ("agenda_events", "confirmation_sent_at", "TIMESTAMP WITH TIME ZONE"),
            ("soumission_items", "cost_per_unit", "NUMERIC(12, 2) NOT NULL DEFAULT 0"),
            ("service_templates", "default_cost_per_unit", "NUMERIC(12, 2)"),
            ("service_template_items", "default_cost_per_unit", "NUMERIC(12, 2) NOT NULL DEFAULT 0"),
            ("measurement_snapshots", "template_type", "VARCHAR(32)"),
            ("measurement_snapshots", "template_data_json", "TEXT"),
            ("users", "calendar_feed_token", "VARCHAR(64)"),
            (
                "users",
                "must_change_password",
                "BOOLEAN NOT NULL DEFAULT FALSE",
            ),
            ("soumissions", "client_note", "TEXT"),
            ("factures", "internal_notes", "TEXT"),
            ("factures", "client_note", "TEXT"),
            ("employes", "address", "VARCHAR(500)"),
            ("employes", "license_number", "VARCHAR(64)"),
            ("employes", "emergency_contact_name", "VARCHAR(255)"),
            ("employes", "emergency_contact_phone", "VARCHAR(50)"),
            (
                "employes",
                "is_ccq",
                "BOOLEAN NOT NULL DEFAULT FALSE",
            ),
            ("employes", "cnesst_rate", "NUMERIC(6, 4)"),
            ("employes", "ccq_rate", "NUMERIC(6, 4)"),
            ("employes", "employeur_d_url", "VARCHAR(500)"),
            ("project_phases", "assignee_employe_id", "INTEGER"),
            ("project_phases", "assignee_sous_traitant_id", "INTEGER"),
            ("projects", "estimated_hours_override", "NUMERIC(8, 2)"),
            # Auto-classification des achats QB par fournisseur.
            ("fournisseurs", "qbo_expense_account", "VARCHAR(255)"),
            (
                "leave_requests",
                "kind",
                "VARCHAR(16) NOT NULL DEFAULT 'vacation'",
            ),
            # QBO OAuth: colonnes ajoutées pour le flow /qbo/connect.
            ("qbo_tokens", "realm_id", "VARCHAR(64)"),
            ("qbo_tokens", "environment", "VARCHAR(16)"),
            ("qbo_tokens", "company_name", "VARCHAR(255)"),
            ("qbo_tokens", "connected_by_user_id", "INTEGER"),
            (
                "qbo_tokens",
                "connected_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            # Liaison client ↔ QBO Customer (push manuel + évite les
            # doublons à chaque re-push).
            ("clients", "qbo_customer_id", "VARCHAR(64)"),
            # Compteur PO + numérotation QBO sur les achats.
            (
                "numbering_counters",
                "next_po_number",
                "INTEGER NOT NULL DEFAULT 1",
            ),
            ("achats", "qbo_bill_id", "VARCHAR(64)"),
            ("achats", "qbo_doc_number", "VARCHAR(64)"),
            ("achats", "qbo_sync_token", "VARCHAR(32)"),
            # Workflow PO complet : assigné à l'employé qui va chercher
            # la marchandise + mode de paiement (routage QB Bill vs
            # Purchase).
            ("achats", "assigned_employe_id", "INTEGER"),
            ("achats", "payment_method", "VARCHAR(32)"),
            # Refonte PO/Achat (Avril 2026) — Achat = vraie transaction.
            ("achats", "purchase_order_id", "INTEGER"),
            ("achats", "supplier_invoice_number", "VARCHAR(64)"),
            ("achats", "invoice_date", "DATE"),
            ("achats", "paid_at", "TIMESTAMP WITH TIME ZONE"),
            # Prospection : scoring auto + tags.
            (
                "prospection_leads",
                "score",
                "INTEGER NOT NULL DEFAULT 0",
            ),
            ("prospection_leads", "tags", "TEXT"),
            # REQ : téléphone du siège social (du CSV REQ).
            ("req_companies", "telephone", "VARCHAR(32)"),
            # CRM : assignation d'un lead à un prospecteur.
            ("contact_requests", "assigned_to_user_id", "INTEGER"),
            # Prospection — données financières et fiscales.
            ("prospection_leads", "purchase_price", "NUMERIC(14, 2)"),
            ("prospection_leads", "purchase_date", "DATE"),
            ("prospection_leads", "mortgage_balance", "NUMERIC(14, 2)"),
            (
                "prospection_leads",
                "tax_delinquent",
                "BOOLEAN NOT NULL DEFAULT FALSE",
            ),
            ("prospection_leads", "tax_year_paid", "INTEGER"),
            ("prospection_leads", "tax_amount", "NUMERIC(10, 2)"),
            ("prospection_leads", "mailing_address", "VARCHAR(500)"),
            (
                "prospection_leads",
                "deal_strategy",
                "VARCHAR(16) NOT NULL DEFAULT 'undecided'",
            ),
            ("prospection_leads", "offer_amount", "NUMERIC(14, 2)"),
            ("prospection_leads", "assignment_price", "NUMERIC(14, 2)"),
            ("prospection_leads", "monday_item_id", "VARCHAR(32)"),
            # Multi-volet : un user peut avoir accès à construction,
            # prospection ou les deux. NULL = backward compat (tous).
            ("users", "volets_json", "TEXT"),
            # Agenda partagé entre volets : scope distingue les events
            # construction (par défaut) des events prospection.
            (
                "agenda_events",
                "scope",
                "VARCHAR(16) NOT NULL DEFAULT 'construction'",
            ),
            ("agenda_events", "lead_id", "INTEGER"),
            ("agenda_events", "assignee_user_id", "INTEGER"),
            # EvalWeb : propriétaires scrapés à la demande, cachés
            # par matricule pour éviter les re-scrapes.
            ("mtl_property_units", "owners_json", "TEXT"),
            ("mtl_property_units", "owners_fetched_at", "TIMESTAMP WITH TIME ZONE"),
            # Comparables loyers : enrichissements parser
            ("rental_listings", "quartier", "VARCHAR(64)"),
            (
                "rental_listings",
                "is_renovated",
                "BOOLEAN NOT NULL DEFAULT FALSE",
            ),
            # Agenda : permission spéciale d'assigner des RDV à d'autres
            # users (cas Zachary) + token pour le lien d'auto-confirmation
            # email.
            (
                "users",
                "can_assign_others",
                "BOOLEAN NOT NULL DEFAULT FALSE",
            ),
            ("users", "agenda_invite_token", "VARCHAR(64)"),
            # Préférence de thème portail. 'light' (noir sur blanc) =
            # défaut. 'dark' = blanc sur noir (legacy). N'affecte que
            # le portail interne — la landing publique reste dark.
            (
                "users",
                "theme_preference",
                "VARCHAR(8) NOT NULL DEFAULT 'light'",
            ),
            # AgendaEvent : champs pour l'invitation email + confirmation
            (
                "agenda_events",
                "invitation_sent_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            (
                "agenda_events",
                "invitation_confirmed_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            # Région pour distinguer MTL / Laval / Rive-Sud / Rive-Nord
            ("mtl_property_units", "region", "VARCHAR(16)"),
        )
        for table, column, col_type in additive_columns:
            await conn.execute(
                text(
                    f'ALTER TABLE {table} '
                    f'ADD COLUMN IF NOT EXISTS {column} {col_type}'
                )
            )

        # Backfill: any pre-existing user with is_admin=TRUE becomes
        # an "owner" so current sign-ins keep full access. Only runs
        # the first time; subsequent runs are harmless (no rows match).
        try:
            await conn.execute(
                text(
                    "UPDATE users SET role='owner' "
                    "WHERE is_admin=TRUE AND role='employee'"
                )
            )
        except Exception:
            pass

        # Élargit la colonne region de mtl_property_units si elle est
        # encore en VARCHAR(8) (legacy). 'mtl-island' fait 10 chars,
        # 'rive-nord' 9. ALTER COLUMN TYPE est idempotent en Postgres
        # quand la nouvelle taille est >= ancienne.
        try:
            await conn.execute(
                text(
                    "ALTER TABLE mtl_property_units "
                    "ALTER COLUMN region TYPE VARCHAR(32)"
                )
            )
        except Exception:
            pass

        # Élargit municipalite et code_utilisation pour accepter les
        # valeurs du rôle provincial MAMH : nom complet de municipalité
        # (« Sainte-Anne-des-Plaines » = 23 chars) au lieu du code 8
        # chars du feed Ville de Montréal, et codes d'utilisation
        # potentiellement alphanumériques.
        for column, new_type in (
            ("municipalite", "VARCHAR(128)"),
            ("code_utilisation", "VARCHAR(16)"),
        ):
            try:
                await conn.execute(
                    text(
                        f"ALTER TABLE mtl_property_units "
                        f"ALTER COLUMN {column} TYPE {new_type}"
                    )
                )
            except Exception:
                pass

        # Relaxations — columns whose nullability changed.
        # ALTER ... DROP NOT NULL is idempotent on PostgreSQL.
        for table, column in (
            ("projects", "client_id"),
            # Le modèle Achat ne sépare plus PO et achat ; le champ
            # reference n'est plus obligatoire.
            ("achats", "reference"),
        ):
            try:
                await conn.execute(
                    text(f'ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL')
                )
            except Exception:
                # Column may not exist yet on a brand-new DB — harmless.
                pass

        # Refonte PO/Achat (Avril 2026) : sépare proprement les bons
        # de commande (en planification) des achats (transactions
        # comptables). Migre les anciens « achats » qui étaient en
        # réalité des POs (status draft/ordered, jamais reçus) vers
        # la nouvelle table purchase_orders, puis les supprime de la
        # table achats. Idempotent : un second run ne trouve plus de
        # candidats à migrer.
        try:
            await conn.execute(
                text(
                    """
                    INSERT INTO purchase_orders (
                        reference, fournisseur_id, project_id,
                        assigned_employe_id, description, amount_max,
                        payment_method, status, sent_at, notes,
                        created_at, updated_at
                    )
                    SELECT
                        reference, fournisseur_id, project_id,
                        assigned_employe_id, description, amount,
                        payment_method,
                        CASE
                            WHEN status = 'ordered' THEN 'sent'
                            WHEN status = 'draft'   THEN 'draft'
                            ELSE 'cancelled'
                        END,
                        ordered_at, notes,
                        COALESCE(created_at, NOW()),
                        COALESCE(updated_at, NOW())
                    FROM achats
                    WHERE status IN ('draft', 'ordered')
                       OR (status = 'cancelled' AND received_at IS NULL)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    DELETE FROM achats
                    WHERE status IN ('draft', 'ordered')
                       OR (status = 'cancelled' AND received_at IS NULL)
                    """
                )
            )
        except Exception:
            # Tables ou colonnes absentes au tout premier boot — sera
            # ré-essayé au démarrage suivant.
            pass

        # Backfill des tables de jointure pour les assignations
        # multi-personnes sur phases et tâches. Idempotent : ON CONFLICT
        # DO NOTHING sur la contrainte d'unicité. Migre les assignations
        # historiques (1 personne max) vers le nouveau modèle (N).
        try:
            await conn.execute(
                text(
                    "INSERT INTO project_phase_assignees "
                    "(phase_id, employe_id, sous_traitant_id) "
                    "SELECT id, assignee_employe_id, NULL "
                    "FROM project_phases "
                    "WHERE assignee_employe_id IS NOT NULL "
                    "ON CONFLICT DO NOTHING"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO project_phase_assignees "
                    "(phase_id, employe_id, sous_traitant_id) "
                    "SELECT id, NULL, assignee_sous_traitant_id "
                    "FROM project_phases "
                    "WHERE assignee_sous_traitant_id IS NOT NULL "
                    "ON CONFLICT DO NOTHING"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO project_task_assignees "
                    "(task_id, employe_id, sous_traitant_id) "
                    "SELECT id, assignee_id, NULL "
                    "FROM project_tasks "
                    "WHERE assignee_id IS NOT NULL "
                    "ON CONFLICT DO NOTHING"
                )
            )
        except Exception:
            # Tables ou colonnes absentes lors du tout premier boot
            # (avant create_all) — harmless, le backfill retentera au
            # prochain démarrage.
            pass


async def close_db() -> None:
    """
    Close database connections.

    Should be called on application shutdown.
    """
    await engine.dispose()
