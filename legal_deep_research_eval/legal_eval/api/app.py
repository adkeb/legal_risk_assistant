"""Standalone FastAPI app for legal evaluation.

Run from /root/sakura/learn/deep/legal_deep_research_eval:
    ../industry_information_assistant/backend/.venv/bin/python -m uvicorn legal_eval.api.app:app --port 8011
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from ..schemas import LegalEvalRequest
from ..service import LegalEvalService
from ..tools.result_store import EvalResultStoreTool


app = FastAPI(
    title="Independent Legal DeepResearch Eval API",
    description="Read-only post-processing evaluator for legal-risk DeepResearch reports.",
    version="1.0.0",
)

service = LegalEvalService()
store = EvalResultStoreTool()


@app.get("/hello")
async def hello() -> dict:
    return {"status": "success", "message": "legal eval api is ready"}


@app.post("/legal-eval/evaluate")
async def evaluate(request: LegalEvalRequest) -> dict:
    result = service.evaluate(request)
    return result.model_dump()


@app.post("/legal-eval/rule-only")
async def rule_only(request: LegalEvalRequest) -> dict:
    request.judge_mode = "rule_only"
    request.save_result = request.save_result
    result = service.evaluate(request)
    return result.model_dump()


@app.get("/legal-eval/results/{eval_id}")
async def get_result(eval_id: str) -> dict:
    result = store.load(eval_id)
    if not result:
        raise HTTPException(status_code=404, detail="eval result not found")
    return result
