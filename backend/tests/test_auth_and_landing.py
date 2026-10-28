import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.core.security import hash_password, verify_password, create_session_token, verify_session_token

client = TestClient(app)


def test_landing_and_auth_views():
    """Verify landing, login, and signup routes return 200 and expected markup."""
    resp_landing = client.get("/landing")
    assert resp_landing.status_code == 200
    assert "CodeMind AI" in resp_landing.text
    assert "Repository Understanding" in resp_landing.text
    assert "Sign In" in resp_landing.text or "Sign in" in resp_landing.text

    resp_login = client.get("/login")
    assert resp_login.status_code == 200
    assert "Welcome back" in resp_login.text
    assert "login-form" in resp_login.text

    resp_signup = client.get("/signup")
    assert resp_signup.status_code == 200
    assert "Create your account" in resp_signup.text
    assert "signup-form" in resp_signup.text


def test_password_hashing_and_verification():
    """Test standard cryptographic password hashing."""
    pwd = "SecureMasterPassword123!"
    hashed = hash_password(pwd)
    assert hashed.startswith("pbkdf2_sha256$600000$")
    assert verify_password(pwd, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


def test_session_token_creation_and_decoding():
    """Test URL-safe HMAC signed session token generation and verification."""
    token = create_session_token(42)
    assert token is not None
    user_id = verify_session_token(token)
    assert user_id == 42

    # Corrupted token
    bad_token = token + "corrupt"
    assert verify_session_token(bad_token) is None



def test_register_duplicate_and_login_flow(client: TestClient):
    """Test user registration, duplicate prevention, and login flow via REST API."""
    import uuid
    test_email = f"auth_test_{uuid.uuid4().hex[:8]}@codemind.dev"
    test_password = "StrongPassword987!"

    # 1. Register new account
    reg_resp = client.post("/api/v1/auth/register", json={
        "email": test_email,
        "password": test_password,
        "full_name": "Auth Tester"
    })
    assert reg_resp.status_code in (201, 400)
    if reg_resp.status_code == 201:
        reg_data = reg_resp.json()
        assert reg_data["user"]["email"] == test_email
        assert "codemind_session" in reg_resp.cookies

    # 2. Duplicate registration rejected
    dup_resp = client.post("/api/v1/auth/register", json={
        "email": test_email,
        "password": test_password,
        "full_name": "Auth Tester"
    })
    assert dup_resp.status_code == 400
    assert "already exists" in dup_resp.json()["detail"].lower()

    # 3. Login with wrong password
    bad_login = client.post("/api/v1/auth/login", json={
        "email": test_email,
        "password": "WrongPassword!"
    })
    assert bad_login.status_code == 401

    # 4. Login with correct password
    good_login = client.post("/api/v1/auth/login", json={
        "email": test_email,
        "password": test_password
    })
    assert good_login.status_code == 200
    login_data = good_login.json()
    assert login_data["user"]["email"] == test_email
    assert "codemind_session" in good_login.cookies

    # 5. Access /me endpoint with session cookie
    me_resp = client.get("/api/v1/auth/me", cookies=good_login.cookies)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == test_email

    # 6. Logout clears cookie
    logout_resp = client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200


def test_auth_validation_errors(client: TestClient):
    """Test short password validation and invalid email rejection."""
    short_pwd_resp = client.post("/api/v1/auth/register", json={
        "email": "valid@email.com",
        "password": "short"
    })
    assert short_pwd_resp.status_code == 422

    bad_email_resp = client.post("/api/v1/auth/register", json={
        "email": "not-an-email",
        "password": "ValidPassword123!"
    })
    assert bad_email_resp.status_code == 422


def test_login_database_error_graceful_handling(client: TestClient, monkeypatch):
    """
    Regression test: Database operational errors during login must return a user-friendly
    503 error without unhandled 500 crashes and without leaking credentials in logs.
    """
    from sqlalchemy.exc import OperationalError
    from unittest.mock import MagicMock

    def mock_query_failure(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("Connection refused"))

    from backend.app.models.user import User
    # Mock db.query to simulate database connection loss during login
    from backend.app.api.routes.auth import get_db

    # Trigger login when DB query raises OperationalError
    with monkeypatch.context() as m:
        m.setattr("sqlalchemy.orm.Session.query", mock_query_failure)
        resp = client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "SomePassword123!"
        })
        # Must return 503 Service Unavailable with user-friendly message, not 500
        assert resp.status_code == 503
        assert "temporarily unavailable" in resp.json()["detail"].lower()


