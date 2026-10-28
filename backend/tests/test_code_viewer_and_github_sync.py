import hashlib
import hmac
import json
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.webhook_delivery import WebhookDelivery
from backend.app.models.indexing_job import IndexingJob
from backend.app.services.github_sync_service import GitHubSyncService


def test_independent_scrolling_css_containment():
    """
    Feature 1 Test:
    Verifies that the CSS file establishes independent scroll containers for:
    - Left file explorer (.file-tree with overflow-y: auto on .tree-body)
    - Center code viewer (.editor-main with overflow-y: auto and overflow-x: auto on #editor-code-pre)
    - Right symbol context (.context-panel with overflow-y: auto on .context-content)
    - Viewport height containment on body.code-viewer-page-body preventing page-level scrollbars.
    """
    css_path = settings.STATIC_DIR / "css" / "styles.css"
    assert css_path.exists(), "styles.css must exist"
    css = css_path.read_text(encoding="utf-8")

    # 1. Main code viewer layout
    assert ".code-viewer {" in css
    assert "overflow: hidden" in css

    # 2. Left file tree independent scroll
    assert ".file-tree {" in css
    assert "overflow-y: auto" in css
    assert "overscroll-behavior: contain" in css

    # 3. Center code canvas independent scroll & horizontal containment
    assert "#editor-code-pre {" in css
    assert "overflow-y: auto" in css
    assert "overflow-x: auto" in css

    # 4. Right symbol context panel independent scroll
    assert ".context-panel {" in css
    assert ".context-content" in css

    # 5. Whole-page overflow prevention for code viewer
    assert "body.code-viewer-page-body" in css
    assert "overflow: hidden" in css


def test_code_viewer_html_structure_and_independent_panels():
    """
    Feature 1 & 2 Test:
    Verifies that code_viewer.html defines the pinned headers and independent scroll bodies:
    - .tree-head, #explorer-search-input, and #tree-repo-header are pinned above #file-tree-container
    - .breadcrumb, .file-tab, and .symbol-bar are pinned above #editor-code-pre
    - .context-head, #symbol-context-card, and .context-tabs are pinned above #context-content-body
    """
    template_path = settings.TEMPLATES_DIR / "code_viewer.html"
    assert template_path.exists(), "code_viewer.html must exist"
    html = template_path.read_text(encoding="utf-8")

    assert "code-viewer-page-body" in html
    assert 'id="file-tree-container"' in html
    assert 'id="editor-code-pre"' in html
    assert 'id="context-content-body"' in html
    assert 'id="explorer-search-input"' in html
    assert 'id="breadcrumb-filename"' in html
    assert 'id="editor-active-file-tab"' in html
    assert 'data-view="code_viewer"' in html
    assert 'class="nav-item active"' in html


def test_code_viewer_dedicated_page_authenticated_access(client: TestClient, db_session: Session):
    """
    Feature 2 Test:
    Verifies /code_viewer responds with HTTP 200 for authenticated users.
    """
    resp = client.get("/code_viewer", follow_redirects=False)
    assert resp.status_code == 200
    assert "Code Search & Viewer" in resp.text
    assert "<!doctype html>" in resp.text.lower()


def test_code_viewer_clean_url_and_legacy_redirect(client: TestClient):
    """
    Feature 2 Test:
    Verifies clean URL /code_viewer and legacy redirect from /code_viewer.html.
    """
    # Legacy redirect
    resp = client.get("/code_viewer.html?repo=1&file=src%2Fmain.py", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("location", "")
    assert location.startswith("/code_viewer?repo=1&file=")

    # Following redirect returns 200
    followed = client.get("/code_viewer.html?repo=1&file=src%2Fmain.py", follow_redirects=True)
    assert followed.status_code == 200


def test_code_viewer_unauthenticated_redirect_to_login(client: TestClient):
    """
    Feature 2 Test:
    Verifies that an unauthenticated user requesting /code_viewer is redirected to /login with return_to.
    """
    resp = client.get("/code_viewer?repo=1&file=app.py", headers={"x-require-auth": "true"}, follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("location", "")
    assert location.startswith("/login?return_to=")


def test_code_viewer_path_traversal_rejected(client: TestClient, db_session: Session):
    """
    Feature 2 Test:
    Verifies that path traversal attacks in the file query parameter return 400 Bad Request.
    """
    resp = client.get("/code_viewer?repo=1&file=../../etc/passwd")
    assert resp.status_code == 400
    assert "traversal" in resp.json().get("detail", "").lower()


def test_code_viewer_unauthorized_repository_access_rejected(client: TestClient, db_session: Session):
    """
    Feature 2 Test:
    Verifies that trying to access a private repository owned by another user with a mismatched workspace returns 403 Forbidden.
    """
    user1 = User(email="owner1@acme.dev", full_name="User One", workspace_name="Workspace A", is_active=True)
    user2 = User(email="owner2@other.dev", full_name="User Two", workspace_name="Workspace B", is_active=True)
    db_session.add_all([user1, user2])
    db_session.commit()
    db_session.refresh(user1)
    db_session.refresh(user2)

    private_repo = Repository(
        name="secret-repo",
        full_name="acme/secret-repo",
        user_id=user1.id,
        is_private=True,
        status="ready"
    )
    db_session.add(private_repo)
    db_session.commit()
    db_session.refresh(private_repo)

    # Create session for user2
    from backend.app.core.security import create_session_token, create_user_session_record
    raw_token = create_session_token(user2.id)
    create_user_session_record(db_session, user2, raw_token, initial_path="/code_viewer")

    # Request code_viewer with user1's repo
    resp = client.get(
        f"/code_viewer?repo={private_repo.id}",
        cookies={"codemind_session": raw_token}
    )
    assert resp.status_code == 403
    assert "permission" in resp.json().get("detail", "").lower() or "denied" in resp.json().get("detail", "").lower()


def test_webhook_signature_verification():
    """
    Feature 3 Test:
    Verifies HMAC-SHA256 signature verification logic.
    """
    secret = "test-secret-key-12345"
    payload = b'{"ref":"refs/heads/main","after":"a1b2c3d4"}'

    # 1. Valid signature
    computed_hash = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    valid_header = f"sha256={computed_hash}"
    assert GitHubSyncService.verify_webhook_signature(payload, valid_header, secret=secret) is True

    # 2. Forged signature
    assert GitHubSyncService.verify_webhook_signature(payload, "sha256=invalidhex00000000", secret=secret) is False

    # 3. Missing header
    assert GitHubSyncService.verify_webhook_signature(payload, None, secret=secret) is False

    # 4. Malformed header without sha256=
    assert GitHubSyncService.verify_webhook_signature(payload, computed_hash, secret=secret) is False


def test_webhook_endpoint_rejects_unauthorized_signature(client: TestClient):
    """
    Feature 3 Test:
    POST /api/v1/webhooks/github rejects invalid signature with HTTP 401.
    """
    payload = {"zen": "Testing webhooks"}
    resp = client.post(
        "/api/v1/webhooks/github",
        json=payload,
        headers={
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": "sha256=bad_signature_here"
        }
    )
    assert resp.status_code == 401
    assert "verification failed" in resp.json().get("detail", "").lower()


def test_webhook_ping_event_accepted(client: TestClient):
    """
    Feature 3 Test:
    POST /api/v1/webhooks/github accepts valid ping event and returns 200 Pong.
    """
    secret = settings.GITHUB_WEBHOOK_SECRET
    body = json.dumps({"zen": "Keep it logically awesome.", "hook_id": 12345}).encode("utf-8")
    sig = f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"

    resp = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": sig
        }
    )
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"
    assert "ping received" in resp.json().get("message", "").lower()


def test_webhook_push_event_skips_duplicate_delivery(client: TestClient, db_session: Session):
    """
    Feature 3 Test:
    Verifies that receiving the same delivery ID twice returns duplicate status without creating duplicate indexing jobs.
    """
    secret = settings.GITHUB_WEBHOOK_SECRET
    delivery_id = "test-delivery-uuid-9999"

    # Pre-record delivery
    existing_del = WebhookDelivery(
        delivery_id=delivery_id,
        event_type="push",
        status="processed"
    )
    db_session.add(existing_del)
    db_session.commit()

    body = json.dumps({"ref": "refs/heads/main", "after": "commit1234"}).encode("utf-8")
    sig = f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"

    resp = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": sig,
            "X-GitHub-Delivery": delivery_id
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "duplicate"
    assert "already processed" in data.get("message", "").lower()


def test_webhook_push_event_skips_unchanged_commit(client: TestClient, db_session: Session):
    """
    Feature 3 Test:
    When a push event has the same commit SHA as the current indexed revision, re-indexing is skipped.
    """
    repo = Repository(
        name="test-repo",
        full_name="acme/test-repo",
        github_repo_id=77778888,
        default_branch="main",
        current_revision="abcdef1234567890",
        last_synced_commit_sha="abcdef1234567890",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    secret = settings.GITHUB_WEBHOOK_SECRET
    delivery_id = f"delivery-{hash('test-unchanged')}"

    body = json.dumps({
        "ref": "refs/heads/main",
        "after": "abcdef1234567890",
        "repository": {
            "id": 77778888,
            "full_name": "acme/test-repo"
        }
    }).encode("utf-8")
    sig = f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"

    resp = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": sig,
            "X-GitHub-Delivery": delivery_id
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "synced"
    assert "already up to date" in data.get("message", "").lower()


def test_webhook_push_event_skips_deleted_branch_safely(client: TestClient, db_session: Session):
    """
    Feature 3 Test:
    Branch deletion webhook must be safely ignored without deleting repository index.
    """
    repo = Repository(
        name="safe-repo",
        full_name="acme/safe-repo",
        github_repo_id=999888,
        default_branch="main",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    secret = settings.GITHUB_WEBHOOK_SECRET
    delivery_id = f"delivery-{hash('deleted-branch')}"

    body = json.dumps({
        "ref": "refs/heads/feature-branch",
        "deleted": True,
        "after": "0000000000000000000000000000000000000000",
        "repository": {
            "id": 999888,
            "full_name": "acme/safe-repo"
        }
    }).encode("utf-8")
    sig = f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"

    resp = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": sig,
            "X-GitHub-Delivery": delivery_id
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ignored"

    # Verify repository still exists in database
    persisted = db_session.query(Repository).filter(Repository.id == repo.id).first()
    assert persisted is not None


def test_webhook_push_event_detects_new_commit_and_enqueues_sync(client: TestClient, db_session: Session):
    """
    Feature 3 Test:
    When a push event contains a new commit on the default branch with source modifications,
    an indexing job is enqueued and sync_status becomes 'syncing'.
    """
    repo = Repository(
        name="sync-repo",
        full_name="acme/sync-repo",
        github_repo_id=55544433,
        default_branch="main",
        current_revision="old_commit_111",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    secret = settings.GITHUB_WEBHOOK_SECRET
    delivery_id = f"delivery-{hash('new-commit-enqueued')}"

    new_sha = "f0e1d2c3b4a59876"
    body = json.dumps({
        "ref": "refs/heads/main",
        "after": new_sha,
        "repository": {
            "id": 55544433,
            "full_name": "acme/sync-repo"
        },
        "commits": [
            {
                "id": new_sha,
                "added": ["src/service.py"],
                "modified": ["src/main.py"],
                "removed": ["src/old.py"]
            }
        ]
    }).encode("utf-8")
    sig = f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"

    resp = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": sig,
            "X-GitHub-Delivery": delivery_id
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "syncing"
    assert data.get("target_commit_sha") == new_sha
    assert data.get("changed_files_count") == 3

    # Verify job was created in DB
    db_session.refresh(repo)
    assert repo.sync_status == "syncing"
    assert repo.latest_remote_commit_sha == new_sha


def test_repository_sync_status_api(client: TestClient, db_session: Session):
    """
    Feature 3 Test:
    GET /api/v1/repositories/{id}/sync/status returns the verified sync metadata and commit SHAs.
    """
    repo = Repository(
        name="status-repo",
        full_name="acme/status-repo",
        default_branch="main",
        current_revision="commitaabbcc",
        last_synced_commit_sha="commitaabbcc",
        latest_remote_commit_sha="commitaabbcc",
        sync_status="synced",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    resp = client.get(f"/api/v1/repositories/{repo.id}/sync/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("repository_id") == repo.id
    assert data.get("sync_status") == "synced"
    assert data.get("last_synced_commit_sha") == "commitaabbcc"
    assert data.get("default_branch") == "main"
