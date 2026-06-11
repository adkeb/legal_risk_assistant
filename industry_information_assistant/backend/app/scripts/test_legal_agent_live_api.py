"""Live API full-flow test for the legal-risk DeepResearch agent.

Required environment variables:
- LLM_API_KEY or DASHSCOPE_API_KEY: OpenAI-compatible LLM API key
- LLM_BASE_URL: OpenAI-compatible base URL
- LLM_MODEL: model name used by every DeepResearch agent
- TAVILY_API_KEY: Tavily web-search API key
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


from app.config.llm_config import reload_config  # noqa: E402
from app.service.deep_research_v2.graph import DeepResearchGraph  # noqa: E402


QUERY = (
    "请从中国大陆法律风控角度分析以下采购合同安排，并形成完整 DeepResearch 报告："
    "卖方应于2026年7月31日前交付生产设备；合同约定卖方逾期交付超过15日，"
    "买方仅可要求退还已付货款；合同未约定违约金、逾期损失赔偿、替代采购差价、"
    "合同解除权、律师费承担和证据保全机制；买方需在到货后5个工作日完成验收。"
    "请检索法律依据、案例或权威材料，识别风险等级、证据链、义务期限和整改建议。"
)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> None:
    if not (os.getenv("LLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY")):
        raise RuntimeError("Missing required environment variable: LLM_API_KEY or DASHSCOPE_API_KEY")
    require_env("LLM_BASE_URL")
    require_env("LLM_MODEL")
    require_env("TAVILY_API_KEY")

    config = reload_config()
    session_id = f"legal-live-api-{uuid.uuid4().hex[:8]}"
    output_dir = Path("/tmp/legal_agent_live_api")
    output_dir.mkdir(parents=True, exist_ok=True)

    graph = DeepResearchGraph(max_iterations=1)
    events: list[dict] = []

    async for event in graph.run(
        QUERY,
        session_id,
        search_web=True,
        search_local=False,
        allow_recursive_search=False,
    ):
        events.append(event)

    complete = next((event for event in reversed(events) if event.get("type") == "research_complete"), None)
    errors = [event for event in events if event.get("type") == "error"]
    if errors:
        raise AssertionError(f"Live legal research emitted error event: {errors[-1]}")
    if not complete:
        raise AssertionError("Live legal research did not emit research_complete")

    report = complete.get("final_report", "")
    report_path = output_dir / "legal_risk_live_api_report.md"
    report_path.write_text(report, encoding="utf-8")

    phases = [event.get("phase") for event in events if event.get("type") == "phase"]
    event_types = [event.get("type") for event in events]
    references = complete.get("references", [])

    checks = {
        "has_final_note": report.strip().endswith("AI生成，仅供参考"),
        "has_overdue_delivery": "逾期交付" in report,
        "has_liquidated_damages": "违约金" in report,
        "has_loss_compensation": "损失赔偿" in report or "赔偿" in report,
        "has_termination_right": "解除权" in report or "解除合同" in report,
        "has_remediation": "整改" in report or "建议" in report,
        "has_evidence_chain": "证据链" in report or "引用" in report,
        "has_human_review": "人工复核" in report or "律师" in report,
    }

    summary = {
        "session_id": session_id,
        "model": config.default_model,
        "base_url": config.base_url,
        "events_count": len(events),
        "phases": phases,
        "event_types": event_types,
        "quality_score": complete.get("quality_score", 0.0),
        "facts_count": complete.get("facts_count", 0),
        "charts_count": complete.get("charts_count", 0),
        "references_count": len(references),
        "report_length": len(report),
        "report_path": str(report_path),
        "checks": checks,
        "reference_titles": [ref.get("title", "") for ref in references[:10]],
    }

    summary_path = output_dir / "summary.json"
    write_json(summary_path, summary)

    if len(report) < 1000:
        raise AssertionError(f"Report is too short: {len(report)} chars")
    if not checks["has_final_note"]:
        raise AssertionError("Report is missing mandatory final AI note")
    if complete.get("facts_count", 0) <= 0 and len(references) <= 0:
        raise AssertionError("Report completed without facts or references")

    print("Live legal agent full-flow test passed.")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
