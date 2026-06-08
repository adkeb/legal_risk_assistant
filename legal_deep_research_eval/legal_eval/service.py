"""Public service wrapper around the fixed orchestrator."""

from __future__ import annotations

from .orchestrator import LegalEvalOrchestrator
from .schemas import LegalEvalRequest, LegalEvalResult
from .tools.result_store import EvalResultStoreTool


class LegalEvalService:
    def __init__(self, result_store: EvalResultStoreTool | None = None) -> None:
        self.orchestrator = LegalEvalOrchestrator(result_store=result_store)

    def evaluate(self, request: LegalEvalRequest) -> LegalEvalResult:
        return self.orchestrator.evaluate(request)
