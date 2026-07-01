"""
Application configuration using Pydantic Settings.

All configuration is loaded from environment variables.
No hardcoded secrets or sensitive values.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment
    env: str = "development"
    port: int = 8000
    debug: bool = False

    # Database
    database_url: str

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    # Security
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    # Durée de session par défaut (sans « Rester connecté »). 24 h pour un
    # outil interne : on évite que les équipes soient déconnectées en
    # pleine journée. « Rester connecté » étend à 30 jours (cf. AuthService).
    access_token_expire_minutes: int = 60 * 24

    # Frontend origins (comma-separated) for CORS in production
    frontend_origins: Optional[str] = None

    # S3 Storage (optional)
    s3_endpoint: Optional[str] = None
    s3_bucket: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None

    # QuickBooks Integration (optional)
    quickbooks_client_id: Optional[str] = None
    quickbooks_client_secret: Optional[str] = None
    quickbooks_env: str = "sandbox"
    qbo_refresh_token: Optional[str] = None
    qbo_realm_id: Optional[str] = None
    # Jeton de vérification du webhook QBO (« Webhooks verifier token » dans
    # le portail Intuit). Sert à valider la signature intuit-signature des
    # notifications QBO → Kratos (reverse-sync : maj mode de paiement + date
    # d'un achat quand la dépense est rapprochée dans QuickBooks).
    qbo_webhook_verifier_token: Optional[str] = None
    # Id du code de taxe QBO à appliquer sur chaque ligne d'achat
    # (reçu de dépense). Requis si la compagnie utilise la taxe de vente
    # automatisée (« Tous les articles ont besoin d'un taux de taxe »).
    # Récupère l'Id via le bouton « Lister codes de taxe » / endpoint
    # /qbo/tax-codes (ex. TPS/TVQ QC).
    qbo_purchase_tax_code: Optional[str] = None
    # Id du code de taxe QBO à appliquer sur chaque ligne de FACTURE de
    # vente. Requis si la compagnie utilise la taxe de vente automatisée
    # (erreur 6000 « toutes vos opérations comprennent un taux de TPS/TVH »).
    # Récupère l'Id via « Lister codes de taxe » (ex. TPS/TVQ QC).
    qbo_sales_tax_code: Optional[str] = None
    # Active l'API Projets QuickBooks (GraphQL) pour CRÉER de vrais projets
    # (onglet Projets) depuis Kratos. Désactivé par défaut : tant que l'app
    # Intuit n'a pas l'accès Premium API + le scope, demander ce scope au
    # consentement OAuth peut faire ÉCHOUER la reconnexion. À passer à true
    # seulement une fois l'accès Premium accordé (puis se reconnecter).
    qbo_enable_projects_api: bool = False
    # Courriel de la commis comptable : reçoit une alerte à chaque
    # création de projet construction, avec le nom du sous-client QBO à
    # convertir en « Projet » dans QuickBooks (l'API ne pouvant pas le
    # faire sans accès Premium). Vide = pas d'envoi.
    bookkeeper_email: Optional[str] = None
    # OAuth redirect URI — doit être enregistrée à l'identique dans
    # l'app Intuit (onglet Keys & credentials → Redirect URIs).
    # Pointe sur le backend (h2-0), pas sur le frontend (h2-0-web).
    quickbooks_redirect_uri: str = (
        "https://h2-0.onrender.com/api/v1/qbo/callback"
    )
    # URL du frontend pour rediriger l'utilisateur après le callback
    # OAuth Intuit. Défaut = domaine de production (immohorizon.com).
    # Override via l'env var FRONTEND_URL si on veut tester contre un
    # autre domaine (preview Render, local, etc.).
    frontend_url: str = "https://immohorizon.com"

    # Microsoft Graph (email)
    azure_tenant_id: Optional[str] = None
    azure_client_id: Optional[str] = None
    azure_client_secret: Optional[str] = None
    mail_from_email: str = "info@immohorizon.com"
    mail_from_name: str = "Horizon Services Immobiliers"
    # Adresse mise en copie cachée (BCC) sur les courriels sortants
    # destinés à l'externe (clients, fournisseurs…). Désactivé par
    # défaut : on ne copie plus automatiquement info@/sgiguere@ sur les
    # envois clients (un CC explicite est ajouté au besoin avant l'envoi
    # et reste consultable). Pour réactiver une copie de supervision,
    # définir l'env var CLIENT_EMAIL_BCC="adresse@…". Les envois marqués
    # `internal=True` (codes/tests d'auth, rappels au personnel) en sont
    # de toute façon exclus.
    client_email_bcc: str = ""

    # Adresse « agenda » : reçoit une invitation calendrier (.ics) pour
    # CHAQUE rendez-vous prospect planifié, même quand le RDV n'est
    # assigné à personne — pour que le RDV atterrisse toujours dans
    # l'agenda du propriétaire. Vider (env APPOINTMENT_OWNER_EMAIL="")
    # désactive cet envoi.
    appointment_owner_email: str = "sgiguere@immohorizon.com"

    # Cron triggers — secret partagé avec GitHub Actions /
    # cron-job.org pour authentifier les hits HTTP qui lancent les
    # jobs (alternative gratuite aux Render Cron Jobs payants).
    cron_secret: Optional[str] = None

    # Anthropic (SEO content + validation — usage hors extraction lead)
    anthropic_api_key: Optional[str] = None
    claude_model: str = "claude-sonnet-4-5"
    # Feature flag pour la ré-extraction Claude (Couche 3, payante).
    # OFF par défaut depuis le passage à Groq (gratuit) en mai 2026.
    # Mettre à True pour réactiver l'endpoint /re-extract-with-claude
    # et afficher un bouton secondaire dans le frontend.
    claude_reextract_enabled: bool = False

    # Gemini (Google AI Studio) — extraction des leads immobiliers
    # (URLs, texte libre, images, PDFs). Tier gratuit : 1500 req/jour.
    # Générer une clé : https://aistudio.google.com/app/apikey
    gemini_api_key: Optional[str] = None
    # Cascade de modèles Gemini à essayer en chaîne quand l'un d'eux
    # tombe en quota (chaque modèle a son propre RPM). Format : liste
    # de noms séparés par virgule. Défaut couvre les 4 modèles texte
    # actuellement gratuits sur Google AI Studio.
    gemini_model_cascade: str = (
        "gemini-2.5-flash,gemini-2.5-pro,gemini-2.0-flash"
    )

    # Groq (Llama 3.3 70B) — remplaçant gratuit de Claude pour la
    # ré-extraction manuelle. Tier gratuit : 14 400 req/jour, sans CB.
    # Générer une clé : https://console.groq.com → API Keys.
    groq_api_key: Optional[str] = None
    groq_model: str = "llama-3.3-70b-versatile"

    # SLA : un nouveau prospect doit être contacté dans les X heures
    # qui suivent sa création, sinon une notif rouge fan-out aux
    # managers+ et le lead apparaît marqué « SLA dépassé » dans la
    # queue. Override via env SLA_FIRST_CONTACT_HOURS.
    sla_first_contact_hours: int = 4

    # Monday integration (migration + live bridge while the portal is built)
    monday_api_token: Optional[str] = None
    # Default board for incoming contact submissions.
    # 18400565505 = CRM Soumissions (Horizon Construction workspace).
    monday_crm_board_id: Optional[int] = 18400565505

    # Téléphonie — provider voix (Twilio par défaut). Voir
    # app/integrations/voice/ et app/api/v1/endpoints/voice.py.
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    # Numéro principal (E.164, ex. "+14388002979") — pour le bootstrap.
    twilio_phone_number: Optional[str] = None
    # Mobile vers lequel forwarder les appels entrants en Phase 1, en
    # attendant que la secrétaire IA prenne le relais (Phase 2).
    twilio_forward_to: Optional[str] = None
    # URL backend que Twilio appellera pour les webhooks. Le script de
    # bootstrap (`python -m app.scripts.twilio_bootstrap`) la pousse
    # sur le numéro via l'API Twilio.
    voice_webhook_base_url: str = "https://h2-0.onrender.com"
    # Twilio Voice SDK (hybride web + mobile). Setup manuel dans la
    # console Twilio : voir app/integrations/voice/voice_sdk.py.
    # Sans ces 3 vars, le portail tombe sur le mode mobile-only.
    twilio_twiml_app_sid: Optional[str] = None
    twilio_api_key_sid: Optional[str] = None
    twilio_api_key_secret: Optional[str] = None

    # SMS entrant hors heures d'ouverture — réponse automatique. Quand un
    # client texte la ligne de l'entreprise alors que les bureaux sont
    # fermés (selon VoiceBusinessHours), on renvoie ce message une fois,
    # sauf si on lui a déjà écrit dans les 10 dernières minutes
    # (conversation active). Chaîne vide => fonctionnalité désactivée.
    # Modifiable sans redéploiement via l'env SMS_AFTER_HOURS_AUTO_REPLY.
    sms_after_hours_auto_reply: str = (
        "Bonjour! Ceci est un message automatique de la ligne d'Horizon "
        "Services Immobiliers. Nos bureaux sont présentement fermés — un "
        "membre de notre équipe vous répondra dès que possible durant les "
        "heures d'ouverture. Merci!"
    )
    # Fenêtre (minutes) : si on a envoyé un SMS à ce numéro dans ce délai,
    # on NE renvoie PAS la réponse auto (la personne répond à un échange
    # en cours). Sert aussi d'anti-spam : la réponse auto comptant comme
    # un message envoyé, les SMS suivants du client dans la fenêtre sont
    # ignorés.
    sms_after_hours_suppress_minutes: int = 10

    # Stripe — paiement en ligne des factures Dev logiciel via
    # Checkout hosted (PR chantier #4, mai 2026). Voir
    # `app/services/devlog_stripe.py`.
    # Clés secrètes (sk_live_... + whsec_...) à provisionner sur
    # Render avant le premier paiement ; tant qu'elles sont absentes,
    # la création de session répond 503 et le webhook 503.
    stripe_secret_key: Optional[str] = None
    stripe_webhook_secret: Optional[str] = None
    # Clé publique (pk_live_...) — utile si on passe un jour à
    # Stripe.js côté frontend. Avec le mode Checkout hosted, le
    # frontend n'a besoin de rien : on lui retourne déjà l'URL
    # hostée par Stripe.
    stripe_publishable_key: Optional[str] = None
    # Base d'URL des success/cancel URLs Stripe : on y append
    # `/{token}?paid=1` (ou `?cancelled=1`). Le domaine peut
    # changer entre prod (kratos.immohorizon.com) et un éventuel
    # preview Render — d'où la variable.
    stripe_devlog_success_url_base: str = (
        "https://kratos.immohorizon.com/fr/devlog/pay-invoice"
    )
    # Feature flag pour activer/desactiver le bouton Stripe sur la page
    # publique de paiement de facture. OFF par defaut (mai 2026) — le
    # client est invite a payer par virement Interac en priorite. Mettre
    # a True pour reactiver le bouton Stripe sans toucher au code.
    stripe_enabled: bool = False
    # Email destinataire pour les virements Interac affiches sur la page
    # publique de paiement de facture devlog.
    devlog_interac_email: str = "philippe.meuser@immohorizon.com"

    # Google Drive Integration (Phase 1 — Foundation OAuth, juin 2026).
    # Permet à chaque utilisateur de connecter son compte Google et
    # d'accéder à son Drive depuis Kratos. Cf. docs/DRIVE_INTEGRATION.md
    # pour la procédure de configuration côté Google Cloud Console.
    #
    # Whitelist d'emails (mode OAuth "Testing") : 3 partners
    # philippe.meuser@, sgiguere@, mvilliard@immohorizon.com.
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    # OAuth redirect URI — doit être enregistrée à l'identique dans la
    # Google Cloud Console (APIs & Services → Credentials → OAuth 2.0
    # Client ID → Authorized redirect URIs).
    # Pointe sur le backend (h2-0), pas sur le frontend.
    google_redirect_uri: str = (
        "https://h2-0.onrender.com/api/v1/drive/auth/callback"
    )
    # Clé Fernet (base64 32 bytes) utilisée pour chiffrer les
    # access_token / refresh_token Drive avant de les écrire dans la BDD.
    # Générer une clé :
    #   python -c "from cryptography.fernet import Fernet; \
    #              print(Fernet.generate_key().decode())"
    # Si absente, fallback base64 NON CHIFFRÉ (dev only) avec WARNING.
    # À configurer OBLIGATOIREMENT sur Render avant le premier connect.
    drive_token_encryption_key: Optional[str] = None

    # Clé Fernet dédiée au coffre « Abonnements » (mots de passe). Si
    # absente, repli sur drive_token_encryption_key. Si AUCUNE des deux
    # n'est configurée, le coffre REFUSE de stocker un mot de passe
    # (jamais de clair) — cf. app.services.secret_vault.
    subscription_encryption_key: Optional[str] = None

    # Synchro Teams → Rencontres : boîtes (organisateurs) dont on scanne
    # le calendrier pour importer les rencontres Teams transcrites.
    # Liste séparée par virgules, ex. "phil@x.com,steven@x.com".
    # Vide = synchro désactivée. Réutilise l'app Azure du mailer
    # (AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET) avec les
    # permissions Calendars.Read + OnlineMeetings.Read.All +
    # OnlineMeetingTranscript.Read.All (+ application access policy).
    teams_meeting_user_emails: str = ""

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.env.lower() == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
