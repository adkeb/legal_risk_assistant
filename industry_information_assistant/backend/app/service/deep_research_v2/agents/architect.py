# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
DeepResearch V2.0 - 总架构师 Agent (ChiefArchitect)

职责：
1. 意图解码 - 深度理解用户问题
2. 知识图谱初始化 - 识别关键实体和关系
3. 动态大纲生成 - 创建可执行的研究计划
4. 进度监控 - 根据研究进展动态调整大纲
"""

import uuid
from typing import Dict, Any, List
from datetime import datetime

from .base import BaseAgent
from ..state import ResearchState, ResearchPhase, ensure_legal_state_defaults
from ..prompts.legal_prompts import LEGAL_SYSTEM_RULES, LEGAL_ARCHITECT_PROMPT


class ChiefArchitect(BaseAgent):
    """
    总架构师 - 研究规划的大脑

    特点：
    - 动态DAG调度
    - 大局观，能看到全貌
    - 根据新发现调整计划
    """

    PLANNING_PROMPT = """法律风控研究课题：{query}

请为该法律风控课题生成研究大纲和待验证法律问题，输出JSON格式如下：

{{
  "hypothesis_1": "关于合同条款或业务安排存在法律风险的假设（需要证据验证）",
  "hypothesis_2": "关于义务、期限、责任或救济安排不充分的假设（需要证据验证）",
  "hypothesis_3": "关于法规、案例、监管规则或内部制度适用的假设（需要证据验证）",
  "sec_1_title": "重要提示与免责声明",
  "sec_1_desc": "说明报告边界和人工复核要求",
  "sec_1_query": "不需要外部搜索",
  "sec_2_title": "事实、假设与分析范围",
  "sec_2_desc": "梳理用户提供事实、事实假设和缺失材料",
  "sec_2_query": "事实 假设 缺失材料",
  "sec_3_title": "适用法域与法律依据",
  "sec_3_desc": "检索适用法律、监管规则、案例和合同依据",
  "sec_3_query": "法律依据 案例 监管规则 合同条款",
  "sec_4_title": "风险识别与等级",
  "sec_4_desc": "识别法律风险、风险等级和评分依据",
  "sec_4_query": "法律风险 风险等级 整改建议",
  "sec_5_title": "逐项法律分析",
  "sec_5_desc": "逐项分析事实、依据、风险和结论",
  "sec_5_query": "法律分析 证据链",
  "sec_6_title": "义务清单与期限",
  "sec_6_desc": "提取义务、期限、触发条件和责任主体",
  "sec_6_query": "义务 期限 责任主体",
  "questions": "核心问题1;核心问题2;核心问题3"
}}

研究假设示例：
- 假设某合同条款存在救济不足风险，需要用法律依据和合同证据链验证
- 假设某履约期限、违约责任或解除权安排不足，需要找证据支持或反驳
- 假设某监管规则、司法案例或内部制度会影响风险判断，需要核验适用性

请根据研究课题填写具体内容，每个字段都是字符串类型。"""

    REVISION_PROMPT = """你是总架构师，需要根据研究进展动态调整大纲。

## 原始问题
{query}

## 当前大纲
{current_outline}

## 新发现的重要信息
{new_findings}

## 当前进度
- 已完成章节: {completed_sections}
- 收集的事实数量: {facts_count}
- 发现的数据点: {data_points_count}

## 任务
评估是否需要调整大纲。可能的调整包括：
1. 新增章节（发现了重要的新方向）
2. 删除章节（发现某方向信息太少）
3. 调整章节顺序或优先级
4. 细化或合并章节

输出JSON格式：
```json
{{
    "needs_revision": true或false,
    "revision_reason": "调整原因",
    "revised_outline": [...],  // 如果needs_revision为true
    "new_search_queries": ["新增的搜索关键词"]  // 如果需要补充搜索
}}
```"""

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__(
            name="ChiefArchitect",
            role="总架构师",
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            model=model
        )

    def _convert_flat_to_outline(self, flat_result: Dict) -> Dict:
        """将扁平JSON格式转换为标准outline格式"""
        outline = []
        for i in range(1, 10):  # 最多支持9个章节
            title_key = f"sec_{i}_title"
            desc_key = f"sec_{i}_desc"
            query_key = f"sec_{i}_query"

            if title_key not in flat_result:
                break

            section = {
                "id": f"sec_{i}",
                "title": flat_result.get(title_key, f"章节{i}"),
                "description": flat_result.get(desc_key, ""),
                "section_type": "mixed",
                "requires_data": i <= 2,  # 前两章需要数据
                "requires_chart": i <= 2,
                "search_queries": [flat_result.get(query_key, flat_result.get(title_key, ""))]
            }
            outline.append(section)

        # 处理研究问题
        questions_str = flat_result.get("questions", "")
        if isinstance(questions_str, str):
            research_questions = [q.strip() for q in questions_str.split(";") if q.strip()]
        else:
            research_questions = []

        # 处理研究假设（假设驱动研究）
        hypotheses = []
        for i in range(1, 6):  # 最多5个假设
            h_key = f"hypothesis_{i}"
            if h_key in flat_result and flat_result[h_key]:
                hypotheses.append({
                    "id": f"h_{i}",
                    "content": flat_result[h_key],
                    "status": "unverified",  # unverified, supported, refuted, partially_supported
                    "evidence_for": [],
                    "evidence_against": []
                })

        return {
            "outline": outline,
            "research_questions": research_questions,
            "hypotheses": hypotheses,
            "key_entities": []
        }

    def _build_default_legal_outline(self, search_queries: List[str] = None) -> List[Dict[str, Any]]:
        """Build a frontend-compatible legal report outline."""
        search_queries = search_queries or []
        sections = [
            ("sec_1", "重要提示与免责声明", "说明 AI 辅助分析边界和人工复核要求", "legal_notice", False, False),
            ("sec_2", "事实、假设与分析范围", "梳理已知事实、事实假设、缺失信息和分析范围", "facts", False, False),
            ("sec_3", "适用法域与法律依据", "识别法域并整理适用法律、监管规则、案例或合同依据", "legal_basis", False, False),
            ("sec_4", "风险识别与等级", "识别法律风险并给出风险等级、评分依据和优先级", "risk_summary", True, True),
            ("sec_5", "逐项法律分析", "围绕每个法律问题进行依据、事实和风险推理", "legal_analysis", False, False),
            ("sec_6", "义务清单与期限", "提取合规义务、合同义务、履行期限和触发条件", "obligations", True, True),
            ("sec_7", "整改建议", "给出可执行的风险缓释和整改建议", "remediation", False, False),
            ("sec_8", "证据链与引用清单", "列明法规、案例、合同条款、处罚或资料引用", "evidence", False, False),
            ("sec_9", "待人工复核事项", "列明需律师、法务或业务人员进一步确认的事项", "human_review", False, False),
        ]
        return [
            {
                "id": section_id,
                "title": title,
                "description": description,
                "section_type": section_type,
                "requires_data": requires_data,
                "requires_chart": requires_chart,
                "priority": index + 1,
                "search_queries": search_queries[:3] or [title],
                "status": "pending",
            }
            for index, (section_id, title, description, section_type, requires_data, requires_chart)
            in enumerate(sections)
        ]

    def _fallback_legal_plan(self, query: str) -> Dict[str, Any]:
        """Deterministic fallback when the LLM cannot produce a valid plan."""
        contract_terms = ["合同", "条款", "违约", "交付", "采购", "赔偿", "解除"]
        task_type = "contract_review" if any(term in query for term in contract_terms) else "general_legal_research"
        legal_domains = ["contract"] if task_type == "contract_review" else []
        legal_questions = [
            {"id": "q_001", "question": "用户问题涉及哪些事实、假设和缺失材料？", "priority": "high"},
            {"id": "q_002", "question": "应适用哪些法域、法律依据或合同依据？", "priority": "high"},
            {"id": "q_003", "question": "存在哪些法律风险、义务和整改事项？", "priority": "high"},
        ]
        pending_search_queries = [
            f"{query} 法律风险",
            f"{query} 法律依据",
            f"{query} 案例 行政处罚 合同条款",
        ]
        return {
            "task_type": task_type,
            "jurisdiction": {
                "primary": "中国大陆",
                "secondary": [],
                "cross_border": False,
                "confidence": 0.5,
                "missing_info": [],
            },
            "legal_domains": legal_domains,
            "parties": [],
            "legal_questions": legal_questions,
            "fact_assumptions": [
                {"id": "fa_001", "content": "分析仅基于用户当前输入和系统可检索资料。", "confidence": 0.5}
            ],
            "missing_facts": [
                {"type": "missing_materials", "description": "尚未确认完整合同、案件材料或企业背景资料。"}
            ],
            "pending_search_queries": pending_search_queries,
            "human_review_required": False,
            "human_review_reasons": [],
        }

    async def process(self, state: ResearchState) -> ResearchState:
        """
        处理入口

        根据当前阶段执行不同的规划任务
        """
        ensure_legal_state_defaults(state)
        if state["phase"] == ResearchPhase.INIT.value:
            return await self._initial_planning(state)
        elif state["phase"] == ResearchPhase.REVIEWING.value:
            return await self._check_revision(state)
        else:
            return state

    async def _initial_planning(self, state: ResearchState) -> ResearchState:
        """初始法律风控规划"""
        ensure_legal_state_defaults(state)
        query = state["query"]
        self.logger.info(f"Starting legal initial planning for: {query[:50]}...")

        self.add_message(state, "research_step", {
            "step_id": f"step_planning_{uuid.uuid4().hex[:8]}",
            "step_type": "planning",
            "title": "法律任务规划",
            "subtitle": "识别法域、问题和证据需求",
            "status": "running",
            "stats": {}
        })

        self.add_message(state, "thought", {
            "agent": self.name,
            "content": "正在拆解法律风控问题，识别法域、风险维度和证据需求..."
        })

        result = {}
        try:
            response = await self.call_llm(
                system_prompt=LEGAL_SYSTEM_RULES,
                user_prompt=LEGAL_ARCHITECT_PROMPT.format(query=query),
                json_mode=True,
                temperature=0.3,
                max_tokens=8000
            )
            result = self.parse_json_response(response)
        except Exception as exc:
            self.logger.warning(f"Legal planning LLM failed, using fallback: {exc}")

        if not result:
            result = self._fallback_legal_plan(query)

        pending_search_queries = result.get("pending_search_queries") or []
        state["task_type"] = result.get("task_type") or "general_legal_research"
        state["jurisdiction"] = result.get("jurisdiction") or state["jurisdiction"]
        state["legal_domains"] = result.get("legal_domains") or []
        state["parties"] = result.get("parties") or []
        state["legal_questions"] = result.get("legal_questions") or []
        state["fact_assumptions"] = result.get("fact_assumptions") or []
        state["missing_facts"] = result.get("missing_facts") or state.get("missing_facts", [])
        state["research_questions"] = [
            item.get("question", str(item)) if isinstance(item, dict) else str(item)
            for item in state["legal_questions"]
        ]
        state["pending_search_queries"] = pending_search_queries
        state["hypotheses"] = [
            {
                "id": item.get("id", f"fa_{index + 1:03d}"),
                "content": item.get("content", ""),
                "status": "unverified",
                "evidence_for": [],
                "evidence_against": [],
            }
            for index, item in enumerate(state.get("fact_assumptions", []))
            if isinstance(item, dict)
        ]
        state["key_entities"] = [
            party.get("name")
            for party in state.get("parties", [])
            if isinstance(party, dict) and party.get("name") and party.get("name") != "unknown"
        ]
        state["mind_map"] = {
            "center": query,
            "branches": ["事实与假设", "适用法域", "法律依据", "风险识别", "整改建议", "证据链"],
        }
        state["knowledge_graph"] = {"nodes": [], "edges": []}
        state["human_review_required"] = bool(result.get("human_review_required", False))
        state["human_review_reasons"] = result.get("human_review_reasons") or []

        state["outline"] = self._build_default_legal_outline(pending_search_queries)
        self.logger.info(f"Legal planning completed with {len(state['outline'])} sections")

        self.add_message(state, "outline", {
            "understanding": {
                "task_type": state["task_type"],
                "jurisdiction": state["jurisdiction"],
                "legal_domains": state["legal_domains"],
            },
            "key_entities": state["key_entities"],
            "outline": state["outline"],
            "research_questions": state["research_questions"],
            "legal_questions": state["legal_questions"],
            "missing_facts": state["missing_facts"],
        })

        state["phase"] = ResearchPhase.PLANNING.value

        self.add_message(state, "research_step", {
            "step_type": "planning",
            "title": "法律任务规划",
            "subtitle": "识别法域、问题和证据需求",
            "status": "completed",
            "stats": {
                "sections_count": len(state["outline"]),
                "questions_count": len(state["research_questions"]),
                "missing_facts_count": len(state.get("missing_facts", [])),
            }
        })

        return state

    async def _check_revision(self, state: ResearchState) -> ResearchState:
        """检查是否需要修订大纲"""
        # 收集新发现
        new_findings = []
        for fact in state["facts"][-10:]:  # 最近10条事实
            new_findings.append(f"- {fact.get('content', '')[:100]}")

        if not new_findings:
            return state

        # 统计进度
        completed = [s for s in state["outline"] if s.get("status") == "final"]

        prompt = self.REVISION_PROMPT.format(
            query=state["query"],
            current_outline=state["outline"],
            new_findings="\n".join(new_findings),
            completed_sections=len(completed),
            facts_count=len(state["facts"]),
            data_points_count=len(state["data_points"])
        )

        response = await self.call_llm(
            system_prompt="你是总架构师，需要判断是否需要调整研究计划。",
            user_prompt=prompt,
            json_mode=True
        )

        result = self.parse_json_response(response)

        if result.get("needs_revision") and result.get("revised_outline"):
            state["outline"] = result["revised_outline"]
            self.add_message(state, "outline_revision", {
                "reason": result.get("revision_reason"),
                "new_outline": result["revised_outline"]
            })
            self.logger.info(f"Outline revised: {result.get('revision_reason')}")

        return state


LegalArchitect = ChiefArchitect
