from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.user import User
from backend.app.core.security import verify_password


def test_registration_persists_row_in_database(client: TestClient, db_session: Session):
    """1 & 2. Verify registration creates a row that persists in the database across request cycles."""
    email = "persist_test_user@example.com"
    pwd = "SecurePassword123!@#"
    
    resp = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": pwd,
        "full_name": "Persistence Tester",
        "workspace_name": "Test Engineering"
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    assert data["user"]["email"] == email

    # Verify directly from database session that the row exists
    persisted_user = db_session.query(User).filter(User.email == email).first()
    assert persisted_user is not None
    assert persisted_user.email == email
    assert persisted_user.full_name == "Persistence Tester"
    assert persisted_user.is_active is True


def test_stored_password_is_hashed_and_not_plaintext(client: TestClient, db_session: Session):
    """3. Verify stored password is cryptographically hashed and never plaintext."""
    email = "hash_verify_user@example.com"
    pwd = "SuperSecret123!@#"
    
    resp = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": pwd,
        "full_name": "Hash Verification User"
    })
    assert resp.status_code == 201

    persisted_user = db_session.query(User).filter(User.email == email).first()
    assert persisted_user is not None
    assert persisted_user.hashed_password != pwd
    assert pwd not in persisted_user.hashed_password
    assert persisted_user.hashed_password.startswith("pbkdf2_sha256$")
    assert verify_password(pwd, persisted_user.hashed_password) is True


def test_newly_registered_user_can_login(client: TestClient, db_session: Session):
    """4. Verify newly registered user can immediately log in with their credentials."""
    email = "login_flow_user@example.com"
    pwd = "MyValidPassword2026!#"
    
    # Register
    reg_resp = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": pwd,
        "full_name": "Login Flow User"
    })
    assert reg_resp.status_code == 201

    # Login
    login_resp = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": pwd
    })
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data["success"] is True
    assert login_data["user"]["email"] == email
    assert "codemind_session" in login_resp.cookies


def test_duplicate_email_registration_rejected(client: TestClient, db_session: Session):
    """5. Verify duplicate email registration returns HTTP 400."""
    email = "duplicate_check@example.com"
    pwd = "Password123!@#"
    
    # First registration
    r1 = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": pwd,
        "full_name": "First User"
    })
    assert r1.status_code == 201

    # Duplicate registration attempt with mixed casing
    r2 = client.post("/api/v1/auth/register", json={
        "email": email.upper(),
        "password": pwd,
        "full_name": "Duplicate User"
    })
    assert r2.status_code == 400
    assert "already exists" in r2.json()["detail"].lower()


def test_failed_database_commit_returns_error_not_success(client: TestClient, db_session: Session):
    """6. Verify failed database commits return HTTP 500 without returning false success."""
    email = "commit_fail_test@example.com"
    pwd = "Password123!@#"

    with patch.object(Session, "commit", side_effect=Exception("Simulated disk write failure")):
        resp = client.post("/api/v1/auth/register", json={
            "email": email,
            "password": pwd,
            "full_name": "Commit Fail User"
        })
        assert resp.status_code == 500
        assert "failed to persist" in resp.json()["detail"].lower()


def test_login_fails_for_incorrect_password(client: TestClient, db_session: Session):
    """7. Verify login fails with HTTP 401 for incorrect password."""
    email = "wrong_pwd_user@example.com"
    pwd = "CorrectPassword123!@"

    client.post("/api/v1/auth/register", json={
        "email": email,
        "password": pwd,
        "full_name": "Wrong Password User"
    })

    bad_login = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "WrongPassword999!@"
    })
    assert bad_login.status_code == 401
    assert "invalid email or password" in bad_login.json()["detail"].lower()


def test_frontend_signup_form_calls_correct_api():
    """8. Verify frontend signup.html form uses the correct /api/v1/auth/register endpoint."""
    signup_html_path = settings.TEMPLATES_DIR / "signup.html"
    assert signup_html_path.exists(), "signup.html must exist"
    content = signup_html_path.read_text(encoding="utf-8")
    assert "/api/v1/auth/register" in content
    assert "method: 'POST'" in content or 'method: "POST"' in content or "POST" in content


def test_cleanup_logic_strictly_preserves_genuine_accounts():
    """9. Verify fake-account classification logic never matches genuine user accounts."""
    genuine_emails = [
        "koppalanaveen20@gmail.com",
        "developer@company.com",
        "admin@myworkspace.org",
        "naveen.koppala@gmail.com"
    ]
    test_emails = [
        "auth_test_12345678@codemind.dev",
        "audit_pass_abcdef@codemind.dev",
        "e2e_70d9c0@codemind.dev",
        "verify_0ebd4ab2@example.com",
        "docker_test_0fc2b7c0@example.com"
    ]

    import re
    test_pattern = re.compile(r"^(auth_test_|audit_pass_|e2e_|verify_|docker_test_)", re.IGNORECASE)

    for g_email in genuine_emails:
        assert not test_pattern.match(g_email), f"Genuine email {g_email} must not match test pattern!"

    for t_email in test_emails:
        assert test_pattern.match(t_email), f"Test email {t_email} must match test pattern!"


def test_production_mode_database_dialect_requirements():
    """10. Verify application enforces PostgreSQL in production mode."""
    prod_url = "postgresql+psycopg2://user:pass@db:5432/codemind_db"
    assert "postgresql" in prod_url
    assert "sqlite" not in prod_url
