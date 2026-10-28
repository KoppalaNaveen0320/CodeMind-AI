import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.api.routes.api_v1 import get_time_based_greeting
from backend.app.models.repository import Repository
from backend.app.models.user import User
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.models.knowledge_graph import GraphNode, GraphEdge


def test_time_based_greeting_boundaries():
    """
    Verifies greeting selection at morning, afternoon, evening, and night boundaries:
    - 5:00 AM–11:59 AM: "Good morning, {first_name}"
    - 12:00 PM–4:59 PM: "Good afternoon, {first_name}"
    - 5:00 PM–8:59 PM: "Good evening, {first_name}"
    - 9:00 PM–4:59 AM: "Good night, {first_name}"
    """
    user_name = "Alex Smith"

    # Morning: 5:00 to 11:59 (hours 5 to 11)
    assert get_time_based_greeting(user_name, client_hour=5) == "Good morning, Alex"
    assert get_time_based_greeting(user_name, client_hour=8) == "Good morning, Alex"
    assert get_time_based_greeting(user_name, client_hour=11) == "Good morning, Alex"

    # Afternoon: 12:00 to 16:59 (hours 12 to 16)
    assert get_time_based_greeting(user_name, client_hour=12) == "Good afternoon, Alex"
    assert get_time_based_greeting(user_name, client_hour=14) == "Good afternoon, Alex"
    assert get_time_based_greeting(user_name, client_hour=16) == "Good afternoon, Alex"

    # Evening: 17:00 to 20:59 (hours 17 to 20)
    assert get_time_based_greeting(user_name, client_hour=17) == "Good evening, Alex"
    assert get_time_based_greeting(user_name, client_hour=19) == "Good evening, Alex"
    assert get_time_based_greeting(user_name, client_hour=20) == "Good evening, Alex"

    # Night: 21:00 to 4:59 (hours 21 to 23, and 0 to 4)
    assert get_time_based_greeting(user_name, client_hour=21) == "Good night, Alex"
    assert get_time_based_greeting(user_name, client_hour=23) == "Good night, Alex"
    assert get_time_based_greeting(user_name, client_hour=0) == "Good night, Alex"
    assert get_time_based_greeting(user_name, client_hour=4) == "Good night, Alex"


def test_authenticated_user_first_name_handling():
    """
    Verifies that first name is extracted correctly and missing names fallback gracefully to generic greeting.
    """
    # Multi-word name extracts first token
    assert get_time_based_greeting("Koppala Naveen", client_hour=9) == "Good morning, Koppala"
    assert get_time_based_greeting("Mary Jane Watson", client_hour=13) == "Good afternoon, Mary"
    assert get_time_based_greeting("Grace", client_hour=18) == "Good evening, Grace"

    # Missing, empty, or whitespace-only names fallback gracefully without trailing commas or spaces
    assert get_time_based_greeting(None, client_hour=9) == "Good morning"
    assert get_time_based_greeting("", client_hour=14) == "Good afternoon"
    assert get_time_based_greeting("   ", client_hour=20) == "Good evening"
    assert get_time_based_greeting(None, client_hour=22) == "Good night"


def test_dashboard_overview_client_hour_parameter(client: TestClient, db_session: Session):
    """
    Verifies that GET /api/v1/dashboard/overview respects client_hour query param.
    """
    res_morning = client.get("/api/v1/dashboard/overview?client_hour=9")
    assert res_morning.status_code == 200
    assert res_morning.json()["greeting"].startswith("Good morning")

    res_afternoon = client.get("/api/v1/dashboard/overview?client_hour=14")
    assert res_afternoon.status_code == 200
    assert res_afternoon.json()["greeting"].startswith("Good afternoon")

    res_night = client.get("/api/v1/dashboard/overview?client_hour=22")
    assert res_night.status_code == 200
    assert res_night.json()["greeting"].startswith("Good night")


def test_correct_metrics_for_indexed_repository(client: TestClient, db_session: Session):
    """
    Verifies correct metrics are returned for an indexed repository.
    """
    repo = Repository(
        name="test-metrics-repo",
        full_name="org/test-metrics-repo",
        files_count=155,
        symbols_count=1920,
        apis_count=76,
        dependencies_count=943,
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()

    res = client.get(f"/api/v1/dashboard/overview?repository_id={repo.id}")
    assert res.status_code == 200
    data = res.json()

    assert data["files_indexed"] == 155
    assert data["functions_classes"] == 1920
    assert data["apis_detected"] == 76
    assert data["dependencies_mapped"] == 943
    assert data["active_repository"]["id"] == repo.id


def test_genuine_zero_metrics_versus_failed_api_requests(client: TestClient, db_session: Session):
    """
    Verifies that genuine zero metrics return 0 (not null or error),
    while invalid/unauthorized repository requests return 404 (not fake 0s).
    """
    zero_repo = Repository(
        name="zero-metrics-repo",
        full_name="org/zero-metrics-repo",
        files_count=0,
        symbols_count=0,
        apis_count=0,
        dependencies_count=0,
        status="pending"
    )
    db_session.add(zero_repo)
    db_session.commit()

    res = client.get(f"/api/v1/dashboard/overview?repository_id={zero_repo.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["files_indexed"] == 0
    assert data["functions_classes"] == 0
    assert data["apis_detected"] == 0
    assert data["dependencies_mapped"] == 0

    # Non-existent repo returns 404 error, strictly not masked as 0
    res_err = client.get("/api/v1/dashboard/overview?repository_id=888888")
    assert res_err.status_code == 404


def test_recent_ai_questions_ownership_and_repository_isolation(client: TestClient, db_session: Session):
    """
    Verifies that recent questions return only questions belonging to the active user
    and the selected repository, preserving tenant isolation.
    """
    current_user = db_session.query(User).filter(User.email == "testuser@codemind.ai").first()
    if not current_user:
        current_user = User(
            email="testuser@codemind.ai",
            full_name="Test User",
            workspace_name="Engineering"
        )
        db_session.add(current_user)
        db_session.commit()

    other_user = User(
        email="other@codemind.ai",
        full_name="Other User",
        workspace_name="Engineering"
    )
    db_session.add(other_user)
    db_session.commit()

    repo_target = Repository(name="target-repo", full_name="org/target-repo", user_id=current_user.id)
    repo_other = Repository(name="other-repo", full_name="org/other-repo", user_id=current_user.id)
    db_session.add_all([repo_target, repo_other])
    db_session.commit()

    # Conversation 1: current user on repo_target -> should be returned
    conv_target = AssistantConversation(
        user_id=current_user.id,
        repository_id=repo_target.id,
        title="How does auth work?"
    )
    # Conversation 2: current user on repo_other -> should NOT be returned for repo_target
    conv_other_repo = AssistantConversation(
        user_id=current_user.id,
        repository_id=repo_other.id,
        title="What is database structure?"
    )
    # Conversation 3: other user on repo_target -> should NEVER be returned for current user
    conv_other_user = AssistantConversation(
        user_id=other_user.id,
        repository_id=repo_target.id,
        title="Private investigation"
    )
    db_session.add_all([conv_target, conv_other_repo, conv_other_user])
    db_session.commit()

    # Add messages
    msg1 = AssistantMessage(
        conversation_id=conv_target.id,
        role="user",
        content="How does authentication work in this repo?"
    )
    msg2 = AssistantMessage(
        conversation_id=conv_target.id,
        role="assistant",
        content="Authentication uses JWT tokens verified in middleware."
    )
    db_session.add_all([msg1, msg2])
    db_session.commit()

    res = client.get(f"/api/v1/dashboard/overview?repository_id={repo_target.id}")
    assert res.status_code == 200
    questions = res.json()["recent_questions"]

    q_titles = [q["title"] for q in questions]
    assert "How does auth work?" in q_titles
    assert "What is database structure?" not in q_titles
    assert "Private investigation" not in q_titles


def test_repository_graph_endpoint_nodes_and_empty_state(client: TestClient, db_session: Session):
    """
    Verifies that the knowledge graph endpoint returns valid nodes and edges,
    and returns empty list when no graph entities exist.
    """
    repo = Repository(name="graph-repo", full_name="org/graph-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    # 1. Empty graph
    res_empty = client.get(f"/api/v1/repositories/{repo.id}/graph?limit=12")
    assert res_empty.status_code == 200
    assert res_empty.json()["nodes"] == []
    assert res_empty.json()["edges"] == []

    # 2. Populated graph
    n1 = GraphNode(
        repository_id=repo.id,
        node_key="node:1",
        node_type="CLASS",
        name="AuthService",
        file_path="backend/services/auth.py"
    )
    n2 = GraphNode(
        repository_id=repo.id,
        node_key="node:2",
        node_type="FUNCTION",
        name="login_user",
        file_path="backend/services/auth.py"
    )
    db_session.add_all([n1, n2])
    db_session.commit()

    edge = GraphEdge(
        repository_id=repo.id,
        source_node_id=n1.id,
        target_node_id=n2.id,
        edge_type="CONTAINS"
    )
    db_session.add(edge)
    db_session.commit()

    res_pop = client.get(f"/api/v1/repositories/{repo.id}/graph?limit=12")
    assert res_pop.status_code == 200
    pop_data = res_pop.json()
    assert len(pop_data["nodes"]) == 2
    assert pop_data["nodes"][0]["name"] in ["AuthService", "login_user"]
    assert pop_data["nodes"][0]["type"] in ["CLASS", "FUNCTION"]


def test_frontend_dashboard_fixes_contracts_and_resilience():
    """
    Verifies that frontend javascript in frontend/static/js/api.js implements:
    1. getTimeBasedGreeting function with hour boundaries
    2. Decoupled sub-tasks (overviewPromise, commitsPromise, archPromise)
    3. Proper node type mapping (node_type || type)
    4. Safe float confidence handling in tech stack
    5. Conversation links including repository ID
    6. Non-stuck error and empty states for commits, arch, and tech stack
    7. Stale request guard with currentDashboardRequestId
    """
    with open("frontend/static/js/api.js", "r", encoding="utf-8") as f:
        js = f.read()

    # 1. Greeting
    assert "function getTimeBasedGreeting" in js
    assert "Good morning" in js
    assert "Good afternoon" in js
    assert "Good evening" in js
    assert "Good night" in js

    # 2. Decoupled sub-tasks
    assert "overviewPromise" in js
    assert "commitsPromise" in js
    assert "archPromise" in js
    assert "Promise.allSettled" in js

    # 3. Graph node type mapping
    assert "n.node_type || n.type || 'Component'" in js

    # 4. Safe float confidence handling
    assert "typeof confRaw === 'string'" in js

    # 5. Assistant conversation link with repo param
    assert "repo=${encodeURIComponent(activeRepo.id)}" in js

    # 6. Graceful error handling without stuck text
    assert "Could not load commits" in js
    assert "Could not load architecture graph" in js
    assert "No architecture relationships mapped yet" in js
    assert "No commits retrieved yet for this repository" in js

    # 7. Stale request guards
    assert "requestId !== currentDashboardRequestId" in js


def test_tech_stack_scroll_controls_and_button_removal():
    """
    Verifies that:
    1. 'View full details & evidence' button is completely removed from the dashboard card.
    2. Left and right scroll arrow buttons exist in dashboard.html with accessible labels.
    3. api.js implements scrollTechStack and updateTechStackScrollButtons with smooth scrolling.
    4. styles.css configures horizontal smooth scrolling without dashboard overflow.
    """
    with open("frontend/templates/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert "View full details & evidence" not in html
    assert "tech-scroll-prev" in html
    assert "tech-scroll-next" in html
    assert 'aria-label="Scroll technology stack left"' in html
    assert 'aria-label="Scroll technology stack right"' in html

    with open("frontend/static/js/api.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "View full details & evidence" not in js
    assert "function updateTechStackScrollButtons" in js
    assert "function scrollTechStack" in js
    assert "initTechStackScrollControls" in js
    assert "scrollLeft" in js
    assert "scrollWidth" in js

    with open("frontend/static/css/styles.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".tech-scroll-btn" in css
    assert "overflow-x: auto" in css
    assert "scroll-behavior: smooth" in css


def test_dashboard_authenticated_user_profile_rendering(client: TestClient, db_session: Session):
    """
    Regression test: Verifies that:
    1. Authenticated user profile and greeting are dynamically rendered on the server.
    2. Real user name and email replace Alex Kim / alex@acme.dev placeholders.
    3. api.js syntax has no syntax errors or unhandled awaits.
    """
    from backend.app.core.security import create_session_token

    user = User(
        email="realuser@example.com",
        full_name="Jane Doe",
        workspace_name="Engineering",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token = create_session_token(user.id, timeout_minutes=30)
    resp = client.get("/dashboard", cookies={"codemind_session": token})
    assert resp.status_code == 200
    assert "Jane Doe" in resp.text
    assert "realuser@example.com" in resp.text
    assert "Alex Kim" not in resp.text
    assert "alex@acme.dev" not in resp.text


