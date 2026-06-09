"""Smoke tests for the five-agent legal artifact workflow."""

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


def _fake_tavily_search(query, topic="general", max_results=5, include_raw_content=True, timeout=30, api_key=None):
    return {
        "query": query,
        "results": [
            {
                "title": "中华人民共和国个人信息保护法_中国人大网",
                "url": "https://www.gov.cn/xinwen/2021-08/20/content_5632486.htm",
                "content": "个人信息处理者处理个人信息前，应当以显著方式、清晰易懂的语言真实、准确、完整地向个人告知处理目的、处理方式、处理的个人信息种类、保存期限等。",
                "raw_content": "个人信息处理者向其他个人信息处理者提供其处理的个人信息的，应当向个人告知接收方的名称或者姓名、联系方式、处理目的、处理方式和个人信息的种类，并取得个人的单独同意。",
                "score": 0.98,
                "published_date": "2021-08-20",
            },
            {
                "title": "中华人民共和国民法典_中国人大网",
                "url": "https://www.gov.cn/xinwen/2020-06/01/content_5516649.htm",
                "content": "民事主体从事民事活动，应当遵循诚信原则。合同相关义务包括按照约定履行义务并保护相对方合法权益。",
                "raw_content": "当事人应当按照约定全面履行自己的义务。履行合同过程中应当避免损害对方利益。",
                "score": 0.95,
                "published_date": "2020-06-01",
            },
        ],
    }


async def main():
    from app.service.deep_research_v2.agents import legal_workflow as workflow_module
    from app.service.deep_research_v2.artifact_schemas import make_envelope
    from app.service.deep_research_v2.graph import DeepResearchGraph

    workflow_module.perform_internet_search = _fake_tavily_search

    graph = DeepResearchGraph(
        llm_api_key="test-key",
        llm_base_url="http://127.0.0.1:9/v1",
        model="mock-model",
        max_iterations=0,
    )

    async def _mock_llm(self, *args, **kwargs):
        if getattr(self, "agent_code", "") == "A1":
            return make_envelope(
                agent="A1",
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
                        {"issue_id": "I04", "question": "聊天记录和商业合作信息是否涉及隐私、保密义务或商业秘密", "priority": "P1", "evidence_needed": ["聊天记录范围", "委托或保密约定"]},
                        {"issue_id": "I05", "question": "未发生确定泄露时民事责任、行政责任和补救义务如何划分", "priority": "P1", "evidence_needed": ["是否保存训练", "是否删除", "是否实际泄露"]},
                    ],
                    "facts_known": [LEGAL_QUERY],
                    "facts_assumed": ["若未特别说明，默认适用中国大陆法域。"],
                    "facts_missing": ["AI 工具名称", "平台隐私政策和训练条款", "实际上传材料范围", "是否已经删除", "是否实际泄露"],
                    "source_targets": ["个人信息处理 告知同意", "敏感个人信息 单独同意", "委托处理 第三方提供", "隐私权 保密义务", "泄露补救 损害赔偿"],
                    "clarification_questions": ["AI 工具名称是什么？", "是否已向平台申请删除？", "客户是否签过保密或授权文件？"],
                    "human_review": {"required": True, "reasons": ["涉及客户身份信息、第三方平台条款和潜在损害后果。"]},
                },
                next_agent="A2",
                reason="mock scope",
            )
        if getattr(self, "agent_code", "") == "A2":
            sources = [
                ("I01", "S01", "中华人民共和国个人信息保护法", "第十七条", "个人信息处理者在处理个人信息前，应当以显著方式、清晰易懂的语言真实、准确、完整地向个人告知处理目的、处理方式和个人信息种类。"),
                ("I02", "S02", "中华人民共和国个人信息保护法", "第二十八条", "敏感个人信息是一旦泄露或者非法使用，容易导致自然人的人格尊严受到侵害或者人身、财产安全受到危害的个人信息。"),
                ("I02", "S03", "中华人民共和国个人信息保护法", "第二十九条", "处理敏感个人信息应当取得个人的单独同意；法律、行政法规规定处理敏感个人信息应当取得书面同意的，从其规定。"),
                ("I03", "S04", "中华人民共和国个人信息保护法", "第二十一条", "个人信息处理者委托处理个人信息的，应当与受托人约定委托处理的目的、期限、处理方式、个人信息的种类、保护措施以及双方的权利和义务。"),
                ("I03", "S05", "中华人民共和国个人信息保护法", "第二十三条", "个人信息处理者向其他个人信息处理者提供其处理的个人信息的，应当向个人告知接收方的名称或者姓名、联系方式、处理目的、处理方式和个人信息的种类，并取得个人的单独同意。"),
                ("I04", "S06", "中华人民共和国民法典", "第一千零三十四条", "自然人的个人信息受法律保护。个人信息是以电子或者其他方式记录的能够单独或者与其他信息结合识别特定自然人的各种信息。"),
                ("I05", "S07", "中华人民共和国民法典", "第五百零九条", "当事人应当按照约定全面履行自己的义务。当事人应当遵循诚信原则，根据合同的性质、目的和交易习惯履行通知、协助、保密等义务。"),
                ("I06", "S08", "中华人民共和国个人信息保护法", "第六十九条", "处理个人信息侵害个人信息权益造成损害，个人信息处理者不能证明自己没有过错的，应当承担损害赔偿等侵权责任。"),
                ("I07", "S09", "中华人民共和国个人信息保护法", "第五十七条", "发生或者可能发生个人信息泄露、篡改、丢失的，个人信息处理者应当立即采取补救措施，并通知履行个人信息保护职责的部门和个人。"),
            ]
            return make_envelope(
                agent="A2",
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
                        "url": "https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm",
                    } for issue_id, source_id, title, article, quote in sources],
                    "unresolved_source_gaps": [],
                },
                next_agent="A3",
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
    assert "不构成正式法律意见" not in report
    assert "免责声明" not in report
    assert "## 核心结论" in report
    assert len(report) >= 2500
    assert "敏感个人信息" in report
    assert "第三方" in report
    assert "保密义务" in report
    assert "补救" in report
    assert "source_pack" not in report and "evidence_matrix" not in report and "工件" not in report
    assert complete.get("references"), "references should come from source_pack"

    verdict = (complete.get("qa_verdict") or {}).get("verdict")
    assert verdict in {"approved", "approved_with_human_review"}, f"unexpected verdict: {verdict}"
    assert complete.get("quality_score", 0) >= 80

    agent_names = [
        artifacts[key].get("meta", {}).get("agent")
        for key in artifacts
        if artifacts.get(key)
    ]
    assert agent_names == ["A1", "A2", "A3", "A4", "A5"], agent_names
    print("five-agent legal workflow smoke test passed")


if __name__ == "__main__":
    asyncio.run(main())
