#!/usr/bin/env python3
"""Component and smoke tests for legal_deep_research_eval.

These tests are intentionally dependency-light: no real LLM, no Milvus, no DB.
"""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PACKAGE_ROOT.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from fastapi.testclient import TestClient

from legal_eval.api.app import app
from legal_eval.loaders.benchmark_loader import BenchmarkTaskLoader
from legal_eval.schemas import LegalEvalRequest
from legal_eval.service import LegalEvalService
from legal_eval.tools.citation_verifier import CitationVerifierTool
from legal_eval.tools.claim_extractor import ClaimExtractorTool
from legal_eval.tools.evidence_verifier import EvidenceChainVerifierTool
from legal_eval.tools.jurisdiction_checker import JurisdictionVersionCheckerTool
from legal_eval.tools.post_checker import PostCheckTool
from legal_eval.tools.report_parser import ReportParserTool
from legal_eval.tools.result_store import EvalResultStoreTool
from legal_eval.tools.rule_engine import LegalRuleEngineTool


def test_report_parser() -> None:
    report = "# 法律风控分析报告\n\n## 重要提示\n本报告仅供参考，不构成正式法律意见。\n\n## 风险识别\n存在高风险。"
    parsed = ReportParserTool().parse(report)
    assert parsed["title"] == "法律风控分析报告"
    assert len(parsed["sections"]) >= 2
    assert parsed["disclaimer_candidates"]


def test_claim_extractor() -> None:
    report = "该条款存在高风险。根据《中华人民共和国民法典》第五百七十七条，违约方可能承担违约责任。"
    claims = ClaimExtractorTool().extract_by_rules(report)
    assert len(claims) >= 2
    assert all(claim["claim_id"] for claim in claims)


def test_rule_engine_fatal() -> None:
    res = LegalRuleEngineTool().run(
        task_meta={"must_include_disclaimer": True},
        report_markdown="该合同可以直接签署。",
        source_index=[],
        risk_items=[],
        evidence_chain=[],
        claims=[],
        gold_reference=None,
    )
    codes = {item["code"] for item in res["fatal_errors"]}
    assert "MISSING_DISCLAIMER" in codes
    assert "DETERMINISTIC_LEGAL_ADVICE" in codes


def test_evidence_chain() -> None:
    risk_items = [{"risk_id": "R1", "risk_level": "高风险", "evidence_ids": []}]
    res = EvidenceChainVerifierTool().verify(risk_items, evidence_chain=[], source_index=[])
    assert res["unsupported_high_risk_items"]


def test_citation_verifier() -> None:
    source_index = [
        {"source_id": "law_001", "title": "中华人民共和国民法典", "article_no": "第五百七十七条"}
    ]
    report = "根据《中华人民共和国民法典》第五百七十七条，违约方可能承担违约责任。"
    res = CitationVerifierTool().verify(report, source_index, claims=[])
    assert res["num_citations_found"] >= 1
    assert res["num_citations_matched"] >= 1
    bad = CitationVerifierTool().verify("根据《不存在法》第九十九条。", source_index, claims=[])
    assert bad["unmatched_citations"]


def test_jurisdiction_checker() -> None:
    source_index = [{"source_id": "law_us_001", "jurisdiction": "US", "validity_status": "effective"}]
    res = JurisdictionVersionCheckerTool().verify(
        task_meta={"jurisdiction": "CN-mainland"},
        source_index=source_index,
        report_markdown="根据美国法律，该合同在中国大陆当然无效。",
    )
    assert res["jurisdiction_match"] is False
    cross = JurisdictionVersionCheckerTool().verify(
        task_meta={"jurisdiction": "中国大陆 / 美国"},
        source_index=source_index,
        report_markdown="美国法律仅作为比较法参考，不直接适用。",
    )
    assert cross["jurisdiction_match"] is True


def test_post_checker() -> None:
    post = PostCheckTool().check(
        rule_engine_result={"fatal_errors": [{"code": "MISSING_DISCLAIMER"}], "auto_checks": {"disclaimer_present": False}},
        llm_judge_result={
            "fatal_errors": [],
            "auto_checks": {"disclaimer_present": True},
            "decision": {"release_ready": True},
            "dimensions": {"evidence_chain": {"score": 5}},
            "uncertainty": {"judge_confidence": 0.9},
        },
        evidence_result={"evidence_chain_complete": False},
        citation_result={},
    )
    assert post["post_check_pass"] is False


def test_orchestrator_e2e() -> None:
    batch_result = WORKSPACE_ROOT / "industry_information_assistant/backend/batch_outputs/legal_30_questions/20260607_005455/results/EASY_01.json"
    if not batch_result.exists():
        return
    service = LegalEvalService(result_store=EvalResultStoreTool(base_dir=PACKAGE_ROOT / "eval_results_test"))
    res = service.evaluate(LegalEvalRequest(batch_result_path=batch_result, judge_mode="mock", save_result=True))
    assert res.eval_id
    assert res.decision["release_ready"] is False
    assert res.result_path


def test_api_smoke() -> None:
    client = TestClient(app)
    hello = client.get("/hello")
    assert hello.status_code == 200
    resp = client.post(
        "/legal-eval/rule-only",
        json={"candidate_report_markdown": "该合同可以直接签署。", "task_meta": {"must_include_disclaimer": True}, "save_result": False},
    )
    assert resp.status_code == 200
    codes = {item["code"] for item in resp.json()["fatal_errors"]}
    assert "MISSING_DISCLAIMER" in codes


def test_benchmark_loader() -> None:
    loader = BenchmarkTaskLoader()
    tasks = loader.load_tasks()
    if tasks:
        assert any(task.get("task_id") == "EASY_01" for task in tasks)


def main() -> None:
    tests = [
        test_report_parser,
        test_claim_extractor,
        test_rule_engine_fatal,
        test_evidence_chain,
        test_citation_verifier,
        test_jurisdiction_checker,
        test_post_checker,
        test_orchestrator_e2e,
        test_api_smoke,
        test_benchmark_loader,
    ]
    for test in tests:
        test()
        print(f"{test.__name__} ok")
    print("all legal eval component tests ok")


if __name__ == "__main__":
    main()
