import logging
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.user_github_account import UserGitHubAccount
from backend.app.schemas.github import (
    GitHubAuthStatusResponse,
    GitHubLoginResponse,
    GitHubRepositoryItem,
    GitHubPersonalAccessTokenRequest,
    GitHubConnectedAccountResponse,
    GitHubAccountListResponse,
    GitHubDisconnectResponse,
)
from backend.app.integrations.github.service import GitHubService, GitHubServiceError
from backend.app.api.routes.api_v1 import get_current_user_record

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth/github", tags=["GitHub Authentication"])


@router.get("/status", response_model=GitHubAuthStatusResponse)
def get_github_auth_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> GitHubAuthStatusResponse:
    """
    Returns the real GitHub connection status for the authenticated user,
    including all connected accounts (OAuth & Personal Access Tokens).
    Never exposes raw tokens or encryption keys.
    """
    is_configured = GitHubService.is_configured()

    # Query all active connected accounts for this user
    accounts = db.query(UserGitHubAccount).filter(
        UserGitHubAccount.user_id == user.id,
        UserGitHubAccount.is_active == True
    ).order_by(UserGitHubAccount.id.desc()).all()

    account_responses = [
        GitHubConnectedAccountResponse(
            id=acc.id,
            user_id=acc.user_id,
            github_user_id=acc.github_user_id,
            github_username=acc.github_username,
            account_type=acc.account_type,
            auth_method=acc.auth_method,
            label=acc.label or f"@{acc.github_username} ({acc.auth_method.upper()})",
            avatar_url=acc.avatar_url,
            token_scope=acc.token_scope,
            token_type=acc.token_type,
            token_expires_at=acc.token_expires_at,
            is_active=acc.is_active,
            created_at=acc.created_at,
            updated_at=acc.updated_at
        )
        for acc in accounts
    ]

    is_connected = len(accounts) > 0 or bool(user.github_access_token)
    primary_username = accounts[0].github_username if accounts else user.github_username
    primary_avatar = accounts[0].avatar_url if accounts else None

    return GitHubAuthStatusResponse(
        configured=is_configured,
        connected=is_connected,
        username=primary_username,
        avatar_url=primary_avatar,
        connected_accounts_count=len(accounts),
        accounts=account_responses
    )


@router.get("/accounts", response_model=GitHubAccountListResponse)
def list_connected_github_accounts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> GitHubAccountListResponse:
    """
    Lists all connected GitHub accounts for the authenticated user.
    Enforces user isolation: users can only see their own accounts.
    Never exposes plaintext tokens, encryption keys, or nonces.
    """
    accounts = db.query(UserGitHubAccount).filter(
        UserGitHubAccount.user_id == user.id,
        UserGitHubAccount.is_active == True
    ).order_by(UserGitHubAccount.id.desc()).all()

    results = [
        GitHubConnectedAccountResponse(
            id=acc.id,
            user_id=acc.user_id,
            github_user_id=acc.github_user_id,
            github_username=acc.github_username,
            account_type=acc.account_type,
            auth_method=acc.auth_method,
            label=acc.label or f"@{acc.github_username} ({acc.auth_method.upper()})",
            avatar_url=acc.avatar_url,
            token_scope=acc.token_scope,
            token_type=acc.token_type,
            token_expires_at=acc.token_expires_at,
            is_active=acc.is_active,
            created_at=acc.created_at,
            updated_at=acc.updated_at
        )
        for acc in accounts
    ]

    return GitHubAccountListResponse(
        accounts=results,
        total_count=len(results)
    )


@router.post("/pat", response_model=GitHubConnectedAccountResponse, status_code=status.HTTP_201_CREATED)
async def connect_github_personal_access_token(
    payload: GitHubPersonalAccessTokenRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> GitHubConnectedAccountResponse:
    """
    Connects a GitHub account via Personal Access Token (classic or fine-grained).
    1. Validates the token against GitHub API to ensure it is authentic and active.
    2. Encrypts the token with AES-256-GCM before persisting.
    3. Never returns or logs the raw token.
    """
    raw_token = payload.personal_access_token.strip() if payload.personal_access_token else ""
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Personal Access Token cannot be empty."
        )

    # 1. Server-side validation with GitHub API
    try:
        profile = await GitHubService.validate_personal_access_token(raw_token)
    except GitHubServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as exc:
        logger.error(f"Error validating GitHub Personal Access Token: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to reach GitHub to validate Personal Access Token. Please check your network and try again."
        )

    # 2. Check if this GitHub username is already connected for this user
    gh_username = profile.get("github_username") or profile.get("login") or "github-user"
    gh_user_id = profile.get("github_user_id") or str(profile.get("id") or "")
    account_type = profile.get("account_type") or profile.get("type", "User")

    existing_account = db.query(UserGitHubAccount).filter(
        UserGitHubAccount.user_id == user.id,
        UserGitHubAccount.github_username == gh_username,
        UserGitHubAccount.auth_method == "pat"
    ).first()

    label = payload.label.strip() if payload.label else f"@{gh_username} (PAT)"

    if existing_account:
        # Update existing record with re-encrypted token
        existing_account.set_encrypted_token(raw_token)
        existing_account.github_user_id = gh_user_id
        existing_account.account_type = account_type
        existing_account.avatar_url = profile.get("avatar_url")
        existing_account.token_scope = profile.get("scopes") or profile.get("token_scope")
        existing_account.label = label
        existing_account.is_active = True
        existing_account.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing_account)
        target_account = existing_account
    else:
        # Create new encrypted account record
        target_account = UserGitHubAccount(
            user_id=user.id,
            github_user_id=gh_user_id,
            github_username=gh_username,
            account_type=account_type,
            auth_method="pat",
            label=label,
            avatar_url=profile.get("avatar_url"),
            token_type="bearer",
            token_scope=profile.get("scopes") or profile.get("token_scope"),
            is_active=True
        )
        target_account.set_encrypted_token(raw_token)
        db.add(target_account)
        db.commit()
        db.refresh(target_account)

    # Update User model primary account fields if not already populated
    if not user.github_username:
        user.github_username = gh_username
        user.github_user_id = profile["github_user_id"]
        db.commit()

    return GitHubConnectedAccountResponse(
        id=target_account.id,
        user_id=target_account.user_id,
        github_user_id=target_account.github_user_id,
        github_username=target_account.github_username,
        account_type=target_account.account_type,
        auth_method=target_account.auth_method,
        label=target_account.label,
        avatar_url=target_account.avatar_url,
        token_scope=target_account.token_scope,
        token_type=target_account.token_type,
        token_expires_at=target_account.token_expires_at,
        is_active=target_account.is_active,
        created_at=target_account.created_at,
        updated_at=target_account.updated_at
    )


@router.get("/accounts/{account_id}/repositories", response_model=List[GitHubRepositoryItem])
async def list_repositories_for_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> List[GitHubRepositoryItem]:
    """
    Lists repositories accessible to a specific connected GitHub account.
    Enforces authorization: users can only list repositories from their own connected accounts.
    Decrypts the token securely on the backend; never exposes it to frontend.
    """
    account = db.query(UserGitHubAccount).filter(
        UserGitHubAccount.id == account_id,
        UserGitHubAccount.user_id == user.id,
        UserGitHubAccount.is_active == True
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connected GitHub account not found or access denied."
        )

    try:
        decrypted_token = account.get_decrypted_token()
    except Exception as e:
        logger.error(f"Decryption failed for account {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to decrypt GitHub credential. Please re-authenticate this account."
        )

    try:
        repos = await GitHubService.list_authorized_repositories(decrypted_token)
    except GitHubServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    # Identify existing repositories in CodeMind DB
    existing_repos = {r.full_name for r in db.query(Repository.full_name).all()}

    results = []
    for r in repos:
        results.append(GitHubRepositoryItem(
            id=r["id"],
            name=r["name"],
            full_name=r["full_name"],
            description=r.get("description"),
            is_private=r.get("is_private") if "is_private" in r else r.get("private", False),
            default_branch=r.get("default_branch", "main"),
            html_url=r.get("html_url"),
            primary_language=r.get("primary_language"),
            is_connected=(r["full_name"] in existing_repos),
            connected_account_id=account.id
        ))
    return results


@router.delete("/accounts/{account_id}", response_model=GitHubDisconnectResponse)
async def disconnect_github_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> GitHubDisconnectResponse:
    """
    Safely disconnects a connected GitHub account and removes its encrypted credentials.
    Enforces authorization: users can only disconnect their own accounts.
    Attempts remote revocation when supported.
    Preserves indexed repositories by nulling connected_account_id.
    """
    account = db.query(UserGitHubAccount).filter(
        UserGitHubAccount.id == account_id,
        UserGitHubAccount.user_id == user.id
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connected GitHub account not found."
        )

    # 1. Attempt remote revocation if OAuth
    revoke_result = await GitHubService.revoke_github_credential(account)

    # 2. Null out connected_account_id on linked repositories to preserve repository history
    db.query(Repository).filter(
        Repository.connected_account_id == account.id
    ).update({"connected_account_id": None})

    # 3. Delete account record
    db.delete(account)
    db.commit()

    # If this was the user's only account, clear user-level fields
    remaining = db.query(UserGitHubAccount).filter(UserGitHubAccount.user_id == user.id).count()
    if remaining == 0:
        user.github_access_token = None
        user.github_username = None
        user.github_user_id = None
        user.github_token_type = None
        user.github_scope = None
        db.commit()

    return GitHubDisconnectResponse(
        status="disconnected",
        message=revoke_result.get("message", f"Account @{account.github_username} disconnected successfully."),
        revoked_remotely=revoke_result.get("revoked", False)
    )


@router.get("/login", response_model=GitHubLoginResponse)
def initiate_github_login(
    db: Session = Depends(get_db),
    redirect: bool = Query(False, description="If True, returns HTTP 302 redirect directly")
):
    """Initiates GitHub OAuth flow with CSRF state validation."""
    if not GitHubService.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub integration is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in backend/.env"
        )

    try:
        auth_url, state = GitHubService.create_oauth_authorization_url(db)
        if redirect:
            return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
        return GitHubLoginResponse(authorization_url=auth_url, state=state)
    except GitHubServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/callback")
async def github_oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
):
    """
    Handles GitHub OAuth callback.
    Validates CSRF state, exchanges code for access token, encrypts with AES-256-GCM,
    and stores securely in user_github_accounts.
    """
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub authorization error: {error_description or error}"
        )

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth code or state parameter"
        )

    # 1. CSRF State validation
    is_valid_state = GitHubService.validate_csrf_state(db, state)
    if not is_valid_state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired CSRF state parameter. Authorization aborted."
        )

    # 2. Token Exchange
    try:
        token_data = await GitHubService.exchange_code_for_token(code)
    except GitHubServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    access_token = token_data["access_token"]

    # 3. Fetch User Profile from GitHub
    try:
        profile = await GitHubService.fetch_user_profile(access_token)
    except GitHubServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    gh_username = profile.get("login")
    gh_uid = str(profile.get("id"))

    # 4. Check for existing connected account for this user
    existing_acc = db.query(UserGitHubAccount).filter(
        UserGitHubAccount.user_id == user.id,
        UserGitHubAccount.github_username == gh_username
    ).first()

    if existing_acc:
        existing_acc.set_encrypted_token(access_token)
        existing_acc.auth_method = "oauth"
        existing_acc.github_user_id = gh_uid
        existing_acc.account_type = profile.get("type", "User")
        existing_acc.avatar_url = profile.get("avatar_url")
        existing_acc.token_scope = token_data.get("scope")
        existing_acc.token_type = token_data.get("token_type", "bearer")
        existing_acc.is_active = True
        existing_acc.updated_at = datetime.now(timezone.utc)
    else:
        new_acc = UserGitHubAccount(
            user_id=user.id,
            github_user_id=gh_uid,
            github_username=gh_username,
            account_type=profile.get("type", "User"),
            auth_method="oauth",
            label=f"@{gh_username} (OAuth)",
            avatar_url=profile.get("avatar_url"),
            token_type=token_data.get("token_type", "bearer"),
            token_scope=token_data.get("scope"),
            is_active=True
        )
        new_acc.set_encrypted_token(access_token)
        db.add(new_acc)

    # Maintain user record for legacy compatibility
    user.github_username = gh_username
    user.github_user_id = gh_uid
    user.github_token_type = token_data.get("token_type")
    user.github_scope = token_data.get("scope")
    db.commit()

    return RedirectResponse(url="/repositories?github_connected=1", status_code=status.HTTP_302_FOUND)


@router.get("/repositories", response_model=List[GitHubRepositoryItem])
async def list_authorized_github_repositories(
    account_id: Optional[int] = Query(None, description="Optional account ID to list repos for"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> List[GitHubRepositoryItem]:
    """
    Queries GitHub API for repositories the authenticated user is authorized to access.
    If account_id is specified, lists repositories for that account.
    Otherwise queries using the user's primary connected account.
    """
    account = None
    if account_id:
        account = db.query(UserGitHubAccount).filter(
            UserGitHubAccount.id == account_id,
            UserGitHubAccount.user_id == user.id,
            UserGitHubAccount.is_active == True
        ).first()
        if not account:
            raise HTTPException(status_code=404, detail="Specified GitHub account not found or access denied.")
    else:
        account = db.query(UserGitHubAccount).filter(
            UserGitHubAccount.user_id == user.id,
            UserGitHubAccount.is_active == True
        ).order_by(UserGitHubAccount.id.desc()).first()

    raw_token = None
    if account:
        try:
            raw_token = account.get_decrypted_token()
        except Exception as e:
            logger.error(f"Decryption failed for account {account.id}: {e}")
            raise HTTPException(status_code=401, detail="Failed to decrypt GitHub credential. Please re-authenticate.")
    elif user.github_access_token:
        raw_token = user.github_access_token

    if not raw_token:
        return []

    try:
        repos = await GitHubService.list_authorized_repositories(raw_token)
    except GitHubServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    existing_repos = {r.full_name for r in db.query(Repository.full_name).all()}

    results = []
    for r in repos:
        results.append(GitHubRepositoryItem(
            id=r["id"],
            name=r["name"],
            full_name=r["full_name"],
            description=r.get("description"),
            is_private=r.get("is_private", False),
            default_branch=r.get("default_branch", "main"),
            html_url=r.get("html_url"),
            primary_language=r.get("primary_language"),
            is_connected=(r["full_name"] in existing_repos),
            connected_account_id=account.id if account else None
        ))
    return results


@router.post("/disconnect")
def disconnect_github(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
):
    """
    Safely disconnects all GitHub accounts for the user and clears stored credentials.
    Preserves indexed repository data according to repository data deletion policy.
    """
    # Null out connected_account_id on repositories
    account_ids = [a.id for a in db.query(UserGitHubAccount.id).filter(UserGitHubAccount.user_id == user.id).all()]
    if account_ids:
        db.query(Repository).filter(Repository.connected_account_id.in_(account_ids)).update(
            {"connected_account_id": None}, synchronize_session=False
        )
        db.query(UserGitHubAccount).filter(UserGitHubAccount.user_id == user.id).delete(synchronize_session=False)

    user.github_access_token = None
    user.github_username = None
    user.github_user_id = None
    user.github_token_type = None
    user.github_scope = None
    db.commit()
    return {"status": "disconnected", "message": "GitHub account(s) successfully disconnected"}
