import io
import zipfile
import pytest
from fastapi.testclient import TestClient


def test_repository_modal_html_structure(client: TestClient):
    """Verify both repositories.html and repositories_modal.html contain accessible modal markup."""
    for page in ["/repositories", "/repositories_modal", "/repositories.html", "/repositories_modal.html"]:
        res = client.get(page, follow_redirects=True)
        assert res.status_code == 200
        html = res.text
        assert 'id="connect-github-modal"' in html
        assert 'role="dialog"' in html
        assert 'aria-modal="true"' in html
        assert 'aria-labelledby="modal-step-title"' in html
        assert 'id="modal-backdrop-close"' in html
        assert 'class="setup-modal"' in html
        assert 'id="modal-step-title"' in html
        assert 'id="modal-close-x-btn"' in html
        assert 'id="modal-steps-indicator"' in html
        assert 'id="modal-body-content"' in html


def test_modal_css_stacking_and_blur_isolation(client: TestClient):
    """Verify styles.css ensures modal backdrop is stacked behind the modal dialog,
    so backdrop blur never blurs the modal dialog and clicks hit the dialog directly."""
    res = client.get("/static/css/styles.css")
    assert res.status_code == 200
    css = res.text

    # Modal container layer has high z-index
    assert ".modal-layer {" in css or ".modal-layer" in css
    assert "z-index: 1000" in css

    # Scoped modal backdrop inside modal-layer has low z-index (1) so it sits behind the modal
    assert ".modal-layer .modal-backdrop" in css
    assert "z-index: 1;" in css

    # Setup modal dialog has higher z-index (10) so it sits in front of the backdrop
    assert ".modal-layer .setup-modal" in css
    assert "z-index: 10;" in css

    # Setup modal has clean white background and rounded card shadow
    assert "background: #ffffff" in css

    # Internal scrolling for modal body on small viewports
    assert ".setup-body" in css
    assert "overflow-y: auto" in css

    # Background-page scroll locking class
    assert "body.modal-open" in css
    assert "overflow: hidden" in css

    # Crisp form controls and focus states
    assert ".setup-modal input[type=\"text\"]" in css
    assert ".setup-modal input[type=\"file\"]" in css
    assert "border-color: var(--primary)" in css


def test_modal_js_click_propagation_and_accessibility(client: TestClient):
    """Verify api.js contains click propagation stops, backdrop target checks,
    accessible labels, and file picker display updates."""
    res = client.get("/static/js/api.js")
    assert res.status_code == 200
    js = res.text

    # Prevent click propagation inside the modal dialog
    assert "setupModal.addEventListener('click'" in js
    assert "e.stopPropagation()" in js

    # Backdrop check ensures modal closes only when backdrop itself is targeted
    assert "e.target === backdrop" in js

    # Duplicate listener prevention on reopening
    assert "modal.dataset.initialized" in js

    # Body scroll lock and unlock
    assert "document.body.classList.add('modal-open')" in js
    assert "document.body.classList.remove('modal-open')" in js

    # Accessible labels for repository input and ZIP upload
    assert 'for="input-direct-repo"' in js
    assert 'for="input-folder-zip"' in js

    # ZIP selected filename and size display
    assert "folder-zip-selected-info" in js
    assert "folderFileInput.addEventListener('change'" in js

    # Auto-fill project name from ZIP filename
    assert "nameInput.value = file.name.replace" in js or "folderNameInput.value = file.name.replace" in js


def test_public_repo_connection_api_validation(client: TestClient):
    """Verify the real /api/v1/repositories/connect-public endpoint validates input and rejects malformed names."""
    # Empty payload
    res = client.post("/api/v1/repositories/connect-public", json={})
    assert res.status_code in (400, 422)

    # Missing slash or invalid repository string
    res = client.post("/api/v1/repositories/connect-public", json={"repository": "invalid-no-slash"})
    assert res.status_code in (400, 422)
    assert "detail" in res.json()


def test_zip_upload_api_validation(client: TestClient):
    """Verify the real /api/v1/repositories/upload-folder endpoint validates file archives and rejects invalid formats."""
    # Attempt upload of non-zip file
    fake_txt = io.BytesIO(b"Hello CodeMind AI")
    res = client.post(
        "/api/v1/repositories/upload-folder",
        files={"file": ("test.txt", fake_txt, "text/plain")}
    )
    assert res.status_code in (400, 422)
    err = res.json()
    assert "zip" in str(err).lower()

    # Create a valid minimal ZIP archive
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("app/main.py", "def hello():\n    return 'world'\n")
        zf.writestr("README.md", "# Test Project\n")
    zip_buffer.seek(0)

    # Upload valid zip archive with project name
    res = client.post(
        "/api/v1/repositories/upload-folder",
        files={"file": ("modal_test_project.zip", zip_buffer, "application/zip")},
        data={"name": "modal_test_project", "auto_index": "false"}
    )
    assert res.status_code in (200, 201)
    data = res.json()
    assert "id" in data
    assert data["name"] == "modal_test_project"
    repo_id = data["id"]

    # Verify repository status endpoint works
    status_res = client.get(f"/api/v1/repositories/{repo_id}/indexing-status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert "status" in status_data
