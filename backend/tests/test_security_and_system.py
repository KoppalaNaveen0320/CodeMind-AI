from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.code_symbol import CodeSymbol


def test_security_findings_clean_repo(client: TestClient, db_session: Session):
    """Verifies that a clean repository without patterns returns 0 findings."""
    repo = Repository(name="clean-repo", full_name="acme/clean-repo", status="ready")
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    response = client.get(f"/api/v1/repositories/{repo.id}/security/findings")
    assert response.status_code == 200
    data = response.json()
    assert data["total_findings"] == 0
    assert data["high_count"] == 0
    assert data["findings"] == []


def test_security_findings_detected(client: TestClient, db_session: Session):
    """Verifies that actual security patterns in indexed code chunks are detected."""
    repo = Repository(name="vulnerable-service", full_name="acme/vulnerable-service", status="ready")
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    file1 = IndexedFile(repository_id=repo.id, path="src/auth/token.py", language="python", lines_count=20)
    db_session.add(file1)
    db_session.commit()
    db_session.refresh(file1)

    chunk1 = CodeChunk(
        repository_id=repo.id,
        file_id=file1.id,
        file_path="src/auth/token.py",
        chunk_index=0,
        chunk_text='api_key = "abcdef1234567890abcdef"\n# Hardcoded key\n',
        content_hash="h1",
        language="python",
        start_line=1,
        end_line=2
    )
    db_session.add(chunk1)
    db_session.commit()

    response = client.get(f"/api/v1/repositories/{repo.id}/security/findings")
    assert response.status_code == 200
    data = response.json()
    assert data["total_findings"] >= 1
    assert data["high_count"] >= 1
    assert data["findings"][0]["cwe"] == "CWE-798"
    assert "src/auth/token.py" in data["findings"][0]["file_path"]

    # Test status update
    finding_id = data["findings"][0]["id"]
    patch_res = client.patch(
        f"/api/v1/repositories/{repo.id}/security/findings/{finding_id}",
        json={"status": "REVIEWED"}
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["new_status"] == "REVIEWED"


def test_repository_documentation(client: TestClient, db_session: Session):
    """Verifies generation of structured documentation from indexed files and symbols."""
    repo = Repository(name="doc-repo", full_name="acme/doc-repo", status="ready")
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    f = IndexedFile(repository_id=repo.id, path="src/user_service.py", language="python", lines_count=50)
    db_session.add(f)
    db_session.commit()
    db_session.refresh(f)

    sym = CodeSymbol(
        repository_id=repo.id,
        file_id=f.id,
        name="UserService",
        kind="class",
        signature="class UserService",
        start_line=5,
        end_line=45,
        docstring="Core service for user authentication and lifecycle."
    )
    db_session.add(sym)
    db_session.commit()

    response = client.get(f"/api/v1/repositories/{repo.id}/docs")
    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 1
    assert data["total_symbols"] == 1
    assert len(data["modules"]) == 1
    assert data["modules"][0]["name"] == "User Service"
    assert data["modules"][0]["symbols"][0]["name"] == "UserService"


def test_user_settings_and_update(client: TestClient):
    """Verifies getting and updating user settings."""
    res = client.get("/api/v1/settings")
    assert res.status_code == 200
    data = res.json()
    assert "app_name" in data
    assert "ai_provider" in data

    put_res = client.put("/api/v1/settings", json={"workspace_name": "Dev Team Core"})
    assert put_res.status_code == 200
    assert put_res.json()["user"]["workspace_name"] == "Dev Team Core"


def test_notifications_endpoint(client: TestClient):
    """Verifies notifications retrieval."""
    res = client.get("/api/v1/notifications")
    assert res.status_code == 200
    data = res.json()
    assert "unread_count" in data
    assert isinstance(data["notifications"], list)


def test_global_search_endpoint(client: TestClient, db_session: Session):
    """Verifies global search across files and symbols."""
    repo = Repository(name="search-repo", full_name="acme/search-repo", status="ready")
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    f = IndexedFile(repository_id=repo.id, path="src/payment_gateway.py", language="python", lines_count=30)
    db_session.add(f)
    db_session.commit()
    db_session.refresh(f)

    sym = CodeSymbol(
        repository_id=repo.id,
        file_id=f.id,
        name="process_payment",
        kind="function",
        start_line=10,
        end_line=25
    )
    db_session.add(sym)
    db_session.commit()

    res = client.get(f"/api/v1/repositories/{repo.id}/search?q=payment")
    assert res.status_code == 200
    data = res.json()
    assert len(data["files"]) >= 1
    assert data["files"][0]["path"] == "src/payment_gateway.py"
    assert len(data["symbols"]) >= 1
    assert data["symbols"][0]["name"] == "process_payment"
