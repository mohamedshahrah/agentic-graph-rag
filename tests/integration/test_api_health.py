"""The /health endpoint should respond without any backing services.

We deliberately do NOT enter the TestClient context manager, so the app's
lifespan (which touches Neo4j) never runs — this stays a fast unit-style check.
"""

from fastapi.testclient import TestClient

from graphrag.api.app import create_app


def test_health_ok():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
