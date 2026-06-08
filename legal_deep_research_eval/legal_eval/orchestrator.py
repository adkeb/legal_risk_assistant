"""Fixed-flow legal evaluation orchestrator."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict

from .aggregator import aggregate_final_result
from .eval_state import LegalEvalState
from .judges.llm_judge import LLMJudgeAgent
from .loaders.batch_loader import BatchOutputLoader
from .loaders.benchmark_loader import BenchmarkTaskLoader
from .loaders.checkpoint_loader import CheckpointLoader
from .loaders.trace_loader import TraceLoader
from .schemas import LegalEvalInput, LegalEvalRequest, LegalEvalResult
from .tools.actionability_checker import ActionabilityCheckerTool
from .tools.citation_verifier import CitationVerifierTool
from .tools.claim_extractor import ClaimExtractorTool
from .tools.evidence_verifier import EvidenceChainVerifierTool
from .tools.gold_comparator import GoldComparatorTool
from .tools.jurisdiction_checker import JurisdictionVersionCheckerTool
from .tools.post_checker import PostCheckTool
from .tools.process_trace_analyzer import ProcessTraceAnalyzerTool
from .tools.report_parser import ReportParserTool
from .tools.result_store import EvalResultStoreTool
from .tools.retrieval_metrics import RetrievalMetricsTool
from .tools.rule_engine import LegalRuleEngineTool
from .utils import extract_sources_from_state, read_text


class LegalEvalOrchestrator:
    def __init__(self, result_store: EvalResultStoreTool | None = None) -> None:
        self.batch_loader = BatchOutputLoader()
        self.task_loader = BenchmarkTaskLoader()
        self.trace_loader = TraceLoader()
        self.checkpoint_loader = CheckpointLoader()
        self.report_parser = ReportParserTool()
        self.claim_extractor = ClaimExtractorTool()
        self.rule_engine = LegalRuleEngineTool()
        self.citation_verifier = CitationVerifierTool()
        self.evidence_verifier = EvidenceChainVerifierTool()
        self.jurisdiction_checker = JurisdictionVersionCheckerTool()
        self.process_analyzer = ProcessTraceAnalyzerTool()
        self.retrieval_metrics = RetrievalMetricsTool()
        self.gold_comparator = GoldComparatorTool()
        self.actionability_checker = ActionabilityCheckerTool()
        self.llm_judge = LLMJudgeAgent()
        self.post_checker = PostCheckTool()
        self.result_store = result_store or EvalResultStoreTool()

    def evaluate(self, request: LegalEvalRequest) -> LegalEvalResult:
        eval_input = self._build_eval_input(request)
        state = LegalEvalState(eval_input=eval_input)
        state.parsed_report = self.report_parser.parse(eval_input.candidate_report_markdown)
        state.extracted_claims = self.claim_extractor.extract(eval_input.candidate_report_markdown)
        state.rule_engine_result = self.rule_engine.run(
            task_meta=eval_input.task_meta,
            report_markdown=eval_input.candidate_report_markdown,
            source_index=eval_input.source_index,
            risk_items=eval_input.risk_items,
            evidence_chain=eval_input.evidence_chain,
            claims=state.extracted_claims,
            gold_reference=eval_input.gold_reference,
        )
        state.citation_result = self.citation_verifier.verify(
            eval_input.candidate_report_markdown,
            eval_input.source_index,
            state.extracted_claims,
        )
        state.evidence_result = self.evidence_verifier.verify(
            eval_input.risk_items,
            eval_input.evidence_chain,
            eval_input.source_index,
        )
        state.jurisdiction_result = self.jurisdiction_checker.verify(
            eval_input.task_meta,
            eval_input.source_index,
            eval_input.candidate_report_markdown,
        )
        state.process_result = self.process_analyzer.analyze(eval_input.state_json, eval_input.process_events)
        state.retrieval_result = self.retrieval_metrics.compute(eval_input.source_index, state.process_result)
        state.gold_comparison_result = self.gold_comparator.compare(
            eval_input.candidate_report_markdown,
            eval_input.gold_reference,
        )
        state.actionability_result = self.actionability_checker.check(
            state.parsed_report,
            eval_input.candidate_report_markdown,
            eval_input.risk_items,
        )
        state.llm_judge_result = self.llm_judge.score(
            eval_input=eval_input,
            parsed_report=state.parsed_report,
            claims=state.extracted_claims,
            rule_engine_result=state.rule_engine_result,
            citation_result=state.citation_result,
            evidence_result=state.evidence_result,
            jurisdiction_result=state.jurisdiction_result,
            retrieval_result=state.retrieval_result,
            process_result=state.process_result,
            gold_comparison_result=state.gold_comparison_result,
            actionability_result=state.actionability_result,
        )
        state.post_check_result = self.post_checker.check(
            rule_engine_result=state.rule_engine_result,
            llm_judge_result=state.llm_judge_result,
            evidence_result=state.evidence_result,
            citation_result=state.citation_result,
        )
        state.final_result = aggregate_final_result(state)
        if request.save_result:
            path = self.result_store.save(state.final_result)
            state.final_result["result_path"] = str(path)
        return LegalEvalResult(**state.final_result)

    def _build_eval_input(self, request: LegalEvalRequest) -> LegalEvalInput:
        data: Dict[str, Any] = request.model_dump()
        if request.batch_result_path:
            batch = self.batch_loader.load_result(request.batch_result_path)
            data["run_meta"] = {**data.get("run_meta", {}), "batch_result": batch.get("batch_result")}
            data["task_id"] = data.get("task_id") or batch.get("task_id")
            data["session_id"] = data.get("session_id") or batch.get("session_id")
            data["task_meta"] = {**batch.get("task_meta", {}), **(data.get("task_meta") or {})}
            data["report_path"] = data.get("report_path") or batch.get("report_path")
            data["events_path"] = data.get("events_path") or batch.get("events_path")
            data["trace_dir"] = data.get("trace_dir") or batch.get("trace_dir")

        if data.get("report_path") and not data.get("candidate_report_markdown"):
            data["candidate_report_markdown"] = read_text(Path(data["report_path"]))

        state_json = dict(data.get("state_json") or {})
        loaded_state = self.trace_loader.load_final_state(data.get("final_state_path"), data.get("trace_dir"))
        if loaded_state:
            state_json = {**loaded_state, **state_json}
        if data.get("session_id") and not state_json and not data.get("candidate_report_markdown"):
            checkpoint = self.checkpoint_loader.load(str(data["session_id"]))
            if checkpoint.get("ok"):
                cp = checkpoint["checkpoint"]
                state_json = cp.get("state_json") or {}
                data["candidate_report_markdown"] = cp.get("final_report") or state_json.get("final_report") or ""
                data["process_events"] = data.get("process_events") or (cp.get("ui_state_json") or {}).get("events", [])
                data["run_meta"] = {**data.get("run_meta", {}), "checkpoint": {"status": cp.get("status"), "phase": cp.get("phase")}}

        process_events = list(data.get("process_events") or [])
        loaded_events = self.trace_loader.load_events(data.get("events_path"), data.get("trace_dir"))
        if loaded_events:
            process_events = loaded_events + process_events

        task_id = data.get("task_id") or self._infer_task_id(data)
        task = self.task_loader.find_task(task_id)
        task_meta = dict(data.get("task_meta") or {})
        gold_reference = data.get("gold_reference")
        if task:
            task_meta = {**task.get("task_meta", {}), **task_meta}
            gold_reference = gold_reference or task.get("gold_reference")
            task_id = task.get("task_id") or task_id

        source_index = list(data.get("source_index") or [])
        if not source_index and state_json:
            source_index = extract_sources_from_state(state_json)
        risk_items = list(data.get("risk_items") or [])
        if not risk_items and state_json:
            risk_items = state_json.get("risk_items") or state_json.get("risk_scores") or []
        evidence_chain = list(data.get("evidence_chain") or [])
        if not evidence_chain and state_json:
            evidence_chain = state_json.get("evidence_chain") or []

        report = data.get("candidate_report_markdown") or state_json.get("final_report") or ""
        eval_id = data.get("eval_id") or f"legal_eval_{(task_id or 'manual').lower()}_{uuid.uuid4().hex[:8]}"
        return LegalEvalInput(
            eval_id=eval_id,
            task_id=task_id,
            session_id=data.get("session_id") or state_json.get("session_id"),
            task_meta=task_meta,
            candidate_report_markdown=report,
            state_json=state_json,
            process_events=process_events,
            source_index=source_index,
            risk_items=risk_items,
            evidence_chain=evidence_chain,
            gold_reference=gold_reference,
            run_meta=data.get("run_meta") or {},
            judge_mode=data.get("judge_mode") or "mock",
            require_llm=bool(data.get("require_llm")),
        )

    def _infer_task_id(self, data: Dict[str, Any]) -> str | None:
        for key in ("report_path", "batch_result_path", "events_path"):
            value = data.get(key)
            if value:
                stem = Path(value).stem
                if stem:
                    return stem
        return None
