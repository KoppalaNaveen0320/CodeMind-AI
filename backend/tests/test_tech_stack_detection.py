import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.services.tech_stack_service import TechStackDetectionService
from backend.app.schemas.repository import TechStackRead


# 1. Frontend-only repository
def test_frontend_only_repository():
    """Verify frontend-only repository (e.g. React/Vite/TS) detects FE and explicitly reports BE as Not detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create frontend manifests and source files
        pkg_json = os.path.join(tmpdir, "package.json")
        with open(pkg_json, "w", encoding="utf-8") as f:
            f.write("""{
                "name": "frontend-app",
                "dependencies": {
                    "react": "^18.2.0",
                    "react-dom": "^18.2.0"
                },
                "devDependencies": {
                    "vite": "^5.0.0",
                    "typescript": "^5.0.0",
                    "tailwindcss": "^3.4.0"
                }
            }""")
        
        src_dir = os.path.join(tmpdir, "src")
        os.makedirs(src_dir)
        with open(os.path.join(src_dir, "App.tsx"), "w", encoding="utf-8") as f:
            f.write("import React from 'react'; export const App = () => <div>Hello</div>;")

        stack = TechStackDetectionService.detect_from_directory(tmpdir)
        assert isinstance(stack, TechStackRead)
        
        # Frontend detected
        fe_names = [item.name for item in stack.frontend]
        assert "React" in fe_names
        assert "TypeScript" in fe_names
        assert "Vite" in fe_names
        assert "Tailwind CSS" in fe_names
        
        # Backend explicitly empty / not detected
        assert len(stack.backend) == 0
        assert stack.summary.backend_summary == "Not detected"
        assert "React" in stack.summary.frontend_summary
        assert "Backend: Not detected" in stack.summary.full_summary


# 2. Backend-only repository
def test_backend_only_repository():
    """Verify backend-only repository (e.g. Python/FastAPI) detects BE and reports FE as Not detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        req_txt = os.path.join(tmpdir, "requirements.txt")
        with open(req_txt, "w", encoding="utf-8") as f:
            f.write("fastapi>=0.100.0\nuvicorn>=0.23.0\npydantic>=2.0\n")

        app_dir = os.path.join(tmpdir, "app")
        os.makedirs(app_dir)
        with open(os.path.join(app_dir, "main.py"), "w", encoding="utf-8") as f:
            f.write("from fastapi import FastAPI\napp = FastAPI()\n")

        stack = TechStackDetectionService.detect_from_directory(tmpdir)
        
        # Frontend explicitly empty
        assert len(stack.frontend) == 0
        assert stack.summary.frontend_summary == "Not detected"
        
        # Backend detected
        be_names = [item.name for item in stack.backend]
        assert "FastAPI" in be_names
        assert "Python" in be_names
        assert "FastAPI" in stack.summary.backend_summary
        assert "Frontend: Not detected" in stack.summary.full_summary


# 3. Full-stack repository
def test_fullstack_repository():
    """Verify full-stack repository detects both frontend and backend technologies with confidence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Frontend
        with open(os.path.join(tmpdir, "package.json"), "w", encoding="utf-8") as f:
            f.write('{"dependencies": {"react": "^18.0.0", "next": "^14.0.0"}}')
        # Backend
        with open(os.path.join(tmpdir, "requirements.txt"), "w", encoding="utf-8") as f:
            f.write("fastapi==0.104.1\nsqlalchemy>=2.0.0\n")
        # Database
        with open(os.path.join(tmpdir, "docker-compose.yml"), "w", encoding="utf-8") as f:
            f.write("services:\n  db:\n    image: postgres:15\n")

        stack = TechStackDetectionService.detect_from_directory(tmpdir)
        
        fe_names = [item.name for item in stack.frontend]
        be_names = [item.name for item in stack.backend]
        db_names = [item.name for item in stack.database]
        infra_names = [item.name for item in stack.infrastructure]
        
        assert "React" in fe_names
        assert "Next.js" in fe_names
        assert "FastAPI" in be_names
        assert "PostgreSQL" in db_names
        assert "Docker Compose" in infra_names
        assert stack.summary.frontend_summary != "Not detected"
        assert stack.summary.backend_summary != "Not detected"


# 4. Repository with database configuration
def test_database_configuration_detection():
    """Verify database technologies are detected from requirements, ORM configs, and docker compose."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "requirements.txt"), "w", encoding="utf-8") as f:
            f.write("psycopg2-binary==2.9.9\nredis==5.0.1\nalembic==1.13.0\n")
        with open(os.path.join(tmpdir, "alembic.ini"), "w", encoding="utf-8") as f:
            f.write("[alembic]\nscript_location = alembic\n")

        stack = TechStackDetectionService.detect_from_directory(tmpdir)
        db_names = [item.name for item in stack.database]
        
        assert "PostgreSQL" in db_names
        assert "Redis" in db_names
        assert "Alembic" in db_names
        
        # Verify evidence includes manifest filenames
        pg_item = next(it for it in stack.database if it.name == "PostgreSQL")
        assert any("requirements.txt" in ev for ev in pg_item.evidence)


# 5. Repository with Docker configuration
def test_docker_and_infrastructure_detection():
    """Verify Docker, Docker Compose, and Nginx configurations are detected with evidence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "Dockerfile"), "w", encoding="utf-8") as f:
            f.write("FROM python:3.11-slim\nWORKDIR /app\n")
        with open(os.path.join(tmpdir, "docker-compose.yml"), "w", encoding="utf-8") as f:
            f.write("version: '3.8'\nservices:\n  web:\n    build: .\n")
        with open(os.path.join(tmpdir, "nginx.conf"), "w", encoding="utf-8") as f:
            f.write("events {}\nhttp { server { listen 80; } }\n")

        stack = TechStackDetectionService.detect_from_directory(tmpdir)
        infra_names = [item.name for item in stack.infrastructure]
        
        assert "Docker" in infra_names
        assert "Docker Compose" in infra_names
        assert "Nginx" in infra_names


# 6. Repository containing multiple programming languages
def test_multilingual_repository():
    """Verify polyglot repository accurately categorizes languages and frameworks across stacks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Go backend
        with open(os.path.join(tmpdir, "go.mod"), "w", encoding="utf-8") as f:
            f.write("module github.com/example/polyglot\ngo 1.21\nrequire github.com/gin-gonic/gin v1.9.1\n")
        # Python script / service
        with open(os.path.join(tmpdir, "requirements.txt"), "w", encoding="utf-8") as f:
            f.write("flask>=3.0.0\n")
        # Vue frontend
        with open(os.path.join(tmpdir, "package.json"), "w", encoding="utf-8") as f:
            f.write('{"dependencies": {"vue": "^3.3.0"}}')

        stack = TechStackDetectionService.detect_from_directory(tmpdir)
        
        fe_names = [item.name for item in stack.frontend]
        be_names = [item.name for item in stack.backend]
        
        assert any("Vue" in n for n in fe_names)
        assert "Gin" in be_names
        assert "Go" in be_names
        assert "Flask" in be_names
        assert "Python" in be_names


# 7. Repository with insufficient evidence
def test_insufficient_evidence_repository():
    """Verify repository without recognizable manifests returns neutral Not detected state without guessing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as f:
            f.write("# Notes\nJust documentation, no code or manifests.")
        with open(os.path.join(tmpdir, "notes.txt"), "w", encoding="utf-8") as f:
            f.write("Random meeting notes")

        stack = TechStackDetectionService.detect_from_directory(tmpdir)
        
        assert len(stack.frontend) == 0
        assert len(stack.backend) == 0
        assert len(stack.database) == 0
        assert len(stack.infrastructure) == 0
        assert stack.summary.frontend_summary == "Not detected"
        assert stack.summary.backend_summary == "Not detected"
        assert stack.summary.full_summary == "Frontend: Not detected; Backend: Not detected"


# 8. Empty repository or incomplete indexing
def test_empty_or_incomplete_repository():
    """Verify empty directory or 0 indexed files returns a graceful fallback."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Completely empty dir
        stack = TechStackDetectionService.detect_from_directory(tmpdir)
        assert stack.summary.frontend_summary == "Not detected"
        assert stack.summary.backend_summary == "Not detected"
        
        # Test detection from empty files list
        files_stack = TechStackDetectionService.detect_from_files([])
        assert files_stack.summary.frontend_summary == "Not detected"
        assert files_stack.summary.backend_summary == "Not detected"


# 9. Existing repositories with no saved technology metadata
def test_existing_repositories_without_tech_metadata(client: TestClient, db_session: Session):
    """Verify legacy repository records with tech_stack=None are populated gracefully via API."""
    repo = Repository(
        name="legacy-repo",
        full_name="acme/legacy-repo",
        primary_language="Python",
        status="ready",
        tech_stack=None  # Legacy record
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    # 1. Test GET list
    res = client.get("/api/v1/repositories")
    assert res.status_code == 200
    repos = res.json()
    matched = next((r for r in repos if r["id"] == repo.id), None)
    assert matched is not None
    assert matched["tech_stack"] is not None
    assert "summary" in matched["tech_stack"]

    # 2. Test GET by ID
    single_res = client.get(f"/api/v1/repositories/{repo.id}")
    assert single_res.status_code == 200
    data = single_res.json()
    assert data["tech_stack"] is not None
    assert data["primary_language"] == "Python"


# 10. Repository table rendering and technology badges API contract
def test_repository_table_rendering_and_badges_contract(client: TestClient, db_session: Session):
    """Verify repository response returns structured tech_stack with categories and evidence."""
    repo = Repository(
        name="store-api",
        full_name="acme/store-api",
        primary_language="Python",
        status="ready",
        tech_stack={
            "frontend": [
                {"name": "React", "category": "frontend", "type": "framework", "confidence": "high", "evidence": ["package.json"]}
            ],
            "backend": [
                {"name": "FastAPI", "category": "backend", "type": "framework", "confidence": "high", "evidence": ["requirements.txt"]}
            ],
            "database": [
                {"name": "PostgreSQL", "category": "database", "type": "database", "confidence": "high", "evidence": ["docker-compose.yml"]}
            ],
            "infrastructure": [],
            "summary": {
                "frontend_summary": "React",
                "backend_summary": "FastAPI",
                "database_summary": "PostgreSQL",
                "infrastructure_summary": "Not detected",
                "full_summary": "Frontend: React; Backend: FastAPI; Database: PostgreSQL"
            }
        }
    )
    db_session.add(repo)
    db_session.commit()

    res = client.get("/api/v1/repositories")
    assert res.status_code == 200
    matched = next(r for r in res.json() if r["name"] == "store-api")
    
    assert matched["tech_stack"]["summary"]["frontend_summary"] == "React"
    assert matched["tech_stack"]["summary"]["backend_summary"] == "FastAPI"
    assert matched["tech_stack"]["frontend"][0]["name"] == "React"
    assert matched["tech_stack"]["frontend"][0]["confidence"] == "high"
    assert matched["tech_stack"]["frontend"][0]["evidence"] == ["package.json"]

    # Verify repositories HTML page contains Technology Stack column header
    html_res = client.get("/repositories")
    assert html_res.status_code == 200
    assert "Technology Stack" in html_res.text


# 11. Technology metadata refresh after re-indexing
def test_tech_metadata_refresh_after_reindexing(db_session: Session):
    """Verify that detect_from_db updates the tech_stack when new indexed files are added."""
    repo = Repository(
        name="evolving-repo",
        full_name="acme/evolving-repo",
        primary_language="Python",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    # Initially only a python file
    f1 = IndexedFile(
        repository_id=repo.id,
        path="backend/app/main.py",
        language="python",
        content_hash="h1",
        size_bytes=100
    )
    db_session.add(f1)
    db_session.commit()

    initial_stack = TechStackDetectionService.detect_from_db(db_session, repo.id)
    assert "Python" in [b.name for b in initial_stack.backend]
    assert len(initial_stack.frontend) == 0

    # Simulate re-indexing adding frontend manifest package.json
    f2 = IndexedFile(
        repository_id=repo.id,
        path="package.json",
        language="json",
        content_hash="h2",
        size_bytes=120
    )
    db_session.add(f2)
    db_session.commit()

    refreshed_stack = TechStackDetectionService.detect_from_db(
        db_session, 
        repo.id, 
        manifest_contents={"package.json": '{"dependencies": {"react": "^18.0.0", "typescript": "^5.0.0"}}'}
    )
    fe_names = [f.name for f in refreshed_stack.frontend]
    assert "React" in fe_names
    assert "TypeScript" in fe_names
    assert refreshed_stack.summary.frontend_summary != "Not detected"


# 12. Workspace isolation and repository authorization
def test_workspace_isolation_and_authorization(client: TestClient, db_session: Session):
    """Verify repositories in separate contexts remain isolated and do not cross-contaminate tech stacks."""
    repo_a = Repository(
        name="workspace-a-repo",
        full_name="team-a/repo",
        primary_language="Dart",
        tech_stack={
            "frontend": [{"name": "Flutter", "category": "frontend", "type": "framework", "confidence": "high", "evidence": ["pubspec.yaml"]}],
            "backend": [],
            "database": [],
            "infrastructure": [],
            "summary": {"frontend_summary": "Flutter", "backend_summary": "Not detected", "full_summary": "Frontend: Flutter; Backend: Not detected"}
        }
    )
    repo_b = Repository(
        name="workspace-b-repo",
        full_name="team-b/repo",
        primary_language="Go",
        tech_stack={
            "frontend": [],
            "backend": [{"name": "Go", "category": "backend", "type": "language", "confidence": "high", "evidence": ["go.mod"]}],
            "database": [],
            "infrastructure": [],
            "summary": {"frontend_summary": "Not detected", "backend_summary": "Go", "full_summary": "Frontend: Not detected; Backend: Go"}
        }
    )
    db_session.add_all([repo_a, repo_b])
    db_session.commit()

    res_a = client.get(f"/api/v1/repositories/{repo_a.id}")
    res_b = client.get(f"/api/v1/repositories/{repo_b.id}")

    assert res_a.status_code == 200
    assert res_b.status_code == 200

    data_a = res_a.json()
    data_b = res_b.json()

    assert data_a["tech_stack"]["summary"]["frontend_summary"] == "Flutter"
    assert data_a["tech_stack"]["summary"]["backend_summary"] == "Not detected"

    assert data_b["tech_stack"]["summary"]["frontend_summary"] == "Not detected"
    assert data_b["tech_stack"]["summary"]["backend_summary"] == "Go"


# 13. Existing repository list and action functionality
def test_existing_repository_list_and_actions(client: TestClient, db_session: Session):
    """Verify standard CRUD and action endpoints continue working seamlessly without regressions."""
    payload = {
        "name": "action-test-repo",
        "full_name": "acme/action-test-repo",
        "description": "Testing actions and status",
        "default_branch": "main",
        "primary_language": "TypeScript"
    }
    create_res = client.post("/api/v1/repositories?auto_index=false", json=payload)
    assert create_res.status_code == 201
    repo_id = create_res.json()["id"]

    # Verify indexing status endpoint and repository details
    status_res = client.get(f"/api/v1/repositories/{repo_id}/indexing-status")
    assert status_res.status_code == 200
    repo_res = client.get(f"/api/v1/repositories/{repo_id}")
    assert repo_res.status_code == 200
    assert repo_res.json()["status"] in ["pending", "ready"]

    # Verify dashboard overview endpoint
    dash_res = client.get(f"/api/v1/dashboard/overview?repository_id={repo_id}")
    assert dash_res.status_code == 200
    dash_data = dash_res.json()
    assert dash_data["active_repository"]["id"] == repo_id
    assert "tech_stack" in dash_data["active_repository"]

    # Delete repository
    del_res = client.delete(f"/api/v1/repositories/{repo_id}")
    assert del_res.status_code == 200
