"""
schemas/syntax_report.py
─────────────────────────
语法与代码质量分析报告的 Pydantic 模型。
由 syntax_analyzer.py 中的 LLM 结构化输出使用，
与 ReAct 变更校验 Agent 并行运行。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SyntaxFinding(BaseModel):
    """单条语法或代码质量问题。"""

    filename: str = Field(description="所在文件名")
    severity: Literal["ERROR", "WARNING", "INFO"] = Field(description="严重度")
    rule: str = Field(
        description=(
            "规则标识符，如 SELECT_STAR | NO_WHERE_DELETE | NO_WHERE_UPDATE | "
            "TRUNCATE_TABLE | DROP_NO_IF_EXISTS | CREATE_NO_IF_NOT_EXISTS | "
            "TYPE_CHANGE | NOT_NULL_NO_DEFAULT | NO_COMMENT | "
            "NAMING_CONVENTION | DML_TARGET_NOT_IN_DB | MISSING_INDEX"
        )
    )
    description: str = Field(description="问题详细描述，说明为什么是问题以及潜在影响")
    sql_snippet: str = Field(default="", description="相关 SQL 片段（建议不超过 10 行）")
    suggestion: str = Field(default="", description="具体修复建议，最好给出示例代码")


class FileSyntaxResult(BaseModel):
    """单个文件的质量统计摘要。"""

    filename: str
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    main_issues: str = Field(default="", description="该文件主要问题的一句话摘要，无问题则填空字符串")


class SyntaxReport(BaseModel):
    """
    SQL 脚本语法与代码质量分析报告。

    由 LLM 综合静态分析结果和文件内容，进行全面质量审查后产出。
    """

    quality_score: int = Field(
        description=(
            "综合质量评分 0-100。评分公式：从 100 开始，"
            "每个 ERROR -20，每个 WARNING -5，每个 INFO -1，最低 0"
        )
    )
    file_results: list[FileSyntaxResult] = Field(
        description="每个文件的质量统计，与输入文件一一对应"
    )
    findings: list[SyntaxFinding] = Field(
        default_factory=list,
        description="所有具体问题，按 severity 排列（ERROR → WARNING → INFO），同级按文件名排列",
    )

    # 专项安全风险计数
    no_where_deletes: int = Field(default=0, description="无 WHERE 的 DELETE 语句数量")
    no_where_updates: int = Field(default=0, description="无 WHERE 的 UPDATE 语句数量")
    truncates: int = Field(default=0, description="TRUNCATE 操作数量")
    drops: int = Field(default=0, description="DROP 操作数量")
    select_stars: int = Field(default=0, description="SELECT * 用法数量")

    improvement_suggestions: list[str] = Field(
        default_factory=list,
        description=(
            "最重要的 1-5 条改进建议，按优先级排列，"
            "格式：'**操作项**（优先级）：具体说明'"
        ),
    )
