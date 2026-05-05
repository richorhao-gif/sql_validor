"""
graph/state.py
───────────────
LangGraph 主图的共享状态定义。

设计原则：
- 所有字段使用 Python 原生类型（dict/list/str），保证序列化安全
- Pydantic 模型在节点边界通过 model_validate / model_dump 进行转换
- 并行 Worker 聚合字段（parsed_scripts / raw_syntax_issues / errors）
  使用 Annotated[list, operator.add] 实现自动追加
- FileAnalyzerInput 为 Send API 的 Worker 节点专用输入 Schema
"""
from __future__ import annotations

import operator
from typing import Annotated, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class SQLValidationState(TypedDict):
    """SQL 变更校验智能体的主图全局状态。"""

    # ── 输入 ─────────────────────────────────────────────────────────────────
    sql_files: list[dict]          # list[SQLFile.model_dump()]
    change_description: str

    # ── input_processor 提取的对象名（供 db_context_agent set diff 校验）────
    object_names: list[str]

    # ── DB 上下文（db_context_agent 产出）────────────────────────────────────
    db_snapshot: Optional[dict]    # DBSnapshot.model_dump() | None

    # ── 并行 Worker 聚合（operator.add 自动追加）──────────────────────────────
    parsed_scripts: Annotated[list[dict], operator.add]      # list[ParsedScript.model_dump()]
    raw_syntax_issues: Annotated[list[dict], operator.add]   # list[SyntaxIssue.model_dump()]

    # ── 语法 Worker 聚合（input_processor 后立即并发）────────────────────────
    syntax_file_results: Annotated[list[dict], operator.add]  # per-file 语法分析结果

    # ── 顺序分析阶段 ──────────────────────────────────────────────────────────
    dependency_graph: Optional[dict]   # DependencyGraph.model_dump() | None
    db_impact: Optional[dict]          # DBImpactAnalysis.model_dump() | None

    # ── 变更校验（change_verifier 产出）──────────────────────────────────────
    change_verification: Optional[dict]  # ChangeVerificationResult.model_dump() | None

    # ── 最终产出 ──────────────────────────────────────────────────────────────
    change_report_path: str
    syntax_report_path: str

    # ── 控制字段 ──────────────────────────────────────────────────────────────
    errors: Annotated[list[str], operator.add]
    messages: Annotated[list[BaseMessage], add_messages]


class FileAnalyzerInput(TypedDict):
    """通过 Send API 分发给并行 file_analyzer Worker 的载荷。"""
    file: dict
    db_snapshot: Optional[dict]
    change_description: str


class SyntaxFileWorkerInput(TypedDict):
    """通过 Send API 分发给并行 syntax_file_worker Worker 的载荷。不依赖 DB 快照。"""
    file: dict
    change_description: str


def make_initial_state(sql_files: list[dict], change_description: str) -> SQLValidationState:
    """构造智能体初始状态，确保所有聚合字段有正确的初始值。"""
    return SQLValidationState(
        sql_files=sql_files,
        change_description=change_description,
        object_names=[],
        db_snapshot=None,
        parsed_scripts=[],
        raw_syntax_issues=[],
        syntax_file_results=[],
        dependency_graph=None,
        db_impact=None,
        change_verification=None,
        change_report_path="",
        syntax_report_path="",
        errors=[],
        messages=[],
    )
