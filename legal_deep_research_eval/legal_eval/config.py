"""Configuration for the independent legal evaluation system."""

from __future__ import annotations

import os
from pathlib import Path


LEGAL_EVAL_VERSION = "legal_eval_v1"
RULE_ENGINE_VERSION = "legal_rule_engine_v1"

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PACKAGE_ROOT.parent
INDUSTRY_PROJECT_ROOT = WORKSPACE_ROOT / "industry_information_assistant"
INDUSTRY_BACKEND_ROOT = INDUSTRY_PROJECT_ROOT / "backend"
INDUSTRY_VENV_PYTHON = INDUSTRY_BACKEND_ROOT / ".venv" / "bin" / "python"

DEFAULT_QUESTION_BANK = WORKSPACE_ROOT / "2026年6月6日-30个法律风控问题.md"
DEFAULT_BENCHMARK_JSONL = PACKAGE_ROOT / "data" / "legal_benchmark_tasks.jsonl"
DEFAULT_EVAL_RESULTS_DIR = PACKAGE_ROOT / "eval_results"
DEFAULT_MANIFEST_DIR = PACKAGE_ROOT / "manifests"

LEGAL_EVAL_THRESHOLDS = {
    "quality_pass": 8.5,
    "quality_revise": 7.5,
    "fatal_release_block": True,
    "legal_factuality_fail": 4.0,
    "evidence_chain_revise": 4.0,
}

RESEARCH_QUALITY_WEIGHTS = {
    "legal_factuality": 0.18,
    "jurisdiction_version_match": 0.12,
    "coverage": 0.12,
    "evidence_chain": 0.16,
    "citation_quality": 0.12,
    "risk_consistency": 0.14,
    "legal_reasoning": 0.10,
    "legal_boundary_compliance": 0.06,
}

RESEARCH_PROCESS_WEIGHTS = {
    "planning_quality": 0.20,
    "retrieval_process": 0.30,
    "authority_priority": 0.20,
    "self_correction": 0.20,
    "trace_completeness": 0.10,
}

BUSINESS_EFFECT_WEIGHTS = {
    "expert_acceptability": 0.40,
    "editing_cost": 0.25,
    "business_actionability": 0.35,
}

OVERALL_WEIGHTS = {
    "research_quality": 0.60,
    "research_process": 0.25,
    "business_effect": 0.15,
}

HIGH_RISK_SCENARIO_KEYWORDS = (
    "诉讼",
    "仲裁",
    "行政处罚",
    "数据出境",
    "数据泄露",
    "劳动解除",
    "重大合同",
    "并购",
    "尽调",
    "跨境",
    "多法域",
    "制裁",
    "出口管制",
    "刑事",
)

LLM_ENV_KEYS = ("LEGAL_EVAL_LLM_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY", "DASHSCOPE_API_KEY")
LLM_MODEL_ENV_KEYS = ("LEGAL_EVAL_LLM_MODEL", "OPENAI_MODEL", "LLM_MODEL", "DEFAULT_MODEL")
LLM_BASE_URL_ENV_KEYS = ("LEGAL_EVAL_LLM_BASE_URL", "OPENAI_BASE_URL", "LLM_BASE_URL", "DASHSCOPE_BASE_URL")


def first_env(keys: tuple[str, ...], default: str = "") -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return default
