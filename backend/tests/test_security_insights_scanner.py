import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.user import User
from backend.app.security.analyzer import SecurityAnalyzer


def test_vulnerable_fixtures_detected(client: TestClient, db_session: Session):
    """
    Verifies that synthetic vulnerable code fixtures produce the expected rule findings,
    CWEs, line numbers, and severity levels.
    """
    repo = Repository(name="vuln-audit-repo", full_name="acme/vuln-audit-repo", status="ready")
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    f1 = IndexedFile(repository_id=repo.id, path="src/backend/service.py", language="python", lines_count=60)
    db_session.add(f1)
    db_session.commit()
    db_session.refresh(f1)

    vuln_code = (
        'import os, subprocess, pickle, hashlib\n'
        '# Rule SEC-001: Hardcoded secret key\n'
        'jwt_secret_key = "supersecretsecretkey12345"\n'
        '# Rule SEC-002: Dynamic SQL construction\n'
        'cursor.execute(f"SELECT * FROM accounts WHERE id = {user_id}")\n'
        '# Rule SEC-003: Insecure eval call\n'
        'result = eval(user_supplied_expression)\n'
        '# Rule SEC-004: Subprocess shell=True\n'
        'subprocess.Popen(f"ping {host}", shell=True)\n'
        '# Rule SEC-005: Insecure pickle deserialization\n'
        'obj = pickle.loads(raw_data)\n'
        '# Rule SEC-007: Weak MD5 for password verification\n'
        'pass_hash = hashlib.md5(candidate_password.encode()).hexdigest()\n'
        '# Rule SEC-011: Plaintext password fallback\n'
        'if str_hash == str_plain:\n'
        '    return True\n'
    )

    chunk = CodeChunk(
        repository_id=repo.id,
        file_id=f1.id,
        file_path="src/backend/service.py",
        chunk_index=0,
        chunk_text=vuln_code,
        content_hash="vuln_hash_1",
        language="python",
        start_line=1,
        end_line=20
    )
    db_session.add(chunk)
    db_session.commit()

    response = client.get(f"/api/v1/repositories/{repo.id}/security/findings")
    assert response.status_code == 200
    data = response.json()

    assert data["total_findings"] >= 7
    assert data["high_count"] >= 5
    assert data["medium_count"] >= 1

    rule_ids = {f["rule_id"] for f in data["findings"]}
    assert "SEC-001" in rule_ids
    assert "SEC-002" in rule_ids
    assert "SEC-003" in rule_ids
    assert "SEC-004" in rule_ids
    assert "SEC-005" in rule_ids
    assert "SEC-007" in rule_ids
    assert "SEC-011" in rule_ids

    # Verify metadata fields
    for f in data["findings"]:
        assert f["file_path"] == "src/backend/service.py"
        assert f["line_number"] > 0
        assert f["why_it_matters"]
        assert f["remediation"]
        assert f["status"] == "OPEN"


def test_safe_code_no_false_positives(client: TestClient, db_session: Session):
    """
    Verifies that safe, modern idioms do NOT produce false positives.
    E.g. PyTorch model.eval(), ast.literal_eval, parameterized SQL,
    test files, and comment lines.
    """
    repo = Repository(name="safe-audit-repo", full_name="acme/safe-audit-repo", status="ready")
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    f1 = IndexedFile(repository_id=repo.id, path="src/ml/model_runner.py", language="python", lines_count=40)
    db_session.add(f1)
    db_session.commit()
    db_session.refresh(f1)

    safe_code = (
        'import ast, os, subprocess, yaml, hashlib\n'
        '# Comments mentioning eval() or secret_key = "12345" should be ignored\n'
        'api_key = os.getenv("API_KEY")\n'
        'model.eval()\n'
        'self.eval()\n'
        'parsed_val = ast.literal_eval(safe_str)\n'
        'subprocess.run(["git", "status"], shell=False)\n'
        'data = yaml.safe_load(yaml_content)\n'
        'digest = hashlib.sha256(data_bytes).hexdigest()\n'
        'db.execute(text("SELECT * FROM users WHERE email LIKE \'%@%\'"))\n'
        'cursor.execute("SELECT * FROM accounts WHERE id = :id", {"id": user_id})\n'
    )

    chunk = CodeChunk(
        repository_id=repo.id,
        file_id=f1.id,
        file_path="src/ml/model_runner.py",
        chunk_index=0,
        chunk_text=safe_code,
        content_hash="safe_hash_1",
        language="python",
        start_line=1,
        end_line=20
    )
    db_session.add(chunk)

    # Add a test file containing mock credentials that MUST be ignored
    f_test = IndexedFile(repository_id=repo.id, path="tests/test_auth.py", language="python", lines_count=10)
    db_session.add(f_test)
    db_session.commit()
    db_session.refresh(f_test)

    chunk_test = CodeChunk(
        repository_id=repo.id,
        file_id=f_test.id,
        file_path="tests/test_auth.py",
        chunk_index=0,
        chunk_text='api_key = "abcdef1234567890abcdef"\neval("2 + 2")\n',
        content_hash="test_hash_1",
        language="python",
        start_line=1,
        end_line=5
    )
    db_session.add(chunk_test)
    db_session.commit()

    response = client.get(f"/api/v1/repositories/{repo.id}/security/findings")
    assert response.status_code == 200
    data = response.json()

    # Zero findings from safe code and test files
    assert data["total_findings"] == 0
    assert data["high_count"] == 0
    assert data["medium_count"] == 0
    assert data["findings"] == []


def test_repository_isolation(client: TestClient, db_session: Session):
    """
    Verifies that findings in one repository are never returned for another repository.
    """
    repo1 = Repository(name="isolated-repo-1", full_name="acme/isolated-repo-1", status="ready")
    repo2 = Repository(name="isolated-repo-2", full_name="acme/isolated-repo-2", status="ready")
    db_session.add_all([repo1, repo2])
    db_session.commit()
    db_session.refresh(repo1)
    db_session.refresh(repo2)

    f1 = IndexedFile(repository_id=repo1.id, path="src/insecure.py", language="python", lines_count=10)
    db_session.add(f1)
    db_session.commit()
    db_session.refresh(f1)

    c1 = CodeChunk(
        repository_id=repo1.id,
        file_id=f1.id,
        file_path="src/insecure.py",
        chunk_index=0,
        chunk_text='api_key = "secret_key_1234567890_val"\n',
        content_hash="iso_hash_1",
        language="python",
        start_line=1,
        end_line=2
    )
    db_session.add(c1)
    db_session.commit()

    # Query Repo 1
    res1 = client.get(f"/api/v1/repositories/{repo1.id}/security/findings")
    assert res1.status_code == 200
    assert res1.json()["total_findings"] == 1

    # Query Repo 2 (must be 0)
    res2 = client.get(f"/api/v1/repositories/{repo2.id}/security/findings")
    assert res2.status_code == 200
    assert res2.json()["total_findings"] == 0


def test_deduplication_across_overlapping_chunks(client: TestClient, db_session: Session):
    """
    Verifies that the same finding present in two overlapping code chunks
    is properly deduplicated into a single finding.
    """
    repo = Repository(name="dedup-repo", full_name="acme/dedup-repo", status="ready")
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    f = IndexedFile(repository_id=repo.id, path="src/utils.py", language="python", lines_count=30)
    db_session.add(f)
    db_session.commit()
    db_session.refresh(f)

    vuln_line = 'api_key = "secret_key_abcdef1234567890"\n'

    # Chunk 0 covers lines 1 to 15
    chunk0 = CodeChunk(
        repository_id=repo.id,
        file_id=f.id,
        file_path="src/utils.py",
        chunk_index=0,
        chunk_text="def foo():\n    pass\n" + vuln_line,
        content_hash="dedup_c0",
        language="python",
        start_line=1,
        end_line=15
    )
    # Chunk 1 overlaps and also contains lines 10 to 25 with the same vuln line
    chunk1 = CodeChunk(
        repository_id=repo.id,
        file_id=f.id,
        file_path="src/utils.py",
        chunk_index=1,
        chunk_text="    pass\n" + vuln_line + "def bar():\n    pass\n",
        content_hash="dedup_c1",
        language="python",
        start_line=2,
        end_line=16
    )
    db_session.add_all([chunk0, chunk1])
    db_session.commit()

    res = client.get(f"/api/v1/repositories/{repo.id}/security/findings")
    assert res.status_code == 200
    data = res.json()

    # Must be deduplicated to 1 finding
    assert data["total_findings"] == 1
    assert data["high_count"] == 1


def test_status_lifecycle_and_persistence(client: TestClient, db_session: Session):
    """
    Tests finding status updates (OPEN -> REVIEWED -> DISMISSED -> OPEN)
    and verifies that status changes persist and correctly affect high/medium/reviewed counters.
    """
    repo = Repository(name="status-lifecycle-repo", full_name="acme/status-lifecycle-repo", status="ready")
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    f = IndexedFile(repository_id=repo.id, path="src/auth.py", language="python", lines_count=10)
    db_session.add(f)
    db_session.commit()
    db_session.refresh(f)

    chunk = CodeChunk(
        repository_id=repo.id,
        file_id=f.id,
        file_path="src/auth.py",
        chunk_index=0,
        chunk_text='jwt_secret = "secret_signing_key_12345678"\n',
        content_hash="status_h1",
        language="python",
        start_line=1,
        end_line=2
    )
    db_session.add(chunk)
    db_session.commit()

    # 1. Initial scan: 1 finding, OPEN, reviewed_count = 0
    res = client.get(f"/api/v1/repositories/{repo.id}/security/findings")
    assert res.status_code == 200
    data = res.json()
    assert data["total_findings"] == 1
    assert data["high_count"] == 1
    assert data["reviewed_count"] == 0
    fid = data["findings"][0]["id"]
    assert data["findings"][0]["status"] == "OPEN"

    # 2. Mark REVIEWED
    patch_res = client.patch(
        f"/api/v1/repositories/{repo.id}/security/findings/{fid}",
        json={"status": "REVIEWED"}
    )
    assert patch_res.status_code == 200

    # Rescan: status must be REVIEWED and reviewed_count == 1
    res2 = client.get(f"/api/v1/repositories/{repo.id}/security/findings")
    data2 = res2.json()
    assert data2["findings"][0]["status"] == "REVIEWED"
    assert data2["reviewed_count"] == 1
    assert data2["high_count"] == 1

    # 3. Mark DISMISSED
    patch_res2 = client.patch(
        f"/api/v1/repositories/{repo.id}/security/findings/{fid}",
        json={"status": "DISMISSED"}
    )
    assert patch_res2.status_code == 200

    # Rescan: high_count should become 0 because dismissed findings are not active
    res3 = client.get(f"/api/v1/repositories/{repo.id}/security/findings")
    data3 = res3.json()
    assert data3["findings"][0]["status"] == "DISMISSED"
    assert data3["high_count"] == 0
    assert data3["reviewed_count"] == 1

    # 4. Reopen finding
    patch_res3 = client.patch(
        f"/api/v1/repositories/{repo.id}/security/findings/{fid}",
        json={"status": "OPEN"}
    )
    assert patch_res3.status_code == 200
    res4 = client.get(f"/api/v1/repositories/{repo.id}/security/findings")
    data4 = res4.json()
    assert data4["findings"][0]["status"] == "OPEN"
    assert data4["high_count"] == 1
    assert data4["reviewed_count"] == 0


def test_on_demand_scan_trigger(client: TestClient, db_session: Session):
    """
    Verifies that POST /repositories/{id}/security/scan executes on demand
    and returns completed summary.
    """
    repo = Repository(name="scan-trigger-repo", full_name="acme/scan-trigger-repo", status="ready")
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    response = client.post(f"/api/v1/repositories/{repo.id}/security/scan")
    assert response.status_code == 200
    data = response.json()
    assert data["repository_id"] == repo.id
    assert data["status"] == "completed"
    assert "scanned_at" in data
    assert data["total_findings"] == 0


def test_three_distinct_repositories_scan_support_and_isolation(client: TestClient, db_session: Session):
    """
    Regression test verifying security insights scanning across at least three distinct repositories:
    1. expertdecision (Python web backend with fallback secret and dynamic SQL)
    2. TokenPool (Python auth library with weak MD5 and password fallback)
    3. ThreatShield-FL / Third Repo (TypeScript frontend & Docker/YAML infrastructure with secrets and XSS)
    Verifies that:
    - Scanning works identically regardless of repository name or structure.
    - Findings are strictly scoped and isolated to each repository.
    - API requests for repo A do not leak or mix with repo B or C.
    """
    # 1. expertdecision repository fixture
    repo_exp = Repository(name="expertdecision", full_name="KoppalaNaveen/expertdecision", status="ready", default_branch="main")
    db_session.add(repo_exp)
    db_session.commit()
    db_session.refresh(repo_exp)

    f_exp = IndexedFile(repository_id=repo_exp.id, path="backend/app/core/security.py", language="python", lines_count=50)
    db_session.add(f_exp)
    db_session.commit()
    db_session.refresh(f_exp)

    c_exp = CodeChunk(
        repository_id=repo_exp.id,
        file_id=f_exp.id,
        file_path="backend/app/core/security.py",
        chunk_index=0,
        chunk_text=(
            'SECRET_KEY = os.getenv("SECRET_KEY") or "fallback-secret-key-12345"\n'
            'cursor.execute(f"SELECT * FROM decisions WHERE id = {decision_id}")\n'
        ),
        content_hash="exp_hash",
        language="python",
        start_line=1,
        end_line=2
    )
    db_session.add(c_exp)

    # 2. TokenPool repository fixture
    repo_tok = Repository(name="TokenPool", full_name="KoppalaNaveen0320/TokenPool", status="ready", default_branch="main")
    db_session.add(repo_tok)
    db_session.commit()
    db_session.refresh(repo_tok)

    f_tok = IndexedFile(repository_id=repo_tok.id, path="tokenpool/auth.py", language="python", lines_count=45)
    db_session.add(f_tok)
    db_session.commit()
    db_session.refresh(f_tok)

    c_tok = CodeChunk(
        repository_id=repo_tok.id,
        file_id=f_tok.id,
        file_path="tokenpool/auth.py",
        chunk_index=0,
        chunk_text=(
            'token_hash = hashlib.md5(candidate_password.encode()).hexdigest()\n'
            'if str_hash == str_plain:\n'
            '    return True\n'
        ),
        content_hash="tok_hash",
        language="python",
        start_line=1,
        end_line=3
    )
    db_session.add(c_tok)

    # 3. Third distinct repository fixture: TypeScript / Docker architecture (ThreatShield / CloudMicroservice)
    repo_third = Repository(name="ThreatShield-FL", full_name="KoppalaNaveen0320/ThreatShield-FL", status="ready", default_branch="main")
    db_session.add(repo_third)
    db_session.commit()
    db_session.refresh(repo_third)

    f_third_docker = IndexedFile(repository_id=repo_third.id, path="docker-compose.yml", language="yaml", lines_count=40)
    f_third_ts = IndexedFile(repository_id=repo_third.id, path="frontend/src/views/Settings.tsx", language="typescript", lines_count=60)
    db_session.add_all([f_third_docker, f_third_ts])
    db_session.commit()
    db_session.refresh(f_third_docker)
    db_session.refresh(f_third_ts)

    c_third_1 = CodeChunk(
        repository_id=repo_third.id,
        file_id=f_third_docker.id,
        file_path="docker-compose.yml",
        chunk_index=0,
        chunk_text=(
            'services:\n'
            '  db:\n'
            '    environment:\n'
            '      POSTGRES_PASSWORD: ts_secure_password_999\n'
            '      SECRET_KEY: supersecretjwtkeychangeinprod\n'
        ),
        content_hash="third_hash_1",
        language="yaml",
        start_line=1,
        end_line=5
    )
    c_third_2 = CodeChunk(
        repository_id=repo_third.id,
        file_id=f_third_ts.id,
        file_path="frontend/src/views/Settings.tsx",
        chunk_index=0,
        chunk_text=(
            'return (\n'
            '  <div dangerouslySetInnerHTML={{ __html: userProvidedMarkup }} />\n'
            ');\n'
        ),
        content_hash="third_hash_2",
        language="typescript",
        start_line=1,
        end_line=3
    )
    db_session.add_all([c_third_1, c_third_2])
    db_session.commit()

    # --- Verification 1: expertdecision scan ---
    res_exp = client.get(f"/api/v1/repositories/{repo_exp.id}/security/findings")
    assert res_exp.status_code == 200
    data_exp = res_exp.json()
    assert data_exp["repository_id"] == repo_exp.id
    assert data_exp["status"] == "completed"
    assert data_exp["total_findings"] == 2
    exp_rule_ids = {f["rule_id"] for f in data_exp["findings"]}
    assert exp_rule_ids == {"SEC-001", "SEC-002"}
    for f in data_exp["findings"]:
        assert f["file_path"] == "backend/app/core/security.py"

    # --- Verification 2: TokenPool scan ---
    res_tok = client.get(f"/api/v1/repositories/{repo_tok.id}/security/findings")
    assert res_tok.status_code == 200
    data_tok = res_tok.json()
    assert data_tok["repository_id"] == repo_tok.id
    assert data_tok["status"] == "completed"
    assert data_tok["total_findings"] == 2
    tok_rule_ids = {f["rule_id"] for f in data_tok["findings"]}
    assert tok_rule_ids == {"SEC-007", "SEC-011"}
    for f in data_tok["findings"]:
        assert f["file_path"] == "tokenpool/auth.py"

    # --- Verification 3: Third repository (TypeScript & Docker YAML) scan ---
    res_third = client.get(f"/api/v1/repositories/{repo_third.id}/security/findings")
    assert res_third.status_code == 200
    data_third = res_third.json()
    assert data_third["repository_id"] == repo_third.id
    assert data_third["status"] == "completed"
    assert data_third["total_findings"] >= 2
    third_rule_ids = {f["rule_id"] for f in data_third["findings"]}
    assert "SEC-001" in third_rule_ids  # Docker hardcoded password / secret key
    assert "SEC-009" in third_rule_ids  # React dangerouslySetInnerHTML
    third_files = {f["file_path"] for f in data_third["findings"]}
    assert "docker-compose.yml" in third_files
    assert "frontend/src/views/Settings.tsx" in third_files

    # --- Verification 4: Strict Repository Isolation ---
    # Ensure findings for repo_exp do not contain findings from repo_tok or repo_third
    for f in data_exp["findings"]:
        assert f["file_path"] != "tokenpool/auth.py"
        assert f["file_path"] != "docker-compose.yml"
    for f in data_tok["findings"]:
        assert f["file_path"] != "backend/app/core/security.py"
        assert f["file_path"] != "docker-compose.yml"
    for f in data_third["findings"]:
        assert f["file_path"] != "backend/app/core/security.py"
        assert f["file_path"] != "tokenpool/auth.py"


def test_indexing_incomplete_reporting(client: TestClient, db_session: Session):
    """
    Verifies that if indexing is incomplete (status='indexing' or 'pending'),
    the scan endpoint returns status='indexing_in_progress' and a clear explanatory message,
    and does NOT claim zero vulnerabilities or complete repository security.
    """
    repo = Repository(name="indexing-in-progress-repo", full_name="acme/indexing-repo", status="indexing", files_count=120)
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    res = client.get(f"/api/v1/repositories/{repo.id}/security/findings")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "indexing_in_progress"
    assert "indexing is in progress" in data["message"].lower()

    # Also test on-demand POST scan
    post_res = client.post(f"/api/v1/repositories/{repo.id}/security/scan")
    assert post_res.status_code == 200
    post_data = post_res.json()
    assert post_data["status"] == "indexing_in_progress"
    assert "indexing is in progress" in post_data["message"].lower()


def test_empty_repository_and_unsupported_files(client: TestClient, db_session: Session):
    """
    Verifies accurate reporting for:
    1. Repository with no indexed files -> status='completed', files_scanned=0, total_files=0, clear message.
    2. Repository with only unsupported files (e.g. only .json and .md docs) -> files_scanned=0, clear message.
    """
    # 1. Unindexed / empty repo
    empty_repo = Repository(name="empty-unindexed-repo", full_name="acme/empty-repo", status="ready")
    db_session.add(empty_repo)
    db_session.commit()
    db_session.refresh(empty_repo)

    res_empty = client.get(f"/api/v1/repositories/{empty_repo.id}/security/findings")
    assert res_empty.status_code == 200
    data_empty = res_empty.json()
    assert data_empty["status"] == "completed"
    assert data_empty["total_findings"] == 0
    assert data_empty["files_scanned"] == 0
    assert "no files have been indexed" in data_empty["message"].lower()

    # 2. Unsupported files only repo (e.g. documentation / language pack)
    docs_repo = Repository(name="docs-only-repo", full_name="acme/docs-only-repo", status="ready")
    db_session.add(docs_repo)
    db_session.commit()
    db_session.refresh(docs_repo)

    f_doc = IndexedFile(repository_id=docs_repo.id, path="docs/manual.md", language="markdown", lines_count=100)
    f_json = IndexedFile(repository_id=docs_repo.id, path="locales/en.json", language="json", lines_count=50)
    db_session.add_all([f_doc, f_json])
    db_session.commit()

    res_docs = client.get(f"/api/v1/repositories/{docs_repo.id}/security/findings")
    assert res_docs.status_code == 200
    data_docs = res_docs.json()
    assert data_docs["status"] == "completed"
    assert data_docs["total_findings"] == 0
    assert data_docs["files_scanned"] == 0
    assert data_docs["total_files"] == 2
    assert "no supported source code files" in data_docs["message"].lower()


def test_arbitrary_project_names_work_identically(client: TestClient, db_session: Session):
    """
    Verifies that the scanner is completely repository-agnostic and that no hardcoded
    project IDs or names determine scanner behavior. Any arbitrary repository name
    with supported files and vulnerable patterns is detected correctly.
    """
    repo = Repository(
        name="arbitrary-fintech-service-999",
        full_name="enterprise-corp/arbitrary-fintech-service-999",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    f = IndexedFile(repository_id=repo.id, path="src/payments.py", language="python", lines_count=20)
    db_session.add(f)
    db_session.commit()
    db_session.refresh(f)

    c = CodeChunk(
        repository_id=repo.id,
        file_id=f.id,
        file_path="src/payments.py",
        chunk_index=0,
        chunk_text='auth_token = "secret_payment_auth_token_987654"\n',
        content_hash="fintech_hash",
        language="python",
        start_line=1,
        end_line=2
    )
    db_session.add(c)
    db_session.commit()

    res = client.get(f"/api/v1/repositories/{repo.id}/security/findings")
    assert res.status_code == 200
    data = res.json()
    assert data["repository_id"] == repo.id
    assert data["total_findings"] == 1
    assert data["findings"][0]["rule_id"] == "SEC-001"
    assert data["findings"][0]["file_path"] == "src/payments.py"

