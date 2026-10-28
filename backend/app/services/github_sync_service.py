import asyncio
import hashlib
import hmac
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.session import SessionLocal
from backend.app.models.repository import Repository
from backend.app.models.user import User
from backend.app.models.webhook_delivery import WebhookDelivery
from backend.app.models.indexing_job import IndexingJob
from backend.app.services.indexing_service import (
    IndexingService,
    IGNORED_DIRECTORIES,
    IGNORED_EXTENSIONS,
    IGNORED_FILE_NAMES,
)
from backend.app.integrations.github.service import GitHubService, GitHubServiceError

logger = logging.getLogger(__name__)


def redact_secrets(text: Optional[str]) -> Optional[str]:
    """Redacts tokens, credentials, and passwords from strings and logs."""
    if not text:
        return text
    # Redact GitHub personal access tokens (classic ghp/gho/ghu/ghs/ghr and fine-grained github_pat)
    text = re.sub(r"(?:gh[pousr]_[A-Za-z0-9_]{16,255}|github_pat_[A-Za-z0-9_]{16,255})", "[REDACTED_TOKEN]", text)
    # Redact Bearer tokens
    text = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [REDACTED_TOKEN]", text, flags=re.IGNORECASE)
    # Redact basic auth in URLs: https://user:pass@github.com
    text = re.sub(r"https?://([^:]+):([^@]+)@", "https://[REDACTED_CREDENTIALS]@", text)
    # Redact authorization query params
    text = re.sub(r"([?&](?:access_token|token|secret|password)=)[^&]+", r"\1[REDACTED]", text, flags=re.IGNORECASE)
    return text


class GitHubSyncService:
    MAX_SYNC_RETRIES: int = 3
    _scheduler_started: bool = False
    _scheduler_task: Optional[asyncio.Task] = None
    _rate_limit_backoff: Dict[int, datetime] = {}  # repo_id -> backoff_until
    _in_flight_syncs: Set[Any] = set()  # set of (repo_id, branch), f"{repo_id}:{branch}", or repo_id
    _etag_cache: Dict[str, str] = {}  # f"{full_name}:{branch}" -> etag
    _sync_semaphore: Optional[asyncio.Semaphore] = None
    _global_rate_limit_reset: Optional[datetime] = None

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        max_concurrent = max(1, getattr(settings, "GITHUB_SYNC_MAX_CONCURRENT_REQUESTS", 3))
        if cls._sync_semaphore is None:
            cls._sync_semaphore = asyncio.Semaphore(max_concurrent)
        return cls._sync_semaphore

    @staticmethod
    def verify_webhook_signature(
        raw_payload: bytes,
        signature_header: Optional[str],
        secret: Optional[str] = None
    ) -> bool:
        """
        Verifies GitHub HMAC-SHA256 signature from 'X-Hub-Signature-256'.
        Prevents timing attacks using constant-time hmac.compare_digest.
        """
        if not signature_header:
            return False

        effective_secret = (secret or settings.GITHUB_WEBHOOK_SECRET).strip()
        if not effective_secret:
            logger.warning("GitHub webhook secret is not configured in settings.")
            return False

        # GitHub format: sha256=HEX_DIGEST
        if not signature_header.startswith("sha256="):
            return False

        expected_sig = signature_header[7:].strip().lower()
        computed_sig = hmac.new(
            effective_secret.encode("utf-8"),
            raw_payload,
            hashlib.sha256
        ).hexdigest().lower()

        return hmac.compare_digest(expected_sig, computed_sig)

    @classmethod
    def is_delivery_duplicate(cls, db: Session, delivery_id: str) -> bool:
        """Checks if a delivery ID has already been recorded and processed."""
        if not delivery_id:
            return False
        return db.query(WebhookDelivery).filter(WebhookDelivery.delivery_id == delivery_id).first() is not None

    @classmethod
    def record_delivery(
        cls,
        db: Session,
        delivery_id: str,
        event_type: str,
        repository_id: Optional[int] = None,
        payload_sha256: Optional[str] = None,
        status: str = "processed",
        summary: Optional[str] = None
    ) -> WebhookDelivery:
        """Persists webhook delivery record to guarantee at-most-once idempotency."""
        existing = db.query(WebhookDelivery).filter(WebhookDelivery.delivery_id == delivery_id).first()
        if existing:
            return existing

        delivery = WebhookDelivery(
            delivery_id=delivery_id,
            event_type=event_type,
            repository_id=repository_id,
            payload_sha256=payload_sha256,
            status=status,
            summary=summary[:1000] if summary else None
        )
        db.add(delivery)
        db.commit()
        db.refresh(delivery)
        return delivery

    @classmethod
    def match_authorized_repository(cls, db: Session, payload: dict) -> Optional[Repository]:
        """
        Matches incoming webhook payload repository to an existing authorized repository.
        Never trusts unverified external repository identifiers without a matching DB record.
        """
        repo_payload = payload.get("repository", {})
        github_repo_id = repo_payload.get("id")
        full_name = repo_payload.get("full_name")
        clone_url = repo_payload.get("clone_url")

        # 1. Match by numeric github_repo_id
        if github_repo_id:
            matched = db.query(Repository).filter(Repository.github_repo_id == github_repo_id).first()
            if matched:
                return matched

        # 2. Match by full_name (e.g. owner/repo)
        if full_name:
            matched = db.query(Repository).filter(Repository.full_name == full_name.strip()).first()
            if matched:
                return matched

        # 3. Match by normalized clone_url
        if clone_url:
            matched = db.query(Repository).filter(Repository.clone_url == clone_url.strip()).first()
            if matched:
                return matched

        return None

    @classmethod
    def filter_meaningful_changed_files(cls, commits: List[dict]) -> Tuple[Set[str], Set[str], Set[str]]:
        """
        Inspects commit file lists and excludes non-source, ignored, or binary paths.
        Returns: (added_files, modified_files, removed_files)
        """
        added: Set[str] = set()
        modified: Set[str] = set()
        removed: Set[str] = set()

        for c in commits:
            for f in c.get("added", []):
                added.add(f.replace("\\", "/").strip().lstrip("/"))
            for f in c.get("modified", []):
                modified.add(f.replace("\\", "/").strip().lstrip("/"))
            for f in c.get("removed", []):
                removed.add(f.replace("\\", "/").strip().lstrip("/"))

        def is_source_path(p: str) -> bool:
            parts = p.split("/")
            if any(part in IGNORED_DIRECTORIES for part in parts[:-1]):
                return False
            name = parts[-1].lower()
            if name in IGNORED_FILE_NAMES:
                return False
            ext = "." + name.split(".")[-1] if "." in name else ""
            if ext in IGNORED_EXTENSIONS:
                return False
            return True

        clean_added = {f for f in added if is_source_path(f)}
        clean_modified = {f for f in modified if is_source_path(f)}
        clean_removed = {f for f in removed if is_source_path(f)}

        return clean_added, clean_modified, clean_removed

    @classmethod
    async def handle_push_webhook(
        cls,
        payload: dict,
        delivery_id: str,
        payload_bytes: bytes,
        db: Session
    ) -> Dict:
        """
        Processes push event webhook:
        - Deduplicates delivery ID
        - Authorizes and resolves existing repository
        - Validates branch ref and detects deletions
        - Checks commit SHA differences
        - Enqueues incremental re-indexing job asynchronously
        """
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()

        # 1. Deduplication check
        if cls.is_delivery_duplicate(db, delivery_id):
            logger.info(f"Webhook delivery {delivery_id} already processed. Skipping duplicate.")
            return {
                "status": "duplicate",
                "message": "Delivery already processed",
                "delivery_id": delivery_id
            }

        # 2. Authorize repository match
        repo = cls.match_authorized_repository(db, payload)
        if not repo:
            logger.warning(f"Webhook push event for repository not tracked in CodeMind AI. Ignoring delivery {delivery_id}.")
            cls.record_delivery(db, delivery_id, "push", None, payload_hash, "ignored", "Untracked repository")
            return {
                "status": "ignored",
                "message": "Repository is not connected or tracked in this CodeMind AI instance"
            }

        # 3. Check for deleted branch
        if payload.get("deleted", False):
            logger.info(f"Push event indicates branch deletion for {repo.full_name}. Preserving user index data.")
            cls.record_delivery(db, delivery_id, "push", repo.id, payload_hash, "ignored", "Branch deletion ignored")
            return {
                "status": "ignored",
                "message": "Branch deletion ignored; index preserved safely"
            }

        # 4. Check branch match (only sync repository's configured default/active branch)
        ref = payload.get("ref", "")
        configured_branch = repo.default_branch or "main"
        expected_ref = f"refs/heads/{configured_branch}"
        if ref and ref != expected_ref and ref.replace("refs/heads/", "") != configured_branch:
            logger.info(f"Push to branch '{ref}' does not match repository configured branch '{configured_branch}'. Ignoring.")
            cls.record_delivery(db, delivery_id, "push", repo.id, payload_hash, "ignored", f"Non-monitored branch {ref}")
            return {
                "status": "ignored",
                "message": f"Push was to non-monitored branch '{ref}'"
            }

        # 5. Check target commit SHA
        head_commit_sha = (payload.get("after") or payload.get("head_commit", {}).get("id") or "").strip()
        if not head_commit_sha or head_commit_sha == "0000000000000000000000000000000000000000":
            cls.record_delivery(db, delivery_id, "push", repo.id, payload_hash, "ignored", "Empty or zero commit SHA")
            return {
                "status": "ignored",
                "message": "Invalid or empty commit SHA"
            }

        # 6. Check if already at latest revision
        if head_commit_sha == repo.current_revision or head_commit_sha == repo.last_synced_commit_sha:
            repo.last_checked_at = datetime.now(timezone.utc)
            repo.sync_last_attempt_at = datetime.now(timezone.utc)
            repo.sync_status = "synced"
            repo.sync_error = None
            repo.sync_error_code = None
            repo.sync_error_category = None
            repo.sync_failed_operation = None
            repo.sync_suggested_action = None
            repo.sync_retry_count = 0
            db.commit()
            cls.record_delivery(db, delivery_id, "push", repo.id, payload_hash, "processed", f"Already synced at {head_commit_sha[:8]}")
            return {
                "status": "synced",
                "message": f"Repository is already up to date at commit {head_commit_sha[:8]}",
                "commit_sha": head_commit_sha
            }

        # 7. Check changed files
        commits = payload.get("commits", [])
        clean_added, clean_modified, clean_removed = cls.filter_meaningful_changed_files(commits)

        if not clean_added and not clean_modified and not clean_removed and commits:
            # Commit only touched ignored/excluded files
            logger.info(f"Push to {repo.full_name} affected only excluded non-source files. Updating revision without re-indexing.")
            repo.current_revision = head_commit_sha
            repo.last_synced_commit_sha = head_commit_sha
            repo.latest_remote_commit_sha = head_commit_sha
            repo.last_checked_at = datetime.now(timezone.utc)
            repo.sync_last_attempt_at = datetime.now(timezone.utc)
            repo.last_synced_at = datetime.now(timezone.utc)
            repo.sync_status = "synced"
            repo.sync_error = None
            repo.sync_error_code = None
            repo.sync_error_category = None
            repo.sync_failed_operation = None
            repo.sync_suggested_action = None
            repo.sync_retry_count = 0
            db.commit()
            cls.record_delivery(db, delivery_id, "push", repo.id, payload_hash, "processed", f"Excluded-only files updated revision to {head_commit_sha[:8]}")
            return {
                "status": "synced",
                "message": f"Commits only modified excluded files. Updated revision to {head_commit_sha[:8]}",
                "commit_sha": head_commit_sha
            }

        # 8. Check for active indexing job to avoid duplicate concurrent runs
        active_job = db.query(IndexingJob).filter(
            IndexingJob.repository_id == repo.id,
            IndexingJob.status.in_(["QUEUED", "CLONING", "PARSING", "INDEXING"])
        ).first()

        if active_job:
            repo.latest_remote_commit_sha = head_commit_sha
            repo.sync_status = "syncing"
            repo.last_checked_at = datetime.now(timezone.utc)
            repo.sync_last_attempt_at = datetime.now(timezone.utc)
            db.commit()
            cls.record_delivery(db, delivery_id, "push", repo.id, payload_hash, "processed", f"Active job {active_job.id} already running")
            return {
                "status": "syncing",
                "message": f"An indexing job (ID: {active_job.id}) is already active for this repository",
                "job_id": active_job.id,
                "commit_sha": head_commit_sha
            }

        # 9. Enqueue incremental indexing job
        job = IndexingService.create_indexing_job(db, repo, branch=configured_branch)
        job.commit_sha = head_commit_sha
        repo.latest_remote_commit_sha = head_commit_sha
        repo.sync_status = "syncing"
        repo.sync_error = None
        repo.sync_error_code = None
        repo.sync_error_category = None
        repo.sync_failed_operation = None
        repo.sync_suggested_action = None
        repo.sync_retry_count = 0
        repo.last_checked_at = datetime.now(timezone.utc)
        repo.sync_last_attempt_at = datetime.now(timezone.utc)
        db.commit()

        cls.record_delivery(db, delivery_id, "push", repo.id, payload_hash, "processed", f"Enqueued job {job.id} for commit {head_commit_sha[:8]}")

        # Trigger background pipeline execution asynchronously
        asyncio.create_task(cls._execute_indexing_job_background(job.id, repo.id, configured_branch))

        return {
            "status": "syncing",
            "message": f"New commit {head_commit_sha[:8]} detected. Incremental indexing enqueued.",
            "job_id": job.id,
            "target_commit_sha": head_commit_sha,
            "changed_files_count": len(clean_added) + len(clean_modified) + len(clean_removed)
        }

    @classmethod
    def classify_sync_error(
        cls,
        err: Exception,
        full_name: str,
        branch: str,
        operation: str = "Fetch latest branch commit"
    ) -> Dict[str, Any]:
        """
        Classifies exceptions into structured error codes, categories, human reasons, and actionable fixes.
        Guarantees that no tokens, credentials, or secrets are exposed in logs or user-facing strings.
        """
        raw_msg = redact_secrets(str(err)) or "Unknown synchronization error"
        lower_msg = raw_msg.lower()

        # 1. Handle GitHubServiceError with explicit HTTP status codes
        if isinstance(err, GitHubServiceError):
            status = getattr(err, "status_code", 500)
            err_reset_at = getattr(err, "reset_at", None)
            err_retry_after = getattr(err, "retry_after", None)
            if status == 401:
                return {
                    "error_code": "GITHUB_AUTH_FAILED",
                    "error_category": "Authentication",
                    "error_message": f"GitHub authentication token invalid or expired for {full_name}.",
                    "failed_operation": operation,
                    "suggested_action": "Reconnect your GitHub account or update your personal access token in Settings.",
                    "retryable": False,
                    "is_rate_limit": False
                }
            elif status == 403:
                if "rate limit" in raw_msg.lower():
                    return {
                        "error_code": "GITHUB_RATE_LIMITED",
                        "error_category": "RateLimit",
                        "error_message": f"GitHub API rate limit exceeded while querying {full_name}.",
                        "failed_operation": operation,
                        "suggested_action": "Wait for the GitHub rate limit window to reset or configure an authenticated GitHub token in Settings.",
                        "retryable": True,
                        "is_rate_limit": True,
                        "reset_at": err_reset_at,
                        "retry_after": err_retry_after
                    }
                return {
                    "error_code": "GITHUB_PERMISSION_DENIED",
                    "error_category": "Permission",
                    "error_message": f"Access forbidden by GitHub permissions for repository '{full_name}'.",
                    "failed_operation": operation,
                    "suggested_action": "Verify repository access and required token read permissions on GitHub.",
                    "retryable": False,
                    "is_rate_limit": False
                }
            elif status == 404:
                return {
                    "error_code": "BRANCH_OR_REPO_NOT_FOUND",
                    "error_category": "NotFound",
                    "error_message": f"Branch '{branch}' or repository '{full_name}' was not found on GitHub.",
                    "failed_operation": operation,
                    "suggested_action": f"Verify that repository '{full_name}' exists and branch '{branch}' is valid on GitHub.",
                    "retryable": False,
                    "is_rate_limit": False
                }
            elif status == 409:
                return {
                    "error_code": "REPOSITORY_EMPTY",
                    "error_category": "EmptyRepository",
                    "error_message": f"Repository '{full_name}' is empty with no commits on branch '{branch}'.",
                    "failed_operation": operation,
                    "suggested_action": "Push initial source code commits to this repository branch on GitHub.",
                    "retryable": False,
                    "is_rate_limit": False
                }
            elif status == 429:
                return {
                    "error_code": "GITHUB_RATE_LIMITED",
                    "error_category": "RateLimit",
                    "error_message": f"GitHub API rate limit exceeded while querying {full_name}.",
                    "failed_operation": operation,
                    "suggested_action": "Wait for GitHub rate limit to reset or configure an authenticated token.",
                    "retryable": True,
                    "is_rate_limit": True,
                    "reset_at": err_reset_at,
                    "retry_after": err_retry_after
                }
            elif status == 504:
                return {
                    "error_code": "NETWORK_TIMEOUT",
                    "error_category": "Network",
                    "error_message": f"Connection to GitHub timed out while performing '{operation}'.",
                    "failed_operation": operation,
                    "suggested_action": "Check your network connectivity and click Retry Sync.",
                    "retryable": True,
                    "is_rate_limit": False
                }
            elif 500 <= status < 600:
                return {
                    "error_code": "GITHUB_SERVER_ERROR",
                    "error_category": "Server",
                    "error_message": f"GitHub API is temporarily unavailable (HTTP {status}).",
                    "failed_operation": operation,
                    "suggested_action": "GitHub is temporarily experiencing issues. Click Retry Sync to try again.",
                    "retryable": True,
                    "is_rate_limit": False
                }

        # 2. Check for database exceptions
        from sqlalchemy.exc import SQLAlchemyError
        if isinstance(err, SQLAlchemyError) or "database" in lower_msg or "psycopg" in lower_msg:
            return {
                "error_code": "DATABASE_ERROR",
                "error_category": "Database",
                "error_message": f"Database transaction error during synchronization: {raw_msg[:160]}",
                "failed_operation": operation,
                "suggested_action": "Check database connectivity and click Retry Sync.",
                "retryable": True,
                "is_rate_limit": False
            }

        # 3. Inspect network/DNS/socket exceptions
        if "getaddrinfo failed" in lower_msg or "gaierror" in lower_msg:
            return {
                "error_code": "NETWORK_DNS_ERROR",
                "error_category": "Network",
                "error_message": f"DNS resolution for api.github.com failed: {raw_msg[:160]}",
                "failed_operation": operation,
                "suggested_action": "Check your network DNS settings and internet connectivity, then click Retry Sync.",
                "retryable": True,
                "is_rate_limit": False
            }
        elif "timeout" in lower_msg or isinstance(err, (httpx.TimeoutException, asyncio.TimeoutError)):
            return {
                "error_code": "NETWORK_TIMEOUT",
                "error_category": "Network",
                "error_message": f"Connection to GitHub timed out: {raw_msg[:160]}",
                "failed_operation": operation,
                "suggested_action": "Verify internet connection and proxy configuration, then click Retry Sync.",
                "retryable": True,
                "is_rate_limit": False
            }
        elif "connection" in lower_msg or isinstance(err, (httpx.ConnectError, ConnectionError)):
            return {
                "error_code": "NETWORK_CONNECTION_ERROR",
                "error_category": "Network",
                "error_message": f"Network connection error: {raw_msg[:160]}",
                "failed_operation": operation,
                "suggested_action": "Check your network connection and click Retry Sync.",
                "retryable": True,
                "is_rate_limit": False
            }

        return {
            "error_code": "SYNC_FAILED",
            "error_category": "Unexpected",
            "error_message": f"Synchronization failed: {raw_msg[:180]}",
            "failed_operation": operation,
            "suggested_action": "Click Retry Sync. If the issue persists, inspect application logs.",
            "retryable": False,
            "is_rate_limit": False
        }

    @classmethod
    async def _execute_indexing_job_background(
        cls,
        job_id: int,
        repository_id: Optional[int] = None,
        branch: Optional[str] = None
    ):
        """Executes indexing pipeline in a separate database session context with complete argument resolution."""
        db = SessionLocal()
        target_repo_id = repository_id
        target_branch = branch
        try:
            job = db.query(IndexingJob).filter(IndexingJob.id == job_id).first()
            if not job:
                logger.warning(f"Indexing job {job_id} not found for background execution.")
                return
            if not target_repo_id:
                target_repo_id = job.repository_id
            if not target_branch:
                target_branch = job.branch or "main"
        except Exception as e:
            logger.error(f"Failed to resolve job metadata for job {job_id}: {e}")
            return
        finally:
            db.close()

        try:
            logger.info(f"Starting background sync indexing for job {job_id} (repo: {target_repo_id}, branch: {target_branch})...")
            await IndexingService.run_indexing_pipeline(job_id, target_repo_id, target_branch)
            logger.info(f"Background sync indexing completed for job {job_id}.")
        except Exception as err:
            logger.error(f"Error in background sync indexing job {job_id}: {err}", exc_info=True)
            # Ensure background exception is captured and persisted
            try:
                err_db = SessionLocal()
                err_job = err_db.query(IndexingJob).filter(IndexingJob.id == job_id).first()
                if err_job:
                    err_job.status = "FAILED"
                    err_job.stage = "FAILED"
                    err_job.error_message = redact_secrets(str(err))
                    err_job.completed_at = datetime.now(timezone.utc)
                err_repo = err_db.query(Repository).filter(Repository.id == target_repo_id).first()
                if err_repo:
                    if not (err_repo.files_count and err_repo.files_count > 0 and err_repo.last_indexed_at):
                        err_repo.status = "failed"
                err_db.commit()
                err_db.close()
            except Exception:
                pass

    @staticmethod
    def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @classmethod
    async def check_repository_for_updates(
        cls,
        db: Session,
        repository: Repository,
        force_check: bool = False
    ) -> Dict:
        """
        Polls remote repository for commit updates via GitHub API with bounded retries,
        structured failure classification, and independent sync/indexing tracking.
        """
        now = datetime.now(timezone.utc)
        if hasattr(db, "default_branch") and not hasattr(repository, "default_branch"):
            db, repository = repository, db
        repo_id = repository.id
        branch = repository.default_branch or "main"

        # 1. Concurrency protection: prevent duplicate concurrent sync checks
        sync_key = f"{repo_id}:{branch}"
        if repo_id in cls._in_flight_syncs or sync_key in cls._in_flight_syncs:
            logger.info(f"Sync check already in flight for {repository.full_name}:{branch}. Skipping concurrent request.")
            return {
                "status": "syncing",
                "message": "Synchronization is already in progress for this repository"
            }

        # 2. Local / folder uploaded repositories bypass remote GitHub checks
        if repository.provider in ("folder", "local") or (repository.full_name or "").startswith("local/"):
            repository.sync_status = "synced"
            repository.sync_error = None
            repository.sync_error_code = None
            repository.sync_error_category = None
            repository.sync_failed_operation = None
            repository.sync_suggested_action = None
            repository.sync_retry_count = 0
            repository.last_checked_at = now
            repository.sync_last_attempt_at = now
            db.commit()
            return {
                "status": "synced",
                "message": "Local repository is up to date (managed via folder upload)",
                "current_sha": repository.current_revision
            }

        # 3. Handle manual vs periodic retry policies & throttling
        if force_check:
            # Manual user action: reset retry counter and clear past backoff
            repository.sync_retry_count = 0
            cls._rate_limit_backoff.pop(repo_id, None)
        else:
            # Check global rate limit window
            global_reset = cls._to_utc(cls._global_rate_limit_reset)
            if global_reset and global_reset > now:
                remaining_sec = int((global_reset - now).total_seconds())
                repository.sync_status = "rate_limited"
                db.commit()
                return {
                    "status": "rate_limited",
                    "message": f"Global GitHub API rate limit active for another {remaining_sec}s",
                    "backoff_seconds": remaining_sec,
                    "reset_at": global_reset
                }

            # Periodic background check: respect backoff and retry bounds
            backoff_until = cls._to_utc(cls._rate_limit_backoff.get(repo_id))
            if backoff_until and backoff_until > now:
                remaining_sec = int((backoff_until - now).total_seconds())
                repository.sync_status = "rate_limited"
                db.commit()
                return {
                    "status": "rate_limited",
                    "message": f"GitHub API rate limit backoff active for another {remaining_sec}s",
                    "backoff_seconds": remaining_sec,
                    "reset_at": backoff_until
                }

            # If repo failed with a permanent error, do not poll continuously
            if repository.sync_status == "failed" and repository.sync_error_code in (
                "GITHUB_AUTH_FAILED", "GITHUB_PERMISSION_DENIED", "BRANCH_OR_REPO_NOT_FOUND", "REPOSITORY_EMPTY"
            ):
                return {
                    "status": "failed",
                    "message": "Sync skipped: permanent error requires manual resolution",
                    "error_code": repository.sync_error_code
                }

            # If retry limit reached for transient errors, require manual recovery
            if repository.sync_status == "failed" and (repository.sync_retry_count or 0) >= cls.MAX_SYNC_RETRIES:
                return {
                    "status": "failed",
                    "message": f"Sync skipped: retry limit of {cls.MAX_SYNC_RETRIES} attempts reached. Please use Retry Sync.",
                    "error_code": repository.sync_error_code
                }

            # Bounded exponential backoff for transient retries
            if repository.sync_status == "failed" and 0 < (repository.sync_retry_count or 0) < cls.MAX_SYNC_RETRIES:
                retry_count = repository.sync_retry_count
                backoff_delay = min(1800, (2 ** retry_count) * 60)
                last_attempt = cls._to_utc(repository.sync_last_attempt_at or repository.last_checked_at)
                if last_attempt and (now - last_attempt).total_seconds() < backoff_delay:
                    remaining = int(backoff_delay - (now - last_attempt).total_seconds())
                    return {
                        "status": "failed",
                        "message": f"Sync skipped: exponential backoff active for another {remaining}s (retry {retry_count}/{cls.MAX_SYNC_RETRIES})",
                        "error_code": repository.sync_error_code
                    }

            # Minimum interval throttling: prevent rapid redundant polling
            min_interval = max(10, getattr(settings, "GITHUB_SYNC_MIN_INTERVAL_SECONDS", 60))
            last_checked = cls._to_utc(repository.last_checked_at)
            if last_checked and (now - last_checked).total_seconds() < min_interval:
                elapsed = int((now - last_checked).total_seconds())
                remaining_throttle = int(min_interval - elapsed)
                return {
                    "status": "throttled",
                    "message": f"Sync skipped: checked recently ({elapsed}s ago, min interval {min_interval}s). Next check permitted in {remaining_throttle}s",
                    "next_permitted_seconds": remaining_throttle,
                    "current_sha": repository.current_revision or repository.last_synced_commit_sha
                }

        # 4. Check for active indexing job and recover stale jobs if stuck
        active_job = db.query(IndexingJob).filter(
            IndexingJob.repository_id == repo_id,
            IndexingJob.status.in_(["QUEUED", "CLONING", "PARSING", "INDEXING"])
        ).first()

        if active_job:
            started_at = cls._to_utc(active_job.started_at)
            job_age = (now - started_at).total_seconds() if started_at else 0
            if job_age > 900:
                logger.warning(f"Job {active_job.id} for {repository.full_name} is stale ({job_age:.0f}s). Recovering.")
                IndexingService.recover_stale_indexing_jobs(db)
            else:
                repository.sync_status = "syncing"
                db.commit()
                return {
                    "status": "syncing",
                    "message": f"Indexing job {active_job.id} is already in progress",
                    "job_id": active_job.id
                }

        # Mark in-flight
        cls._in_flight_syncs.add(sync_key)
        cls._in_flight_syncs.add(repo_id)
        try:
            # 5. Retrieve latest commit SHA from GitHub (resolve via connected account, user, or settings)
            user = getattr(repository, 'user', None) or (
                db.query(User).filter(User.id == repository.user_id).first() if repository.user_id else None
            )
            access_token = GitHubService.resolve_token_for_repository(
                repository, db=db, user=user, allow_server_fallback=not getattr(repository, "is_private", True)
            )
            if not access_token and not getattr(repository, "is_private", True):
                raw_user_token = getattr(user, 'github_access_token', None) if user else None
                access_token = GitHubService.resolve_token(raw_user_token)

            operation = "Fetch latest branch commit"
            sem = cls._get_semaphore()
            async with sem:
                import inspect
                sig = inspect.signature(GitHubService.get_branch_latest_commit)
                extra_kwargs = {}
                if "etag" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    cached_etag = cls._etag_cache.get(f"{repository.full_name}:{branch}")
                    extra_kwargs["etag"] = cached_etag
                    extra_kwargs["last_known_sha"] = repository.current_revision or repository.last_synced_commit_sha

                try:
                    remote_sha = await GitHubService.get_branch_latest_commit(
                        access_token=access_token,
                        full_name=repository.full_name,
                        branch=branch,
                        **extra_kwargs
                    )
                except Exception as check_err:
                    error_info = cls.classify_sync_error(check_err, repository.full_name, branch, operation=operation)
                    logger.warning(f"Sync check failed for {repository.full_name}: [{error_info['error_code']}] {error_info['error_message']}")

                    repository.last_checked_at = now
                    repository.sync_last_attempt_at = now
                    repository.sync_status = "rate_limited" if error_info["is_rate_limit"] else "failed"
                    repository.sync_error = error_info["error_message"]
                    repository.sync_error_code = error_info["error_code"]
                    repository.sync_error_category = error_info["error_category"]
                    repository.sync_failed_operation = error_info["failed_operation"]
                    repository.sync_suggested_action = error_info["suggested_action"]

                    if error_info["retryable"]:
                        repository.sync_retry_count = (repository.sync_retry_count or 0) + 1

                    if error_info["is_rate_limit"]:
                        reset_ts = error_info.get("reset_at")
                        if not reset_ts and error_info.get("retry_after"):
                            reset_ts = now + timedelta(seconds=error_info["retry_after"])
                        elif not reset_ts:
                            reset_ts = now + timedelta(minutes=15)

                        cls._rate_limit_backoff[repo_id] = reset_ts

                    try:
                        db.commit()
                    except Exception as commit_err:
                        try:
                            db.rollback()
                        except Exception:
                            pass
                        logger.error(f"Database commit failed while saving sync failure state for {repository.full_name}: {commit_err}")
                        db_err_info = cls.classify_sync_error(commit_err, repository.full_name, branch, operation="Persist sync failure state")
                        return {
                            "status": "failed",
                            "error": db_err_info["error_message"],
                            "error_code": db_err_info["error_code"],
                            "error_category": db_err_info["error_category"],
                            "failed_operation": db_err_info["failed_operation"],
                            "suggested_action": db_err_info["suggested_action"],
                            "retry_count": repository.sync_retry_count
                        }

                    return {
                        "status": repository.sync_status,
                        "error": repository.sync_error,
                        "error_code": repository.sync_error_code,
                        "error_category": repository.sync_error_category,
                        "failed_operation": repository.sync_failed_operation,
                        "suggested_action": repository.sync_suggested_action,
                        "retry_count": repository.sync_retry_count,
                        "reset_at": error_info.get("reset_at"),
                        "retry_after": error_info.get("retry_after")
                    }

            # 6. Remote query succeeded: update revision metadata & clear error states
            repository.last_checked_at = now
            repository.sync_last_attempt_at = now
            repository.latest_remote_commit_sha = remote_sha
            cls._rate_limit_backoff.pop(repo_id, None)

            current_rev = repository.current_revision or repository.last_synced_commit_sha
            if remote_sha == current_rev:
                # Already up to date
                repository.sync_status = "synced"
                repository.sync_error = None
                repository.sync_error_code = None
                repository.sync_error_category = None
                repository.sync_failed_operation = None
                repository.sync_suggested_action = None
                repository.sync_retry_count = 0
                repository.last_synced_commit_sha = remote_sha
                repository.last_synced_at = now
                try:
                    db.commit()
                except Exception as commit_err:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    logger.error(f"Database commit failed while saving sync success state for {repository.full_name}: {commit_err}")
                    db_err_info = cls.classify_sync_error(commit_err, repository.full_name, branch, operation="Persist sync state")
                    return {
                        "status": "failed",
                        "error": db_err_info["error_message"],
                        "error_code": db_err_info["error_code"],
                        "error_category": db_err_info["error_category"],
                        "failed_operation": db_err_info["failed_operation"],
                        "suggested_action": db_err_info["suggested_action"],
                        "retry_count": repository.sync_retry_count
                    }
                return {
                    "status": "synced",
                    "message": f"Repository is up to date at commit {remote_sha[:8]}",
                    "current_sha": remote_sha
                }

            # 7. New revision detected: Enqueue indexing pipeline
            logger.info(f"New commit {remote_sha[:8]} detected for {repository.full_name} (was {current_rev[:8] if current_rev else 'none'}).")
            repository.sync_status = "syncing"
            repository.sync_error = None
            repository.sync_error_code = None
            repository.sync_error_category = None
            repository.sync_failed_operation = None
            repository.sync_suggested_action = None
            repository.sync_retry_count = 0
            db.commit()

            job = IndexingService.create_indexing_job(db, repository, branch=branch)
            job.commit_sha = remote_sha
            db.commit()

            asyncio.create_task(cls._execute_indexing_job_background(job.id, repository.id, branch))

            return {
                "status": "syncing",
                "message": f"New commit {remote_sha[:8]} detected. Incremental indexing enqueued.",
                "job_id": job.id,
                "target_commit_sha": remote_sha
            }

        finally:
            cls._in_flight_syncs.discard(sync_key)
            cls._in_flight_syncs.discard(repo_id)

    @classmethod
    async def poll_all_repositories(cls):
        """Polls all active connected GitHub repositories for commit updates with burst throttling."""
        if not settings.GITHUB_SYNC_POLLING_ENABLED:
            return

        now = datetime.now(timezone.utc)
        if cls._global_rate_limit_reset and cls._global_rate_limit_reset > now:
            logger.info(f"Global GitHub API rate limit active until {cls._global_rate_limit_reset.isoformat()}. Skipping polling round.")
            return

        db = SessionLocal()
        try:
            repos = db.query(Repository).filter(
                Repository.provider == "github",
                Repository.status != "indexing"
            ).all()

            burst_delay = max(0.0, getattr(settings, "GITHUB_SYNC_BURST_DELAY_SECONDS", 1.0))
            for i, repo in enumerate(repos):
                if i > 0 and burst_delay > 0:
                    await asyncio.sleep(burst_delay)

                # Check if global rate limit window was triggered during polling loop
                now = datetime.now(timezone.utc)
                if cls._global_rate_limit_reset and cls._global_rate_limit_reset > now:
                    logger.info("Global rate limit hit during polling loop. Halting remaining checks.")
                    break

                try:
                    await cls.check_repository_for_updates(db, repo, force_check=False)
                except Exception as e:
                    logger.error(f"Error checking updates for {repo.full_name}: {e}")
        finally:
            db.close()

    @classmethod
    def get_sync_diagnostics(cls, db: Session, repository: Repository) -> Dict[str, Any]:
        """
        Builds safe diagnostics for authentication availability, remaining quota,
        last sync attempt, next permitted retry, and request failure category.
        Never exposes raw secrets or tokens.
        """
        now = datetime.now(timezone.utc)
        user = getattr(repository, 'user', None) or (
            db.query(User).filter(User.id == repository.user_id).first() if repository.user_id else None
        )
        token = GitHubService.resolve_token_for_repository(
            repository, db=db, user=user, allow_server_fallback=not getattr(repository, "is_private", True)
        )
        auth_diag = GitHubService.get_auth_diagnostics(token)

        rl_metrics = GitHubService.get_rate_limit_metrics()
        rate_limit_remaining = rl_metrics.get("remaining")
        rate_limit_limit = rl_metrics.get("limit")
        rate_limit_reset_at = rl_metrics.get("reset_at")

        repo_id = repository.id
        backoff_until = cls._to_utc(cls._rate_limit_backoff.get(repo_id))
        global_reset = cls._to_utc(cls._global_rate_limit_reset)
        last_attempt = cls._to_utc(repository.sync_last_attempt_at or repository.last_checked_at)
        last_checked = cls._to_utc(repository.last_checked_at)
        rate_limit_reset_at = cls._to_utc(rl_metrics.get("reset_at"))

        next_permitted = None

        if backoff_until and backoff_until > now:
            next_permitted = backoff_until
        elif global_reset and global_reset > now:
            next_permitted = global_reset
        elif repository.sync_status == "failed" and 0 < (repository.sync_retry_count or 0) < cls.MAX_SYNC_RETRIES:
            retry_count = repository.sync_retry_count
            backoff_delay = min(1800, (2 ** retry_count) * 60)
            if last_attempt:
                next_permitted = last_attempt + timedelta(seconds=backoff_delay)
        elif last_checked:
            min_interval = max(10, getattr(settings, "GITHUB_SYNC_MIN_INTERVAL_SECONDS", 60))
            candidate = last_checked + timedelta(seconds=min_interval)
            if candidate > now:
                next_permitted = candidate

        last_success_sha = repository.last_synced_commit_sha or repository.current_revision
        last_success_time = repository.last_synced_at or repository.last_indexed_at

        return {
            "repository_id": repository.id,
            "full_name": repository.full_name,
            "branch": repository.default_branch or "main",
            "sync_status": repository.sync_status or "synced",
            "auth_available": auth_diag.get("has_token", False),
            "auth_type": auth_diag.get("auth_type", "unauthenticated"),
            "token_source": "connected_account" if getattr(repository, "connected_account_id", None) else auth_diag.get("token_source", "none"),
            "rate_limit_remaining": rate_limit_remaining,
            "rate_limit_limit": rate_limit_limit,
            "rate_limit_reset_at": rate_limit_reset_at or backoff_until,
            "last_attempt_at": repository.sync_last_attempt_at or repository.last_checked_at,
            "last_successful_sync_at": last_success_time,
            "last_successful_commit_sha": last_success_sha,
            "next_permitted_sync_at": next_permitted,
            "error_category": repository.sync_error_category,
            "error_code": repository.sync_error_code,
            "failed_operation": repository.sync_failed_operation,
            "retry_count": repository.sync_retry_count or 0,
            "suggested_action": repository.sync_suggested_action
        }

    @classmethod
    def start_background_polling(cls):
        """Starts the periodic background scheduler task safely if not already active."""
        if not settings.GITHUB_SYNC_POLLING_ENABLED or cls._scheduler_started:
            return

        cls._scheduler_started = True

        async def _polling_loop():
            interval = max(60, settings.GITHUB_SYNC_POLLING_INTERVAL_SECONDS)
            logger.info(f"GitHub commit synchronization polling scheduler started (interval: {interval}s).")
            # Wait initial 15s to let application boot cleanly
            await asyncio.sleep(15)
            while cls._scheduler_started:
                try:
                    await cls.poll_all_repositories()
                except Exception as err:
                    logger.error(f"Error in periodic GitHub sync polling: {err}")
                await asyncio.sleep(interval)

        try:
            loop = asyncio.get_running_loop()
            cls._scheduler_task = loop.create_task(_polling_loop())
        except RuntimeError:
            pass

    @classmethod
    def stop_background_polling(cls):
        """Stops the background polling scheduler."""
        cls._scheduler_started = False
        if cls._scheduler_task:
            cls._scheduler_task.cancel()
            cls._scheduler_task = None
