"""Randomly run QA-pair questions through the legal workflow and save quality results."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
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
DEFAULT_QA_PATH = LEARN_ROOT / "30个QA对.md"
DEFAULT_OUTPUT_ROOT = BACKEND_ROOT / "batch_outputs" / "qa30_random_runs"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.service.deep_research_v2.graph import DeepResearchGraph  # noqa: E402


INTERNAL_TERMS = [
    "source_pack", "evidence_matrix", "scope_brief", "analysis_draft", "qa_verdict",
    "Source Pack", "Evidence Matrix", "Scope Brief", "Analysis Draft", "QA Verdict",
    "artifact", "Artifact", "工件", "A1", "A2", "A3", "A4", "A5",
]
FINAL_AI_NOTE = "AI生成，仅供参考"
OVER_DISCLAIMER_TERMS = ["免责声明", "不构成正式法律意见", "诉讼代理意见", "监管机关最终认定结论"]
CASE_TERMS = ["类案", "案例", "判决", "裁判", "处罚"]
LAW_TERMS = ["法律依据", "民法典", "消费者权益保护法", "劳动合同法", "个人信息保护法", "刑法", "行政法规", "司法解释"]
ACTION_TERMS = ["行动建议", "证据", "投诉", "协商", "调解", "仲裁", "诉讼", "催告", "整改", "保全"]


def _normalize(text: str) -> str:
    return " ".join((text or "").split())


def parse_qa_pairs(path: Path) -> List[Dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"(?m)^##\s+(\d+)\.\s*([^\n]+)\n\s*### 问题\s*\n")
    matches = list(pattern.finditer(text))
    if len(matches) != 30:
        raise ValueError(f"Expected 30 QA pairs, found {len(matches)} in {path}")

    pairs: List[Dict[str, str]] = []
    for index, match in enumerate(matches):
        block_start = match.end()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[block_start:block_end].strip()
        answer_marker = re.search(r"(?m)^### 回答\s*$", block)
        if not answer_marker:
            raise ValueError(f"QA pair {match.group(1)} is missing answer marker")
        question = block[:answer_marker.start()].strip()
        answer = block[answer_marker.end():].strip()
        pairs.append({
            "id": f"Q{int(match.group(1)):02d}",
            "number": match.group(1),
            "title": match.group(2).strip(),
            "question": question,
            "answer": answer,
        })
    return pairs


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def slug(text: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", text)
    return cleaned.strip("_")[:40] or "qa"


def extract_expected_terms(answer: str, limit: int = 18) -> List[str]:
    candidates: List[str] = []
    candidates.extend(re.findall(r"《([^》]{2,24})》", answer))
    candidates.extend(re.findall(r"\*\*([^*\n]{2,18})\*\*", answer))
    for line in answer.splitlines():
        stripped = line.strip()
        if stripped.startswith("##"):
            candidates.append(re.sub(r"^#+\s*", "", stripped)[:18])
    legal_words = re.findall(r"[\u4e00-\u9fff]{2,8}(?:权|责任|义务|风险|赔偿|退款|退费|解除|违约|侵权|投诉|证据|合同|押金|工资|社保|继承|离婚|平台|消费者|劳动|隐私|个人信息|物业费|格式条款)", answer)
    candidates.extend(legal_words)
    terms = []
    for item in candidates:
        text = _normalize(item)
        if not text or len(text) > 18:
            continue
        terms.append(text)
    return list(dict.fromkeys(terms))[:limit]


def count_action_items(report: str) -> int:
    count = 0
    for line in report.splitlines():
        if re.match(r"^\s*(?:[-*]|\d+[\.\、])\s+", line):
            if any(term in line for term in ACTION_TERMS) or len(_normalize(line)) >= 18:
                count += 1
    return count


def review_report(report: str, expected_answer: str, complete: Dict[str, Any] | None) -> Dict[str, Any]:
    references = (complete or {}).get("references", [])
    artifacts = (complete or {}).get("artifacts", {})
    final_line_ok = bool(report.strip()) and report.strip().splitlines()[-1].strip() == FINAL_AI_NOTE and report.count(FINAL_AI_NOTE) == 1
    expected_terms = extract_expected_terms(expected_answer)
    covered_terms = [term for term in expected_terms if term and term in report]
    source_pack = ((artifacts.get("source_pack") or {}).get("writes") or {})
    source_kinds = [
        str(source.get("source_kind", ""))
        for source in source_pack.get("issue_sources", [])
        if isinstance(source, dict)
    ]
    has_case_source = any(kind in {"case", "penalty"} for kind in source_kinds) or any(
        any(term in f"{ref.get('title', '')} {ref.get('content', '')}" for term in CASE_TERMS)
        for ref in references
        if isinstance(ref, dict)
    )
    qa_verdict = (complete or {}).get("qa_verdict", {})
    verdict_value = qa_verdict.get("verdict") if isinstance(qa_verdict, dict) else ""
    quality_score = (complete or {}).get("quality_score", 0.0)
    checks = {
        "complete_event": complete is not None,
        "report_long_enough": len(report) >= 2200,
        "no_internal_terms": not any(term in report for term in INTERNAL_TERMS),
        "final_ai_note_only": final_line_ok and not any(term in report for term in OVER_DISCLAIMER_TERMS),
        "has_law_basis": any(term in report for term in LAW_TERMS),
        "has_case_reference": has_case_source or any(term in report for term in CASE_TERMS),
        "has_action_plan": any(term in report for term in ACTION_TERMS) and count_action_items(report) >= 5,
        "not_too_pending": report.count("待核验") <= 12 and "暂缺可承载结论的精确法源" not in report,
        "expected_terms_coverage": len(covered_terms) >= max(2, min(5, len(expected_terms) // 4)),
        "qa_verdict_passed": verdict_value in {"approved", "approved_with_human_review"} or quality_score >= 80,
    }
    issues = []
    for key, passed in checks.items():
        if not passed:
            issues.append(key)
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "issues": issues,
        "report_length": len(report),
        "expected_answer_length": len(expected_answer),
        "expected_terms": expected_terms,
        "covered_expected_terms": covered_terms,
        "coverage_ratio": round(len(covered_terms) / max(1, len(expected_terms)), 3),
        "references_count": len(references),
        "quality_score": quality_score,
        "qa_verdict": qa_verdict,
    }


def build_query(pair: Dict[str, str]) -> str:
    return (
        f"{pair['question']}\n\n"
        "请直接给出面向普通用户的翔实法律风险分析，重点覆盖法律依据、相似案例或裁判参考、责任或权利边界、证据准备和具体行动建议。"
    )


async def run_one(pair: Dict[str, str], output_dir: Path, args: argparse.Namespace, semaphore: asyncio.Semaphore) -> Dict[str, Any]:
    async with semaphore:
        run_dir = output_dir / f"{pair['id']}_{slug(pair['title'])}"
        run_dir.mkdir(parents=True, exist_ok=True)
        session_id = f"qa30-{pair['id'].lower()}-{uuid.uuid4().hex[:8]}"
        query = build_query(pair)
        events: List[Dict[str, Any]] = []
        error = None

        (run_dir / "question.md").write_text(pair["question"], encoding="utf-8")
        (run_dir / "qa_expected_answer.md").write_text(pair["answer"], encoding="utf-8")
        write_json(run_dir / "metadata.json", {"id": pair["id"], "title": pair["title"], "session_id": session_id})

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
        except Exception as exc:
            error = str(exc)

        write_jsonl(run_dir / "events.jsonl", events)
        complete = next((event for event in reversed(events) if event.get("type") == "research_complete"), None)
        error_event = next((event for event in reversed(events) if event.get("type") == "error"), None)
        if error_event and not error:
            error = error_event.get("content") or "unknown error"

        report = complete.get("final_report", "") if complete else ""
        (run_dir / "final_report.md").write_text(report, encoding="utf-8")
        write_json(run_dir / "complete_event.json", complete or {})
        write_json(run_dir / "artifacts.json", (complete or {}).get("artifacts", {}))
        write_json(run_dir / "references.json", (complete or {}).get("references", []))
        quality = review_report(report, pair["answer"], complete)
        write_json(run_dir / "quality_review.json", quality)

        summary = {
            "id": pair["id"],
            "title": pair["title"],
            "session_id": session_id,
            "run_dir": str(run_dir),
            "error": error,
            "events_count": len(events),
            "report_length": len(report),
            "quality_passed": quality["passed"],
            "quality_issues": quality["issues"],
            "quality_score": quality.get("quality_score", 0.0),
            "qa_verdict": quality.get("qa_verdict", {}).get("verdict") if isinstance(quality.get("qa_verdict"), dict) else None,
        }
        write_json(run_dir / "summary.json", summary)
        return summary


async def run_sample(args: argparse.Namespace) -> Dict[str, Any]:
    pairs = parse_qa_pairs(args.qa_path)
    rng = random.Random(args.seed)
    if args.ids:
        wanted = {item.strip().upper() for item in args.ids.split(",") if item.strip()}
        selected = [pair for pair in pairs if pair["id"].upper() in wanted or pair["number"] in wanted]
    else:
        selected = rng.sample(pairs, k=min(args.sample_size, len(pairs)))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "selected_questions.json", selected)

    semaphore = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*(run_one(pair, output_dir, args, semaphore) for pair in selected))
    passed = [item for item in results if item["quality_passed"] and not item["error"]]
    failed = [item for item in results if item not in passed]
    summary = {
        "output_dir": str(output_dir),
        "qa_path": str(args.qa_path),
        "seed": args.seed,
        "sample_size": len(selected),
        "concurrency": args.concurrency,
        "passed_count": len(passed),
        "failed_count": len(failed),
        "selected_ids": [pair["id"] for pair in selected],
        "results": results,
        "finished_at": datetime.now().isoformat(),
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-path", type=Path, default=DEFAULT_QA_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--sample-size", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--ids", default="", help="Comma-separated QA ids, e.g. Q01,Q12,30. Overrides random sampling.")
    parser.add_argument("--search-local", action="store_true")
    parser.add_argument("--no-search-web", action="store_true")
    parser.add_argument("--allow-recursive-search", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = asyncio.run(run_sample(args))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
