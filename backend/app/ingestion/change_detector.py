import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session

from backend.app.models.indexed_file import IndexedFile
from backend.app.parsing.extractor import CodeExtractor

logger = logging.getLogger(__name__)


@dataclass
class FileSnapshot:
    """Represents a discovered and validated source file snapshot."""
    path: str  # Normalized relative path with forward slashes, e.g. 'src/main.py'
    content_hash: str  # SHA-256 of file content bytes
    size_bytes: int
    lines_count: int
    language: str
    absolute_path: Path
    text_content: Optional[str] = None
    clean_bytes: Optional[bytes] = None


@dataclass
class ChangeSet:
    """Categorized repository-scoped change detection result."""
    repository_id: int
    is_complete_scan: bool
    added: List[FileSnapshot] = field(default_factory=list)
    modified: List[Tuple[FileSnapshot, IndexedFile]] = field(default_factory=list)
    unchanged: List[Tuple[FileSnapshot, IndexedFile]] = field(default_factory=list)
    deleted: List[IndexedFile] = field(default_factory=list)
    renamed: List[Tuple[IndexedFile, FileSnapshot]] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.deleted or self.renamed)

    @property
    def summary_counts(self) -> Dict[str, int]:
        return {
            "added": len(self.added),
            "modified": len(self.modified),
            "unchanged": len(self.unchanged),
            "deleted": len(self.deleted),
            "renamed": len(self.renamed),
            "total_active": len(self.added) + len(self.modified) + len(self.unchanged) + len(self.renamed),
        }


class ChangeDetector:
    """
    Repository-scoped change detection engine for incremental indexing.
    Classifies files into Added, Modified, Unchanged, Deleted, and Renamed.
    Enforces path traversal defenses, symlink safety, and protects against partial scan data loss.
    """

    @staticmethod
    def normalize_repo_path(file_path: Path, root_folder: Path) -> str:
        """
        Normalizes a repository file path safely.
        - Resolves relative path to root_folder.
        - Standardizes path separators to forward slash '/'.
        - Prevents directory traversal outside root_folder.
        """
        resolved_root = root_folder.resolve()
        resolved_file = file_path.resolve()

        # Symlink boundary defense: symlink cannot point outside root_folder
        if file_path.is_symlink():
            try:
                target = file_path.resolve(strict=True)
                if not target.is_relative_to(resolved_root):
                    raise ValueError(f"Symlink target {target} escapes repository root {resolved_root}")
            except Exception as e:
                raise ValueError(f"Invalid or escaping symlink {file_path}: {e}")

        # Check relative containment
        try:
            rel = file_path.relative_to(root_folder)
        except ValueError:
            # Try resolved paths
            try:
                rel = resolved_file.relative_to(resolved_root)
            except ValueError:
                raise ValueError(f"Path {file_path} is not within repository root {root_folder}")

        normalized = str(rel).replace("\\", "/").strip("./").strip("/")
        if not normalized or ".." in normalized.split("/"):
            raise ValueError(f"Illegal normalized path '{normalized}' from {file_path}")

        return normalized

    @classmethod
    def compute_sha256(cls, content_bytes: bytes) -> str:
        """Computes stable SHA-256 hash for raw file bytes."""
        return hashlib.sha256(content_bytes).hexdigest()

    @classmethod
    def detect_changes(
        cls,
        db: Session,
        repository_id: int,
        source_folder: Path,
        discovered_paths: List[Path],
        read_validator: Callable[[Path], Tuple[Optional[str], Optional[bytes], Optional[str]]],
        is_complete_scan: bool = True,
    ) -> ChangeSet:
        """
        Detects changes between the filesystem snapshot and the database index for repository_id.
        
        Guarantees:
        1. Compare files within the correct repository only.
        2. Never deletes indexed data if is_complete_scan is False.
        3. Stable SHA-256 hash comparison.
        4. Detects renamed/moved files when content hash matches an added and deleted pair.
        """
        change_set = ChangeSet(repository_id=repository_id, is_complete_scan=is_complete_scan)

        # 1. Fetch current indexed files from database for THIS repository only
        existing_records: List[IndexedFile] = (
            db.query(IndexedFile)
            .filter(IndexedFile.repository_id == repository_id)
            .all()
        )
        existing_by_path: Dict[str, IndexedFile] = {
            f.path.replace("\\", "/"): f for f in existing_records
        }

        # 2. Process discovered filesystem files
        candidate_snapshots: Dict[str, FileSnapshot] = {}
        seen_paths: Set[str] = set()

        for f_path in discovered_paths:
            try:
                rel_path = cls.normalize_repo_path(f_path, source_folder)
            except Exception as norm_err:
                logger.warning(f"Skipping invalid/escaping path {f_path}: {norm_err}")
                continue

            if rel_path in seen_paths:
                continue
            seen_paths.add(rel_path)

            # Read and validate source content
            text_str, content_bytes, skip_reason = read_validator(f_path)
            if skip_reason is not None or content_bytes is None:
                logger.debug(f"Skipping unreadable or non-source file {rel_path}: {skip_reason}")
                continue

            content_hash = cls.compute_sha256(content_bytes)
            lang = CodeExtractor.detect_language(rel_path)
            lines_c = max(0, min(2147483647, len(content_bytes.splitlines())))
            size_b = max(0, min(2147483647, len(content_bytes)))

            snapshot = FileSnapshot(
                path=rel_path,
                content_hash=content_hash,
                size_bytes=size_b,
                lines_count=lines_c,
                language=lang,
                absolute_path=f_path,
                text_content=text_str,
                clean_bytes=content_bytes,
            )
            candidate_snapshots[rel_path] = snapshot

        # 3. Classify into preliminary added, modified, unchanged
        raw_added: List[FileSnapshot] = []
        raw_deleted: List[IndexedFile] = []

        for rel_path, snapshot in candidate_snapshots.items():
            if rel_path in existing_by_path:
                existing_file = existing_by_path[rel_path]
                if existing_file.content_hash == snapshot.content_hash:
                    snapshot.text_content = None
                    snapshot.clean_bytes = None
                    change_set.unchanged.append((snapshot, existing_file))
                else:
                    change_set.modified.append((snapshot, existing_file))
            else:
                raw_added.append(snapshot)

        # 4. Check for deleted files (absent from candidate_snapshots)
        # CRITICAL SAFETY: Only consider files deleted if the scan is verified to be complete!
        if is_complete_scan:
            for rel_path, existing_file in existing_by_path.items():
                if rel_path not in candidate_snapshots:
                    raw_deleted.append(existing_file)
        else:
            logger.warning(
                f"Scan for repository {repository_id} was partial or interrupted. "
                "Deletion cleanup is suppressed to protect the existing index."
            )

        # 5. Detect Renamed or Moved Files
        # Match added files and deleted files with identical content hash
        deleted_by_hash: Dict[str, List[IndexedFile]] = {}
        for d in raw_deleted:
            if d.content_hash:
                deleted_by_hash.setdefault(d.content_hash, []).append(d)

        paired_deleted_ids: Set[int] = set()
        paired_added_paths: Set[str] = set()

        for a in raw_added:
            if a.content_hash in deleted_by_hash:
                candidates = deleted_by_hash[a.content_hash]
                # Pick first unpaired candidate
                matching_del = next((c for c in candidates if c.id not in paired_deleted_ids), None)
                if matching_del:
                    change_set.renamed.append((matching_del, a))
                    paired_deleted_ids.add(matching_del.id)
                    paired_added_paths.add(a.path)

        # Remaining unpaired additions and deletions
        for a in raw_added:
            if a.path not in paired_added_paths:
                change_set.added.append(a)

        for d in raw_deleted:
            if d.id not in paired_deleted_ids:
                change_set.deleted.append(d)

        logger.info(
            f"Repository {repository_id} change detection: "
            f"{len(change_set.added)} added, {len(change_set.modified)} modified, "
            f"{len(change_set.unchanged)} unchanged, {len(change_set.deleted)} deleted, "
            f"{len(change_set.renamed)} renamed."
        )

        return change_set
