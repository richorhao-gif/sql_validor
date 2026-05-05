"""
agent.py
─────────
SQL 变更校验智能体工厂。

使用 LangGraph 内置的 create_react_agent：
  - prompt 注入系统提示词
  - response_format 强制产出结构化 ValidationReport（在 Agent 完成 ReAct 循环后
    额外调用一次 LLM 提取结构化输出，结果存入 state["structured_response"]）
  - recursion_limit 通过 invoke 时的 config 传入，默认 50 步

LangGraph 官方文档参考：
  https://langchain-ai.github.io/langgraph/reference/prebuilt/#langgraph.prebuilt.chat_agent_executor.create_react_agent
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import create_react_agent

from sql_validator.prompts.system import SYSTEM_PROMPT
from sql_validator.schemas.report import ValidationReport


def create_validator_agent(llm: BaseChatModel, tools: list[BaseTool]):
    """
    创建 SQL 变更校验 ReAct Agent。

    Agent 完成工具调用循环后，会额外进行一次结构化提取，将分析结果转换为
    ValidationReport 存入 state["structured_response"]。

    Args:
        llm  : 已配置的 ChatModel（推荐 temperature=0.0）
        tools: DB 工具 + 纯代码分析工具的合并列表

    Returns:
        CompiledStateGraph，调用 .invoke({"messages": [...]}) 使用
    """
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=SystemMessage(content=SYSTEM_PROMPT),
        response_format=ValidationReport,
    )
