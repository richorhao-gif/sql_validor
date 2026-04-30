"""
graph/nodes/db_context_agent.py
────────────────────────────────
构建 db_context_agent 节点的工厂函数。

内部使用 create_react_agent 创建 ReAct 子图，装备只读 SQLDatabaseToolkit。
Agent 自主决定查询哪些对象，追查外键、隐式依赖等。
最终将 Agent 的探查结果转换为结构化的 DBSnapshot。
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool

from sql_validator.prompts.db_context import DB_SNAPSHOT_EXTRACTION_PROMPT
from sql_validator.schemas.db_context import DBSnapshot
from sql_validator.graph.state import SQLValidationState


def make_db_context_agent_node(
    llm: BaseChatModel,
    db_tools: list[BaseTool],
):
    """
    工厂函数：返回 db_context_agent 节点函数。

    Args:
        llm: 已配置的 ChatModel 实例
        db_tools: create_db_tools() 返回的只读工具列表
    """
    from langgraph.prebuilt import create_react_agent

    # ReAct 子图（无 checkpointer，由主图管理持久化）
    react_agent = create_react_agent(
        model=llm,
        tools=db_tools,
    )

    # 用于最终结构化提取的绑定模型
    structured_llm = llm.with_structured_output(DBSnapshot)

    def db_context_agent(state: SQLValidationState) -> dict:
        """
        调用 ReAct 子图探查数据库，然后用结构化输出提取 DBSnapshot。
        """
        # 取 input_processor 写入的初始消息
        messages = state.get("messages", [])
        if not messages:
            return {"errors": ["db_context_agent: 未找到初始消息，跳过 DB 查询"]}

        # 调用 ReAct Agent，用 stream(values) 实时打印进度，最后一个 chunk 即完整状态
        try:
            final_result: dict = {}
            step = 0
            for chunk in react_agent.stream(
                {"messages": messages}, stream_mode="values"
            ):
                final_result = chunk
                # 取本轮新增的最后一条消息做进度提示
                latest = (chunk.get("messages") or [])[-1] if chunk.get("messages") else None
                if latest is not None:
                    step += 1
                    label = type(latest).__name__
                    if hasattr(latest, "tool_calls") and latest.tool_calls:
                        hint = f"调用工具: {latest.tool_calls[0].get('name', '?')}"
                    elif hasattr(latest, "content") and isinstance(latest.content, str):
                        hint = latest.content[:80].replace("\n", " ")
                    else:
                        hint = ""
                    if hint:
                        print(f"    [db_context step {step}] {label}: {hint}", flush=True)
        except Exception as exc:  # noqa: BLE001
            return {
                "errors": [f"db_context_agent ReAct 调用失败: {exc}"],
                "db_snapshot": DBSnapshot().model_dump(),
            }

        agent_msgs: list[BaseMessage] = final_result.get("messages", [])
        conversation_text = "\n\n".join(
            f"[{type(m).__name__}]: {m.content}"
            for m in agent_msgs
            if isinstance(m.content, str) and m.content.strip()
        )

        # 用结构化 LLM 从对话文本中提取 DBSnapshot
        print("    [db_context] 提取结构化 DBSnapshot……", flush=True)
        try:
            snapshot: DBSnapshot = structured_llm.invoke(
                DB_SNAPSHOT_EXTRACTION_PROMPT.format(
                    agent_conversation=conversation_text[:8000]  # 防止超 Token
                )
            )
            print("    [db_context] DBSnapshot 提取完成", flush=True)
        except Exception as exc:  # noqa: BLE001
            return {
                "errors": [f"DBSnapshot 结构化提取失败: {exc}"],
                "db_snapshot": DBSnapshot(
                    agent_query_notes=f"提取失败，原始对话已截断: {conversation_text[:500]}"
                ).model_dump(),
                "messages": agent_msgs,
            }

        return {
            "db_snapshot": snapshot.model_dump(),
            "messages": agent_msgs,
        }

    return db_context_agent
