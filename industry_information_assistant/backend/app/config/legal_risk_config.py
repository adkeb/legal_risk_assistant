# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Legal risk domain configuration for DeepResearch V2."""

LEGAL_TASK_TYPES = {
    "contract_review": "合同审查",
    "due_diligence": "企业法律尽调",
    "regulation_interpretation": "法规解读",
    "case_analysis": "案件研判",
    "enforcement_analysis": "行政处罚分析",
    "compliance_gap_analysis": "合规差距分析",
    "general_legal_research": "通用法律研究",
}

LEGAL_DOMAINS = {
    "contract": "合同",
    "corporate_governance": "公司治理",
    "labor": "劳动用工",
    "data_compliance": "数据合规",
    "ip": "知识产权",
    "litigation": "诉讼仲裁",
    "administrative_enforcement": "行政处罚",
    "sanctions": "制裁名单",
    "financial_compliance": "金融合规",
    "anti_bribery": "反商业贿赂",
    "tax": "税务",
}

LEGAL_SOURCE_TYPES = {
    "law": "法律",
    "regulation": "行政法规/部门规章/地方规则",
    "judicial_interpretation": "司法解释",
    "case": "案例",
    "court_decision": "裁判文书",
    "enforcement": "行政处罚",
    "contract": "合同",
    "internal_policy": "内部制度",
    "regulator_guidance": "监管指引",
    "company_record": "企业记录",
    "news": "舆情/新闻",
}

LEGAL_RISK_CATEGORIES = {
    "contract_clause": "合同条款风险",
    "compliance_obligation": "合规义务风险",
    "litigation": "诉讼仲裁风险",
    "enforcement": "行政处罚风险",
    "data_privacy": "数据合规风险",
    "labor": "劳动用工风险",
    "ip": "知识产权风险",
    "corporate": "公司治理风险",
    "sanctions": "制裁与名单风险",
    "reputation": "声誉风险",
}

LEGAL_QUALITY_THRESHOLD = 8.0
LEGAL_CODE_EXECUTION_ENABLED = False
LEGAL_DEFAULT_DISCLAIMER = (
    "本报告由 AI 辅助生成，仅基于用户提供材料、系统检索资料和当前可用信息进行法律风控分析，"
    "仅供参考，不构成正式法律意见。涉及重大、复杂或高风险事项，应由执业律师或企业法务进行人工复核。"
)


def score_to_level(score: float) -> str:
    """Map a 1-5 risk score to a legal risk level."""
    if score >= 4.2:
        return "重大风险"
    if score >= 3.4:
        return "高风险"
    if score >= 2.6:
        return "中风险"
    if score >= 1.8:
        return "低风险"
    return "提示项"
