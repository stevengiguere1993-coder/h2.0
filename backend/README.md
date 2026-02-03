# Construction Management Backend

Backend API pour le logiciel de gestion d'entreprise de construction.

## Stack Technique

- **Framework**: FastAPI
- **ORM**: SQLAlchemy 2.0 (async)
- **Base de données**: PostgreSQL
- **Migrations**: Alembic
- **Authentification**: JWT (préparé)

## Prérequis

- Python 3.11+
- PostgreSQL 14+
- pip ou poetry

## Installation

### 1. Cloner le repository

```bash
git clone <repository-url>
cd backend
```

### 2. Créer un environnement virtuel

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# ou
venv\Scripts\activate  # Windows
```

### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 4. Configurer les variables d'environnement

```bash
cp .env.example .env
# Éditer .env avec vos valeurs
```

### 5. Créer la base de données

```bash
# Se connecter à PostgreSQL
psql -U postgres

# Créer la base de données
CREATE DATABASE construction_db;
CREATE USER construction_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE construction_db TO construction_user;
\q
```

### 6. Appliquer les migrations

```bash
alembic upgrade head
```

### 7. Créer le premier admin

```bash
# Mode interactif (développement)
python -m scripts.create_admin

# Mode automatique (via variables d'environnement)
export ADMIN_EMAIL="admin@example.com"
export ADMIN_PASSWORD="securepassword123"
python -m scripts.init_admin
```

### 8. Lancer le serveur

```bash
# Développement
uvicorn app.main:app --reload --port 8000

# Production
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Commandes Alembic

```bash
# Créer une nouvelle migration
alembic revision --autogenerate -m "Description de la migration"

# Appliquer toutes les migrations
alembic upgrade head

# Revenir à la migration précédente
alembic downgrade -1

# Voir l'historique des migrations
alembic history

# Voir la migration actuelle
alembic current
```

## Structure du Projet

```
backend/
├── app/
│   ├── main.py              # Point d'entrée FastAPI
│   ├── api/                 # Routes API
│   │   └── v1/              # Version 1 de l'API
│   ├── core/                # Configuration et sécurité
│   │   ├── config.py        # Variables d'environnement
│   │   └── security.py      # Hashing et JWT
│   ├── db/                  # Configuration base de données
│   │   ├── base.py          # Base SQLAlchemy
│   │   └── session.py       # Sessions async
│   ├── models/              # Modèles SQLAlchemy
│   ├── repositories/        # Pattern Repository
│   ├── services/            # Logique métier
│   └── schemas/             # Schémas Pydantic
├── alembic/                 # Migrations
├── alembic.ini              # Configuration Alembic
├── requirements.txt         # Dépendances Python
├── render.yaml              # Configuration Render
└── .env.example             # Template variables d'environnement
```

## Déploiement sur Render

1. Connecter le repository GitHub à Render
2. Créer un nouveau "Blueprint" avec le fichier `render.yaml`
3. Configurer les variables d'environnement dans le dashboard Render
4. Le déploiement est automatique à chaque push

## API Documentation

Une fois le serveur lancé, la documentation est disponible :

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Endpoints Disponibles

### Root
| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/` | Message de bienvenue |
| GET | `/health` | Health check |
| GET | `/docs` | Documentation Swagger |

### Authentification
| Méthode | Endpoint | Description | Accès |
|---------|----------|-------------|-------|
| POST | `/api/v1/auth/login` | Connexion | Public |
| POST | `/api/v1/auth/register` | Créer un utilisateur | Admin |
| GET | `/api/v1/auth/me` | Profil utilisateur | Authentifié |

### Clients
| Méthode | Endpoint | Description | Accès |
|---------|----------|-------------|-------|
| POST | `/api/v1/clients` | Créer un client | Admin |
| GET | `/api/v1/clients` | Liste des clients | Authentifié |
| GET | `/api/v1/clients/{id}` | Détail d'un client | Authentifié |
| PUT | `/api/v1/clients/{id}` | Modifier un client | Admin |
| DELETE | `/api/v1/clients/{id}` | Supprimer un client | Admin |

### Projets
| Méthode | Endpoint | Description | Accès |
|---------|----------|-------------|-------|
| POST | `/api/v1/projects` | Créer un projet | Admin |
| GET | `/api/v1/projects` | Liste des projets | Authentifié |
| GET | `/api/v1/projects/{id}` | Détail d'un projet | Authentifié |
| PUT | `/api/v1/projects/{id}` | Modifier un projet | Admin |
| DELETE | `/api/v1/projects/{id}` | Supprimer un projet | Admin |

## Variables d'Environnement

| Variable | Description | Requis |
|----------|-------------|--------|
| `ENV` | Environnement (development/production) | Oui |
| `PORT` | Port du serveur | Oui |
| `DATABASE_URL` | URL de connexion PostgreSQL | Oui |
| `JWT_SECRET` | Clé secrète pour JWT | Oui |
| `JWT_ALGORITHM` | Algorithme JWT (HS256) | Non |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Durée de validité token | Non |
| `ADMIN_EMAIL` | Email du premier admin (init) | Non |
| `ADMIN_PASSWORD` | Mot de passe du premier admin (init) | Non |

## Licence

Propriétaire - Tous droits réservés
