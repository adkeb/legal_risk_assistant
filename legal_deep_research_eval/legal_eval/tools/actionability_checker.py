"""Business actionability checks for remediation recommendations."""

from __future__ import annotations

import re
from typing import Any, Dict

from ..utils import ratio


class ActionabilityCheckerTool:
    def check(self, parsed_report: Dict[str, Any], report_markdown: str, risk_items: list[dict] | None = None) -> Dict[str, Any]:
        action_items = parsed_report.get("action_items") or []
        text = report_markdown or ""
        has_owner = bool(re.search(r"(责任人|负责部门|法务|业务|IT|合规|律师)", text))
        has_priority = bool(re.search(r"(优先级|高优先|中优先|低优先|立即|短期|中期|长期)", text))
        has_deadline = bool(re.search(r"(\d+\s*(日|天|周|月)|期限|完成时间|前完成|内完成)", text))
        has_action_verbs = bool(action_items)
        score_components = [has_owner, has_priority, has_deadline, has_action_verbs]
        return {
            "actionability_score": ratio(sum(1 for item in score_components if item), len(score_components), default=0.0),
            "action_item_count": len(action_items),
            "has_owner": has_owner,
            "has_priority": has_priority,
            "has_deadline": has_deadline,
            "has_action_verbs": has_action_verbs,
            "weaknesses": [
                label
                for label, ok in {
                    "missing_owner": has_owner,
                    "missing_priority": has_priority,
                    "missing_deadline": has_deadline,
                    "missing_action_items": has_action_verbs,
                }.items()
                if not ok
            ],
        }
