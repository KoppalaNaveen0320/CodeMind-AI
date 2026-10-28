import asyncio
import json
import re
import time
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.services.assistant_service import AssistantService
from backend.app.retrieval.hybrid_engine import RetrievedChunk


def _get_or_create_user(db: Session, email="relevance_tester@acme.dev") -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, full_name="Relevance Tester", workspace_name="Acme", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _seed_ecommerce_repo(db: Session, name="EcommerceApp", user_id=None):
    if user_id is None:
        user = _get_or_create_user(db)
        user_id = user.id
    repo = Repository(name=name, full_name=f"acme/{name}", user_id=user_id, status="ready")
    db.add(repo)
    db.commit()

    f_auth = IndexedFile(repository_id=repo.id, path="src/auth/service.py", lines_count=40)
    f_models = IndexedFile(repository_id=repo.id, path="src/models/user.py", lines_count=50)
    f_routes = IndexedFile(repository_id=repo.id, path="src/api/routes.py", lines_count=60)
    f_config = IndexedFile(repository_id=repo.id, path="src/config/settings.py", lines_count=35)
    f_orders = IndexedFile(repository_id=repo.id, path="src/services/order_service.py", lines_count=55)
    db.add_all([f_auth, f_models, f_routes, f_config, f_orders])
    db.commit()

    c1 = CodeChunk(
        repository_id=repo.id,
        file_id=f_auth.id,
        file_path="src/auth/service.py",
        code_symbol="create_access_token",
        chunk_index=0,
        chunk_text="def create_access_token(data: dict, expires_delta=None):\n    to_encode = data.copy()\n    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)\n",
        content_hash=f"h_auth_{name}",
        language="python",
        start_line=1,
        end_line=15,
    )
    c2 = CodeChunk(
        repository_id=repo.id,
        file_id=f_models.id,
        file_path="src/models/user.py",
        code_symbol="UserModel",
        chunk_index=1,
        chunk_text="class UserModel(Base):\n    __tablename__ = 'users'\n    id = Column(Integer, primary_key=True)\n    email = Column(String, unique=True)\n    is_active = Column(Boolean, default=True)\n",
        content_hash=f"h_user_{name}",
        language="python",
        start_line=1,
        end_line=20,
    )
    c3 = CodeChunk(
        repository_id=repo.id,
        file_id=f_routes.id,
        file_path="src/api/routes.py",
        code_symbol="get_users_route",
        chunk_index=2,
        chunk_text="@router.get('/users')\ndef get_users_route(db: Session = Depends(get_db)):\n    return db.query(UserModel).all()\n",
        content_hash=f"h_routes_{name}",
        language="python",
        start_line=1,
        end_line=20,
    )
    c4 = CodeChunk(
        repository_id=repo.id,
        file_id=f_config.id,
        file_path="src/config/settings.py",
        code_symbol="AppSettings",
        chunk_index=3,
        chunk_text="class AppSettings(BaseSettings):\n    DATABASE_URL: str = 'postgresql://localhost/db'\n    SECRET_KEY: str = 'supersecret'\n    DEBUG: bool = False\n",
        content_hash=f"h_cfg_{name}",
        language="python",
        start_line=1,
        end_line=20,
    )
    c5 = CodeChunk(
        repository_id=repo.id,
        file_id=f_orders.id,
        file_path="src/services/order_service.py",
        code_symbol="calculate_tax",
        chunk_index=4,
        chunk_text="def calculate_tax(amount: float, state: str) -> float:\n    rate = 0.08 if state == 'CA' else 0.05\n    return amount * rate\n",
        content_hash=f"h_tax_{name}",
        language="python",
        start_line=1,
        end_line=20,
    )
    db.add_all([c1, c2, c3, c4, c5])
    db.commit()

    sym1 = CodeSymbol(repository_id=repo.id, file_id=f_auth.id, name="create_access_token", kind="function", start_line=1, end_line=15)
    sym2 = CodeSymbol(repository_id=repo.id, file_id=f_models.id, name="UserModel", kind="class", start_line=1, end_line=20)
    sym3 = CodeSymbol(repository_id=repo.id, file_id=f_routes.id, name="get_users_route", kind="function", start_line=1, end_line=20)
    sym4 = CodeSymbol(repository_id=repo.id, file_id=f_config.id, name="AppSettings", kind="class", start_line=1, end_line=20)
    sym5 = CodeSymbol(repository_id=repo.id, file_id=f_orders.id, name="calculate_tax", kind="function", start_line=1, end_line=20)
    db.add_all([sym1, sym2, sym3, sym4, sym5])
    db.commit()

    return repo


class TestAnswerRelevanceRegression:
    """12 deterministic regression tests verifying conversation isolation and relevance."""

    # 1. Ten sequential questions with different topics in one conversation
    @pytest.mark.anyio
    async def test_01_ten_sequential_questions_different_topics(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "SeqTopicRepo")
        conv = AssistantService.create_conversation(db_session, user_id=repo.user_id, repository_id=repo.id)

        ten_questions = [
            "What is the overall architecture of this repository?",
            "Where is `create_access_token` defined?",
            "How does user authentication work in `src/auth/service.py`?",
            "What are the database models in this project?",
            "What is the difference between a list and a dictionary in Python?",
            "Where are the API routes structured?",
            "How does `calculate_tax` work in order service?",
            "Does this project support email notifications?",
            "Can you explain src/config/settings.py?",
            "What database is configured in `AppSettings`?",
        ]

        with patch("backend.app.services.assistant_service.get_llm_provider") as mock_provider:
            instance = AsyncMock()
            instance.is_configured = True
            instance.model = "mock-qwen-3b"

            async def mock_resp(messages):
                user_msg = messages[-1]["content"]
                m = re.search(r"### CURRENT USER QUESTION \(Address this directly\):\s*(.+?)\n", user_msg)
                q = m.group(1).strip() if m else "general answer"
                return f"Direct Answer for: {q}. Verified according to source."

            instance.generate_chat_response.side_effect = mock_resp
            mock_provider.return_value = instance

            for idx, q in enumerate(ten_questions, start=1):
                res = await AssistantService.answer_question(
                    db=db_session,
                    question=q,
                    conversation_id=conv.id,
                    repository_id=repo.id,
                    user_id=repo.user_id,
                )
                assert res["status"] == "success"
                assert "diagnostics" in res
                diag = res["diagnostics"]
                assert diag["conversation_id"] == conv.id
                assert diag["repository_id"] == repo.id
                assert diag["current_question"] == q
                assert "Direct Answer for: " + q in res["answer"]

                # Ensure previous symbols do not leak into search query for unrelated turns
                if idx == 5:
                    # Python question should be general knowledge
                    assert res["retrieval_strategy"] == "general_knowledge"
                    assert len(res["citations"]) == 0
                if idx == 9:
                    # Explicit settings file should cite settings.py
                    assert any("settings.py" in c["file_path"] for c in res["citations"])

    # 2. A follow-up question that legitimately depends on previous context
    @pytest.mark.anyio
    async def test_02_legitimate_follow_up_question(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "FollowUpRepo")
        conv = AssistantService.create_conversation(db_session, user_id=repo.user_id, repository_id=repo.id)

        # Turn 1
        follow_1 = AssistantService._resolve_follow_up_context(
            db=db_session,
            repository_id=repo.id,
            conversation_id=conv.id,
            question="Where is `create_access_token` defined?",
        )
        assert follow_1["is_follow_up"] is False

        # Store turn 1 response
        asst_msg = AssistantMessage(
            conversation_id=conv.id,
            role="assistant",
            content="`create_access_token` is defined in `src/auth/service.py:1-15`.",
            citations=json.dumps([{"repository_name": repo.name, "file_path": "src/auth/service.py", "symbol_name": "create_access_token"}]),
            retrieval_strategy="hybrid",
            evidence_metadata=json.dumps({"repository_id": repo.id}),
            status="success",
        )
        db_session.add(asst_msg)
        db_session.commit()

        # Turn 2: pronoun / continuation
        follow_2 = AssistantService._resolve_follow_up_context(
            db=db_session,
            repository_id=repo.id,
            conversation_id=conv.id,
            question="What parameters does it take?",
        )
        assert follow_2["is_follow_up"] is True
        assert follow_2["resolved_symbol"] == "create_access_token"
        assert "create_access_token" in follow_2["augmented_query"]

    # 3. An unrelated new question that must not inherit irrelevant prior context
    @pytest.mark.anyio
    async def test_03_unrelated_new_question_not_contaminated(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "UnrelatedRepo")
        conv = AssistantService.create_conversation(db_session, user_id=repo.user_id, repository_id=repo.id)

        # Simulate prior turn discussing create_access_token
        m_user = AssistantMessage(conversation_id=conv.id, role="user", content="Where is `create_access_token`?", status="success")
        m_asst = AssistantMessage(
            conversation_id=conv.id,
            role="assistant",
            content="`create_access_token` is in `src/auth/service.py`.",
            citations=json.dumps([{"repository_name": repo.name, "file_path": "src/auth/service.py"}]),
            evidence_metadata=json.dumps({"repository_id": repo.id}),
            status="success",
        )
        db_session.add_all([m_user, m_asst])
        db_session.commit()

        # New standalone question
        follow = AssistantService._resolve_follow_up_context(
            db=db_session,
            repository_id=repo.id,
            conversation_id=conv.id,
            question="Where are the database models?",
        )
        assert follow["is_follow_up"] is False
        assert "create_access_token" not in follow["augmented_query"]
        assert follow["augmented_query"] == "Where are the database models?"

    # 4. Explicit filename and symbol questions
    @pytest.mark.anyio
    async def test_04_explicit_filename_and_symbol_questions(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "ExplicitFileRepo")

        # Test explicit candidate detection and chunk ranking
        retrieved_chunks = [
            RetrievedChunk(
                chunk_id=1,
                repository_id=repo.id,
                file_path="src/api/routes.py",
                symbol_name="routes",
                start_line=1,
                end_line=20,
                chunk_text="routes",
                score=0.8,
                channels=["hybrid"],
            ),
            RetrievedChunk(
                chunk_id=2,
                repository_id=repo.id,
                file_path="src/config/settings.py",
                symbol_name="AppSettings",
                start_line=1,
                end_line=20,
                chunk_text="class AppSettings",
                score=0.7,
                channels=["hybrid"],
            ),
        ]
        enriched, notes, meta = AssistantService._enrich_multi_layer_retrieval(
            db=db_session,
            repository_id=repo.id,
            question="Can you explain src/config/settings.py?",
            retrieved_chunks=retrieved_chunks,
            intents=["CONFIGURATION"],
        )
        # Explicit file chunks should be prioritized at the front
        assert enriched[0].file_path == "src/config/settings.py"
        assert "VERIFIED EXPLICIT FILE EVIDENCE" in (notes or "")

    # 5. Switching between repositories and conversations
    @pytest.mark.anyio
    async def test_05_switching_between_repositories(self, db_session: Session):
        repo_a = _seed_ecommerce_repo(db_session, "RepoA_Commerce")
        repo_b = _seed_ecommerce_repo(db_session, "RepoB_Analytics")
        conv = AssistantService.create_conversation(db_session, user_id=repo_a.user_id, repository_id=repo_a.id)

        # User message in Repo A
        m1 = AssistantMessage(conversation_id=conv.id, role="user", content="Explain RepoA models", status="success")
        m2 = AssistantMessage(
            conversation_id=conv.id,
            role="assistant",
            content="RepoA has UserModel.",
            citations=json.dumps([{"repository_name": repo_a.name, "file_path": "src/models/user.py"}]),
            evidence_metadata=json.dumps({"repository_id": repo_a.id}),
            status="success",
        )
        db_session.add_all([m1, m2])
        db_session.commit()

        # Switch conversation to Repo B
        follow_b = AssistantService._resolve_follow_up_context(
            db=db_session,
            repository_id=repo_b.id,
            conversation_id=conv.id,
            question="What is this component?",
        )
        # History from Repo A must be isolated
        assert follow_b["is_follow_up"] is False
        assert len(follow_b["history_turns"]) == 0

    # 6. Long conversations that exceed the configured context budget
    @pytest.mark.anyio
    async def test_06_long_conversation_context_budget_and_summary(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "LongConvRepo")
        conv = AssistantService.create_conversation(db_session, user_id=repo.user_id, repository_id=repo.id)

        # Seed 5 user-assistant pairs (10 messages)
        for i in range(5):
            u = AssistantMessage(conversation_id=conv.id, role="user", content=f"Question number {i} regarding feature {i}", status="success")
            a = AssistantMessage(
                conversation_id=conv.id,
                role="assistant",
                content=f"Answer number {i} with verified evidence {i}.",
                citations=json.dumps([{"repository_name": repo.name, "file_path": "src/auth/service.py"}]),
                evidence_metadata=json.dumps({"repository_id": repo.id}),
                status="success",
            )
            db_session.add_all([u, a])
        db_session.commit()

        follow = AssistantService._resolve_follow_up_context(
            db=db_session,
            repository_id=repo.id,
            conversation_id=conv.id,
            question="Tell me more about calculate_tax",
        )
        # History turns should be bounded to last 3 pairs = 6 messages
        assert len(follow["history_turns"]) == 6
        # Older turns should be summarized
        assert follow["conversation_summary"] is not None
        assert "Earlier conversation turns discussed:" in follow["conversation_summary"]

    # 7. Duplicate or incorrectly ordered history messages
    @pytest.mark.anyio
    async def test_07_duplicate_or_unordered_history_messages(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "UnorderedRepo")
        conv = AssistantService.create_conversation(db_session, user_id=repo.user_id, repository_id=repo.id)

        # Add duplicate consecutive user messages and unpaired items
        m1 = AssistantMessage(conversation_id=conv.id, role="user", content="Duplicate question", status="success")
        m2 = AssistantMessage(conversation_id=conv.id, role="user", content="Duplicate question 2", status="success")
        m3 = AssistantMessage(
            conversation_id=conv.id,
            role="assistant",
            content="Valid response to question 2",
            evidence_metadata=json.dumps({"repository_id": repo.id}),
            status="success",
        )
        db_session.add_all([m1, m2, m3])
        db_session.commit()

        follow = AssistantService._resolve_follow_up_context(
            db=db_session,
            repository_id=repo.id,
            conversation_id=conv.id,
            question="What is next?",
        )
        # History turns must alternate cleanly [user, assistant]
        turns = follow["history_turns"]
        assert len(turns) == 2
        assert turns[0]["role"] == "user"
        assert turns[1]["role"] == "assistant"

    # 8. Empty or irrelevant retrieval results
    @pytest.mark.anyio
    async def test_08_empty_or_irrelevant_retrieval(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "EmptyRetrievalRepo")
        conv = AssistantService.create_conversation(db_session, user_id=repo.user_id, repository_id=repo.id)

        with patch("backend.app.retrieval.hybrid_engine.HybridRetrievalEngine.retrieve", new_callable=AsyncMock) as mock_ret:
            mock_ret.return_value = []
            res = await AssistantService.answer_question(
                db=db_session,
                question="Explain quantum_neural_cryptography_engine.py",
                conversation_id=conv.id,
                repository_id=repo.id,
                user_id=repo.user_id,
            )
            assert res["retrieval_strategy"] == "empty_retrieval"
            assert "No relevant source code" in res["answer"]
            assert len(res["citations"]) == 0
            assert res["diagnostics"]["status"] == "success"

    # 9. General programming questions that should not be forced to use repository evidence
    @pytest.mark.anyio
    async def test_09_general_programming_questions_not_forced_to_repo(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "GeneralProgRepo")
        conv = AssistantService.create_conversation(db_session, user_id=repo.user_id, repository_id=repo.id)

        with patch("backend.app.services.assistant_service.get_llm_provider") as mock_provider:
            instance = AsyncMock()
            instance.is_configured = True
            instance.model = "mock-qwen-3b"
            instance.generate_chat_response.return_value = "In Python, a list is an ordered mutable sequence, while a dictionary is a key-value mapping."
            mock_provider.return_value = instance

            res = await AssistantService.answer_question(
                db=db_session,
                question="What is the difference between a list and a dictionary in Python?",
                conversation_id=conv.id,
                repository_id=repo.id,
                user_id=repo.user_id,
            )
            assert res["status"] == "success"
            assert res["retrieval_strategy"] == "general_knowledge"
            assert len(res["citations"]) == 0
            assert "list is an ordered mutable sequence" in res["answer"]

    # 10. Repository questions that require evidence from multiple files
    @pytest.mark.anyio
    async def test_10_multiple_files_evidence(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "MultiFileRepo")
        conv = AssistantService.create_conversation(db_session, user_id=repo.user_id, repository_id=repo.id)

        with patch("backend.app.services.assistant_service.get_llm_provider") as mock_provider:
            instance = AsyncMock()
            instance.is_configured = True
            instance.model = "mock-qwen-3b"
            instance.generate_chat_response.return_value = "The architecture uses routes in `src/api/routes.py`, services in `src/auth/service.py`, and models in `src/models/user.py`."
            mock_provider.return_value = instance

            res = await AssistantService.answer_question(
                db=db_session,
                question="Explain the full architecture and component flow of this repository.",
                conversation_id=conv.id,
                repository_id=repo.id,
                user_id=repo.user_id,
            )
            assert res["status"] == "success"
            cited_files = {c["file_path"] for c in res["citations"]}
            assert len(cited_files) >= 2

    # 11. Failed and cancelled model responses
    @pytest.mark.anyio
    async def test_11_failed_and_cancelled_model_responses(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "FailCancelRepo")
        conv = AssistantService.create_conversation(db_session, user_id=repo.user_id, repository_id=repo.id)

        # Seed a failed assistant message and a cancelled assistant message
        m_fail = AssistantMessage(conversation_id=conv.id, role="assistant", content="AI Assistant Error: Timeout", status="failed")
        m_cancel = AssistantMessage(conversation_id=conv.id, role="assistant", content="Generation cancelled", status="cancelled")
        db_session.add_all([m_fail, m_cancel])
        db_session.commit()

        # Build follow-up context for next question
        follow = AssistantService._resolve_follow_up_context(
            db=db_session,
            repository_id=repo.id,
            conversation_id=conv.id,
            question="Can you help me?",
        )
        # Failed and cancelled messages must not be loaded into history turns
        assert len(follow["history_turns"]) == 0

    # 12. Repeated questions and requests to revise a previous answer
    @pytest.mark.anyio
    async def test_12_repeated_questions_and_revision_requests(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "ReviseRepo")
        conv = AssistantService.create_conversation(db_session, user_id=repo.user_id, repository_id=repo.id)

        # Turn 1
        m1 = AssistantMessage(conversation_id=conv.id, role="user", content="How does calculate_tax work?", status="success")
        m2 = AssistantMessage(
            conversation_id=conv.id,
            role="assistant",
            content="`calculate_tax` multiplies amount by 0.08 for CA and 0.05 otherwise.",
            citations=json.dumps([{"repository_name": repo.name, "file_path": "src/services/order_service.py"}]),
            evidence_metadata=json.dumps({"repository_id": repo.id}),
            status="success",
        )
        db_session.add_all([m1, m2])
        db_session.commit()

        # Turn 2: Request revision of previous answer
        follow = AssistantService._resolve_follow_up_context(
            db=db_session,
            repository_id=repo.id,
            conversation_id=conv.id,
            question="Can you revise your previous answer to include tax exemption?",
        )
        assert follow["is_follow_up"] is True
        assert len(follow["history_turns"]) == 2
        assert follow["history_turns"][0]["role"] == "user"
        assert follow["history_turns"][1]["role"] == "assistant"

    # 13. Email notification grounding vs data model field (Audit Requirement 6)
    @pytest.mark.anyio
    async def test_13_email_notifications_absence_vs_data_field(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "EmailAuditRepo")
        # Simulate LLM claiming email notifications are supported because UserModel.email exists
        raw_llm_answer = (
            "The project supports email notifications as the email field is present in the UserModel from src/models/user.py. "
            "Users have an email address stored in the database."
        )
        user_chunk = RetrievedChunk(
            file_path="src/models/user.py",
            chunk_text="class UserModel(Base):\n    email = Column(String)\n",
            score=0.9,
            chunk_id=1,
            symbol_name="UserModel",
            start_line=1,
            end_line=10,
            repository_id=repo.id,
        )
        sanitized = AssistantService._validate_and_sanitize_answer(
            answer=raw_llm_answer,
            chunks=[user_chunk],
            repo_name=repo.name,
            question="Does this project support email notifications?",
        )
        # Must not claim email notification system is supported solely because of user column
        assert "supports email notifications as the email field is present" not in sanitized
        assert "UNVERIFIED / ABSENT" in sanitized or "does not implement an email notification system" in sanitized

    # 14. Configured database values grounding (Audit Requirement 6)
    @pytest.mark.anyio
    async def test_14_configured_database_values_grounding(self, db_session: Session):
        repo = _seed_ecommerce_repo(db_session, "DbConfigRepo")
        raw_llm_answer = "The project uses postgresql://prod-server.com:5432/db for production."
        settings_chunk = RetrievedChunk(
            file_path="src/config/settings.py",
            chunk_text="class AppSettings(BaseSettings):\n    DATABASE_URL: str = 'sqlite:///./test.db'\n",
            score=0.95,
            chunk_id=2,
            symbol_name="AppSettings",
            start_line=1,
            end_line=10,
            repository_id=repo.id,
        )
        sanitized = AssistantService._validate_and_sanitize_answer(
            answer=raw_llm_answer,
            chunks=[settings_chunk],
            repo_name=repo.name,
            question="What database URL is configured in settings.py?",
        )
        assert "sqlite:///./test.db" in sanitized

