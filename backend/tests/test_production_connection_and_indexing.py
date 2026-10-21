import io
import shutil
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.integrations.github.service import GitHubService, GitHubServiceError
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.indexing_job import IndexingJob
from backend.app.models.repository import Repository
from backend.app.services.indexing_service import IndexingService


# --- Part 1 Tests: Repository Connection & URL Sanitization ---

def test_normalize_and_validate_repo_input_valid():
    """Verifies that valid GitHub repository formats are normalized correctly."""
    assert GitHubService.normalize_and_validate_repo_input("pallets/flask") == ("pallets", "flask")
    assert GitHubService.normalize_and_validate_repo_input("https://github.com/pallets/flask") == ("pallets", "flask")
    assert GitHubService.normalize_and_validate_repo_input("https://github.com/pallets/flask.git") == ("pallets", "flask")
    assert GitHubService.normalize_and_validate_repo_input("https://github.com/fastapi/fastapi/") == ("fastapi", "fastapi")
    assert GitHubService.normalize_and_validate_repo_input("  owner-123/repo_abc.v2  ") == ("owner-123", "repo_abc.v2")


def test_normalize_and_validate_repo_input_rejections():
    """Verifies that SSRF, path traversal, command injection, and invalid URLs are rejected."""
    # SSRF / non-GitHub host
    with pytest.raises(GitHubServiceError) as exc:
        GitHubService.normalize_and_validate_repo_input("https://evil.com/owner/repo")
    assert "Only GitHub repositories" in str(exc.value)

    # Path traversal
    with pytest.raises(GitHubServiceError):
        GitHubService.normalize_and_validate_repo_input("../owner/repo")

    with pytest.raises(GitHubServiceError):
        GitHubService.normalize_and_validate_repo_input("owner/../../etc/passwd")

    # Command injection characters
    with pytest.raises(GitHubServiceError):
        GitHubService.normalize_and_validate_repo_input("owner/repo; rm -rf /")

    with pytest.raises(GitHubServiceError):
        GitHubService.normalize_and_validate_repo_input("owner/repo | cat")

    with pytest.raises(GitHubServiceError):
        GitHubService.normalize_and_validate_repo_input("owner/`id`")

    with pytest.raises(GitHubServiceError):
        GitHubService.normalize_and_validate_repo_input("owner/$HOME")

    # Incomplete or empty
    with pytest.raises(GitHubServiceError):
        GitHubService.normalize_and_validate_repo_input("just-a-name")

    with pytest.raises(GitHubServiceError):
        GitHubService.normalize_and_validate_repo_input("")


def test_connect_public_repository_endpoint(client: TestClient, db_session: Session):
    """Verifies connecting a public GitHub repository without requiring OAuth tokens."""
    mock_repo_data = {
        "id": 1234567,
        "name": "flask",
        "full_name": "pallets/flask",
        "description": "The Python micro framework for building web applications.",
        "is_private": False,
        "default_branch": "main",
        "primary_language": "Python",
        "html_url": "https://github.com/pallets/flask",
        "clone_url": "https://github.com/pallets/flask.git",
        "owner_login": "pallets",
    }

    with patch.object(GitHubService, "resolve_public_repository", new=AsyncMock(return_value=mock_repo_data)):
        res = client.post(
            "/api/v1/repositories/connect-public",
            json={"repository": "https://github.com/pallets/flask", "auto_index": False}
        )
        assert res.status_code == 201
        data = res.json()
        assert data["full_name"] == "pallets/flask"
        assert data["primary_language"] == "Python"
        assert data["provider"] == "github"

        # Verify record exists in DB
        repo = db_session.query(Repository).filter(Repository.full_name == "pallets/flask").first()
        assert repo is not None
        assert repo.name == "flask"


def test_connect_public_repository_endpoint_validation_error(client: TestClient):
    """Verifies that invalid repository inputs produce HTTP 400 with a helpful error."""
    res = client.post(
        "/api/v1/repositories/connect-public",
        json={"repository": "https://notgithub.com/evil/repo", "auto_index": False}
    )
    assert res.status_code == 400
    assert "Only GitHub repositories" in res.json()["detail"]


# --- Part 6 Tests: Real Project Folder Upload ---

def test_upload_folder_valid_zip_and_cleanup(client: TestClient, db_session: Session):
    """Verifies uploading a project zip, extracting it securely, and cleaning it up upon deletion."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("app/main.py", "def main():\n    return 'Hello World'\n")
        zf.writestr("app/utils.py", "def helper():\n    pass\n")
    zip_buffer.seek(0)

    files = {"file": ("sample_project.zip", zip_buffer.getvalue(), "application/zip")}
    data = {"name": "sample_project", "auto_index": "false"}

    res = client.post("/api/v1/repositories/upload-folder", files=files, data=data)
    assert res.status_code == 201
    repo_data = res.json()
    assert repo_data["provider"] == "folder"
    assert repo_data["full_name"].startswith("local/sample_project")
    assert repo_data["primary_language"] == "Python"

    repo_id = repo_data["id"]
    repo = db_session.query(Repository).filter(Repository.id == repo_id).first()
    assert repo is not None
    folder_path = Path(repo.clone_url)
    assert folder_path.exists()
    assert (folder_path / "main.py").exists() or (folder_path / "app" / "main.py").exists()

    # Verify safe cascade deletion cleans up extracted folder on disk
    del_res = client.delete(f"/api/v1/repositories/{repo_id}")
    assert del_res.status_code == 200
    assert not folder_path.exists()


def test_upload_folder_zip_slip_rejected(client: TestClient):
    """Verifies Zip Slip path traversal attempts are rejected and cleaned up immediately."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../../malicious_escape.py", "import os; os.system('echo hacked')")
    zip_buffer.seek(0)

    files = {"file": ("exploit.zip", zip_buffer.getvalue(), "application/zip")}
    res = client.post("/api/v1/repositories/upload-folder", files=files, data={"auto_index": "false"})
    assert res.status_code == 400
    assert "traversal" in res.json()["detail"].lower()


def test_upload_folder_non_zip_rejected(client: TestClient):
    """Verifies non-zip files are rejected."""
    files = {"file": ("code.py", b"print('hello')", "text/x-python")}
    res = client.post("/api/v1/repositories/upload-folder", files=files, data={"auto_index": "false"})
    assert res.status_code == 400
    assert "Only .zip files are supported" in res.json()["detail"]


# --- Part 2 Tests: Empty Repository Handling & Reindex Pre-Flight Protection ---

@pytest.mark.anyio
async def test_empty_repository_indexing_handling(db_session: Session, tmp_path: Path):
    """Verifies truthful handling of an empty repository (0 files, 0 symbols, marks status ready)."""
    empty_dir = tmp_path / "empty_repo"
    empty_dir.mkdir()

    repo = Repository(
        name="empty-test",
        full_name="local/empty-test",
        provider="folder",
        clone_url=str(empty_dir),
        default_branch="main",
        status="pending"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    job = IndexingService.create_indexing_job(db_session, repo, "main")
    # Run pipeline asynchronously with test db session
    await IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)

    db_session.refresh(job)
    db_session.refresh(repo)

    assert job.status == "COMPLETED"
    assert job.stage == "COMPLETED"
    assert job.progress_percent == 100
    assert repo.status == "ready"
    assert repo.files_count == 0
    assert repo.symbols_count == 0


@pytest.mark.anyio
async def test_reindex_preflight_check_protects_existing_index(db_session: Session, tmp_path: Path):
    """
    Verifies that if embedding service pre-flight check fails during reindex,
    the existing indexed files, symbols, and knowledge graph are NOT wiped out.
    """
    repo_dir = tmp_path / "protected_repo"
    repo_dir.mkdir()
    (repo_dir / "index.js").write_text("console.log('alive');")

    repo = Repository(
        name="protected-repo",
        full_name="local/protected-repo",
        provider="folder",
        clone_url=str(repo_dir),
        default_branch="main",
        status="ready",
        files_count=1,
        symbols_count=1
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    # Insert existing indexed file and symbol
    existing_file = IndexedFile(
        repository_id=repo.id,
        path="index.js",
        content_hash="hash123",
        size_bytes=22,
        language="JavaScript",
        lines_count=1
    )
    db_session.add(existing_file)
    db_session.commit()
    db_session.refresh(existing_file)

    existing_sym = CodeSymbol(
        repository_id=repo.id,
        file_id=existing_file.id,
        name="log",
        kind="function",
        start_line=1,
        end_line=1
    )
    db_session.add(existing_sym)
    db_session.commit()

    # Trigger reindex with mocked pre-flight failure
    job = IndexingService.create_indexing_job(db_session, repo, "main")
    from backend.app.integrations.embeddings.service import EmbeddingService
    from backend.app.core.config import settings
    orig_ai = settings.AI_PROVIDER
    orig_emb = settings.EMBEDDING_PROVIDER
    try:
        settings.AI_PROVIDER = "ollama"
        settings.EMBEDDING_PROVIDER = "ollama"
        with patch.object(
            EmbeddingService,
            "get_status",
            return_value={"service_available": False, "message": "Ollama service unavailable: connection refused"}
        ):
            await IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)
    finally:
        settings.AI_PROVIDER = orig_ai
        settings.EMBEDDING_PROVIDER = orig_emb

    db_session.refresh(job)
    db_session.refresh(repo)

    # Job failed cleanly with error message
    assert job.status == "FAILED"
    assert job.stage == "PREFLIGHT"
    assert "Reindexing aborted" in (job.error_message or "")
    assert "Existing indexed repository data preserved" in (job.error_message or "")

    # Crucial: Existing indexed files and symbols were NOT wiped out!
    remaining_files = db_session.query(IndexedFile).filter(IndexedFile.repository_id == repo.id).count()
    remaining_syms = db_session.query(CodeSymbol).filter(CodeSymbol.repository_id == repo.id).count()
    assert remaining_files == 1
    assert remaining_syms == 1


# --- Part 3 Tests: Dashboard Overview Recent Questions ---

def test_dashboard_overview_recent_questions(client: TestClient, db_session: Session):
    """Verifies that GET /api/v1/dashboard/overview populates recent_questions from AssistantConversation."""
    conv = AssistantConversation(
        title="Where is the JWT token verified?",
        title_is_manual=True,
        branch="main"
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    msg_user = AssistantMessage(
        conversation_id=conv.id,
        role="user",
        content="Where is the JWT token verified in the backend?",
        status="success"
    )
    msg_asst = AssistantMessage(
        conversation_id=conv.id,
        role="assistant",
        content="The JWT token is verified in backend/app/core/security.py using verify_session_token.",
        status="success"
    )
    db_session.add_all([msg_user, msg_asst])
    db_session.commit()

    res = client.get("/api/v1/dashboard/overview")
    assert res.status_code == 200
    data = res.json()
    assert "recent_questions" in data
    assert len(data["recent_questions"]) > 0

    found = next((q for q in data["recent_questions"] if q["conversation_id"] == conv.id), None)
    assert found is not None
    assert found["title"] == "Where is the JWT token verified?"
    assert "JWT" in found["question"]
    assert "verify_session_token" in found["answer_preview"]
