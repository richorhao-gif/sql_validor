from __future__ import annotations

from pydantic import BaseModel, Field


class DBColumn(BaseModel):
    """数据库表的列信息。"""

    name: str
    data_type: str
    is_nullable: bool = True
    column_default: str | None = None
    character_maximum_length: int | None = None
    ordinal_position: int = 0


class DBForeignKey(BaseModel):
    """外键约束信息。"""

    constraint_name: str
    column_name: str
    references_schema: str
    references_table: str
    references_column: str


class DBIndex(BaseModel):
    """索引信息。"""

    index_name: str
    columns: list[str] = Field(default_factory=list)
    is_unique: bool = False
    index_type: str = "btree"


class DBTable(BaseModel):
    """数据库表的完整结构快照。"""

    schema_name: str
    table_name: str
    full_name: str = Field(description="schema_name.table_name 格式的全限定名")
    columns: list[DBColumn] = Field(default_factory=list)
    primary_keys: list[str] = Field(default_factory=list)
    foreign_keys: list[DBForeignKey] = Field(default_factory=list)
    indexes: list[DBIndex] = Field(default_factory=list)

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


class DBView(BaseModel):
    """视图信息。"""

    schema_name: str
    view_name: str
    full_name: str
    view_definition: str | None = None


class DBRoutine(BaseModel):
    """存储过程或函数信息。"""

    schema_name: str
    routine_name: str
    routine_type: str = Field(description="FUNCTION | PROCEDURE")
    full_name: str


class DBSnapshot(BaseModel):
    """
    db_context_agent 查询完毕后产出的数据库状态快照。
    字典的 key 统一使用 schema.object_name 全限定名格式。
    """

    tables: dict[str, DBTable] = Field(default_factory=dict)
    views: dict[str, DBView] = Field(default_factory=dict)
    routines: dict[str, DBRoutine] = Field(default_factory=dict)
    available_schemas: list[str] = Field(default_factory=list)
    agent_query_notes: str = Field(
        default="",
        description="Agent 记录的查询过程说明（追查了哪些隐式依赖、外键等）",
    )
