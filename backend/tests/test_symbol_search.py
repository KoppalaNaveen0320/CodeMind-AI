import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk


def test_symbol_search_exact_vs_partial_ranking(client: TestClient, db_session: Session):
    repo = Repository(name="test-symbol-repo", full_name="org/test-symbol-repo", default_branch="main", status="ready")
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(repository_id=repo.id, path="app/users.py", language="python")
    f2 = IndexedFile(repository_id=repo.id, path="tests/test_users.py", language="python")
    f3 = IndexedFile(repository_id=repo.id, path="app/constants.py", language="python")
    f4 = IndexedFile(repository_id=repo.id, path="app/other.py", language="python")
    db_session.add_all([f1, f2, f3, f4])
    db_session.commit()

    s1 = CodeSymbol(repository_id=repo.id, file_id=f1.id, name="find_user", kind="function", start_line=10, end_line=20)
    s2 = CodeSymbol(repository_id=repo.id, file_id=f1.id, name="find_user_by_id", kind="function", start_line=30, end_line=40)
    s3 = CodeSymbol(repository_id=repo.id, file_id=f2.id, name="should_find_user", kind="function", start_line=5, end_line=15)
    s4 = CodeSymbol(repository_id=repo.id, file_id=f3.id, name="FIND_USER", kind="constant", start_line=1, end_line=2)
    s5 = CodeSymbol(repository_id=repo.id, file_id=f4.id, name="unrelated_func", kind="function", start_line=1, end_line=10)

    db_session.add_all([s1, s2, s3, s4, s5])
    db_session.commit()

    resp = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=find_user")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_count"] == 4
    names = [s["name"] for s in data["symbols"]]
    # Exact case match should be first
    assert names[0] == "find_user"
    # Case-insensitive exact match should be second
    assert names[1] == "FIND_USER"
    # Prefix match before partial match
    assert names[2] == "find_user_by_id"
    assert names[3] == "should_find_user"


def test_symbol_search_case_insensitivity(client: TestClient, db_session: Session):
    repo = Repository(name="case-repo", full_name="org/case-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="app/metrics.py", language="python")
    db_session.add(f)
    db_session.commit()

    s = CodeSymbol(repository_id=repo.id, file_id=f.id, name="CalculateMetrics", kind="function", start_line=1, end_line=10)
    db_session.add(s)
    db_session.commit()

    resp = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=calculatemetrics")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["symbols"]) == 1
    assert data["symbols"][0]["name"] == "CalculateMetrics"


def test_symbol_search_multiple_files_disambiguation(client: TestClient, db_session: Session):
    repo = Repository(name="disambig-repo", full_name="org/disambig-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(repository_id=repo.id, path="app/auth/jwt.py", language="python")
    f2 = IndexedFile(repository_id=repo.id, path="app/auth/oauth.py", language="python")
    db_session.add_all([f1, f2])
    db_session.commit()

    s1 = CodeSymbol(repository_id=repo.id, file_id=f1.id, name="authenticate", kind="function", start_line=10, end_line=25)
    s2 = CodeSymbol(repository_id=repo.id, file_id=f2.id, name="authenticate", kind="function", start_line=15, end_line=30)
    db_session.add_all([s1, s2])
    db_session.commit()

    resp = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=authenticate")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["symbols"]) == 2
    paths = {s["file_path"] for s in data["symbols"]}
    assert paths == {"app/auth/jwt.py", "app/auth/oauth.py"}
    ids = {s["id"] for s in data["symbols"]}
    assert len(ids) == 2


def test_symbol_search_filters(client: TestClient, db_session: Session):
    repo = Repository(name="filter-repo", full_name="org/filter-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(repository_id=repo.id, path="app/services/user.py", language="python")
    f2 = IndexedFile(repository_id=repo.id, path="frontend/src/client.ts", language="typescript")
    db_session.add_all([f1, f2])
    db_session.commit()

    s1 = CodeSymbol(repository_id=repo.id, file_id=f1.id, name="UserService", kind="class", start_line=1, end_line=50)
    s2 = CodeSymbol(repository_id=repo.id, file_id=f1.id, name="create_user", kind="function", start_line=52, end_line=80)
    s3 = CodeSymbol(repository_id=repo.id, file_id=f2.id, name="UserClient", kind="class", start_line=1, end_line=40)
    db_session.add_all([s1, s2, s3])
    db_session.commit()

    # Filter by symbol_type
    resp_type = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=User&symbol_type=class")
    assert resp_type.status_code == 200
    assert len(resp_type.json()["symbols"]) == 2
    for s in resp_type.json()["symbols"]:
        assert s["symbol_type"] == "class"

    # Filter by file_path
    resp_path = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=User&file_path=app/services/user.py")
    assert resp_path.status_code == 200
    assert len(resp_path.json()["symbols"]) == 2
    for s in resp_path.json()["symbols"]:
        assert "app/services/user.py" in s["file_path"]

    # Filter by language
    resp_lang = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=User&language=typescript")
    assert resp_lang.status_code == 200
    assert len(resp_lang.json()["symbols"]) == 1
    assert resp_lang.json()["symbols"][0]["name"] == "UserClient"


def test_symbol_search_repository_isolation(client: TestClient, db_session: Session):
    repo1 = Repository(name="iso-repo-1", full_name="org/iso-repo-1", status="ready")
    repo2 = Repository(name="iso-repo-2", full_name="org/iso-repo-2", status="ready")
    db_session.add_all([repo1, repo2])
    db_session.commit()

    f1 = IndexedFile(repository_id=repo1.id, path="app/secret.py", language="python")
    f2 = IndexedFile(repository_id=repo2.id, path="app/public.py", language="python")
    db_session.add_all([f1, f2])
    db_session.commit()

    s1 = CodeSymbol(repository_id=repo1.id, file_id=f1.id, name="shared_secret_function", kind="function", start_line=1, end_line=10)
    s2 = CodeSymbol(repository_id=repo2.id, file_id=f2.id, name="public_function", kind="function", start_line=1, end_line=10)
    db_session.add_all([s1, s2])
    db_session.commit()

    resp = client.get(f"/api/v1/repositories/{repo2.id}/symbols/search?query=shared_secret")
    assert resp.status_code == 200
    assert len(resp.json()["symbols"]) == 0

    resp1 = client.get(f"/api/v1/repositories/{repo1.id}/symbols/search?query=shared_secret")
    assert resp1.status_code == 200
    assert len(resp1.json()["symbols"]) == 1


def test_symbol_search_pagination_and_empty(client: TestClient, db_session: Session):
    repo = Repository(name="page-repo", full_name="org/page-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="app/helpers.py", language="python")
    db_session.add(f)
    db_session.commit()

    for i in range(15):
        db_session.add(CodeSymbol(
            repository_id=repo.id,
            file_id=f.id,
            name=f"helper_func_{i:02d}",
            kind="function",
            start_line=i * 10 + 1,
            end_line=i * 10 + 9
        ))
    db_session.commit()

    # Page 1
    resp1 = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=helper_func&limit=5&offset=0")
    assert resp1.status_code == 200
    d1 = resp1.json()
    assert d1["total_count"] == 15
    assert len(d1["symbols"]) == 5
    assert d1["has_more"] is True

    # Page 2
    resp2 = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=helper_func&limit=5&offset=5")
    assert resp2.status_code == 200
    d2 = resp2.json()
    assert len(d2["symbols"]) == 5
    assert d2["symbols"][0]["name"] != d1["symbols"][0]["name"]

    # Empty match
    resp_empty = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=non_existent_symbol_xyz")
    assert resp_empty.status_code == 200
    de = resp_empty.json()
    assert de["total_count"] == 0
    assert len(de["symbols"]) == 0
    assert de["has_more"] is False


def test_symbol_detail_and_source_coords(client: TestClient, db_session: Session):
    repo = Repository(name="detail-repo", full_name="org/detail-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="app/billing/tax.py", language="python")
    db_session.add(f)
    db_session.commit()

    sym = CodeSymbol(
        repository_id=repo.id,
        file_id=f.id,
        name="calculate_tax",
        kind="function",
        start_line=45,
        end_line=75
    )
    db_session.add(sym)
    db_session.commit()

    # Add code chunk
    chunk = CodeChunk(
        repository_id=repo.id,
        file_id=f.id,
        file_path="app/billing/tax.py",
        start_line=40,
        end_line=80,
        chunk_index=0,
        chunk_text="def calculate_tax(amount: float) -> float:\n    rate = 0.08\n    return amount * rate\n",
        content_hash="hash_calculate_tax_001",
        language="python"
    )
    db_session.add(chunk)
    db_session.commit()

    # Search returns preview snippet
    resp = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=calculate_tax")
    assert resp.status_code == 200
    item = resp.json()["symbols"][0]
    assert item["start_line"] == 45
    assert item["end_line"] == 75
    assert item["file_path"] == "app/billing/tax.py"
    assert "calculate_tax" in (item["snippet"] or "")

    # Detail endpoint
    detail_resp = client.get(f"/api/v1/repositories/{repo.id}/symbols/{sym.id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["name"] == "calculate_tax"
    assert detail["file_path"] == "app/billing/tax.py"
    assert detail["start_line"] == 45
    assert detail["end_line"] == 75
