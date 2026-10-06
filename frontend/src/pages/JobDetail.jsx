import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api, formatDate, shortId } from "../api.js";
import { Alert, Badge, Empty, Finding, Spinner, Stat } from "../components/ui.jsx";
import ReportView from "../components/ReportView.jsx";

const TYPE_LABEL = {
  COMMERCIAL_INVOICE: "Commercial Invoice",
  PACKING_LIST: "Packing List",
  BILL_OF_LADING: "Bill of Lading",
  OTHER: "Không xác định",
  UNKNOWN: "Chưa phân loại",
};

export default function JobDetail() {
  const { jobId } = useParams();
  const [data, setData] = useState(null);
  const [runs, setRuns] = useState([]);
  const [viewRunId, setViewRunId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState(null);
  const [comparing, setComparing] = useState(false);
  const [uploading, setUploading] = useState(false);

  const isHistory = Boolean(viewRunId);

  const loadRuns = useCallback(async () => {
    const res = await api.listRuns(jobId);
    setRuns(res.runs || []);
  }, [jobId]);

  const loadReport = useCallback(
    async (runId) => {
      setError("");
      setData(await api.getReport(jobId, runId));
    },
    [jobId]
  );

  async function loadAll(runId) {
    try {
      await Promise.all([loadReport(runId), loadRuns()]);
    } catch (e) {
      setError(e.message || "Không tải được dữ liệu job");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setSelected(null);
    setViewRunId(null);
    setNotice("");
    loadAll(null);
  }, [jobId]);

  async function runCompare() {
    setComparing(true);
    setNotice("");
    setError("");
    try {
      const res = await api.compare(jobId);
      setNotice(
        `Kiểm tra hoàn tất (lần #${res.run?.run_number}): ` +
          `rụi ro ${res.validation?.risk_level ?? "—"}, ` +
          `${res.persisted_issue_ids?.length ?? 0} lỗi đã lưu.`
      );
      setViewRunId(null);
      setSelected(null);
      await loadAll(null);
    } catch (e) {
      setError(e.message);
      await loadAll(viewRunId);
    } finally {
      setComparing(false);
    }
  }

  async function openRun(runId) {
    if (runId === null) {
      setViewRunId(null);
      setSelected(null);
      setNotice("");
      await loadAll(null);
      return;
    }
    setViewRunId(runId);
    setSelected(null);
    setNotice("");
    await loadAll(runId);
  }

  async function onUpload(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (files.length === 0) return;
    setUploading(true);
    setError("");
    try {
      for (const file of files) {
        await api.upload(jobId, file, "UNKNOWN", viewRunId);
      }
      await loadAll(viewRunId);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  }

  async function onDeleteDoc(doc) {
    if (!window.confirm(`Xóa "${doc.filename}"?`)) return;
    try {
      await api.deleteDocument(doc.id, viewRunId);
      if (selected === doc.id) setSelected(null);
      await loadAll(viewRunId);
    } catch (e) {
      setError(e.message);
    }
  }

  if (loading) return <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">Đang tải…</div>;
  if (error && !data) return <Alert kind="error">{error}</Alert>;
  if (!data) return null;

  const {
    job, issues = [], issue_totals: totals = {},
    documents = [], report, has_report: hasReport,
  } = data;
  // Header error stats describe the run on screen. In history mode the backend
  // already scopes issue_totals to the viewed run; outside history mode
  // issue_totals sums every compare run, so use the latest run's own counts.
  const latestRun = runs[0] || null;
  const headerTotals =
    !isHistory && latestRun
      ? {
          total: latestRun.issue_count ?? 0,
          by_severity: latestRun.issue_count_by_severity || {},
        }
      : totals;
  const sev = headerTotals.by_severity || {};
  // stats describe the run currently on screen (latest unless in history mode)
  const summary = report?.summary || {};
  const activeDoc = documents.find((d) => d.id === selected) || null;

  return (
    <>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1.5">
            <Link to="/" className="text-[13px] text-slate-400 hover:text-slate-200">← Lịch sử</Link>
          </div>
          <h2 className="text-[19px] font-semibold">{job.name || "Không tên"}</h2>
          <div className="mt-1 font-mono text-xs text-slate-400">
            Job {shortId(job.id)} · tạo {formatDate(job.created_at)}
            {data.run && ` · lần #${data.run.run_number} đế {formatDate(data.run.created_at)}`}
          </div>
        </div>
        <div className="flex items-center gap-2.5">
          <Badge value={job.risk_level} fallback="Chưa kiểm tra" />
          <Badge value={job.status} />
        </div>
      </div>

      {isHistory && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-md border border-sky-800 bg-sky-500/10 px-3.5 py-2.5">
          <span className="text-[13px] text-sky-200">
            Đang xem lịch sử — lần #{data.run?.run_number} ({formatDate(data.run?.created_at)}). Chế độ chế ś đổ.
          </span>
          <button
            onClick={() => openRun(null)}
            className="rounded-md bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-500"
          >
            Về lần mới nhất
          </button>
        </div>
      )}

      <div className="mb-3 flex flex-wrap gap-2.5">
        <Stat label="Chứng từ" value={documents.length} />
        <Stat label="Lần kiểm tra" value={runs.length} />
        <Stat
          label="Lỗi lần này"
          value={headerTotals.total ?? 0}
          tone={headerTotals.total ? "HIGH" : "LOW"}
        />
        <Stat label="HIGH" value={sev.HIGH ?? 0} tone={sev.HIGH ? "HIGH" : "LOW"} />
        <Stat label="MEDIUM" value={sev.MEDIUM ?? 0} tone={sev.MEDIUM ? "MEDIUM" : "LOW"} />
        <Stat label="PASS" value={summary.PASS ?? 0} tone="LOW" />
        <Stat label="Tổng rule" value={report?.findings?.length ?? 0} />
      </div>

      <Alert kind="error">{error}</Alert>
      <Alert kind="info">{notice}</Alert>

      <div className="grid items-start gap-4 lg:grid-cols-[290px_1fr]">
        <aside className="lg:sticky lg:top-20">
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-3.5">
            <h3 className="mb-3 text-[11px] uppercase tracking-wider text-slate-400">
              Chứng từ ({documents.length})
            </h3>

            {documents.length === 0 && (
              <div className="mb-2.5 text-[12.5px] text-slate-400">Chưa có chứng từ.</div>
            )}

            {documents.map((doc) => (
              <div
                key={doc.id}
                onClick={() => setSelected(selected === doc.id ? null : doc.id)}
                className={`mb-2 flex cursor-pointer items-center gap-2 rounded-lg border px-2.5 py-2 ${
                  selected === doc.id
                    ? "border-blue-500 bg-blue-500/10"
                    : "border-slate-700 bg-slate-800/50 hover:border-slate-600"
                }`}
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px]" title={doc.filename}>{doc.filename}</div>
                  <div className="text-[10px] text-slate-400">
                    {TYPE_LABEL[doc.document_type] || doc.document_type}
                    {doc.page_count ? ` · ${doc.page_count} trang` : ""}
                  </div>
                </div>
                {!isHistory && (
                  <button
                    title="Xóa chứng từ"
                    onClick={(e) => { e.stopPropagation(); onDeleteDoc(doc); }}
                    className="rounded px-1 text-[15px] text-slate-400 hover:bg-red-500/15 hover:text-red-300"
                  >
                    {"🗑"}
                  </button>
                )}
              </div>
            ))}

            {isHistory ? (
              <p className="mt-3 border-t border-slate-800 pt-3 text-[12px] text-slate-500">
                Không thể thêm/xóa chứng từ khi đang xem lịch sử.
              </p>
            ) : (
              <div className="mt-3 border-t border-slate-800 pt-3">
                <label className="mb-2 block w-full cursor-pointer rounded-md border border-slate-700 bg-slate-800 py-2 text-center text-[13px] hover:bg-slate-700">
                  {uploading ? "Đang tải lên…" : "＋ Upload chứng từ"}
                  <input type="file" multiple accept=".pdf,.txt,.md" onChange={onUpload}
                         disabled={uploading} className="hidden" />
                </label>
                <button
                  onClick={runCompare}
                  disabled={comparing || documents.length === 0}
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-blue-600 py-2 text-[13px] font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
                >
                  {comparing && <Spinner />}
                  {comparing ? " Đang kiểm tra…" : "Kiểm tra Import Risk"}
                </button>
              </div>
            )}
          </div>

          <div className="mt-3.5 rounded-xl border border-slate-800 bg-slate-900 p-3.5">
            <h3 className="mb-3 text-[11px] uppercase tracking-wider text-slate-400">
              Lịch sử kiểm tra ({runs.length})
            </h3>
            {runs.length === 0 ? (
              <div className="text-[12.5px] text-slate-400">Chưa có lần kiểm tra nào.</div>
            ) : (
              runs.map((r) => {
                const active = viewRunId === r.id;
                const isLatest = runs[0]?.id === r.id;
                return (
                  <button
                    key={r.id}
                    onClick={() => openRun(active && isLatest ? null : r.id)}
                    className={`mb-2 block w-full rounded-lg border px-2.5 py-2 text-left ${
                      active
                        ? "border-blue-500 bg-blue-500/10"
                        : "border-slate-700 bg-slate-800/50 hover:border-slate-600"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[12.5px] font-semibold">
                        Lần #{r.run_number}
                        {isLatest && <span className="ml-1.5 text-[10px] font-normal text-emerald-400">mới nhất</span>}
                      </span>
                      <Badge value={r.risk_level} fallback="—" />
                    </div>
                    <div className="mt-0.5 text-[11px] text-slate-400">
                      {formatDate(r.created_at)} · {r.issue_count} lỗi
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        <section className="min-h-[520px]">
          {!hasReport ? (
            <Empty
              icon={documents.length ? "🧾" : "📂"}
              title={documents.length ? "Chưa có kết quả kiểm tra" : "Chưa có chứng từ nào"}
              hint={documents.length
                ? 'Bấm "Kiểm tra Import Risk" ở thanh bên trái để chạy AI so sánh bộ chứng từ.'
                : "Upload PDF chứng từ ở thanh bên trái để bắt đầu."}
            />
          ) : !activeDoc ? (
            <>
              <ReportView report={report} />
              {issues.length > 0 && (
                <div className="mt-3.5 rounded-xl border border-slate-800 bg-slate-900 p-4">
                  <h2 className="mb-3 text-[15px] font-semibold">
                    Lỗi đã lưu ({issues.length})
                  </h2>
                  {issues.map((i) => (
                    <Finding
                      key={i.id}
                      severity={i.severity}
                      rule={i.rule_code}
                      message={i.message}
                      extra={<><Badge value={i.severity} /><Badge value={i.status} /></>}
                    />
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="grid items-start gap-3.5 xl:grid-cols-[70fr_30fr]">
              <DocViewer doc={activeDoc} />
              <ReportView report={report} />
            </div>
          )}
        </section>
      </div>
    </>
  );
}

function DocViewer({ doc }) {
  const isPdf = (doc.filename || "").toLowerCase().endsWith(".pdf");
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-2 text-[15px] font-semibold">{doc.filename}</h2>
      <div className="mb-3 font-mono text-xs text-slate-400">
        {TYPE_LABEL[doc.document_type] || doc.document_type}
        {doc.model_name && ` · ${doc.model_name}`}
      </div>

      {isPdf ? (
        <iframe className="h-[640px] w-full rounded-lg border border-slate-700 bg-white"
                src={api.fileUrl(doc.id)} title={doc.filename} />
      ) : (
        <TextPreview doc={doc} />
      )}

      {doc.extracted_data && (
        <>
          <h3 className="mb-2 mt-4 text-[11px] uppercase tracking-wider text-slate-400">
            Dụ liệu đã trích xuất
          </h3>
          <pre className="max-h-72 overflow-auto rounded-lg bg-slate-950 p-2.5 text-[11px] text-slate-300">
            {JSON.stringify(doc.extracted_data, null, 2)}
          </pre>
        </>
      )}
    </div>
  );
}

function TextPreview({ doc }) {
  const [text, setText] = useState("");
  useEffect(() => {
    let alive = true;
    api.docText(doc.id)
      .then((d) => alive && setText(d.text_preview || ""))
      .catch(() => alive && setText("Không đọC được nội dung."));
    return () => { alive = false; };
  }, [doc.id]);
  return <div className="max-h-[560px] overflow-auto whitespace-pre-wrap rounded-lg border border-slate-700 bg-slate-950 p-3 font-mono text-xs text-slate-300">{text || "Đang tải nội dung…"}</div>;
}
