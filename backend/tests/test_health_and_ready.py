from unittest.mock import patch
from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient):
    """Verify GET /health returns 200 with application liveness details."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "CodeMind AI"
    assert "version" in data
    assert "environment" in data


def test_ready_endpoint_connected(client: TestClient):
    """Verify GET /ready returns 200 when database connectivity is established."""
    with patch("backend.app.api.routes.health.check_db_connection", return_value=(True, "postgresql", "Connected to postgres")):
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["database"] == "connected"
        assert data["dialect"] == "postgresql"


def test_ready_endpoint_disconnected(client: TestClient):
    """Verify GET /ready returns 503 when database connectivity fails."""
    with patch("backend.app.api.routes.health.check_db_connection", return_value=(False, "postgresql", "Connection refused")):
        response = client.get("/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["database"] == "disconnected"
        assert "Connection refused" in data["detail"]
