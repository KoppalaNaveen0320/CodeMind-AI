import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from backend.app.models.repository import Repository
from backend.app.models.user import User


def test_dashboard_initially_loads_intended_repository(client: TestClient, db_session: Session):
    """
    1. Verifies that GET /api/v1/dashboard/overview initially loads the intended active repository
       without summing or combining metrics across different repositories in the workspace.
    """
    # Create two test repositories with distinct metrics
    repo_a = Repository(
        name="repo-alpha",
        full_name="org/repo-alpha",
        files_count=12,
        symbols_count=60,
        apis_count=4,
        dependencies_count=18,
        status="ready"
    )
    repo_b = Repository(
        name="repo-beta",
        full_name="org/repo-beta",
        files_count=85,
        symbols_count=420,
        apis_count=22,
        dependencies_count=110,
        status="ready"
    )
    db_session.add_all([repo_a, repo_b])
    db_session.commit()

    # Omit repository_id: overview must return active_repository's own isolated metrics, NOT the sum
    res = client.get("/api/v1/dashboard/overview")
    assert res.status_code == 200
    data = res.json()

    active_repo = data["active_repository"]
    assert active_repo is not None
    assert active_repo["id"] == repo_b.id  # Ordered by id desc
    assert data["files_indexed"] == 85
    assert data["functions_classes"] == 420
    assert data["apis_detected"] == 22
    assert data["dependencies_mapped"] == 110

    # Ensure cross-repo summation (12 + 85 = 97) is strictly prevented
    assert data["files_indexed"] != 97
    assert data["functions_classes"] != 480


def test_switching_expertdecision_to_tokenpool(client: TestClient, db_session: Session):
    """
    2. Verifies switching from expertdecision to TokenPool refreshes every repository-specific metric.
    """
    exp_repo = db_session.query(Repository).filter(Repository.name == "expertdecision").first()
    token_repo = db_session.query(Repository).filter(Repository.name == "TokenPool").first()

    if not exp_repo:
        exp_repo = Repository(
            name="expertdecision",
            full_name="KoppalaNaveen/expertdecision",
            files_count=208,
            symbols_count=1750,
            apis_count=59,
            dependencies_count=659,
            status="ready"
        )
        db_session.add(exp_repo)

    if not token_repo:
        token_repo = Repository(
            name="TokenPool",
            full_name="KoppalaNaveen0320/TokenPool",
            files_count=89,
            symbols_count=940,
            apis_count=55,
            dependencies_count=344,
            status="ready"
        )
        db_session.add(token_repo)
    db_session.commit()

    # 1. Fetch expertdecision
    res_exp = client.get(f"/api/v1/dashboard/overview?repository_id={exp_repo.id}")
    assert res_exp.status_code == 200
    data_exp = res_exp.json()
    assert data_exp["active_repository"]["id"] == exp_repo.id
    assert data_exp["files_indexed"] == exp_repo.files_count
    assert data_exp["functions_classes"] == exp_repo.symbols_count
    assert data_exp["apis_detected"] == exp_repo.apis_count
    assert data_exp["dependencies_mapped"] == exp_repo.dependencies_count

    # 2. Switch to TokenPool
    res_token = client.get(f"/api/v1/dashboard/overview?repository_id={token_repo.id}")
    assert res_token.status_code == 200
    data_token = res_token.json()
    assert data_token["active_repository"]["id"] == token_repo.id
    assert data_token["files_indexed"] == token_repo.files_count
    assert data_token["functions_classes"] == token_repo.symbols_count
    assert data_token["apis_detected"] == token_repo.apis_count
    assert data_token["dependencies_mapped"] == token_repo.dependencies_count

    # Metrics must differ and match their respective repos
    assert data_token["files_indexed"] != data_exp["files_indexed"]
    assert data_token["functions_classes"] != data_exp["functions_classes"]


def test_switching_to_pallets_flask(client: TestClient, db_session: Session):
    """
    3. Verifies switching to pallets/flask shows only Flask repository data.
    """
    flask_repo = db_session.query(Repository).filter(Repository.name == "flask").first()
    if not flask_repo:
        flask_repo = Repository(
            name="flask",
            full_name="pallets/flask",
            files_count=208,
            symbols_count=2864,
            apis_count=51,
            dependencies_count=906,
            status="ready"
        )
        db_session.add(flask_repo)
        db_session.commit()

    res = client.get(f"/api/v1/dashboard/overview?repository_id={flask_repo.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["active_repository"]["full_name"] == "pallets/flask"
    assert data["files_indexed"] == flask_repo.files_count
    assert data["functions_classes"] == flask_repo.symbols_count
    assert data["apis_detected"] == flask_repo.apis_count
    assert data["dependencies_mapped"] == flask_repo.dependencies_count


def test_switching_to_codemind_ui_ux_design(client: TestClient, db_session: Session):
    """
    4. Verifies switching to CodeMind_AI_UI_UX_Design shows its own data.
    """
    design_repo = db_session.query(Repository).filter(Repository.name == "CodeMind_AI_UI_UX_Design").first()
    if not design_repo:
        design_repo = Repository(
            name="CodeMind_AI_UI_UX_Design",
            full_name="local/CodeMind_AI_UI_UX_Design",
            files_count=10,
            symbols_count=47,
            apis_count=0,
            dependencies_count=11,
            status="ready"
        )
        db_session.add(design_repo)
        db_session.commit()

    res = client.get(f"/api/v1/dashboard/overview?repository_id={design_repo.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["active_repository"]["name"] == "CodeMind_AI_UI_UX_Design"
    assert data["files_indexed"] == design_repo.files_count
    assert data["functions_classes"] == design_repo.symbols_count
    assert data["apis_detected"] == design_repo.apis_count
    assert data["dependencies_mapped"] == design_repo.dependencies_count


def test_consecutive_switching_isolation(client: TestClient, db_session: Session):
    """
    5. Switching repositories repeatedly does not retain stale metrics or architecture nodes.
    """
    r1 = Repository(
        name="repo-isolated-1",
        full_name="test/repo-isolated-1",
        files_count=45,
        symbols_count=190,
        apis_count=11,
        dependencies_count=65,
        status="ready"
    )
    r2 = Repository(
        name="repo-isolated-2",
        full_name="test/repo-isolated-2",
        files_count=78,
        symbols_count=350,
        apis_count=24,
        dependencies_count=140,
        status="ready"
    )
    db_session.add_all([r1, r2])
    db_session.commit()

    res1 = client.get(f"/api/v1/dashboard/overview?repository_id={r1.id}").json()
    res2 = client.get(f"/api/v1/dashboard/overview?repository_id={r2.id}").json()
    res3 = client.get(f"/api/v1/dashboard/overview?repository_id={r1.id}").json()

    assert res1["active_repository"]["id"] == r1.id
    assert res2["active_repository"]["id"] == r2.id
    assert res3["active_repository"]["id"] == r1.id
    assert res1["files_indexed"] == res3["files_indexed"]
    assert res1["files_indexed"] == 45
    assert res2["files_indexed"] == 78


def test_unindexed_repository_metrics(client: TestClient, db_session: Session):
    """
    7. Verifies that connected but unindexed repositories show zero metrics without fabricated numbers.
    """
    unindexed = Repository(
        name="fresh-project",
        full_name="user/fresh-project",
        status="pending",
        files_count=0,
        symbols_count=0,
        apis_count=0,
        dependencies_count=0
    )
    db_session.add(unindexed)
    db_session.commit()

    res = client.get(f"/api/v1/dashboard/overview?repository_id={unindexed.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["active_repository"]["status"] == "pending"
    assert data["files_indexed"] == 0
    assert data["functions_classes"] == 0
    assert data["apis_detected"] == 0
    assert data["dependencies_mapped"] == 0


def test_every_repository_query_uses_selected_repository_id(client: TestClient, db_session: Session):
    """
    8. Verifies that every repository-specific query uses the selected repository ID
       and rejects invalid or non-existent repository IDs with 404.
    """
    res_bad = client.get("/api/v1/dashboard/overview?repository_id=999999")
    assert res_bad.status_code == 404

    res_bad_graph = client.get("/api/v1/repositories/999999/graph")
    assert res_bad_graph.status_code == 404

    res_bad_commits = client.get("/api/v1/repositories/999999/commits")
    assert res_bad_commits.status_code == 404


def test_adding_new_repository_displays_dynamically(client: TestClient, db_session: Session):
    """
    9. Adding another repository dynamically does not require code changes or hardcoded configuration.
    """
    new_repo = Repository(
        name="dynamic-service",
        full_name="corp/dynamic-service",
        description="Newly onboarded microservice",
        primary_language="Go",
        default_branch="master",
        status="ready",
        files_count=42,
        symbols_count=310,
        apis_count=18,
        dependencies_count=88
    )
    db_session.add(new_repo)
    db_session.commit()

    res = client.get(f"/api/v1/dashboard/overview?repository_id={new_repo.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["active_repository"]["name"] == "dynamic-service"
    assert data["active_repository"]["default_branch"] == "master"
    assert data["files_indexed"] == 42
    assert data["functions_classes"] == 310
    assert data["apis_detected"] == 18
    assert data["dependencies_mapped"] == 88


def test_frontend_repository_switcher_and_stale_data_guard():
    """
    6 & UI. Verifies that frontend code includes:
    - currentDashboardRequestId for race-condition cancellation
    - switchActiveRepository global handler
    - Interactive repo dropdown UI (.repo-dropdown-menu)
    - Clickable repository link to dashboard.html?repo=
    - Overview action in repositories table
    """
    with open("frontend/static/js/api.js", "r", encoding="utf-8") as f:
        js_content = f.read()

    assert "currentDashboardRequestId" in js_content, "Missing requestId race condition protection"
    assert "requestId !== currentDashboardRequestId" in js_content, "Missing stale response check"
    assert "switchActiveRepository" in js_content, "Missing window.switchActiveRepository"
    assert "codemind-repo-dropdown" in js_content, "Missing codemind-repo-dropdown menu element"
    assert "/dashboard?repo=" in js_content or "dashboard.html?repo=" in js_content, "Missing /dashboard?repo= link in repository table"
    assert "title=\"View Dashboard Overview\">Overview</a>" in js_content, "Missing Overview action button in table"

    with open("frontend/static/css/styles.css", "r", encoding="utf-8") as f:
        css_content = f.read()

    assert ".repo-dropdown-menu" in css_content, "Missing .repo-dropdown-menu CSS"
    assert ".repo-dropdown-item" in css_content, "Missing .repo-dropdown-item CSS"
    assert ".repo-title-link" in css_content, "Missing .repo-title-link CSS"
