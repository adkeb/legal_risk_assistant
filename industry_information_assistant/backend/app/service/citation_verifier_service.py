# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Basic citation and evidence-chain verification for legal risks."""

from typing import Any, Dict, List


class CitationVerifierService:
    """基础证据链核验服务。第一阶段做结构完整性检查。"""

    REQUIRED_SOURCE_TYPES = {
        "law",
        "regulation",
        "judicial_interpretation",
        "case",
        "court_decision",
        "enforcement",
        "contract",
        "internal_policy",
        "regulator_guidance",
        "company_record",
    }

    @classmethod
    def verify_risk_items(cls, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        checks: List[Dict[str, Any]] = []
        evidence_ids = {
            cls._item_id(item, "evidence_id")
            for item in state.get("evidence_chain", [])
            if cls._item_id(item, "evidence_id")
        }
        legal_source_ids = {
            cls._item_id(item, "source_id")
            for item in state.get("legal_sources", [])
            if cls._item_id(item, "source_id")
        }

        for risk in state.get("risk_items", []):
            if not isinstance(risk, dict):
                risk = {"risk_id": str(risk)}
            risk_id = str(risk.get("risk_id", ""))
            linked_evidence = cls._normalize_ids(risk.get("evidence_ids", []) or [], "evidence_id")
            linked_basis = cls._normalize_ids(risk.get("legal_basis_ids", []) or [], "source_id")

            missing_evidence = [ev for ev in linked_evidence if ev not in evidence_ids]
            missing_basis = [src for src in linked_basis if src not in legal_source_ids]

            status = "passed"
            if not linked_evidence and not linked_basis:
                status = "missing"
            elif missing_evidence or missing_basis:
                status = "weak"

            checks.append({
                "target_id": risk_id,
                "target_type": "risk_item",
                "status": status,
                "missing_evidence": missing_evidence,
                "missing_basis": missing_basis,
            })

        return checks

    @classmethod
    def _normalize_ids(cls, value: Any, preferred_key: str) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        return [item_id for item_id in (cls._item_id(item, preferred_key) for item in value) if item_id]

    @staticmethod
    def _item_id(item: Any, preferred_key: str) -> str:
        if isinstance(item, dict):
            for key in (preferred_key, "id", "source_id", "evidence_id", "risk_id", "title"):
                value = item.get(key)
                if value:
                    return str(value)
            return str(item)
        return str(item) if item else ""
