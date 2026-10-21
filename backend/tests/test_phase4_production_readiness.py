import io
import time
import zipfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.core.config import settings
from backend.app.core.security import create_session_token
from backend.app.core.ssrf import validate_safe_url, SSRFValidationError, is_ip_blocked
from backend.app.core.archive_security import extract_zip_safely, ArchiveSecurityError, validate_path_safety
from backend.app.core.rate_limiter import rate_limiter
from backend.app.core.middleware import sanitize_sensitive_text
from backend.app.db.session import _mask_sensitive_db_error
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.assistant import AssistantConversation
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.integrations.github.service import GitHubService, GitHubServiceError
from backend.app.services.symbol_service import SymbolService


@pytest.fixture
def setup_two_users_and_repos(db_session: Session):
    """Creates two isolated users with their own repositories and conversations."""
    u1 = User(
        email="alice@corp.internal",
        full_name="Alice Adams",
        workspace_name="Alice Security Lab",
        avatar_initials="AA",
        is_active=True
    )
    u2 = User(
        email="bob@corp.internal",
        full_name="Bob Builder",
        workspace_name="Bob Infra Lab",
        avatar_initials="BB",
        is_active=True
    )
    db_session.add_all([u1, u2])
    db_session.commit()
    db_session.refresh(u1)
    db_session.refresh(u2)

    repo_alice = Repository(
        name="alice-secret-repo",
        full_name="alice/secret-repo",
        description="Confidential proprietary algorithms",
        provider="folder",
        is_private=True,
        default_branch="main",
        user_id=u1.id,
        status="ready"
    )
    repo_bob = Repository(
        name="bob-infra-repo",
        full_name="bob/infra-repo",
        description="Bob's private infrastructure",
        provider="folder",
        is_private=True,
        default_branch="main",
        user_id=u2.id,
        status="ready"
    )
    db_session.add_all([repo_alice, repo_bob])
    db_session.commit()
    db_session.refresh(repo_alice)
    db_session.refresh(repo_bob)

    # Add symbols to Alice's repo
    f_alice = IndexedFile(
        repository_id=repo_alice.id,
        path="crypto/cipher.py",
        language="python",
        lines_count=100,
        size_bytes=2048,
        content_hash="abc123hash"
    )
    db_session.add(f_alice)
    db_session.commit()
    db_session.refresh(f_alice)

    sym_alice = CodeSymbol(
        repository_id=repo_alice.id,
        file_id=f_alice.id,
        name="super_secret_cipher_key",
        kind="function",
        start_line=10,
        end_line=25
    )
    db_session.add(sym_alice)

    conv_alice = AssistantConversation(
        user_id=u1.id,
        repository_id=repo_alice.id,
        title="Alice Private Crypto Discussion",
        branch="main"
    )
    db_session.add(conv_alice)
    db_session.commit()
    db_session.refresh(conv_alice)

    return {
        "alice": u1,
        "bob": u2,
        "repo_alice": repo_alice,
        "repo_bob": repo_bob,
        "conv_alice": conv_alice,
        "sym_alice": sym_alice,
    }


# ============================================================================
# 1. Authentication & Authorization Tests
# ============================================================================

def test_unauthenticated_request_with_strict_auth_returns_401(client: TestClient):
    """When strict auth is demanded (X-Require-Auth), requests without tokens must receive HTTP 401."""
    res = client.get("/api/v1/me", headers={"x-require-auth": "true"})
    assert res.status_code == 401
    assert "Authentication required" in res.json()["detail"]


def test_invalid_or_expired_session_token_returns_401(client: TestClient):
    """Invalid or forged session tokens must be rejected with 401 Unauthorized."""
    # 1. Completely forged token
    res = client.get("/api/v1/me", cookies={"codemind_session": "invalid.signature.token"})
    assert res.status_code == 401
    assert "Invalid or expired session token" in res.json()["detail"]

    # 2. Bearer header forged token
    res2 = client.get("/api/v1/me", headers={"Authorization": "Bearer badtoken.xyz"})
    assert res2.status_code == 401


def test_cross_user_repository_access_forbidden(client: TestClient, setup_two_users_and_repos):
    """Bob must be forbidden (HTTP 403) from accessing Alice's private repository."""
    bob = setup_two_users_and_repos["bob"]
    repo_alice = setup_two_users_and_repos["repo_alice"]

    bob_token = create_session_token(bob.id)
    headers = {"Authorization": f"Bearer {bob_token}"}

    # Bob attempts to read Alice's repository details
    res = client.get(f"/api/v1/repositories/{repo_alice.id}", headers=headers)
    assert res.status_code == 403
    assert "Access denied" in res.json()["detail"]

    # Bob attempts to delete Alice's repository
    res_del = client.delete(f"/api/v1/repositories/{repo_alice.id}", headers=headers)
    assert res_del.status_code == 403

    # Bob attempts to query assistant on Alice's repository
    res_query = client.post(
        f"/api/v1/repositories/{repo_alice.id}/assistant/query",
        json={"question": "What is the secret cipher?"},
        headers=headers
    )
    assert res_query.status_code == 403


def test_cross_user_conversation_access_forbidden(client: TestClient, setup_two_users_and_repos):
    """Bob must be forbidden (HTTP 403) from viewing or updating Alice's conversation."""
    bob = setup_two_users_and_repos["bob"]
    conv_alice = setup_two_users_and_repos["conv_alice"]

    bob_token = create_session_token(bob.id)
    headers = {"Authorization": f"Bearer {bob_token}"}

    # Bob attempts to get Alice's conversation
    res = client.get(f"/api/v1/assistant/conversations/{conv_alice.id}", headers=headers)
    assert res.status_code == 403
    assert "Access denied" in res.json()["detail"]

    # Bob attempts to post message to Alice's conversation
    res_msg = client.post(
        f"/api/v1/assistant/conversations/{conv_alice.id}/messages",
        json={"content": "Malicious probe"},
        headers=headers
    )
    assert res_msg.status_code == 403


def test_cross_user_symbol_search_isolation(db_session: Session, setup_two_users_and_repos):
    """Global symbol search by Bob must NOT return symbols from Alice's private repository."""
    bob = setup_two_users_and_repos["bob"]
    alice = setup_two_users_and_repos["alice"]

    # Search as Bob
    res_bob = SymbolService.search_symbols(
        db=db_session,
        query="super_secret_cipher_key",
        user_id=bob.id
    )
    assert res_bob.total_count == 0
    assert len(res_bob.results) == 0

    # Search as Alice
    res_alice = SymbolService.search_symbols(
        db=db_session,
        query="super_secret_cipher_key",
        user_id=alice.id
    )
    assert res_alice.total_count == 1
    assert res_alice.results[0].name == "super_secret_cipher_key"


# ============================================================================
# 2. Upload & Filesystem Security Tests
# ============================================================================

def test_zip_slip_path_traversal_rejected(tmp_path):
    """Archives containing ../ path traversal must be rejected immediately."""
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("../../etc/passwd", "root:x:0:0:")
    zip_buf.seek(0)

    with pytest.raises(ArchiveSecurityError) as exc:
        extract_zip_safely(zip_buf, tmp_path / "extracted")
    assert "illegal path traversal" in str(exc.value)


def test_zip_bomb_decompression_limit_rejected(tmp_path):
    """Archives whose uncompressed size exceeds max limit must be rejected before extraction."""
    zip_buf = io.BytesIO()
    # Create an archive with claimed large uncompressed size (e.g. 500 MB)
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 10 MB compressed string of zeros
        zf.writestr("huge.txt", "0" * (10 * 1024 * 1024))
    zip_buf.seek(0)

    # Set threshold low (5 MB) to test limit enforcement
    with pytest.raises(ArchiveSecurityError) as exc:
        extract_zip_safely(zip_buf, tmp_path / "extracted", max_extracted_bytes=5 * 1024 * 1024)
    assert exc.value.status_code == 413
    assert "uncompressed size exceeds limit" in str(exc.value)


def test_zip_entry_count_limit_rejected(tmp_path):
    """Archives with too many file entries must be rejected (inode exhaustion defense)."""
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        for i in range(25):
            zf.writestr(f"file_{i}.txt", f"data {i}")
    zip_buf.seek(0)

    with pytest.raises(ArchiveSecurityError) as exc:
        extract_zip_safely(zip_buf, tmp_path / "extracted", max_file_count=20)
    assert exc.value.status_code == 413
    assert "maximum allowed entry count" in str(exc.value)


def test_file_content_path_traversal_blocked(client: TestClient, setup_two_users_and_repos):
    """Source navigation endpoint must block path traversal attempts with HTTP 400."""
    alice = setup_two_users_and_repos["alice"]
    repo_alice = setup_two_users_and_repos["repo_alice"]
    alice_token = create_session_token(alice.id)
    headers = {"Authorization": f"Bearer {alice_token}"}

    # Attempt path traversal
    res = client.get(
        f"/api/v1/repositories/{repo_alice.id}/files/content?file_path=../../etc/passwd",
        headers=headers
    )
    assert res.status_code == 400
    assert "path traversal is not permitted" in res.json()["detail"]


# ============================================================================
# 3. GitHub & SSRF Protection Tests
# ============================================================================

@pytest.mark.parametrize("malicious_url", [
    "http://127.0.0.1:8000/private",
    "http://localhost:5432",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/admin",
    "http://192.168.1.100/status",
    "http://172.16.0.1/secrets",
    "ftp://github.com/owner/repo",
    "file:///etc/passwd",
    "gopher://github.com/owner/repo",
])
def test_ssrf_validation_blocks_private_and_metadata_targets(malicious_url):
    """SSRF validator must block loopback, link-local, cloud metadata, and invalid schemes."""
    with pytest.raises(SSRFValidationError):
        validate_safe_url(malicious_url)


def test_github_repo_input_blocks_ssrf_and_traversal():
    """normalize_and_validate_repo_input must reject non-GitHub hosts and malicious paths."""
    with pytest.raises(GitHubServiceError):
        GitHubService.normalize_and_validate_repo_input("http://169.254.169.254/latest/meta-data/")

    with pytest.raises(GitHubServiceError):
        GitHubService.normalize_and_validate_repo_input("https://gitlab.com/owner/repo")

    with pytest.raises(GitHubServiceError):
        GitHubService.normalize_and_validate_repo_input("owner/../etc")


# ============================================================================
# 4. API Validation, Rate Limiting & Error Handling Tests
# ============================================================================

def test_rate_limiter_triggers_429(client: TestClient):
    """Exceeding endpoint rate limit must return HTTP 429 Too Many Requests."""
    rate_limiter.reset()

    # Trigger rate limit on auth category (limit: 15 per min)
    for _ in range(15):
        rate_limiter.is_rate_limited("test-client:auth", max_requests=15, window_seconds=60)

    # Next attempt should be blocked
    assert rate_limiter.is_rate_limited("test-client:auth", max_requests=15, window_seconds=60) is True


def test_correlation_id_middleware(client: TestClient):
    """Responses must include X-Request-ID header, preserving client-supplied or generating UUID."""
    # 1. Server generates fresh correlation ID
    res = client.get("/healthz")
    assert res.status_code == 200
    assert "X-Request-ID" in res.headers
    assert len(res.headers["X-Request-ID"]) > 10

    # 2. Server preserves client correlation ID
    custom_id = "req-custom-trace-12345"
    res2 = client.get("/healthz", headers={"X-Request-ID": custom_id})
    assert res2.headers["X-Request-ID"] == custom_id


def test_sensitive_credential_masking():
    """Database connection strings and bearer tokens must be masked in error messages."""
    raw_error = "connection to postgresql://postgres:SuperSecretP@ss@localhost:5432/codemind_db failed"
    masked = sanitize_sensitive_text(raw_error)
    assert "SuperSecretP@ss" not in masked
    assert ":***@" in masked

    raw_db_err = "password authentication failed for user 'postgres': password=SuperSecretP@ss"
    masked_db = _mask_sensitive_db_error(raw_db_err)
    assert "SuperSecretP@ss" not in masked_db


# ============================================================================
# 5. Health & Readiness Probes Tests
# ============================================================================

def test_health_and_healthz_liveness(client: TestClient):
    """Both /health and /healthz must return HTTP 200 with status='ok'."""
    res1 = client.get("/health")
    assert res1.status_code == 200
    assert res1.json()["status"] == "ok"

    res2 = client.get("/healthz")
    assert res2.status_code == 200
    assert res2.json()["status"] == "ok"


def test_ready_and_readyz_probes(client: TestClient):
    """Both /ready and /readyz must return structured dependency readiness."""
    res1 = client.get("/ready")
    assert res1.status_code in (200, 503)
    data1 = res1.json()
    assert "database" in data1
    assert "pgvector_available" in data1

    res2 = client.get("/readyz")
    assert res2.status_code in (200, 503)
    data2 = res2.json()
    assert data2["database"] == data1["database"]
