# RAT — Repository Analysis Tool

COMS3011A test deliverable: a web dashboard that ingests git repositories
(zip upload or remote clone URL) and computes file, directory, repository,
commit-set, and author metrics, with commit filtering, author merging, and
multi-repository support.

## Stack

- **Backend:** Python 3.12 + Flask 3 (JSON API). All git operations run through
  the `git` CLI so metric semantics (line counts, rename detection at 50%,
  binary detection, `.mailmap`) match git exactly.
- **Frontend:** React 18 SPA built with Vite (ECharts for visualisation).

## Quick start

### Backend

```bash
pip install -r requirements.txt
python run.py                 # http://127.0.0.1:5000
```

### Frontend (development)

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173, proxies /api to :5000
```

### Frontend (production build, served by Flask)

```bash
cd frontend
npm install
npm run build                 # outputs frontend/dist, served by python run.py
```

## Development

```bash
pip install -r requirements-dev.txt
pytest                        # runs the test suite in tests/
```

## Project status

Stage 1 of 10 (foundation and skeleton) — see the build plan for the staged
roadmap: ingestion, metric engine, query layer, filtering, author merging,
multi-repo support, visualisation, performance, and hardening.

## Project layout

```
app/                  Flask application (factory, routes, services)
app/services/         ingestion, analysis, queries, authors, jobs (later stages)
frontend/             React SPA (Vite)
tests/                pytest suite, incl. deterministic fixture repos
instance/             runtime data: cloned repos, uploads, SQLite cache (git-ignored)
```
