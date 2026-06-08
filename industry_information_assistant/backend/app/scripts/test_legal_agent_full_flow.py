# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Fixture-backed full-flow test for the legal DeepResearch V2 agent graph.

This script does not call external LLM or search APIs. It verifies that the new
legal agent flow can complete all phases and generate a substantive legal risk
report from explicit legal/contract materials.
"""

import asyncio
import json
import uuid
from pathlib import Path

from app.service.deep_research_v2.graph import DeepResearchGraph


QUERY = (
    "请从法律风控角度分析：某采购合同约定卖方逾期交付仅需退还货款，"
    "没有违约金、损失赔偿和解除权安排，买方有哪些风险并如何整改？"
)


LEGAL_FIXTURE_RESULTS = [
    {
        "source_id": "law_001",
        "source_type": "law",
        "title": "中华人民共和国民法典 第五百七十七条",
        "site_name": "全国人大",
        "url": "https://example.test/civil-code/article-577",
        "summary": "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。",
        "quoted_text": "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。",
        "authority_level": "法律",
        "validity_status": "effective",
        "confidence": 0.9,
    },
    {
        "source_id": "law_002",
        "source_type": "law",
        "title": "中华人民共和国民法典 第五百八十五条",
        "site_name": "全国人大",
        "url": "https://example.test/civil-code/article-585",
        "summary": "当事人可以约定一方违约时应当根据违约情况向对方支付一定数额的违约金，也可以约定因违约产生的损失赔偿额的计算方法。",
        "quoted_text": "当事人可以约定一方违约时应当根据违约情况向对方支付一定数额的违约金，也可以约定因违约产生的损失赔偿额的计算方法。",
        "authority_level": "法律",
        "validity_status": "effective",
        "confidence": 0.9,
    },
    {
        "source_id": "law_003",
        "source_type": "law",
        "title": "中华人民共和国民法典 第五百六十三条",
        "site_name": "全国人大",
        "url": "https://example.test/civil-code/article-563",
        "summary": "当事人一方迟延履行主要债务，经催告后在合理期限内仍未履行的，当事人可以解除合同。",
        "quoted_text": "当事人一方迟延履行主要债务，经催告后在合理期限内仍未履行的，当事人可以解除合同。",
        "authority_level": "法律",
        "validity_status": "effective",
        "confidence": 0.88,
    },
    {
        "source_id": "contract_001",
        "source_type": "contract",
        "title": "采购合同样本 第3条、第8条、第9条",
        "site_name": "用户提供合同材料",
        "url": "local://fixture/procurement-contract",
        "summary": (
            "第3条：卖方应于2026年7月31日前交付设备。"
            "第8条：卖方逾期交付超过15日，买方只能要求退还已付款项，"
            "卖方不承担违约金、损失赔偿或其他责任，合同没有解除权安排。"
            "第9条：买方应在到货后5个工作日内完成验收。"
        ),
        "quoted_text": (
            "第3条：卖方应于2026年7月31日前交付设备。"
            "第8条：卖方逾期交付超过15日，买方只能要求退还已付款项，"
            "卖方不承担违约金、损失赔偿或其他责任，合同没有解除权安排。"
            "第9条：买方应在到货后5个工作日内完成验收。"
        ),
        "authority_level": "合同",
        "validity_status": "unknown",
        "confidence": 0.85,
    },
]


async def _disabled_llm(*args, **kwargs):
    raise RuntimeError("External LLM disabled for deterministic full-flow test.")


async def _fixture_search(query: str, count: int = 10):
    return LEGAL_FIXTURE_RESULTS[:count]


async def run_full_flow() -> dict:
    graph = DeepResearchGraph(max_iterations=1)
    for agent in [
        graph.architect,
        graph.scout,
        graph.evidence_extractor,
        graph.data_analyst,
        graph.wizard,
        graph.writer,
        graph.critic,
    ]:
        agent.call_llm = _disabled_llm
    graph.scout._execute_search = _fixture_search

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
    assert final_event.get("charts_count", 0) >= 3
    assert final_event.get("quality_score", 0) >= 8.0

    required_report_terms = [
        "不构成正式法律意见",
        "逾期交付",
        "违约金",
        "损失赔偿",
        "解除权",
        "整改建议",
        "证据链",
        "人工复核",
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
