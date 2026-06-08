# Independent Legal DeepResearch Eval

This directory contains a standalone, read-only evaluation system for legal-risk
DeepResearch reports produced by `industry_information_assistant`.

It does not register routers, services, scripts, database tables, or outputs
inside the original project. Existing reports, events, traces, and final states
are consumed as input artifacts only.

## Quick Checks

```bash
/root/sakura/learn/deep/industry_information_assistant/backend/.venv/bin/python \
  -m compileall /root/sakura/learn/deep/legal_deep_research_eval

/root/sakura/learn/deep/industry_information_assistant/backend/.venv/bin/python \
  /root/sakura/learn/deep/legal_deep_research_eval/scripts/test_legal_eval_components.py
```

## CLI Examples

```bash
# Export benchmark JSONL from the 30-question markdown bank.
/root/sakura/learn/deep/industry_information_assistant/backend/.venv/bin/python \
  /root/sakura/learn/deep/legal_deep_research_eval/scripts/run_legal_eval.py export-tasks

# Evaluate one existing batch result.
/root/sakura/learn/deep/industry_information_assistant/backend/.venv/bin/python \
  /root/sakura/learn/deep/legal_deep_research_eval/scripts/run_legal_eval.py evaluate \
  --batch-result-path /root/sakura/learn/deep/industry_information_assistant/backend/batch_outputs/legal_30_questions/20260607_005455/results/EASY_01.json \
  --judge-mode mock

# Batch evaluate a few reports.
/root/sakura/learn/deep/industry_information_assistant/backend/.venv/bin/python \
  /root/sakura/learn/deep/legal_deep_research_eval/scripts/run_legal_eval.py batch \
  --batch-dir /root/sakura/learn/deep/industry_information_assistant/backend/batch_outputs/legal_30_questions/20260607_005455 \
  --limit 3
```

## API

```bash
cd /root/sakura/learn/deep/legal_deep_research_eval
/root/sakura/learn/deep/industry_information_assistant/backend/.venv/bin/python \
  -m uvicorn legal_eval.api.app:app --host 127.0.0.1 --port 8011
```
