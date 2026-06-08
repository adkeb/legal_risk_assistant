"""Evidence-chain verification."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ..utils import ratio


HIGH_RISK_RE = re.compile(r"(高|重大|critical|high)", re.I)
NORMATIVE_TYPES = {"law", "regulation", "judicial_interpretation", "court_decision", "regulator_guidance"}


class EvidenceChainVerifierTool:
    def verify(
        self,
        risk_items: List[Dict[str, Any]],
        evidence_chain: List[Dict[str, Any]],
        source_index: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        evidence_by_id = {
            str(item.get("evidence_id") or item.get("id")): item
            for item in evidence_chain
            if item.get("evidence_id") or item.get("id")
        }
        source_by_id = {str(item.get("source_id")): item for item in source_index if item.get("source_id")}
        risks_with_evidence = 0
        unsupported_high: List[str] = []
        weak: List[Dict[str, Any]] = []
        high_total = 0
        high_dual_basis = 0

        for idx, risk in enumerate(risk_items or [], start=1):
            risk_id = str(risk.get("risk_id") or risk.get("id") or f"R{idx}")
            level = str(risk.get("risk_level") or risk.get("level") or risk.get("severity") or "")
            is_high = bool(HIGH_RISK_RE.search(level))
            if is_high:
                high_total += 1
            evidence_ids = [str(item) for item in (risk.get("evidence_ids") or []) if item]
            law_ids = [str(item) for item in (risk.get("supporting_law_ids") or risk.get("law_ids") or []) if item]
            if evidence_ids or law_ids:
                risks_with_evidence += 1
            if is_high and not evidence_ids:
                unsupported_high.append(risk_id)
            missing_evidence = [eid for eid in evidence_ids if eid not in evidence_by_id]
            if missing_evidence:
                weak.append({"risk_id": risk_id, "reason": "missing_evidence", "missing_ids": missing_evidence})
            source_ids = [
                str(evidence_by_id[eid].get("source_id"))
                for eid in evidence_ids
                if eid in evidence_by_id and evidence_by_id[eid].get("source_id")
            ]
            missing_sources = [sid for sid in source_ids if sid not in source_by_id]
            if missing_sources:
                weak.append({"risk_id": risk_id, "reason": "missing_source", "missing_ids": missing_sources})
            has_fact_basis = bool(evidence_ids)
            has_normative_basis = bool(law_ids) or any(
                str(source_by_id.get(sid, {}).get("source_type", "")).lower() in NORMATIVE_TYPES
                for sid in source_ids
            )
            if is_high and has_fact_basis and has_normative_basis:
                high_dual_basis += 1
            if is_high and not has_normative_basis:
                weak.append({"risk_id": risk_id, "reason": "missing_normative_basis", "missing_ids": []})

        risk_ratio = ratio(risks_with_evidence, len(risk_items or []), default=1.0)
        dual_ratio = ratio(high_dual_basis, high_total, default=1.0)
        return {
            "evidence_chain_complete": not unsupported_high and not weak,
            "risk_with_evidence_ratio": risk_ratio,
            "high_risk_dual_basis_ratio": dual_ratio,
            "unsupported_high_risk_items": unsupported_high,
            "weak_evidence_risk_items": weak,
        }
