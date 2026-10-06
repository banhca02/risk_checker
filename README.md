# Import Document Risk Checker

Hệ thống hỗ trợ nhân viên xuất nhập khẩu đọc và kiểm tra tính nhất quán của
một bộ chứng từ lô hàng — **Commercial Invoice (CI), Packing List (PL),
Bill of Lading (BL)**: upload chứng từ, AI trích xuất thông tin, đối chiếu
cross-document theo 26 rule tất định, gắn cờ rủi ro và lưu lại toàn bộ lịch
các lần kiểm tra.

> **Disclaimer:** đây là cờ cảnh báo dựa trên quy tắc, **không phải kết luận
> gian lận**. Mọi trường hợp rủi ro cao đều cần người có thẩm quyền rà soát
> trước khi dùng bộ chứng từ cho nghiệp vụ tiếp theo.

![Stack](https://img.shields.io/badge/Python-3.11-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.142-009688) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791) ![React](https://img.shields.io/badge/React-18-61dafb) ![Tailwind](https://img.shields.io/badge/Tailwind-4-38bdf8)

---

## 1. Bài toán và hướng tiếp cận

Một bộ chứng từ xuất nhập khẩu gồm 3 loại: **Commercial Invoice**, **Packing
List**, **Bill of Lading**. Rủi ro không nằm ở việc đọc từng file, mà ở chỗ
**các thông tin phải khớp nhau giữa các chứng từ**: số invoice, thông tin
các bên, mô tả hàng, số lượng, trọng lượng, số container/seal, cảng xếp/dỡ,
ngày tháng — và cả **tính toán nội bộ** của từng chứng từ (đơn giá × khối
lượng = thành tiền, tổng dòng = tổng khai báo).

Nguyên tắc thiết kế của dự án:

1. **LLM chỉ lo trích xuất, không lo phán xét.** Mọi kết luận rủi ro đến từ
   code tất định trong `validation.py` (rule R01–R26). Nếu không làm vậy,
   kết quả sẽ thay đổi mỗi lần gọi API và không kiểm toán được.
2. **Không suy diễn dữ liệu vắng mặt.** Thiếu trường phải ra `None`, không
   phải `0`; thiếu dữ liệu cho một rule thì rule đó **skip**.
3. **Có bằng chứng kèm theo.** Mỗi giá trị quan trọng gắn `field_evidence`
   (số trang + trích dẫn nguyên văn) để người dùng tự kiểm chứng vị trí lỗi.
4. **Lịch sử bất biến.** Mỗi lần kiểm tra lưu thành một `audit_run` riêng,
   không ghi đè kết quả cũ; mở lại lần cũ không tốn phí gọi LLM.

Định nghĩa đầy đủ schema trích xuất và 26 rule (ma trận đối chiếu V01–V20 /
R01–R26, ngưỡng đã chốt) nằm ở
[`docs/SPEC_EXTRACTION_AND_VALIDATION.md`](docs/SPEC_EXTRACTION_AND_VALIDATION.md).

---

## 2. Tính năng

| Nhóm | Mô tả |
|---|---|
| Quản lý lô hồ sơ | Tạo job, upload nhiều chứng từ, xem lại lịch sử các lần đã kiểm tra |
| Đọc tài liệu | PDF nhiều trang, TXT, MD; tự nhận dạng loại chứng từ bằng LLM |
| Trích xuất | Pydantic schema riêng cho CI/PL/BL + bằng chứng theo trang |
| Kiểm tra chéo | 26 rule R01–R26: đối chiếu document-level, party, line-item, per-container, nội bộ CI/PL/BL, ngày tháng |
| Lịch sử kiểm tra | Mỗi lần chạy lưu 1 `audit_run`; mở lại lần cũ không tốn phí LLM |
| Giao diện | React + Tailwind: dashboard lịch sử, trang chi tiết job, xem PDF cạnh kết quả |

---

## 3. Kiến trúc

```
import_document_risk_checker/
├── app/
│   ├── main.py                  # Khởi tạo FastAPI, gắn router
│   ├── routers/
│   │   ├── jobs.py              # CRUD job + số liệu tổng hợp cho dashboard
│   │   ├── documents.py         # Upload, xem/xoá file, lấy text & extraction
│   │   ├── issues.py            # Xem & cập nhật trạng thái issue
│   │   └── extractation.py      # Luồng kiểm tra chính (compare) + lịch sử run
│   ├── services/
│   │   ├── document_reader.py   # Đọc text từ PDF, fallback OCR
│   │   ├── extractor.py         # Gọi LLM: phân loại + trích xuất theo schema
│   │   ├── schemas.py           # Pydantic model: CI / PL / BL (+ model con)
│   │   └── validation.py        # 26 rule R01–R26 tất định (không dùng LLM)
│   └── database/
│       ├── models.py            # SQLAlchemy ORM
│       ├── crud.py              # Truy vấn dữ liệu
│       └── connection.py        # Engine, Session, Base
├── frontend/                    # React 18 + Vite + Tailwind 4
├── samples/                     # 3 file PDF mẫu của đề bài (dữ liệu test)
├── tests/golden_check.py        # Golden test: R01–R26 trên bộ mẫu
├── docs/SPEC_..._VALIDATION.md  # Định nghĩa schema + ma trận rule đã chốt
├── schema.sql                   # Schema PostgreSQL
├── requirements.txt
└── .env.example
```

**Luồng kiểm tra một job:**

```
Upload file
   → document_reader đọc text (PDF embedded → OCR nếu cần)
   → extractor.detect_document_type()  phân loại: commercial_invoice / packing_list / bill_of_lading
   → extractor.extract_structured_data()  LLM trả JSON khớp Pydantic schema của loại đó
   → validation.validate_documents()  26 rule tất định R01–R26
   → lưu audit_run + validation_issues → trả kết quả về UI
```

---

## 4. Cài đặt và chạy

### Yêu cầu
- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- Gemini API key (miễn phí là đủ)

### Bước 1 — Database

```bash
createdb import_doc_audit
psql -d import_doc_audit -f schema.sql
```

File `schema.sql` tạo đủ 6 bảng: `processing_jobs`, `documents`,
`document_extractions`, `audit_runs`, `validation_issues`,
`validation_issue_documents`. CHECK constraint của `documents.document_type`
nhận `COMMERCIAL_INVOICE`, `PACKING_LIST`, `BILL_OF_LADING`, `OTHER`, `UNKNOWN`.

### Bước 2 — Backend

```bash
python -m venv .venv
# Windows:  .venv\Scripts\Activate.ps1
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

Tạo file cấu hình:

```bash
cp .env.example .env        # Windows: Copy-Item .env.example .env
```

Sửa `.env`:

```ini
DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/import_doc_audit
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-3.1-flash-lite
```

Chạy API:

```bash
uvicorn app.main:app --reload
```

- Swagger UI: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

### Bước 3 — Frontend

```bash
cd frontend
npm install
npm run dev
```

Giao diện: http://127.0.0.1:5173

Vite đã cấu hình proxy `/api` sang `127.0.0.1:8000`, nên **không cần cấu hình CORS**.

> Lưu ý: `DATABASE_URL` dùng scheme `postgresql+psycopg` (driver psycopg 3).
> Nếu dùng `postgresql+psycopg2` thì cần cài `psycopg2-binary` thay vì `psycopg`.

---

## 5. Hướng dẫn sử dụng

1. Mở trang chủ → bấm **Tạo Job mới**.
2. Ở trang chi tiết, upload 3 file PDF trong `samples/` (hoặc chứng từ thật).
3. Bấm **Kiểm tra Import Risk** để chạy trích xuất + kiểm tra chéo.
4. Xem kết quả ở khung giữa; từng finding kèm `evidence` trỏ đúng trang +
   trích dẫn nguyên văn trên file.
5. Bấm vào một chứng từ trong sidebar để xem PDF cạnh kết quả kiểm tra.
6. Bấm kiểm tra lần nữa để tạo lịch sử; mở lần cũ ở sidebar dưới để xem lại.

### Về chế độ xem lịch sử
Khi mở một lần kiểm tra cũ, hệ thống **chỉ cho phép xem**:
nút upload, xoá chứng từ và nút kiểm tra bị ẩn đi. Ràng buộc này được enforce ở
**backend** chứ không chỉ ở giao diện — các API ghi sẽ trả về `409 Conflict`
nếu request có kèm `run_id` của một lần đang xem lại.

---

## 6. API chính

| Method | Endpoint | Mô tả |
|---|---|---|
| `GET` | `/health` | Kiểm tra dịch vụ |
| `POST` | `/api/jobs` | Tạo lô hồ sơ mới |
| `GET` | `/api/jobs` | Danh sách job kèm số liệu tổng hợp (dashboard) |
| `GET` | `/api/jobs/{job_id}` | Chi tiết job |
| `DELETE` | `/api/jobs/{job_id}` | Xoá job (cascade toàn bộ dữ liệu) |
| `POST` | `/api/documents/upload` | Upload chứng từ (`multipart`) |
| `GET` | `/api/documents/by-job/{job_id}` | Danh sách chứng từ của job |
| `DELETE` | `/api/documents/{document_id}` | Xoá chứng từ + file vật lý |
| `GET` | `/api/documents/{document_id}/file` | Trả file (hiển thị inline) |
| `GET` | `/api/documents/{document_id}/text` | Text đã đọc + nguồn từng trang |
| `POST` | `/api/AI/jobs/{job_id}/compare` | **Chạy kiểm tra toàn bộ bộ chứng từ** |
| `GET` | `/api/AI/jobs/{job_id}/report` | Báo cáo (mặc định lần mới nhất) |
| `GET` | `/api/AI/jobs/{job_id}/report?run_id=` | Báo cáo của một lần cũ |
| `GET` | `/api/AI/jobs/{job_id}/runs` | Danh sách các lần đã kiểm tra |
| `GET` | `/api/AI/jobs/{job_id}/runs/{run_id}` | Chi tiết một lần kiểm tra |
| `GET` | `/api/issues/by-job/{job_id}` | Danh sách issue đã lưu |
| `PATCH` | `/api/issues/{issue_id}/status` | Đánh dấu đã xem / đã xử lý |

### Ví dụ: kiểm tra một job

```bash
curl -X POST http://127.0.0.1:8000/api/AI/jobs/<job_id>/compare
```

```json
{
  "status": "COMPLETED",
  "documents_used": ["commercial_invoice", "packing_list", "bill_of_lading"],
  "validation": {
    "risk_level": "HIGH",
    "summary": { "FAIL": 3, "REVIEW": 1, "PASS": 24 },
    "findings": [
      {
        "rule_id": "R03",
        "severity": "HIGH",
        "status": "FAIL",
        "message": "Số invoice không khớp sau chuẩn hóa: CI 'IV-2026-1008' vs PL 'IV-2026-100B'.",
        "documents": ["commercial_invoice", "packing_list"],
        "evidence": {
          "invoice_no": [
            { "document": "commercial_invoice", "value": "IV-2026-1008", "page": 1 },
            { "document": "packing_list", "value": "IV-2026-100B", "page": 1 }
          ]
        }
      }
    ]
  },
  "persisted_issue_ids": ["..."]
}
```

---

## 7. Các rule kiểm tra (R01–R26)

Toàn bộ rule nằm trong `app/services/validation.py`, **không dùng LLM**, nên
cho kết quả giống nhau mỗi lần chạy. Mỗi finding có `rule_id`, `severity`
(HIGH/MEDIUM/LOW), `status` (FAIL/REVIEW/PASS), `evidence`. Ngưỡng dung sai
và cách chuẩn hóa định nghĩa ở đầu file (dễ chỉnh): weight **0.1%**, tiền
±0.01, tên/địa chỉ review ở độ tương đồng **0.70**.

| Rule | Kiểm tra | Phạm vi | Mức |
|---|---|---|---|
| `R01` | Thiếu chứng từ CI / PL / BL trong bộ | Job | HIGH |
| `R02` | Thiếu trường bắt buộc của từng loại chứng từ | Document | HIGH/MEDIUM |
| `R03` | Số invoice CI ↔ `invoice_reference_no` PL | CI ↔ PL | HIGH |
| `R04` | Thông tin các bên (seller/buyer ↔ shipper/consignee) | CI ↔ PL ↔ BL | HIGH / MEDIUM+REVIEW |
| `R05` | Mô tả hàng hóa (thuộc tính quan trọng: quy cách, kích thước) | CI ↔ PL ↔ BL | HIGH / MEDIUM+REVIEW |
| `R06` | Tổng số lượng sau chuẩn hóa đơn vị | CI ↔ PL ↔ BL | HIGH |
| `R07` | Tổng net weight (dung sai 0.1%) | CI ↔ PL | HIGH |
| `R08` | Tổng gross weight (dung sai 0.1%) | CI ↔ PL ↔ BL | HIGH |
| `R09` | Danh sách container | PL ↔ BL | HIGH |
| `R10` | Seal number từng container (ghép exact → fallback theo seal) | PL ↔ BL | HIGH |
| `R11` | Gross weight từng container (dung sai 0.1%) | PL ↔ BL | HIGH |
| `R12` | Số lượng kiện từng container | PL ↔ BL | HIGH |
| `R13` | Cảng xếp hàng sau chuẩn hóa địa điểm | CI ↔ BL | HIGH |
| `R14` | Cảng dỡ hàng sau chuẩn hóa địa điểm | CI ↔ BL | HIGH |
| `R15` | `unit_price × basis = line_amount` (basis theo `price_basis`, ±0.01) | CI nội bộ | HIGH |
| `R16` | Σ `line_amount` = `total_amount` (±0.01) | CI nội bộ | HIGH |
| `R17` | Σ net weight dòng = tổng khai báo (0.1%) | CI nội bộ | HIGH |
| `R18` | Σ gross weight dòng = tổng khai báo — **skip nếu CI không có gross/dòng** | CI nội bộ | HIGH |
| `R19` | Σ dòng = totals (qty/net/gross) | PL nội bộ | HIGH |
| `R20` | Σ dòng theo container = Container Summary — skip nếu thiếu summary | PL nội bộ | HIGH |
| `R21` | Σ container = totals | BL nội bộ | HIGH |
| `R22` | Batch number của dòng ghép cặp | CI ↔ PL | HIGH |
| `R23` | Shipping marks sau chuẩn hóa ws/case | CI ↔ PL | MEDIUM |
| `R24` | Quan hệ ngày cấu hình: REL-1 `PL.date == CI.invoice_date`, REL-2 `BL.issue >= BL.shipped` (đã bỏ REL-3 theo chốt) | Date | MEDIUM |
| `R25` | Measurement (0.1%) — **chỉ khi cả PL và BL có dữ liệu** | PL ↔ BL | MEDIUM |
| `R26` | Dòng hàng thiếu / trùng khi ghép cặp | CI ↔ PL | HIGH |

**Mức rủi ro tổng thể** = `HIGH` nếu có bất kỳ finding `HIGH` ở trạng thái
`FAIL`/`REVIEW`; nếu không thì `MEDIUM` khi có `FAIL`/`REVIEW`, còn lại `LOW`.

### Ví dụ lỗi thực tế mà bộ mẫu bắt được

Bộ `samples/` cố tình chứa 4 lỗi seeded:

| Rule | Bằng chứng trong file mẫu |
|---|---|
| `R03` | CI `IV-2026-1008` (số 8) vs PL `IV-2026-100B` (chữ B) |
| `R04` | Buyer PL `GREENFIELD FOODS VIETNAM COMPANY LIMITED` gần giống CI/BL `GREENFIELD FOOD VIETNAM CO., LTD.` → REVIEW |
| `R08` | Tổng gross CI `231,000 KG` vs PL/BL `232,000 KG` (chênh 0.43% > 0.1%) |
| `R09` | Container PL `OOLU7654321` vs BL `OOLU7654327` (số cuối 1 ↔ 7) |

---

## 8. Schema database

| Bảng | Mô tả |
|---|---|
| `processing_jobs` | Mỗi lô hồ sơ. Có cache `risk_level`, `validation_summary` của lần chạy mới nhất để dashboard không phải join |
| `documents` | File đã upload kèm loại (`COMMERCIAL_INVOICE` / `PACKING_LIST` / `BILL_OF_LADING`), số trang, `text_preview`, `page_sources` |
| `document_extractions` | Kết quả trích xuất + evidence của từng chứng từ |
| `audit_runs` | **Lịch sử các lần kiểm tra.** Mỗi lần bấm nút tạo 1 dòng, có `run_number` tăng dần + `document_snapshot` |
| `validation_issues` | Issue phát hiện được, gắn `audit_run_id` để biết thuộc lần nào |
| `validation_issue_documents` | Quan hệ nhiều-nhiều issue ↔ chứng từ |

### Vì sao cần bảng `audit_runs`
Nếu chỉ lưu kết quả mới nhất trên `processing_jobs`, mỗi lần kiểm tra sẽ
**ghi đè** lần trước và người dùng không xem lại được kết quả cũ — cũng tốn
tiền gọi LLM lần nữa. `audit_runs` giữ lại từng lần, kèm
`document_snapshot` (tên + loại chứng từ tại thời điểm chạy) để lịch sử vẫn
đọc được ngay cả khi file gốc đã bị xoá.

---

## 9. Quyết định thiết kế

**Tách LLM khỏi logic kiểm tra.** LLM chỉ trả về JSON có cấu trúc; việc so
số, so tên, so container... do code tất định thực hiện — kết quả tái lập và
giải thích được.

**Schema CI/PL/BL tách riêng, `CommonDocumentData` thu gọn.** Ba loại chứng
từ có cấu trúc rất khác nhau (CI có pricing, PL có container summary, BL có
containers) và cả tên field các bên cũng khác theo `FIELD_MAPPING`
(`seller_name` vs `shipper_name`), nên base class chỉ giữ phần chung thật
sự: `document_type`, `field_evidence`, `extraction_notes`. Nhờ đó JSON
schema gửi lên LLM không chứa field vô nghĩa cho từng loại chứng từ.

**Cache kết quả trích xuất.** `extractor` tách riêng phần đọc file và phần
gọi LLM; khi bấm kiểm tra lần 2 hệ thống chỉ chạy lại rule, không gọi lại
LLM (trừ khi có file mới).

**Ghép cặp container theo 2 bước.** Match exact theo `container_no`, sau đó
fallback theo `seal_no` — để lỗi sai số container (R09) không làm hỏng hết
đánh giá seal/gross/qty từng container (R10–R12).

**Ràng buộc ở tầng API.** Chế độ chỉ đọc khi xem lịch sử được enforce bằng
`run_id` và trả `409`, thay vì chỉ ẩn nút trên giao diện.

---

## 10. Hạn chế đã biết

- Chưa hỗ trợ ảnh (JPG/PNG) dù đề bài cho phép; `document_reader` mới nhận PDF/TXT/MD.
- OCR cần cài thêm Tesseract ở mức hệ điều hành, không chỉ cài `pytesseract`.
- So khớp tên bên dùng chuẩn hóa + `difflib` (ngưỡng 0.70), chỉ xử lý được
  các hậu tố pháp nhân trong danh sách cấu hình (`co, ltd, limited, ...`).
- Khi hồ sơ có **dưới 2 loại chứng từ khác nhau**, hệ thống từ chối so sánh
  và báo rõ loại còn thiếu (`R01` vẫn báo thiếu CI/PL/BL).
- V20 (`trade_term` / `freight_term`) **cố ý chưa kiểm tra** — theo ma trận,
  chỉ kiểm tra khi có quy tắc nghiệp vụ được định nghĩa; sẽ thêm khi có yêu cầu.
- Chưa có phân quyền người dùng và xác thực.
- Validation xử lý bằng `Decimal`, nhưng dữ liệu LLM lưu vào DB vẫn là JSON number (float).

---

## 12. Công nghệ sử dụng

**Backend:** Python 3.11, FastAPI, SQLAlchemy 2.x, Pydantic v2, PyMuPDF,
OpenAI SDK (trỏ sang endpoint tương thích của Gemini), psycopg 3

**Frontend:** React 18, React Router 6, Vite 5, Tailwind CSS 4

[![Demo System Video](https://img.youtube.com/vi/CoX7NPkcJwU/maxresdefault.jpg)](https://www.youtube.com/watch?v=CoX7NPkcJwU)



