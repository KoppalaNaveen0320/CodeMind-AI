import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexing_job import IndexingJob


def test_repositories_page_no_simulated_prototype_strings(client: TestClient):
    """Verify repositories.html contains no simulated flow or prototype disclaimer strings."""
    response = client.get("/repositories", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert "SIMULATED FLOW" not in html
    assert "Simulate GitHub authorization" not in html
    assert "This prototype demonstrates" not in html
    assert "No OAuth request is made" not in html
    # Verify new dynamic containers exist
    assert 'id="repositories-container"' in html
    assert 'id="connect-github-modal"' in html
    assert 'id="repo-search-input"' in html
    assert 'id="repo-status-filter"' in html


def test_repositories_modal_page_clean_structure(client: TestClient):
    """Verify repositories_modal.html has removed prototype simulated flows and static mock rows."""
    response = client.get("/repositories_modal", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert "SIMULATED FLOW" not in html
    assert "Simulate GitHub authorization" not in html
    assert "This prototype demonstrates" not in html
    # Ensure modal container and steps exist
    assert 'id="connect-github-modal"' in html
    assert 'id="modal-steps-indicator"' in html
    assert 'id="modal-body-content"' in html


def test_github_oauth_denial_handling(client: TestClient):
    """Verify GitHub OAuth callback returns 400 when access is denied by the user."""
    response = client.get(
        "/api/v1/auth/github/callback?error=access_denied&error_description=The+user+has+denied+your+application+access."
    )
    assert response.status_code == 400
    assert "denied" in response.json()["detail"].lower()


def test_github_oauth_missing_parameters_rejected(client: TestClient):
    """Verify OAuth callback returns 400 when code or state is missing."""
    response = client.get("/api/v1/auth/github/callback")
    assert response.status_code == 400
    assert "missing oauth code or state" in response.json()["detail"].lower()


def test_repository_duplicate_connection_upsert(client: TestClient, db_session: Session):
    """Verify registering the same repository full_name multiple times updates rather than duplicating."""
    payload = {
        "name": "fastapi",
        "full_name": "tiangolo/fastapi",
        "description": "FastAPI framework",
        "is_private": False,
        "default_branch": "master",
        "primary_language": "Python"
    }

    res1 = client.post("/api/v1/repositories?auto_index=false", json=payload)
    assert res1.status_code == 201
    repo1 = res1.json()

    # Register again with updated branch
    payload["default_branch"] = "main"
    res2 = client.post("/api/v1/repositories?auto_index=false", json=payload)
    assert res2.status_code == 201
    repo2 = res2.json()

    assert repo1["id"] == repo2["id"]
    assert repo2["default_branch"] == "main"

    # Verify only 1 record exists in DB
    repos_count = db_session.query(Repository).filter(Repository.full_name == "tiangolo/fastapi").count()
    assert repos_count == 1

    # Cleanup
    client.delete(f"/api/v1/repositories/{repo1['id']}")


def test_repository_indexing_trigger_and_status(client: TestClient, db_session: Session):
    """Verify repository indexing can be triggered and status polled correctly."""
    payload = {
        "name": "flask",
        "full_name": "pallets/flask",
        "description": "Flask microframework",
        "is_private": False,
        "default_branch": "main",
        "primary_language": "Python"
    }

    res = client.post("/api/v1/repositories?auto_index=false", json=payload)
    assert res.status_code == 201
    repo = res.json()

    # Trigger indexing
    idx_res = client.post(f"/api/v1/repositories/{repo['id']}/index", json={"branch": "main"})
    assert idx_res.status_code == 200
    job = idx_res.json()
    assert job["repository_id"] == repo["id"]
    assert job["status"].lower() in ["queued", "processing", "completed"]

    # Check indexing status endpoint
    status_res = client.get(f"/api/v1/repositories/{repo['id']}/indexing-status")
    assert status_res.status_code == 200
    data = status_res.json()
    assert data["repository_id"] == repo["id"]
    assert "status" in data

    # Cleanup
    client.delete(f"/api/v1/repositories/{repo['id']}")


def test_disconnect_github_clears_tokens_safely(client: TestClient, db_session: Session):
    """Verify disconnecting GitHub account clears OAuth credentials without deleting repository data."""
    user = db_session.query(User).first()
    if not user:
        user = User(
            email="test_ui@dev.local",
            full_name="Test UI Developer",
            workspace_name="Test Workspace",
            avatar_initials="TD",
            is_active=True
        )
        db_session.add(user)
    user.github_access_token = "gho_test_token_sample"
    user.github_username = "test_developer"
    db_session.commit()

    # Call disconnect endpoint
    res = client.post("/api/v1/auth/github/disconnect")
    assert res.status_code == 200
    assert res.json()["status"] == "disconnected"

    # Verify user token is cleared
    db_session.refresh(user)
    assert user.github_access_token is None
    assert user.github_username is None

    # Check status endpoint now reflects disconnected
    status_res = client.get("/api/v1/auth/github/status")
    assert status_res.status_code == 200
    assert status_res.json()["connected"] is False


def test_assistant_has_stop_generating_button(client: TestClient):
    """Verify assistant.html contains the stop-generating button and accessible markup."""
    res = client.get("/assistant", follow_redirects=True)
    assert res.status_code == 200
    html = res.text
    assert 'id="stop-generating-btn"' in html
    assert 'class="stop-btn"' in html
    assert 'title="Stop generating"' in html
    assert 'aria-label="Stop generating"' in html
    assert 'id="send-message-btn"' in html


def test_security_badge_removed_fake_counts_across_templates(client: TestClient):
    """Verify templates contain no hardcoded fake '3' notifications and use dynamic badge ID."""
    templates = [
        "/dashboard.html",
        "/assistant.html",
        "/dependencies.html",
        "/security_insights.html",
        "/repositories.html",
        "/git_history.html",
    ]
    for tmpl in templates:
        res = client.get(tmpl, follow_redirects=True)
        assert res.status_code == 200
        html = res.text
        # Hardcoded count '3' badge MUST NOT exist
        assert '<span class="nav-count">3</span>' not in html
        # Dynamic badge container must exist
        assert 'id="sidebar-security-badge"' in html


def test_dependency_explorer_controls_and_panel(client: TestClient):
    """Verify dependencies.html contains zoom buttons, canvas container, and details panel elements."""
    res = client.get("/dependencies", follow_redirects=True)
    assert res.status_code == 200
    html = res.text
    assert 'id="btn-zoom-in"' in html
    assert 'id="btn-zoom-out"' in html
    assert 'id="btn-zoom-fit"' in html
    assert 'id="graph-canvas-container"' in html
    assert 'id="graph-node-panel"' in html
    assert 'id="btn-analyze-impact"' in html
    assert 'id="btn-ask-ai"' in html
    assert 'id="btn-view-in-code-viewer"' in html
    assert 'id="node-relations-container"' in html


def test_dashboard_overview_architecture_and_commits(client: TestClient):
    """Verify dashboard.html contains responsive architecture overview and recent commits containers."""
    res = client.get("/dashboard", follow_redirects=True)
    assert res.status_code == 200
    html = res.text
    assert 'id="dashboard-architecture-container"' in html
    assert 'id="dashboard-recent-commits"' in html
    assert '3 findings need attention' not in html
    assert 'id="quick-action-security-sub"' in html

