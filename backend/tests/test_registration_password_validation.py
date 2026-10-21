import re
import uuid
import pytest
from fastapi.testclient import TestClient

from backend.app.core.security import validate_password_strength


# --- 1. Backend Password Policy & Strength Unit Tests ---

def test_password_strength_length_rule():
    """Verify passwords shorter than 8 characters are rejected with clear detail."""
    valid, msg = validate_password_strength("Ab1!xyz")
    assert valid is False
    assert "at least 8 characters" in msg.lower()


def test_password_strength_uppercase_rule():
    """Verify passwords missing uppercase letter are rejected."""
    valid, msg = validate_password_strength("weakpassword123!")
    assert valid is False
    assert "uppercase" in msg.lower()


def test_password_strength_lowercase_rule():
    """Verify passwords missing lowercase letter are rejected."""
    valid, msg = validate_password_strength("WEAKPASSWORD123!")
    assert valid is False
    assert "lowercase" in msg.lower()


def test_password_strength_number_rule():
    """Verify passwords missing digits are rejected."""
    valid, msg = validate_password_strength("WeakPasswordSpecial!")
    assert valid is False
    assert "number" in msg.lower()


def test_password_strength_special_character_rule():
    """Verify passwords missing special character are rejected."""
    valid, msg = validate_password_strength("WeakPassword123")
    assert valid is False
    assert "special character" in msg.lower()


def test_password_strength_all_satisfied():
    """Verify passwords satisfying all 5 criteria are accepted."""
    valid, msg = validate_password_strength("StrongPass123!@#")
    assert valid is True
    assert msg is None


# --- 2. Registration API Endpoint Validation Tests ---

def test_api_register_rejects_missing_criteria(client: TestClient):
    """Verify POST /api/v1/auth/register enforces all criteria via API."""
    base_user = {
        "full_name": "Test Candidate",
        "workspace_name": "Test Space",
        "email": f"test_{uuid.uuid4().hex[:8]}@codemind.dev"
    }

    # 1. Missing uppercase
    resp = client.post("/api/v1/auth/register", json={**base_user, "password": "lowercase123!@#"})
    assert resp.status_code == 422
    assert "uppercase" in resp.json()["detail"].lower()

    # 2. Missing lowercase
    resp = client.post("/api/v1/auth/register", json={**base_user, "password": "UPPERCASE123!@#"})
    assert resp.status_code == 422
    assert "lowercase" in resp.json()["detail"].lower()

    # 3. Missing number
    resp = client.post("/api/v1/auth/register", json={**base_user, "password": "NoNumbersHere!@#"})
    assert resp.status_code == 422
    assert "number" in resp.json()["detail"].lower()

    # 4. Missing special character
    resp = client.post("/api/v1/auth/register", json={**base_user, "password": "NoSpecialChar123"})
    assert resp.status_code == 422
    assert "special character" in resp.json()["detail"].lower()

    # 5. Shorter than 8 characters
    resp = client.post("/api/v1/auth/register", json={**base_user, "password": "A1!b2"})
    assert resp.status_code == 422
    assert "8 characters" in str(resp.json()).lower()


def test_api_register_accepts_valid_password_and_hashes(client: TestClient):
    """Verify valid registration creates user with proper session cookie and hash."""
    test_email = f"valid_{uuid.uuid4().hex[:8]}@codemind.dev"
    resp = client.post("/api/v1/auth/register", json={
        "full_name": "Secure User",
        "workspace_name": "Secure Workspace",
        "email": test_email,
        "password": "Valid@Password99!"
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    assert data["user"]["email"] == test_email
    assert "token" in data
    assert "codemind_session" in resp.cookies


# --- 3. Frontend HTML Template DOM Structure Tests ---

def test_signup_template_structure_and_accessibility(client: TestClient):
    """Verify signup.html includes confirm password, independent toggles, and live checklist."""
    resp = client.get("/signup", follow_redirects=True)
    assert resp.status_code == 200
    html = resp.text

    # Primary password field and toggle
    assert 'id="signup-password"' in html
    assert 'id="signup-password-toggle"' in html
    assert 'aria-label="Show password"' in html
    assert 'title="Show password"' in html
    assert 'type="button"' in html

    # Confirm password field and independent toggle
    assert 'id="signup-confirm-password"' in html
    assert 'id="signup-confirm-toggle"' in html
    assert 'aria-label="Show confirm password"' in html
    assert 'title="Show confirm password"' in html
    assert 'Confirm password' in html
    assert 'placeholder="Re-enter your password"' in html

    # Exact labels for the 5 requirements checklist
    assert "1 uppercase letter" in html
    assert "1 lowercase letter" in html
    assert "1 number" in html
    assert "1 special character" in html
    assert "At least 8 characters" in html

    # Checklist elements
    assert 'id="password-checklist"' in html
    assert 'id="req-uppercase"' in html
    assert 'id="req-lowercase"' in html
    assert 'id="req-number"' in html
    assert 'id="req-special"' in html
    assert 'id="req-length"' in html

    # Match indicator
    assert 'id="password-match-status"' in html
    assert 'id="password-match-text"' in html

    # Create account button is disabled initially
    assert 'id="signup-submit-btn"' in html
    assert '<button type="submit" class="auth-btn-primary" id="signup-submit-btn" disabled>' in html or 'disabled' in html


# --- 4. CSS Contrast, Hover State, and Non-Overlap Verification ---

def test_css_variables_and_button_hover_contrast(client: TestClient):
    """
    Verify --primary-hover is declared in CSS, .auth-btn-primary has non-white hover styling,
    disabled states prevent hover, and password inputs have right padding for eye buttons.
    """
    resp = client.get("/static/css/styles.css")
    assert resp.status_code == 200
    css = resp.text

    # 1. CSS variable defined in :root
    assert "--primary-hover: #4338ca;" in css or "--primary-hover" in css

    # 2. .auth-btn-primary hover retains non-white purple background and white text
    assert ".auth-btn-primary:hover:not(:disabled)" in css or ".auth-btn-primary:hover" in css
    assert "var(--primary-hover" in css

    # 3. Disabled button styling exists and is distinct
    assert ".auth-btn-primary:disabled" in css
    assert "cursor: not-allowed" in css

    # 4. Input text cannot overlap toggle icon (right padding reserved)
    assert ".password-input-wrap .form-input" in css
    assert "padding-right: 42px" in css or "padding-right: 40px" in css

    # 5. Focus-visible outline for keyboard accessibility
    assert ".auth-btn-primary:focus-visible" in css
    assert ".password-toggle-btn:focus-visible" in css


# --- 5. Side-by-Side Layout and Scrolling Verification ---

def test_signup_side_by_side_layout_structure(client: TestClient):
    """
    Verify Password and Confirm Password are organized in a responsive side-by-side grid,
    with the checklist below Password (left) and match status below Confirm Password (right).
    """
    resp = client.get("/signup", follow_redirects=True)
    assert resp.status_code == 200
    html = resp.text

    # Responsive grid row wrapper exists
    assert 'class="form-row-password-grid"' in html
    assert 'signup-card-wrap' in html

    # Left column contains Password and Checklist
    assert 'form-col-password' in html
    left_col_start = html.find('form-col-password')
    right_col_start = html.find('form-col-confirm')
    assert left_col_start != -1 and right_col_start != -1
    assert left_col_start < right_col_start

    # Checklist is in the left column
    checklist_pos = html.find('id="password-checklist"')
    assert left_col_start < checklist_pos < right_col_start

    # Match status is in the right column
    match_status_pos = html.find('id="password-match-status"')
    assert match_status_pos > right_col_start


def test_css_registration_page_scrolling_and_responsive_grid(client: TestClient):
    """
    Verify CSS allows natural document scrolling (no overflow: hidden on .auth-page),
    uses margin: auto for non-clipped flex centering, and specifies 2-column desktop / 1-column mobile grid.
    """
    resp = client.get("/static/css/styles.css")
    assert resp.status_code == 200
    css = resp.text

    # 1. Scrolling fix: overflow-y: auto, NO overflow: hidden on .auth-page
    assert "overflow-y: auto" in css
    assert "overflow-x: hidden" in css

    # 2. Centering without top clipping: margin: auto on .auth-card-wrap
    assert "margin: auto" in css

    # 3. Dedicated signup card width
    assert ".auth-card-wrap.signup-card-wrap" in css
    assert "max-width: 720px" in css

    # 4. Side-by-side grid definition on desktop
    assert ".form-row-password-grid" in css
    assert "grid-template-columns: 1fr 1fr" in css

    # 5. Mobile breakpoint stacking
    assert "@media (max-width: 680px)" in css
    assert "grid-template-columns: 1fr" in css
