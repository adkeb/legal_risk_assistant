# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
DeepResearch V2.0 - 首席笔杆 Agent (LeadWriter)

职责：
1. 深度写作 - 将零散信息串联成逻辑严密的报告
2. Markdown排版 - 专业的格式排版
3. 图文混排 - 整合文字、图表、数据
4. 参考文献 - 规范的引用格式
"""

import uuid
from typing import Dict, Any, List
from datetime import datetime

from .base import BaseAgent
from ..state import ResearchState, ResearchPhase, ensure_legal_state_defaults

try:
    from app.config.legal_risk_config import LEGAL_DEFAULT_DISCLAIMER
except ImportError:
    from config.legal_risk_config import LEGAL_DEFAULT_DISCLAIMER


def build_legal_report_skeleton(state: Dict[str, Any]) -> str:
    """Build a deterministic legal risk report skeleton."""
    disclaimer = (state.get("disclaimers") or [LEGAL_DEFAULT_DISCLAIMER])[0]
    jurisdiction = state.get("jurisdiction", {})
    if not isinstance(jurisdiction, dict):
        jurisdiction = {"primary": str(jurisdiction)}
    risk_items = state.get("risk_items", [])
    legal_sources = state.get("legal_sources", [])
    evidence_chain = state.get("evidence_chain", [])
    obligations = state.get("obligations", [])
    deadlines = state.get("deadlines", [])
    remediation_tasks = state.get("remediation_tasks", [])
    missing_facts = state.get("missing_facts", [])
    human_review_reasons = state.get("human_review_reasons", [])

    def item_dict(item: Any, fallback_key: str = "description") -> Dict[str, Any]:
        if isinstance(item, dict):
            return item
        return {fallback_key: str(item)}

    def get_value(item: Any, key: str, default: Any = "") -> Any:
        return item.get(key, default) if isinstance(item, dict) else default

    def string_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            items = value
        else:
            items = [value]
        rendered: List[str] = []
        for item in items:
            if isinstance(item, dict):
                rendered.append(str(item.get("id") or item.get("source_id") or item.get("evidence_id") or item.get("title") or item))
            elif item:
                rendered.append(str(item))
        return [item for item in rendered if item]

    def safe_join(value: Any, fallback: str) -> str:
        rendered = string_list(value)
        return ", ".join(rendered) if rendered else fallback

    def lines(items: List[Any], formatter) -> str:
        rendered = []
        for index, item in enumerate(items or [], start=1):
            try:
                rendered.append(formatter(item_dict(item), index))
            except Exception:
                rendered.append(f"{index}. {str(item)}")
        return "\n".join(rendered) if rendered else "- 暂无可核验信息，需补充材料后复核。"

    risk_summary = lines(
        risk_items,
        lambda risk, index: (
            f"{index}. **{risk.get('title', '未命名风险')}**：{risk.get('risk_level', risk.get('severity', '中风险'))}，"
            f"评分 {risk.get('overall_score', '待核验')}。"
            f" 依据：{safe_join(risk.get('legal_basis_ids', []), '待核验')}；"
            f"证据：{safe_join(risk.get('evidence_ids', []), '需补充材料')}。"
        )
    )
    source_summary = lines(
        legal_sources,
        lambda source, index: (
            f"{index}. [{source.get('source_id', f'source_{index:03d}')}] "
            f"{source.get('title', '未命名来源')}（{source.get('source_type', 'unknown')}，"
            f"{source.get('validity_status', 'unknown')}）"
        )
    )
    evidence_summary = lines(
        evidence_chain,
        lambda evidence, index: (
            f"{index}. [{evidence.get('evidence_id', f'ev_{index:03d}')}] "
            f"{evidence.get('quote', '')[:160] or '待核验证据'}"
        )
    )
    obligation_summary = lines(
        obligations + deadlines,
        lambda item, index: f"{index}. {item.get('title') or item.get('description') or item.get('obligation', '待确认事项')}（期限：{item.get('deadline') or item.get('date') or '待确认'}）"
    )
    remediation_summary = lines(
        remediation_tasks or [
            {"description": get_value(risk, "recommended_action", "")}
            for risk in risk_items
            if get_value(risk, "recommended_action", "")
        ],
        lambda item, index: f"{index}. {item.get('description') or item.get('action') or '补充资料并进行人工复核。'}"
    )
    review_summary = lines(
        string_list(human_review_reasons) + [
            item.get("description", "") if isinstance(item, dict) else str(item)
            for item in missing_facts
        ],
        lambda item, index: f"{index}. {item.get('description') or '待人工复核事项'}"
    )

    return f"""# 法律风控分析报告

## 重要提示
{disclaimer}

## 一、执行摘要
本报告围绕“{state.get('query', '')}”进行法律风控辅助分析。当前结论基于用户输入、系统检索资料和已解析文本形成；缺少证据链的事项均按“待核验/需人工复核”处理。

## 二、分析范围、事实与假设
- 任务类型：{state.get('task_type', 'general_legal_research')}
- 主要法域：{jurisdiction.get('primary', '中国大陆')}
- 次要法域：{safe_join(jurisdiction.get('secondary', []), '无')}
- 缺失事实：{'; '.join(item.get('description', str(item)) if isinstance(item, dict) else str(item) for item in missing_facts) or '暂无'}

## 三、适用法域与法律依据
{source_summary}

## 四、风险识别与等级
{risk_summary}

## 五、逐项法律分析
{lines(risk_items, lambda risk, index: f"{index}. {risk.get('title', '风险')}：{risk.get('description', '待核验')} 建议：{risk.get('recommended_action', '需补充材料并人工复核。')}")}

## 六、义务清单与期限
{obligation_summary}

## 七、整改建议
{remediation_summary}

## 八、证据链与引用清单
{evidence_summary}

## 九、待人工复核事项
{review_summary}
"""


class LeadWriter(BaseAgent):
    """
    首席笔杆 - 最终输出的打磨者

    特点：
    - 深度写作能力
    - 专业的法律风控报告风格
    - 逻辑严密的叙述结构
    - 规范的引用和排版
    """

    SECTION_WRITING_PROMPT = """你是一位法律风控报告专家，擅长撰写法律风险分析报告。

## 研究主题
{query}

## 当前章节信息
标题: {section_title}
描述: {section_description}
类型: {section_type}

## 可用素材

### 相关事实
{facts}

### 数据点
{data_points}

### 已有洞察
{insights}

### 相关图表
{charts_info}

## 写作要求
	1. **专业性**：使用法律风控术语，区分事实、假设、依据、分析和建议
	2. **逻辑性**：风险结论必须说明事实基础、适用依据和推理边界
	3. **证据支撑**：关键观点必须有证据链、法律来源或明确标记“待核验”
	4. **引用规范**：使用可点击链接格式 [来源名称](URL)，如 [法规/案例/合同来源](URL)
5. **图表整合**：在合适位置插入图表引用 ![图表标题](chart_id)
6. **字数控制**：本章节 500-1000 字
7. **不要重复标题**：正文开头不要再写章节标题

## 输出格式
```json
{{
    "content": "章节正文内容（Markdown格式，不包含章节标题）",
    "key_points": ["本章节的核心要点"],
    "citations": [
        {{"source": "来源名称", "url": "完整URL"}}
    ],
    "suggested_improvements": ["如果有更多信息可以改进的地方"]
}}
```

## 写作风格示例
- 好的开头："根据已检索资料和证据链，本事项主要风险集中在合同履行和救济安排..."
	- 避免的开头："我们可以保证该条款一定有效..."
- 依据引用示例："该风险需结合相关条款和法规依据进一步核验（[来源名称](URL)）"

开始撰写："""

    SYNTHESIS_PROMPT = """你是法律风控报告主编，需要将各章节整合成完整的法律风控分析报告。

## 研究主题
{query}

## 各章节内容
{sections_content}

## 收集的所有引用来源
{all_sources}

    ## 任务
    1. 撰写法律风控执行摘要。
    2. 整合各章节，确保事实、假设、法律依据、风险分析和建议边界清楚。
    3. 对缺少证据链的结论标记“待核验”或“需人工复核”。
    4. 整理证据链与引用列表（确保链接可点击）。

## 关键要求

### 1. 标题编号规则（必须严格遵守）
    - 一级标题：1、2、3...（如：1 事实与假设）
- 二级标题：1.1、1.2、2.1...（如：1.1 风险等级）
	- 三级标题：1.1.1、1.1.2...（如：1.1.1 事实基础）
- **禁止标题重复**：每个标题必须唯一，不要在正文中重复章节标题

### 2. 引用格式规则（确保可点击）
	- 行内引用：使用 [来源名称](URL) 格式，如 [法规/案例/合同来源](URL)
- 依据引用：在结论后标注来源，如"该事项需补充核验（[来源名称](URL)）"
- 文末参考文献：使用有序列表 + 可点击链接格式

### 3. 报告结构规范
    - 必须包含“不构成正式法律意见”免责声明。
    - 必须包含事实与假设、适用法域、风险等级、整改建议、证据链和人工复核事项。
    - 各章节使用 ## 二级标题，子章节使用 ### 三级标题。

## 输出格式
```json
{{
    "executive_summary": "执行摘要（300-500字）",
    "full_report": "完整报告（Markdown格式，按下方结构生成）",
    "conclusions": ["核心结论1", "核心结论2"],
	    "outlook": "人工复核与后续整改建议",
    "references": [
        {{"id": 1, "title": "来源标题", "url": "完整URL", "author": "作者/机构", "date": "日期"}}
    ]
}}
```

## 报告结构模板
```markdown
## 执行摘要

[300-500字的研究摘要]

---

	## 1 重要提示

	本报告由 AI 辅助生成，仅供法律风控参考，不构成正式法律意见。

	### 1.1 事实与假设

	[内容，包含依据引用如：根据[来源名](URL)，...]

### 1.2 [子章节标题]

#### 1.2.1 [三级标题]

[更详细的内容]

---

## 2 [第二章标题]

### 2.1 [子章节标题]

...

---

	## 人工复核与后续整改

### 核心结论
1. [结论1]
2. [结论2]

	### 人工复核事项
	[复核内容]

---

## 参考文献

1. [来源标题1](URL1) - 作者/机构, 日期
2. [来源标题2](URL2) - 作者/机构, 日期
...
```"""

    REVISION_PROMPT = """你是首席笔杆，需要根据审核反馈修订报告。

## 原始报告
{original_content}

## 审核反馈
{feedback}

## 补充的新信息
{new_info}

## 任务
根据反馈修订报告，解决指出的问题。

## 修订原则
1. 针对性修改：只修改有问题的部分
2. 补充来源：对缺少来源的观点补充引用
3. 修正错误：纠正事实错误或逻辑漏洞
4. 保持风格：修订后保持报告整体风格一致

输出JSON：
```json
{{
    "revised_content": "修订后的内容",
    "changes_made": ["修改1", "修改2"],
    "addressed_issues": ["已解决的问题ID"],
    "unable_to_address": ["无法解决的问题及原因"]
}}
```"""

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__(
            name="LeadWriter",
            role="首席笔杆",
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            model=model
        )

    async def process(self, state: ResearchState) -> ResearchState:
        """处理入口"""
        if state["phase"] == ResearchPhase.WRITING.value:
            return await self._write_report(state)
        elif state["phase"] == ResearchPhase.REVISING.value:
            return await self._revise_report(state)
        else:
            return state

    async def _write_report(self, state: ResearchState) -> ResearchState:
        """撰写法律风控报告"""
        ensure_legal_state_defaults(state)
        state["outline"] = [self._normalize_section(section, index) for index, section in enumerate(state.get("outline", []), start=1)]
        self.add_message(state, "research_step", {
            "step_id": f"step_writing_{uuid.uuid4().hex[:8]}",
            "step_type": "writing",
            "title": "法律报告生成",
            "subtitle": "生成法律风控分析报告",
            "status": "running",
            "stats": {"sections_count": len(state["outline"]), "word_count": 0}
        })

        self.add_message(state, "thought", {
            "agent": self.name,
            "content": "开始生成法律风控报告，确保包含免责声明、风险等级、整改建议和证据链..."
        })

        full_report = build_legal_report_skeleton(state)
        state["final_report"] = full_report
        section_blocks = self._split_legal_report_sections(full_report)

        for section in state["outline"]:
            section_id = section.get("id")
            title = section.get("title", "")
            content = section_blocks.get(title, "")
            if not content:
                content = self._content_for_section_title(state, title)
            state["draft_sections"][section_id] = content
            section["status"] = "drafted"
            self.add_message(state, "section_content", {
                "agent": self.name,
                "section_id": section_id,
                "section_title": title,
                "content": content,
                "word_count": len(content),
                "key_points": []
            })

        state["references"] = [
            {
                "id": index,
                "title": source.get("title", f"来源 {index}"),
                "source": source.get("issuing_body") or source.get("source_type", "法律来源"),
                "url": source.get("url", ""),
                "source_id": source.get("source_id", ""),
            }
            for index, source in enumerate(state.get("legal_sources", []), start=1)
        ]

        self.add_message(state, "report_draft", {
            "agent": self.name,
            "content": state["final_report"],
            "executive_summary": "法律风控分析报告已生成，缺少证据的结论已标记待核验或需人工复核。",
            "conclusions": [risk.get("title", "") for risk in state.get("risk_items", [])[:5]],
            "word_count": len(state["final_report"]),
            "references_count": len(state["references"])
        })

        word_count = len(state.get("final_report", ""))
        self.add_message(state, "research_step", {
            "step_type": "writing",
            "title": "法律报告生成",
            "subtitle": "生成法律风控分析报告",
            "status": "completed",
            "stats": {
                "sections_count": len(state["outline"]),
                "word_count": word_count,
                "references_count": len(state.get("references", []))
            }
        })

        state["phase"] = ResearchPhase.REVIEWING.value

        return state

    def _split_legal_report_sections(self, report: str) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        current_title = ""
        current_lines: List[str] = []
        title_alias = {
            "重要提示": "重要提示与免责声明",
            "二、分析范围、事实与假设": "事实、假设与分析范围",
            "三、适用法域与法律依据": "适用法域与法律依据",
            "四、风险识别与等级": "风险识别与等级",
            "五、逐项法律分析": "逐项法律分析",
            "六、义务清单与期限": "义务清单与期限",
            "七、整改建议": "整改建议",
            "八、证据链与引用清单": "证据链与引用清单",
            "九、待人工复核事项": "待人工复核事项",
        }
        for line in report.splitlines():
            if line.startswith("## "):
                if current_title:
                    mapping[title_alias.get(current_title, current_title)] = "\n".join(current_lines).strip()
                current_title = line[3:].strip()
                current_lines = []
            elif current_title:
                current_lines.append(line)
        if current_title:
            mapping[title_alias.get(current_title, current_title)] = "\n".join(current_lines).strip()
        return mapping

    def _content_for_section_title(self, state: ResearchState, title: str) -> str:
        if "免责声明" in title or "重要提示" in title:
            return (state.get("disclaimers") or [LEGAL_DEFAULT_DISCLAIMER])[0]
        if "风险" in title:
            return "\n".join([
                f"- {self._get_item_value(risk, 'title', str(risk))}: {self._get_item_value(risk, 'risk_level', self._get_item_value(risk, 'severity', '中风险'))}"
                for risk in state.get("risk_items", [])
            ]) or "暂无可核验风险，需补充材料。"
        if "证据" in title or "引用" in title:
            return "\n".join([
                f"- {self._get_item_value(ev, 'evidence_id', '')}: {str(self._get_item_value(ev, 'quote', ev))[:120]}"
                for ev in state.get("evidence_chain", [])
            ]) or "暂无证据链，需人工复核。"
        return "待核验，需结合完整材料进行人工复核。"

    def _normalize_section(self, section: Any, index: int) -> Dict[str, Any]:
        if isinstance(section, dict):
            section.setdefault("id", f"section_{index}")
            section.setdefault("title", section.get("name") or f"第 {index} 节")
            return section
        return {
            "id": f"section_{index}",
            "title": str(section) or f"第 {index} 节",
            "description": "",
            "section_type": "legal_analysis",
            "status": "pending",
        }

    def _get_item_value(self, item: Any, key: str, default: Any = "") -> Any:
        return item.get(key, default) if isinstance(item, dict) else default

    async def _write_section(self, state: ResearchState, section: Dict) -> None:
        """撰写单个章节"""
        section_id = section["id"]
        self.logger.info(f"Writing section: {section.get('title')}")

        self.add_message(state, "action", {
            "agent": self.name,
            "tool": "writing_section",
            "section": section.get("title")
        })

        # 收集相关素材
        related_facts = [f for f in state["facts"] if section_id in f.get("related_sections", [])]
        if not related_facts:
            # 如果没有特定关联，使用所有事实
            related_facts = state["facts"][:10]

        # 格式化事实
        facts_text = []
        for fact in related_facts:
            facts_text.append(f"- {fact.get('content')} (来源: {fact.get('source_name')}, 可信度: {fact.get('credibility_score')})")

        # 格式化数据点
        data_text = []
        for dp in state["data_points"][:10]:
            data_text.append(f"- {dp.get('name')}: {dp.get('value')} {dp.get('unit', '')} ({dp.get('year', 'N/A')})")

        # 格式化图表信息
        charts_info = []
        for chart in state["charts"]:
            if chart.get("section_id") == section_id:
                charts_info.append(f"- 图表: {chart.get('title')} (ID: {chart.get('id')})")

        prompt = self.SECTION_WRITING_PROMPT.format(
            query=state["query"],
            section_title=section.get("title", ""),
            section_description=section.get("description", ""),
            section_type=section.get("section_type", "mixed"),
            facts="\n".join(facts_text) if facts_text else "（暂无相关事实）",
            data_points="\n".join(data_text) if data_text else "（暂无数据点）",
            insights="\n".join([f"- {i}" for i in state["insights"][:5]]) if state["insights"] else "（暂无洞察）",
            charts_info="\n".join(charts_info) if charts_info else "（暂无图表）"
        )

        response = await self.call_llm(
	            system_prompt="你是法律风控报告专家，擅长撰写基于证据链的法律风险分析报告。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.4,
            max_tokens=16000  # 拉满到最大值
        )

        result = self.parse_json_response(response)

        if result and result.get("content"):
            section_content = result["content"]
            state["draft_sections"][section_id] = section_content
            section["status"] = "drafted"

            # 收集引用
            for citation in result.get("citations", []):
                state["references"].append({
                    "id": len(state["references"]) + 1,
                    "marker": citation.get("marker"),
                    "source": citation.get("source"),
                    "url": citation.get("url", "")
                })

            # 发送章节内容到"过程报告" - 包含完整内容用于流式显示
            self.add_message(state, "section_content", {
                "agent": self.name,
                "section_id": section_id,
                "section_title": section.get("title"),
                "content": section_content,  # 完整章节内容
                "word_count": len(section_content),
                "key_points": result.get("key_points", [])
            })

            # 发送观察消息（显示在左侧步骤流程）
            self.add_message(state, "observation", {
                "agent": self.name,
                "content": f"章节「{section.get('title')}」撰写完成\n字数: {len(section_content)}\n要点: {', '.join(result.get('key_points', [])[:2]) if result.get('key_points') else '无'}"
            })

    async def _synthesize_report(self, state: ResearchState) -> None:
        """整合完整报告"""
        self.add_message(state, "thought", {
            "agent": self.name,
            "content": "正在整合各章节，生成完整研究报告..."
        })

        # 准备各章节内容
        sections_content = []
        for section in state["outline"]:
            section_id = section["id"]
            content = state["draft_sections"].get(section_id, "")
            if content:
                sections_content.append(f"## {section.get('title')}\n{content}")

        # 收集所有来源
        all_sources = []
        for ref in state["references"]:
            all_sources.append(f"- {ref.get('source')} ({ref.get('url', 'N/A')})")

        for fact in state["facts"]:
            source_entry = f"- {fact.get('source_name')} ({fact.get('source_url', 'N/A')})"
            if source_entry not in all_sources:
                all_sources.append(source_entry)

        prompt = self.SYNTHESIS_PROMPT.format(
            query=state["query"],
            sections_content="\n\n".join(sections_content) if sections_content else "（暂无章节内容）",
            all_sources="\n".join(all_sources[:30]) if all_sources else "（暂无来源）"
        )

        self.logger.info(f"[LeadWriter] 调用 LLM 整合报告...")
        response = await self.call_llm(
            system_prompt="你是资深法律风控报告主编，擅长整合事实、依据、风险评级、整改建议和免责声明。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.3,
            max_tokens=16000  # 拉满到最大值
        )

        result = self.parse_json_response(response)
        self.logger.info(f"[LeadWriter] JSON 解析结果: {bool(result)}, keys: {result.keys() if result else 'N/A'}")

        executive_summary = ""
        conclusions = []

        if result and result.get("full_report"):
            state["final_report"] = result.get("full_report", "")
            executive_summary = result.get("executive_summary", "")
            conclusions = result.get("conclusions", [])
            self.logger.info(f"[LeadWriter] ✅ 报告整合成功，长度: {len(state['final_report'])}")

            # 更新参考文献
            for ref in result.get("references", []):
                if ref not in state["references"]:
                    state["references"].append(ref)
        else:
            # JSON 解析失败时的备选方案：使用已有章节内容组装报告
            self.logger.warning(f"[LeadWriter] ⚠️ JSON 解析失败，使用章节内容作为备选")
            fallback_report = f"# {state['query']} 法律风控分析报告\n\n{LEGAL_DEFAULT_DISCLAIMER}\n\n"
            for section in state["outline"]:
                section_id = section["id"]
                content = state["draft_sections"].get(section_id, "")
                if content:
                    fallback_report += f"## {section.get('title', section_id)}\n\n{content}\n\n"
            state["final_report"] = fallback_report
            self.logger.info(f"[LeadWriter] 使用备选报告，长度: {len(state['final_report'])}")

        # 发送报告完成事件 - 包含完整报告内容用于前端流式显示
        self.add_message(state, "report_draft", {
            "agent": self.name,
            "content": state["final_report"],  # 完整报告内容
            "executive_summary": executive_summary,
            "conclusions": conclusions,
            "word_count": len(state["final_report"]),
            "references_count": len(state["references"])
        })

    async def _revise_report(self, state: ResearchState) -> ResearchState:
        """根据反馈修订法律风控报告"""
        ensure_legal_state_defaults(state)
        self.add_message(state, "thought", {
            "agent": self.name,
            "content": "根据法律质量审查反馈修订报告..."
        })

        unresolved = [f for f in state["critic_feedback"] if not f.get("resolved")]
        revision_note = "\n\n## 修订说明\n"
        if unresolved:
            revision_note += "\n".join([
                f"- 已根据审查意见标记为待核验/需人工复核：{issue.get('description', '')}"
                for issue in unresolved[:10]
            ])
        else:
            revision_note += "- 未发现需修订的未解决问题。"
        if "不构成正式法律意见" not in state.get("final_report", ""):
            state["final_report"] = f"{LEGAL_DEFAULT_DISCLAIMER}\n\n{state.get('final_report', '')}"
        if revision_note not in state.get("final_report", ""):
            state["final_report"] = f"{state.get('final_report', '')}{revision_note}"

        for feedback in unresolved:
            feedback["resolved"] = True

        self.add_message(state, "revision_complete", {
            "agent": self.name,
            "changes_count": len(unresolved),
            "addressed_issues": [item.get("id") for item in unresolved if item.get("id")],
            "unable_to_address": []
        })

        state["phase"] = ResearchPhase.REVIEWING.value

        return state


LegalWriter = LeadWriter
