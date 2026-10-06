const BASE = import.meta.env.VITE_API_BASE ?? "";

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, options);
  if (response.status === 204) return null;

  const isJson = (response.headers.get("content-type") || "").includes("application/json");
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const detail = isJson ? payload?.detail : payload;
    throw new ApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      response.status,
      isJson ? detail : null
    );
  }
  return payload;
}

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export const api = {
  listJobs: () => request("/api/jobs?limit=100"),
  createJob: (name) =>
    request("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  // runId undefined => latest run; pass it to replay a previous compare.
  getReport: (jobId, runId) =>
    request(`/api/AI/jobs/${jobId}/report${runId ? `?run_id=${runId}` : ""}`),
  listRuns: (jobId) => request(`/api/AI/jobs/${jobId}/runs`),
  getRun: (jobId, runId) => request(`/api/AI/jobs/${jobId}/runs/${runId}`),
  compare: (jobId) => request(`/api/AI/jobs/${jobId}/compare`, { method: "POST" }),

  // runId is sent while browsing history; the backend answers 409.
  upload: (jobId, file, documentType = "UNKNOWN", runId = null) => {
    const form = new FormData();
    form.append("job_id", jobId);
    form.append("document_type", documentType);
    form.append("file", file);
    const q = runId ? `?run_id=${runId}` : "";
    return request(`/api/documents/upload${q}`, { method: "POST", body: form });
  },
  deleteDocument: (id, runId = null) =>
    request(`/api/documents/${id}${runId ? `?run_id=${runId}` : ""}`, { method: "DELETE" }),
  fileUrl: (id) => `${BASE}/api/documents/${id}/file`,
  docText: (id) => request(`/api/documents/${id}/text`),
};

export function formatDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("vi-VN", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export function shortId(id) {
  return id ? String(id).slice(0, 8) : "—";
}
