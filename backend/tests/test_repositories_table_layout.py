import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from backend.app.models.repository import Repository
from backend.app.models.user import User

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def test_repositories_table_semantic_columns_and_markup(client: TestClient):
    """
    Verify repositories.html, repositories_modal.html, and api.js define
    all 5 independent semantic table column wrappers:
    1. Repository (col-repo)
    2. Technology Stack (col-tech)
    3. Status (col-status)
    4. Files & Symbols (col-stats)
    5. Actions (col-actions)
    """
    for page in ["/repositories", "/repositories_modal"]:
        res = client.get(page)
        assert res.status_code == 200
        html = res.text
        assert 'class="col-repo"' in html
        assert 'class="col-tech"' in html
        assert 'class="col-status"' in html
        assert 'class="col-stats"' in html
        assert 'class="col-actions"' in html

    api_js_path = BASE_DIR / "frontend" / "static" / "js" / "api.js"
    js_content = api_js_path.read_text(encoding="utf-8")
    assert '<div class="col-repo">' in js_content
    assert '<div class="col-tech">' in js_content
    assert '<div class="col-status">' in js_content
    assert '<div class="col-stats repo-stats-col">' in js_content
    assert '<div class="col-actions repo-actions-cell">' in js_content


def test_repositories_table_css_grid_and_overlap_guards():
    """
    Verify styles.css enforces:
    - CSS grid columns with dedicated width allocation for all 5 columns
    - Minimum width constraint on table-row/table-head preventing column collapse
    - Flex-wrap on action buttons container preventing leftward intrusion into stats
    - Table-card horizontal scroll container with touch scrolling
    - Clean files and symbols separation
    """
    css_path = BASE_DIR / "frontend" / "static" / "css" / "styles.css"
    css = css_path.read_text(encoding="utf-8")

    # Column grid definition
    assert "grid-template-columns:" in css
    assert "minmax(210px" in css or "minmax(200px" in css
    assert "minmax(290px" in css or "minmax(280px" in css
    assert "minmax(150px" in css or "minmax(140px" in css
    assert "minmax(330px" in css or "minmax(320px" in css

    # Minimum width and overflow containment
    assert "min-width: 1140px" in css
    assert ".table-card {" in css
    assert "overflow-x: auto" in css

    # Actions wrapping guard preventing intrusion into Files & Symbols
    assert ".repo-actions-cell {" in css
    assert "flex-wrap: wrap" in css

    # Stats styling
    assert ".repo-stats-col" in css
    assert ".repo-stat-item" in css
    assert ".repo-stat-num" in css
    assert ".repo-stat-dot" in css


def test_all_five_actions_preserved_and_functional():
    """
    Verify that all 5 repository actions remain functional with exact attributes:
    - Index (triggerRepoIndex)
    - Overview (/dashboard?repo= link)
    - Browse (/git_history?repo= link)
    - Explore (/code_viewer?repo= link)
    - Disconnect (deleteRepo with danger styling)
    """
    api_js_path = BASE_DIR / "frontend" / "static" / "js" / "api.js"
    js_content = api_js_path.read_text(encoding="utf-8")

    assert 'onclick="triggerRepoIndex(' in js_content
    assert 'title="Index or re-index">Index</button>' in js_content
    assert 'href="/dashboard?repo=' in js_content
    assert 'title="View Dashboard Overview">Overview</a>' in js_content
    assert 'href="/git_history?repo=' in js_content
    assert 'title="Browse commits">Browse</a>' in js_content
    assert 'href="/code_viewer?repo=' in js_content
    assert 'title="Explore code">Explore</a>' in js_content
    assert 'onclick="deleteRepo(' in js_content
    assert 'btn-danger-action' in js_content
    assert 'title="Disconnect repository">Disconnect</button>' in js_content


def test_files_and_symbols_formatting_and_contract(client: TestClient, db_session: Session):
    """
    Verify that actual repository files_count and symbols_count from the backend
    are formatted together legibly in the Files & Symbols column without hardcoding.
    """
    repo = Repository(
        name="metrics-repo",
        full_name="acme/metrics-repo",
        primary_language="Python",
        status="ready",
        files_count=1240,
        symbols_count=4850,
        tech_stack={
            "frontend": [{"name": "React", "category": "frontend"}],
            "backend": [{"name": "FastAPI", "category": "backend"}],
            "database": [],
            "infrastructure": []
        }
    )
    db_session.add(repo)
    db_session.commit()

    res = client.get("/api/v1/repositories")
    assert res.status_code == 200
    matched = next(r for r in res.json() if r["name"] == "metrics-repo")
    assert matched["files_count"] == 1240
    assert matched["symbols_count"] == 4850

    api_js_path = BASE_DIR / "frontend" / "static" / "js" / "api.js"
    js = api_js_path.read_text(encoding="utf-8")
    assert "formatNumber(repo.files_count || 0)" in js
    assert "formatNumber(repo.symbols_count || 0)" in js
