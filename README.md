# Document Reader Skill

Skill dành cho coding agent đọc có chọn lọc requirement trong một thư mục local,
sau đó cập nhật trực tiếp source code và tests của project hiện tại.

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

Coding agent là thành phần sửa project. Các script của skill chỉ đọc và chuẩn
hóa tài liệu. Adapter OpenAI/Anthropic/Gemini là tùy chọn dành cho phân tích API
và không có quyền sửa filesystem.

Tri thức dùng lại giữa các context được lưu trong project:

```text
.document-reader/
├── manifest.json   # hash và cấu trúc tài liệu
└── knowledge.md    # requirement, mapping code, trạng thái và validation
```

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
`~/.document-reader/venv` và cài `openpyxl`, `pypdf`.

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
