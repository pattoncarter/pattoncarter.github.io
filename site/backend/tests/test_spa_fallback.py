import json

from fastapi.testclient import TestClient

from app.main import create_app


def _app_with_static(tmp_path):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html><!-- SPA --></html>")
    (static_dir / "assets").mkdir()
    (static_dir / "assets" / "main.js").write_text("console.log(1)")
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "about.json").write_text("{}")
    return create_app(content_dir=content_dir, static_dir=static_dir)


def _app_with_escape_targets(tmp_path):
    """SPA shell plus secrets outside the static dir that must never be served."""
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html><!-- SPA --></html>")
    (tmp_path / "outside.txt").write_text("SECRET outside")
    sibling = tmp_path / "static2"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("SECRET sibling")
    (static_dir / "link.txt").symlink_to(tmp_path / "outside.txt")
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "about.json").write_text("{}")
    return create_app(content_dir=content_dir, static_dir=static_dir)


def test_deep_link_serves_spa_shell(tmp_path):
    resp = TestClient(_app_with_static(tmp_path)).get("/about")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_unknown_api_path_is_json_404(tmp_path):
    resp = TestClient(_app_with_static(tmp_path)).get("/api/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_bare_api_path_is_json_404(tmp_path):
    # "/api" (no trailing slash) must not fall through to the SPA shell.
    resp = TestClient(_app_with_static(tmp_path)).get("/api")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_static_file_served(tmp_path):
    resp = TestClient(_app_with_static(tmp_path)).get("/assets/main.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_api_routes_take_precedence_over_spa_catch_all(tmp_path):
    # Regression: a misplaced catch-all/mount would shadow API routes only
    # when static_dir is present — this test pins the production config.
    app = _app_with_static(tmp_path)
    content_dir = tmp_path / "content"
    (content_dir / "about.json").write_text(json.dumps({
        "tagline": "t", "hero": "h", "mission": "m", "interests": "i",
        "quote": "q", "competencies": [], "education": [],
        "resume_url": "https://r", "socials": {},
    }))
    resp = TestClient(app).get("/api/about")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "SPA" not in resp.text


def test_missing_index_html_returns_json_404(tmp_path):
    # Empty static dir (Docker auto-creates missing bind-mount paths) must not
    # 500 on every navigation.
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "about.json").write_text("{}")
    app = create_app(content_dir=content_dir, static_dir=static_dir)
    resp = TestClient(app).get("/about")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_raw_traversal_does_not_leak(tmp_path):
    resp = TestClient(_app_with_escape_targets(tmp_path)).get("/../../outside.txt")
    assert "SECRET" not in resp.text


def test_encoded_traversal_does_not_leak(tmp_path):
    resp = TestClient(_app_with_escape_targets(tmp_path)).get("/..%2F..%2Foutside.txt")
    assert "SECRET" not in resp.text


def test_prefix_sibling_escape_does_not_leak(tmp_path):
    resp = TestClient(_app_with_escape_targets(tmp_path)).get("/../static2/secret.txt")
    assert "SECRET" not in resp.text


def test_symlink_escape_does_not_leak(tmp_path):
    resp = TestClient(_app_with_escape_targets(tmp_path)).get("/link.txt")
    assert "SECRET" not in resp.text
