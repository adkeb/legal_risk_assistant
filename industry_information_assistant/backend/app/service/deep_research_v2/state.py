# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Minimal artifact state for the legal-risk DeepResearch workflow."""

from __future__ import annotations

import copy
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict


class ResearchPhase(str, Enum):
    """Public phase values kept for the existing SSE/checkpoint shell."""

    INIT = "init"
    PLANNING = "planning"
    RESEARCHING = "researching"
    ANALYZING = "analyzing"
    WRITING = "writing"
    REVIEWING = "reviewing"
    RE_RESEARCHING = "re_researching"
    REVISING = "revising"
    COMPLETED = "completed"


ARTIFACT_KEYS = (
    "scope_brief",
    "source_pack",
    "evidence_matrix",
    "analysis_draft",
    "qa_verdict",
)


@dataclass
class AgentLog:
    timestamp: datetime
    agent: str
    action: str
    input_summary: str
    output_summary: str
    duration_ms: int
    tokens_used: int = 0


class ResearchState(TypedDict, total=False):
    """Orchestration state: metadata plus immutable stage artifacts."""

    query: str
    session_id: str
    phase: str
    iteration: int
    max_iterations: int
    search_web: bool
    search_local: bool
    allow_recursive_search: bool
    current_agent: str
    artifacts: Dict[str, Dict[str, Any]]
    artifact_history: Dict[str, List[Dict[str, Any]]]
    artifact_order: List[str]
    route_instruction: Dict[str, Any]
    messages: List[Dict[str, Any]]
    logs: List[Dict[str, Any]]
    errors: List[str]
    trace_info: Dict[str, Any]
    trace_started: bool


def ensure_artifact_state_defaults(state: Dict[str, Any]) -> Dict[str, Any]:
    """Backfill only the new orchestration fields for new states/checkpoints."""

    state.setdefault("phase", ResearchPhase.INIT.value)
    state.setdefault("iteration", 0)
    state.setdefault("max_iterations", 1)
    state.setdefault("search_web", True)
    state.setdefault("search_local", False)
    state.setdefault("allow_recursive_search", True)
    state.setdefault("current_agent", "")
    state.setdefault("artifacts", {})
    if not isinstance(state["artifacts"], dict):
        state["artifacts"] = {}
    for key in ARTIFACT_KEYS:
        state["artifacts"].setdefault(key, {})
    state.setdefault("artifact_history", {})
    if not isinstance(state["artifact_history"], dict):
        state["artifact_history"] = {}
    for key in ARTIFACT_KEYS:
        state["artifact_history"].setdefault(key, [])
    state.setdefault("artifact_order", [])
    state.setdefault("route_instruction", {})
    state.setdefault("messages", [])
    state.setdefault("logs", [])
    state.setdefault("errors", [])
    return state


def is_legacy_state(state: Optional[Dict[str, Any]]) -> bool:
    """Detect checkpoints created by the previous shared-field workflow."""

    if not state:
        return False
    if "artifacts" in state:
        return False
    legacy_keys = {
        "outline",
        "facts",
        "legal_sources",
        "risk_items",
        "final_report",
        "references",
        "critic_feedback",
    }
    return any(key in state for key in legacy_keys)


def create_initial_state(
    query: str,
    session_id: str,
    search_web: bool = True,
    search_local: bool = False,
) -> ResearchState:
    """Create a fresh legal workflow state."""

    state: Dict[str, Any] = {
        "query": query,
        "session_id": session_id,
        "phase": ResearchPhase.INIT.value,
        "iteration": 0,
        "max_iterations": 1,
        "search_web": search_web,
        "search_local": search_local,
        "allow_recursive_search": True,
        "current_agent": "",
        "artifacts": {key: {} for key in ARTIFACT_KEYS},
        "artifact_history": {key: [] for key in ARTIFACT_KEYS},
        "artifact_order": [],
        "route_instruction": {},
        "messages": [],
        "logs": [],
        "errors": [],
    }
    return ResearchState(**ensure_artifact_state_defaults(state))


def get_artifact(state: Dict[str, Any], artifact_key: str) -> Dict[str, Any]:
    ensure_artifact_state_defaults(state)
    artifact = state.get("artifacts", {}).get(artifact_key) or {}
    return artifact if isinstance(artifact, dict) else {}


def get_artifact_writes(state: Dict[str, Any], artifact_key: str) -> Dict[str, Any]:
    artifact = get_artifact(state, artifact_key)
    writes = artifact.get("writes") if isinstance(artifact, dict) else {}
    return writes if isinstance(writes, dict) else {}


def put_artifact(state: Dict[str, Any], artifact_key: str, artifact: Dict[str, Any]) -> None:
    ensure_artifact_state_defaults(state)
    previous = state["artifacts"].get(artifact_key)
    if isinstance(previous, dict) and previous:
        history = state["artifact_history"].setdefault(artifact_key, [])
        history.append(copy.deepcopy(previous))
    state["artifacts"][artifact_key] = artifact
    order = state.setdefault("artifact_order", [])
    if artifact_key not in order:
        order.append(artifact_key)


def get_final_report(state: Dict[str, Any]) -> str:
    return str(get_artifact_writes(state, "analysis_draft").get("report_markdown") or "")


def get_quality_score(state: Dict[str, Any]) -> float:
    score = get_artifact_writes(state, "qa_verdict").get("score_total")
    try:
        return float(score or 0.0)
    except (TypeError, ValueError):
        return 0.0


def get_references(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    issue_sources = get_artifact_writes(state, "source_pack").get("issue_sources") or []
    references: List[Dict[str, Any]] = []
    for source in issue_sources:
        if not isinstance(source, dict):
            continue
        references.append(
            {
                "id": source.get("source_id", ""),
                "title": source.get("title", "") or source.get("proposition", ""),
                "link": source.get("url", ""),
                "content": source.get("exact_quote", ""),
                "source": source.get("source_kind", "legal_source"),
            }
        )
    return references


# Temporary compatibility for modules outside the new legal workflow that still
# import the old helper name. It does not restore or map old business fields.
def ensure_legal_state_defaults(state: Dict[str, Any]) -> Dict[str, Any]:
    return ensure_artifact_state_defaults(state)
