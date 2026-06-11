"""Smoke tests for the decoupled legal artifact workflow."""

from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEEP_RESEARCH_TRACE_ENABLED", "false")


LEGAL_QUERY = (
    "我是一名个人自由职业者，客户给我身份证照片、微信聊天记录、合同材料和商业合作信息，"
    "我没有提前告知客户并取得明确同意，就上传到第三方 AI 工具整理和生成协议草稿。"
    "客户担心信息被保存或泄露，要求说明法律风险。"
)


def _fake_legal_search(query, max_results=5, include_raw_content=True, bocha_api_key=None):
    return {
        "query": query,
        "attempts": [{"provider": "tavily", "query": query, "status": "ok", "result_count": 2, "error": ""}],
        "providers_used": ["tavily"],
        "tool_errors": 0,
        "results": [
            {
                "provider": "tavily",
                "query": query,
                "title": "中华人民共和国个人信息保护法_中国人大网",
                "url": "https://example.test/pipl",
                "content": "个人信息处理者处理个人信息前，应当向个人告知处理目的、处理方式和个人信息种类。",
                "raw_content": "个人信息处理者向其他个人信息处理者提供其处理的个人信息的，应当告知接收方信息并取得个人的单独同意。",
                "score": 0.98,
                "published_date": "2021-08-20",
            },
            {
                "provider": "tavily",
                "query": query,
                "title": "中华人民共和国民法典_中国人大网",
                "url": "https://example.test/civil-code",
                "content": "当事人应当按照约定全面履行自己的义务，并遵循诚信原则。",
                "raw_content": "履行合同过程中应当避免损害对方利益。",
                "score": 0.95,
                "published_date": "2020-06-01",
            },
        ],
    }


async def main():
    import app.service.deep_research_v2.agents.source_verification as source_module
    from app.service.deep_research_v2.artifact_schemas import make_envelope
    from app.service.deep_research_v2.agents.workflow_utils import (
        END,
        EVIDENCE_CATALOG,
        LEGAL_ANALYSIS_DRAFT,
        QUALITY_ROUTING,
        SCOPE_DEFINITION,
        SOURCE_VERIFICATION,
    )
    from app.service.deep_research_v2.graph import DeepResearchGraph

    source_module.perform_legal_search = _fake_legal_search

    graph = DeepResearchGraph(
        llm_api_key="test-key",
        llm_base_url="http://127.0.0.1:9/v1",
        model="mock-model",
        max_iterations=0,
    )

    async def _mock_llm(self, *args, **kwargs):
        if getattr(self, "agent_id", "") == SCOPE_DEFINITION:
            return make_envelope(
                agent=SCOPE_DEFINITION,
                artifact_id="scope_brief",
                writes={
                    "task_type": "ai_tool_client_material_privacy_compliance",
                    "jurisdiction": {
                        "primary": "中国大陆",
                        "others": [],
                        "status": "assumed",
                        "jurisdiction_candidates": ["中国大陆"],
                        "why_unknown": "",
                    },
                    "issue_tree": [
                        {"issue_id": "I01", "question": "未经告知同意上传客户材料是否涉及个人信息处理合法性", "priority": "P0", "evidence_needed": ["客户授权记录", "上传材料范围"]},
                        {"issue_id": "I02", "question": "身份证照片和转账记录是否属于敏感个人信息并需要更高同意要求", "priority": "P0", "evidence_needed": ["身份证照片范围", "转账记录内容"]},
                        {"issue_id": "I03", "question": "使用第三方 AI 工具是否构成委托处理或向第三方提供", "priority": "P0", "evidence_needed": ["AI 工具服务条款", "平台隐私政策"]},
                    ],
                    "facts_known": [LEGAL_QUERY],
                    "facts_assumed": ["若未特别说明，默认适用中国大陆法域。"],
                    "facts_missing": ["AI 工具名称", "平台隐私政策和训练条款", "实际上传材料范围", "是否已经删除", "是否实际泄露"],
                    "source_targets": ["个人信息处理 告知同意", "敏感个人信息 单独同意", "委托处理 第三方提供"],
                    "clarification_questions": ["AI 工具名称是什么？", "是否已向平台申请删除？"],
                    "human_review": {"required": True, "reasons": ["涉及客户身份信息和第三方平台条款。"]},
                },
                next_agent=SOURCE_VERIFICATION,
                reason="mock scope",
            )
        if getattr(self, "agent_id", "") == SOURCE_VERIFICATION:
            sources = [
                ("I01", "S01", "中华人民共和国个人信息保护法", "第十七条", "个人信息处理者在处理个人信息前，应当向个人告知处理目的、处理方式和个人信息种类。"),
                ("I02", "S02", "中华人民共和国个人信息保护法", "第二十九条", "处理敏感个人信息应当取得个人的单独同意。"),
                ("I03", "S03", "中华人民共和国个人信息保护法", "第二十三条", "个人信息处理者向其他个人信息处理者提供个人信息的，应当告知接收方信息并取得个人的单独同意。"),
            ]
            return make_envelope(
                agent=SOURCE_VERIFICATION,
                artifact_id="source_pack",
                writes={
                    "issue_sources": [{
                        "issue_id": issue_id,
                        "proposition": title,
                        "source_id": source_id,
                        "jurisdiction": "中国大陆",
                        "title": title,
                        "issuing_body": "全国人大或主管机关",
                        "source_kind": "law",
                        "source_tier": "T1",
                        "article_or_section": article,
                        "effective_status": "effective",
                        "exact_quote": quote,
                        "pinpoint": article,
                        "language": "zh-CN",
                        "verification_status": "verified_official",
                        "use_for_load_bearing": True,
                        "not_load_bearing_reason": "",
                        "url": f"https://example.test/{source_id}",
                    } for issue_id, source_id, title, article, quote in sources],
                    "unresolved_source_gaps": [],
                },
                next_agent=EVIDENCE_CATALOG,
                reason="mock source pack",
            )
        raise RuntimeError("offline test forces deterministic fallback")

    for agent in graph.agents_by_code.values():
        agent._call_json = types.MethodType(_mock_llm, agent)

    events = []
    async for event in graph.run(
        LEGAL_QUERY,
        "test-five-agent-workflow",
        search_web=True,
        search_local=False,
    ):
        events.append(event)

    complete = next((event for event in events if event.get("type") == "research_complete"), None)
    assert complete, "research_complete event missing"
    phases = [event.get("phase") for event in events if event.get("type") == "phase"]
    for phase in ["planning", "researching", "analyzing", "writing", "reviewing"]:
        assert phase in phases, f"phase missing: {phase}"

    artifacts = complete.get("artifacts") or {}
    for key in ["scope_brief", "source_pack", "evidence_matrix", "analysis_draft", "qa_verdict"]:
        assert key in artifacts and artifacts[key], f"artifact missing: {key}"

    report = complete.get("final_report", "")
    assert report.strip().endswith("AI生成，仅供参考")
    assert "## 核心结论" in report
    assert len(report) >= 1000
    assert complete.get("references"), "references should come from source_pack"

    verdict = (complete.get("qa_verdict") or {}).get("verdict")
    assert verdict in {"approved", "approved_with_human_review"}, f"unexpected verdict: {verdict}"
    assert complete.get("quality_score", 0) >= 80

    agent_names = [
        artifacts[key].get("meta", {}).get("agent")
        for key in ["scope_brief", "source_pack", "evidence_matrix", "analysis_draft", "qa_verdict"]
    ]
    assert agent_names == [SCOPE_DEFINITION, SOURCE_VERIFICATION, EVIDENCE_CATALOG, LEGAL_ANALYSIS_DRAFT, QUALITY_ROUTING], agent_names
    assert (complete.get("qa_verdict") or {}).get("route", {}).get("next_agent") in {END, LEGAL_ANALYSIS_DRAFT, SOURCE_VERIFICATION, EVIDENCE_CATALOG}
    print("decoupled legal workflow smoke test passed")


if __name__ == "__main__":
    asyncio.run(main())
