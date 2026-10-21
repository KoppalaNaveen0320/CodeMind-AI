import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from backend.app.models.repository import Repository
from backend.app.models.user import User
from backend.app.models.indexing_job import IndexingJob
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.core.security import create_session_token


def test_disconnect_authorized_repository(client: TestClient, db_session: Session):
    """Verify disconnecting an authorized repository succeeds with correct metadata."""
    user = User(
        email="disconnect_owner@codemind.dev",
        full_name="Disconnect Owner",
        workspace_name="Disconnection Lab",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    repo = Repository(
        name="test_service",
        full_name="disconnection-lab/test_service",
        user_id=user.id,
        provider="github",
        is_private=False,
        default_branch="main",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    token = create_session_token(user.id)
    headers = {"Cookie": f"codemind_session={token}"}

    del_res = client.delete(f"/api/v1/repositories/{repo.id}", headers=headers)
    assert del_res.status_code == 200
    data = del_res.json()
    assert data["status"] == "deleted"
    assert data["repository_id"] == repo.id
    assert data["name"] == "test_service"
    assert data["full_name"] == "disconnection-lab/test_service"
    assert "disconnected successfully" in data["message"] or "deleted" in data["message"]

    # Verify repository is removed from DB
    deleted = db_session.query(Repository).filter(Repository.id == repo.id).first()
    assert deleted is None


def test_disconnect_using_correct_database_id(client: TestClient, db_session: Session):
    """Verify disconnecting a specific repository ID removes only that repository."""
    user = User(
        email="multi_repo_owner@codemind.dev",
        full_name="Multi Repo Owner",
        workspace_name="Multi Lab",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    repo_a = Repository(
        name="repo_alpha",
        full_name="multi/repo_alpha",
        user_id=user.id,
        status="ready"
    )
    repo_b = Repository(
        name="repo_beta",
        full_name="multi/repo_beta",
        user_id=user.id,
        status="ready"
    )
    db_session.add_all([repo_a, repo_b])
    db_session.commit()
    db_session.refresh(repo_a)
    db_session.refresh(repo_b)

    token = create_session_token(user.id)
    headers = {"Cookie": f"codemind_session={token}"}

    # Delete repo_b only
    del_res = client.delete(f"/api/v1/repositories/{repo_b.id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["repository_id"] == repo_b.id

    # Verify repo_b is gone, but repo_a remains intact
    assert db_session.query(Repository).filter(Repository.id == repo_b.id).first() is None
    remains = db_session.query(Repository).filter(Repository.id == repo_a.id).first()
    assert remains is not None
    assert remains.name == "repo_alpha"


def test_disconnect_repository_record_missing(client: TestClient, db_session: Session):
    """Verify disconnecting a missing repository returns 404 without crashing."""
    user = User(
        email="missing_check@codemind.dev",
        full_name="Missing Checker",
        workspace_name="Check Lab",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token = create_session_token(user.id)
    headers = {"Cookie": f"codemind_session={token}"}

    del_res = client.delete("/api/v1/repositories/999999", headers=headers)
    assert del_res.status_code == 404
    assert "Repository not found" in del_res.json()["detail"]


def test_disconnect_unauthorized_cross_workspace_forbidden(client: TestClient, db_session: Session):
    """Verify tenant isolation: a user from Workspace B cannot disconnect Workspace A's repository."""
    user_a = User(
        email="tenant_a@company-a.com",
        full_name="Tenant A",
        workspace_name="Workspace Alpha",
        is_active=True
    )
    user_b = User(
        email="tenant_b@company-b.com",
        full_name="Tenant B",
        workspace_name="Workspace Beta",
        is_active=True
    )
    db_session.add_all([user_a, user_b])
    db_session.commit()
    db_session.refresh(user_a)
    db_session.refresh(user_b)

    repo_a = Repository(
        name="alpha_secret_repo",
        full_name="company-a/secret_repo",
        user_id=user_a.id,
        is_private=True,
        status="ready"
    )
    db_session.add(repo_a)
    db_session.commit()
    db_session.refresh(repo_a)

    # User B attempts to delete User A's repository
    token_b = create_session_token(user_b.id)
    headers_b = {"Cookie": f"codemind_session={token_b}"}

    del_res = client.delete(f"/api/v1/repositories/{repo_a.id}", headers=headers_b)
    assert del_res.status_code == 403
    assert "Access denied to this repository" in del_res.json()["detail"]

    # Verify repository was NOT deleted
    assert db_session.query(Repository).filter(Repository.id == repo_a.id).first() is not None


def test_disconnect_repeated_requests_handling(client: TestClient, db_session: Session):
    """Verify repeated or duplicate disconnect requests are handled safely."""
    user = User(
        email="repeat_test@codemind.dev",
        full_name="Repeat Tester",
        workspace_name="Repeat Lab",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    repo = Repository(
        name="repeat_repo",
        full_name="repeat/test_repo",
        user_id=user.id,
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    token = create_session_token(user.id)
    headers = {"Cookie": f"codemind_session={token}"}

    # First request succeeds
    first_res = client.delete(f"/api/v1/repositories/{repo.id}", headers=headers)
    assert first_res.status_code == 200

    # Second immediate duplicate request cleanly reports missing/already-disconnected
    second_res = client.delete(f"/api/v1/repositories/{repo.id}", headers=headers)
    assert second_res.status_code == 404
    assert "Repository not found" in second_res.json()["detail"]


def test_disconnect_active_indexing_job_cancellation(client: TestClient, db_session: Session):
    """Verify that disconnecting a repository with active indexing job cancels the job safely."""
    user = User(
        email="job_cancel_user@codemind.dev",
        full_name="Job Cancel User",
        workspace_name="Job Lab",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    repo = Repository(
        name="active_job_repo",
        full_name="job-lab/active_job_repo",
        user_id=user.id,
        status="indexing"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    job = IndexingJob(
        repository_id=repo.id,
        branch="main",
        status="INDEXING",
        stage="PARSING"
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    token = create_session_token(user.id)
    headers = {"Cookie": f"codemind_session={token}"}

    del_res = client.delete(f"/api/v1/repositories/{repo.id}", headers=headers)
    assert del_res.status_code == 200

    # Verify both repo and job are cleaned up and no orphan job is left
    assert db_session.query(Repository).filter(Repository.id == repo.id).first() is None
    assert db_session.query(IndexingJob).filter(IndexingJob.id == job.id).first() is None


def test_disconnect_database_transaction_failure(client: TestClient, db_session: Session, monkeypatch):
    """Verify that a database transaction failure rolls back safely and returns HTTP 500 without leaking secrets."""
    user = User(
        email="tx_fail_user@codemind.dev",
        full_name="Tx Fail User",
        workspace_name="Tx Lab",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    repo = Repository(
        name="tx_fail_repo",
        full_name="tx-lab/tx_fail_repo",
        user_id=user.id,
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    token = create_session_token(user.id)
    headers = {"Cookie": f"codemind_session={token}"}

    # Monkeypatch db.commit to simulate database lock/failure
    def mock_commit():
        raise SQLAlchemyError("Simulated database operational lock error")

    monkeypatch.setattr(db_session, "commit", mock_commit)

    del_res = client.delete(f"/api/v1/repositories/{repo.id}", headers=headers)
    assert del_res.status_code == 500
    assert "Failed to disconnect repository due to a database error" in del_res.json()["detail"]


def test_disconnected_repository_disappears_from_list(client: TestClient, db_session: Session):
    """Verify that after disconnect, the repository no longer appears in GET /api/v1/repositories."""
    user = User(
        email="list_refresh_user@codemind.dev",
        full_name="List Refresh User",
        workspace_name="List Refresh Lab",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    repo = Repository(
        name="refresh_repo",
        full_name="list-refresh/target_repo",
        user_id=user.id,
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    token = create_session_token(user.id)
    headers = {"Cookie": f"codemind_session={token}"}

    # Verify present in list
    list_before = client.get("/api/v1/repositories", headers=headers)
    assert list_before.status_code == 200
    ids_before = [r["id"] for r in list_before.json()]
    assert repo.id in ids_before

    # Disconnect
    del_res = client.delete(f"/api/v1/repositories/{repo.id}", headers=headers)
    assert del_res.status_code == 200

    # Verify absent from list
    list_after = client.get("/api/v1/repositories", headers=headers)
    assert list_after.status_code == 200
    ids_after = [r["id"] for r in list_after.json()]
    assert repo.id not in ids_after


def test_disconnect_preserves_other_repositories_and_workspaces(client: TestClient, db_session: Session):
    """Verify that disconnecting one repository does not affect other repositories or other workspaces."""
    user_alpha = User(email="alpha_dev@codemind.dev", full_name="Alpha", workspace_name="Org Alpha", is_active=True)
    user_beta = User(email="beta_dev@codemind.dev", full_name="Beta", workspace_name="Org Beta", is_active=True)
    db_session.add_all([user_alpha, user_beta])
    db_session.commit()
    db_session.refresh(user_alpha)
    db_session.refresh(user_beta)

    repo1 = Repository(name="r1", full_name="alpha/r1", user_id=user_alpha.id, status="ready")
    repo2 = Repository(name="r2", full_name="alpha/r2", user_id=user_alpha.id, status="ready")
    repo3 = Repository(name="r3", full_name="beta/r3", user_id=user_beta.id, status="ready")
    db_session.add_all([repo1, repo2, repo3])
    db_session.commit()
    db_session.refresh(repo1)
    db_session.refresh(repo2)
    db_session.refresh(repo3)

    token_alpha = create_session_token(user_alpha.id)
    headers_alpha = {"Cookie": f"codemind_session={token_alpha}"}

    # Disconnect repo1
    del_res = client.delete(f"/api/v1/repositories/{repo1.id}", headers=headers_alpha)
    assert del_res.status_code == 200

    # Verify repo2 in Org Alpha and repo3 in Org Beta are untouched
    assert db_session.query(Repository).filter(Repository.id == repo1.id).first() is None
    assert db_session.query(Repository).filter(Repository.id == repo2.id).first() is not None
    assert db_session.query(Repository).filter(Repository.id == repo3.id).first() is not None
