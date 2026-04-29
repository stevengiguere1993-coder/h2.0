FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

# Xvfb pour faire tourner Chrome en mode "headed" sur le serveur
# (display virtuel) — score reCAPTCHA v3 beaucoup plus élevé qu'en
# headless pur. Headless est blacklisté par les sites protégés.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*

# Dependencies Python
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Code
COPY . /app

# Non-root user pour la sécurité (Playwright a besoin d'un user
# avec un home dir pour Chromium)
USER pwuser

# Port exposé
EXPOSE 8000

# Démarrage avec xvfb-run qui crée un display virtuel et lance
# uvicorn dedans. Chrome se lance en mode headed (sans GUI réelle
# mais sans flag --headless) → reCAPTCHA score beaucoup mieux.
# workers=1 pour CPX11 (2 GB) — Chromium prend 500-700 MB.
CMD ["xvfb-run", "-a", "--server-args=-screen 0 1280x800x24", \
     "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1"]
