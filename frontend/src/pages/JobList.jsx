import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, formatDate, shortId } from "../api.js";
import { Alert, Badge, Empty } from "../components/ui.jsx";

export default function JobList() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);

  async function load() {
    try {
      setError("");
      setJobs(await api.listJobs());
    } catch (e) {
      setError(e.message || "Không tải được danh sách job");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function createJob(e) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setCreating(true);
    try {
      const job = await api.createJob(trimmed);
      setShowModal(false);
      setName("");
      navigate(`/jobs/${job.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-[19px] font-semibold">Lịch sử kiểm tra bộ chứng từ</h2>
          <div className="mt-1 text-[13px] text-slate-400">
            {jobs.length} bộ chứng từ đã xử lý • click vào một dòng để xem báo cáo
          </div>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="rounded-md bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
        >
          + Tạo Job mới
        </button>
      </div>

      <Alert kind="error">{error}</Alert>

      {loading ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">Đang tải…</div>
      ) : jobs.length === 0 ? (
        <Empty
          icon="🗂"
          title="Chưa có bộ chứng từ nào"
          hint="Bấm “Tạo Job mới” để bắt đầu kiểm tra."
          action={
            <button
              onClick={() => setShowModal(true)}
              className="rounded-md bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-blue-500"
            >
              + Tạo Job mới
            </button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                {["Mã / Tên Job", "Thời gian tạo", "Số chứng từ",
                  "Mức độ rủi ro", "Trạng thái", "Lỗi", "Thao tác"].map((h) => (
                  <th
                    key={h}
                    className={`border-b border-slate-800 bg-slate-800/60 px-4 py-3 text-[11px] uppercase tracking-wider text-slate-400 ${
                      h === "Thao tác" ? "text-right" : "text-left"
                    }`}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr
                  key={job.id}
                  onClick={() => navigate(`/jobs/${job.id}`)}
                  className="cursor-pointer border-b border-slate-800 last:border-0 hover:bg-slate-800/40"
                >
                  <td className="px-4 py-3">
                    <div className="font-semibold">{job.name || "Không tên"}</div>
                    <div className="font-mono text-xs text-slate-400">{shortId(job.id)}</div>
                  </td>
                  <td className="px-4 py-3">{formatDate(job.created_at)}</td>
                  <td className="px-4 py-3">{job.document_count}</td>
                  <td className="px-4 py-3">
                    <Badge value={job.risk_level} fallback="Chưa kiểm tra" />
                  </td>
                  <td className="px-4 py-3"><Badge value={job.status} /></td>
                  <td className="px-4 py-3">
                    {job.issue_count > 0 ? (
                      <span className="font-semibold text-amber-300">{job.issue_count}</span>
                    ) : (
                      <span className="text-slate-400">0</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={(e) => { e.stopPropagation(); navigate(`/jobs/${job.id}`); }}
                      className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
                    >
                      Xem chi tiết
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowModal(false)}>
          <div className="w-[420px] rounded-xl border border-slate-800 bg-slate-900 p-5" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-3.5 text-[15px] font-semibold">Tạo Job mới</h3>
            <form onSubmit={createJob}>
              <input
                autoFocus
                placeholder="VD: Lô hàng xuất khẩu tháng 10"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100 outline-none focus:border-blue-500"
              />
              <div className="mt-4 flex justify-end gap-2.5">
                <button type="button" onClick={() => setShowModal(false)}
                  className="rounded-md border border-slate-700 px-3.5 py-2 text-[13px] hover:bg-slate-800">
                  Hủy
                </button>
                <button disabled={creating || !name.trim()}
                  className="rounded-md bg-blue-600 px-3.5 py-2 text-[13px] font-semibold text-white hover:bg-blue-500 disabled:opacity-50">
                  {creating ? "Đang tạo…" : "Tạo"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
