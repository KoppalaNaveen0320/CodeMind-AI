# CodeMind AI — Production Deployment & Operations Guide

## 1. System Overview & Architecture

CodeMind AI is an enterprise-grade repository intelligence and code architecture understanding platform. The system operates as a hybrid retrieval-augmented generation (RAG) and knowledge-graph engine built with:

- **Backend Runtime:** Python 3.12+ with FastAPI and Starlette.
- **Database Engine:** PostgreSQL 16 with the `pgvector` extension for high-performance 768-dimensional vector similarity indexing.
- **Database Migrations:** Alembic (current head: `009_phase3_incremental_indexing`).
- **AST Parsing Engine:** Tree-sitter for multi-language AST extraction (Python, JavaScript, TypeScript, Go, Rust, Java, C, C++).
- **Local AI Runtimes:** Ollama hosting:
  - Embeddings: `nomic-embed-text` (768-dimensional normalized vector embeddings).
  - LLM Inference: `qwen2.5:3b` (contextual answering, query analysis, reasoning).
- **Security Boundary:** Multi-layer defense with SSRF protection, Zip Slip and decompression bomb validation, strict IDOR authorization, in-memory sliding-window rate limiting, and masked diagnostic logs.

---

## 2. Prerequisites & Dependencies

### Operating System & Core Runtimes
- Linux (Ubuntu 22.04 LTS / Debian 12 / RHEL 9) or Windows Server 2022.
- Python 3.12 or newer.
- Git (configured in system PATH).
- Docker and Docker Compose (recommended for containerized deployments).

### Required AI Runtimes (Ollama)
Ollama must be installed either natively on the host machine or in a network-accessible container.

Verify Ollama installation and download the required models:
```bash
# Pull 768-dimensional embedding model
ollama pull nomic-embed-text

# Pull LLM generation model
ollama pull qwen2.5:3b

# Verify models are loaded
ollama list
```

---

## 3. Environment Configuration

Copy `.env.example` to `backend/.env` and update the values:

```ini
# Application Core
APP_NAME=CodeMind AI
APP_ENV=production
APP_PORT=8000
DEBUG=false
REQUIRE_AUTH=true

# Security Keys (Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))")
SECRET_KEY=YOUR_SECURE_GENERATED_SECRET_KEY_AT_LEAST_32_CHARS

# Database (PostgreSQL 16 with pgvector)
DATABASE_URL=postgresql+psycopg2://codemind_user:secure_password@localhost:5432/codemind_db
ALLOW_SQLITE_FALLBACK=false

# Ollama Runtime
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:3b
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSION=768

# Repository & Ingestion Limits
INDEXING_MAX_FILES=2000
INDEXING_MAX_FILE_SIZE_BYTES=524288          # 500 KB per file
INDEXING_MAX_REPO_SIZE_BYTES=104857600       # 100 MB max archive upload
MAX_EXTRACTED_SIZE_BYTES=262144000           # 250 MB max uncompressed archive
MAX_ARCHIVE_FILE_COUNT=5000                  # Max file entries per archive
INDEXING_TIMEOUT_SECONDS=180

# Rate Limiting Controls
RATE_LIMIT_ENABLED=true
RATE_LIMIT_AUTH_PER_MINUTE=15
RATE_LIMIT_INDEXING_PER_MINUTE=10
RATE_LIMIT_ASSISTANT_PER_MINUTE=30
RATE_LIMIT_DEFAULT_PER_MINUTE=120
```

---

## 4. Database Setup & Alembic Migrations

### 1. Initialize PostgreSQL and Enable pgvector
Connect to your PostgreSQL 16 cluster as a superuser:
```sql
CREATE DATABASE codemind_db;
CREATE USER codemind_user WITH ENCRYPTED PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE codemind_db TO codemind_user;
\c codemind_db
CREATE EXTENSION IF NOT EXISTS vector;
GRANT ALL ON SCHEMA public TO codemind_user;
```

### 2. Apply Alembic Migrations
Run Alembic from the project root:
```bash
# Check current migration revision
alembic current

# Run migrations to head
alembic upgrade head

# Expected head revision: 009_phase3_incremental_indexing
```

---

## 5. Deployment Options

### Option A: Docker Compose (Recommended)

CodeMind AI includes a production `docker-compose.yml` that provisions PostgreSQL 16 with `pgvector` alongside the hardened FastAPI backend.

```bash
# 1. Build and start containers in the background
docker compose up -d --build

# 2. Verify container statuses
docker compose ps

# 3. View live application logs
docker compose logs -f backend
```

> **Note on Ollama in Docker:** The compose configuration routes `OLLAMA_BASE_URL` to `http://host.docker.internal:11434` via `extra_hosts: host.docker.internal:host-gateway`. Ensure Ollama on the host machine is running and listening on `11434` (or configured via `OLLAMA_HOST=0.0.0.0`).

### Option B: Bare-Metal / Systemd Service

#### 1. Install Dependencies
```bash
python -m venv .venv
source .venv/bin/activate  # Or .venv\Scripts\activate on Windows
pip install --upgrade pip
pip install -r backend/requirements.txt
```

#### 2. Run Database Migrations
```bash
alembic upgrade head
```

#### 3. Create Systemd Service (`/etc/systemd/system/codemind.service`)
```ini
[Unit]
Description=CodeMind AI Production Backend
After=network.target postgresql.service

[Service]
Type=simple
User=codemind
WorkingDirectory=/opt/codemind
EnvironmentFile=/opt/codemind/backend/.env
ExecStart=/opt/codemind/.venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now codemind
sudo systemctl status codemind
```

---

## 6. Health Checks & Observability

CodeMind AI provides RFC-compliant liveness and readiness probes suitable for load balancers and Kubernetes:

### Liveness Probe
- **Endpoints:** `GET /health` or `GET /healthz`
- **Purpose:** Verifies that the FastAPI process is alive and accepting connections.
- **Expected Status:** `200 OK`
```json
{
  "status": "ok",
  "app": "CodeMind AI",
  "version": "0.1.0",
  "environment": "production"
}
```

### Readiness Probe
- **Endpoints:** `GET /ready` or `GET /readyz`
- **Purpose:** Verifies database reachability, pgvector extension availability, and Ollama service readiness.
- **Expected Status:** `200 OK` (when ready) or `503 Service Unavailable` (if database disconnected).
```json
{
  "status": "ready",
  "database": "connected",
  "dialect": "postgresql",
  "detail": "Connected to postgresql database.",
  "pgvector_available": true,
  "ai_provider": "ollama",
  "ollama_service_available": true,
  "llm_model_available": true,
  "embedding_model_available": true
}
```

---

## 7. Security Hardening Summary

| Vector | Production Defense Implementation |
|---|---|
| **SSRF** | Whitelist domains (`github.com`, `api.github.com`), DNS resolution validation blocking loopback (`127.0.0.0/8`, `::1`), private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), and cloud metadata (`169.254.169.254`). Validates redirect locations. |
| **Zip Slip & Bombs** | Pre-extraction inspection enforcing 5000 max entries, 250 MB total uncompressed size limit, symlink/hardlink rejection, and normalized path isolation within extraction root. |
| **Authentication** | Cryptographically signed HMAC-SHA256 session tokens with timestamp validation. Returns `401 Unauthorized` on invalid/expired tokens or missing auth in production. |
| **Authorization / IDOR** | Strict ownership checks (`verify_repo_access`, `get_conversation_record`) preventing cross-user access to repositories, conversations, messages, jobs, and symbols. |
| **Rate Limiting** | In-memory sliding-window limiter returning `429 Too Many Requests` with `Retry-After: 60` for auth, indexing, and assistant endpoints. |
| **Data Masking** | Global correlation middleware (`X-Request-ID`) and database diagnostics mask all passwords, tokens, and connection strings from logs and client responses. |

---

## 8. Verification & Test Execution

Run the complete test suite against your installation:
```bash
python -m pytest backend/tests
```

All tests should pass cleanly without regressions.

---

## 9. Troubleshooting Guide

### 1. Database Connection Timeout or Refused
- Check that PostgreSQL is running: `sudo systemctl status postgresql` or `docker compose ps db`.
- Confirm credentials in `DATABASE_URL` match your PostgreSQL user and database.
- Ensure PostgreSQL `pg_hba.conf` allows MD5/SCRAM password authentication for the user.

### 2. Missing pgvector Extension Error
- Error: `type "vector" does not exist`
- Fix: Connect to the database as superuser and execute:
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  ```

### 3. Ollama Connection Error (502 / 503)
- Verify Ollama service is active: `curl http://127.0.0.1:11434/api/tags`.
- If running backend inside Docker and Ollama on host, ensure `OLLAMA_BASE_URL=http://host.docker.internal:11434`.
- On Linux hosts, ensure Ollama environment has `OLLAMA_HOST=0.0.0.0:11434`.

### 4. Upload Rejected with 413 or 400
- 413: Uploaded file exceeds `MAX_UPLOAD_SIZE_BYTES` (100 MB) or uncompressed size exceeds `MAX_EXTRACTED_SIZE_BYTES` (250 MB).
- 400: Archive contains illegal relative path traversal (`../`) or prohibited symlinks.
