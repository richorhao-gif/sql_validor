"""
graph/nodes/syntax_summarizer.py
──────────────────────────────────
双轨并行分析之二：汇总所有文件的语法问题，计算质量评分，生成改进建议。
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from sql_validator.core.db_comparator import compute_quality_score
from sql_validator.core.report_builder import format_file_stats, format_issues_for_summary
from sql_validator.graph.state import SQLValidationState
from sql_validator.prompts.report_gen import SYNTAX_REPORT_PROMPT
from sql_validator.schemas.reports import SyntaxAnalysisSummary


def make_syntax_summarizer_node(llm: BaseChatModel):
    """工厂函数：返回 syntax_summarizer 节点函数。"""

    structured_llm = llm.with_structured_output(SyntaxAnalysisSummary)

    def syntax_summarizer(state: SQLValidationState) -> dict:
        issues: list[dict] = state.get("raw_syntax_issues", [])
        parsed_scripts: list[dict] = state.get("parsed_scripts", [])
        file_list = [s["filename"] for s in parsed_scripts]

        # ── 纯代码统计 ─────────────────────────────────────────────────────────
        error_count = sum(1 for i in issues if i.get("severity") == "ERROR")
        warning_count = sum(1 for i in issues if i.get("severity") == "WARNING")
        info_count = sum(1 for i in issues if i.get("severity") == "INFO")
        quality_score = compute_quality_score(issues)
        files_with_errors = sorted({
            i["filename"] for i in issues if i.get("severity") == "ERROR"
        })

        issues_json = format_issues_for_summary(issues)
        file_stats = format_file_stats(issues, file_list)

        # ── LLM 生成 top_issues 和 recommendations ────────────────────────────
        try:
            # 复用 SYNTAX_REPORT_PROMPT 中的数据，但此处仅用于 top_issues/recommendations
            import json
            summary_data = {
                "error_count": error_count,
                "warning_count": warning_count,
                "info_count": info_count,
                "quality_score": quality_score,
                "issues": json.loads(issues_json),
                "file_stats": file_stats,
            }
            from sql_validator.prompts.impact_analysis import DEPENDENCY_ANALYSIS_PROMPT

            # 构造专用 Prompt
            summary_prompt = (
                f"以下是 SQL 脚本的问题列表（JSON）：\n{issues_json}\n\n"
                f"文件统计：\n{file_stats}\n\n"
                "请填写 top_issues（最重要的3-5条问题摘要，每条≤50字）"
                "和 recommendations（3-5条改进建议，每条≤80字）。"
                "quality_score、error_count、warning_count、info_count、"
                f"files_with_errors 已计算好，直接填入即可。"
            )
            result: SyntaxAnalysisSummary = structured_llm.invoke(summary_prompt)
            result = result.model_copy(update={
                "error_count": error_count,
                "warning_count": warning_count,
                "info_count": info_count,
                "quality_score": quality_score,
                "files_with_errors": files_with_errors,
            })
        except Exception as exc:  # noqa: BLE001
            result = SyntaxAnalysisSummary(
                error_count=error_count,
                warning_count=warning_count,
                info_count=info_count,
                quality_score=quality_score,
                files_with_errors=files_with_errors,
                top_issues=[f"LLM 摘要失败: {exc}"],
                recommendations=[],
            )
            return {
                "syntax_summary": result.model_dump(),
                "errors": [f"syntax_summarizer LLM 调用失败: {exc}"],
            }

        return {"syntax_summary": result.model_dump(), "errors": []}

    return syntax_summarizer
