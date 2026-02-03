# Architecture Phase 1 - Documentation Technique

## Vue d'ensemble

Ce document décrit l'architecture technique mise en place pour la Phase 1 du logiciel de gestion d'entreprise de construction.

## Stack Technique

| Composant | Technologie | Version |
|-----------|-------------|---------|
| Langage | Python | 3.11+ |
| Framework Web | FastAPI | 0.109+ |
| ORM | SQLAlchemy | 2.0+ |
| Driver DB | asyncpg | 0.29+ |
| Migrations | Alembic | 1.13+ |
| Auth (préparé) | python-jose + passlib | 3.3+ / 1.7+ |
| Configuration | pydantic-settings | 2.1+ |
| Base de données | PostgreSQL | 14+ |

## Structure du Projet

```
backend/
├── app/
│   ├── __init__.py              # Package principal, version
│   ├── main.py                  # Point d'entrée FastAPI
│   │
│   ├── api/                     # Couche API
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       └── router.py        # Router principal v1
│   │
│   ├── core/                    # Configuration et utilitaires
│   │   ├── __init__.py
│   │   ├── config.py            # Gestion des variables d'environnement
│   │   └── security.py          # Hashing et JWT
│   │
│   ├── db/                      # Configuration base de données
│   │   ├── __init__.py
│   │   ├── base.py              # Base SQLAlchemy + mixins
│   │   └── session.py           # Sessions async + dependency
│   │
│   ├── models/                  # Modèles SQLAlchemy
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── client.py
│   │   └── project.py
│   │
│   ├── repositories/            # Couche d'accès aux données (préparé)
│   │   └── __init__.py
│   │
│   ├── services/                # Logique métier (préparé)
│   │   └── __init__.py
│   │
│   └── schemas/                 # Schémas Pydantic (préparé)
│       └── __init__.py
│
├── alembic/                     # Migrations de base de données
│   ├── versions/                # Scripts de migration
│   ├── env.py                   # Configuration Alembic async
│   ├── script.py.mako           # Template de migration
│   └── README
│
├── alembic.ini                  # Configuration Alembic
├── requirements.txt             # Dépendances Python
├── render.yaml                  # Configuration déploiement Render
├── .env.example                 # Template variables d'environnement
├── README.md                    # Documentation d'installation
└── ARCHITECTURE_PHASE1.md       # Ce document
```

## Choix Architecturaux

### 1. Clean Architecture

L'application suit les principes de la Clean Architecture avec une séparation claire des responsabilités :

```
┌─────────────────────────────────────────────┐
│                   API Layer                  │
│              (routes, endpoints)             │
├─────────────────────────────────────────────┤
│                Service Layer                 │
│             (business logic)                 │
├─────────────────────────────────────────────┤
│              Repository Layer                │
│              (data access)                   │
├─────────────────────────────────────────────┤
│                Model Layer                   │
│            (SQLAlchemy models)               │
├─────────────────────────────────────────────┤
│                 Database                     │
│               (PostgreSQL)                   │
└─────────────────────────────────────────────┘
```

### 2. Async-First

Toute la stack est conçue pour être asynchrone :
- FastAPI avec support natif async
- SQLAlchemy 2.0 avec asyncpg
- Sessions de base de données async

### 3. Configuration Centralisée

Utilisation de `pydantic-settings` pour :
- Validation des variables d'environnement
- Typage fort des configurations
- Support des fichiers `.env`
- Aucun secret hardcodé

### 4. Sécurité Préparée

Les utilitaires de sécurité sont prêts mais pas exposés via endpoints :
- Hashing de mots de passe avec bcrypt
- Création et vérification de tokens JWT
- Configuration des durées de validité

## Modèles de Données

### Diagramme Entité-Relation

```
┌──────────────┐
│     User     │
├──────────────┤
│ id (PK)      │
│ email        │
│ hashed_pwd   │
│ is_active    │
│ is_admin     │
│ created_at   │
└──────────────┘

┌──────────────┐       ┌──────────────┐
│    Client    │       │   Project    │
├──────────────┤       ├──────────────┤
│ id (PK)      │──────<│ id (PK)      │
│ name         │   1:N │ name         │
│ created_at   │       │ client_id(FK)│
└──────────────┘       │ created_at   │
                       └──────────────┘
```

### User

| Champ | Type | Contraintes |
|-------|------|-------------|
| id | Integer | PK, auto-increment |
| email | String(255) | unique, not null |
| hashed_password | String(255) | not null |
| is_active | Boolean | default: true |
| is_admin | Boolean | default: false |
| created_at | DateTime(tz) | auto |

### Client

| Champ | Type | Contraintes |
|-------|------|-------------|
| id | Integer | PK, auto-increment |
| name | String(255) | not null, indexed |
| created_at | DateTime(tz) | auto |

### Project

| Champ | Type | Contraintes |
|-------|------|-------------|
| id | Integer | PK, auto-increment |
| name | String(255) | not null, indexed |
| client_id | Integer | FK → clients.id, cascade |
| created_at | DateTime(tz) | auto |

## Configuration des Variables d'Environnement

### Variables Requises

| Variable | Description | Exemple |
|----------|-------------|---------|
| `ENV` | Environnement | `development` / `production` |
| `PORT` | Port du serveur | `8000` |
| `DATABASE_URL` | URL PostgreSQL | `postgresql+asyncpg://...` |
| `JWT_SECRET` | Clé secrète JWT | (généré aléatoirement) |

### Variables Optionnelles

| Variable | Description | Défaut |
|----------|-------------|--------|
| `JWT_ALGORITHM` | Algorithme JWT | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Durée token | `30` |
| `S3_*` | Configuration S3 | (vide) |
| `QUICKBOOKS_*` | Configuration QB | (vide) |

## Déploiement Render

### Configuration (render.yaml)

Le fichier `render.yaml` configure :
- Service web Python
- Base de données PostgreSQL
- Variables d'environnement
- Health check sur `/health`

### Étapes de Déploiement

1. Connecter le repository GitHub à Render
2. Créer un Blueprint depuis `render.yaml`
3. Configurer `DATABASE_URL` avec l'URL de la base Render
4. Déclencher le déploiement

### Commandes de Build

```bash
# Build
pip install -r requirements.txt

# Start
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Commandes de Développement

### Installation

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Éditer .env
```

### Migrations

```bash
# Créer une migration
alembic revision --autogenerate -m "Description"

# Appliquer les migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Lancer le Serveur

```bash
# Développement (avec reload)
uvicorn app.main:app --reload --port 8000

# Production
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Prochaines Phases

### Phase 2 - Authentification
- Endpoints de login/register
- Middleware JWT
- Gestion des sessions

### Phase 3 - CRUD de Base
- Endpoints pour User, Client, Project
- Validation des données
- Pagination

### Phase 4 - Logique Métier
- Services métier
- Règles de validation
- Workflow de projets

### Phase 5 - Intégrations
- QuickBooks
- Stockage S3
- Notifications

## Points d'Extension

L'architecture est conçue pour être extensible :

1. **Nouveaux Modèles** : Ajouter dans `app/models/` et importer dans `__init__.py`
2. **Nouveaux Endpoints** : Créer des routers dans `app/api/v1/` et inclure dans le router principal
3. **Services** : Implémenter dans `app/services/` pour la logique métier
4. **Repositories** : Créer dans `app/repositories/` pour abstraire l'accès aux données

## Conclusion

Cette Phase 1 établit une fondation solide et professionnelle pour le développement futur. L'architecture suit les meilleures pratiques de l'industrie et est prête pour la scalabilité.
