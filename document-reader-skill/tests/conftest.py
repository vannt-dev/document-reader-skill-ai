import pytest


@pytest.fixture
def sample_md(tmp_path):
    path = tmp_path / "business.md"
    path.write_text(
        "# Overview\nIntro text.\n\n# Authentication\nUsers must log in.\n\n"
        "## Tokens\nUse JWT.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def sample_xlsx(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "api.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "API"
    sheet.append(["ID", "Requirement", "Status"])
    sheet.append(["REQ-1", "Login endpoint", "pending"])
    sheet.append(["REQ-2", "Logout endpoint", "pending"])
    workbook.save(path)
    return path


@pytest.fixture
def manifest_for(tmp_path):
    """Build a manifest.json referencing given files, return its path."""
    import json
    from index_documents import digest

    def _make(paths, cache_dir):
        documents = []
        for path in paths:
            documents.append({
                "path": path.name,
                "type": "markdown" if path.suffix.lower() in {".md", ".markdown"} else "excel",
                "sha256": digest(path),
            })
        manifest = {
            "schema_version": "1.0",
            "requirements_root": str(tmp_path),
            "documents": documents,
        }
        cache_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = cache_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    return _make
