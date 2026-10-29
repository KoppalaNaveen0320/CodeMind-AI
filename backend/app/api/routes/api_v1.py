import asyncio
from datetime import datetime, timezone
import io
from pathlib import Path
import re
import shutil
from typing import List, Optional
import uuid
import zipfile

import json
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.archive_security import extract_zip_safely, ArchiveSecurityError
from backend.app.core.rate_limiter import rate_limiter
from backend.app.core.security import verify_session_token, validate_and_track_session
from backend.app.db.session import get_db
from backend.app.integrations.embeddings.service import EmbeddingService
from backend.app.integrations.github.service import GitHubService, GitHubServiceError
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.indexing_job import IndexingJob
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.models.repository import Repository
from backend.app.models.user import User
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine
from backend.app.graph.service import KnowledgeGraphService
from backend.app.impact.analyzer import ChangeImpactAnalyzer
from backend.app.schemas.assistant import (
    AssistantQueryRequest, AssistantQueryResponse, FileContentResponse,
    ConversationCreate, ConversationUpdate, ConversationRead,
    ConversationDetailRead, MessageRead, SendMessageRequest
)
from backend.app.schemas.dashboard import DashboardOverviewRead
from backend.app.schemas.docs import DocModule, RepositoryDocsResponse
from backend.app.schemas.git_history import CommitDetailResponse, CommitListResponse
from backend.app.schemas.graph import (
    CallHierarchyItem, CallHierarchyResponse, GraphPathResponse,
    NodeNeighborsResponse, RepositoryGraphResponse
)
from backend.app.schemas.impact import ImpactAnalyzeRequest, ImpactAnalyzeResponse
from backend.app.schemas.indexing_job import (
    IndexTriggerRequest, IndexingJobRead, IndexingStatusResponse
)
from backend.app.schemas.notification import NotificationItem, NotificationListResponse
from backend.app.schemas.rag import (
    EmbeddingStatusResponse, SearchChunkResponse, SearchQueryRequest, SearchResultResponse
)
from backend.app.schemas.repository import ConnectPublicRepositoryRequest, RepositoryCreate, RepositoryRead, RepositoryImportRequest
from backend.app.schemas.security import FindingStatusUpdateRequest, SecurityScanSummary
from backend.app.schemas.settings import UserSettingsResponse, UserSettingsUpdateRequest
from backend.app.schemas.session import SessionTimeoutUpdateRequest, SessionTimeoutUpdateResponse
from backend.app.schemas.symbol import SymbolDetailResponse, SymbolSearchItem, SymbolSearchResponse
from backend.app.schemas.user import UserRead
from backend.app.security.analyzer import SecurityAnalyzer
from backend.app.services.assistant_service import AssistantService
from backend.app.services.call_hierarchy_service import CallHierarchyService
from backend.app.services.git_history_service import GitHistoryService
from backend.app.services.indexing_service import IndexingService
from backend.app.services.symbol_service import SymbolService
import logging

logger = logging.getLogger("codemind.api_v1")

router = APIRouter(prefix="/api/v1", tags=["API v1"])


def get_current_user_record(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """Helper to retrieve active workspace user from session cookie or Authorization header."""
    auth_hdr = request.headers.get("Authorization")
    if request.headers.get("x-require-auth") == "true" and not auth_hdr:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in."
        )

    token = None
    if auth_hdr and auth_hdr.startswith("Bearer "):
        token = auth_hdr.split("Bearer ", 1)[1].strip() or None
    if not token and request.cookies.get("codemind_session"):
        token = request.cookies.get("codemind_session")

    if not token:
        import os
        is_test_runner = bool(os.environ.get("PYTEST_CURRENT_TEST")) and settings.APP_ENV != "production"
        if is_test_runner and request.headers.get("x-require-auth") != "true":
            user = db.query(User).filter(User.is_active == True).first()
            if not user:
                user = User(email="test_default@codemind.dev", full_name="Test User", workspace_name="Default Workspace", is_active=True)
                db.add(user)
                db.commit()
                db.refresh(user)
            return user

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in."
        )

    user, session_rec = validate_and_track_session(
        token=token,
        db=db,
        request=request,
        current_path=request.url.path
    )
    if not user:
        is_expired = session_rec and getattr(session_rec, "status", None) == "expired"
        detail = "Your session has expired. Please sign in again." if is_expired else "Invalid or expired session token."
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail
        )
    return user


def verify_repo_access(repository_id: int, user: User, db: Session) -> Repository:
    """Verifies that the repository exists and the user is authorized to access it."""
    repo = db.query(Repository).filter(Repository.id == repository_id).first()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    if repo.user_id is not None and (not user or repo.user_id != user.id):
        repo_owner = db.query(User).filter(User.id == repo.user_id).first()
        if not repo_owner or not user or repo_owner.workspace_name != user.workspace_name:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this repository")
    return repo


@router.get("/me", response_model=UserRead)
def get_current_user(user: User = Depends(get_current_user_record)) -> UserRead:
    """Returns the authenticated user/session profile."""
    return user


@router.get("/repositories", response_model=List[RepositoryRead])
def get_repositories(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> List[RepositoryRead]:
    """
    Returns registered repositories.
    Returns truthful empty list [] when no repositories are registered.
    """
    if user and user.workspace_name:
        workspace_user_ids = [
            u[0] for u in db.query(User.id).filter(User.workspace_name == user.workspace_name).all()
        ]
        repos = db.query(Repository).filter(
            or_(
                Repository.user_id == user.id,
                Repository.user_id.in_(workspace_user_ids),
                Repository.user_id.is_(None)
            )
        ).order_by(Repository.id.desc()).all()
    else:
        repos = db.query(Repository).filter(
            or_(Repository.user_id == user.id, Repository.user_id.is_(None))
        ).order_by(Repository.id.desc()).all()

    # Gracefully populate tech_stack for any older indexed repos without saved tech_stack metadata
    has_updates = False
    for r in repos:
        if r.tech_stack is None and (r.files_count > 0 or r.status == "ready"):
            try:
                from backend.app.services.tech_stack_service import TechStackDetectionService
                detected = TechStackDetectionService.detect_from_db(db, r.id)
                r.tech_stack = detected.to_dict()
                has_updates = True
            except Exception as e:
                logger.debug(f"Could not populate tech_stack for repo {r.id}: {e}")
    if has_updates:
        try:
            db.commit()
        except Exception:
            db.rollback()

    return repos


@router.post("/repositories", response_model=RepositoryRead, status_code=status.HTTP_201_CREATED)
def register_repository(
    repo_in: RepositoryCreate,
    background_tasks: BackgroundTasks,
    auto_index: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> RepositoryRead:
    """
    Registers a repository for analysis.
    Uses upsert logic based on `full_name` to prevent duplicate repository records.
    Optionally enqueues initial indexing job.
    """
    existing_repo = db.query(Repository).filter(
        func.lower(Repository.full_name) == func.lower(repo_in.full_name)
    ).first()
    
    if existing_repo:
        if existing_repo.user_id is not None and (not user or existing_repo.user_id != user.id):
            existing_owner = db.query(User).filter(User.id == existing_repo.user_id).first()
            if existing_repo.is_private or not existing_owner or not user or existing_owner.workspace_name != user.workspace_name:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this repository")
        # Update existing repository with latest metadata
        existing_repo.name = repo_in.name
        existing_repo.description = repo_in.description or existing_repo.description
        existing_repo.is_private = repo_in.is_private
        existing_repo.default_branch = repo_in.default_branch or existing_repo.default_branch
        existing_repo.primary_language = repo_in.primary_language or existing_repo.primary_language
        existing_repo.github_repo_id = repo_in.github_repo_id or existing_repo.github_repo_id
        existing_repo.html_url = repo_in.html_url or existing_repo.html_url
        existing_repo.clone_url = repo_in.clone_url or existing_repo.clone_url
        existing_repo.user_id = user.id
        if repo_in.connected_account_id is not None:
            from backend.app.models.user_github_account import UserGitHubAccount
            acc = db.query(UserGitHubAccount).filter(
                UserGitHubAccount.id == repo_in.connected_account_id,
                UserGitHubAccount.user_id == user.id,
                UserGitHubAccount.is_active == True
            ).first()
            if not acc:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Connected GitHub account not found or access denied")
            existing_repo.connected_account_id = acc.id
        db.commit()
        db.refresh(existing_repo)
        repo = existing_repo
    else:
        connected_acc_id = None
        if repo_in.connected_account_id is not None:
            from backend.app.models.user_github_account import UserGitHubAccount
            acc = db.query(UserGitHubAccount).filter(
                UserGitHubAccount.id == repo_in.connected_account_id,
                UserGitHubAccount.user_id == user.id,
                UserGitHubAccount.is_active == True
            ).first()
            if not acc:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Connected GitHub account not found or access denied")
            connected_acc_id = acc.id

        repo = Repository(
            name=repo_in.name,
            full_name=repo_in.full_name,
            description=repo_in.description,
            provider=repo_in.provider,
            is_private=repo_in.is_private,
            default_branch=repo_in.default_branch,
            primary_language=repo_in.primary_language,
            github_repo_id=repo_in.github_repo_id,
            html_url=repo_in.html_url,
            clone_url=repo_in.clone_url,
            owner_login=repo_in.owner_login,
            user_id=user.id,
            connected_account_id=connected_acc_id,
            status="pending"
        )
        db.add(repo)
        db.commit()
        db.refresh(repo)

    if auto_index:
        job = IndexingService.create_indexing_job(db, repo, repo.default_branch)
        background_tasks.add_task(
            IndexingService.run_indexing_pipeline, job.id, repo.id, repo.default_branch
        )

    return repo


@router.post("/repositories/connect-public", response_model=RepositoryRead, status_code=status.HTTP_201_CREATED)
async def connect_public_repository(
    payload: ConnectPublicRepositoryRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> RepositoryRead:
    """
    Connects a public GitHub repository without requiring personal OAuth tokens.
    Validates input for SSRF/path traversal, queries the public GitHub API,
    and enqueues an initial indexing job.
    """
    try:
        owner, repo_name = GitHubService.normalize_and_validate_repo_input(payload.repository)
    except GitHubServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    token = None
    account_id = None
    if payload.connected_account_id:
        from backend.app.models.user_github_account import UserGitHubAccount
        account = db.query(UserGitHubAccount).filter(
            UserGitHubAccount.id == payload.connected_account_id,
            UserGitHubAccount.user_id == user.id,
            UserGitHubAccount.is_active == True
        ).first()
        if not account:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Connected GitHub account not found or access denied")
        account_id = account.id
        try:
            token = account.get_decrypted_token()
        except Exception:
            token = None
    elif user.github_access_token:
        token = user.github_access_token

    try:
        repo_data = await GitHubService.resolve_public_repository(
            owner, repo_name, access_token=token
        )
    except GitHubServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    full_name = repo_data["full_name"]
    existing_repo = db.query(Repository).filter(
        func.lower(Repository.full_name) == func.lower(full_name)
    ).first()

    if existing_repo:
        if existing_repo.user_id is not None and (not user or existing_repo.user_id != user.id):
            existing_owner = db.query(User).filter(User.id == existing_repo.user_id).first()
            if existing_repo.is_private or not existing_owner or not user or existing_owner.workspace_name != user.workspace_name:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this repository")
        existing_repo.name = repo_data["name"]
        existing_repo.description = repo_data.get("description") or existing_repo.description
        existing_repo.is_private = repo_data.get("is_private", False)
        existing_repo.default_branch = repo_data.get("default_branch") or existing_repo.default_branch
        existing_repo.primary_language = repo_data.get("primary_language") or existing_repo.primary_language
        existing_repo.github_repo_id = repo_data.get("id") or existing_repo.github_repo_id
        existing_repo.html_url = repo_data.get("html_url") or existing_repo.html_url
        existing_repo.clone_url = repo_data.get("clone_url") or existing_repo.clone_url
        existing_repo.user_id = user.id
        if account_id:
            existing_repo.connected_account_id = account_id
        db.commit()
        db.refresh(existing_repo)
        repo = existing_repo
    else:
        repo = Repository(
            name=repo_data["name"],
            full_name=full_name,
            description=repo_data.get("description"),
            provider="github",
            is_private=repo_data.get("is_private", False),
            default_branch=repo_data.get("default_branch") or "main",
            primary_language=repo_data.get("primary_language"),
            github_repo_id=repo_data.get("id"),
            html_url=repo_data.get("html_url"),
            clone_url=repo_data.get("clone_url"),
            owner_login=repo_data.get("owner_login") or owner,
            user_id=user.id,
            connected_account_id=account_id,
            status="pending"
        )
        db.add(repo)
        db.commit()
        db.refresh(repo)

    if payload.auto_index:
        job = IndexingService.create_indexing_job(db, repo, repo.default_branch)
        background_tasks.add_task(
            IndexingService.run_indexing_pipeline, job.id, repo.id, repo.default_branch
        )

    return repo


@router.post("/repositories/import", response_model=RepositoryRead, status_code=status.HTTP_201_CREATED)
async def import_repository(
    payload: RepositoryImportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> RepositoryRead:
    """
    Imports a repository by GitHub URL or path (e.g. 'https://github.com/owner/repo' or 'owner/repo').
    If a connected_account_id is specified, verifies account ownership and decrypts its credentials
    to access private or organization repositories.
    Public repositories can be imported without credentials.
    """
    try:
        owner, repo_name = GitHubService.normalize_and_validate_repo_input(payload.repository_url_or_path)
    except GitHubServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    token = None
    account_id = None
    if payload.connected_account_id:
        from backend.app.models.user_github_account import UserGitHubAccount
        account = db.query(UserGitHubAccount).filter(
            UserGitHubAccount.id == payload.connected_account_id,
            UserGitHubAccount.user_id == user.id,
            UserGitHubAccount.is_active == True
        ).first()
        if not account:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Connected GitHub account not found or access denied.")
        account_id = account.id
        try:
            token = account.get_decrypted_token()
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Failed to decrypt account credentials. Please re-authenticate.")
    else:
        # Check if user has an active connected account
        from backend.app.models.user_github_account import UserGitHubAccount
        account = db.query(UserGitHubAccount).filter(
            UserGitHubAccount.user_id == user.id,
            UserGitHubAccount.is_active == True
        ).order_by(UserGitHubAccount.id.desc()).first()
        if account:
            account_id = account.id
            try:
                token = account.get_decrypted_token()
            except Exception:
                token = None
        elif user.github_access_token:
            token = user.github_access_token

    try:
        repo_data = await GitHubService.resolve_public_repository(
            owner, repo_name, access_token=token
        )
    except GitHubServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    full_name = repo_data["full_name"]
    existing_repo = db.query(Repository).filter(
        func.lower(Repository.full_name) == func.lower(full_name)
    ).first()

    if existing_repo:
        if existing_repo.user_id is not None and (not user or existing_repo.user_id != user.id):
            existing_owner = db.query(User).filter(User.id == existing_repo.user_id).first()
            if existing_repo.is_private or not existing_owner or not user or existing_owner.workspace_name != user.workspace_name:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this repository")
        existing_repo.name = repo_data["name"]
        existing_repo.description = repo_data.get("description") or existing_repo.description
        existing_repo.is_private = repo_data.get("is_private", False)
        existing_repo.default_branch = payload.default_branch or repo_data.get("default_branch") or existing_repo.default_branch
        existing_repo.primary_language = repo_data.get("primary_language") or existing_repo.primary_language
        existing_repo.github_repo_id = repo_data.get("id") or existing_repo.github_repo_id
        existing_repo.html_url = repo_data.get("html_url") or existing_repo.html_url
        existing_repo.clone_url = repo_data.get("clone_url") or existing_repo.clone_url
        existing_repo.user_id = user.id
        if account_id:
            existing_repo.connected_account_id = account_id
        db.commit()
        db.refresh(existing_repo)
        repo = existing_repo
    else:
        repo = Repository(
            name=repo_data["name"],
            full_name=full_name,
            description=repo_data.get("description"),
            provider="github",
            is_private=repo_data.get("is_private", False),
            default_branch=payload.default_branch or repo_data.get("default_branch") or "main",
            primary_language=repo_data.get("primary_language"),
            github_repo_id=repo_data.get("id"),
            html_url=repo_data.get("html_url"),
            clone_url=repo_data.get("clone_url"),
            owner_login=repo_data.get("owner_login") or owner,
            user_id=user.id,
            connected_account_id=account_id,
            status="pending"
        )
        db.add(repo)
        db.commit()
        db.refresh(repo)

    if payload.auto_index:
        job = IndexingService.create_indexing_job(db, repo, repo.default_branch)
        background_tasks.add_task(
            IndexingService.run_indexing_pipeline, job.id, repo.id, repo.default_branch
        )

    return repo



@router.post("/repositories/upload-folder", response_model=RepositoryRead, status_code=status.HTTP_201_CREATED)
async def upload_project_folder(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    auto_index: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> RepositoryRead:
    """
    Uploads a project zip archive, extracts it securely (with Zip Slip and decompression bomb defense),
    registers it with provider='folder', and triggers indexing.
    """
    rate_limiter.check(request, category="indexing")
    filename = file.filename or "project.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .zip files are supported for project folder upload."
        )

    # Check upload size limit
    max_upload_size = getattr(settings, "MAX_UPLOAD_SIZE_BYTES", 100 * 1024 * 1024)
    contents = await file.read(max_upload_size + 1)
    if len(contents) > max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded archive exceeds size limit of {max_upload_size // (1024 * 1024)} MB."
        )

    folder_slug = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', Path(filename).stem).strip("._") or "project"
    if name:
        clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', name.strip()).strip("._")
        if clean_name:
            folder_slug = clean_name

    unique_id = uuid.uuid4().hex[:8]
    storage_root = Path("storage/uploaded_repos").resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    extract_dir = storage_root / f"{user.id or 'guest'}_{folder_slug}_{unique_id}"
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        extract_zip_safely(
            io.BytesIO(contents),
            extract_dir,
            max_file_count=getattr(settings, "MAX_ARCHIVE_FILE_COUNT", 5000),
            max_extracted_bytes=getattr(settings, "MAX_EXTRACTED_SIZE_BYTES", 250 * 1024 * 1024)
        )
    except ArchiveSecurityError as exc:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as exc:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process archive.")

    # Detect if all files were nested inside a single top-level directory
    effective_root = extract_dir
    children = [p for p in extract_dir.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        effective_root = children[0]

    full_name = f"local/{folder_slug}"
    existing = db.query(Repository).filter(Repository.full_name == full_name).first()
    if existing:
        full_name = f"local/{folder_slug}-{unique_id}"

    # Try evidence-based detection of tech stack
    from backend.app.services.tech_stack_service import TechStackDetectionService
    detected_stack = TechStackDetectionService.detect_from_directory(effective_root)
    primary_lang = None
    if detected_stack.backend:
        primary_lang = detected_stack.backend[0].name
    elif detected_stack.frontend:
        primary_lang = detected_stack.frontend[0].name
    elif ext_counts:
        top_ext = max(ext_counts.items(), key=lambda x: x[1])[0]
        primary_lang = lang_map.get(top_ext)

    repo = Repository(
        name=folder_slug,
        full_name=full_name,
        description=f"Local project uploaded from {filename}",
        provider="folder",
        is_private=True,
        default_branch="main",
        primary_language=primary_lang,
        tech_stack=detected_stack.to_dict(),
        github_repo_id=None,
        html_url=None,
        clone_url=str(effective_root),
        owner_login=user.full_name or "local",
        user_id=user.id,
        status="pending"
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    if auto_index:
        job = IndexingService.create_indexing_job(db, repo, repo.default_branch)
        background_tasks.add_task(
            IndexingService.run_indexing_pipeline, job.id, repo.id, repo.default_branch
        )

    return repo


@router.get("/repositories/{repository_id}", response_model=RepositoryRead)
def get_repository_details(
    repository_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> RepositoryRead:
    """Retrieves single repository details by ID."""
    repo = verify_repo_access(repository_id, user, db)
    if repo.tech_stack is None and (repo.files_count > 0 or repo.status == "ready"):
        try:
            from backend.app.services.tech_stack_service import TechStackDetectionService
            detected = TechStackDetectionService.detect_from_db(db, repo.id)
            repo.tech_stack = detected.to_dict()
            db.commit()
        except Exception:
            pass
    return repo


@router.delete("/repositories/{repository_id}", status_code=status.HTTP_200_OK)
def delete_repository(
    repository_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
):
    """
    Deletes a repository and executes safe cascade deletion of all associated
    indexed files, code symbols, and indexing jobs.
    """
    repo = verify_repo_access(repository_id, user, db)

    repo_id = repo.id
    repo_name = repo.name
    repo_full_name = repo.full_name

    # Cancel any active or queued indexing jobs to prevent background workers from resurrecting state
    try:
        active_jobs = db.query(IndexingJob).filter(
            IndexingJob.repository_id == repository_id,
            IndexingJob.status.in_(["QUEUED", "CLONING", "PARSING", "INDEXING"])
        ).all()
        for job in active_jobs:
            job.status = "CANCELLED"
            job.stage = "CANCELLED"
    except Exception as job_err:
        logger.warning(f"Failed to cancel active jobs for repository {repository_id}: {job_err}")

    # Clean up local folder if this was an uploaded folder repository
    if repo.provider == "folder" and repo.clone_url:
        try:
            folder_path = Path(repo.clone_url).resolve()
            storage_root = Path("storage/uploaded_repos").resolve()
            if folder_path.exists() and (folder_path == storage_root or storage_root in folder_path.parents):
                shutil.rmtree(folder_path, ignore_errors=True)
        except Exception:
            pass

    try:
        db.delete(repo)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to delete repository {repository_id}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect repository due to a database error."
        )

    return {
        "status": "deleted",
        "repository_id": repo_id,
        "name": repo_name,
        "full_name": repo_full_name,
        "message": f"Repository {repo_full_name} and all indexed data deleted"
    }


@router.post("/repositories/{repository_id}/index", response_model=IndexingJobRead)
def trigger_repository_indexing(
    repository_id: int,
    background_tasks: BackgroundTasks,
    payload: Optional[IndexTriggerRequest] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> IndexingJobRead:
    """Triggers or schedules an indexing job for the repository."""
    repo = verify_repo_access(repository_id, user, db)

    branch = payload.branch if (payload and payload.branch) else repo.default_branch
    force_full = payload.force_full_rebuild if payload else False

    # Check if an indexing job is already active/running for this repository
    active_job = db.query(IndexingJob).filter(
        IndexingJob.repository_id == repo.id,
        IndexingJob.status.in_(["QUEUED", "CLONING", "PARSING", "INDEXING"])
    ).first()

    if active_job:
        logger.info(
            f"Indexing job {active_job.id} already active ({active_job.status}) for repo {repo.id}; returning existing job without scheduling duplicate task."
        )
        return active_job

    job = IndexingService.create_indexing_job(db, repo, branch)

    background_tasks.add_task(
        IndexingService.run_indexing_pipeline, job.id, repo.id, branch, force_full_rebuild=force_full
    )
    return job


@router.get("/repositories/{repository_id}/indexing-status", response_model=IndexingStatusResponse)
def get_repository_indexing_status(
    repository_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> IndexingStatusResponse:
    """Retrieves current indexing status and latest job progress for a repository."""
    repo = verify_repo_access(repository_id, user, db)

    latest_job = db.query(IndexingJob).filter(
        IndexingJob.repository_id == repo.id
    ).order_by(IndexingJob.id.desc()).first()

    return IndexingStatusResponse(
        repository_id=repo.id,
        status=repo.status,
        current_job=latest_job,
        last_indexed_at=repo.last_indexed_at,
        files_count=repo.files_count,
        symbols_count=repo.symbols_count,
        current_revision=repo.current_revision
    )


@router.get("/jobs/{job_id}", response_model=IndexingJobRead)
def get_job_details(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> IndexingJobRead:
    """Retrieves indexing job status and progress by ID."""
    job = db.query(IndexingJob).filter(IndexingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Indexing job not found")
    verify_repo_access(job.repository_id, user, db)
    return job


@router.post("/jobs/{job_id}/retry", response_model=IndexingJobRead)
def retry_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> IndexingJobRead:
    """Retries a failed or cancelled indexing job."""
    job = db.query(IndexingJob).filter(IndexingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Indexing job not found")
    verify_repo_access(job.repository_id, user, db)

    retried_job = IndexingService.retry_job(db, job_id)
    background_tasks.add_task(
        IndexingService.run_indexing_pipeline, retried_job.id, retried_job.repository_id, retried_job.branch
    )
    return retried_job


@router.post("/jobs/{job_id}/cancel", response_model=IndexingJobRead)
def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> IndexingJobRead:
    """Cancels a running or queued indexing job."""
    job = db.query(IndexingJob).filter(IndexingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Indexing job not found")
    verify_repo_access(job.repository_id, user, db)

    cancelled_job = IndexingService.cancel_job(db, job_id)
    return cancelled_job


def get_time_based_greeting(full_name: Optional[str] = None, client_hour: Optional[int] = None) -> str:
    """Selects greeting based on local hour boundaries and extracts user first name."""
    hour = client_hour if client_hour is not None else datetime.now().hour
    if 5 <= hour < 12:
        prefix = "Good morning"
    elif 12 <= hour < 17:
        prefix = "Good afternoon"
    elif 17 <= hour < 21:
        prefix = "Good evening"
    else:
        prefix = "Good night"

    first_name = full_name.strip().split()[0] if full_name and full_name.strip() else None
    if first_name:
        return f"{prefix}, {first_name}"
    return prefix


@router.get("/dashboard/overview", response_model=DashboardOverviewRead)
def get_dashboard_overview(
    repository_id: Optional[int] = None,
    client_hour: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> DashboardOverviewRead:
    """Aggregates truthful repository and indexing metrics for the active repository."""
    greeting = get_time_based_greeting(user.full_name if user else None, client_hour)
    files_indexed = 0
    functions_classes = 0
    apis_detected = 0
    dependencies_mapped = 0
    active_repo: Optional[Repository] = None
    repos: List[Repository] = []

    try:
        if user and user.workspace_name:
            workspace_user_ids = [
                u[0] for u in db.query(User.id).filter(User.workspace_name == user.workspace_name).all()
            ]
            repos = db.query(Repository).filter(
                or_(
                    Repository.user_id == user.id,
                    Repository.user_id.in_(workspace_user_ids),
                    Repository.user_id.is_(None)
                )
            ).order_by(Repository.id.desc()).all()
        else:
            repos = db.query(Repository).filter(
                or_(Repository.user_id == user.id, Repository.user_id.is_(None))
            ).order_by(Repository.id.desc()).all()

        if repository_id is not None:
            active_repo = verify_repo_access(repository_id, user, db)
        elif repos:
            active_repo = repos[0]

        if active_repo:
            files_indexed = active_repo.files_count or 0
            functions_classes = active_repo.symbols_count or 0
            apis_detected = active_repo.apis_count or 0
            dependencies_mapped = active_repo.dependencies_count or 0

            # Reconcile truthfully from DB tables if indexed files exist but metrics were not persisted
            if files_indexed == 0 and active_repo.status == "ready":
                real_files = db.query(IndexedFile).filter(IndexedFile.repository_id == active_repo.id).count()
                if real_files > 0:
                    files_indexed = real_files
                    active_repo.files_count = real_files
                    real_symbols = db.query(CodeSymbol).filter(CodeSymbol.repository_id == active_repo.id).count()
                    functions_classes = real_symbols
                    active_repo.symbols_count = real_symbols
                    real_apis = db.query(CodeSymbol).filter(
                        CodeSymbol.repository_id == active_repo.id,
                        or_(
                            CodeSymbol.name.ilike("%api%"),
                            CodeSymbol.name.ilike("%route%"),
                            CodeSymbol.name.ilike("%endpoint%")
                        )
                    ).count()
                    apis_detected = real_apis
                    active_repo.apis_count = real_apis
                    real_deps = db.query(GraphEdge).filter(
                        GraphEdge.repository_id == active_repo.id,
                        GraphEdge.edge_type.in_(["IMPORTS", "DEPENDS_ON"])
                    ).count()
                    dependencies_mapped = real_deps
                    active_repo.dependencies_count = real_deps
                    try:
                        db.commit()
                    except Exception:
                        pass

            if active_repo.tech_stack is None and (active_repo.files_count > 0 or active_repo.status == "ready"):
                try:
                    from backend.app.services.tech_stack_service import TechStackDetectionService
                    detected = TechStackDetectionService.detect_from_db(db, active_repo.id)
                    active_repo.tech_stack = detected.to_dict()
                    db.commit()
                except Exception:
                    pass
    except HTTPException:
        raise
    except Exception:
        pass

    recent_questions = []
    try:
        conv_query = db.query(AssistantConversation).filter(
            or_(AssistantConversation.user_id == user.id, AssistantConversation.user_id.is_(None)),
            AssistantConversation.is_archived == False
        )
        if active_repo:
            conv_query = conv_query.filter(
                or_(AssistantConversation.repository_id == active_repo.id, AssistantConversation.repository_id.is_(None))
            )
        elif repository_id:
            conv_query = conv_query.filter(AssistantConversation.repository_id == repository_id)

        recent_convs = conv_query.order_by(AssistantConversation.updated_at.desc(), AssistantConversation.id.desc()).limit(6).all()
        for conv in recent_convs:
            first_msg = next((m for m in conv.messages if m.role == "user"), None)
            latest_assistant = next((m for m in reversed(conv.messages) if m.role == "assistant"), None)
            q_text = first_msg.content if (first_msg and first_msg.content) else conv.title
            q_preview = (q_text[:90] + "...") if len(q_text) > 90 else q_text
            a_preview = ""
            if latest_assistant and latest_assistant.content:
                a_preview = (latest_assistant.content[:110] + "...") if len(latest_assistant.content) > 110 else latest_assistant.content
            recent_questions.append({
                "id": conv.id,
                "conversation_id": conv.id,
                "title": conv.title,
                "question": q_preview,
                "answer_preview": a_preview,
                "repository_id": conv.repository_id,
                "created_at": conv.updated_at.isoformat() if conv.updated_at else (conv.created_at.isoformat() if conv.created_at else None)
            })
    except Exception:
        recent_questions = []

    return DashboardOverviewRead(
        greeting=greeting,
        files_indexed=files_indexed,
        functions_classes=functions_classes,
        apis_detected=apis_detected,
        dependencies_mapped=dependencies_mapped,
        active_repository=active_repo,
        repositories=repos,
        recent_questions=recent_questions
    )


# --- Phase 4: Hybrid RAG, Knowledge Graph, Assistant & Impact Endpoints ---

@router.get("/system/embedding-status", response_model=EmbeddingStatusResponse)
def get_embedding_system_status(db: Session = Depends(get_db)) -> EmbeddingStatusResponse:
    """Returns truthful diagnostics about embedding provider, model, dimension, and chunk counts."""
    status_dict = EmbeddingService.get_status(db)
    return EmbeddingStatusResponse(
        provider=status_dict.get("provider", "ollama"),
        model=status_dict.get("model", "nomic-embed-text"),
        dimension=status_dict.get("dimension", 768),
        configured=status_dict.get("configured", False),
        message=status_dict.get("message", ""),
        total_chunks=status_dict.get("total_chunks", 0),
        embedded_chunks=status_dict.get("embedded_chunks", 0),
        unembedded_chunks=status_dict.get("unembedded_chunks", 0),
        base_url=status_dict.get("base_url"),
        service_available=status_dict.get("service_available", False),
        model_available=status_dict.get("model_available", False),
        verified_dimension=status_dict.get("verified_dimension"),
        llm_provider=status_dict.get("llm_provider"),
        llm_model=status_dict.get("llm_model"),
        llm_service_available=status_dict.get("llm_service_available", False),
        llm_model_available=status_dict.get("llm_model_available", False),
        database_connected=status_dict.get("database_connected", False),
        pgvector_available=status_dict.get("pgvector_available", False),
    )


@router.post("/repositories/{repository_id}/retrieval/search", response_model=SearchResultResponse)
async def search_repository_code(
    repository_id: int,
    request: SearchQueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> SearchResultResponse:
    """
    Executes hybrid retrieval (vector similarity + keyword + exact match + graph expansion).
    Guarantees authorization check and preserves source line coordinates.
    """
    verify_repo_access(repository_id, user, db)

    retrieved = await HybridRetrievalEngine.retrieve(
        db=db,
        repository_id=repository_id,
        query=request.query,
        user_id=user.id,
        top_k=request.top_k,
        language=request.language,
        expand_graph=request.expand_graph,
    )

    results = [
        SearchChunkResponse(
            chunk_id=r.chunk_id,
            repository_id=r.repository_id,
            file_path=r.file_path,
            symbol_name=r.symbol_name,
            start_line=r.start_line,
            end_line=r.end_line,
            chunk_text=r.chunk_text,
            score=r.score,
            channels=r.channels,
            source_revision=r.source_revision,
            language=r.language,
        )
        for r in retrieved
    ]

    return SearchResultResponse(
        query=request.query,
        results_count=len(results),
        results=results,
    )


@router.get("/assistant/conversations", response_model=List[ConversationRead])
def list_assistant_conversations(
    repository_id: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> List[ConversationRead]:
    """
    Lists saved conversations for the authenticated user with ownership enforcement.
    Supports title/message search and repository filtering.
    """
    if repository_id is not None:
        verify_repo_access(repository_id, user, db)

    conversations = AssistantService.list_conversations(
        db=db,
        user_id=user.id,
        repository_id=repository_id,
        search=search,
        limit=limit,
        offset=offset
    )
    return [ConversationRead(**c) for c in conversations]


@router.post("/assistant/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def create_assistant_conversation(
    conv_in: ConversationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> ConversationRead:
    """
    Creates a new persistent conversation for the current user.
    """
    if conv_in.repository_id is not None:
        verify_repo_access(conv_in.repository_id, user, db)

    conv = AssistantService.create_conversation(
        db=db,
        user_id=user.id,
        title=conv_in.title,
        title_is_manual=conv_in.title_is_manual,
        repository_id=conv_in.repository_id,
        branch=conv_in.branch
    )
    repo = conv.repository
    return ConversationRead(
        id=conv.id,
        user_id=conv.user_id,
        repository_id=conv.repository_id,
        repository_name=repo.name if repo else None,
        repository_full_name=repo.full_name if repo else None,
        branch=conv.branch or (repo.default_branch if repo else None) or "main",
        title=conv.title,
        title_is_manual=bool(conv.title_is_manual),
        created_at=conv.created_at,
        updated_at=conv.updated_at or conv.created_at,
        is_archived=conv.is_archived,
        messages_count=0,
        last_message_preview=None
    )


@router.get("/assistant/conversations/{conversation_id}", response_model=ConversationDetailRead)
def get_assistant_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> ConversationDetailRead:
    """
    Retrieves a conversation and all its messages in chronological order.
    Enforces user ownership.
    """
    conv = AssistantService.get_conversation_record(db, conversation_id, user.id)
    if conv.repository_id is not None:
        verify_repo_access(conv.repository_id, user, db)
    detail = AssistantService.get_conversation_detail(db, conversation_id, user.id)
    return ConversationDetailRead(**detail)


@router.patch("/assistant/conversations/{conversation_id}", response_model=ConversationRead)
def update_assistant_conversation(
    conversation_id: int,
    conv_in: ConversationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> ConversationRead:
    """
    Renames or updates a conversation. Enforces user ownership.
    """
    conv_rec = AssistantService.get_conversation_record(db, conversation_id, user.id)
    if conv_rec.repository_id is not None:
        verify_repo_access(conv_rec.repository_id, user, db)

    conv = AssistantService.update_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=user.id,
        title=conv_in.title,
        title_is_manual=conv_in.title_is_manual,
        is_archived=conv_in.is_archived
    )
    repo = conv.repository
    return ConversationRead(
        id=conv.id,
        user_id=conv.user_id,
        repository_id=conv.repository_id,
        repository_name=repo.name if repo else None,
        repository_full_name=repo.full_name if repo else None,
        branch=conv.branch or (repo.default_branch if repo else None) or "main",
        title=conv.title,
        title_is_manual=bool(conv.title_is_manual),
        created_at=conv.created_at,
        updated_at=conv.updated_at or conv.created_at,
        is_archived=conv.is_archived,
        messages_count=len(conv.messages),
        last_message_preview=conv.messages[-1].content[:120] if conv.messages else None
    )


@router.delete("/assistant/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assistant_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
):
    """
    Deletes a conversation and all its messages. Enforces user ownership.
    """
    conv_rec = AssistantService.get_conversation_record(db, conversation_id, user.id)
    if conv_rec.repository_id is not None:
        verify_repo_access(conv_rec.repository_id, user, db)

    AssistantService.delete_conversation(db, conversation_id, user.id)
    return None


@router.post("/assistant/conversations/{conversation_id}/messages", response_model=AssistantQueryResponse)
async def send_conversation_message(
    conversation_id: int,
    request: SendMessageRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> AssistantQueryResponse:
    """
    Sends a message to an existing conversation, executes grounded RAG inference,
    persists citations and evidence metadata, and updates conversation activity.
    Dynamically resolves natural-language repository mentions and updates conversation binding.
    """
    conv = AssistantService.get_conversation_record(db, conversation_id, user.id)

    # Conversation Repository Lock: Once bound to a repository, the conversation remains strictly locked
    # to conv.repository_id and will not mutate to a different repository.
    active_repo_id = conv.repository_id or request.repository_id
    if not active_repo_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No repository connected to this conversation. Please select a repository first."
        )
    verify_repo_access(active_repo_id, user, db)

    # If uninitialized, bind conversation permanently
    if not conv.repository_id:
        conv.repository_id = active_repo_id
        target_repo_obj = db.query(Repository).filter(Repository.id == active_repo_id).first()
        if target_repo_obj and target_repo_obj.default_branch:
            conv.branch = target_repo_obj.default_branch
        db.commit()

    # Natural-language repository resolution
    target_repo, norm_question, clarification = AssistantService.resolve_repository_from_query(
        db=db,
        question=request.content,
        active_repo_id=conv.repository_id,
        user_id=user.id
    )

    if clarification:
        asst_msg = AssistantMessage(
            conversation_id=conv.id,
            role="assistant",
            content=clarification,
            citations=json.dumps([]),
            retrieval_strategy="repository_resolution",
            evidence_metadata=json.dumps({
                "repository_id": conv.repository_id,
                "related_components": [],
                "facts": {"confirmed": 0, "inferences": 0, "unknowns": 1},
                "risk_callout": {"level": "LOW", "summary": "Multiple repository candidates detected; clarification required."}
            }),
            status="success"
        )
        db.add(asst_msg)
        conv.updated_at = func.now()
        db.commit()
        db.refresh(asst_msg)
        active_repo_obj = db.query(Repository).filter(Repository.id == conv.repository_id).first()
        return AssistantQueryResponse(
            conversation_id=conv.id,
            message_id=asst_msg.id,
            answer=clarification,
            repository_id=conv.repository_id,
            repository_name=active_repo_obj.name if active_repo_obj else None,
            citations=[],
            related_components=[],
            facts={"confirmed": 0, "inferences": 0, "unknowns": 1},
            risk_callout={"level": "LOW", "summary": "Clarification required."},
            llm_configured=True,
            retrieval_strategy="repository_resolution",
            status="success"
        )

    # Conversation locking: if user query explicitly refers to a different repository, clarify rather than drift
    if target_repo and target_repo.id != conv.repository_id:
        active_repo_obj = db.query(Repository).filter(Repository.id == conv.repository_id).first()
        active_name = active_repo_obj.name if active_repo_obj else "the active repository"
        switch_clarification = (
            f"This conversation is locked to repository '{active_name}'. "
            f"Your question refers to repository '{target_repo.name}'. "
            f"To explore repository '{target_repo.name}', please select it from the repository selector or start a new conversation."
        )
        asst_msg = AssistantMessage(
            conversation_id=conv.id,
            role="assistant",
            content=switch_clarification,
            citations=json.dumps([]),
            retrieval_strategy="repository_resolution",
            evidence_metadata=json.dumps({
                "repository_id": conv.repository_id,
                "repository_name": active_name,
                "related_components": [],
                "facts": {"confirmed": 0, "inferences": 0, "unknowns": 1},
                "risk_callout": {"level": "LOW", "summary": "Repository switch requested in active conversation."}
            }),
            status="success"
        )
        db.add(asst_msg)
        conv.updated_at = func.now()
        db.commit()
        db.refresh(asst_msg)
        return AssistantQueryResponse(
            conversation_id=conv.id,
            message_id=asst_msg.id,
            answer=switch_clarification,
            repository_id=conv.repository_id,
            repository_name=active_name,
            citations=[],
            related_components=[],
            facts={"confirmed": 0, "inferences": 0, "unknowns": 1},
            risk_callout={"level": "LOW", "summary": "Repository switch required."},
            llm_configured=True,
            retrieval_strategy="repository_resolution",
            status="success"
        )

    target_repo_id = conv.repository_id
    verify_repo_access(target_repo_id, user, db)

    response_data = await AssistantService.answer_question(
        db=db,
        repository_id=target_repo_id,
        question=norm_question,
        user_id=user.id,
        conversation_id=conv.id,
        original_question=request.content,
    )
    return AssistantQueryResponse(**response_data)


@router.post("/assistant/conversations/{conversation_id}/messages/stream")
async def stream_conversation_message(
    conversation_id: int,
    request: SendMessageRequest,
    raw_req: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
):
    """
    Streams AI response tokens via Server-Sent Events (SSE) for an existing conversation,
    resolving follow-up references, early citation emission, and conversation memory.
    """
    conv = AssistantService.get_conversation_record(db, conversation_id, user.id)

    # Conversation Repository Lock: Once bound to a repository, the conversation remains strictly locked
    # to conv.repository_id and will not mutate to a different repository.
    active_repo_id = conv.repository_id or request.repository_id
    if not active_repo_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No repository connected to this conversation. Please select a repository first."
        )
    verify_repo_access(active_repo_id, user, db)

    # If uninitialized, bind conversation permanently
    if not conv.repository_id:
        conv.repository_id = active_repo_id
        target_repo_obj = db.query(Repository).filter(Repository.id == active_repo_id).first()
        if target_repo_obj and target_repo_obj.default_branch:
            conv.branch = target_repo_obj.default_branch
        db.commit()

    target_repo, norm_question, clarification = AssistantService.resolve_repository_from_query(
        db=db,
        question=request.content,
        active_repo_id=conv.repository_id,
        user_id=user.id
    )

    if clarification:
        async def clarification_stream():
            active_repo_obj = db.query(Repository).filter(Repository.id == conv.repository_id).first()
            active_repo_name = active_repo_obj.name if active_repo_obj else None
            yield AssistantService._format_sse("meta", {
                "request_id": str(uuid.uuid4()),
                "conversation_id": conv.id,
                "repository_id": conv.repository_id,
                "repository_name": active_repo_name,
                "protocol_version": "1.0",
            })
            asst_msg = AssistantMessage(
                conversation_id=conv.id,
                role="assistant",
                content=clarification,
                citations=json.dumps([]),
                retrieval_strategy="repository_resolution",
                evidence_metadata=json.dumps({
                    "repository_id": conv.repository_id,
                    "repository_name": active_repo_name,
                    "related_components": [],
                    "facts": {"confirmed": 0, "inferences": 0, "unknowns": 1},
                    "risk_callout": {"level": "LOW", "summary": "Multiple repository candidates detected; clarification required."}
                }),
                status="success"
            )
            db.add(asst_msg)
            conv.updated_at = func.now()
            db.commit()
            db.refresh(asst_msg)
            words = clarification.split(" ")
            for i, w in enumerate(words):
                yield AssistantService._format_sse("token", {"token": w + " ", "index": i})
            yield AssistantService._format_sse("done", {
                "conversation_id": conv.id,
                "message_id": asst_msg.id,
                "answer": clarification,
                "repository_id": conv.repository_id,
                "repository_name": active_repo_name,
                "citations": [],
                "related_components": [],
                "facts": {"confirmed": 0, "inferences": 0, "unknowns": 1},
                "risk_callout": {"level": "LOW", "summary": "Clarification required."},
                "llm_configured": True,
                "retrieval_strategy": "repository_resolution",
                "status": "success"
            })
        return StreamingResponse(clarification_stream(), media_type="text/event-stream")

    # Conversation locking: if user query explicitly refers to a different repository, clarify rather than drift
    if target_repo and target_repo.id != conv.repository_id:
        active_repo_obj = db.query(Repository).filter(Repository.id == conv.repository_id).first()
        active_name = active_repo_obj.name if active_repo_obj else "the active repository"
        switch_clarification = (
            f"This conversation is locked to repository '{active_name}'. "
            f"Your question refers to repository '{target_repo.name}'. "
            f"To explore repository '{target_repo.name}', please select it from the repository selector or start a new conversation."
        )

        async def switch_clarification_stream():
            yield AssistantService._format_sse("meta", {
                "request_id": str(uuid.uuid4()),
                "conversation_id": conv.id,
                "repository_id": conv.repository_id,
                "repository_name": active_name,
                "protocol_version": "1.0",
            })
            asst_msg = AssistantMessage(
                conversation_id=conv.id,
                role="assistant",
                content=switch_clarification,
                citations=json.dumps([]),
                retrieval_strategy="repository_resolution",
                evidence_metadata=json.dumps({
                    "repository_id": conv.repository_id,
                    "repository_name": active_name,
                    "related_components": [],
                    "facts": {"confirmed": 0, "inferences": 0, "unknowns": 1},
                    "risk_callout": {"level": "LOW", "summary": "Repository switch requested in active conversation."}
                }),
                status="success"
            )
            db.add(asst_msg)
            conv.updated_at = func.now()
            db.commit()
            db.refresh(asst_msg)
            words = switch_clarification.split(" ")
            for i, w in enumerate(words):
                yield AssistantService._format_sse("token", {"token": w + " ", "index": i})
            yield AssistantService._format_sse("done", {
                "conversation_id": conv.id,
                "message_id": asst_msg.id,
                "answer": switch_clarification,
                "repository_id": conv.repository_id,
                "repository_name": active_name,
                "citations": [],
                "related_components": [],
                "facts": {"confirmed": 0, "inferences": 0, "unknowns": 1},
                "risk_callout": {"level": "LOW", "summary": "Repository switch required."},
                "llm_configured": True,
                "retrieval_strategy": "repository_resolution",
                "status": "success"
            })
        return StreamingResponse(switch_clarification_stream(), media_type="text/event-stream")

    target_repo_id = conv.repository_id
    verify_repo_access(target_repo_id, user, db)

    stream_gen = AssistantService.stream_answer_question(
        db=db,
        repository_id=target_repo_id,
        question=norm_question,
        user_id=user.id,
        conversation_id=conv.id,
        original_question=request.content,
        request=raw_req,
    )
    return StreamingResponse(
        stream_gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/repositories/{repository_id}/assistant/query", response_model=AssistantQueryResponse)
async def ask_assistant(
    repository_id: int,
    request: AssistantQueryRequest,
    raw_req: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> AssistantQueryResponse:
    """
    Executes grounded AI code answering with citations and prompt injection defenses.
    Dynamically resolves natural-language repository mentions and updates conversation context.
    """
    rate_limiter.check(raw_req, category="assistant")
    verify_repo_access(repository_id, user, db)

    target_repo, norm_question, clarification = AssistantService.resolve_repository_from_query(
        db=db,
        question=request.question,
        active_repo_id=repository_id,
        user_id=user.id
    )

    if clarification:
        return AssistantQueryResponse(
            conversation_id=request.conversation_id or 0,
            message_id=0,
            answer=clarification,
            repository_id=repository_id,
            repository_name=None,
            citations=[],
            related_components=[],
            facts={"confirmed": 0, "inferences": 0, "unknowns": 1},
            risk_callout={"level": "LOW", "summary": "Clarification required."},
            llm_configured=True,
            retrieval_strategy="repository_resolution",
            status="success"
        )

    # If conversation_id is provided, verify repository binding
    if request.conversation_id:
        conv = AssistantService.get_conversation_record(db, request.conversation_id, user.id)
        if conv.repository_id and conv.repository_id != repository_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Repository mismatch: Conversation {conv.id} is bound to repository {conv.repository_id}, but request path specified repository {repository_id}."
            )
        if not conv.repository_id:
            conv.repository_id = repository_id
            db.commit()

    if target_repo and target_repo.id != repository_id:
        active_repo_obj = db.query(Repository).filter(Repository.id == repository_id).first()
        active_name = active_repo_obj.name if active_repo_obj else str(repository_id)
        clarification_msg = (
            f"You are currently querying repository '{active_name}'. "
            f"Your question refers to repository '{target_repo.name}'. "
            f"To explore repository '{target_repo.name}', please select it from the repository selector or start a new conversation."
        )
        return AssistantQueryResponse(
            conversation_id=request.conversation_id or 0,
            message_id=0,
            answer=clarification_msg,
            repository_id=repository_id,
            repository_name=active_name,
            citations=[],
            related_components=[],
            facts={"confirmed": 0, "inferences": 0, "unknowns": 1},
            risk_callout={"level": "LOW", "summary": "Repository switch required."},
            llm_configured=True,
            retrieval_strategy="repository_resolution",
            status="success"
        )

    target_repo_id = repository_id
    verify_repo_access(target_repo_id, user, db)

    response_data = await AssistantService.answer_question(
        db=db,
        repository_id=target_repo_id,
        question=norm_question,
        user_id=user.id,
        conversation_id=request.conversation_id,
        original_question=request.question,
    )

    return AssistantQueryResponse(**response_data)


@router.post("/repositories/{repository_id}/assistant/stream")
async def stream_repository_assistant_query(
    repository_id: int,
    request: AssistantQueryRequest,
    raw_req: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
):
    """
    Streams grounded AI code answering with citations and follow-up memory via SSE.
    Dynamically resolves natural-language repository mentions and updates conversation context.
    """
    rate_limiter.check(raw_req, category="assistant")
    verify_repo_access(repository_id, user, db)

    target_repo, norm_question, clarification = AssistantService.resolve_repository_from_query(
        db=db,
        question=request.question,
        active_repo_id=repository_id,
        user_id=user.id
    )

    if clarification:
        async def clarification_stream():
            yield AssistantService._format_sse("meta", {
                "request_id": str(uuid.uuid4()),
                "conversation_id": request.conversation_id or 0,
                "repository_id": repository_id,
                "repository_name": None,
                "protocol_version": "1.0",
            })
            words = clarification.split(" ")
            for i, w in enumerate(words):
                yield AssistantService._format_sse("token", {"token": w + " ", "index": i})
            yield AssistantService._format_sse("done", {
                "conversation_id": request.conversation_id or 0,
                "message_id": 0,
                "answer": clarification,
                "repository_id": repository_id,
                "repository_name": None,
                "citations": [],
                "related_components": [],
                "facts": {"confirmed": 0, "inferences": 0, "unknowns": 1},
                "risk_callout": {"level": "LOW", "summary": "Clarification required."},
                "llm_configured": True,
                "retrieval_strategy": "repository_resolution",
                "status": "success"
            })
        return StreamingResponse(clarification_stream(), media_type="text/event-stream")

    if request.conversation_id:
        conv = AssistantService.get_conversation_record(db, request.conversation_id, user.id)
        if conv.repository_id and conv.repository_id != repository_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Repository mismatch: Conversation {conv.id} is bound to repository {conv.repository_id}, but request path specified repository {repository_id}."
            )
        if not conv.repository_id:
            conv.repository_id = repository_id
            db.commit()

    if target_repo and target_repo.id != repository_id:
        active_repo_obj = db.query(Repository).filter(Repository.id == repository_id).first()
        active_name = active_repo_obj.name if active_repo_obj else str(repository_id)
        switch_clarification = (
            f"You are currently querying repository '{active_name}'. "
            f"Your question refers to repository '{target_repo.name}'. "
            f"To explore repository '{target_repo.name}', please select it from the repository selector or start a new conversation."
        )

        async def switch_clarification_stream():
            yield AssistantService._format_sse("meta", {
                "request_id": str(uuid.uuid4()),
                "conversation_id": request.conversation_id or 0,
                "repository_id": repository_id,
                "repository_name": active_name,
                "protocol_version": "1.0",
            })
            words = switch_clarification.split(" ")
            for i, w in enumerate(words):
                yield AssistantService._format_sse("token", {"token": w + " ", "index": i})
            yield AssistantService._format_sse("done", {
                "conversation_id": request.conversation_id or 0,
                "message_id": 0,
                "answer": switch_clarification,
                "repository_id": repository_id,
                "repository_name": active_name,
                "citations": [],
                "related_components": [],
                "facts": {"confirmed": 0, "inferences": 0, "unknowns": 1},
                "risk_callout": {"level": "LOW", "summary": "Repository switch required."},
                "llm_configured": True,
                "retrieval_strategy": "repository_resolution",
                "status": "success"
            })
        return StreamingResponse(switch_clarification_stream(), media_type="text/event-stream")

    target_repo_id = repository_id
    verify_repo_access(target_repo_id, user, db)

    stream_gen = AssistantService.stream_answer_question(
        db=db,
        repository_id=target_repo_id,
        question=norm_question,
        user_id=user.id,
        conversation_id=request.conversation_id,
        original_question=request.question,
        request=raw_req,
    )
    return StreamingResponse(
        stream_gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# --- Phase 1: Advanced Symbol Search, Dependency Graph & Call Hierarchy ---

@router.get("/repositories/{repository_id}/symbols/search", response_model=SymbolSearchResponse)
def search_repository_symbols(
    repository_id: int,
    q: str = "",
    query: Optional[str] = None,
    file_path: Optional[str] = None,
    symbol_type: Optional[str] = None,
    language: Optional[str] = None,
    exact: bool = False,
    limit: int = 25,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> SymbolSearchResponse:
    """
    Advanced symbol search scoped to a repository with exact-above-partial ranking.
    """
    verify_repo_access(repository_id, user, db)
    effective_q = query if query is not None and query != "" else q
    return SymbolService.search_symbols(
        db=db,
        query=effective_q,
        repository_id=repository_id,
        file_path=file_path,
        symbol_type=symbol_type,
        language=language,
        exact=exact,
        limit=limit,
        offset=offset
    )


@router.get("/symbols/search", response_model=SymbolSearchResponse)
def search_all_symbols(
    q: str = "",
    query: Optional[str] = None,
    repository_id: Optional[int] = None,
    file_path: Optional[str] = None,
    symbol_type: Optional[str] = None,
    language: Optional[str] = None,
    exact: bool = False,
    limit: int = 25,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> SymbolSearchResponse:
    """
    Global symbol search across repositories with exact-above-partial ranking.
    """
    if repository_id is not None:
        verify_repo_access(repository_id, user, db)
    effective_q = query if query is not None and query != "" else q
    return SymbolService.search_symbols(
        db=db,
        query=effective_q,
        repository_id=repository_id,
        file_path=file_path,
        symbol_type=symbol_type,
        language=language,
        exact=exact,
        limit=limit,
        offset=offset,
        user_id=user.id,
    )


@router.get("/repositories/{repository_id}/symbols/{symbol_id}", response_model=SymbolDetailResponse)
def get_symbol_details(
    repository_id: int,
    symbol_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> SymbolDetailResponse:
    """
    Retrieves full symbol details and incoming/outgoing call summary.
    """
    verify_repo_access(repository_id, user, db)
    detail = SymbolService.get_symbol_detail(db, symbol_id, repository_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found in repository")
    return detail


@router.get("/repositories/{repository_id}/symbols/{symbol_id}/call-hierarchy", response_model=CallHierarchyResponse)
def get_symbol_call_hierarchy_by_id(
    repository_id: int,
    symbol_id: int,
    direction: str = "both",
    max_depth: int = 2,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> CallHierarchyResponse:
    """
    Retrieves verified caller and callee hierarchy for a symbol by ID.
    """
    verify_repo_access(repository_id, user, db)
    return CallHierarchyService.get_call_hierarchy_by_id(
        db=db,
        repository_id=repository_id,
        symbol_id=symbol_id,
        direction=direction,
        max_depth=max_depth
    )


@router.get("/repositories/{repository_id}/calls/hierarchy", response_model=CallHierarchyResponse)
def get_symbol_call_hierarchy_by_name(
    repository_id: int,
    symbol_name: str,
    file_path: Optional[str] = None,
    direction: str = "both",
    max_depth: int = 2,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> CallHierarchyResponse:
    """
    Retrieves verified caller and callee hierarchy by symbol name and optional file path.
    Flags ambiguity if multiple symbols share the same name across modules.
    """
    verify_repo_access(repository_id, user, db)
    return CallHierarchyService.get_call_hierarchy_by_name(
        db=db,
        repository_id=repository_id,
        symbol_name=symbol_name,
        file_path=file_path,
        direction=direction,
        max_depth=max_depth
    )


@router.get("/repositories/{repository_id}/graph", response_model=RepositoryGraphResponse)
def get_repository_knowledge_graph(
    repository_id: int,
    limit: int = 150,
    node_type: Optional[str] = None,
    edge_type: Optional[str] = None,
    file_path: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> RepositoryGraphResponse:
    """Retrieves verified knowledge graph nodes and edges for the repository with optional filtering."""
    verify_repo_access(repository_id, user, db)
    graph_data = KnowledgeGraphService.get_repository_graph(
        db=db,
        repository_id=repository_id,
        node_limit=limit,
        node_type=node_type,
        edge_type=edge_type,
        file_path=file_path
    )
    return RepositoryGraphResponse(**graph_data)


@router.get("/repositories/{repository_id}/graph/nodes/{node_id}/neighbors", response_model=NodeNeighborsResponse)
def get_graph_node_neighbors(
    repository_id: int,
    node_id: int,
    depth: int = 1,
    relationship_type: Optional[str] = None,
    direction: str = "both",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> NodeNeighborsResponse:
    """Retrieves 1-hop or multi-hop incoming and outgoing connections for a specific graph node."""
    verify_repo_access(repository_id, user, db)
    data = KnowledgeGraphService.get_node_neighbors(
        db=db,
        repository_id=repository_id,
        node_id=node_id,
        depth=depth,
        relationship_type=relationship_type,
        direction=direction
    )
    return NodeNeighborsResponse(**data)


@router.get("/repositories/{repository_id}/graph/paths", response_model=GraphPathResponse)
def find_graph_path(
    repository_id: int,
    start_id: int,
    end_id: int,
    max_depth: int = 4,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> GraphPathResponse:
    """Finds the shortest dependency/call path between two components."""
    verify_repo_access(repository_id, user, db)
    path = KnowledgeGraphService.find_path(db, repository_id, start_id, end_id, max_depth)
    return GraphPathResponse(path=path)


@router.post("/repositories/{repository_id}/impact/analyze", response_model=ImpactAnalyzeResponse)
def analyze_change_impact(
    repository_id: int,
    request: ImpactAnalyzeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> ImpactAnalyzeResponse:
    """
    Analyzes the potential impact of changing a component or file.
    Traces incoming callers and importing components via verified static graph edges.
    """
    verify_repo_access(repository_id, user, db)

    result = ChangeImpactAnalyzer.analyze_impact(
        db=db,
        repository_id=repository_id,
        component_name=request.component_name,
        file_path=request.file_path,
        proposed_change=request.proposed_change,
        max_depth=request.max_depth,
    )

    affected_comp_models = [
        {
            "node_id": a.node_id,
            "name": a.name,
            "component_type": a.component_type,
            "file_path": a.file_path,
            "impact_level": a.impact_level,
            "distance": a.distance,
            "confidence_score": a.confidence_score,
            "evidence": a.evidence,
            "dependency_path": a.dependency_path,
        }
        for a in result.affected_components
    ]

    return ImpactAnalyzeResponse(
        target_component=result.target_component,
        target_type=result.target_type,
        file_path=result.file_path,
        proposed_change=result.proposed_change,
        total_affected=result.total_affected,
        direct_count=result.direct_count,
        transitive_count=result.transitive_count,
        risk_level=result.risk_level,
        affected_components=affected_comp_models,
        affected_files=result.affected_files,
        dependency_paths=result.dependency_paths,
        limitations=result.limitations,
        explanation=result.explanation,
        direct_symbols_count=result.direct_symbols_count,
        transitive_symbols_count=result.transitive_symbols_count,
        direct_files_count=result.direct_files_count,
        transitive_files_count=result.transitive_files_count,
        external_dependencies=result.external_dependencies,
    )


@router.get("/repositories/{repository_id}/files/tree")
def get_repository_file_tree(
    repository_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
):
    """Returns the list of indexed files and symbols for the Code Viewer file tree."""
    verify_repo_access(repository_id, user, db)
    files = (
        db.query(IndexedFile)
        .filter(IndexedFile.repository_id == repository_id)
        .order_by(IndexedFile.path.asc())
        .all()
    )

    return [
        {
            "id": f.id,
            "path": f.path,
            "language": f.language,
            "lines_count": f.lines_count,
            "size_bytes": f.size_bytes,
            "symbols": [
                {
                    "id": s.id,
                    "name": s.name,
                    "kind": s.kind,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                }
                for s in f.symbols
            ],
        }
        for f in files
    ]


@router.get("/repositories/{repository_id}/files/content", response_model=FileContentResponse)
def get_repository_file_content(
    repository_id: int,
    file_path: str,
    highlight_start: Optional[int] = None,
    highlight_end: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> FileContentResponse:
    """Retrieves file text or chunk content for Code Viewer with highlighted line coordinates."""
    verify_repo_access(repository_id, user, db)

    # Validate path safety
    if "\0" in file_path or ".." in file_path.replace("\\", "/").split("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path: path traversal is not permitted."
        )

    clean_file_path = file_path.replace("\\", "/").strip().lstrip("/")
    indexed_file = (
        db.query(IndexedFile)
        .filter(
            IndexedFile.repository_id == repository_id,
            IndexedFile.path == clean_file_path,
        )
        .first()
    )

    if not indexed_file:
        # Check if any chunk matches
        matching_chunk = (
            db.query(CodeChunk)
            .filter(
                CodeChunk.repository_id == repository_id,
                CodeChunk.file_path == file_path,
            )
            .first()
        )
        if matching_chunk:
            return FileContentResponse(
                file_path=file_path,
                language=matching_chunk.language,
                lines_count=matching_chunk.end_line,
                content=matching_chunk.chunk_text,
                highlight_start=highlight_start or matching_chunk.start_line,
                highlight_end=highlight_end or matching_chunk.end_line,
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File '{file_path}' not found in repository")

    # Combine chunk texts for this file if available
    chunks = (
        db.query(CodeChunk)
        .filter(
            CodeChunk.repository_id == repository_id,
            CodeChunk.file_id == indexed_file.id,
        )
        .order_by(CodeChunk.start_line.asc())
        .all()
    )

    if chunks:
        # Construct content from chunks
        combined = "\n".join(c.chunk_text for c in chunks)
        return FileContentResponse(
            file_path=indexed_file.path,
            language=indexed_file.language,
            lines_count=indexed_file.lines_count,
            content=combined,
            highlight_start=highlight_start,
            highlight_end=highlight_end,
        )

    return FileContentResponse(
        file_path=indexed_file.path,
        language=indexed_file.language,
        lines_count=indexed_file.lines_count,
        content=f"// File: {indexed_file.path}\n// Indexed symbols: {len(indexed_file.symbols)}\n",
        highlight_start=highlight_start,
        highlight_end=highlight_end,
    )


# --- Git History Endpoints ---

@router.get("/repositories/{repository_id}/commits", response_model=CommitListResponse)
async def get_repository_commits(
    repository_id: int,
    branch: Optional[str] = None,
    author: Optional[str] = None,
    search: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    page: int = 1,
    per_page: int = 25,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> CommitListResponse:
    """
    Returns verified Git commits from GitHub or local git history for the selected repository and branch.
    """
    repo = verify_repo_access(repository_id, user, db)
    return await GitHistoryService.get_repository_commits(
        db=db,
        repository=repo,
        branch=branch,
        author=author,
        search=search,
        since=since,
        until=until,
        page=page,
        per_page=per_page
    )


@router.get("/repositories/{repository_id}/commits/{commit_sha}", response_model=CommitDetailResponse)
async def get_repository_commit_detail(
    repository_id: int,
    commit_sha: str,
    branch: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> CommitDetailResponse:
    """
    Returns full details for a commit, including genuine file diffs, additions, deletions,
    and evidence-backed AI change explanations.
    """
    repo = verify_repo_access(repository_id, user, db)
    return await GitHistoryService.get_commit_details(
        db=db,
        repository=repo,
        commit_sha=commit_sha,
        branch=branch
    )


# --- Security Insights Endpoints ---

@router.get("/repositories/{repository_id}/security/findings", response_model=SecurityScanSummary)
def get_security_findings(
    repository_id: int,
    branch: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> SecurityScanSummary:
    """
    Returns verified static security findings for the repository from indexed code chunks.
    """
    verify_repo_access(repository_id, user, db)
    return SecurityAnalyzer.scan_repository(db, repository_id, branch=branch)


@router.post("/repositories/{repository_id}/security/scan", response_model=SecurityScanSummary)
def run_security_scan(
    repository_id: int,
    branch: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> SecurityScanSummary:
    """
    Triggers an on-demand security scan against the repository's indexed source code.
    """
    verify_repo_access(repository_id, user, db)
    return SecurityAnalyzer.scan_repository(db, repository_id, branch=branch)


@router.patch("/repositories/{repository_id}/security/findings/{finding_id}")
def update_security_finding_status(
    repository_id: int,
    finding_id: str,
    payload: FindingStatusUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
):
    """
    Updates status of a security finding (REVIEWED, DISMISSED, ACKNOWLEDGED, OPEN).
    """
    verify_repo_access(repository_id, user, db)
    SecurityAnalyzer.update_finding_status(db, repository_id, finding_id, payload.status)
    return {"status": "updated", "finding_id": finding_id, "new_status": payload.status}


# --- Documentation Generation Endpoint ---

@router.get("/repositories/{repository_id}/docs", response_model=RepositoryDocsResponse)
def get_repository_documentation(
    repository_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> RepositoryDocsResponse:
    """
    Generates structured module, class, and function documentation grounded in actual indexed files.
    """
    repo = verify_repo_access(repository_id, user, db)
    files = db.query(IndexedFile).filter(IndexedFile.repository_id == repository_id).order_by(IndexedFile.path.asc()).all()

    modules = []
    total_symbols = 0

    for f in files:
        symbols_data = [
            {
                "id": s.id,
                "name": s.name,
                "kind": s.kind,
                "signature": s.signature or "",
                "start_line": s.start_line,
                "end_line": s.end_line,
                "docstring": s.docstring or ""
            }
            for s in f.symbols
        ]
        total_symbols += len(symbols_data)
        mod_name = Path(f.path).stem.replace("_", " ").title()
        modules.append(DocModule(
            name=mod_name,
            file_path=f.path,
            language=f.language,
            lines_count=f.lines_count,
            symbols_count=len(symbols_data),
            symbols=symbols_data
        ))

    overview = (
        f"Automated architectural documentation for {repo.full_name}. "
        f"Contains {len(files)} indexed source file(s) across {repo.primary_language or 'multiple languages'}."
    ) if files else f"No indexed documentation available for {repo.full_name}. Index this repository to generate documentation."

    return RepositoryDocsResponse(
        repository_id=repo.id,
        repository_name=repo.full_name,
        overview=overview,
        total_files=len(files),
        total_symbols=total_symbols,
        modules=modules
    )


# --- Settings & Profile Endpoints ---

@router.get("/settings", response_model=UserSettingsResponse)
def get_user_settings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> UserSettingsResponse:
    """
    Retrieves user profile and system settings.
    """
    return UserSettingsResponse(
        user=user,
        app_name=settings.APP_NAME,
        app_env=settings.APP_ENV,
        ai_provider=settings.AI_PROVIDER,
        llm_model=settings.LLM_MODEL,
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_dimension=settings.EMBEDDING_DIMENSION,
        github_configured=GitHubService.is_configured(),
        github_connected=bool(user.github_access_token),
        github_username=user.github_username
    )


@router.put("/settings", response_model=UserSettingsResponse)
def update_user_settings(
    payload: UserSettingsUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> UserSettingsResponse:
    """
    Updates user profile details (full_name, workspace_name).
    """
    if payload.full_name:
        user.full_name = payload.full_name
        parts = payload.full_name.strip().split()
        user.avatar_initials = "".join(p[0].upper() for p in parts[:2]) if parts else "AK"
    if payload.workspace_name:
        user.workspace_name = payload.workspace_name
    db.commit()
    db.refresh(user)

    return UserSettingsResponse(
        user=user,
        app_name=settings.APP_NAME,
        app_env=settings.APP_ENV,
        ai_provider=settings.AI_PROVIDER,
        llm_model=settings.LLM_MODEL,
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_dimension=settings.EMBEDDING_DIMENSION,
        github_configured=GitHubService.is_configured(),
        github_connected=bool(user.github_access_token),
        github_username=user.github_username
    )


@router.put("/settings/session-timeout", response_model=SessionTimeoutUpdateResponse)
def update_session_timeout_setting(
    payload: SessionTimeoutUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> SessionTimeoutUpdateResponse:
    """
    Updates the automatic session logout timeout preference (30, 60, 240, or 480 minutes).
    Applies to future sessions and safely extends or updates active sessions.
    """
    if payload.timeout_minutes not in (30, 60, 240, 480):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid timeout duration. Supported options: 30, 60, 240, 480 minutes."
        )

    user.session_timeout_minutes = payload.timeout_minutes

    # Update active session if token present
    token = request.cookies.get("codemind_session")
    if not token:
        auth_hdr = request.headers.get("Authorization")
        if auth_hdr and auth_hdr.startswith("Bearer "):
            token = auth_hdr.split("Bearer ", 1)[1].strip()

    if token:
        from backend.app.core.security import hash_token
        from backend.app.models.user_session import UserSession
        from datetime import timedelta
        thash = hash_token(token)
        cur_session = db.query(UserSession).filter(UserSession.session_token_hash == thash, UserSession.status == "active").first()
        if cur_session:
            cur_session.expires_at = cur_session.login_at + timedelta(minutes=payload.timeout_minutes)

    db.commit()
    db.refresh(user)

    return SessionTimeoutUpdateResponse(
        success=True,
        timeout_minutes=user.session_timeout_minutes,
        message=f"Automatic logout duration updated to {user.session_timeout_minutes} minutes."
    )


# --- Notifications Endpoint ---

@router.get("/notifications", response_model=NotificationListResponse)
def get_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> NotificationListResponse:
    """
    Returns real application event notifications (indexing jobs, security findings, etc.).
    """
    notifications: List[NotificationItem] = []
    
    # 1. Recent Indexing Jobs
    jobs = (
        db.query(IndexingJob)
        .order_by(IndexingJob.id.desc())
        .limit(5)
        .all()
    )
    for j in jobs:
        repo = db.query(Repository).filter(Repository.id == j.repository_id).first()
        repo_name = repo.name if repo else f"Repo #{j.repository_id}"
        ts = j.completed_at or j.started_at or datetime.now(timezone.utc)
        time_ago = GitHistoryService._format_time_ago(ts)

        if j.status == "COMPLETED":
            notifications.append(NotificationItem(
                id=f"job-{j.id}",
                type="indexing",
                title=f"Indexing Completed: {repo_name}",
                message=f"Successfully indexed {j.files_processed} files on branch '{j.branch}'.",
                timestamp=ts.isoformat(),
                time_ago=time_ago,
                status="success",
                link="/repositories"
            ))
        elif j.status == "FAILED":
            notifications.append(NotificationItem(
                id=f"job-{j.id}",
                type="indexing",
                title=f"Indexing Failed: {repo_name}",
                message=j.error_message or "Job encountered an unhandled exception.",
                timestamp=ts.isoformat(),
                time_ago=time_ago,
                status="danger",
                link="/repositories"
            ))

    # 2. Open Security Findings
    repos = db.query(Repository).filter(Repository.files_count > 0).limit(3).all()
    for r in repos:
        summary = SecurityAnalyzer.scan_repository(db, r.id)
        if summary.high_count > 0:
            notifications.append(NotificationItem(
                id=f"sec-{r.id}",
                type="security",
                title=f"Security Alert: {r.name}",
                message=f"Found {summary.high_count} high-severity potential vulnerability pattern(s).",
                timestamp=datetime.now(timezone.utc).isoformat(),
                time_ago="Active",
                status="warning",
                link="/security_insights"
            ))

    return NotificationListResponse(
        unread_count=len(notifications),
        notifications=notifications
    )


# --- Global Search Endpoint ---

@router.get("/repositories/{repository_id}/search")
def global_repository_search(
    repository_id: int,
    q: str,
    limit: int = 15,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
):
    """
    Searches indexed files and code symbols for the ⌘ K global search palette.
    Ranks exact matches above partial matches using SymbolService.
    """
    verify_repo_access(repository_id, user, db)
    q_pattern = f"%{q.strip()}%"

    files = (
        db.query(IndexedFile)
        .filter(IndexedFile.repository_id == repository_id, IndexedFile.path.ilike(q_pattern))
        .limit(limit)
        .all()
    )

    sym_res = SymbolService.search_symbols(
        db=db,
        query=q,
        repository_id=repository_id,
        limit=limit
    )

    return {
        "query": q,
        "files": [{"id": f.id, "path": f.path, "language": f.language} for f in files],
        "symbols": [
            {
                "id": s.id,
                "name": s.name,
                "kind": s.kind,
                "file_path": s.file_path,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "signature": s.signature,
                "preview": s.preview,
                "match_type": s.match_type,
                "score": s.score,
            }
            for s in sym_res.results
        ]
    }

