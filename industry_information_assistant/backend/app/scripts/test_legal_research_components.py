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

    assert _source_tier("https://www.cac.gov.cn/test", "中华人民共和国个人信息保护法", "法律原文")[0] == "T1"
    assert _source_tier("https://www.cqck.gov.cn/test", "民法典解读", "亮点梳理")[0] == "T4"


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
                "report_markdown": "## 核心结论\n个人信息 敏感个人信息 第三方 转委托 保密义务 违约 侵权 补救\n\n## 法律依据与类案参考\n案例\n\n## 行动建议\n行动\n\nAI生成，仅供参考",
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

    query = "我把客户身份证照片、聊天记录和合同上传到第三方 AI 工具，未取得明确同意，有什么风险？"
    agent = ScopeDefinitionAgent("", "")
    artifact = make_envelope(
        agent="A1",
        artifact_id="scope_brief",
        writes={
            "task_type": "AI Deepfake / Personal Information Compliance",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": [], "why_unknown": ""},
            "issue_tree": [{"issue_id": "I01", "question": query, "priority": "P0", "evidence_needed": []}],
            "facts_known": [query],
            "facts_assumed": [],
            "facts_missing": [],
            "source_targets": ["《个人信息保护法》第二十三条：向其他个人信息处理者提供个人信息时需要告知并取得单独同意"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent="A2",
        reason="test",
    )
    normalized = agent._normalize_scope_artifact(artifact, {"query": query, "session_id": "s1"})
    targets = normalized["writes"]["source_targets"]

    assert normalized["writes"]["task_type"] == "ai_deepfake_personal_information_compliance"
    assert all("《" not in target and "第二十三条" not in target for target in targets)
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
            "task_type": "model_defined_privacy_ai_upload",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": [], "why_unknown": ""},
            "issue_tree": [{
                "issue_id": "I01",
                "question": "用户作为数据处理者（受托处理个人信息），其向第三方AI工具提供客户个人信息的行为，是否构成《个人信息保护法》下的委托处理或向其他个人信息处理者提供？是否需要单独同意？",
                "priority": "P0",
                "evidence_needed": [],
            }],
            "facts_known": ["用户陈述"],
            "facts_assumed": [],
            "facts_missing": [],
            "source_targets": ["第三方提供 个人信息"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent="A2",
        reason="test",
    )
    put_artifact(state, "scope_brief", scope)

    queries = SourceVerificationAgent("", "")._build_search_queries(state)
    assert any("第三方提供 个人信息 官方" in query for query in queries)
    assert any("典型案例" in query or "裁判规则" in query or "判决" in query for query in queries)
    assert not any("用户作为数据处理者" in query for query in queries)
    assert not any("第二十三条" in query for query in queries)


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
                "title": "中华人民共和国个人信息保护法",
                "issuing_body": "官方",
                "source_kind": "law",
                "source_tier": "T1",
                "article_or_section": "待定位",
                "effective_status": "effective",
                "exact_quote": "个人信息处理者处理个人信息应当遵循合法、正当、必要和诚信原则。",
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


def test_a2_merge_preserves_better_previous_source():
    from app.service.deep_research_v2.agents.legal_workflow import SourceVerificationAgent
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = {"query": "测试", "session_id": "s1", "artifacts": {"scope_brief": {"writes": {"issue_tree": [{"issue_id": "I01"}]}}}}
    previous = {
        "issue_sources": [{
            "issue_id": "I01",
            "proposition": "第三方提供",
            "source_id": "S09",
            "jurisdiction": "中国大陆",
            "title": "中华人民共和国个人信息保护法",
            "issuing_body": "全国人大",
            "source_kind": "law",
            "source_tier": "T1",
            "article_or_section": "第二十三条",
            "effective_status": "effective",
            "exact_quote": "个人信息处理者向其他个人信息处理者提供其处理的个人信息的，应当向个人告知接收方的名称或者姓名、联系方式、处理目的、处理方式和个人信息的种类，并取得个人的单独同意。",
            "pinpoint": "第二十三条",
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
                "proposition": "第三方提供",
                "source_id": "S01",
                "jurisdiction": "中国大陆",
                "title": "个人信息保护法解读",
                "issuing_body": "地方政府",
                "source_kind": "law",
                "source_tier": "T1",
                "article_or_section": "待定位",
                "effective_status": "unknown",
                "exact_quote": "首页 登录 注册 个人信息保护法解读",
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

    assert any(source["article_or_section"] == "第二十三条" and source["use_for_load_bearing"] for source in merged["writes"]["issue_sources"])


def test_a3_user_statement_is_partially_verified():
    from app.service.deep_research_v2.agents.legal_workflow import EvidenceCatalogAgent
    from app.service.deep_research_v2.state import put_artifact
    from app.service.deep_research_v2.artifact_schemas import make_envelope

    state = {"query": "用户陈述", "session_id": "s1"}
    scope = make_envelope(
        agent="A1",
        artifact_id="scope_brief",
        writes={
            "task_type": "model_defined_privacy_ai_upload",
            "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": [], "why_unknown": ""},
            "issue_tree": [{"issue_id": "I01", "question": "测试", "priority": "P0", "evidence_needed": ["平台条款"]}],
            "facts_known": ["用户说自己上传了材料"],
            "facts_assumed": [],
            "facts_missing": ["AI 工具名称"],
            "source_targets": ["个人信息保护法"],
            "clarification_questions": [],
            "human_review": {"required": False, "reasons": []},
        },
        next_agent="A2",
        reason="test",
    )
    put_artifact(state, "scope_brief", scope)
    artifact = EvidenceCatalogAgent("", "")._fallback(state)

    assert artifact["writes"]["facts"][0]["status"] == "partially_verified"
    assert "AI 工具名称" in artifact["writes"]["missing_materials"]
    assert "平台条款" in artifact["writes"]["missing_materials"]


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


def test_a4_fallback_is_user_facing_and_not_template_bound():
    from app.service.deep_research_v2.agents.legal_workflow import LegalAnalysisDraftAgent

    state = {"query": "未经同事同意用 AI 换脸和配音制作搞笑视频并被转发", "session_id": "s1"}
    artifact = LegalAnalysisDraftAgent("", "")._fallback(state)
    report = artifact["writes"]["report_markdown"]
    actions = artifact["writes"]["action_plan"]

    assert report.strip().endswith("AI生成，仅供参考")
    assert "不构成正式法律意见" not in report
    assert "免责声明" not in report
    assert "source_pack" not in report and "evidence_matrix" not in report and "工件" not in report
    assert "核心结论" in report and "法律依据" in report and "行动建议" in report
    assert "不能直接等同于“已经发生泄露”" not in report
    assert len({action["description"] for action in actions}) >= 6
    assert not any(action["description"] == "补齐事实材料、保留处理记录，并在取得明确授权或完成法源复核后再对外作确定性表述。" for action in actions)


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
            "evidence_matrix": {"writes": {"evidence_items": [{"evidence_id": "E01"}], "missing_materials": ["平台条款"], "material_read_status": []}},
            "analysis_draft": {"writes": {
                "report_markdown": "# 报告\n\n## 核心结论\n本报告基于 source_pack 和 evidence_matrix。暂无额外待核验事项。\n\n## 法律依据与类案参考\n案例\n\n## 行动建议\n行动\n\nAI生成，仅供参考",
                "risk_register": [{"risk_id": "R01", "title": "是否有风险？", "level": "high", "priority": "P0", "source_ids": ["S01"], "evidence_ids": ["E01"]}],
                "issue_analysis": [{"issue_id": "I01", "source_ids": ["S01"]}],
                "action_plan": [{"action_id": f"A{i}", "priority": "P0", "owner": "用户", "description": "补齐事实材料、保留处理记录，并在取得明确授权或完成法源复核后再对外作确定性表述。", "depends_on": []} for i in range(6)],
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
    test_a2_merge_preserves_better_previous_source()
    test_a3_user_statement_is_partially_verified()
    test_a3_missing_materials_object_coercion()
    test_a4_analysis_nested_writes_coercion()
    test_a4_fallback_is_user_facing_and_not_template_bound()
    test_a4_fallback_does_not_inject_legacy_topic_templates()
    test_a5_blocks_bad_report_and_llm_approval_override()
    test_a5_qa_shape_coercion()
    print("All legal research component tests passed.")


if __name__ == "__main__":
    main()
