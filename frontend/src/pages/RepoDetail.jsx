import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { reposApi } from "../api/client.js";

/** File/directory/repository metrics table for one ingested repository. */
export default function RepoDetail() {
  const { repoId } = useParams();
  const { data, error, loading } = useMetrics(repoId);
  const [filter, setFilter] = useState("");

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

      {loading && (
        <section className="card empty-state">
          <p>Computing metrics…</p>
        </section>
      )}

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
                <dt>Non-merge commits</dt>
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

          <section className="card">
            <input
              className="input"
              placeholder="Filter by path…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <MetricsTable objects={data.objects} filter={filter} />
          </section>
        </>
      )}
    </>
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

function useMetrics(repoId) {
  const [state, setState] = useState({ data: null, error: null, loading: true });

  useEffect(() => {
    let cancelled = false;
    setState({ data: null, error: null, loading: true });
    reposApi
      .metrics(repoId)
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch(
        (err) => !cancelled && setState({ data: null, error: err.message, loading: false })
      );
    return () => {
      cancelled = true;
    };
  }, [repoId]);

  return state;
}
