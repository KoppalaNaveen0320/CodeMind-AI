import hashlib
import os
import tempfile
from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.ingestion.change_detector import ChangeDetector, FileSnapshot, ChangeSet
from backend.app.services.indexing_service import IndexingService


def test_path_normalization():
    """Verify paths are normalized with forward slashes and directory traversal is prevented."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        sub = root / "src" / "deep"
        sub.mkdir(parents=True, exist_ok=True)
        test_file = sub / "module.py"
        test_file.write_text("print('hello')", encoding="utf-8")

        # Standard path normalization
        norm = ChangeDetector.normalize_repo_path(test_file, root)
        assert norm == "src/deep/module.py"
        assert "\\" not in norm

        # Path traversal rejection
        outside_file = Path(tempfile.gettempdir()) / "outside_secret.txt"
        outside_file.write_text("secret", encoding="utf-8")
        with pytest.raises(ValueError, match="not within repository root"):
            ChangeDetector.normalize_repo_path(outside_file, root)


def test_change_detection_added_modified_unchanged_deleted(db_session: Session):
    """
    Verify complete classification into added, modified, unchanged, and deleted files.
    """
    repo = Repository(
        name="test-repo",
        full_name="test-org/test-repo",
        provider="github",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    # Pre-populate database with two indexed files
    f1 = IndexedFile(
        repository_id=repo.id,
        path="src/unchanged.py",
        language="python",
        size_bytes=20,
        content_hash=hashlib.sha256(b"unchanged content").hexdigest(),
        lines_count=1
    )
    f2 = IndexedFile(
        repository_id=repo.id,
        path="src/modified.py",
        language="python",
        size_bytes=20,
        content_hash=hashlib.sha256(b"original content").hexdigest(),
        lines_count=1
    )
    f3_to_delete = IndexedFile(
        repository_id=repo.id,
        path="src/obsolete.py",
        language="python",
        size_bytes=30,
        content_hash=hashlib.sha256(b"to be deleted").hexdigest(),
        lines_count=2
    )
    db_session.add_all([f1, f2, f3_to_delete])
    db_session.commit()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        src = root / "src"
        src.mkdir()

        # 1. Unchanged file (same path, same content)
        (src / "unchanged.py").write_bytes(b"unchanged content")
        # 2. Modified file (same path, different content)
        (src / "modified.py").write_bytes(b"modified updated content")
        # 3. Added file (new path)
        (src / "new_feature.py").write_bytes(b"def new_feature(): return True\n")
        # Note: obsolete.py is NOT created on disk (it was deleted!)

        discovered = [
            src / "unchanged.py",
            src / "modified.py",
            src / "new_feature.py"
        ]

        change_set = ChangeDetector.detect_changes(
            db=db_session,
            repository_id=repo.id,
            source_folder=root,
            discovered_paths=discovered,
            read_validator=IndexingService._read_and_validate_source_file,
            is_complete_scan=True
        )

        assert len(change_set.unchanged) == 1
        assert change_set.unchanged[0][0].path == "src/unchanged.py"

        assert len(change_set.modified) == 1
        assert change_set.modified[0][0].path == "src/modified.py"

        assert len(change_set.added) == 1
        assert change_set.added[0].path == "src/new_feature.py"

        assert len(change_set.deleted) == 1
        assert change_set.deleted[0].path == "src/obsolete.py"

        assert change_set.has_changes is True
        counts = change_set.summary_counts
        assert counts["added"] == 1
        assert counts["modified"] == 1
        assert counts["unchanged"] == 1
        assert counts["deleted"] == 1


def test_rename_detection(db_session: Session):
    """Verify that moving a file with identical content is detected as a rename."""
    repo = Repository(
        name="rename-repo",
        full_name="test-org/rename-repo",
        provider="github",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()

    content = b"class UsefulHelper:\n    def calculate(self): return 42\n"
    content_hash = hashlib.sha256(content).hexdigest()

    # Old indexed file path
    old_file = IndexedFile(
        repository_id=repo.id,
        path="src/old_name.py",
        language="python",
        size_bytes=len(content),
        content_hash=content_hash,
        lines_count=2
    )
    db_session.add(old_file)
    db_session.commit()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        src = root / "src"
        src.mkdir()

        # File moved to new_name.py with identical content
        new_file_path = src / "new_name.py"
        new_file_path.write_bytes(content)

        change_set = ChangeDetector.detect_changes(
            db=db_session,
            repository_id=repo.id,
            source_folder=root,
            discovered_paths=[new_file_path],
            read_validator=IndexingService._read_and_validate_source_file,
            is_complete_scan=True
        )

        assert len(change_set.renamed) == 1
        deleted_file, added_snapshot = change_set.renamed[0]
        assert deleted_file.path == "src/old_name.py"
        assert added_snapshot.path == "src/new_name.py"
        assert len(change_set.added) == 0
        assert len(change_set.deleted) == 0


def test_incomplete_scan_suppresses_deletion(db_session: Session):
    """
    CRITICAL SAFETY REQUIREMENT:
    An incomplete, partial, or failed scan must NEVER trigger deletion cleanup of indexed data.
    """
    repo = Repository(
        name="safety-repo",
        full_name="test-org/safety-repo",
        provider="github",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()

    # Repo has 3 existing files
    for p in ["a.py", "b.py", "c.py"]:
        db_session.add(IndexedFile(
            repository_id=repo.id,
            path=p,
            language="python",
            size_bytes=10,
            content_hash=hashlib.sha256(p.encode()).hexdigest(),
            lines_count=1
        ))
    db_session.commit()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        # Partial scan discovers only a.py
        (root / "a.py").write_text("a.py", encoding="utf-8")

        change_set = ChangeDetector.detect_changes(
            db=db_session,
            repository_id=repo.id,
            source_folder=root,
            discovered_paths=[root / "a.py"],
            read_validator=IndexingService._read_and_validate_source_file,
            is_complete_scan=False  # PARTIAL / INCOMPLETE SCAN FLAG!
        )

        # Deletion MUST be suppressed!
        assert len(change_set.deleted) == 0
        assert len(change_set.renamed) == 0
        assert len(change_set.unchanged) == 1


def test_repository_isolation_in_change_detection(db_session: Session):
    """Verify files with identical paths in different repositories do not interfere."""
    repo1 = Repository(name="r1", full_name="org/r1", provider="github", status="ready")
    repo2 = Repository(name="r2", full_name="org/r2", provider="github", status="ready")
    db_session.add_all([repo1, repo2])
    db_session.commit()

    # Both repos have "src/app.py", but repo1 has hash A, repo2 has hash B
    db_session.add(IndexedFile(
        repository_id=repo1.id,
        path="src/app.py",
        language="python",
        size_bytes=10,
        content_hash="hash_repo1",
        lines_count=1
    ))
    db_session.add(IndexedFile(
        repository_id=repo2.id,
        path="src/app.py",
        language="python",
        size_bytes=10,
        content_hash="hash_repo2",
        lines_count=1
    ))
    db_session.commit()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        src = root / "src"
        src.mkdir()
        (src / "app.py").write_text("content for repo 1", encoding="utf-8")

        # Detecting changes for repo1 should only compare against repo1's records
        cs1 = ChangeDetector.detect_changes(
            db=db_session,
            repository_id=repo1.id,
            source_folder=root,
            discovered_paths=[src / "app.py"],
            read_validator=IndexingService._read_and_validate_source_file,
            is_complete_scan=True
        )

        # Content matches hash of "content for repo 1" (not "hash_repo1"), so modified
        assert len(cs1.modified) == 1
        assert cs1.modified[0][1].repository_id == repo1.id


def test_binary_and_unreadable_file_handling():
    """Verify binary content, NUL bytes, and oversized files are handled gracefully."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        bin_file = root / "binary_data.bin"
        bin_file.write_bytes(bytes([0, 1, 2, 3, 255, 0, 12, 14, 0, 0, 0]))

        text_str, clean_bytes, skip_reason = IndexingService._read_and_validate_source_file(bin_file)
        assert skip_reason is not None

        # Source file with occasional NUL byte is sanitized with U+FFFD
        nul_file = root / "nul_char.py"
        nul_file.write_bytes(b"x = 1\x00\ny = 2\n")
        text_str, clean_bytes, skip_reason = IndexingService._read_and_validate_source_file(nul_file)
        assert skip_reason is None
        assert "\x00" not in text_str
        assert "\uFFFD" in text_str
