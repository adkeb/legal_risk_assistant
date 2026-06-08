"""Read-only file manifest generation and comparison."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable

from ..utils import iter_files, read_json, sha256_file, write_json


DEFAULT_EXCLUDED_PARTS = {
    ".venv",
    "node_modules",
    "__pycache__",
    "dist",
    "batch_outputs",
    "runtime_traces",
    ".git",
}


class ManifestTool:
    def create(
        self,
        target_root: Path,
        output_path: Path,
        excluded_parts: Iterable[str] = DEFAULT_EXCLUDED_PARTS,
    ) -> Path:
        target_root = Path(target_root).resolve()
        excluded = sorted(set(excluded_parts))
        files: Dict[str, Dict[str, Any]] = {}
        for path in iter_files(target_root, excluded):
            rel = str(path.relative_to(target_root))
            files[rel] = {"sha256": sha256_file(path), "size": path.stat().st_size}
        manifest = {
            "target_root": str(target_root),
            "created_at": datetime.utcnow().isoformat(),
            "excluded_parts": excluded,
            "file_count": len(files),
            "files": files,
        }
        return write_json(Path(output_path), manifest)

    def compare(self, before_path: Path, after_path: Path) -> Dict[str, Any]:
        before = read_json(Path(before_path))
        after = read_json(Path(after_path))
        before_files = before.get("files", {})
        after_files = after.get("files", {})
        before_keys = set(before_files)
        after_keys = set(after_files)
        added = sorted(after_keys - before_keys)
        removed = sorted(before_keys - after_keys)
        changed = sorted(
            key
            for key in before_keys & after_keys
            if before_files[key].get("sha256") != after_files[key].get("sha256")
        )
        return {
            "before": str(before_path),
            "after": str(after_path),
            "added": added,
            "removed": removed,
            "changed": changed,
            "clean": not added and not removed and not changed,
        }
