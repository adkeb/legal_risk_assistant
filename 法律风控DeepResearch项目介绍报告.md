# 法律风控 DeepResearch Agent 项目介绍报告

## 一、项目整体背景

本项目位于 `/root/sakura/learn/deep/industry_information_assistant`，当前定位为“法律风控 DeepResearch Agent”。它不是单一聊天机器人，而是一个由 FastAPI 后端、React 前端、RAG/知识库、多 Agent 深度研究、报告生成、图表、知识图谱、checkpoint 恢复和 SSE 流式输出组成的复合系统。

项目最初偏“行业信息助手/行业金融研究”，后来将 DeepResearch V2 的领域层重构为法律风控方向。当前法律化改造的重点在后端 Agent 层、法律风控字段、法律提示词、风险评分、证据链核验和报告生成逻辑。接口、前端接入方式、认证、会话、知识库和 checkpoint 机制基本沿用原系统。

当前系统面向以下法律风控任务：

- 合同审查
- 企业法律尽调
- 法规解读
- 案件研判
- 行政处罚分析
- 合规差距分析
- 通用法律研究
- 证据链核验
- 法律风控报告生成

核心后端目录为：

```text
industry_information_assistant/backend/app/service/deep_research_v2
```

核心文件包括：

```text
graph.py                Agent 编排与 SSE 输出
service.py              DeepResearch V2 服务入口
state.py                全局 ResearchState
trace_recorder.py       Agent 运行轨迹记录
agents/                 各 Agent 实现
prompts/legal_prompts.py 法律提示词集中管理
```

## 二、项目使用的 Agent 及编排方式

### 2.1 Agent 列表

当前 DeepResearch V2 法律风控链路中实际使用 7 个 Agent。

| Agent 类名 | 法律化角色 | 文件 | 主要职责 |
|---|---|---|---|
| `ChiefArchitect` | 法律任务规划 Agent | `agents/architect.py` | 识别任务类型、法域、法律问题、事实假设、缺失事实和检索计划 |
| `DeepScout` | 法律检索 Agent | `agents/scout.py` | 检索法规、案例、处罚、合同、企业记录和本地知识库资料 |
| `EvidenceExtractor` | 证据抽取 Agent | `agents/evidence_extractor.py` | 抽取合同条款、义务、期限、证据链和未解析附件风险 |
| `DataAnalyst` | 法律风险分析 Agent | `agents/data_analyst.py` | 识别风险项、义务、整改任务，进行风险评分和图表/知识图谱生成 |
| `CodeWizard` | 代码/图表 Agent | `agents/wizard.py` | 旧版代码执行和图表生成 Agent；法律模式默认跳过代码执行 |
| `LeadWriter` | 法律报告生成 Agent | `agents/writer.py` | 生成法律风控 Markdown 报告，输出章节内容、引用和最终报告 |
| `CriticMaster` | 法律质量审查 Agent | `agents/critic.py` | 检查法域、证据链、免责声明、重大风险依据、人审触发等 |

为降低重构破坏风险，项目保留了旧类名，同时增加法律别名：

```python
LegalArchitect = ChiefArchitect
LegalEvidenceExtractor = EvidenceExtractor
LegalRiskAnalyst = DataAnalyst
LegalWriter = LeadWriter
LegalCriticMaster = CriticMaster
```

### 2.2 全局状态：ResearchState

所有 Agent 共享同一个 `ResearchState` 字典。该状态既保留原行业研究字段，也新增法律风控字段。

基础字段包括：

```text
query
session_id
phase
iteration
max_iterations
search_web
search_local
outline
facts
raw_sources
charts
final_report
references
critic_feedback
quality_score
pending_search_queries
```

法律风控字段包括：

```text
task_type
jurisdiction
legal_domains
parties
legal_questions
fact_assumptions
missing_facts
legal_sources
applicable_laws
case_sources
enforcement_sources
contract_clauses
risk_items
risk_scores
obligations
deadlines
remediation_tasks
evidence_chain
citation_checks
disclaimers
human_review_required
human_review_reasons
```

`ensure_legal_state_defaults()` 会为新状态和旧 checkpoint 自动补齐法律字段，避免旧 checkpoint 因缺字段报错。

### 2.3 实际编排方式

虽然 `graph.py` 中保留了 LangGraph 相关结构，但当前实际执行的是 `_run_simplified()` 手写异步流程。原因是项目要支持实时 SSE 输出；LangGraph 版本会更偏批处理，不适合当前前端逐步展示。

实际流程如下：

```text
research_start
  ↓
planning
  ChiefArchitect
  checkpoint
  ↓
researching
  DeepScout
  checkpoint
  ↓
analyzing
  EvidenceExtractor
  DataAnalyst
  CodeWizard
  checkpoint
  ↓
writing
  LeadWriter
  checkpoint
  ↓
reviewing
  CriticMaster
  ↓
  ├─ 若审核要求补充检索：
  │    re_researching
  │      DeepScout
  │      EvidenceExtractor
  │      DataAnalyst
  │      LeadWriter
  │
  ├─ 若审核要求文字修订：
  │    revising
  │      LeadWriter
  │
  └─ 若审核通过或达到最大迭代：
       completed
       research_complete
```

### 2.4 SSE 流式输出机制

每个 Agent 继承 `BaseAgent`，通过：

```python
BaseAgent.add_message(state, event_type, content)
```

将消息写入：

```python
state["_message_queue"]
```

`DeepResearchGraph._run_simplified()` 会持续读取该队列，并向前端输出 SSE 事件。前端据此展示：

- 阶段切换
- 研究步骤
- 搜索结果
- 知识图谱
- 图表
- 章节内容
- 报告草稿
- 审核反馈
- 最终报告

主要 SSE 事件类型包括：

```text
research_start
phase
research_step
thought
action
observation
outline
search_progress
search_results
knowledge_graph
charts
section_content
report_draft
review
critic_feedback
revision_complete
checkpoint_saved
research_complete
research_cancelled
error
```

## 三、每个 Agent 的方法、工具和数据产出

## 3.1 ChiefArchitect：法律任务规划 Agent

### 3.1.1 主要职责

`ChiefArchitect` 是规划阶段的入口 Agent，负责把用户原始问题转换为可执行的法律风控研究计划。

它主要完成：

- 判断法律任务类型
- 识别主要法域、次要法域、是否跨境
- 识别法律领域，例如合同、劳动、数据合规、公司治理等
- 提取当事方
- 拆解法律问题
- 形成事实假设
- 标记缺失事实
- 生成检索词
- 判断是否需要人工复核
- 生成默认法律报告大纲

### 3.1.2 主要方法

```text
process(state)
_initial_planning(state)
_check_revision(state)
_fallback_legal_plan(query)
_build_default_legal_outline(search_queries)
_convert_flat_to_outline(flat_result)
```

`process()` 根据 `state["phase"]` 分流：

- `init`：执行 `_initial_planning()`
- `reviewing`：执行 `_check_revision()`
- 其他阶段：直接返回 state

### 3.1.3 使用的工具和能力

```text
BaseAgent.call_llm()
BaseAgent.parse_json_response()
BaseAgent.add_message()
ensure_legal_state_defaults()
```

如果 LLM 调用失败，使用 `_fallback_legal_plan()` 生成确定性兜底规划。

### 3.1.4 主要写入的状态字段

```text
task_type
jurisdiction
legal_domains
parties
legal_questions
fact_assumptions
missing_facts
research_questions
pending_search_queries
hypotheses
key_entities
mind_map
knowledge_graph
human_review_required
human_review_reasons
outline
phase
```

## 3.2 DeepScout：法律检索 Agent

### 3.2.1 主要职责

`DeepScout` 是信息入口 Agent，负责通过网络搜索和本地知识库检索获取法律资料，并将结果结构化为后续 Agent 可用的法律来源和事实。

它主要检索：

- 法律
- 行政法规/部门规章/地方规则
- 司法解释
- 案例
- 裁判文书
- 行政处罚
- 合同
- 内部制度
- 监管指引
- 企业记录
- 新闻/舆情

### 3.2.2 主要方法

```text
process(state)
_supplementary_research(state)
_research_section(state, section)
_execute_search(query, count)
_execute_tavily_search(normalized_query, count)
_execute_bocha_search(normalized_query, count)
_execute_local_search(query, top_k)
_analyze_search_results(query, section, results, hypotheses)
_execute_deep_search(state, section_id, queries, search_type, hypotheses)
_analyze_deep_search_results(original_query, search_query, results, search_type, hypotheses)
_analyze_supplementary_results(original_query, search_query, results)
_fallback_search_analysis(query, section, results)
_append_legal_sources(state, sources, default_source_type)
_emit_search_results_event(state)
deep_read_url(url, title, query)
_extract_text_from_html(html, url, max_length)
_compute_fact_fingerprint(content)
_is_duplicate_fact(content, source_url)
_update_knowledge_graph(state, entities)
_update_hypothesis_status(state, evidence)
```

### 3.2.3 使用的工具和能力

网络搜索：

```text
Tavily: perform_internet_search()
Bocha: requests.post("https://api.bocha.cn/v1/web-search")
```

本地知识库：

```text
generate_embedding()
MilvusService.search()
```

网页正文抽取：

```text
trafilatura
BeautifulSoup
正则清洗
```

LLM 能力：

```text
BaseAgent.call_llm()
BaseAgent.parse_json_response()
```

结构化工具函数：

```text
infer_legal_source_type()
normalize_legal_source()
```

### 3.2.4 主要写入的状态字段

```text
legal_sources
raw_sources
facts
data_points
applicable_laws
case_sources
enforcement_sources
key_entities
knowledge_graph
insights
hypotheses
pending_search_queries
```

### 3.2.5 检索模式

DeepScout 根据 `state` 中搜索开关运行：

```text
search_web = True/False
search_local = True/False
```

当前前端默认发送：

```text
search_modes = ["web"]
```

如果两个搜索模式都未开启，DeepScout 不检索外部来源，后续分析会标记证据不足或需人工复核。

## 3.3 EvidenceExtractor：证据抽取 Agent

### 3.3.1 主要职责

`EvidenceExtractor` 负责从已经检索到的法律来源、事实和原始材料中抽取证据链、合同条款、义务和期限。

它特别关注：

- 合同条款原文
- 条款号
- 义务主体
- 履行期限
- 通知期限
- 风险信号
- 证据定位
- 附件是否真正解析

### 3.3.2 主要方法

```text
process(state)
_collect_materials(state)
_mark_unparsed_attachment(state)
_fallback_evidence(materials)
_extract_clause_no(text)
_infer_clause_title(text)
_extract_risk_signals(text)
_extract_obligations_from_text(text, source_id)
_extract_deadlines_from_text(text, source_id)
_merge_extraction_result(state, result)
_as_dict_list(value, text_key)
_as_string_list(value)
_append_unique_item(items, item, key_fields, id_field, id_prefix)
_append_unique_missing_fact(state, missing_fact)
_append_unique_reason(state, reason)
_complete_step(state)
```

### 3.3.3 使用的工具和能力

```text
BaseAgent.call_llm()
BaseAgent.parse_json_response()
BaseAgent.add_message()
正则表达式
has_unparsed_attachment_placeholder()
确定性 fallback 抽取
```

附件占位检测函数：

```python
has_unparsed_attachment_placeholder(text)
```

会识别：

```text
[PDF 文件:
[Word 文档:
[图片:
```

如果发现这类占位符，会触发：

```text
human_review_required = True
missing_facts += unparsed_attachment
```

### 3.3.4 主要写入的状态字段

```text
contract_clauses
obligations
deadlines
evidence_chain
missing_facts
human_review_required
human_review_reasons
```

## 3.4 DataAnalyst：法律风险分析 Agent

### 3.4.1 主要职责

`DataAnalyst` 在法律化后不再是行业市场数据分析师，而是法律风险分析 Agent。它负责识别法律风险、评分、生成整改任务和可视化。

它主要完成：

- 识别风险项
- 计算风险评分
- 生成风险等级
- 生成义务清单
- 生成期限清单
- 生成整改任务
- 生成 ECharts 风险图表
- 生成法律知识图谱

### 3.4.2 主要方法

```text
process(state)
_analyze_data(state)
_analyze_legal_risks(state)
_fallback_legal_risk_analysis(state)
_build_evidence_gap_risk(state)
_upsert_charts(existing_charts, new_charts)
_extend_unique_items(existing_items, new_items, key_fields)
```

模块级图表/图谱函数：

```text
build_risk_distribution_chart(risk_items)
build_risk_matrix_chart(risk_items)
build_obligation_deadline_chart(obligations, deadlines)
build_legal_knowledge_graph(state)
```

### 3.4.3 使用的工具和能力

```text
RiskScoringService.score_risk()
RiskScoringService.normalize_score()
BaseAgent.call_llm()
BaseAgent.parse_json_response()
BaseAgent.add_message()
ECharts 模板配置
确定性 fallback 风险识别
```

风险评分服务文件：

```text
backend/app/service/risk_scoring_service.py
```

评分权重：

```text
impact_score: 0.30
probability_score: 0.20
legal_certainty_score: 0.15
evidence_strength_score: 0.15
urgency_score: 0.10
remediation_difficulty_score: 0.10
```

风险等级映射：

```text
>= 4.2  重大风险
>= 3.4  高风险
>= 2.6  中风险
>= 1.8  低风险
<  1.8  提示项
```

### 3.4.4 主要写入的状态字段

```text
risk_items
risk_scores
obligations
deadlines
remediation_tasks
insights
charts
knowledge_graph
human_review_required
human_review_reasons
```

## 3.5 CodeWizard：代码/图表 Agent

### 3.5.1 当前实际作用

`CodeWizard` 是原 DeepResearch V2 中的数据代码执行 Agent。法律风控改造后保留它是为了兼容原流程，但当前默认不执行代码。

配置位置：

```text
backend/app/config/llm_config.py
```

当前默认：

```text
enable_code_execution = False
legal_chart_mode = "template"
```

因此 CodeWizard 当前运行时只会记录：

```text
法律风控模式默认关闭 LLM 生成代码执行，已使用模板图表。
```

### 3.5.2 主要方法

```text
process(state)
_analyze_data(state)
_generate_charts(state)
_generate_chart_code(topic, data, chart_type, title)
_execute_code(code)
_fix_code(code, error, stdout)
_clean_code(code)
_validate_code_safety(code)
```

### 3.5.3 使用的工具和能力

如果开启代码执行，CodeWizard 会使用：

```text
pandas
numpy
matplotlib
seaborn
base64
io
redirect_stdout
redirect_stderr
LLM 生成代码
LLM 修复代码
危险代码正则过滤
```

但当前法律模式下不会实际执行 LLM 生成代码。

### 3.5.4 主要写入的状态字段

当前法律模式主要写入：

```text
code_executions: [{"status": "skipped", "reason": "..."}]
```

并发送：

```text
research_step: code_execution_skipped
thought: 法律风控模式默认关闭代码执行
```

## 3.6 LeadWriter：法律报告生成 Agent

### 3.6.1 主要职责

`LeadWriter` 负责将前面各 Agent 产生的法域、法律来源、证据链、风险项、义务、期限和整改任务整合成最终法律风控报告。

当前主路径中，它主要使用确定性函数：

```python
build_legal_report_skeleton(state)
```

生成报告，而不是完全依赖 LLM 写整篇报告。

### 3.6.2 主要方法

```text
process(state)
_write_report(state)
build_legal_report_skeleton(state)
_split_legal_report_sections(report)
_content_for_section_title(state, title)
_normalize_section(section, index)
_write_section(state, section)
_synthesize_report(state)
_revise_report(state)
```

其中当前主流程主要使用：

```text
_write_report()
build_legal_report_skeleton()
_split_legal_report_sections()
_content_for_section_title()
_revise_report()
```

`_write_section()` 和 `_synthesize_report()` 仍保留 LLM 写作能力，但当前主路径没有优先使用它们。

### 3.6.3 使用的工具和能力

```text
LEGAL_DEFAULT_DISCLAIMER
确定性 Markdown 报告模板
BaseAgent.add_message()
引用来源 references 构造
章节内容 section_content 事件
报告草稿 report_draft 事件
```

### 3.6.4 报告默认结构

```text
法律风控分析报告
  重要提示
  一、执行摘要
  二、分析范围、事实与假设
  三、适用法域与法律依据
  四、风险识别与等级
  五、逐项法律分析
  六、义务清单与期限
  七、整改建议
  八、证据链与引用清单
  九、待人工复核事项
```

### 3.6.5 主要写入的状态字段

```text
final_report
draft_sections
references
outline.status
phase
```

## 3.7 CriticMaster：法律质量审查 Agent

### 3.7.1 主要职责

`CriticMaster` 是质量守门 Agent。当前主路径主要使用确定性规则审查，不依赖 LLM 审查。

它重点检查：

- 是否识别主要法域
- 是否包含“不构成正式法律意见”免责声明
- 是否形成法律来源
- 是否识别风险项
- 重大/高风险是否绑定证据或法律依据
- 风险项是否有评分
- 引用链是否完整
- 是否存在绝对化法律结论
- 是否存在未解析附件
- 是否触发人工复核

### 3.7.2 主要方法

```text
process(state)
_run_legal_quality_checks(state)
_issue(issue_type, severity, description, suggestion, requires_new_search)
_decide_legal_verdict(state, issues)
_build_pending_search_queries(state, issues)
normalize_critic_verdict(verdict)
_analyze_issues_for_routing(review_result)
_review_content(state)
final_check(state)
```

当前主流程中主要使用：

```text
process()
_run_legal_quality_checks()
_decide_legal_verdict()
_build_pending_search_queries()
```

`_review_content()` 和 `final_check()` 是保留的 LLM 审查能力，但当前主路径未优先调用。

### 3.7.3 使用的工具和能力

```text
CitationVerifierService.verify_risk_items()
BaseAgent.add_message()
确定性规则检查
```

引用核验服务文件：

```text
backend/app/service/citation_verifier_service.py
```

它会检查：

```text
risk_items[].evidence_ids 是否存在于 evidence_chain[].evidence_id
risk_items[].legal_basis_ids 是否存在于 legal_sources[].source_id
```

### 3.7.4 Verdict 逻辑

审查结果会归一化为：

```text
approved
needs_research
needs_revision
human_review_required
```

路由逻辑：

```text
无问题：
  human_review_required 为 true → human_review_required
  否则 → approved

存在 requires_new_search 的问题：
  → needs_research

human_review_required 且 quality_score >= 8：
  → human_review_required

其他：
  → needs_revision
```

### 3.7.5 主要写入的状态字段

```text
citation_checks
critic_feedback
unresolved_issues
quality_score
phase
pending_search_queries
human_review_required
human_review_reasons
```

## 四、每个 Agent 的提示词

提示词集中在：

```text
backend/app/service/deep_research_v2/prompts/legal_prompts.py
```

此外，部分 Agent 文件中仍保留旧版或备用 Prompt。

## 4.1 全局法律系统提示词：LEGAL_SYSTEM_RULES

适用 Agent：

```text
ChiefArchitect
DeepScout
EvidenceExtractor
DataAnalyst
```

核心内容如下：

```text
你是法律风控辅助分析系统，不是执业律师替代品。

必须遵守：
1. 区分事实、假设、法律依据、分析推理和建议。
2. 必须识别法域，不能跨法域混用规则。
3. 关键结论必须尽量引用法规、案例、合同条款、处罚文书、内部制度或数据库记录。
4. 没有依据的内容必须标记为“待核验”或“需人工复核”。
5. 不得伪造法条、案例、案号、处罚文书号、监管文件名称。
6. 不得输出保证性、绝对化法律结论。
7. 涉及重大风险、跨境、多法域、刑事、行政处罚、数据出境、上市公司披露等事项，应标记 human_review_required。
8. 最终报告必须包含免责声明和证据链。
9. 只输出 JSON，不要输出 Markdown 代码块；如果无法判断，用 unknown/null/[]，不要编造。
```

## 4.2 ChiefArchitect 的提示词

### 4.2.1 LEGAL_ARCHITECT_PROMPT

用途：法律任务规划。

核心要求：

```text
请对用户法律风控问题进行任务规划。

用户问题：
{query}

输出 JSON：
{
  "task_type": "contract_review/due_diligence/regulation_interpretation/case_analysis/enforcement_analysis/compliance_gap_analysis/general_legal_research",
  "jurisdiction": {"primary": "中国大陆", "secondary": [], "cross_border": false, "confidence": 0.0, "missing_info": []},
  "legal_domains": ["contract"],
  "parties": [{"name": "unknown", "role": "unknown"}],
  "legal_questions": [{"id": "q_001", "question": "需要回答的法律问题", "priority": "high"}],
  "fact_assumptions": [{"id": "fa_001", "content": "基于用户问题形成的事实假设", "confidence": 0.0}],
  "missing_facts": [{"type": "missing_info", "description": "缺失事实"}],
  "pending_search_queries": ["法规/案例/处罚/合同条款检索词"],
  "human_review_required": false,
  "human_review_reasons": []
}
```

### 4.2.2 ChiefArchitect 内部 PLANNING_PROMPT

文件 `architect.py` 中还保留了 `PLANNING_PROMPT`，要求为法律风控课题生成研究大纲和待验证法律问题。它的核心输出字段包括：

```text
hypothesis_1
hypothesis_2
hypothesis_3
sec_1_title / sec_1_desc / sec_1_query
...
sec_6_title / sec_6_desc / sec_6_query
questions
```

但当前法律主路径主要使用 `LEGAL_ARCHITECT_PROMPT` 加默认大纲函数 `_build_default_legal_outline()`。

### 4.2.3 REVISION_PROMPT

用途：根据研究进展动态调整大纲。

核心输出：

```text
needs_revision
revision_reason
revised_outline
new_search_queries
```

## 4.3 DeepScout 的提示词

### 4.3.1 LEGAL_SCOUT_PROMPT

用途：从搜索结果中抽取法律依据、案例、处罚、合同或企业风险信息。

核心内容：

```text
请从搜索结果中抽取法律依据、案例、处罚、合同或企业风险信息。

研究问题：{query}
当前检索目标：{section_title} - {section_description}
搜索结果：
{search_results}

输出 JSON：
{
  "legal_sources": [
    {
      "source_type": "law/regulation/judicial_interpretation/case/court_decision/enforcement/contract/internal_policy/regulator_guidance/company_record/news",
      "title": "来源标题",
      "issuing_body": "发布机关或来源主体",
      "authority_level": "法律/行政法规/部门规章/司法解释/合同/unknown",
      "jurisdiction": "中国大陆",
      "article_no": "条文或定位",
      "validity_status": "effective/expired/unknown",
      "url": "URL",
      "quoted_text": "可核验原文片段",
      "confidence": 0.0
    }
  ],
  "facts": [
    {
      "content": "可验证事实",
      "source_name": "来源",
      "source_url": "URL",
      "source_type": "law",
      "credibility_score": 0.0
    }
  ],
  "key_entities": ["主体/法规/案件/风险"],
  "follow_up_queries": ["补充检索词"],
  "missing_info": ["仍缺失的信息"]
}
```

### 4.3.2 SEARCH_ANALYSIS_PROMPT

定义在 `scout.py`。用途是分析搜索结果、验证法律风控假设、提取结构化事实。

核心输出：

```text
extracted_facts
hypothesis_evidence
entities_discovered
key_insights
follow_up_queries
source_tracing_queries
missing_info
source_quality_assessment
```

其中 `extracted_facts` 包含：

```text
content
source_name
source_url
source_type
credibility_score
data_points
needs_verification
importance
related_hypothesis
hypothesis_support
```

### 4.3.3 DEEP_READ_PROMPT

用途：深度阅读网页长文本。

核心要求：

```text
深度阅读文档，提取与研究问题相关的可核验法律信息。
不得伪造法条、案号、处罚文书号或合同正文。
```

核心输出：

```text
summary
legal_sources
extracted_facts
quotes
related_entities
publication_date
authority_assessment
```

### 4.3.4 补充检索 Prompt

`_analyze_supplementary_results()` 中有内联 Prompt，要求针对审核发现的信息缺失，从补充搜索结果中提取：

```text
legal_sources
extracted_facts
key_findings
```

### 4.3.5 递归深搜 Prompt

`_analyze_deep_search_results()` 中有内联 Prompt，要求：

```text
1. 从搜索结果中提取法规、司法解释、案例、裁判文书、行政处罚、合同条款、内部制度或企业记录。
2. 为每条风险相关事实保留 source_id/source_url/quoted_text，缺少依据时标记待核验。
3. 如果发现引用了其他法律依据或证据原文，生成进一步追溯查询。
```

核心输出：

```text
legal_sources
extracted_facts
further_tracing_queries
source_reliability
```

## 4.4 EvidenceExtractor 的提示词

### 4.4.1 EVIDENCE_EXTRACTOR_PROMPT

用途：基于已有真实文本抽取合同条款、义务、期限和证据链。

核心内容：

```text
请基于已有真实文本抽取合同条款、义务、期限和证据链。
不得从附件占位文本中臆造正文。

用户问题：{query}
材料：
{materials}

输出 JSON：
{
  "contract_clauses": [],
  "obligations": [],
  "deadlines": [],
  "evidence_chain": [
    {
      "source_type": "law/contract/case/enforcement/news",
      "source_id": "source_001",
      "locator": "定位",
      "quote": "原文片段",
      "confidence": 0.0
    }
  ],
  "missing_facts": [],
  "human_review_required": false,
  "human_review_reasons": []
}
```

如果 LLM 失败，它会用 `_fallback_evidence()` 从文本中规则抽取：

- 证据片段
- 合同条款
- 交付义务
- 验收义务
- 赔偿/违约责任义务
- 日期或期限

## 4.5 DataAnalyst 的提示词

### 4.5.1 LEGAL_RISK_ANALYST_PROMPT

用途：识别法律风险、合规义务和整改任务。

核心内容：

```text
请识别法律风险、合规义务和整改任务。

用户问题：{query}
法律依据：{legal_sources}
证据链：{evidence_chain}
合同条款：{contract_clauses}
事实：{facts}

输出 JSON：
{
  "risk_items": [
    {
      "risk_id": "risk_001",
      "title": "风险标题",
      "risk_category": "contract_clause",
      "description": "风险说明",
      "impact_score": 3,
      "probability_score": 3,
      "legal_certainty_score": 3,
      "evidence_strength_score": 3,
      "urgency_score": 3,
      "remediation_difficulty_score": 3,
      "legal_basis_ids": [],
      "evidence_ids": [],
      "recommended_action": "整改建议",
      "human_review_required": false
    }
  ],
  "obligations": [],
  "deadlines": [],
  "remediation_tasks": [],
  "insights": []
}
```

### 4.5.2 DATA_EXTRACTION_PROMPT

旧版保留 Prompt，用于从文本中提取结构化数据点。当前法律主路径较少使用。

核心输出：

```text
data_points
time_series
distributions
insights
```

### 4.5.3 KNOWLEDGE_GRAPH_PROMPT

旧版保留 Prompt，用于从文本中提取实体关系。当前法律主路径主要使用确定性 `build_legal_knowledge_graph()`。

核心输出：

```text
nodes
edges
```

### 4.5.4 CHART_GENERATION_PROMPT

旧版保留 Prompt，用于让 LLM 生成 ECharts 配置。当前法律主路径主要用确定性模板：

```text
风险等级分布
风险矩阵
义务与期限清单
```

## 4.6 CodeWizard 的提示词

当前法律模式默认跳过代码执行，因此这些 Prompt 保留但通常不触发。

### 4.6.1 ANALYSIS_PROMPT

用途：让模型生成 Python 数据分析和可视化代码。

核心规则：

```text
禁止使用反斜杠续行
只选取关键 5-10 个数据点
使用列字典格式定义数据
创建 DataFrame 后必须执行类型转换
禁止 import 语句
已预定义 pd, np, plt, sns
生成高质量商业图表
输出 JSON，包含 analysis_plan、code、expected_outputs
```

### 4.6.2 CHART_PROMPT

用途：生成特定图表代码。

核心规则：

```text
禁止反斜杠续行
不要写 import
使用标准字典格式定义数据
图表尺寸 12x7 dpi=200
使用 seaborn 主题
保存 chart.png
输出 code 和 chart_description
```

### 4.6.3 CODE_FIX_PROMPT

用途：修复执行失败的 Python 代码。

它根据错误类型进行修复：

```text
could not convert string to float
SyntaxError
KeyError
TypeError
```

输出：

```text
error_analysis
fix_description
fixed_code
```

### 4.6.4 WORDCLOUD_PROMPT

用途：生成词云图代码。

### 4.6.5 SANKEY_PROMPT

用途：生成桑基图或流向图配置。

## 4.7 LeadWriter 的提示词

当前主路径主要用确定性报告骨架，不优先调用 LLM 写整篇报告。但文件中仍保留写作 Prompt。

### 4.7.1 LEGAL_WRITER_PROMPT

集中定义在 `legal_prompts.py`。

核心内容：

```text
请生成法律风控分析报告，必须包含免责声明、事实与假设、适用法域、法律依据、风险等级、整改建议、证据链和人工复核事项。
每个重大风险结论必须引用 risk_items 中的 legal_basis_ids 或 evidence_ids；缺证据时写“待核验”或“需人工复核”。
```

### 4.7.2 SECTION_WRITING_PROMPT

用途：撰写单个章节。

核心要求：

```text
专业性：使用法律风控术语，区分事实、假设、依据、分析和建议
逻辑性：风险结论必须说明事实基础、适用依据和推理边界
证据支撑：关键观点必须有证据链、法律来源或明确标记“待核验”
引用规范：使用可点击链接格式
图表整合：合适位置插入图表引用
字数控制：500-1000 字
不要重复标题
```

输出：

```text
content
key_points
citations
suggested_improvements
```

### 4.7.3 SYNTHESIS_PROMPT

用途：整合完整法律风控报告。

核心要求：

```text
撰写法律风控执行摘要
整合各章节
确保事实、假设、法律依据、风险分析和建议边界清楚
缺少证据链的结论标记“待核验”或“需人工复核”
整理证据链与引用列表
必须包含“不构成正式法律意见”免责声明
必须包含事实与假设、适用法域、风险等级、整改建议、证据链和人工复核事项
```

输出：

```text
executive_summary
full_report
conclusions
outlook
references
```

### 4.7.4 REVISION_PROMPT

用途：根据审核反馈修订报告。

核心原则：

```text
针对性修改
补充来源
修正事实错误或逻辑漏洞
保持整体风格一致
```

输出：

```text
revised_content
changes_made
addressed_issues
unable_to_address
```

## 4.8 CriticMaster 的提示词

当前主路径主要使用确定性审查函数 `_run_legal_quality_checks()`，但文件中仍保留 LLM 审查 Prompt。

### 4.8.1 LEGAL_CRITIC_PROMPT

集中定义在 `legal_prompts.py`。

核心内容：

```text
请从法律质量角度审查报告：法域、依据、证据链、风险评分、免责声明、绝对化结论、缺失事实、人工复核触发和 citation_checks。
无证据重大结论、缺免责声明或附件未解析直接审查时，不得 approved。
```

### 4.8.2 REVIEW_PROMPT

用途：让 LLM 作为严苛法律风控质量审核专家审查报告。

审核原则：

```text
零容忍幻觉：不得伪造法条、案号、处罚文书号、合同条款或来源
证据闭环：重大/高风险结论必须绑定 evidence_ids 或 legal_basis_ids
法域一致：必须识别主要法域，不能跨法域混用规则
有效性提示：法规、案例、处罚、合同依据的有效性或真实性未知时必须标记
边界完整：必须包含免责声明、缺失事实、待核验事项和人工复核提示
```

输出：

```text
overall_assessment:
  quality_score
  verdict
  summary

issues:
  id
  target_section
  issue_type
  severity
  location
  description
  evidence
  suggestion
  requires_new_search
  search_query

citation_check_results
missing_aspects
strength_points
```

### 4.8.3 FINAL_CHECK_PROMPT

用途：最终质量把关，检查修订后的报告是否解决之前问题。

输出：

```text
resolved_issues
unresolved_issues
new_issues
final_verdict
final_score
publication_readiness
final_comments
```

## 五、Agent 之间的数据流

### 5.1 规划到检索

`ChiefArchitect` 生成：

```text
outline
legal_questions
pending_search_queries
jurisdiction
legal_domains
missing_facts
```

`DeepScout` 读取这些字段，决定搜索章节和搜索词。

### 5.2 检索到证据抽取

`DeepScout` 生成：

```text
legal_sources
facts
raw_sources
applicable_laws
case_sources
enforcement_sources
```

`EvidenceExtractor` 从这些字段收集材料，生成：

```text
contract_clauses
obligations
deadlines
evidence_chain
```

### 5.3 证据抽取到风险分析

`DataAnalyst` 读取：

```text
legal_sources
evidence_chain
contract_clauses
facts
```

生成：

```text
risk_items
risk_scores
remediation_tasks
charts
knowledge_graph
```

### 5.4 风险分析到报告生成

`LeadWriter` 读取：

```text
query
jurisdiction
risk_items
legal_sources
evidence_chain
obligations
deadlines
remediation_tasks
missing_facts
human_review_reasons
```

生成：

```text
final_report
draft_sections
references
```

### 5.5 报告生成到质量审查

`CriticMaster` 读取：

```text
final_report
legal_sources
risk_items
evidence_chain
jurisdiction
missing_facts
```

生成：

```text
citation_checks
critic_feedback
quality_score
unresolved_issues
pending_search_queries
phase
```

如果发现需要补充来源的问题，流程回到 `DeepScout`；如果只需文字修订，流程回到 `LeadWriter`。

## 六、当前项目实现中的重要边界

1. 当前实际编排是手写 `_run_simplified()`，不是完整 LangGraph 执行。

2. CodeWizard 保留旧能力，但法律模式默认关闭代码执行。

3. LeadWriter 当前主路径主要使用确定性报告骨架，而不是 LLM 自由生成整篇报告。

4. CriticMaster 当前主路径主要使用确定性规则审查，而不是 LLM 审查。

5. 前端上传附件虽然存在，但 DeepResearch 请求当前没有把 `attachmentIds` 传给后端研究接口；普通附件和知识库文档是两条链路。

6. PDF/Word/图片附件在普通附件路由中目前只产生占位文本，证据抽取和 Critic 会将其视为需人工复核。

7. 本地知识库链路依赖 DocMind、Embedding、Milvus；只有开启 `search_local` 时 DeepScout 才会尝试本地检索。

8. 网络搜索默认 Tavily，Bocha 只是兜底。

9. 法律提示词强调“不得伪造法条、案例、案号、处罚文书号”，但最终质量仍取决于检索来源、LLM 抽取质量和证据链核验。

## 七、核心文件索引

```text
backend/app/service/deep_research_v2/graph.py
backend/app/service/deep_research_v2/service.py
backend/app/service/deep_research_v2/state.py
backend/app/service/deep_research_v2/trace_recorder.py

backend/app/service/deep_research_v2/agents/base.py
backend/app/service/deep_research_v2/agents/architect.py
backend/app/service/deep_research_v2/agents/scout.py
backend/app/service/deep_research_v2/agents/evidence_extractor.py
backend/app/service/deep_research_v2/agents/data_analyst.py
backend/app/service/deep_research_v2/agents/wizard.py
backend/app/service/deep_research_v2/agents/writer.py
backend/app/service/deep_research_v2/agents/critic.py

backend/app/service/deep_research_v2/prompts/legal_prompts.py
backend/app/config/legal_risk_config.py
backend/app/config/llm_config.py
backend/app/service/risk_scoring_service.py
backend/app/service/citation_verifier_service.py
backend/app/service/checkpoint_service.py
backend/app/router/research_router.py
```
