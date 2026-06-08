# Legal Agent Refactor Log

This project directory is not a git repository, so this log records the first-stage legal risk DeepResearch refactor steps.

## 2026-06-06

- Started first-stage backend/domain-layer refactor for legal risk DeepResearch Agent.
- Scope: keep `/research/stream`, SSE events, checkpoint, session, authentication, frontend, and knowledge-base integrations compatible.
- Baseline finding: `python3 -m compileall app` passes; local environment lacks the `python` command and some runtime packages (`fastapi`, `llama_index`), so component tests use `python3` and avoid external services.
- Added legal config, schemas, risk scoring, citation verification, centralized legal prompts, and a no-external-service component test script.
- Extended DeepResearch V2 state with legal defaults for checkpoint compatibility.
- Legalized Architect, Scout, DataAnalyst, Writer, and Critic while preserving their original class names; added EvidenceExtractor.
- Defaulted CodeWizard/code execution to skipped in legal mode.
- Updated graph orchestration to run EvidenceExtractor before DataAnalyst and keep existing phase names.
- Verification passed: `python3 -m compileall app`, `PYTHONPATH=. python3 app/scripts/test_legal_research_components.py`, and internal no-search V2 SSE smoke test ending with `research_complete` and `[DONE]`.

## Phase Completion Notes

- Phase 0: Confirmed the project directory is not a git repository; this log is the change record.
- Phase 1-6: Added legal risk config, legal schemas, risk scoring, citation verification, and centralized legal prompts.
- Phase 7-10: Legalized Architect, Scout, EvidenceExtractor, and DataAnalyst while preserving class/file names and SSE queue behavior.
- Phase 11: CodeWizard remains available for compatibility but legal mode defaults to skipped code execution and template ECharts.
- Phase 12-13: Writer now produces a legal risk report skeleton with mandatory disclaimer; Critic performs deterministic legal quality checks and blocks unsupported major/high-risk conclusions from direct approval.
- Phase 14-16: Graph keeps existing phases, runs EvidenceExtractor before DataAnalyst, preserves `/research/stream` request/SSE compatibility, and backfills legal fields on checkpoint save/load/full-load.
- Phase 17-19: Component script now covers defaults, scoring, citation checks, placeholder detection, legal source normalization, disclaimer generation, CodeWizard legal defaults, allowed phase names, and unsupported major-risk rejection.

Latest verification:

- `/tmp/industry_legal_test_venv/bin/python -m compileall app`
- `PYTHONPATH=. /tmp/industry_legal_test_venv/bin/python app/scripts/test_legal_research_components.py`
- `PYTHONPATH=app:. /tmp/industry_legal_test_venv/bin/python -c "from service.deep_research_v2.graph import DeepResearchGraph; from service.deep_research_v2.service import DeepResearchV2Service; from router import research_router; print('imports ok')"`
- `rg -n "顶级投行|市场规模|市场份额|产业链|执行.*Python" app/service/deep_research_v2` returned no matches.

Full-flow verification:

- Docker services were available through `DOCKER_HOST=unix:///mnt/wsl/docker-desktop/shared-sockets/host-services/docker.proxy.sock`; postgres, redis, milvus, minio, and related services were running and healthy.
- Added `app/scripts/test_legal_agent_full_flow.py`, a deterministic fixture-backed full DeepResearchGraph run using explicit Civil Code articles and procurement contract clauses.
- Full-flow fixture result: emitted `research_complete`, covered phases `planning/researching/analyzing/writing/reviewing`, produced 74 events, 4 facts, 3 ECharts templates, quality score 10.0, and a 2708-character legal risk report at `/tmp/legal_agent_full_flow/legal_risk_deep_research_report.md`.
- The generated report included the mandatory disclaimer, evidence chain, human-review notice, overdue delivery, liquidated damages, loss compensation, termination-right, and remediation content.
- HTTP smoke result for `/hello`: returned 200 with the expected API status payload.
- HTTP smoke result for `/research/stream`: emitted 69 SSE events, `[DONE]`, no error event, 4 checkpoint saves, allowed phase names, 3 charts, and a report with the mandatory disclaimer.
- HTTP checkpoint full-load check confirmed legal fields are persisted/restored: `legal_sources`, `risk_items`, `evidence_chain`, `human_review_required`, and disclaimer-bearing `final_report`.
- Fixed checkpoint persistence to skip internal keys such as `_message_queue` and recursively JSON-normalize state before JSONB storage.
- Added deterministic fallbacks and deduplication improvements in DeepScout, EvidenceExtractor, and DataAnalyst so legal materials can still produce an evidence-linked risk report when LLM calls fail.
- External live LLM/search quality was not validated in this environment because the DashScope call returned an API-key error and BOCHA search key was unavailable.

Legal-only application narrowing:

- Backend app exposure was narrowed to legal-risk essentials: auth, sessions, legal knowledge bases, attachments, and research/checkpoint routes.
- Industry/news/bidding/database/memory/document/search/general-chat HTTP capabilities are no longer registered by `app_main.py`; their `/api/*` endpoints now return 404.
- Industry news scheduler startup/shutdown was removed from the app lifespan in legal-only mode.
- Frontend navigation was narrowed to legal risk home, new research, research history, and legal knowledge base.
- Frontend home and new-research pages were rewritten as legal-risk entry points; industry selector, industry cards, market search, hot news, bidding, database, memory, and general-chat entry points were removed.
- New frontend research sends through DeepResearch by default, even when no web/local search mode is selected.
- DeepScout stock/market-data enrichment was disabled, and remaining DeepResearch V2 examples/prompts were rewritten toward legal risk research.
- Verification passed after narrowing: backend compileall, frontend build, legal component test, fixture-backed legal full-flow test, `/api/research/stream` SSE smoke, `/api/chat/*` 404, and removed industry API endpoint 404 checks.

## 2026-06-07

- Added full DeepResearch V2 trace recording under `backend/runtime_traces/deep_research/`.
- Each graph run now writes trace metadata, graph events, LLM calls, final state, and per-agent input/output snapshots.
- Per-agent trace directories include `input_state.json`, `output_state.json`, `messages.jsonl`, and agent-attributed LLM calls when applicable.
- Integrated tracing into `DeepResearchGraph.run()` so normal `/research/stream` runs and batch runs both save subprocess input/output without changing SSE event types or phase names.
- Added secret-key sanitization for trace output and kept runtime trace/batch output directories ignored by `.gitignore`.
- Added `app/scripts/run_legal_30_question_batch.py` to extract the 30 legal-risk questions from `/root/sakura/learn/deep/2026年6月6日-30个法律风控问题.md`, run them with default concurrency 10, save reports/events/results, and validate trace completeness for all required agents.
- Live batch output: `backend/batch_outputs/legal_30_questions/20260607_005455`.
- Live batch verification: 30 questions extracted, concurrency 10, 30 passed, 0 failed, 30 reports, 30 event logs, 30 result JSON files, and all trace validations passed.
- Secret scan excluding `.env`, traces, and batch outputs returned no hard-coded Mimo/Bocha key or model/base-url values in backend code.
- Verification passed: `python3 -m compileall app`, `PYTHONPATH=app:. python3 app/scripts/test_legal_research_components.py`, `PYTHONPATH=app:. python3 app/scripts/test_legal_agent_full_flow.py`, and `python3 -m py_compile app/scripts/run_legal_30_question_batch.py`.

Tavily search integration:

- Added `app/tools/tavily_tool.py` with `perform_internet_search(...)` returning structured dictionaries and `internet_search.invoke(...)` returning agent-friendly text.
- Added `SEARCH_PROVIDER=tavily` and `TAVILY_API_KEY` support in environment/config files; actual keys remain only in `.env`.
- Changed DeepResearch V2 `DeepScout` web search to use Tavily by default, with Bocha retained only as a fallback when Tavily is unavailable or returns no results.
- Verified direct Tavily tool import/call, `internet_search.invoke`, and `DeepScout._execute_search`; returned results were marked with `search_provider=tavily`.
- Verification passed: `.venv/bin/python -m compileall app`, `PYTHONPATH=app:. .venv/bin/python app/scripts/test_legal_research_components.py`, and `PYTHONPATH=app:. .venv/bin/python app/scripts/test_legal_agent_full_flow.py`.
