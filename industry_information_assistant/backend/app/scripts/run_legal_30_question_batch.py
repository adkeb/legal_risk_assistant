"""Run the 30 legal-risk benchmark questions with DeepResearch tracing enabled."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
LEARN_ROOT = PROJECT_ROOT.parent
DEFAULT_QUESTIONS_PATH = LEARN_ROOT / "2026年6月6日-30个法律风控问题.md"
DEFAULT_OUTPUT_ROOT = BACKEND_ROOT / "batch_outputs" / "legal_30_questions"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.service.deep_research_v2.graph import DeepResearchGraph  # noqa: E402


REQUIRED_AGENTS = {
    "ChiefArchitect",
    "DeepScout",
    "EvidenceExtractor",
    "DataAnalyst",
    "CodeWizard",
    "LeadWriter",
    "CriticMaster",
}


def extract_questions(path: Path) -> List[Dict[str, Any]]:
    content = path.read_text(encoding="utf-8")
    match = re.search(r"```json\s*(\[[\s\S]*?\])\s*```", content)
    if not match:
        raise ValueError(f"No JSON array code block found in {path}")
    questions = json.loads(match.group(1))
    if not isinstance(questions, list):
        raise ValueError("Question bank JSON is not a list")
    if len(questions) != 30:
        raise ValueError(f"Expected 30 questions, got {len(questions)}")
    for item in questions:
        if not item.get("id") or not item.get("user_question"):
            raise ValueError(f"Invalid question item: {item}")
    return questions


def build_research_query(item: Dict[str, Any]) -> str:
    evidence_requirements = "\n".join(
        f"- {entry}" for entry in item.get("evidence_chain_requirements", [])
    )
    expected_points = "\n".join(
        f"- {entry}" for entry in item.get("expected_answer_points", [])
    )
    return f"""请作为法律风控 DeepResearch Agent 完成以下测评题，输出完整法律风控报告。

题目编号：{item.get("id")}
难度：{item.get("difficulty")}
任务类型：{item.get("task_type")}
主要法域：{item.get("primary_jurisdiction")}

场景：
{item.get("scenario_summary")}

用户原始问题：
{item.get("user_question")}

期望覆盖要点：
{expected_points}

证据链要求：
{evidence_requirements}

请严格包含：事实与假设、适用法域、法律依据、风险等级、证据链、整改建议、人工复核事项，以及“不构成正式法律意见”免责声明。"""


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")


def validate_trace(trace_info: Dict[str, Any]) -> Dict[str, Any]:
    trace_dir = Path(trace_info.get("trace_dir", ""))
    result = {
        "trace_dir": str(trace_dir),
        "exists": trace_dir.exists(),
        "has_agent_runs": False,
        "has_events": False,
        "has_final_state": False,
        "agent_input_output_ok": False,
        "agents_seen": [],
        "missing_agents": sorted(REQUIRED_AGENTS),
        "missing_io_dirs": [],
    }
    if not trace_dir.exists():
        return result

    agent_runs_path = trace_dir / "agent_runs.jsonl"
    events_path = trace_dir / "events.jsonl"
    result["has_agent_runs"] = agent_runs_path.exists() and agent_runs_path.stat().st_size > 0
    result["has_events"] = events_path.exists() and events_path.stat().st_size > 0
    result["has_final_state"] = (trace_dir / "final_state.json").exists()

    agents_seen = set()
    missing_io_dirs = []
    for run_dir in sorted((trace_dir / "agents").glob("*")):
        if not run_dir.is_dir():
            continue
        parts = run_dir.name.split("_")
        agent_name = parts[1] if len(parts) >= 2 else run_dir.name
        agents_seen.add(agent_name)
        if not (run_dir / "input_state.json").exists() or not (run_dir / "output_state.json").exists():
            missing_io_dirs.append(str(run_dir))

    result["agents_seen"] = sorted(agents_seen)
    result["missing_agents"] = sorted(REQUIRED_AGENTS - agents_seen)
    result["missing_io_dirs"] = missing_io_dirs
    result["agent_input_output_ok"] = (
        not result["missing_agents"]
        and not missing_io_dirs
        and result["has_agent_runs"]
        and result["has_events"]
        and result["has_final_state"]
    )
    return result


async def run_one(
    item: Dict[str, Any],
    output_dir: Path,
    args: argparse.Namespace,
    semaphore: asyncio.Semaphore,
) -> Dict[str, Any]:
    async with semaphore:
        question_id = item["id"]
        session_id = f"legal-batch-{question_id.lower()}-{uuid.uuid4().hex[:8]}"
        query = build_research_query(item)
        report_path = output_dir / "reports" / f"{question_id}.md"
        events_path = output_dir / "events" / f"{question_id}.jsonl"
        result_path = output_dir / "results" / f"{question_id}.json"
        started_at = datetime.now().isoformat()
        events: List[Dict[str, Any]] = []
        error = None

        graph = DeepResearchGraph(max_iterations=args.max_iterations)
        try:
            async for event in graph.run(
                query,
                session_id,
                search_web=not args.no_search_web,
                search_local=args.search_local,
                allow_recursive_search=args.allow_recursive_search,
            ):
                events.append(event)
                append_jsonl(events_path, event)
        except Exception as exc:
            error = str(exc)

        complete = next((event for event in reversed(events) if event.get("type") == "research_complete"), None)
        error_event = next((event for event in reversed(events) if event.get("type") == "error"), None)
        if error_event and not error:
            error = error_event.get("content", "unknown error")

        report = complete.get("final_report", "") if complete else ""
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")

        trace_info = (complete or {}).get("trace_info") or {}
        trace_validation = validate_trace(trace_info)
        checks = {
            "has_complete_event": complete is not None,
            "has_report": len(report) >= args.min_report_chars,
            "has_disclaimer": "不构成正式法律意见" in report,
            "trace_ok": trace_validation.get("agent_input_output_ok", False),
        }
        status = "passed" if all(checks.values()) and not error else "failed"
        summary = {
            "id": question_id,
            "difficulty": item.get("difficulty"),
            "task_type": item.get("task_type"),
            "primary_jurisdiction": item.get("primary_jurisdiction"),
            "session_id": session_id,
            "status": status,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(),
            "error": error,
            "events_count": len(events),
            "phases": [event.get("phase") for event in events if event.get("type") == "phase"],
            "quality_score": (complete or {}).get("quality_score", 0.0),
            "facts_count": (complete or {}).get("facts_count", 0),
            "charts_count": (complete or {}).get("charts_count", 0),
            "references_count": len((complete or {}).get("references", [])),
            "report_length": len(report),
            "report_path": str(report_path),
            "events_path": str(events_path),
            "trace_info": trace_info,
            "trace_validation": trace_validation,
            "checks": checks,
        }
        write_json(result_path, summary)
        append_jsonl(output_dir / "status.jsonl", summary)
        return summary


async def run_batch(args: argparse.Namespace) -> Dict[str, Any]:
    questions = extract_questions(args.questions_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "questions.json", questions)

    if args.dry_run:
        summary = {
            "output_dir": str(output_dir),
            "total_count": len(questions),
            "questions_count": len(questions),
            "ids": [item["id"] for item in questions],
            "dry_run": True,
        }
        write_json(output_dir / "summary.json", summary)
        return summary

    semaphore = asyncio.Semaphore(args.concurrency)
    tasks = [
        asyncio.create_task(run_one(item, output_dir, args, semaphore))
        for item in questions
    ]
    results = await asyncio.gather(*tasks)
    passed = [item for item in results if item["status"] == "passed"]
    failed = [item for item in results if item["status"] != "passed"]
    summary = {
        "output_dir": str(output_dir),
        "total_count": len(questions),
        "questions_count": len(questions),
        "concurrency": args.concurrency,
        "passed_count": len(passed),
        "failed_count": len(failed),
        "passed_ids": [item["id"] for item in passed],
        "failed_ids": [item["id"] for item in failed],
        "results": results,
    }
    write_json(output_dir / "summary.json", summary)
    if failed:
        raise SystemExit(f"{len(failed)} question(s) failed; see {output_dir / 'summary.json'}")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions-path", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--min-report-chars", type=int, default=1000)
    parser.add_argument("--search-local", action="store_true")
    parser.add_argument("--no-search-web", action="store_true")
    parser.add_argument("--allow-recursive-search", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = asyncio.run(run_batch(args))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
