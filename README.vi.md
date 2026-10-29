# Document Reader Skill

[![CI](https://github.com/vannt-dev/document-reader-skill-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/vannt-dev/document-reader-skill-ai/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

English: [README.md](README.md)

Skill dành cho coding agent đọc tài liệu requirement (Word, PDF, Excel,
PowerPoint, Markdown và các định dạng khác) trong một thư mục local, chỉ phần cần
dùng, để agent cập nhật source code và tests của project hiện tại. Ngoài việc
đọc nội dung, skill làm thêm hai việc:

- **Bằng chứng lấy từ cache ghi rõ đúng block mà nó được lấy ra.** Tài liệu được
  chia thành các block, ID của block cho biết vị trí: `Requirements!A1:F40` cho
  một vùng ô trong sheet, `page-3` hoặc `page-3-table-1` cho PDF, `slide-4`,
  `login@L12-30` cho một heading Markdown và các dòng của nó, `login@P5-12` cho
  một heading Word và các đoạn của nó. Tìm trong cache sẽ trả về tài liệu, ID
  block và vị trí kèm mỗi kết quả, và lệnh
  `query_cache.py --doc <doc-id> --block-id <block-id>` lấy lại đúng block đó,
  nên mỗi requirement đều lần lại được nơi nó được viết.
- **Khi một tài liệu được sửa, bạn có báo cáo phần đã thay đổi.** Phiên bản mới
  được so với bản đã cache trước đó, và báo cáo liệt kê phần được thêm, sửa, xóa:
  requirement theo mã (`REQ-12`, `FR-3.1`, `US-7`), section theo heading, trang
  theo số trang, slide theo tiêu đề hoặc số slide, dòng bảng theo ô chứa mã
  hoặc ô đầu tiên. Phần text bị sửa có kèm diff ngắn; dòng bảng bị sửa có giá
  trị các ô trước và sau. Xem bằng `query_cache.py --changes --doc <doc-id>`.

Sau khi cài đặt một lần, người dùng có thể chỉ cần đưa tên folder:

```text
Apply requirements from ./requirements
```

```text
Local requirements
        ↓
Document Reader scripts (inspect/search/extract)
        ↓
Relevant evidence with source references
        ↓
Host coding agent (Codex, Claude Code, Gemini CLI, ...)
        ↓
Project code changes + tests
```

Định dạng đọc được: Excel (`.xlsx`, `.xlsm`), CSV (`.csv`, `.tsv`), Markdown,
PDF (kể cả bảng, và trang scan qua OCR), Word (`.docx`), PowerPoint (`.pptx`),
HTML (`.html`, `.htm`, ví dụ bản export Confluence/wiki) và text (`.txt`).

Coding agent là thành phần sửa project. Các script của skill chỉ đọc và chuẩn
hóa tài liệu. Adapter OpenAI/Anthropic/Gemini là tùy chọn dành cho phân tích API
và không có quyền sửa filesystem.

Tri thức dùng lại giữa các context được lưu trong project:

```text
.document-reader/
├── manifest.json   # hash và cấu trúc tài liệu
├── index.json      # danh mục block đã cache của từng tài liệu
├── cache/          # nội dung đầy đủ đã chuẩn hóa, một file JSON cho mỗi tài liệu
└── knowledge.md    # requirement, mapping code, trạng thái và validation
```

Khi một tài liệu được sửa, cache chỉ đọc lại tài liệu đó và ghi lại phần nào được
thêm, sửa, xóa (theo mã requirement như `REQ-12`, theo heading, theo dòng bảng), để
agent chỉ áp dụng phần đã đổi: `query_cache.py --changes --doc <doc-id>`.

Đây là project-persistent context, không phải trí nhớ ngầm của model. Vì vậy
Codex, Claude Code hoặc Gemini CLI đều có thể đọc lại nếu được cấu hình dùng skill.

## Tự cài Python environment

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-python-env.ps1
```

Linux/macOS:

```bash
sh setup-python-env.sh
```

Hai bootstrap dùng `uv` để tự cài Python 3.12, tạo venv trung lập tại
`~/.document-reader/venv` và cài `openpyxl`, `pypdf`, `pdfplumber`.

### OCR cho PDF scan và ảnh (tùy chọn)

Trang PDF scan và ảnh chụp không có lớp chữ. Để skill đọc được chúng bằng
Tesseract:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-ocr.ps1
```

```bash
sh setup-ocr.sh
```

Trên Windows script cài Tesseract bằng `winget` nếu máy chưa có (Windows sẽ hỏi
quyền); trên Linux/macOS bạn tự cài `tesseract` bằng trình quản lý gói trước. Cả
hai script tải dữ liệu tiếng Việt và tiếng Anh vào `~/.document-reader/tessdata`.
Không chạy bước này thì mọi thứ khác vẫn hoạt động; trang scan được báo là chưa đọc.

Xem [`document-reader-skill/SKILL.md`](document-reader-skill/SKILL.md) để biết
workflow và [`document-reader-skill/README.md`](document-reader-skill/README.md)
để cài đặt, sử dụng.

## Cài tự động trên Windows

```powershell
.\setup-document-reader.bat C:\Git\my-project requirements --agent all /install-deps
```

Batch cài skill cho Codex, Claude Code và Gemini CLI; tạo `requirements/`,
`.document-reader/`, các instruction file native và manifest lần đầu.

## Cài tự động trên Linux/macOS

```bash
chmod +x setup-document-reader.sh
./setup-document-reader.sh /path/to/my-project requirements --agent all --install-deps
```

Script POSIX hỗ trợ Linux và macOS, thực hiện cùng workflow với bản Windows.

## Lịch sử thay đổi

Xem [CHANGELOG.md](CHANGELOG.md).

## Giấy phép

Phát hành theo giấy phép MIT. Xem [LICENSE](LICENSE).
