import pytest
from sqlalchemy.orm import Session
from unittest.mock import AsyncMock, patch

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.assistant import AssistantConversation
from backend.app.services.assistant_service import AssistantService
from backend.app.services.architecture_service import ArchitectureAnalysisEngine


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


@pytest.mark.anyio
async def test_phase6_codemind_ai_architecture_grounding(db_session: Session):
    """
    Phase 6: CodeMind AI architecture questions receive grounded architectural descriptions.
    Entry point is main.py, languages are Python/HTML/JS/CSS, models/repository.py is an ORM table,
    and DAO layer is UNVERIFIED/ABSENT.
    """
    repo = Repository(name="CodeMind-AI", full_name="org/CodeMind-AI", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f_main = IndexedFile(repository_id=repo.id, path="backend/app/main.py", lines_count=60)
    f_repo = IndexedFile(repository_id=repo.id, path="backend/app/models/repository.py", lines_count=60)
    db_session.add_all([f_main, f_repo])
    db_session.commit()

    c_main = CodeChunk(repository_id=repo.id, file_id=f_main.id, file_path=f_main.path, chunk_index=0, chunk_text="app = FastAPI()\napp.include_router(api_v1.router, prefix='/api/v1')", content_hash="cm1", language="python", start_line=1, end_line=60)
    c_repo = CodeChunk(repository_id=repo.id, file_id=f_repo.id, file_path=f_repo.path, chunk_index=0, chunk_text="class Repository(Base):\n    __tablename__ = 'repositories'\n    id = Column(Integer, primary_key=True)", content_hash="cm2", language="python", start_line=1, end_line=60)
    db_session.add_all([c_main, c_repo])
    db_session.commit()

    ArchitectureAnalysisEngine.invalidate_cache(repo.id)
    arch = ArchitectureAnalysisEngine.get_repository_architecture(db_session, repo.id)
    assert arch.project_type in ["fullstack", "backend"]
    assert "Entry: main.py" in [c.name for c in arch.get_components_of_type("entry_point")]

    # Persistence should NOT tag models/repository.py as a DAO repository
    dao_repos = [c for c in arch.get_components_of_type("persistence") if c.metadata.get("sub_type") == "repository"]
    assert len(dao_repos) == 0

    # Answer sanitization should reject claiming models/repository.py defines languages
    raw = "backend/app/models/repository.py defines the primary languages of CodeMind AI."
    sanitized = AssistantService._validate_and_sanitize_answer(raw, [c_main, c_repo], repo.name, "Explain architecture")
    assert "defines the primary languages" not in sanitized
    assert "SQLAlchemy database model" in sanitized


@pytest.mark.anyio
async def test_phase6_request_tracing_call_chain_accuracy(db_session: Session):
    """
    Phase 6: Request tracing accurately identifies route handler send_conversation_message,
    dependency get_current_user_record, service AssistantService.answer_question, and AssistantMessage persistence.
    get_current_user_record is an auth dependency, not the route entry point.
    """
    repo = Repository(name="CodeMind-AI", full_name="org/CodeMind-AI", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f_main = IndexedFile(repository_id=repo.id, path="backend/app/main.py", lines_count=60)
    f_route = IndexedFile(repository_id=repo.id, path="backend/app/api/routes/api_v1.py", lines_count=1300)
    f_svc = IndexedFile(repository_id=repo.id, path="backend/app/services/assistant_service.py", lines_count=3500)
    f_model = IndexedFile(repository_id=repo.id, path="backend/app/models/assistant.py", lines_count=60)
    db_session.add_all([f_main, f_route, f_svc, f_model])
    db_session.commit()

    c_main = CodeChunk(repository_id=repo.id, file_id=f_main.id, file_path=f_main.path, chunk_index=0, chunk_text="app.include_router(api_v1.router, prefix='/api/v1')", content_hash="tr1", language="python", start_line=19, end_line=60)
    c_route = CodeChunk(repository_id=repo.id, file_id=f_route.id, file_path=f_route.path, code_symbol="send_conversation_message", chunk_index=0, chunk_text="@router.post('/assistant/conversations/{conversation_id}/messages')\nasync def send_conversation_message(): pass", content_hash="tr2", language="python", start_line=1144, end_line=1200)
    c_auth = CodeChunk(repository_id=repo.id, file_id=f_route.id, file_path=f_route.path, code_symbol="get_current_user_record", chunk_index=1, chunk_text="async def get_current_user_record(): pass", content_hash="tr3", language="python", start_line=74, end_line=122)
    c_svc = CodeChunk(repository_id=repo.id, file_id=f_svc.id, file_path=f_svc.path, code_symbol="AssistantService.answer_question", chunk_index=0, chunk_text="async def answer_question(): pass", content_hash="tr4", language="python", start_line=3249, end_line=3300)
    c_model = CodeChunk(repository_id=repo.id, file_id=f_model.id, file_path=f_model.path, code_symbol="AssistantMessage", chunk_index=0, chunk_text="class AssistantMessage(Base): pass", content_hash="tr5", language="python", start_line=34, end_line=51)
    db_session.add_all([c_main, c_route, c_auth, c_svc, c_model])
    db_session.commit()

    ArchitectureAnalysisEngine.invalidate_cache(repo.id)
    chunks, note = AssistantService._extract_verified_request_flow(
        db=db_session,
        repository_id=repo.id,
        question="Trace a real request from API entry point through routing and business logic to database persistence.",
    )

    assert note is not None
    assert "send_conversation_message" in note
    assert "get_current_user_record" in note
    assert "AssistantService.answer_question" in note
    assert "AssistantMessage" in note
    assert "get_current_user_record" in note
    assert "authentication dependency" in note

    # Sanitization check
    raw = "The route handler is get_current_user_record."
    sanitized = AssistantService._validate_and_sanitize_answer(raw, chunks, repo.name, "Trace request")
    assert "send_conversation_message" in sanitized


@pytest.mark.anyio
async def test_phase6_authentication_flow_grounding_and_no_token_encryption(db_session: Session):
    """
    Phase 6: Authentication flow cites auth.py, security.py, user_session.py, api_v1.py.
    Does NOT describe token_encryption.py as login token creator or JWT validator.
    """
    repo = Repository(name="CodeMind-AI", full_name="org/CodeMind-AI", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f_auth = IndexedFile(repository_id=repo.id, path="backend/app/api/routes/auth.py", lines_count=270)
    f_sec = IndexedFile(repository_id=repo.id, path="backend/app/core/security.py", lines_count=500)
    f_enc = IndexedFile(repository_id=repo.id, path="backend/app/core/token_encryption.py", lines_count=230)
    db_session.add_all([f_auth, f_sec, f_enc])
    db_session.commit()

    c_auth = CodeChunk(repository_id=repo.id, file_id=f_auth.id, file_path=f_auth.path, code_symbol="login", chunk_index=0, chunk_text="@router.post('/login')\ndef login(): pass", content_hash="a1", language="python", start_line=186, end_line=245)
    c_sec = CodeChunk(repository_id=repo.id, file_id=f_sec.id, file_path=f_sec.path, code_symbol="create_session_token", chunk_index=0, chunk_text="def create_session_token(): pass", content_hash="a2", language="python", start_line=159, end_line=182)
    c_enc = CodeChunk(repository_id=repo.id, file_id=f_enc.id, file_path=f_enc.path, code_symbol="encrypt_token", chunk_index=0, chunk_text="def encrypt_token(): pass", content_hash="a3", language="python", start_line=203, end_line=220)
    db_session.add_all([c_auth, c_sec, c_enc])
    db_session.commit()

    ArchitectureAnalysisEngine.invalidate_cache(repo.id)
    chunks, notes, meta = AssistantService._enrich_multi_layer_retrieval(
        db=db_session,
        repository_id=repo.id,
        question="Explain the authentication flow from login to token creation and protected endpoint access.",
        retrieved_chunks=[c_enc],
        intents=["AUTH", "REQUEST_FLOW"],
    )

    # token_encryption.py must be excluded from login query retrieval
    assert not any("token_encryption.py" in c.file_path for c in chunks)
    assert any("auth.py" in c.file_path for c in chunks)
    assert notes is not None
    assert "token_encryption.py" in notes
    assert "AES-256-GCM" in notes


@pytest.mark.anyio
async def test_phase6_feature_end_to_end_no_hallucinated_repository_service(db_session: Session):
    """
    Phase 6: End-to-end feature tracing does not invent repository_service.py.
    Sanitizes any hallucinated repository_service.py.
    """
    repo = Repository(name="CodeMind-AI", full_name="org/CodeMind-AI", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    raw = "The request calls backend/app/services/repository_service.py:12-100 to sync the repo."
    sanitized = AssistantService._validate_and_sanitize_answer(raw, [], repo.name, "Trace feature")
    assert "repository_service" not in sanitized
    assert "github_sync_service.py" in sanitized


@pytest.mark.anyio
async def test_phase6_fincell_flutter_architecture_components(db_session: Session):
    """
    Phase 6: FinCell mobile architecture identifies lib/main.dart runtime entry point,
    Flutter UI screens, Dart services, and Android native integration.
    Excludes LaunchScreen.storyboard and does not claim pubspec.yaml is runtime entry point.
    """
    repo = Repository(name="FinCell", full_name="org/FinCell", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f_main = IndexedFile(repository_id=repo.id, path="lib/main.dart", lines_count=50)
    f_home = IndexedFile(repository_id=repo.id, path="lib/home/home_page.dart", lines_count=100)
    f_svc = IndexedFile(repository_id=repo.id, path="lib/services/device_service.dart", lines_count=80)
    f_manifest = IndexedFile(repository_id=repo.id, path="android/app/src/main/AndroidManifest.xml", lines_count=60)
    f_kt = IndexedFile(repository_id=repo.id, path="android/app/src/main/kotlin/com/example/fincell/MainActivity.kt", lines_count=20)
    f_storyboard = IndexedFile(repository_id=repo.id, path="ios/Runner/Base.lproj/LaunchScreen.storyboard", lines_count=30)
    db_session.add_all([f_main, f_home, f_svc, f_manifest, f_kt, f_storyboard])
    db_session.commit()

    c_main = CodeChunk(repository_id=repo.id, file_id=f_main.id, file_path=f_main.path, chunk_index=0, chunk_text="void main() => runApp(FinCellApp());", content_hash="fc1", language="dart", start_line=1, end_line=50)
    c_home = CodeChunk(repository_id=repo.id, file_id=f_home.id, file_path=f_home.path, chunk_index=0, chunk_text="class HomePage extends StatefulWidget {}", content_hash="fc2", language="dart", start_line=1, end_line=100)
    c_svc = CodeChunk(repository_id=repo.id, file_id=f_svc.id, file_path=f_svc.path, chunk_index=0, chunk_text="class DeviceService {}", content_hash="fc3", language="dart", start_line=1, end_line=80)
    c_manifest = CodeChunk(repository_id=repo.id, file_id=f_manifest.id, file_path=f_manifest.path, chunk_index=0, chunk_text="<manifest xmlns:android='...'>", content_hash="fc4", language="xml", start_line=1, end_line=60)
    c_kt = CodeChunk(repository_id=repo.id, file_id=f_kt.id, file_path=f_kt.path, chunk_index=0, chunk_text="class MainActivity: FlutterActivity() {}", content_hash="fc5", language="kotlin", start_line=1, end_line=20)
    c_sb = CodeChunk(repository_id=repo.id, file_id=f_storyboard.id, file_path=f_storyboard.path, chunk_index=0, chunk_text="<document type='com.apple.InterfaceBuilder3'>", content_hash="fc6", language="xml", start_line=1, end_line=30)
    db_session.add_all([c_main, c_home, c_svc, c_manifest, c_kt, c_sb])
    db_session.commit()

    ArchitectureAnalysisEngine.invalidate_cache(repo.id)
    arch = ArchitectureAnalysisEngine.get_repository_architecture(db_session, repo.id)
    assert arch.project_type == "mobile"

    chunks, notes, meta = AssistantService._enrich_multi_layer_retrieval(
        db=db_session,
        repository_id=repo.id,
        question="Explain the Flutter application architecture, including services, screens, and Android native integration.",
        retrieved_chunks=[c_sb],
        intents=["ARCHITECTURE", "SERVICES"],
        arch=arch,
    )

    # LaunchScreen.storyboard must be excluded
    assert not any("storyboard" in c.file_path for c in chunks)
    # lib/main.dart must be present
    assert any("lib/main.dart" in c.file_path for c in chunks)
    assert notes is not None
    assert "android native platform integration" in notes.lower()
    assert "lib/main.dart" in notes

    # Sanitization check
    raw = "The entry point is pubspec.yaml. Also check LaunchScreen.storyboard."
    sanitized = AssistantService._validate_and_sanitize_answer(raw, chunks, repo.name, "Explain Flutter architecture")
    assert "LaunchScreen.storyboard" not in sanitized
    assert "lib/main.dart" in sanitized


@pytest.mark.anyio
async def test_phase6_citation_to_claim_filtering_and_span_deduplication(db_session: Session):
    """
    Phase 6: Citation-to-Claim validation:
    1. _filter_citations_for_answer prunes unreferenced noise files (docker-compose, mock_provider, etc.).
    2. Keeps only citations whose file, symbol, or line range is discussed in answer.
    3. Orders citations by their first appearance in the answer text.
    4. Renumbers source_index sequentially.
    """
    raw_citations = [
        {"source_index": 1, "file_path": "docker-compose.yml", "start_line": 1, "end_line": 60, "symbol_name": None},
        {"source_index": 2, "file_path": "backend/app/models/security_finding_status.py", "start_line": 7, "end_line": 20, "symbol_name": "SecurityFindingStatus"},
        {"source_index": 3, "file_path": "backend/app/api/routes/api_v1.py", "start_line": 1144, "end_line": 1203, "symbol_name": "send_conversation_message"},
        {"source_index": 4, "file_path": "backend/app/api/routes/api_v1.py", "start_line": 74, "end_line": 122, "symbol_name": "get_current_user_record"},
        {"source_index": 5, "file_path": "backend/app/services/assistant_service.py", "start_line": 3249, "end_line": 3308, "symbol_name": "AssistantService.answer_question"},
        {"source_index": 6, "file_path": "backend/app/integrations/embeddings/mock_provider.py", "start_line": 8, "end_line": 62, "symbol_name": "MockEmbeddingProvider"},
    ]

    answer = (
        "Requests enter through `send_conversation_message` in `backend/app/api/routes/api_v1.py:1144-1272`. "
        "The authentication dependency `get_current_user_record` (`backend/app/api/routes/api_v1.py:74-122`) validates the session. "
        "Then domain logic delegates to `AssistantService.answer_question` in `backend/app/services/assistant_service.py`."
    )

    filtered = AssistantService._filter_citations_for_answer(raw_citations, answer)

    # Noise files must be pruned
    cit_paths = [c["file_path"] for c in filtered]
    assert "docker-compose.yml" not in cit_paths
    assert "backend/app/models/security_finding_status.py" not in cit_paths
    assert "backend/app/integrations/embeddings/mock_provider.py" not in cit_paths

    # Legitimate referenced files must be kept
    assert "backend/app/api/routes/api_v1.py" in cit_paths
    assert "backend/app/services/assistant_service.py" in cit_paths

    # Order must match appearance in answer
    assert filtered[0]["file_path"] == "backend/app/api/routes/api_v1.py"
    assert filtered[0]["start_line"] == 1144
    assert filtered[1]["start_line"] == 74
    assert filtered[2]["file_path"] == "backend/app/services/assistant_service.py"

    # Indices must be sequentially renumbered 1, 2, 3
    assert [c["source_index"] for c in filtered] == [1, 2, 3]

