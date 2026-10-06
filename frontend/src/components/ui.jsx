const TONE = {
  HIGH: "bg-red-500/15 text-red-300",
  MEDIUM: "bg-amber-500/15 text-amber-300",
  LOW: "bg-emerald-500/15 text-emerald-300",
  CRITICAL: "bg-red-700/25 text-red-200",
  INFO: "bg-sky-500/15 text-sky-300",
  PENDING: "bg-slate-500/15 text-slate-300",
  PROCESSING: "bg-slate-500/15 text-slate-300",
  COMPLETED: "bg-emerald-500/15 text-emerald-300",
  FAILED: "bg-red-500/15 text-red-300",
  OPEN: "bg-sky-500/15 text-sky-300",
  REVIEWED: "bg-slate-500/15 text-slate-300",
  RESOLVED: "bg-emerald-500/15 text-emerald-300",
  DISMISSED: "bg-slate-600/15 text-slate-400",
};

const VALUE = {
  HIGH: "text-red-400",
  MEDIUM: "text-amber-400",
  LOW: "text-emerald-400",
};

const SEV_BORDER = {
  HIGH: "border-l-red-500",
  MEDIUM: "border-l-amber-500",
  LOW: "border-l-emerald-500",
  CRITICAL: "border-l-red-700",
  INFO: "border-l-sky-500",
};

export function Badge({ value, fallback = "—" }) {
  if (!value) {
    return (
      <span className="inline-block rounded-full border border-slate-700 px-2.5 py-0.5 text-[11px] text-slate-400">
        {fallback}
      </span>
    );
  }
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-[11px] font-bold tracking-wide ${
        TONE[value] || "bg-slate-500/15 text-slate-300"
      }`}
    >
      {value}
    </span>
  );
}

export function Stat({ label, value, tone }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 px-4 py-2.5 min-w-24">
      <div className="text-[11px] uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${VALUE[tone] || "text-slate-100"}`}>{value}</div>
    </div>
  );
}

export function Alert({ kind = "info", children }) {
  if (!children) return null;
  const tones = {
    error: "bg-red-500/10 border-red-800 text-red-300",
    warn: "bg-amber-500/10 border-amber-700 text-amber-200",
    info: "bg-sky-500/10 border-sky-800 text-sky-200",
  };
  return (
    <div className={`mb-3 rounded-md border px-3.5 py-2.5 text-[13px] ${tones[kind]}`}>
      {children}
    </div>
  );
}

export function Empty({ icon = "📄", title, hint, action }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="px-6 py-14 text-center text-slate-400">
        <div className="mb-3 text-4xl">{icon}</div>
        <div className="text-[15px] text-slate-100">{title}</div>
        {hint && <div className="mt-1.5 text-[13px]">{hint}</div>}
        {action && <div className="mt-4">{action}</div>}
      </div>
    </div>
  );
}

export function Spinner() {
  return (
    <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
  );
}

export function Finding({ severity, rule, message, extra, children }) {
  return (
    <div
      className={`mb-2 rounded-md border border-slate-800 border-l-[3px] bg-slate-800/50 px-3.5 py-2.5 ${
        SEV_BORDER[severity] || "border-l-slate-600"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-slate-400">{rule}</span>
        <span className="flex items-center gap-1.5">{extra}</span>
      </div>
      <div className="mt-1">{message}</div>
      {children}
    </div>
  );
}
