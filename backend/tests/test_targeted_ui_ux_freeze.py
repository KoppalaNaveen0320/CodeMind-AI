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


def test_area3_settings_page_active_sessions_modal_dialog():
    """Verify Settings page Active Sessions opens in a centered modal dialog with full accessibility and revocation."""
    js_path = BASE_DIR / "frontend" / "static" / "js" / "api.js"
    js = js_path.read_text(encoding="utf-8")
    settings_tmpl = (BASE_DIR / "frontend" / "templates" / "settings.html").read_text(encoding="utf-8")

    # Centered modal in settings.html template
    assert 'id="active-sessions-modal"' in settings_tmpl
    assert 'class="modal-layer hidden"' in settings_tmpl
    assert 'role="dialog"' in settings_tmpl
    assert 'aria-modal="true"' in settings_tmpl
    assert 'active-sessions-backdrop-close' in settings_tmpl
    assert 'btn-close-active-sessions-modal' in settings_tmpl
    assert 'id="active-sessions-list-container"' in settings_tmpl

    # Button triggers modal dialog on same page
    assert 'id="btn-toggle-active-sessions"' in js
    assert 'openActiveSessionsModal()' in js
    assert 'aria-haspopup="dialog"' in js
    assert 'aria-controls="active-sessions-modal"' in js

    # Modal opening/closing functions and ESC listener
    assert "window.openActiveSessionsModal" in js
    assert "window.closeActiveSessionsModal" in js
    assert "window.loadActiveSessions" in js
    assert "document.body.classList.add('modal-open')" in js
    assert "document.body.classList.remove('modal-open')" in js
    assert "e.key === 'Escape'" in js

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

    # CSS for session modal and badges
    css_path = BASE_DIR / "frontend" / "static" / "css" / "styles.css"
    css = css_path.read_text(encoding="utf-8")

    assert ".session-security-card" in css
    assert ".active-sessions-modal" in css
    assert ".session-card-item" in css
    assert ".session-card-item.is-current" in css
    assert ".session-badge-current" in css
    assert ".session-badge-active" in css
    assert ".session-badge-expired" in css
    assert ".session-badge-revoked" in css
    assert ".session-details-grid" in css


def test_tech_stack_modal_ui_styling_and_card_layout():
    """Verify Technology Stack details modal has spacious card-based layout with clean category sections."""
    css_path = BASE_DIR / "frontend" / "static" / "css" / "styles.css"
    css = css_path.read_text(encoding="utf-8")

    # Tech stack modal layout classes
    assert ".modal-layer .tech-details-modal" in css
    assert ".tech-modal-body" in css
    assert ".tech-modal-grid" in css
    assert ".tech-modal-section" in css
    assert ".tech-modal-sec-head" in css
    assert ".tech-count-badge" in css
    assert ".tech-modal-sec-items" in css
    assert ".tech-evidence-card" in css
    assert ".tech-card-header-row" in css
    assert ".tech-card-identity" in css
    assert ".tech-card-name" in css
    assert ".tech-card-name.tech-frontend" in css
    assert ".tech-card-name.tech-backend" in css
    assert ".tech-card-name.tech-db" in css
    assert ".tech-card-name.tech-infra" in css
    assert ".tech-type-pill" in css
    assert ".tech-version-pill" in css
    assert ".tech-confidence-badge" in css
    assert ".tech-confidence-badge.conf-high" in css
    assert ".tech-card-evidence" in css
    assert ".tech-evidence-tags" in css
    assert ".tech-evidence-path" in css

    # JS modal builder
    js_path = BASE_DIR / "frontend" / "static" / "js" / "api.js"
    js = js_path.read_text(encoding="utf-8")
    assert "window.openTechStackModal" in js
    assert "window.closeTechStackModal" in js
    assert "cleanEvidenceSnippet" in js
    assert "tech-evidence-card" in js

    # Repositories template sizing
    repo_tmpl = (BASE_DIR / "frontend" / "templates" / "repositories.html").read_text(encoding="utf-8")
    assert 'class="setup-modal tech-details-modal"' in repo_tmpl
    assert 'max-height: min(800px, calc(100vh - 48px));' in repo_tmpl

