from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
DRAFT_DIR = STORAGE_DIR / "drafts"
EXPORT_DIR = STORAGE_DIR / "exports"


def ensure_storage_dirs() -> None:
    """Migration note: desktop app filesystem behavior is preserved for MVP."""
    for path in (STORAGE_DIR, UPLOAD_DIR, DRAFT_DIR, EXPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)
