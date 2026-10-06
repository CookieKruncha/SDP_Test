import { useState } from "react";

import { reposApi } from "../api/client.js";

const STATUS_LABELS = {
  pending: "Queued",
  running: "Ingesting",
  ready: "Ready",
  failed: "Failed",
};

const STATUS_VARIANTS = {
  pending: "warn",
  running: "info",
  ready: "ok",
  failed: "err",
};

const PHASE_LABELS = {
  queued: "Queued",
  cloning: "Cloning repository",
  extracting: "Extracting archive",
  validating: "Validating repository",
  finished: "Finished",
};

/** Repository cards with per-repo status, progress and commit counts. */
export default function RepoList({ repos, onChanged }) {
  if (repos === null) {
    return (
      <section className="card empty-state">
        <p>Loading repositories…</p>
      </section>
    );
  }
  if (repos.length === 0) {
    return (
      <section className="card empty-state">
        <h2>No repositories yet</h2>
        <p>Add one above — upload a zip archive or clone it from a URL.</p>
      </section>
    );
  }
  return (
    <div className="repo-grid">
      {repos.map((repo) => (
        <RepoCard key={repo.id} repo={repo} onChanged={onChanged} />
      ))}
    </div>
  );
}

function RepoCard({ repo, onChanged }) {
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState(null);
  const active = repo.status === "pending" || repo.status === "running";

  async function remove() {
    if (!window.confirm(`Remove "${repo.name}" and its local copy?`)) return;
    setRemoving(true);
    setRemoveError(null);
    try {
      await reposApi.remove(repo.id);
      onChanged?.();
    } catch (err) {
      setRemoveError(err.message);
    } finally {
      setRemoving(false);
    }
  }

  return (
    <article className="card repo-card">
      <div className="repo-card-head">
        <div className="repo-card-title">
          <h3>{repo.name}</h3>
          <p className="muted small" title={repo.source ?? ""}>
            {repo.source_type === "url" ? "Cloned" : "Uploaded"} · {repo.source}
          </p>
        </div>
        <StatusBadge status={repo.status} />
      </div>

      {repo.status === "ready" && (
        <dl className="repo-stats">
          <div>
            <dt>Commits</dt>
            <dd>{repo.commit_count}</dd>
          </div>
          <div>
            <dt>Non-merge</dt>
            <dd>{repo.non_merge_count}</dd>
          </div>
          <div>
            <dt>HEAD</dt>
            <dd className="mono" title={repo.head_sha ?? ""}>
              {repo.head_sha ? repo.head_sha.slice(0, 10) : "—"}
            </dd>
          </div>
        </dl>
      )}

      {active && <Progress job={repo.job} />}

      {repo.status === "failed" && repo.error && (
        <p className="form-error" role="alert">
          {repo.error}
        </p>
      )}

      <div className="repo-card-foot">
        <span className="muted small">Added {formatTime(repo.created_at)}</span>
        <button
          type="button"
          className="btn ghost danger"
          onClick={remove}
          disabled={active || removing}
          title={active ? "Wait for ingestion to finish before removing" : "Remove"}
        >
          {removing ? "Removing…" : "Remove"}
        </button>
      </div>
      {removeError && (
        <p className="form-error" role="alert">
          {removeError}
        </p>
      )}
    </article>
  );
}

function StatusBadge({ status }) {
  const variant = STATUS_VARIANTS[status] ?? "";
  const pulse = status === "running" ? " pulse" : "";
  return (
    <span className={`badge ${variant}${pulse}`}>
      <span className="dot" />
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function Progress({ job }) {
  const progress = Math.min(Math.max(job?.progress ?? 0, 0), 1);
  const percent = Math.round(progress * 100);
  return (
    <div className="progress-wrap">
      <div className="progress">
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
      <span className="muted small">
        {PHASE_LABELS[job?.phase] ?? "Working"} · {percent}%
      </span>
    </div>
  );
}

function formatTime(unixSeconds) {
  if (!unixSeconds) return "—";
  return new Date(unixSeconds * 1000).toLocaleString();
}
