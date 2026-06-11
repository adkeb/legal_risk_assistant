"""Component checks for the decoupled legal workflow."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _base_state() -> dict:
    from app.service.deep_research_v2.state import create_initial_state

    return create_initial_state("测试法律问题", "component-test")


def test_legal_config():
    from app.config.llm_config import get_config

    config = get_config()
    assert config.research.legal_mode is True
    assert config.get_agent_config("scope_definition") is not None
    assert config.get_agent_config("source_verification") is not None
    assert config.get_agent_config("evidence_catalog") is not None
    assert config.get_agent_config("legal_analysis_draft") is not None
    assert config.get_agent_config("quality_routing") is not None


def test_descriptive_route_schema():
    from pydantic import ValidationError

    from app.service.deep_research_v2.artifact_schemas import make_envelope, validate_artifact
    from app.service.deep_research_v2.agents.workflow_utils import (
        LEGAL_ANALYSIS_DRAFT,
        QUALITY_ROUTING,
        SOURCE_VERIFICATION,
    )

    valid = make_envelope(
        agent=QUALITY_ROUTING,
        artifact_id="qa_verdict",
        writes={
            "score_total": 80,
            "dimension_scores": {
                "jurisdiction_scope": 12,
                "source_accuracy": 20,
                "evidence_closure": 12,
                "phase_discipline": 12,
                "reasoning_quality": 12,
                "readability": 12,
            },
            "hard_failures": [],
            "issues": [{"severity": "major", "type": "source_gap", "message": "补法源", "route_to": SOURCE_VERIFICATION}],
            "verdict": "needs_revision",
            "route": {"next_agent": LEGAL_ANALYSIS_DRAFT, "instruction": "修订报告。"},
        },
        next_agent=LEGAL_ANALYSIS_DRAFT,
        reason="test",
    )
    assert validate_artifact("qa_verdict", valid)["writes"]["route"]["next_agent"] == LEGAL_ANALYSIS_DRAFT

    legacy_route = "A" + "4"
    invalid = valid.copy()
    invalid["writes"] = dict(valid["writes"], route={"next_agent": legacy_route, "instruction": "old"})
    try:
        validate_artifact("qa_verdict", invalid)
    except ValidationError:
        pass
    else:
        raise AssertionError("legacy Ax route should be rejected")


def test_main_path_no_ax_agent_names():
    files = [
        ROOT / "app/service/deep_research_v2/graph.py",
        ROOT / "app/service/deep_research_v2/artifact_schemas.py",
        ROOT / "app/service/deep_research_v2/prompts/legal_prompts.py",
    ]
    pattern = re.compile(r"\bA[1-5]\b")
    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(str(path))
    assert not offenders, offenders


def test_scope_fallback_uses_descriptive_agent_ids():
    from app.service.deep_research_v2.agents.scope_definition import ScopeDefinitionAgent
    from app.service.deep_research_v2.agents.workflow_utils import SCOPE_DEFINITION, SOURCE_VERIFICATION

    artifact = ScopeDefinitionAgent("", "")._fallback(_base_state())
    assert artifact["meta"]["agent"] == SCOPE_DEFINITION
    assert artifact["handoff"]["next_agent"] == SOURCE_VERIFICATION
    assert artifact["writes"]["source_targets"]


def test_source_query_builder_uses_scope_terms():
    from app.service.deep_research_v2.agents.source_verification import SourceVerificationAgent
    from app.service.deep_research_v2.artifact_schemas import make_envelope
    from app.service.deep_research_v2.state import put_artifact
    from app.service.deep_research_v2.agents.workflow_utils import SCOPE_DEFINITION, SOURCE_VERIFICATION

    state = _base_state()
    put_artifact(state, "scope_brief", make_envelope(
        agent=SCOPE_DEFINITION,
        artifact_id="scope",
        writes={
            "task_type": "test",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": ["中国大陆"], "why_unknown": ""},
            "issue_tree": [{"issue_id": "I01", "question": "未经同意处理个人信息的责任", "priority": "P0", "evidence_needed": ["授权记录"]}],
            "facts_known": ["用户陈述"],
            "facts_assumed": [],
            "facts_missing": [],
            "source_targets": ["个人信息 单独同意"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent=SOURCE_VERIFICATION,
        reason="test",
    ))
    queries = SourceVerificationAgent("", "")._build_search_queries(state)
    assert "个人信息 单独同意" in queries
    assert any("未经同意处理个人信息" in query for query in queries)


def test_legal_search_uses_tavily_before_bocha():
    from app.tools import legal_search_tool as tool

    bocha_called = {"value": False}
    original_tavily = tool.perform_internet_search
    original_bocha = tool._search_bocha

    def fake_tavily(**kwargs):
        return {"query": kwargs["query"], "results": [{"title": "法源", "url": "https://example.test/source", "content": "内容"}]}

    def fake_bocha(*args, **kwargs):
        bocha_called["value"] = True
        return []

    try:
        tool.perform_internet_search = fake_tavily
        tool._search_bocha = fake_bocha
        result = tool.perform_legal_search("民法典 侵权责任", max_results=2)
    finally:
        tool.perform_internet_search = original_tavily
        tool._search_bocha = original_bocha

    assert result["results"][0]["provider"] == "tavily"
    assert bocha_called["value"] is False


def test_legal_search_falls_back_to_bocha():
    from app.tools import legal_search_tool as tool

    original_tavily = tool.perform_internet_search
    original_bocha = tool._search_bocha

    def fake_tavily(**kwargs):
        raise RuntimeError("Tavily exhausted")

    def fake_bocha(query, max_results, api_key=None):
        return [{
            "provider": "bocha",
            "query": query,
            "title": "博查法源",
            "url": "https://example.test/bocha",
            "content": "博查摘要",
            "raw_content": "博查摘要",
            "published_date": "",
            "error": "",
        }]

    try:
        tool.perform_internet_search = fake_tavily
        tool._search_bocha = fake_bocha
        result = tool.perform_legal_search("民法典 侵权责任", max_results=2)
    finally:
        tool.perform_internet_search = original_tavily
        tool._search_bocha = original_bocha

    assert result["results"][0]["provider"] == "bocha"
    assert result["tool_errors"] == 1
    assert result["providers_used"] == ["tavily", "bocha"]


def test_source_fallback_hard_fails_without_results():
    from app.service.deep_research_v2.agents.source_verification import SourceVerificationAgent
    from app.service.deep_research_v2.agents.workflow_utils import SCOPE_DEFINITION, SOURCE_VERIFICATION
    from app.service.deep_research_v2.artifact_schemas import make_envelope
    from app.service.deep_research_v2.state import put_artifact

    state = _base_state()
    put_artifact(state, "scope_brief", make_envelope(
        agent=SCOPE_DEFINITION,
        artifact_id="scope",
        writes={
            "task_type": "test",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": ["中国大陆"], "why_unknown": ""},
            "issue_tree": [{"issue_id": "I01", "question": "测试问题", "priority": "P0", "evidence_needed": []}],
            "facts_known": ["事实"],
            "facts_assumed": [],
            "facts_missing": [],
            "source_targets": ["民法典"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent=SOURCE_VERIFICATION,
        reason="test",
    ))
    state["_source_search_summary"] = {"search_attempts": 1, "valid_results": 0, "tool_errors": 2, "providers_used": ["tavily", "bocha"]}
    artifact = SourceVerificationAgent("", "")._fallback(state, [{"query": "民法典", "error": "failed"}])
    assert artifact["meta"]["status"] == "hard_fail"
    assert artifact["writes"]["issue_sources"] == []
    assert artifact["writes"]["source_health"] == "source_unavailable"


def test_evidence_catalog_merges_scope_missing_materials():
    from app.service.deep_research_v2.agents.evidence_catalog import EvidenceCatalogAgent
    from app.service.deep_research_v2.agents.workflow_utils import EVIDENCE_CATALOG, SCOPE_DEFINITION, SOURCE_VERIFICATION
    from app.service.deep_research_v2.artifact_schemas import make_envelope
    from app.service.deep_research_v2.state import put_artifact

    state = _base_state()
    put_artifact(state, "scope_brief", make_envelope(
        agent=SCOPE_DEFINITION,
        artifact_id="scope",
        writes={
            "task_type": "test",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": ["中国大陆"], "why_unknown": ""},
            "issue_tree": [{"issue_id": "I01", "question": "测试问题", "priority": "P0", "evidence_needed": ["合同全文"]}],
            "facts_known": ["事实"],
            "facts_assumed": [],
            "facts_missing": ["平台隐私政策"],
            "source_targets": ["民法典"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent=SOURCE_VERIFICATION,
        reason="test",
    ))
    artifact = make_envelope(
        agent=EVIDENCE_CATALOG,
        artifact_id="evidence",
        writes={
            "facts": [],
            "evidence_items": [],
            "issue_evidence_matrix": [{"issue_id": "I01", "supporting_evidence": [], "conflicting_evidence": [], "missing_evidence": ["聊天记录"]}],
            "material_read_status": [],
            "missing_materials": [],
        },
        next_agent="legal_analysis_draft",
        reason="test",
    )
    writes = EvidenceCatalogAgent("", "")._coerce_evidence_matrix_shape(state, artifact)["writes"]
    joined = "\n".join(writes["missing_materials"])
    assert "平台隐私政策" in joined
    assert "聊天记录" in joined
    assert "影响" in joined


def test_analysis_maps_fact_ids_to_evidence_ids():
    from app.service.deep_research_v2.agents.legal_analysis_draft import LegalAnalysisDraftAgent
    from app.service.deep_research_v2.agents.workflow_utils import (
        EVIDENCE_CATALOG,
        LEGAL_ANALYSIS_DRAFT,
        QUALITY_ROUTING,
        SCOPE_DEFINITION,
        SOURCE_VERIFICATION,
    )
    from app.service.deep_research_v2.artifact_schemas import make_envelope
    from app.service.deep_research_v2.state import put_artifact

    state = _base_state()
    put_artifact(state, "scope_brief", make_envelope(
        agent=SCOPE_DEFINITION,
        artifact_id="scope",
        writes={
            "task_type": "test",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": ["中国大陆"], "why_unknown": ""},
            "issue_tree": [{"issue_id": "I01", "question": "测试问题", "priority": "P0", "evidence_needed": []}],
            "facts_known": ["事实"],
            "facts_assumed": [],
            "facts_missing": [],
            "source_targets": ["测试"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent=SOURCE_VERIFICATION,
        reason="test",
    ))
    put_artifact(state, "source_pack", make_envelope(
        agent=SOURCE_VERIFICATION,
        artifact_id="source",
        writes={"issue_sources": [], "unresolved_source_gaps": []},
        next_agent=EVIDENCE_CATALOG,
        reason="test",
    ))
    put_artifact(state, "evidence_matrix", make_envelope(
        agent=EVIDENCE_CATALOG,
        artifact_id="evidence",
        writes={
            "facts": [{"fact_id": "F03", "statement": "事实", "evidence_ids": ["E01"], "status": "partially_verified"}],
            "evidence_items": [{"evidence_id": "E01", "source_type": "user_material", "locator": "用户问题", "excerpt": "事实", "read_status": "read"}],
            "issue_evidence_matrix": [{"issue_id": "I01", "supporting_evidence": ["E01"], "conflicting_evidence": [], "missing_evidence": []}],
            "material_read_status": [{"material_id": "MATERIAL_USER_QUERY", "status": "read", "reason": ""}],
            "missing_materials": [],
        },
        next_agent=LEGAL_ANALYSIS_DRAFT,
        reason="test",
    ))
    analysis = make_envelope(
        agent=LEGAL_ANALYSIS_DRAFT,
        artifact_id="analysis",
        writes={
            "issue_analysis": [{"issue_id": "I01", "conclusion": "结论", "reasoning": "推理", "source_ids": [], "evidence_ids": ["F03", "BAD"], "certainty": "medium"}],
            "risk_register": [{"risk_id": "R01", "title": "风险", "level": "medium", "priority": "P1", "source_ids": [], "evidence_ids": ["F03"]}],
            "action_plan": [{"action_id": "ACT01", "priority": "P1", "owner": "用户", "description": "行动", "depends_on": []}],
            "report_markdown": "## 核心结论\n测试\n\nAI生成，仅供参考",
            "citation_index": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent=QUALITY_ROUTING,
        reason="test",
    )
    normalized = LegalAnalysisDraftAgent("", "")._normalize_analysis_artifact(state, analysis)["writes"]
    assert normalized["issue_analysis"][0]["evidence_ids"] == ["E01"]
    assert normalized["risk_register"][0]["evidence_ids"] == ["E01"]


def test_analysis_source_failure_generates_temporary_report_without_internal_markers():
    from app.service.deep_research_v2.agents.legal_analysis_draft import LegalAnalysisDraftAgent
    from app.service.deep_research_v2.agents.workflow_utils import (
        EVIDENCE_CATALOG,
        LEGAL_ANALYSIS_DRAFT,
        QUALITY_ROUTING,
        SCOPE_DEFINITION,
        SOURCE_VERIFICATION,
    )
    from app.service.deep_research_v2.artifact_schemas import make_envelope
    from app.service.deep_research_v2.state import put_artifact

    state = _base_state()
    put_artifact(state, "scope_brief", make_envelope(
        agent=SCOPE_DEFINITION,
        artifact_id="scope",
        writes={
            "task_type": "test",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": ["中国大陆"], "why_unknown": ""},
            "issue_tree": [{"issue_id": "I01", "question": "无人机致损责任", "priority": "P0", "evidence_needed": ["维修发票"]}],
            "facts_known": ["无人机撞车"],
            "facts_assumed": [],
            "facts_missing": ["无人机型号"],
            "source_targets": ["民法典 侵权责任"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent=SOURCE_VERIFICATION,
        reason="test",
    ))
    put_artifact(state, "source_pack", make_envelope(
        agent=SOURCE_VERIFICATION,
        artifact_id="source",
        writes={
            "issue_sources": [],
            "unresolved_source_gaps": ["source_unavailable：未取得法源"],
            "search_summary": {"load_bearing_sources": 0},
            "source_health": "source_unavailable",
        },
        next_agent=EVIDENCE_CATALOG,
        reason="test",
        status="hard_fail",
    ))
    put_artifact(state, "evidence_matrix", make_envelope(
        agent=EVIDENCE_CATALOG,
        artifact_id="evidence",
        writes={
            "facts": [{"fact_id": "F01", "statement": "无人机撞车", "evidence_ids": ["E01"], "status": "partially_verified"}],
            "evidence_items": [{"evidence_id": "E01", "source_type": "user_material", "locator": "用户问题", "excerpt": "无人机撞车", "read_status": "read"}],
            "issue_evidence_matrix": [{"issue_id": "I01", "supporting_evidence": ["E01"], "conflicting_evidence": [], "missing_evidence": ["维修发票"]}],
            "material_read_status": [{"material_id": "MATERIAL_USER_QUERY", "status": "read", "reason": ""}],
            "missing_materials": ["维修发票：影响赔偿金额。"],
        },
        next_agent=LEGAL_ANALYSIS_DRAFT,
        reason="test",
    ))
    analysis = make_envelope(
        agent=LEGAL_ANALYSIS_DRAFT,
        artifact_id="analysis",
        writes={
            "issue_analysis": [{"issue_id": "I01", "conclusion": "应承担责任", "reasoning": "source_pack E01 F01", "source_ids": [], "evidence_ids": ["E01"], "certainty": "medium"}],
            "risk_register": [{"risk_id": "R01", "title": "赔偿风险", "level": "high", "priority": "P1", "source_ids": [], "evidence_ids": ["E01"]}],
            "action_plan": [{"action_id": "ACT01", "priority": "P1", "owner": "用户", "description": "固定证据", "depends_on": []}],
            "report_markdown": "# 正式报告\nsource_pack E01 F01 I01 ACT01 GAP01\n\nAI生成，仅供参考",
            "citation_index": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent=QUALITY_ROUTING,
        reason="test",
    )
    normalized = LegalAnalysisDraftAgent("", "")._apply_source_availability_mode(state, analysis)
    report = normalized["writes"]["report_markdown"]
    assert "临时风险梳理草稿" in report
    for marker in ["source_pack", "evidence_matrix", "GAP01", "I01", "F01", "E01", "M01", "ACT01", "Agent"]:
        assert marker not in report
    assert normalized["writes"]["issue_analysis"][0]["certainty"] == "pending_verification"


def test_quality_blocks_outside_references_with_descriptive_routes():
    from app.service.deep_research_v2.agents.quality_routing import QualityRoutingAgent
    from app.service.deep_research_v2.agents.workflow_utils import EVIDENCE_CATALOG, QUALITY_ROUTING, SOURCE_VERIFICATION
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = _base_state()
    state["artifacts"] = {
        "source_pack": make_envelope(
            agent=SOURCE_VERIFICATION,
            artifact_id="source",
            writes={"issue_sources": [], "unresolved_source_gaps": []},
            next_agent=EVIDENCE_CATALOG,
            reason="test",
        ),
        "evidence_matrix": make_envelope(
            agent=EVIDENCE_CATALOG,
            artifact_id="evidence",
            writes={
                "facts": [],
                "evidence_items": [{"evidence_id": "E01", "source_type": "user_material", "locator": "用户问题", "excerpt": "事实", "read_status": "read"}],
                "issue_evidence_matrix": [],
                "material_read_status": [{"material_id": "MATERIAL_USER_QUERY", "status": "read", "reason": ""}],
                "missing_materials": [],
            },
            next_agent="legal_analysis_draft",
            reason="test",
        ),
        "analysis_draft": make_envelope(
            agent="legal_analysis_draft",
            artifact_id="analysis",
            writes={
                "issue_analysis": [{"issue_id": "I01", "conclusion": "结论", "reasoning": "推理", "source_ids": ["S99"], "evidence_ids": ["E99"], "certainty": "medium"}],
                "risk_register": [],
                "action_plan": [{"action_id": "ACT01", "priority": "P1", "owner": "用户", "description": "行动", "depends_on": []}],
                "report_markdown": "## 核心结论\n测试\n\nAI生成，仅供参考",
                "citation_index": [],
                "human_review": {"required": False, "reasons": []},
            },
            next_agent=QUALITY_ROUTING,
            reason="test",
        ),
    }
    verdict = QualityRoutingAgent("", "")._deterministic_verdict(state)["writes"]
    assert verdict["route"]["next_agent"] == SOURCE_VERIFICATION
    assert verdict["verdict"] == "needs_research"


def test_graph_import():
    from app.service.deep_research_v2.graph import DeepResearchGraph
    from app.service.deep_research_v2.agents.workflow_utils import SCOPE_DEFINITION

    graph = DeepResearchGraph(max_iterations=0)
    assert SCOPE_DEFINITION in graph.agents_by_code


def main():
    test_legal_config()
    test_descriptive_route_schema()
    test_main_path_no_ax_agent_names()
    test_scope_fallback_uses_descriptive_agent_ids()
    test_source_query_builder_uses_scope_terms()
    test_legal_search_uses_tavily_before_bocha()
    test_legal_search_falls_back_to_bocha()
    test_source_fallback_hard_fails_without_results()
    test_evidence_catalog_merges_scope_missing_materials()
    test_analysis_maps_fact_ids_to_evidence_ids()
    test_analysis_source_failure_generates_temporary_report_without_internal_markers()
    test_quality_blocks_outside_references_with_descriptive_routes()
    test_graph_import()
    print("All legal research component tests passed.")


if __name__ == "__main__":
    main()
