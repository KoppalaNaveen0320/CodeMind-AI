import re
from typing import Optional
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.auth import UserRegisterRequest, UserLoginRequest, AuthResponse, LogoutResponse
from backend.app.schemas.user import UserRead
from backend.app.core.security import (
    hash_password,
    verify_password,
    validate_password_strength,
    create_session_token,
    verify_session_token,
    revoke_session_token
)
from backend.app.core.config import settings
from backend.app.core.rate_limiter import rate_limiter

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

SESSION_COOKIE_NAME = "codemind_session"


def get_authenticated_user(
    request: Request,
    db: Session = Depends(get_db),
    codemind_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
) -> User:
    """
    Retrieves user from session cookie or Authorization header.
    Rejects invalid/expired tokens with HTTP 401.
    In local development without explicit auth headers, falls back gracefully to active user.
    """
    token = None
    if codemind_session:
        token = codemind_session
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()

    if token is not None:
        user_id = verify_session_token(token)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session token."
            )
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account associated with this session no longer exists or is inactive."
            )
        return user

    # Check if strict authentication is required
    require_auth = (
        getattr(settings, "REQUIRE_AUTH", False)
        or settings.APP_ENV == "production"
        or request.headers.get("x-require-auth", "").lower() == "true"
    )
    if require_auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required."
        )

    # Development / test fallback
    user = db.query(User).filter(User.is_active == True).first()
    if user:
        return user

    # Create initial dev user if database is completely empty
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


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    request: Request,
    payload: UserRegisterRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Registers a new account.
    Hashes password with PBKDF2-SHA256, prevents duplicate emails, and creates user session.
    """
    rate_limiter.check(request, category="auth")
    email_clean = payload.email.strip().lower()
    
    # 1. Check duplicate email
    existing = db.query(User).filter(User.email == email_clean).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists. Please sign in."
        )

    # 2. Validate password strength
    is_valid, err_msg = validate_password_strength(payload.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=err_msg
        )

    # 3. Derive initials
    names = payload.full_name.strip().split()
    initials = "".join([n[0].upper() for n in names[:2]]) or "U"

    # 4. Hash password
    pw_hash = hash_password(payload.password)

    user = User(
        email=email_clean,
        full_name=payload.full_name.strip(),
        workspace_name=(payload.workspace_name or "My Workspace").strip(),
        avatar_initials=initials,
        hashed_password=pw_hash,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 5. Create secure session token
    token = create_session_token(user.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=7 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=not settings.DEBUG
    )

    return AuthResponse(
        success=True,
        message="Account registered successfully.",
        user=UserRead.model_validate(user),
        token=token
    )


@router.post("/login", response_model=AuthResponse)
def login(
    request: Request,
    payload: UserLoginRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Authenticates user credentials and establishes a secure session cookie.
    """
    rate_limiter.check(request, category="auth")
    email_clean = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email_clean, User.is_active == True).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )

    # If user has no password set (e.g. created via initial dev seed or OAuth), allow initial password setup
    if not user.hashed_password:
        if payload.password and len(payload.password) >= 6:
            user.hashed_password = hash_password(payload.password)
            db.commit()
            db.refresh(user)
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account requires a password. Please sign up or contact administrator."
            )
    else:
        if not verify_password(payload.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password."
            )

    token = create_session_token(user.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=7 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=not settings.DEBUG
    )

    return AuthResponse(
        success=True,
        message="Login successful.",
        user=UserRead.model_validate(user),
        token=token
    )


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    response: Response,
    codemind_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """
    Securely terminates the active session:
    1. Revokes the session token (from cookie or Bearer header) on the server side.
    2. Clears the authentication cookie using compatible path, domain, and security settings.
    3. Handles repeated logout attempts idempotently without error.
    """
    token = None
    if codemind_session:
        token = codemind_session
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()

    if token:
        revoke_session_token(token)

    # Invalidate cookie across root path with matching security attributes
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=not settings.DEBUG
    )
    return LogoutResponse(
        success=True,
        message="Successfully signed out."
    )


@router.get("/me", response_model=UserRead)
def get_auth_me(user: User = Depends(get_authenticated_user)):
    """
    Returns the current authenticated user.
    """
    return user
