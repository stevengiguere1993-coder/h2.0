# Horizon Services Immobiliers — h2.0

Monorepo pour le site public + portail interne de **Horizon Services
Immobiliers** (immohorizon.com, immohorizon.ca).

## Structure

```
h2.0/
├── backend/          FastAPI + PostgreSQL + SQLAlchemy async + Alembic
├── frontend/         Next.js 15 + TypeScript + Tailwind + next-intl (FR/EN)
└── render.yaml       Blueprint Render : 1 API, 1 web, 1 cron quotidien
```

## Services Render

| Service | Rôle | Techno |
|---|---|---|
| `h2-0` | API publique + interne | FastAPI / Python 3.11 |
| `h2-0-web` | Site public + portail interne | Next.js 15 / Node 20 |
| `h2-0-seo-daily` | Génération quotidienne d'articles SEO | Python cron |

## Domaines

- **Principal** : `https://immohorizon.com`
- **Alternatif** : `https://immohorizon.ca` (301 → .com)
- API : `https://h2-0.onrender.com`

## Démarrage local

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # éditer DATABASE_URL et JWT_SECRET
uvicorn app.main:app --reload
# http://localhost:8000/docs
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local     # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev
# http://localhost:3000
```

## Déploiement

Voir **[DEPLOYMENT.md](./DEPLOYMENT.md)** pour les étapes précises de
création des services Render et de configuration DNS Squarespace.
