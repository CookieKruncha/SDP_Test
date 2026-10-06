import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { reposApi } from "../api/client.js";

/** Side-by-side comparison of 2+ ingested repositories, using the same
 * per-repo metrics endpoint as the detail page (one call per selected repo,
 * run in parallel) so filters behave identically to a single-repo view.
 */
export default function Compare() {
  const { repos, error: reposError } = useRepos();
  const [selected, setSelected] = useState([]);
  const [filters, setFilters] = useState({ author: "", since: "", until: "" });
  const [pathFilter, setPathFilter] = useState("");

  const readyRepos = useMemo(() => (repos ?? []).filter((r) => r.status === "ready"), [repos]);
  const selectedIds = useMemo(
    () => selected.filter((id) => readyRepos.some((r) => r.id === id)),
    [selected, readyRepos]
  );

  function toggle(id) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  const { byRepo, loading, error } = useComparison(selectedIds, filters);
  const authorOptions = useAuthorOptions(selectedIds);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Compare repositories</h1>
          <p className="muted">
            <Link to="/">← Back to repositories</Link>
          </p>
        </div>
      </div>

      {reposError && (
        <section className="card form-error-card">
          <p className="form-error" role="alert">
            {reposError}
          </p>
        </section>
      )}

      <section className="card">
        <h3>1. Pick 2 or more repositories</h3>
        {readyRepos.length === 0 ? (
          <p className="muted">No ready repositories yet — ingest at least two to compare them.</p>
        ) : (
          <ul className="repo-pick-list">
            {readyRepos.map((repo) => (
              <li key={repo.id} className="repo-pick-item">
                <label>
                  <input
                    type="checkbox"
                    checked={selected.includes(repo.id)}
                    onChange={() => toggle(repo.id)}
                  />
                  <span className="mono">{repo.name}</span>
                  <span className="muted small"> · {repo.non_merge_count} commits</span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {selectedIds.length === 1 && (
          <p className="muted small">Pick at least one more repository to compare.</p>
        )}
      </section>

      {selectedIds.length >= 2 && (
        <>
          <section className="card filters-row">
            <label className="filter-field">
              <span className="muted small">Author (applied to every selected repo)</span>
              <select
                className="input"
                value={filters.author}
                onChange={(e) => setFilters({ ...filters, author: e.target.value })}
              >
                <option value="">All authors</option>
                {authorOptions.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              <span className="muted small">Since (committer date)</span>
              <input
                className="input"
                type="datetime-local"
                onChange={(e) => setFilters({ ...filters, since: toUnix(e.target.value) })}
              />
            </label>
            <label className="filter-field">
              <span className="muted small">Until (exclusive)</span>
              <input
                className="input"
                type="datetime-local"
                onChange={(e) => setFilters({ ...filters, until: toUnix(e.target.value) })}
              />
            </label>
            <label className="filter-field">
              <span className="muted small">Path contains</span>
              <input
                className="input"
                placeholder="e.g. src/"
                value={pathFilter}
                onChange={(e) => setPathFilter(e.target.value)}
              />
            </label>
          </section>

          {error && (
            <section className="card form-error-card">
              <p className="form-error" role="alert">
                {error}
              </p>
            </section>
          )}

          <section className="card">
            <h3>2. Totals</h3>
            {loading ? (
              <p className="muted">Loading metrics…</p>
            ) : (
              <SummaryTable repos={readyRepos} selectedIds={selectedIds} byRepo={byRepo} />
            )}
          </section>

          <section className="card">
            <h3>3. Per-file summary</h3>
            {!loading && (
              <FileCompareTable
                repos={readyRepos}
                selectedIds={selectedIds}
                byRepo={byRepo}
                pathFilter={pathFilter}
              />
            )}
          </section>
        </>
      )}
    </>
  );
}

function SummaryTable({ repos, selectedIds, byRepo }) {
  const nameOf = (id) => repos.find((r) => r.id === id)?.name ?? id;
  const totalCommits = selectedIds.reduce((sum, id) => sum + (byRepo[id]?.commit_count ?? 0), 0);
  const totalAuthors = selectedIds.reduce((sum, id) => sum + (byRepo[id]?.author_count ?? 0), 0);

  return (
    <table className="metrics-table compare-table">
      <thead>
        <tr>
          <th className="compare-row-label">Metric</th>
          {selectedIds.map((id) => (
            <th key={id}>{nameOf(id)}</th>
          ))}
          <th>Total (sum)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td className="compare-row-label">Commits (filtered)</td>
          {selectedIds.map((id) => (
            <td key={id}>{byRepo[id]?.commit_count ?? "—"}</td>
          ))}
          <td>{totalCommits}</td>
        </tr>
        <tr>
          <td className="compare-row-label">Authors (filtered)</td>
          {selectedIds.map((id) => (
            <td key={id}>{byRepo[id]?.author_count ?? "—"}</td>
          ))}
          <td title="Authors are not deduplicated across repositories">{totalAuthors}</td>
        </tr>
        <tr>
          <td className="compare-row-label">HEAD</td>
          {selectedIds.map((id) => (
            <td key={id} className="mono" title={byRepo[id]?.head_sha}>
              {byRepo[id]?.head_sha ? byRepo[id].head_sha.slice(0, 10) : "—"}
            </td>
          ))}
          <td />
        </tr>
      </tbody>
    </table>
  );
}

function FileCompareTable({ repos, selectedIds, byRepo, pathFilter }) {
  const nameOf = (id) => repos.find((r) => r.id === id)?.name ?? id;
  const needle = pathFilter.trim().toLowerCase();

  // Union of every object path seen across the selected repos, so repos
  // that lack a given path simply render "—" for that column.
  const allPaths = useMemo(() => {
    const seen = new Map(); // path -> type (prefer "repository"/"directory" over "file" if it ever differs)
    for (const id of selectedIds) {
      for (const obj of byRepo[id]?.objects ?? []) {
        if (!seen.has(obj.path)) seen.set(obj.path, obj.type);
      }
    }
    const paths = [...seen.entries()].map(([path, type]) => ({ path, type }));
    paths.sort((a, b) => (a.type !== b.type ? a.type.localeCompare(b.type) : a.path.localeCompare(b.path)));
    return needle ? paths.filter((p) => (p.path || "/").toLowerCase().includes(needle)) : paths;
  }, [selectedIds, byRepo, needle]);

  function cell(id, path) {
    const obj = (byRepo[id]?.objects ?? []).find((o) => o.path === path);
    if (!obj) return null;
    return obj;
  }

  return (
    <table className="metrics-table compare-table">
      <thead>
        <tr>
          <th rowSpan={2} className="compare-row-label">
            Path
          </th>
          {selectedIds.map((id) => (
            <th key={id} colSpan={2}>
              {nameOf(id)}
            </th>
          ))}
        </tr>
        <tr>
          {selectedIds.map((id) => (
            <Fragment key={id}>
              <th>Churn</th>
              <th>Mods</th>
            </Fragment>
          ))}
        </tr>
      </thead>
      <tbody>
        {allPaths.map(({ path, type }) => (
          <tr key={`${type}:${path}`}>
            <td className="mono compare-row-label">{path || "/"}</td>
            {selectedIds.map((id) => {
              const obj = cell(id, path);
              return (
                <Fragment key={id}>
                  <td>{obj ? obj.churn : "—"}</td>
                  <td>{obj ? obj.modifications : "—"}</td>
                </Fragment>
              );
            })}
          </tr>
        ))}
        {allPaths.length === 0 && (
          <tr>
            <td colSpan={1 + selectedIds.length * 2} className="muted">
              No objects match “{pathFilter}”.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function toUnix(datetimeLocal) {
  if (!datetimeLocal) return "";
  const ms = new Date(datetimeLocal).getTime();
  return Number.isNaN(ms) ? "" : String(Math.floor(ms / 1000));
}

function useRepos() {
  const [repos, setRepos] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    reposApi
      .list()
      .then((data) => setRepos(data.repos))
      .catch((err) => setError(err.message));
  }, []);

  return { repos, error };
}

/** Fetches /metrics for every selected repo in parallel, re-running whenever
 * the selection or the shared filters change. One repo's failure doesn't
 * block the others; its slot in the result map is simply left out.
 */
function useComparison(selectedIds, filters) {
  const [byRepo, setByRepo] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const key = selectedIds.join(",");

  const load = useCallback(() => {
    if (selectedIds.length < 2) return;
    setLoading(true);
    setError(null);
    Promise.all(
      selectedIds.map((id) =>
        reposApi
          .metrics(id, filters)
          .then((data) => [id, data])
          .catch((err) => [id, { error: err.message }])
      )
    ).then((pairs) => {
      const next = {};
      const failures = [];
      for (const [id, data] of pairs) {
        if (data.error) failures.push(`${id}: ${data.error}`);
        else next[id] = data;
      }
      setByRepo(next);
      setError(failures.length ? failures.join("; ") : null);
      setLoading(false);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, filters.author, filters.since, filters.until]);

  useEffect(() => {
    load();
  }, [load]);

  return { byRepo, loading, error };
}

/** Union of canonical author names across the selected repos, for the
 * cross-repo author filter dropdown.
 */
function useAuthorOptions(selectedIds) {
  const [options, setOptions] = useState([]);
  const key = selectedIds.join(",");

  useEffect(() => {
    if (selectedIds.length < 2) {
      setOptions([]);
      return;
    }
    Promise.all(selectedIds.map((id) => reposApi.authors(id).catch(() => ({ groups: [] }))))
      .then((results) => {
        const names = new Set();
        for (const { groups } of results) {
          for (const g of groups ?? []) names.add(g.canonical);
        }
        setOptions([...names].sort());
      })
      .catch(() => setOptions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return options;
}
