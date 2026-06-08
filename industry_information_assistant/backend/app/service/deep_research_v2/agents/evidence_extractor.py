# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Legal evidence extraction agent for DeepResearch V2."""

import re
import uuid
from typing import Dict, Any, List

from .base import BaseAgent
from ..state import ResearchState, ensure_legal_state_defaults
from ..prompts.legal_prompts import LEGAL_SYSTEM_RULES, EVIDENCE_EXTRACTOR_PROMPT


def has_unparsed_attachment_placeholder(text: str) -> bool:
    """Detect attachment placeholders that are not real document text."""
    markers = ["[PDF 文件:", "[Word 文档:", "[图片:"]
    return any(marker in (text or "") for marker in markers)


class EvidenceExtractor(BaseAgent):
    """Extract legal evidence, clauses, obligations, and deadlines."""

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = ""):
        super().__init__(
            name="EvidenceExtractor",
            role="证据抽取专家",
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            model=model
        )

    async def process(self, state: ResearchState) -> ResearchState:
        ensure_legal_state_defaults(state)
        self.add_message(state, "research_step", {
            "step_id": f"step_evidence_{uuid.uuid4().hex[:8]}",
            "step_type": "evidence_extraction",
            "title": "证据抽取",
            "subtitle": "抽取条款、义务、期限和证据链",
            "status": "running",
            "stats": {}
        })
        self.add_message(state, "thought", {
            "agent": self.name,
            "content": "正在从已检索资料和本地片段中抽取法律证据链..."
        })

        materials = self._collect_materials(state)
        combined_text = "\n".join(item.get("text", "") for item in materials)
        if has_unparsed_attachment_placeholder(combined_text):
            self._mark_unparsed_attachment(state)

        if not materials:
            self._append_unique_missing_fact(state, {
                "type": "no_source_text",
                "description": "未检索到可用于证据抽取的真实文本。"
            })
            state["human_review_required"] = True
            self._append_unique_reason(state, "缺少可核验文本，无法完成证据链抽取。")
            self._complete_step(state)
            return state

        result: Dict[str, Any] = {}
        try:
            response = await self.call_llm(
                system_prompt=LEGAL_SYSTEM_RULES,
                user_prompt=EVIDENCE_EXTRACTOR_PROMPT.format(
                    query=state.get("query", ""),
                    materials="\n\n".join(item.get("text", "")[:1200] for item in materials[:12])
                ),
                json_mode=True,
                temperature=0.2,
                max_tokens=8000
            )
            result = self.parse_json_response(response)
        except Exception as exc:
            self.logger.warning(f"Evidence extraction LLM failed, using deterministic fallback: {exc}")

        if not result:
            result = self._fallback_evidence(materials)

        self._merge_extraction_result(state, result)
        self._complete_step(state)
        return state

    def _collect_materials(self, state: ResearchState) -> List[Dict[str, str]]:
        materials: List[Dict[str, str]] = []
        seen = set()

        def append_material(source_id: str, source_type: str, text: str) -> None:
            if not text:
                return
            key = text[:300]
            if key in seen:
                return
            seen.add(key)
            materials.append({
                "source_id": source_id,
                "source_type": source_type,
                "text": text,
            })

        for source in state.get("legal_sources", []):
            text = source.get("quoted_text") or source.get("snippet") or ""
            append_material(
                source.get("source_id", ""),
                source.get("source_type", "unknown"),
                f"{source.get('title', '')}\n{text}" if text else "",
            )
        for fact in state.get("facts", []):
            text = fact.get("content", "")
            append_material(
                fact.get("source_url") or fact.get("id", ""),
                fact.get("source_type", "unknown"),
                text,
            )
        for raw in state.get("raw_sources", []):
            text = raw.get("content") or raw.get("summary") or raw.get("snippet") or ""
            append_material(
                raw.get("source_id") or raw.get("url", ""),
                raw.get("source_type", "unknown"),
                text,
            )
        return materials

    def _mark_unparsed_attachment(self, state: ResearchState) -> None:
        state["human_review_required"] = True
        self._append_unique_reason(state, "上传附件可能未完成正文解析，无法直接完成合同或案件材料审查。")
        self._append_unique_missing_fact(state, {
            "type": "unparsed_attachment",
            "description": "附件正文未解析，仅检测到占位文本。"
        })

    def _fallback_evidence(self, materials: List[Dict[str, str]]) -> Dict[str, Any]:
        evidence_chain = []
        contract_clauses = []
        obligations = []
        deadlines = []
        for index, item in enumerate(materials[:20], start=1):
            quote = item.get("text", "").strip()
            if not quote:
                continue
            source_type = item.get("source_type", "unknown")
            source_id = item.get("source_id", "")
            evidence_chain.append({
                "source_type": source_type,
                "source_id": source_id,
                "locator": "检索片段",
                "quote": quote[:300],
                "confidence": 0.5,
            })
            if source_type == "contract" or any(term in quote for term in ["合同", "条款", "卖方", "买方", "交付", "违约金", "解除权"]):
                clause_type = "delivery" if "交付" in quote else "liability" if any(term in quote for term in ["违约金", "赔偿", "责任"]) else "general"
                contract_clauses.append({
                    "document_id": source_id,
                    "clause_no": self._extract_clause_no(quote),
                    "title": self._infer_clause_title(quote),
                    "text": quote[:800],
                    "clause_type": clause_type,
                    "risk_signals": self._extract_risk_signals(quote),
                })
            obligations.extend(self._extract_obligations_from_text(quote, source_id))
            deadlines.extend(self._extract_deadlines_from_text(quote, source_id))
        return {
            "contract_clauses": contract_clauses[:20],
            "obligations": obligations[:20],
            "deadlines": deadlines[:20],
            "evidence_chain": evidence_chain,
            "missing_facts": [],
            "human_review_required": False,
            "human_review_reasons": [],
        }

    def _extract_clause_no(self, text: str) -> str:
        match = re.search(r"(第[一二三四五六七八九十百\d]+条)", text)
        return match.group(1) if match else ""

    def _infer_clause_title(self, text: str) -> str:
        if "逾期" in text or "迟延" in text or "交付" in text:
            return "交付与逾期责任条款"
        if "违约金" in text or "赔偿" in text:
            return "违约责任与损失赔偿条款"
        if "解除" in text:
            return "解除权条款"
        if "验收" in text:
            return "验收条款"
        return "合同条款"

    def _extract_risk_signals(self, text: str) -> List[str]:
        signals = []
        if "仅" in text and any(term in text for term in ["退还", "退款", "货款"]):
            signals.append("救济方式可能过窄")
        if "不承担" in text and any(term in text for term in ["违约金", "赔偿", "责任"]):
            signals.append("违约责任可能被过度限制")
        if "违约金" not in text and "逾期" in text:
            signals.append("逾期违约金约定不足")
        if "解除" not in text and "逾期" in text:
            signals.append("解除权触发条件不明确")
        return signals

    def _extract_obligations_from_text(self, text: str, source_id: str) -> List[Dict[str, Any]]:
        obligations = []
        if "交付" in text:
            obligations.append({
                "title": "卖方按期交付义务",
                "description": "卖方应按照合同约定的时间、地点和质量要求交付标的物。",
                "owner": "卖方",
                "source_id": source_id,
            })
        if "验收" in text:
            obligations.append({
                "title": "买方验收与通知义务",
                "description": "买方应在约定期限内完成验收并及时提出异议。",
                "owner": "买方",
                "source_id": source_id,
            })
        if "赔偿" in text or "违约金" in text:
            obligations.append({
                "title": "违约责任承担义务",
                "description": "违约方应按照合同或法律规定承担违约责任，赔偿守约方损失。",
                "owner": "违约方",
                "source_id": source_id,
            })
        return obligations

    def _extract_deadlines_from_text(self, text: str, source_id: str) -> List[Dict[str, Any]]:
        deadlines = []
        for match in re.finditer(r"(\d{4}年\d{1,2}月\d{1,2}日|\d+\s*个?工作日内|\d+\s*日内|\d+\s*日)", text):
            deadlines.append({
                "title": "合同期限/通知期限",
                "description": f"文本中出现期限：{match.group(1)}",
                "date": match.group(1),
                "owner": "待确认",
                "source_id": source_id,
            })
        return deadlines

    def _merge_extraction_result(self, state: ResearchState, result: Dict[str, Any]) -> None:
        if not isinstance(result, dict):
            result = {}
        for clause in self._as_dict_list(result.get("contract_clauses", []), "text"):
            self._append_unique_item(state["contract_clauses"], clause, ("clause_no", "text"), "clause_id", "clause")
        for obligation in self._as_dict_list(result.get("obligations", []), "description"):
            self._append_unique_item(state["obligations"], obligation, ("title", "description"), "obligation_id", "obligation")
        for deadline in self._as_dict_list(result.get("deadlines", []), "description"):
            self._append_unique_item(state["deadlines"], deadline, ("title", "date"), "deadline_id", "deadline")
        for evidence in self._as_dict_list(result.get("evidence_chain", []), "quote"):
            evidence.setdefault("verification_status", "unverified")
            self._append_unique_item(state["evidence_chain"], evidence, ("locator", "quote"), "evidence_id", "ev")
        for missing_fact in self._as_dict_list(result.get("missing_facts", []) or [], "description"):
            self._append_unique_missing_fact(state, missing_fact)
        if result.get("human_review_required"):
            state["human_review_required"] = True
        for reason in self._as_string_list(result.get("human_review_reasons", []) or []):
            self._append_unique_reason(state, reason)

    def _as_dict_list(self, value: Any, text_key: str) -> List[Dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            value = [value]
        normalized: List[Dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                normalized.append(item)
            elif item:
                normalized.append({text_key: str(item)})
        return normalized

    def _as_string_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return [str(value)] if value else []

    def _append_unique_item(
        self,
        items: List[Dict[str, Any]],
        item: Dict[str, Any],
        key_fields: tuple,
        id_field: str,
        id_prefix: str
    ) -> None:
        if not isinstance(item, dict):
            item = {"value": str(item)}
        key = tuple(str(item.get(field) or "") for field in key_fields)
        if any(tuple(str(existing.get(field) or "") for field in key_fields) == key for existing in items):
            return
        item.setdefault(id_field, f"{id_prefix}_{len(items) + 1:03d}")
        items.append(item)

    def _append_unique_missing_fact(self, state: ResearchState, missing_fact: Dict[str, Any]) -> None:
        if not isinstance(missing_fact, dict):
            missing_fact = {"type": "missing_fact", "description": str(missing_fact)}
        key = (missing_fact.get("type"), missing_fact.get("description"))
        if not any((item.get("type"), item.get("description")) == key for item in state["missing_facts"]):
            state["missing_facts"].append(missing_fact)

    def _append_unique_reason(self, state: ResearchState, reason: str) -> None:
        if reason and reason not in state["human_review_reasons"]:
            state["human_review_reasons"].append(reason)

    def _complete_step(self, state: ResearchState) -> None:
        self.add_message(state, "observation", {
            "agent": self.name,
            "content": (
                f"证据抽取完成：证据 {len(state.get('evidence_chain', []))} 条，"
                f"合同条款 {len(state.get('contract_clauses', []))} 条，"
                f"义务 {len(state.get('obligations', []))} 条。"
            )
        })
        self.add_message(state, "research_step", {
            "step_type": "evidence_extraction",
            "title": "证据抽取",
            "subtitle": "抽取条款、义务、期限和证据链",
            "status": "completed",
            "stats": {
                "evidence_count": len(state.get("evidence_chain", [])),
                "clauses_count": len(state.get("contract_clauses", [])),
                "obligations_count": len(state.get("obligations", [])),
            }
        })


LegalEvidenceExtractor = EvidenceExtractor
