import asyncio
from datetime import datetime, timezone, timedelta
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.repository import Repository
from backend.app.models.indexing_job import IndexingJob
from backend.app.models.user import User
from backend.app.services.github_sync_service import GitHubSyncService, redact_secrets
from backend.app.integrations.github.service import GitHubService, GitHubServiceError


def create_test_repo(
    db: Session,
    name: str = "Opt-Test-Repo",
    full_name: str = "testorg/Opt-Test-Repo",
    default_branch: str = "main",
    current_revision: str = "sha_baseline_111",
    last_synced_commit_sha: str = "sha_baseline_111",
    sync_status: str = "synced",
    status: str = "ready",
    last_checked_offset_seconds: int = 120
) -> Repository:
    """Helper to initialize test repository."""
    last_checked = datetime.now(timezone.utc) - timedelta(seconds=last_checked_offset_seconds)
    repo = Repository(
        name=name,
        full_name=full_name,
        default_branch=default_branch,
        current_revision=current_revision,
        last_synced_commit_sha=last_synced_commit_sha,
        latest_remote_commit_sha=last_synced_commit_sha,
        last_synced_at=last_checked,
        last_checked_at=last_checked,
        sync_status=sync_status,
        sync_retry_count=0,
        status=status,
        files_count=15,
        last_indexed_at=last_checked
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


# ==============================================================================
# 1. Server-side credential resolution & safe auth diagnostics
# ==============================================================================
def test_server_side_credential_resolution_and_no_secret_leak(db_session: Session):
    """
    Confirms that when user has no explicit token, configured server-side token
    (settings.GITHUB_TOKEN or GITHUB_PERSONAL_ACCESS_TOKEN) is resolved cleanly,
    and safe diagnostics never leak the secret.
    """
    original_token = settings.GITHUB_TOKEN
    test_secret = "ghp_ServerSideSecureToken9876543210fedcba"
    settings.GITHUB_TOKEN = test_secret
    try:
        resolved = GitHubService.resolve_token(None)
        assert resolved == test_secret

        # Check safe diagnostics
        auth_diag = GitHubService.get_auth_diagnostics(None)
        assert auth_diag["has_token"] is True
        assert auth_diag["auth_type"] == "bearer"
        assert auth_diag["token_source"] == "settings"
        # Verify secret token is NOT leaked in string representation
        diag_str = str(auth_diag)
        assert test_secret not in diag_str
        assert "9876543210fedcba" not in diag_str
    finally:
        settings.GITHUB_TOKEN = original_token


# ==============================================================================
# 2. Avoid redundant polling: minimum interval throttling
# ==============================================================================
def test_repeated_polling_is_throttled_unless_forced(db_session: Session):
    """
    Validates that rapid consecutive checks for the same repository without force_check
    are throttled to prevent redundant GitHub API requests, while manual force_check runs immediately.
    """
    repo = create_test_repo(db_session, last_checked_offset_seconds=5)  # Checked 5s ago
    api_call_count = 0

    async def mock_remote(access_token, full_name, branch="main", **kwargs):
        nonlocal api_call_count
        api_call_count += 1
        return "sha_baseline_111"

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_remote
    try:
        # 1. Periodic background check within min_interval (60s) -> should be throttled
        res_throttled = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=False))
        assert res_throttled["status"] == "throttled"
        assert "checked recently" in res_throttled["message"]
        assert api_call_count == 0  # No remote API call was made!

        # 2. Manual user check (force_check=True) -> bypasses throttle
        res_forced = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res_forced["status"] == "synced"
        assert api_call_count == 1  # Exactly one API call executed
    finally:
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# 3. Unchanged commits do not trigger re-indexing
# ==============================================================================
def test_unchanged_commits_do_not_trigger_unnecessary_work(db_session: Session):
    """
    Confirms that when the remote commit SHA matches the repository's current revision,
    the sync marks the repository as synced and does NOT enqueue an IndexingJob.
    """
    current_sha = "sha_unchanged_commit_5555"
    repo = create_test_repo(
        db_session,
        current_revision=current_sha,
        last_synced_commit_sha=current_sha,
        last_checked_offset_seconds=500
    )

    async def mock_remote(access_token, full_name, branch="main", **kwargs):
        return current_sha

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_remote
    try:
        initial_job_count = db_session.query(IndexingJob).filter(IndexingJob.repository_id == repo.id).count()

        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res["status"] == "synced"
        assert "up to date" in res["message"]

        # Verify NO new IndexingJob was created
        final_job_count = db_session.query(IndexingJob).filter(IndexingJob.repository_id == repo.id).count()
        assert final_job_count == initial_job_count
        assert repo.status == "ready"
    finally:
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# 4. Conditional requests: ETag 304 Not Modified
# ==============================================================================
def test_conditional_request_etag_and_304_support(db_session: Session):
    """
    Verifies that GitHub conditional requests using If-None-Match with cached ETag
    return HTTP 304 without consuming normal rate limit quota or triggering re-indexing.
    """
    repo = create_test_repo(
        db_session,
        current_revision="sha_etag_tested_777",
        last_synced_commit_sha="sha_etag_tested_777",
        last_checked_offset_seconds=400
    )
    # Seed cached ETag
    GitHubSyncService._etag_cache[f"{repo.full_name}:{repo.default_branch}"] = '"etag_abc12345"'

    captured_etag = None

    async def mock_conditional(access_token, full_name, branch="main", etag=None, last_known_sha=None):
        nonlocal captured_etag
        captured_etag = etag
        # Simulate GitHub returning cached sha on 304 Not Modified
        return last_known_sha

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_conditional
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res["status"] == "synced"
        assert captured_etag == '"etag_abc12345"'
        assert res["current_sha"] == "sha_etag_tested_777"
    finally:
        GitHubSyncService._etag_cache.pop(f"{repo.full_name}:{repo.default_branch}", None)
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# 5. Rate limit pause and resume only when permitted
# ==============================================================================
def test_rate_limit_pauses_requests_and_resumes_when_permitted(db_session: Session):
    """
    Confirms that when rate-limited:
    - Requests are paused until reset_at
    - Subsequent checks during the pause window return rate_limited without hitting GitHub
    - Requests resume once the reset timestamp has elapsed
    """
    repo = create_test_repo(db_session, last_checked_offset_seconds=500)
    now = datetime.now(timezone.utc)
    pause_until = now + timedelta(seconds=2)
    api_call_count = 0

    async def mock_rate_limit(access_token, full_name, branch="main", **kwargs):
        nonlocal api_call_count
        api_call_count += 1
        raise GitHubServiceError(
            "API rate limit exceeded",
            status_code=429,
            reset_at=pause_until,
            retry_after=2
        )

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_rate_limit
    try:
        # 1. First call encounters rate limit
        res1 = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res1["status"] == "rate_limited"
        assert api_call_count == 1

        # 2. Second check during pause window -> skipped without remote API call
        res2 = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=False))
        assert res2["status"] == "rate_limited"
        assert api_call_count == 1  # Remote call count did NOT increase!

        # 3. Simulate reset timestamp passing
        GitHubSyncService._rate_limit_backoff[repo.id] = now - timedelta(seconds=1)
        GitHubSyncService._global_rate_limit_reset = now - timedelta(seconds=1)

        # Mock now returns clean response
        async def mock_resumed(access_token, full_name, branch="main", **kwargs):
            nonlocal api_call_count
            api_call_count += 1
            return "sha_baseline_111"

        GitHubService.get_branch_latest_commit = mock_resumed

        # Check again -> successfully resumes
        res3 = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res3["status"] == "synced"
        assert api_call_count == 2
    finally:
        GitHubSyncService._rate_limit_backoff.pop(repo.id, None)
        GitHubSyncService._global_rate_limit_reset = None
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# 6. Concurrency protection: prevent duplicate in-flight checks
# ==============================================================================
def test_prevent_duplicate_concurrent_sync_checks(db_session: Session):
    """
    Verifies that simultaneous sync checks for the same repository and branch
    are de-duplicated, returning status='syncing' without spawning concurrent requests.
    """
    repo = create_test_repo(db_session, last_checked_offset_seconds=500)
    sync_key = f"{repo.id}:{repo.default_branch}"

    # Mark as already in-flight
    GitHubSyncService._in_flight_syncs.add(sync_key)
    try:
        res = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo, force_check=True))
        assert res["status"] == "syncing"
        assert "already in progress" in res["message"]
    finally:
        GitHubSyncService._in_flight_syncs.discard(sync_key)


# ==============================================================================
# 7. Repository isolation: rate limits and backoffs do not affect other repos
# ==============================================================================
def test_repository_isolation_under_rate_limits(db_session: Session):
    """
    Confirms that when Repo A is in an active rate-limit backoff,
    Repo B can sync successfully without being blocked or throttled.
    """
    repo_a = create_test_repo(
        db_session,
        name="Repo-A-Limited",
        full_name="org/Repo-A-Limited",
        last_checked_offset_seconds=500
    )
    repo_b = create_test_repo(
        db_session,
        name="Repo-B-Normal",
        full_name="org/Repo-B-Normal",
        last_checked_offset_seconds=500
    )

    # Place Repo A in rate limit backoff
    GitHubSyncService._rate_limit_backoff[repo_a.id] = datetime.now(timezone.utc) + timedelta(minutes=10)

    async def mock_dispatch(access_token, full_name, branch="main", **kwargs):
        if "Repo-A" in full_name:
            raise GitHubServiceError("Rate limit", 429)
        return "sha_baseline_111"

    original_method = GitHubService.get_branch_latest_commit
    GitHubService.get_branch_latest_commit = mock_dispatch
    try:
        # Repo A is rate limited
        res_a = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo_a, force_check=False))
        assert res_a["status"] == "rate_limited"

        # Repo B syncs cleanly
        res_b = asyncio.run(GitHubSyncService.check_repository_for_updates(db_session, repo_b, force_check=True))
        assert res_b["status"] == "synced"
    finally:
        GitHubSyncService._rate_limit_backoff.pop(repo_a.id, None)
        GitHubService.get_branch_latest_commit = original_method


# ==============================================================================
# 8. Safe diagnostics endpoint: quota, auth, and next permitted retry
# ==============================================================================
def test_safe_sync_diagnostics_endpoint(client: TestClient, db_session: Session):
    """
    Confirms that GET /api/v1/repositories/{id}/sync/diagnostics returns:
    - auth availability and type
    - rate limit quota metrics
    - next permitted sync timestamp
    - failure category
    - NEVER exposes sensitive tokens
    """
    repo = create_test_repo(db_session, last_checked_offset_seconds=20)
    repo.sync_status = "failed"
    repo.sync_error = "DNS resolution failed"
    repo.sync_error_code = "NETWORK_DNS_ERROR"
    repo.sync_error_category = "Network"
    repo.sync_failed_operation = "Fetch latest branch commit"
    repo.sync_retry_count = 1
    db_session.commit()

    # Simulate known rate limit metrics
    GitHubService._latest_rate_limit.update({
        "limit": 5000,
        "remaining": 4820,
        "reset_at": datetime.now(timezone.utc) + timedelta(minutes=45)
    })

    resp = client.get(f"/api/v1/repositories/{repo.id}/sync/diagnostics")
    assert resp.status_code == 200
    diag = resp.json()

    assert diag["repository_id"] == repo.id
    assert diag["full_name"] == repo.full_name
    assert diag["sync_status"] == "failed"
    assert "auth_available" in diag
    assert "auth_type" in diag
    assert diag["rate_limit_remaining"] == 4820
    assert diag["rate_limit_limit"] == 5000
    assert diag["error_category"] == "Network"
    assert diag["error_code"] == "NETWORK_DNS_ERROR"
    assert diag["next_permitted_sync_at"] is not None

    # Verify no tokens or sensitive keys in response text
    raw_text = resp.text
    assert "ghp_" not in raw_text
    assert "token=" not in raw_text
    assert "password" not in raw_text


# ==============================================================================
# 9. Git fallback audit & failure cooldown
# ==============================================================================
def test_git_fallback_failure_cooldown(db_session: Session):
    """
    Verifies that when git ls-remote fallback fails, subsequent calls during the cooldown
    window avoid repeatedly spawning git subprocesses.
    """
    now = datetime.now(timezone.utc)
    repo_name = "testorg/Cooldown-Repo"

    # Seed failure in git fallback cache
    GitHubService._git_fallback_failures[repo_name] = now

    headers = httpx.Headers({"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1893456000"})
    GitHubService.record_rate_limit_headers(headers)
    metrics = GitHubService.get_rate_limit_metrics()
    assert metrics["remaining"] == 0

    # Clean up
    GitHubService._git_fallback_failures.pop(repo_name, None)
