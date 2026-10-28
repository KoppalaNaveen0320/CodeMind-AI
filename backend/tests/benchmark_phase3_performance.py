import asyncio
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.db.session import SessionLocal
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.services.indexing_service import IndexingService


def generate_large_repo_fixture(repo_dir: Path, num_packages: int = 10, files_per_pkg: int = 10):
    """
    Generates a realistic multi-package repository with cross-file dependencies.
    Total files = num_packages * files_per_pkg (default: 100 files).
    """
    for p in range(num_packages):
        pkg_dir = repo_dir / f"package_{p:02d}"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "__init__.py").write_text(f'"""Package {p} init"""\n', encoding="utf-8")

        for f in range(files_per_pkg - 1):
            file_path = pkg_dir / f"service_{f:02d}.py"
            other_pkg = (p + 1) % num_packages
            code = f'''"""Service {f} in package {p}"""
from package_{other_pkg:02d}.service_00 import BaseService{other_pkg} if {f} > 0 else object

class Service_{p:02d}_{f:02d}:
    """Handles business domain {p}-{f} logic."""
    def __init__(self, name: str = "service_{p}_{f}"):
        self.name = name

    def execute_operation(self, value: int) -> int:
        return value * {f + 1} + {p}

    def compute_summary(self, data: list) -> dict:
        total = sum(data) if data else 0
        return {{"service": self.name, "total": total, "factor": {f + 1}}}

def helper_{p:02d}_{f:02d}(x: int, y: int) -> int:
    """Helper calculation for domain {p}-{f}."""
    return x + y + {f}
'''
            file_path.write_text(code, encoding="utf-8")


async def run_benchmark():
    db = SessionLocal()
    temp_dir = Path(tempfile.mkdtemp(prefix="codemind_bench_"))
    try:
        repo_dir = temp_dir / "large_benchmark_repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        
        TOTAL_PACKAGES = 10
        FILES_PER_PKG = 10
        TOTAL_FILES = TOTAL_PACKAGES * FILES_PER_PKG  # 100 files

        print(f"================================================================")
        print(f" CodeMind AI - Phase 3 Large Repository Performance Benchmark   ")
        print(f"================================================================")
        print(f"Target Source Files: {TOTAL_FILES} files across {TOTAL_PACKAGES} packages")
        print(f"Generating realistic fixture at: {repo_dir}...")
        generate_large_repo_fixture(repo_dir, TOTAL_PACKAGES, FILES_PER_PKG)
        actual_files = list(repo_dir.glob("**/*.py"))
        print(f"Fixture created with {len(actual_files)} Python source files.")

        # Create benchmark repository
        repo = Repository(
            name="benchmark-large-repo",
            full_name="benchmark-org/benchmark-large-repo",
            provider="folder",
            clone_url=str(repo_dir),
            status="ready",
        )
        db.add(repo)
        db.commit()
        db.refresh(repo)

        # -------------------------------------------------------------
        # BENCHMARK RUN 1: Full Initial Indexing
        # -------------------------------------------------------------
        print("\n--- 1. Full Initial Indexing Benchmark ---")
        job1 = IndexingService.create_indexing_job(db, repo)
        t0 = time.perf_counter()
        await IndexingService.run_indexing_pipeline(job1.id, repo.id, "main", db_session=db)
        t_full = time.perf_counter() - t0

        db.refresh(job1)
        db.refresh(repo)
        full_files_count = db.query(IndexedFile).filter(IndexedFile.repository_id == repo.id).count()
        full_symbols_count = db.query(CodeSymbol).filter(CodeSymbol.repository_id == repo.id).count()
        full_chunks_count = db.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).count()
        full_nodes_count = db.query(GraphNode).filter(GraphNode.repository_id == repo.id).count()
        full_edges_count = db.query(GraphEdge).filter(GraphEdge.repository_id == repo.id).count()

        print(f"Status: {job1.status}")
        print(f"Full Index Elapsed Time: {t_full:.3f} seconds")
        print(f"Files Indexed: {full_files_count} (added={job1.files_added})")
        print(f"Symbols Extracted: {full_symbols_count}")
        print(f"Chunks Created: {full_chunks_count}")
        print(f"Graph Nodes / Edges: {full_nodes_count} / {full_edges_count}")
        print(f"Throughput: {full_files_count / t_full:.1f} files/sec")

        # -------------------------------------------------------------
        # BENCHMARK RUN 2: Zero-Change Incremental Indexing
        # -------------------------------------------------------------
        print("\n--- 2. Zero-Change Incremental Indexing Benchmark ---")
        job2 = IndexingService.create_indexing_job(db, repo)
        t0 = time.perf_counter()
        await IndexingService.run_indexing_pipeline(job2.id, repo.id, "main", db_session=db)
        t_unchanged = time.perf_counter() - t0

        db.refresh(job2)
        print(f"Status: {job2.status}")
        print(f"Unchanged Index Elapsed Time: {t_unchanged:.3f} seconds")
        print(f"Files Unchanged (Reused): {job2.files_unchanged} / {job2.total_files}")
        print(f"Reparsed Files: {job2.files_processed}")
        print(f"Speedup vs Full Index: {t_full / max(0.001, t_unchanged):.1f}x")

        # -------------------------------------------------------------
        # BENCHMARK RUN 3: Incremental Changes (Modified, Added, Deleted)
        # -------------------------------------------------------------
        print("\n--- 3. Incremental Changes Benchmark (Modified, Added, Deleted) ---")
        # Modify 5 files
        for f in range(5):
            mod_file = repo_dir / "package_00" / f"service_{f:02d}.py"
            if mod_file.exists():
                mod_file.write_text(mod_file.read_text(encoding="utf-8") + "\ndef added_method(): return 999\n", encoding="utf-8")

        # Add 3 new files
        for a in range(3):
            new_file = repo_dir / "package_00" / f"new_feature_{a:02d}.py"
            new_file.write_text(f"class NewFeature{a}:\n    def run(self): return {a}\n", encoding="utf-8")

        # Delete 2 files
        del_file1 = repo_dir / "package_01" / "service_01.py"
        del_file2 = repo_dir / "package_01" / "service_02.py"
        if del_file1.exists():
            del_file1.unlink()
        if del_file2.exists():
            del_file2.unlink()

        job3 = IndexingService.create_indexing_job(db, repo)
        t0 = time.perf_counter()
        await IndexingService.run_indexing_pipeline(job3.id, repo.id, "main", db_session=db)
        t_inc = time.perf_counter() - t0

        db.refresh(job3)
        db.refresh(repo)
        inc_files_count = db.query(IndexedFile).filter(IndexedFile.repository_id == repo.id).count()
        inc_symbols_count = db.query(CodeSymbol).filter(CodeSymbol.repository_id == repo.id).count()
        inc_chunks_count = db.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).count()

        print(f"Status: {job3.status}")
        print(f"Incremental Index Elapsed Time: {t_inc:.3f} seconds")
        print(f"Changes Detected: modified={job3.files_modified}, added={job3.files_added}, deleted={job3.files_deleted}, unchanged={job3.files_unchanged}")
        print(f"Active Files Post-Update: {inc_files_count} (Expected: {full_files_count - 2 + 3})")
        print(f"Active Symbols Post-Update: {inc_symbols_count}")
        print(f"Active Chunks Post-Update: {inc_chunks_count}")
        print(f"Incremental Speedup vs Full Index: {t_full / max(0.001, t_inc):.2f}x")

        # Parity check
        expected_files = full_files_count - 2 + 3
        assert inc_files_count == expected_files, f"File count mismatch: {inc_files_count} vs {expected_files}"
        assert job3.files_modified == 5, f"Modified count mismatch: {job3.files_modified}"
        assert job3.files_added == 3, f"Added count mismatch: {job3.files_added}"
        assert job3.files_deleted == 2, f"Deleted count mismatch: {job3.files_deleted}"
        print("\nAll Benchmark Assertions & Parity Checks: PASSED!")

    finally:
        db.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
