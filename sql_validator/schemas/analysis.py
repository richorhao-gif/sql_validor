"""
schemas/analysis.py
────────────────────
sql_parser.py 内部使用的解析结果数据模型。
这些模型作为 analysis_tools.py 工具的中间层，不直接暴露给外部调用方。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class StatementInfo(BaseModel):
    """单条 SQL 语句的结构化信息。"""

    index: int = Field(description="语句在文件中的序号（0-based）")
    statement_type: str = Field(description="语句大类：DDL | DML | QUERY | DCL")
    operation: str = Field(
        description="操作类型：CREATE | ALTER | DROP | INSERT | UPDATE | DELETE | TRUNCATE | MERGE | SELECT | GRANT | REVOKE"
    )
    object_type: str = Field(description="对象类型：TABLE | VIEW | FOREIGN TABLE | INDEX 等")
    object_schema: str = Field(description="对象所在 schema")
    object_name: str = Field(description="对象名")
    full_object_name: str = Field(description="schema.name 格式的全限定名")
    raw_sql_snippet: str = Field(default="", description="原始 SQL 片段（前 300 字符）")


class SyntaxIssue(BaseModel):
    """单条语法或代码质量问题。"""

    filename: str
    severity: str = Field(description="ERROR | WARNING | INFO")
    category: str = Field(description="SYNTAX | QUALITY 等")
    rule: str = Field(description="规则标识符")
    message: str = Field(description="问题描述")
    sql_snippet: str = Field(default="", description="相关 SQL 片段")
    suggestion: str = Field(default="", description="修复建议")


class ParsedScript(BaseModel):
    """单个 SQL 文件的完整解析结果。"""

    filename: str
    dialect: str = "postgres"
    statements: list[StatementInfo] = Field(default_factory=list)
    objects_created: list[str] = Field(
        default_factory=list, description="本文件新建的对象全限定名列表"
    )
    objects_altered: list[str] = Field(
        default_factory=list, description="本文件修改的对象全限定名列表"
    )
    objects_dropped: list[str] = Field(
        default_factory=list, description="本文件删除的对象全限定名列表"
    )
    objects_read: list[str] = Field(
        default_factory=list, description="本文件 SELECT 读取的对象全限定名列表"
    )
    objects_written: list[str] = Field(
        default_factory=list,
        description="本文件 INSERT/UPDATE/DELETE/TRUNCATE 写入的对象全限定名列表",
    )
    syntax_error_count: int = 0
    intent_summary: str = Field(
        default="", description="LLM 填充的意图摘要（当前架构中保留字段，默认为空）"
    )
