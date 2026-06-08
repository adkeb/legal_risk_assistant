"""Pydantic schemas used by the legal evaluation pipeline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


JsonDict = Dict[str, Any]


class LegalEvalRequest(BaseModel):
    eval_id: Optional[str] = None
    task_id: Optional[str] = None
    session_id: Optional[str] = None

    report_path: Optional[Path] = None
    batch_result_path: Optional[Path] = None
    events_path: Optional[Path] = None
    trace_dir: Optional[Path] = None
    final_state_path: Optional[Path] = None

    candidate_report_markdown: Optional[str] = None
    task_meta: JsonDict = Field(default_factory=dict)
    source_index: List[JsonDict] = Field(default_factory=list)
    risk_items: List[JsonDict] = Field(default_factory=list)
    evidence_chain: List[JsonDict] = Field(default_factory=list)
    gold_reference: Optional[JsonDict] = None
    process_events: List[JsonDict] = Field(default_factory=list)
    state_json: JsonDict = Field(default_factory=dict)
    run_meta: JsonDict = Field(default_factory=dict)

    judge_mode: Literal["mock", "real", "rule_only"] = "mock"
    save_result: bool = True
    require_llm: bool = False


class LegalEvalInput(BaseModel):
    eval_id: str
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    task_meta: JsonDict = Field(default_factory=dict)
    candidate_report_markdown: str = ""
    state_json: JsonDict = Field(default_factory=dict)
    process_events: List[JsonDict] = Field(default_factory=list)
    source_index: List[JsonDict] = Field(default_factory=list)
    risk_items: List[JsonDict] = Field(default_factory=list)
    evidence_chain: List[JsonDict] = Field(default_factory=list)
    gold_reference: Optional[JsonDict] = None
    run_meta: JsonDict = Field(default_factory=dict)
    judge_mode: Literal["mock", "real", "rule_only"] = "mock"
    require_llm: bool = False


class FatalError(BaseModel):
    code: str
    message: str
    evidence_ids: List[str] = Field(default_factory=list)
    severity: Literal["fatal", "high", "medium", "low"] = "fatal"


class DimensionScore(BaseModel):
    score: float = 0.0
    comment: str = ""
    metrics: JsonDict = Field(default_factory=dict)


class LegalEvalResult(BaseModel):
    eval_id: str
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    overall_score: float = 0.0
    goal_scores: Dict[str, float] = Field(default_factory=dict)
    dimensions: Dict[str, Any] = Field(default_factory=dict)
    fatal_errors: List[JsonDict] = Field(default_factory=list)
    warnings: List[JsonDict] = Field(default_factory=list)
    auto_checks: JsonDict = Field(default_factory=dict)
    metrics: JsonDict = Field(default_factory=dict)
    decision: JsonDict = Field(default_factory=dict)
    uncertainty: JsonDict = Field(default_factory=dict)
    notes: JsonDict = Field(default_factory=dict)
    rule_engine_result: JsonDict = Field(default_factory=dict)
    citation_result: JsonDict = Field(default_factory=dict)
    evidence_result: JsonDict = Field(default_factory=dict)
    jurisdiction_result: JsonDict = Field(default_factory=dict)
    retrieval_result: JsonDict = Field(default_factory=dict)
    process_result: JsonDict = Field(default_factory=dict)
    gold_comparison_result: JsonDict = Field(default_factory=dict)
    actionability_result: JsonDict = Field(default_factory=dict)
    llm_judge_result: JsonDict = Field(default_factory=dict)
    post_check_result: JsonDict = Field(default_factory=dict)
    result_path: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    eval_version: str = "legal_eval_v1"
