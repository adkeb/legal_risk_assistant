"""Aggregate tool results into final scores and gate decisions."""

from __future__ import annotations

from typing import Any, Dict, List

from .config import (
    BUSINESS_EFFECT_WEIGHTS,
    LEGAL_EVAL_THRESHOLDS,
    LEGAL_EVAL_VERSION,
    OVERALL_WEIGHTS,
    RESEARCH_PROCESS_WEIGHTS,
    RESEARCH_QUALITY_WEIGHTS,
)


def aggregate_final_result(state: Any) -> Dict[str, Any]:
    judge = state.llm_judge_result or {}
    dimensions = judge.get("dimensions", {})
    rule = state.rule_engine_result or {}
    fatal_errors = _dedupe_errors(list(rule.get("fatal_errors", [])) + list(judge.get("fatal_errors", [])))
    goal_scores = {
        "research_quality": _weighted_goal(dimensions, RESEARCH_QUALITY_WEIGHTS),
        "research_process": _weighted_goal(dimensions, RESEARCH_PROCESS_WEIGHTS),
        "business_effect": _weighted_goal(dimensions, BUSINESS_EFFECT_WEIGHTS),
    }
    overall_score = round(
        goal_scores["research_quality"] * OVERALL_WEIGHTS["research_quality"]
        + goal_scores["research_process"] * OVERALL_WEIGHTS["research_process"]
        + goal_scores["business_effect"] * OVERALL_WEIGHTS["business_effect"],
        2,
    )
    result = {
        "eval_id": state.eval_input.eval_id,
        "task_id": state.eval_input.task_id,
        "session_id": state.eval_input.session_id,
        "overall_score": overall_score,
        "goal_scores": goal_scores,
        "dimensions": dimensions,
        "fatal_errors": fatal_errors,
        "warnings": list(rule.get("warnings", [])) + list(state.warnings),
        "auto_checks": {**rule.get("auto_checks", {}), **judge.get("auto_checks", {})},
        "metrics": {
            **rule.get("metrics", {}),
            **state.citation_result,
            **state.evidence_result,
            **state.jurisdiction_result,
            **state.retrieval_result,
            **state.process_result,
            **state.gold_comparison_result,
            **state.actionability_result,
        },
        "uncertainty": judge.get("uncertainty", {}),
        "notes": judge.get("notes", {}),
        "rule_engine_result": state.rule_engine_result,
        "citation_result": state.citation_result,
        "evidence_result": state.evidence_result,
        "jurisdiction_result": state.jurisdiction_result,
        "retrieval_result": state.retrieval_result,
        "process_result": state.process_result,
        "gold_comparison_result": state.gold_comparison_result,
        "actionability_result": state.actionability_result,
        "llm_judge_result": state.llm_judge_result,
        "post_check_result": state.post_check_result,
        "eval_version": LEGAL_EVAL_VERSION,
    }
    result["decision"] = decide_gate(result)
    return result


def decide_gate(final_result: Dict[str, Any]) -> Dict[str, Any]:
    fatal_errors = final_result.get("fatal_errors", [])
    goal_scores = final_result.get("goal_scores", {})
    dimensions = final_result.get("dimensions", {})
    post_check = final_result.get("post_check_result", {})
    if fatal_errors:
        return {
            "pass_gate": "fail",
            "release_ready": False,
            "requires_human_review": True,
            "reason": "存在 fatal_errors",
            "decision_source": "rule_engine + judge",
        }
    if not post_check.get("post_check_pass", True):
        return {
            "pass_gate": "fail",
            "release_ready": False,
            "requires_human_review": True,
            "reason": "Judge 输出与规则检查结果不一致",
            "decision_source": "post_check",
        }
    if goal_scores.get("research_quality", 0) < LEGAL_EVAL_THRESHOLDS["quality_revise"]:
        return {
            "pass_gate": "revise",
            "release_ready": False,
            "requires_human_review": True,
            "reason": "研究质量分不足",
            "decision_source": "aggregator",
        }
    if dimensions.get("legal_factuality", {}).get("score", 0) < LEGAL_EVAL_THRESHOLDS["legal_factuality_fail"]:
        return {
            "pass_gate": "fail",
            "release_ready": False,
            "requires_human_review": True,
            "reason": "法律事实正确性不足",
            "decision_source": "aggregator",
        }
    if dimensions.get("evidence_chain", {}).get("score", 0) < LEGAL_EVAL_THRESHOLDS["evidence_chain_revise"]:
        return {
            "pass_gate": "revise",
            "release_ready": False,
            "requires_human_review": True,
            "reason": "证据链完整性不足",
            "decision_source": "aggregator",
        }
    if final_result.get("overall_score", 0) >= LEGAL_EVAL_THRESHOLDS["quality_pass"]:
        return {
            "pass_gate": "conditional_pass",
            "release_ready": False,
            "requires_human_review": True,
            "reason": "法律风控报告建议人工复核后使用",
            "decision_source": "aggregator",
        }
    return {
        "pass_gate": "revise",
        "release_ready": False,
        "requires_human_review": True,
        "reason": "可修订后复评",
        "decision_source": "aggregator",
    }


def _weighted_goal(dimensions: Dict[str, Any], weights: Dict[str, float]) -> float:
    score = 0.0
    weight_total = 0.0
    for key, weight in weights.items():
        dim = dimensions.get(key, {})
        if "score" not in dim:
            continue
        score += float(dim.get("score", 0)) * weight
        weight_total += weight
    if not weight_total:
        return 0.0
    return round((score / weight_total) * 2, 2)


def _dedupe_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for error in errors:
        code = error.get("code")
        if code in seen:
            continue
        seen.add(code)
        out.append(error)
    return out
