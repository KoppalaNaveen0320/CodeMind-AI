from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from backend.app.models.repository import Repository
from backend.app.models.user import User


def test_get_current_user_default(client: TestClient):
    """Verify GET /api/v1/me returns user profile."""
    response = client.get("/api/v1/me")
    assert response.status_code == 200
    data = response.json()
    assert "email" in data
    assert "full_name" in data
    assert "workspace_name" in data


def test_get_repositories_empty(client: TestClient):
    """Verify GET /api/v1/repositories returns truthful empty list when no repos are in DB."""
    response = client.get("/api/v1/repositories")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


def test_get_repositories_populated(client: TestClient, db_session: Session):
    """Verify GET /api/v1/repositories returns registered repositories."""
    repo = Repository(
        name="test-repo",
        full_name="test-org/test-repo",
        description="A test repository",
        primary_language="TypeScript",
        status="ready",
        files_count=150,
        symbols_count=45,
        apis_count=12,
        dependencies_count=80
    )
    db_session.add(repo)
    db_session.commit()

    response = client.get("/api/v1/repositories")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "test-repo"
    assert data[0]["files_count"] == 150


def test_dashboard_overview_truthful_empty(client: TestClient):
    """Verify GET /api/v1/dashboard/overview returns 0 metrics when no repositories exist."""
    response = client.get("/api/v1/dashboard/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["files_indexed"] == 0
    assert data["functions_classes"] == 0
    assert data["apis_detected"] == 0
    assert data["dependencies_mapped"] == 0
    assert data["active_repository"] is None
    assert len(data["repositories"]) == 0


def test_dashboard_overview_populated(client: TestClient, db_session: Session):
    """Verify GET /api/v1/dashboard/overview aggregates truthful metrics from repositories."""
    repo1 = Repository(
        name="repo-1",
        full_name="org/repo-1",
        files_count=100,
        symbols_count=50,
        apis_count=10,
        dependencies_count=20,
        status="ready"
    )
    repo2 = Repository(
        name="repo-2",
        full_name="org/repo-2",
        files_count=200,
        symbols_count=70,
        apis_count=15,
        dependencies_count=40,
        status="ready"
    )
    db_session.add_all([repo1, repo2])
    db_session.commit()

    # Default active repo is repo2 (most recent by ID)
    response = client.get("/api/v1/dashboard/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["active_repository"]["id"] == repo2.id
    assert data["files_indexed"] == 200
    assert data["functions_classes"] == 70
    assert data["apis_detected"] == 15
    assert data["dependencies_mapped"] == 40
    assert len(data["repositories"]) == 2

    # Querying specific repository returns repo1's isolated metrics
    res_repo1 = client.get(f"/api/v1/dashboard/overview?repository_id={repo1.id}")
    assert res_repo1.status_code == 200
    data1 = res_repo1.json()
    assert data1["active_repository"]["id"] == repo1.id
    assert data1["files_indexed"] == 100
    assert data1["functions_classes"] == 50
    assert data1["apis_detected"] == 10
    assert data1["dependencies_mapped"] == 20
