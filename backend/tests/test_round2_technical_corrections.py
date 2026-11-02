import ast
import asyncio
import os
import time
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.session import Base
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.parsing.extractor import CodeExtractor, ExtractedSymbol
from backend.app.graph.service import KnowledgeGraphService
from backend.app.impact.analyzer import ChangeImpactAnalyzer
import anyio
import anyio.to_thread

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

# 1. Targeted Test: TYPE_CHECKING dependency versus runtime circular import
def test_type_checking_vs_runtime_circular_import():
    sample_code = b"""
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .routing import APIRoute

def generate_unique_id(route: "APIRoute") -> str:
    return "id"
"""
    symbols = CodeExtractor.extract_symbols(sample_code, "fastapi/utils.py", "python")
    
    # Verify import symbol classification
    import_syms = [s for s in symbols if s.kind == "import"]
    assert len(import_syms) >= 1
    tc_sym = next(s for s in import_syms if "APIRoute" in s.name)
    assert tc_sym.docstring == "TYPE_CHECKING"

    # Verify forward reference extraction
    fwd_syms = [s for s in symbols if s.kind == "forward_ref"]
    assert any(s.name == "APIRoute" for s in fwd_syms)

# 2. Targeted Test: Actual runtime import cycles detection
def test_actual_runtime_import_cycles(db_session):
    repo = Repository(id=999, name="cyclic_repo", full_name="test/cyclic_repo")
    db_session.add(repo)
    
    node_a = GraphNode(id=1, repository_id=999, node_key="f:a.py", node_type="file", name="a.py", file_path="a.py")
    node_b = GraphNode(id=2, repository_id=999, node_key="f:b.py", node_type="file", name="b.py", file_path="b.py")
    node_c = GraphNode(id=3, repository_id=999, node_key="f:c.py", node_type="file", name="c.py", file_path="c.py")
    db_session.add_all([node_a, node_b, node_c])
    db_session.flush()

    # Create a true runtime cycle: a -> b -> a
    edge_ab = GraphEdge(repository_id=999, source_node_id=1, target_node_id=2, edge_type="IMPORTS", evidence="[RUNTIME] import b")
    edge_ba = GraphEdge(repository_id=999, source_node_id=2, target_node_id=1, edge_type="IMPORTS", evidence="[RUNTIME] import a")
    # And a TYPE_CHECKING edge: c -> a (should NOT create a cycle even if a -> c)
    edge_ac = GraphEdge(repository_id=999, source_node_id=1, target_node_id=3, edge_type="IMPORTS", evidence="[RUNTIME] import c")
    edge_ca_tc = GraphEdge(repository_id=999, source_node_id=3, target_node_id=1, edge_type="TYPE_CHECKING_IMPORTS", evidence="[TYPE_CHECKING] from a import A")
    
    db_session.add_all([edge_ab, edge_ba, edge_ac, edge_ca_tc])
    db_session.commit()

    res = KnowledgeGraphService.classify_imports_and_cycles(db_session, repository_id=999)
    assert res["has_runtime_cycles"] is True
    assert res["runtime_cycle_count"] == 1
    # Cycle must contain only a.py and b.py, NOT c.py
    cycle = res["runtime_cycles"][0]
    assert "a.py" in cycle and "b.py" in cycle
    assert "c.py" not in cycle
    assert res["type_checking_count"] >= 1

# 3. Targeted Test: Hypothetical application functions vs real framework functions
def test_hypothetical_application_functions_vs_real_framework_functions():
    hypothetical_app_functions = ["get_db", "get_current_user", "get_current_active_user", "create_user", "login_user"]
    real_fastapi_framework_functions = ["solve_dependencies", "get_dependant", "serialize_response", "jsonable_encoder", "get_openapi"]

    repo_path = r"C:\Users\koppa\AppData\Local\Temp\tmpy60siv75\extracted\fastapi-fastapi-79cab5b\fastapi"
    if os.path.exists(repo_path):
        all_fastapi_code = ""
        for root, _, files in os.walk(repo_path):
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(root, f), "r", encoding="utf-8") as src:
                        all_fastapi_code += src.read() + "\n"

        # Assert hypothetical application functions do NOT exist as function definitions in core framework
        for hyp in hypothetical_app_functions:
            assert f"def {hyp}(" not in all_fastapi_code, f"Hypothetical function {hyp} was unexpectedly found in core framework!"

        # Assert real framework functions DO exist
        for real_fn in real_fastapi_framework_functions:
            assert f"def {real_fn}(" in all_fastapi_code, f"Real framework function {real_fn} missing from core framework!"

# 4. Targeted Test: Evidence-backed change-impact analysis
def test_evidence_backed_change_impact_analysis(db_session):
    repo = Repository(id=100, name="fastapi", full_name="fastapi/fastapi")
    db_session.add(repo)
    
    file_params = GraphNode(id=10, repository_id=100, node_key="f:params.py", node_type="file", name="params.py", file_path="fastapi/params.py")
    file_models = GraphNode(id=11, repository_id=100, node_key="f:models.py", node_type="file", name="models.py", file_path="fastapi/dependencies/models.py")
    file_utils = GraphNode(id=12, repository_id=100, node_key="f:utils.py", node_type="file", name="utils.py", file_path="fastapi/dependencies/utils.py")
    file_test = GraphNode(id=13, repository_id=100, node_key="f:test_dep.py", node_type="file", name="test_dependency_cache.py", file_path="tests/test_dependency_cache.py")
    
    sym_use_cache = GraphNode(id=14, repository_id=100, node_key="s:use_cache", node_type="symbol", name="use_cache", symbol_name="use_cache", file_path="fastapi/params.py")
    sym_solve = GraphNode(id=15, repository_id=100, node_key="s:solve", node_type="function", name="solve_dependencies", symbol_name="solve_dependencies", file_path="fastapi/dependencies/utils.py")
    
    db_session.add_all([file_params, file_models, file_utils, file_test, sym_use_cache, sym_solve])
    db_session.flush()

    # Link incoming dependency edges: solve_dependencies (source) -> use_cache (target)
    # test_dependency_cache (source) -> solve_dependencies (target)
    e1 = GraphEdge(repository_id=100, source_node_id=15, target_node_id=14, edge_type="CALLS", evidence="solve_dependencies evaluates use_cache")
    e2 = GraphEdge(repository_id=100, source_node_id=13, target_node_id=15, edge_type="CALLS", evidence="test_dependency_cache calls solve_dependencies")
    db_session.add_all([e1, e2])
    db_session.commit()

    impact = ChangeImpactAnalyzer.analyze_impact(db_session, repository_id=100, component_name="use_cache")
    assert impact.total_affected >= 1
    assert any(c.name == "solve_dependencies" for c in impact.affected_components)
    assert "Static graph analysis reflects declared imports" in ChangeImpactAnalyzer.LIMITATIONS_NOTICE

# 5. Targeted Test: AnyIO limiter instrumentation
def test_anyio_limiter_instrumentation():
    async def _async_test():
        limiter = anyio.to_thread.current_default_thread_limiter()
        # Confirm limiter has total_tokens and borrowed_tokens attributes
        assert hasattr(limiter, "total_tokens")
        assert hasattr(limiter, "borrowed_tokens")
        assert isinstance(limiter.total_tokens, int)
        assert limiter.total_tokens > 0

        # Test queue waiting time measurement
        enqueue_time = time.perf_counter()
        start_time = None
        
        def worker():
            nonlocal start_time
            start_time = time.perf_counter()
            time.sleep(0.005)
            return True

        await anyio.to_thread.run_sync(worker, limiter=limiter)
        assert start_time is not None
        queue_wait_ms = (start_time - enqueue_time) * 1000
        assert queue_wait_ms >= 0.0

    asyncio.run(_async_test())

# 6. Targeted Test: Benchmark platform compatibility and metrics capture
def test_benchmark_platform_compatibility():
    from scratch.benchmark_anyio_dependency import run_sync_benchmark, run_async_benchmark
    
    async def _run():
        sync_res = await run_sync_benchmark(concurrent_tasks=10, total_requests=20, work_duration=0.001)
        async_res = await run_async_benchmark(concurrent_tasks=10, total_requests=20, work_duration=0.001)
        return sync_res, async_res

    sync_res, async_res = asyncio.run(_run())

    required_keys = ["throughput_req_sec", "p50_ms", "p95_ms", "p99_ms", "p99_9_ms", "errors", "timeouts"]
    for k in required_keys:
        assert k in sync_res, f"Missing {k} in sync benchmark results"
        assert k in async_res, f"Missing {k} in async benchmark results"

    # Verify limiter saturation instrumentation exists in sync benchmark
    assert "limiter_saturation_events" in sync_res
    assert "p50_queue_wait_ms" in sync_res

# 7. Targeted Test: Citation claim-to-source accuracy
def test_citation_claim_to_source_accuracy():
    repo_path = r"C:\Users\koppa\AppData\Local\Temp\tmpy60siv75\extracted\fastapi-fastapi-79cab5b\fastapi"
    if not os.path.exists(repo_path):
        pytest.skip("FastAPI extracted source not found at temp path")

    # Q1: openapi in applications.py & get_openapi in openapi/utils.py
    app_py = os.path.join(repo_path, "applications.py")
    with open(app_py, "r", encoding="utf-8") as f:
        app_text = f.read()
    assert "def openapi(self) -> dict[str, Any]:" in app_text
    assert "def setup(self) -> None:" in app_text

    utils_py = os.path.join(repo_path, "openapi", "utils.py")
    with open(utils_py, "r", encoding="utf-8") as f:
        utils_text = f.read()
    assert "def get_openapi(" in utils_text

    # Q6: class APIRoute(routing.Route) in routing.py
    routing_py = os.path.join(repo_path, "routing.py")
    with open(routing_py, "r", encoding="utf-8") as f:
        routing_text = f.read()
    assert "class APIRoute(routing.Route):" in routing_text
    assert "async def serialize_response(" in routing_text

    # Q7: jsonable_encoder in encoders.py
    encoders_py = os.path.join(repo_path, "encoders.py")
    with open(encoders_py, "r", encoding="utf-8") as f:
        encoders_text = f.read()
    assert "def jsonable_encoder(" in encoders_text

    # Q8: TYPE_CHECKING import in utils.py
    fastapi_utils_py = os.path.join(repo_path, "utils.py")
    with open(fastapi_utils_py, "r", encoding="utf-8") as f:
        fastapi_utils_text = f.read()
    assert "if TYPE_CHECKING:" in fastapi_utils_text
    assert "from .routing import APIRoute" in fastapi_utils_text
    assert 'def generate_unique_id(route: "APIRoute") -> str:' in fastapi_utils_text
