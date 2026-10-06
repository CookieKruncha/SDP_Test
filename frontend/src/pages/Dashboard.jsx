import { useCallback, useEffect, useState } from "react";

import AddRepository from "../components/AddRepository.jsx";
import RepoList from "../components/RepoList.jsx";
import { apiGet, reposApi } from "../api/client.js";

export default function Dashboard() {
  const health = useHealth();
  const { repos, error, reload } = useRepos();

  // While any repo is being ingested, poll so status/progress stay live.
  const hasActive = (repos ?? []).some(
    (repo) => repo.status === "pending" || repo.status === "running"
  );
  useEffect(() => {
    if (!hasActive) return undefined;
    const timer = setInterval(reload, 1500);
    return () => clearInterval(timer);
  }, [hasActive, reload]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">Repositories available to analyse</p>
        </div>
        <HealthBadge health={health} />
      </div>

      <AddRepository onAdded={reload} />

      {error && (
        <section className="card form-error-card">
          <p className="form-error" role="alert">
            {error}
          </p>
        </section>
      )}

      <RepoList repos={repos} onChanged={reload} />
    </>
  );
}

/** Loads the repository list; exposed with a stable reload callback. */
function useRepos() {
  const [repos, setRepos] = useState(null);
  const [error, setError] = useState(null);

  const reload = useCallback(() => {
    reposApi
      .list()
      .then((data) => {
        setRepos(data.repos);
        setError(null);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  return { repos, error, reload };
}

/** Polls API health once on mount; proves the SPA <-> API wiring end to end. */
function useHealth() {
  const [health, setHealth] = useState({ state: "loading" });

  useEffect(() => {
    let cancelled = false;
    apiGet("/api/healthz")
      .then((data) => !cancelled && setHealth({ state: "ok", data }))
      .catch((err) => !cancelled && setHealth({ state: "error", message: err.message }));
    return () => {
      cancelled = true;
    };
  }, []);

  return health;
}

function HealthBadge({ health }) {
  if (health.state === "loading") {
    return <span className="badge">Checking API…</span>;
  }
  if (health.state === "error") {
    return (
      <span className="badge err" title={health.message}>
        <span className="dot" />
        API unreachable
      </span>
    );
  }
  return (
    <span className="badge ok" title={`service: ${health.data.service}`}>
      <span className="dot" />
      API connected · schema v{health.data.schema_version}
    </span>
  );
}
