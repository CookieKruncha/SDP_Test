"""Development entrypoint for the RAT application.

Usage: python run.py  ->  http://127.0.0.1:5000

The Werkzeug auto-reloader is deliberately off: it watches the whole project
tree, including ``instance/`` where ingestion writes files, so ingesting a
repository would restart the server and kill the in-flight job thread
(daemon), leaving the job stuck in ``running``. Set ``RAT_DEBUG=1`` to enable
the interactive debugger; the reloader stays disabled either way.
"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=os.environ.get("RAT_DEBUG") == "1",
        use_reloader=False,
    )
