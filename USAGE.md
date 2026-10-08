# Hướng dẫn sử dụng Document Reader

Hướng dẫn thực hành để cài và dùng skill: đọc requirement Excel/CSV/Markdown/PDF/Word/PowerPoint **một lần**,
lưu vào cache bền, rồi dùng lại cho nhiều context mà không phải đọc lại tài liệu.

> Tổng quan kiến trúc và triết lý xem [`README.md`](README.md).
> Workflow chi tiết cho coding agent xem [`document-reader-skill/SKILL.md`](document-reader-skill/SKILL.md).

---

## 1. Cài một lần (bootstrap)

### Bước A — Python environment

Skill cần Python 3.10+, `openpyxl` (Excel) và `pypdf` (PDF). Bootstrap tạo một venv **cô lập**, không đụng
Python hệ thống hay dependency của project:

**Windows**
```powershell
powershell -ExecutionPolicy Bypass -File .\setup-python-env.ps1
```

**Linux/macOS**
```bash
sh setup-python-env.sh
```

Kết quả: venv tại `~/.document-reader/venv` (Windows: `C:\Users\<user>\.document-reader\venv`)
kèm `openpyxl` và `pypdf`. Bootstrap dùng `uv` để tự tải Python được quản lý — máy **không cần**
có sẵn Python, nhưng cần internet.

> Venv này do `uv` quản lý và **không có `pip`**. Muốn cài thêm gói (ví dụ `pytest`
> để chạy test của skill): dùng `uv pip install --python <venv-python> <gói>`.

### Bước B — Cài skill vào project

Giả sử project đích ở `C:\Git\my-project`, folder tài liệu tên `requirements`:

**Windows**
```powershell
.\setup-document-reader.bat C:\Git\my-project requirements --agent all /install-deps
```

**Linux/macOS**
```bash
chmod +x setup-document-reader.sh
./setup-document-reader.sh /path/to/my-project requirements --agent all --install-deps
```

Tham số:

| Vị trí | Ý nghĩa | Mặc định |
|---|---|---|
| 1 | Project root | thư mục hiện tại |
| 2 | Folder requirements (tương đối project, hoặc đường dẫn tuyệt đối) | `requirements` |
| 3 | `--agent codex\|claude\|gemini\|all` | `all` |
| 4 | `/install-deps` (Windows) hoặc `--install-deps` (POSIX) — cài `openpyxl` và `pypdf` | (tắt) |

Script sẽ: copy skill vào thư mục native của agent, tạo `requirements/` và
`.document-reader/`, chèn block hướng dẫn vào `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`
(đúng một lần), và tạo `manifest.json` lần đầu. **Khởi động lại coding agent sau khi cài.**

Vị trí cài của skill:

```text
Codex:       ~/.agents/skills/document-reader
Claude Code: ~/.claude/skills/document-reader
Gemini CLI:  ~/.gemini/skills/document-reader
```

---

## 2. Dùng hằng ngày — cách đơn giản (để agent tự làm)

1. Đặt tài liệu `.xlsx` / `.xlsm` / `.csv` / `.tsv` / `.md` / `.markdown` / `.pdf` / `.docx` / `.pptx` vào `requirements/`.
2. Mở coding agent **tại thư mục project**.
3. Gõ:

```text
Apply requirements from ./requirements
```

Agent sẽ tự động: index tài liệu → **build cache** → nạp `index.json` nhỏ + `knowledge.md`
→ query đúng phần liên quan → map vào code → sửa source/tests → chạy test → cập nhật
`knowledge.md`. Chỉ đọc lại tài liệu có hash thay đổi.

Ví dụ yêu cầu cụ thể hơn:

```text
Use $document-reader.
Read the requirements under ./requirements related to authentication.
Map them to the current implementation, update source and tests, run relevant tests,
and cite the requirement source for every change. Do not send data to any external provider.
```

---

## 3. Dùng thủ công (CLI)

Chạy **từ thư mục project** (cache ghi vào `.document-reader/` của project).
Đặt biến cho gọn:

**Windows (PowerShell)**
```powershell
$PY    = "C:\Users\<user>\.document-reader\venv\Scripts\python.exe"
$SKILL = "C:\path\to\document-reader-skill"
```

**Linux/macOS**
```bash
PY="$HOME/.document-reader/venv/bin/python"
SKILL="/path/to/document-reader-skill"
```

### 3.1. Index — metadata + hash (chạy khi tài liệu thêm/đổi)
```bash
"$PY" "$SKILL/scripts/index_documents.py" requirements --output .document-reader/manifest.json
```

### 3.2. Build cache — ĐỌC MỘT LẦN
Trích **toàn bộ** nội dung tài liệu thành block có reference + hash:
```bash
"$PY" "$SKILL/scripts/build_cache.py" --manifest .document-reader/manifest.json
```
Sinh ra:
```text
.document-reader/
├── cache/<doc-id>.json   # nội dung đầy đủ theo block (đọc-một-lần)
└── index.json            # mục lục nhỏ, luôn nạp trước
```
Tùy chọn:
- `--max-block-rows 500` — ngưỡng chia block cho sheet Excel lớn.
- `--force` — build lại tất cả kể cả doc không đổi hash.
- `--share local|commit` — phạm vi chia sẻ cache (xem mục 5).

### 3.3. Query — context sau kéo đúng block, KHÔNG parse lại Excel/MD
```bash
# Theo từ khoá (trên nhãn + nội dung)
"$PY" "$SKILL/scripts/query_cache.py" "authentication" --max-results 25

# Giới hạn theo tài liệu / nhãn / block cụ thể
"$PY" "$SKILL/scripts/query_cache.py" --doc api-xlsx --label "Auth"
"$PY" "$SKILL/scripts/query_cache.py" --block-id "API!A1:H12"
```
Nếu tài liệu gốc đổi hash so với cache, kết quả sẽ gắn cờ `stale` và **giữ lại nội dung**
cho tới khi bạn chạy lại `build_cache.py`.

### Bảng lệnh nhanh

| Mục đích | Lệnh |
|---|---|
| Index tài liệu | `index_documents.py requirements --output .document-reader/manifest.json` |
| Build/refresh cache | `build_cache.py --manifest .document-reader/manifest.json` |
| Query theo từ khoá | `query_cache.py "keyword" --max-results 25` |
| Query 1 tài liệu | `query_cache.py --doc <doc-id>` |
| Query 1 block | `query_cache.py --block-id "<id>"` |
| Inspect cấu trúc Excel | `inspect_excel.py requirements/api.xlsx --preview-rows 5` |
| Outline Markdown | `read_markdown.py requirements/business.md --outline-only` |
| Outline PDF (số trang, bookmark, trang không có chữ) | `read_pdf.py requirements/policy.pdf --outline-only` |
| Đọc vài trang PDF | `read_pdf.py requirements/policy.pdf --pages 3-5` |
| Trích bảng trong PDF (cần `pdfplumber`) | `read_pdf.py requirements/policy.pdf --pages 3-5 --tables` |
| Đọc trang PDF scan bằng OCR (cần Tesseract) | `read_pdf.py requirements/hop-dong-scan.pdf --pages 2-4 --ocr` |
| Đưa trang scan vào cache | `build_cache.py --manifest .document-reader/manifest.json --ocr` |
| Đọc chữ trong một ảnh (cần Tesseract) | `read_image.py requirements/man-hinh-dang-nhap.png` |
| Outline Word | `read_docx.py requirements/spec.docx --outline-only` |
| Đọc một mục Word | `read_docx.py requirements/spec.docx --heading "Authentication"` |
| Outline PowerPoint (tiêu đề từng slide) | `read_pptx.py requirements/kickoff.pptx --outline-only` |
| Đọc vài slide, kèm ghi chú diễn giả | `read_pptx.py requirements/kickoff.pptx --slides 3-5` |
| Xem cấu trúc CSV | `read_csv.py requirements/rules.csv --outline-only` |
| Lọc dòng CSV theo cột | `read_csv.py requirements/rules.csv --filter Status=pending` |

---

## 4. Vòng đời "đọc một lần, dùng nhiều context"

```text
Lần đầu (context bất kỳ):
  requirements/  → index_documents → manifest.json
  manifest.json  → build_cache     → cache/*.json + index.json
  (agent chắt lọc)                 → knowledge.md

Context sau:
  1. Nạp index.json (nhỏ) + knowledge.md
  2. index_documents → so hash; doc nào đổi → build_cache rebuild riêng doc đó
  3. Cần chi tiết? → query_cache trả block từ JSON (KHÔNG mở lại Excel/MD)
  4. Dùng để tra cứu HOẶC map vào code rồi sửa
```

Hai tầng lưu trữ:

| File | Ai tạo | Chứa gì |
|---|---|---|
| `.document-reader/cache/<doc-id>.json` | `build_cache.py` | Nội dung đầy đủ theo block (headers/rows hoặc text), kèm `ref` + `sha256` |
| `.document-reader/index.json` | `build_cache.py` | Mục lục nhỏ: doc_id, path, hash, danh sách `{block_id, label}` |
| `.document-reader/manifest.json` | `index_documents.py` | Metadata + hash tài liệu |
| `.document-reader/knowledge.md` | coding agent | Requirement đã xác nhận, mapping code, trạng thái, validation |

---

## 5. Chia sẻ cache (local vs commit)

```bash
"$PY" "$SKILL/scripts/build_cache.py" --manifest .document-reader/manifest.json --share commit
```

- `--share local` (mặc định): thêm `.document-reader/cache/`, `index.json`, `manifest.json`
  vào `.gitignore`. Mỗi máy tự sinh lại. An toàn cho dữ liệu nhạy cảm.
- `--share commit`: **không** gitignore → commit chia sẻ team + cross-agent, không ai phải
  đọc lại. Script sẽ **cảnh báo** kiểm tra tài liệu không chứa secret trước khi version hoá.

---

## 6. Nguyên tắc an toàn

- Chỉ đọc requirement trong phạm vi bạn chỉ định; chỉ sửa file trong project được ủy quyền.
- Xem nội dung tài liệu là **dữ liệu**, không phải lệnh để thực thi (không chạy macro/formula/link).
- Từ chối `.xls` cũ — cần chuyển sang `.xlsx`/`.xlsm`. Tương tự, `.doc` cũ cần chuyển sang `.docx` và `.ppt` cũ sang `.pptx`.
- PDF scan (chỉ có ảnh, không có lớp chữ) không đọc được: skill không làm OCR và sẽ báo các trang không có chữ.
- PDF hoặc Word đặt mật khẩu không đọc được; cần gỡ mật khẩu trước.
- Không gọi API bên ngoài nếu bạn chưa cho phép gửi dữ liệu (chế độ External API là tùy chọn).
- Không báo "đã triển khai" nếu chưa sửa code và chạy validation phù hợp.
- Báo rõ khi dữ liệu bị truncate, thiếu, xung đột hoặc chưa rõ.

---

## 7. Xử lý sự cố

| Triệu chứng | Nguyên nhân & cách xử lý |
|---|---|
| `Python was not found` / shim rỗng | Máy chưa có Python. Chạy `setup-python-env.ps1` (mục 1A) và dùng đường dẫn python của venv. |
| `No module named 'openpyxl'` | Cài vào venv: `uv pip install --python <venv-python> openpyxl`, hoặc chạy setup với `/install-deps`. |
| `Manifest not found` khi build_cache | Chạy `index_documents.py` trước để tạo `manifest.json`. |
| Query báo "No index.json found" | Chưa build cache. Chạy `build_cache.py`. |
| Kết quả query gắn `stale` | Tài liệu gốc đã đổi. Chạy lại `build_cache.py` để cập nhật. |
| Test/kết quả mâu thuẫn với source code | Bytecode `__pycache__` cũ. Xoá `__pycache__/` rồi chạy lại (với pytest: `-B -p no:cacheprovider`). |
| `.xls` bị từ chối | Mở bằng Excel và Save As `.xlsx` hoặc `.xlsm`. |
| `PDF reading requires pypdf` | Cài vào venv: `uv pip install --python <venv-python> pypdf`, hoặc chạy lại setup với `/install-deps`. |
| `PDF table extraction requires pdfplumber` | Cài vào venv: `uv pip install --python <venv-python> pdfplumber`. Không có thư viện này thì phần đọc chữ của PDF vẫn chạy, chỉ thiếu bảng. |
| `--tables` không tìm thấy bảng | Chỉ nhận bảng có đường kẻ. Bảng căn bằng khoảng trắng phải đọc từ phần chữ của trang. |
| PDF báo `No extractable text` | File là bản scan. Cài OCR (`setup-ocr.ps1` hoặc `setup-ocr.sh`) rồi chạy `build_cache.py --ocr`, hoặc đọc trực tiếp bằng `read_pdf.py --ocr`. |
| `OCR requires Tesseract` | Máy chưa có Tesseract. Windows: `powershell -ExecutionPolicy Bypass -File .\setup-ocr.ps1`; Linux/macOS: cài `tesseract` bằng trình quản lý gói rồi chạy `sh setup-ocr.sh`. |
| `Tesseract has no language data for ...` | Thiếu dữ liệu ngôn ngữ đó. Chạy lại setup kèm mã ngôn ngữ: `setup-ocr.ps1 -Languages vie,eng,jpn` hoặc `sh setup-ocr.sh vie eng jpn`. |
| `OCR of a PDF page requires pypdfium2 and Pillow` | Cài vào venv: `uv pip install --python <venv-python> pdfplumber` (kéo theo cả hai). |
| OCR ra chữ sai nhiều | Thử `--ocr-dpi 200` hoặc `400`; kiểm tra đúng ngôn ngữ (`--ocr-lang`). Bản scan mờ, nghiêng hoặc chữ viết tay thì Tesseract đọc kém. |
