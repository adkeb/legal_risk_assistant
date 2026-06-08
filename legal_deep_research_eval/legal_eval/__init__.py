"""Independent legal DeepResearch evaluation system."""

from .schemas import LegalEvalRequest, LegalEvalResult
from .service import LegalEvalService

__all__ = ["LegalEvalRequest", "LegalEvalResult", "LegalEvalService"]
