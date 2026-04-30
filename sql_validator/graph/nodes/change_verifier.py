"""
graph/nodes/change_verifier.py
────────────────────────────────
双轨并行分析之一：将变更说明与数据库实际影响逐条对比，输出 PASS/WARN/FAIL 判定。
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from sql_validator.core.report_builder import (
    format_changes_detail,
    format_db_impact_for_verification,
)
from sql_validator.graph.state import SQLValidationState
from sql_validator.prompts.verification import CHANGE_VERIFICATION_PROMPT
from sql_validator.schemas.reports import ChangeVerificationResult


def make_change_verifier_node(llm: BaseChatModel):
    """工厂函数：返回 change_verifier 节点函数。"""

    structured_llm = llm.with_structured_output(ChangeVerificationResult)

    def change_verifier(state: SQLValidationState) -> dict:
        change_description: str = state.get("change_description", "")
        db_impact: dict | None = state.get("db_impact")

        if not db_impact:
            result = ChangeVerificationResult(
                verdict="FAIL",
                risk_level="HIGH",
                confidence=0,
                analysis_notes="db_impact 数据缺失，无法进行变更说明对比",
            )
            return {"change_verification": result.model_dump()}

        db_impact_summary = format_db_impact_for_verification(db_impact)
        changes_detail = format_changes_detail(db_impact)

        try:
            prompt = CHANGE_VERIFICATION_PROMPT.format(
                change_description=change_description,
                db_impact_summary=db_impact_summary,
                changes_detail=changes_detail,
            )
            result: ChangeVerificationResult = structured_llm.invoke(prompt)
        except Exception as exc:  # noqa: BLE001
            result = ChangeVerificationResult(
                verdict="FAIL",
                risk_level="HIGH",
                confidence=0,
                analysis_notes=f"LLM 对比分析失败: {exc}",
            )
            return {
                "change_verification": result.model_dump(),
                "errors": [f"change_verifier LLM 调用失败: {exc}"],
            }

        return {"change_verification": result.model_dump(), "errors": []}

    return change_verifier
