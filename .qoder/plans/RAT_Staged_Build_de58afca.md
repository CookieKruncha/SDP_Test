# RAT (Repo Analysis Tool) — Staged Implementation Plan

## Summary
Build the test deliverable: a multi-repository web dashboard — Flask JSON REST API + React SPA — that ingests repos (zip upload + remote deep clone) and computes file, directory, repository, commit-set, and author metrics per the brief's definitions, with commit filtering, author merging, and multi-repo support. Ten numbered stages; each stage ends with the app runnable, tests green, and all previously completed features intact.

## Stack & Decisions
- **Backend:** Python 3.12 + Flask 3.0 JSON REST API (preinstalled). All git operations via the git CLI through `subprocess` — streaming-friendly and git-exact semantics (numstat, `-M50%` renames, git binary detection, `.mailmap`).
- **Frontend:** React SPA built with Vite (Node 18 + npm 9 available), JavaScript/JSX (no TypeScript — velocity), react-router for navigation, ECharts for visualisation (built-in treemap / calendar heatmap / stacked series cover the "inspired visualisation" tier). No CDN — all assets bundled.
- **Build/run:** dev = Vite dev server (:5173) proxying `/api` to Flask (:5000); production = `npm run build`, Flask serves `frontend/dist` so graders need only `python run.py`. The production build is committed so grading works without npm; README documents the rebuild.
- **Storage:** stdlib `sqlite3`, single DB `instance/rat.db`; repos as full mirror clones in `instance/repos/<id>`; uploads staged in `instance/uploads/`.
- **Ingestion:** URL → `git clone --mirror` (deep, full history, no worktree); zip must contain `.git` (dir or file, including zips with a wrapping folder). Ingest runs as a background job with progress persisted and polled by the UI.
- **Correctness:** no graders' expected values are available (the brief provides only the three repo links) → self-verified via fixture repos with golden values plus an independent cross-check script on cJSON / Redis / git, run against pinned HEAD hashes captured at project start.
- Submission = the existing public remote; run instructions in README.

## Architecture & Guardrails (fixed in Stage 1, protects later stages)
- **Backend:** app factory `app/__init__.py`; JSON API blueprints: `repos`, `jobs`, `metrics` (query), `authors`. Services: `ingest.py` (validate/clone/extract), `analyzer.py` (streaming analysis → cache), `queries.py` (the ONLY metric read path), `authors.py` (alias resolution/merge), `jobs.py` (background jobs + progress).
- **Frontend:** `frontend/src/` with `api/` (fetch wrappers), `components/` (FilterBar, charts, tables), `pages/` (Dashboard, RepoOverview, ObjectDetail, Commits, Authors), `state/` (global filter context). Filter state synced to URL query params.
- **API surface (fixed early to avoid rework):** `POST /api/repos` (zip multipart or URL), `GET /api/repos`, `GET/DELETE /api/repos/<id>`, `POST /api/repos/<id>/reingest`, `GET /api/jobs/<id>`, `GET /api/repos/<id>/summary`, `GET /api/repos/<id>/commits` (paginated), `GET /api/repos/<id>/tree`, `GET /api/repos/<id>/metrics?object&author&ref&from&to&commits`, `GET /api/repos/<id>/series?metric&bucket`, `GET /api/repos/<id>/authors`, `POST /api/repos/<id>/authors/merge|split`.
- **Cache schema:** `repos`, `commits` (non-merge only: hash, parent, committer date, raw + mailmap identities), `changes` (commit, path, old_path, adds, dels, is_binary), `authors`, `author_alias` (mailmap + manual seeds), `ingest_jobs`, `schema_version`.
- **Guardrails:** metrics engine and query layer are pure over the cache; the UI depends ONLY on the REST API → filter/visualisation work cannot corrupt metric correctness. Backend pytest suite must be green before each stage transition; every bug fix adds a regression test. Frontend has no unit-test suite in scope (time budget) — covered by per-stage manual smoke that re-exercises all completed features.

## Stage 1 — Foundation & skeleton
- Repo hygiene: `.gitignore` (venv, `__pycache__`, `instance/`, `node_modules`), `requirements.txt`, README stub.
- Backend: app factory, `/api/healthz`, consistent JSON error-handling skeleton.
- Frontend: Vite + React + react-router shell with base design-system CSS; API client module; dev proxy to Flask.
- pytest scaffold + `tests/conftest.py` fixture-repo builder (add / edit / rename / rename+edit / delete / binary / merge commits / mailmap).
- Done when: `python run.py` + `npm run dev` show the SPA shell reading `/api/healthz`; pytest green; first commit clean of scratch files (delete `test_brief_extracted.txt`).

## Stage 2 — Ingestion & repository registry
- `POST /api/repos`: zip upload (locate top-level dir containing `.git`, reject without it, zip-slip-safe extraction) and URL deep clone (`--mirror`) — both as background jobs with progress; `GET /api/jobs/<id>` polling.
- Friendly error paths: invalid zip, missing `.git`, bad URL, clone/auth failure, disk errors.
- UI: "Add repository" (file picker + URL field), repo list with status polling (pending/analyzing/ready/failed) and commit counts.
- Done when: fixture repo and cJSON ingest via both forms through the browser; failure cases covered by tests.

## Stage 3 — Commit-stream analyzer (metrics foundation)
- One streaming pass per repo: `git log --numstat -M50% --no-merges -z --format=<%H|%P|%ct|%an|%ae|%aN|%aE>`, batched SQLite inserts into `changes`.
- Semantics locked here: binary excluded ("-" numstat), pure rename → no churn, rename+edit → counted on the NEW path (old_path retained), deletion → removals on its path, merge commits excluded, reference commit selectable (default HEAD).
- Directory metrics = path-prefix aggregation over `changes` (computed in the Stage 4 query layer).
- Ingest progress (commits processed / total).
- Done when: fixture per-commit l+/l−/δ/λ match hand-computed goldens for every edge case; cJSON fully ingests; re-runs are idempotent.

## Stage 4 — Query layer, metrics API + core views (≈50% rubric tier)
- Commit sets: full history to ref, H_t, H_i,j (committer date, half-open), manual lists, single commit; object resolution: exact file path, directory prefix, root.
- All commit-set metrics (sums, n_H,o, η, ρ) and author metrics (n_H,o,a, λ_H,o,a, ω) as SQL aggregations; `/summary`, `/metrics`, `/commits`, `/tree` endpoints.
- UI: repo overview (repository metrics = root), file/directory detail, commit list, author table.
- Independent cross-check script (separate raw-git commands, e.g. per-commit `git diff --numstat`) diffed against the API on cJSON and Redis.
- Done when: cross-check passes on cJSON + Redis; metric definitions frozen behind tests.

## Stage 5 — Filtering UX
- Global FilterBar: repository, author, file/directory tree selector, commit-set selector (date range → H_i,j, manual multi-select commit list, reference-commit picker); state synced to URL query params; all views recompute through the same metrics API.
- Done when: every view respects every filter and combinations; empty commit sets render spec-compliant zeros (η = ρ = 0).

## Stage 6 — Author merging
- Mailmap identity pairs stored at ingest; alias closure resolves canonical authors at query time (mailmap applied automatically, no re-ingest); manual merge/split endpoints + UI (author list with raw identities, merge modal).
- Done when: fixture with mailmap + multi-email author merges correctly; manual merge (no-mailmap case) immediately updates churn/ownership metrics; regression tests cover both paths.

## Stage 7 — Multi-repo support (100% requirements tier)
- Home dashboard lists all repos with summary cards; repo switcher; strict per-repo isolation in every query; re-ingest / rename / delete.
- Done when: cJSON + Redis loaded simultaneously with all Stage 4–6 features working per repo, no cross-talk.

## Stage 8 — Visualisation upgrade (Architecture & UI tier)
- ECharts components: stacked churn timeline (added/removed per period), commit calendar heatmap, directory treemap, author ownership donut, top-N movers tables; consistent theme; responsive layout.
- Interactions: tooltips + click-through that applies the matching filter (drill-down agrees with tables).
- Done when: all charts driven by `/series` + `/metrics`; drill-down navigates to matching filtered views.

## Stage 9 — Large-repo performance (~100k commits)
- Ingest: stream parsing (no full-output buffering), batched inserts, WAL + tuned PRAGMAs, single pass per repo.
- Queries/API: indexes (`repo,ct`), (`repo,path`); server-side bucketing for series; pagination for commits/authors; avoid N+1 fetches from the SPA.
- Targets: git.git (~80k commits) ingests in the background while the UI stays usable; cJSON/Redis metric views < ~300ms; large-repo views < ~1s.
- Done when: targets met on all three provided repos and cross-check still passes on sampled git.git ranges.

## Stage 10 — Usability, hardening & submission
- Error-handling sweep (invalid inputs, interrupted clone, empty filters, oversized uploads), loading/empty states, toast notifications.
- QoL: CSV export of metric tables, tooltips explaining each metric definition, README (dev + prod setup, screenshots, architecture notes, AI-use declaration if required).
- Final acceptance: build + commit the production bundle, verify plain `python run.py` serves the whole app with no Node/npm; correctness spot-check at pinned commits on cJSON/Redis/git; end-to-end walkthrough of every rubric bullet; clean commit history; push to the public remote.

## Test Plan (cumulative)
- Unit (pytest): fixture repos with golden values — every metric and edge case (binary, renames, deletes, merges, empty sets, half-open windows, mailmap, manual merge).
- Integration: independent raw-git cross-check script on cJSON/Redis (+ sampled git.git ranges in Stage 9) against pinned commit hashes.
- Performance: timed ingest + query latency on git.git.
- Manual: per-stage UI smoke covering all previously completed features, plus a full rubric walkthrough before submission.

## Risks / Mitigations
- Metric-definition ambiguities (binary files' effect on Modifications, deletion path attribution, directory roll-up semantics) → pinned in Stage 3 goldens and documented in README.
- Network dependency for npm/Vite and clones → production build committed; only clone-time network needed at grading; clear README.
- 100k-commit cost → mirror clone + single streaming pass + batched SQLite writes; background jobs keep the UI responsive.
- Scope creep in visualisation → charts consume only existing endpoints; no metric logic changes after Stage 4 without a fixture test.