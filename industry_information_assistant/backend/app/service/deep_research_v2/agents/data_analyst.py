# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
DeepResearch V2.0 - 数据分析师 Agent (DataAnalyst)

职责：
1. 从搜索结果中提取结构化数据
2. 构建知识图谱(实体+关系)
3. 生成可视化图表配置(ECharts)
4. 识别数据趋势和洞察
"""

import uuid
from typing import Dict, Any, List
from datetime import datetime

from .base import BaseAgent
from ..state import ResearchState, ResearchPhase, ensure_legal_state_defaults
from ..prompts.legal_prompts import LEGAL_SYSTEM_RULES, LEGAL_RISK_ANALYST_PROMPT

try:
    from app.service.risk_scoring_service import RiskScoringService
except ImportError:
    from service.risk_scoring_service import RiskScoringService


def build_risk_distribution_chart(risk_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build an ECharts risk-level distribution chart."""
    levels = ["重大风险", "高风险", "中风险", "低风险", "提示项"]
    counts = {level: 0 for level in levels}
    for risk in risk_items:
        level = risk.get("risk_level") or risk.get("severity") or "中风险"
        counts[level] = counts.get(level, 0) + 1
    return {
        "id": "chart_risk_distribution",
        "title": "风险等级分布",
        "type": "bar",
        "echarts_option": {
            "tooltip": {"trigger": "axis"},
            "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
            "xAxis": {"type": "category", "data": levels},
            "yAxis": {"type": "value", "minInterval": 1},
            "series": [{
                "type": "bar",
                "data": [counts.get(level, 0) for level in levels],
                "itemStyle": {"color": "#1677ff"},
                "barWidth": 24,
            }],
        },
    }


def build_risk_matrix_chart(risk_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a risk matrix scatter chart from impact/probability scores."""
    data = [
        [
            RiskScoringService.normalize_score(risk.get("probability_score")),
            RiskScoringService.normalize_score(risk.get("impact_score")),
            risk.get("title", risk.get("risk_id", "风险")),
            risk.get("risk_level", risk.get("severity", "中风险")),
        ]
        for risk in risk_items
    ]
    return {
        "id": "chart_risk_matrix",
        "title": "风险矩阵",
        "type": "scatter",
        "echarts_option": {
            "tooltip": {
                "formatter": "{b}<br/>发生可能性: {@[0]}<br/>影响程度: {@[1]}"
            },
            "xAxis": {"type": "value", "name": "发生可能性", "min": 1, "max": 5},
            "yAxis": {"type": "value", "name": "影响程度", "min": 1, "max": 5},
            "series": [{
                "type": "scatter",
                "symbolSize": 16,
                "data": [{"name": item[2], "value": item} for item in data],
                "itemStyle": {"color": "#d4380d"},
            }],
        },
    }


def build_obligation_deadline_chart(obligations: List[Dict[str, Any]], deadlines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a compact obligation/deadline list chart for the frontend chart panel."""
    rows = []
    for obligation in obligations[:20]:
        rows.append([obligation.get("title") or obligation.get("description", "义务"), obligation.get("owner", "待确认"), obligation.get("deadline", "待确认")])
    for deadline in deadlines[:20]:
        rows.append([deadline.get("title") or deadline.get("description", "期限"), deadline.get("owner", "待确认"), deadline.get("date", deadline.get("deadline", "待确认"))])
    return {
        "id": "chart_obligation_deadlines",
        "title": "义务与期限清单",
        "type": "table",
        "echarts_option": {
            "title": {"text": "义务与期限清单", "left": "center"},
            "dataset": {"source": [["事项", "责任方", "期限"]] + rows},
            "series": [{"type": "table"}],
        },
        "data": {"headers": ["事项", "责任方", "期限"], "rows": rows},
    }


def build_legal_knowledge_graph(state: Dict[str, Any]) -> Dict[str, Any]:
    """Build a frontend-compatible legal knowledge graph."""
    nodes = []
    edges = []
    seen = set()

    def add_node(node_id: str, name: str, node_type: str) -> None:
        if not node_id or node_id in seen:
            return
        seen.add(node_id)
        nodes.append({"id": node_id, "name": name or node_id, "type": node_type})

    for party in state.get("parties", [])[:20]:
        if isinstance(party, dict) and party.get("name"):
            add_node(f"party_{len(nodes) + 1}", party.get("name"), "party")
    for source in state.get("legal_sources", [])[:30]:
        source_id = source.get("source_id", "")
        add_node(source_id, source.get("title", source_id), source.get("source_type", "law"))
    for evidence in state.get("evidence_chain", [])[:50]:
        evidence_id = evidence.get("evidence_id", "")
        add_node(evidence_id, evidence.get("locator") or evidence_id, "evidence")
        if evidence.get("source_id"):
            edges.append({"source": evidence.get("source_id"), "target": evidence_id, "type": "contains"})
    for risk in state.get("risk_items", [])[:50]:
        risk_id = risk.get("risk_id", "")
        add_node(risk_id, risk.get("title", risk_id), "risk")
        for evidence_id in risk.get("evidence_ids", []) or []:
            edges.append({"source": evidence_id, "target": risk_id, "type": "supports"})
        for source_id in risk.get("legal_basis_ids", []) or []:
            edges.append({"source": source_id, "target": risk_id, "type": "applies_to"})
    return {"nodes": nodes, "edges": edges}


class DataAnalyst(BaseAgent):
    """
    数据分析师 - 专注于数据提取、知识图谱和可视化

    特点：
    - 从文本中提取结构化数据点
    - 构建实体关系知识图谱
    - 生成ECharts可视化配置
    - 识别趋势和洞察
    """

    # 数据提取 Prompt
    DATA_EXTRACTION_PROMPT = """你是专业的数据分析师，擅长从文本中提取结构化数据。

## 研究主题
{query}

## 搜索结果
{search_results}

## 任务
从以上搜索结果中提取所有可量化的数据点，包括：
1. 风险数量、处罚次数、争议金额或期限数据
2. 增长率数据（百分比、时间段）
3. 风险类别、义务类型或责任主体占比
4. 排名数据（企业、产品、技术）
5. 时间序列数据（同一指标在不同年份的值）

## 输出要求
请输出JSON格式：
```json
{{
    "data_points": [
        {{
            "id": "dp_001",
            "name": "合同风险数量",
            "value": 5000,
            "unit": "亿元",
            "year": 2024,
            "source": "艾瑞咨询",
            "category": "market_size",
            "confidence": 0.9
        }}
    ],
    "time_series": [
        {{
            "id": "ts_001",
            "metric": "合同风险数量",
            "unit": "亿元",
            "data": [
                {{"year": 2020, "value": 3200}},
                {{"year": 2021, "value": 4100}},
                {{"year": 2024, "value": 8500}}
            ],
            "source": "艾瑞咨询"
        }}
    ],
    "distributions": [
        {{
            "id": "dist_001",
            "name": "风险类别占比",
            "year": 2024,
            "data": [
                {{"category": "计算机视觉", "value": 32, "unit": "%"}},
                {{"category": "自然语言处理", "value": 28, "unit": "%"}}
            ],
            "source": "IDC"
        }}
    ],
    "insights": [
        "识别到多个需人工复核的合同风险点",
        "计算机视觉是最大的细分领域，占比32%"
    ]
}}
```

注意：
- 只提取有明确来源的数据
- confidence表示数据可信度(0-1)
- 如果没有找到相关数据，返回空数组"""

    # 知识图谱构建 Prompt
    KNOWLEDGE_GRAPH_PROMPT = """你是知识图谱专家，擅长从文本中提取实体和关系。

## 研究主题
{query}

## 文本内容
{content}

## 任务
从以上文本中提取实体和关系，构建知识图谱。

## 实体类型定义
- core: 核心概念（如：人工智能、大模型）
- tech: 技术（如：深度学习、计算机视觉、NLP）
- company: 企业（如：百度、阿里巴巴、华为）
- policy: 政策（如：AI发展规划、数据安全法）
- product: 产品（如：ChatGPT、文心一言）
- person: 人物（如：创始人、CEO）

## 输出要求
请输出JSON格式：
```json
{{
    "nodes": [
        {{"id": "ai", "name": "人工智能", "type": "core", "importance": 10}},
        {{"id": "baidu", "name": "百度", "type": "company", "importance": 8}},
        {{"id": "cv", "name": "计算机视觉", "type": "tech", "importance": 7}}
    ],
    "edges": [
        {{"source": "baidu", "target": "ai", "relation": "布局"}},
        {{"source": "cv", "target": "ai", "relation": "属于"}},
        {{"source": "baidu", "target": "cv", "relation": "研发"}}
    ]
}}
```

注意：
- importance范围1-10，表示节点重要性
- 核心概念(core)的importance最高
- 提取5-15个最重要的实体
- 关系要简洁，2-4个字"""

    # 图表生成 Prompt
    CHART_GENERATION_PROMPT = """你是数据可视化专家，擅长生成ECharts图表配置。

## 研究主题
{query}

## 可用数据
{data}

## 任务
根据数据生成合适的ECharts图表配置，选择最能展示数据特点的图表类型。

## 图表类型选择规则
- 时间序列数据 → line (折线图)
- 分类比较数据 → bar (柱状图)
- 占比分布数据 → pie (饼图)
- 进度/百分比 → horizontal_bar (横向进度条)
- 多维对比 → radar (雷达图)

## 设计要求
1. 配色使用简约专业色系：
   - 主色：#1677ff (蓝)
   - 辅助色：#52c41a (绿), #722ed1 (紫), #fa8c16 (橙), #eb2f96 (粉)
2. 标题简洁明了
3. 不要过多装饰，保持简约

## 输出要求
请输出JSON格式：
```json
{{
    "charts": [
        {{
            "id": "chart_001",
            "title": "合同风险数量",
            "subtitle": "按风险类别统计",
            "type": "line",
            "echarts_option": {{
                "grid": {{"left": "3%", "right": "4%", "bottom": "3%", "containLabel": true}},
                "xAxis": {{
                    "type": "category",
                    "data": ["2020", "2021", "2022", "2023", "2024"],
                    "axisLine": {{"lineStyle": {{"color": "#e8e8e8"}}}},
                    "axisLabel": {{"color": "#666"}}
                }},
                "yAxis": {{
                    "type": "value",
                    "axisLine": {{"show": false}},
                    "splitLine": {{"lineStyle": {{"color": "#f0f0f0"}}}}
                }},
                "series": [{{
                    "type": "line",
                    "data": [3200, 4100, 5200, 6800, 8500],
                    "smooth": true,
                    "symbol": "circle",
                    "symbolSize": 8,
                    "itemStyle": {{"color": "#1677ff"}},
                    "lineStyle": {{"width": 3}},
                    "areaStyle": {{"color": {{"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": [{{"offset": 0, "color": "rgba(22,119,255,0.2)"}}, {{"offset": 1, "color": "rgba(22,119,255,0)"}}]}}}}
                }}]
            }}
        }},
        {{
            "id": "chart_002",
            "title": "风险类别占比",
            "subtitle": "2024年各技术领域占比",
            "type": "horizontal_bar",
            "echarts_option": {{
                "grid": {{"left": "25%", "right": "15%", "top": "5%", "bottom": "5%"}},
                "xAxis": {{"type": "value", "show": false, "max": 100}},
                "yAxis": {{
                    "type": "category",
                    "data": ["计算机视觉", "自然语言处理", "机器学习平台", "智能语音", "其他"],
                    "axisLine": {{"show": false}},
                    "axisTick": {{"show": false}},
                    "axisLabel": {{"color": "#333", "fontSize": 13}}
                }},
                "series": [{{
                    "type": "bar",
                    "data": [
                        {{"value": 32, "itemStyle": {{"color": "#1677ff"}}}},
                        {{"value": 28, "itemStyle": {{"color": "#722ed1"}}}},
                        {{"value": 24, "itemStyle": {{"color": "#1677ff"}}}},
                        {{"value": 10, "itemStyle": {{"color": "#52c41a"}}}},
                        {{"value": 6, "itemStyle": {{"color": "#fa8c16"}}}}
                    ],
                    "barWidth": 12,
                    "label": {{
                        "show": true,
                        "position": "right",
                        "formatter": "{{c}}%",
                        "color": "#666"
                    }},
                    "backgroundStyle": {{"color": "#f5f5f5"}},
                    "showBackground": true
                }}]
            }}
        }}
    ]
}}
```"""

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__(
            name="DataAnalyst",
            role="数据分析师",
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            model=model
        )

    async def process(self, state: ResearchState) -> ResearchState:
        """处理入口"""
        if state["phase"] == ResearchPhase.ANALYZING.value:
            return await self._analyze_data(state)
        return state

    async def _analyze_data(self, state: ResearchState) -> ResearchState:
        """执行法律风险分析"""
        ensure_legal_state_defaults(state)
        self.logger.info("Starting legal risk analysis...")

        self.add_message(state, "research_step", {
            "step_id": f"step_analyze_{uuid.uuid4().hex[:8]}",
            "step_type": "analyzing",
            "title": "法律风险分析",
            "subtitle": "识别风险、义务和整改事项",
            "status": "running",
            "stats": {"results_count": 0, "charts_count": 0, "entities_count": 0}
        })

        analysis = await self._analyze_legal_risks(state)

        risk_items = analysis.get("risk_items", []) or []
        if not risk_items:
            risk_items = [self._build_evidence_gap_risk(state)]

        scored_risks = []
        for index, risk in enumerate(risk_items, start=1):
            risk.setdefault("risk_id", f"risk_{index:03d}")
            scored = RiskScoringService.score_risk(risk)
            scored_risks.append(scored)
            if scored.get("risk_level") == "重大风险" or scored.get("human_review_required"):
                state["human_review_required"] = True
                reason = f"{scored.get('title', scored.get('risk_id'))} 需要人工复核。"
                if reason not in state["human_review_reasons"]:
                    state["human_review_reasons"].append(reason)

        state["risk_items"] = scored_risks
        state["risk_scores"] = [
            {
                "risk_id": risk.get("risk_id"),
                "overall_score": risk.get("overall_score"),
                "risk_level": risk.get("risk_level"),
            }
            for risk in scored_risks
        ]
        self._extend_unique_items(state["obligations"], analysis.get("obligations", []) or [], ("title", "description"))
        self._extend_unique_items(state["deadlines"], analysis.get("deadlines", []) or [], ("title", "date"))
        self._extend_unique_items(state["remediation_tasks"], analysis.get("remediation_tasks", []) or [], ("risk_id", "description"))
        for insight in analysis.get("insights", []) or []:
            if insight not in state["insights"]:
                state["insights"].append(insight)

        charts = [
            build_risk_distribution_chart(scored_risks),
            build_risk_matrix_chart(scored_risks),
            build_obligation_deadline_chart(state.get("obligations", []), state.get("deadlines", [])),
        ]
        state["charts"] = self._upsert_charts(state.get("charts", []), charts)

        knowledge_graph = build_legal_knowledge_graph(state)
        state["knowledge_graph"] = knowledge_graph

        self.add_message(state, "knowledge_graph", {
            "graph": knowledge_graph,
            "stats": {
                "entities_count": len(knowledge_graph.get("nodes", [])),
                "relations_count": len(knowledge_graph.get("edges", []))
            }
        })
        self.add_message(state, "charts", {"charts": charts})

        self.add_message(state, "research_step", {
            "step_type": "analyzing",
            "title": "法律风险分析",
            "subtitle": "识别风险、义务和整改事项",
            "status": "completed",
            "stats": {
                "risk_count": len(scored_risks),
                "charts_count": len(charts),
                "entities_count": len(knowledge_graph.get("nodes", []))
            }
        })

        return state

    def _upsert_charts(self, existing_charts: List[Dict[str, Any]], new_charts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        new_ids = {chart.get("id") for chart in new_charts if chart.get("id")}
        preserved = [chart for chart in existing_charts if chart.get("id") not in new_ids]
        return preserved + new_charts

    def _extend_unique_items(
        self,
        existing_items: List[Dict[str, Any]],
        new_items: List[Dict[str, Any]],
        key_fields: tuple
    ) -> None:
        existing_keys = {
            tuple((item.get(field) or "") for field in key_fields)
            for item in existing_items
        }
        for item in new_items:
            key = tuple((item.get(field) or "") for field in key_fields)
            if key in existing_keys:
                continue
            existing_keys.add(key)
            existing_items.append(item)

    async def _analyze_legal_risks(self, state: ResearchState) -> Dict[str, Any]:
        """Use the LLM to identify legal risks, with deterministic fallback."""
        has_material = any([
            state.get("legal_sources"),
            state.get("evidence_chain"),
            state.get("contract_clauses"),
            state.get("facts"),
        ])
        if not has_material:
            return {}

        try:
            response = await self.call_llm(
                system_prompt=LEGAL_SYSTEM_RULES,
                user_prompt=LEGAL_RISK_ANALYST_PROMPT.format(
                    query=state.get("query", ""),
                    legal_sources=str(state.get("legal_sources", [])[:20]),
                    evidence_chain=str(state.get("evidence_chain", [])[:30]),
                    contract_clauses=str(state.get("contract_clauses", [])[:20]),
                    facts=str(state.get("facts", [])[:20]),
                ),
                json_mode=True,
                temperature=0.2,
                max_tokens=8000
            )
            result = self.parse_json_response(response)
            if result:
                return result
        except Exception as exc:
            self.logger.warning(f"Legal risk analysis LLM failed, using fallback: {exc}")
        return self._fallback_legal_risk_analysis(state)

    def _fallback_legal_risk_analysis(self, state: ResearchState) -> Dict[str, Any]:
        """Create evidence-linked legal risks from available materials without an LLM."""
        evidence_ids = [item.get("evidence_id") for item in state.get("evidence_chain", []) if item.get("evidence_id")]
        basis_ids = [
            item.get("source_id")
            for item in state.get("legal_sources", [])
            if item.get("source_id") and item.get("source_type") in {"law", "regulation", "judicial_interpretation", "regulator_guidance"}
        ]
        evidence_link = evidence_ids[:5]
        basis_link = basis_ids[:5]
        text = "\n".join([
            state.get("query", ""),
            "\n".join(str(source.get("quoted_text") or source.get("snippet") or source.get("title", "")) for source in state.get("legal_sources", [])),
            "\n".join(str(evidence.get("quote", "")) for evidence in state.get("evidence_chain", [])),
            "\n".join(str(clause.get("text", "")) for clause in state.get("contract_clauses", [])),
        ])

        risks: List[Dict[str, Any]] = []

        def add_risk(
            title: str,
            subtype: str,
            description: str,
            action: str,
            impact: float = 4,
            probability: float = 3.5,
            urgency: float = 3.5,
        ) -> None:
            if any(risk.get("title") == title for risk in risks):
                return
            risks.append({
                "risk_id": f"risk_{len(risks) + 1:03d}",
                "title": title,
                "risk_category": "contract_clause",
                "risk_subtype": subtype,
                "description": description,
                "impact_score": impact,
                "probability_score": probability,
                "legal_certainty_score": 3.5 if basis_link else 2.5,
                "evidence_strength_score": 3.5 if evidence_link else 2.0,
                "urgency_score": urgency,
                "remediation_difficulty_score": 2.5,
                "legal_basis_ids": basis_link,
                "evidence_ids": evidence_link,
                "recommended_action": action,
                "human_review_required": False,
            })

        if any(term in text for term in ["逾期交付", "迟延交付", "延迟交付", "逾期", "交付"]):
            add_risk(
                "逾期交付救济不足风险",
                "delivery_delay_remedy",
                "材料显示合同关注逾期交付安排；若买方救济仅限退还货款，可能不足以覆盖停工、替代采购、价差、客户索赔等实际损失。",
                "补充明确逾期交付违约金、损失赔偿、替代采购价差、催告和解除权触发条件。",
                impact=4.2,
                probability=3.8,
                urgency=4.0,
            )
        if "违约金" in text and any(term in text for term in ["没有违约金", "未约定违约金", "不承担违约金", "无违约金"]):
            add_risk(
                "违约金约定缺失或排除风险",
                "liquidated_damages_gap",
                "材料出现未约定或排除违约金的信号，可能削弱守约方对迟延履行的约束和损失预补偿能力。",
                "约定按逾期天数、合同价款比例或实际损失孰高/合理区间计算的违约金，并保留调整和追加赔偿机制。",
                impact=4.0,
                probability=3.6,
                urgency=3.6,
            )
        if any(term in text for term in ["损失赔偿", "赔偿"]) and any(term in text for term in ["不承担", "没有", "仅需退还", "仅退还"]):
            add_risk(
                "损失赔偿被不当限制风险",
                "damage_compensation_limitation",
                "若条款将违约后果限制为退款或排除损失赔偿，可能导致买方无法覆盖直接损失、扩大损失和第三方索赔。",
                "增加直接损失、合理维权费用、替代采购价差、第三方索赔等赔偿范围，并设置责任限制的例外情形。",
                impact=4.3,
                probability=3.5,
                urgency=3.8,
            )
        if "解除" in text and any(term in text for term in ["没有解除权", "未约定解除", "无解除权"]):
            add_risk(
                "合同解除权缺失风险",
                "termination_right_gap",
                "逾期交付场景下若未明确解除权，买方可能在重大迟延时仍难以及时退出交易或另行采购。",
                "约定逾期达到一定天数、催告后仍未履行、影响项目节点等情形下的单方解除权和退款/赔偿安排。",
                impact=4.0,
                probability=3.4,
                urgency=3.5,
            )
        if any(term in text for term in ["仅需退还货款", "仅退还货款", "仅退款"]):
            add_risk(
                "单一退款救济导致责任失衡风险",
                "sole_refund_remedy",
                "仅退款救济可能使违约方责任低于违约造成的商业后果，并将履约失败风险转嫁给买方。",
                "将退款与违约金、损失赔偿、解除权、替代采购和继续履行等救济并列，避免排他性救济。",
                impact=4.1,
                probability=3.7,
                urgency=3.7,
            )

        if not risks and evidence_link:
            add_risk(
                "法律依据与合同事实匹配待核验风险",
                "evidence_mapping_review",
                "已取得证据片段，但风险类型需结合完整合同、履约背景和交易目的进一步确认。",
                "补充完整合同、往来函件、交付计划和损失资料，由法务或律师复核。",
                impact=3.2,
                probability=3.0,
                urgency=3.0,
            )

        remediation_tasks = [
            {
                "task_id": f"rem_{index:03d}",
                "description": risk.get("recommended_action", ""),
                "priority": "high" if risk.get("impact_score", 0) >= 4 else "medium",
                "risk_id": risk.get("risk_id"),
            }
            for index, risk in enumerate(risks, start=1)
        ]

        return {
            "risk_items": risks,
            "obligations": [],
            "deadlines": [],
            "remediation_tasks": remediation_tasks,
            "insights": [
                "已基于证据链识别合同救济不足、违约责任限制和解除权安排等核心法律风控问题。"
            ] if risks else [],
        }

    def _build_evidence_gap_risk(self, state: ResearchState) -> Dict[str, Any]:
        """Create a conservative risk item when evidence is insufficient."""
        state["human_review_required"] = True
        reason = "证据链或法律依据不足，需人工复核。"
        if reason not in state["human_review_reasons"]:
            state["human_review_reasons"].append(reason)
        return {
            "risk_id": "risk_001",
            "title": "证据链不足风险",
            "risk_category": "compliance_obligation",
            "risk_subtype": "insufficient_evidence",
            "description": "当前检索资料或已解析文本不足，无法形成确定性法律结论。",
            "impact_score": 4,
            "probability_score": 3,
            "legal_certainty_score": 2,
            "evidence_strength_score": 1,
            "urgency_score": 3,
            "remediation_difficulty_score": 2,
            "legal_basis_ids": [],
            "evidence_ids": [],
            "recommended_action": "补充完整合同、案件材料、监管文件或企业记录，并由律师/法务进行复核。",
            "human_review_required": True,
        }

    async def _extract_data(self, state: ResearchState) -> Dict[str, Any]:
        """从搜索结果中提取结构化数据"""
        self.logger.info("Extracting structured data...")

        # 收集搜索结果
        search_results_text = []
        for fact in state.get("facts", [])[:20]:
            search_results_text.append(f"- {fact.get('content', '')} (来源: {fact.get('source_name', '未知')})")

        if not search_results_text:
            self.logger.info("No facts to extract data from")
            return {"data_points": [], "time_series": [], "distributions": [], "insights": []}

        prompt = self.DATA_EXTRACTION_PROMPT.format(
            query=state["query"],
            search_results="\n".join(search_results_text)
        )

        response = await self.call_llm(
            system_prompt="你是专业的数据分析师，擅长从文本中提取结构化数据。请输出JSON格式。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.2
        )

        result = self.parse_json_response(response)

        # 更新数据点到状态
        if result.get("data_points"):
            for dp in result["data_points"]:
                state["data_points"].append(dp)

        # 更新洞察
        if result.get("insights"):
            state["insights"].extend(result["insights"])

        self.logger.info(f"Extracted {len(result.get('data_points', []))} data points, {len(result.get('time_series', []))} time series")

        return result

    async def _build_knowledge_graph(self, state: ResearchState) -> Dict[str, Any]:
        """构建知识图谱"""
        self.logger.info("Building knowledge graph...")

        # 收集内容
        content_parts = []
        for fact in state.get("facts", [])[:15]:
            content_parts.append(fact.get("content", ""))

        if not content_parts:
            self.logger.info("No content for knowledge graph")
            return {"nodes": [], "edges": []}

        prompt = self.KNOWLEDGE_GRAPH_PROMPT.format(
            query=state["query"],
            content="\n".join(content_parts)
        )

        response = await self.call_llm(
            system_prompt="你是知识图谱专家，擅长从文本中提取实体和关系。请输出JSON格式。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.2
        )

        result = self.parse_json_response(response)

        # 添加节点大小（基于importance）
        if result.get("nodes"):
            for node in result["nodes"]:
                importance = node.get("importance", 5)
                node["size"] = 20 + importance * 3  # 20-50 range

        self.logger.info(f"Built knowledge graph with {len(result.get('nodes', []))} nodes, {len(result.get('edges', []))} edges")

        return result

    async def _generate_charts(self, state: ResearchState, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成可视化图表"""
        self.logger.info("[DataAnalyst] ========== 开始生成 ECharts 可视化图表 ==========")

        # 准备数据
        data_for_charts = {
            "data_points": extracted_data.get("data_points", []),
            "time_series": extracted_data.get("time_series", []),
            "distributions": extracted_data.get("distributions", []),
            "existing_data_points": state.get("data_points", [])[:10]
        }

        # 如果没有足够数据，跳过
        total_data = (len(data_for_charts["data_points"]) +
                     len(data_for_charts["time_series"]) +
                     len(data_for_charts["distributions"]))

        self.logger.info(f"[DataAnalyst] 图表数据统计: data_points={len(data_for_charts['data_points'])}, time_series={len(data_for_charts['time_series'])}, distributions={len(data_for_charts['distributions'])}, total={total_data}")

        if total_data == 0:
            self.logger.warning("[DataAnalyst] ⚠️ 没有足够数据生成图表，跳过")
            return []

        prompt = self.CHART_GENERATION_PROMPT.format(
            query=state["query"],
            data=str(data_for_charts)
        )

        response = await self.call_llm(
            system_prompt="你是数据可视化专家，擅长生成ECharts图表配置。请输出JSON格式。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.3
        )

        result = self.parse_json_response(response)
        charts = result.get("charts", [])

        # 为每个图表添加唯一ID
        for chart in charts:
            if not chart.get("id"):
                chart["id"] = f"chart_{uuid.uuid4().hex[:8]}"

        self.logger.info(f"Generated {len(charts)} charts")

        return charts

    async def analyze_for_section(self, state: ResearchState, section_title: str) -> Dict[str, Any]:
        """为特定章节分析数据（可被其他Agent调用）"""
        self.logger.info(f"Analyzing data for section: {section_title}")

        # 收集与该章节相关的事实
        related_facts = [f for f in state.get("facts", [])
                        if section_title in str(f.get("related_sections", []))]

        if not related_facts:
            related_facts = state.get("facts", [])[:10]

        # 简化的数据提取
        search_results_text = [f"- {f.get('content', '')}" for f in related_facts]

        prompt = f"""分析以下内容，提取与"{section_title}"相关的关键数据：

{chr(10).join(search_results_text)}

输出JSON格式：
{{
    "key_metrics": [
        {{"name": "指标名", "value": "值", "unit": "单位"}}
    ],
    "trend": "上升/下降/稳定",
    "summary": "一句话总结"
}}"""

        response = await self.call_llm(
            system_prompt="你是数据分析师，提取关键数据。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.2
        )

        return self.parse_json_response(response)


LegalRiskAnalyst = DataAnalyst
