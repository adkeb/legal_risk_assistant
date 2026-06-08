# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Legal-risk DeepResearch V2 five-agent workflow."""

from .state import (
    ResearchState,
    ResearchPhase,
    create_initial_state,
    ensure_artifact_state_defaults,
    get_final_report,
    get_quality_score,
    get_references,
)
from .graph import DeepResearchGraph, create_research_graph
from .agents import (
    ScopeDefinitionAgent,
    SourceVerificationAgent,
    EvidenceCatalogAgent,
    LegalAnalysisDraftAgent,
    QualityRoutingAgent,
)

__all__ = [
    "ResearchState",
    "ResearchPhase",
    "create_initial_state",
    "ensure_artifact_state_defaults",
    "get_final_report",
    "get_quality_score",
    "get_references",
    "DeepResearchGraph",
    "create_research_graph",
    "ScopeDefinitionAgent",
    "SourceVerificationAgent",
    "EvidenceCatalogAgent",
    "LegalAnalysisDraftAgent",
    "QualityRoutingAgent",
]
