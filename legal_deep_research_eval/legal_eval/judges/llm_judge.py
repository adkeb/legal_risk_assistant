"""Mock and optional real LLM-as-Judge."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..config import LLM_BASE_URL_ENV_KEYS, LLM_ENV_KEYS, LLM_MODEL_ENV_KEYS, first_env
from ..utils import clamp
from .prompts import JUDGE_SYSTEM_PROMPT, JUDGE_USER_TEMPLATE


class LLMJudgeAgent:
    def score(
        self,
        eval_input: Any,
        parsed_report: Dict[str, Any],
        claims: List[Dict[str, Any]],
        rule_engine_result: Dict[str, Any],
        citation_result: Dict[str, Any],
        evidence_result: Dict[str, Any],
        jurisdiction_result: Dict[str, Any],
        retrieval_result: Dict[str, Any],
        process_result: Dict[str, Any],
        gold_comparison_result: Dict[str, Any],
        actionability_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        if eval_input.judge_mode == "real":
            real = self._score_real(
                eval_input,
                rule_engine_result,
                citation_result,
                evidence_result,
                jurisdiction_result,
                retrieval_result,
                process_result,
                gold_comparison_result,
                actionability_result,
            )
            if real:
                return real
            if eval_input.require_llm:
                raise RuntimeError("real LLM judge required but unavailable")
        return self._score_mock(
            eval_input,
            rule_engine_result,
            citation_result,
            evidence_result,
            jurisdiction_result,
            retrieval_result,
            process_result,
            gold_comparison_result,
            actionability_result,
        )

    def _score_mock(
        self,
        eval_input: Any,
        rule_engine_result: Dict[str, Any],
        citation_result: Dict[str, Any],
        evidence_result: Dict[str, Any],
        jurisdiction_result: Dict[str, Any],
        retrieval_result: Dict[str, Any],
        process_result: Dict[str, Any],
        gold_result: Dict[str, Any],
        actionability_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        fatal_count = len(rule_engine_result.get("fatal_errors", []))
        legal_factuality = 4.2 - fatal_count * 0.8
        if citation_result.get("warnings"):
            legal_factuality -= 0.4
        dimensions = {
            "legal_factuality": self._dimension(legal_factuality, "基于规则引擎和引用核验的确定性诊断。", {
                "unverified_claim_rate": 1 - citation_result.get("critical_claim_citation_coverage", 1.0),
                "hallucination_rate": 1 - citation_result.get("citation_match_rate", 1.0),
            }),
            "jurisdiction_version_match": self._dimension(
                5 * min(jurisdiction_result.get("jurisdiction_match_rate", 1.0), jurisdiction_result.get("effective_version_match_rate", 1.0)),
                "按法域和版本字段进行规则化核验。",
                jurisdiction_result,
            ),
            "coverage": self._dimension(5 * gold_result.get("required_points_recall", 1.0), "按 Gold 必须覆盖要点粗粒度召回。", gold_result),
            "evidence_chain": self._dimension(
                5 * min(evidence_result.get("risk_with_evidence_ratio", 1.0), evidence_result.get("high_risk_dual_basis_ratio", 1.0)),
                "按 risk_item 到 evidence/source 的链路完整性评分。",
                evidence_result,
            ),
            "citation_quality": self._dimension(
                5 * min(citation_result.get("citation_match_rate", 1.0), retrieval_result.get("official_source_ratio", 0.0) + 0.25),
                "综合引用匹配率和权威来源占比。",
                {**citation_result, **retrieval_result},
            ),
            "risk_consistency": self._dimension(
                5 * rule_engine_result.get("metrics", {}).get("risk_score_consistency_rate", 1.0),
                "按摘要、正文和 risk_items 的风险等级一致性估计。",
                rule_engine_result.get("metrics", {}),
            ),
            "legal_reasoning": self._dimension(3.5 - fatal_count * 0.4, "mock judge 不作外部法律判断，仅按结构完整性保守估计。"),
            "legal_boundary_compliance": self._dimension(5 if rule_engine_result.get("auto_checks", {}).get("disclaimer_present") else 1.5, "免责声明和结论边界检查。"),
            "planning_quality": self._dimension(5 if process_result.get("has_planning") else 2.0, "规划阶段轨迹检查。"),
            "retrieval_process": self._dimension(min(5.0, 2.0 + process_result.get("num_search_calls", 0) / 10), "检索调用数量和 query 去重情况。", process_result),
            "authority_priority": self._dimension(5 * retrieval_result.get("authority_source_ratio", 0.0), "权威来源占比。", retrieval_result),
            "self_correction": self._dimension(min(5.0, 2.5 + process_result.get("critic_loop_count", 0)), "critic/research revision 轨迹。", process_result),
            "trace_completeness": self._dimension(5 * process_result.get("phase_coverage", 0.0), "关键 phase 覆盖。", process_result),
            "expert_acceptability": self._dimension(3.6 - fatal_count * 0.5, "按 fatal、覆盖和证据链保守估计。"),
            "editing_cost": self._dimension(4.0 - fatal_count * 0.5 - gold_result.get("critical_omission_count", 0) * 0.2, "fatal 和遗漏越多，修订成本越高。"),
            "business_actionability": self._dimension(5 * actionability_result.get("actionability_score", 0.0), "整改建议 owner/priority/deadline/action 检查。", actionability_result),
        }
        fatal_errors = list(rule_engine_result.get("fatal_errors", []))
        confidence = 0.78
        if fatal_errors:
            confidence = 0.6
        if not eval_input.source_index:
            confidence -= 0.15
        return {
            "evaluator_model": "mock_legal_eval_judge_v1" if eval_input.judge_mode != "rule_only" else "rule_only",
            "task_id": eval_input.task_id,
            "overall_score": 0.0,
            "goal_scores": {},
            "dimensions": dimensions,
            "fatal_errors": fatal_errors,
            "auto_checks": dict(rule_engine_result.get("auto_checks", {})),
            "uncertainty": {
                "judge_confidence": max(0.0, min(1.0, confidence)),
                "human_review_recommended": True,
                "reasons": self._uncertainty_reasons(eval_input, fatal_errors, citation_result, gold_result),
            },
            "notes": {
                "strengths": [],
                "weaknesses": [item.get("message", item.get("code", "")) for item in fatal_errors],
                "missing_points": gold_result.get("missing_points", []),
                "fix_recommendations": ["补齐证据链、免责声明和人工复核提示后复评"] if fatal_errors else [],
            },
            "decision": {"pass_gate": "fail" if fatal_errors else "conditional_pass", "release_ready": False},
        }

    def _score_real(self, eval_input: Any, *results: Dict[str, Any]) -> Dict[str, Any] | None:
        api_key = first_env(LLM_ENV_KEYS)
        model = first_env(LLM_MODEL_ENV_KEYS)
        if not api_key or not model:
            return None
        try:
            from openai import OpenAI

            client_kwargs = {"api_key": api_key}
            base_url = first_env(LLM_BASE_URL_ENV_KEYS)
            if base_url:
                client_kwargs["base_url"] = base_url
            client = OpenAI(**client_kwargs)
            rule_engine_result = results[0]
            prompt = JUDGE_USER_TEMPLATE.format(
                task_meta_json=json.dumps(eval_input.task_meta, ensure_ascii=False),
                candidate_report_markdown=eval_input.candidate_report_markdown[:20000],
                gold_reference_json=json.dumps(eval_input.gold_reference, ensure_ascii=False),
                process_trace_summary_json=json.dumps(results[5], ensure_ascii=False),
                source_index_json=json.dumps(eval_input.source_index[:80], ensure_ascii=False),
                rule_engine_result_json=json.dumps(rule_engine_result, ensure_ascii=False),
            )
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            content = response.choices[0].message.content or "{}"
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    def _dimension(self, score: float, comment: str, metrics: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return {"score": round(clamp(score), 2), "comment": comment, "metrics": metrics or {}}

    def _uncertainty_reasons(
        self,
        eval_input: Any,
        fatal_errors: List[Dict[str, Any]],
        citation_result: Dict[str, Any],
        gold_result: Dict[str, Any],
    ) -> List[str]:
        reasons = []
        if fatal_errors:
            reasons.append("规则引擎发现 fatal 红线")
        if not eval_input.source_index:
            reasons.append("source_index 缺失或不足")
        if citation_result.get("unmatched_citations"):
            reasons.append("存在未匹配引用")
        if gold_result.get("missing_points"):
            reasons.append("存在 Gold 要点遗漏")
        return reasons or ["法律风控报告建议人工复核后使用"]
