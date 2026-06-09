# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Fixture-backed full-flow test for the legal DeepResearch V2 agent graph.

This script does not call external LLM or search APIs. It verifies that the new
legal agent flow can complete all phases and generate a substantive legal risk
report from explicit legal/contract materials.
"""

import asyncio
import json
import types
import uuid
from pathlib import Path

from app.service.deep_research_v2.artifact_schemas import make_envelope
from app.service.deep_research_v2.graph import DeepResearchGraph


QUERY = (
    "请从法律风控角度分析：某采购合同约定卖方逾期交付仅需退还货款，"
    "没有违约金、损失赔偿和解除权安排，买方有哪些风险并如何整改？"
)


async def run_full_flow() -> dict:
    graph = DeepResearchGraph(max_iterations=1)

    async def _mock_llm(self, *args, **kwargs):
        if getattr(self, "agent_code", "") == "A1":
            return make_envelope(
                agent="A1",
                artifact_id="scope_brief",
                writes={
                    "task_type": "procurement_contract_delivery_default_risk",
                    "jurisdiction": {"primary": "中国大陆", "others": [], "status": "assumed", "jurisdiction_candidates": ["中国大陆"], "why_unknown": ""},
                    "issue_tree": [
                        {"issue_id": "I01", "question": "逾期交付时仅退还货款是否削弱违约责任主张", "priority": "P0", "evidence_needed": ["采购合同全文", "付款记录"]},
                        {"issue_id": "I02", "question": "没有违约金和损失赔偿计算方法会造成哪些举证和赔偿风险", "priority": "P0", "evidence_needed": ["损失构成", "替代采购成本"]},
                        {"issue_id": "I03", "question": "合同未约定解除权时买方如何保留解除和替代采购空间", "priority": "P1", "evidence_needed": ["交付期限", "催告记录"]},
                        {"issue_id": "I04", "question": "应如何整改交付、验收、违约金、损失赔偿和解除条款", "priority": "P1", "evidence_needed": ["业务交付节点", "验收标准"]},
                    ],
                    "facts_known": [QUERY],
                    "facts_assumed": ["若未特别说明，默认适用中国大陆法域。"],
                    "facts_missing": ["采购合同全文", "付款金额", "交付标的价值", "替代采购成本", "验收标准"],
                    "source_targets": ["民法典 违约责任", "违约金 损失赔偿", "迟延履行 解除合同", "采购合同 验收交付"],
                    "clarification_questions": ["标的金额是多少？", "交付逾期会造成哪些业务损失？", "合同是否有催告和验收条款？"],
                    "human_review": {"required": False, "reasons": []},
                },
                next_agent="A2",
                reason="mock procurement scope",
            )
        if getattr(self, "agent_code", "") == "A2":
            sources = [
                ("I01", "S01", "中华人民共和国民法典", "第五百七十七条", "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。"),
                ("I02", "S02", "中华人民共和国民法典", "第五百八十五条", "当事人可以约定一方违约时应当根据违约情况向对方支付一定数额的违约金，也可以约定因违约产生的损失赔偿额的计算方法。"),
                ("I03", "S03", "中华人民共和国民法典", "第五百六十三条", "当事人一方迟延履行主要债务，经催告后在合理期限内仍未履行的，当事人可以解除合同。"),
                ("I04", "S04", "中华人民共和国民法典", "第五百零九条", "当事人应当按照约定全面履行自己的义务。当事人应当遵循诚信原则，根据合同的性质、目的和交易习惯履行通知、协助、保密等义务。"),
            ]
            return make_envelope(
                agent="A2",
                artifact_id="source_pack",
                writes={
                    "issue_sources": [{
                        "issue_id": issue_id,
                        "proposition": quote[:80],
                        "source_id": source_id,
                        "jurisdiction": "中国大陆",
                        "title": title,
                        "issuing_body": "全国人大",
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
                        "url": f"https://example.test/civil-code/{source_id}",
                    } for issue_id, source_id, title, article, quote in sources],
                    "unresolved_source_gaps": [],
                },
                next_agent="A3",
                reason="mock source pack",
            )
        raise RuntimeError("External LLM disabled for deterministic full-flow test.")

    for agent in graph.agents_by_code.values():
        agent._call_json = types.MethodType(_mock_llm, agent)

    session_id = f"legal-full-flow-{uuid.uuid4().hex[:8]}"
    events = []
    final_event = None
    async for event in graph.run(
        QUERY,
        session_id,
        search_web=True,
        search_local=False,
    ):
        events.append(event)
        if event.get("type") == "research_complete":
            final_event = event

    assert final_event, "research_complete event was not emitted"
    final_report = final_event.get("final_report", "")
    phases = [event.get("phase") for event in events if event.get("type") == "phase"]
    event_types = [event.get("type") for event in events]

    allowed_phases = {
        "planning",
        "researching",
        "analyzing",
        "writing",
        "reviewing",
        "re_researching",
        "revising",
        "completed",
    }
    assert set(phases).issubset(allowed_phases), f"unexpected phases: {set(phases) - allowed_phases}"
    assert "planning" in phases
    assert "researching" in phases
    assert "analyzing" in phases
    assert "writing" in phases
    assert "reviewing" in phases
    assert "research_start" in event_types
    assert final_event.get("charts_count", 0) == 0
    assert final_event.get("quality_score", 0) >= 80

    required_report_terms = [
        "逾期交付",
        "违约金",
        "损失赔偿",
        "解除权",
        "行动建议",
        "待核验材料",
        "AI生成，仅供参考",
    ]
    missing_terms = [term for term in required_report_terms if term not in final_report]
    assert not missing_terms, f"final_report missing terms: {missing_terms}"
    assert len(final_report) >= 1000, f"final_report too short: {len(final_report)}"

    output_dir = Path("/tmp/legal_agent_full_flow")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "legal_risk_deep_research_report.md"
    summary_path = output_dir / "summary.json"
    report_path.write_text(final_report, encoding="utf-8")
    summary = {
        "session_id": session_id,
        "events_count": len(events),
        "phases": phases,
        "event_types": event_types,
        "quality_score": final_event.get("quality_score"),
        "facts_count": final_event.get("facts_count"),
        "charts_count": final_event.get("charts_count"),
        "report_length": len(final_report),
        "report_path": str(report_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    summary = asyncio.run(run_full_flow())
    print("Legal agent full-flow test passed.")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
