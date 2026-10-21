from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_chunk import CodeChunk
from backend.app.schemas.git_history import CommitListResponse, CommitDetailResponse


def test_get_repository_commits_empty(client: TestClient, db_session: Session):
    """Verify commits endpoint returns truthful empty list when no repo commits are found."""
    repo = Repository(
        name="empty-repo",
        full_name="acme/empty-repo",
        default_branch="main",
        status="ready",
        files_count=0
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    response = client.get(f"/api/v1/repositories/{repo.id}/commits")
    assert response.status_code == 200
    data = response.json()
    assert data["repository_id"] == repo.id
    assert data["branch"] == "main"
    assert data["total_commits"] == 0
    assert data["commits"] == []


def test_get_repository_commits_from_indexed_snapshot(client: TestClient, db_session: Session):
    """Verify indexed repository without git credentials exposes verified indexed snapshot commit."""
    repo = Repository(
        name="billing-service",
        full_name="acme/billing-service",
        default_branch="main",
        status="ready",
        files_count=12,
        symbols_count=45,
        current_revision="8f21a6c9e01234567890abcdef1234567890abcd"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    response = client.get(f"/api/v1/repositories/{repo.id}/commits")
    assert response.status_code == 200
    data = response.json()
    assert data["total_commits"] == 1
    commit = data["commits"][0]
    assert commit["short_sha"] == "8f21a6c"
    assert "Indexed snapshot" in commit["message"]
    assert commit["files_count"] == 12


def test_get_commit_details_and_click_interaction(client: TestClient, db_session: Session):
    """
    Regression test for the Git History commit selection bug:
    Verifies that selecting/clicking a commit SHA retrieves full commit details,
    genuine file diffs, and evidence-based AI explanation.
    """
    repo = Repository(
        name="billing-service",
        full_name="acme/billing-service",
        default_branch="main",
        status="ready",
        files_count=2,
        symbols_count=5,
        current_revision="3c91de29e01234567890abcdef1234567890abcd"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    file1 = IndexedFile(
        repository_id=repo.id,
        path="src/billing/invoice_retry.py",
        language="python",
        lines_count=35
    )
    db_session.add(file1)
    db_session.commit()
    db_session.refresh(file1)

    chunk1 = CodeChunk(
        repository_id=repo.id,
        file_id=file1.id,
        file_path="src/billing/invoice_retry.py",
        chunk_index=0,
        chunk_text="def retry_invoice(invoice_id):\n    # Exponential backoff retry\n    return True\n",
        content_hash="hash-12345",
        language="python",
        start_line=1,
        end_line=3
    )
    db_session.add(chunk1)
    db_session.commit()

    # Query details for the commit (e.g. 3c91de2)
    response = client.get(f"/api/v1/repositories/{repo.id}/commits/3c91de29e01234567890abcdef1234567890abcd")
    assert response.status_code == 200
    data = response.json()

    assert data["sha"] == "3c91de29e01234567890abcdef1234567890abcd"
    assert data["short_sha"] == "3c91de2"
    assert len(data["files"]) >= 1
    assert data["files"][0]["filename"] == "src/billing/invoice_retry.py"
    assert "+ def retry_invoice" in data["files"][0]["patch"]
    assert "Confirmed:" in data["ai_explanation"]
    assert "Inference:" in data["ai_explanation"]
    assert len(data["citations"]) >= 1


def test_get_commits_via_mocked_github_api(client: TestClient, db_session: Session):
    """Verifies that commits fetched from GitHub API are correctly formatted and filtered."""
    repo = Repository(
        name="web-app",
        full_name="octocat/web-app",
        default_branch="main",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    mock_gh_commits = [
        {
            "sha": "a72bf049e01234567890abcdef1234567890abcd",
            "commit": {
                "message": "feat(billing): add invoice retry policy\n\nImplements exponential backoff.",
                "author": {"name": "Jon Bell", "email": "jon@example.com", "date": "2026-10-16T12:00:00Z"},
                "verification": {"verified": True}
            }
        },
        {
            "sha": "91bd1209e01234567890abcdef1234567890abcd",
            "commit": {
                "message": "fix(auth): prevent refresh token race condition",
                "author": {"name": "Maya Chen", "email": "maya@example.com", "date": "2026-10-15T10:00:00Z"},
                "verification": {"verified": True}
            }
        }
    ]

    with patch("httpx.AsyncClient.get") as mock_get:
        from unittest.mock import MagicMock
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_gh_commits
        mock_get.return_value = mock_response

        # Fetch without filter
        response = client.get(f"/api/v1/repositories/{repo.id}/commits")
        assert response.status_code == 200
        data = response.json()
        assert data["total_commits"] == 2
        assert data["commits"][0]["short_sha"] == "a72bf04"
        assert data["commits"][0]["message"] == "feat(billing): add invoice retry policy"
        assert data["commits"][0]["author_name"] == "Jon Bell"

        # Fetch with search filter for 'billing'
        response_filtered = client.get(f"/api/v1/repositories/{repo.id}/commits?search=billing")
        assert response_filtered.status_code == 200
        data_filtered = response_filtered.json()
        assert data_filtered["total_commits"] == 1
        assert data_filtered["commits"][0]["short_sha"] == "a72bf04"
