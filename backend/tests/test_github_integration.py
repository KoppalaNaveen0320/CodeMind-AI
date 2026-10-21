from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.oauth_state import OAuthState
from backend.app.models.user import User
from backend.app.integrations.github.service import GitHubService


def test_github_status_unconfigured(client: TestClient):
    """Verify GitHub status truthfully returns configured=False when credentials missing."""
    with patch.object(settings, "GITHUB_CLIENT_ID", ""):
        response = client.get("/api/v1/auth/github/status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False
        assert data["connected"] is False


def test_github_status_configured(client: TestClient, db_session: Session):
    """Verify GitHub status returns configured=True when credentials provided."""
    with patch.object(settings, "GITHUB_CLIENT_ID", "gh_test_client_id_123"):
        with patch.object(settings, "GITHUB_CLIENT_SECRET", "gh_test_secret_abc"):
            response = client.get("/api/v1/auth/github/status")
            assert response.status_code == 200
            data = response.json()
            assert data["configured"] is True


def test_github_login_unconfigured_error(client: TestClient):
    """Verify initiating GitHub login when unconfigured returns HTTP 503."""
    with patch.object(settings, "GITHUB_CLIENT_ID", ""):
        response = client.get("/api/v1/auth/github/login")
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()


def test_github_login_initiates_oauth(client: TestClient, db_session: Session):
    """Verify initiating GitHub login generates CSRF state and authorization URL."""
    with patch.object(settings, "GITHUB_CLIENT_ID", "gh_test_client_id_123"):
        with patch.object(settings, "GITHUB_CLIENT_SECRET", "gh_test_secret_abc"):
            response = client.get("/api/v1/auth/github/login")
            assert response.status_code == 200
            data = response.json()
            assert "authorization_url" in data
            assert "state" in data
            assert "gh_test_client_id_123" in data["authorization_url"]

            # Verify state was saved to database for validation
            saved_state = db_session.query(OAuthState).filter(OAuthState.state == data["state"]).first()
            assert saved_state is not None


def test_github_callback_csrf_validation_fails(client: TestClient):
    """Verify callback with fake or missing CSRF state is rejected with 400."""
    response = client.get("/api/v1/auth/github/callback?code=mock_code&state=nonexistent_state")
    assert response.status_code == 400
    assert "invalid or expired csrf state" in response.json()["detail"].lower()


def test_github_callback_success(client: TestClient, db_session: Session):
    """Verify valid CSRF state exchanges code for token and updates User."""
    with patch.object(settings, "GITHUB_CLIENT_ID", "gh_test_client_id_123"):
        with patch.object(settings, "GITHUB_CLIENT_SECRET", "gh_test_secret_abc"):
            # 1. Create valid state
            auth_url, state = GitHubService.create_oauth_authorization_url(db_session)

            mock_token_data = {
                "access_token": "gho_mock_access_token_xyz987",
                "token_type": "bearer",
                "scope": "repo,read:user"
            }
            mock_profile = {
                "id": 1234567,
                "login": "octocat_developer",
                "name": "Octocat"
            }

            with patch("backend.app.integrations.github.service.GitHubService.exchange_code_for_token", new_callable=AsyncMock) as mock_exch:
                mock_exch.return_value = mock_token_data
                with patch("backend.app.integrations.github.service.GitHubService.fetch_user_profile", new_callable=AsyncMock) as mock_prof:
                    mock_prof.return_value = mock_profile

                    response = client.get(
                        f"/api/v1/auth/github/callback?code=valid_code_123&state={state}",
                        follow_redirects=False
                    )
                    assert response.status_code == 302
                    assert "/repositories" in response.headers["location"]
                    assert "github_connected=1" in response.headers["location"]
                    assert ".html" not in response.headers["location"]

                    # Verify user in DB received token securely
                    user = db_session.query(User).filter(User.github_username == "octocat_developer").first()
                    assert user is not None
                    assert user.github_access_token == "gho_mock_access_token_xyz987"


def test_github_disconnect(client: TestClient, db_session: Session):
    """Verify disconnect clears user tokens."""
    user = db_session.query(User).first()
    if not user:
        user = User(email="test@user.dev", full_name="Test", workspace_name="Test", avatar_initials="TU")
        db_session.add(user)
    user.github_access_token = "some_token"
    user.github_username = "some_user"
    db_session.commit()

    response = client.post("/api/v1/auth/github/disconnect")
    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"

    db_session.refresh(user)
    assert user.github_access_token is None
    assert user.github_username is None
