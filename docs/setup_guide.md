# CodeMind AI — Setup, Integration & Execution Guide

This document describes the environment verification, PostgreSQL database setup, GitHub App configuration, repository indexing pipeline, and execution instructions on Windows using PowerShell.

---

## 1. Environment Verification & Database Status

### Current Status on this Machine
- **PostgreSQL**: Port 5432 is not currently listening on `127.0.0.1`. Neither local PostgreSQL service nor Docker is installed on this host.
- **Development Fallback**: The application is configured to connect to PostgreSQL via `DATABASE_URL` in `backend/.env`. For isolated development and tests when PostgreSQL is not running, an automated SQLite development fallback is supported.

### Starting or Installing PostgreSQL on Windows (PowerShell)

#### Option A: Using Windows Package Manager (`winget`)
Run PowerShell as Administrator:
```powershell
# 1. Install PostgreSQL 16
winget install PostgreSQL.PostgreSQL.16

# 2. Start PostgreSQL Windows Service
Start-Service -Name postgresql-x64-16

# 3. Create database
& "C:\Program Files\PostgreSQL\16\bin\createdb.exe" -U postgres codemind_db
```

#### Option B: Using Docker (if installed on developer machine)
```powershell
docker run --name codemind-postgres `
  -e POSTGRES_DB=codemind_db `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -p 5432:5432 -d postgres:16-alpine
```

---

## 2. GitHub App / OAuth Integration Setup

To connect real GitHub repositories and index codebases:

1. Navigate to **GitHub Settings** -> **Developer settings** -> **OAuth Apps** -> **New OAuth App**  
   *(or create a GitHub App at `https://github.com/settings/apps/new`)*:
   - **Application name**: `CodeMind AI`
   - **Homepage URL**: `http://localhost:8000`
   - **Authorization callback URL**: `http://localhost:8000/api/v1/auth/github/callback`
2. Generate a Client Secret.
3. Copy credentials into `backend/.env`:
   ```env
   GITHUB_CLIENT_ID=your_client_id_here
   GITHUB_CLIENT_SECRET=your_client_secret_here
   GITHUB_REDIRECT_URI=http://localhost:8000/api/v1/auth/github/callback
   ```
4. Scopes used:
   - `repo`: Grants access to public and private repositories, commit history, and tarball archives.
   - `read:user`: Grants access to user profile and username display.

### Security Guarantees:
- **CSRF State Validation**: Every authorization request generates a cryptographically signed random state token stored in the `oauth_states` table with a 15-minute expiration. Unmatched or replayed states are rejected.
- **Server-Side Token Storage**: Access tokens are stored exclusively on the server in the `users` database table and are never exposed in HTML, client-side JavaScript, logs, or API responses.
- **Safe Disconnection**: Calling `POST /api/v1/auth/github/disconnect` purges the stored access token and credentials immediately.

---

## 3. Repository Data Deletion Policy

When a user disconnects or deletes a repository:
- **Repository Deletion (`DELETE /api/v1/repositories/{id}`)**: Atomically removes the repository record, cascading deletion to all associated `indexed_files`, `code_symbols`, and `indexing_jobs`.
- **Source Code Cleanup**: Source archives downloaded during indexing are processed in temporary scratch directories and immediately unlinked and purged upon completion or failure.
- **User Credentials**: Disconnecting GitHub removes access tokens without deleting historical repository metadata unless explicitly requested.

---

## 4. Applying Alembic Migrations

Once PostgreSQL is running:

```powershell
$env:PYTHONPATH = "."
alembic -c backend/alembic.ini upgrade head
```

Migrations included:
- `001_initial_schema`: Initial `users`, `repositories`, `indexing_jobs` tables.
- `002_github_and_indexing_schema`: GitHub OAuth columns, `oauth_states`, `indexed_files`, and `code_symbols` tables.

---

## 5. Running the Application

```powershell
$env:PYTHONPATH = "."
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Access points:
- Dashboard: [http://localhost:8000](http://localhost:8000)
- Repositories: [http://localhost:8000/repositories](http://localhost:8000/repositories)
- Connect Modal: [http://localhost:8000/repositories_modal.html](http://localhost:8000/repositories_modal.html)
- API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health Check: [http://localhost:8000/health](http://localhost:8000/health)
- Readiness Check: [http://localhost:8000/ready](http://localhost:8000/ready)
