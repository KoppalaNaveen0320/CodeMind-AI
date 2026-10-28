import pytest
from fastapi.testclient import TestClient


CLEAN_PAGES = [
    "/landing",
    "/login",
    "/signup",
    "/dashboard",
    "/repositories",
    "/repositories_modal",
    "/repositories-modal",
    "/assistant",
    "/assistant_empty",
    "/assistant-empty",
    "/code_viewer",
    "/code-viewer",
    "/code",
    "/dependencies",
    "/impact_analysis",
    "/impact-analysis",
    "/impact",
    "/git_history",
    "/git-history",
    "/history",
    "/security_insights",
    "/security-insights",
    "/security",
    "/docs",
    "/documentation",
    "/settings",
    "/index",
    "/suite",
]

LEGACY_REDIRECT_MAPPINGS = [
    ("/landing.html", "/landing"),
    ("/login.html", "/login"),
    ("/signup.html", "/signup"),
    ("/dashboard.html", "/dashboard"),
    ("/repositories.html", "/repositories"),
    ("/repositories_modal.html", "/repositories_modal"),
    ("/assistant.html", "/assistant"),
    ("/assistant_empty.html", "/assistant_empty"),
    ("/code_viewer.html", "/code_viewer"),
    ("/dependencies.html", "/dependencies"),
    ("/impact_analysis.html", "/impact_analysis"),
    ("/git_history.html", "/git_history"),
    ("/security_insights.html", "/security_insights"),
    ("/docs.html", "/documentation"),
    ("/settings.html", "/settings"),
    ("/index.html", "/index"),
]


@pytest.mark.parametrize("route", CLEAN_PAGES)
def test_clean_page_routes_return_200(client: TestClient, route: str):
    """Verify all clean URLs return HTTP 200 and render HTML directly without redirecting."""
    resp = client.get(route, follow_redirects=False)
    assert resp.status_code == 200, f"Route {route} returned {resp.status_code}"
    assert "text/html" in resp.headers.get("content-type", "")
    assert "<!doctype html>" in resp.text.lower()


def test_root_route_serves_dashboard(client: TestClient):
    """Verify root / serves the dashboard directly with 200."""
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert "CodeMind" in resp.text


@pytest.mark.parametrize("legacy_url, clean_target", LEGACY_REDIRECT_MAPPINGS)
def test_legacy_html_urls_redirect_to_clean_urls(client: TestClient, legacy_url: str, clean_target: str):
    """Verify legacy .html URLs redirect via HTTP 302 to clean URLs."""
    resp = client.get(legacy_url, follow_redirects=False)
    assert resp.status_code == 302, f"Legacy URL {legacy_url} returned {resp.status_code}"
    location = resp.headers.get("location", "")
    assert location == clean_target, f"Expected redirect to {clean_target}, got {location}"


@pytest.mark.parametrize("legacy_url, clean_target", LEGACY_REDIRECT_MAPPINGS)
def test_query_parameters_survive_redirects(client: TestClient, legacy_url: str, clean_target: str):
    """Verify query parameters are faithfully preserved during legacy .html redirects."""
    query = "repo=42&file=src%2Fmain.py&start=15&end=45&branch=feature%2Ftest"
    url_with_query = f"{legacy_url}?{query}"
    resp = client.get(url_with_query, follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("location", "")
    assert location == f"{clean_target}?{query}"

    # Also verify following redirect reaches 200
    followed_resp = client.get(url_with_query, follow_redirects=True)
    assert followed_resp.status_code == 200
    assert "text/html" in followed_resp.headers.get("content-type", "")


def test_internal_navigation_in_templates_has_no_html_links(client: TestClient):
    """Verify rendered templates contain no user-facing .html navigation hrefs."""
    pages_to_check = [
        "/dashboard",
        "/repositories",
        "/assistant",
        "/dependencies",
        "/impact_analysis",
        "/git_history",
        "/security_insights",
        "/settings",
        "/docs",
        "/code_viewer",
        "/landing",
        "/login",
        "/signup",
    ]
    for page in pages_to_check:
        resp = client.get(page)
        assert resp.status_code == 200
        html = resp.text
        # Ensure no href contains .html
        assert 'href="dashboard.html"' not in html
        assert 'href="repositories.html"' not in html
        assert 'href="assistant.html"' not in html
        assert 'href="dependencies.html"' not in html
        assert 'href="impact_analysis.html"' not in html
        assert 'href="git_history.html"' not in html
        assert 'href="security_insights.html"' not in html
        assert 'href="settings.html"' not in html
        assert 'href="docs.html"' not in html
        assert 'href="code_viewer.html"' not in html
        assert 'href="/login.html"' not in html
        assert 'href="/signup.html"' not in html


def test_static_assets_unaffected_by_clean_routing(client: TestClient):
    """Verify static CSS, JS, and SVG assets are properly served without interference."""
    for asset in ["/static/css/styles.css", "/static/js/api.js", "/static/assets/favicon.svg"]:
        resp = client.get(asset)
        assert resp.status_code == 200


def test_api_routes_unaffected_by_clean_routing(client: TestClient):
    """Verify API endpoints like /health and /api/v1/auth/me remain unaffected."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # API docs check
    resp = client.get("/api/docs")
    assert resp.status_code == 200


def test_authenticated_pages_have_strict_no_cache_headers(client: TestClient):
    """Verify clean authenticated pages have strict no-cache headers."""
    clean_authenticated = [
        "/dashboard",
        "/repositories",
        "/assistant",
        "/dependencies",
        "/impact_analysis",
        "/git_history",
        "/security_insights",
        "/documentation",
        "/settings",
        "/code_viewer",
    ]
    for page in clean_authenticated:
        resp = client.get(page)
        assert resp.status_code == 200
        cache_control = resp.headers.get("cache-control", "").lower()
        assert "no-store" in cache_control
        assert "no-cache" in cache_control
        assert "must-revalidate" in cache_control


def test_nonexistent_routes_return_404(client: TestClient):
    """Verify nonexistent routes properly return 404."""
    resp = client.get("/nonexistent_page_xyz", follow_redirects=False)
    assert resp.status_code == 404
