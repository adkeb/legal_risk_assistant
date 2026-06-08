# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Service package exports.

Some legacy services depend on optional runtime packages. Keep package imports
lightweight so focused component tests can import new services without loading
the entire application stack.
"""

import importlib
import logging

logger = logging.getLogger(__name__)


def _optional_attr(module_name: str, attr_name: str):
    try:
        module = importlib.import_module(f".{module_name}", __name__)
        return getattr(module, attr_name)
    except Exception as exc:
        logger.debug("Optional service import skipped: %s.%s (%s)", module_name, attr_name, exc)
        return None


DocumentService = _optional_attr("document_service", "DocumentService")
ServiceConfig = _optional_attr("config", "ServiceConfig")
WebSearchService = _optional_attr("web_search_service", "WebSearchService")
ChatService = _optional_attr("chat_service", "ChatService")
SessionService = _optional_attr("session_service", "SessionService")
PolicySearchService = _optional_attr("policy_search_service", "PolicySearchService")
ResearchService = _optional_attr("dr_g", "ResearchService")

# ReAct 架构组件
ReActController = _optional_attr("react_controller", "ReActController")
create_default_tools = _optional_attr("react_controller", "create_default_tools")
ToolExecutor = _optional_attr("tool_executor", "ToolExecutor")
create_tool_executor = _optional_attr("tool_executor", "create_tool_executor")
Text2SQLService = _optional_attr("text2sql_service", "Text2SQLService")
create_text2sql_service = _optional_attr("text2sql_service", "create_text2sql_service")
SmartDataAnalyzer = _optional_attr("smart_analyzer", "SmartDataAnalyzer")
create_smart_analyzer = _optional_attr("smart_analyzer", "create_smart_analyzer")
ChartGenerator = _optional_attr("chart_generator", "ChartGenerator")
create_chart_generator = _optional_attr("chart_generator", "create_chart_generator")

__all__ = [
    "DocumentService",
    "ServiceConfig",
    "WebSearchService",
    "ChatService",
    "SessionService",
    "PolicySearchService",
    "ResearchService",
    "ReActController",
    "create_default_tools",
    "ToolExecutor",
    "create_tool_executor",
    "Text2SQLService",
    "create_text2sql_service",
    "SmartDataAnalyzer",
    "create_smart_analyzer",
    "ChartGenerator",
    "create_chart_generator",
]
