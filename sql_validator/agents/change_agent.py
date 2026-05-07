"""
agents/change_agent.py
───────────────────────
SQL 变更校验 ReAct Agent 工厂。

使用 LangGraph 内置 create_react_agent，生成结构化 ValidationReport。
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import create_react_agent

from sql_validator.prompts.system import SYSTEM_PROMPT
from sql_validator.schemas.report import ValidationReport


def create_change_agent(llm: BaseChatModel, tools: list[BaseTool]):
    """
    创建变更校验 ReAct Agent。

    Agent 完成工具调用循环后，额外进行一次结构化提取，将分析结果转换为
    ValidationReport 存入 state["structured_response"]。

    Args:
        llm  : 已配置的 ChatModel（推荐 temperature=0.0）
        tools: DB 工具 + 纯代码分析工具的合并列表

    Returns:
        CompiledStateGraph
    """
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=SystemMessage(content=SYSTEM_PROMPT),
        response_format=ValidationReport,
    )
