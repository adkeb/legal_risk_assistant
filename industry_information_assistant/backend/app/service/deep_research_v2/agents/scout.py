# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
DeepResearch V2.0 - 深度侦探 Agent (DeepScout)

职责：
1. 全网穿透搜索 - 不只是看摘要，深入阅读原文
2. 递归搜索 - 发现新线索时自动追踪
3. 信源评级 - 评估来源可信度
4. 交叉验证 - 多源验证关键信息
"""

import uuid
import asyncio
import hashlib
import requests
from typing import Dict, Any, List, Optional
from datetime import datetime
from urllib.parse import urlparse

from .base import BaseAgent
from ..state import ResearchState, ResearchPhase, ensure_legal_state_defaults
from ..prompts.legal_prompts import LEGAL_SYSTEM_RULES, LEGAL_SCOUT_PROMPT

try:
    from tools.tavily_tool import perform_internet_search
except ImportError:
    from app.tools.tavily_tool import perform_internet_search

# 网页文本提取库（可选依赖）
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# 本地知识库搜索依赖
try:
    from service.milvus_service import MilvusService
    from service.embedding_service import generate_embedding
    MILVUS_AVAILABLE = True
except ImportError:
    try:
        from app.service.milvus_service import MilvusService
        from app.service.embedding_service import generate_embedding
        MILVUS_AVAILABLE = True
    except ImportError:
        MILVUS_AVAILABLE = False


def infer_legal_source_type(raw: Dict[str, Any], default_source_type: str = "unknown") -> str:
    """Infer a legal source type from loose search result metadata."""
    text = " ".join(str(raw.get(key, "")) for key in ("title", "source_name", "site_name", "summary", "snippet", "content"))
    if any(term in text for term in ["处罚", "行政处罚", "监管处罚"]):
        return "enforcement"
    if any(term in text for term in ["判决", "裁定", "案号", "裁判文书", "法院"]):
        return "court_decision"
    if any(term in text for term in ["案例", "指导性案例"]):
        return "case"
    if any(term in text for term in ["司法解释", "最高人民法院", "最高人民检察院"]):
        return "judicial_interpretation"
    if any(term in text for term in ["合同", "协议", "条款"]):
        return "contract"
    if any(term in text for term in ["监管指引", "指引", "指南"]):
        return "regulator_guidance"
    if any(term in text for term in ["法律", "法典", "法 "]) or text.endswith("法"):
        return "law"
    if any(term in text for term in ["条例", "办法", "规定", "规章"]):
        return "regulation"
    return default_source_type


def normalize_legal_source(raw: Dict[str, Any], index: int, default_source_type: str = "unknown") -> Dict[str, Any]:
    """Normalize arbitrary web/local search data into legal source metadata."""
    source_type = raw.get("source_type")
    if not source_type:
        source_type = default_source_type if default_source_type != "unknown" else infer_legal_source_type(raw, default_source_type)
    title = raw.get("title") or raw.get("source_name") or raw.get("site_name") or f"法律来源 {index}"
    snippet = raw.get("snippet") or raw.get("summary") or raw.get("content") or raw.get("quoted_text") or ""
    source_id = raw.get("source_id") or f"source_{index:03d}"
    return {
        "source_id": source_id,
        "source_type": source_type,
        "title": title,
        "url": raw.get("url") or raw.get("source_url") or "",
        "snippet": snippet[:500],
        "quoted_text": raw.get("quoted_text") or snippet[:500],
        "jurisdiction": raw.get("jurisdiction") or "中国大陆",
        "authority_level": raw.get("authority_level") or ("法律" if source_type == "law" else "unknown"),
        "issuing_body": raw.get("issuing_body") or raw.get("source_name") or raw.get("site_name"),
        "article_no": raw.get("article_no"),
        "effective_date": raw.get("effective_date"),
        "expiry_date": raw.get("expiry_date"),
        "validity_status": raw.get("validity_status") or "unknown",
        "confidence": raw.get("confidence", raw.get("credibility_score", 0.0)),
        "metadata": {
            key: value for key, value in raw.items()
            if key not in {"source_id", "source_type", "title", "url", "source_url", "snippet", "summary", "content", "quoted_text"}
        },
    }


class DeepScout(BaseAgent):
    """
    深度侦探 - 信息收集专家

    特点：
    - 递归搜索：发现重要线索后自动深挖
    - 长文本阅读：进入网页读取完整内容
    - 信源评级：对来源进行可信度评分
    - 并行搜索：同时执行多个搜索任务
    """

    SEARCH_ANALYSIS_PROMPT = """你是一位法律信息提取专家，擅长从法规、案例、监管材料、合同条款和处罚文书中提取可引用证据，并验证法律风控假设。

## 研究问题
{query}

## 当前研究章节
标题: {section_title}
描述: {section_description}

## 法律风控假设（需要寻找证据支持或反驳）
{hypotheses}

## 搜索结果
{search_results}

## 任务
1. 分析搜索结果，提取结构化信息
2. 寻找支持或反驳法律风控假设的证据
3. 优先抽取条文号、案号、监管主体、合同条款号、义务、期限和责任安排

输出JSON格式：
```json
{{
    "extracted_facts": [
        {{
            "content": "提取的事实陈述（要具体、可验证）",
            "source_name": "来源名称",
            "source_url": "来源URL",
            "source_type": "law/regulation/case/court_decision/regulator_guidance/enforcement/contract",
            "credibility_score": 0.0-1.0,
            "data_points": [
                {{"name": "指标名", "value": "数值", "unit": "单位", "year": 2024}}
            ],
            "needs_verification": true或false,
            "importance": "high/medium/low",
            "related_hypothesis": "h_1或h_2或null",
            "hypothesis_support": "supports/refutes/neutral"
        }}
    ],
    "hypothesis_evidence": [
        {{
            "hypothesis_id": "h_1",
            "evidence_type": "supports/refutes/inconclusive",
            "evidence_summary": "证据摘要"
        }}
    ],
    "entities_discovered": [
        {{"name": "实体名", "type": "company/person/policy/technology", "relations": ["与XX相关"]}}
    ],
    "key_insights": ["从这些结果中得到的关键洞察"],
    "follow_up_queries": ["需要进一步搜索的关键词"],
    "source_tracing_queries": ["追溯权威法律来源的搜索词，如'民法典 第五百八十五条 违约金'"],
    "missing_info": ["仍然缺失的信息"],
    "source_quality_assessment": "对整体来源质量的评估"
}}
```

## 评分标准
- 现行法律、行政法规、司法解释、最高法案例: 0.9-1.0
- 监管规则、监管指引、行政处罚决定: 0.8-0.95
- 裁判文书、指导性案例、典型案例: 0.75-0.95
- 合同原文、内部制度、用户上传材料: 0.7-0.9
- 律所文章、媒体报道、二手解读: 0.3-0.7

请开始分析："""

    DEEP_READ_PROMPT = """你是一位法律信息提取专家，擅长从长文本中提取法规、案例、处罚、合同条款和企业风险事实。

## 研究问题
{query}

## 文档来源
URL: {url}
标题: {title}

## 文档内容
{content}

    ## 任务
    深度阅读文档，提取与研究问题相关的可核验法律信息。不得伪造法条、案号、处罚文书号或合同正文。

    输出JSON格式：
    ```json
    {{
        "summary": "文档核心法律信息摘要（200字内）",
        "legal_sources": [
            {{
                "source_type": "law/regulation/judicial_interpretation/case/court_decision/enforcement/contract/internal_policy/regulator_guidance/company_record/news",
                "title": "来源标题",
                "source_name": "来源名称",
                "source_url": "URL",
                "article_no": "条款/案号/处罚文书号/定位",
                "quoted_text": "可核验原文片段",
                "validity_status": "effective/expired/unknown",
                "credibility_score": 0.0
            }}
        ],
        "extracted_facts": [
            {{
                "content": "关键事实",
                "source_name": "来源名称",
                "source_url": "URL",
                "source_type": "law/regulation/case/enforcement/contract/company_record/news",
                "credibility_score": 0.0,
                "page_location": "大概位置描述"
            }}
        ],
        "quotes": ["重要原文引用"],
        "related_entities": ["主体/法规/案件/风险"],
        "publication_date": "发布日期（如果能识别）",
        "authority_assessment": "来源法律效力或可信度评估"
    }}
    ```"""

    def __init__(
        self,
        llm_api_key: str,
        llm_base_url: str,
        search_api_key: str,
        model: str = ""
    ):
        super().__init__(
            name="DeepScout",
            role="深度侦探",
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            model=model
        )
        self.search_api_key = search_api_key
        self.search_cache: Dict[str, List] = {}
        self.search_locks: Dict[str, asyncio.Lock] = {}
        self.fact_fingerprints: Dict[str, str] = {}  # 事实指纹用于去重

        # 初始化本地知识库搜索服务
        self.milvus_service = None
        if MILVUS_AVAILABLE:
            try:
                self.milvus_service = MilvusService()
                self.logger.info("Milvus service initialized for local knowledge base search")
            except Exception as e:
                self.logger.warning(f"Failed to initialize Milvus service: {e}")

    async def process(self, state: ResearchState) -> ResearchState:
        """处理入口"""
        ensure_legal_state_defaults(state)
        # 处理补充搜索阶段（审核后回退）
        if state["phase"] == ResearchPhase.RE_RESEARCHING.value:
            return await self._supplementary_research(state)

        # 正常研究阶段
        if state["phase"] not in [ResearchPhase.PLANNING.value, ResearchPhase.RESEARCHING.value]:
            return state

        state["phase"] = ResearchPhase.RESEARCHING.value

        # 获取搜索模式配置
        search_web = state.get("search_web", True)
        search_local = state.get("search_local", False)

        if not search_web and not search_local:
            self.logger.info("No search mode selected; legal sources will remain empty")
            self.add_message(state, "research_step", {
                "step_id": f"step_searching_{uuid.uuid4().hex[:8]}",
                "step_type": "searching",
                "title": "法律信息检索",
                "subtitle": "未启用网络或本地知识库搜索",
                "status": "completed",
                "stats": {"results_count": 0, "sources_count": 0}
            })
            self.add_message(state, "observation", {
                "agent": self.name,
                "content": "未启用搜索模式，本轮不检索外部法律来源；后续分析会标记证据不足或需人工复核。"
            })
            return state

        # 获取需要研究的章节
        pending_sections = [s for s in state["outline"] if s.get("status") == "pending"]

        if not pending_sections:
            self.logger.info("No pending sections to research")
            return state

        # 构建搜索模式描述
        search_mode_desc = []
        if search_web:
            search_mode_desc.append("网络搜索")
        if search_local:
            search_mode_desc.append("本地知识库")
        subtitle = " + ".join(search_mode_desc) if search_mode_desc else "法律检索"

        # 发送 research_step 开始事件
        self.add_message(state, "research_step", {
            "step_id": f"step_searching_{uuid.uuid4().hex[:8]}",
            "step_type": "searching",
            "title": "法律信息检索",
            "subtitle": subtitle,
            "status": "running",
            "stats": {"sections_count": len(pending_sections), "results_count": 0},
            "search_web": search_web,
            "search_local": search_local
        })

        self.add_message(state, "thought", {
            "agent": self.name,
            "content": f"开始{'、'.join(search_mode_desc)}，检索法规、案例、处罚、合同和企业风险信息..."
        })

        # 并行研究多个章节
        tasks = []
        for section in pending_sections[:3]:  # 每次最多处理3个章节
            tasks.append(self._research_section(state, section))

        await asyncio.gather(*tasks)

        # 发送 research_step 完成事件
        self.add_message(state, "research_step", {
            "step_type": "searching",
            "title": "法律信息检索",
            "subtitle": "法规/案例/处罚/合同/企业风险检索",
            "status": "completed",
            "stats": {
                "results_count": len(state.get("facts", [])),
                "sources_count": len(state.get("legal_sources", []))
            }
        })

        # 发送搜索结果事件供前端详情面板展示
        self._emit_search_results_event(state)

        return state

    async def _supplementary_research(self, state: ResearchState) -> ResearchState:
        """
        补充搜索阶段 - 处理审核后发现的信息缺失

        这个方法在 Critic 发现需要补充信息时被调用
        """
        pending_queries = state.get("pending_search_queries", [])

        if not pending_queries:
            self.logger.info("No pending search queries for supplementary research")
            state["phase"] = ResearchPhase.WRITING.value
            return state

        if not state.get("search_web", True) and not state.get("search_local", False):
            self.logger.info("No search mode selected for supplementary research; skipping external search")
            self.add_message(state, "observation", {
                "agent": self.name,
                "content": "未启用搜索模式，跳过补充检索；相关缺口将保留为需人工复核。"
            })
            state["pending_search_queries"] = []
            state["phase"] = ResearchPhase.WRITING.value
            return state

        self.logger.info(f"Starting supplementary research with {len(pending_queries)} queries")

        # 发送 research_step 开始事件
        self.add_message(state, "research_step", {
            "step_id": f"step_supplementary_{uuid.uuid4().hex[:8]}",
            "step_type": "searching",
            "title": "补充搜索",
            "subtitle": "针对性信息补充",
            "status": "running",
            "stats": {"queries_count": len(pending_queries), "results_count": 0}
        })

        self.add_message(state, "thought", {
            "agent": self.name,
            "content": f"根据审核反馈，开始补充搜索 {len(pending_queries)} 个问题..."
        })

        # 执行补充搜索
        initial_facts_count = len(state.get("facts", []))

        for query in pending_queries[:5]:  # 最多处理5个补充查询
            self.add_message(state, "action", {
                "agent": self.name,
                "tool": "supplementary_search",
                "query": query
            })

            # 执行搜索
            results = await self._execute_search(query, count=8)

            if results:
                self._append_legal_sources(state, results, default_source_type="unknown")
                # 分析结果
                analysis = await self._analyze_supplementary_results(
                    state["query"],
                    query,
                    results
                )

                if analysis:
                    # 添加新事实
                    for fact in analysis.get("extracted_facts", []):
                        content = fact.get("content", "")
                        source_url = fact.get("source_url", "")

                        if not self._is_duplicate_fact(content, source_url):
                            fact_entry = {
                                "id": f"fact_{uuid.uuid4().hex[:8]}",
                                "content": content,
                                "source_url": source_url,
                                "source_name": fact.get("source_name", ""),
                                "source_type": fact.get("source_type", "news"),
                                "credibility_score": fact.get("credibility_score", 0.5),
                                "is_supplementary": True,  # 标记为补充搜索获得
                                "related_sections": []
                            }
                            state["facts"].append(fact_entry)
                    self._append_legal_sources(
                        state,
                        analysis.get("legal_sources", []) + analysis.get("extracted_facts", []),
                        default_source_type="unknown"
                    )

        # 清空待搜索列表
        state["pending_search_queries"] = []

        # 发送完成事件
        new_facts_count = len(state.get("facts", [])) - initial_facts_count
        self.add_message(state, "research_step", {
            "step_type": "searching",
            "title": "补充搜索",
            "subtitle": "针对性信息补充",
            "status": "completed",
            "stats": {
                "results_count": new_facts_count,
                "sources_count": len(set(f.get("source_url", "") for f in state.get("facts", [])[-new_facts_count:] if new_facts_count > 0))
            }
        })

        self.add_message(state, "observation", {
            "agent": self.name,
            "content": f"补充搜索完成，新增 {new_facts_count} 条事实"
        })

        # 发送更新后的搜索结果
        self._emit_search_results_event(state)

        # 继续写作阶段
        state["phase"] = ResearchPhase.WRITING.value

        return state

    async def _fetch_stock_data_if_relevant(self, state: ResearchState) -> None:
        """法律风控专用版禁用股票/行业行情增强。"""
        return None

    async def _analyze_supplementary_results(
        self,
        original_query: str,
        search_query: str,
        results: List[Dict]
    ) -> Optional[Dict]:
        """分析补充搜索结果"""
        results_text = []
        for r in results[:8]:
            results_text.append(f"标题: {r.get('title', 'N/A')}\n来源: {r.get('site_name', 'N/A')}\n内容: {r.get('summary', '')[:300]}")

        prompt = f"""你是一位法律信息提取专家，正在补充搜索以解决法律风控审查发现的信息缺失问题。

## 原始研究问题
{original_query}

## 补充搜索关键词
{search_query}

## 搜索结果
{chr(10).join(results_text)}

## 任务
从搜索结果中提取与"{search_query}"直接相关的法规、案例、处罚、合同条款、企业记录和关键事实。

输出JSON格式：
```json
{{
    "legal_sources": [
        {{
            "source_type": "law/regulation/judicial_interpretation/case/court_decision/enforcement/contract/internal_policy/regulator_guidance/company_record/news",
            "title": "来源标题",
            "source_name": "来源名称",
            "source_url": "来源URL",
            "quoted_text": "可核验片段",
            "validity_status": "effective/expired/unknown",
            "credibility_score": 0.0
        }}
    ],
    "extracted_facts": [
        {{
            "content": "提取的事实陈述",
            "source_name": "来源名称",
            "source_url": "来源URL",
            "source_type": "law/regulation/case/enforcement/contract/company_record/news",
            "credibility_score": 0.0-1.0,
            "data_points": [
                {{"name": "指标名", "value": "数值", "unit": "单位"}}
            ]
        }}
    ],
    "key_findings": "本次补充搜索的关键发现"
}}
```"""

        try:
            response = await self.call_llm(
                system_prompt=LEGAL_SYSTEM_RULES,
                user_prompt=prompt,
                json_mode=True,
                temperature=0.2
            )
            result = self.parse_json_response(response)
            return result or self._fallback_search_analysis(search_query, {"title": "补充搜索"}, results)
        except Exception as exc:
            self.logger.warning(f"Supplementary legal analysis LLM failed, using fallback: {exc}")
            return self._fallback_search_analysis(search_query, {"title": "补充搜索"}, results)

    def _emit_search_results_event(self, state: ResearchState) -> None:
        """发送搜索结果事件供前端展示"""
        search_results_for_ui = []
        legal_sources = state.get("legal_sources", [])[-20:]
        if legal_sources:
            for source in legal_sources:
                search_results_for_ui.append({
                    "id": source.get("source_id", ""),
                    "title": source.get("title", ""),
                    "source": source.get("issuing_body") or source.get("source_type", "法律来源"),
                    "url": source.get("url", ""),
                    "snippet": source.get("quoted_text") or source.get("snippet", ""),
                    "date": source.get("effective_date", ""),
                    "source_type": source.get("source_type", "unknown"),
                    "jurisdiction": source.get("jurisdiction", "中国大陆"),
                    "authority_level": source.get("authority_level", "unknown"),
                    "article_no": source.get("article_no"),
                    "validity_status": source.get("validity_status", "unknown"),
                })
        else:
            for fact in state.get("facts", [])[-20:]:  # 取最近的20条
                search_results_for_ui.append({
                    "id": fact.get("id", ""),
                    "title": fact.get("content", "")[:80] + "..." if len(fact.get("content", "")) > 80 else fact.get("content", ""),
                    "source": fact.get("source_name", "未知来源"),
                    "url": fact.get("source_url", ""),
                    "snippet": fact.get("content", "")[:200],
                    "date": fact.get("date", ""),
                    "isSupplementary": fact.get("is_supplementary", False),
                    "source_type": fact.get("source_type", "unknown"),
                })

        if search_results_for_ui:
            self.add_message(state, "search_results", {
                "results": search_results_for_ui
            })

    def _append_legal_sources(
        self,
        state: ResearchState,
        sources: List[Dict[str, Any]],
        default_source_type: str = "unknown"
    ) -> None:
        """Append normalized legal sources while keeping bucket fields in sync."""
        ensure_legal_state_defaults(state)
        existing_keys = {
            (item.get("url"), (item.get("quoted_text") or item.get("snippet") or "")[:300])
            for item in state.get("legal_sources", [])
        }
        existing_source_ids = {item.get("source_id") for item in state.get("legal_sources", []) if item.get("source_id")}
        next_index = len(state.get("legal_sources", [])) + 1

        for raw in sources or []:
            if not isinstance(raw, dict):
                continue
            source = normalize_legal_source(raw, next_index, default_source_type)
            key = (source.get("url"), (source.get("quoted_text") or source.get("snippet") or "")[:300])
            if source.get("source_id") in existing_source_ids or key in existing_keys:
                continue
            existing_source_ids.add(source.get("source_id"))
            existing_keys.add(key)
            state["legal_sources"].append(source)
            state["raw_sources"].append(raw)

            source_type = source.get("source_type")
            if source_type in {"case", "court_decision"}:
                state["case_sources"].append(source)
            if source_type == "enforcement":
                state["enforcement_sources"].append(source)
            if source_type in {"law", "regulation", "judicial_interpretation", "regulator_guidance"}:
                state["applicable_laws"].append(source)
            next_index += 1

    async def _research_section(self, state: ResearchState, section: Dict) -> None:
        """研究单个章节"""
        section_id = section["id"]
        section_title = section["title"]
        search_queries = section.get("search_queries", [section_title])

        # 获取搜索模式配置
        search_web = state.get("search_web", True)
        search_local = state.get("search_local", False)

        self.logger.info(f"Researching section: {section_title} (web={search_web}, local={search_local})")

        self.add_message(state, "action", {
            "agent": self.name,
            "tool": "parallel_search",
            "section": section_title,
            "queries": search_queries,
            "search_web": search_web,
            "search_local": search_local
        })

        # 逐个执行搜索，每完成一个就发送事件（提升用户体验）
        all_results = []
        for i, query in enumerate(search_queries):
            # 网络搜索
            if search_web:
                results = await self._execute_search(query)
                all_results.extend(results)

                # 搜索完成后立即发送原始结果（让用户看到进度）
                if results:
                    self.add_message(state, "search_progress", {
                        "agent": self.name,
                        "query": query,
                        "results_count": len(results),
                        "total_so_far": len(all_results),
                        "section": section_title,
                        "progress": f"{i + 1}/{len(search_queries)}",
                        "search_type": "web"
                    })

                    # 立即发送搜索结果供前端展示
                    search_results_for_ui = [
                        {
                            "id": f"sr_{uuid.uuid4().hex[:6]}",
                            "title": r.get("title", "")[:80],
                            "source": r.get("site_name", "未知来源"),
                            "url": r.get("url", ""),
                            "snippet": r.get("summary", "") or r.get("snippet", ""),
                            "date": r.get("date", ""),
                            "isLocal": False
                        }
                        for r in results[:5]  # 每次最多显示5条
                    ]
                    self.add_message(state, "search_results", {
                        "results": search_results_for_ui,
                        "isIncremental": True,
                        "searchType": "web"
                    })

            # 本地知识库搜索
            if search_local:
                local_results = await self._execute_local_search(query)
                all_results.extend(local_results)

                if local_results:
                    self.add_message(state, "search_progress", {
                        "agent": self.name,
                        "query": query,
                        "results_count": len(local_results),
                        "total_so_far": len(all_results),
                        "section": section_title,
                        "progress": f"{i + 1}/{len(search_queries)}",
                        "search_type": "local"
                    })

                    # 发送本地搜索结果
                    local_results_for_ui = [
                        {
                            "id": f"lr_{uuid.uuid4().hex[:6]}",
                            "title": r.get("title", "")[:80],
                            "source": "本地知识库",
                            "url": r.get("url", ""),
                            "snippet": r.get("summary", "") or r.get("snippet", ""),
                            "date": "",
                            "isLocal": True,
                            "score": r.get("score", 0)
                        }
                        for r in local_results[:5]
                    ]
                    self.add_message(state, "search_results", {
                        "results": local_results_for_ui,
                        "isIncremental": True,
                        "searchType": "local"
                    })

        if not all_results:
            self.logger.warning(f"No search results for section: {section_title}")
            return

        self._append_legal_sources(state, all_results, default_source_type="unknown")

        self.add_message(state, "thought", {
            "agent": self.name,
            "content": f"搜索完成，获得 {len(all_results)} 条结果，正在分析提取关键信息..."
        })

        # 分析搜索结果（传入假设以便验证）
        analysis = await self._analyze_search_results(
            state["query"],
            section,
            all_results,
            hypotheses=state.get("hypotheses", [])
        )

        if analysis:
            self._append_legal_sources(
                state,
                analysis.get("legal_sources", []) + analysis.get("extracted_facts", []),
                default_source_type="unknown"
            )
            # 提取事实（带去重）
            added_facts = 0
            duplicate_facts = 0
            for fact in analysis.get("extracted_facts", []):
                content = fact.get("content", "")
                source_url = fact.get("source_url", "")

                # 去重检查
                if self._is_duplicate_fact(content, source_url):
                    duplicate_facts += 1
                    continue

                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": content,
                    "source_url": source_url,
                    "source_name": fact.get("source_name", ""),
                    "source_type": fact.get("source_type", "news"),
                    "credibility_score": fact.get("credibility_score", 0.5),
                    "extracted_at": datetime.now().isoformat(),
                    "related_sections": [section_id],
                    "verified": False,
                    "related_hypothesis": fact.get("related_hypothesis"),
                    "hypothesis_support": fact.get("hypothesis_support"),
                    "metadata": {}
                }
                state["facts"].append(fact_entry)
                added_facts += 1

                # 提取数据点
                for dp in fact.get("data_points", []):
                    data_point = {
                        "id": f"dp_{uuid.uuid4().hex[:8]}",
                        "name": dp.get("name", ""),
                        "value": dp.get("value", ""),
                        "unit": dp.get("unit", ""),
                        "year": dp.get("year"),
                        "source": fact.get("source_name", ""),
                        "confidence": fact.get("credibility_score", 0.5)
                    }
                    state["data_points"].append(data_point)

            if duplicate_facts > 0:
                self.logger.info(f"Deduplicated {duplicate_facts} facts, added {added_facts}")

            # 更新知识图谱
            entities = analysis.get("entities_discovered", [])
            if entities:
                self._update_knowledge_graph(state, entities)
                self.logger.info(f"Added {len(entities)} entities to knowledge graph")
                # 发送知识图谱增量更新事件
                graph = state.get("knowledge_graph", {"nodes": [], "edges": []})
                self.add_message(state, "knowledge_graph", {
                    "graph": graph,
                    "stats": {
                        "entitiesCount": len(graph.get("nodes", [])),
                        "relationsCount": len(graph.get("edges", []))
                    },
                    "isIncremental": True
                })

            # 更新假设状态
            hypothesis_evidence = analysis.get("hypothesis_evidence", [])
            if hypothesis_evidence:
                self._update_hypothesis_status(state, hypothesis_evidence)

            # 添加洞察
            for insight in analysis.get("key_insights", []):
                if insight not in state["insights"]:
                    state["insights"].append(insight)

            # 收集本次提取的数据点
            extracted_data_points = []
            for fact in analysis.get("extracted_facts", []):
                for dp in fact.get("data_points", []):
                    extracted_data_points.append({
                        "name": dp.get("name", ""),
                        "value": dp.get("value", ""),
                        "unit": dp.get("unit", ""),
                        "year": dp.get("year"),
                        "source": fact.get("source_name", "")
                    })

            # 发送观察结果 (包含详细数据供前端展示)
            self.add_message(state, "observation", {
                "agent": self.name,
                "section": section_title,
                "facts_count": added_facts,
                "duplicates_removed": duplicate_facts,
                "data_points_count": len(extracted_data_points),
                "insights": analysis.get("key_insights", [])[:3],
                "source_quality": analysis.get("source_quality_assessment", ""),
                "hypothesis_updates": len(hypothesis_evidence),
                # 新增: 原始搜索结果 (供前端详情面板展示)
                "search_results": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "source": r.get("site_name", ""),
                        "snippet": r.get("summary", "") or r.get("snippet", ""),
                        "date": r.get("date", "")
                    }
                    for r in all_results[:10]  # 最多返回10条
                ],
                # 新增: 提取的事实
                "extracted_facts": [
                    {
                        "content": f.get("content", ""),
                        "source_name": f.get("source_name", ""),
                        "source_url": f.get("source_url", ""),
                        "credibility": f.get("credibility_score", 0.5)
                    }
                    for f in analysis.get("extracted_facts", [])[:8]
                ],
                # 新增: 提取的数据点
                "data_points": extracted_data_points[:10]
            })

            # 递归搜索：信源追溯查询（优先级最高）
            source_tracing = analysis.get("source_tracing_queries", [])
            if source_tracing and state.get("allow_recursive_search", True) and state["iteration"] < state["max_iterations"]:
                self.add_message(state, "thought", {
                    "agent": self.name,
                    "content": f"追溯原始数据源: {', '.join(source_tracing[:2])}"
                })
                # 执行信源追溯搜索
                await self._execute_deep_search(
                    state, section_id, source_tracing[:2],
                    search_type="source_tracing",
                    hypotheses=state.get("hypotheses", [])
                )

            # 递归搜索：追踪发现的新线索
            follow_up = analysis.get("follow_up_queries", [])
            if follow_up and state.get("allow_recursive_search", True) and state["iteration"] < state["max_iterations"]:
                self.add_message(state, "thought", {
                    "agent": self.name,
                    "content": f"追踪发现的线索: {', '.join(follow_up[:2])}"
                })
                # 执行线索追踪搜索
                await self._execute_deep_search(
                    state, section_id, follow_up[:2],
                    search_type="follow_up",
                    hypotheses=state.get("hypotheses", [])
                )

        # 更新章节状态
        section["status"] = "researching"

    async def _execute_deep_search(
        self,
        state: ResearchState,
        section_id: str,
        queries: List[str],
        search_type: str,
        hypotheses: List[Dict],
        depth: int = 1,
        max_depth: int = 2
    ) -> None:
        """
        执行深度递归搜索

        Args:
            state: 研究状态
            section_id: 关联章节ID
            queries: 搜索查询列表
            search_type: 搜索类型 (source_tracing/follow_up)
            hypotheses: 研究假设
            depth: 当前递归深度
            max_depth: 最大递归深度
        """
        if depth > max_depth:
            self.logger.info(f"Reached max recursion depth ({max_depth})")
            return

        type_labels = {
            "source_tracing": "信源追溯",
            "follow_up": "线索追踪"
        }

        self.add_message(state, "action", {
            "agent": self.name,
            "tool": f"deep_search_{search_type}",
            "queries": queries,
            "depth": depth
        })

        for query in queries:
            # 执行搜索
            results = await self._execute_search(query, count=6)

            if not results:
                continue

            self._append_legal_sources(state, results, default_source_type="unknown")

            # 立即发送搜索结果供前端展示（增量）
            search_results_for_ui = [
                {
                    "id": f"sr_{uuid.uuid4().hex[:6]}",
                    "title": r.get("title", "")[:80],
                    "source": r.get("site_name", "未知来源"),
                    "url": r.get("url", ""),
                    "snippet": r.get("summary", "") or r.get("snippet", ""),
                    "date": r.get("date", "")
                }
                for r in results[:5]
            ]
            self.add_message(state, "search_results", {
                "results": search_results_for_ui,
                "isIncremental": True,
                "searchType": type_labels.get(search_type, search_type),
                "depth": depth
            })

            # 分析结果
            analysis = await self._analyze_deep_search_results(
                state["query"],
                query,
                results,
                search_type,
                hypotheses
            )

            if not analysis:
                continue

            self._append_legal_sources(
                state,
                analysis.get("legal_sources", []) + analysis.get("extracted_facts", []),
                default_source_type="unknown"
            )

            # 提取并添加事实
            added_facts = 0
            for fact in analysis.get("extracted_facts", []):
                content = fact.get("content", "")
                source_url = fact.get("source_url", "")

                if not self._is_duplicate_fact(content, source_url):
                    fact_entry = {
                        "id": f"fact_{uuid.uuid4().hex[:8]}",
                        "content": content,
                        "source_url": source_url,
                        "source_name": fact.get("source_name", ""),
                        "source_type": fact.get("source_type", "news"),
                        "credibility_score": fact.get("credibility_score", 0.5),
                        "related_sections": [section_id],
                        "search_depth": depth,
                        "search_type": search_type
                    }
                    state["facts"].append(fact_entry)
                    added_facts += 1

                    # 更新假设证据（如果有）
                    hypothesis_support = fact.get("hypothesis_support")
                    if hypothesis_support and fact.get("related_hypothesis"):
                        h_id = fact["related_hypothesis"]
                        for h in state.get("hypotheses", []):
                            if h.get("id") == h_id:
                                if hypothesis_support == "supports":
                                    h.setdefault("evidence_for", []).append(content[:100])
                                elif hypothesis_support == "refutes":
                                    h.setdefault("evidence_against", []).append(content[:100])

            # 提取数据点
            for dp in analysis.get("data_points", []):
                state["data_points"].append({
                    "id": f"dp_{uuid.uuid4().hex[:8]}",
                    "name": dp.get("name"),
                    "value": dp.get("value"),
                    "unit": dp.get("unit", ""),
                    "year": dp.get("year"),
                    "source": dp.get("source", query),
                    "confidence": dp.get("confidence", 0.7),
                    "search_depth": depth
                })

            self.logger.info(f"Deep search ({search_type}, depth={depth}): +{added_facts} facts for query '{query[:30]}...'")

            # 如果发现更多需要追溯的线索，继续递归（但不超过max_depth）
            if depth < max_depth:
                further_tracing = analysis.get("further_tracing_queries", [])
                if further_tracing:
                    self.add_message(state, "thought", {
                        "agent": self.name,
                        "content": f"发现更深层线索 (深度{depth+1}): {', '.join(further_tracing[:2])}"
                    })
                    await self._execute_deep_search(
                        state, section_id, further_tracing[:2],
                        search_type, hypotheses,
                        depth=depth + 1, max_depth=max_depth
                    )

    async def _analyze_deep_search_results(
        self,
        original_query: str,
        search_query: str,
        results: List[Dict],
        search_type: str,
        hypotheses: List[Dict]
    ) -> Optional[Dict]:
        """分析深度搜索结果"""
        results_text = []
        for r in results[:6]:
            results_text.append(f"标题: {r.get('title', 'N/A')}\n来源: {r.get('site_name', 'N/A')}\n内容: {r.get('summary', '')[:300]}")

        hypotheses_text = ""
        if hypotheses:
            hypotheses_text = "## 研究假设\n" + "\n".join([
                f"- [{h.get('id')}] {h.get('content')}" for h in hypotheses[:3]
            ])

        search_type_desc = "追溯法律依据或证据原文" if search_type == "source_tracing" else "追踪相关法律线索"

        prompt = f"""你是一位法律检索与证据核验专家，正在{search_type_desc}。

## 原始研究问题
{original_query}

## 当前搜索关键词
{search_query}

{hypotheses_text}

## 搜索结果
{chr(10).join(results_text)}

    ## 任务
    1. 从搜索结果中提取法规、司法解释、案例、裁判文书、行政处罚、合同条款、内部制度或企业记录。
    2. 为每条风险相关事实保留 source_id/source_url/quoted_text，缺少依据时标记待核验。
    3. 如果发现引用了其他法律依据或证据原文，生成进一步追溯查询。

    输出JSON格式：
    ```json
    {{
        "legal_sources": [
            {{
                "source_type": "law/regulation/judicial_interpretation/case/court_decision/enforcement/contract/internal_policy/regulator_guidance/company_record/news",
                "title": "来源标题",
                "source_name": "来源名称",
                "source_url": "来源URL",
                "quoted_text": "可核验片段",
                "validity_status": "effective/expired/unknown",
                "credibility_score": 0.0
            }}
        ],
        "extracted_facts": [
            {{
                "content": "提取的事实陈述（要具体、可验证）",
                "source_name": "来源名称",
                "source_url": "来源URL",
                "source_type": "law/regulation/case/enforcement/contract/company_record/news",
                "credibility_score": 0.0-1.0,
                "related_hypothesis": "h_1或null",
                "hypothesis_support": "supports/refutes/neutral"
            }}
        ],
        "further_tracing_queries": ["如果发现引用了其他法律依据或原始证据，建议进一步追溯的查询"],
        "source_reliability": "对本次搜索来源法律效力和可核验性的评估"
    }}
    ```"""

        try:
            response = await self.call_llm(
                system_prompt=LEGAL_SYSTEM_RULES,
                user_prompt=prompt,
                json_mode=True,
                temperature=0.2
            )
            result = self.parse_json_response(response)
            if result:
                return result
        except Exception as exc:
            self.logger.warning(f"Deep legal search analysis LLM failed, using fallback: {exc}")

        fallback = self._fallback_search_analysis(search_query, {"title": search_type_desc}, results)
        fallback["further_tracing_queries"] = []
        fallback["source_reliability"] = "LLM 不可用，已基于检索结果片段做结构化降级抽取。"
        return fallback

    async def _execute_local_search(self, query: str, top_k: int = 10) -> List[Dict]:
        """
        执行本地知识库搜索 - 使用 Milvus 向量检索

        Args:
            query: 搜索查询
            top_k: 返回结果数量

        Returns:
            搜索结果列表
        """
        if not self.milvus_service or not MILVUS_AVAILABLE:
            self.logger.warning("Milvus service not available for local search")
            return []

        try:
            # 生成查询向量
            query_vector = generate_embedding(query)
            if not query_vector:
                self.logger.error("Failed to generate embedding for query")
                return []

            self.logger.info(f"Executing local knowledge base search: {query[:50]}...")

            # 搜索所有知识库（collection_name = "knowledge_base"）
            results = self.milvus_service.search(
                collection_name="knowledge_base",
                query_vector=query_vector,
                top_k=top_k
            )

            # 格式化结果为与网络搜索一致的格式
            formatted_results = []
            for r in results:
                formatted_results.append({
                    'url': f"local://kb/{r.get('kb_id', 'unknown')}/{r.get('doc_id', 'unknown')}",
                    'title': r.get('filename', 'N/A'),
                    'summary': r.get('content', '')[:500],
                    'snippet': r.get('content', '')[:200],
                    'site_name': f"本地知识库",
                    'date': '',
                    'score': r.get('score', 0),
                    'is_local': True,
                    'kb_id': r.get('kb_id'),
                    'doc_id': r.get('doc_id'),
                    'chunk_index': r.get('chunk_index')
                })

            self.logger.info(f"Local search returned {len(formatted_results)} results for: {query[:30]}...")
            return formatted_results

        except Exception as e:
            self.logger.error(f"Local search error for '{query}': {e}")
            return []

    def _infer_tavily_topic(self, query: str) -> str:
        """Infer Tavily topic from query text while defaulting to general."""
        text = query or ""
        if any(term in text for term in ["股票", "证券", "基金", "债券", "财报", "金融", "财经", "上市公司"]):
            return "finance"
        if any(term in text for term in ["新闻", "最新", "近期", "今日", "舆情", "动态"]):
            return "news"
        return "general"

    def _format_tavily_results(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        for item in data.get("results", []) or []:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or ""
            content = item.get("raw_content") or item.get("content") or ""
            if not url or not content:
                continue
            hostname = ""
            try:
                hostname = urlparse(url).hostname or ""
            except Exception:
                hostname = ""
            results.append({
                "url": url,
                "title": item.get("title") or "N/A",
                "summary": content[:2000],
                "snippet": (item.get("content") or content)[:500],
                "site_name": hostname.replace("www.", "") or "Tavily",
                "date": item.get("published_date") or "",
                "score": item.get("score"),
                "raw_content": item.get("raw_content") or "",
                "search_provider": "tavily",
            })
        return results

    async def _execute_search(self, query: str, count: int = 10) -> List[Dict]:
        """执行网络搜索 - 默认使用 Tavily，Bocha 仅作为兼容兜底。"""
        # 检查缓存
        normalized_query = " ".join((query or "").split())
        cache_key = hashlib.md5(f"tavily|{normalized_query}|{count}".encode()).hexdigest()
        if cache_key in self.search_cache:
            self.logger.debug(f"Cache hit for query: {query[:30]}...")
            return self.search_cache[cache_key]

        lock = self.search_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            if cache_key in self.search_cache:
                self.logger.debug(f"Cache hit after wait for query: {query[:30]}...")
                return self.search_cache[cache_key]

            results = await self._execute_tavily_search(normalized_query, count)
            if not results:
                results = await self._execute_bocha_search(normalized_query, count)

            self.search_cache[cache_key] = results
            return results

    async def _execute_tavily_search(self, normalized_query: str, count: int) -> List[Dict[str, Any]]:
        try:
            topic = self._infer_tavily_topic(normalized_query)
            self.logger.info(f"Executing Tavily search: {normalized_query[:50]}... (topic={topic})")
            data = await asyncio.to_thread(
                perform_internet_search,
                query=normalized_query,
                topic=topic,
                max_results=count,
                include_raw_content=True,
            )
            results = self._format_tavily_results(data)
            self.logger.info(f"Tavily search returned {len(results)} results for: {normalized_query[:30]}...")
            return results
        except requests.exceptions.Timeout:
            self.logger.error(f"Tavily search timeout for: {normalized_query[:30]}...")
            return []
        except Exception as e:
            self.logger.warning(f"Tavily search failed for '{normalized_query[:50]}...': {e}")
            return []

    async def _execute_bocha_search(self, normalized_query: str, count: int) -> List[Dict[str, Any]]:
        """Fallback network search through Bocha for compatibility."""
        if not self.search_api_key:
            self.logger.info("Bocha fallback skipped: BOCHA_API_KEY is not configured")
            return []

        try:
            url = "https://api.bocha.cn/v1/web-search"
            payload = {
                "query": normalized_query,
                "summary": True,
                "count": count,
                "freshness": "noLimit"
            }
            headers = {
                'Authorization': f'Bearer {self.search_api_key}',
                'Content-Type': 'application/json'
            }

            self.logger.info(f"Executing Bocha fallback search: {normalized_query[:50]}...")

            response = await asyncio.to_thread(
                requests.post,
                url,
                headers=headers,
                json=payload,
                timeout=30
            )

            if response.status_code != 200:
                self.logger.error(f"Bocha API error: {response.status_code} - {response.text[:200]}")
                return []

            data = response.json()

            if data.get('code') != 200:
                self.logger.error(f"Bocha API returned error: {data.get('msg', 'Unknown error')}")
                return []

            webpages = data.get('data', {}).get('webPages', {}).get('value', [])
            self.logger.info(f"Bocha fallback returned {len(webpages)} results for: {normalized_query[:30]}...")

            results = []
            for item in webpages:
                if item.get('url') and (item.get('snippet') or item.get('summary')):
                    results.append({
                        'url': item.get('url'),
                        'title': item.get('name', 'N/A'),
                        'summary': item.get('summary', '') or item.get('snippet', ''),
                        'snippet': item.get('snippet', ''),
                        'site_name': item.get('siteName', 'N/A'),
                        'date': item.get('datePublished', '') or item.get('dateLastCrawled', ''),
                        'search_provider': 'bocha',
                    })

            return results

        except requests.exceptions.Timeout:
            self.logger.error(f"Bocha search timeout for: {normalized_query[:30]}...")
            return []
        except Exception as e:
            self.logger.error(f"Bocha search error for '{normalized_query}': {e}")
            return []

    async def _analyze_search_results(
        self,
        query: str,
        section: Dict,
        results: List[Dict],
        hypotheses: List[Dict] = None
    ) -> Optional[Dict]:
        """分析搜索结果"""
        if not results:
            return None

        # 格式化搜索结果
        formatted_results = []
        for i, r in enumerate(results[:15]):  # 最多分析15条
            formatted_results.append(f"""
[{i+1}] {r.get('title', 'N/A')}
URL: {r.get('url', '')}
来源: {r.get('site_name', 'N/A')}
日期: {r.get('date', 'N/A')}
摘要: {r.get('summary', '')[:300]}
""")

        # 格式化假设
        hypotheses_text = "无特定假设"
        if hypotheses:
            h_lines = []
            for h in hypotheses:
                status = h.get("status", "unverified")
                h_lines.append(f"- [{h.get('id')}] {h.get('content')} (状态: {status})")
            hypotheses_text = "\n".join(h_lines)

        prompt = LEGAL_SCOUT_PROMPT.format(
            query=query,
            section_title=section.get("title", ""),
            section_description=section.get("description", ""),
            search_results="\n".join(formatted_results)
        )

        try:
            response = await self.call_llm(
                system_prompt=LEGAL_SYSTEM_RULES,
                user_prompt=prompt,
                json_mode=True,
                temperature=0.2
            )
            result = self.parse_json_response(response)
            if result:
                return result
        except Exception as exc:
            self.logger.warning(f"Legal search analysis LLM failed, using fallback: {exc}")

        return self._fallback_search_analysis(query, section, results)

    def _fallback_search_analysis(
        self,
        query: str,
        section: Dict[str, Any],
        results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Deterministically extract legal sources and facts when the LLM is unavailable."""
        legal_sources = [
            normalize_legal_source(raw, index, default_source_type="unknown")
            for index, raw in enumerate(results[:20], start=1)
            if isinstance(raw, dict)
        ]
        extracted_facts = []
        key_entities = []
        for index, source in enumerate(legal_sources, start=1):
            text = source.get("quoted_text") or source.get("snippet") or source.get("title", "")
            if not text:
                continue
            extracted_facts.append({
                "content": text[:500],
                "source_name": source.get("issuing_body") or source.get("title") or "法律来源",
                "source_url": source.get("url", ""),
                "source_type": source.get("source_type", "unknown"),
                "credibility_score": source.get("confidence") or 0.65,
                "related_hypothesis": None,
                "hypothesis_support": "neutral",
                "data_points": [],
            })
            title = source.get("title", "")
            if title and title not in key_entities:
                key_entities.append(title)

        missing_info = []
        if not legal_sources:
            missing_info.append("未取得可结构化的法律检索结果。")

        return {
            "legal_sources": legal_sources,
            "extracted_facts": extracted_facts,
            "hypothesis_evidence": [],
            "entities_discovered": [
                {"name": entity, "type": "legal_source", "relations": [section.get("title", query)]}
                for entity in key_entities[:10]
            ],
            "key_insights": [
                f"已从“{section.get('title', '法律检索')}”检索结果中规范化 {len(legal_sources)} 条法律来源。"
            ] if legal_sources else [],
            "follow_up_queries": [],
            "source_tracing_queries": [],
            "missing_info": missing_info,
            "source_quality_assessment": "LLM 不可用，采用确定性结构化抽取；引用有效性仍需人工复核。",
        }

    async def deep_read_url(self, url: str, title: str, query: str) -> Optional[Dict]:
        """
        深度阅读网页内容

        TODO: 集成 Headless Browser（如 Playwright）实现真正的网页抓取
        目前使用简化版本
        """
        try:
            # 简化版：直接获取网页内容
            response = await asyncio.to_thread(
                requests.get,
                url,
                timeout=15,
                headers={'User-Agent': 'Mozilla/5.0'}
            )

            if response.status_code != 200:
                return None

            # 提取网页正文（去除 HTML 标签和噪音）
            content = self._extract_text_from_html(response.text, url)
            if not content or len(content) < 100:
                self.logger.warning(f"Extracted content too short for {url}")
                return None

            prompt = self.DEEP_READ_PROMPT.format(
                query=query,
                url=url,
                title=title,
                content=content
            )

            llm_response = await self.call_llm(
                system_prompt=LEGAL_SYSTEM_RULES,
                user_prompt=prompt,
                json_mode=True
            )

            return self.parse_json_response(llm_response)

        except Exception as e:
            self.logger.error(f"Deep read error for {url}: {e}")
            return None

    def _extract_text_from_html(self, html: str, url: str = "", max_length: int = 12000) -> str:
        """
        从 HTML 中提取纯文本正文

        使用多种策略提取，优先级：
        1. trafilatura - 专业的网页正文提取库（效果最好）
        2. BeautifulSoup - 通用 HTML 解析（备选）
        3. 简单正则 - 最后的备选方案

        Args:
            html: 原始 HTML 内容
            url: 网页 URL（用于 trafilatura 优化）
            max_length: 最大返回长度

        Returns:
            提取的纯文本
        """
        text = ""

        # 方法 1: 使用 trafilatura（效果最好）
        if TRAFILATURA_AVAILABLE:
            try:
                text = trafilatura.extract(
                    html,
                    url=url,
                    include_comments=False,
                    include_tables=True,
                    no_fallback=False,
                    favor_precision=True
                )
                if text and len(text) > 200:
                    self.logger.debug(f"Trafilatura extracted {len(text)} chars from {url}")
                    return text[:max_length]
            except Exception as e:
                self.logger.warning(f"Trafilatura extraction failed: {e}")

        # 方法 2: 使用 BeautifulSoup
        if BS4_AVAILABLE:
            try:
                soup = BeautifulSoup(html, 'lxml')

                # 移除无用标签
                for tag in soup(['script', 'style', 'nav', 'header', 'footer',
                                'aside', 'iframe', 'noscript', 'meta', 'link']):
                    tag.decompose()

                # 尝试找正文区域
                main_content = None
                for selector in ['article', 'main', '.content', '.article',
                                '#content', '#article', '.post', '.entry']:
                    main_content = soup.select_one(selector)
                    if main_content:
                        break

                if main_content:
                    text = main_content.get_text(separator='\n', strip=True)
                else:
                    # 找不到正文区域，提取 body
                    body = soup.find('body')
                    if body:
                        text = body.get_text(separator='\n', strip=True)
                    else:
                        text = soup.get_text(separator='\n', strip=True)

                if text and len(text) > 200:
                    # 清理多余空白
                    import re
                    text = re.sub(r'\n{3,}', '\n\n', text)
                    text = re.sub(r' {2,}', ' ', text)
                    self.logger.debug(f"BeautifulSoup extracted {len(text)} chars from {url}")
                    return text[:max_length]

            except Exception as e:
                self.logger.warning(f"BeautifulSoup extraction failed: {e}")

        # 方法 3: 简单正则（最后的备选）
        import re
        # 移除 script 和 style
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # 移除所有 HTML 标签
        text = re.sub(r'<[^>]+>', ' ', text)
        # 解码 HTML 实体
        text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&amp;', '&').replace('&quot;', '"')
        # 清理空白
        text = re.sub(r'\s+', ' ', text).strip()

        self.logger.debug(f"Regex extracted {len(text)} chars from {url}")
        return text[:max_length]

    def _compute_fact_fingerprint(self, content: str) -> str:
        """计算事实的语义指纹用于去重"""
        # 简化版：使用内容hash
        # TODO: 集成向量嵌入进行语义相似度比较
        import re
        # 提取数字和关键词作为指纹
        numbers = re.findall(r'\d+\.?\d*', content)
        keywords = re.findall(r'[\u4e00-\u9fa5]{2,4}', content)[:5]
        fingerprint = f"{','.join(numbers[:3])}|{','.join(keywords)}"
        return hashlib.md5(fingerprint.encode()).hexdigest()[:16]

    def _is_duplicate_fact(self, content: str, source_url: str) -> bool:
        """检查事实是否重复"""
        fingerprint = self._compute_fact_fingerprint(content)

        # 检查指纹是否已存在
        if fingerprint in self.fact_fingerprints:
            existing_url = self.fact_fingerprints[fingerprint]
            if existing_url == source_url:
                return True
            self.logger.debug(f"Duplicate fact detected: {content[:50]}...")
            return True

        # 保存指纹
        self.fact_fingerprints[fingerprint] = source_url
        return False

    def _update_knowledge_graph(self, state: ResearchState, entities: List[Dict]) -> None:
        """更新知识图谱"""
        graph = state.get("knowledge_graph", {"nodes": [], "edges": []})
        existing_nodes = {n.get("name") for n in graph["nodes"]}

        for entity in entities:
            name = entity.get("name", "")
            if not name or name in existing_nodes:
                continue

            # 添加节点
            graph["nodes"].append({
                "id": f"node_{len(graph['nodes'])}",
                "name": name,
                "type": entity.get("type", "unknown"),
                "discovered_at": datetime.now().isoformat()
            })
            existing_nodes.add(name)

            # 添加边（关系）
            for relation in entity.get("relations", []):
                # 简单解析关系
                graph["edges"].append({
                    "source": name,
                    "relation": relation,
                    "discovered_at": datetime.now().isoformat()
                })

        state["knowledge_graph"] = graph

    def _update_hypothesis_status(self, state: ResearchState, evidence: List[Dict]) -> None:
        """根据证据更新假设状态"""
        hypotheses = state.get("hypotheses", [])

        for ev in evidence:
            h_id = ev.get("hypothesis_id", "")
            ev_type = ev.get("evidence_type", "")
            ev_summary = ev.get("evidence_summary", "")

            for h in hypotheses:
                if h.get("id") == h_id:
                    if ev_type == "supports":
                        h["evidence_for"].append(ev_summary)
                        if len(h["evidence_for"]) >= 2:
                            h["status"] = "supported"
                    elif ev_type == "refutes":
                        h["evidence_against"].append(ev_summary)
                        if len(h["evidence_against"]) >= 2:
                            h["status"] = "refuted"
                    else:
                        if h.get("status") == "unverified":
                            h["status"] = "partially_supported"
                    break

        state["hypotheses"] = hypotheses


LegalScout = DeepScout
