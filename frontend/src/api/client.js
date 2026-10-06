/**
 * Minimal fetch wrapper for the RAT JSON API.
 * Failures are normalized into ApiError with a human-readable message.
 */
export class ApiError extends Error {
  constructor(message, { status, code } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { Accept: "application/json", ...(options.headers ?? {}) },
    });
  } catch {
    throw new ApiError("The API is unreachable. Is the backend running?", {
      code: "network_error",
    });
  }

  const contentType = response.headers.get("content-type") ?? "";
  const body = contentType.includes("application/json") ? await response.json() : null;

  if (!response.ok) {
    throw new ApiError(body?.error?.message ?? `Request failed (${response.status})`, {
      status: response.status,
      code: body?.error?.code ?? "http_error",
    });
  }
  return body;
}

export function apiGet(path, params) {
  let url = path;
  if (params) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") query.set(key, value);
    }
    const qs = query.toString();
    if (qs) url = `${path}?${qs}`;
  }
  return request(url);
}

export function apiPost(path, json) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(json ?? {}),
  });
}

export function apiDelete(path) {
  return request(path, { method: "DELETE" });
}

export function apiUpload(path, formData) {
  // No explicit Content-Type: the browser must set the multipart boundary.
  return request(path, { method: "POST", body: formData });
}

/** Thin wrappers for the repository registry endpoints. */
export const reposApi = {
  list: () => apiGet("/api/repos"),
  get: (repoId) => apiGet(`/api/repos/${repoId}`),
  createFromUrl: (url) => apiPost("/api/repos", { url }),
  createFromFile: (file) => {
    const form = new FormData();
    form.append("file", file);
    return apiUpload("/api/repos", form);
  },
  remove: (repoId) => apiDelete(`/api/repos/${repoId}`),
  job: (jobId) => apiGet(`/api/jobs/${jobId}`),
  metrics: (repoId) => apiGet(`/api/repos/${repoId}/metrics`),
};
