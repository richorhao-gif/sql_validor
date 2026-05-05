from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConfirmedChange(BaseModel):
    """变更说明中已有对应实现的条目。"""

    point: str = Field(description="变更说明要点（摘自变更说明原文）")
    implementation: str = Field(description="对应实现，说明在哪个文件做了什么操作")


class ObjectChange(BaseModel):
    """数据库对象级别的变更（新增 / 修改 / 删除）。"""

    object_type: str = Field(description="TABLE | VIEW | FOREIGN TABLE | INDEX 等")
    schema_name: str = Field(description="所在 schema")
    object_name: str = Field(description="对象名（不含 schema）")
    file: str = Field(description="变更来源文件名")
    notes: str = Field(default="", description="补充说明，如重建模式、新增列名等")


class DMLChange(BaseModel):
    """DML 数据写入操作记录。"""

    table: str = Field(description="目标表全限定名，schema.table 格式")
    operation: str = Field(description="INSERT | UPDATE | DELETE | TRUNCATE | MERGE")
    estimated_rows: str = Field(
        default="未知",
        description="影响行数估算，如 '4 行（初始化数据）' 或 '未知（取决于运行时）'",
    )
    file: str = Field(description="来源文件名")


class Finding(BaseModel):
    """一条具体发现（风险、不一致、质量问题等）。"""

    category: Literal["RISK", "MISMATCH", "QUALITY", "INFO"] = Field(
        description="RISK：数据库风险；MISMATCH：与变更说明不符；QUALITY：代码质量；INFO：仅供参考"
    )
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(
        description="严重程度"
    )
    file: str = Field(
        description="涉及的文件名，如问题跨文件或全局则填 'all'"
    )
    description: str = Field(
        description="问题描述，具体说明是什么问题以及为什么是风险"
    )
    suggestion: str = Field(
        default="",
        description="改进建议，告诉开发者应该怎么修"
    )


class ValidationReport(BaseModel):
    """
    SQL 变更校验最终报告。

    由 ReAct Agent 使用工具完成所有分析后，作为结构化响应产出。
    包含变更核对结果、风险清单、执行顺序建议和总体判定。
    """

    verdict: Literal["PASS", "WARN", "FAIL"] = Field(
        description=(
            "PASS：变更符合预期，无 HIGH+ 风险；"
            "WARN：存在 HIGH 风险或轻微不一致；"
            "FAIL：存在 CRITICAL 风险或脚本与变更说明严重不符"
        )
    )
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = Field(
        description="整体风险等级，取所有 findings 中最高的 severity"
    )
    confidence: int = Field(
        default=0,
        description="LLM 对本次校验结论的置信度（0-100），综合信息完整性和歧义程度评估",
    )
    summary: str = Field(
        description="一句话概括本次变更的整体情况和判定理由，不超过 120 字"
    )
    execution_overview: str = Field(
        default="",
        description=(
            "执行概要段落（2-4 句话）：描述本次变更的整体方向、涉及的对象范围、"
            "执行顺序是否合理、以及总体风险判断"
        ),
    )
    execution_order: list[str] = Field(
        default_factory=list,
        description="推荐的 SQL 文件执行顺序（由文件间对象依赖关系决定，需先执行的文件在前）"
    )
    confirmed_changes: list[ConfirmedChange] = Field(
        default_factory=list,
        description="变更说明中有对应脚本实现的条目",
    )
    missing_changes: list[str] = Field(
        default_factory=list,
        description="变更说明中提到但在脚本中未找到对应实现的条目"
    )
    extra_changes: list[str] = Field(
        default_factory=list,
        description="脚本中有但变更说明未提及的变更（可能存在遗漏说明）"
    )
    high_risk_operations: list[str] = Field(
        default_factory=list,
        description=(
            "高风险操作列表，如：DROP 有下游依赖、无 WHERE 的 DML、"
            "修改列类型、新增 NOT NULL 列等"
        )
    )
    new_objects: list[ObjectChange] = Field(
        default_factory=list,
        description="本次新建的数据库对象列表",
    )
    altered_objects: list[ObjectChange] = Field(
        default_factory=list,
        description="本次修改的数据库对象列表（ALTER TABLE 等）",
    )
    dropped_objects: list[ObjectChange] = Field(
        default_factory=list,
        description="本次删除的数据库对象列表（DROP TABLE/VIEW 等）",
    )
    dml_changes: list[DMLChange] = Field(
        default_factory=list,
        description="本次 DML 数据写入操作汇总（INSERT / UPDATE / DELETE / TRUNCATE）",
    )
    findings: list[Finding] = Field(
        default_factory=list,
        description="所有具体发现，按 severity 由高到低排列（CRITICAL → HIGH → MEDIUM → LOW）"
    )
