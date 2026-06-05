"""
Database session configuration for async SQLAlchemy.

Provides:
- Async engine configuration
- Session factory
- Dependency injection for FastAPI
"""

from collections.abc import AsyncGenerator
from typing import Optional

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


def _rotate_receipt_blob_cw90(blob: bytes, content_type: str) -> Optional[bytes]:
    """Fait pivoter de 90° HORAIRE (vers la droite) un reçu stocké.
    Délègue au service partagé. Retourne None si format inconnu / échec."""
    from app.services.receipt_rotate import rotate_receipt_blob

    return rotate_receipt_blob(blob, content_type, clockwise=True)


async def _rotate_existing_receipts_cw90(conn) -> int:
    """Pivote (une seule fois) tous les reçus d'achat déjà stockés.
    Traite un reçu à la fois pour limiter la mémoire. Retourne le
    nombre de reçus effectivement pivotés."""
    from sqlalchemy import text

    ids = (
        await conn.execute(
            text(
                "SELECT id FROM achats WHERE receipt_image IS NOT NULL"
            )
        )
    ).all()
    rotated = 0
    for (rid,) in ids:
        # Chaque reçu est indépendant : une erreur isolée ne doit pas
        # interrompre le passage (sinon des reçus seraient pivotés sans
        # que le marqueur soit posé → double rotation au boot suivant).
        try:
            row = (
                await conn.execute(
                    text(
                        "SELECT receipt_image, receipt_image_content_type "
                        "FROM achats WHERE id = :id"
                    ),
                    {"id": rid},
                )
            ).first()
            if row is None or row[0] is None:
                continue
            new_blob = _rotate_receipt_blob_cw90(bytes(row[0]), row[1] or "")
            if new_blob is None:
                continue
            await conn.execute(
                text("UPDATE achats SET receipt_image = :img WHERE id = :id"),
                {"img": new_blob, "id": rid},
            )
            rotated += 1
        except Exception:
            continue
    return rotated


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
            ("sous_traitants", "region", "VARCHAR(255)"),
            ("fournisseurs", "payment_terms_days", "INTEGER"),
            ("fournisseurs", "address", "VARCHAR(500)"),
            ("fournisseurs", "qbo_vendor_id", "VARCHAR(64)"),
            ("achats", "due_at", "TIMESTAMP WITH TIME ZONE"),
            ("achats", "qbo_bill_payment_id", "VARCHAR(64)"),
            ("factures", "next_reminder_at", "TIMESTAMP WITH TIME ZONE"),
            ("voice_calls", "verbatim_transcript", "TEXT"),
            ("imm_immeubles", "urgence_phone", "VARCHAR(32)"),
            ("soumissions", "qbo_estimate_id", "VARCHAR(64)"),
            ("soumissions", "qbo_doc_number", "VARCHAR(64)"),
            ("soumissions", "qbo_sync_token", "VARCHAR(32)"),
            (
                "soumissions",
                "client_opened_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            (
                "soumissions",
                "client_last_opened_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            (
                "soumissions",
                "client_open_count",
                "INTEGER NOT NULL DEFAULT 0",
            ),
            (
                "soumissions",
                "contractor_opened_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            (
                "soumissions",
                "contractor_last_opened_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            (
                "soumissions",
                "contractor_open_count",
                "INTEGER NOT NULL DEFAULT 0",
            ),
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
            ("clients", "language", "VARCHAR(8) NOT NULL DEFAULT 'fr'"),
            ("clients", "is_company", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("clients", "representative", "VARCHAR(255)"),
            ("project_phase_assignees", "hourly_billed", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("project_phase_assignees", "worker_count", "INTEGER NOT NULL DEFAULT 1"),
            ("achats", "receipt_image", "BYTEA"),
            ("achats", "receipt_image_content_type", "VARCHAR(100)"),
            ("achats", "amount_tps", "NUMERIC(12,2)"),
            ("achats", "amount_tvq", "NUMERIC(12,2)"),
            ("factures", "last_reminder_at", "TIMESTAMP WITH TIME ZONE"),
            ("factures", "reminder_count", "INTEGER NOT NULL DEFAULT 0"),
            # FactureItem.kind — service|extra|rabais|frais. « extra » =
            # hors soumission, ne réduit pas le « reste à facturer ».
            (
                "facture_items",
                "kind",
                "VARCHAR(16) NOT NULL DEFAULT 'service'",
            ),
            ("soumissions", "signature_token", "VARCHAR(64)"),
            ("soumissions", "signed_name", "VARCHAR(255)"),
            ("soumissions", "signed_ip", "VARCHAR(64)"),
            ("bons_travail", "signature_token", "VARCHAR(64)"),
            ("soumissions", "property_address", "VARCHAR(500)"),
            (
                "soumissions",
                "project_skip_backfill",
                "BOOLEAN NOT NULL DEFAULT FALSE",
            ),
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
            ("users", "first_name", "VARCHAR(100)"),
            ("users", "last_name", "VARCHAR(100)"),
            ("users", "avatar_image", "BYTEA"),
            ("users", "avatar_content_type", "VARCHAR(64)"),
            ("users", "profile_color", "VARCHAR(16)"),
            ("soumissions", "client_note", "TEXT"),
            ("factures", "internal_notes", "TEXT"),
            ("factures", "client_note", "TEXT"),
            # Facture finale + signature électronique du client.
            ("factures", "is_final", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("factures", "signature_token", "VARCHAR(64)"),
            ("factures", "signed_name", "VARCHAR(255)"),
            ("factures", "signed_ip", "VARCHAR(64)"),
            ("factures", "signed_at", "TIMESTAMP WITH TIME ZONE"),
            ("factures", "signature_image", "BYTEA"),
            (
                "factures",
                "signature_image_content_type",
                "VARCHAR(100)",
            ),
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
            ("project_phases", "start_time", "TIME"),
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
            ("prospection_leads", "recontact_at", "DATE"),
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
            ("agenda_events", "phase_id", "INTEGER"),
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
            # Immeuble cover photo en blob (upload direct, pas seulement URL).
            ("imm_immeubles", "cover_photo_blob", "BYTEA"),
            ("imm_immeubles", "cover_photo_content_type", "VARCHAR(64)"),
            # Partenaire externe (sans user_id) ou notes additionnelles.
            ("entreprise_partners", "partner_name", "VARCHAR(255)"),
            ("entreprise_partners", "partner_email", "VARCHAR(320)"),
            ("entreprise_partners", "partner_notes", "TEXT"),
            # Arrondissement (Ville de MTL) — dérivé via cross-référence
            # avec le dataset public « Adresses Civiques de Montréal ».
            ("mtl_property_units", "arrondissement", "VARCHAR(64)"),
            # Priorité côté UI (Monday-style) sur les tâches d'entreprise.
            (
                "entreprise_taches",
                "priority",
                "VARCHAR(16) NOT NULL DEFAULT 'moyenne'",
            ),
            # Ordre d'affichage des entreprises dans la sidebar.
            (
                "entreprises",
                "position",
                "INTEGER NOT NULL DEFAULT 0",
            ),
            # Ordre d'affichage des deals (Pipeline) dans la sidebar
            # Prospection — drag & drop similaire à Mes entreprises.
            (
                "prospection_deals",
                "position",
                "INTEGER NOT NULL DEFAULT 0",
            ),
            # Champs « riches » alignés sur EntrepriseTache pour que la
            # fiche détaillée des tâches soit identique sur les deux
            # volets (Pipeline et Entreprise).
            ("prospection_deal_tasks", "departement", "VARCHAR(64)"),
            ("prospection_deal_tasks", "recurrence", "VARCHAR(16)"),
            ("prospection_deal_tasks", "impact", "INTEGER"),
            ("prospection_deal_tasks", "confidence", "INTEGER"),
            ("prospection_deal_tasks", "effort", "INTEGER"),
            # Position manuelle — pour le drag & drop dans le tableau
            # de tâches d'entreprise (sinon classement par score).
            (
                "entreprise_taches",
                "position",
                "INTEGER NOT NULL DEFAULT 0",
            ),
            # Catalogue immeuble scopé par parent (entreprise OU deal).
            # Quand on crée un immeuble depuis le picker d'une fiche de
            # tâche, il n'apparaît que dans le catalogue de cette même
            # fiche. Les deux sont nullables ; au plus un est rempli à
            # la fois (immeuble appartient à une entreprise OU un deal).
            ("imm_immeubles", "owner_entreprise_id", "INTEGER"),
            ("imm_immeubles", "owner_deal_id", "INTEGER"),
            # Drive : URL du dossier Google Drive lié à l'entité.
            # Bouton « Drive » dans le header de la fiche y mène.
            # NULL = pas configuré.
            ("entreprises", "drive_folder_url", "VARCHAR(1024)"),
            ("prospection_leads", "drive_folder_url", "VARCHAR(1024)"),
            ("prospection_deals", "drive_folder_url", "VARCHAR(1024)"),
            # Modèles de tâches récurrentes : statut par défaut +
            # immeubles à attacher à chaque tâche matérialisée.
            (
                "entreprise_tache_templates",
                "default_status",
                "VARCHAR(16) NOT NULL DEFAULT 'todo'",
            ),
            ("entreprise_tache_templates", "immeuble_ids_json", "TEXT"),
            # Capture d'écran optionnelle sur les signalements de bug.
            ("help_requests", "screenshot_blob", "BYTEA"),
            ("help_requests", "screenshot_content_type", "VARCHAR(64)"),
            ("help_requests", "resolution_notes", "TEXT"),
            # Type de soumission (forfaitaire / estime). Défaut
            # "forfaitaire" (95% des cas en construction).
            (
                "soumissions",
                "pricing_kind",
                "VARCHAR(16) NOT NULL DEFAULT 'forfaitaire'",
            ),
            # Contrat d'entreprise APCHQ personnalisé Horizon : un
            # document soumission de type "contract" porte ses champs
            # structurés dans contract_data (JSON), et la signature de
            # l'entrepreneur (chargé de projet) dans contractor_*.
            (
                "soumissions",
                "kind",
                "VARCHAR(16) NOT NULL DEFAULT 'quote'",
            ),
            ("soumissions", "contract_data", "TEXT"),
            ("soumissions", "contractor_signed_name", "VARCHAR(255)"),
            (
                "soumissions",
                "contractor_signed_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            ("soumissions", "contractor_signed_ip", "VARCHAR(64)"),
            ("soumissions", "contractor_signature_image", "BYTEA"),
            (
                "soumissions",
                "contractor_signature_image_content_type",
                "VARCHAR(100)",
            ),
            (
                "soumissions",
                "contractor_signature_token",
                "VARCHAR(64)",
            ),
            ("lead_analyses", "best_refi_program", "VARCHAR(128)"),
            (
                "lead_analyses",
                "tga_pct",
                "NUMERIC(5,3) DEFAULT 4.0",
            ),
            (
                "lead_analyses",
                "taux_interet_achat_pct",
                "NUMERIC(5,3) DEFAULT 4.0",
            ),
            ("lead_analyses", "mdf_preteur_b", "NUMERIC(14,2)"),
            (
                "lead_analyses",
                "mdf_preteur_b_pct",
                "NUMERIC(5,2) DEFAULT 25.0",
            ),
            (
                "lead_analyses",
                "frais_demarrage_overrides_json",
                "TEXT",
            ),
            # Nouveau champ paramétrable (mai 2026) : taux d'intérêt
            # prêteur B pendant la phase chantier. Avant on utilisait
            # le défaut hardcodé 0.08 (dataclass FinanceInputs) ;
            # maintenant l'utilisateur peut surcharger par fiche.
            (
                "lead_analyses",
                "taux_interet_preteur_b_projet_pct",
                "NUMERIC(5,3) DEFAULT 8.0",
            ),
            # Kratos : pivot vers le modèle user-driven (problème
            # écrit/dicté par l'utilisateur, solution générée par l'IA).
            ("kratos_problems", "problem_text", "TEXT"),
            ("kratos_problems", "solution_plan", "TEXT"),
            ("kratos_problems", "solution_steps_json", "TEXT"),
            (
                "lead_analyses",
                "frais_demarrage_financables_json",
                "TEXT",
            ),
            (
                "entreprises",
                "is_parent_company",
                "BOOLEAN DEFAULT FALSE NOT NULL",
            ),
            # Organigramme : co-détenteurs d'un nœud entreprise (JSON
            # liste d'IDs org_nodes) — la détention n'est pas un arbre
            # strict, plusieurs entreprises peuvent en posséder une.
            ("org_nodes", "co_owner_node_ids", "TEXT"),
            # Organigramme : position libre sur le canvas type Miro.
            ("org_nodes", "pos_x", "DOUBLE PRECISION"),
            ("org_nodes", "pos_y", "DOUBLE PRECISION"),
            # Organigramme : niveau d'exécution (direction / adjoint /
            # adjoint_virtuel) — qui doit faire ce rôle / cette tâche.
            ("org_nodes", "execution_tier", "VARCHAR(24)"),
            # Refacturation des achats — Phase A.
            # `is_billable` indique si l'achat doit être refacturé au
            # client. `markup_percent` : majoration appliquée à
            # l'import. `invoiced_at` + `facture_item_id` : garde-fous
            # contre la double-facturation.
            (
                "achats",
                "is_billable",
                "BOOLEAN NOT NULL DEFAULT TRUE",
            ),
            ("achats", "markup_percent", "NUMERIC(6, 2)"),
            ("achats", "invoiced_at", "TIMESTAMP WITH TIME ZONE"),
            ("achats", "facture_item_id", "INTEGER"),
            # Sépare taxes payées au fournisseur du HT — pour ne pas
            # appliquer le markup sur des taxes lors de la refacturation.
            ("achats", "amount_taxes", "NUMERIC(12, 2)"),
            # Phase B — taux facturable employés + flag refacturé punches.
            ("employes", "billing_rate", "NUMERIC(10, 2)"),
            ("punches", "invoiced_at", "TIMESTAMP WITH TIME ZONE"),
            ("punches", "facture_item_id", "INTEGER"),
            # Phase C — facture sous-traitant + contrat de projet.
            ("achats", "sous_traitant_id", "INTEGER"),
            (
                "achats",
                "kind",
                "VARCHAR(16) NOT NULL DEFAULT 'material'",
            ),
            ("achats", "hours", "NUMERIC(6, 2)"),
            # Organigramme : suivi de mise en œuvre du plan canonique
            # (planifie | en_cours | fait | bloque | non_applicable).
            ("org_nodes", "state", "VARCHAR(16)"),
            ("org_nodes", "state_note", "TEXT"),
            # DevlogLead — alignement structurel sur ContactRequest pour
            # permettre le clonage 1:1 de la page CRM côté frontend.
            # Soumission rebuild : sections par pôle (Frontend, Backend,
            # Hosting…) avec markup interne et items associés.
            ("devlog_soumission_items", "section_id", "INTEGER"),
            (
                "devlog_soumission_items",
                "cost_per_unit",
                "DOUBLE PRECISION NOT NULL DEFAULT 0",
            ),
            # Refonte devis Dev logiciel (mai 2026) — calcul circulaire
            # mensuel + mise en oeuvre, voir
            # ``app.services.devlog_devis_calc``. ``is_devis_dev``
            # distingue les soumissions nouveau format des soumissions
            # legacy (conservées en lecture seule).
            (
                "devlog_soumissions",
                "is_devis_dev",
                "BOOLEAN NOT NULL DEFAULT FALSE",
            ),
            ("devlog_soumissions", "marge_recurrente_pct", "NUMERIC(5,2)"),
            ("devlog_soumissions", "marge_initiale_pct", "NUMERIC(5,2)"),
            (
                "devlog_soumissions",
                "commission_closer_pct",
                "NUMERIC(5,2)",
            ),
            ("devlog_soumissions", "taux_dev_horaire", "NUMERIC(8,2)"),
            (
                "devlog_soumissions",
                "taux_manager_horaire",
                "NUMERIC(8,2)",
            ),
            ("devlog_soumissions", "heures_manager", "NUMERIC(8,2)"),
            (
                "devlog_soumissions",
                "client_recurring_description",
                "TEXT",
            ),
            # Envoi PDF + signature publique (vague 1, mai 2026) —
            # token opaque + horodatages + audit trail signature.
            ("devlog_soumissions", "signature_token", "VARCHAR(64)"),
            (
                "devlog_soumissions",
                "sent_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            (
                "devlog_soumissions",
                "signed_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            ("devlog_soumissions", "signed_name", "VARCHAR(255)"),
            ("devlog_soumissions", "signed_ip", "VARCHAR(64)"),
            # PDF signé — généré à la signature publique, contient l'encart
            # « Signée électroniquement le ... par ... IP : ... » en bas
            # de chaque page. Stocké en BYTEA pour rester self-contained
            # (pas de bucket externe). Récupérable via
            # GET /devlog/soumissions/{id}/signed-pdf (auth admin/owner).
            ("devlog_soumissions", "signed_pdf_blob", "BYTEA"),
            # NDA — PDF signé généré au moment de la signature publique
            # (POST /public/ndas/{token}/sign). Contient le bloc Récepteur
            # rempli (nom, courriel, date, mention « Signée électrique-
            # ment ») + un bandeau emerald-600 « SIGNEE ELECTRONIQUEMENT »
            # en haut de la première page avec horodatage, IP, et hash
            # SHA-256 du document pour intégrité. Récupérable via
            # GET /api/v1/ndas/{id}/signed-pdf (auth admin/owner).
            ("ndas", "signed_pdf_blob", "BYTEA"),
            # Téléphone collecté sur le formulaire public de signature
            # NDA. Le bloc Récepteur du NDA exige Nom + Email +
            # Téléphone + Date + Signature ; l'email est déjà connu
            # (lien envoyé à cette adresse), reste à collecter le
            # téléphone côté formulaire public.
            ("ndas", "signed_phone", "VARCHAR(32)"),
            # Envoi PDF + consultation publique des factures devlog
            # (pièce #5 vague 1). `due_date` existe déjà dans le modèle,
            # on ajoute le token public, l'horodatage d'envoi et celui
            # du marquage manuel « payée » (en attendant Stripe).
            ("devlog_invoices", "signature_token", "VARCHAR(64)"),
            (
                "devlog_invoices",
                "sent_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            (
                "devlog_invoices",
                "paid_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            # Relances automatiques des factures Dev logiciel
            # (cron ``app.jobs.devlog_facture_reminders``).
            (
                "devlog_invoices",
                "last_reminder_sent_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            (
                "devlog_invoices",
                "reminder_count",
                "INTEGER NOT NULL DEFAULT 0",
            ),
            # Stripe Checkout pour les factures devlog (chantier #4,
            # mai 2026). `stripe_session_id` sert au mapping webhook
            # → facture ; `payment_method` distingue les paiements en
            # ligne ('stripe') des paiements manuels ('virement',
            # 'cheque', 'manuel').
            (
                "devlog_invoices",
                "stripe_session_id",
                "VARCHAR(128)",
            ),
            (
                "devlog_invoices",
                "stripe_payment_intent_id",
                "VARCHAR(128)",
            ),
            (
                "devlog_invoices",
                "payment_method",
                "VARCHAR(32)",
            ),
            (
                "devlog_soumission_items",
                "item_kind",
                "VARCHAR(20) NOT NULL DEFAULT 'feature'",
            ),
            ("devlog_soumission_items", "heures", "NUMERIC(8,2)"),
            # Niveau MODULE (refonte 2026-06) — un item rattaché à un
            # module est une fonctionnalité de ce module. La table
            # ``devlog_soumission_modules`` est créée par create_all ;
            # cette colonne FK (nullable, ON DELETE SET NULL côté modèle)
            # étend la table items existante. Additif et rétrocompatible :
            # NULL pour tous les items legacy.
            ("devlog_soumission_items", "module_id", "INTEGER"),
            # Gratuité conditionnelle « module → module » (refonte
            # 2026-06, Phase 2). Si défini ET module déclencheur
            # sélectionné, ce module devient gratuit côté client. FK
            # auto-référente (ON DELETE SET NULL côté modèle ; l'ALTER
            # ajoute la colonne simple, comme pour ``module_id``).
            # Additif et rétrocompatible : NULL pour tous les modules
            # existants.
            (
                "devlog_soumission_modules",
                "free_when_module_id",
                "INTEGER",
            ),
            ("devlog_leads", "address", "VARCHAR(500)"),
            (
                "devlog_leads",
                "project_type",
                "VARCHAR(32) NOT NULL DEFAULT 'autre'",
            ),
            ("devlog_leads", "kanban_column", "VARCHAR(64)"),
            (
                "devlog_leads",
                "locale",
                "VARCHAR(8) NOT NULL DEFAULT 'fr'",
            ),
            # Notes de rencontre client (texte libre, peut etre tres
            # long). Resume par Gemini via /devlog/leads/{id}/summarize-notes.
            ("devlog_leads", "meeting_notes", "TEXT"),
            # Fiche client unifiee (mai 2026) — quand un prospect est
            # converti en client, on garde le lien bidirectionnel
            # (`devlog_leads.client_id` ↔ `devlog_clients.converted_from_lead_id`)
            # + l'horodatage de la conversion pour afficher le badge
            # "Prospect depuis ... · Converti le ..." sur la fiche client
            # et pour permettre le merge de l'historique (notes, soumissions,
            # attachments) entre les deux entites.
            (
                "devlog_clients",
                "converted_from_lead_id",
                "INTEGER REFERENCES devlog_leads(id) ON DELETE SET NULL",
            ),
            (
                "devlog_clients",
                "converted_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            # Téléphonie Phase 2 — secrétaire IA. La table CallTurn est
            # créée par create_all ; les colonnes ci-dessous étendent
            # PhoneNumber et Call (créés en Phase 1).
            (
                "voice_phone_numbers",
                "secretary_mode_active",
                "BOOLEAN NOT NULL DEFAULT FALSE",
            ),
            (
                "voice_phone_numbers",
                "lead_auto_callback_enabled",
                "BOOLEAN NOT NULL DEFAULT FALSE",
            ),
            ("voice_calls", "lang", "VARCHAR(8) NOT NULL DEFAULT 'fr-CA'"),
            ("voice_calls", "intent", "VARCHAR(64)"),
            ("voice_calls", "lead_name", "VARCHAR(255)"),
            ("voice_calls", "lead_callback_phone", "VARCHAR(50)"),
            ("voice_calls", "lead_reason", "TEXT"),
            ("voice_calls", "contact_request_id", "INTEGER"),
            # Téléphonie Phase 3 — flags routage + voicemail.
            (
                "voice_calls",
                "was_blocked",
                "BOOLEAN NOT NULL DEFAULT FALSE",
            ),
            ("voice_calls", "was_vip", "BOOLEAN NOT NULL DEFAULT FALSE"),
            (
                "voice_calls",
                "was_voicemail",
                "BOOLEAN NOT NULL DEFAULT FALSE",
            ),
            ("voice_calls", "voicemail_transcription", "TEXT"),
            ("voice_calls", "voicemail_summary", "TEXT"),
            # Phase 4 — sortant + lien CRM générique.
            ("voice_calls", "entity_type", "VARCHAR(32)"),
            ("voice_calls", "entity_id", "INTEGER"),
            ("voice_calls", "followup_suggestion", "TEXT"),
            ("voice_calls", "caller_kind", "VARCHAR(32)"),
            # Anti-spam — VoiceUsageDaily peut être créée vide par
            # create_all, mais on ajoute spam_blocked au cas où la
            # table existait sans cette colonne (bootstrap progressif).
            (
                "voice_usage_daily",
                "spam_blocked",
                "INTEGER NOT NULL DEFAULT 0",
            ),
            # Intake téléphonique IA — collecte de besoins en
            # construction par Léa au téléphone, avec validation par
            # le client via lien courriel (page publique).
            ("contact_requests", "intake_data", "TEXT"),
            ("contact_requests", "validation_token", "VARCHAR(64)"),
            (
                "contact_requests",
                "validated_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            # Phase 8 : cibles de routage par scénario, configurables
            # depuis l'app (au lieu d'env vars Render).
            ("voice_phone_numbers", "urgency_forward_e164", "VARCHAR(20)"),
            ("voice_phone_numbers", "closer_forward_e164", "VARCHAR(20)"),
            ("voice_phone_numbers", "followup_forward_e164", "VARCHAR(20)"),
            # Agenda — type de RV configurable (lien vers
            # appointment_types). Optionnel pour ne pas casser le legacy.
            ("agenda_events", "appointment_type_id", "INTEGER"),
            # État conversationnel JSON sur Call (smart booking : on
            # mémorise les créneaux proposés par Léa pour les
            # retrouver au tour suivant).
            ("voice_calls", "session_state", "TEXT"),
            ("prospection_deals", "lead_analysis_id", "INTEGER"),
            ("lead_analyses", "converted_to_deal_id", "INTEGER"),
            # Phase A2 (tri-couche extraction) : modèle utilisé pour
            # l'extraction (local / gemini / claude-sonnet-4-6).
            ("lead_analyses", "model_used", "VARCHAR(64)"),
            # Phase A3 (validation post-extraction) : liste JSONB des
            # anomalies détectées (bornes hors-limites, divergences
            # local↔gemini). Cf. app.services.lead_validation.
            ("lead_analyses", "validation_warnings", "JSONB"),
            # Chantier "contrat signé + dépôt payé → projet démarré"
            # (mai 2026). Sur DevlogContract : dépôt initial requis +
            # trace du paiement manuel + lien vers le projet provisionné.
            # Sur DevlogProject : horodatage de démarrage effectif.
            (
                "devlog_contracts",
                "deposit_required_cents",
                "INTEGER",
            ),
            (
                "devlog_contracts",
                "deposit_paid_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            (
                "devlog_contracts",
                "deposit_paid_amount_cents",
                "INTEGER",
            ),
            ("devlog_contracts", "project_id", "INTEGER"),
            (
                "devlog_projects",
                "started_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            # Horodatage du passage en status='livre' — sert au cron
            # ``devlog_nps_dispatch`` (envoi NPS 7 jours après livraison).
            # Posé automatiquement par l'event listener du modèle
            # ``DevlogProject``.
            (
                "devlog_projects",
                "delivered_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            # Hook post-signature contrat (mai 2026, PR Phil). 4 side-effects
            # best-effort déclenchés depuis le endpoint public sign — chaque
            # horodatage marque le succès de l'étape (NULL = pas encore /
            # rate ou skip). github_repo_url contient l'URL HTML du repo
            # provisionné par GITHUB_AUTOMATION_TOKEN.
            (
                "devlog_contracts",
                "github_repo_url",
                "VARCHAR(512)",
            ),
            (
                "devlog_contracts",
                "welcome_email_sent_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            (
                "devlog_contracts",
                "qbo_pushed_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            (
                "devlog_contracts",
                "teams_notified_at",
                "TIMESTAMP WITH TIME ZONE",
            ),
            # Mai 2026 : colonne "finançable par défaut" sur la table
            # de défauts d'analyse. Permet à Phil de configurer
            # globalement, pour chaque item MDF (groupes ``mdf_frais``
            # et ``mdf_pct``), si la case "Finançable" doit être
            # pré-cochée à la création d'une nouvelle fiche.
            (
                "prospection_analysis_defaults",
                "financable_par_defaut",
                "BOOLEAN",
            ),
            # Drive page modules : registry par pôle (navigation Settings).
            # Métadonnées seedées (cf. drive_page_modules_seed), nullables
            # pour les modules auto-créés via PATCH.
            ("drive_page_modules", "pole", "VARCHAR(64)"),
            ("drive_page_modules", "label", "VARCHAR(128)"),
            ("drive_page_modules", "route", "VARCHAR(256)"),
            # Portée du module : "entity" (un dossier par fiche — défaut,
            # comportement historique) ou "page" (dossier unique singleton,
            # via DriveEntityLink à entity_id=0). DEFAULT 'entity' garantit
            # que les 22 modules de fiche existants restent en mode entité.
            (
                "drive_page_modules",
                "scope",
                "VARCHAR(16) NOT NULL DEFAULT 'entity'",
            ),
            # Résumé IA de l'enregistrement d'appel (humain) — distinct du
            # voicemail.
            ("voice_calls", "recording_transcription", "TEXT"),
            ("voice_calls", "recording_summary", "TEXT"),
            # Extracteur générique des Drive Conventions : mapping JSON
            # {var_key: field_path} résolu par introspection. NULL =
            # fallback sur l'extracteur hardcodé du registry (rétrocompat
            # des conventions existantes sans mapping).
            ("drive_conventions", "variable_mapping", "JSON"),
            # Signature électronique des baux (volet immobilier, Phase 2.4).
            ("imm_baux", "signature_token", "VARCHAR(64)"),
            ("imm_baux", "sent_to_email", "VARCHAR(320)"),
            ("imm_baux", "sent_at", "TIMESTAMP WITH TIME ZONE"),
            ("imm_baux", "signed_at", "TIMESTAMP WITH TIME ZONE"),
            ("imm_baux", "signed_by_name", "VARCHAR(255)"),
            ("imm_baux", "signature_ip", "VARCHAR(64)"),
            ("imm_baux", "signature_image", "BYTEA"),
            ("imm_baux", "signature_image_content_type", "VARCHAR(100)"),
            # Valeurs par defaut des soumissions devis_dev (juin 2026) :
            # fonctionnalites par defaut (pre-remplissent CHAQUE nouveau
            # module) + taches du charge de projet par defaut (pre-remplies a
            # CHAQUE nouvelle soumission). Listes JSON [{description, heures}].
            # NULL sur les lignes existantes => comportement neutre (retrocompat).
            ("devlog_soumission_defaults", "default_features_json", "JSONB"),
            (
                "devlog_soumission_defaults",
                "default_manager_tasks_json",
                "JSONB",
            ),
            # Permissions par pôle des clés d'API (juin 2026) : liste JSON de
            # scopes « <pole>:<capability> » (ex. devlog:activity:read,
            # prospection:tasks:create). NULL sur les clés existantes =>
            # rétrocompat : lecture de TOUS les pôles (aucune écriture).
            ("api_keys", "scopes_json", "TEXT"),
        )
        for table, column, col_type in additive_columns:
            await conn.execute(
                text(
                    f'ALTER TABLE {table} '
                    f'ADD COLUMN IF NOT EXISTS {column} {col_type}'
                )
            )

        # Achats : tout achat NON paye par facture fournisseur
        # (cheque, CC) est considere paye au moment de l'achat.
        # Backfill idempotent : marque paid les achats existants avec
        # payment_method != bill_to_pay encore en status received.
        try:
            await conn.execute(
                text(
                    "UPDATE achats SET status = 'paid', "
                    "paid_at = COALESCE(paid_at, received_at, "
                    "created_at) "
                    "WHERE status = 'received' "
                    "AND payment_method IS NOT NULL "
                    "AND payment_method <> 'bill_to_pay'"
                )
            )
        except Exception:
            # Table peut ne pas exister au tout premier demarrage,
            # ou colonne pas encore la sur ancien schema.
            pass

        # Achats : pour les bill_to_pay existants sans due_at, calcule
        # received_at + 30j (defaut) ou + payment_terms_days du
        # fournisseur si defini. Idempotent.
        try:
            await conn.execute(
                text(
                    "UPDATE achats a SET due_at = "
                    "COALESCE(a.received_at, a.created_at) + "
                    "make_interval(days := COALESCE("
                    "(SELECT f.payment_terms_days FROM fournisseurs f "
                    "WHERE f.id = a.fournisseur_id), 30)) "
                    "WHERE a.status = 'received' "
                    "AND a.payment_method = 'bill_to_pay' "
                    "AND a.due_at IS NULL"
                )
            )
        except Exception:
            pass

        # DevlogLead : migration des statuts français vers les valeurs
        # ContactRequest (new/contacted/qualified/quoted/won/lost/spam)
        # pour aligner la page CRM Dev logiciel sur Construction.
        # Idempotent : les rows déjà migrées (status déjà en anglais) ne
        # sont pas touchées.
        try:
            for old, new in (
                ("nouveau", "new"),
                ("contacte", "contacted"),
                ("rdv", "qualified"),
                ("presentation", "qualified"),
                ("soumission", "quoted"),
                ("gagne", "won"),
                ("perdu", "lost"),
            ):
                await conn.execute(
                    text(
                        "UPDATE devlog_leads SET status = :new "
                        "WHERE status = :old"
                    ),
                    {"new": new, "old": old},
                )
            # Aligne la longueur de la colonne status à VARCHAR(32) au
            # cas où l'ancienne VARCHAR(20) existerait — silencieux si
            # déjà à la bonne taille.
            await conn.execute(
                text(
                    "ALTER TABLE devlog_leads "
                    "ALTER COLUMN status TYPE VARCHAR(32)"
                )
            )
        except Exception:  # noqa: BLE001
            # Table peut ne pas exister encore au tout premier démarrage
            # ou avoir une autre forme. Migration silencieuse — sera
            # rejouée au prochain redémarrage si nécessaire.
            pass

        # Kratos : passage à entreprise_id NULLABLE (problème global
        # transverse possible). Idempotent : si déjà nullable, no-op.
        try:
            await conn.execute(
                text(
                    "ALTER TABLE kratos_problems "
                    "ALTER COLUMN entreprise_id DROP NOT NULL"
                )
            )
        except Exception:
            pass

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

        # Promote Philippe Meuser au rang owner (mêmes accès que
        # Steven). Idempotent — UPDATE n'a aucun effet quand le rôle
        # est déjà 'owner'. On vise les deux variantes de courriel
        # qu'on a vues dans les whitelists.
        try:
            await conn.execute(
                text(
                    "UPDATE users SET role='owner', is_admin=TRUE "
                    "WHERE LOWER(email) IN "
                    "('philippe.meuser@immohorizon.com', "
                    " 'pmeuser@immohorizon.com')"
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

        # Élargit sous_traitants.region : créée en VARCHAR(32) (une
        # seule région), on accepte désormais une liste séparée par
        # virgules pour permettre plusieurs régions par sous-traitant.
        try:
            await conn.execute(
                text(
                    "ALTER TABLE sous_traitants "
                    "ALTER COLUMN region TYPE VARCHAR(255)"
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

        # project_phases.duration_days passe de INTEGER → NUMERIC(6,2)
        # pour supporter les phases en heures (ex. 0.5 = ½ journée).
        # ALTER TYPE NUMERIC est idempotent côté PG quand la conversion
        # est implicite (INTEGER → NUMERIC ne perd jamais de données).
        try:
            await conn.execute(
                text(
                    "ALTER TABLE project_phases "
                    "ALTER COLUMN duration_days TYPE NUMERIC(6,2)"
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
            # Le nom d'immeuble est désormais facultatif — fallback sur
            # l'adresse si non fourni.
            ("imm_immeubles", "name"),
            # user_id devient optionnel sur entreprise_partners pour
            # permettre des partenaires externes sans compte portail.
            ("entreprise_partners", "user_id"),
        ):
            try:
                await conn.execute(
                    text(f'ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL')
                )
            except Exception:
                # Column may not exist yet on a brand-new DB — harmless.
                pass

        # Drop l'unique constraint sur user_calendar_feeds.user_id pour
        # autoriser plusieurs flux ICS par user (perso + travail + équipe).
        # Idempotent — DROP CONSTRAINT IF EXISTS si le nom est trouvé.
        for cstr in (
            "user_calendar_feeds_user_id_key",
            "uq_user_calendar_feeds_user_id",
        ):
            try:
                await conn.execute(
                    text(
                        f"ALTER TABLE user_calendar_feeds "
                        f"DROP CONSTRAINT IF EXISTS {cstr}"
                    )
                )
            except Exception:
                pass

        # ⚠ DÉSACTIVÉ — était une migration one-shot (Avril 2026) qui
        # déplaçait les anciens « achats » draft/ordered vers la table
        # purchase_orders puis les SUPPRIMAIT de la table achats. Comme
        # le bloc est resté dans init_db, il s'exécutait à CHAQUE
        # démarrage et avalait silencieusement tout achat futur dont
        # le status était draft/ordered ou cancelled+received_at=NULL.
        # Conséquence : les achats annulés non-reçus, créés normalement
        # par les utilisateurs, disparaissaient au prochain cold-start
        # Render. Désactivé en novembre 2026 pour stopper la perte.
        # On garde le bloc commenté pour la mémoire.

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

        # Index additionnels — perf des listes /prospection/mtl-properties
        # avec ~900 K-1 M unités. CREATE INDEX IF NOT EXISTS est idempotent.
        # Sans ces index, les filtres déclenchent des seq-scans (plusieurs
        # secondes par requête).
        additive_indexes = (
            # Téléphonie anti-spam : rate-limit compte les appels
            # récents par from_e164 — sans cet index, scan complet de
            # voice_calls à chaque appel entrant.
            (
                "ix_voice_calls_from_started",
                "voice_calls",
                "(from_e164, started_at DESC)",
            ),
            (
                "ix_mtl_units_nombre_logement",
                "mtl_property_units",
                "(nombre_logement)",
            ),
            (
                "ix_mtl_units_code_utilisation",
                "mtl_property_units",
                "(code_utilisation)",
            ),
            (
                "ix_mtl_units_municipalite_lower",
                "mtl_property_units",
                "(LOWER(municipalite))",
            ),
            (
                "ix_mtl_units_annee_construction",
                "mtl_property_units",
                "(annee_construction)",
            ),
            (
                "ix_mtl_units_arrondissement",
                "mtl_property_units",
                "(arrondissement)",
            ),
        )
        for idx_name, table, expr in additive_indexes:
            try:
                await conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {idx_name} "
                        f"ON {table} {expr}"
                    )
                )
            except Exception:
                # Table absente au tout premier boot — sera ré-essayé.
                pass

        # Reclassification one-shot des tâches d'entreprises importées
        # de Monday qui sont restées en « backlog ». L'utilisateur veut
        # qu'aucune tâche importée ne reste classée backlog : on la
        # ventile dans À faire / En cours / En attente / Terminé selon
        # son `monday_group_title` (le nom du groupe d'origine sur le
        # board Monday). Idempotent — chaque UPDATE ne touche que les
        # lignes encore en backlog, donc une fois reclassifiées elles
        # ne bougent plus aux boots suivants.
        #
        # On limite aux tâches avec monday_item_id NOT NULL pour ne pas
        # toucher les backlogs créés manuellement par les utilisateurs.
        for sql in (
            # Terminé : si completed_at est déjà set OU si le titre du
            # groupe matche done/complete/✓/etc.
            """
            UPDATE entreprise_taches SET status = 'done'
            WHERE status = 'backlog'
              AND monday_item_id IS NOT NULL
              AND (
                completed_at IS NOT NULL
                OR LOWER(COALESCE(monday_group_title, '')) ~
                   '(done|complete|fini|termin|✓|✅|achev|fait)'
              )
            """,
            # En cours
            """
            UPDATE entreprise_taches SET status = 'in_progress'
            WHERE status = 'backlog'
              AND monday_item_id IS NOT NULL
              AND LOWER(COALESCE(monday_group_title, '')) ~
                  '(working|en cours|doing|actif|wip|ongoing|en traitement)'
            """,
            # En attente / bloqué
            """
            UPDATE entreprise_taches SET status = 'waiting'
            WHERE status = 'backlog'
              AND monday_item_id IS NOT NULL
              AND LOWER(COALESCE(monday_group_title, '')) ~
                  '(attente|wait|block|stuck|on hold|hold|pause|bloqu|pending review)'
            """,
            # Tout le reste qui venait de Monday → À faire (TODO)
            # par défaut. C'est plus utile que de laisser en backlog,
            # et l'utilisateur pourra raffiner manuellement par la suite.
            """
            UPDATE entreprise_taches SET status = 'todo'
            WHERE status = 'backlog'
              AND monday_item_id IS NOT NULL
            """,
            # NOTE : la migration « waiting → todo » a été retirée
            # car la colonne « En attente » est maintenant un statut
            # actif de l'UI (entre « En traitement » et « Terminé »).
            # Toute valeur historique en `waiting` reprend donc sa
            # signification correcte sans rien faire.
            # Pipeline (deals) — alignement du vocabulaire de statut sur
            # celui des tâches d'entreprise. Le frontend partage un seul
            # task-config (todo / a_faire / in_progress / done) ; les
            # anciennes valeurs (a_venir / en_traitement / termine)
            # doivent être renommées dans `prospection_deal_tasks`.
            # Idempotent — une fois renommées, plus aucune ligne ne
            # matche.
            """
            UPDATE prospection_deal_tasks SET status = 'todo'
            WHERE status = 'a_venir'
            """,
            """
            UPDATE prospection_deal_tasks SET status = 'in_progress'
            WHERE status = 'en_traitement'
            """,
            """
            UPDATE prospection_deal_tasks SET status = 'done'
            WHERE status = 'termine'
            """,
            # Auto-remplissage des scores ICE (impact / confiance /
            # effort) pour toutes les tâches qui n'ont pas encore été
            # évaluées. Idempotent — la WHERE clause ne touche que les
            # lignes où impact IS NULL. L'impact dérive de la priorité
            # manuelle (urgent → 9, eleve → 7, moyenne/non_assigne →
            # 5, faible → 3), la confiance et l'effort sont initialisés
            # à 5 (médian) — l'utilisateur peut affiner par la suite
            # depuis la fiche détaillée.
            """
            UPDATE entreprise_taches
            SET impact = CASE priority
                  WHEN 'urgent' THEN 9
                  WHEN 'eleve'  THEN 7
                  WHEN 'faible' THEN 3
                  ELSE 5
                END,
                confidence = COALESCE(confidence, 5),
                effort     = COALESCE(effort, 5)
            WHERE impact IS NULL
            """,
            """
            UPDATE entreprise_taches
            SET confidence = 5
            WHERE confidence IS NULL
            """,
            """
            UPDATE entreprise_taches
            SET effort = 5
            WHERE effort IS NULL
            """,
            """
            UPDATE prospection_deal_tasks
            SET impact = CASE priority
                  WHEN 'urgent' THEN 9
                  WHEN 'eleve'  THEN 7
                  WHEN 'faible' THEN 3
                  ELSE 5
                END,
                confidence = COALESCE(confidence, 5),
                effort     = COALESCE(effort, 5)
            WHERE impact IS NULL
            """,
            """
            UPDATE prospection_deal_tasks
            SET confidence = 5
            WHERE confidence IS NULL
            """,
            """
            UPDATE prospection_deal_tasks
            SET effort = 5
            WHERE effort IS NULL
            """,
            # Backfill des soumissions acceptées sans `accepted_at`.
            # Cas typique : statut posé via PATCH générique ou import
            # externe sans timestamp. Sans ce timestamp, le KPI
            # « Ventes » du dashboard les ignore — on retombe donc
            # sur `updated_at` (heure de la dernière modif, qui
            # correspond ~ à la transition vers ACCEPTED).
            """
            UPDATE soumissions
            SET accepted_at = updated_at
            WHERE status = 'accepted' AND accepted_at IS NULL
            """,
            # Ventilation TPS/TVQ des achats existants : on répartit
            # `amount_taxes` (somme) selon les taux QC standard
            # (TPS 5 % + TVQ 9,975 % = 14,975 %). Idempotent — ne touche
            # que les lignes pas encore ventilées (amount_tps NULL). La
            # somme tps+tvq reste exactement égale à amount_taxes.
            """
            UPDATE achats
            SET amount_tps = ROUND(COALESCE(amount_taxes, 0) * 5.0 / 14.975, 2),
                amount_tvq = COALESCE(amount_taxes, 0)
                             - ROUND(COALESCE(amount_taxes, 0) * 5.0 / 14.975, 2)
            WHERE amount_tps IS NULL
            """,
            # Rétro-lien projet ↔ soumission : un projet créé manuellement
            # (ou par une ancienne version) peut avoir budget = total de la
            # soumission mais soumission_id NULL → impossible d'importer
            # les items de la soumission dans une facture, et la carte
            # kanban tombe sur le titre au lieu de l'adresse. On relie au
            # devis ACCEPTÉ correspondant (même prospect ou même client ET
            # même montant total). Idempotent : ne touche que soumission_id
            # NULL.
            """
            UPDATE projects p
            SET soumission_id = (
                SELECT s.id FROM soumissions s
                WHERE s.status = 'accepted'
                  AND s.total = p.budget
                  AND (
                    (p.contact_request_id IS NOT NULL
                       AND s.contact_request_id = p.contact_request_id)
                    OR (p.client_id IS NOT NULL
                       AND s.client_id = p.client_id)
                  )
                ORDER BY s.accepted_at DESC NULLS LAST, s.id DESC
                LIMIT 1
            )
            WHERE p.soumission_id IS NULL
              AND p.budget IS NOT NULL
              AND EXISTS (
                SELECT 1 FROM soumissions s
                WHERE s.status = 'accepted'
                  AND s.total = p.budget
                  AND (
                    (p.contact_request_id IS NOT NULL
                       AND s.contact_request_id = p.contact_request_id)
                    OR (p.client_id IS NOT NULL
                       AND s.client_id = p.client_id)
                  )
              )
            """,
            # Table de marqueurs pour les backfills à exécuter UNE seule
            # fois (par opposition aux UPDATE idempotents ci-dessus qui
            # peuvent retourner à chaque boot). Permet d'appliquer une
            # règle rétroactive sans réécraser les choix manuels faits
            # ensuite par l'utilisateur.
            """
            CREATE TABLE IF NOT EXISTS applied_backfills (
                key VARCHAR(120) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            # Rétroactif (one-shot) : défaut « refacturable » des achats
            # selon le type de la soumission du projet. Forfaitaire =
            # non refacturable (décoché) ; estimé / à contrat =
            # refacturable (coché). Les projets sans soumission liée
            # retombent sur forfaitaire (décoché). Garde NOT EXISTS : ne
            # s'exécute qu'au premier boot après déploiement, puis le
            # marqueur empêche d'écraser les ajustements manuels.
            """
            UPDATE achats a
            SET is_billable = CASE
                    WHEN s.kind = 'contract' OR s.pricing_kind = 'estime'
                        THEN TRUE
                    ELSE FALSE
                END
            FROM projects p
            LEFT JOIN soumissions s ON s.id = p.soumission_id
            WHERE a.project_id = p.id
              AND NOT EXISTS (
                  SELECT 1 FROM applied_backfills
                  WHERE key = 'achat_is_billable_by_project_type_v1'
              )
            """,
            """
            INSERT INTO applied_backfills (key)
            VALUES ('achat_is_billable_by_project_type_v1')
            ON CONFLICT (key) DO NOTHING
            """,
        ):
            try:
                await conn.execute(text(sql))
            except Exception:
                # Table absente / colonne pas encore migrée — on
                # passe sans bloquer le boot.
                pass

        # Rétroactif (one-shot) : faire pivoter de 90° HORAIRE tous les
        # reçus d'achat déjà stockés. Ils ont été numérisés avant la
        # correction d'orientation et sont enregistrés de côté. Les
        # nouveaux reçus passent par le recadrage (déjà à l'endroit) et
        # ne sont PAS touchés car le marqueur empêche un second passage.
        # Gardé + exception-safe pour ne jamais bloquer le boot.
        try:
            done = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM applied_backfills WHERE key = :k"
                    ),
                    {"k": "rotate_existing_receipts_cw90_v1"},
                )
            ).first()
        except Exception:
            done = True  # table pas prête — on retentera au prochain boot
        if not done:
            try:
                n = await _rotate_existing_receipts_cw90(conn)
                await conn.execute(
                    text(
                        "INSERT INTO applied_backfills (key) VALUES (:k) "
                        "ON CONFLICT (key) DO NOTHING"
                    ),
                    {"k": "rotate_existing_receipts_cw90_v1"},
                )
                print(f"[init_db] reçus pivotés 90° horaire : {n}")
            except Exception as exc:  # noqa: BLE001
                print(f"[init_db] rotation reçus échouée : {exc}")

        # Seed des types de RV par défaut. Idempotent :
        # INSERT ... ON CONFLICT DO NOTHING. L'admin peut modifier
        # depuis l'UI ensuite (couleur, durée, buffer).
        for slug, label, duration, prep, roles, color, travel in (
            (
                "evaluation_soumission",
                "Évaluation soumission (chez le client)",
                90,
                15,
                "closer",
                "0ea5e9",
                True,
            ),
            (
                "visite_chantier",
                "Visite de chantier",
                30,
                0,
                "charge_projet,closer",
                "10b981",
                True,
            ),
            (
                "reunion_interne",
                "Réunion interne (bureau)",
                30,
                0,
                None,
                "a855f7",
                False,
            ),
            (
                "inspection_finale",
                "Inspection finale / livraison",
                45,
                15,
                "closer,charge_projet",
                "f59e0b",
                True,
            ),
            (
                "appel_telephone",
                "Appel téléphonique planifié",
                15,
                0,
                None,
                "64748b",
                False,
            ),
        ):
            try:
                await conn.execute(
                    text(
                        """
                        INSERT INTO appointment_types
                          (slug, label, default_duration_min,
                           prep_buffer_min, allowed_roles_csv, color,
                           requires_travel, active, created_at)
                        VALUES (:slug, :label, :duration, :prep,
                                :roles, :color, :travel, TRUE, NOW())
                        ON CONFLICT (slug) DO NOTHING
                        """
                    ),
                    {
                        "slug": slug,
                        "label": label,
                        "duration": duration,
                        "prep": prep,
                        "roles": roles,
                        "color": color,
                        "travel": travel,
                    },
                )
            except Exception:
                pass

        # Seed des défauts globaux d'analyse financière (mai 2026,
        # étendu mai 2026 pour couvrir TOUS les inputs manuels +
        # frais MDF — PR « extend-analysis-defaults-tous-champs »).
        #
        # Permet à Phil de modifier les valeurs pré-remplies pour les
        # nouvelles fiches d'analyse depuis l'UI (bouton ⚙️ « Modifier
        # les défauts »). Stockés en pourcentage (3.75 = 3.75 %, 25.0
        # = 25 %, 8.0 = 8 %) ou en $ selon le champ. Le `step` permet
        # à l'UI de deviner le format (< 1 → %, >= 1 → $).
        # Idempotent :
        #   - ON CONFLICT (key) DO UPDATE SET group_name pour garder
        #     les renommages de groupes en sync sans toucher aux
        #     valeurs déjà modifiées par Phil.
        #   - INSERT des nouvelles clés via DO NOTHING équivalent.
        # Modifier un défaut ne change que les FUTURES analyses, pas
        # les existantes.
        #
        # Migration douce des anciens noms de groupes :
        #   - 'refi' → 'inputs_manuels' (libellé plus clair)
        #   - 'mdf'  → 'inputs_manuels' (mdf_preteur_b_pct est un
        #              input manuel, pas un frais)
        #   - nouveaux frais MDF → groupe 'mdf_frais'
        #
        # Juin 2026 — Dé-hardcodage du moteur d'analyse de lead
        # (PR « prospection-config-dehardcode-1a »). On externalise vers
        # cette table les constantes encore codées en dur dans
        # ``lead_analysis_finance`` via 3 nouveaux groupes :
        #   - 'depenses_normalisees' : barème SCHL (concierge, entretien,
        #     gestion, wifi, internet, thermopompe, seuil 12 log).
        #   - 'scenarios_financement' : LTV / amortissement / RCD des 4
        #     scénarios (achat, SCHL std, APH 50, APH 100).
        #   - 'baremes_fiscaux' : ratio abordabilité APH (0.40) + barème
        #     progressif des taxes de bienvenue de Montréal (value_json).
        # Les valeurs seedées = EXACTEMENT les constantes actuelles ; le
        # moteur lit la config si présente, sinon retombe sur la
        # constante (fallback ultime). Résultat identique au centime
        # tant que personne ne modifie rien.
        try:
            await conn.execute(
                text(
                    """
                    UPDATE prospection_analysis_defaults
                       SET group_name = 'inputs_manuels'
                     WHERE group_name IN ('refi', 'mdf')
                    """
                )
            )
        except Exception:
            # Table absente — sera créée par create_all + retentée
            # au prochain boot.
            pass

        # Liste exhaustive des défauts.
        # Champs des inputs manuels (groupe 'inputs_manuels') :
        #   - stockés en pct (step < 1) ou unités entières (step >= 1).
        # Frais MDF (groupe 'mdf_frais') :
        #   - frais_* : montants $ one-shot (step = 50).
        #   - pct_courtier_hypothecaire_* : %, appliqué au prix d'achat
        #     ou financement APH (step = 0.05).
        for key, value_float, label_fr, description_fr, mn, mx, step, group in (
                # ── Groupe : Inputs manuels ──────────────────────────
                (
                    "taux_interet_refi",
                    3.75,
                    "Taux d'intérêt refi (%)",
                    "Taux d'intérêt utilisé pour calculer le refinancement "
                    "(SCHL, APH 50, APH 100).",
                    0.0,
                    25.0,
                    0.05,
                    "inputs_manuels",
                ),
                (
                    "taux_interet_preteur_b_projet",
                    8.0,
                    "Taux d'intérêt prêteur B (pendant projet) (%)",
                    "Taux d'intérêt appliqué par le prêteur B pendant la "
                    "phase chantier (typique 8 % en 2024-2025). Utilisé "
                    "pour calculer les intérêts de portage (L17).",
                    0.0,
                    30.0,
                    0.05,
                    "inputs_manuels",
                ),
                (
                    "mdf_preteur_b_pct",
                    25.0,
                    "% MDF prêteur B (%)",
                    "Pourcentage de mise de fonds requis par le prêteur B "
                    "(privé, hypothèque conventionnelle 75 % LTV). Varie "
                    "selon le prêteur (25 % typique, parfois 35 %).",
                    0.0,
                    100.0,
                    0.5,
                    "inputs_manuels",
                ),
                (
                    "tga_pct",
                    4.0,
                    "TGA — Taux global d'actualisation (%)",
                    "Taux d'actualisation utilisé pour calculer la valeur "
                    "économique TGA (R54 dans l'Excel). Défaut marché : 4 %.",
                    0.0,
                    20.0,
                    0.05,
                    "inputs_manuels",
                ),
                (
                    "taux_interet_achat_pct",
                    4.0,
                    "Taux d'intérêt prêt à l'achat (%)",
                    "Taux d'intérêt appliqué au scénario d'achat "
                    "conventionnel (75 % LTV, 25 ans, RCD 1.20).",
                    0.0,
                    25.0,
                    0.05,
                    "inputs_manuels",
                ),
                (
                    "reduction_energie_pct",
                    0.0,
                    "Réduction énergie post-refi (%)",
                    "Réduction estimée de la facture d'énergie après "
                    "travaux d'efficacité (appliquée seulement aux "
                    "scénarios refi).",
                    0.0,
                    100.0,
                    1.0,
                    "inputs_manuels",
                ),
                (
                    "duree_projet_annees",
                    2.0,
                    "Durée du projet (années)",
                    "Durée typique chantier + lease-up avant refi. Utilisée "
                    "pour calculer L17 (intérêts pendant projet) et L18 "
                    "(revenus nets pendant projet).",
                    1.0,
                    10.0,
                    1.0,
                    "inputs_manuels",
                ),
                (
                    "nb_logements_ajoutes",
                    0.0,
                    "Logements ajoutés par défaut",
                    "Nombre de logements créés en moyenne par projet. "
                    "Pré-rempli sur les nouvelles fiches (modifiable).",
                    0.0,
                    50.0,
                    1.0,
                    "inputs_manuels",
                ),
                (
                    "nb_thermopompes_ajoutees",
                    0.0,
                    "Thermopompes ajoutées par défaut",
                    "Nombre de thermopompes installées en moyenne (impacte "
                    "uniquement les scénarios APH — efficacité énergétique).",
                    0.0,
                    50.0,
                    1.0,
                    "inputs_manuels",
                ),
                (
                    "taux_inoccupation_pct",
                    3.0,
                    "Taux d'inoccupation (%)",
                    "Pourcentage de perte de loyer hypothèse SCHL. Varie "
                    "par marché (3 % Montréal, plus en région).",
                    0.0,
                    30.0,
                    0.1,
                    "inputs_manuels",
                ),
                # ── Groupe : Frais MDF (one-shot) ────────────────────
                (
                    "frais_evaluateur",
                    1500.0,
                    "Évaluateur agréé ($)",
                    "Frais d'évaluation principal (un seul rapport).",
                    0.0,
                    20000.0,
                    50.0,
                    "mdf_frais",
                ),
                (
                    "frais_evaluateur_2",
                    1500.0,
                    "Évaluateur agréé 2 ($)",
                    "Deuxième évaluation (ex. refi SCHL exige souvent un "
                    "second évaluateur indépendant).",
                    0.0,
                    20000.0,
                    50.0,
                    "mdf_frais",
                ),
                (
                    "frais_inspection",
                    1700.0,
                    "Inspection ($)",
                    "Inspection préachat (bâtiment + mécanique).",
                    0.0,
                    20000.0,
                    50.0,
                    "mdf_frais",
                ),
                (
                    "frais_avocat",
                    4000.0,
                    "Avocat ($)",
                    "Honoraires juridiques (vérification diligente, "
                    "négociations, contrats).",
                    0.0,
                    50000.0,
                    50.0,
                    "mdf_frais",
                ),
                (
                    "frais_notaire",
                    1600.0,
                    "Notaire ($)",
                    "Frais de notaire pour l'acte d'achat (vente).",
                    0.0,
                    20000.0,
                    50.0,
                    "mdf_frais",
                ),
                (
                    "frais_notaire_2",
                    1600.0,
                    "Notaire 2 ($)",
                    "Frais de notaire pour l'acte de refinancement "
                    "(hypothèque SCHL/APH après projet).",
                    0.0,
                    20000.0,
                    50.0,
                    "mdf_frais",
                ),
                (
                    "frais_rapport_efficacite",
                    4500.0,
                    "Rapport d'efficacité énergétique ($)",
                    "Rapport requis pour les programmes SCHL APH 50/100 "
                    "(efficacité énergétique + abordabilité).",
                    0.0,
                    20000.0,
                    50.0,
                    "mdf_frais",
                ),
                (
                    "pct_courtier_hypothecaire_1",
                    1.0,
                    "Courtier hypothécaire 1 (% × prix d'achat)",
                    "Pourcentage facturé par le courtier hypothécaire sur "
                    "le prêt à l'achat. Défaut 1 %.",
                    0.0,
                    5.0,
                    0.05,
                    "mdf_frais",
                ),
                (
                    "pct_courtier_hypothecaire_2",
                    1.0,
                    "Courtier hypothécaire 2 (% × financement APH)",
                    "Pourcentage facturé par le courtier hypothécaire sur "
                    "le financement refi APH (post-projet). Défaut 1 %.",
                    0.0,
                    5.0,
                    0.05,
                    "mdf_frais",
                ),
                # ── Mai 2026 : Frais de dossier du prêteur B ──────────
                # Pourcentage appliqué au prêt initial du prêteur B
                # (= prix_achat × ltv_achat, 75 % typique). Stocké en
                # pct (2.0 = 2 %) comme les autres %. Non finançable par
                # défaut (Phil paie cash en pratique).
                (
                    "frais_dossier_preteur_pct",
                    2.0,
                    "Frais de dossier du prêteur (% × prêt initial)",
                    "Pourcentage facturé par le prêteur B sur le prêt "
                    "initial (= prix d'achat × LTV à l'achat, 75 % "
                    "typique). Défaut 2 %.",
                    0.0,
                    10.0,
                    0.05,
                    "mdf_frais",
                ),
                # ── Groupe : Dépenses normalisées SCHL (juin 2026) ───
                # Barème ``lead_analysis_finance.BAREME`` externalisé.
                # Valeurs = EXACTEMENT les constantes hardcoded. Les % de
                # gestion sont seedés en pct (4.25, 5.0) et reconvertis en
                # fraction (÷100) au runtime côté loader.
                (
                    "conciergerie_moins_12_log",
                    215.0,
                    "Conciergerie — moins de 12 log ($/log/an)",
                    "Frais de conciergerie normalisés par logement et par "
                    "an pour un immeuble de moins de 12 logements.",
                    0.0,
                    5000.0,
                    5.0,
                    "depenses_normalisees",
                ),
                (
                    "conciergerie_12_log_plus",
                    365.0,
                    "Conciergerie — 12 log et plus ($/log/an)",
                    "Frais de conciergerie normalisés par logement et par "
                    "an pour un immeuble de 12 logements ou plus.",
                    0.0,
                    5000.0,
                    5.0,
                    "depenses_normalisees",
                ),
                (
                    "entretien_par_log",
                    610.0,
                    "Entretien ($/log/an)",
                    "Frais d'entretien normalisés par logement et par an.",
                    0.0,
                    10000.0,
                    10.0,
                    "depenses_normalisees",
                ),
                (
                    "gestion_moins_12_pct",
                    4.25,
                    "Gestion — moins de 12 log (% des revenus)",
                    "Pourcentage des revenus alloué à la gestion pour un "
                    "immeuble de moins de 12 logements.",
                    0.0,
                    20.0,
                    0.05,
                    "depenses_normalisees",
                ),
                (
                    "gestion_12_log_plus_pct",
                    5.0,
                    "Gestion — 12 log et plus (% des revenus)",
                    "Pourcentage des revenus alloué à la gestion pour un "
                    "immeuble de 12 logements ou plus.",
                    0.0,
                    20.0,
                    0.05,
                    "depenses_normalisees",
                ),
                (
                    "wifi_par_log_mois",
                    5.0,
                    "WIFI ($/log/mois)",
                    "Coût WIFI normalisé par logement et par mois (ajouté "
                    "seulement aux scénarios refi si l'option WIFI est "
                    "activée).",
                    0.0,
                    100.0,
                    0.5,
                    "depenses_normalisees",
                ),
                (
                    "internet_batiment_mois",
                    120.0,
                    "Internet du bâtiment ($/mois)",
                    "Coût fixe de la connexion internet du bâtiment par "
                    "mois (ajouté seulement aux scénarios refi si l'option "
                    "WIFI est activée).",
                    0.0,
                    2000.0,
                    5.0,
                    "depenses_normalisees",
                ),
                (
                    "entretien_thermopompe_an",
                    190.0,
                    "Entretien thermopompe ($/thermopompe/an)",
                    "Coût d'entretien annuel par thermopompe ajoutée "
                    "(scénarios APH — efficacité énergétique uniquement).",
                    0.0,
                    5000.0,
                    5.0,
                    "depenses_normalisees",
                ),
                (
                    "seuil_bascule_bareme_log",
                    12.0,
                    "Seuil de bascule du barème (nb log)",
                    "Nombre de logements à partir duquel on bascule des "
                    "tarifs « petit immeuble » (conciergerie/gestion) vers "
                    "les tarifs « grand immeuble ». Défaut 12.",
                    1.0,
                    100.0,
                    1.0,
                    "depenses_normalisees",
                ),
        ):
            try:
                # UPSERT : on insère si la clé n'existe pas, sinon on
                # met UNIQUEMENT à jour les métadonnées (label, group,
                # bornes) — pas la `value_float` modifiée par Phil.
                await conn.execute(
                    text(
                        """
                        INSERT INTO prospection_analysis_defaults
                          (key, value_float, label_fr, description_fr,
                           min_value, max_value, step, group_name,
                           updated_at)
                        VALUES (:key, :value_float, :label_fr,
                                :description_fr, :mn, :mx, :step, :group,
                                NOW())
                        ON CONFLICT (key) DO UPDATE SET
                            label_fr       = EXCLUDED.label_fr,
                            description_fr = EXCLUDED.description_fr,
                            min_value      = EXCLUDED.min_value,
                            max_value      = EXCLUDED.max_value,
                            step           = EXCLUDED.step,
                            group_name     = EXCLUDED.group_name
                        """
                    ),
                    {
                        "key": key,
                        "value_float": value_float,
                        "label_fr": label_fr,
                        "description_fr": description_fr,
                        "mn": mn,
                        "mx": mx,
                        "step": step,
                        "group": group,
                    },
                )
            except Exception:
                # Table absente au tout premier boot (create_all n'a
                # pas encore tourné) — retentera au prochain démarrage.
                pass

        # ── Backfill `financable_par_defaut` (mai 2026) ──────────────
        # On ne TOUCHE PAS aux items pour lesquels Phil a déjà
        # configuré explicitement la valeur (NULL → on backfill, NOT
        # NULL → on respecte le choix admin). Idempotent au boot.
        #
        # Choix par défaut (cf. PR « mdf-frais-dossier-preteur-financable-defaut ») :
        #   - frais_evaluateur / _2          : True  (intégré au prêt SCHL)
        #   - frais_inspection               : False (payé hors prêt en pratique)
        #   - frais_avocat                   : True
        #   - frais_notaire / _2             : True
        #   - frais_rapport_efficacite       : True
        #   - pct_courtier_hypothecaire_1/_2 : True
        #   - frais_dossier_preteur_pct      : False (Phil paie cash)
        financable_par_defaut_seed: tuple[tuple[str, bool], ...] = (
            ("frais_evaluateur", True),
            ("frais_evaluateur_2", True),
            ("frais_inspection", False),
            ("frais_avocat", True),
            ("frais_notaire", True),
            ("frais_notaire_2", True),
            ("frais_rapport_efficacite", True),
            ("pct_courtier_hypothecaire_1", True),
            ("pct_courtier_hypothecaire_2", True),
            ("frais_dossier_preteur_pct", False),
        )
        for default_key, default_val in financable_par_defaut_seed:
            try:
                await conn.execute(
                    text(
                        """
                        UPDATE prospection_analysis_defaults
                           SET financable_par_defaut = :val
                         WHERE key = :key
                           AND financable_par_defaut IS NULL
                        """
                    ),
                    {"key": default_key, "val": default_val},
                )
            except Exception:
                # Table/colonne absente au premier boot — silencieux.
                pass

        # ── Seed des valeurs par défaut des soumissions devis_dev (Phase 6,
        # juin 2026) ─────────────────────────────────────────────────────
        # Table singleton `devlog_soumission_defaults` (id=1) créée par
        # `create_all`. On insère la ligne avec les valeurs historiques
        # (75/80/10/50/50, template vide) UNIQUEMENT si elle est absente —
        # ON CONFLICT DO NOTHING préserve les réglages déjà modifiés par
        # Phil depuis l'UI. Idempotent au boot. Plus aucun hard-code côté
        # application : la création d'une soumission lit cette ligne.
        try:
            await conn.execute(
                text(
                    """
                    INSERT INTO devlog_soumission_defaults
                      (id, taux_dev_horaire, taux_manager_horaire,
                       commission_closer_pct, marge_initiale_pct,
                       marge_recurrente_pct, base_modules_json, updated_at)
                    VALUES (1, 75, 80, 10, 50, 50, '[]'::jsonb, NOW())
                    ON CONFLICT (id) DO NOTHING
                    """
                )
            )
        except Exception:
            # Table absente au tout premier boot (create_all n'a pas encore
            # tourné) — retentera au prochain démarrage.
            pass


async def close_db() -> None:
    """
    Close database connections.

    Should be called on application shutdown.
    """
    await engine.dispose()




