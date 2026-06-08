# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Filesystem trace recorder for DeepResearch agent subprocess I/O."""

from __future__ import annotations

import json
import os
import threading
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


CURRENT_TRACE: ContextVar[Optional["TraceRecorder"]] = ContextVar("deep_research_trace", default=None)
CURRENT_AGENT_RUN_ID: ContextVar[Optional[str]] = ContextVar("deep_research_agent_run_id", default=None)

SENSITIVE_KEYWORDS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "secret",
    "token",
    "password",
    "access_key",
    "refresh_key",
)

INTERNAL_STATE_KEYS = {
    "_message_queue",
    "_trace_recorder",
}


def get_default_trace_root() -> Path:
    env_path = os.getenv("DEEP_RESEARCH_TRACE_DIR") or os.getenv("LEGAL_TRACE_DIR")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "runtime_traces" / "deep_research"


def is_trace_enabled() -> bool:
    value = os.getenv("DEEP_RESEARCH_TRACE_ENABLED", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def sanitize_for_trace(value: Any) -> Any:
    """Return a JSON-safe value, redacting secrets but preserving agent I/O."""
    if isinstance(value, dict):
        clean: Dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            lowered = key_str.lower()
            if key_str in INTERNAL_STATE_KEYS or key_str.startswith("_"):
                continue
            if any(marker in lowered for marker in SENSITIVE_KEYWORDS):
                clean[key_str] = "[REDACTED]"
            else:
                clean[key_str] = sanitize_for_trace(item)
        return clean
    if isinstance(value, list):
        return [sanitize_for_trace(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_trace(item) for item in value]
    if isinstance(value, set):
        return [sanitize_for_trace(item) for item in sorted(value, key=lambda x: str(x))]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except Exception:
        return repr(value)


def json_dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize_for_trace(data), ensure_ascii=False, indent=2), encoding="utf-8")


def json_append(path: Path, data: Any, lock: threading.Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(sanitize_for_trace(data), ensure_ascii=False)
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def state_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    artifacts = state.get("artifacts") or {}
    analysis = ((artifacts.get("analysis_draft") or {}).get("writes") or {})
    qa = ((artifacts.get("qa_verdict") or {}).get("writes") or {})
    return {
        "phase": state.get("phase"),
        "iteration": state.get("iteration"),
        "max_iterations": state.get("max_iterations"),
        "current_agent": state.get("current_agent"),
        "artifact_status": {
            key: (value.get("meta") or {}).get("status")
            for key, value in artifacts.items()
            if isinstance(value, dict) and value
        },
        "report_length": len(analysis.get("report_markdown", "") or ""),
        "quality_score": qa.get("score_total"),
        "qa_verdict": qa.get("verdict"),
    }


class TraceRecorder:
    """Write complete DeepResearch subprocess traces under one session folder."""

    def __init__(
        self,
        session_id: str,
        query: str,
        root_dir: Optional[Path] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.session_id = session_id
        self.query = query
        self.trace_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{session_id}_{uuid.uuid4().hex[:8]}"
        self.root_dir = Path(root_dir or get_default_trace_root()).expanduser().resolve()
        self.trace_dir = self.root_dir / self.trace_id
        self.agent_dir = self.trace_dir / "agents"
        self.llm_path = self.trace_dir / "llm_calls.jsonl"
        self.events_path = self.trace_dir / "events.jsonl"
        self.agent_index_path = self.trace_dir / "agent_runs.jsonl"
        self._lock = threading.Lock()
        self._counter = 0
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        json_dump(self.trace_dir / "metadata.json", {
            "trace_id": self.trace_id,
            "session_id": session_id,
            "query": query,
            "created_at": datetime.now().isoformat(),
            **(metadata or {}),
        })

    def _next_counter(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    def start_agent(self, agent_name: str, role: str, state: Dict[str, Any]) -> str:
        sequence = self._next_counter()
        run_id = f"{sequence:03d}_{agent_name}_{uuid.uuid4().hex[:6]}"
        run_dir = self.agent_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        json_dump(run_dir / "input_state.json", state)
        json_append(self.agent_index_path, {
            "event": "agent_start",
            "run_id": run_id,
            "agent": agent_name,
            "role": role,
            "sequence": sequence,
            "timestamp": datetime.now().isoformat(),
            "input_summary": state_summary(state),
            "run_dir": str(run_dir),
        }, self._lock)
        return run_id

    def end_agent(
        self,
        run_id: str,
        agent_name: str,
        state: Dict[str, Any],
        error: Optional[str] = None,
    ) -> None:
        run_dir = self.agent_dir / run_id
        json_dump(run_dir / "output_state.json", state)
        json_append(self.agent_index_path, {
            "event": "agent_end",
            "run_id": run_id,
            "agent": agent_name,
            "timestamp": datetime.now().isoformat(),
            "output_summary": state_summary(state),
            "error": error,
            "run_dir": str(run_dir),
        }, self._lock)

    def record_message(self, agent_name: str, event_type: str, message: Dict[str, Any]) -> None:
        run_id = CURRENT_AGENT_RUN_ID.get()
        payload = {
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "agent": agent_name,
            "run_id": run_id,
            "event_type": event_type,
            "message": message,
        }
        json_append(self.events_path, payload, self._lock)
        if run_id:
            json_append(self.agent_dir / run_id / "messages.jsonl", payload, self._lock)

    def record_graph_event(self, event: Dict[str, Any]) -> None:
        json_append(self.events_path, {
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "agent": "DeepResearchGraph",
            "run_id": None,
            "event_type": event.get("type", "graph_event"),
            "message": event,
        }, self._lock)

    def record_llm_call(
        self,
        agent_name: str,
        model: str,
        request: Dict[str, Any],
        response: Optional[str],
        duration_ms: int,
        error: Optional[str] = None,
    ) -> None:
        run_id = CURRENT_AGENT_RUN_ID.get()
        payload = {
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "agent": agent_name,
            "run_id": run_id,
            "model": model,
            "duration_ms": duration_ms,
            "request": request,
            "response": response,
            "response_length": len(response or ""),
            "error": error,
        }
        json_append(self.llm_path, payload, self._lock)
        if run_id:
            json_append(self.agent_dir / run_id / "llm_calls.jsonl", payload, self._lock)

    def record_final_state(self, state: Dict[str, Any]) -> None:
        json_dump(self.trace_dir / "final_state.json", state)
        json_dump(self.trace_dir / "summary.json", {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "query": self.query,
            "completed_at": datetime.now().isoformat(),
            "summary": state_summary(state),
        })

    def trace_info(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "trace_dir": str(self.trace_dir),
            "events_path": str(self.events_path),
            "llm_path": str(self.llm_path),
            "agent_index_path": str(self.agent_index_path),
        }


def clone_state_for_trace(state: Dict[str, Any]) -> Dict[str, Any]:
    return sanitize_for_trace(state)
