"""Conftest racine de la suite backend.

Pose les variables d'environnement FACTICES avant TOUT import de l'app.
`app.core.config.Settings` (pydantic-settings) est instancié au premier
import — il lit l'environnement à ce moment-là. Ce fichier est importé
par pytest avant tout module de test, ce qui garantit l'ordre.

Points clés :
- DATABASE_URL pointe sur un fichier SQLite temporaire (aiosqlite) :
  les smoke tests (tests/smoke/) tournent sans Postgres. Les tests purs
  (tests/services/) ne touchent pas la DB et s'en fichent.
- Les clés d'intégrations externes (IA, QBO, Twilio, Graph, Stripe…)
  sont FORCÉES à vide : même si un `.env` local existe avec de vraies
  clés, les env vars posées ici priment (pydantic-settings donne la
  priorité à l'environnement sur le fichier .env). Aucun appel réseau
  réel ne peut donc partir pendant les tests.

NE MODIFIE AUCUN CODE DE PRODUCTION — fichier de test uniquement.
"""

import os
import tempfile
from pathlib import Path

# Répertoire temporaire dédié à cette exécution de tests (un fichier
# SQLite par run : pas d'état partagé entre deux runs).
_TMP_DIR = Path(tempfile.mkdtemp(prefix="kratos-tests-"))
SMOKE_DB_PATH = _TMP_DIR / "smoke.db"

# ── Env vars minimales exigées par Settings ─────────────────────────
# Assignation FORCÉE (pas setdefault) : les tests ne doivent JAMAIS
# toucher une vraie base, même si l'appelant a exporté DATABASE_URL.
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{SMOKE_DB_PATH.as_posix()}"
os.environ["JWT_SECRET"] = "smoke-test-secret-not-for-prod"
os.environ["ENV"] = "test"

# ── Neutralisation des intégrations externes ────────────────────────
# Chaîne vide = falsy pour tous les checks `if settings.xxx_api_key`.
for _key in (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "AI_PROVIDER",
    "QUICKBOOKS_CLIENT_ID",
    "QUICKBOOKS_CLIENT_SECRET",
    "QBO_REFRESH_TOKEN",
    "QBO_REALM_ID",
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "MONDAY_API_TOKEN",
    "CRON_SECRET",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "TEAMS_MEETING_USER_EMAILS",
):
    os.environ[_key] = ""
