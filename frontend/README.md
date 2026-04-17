# Horizon Services Immobiliers — Frontend

Next.js 15 (App Router) frontend for `immohorizon.com`.

## Dev

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

The app talks to the FastAPI backend defined by `NEXT_PUBLIC_API_BASE_URL`
(defaults to the deployed `https://h2-0.onrender.com`).

## Locales

- `/` → French (default)
- `/en` → English

Messages live in `messages/{locale}.json`.

## Build

```bash
npm run build && npm run start
```
