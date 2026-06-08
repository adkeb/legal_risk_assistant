# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
LLM 和 Agent 配置文件

集中管理所有 LLM 相关配置，包括：
- API 配置（密钥、基础 URL）
- 每个 Agent 节点的模型配置
- 研究流程参数

使用方式:
    from app.config.llm_config import LLMConfig, AgentConfig

    config = LLMConfig()
    print(config.default_model)
    print(config.agents.quality_routing.model)
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:
    pass


def _env_first(*keys: str, default: str = "") -> str:
    """Read the first non-empty environment variable."""
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return default


def _env_model(default: str, *keys: str) -> str:
    """Read model override from agent-specific env vars, then global env vars."""
    return _env_first(*keys, "LLM_MODEL", "DEFAULT_MODEL", "DASHSCOPE_MODEL", "OPENAI_MODEL", "MODEL", default=default)


@dataclass
class AgentModelConfig:
    """单个 Agent 的模型配置"""
    model: str
    temperature: float = 0.7
    max_tokens: int = 8000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }


@dataclass
class AgentsConfig:
    """五 Agent 法律风控工作流配置"""

    scope_definition: AgentModelConfig = field(default_factory=lambda: AgentModelConfig(
        model=_env_model("", "SCOPE_DEFINITION_MODEL"),
        temperature=0.7,
        max_tokens=4000
    ))

    source_verification: AgentModelConfig = field(default_factory=lambda: AgentModelConfig(
        model=_env_model("", "SOURCE_VERIFICATION_MODEL"),
        temperature=0.2,
        max_tokens=8000
    ))

    evidence_catalog: AgentModelConfig = field(default_factory=lambda: AgentModelConfig(
        model=_env_model("", "EVIDENCE_CATALOG_MODEL"),
        temperature=0.2,
        max_tokens=8000
    ))

    legal_analysis_draft: AgentModelConfig = field(default_factory=lambda: AgentModelConfig(
        model=_env_model("", "LEGAL_ANALYSIS_DRAFT_MODEL"),
        temperature=0.7,
        max_tokens=16000
    ))

    quality_routing: AgentModelConfig = field(default_factory=lambda: AgentModelConfig(
        model=_env_model("", "QUALITY_ROUTING_MODEL"),
        temperature=0.1,
        max_tokens=8000
    ))

@dataclass
class ResearchConfig:
    """研究流程配置"""
    # 最大迭代次数（审核-修订循环）
    max_iterations: int = 3

    # 每个章节最大搜索数量
    max_searches_per_section: int = 3

    # 最大图表数量
    max_charts: int = 5

    # 质量评分阈值（百分制）
    quality_threshold: float = 80.0

    # 法律风控模式开关
    legal_mode: bool = True

    # 法律资料与报告约束
    max_legal_sources: int = 30
    require_disclaimer: bool = False
    require_citation_for_major_claims: bool = True
    human_review_when_uncertain: bool = True


@dataclass
class LLMConfig:
    """
    LLM 配置主类

    集中管理所有配置，支持从环境变量读取
    """
    # API 配置
    api_key: str = field(default_factory=lambda: _env_first("LLM_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY"))
    base_url: str = field(default_factory=lambda: _env_first("LLM_BASE_URL", "DASHSCOPE_BASE_URL", "OPENAI_BASE_URL"))

    # 搜索 API
    search_provider: str = field(default_factory=lambda: os.getenv("SEARCH_PROVIDER", "tavily").strip().lower() or "tavily")
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))
    bocha_api_key: str = field(default_factory=lambda: os.getenv("BOCHA_API_KEY", ""))
    search_api_key: str = field(default_factory=lambda: os.getenv("BOCHA_API_KEY", ""))

    # 默认模型（用于未单独配置的场景）
    default_model: str = field(default_factory=lambda: _env_model("", "DEFAULT_MODEL"))

    # Agent 配置
    agents: AgentsConfig = field(default_factory=AgentsConfig)

    # 研究流程配置
    research: ResearchConfig = field(default_factory=ResearchConfig)

    def get_agent_config(self, agent_name: str) -> AgentModelConfig:
        """获取指定 Agent 的配置"""
        agent_configs = {
            "scope_definition": self.agents.scope_definition,
            "source_verification": self.agents.source_verification,
            "evidence_catalog": self.agents.evidence_catalog,
            "legal_analysis_draft": self.agents.legal_analysis_draft,
            "quality_routing": self.agents.quality_routing,
        }
        return agent_configs.get(agent_name, AgentModelConfig(model=self.default_model))

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "api_key": self.api_key[:8] + "..." if self.api_key else "",
            "base_url": self.base_url,
            "search_provider": self.search_provider,
            "tavily_api_key": self.tavily_api_key[:8] + "..." if self.tavily_api_key else "",
            "bocha_api_key": self.bocha_api_key[:8] + "..." if self.bocha_api_key else "",
            "search_api_key": self.search_api_key[:8] + "..." if self.search_api_key else "",
            "default_model": self.default_model,
            "agents": {
                "scope_definition": self.agents.scope_definition.to_dict(),
                "source_verification": self.agents.source_verification.to_dict(),
                "evidence_catalog": self.agents.evidence_catalog.to_dict(),
                "legal_analysis_draft": self.agents.legal_analysis_draft.to_dict(),
                "quality_routing": self.agents.quality_routing.to_dict(),
            },
            "research": {
                "max_iterations": self.research.max_iterations,
                "max_searches_per_section": self.research.max_searches_per_section,
                "max_charts": self.research.max_charts,
                "quality_threshold": self.research.quality_threshold,
                "legal_mode": self.research.legal_mode,
                "max_legal_sources": self.research.max_legal_sources,
                "require_disclaimer": self.research.require_disclaimer,
                "require_citation_for_major_claims": self.research.require_citation_for_major_claims,
                "human_review_when_uncertain": self.research.human_review_when_uncertain,
            }
        }


# 全局配置实例（单例模式）
_config_instance: Optional[LLMConfig] = None


def get_config() -> LLMConfig:
    """获取全局配置实例"""
    global _config_instance
    if _config_instance is None:
        _config_instance = LLMConfig()
    return _config_instance


def reload_config() -> LLMConfig:
    """重新加载配置"""
    global _config_instance
    _config_instance = LLMConfig()
    return _config_instance


# 便捷访问
def get_agent_model(agent_name: str) -> str:
    """快速获取指定 Agent 的模型名称"""
    return get_config().get_agent_config(agent_name).model


def get_default_model() -> str:
    """快速获取默认模型"""
    return get_config().default_model


# 用于打印配置信息
def print_config():
    """打印当前配置（用于调试）"""
    import json
    config = get_config()
    print("=" * 60)
    print("LLM Configuration")
    print("=" * 60)
    print(json.dumps(config.to_dict(), indent=2, ensure_ascii=False))
    print("=" * 60)


if __name__ == "__main__":
    # 测试配置
    print_config()
