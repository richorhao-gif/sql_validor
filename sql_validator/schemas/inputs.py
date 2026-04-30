from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class SQLFile(BaseModel):
    """单个 SQL 脚本文件。"""

    filename: str = Field(description="文件名（必须以 .sql 结尾）")
    content: str = Field(min_length=1, description="SQL 文件内容")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        v = v.strip()
        if not v.lower().endswith(".sql"):
            raise ValueError(f"文件名必须以 .sql 结尾，当前: {v!r}")
        # 禁止路径穿越
        if any(c in v for c in ("/", "\\", "..")):
            raise ValueError("文件名不允许包含路径分隔符或 '..'")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("SQL 文件内容不能为空或全空白")
        return v


class ValidationRequest(BaseModel):
    """智能体的唯一入口请求模型，承担所有输入校验责任。"""

    sql_files: list[SQLFile] = Field(
        min_length=1,
        description="本次发版的 SQL 脚本文件列表",
    )
    change_description: str = Field(
        min_length=10,
        description="本次发版的变更说明（不少于 10 字）",
    )

    @model_validator(mode="after")
    def validate_unique_filenames(self) -> "ValidationRequest":
        names = [f.filename for f in self.sql_files]
        if len(names) != len(set(names)):
            duplicates = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"存在重复的文件名: {duplicates}")
        return self

    def check_file_count(self, max_files: int) -> None:
        """业务层文件数量校验（需从 Settings 传入上限）。"""
        if len(self.sql_files) > max_files:
            raise ValueError(
                f"单次发版文件数超过上限（{len(self.sql_files)} > {max_files}），"
                "请拆分为多次发版"
            )


class ValidationResult(BaseModel):
    """智能体最终输出结果。"""

    change_report_path: str = Field(description="变更对比报告 MD 文件路径")
    syntax_report_path: str = Field(description="语法质量报告 MD 文件路径")
    verdict: str = Field(description="总体判定: PASS | WARN | FAIL")
    risk_level: str = Field(description="风险等级: LOW | MEDIUM | HIGH | CRITICAL")
    summary: str = Field(description="一句话摘要")
