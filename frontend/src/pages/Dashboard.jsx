import { useEffect, useState } from "react";

import { apiGet } from "../api/client.js";

export default function Dashboard() {
  const health = useHealth();

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">Repository metrics at a glance</p>
        </div>
        <HealthBadge health={health} />
      </div>

      <section className="card empty-state">
        <h2>No repositories yet</h2>
        <p>
          Repository ingestion (zip upload and clone URL) arrives in Stage 2 of the
          build plan.
        </p>
      </section>
    </>
  );
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
