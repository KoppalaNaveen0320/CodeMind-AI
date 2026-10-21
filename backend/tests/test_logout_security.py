import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.core.config import settings
from backend.app.core.security import (
    create_session_token,
    verify_session_token,
    revoke_session_token,
    is_token_revoked,
    clear_revoked_tokens_for_testing
)


@pytest.fixture(autouse=True)
def cleanup_revoked_tokens():
    """Ensure clean token revocation state for each test."""
    clear_revoked_tokens_for_testing()
    yield
    clear_revoked_tokens_for_testing()


def test_top_right_logout_button_rendered_and_accessible(client: TestClient):
    """
    Verify top-right header logout button is present, has accessible label,
    contains the log-out icon, and is adjacent to the avatar.
    """
    for page in ["/dashboard", "/repositories", "/assistant", "/code_viewer", "/dashboard.html"]:
        resp = client.get(page, follow_redirects=True)
        assert resp.status_code == 200
        html = resp.text

        # Top-right header logout button exists
        assert "header-logout-btn" in html
        assert 'id="header-logout-btn"' in html

        # Accessible label / tooltip
        assert 'aria-label="Logout"' in html
        assert 'title="Logout"' in html

        # Notification bell and avatar preserved
        assert "notification" in html
        assert "avatar-button" in html

        # Log-out SVG icon check (door path and arrow line)
        assert 'd="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"' in html
        assert 'polyline points="16 17 21 12 16 7"' in html


def test_bottom_left_profile_dropdown_contains_logout_option(client: TestClient):
    """
    Verify bottom-left profile dropdown exists, displays user details without duplicate elements or overlap,
    and includes Settings and Logout menuitem actions.
    """
    for page in ["/dashboard", "/repositories", "/assistant", "/dashboard.html"]:
        resp = client.get(page, follow_redirects=True)
        assert resp.status_code == 200
        html = resp.text

        # Sidebar profile section container and dropdown trigger
        assert 'sidebar-profile-section' in html
        assert 'id="sidebar-profile-container"' in html
        assert 'id="sidebar-profile-trigger"' in html
        assert 'aria-haspopup="true"' in html
        assert 'aria-expanded="false"' in html

        # Profile avatar and details - verify SINGLE occurrence (no duplicate inside dropdown)
        assert html.count('id="sidebar-profile-avatar"') == 1
        assert html.count('id="sidebar-profile-name"') == 1
        assert html.count('id="sidebar-profile-email"') == 1

        # Menu no longer has duplicate user info
        assert 'id="menu-profile-avatar"' not in html
        assert 'id="menu-profile-name"' not in html
        assert 'id="menu-profile-email"' not in html

        # Profile dropdown menu structure
        assert 'id="sidebar-profile-menu"' in html
        assert 'role="menu"' in html
        assert "Settings" in html

        # Logout menuitem action
        assert 'id="sidebar-logout-btn"' in html
        assert 'role="menuitem"' in html
        assert "logout-action" in html
        assert "Logout" in html

        # Workspace switcher is completely removed from sidebar
        assert '<div class="workspace">' not in html
        assert 'class="workspace-icon"' not in html


def test_both_controls_invoke_same_logout_flow(client: TestClient):
    """
    Verify that both header and sidebar controls are bound to the same unified
    executeSecureLogout flow in api.js, calling /api/v1/auth/logout and redirecting to /login.html.
    """
    resp = client.get("/static/js/api.js")
    assert resp.status_code == 200
    js = resp.text

    # Unified secure logout handler exists
    assert "async function executeSecureLogout()" in js
    assert "fetch('/api/v1/auth/logout'" in js or 'fetch("/api/v1/auth/logout"' in js

    # Both header and sidebar controls are wired to executeSecureLogout
    assert "headerLogoutBtns" in js or "header-logout-btn" in js
    assert "sidebarLogoutBtns" in js or "sidebar-logout-btn" in js
    assert "setupLogoutControls()" in js

    # Redirection to existing login page (/login)
    assert "/login" in js

    # API client exposes the same unified logout
    assert "async logout()" in js
    assert "return executeSecureLogout();" in js


def test_successful_logout_clears_cookie_and_returns_status(client: TestClient):
    """
    Verify calling POST /api/v1/auth/logout clears the session cookie and returns 200.
    """
    token = create_session_token(1)

    # Call logout with cookie
    client.cookies.set("codemind_session", token)
    logout_resp = client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200
    data = logout_resp.json()
    assert data["success"] is True
    assert "signed out" in data["message"].lower()

    # Verify session cookie is cleared
    set_cookie = logout_resp.headers.get("set-cookie", "")
    assert "codemind_session=" in set_cookie
    assert 'max-age=0' in set_cookie.lower() or 'expires=' in set_cookie.lower()


def test_revoked_session_token_rejected_after_logout(client: TestClient, db_session: Session):
    """
    Verify that an invalidated session token cannot be reused to access protected resources.
    """
    user = User(
        email="revocation_user@acme.dev",
        full_name="Revocation Tester",
        workspace_name="Security Testing",
        avatar_initials="RT",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    # 1. Generate a valid session token for user
    token = create_session_token(user.id)
    assert verify_session_token(token) == user.id

    # 2. Verify token grants access before logout
    headers = {"Authorization": f"Bearer {token}"}
    me_resp = client.get("/api/v1/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == user.email

    # 3. Call logout with the Bearer token
    logout_resp = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_resp.status_code == 200

    # 4. Attempt to reuse the revoked token via Authorization header
    me_after = client.get("/api/v1/auth/me", headers=headers)
    assert me_after.status_code == 401
    assert "invalid or expired" in me_after.json()["detail"].lower()

    # 5. Attempt to reuse the revoked token via Cookie
    cookie_headers = {"Cookie": f"codemind_session={token}"}
    me_cookie = client.get("/api/v1/auth/me", headers=cookie_headers)
    assert me_cookie.status_code == 401
    assert "invalid or expired" in me_cookie.json()["detail"].lower()


def test_repeated_logout_requests_handled_safely(client: TestClient):
    """
    Verify repeated logout requests succeed idempotently without error.
    """
    token = create_session_token(99)

    # First logout with cookie
    resp1 = client.post(
        "/api/v1/auth/logout",
        cookies={"codemind_session": token}
    )
    assert resp1.status_code == 200
    assert resp1.json()["success"] is True

    # Second logout with same revoked token
    resp2 = client.post(
        "/api/v1/auth/logout",
        cookies={"codemind_session": token}
    )
    assert resp2.status_code == 200
    assert resp2.json()["success"] is True

    # Third logout with no cookie or token at all
    resp3 = client.post("/api/v1/auth/logout")
    assert resp3.status_code == 200
    assert resp3.json()["success"] is True


def test_browser_cache_control_headers_on_protected_pages(client: TestClient):
    """
    Verify that sensitive authenticated HTML pages emit strict no-cache headers
    preventing browser back navigation from serving cached dashboard state after logout.
    """
    protected_routes = [
        "/",
        "/dashboard",
        "/dashboard.html",
        "/repositories",
        "/repositories.html",
        "/assistant",
        "/assistant.html",
        "/code_viewer.html",
        "/dependencies",
        "/dependencies.html",
        "/impact_analysis.html",
        "/git_history.html",
        "/security_insights.html",
        "/docs.html",
        "/settings.html"
    ]

    for route in protected_routes:
        resp = client.get(route, follow_redirects=True)
        assert resp.status_code == 200
        cache_control = resp.headers.get("cache-control", "").lower()
        assert "no-store" in cache_control, f"Route {route} missing no-store in Cache-Control"
        assert "no-cache" in cache_control, f"Route {route} missing no-cache in Cache-Control"
        assert "must-revalidate" in cache_control, f"Route {route} missing must-revalidate in Cache-Control"
        assert resp.headers.get("pragma", "").lower() == "no-cache"


def test_server_side_token_revocation_logic_direct():
    """
    Directly verify token revocation registry and verification lifecycle.
    """
    user_id = 12345
    token = create_session_token(user_id)

    # Before revocation: valid
    assert is_token_revoked(token) is False
    assert verify_session_token(token) == user_id

    # Revoke token
    revoked = revoke_session_token(token)
    assert revoked is True

    # After revocation: revoked and returns None
    assert is_token_revoked(token) is True
    assert verify_session_token(token) is None

    # Revoking invalid or empty token safely returns False
    assert revoke_session_token("") is False
    assert revoke_session_token(None) is False
    assert is_token_revoked("") is False
    assert is_token_revoked(None) is False


def test_protected_api_enforces_auth_when_required(client: TestClient):
    """
    Verify that protected endpoints reject requests when strict authentication is required.
    """
    # Request without token when x-require-auth is sent
    resp = client.get("/api/v1/auth/me", headers={"x-require-auth": "true"})
    assert resp.status_code == 401
    assert "authentication required" in resp.json()["detail"].lower()


def test_login_routes_return_200_and_render_form(client: TestClient):
    """
    Verify that /login.html and /login are served by the application
    and render the expected login page with form elements.
    """
    for route in ["/login", "/login.html"]:
        resp = client.get(route, follow_redirects=True)
        assert resp.status_code == 200
        html = resp.text
        assert 'id="login-form"' in html
        assert 'id="login-email"' in html
        assert 'id="login-password"' in html
        assert 'id="login-submit-btn"' in html


def test_logout_failure_handles_error_without_blanking(client: TestClient):
    """
    Verify that when logout request fails or returns an error,
    client code handles errors gracefully instead of silently blanking credentials.
    """
    resp = client.get("/static/js/api.js")
    assert resp.status_code == 200
    js = resp.text

    # Credentials must only be cleared if res.ok
    assert "if (!res.ok)" in js
    # Error message must be shown to the user
    assert "alert(" in js
    # Credentials removed upon successful logout
    assert "localStorage.removeItem('codemind_auth_token')" in js
    # Redirects reliably to login page
    assert "window.location.href = '/login'" in js
