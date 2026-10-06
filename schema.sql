
-- =====================================================
-- 1. PROCESSING_JOBS
-- Mỗi job đại diện cho một lô chứng từ (CI/PL/BL) cần kiểm tra
-- =====================================================

CREATE TABLE processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    name VARCHAR(255) NOT NULL,

    status VARCHAR(30) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN (
            'PENDING',
            'PROCESSING',
            'COMPLETED',
            'FAILED'
        )),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    CHECK (
        completed_at IS NULL OR completed_at >= created_at
    )
);

-- =====================================================
-- 2. DOCUMENTS
-- Danh sách chứng từ (CI/PL/BL) thuộc từng bộ hồ sơ
-- =====================================================

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    job_id UUID NOT NULL
        REFERENCES processing_jobs(id)
        ON DELETE CASCADE,

    filename VARCHAR(255) NOT NULL,

    document_type VARCHAR(50) NOT NULL
        CHECK (document_type IN (
            'COMMERCIAL_INVOICE',
            'PACKING_LIST',
            'BILL_OF_LADING',
            'OTHER',
            'UNKNOWN'
        )),

    file_path TEXT NOT NULL,

    page_count INTEGER
        CHECK (page_count IS NULL OR page_count > 0),

    read_status VARCHAR(30) NOT NULL DEFAULT 'PENDING'
        CHECK (read_status IN (
            'PENDING',
            'SUCCESS',
            'FAILED'
        )),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- SHA-256 cua file goc, dung cho cache / dedup.
    file_sha256 VARCHAR(64),

    -- Doan text dau tien + nguon tung trang, phuc vu preview.
    text_preview TEXT,
    page_sources JSONB
);


-- =====================================================
-- 3. DOCUMENT_EXTRACTIONS
-- Lưu kết quả trích xuất AI theo từng chứng từ
-- =====================================================

CREATE TABLE document_extractions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    document_id UUID NOT NULL
        REFERENCES documents(id)
        ON DELETE CASCADE,

    extracted_data JSONB NOT NULL DEFAULT '{}'::JSONB,

    evidence JSONB NOT NULL DEFAULT '[]'::JSONB,

    extraction_status VARCHAR(30) NOT NULL DEFAULT 'PENDING'
        CHECK (extraction_status IN (
            'PENDING',
            'SUCCESS',
            'PARTIAL',
            'FAILED'
        )),

    model_name VARCHAR(100),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =====================================================
-- 5. AUDIT_RUNS (lịch sử các lần kiểm tra)
-- Mỗi lần bấm "Kiểm tra Import Risk" tạo 1 dòng,
-- nên có thể xem lại kết quả của các lần trước
-- mà không cần chạy lại AI.
-- =====================================================

CREATE TABLE audit_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    job_id UUID NOT NULL
        REFERENCES processing_jobs(id)
        ON DELETE CASCADE,

    run_number INTEGER NOT NULL,

    risk_level VARCHAR(20)
        CHECK (risk_level IN ('HIGH', 'MEDIUM', 'LOW', NULL)),

    summary JSONB NOT NULL DEFAULT '{}'::JSONB,
    report  JSONB NOT NULL DEFAULT '{}'::JSONB,

    documents_used       JSONB DEFAULT '[]'::JSONB,
    unsupported_documents JSONB DEFAULT '[]'::JSONB,
    warnings             JSONB DEFAULT '[]'::JSONB,

    -- Chụp lại tên/loại chứng từ tại thời điểm chạy,
    -- để lịch sử vẫn đọc được sau khi file đã bị xoá.
    document_snapshot JSONB DEFAULT '[]'::JSONB,

    model_name VARCHAR(100),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (job_id, run_number)
);


-- =====================================================
-- 4. VALIDATION_ISSUES
-- Các lỗi và cảnh báo do Validation Engine phát hiện
-- =====================================================

CREATE TABLE validation_issues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    job_id UUID NOT NULL
        REFERENCES processing_jobs(id)
        ON DELETE CASCADE,

    -- Lần compare sinh ra issue này (NULL nếu tạo tay).
    audit_run_id UUID
        REFERENCES audit_runs(id)
        ON DELETE CASCADE,

    rule_code VARCHAR(100) NOT NULL,

    severity VARCHAR(20) NOT NULL
        CHECK (severity IN (
            'LOW',
            'MEDIUM',
            'HIGH',
            'CRITICAL'
        )),

    message TEXT NOT NULL,

    compared_values JSONB NOT NULL DEFAULT '{}'::JSONB,

    evidence JSONB NOT NULL DEFAULT '[]'::JSONB,

    status VARCHAR(20) NOT NULL DEFAULT 'OPEN'
        CHECK (status IN (
            'OPEN',
            'REVIEWED',
            'RESOLVED',
            'DISMISSED'
        )),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =====================================================
-- 5. VALIDATION_ISSUE_DOCUMENTS
-- Một cảnh báo có thể liên quan đến nhiều chứng từ
-- =====================================================

CREATE TABLE validation_issue_documents (
    issue_id UUID NOT NULL
        REFERENCES validation_issues(id)
        ON DELETE CASCADE,

    document_id UUID NOT NULL
        REFERENCES documents(id)
        ON DELETE CASCADE,

    PRIMARY KEY (issue_id, document_id)
);


-- =====================================================
-- 8. INDEXES
-- Tối ưu các truy vấn thường gặp
-- =====================================================

CREATE INDEX idx_jobs_status_created
    ON processing_jobs(status, created_at DESC);

CREATE INDEX idx_documents_job_id
    ON documents(job_id);

CREATE INDEX idx_documents_type
    ON documents(document_type);

CREATE INDEX idx_extractions_document_created
    ON document_extractions(document_id, created_at DESC);

CREATE INDEX idx_extractions_data
    ON document_extractions USING GIN (extracted_data);

CREATE INDEX idx_issues_job_status
    ON validation_issues(job_id, status);

CREATE INDEX idx_issues_severity
    ON validation_issues(severity);

CREATE INDEX idx_issue_documents_document
    ON validation_issue_documents(document_id);

-- =====================================================
-- 9. CỘT KẾT QUẢ KIỂM TOÁN TRÊN JOBS
-- Cache của lần chạy MỚI NHẤT, dùng cho dashboard
-- để không phải join vào audit_runs mỗi lần list job.
-- =====================================================

ALTER TABLE processing_jobs
    ADD COLUMN risk_level         VARCHAR(20),
    ADD COLUMN validation_summary JSONB,
    ADD COLUMN validation_report  JSONB,
    ADD COLUMN compared_at        TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_jobs_created
    ON processing_jobs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_risk
    ON processing_jobs(risk_level);

CREATE INDEX IF NOT EXISTS idx_audit_runs_job
    ON audit_runs(job_id, run_number DESC);

CREATE INDEX IF NOT EXISTS idx_issues_run
    ON validation_issues(audit_run_id);
