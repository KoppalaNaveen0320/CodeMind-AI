import asyncio
import hashlib
import json
import uuid
import pytest
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine, RetrievedChunk
from backend.app.services.assistant_service import AssistantService


# ==============================================================================
# Helper Factories
# ==============================================================================

def create_test_user(db: Session, email: str = "audit_user@example.com") -> User:
    user = User(email=email, full_name="Audit Test User")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_chunk(repository_id: int, file_path: str, chunk_index: int, start_line: int, end_line: int, chunk_text: str, code_symbol: str = None, language: str = "python") -> CodeChunk:
    return CodeChunk(
        repository_id=repository_id,
        file_path=file_path,
        chunk_index=chunk_index,
        start_line=start_line,
        end_line=end_line,
        chunk_text=chunk_text,
        content_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
        code_symbol=code_symbol,
        language=language,
    )


# ==============================================================================
# Test 1: Genuinely Absent Feature -> NOT_FOUND_IN_INDEXED_SOURCE
# ==============================================================================

def test_genuinely_absent_feature_returns_not_found_in_indexed_source(db_session: Session):
    """
    When repository is fully indexed (status=ready) and contains no retrieval engine,
    audit must report NOT_FOUND_IN_INDEXED_SOURCE with coverage files (e.g. manifest, entry point),
    and evidence counters must reflect confirmed coverage citations with unknowns=0.
    """
    db = db_session
    user = create_test_user(db, "absent_test@example.com")
    repo = Repository(
        name="MobileFlutterApp",
        full_name="testorg/mobile-flutter-app",
        status="ready",
        files_count=45,
        default_branch="main",
        user_id=user.id,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    # Add indexed files and chunks representing a mobile app with no retrieval engine
    f1 = IndexedFile(repository_id=repo.id, path="pubspec.yaml", language="yaml", lines_count=40)
    f2 = IndexedFile(repository_id=repo.id, path="lib/main.dart", language="dart", lines_count=80)
    f3 = IndexedFile(repository_id=repo.id, path="lib/ui/home_screen.dart", language="dart", lines_count=120)
    db.add_all([f1, f2, f3])
    db.commit()

    c1 = make_chunk(
        repository_id=repo.id,
        file_path="pubspec.yaml",
        chunk_index=0,
        start_line=1,
        end_line=40,
        chunk_text="name: mobile_flutter_app\ndependencies:\n  flutter:\n    sdk: flutter\n  provider: ^6.0.0\n  http: ^0.13.0\n",
        language="yaml",
    )
    c2 = make_chunk(
        repository_id=repo.id,
        file_path="lib/main.dart",
        chunk_index=0,
        start_line=1,
        end_line=35,
        chunk_text="void main() {\n  runApp(const MyApp());\n}\n\nclass MyApp extends StatelessWidget {\n  @override\n  Widget build(BuildContext context) => Container();\n}\n",
        code_symbol="main",
        language="dart",
    )
    db.add_all([c1, c2])
    db.commit()

    chunks, domain_notes, audit_meta = AssistantService._enrich_multi_layer_retrieval(
        db=db,
        repository_id=repo.id,
        question="Does MobileFlutterApp implement a hybrid retrieval engine?",
        retrieved_chunks=[],
    )

    # 1. Outcome must be NOT_FOUND_IN_INDEXED_SOURCE
    assert audit_meta.get("retrieval_audit_outcome") == "NOT_FOUND_IN_INDEXED_SOURCE"
    assert audit_meta.get("repo_status") == "ready"
    assert audit_meta.get("indexed_files_count") == 3

    # 2. Coverage evidence must cite actual inspected manifest and/or entry point
    assert domain_notes is not None
    assert "NOT_FOUND_IN_INDEXED_SOURCE" in domain_notes
    assert "pubspec.yaml" in domain_notes
    assert len(chunks) >= 1
    assert any(c.file_path == "pubspec.yaml" for c in chunks)

    # 3. Evidence counters check
    citations = [{"file_path": c.file_path, "start_line": c.start_line, "end_line": c.end_line} for c in chunks]
    answer = f"Hybrid retrieval is NOT_FOUND_IN_INDEXED_SOURCE in repository MobileFlutterApp. Inspected pubspec.yaml."
    facts = AssistantService._calculate_evidence_counters(
        answer=answer,
        citations=citations,
        retrieved_chunks=chunks,
        audit_meta=audit_meta,
    )
    assert facts["confirmed"] >= 1
    assert facts["unknowns"] == 0


# ==============================================================================
# Test 2: Incomplete Indexing -> UNVERIFIED
# ==============================================================================

def test_incomplete_indexing_returns_unverified(db_session: Session):
    """
    When repository status is 'indexing' or file count is incomplete,
    audit must classify the outcome as UNVERIFIED, must NOT declare feature absent,
    and unknowns must reflect the unresolved status (unknowns >= 1).
    """
    db = db_session
    user = create_test_user(db, "incomplete_test@example.com")
    repo = Repository(
        name="IncompleteApp",
        full_name="testorg/incomplete-app",
        status="indexing",
        files_count=100,
        default_branch="main",
        user_id=user.id,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    f1 = IndexedFile(repository_id=repo.id, path="src/partial.py", language="python", lines_count=50)
    db.add(f1)
    db.commit()

    c1 = make_chunk(
        repository_id=repo.id,
        file_path="src/partial.py",
        chunk_index=0,
        start_line=1,
        end_line=25,
        chunk_text="def partial_work():\n    pass\n",
        code_symbol="partial_work",
        language="python",
    )
    db.add(c1)
    db.commit()

    chunks, domain_notes, audit_meta = AssistantService._enrich_multi_layer_retrieval(
        db=db,
        repository_id=repo.id,
        question="Does IncompleteApp implement a hybrid retrieval engine?",
        retrieved_chunks=[],
    )

    # 1. Outcome must be UNVERIFIED
    assert audit_meta.get("retrieval_audit_outcome") == "UNVERIFIED"
    assert audit_meta.get("repo_status") == "indexing"

    # 2. Domain notes must warn of incomplete coverage and forbid claiming feature is absent
    assert domain_notes is not None
    assert "UNVERIFIED" in domain_notes
    assert "Do NOT conclude that the feature is absent" in domain_notes

    # 3. Evidence counters check: unknowns must be >= 1
    citations = [{"file_path": c.file_path, "start_line": c.start_line, "end_line": c.end_line} for c in chunks]
    answer = "The status of hybrid retrieval is UNVERIFIED because repository indexing is in progress."
    facts = AssistantService._calculate_evidence_counters(
        answer=answer,
        citations=citations,
        retrieved_chunks=chunks,
        audit_meta=audit_meta,
    )
    assert facts["unknowns"] >= 1


# ==============================================================================
# Test 3: Failed Indexing -> UNVERIFIED
# ==============================================================================

def test_failed_indexing_returns_unverified(db_session: Session):
    """
    When repository status is 'failed' or has an indexing error,
    audit must classify outcome as UNVERIFIED and report the failure reason.
    """
    db = db_session
    user = create_test_user(db, "failed_test@example.com")
    repo = Repository(
        name="FailedApp",
        full_name="testorg/failed-app",
        status="failed",
        sync_error="AST parse error: tree-sitter crash on malformed file",
        files_count=80,
        default_branch="main",
        user_id=user.id,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    f1 = IndexedFile(repository_id=repo.id, path="src/main.rs", language="rust", lines_count=30)
    db.add(f1)
    db.commit()

    chunks, domain_notes, audit_meta = AssistantService._enrich_multi_layer_retrieval(
        db=db,
        repository_id=repo.id,
        question="Does FailedApp implement hybrid retrieval or full text search?",
        retrieved_chunks=[],
    )

    assert audit_meta.get("retrieval_audit_outcome") == "UNVERIFIED"
    assert "UNVERIFIED" in domain_notes
    assert "failed" in domain_notes.lower()
    assert "tree-sitter crash" in domain_notes


# ==============================================================================
# Test 4: Unrelated Keyword Matches Excluded (e.g. generate_pdf.py & MainActivity.kt)
# ==============================================================================

def test_unrelated_keyword_matches_excluded_from_citations(db_session: Session):
    """
    When a repository contains files that happen to match generic query words like 'engine' or 'implement'
    (e.g. MainActivity.kt with FlutterEngine, generate_pdf.py with ReportLab table styles),
    these spurious chunks must NOT be cited as evidence of a retrieval engine.
    """
    db = db_session
    user = create_test_user(db, "unrelated_words@example.com")
    repo = Repository(
        name="FinCellMock",
        full_name="testorg/fincell-mock",
        status="ready",
        files_count=115,
        default_branch="main",
        user_id=user.id,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    # 1. Add spurious chunks that match 'engine', 'implement', and 'hybrid triangulation'
    f_pdf = IndexedFile(repository_id=repo.id, path="generate_pdf.py", language="python", lines_count=350)
    f_act = IndexedFile(repository_id=repo.id, path="android/MainActivity.kt", language="kotlin", lines_count=50)
    f_pub = IndexedFile(repository_id=repo.id, path="pubspec.yaml", language="yaml", lines_count=58)
    f_main = IndexedFile(repository_id=repo.id, path="lib/main.dart", language="dart", lines_count=100)
    db.add_all([f_pdf, f_act, f_pub, f_main])
    db.commit()

    c_pdf = make_chunk(
        repository_id=repo.id,
        file_path="generate_pdf.py",
        chunk_index=0,
        start_line=191,
        end_line=250,
        chunk_text="def generate_report(filename):\n    # Cellular Tower Triangulation: hybrid triangulation\n    styles = getSampleStyleSheet()\n",
        code_symbol="generate_report",
        language="python",
    )
    c_act = make_chunk(
        repository_id=repo.id,
        file_path="android/MainActivity.kt",
        chunk_index=0,
        start_line=14,
        end_line=30,
        chunk_text="class MainActivity : FlutterFragmentActivity() {\n    // implements FlutterEngine configuration\n}\n",
        code_symbol="MainActivity",
        language="kotlin",
    )
    c_pub = make_chunk(
        repository_id=repo.id,
        file_path="pubspec.yaml",
        chunk_index=0,
        start_line=1,
        end_line=58,
        chunk_text="name: fincell_mock\ndependencies:\n  flutter:\n    sdk: flutter\n  cloud_firestore: ^4.17.5\n",
        language="yaml",
    )
    c_main = make_chunk(
        repository_id=repo.id,
        file_path="lib/main.dart",
        chunk_index=0,
        start_line=1,
        end_line=40,
        chunk_text="void main() => runApp(FinCellApp());\nclass FinCellApp extends StatelessWidget {}\n",
        code_symbol="FinCellApp",
        language="dart",
    )
    db.add_all([c_pdf, c_act, c_pub, c_main])
    db.commit()

    # Pass spurious retrieved chunks into _enrich_multi_layer_retrieval
    spurious_chunks = [
        RetrievedChunk(
            chunk_id=c_pdf.id,
            file_path=c_pdf.file_path,
            symbol_name=c_pdf.code_symbol,
            start_line=c_pdf.start_line,
            end_line=c_pdf.end_line,
            chunk_text=c_pdf.chunk_text,
            score=0.45,
            channels=["keyword"],
            repository_id=repo.id,
        ),
        RetrievedChunk(
            chunk_id=c_act.id,
            file_path=c_act.file_path,
            symbol_name=c_act.code_symbol,
            start_line=c_act.start_line,
            end_line=c_act.end_line,
            chunk_text=c_act.chunk_text,
            score=0.40,
            channels=["exact"],
            repository_id=repo.id,
        ),
    ]

    filtered_chunks, domain_notes, audit_meta = AssistantService._enrich_multi_layer_retrieval(
        db=db,
        repository_id=repo.id,
        question="Does FinCellMock implement a hybrid retrieval engine?",
        retrieved_chunks=spurious_chunks,
    )

    # 1. Spurious chunks MUST be purged
    chunk_paths = [c.file_path for c in filtered_chunks]
    assert "generate_pdf.py" not in chunk_paths, "generate_pdf.py should have been purged"
    assert "android/MainActivity.kt" not in chunk_paths, "MainActivity.kt should have been purged"

    # 2. Genuine coverage chunks must be cited
    assert "pubspec.yaml" in chunk_paths
    assert audit_meta.get("retrieval_audit_outcome") == "NOT_FOUND_IN_INDEXED_SOURCE"


# ==============================================================================
# Test 5: Feature Implemented Under Different Names / Synonyms -> IMPLEMENTED
# ==============================================================================

def test_feature_implemented_under_different_names(db_session: Session):
    """
    When retrieval is implemented under alternate names or synonyms
    (e.g. 'vector_matches', 'rank_bm25', 'rank_fusion', 'MultiStageSearchPipeline'),
    the audit must detect it as IMPLEMENTED and cite the exact file.
    """
    db = db_session
    user = create_test_user(db, "synonyms_test@example.com")
    repo = Repository(
        name="SearchPlatform",
        full_name="testorg/search-platform",
        status="ready",
        files_count=60,
        default_branch="main",
        user_id=user.id,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    f1 = IndexedFile(repository_id=repo.id, path="src/search/pipeline.py", language="python", lines_count=150)
    db.add(f1)
    db.commit()

    # Chunk with vector_matches, rank_bm25, and rank_fusion
    c1 = make_chunk(
        repository_id=repo.id,
        file_path="src/search/pipeline.py",
        chunk_index=0,
        start_line=20,
        end_line=95,
        chunk_text="class MultiStageSearchPipeline:\n    async def vector_matches(self, query):\n        # semantic similarity via pgvector\n        pass\n\n    def rank_bm25_search(self, query):\n        # full text keyword matching\n        pass\n\n    def rank_fusion(self, v_results, kw_results):\n        # reciprocal_rank fusion combination\n        pass\n",
        code_symbol="MultiStageSearchPipeline",
        language="python",
    )
    db.add(c1)
    db.commit()

    chunks, domain_notes, audit_meta = AssistantService._enrich_multi_layer_retrieval(
        db=db,
        repository_id=repo.id,
        question="Does SearchPlatform implement a hybrid retrieval engine?",
        retrieved_chunks=[],
    )

    # 1. Must recognize the implementation under synonyms as IMPLEMENTED
    assert audit_meta.get("retrieval_audit_outcome") == "IMPLEMENTED"
    assert "IMPLEMENTED" in domain_notes
    assert "src/search/pipeline.py" in audit_meta.get("retrieval_files", [])

    # 2. Evidence chunk must be present
    assert any(c.file_path == "src/search/pipeline.py" for c in chunks)

    # 3. Evidence counters check: confirmed >= 1, unknowns == 0
    citations = [{"file_path": c.file_path, "start_line": c.start_line, "end_line": c.end_line} for c in chunks]
    answer = "Hybrid retrieval is implemented in `src/search/pipeline.py:20-95` via MultiStageSearchPipeline combining vector_matches and rank_bm25 with rank_fusion."
    facts = AssistantService._calculate_evidence_counters(
        answer=answer,
        citations=citations,
        retrieved_chunks=chunks,
        audit_meta=audit_meta,
    )
    assert facts["confirmed"] >= 1
    assert facts["unknowns"] == 0


# ==============================================================================
# Test 6: End-to-End FinCell QA Negative Detection & Citation Verification
# ==============================================================================

@pytest.mark.anyio
async def test_fincell_e2e_answer_question_negative_detection_and_citations(db_session: Session):
    """
    End-to-End test verifying that when asked whether the FinCell repository implements a hybrid retrieval engine:
    1. CodeMind inspects the actual retrieval pipeline and indexed source coverage.
    2. Reports NOT_FOUND_IN_INDEXED_SOURCE with verified manifest and entry point evidence.
    3. Excludes spurious files (generate_pdf.py with 'hybrid triangulation' and MainActivity.kt with 'FlutterEngine').
    4. Evidence counters accurately reflect confirmed >= 1 and unknowns == 0.
    """
    db = db_session
    user = create_test_user(db, "fincell_e2e@example.com")
    repo = Repository(
        name="FinCell",
        full_name="fintech/FinCell",
        status="ready",
        files_count=4,
        default_branch="main",
        user_id=user.id,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    # Add indexed files and code chunks representing the FinCell repository
    f_pdf = IndexedFile(repository_id=repo.id, path="generate_pdf.py", language="python", lines_count=350)
    f_act = IndexedFile(repository_id=repo.id, path="android/MainActivity.kt", language="kotlin", lines_count=50)
    f_pub = IndexedFile(repository_id=repo.id, path="pubspec.yaml", language="yaml", lines_count=58)
    f_main = IndexedFile(repository_id=repo.id, path="lib/main.dart", language="dart", lines_count=100)
    db.add_all([f_pdf, f_act, f_pub, f_main])
    db.commit()

    c_pdf = make_chunk(
        repository_id=repo.id,
        file_path="generate_pdf.py",
        chunk_index=0,
        start_line=191,
        end_line=250,
        chunk_text="def generate_report(filename):\n    # Cellular Tower Triangulation: hybrid triangulation\n    styles = getSampleStyleSheet()\n",
        code_symbol="generate_report",
        language="python",
    )
    c_act = make_chunk(
        repository_id=repo.id,
        file_path="android/MainActivity.kt",
        chunk_index=0,
        start_line=14,
        end_line=30,
        chunk_text="class MainActivity : FlutterFragmentActivity() {\n    // implements FlutterEngine configuration\n}\n",
        code_symbol="MainActivity",
        language="kotlin",
    )
    c_pub = make_chunk(
        repository_id=repo.id,
        file_path="pubspec.yaml",
        chunk_index=0,
        start_line=1,
        end_line=58,
        chunk_text="name: fincell\ndependencies:\n  flutter:\n    sdk: flutter\n  dio: ^5.0.0\n",
        language="yaml",
    )
    c_main = make_chunk(
        repository_id=repo.id,
        file_path="lib/main.dart",
        chunk_index=0,
        start_line=1,
        end_line=40,
        chunk_text="void main() => runApp(const FinCellApp());\nclass FinCellApp extends StatelessWidget {}\n",
        code_symbol="FinCellApp",
        language="dart",
    )
    db.add_all([c_pdf, c_act, c_pub, c_main])
    db.commit()

    response = await AssistantService.answer_question(
        db=db,
        repository_id=repo.id,
        question="Does the FinCell repository implement a hybrid retrieval engine?",
        user_id=user.id,
    )

    assert response["status"] == "success"
    answer = response["answer"]
    citations = response["citations"]
    facts = response["facts"]

    # 1. Negative outcome MUST be NOT_FOUND_IN_INDEXED_SOURCE (not UNVERIFIED / ABSENT)
    assert "NOT_FOUND_IN_INDEXED_SOURCE" in answer
    assert "UNVERIFIED / ABSENT" not in answer

    # 2. Spurious matches (generate_pdf.py and MainActivity.kt) MUST be excluded from citations
    cit_paths = [c["file_path"] for c in citations]
    assert "generate_pdf.py" not in cit_paths
    assert "android/MainActivity.kt" not in cit_paths

    # 3. Relevant coverage evidence (pubspec.yaml or lib/main.dart) MUST be cited
    assert any("pubspec.yaml" in p for p in cit_paths)

    # 4. Verified facts counter reflects inspected coverage evidence with unknowns == 0
    assert facts["confirmed"] >= 1
    assert facts["unknowns"] == 0

