# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Deterministic legal risk scoring helpers."""

from typing import Any, Dict

try:
    from app.config.legal_risk_config import score_to_level
except ImportError:
    from config.legal_risk_config import score_to_level


class RiskScoringService:
    """法律风控风险评分服务。"""

    WEIGHTS = {
        "impact_score": 0.30,
        "probability_score": 0.20,
        "legal_certainty_score": 0.15,
        "evidence_strength_score": 0.15,
        "urgency_score": 0.10,
        "remediation_difficulty_score": 0.10,
    }

    @classmethod
    def normalize_score(cls, value: Any, default: float = 3.0) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return default
        return max(1.0, min(5.0, score))

    @classmethod
    def score_risk(cls, risk: Dict[str, Any]) -> Dict[str, Any]:
        total = 0.0
        for key, weight in cls.WEIGHTS.items():
            total += cls.normalize_score(risk.get(key)) * weight

        risk["overall_score"] = round(total, 2)
        risk["risk_level"] = score_to_level(total)
        risk["severity"] = risk["risk_level"]
        return risk
