import logging
from datetime import datetime, timezone, timedelta
import re
from typing import Optional, Tuple, List
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.models.user_session import UserSession
from backend.app.schemas.auth import UserRegisterRequest, UserLoginRequest, AuthResponse, LogoutResponse
from backend.app.schemas.session import (
    SessionRead,
    SessionListResponse,
    SessionRevokeResponse,
    RevokeOthersResponse,
    SessionTimeoutUpdateRequest,
    SessionTimeoutUpdateResponse
)
from backend.app.schemas.user import UserRead
from backend.app.core.security import (
    hash_password,
    verify_password,
    validate_password_strength,
    create_session_token,
    verify_session_token,
    revoke_session_token,
    hash_token,
    create_user_session_record,
    revoke_user_session,
    revoke_token_record,
    validate_and_track_session
)
from backend.app.core.config import settings
from backend.app.core.rate_limiter import rate_limiter

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

SESSION_COOKIE_NAME = "codemind_session"


def get_current_user_and_session(
    request: Request,
    db: Session = Depends(get_db),
    codemind_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
) -> Tuple[User, Optional[UserSession], str]:
    """
    Extracts and strictly validates the session token from cookie or Authorization header.
    Rejects missing, expired, revoked, or invalid tokens with HTTP 401.
    Never falls back to arbitrary or first active database users.
    Returns (User, UserSession, token_str).
    """
    if request.headers.get("x-require-auth") == "true" and not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in."
        )

    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif codemind_session:
        token = codemind_session

    if not token:
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

    return user, session_rec, token


def get_authenticated_user(
    current_data: Tuple[User, Optional[UserSession], str] = Depends(get_current_user_and_session)
) -> User:
    """Dependency that returns the authenticated User."""
    return current_data[0]


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    request: Request,
    payload: UserRegisterRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Registers a new account.
    Hashes password with PBKDF2-SHA256, validates criteria, creates user record,
    generates secure session token, and records persistent session.
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
        session_timeout_minutes=30,
        is_active=True
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as db_err:
        db.rollback()
        logger.error(f"Database error during user registration persistence: {db_err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist user registration in database. Please try again."
        )

    # 5. Create secure session token and persistent session record
    try:
        timeout_mins = user.session_timeout_minutes or 30
        token = create_session_token(user.id, timeout_minutes=timeout_mins)
        create_user_session_record(db, user, token, request=request, initial_path="/dashboard")
    except Exception as sess_err:
        logger.warning(f"Failed to record initial user session during registration: {sess_err}")
        token = create_session_token(user.id, timeout_minutes=30)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=timeout_mins * 60,
        httponly=True,
        samesite="lax",
        secure=settings.is_cookie_secure
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
    Authenticates user credentials, generates cryptographically signed session token,
    creates persistent active session history record, and sets secure HttpOnly cookie.
    """
    rate_limiter.check(request, category="auth")
    email_clean = payload.email.strip().lower()
    try:
        user = db.query(User).filter(User.email == email_clean, User.is_active == True).first()
    except SQLAlchemyError as exc:
        logger.error("Database error during user authentication query: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable. Please try again later."
        )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )

    # In production, accounts without password must not allow spontaneous setup
    if not user.hashed_password:
        if settings.APP_ENV == "production":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account requires a password. Please sign up or contact administrator."
            )
        if payload.password and len(payload.password) >= 6:
            user.hashed_password = hash_password(payload.password)
            try:
                db.commit()
                db.refresh(user)
            except SQLAlchemyError as exc:
                logger.error("Database error updating password during login: %s", exc)
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Authentication service is temporarily unavailable. Please try again later."
                )
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

    timeout_mins = getattr(user, "session_timeout_minutes", 30) or 30
    token = create_session_token(user.id, timeout_minutes=timeout_mins)
    try:
        create_user_session_record(db, user, token, request=request, initial_path="/dashboard")
    except SQLAlchemyError as exc:
        logger.error("Database error creating user session record: %s", exc)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable. Please try again later."
        )

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=timeout_mins * 60,
        httponly=True,
        samesite="lax",
        secure=settings.is_cookie_secure
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
    db: Session = Depends(get_db),
    codemind_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """
    Securely terminates the active session:
    1. Revokes the session token and updates database status to 'logged_out'.
    2. Clears the authentication cookie using compatible path and security settings.
    3. Handles repeated logout attempts idempotently without error.
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif codemind_session:
        token = codemind_session

    if token:
        revoke_token_record(db, token, reason="logged_out")
    if codemind_session and codemind_session != token:
        revoke_token_record(db, codemind_session, reason="logged_out")

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.is_cookie_secure
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


# ==========================================
# Active Sessions Management Endpoints
# ==========================================

@router.get("/sessions", response_model=SessionListResponse)
def list_user_sessions(
    current_data: Tuple[User, Optional[UserSession], str] = Depends(get_current_user_and_session),
    db: Session = Depends(get_db)
):
    """
    Lists session history for the current authenticated user.
    Enforces user isolation: only the user's own sessions are returned.
    Identifies the active session corresponding to the current request.
    """
    user, current_session, current_token = current_data
    current_hash = hash_token(current_token)

    sessions_query = (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id)
        .order_by(UserSession.last_activity_at.desc())
        .limit(50)
        .all()
    )

    now_utc = datetime.now(timezone.utc)
    results: List[SessionRead] = []
    current_session_id = current_session.id if current_session else None

    for s in sessions_query:
        exp = s.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)

        status_val = s.status
        if status_val == "active" and now_utc >= exp:
            status_val = "expired"
            s.status = "expired"
            try:
                db.commit()
            except Exception:
                db.rollback()

        is_current = (s.session_token_hash == current_hash)
        if is_current:
            current_session_id = s.id

        results.append(
            SessionRead(
                id=s.id,
                user_id=s.user_id,
                user_email=user.email,
                user_name=user.full_name,
                device_label=s.device_label,
                browser=s.browser,
                os=s.os,
                ip_address=s.ip_address,
                login_at=s.login_at,
                last_activity_at=s.last_activity_at,
                expires_at=s.expires_at,
                logout_at=s.logout_at,
                last_accessed_path=s.last_accessed_path,
                status=status_val,
                is_current=is_current,
                created_at=s.created_at,
                updated_at=s.updated_at
            )
        )

    return SessionListResponse(
        sessions=results,
        total_count=len(results),
        current_session_id=current_session_id
    )


@router.get("/sessions/current", response_model=SessionRead)
def get_current_session_details(
    current_data: Tuple[User, Optional[UserSession], str] = Depends(get_current_user_and_session),
    db: Session = Depends(get_db)
):
    """
    Returns details of the currently active session.
    """
    user, current_session, current_token = current_data
    if not current_session:
        current_hash = hash_token(current_token)
        current_session = db.query(UserSession).filter(UserSession.session_token_hash == current_hash).first()
        if not current_session:
            raise HTTPException(status_code=404, detail="Current session record not found.")

    return SessionRead(
        id=current_session.id,
        user_id=user.id,
        user_email=user.email,
        user_name=user.full_name,
        device_label=current_session.device_label,
        browser=current_session.browser,
        os=current_session.os,
        ip_address=current_session.ip_address,
        login_at=current_session.login_at,
        last_activity_at=current_session.last_activity_at,
        expires_at=current_session.expires_at,
        logout_at=current_session.logout_at,
        last_accessed_path=current_session.last_accessed_path,
        status=current_session.status,
        is_current=True,
        created_at=current_session.created_at,
        updated_at=current_session.updated_at
    )


@router.delete("/sessions/{session_id}", response_model=SessionRevokeResponse)
def revoke_session(
    session_id: int,
    response: Response,
    current_data: Tuple[User, Optional[UserSession], str] = Depends(get_current_user_and_session),
    db: Session = Depends(get_db)
):
    """
    Revokes an active session.
    Enforces authorization: users can only revoke their own sessions.
    If the current session is revoked, clears the authentication cookie.
    """
    user, current_session, current_token = current_data
    target = db.query(UserSession).filter(UserSession.id == session_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Session record not found.")

    # Authorization boundary: User cannot revoke other users' sessions
    if target.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to revoke this session.")

    is_current = (target.session_token_hash == hash_token(current_token))
    revoke_user_session(db, target, reason="revoked")

    if is_current:
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            path="/",
            httponly=True,
            samesite="lax",
            secure=not settings.DEBUG
        )
        return SessionRevokeResponse(
            success=True,
            message="Your current session was revoked. Please sign in again.",
            is_current=True
        )

    return SessionRevokeResponse(
        success=True,
        message="Session revoked successfully.",
        is_current=False
    )


@router.post("/sessions/revoke-others", response_model=RevokeOthersResponse)
def revoke_other_sessions(
    current_data: Tuple[User, Optional[UserSession], str] = Depends(get_current_user_and_session),
    db: Session = Depends(get_db)
):
    """
    Revokes all active sessions for the current user except the current session.
    """
    user, current_session, current_token = current_data
    current_hash = hash_token(current_token)

    other_sessions = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == user.id,
            UserSession.session_token_hash != current_hash,
            UserSession.status == "active"
        )
        .all()
    )

    now_utc = datetime.now(timezone.utc)
    revoked_count = 0

    for s in other_sessions:
        s.status = "revoked"
        s.logout_at = now_utc
        # Register in-memory
        revoke_session_token(s.session_token_hash)
        revoked_count += 1

    db.commit()

    return RevokeOthersResponse(
        success=True,
        revoked_count=revoked_count,
        message=f"Successfully revoked {revoked_count} other active session(s)."
    )


@router.put("/session-timeout", response_model=SessionTimeoutUpdateResponse)
def update_auth_session_timeout(
    payload: SessionTimeoutUpdateRequest,
    request: Request,
    current_data: Tuple[User, Optional[UserSession], str] = Depends(get_current_user_and_session),
    db: Session = Depends(get_db)
):
    """
    Updates the session timeout preference (30, 60, 240, or 480 minutes).
    Persists setting in database and applies to current session.
    """
    if payload.timeout_minutes not in (30, 60, 240, 480):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid timeout duration. Supported options: 30, 60, 240, 480 minutes."
        )

    user, current_session, current_token = current_data
    user.session_timeout_minutes = payload.timeout_minutes

    if current_session and current_session.status == "active":
        current_session.expires_at = current_session.login_at + timedelta(minutes=payload.timeout_minutes)

    db.commit()
    db.refresh(user)

    return SessionTimeoutUpdateResponse(
        success=True,
        timeout_minutes=user.session_timeout_minutes,
        message=f"Automatic logout duration updated to {user.session_timeout_minutes} minutes."
    )
