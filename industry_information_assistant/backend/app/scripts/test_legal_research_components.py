# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Minimal legal DeepResearch component tests without external services."""

def test_legal_config():
    from app.config.legal_risk_config import LEGAL_TASK_TYPES, score_to_level

    assert "contract_review" in LEGAL_TASK_TYPES
    assert score_to_level(4.5) == "重大风险"
    assert score_to_level(3.5) == "高风险"


def test_state_defaults():
    from app.service.deep_research_v2.state import ResearchPhase, ensure_legal_state_defaults

    state = ensure_legal_state_defaults({"query": "测试", "session_id": "s1"})
    assert isinstance(state["artifacts"], dict)
    assert isinstance(state["artifact_history"], dict)
    assert "source_pack" in state["artifacts"]
    assert state["artifact_history"]["source_pack"] == []
    assert {phase.value for phase in ResearchPhase} == {
        "init",
        "planning",
        "researching",
        "analyzing",
        "writing",
        "reviewing",
        "re_researching",
        "revising",
        "completed",
    }


def test_llm_legal_defaults():
    from app.config.llm_config import get_config

    config = get_config()
    assert config.research.legal_mode is True
    assert config.research.quality_threshold == 80.0
    assert config.research.require_disclaimer is False
    assert config.get_agent_config("scope_definition") is not None
    assert config.get_agent_config("source_verification") is not None
    assert config.get_agent_config("evidence_catalog") is not None
    assert config.get_agent_config("legal_analysis_draft") is not None
    assert config.get_agent_config("quality_routing") is not None


def test_risk_scoring():
    from app.service.risk_scoring_service import RiskScoringService

    risk = RiskScoringService.score_risk({
        "impact_score": 5,
        "probability_score": 4,
        "legal_certainty_score": 4,
        "evidence_strength_score": 4,
        "urgency_score": 3,
        "remediation_difficulty_score": 3,
    })
    assert "overall_score" in risk
    assert risk["risk_level"] in ["高风险", "重大风险"]


def test_citation_verifier():
    from app.service.citation_verifier_service import CitationVerifierService

    state = {
        "risk_items": [{"risk_id": "r1", "evidence_ids": ["ev1"], "legal_basis_ids": ["law1"]}],
        "evidence_chain": [{"evidence_id": "ev1"}],
        "legal_sources": [{"source_id": "law1"}],
    }
    assert CitationVerifierService.verify_risk_items(state)[0]["status"] == "passed"
    assert CitationVerifierService.verify_risk_items({"risk_items": [{"risk_id": "r2"}]})[0]["status"] == "missing"


def test_evidence_placeholder_detection():
    from app.service.deep_research_v2.agents.legal_workflow import _contains_unread_placeholder

    assert _contains_unread_placeholder("[PDF 文件: test.pdf]")
    assert not _contains_unread_placeholder("这是合同正文")


def test_legacy_task_matchers_removed():
    import app.service.deep_research_v2.agents.legal_workflow as workflow

    removed = [
        "_is_privacy_ai_task",
        "_is_privacy_infringement_task",
        "_is_animal_bite_task",
        "_is_rental_deposit_task",
        "_is_partnership_accounting_task",
        "_is_training_shutdown_task",
        "_privacy_risk_templates",
        "_privacy_action_plan",
    ]
    assert all(not hasattr(workflow, name) for name in removed)


def test_source_tier_normalize():
    from app.service.deep_research_v2.agents.legal_workflow import _source_tier

    assert _source_tier("https://example.test/source")[0] == "T4"
    assert _source_tier("")[0] == "T5"


def test_preliminary_source_supports_mirror_rule_text():
    from app.service.deep_research_v2.agents.legal_workflow import _can_support_preliminary_source

    source = {
        "source_kind": "law",
        "source_tier": "T4",
        "article_or_section": "第一千零三十三条",
        "exact_quote": "除法律另有规定或者权利人明确同意外，任何组织或者个人不得拍摄、窥视、窃听、公开他人的私密活动。",
    }
    assert _can_support_preliminary_source(source)


def test_writer_skeleton():
    from app.service.deep_research_v2.agents.legal_workflow import LegalAnalysisDraftAgent

    report = LegalAnalysisDraftAgent("", "")._fallback({"query": "测试法律问题", "session_id": "s1"})["writes"]["report_markdown"]
    assert "核心结论" in report
    assert report.strip().endswith("AI生成，仅供参考")
    assert "不构成正式法律意见" not in report


def test_critic_verdict_normalize():
    from app.service.deep_research_v2.agents.legal_workflow import QualityRoutingAgent

    qa = QualityRoutingAgent("", "")
    assert qa.next_agent == "END"
    assert qa.artifact_key == "qa_verdict"


def test_critic_allows_model_when_no_structural_failure():
    from app.service.deep_research_v2.agents.legal_workflow import QualityRoutingAgent

    state = {
        "query": "重大合同风险测试",
        "session_id": "s1",
        "artifacts": {
            "scope_brief": {"writes": {"jurisdiction": {"primary": "中国大陆"}, "human_review": {"required": False, "reasons": []}}},
            "source_pack": {"writes": {"issue_sources": [], "unresolved_source_gaps": []}},
            "evidence_matrix": {"writes": {"evidence_items": [], "missing_materials": [], "material_read_status": []}},
            "analysis_draft": {"writes": {
                "report_markdown": "## 核心结论\n测试结论。\n\n## 法律依据与类案参考\n测试来源。\n\n## 行动建议\n测试行动。\n\nAI生成，仅供参考",
                "risk_register": [{"risk_id": "R01", "title": "无证据重大风险", "level": "high", "priority": "P0", "source_ids": [], "evidence_ids": []}],
                "issue_analysis": [],
                "action_plan": [{"action_id": f"A{i}", "priority": "P0", "owner": "用户", "description": f"具体动作 {i}", "depends_on": []} for i in range(6)],
                "human_review": {"required": False, "reasons": []},
            }},
        },
    }
    verdict = QualityRoutingAgent("", "")._deterministic_verdict(state)["writes"]

    assert verdict["verdict"] == "approved"
    assert verdict["hard_failures"] == []


def test_graph_import():
    from app.service.deep_research_v2.graph import DeepResearchGraph

    assert DeepResearchGraph is not None


def test_a1_model_defined_task_type_and_short_source_targets():
    from app.service.deep_research_v2.agents.legal_workflow import ScopeDefinitionAgent
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    query = "用户提供一组材料，要求判断某项业务安排的法律风险。"
    agent = ScopeDefinitionAgent("", "")
    artifact = make_envelope(
        agent="A1",
        artifact_id="scope_brief",
        writes={
            "task_type": "Custom Legal Risk / Source Review",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": [], "why_unknown": ""},
            "issue_tree": [{"issue_id": "I01", "question": query, "priority": "P0", "evidence_needed": []}],
            "facts_known": [query],
            "facts_assumed": [],
            "facts_missing": [],
            "source_targets": ["《示例法》第十条：这是一个很长的法条说明，不应当作为检索关键词直接输出"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent="A2",
        reason="test",
    )
    normalized = agent._normalize_scope_artifact(artifact, {"query": query, "session_id": "s1"})
    targets = normalized["writes"]["source_targets"]

    assert normalized["writes"]["task_type"] == "custom_legal_risk_source_review"
    assert all("《" not in target and "第十条" not in target for target in targets)
    assert all(len(target) <= 36 for target in targets)


def test_a2_short_query_builder():
    from app.service.deep_research_v2.agents.legal_workflow import SourceVerificationAgent
    from app.service.deep_research_v2.state import put_artifact
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = {"query": "长问题", "session_id": "s1"}
    scope = make_envelope(
        agent="A1",
        artifact_id="scope_brief",
        writes={
            "task_type": "model_defined_task",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": [], "why_unknown": ""},
            "issue_tree": [{
                "issue_id": "I01",
                "question": "用户陈述的一项复杂安排需要判断法律依据和责任边界。",
                "priority": "P0",
                "evidence_needed": [],
            }],
            "facts_known": ["用户陈述"],
            "facts_assumed": [],
            "facts_missing": [],
            "source_targets": ["复杂安排 法律依据"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent="A2",
        reason="test",
    )
    put_artifact(state, "scope_brief", scope)

    queries = SourceVerificationAgent("", "")._build_search_queries(state)
    assert "复杂安排 法律依据" in queries
    assert all("官方" not in query for query in queries)
    assert all("典型案例" not in query and "裁判规则" not in query and "判决" not in query for query in queries)


def test_a2_source_gap_shape_coercion():
    from app.service.deep_research_v2.agents.legal_workflow import _coerce_source_pack_shape

    artifact = {
        "writes": {
            "unresolved_source_gaps": [
                {"issue_id": "I01", "message": "缺少可承载法源"},
                "I02 缺少案例",
            ]
        }
    }
    coerced = _coerce_source_pack_shape(artifact)

    assert coerced["writes"]["unresolved_source_gaps"] == ["I01 缺少可承载法源", "I02 缺少案例"]


def test_a2_downgrades_unpinpointed_load_bearing_source():
    from app.service.deep_research_v2.agents.legal_workflow import SourceVerificationAgent
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = {
        "query": "测试",
        "session_id": "s1",
        "artifacts": {"scope_brief": {"writes": {"issue_tree": [{"issue_id": "I01", "priority": "P0"}]}}},
    }
    artifact = make_envelope(
        agent="A2",
        artifact_id="source_pack",
        writes={
            "issue_sources": [{
                "issue_id": "I01",
                "proposition": "测试命题",
                "source_id": "S01",
                "jurisdiction": "中国大陆",
                "title": "测试法源",
                "issuing_body": "官方",
                "source_kind": "law",
                "source_tier": "T1",
                "article_or_section": "待定位",
                "effective_status": "effective",
                "exact_quote": "测试规则原文足够长，但本条缺少精确定位，不能承载结论。",
                "pinpoint": "待定位",
                "language": "zh-CN",
                "verification_status": "verified_official",
                "use_for_load_bearing": True,
                "not_load_bearing_reason": "",
                "url": "https://www.cac.gov.cn/test",
            }],
            "unresolved_source_gaps": [],
        },
        next_agent="A3",
        reason="test",
    )
    normalized = SourceVerificationAgent("", "")._normalize_source_pack(state, artifact)
    source = normalized["writes"]["issue_sources"][0]

    assert source["use_for_load_bearing"] is False
    assert source["verification_status"] in {"pending", "fallback_mirror"}
    assert normalized["writes"]["unresolved_source_gaps"]


def test_a2_source_gaps_are_structural_not_topic_keyword_based():
    from app.service.deep_research_v2.agents.legal_workflow import SourceVerificationAgent
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = {
        "query": "测试",
        "session_id": "s1",
        "artifacts": {
            "scope_brief": {
                "writes": {
                    "issue_tree": [
                        {"issue_id": "I01", "priority": "P0"},
                        {"issue_id": "I02", "priority": "P1"},
                    ]
                }
            }
        },
    }
    artifact = make_envelope(
        agent="A2",
        artifact_id="source_pack",
        writes={
            "issue_sources": [{
                "issue_id": "I02",
                "proposition": "已有来源的争点",
                "source_id": "S01",
                "jurisdiction": "中国大陆",
                "title": "测试法源",
                "issuing_body": "机关",
                "source_kind": "law",
                "source_tier": "T1",
                "article_or_section": "第一条",
                "effective_status": "effective",
                "exact_quote": "第一条 测试法源规则原文足够长，可以支撑第二个争点的初步判断。",
                "pinpoint": "第一条",
                "language": "zh-CN",
                "verification_status": "verified_official",
                "use_for_load_bearing": True,
                "not_load_bearing_reason": "",
                "url": "https://example.test/law",
            }],
            "unresolved_source_gaps": [
                "I01 仍缺少可承载法源",
                "I02 仍需补充来源",
                "未绑定 issue 的辅助检索缺口",
            ],
        },
        next_agent="A3",
        reason="test",
    )
    normalized = SourceVerificationAgent("", "")._normalize_source_pack(state, artifact)
    gaps = normalized["writes"]["unresolved_source_gaps"]

    assert "I01 仍缺少可承载法源" in gaps
    assert "I02 仍需补充来源" not in gaps
    assert any("未绑定 issue" in gap for gap in gaps)


def test_a2_normalizes_duplicate_source_ids():
    from app.service.deep_research_v2.agents.legal_workflow import SourceVerificationAgent
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = {
        "query": "测试",
        "session_id": "s1",
        "artifacts": {"scope_brief": {"writes": {"issue_tree": [{"issue_id": "I01"}, {"issue_id": "I02"}]}}},
    }
    artifact = make_envelope(
        agent="A2",
        artifact_id="source_pack",
        writes={
            "issue_sources": [
                {
                    "issue_id": "I01",
                    "proposition": "争点一",
                    "source_id": "S08",
                    "jurisdiction": "中国大陆",
                    "title": "测试法律",
                    "issuing_body": "机关",
                    "source_kind": "law",
                    "source_tier": "T1",
                    "article_or_section": "第一条",
                    "effective_status": "effective",
                    "exact_quote": "第一条 测试法律规则原文足够长，可以支撑争点一的初步判断。",
                    "pinpoint": "第一条",
                    "language": "zh-CN",
                    "verification_status": "verified_official",
                    "use_for_load_bearing": True,
                    "not_load_bearing_reason": "",
                    "url": "https://example.test/1",
                },
                {
                    "issue_id": "I02",
                    "proposition": "争点二",
                    "source_id": "S08",
                    "jurisdiction": "中国大陆",
                    "title": "测试法律",
                    "issuing_body": "机关",
                    "source_kind": "law",
                    "source_tier": "T1",
                    "article_or_section": "第二条",
                    "effective_status": "effective",
                    "exact_quote": "第二条 测试法律规则原文足够长，可以支撑争点二的初步判断。",
                    "pinpoint": "第二条",
                    "language": "zh-CN",
                    "verification_status": "verified_official",
                    "use_for_load_bearing": True,
                    "not_load_bearing_reason": "",
                    "url": "https://example.test/2",
                },
            ],
            "unresolved_source_gaps": [],
        },
        next_agent="A3",
        reason="test",
    )
    normalized = SourceVerificationAgent("", "")._normalize_source_pack(state, artifact)
    source_ids = [source["source_id"] for source in normalized["writes"]["issue_sources"]]

    assert source_ids == ["S01", "S02"]
    assert len(source_ids) == len(set(source_ids))


def test_a2_merge_preserves_better_previous_source():
    from app.service.deep_research_v2.agents.legal_workflow import SourceVerificationAgent
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = {"query": "测试", "session_id": "s1", "artifacts": {"scope_brief": {"writes": {"issue_tree": [{"issue_id": "I01"}]}}}}
    previous = {
        "issue_sources": [{
            "issue_id": "I01",
            "proposition": "测试命题",
            "source_id": "S09",
            "jurisdiction": "中国大陆",
            "title": "测试法律",
            "issuing_body": "测试机关",
            "source_kind": "law",
            "source_tier": "T1",
            "article_or_section": "第二条",
            "effective_status": "effective",
            "exact_quote": "第二条 测试法律规则原文足够长，可以支撑当前命题的初步判断，并用于比较来源质量。",
            "pinpoint": "第二条",
            "language": "zh-CN",
            "verification_status": "verified_official",
            "use_for_load_bearing": True,
            "not_load_bearing_reason": "",
            "url": "https://www.cac.gov.cn/test",
        }],
        "unresolved_source_gaps": [],
    }
    weak = make_envelope(
        agent="A2",
        artifact_id="source_pack",
        writes={
            "issue_sources": [{
                "issue_id": "I01",
                "proposition": "测试命题",
                "source_id": "S01",
                "jurisdiction": "中国大陆",
                "title": "测试法律解读",
                "issuing_body": "地方政府",
                "source_kind": "law",
                "source_tier": "T1",
                "article_or_section": "待定位",
                "effective_status": "unknown",
                "exact_quote": "首页 登录 注册 测试法律解读",
                "pinpoint": "待定位",
                "language": "zh-CN",
                "verification_status": "verified_official",
                "use_for_load_bearing": True,
                "not_load_bearing_reason": "",
                "url": "https://example.gov.cn/read",
            }],
            "unresolved_source_gaps": [],
        },
        next_agent="A3",
        reason="test",
    )
    merged = SourceVerificationAgent("", "")._merge_with_previous_sources(state, weak, previous)

    assert any(source["article_or_section"] == "第二条" and source["use_for_load_bearing"] for source in merged["writes"]["issue_sources"])


def test_a3_user_statement_is_partially_verified():
    from app.service.deep_research_v2.agents.legal_workflow import EvidenceCatalogAgent
    from app.service.deep_research_v2.state import put_artifact
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = {"query": "用户陈述", "session_id": "s1"}
    scope = make_envelope(
        agent="A1",
        artifact_id="scope_brief",
        writes={
            "task_type": "model_defined_task",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": [], "why_unknown": ""},
            "issue_tree": [{"issue_id": "I01", "question": "测试", "priority": "P0", "evidence_needed": ["关键材料二"]}],
            "facts_known": ["用户说自己上传了材料"],
            "facts_assumed": [],
            "facts_missing": ["关键材料一"],
            "source_targets": ["测试依据"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent="A2",
        reason="test",
    )
    put_artifact(state, "scope_brief", scope)
    artifact = EvidenceCatalogAgent("", "")._fallback(state)

    assert artifact["writes"]["facts"][0]["status"] == "partially_verified"
    assert "关键材料一" in artifact["writes"]["missing_materials"]
    assert "关键材料二" in artifact["writes"]["missing_materials"]


def test_a3_missing_materials_object_coercion():
    from app.service.deep_research_v2.agents.legal_workflow import _coerce_evidence_matrix_shape

    artifact = {
        "writes": {
            "facts": [],
            "evidence_items": [],
            "issue_evidence_matrix": [{
                "issue_id": "I01",
                "supporting_evidence": [],
                "conflicting_evidence": [],
                "missing_evidence": [{"material_id": "M01", "reason": "缺少租赁合同"}],
            }],
            "material_read_status": [],
            "missing_materials": [{"material_id": "M02", "reason": "缺少押金凭证"}],
        }
    }
    coerced = _coerce_evidence_matrix_shape(artifact)

    assert coerced["writes"]["missing_materials"] == ["M02 缺少押金凭证"]
    assert coerced["writes"]["issue_evidence_matrix"][0]["missing_evidence"] == ["M01 缺少租赁合同"]


def test_a4_analysis_nested_writes_coercion():
    from app.service.deep_research_v2.agents.legal_workflow import _coerce_analysis_draft_shape

    artifact = {
        "writes": {
            "writes": {
                "issue_analysis": [],
                "risk_register": [],
                "action_plan": [],
                "report_markdown": "## 核心结论\n\n## 法律依据\n\n## 行动建议\n\nAI生成，仅供参考",
            }
        }
    }
    coerced = _coerce_analysis_draft_shape(artifact)

    assert "report_markdown" in coerced["writes"]
    assert "writes" not in coerced["writes"]


def test_a4_analysis_nested_envelope_coercion():
    from app.service.deep_research_v2.agents.legal_workflow import _coerce_analysis_draft_shape

    artifact = {
        "writes": {
            "meta": {"agent": "A4"},
            "writes": {
                "issue_analysis": [],
                "risk_register": [],
                "action_plan": [],
                "report_markdown": "## 核心结论\n\n## 法律依据\n\n## 行动建议\n\nAI生成，仅供参考",
                "citation_index": [],
                "human_review": {"required": False, "reasons": []},
            },
        }
    }
    coerced = _coerce_analysis_draft_shape(artifact)

    assert "report_markdown" in coerced["writes"]
    assert "meta" not in coerced["writes"]


def test_a4_fallback_is_user_facing_and_not_template_bound():
    from app.service.deep_research_v2.agents.legal_workflow import LegalAnalysisDraftAgent

    state = {"query": "用户陈述某项行为引发争议，需要判断法律责任。", "session_id": "s1"}
    artifact = LegalAnalysisDraftAgent("", "")._fallback(state)
    report = artifact["writes"]["report_markdown"]
    actions = artifact["writes"]["action_plan"]

    assert report.strip().endswith("AI生成，仅供参考")
    assert "不构成正式法律意见" not in report
    assert "免责声明" not in report
    assert "source_pack" not in report and "evidence_matrix" not in report and "工件" not in report
    assert "核心结论" in report and "法律依据" in report and "行动建议" in report
    assert len({action["description"] for action in actions}) >= 6


def test_a4_fallback_does_not_inject_legacy_topic_templates():
    from app.service.deep_research_v2.agents.legal_workflow import LegalAnalysisDraftAgent
    from app.service.deep_research_v2.state import put_artifact
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = {"query": "租房退租后房东扣押金；另有朋友合伙开店账目不清；还怀疑维修店查看手机隐私", "session_id": "s1"}
    scope = make_envelope(
        agent="A1",
        artifact_id="scope_brief",
        writes={
            "task_type": "model_defined_mixed_consumer_contract_privacy",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": [], "why_unknown": ""},
            "issue_tree": [
                {"issue_id": "I01", "question": "押金扣除是否有合同和损失依据", "priority": "P0", "evidence_needed": ["租赁合同"]},
                {"issue_id": "I02", "question": "合伙账目不清时如何要求说明和结算", "priority": "P1", "evidence_needed": ["出资记录"]},
                {"issue_id": "I03", "question": "维修服务中查看手机隐私如何判断责任", "priority": "P1", "evidence_needed": ["维修凭证"]},
            ],
            "facts_known": ["用户陈述存在三个不同争议"],
            "facts_assumed": [],
            "facts_missing": ["合同原件", "付款记录", "维修凭证"],
            "source_targets": ["合同责任", "合伙结算", "隐私权"],
            "clarification_questions": [],
            "human_review": {"required": True, "reasons": []},
        },
        next_agent="A2",
        reason="test",
    )
    put_artifact(state, "scope_brief", scope)
    artifact = LegalAnalysisDraftAgent("", "")._fallback(state)
    report = artifact["writes"]["report_markdown"]
    actions = [action["description"] for action in artifact["writes"]["action_plan"]]

    legacy_phrases = ["22500 元", "8/14，即约 57.14%", "学法典读案例答问题", "修改手机锁屏密码"]
    assert all(phrase not in report for phrase in legacy_phrases)
    assert all(phrase not in " ".join(actions) for phrase in legacy_phrases)
    assert "行动建议" in report
    assert "pending_verification" not in report


def test_a4_fallback_addresses_qa_quality_findings():
    from app.service.deep_research_v2.agents.legal_workflow import LegalAnalysisDraftAgent
    from app.service.deep_research_v2.state import put_artifact
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = {"query": "用户陈述某项行为引发争议并产生后续影响。", "session_id": "s1"}
    scope = make_envelope(
        agent="A1",
        artifact_id="scope_brief",
        writes={
            "task_type": "model_defined_dispute",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": [], "why_unknown": ""},
            "issue_tree": [
                {"issue_id": "I01", "question": "争点一的法律判断", "priority": "P0", "evidence_needed": ["关键材料一"]},
                {"issue_id": "I02", "question": "争点二的责任范围", "priority": "P1", "evidence_needed": ["关键材料二"]},
            ],
            "facts_known": ["用户陈述某项行为引发争议"],
            "facts_assumed": [],
            "facts_missing": ["关键材料一", "关键材料二"],
            "source_targets": ["争点一 依据", "争点二 责任"],
            "clarification_questions": [],
            "human_review": {"required": True, "reasons": ["需要核验关键材料"]},
        },
        next_agent="A2",
        reason="test",
    )
    source_pack = make_envelope(
        agent="A2",
        artifact_id="source_pack",
        writes={
            "issue_sources": [{
                "issue_id": "I01",
                "proposition": "争点一可参考的可比来源",
                "source_id": "S01",
                "jurisdiction": "中国大陆",
                "title": "可比来源一",
                "issuing_body": "人民法院",
                "source_kind": "case",
                "source_tier": "T3",
                "article_or_section": "第一条",
                "effective_status": "effective",
                "exact_quote": "第一条 该可比来源规则原文足够长，可以支撑争点一的初步判断。",
                "pinpoint": "第一条",
                "language": "zh-CN",
                "verification_status": "verified_official",
                "use_for_load_bearing": True,
                "not_load_bearing_reason": "",
                "url": "https://example.test/case",
            }],
            "unresolved_source_gaps": [],
        },
        next_agent="A3",
        reason="test",
    )
    evidence_matrix = make_envelope(
        agent="A3",
        artifact_id="evidence_matrix",
        writes={
            "facts": [{"fact_id": "F01", "statement": "用户陈述某项行为引发争议", "evidence_ids": ["E01"], "status": "partially_verified"}],
            "evidence_items": [{"evidence_id": "E01", "source_type": "user_material", "locator": "用户问题", "excerpt": "用户陈述", "read_status": "read"}],
            "issue_evidence_matrix": [
                {"issue_id": "I01", "supporting_evidence": ["E01"], "conflicting_evidence": [], "missing_evidence": ["关键材料一"]},
                {"issue_id": "I02", "supporting_evidence": ["E01"], "conflicting_evidence": [], "missing_evidence": ["关键材料二"]},
            ],
            "material_read_status": [],
            "missing_materials": ["关键材料一", "关键材料二"],
        },
        next_agent="A4",
        reason="test",
    )
    put_artifact(state, "scope_brief", scope)
    put_artifact(state, "source_pack", source_pack)
    put_artifact(state, "evidence_matrix", evidence_matrix)
    artifact = LegalAnalysisDraftAgent("", "")._fallback(state)
    report = artifact["writes"]["report_markdown"]
    actions = [action["description"] for action in artifact["writes"]["action_plan"]]

    assert "可比来源一 第一条（S01）" in report
    assert "建议按以下顺序执行" in report
    assert actions[0].startswith("暂停")
    assert actions[1].startswith("完整保存")
    assert "关键材料一：主要影响" in report
    assert "争点二的责任范围" in report


def test_a4_normalizes_action_order_and_issue_source_binding():
    from app.service.deep_research_v2.agents.legal_workflow import LegalAnalysisDraftAgent
    from app.service.deep_research_v2.state import put_artifact
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = {"query": "测试", "session_id": "s1"}
    scope = make_envelope(
        agent="A1",
        artifact_id="scope_brief",
        writes={
            "task_type": "model_defined_test",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": [], "why_unknown": ""},
            "issue_tree": [
                {"issue_id": "I01", "question": "第一个争点", "priority": "P0", "evidence_needed": []},
                {"issue_id": "I02", "question": "第二个争点", "priority": "P0", "evidence_needed": []},
            ],
            "facts_known": ["测试事实"],
            "facts_assumed": [],
            "facts_missing": [],
            "source_targets": ["测试"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent="A2",
        reason="test",
    )
    source_pack = make_envelope(
        agent="A2",
        artifact_id="source_pack",
        writes={
            "issue_sources": [
                {
                    "issue_id": "I01",
                    "proposition": "第一个争点依据",
                    "source_id": "S01",
                    "jurisdiction": "中国大陆",
                    "title": "测试法源一",
                    "issuing_body": "机关",
                    "source_kind": "law",
                    "source_tier": "T1",
                    "article_or_section": "第一条",
                    "effective_status": "effective",
                    "exact_quote": "第一条 测试法源一用于支撑第一个争点，文本足够长以满足规则原文要求。",
                    "pinpoint": "第一条",
                    "language": "zh-CN",
                    "verification_status": "verified_official",
                    "use_for_load_bearing": True,
                    "not_load_bearing_reason": "",
                    "url": "https://example.test/1",
                },
                {
                    "issue_id": "I02",
                    "proposition": "第二个争点依据",
                    "source_id": "S02",
                    "jurisdiction": "中国大陆",
                    "title": "测试法源二",
                    "issuing_body": "机关",
                    "source_kind": "law",
                    "source_tier": "T1",
                    "article_or_section": "第二条",
                    "effective_status": "effective",
                    "exact_quote": "第二条 测试法源二用于支撑第二个争点，文本足够长以满足规则原文要求。",
                    "pinpoint": "第二条",
                    "language": "zh-CN",
                    "verification_status": "verified_official",
                    "use_for_load_bearing": True,
                    "not_load_bearing_reason": "",
                    "url": "https://example.test/2",
                },
                {
                    "issue_id": "I01",
                    "proposition": "歧义编号争点一",
                    "source_id": "S03",
                    "jurisdiction": "中国大陆",
                    "title": "歧义法源一",
                    "issuing_body": "机关",
                    "source_kind": "law",
                    "source_tier": "T1",
                    "article_or_section": "第三条",
                    "effective_status": "effective",
                    "exact_quote": "第三条 歧义法源一用于支撑第一个争点，文本足够长以满足规则原文要求。",
                    "pinpoint": "第三条",
                    "language": "zh-CN",
                    "verification_status": "verified_official",
                    "use_for_load_bearing": True,
                    "not_load_bearing_reason": "",
                    "url": "https://example.test/3",
                },
                {
                    "issue_id": "I02",
                    "proposition": "歧义编号争点二",
                    "source_id": "S03",
                    "jurisdiction": "中国大陆",
                    "title": "歧义法源二",
                    "issuing_body": "机关",
                    "source_kind": "law",
                    "source_tier": "T1",
                    "article_or_section": "第四条",
                    "effective_status": "effective",
                    "exact_quote": "第四条 歧义法源二用于支撑第二个争点，文本足够长以满足规则原文要求。",
                    "pinpoint": "第四条",
                    "language": "zh-CN",
                    "verification_status": "verified_official",
                    "use_for_load_bearing": True,
                    "not_load_bearing_reason": "",
                    "url": "https://example.test/4",
                },
            ],
            "unresolved_source_gaps": [],
        },
        next_agent="A3",
        reason="test",
    )
    evidence_matrix = make_envelope(
        agent="A3",
        artifact_id="evidence_matrix",
        writes={
            "facts": [{"fact_id": "F01", "statement": "测试事实", "evidence_ids": ["E01"], "status": "partially_verified"}],
            "evidence_items": [{"evidence_id": "E01", "source_type": "user_material", "locator": "用户问题", "excerpt": "测试事实", "read_status": "read"}],
            "issue_evidence_matrix": [],
            "material_read_status": [],
            "missing_materials": [],
        },
        next_agent="A4",
        reason="test",
    )
    put_artifact(state, "scope_brief", scope)
    put_artifact(state, "source_pack", source_pack)
    put_artifact(state, "evidence_matrix", evidence_matrix)

    artifact = make_envelope(
        agent="A4",
        artifact_id="analysis_draft",
        writes={
            "issue_analysis": [
                {"issue_id": "I01", "conclusion": "第一个争点", "reasoning": "推理", "source_ids": ["S03", "S01"], "evidence_ids": ["E01"], "certainty": "medium"},
                {"issue_id": "I02", "conclusion": "第二个争点", "reasoning": "推理", "source_ids": ["S03", "S01"], "evidence_ids": ["E01"], "certainty": "medium"},
            ],
            "risk_register": [
                {"risk_id": "R01", "title": "第一个风险", "level": "high", "priority": "P0", "source_ids": ["S03", "S01"], "evidence_ids": ["E01"]},
                {"risk_id": "R02", "title": "第二个风险", "level": "high", "priority": "P0", "source_ids": ["S03", "S01"], "evidence_ids": ["E01"]},
            ],
            "action_plan": [
                {"action_id": "A01", "priority": "P0", "owner": "用户", "description": "向平台提交投诉并请求删除。", "depends_on": ["A04"]},
                {"action_id": "A02", "priority": "P0", "owner": "用户", "description": "证据保全：先截图录屏保存传播页面。", "depends_on": []},
                {"action_id": "A03", "priority": "紧急", "owner": "用户", "description": "立即止损：停止继续传播。", "depends_on": []},
                {"action_id": "A04", "priority": "P1", "owner": "用户", "description": "主动沟通并书面说明情况。", "depends_on": []},
                {"action_id": "A05", "priority": "P1", "owner": "用户", "description": "协商赔偿和解方案。", "depends_on": []},
                {"action_id": "A06", "priority": "P2", "owner": "用户", "description": "长期预防：建立授权审查机制。", "depends_on": []},
            ],
            "report_markdown": "## 核心结论\n本段误写 source_pack、A1 和 artifact，但应被清洗。\n\n## 法律依据与类案参考\n测试\n\n## 行动建议\n测试\n\n## 待核验材料\n测试\n\nAI生成，仅供参考",
            "citation_index": [{"citation_tag": "〔S01,第一条〕", "source_id": "S01"}],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent="A5",
        reason="test",
    )
    normalized = LegalAnalysisDraftAgent("", "")._normalize_analysis_artifact(state, artifact)["writes"]

    assert normalized["issue_analysis"][1]["source_ids"] == ["S02"]
    assert normalized["risk_register"][1]["source_ids"] == ["S02"]
    assert "S03" not in normalized["issue_analysis"][0]["source_ids"]
    assert "S03" not in normalized["issue_analysis"][1]["source_ids"]
    descriptions = [action["description"] for action in normalized["action_plan"]]
    assert descriptions == [
        "向平台提交投诉并请求删除。",
        "证据保全：先截图录屏保存传播页面。",
        "立即止损：停止继续传播。",
        "主动沟通并书面说明情况。",
        "协商赔偿和解方案。",
        "长期预防：建立授权审查机制。",
    ]
    assert normalized["action_plan"][2]["priority"] == "P1"
    assert all(action["depends_on"] == [] for action in normalized["action_plan"])


def test_a4_maps_fact_ids_to_valid_evidence_ids_and_drops_unknowns():
    from app.service.deep_research_v2.agents.legal_workflow import LegalAnalysisDraftAgent, QualityRoutingAgent
    from app.service.deep_research_v2.state import put_artifact
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = {"query": "测试", "session_id": "s1"}
    scope = make_envelope(
        agent="A1",
        artifact_id="scope_brief",
        writes={
            "task_type": "model_defined_test",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": [], "why_unknown": ""},
            "issue_tree": [
                {"issue_id": "I01", "question": "第一个争点", "priority": "P0", "evidence_needed": []},
                {"issue_id": "I02", "question": "第二个争点", "priority": "P1", "evidence_needed": []},
                {"issue_id": "I03", "question": "第三个争点", "priority": "P1", "evidence_needed": []},
            ],
            "facts_known": ["测试事实"],
            "facts_assumed": [],
            "facts_missing": [],
            "source_targets": ["测试"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent="A2",
        reason="test",
    )
    source_pack = make_envelope(
        agent="A2",
        artifact_id="source_pack",
        writes={
            "issue_sources": [
                {
                    "issue_id": f"I{index:02d}",
                    "proposition": f"争点 {index} 依据",
                    "source_id": f"S{index:02d}",
                    "jurisdiction": "中国大陆",
                    "title": f"测试法源 {index}",
                    "issuing_body": "机关",
                    "source_kind": "law",
                    "source_tier": "T1",
                    "article_or_section": f"第{index}条",
                    "effective_status": "effective",
                    "exact_quote": f"第{index}条 测试法源规则原文足够长，可以支撑争点 {index} 的初步判断。",
                    "pinpoint": f"第{index}条",
                    "language": "zh-CN",
                    "verification_status": "verified_official",
                    "use_for_load_bearing": True,
                    "not_load_bearing_reason": "",
                    "url": f"https://example.test/{index}",
                }
                for index in range(1, 4)
            ],
            "unresolved_source_gaps": [],
        },
        next_agent="A3",
        reason="test",
    )
    evidence_matrix = make_envelope(
        agent="A3",
        artifact_id="evidence_matrix",
        writes={
            "facts": [
                {"fact_id": "F03", "statement": "事实三", "evidence_ids": ["E01"], "status": "partially_verified"},
                {"fact_id": "F04", "statement": "事实四", "evidence_ids": ["E02"], "status": "partially_verified"},
                {"fact_id": "F07", "statement": "事实七", "evidence_ids": ["E01"], "status": "partially_verified"},
            ],
            "evidence_items": [
                {"evidence_id": "E01", "source_type": "user_material", "locator": "用户问题", "excerpt": "材料一", "read_status": "read"},
                {"evidence_id": "E02", "source_type": "user_material", "locator": "用户问题", "excerpt": "材料二", "read_status": "read"},
            ],
            "issue_evidence_matrix": [],
            "material_read_status": [],
            "missing_materials": [],
        },
        next_agent="A4",
        reason="test",
    )
    put_artifact(state, "scope_brief", scope)
    put_artifact(state, "source_pack", source_pack)
    put_artifact(state, "evidence_matrix", evidence_matrix)

    analysis = make_envelope(
        agent="A4",
        artifact_id="analysis_draft",
        writes={
            "issue_analysis": [
                {"issue_id": "I01", "conclusion": "结论一", "reasoning": "推理一", "source_ids": ["S01"], "evidence_ids": ["E01", "F03", "F07", "BAD01"], "certainty": "medium"},
                {"issue_id": "I02", "conclusion": "结论二", "reasoning": "推理二", "source_ids": ["S02"], "evidence_ids": ["F04"], "certainty": "medium"},
                {"issue_id": "I03", "conclusion": "结论三", "reasoning": "推理三", "source_ids": ["S03"], "evidence_ids": ["F99", "BAD01"], "certainty": "low"},
            ],
            "risk_register": [
                {"risk_id": "R01", "title": "风险一", "level": "high", "priority": "P0", "source_ids": ["S01"], "evidence_ids": ["F03", "UNKNOWN"]},
                {"risk_id": "R02", "title": "风险二", "level": "medium", "priority": "P1", "source_ids": ["S02"], "evidence_ids": ["F04"]},
            ],
            "action_plan": [
                {"action_id": f"A{index}", "priority": "P1", "owner": "用户", "description": f"具体动作 {index}", "depends_on": []}
                for index in range(6)
            ],
            "report_markdown": "## 核心结论\n测试结论。\n\n## 法律依据与类案参考\n测试来源。\n\n## 行动建议\n测试行动。\n\nAI生成，仅供参考",
            "citation_index": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent="A5",
        reason="test",
    )
    normalized_artifact = LegalAnalysisDraftAgent("", "")._normalize_analysis_artifact(state, analysis)
    normalized = normalized_artifact["writes"]

    assert normalized["issue_analysis"][0]["evidence_ids"] == ["E01"]
    assert normalized["issue_analysis"][1]["evidence_ids"] == ["E02"]
    assert normalized["issue_analysis"][2]["evidence_ids"] == ["E01"]
    assert normalized["risk_register"][0]["evidence_ids"] == ["E01"]
    assert normalized["risk_register"][1]["evidence_ids"] == ["E02"]

    put_artifact(state, "analysis_draft", normalized_artifact)
    verdict = QualityRoutingAgent("", "")._deterministic_verdict(state)["writes"]
    assert not any("evidence_matrix 外证据" in failure for failure in verdict["hard_failures"])


def test_prompts_cover_qa_quality_findings():
    from app.service.deep_research_v2.prompts.legal_prompts import A4_ANALYSIS_SYSTEM_PROMPT, A5_QA_SYSTEM_PROMPT

    assert "绑定具体 source_id" in A4_ANALYSIS_SYSTEM_PROMPT
    assert "F 编号只是 facts 的事实编号" in A4_ANALYSIS_SYSTEM_PROMPT
    assert "行动建议必须按执行顺序组织" in A4_ANALYSIS_SYSTEM_PROMPT
    assert "每项必须说明：缺什么材料、影响哪个结论" in A4_ANALYSIS_SYSTEM_PROMPT
    assert "可比来源没有绑定 source_id" in A5_QA_SYSTEM_PROMPT
    assert "行动建议执行顺序混乱" in A5_QA_SYSTEM_PROMPT
    assert "待核验材料没有说明对结论强弱的影响" in A5_QA_SYSTEM_PROMPT


def test_a5_still_blocks_unknown_evidence_ids():
    from app.service.deep_research_v2.agents.legal_workflow import QualityRoutingAgent

    state = {
        "query": "测试",
        "session_id": "s1",
        "artifacts": {
            "scope_brief": {"writes": {"jurisdiction": {"primary": "中国大陆"}, "human_review": {"required": False, "reasons": []}}},
            "source_pack": {"writes": {"issue_sources": [{
                "source_id": "S01",
                "issue_id": "I01",
                "title": "测试法源",
                "source_kind": "law",
                "article_or_section": "第一条",
                "pinpoint": "第一条",
                "source_tier": "T1",
                "exact_quote": "第一条 测试法源规则原文足够长，可以承载当前结构性测试结论。",
                "use_for_load_bearing": True,
                "url": "https://example.test/law",
            }], "unresolved_source_gaps": []}},
            "evidence_matrix": {"writes": {"evidence_items": [{"evidence_id": "E01"}], "missing_materials": [], "material_read_status": []}},
            "analysis_draft": {"writes": {
                "report_markdown": "# 报告\n\n## 核心结论\n测试结论。\n\n## 法律依据与类案参考\n测试来源。\n\n## 行动建议\n行动\n\nAI生成，仅供参考",
                "risk_register": [{"risk_id": "R01", "title": "测试风险", "level": "high", "priority": "P0", "source_ids": ["S01"], "evidence_ids": ["E99"]}],
                "issue_analysis": [{"issue_id": "I01", "source_ids": ["S01"], "evidence_ids": ["E99"]}],
                "action_plan": [{"action_id": f"A{i}", "priority": "P1", "owner": "用户", "description": f"具体动作 {i}", "depends_on": []} for i in range(6)],
                "human_review": {"required": False, "reasons": []},
            }},
        },
    }
    verdict = QualityRoutingAgent("", "")._deterministic_verdict(state)["writes"]

    assert verdict["verdict"] == "needs_evidence_rebuild"
    assert any("E99" in failure and "evidence_matrix 外证据" in failure for failure in verdict["hard_failures"])


def test_a5_blocks_bad_report_and_llm_approval_override():
    from app.service.deep_research_v2.agents.legal_workflow import QualityRoutingAgent
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    qa = QualityRoutingAgent("", "")
    state = {
        "query": "测试",
        "session_id": "s1",
        "artifacts": {
            "scope_brief": {"writes": {"jurisdiction": {"primary": "中国大陆"}, "human_review": {"required": False, "reasons": []}}},
            "source_pack": {"writes": {"issue_sources": [{
                "source_id": "S01",
                "issue_id": "I01",
                "title": "中华人民共和国个人信息保护法",
                "article_or_section": "待定位",
                "pinpoint": "待定位",
                "source_tier": "T1",
                "exact_quote": "个人信息处理者处理个人信息应当遵循合法、正当、必要和诚信原则。",
                "use_for_load_bearing": True,
                "url": "https://www.cac.gov.cn/test",
            }], "unresolved_source_gaps": []}},
            "evidence_matrix": {"writes": {"evidence_items": [{"evidence_id": "E01"}], "missing_materials": ["关键材料"], "material_read_status": []}},
            "analysis_draft": {"writes": {
                "report_markdown": "# 报告\n\n## 核心结论\n测试结论。\n\n## 法律依据与类案参考\n测试来源。\n\n## 行动建议\n行动\n\nAI生成，仅供参考",
                "risk_register": [{"risk_id": "R01", "title": "是否有风险？", "level": "high", "priority": "P0", "source_ids": ["S01"], "evidence_ids": ["E01"]}],
                "issue_analysis": [{"issue_id": "I01", "source_ids": ["S01"]}],
                "action_plan": [{"action_id": f"A{i}", "priority": "P0", "owner": "用户", "description": "重复动作", "depends_on": []} for i in range(6)],
                "human_review": {"required": False, "reasons": []},
            }},
        },
    }
    deterministic = qa._deterministic_verdict(state)
    llm_approved = make_envelope(
        agent="A5",
        artifact_id="qa_verdict",
        writes={
            "score_total": 99,
            "dimension_scores": {"jurisdiction_scope": 14, "source_accuracy": 30, "evidence_closure": 20, "phase_discipline": 10, "reasoning_quality": 15, "readability": 10},
            "hard_failures": [],
            "issues": [],
            "verdict": "approved",
            "route": {"next_agent": "END", "instruction": "通过。"},
        },
        next_agent="END",
        reason="test",
    )
    merged = qa._merge_hard_gates(llm_approved, deterministic)

    assert deterministic["writes"]["verdict"] != "approved"
    assert merged["writes"]["verdict"] == deterministic["writes"]["verdict"]


def test_a5_qa_shape_coercion():
    from app.service.deep_research_v2.agents.legal_workflow import _coerce_qa_shape

    artifact = {
        "writes": {
            "hard_failures": [{"message": "缺少条号"}],
            "issues": [{"level": "major", "id": "source_gap", "description": "补法源", "next_agent": "A2"}],
        }
    }
    coerced = _coerce_qa_shape(artifact)

    assert coerced["writes"]["hard_failures"] == ["缺少条号"]
    assert coerced["writes"]["issues"][0]["route_to"] == "A2"
    assert coerced["writes"]["issues"][0]["type"] == "source_gap"


def main():
    test_legal_config()
    test_state_defaults()
    test_llm_legal_defaults()
    test_risk_scoring()
    test_citation_verifier()
    test_evidence_placeholder_detection()
    test_legacy_task_matchers_removed()
    test_source_tier_normalize()
    test_preliminary_source_supports_mirror_rule_text()
    test_writer_skeleton()
    test_critic_verdict_normalize()
    test_critic_allows_model_when_no_structural_failure()
    test_graph_import()
    test_a1_model_defined_task_type_and_short_source_targets()
    test_a2_short_query_builder()
    test_a2_source_gap_shape_coercion()
    test_a2_downgrades_unpinpointed_load_bearing_source()
    test_a2_source_gaps_are_structural_not_topic_keyword_based()
    test_a2_normalizes_duplicate_source_ids()
    test_a2_merge_preserves_better_previous_source()
    test_a3_user_statement_is_partially_verified()
    test_a3_missing_materials_object_coercion()
    test_a4_analysis_nested_writes_coercion()
    test_a4_analysis_nested_envelope_coercion()
    test_a4_fallback_is_user_facing_and_not_template_bound()
    test_a4_fallback_does_not_inject_legacy_topic_templates()
    test_a4_fallback_addresses_qa_quality_findings()
    test_a4_normalizes_action_order_and_issue_source_binding()
    test_a4_maps_fact_ids_to_valid_evidence_ids_and_drops_unknowns()
    test_prompts_cover_qa_quality_findings()
    test_a5_still_blocks_unknown_evidence_ids()
    test_a5_blocks_bad_report_and_llm_approval_override()
    test_a5_qa_shape_coercion()
    print("All legal research component tests passed.")


if __name__ == "__main__":
    main()
