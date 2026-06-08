# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Pydantic schemas used internally by the legal DeepResearch agents."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LegalJurisdiction(BaseModel):
    primary: str = "中国大陆"
    secondary: List[str] = Field(default_factory=list)
    cross_border: bool = False
    confidence: float = 0.0
    missing_info: List[str] = Field(default_factory=list)


class LegalSource(BaseModel):
    source_id: str
    source_type: str = "unknown"
    title: str = ""
    issuing_body: Optional[str] = None
    authority_level: Optional[str] = None
    jurisdiction: Optional[str] = None
    article_no: Optional[str] = None
    effective_date: Optional[str] = None
    expiry_date: Optional[str] = None
    validity_status: str = "unknown"
    url: Optional[str] = None
    retrieved_at: Optional[str] = None
    quoted_text: str = ""
    confidence: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ContractClause(BaseModel):
    clause_id: str
    document_id: Optional[str] = None
    clause_no: Optional[str] = None
    page_no: Optional[int] = None
    title: str = ""
    text: str = ""
    clause_type: str = "unknown"
    obligations: List[Dict[str, Any]] = Field(default_factory=list)
    deadlines: List[Dict[str, Any]] = Field(default_factory=list)
    risk_signals: List[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    evidence_id: str
    source_type: str
    source_id: str
    locator: str = ""
    quote: str = ""
    confidence: float = 0.0
    verification_status: str = "unverified"


class RiskItem(BaseModel):
    risk_id: str
    title: str
    risk_category: str = "unknown"
    risk_subtype: str = ""
    description: str = ""
    severity: str = "中风险"
    impact_score: float = 3.0
    probability_score: float = 3.0
    legal_certainty_score: float = 3.0
    evidence_strength_score: float = 3.0
    urgency_score: float = 3.0
    remediation_difficulty_score: float = 3.0
    overall_score: float = 3.0
    legal_basis_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    recommended_action: str = ""
    human_review_required: bool = False
