"""Optional read-only checkpoint loader.

This adapter imports the original project's checkpoint service only when a
session_id-based evaluation is requested. It never calls save/update/delete.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

from ..config import INDUSTRY_BACKEND_ROOT


class CheckpointLoader:
    def __init__(self, backend_root: Path = INDUSTRY_BACKEND_ROOT) -> None:
        self.backend_root = Path(backend_root)

    def load(self, session_id: str) -> Dict[str, Any]:
        if not session_id:
            return {"ok": False, "error": "session_id is required"}
        if not self.backend_root.exists():
            return {"ok": False, "error": f"backend root not found: {self.backend_root}"}
        inserted = False
        backend_str = str(self.backend_root)
        if backend_str not in sys.path:
            sys.path.insert(0, backend_str)
            inserted = True
        try:
            from app.service.checkpoint_service import get_checkpoint_service  # type: ignore

            service = get_checkpoint_service()
            data = service.load_full_checkpoint(session_id)
            if not data:
                return {"ok": False, "error": f"checkpoint not found: {session_id}"}
            warnings = []
            if not data.get("final_report"):
                warnings.append({"code": "EMPTY_FINAL_REPORT", "message": "final_report is empty"})
            return {"ok": True, "checkpoint": data, "warnings": warnings}
        except Exception as exc:  # pragma: no cover - depends on external DB availability.
            return {"ok": False, "error": f"checkpoint load failed: {exc}"}
        finally:
            if inserted:
                try:
                    sys.path.remove(backend_str)
                except ValueError:
                    pass
