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
        )
        for table, column, col_type in additive_columns:
            await conn.execute(
                text(
                    f'ALTER TABLE {table} '
                    f'ADD COLUMN IF NOT EXISTS {column} {col_type}'
                )
            )

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
        ):
            try:
                await conn.execute(text(sql))
            except Exception:
                # Table absente / colonne pas encore migrée — on
                # passe sans bloquer le boot.
                pass


async def close_db() -> None:
    """
    Close database connections.

    Should be called on application shutdown.
    """
    await engine.dispose()
