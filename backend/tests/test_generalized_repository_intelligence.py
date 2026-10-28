import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.user import User
from backend.app.services.architecture_service import ArchitectureAnalysisEngine, RepositoryArchitecture
from backend.app.services.assistant_service import AssistantService
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine, RetrievedChunk


@pytest.fixture
def gen_user(db_session: Session) -> User:
    user = db_session.query(User).filter(User.email == "gen_intelligence@codemind.dev").first()
    if not user:
        user = User(
            email="gen_intelligence@codemind.dev",
            full_name="Gen Intelligence User",
            workspace_name="General Workspace",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
    return user


# =========================================================================
# 1. Broad Architecture Questions Requiring Multi-File Evidence
# =========================================================================
@pytest.mark.anyio
async def test_broad_architecture_multi_layer_discovery(db_session: Session, gen_user: User):
    """
    Verifies that for broad architecture queries, the system discovers and retrieves
    diverse evidence across entry points, routes, services, repositories, and models.
    """
    repo = Repository(name="enterprise-order-hub", full_name="acme/enterprise-order-hub", user_id=gen_user.id)
    db_session.add(repo)
    db_session.commit()

    layers = [
        ("cmd/server/main.py", "from fastapi import FastAPI\napp = FastAPI()\napp.include_router(orders.router)"),
        ("app/api/orders.py", "@router.post('/orders')\ndef create_order(): return OrderService.process()"),
        ("app/services/order_service.py", "class OrderService:\n    @staticmethod\n    def process(): return OrderRepository.save()"),
        ("app/repositories/order_repository.py", "class OrderRepository:\n    @staticmethod\n    def save(): return db.commit()"),
        ("app/models/order.py", "class Order(Base):\n    __tablename__ = 'orders'\n    id = Column(Integer, primary_key=True)"),
        ("app/config/settings.py", "class Settings(BaseSettings):\n    DATABASE_URL: str = 'postgresql://localhost'"),
    ]

    for path, code in layers:
        f = IndexedFile(repository_id=repo.id, path=path, lines_count=30)
        db_session.add(f)
        db_session.commit()
        db_session.add(CodeChunk(
            repository_id=repo.id, file_id=f.id, file_path=path, chunk_index=0,
            chunk_text=code, content_hash=f"hash_{path}", language="python", start_line=1, end_line=25
        ))
    db_session.commit()

    arch = ArchitectureAnalysisEngine.get_repository_architecture(db_session, repo.id)
    assert arch.project_type in ("backend", "monolith")
    assert "Python" in arch.primary_languages
    assert "FastAPI" in arch.frameworks

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the complete architecture of this order processing platform.",
        user_id=gen_user.id,
    )

    cited_files = {c["file_path"] for c in res["citations"]}
    assert any("main.py" in p for p in cited_files), "Entry point must be cited"
    assert any("orders.py" in p for p in cited_files), "Route handler must be cited"
    assert any("order_service.py" in p for p in cited_files), "Service must be cited"
    assert any("order_repository.py" in p for p in cited_files), "Repository must be cited"
    assert any("order.py" in p for p in cited_files), "Model must be cited"

    facts = res["facts"]
    assert facts["confirmed"] >= 4
    assert facts["unknowns"] >= 0


# =========================================================================
# 2. Precise File-Path and Symbol Queries Without Overhead
# =========================================================================
@pytest.mark.anyio
async def test_precise_file_and_symbol_query_focus(db_session: Session, gen_user: User):
    """
    Verifies that precise symbol and file-path questions retrieve focused evidence
    without injecting unnecessary multi-layer architecture overhead.
    """
    repo = Repository(name="metric-collector", full_name="acme/metric-collector", user_id=gen_user.id)
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(repository_id=repo.id, path="pkg/calculator/tax.py", lines_count=60)
    f2 = IndexedFile(repository_id=repo.id, path="cmd/server.py", lines_count=100)
    db_session.add_all([f1, f2])
    db_session.commit()

    c1 = CodeChunk(
        repository_id=repo.id, file_id=f1.id, file_path="pkg/calculator/tax.py",
        code_symbol="compute_sales_tax", chunk_index=0,
        chunk_text="def compute_sales_tax(amount: float, rate: float) -> float:\n    return amount * rate\n",
        content_hash="h_tax", language="python", start_line=15, end_line=25
    )
    c2 = CodeChunk(
        repository_id=repo.id, file_id=f2.id, file_path="cmd/server.py",
        code_symbol="start_server", chunk_index=0,
        chunk_text="def start_server(): pass\n",
        content_hash="h_srv", language="python", start_line=1, end_line=15
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    # Query targeting specific function in specific file
    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="How does `compute_sales_tax` work in `pkg/calculator/tax.py`?",
        user_id=gen_user.id,
    )

    cites = res["citations"]
    assert len(cites) >= 1
    assert all("tax.py" in c["file_path"] for c in cites), "Precise query must focus on target file"
    assert not any("server.py" in c["file_path"] for c in cites)


# =========================================================================
# 3. FinCell Architecture Regression Test (Flutter/Dart Mobile Repository)
# =========================================================================
@pytest.mark.anyio
async def test_fincell_architecture_regression(db_session: Session, gen_user: User):
    """
    Regression test for FinCell-style mobile client architectures:
    - Language: Dart
    - Framework: Flutter
    - Project Type: mobile
    - Entry point: lib/main.dart with runApp(FinCellApp())
    - UI layer: screens & widgets
    - State management: controllers / bloc
    - Models: Dart data models
    - External API integration: Dio / HTTP client
    - Verified absence: Backend database / ORM schemas are correctly marked unverified/absent
      from the mobile client codebase without guessing or hallucinating.
    """
    repo = Repository(name="FinCell", full_name="fintech/FinCell", user_id=gen_user.id)
    db_session.add(repo)
    db_session.commit()

    files_data = [
        ("pubspec.yaml", "name: fincell\ndescription: FinCell Banking App\ndependencies:\n  flutter:\n    sdk: flutter\n  dio: ^5.0.0\n"),
        ("lib/main.dart", "void main() {\n  runApp(const FinCellApp());\n}\nclass FinCellApp extends StatelessWidget {\n  const FinCellApp();\n}\n"),
        ("lib/screens/dashboard_screen.dart", "class DashboardScreen extends StatelessWidget {\n  Widget build(BuildContext context) { return Container(); }\n}\n"),
        ("lib/controllers/wallet_controller.dart", "class WalletController {\n  final ApiService apiService = ApiService();\n  void fetchBalance() { apiService.getBalance(); }\n}\n"),
        ("lib/models/transaction.dart", "class Transaction {\n  final String id;\n  final double amount;\n  Transaction({required this.id, required this.amount});\n  factory Transaction.fromJson(Map<String, dynamic> json) => Transaction(id: json['id'], amount: json['amount']);\n}\n"),
        ("lib/services/api_service.dart", "class ApiService {\n  final Dio _dio = Dio();\n  Future<Map<String, dynamic>> getBalance() async { return {}; }\n}\n"),
    ]

    for p, code in files_data:
        f = IndexedFile(repository_id=repo.id, path=p, lines_count=40)
        db_session.add(f)
        db_session.commit()
        db_session.add(CodeChunk(
            repository_id=repo.id, file_id=f.id, file_path=p, chunk_index=0,
            chunk_text=code, content_hash=f"h_{p}", language="dart" if p.endswith(".dart") else "yaml",
            start_line=1, end_line=30
        ))
    db_session.commit()

    arch = ArchitectureAnalysisEngine.get_repository_architecture(db_session, repo.id)
    assert arch.project_type == "mobile", f"Expected mobile project type, got {arch.project_type}"
    assert "Dart" in arch.primary_languages
    assert "Flutter" in arch.frameworks

    entry_comps = arch.get_components_of_type("entry_point")
    assert any("main.dart" in c.file_path for c in entry_comps)

    fe_comps = arch.get_components_of_type("frontend_ui")
    assert any("dashboard_screen.dart" in c.file_path for c in fe_comps)

    svc_comps = arch.get_components_of_type("service")
    assert any("wallet_controller.dart" in c.file_path for c in svc_comps)

    model_comps = arch.get_components_of_type("persistence")
    assert any("transaction.dart" in c.file_path for c in model_comps)

    # Database schemas / ORM persistence should NOT be verified in client repo
    repo_comps = arch.get_components_of_type("repository")
    assert len(repo_comps) == 0

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the architecture of FinCell.",
        user_id=gen_user.id,
    )

    cited_files = {c["file_path"] for c in res["citations"]}
    assert any("main.dart" in p for p in cited_files), "Entry point must be cited"
    assert any("dashboard_screen.dart" in p for p in cited_files), "Dashboard screen must be cited"
    assert any("transaction.dart" in p for p in cited_files), "Transaction model must be cited"

    # Verify no hallucinated backend files
    for c in res["citations"]:
        assert not any(fake in c["file_path"] for fake in ["alembic", "models/user.py", "views.py", "backend/app/main.py"])

    facts = res["facts"]
    assert facts["confirmed"] >= 3
    # Dedicated DAO / database persistence recognized as unverified/absent from client
    assert facts["unknowns"] >= 1


# =========================================================================
# 4. Monorepo and Multi-Platform Project Discovery
# =========================================================================
def test_monorepo_project_type_detection(db_session: Session):
    """Verifies that projects with apps/ and packages/ or services/ are identified as monorepos."""
    repo = Repository(name="platform-monorepo", full_name="acme/platform-monorepo")
    db_session.add(repo)
    db_session.commit()

    file_paths = [
        "apps/web/package.json",
        "apps/web/src/App.tsx",
        "apps/mobile/pubspec.yaml",
        "apps/mobile/lib/main.dart",
        "packages/shared-types/index.ts",
        "packages/ui-components/Button.tsx",
    ]

    for p in file_paths:
        f = IndexedFile(repository_id=repo.id, path=p, lines_count=20)
        db_session.add(f)
        db_session.commit()
        db_session.add(CodeChunk(
            repository_id=repo.id, file_id=f.id, file_path=p, chunk_index=0,
            chunk_text="// content", content_hash=f"h_{p}", language="typescript", start_line=1, end_line=10
        ))
    db_session.commit()

    arch = ArchitectureAnalysisEngine.get_repository_architecture(db_session, repo.id)
    assert arch.project_type == "monorepo"


# =========================================================================
# 5. Stale Evidence & Cache Invalidation on Re-Indexing / Sync
# =========================================================================
def test_cache_invalidation_after_file_modifications(db_session: Session):
    """
    Verifies that modifying repository chunks updates the cache key
    and invalidates stale architecture data immediately.
    """
    repo = Repository(name="sync-cache-test", full_name="acme/sync-cache-test", current_revision="v1")
    db_session.add(repo)
    db_session.commit()

    c1 = CodeChunk(
        repository_id=repo.id, file_path="src/main.py", start_line=1, end_line=10,
        chunk_text="def main(): pass", content_hash="h1", language="python", chunk_index=0
    )
    db_session.add(c1)
    db_session.commit()

    arch1 = ArchitectureAnalysisEngine.get_repository_architecture(db_session, repo.id)
    assert len(arch1.components) >= 1
    assert not any("api_route" == c.component_type for c in arch1.components)

    # Now simulate sync adding a new API route chunk
    c2 = CodeChunk(
        repository_id=repo.id, file_path="src/routes/api.py", start_line=1, end_line=15,
        chunk_text="@router.get('/data')\ndef get_data(): return {}", content_hash="h2", language="python", chunk_index=1
    )
    db_session.add(c2)
    db_session.commit()

    # Retrieve architecture again - must reflect new chunk automatically because chunk count changed
    arch2 = ArchitectureAnalysisEngine.get_repository_architecture(db_session, repo.id)
    route_comps = arch2.get_components_of_type("api_route")
    assert len(route_comps) >= 1
    assert any("routes/api.py" in c.file_path for c in route_comps)


# =========================================================================
# 6. Cross-File Execution Flow Reconstructed from Source Code
# =========================================================================
def test_execution_flow_reconstruction_completeness(db_session: Session):
    """
    Verifies that _extract_verified_request_flow reconstructs all 4 stages:
    Entry point -> Route handler -> Dependency / database session -> Model.
    """
    repo = Repository(name="flow-pipeline-repo", full_name="acme/flow-pipeline-repo")
    db_session.add(repo)
    db_session.commit()

    chunks_data = [
        ("src/main.py", 1, 20, "app = FastAPI()\napp.include_router(auth_router)"),
        ("src/routes/auth.py", 1, 30, "@router.post('/login')\ndef login(db: Session = Depends(get_db)):\n    return db.query(Account).first()"),
        ("src/core/database.py", 1, 25, "def get_db():\n    db = SessionLocal()\n    try:\n        yield db\n    finally:\n        db.close()"),
        ("src/models/account.py", 1, 25, "class Account(Base):\n    __tablename__ = 'accounts'\n    id = Column(Integer, primary_key=True)"),
    ]

    for p, s, e, t in chunks_data:
        db_session.add(CodeChunk(
            repository_id=repo.id, file_path=p, start_line=s, end_line=e,
            chunk_text=t, content_hash=f"h_{p}", chunk_index=0, language="python"
        ))
    db_session.commit()

    flow_chunks, notes = AssistantService._extract_verified_request_flow(
        db=db_session,
        repository_id=repo.id,
        question="Trace an authentication request through the pipeline to database",
    )

    flow_paths = [c.file_path for c in flow_chunks]
    assert "src/main.py" in flow_paths, "Entry point must be in flow"
    assert "src/routes/auth.py" in flow_paths, "Route must be in flow"
    assert "src/core/database.py" in flow_paths, "Database dependency must be in flow"
    assert "src/models/account.py" in flow_paths, "Model must be in flow"
    assert "VERIFIED REQUEST FLOW AUDIT" in notes


# =========================================================================
# 7. Multi-Framework Support: Go Gin & Java Spring Boot
# =========================================================================
def test_go_gin_architecture_discovery(db_session: Session):
    """Verifies that Go Gin applications are recognized with correct entry points, routes, and models."""
    repo = Repository(name="go-service", full_name="acme/go-service")
    db_session.add(repo)
    db_session.commit()

    chunks = [
        ("cmd/main.go", "package main\nimport 'github.com/gin-gonic/gin'\nfunc main() {\n    r := gin.Default()\n    r.GET('/ping', pingHandler)\n}"),
        ("internal/handlers/ping.go", "package handlers\nfunc pingHandler(c *gin.Context) {\n    c.JSON(200, gin.H{'message': 'pong'})\n}"),
        ("internal/models/user.go", "package models\ntype User struct {\n    ID uint `gorm:\"primaryKey\"`\n}"),
    ]

    for p, t in chunks:
        db_session.add(CodeChunk(
            repository_id=repo.id, file_path=p, start_line=1, end_line=20,
            chunk_text=t, content_hash=f"h_{p}", language="go", chunk_index=0
        ))
    db_session.commit()

    arch = ArchitectureAnalysisEngine.get_repository_architecture(db_session, repo.id)
    assert "Go" in arch.primary_languages
    assert "Gin" in arch.frameworks

    entry_comps = arch.get_components_of_type("entry_point")
    assert any("cmd/main.go" in c.file_path for c in entry_comps)

    model_comps = arch.get_components_of_type("persistence")
    assert any("internal/models/user.go" in c.file_path for c in model_comps)


def test_java_spring_boot_architecture_discovery(db_session: Session):
    """Verifies that Java Spring Boot applications are recognized with correct annotations and controllers."""
    repo = Repository(name="spring-service", full_name="acme/spring-service")
    db_session.add(repo)
    db_session.commit()

    chunks = [
        ("src/main/java/com/example/App.java", "@SpringBootApplication\npublic class App {\n    public static void main(String[] args) {}\n}"),
        ("src/main/java/com/example/UserController.java", "@RestController\npublic class UserController {\n    @GetMapping(\"/users\")\n    public List<User> getUsers() {}\n}"),
        ("src/main/java/com/example/User.java", "@Entity\npublic class User {\n    @Id private Long id;\n}"),
    ]

    for p, t in chunks:
        db_session.add(CodeChunk(
            repository_id=repo.id, file_path=p, start_line=1, end_line=20,
            chunk_text=t, content_hash=f"h_{p}", language="java", chunk_index=0
        ))
    db_session.commit()

    arch = ArchitectureAnalysisEngine.get_repository_architecture(db_session, repo.id)
    assert "Java" in arch.primary_languages
    assert "Spring Boot" in arch.frameworks

    entry_comps = arch.get_components_of_type("entry_point")
    assert any("App.java" in c.file_path for c in entry_comps)

    route_comps = arch.get_components_of_type("api_route")
    assert any("UserController.java" in c.file_path for c in route_comps)

    model_comps = arch.get_components_of_type("persistence")
    assert any("User.java" in c.file_path for c in model_comps)


# =========================================================================
# 8. Counter Consistency & Unknown Layer Accounting
# =========================================================================
@pytest.mark.anyio
async def test_counter_consistency_with_unverified_layers(db_session: Session, gen_user: User):
    """
    Verifies that when certain architecture layers (e.g. database or background jobs)
    do not exist in the repository, they are captured in unknowns without guessing.
    """
    repo = Repository(name="stateless-proxy", full_name="acme/stateless-proxy", user_id=gen_user.id)
    db_session.add(repo)
    db_session.commit()

    c_main = CodeChunk(
        repository_id=repo.id, file_path="main.py", start_line=1, end_line=20,
        chunk_text="from fastapi import FastAPI\napp = FastAPI()\n@app.get('/proxy')\ndef proxy(): return {'status': 'ok'}",
        content_hash="h_proxy", language="python", chunk_index=0
    )
    db_session.add(c_main)
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the architecture, storage, and background processing of this proxy.",
        user_id=gen_user.id,
    )

    facts = res["facts"]
    assert facts["confirmed"] >= 1, "Verified entry point and route must be confirmed"
    assert facts["unknowns"] >= 1, "Unverified database models and workers must be recorded as unknowns"


# =========================================================================
# 9. Repository Switching within Conversation Isolates Context
# =========================================================================
@pytest.mark.anyio
async def test_repository_switching_in_conversation_isolates_context(db_session: Session, gen_user: User):
    """
    Verifies that when a conversation switches from Repository A to Repository B,
    Repository A's symbols, citations, and summary do not contaminate Repository B's answer.
    """
    repo_a = Repository(name="project-alpha", full_name="acme/project-alpha", user_id=gen_user.id)
    repo_b = Repository(name="project-beta", full_name="acme/project-beta", user_id=gen_user.id)
    db_session.add_all([repo_a, repo_b])
    db_session.commit()

    chunk_a = CodeChunk(
        repository_id=repo_a.id, file_path="alpha_core.py", start_line=1, end_line=30,
        chunk_text="def execute_alpha():\n    return 'alpha-secret-process'",
        content_hash="h_alpha", language="python", chunk_index=0
    )
    chunk_b = CodeChunk(
        repository_id=repo_b.id, file_path="beta_service.dart", start_line=1, end_line=30,
        chunk_text="class BetaService {\n  void runBeta() => print('beta');\n}",
        content_hash="h_beta", language="dart", chunk_index=0
    )
    db_session.add_all([chunk_a, chunk_b])
    db_session.commit()

    # Step 1: Query repo A in a new conversation
    res_a = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_a.id,
        question="What does execute_alpha do in project-alpha?",
        user_id=gen_user.id,
    )
    conv_id = res_a["conversation_id"]
    assert res_a["repository_id"] == repo_a.id
    assert any("alpha_core.py" in c["file_path"] for c in res_a["citations"])

    # Step 2: Switch conversation to repo B and ask follow-up
    res_b = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_b.id,
        question="How is BetaService structured?",
        user_id=gen_user.id,
        conversation_id=conv_id,
    )
    assert res_b["repository_id"] == repo_b.id
    # Assert no citations from repo A leaked into repo B
    for cit in res_b["citations"]:
        assert cit["repository_name"] == repo_b.name
        assert "alpha_core.py" not in cit["file_path"]


# =========================================================================
# 10. Multi-User Repository Access Isolation
# =========================================================================
def test_multi_user_repository_access_isolation(db_session: Session, gen_user: User):
    """
    Verifies that repository matching and access resolution respects user ownership
    and never leaks repositories owned by another user into candidate matchers.
    """
    other_user = User(
        email="other_tenant@codemind.dev",
        full_name="Other Tenant",
        workspace_name="Other Workspace",
        is_active=True,
    )
    db_session.add(other_user)
    db_session.commit()

    private_repo_gen = Repository(name="gen-private-tool", full_name="acme/gen-private-tool", user_id=gen_user.id)
    private_repo_other = Repository(name="other-secret-tool", full_name="tenant/other-secret-tool", user_id=other_user.id)
    db_session.add_all([private_repo_gen, private_repo_other])
    db_session.commit()

    # Matchers for other_user should include other-secret-tool but NOT gen-private-tool
    matchers_other = AssistantService.build_repository_matchers(db_session, user_id=other_user.id)
    matched_ids_other = [r.id for r, _ in matchers_other]
    assert private_repo_other.id in matched_ids_other
    assert private_repo_gen.id not in matched_ids_other

    # Matchers for gen_user should include gen-private-tool but NOT other-secret-tool
    matchers_gen = AssistantService.build_repository_matchers(db_session, user_id=gen_user.id)
    matched_ids_gen = [r.id for r, _ in matchers_gen]
    assert private_repo_gen.id in matched_ids_gen
    assert private_repo_other.id not in matched_ids_gen


# =========================================================================
# 11. Actively Indexing Repository Communicates In-Progress Status
# =========================================================================
@pytest.mark.anyio
async def test_indexing_in_progress_returns_actionable_limitation(db_session: Session, gen_user: User):
    """
    Verifies that when a repository is actively indexing (status='indexing'),
    the assistant communicates that indexing is in progress without failing or inventing answers.
    """
    repo = Repository(name="in-progress-repo", full_name="acme/in-progress-repo", user_id=gen_user.id, status="indexing")
    db_session.add(repo)
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="What is the architecture of this repo?",
        user_id=gen_user.id,
    )

    assert res["retrieval_strategy"] == "indexing"
    assert "currently being indexed" in res["answer"].lower()
    assert res["facts"]["unknowns"] >= 1
    assert len(res["citations"]) == 0


# =========================================================================
# 12. Empty Retrieval Returns Honest Guidance Without Hallucination
# =========================================================================
@pytest.mark.anyio
async def test_empty_retrieval_returns_unhallucinated_guidance(db_session: Session, gen_user: User):
    """
    Verifies that when a repository is indexed but retrieval yields no matching chunks,
    the assistant returns an honest message stating no relevant code was retrieved
    with unknowns=1 and 0 citations, instead of fabricating content.
    """
    repo = Repository(name="clean-calc-repo", full_name="acme/clean-calc-repo", user_id=gen_user.id, status="ready", files_count=1)
    db_session.add(repo)
    db_session.commit()

    c = CodeChunk(
        repository_id=repo.id, file_path="calc.py", start_line=1, end_line=15,
        chunk_text="def add(a, b):\n    return a + b",
        content_hash="h_calc", language="python", chunk_index=0
    )
    db_session.add(c)
    db_session.commit()

    # Query asking about something completely unrelated that matches 0 chunks
    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="xyzabc_nonexistent_quantum_crypto_protocol_spec",
        user_id=gen_user.id,
    )

    assert res["retrieval_strategy"] == "empty_retrieval"
    assert "no relevant source code" in res["answer"].lower()
    assert len(res["citations"]) == 0
    assert res["facts"]["unknowns"] == 1

