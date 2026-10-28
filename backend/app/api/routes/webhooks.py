import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.schemas.repository import RepositorySyncStatusResponse, RepositorySyncDiagnosticsResponse
from backend.app.services.github_sync_service import GitHubSyncService
from backend.app.api.routes.api_v1 import get_current_user_record, verify_repo_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Webhooks & Commit Sync"])


@router.post("/webhooks/github", status_code=status.HTTP_200_OK)
async def github_webhook_handler(
    request: Request,
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
    db: Session = Depends(get_db)
):
    """
    Receives and processes GitHub Webhooks (push, ping, etc.).
    - Validates HMAC-SHA256 signature from X-Hub-Signature-256 header.
    - Idempotently deduplicates deliveries via X-GitHub-Delivery.
    - Automatically enqueues incremental re-indexing on new pushed commits.
    """
    raw_body = await request.body()

    # 1. Signature Verification
    is_valid = GitHubSyncService.verify_webhook_signature(
        raw_payload=raw_body,
        signature_header=x_hub_signature_256,
        secret=settings.GITHUB_WEBHOOK_SECRET
    )
    if not is_valid:
        logger.warning("Rejected GitHub webhook request: Invalid or missing X-Hub-Signature-256 signature.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature: HMAC-SHA256 verification failed."
        )

    # 2. Parse JSON payload
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as err:
        logger.warning(f"Rejected GitHub webhook request: Malformed JSON payload ({err}).")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON webhook payload."
        )

    event_type = (x_github_event or "push").strip().lower()
    delivery_id = (x_github_delivery or f"delivery-{hash(raw_body)}").strip()

    # 3. Handle 'ping' event
    if event_type == "ping":
        zen = payload.get("zen", "Keep it logically awesome.")
        hook_id = payload.get("hook_id", "unknown")
        logger.info(f"Received GitHub ping webhook (hook_id={hook_id}): '{zen}'")
        return {
            "status": "ok",
            "message": "GitHub webhook ping received successfully.",
            "hook_id": hook_id,
            "zen": zen
        }

    # 4. Handle unsupported or unrelated event types
    if event_type != "push":
        logger.info(f"Ignoring GitHub webhook event of type '{event_type}'.")
        return {
            "status": "ignored",
            "message": f"Webhook event '{event_type}' is not monitored for commit synchronization.",
            "delivery_id": delivery_id
        }

    # 5. Handle 'push' event
    result = await GitHubSyncService.handle_push_webhook(
        payload=payload,
        delivery_id=delivery_id,
        payload_bytes=raw_body,
        db=db
    )

    return result


@router.post("/repositories/{repository_id}/sync")
async def trigger_repository_sync(
    repository_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
):
    """
    Manually triggers commit synchronization check for a connected repository.
    Verifies user ownership, queries remote HEAD commit, and enqueues incremental indexing if new commits exist.
    """
    repo = verify_repo_access(repository_id, user, db)
    result = await GitHubSyncService.check_repository_for_updates(db, repo, force_check=True)
    db.refresh(repo)

    last_success_sha = repo.last_synced_commit_sha or repo.current_revision
    last_success_time = repo.last_synced_at or repo.last_indexed_at
    branch = repo.default_branch or "main"

    return {
        **result,
        "repository_id": repo.id,
        "repository_name": repo.name,
        "full_name": repo.full_name,
        "branch": branch,
        "default_branch": branch,
        "sync_status": repo.sync_status or "synced",
        "sync_error": repo.sync_error,
        "error_message": repo.sync_error,
        "error_code": repo.sync_error_code,
        "error_category": repo.sync_error_category,
        "failed_operation": repo.sync_failed_operation,
        "suggested_action": repo.sync_suggested_action,
        "last_synced_commit_sha": last_success_sha,
        "last_successful_commit_sha": last_success_sha,
        "last_synced_at": last_success_time.isoformat() if last_success_time else None,
        "last_success_at": last_success_time.isoformat() if last_success_time else None,
        "last_attempt_at": repo.sync_last_attempt_at.isoformat() if repo.sync_last_attempt_at else (repo.last_checked_at.isoformat() if repo.last_checked_at else None),
        "retry_count": repo.sync_retry_count or 0
    }


@router.get("/repositories/{repository_id}/sync/status", response_model=RepositorySyncStatusResponse)
def get_repository_sync_status(
    repository_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> RepositorySyncStatusResponse:
    """
    Returns verified synchronization and commit tracking status for a repository.
    """
    repo = verify_repo_access(repository_id, user, db)
    last_success_sha = repo.last_synced_commit_sha or repo.current_revision
    last_success_time = repo.last_synced_at or repo.last_indexed_at
    branch = repo.default_branch or "main"
    diag = GitHubSyncService.get_sync_diagnostics(db, repo)
    return RepositorySyncStatusResponse(
        repository_id=repo.id,
        repository_name=repo.name,
        full_name=repo.full_name,
        default_branch=branch,
        branch=branch,
        sync_status=repo.sync_status or "synced",
        last_synced_commit_sha=last_success_sha,
        last_successful_commit_sha=last_success_sha,
        latest_remote_commit_sha=repo.latest_remote_commit_sha,
        last_synced_at=last_success_time,
        last_success_at=last_success_time,
        last_checked_at=repo.last_checked_at,
        last_attempt_at=repo.sync_last_attempt_at or repo.last_checked_at,
        sync_error=repo.sync_error,
        error_message=repo.sync_error,
        error_code=repo.sync_error_code,
        error_category=repo.sync_error_category,
        failed_operation=repo.sync_failed_operation,
        suggested_action=repo.sync_suggested_action,
        retry_count=repo.sync_retry_count or 0,
        reset_at=diag.get("rate_limit_reset_at"),
        auth_available=diag.get("auth_available", False),
        auth_type=diag.get("auth_type", "unauthenticated"),
        rate_limit_remaining=diag.get("rate_limit_remaining"),
        rate_limit_limit=diag.get("rate_limit_limit"),
        next_permitted_sync_at=diag.get("next_permitted_sync_at")
    )


@router.get("/repositories/{repository_id}/sync/diagnostics", response_model=RepositorySyncDiagnosticsResponse)
def get_repository_sync_diagnostics(
    repository_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> RepositorySyncDiagnosticsResponse:
    """
    Returns comprehensive diagnostics for authentication availability, remaining quota,
    last sync attempt, next permitted retry, and request failure category. Never exposes secrets.
    """
    repo = verify_repo_access(repository_id, user, db)
    diag = GitHubSyncService.get_sync_diagnostics(db, repo)
    return RepositorySyncDiagnosticsResponse(**diag)
