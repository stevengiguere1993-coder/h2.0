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

# Non-root user pour la sécurité
USER pwuser

# Display virtuel pour Chrome headed
ENV DISPLAY=:99

EXPOSE 8000

# Lance Xvfb en background puis uvicorn. exec uvicorn permet la
# propagation des signaux (SIGTERM, etc) directement à uvicorn.
# >/dev/null pour que les logs Xvfb ne polluent pas docker logs.
CMD ["bash", "-c", "Xvfb :99 -screen 0 1280x800x24 -ac >/dev/null 2>&1 & sleep 1 && exec uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1"]
