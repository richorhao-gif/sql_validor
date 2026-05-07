"""
agents/syntax_agent.py
───────────────────────
SQL 语法与发版规范审查 ReAct Agent 工厂。

与 change_agent 并行运行，专注于：
  - SQL 语法与代码质量（原 syntax_analyzer.py 的职责）
  - 数仓发版规范 RULE4.1-4.9
生成结构化 SyntaxReport。
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import create_react_agent

from sql_validator.prompts.syntax import SYNTAX_PROMPT
from sql_validator.schemas.syntax_report import SyntaxReport


def create_syntax_agent(llm: BaseChatModel, tools: list[BaseTool]):
    """
    创建语法审查 ReAct Agent。

    Agent 调用 parse_sql_files 获取脚本内容，按需使用 DB 工具查询数据库对象，
    最终产出 SyntaxReport 存入 state["structured_response"]。

    Args:
        llm  : 与 change_agent 共享的 ChatModel 实例（HTTP 连接池线程安全）
        tools: DB 工具 + 纯代码分析工具的合并列表（与 change_agent 相同）

    Returns:
        CompiledStateGraph
    """
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=SystemMessage(content=SYNTAX_PROMPT),
        response_format=SyntaxReport,
    )
