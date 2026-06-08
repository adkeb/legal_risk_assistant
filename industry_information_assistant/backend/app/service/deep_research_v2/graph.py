# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Five-agent legal-risk DeepResearch orchestrator."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

try:
    from router.research_router import is_research_cancelled, clear_cancel_flag
except ImportError:
    try:
        from app.router.research_router import is_research_cancelled, clear_cancel_flag
    except ImportError:
        def is_research_cancelled(session_id: str) -> bool:
            return False

        def clear_cancel_flag(session_id: str) -> None:
            pass

from .state import (
    ResearchPhase,
    ResearchState,
    create_initial_state,
    ensure_artifact_state_defaults,
    get_artifact_writes,
    get_final_report,
    get_quality_score,
    get_references,
    is_legacy_state,
)
from .agents import (
    ScopeDefinitionAgent,
    SourceVerificationAgent,
    EvidenceCatalogAgent,
    LegalAnalysisDraftAgent,
    QualityRoutingAgent,
)
from .trace_recorder import (
    CURRENT_AGENT_RUN_ID,
    CURRENT_TRACE,
    TraceRecorder,
    clone_state_for_trace,
    is_trace_enabled,
)

try:
    from service.checkpoint_service import get_checkpoint_service
except ImportError:
    try:
        from app.service.checkpoint_service import get_checkpoint_service
    except ImportError:
        def get_checkpoint_service():
            return None

try:
    from config.llm_config import get_config
except ImportError:
    try:
        from app.config.llm_config import get_config
    except ImportError:
        import os
        import sys

        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from config.llm_config import get_config


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DeepResearchGraph")


class DeepResearchGraph:
    """Legal-risk workflow: A1 scope -> A2 sources -> A3 evidence -> A4 report -> A5 QA."""

    PHASE_RUNS = [
        ("planning", ResearchPhase.PLANNING, "开始立项定界...", "A1"),
        ("researching", ResearchPhase.RESEARCHING, "开始法源检索与引注核验...", "A2"),
        ("analyzing", ResearchPhase.ANALYZING, "开始事实证据编目...", "A3"),
        ("writing", ResearchPhase.WRITING, "开始法律分析与报告起草...", "A4"),
        ("reviewing", ResearchPhase.REVIEWING, "开始质量评估与路由...", "A5"),
    ]

    DOWNSTREAM = {
        "A1": ["A1", "A2", "A3", "A4", "A5"],
        "A2": ["A2", "A3", "A4", "A5"],
        "A3": ["A3", "A4", "A5"],
        "A4": ["A4", "A5"],
        "A5": ["A5"],
    }

    AGENT_PHASE = {
        "A1": ("planning", ResearchPhase.PLANNING, "重新立项定界..."),
        "A2": ("re_researching", ResearchPhase.RE_RESEARCHING, "根据审查反馈补充法源核验..."),
        "A3": ("analyzing", ResearchPhase.ANALYZING, "根据审查反馈重建证据矩阵..."),
        "A4": ("revising", ResearchPhase.REVISING, "根据审查反馈修订分析报告..."),
        "A5": ("reviewing", ResearchPhase.REVIEWING, "重新质量评估..."),
    }

    def __init__(
        self,
        llm_api_key: str = None,
        llm_base_url: str = None,
        search_api_key: str = None,
        model: str = None,
        max_iterations: int = None,
    ):
        config = get_config()
        self.config = config
        self.llm_api_key = llm_api_key or config.api_key
        self.llm_base_url = llm_base_url or config.base_url
        self.search_api_key = search_api_key or config.search_api_key
        self.model = model or config.default_model
        configured_iterations = config.research.max_iterations if max_iterations is None else max_iterations
        self.max_iterations = max(0, min(int(configured_iterations or 0), 3))

        self.scope_definition = ScopeDefinitionAgent(
            self.llm_api_key,
            self.llm_base_url,
            config.agents.scope_definition.model,
        )
        self.source_verification = SourceVerificationAgent(
            self.llm_api_key,
            self.llm_base_url,
            self.search_api_key,
            config.agents.source_verification.model,
        )
        self.evidence_catalog = EvidenceCatalogAgent(
            self.llm_api_key,
            self.llm_base_url,
            config.agents.evidence_catalog.model,
        )
        self.legal_analysis_draft = LegalAnalysisDraftAgent(
            self.llm_api_key,
            self.llm_base_url,
            config.agents.legal_analysis_draft.model,
        )
        self.quality_routing = QualityRoutingAgent(
            self.llm_api_key,
            self.llm_base_url,
            config.agents.quality_routing.model,
        )
        self.agents_by_code = {
            "A1": self.scope_definition,
            "A2": self.source_verification,
            "A3": self.evidence_catalog,
            "A4": self.legal_analysis_draft,
            "A5": self.quality_routing,
        }
        logger.info("DeepResearchGraph initialized with five legal workflow agents.")
        logger.info("  - A1 ScopeDefinitionAgent: %s", config.agents.scope_definition.model)
        logger.info("  - A2 SourceVerificationAgent: %s", config.agents.source_verification.model)
        logger.info("  - A3 EvidenceCatalogAgent: %s", config.agents.evidence_catalog.model)
        logger.info("  - A4 LegalAnalysisDraftAgent: %s", config.agents.legal_analysis_draft.model)
        logger.info("  - A5 QualityRoutingAgent: %s", config.agents.quality_routing.model)

        self.checkpoint_service = get_checkpoint_service()
        self.graph = None

    def _save_checkpoint(
        self,
        state: Dict[str, Any],
        user_id: str = None,
        ui_state: Dict[str, Any] = None,
    ) -> bool:
        if not self.checkpoint_service:
            return False
        session_id = state.get("session_id", "")
        if not session_id:
            return False
        try:
            checkpoint_id = self.checkpoint_service.save_checkpoint(
                session_id=session_id,
                state=state,
                user_id=user_id,
                ui_state=ui_state,
                final_report=get_final_report(state),
            )
            if checkpoint_id:
                logger.info("Checkpoint saved: %s", checkpoint_id)
                return True
        except Exception as exc:
            logger.warning("Failed to save checkpoint: %s", exc)
        return False

    def _load_checkpoint(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not self.checkpoint_service:
            return None
        state = self.checkpoint_service.load_checkpoint(session_id)
        if not state:
            return None
        if is_legacy_state(state):
            raise RuntimeError("旧版共享字段 checkpoint 与五工件法律工作流不兼容，请新建研究任务。")
        ensure_artifact_state_defaults(state)
        logger.info("Checkpoint loaded for session: %s", session_id)
        return state

    def get_checkpoint_info(self, session_id: str) -> Dict[str, Any]:
        if not self.checkpoint_service:
            return None
        return self.checkpoint_service.get_checkpoint_info(session_id)

    async def run(
        self,
        query: str,
        session_id: str,
        resume: bool = False,
        user_id: str = None,
        search_web: bool = True,
        search_local: bool = False,
        allow_recursive_search: bool = True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        state = None
        created_new_state = False
        if resume and session_id:
            try:
                state = self._load_checkpoint(session_id)
            except RuntimeError as exc:
                yield {"type": "error", "content": str(exc), "session_id": session_id}
                return
            if state:
                yield {
                    "type": "research_resumed",
                    "phase": state.get("phase", ""),
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat(),
                }

        if not state:
            created_new_state = True
            state = create_initial_state(
                query,
                session_id,
                search_web=search_web,
                search_local=search_local,
            )
            state["max_iterations"] = self.max_iterations
            state["allow_recursive_search"] = allow_recursive_search

        ensure_artifact_state_defaults(state)
        if is_trace_enabled():
            trace = TraceRecorder(
                session_id=session_id,
                query=state.get("query", query),
                metadata={
                    "search_web": search_web,
                    "search_local": search_local,
                    "resume": resume,
                    "max_iterations": self.max_iterations,
                    "models": {
                        "scope_definition": self.config.agents.scope_definition.model,
                        "source_verification": self.config.agents.source_verification.model,
                        "evidence_catalog": self.config.agents.evidence_catalog.model,
                        "legal_analysis_draft": self.config.agents.legal_analysis_draft.model,
                        "quality_routing": self.config.agents.quality_routing.model,
                    },
                },
            )
            state["_trace_recorder"] = trace
            state["trace_info"] = trace.trace_info()
        else:
            state["_trace_recorder"] = None

        if created_new_state:
            start_event = {
                "type": "research_start",
                "query": state.get("query", query),
                "session_id": session_id,
                "search_web": search_web,
                "search_local": search_local,
                "timestamp": datetime.now().isoformat(),
                "trace_info": state.get("trace_info"),
            }
            if state.get("_trace_recorder"):
                state["_trace_recorder"].record_graph_event(start_event)
            state["trace_started"] = True
            yield start_event

        state["_user_id"] = user_id
        async for event in self._run_simplified(state):
            yield event

    async def _run_simplified(self, state: ResearchState) -> AsyncGenerator[Dict[str, Any], None]:
        message_queue = asyncio.Queue()
        state["_message_queue"] = message_queue
        trace: TraceRecorder = state.get("_trace_recorder")
        session_id = state.get("session_id", "")
        user_id = state.get("_user_id")

        if session_id:
            clear_cancel_flag(session_id)

        def graph_event(event: Dict[str, Any]) -> Dict[str, Any]:
            if trace:
                trace.record_graph_event(event)
            return event

        async def check_cancelled() -> bool:
            return bool(session_id and is_research_cancelled(session_id))

        async def run_agent_with_streaming(agent):
            if await check_cancelled():
                logger.info("Research cancelled before starting agent: %s", agent.name)
                return
            logger.info("Starting agent: %s", agent.name)
            run_id = None
            trace_token = None
            run_token = None
            agent_error = None
            if trace:
                run_id = trace.start_agent(
                    agent_name=agent.name,
                    role=getattr(agent, "role", ""),
                    state=clone_state_for_trace(state),
                )
                trace_token = CURRENT_TRACE.set(trace)
                run_token = CURRENT_AGENT_RUN_ID.set(run_id)

            task = asyncio.create_task(agent.process(state))
            while not task.done():
                if await check_cancelled():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    agent_error = "cancelled"
                    break
                try:
                    msg = await asyncio.wait_for(message_queue.get(), timeout=0.5)
                    yield msg
                except asyncio.TimeoutError:
                    continue
                except Exception as exc:
                    logger.warning("[%s] Queue error: %s", agent.name, exc)
                    continue

            try:
                await task
            except Exception as exc:
                agent_error = str(exc)
                logger.error("Agent %s error: %s", agent.name, exc)

            while not message_queue.empty():
                try:
                    yield message_queue.get_nowait()
                except Exception:
                    break

            if trace and run_id:
                trace.end_agent(
                    run_id=run_id,
                    agent_name=agent.name,
                    state=clone_state_for_trace(state),
                    error=agent_error,
                )
            if run_token is not None:
                CURRENT_AGENT_RUN_ID.reset(run_token)
            if trace_token is not None:
                CURRENT_TRACE.reset(trace_token)

        ui_state = {
            "research_steps": [],
            "search_results": [],
            "charts": [],
            "knowledge_graph": {"nodes": [], "edges": []},
            "streaming_report": "",
            "references": [],
            "artifacts": {},
        }

        def update_ui_state() -> None:
            ui_state["streaming_report"] = get_final_report(state)
            ui_state["references"] = get_references(state)
            ui_state["search_results"] = [
                {
                    "id": ref.get("id", ""),
                    "title": ref.get("title", ""),
                    "source": ref.get("source", "legal_source"),
                    "url": ref.get("link", ""),
                    "snippet": ref.get("content", "")[:200],
                    "date": "",
                }
                for ref in ui_state["references"]
            ]
            ui_state["artifacts"] = {
                key: {
                    "status": (value.get("meta") or {}).get("status"),
                    "agent": (value.get("meta") or {}).get("agent"),
                }
                for key, value in (state.get("artifacts") or {}).items()
                if value
            }
            logger.info(
                "[UI状态更新] artifacts=%s, references=%s, report_len=%s",
                list(ui_state["artifacts"].keys()),
                len(ui_state["references"]),
                len(ui_state["streaming_report"]),
            )

        async def save_checkpoint_async(step_info: Dict[str, Any] = None):
            update_ui_state()
            if step_info:
                existing = next(
                    (s for s in ui_state["research_steps"] if s.get("type") == step_info.get("type")),
                    None,
                )
                if existing:
                    existing.update(step_info)
                else:
                    ui_state["research_steps"].append(step_info)
            if self._save_checkpoint(state, user_id, ui_state):
                return {"type": "checkpoint_saved", "phase": state.get("phase", ""), "session_id": session_id}
            return None

        async def run_agent_code(agent_code: str) -> None:
            phase_name, phase_enum, content = self.AGENT_PHASE[agent_code]
            yield_phase = {"type": "phase", "phase": phase_name, "content": content}
            state["phase"] = phase_enum.value
            yield graph_event(yield_phase)
            async for msg in run_agent_with_streaming(self.agents_by_code[agent_code]):
                yield msg
            state["messages"] = []
            cp_event = await save_checkpoint_async({
                "type": phase_name,
                "status": "completed",
                "agent": agent_code,
                "artifact": self.agents_by_code[agent_code].artifact_key,
            })
            if cp_event:
                yield cp_event

        try:
            for step_type, phase_enum, content, agent_code in self.PHASE_RUNS:
                if await check_cancelled():
                    yield graph_event({"type": "research_cancelled", "message": "研究已取消"})
                    return
                yield graph_event({"type": "phase", "phase": step_type, "content": content})
                state["phase"] = phase_enum.value
                async for msg in run_agent_with_streaming(self.agents_by_code[agent_code]):
                    yield msg
                state["messages"] = []
                cp_event = await save_checkpoint_async({
                    "type": step_type,
                    "status": "completed",
                    "agent": agent_code,
                    "artifact": self.agents_by_code[agent_code].artifact_key,
                })
                if cp_event:
                    yield cp_event

            while state.get("iteration", 0) < state.get("max_iterations", 1):
                route = get_artifact_writes(state, "qa_verdict").get("route") or {}
                next_agent = route.get("next_agent")
                if not next_agent or next_agent == "END":
                    break
                state["iteration"] = int(state.get("iteration", 0)) + 1
                for agent_code in self.DOWNSTREAM.get(next_agent, []):
                    if await check_cancelled():
                        yield graph_event({"type": "research_cancelled", "message": "研究已取消"})
                        return
                    async for event in run_agent_code(agent_code):
                        yield event

            state["phase"] = ResearchPhase.COMPLETED.value
            if self.checkpoint_service and session_id:
                self.checkpoint_service.update_status(session_id, "completed")
            update_ui_state()
            if trace:
                trace.record_final_state(clone_state_for_trace(state))
            evidence_facts = get_artifact_writes(state, "evidence_matrix").get("facts") or []
            complete_event = {
                "type": "research_complete",
                "final_report": get_final_report(state),
                "quality_score": get_quality_score(state),
                "facts_count": len(evidence_facts),
                "charts_count": 0,
                "iterations": state.get("iteration", 0),
                "references": get_references(state),
                "qa_verdict": get_artifact_writes(state, "qa_verdict"),
                "artifacts": state.get("artifacts", {}),
                "trace_info": state.get("trace_info"),
            }
            yield graph_event(complete_event)

        except Exception as exc:
            logger.error("Simplified execution error: %s", exc)
            if self.checkpoint_service and session_id:
                self.checkpoint_service.update_status(session_id, "failed", str(exc))
            error_event = {"type": "error", "content": str(exc), "trace_info": state.get("trace_info")}
            if trace:
                trace.record_final_state(clone_state_for_trace(state))
            yield graph_event(error_event)
        finally:
            state["_message_queue"] = None

    async def run_sync(self, query: str, session_id: str) -> ResearchState:
        state = create_initial_state(query, session_id)
        state["max_iterations"] = self.max_iterations
        for _, phase_enum, _, agent_code in self.PHASE_RUNS:
            state["phase"] = phase_enum.value
            await self.agents_by_code[agent_code].process(state)
        state["phase"] = ResearchPhase.COMPLETED.value
        return state


def create_research_graph(
    llm_api_key: str = None,
    llm_base_url: str = None,
    search_api_key: str = None,
    model: str = None,
) -> DeepResearchGraph:
    return DeepResearchGraph(
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        search_api_key=search_api_key,
        model=model,
    )
