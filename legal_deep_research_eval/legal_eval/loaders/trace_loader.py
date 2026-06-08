"""Read runtime trace artifacts and normalize final state data."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils import extract_sources_from_state, read_json, read_jsonl


class TraceLoader:
    def load_final_state(
        self,
        final_state_path: Optional[Path] = None,
        trace_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        path: Optional[Path] = Path(final_state_path) if final_state_path else None
        if not path and trace_dir:
            candidate = Path(trace_dir) / "final_state.json"
            path = candidate if candidate.exists() else None
        if not path or not path.exists():
            return {}
        data = read_json(path)
        return data if isinstance(data, dict) else {}

    def load_events(
        self,
        events_path: Optional[Path] = None,
        trace_dir: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        path: Optional[Path] = Path(events_path) if events_path else None
        if not path and trace_dir:
            candidate = Path(trace_dir) / "events.jsonl"
            path = candidate if candidate.exists() else None
        if not path or not path.exists():
            return []
        return read_jsonl(path)

    def extract_source_index(self, state_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        return extract_sources_from_state(state_json)

    def extract_risk_items(self, state_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        values = state_json.get("risk_items") or state_json.get("risk_scores") or []
        return values if isinstance(values, list) else []

    def extract_evidence_chain(self, state_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        values = state_json.get("evidence_chain") or []
        return values if isinstance(values, list) else []
