"""
graph/nodes/syntax_file_worker.py
───────────────────────────────────
语法分析 Fan-out Worker：针对单个 SQL 文件，用 sqlglot 静态解析 + LLM 提炼问题。

从 input_processor 之后立即并发启动，与 db_context_agent → file_analyzer 链路完全独立，
不依赖 DB 快照。Fan-in 后由 syntax_summarizer（纯代码）汇总写报告。
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from sql_validator.core.report_builder import format_issues_for_summary
from sql_validator.core.sql_parser import parse_sql_file
from sql_validator.graph.state import SyntaxFileWorkerInput
from sql_validator.prompts.report_gen import SYNTAX_FILE_ANALYSIS_PROMPT
from sql_validator.schemas.reports import SyntaxFileAnalysis


def make_syntax_file_worker_node(llm: BaseChatModel):
    """工厂函数：返回 syntax_file_worker Worker 节点函数。"""

    structured_llm = llm.with_structured_output(SyntaxFileAnalysis)

    def syntax_file_worker(state: SyntaxFileWorkerInput, config: RunnableConfig) -> dict:
        """处理单个 SQL 文件的语法分析，返回结果追加到主图 syntax_file_results。"""
        file_dict: dict = state["file"]
        filename: str = file_dict.get("filename", "unknown.sql")

        # ── Step 1: sqlglot 静态解析 ──────────────────────────────────────────
        try:
            script, issues = parse_sql_file(file_dict)
        except Exception as exc:  # noqa: BLE001
            return {
                "syntax_file_results": [{
                    "filename": filename,
                    "error_count": 1,
                    "warning_count": 0,
                    "info_count": 0,
                    "issues": [],
                    "top_issues": [f"解析异常: {exc}"],
                    "recommendations": [],
                }],
                "errors": [f"[{filename}] sqlglot 解析异常: {exc}"],
            }

        issues_dicts = [i.model_dump() for i in issues]
        error_count   = sum(1 for i in issues_dicts if i.get("severity") == "ERROR")
        warning_count = sum(1 for i in issues_dicts if i.get("severity") == "WARNING")
        info_count    = sum(1 for i in issues_dicts if i.get("severity") == "INFO")

        issues_json = format_issues_for_summary(issues_dicts)
        statements_summary = "\n".join(
            f"  {i + 1}. [{s.operation}] {s.full_object_name or '(无对象名)'}"
            for i, s in enumerate(script.statements[:15])
        )

        # ── Step 2: LLM 提炼 per-file top_issues + recommendations ───────────
        try:
            print(f"    [syntax_file_worker] LLM 分析 {filename}……", flush=True)
            prompt = SYNTAX_FILE_ANALYSIS_PROMPT.format(
                filename=filename,
                statement_count=len(script.statements),
                issues_json=issues_json[:4000],
                statements_summary=statements_summary,
            )
            analysis: SyntaxFileAnalysis = structured_llm.invoke(prompt, config=config)
        except Exception as exc:  # noqa: BLE001
            analysis = SyntaxFileAnalysis(
                top_issues=[f"LLM 分析失败: {exc}"],
                recommendations=[],
            )

        return {
            "syntax_file_results": [{
                "filename": filename,
                "error_count": error_count,
                "warning_count": warning_count,
                "info_count": info_count,
                "issues": issues_dicts,
                "top_issues": analysis.top_issues,
                "recommendations": analysis.recommendations,
            }],
            "errors": [],
        }

    return syntax_file_worker
