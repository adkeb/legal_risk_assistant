"""Mutable state object passed through the fixed evaluation pipeline."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from .schemas import LegalEvalInput


class LegalEvalState(BaseModel):
    eval_input: LegalEvalInput
    parsed_report: Dict[str, Any] = Field(default_factory=dict)
    extracted_claims: List[Dict[str, Any]] = Field(default_factory=list)
    rule_engine_result: Dict[str, Any] = Field(default_factory=dict)
    citation_result: Dict[str, Any] = Field(default_factory=dict)
    evidence_result: Dict[str, Any] = Field(default_factory=dict)
    jurisdiction_result: Dict[str, Any] = Field(default_factory=dict)
    retrieval_result: Dict[str, Any] = Field(default_factory=dict)
    process_result: Dict[str, Any] = Field(default_factory=dict)
    gold_comparison_result: Dict[str, Any] = Field(default_factory=dict)
    actionability_result: Dict[str, Any] = Field(default_factory=dict)
    llm_judge_result: Dict[str, Any] = Field(default_factory=dict)
    post_check_result: Dict[str, Any] = Field(default_factory=dict)
    final_result: Dict[str, Any] = Field(default_factory=dict)
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[Dict[str, Any]] = Field(default_factory=list)
