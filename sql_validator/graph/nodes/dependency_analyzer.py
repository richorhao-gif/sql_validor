"""
graph/nodes/dependency_analyzer.py
────────────────────────────────────
分析 SQL 文件间依赖关系并确定执行顺序。

先用 core/dependency.py 的纯算法计算依赖图，
再用 LLM 补充 analysis_notes 并验证隐式依赖。
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from sql_validator.core.dependency import build_dependency_graph
from sql_validator.core.report_builder import format_scripts_summary
from sql_validator.graph.state import SQLValidationState
from sql_validator.prompts.impact_analysis import DEPENDENCY_ANALYSIS_PROMPT
from sql_validator.schemas.analysis import DependencyGraph


def make_dependency_analyzer_node(llm: BaseChatModel):
    """工厂函数：返回 dependency_analyzer 节点函数。"""

    structured_llm = llm.with_structured_output(DependencyGraph)

    def dependency_analyzer(state: SQLValidationState) -> dict:
        parsed_scripts: list[dict] = state.get("parsed_scripts", [])

        if not parsed_scripts:
            return {
                "dependency_graph": DependencyGraph(
                    execution_order=[],
                    analysis_notes="无可用的解析结果",
                ).model_dump(),
                "errors": ["dependency_analyzer: parsed_scripts 为空"],
            }

        # ── 纯算法计算依赖图 ──────────────────────────────────────────────────
        computed = build_dependency_graph(parsed_scripts)
        computed_order_str = " → ".join(computed["execution_order"]) or "（无顺序约束）"
        scripts_summary = format_scripts_summary(parsed_scripts)

        # ── LLM 补充分析 ──────────────────────────────────────────────────────
        try:
            prompt = DEPENDENCY_ANALYSIS_PROMPT.format(
                scripts_summary=scripts_summary,
                computed_order=computed_order_str,
            )
            dep_graph: DependencyGraph = structured_llm.invoke(prompt)

            # 以算法结果为准，LLM 只覆盖 analysis_notes（避免 LLM 乱改执行顺序）
            dep_graph = dep_graph.model_copy(
                update={
                    "execution_order": computed["execution_order"],
                    "dependency_map": computed["dependency_map"],
                    "reverse_map": computed["reverse_map"],
                    "has_cycles": computed["has_cycles"],
                    "cycle_paths": computed["cycle_paths"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            computed_without_notes = {k: v for k, v in computed.items() if k != "analysis_notes"}
            dep_graph = DependencyGraph(
                **computed_without_notes,
                analysis_notes=f"LLM 分析失败（{exc}），已使用算法结果",
            )

        result = {"dependency_graph": dep_graph.model_dump(), "errors": []}

        if dep_graph.has_cycles:
            result["errors"] = [
                f"检测到循环依赖: {dep_graph.cycle_paths}，请检查脚本间的依赖关系"
            ]

        return result

    return dependency_analyzer
