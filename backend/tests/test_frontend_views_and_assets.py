from fastapi.testclient import TestClient
import pytest


def test_dashboard_page(client: TestClient):
    """Verify root / and /dashboard load dashboard.html successfully."""
    for path in ["/", "/dashboard", "/dashboard.html"]:
        response = client.get(path, follow_redirects=True)
        assert response.status_code == 200
        assert "CodeMind" in response.text
        assert '<link rel="stylesheet" href="/static/css/styles.css"' in response.text


@pytest.mark.parametrize("route", [
    "/repositories",
    "/repositories.html",
    "/repositories_modal.html",
    "/assistant",
    "/assistant.html",
    "/assistant_empty.html",
    "/code_viewer.html",
    "/dependencies",
    "/dependencies.html",
    "/impact_analysis.html",
    "/git_history.html",
    "/security_insights.html",
    "/docs",
    "/docs.html",
    "/documentation",
    "/settings",
    "/settings.html",
    "/index.html",
    "/suite"
])
def test_all_html_pages_accessible(client: TestClient, route: str):
    """Verify every extracted Figma UI page is properly routed and served."""
    response = client.get(route, follow_redirects=True)
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "<!doctype html>" in response.text.lower()


def test_static_css_served(client: TestClient):
    """Verify static styles.css is served with correct css content."""
    response = client.get("/static/css/styles.css")
    assert response.status_code == 200
    assert ":root" in response.text


def test_static_js_served(client: TestClient):
    """Verify static api.js client is served with correct javascript content."""
    response = client.get("/static/js/api.js")
    assert response.status_code == 200
    assert "CodeMindAPI" in response.text


def test_static_favicon_served(client: TestClient):
    """Verify static favicon.svg is served."""
    response = client.get("/static/assets/favicon.svg")
    assert response.status_code == 200
    assert "<svg" in response.text


def test_assistant_layout_and_modal_markup(client: TestClient):
    """Verify assistant.html contains the three-panel layout and delete confirmation modal elements."""
    res = client.get("/assistant", follow_redirects=True)
    assert res.status_code == 200
    html = res.text
    # Three panels
    assert "assistant-page-body" in html
    assert "assistant-layout" in html
    assert "history-sidebar" in html
    assert "history-conversations-list" in html
    assert "conversation" in html
    assert "messages" in html
    assert "composer-wrap" in html
    assert "evidence-panel" in html
    assert "assistant-evidence-body" in html
    # Delete modal
    assert "delete-modal-backdrop" in html
    assert "delete-modal-conv-title" in html
    assert "delete-modal-confirm" in html
    assert "delete-modal-cancel" in html
    assert "delete-modal-error" in html


def test_independent_scrolling_css_rules(client: TestClient):
    """Verify styles.css enforces viewport-constrained layout and independent panel scrolling."""
    res = client.get("/static/css/styles.css")
    assert res.status_code == 200
    css = res.text
    # Viewport containment
    assert "body.assistant-page-body" in css
    assert "overscroll-behavior: contain" in css
    # Confirm history list, messages, and evidence-body scroll independently
    assert ".history-list {" in css
    assert ".messages {" in css
    assert ".evidence-body {" in css
    # Confirm assistant-layout is not overridden by full-page-mode height: auto
    assert ".full-page-mode .assistant-layout" not in css


def test_api_js_client_improvements(client: TestClient):
    """Verify api.js contains 204 support, collision-proof markdown placeholders, and scroll logic."""
    res = client.get("/static/js/api.js")
    assert res.status_code == 200
    js = res.text
    # 204 No Content handling
    assert "response.status === 204" in js
    # Collision-proof placeholders
    assert "@@CM_CODE_BLOCK_" in js
    assert "@@CM_INLINE_CODE_" in js
    # Conditional auto-scroll check
    assert "wasNearBottom" in js
    # Scroll reset on conversation switch
    assert "messagesContainer.scrollTop = 0" in js

