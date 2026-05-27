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
    access_token_expire_minutes: int = 30

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
        "gemini-2.0-flash,gemini-1.5-flash,"
        "gemini-2.5-pro,gemini-1.5-pro"
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
