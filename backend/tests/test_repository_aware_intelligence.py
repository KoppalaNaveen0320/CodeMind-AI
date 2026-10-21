import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine
from backend.app.services.assistant_service import AssistantService


@pytest.fixture
def test_user(db_session: Session) -> User:
    user = db_session.query(User).filter(User.email == "test_intel@codemind.dev").first()
    if not user:
        user = User(
            email="test_intel@codemind.dev",
            full_name="Intelligence Test User",
            workspace_name="Test Workspace",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    return user


# 1. Architecture questions for repositories with different names and structures
@pytest.mark.anyio
async def test_1_architecture_questions_different_repo_structures(db_session: Session, test_user: User):
    repo_fe = Repository(name="CodeMind_AI_UI_UX_Design", full_name="local/CodeMind_AI_UI_UX_Design", user_id=test_user.id)
    repo_be = Repository(name="decision_service", full_name="acme/decision_service", user_id=test_user.id)
    db_session.add_all([repo_fe, repo_be])
    db_session.commit()

    f_fe1 = IndexedFile(repository_id=repo_fe.id, path="package.json", lines_count=40)
    f_fe2 = IndexedFile(repository_id=repo_fe.id, path="src/App.tsx", lines_count=80)
    db_session.add_all([f_fe1, f_fe2])
    db_session.commit()

    c_fe1 = CodeChunk(
        repository_id=repo_fe.id, file_id=f_fe1.id, file_path="package.json", chunk_index=0,
        chunk_text='{"dependencies": {"react": "^18.2.0", "lucide-react": "^0.300.0"}}',
        content_hash="h_fe1", language="json", start_line=1, end_line=10
    )
    c_fe2 = CodeChunk(
        repository_id=repo_fe.id, file_id=f_fe2.id, file_path="src/App.tsx", chunk_index=0,
        chunk_text='export function App() { return <div className="dashboard">CodeMind UI</div>; }',
        content_hash="h_fe2", language="typescript", start_line=1, end_line=20
    )

    f_be1 = IndexedFile(repository_id=repo_be.id, path="main.py", lines_count=30)
    f_be2 = IndexedFile(repository_id=repo_be.id, path="routers/decision.py", lines_count=50)
    db_session.add_all([f_be1, f_be2])
    db_session.commit()

    c_be1 = CodeChunk(
        repository_id=repo_be.id, file_id=f_be1.id, file_path="main.py", chunk_index=0,
        chunk_text='from fastapi import FastAPI\napp = FastAPI()\napp.include_router(decision.router)',
        content_hash="h_be1", language="python", start_line=1, end_line=15
    )
    c_be2 = CodeChunk(
        repository_id=repo_be.id, file_id=f_be2.id, file_path="routers/decision.py", chunk_index=0,
        chunk_text='@router.get("/decisions")\ndef list_decisions(): return []',
        content_hash="h_be2", language="python", start_line=1, end_line=20
    )
    db_session.add_all([c_fe1, c_fe2, c_be1, c_be2])
    db_session.commit()

    # Query FE repo
    res_fe = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_fe.id,
        question="Explain the architecture about the codemind UI UX design.",
        user_id=test_user.id
    )
    fe_cites = [c["file_path"] for c in res_fe["citations"]]
    assert any("App.tsx" in p or "package.json" in p for p in fe_cites)
    assert not any("decision" in p for p in fe_cites)

    # Query BE repo
    res_be = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_be.id,
        question="Explain the architecture of the decision service.",
        user_id=test_user.id
    )
    be_cites = [c["file_path"] for c in res_be["citations"]]
    assert any("main.py" in p or "decision.py" in p for p in be_cites)
    assert not any("App.tsx" in p for p in be_cites)


# 2. Natural-language names that differ from stored repository name
def test_2_natural_language_names_differ_from_stored_name(db_session: Session, test_user: User):
    repo = Repository(name="TokenPool", full_name="KoppalaNaveen0320/TokenPool", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    matched, norm_q, clar = AssistantService.resolve_repository_from_query(
        db=db_session,
        question="Explain the architecture of the token pool and how it manages assets.",
        user_id=test_user.id
    )
    assert matched is not None
    assert matched.id == repo.id
    assert clar is None
    assert "token pool" not in norm_q.lower()
    assert "architecture" in norm_q.lower()


# 3. Questions that omit the repository name but use the selected repository
def test_3_questions_omitting_repository_name_use_active_repo(db_session: Session, test_user: User):
    repo = Repository(name="flask", full_name="pallets/flask", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    matched, norm_q, clar = AssistantService.resolve_repository_from_query(
        db=db_session,
        question="How does this application handle API requests and database operations?",
        active_repo_id=repo.id,
        user_id=test_user.id
    )
    assert matched is not None
    assert matched.id == repo.id
    assert clar is None
    assert "handle api requests" in norm_q.lower()


# 4. Follow-up questions that retain the conversation's repository context
def test_4_follow_up_questions_retain_conversation_repo_context(client: TestClient, db_session: Session, test_user: User):
    repo = Repository(name="expertdecision", full_name="KoppalaNaveen/expertdecision", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="app/main.py", lines_count=20)
    db_session.add(f)
    db_session.commit()
    c = CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="app/main.py", chunk_index=0,
        chunk_text="app = FastAPI()", content_hash="hc_ed", language="python", start_line=1, end_line=10
    )
    db_session.add(c)
    db_session.commit()

    conv = AssistantConversation(
        user_id=test_user.id,
        repository_id=repo.id,
        branch="main",
        title="Architecture Discussion",
        title_is_manual=True,
    )
    db_session.add(conv)
    db_session.commit()

    res = client.post(
        f"/api/v1/assistant/conversations/{conv.id}/messages",
        json={"content": "What is the project structure and main components?"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["repository_id"] == repo.id
    assert data["repository_name"] == repo.name


# 5. Explicit switching between two connected repositories
def test_5_explicit_switching_between_two_connected_repositories(client: TestClient, db_session: Session, test_user: User):
    repo_a = Repository(name="service-alpha", full_name="acme/service-alpha", user_id=test_user.id)
    repo_b = Repository(name="service-beta", full_name="acme/service-beta", user_id=test_user.id)
    db_session.add_all([repo_a, repo_b])
    db_session.commit()

    for r in [repo_a, repo_b]:
        f = IndexedFile(repository_id=r.id, path="main.py", lines_count=10)
        db_session.add(f)
        db_session.commit()
        db_session.add(CodeChunk(
            repository_id=r.id, file_id=f.id, file_path="main.py", chunk_index=0,
            chunk_text=f"print('{r.name}')", content_hash=f"h_{r.name}", language="python", start_line=1, end_line=5
        ))
    db_session.commit()

    conv = AssistantConversation(
        user_id=test_user.id,
        repository_id=repo_a.id,
        branch="main",
        title="Alpha Conversation",
        title_is_manual=True,
    )
    db_session.add(conv)
    db_session.commit()

    res = client.post(
        f"/api/v1/assistant/conversations/{conv.id}/messages",
        json={"content": "Now explain the architecture of service-beta."}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["repository_id"] == repo_b.id
    assert data["repository_name"] == repo_b.name

    db_session.refresh(conv)
    assert conv.repository_id == repo_b.id


# 6. Ambiguous repository names requiring clarification
def test_6_ambiguous_repository_names_require_clarification(db_session: Session, test_user: User):
    repo_ui = Repository(name="acme-portal-ui", full_name="acme/acme-portal-ui", user_id=test_user.id)
    repo_api = Repository(name="acme-portal-api", full_name="acme/acme-portal-api", user_id=test_user.id)
    db_session.add_all([repo_ui, repo_api])
    db_session.commit()

    matched, norm_q, clar = AssistantService.resolve_repository_from_query(
        db=db_session,
        question="Explain the architecture of acme portal.",
        user_id=test_user.id
    )
    assert clar is not None
    assert "acme-portal-ui" in clar
    assert "acme-portal-api" in clar


# 7. Architecture retrieval across routes, services, models, and schemas
@pytest.mark.anyio
async def test_7_architecture_multi_layer_retrieval(db_session: Session, test_user: User):
    repo = Repository(name="layered-app", full_name="acme/layered-app", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    layers = [
        ("main.py", "app.include_router(item_router)"),
        ("api/items.py", "@router.get('/items')\ndef list_items(): return item_service.get_all()"),
        ("services/item_service.py", "class ItemService:\n    def get_all(self): return repo.all()"),
        ("repositories/item_repo.py", "class ItemRepository:\n    def all(self): return db.query(Item).all()"),
        ("models/item.py", "class Item(Base):\n    id = Column(Integer, primary_key=True)"),
        ("schemas/item.py", "class ItemResponse(BaseModel):\n    id: int"),
    ]

    for path, code in layers:
        f = IndexedFile(repository_id=repo.id, path=path, lines_count=20)
        db_session.add(f)
        db_session.commit()
        db_session.add(CodeChunk(
            repository_id=repo.id, file_id=f.id, file_path=path, chunk_index=0,
            chunk_text=code, content_hash=f"h_{path}", language="python", start_line=1, end_line=15
        ))
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the architecture and data flow for items.",
        user_id=test_user.id
    )

    cited_files = {c["file_path"] for c in res["citations"]}
    assert any("main.py" in p for p in cited_files)
    assert any("api/items.py" in p for p in cited_files)
    assert any("services/item_service.py" in p for p in cited_files)
    assert any("repositories/item_repo.py" in p for p in cited_files)
    assert any("models/item.py" in p for p in cited_files)


# 8. Authentication questions where token creation exists but validation does not
@pytest.mark.anyio
async def test_8_auth_token_creation_vs_validation(db_session: Session, test_user: User):
    repo = Repository(name="auth-partial-repo", full_name="acme/auth-partial-repo", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="auth/tokens.py", lines_count=30)
    db_session.add(f)
    db_session.commit()

    c = CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="auth/tokens.py", chunk_index=0,
        chunk_text="def create_jwt_token(payload):\n    return jwt.encode(payload, 'secret', algorithm='HS256')",
        content_hash="h_tok", language="python", start_line=1, end_line=15
    )
    db_session.add(c)
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the authentication and token validation in this project.",
        user_id=test_user.id
    )

    answer = res["answer"]
    assert "create_jwt_token" in answer or "jwt.encode" in answer
    assert "jwt.decode" in answer
    assert "UNVERIFIED" in answer or "unverified" in answer.lower() or "ABSENT" in answer


# 9. First retrieval result irrelevant but recovered by layer enrichment
@pytest.mark.anyio
async def test_9_first_retrieval_result_irrelevant_recovered_by_layer_enrichment(db_session: Session, test_user: User):
    repo = Repository(name="recovery-repo", full_name="acme/recovery-repo", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f_gen = IndexedFile(repository_id=repo.id, path="docs/intro.txt", lines_count=10)
    f_real = IndexedFile(repository_id=repo.id, path="backend/routes/api.py", lines_count=30)
    db_session.add_all([f_gen, f_real])
    db_session.commit()

    c_gen = CodeChunk(
        repository_id=repo.id, file_id=f_gen.id, file_path="docs/intro.txt", chunk_index=0,
        chunk_text="This project has an architecture. It is built well.",
        content_hash="h_gen", language="text", start_line=1, end_line=5
    )
    c_real = CodeChunk(
        repository_id=repo.id, file_id=f_real.id, file_path="backend/routes/api.py", chunk_index=0,
        chunk_text="@router.get('/health')\ndef health(): return {'status': 'ok'}",
        content_hash="h_real", language="python", start_line=1, end_line=10
    )
    db_session.add_all([c_gen, c_real])
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the architecture and routes of the project.",
        user_id=test_user.id
    )

    cites = [c["file_path"] for c in res["citations"]]
    assert any("routes/api.py" in p for p in cites)


# 10. Unknown features that must remain explicitly unverified
@pytest.mark.anyio
async def test_10_unknown_features_remain_explicitly_unverified(db_session: Session, test_user: User):
    repo = Repository(name="simple-rest", full_name="acme/simple-rest", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="server.py", lines_count=20)
    db_session.add(f)
    db_session.commit()
    db_session.add(CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="server.py", chunk_index=0,
        chunk_text="print('REST server')", content_hash="h_srv", language="python", start_line=1, end_line=5
    ))
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain how Redis caching and WebSocket streaming are configured in this repository.",
        user_id=test_user.id
    )

    answer = res["answer"].lower()
    assert (
        "not found" in answer
        or "unverified" in answer
        or "no evidence" in answer
        or "unknown" in answer
        or "does not contain" in answer
        or "cannot be determined" in answer
        or "cannot determine" in answer
        or "no information" in answer
        or "does not provide" in answer
        or "no configuration" in answer
        or "no conclusions" in answer
    )
    assert res["facts"]["unknowns"] >= 1


# 11. Repository isolation across all retrieval and graph operations
@pytest.mark.anyio
async def test_11_repository_isolation_across_retrieval_and_graph(db_session: Session, test_user: User):
    repo_1 = Repository(name="tenant-one", full_name="org/tenant-one", user_id=test_user.id)
    repo_2 = Repository(name="tenant-two", full_name="org/tenant-two", user_id=test_user.id)
    db_session.add_all([repo_1, repo_2])
    db_session.commit()

    f1 = IndexedFile(repository_id=repo_1.id, path="secret.py", lines_count=10)
    f2 = IndexedFile(repository_id=repo_2.id, path="secret.py", lines_count=10)
    db_session.add_all([f1, f2])
    db_session.commit()

    c1 = CodeChunk(
        repository_id=repo_1.id, file_id=f1.id, file_path="secret.py", chunk_index=0,
        chunk_text="TENANT_1_SECRET_VALUE = '111'", content_hash="h_t1", language="python", start_line=1, end_line=5
    )
    c2 = CodeChunk(
        repository_id=repo_2.id, file_id=f2.id, file_path="secret.py", chunk_index=0,
        chunk_text="TENANT_2_SECRET_VALUE = '222'", content_hash="h_t2", language="python", start_line=1, end_line=5
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    retrieved = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo_1.id,
        query="TENANT_2_SECRET_VALUE",
        top_k=5
    )
    for chunk in retrieved:
        assert chunk.repository_id == repo_1.id
        assert "TENANT_2_SECRET_VALUE" not in chunk.chunk_text


# 12. Evidence counts and citations consistent with final answer
@pytest.mark.anyio
async def test_12_evidence_counts_and_citations_consistent(db_session: Session, test_user: User):
    repo = Repository(name="cite-count-repo", full_name="acme/cite-count-repo", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="app.py", lines_count=20)
    db_session.add(f)
    db_session.commit()
    db_session.add(CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="app.py", chunk_index=0,
        chunk_text="def start(): pass", content_hash="h_app", language="python", start_line=1, end_line=5
    ))
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain how app.py starts.",
        user_id=test_user.id
    )

    citations = res["citations"]
    facts = res["facts"]
    assert facts["confirmed"] == len(citations)
    for c in citations:
        assert "file_path" in c
        assert "start_line" in c
        assert "end_line" in c


# 13. Informational questions that must not trigger speculative change-impact analysis
@pytest.mark.anyio
async def test_13_informational_questions_do_not_trigger_speculative_impact(db_session: Session, test_user: User):
    repo = Repository(name="info-only-repo", full_name="acme/info-only-repo", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="routes.py", lines_count=20)
    db_session.add(f)
    db_session.commit()
    db_session.add(CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="routes.py", chunk_index=0,
        chunk_text="def get_info(): return 'info'", content_hash="h_inf", language="python", start_line=1, end_line=5
    ))
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the architecture and project structure.",
        user_id=test_user.id
    )

    risk_callout = res.get("risk_callout", {})
    assert risk_callout.get("level") == "LOW"
    assert "No change impact analysis performed" in risk_callout.get("summary", "")


# 14. Newly added repositories working without hardcoded aliases or code changes
def test_14_newly_added_repositories_work_without_hardcoding(db_session: Session, test_user: User):
    arbitrary_name = "hyperion-distributed-engine-99"
    repo = Repository(
        name=arbitrary_name,
        full_name=f"nebula/{arbitrary_name}",
        user_id=test_user.id
    )
    db_session.add(repo)
    db_session.commit()

    matched, norm_q, clar = AssistantService.resolve_repository_from_query(
        db=db_session,
        question=f"Explain how {arbitrary_name} handles distributed state.",
        user_id=test_user.id
    )
    assert matched is not None
    assert matched.id == repo.id
    assert matched.name == arbitrary_name
    assert clar is None
    assert arbitrary_name not in norm_q
