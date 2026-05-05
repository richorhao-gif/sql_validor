from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChangeVerificationResult(BaseModel):
    """变更说明 vs 脚本实现的逐条对比校验结果。"""

    confirmed_items: list[str] = Field(
        default_factory=list,
        description="变更说明中有对应脚本实现的条目（含文件名和具体说明）",
    )
    missing_items: list[str] = Field(
        default_factory=list,
        description="变更说明提到但脚本中未找到实现的条目",
    )
    extra_items: list[str] = Field(
        default_factory=list,
        description="脚本中有但变更说明未提及的变更（可能被遗漏说明）",
    )
    risk_items: list[str] = Field(
        default_factory=list,
        description="高风险操作清单（DROP/TRUNCATE/无 WHERE 的 DML 等）",
    )
    verdict: Literal["PASS", "WARN", "FAIL"] = Field(
        description="PASS：完全吻合；WARN：轻微不一致；FAIL：严重遗漏或高危操作"
    )
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    confidence: int = Field(ge=0, le=100, description="LLM 置信度评分 0-100")
    analysis_notes: str = Field(description="对比分析的详细说明文字")


class SyntaxAnalysisSummary(BaseModel):
    """所有文件语法与代码质量问题的汇总评估。"""

    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    quality_score: int = Field(
        default=100,
        ge=0,
        le=100,
        description="综合质量评分 0-100（每 ERROR -10，每 WARNING -3，每 INFO -0.5）",
    )
    files_with_errors: list[str] = Field(default_factory=list)
    top_issues: list[str] = Field(
        default_factory=list, description="最重要的问题摘要条目"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="针对本次发版的改进建议"
    )


class SyntaxFileAnalysis(BaseModel):
    """单文件语法分析结果（LLM 输出，例行并发）。"""

    top_issues: list[str] = Field(
        default_factory=list, description="最重要的 3−5 条问题摘要，每条 ≤ 50 字"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="针对此文件的2−3 条改进建议，每条 ≤ 80 字"
    )
