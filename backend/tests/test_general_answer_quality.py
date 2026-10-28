import pytest
import json
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.user import User
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.services.assistant_service import AssistantService, RetrievedChunk


@pytest.fixture
def test_user(db_session: Session) -> User:
    user = db_session.query(User).filter(User.email == "test_general_qa@codemind.dev").first()
    if not user:
        user = User(
            email="test_general_qa@codemind.dev",
            full_name="General QA Test User",
            workspace_name="QA Workspace",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
    return user


# =========================================================================
# Category 1: Straightforward Code Explanation & Symbol Behavior
# =========================================================================
@pytest.mark.anyio
async def test_category_1_code_explanation_direct_and_grounded(db_session: Session, test_user: User):
    repo = Repository(name="calc-service", full_name="org/calc-service", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="calc/tax.py", lines_count=40)
    db_session.add(f)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_id=f.id,
        file_path="calc/tax.py",
        code_symbol="calculate_sales_tax",
        chunk_index=0,
        chunk_text=(
            "def calculate_sales_tax(subtotal: float, state_code: str) -> float:\n"
            "    rates = {'CA': 0.0725, 'NY': 0.04, 'TX': 0.0625}\n"
            "    rate = rates.get(state_code.upper(), 0.05)\n"
            "    return round(subtotal * rate, 2)\n"
        ),
        content_hash="h_calc_tax",
        language="python",
        start_line=1,
        end_line=10,
    )
    db_session.add(chunk)
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="How does `calculate_sales_tax` work and what are its inputs and return value?",
        user_id=test_user.id,
    )

    answer = res["answer"]
    # 1. Addresses question directly in the opening
    assert "calculate_sales_tax" in answer
    # 2. Key claims grounded in evidence
    assert any(term in answer for term in ["subtotal", "state_code", "rates", "tax", "round"])
    # 3. Citations resolve to real indexed sources
    assert len(res["citations"]) >= 1
    assert res["citations"][0]["file_path"] == "calc/tax.py"
    # 4. Evidence counters consistent
    assert res["facts"]["confirmed"] >= 1
    # 5. When evidence is complete for this function, unknowns is 0
    assert res["facts"]["unknowns"] == 0


# =========================================================================
# Category 2: Symbol and Call Hierarchy Lookup
# =========================================================================
@pytest.mark.anyio
async def test_category_2_call_hierarchy_lookup_no_contradictions(db_session: Session, test_user: User):
    repo = Repository(name="order-pipeline", full_name="org/order-pipeline", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="orders/processor.py", lines_count=50)
    db_session.add(f)
    db_session.commit()

    chunk1 = CodeChunk(
        repository_id=repo.id,
        file_id=f.id,
        file_path="orders/processor.py",
        code_symbol="submit_order",
        chunk_index=0,
        chunk_text=(
            "def submit_order(order_id: int):\n"
            "    validate_inventory(order_id)\n"
            "    return {'status': 'processed'}\n"
        ),
        content_hash="h_submit",
        language="python",
        start_line=1,
        end_line=10,
    )
    chunk2 = CodeChunk(
        repository_id=repo.id,
        file_id=f.id,
        file_path="orders/processor.py",
        code_symbol="validate_inventory",
        chunk_index=1,
        chunk_text=(
            "def validate_inventory(order_id: int):\n"
            "    # check warehouse stocks\n"
            "    return True\n"
        ),
        content_hash="h_validate",
        language="python",
        start_line=12,
        end_line=20,
    )
    db_session.add_all([chunk1, chunk2])
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="What functions does `submit_order` call in `orders/processor.py`?",
        user_id=test_user.id,
    )

    answer = res["answer"]
    # Addresses the question and identifies the callee
    assert "validate_inventory" in answer or "submit_order" in answer
    # No self-contradictions
    assert "not called by any other function" not in answer.lower()
    # Citations resolve to processor.py
    assert any("orders/processor.py" in c["file_path"] for c in res["citations"])


# =========================================================================
# Category 3: Dependency and Architecture Questions
# =========================================================================
@pytest.mark.anyio
async def test_category_3_architecture_layer_grounding(db_session: Session, test_user: User):
    repo = Repository(name="store-api", full_name="org/store-api", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(repository_id=repo.id, path="main.py", lines_count=20)
    f2 = IndexedFile(repository_id=repo.id, path="routes/items.py", lines_count=30)
    db_session.add_all([f1, f2])
    db_session.commit()

    c1 = CodeChunk(
        repository_id=repo.id, file_id=f1.id, file_path="main.py", chunk_index=0,
        chunk_text="from fastapi import FastAPI\nfrom routes.items import router\napp = FastAPI()\napp.include_router(router)\n",
        content_hash="h_main", language="python", start_line=1, end_line=15
    )
    c2 = CodeChunk(
        repository_id=repo.id, file_id=f2.id, file_path="routes/items.py", chunk_index=0,
        chunk_text="from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/items')\ndef list_items():\n    return []\n",
        content_hash="h_routes", language="python", start_line=1, end_line=20
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the high-level architecture, entry point, and route registration in this codebase.",
        user_id=test_user.id,
    )

    answer = res["answer"]
    assert "main.py" in answer
    assert "routes/items.py" in answer or "/items" in answer
    # Distinct confirmed layers captured
    assert res["facts"]["confirmed"] >= 2


# =========================================================================
# Category 4: Debugging and Root-Cause Analysis
# =========================================================================
@pytest.mark.anyio
async def test_category_4_debugging_and_root_cause(db_session: Session, test_user: User):
    repo = Repository(name="payment-svc", full_name="org/payment-svc", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="services/payment.py", lines_count=35)
    db_session.add(f)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="services/payment.py", chunk_index=0,
        code_symbol="process_refund",
        chunk_text=(
            "def process_refund(tx_id: str, amount: float):\n"
            "    tx = get_transaction(tx_id)\n"
            "    if tx is None:\n"
            "        raise ValueError(f'Transaction {tx_id} not found')\n"
            "    if amount > tx.amount:\n"
            "        raise ValueError('Refund amount exceeds original charge')\n"
            "    return execute_gateway_refund(tx.gateway_id, amount)\n"
        ),
        content_hash="h_refund", language="python", start_line=1, end_line=20
    )
    db_session.add(chunk)
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Why would `process_refund` raise a ValueError and how does it handle missing transactions?",
        user_id=test_user.id,
    )

    answer = res["answer"]
    assert "ValueError" in answer or "valueerror" in answer.lower()
    assert "not found" in answer.lower() or "exceeds" in answer.lower() or "tx is none" in answer.lower()
    assert res["citations"][0]["file_path"] == "services/payment.py"


# =========================================================================
# Category 5: Repository-Wide Technology and Configuration Questions
# =========================================================================
@pytest.mark.anyio
async def test_category_5_tech_stack_and_configuration(db_session: Session, test_user: User):
    repo = Repository(name="dockerized-app", full_name="org/dockerized-app", user_id=test_user.id)
    repo.tech_stack = {
        "summary": {"full_summary": "Python, FastAPI, PostgreSQL, Docker"},
        "backend": [{"name": "FastAPI"}],
        "database": [{"name": "PostgreSQL"}],
        "infrastructure": [{"name": "Docker"}]
    }
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(repository_id=repo.id, path="requirements.txt", lines_count=10)
    f2 = IndexedFile(repository_id=repo.id, path="Dockerfile", lines_count=20)
    db_session.add_all([f1, f2])
    db_session.commit()

    c1 = CodeChunk(
        repository_id=repo.id, file_id=f1.id, file_path="requirements.txt", chunk_index=0,
        chunk_text="fastapi==0.110.0\nuvicorn==0.28.0\npsycopg2-binary==2.9.9\n",
        content_hash="h_reqs", language="text", start_line=1, end_line=5
    )
    c2 = CodeChunk(
        repository_id=repo.id, file_id=f2.id, file_path="Dockerfile", chunk_index=0,
        chunk_text="FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\n",
        content_hash="h_dock", language="dockerfile", start_line=1, end_line=10
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="What is the technology stack and deployment configuration for this project?",
        user_id=test_user.id,
    )

    answer = res["answer"]
    assert "FastAPI" in answer or "fastapi" in answer.lower()
    assert "requirements.txt" in answer or "Dockerfile" in answer or "docker" in answer.lower()
    assert res["facts"]["confirmed"] >= 1


# =========================================================================
# Category 6: Security and Reliability Analysis
# =========================================================================
@pytest.mark.anyio
async def test_category_6_security_and_credential_sanitization(db_session: Session, test_user: User):
    repo = Repository(name="vault-service", full_name="org/vault-service", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="security/crypto.py", lines_count=30)
    db_session.add(f)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="security/crypto.py", chunk_index=0,
        code_symbol="hash_password",
        chunk_text=(
            "import bcrypt\n"
            "def hash_password(plain_password: str) -> str:\n"
            "    salt = bcrypt.gensalt(rounds=12)\n"
            "    return bcrypt.hashpw(plain_password.encode('utf-8'), salt).decode('utf-8')\n"
        ),
        content_hash="h_crypto", language="python", start_line=1, end_line=15
    )
    db_session.add(chunk)
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="How does `hash_password` hash user credentials securely and what algorithm does it use?",
        user_id=test_user.id,
    )

    answer = res["answer"]
    assert "bcrypt" in answer.lower()
    assert "salt" in answer.lower() or "rounds" in answer.lower()
    assert res["citations"][0]["file_path"] == "security/crypto.py"


# =========================================================================
# Category 7: Follow-Up Questions Using Prior Context
# =========================================================================
@pytest.mark.anyio
async def test_category_7_follow_up_pronoun_context_retention(db_session: Session, test_user: User):
    repo = Repository(name="auth-flow-repo", full_name="org/auth-flow-repo", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="auth/tokens.py", lines_count=40)
    db_session.add(f)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="auth/tokens.py", chunk_index=0,
        code_symbol="generate_session_token",
        chunk_text=(
            "import secrets\n"
            "def generate_session_token(user_id: int) -> str:\n"
            "    return f'sess_{user_id}_{secrets.token_hex(16)}'\n"
        ),
        content_hash="h_sess", language="python", start_line=1, end_line=10
    )
    db_session.add(chunk)
    db_session.commit()

    conv = AssistantConversation(user_id=test_user.id, repository_id=repo.id, title="Token Flow")
    db_session.add(conv)
    db_session.commit()

    # Turn 1
    res1 = await AssistantService.answer_question(
        db=db_session, repository_id=repo.id, conversation_id=conv.id,
        question="Explain `generate_session_token` in `auth/tokens.py`.", user_id=test_user.id,
    )
    assert "generate_session_token" in res1["answer"]

    # Turn 2: Follow-up using pronoun
    res2 = await AssistantService.answer_question(
        db=db_session, repository_id=repo.id, conversation_id=conv.id,
        question="What does it return and how is the token constructed?", user_id=test_user.id,
    )
    answer2 = res2["answer"]
    assert "token" in answer2.lower()
    assert "sess_" in answer2 or "secrets" in answer2.lower() or "user_id" in answer2.lower()


# =========================================================================
# Category 8: Questions Requiring Evidence the Index Does Not Contain (Feature Absence)
# =========================================================================
@pytest.mark.anyio
async def test_category_8_feature_absence_explicitly_unverified(db_session: Session, test_user: User):
    repo = Repository(name="basic-cli", full_name="org/basic-cli", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="cli.py", lines_count=15)
    db_session.add(f)
    db_session.commit()
    db_session.add(CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="cli.py", chunk_index=0,
        chunk_text="import sys\nprint('Running basic CLI')\n", content_hash="h_cli", language="python", start_line=1, end_line=5
    ))
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="How does this project implement GraphQL subscriptions and WebSockets?",
        user_id=test_user.id,
    )

    answer = res["answer"].lower()
    # Explicitly reports absence or unverified status instead of hallucinating GraphQL
    assert (
        "not found" in answer
        or "unverified" in answer
        or "no evidence" in answer
        or "does not contain" in answer
        or "absent" in answer
        or "cannot be determined" in answer
        or "could not be verified" in answer
        or "does not implement" in answer
        or "do not exist" in answer
        or "not implemented" in answer
        or "no configuration" in answer
    )
    assert res["facts"]["unknowns"] >= 1


# =========================================================================
# Category 9: Incomplete or Conflicting Retrieval Evidence Handled Truthfully
# =========================================================================
@pytest.mark.anyio
async def test_category_9_incomplete_evidence_separated_from_verified_facts(db_session: Session, test_user: User):
    repo = Repository(name="partial-gateway", full_name="org/partial-gateway", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(repository_id=repo.id, path="routes/login.py", lines_count=20)
    db_session.add(f1)
    db_session.commit()
    db_session.add(CodeChunk(
        repository_id=repo.id, file_id=f1.id, file_path="routes/login.py", chunk_index=0,
        code_symbol="login",
        chunk_text="def login():\n    token = issue_token()\n    return {'token': token}\n",
        content_hash="h_login", language="python", start_line=1, end_line=10
    ))
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the complete authentication, JWT verification, and user session database models.",
        user_id=test_user.id,
    )

    answer = res["answer"]
    # Token issue is verified, but database models and JWT verification are unverified/absent
    assert "login" in answer.lower() or "token" in answer.lower()
    assert (
        "unverified" in answer.lower()
        or "not verified" in answer.lower()
        or "not found" in answer.lower()
        or "absent" in answer.lower()
        or "does not contain" in answer.lower()
    )
    # Both confirmed facts and unknowns are recorded consistently
    assert res["facts"]["confirmed"] >= 1
    assert res["facts"]["unknowns"] >= 1


# =========================================================================
# Category 10: Sufficient Evidence Where Uncertainty Is NOT Exaggerated
# =========================================================================
@pytest.mark.anyio
async def test_category_10_sufficient_evidence_no_exaggerated_uncertainty(db_session: Session, test_user: User):
    repo = Repository(name="math-utils", full_name="org/math-utils", user_id=test_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="utils/math_ops.py", lines_count=30)
    db_session.add(f)
    db_session.commit()
    db_session.add(CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="utils/math_ops.py", chunk_index=0,
        code_symbol="add_numbers",
        chunk_text="def add_numbers(a: int, b: int) -> int:\n    return a + b\n",
        content_hash="h_add", language="python", start_line=1, end_line=5
    ))
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="What does `add_numbers` in `utils/math_ops.py` do?",
        user_id=test_user.id,
    )

    answer = res["answer"]
    assert "add_numbers" in answer
    assert "a + b" in answer or "sum" in answer.lower() or "adds" in answer.lower()
    # When evidence is completely sufficient, unknowns is 0
    assert res["facts"]["unknowns"] == 0
    assert res["facts"]["confirmed"] >= 1
