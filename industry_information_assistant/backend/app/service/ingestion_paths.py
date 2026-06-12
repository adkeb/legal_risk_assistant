"""Stable storage paths for document ingestion and OCR artifacts."""
from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_STORAGE_ROOT = PROJECT_ROOT / "storage"
STORAGE_ROOT = Path(os.getenv("DOCUMENT_STORAGE_ROOT", str(DEFAULT_STORAGE_ROOT))).expanduser()
DOCUMENTS_ROOT = STORAGE_ROOT / "documents"
ARTIFACTS_ROOT = STORAGE_ROOT / "artifacts"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def document_dir(user_id: str, document_id: str) -> Path:
    return ensure_dir(DOCUMENTS_ROOT / str(user_id) / str(document_id))


def original_document_path(user_id: str, document_id: str, filename: str) -> Path:
    suffix = Path(filename or "").suffix.lower()
    return document_dir(user_id, document_id) / f"original{suffix}"


def document_artifact_dir(document_id: str) -> Path:
    return ensure_dir(ARTIFACTS_ROOT / str(document_id))


def page_artifact_dir(document_id: str, page_no: int) -> Path:
    return ensure_dir(document_artifact_dir(document_id) / "pages" / str(page_no))
