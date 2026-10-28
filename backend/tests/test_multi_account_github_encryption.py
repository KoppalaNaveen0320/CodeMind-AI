import os
import base64
import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.token_encryption import (
    TokenEncryptionService,
    TokenEncryptionError,
    generate_key_b64,
)
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.user_github_account import UserGitHubAccount
from backend.app.integrations.github.service import GitHubService, GitHubServiceError
from backend.app.services.github_sync_service import GitHubSyncService, redact_secrets
from backend.app.api.routes.api_v1 import get_current_user_record


# ==============================================================================
# Helper fixtures / setup
# ==============================================================================
@pytest.fixture(autouse=True)
def setup_encryption_key():
    """Ensure a valid 256-bit AES encryption key is set for tests."""
    original_key = settings.GITHUB_TOKEN_ENCRYPTION_KEY
    test_key = generate_key_b64()
    settings.GITHUB_TOKEN_ENCRYPTION_KEY = test_key
    yield test_key
    settings.GITHUB_TOKEN_ENCRYPTION_KEY = original_key


def create_test_user(db: Session, email: str = "alice@example.com") -> User:
    user = User(
        email=email,
        full_name=email.split("@")[0].capitalize(),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_test_repo(
    db: Session,
    name: str = "Test-Repo",
    full_name: str = "org/Test-Repo",
    is_private: bool = False,
    user_id: int = None,
    connected_account_id: int = None,
) -> Repository:
    repo = Repository(
        name=name,
        full_name=full_name,
        default_branch="main",
        current_revision="sha_111",
        last_synced_commit_sha="sha_111",
        is_private=is_private,
        user_id=user_id,
        connected_account_id=connected_account_id,
        sync_status="synced",
        sync_retry_count=0,
        status="ready",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


# ==============================================================================
# 1. AES-256-GCM Encryption & Decryption Round-Trip
# ==============================================================================
def test_aes_256_gcm_encryption_roundtrip():
    key = generate_key_b64()
    raw_token = "ghp_PersonalAccessTokenWithSecretData1234567890"

    res = TokenEncryptionService.encrypt_token(raw_token, key=key)
    encrypted = res["encrypted_token"]
    nonce = res["nonce"]
    tag = res["tag"]

    assert encrypted != raw_token
    assert nonce is not None and len(nonce) > 0
    assert tag is not None and len(tag) > 0

    decrypted = TokenEncryptionService.decrypt_token(encrypted, nonce_b64=nonce, tag_b64=tag, key=key)
    assert decrypted == raw_token


# ==============================================================================
# 2. Tampered Ciphertext, Bad Tag & Invalid Nonce Failure
# ==============================================================================
def test_tampered_ciphertext_detection():
    key = generate_key_b64()
    raw_token = "ghp_TamperCheckToken12345"

    res = TokenEncryptionService.encrypt_token(raw_token, key=key)
    encrypted = res["encrypted_token"]
    nonce = res["nonce"]
    tag = res["tag"]

    # Tamper with encrypted bytes
    raw_enc = base64.b64decode(encrypted)
    tampered_bytes = bytearray(raw_enc)
    tampered_bytes[0] ^= 0xFF
    tampered_encrypted = base64.b64encode(tampered_bytes).decode("utf-8")

    with pytest.raises(TokenEncryptionError, match="Decryption failed"):
        TokenEncryptionService.decrypt_token(tampered_encrypted, nonce_b64=nonce, tag_b64=tag, key=key)

    # Tamper with tag
    raw_tag = base64.b64decode(tag)
    tampered_tag_bytes = bytearray(raw_tag)
    tampered_tag_bytes[0] ^= 0xFF
    tampered_tag = base64.b64encode(tampered_tag_bytes).decode("utf-8")

    with pytest.raises(TokenEncryptionError):
        TokenEncryptionService.decrypt_token(encrypted, nonce_b64=nonce, tag_b64=tampered_tag, key=key)

    # Bad nonce
    bad_nonce = base64.b64encode(b"short").decode("utf-8")
    with pytest.raises(TokenEncryptionError):
        TokenEncryptionService.decrypt_token(encrypted, nonce_b64=bad_nonce, tag_b64=tag, key=key)


# ==============================================================================
# 3. Missing or Invalid Key Error Handling
# ==============================================================================
def test_missing_or_invalid_key_handling():
    with patch.object(settings, "GITHUB_TOKEN_ENCRYPTION_KEY", None):
        with pytest.raises(TokenEncryptionError, match="not configured"):
            TokenEncryptionService.encrypt_token("ghp_test")

    invalid_key = base64.b64encode(b"short_16_byte_ky").decode("utf-8")
    with patch.object(settings, "GITHUB_TOKEN_ENCRYPTION_KEY", invalid_key):
        with pytest.raises(TokenEncryptionError, match="32-byte key"):
            TokenEncryptionService.encrypt_token("ghp_test")


# ==============================================================================
# 4. Key Rotation Helper
# ==============================================================================
def test_key_rotation_helper():
    old_key = generate_key_b64()
    new_key = generate_key_b64()
    raw_token = "ghp_RotateMe123456789"

    res_old = TokenEncryptionService.encrypt_token(raw_token, key=old_key)
    enc_old = res_old["encrypted_token"]
    nonce_old = res_old["nonce"]
    tag_old = res_old["tag"]

    res_new = TokenEncryptionService.rotate_token_encryption(
        enc_old, nonce_b64=nonce_old, tag_b64=tag_old, old_key=old_key, new_key=new_key
    )
    enc_new = res_new["encrypted_token"]
    nonce_new = res_new["nonce"]
    tag_new = res_new["tag"]

    # Verify old key cannot decrypt new ciphertext
    with pytest.raises(TokenEncryptionError):
        TokenEncryptionService.decrypt_token(enc_new, nonce_b64=nonce_new, tag_b64=tag_new, key=old_key)

    # Verify new key decrypts to exact original token
    assert TokenEncryptionService.decrypt_token(enc_new, nonce_b64=nonce_new, tag_b64=tag_new, key=new_key) == raw_token


# ==============================================================================
# 5. Connect Multiple GitHub Accounts (OAuth & PAT) for One User
# ==============================================================================
def test_connect_multiple_accounts_one_user(db_session: Session):
    user = create_test_user(db_session, "multiuser@example.com")

    # Account 1: OAuth Personal
    acc1 = UserGitHubAccount(
        user_id=user.id,
        github_user_id="11111",
        github_username="personal-gh",
        label="Personal",
        auth_method="oauth",
        avatar_url="https://github.com/personal-gh.png",
    )
    acc1.set_encrypted_token("gho_oauth_token_111")
    db_session.add(acc1)

    # Account 2: PAT Work Org
    acc2 = UserGitHubAccount(
        user_id=user.id,
        github_user_id="22222",
        github_username="work-gh",
        label="Work Org",
        auth_method="pat",
        avatar_url="https://github.com/work-gh.png",
        token_scope="repo, workflow",
    )
    acc2.set_encrypted_token("ghp_pat_token_222")
    db_session.add(acc2)
    db_session.commit()

    # Query accounts for user
    accounts = db_session.query(UserGitHubAccount).filter(UserGitHubAccount.user_id == user.id).all()
    assert len(accounts) == 2
    assert {a.github_username for a in accounts} == {"personal-gh", "work-gh"}
    assert {a.auth_method for a in accounts} == {"oauth", "pat"}
    assert accounts[0].get_decrypted_token().startswith("gh")
    assert accounts[1].get_decrypted_token().startswith("gh")


# ==============================================================================
# 6. PAT Validation & Server-Side Encryption Endpoint
# ==============================================================================
def test_pat_validation_and_encryption_endpoint(client: TestClient, db_session: Session):
    user = create_test_user(db_session, "patuser@example.com")

    from backend.app.main import app
    app.dependency_overrides[get_current_user_record] = lambda: user

    try:
        mock_github_user = {
            "github_user_id": "99999",
            "github_username": "octocat-contractor",
            "login": "octocat-contractor",
            "account_type": "User",
            "avatar_url": "https://avatars.githubusercontent.com/u/99999",
            "scopes": "repo, read:org",
            "token_type": "bearer",
        }

        with patch("backend.app.integrations.github.service.GitHubService.validate_personal_access_token", new_callable=AsyncMock) as mock_val:
            mock_val.return_value = mock_github_user
            resp = client.post(
                "/api/v1/auth/github/pat",
                json={
                    "token": "ghp_LiveContractorToken99999",
                    "label": "Client Organization",
                },
            )

            assert resp.status_code in (200, 201)
            data = resp.json()
            assert data["github_username"] == "octocat-contractor"
            assert data["label"] == "Client Organization"
            assert data["auth_method"] == "pat"
            # Ensure plaintext token is NOT returned in response
            assert "ghp_" not in str(data)

            # Check database persistence
            account = db_session.query(UserGitHubAccount).filter(UserGitHubAccount.id == data["id"]).first()
            assert account is not None
            assert account.encrypted_token != "ghp_LiveContractorToken99999"
            assert account.get_decrypted_token() == "ghp_LiveContractorToken99999"
    finally:
        app.dependency_overrides.pop(get_current_user_record, None)


# ==============================================================================
# 7. Public Repository Import / Cloning Without Credentials
# ==============================================================================
def test_public_repo_unauthenticated_resolution(db_session: Session):
    user = create_test_user(db_session, "public_user@example.com")
    public_repo = create_test_repo(
        db_session,
        name="open-source-tool",
        full_name="community/open-source-tool",
        is_private=False,
        user_id=user.id,
        connected_account_id=None,
    )

    # For public repo with no server fallback, resolved token must be None
    resolved_token = GitHubService.resolve_token_for_repository(
        public_repo, db=db_session, user=user, allow_server_fallback=False
    )
    assert resolved_token is None

    # Clone URL should be public HTTPS without any token embedded
    clone_url = GitHubService.build_authenticated_clone_url(public_repo.full_name, resolved_token)
    assert clone_url == "https://github.com/community/open-source-tool.git"


# ==============================================================================
# 8. Authorized Private Repository Cloning & Sync with Account Credential
# ==============================================================================
def test_private_repo_uses_connected_account_token(db_session: Session):
    user = create_test_user(db_session, "privuser@example.com")
    account = UserGitHubAccount(
        user_id=user.id,
        github_user_id="33333",
        github_username="org-member",
        label="Work Account",
        auth_method="pat",
    )
    account.set_encrypted_token("ghp_SecretPrivToken777")
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    private_repo = create_test_repo(
        db_session,
        name="secret-internal-service",
        full_name="company/secret-internal-service",
        is_private=True,
        user_id=user.id,
        connected_account_id=account.id,
    )

    resolved = GitHubService.resolve_token_for_repository(
        private_repo, db=db_session, user=user, allow_server_fallback=False
    )
    assert resolved == "ghp_SecretPrivToken777"

    # Clone URL contains embedded credentials
    clone_url = GitHubService.build_authenticated_clone_url(private_repo.full_name, resolved)
    assert "ghp_SecretPrivToken777@github.com/company/secret-internal-service.git" in clone_url


# ==============================================================================
# 9. Unauthorized Private Repository Rejection
# ==============================================================================
def test_unauthorized_private_repo_rejected(db_session: Session):
    user = create_test_user(db_session, "noauth@example.com")
    private_repo = create_test_repo(
        db_session,
        name="private-without-account",
        full_name="company/private-without-account",
        is_private=True,
        user_id=user.id,
        connected_account_id=None,
    )

    # Private repo without connected account and allow_server_fallback=False cannot resolve a credential
    resolved = GitHubService.resolve_token_for_repository(
        private_repo, db=db_session, user=user, allow_server_fallback=False
    )
    assert resolved is None


# ==============================================================================
# 10. Strict User & Organization Credential Isolation
# ==============================================================================
def test_user_credential_isolation(client: TestClient, db_session: Session):
    user_a = create_test_user(db_session, "user_a@example.com")
    user_b = create_test_user(db_session, "user_b@example.com")

    # Account owned by User A
    acc_a = UserGitHubAccount(
        user_id=user_a.id,
        github_user_id="10101",
        github_username="account-a",
        label="User A Work",
        auth_method="pat",
    )
    acc_a.set_encrypted_token("ghp_UserATokenSecret")
    db_session.add(acc_a)
    db_session.commit()
    db_session.refresh(acc_a)

    from backend.app.main import app
    # Simulate requests as User B
    app.dependency_overrides[get_current_user_record] = lambda: user_b

    try:
        # User B lists accounts: should NOT see User A's account
        resp = client.get("/api/v1/auth/github/accounts")
        assert resp.status_code == 200
        accounts = resp.json()["accounts"]
        assert len(accounts) == 0

        # User B attempts to delete User A's account
        del_resp = client.delete(f"/api/v1/auth/github/accounts/{acc_a.id}")
        assert del_resp.status_code == 404

        # User B attempts to list repositories using User A's account
        repo_resp = client.get(f"/api/v1/auth/github/accounts/{acc_a.id}/repositories")
        assert repo_resp.status_code == 404

        # User B cannot use User A's connected account when resolving tokens
        private_repo_b = create_test_repo(
            db_session,
            name="repo-b",
            full_name="org/repo-b",
            is_private=True,
            user_id=user_b.id,
            connected_account_id=acc_a.id,  # Illicitly pointing to User A's account
        )
        resolved_token = GitHubService.resolve_token_for_repository(
            private_repo_b, db=db_session, user=user_b, allow_server_fallback=False
        )
        assert resolved_token is None, "Cross-user token leak prevented!"

    finally:
        app.dependency_overrides.pop(get_current_user_record, None)


# ==============================================================================
# 11. Credential Selection During Background Synchronization
# ==============================================================================
def test_background_sync_credential_selection(db_session: Session):
    user = create_test_user(db_session, "syncuser@example.com")
    acc = UserGitHubAccount(
        user_id=user.id,
        github_user_id="44444",
        github_username="sync-dev",
        label="Sync PAT",
        auth_method="pat",
    )
    acc.set_encrypted_token("ghp_SyncDevToken444")
    db_session.add(acc)
    db_session.commit()
    db_session.refresh(acc)

    repo = create_test_repo(
        db_session,
        name="sync-repo",
        full_name="org/sync-repo",
        is_private=True,
        user_id=user.id,
        connected_account_id=acc.id,
    )

    with patch("backend.app.integrations.github.service.GitHubService.get_branch_latest_commit", new_callable=AsyncMock) as mock_commit:
        mock_commit.return_value = "sha_new_222"
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(repo, db_session, force_check=True))

        assert res["status"] in ("syncing", "updated", "synced")
        mock_commit.assert_called_once()
        args, kwargs = mock_commit.call_args
        assert kwargs.get("access_token") == "ghp_SyncDevToken444" or (args and args[0] == "ghp_SyncDevToken444")


# ==============================================================================
# 12. Expired & Revoked Authorization Handling
# ==============================================================================
def test_expired_or_revoked_credential_sync_handling(db_session: Session):
    user = create_test_user(db_session, "revoked@example.com")
    acc = UserGitHubAccount(
        user_id=user.id,
        github_user_id="55555",
        github_username="revoked-dev",
        label="Revoked Acc",
        auth_method="pat",
    )
    acc.set_encrypted_token("ghp_ExpiredTokenBad555")
    db_session.add(acc)
    db_session.commit()
    db_session.refresh(acc)

    repo = create_test_repo(
        db_session,
        name="revoked-repo",
        full_name="org/revoked-repo",
        is_private=True,
        user_id=user.id,
        connected_account_id=acc.id,
    )

    # Mock 401 Unauthorized from GitHub
    with patch(
        "backend.app.integrations.github.service.GitHubService.get_branch_latest_commit",
        new_callable=AsyncMock,
        side_effect=GitHubServiceError("Bad credentials (401)", status_code=401),
    ):
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(repo, db_session, force_check=True))
        assert res["status"] in ("failed", "error")
        assert repo.sync_status in ("failed", "error")
        assert "401" in (repo.sync_error or "") or "Bad credentials" in (repo.sync_error or "") or repo.sync_error_code == "GITHUB_AUTH_FAILED"

        # Sync diagnostics should guide user to re-authenticate
        diag = GitHubSyncService.get_sync_diagnostics(db_session, repo)
        assert diag["auth_available"] is True
        assert diag["token_source"] == "connected_account"
        assert "re-connect" in diag["suggested_action"].lower() or "expired" in diag["suggested_action"].lower() or "auth" in diag["suggested_action"].lower() or "token" in diag["suggested_action"].lower()


# ==============================================================================
# 13. Disconnecting One Account Without Affecting Other Accounts or Repositories
# ==============================================================================
def test_disconnect_account_preserves_repositories(client: TestClient, db_session: Session):
    user = create_test_user(db_session, "disconnect_test@example.com")

    # Account 1
    acc1 = UserGitHubAccount(
        user_id=user.id,
        github_user_id="66661",
        github_username="acc-to-delete",
        label="Delete Me",
        auth_method="pat",
    )
    acc1.set_encrypted_token("ghp_DeleteToken1")
    db_session.add(acc1)

    # Account 2
    acc2 = UserGitHubAccount(
        user_id=user.id,
        github_user_id="66662",
        github_username="acc-to-keep",
        label="Keep Me",
        auth_method="pat",
    )
    acc2.set_encrypted_token("ghp_KeepToken2")
    db_session.add(acc2)
    db_session.commit()
    db_session.refresh(acc1)
    db_session.refresh(acc2)

    # Repository linked to Account 1
    repo = create_test_repo(
        db_session,
        name="linked-repo",
        full_name="org/linked-repo",
        is_private=True,
        user_id=user.id,
        connected_account_id=acc1.id,
    )

    from backend.app.main import app
    app.dependency_overrides[get_current_user_record] = lambda: user

    try:
        # Delete Account 1
        resp = client.delete(f"/api/v1/auth/github/accounts/{acc1.id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"

        # Account 1 is removed from DB
        assert db_session.query(UserGitHubAccount).filter(UserGitHubAccount.id == acc1.id).first() is None
        # Account 2 is preserved
        assert db_session.query(UserGitHubAccount).filter(UserGitHubAccount.id == acc2.id).first() is not None

        # Repository still exists, but connected_account_id is SET NULL
        db_session.refresh(repo)
        assert repo is not None
        assert repo.connected_account_id is None

    finally:
        app.dependency_overrides.pop(get_current_user_record, None)


# ==============================================================================
# 14. Token Redaction in API Responses, Logs & Diagnostics
# ==============================================================================
def test_token_redaction_and_safe_output():
    raw = "Error cloning with https://ghp_SuperSecretPAT123456789@github.com/myorg/myrepo.git"
    redacted = redact_secrets(raw)
    assert "ghp_SuperSecretPAT123456789" not in redacted
    assert "[REDACTED" in redacted

    oauth_raw = "Bearer gho_OAuthSecretTokenValue999"
    redacted_oauth = redact_secrets(oauth_raw)
    assert "gho_OAuthSecretTokenValue999" not in redacted_oauth


# ==============================================================================
# 15. Repository Listing for Specific Connected Account
# ==============================================================================
def test_list_repositories_for_specific_account(client: TestClient, db_session: Session):
    user = create_test_user(db_session, "list_repos_user@example.com")
    acc = UserGitHubAccount(
        user_id=user.id,
        github_user_id="77777",
        github_username="repo-owner",
        label="Owner Acc",
        auth_method="pat",
    )
    acc.set_encrypted_token("ghp_RepoOwnerToken777")
    db_session.add(acc)
    db_session.commit()
    db_session.refresh(acc)

    from backend.app.main import app
    app.dependency_overrides[get_current_user_record] = lambda: user

    mock_repos = [
        {
            "id": 1001,
            "name": "private-project",
            "full_name": "repo-owner/private-project",
            "private": True,
            "default_branch": "main",
            "language": "Python",
            "html_url": "https://github.com/repo-owner/private-project",
        }
    ]

    try:
        with patch("backend.app.integrations.github.service.GitHubService.list_authorized_repositories", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = mock_repos
            resp = client.get(f"/api/v1/auth/github/accounts/{acc.id}/repositories")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["full_name"] == "repo-owner/private-project"
            assert data[0]["is_private"] is True
            assert data[0]["connected_account_id"] == acc.id

    finally:
        app.dependency_overrides.pop(get_current_user_record, None)


# ==============================================================================
# 16. Backward Compatibility with Existing Repository Connections
# ==============================================================================
def test_backward_compatibility_existing_connections(db_session: Session):
    # Existing repository created prior to multi-account migration
    repo = create_test_repo(
        db_session,
        name="legacy-repo",
        full_name="legacy/legacy-repo",
        is_private=False,
        user_id=None,
        connected_account_id=None,
    )

    # Should resolve using server-fallback when enabled
    with patch.object(settings, "GITHUB_TOKEN", "ghp_GlobalServerToken"):
        resolved = GitHubService.resolve_token_for_repository(
            repo, db=db_session, user=None, allow_server_fallback=True
        )
        assert resolved == "ghp_GlobalServerToken"

    # Diagnostics should indicate server_fallback
    with patch.object(settings, "GITHUB_TOKEN", "ghp_GlobalServerToken"):
        diag = GitHubSyncService.get_sync_diagnostics(db_session, repo)
        assert diag["token_source"] in ("settings", "server_fallback", "environment", "user")
        assert diag["auth_available"] is True
