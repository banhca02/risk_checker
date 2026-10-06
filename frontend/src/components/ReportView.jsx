import { Alert, Badge, Finding } from "./ui.jsx";

const SEV_ORDER = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3, INFO: 4 };

export default function ReportView({ report }) {
  if (!report) return null;

  const findings = [...(report.findings || [])].sort(
    (a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9)
  );

  return (
    <>
      {(report.warnings || []).map((w, i) => (
        <Alert key={i} kind="warn">{w}</Alert>
      ))}

      {(report.unsupported_documents || []).length > 0 && (
        <Alert kind="warn">
          Bỏ qua {report.unsupported_documents.length} tài liệu không thuộc loại được hỗ trợ:{" "}
          {report.unsupported_documents.map((d) => d.filename).join(", ")}
        </Alert>
      )}

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <h2 className="mb-3 text-[15px] font-semibold">Kết quả kiểm tra ({findings.length})</h2>
        {findings.length === 0 ? (
          <div className="text-slate-400">Không có rule nào được kích hoạt.</div>
        ) : (
          findings.map((f, i) => {
            const evidence =
              f.evidence && Object.keys(f.evidence).length
                ? f.evidence
                : f.compared_values && Object.keys(f.compared_values).length
                ? f.compared_values
                : null;
            return (
              <Finding
                key={i}
                severity={f.severity}
                rule={f.rule_id || f.rule_code}
                message={f.msg || f.message}
                extra={<Badge value={f.severity} />}
              >
                {Array.isArray(f.documents) && f.documents.length > 0 && (
                  <div className="mt-1.5 text-xs text-slate-400">
                    Chứng từ liên quan: {f.documents.join(", ")}
                  </div>
                )}
                {evidence && (
                  <pre className="mt-2 max-h-40 overflow-auto rounded bg-slate-950 p-2 text-[11px] text-slate-400">
                    {JSON.stringify(evidence, null, 2)}
                  </pre>
                )}
              </Finding>
            );
          })
        )}
      </div>

      {report.disclaimer && (
        <div className="mt-3 rounded-xl border border-slate-800 bg-slate-900 p-4 text-[12.5px] italic text-slate-400">
          {report.disclaimer}
        </div>
      )}
    </>
  );
}
