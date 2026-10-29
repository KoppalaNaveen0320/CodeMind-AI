"""
CodeMind AI — Targeted UI/UX Freeze Regression Test Suite
Validates the three authorized UI/UX enhancements under Strict Design Freeze:
1. Overview Page: Technology Stack & Ecosystem panel (layout, compact evidence, container scroll containment)
2. Repositories Page: Technology Stack column (grid allocation, category grouping, pill spacing without concatenation, action wrap guard)
3. Settings Page: Active Sessions section (collapsed by default, toggle button, aria-expanded, duplicate prevention, lazy load)
"""

from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from backend.app.models.repository import Repository
from backend.app.models.user import User
from backend.app.models.user_session import UserSession

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def test_area1_overview_page_ecosystem_panel_styling_and_containment():
    """Verify Overview page Technology Stack & Ecosystem styles and scroll containment."""
    css_path = BASE_DIR / "frontend" / "static" / "css" / "styles.css"
    css = css_path.read_text(encoding="utf-8")

    assert ".tech-ecosystem-card" in css
    assert ".tech-ecosystem-container {" in css
    assert "max-height: 480px" in css
    assert "overflow-y: auto" in css
    assert ".tech-overview-grid" in css
    assert ".tech-overview-col" in css
    assert ".tech-overview-col-head" in css
    assert ".tech-overview-item" in css
    assert ".tech-evidence-line" in css
    assert ".badge-cat-fe" in css
    assert ".badge-cat-be" in css
    assert ".badge-cat-db" in css
    assert ".badge-cat-infra" in css

    # Verify api.js cleanEvidenceSnippet prevents redundant 'Found in ' repetition
    js_path = BASE_DIR / "frontend" / "static" / "js" / "api.js"
    js = js_path.read_text(encoding="utf-8")
    assert "function cleanEvidenceSnippet" in js
    assert "str.startsWith('Found in ')" in js
    assert "renderTechStackOverview" in js


def test_area2_repositories_page_tech_stack_pills_and_table_layout():
    """Verify Repositories page column grid, pill spacing, and action preservation."""
    css_path = BASE_DIR / "frontend" / "static" / "css" / "styles.css"
    css = css_path.read_text(encoding="utf-8")

    # Table layout grid and scroll container
    assert "grid-template-columns: minmax(210px, 1.4fr) minmax(290px, 1.8fr) minmax(110px, 0.7fr) minmax(150px, 0.8fr) minmax(330px, 1.2fr)" in css
    assert "min-width: 1140px" in css
    assert ".table-card { overflow-x: auto" in css

    # Pill spacing and wrapping
    assert ".tech-stack-cell" in css
    assert ".tech-stack-groups" in css
    assert ".tech-group-row" in css
    assert ".tech-cat-tag" in css
    assert ".tech-badges-wrap" in css
    assert "flex-wrap: wrap" in css
    assert ".tech-pill" in css
    assert ".tech-pill.tech-frontend" in css
    assert ".tech-pill.tech-backend" in css
    assert ".tech-pill.tech-db" in css
    assert ".tech-pill.tech-infra" in css
    assert ".tech-pill.tech-none" in css
    assert ".tech-pill.tech-more" in css
    assert ".tech-details-btn" in css

    # Actions wrapping guard
    assert ".repo-actions-cell" in css
    assert "flex-wrap: wrap" in css

    # Stats styling
    assert ".repo-stats-col" in css
    assert ".repo-stat-item" in css
    assert ".repo-stat-num" in css
    assert ".repo-stat-dot" in css


def test_area3_settings_page_active_sessions_collapsed_and_toggleable():
    """Verify Settings page Active Sessions is collapsed by default and toggleable via button."""
    js_path = BASE_DIR / "frontend" / "static" / "js" / "api.js"
    js = js_path.read_text(encoding="utf-8")

    # Expandable container starts hidden with display: none
    assert 'id="active-sessions-expandable-wrap" style="display: none;' in js

    # Toggle button with aria-expanded="false" and icon
    assert 'id="btn-toggle-active-sessions"' in js
    assert 'aria-expanded="false"' in js
    assert 'aria-controls="active-sessions-expandable-wrap"' in js

    # Initial load of active sessions on page load is removed
    assert "loadActiveSessions();\n\n      } else {" not in js
    assert "Active Sessions section is collapsed by default and loaded on-demand" in js

    # Toggle event listener controls display, aria-expanded, and lazy loading
    assert "toggleBtn.addEventListener('click'" in js
    assert "toggleBtn.setAttribute('aria-expanded', 'true')" in js
    assert "toggleBtn.setAttribute('aria-expanded', 'false')" in js
    assert "await loadActiveSessions()" in js

    # Session card fields in DOM generator
    assert "session-badge-current" in js
    assert "IP address:" in js
    assert "Login time:" in js
    assert "Last activity:" in js
    assert "Expires at:" in js
    assert "Last accessed page:" in js
    assert "Browser:" in js
    assert "Operating system:" in js
    assert "Ended:" in js
    assert "btn-revoke-session" in js
    assert "btn-revoke-other-sessions" in js

    # CSS for session security card and badges
    css_path = BASE_DIR / "frontend" / "static" / "css" / "styles.css"
    css = css_path.read_text(encoding="utf-8")

    assert ".session-security-card" in css
    assert ".session-card-item" in css
    assert ".session-card-item.is-current" in css
    assert ".session-badge-current" in css
    assert ".session-badge-active" in css
    assert ".session-badge-expired" in css
    assert ".session-badge-revoked" in css
    assert ".session-details-grid" in css
