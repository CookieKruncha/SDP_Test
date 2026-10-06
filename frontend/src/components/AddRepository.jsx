import { useRef, useState } from "react";

import { reposApi } from "../api/client.js";

const MODES = [
  { id: "upload", label: "Upload .zip" },
  { id: "url", label: "Clone URL" },
];

/**
 * "Add repository" panel: zip upload or URL clone.
 * Both start a background ingestion job; the dashboard polls for progress.
 */
export default function AddRepository({ onAdded }) {
  const [mode, setMode] = useState("upload");
  const [file, setFile] = useState(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);

  async function submit(event) {
    event.preventDefault();
    setError(null);

    if (mode === "upload" && !file) {
      setError("Choose a .zip archive of a git repository first.");
      return;
    }
    if (mode === "url" && !url.trim()) {
      setError("Enter a repository URL to clone.");
      return;
    }

    setBusy(true);
    try {
      if (mode === "upload") {
        await reposApi.createFromFile(file);
      } else {
        await reposApi.createFromUrl(url.trim());
      }
      setFile(null);
      setUrl("");
      if (fileRef.current) fileRef.current.value = "";
      onAdded?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card add-repo">
      <h2>Add repository</h2>
      <div className="segmented" role="tablist" aria-label="Ingestion method">
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            role="tab"
            aria-selected={mode === m.id}
            className={mode === m.id ? "active" : ""}
            onClick={() => {
              setMode(m.id);
              setError(null);
            }}
          >
            {m.label}
          </button>
        ))}
      </div>

      <form className="add-repo-form" onSubmit={submit}>
        {mode === "upload" ? (
          <label className="file-field">
            <input
              ref={fileRef}
              type="file"
              accept=".zip"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              disabled={busy}
            />
            <span className="muted small">
              {file ? file.name : "A zip archive that includes the hidden .git folder"}
            </span>
          </label>
        ) : (
          <input
            className="text-input"
            type="text"
            placeholder="https://github.com/owner/repo.git"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            spellCheck={false}
            disabled={busy}
          />
        )}
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Adding…" : "Add repository"}
        </button>
      </form>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <p className="muted hint">
        Clones are full mirrors and stay on disk; large repositories ingest in
        the background while this page keeps working.
      </p>
    </section>
  );
}
