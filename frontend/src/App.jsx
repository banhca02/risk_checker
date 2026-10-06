import { Routes, Route, Link, useLocation } from "react-router-dom";
import JobList from "./pages/JobList.jsx";
import JobDetail from "./pages/JobDetail.jsx";

export default function App() {
  const { pathname } = useLocation();

  return (
    <div className="flex min-h-screen flex-col bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-800 bg-slate-900 px-6 py-3.5">
        <div>
          <h1 className="text-[17px] font-semibold">
            <Link to="/">Import Document Risk Checker</Link>
          </h1>
          <div className="mt-0.5 text-xs text-slate-400">
            Kiểm tra tính nhất quán bộ chứng từ xuất nhập khẩu (CI / PL / BL)
          </div>
        </div>
        {pathname !== "/" && (
          <Link
            to="/"
            className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800"
          >
            Tất cả job
          </Link>
        )}
      </header>

      <main className="flex-1 px-6 py-6">
        <Routes>
          <Route path="/" element={<JobList />} />
          <Route path="/jobs/:jobId" element={<JobDetail />} />
        </Routes>
      </main>
    </div>
  );
}
