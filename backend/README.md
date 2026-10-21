# CodeMind AI — Backend Architecture & Service Layer

This directory houses the backend application, REST API routes, data persistence, migrations, and test suites for CodeMind AI.

## Structure

```text
backend/
├── app/
│   ├── api/routes/         # Endpoints: health, api_v1 (me, repos, dashboard), views
│   ├── core/               # Configuration settings and environment variables
│   ├── db/                 # Database engine, sessionmaker, and connectivity checks
│   ├── models/             # SQLAlchemy ORM models (User, Repository, IndexingJob)
│   ├── schemas/            # Pydantic v2 validation models
│   ├── main.py             # FastAPI entry point, static mount, lifecycle hooks
│   └── ...                 # Ingestion, parsing, graph, retrieval (Phases 3+)
├── migrations/             # Alembic migration environment and version scripts
├── tests/                  # Automated pytest test suites
├── alembic.ini             # Alembic configuration
├── requirements.txt        # Backend dependencies
└── .env.example            # Environment configuration template
```

## Quick Start (PowerShell)

```powershell
# Install dependencies
pip install -r backend/requirements.txt

# Run migrations
$env:PYTHONPATH = "."
alembic -c backend/alembic.ini upgrade head

# Launch dev server
python -m uvicorn backend.app.main:app --reload --port 8000
```
