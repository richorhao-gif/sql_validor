from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
    summary: str = Field(
        description="一句话概括本次变更的整体情况和判定理由，不超过 120 字"
    )
    execution_order: list[str] = Field(
        default_factory=list,
        description="推荐的 SQL 文件执行顺序（由文件间对象依赖关系决定，需先执行的文件在前）"
    )
    confirmed_changes: list[str] = Field(
        default_factory=list,
        description="变更说明中有对应脚本实现的条目，每条需说明具体文件和操作内容"
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
    findings: list[Finding] = Field(
        default_factory=list,
        description="所有具体发现，按 severity 由高到低排列（CRITICAL → HIGH → MEDIUM → LOW）"
    )
