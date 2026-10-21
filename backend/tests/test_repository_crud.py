from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol


def test_create_and_get_repository(client: TestClient, db_session: Session):
    """Verify repository creation and retrieval."""
    payload = {
        "name": "billing-engine",
        "full_name": "acme-inc/billing-engine",
        "description": "Core billing service",
        "default_branch": "main",
        "primary_language": "TypeScript",
        "is_private": True,
        "github_repo_id": 998877
    }
    response = client.post("/api/v1/repositories?auto_index=false", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["full_name"] == "acme-inc/billing-engine"
    repo_id = data["id"]

    # Retrieve by ID
    get_res = client.get(f"/api/v1/repositories/{repo_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "billing-engine"


def test_duplicate_repository_prevention(client: TestClient, db_session: Session):
    """Verify posting an existing repository full_name updates it instead of creating duplicates."""
    payload1 = {
        "name": "auth-service",
        "full_name": "acme-inc/auth-service",
        "description": "Initial description",
        "primary_language": "Python"
    }
    client.post("/api/v1/repositories?auto_index=false", json=payload1)

    payload2 = {
        "name": "auth-service",
        "full_name": "acme-inc/auth-service",
        "description": "Updated description",
        "primary_language": "Python"
    }
    response = client.post("/api/v1/repositories?auto_index=false", json=payload2)
    assert response.status_code == 201
    
    # Check total count in DB
    repos = db_session.query(Repository).filter(Repository.full_name == "acme-inc/auth-service").all()
    assert len(repos) == 1
    assert repos[0].description == "Updated description"


def test_delete_repository_cascade(client: TestClient, db_session: Session):
    """Verify deleting a repository cascades deletion to files and symbols."""
    repo = Repository(
        name="temp-repo",
        full_name="acme/temp-repo",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    f = IndexedFile(
        repository_id=repo.id,
        path="src/index.ts",
        language="typescript",
        lines_count=10
    )
    db_session.add(f)
    db_session.commit()
    db_session.refresh(f)

    sym = CodeSymbol(
        repository_id=repo.id,
        file_id=f.id,
        name="startApp",
        kind="function",
        start_line=1,
        end_line=5
    )
    db_session.add(sym)
    db_session.commit()

    # Delete via API
    del_res = client.delete(f"/api/v1/repositories/{repo.id}")
    assert del_res.status_code == 200

    # Verify cascading
    assert db_session.query(Repository).filter(Repository.id == repo.id).first() is None
    assert db_session.query(IndexedFile).filter(IndexedFile.repository_id == repo.id).first() is None
    assert db_session.query(CodeSymbol).filter(CodeSymbol.repository_id == repo.id).first() is None
