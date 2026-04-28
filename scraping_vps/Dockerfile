FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

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

# Démarrage. workers=1 pour limiter l'empreinte RAM (Chromium est
# déjà gros). Sur CPX11 (2 GB) c'est nécessaire ; sur CPX21+ (4 GB)
# on peut passer à workers=2 sans risque.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
