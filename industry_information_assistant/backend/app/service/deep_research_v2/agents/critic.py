# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
DeepResearch V2.0 - 毒舌评论家 Agent (CriticMaster)

职责：
1. 对抗式质检 - 永远不满意，找出问题
2. 逻辑漏洞检测 - 检查推理链条
3. 幻觉查杀 - 识别无来源或错误的信息
4. 偏见识别 - 发现观点偏颇
"""

import uuid
from typing import Dict, Any, List
from datetime import datetime

from .base import BaseAgent
from ..state import ResearchState, ResearchPhase, ensure_legal_state_defaults

try:
    from app.service.citation_verifier_service import CitationVerifierService
except ImportError:
    from service.citation_verifier_service import CitationVerifierService


def normalize_critic_verdict(verdict: str) -> str:
    if verdict in {"approved", "pass", "completed"}:
        return "approved"
    if verdict in {"needs_research", "re_researching", "research"}:
        return "needs_research"
    if verdict in {"needs_revision", "revising", "revise"}:
        return "needs_revision"
    if verdict == "human_review_required":
        return "human_review_required"
    return "needs_revision"


class CriticMaster(BaseAgent):
    """
    毒舌评论家 - 质量守门人

    特点：
    - 对抗式思维：假设一切都有问题
    - 严格的证据要求
    - 逻辑一致性检查
    - 有权打回重写
    """

    REVIEW_PROMPT = """你是一位极其严苛的法律风控质量审核专家。你的任务是找出法律风控报告中的所有问题。

## 审核原则（必须严格执行）
	1. **零容忍幻觉**：不得伪造法条、案号、处罚文书号、合同条款或来源
	2. **证据闭环**：重大/高风险结论必须绑定 evidence_ids 或 legal_basis_ids
	3. **法域一致**：必须识别主要法域，不能跨法域混用规则
	4. **有效性提示**：法规、案例、处罚、合同依据的有效性或真实性未知时必须标记
	5. **边界完整**：必须包含免责声明、缺失事实、待核验事项和人工复核提示

## 研究问题
{query}

## 研究大纲
{outline}

## 待审核内容

### 章节草稿
{draft_content}

### 引用的事实
{facts}

### 使用的数据点
{data_points}

## 任务
	逐条审核上述内容，找出所有法域、依据、证据链、风险评分、免责声明和人工复核问题。

## 输出格式
```json
{{
    "overall_assessment": {{
        "quality_score": 1-10,
        "verdict": "pass/needs_revision/major_issues",
        "summary": "整体评估摘要"
    }},
    "issues": [
        {{
            "id": "issue_1",
            "target_section": "章节ID或'全局'",
            "issue_type": "missing_source/logic_error/bias/hallucination/outdated/incomplete",
            "severity": "critical/major/minor",
            "location": "具体位置描述",
            "description": "问题详细描述",
            "evidence": "为什么这是问题的证据",
            "suggestion": "具体的修改建议",
            "requires_new_search": true或false,
            "search_query": "如果需要补充搜索，建议的关键词"
        }}
    ],
	    "citation_check_results": [
        {{
            "fact_id": "事实ID",
            "status": "verified/unverified/suspicious/false",
            "reason": "判断理由"
        }}
    ],
    "missing_aspects": ["报告中遗漏的重要方面"],
    "strength_points": ["报告中做得好的地方"]
}}
```

## 严重程度说明
	- critical: 必须修复，否则报告不可用（如：无证据重大结论、缺免责声明、严重幻觉）
	- major: 强烈建议修复，影响报告质量（如：缺少来源、法域不明、逻辑漏洞）
- minor: 建议修复，提升报告质量（如：表述不够精确）

## 评分标准（1-10分制）
- 9-10分：优秀，几乎无问题，可直接发布
- 7-8分：良好，有小问题但不影响整体质量，审核通过（verdict=pass）
- 5-6分：一般，有明显问题需要修订
- 3-4分：较差，问题较多，需要大幅修改
- 1-2分：很差，存在严重问题或大量错误

注意：quality_score >= 7 时才能设置 verdict 为 "pass"

开始你的审核："""

    FINAL_CHECK_PROMPT = """你是最终质量把关人。这是修订后的研究报告。

## 原始问题
{query}

## 之前的问题
{previous_issues}

## 修订后的内容
{revised_content}

## 任务
检查之前的问题是否已解决，是否有新问题产生。

输出JSON：
```json
{{
    "resolved_issues": ["已解决的问题ID列表"],
    "unresolved_issues": ["未解决的问题ID列表"],
    "new_issues": [{{
        "description": "新发现的问题",
        "severity": "critical/major/minor"
    }}],
    "final_verdict": "approved/needs_more_work",
    "final_score": 1-10,
    "publication_readiness": "ready/almost_ready/not_ready",
    "final_comments": "最终评语"
}}
```"""

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__(
            name="CriticMaster",
            role="毒舌评论家",
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            model=model
        )

    async def process(self, state: ResearchState) -> ResearchState:
        """法律质量审查入口"""
        ensure_legal_state_defaults(state)
        self.logger.info("[CriticMaster] ========== legal review process start ==========")
        self.logger.info(f"[CriticMaster] phase: {state['phase']}, final_report 长度: {len(state.get('final_report', ''))}")

        if state["phase"] != ResearchPhase.REVIEWING.value:
            self.logger.info(f"[CriticMaster] phase 不是 REVIEWING，跳过")
            return state

        self.add_message(state, "thought", {
            "agent": self.name,
            "content": "开始法律质量审查：检查法域、证据链、风险评分、免责声明和人工复核事项..."
        })

        state["citation_checks"] = CitationVerifierService.verify_risk_items(state)
        issues = self._run_legal_quality_checks(state)

        for issue in issues:
            issue.setdefault("id", f"issue_{uuid.uuid4().hex[:8]}")
            issue["resolved"] = False
            state["critic_feedback"].append(issue)

        critical_count = len([i for i in issues if i.get("severity") == "critical"])
        major_count = len([i for i in issues if i.get("severity") == "major"])
        state["unresolved_issues"] = critical_count + major_count
        state["quality_score"] = max(1.0, round(10.0 - critical_count * 2.0 - major_count * 1.2 - (len(issues) - critical_count - major_count) * 0.5, 1))

        verdict = self._decide_legal_verdict(state, issues)
        normalized_verdict = normalize_critic_verdict(verdict)
        self.add_message(state, "review", {
            "agent": self.name,
            "verdict": normalized_verdict,
            "quality_score": state["quality_score"],
            "issues_count": len(issues),
            "critical_issues": critical_count,
            "major_issues": major_count,
            "summary": "法律质量审查完成",
            "missing_aspects": [i.get("description", "") for i in issues if i.get("issue_type") == "incomplete"],
            "citation_checks": state.get("citation_checks", []),
            "human_review_required": state.get("human_review_required", False),
        })

        for issue in issues[:5]:
            self.add_message(state, "critic_feedback", {
                "agent": self.name,
                "issue_type": issue.get("issue_type"),
                "severity": issue.get("severity"),
                "description": issue.get("description"),
                "suggestion": issue.get("suggestion")
            })

        if normalized_verdict in {"approved", "human_review_required"}:
            state["phase"] = ResearchPhase.COMPLETED.value
        elif state["iteration"] >= state["max_iterations"]:
            state["phase"] = ResearchPhase.COMPLETED.value
            self.add_message(state, "warning", {
                "agent": self.name,
                "content": "已达最大迭代次数，部分法律问题可能仍需人工复核。"
            })
        elif normalized_verdict == "needs_research":
            state["phase"] = ResearchPhase.RE_RESEARCHING.value
            state["pending_search_queries"] = self._build_pending_search_queries(state, issues)
            state["iteration"] += 1
        else:
            state["phase"] = ResearchPhase.REVISING.value
            state["iteration"] += 1

        return state

    def _run_legal_quality_checks(self, state: ResearchState) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        report = state.get("final_report", "")

        if not state.get("jurisdiction", {}).get("primary"):
            issues.append(self._issue("missing_jurisdiction", "major", "未识别主要法域。", "补充法域识别并避免跨法域混用规则。", True))
        if "不构成正式法律意见" not in report:
            issues.append(self._issue("missing_disclaimer", "critical", "报告缺少“不构成正式法律意见”免责声明。", "在重要提示中补充强制免责声明。", False))
        if not state.get("legal_sources"):
            issues.append(self._issue("missing_source", "critical", "未形成任何法律来源。", "补充法规、案例、处罚、合同或企业记录检索。", True))
        if not state.get("risk_items"):
            issues.append(self._issue("incomplete", "major", "未识别法律风险项。", "补充风险识别和评分。", False))

        absolute_terms = ["必然胜诉", "一定违法", "绝对无效", "保证合规", "必然无责"]
        if any(term in report for term in absolute_terms):
            issues.append(self._issue("absolute_conclusion", "major", "报告存在绝对化法律结论。", "改为条件化、概率化表述，并标记需人工复核。", False))

        for risk in state.get("risk_items", []):
            if not isinstance(risk, dict):
                risk = {"risk_id": str(risk), "title": str(risk)}
            risk_level = risk.get("risk_level") or risk.get("severity", "")
            if risk_level in {"重大风险", "高风险"} and not (risk.get("evidence_ids") or risk.get("legal_basis_ids")):
                state["human_review_required"] = True
                issues.append(self._issue(
                    "missing_source",
                    "critical",
                    f"重大/高风险“{risk.get('title', risk.get('risk_id'))}”缺少 evidence_ids 或 legal_basis_ids。",
                    "为风险结论绑定证据链或法律依据；无法绑定时写明待核验。",
                    True
                ))
            if risk.get("overall_score") is None:
                issues.append(self._issue("missing_score", "major", f"风险“{risk.get('title', risk.get('risk_id'))}”缺少评分结果。", "使用 RiskScoringService 重新评分。", False))

        for check in state.get("citation_checks", []):
            if check.get("status") in {"missing", "weak"}:
                severity = "critical" if check.get("status") == "missing" else "major"
                issues.append(self._issue(
                    "citation_gap",
                    severity,
                    f"风险 {check.get('target_id')} 的证据链核验状态为 {check.get('status')}。",
                    "补齐 evidence_chain/legal_sources 中可追溯的 ID。",
                    check.get("status") == "missing"
                ))

        if any(item.get("type") == "unparsed_attachment" for item in state.get("missing_facts", []) if isinstance(item, dict)):
            state["human_review_required"] = True
            issues.append(self._issue("unparsed_attachment", "critical", "检测到 PDF/Word/图片附件占位，正文可能未解析。", "补充附件正文解析或进行人工审查。", False))

        high_risk_triggers = ["行政处罚", "刑事", "数据出境", "个人信息", "上市公司披露", "跨境"]
        if any(trigger in state.get("query", "") + report for trigger in high_risk_triggers):
            state["human_review_required"] = True
            reason = "涉及行政处罚、刑事、数据合规、上市公司披露或跨境事项，需人工复核。"
            if reason not in state["human_review_reasons"]:
                state["human_review_reasons"].append(reason)

        return issues

    def _issue(self, issue_type: str, severity: str, description: str, suggestion: str, requires_new_search: bool) -> Dict[str, Any]:
        return {
            "target_section": "全局",
            "issue_type": issue_type,
            "severity": severity,
            "location": "法律风控报告",
            "description": description,
            "evidence": description,
            "suggestion": suggestion,
            "requires_new_search": requires_new_search,
            "search_query": suggestion if requires_new_search else "",
        }

    def _decide_legal_verdict(self, state: ResearchState, issues: List[Dict[str, Any]]) -> str:
        if not issues:
            return "human_review_required" if state.get("human_review_required") else "approved"
        if any(issue.get("requires_new_search") for issue in issues):
            return "needs_research"
        if state.get("human_review_required") and state.get("quality_score", 0) >= 8:
            return "human_review_required"
        return "needs_revision"

    def _build_pending_search_queries(self, state: ResearchState, issues: List[Dict[str, Any]]) -> List[str]:
        queries = []
        for issue in issues:
            if issue.get("requires_new_search"):
                queries.append(issue.get("search_query") or issue.get("description", "法律依据 补充检索"))
        queries.extend(state.get("pending_search_queries", [])[:3])
        if not queries:
            queries.append(f"{state.get('query', '')} 法律依据 案例 处罚")
        return list(dict.fromkeys([q for q in queries if q]))[:5]

    def _analyze_issues_for_routing(self, review_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析问题类型，决定路由方向

        Returns:
            {
                "should_research": bool,  # 是否需要重新搜索
                "search_queries": List[str]  # 建议的搜索查询
            }
        """
        issues = review_result.get("issues", [])
        missing_aspects = review_result.get("missing_aspects", [])

        # 需要补充搜索的问题类型
        research_needed_types = {"missing_source", "incomplete", "outdated"}

        search_queries = []
        research_issues_count = 0

        for issue in issues:
            issue_type = issue.get("issue_type", "")
            severity = issue.get("severity", "minor")

            # 检查是否是需要搜索的问题类型
            if issue_type in research_needed_types and severity in ["critical", "major"]:
                research_issues_count += 1

                # 收集搜索建议
                if issue.get("requires_new_search") and issue.get("search_query"):
                    search_queries.append(issue["search_query"])

        # 添加遗漏方面的搜索查询
        for aspect in missing_aspects[:3]:
            search_queries.append(aspect)

        # 决策：如果有超过30%的严重问题需要搜索，或者有明确的搜索建议，则回到搜索阶段
        total_critical_major = len([i for i in issues if i.get("severity") in ["critical", "major"]])
        should_research = (
            len(search_queries) > 0 and
            (research_issues_count > 0 or len(missing_aspects) > 0) and
            (total_critical_major == 0 or research_issues_count / max(total_critical_major, 1) > 0.3)
        )

        return {
            "should_research": should_research,
            "search_queries": list(set(search_queries))[:5]  # 去重，最多5个查询
        }

    async def _review_content(self, state: ResearchState) -> Dict[str, Any]:
        """审核内容"""
        self.logger.info(f"[CriticMaster] _review_content 开始")

        # 准备草稿内容
        draft_content = ""
        for section_id, content in state["draft_sections"].items():
            section = next((s for s in state["outline"] if s.get("id") == section_id), {})
            draft_content += f"\n## {section.get('title', section_id)}\n{content}\n"

        if not draft_content:
            draft_content = state.get("final_report", "（暂无内容）")

        self.logger.info(f"[CriticMaster] 待审核内容长度: {len(draft_content)}")

        # 准备事实列表
        facts_summary = []
        for fact in state["facts"][:20]:
            facts_summary.append(f"- [{fact.get('id')}] {fact.get('content', '')[:150]} (来源: {fact.get('source_name')}, 可信度: {fact.get('credibility_score')})")

        # 准备数据点列表
        data_summary = []
        for dp in state["data_points"][:15]:
            data_summary.append(f"- {dp.get('name')}: {dp.get('value')} {dp.get('unit', '')} (来源: {dp.get('source')})")

        # 格式化大纲
        outline_summary = []
        for section in state["outline"]:
            outline_summary.append(f"- {section.get('id')}: {section.get('title')} ({section.get('status', 'pending')})")

        prompt = self.REVIEW_PROMPT.format(
            query=state["query"],
            outline="\n".join(outline_summary),
            draft_content=draft_content[:8000],  # 限制长度
            facts="\n".join(facts_summary) if facts_summary else "（暂无事实记录）",
            data_points="\n".join(data_summary) if data_summary else "（暂无数据点）"
        )

        self.logger.info(f"[CriticMaster] 调用 LLM 进行审核...")
        response = await self.call_llm(
	            system_prompt="你是一位极其严苛的法律风控质量审核专家，专门检查法域、依据、证据链、风险评分、免责声明和人工复核事项。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.2,
            max_tokens=16000  # 拉满到最大值
        )
        self.logger.info(f"[CriticMaster] LLM 响应长度: {len(response)}")

        result = self.parse_json_response(response)
        self.logger.info(f"[CriticMaster] JSON 解析结果: {bool(result)}, verdict: {result.get('overall_assessment', {}).get('verdict') if result else 'N/A'}")
        return result

    async def final_check(self, state: ResearchState) -> Dict[str, Any]:
        """最终检查"""
        # 收集之前的问题
        previous_issues = []
        for issue in state["critic_feedback"]:
            if not issue.get("resolved"):
                previous_issues.append(f"- [{issue.get('severity')}] {issue.get('description')}")

        prompt = self.FINAL_CHECK_PROMPT.format(
            query=state["query"],
            previous_issues="\n".join(previous_issues) if previous_issues else "无之前的问题",
            revised_content=state.get("final_report", "")[:8000]
        )

        response = await self.call_llm(
            system_prompt="你是最终质量把关人。",
            user_prompt=prompt,
            json_mode=True
        )

        return self.parse_json_response(response)


LegalCriticMaster = CriticMaster
