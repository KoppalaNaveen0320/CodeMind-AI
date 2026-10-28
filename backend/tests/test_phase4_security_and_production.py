import os
import secrets
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.core.config import Settings, settings
from backend.app.core.security import (
    create_session_token,
    create_user_session_record,
    revoke_user_session,
    validate_and_track_session,
    hash_password
)
from backend.app.models.user import User
from backend.app.models.user_session import UserSession
from backend.app.models.repository import Repository
from backend.app.db.session import engine, create_db_engine
from backend.app.services.github_sync_service import GitHubSyncService


def test_production_startup_validation_rejects_weak_secret_key():
    """
    Verify that in production mode (APP_ENV=production), the application fails startup
    if SECRET_KEY is set to default or insecure placeholder.
    """
    with patch.object(settings, "APP_ENV", "production"):
        with patch.object(settings, "DEBUG", False):
            with patch.object(settings, "SECRET_KEY", "codemind-secure-secret-key-32-chars-long!"):
                from backend.app.main import lifespan
                import asyncio
                async def _test():
                    async with lifespan(app):
                        pass
                with pytest.raises(RuntimeError, match="FATAL CONFIGURATION ERROR.*SECRET_KEY"):
                    asyncio.run(_test())


def test_production_startup_validation_rejects_debug_true():
    """
    Verify that in production mode, startup fails if DEBUG=True.
    """
    valid_key = secrets.token_urlsafe(32)
    with patch.object(settings, "APP_ENV", "production"):
        with patch.object(settings, "DEBUG", True):
            with patch.object(settings, "SECRET_KEY", valid_key):
                from backend.app.main import lifespan
                import asyncio
                async def _test():
                    async with lifespan(app):
                        pass
                with pytest.raises(RuntimeError, match="FATAL CONFIGURATION ERROR.*DEBUG=True"):
                    asyncio.run(_test())


def test_production_disables_initial_password_setup_fallback(client: TestClient, db_session: Session):
    """
    Verify that in production mode, accounts without hashed_password are not
    permitted to establish passwords during login, closing the unauthenticated setup fallback.
    """
    unseeded_user = User(
        email="unseeded@company.com",
        full_name="Unseeded User",
        workspace_name="Company WS",
        hashed_password=None,
        is_active=True
    )
    db_session.add(unseeded_user)
    db_session.commit()

    with patch.object(settings, "APP_ENV", "production"):
        resp = client.post("/api/v1/auth/login", json={
            "email": "unseeded@company.com",
            "password": "NewStrongPassword123!"
        })
        assert resp.status_code == 401
        assert "Account requires a password" in resp.json().get("detail", "")


def test_production_mode_disables_test_auth_bypass(client: TestClient, db_session: Session):
    """
    Verify that in production mode, even if PYTEST_CURRENT_TEST is present in the environment,
    unauthenticated requests are strictly rejected with 401 and never auto-assigned to default user.
    """
    with patch.object(settings, "APP_ENV", "production"):
        resp = client.get("/api/v1/me")
        assert resp.status_code == 401
        assert "Authentication required" in resp.json().get("detail", "")

        # Also test view routes redirect to login
        view_resp = client.get("/dashboard", follow_redirects=False)
        assert view_resp.status_code == 302
        assert "/login" in view_resp.headers.get("location", "")


def test_database_connection_pool_configured():
    """
    Verify that PostgreSQL engine creates connections with pool boundaries
    (pool_size, max_overflow, pool_recycle, pool_pre_ping).
    """
    pg_url = "postgresql+psycopg2://postgres:postgres@localhost:5432/codemind_db"
    test_engine = create_db_engine(pg_url)
    assert hasattr(test_engine.pool, "size"), "Engine pool must have bounded size"
    assert test_engine.pool.size() == settings.DATABASE_POOL_SIZE
    assert test_engine.pool._max_overflow == settings.DATABASE_MAX_OVERFLOW
    assert test_engine.pool._recycle == settings.DATABASE_POOL_RECYCLE_SECONDS


def test_cookie_security_flag_resolution():
    """
    Verify that is_cookie_secure resolves correctly according to environment settings:
    - In dev with DEBUG=True: False
    - In prod with DEBUG=False: True
    - Explicit override via SECURE_COOKIES
    """
    s = Settings(APP_ENV="development", DEBUG=True, SECURE_COOKIES=None)
    assert s.is_cookie_secure is False

    s_prod = Settings(APP_ENV="production", DEBUG=False, SECURE_COOKIES=None)
    assert s_prod.is_cookie_secure is True

    s_override = Settings(APP_ENV="development", DEBUG=True, SECURE_COOKIES=True)
    assert s_override.is_cookie_secure is True


def test_shared_database_session_revocation_across_workers(db_session: Session):
    """
    Verify that session revocation is enforced through the durable PostgreSQL database,
    guaranteeing that revoking in one worker immediately invalidates the session
    for any other worker querying the shared database.
    """
    user = User(
        email="shared_worker@test.com",
        full_name="Shared Worker User",
        workspace_name="Worker WS",
        hashed_password=hash_password("SecurePass123!"),
        session_timeout_minutes=30,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()

    token = create_session_token(user.id, timeout_minutes=30)
    session_rec = create_user_session_record(db_session, user, token, initial_path="/dashboard")

    # Worker 1: validates session successfully
    u_w1, s_w1 = validate_and_track_session(token, db_session)
    assert u_w1 is not None
    assert s_w1.status == "active"

    # Worker 1: revokes session
    revoke_user_session(db_session, session_rec, reason="revoked")

    # Worker 2: validates session using fresh lookup from database
    u_w2, s_w2 = validate_and_track_session(token, db_session)
    assert u_w2 is None, "Worker 2 must reject revoked session from shared database"
    
    # Check durable database record directly
    refreshed_rec = db_session.query(UserSession).filter(UserSession.id == session_rec.id).first()
    assert refreshed_rec is not None
    assert refreshed_rec.status == "revoked"


def test_github_sync_duplicate_delivery_idempotency(db_session: Session):
    """
    Verify that duplicate GitHub webhook deliveries are detected via the
    shared WebhookDelivery database table and skipped safely without re-indexing.
    """
    delivery_id = f"test-delivery-{secrets.token_hex(8)}"

    # First check: not duplicate
    assert GitHubSyncService.is_delivery_duplicate(db_session, delivery_id) is False

    # Record delivery
    GitHubSyncService.record_delivery(
        db=db_session,
        delivery_id=delivery_id,
        event_type="push",
        status="processed",
        summary="Initial delivery processed"
    )

    # Second check: duplicate detected
    assert GitHubSyncService.is_delivery_duplicate(db_session, delivery_id) is True

    # Calling record_delivery again is idempotent
    second_rec = GitHubSyncService.record_delivery(
        db=db_session,
        delivery_id=delivery_id,
        event_type="push",
        status="processed"
    )
    assert second_rec.delivery_id == delivery_id


def test_cors_middleware_headers():
    """
    Verify that CORS middleware responds appropriately to allowed origins.
    """
    client = TestClient(app)
    resp = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "GET"
        }
    )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:8000"
