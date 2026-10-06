import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { reposApi } from "../api/client.js";

/** File/directory/repository metrics table for one ingested repository,
 * filterable by author / committer-date window / path, plus a manual
 * author-merge panel for when no (or an incomplete) .mailmap is present.
 */
export default function RepoDetail() {
  const { repoId } = useParams();
  const [filters, setFilters] = useState({ author: "", since: "", until: "" });
  const { data, error, loading, reload } = useMetrics(repoId, filters);
  const { groups, reloadGroups } = useAuthorGroups(repoId);
  const [pathFilter, setPathFilter] = useState("");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Metrics</h1>
          <p className="muted">
            <Link to="/">← Back to repositories</Link>
          </p>
        </div>
      </div>

      {error && (
        <section className="card form-error-card">
          <p className="form-error" role="alert">
            {error}
          </p>
        </section>
      )}

      {data && (
        <>
          <section className="card">
            <dl className="repo-stats">
              <div>
                <dt>Non-merge commits (filtered)</dt>
                <dd>{data.commit_count}</dd>
              </div>
              <div>
                <dt>Authors</dt>
                <dd>{data.author_count}</dd>
              </div>
              <div>
                <dt>HEAD</dt>
                <dd className="mono" title={data.head_sha}>
                  {data.head_sha.slice(0, 10)}
                </dd>
              </div>
            </dl>
          </section>

          <Filters
            filters={filters}
            onChange={setFilters}
            groups={groups}
            pathFilter={pathFilter}
            onPathChange={setPathFilter}
          />

          <AuthorMerge
            repoId={repoId}
            groups={groups}
            onChanged={() => {
              reloadGroups();
              reload();
            }}
          />

          <section className="card">
            {loading ? (
              <p className="muted">Updating…</p>
            ) : (
              <MetricsTable objects={data.objects} filter={pathFilter} />
            )}
          </section>
        </>
      )}
    </>
  );
}

function Filters({ filters, onChange, groups, pathFilter, onPathChange }) {
  const canonicalNames = groups.map((g) => g.canonical);
  return (
    <section className="card filters-row">
      <label className="filter-field">
        <span className="muted small">Author</span>
        <select
          className="input"
          value={filters.author}
          onChange={(e) => onChange({ ...filters, author: e.target.value })}
        >
          <option value="">All authors</option>
          {canonicalNames.map((name) => (
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
          onChange={(e) => onChange({ ...filters, since: toUnix(e.target.value) })}
        />
      </label>
      <label className="filter-field">
        <span className="muted small">Until (exclusive)</span>
        <input
          className="input"
          type="datetime-local"
          onChange={(e) => onChange({ ...filters, until: toUnix(e.target.value) })}
        />
      </label>
      <label className="filter-field">
        <span className="muted small">Path contains</span>
        <input
          className="input"
          placeholder="e.g. src/"
          value={pathFilter}
          onChange={(e) => onPathChange(e.target.value)}
        />
      </label>
    </section>
  );
}

function AuthorMerge({ repoId, groups, onChanged }) {
  const [selected, setSelected] = useState([]);
  const [canonical, setCanonical] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  function toggle(name) {
    setSelected((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    );
  }

  async function merge() {
    if (selected.length < 2 || !canonical.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await reposApi.mergeAuthors(repoId, selected, canonical.trim());
      setSelected([]);
      setCanonical("");
      onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function split(member) {
    setBusy(true);
    setError(null);
    try {
      await reposApi.splitAuthor(repoId, member);
      onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h3>Author merge</h3>
      <p className="muted small">
        Mailmap entries are merged automatically. Select two or more authors below
        to merge them manually under one display name.
      </p>
      <ul className="author-groups">
        {groups.map((group) => (
          <li key={group.canonical} className="author-group">
            <span className="mono">{group.canonical}</span>
            {group.members.length > 1 && (
              <span className="muted small">
                {" "}
                ({group.members.length} merged)
              </span>
            )}
            {group.members.map((member) => (
              <span key={member} className="author-chip">
                {group.members.length > 1 && member !== group.canonical && (
                  <button
                    type="button"
                    className="btn ghost tiny"
                    disabled={busy}
                    onClick={() => split(member)}
                    title={`Split "${member}" out of this group`}
                  >
                    ×
                  </button>
                )}
                <label>
                  <input
                    type="checkbox"
                    checked={selected.includes(member)}
                    onChange={() => toggle(member)}
                  />
                  {member}
                </label>
              </span>
            ))}
          </li>
        ))}
      </ul>
      <div className="repo-card-actions">
        <input
          className="input"
          placeholder="Merged display name…"
          value={canonical}
          onChange={(e) => setCanonical(e.target.value)}
        />
        <button
          type="button"
          className="btn"
          disabled={busy || selected.length < 2 || !canonical.trim()}
          onClick={merge}
        >
          Merge {selected.length > 0 ? `(${selected.length})` : ""}
        </button>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function MetricsTable({ objects, filter }) {
  const needle = filter.trim().toLowerCase();
  const rows = needle
    ? objects.filter((o) => (o.path || "/").toLowerCase().includes(needle))
    : objects;

  return (
    <table className="metrics-table">
      <thead>
        <tr>
          <th>Type</th>
          <th>Path</th>
          <th>+</th>
          <th>−</th>
          <th>Growth</th>
          <th>Churn</th>
          <th>Modifications</th>
          <th>Mod. freq.</th>
          <th>Churn rate</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((o) => (
          <tr key={`${o.type}:${o.path}`}>
            <td className="muted small">{o.type}</td>
            <td className="mono">{o.path || "/"}</td>
            <td>{o.added}</td>
            <td>{o.removed}</td>
            <td>{o.growth}</td>
            <td>{o.churn}</td>
            <td>{o.modifications}</td>
            <td>{o.modification_frequency.toFixed(3)}</td>
            <td>{o.churn_rate.toFixed(3)}</td>
          </tr>
        ))}
        {rows.length === 0 && (
          <tr>
            <td colSpan={9} className="muted">
              No objects match “{filter}”.
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

function useMetrics(repoId, filters) {
  const [state, setState] = useState({ data: null, error: null, loading: true });

  const reload = useCallback(() => {
    setState((prev) => ({ ...prev, loading: true }));
    reposApi
      .metrics(repoId, filters)
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((err) => setState({ data: null, error: err.message, loading: false }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId, filters.author, filters.since, filters.until]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { ...state, reload };
}

function useAuthorGroups(repoId) {
  const [groups, setGroups] = useState([]);

  const reloadGroups = useCallback(() => {
    reposApi
      .authors(repoId)
      .then((data) => setGroups(data.groups))
      .catch(() => setGroups([]));
  }, [repoId]);

  useEffect(() => {
    reloadGroups();
  }, [reloadGroups]);

  return { groups, reloadGroups };
}
