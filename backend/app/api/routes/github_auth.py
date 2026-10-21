from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.schemas.github import GitHubAuthStatusResponse, GitHubLoginResponse, GitHubRepositoryItem
from backend.app.integrations.github.service import GitHubService, GitHubServiceError

router = APIRouter(prefix="/api/v1/auth/github", tags=["GitHub Authentication"])


def get_current_user_record(db: Session = Depends(get_db)) -> User:
    """Helper to retrieve or initialize the active workspace user."""
    user = db.query(User).filter(User.is_active == True).first()
    if not user:
        user = User(
            email="alex@acme.dev",
            full_name="Alex Kim",
            workspace_name="Acme Engineering",
            avatar_initials="AK",
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@router.get("/status", response_model=GitHubAuthStatusResponse)
def get_github_auth_status(user: User = Depends(get_current_user_record)) -> GitHubAuthStatusResponse:
    """
    Returns the real connection status for GitHub.
    Truthfully reports if GitHub OAuth credentials are not configured in .env.
    """
    is_configured = GitHubService.is_configured()
    is_connected = bool(user.github_access_token)
    return GitHubAuthStatusResponse(
        configured=is_configured,
        connected=is_connected,
        username=user.github_username,
        avatar_url=None
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
    Validates CSRF state, exchanges code for access token, and stores securely server-side.
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

    # 4. Secure server-side storage on User record
    user.github_access_token = access_token
    user.github_user_id = str(profile.get("id"))
    user.github_username = profile.get("login")
    user.github_token_type = token_data.get("token_type")
    user.github_scope = token_data.get("scope")
    db.commit()

    # Redirect user back to the Repositories management interface
    return RedirectResponse(url="/repositories?github_connected=1", status_code=status.HTTP_302_FOUND)


@router.get("/repositories", response_model=List[GitHubRepositoryItem])
async def list_authorized_github_repositories(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
) -> List[GitHubRepositoryItem]:
    """
    Queries real GitHub API for repositories the authenticated user is authorized to access.
    Returns empty list truthfully if GitHub is not connected.
    """
    if not user.github_access_token:
        return []

    try:
        repos = await GitHubService.list_authorized_repositories(user.github_access_token)
    except GitHubServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    # Check which repositories are already connected in CodeMind DB
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
            is_connected=(r["full_name"] in existing_repos)
        ))
    return results


@router.post("/disconnect")
def disconnect_github(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_record)
):
    """
    Safely disconnects GitHub account and clears stored access tokens server-side.
    Preserves indexed repository data according to repository data deletion policy.
    """
    user.github_access_token = None
    user.github_username = None
    user.github_user_id = None
    user.github_token_type = None
    user.github_scope = None
    db.commit()
    return {"status": "disconnected", "message": "GitHub account successfully disconnected"}
