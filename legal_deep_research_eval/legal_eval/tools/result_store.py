"""JSON result storage with path-safety checks."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import DEFAULT_EVAL_RESULTS_DIR
from ..utils import json_safe_id, read_json, write_json


class EvalResultStoreTool:
    def __init__(self, base_dir: Path = DEFAULT_EVAL_RESULTS_DIR) -> None:
        self.base_dir = Path(base_dir)

    def save(self, result: Dict[str, Any], filename: Optional[str] = None) -> Path:
        eval_id = json_safe_id(filename or result.get("eval_id") or "eval_result")
        date_dir = datetime.utcnow().strftime("%Y%m%d")
        path = (self.base_dir / date_dir / f"{eval_id}.json").resolve()
        root = self.base_dir.resolve()
        if root not in path.parents:
            raise ValueError("unsafe result path")
        write_json(path, result)
        return path

    def load(self, eval_id: str) -> Dict[str, Any] | None:
        safe = json_safe_id(eval_id)
        for path in self.base_dir.rglob(f"{safe}.json"):
            data = read_json(path)
            return data if isinstance(data, dict) else None
        return None
