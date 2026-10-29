import pytest
from sqlalchemy.orm import Session
from unittest.mock import AsyncMock, patch

from backend.app.models.repository import Repository, IndexedFile, CodeChunk, CodeSymbol
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

