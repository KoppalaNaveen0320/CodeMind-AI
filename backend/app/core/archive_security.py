import io
import logging
import os
from pathlib import Path
import shutil
import stat
import tarfile
from typing import List, Optional, Set
import zipfile

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Defaults for archive extraction safety boundaries
DEFAULT_MAX_FILE_COUNT = 5000
DEFAULT_MAX_EXTRACTED_BYTES = 250 * 1024 * 1024  # 250 MB uncompressed limit
DEFAULT_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024    # 100 MB compressed upload limit
DEFAULT_MAX_SINGLE_FILE_BYTES = 10 * 1024 * 1024 # 10 MB per file limit


class ArchiveSecurityError(Exception):
    """Raised when an archive fails security checks or violates extraction limits."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def validate_path_safety(base_dir: Path, relative_name: str) -> Path:
    """
    Validates that resolving relative_name against base_dir stays strictly
    inside base_dir and does not escape via traversal, symlinks, or absolute paths.
    """
    clean_name = relative_name.replace("\\", "/").strip()
    if clean_name.startswith("/") or clean_name.startswith("\\"):
        raise ArchiveSecurityError(f"Archive entry '{relative_name}' has an absolute path.", 400)

    # Check for traversal components
    parts = Path(clean_name).parts
    if any(p == ".." for p in parts):
        raise ArchiveSecurityError(f"Archive entry '{relative_name}' contains illegal path traversal.", 400)

    resolved_base = base_dir.resolve()
    target_path = (resolved_base / clean_name).resolve()

    try:
        if not target_path.is_relative_to(resolved_base):
            raise ArchiveSecurityError(
                f"Archive entry '{relative_name}' resolves outside extraction root.",
                400
            )
    except AttributeError:
        # Fallback for Python versions where is_relative_to is not available
        if not str(target_path).startswith(str(resolved_base)):
            raise ArchiveSecurityError(
                f"Archive entry '{relative_name}' resolves outside extraction root.",
                400
            )

    return target_path


def is_zip_member_symlink(member: zipfile.ZipInfo) -> bool:
    """
    Detects if a ZIP entry is a symbolic link using UNIX file attribute bits.
    """
    mode = member.external_attr >> 16
    return stat.S_ISLNK(mode) != 0


def extract_zip_safely(
    zip_bytes_or_file: io.BytesIO | Path | str,
    target_dir: Path,
    max_file_count: int = DEFAULT_MAX_FILE_COUNT,
    max_extracted_bytes: int = DEFAULT_MAX_EXTRACTED_BYTES,
) -> Path:
    """
    Safely inspects and extracts a ZIP archive:
    1. Validates zip file integrity.
    2. Enforces maximum file count (prevents inode exhaustion).
    3. Enforces maximum total uncompressed size (decompression bomb protection).
    4. Enforces strict Zip Slip path traversal checks.
    5. Rejects symlinks and hardlinks that could escape extraction boundaries.
    6. Ensures transactional cleanup on any failure.
    """
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        zf = zipfile.ZipFile(zip_bytes_or_file, "r")
    except zipfile.BadZipFile as e:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise ArchiveSecurityError(f"Corrupted or invalid zip archive: {str(e)}", 400)
    except Exception as e:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise ArchiveSecurityError(f"Failed to open archive: {str(e)}", 400)

    with zf:
        infolist = zf.infolist()

        # 1. File count check
        if len(infolist) > max_file_count:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise ArchiveSecurityError(
                f"Archive exceeds maximum allowed entry count ({len(infolist)} > {max_file_count}).",
                413
            )

        # 2. Pre-extraction total uncompressed size check (Zip Bomb defense)
        total_uncompressed = sum(member.file_size for member in infolist)
        if total_uncompressed > max_extracted_bytes:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise ArchiveSecurityError(
                f"Archive uncompressed size exceeds limit of {max_extracted_bytes // (1024 * 1024)} MB "
                f"({total_uncompressed} bytes requested).",
                413
            )

        # 3. Path inspection and extraction
        extracted_bytes = 0
        for member in infolist:
            # Reject symlinks
            if is_zip_member_symlink(member):
                shutil.rmtree(target_dir, ignore_errors=True)
                raise ArchiveSecurityError(
                    f"Archive contains prohibited symbolic link '{member.filename}'.",
                    400
                )

            # Validate target path
            target_path = validate_path_safety(target_dir, member.filename)

            if member.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Stream extraction with running size verification
            with zf.open(member) as source_f, open(target_path, "wb") as dest_f:
                while chunk := source_f.read(65536):
                    extracted_bytes += len(chunk)
                    if extracted_bytes > max_extracted_bytes:
                        shutil.rmtree(target_dir, ignore_errors=True)
                        raise ArchiveSecurityError("Archive exceeded uncompressed size limit during extraction.", 413)
                    dest_f.write(chunk)

    return target_dir


def extract_tar_safely(
    tar_path: Path,
    target_dir: Path,
    max_file_count: int = DEFAULT_MAX_FILE_COUNT,
    max_extracted_bytes: int = DEFAULT_MAX_EXTRACTED_BYTES,
) -> Path:
    """
    Safely inspects and extracts a TAR (tar.gz) archive:
    1. Enforces member count boundaries.
    2. Enforces decompression size boundaries.
    3. Rejects symlinks and hardlinks.
    4. Validates normalized target paths.
    """
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(tar_path, "r:*") as tar:
            members = tar.getmembers()

            if len(members) > max_file_count:
                shutil.rmtree(target_dir, ignore_errors=True)
                raise ArchiveSecurityError(
                    f"Archive member count ({len(members)}) exceeds limit of {max_file_count}.",
                    413
                )

            total_size = sum(m.size for m in members)
            if total_size > max_extracted_bytes:
                shutil.rmtree(target_dir, ignore_errors=True)
                raise ArchiveSecurityError(
                    f"Archive uncompressed size exceeds limit of {max_extracted_bytes // (1024 * 1024)} MB.",
                    413
                )

            for member in members:
                # Disallow symlinks and hard links
                if member.issym() or member.islnk():
                    shutil.rmtree(target_dir, ignore_errors=True)
                    raise ArchiveSecurityError(
                        f"Archive contains prohibited symbolic or hard link '{member.name}'.",
                        400
                    )

                validate_path_safety(target_dir, member.name)

            # Safe extraction
            tar.extractall(path=target_dir)

    except ArchiveSecurityError:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise ArchiveSecurityError(f"Failed to extract tar archive: {str(e)}", 400)

    return target_dir
