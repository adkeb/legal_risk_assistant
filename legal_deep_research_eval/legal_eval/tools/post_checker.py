"""Consistency checks for judge output."""

from __future__ import annotations

from typing import Any, Dict, List


class PostCheckTool:
    def check(
        self,
        rule_engine_result: Dict[str, Any],
        llm_judge_result: Dict[str, Any],
        evidence_result: Dict[str, Any],
        citation_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        errors: List[str] = []
        rule_fatal_codes = {item.get("code") for item in rule_engine_result.get("fatal_errors", [])}
        judge_fatal_codes = {item.get("code") for item in llm_judge_result.get("fatal_errors", [])}
        missing = sorted(code for code in rule_fatal_codes - judge_fatal_codes if code)
        if missing:
            errors.append(f"Judge 未继承规则引擎 fatal: {missing}")
        if llm_judge_result.get("fatal_errors") and llm_judge_result.get("decision", {}).get("release_ready") is True:
            errors.append("存在 fatal_errors 但 release_ready=true")
        if rule_engine_result.get("auto_checks", {}).get("disclaimer_present") is False:
            if llm_judge_result.get("auto_checks", {}).get("disclaimer_present") is True:
                errors.append("规则引擎判定缺免责声明，但 Judge 输出为存在")
        if evidence_result.get("evidence_chain_complete") is False:
            score = (
                llm_judge_result.get("dimensions", {})
                .get("evidence_chain", {})
                .get("score", 0)
            )
            if score > 3:
                errors.append("证据链不完整但 Judge 给出过高分")
        if rule_engine_result.get("fatal_errors"):
            confidence = llm_judge_result.get("uncertainty", {}).get("judge_confidence", 0)
            if confidence > 0.85:
                errors.append("存在 fatal 时 Judge 置信度不应过高")
        return {
            "post_check_pass": not errors,
            "errors": errors,
            "warnings": [],
            "citation_validity": citation_result.get("citation_validity"),
        }
