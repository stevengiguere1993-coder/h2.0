# Immo Horizon — frontend (Next.js 15)

Site public bilingue (FR / EN) et portail interne pour Horizon Services Immobiliers.

## Stack

- Next.js 15 App Router + React 19
- TypeScript strict
- Tailwind CSS + tokens brand Horizon
- `next-intl` pour la i18n FR/EN
- Consomme l'API FastAPI déployée sur Render (`NEXT_PUBLIC_API_BASE_URL`)

## Développement

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

## Build / start (Render)

```bash
npm install
npm run build
npm run start
```

Le `start` écoute sur `$PORT` (injecté par Render).
