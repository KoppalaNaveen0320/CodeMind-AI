"""
CodeMind AI - AES-256-GCM Token Encryption Module
Provides authenticated symmetric encryption for GitHub OAuth tokens and Personal Access Tokens.
Tokens are encrypted at rest with a 256-bit key and verified with an authentication tag.
"""

import base64
import os
import secrets
from typing import Dict, Optional, Tuple, Any
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.core.config import settings


class TokenEncryptionError(Exception):
    """Raised when token encryption fails."""
    pass


class TokenDecryptionError(TokenEncryptionError):
    """Raised when token decryption fails (tampered ciphertext, invalid tag, wrong key)."""
    pass


class InvalidEncryptionKeyError(TokenEncryptionError):
    """Raised when the configured encryption key is missing or invalid."""
    pass


class TokenEncryptionService:
    """
    AES-256-GCM authenticated encryption service for sensitive GitHub credentials.
    """
    DEFAULT_KEY_VERSION = 1
    NONCE_SIZE_BYTES = 12  # Standard 96-bit nonce for AES-GCM
    KEY_SIZE_BYTES = 32    # 256-bit key

    @classmethod
    def generate_key_b64(cls) -> str:
        """
        Generates a cryptographically secure 256-bit key encoded as URL-safe base64.
        Can be used via CLI or scripts to populate GITHUB_TOKEN_ENCRYPTION_KEY.
        """
        raw_key = AESGCM.generate_key(bit_length=256)
        return base64.urlsafe_b64encode(raw_key).decode("utf-8")

    @classmethod
    def get_configured_key_bytes(cls, explicit_key: Optional[Any] = None) -> bytes:
        """
        Retrieves and validates the 256-bit key from environment/settings or explicit override.
        Accepts 32-byte raw bytes, 32-byte string, 64-character hex string, or base64 string.
        Fails safely if missing or invalid.
        """
        if explicit_key is not None:
            if isinstance(explicit_key, bytes):
                if len(explicit_key) == cls.KEY_SIZE_BYTES:
                    return explicit_key
                raise InvalidEncryptionKeyError(f"Invalid key length: expected {cls.KEY_SIZE_BYTES} bytes, got {len(explicit_key)}.")
            key_val = explicit_key
        else:
            key_val = getattr(settings, "GITHUB_TOKEN_ENCRYPTION_KEY", None) or os.environ.get("GITHUB_TOKEN_ENCRYPTION_KEY")

        if not key_val:
            raise InvalidEncryptionKeyError(
                "GITHUB_TOKEN_ENCRYPTION_KEY is not configured. "
                "Set a valid 256-bit key in environment variables or secret manager."
            )

        if isinstance(key_val, bytes):
            if len(key_val) == cls.KEY_SIZE_BYTES:
                return key_val
            raise InvalidEncryptionKeyError(f"Invalid key length: expected {cls.KEY_SIZE_BYTES} bytes, got {len(key_val)}.")

        key_str = key_val.strip()

        # Try base64 urlsafe decode
        try:
            padded = key_str + "=" * ((4 - len(key_str) % 4) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
            if len(decoded) == cls.KEY_SIZE_BYTES:
                return decoded
        except Exception:
            pass

        # Try standard base64 decode
        try:
            padded = key_str + "=" * ((4 - len(key_str) % 4) % 4)
            decoded = base64.b64decode(padded.encode("utf-8"))
            if len(decoded) == cls.KEY_SIZE_BYTES:
                return decoded
        except Exception:
            pass

        # Try hex decode
        try:
            if len(key_str) == 64:
                decoded = bytes.fromhex(key_str)
                if len(decoded) == cls.KEY_SIZE_BYTES:
                    return decoded
        except Exception:
            pass

        # Try raw 32-byte string
        raw_bytes = key_str.encode("utf-8")
        if len(raw_bytes) == cls.KEY_SIZE_BYTES:
            return raw_bytes

        raise InvalidEncryptionKeyError(
            f"Invalid GITHUB_TOKEN_ENCRYPTION_KEY length ({len(key_str)} chars). "
            f"Must be a 32-byte key (base64-encoded, 64-char hex, or 32 raw bytes)."
        )

    @classmethod
    def encrypt_token(
        cls,
        plain_token: str,
        key: Optional[Any] = None,
        key_bytes: Optional[Any] = None,
        key_version: int = DEFAULT_KEY_VERSION,
        associated_data: Optional[bytes] = None
    ) -> Dict[str, Any]:
        """
        Encrypts a plaintext token using AES-256-GCM.
        Returns a dictionary containing:
        - encrypted_token: base64 ciphertext (including GCM tag)
        - nonce: base64 nonce (12 bytes)
        - tag: base64 authentication tag (last 16 bytes of AESGCM output)
        - key_version: integer key version for rotation tracking
        """
        if not plain_token:
            raise TokenEncryptionError("Cannot encrypt empty token.")

        k_bytes = cls.get_configured_key_bytes(explicit_key=key if key is not None else key_bytes)
        nonce = secrets.token_bytes(cls.NONCE_SIZE_BYTES)

        try:
            aesgcm = AESGCM(k_bytes)
            # AESGCM.encrypt appends 16-byte authentication tag to ciphertext
            ct_and_tag = aesgcm.encrypt(nonce, plain_token.encode("utf-8"), associated_data)
            
            ciphertext = ct_and_tag[:-16]
            tag = ct_and_tag[-16:]

            return {
                "encrypted_token": base64.b64encode(ct_and_tag).decode("utf-8"),
                "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
                "nonce": base64.b64encode(nonce).decode("utf-8"),
                "tag": base64.b64encode(tag).decode("utf-8"),
                "key_version": key_version
            }
        except Exception as e:
            raise TokenEncryptionError(f"Failed to encrypt GitHub token: {e}") from e

    @classmethod
    def decrypt_token(
        cls,
        encrypted_token_b64: str,
        nonce_b64: Optional[str] = None,
        tag_b64: Optional[str] = None,
        key: Optional[Any] = None,
        key_bytes: Optional[Any] = None,
        associated_data: Optional[bytes] = None
    ) -> str:
        """
        Decrypts an encrypted token using AES-256-GCM.
        Validates authentication tag and integrity.
        Fails safely if corrupted, tampered, wrong key, or invalid nonce.
        """
        if not encrypted_token_b64:
            raise TokenDecryptionError("Cannot decrypt empty token payload.")

        k_bytes = cls.get_configured_key_bytes(explicit_key=key if key is not None else key_bytes)

        try:
            ct_and_tag = base64.b64decode(encrypted_token_b64)
            if len(ct_and_tag) < 16:
                raise TokenDecryptionError("Ciphertext payload is too short to contain a valid authentication tag.")

            if nonce_b64:
                nonce = base64.b64decode(nonce_b64)
            else:
                # If nonce wasn't passed separately, cannot decrypt securely
                raise TokenDecryptionError("Missing nonce for AES-256-GCM decryption.")

            if len(nonce) != cls.NONCE_SIZE_BYTES:
                raise TokenDecryptionError(f"Invalid nonce length: expected {cls.NONCE_SIZE_BYTES} bytes, got {len(nonce)}.")

            if tag_b64:
                expected_tag = base64.b64decode(tag_b64)
                if ct_and_tag[-16:] != expected_tag:
                    raise TokenDecryptionError("Decryption failed: authentication tag mismatch.")

            aesgcm = AESGCM(k_bytes)
            decrypted_bytes = aesgcm.decrypt(nonce, ct_and_tag, associated_data)
            return decrypted_bytes.decode("utf-8")
        except TokenDecryptionError:
            raise
        except Exception as e:
            raise TokenDecryptionError("Decryption failed: invalid key, corrupted ciphertext, or authentication tag mismatch.") from e

    @classmethod
    def rotate_token_encryption(
        cls,
        encrypted_token_b64: str,
        nonce_b64: str,
        tag_b64: Optional[str] = None,
        old_key: Optional[Any] = None,
        new_key: Optional[Any] = None,
        old_key_bytes: Optional[Any] = None,
        new_key_bytes: Optional[Any] = None,
        new_key_version: int = DEFAULT_KEY_VERSION
    ) -> Dict[str, Any]:
        """
        Decrypts with old key and re-encrypts with new key for key rotation.
        """
        resolved_old = old_key if old_key is not None else old_key_bytes
        resolved_new = new_key if new_key is not None else new_key_bytes
        plain = cls.decrypt_token(encrypted_token_b64, nonce_b64=nonce_b64, tag_b64=tag_b64, key=resolved_old)
        return cls.encrypt_token(plain, key=resolved_new, key_version=new_key_version)


generate_key_b64 = TokenEncryptionService.generate_key_b64
