"""Smoke tests for the app skeleton: health endpoint, error shape, SPA serving."""


def test_healthz(client):
    resp = client.get("/api/healthz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["service"] == "rat"
    assert isinstance(body["schema_version"], int)


def test_unknown_api_route_returns_json_error(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"]["code"] == "http_404"
    assert body["error"]["message"]


def test_api_root_also_returns_json_error(client):
    """The bare /api path must not fall through to the SPA shell."""
    resp = client.get("/api")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "http_404"


def test_root_serves_html(client):
    """Serves the built SPA when present, or the placeholder otherwise."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["Content-Type"]
