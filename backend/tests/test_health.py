from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.db import get_db
from app.main import app

client = TestClient(app)


def test_health_success():
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "claimgraph-api"
        assert data["version"] == "0.1.0"
        assert data["db"] == "ok"
        assert "time" in data
        mock_db.execute.assert_called_once()
    finally:
        app.dependency_overrides.clear()


def test_health_db_failure_returns_degraded():
    mock_db = MagicMock()
    mock_db.execute.side_effect = OperationalError("connection refused", {}, None)
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["service"] == "claimgraph-api"
        assert data["version"] == "0.1.0"
        assert data["db"] == "error"
        assert "time" in data
    finally:
        app.dependency_overrides.clear()
