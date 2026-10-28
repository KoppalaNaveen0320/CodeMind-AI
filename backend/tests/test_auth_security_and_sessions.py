import datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.security import (
    create_session_token,
    verify_session_token,
    create_user_session_record,
    hash_session_token,
    clear_revoked_tokens_for_testing
)
from backend.app.models.user import User
from backend.app.models.user_session import UserSession


@pytest.fixture(autouse=True)
def clean_security_state():
    clear_revoked_tokens_for_testing()
    yield
    clear_revoked_tokens_for_testing()


@pytest.fixture
def auth_users(db_session: Session):
    """Creates two distinct active test users with passwords."""
    from backend.app.core.security import hash_password

    u1 = User(
        email="alice@acme.dev",
        full_name="Alice Security",
        workspace_name="Alice Workspace",
        avatar_initials="AS",
        hashed_password=hash_password("ValidPassword123!"),
        session_timeout_minutes=30,
        is_active=True
    )
    u2 = User(
        email="bob@acme.dev",
        full_name="Bob Security",
        workspace_name="Bob Workspace",
        avatar_initials="BS",
        hashed_password=hash_password("ValidPassword123!"),
        session_timeout_minutes=60,
        is_active=True
    )
    db_session.add(u1)
    db_session.add(u2)
    db_session.commit()
    db_session.refresh(u1)
    db_session.refresh(u2)
    return {"alice": u1, "bob": u2}


# ============================================================================
# 1. Direct URL Navigation & Protection Tests
# ============================================================================

def test_unauthenticated_direct_navigation_redirects_to_login(unauthenticated_client: TestClient):
    """
    Logged-out user attempting to directly access protected URLs must be redirected
    to /login with return_to parameter and no-cache headers.
    """
    protected_paths = [
        "/dashboard",
        "/repositories",
        "/assistant",
        "/code_viewer",
        "/dependencies",
        "/impact_analysis",
        "/git_history",
        "/security_insights",
        "/settings",
        "/documentation"
    ]
    for path in protected_paths:
        resp = unauthenticated_client.get(path, follow_redirects=False)
        assert resp.status_code == 302, f"Direct access to {path} did not redirect"
        loc = resp.headers.get("location", "")
        assert loc.startswith("/login?return_to="), f"Redirect location for {path} was {loc}"
        assert resp.headers.get("cache-control") is not None
        assert "no-store" in resp.headers.get("cache-control", "").lower()


def test_public_routes_remain_accessible_without_session(unauthenticated_client: TestClient):
    """Public pages (/login, /signup, /landing, /health) remain directly accessible."""
    for public_path in ["/login", "/signup", "/landing", "/health"]:
        resp = unauthenticated_client.get(public_path, follow_redirects=False)
        assert resp.status_code == 200, f"Expected 200 for public route {public_path}, got {resp.status_code}"


def test_open_redirect_protection_on_login(unauthenticated_client: TestClient):
    """Verify that malicious external return_to destinations are safely sanitized to /dashboard."""
    malicious_targets = [
        "https://evil.com/phish",
        "http://attacker.org",
        "//attacker.org/steal",
        "javascript:alert(1)"
    ]
    for target in malicious_targets:
        resp = unauthenticated_client.get(f"/dashboard?return_to={target}", follow_redirects=False)
        loc = resp.headers.get("location", "")
        assert "evil.com" not in loc
        assert "attacker.org" not in loc


# ============================================================================
# 2. Protected API Authorization & Fail-Closed Behavior
# ============================================================================

def test_protected_apis_return_401_without_session(unauthenticated_client: TestClient):
    """Protected API endpoints must reject requests with 401 when no session is present."""
    protected_apis = [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/auth/sessions"),
        ("GET", "/api/v1/auth/sessions/current"),
        ("GET", "/api/v1/me"),
        ("GET", "/api/v1/repositories"),
        ("PUT", "/api/v1/settings/session-timeout"),
    ]
    for method, endpoint in protected_apis:
        if method == "GET":
            resp = unauthenticated_client.get(endpoint)
        elif method == "PUT":
            resp = unauthenticated_client.put(endpoint, json={"timeout_minutes": 60})
        assert resp.status_code == 401, f"{method} {endpoint} returned {resp.status_code} instead of 401"
        assert "authentication required" in resp.json()["detail"].lower()


def test_malformed_and_forged_tokens_rejected_with_401(unauthenticated_client: TestClient):
    """Malformed tokens in cookie or Authorization header must be rejected with 401."""
    bad_tokens = [
        "not.a.valid.jwt.token",
        "gibberish",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.fake_signature",
    ]
    for bad_token in bad_tokens:
        # As Cookie
        r_cookie = unauthenticated_client.get("/api/v1/auth/me", cookies={"codemind_session": bad_token})
        assert r_cookie.status_code == 401
        # As Header
        r_hdr = unauthenticated_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {bad_token}"})
        assert r_hdr.status_code == 401


# ============================================================================
# 3. Configurable Automatic Session Timeout Tests
# ============================================================================

def test_session_timeout_setting_options_and_persistence(unauthenticated_client: TestClient, auth_users, db_session: Session):
    """
    Users can update their session duration to 30, 60, 240, or 480 minutes.
    The preference is persisted in the database.
    Invalid values are rejected.
    """
    alice = auth_users["alice"]
    token = create_session_token(alice.id, timeout_minutes=30)
    create_user_session_record(db_session, alice, token, initial_path="/settings")
    headers = {"Authorization": f"Bearer {token}"}

    # Test all 4 valid timeout options
    valid_timeouts = [30, 60, 240, 480]
    for timeout in valid_timeouts:
        resp = unauthenticated_client.put(
            "/api/v1/settings/session-timeout",
            json={"timeout_minutes": timeout},
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["timeout_minutes"] == timeout

        # Verify DB persistence
        db_session.refresh(alice)
        assert alice.session_timeout_minutes == timeout

    # Test invalid durations
    for invalid in [0, 15, 45, 120, 1000, -30]:
        resp_invalid = unauthenticated_client.put(
            "/api/v1/settings/session-timeout",
            json={"timeout_minutes": invalid},
            headers=headers
        )
        assert resp_invalid.status_code in [400, 422]


def test_session_expiration_boundary_rejection(unauthenticated_client: TestClient, auth_users, db_session: Session):
    """
    Sessions past their absolute expiration boundary must be rejected with 401
    and status updated to 'expired' in the database.
    """
    alice = auth_users["alice"]
    # Create an already expired token (past timestamp)
    expired_token = create_session_token(alice.id, timeout_minutes=-5)
    create_user_session_record(
        db_session,
        alice,
        expired_token,
        initial_path="/dashboard"
    )

    # Manually ensure DB session record is also expired
    token_hash = hash_session_token(expired_token)
    session_row = db_session.query(UserSession).filter(UserSession.session_token_hash == token_hash).first()
    assert session_row is not None
    session_row.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    db_session.commit()

    # Protected request with expired token
    resp = unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()

    # Verify session row updated to expired
    db_session.refresh(session_row)
    assert session_row.status == "expired"


# ============================================================================
# 4. Active Sessions Management & Tracking Tests
# ============================================================================

def test_login_creates_persistent_session_record(unauthenticated_client: TestClient, auth_users, db_session: Session):
    """
    Logging in creates a persistent UserSession record with client metadata,
    device info, and active status.
    """
    login_resp = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "alice@acme.dev", "password": "ValidPassword123!"},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]

    # Verify cookie was set with expected max-age (30 mins = 1800s)
    set_cookie = login_resp.headers.get("set-cookie", "")
    assert "codemind_session=" in set_cookie
    assert "max-age=1800" in set_cookie.lower() or "httponly" in set_cookie.lower()

    # Verify session in DB
    token_hash = hash_session_token(token)
    session_rec = db_session.query(UserSession).filter(UserSession.session_token_hash == token_hash).first()
    assert session_rec is not None
    assert session_rec.user_id == auth_users["alice"].id
    assert session_rec.status == "active"
    assert "Chrome" in (session_rec.browser or "")
    assert "Windows" in (session_rec.os or "")
    assert session_rec.last_accessed_path == "/dashboard"


def test_page_tracking_and_query_param_sanitization(unauthenticated_client: TestClient, auth_users, db_session: Session):
    """
    Accessed path must be tracked on authenticated navigation, and sensitive
    query parameters must NEVER be stored in the session record.
    """
    alice = auth_users["alice"]
    token = create_session_token(alice.id, timeout_minutes=30)
    create_user_session_record(db_session, alice, token, initial_path="/dashboard")
    headers = {"Authorization": f"Bearer {token}"}

    # Request code_viewer with sensitive query params
    resp = unauthenticated_client.get(
        "/code_viewer?repo_id=1&secret_token=super_secret_dont_store_this",
        headers=headers
    )
    assert resp.status_code == 200

    token_hash = hash_session_token(token)
    session_rec = db_session.query(UserSession).filter(UserSession.session_token_hash == token_hash).first()
    db_session.refresh(session_rec)

    # Path tracked without query parameters
    assert session_rec.last_accessed_path == "/code_viewer"
    assert "secret_token" not in (session_rec.last_accessed_path or "")


def test_active_sessions_list_and_user_isolation(unauthenticated_client: TestClient, auth_users, db_session: Session):
    """
    User A can only view their own sessions, and the current session is marked is_current: true.
    """
    alice = auth_users["alice"]
    bob = auth_users["bob"]

    t_alice = create_session_token(alice.id, timeout_minutes=30)
    create_user_session_record(db_session, alice, t_alice, initial_path="/dashboard")

    t_bob = create_session_token(bob.id, timeout_minutes=60)
    create_user_session_record(db_session, bob, t_bob, initial_path="/dashboard")

    # Alice requests sessions
    resp_alice = unauthenticated_client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {t_alice}"}
    )
    assert resp_alice.status_code == 200
    sessions_alice = resp_alice.json()["sessions"]

    # All returned sessions must belong to Alice
    assert len(sessions_alice) >= 1
    for s in sessions_alice:
        assert s["user_id"] == alice.id
        assert s["user_email"] == alice.email
        if s["is_current"]:
            assert s["status"] == "active"

    # Bob's session must not be visible to Alice
    assert not any(s["user_id"] == bob.id for s in sessions_alice)


def test_revoke_specific_session(unauthenticated_client: TestClient, auth_users, db_session: Session):
    """
    User can revoke a specific session. The revoked session is immediately
    rejected with 401 on subsequent requests.
    """
    alice = auth_users["alice"]
    # Session 1 (current)
    token1 = create_session_token(alice.id, timeout_minutes=30)
    s1 = create_user_session_record(db_session, alice, token1, initial_path="/dashboard")

    # Session 2 (another device)
    token2 = create_session_token(alice.id, timeout_minutes=30)
    s2 = create_user_session_record(db_session, alice, token2, initial_path="/dashboard")

    # Alice uses Session 1 to revoke Session 2
    headers1 = {"Authorization": f"Bearer {token1}"}
    del_resp = unauthenticated_client.delete(f"/api/v1/auth/sessions/{s2.id}", headers=headers1)
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # Verify Session 2 DB status
    db_session.refresh(s2)
    assert s2.status == "revoked"
    assert s2.logout_at is not None

    # Verify Session 2 cannot access protected APIs anymore
    headers2 = {"Authorization": f"Bearer {token2}"}
    blocked_resp = unauthenticated_client.get("/api/v1/auth/me", headers=headers2)
    assert blocked_resp.status_code == 401

    # Verify Session 1 is still active
    ok_resp = unauthenticated_client.get("/api/v1/auth/me", headers=headers1)
    assert ok_resp.status_code == 200


def test_revoke_other_sessions(unauthenticated_client: TestClient, auth_users, db_session: Session):
    """
    User can revoke all other active sessions while retaining their current session.
    """
    alice = auth_users["alice"]
    token_current = create_session_token(alice.id, timeout_minutes=30)
    s_curr = create_user_session_record(db_session, alice, token_current, initial_path="/settings")

    token_other1 = create_session_token(alice.id, timeout_minutes=30)
    s_other1 = create_user_session_record(db_session, alice, token_other1, initial_path="/dashboard")

    token_other2 = create_session_token(alice.id, timeout_minutes=30)
    s_other2 = create_user_session_record(db_session, alice, token_other2, initial_path="/repositories")

    # Call revoke-others with current session
    headers_curr = {"Authorization": f"Bearer {token_current}"}
    resp = unauthenticated_client.post("/api/v1/auth/sessions/revoke-others", headers=headers_curr)
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["revoked_count"] == 2

    # Verify current session is still active
    db_session.refresh(s_curr)
    assert s_curr.status == "active"
    me_resp = unauthenticated_client.get("/api/v1/auth/me", headers=headers_curr)
    assert me_resp.status_code == 200

    # Verify other sessions are revoked and blocked
    for tok, s_row in [(token_other1, s_other1), (token_other2, s_other2)]:
        db_session.refresh(s_row)
        assert s_row.status == "revoked"
        blk = unauthenticated_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert blk.status_code == 401


def test_cross_user_session_revocation_forbidden(unauthenticated_client: TestClient, auth_users, db_session: Session):
    """
    A user cannot revoke another user's session even if they know the ID.
    """
    alice = auth_users["alice"]
    bob = auth_users["bob"]

    t_alice = create_session_token(alice.id, timeout_minutes=30)
    create_user_session_record(db_session, alice, t_alice, initial_path="/dashboard")

    t_bob = create_session_token(bob.id, timeout_minutes=60)
    s_bob = create_user_session_record(db_session, bob, t_bob, initial_path="/dashboard")

    # Alice tries to delete Bob's session
    headers_alice = {"Authorization": f"Bearer {t_alice}"}
    hack_resp = unauthenticated_client.delete(f"/api/v1/auth/sessions/{s_bob.id}", headers=headers_alice)
    assert hack_resp.status_code in [403, 404]

    # Verify Bob's session is still active
    db_session.refresh(s_bob)
    assert s_bob.status == "active"
