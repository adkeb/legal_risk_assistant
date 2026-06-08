"""Deterministic legal-risk rule engine."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ..config import HIGH_RISK_SCENARIO_KEYWORDS, RULE_ENGINE_VERSION
from .citation_verifier import CitationVerifierTool
from .evidence_verifier import EvidenceChainVerifierTool
from .jurisdiction_checker import JurisdictionVersionCheckerTool
from .report_parser import DISCLAIMER_RE


ABSOLUTE_ADVICE_RE = re.compile(
    r"(可以直接|无需.{0,8}复核|肯定|必然|一定|保证|应当立即|必须立即).{0,20}(签署|胜诉|败诉|违法|无效|解除|裁员|付款|放行|起诉)"
)


class LegalRuleEngineTool:
    def __init__(self) -> None:
        self.citation_verifier = CitationVerifierTool()
        self.evidence_verifier = EvidenceChainVerifierTool()
        self.jurisdiction_checker = JurisdictionVersionCheckerTool()

    def run(
        self,
        task_meta: Dict[str, Any],
        report_markdown: str,
        source_index: List[Dict[str, Any]],
        risk_items: List[Dict[str, Any]],
        evidence_chain: List[Dict[str, Any]],
        claims: List[Dict[str, Any]],
        gold_reference: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        text = report_markdown or ""
        fatal_errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        auto_checks: Dict[str, Any] = {}
        metrics: Dict[str, Any] = {}

        disclaimer_present = bool(DISCLAIMER_RE.search(text))
        auto_checks["disclaimer_present"] = disclaimer_present
        required_disclaimer = bool(
            task_meta.get("must_include_disclaimer", True)
            or (gold_reference or {}).get("required_disclaimer", True)
        )
        if required_disclaimer and not disclaimer_present:
            fatal_errors.append(self._fatal("MISSING_DISCLAIMER", "报告缺少法律风控场景必须包含的免责声明。"))

        has_absolute_advice = bool(ABSOLUTE_ADVICE_RE.search(text))
        auto_checks["has_deterministic_legal_advice"] = has_absolute_advice
        if has_absolute_advice:
            fatal_errors.append(self._fatal("DETERMINISTIC_LEGAL_ADVICE", "报告出现过度确定性的法律建议。"))

        citation_result = self.citation_verifier.verify(text, source_index, claims)
        metrics.update(
            {
                "law_citation_match_rate": citation_result["citation_match_rate"],
                "case_number_match_rate": citation_result["citation_match_rate"],
                "critical_claim_citation_coverage": citation_result["critical_claim_citation_coverage"],
                "pinpoint_citation_rate": citation_result["pinpoint_citation_rate"],
            }
        )
        auto_checks["citation_validity"] = citation_result["citation_validity"]
        if not source_index and citation_result["num_citations_found"]:
            warnings.append({"code": "SOURCE_INDEX_MISSING", "message": "source_index 为空，无法判定引用真伪。"})
        elif citation_result["unmatched_citations"]:
            fatal_errors.append(
                self._fatal(
                    "FABRICATED_LAW_OR_CASE",
                    "报告引用了 source_index 中无法匹配的法条、案号或 source_id。",
                    [item.get("text", "") for item in citation_result["unmatched_citations"]],
                )
            )

        jurisdiction_result = self.jurisdiction_checker.verify(task_meta, source_index, text)
        auto_checks["jurisdiction_match"] = jurisdiction_result["jurisdiction_match"]
        auto_checks["law_version_match"] = jurisdiction_result["law_version_match"]
        metrics["jurisdiction_match_rate"] = jurisdiction_result["jurisdiction_match_rate"]
        metrics["effective_version_match_rate"] = jurisdiction_result["effective_version_match_rate"]
        if jurisdiction_result["wrong_jurisdiction_sources"] or jurisdiction_result.get("boundary_warning"):
            fatal_errors.append(
                self._fatal(
                    "WRONG_JURISDICTION",
                    "报告存在未说明边界的跨法域适用或非任务法域直接适用问题。",
                    [str(item.get("source_id")) for item in jurisdiction_result["wrong_jurisdiction_sources"]],
                )
            )
        if jurisdiction_result["expired_sources_used_as_current"]:
            fatal_errors.append(
                self._fatal(
                    "EXPIRED_LAW_AS_CURRENT",
                    "报告将失效法规作为现行依据使用。",
                    [str(item.get("source_id")) for item in jurisdiction_result["expired_sources_used_as_current"]],
                )
            )

        evidence_result = self.evidence_verifier.verify(risk_items, evidence_chain, source_index)
        auto_checks["evidence_chain_complete"] = evidence_result["evidence_chain_complete"]
        metrics["risk_with_evidence_ratio"] = evidence_result["risk_with_evidence_ratio"]
        if evidence_result["unsupported_high_risk_items"]:
            fatal_errors.append(
                self._fatal(
                    "UNSUPPORTED_HIGH_RISK_CONCLUSION",
                    "高风险结论缺少事实依据或规范依据。",
                    evidence_result["unsupported_high_risk_items"],
                )
            )

        risk_consistency_pass = self._risk_consistency_pass(text, risk_items)
        auto_checks["risk_consistency_pass"] = risk_consistency_pass
        metrics["risk_score_consistency_rate"] = 1.0 if risk_consistency_pass else 0.6

        review_check = self._human_review_check(task_meta, text, risk_items, gold_reference)
        auto_checks["human_review_required_correctly_flagged"] = review_check["pass"]
        if review_check["fatal"]:
            fatal_errors.append(
                self._fatal(
                    "REQUIRED_HUMAN_REVIEW_SKIPPED",
                    "该任务属于应人工复核的法律风控场景，但报告未提示人工复核。",
                    review_check["risk_ids"],
                )
            )

        return {
            "rule_engine_version": RULE_ENGINE_VERSION,
            "fatal_errors": self._dedupe_errors(fatal_errors),
            "warnings": warnings + citation_result.get("warnings", []),
            "auto_checks": auto_checks,
            "metrics": metrics,
            "rule_notes": [],
        }

    def _fatal(self, code: str, message: str, evidence_ids: List[str] | None = None) -> Dict[str, Any]:
        return {"code": code, "message": message, "evidence_ids": evidence_ids or [], "severity": "fatal"}

    def _dedupe_errors(self, errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        out = []
        for error in errors:
            key = error.get("code")
            if key in seen:
                continue
            seen.add(key)
            out.append(error)
        return out

    def _risk_consistency_pass(self, text: str, risk_items: List[Dict[str, Any]]) -> bool:
        if not risk_items:
            return True
        report_has_high = bool(re.search(r"(高风险|重大风险)", text))
        item_has_high = any(re.search(r"(高|重大|critical|high)", str(item.get("risk_level") or item.get("level") or ""), re.I) for item in risk_items)
        return not (report_has_high and not item_has_high)

    def _human_review_check(
        self,
        task_meta: Dict[str, Any],
        report_markdown: str,
        risk_items: List[Dict[str, Any]],
        gold_reference: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        gold_trigger = (gold_reference or {}).get("expected_human_review_trigger") or {}
        scenario_text = " ".join(str(task_meta.get(key, "")) for key in ("scenario", "task_type", "jurisdiction", "primary_jurisdiction"))
        high_risk_ids = [
            str(item.get("risk_id") or item.get("id") or idx)
            for idx, item in enumerate(risk_items, start=1)
            if re.search(r"(高|重大|critical|high)", str(item.get("risk_level") or item.get("level") or ""), re.I)
        ]
        required = bool(
            task_meta.get("requires_human_review")
            or gold_trigger.get("required")
            or high_risk_ids
            or any(keyword in scenario_text for keyword in HIGH_RISK_SCENARIO_KEYWORDS)
        )
        mentioned = bool(re.search(r"(人工复核|律师复核|法务复核|需.{0,8}复核|建议.{0,8}律师|建议.{0,8}法务)", report_markdown or ""))
        return {"required": required, "mentioned": mentioned, "pass": (not required) or mentioned, "fatal": required and not mentioned, "risk_ids": high_risk_ids}
