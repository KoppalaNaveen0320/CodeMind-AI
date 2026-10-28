import base64
import hashlib
import hmac
import json
import secrets
import time
import re
from typing import Optional, Tuple
from backend.app.core.config import settings

PBKDF2_ITERATIONS = 600000
SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 days


def validate_password_strength(password: str) -> Tuple[bool, Optional[str]]:
    """
    Validates that a password satisfies all five core requirements:
    1. Minimum 8 characters.
    2. At least one uppercase letter (A-Z).
    3. At least one lowercase letter (a-z).
    4. At least one number (0-9).
    5. At least one special character (!@#$%^&* etc.).

    Returns (True, None) on success, or (False, error_message) on failure.
    """
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter (A-Z)."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter (a-z)."
    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one number (0-9)."
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", password):
        return False, "Password must contain at least one special character (e.g. !@#$%^&*)."
    return True, None


def hash_password(password: str) -> str:
    """
    Hashes a password using PBKDF2-HMAC-SHA256 with a 16-byte random salt and 600,000 iterations.
    Conforms to NIST SP 800-63B guidelines.
    """
    if not password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plain-text password against a stored PBKDF2 hash using constant-time comparison.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        parts = hashed_password.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = parts[2]
        expected_hex = parts[3]

        computed = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations
        )
        return secrets.compare_digest(computed.hex(), expected_hex)
    except Exception:
        return False


import threading
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

_revoked_tokens: dict[str, float] = {}
_revocation_lock = threading.Lock()


def _token_identifier(token: str) -> str:
    """Computes a deterministic hash identifier for a session token."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def hash_token(token: str) -> str:
    """Public helper for computing deterministic SHA-256 session token hash."""
    return _token_identifier(token)


hash_session_token = hash_token


def revoke_session_token(token: str) -> bool:
    """
    Revokes a session token immediately so it cannot be reused.
    Extracts the token's expiration timestamp to keep the in-memory revocation blocklist bounded.
    """
    if not token or not isinstance(token, str):
        return False
    try:
        ident = _token_identifier(token)
        exp = time.time() + SESSION_MAX_AGE_SECONDS
        if "." in token:
            try:
                b64_payload = token.split(".", 1)[0]
                padding = 4 - (len(b64_payload) % 4)
                if padding < 4:
                    b64_payload += "=" * padding
                raw_payload = base64.urlsafe_b64decode(b64_payload.encode('utf-8'))
                data = json.loads(raw_payload.decode('utf-8'))
                exp = float(data.get("exp", exp))
            except Exception:
                pass

        now = time.time()
        with _revocation_lock:
            if len(_revoked_tokens) > 500:
                expired_keys = [k for k, v in _revoked_tokens.items() if v <= now]
                for k in expired_keys:
                    _revoked_tokens.pop(k, None)
            _revoked_tokens[ident] = exp
        return True
    except Exception:
        return False


def is_token_revoked(token: str) -> bool:
    """
    Checks if a token has been revoked in the in-memory cache.
    """
    if not token or not isinstance(token, str):
        return False
    ident = _token_identifier(token)
    with _revocation_lock:
        exp = _revoked_tokens.get(ident)
        if exp is None:
            return False
        if exp < time.time():
            _revoked_tokens.pop(ident, None)
            return False
        return True


def clear_revoked_tokens_for_testing() -> None:
    """Helper for testing to reset revocation registry."""
    with _revocation_lock:
        _revoked_tokens.clear()


def create_session_token(user_id: int, timeout_minutes: int = 30) -> str:
    """
    Generates a cryptographically signed URL-safe session token with timestamp and user ID.
    Timeout defaults to 30 minutes.
    Format: base64(payload).signature
    """
    now = int(time.time())
    ttl = int(timeout_minutes * 60) if timeout_minutes and timeout_minutes > 0 else 1800
    payload = {
        "uid": user_id,
        "iat": now,
        "exp": now + ttl,
        "nonce": secrets.token_hex(8)
    }
    raw_payload = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    b64_payload = base64.urlsafe_b64encode(raw_payload).decode('utf-8').rstrip('=')
    
    sig = hmac.new(
        settings.SECRET_KEY.encode('utf-8'),
        b64_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return f"{b64_payload}.{sig}"


def verify_session_token(token: str) -> Optional[int]:
    """
    Verifies a signed session token. Returns user_id if valid, not expired, and not revoked, else None.
    """
    if not token or "." not in token:
        return None
    if is_token_revoked(token):
        return None
    try:
        b64_payload, signature = token.split(".", 1)
        
        expected_sig = hmac.new(
            settings.SECRET_KEY.encode('utf-8'),
            b64_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        if not secrets.compare_digest(signature, expected_sig):
            return None
        
        # Pad base64 if needed
        padding = 4 - (len(b64_payload) % 4)
        if padding < 4:
            b64_payload += "=" * padding
            
        raw_payload = base64.urlsafe_b64decode(b64_payload.encode('utf-8'))
        data = json.loads(raw_payload.decode('utf-8'))
        
        # Check expiry
        if data.get("exp", 0) < time.time():
            return None
        
        return data.get("uid")
    except Exception:
        return None


def parse_client_device_and_ip(request: Optional[object]) -> Tuple[str, str, str, str]:
    """
    Extracts client IP address safely (respecting trusted proxies) and parses user-agent
    into safe, human-readable device, browser, and OS metadata.
    Returns (device_label, browser, os, ip_address).
    """
    if request is None:
        return "Unknown Device", "Unknown Browser", "Unknown OS", "127.0.0.1"

    # 1. Safe IP Extraction
    client_host = getattr(getattr(request, "client", None), "host", "127.0.0.1")
    trusted_proxies = {"127.0.0.1", "::1", "localhost", "testclient"}
    ip_address = client_host

    headers = getattr(request, "headers", {})
    if client_host in trusted_proxies:
        xfwd = headers.get("x-forwarded-for")
        xreal = headers.get("x-real-ip")
        if xfwd:
            # Take leftmost client IP
            first_ip = xfwd.split(",")[0].strip()
            if first_ip:
                ip_address = first_ip
        elif xreal:
            ip_address = xreal.strip()

    # 2. User-Agent Parsing
    ua = headers.get("user-agent", "")
    browser = "Unknown Browser"
    os_name = "Unknown OS"

    if ua:
        # Detect Browser
        if "Brave" in ua or "brave" in ua.lower():
            browser = "Brave"
        elif "Edg/" in ua:
            match = re.search(r"Edg/([0-9.]+)", ua)
            browser = f"Edge {match.group(1).split('.')[0]}" if match else "Edge"
        elif "OPR/" in ua or "Opera" in ua:
            match = re.search(r"OPR/([0-9.]+)", ua)
            browser = f"Opera {match.group(1).split('.')[0]}" if match else "Opera"
        elif "Chrome/" in ua:
            match = re.search(r"Chrome/([0-9.]+)", ua)
            browser = f"Chrome {match.group(1).split('.')[0]}" if match else "Chrome"
        elif "Firefox/" in ua:
            match = re.search(r"Firefox/([0-9.]+)", ua)
            browser = f"Firefox {match.group(1).split('.')[0]}" if match else "Firefox"
        elif "Safari/" in ua and "Chrome" not in ua:
            match = re.search(r"Version/([0-9.]+)", ua)
            browser = f"Safari {match.group(1).split('.')[0]}" if match else "Safari"
        elif "curl" in ua.lower() or "python" in ua.lower() or "http" in ua.lower():
            browser = "API Client"

        # Detect OS
        if "Windows NT 10.0" in ua or "Windows NT 11.0" in ua:
            os_name = "Windows"
        elif "Windows" in ua:
            os_name = "Windows"
        elif "Macintosh" in ua or "Mac OS X" in ua:
            os_name = "macOS"
        elif "Android" in ua:
            os_name = "Android"
        elif "iPhone" in ua or "iPad" in ua:
            os_name = "iOS"
        elif "Linux" in ua:
            os_name = "Linux"

    if browser != "Unknown Browser" and os_name != "Unknown OS":
        device_label = f"{browser} on {os_name}"
    elif browser != "Unknown Browser":
        device_label = browser
    elif os_name != "Unknown OS":
        device_label = f"Device on {os_name}"
    else:
        device_label = "Web Browser"

    return device_label, browser, os_name, ip_address


def sanitize_accessed_path(path: str) -> str:
    """
    Sanitizes URL path to avoid storing query parameters, secrets, or tokens in session history.
    """
    if not path:
        return "/dashboard"
    try:
        parsed = urlparse(path)
        clean = parsed.path
        if not clean.startswith("/"):
            clean = f"/{clean}"
        return clean[:255]
    except Exception:
        return "/dashboard"


def create_user_session_record(
    db: object,
    user: object,
    token: str,
    request: Optional[object] = None,
    initial_path: str = "/dashboard"
) -> object:
    """
    Persists a new active UserSession record in the database upon login.
    """
    from backend.app.models.user_session import UserSession

    token_hash = hash_token(token)
    device_label, browser, os_name, ip_address = parse_client_device_and_ip(request)
    now_utc = datetime.now(timezone.utc)
    
    timeout_mins = getattr(user, "session_timeout_minutes", 30) or 30
    expires_at = now_utc + timedelta(minutes=timeout_mins)

    session_record = UserSession(
        user_id=user.id,
        session_token_hash=token_hash,
        device_label=device_label,
        browser=browser,
        os=os_name,
        ip_address=ip_address,
        login_at=now_utc,
        last_activity_at=now_utc,
        expires_at=expires_at,
        last_accessed_path=sanitize_accessed_path(initial_path),
        status="active"
    )
    db.add(session_record)
    db.commit()
    db.refresh(session_record)
    return session_record


def revoke_user_session(db: object, session_record: object, reason: str = "revoked") -> None:
    """
    Revokes an active UserSession in the database and registers in the in-memory revocation cache.
    """
    if not session_record:
        return
    session_record.status = reason
    session_record.logout_at = datetime.now(timezone.utc)
    
    # Register token hash in in-memory revocation cache
    with _revocation_lock:
        exp = time.time() + SESSION_MAX_AGE_SECONDS
        _revoked_tokens[session_record.session_token_hash] = exp
        
    db.commit()


def revoke_token_record(db: object, token: str, reason: str = "logged_out") -> None:
    """
    Revokes a session by its token: sets status in DB and in-memory revocation registry.
    """
    if not token:
        return
    revoke_session_token(token)
    
    from backend.app.models.user_session import UserSession
    token_hash = hash_token(token)
    session_rec = db.query(UserSession).filter(UserSession.session_token_hash == token_hash).first()
    if session_rec and session_rec.status == "active":
        session_rec.status = reason
        session_rec.logout_at = datetime.now(timezone.utc)
        db.commit()


def validate_and_track_session(
    token: str,
    db: object,
    request: Optional[object] = None,
    current_path: Optional[str] = None
) -> Tuple[Optional[object], Optional[object]]:
    """
    Validates a session token against cryptography and database session status.
    Rejects revoked, logged-out, or expired sessions.
    Updates last_activity_at and last_accessed_path safely with throttling.
    Returns (User, UserSession) or (None, None).
    """
    from backend.app.models.user import User
    from backend.app.models.user_session import UserSession

    user_id = verify_session_token(token)
    if not user_id:
        return None, None

    token_hash = hash_token(token)
    session_rec = db.query(UserSession).filter(UserSession.session_token_hash == token_hash).first()

    now_utc = datetime.now(timezone.utc)

    if session_rec:
        if session_rec.status != "active":
            return None, session_rec

        # Absolute expiration enforcement
        exp = session_rec.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)

        if now_utc >= exp:
            session_rec.status = "expired"
            with _revocation_lock:
                _revoked_tokens[token_hash] = time.time() + 3600
            try:
                db.commit()
            except Exception:
                db.rollback()
            return None, session_rec

        # Verify active user
        user = db.query(User).filter(User.id == session_rec.user_id, User.is_active == True).first()
        if not user:
            return None, session_rec

        # Track page and activity (throttled)
        clean_path = sanitize_accessed_path(current_path) if current_path else None
        should_update = False
        
        # Only track user-facing application routes, never API or static paths
        if clean_path and clean_path != session_rec.last_accessed_path and not clean_path.startswith("/api/") and not clean_path.startswith("/static/"):
            session_rec.last_accessed_path = clean_path
            should_update = True

        last_act = session_rec.last_activity_at
        if last_act.tzinfo is None:
            last_act = last_act.replace(tzinfo=timezone.utc)

        if (now_utc - last_act).total_seconds() >= 30:
            session_rec.last_activity_at = now_utc
            should_update = True

        if should_update:
            try:
                db.commit()
            except Exception:
                db.rollback()

        return user, session_rec

    # If no DB session record exists (e.g. lightweight test or newly generated token)
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        return None, None

    # Persist session record so it is tracked going forward
    try:
        session_rec = create_user_session_record(
            db, user, token, request=request, initial_path=current_path or "/dashboard"
        )
        return user, session_rec
    except Exception:
        # If DB write fails, still return user
        return user, None
