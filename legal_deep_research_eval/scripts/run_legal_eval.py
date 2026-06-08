#!/usr/bin/env python3
"""CLI for the independent legal DeepResearch evaluator."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from legal_eval.config import DEFAULT_BENCHMARK_JSONL, DEFAULT_EVAL_RESULTS_DIR, DEFAULT_MANIFEST_DIR, INDUSTRY_PROJECT_ROOT
from legal_eval.loaders.batch_loader import BatchOutputLoader
from legal_eval.loaders.benchmark_loader import BenchmarkTaskLoader
from legal_eval.loaders.manifest import ManifestTool
from legal_eval.schemas import LegalEvalRequest
from legal_eval.service import LegalEvalService
from legal_eval.tools.result_store import EvalResultStoreTool
from legal_eval.utils import read_text, write_json


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_service(args: argparse.Namespace) -> LegalEvalService:
    base_dir = Path(getattr(args, "result_base_dir", DEFAULT_EVAL_RESULTS_DIR))
    return LegalEvalService(result_store=EvalResultStoreTool(base_dir=base_dir))


def cmd_evaluate(args: argparse.Namespace) -> None:
    service = build_service(args)
    request = LegalEvalRequest(
        report_path=args.report_path,
        batch_result_path=args.batch_result_path,
        events_path=args.events_path,
        trace_dir=args.trace_dir,
        final_state_path=args.final_state_path,
        task_id=args.task_id,
        judge_mode=args.judge_mode,
        save_result=not args.no_save,
        require_llm=args.require_llm,
    )
    result = service.evaluate(request)
    print_json(result.model_dump())


def cmd_rule_only(args: argparse.Namespace) -> None:
    report = args.report_text or ""
    if args.report_path:
        report = read_text(args.report_path)
    service = build_service(args)
    result = service.evaluate(
        LegalEvalRequest(
            candidate_report_markdown=report,
            task_id=args.task_id,
            task_meta={"must_include_disclaimer": True, **(json.loads(args.task_meta_json) if args.task_meta_json else {})},
            judge_mode="rule_only",
            save_result=not args.no_save,
        )
    )
    print_json(result.model_dump())


def cmd_batch(args: argparse.Namespace) -> None:
    loader = BatchOutputLoader()
    service = build_service(args)
    result_paths = loader.iter_result_paths(args.batch_dir)
    if args.limit:
        result_paths = result_paths[: args.limit]
    results: List[Dict[str, Any]] = []
    for result_path in result_paths:
        result = service.evaluate(
            LegalEvalRequest(
                batch_result_path=result_path,
                judge_mode=args.judge_mode,
                save_result=not args.no_save,
                require_llm=args.require_llm,
            )
        )
        results.append(result.model_dump())
    summary = {
        "batch_id": f"legal_eval_batch_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
        "batch_dir": str(args.batch_dir),
        "total_count": len(results),
        "pass_gate_counts": _count_by(results, ["decision", "pass_gate"]),
        "fatal_error_count": sum(1 for item in results if item.get("fatal_errors")),
        "average_overall_score": round(sum(item.get("overall_score", 0) for item in results) / len(results), 2) if results else 0,
        "results": [
            {
                "eval_id": item.get("eval_id"),
                "task_id": item.get("task_id"),
                "overall_score": item.get("overall_score"),
                "decision": item.get("decision"),
                "fatal_errors": item.get("fatal_errors"),
                "result_path": item.get("result_path"),
            }
            for item in results
        ],
    }
    output_file = args.output_file or (DEFAULT_EVAL_RESULTS_DIR / "batch_summary.json")
    write_json(output_file, summary)
    print_json(summary)


def cmd_export_tasks(args: argparse.Namespace) -> None:
    loader = BenchmarkTaskLoader(markdown_path=args.markdown_path, jsonl_path=args.output)
    path = loader.export_jsonl(args.output)
    print_json({"output": str(path)})


def cmd_manifest_create(args: argparse.Namespace) -> None:
    output = args.output or (DEFAULT_MANIFEST_DIR / f"{args.name}.json")
    path = ManifestTool().create(args.target_root, output)
    print_json({"manifest": str(path)})


def cmd_manifest_compare(args: argparse.Namespace) -> None:
    result = ManifestTool().compare(args.before, args.after)
    print_json(result)
    if not result["clean"]:
        raise SystemExit(1)


def _count_by(rows: List[Dict[str, Any]], path: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        value: Any = row
        for key in path:
            value = value.get(key, {}) if isinstance(value, dict) else {}
        label = str(value or "unknown")
        counts[label] = counts.get(label, 0) + 1
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_eval_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--task-id")
        p.add_argument("--judge-mode", choices=["mock", "real", "rule_only"], default="mock")
        p.add_argument("--no-save", action="store_true")
        p.add_argument("--require-llm", action="store_true")
        p.add_argument("--result-base-dir", type=Path, default=DEFAULT_EVAL_RESULTS_DIR)

    evaluate = sub.add_parser("evaluate", help="Evaluate one report or batch result")
    evaluate.add_argument("--report-path", type=Path)
    evaluate.add_argument("--batch-result-path", type=Path)
    evaluate.add_argument("--events-path", type=Path)
    evaluate.add_argument("--trace-dir", type=Path)
    evaluate.add_argument("--final-state-path", type=Path)
    add_eval_common(evaluate)
    evaluate.set_defaults(func=cmd_evaluate)

    rule = sub.add_parser("rule-only", help="Run deterministic rule-only evaluation")
    rule.add_argument("--report-path", type=Path)
    rule.add_argument("--report-text")
    rule.add_argument("--task-meta-json")
    add_eval_common(rule)
    rule.set_defaults(func=cmd_rule_only)

    batch = sub.add_parser("batch", help="Evaluate an existing batch_outputs directory")
    batch.add_argument("--batch-dir", type=Path, required=True)
    batch.add_argument("--limit", type=int)
    batch.add_argument("--output-file", type=Path)
    add_eval_common(batch)
    batch.set_defaults(func=cmd_batch)

    export = sub.add_parser("export-tasks", help="Export benchmark JSONL from the markdown question bank")
    export.add_argument("--markdown-path", type=Path, default=Path(PACKAGE_ROOT).parent / "2026年6月6日-30个法律风控问题.md")
    export.add_argument("--output", type=Path, default=DEFAULT_BENCHMARK_JSONL)
    export.set_defaults(func=cmd_export_tasks)

    manifest_create = sub.add_parser("manifest-create", help="Create a read-only SHA256 manifest")
    manifest_create.add_argument("--target-root", type=Path, default=INDUSTRY_PROJECT_ROOT)
    manifest_create.add_argument("--output", type=Path)
    manifest_create.add_argument("--name", default="industry_information_assistant_before")
    manifest_create.set_defaults(func=cmd_manifest_create)

    manifest_compare = sub.add_parser("manifest-compare", help="Compare two SHA256 manifests")
    manifest_compare.add_argument("--before", type=Path, required=True)
    manifest_compare.add_argument("--after", type=Path, required=True)
    manifest_compare.set_defaults(func=cmd_manifest_compare)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
