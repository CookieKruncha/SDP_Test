"""Serve the built React SPA, with a friendly fallback before the first build.

Routing rules:
- Static assets under frontend/dist are served directly.
- Unknown non-API paths fall back to index.html so client-side routes work.
- /api/* is never captured here; unmatched API paths 404 as JSON.
"""

from pathlib import Path

from flask import abort, current_app, send_from_directory

_PLACEHOLDER = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>RAT — frontend not built</title>
<style>
  body { font-family: system-ui, -apple-system, sans-serif; background: #0e1116;
         color: #e6edf3; display: grid; place-items: center; height: 100vh; margin: 0; }
  main { max-width: 560px; padding: 24px; line-height: 1.6; }
  code { background: #1c232d; padding: 2px 6px; border-radius: 6px; }
  .muted { color: #8b949e; }
  a { color: #4f8cff; }
</style>
</head>
<body>
<main>
  <h1>RAT backend is running</h1>
  <p>The React frontend has not been built yet.</p>
  <p>Build it with <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>
     then reload this page, or use the Vite dev server:
     <code>cd frontend &amp;&amp; npm run dev</code> (then open
     <a href="http://localhost:5173">localhost:5173</a>).</p>
  <p class="muted">API health: <a href="/api/healthz">/api/healthz</a></p>
</main>
</body>
</html>
"""


def register_spa(app) -> None:
    @app.get("/")
    def spa_index():
        return _serve_spa_file("")

    @app.get("/<path:path>")
    def spa_files(path: str):
        if path == "api" or path.startswith("api/"):
            abort(404)
        return _serve_spa_file(path)


def _serve_spa_file(path: str):
    dist = Path(current_app.config["FRONTEND_DIST"])
    if not (dist / "index.html").is_file():
        return _PLACEHOLDER, 200

    if path:
        if (dist / path).is_file():
            return send_from_directory(str(dist), path)
        if Path(path).suffix:
            # A missing asset (e.g. /assets/old-hash.js) should 404, not
            # silently return the SPA shell.
            abort(404)
    return send_from_directory(str(dist), "index.html")
