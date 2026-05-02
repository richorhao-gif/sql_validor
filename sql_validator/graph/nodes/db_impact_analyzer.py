"""
graph/nodes/db_impact_analyzer.py
───────────────────────────────────
汇总本次发版对数据库的全局影响。

结合执行顺序、各文件解析结果、DB 快照，由 LLM 生成结构化影响分析。
"""
from __future__ import annotations

import json

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from sql_validator.core.report_builder import format_scripts_summary
from sql_validator.graph.state import SQLValidationState
from sql_validator.prompts.impact_analysis import DB_IMPACT_PROMPT
from sql_validator.schemas.analysis import DBImpactAnalysis


def make_db_impact_analyzer_node(llm: BaseChatModel):
    """工厂函数：返回 db_impact_analyzer 节点函数。"""

    structured_llm = llm.with_structured_output(DBImpactAnalysis)

    def db_impact_analyzer(state: SQLValidationState, config: RunnableConfig) -> dict:
        parsed_scripts: list[dict] = state.get("parsed_scripts", [])
        dep_graph: dict | None = state.get("dependency_graph")
        snapshot: dict | None = state.get("db_snapshot")

        execution_order = (
            dep_graph.get("execution_order", []) if dep_graph else
            [s["filename"] for s in parsed_scripts]
        )

        scripts_summary = format_scripts_summary(parsed_scripts)
        execution_str = " → ".join(execution_order) if execution_order else "（顺序待定）"

        # DB 快照摘要（避免传入过多 Token）
        db_snapshot_summary = "（未提供 DB 快照）"
        if snapshot:
            table_names = list(snapshot.get("tables", {}).keys())
            view_names = list(snapshot.get("views", {}).keys())
            notes = snapshot.get("agent_query_notes", "")
            db_snapshot_summary = (
                f"已存在的表（{len(table_names)} 张）: {', '.join(table_names[:20])}\n"
                f"已存在的视图（{len(view_names)} 个）: {', '.join(view_names[:10])}\n"
                f"Agent 查询说明: {notes[:500]}"
            )

        try:
            prompt = DB_IMPACT_PROMPT.format(
                execution_order=execution_str,
                scripts_summary=scripts_summary,
                db_snapshot_summary=db_snapshot_summary,
            )
            impact: DBImpactAnalysis = structured_llm.invoke(prompt, config=config)
            # 确保 execution_sequence 与算法结果一致
            impact = impact.model_copy(update={"execution_sequence": execution_order})
        except Exception as exc:  # noqa: BLE001
            impact = DBImpactAnalysis(
                execution_sequence=execution_order,
                overall_summary=f"LLM 分析失败: {exc}",
            )
            return {
                "db_impact": impact.model_dump(),
                "errors": [f"db_impact_analyzer LLM 调用失败: {exc}"],
            }

        return {"db_impact": impact.model_dump(), "errors": []}

    return db_impact_analyzer
