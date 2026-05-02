"""
tools/db_tools.py
──────────────────
封装 LangChain SQLDatabaseToolkit，强制只读权限：
  - 所有通过 QuerySQLDataBaseTool 执行的 SQL 必须是 SELECT 语句
  - 其他写操作（INSERT/UPDATE/DELETE/DROP 等）直接拦截，不发送到数据库
"""
from __future__ import annotations

from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool
from langchain_community.utilities import SQLDatabase
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool


_BLOCKED_KEYWORDS = frozenset({
    "insert", "update", "delete", "drop", "truncate",
    "create", "alter", "grant", "revoke", "call", "execute",
})


def _is_select_only(sql: str) -> bool:
    """宽松检查：SQL 是否为 SELECT-only 语句（防止意外写操作）。"""
    first_token = sql.strip().lower().split()[0] if sql.strip() else ""
    return first_token == "select" or first_token in {"with", "explain"}


class SafeQueryTool(BaseTool):
    """
    只读查询工具，拦截所有非 SELECT 语句。
    包装 QuerySQLDataBaseTool，在实际执行前校验 SQL。
    """

    name: str = "sql_db_query"
    description: str = (
        "对 PostgreSQL 数据库执行只读 SQL 查询（仅允许 SELECT/WITH/EXPLAIN）。"
        "用于查询表结构、数据量、外键引用等信息。"
        "Input: 合法的 SELECT SQL 语句。"
    )
    inner: QuerySQLDataBaseTool

    def _run(self, query: str) -> str:  # type: ignore[override]
        if not _is_select_only(query):
            blocked = query.strip().lower().split()[0]
            return (
                f"[BLOCKED] 安全策略拒绝执行 {blocked.upper()} 语句。"
                "本工具仅允许 SELECT/WITH/EXPLAIN 查询。"
            )
        return self.inner._run(query)

    async def _arun(self, query: str) -> str:  # type: ignore[override]
        return self._run(query)


def create_db_tools(dsn: str, llm: BaseChatModel) -> list[BaseTool]:
    """
    创建面向 db_context_agent 的只读数据库工具集。

    包含：
      - sql_db_list_tables  : 列出数据库所有表
      - sql_db_schema       : 获取指定表的 DDL 和列信息
      - sql_db_query        : 安全只读查询（SafeQueryTool 包装）

    Args:
        dsn: PostgreSQL 连接字符串
        llm: LLM 实例（toolkit 内部使用，保持接口兼容）

    Returns:
        工具列表，可直接传入 create_react_agent
    """
    from langchain_community.agent_toolkits import SQLDatabaseToolkit
    from langchain_community.tools.sql_database.tool import (
        InfoSQLDatabaseTool,
        ListSQLDatabaseTool,
    )

    # SQLAlchemy 默认将 postgresql:// 映射到 psycopg2；
    # 项目使用 psycopg3，需将 scheme 替换为 postgresql+psycopg://
    sqlalchemy_dsn = dsn.replace("postgresql://", "postgresql+psycopg://", 1).replace(
        "postgres://", "postgresql+psycopg://", 1
    )
    db = SQLDatabase.from_uri(sqlalchemy_dsn)
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    all_tools = toolkit.get_tools()

    # 按类型筛选：SafeQueryTool 替换查询工具，排除 checker 和写工具
    result: list[BaseTool] = []
    for t in all_tools:
        if isinstance(t, QuerySQLDataBaseTool):
            result.append(SafeQueryTool(inner=t))
        elif isinstance(t, (ListSQLDatabaseTool, InfoSQLDatabaseTool)):
            result.append(t)

    return result
