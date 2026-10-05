import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    """App with a temp content dir (seeded with about.json for the health check)
    and NO static dir (no frontend build in tests)."""
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "about.json").write_text("{}")
    app = create_app(content_dir=content_dir, static_dir=None)
    return TestClient(app)
