import asyncio
from datetime import datetime, timezone, timedelta
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, OperationalError

from backend.app.models.repository import Repository
from backend.app.models.indexing_job import IndexingJob
from backend.app.services.github_sync_service import GitHubSyncService, redact_secrets
from backend.app.integrations.github.service import GitHubService, GitHubServiceError


def create_sync_test_repo(
    db: Session,
    name: str = "CodeMind-Sync-Test",
    full_name: str = "testorg/CodeMind-Sync-Test",
    default_branch: str = "main",
    current_revision: str = "init_commit_sha_12345678",
    last_synced_commit_sha: str = "init_commit_sha_12345678",
    sync_status: str = "synced",
    status: str = "ready",
    files_count: int = 42,
    last_indexed_at: datetime = None
) -> Repository:
    """Helper to initialize the dedicated test repository with baseline sync and indexing metadata."""
    if last_indexed_at is None:
        last_indexed_at = datetime.now(timezone.utc) - timedelta(hours=2)

    repo = Repository(
        name=name,
        full_name=full_name,
        default_branch=default_branch,
        current_revision=current_revision,
        last_synced_commit_sha=last_synced_commit_sha,
        latest_remote_commit_sha=last_synced_commit_sha,
        last_synced_at=datetime.now(timezone.utc) - timedelta(hours=2),
        last_checked_at=datetime.now(timezone.utc) - timedelta(hours=2),
        sync_status=sync_status,
        sync_retry_count=0,
        status=status,
        files_count=files_count,
        symbols_count=180,
        apis_count=24,
        dependencies_count=15,
        last_indexed_at=last_indexed_at
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


# ==============================================================================
# Scenario 1: Invalid Credentials / HTTP 401
# ==============================================================================
def test_scenario_1_invalid_credentials_http_401(db_session: Session, client: TestClient):
    """
    Scenario 1:
    When GitHub returns HTTP 401 Unauthorized:
    - Status transitions to 'failed'
    - Error code is 'GITHUB_AUTH_FAILED', Category is 'Authentication'
    - Failed operation is 'Fetch latest branch commit'
    - Non-retryable: retry counter is not incremented and periodic poll skips it
    - Indexing status ('status', 'files_count', 'last_indexed_at') remains independent and intact
    - Last successful sync metadata is strictly preserved
    """
    repo = create_sync_test_repo(db_session)
    original_last_sha = repo.last_synced_commit_sha
    original_last_synced_at = repo.last_synced_at
    original_indexed_at = repo.last_indexed_at

    async def mock_auth_error(access_token, full_name, branch="main"):
        raise GitHubServiceError("Bad credentials: token expired or invalid", 401)

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_auth_error
    try:
        # Trigger sync check
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))

        # Assert status and structured classification
        assert res["status"] == "failed"
        assert res["error_code"] == "GITHUB_AUTH_FAILED"
        assert res["error_category"] == "Authentication"
        assert res["failed_operation"] == "Fetch latest branch commit"
        assert "Reconnect your GitHub account" in res["suggested_action"]

        db_session.refresh(repo)
        assert repo.sync_status == "failed"
        assert repo.sync_error_code == "GITHUB_AUTH_FAILED"
        assert repo.sync_error_category == "Authentication"
        assert repo.sync_failed_operation == "Fetch latest branch commit"

        # Retry behavior: Non-retryable error does not increment retry count
        assert repo.sync_retry_count == 0
        skip_res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=False))
        assert "permanent error requires manual resolution" in skip_res["message"]

        # Preservation of last successful sync metadata
        assert repo.last_synced_commit_sha == original_last_sha
        assert repo.last_synced_at == original_last_synced_at

        # Indexing status remains completely independent
        assert repo.status == "ready"
        assert repo.files_count == 42
        assert repo.last_indexed_at == original_indexed_at

        # Assert verified API response
        api_res = client.get(f"/api/v1/repositories/{repo.id}/sync/status")
        assert api_res.status_code == 200
        payload = api_res.json()
        assert payload["sync_status"] == "failed"
        assert payload["error_code"] == "GITHUB_AUTH_FAILED"
        assert payload["error_category"] == "Authentication"
        assert payload["failed_operation"] == "Fetch latest branch commit"
        assert payload["last_successful_commit_sha"] == original_last_sha
    finally:
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# Scenario 2: Permission Denied / HTTP 403
# ==============================================================================
def test_scenario_2_permission_denied_http_403(db_session: Session, client: TestClient):
    """
    Scenario 2:
    When GitHub returns HTTP 403 Forbidden without rate limit headers:
    - Status transitions to 'failed'
    - Error code is 'GITHUB_PERMISSION_DENIED', Category is 'Permission'
    - Failed operation is 'Fetch latest branch commit'
    - Non-retryable: background polling skips repeated checks
    - Suggested action provides clear access/permission guidance
    - Indexing status remains independent
    """
    repo = create_sync_test_repo(db_session)

    async def mock_permission_error(access_token, full_name, branch="main"):
        raise GitHubServiceError("Resource not accessible by personal access token", 403)

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_permission_error
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))

        assert res["status"] == "failed"
        assert res["error_code"] == "GITHUB_PERMISSION_DENIED"
        assert res["error_category"] == "Permission"
        assert res["failed_operation"] == "Fetch latest branch commit"
        assert "Verify repository access and required token read permissions" in res["suggested_action"]

        db_session.refresh(repo)
        assert repo.sync_status == "failed"
        assert repo.sync_error_code == "GITHUB_PERMISSION_DENIED"
        assert repo.sync_retry_count == 0

        # Periodic check skips permanent error
        skip_res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=False))
        assert "permanent error" in skip_res["message"]

        # Indexing status remains independent
        assert repo.status == "ready"
        assert repo.files_count == 42
    finally:
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# Scenario 3: Missing Branch
# ==============================================================================
def test_scenario_3_missing_branch(db_session: Session):
    """
    Scenario 3:
    When GitHub returns HTTP 404 for a branch or commit query:
    - Status transitions to 'failed'
    - Error code is 'BRANCH_OR_REPO_NOT_FOUND', Category is 'NotFound'
    - Error message explicitly names the missing branch
    - Non-retryable: retry count remains 0 and periodic polling skips
    - Indexing status remains independent
    """
    repo = create_sync_test_repo(db_session, default_branch="release-candidate-v9")

    async def mock_not_found(access_token, full_name, branch="main"):
        raise GitHubServiceError(f"Branch '{branch}' or repository '{full_name}' was not found on GitHub", 404)

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_not_found
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))

        assert res["status"] == "failed"
        assert res["error_code"] == "BRANCH_OR_REPO_NOT_FOUND"
        assert res["error_category"] == "NotFound"
        assert "release-candidate-v9" in res["error"]
        assert "valid on GitHub" in res["suggested_action"]

        db_session.refresh(repo)
        assert repo.sync_status == "failed"
        assert repo.sync_error_code == "BRANCH_OR_REPO_NOT_FOUND"
        assert repo.sync_retry_count == 0

        # Indexing status remains independent
        assert repo.status == "ready"
    finally:
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# Scenario 4: GitHub API Rate Limit with Reset Headers
# ==============================================================================
def test_scenario_4_rate_limit_with_reset_headers(db_session: Session, client: TestClient):
    """
    Scenario 4:
    When GitHub returns HTTP 429 or 403 Rate Limit with reset headers:
    - Status transitions to 'rate_limited'
    - Error code is 'GITHUB_RATE_LIMITED', Category is 'RateLimit'
    - Retry behavior: marked retryable (sync_retry_count incremented)
    - Rate limit backoff window is recorded from reset headers
    - Subsequent periodic checks within the window return 'rate_limited' without hitting remote API
    - Indexing status remains independent
    """
    repo = create_sync_test_repo(db_session)
    future_reset = datetime.now(timezone.utc) + timedelta(minutes=25)

    async def mock_rate_limit(access_token, full_name, branch="main"):
        raise GitHubServiceError(
            "GitHub API rate limit exceeded for testorg/CodeMind-Sync-Test",
            status_code=429,
            reset_at=future_reset,
            retry_after=1500
        )

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_rate_limit
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))

        assert res["status"] == "rate_limited"
        assert res["error_code"] == "GITHUB_RATE_LIMITED"
        assert res["error_category"] == "RateLimit"
        assert res["retry_count"] == 1
        assert res.get("reset_at") == future_reset

        db_session.refresh(repo)
        assert repo.sync_status == "rate_limited"
        assert repo.sync_error_code == "GITHUB_RATE_LIMITED"
        assert repo.sync_retry_count == 1
        assert repo.status == "ready"  # Indexing status independent

        # Backoff map in GitHubSyncService holds exact reset timestamp
        assert repo.id in GitHubSyncService._rate_limit_backoff
        assert GitHubSyncService._rate_limit_backoff[repo.id] == future_reset

        # Background polling without force_check respects backoff immediately
        poll_res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=False))
        assert poll_res["status"] == "rate_limited"
        assert "rate limit backoff active" in poll_res["message"]

        # API status endpoint returns rate_limited and reset_at
        status_res = client.get(f"/api/v1/repositories/{repo.id}/sync/status")
        assert status_res.status_code == 200
        payload = status_res.json()
        assert payload["sync_status"] == "rate_limited"
        assert payload["error_code"] == "GITHUB_RATE_LIMITED"
        assert payload["reset_at"] is not None
    finally:
        GitHubSyncService._rate_limit_backoff.pop(repo.id, None)
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# Scenario 5: Network Timeout
# ==============================================================================
def test_scenario_5_network_timeout(db_session: Session):
    """
    Scenario 5:
    When connection to GitHub times out (TimeoutError / httpx.TimeoutException):
    - Status transitions to 'failed'
    - Error code is 'NETWORK_TIMEOUT', Category is 'Network'
    - Retry behavior: marked retryable (sync_retry_count incremented)
    - Suggested action advises checking network and retrying
    - Indexing status remains independent
    """
    repo = create_sync_test_repo(db_session)

    async def mock_timeout(access_token, full_name, branch="main"):
        raise httpx.TimeoutException("ReadTimeout connecting to api.github.com:443")

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_timeout
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))

        assert res["status"] == "failed"
        assert res["error_code"] == "NETWORK_TIMEOUT"
        assert res["error_category"] == "Network"
        assert res["retry_count"] == 1
        assert "timed out" in res["error"].lower()
        assert "Retry Sync" in res["suggested_action"]

        db_session.refresh(repo)
        assert repo.sync_status == "failed"
        assert repo.sync_error_code == "NETWORK_TIMEOUT"
        assert repo.sync_retry_count == 1
        assert repo.status == "ready"
    finally:
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# Scenario 6: Temporary GitHub Server Error / HTTP 500
# ==============================================================================
def test_scenario_6_temporary_github_server_error_500(db_session: Session):
    """
    Scenario 6:
    When GitHub returns temporary server errors (HTTP 500, 502, 503):
    - Status transitions to 'failed'
    - Error code is 'GITHUB_SERVER_ERROR', Category is 'Server'
    - Retry behavior: retryable with retry counter incremented
    - Indexing status remains independent
    """
    repo = create_sync_test_repo(db_session)

    async def mock_server_error(access_token, full_name, branch="main"):
        raise GitHubServiceError("GitHub API is temporarily unavailable (HTTP 500)", 500)

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_server_error
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))

        assert res["status"] == "failed"
        assert res["error_code"] == "GITHUB_SERVER_ERROR"
        assert res["error_category"] == "Server"
        assert res["retry_count"] == 1
        assert "temporarily experiencing issues" in res["suggested_action"]

        db_session.refresh(repo)
        assert repo.sync_status == "failed"
        assert repo.sync_error_code == "GITHUB_SERVER_ERROR"
        assert repo.sync_retry_count == 1
        assert repo.status == "ready"
    finally:
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# Scenario 7: Database Write Failure
# ==============================================================================
def test_scenario_7_database_write_failure(db_session: Session):
    """
    Scenario 7:
    When a controlled database write failure occurs during synchronization:
    - Application catches exception gracefully without unhandled crashes
    - Error code is 'DATABASE_ERROR', Category is 'Database'
    - Retry behavior: retryable
    - Transaction is safely rolled back so session is not corrupted
    """
    repo = create_sync_test_repo(db_session)

    # 1. Classify standalone database operational error
    op_err = OperationalError("INSERT INTO repositories", {}, Exception("database disk image is locked"))
    diag = GitHubSyncService.classify_sync_error(op_err, repo.full_name, repo.default_branch)
    assert diag["error_code"] == "DATABASE_ERROR"
    assert diag["error_category"] == "Database"
    assert diag["retryable"] is True
    assert diag["failed_operation"] == "Fetch latest branch commit"

    # 2. Simulate database failure during remote update query
    async def mock_db_failure(access_token, full_name, branch="main"):
        raise OperationalError("SELECT 1", {}, Exception("Connection refused to database backend"))

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_db_failure
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res["status"] == "failed"
        assert res["error_code"] == "DATABASE_ERROR"
        assert res["error_category"] == "Database"
        assert "Database transaction error" in res["error"]
        assert res["retry_count"] == 1

        db_session.refresh(repo)
        assert repo.sync_status == "failed"
        assert repo.sync_error_code == "DATABASE_ERROR"
        assert repo.sync_error_category == "Database"
        assert repo.status == "ready"  # Indexing status remains independent
    finally:
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# Scenario 8: Bounded Retry Exhaustion
# ==============================================================================
def test_scenario_8_bounded_retry_exhaustion(db_session: Session):
    """
    Scenario 8:
    When transient errors repeatedly occur:
    - Retry counter increments on transient failure
    - When bounded limit of MAX_SYNC_RETRIES (3) is reached, periodic background poll halts
    - Returns bounded retry limit message requiring manual recovery
    - Repository preserves error diagnosis and last successful commit
    """
    repo = create_sync_test_repo(db_session)

    async def mock_flaky_timeout(access_token, full_name, branch="main"):
        raise TimeoutError("Connection to GitHub timed out")

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_flaky_timeout
    try:
        # First transient error increments retry count
        res1 = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res1["status"] == "failed"
        assert res1["retry_count"] == 1

        # Simulate reaching max retries (3)
        repo.sync_retry_count = GitHubSyncService.MAX_SYNC_RETRIES
        db_session.commit()

        # Automated periodic check now halts polling due to bounded exhaustion
        skip_res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=False))
        assert skip_res["status"] == "failed"
        assert f"retry limit of {GitHubSyncService.MAX_SYNC_RETRIES} attempts reached" in skip_res["message"]

        db_session.refresh(repo)
        assert repo.sync_retry_count == 3
        assert repo.sync_status == "failed"
        assert repo.last_synced_commit_sha == "init_commit_sha_12345678"
        assert repo.status == "ready"
    finally:
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# Scenario 9: Successful Retry and Recovery
# ==============================================================================
def test_scenario_9_successful_retry_and_recovery(db_session: Session, client: TestClient):
    """
    Scenario 9:
    When manual retry is triggered on an exhausted failed repository:
    - Status transitions from 'failed' to 'synced' (when up to date)
    - All error fields are reset to None
    - Retry counter is reset to 0
    - Last synced commit SHA and timestamp are preserved
    - Rate limit backoff is cleared
    - Indexing status remains independent ('status' == 'ready')
    """
    current_sha = "commit_sha_known_good_123"
    repo = create_sync_test_repo(
        db_session,
        current_revision=current_sha,
        last_synced_commit_sha=current_sha,
        sync_status="failed"
    )
    repo.sync_error = "Previous connection timeout"
    repo.sync_error_code = "NETWORK_TIMEOUT"
    repo.sync_error_category = "Network"
    repo.sync_failed_operation = "Fetch latest branch commit"
    repo.sync_suggested_action = "Click Retry Sync"
    repo.sync_retry_count = 3
    db_session.commit()
    db_session.refresh(repo)

    # Remote confirms current commit is up to date
    async def mock_success(access_token, full_name, branch="main"):
        return current_sha

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_success
    try:
        # Trigger manual retry via API endpoint POST /api/v1/repositories/{id}/sync
        retry_res = client.post(f"/api/v1/repositories/{repo.id}/sync")
        assert retry_res.status_code == 200
        data = retry_res.json()
        assert data["sync_status"] == "synced"
        assert data["retry_count"] == 0
        assert data["error_code"] is None
        assert data["error_message"] is None

        db_session.refresh(repo)
        assert repo.sync_status == "synced"
        assert repo.sync_error is None
        assert repo.sync_error_code is None
        assert repo.sync_error_category is None
        assert repo.sync_failed_operation is None
        assert repo.sync_suggested_action is None
        assert repo.sync_retry_count == 0
        assert repo.last_synced_commit_sha == current_sha

        # Indexing status remains independent
        assert repo.status == "ready"
        assert repo.files_count == 42
    finally:
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# Scenario 10: Error Details Persistence Across Refresh
# ==============================================================================
def test_scenario_10_error_details_persistence_across_refresh(db_session: Session, client: TestClient):
    """
    Scenario 10:
    Verifies that when a sync error occurs:
    - All structured diagnostic fields are persisted in the database
    - A page refresh / new query / GET sync status retains the exact fields
    - GET /api/v1/repositories includes the sync failure attributes
    """
    repo = create_sync_test_repo(db_session)

    async def mock_timeout(access_token, full_name, branch="main"):
        raise httpx.TimeoutException("Persistent connection timeout")

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_timeout
    try:
        asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))

        # Evict local cache and simulate fresh database query
        db_session.expire_all()
        refreshed = db_session.query(Repository).filter(Repository.id == repo.id).first()

        assert refreshed.sync_status == "failed"
        assert refreshed.sync_error_code == "NETWORK_TIMEOUT"
        assert refreshed.sync_error_category == "Network"
        assert refreshed.sync_failed_operation == "Fetch latest branch commit"
        assert "Persistent connection timeout" in refreshed.sync_error
        assert refreshed.sync_retry_count == 1
        assert refreshed.sync_last_attempt_at is not None

        # Verify API query returns identical persistent fields
        status_res = client.get(f"/api/v1/repositories/{repo.id}/sync/status")
        assert status_res.status_code == 200
        s_data = status_res.json()
        assert s_data["sync_status"] == "failed"
        assert s_data["error_code"] == "NETWORK_TIMEOUT"
        assert s_data["error_category"] == "Network"
        assert s_data["failed_operation"] == "Fetch latest branch commit"
        assert s_data["retry_count"] == 1

        # Verify repository table endpoint reflects sync failure
        list_res = client.get("/api/v1/repositories")
        assert list_res.status_code == 200
        repos_list = list_res.json()
        matched = next((r for r in repos_list if r["id"] == repo.id), None)
        assert matched is not None
        assert matched["sync_status"] == "failed"
        assert matched["sync_error_code"] == "NETWORK_TIMEOUT"
    finally:
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# Scenario 11: Correct Repository and Branch Isolation
# ==============================================================================
def test_scenario_11_repository_and_branch_isolation(db_session: Session):
    """
    Scenario 11:
    Verifies that failures on one repository or branch never bleed into another:
    - Repo A fails with permission denied on main
    - Repo B succeeds on branch develop
    - Repo A's failure details and retry count belong strictly to Repo A
    - Repo B remains clean and synced
    - In-flight sets and backoff maps are isolated by repository ID
    """
    branch_b_sha = "commit_sha_develop_branch_ok"
    repo_a = create_sync_test_repo(
        db_session,
        name="CodeMind-Sync-Test",
        full_name="testorg/CodeMind-Sync-Test",
        default_branch="main"
    )
    repo_b = create_sync_test_repo(
        db_session,
        name="Other-Isolated-Repo",
        full_name="testorg/Other-Isolated-Repo",
        default_branch="develop",
        current_revision=branch_b_sha,
        last_synced_commit_sha=branch_b_sha
    )

    async def mock_selective_dispatch(access_token, full_name, branch="main"):
        if "CodeMind-Sync-Test" in full_name:
            raise GitHubServiceError("Access forbidden by GitHub permissions", 403)
        return branch_b_sha

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_selective_dispatch
    try:
        res_a = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo_a, force_check=True))
        res_b = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo_b, force_check=True))

        assert res_a["status"] == "failed"
        assert res_a["error_code"] == "GITHUB_PERMISSION_DENIED"

        assert res_b["status"] == "synced"
        assert res_b.get("error_code") is None

        db_session.refresh(repo_a)
        db_session.refresh(repo_b)

        # Assert strict isolation
        assert repo_a.sync_status == "failed"
        assert repo_a.sync_error_code == "GITHUB_PERMISSION_DENIED"
        assert repo_a.default_branch == "main"

        assert repo_b.sync_status == "synced"
        assert repo_b.sync_error_code is None
        assert repo_b.sync_error is None
        assert repo_b.sync_retry_count == 0
        assert repo_b.default_branch == "develop"
    finally:
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# Scenario 12: Clickable Sync Failed Modal, Retry Sync and Copy Error Details
# ==============================================================================
def test_scenario_12_clickable_sync_failed_modal_retry_and_copy(client: TestClient, db_session: Session):
    """
    Scenario 12:
    Validates complete frontend diagnostics modal integration:
    - Accessible modal markup present in templates (#sync-error-details-modal)
    - Badge trigger button rendered for failed and rate_limited states
    - Retry Sync and Copy Error Details buttons with expected IDs and handlers
    - copySyncErrorDetails JavaScript handler exists and structures error details
    - retrySyncFromModal JavaScript handler triggers /api/v1/repositories/{id}/sync
    """
    repo = create_sync_test_repo(
        db_session,
        sync_status="failed"
    )
    repo.sync_error = "GitHub API rate limit exceeded while querying testorg/CodeMind-Sync-Test"
    repo.sync_error_code = "GITHUB_RATE_LIMITED"
    repo.sync_error_category = "RateLimit"
    repo.sync_failed_operation = "Fetch latest branch commit"
    repo.sync_suggested_action = "Wait for rate limit window to reset"
    repo.sync_retry_count = 1
    db_session.commit()

    # 1. Verify HTML template markup
    res_html = client.get("/repositories", follow_redirects=True)
    assert res_html.status_code == 200
    html = res_html.text
    assert 'id="sync-error-details-modal"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'id="sync-error-modal-title"' in html
    assert 'id="sync-error-modal-subtitle"' in html
    assert 'id="sync-error-modal-body"' in html
    assert 'id="btn-copy-sync-error"' in html
    assert 'onclick="copySyncErrorDetails()"' in html
    assert 'id="btn-retry-sync"' in html
    assert 'onclick="retrySyncFromModal()"' in html

    # 2. Verify JavaScript modal logic in api.js
    res_js = client.get("/static/js/api.js")
    assert res_js.status_code == 200
    js = res_js.text
    # Badge rendering with openSyncErrorModal
    assert "openSyncErrorModal" in js
    assert "sync-badge-btn" in js
    assert "Sync failed" in js
    # Retry function calling triggerSync
    assert "retrySyncFromModal" in js
    assert "CodeMindAPI.triggerSync" in js
    # Copy error details function
    assert "copySyncErrorDetails" in js
    assert "last_successful_commit_sha" in js
    assert "last_successful_sync_at" in js
    assert "Error details copied to clipboard!" in js

    # 3. Verify sync status endpoint used by openSyncErrorModal returns expected modal payload
    status_res = client.get(f"/api/v1/repositories/{repo.id}/sync/status")
    assert status_res.status_code == 200
    diag_data = status_res.json()
    assert diag_data["repository_id"] == repo.id
    assert diag_data["sync_status"] == "failed"
    assert diag_data["error_code"] == "GITHUB_RATE_LIMITED"
    assert diag_data["error_category"] == "RateLimit"
    assert diag_data["failed_operation"] == "Fetch latest branch commit"
    assert diag_data["retry_count"] == 1


# ==============================================================================
# Scenario 13: Secret Redaction & Preservation of Last Successful Sync Metadata
# ==============================================================================
def test_scenario_13_secret_redaction_and_metadata_preservation(db_session: Session):
    """
    Scenario 13:
    Validates that:
    - Classic GitHub PATs, fine-grained PATs, Bearer tokens, URL credentials,
      and URL parameters are all fully redacted from error messages
    - Last successful commit SHA and sync timestamp are preserved upon failure
    - Indexing status remains completely independent
    """
    repo = create_sync_test_repo(
        db_session,
        current_revision="good_sha_previous_999",
        last_synced_commit_sha="good_sha_previous_999"
    )
    last_good_sha = repo.last_synced_commit_sha
    last_good_time = repo.last_synced_at

    raw_sensitive_message = (
        "Failed fetching commits with token ghp_secretpattoken1234567890abcdef and "
        "github_pat_11AAAAAA00000000000000_1234567890abcdef1234567890 and "
        "Bearer eyJhbGciOiJIUzI1NiJ9.secretpayload.xyz on "
        "https://admin_user:super_secret_pw@github.com/testorg/CodeMind-Sync-Test.git?access_token=ghp_querytoken123"
    )

    # 1. Verify redact_secrets utility
    redacted = redact_secrets(raw_sensitive_message)
    assert "ghp_secretpattoken1234567890abcdef" not in redacted
    assert "github_pat_11AAAAAA00000000000000_1234567890abcdef1234567890" not in redacted
    assert "super_secret_pw" not in redacted
    assert "ghp_querytoken123" not in redacted
    assert "[REDACTED_TOKEN]" in redacted
    assert "[REDACTED_CREDENTIALS]" in redacted
    assert "[REDACTED]" in redacted

    # 2. Verify error classification redacts secrets
    classified = GitHubSyncService.classify_sync_error(
        Exception(raw_sensitive_message),
        repo.full_name,
        repo.default_branch
    )
    assert "ghp_secretpattoken1234567890abcdef" not in classified["error_message"]
    assert "super_secret_pw" not in classified["error_message"]
    assert "[REDACTED" in classified["error_message"]

    # 3. Verify sync failure preserves last successful sync metadata
    async def mock_sensitive_failure(access_token, full_name, branch="main"):
        raise Exception(raw_sensitive_message)

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_sensitive_failure
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert "ghp_secretpattoken1234567890abcdef" not in res["error"]
        assert "super_secret_pw" not in res["error"]

        db_session.refresh(repo)
        assert repo.last_synced_commit_sha == last_good_sha
        assert repo.last_synced_at == last_good_time
        assert repo.status == "ready"
        assert repo.files_count == 42
    finally:
        GitHubService.get_branch_latest_commit = original_method
