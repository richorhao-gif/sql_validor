"""
graph/nodes/change_verifier.py
────────────────────────────────
将变更说明与数据库实际影响逐条对比，输出 PASS/WARN/FAIL 判定，并直接写出变更报告。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from sql_validator.core.report_builder import (
    format_changes_detail,
    format_db_impact_for_verification,
)
from sql_validator.graph.state import SQLValidationState
from sql_validator.prompts.report_gen import CHANGE_REPORT_PROMPT
from sql_validator.prompts.verification import CHANGE_VERIFICATION_PROMPT
from sql_validator.schemas.reports import ChangeVerificationResult


def make_change_verifier_node(llm: BaseChatModel, output_dir: str = "./reports"):
    """工厂函数：返回 change_verifier 节点函数。"""

    structured_llm = llm.with_structured_output(ChangeVerificationResult)

    def change_verifier(state: SQLValidationState, config: RunnableConfig) -> dict:
        change_description: str = state.get("change_description", "")
        db_impact: dict | None = state.get("db_impact")
        dep_graph: dict | None = state.get("dependency_graph")
        parsed_scripts: list[dict] = state.get("parsed_scripts", [])

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

        # ── Step 1: LLM 结构化对比校验 ───────────────────────────────────────
        try:
            prompt = CHANGE_VERIFICATION_PROMPT.format(
                change_description=change_description,
                db_impact_summary=db_impact_summary,
                changes_detail=changes_detail,
            )
            result: ChangeVerificationResult = structured_llm.invoke(prompt, config=config)
        except Exception as exc:  # noqa: BLE001
            result = ChangeVerificationResult(
                verdict="FAIL",
                risk_level="HIGH",
                confidence=0,
                analysis_notes=f"LLM 对比分析失败: {exc}",
            )

        # ── Step 2: LLM 生成 MD 变更报告 ─────────────────────────────────────
        errors: list[str] = []
        change_report_md = ""
        try:
            report_data = {
                "generated_at": datetime.now().isoformat(),
                "file_count": len(parsed_scripts),
                "change_verification": result.model_dump(),
                "db_impact": db_impact,
                "dependency_graph": dep_graph,
            }
            change_prompt = CHANGE_REPORT_PROMPT.format(
                report_data=json.dumps(report_data, ensure_ascii=False, indent=2)[:12000]
            )
            response = llm.invoke(change_prompt, config=config)
            change_report_md = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"变更报告生成失败: {exc}")
            change_report_md = f"# 变更对比报告生成失败\n\n错误: {exc}"

        # ── Step 3: 写入磁盘 ──────────────────────────────────────────────────
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = out_path / f"change_report_{timestamp}.md"
        report_path.write_text(change_report_md, encoding="utf-8")
        print(f"    [change_verifier] 变更报告已写入: {report_path}", flush=True)

        return {
            "change_verification": result.model_dump(),
            "change_report_path": str(report_path),
            "errors": errors,
        }

    return change_verifier

