# RAT — Repository Analysis Tool

COMS3011A test deliverable: a web dashboard that ingests git repositories
(zip upload or remote clone URL) and computes file, directory, repository,
commit-set, and author metrics, with commit filtering, author merging, and
multi-repository comparison.

## Stack

- **Backend:** Python 3.12 + Flask 3 (JSON API), stdlib `sqlite3` as a
  repository registry / derived-data cache. All git operations run through
  the `git` CLI via `subprocess` (`app/services/gitlog.py`), so metric
  semantics (line counts, rename detection at `-M50%`, binary detection,
  `.mailmap`) match git exactly rather than approximating it.
- **Frontend:** React 18 SPA built with Vite, plain JavaScript/JSX,
  react-router for navigation. No build-time framework beyond Vite; the
  production bundle is committed under `frontend/dist` so grading needs no
  `npm install`.

## Quick start

### Run the whole app (no Node/npm required)

The production frontend bundle is committed, so this is enough to use the
full app:

```bash
pip install -r requirements.txt
python run.py                 # http://127.0.0.1:5000
```

### Frontend (development, with hot reload)

Only needed if you're changing frontend code:

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173, proxies /api to :5000
```

### Rebuilding the production bundle

Run this after any frontend change and commit the resulting `frontend/dist`:

```bash
cd frontend
npm install
npm run build                 # outputs frontend/dist, served by python run.py
```

### Tests

```bash
pip install -r requirements-dev.txt
pytest                        # runs the test suite in tests/
```

`python run.py` deliberately runs without the Werkzeug auto-reloader — the
reloader watches the whole project tree (including `instance/`, where
ingestion writes files), and a reload would kill in-flight ingest jobs. Set
`RAT_DEBUG=1` for the interactive debugger (the reloader stays off).

## Using the app

1. **Add a repository** from the dashboard: upload a `.zip` of a repo (must
   contain a `.git` directory somewhere inside, including inside a single
   wrapping folder) or paste a clone URL. Ingestion runs as a background job
   (clone/extract → validate → analyse) with live progress; the repo card
   flips to "Ready" when it's queryable.
2. **View metrics** for a ready repository: file / directory / repository
   rows with added/removed/growth/churn/modifications/modification-frequency
   /churn-rate, each broken down by author with an ownership ratio. Filter by
   author, a committer-date window, or an explicit comma-separated commit SHA
   list; the path-contains box narrows the visible rows client-side.
3. **Merge authors** on the same page when `.mailmap` doesn't already cover
   an alias: select two or more raw identities, give them a canonical display
   name, and all metrics (including ownership) are recomputed over the
   merged identity. Splitting an identity back out is one click.
4. **Compare repositories**: pick two or more ready repositories on the
   `/compare` page to see commit/author totals and a per-file churn +
   modifications breakdown side by side, with the same author/date/path
   filters applied identically to every selected repo.
5. **Remove a repository** from its card; this deletes its local clone and
   derived data.

## Metric definitions (brief-aligned)

- **File metrics**: `added` (l+), `removed` (l−), `growth` (δ = l+ − l−),
  `churn` (λ = l+ + l−), `modifications` (count of non-merge commits that
  touched the path).
- **Directory / repository metrics**: the sum of the above over every file
  nested under that path (the repository is the sum over the whole tree);
  computed by flat prefix-propagation, which is algebraically equivalent to
  recursive summation over immediate children.
- **Commit-set metrics**: `modification_frequency` = modifications / commits
  in the set (η), `churn_rate` = churn / commits in the set (ρ). An empty
  commit set yields `0` for both rather than dividing by zero.
- **Author ownership** (ω): an author's share of an object's churn within
  the active commit set — `(author added + author removed) / object churn`.
- Merge commits are excluded everywhere (`--no-merges`); renames are detected
  at a 50% similarity threshold (`-M50%`) and attributed to the new path;
  binary files are excluded from line-count metrics but still count as a
  modification.

## Correctness

The analyzer has no access to a grading rubric with expected values, so it
is self-verified two ways:

- `tests/test_analyzer_fixture.py` — a synthetic fixture repo
  (`tests/conftest.py`) with hand-computed goldens for every edge case: pure
  rename, rename+edit, delete, binary file, merge commit, `.mailmap`-merged
  dual-email author.
- `tests/test_golden_metrics.py` — clones cJSON and Redis at the pinned
  commit hashes recorded in `repo-references/*.csv` and diffs every row of
  the analyzer's output against those reference CSVs (committer-provided
  "golden" values for this assessment).

Run `pytest` to execute both; CI-equivalent correctness is reproduced any
time this is run.

## Architecture

```
app/__init__.py          Flask app factory, SPA static serving, error handling
app/config.py            Config (DB path, instance dir, cache schema version)
app/db.py                 SQLite schema + connection helpers
app/errors.py             ApiError -> JSON error envelope
app/routes/               Blueprints: health, repos, jobs, metrics (+ authors)
app/services/
  ingest.py               Zip validation/extraction, mirror clone, orchestration
  jobs.py                 Background job runner + progress tracking
  registry.py             Repository registry (SQLite) CRUD
  gitlog.py               subprocess wrapper: parses `git log --numstat -z`
  analyzer.py             Per-file/directory/repository/author aggregation
  metrics.py              Caching + commit-set filtering layer over analyzer
  authors.py              Manual author-alias merge/split, on top of mailmap
frontend/src/
  api/client.js           Fetch wrapper + typed endpoint helpers
  components/             Shared UI (repo cards, add-repository form, layout)
  pages/                  Dashboard, RepoDetail (metrics+filters+merge), Compare
  styles/theme.css        Design-system tokens + component styles
tests/                    pytest suite (fixtures, ingestion, metrics API, goldens)
repo-references/          Grading reference CSVs for cJSON / Redis / git at pinned SHAs
instance/                 Runtime data: cloned repos, uploads, SQLite cache (git-ignored)
```

Design decisions worth noting:

- **Caching**: metrics are computed on first request per `(repo_id,
  head_sha)` and cached in-process (`app/services/metrics.py`); re-ingesting
  a repo (new `head_sha`) invalidates automatically, and explicit removal
  calls `metrics.invalidate()`. This is a deliberate, documented trade-off
  for moderate repo sizes — see the next section for the large-repo path.
- **Author merging**: manual aliases are stored per-repo
  (`repo_id, raw_author -> canonical_author`) and applied when shaping the
  JSON response, not by re-walking git, since ownership is a ratio that must
  be recomputed from merged sums rather than combined after the fact.
- **Filtering**: author / committer-date-window / explicit-SHA filters are
  applied to the already-fetched raw commit list before the (same,
  golden-validated) aggregation function runs — no separate filtering-aware
  aggregation code path to keep in sync.

## Known limitations / next steps

- The in-process metrics cache (see above) is appropriate for small/medium
  repositories; a very large history (git.git-scale, ~80k+ commits) has not
  been performance-tested and would benefit from ingestion-time
  precomputation into SQLite instead of on-demand analysis.
- No chart/visualisation layer yet (treemap, commit heatmap, ownership
  donut) — current views are tabular.
- Single-process deployment assumption: the metrics cache is per-process, so
  it would need to move to a shared store before running multiple API
  workers.

## AI-use declaration

Significant portions of this project (planning, implementation, and tests)
were produced with AI pair-programming assistance, under direct human
review and iteration at each stage.
