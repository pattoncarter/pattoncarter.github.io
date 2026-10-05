def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_unavailable_when_content_dir_missing(client, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app(content_dir=tmp_path / "does-not-exist", static_dir=None)
    resp = TestClient(app).get("/api/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}
