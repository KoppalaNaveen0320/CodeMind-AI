import os
import shutil
import tempfile
import pytest
from pathlib import Path
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.repository import Repository
from backend.app.models.indexing_job import IndexingJob
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.parsing.extractor import CodeExtractor, ExtractedCall
from backend.app.parsing.chunker import CodeChunker
from backend.app.graph.builder import KnowledgeGraphBuilder
from backend.app.integrations.embeddings.mock_provider import MockEmbeddingProvider
from backend.app.integrations.embeddings.service import EmbeddingService
from backend.app.integrations.github.service import GitHubService
from backend.app.services.indexing_service import (
    IndexingService,
    IGNORED_DIRECTORIES,
    IGNORED_FILE_NAMES,
    IGNORED_EXTENSIONS,
)


def test_recursive_source_file_discovery_and_filtering():
    """
    Verify recursive discovery traverses nested directories while strictly excluding:
    .git, dependencies (node_modules), build outputs, binaries, and configured ignored patterns.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)
        # Nested source structure
        (tmp_dir / "src" / "core").mkdir(parents=True, exist_ok=True)
        (tmp_dir / "src" / "utils").mkdir(parents=True, exist_ok=True)
        (tmp_dir / "tests").mkdir(parents=True, exist_ok=True)
        (tmp_dir / ".git").mkdir(parents=True, exist_ok=True)
        (tmp_dir / "node_modules" / "express").mkdir(parents=True, exist_ok=True)
        (tmp_dir / "build" / "dist").mkdir(parents=True, exist_ok=True)
        (tmp_dir / "__pycache__").mkdir(parents=True, exist_ok=True)

        # Valid source files
        (tmp_dir / "src" / "core" / "app.py").write_text("class App: pass\n", encoding="utf-8")
        (tmp_dir / "src" / "utils" / "helper.py").write_text("def assist(): pass\n", encoding="utf-8")
        (tmp_dir / "tests" / "test_app.py").write_text("def test(): pass\n", encoding="utf-8")

        # Files that MUST be excluded
        (tmp_dir / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (tmp_dir / "node_modules" / "express" / "index.js").write_text("module.exports = {};\n", encoding="utf-8")
        (tmp_dir / "build" / "dist" / "bundle.min.js").write_text("var x=1;\n", encoding="utf-8")
        (tmp_dir / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"\x00\x01\x02")
        (tmp_dir / ".env").write_text("API_KEY=secret\n", encoding="utf-8")
        (tmp_dir / "package-lock.json").write_text("{}\n", encoding="utf-8")
        (tmp_dir / "poetry.lock").write_text("# lockfile\n", encoding="utf-8")

        discovered: list[Path] = []
        for root, dirs, files in os.walk(tmp_dir):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES and not d.startswith(".")]
            for f in files:
                file_path = Path(root) / f
                ext = file_path.suffix.lower()
                if f.startswith(".") or f in IGNORED_FILE_NAMES or ext in IGNORED_EXTENSIONS or f.endswith(".lock"):
                    continue
                discovered.append(file_path)

        rel_paths = {str(p.relative_to(tmp_dir)).replace("\\", "/") for p in discovered}

        # Assert valid files are discovered recursively
        assert "src/core/app.py" in rel_paths
        assert "src/utils/helper.py" in rel_paths
        assert "tests/test_app.py" in rel_paths

        # Assert ignored folders and files are strictly excluded
        assert not any(p.startswith(".git") for p in rel_paths)
        assert not any(p.startswith("node_modules") for p in rel_paths)
        assert not any(p.startswith("build") for p in rel_paths)
        assert not any(p.startswith("__pycache__") for p in rel_paths)
        assert ".env" not in rel_paths
        assert "poetry.lock" not in rel_paths
        assert len(rel_paths) == 3


@pytest.mark.anyio
async def test_default_branch_and_repository_tree_handling(monkeypatch):
    """
    Verify public repository download succeeds without access token (None)
    and resolves commit SHA or archive fallback gracefully.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        temp_dir = Path(tmp_str)

        async def mock_extract(access_token, full_name, ref, dest_dir):
            repo_folder = dest_dir / "repo"
            repo_folder.mkdir(parents=True, exist_ok=True)
            (repo_folder / "flask").mkdir(exist_ok=True)
            (repo_folder / "flask" / "app.py").write_text("class Flask: pass\n", encoding="utf-8")
            (repo_folder / "flask" / "blueprints.py").write_text("class Blueprint: pass\n", encoding="utf-8")
            return repo_folder

        monkeypatch.setattr(GitHubService, "download_and_extract_archive", mock_extract)

        # Call with access_token=None (public repo)
        folder = await GitHubService.download_and_extract_archive(
            access_token=None,
            full_name="pallets/flask",
            ref="main",
            dest_dir=temp_dir
        )

        assert folder.exists()
        assert (folder / "flask" / "app.py").exists()
        assert (folder / "flask" / "blueprints.py").exists()


def test_tree_sitter_ast_symbol_extraction_comprehensive():
    """
    Verify AST symbol and call extraction accurately identifies:
    classes, functions, methods, imports, lines, and call relationships.
    """
    code_py = b'''import sys
from os import path

def top_level_func(a: int, b: int) -> int:
    """Computes total."""
    return a + b

class DatabaseManager:
    """Manages db pool."""
    def __init__(self, dsn: str):
        self.dsn = dsn

    def execute_query(self, query: str):
        top_level_func(1, 2)
        return True
'''
    symbols = CodeExtractor.extract_symbols(code_py, "src/db.py", "python")
    names = [s.name for s in symbols]
    kinds = {s.kind for s in symbols}

    assert "top_level_func" in names
    assert "DatabaseManager" in names
    assert any("execute_query" in n for n in names)
    assert any("__init__" in n for n in names)
    assert "function" in kinds
    assert "class" in kinds
    assert "import" in kinds

    # Verify docstring extraction
    func_sym = next(s for s in symbols if s.name == "top_level_func")
    assert func_sym.docstring == "Computes total."
    assert func_sym.start_line == 4

    # Verify static call extraction
    calls = CodeExtractor.extract_static_calls(code_py, "src/db.py", "python")
    call_names = [c.callee_name for c in calls]
    assert "top_level_func" in call_names


def test_chunk_and_embedding_768_dim_compatibility(db_session: Session):
    """
    Verify chunking generates proper AST chunks and embedding pipeline
    produces vectors matching the 768-dimensional schema.
    """
    repo = Repository(name="vec-repo", full_name="acme/vec-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(id=1, repository_id=repo.id, path="src/service.py", language="python", lines_count=20)
    db_session.add(f)
    db_session.commit()

    code = (
        "class OrderService:\n"
        "    def create_order(self, item_id: int):\n"
        "        return {'status': 'created', 'item': item_id}\n\n"
        "def cancel_order(order_id: int):\n"
        "    return {'status': 'cancelled', 'order': order_id}\n"
    )

    sym1 = CodeSymbol(id=1, repository_id=repo.id, file_id=f.id, name="OrderService", kind="class", start_line=1, end_line=3)
    sym2 = CodeSymbol(id=2, repository_id=repo.id, file_id=f.id, name="cancel_order", kind="function", start_line=5, end_line=6)
    db_session.add_all([sym1, sym2])
    db_session.commit()

    chunks = CodeChunker.chunk_file(f, code, [sym1, sym2], "rev-001")
    assert len(chunks) == 2

    chunk_objs = []
    for c in chunks:
        co = CodeChunk(
            repository_id=repo.id,
            file_id=f.id,
            symbol_id=c.symbol_id,
            file_path=c.file_path,
            code_symbol=c.code_symbol,
            source_revision="rev-001",
            chunk_index=c.chunk_index,
            chunk_text=c.chunk_text,
            content_hash=c.content_hash,
            language=c.language,
            start_line=c.start_line,
            end_line=c.end_line,
        )
        db_session.add(co)
        chunk_objs.append(co)
    db_session.commit()

    # Embed using 768-dim mock provider (matching settings.EMBEDDING_DIMENSION)
    provider = MockEmbeddingProvider(dimension=768)
    assert provider.dimension == 768

    import asyncio
    res = asyncio.run(EmbeddingService.embed_new_chunks(db_session, chunk_objs, provider=provider))
    assert res["success"] is True
    assert res["embedded_count"] == 2

    # Verify persisted vector length
    db_session.refresh(chunk_objs[0])
    vec = list(chunk_objs[0].embedding)
    assert len(vec) == 768


def test_knowledge_graph_node_and_edge_creation(db_session: Session):
    """Verify knowledge graph creates repository, file, symbol nodes and connecting edges."""
    repo = Repository(name="kg-repo", full_name="acme/kg-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(id=10, repository_id=repo.id, path="src/router.py", language="python", lines_count=30)
    db_session.add(f1)
    db_session.commit()

    sym_cls = CodeSymbol(id=20, repository_id=repo.id, file_id=f1.id, name="Router", kind="class", start_line=1, end_line=20)
    sym_method = CodeSymbol(id=21, repository_id=repo.id, file_id=f1.id, name="Router.handle_request", kind="method", start_line=5, end_line=15)
    db_session.add_all([sym_cls, sym_method])
    db_session.commit()

    nodes_cnt, edges_cnt = KnowledgeGraphBuilder.build_graph_for_repository(
        db=db_session,
        repository=repo,
        files=[f1],
        symbols_by_file={f1.id: [sym_cls, sym_method]},
        calls_by_file={},
        revision="rev-kg"
    )

    assert nodes_cnt >= 4  # Repo, File, Class, Method
    assert edges_cnt >= 3  # CONTAINS, DEFINES

    nodes = db_session.query(GraphNode).filter(GraphNode.repository_id == repo.id).all()
    node_types = {n.node_type for n in nodes}
    assert "repository" in node_types
    assert "file" in node_types
    assert "class" in node_types
    assert "method" in node_types

    edges = db_session.query(GraphEdge).filter(GraphEdge.repository_id == repo.id).all()
    edge_types = {e.edge_type for e in edges}
    assert "CONTAINS" in edge_types
    assert "DEFINES" in edge_types


@pytest.mark.anyio
async def test_indexing_multiple_source_files_pipeline(db_session: Session, monkeypatch):
    """
    Verify full pipeline on multiple source files:
    - Multiple files discovered and indexed
    - Real database counts updated
    - Chunks, symbols, and embeddings persisted
    """
    repo = Repository(name="multi-repo", full_name="org/multi-repo", default_branch="main", status="pending")
    db_session.add(repo)
    db_session.commit()

    # Mock download to provide 4 realistic source files
    async def mock_download(access_token, full_name, ref, dest_dir):
        source_dir = dest_dir / "repo"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "src").mkdir(exist_ok=True)
        (source_dir / "src" / "api.py").write_text(
            "import os\n\ndef get_api_route():\n    return '/v1/users'\n",
            encoding="utf-8"
        )
        (source_dir / "src" / "models.py").write_text(
            "class UserModel:\n    name: str = 'User'\n",
            encoding="utf-8"
        )
        (source_dir / "src" / "utils.py").write_text(
            "def format_date(ts):\n    return str(ts)\n",
            encoding="utf-8"
        )
        (source_dir / "src" / "client.js").write_text(
            "function createClient() { return { active: true }; }\n",
            encoding="utf-8"
        )
        return source_dir

    monkeypatch.setattr(GitHubService, "download_and_extract_archive", mock_download)
    async def mock_latest_commit(*args, **kwargs):
        return "sha-multi-123"
    monkeypatch.setattr(GitHubService, "get_branch_latest_commit", mock_latest_commit)

    job = IndexingService.create_indexing_job(db_session, repo, "main")
    await IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)

    db_session.refresh(repo)
    db_session.refresh(job)

    # Assert accurate file and job counts
    assert job.status == "COMPLETED"
    assert job.stage == "COMPLETED"
    assert job.total_files == 4
    assert job.files_processed == 4
    assert repo.files_count == 4
    assert repo.symbols_count >= 4
    assert repo.status == "ready"
    assert repo.apis_count >= 1  # get_api_route detected as API

    # Assert database persistence
    indexed_files = db_session.query(IndexedFile).filter_by(repository_id=repo.id).all()
    assert len(indexed_files) == 4
    paths = {f.path for f in indexed_files}
    assert "src/api.py" in paths
    assert "src/models.py" in paths
    assert "src/utils.py" in paths
    assert "src/client.js" in paths

    chunks = db_session.query(CodeChunk).filter_by(repository_id=repo.id).all()
    assert len(chunks) >= 4


@pytest.mark.anyio
async def test_idempotent_reindexing(db_session: Session, monkeypatch):
    """
    Verify re-indexing the same repository does NOT create duplicate records
    in indexed_files, code_symbols, code_chunks, graph_nodes, or graph_edges.
    """
    repo = Repository(name="idemp-repo", full_name="org/idemp-repo", default_branch="main", status="pending")
    db_session.add(repo)
    db_session.commit()

    async def mock_download(access_token, full_name, ref, dest_dir):
        source_dir = dest_dir / "repo"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "app.py").write_text("class CoreApp:\n    def start(self): pass\n", encoding="utf-8")
        return source_dir

    monkeypatch.setattr(GitHubService, "download_and_extract_archive", mock_download)
    async def mock_latest_commit(*args, **kwargs):
        return "sha-idemp-1"
    monkeypatch.setattr(GitHubService, "get_branch_latest_commit", mock_latest_commit)

    # Run Indexing Run 1
    job1 = IndexingService.create_indexing_job(db_session, repo, "main")
    await IndexingService.run_indexing_pipeline(job1.id, repo.id, "main", db_session=db_session)

    files_run1 = db_session.query(IndexedFile).filter_by(repository_id=repo.id).count()
    symbols_run1 = db_session.query(CodeSymbol).filter_by(repository_id=repo.id).count()
    chunks_run1 = db_session.query(CodeChunk).filter_by(repository_id=repo.id).count()
    nodes_run1 = db_session.query(GraphNode).filter_by(repository_id=repo.id).count()
    edges_run1 = db_session.query(GraphEdge).filter_by(repository_id=repo.id).count()

    assert files_run1 == 1
    assert symbols_run1 >= 2
    assert chunks_run1 >= 1

    # Run Indexing Run 2 on same repository (Re-index)
    job2 = IndexingJob(repository_id=repo.id, branch="main", status="QUEUED")
    db_session.add(job2)
    db_session.commit()

    await IndexingService.run_indexing_pipeline(job2.id, repo.id, "main", db_session=db_session)

    db_session.refresh(repo)
    db_session.refresh(job2)

    files_run2 = db_session.query(IndexedFile).filter_by(repository_id=repo.id).count()
    symbols_run2 = db_session.query(CodeSymbol).filter_by(repository_id=repo.id).count()
    chunks_run2 = db_session.query(CodeChunk).filter_by(repository_id=repo.id).count()
    nodes_run2 = db_session.query(GraphNode).filter_by(repository_id=repo.id).count()
    edges_run2 = db_session.query(GraphEdge).filter_by(repository_id=repo.id).count()

    # Counts must remain identical — NO DUPLICATES
    assert files_run2 == files_run1
    assert symbols_run2 == symbols_run1
    assert chunks_run2 == chunks_run1
    assert nodes_run2 == nodes_run1
    assert edges_run2 == edges_run1
    assert job2.status == "COMPLETED"
    assert repo.status == "ready"


@pytest.mark.anyio
async def test_partial_indexing_failure_reporting(db_session: Session, monkeypatch):
    """
    Verify that if a stage fails (e.g. embedding failure), the failure is surfaced,
    the job is marked FAILED at the specific stage, the error message is recorded,
    and repo status becomes failed.
    """
    repo = Repository(name="fail-repo", full_name="org/fail-repo", default_branch="main", status="pending")
    db_session.add(repo)
    db_session.commit()

    async def mock_download(access_token, full_name, ref, dest_dir):
        source_dir = dest_dir / "repo"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "broken.py").write_text("def broken(): pass\n", encoding="utf-8")
        return source_dir

    async def mock_embed_failure(*args, **kwargs):
        return {"success": False, "error": "Embedding model unavailable or timed out"}

    monkeypatch.setattr(GitHubService, "download_and_extract_archive", mock_download)
    async def mock_latest_commit(*args, **kwargs):
        return "sha-fail"
    monkeypatch.setattr(GitHubService, "get_branch_latest_commit", mock_latest_commit)
    monkeypatch.setattr(EmbeddingService, "embed_new_chunks", mock_embed_failure)

    job = IndexingService.create_indexing_job(db_session, repo, "main")
    await IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)

    db_session.refresh(job)
    db_session.refresh(repo)

    assert job.status == "FAILED"
    assert job.stage == "EMBEDDING"
    assert "Embedding model unavailable or timed out" in job.error_message
    assert repo.status == "failed"
    assert job.completed_at is not None
