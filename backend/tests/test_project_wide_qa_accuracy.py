import pytest
from sqlalchemy.orm import Session
from unittest.mock import AsyncMock, patch

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.assistant import AssistantConversation
from backend.app.services.assistant_service import AssistantService


@pytest.mark.anyio
async def test_broad_overview_intent_and_layer_enrichment(db_session: Session):
    """
    Verifies that broad repository explanation inquiries:
    - Are classified with PROJECT_OVERVIEW and ARCHITECTURE intents.
    - Trigger multi-layer architecture discovery across entry points, config, routes, and services.
    - Exclude build/Xcode artifacts from sampled architecture layers.
    """
    repo = Repository(name="broad-test-app", full_name="acme/broad-test-app", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f_main = IndexedFile(repository_id=repo.id, path="lib/main.dart", lines_count=60)
    f_conf = IndexedFile(repository_id=repo.id, path="pubspec.yaml", lines_count=40)
    f_screen = IndexedFile(repository_id=repo.id, path="lib/screens/home_screen.dart", lines_count=80)
    f_xcode = IndexedFile(repository_id=repo.id, path="ios/Runner.xcodeproj/project.pbxproj", lines_count=500)
    db_session.add_all([f_main, f_conf, f_screen, f_xcode])
    db_session.commit()

    c_main = CodeChunk(
        repository_id=repo.id,
        file_id=f_main.id,
        file_path=f_main.path,
        code_symbol="main",
        chunk_index=0,
        chunk_text="void main() { runApp(const MyApp()); }",
        content_hash="h_main",
        language="dart",
        start_line=1,
        end_line=20,
    )
    c_conf = CodeChunk(
        repository_id=repo.id,
        file_id=f_conf.id,
        file_path=f_conf.path,
        code_symbol=None,
        chunk_index=0,
        chunk_text="name: broad_test_app\ndependencies:\n  flutter:\n    sdk: flutter",
        content_hash="h_conf",
        language="yaml",
        start_line=1,
        end_line=15,
    )
    c_screen = CodeChunk(
        repository_id=repo.id,
        file_id=f_screen.id,
        file_path=f_screen.path,
        code_symbol="HomeScreen",
        chunk_index=0,
        chunk_text="class HomeScreen extends StatelessWidget { Widget build(BuildContext context) { return Container(); } }",
        content_hash="h_screen",
        language="dart",
        start_line=1,
        end_line=30,
    )
    c_xcode = CodeChunk(
        repository_id=repo.id,
        file_id=f_xcode.id,
        file_path=f_xcode.path,
        code_symbol=None,
        chunk_index=0,
        chunk_text="// !$*UTF8*$!\n{\n\tarchiveVersion = 1;\n\tclasses = {\n\t};\n}",
        content_hash="h_xcode",
        language="text",
        start_line=1,
        end_line=25,
    )
    db_session.add_all([c_main, c_conf, c_screen, c_xcode])
    db_session.commit()

    q = "Explain this repository."
    intents = AssistantService.classify_query_intent(q)
    assert "PROJECT_OVERVIEW" in intents
    assert "ARCHITECTURE" in intents

    enriched_chunks, notes, audit_meta = AssistantService._enrich_multi_layer_retrieval(
        db=db_session,
        repository_id=repo.id,
        question=q,
        retrieved_chunks=[],
        intents=intents,
    )
    # Layer discovery must sample main and config, but discard Xcode internal project files
    sampled_paths = {c.file_path for c in enriched_chunks}
    assert "lib/main.dart" in sampled_paths
    assert "pubspec.yaml" in sampled_paths
    assert "ios/Runner.xcodeproj/project.pbxproj" not in sampled_paths


@pytest.mark.anyio
async def test_narrow_code_inquiry_not_misclassified_as_general_programming(db_session: Session):
    """
    Verifies that questions inquiring about functions, methods, or components in the codebase
    (such as 'What does the main function do?' or 'Explain `calculate_total()`')
    are recognized as repository inquiries and not intercepted as generic computer science questions.
    """
    repo = Repository(name="entry-test-repo", full_name="acme/entry-test-repo", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f_main = IndexedFile(repository_id=repo.id, path="core/main.py", lines_count=30)
    db_session.add(f_main)
    db_session.commit()

    c_main = CodeChunk(
        repository_id=repo.id,
        file_id=f_main.id,
        file_path=f_main.path,
        code_symbol="main",
        chunk_index=0,
        chunk_text="def main():\n    print('Starting service worker on port 8080')\n    return 0",
        content_hash="h_main_py",
        language="python",
        start_line=1,
        end_line=15,
    )
    db_session.add(c_main)
    db_session.commit()

    q1 = "What does the main function do?"
    intents1 = AssistantService.classify_query_intent(q1)
    assert "GENERAL_PROGRAMMING" not in intents1

    q2 = "Explain `calculate_total()` in this codebase."
    intents2 = AssistantService.classify_query_intent(q2)
    assert "GENERAL_PROGRAMMING" not in intents2


@pytest.mark.anyio
async def test_feature_existence_audit_positive_and_negative(db_session: Session):
    """
    Verifies that queries asking whether a feature is implemented:
    - Return IMPLEMENTED with citations when the code exists.
    - Return NOT_FOUND_IN_INDEXED_SOURCE with structural coverage confirmation when it does not exist.
    """
    repo = Repository(name="feature-audit-repo", full_name="acme/feature-audit-repo", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f_cache = IndexedFile(repository_id=repo.id, path="services/cache_service.py", lines_count=50)
    f_req = IndexedFile(repository_id=repo.id, path="requirements.txt", lines_count=10)
    db_session.add_all([f_cache, f_req])
    db_session.commit()

    c_cache = CodeChunk(
        repository_id=repo.id,
        file_id=f_cache.id,
        file_path=f_cache.path,
        code_symbol="get_cached_item",
        chunk_index=0,
        chunk_text="def get_cached_item(key: str):\n    return in_memory_cache.get(key)",
        content_hash="h_cache",
        language="python",
        start_line=1,
        end_line=20,
    )
    c_req = CodeChunk(
        repository_id=repo.id,
        file_id=f_req.id,
        file_path=f_req.path,
        code_symbol=None,
        chunk_index=0,
        chunk_text="fastapi==0.100.0\nuvicorn==0.22.0",
        content_hash="h_req",
        language="text",
        start_line=1,
        end_line=10,
    )
    db_session.add_all([c_cache, c_req])
    db_session.commit()

    # Query 1: Implemented feature (caching)
    q1 = "Is caching implemented in this repository?"
    intents1 = AssistantService.classify_query_intent(q1)
    assert "FEATURE_AUDIT" in intents1

    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q1,
    )
    assert len(res1["citations"]) > 0
    assert any("cache_service.py" in c["file_path"] for c in res1["citations"])

    # Query 2: Absent feature (stripe payment processing)
    q2 = "Is stripe payment processing implemented in this repository?"
    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q2,
    )
    assert "NOT_FOUND_IN_INDEXED_SOURCE" in res2["answer"] or "not found" in res2["answer"].lower()
    assert res2["risk_callout"]["summary"] == "No change impact analysis performed for informational inquiry."


@pytest.mark.anyio
async def test_entry_point_classification_excludes_services(db_session: Session):
    """
    Verifies that ArchitectureAnalysisEngine._discover_entry_points:
    - Never classifies files in services/, models/, schemas/, utils/, or alembic/ as entry_point.
    - Successfully identifies priority entry points like backend/app/main.py and lib/main.dart.
    """
    from backend.app.services.architecture_service import ArchitectureAnalysisEngine, DiscoveredComponent

    repo = Repository(name="entry-point-test-repo", full_name="acme/entry-point-test-repo", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f_svc = IndexedFile(repository_id=repo.id, path="backend/app/services/assistant_service.py", lines_count=100)
    f_main = IndexedFile(repository_id=repo.id, path="backend/app/main.py", lines_count=50)
    f_schema = IndexedFile(repository_id=repo.id, path="backend/app/schemas/auth.py", lines_count=40)
    db_session.add_all([f_svc, f_main, f_schema])
    db_session.commit()

    c_svc = CodeChunk(
        repository_id=repo.id,
        file_id=f_svc.id,
        file_path=f_svc.path,
        code_symbol="main",
        chunk_index=0,
        chunk_text='def main():\n    print("Scratch runner")\nif __name__ == "__main__":\n    main()',
        content_hash="h_svc_main",
        language="python",
        start_line=1,
        end_line=10,
    )
    c_main = CodeChunk(
        repository_id=repo.id,
        file_id=f_main.id,
        file_path=f_main.path,
        code_symbol="lifespan",
        chunk_index=0,
        chunk_text='app = FastAPI(title="App")\napp.include_router(router)',
        content_hash="h_main_app",
        language="python",
        start_line=1,
        end_line=20,
    )
    db_session.add_all([c_svc, c_main])
    db_session.commit()

    discovered = []
    def add_comp(comp):
        discovered.append(comp)

    ArchitectureAnalysisEngine._discover_entry_points([c_svc, c_main], [f_svc.path, f_main.path], add_comp)

    entry_files = [c.file_path for c in discovered if c.component_type == "entry_point"]
    assert "backend/app/main.py" in entry_files
    assert "backend/app/services/assistant_service.py" not in entry_files


@pytest.mark.anyio
async def test_cross_repository_resolution_and_scope_guard(db_session: Session):
    """
    Verifies that resolve_repository_from_query:
    - Correctly targets a named repository (e.g. FinCell) even when active_repo_id points to another repo.
    - Does not let phrases like 'this project' or 'the repository' override an explicit repository name.
    """
    repo_cm = Repository(name="CodeMind-AI", full_name="acme/CodeMind-AI", is_private=False, status="ready")
    repo_fc = Repository(name="FinCell", full_name="acme/FinCell", is_private=False, status="ready")
    db_session.add_all([repo_cm, repo_fc])
    db_session.commit()

    # 1. Explicit other repo mention with "for this project"
    q1 = "Explain FinCell's architecture for this project"
    target1, norm1, clar1 = AssistantService.resolve_repository_from_query(
        db=db_session,
        question=q1,
        active_repo_id=repo_cm.id,
    )
    assert target1 is not None
    assert target1.name == "FinCell"
    assert clar1 is None

    # 2. Deictic reference without repository name -> stays on active repo
    q2 = "Explain this repository architecture"
    target2, norm2, clar2 = AssistantService.resolve_repository_from_query(
        db=db_session,
        question=q2,
        active_repo_id=repo_cm.id,
    )
    assert target2 is not None
    assert target2.name == "CodeMind-AI"


@pytest.mark.anyio
async def test_cross_repository_sanitization_no_hybrid_leakage(db_session: Session):
    """
    Verifies that _validate_and_sanitize_answer:
    - Never injects backend/app/retrieval/hybrid_engine.py or config.py citations
      into answers for repositories that do not contain hybrid_engine evidence.
    """
    from backend.app.retrieval.hybrid_engine import RetrievedChunk

    chunks = [
        RetrievedChunk(
            chunk_id=1,
            file_path="lib/services/crypto_service.dart",
            symbol_name="calculateScore",
            start_line=10,
            end_line=30,
            chunk_text="double calculateScore(double a, double b) => a * 0.7 + b * 0.3;",
            score=0.90,
            channels=["keyword"],
            repository_id=99,
        )
    ]

    raw_answer = "The scoring formula combines vector and keyword scores for rank fusion."
    sanitized = AssistantService._validate_and_sanitize_answer(
        answer=raw_answer,
        chunks=chunks,
        repo_name="FinCell",
        question="How is the final hybrid retrieval score calculated?",
        audit_meta={"is_score_combination_query": True},
    )

    assert "backend/app/retrieval/hybrid_engine.py" not in sanitized
    assert "backend/app/core/config.py" not in sanitized


@pytest.mark.anyio
async def test_token_encryption_not_described_as_login_or_jwt_validation(db_session: Session):
    """
    Verifies that _validate_and_sanitize_answer:
    - Sanitizes claims that token_encryption.py creates user login tokens or uses jwt.decode.
    - Correctly grounds token_encryption.py as AES-256-GCM encryption at rest.
    """
    from backend.app.retrieval.hybrid_engine import RetrievedChunk

    chunks = [
        RetrievedChunk(
            chunk_id=10,
            file_path="backend/app/core/token_encryption.py",
            symbol_name="TokenEncryptionService",
            start_line=1,
            end_line=50,
            chunk_text="class TokenEncryptionService:\n    pass",
            score=0.95,
            channels=["auth"],
            repository_id=41,
        )
    ]

    hallucinated = "The token creation and validation are implemented in backend/app/core/token_encryption.py, which uses jwt.decode to validate JWTs."
    sanitized = AssistantService._validate_and_sanitize_answer(
        answer=hallucinated,
        chunks=chunks,
        repo_name="CodeMind-AI",
        question="Explain how authentication works in this repository",
        audit_meta={"jwt_decode_count": 0},
    )

    assert "uses jwt.decode" not in sanitized
    assert "AES-256-GCM" in sanitized
    assert "UNVERIFIED / ABSENT" in sanitized


@pytest.mark.anyio
async def test_request_flow_starts_at_route_handler_not_service(db_session: Session):
    """
    Verifies that _extract_verified_request_flow:
    - Establishes that API requests enter through API route handlers and delegate to service modules.
    - Explicitly instructs that service modules are not API entry points.
    """
    from backend.app.services.architecture_service import ArchitectureAnalysisEngine

    repo = Repository(name="request-flow-repo", full_name="acme/request-flow-repo", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f_main = IndexedFile(repository_id=repo.id, path="backend/app/main.py", lines_count=50)
    f_route = IndexedFile(repository_id=repo.id, path="backend/app/api/routes/api_v1.py", lines_count=100)
    f_svc = IndexedFile(repository_id=repo.id, path="backend/app/services/assistant_service.py", lines_count=120)
    f_model = IndexedFile(repository_id=repo.id, path="backend/app/models/repository.py", lines_count=60)
    db_session.add_all([f_main, f_route, f_svc, f_model])
    db_session.commit()

    c_main = CodeChunk(repository_id=repo.id, file_id=f_main.id, file_path=f_main.path, code_symbol=None, chunk_index=0, chunk_text="app = FastAPI()", content_hash="h1", language="python", start_line=1, end_line=20)
    c_route = CodeChunk(repository_id=repo.id, file_id=f_route.id, file_path=f_route.path, code_symbol="get_repo", chunk_index=0, chunk_text="@router.get('/repos')\ndef get_repo(): pass", content_hash="h2", language="python", start_line=1, end_line=30)
    c_svc = CodeChunk(repository_id=repo.id, file_id=f_svc.id, file_path=f_svc.path, code_symbol="AssistantService", chunk_index=0, chunk_text="class AssistantService: pass", content_hash="h3", language="python", start_line=1, end_line=40)
    c_model = CodeChunk(repository_id=repo.id, file_id=f_model.id, file_path=f_model.path, code_symbol="Repository", chunk_index=0, chunk_text="class Repository(Base): pass", content_hash="h4", language="python", start_line=1, end_line=50)
    db_session.add_all([c_main, c_route, c_svc, c_model])
    db_session.commit()

    ArchitectureAnalysisEngine.invalidate_cache(repo.id)
    chunks, note = AssistantService._extract_verified_request_flow(
        db=db_session,
        repository_id=repo.id,
        question="Trace one real user request from the API entry point",
    )

    assert note is not None
    assert "API Entry Point & Request Routing" in note
    assert "Never describe a service module" in note
    assert "as an API entry point" in note

