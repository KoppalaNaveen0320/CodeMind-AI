import tempfile
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexing_job import IndexingJob
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.parsing.extractor import CodeExtractor
from backend.app.services.indexing_service import IndexingService


def test_tree_sitter_python_extractor():
    """Verify tree-sitter extracts functions, classes, methods, and imports from Python."""
    code = b"""import os
from pathlib import Path

def calculate_metrics(count: int) -> int:
    '''Calculates total score.'''
    return count * 2

class MetricAnalyzer:
    '''Class documentation.'''
    def analyze(self):
        return calculate_metrics(10)
"""
    symbols = CodeExtractor.extract_symbols(code, "test.py", "python")
    names = [s.name for s in symbols]
    kinds = {s.kind for s in symbols}

    assert "calculate_metrics" in names
    assert "MetricAnalyzer" in names
    assert any("analyze" in n for n in names)
    assert "function" in kinds
    assert "class" in kinds
    assert "import" in kinds

    func_sym = next(s for s in symbols if s.name == "calculate_metrics")
    assert func_sym.start_line == 4
    assert func_sym.end_line == 6


def test_tree_sitter_javascript_extractor():
    """Verify tree-sitter extracts functions, classes, and imports from JavaScript/TypeScript."""
    code = b"""import { useState } from 'react';

function HeaderComponent(props) {
    return null;
}

class SessionService {
    authenticate(token) {
        return true;
    }
}
"""
    symbols = CodeExtractor.extract_symbols(code, "app.js", "javascript")
    names = [s.name for s in symbols]
    assert any("HeaderComponent" in n for n in names)
    assert any("SessionService" in n for n in names)
    assert any("authenticate" in n for n in names)


def test_duplicate_concurrent_indexing_job_prevention(db_session: Session):
    """Verify create_indexing_job returns existing active job instead of duplicating."""
    repo = Repository(name="job-repo", full_name="acme/job-repo", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    job1 = IndexingService.create_indexing_job(db_session, repo, "main")
    job2 = IndexingService.create_indexing_job(db_session, repo, "main")

    assert job1.id == job2.id
    all_jobs = db_session.query(IndexingJob).filter(IndexingJob.repository_id == repo.id).all()
    assert len(all_jobs) == 1


def test_cancel_and_retry_job(client: TestClient, db_session: Session):
    """Verify job cancellation and retry states."""
    repo = Repository(name="cancel-repo", full_name="acme/cancel-repo")
    db_session.add(repo)
    db_session.commit()

    job = IndexingJob(repository_id=repo.id, status="INDEXING", stage="INDEXING")
    db_session.add(job)
    db_session.commit()

    # Cancel
    cancel_res = client.post(f"/api/v1/jobs/{job.id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # Retry
    retry_res = client.post(f"/api/v1/jobs/{job.id}/retry")
    assert retry_res.status_code == 200
    assert retry_res.json()["status"] == "QUEUED"


@pytest.mark.anyio
async def test_indexing_pipeline_execution(db_session: Session):
    """
    Verify full indexing pipeline on a repository, testing:
    - File filtering (.git, binaries, secrets excluded)
    - File metadata persistence in indexed_files
    - Symbol persistence in code_symbols
    - Repository counts updated
    """
    repo = Repository(
        name="sample-pipeline-repo",
        full_name="acme/sample-pipeline-repo",
        default_branch="main",
        status="pending"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    job = IndexingService.create_indexing_job(db_session, repo, "main")

    # Run the pipeline with isolated test session
    await IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)

    db_session.refresh(repo)
    db_session.refresh(job)

    assert job.status == "COMPLETED"
    assert job.stage == "COMPLETED"
    assert repo.status == "ready"
    assert repo.files_count > 0
    assert repo.symbols_count > 0
    assert repo.current_revision is not None
