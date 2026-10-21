import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import patch, AsyncMock

from backend.app.integrations.github.service import GitHubService, GitHubServiceError
from backend.app.models.repository import Repository
from backend.app.models.user import User
from backend.app.core.security import create_session_token


def test_experdecision_owner_repo_path_parsing():
    """
    Verify owner and repository path parsing for KoppalaNaveen/experdecision
    and KoppalaNaveen/expertdecision across accepted formats:
    - owner/repo
    - full https:// URL
    - URL with .git suffix
    - paths with leading/trailing whitespace and slashes
    """
    test_cases = [
        ("KoppalaNaveen/experdecision", "KoppalaNaveen", "experdecision"),
        ("https://github.com/KoppalaNaveen/experdecision", "KoppalaNaveen", "experdecision"),
        ("https://github.com/KoppalaNaveen/experdecision.git", "KoppalaNaveen", "experdecision"),
        ("  https://github.com/KoppalaNaveen/experdecision/  ", "KoppalaNaveen", "experdecision"),
        ("KoppalaNaveen/expertdecision", "KoppalaNaveen", "expertdecision"),
        ("https://github.com/KoppalaNaveen/expertdecision", "KoppalaNaveen", "expertdecision"),
        ("https://github.com/KoppalaNaveen/expertdecision.git", "KoppalaNaveen", "expertdecision"),
        ("  KoppalaNaveen/expertdecision/  ", "KoppalaNaveen", "expertdecision"),
    ]

    for raw_input, expected_owner, expected_repo in test_cases:
        owner, repo = GitHubService.normalize_and_validate_repo_input(raw_input)
        assert owner == expected_owner, f"Failed for {raw_input}: expected owner {expected_owner}, got {owner}"
        assert repo == expected_repo, f"Failed for {raw_input}: expected repo {expected_repo}, got {repo}"


def test_nonexistent_repository_returns_404_not_access_denied(client: TestClient, db_session: Session):
    """
    Verify that a nonexistent or inaccessible repository returns HTTP 404 with a helpful message,
    and is NOT mislabeled as 'Access denied to this repository'.
    """
    mock_resp = httpx.Response(
        status_code=404,
        headers={"x-github-request-id": "MOCK-REQ-404"},
        json={"message": "Not Found", "documentation_url": "https://docs.github.com/rest/repos/repos#get-a-repository"}
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        res = client.post(
            "/api/v1/repositories/connect-public",
            json={"repository": "KoppalaNaveen/experdecision", "auto_index": False}
        )
        assert res.status_code == 404
        detail = res.json()["detail"]
        assert "not found or is inaccessible" in detail.lower()
        assert "Access denied to this repository" not in detail


def test_working_public_repository_connects_successfully(client: TestClient, db_session: Session):
    """
    Verify that a valid public GitHub repository connects and returns 201 Created.
    """
    mock_resp = httpx.Response(
        status_code=200,
        headers={"x-github-request-id": "MOCK-REQ-200"},
        json={
            "id": 987654321,
            "name": "expertdecision",
            "full_name": "KoppalaNaveen/expertdecision-mock-test",
            "description": "Expert Decision Support Platform",
            "private": False,
            "default_branch": "main",
            "language": "Python",
            "html_url": "https://github.com/KoppalaNaveen/expertdecision-mock-test",
            "clone_url": "https://github.com/KoppalaNaveen/expertdecision-mock-test.git",
            "owner": {"login": "KoppalaNaveen"}
        }
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        res = client.post(
            "/api/v1/repositories/connect-public",
            json={"repository": "KoppalaNaveen/expertdecision-mock-test", "auto_index": False}
        )
        assert res.status_code == 201
        data = res.json()
        assert data["full_name"] == "KoppalaNaveen/expertdecision-mock-test"
        assert data["is_private"] is False


def test_private_repository_without_oauth_rejected_with_guidance(client: TestClient, db_session: Session):
    """
    Verify that resolving a private repository through the public connection flow without OAuth
    returns HTTP 400 instructing the user to use GitHub OAuth.
    """
    mock_resp = httpx.Response(
        status_code=200,
        headers={"x-github-request-id": "MOCK-REQ-PRIV"},
        json={
            "id": 987654322,
            "name": "private-project",
            "full_name": "KoppalaNaveen/private-project",
            "private": True,
            "default_branch": "main",
            "owner": {"login": "KoppalaNaveen"}
        }
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        res = client.post(
            "/api/v1/repositories/connect-public",
            json={"repository": "KoppalaNaveen/private-project", "auto_index": False}
        )
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert "private repository" in detail.lower()
        assert "oauth" in detail.lower()


def test_github_rate_limiting_distinguished_from_permission_forbidden(client: TestClient, db_session: Session):
    """
    Verify distinction between:
    - GitHub API rate limiting (429 or 403 with rate limit headers/body)
    - GitHub permission failure (403 forbidden)
    """
    # 1. GitHub 403 with rate limit body
    mock_rl_body = httpx.Response(
        status_code=403,
        headers={"x-github-request-id": "MOCK-RL-1"},
        text="API rate limit exceeded for 192.0.2.1"
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_rl_body
        res = client.post(
            "/api/v1/repositories/connect-public",
            json={"repository": "pallets/flask-rl1", "auto_index": False}
        )
        assert res.status_code == 429
        assert "rate limit exceeded" in res.json()["detail"].lower()

    # 2. GitHub 403 with x-ratelimit-remaining: 0
    mock_rl_hdr = httpx.Response(
        status_code=403,
        headers={"x-github-request-id": "MOCK-RL-2", "x-ratelimit-remaining": "0"},
        text="Forbidden"
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_rl_hdr
        res = client.post(
            "/api/v1/repositories/connect-public",
            json={"repository": "pallets/flask-rl2", "auto_index": False}
        )
        assert res.status_code == 429
        assert "rate limit exceeded" in res.json()["detail"].lower()

    # 3. GitHub 429 status code
    mock_429 = httpx.Response(
        status_code=429,
        headers={"x-github-request-id": "MOCK-RL-3"},
        text="Too Many Requests"
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_429
        res = client.post(
            "/api/v1/repositories/connect-public",
            json={"repository": "pallets/flask-rl3", "auto_index": False}
        )
        assert res.status_code == 429
        assert "rate limit exceeded" in res.json()["detail"].lower()

    # 4. GitHub 403 genuine permission failure
    mock_403_perm = httpx.Response(
        status_code=403,
        headers={"x-github-request-id": "MOCK-PERM-403", "x-ratelimit-remaining": "50"},
        text="Resource not accessible by integration"
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_403_perm
        res = client.post(
            "/api/v1/repositories/connect-public",
            json={"repository": "org/restricted-repo", "auto_index": False}
        )
        assert res.status_code == 403
        assert "forbidden by github permissions" in res.json()["detail"].lower()


def test_github_timeout_and_5xx_service_error_handling(client: TestClient, db_session: Session):
    """
    Verify proper handling of network timeouts (504) and GitHub 5xx errors (502).
    """
    # 1. Timeout
    with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Read timed out")):
        res = client.post(
            "/api/v1/repositories/connect-public",
            json={"repository": "org/slow-repo", "auto_index": False}
        )
        assert res.status_code == 504
        assert "timed out" in res.json()["detail"].lower()

    # 2. GitHub 503 Service Unavailable
    mock_503 = httpx.Response(
        status_code=503,
        headers={"x-github-request-id": "MOCK-503"},
        text="Service Unavailable"
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_503
        res = client.post(
            "/api/v1/repositories/connect-public",
            json={"repository": "org/down-repo", "auto_index": False}
        )
        assert res.status_code == 502
        assert "temporarily unavailable" in res.json()["detail"].lower()


def test_same_workspace_ownership_transfer_and_access(client: TestClient, db_session: Session):
    """
    Regression Test for Root Cause:
    When user 1 (Alex Kim in 'Acme Engineering') previously connected KoppalaNaveen/expertdecision,
    user 2 (Koppala Naveen in 'Acme Engineering') connecting the same repository must succeed,
    transfer or associate ownership with the active user, and NOT raise 'Access denied to this repository'.
    """
    # Create two users in the same workspace
    dev_user = User(
        email="alex.kim.regtest@acme.dev",
        full_name="Alex Kim",
        workspace_name="Acme Engineering",
        avatar_initials="AK",
        is_active=True
    )
    naveen_user = User(
        email="koppalanaveen.regtest@acme.dev",
        full_name="Koppala Naveen",
        workspace_name="Acme Engineering",
        avatar_initials="KN",
        is_active=True
    )
    db_session.add_all([dev_user, naveen_user])
    db_session.commit()
    db_session.refresh(dev_user)
    db_session.refresh(naveen_user)

    # Dev user registers expertdecision
    existing_repo = Repository(
        name="expertdecision",
        full_name="KoppalaNaveen/expertdecision-ws-test",
        description="Original dev connection",
        is_private=False,
        default_branch="main",
        user_id=dev_user.id,
        status="ready"
    )
    db_session.add(existing_repo)
    db_session.commit()
    db_session.refresh(existing_repo)

    naveen_token = create_session_token(naveen_user.id)
    naveen_headers = {"Authorization": f"Bearer {naveen_token}"}

    # Naveen connects the repository in his account
    mock_resp = httpx.Response(
        status_code=200,
        headers={"x-github-request-id": "MOCK-WS-200"},
        json={
            "id": 999111222,
            "name": "expertdecision-ws-test",
            "full_name": "KoppalaNaveen/expertdecision-ws-test",
            "description": "Updated by Naveen",
            "private": False,
            "default_branch": "main",
            "language": "Python",
            "owner": {"login": "KoppalaNaveen"}
        }
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        res = client.post(
            "/api/v1/repositories/connect-public",
            json={"repository": "KoppalaNaveen/expertdecision-ws-test", "auto_index": False},
            headers=naveen_headers
        )
        assert res.status_code == 201
        data = res.json()
        assert data["id"] == existing_repo.id
        assert data["user_id"] == naveen_user.id

    # Verify Naveen can retrieve repo details without 403
    get_res = client.get(f"/api/v1/repositories/{existing_repo.id}", headers=naveen_headers)
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "expertdecision-ws-test"


def test_cross_workspace_isolation_strictly_preserved(client: TestClient, db_session: Session):
    """
    Verify security controls:
    A user in 'Competitor Lab' cannot access, hijack, or connect a private repository
    belonging to 'Enterprise Workspace'.
    """
    user_alice = User(
        email="alice.regtest@enterprise.dev",
        full_name="Alice Lead",
        workspace_name="Enterprise Workspace",
        is_active=True
    )
    user_bob = User(
        email="bob.regtest@competitor.dev",
        full_name="Bob Attacker",
        workspace_name="Competitor Lab",
        is_active=True
    )
    db_session.add_all([user_alice, user_bob])
    db_session.commit()
    db_session.refresh(user_alice)
    db_session.refresh(user_bob)

    alice_repo = Repository(
        name="proprietary-ai",
        full_name="enterprise/proprietary-ai",
        is_private=True,
        user_id=user_alice.id,
        status="ready"
    )
    db_session.add(alice_repo)
    db_session.commit()
    db_session.refresh(alice_repo)

    bob_token = create_session_token(user_bob.id)
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # 1. Bob cannot register/overwrite Alice's private repo via register_repository (IDOR protection)
    reg_res = client.post(
        "/api/v1/repositories?auto_index=false",
        json={"name": "proprietary-ai", "full_name": "enterprise/proprietary-ai", "is_private": True},
        headers=bob_headers
    )
    assert reg_res.status_code == 403
    assert "Access denied to this repository" in reg_res.json()["detail"]

    # 2. Bob cannot connect Alice's private repo via connect-public
    mock_resp = httpx.Response(
        status_code=200,
        headers={"x-github-request-id": "MOCK-PROBE"},
        json={
            "id": 111222333,
            "name": "proprietary-ai",
            "full_name": "enterprise/proprietary-ai",
            "private": True,
            "default_branch": "main",
            "owner": {"login": "enterprise"}
        }
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = client.post(
            "/api/v1/repositories/connect-public",
            json={"repository": "enterprise/proprietary-ai", "auto_index": False},
            headers=bob_headers
        )
        assert res.status_code in (400, 403)
        assert "private repository" in res.json()["detail"].lower() or "access denied" in res.json()["detail"].lower()

    # 2. Bob cannot view Alice's repo
    get_res = client.get(f"/api/v1/repositories/{alice_repo.id}", headers=bob_headers)
    assert get_res.status_code == 403
    assert "Access denied to this repository" in get_res.json()["detail"]

    # 3. Bob cannot delete Alice's repo
    del_res = client.delete(f"/api/v1/repositories/{alice_repo.id}", headers=bob_headers)
    assert del_res.status_code == 403
    assert "Access denied to this repository" in del_res.json()["detail"]

    # 4. Bob's repo list does NOT include Alice's repo
    list_res = client.get("/api/v1/repositories", headers=bob_headers)
    assert list_res.status_code == 200
    repo_ids = [r["id"] for r in list_res.json()]
    assert alice_repo.id not in repo_ids
