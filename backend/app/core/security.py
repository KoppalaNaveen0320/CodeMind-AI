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

_revoked_tokens: dict[str, float] = {}
_revocation_lock = threading.Lock()


def _token_identifier(token: str) -> str:
    """Computes a deterministic hash identifier for a session token."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


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
    Checks if a token has been revoked.
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


def create_session_token(user_id: int) -> str:
    """
    Generates a cryptographically signed URL-safe session token with timestamp and user ID.
    Format: base64(payload).signature
    """
    payload = {
        "uid": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + SESSION_MAX_AGE_SECONDS,
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
