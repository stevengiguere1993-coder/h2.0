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

    # Anthropic (SEO content + validation)
    anthropic_api_key: Optional[str] = None
    claude_model: str = "claude-sonnet-4-5"

    # Monday integration (migration + live bridge while the portal is built)
    monday_api_token: Optional[str] = None
    # Default board for incoming contact submissions.
    # 18400565505 = CRM Soumissions (Horizon Construction workspace).
    monday_crm_board_id: Optional[int] = 18400565505

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
