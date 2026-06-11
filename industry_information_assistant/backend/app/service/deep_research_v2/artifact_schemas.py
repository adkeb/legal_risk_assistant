"""Pydantic schemas and helpers for legal DeepResearch artifacts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _model_validate(model_cls, data: Dict[str, Any]):
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(data)
    return model_cls.parse_obj(data)


def _model_dump(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class ArtifactMeta(StrictModel):
    agent: str
    artifact_id: str
    status: str = Field(pattern="^(ok|needs_more_facts|needs_primary_recheck|hard_fail)$")
    confidence: float = Field(ge=0, le=1)


class ArtifactHandoff(StrictModel):
    next_agent: str
    reason: str


class AgentArtifactEnvelope(StrictModel):
    meta: ArtifactMeta
    writes: Dict[str, Any]
    handoff: ArtifactHandoff


class Jurisdiction(StrictModel):
    primary: Optional[str] = None
    others: List[str] = []
    status: str = Field(pattern="^(confirmed|assumed|unknown)$")
    jurisdiction_candidates: List[str] = []
    why_unknown: str = ""


class HumanReview(StrictModel):
    required: bool
    reasons: List[str] = []


class Issue(StrictModel):
    issue_id: str
    question: str
    priority: str = Field(pattern="^P[0-3]$")
    evidence_needed: List[str] = []


class ScopeBriefWrites(StrictModel):
    task_type: str
    jurisdiction: Jurisdiction
    issue_tree: List[Issue]
    facts_known: List[str]
    facts_assumed: List[str]
    facts_missing: List[str]
    source_targets: List[str]
    clarification_questions: List[str]
    human_review: HumanReview


class IssueSource(StrictModel):
    issue_id: str
    proposition: str
    source_id: str
    jurisdiction: str
    title: str
    issuing_body: str = ""
    source_kind: str
    source_tier: str = Field(pattern="^T[1-5]$")
    article_or_section: str
    effective_status: str = Field(pattern="^(effective|amended|repealed|unknown)$")
    exact_quote: str
    pinpoint: str = ""
    language: str = "zh-CN"
    verification_status: str
    use_for_load_bearing: bool
    not_load_bearing_reason: str = ""
    url: str = ""


class SourcePackWrites(StrictModel):
    issue_sources: List[IssueSource]
    unresolved_source_gaps: List[str]
    search_summary: Dict[str, Any] = Field(default_factory=dict)
    source_health: str = "unknown"


class FactItem(StrictModel):
    fact_id: str
    statement: str
    evidence_ids: List[str]
    status: str = Field(pattern="^(verified|partially_verified|assumed)$")


class EvidenceItem(StrictModel):
    evidence_id: str
    source_type: str
    locator: str
    excerpt: str
    read_status: str = Field(pattern="^(read|unread|partial)$")


class IssueEvidence(StrictModel):
    issue_id: str
    supporting_evidence: List[str]
    conflicting_evidence: List[str]
    missing_evidence: List[str]


class MaterialStatus(StrictModel):
    material_id: str
    status: str = Field(pattern="^(read|partial|material_unread)$")
    reason: str = ""


class EvidenceMatrixWrites(StrictModel):
    facts: List[FactItem]
    evidence_items: List[EvidenceItem]
    issue_evidence_matrix: List[IssueEvidence]
    material_read_status: List[MaterialStatus]
    missing_materials: List[str]


class IssueAnalysis(StrictModel):
    issue_id: str
    conclusion: str
    reasoning: str
    source_ids: List[str]
    evidence_ids: List[str]
    certainty: str = Field(pattern="^(high|medium|low|pending_verification)$")


class RiskItem(StrictModel):
    risk_id: str
    title: str
    level: str = Field(pattern="^(critical|high|medium|low|note)$")
    priority: str = Field(pattern="^P[0-3]$")
    source_ids: List[str]
    evidence_ids: List[str]


class ActionItem(StrictModel):
    action_id: str
    priority: str = Field(pattern="^P[0-3]$")
    owner: str
    description: str
    depends_on: List[str] = []


class CitationIndexItem(StrictModel):
    citation_tag: str
    source_id: str


class AnalysisDraftWrites(StrictModel):
    issue_analysis: List[IssueAnalysis]
    risk_register: List[RiskItem]
    action_plan: List[ActionItem]
    report_markdown: str
    citation_index: List[CitationIndexItem]
    human_review: HumanReview


class DimensionScores(StrictModel):
    jurisdiction_scope: float
    source_accuracy: float
    evidence_closure: float
    phase_discipline: float
    reasoning_quality: float
    readability: float


class QAIssue(StrictModel):
    severity: str = Field(pattern="^(critical|major|minor)$")
    type: str
    message: str
    route_to: str = Field(pattern="^(scope_definition|source_verification|evidence_catalog|legal_analysis_draft)$")


class QARoute(StrictModel):
    next_agent: str = Field(pattern="^(scope_definition|source_verification|evidence_catalog|legal_analysis_draft|END)$")
    instruction: str


class QAVerdictWrites(StrictModel):
    score_total: float = Field(ge=0, le=100)
    dimension_scores: DimensionScores
    hard_failures: List[str]
    issues: List[QAIssue]
    verdict: str
    route: QARoute


WRITE_MODELS = {
    "scope_brief": ScopeBriefWrites,
    "source_pack": SourcePackWrites,
    "evidence_matrix": EvidenceMatrixWrites,
    "analysis_draft": AnalysisDraftWrites,
    "qa_verdict": QAVerdictWrites,
}


def make_envelope(
    *,
    agent: str,
    artifact_id: str,
    writes: Dict[str, Any],
    next_agent: str,
    reason: str,
    status: str = "ok",
    confidence: float = 0.7,
) -> Dict[str, Any]:
    return {
        "meta": {
            "agent": agent,
            "artifact_id": artifact_id,
            "status": status,
            "confidence": max(0.0, min(float(confidence), 1.0)),
        },
        "writes": writes,
        "handoff": {
            "next_agent": next_agent,
            "reason": reason,
        },
    }


def validate_artifact(artifact_key: str, envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an artifact envelope and its stage-specific writes."""

    if "meta" not in envelope or "writes" not in envelope or "handoff" not in envelope:
        envelope = make_envelope(
            agent=str(envelope.get("agent") or artifact_key),
            artifact_id=artifact_key,
            writes=dict(envelope),
            next_agent="",
            reason="LLM returned raw writes; wrapped by parser.",
        )
    validated_envelope = _model_validate(AgentArtifactEnvelope, envelope)
    writes_model = WRITE_MODELS[artifact_key]
    validated_writes = _model_validate(writes_model, validated_envelope.writes)
    data = _model_dump(validated_envelope)
    data["writes"] = _model_dump(validated_writes)
    return data
