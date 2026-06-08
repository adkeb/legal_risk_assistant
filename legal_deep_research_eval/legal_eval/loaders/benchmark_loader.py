"""Benchmark task loader for the 30-question legal-risk bank."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import DEFAULT_BENCHMARK_JSONL, DEFAULT_QUESTION_BANK
from ..utils import read_jsonl, read_text, write_jsonl


class BenchmarkTaskLoader:
    def __init__(
        self,
        markdown_path: Path = DEFAULT_QUESTION_BANK,
        jsonl_path: Path = DEFAULT_BENCHMARK_JSONL,
    ) -> None:
        self.markdown_path = Path(markdown_path)
        self.jsonl_path = Path(jsonl_path)

    def load_tasks(self) -> List[Dict[str, Any]]:
        if self.jsonl_path.exists():
            return read_jsonl(self.jsonl_path)
        if self.markdown_path.exists():
            return self.load_from_markdown(self.markdown_path)
        return []

    def load_from_markdown(self, path: Path) -> List[Dict[str, Any]]:
        content = read_text(Path(path))
        match = re.search(r"```json\s*(\[[\s\S]*?\])\s*```", content)
        if not match:
            raise ValueError(f"No JSON array code block found in {path}")
        tasks = json.loads(match.group(1))
        if not isinstance(tasks, list):
            raise ValueError("Question bank JSON is not a list")
        return [self._normalize_task(item) for item in tasks if isinstance(item, dict)]

    def export_jsonl(self, path: Optional[Path] = None) -> Path:
        output = Path(path or self.jsonl_path)
        tasks = self.load_from_markdown(self.markdown_path)
        write_jsonl(output, tasks)
        return output

    def find_task(self, task_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not task_id:
            return None
        for task in self.load_tasks():
            if task.get("task_id") == task_id or task.get("id") == task_id:
                return task
        return None

    def build_task_meta(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task_id": task.get("task_id") or task.get("id"),
            "difficulty": task.get("difficulty"),
            "scenario": task.get("scenario_summary") or task.get("scenario"),
            "task_type": task.get("task_type"),
            "legal_domain": task.get("legal_domain") or [],
            "jurisdiction": task.get("primary_jurisdiction") or "中国大陆",
            "primary_jurisdiction": task.get("primary_jurisdiction") or "中国大陆",
            "requires_human_review": bool(
                (task.get("expected_human_review_trigger") or {}).get("required", False)
            ),
            "must_include_disclaimer": True,
        }

    def build_gold_reference(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task_id": task.get("task_id") or task.get("id"),
            "must_cover_points": task.get("expected_answer_points") or task.get("must_cover_points") or [],
            "evidence_chain_requirements": task.get("evidence_chain_requirements") or [],
            "expected_human_review_trigger": task.get("expected_human_review_trigger") or {},
            "auto_scoring": task.get("auto_scoring") or [],
            "human_scoring_notes": task.get("human_scoring_notes") or "",
            "required_disclaimer": True,
            "prohibited_outputs": task.get("prohibited_outputs") or ["可以直接签署", "无需律师复核"],
        }

    def _normalize_task(self, item: Dict[str, Any]) -> Dict[str, Any]:
        task_id = item.get("task_id") or item.get("id")
        return {
            **item,
            "task_id": task_id,
            "id": task_id,
            "gold_reference": self.build_gold_reference(item),
            "task_meta": self.build_task_meta(item),
        }
