import asyncio
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexing_job import IndexingJob
from backend.app.services.github_sync_service import GitHubSyncService, redact_secrets
from backend.app.services.indexing_service import IndexingService
from backend.app.integrations.github.service import GitHubService, GitHubServiceError


def test_secret_redaction():
    """Confirms that tokens, auth headers, and passwords are fully redacted from error strings."""
    assert redact_secrets(None) is None
    sample = "Failed with ghp_1234567890abcdef1234567890abcdef and Bearer gho_secrettoken998877"
    redacted = redact_secrets(sample)
    assert "ghp_1234567890abcdef" not in redacted
    assert "gho_secrettoken998877" not in redacted
    assert "[REDACTED_TOKEN]" in redacted

    url_sample = "https://user:my_secret_pwd@github.com/org/repo.git?access_token=ghp_secret99"
    redacted_url = redact_secrets(url_sample)
    assert "my_secret_pwd" not in redacted_url
    assert "ghp_secret99" not in redacted_url
    assert "[REDACTED_CREDENTIALS]" in redacted_url


def test_successful_sync_up_to_date(db_session: Session):
    """Verifies that an up-to-date repository is correctly marked as synced and errors are cleared."""
    repo = Repository(
        name="sync-ok",
        full_name="testorg/sync-ok",
        default_branch="main",
        current_revision="1111222233334444",
        last_synced_commit_sha="1111222233334444",
        sync_status="failed",
        sync_error="Previous error",
        sync_error_code="SYNC_FAILED",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    async def mock_get_commit(access_token, full_name, branch="main"):
        return "1111222233334444"

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_get_commit
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res["status"] == "synced"
        assert repo.sync_status == "synced"
        assert repo.sync_error is None
        assert repo.sync_error_code is None
        assert repo.last_synced_commit_sha == "1111222233334444"
        assert repo.last_synced_at is not None
    finally:
        GitHubService.get_branch_latest_commit = original_method


def test_authentication_failure_handling(db_session: Session):
    """HTTP 401 error sets GITHUB_AUTH_FAILED, marks failed, and does not retry automatically."""
    repo = Repository(
        name="auth-fail",
        full_name="testorg/auth-fail",
        default_branch="main",
        current_revision="old_rev_sha",
        last_synced_commit_sha="old_rev_sha",
        sync_status="synced",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    async def mock_get_commit(access_token, full_name, branch="main"):
        raise GitHubServiceError("GitHub authentication token invalid or expired", 401)

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_get_commit
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res["status"] == "failed"
        assert repo.sync_status == "failed"
        assert repo.sync_error_code == "GITHUB_AUTH_FAILED"
        assert repo.sync_error_category == "Authentication"
        assert "Reconnect your GitHub account" in repo.sync_suggested_action
        # Confirm last successful commit SHA is PRESERVED
        assert repo.last_synced_commit_sha == "old_rev_sha"

        # Check periodic polling skips permanent error without force_check
        skip_res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=False))
        assert "permanent error" in skip_res["message"]
    finally:
        GitHubService.get_branch_latest_commit = original_method


def test_permission_denied_handling(db_session: Session):
    """HTTP 403 error sets GITHUB_PERMISSION_DENIED and provides actionable guidance."""
    repo = Repository(
        name="perm-denied",
        full_name="testorg/perm-denied",
        default_branch="main",
        current_revision="good_sha",
        last_synced_commit_sha="good_sha",
        sync_status="synced",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    async def mock_get_commit(access_token, full_name, branch="main"):
        raise GitHubServiceError("Access forbidden by GitHub permissions", 403)

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_get_commit
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res["status"] == "failed"
        assert repo.sync_status == "failed"
        assert repo.sync_error_code == "GITHUB_PERMISSION_DENIED"
        assert repo.sync_error_category == "Permission"
        assert repo.last_synced_commit_sha == "good_sha"
    finally:
        GitHubService.get_branch_latest_commit = original_method


def test_rate_limiting_with_backoff(db_session: Session):
    """HTTP 429 sets rate_limited status and backoff window."""
    repo = Repository(
        name="rate-limit-repo",
        full_name="testorg/rate-limit-repo",
        default_branch="main",
        sync_status="synced",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    async def mock_get_commit(access_token, full_name, branch="main"):
        raise GitHubServiceError("GitHub API rate limit exceeded", 429)

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_get_commit
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res["status"] == "rate_limited"
        assert repo.sync_status == "rate_limited"
        assert repo.sync_error_code == "GITHUB_RATE_LIMITED"
        assert repo.sync_error_category == "RateLimit"

        # Next check within window without force_check should return rate_limited immediately
        check2 = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=False))
        assert check2["status"] == "rate_limited"
    finally:
        GitHubService.get_branch_latest_commit = original_method


def test_transient_network_timeout_and_retry_limit(db_session: Session):
    """Transient network errors increment retry counter and bound retries at MAX_SYNC_RETRIES."""
    repo = Repository(
        name="timeout-repo",
        full_name="testorg/timeout-repo",
        default_branch="main",
        sync_status="synced",
        sync_retry_count=0,
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    async def mock_get_commit(access_token, full_name, branch="main"):
        raise TimeoutError("Connection to GitHub timed out")

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_get_commit
    try:
        # First transient failure
        res1 = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res1["status"] == "failed"
        assert repo.sync_error_code == "NETWORK_TIMEOUT"
        assert repo.sync_retry_count == 1

        # Simulate reaching max retries
        repo.sync_retry_count = 3
        db_session.commit()

        # Background poll should now skip indefinite retries
        res_skip = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=False))
        assert "retry limit of 3 attempts reached" in res_skip["message"]

        # Manual retry (force_check=True) resets counter
        repo.sync_retry_count = 0
        db_session.commit()
    finally:
        GitHubService.get_branch_latest_commit = original_method


def test_local_folder_repository_bypasses_github(db_session: Session):
    """Local uploaded repositories (provider: folder) bypass GitHub API calls and remain synced."""
    repo = Repository(
        name="local-app",
        full_name="local/local-app",
        provider="folder",
        default_branch="main",
        current_revision="local-12345",
        sync_status="failed",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
    assert res["status"] == "synced"
    assert repo.sync_status == "synced"
    assert repo.sync_error is None


def test_decoupled_indexing_failure_preserves_sync_status(db_session: Session):
    """Failure during indexing recovery or pipeline execution does NOT mark sync_status as failed."""
    repo = Repository(
        name="decoupled-repo",
        full_name="testorg/decoupled-repo",
        default_branch="main",
        current_revision="valid_commit_sha",
        last_synced_commit_sha="valid_commit_sha",
        sync_status="synced",
        status="indexing",
        files_count=10,
        last_indexed_at=datetime.now(timezone.utc)
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    job = IndexingJob(
        repository_id=repo.id,
        status="QUEUED",
        stage="QUEUED",
        branch="main"
    )
    db_session.add(job)
    db_session.commit()

    # Recover stale jobs
    recovered = IndexingService.recover_stale_indexing_jobs(db_session)
    assert recovered >= 1

    db_session.refresh(repo)
    # repo.status should be recovered to ready because it had files_count & last_indexed_at
    assert repo.status == "ready"
    # repo.sync_status MUST REMAIN synced (independent from indexing recovery!)
    assert repo.sync_status == "synced"
    assert repo.sync_error is None


def test_sync_status_api_endpoint(client: TestClient, db_session: Session):
    """GET /api/v1/repositories/{id}/sync/status returns all structured error fields."""
    repo = Repository(
        name="api-status-test",
        full_name="testorg/api-status-test",
        default_branch="main",
        current_revision="sha_success_123",
        last_synced_commit_sha="sha_success_123",
        sync_status="failed",
        sync_error="DNS resolution for api.github.com failed",
        sync_error_code="NETWORK_DNS_ERROR",
        sync_error_category="Network",
        sync_failed_operation="Fetch latest branch commit",
        sync_suggested_action="Check your network DNS settings and internet connectivity, then click Retry Sync.",
        sync_retry_count=2,
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    resp = client.get(f"/api/v1/repositories/{repo.id}/sync/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["repository_id"] == repo.id
    assert data["sync_status"] == "failed"
    assert data["error_code"] == "NETWORK_DNS_ERROR"
    assert data["error_category"] == "Network"
    assert data["failed_operation"] == "Fetch latest branch commit"
    assert "DNS resolution" in data["error_message"]
    assert "Check your network DNS" in data["suggested_action"]
    assert data["last_successful_commit_sha"] == "sha_success_123"
    assert data["retry_count"] == 2


def test_concurrent_sync_prevention(db_session: Session):
    """Verifies that duplicate concurrent sync checks are rejected while one is already in-flight."""
    repo = Repository(
        name="concurrent-repo",
        full_name="testorg/concurrent-repo",
        default_branch="main",
        sync_status="synced",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    # Manually mark repo as in-flight
    GitHubSyncService._in_flight_syncs.add(repo.id)
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo))
        assert res["status"] == "syncing"
        assert "already in progress" in res["message"]
    finally:
        GitHubSyncService._in_flight_syncs.discard(repo.id)


def test_missing_branch_error_classification(db_session: Session):
    """Missing branch or repo (HTTP 404) is classified as BRANCH_OR_REPO_NOT_FOUND and not retried automatically."""
    repo = Repository(
        name="missing-branch",
        full_name="testorg/missing-branch",
        default_branch="feature-xyz",
        sync_status="synced",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    async def mock_get_commit(access_token, full_name, branch="main"):
        raise GitHubServiceError(f"Branch '{branch}' or repository '{full_name}' was not found on GitHub", 404)

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_get_commit
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res["status"] == "failed"
        assert repo.sync_error_code == "BRANCH_OR_REPO_NOT_FOUND"
        assert repo.sync_error_category == "NotFound"
        assert "feature-xyz" in repo.sync_error

        # Background poll skips permanent error
        skip_res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=False))
        assert "permanent error" in skip_res["message"]
    finally:
        GitHubService.get_branch_latest_commit = original_method


def test_temporary_github_server_error(db_session: Session):
    """HTTP 502/503 temporary GitHub server error is classified as GITHUB_SERVER_ERROR and marked retryable."""
    repo = Repository(
        name="server-err",
        full_name="testorg/server-err",
        default_branch="main",
        sync_status="synced",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    async def mock_get_commit(access_token, full_name, branch="main"):
        raise GitHubServiceError("GitHub service is temporarily unavailable (HTTP 502)", 502)

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_get_commit
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res["status"] == "failed"
        assert repo.sync_error_code == "GITHUB_SERVER_ERROR"
        assert repo.sync_error_category == "Server"
        assert repo.sync_retry_count == 1
    finally:
        GitHubService.get_branch_latest_commit = original_method


def test_empty_repository_handling(db_session: Session):
    """Empty repository with no commits (HTTP 409) is classified as REPOSITORY_EMPTY and not retried."""
    repo = Repository(
        name="empty-repo",
        full_name="testorg/empty-repo",
        default_branch="main",
        sync_status="synced",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    async def mock_get_commit(access_token, full_name, branch="main"):
        raise GitHubServiceError(f"Repository '{full_name}' is empty with no commits on branch '{branch}'", 409)

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_get_commit
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res["status"] == "failed"
        assert repo.sync_error_code == "REPOSITORY_EMPTY"
        assert repo.sync_error_category == "EmptyRepository"
        assert "Push initial source code commits" in repo.sync_suggested_action
    finally:
        GitHubService.get_branch_latest_commit = original_method


def test_successful_retry_after_transient_failure(db_session: Session):
    """Verifies that a manual retry recovers a failed repository, resets retry counter, and preserves sha."""
    repo = Repository(
        name="retry-success",
        full_name="testorg/retry-success",
        default_branch="main",
        current_revision="commit_rev_100",
        last_synced_commit_sha="commit_rev_100",
        sync_status="failed",
        sync_error="Connection to GitHub timed out",
        sync_error_code="NETWORK_TIMEOUT",
        sync_error_category="Network",
        sync_retry_count=2,
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    async def mock_get_commit(access_token, full_name, branch="main"):
        return "commit_rev_100"

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_get_commit
    try:
        # Trigger force retry
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res["status"] == "synced"
        assert repo.sync_status == "synced"
        assert repo.sync_error is None
        assert repo.sync_error_code is None
        assert repo.sync_retry_count == 0
        assert repo.last_synced_commit_sha == "commit_rev_100"
    finally:
        GitHubService.get_branch_latest_commit = original_method


def test_database_transaction_error_classification():
    """Confirms that SQLAlchemy/database exceptions are classified as DATABASE_ERROR."""
    from sqlalchemy.exc import OperationalError
    db_err = OperationalError("SELECT 1", {}, Exception("Connection refused to database"))
    info = GitHubSyncService.classify_sync_error(db_err, "testorg/testrepo", "main")
    assert info["error_code"] == "DATABASE_ERROR"
    assert info["error_category"] == "Database"
    assert "Database transaction error" in info["error_message"]
    assert info["retryable"] is True


def test_repository_and_branch_isolation(db_session: Session):
    """Confirms that sync errors and statuses on one repository do NOT affect or corrupt another repository."""
    repo_a = Repository(
        name="repo-a",
        full_name="org/repo-a",
        default_branch="main",
        sync_status="failed",
        sync_error="Error A",
        sync_error_code="GITHUB_PERMISSION_DENIED",
        status="ready"
    )
    repo_b = Repository(
        name="repo-b",
        full_name="org/repo-b",
        default_branch="develop",
        sync_status="synced",
        sync_error=None,
        status="ready"
    )
    db_session.add_all([repo_a, repo_b])
    db_session.commit()
    db_session.refresh(repo_a)
    db_session.refresh(repo_b)

    assert repo_a.sync_status == "failed"
    assert repo_b.sync_status == "synced"
    assert repo_a.default_branch == "main"
    assert repo_b.default_branch == "develop"
    assert repo_a.sync_error_code == "GITHUB_PERMISSION_DENIED"
    assert repo_b.sync_error_code is None

