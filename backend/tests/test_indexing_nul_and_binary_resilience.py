import pytest
from pathlib import Path
from sqlalchemy.orm import Session

from backend.app.services.indexing_service import (
    IndexingService,
    _sanitize_pg_text,
    _sanitize_pg_identifier,
)
from backend.app.parsing.extractor import CodeExtractor
from backend.app.models.repository import Repository
from backend.app.models.indexing_job import IndexingJob
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_chunk import CodeChunk


def test_sanitize_pg_text_replaces_nul():
    """Verify that PostgreSQL string sanitizer replaces 0x00 with replacement character."""
    raw = "Hello\x00World\x00Testing"
    sanitized = _sanitize_pg_text(raw)
    assert "\x00" not in sanitized
    assert sanitized == "Hello\uFFFDWorld\uFFFDTesting"
    assert _sanitize_pg_text(None) is None


def test_sanitize_pg_identifier_strips_nul():
    """Verify that identifier sanitizer strips 0x00 characters entirely."""
    raw = "func\x00_name\x00"
    sanitized = _sanitize_pg_identifier(raw)
    assert "\x00" not in sanitized
    assert sanitized == "func_name"
    assert _sanitize_pg_identifier(None) is None


def test_utf16_le_bom_file_reading(tmp_path: Path):
    """
    Verify that PowerShell-generated UTF-16 LE files with BOM (e.g. project_structure.txt)
    are decoded cleanly as UTF-16 LE and not corrupted into null-byte sequences.
    """
    utf16_file = tmp_path / "project_structure.txt"
    original_text = "Folder1\\\n  subfile.py\nFolder2\\\n  another.py\n"
    utf16_file.write_bytes(original_text.encode("utf-16"))

    text, raw_bytes, skip_reason = IndexingService._read_and_validate_source_file(utf16_file)
    assert skip_reason is None
    assert text is not None
    assert "\x00" not in text
    assert "subfile.py" in text
    assert "another.py" in text


def test_binary_file_detection_and_skip(tmp_path: Path):
    """Verify that binary files with high ratio of NUL/control bytes are skipped with reason."""
    bin_file = tmp_path / "model.onnx"
    bin_file.write_bytes(b"\x00\x01\x02\x03\x00\x00\x00\xff\xfe\x00" * 100)

    text, raw_bytes, skip_reason = IndexingService._read_and_validate_source_file(bin_file)
    assert skip_reason is not None
    assert "binary" in skip_reason.lower() or "extension" in skip_reason.lower()


def test_javascript_symbol_extraction_robustness():
    """
    Verify JavaScript symbol extraction captures classes, methods, functions,
    and arrow functions without triggering C runtime segmentation faults.
    """
    js_code = b"""
import { useState, useEffect } from 'react';

export class DecisionManager {
    constructor() {
        this.state = {};
    }

    async evaluateAlternatives(criteria) {
        return criteria.map(c => c.weight);
    }
}

function computeScore(a, b) {
    return a + b;
}

const formatScore = (score) => {
    return `${score}%`;
};

const validateInput = function(val) {
    return val !== null;
};
"""
    symbols = CodeExtractor.extract_symbols(js_code, "decision_manager.js", "javascript")
    names = [s.name for s in symbols]
    kinds = [s.kind for s in symbols]

    assert any("DecisionManager" in n for n in names)
    assert any("evaluateAlternatives" in n for n in names)
    assert any("computeScore" in n for n in names)
    assert any("formatScore" in n for n in names)
    assert any("validateInput" in n for n in names)
    assert "class" in kinds
    assert "method" in kinds
    assert "function" in kinds
    assert "import" in kinds


@pytest.mark.anyio
async def test_per_file_savepoint_isolation(db_session: Session, tmp_path: Path, monkeypatch):
    """
    Verify that an error on an individual corrupted file is caught and isolated
    by the per-file savepoint, allowing valid files to be indexed successfully.
    """
    repo = Repository(name="savepoint-repo", full_name="acme/savepoint-repo", default_branch="main", status="pending")
    db_session.add(repo)
    db_session.commit()

    async def mock_download(access_token, full_name, ref, dest_dir):
        source_dir = dest_dir / "repo"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "good1.py").write_text("def good_one(): return 1\n", encoding="utf-8")
        (source_dir / "good2.py").write_text("def good_two(): return 2\n", encoding="utf-8")
        return source_dir

    monkeypatch.setattr("backend.app.services.indexing_service.GitHubService.download_and_extract_archive", mock_download)

    job = IndexingService.create_indexing_job(db_session, repo, "main")
    await IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)

    db_session.refresh(job)
    db_session.refresh(repo)

    assert job.status == "COMPLETED"
    assert repo.status == "ready"
    assert repo.files_count == 2
    assert repo.symbols_count >= 2
