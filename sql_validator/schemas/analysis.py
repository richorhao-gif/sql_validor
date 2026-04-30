from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StatementInfo(BaseModel):
    """单条 SQL 语句的结构化解析结果。"""

    index: int = Field(description="在文件中的顺序（0-based）")
    statement_type: Literal["DDL", "DML", "DCL", "TCL", "QUERY", "UNKNOWN"]
    operation: Literal[
        "CREATE", "ALTER", "DROP",
        "INSERT", "UPDATE", "DELETE", "TRUNCATE", "MERGE",
        "SELECT", "GRANT", "REVOKE",
        "BEGIN", "COMMIT", "ROLLBACK",
        "UNKNOWN",
    ]
    object_type: str = Field(
        description="TABLE | VIEW | INDEX | FUNCTION | PROCEDURE | SEQUENCE | SCHEMA | UNKNOWN"
    )
    object_schema: str = Field(default="public")
    object_name: str = Field(default="")
    full_object_name: str = Field(description="schema.object_name 格式")
    raw_sql_snippet: str = Field(description="原始 SQL 片段（截断至 300 字符）")


class ParsedScript(BaseModel):
    """单个 SQL 文件的完整解析结果（sqlglot + LLM 共同产出）。"""

    filename: str
    dialect: str = "postgres"
    statements: list[StatementInfo] = Field(default_factory=list)
    objects_created: list[str] = Field(
        default_factory=list, description="本文件新建的对象全名列表"
    )
    objects_altered: list[str] = Field(
        default_factory=list, description="本文件修改的对象全名列表"
    )
    objects_dropped: list[str] = Field(
        default_factory=list, description="本文件删除的对象全名列表"
    )
    objects_read: list[str] = Field(
        default_factory=list, description="本文件 SELECT 引用的对象全名列表"
    )
    objects_written: list[str] = Field(
        default_factory=list, description="本文件 DML 写入的对象全名列表"
    )
    syntax_error_count: int = 0
    intent_summary: str = Field(
        default="", description="LLM 生成的业务意图一段话描述"
    )


class SyntaxIssue(BaseModel):
    """单条语法或代码质量问题。"""

    filename: str
    severity: Literal["ERROR", "WARNING", "INFO"]
    category: Literal["SYNTAX", "PERFORMANCE", "CONVENTION", "SECURITY", "LOGIC"]
    rule: str = Field(description="规则短名，如 NO_WHERE_CLAUSE、SELECT_STAR")
    message: str = Field(description="问题描述")
    sql_snippet: str = Field(default="", description="涉及的 SQL 片段（截断）")
    suggestion: str = Field(default="", description="修复建议")


class DependencyGraph(BaseModel):
    """SQL 文件间的依赖关系图和推荐执行顺序。"""

    execution_order: list[str] = Field(description="拓扑排序后的推荐文件执行顺序")
    dependency_map: dict[str, list[str]] = Field(
        default_factory=dict,
        description="文件 → 其依赖的文件列表（该文件应在依赖文件之后执行）",
    )
    reverse_map: dict[str, list[str]] = Field(
        default_factory=dict,
        description="文件 → 依赖它的文件列表",
    )
    has_cycles: bool = False
    cycle_paths: list[list[str]] = Field(
        default_factory=list, description="检测到的循环依赖路径"
    )
    analysis_notes: str = Field(
        default="", description="LLM 生成的依赖关系说明"
    )


class DBChange(BaseModel):
    """一条具体的数据库对象变更记录。"""

    source_file: str
    object_full_name: str
    object_type: str
    operation: str
    before_state: str | None = Field(
        default=None, description="变更前对象状态描述（结合 DB 快照生成）"
    )
    after_state: str = Field(description="变更后对象状态描述")
    impact_scope: Literal["SCHEMA_ONLY", "DATA_ONLY", "SCHEMA_AND_DATA"]
    is_destructive: bool = Field(
        default=False, description="是否为破坏性操作（DROP/TRUNCATE）"
    )


class DBImpactAnalysis(BaseModel):
    """本次发版对数据库的全局影响汇总（结合执行顺序和 DB 快照）。"""

    changes: list[DBChange] = Field(default_factory=list)
    execution_sequence: list[str] = Field(description="文件执行顺序")
    new_objects: list[str] = Field(default_factory=list)
    modified_objects: list[str] = Field(default_factory=list)
    removed_objects: list[str] = Field(default_factory=list)
    data_affected_tables: list[str] = Field(default_factory=list)
    cross_file_dependencies: list[str] = Field(
        default_factory=list,
        description="跨文件依赖说明，如：file2 的 INSERT 依赖 file1 创建的 dim_date 表",
    )
    schema_changes_summary: str = ""
    data_changes_summary: str = ""
    overall_summary: str = ""
