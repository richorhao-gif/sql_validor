"""
graph/builder.py
─────────────────
LangGraph 主图组装。

节点路由示意：
  START
    → input_processor
    → db_context_agent
    → [file_analyzer × N]  (Send API 扇出 + Fan-in)
    → dependency_analyzer
    → db_impact_analyzer
    → [change_verifier, syntax_summarizer]  (并行 Fork)
    → report_generator       (Fan-in 屏障：等两条分支都完成)
    → END
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from sql_validator.graph.nodes.change_verifier import make_change_verifier_node
from sql_validator.graph.nodes.db_context_agent import make_db_context_agent_node
from sql_validator.graph.nodes.db_impact_analyzer import make_db_impact_analyzer_node
from sql_validator.graph.nodes.dependency_analyzer import make_dependency_analyzer_node
from sql_validator.graph.nodes.file_analyzer import make_file_analyzer_node
from sql_validator.graph.nodes.input_processor import input_processor
from sql_validator.graph.nodes.report_generator import make_report_generator_node
from sql_validator.graph.nodes.syntax_summarizer import make_syntax_summarizer_node
from sql_validator.graph.state import FileAnalyzerInput, SQLValidationState


# ─────────────────────────────────────────────────────────────────────────────
# 路由函数
# ─────────────────────────────────────────────────────────────────────────────

def _route_to_file_analyzers(state: SQLValidationState) -> list[Send]:
    """
    db_context_agent 完成后，通过 Send API 将每个文件分发给并行 Worker。
    每个 Worker 拿到自己的文件 + 完整的 db_snapshot。
    """
    return [
        Send(
            "file_analyzer",
            FileAnalyzerInput(
                file=f,
                db_snapshot=state.get("db_snapshot"),
                change_description=state["change_description"],
            ),
        )
        for f in state["sql_files"]
    ]


def _route_to_final_analysis(state: SQLValidationState) -> list[str]:
    """
    db_impact_analyzer 完成后，并行触发两条分支：
    change_verifier 和 syntax_summarizer。
    """
    return ["change_verifier", "syntax_summarizer"]


# ─────────────────────────────────────────────────────────────────────────────
# 图组装
# ─────────────────────────────────────────────────────────────────────────────

def build_graph(
    llm: BaseChatModel,
    db_tools: list[BaseTool],
    output_dir: str = "./reports",
    checkpointer: BaseCheckpointSaver | None = None,
):
    """
    组装并编译 SQL 变更校验主图。

    Args:
        llm        : 已配置的 ChatModel 实例
        db_tools   : create_db_tools() 返回的只读 DB 工具列表
        output_dir : MD 报告输出目录
        checkpointer: 可选，传入 MemorySaver() 或 PostgresSaver 支持断点续跑

    Returns:
        CompiledStateGraph，可调用 .invoke() / .stream()
    """
    builder = StateGraph(SQLValidationState)

    # ── 注册节点 ──────────────────────────────────────────────────────────────
    builder.add_node("input_processor", input_processor)

    builder.add_node(
        "db_context_agent",
        make_db_context_agent_node(llm, db_tools),
    )

    builder.add_node(
        "file_analyzer",
        make_file_analyzer_node(llm),
        input_schema=FileAnalyzerInput,
    )

    builder.add_node(
        "dependency_analyzer",
        make_dependency_analyzer_node(llm),
    )

    builder.add_node(
        "db_impact_analyzer",
        make_db_impact_analyzer_node(llm),
    )

    builder.add_node(
        "change_verifier",
        make_change_verifier_node(llm),
    )

    builder.add_node(
        "syntax_summarizer",
        make_syntax_summarizer_node(llm),
    )

    builder.add_node(
        "report_generator",
        make_report_generator_node(llm, output_dir=output_dir),
    )

    # ── 串行边 ────────────────────────────────────────────────────────────────
    builder.add_edge(START, "input_processor")
    builder.add_edge("input_processor", "db_context_agent")

    # db_context_agent → Send 扇出到 N 个 file_analyzer
    builder.add_conditional_edges(
        "db_context_agent",
        _route_to_file_analyzers,
    )

    # 所有 file_analyzer 完成后 → dependency_analyzer（Fan-in 由 LangGraph 自动处理）
    builder.add_edge("file_analyzer", "dependency_analyzer")
    builder.add_edge("dependency_analyzer", "db_impact_analyzer")

    # db_impact_analyzer → 并行 Fork 到两条分支
    builder.add_conditional_edges(
        "db_impact_analyzer",
        _route_to_final_analysis,
    )

    # 两条分支都完成 → report_generator（Fan-in 屏障）
    builder.add_edge(["change_verifier", "syntax_summarizer"], "report_generator")
    builder.add_edge("report_generator", END)

    return builder.compile(checkpointer=checkpointer)
