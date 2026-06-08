"""DeepResearch process trace analysis."""

from __future__ import annotations

from typing import Any, Dict, List

from ..utils import ratio


EXPECTED_PHASES = ("planning", "researching", "analyzing", "writing", "reviewing", "completed")


class ProcessTraceAnalyzerTool:
    def analyze(
        self,
        state_json: Dict[str, Any],
        process_events: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        events = process_events or []
        messages = state_json.get("messages") if isinstance(state_json.get("messages"), list) else []
        combined = events + messages
        phase_values = set()
        search_calls = 0
        queries = set()
        critic_loop_count = 0
        revision_count = 0
        re_research_count = 0
        num_agent_steps = 0

        for event in combined:
            normalized = self._normalize_event(event)
            etype = normalized.get("type") or normalized.get("event_type")
            phase = normalized.get("phase")
            if etype == "phase" and phase:
                phase_values.add(str(phase))
            if phase:
                phase_values.add(str(phase))
            if etype in {"search_results", "search_progress"}:
                search_calls += 1
            if etype == "action" and normalized.get("tool") and "search" in str(normalized.get("tool")):
                search_calls += 1
            query = normalized.get("query")
            if query:
                queries.add(str(query))
            if etype == "critic_feedback" or normalized.get("agent") == "CriticMaster":
                critic_loop_count += 1
            text = str(normalized)
            if "re_research" in text or "re_researching" in text:
                re_research_count += 1
            if "revision" in text or "修订" in text:
                revision_count += 1
            if etype in {"research_step", "thought", "action"}:
                num_agent_steps += 1

        if state_json.get("phase"):
            phase_values.add(str(state_json.get("phase")))
        if state_json.get("outline"):
            phase_values.add("planning")
        if state_json.get("raw_sources") or state_json.get("legal_sources"):
            phase_values.add("researching")
        if state_json.get("risk_items") or state_json.get("facts"):
            phase_values.add("analyzing")
        if state_json.get("final_report"):
            phase_values.update({"writing", "completed"})
        if state_json.get("critic_feedback"):
            critic_loop_count += len(state_json.get("critic_feedback") or []) if isinstance(state_json.get("critic_feedback"), list) else 1
            phase_values.add("reviewing")

        phase_coverage = ratio(sum(1 for phase in EXPECTED_PHASES if phase in phase_values), len(EXPECTED_PHASES), default=0.0)
        event_completeness = 1.0 if combined else 0.0
        if not state_json.get("final_report"):
            event_completeness *= 0.7
        return {
            "phase_coverage": phase_coverage,
            "event_completeness_rate": event_completeness,
            "num_agent_steps": num_agent_steps,
            "num_search_calls": search_calls,
            "unique_queries": len(queries),
            "critic_loop_count": critic_loop_count,
            "re_research_count": re_research_count,
            "revision_count": revision_count,
            "has_planning": "planning" in phase_values,
            "has_researching": "researching" in phase_values,
            "has_analyzing": "analyzing" in phase_values,
            "has_writing": "writing" in phase_values,
            "has_reviewing": "reviewing" in phase_values,
            "has_completed": "completed" in phase_values,
        }

    def _normalize_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(event, dict):
            return {}
        message = event.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            base = {**event, **message}
            if isinstance(content, dict):
                base.update(content)
            return base
        content = event.get("content")
        if isinstance(content, dict):
            return {**event, **content}
        return event
