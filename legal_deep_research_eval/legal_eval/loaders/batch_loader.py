"""Load existing batch output artifacts from industry_information_assistant."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ..utils import read_json, read_text


class BatchOutputLoader:
    def load_result(self, result_path: Path) -> Dict[str, Any]:
        result_path = Path(result_path)
        data = read_json(result_path)
        if not isinstance(data, dict):
            raise ValueError(f"Batch result is not an object: {result_path}")
        report_path = Path(data.get("report_path", ""))
        events_path = Path(data.get("events_path", ""))
        trace_info = data.get("trace_info") or {}
        trace_dir = Path(trace_info.get("trace_dir", "")) if trace_info else None
        return {
            "batch_result": data,
            "task_id": data.get("id") or data.get("task_id"),
            "session_id": data.get("session_id"),
            "task_meta": {
                "task_id": data.get("id") or data.get("task_id"),
                "difficulty": data.get("difficulty"),
                "task_type": data.get("task_type"),
                "jurisdiction": data.get("primary_jurisdiction") or "中国大陆",
                "primary_jurisdiction": data.get("primary_jurisdiction") or "中国大陆",
            },
            "report_path": report_path if str(report_path) else None,
            "events_path": events_path if str(events_path) else None,
            "trace_dir": trace_dir if trace_dir and str(trace_dir) else None,
        }

    def load_report(self, report_path: Path) -> str:
        path = Path(report_path)
        if not path.exists():
            return ""
        return read_text(path)

    def iter_result_paths(self, batch_dir: Path) -> List[Path]:
        results_dir = Path(batch_dir) / "results"
        if not results_dir.exists():
            return []
        return sorted(results_dir.glob("*.json"))
