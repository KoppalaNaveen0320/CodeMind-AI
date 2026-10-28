"""
verify_live_sequential.py
Live Verification of Current-Question Precedence, Multi-Turn Isolation,
and Edge-Case Robustness across Sequential Application Queries.
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import asyncio
import re
from typing import Dict, Any, List
import pytest
from sqlalchemy.orm import Session

from backend.app.db.session import SessionLocal
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.assistant import AssistantConversation
from backend.app.services.assistant_service import AssistantService


def setup_test_data(db: Session) -> Repository:
    """Sets up a test repository with actual CodeMind AI files and chunks."""
    import hashlib
    # Clean up any existing test repo
    existing = db.query(Repository).filter(Repository.name == "CodeMind-LiveVerify").first()
    if existing:
        db.query(CodeChunk).filter(CodeChunk.repository_id == existing.id).delete()
        db.query(IndexedFile).filter(IndexedFile.repository_id == existing.id).delete()
        db.query(AssistantConversation).filter(AssistantConversation.repository_id == existing.id).delete()
        db.delete(existing)
        db.commit()

    repo = Repository(
        name="CodeMind-LiveVerify",
        full_name="org/CodeMind-LiveVerify",
        description="Live audit test repo",
        default_branch="main",
        status="ready"
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    f_engine = IndexedFile(
        repository_id=repo.id,
        path="backend/app/retrieval/hybrid_engine.py",
        language="python",
        lines_count=721,
    )
    db.add(f_engine)

    # Add chunk for vector similarity calculation in pgvector & in-memory fallback
    vec_sim_text = (
        "if is_postgres:\n"
        "    distance = CodeChunk.embedding.cosine_distance(query_vector)\n"
        "    return [(chunk, max(0.0, 1.0 - float(dist))) for chunk, dist in chunks_with_dist]\n"
        "else:\n"
        "    sim = cls._cosine_similarity(query_vector, chunk.embedding)\n"
    )
    c_vec = CodeChunk(
        content_hash=hashlib.sha256(vec_sim_text.encode()).hexdigest(),
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine._retrieve_vector_matches",
        start_line=578,
        end_line=610,
        chunk_text=vec_sim_text,
        language="python"
    )

    c_cosine = CodeChunk(
        content_hash=hashlib.sha256("def _cosine_similarity".encode()).hexdigest(),
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine._cosine_similarity",
        start_line=698,
        end_line=706,
        chunk_text="def _cosine_similarity(vec_a, vec_b):\n    dot = sum(a * b for a, b in zip(vec_a, vec_b))\n    return dot / (norm_a * norm_b)\n",
        language="python"
    )

    db.add_all([c_vec, c_cosine])
    db.commit()
    return repo


@pytest.mark.anyio
async def test_live_sequential_audit():
    db = SessionLocal()
    try:
        repo = setup_test_data(db)
        conv = AssistantConversation(
            repository_id=repo.id,
            branch="main",
            title="Live Verification Audit"
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

        print(f"\n=== STARTING LIVE SEQUENTIAL AUDIT (Conv ID: {conv.id}) ===")

        # =====================================================================
        # Turn 1: Pythagorean Theorem
        # =====================================================================
        q1 = "Explain the Pythagorean theorem."
        print(f"\n[Turn 1] Question: {q1}")
        res1 = await AssistantService.answer_question(
            db=db,
            repository_id=repo.id,
            question=q1,
            conversation_id=conv.id
        )
        ans1 = res1["answer"]
        print(f"[Turn 1] Strategy: {res1.get('retrieval_strategy')} | Citations: {len(res1.get('citations', []))}")
        print(f"[Turn 1] Answer snippet:\n{ans1[:200]}...")

        assert "pythagorean" in ans1.lower(), "Turn 1 must address Pythagorean theorem"
        assert ("\\[" in ans1 or "\\(" in ans1) and ("a^2 + b^2" in ans1 or "c^2" in ans1), "Turn 1 must include mathematical formula"
        assert res1.get("citations") == [], "Educational question must have no repo citations"
        print("PASS: Turn 1 verified")

        # =====================================================================
        # Turn 2: Einstein + Fraction + Sum of squares + Binomial expansion
        # =====================================================================
        q2 = "Now explain Einstein's mass-energy equation, a fraction, the sum of squares, and a binomial expansion."
        print(f"\n[Turn 2] Question: {q2}")
        res2 = await AssistantService.answer_question(
            db=db,
            repository_id=repo.id,
            question=q2,
            conversation_id=conv.id
        )
        ans2 = res2["answer"]
        print(f"[Turn 2] Strategy: {res2.get('retrieval_strategy')} | Citations: {len(res2.get('citations', []))}")
        print(f"[Turn 2] Answer snippet:\n{ans2[:300]}...")

        # Current-question precedence: must NOT lead with or be dominated by Turn 1 (Pythagorean)
        assert not ans2.strip().lower().startswith("the pythagorean theorem"), "Turn 2 must NOT lead with Turn 1"
        assert not ans2.strip().lower().startswith("### 1. pythagorean theorem"), "Turn 2 must NOT lead with Turn 1"
        first_heading = next((l for l in ans2.splitlines() if l.strip().startswith("#")), "")
        assert "pythagorean" not in first_heading.lower(), "First heading must not be Pythagorean theorem"

        # Must answer ALL 4 requested items
        assert "einstein" in ans2.lower() or "mc^2" in ans2.lower(), "Turn 2 must answer Einstein equation"
        assert "fraction" in ans2.lower() or "\\frac" in ans2, "Turn 2 must answer fraction"
        assert "sum of squares" in ans2.lower() or "a^2 + b^2" in ans2, "Turn 2 must answer sum of squares"
        assert "binomial" in ans2.lower() or "(a + b)^2" in ans2 or "(x + y)^2" in ans2, "Turn 2 must answer binomial expansion"
        assert res2.get("citations") == [], "Educational question must have no repo citations"
        print("PASS: Turn 2 verified (All 4 parts covered, no Turn 1 contamination)")

        # =====================================================================
        # Turn 3: Quadratic Formula
        # =====================================================================
        q3 = "Explain the quadratic formula."
        print(f"\n[Turn 3] Question: {q3}")
        res3 = await AssistantService.answer_question(
            db=db,
            repository_id=repo.id,
            question=q3,
            conversation_id=conv.id
        )
        ans3 = res3["answer"]
        print(f"[Turn 3] Strategy: {res3.get('retrieval_strategy')} | Citations: {len(res3.get('citations', []))}")
        print(f"[Turn 3] Answer snippet:\n{ans3[:250]}...")

        assert "quadratic formula" in ans3.lower(), "Turn 3 must address quadratic formula"
        assert "\\frac{-b" in ans3 or "\\sqrt{b^2 - 4ac}" in ans3, "Turn 3 must include the quadratic formula in LaTeX"
        assert "no relevant source code" not in ans3.lower(), "Must NOT have repo-absence disclaimer"
        assert "unverified" not in ans3.lower(), "Must NOT have unverified disclaimer"
        assert res3.get("citations") == [], "Educational question must have no repo citations"
        print("PASS: Turn 3 verified (LaTeX quadratic formula, no disclaimers)")

        # =====================================================================
        # Turn 4: General Python list vs tuple
        # =====================================================================
        q4 = "What is the difference between a Python list and tuple?"
        print(f"\n[Turn 4] Question: {q4}")
        res4 = await AssistantService.answer_question(
            db=db,
            repository_id=repo.id,
            question=q4,
            conversation_id=conv.id
        )
        ans4 = res4["answer"]
        print(f"[Turn 4] Strategy: {res4.get('retrieval_strategy')} | Citations: {len(res4.get('citations', []))}")
        print(f"[Turn 4] Answer snippet:\n{ans4[:250]}...")

        assert "mutable" in ans4.lower() and "immutable" in ans4.lower(), "Turn 4 must explain mutability difference"
        assert "not found in the indexed source" not in ans4.lower(), "Must not claim absence from repo"
        assert res4.get("citations") == [], "General programming must have no repo citations"
        print("PASS: Turn 4 verified (General programming, list vs tuple mutability)")

        # =====================================================================
        # Turn 5: Repository-specific vector-similarity question
        # =====================================================================
        q5 = "Where does this repository calculate vector similarity?"
        print(f"\n[Turn 5] Question: {q5}")
        res5 = await AssistantService.answer_question(
            db=db,
            repository_id=repo.id,
            question=q5,
            conversation_id=conv.id
        )
        ans5 = res5["answer"]
        print(f"[Turn 5] Strategy: {res5.get('retrieval_strategy')} | Citations: {len(res5.get('citations', []))}")
        print(f"[Turn 5] Citations: {[c['file_path'] + ':' + str(c.get('start_line')) for c in res5.get('citations', [])]}")
        print(f"[Turn 5] Answer snippet:\n{ans5[:350]}...")

        # Grounding & citation verification
        assert len(res5.get("citations", [])) > 0, "Repository question must return citations"
        assert any("hybrid_engine.py" in c["file_path"] for c in res5["citations"]), "Must cite hybrid_engine.py"
        assert "backend/app/retrieval/hybrid_engine.py" in ans5, "Answer must reference hybrid_engine.py"
        assert "cosine_distance" in ans5, "Answer must mention pgvector cosine_distance"
        assert "_cosine_similarity" in ans5, "Answer must mention _cosine_similarity fallback"
        print("PASS: Turn 5 verified (pgvector cosine_distance + fallback cited)")

        # =====================================================================
        # ROBUSTNESS AUDIT: Reordered Multi-part & Varied Phrasing
        # =====================================================================
        print("\n--- ROBUSTNESS AUDIT ---")

        # Robustness 1: Reordered multi-part request
        q_reordered = "Explain a fraction, the sum of squares, a binomial expansion, and Einstein's equation."
        res_reord = await AssistantService.answer_question(
            db=db,
            repository_id=repo.id,
            question=q_reordered,
            conversation_id=conv.id
        )
        ans_reord = res_reord["answer"]
        assert "fraction" in ans_reord.lower()
        assert "sum of squares" in ans_reord.lower() or "a^2 + b^2" in ans_reord
        assert "binomial" in ans_reord.lower() or "(a + b)^2" in ans_reord
        assert "einstein" in ans_reord.lower() or "mc^2" in ans_reord
        print("PASS: Reordered multi-part request correctly handled")

        # Robustness 2: Varied mathematical wording
        q_var1 = "What is the formula for the hypotenuse in a right triangle?"
        res_var1 = await AssistantService.answer_question(
            db=db,
            repository_id=repo.id,
            question=q_var1,
        )
        assert ("a^2 + b^2" in res_var1["answer"] or "c^2" in res_var1["answer"])
        print("PASS: Varied math wording (hypotenuse formula) correctly handled")

        # Robustness 3: Generic keywords in educational query
        q_generic = "In mathematics, explain the list of formulas for quadratic equations and binomial expansions."
        intent_generic = AssistantService.classify_query_intent(q_generic)
        assert "GENERAL_EDUCATIONAL" in intent_generic
        assert "INDEXING_AND_EMBEDDINGS" not in intent_generic
        print("PASS: Generic keywords ('list', 'formulas') did not trigger repo selection")

        # Robustness 4: Follow-up question referencing previous formula
        q_followup = "What was the formula in the previous answer?"
        res_followup = await AssistantService.answer_question(
            db=db,
            repository_id=repo.id,
            question=q_followup,
            conversation_id=conv.id
        )
        assert res_followup["answer"] is not None and len(res_followup["answer"]) > 10
        print("PASS: Contextual follow-up question handled without crash")

        print("\n========================================================")
        print("ALL LIVE SEQUENTIAL & ROBUSTNESS TESTS PASSED SUCCESSFULLY!")
        print("========================================================")

    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(test_live_sequential_audit())
