"""
syntax_analyzer.py
────────────────────
SQL 脚本语法与代码质量分析器。

与 ReAct 变更校验 Agent 并行运行，无需工具调用，直接通过单次
LLM 结构化输出完成分析。

流程：
  1. 对所有文件运行静态分析（sqlglot AST + 质量规则）
  2. 将文件内容 + 静态分析结果发送给 LLM
  3. LLM 产出结构化 SyntaxReport

调用方式：
  from sql_validator.syntax_analyzer import run_syntax_analysis
  report = run_syntax_analysis(sql_files, llm)
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from sql_validator.core.sql_parser import parse_sql_file
from sql_validator.prompts.syntax import SYNTAX_PROMPT
from sql_validator.schemas.syntax_report import SyntaxReport


def run_syntax_analysis(
    sql_files: list[dict[str, Any]],
    llm: BaseChatModel,
) -> SyntaxReport:
    """
    对本次所有 SQL 文件执行语法与代码质量分析。

    Args:
        sql_files : SQLFile.model_dump() 列表，包含 filename 和 content 字段
        llm       : 已配置的 ChatModel（与 ReAct Agent 共享同一实例）

    Returns:
        SyntaxReport 结构化分析报告
    """
    # ── 第一步：静态分析（sqlglot AST + 质量规则）─────────────────────────
    static_findings: list[dict] = []
    for f in sql_files:
        _, issues = parse_sql_file(f)
        for issue in issues:
            static_findings.append(issue.model_dump())

    # ── 第二步：组装 LLM 请求消息 ──────────────────────────────────────────
    files_block = "\n\n".join(
        f"### 文件 {i + 1}：`{f['filename']}`\n```sql\n{f['content']}\n```"
        for i, f in enumerate(sql_files)
    )
    static_block = json.dumps(static_findings, ensure_ascii=False, indent=2)

    user_msg = HumanMessage(
        content=(
            f"## 本次发版 SQL 文件（共 {len(sql_files)} 个）\n\n"
            f"{files_block}\n\n"
            f"---\n\n"
            f"## 静态分析结果\n\n"
            f"```json\n{static_block}\n```\n\n"
            f"请综合以上信息，产出完整的 SyntaxReport。"
        )
    )

    # ── 第三步：结构化 LLM 调用 ────────────────────────────────────────────
    print(
        f"    [syntax] 开始语法质量分析（{len(sql_files)} 个文件，"
        f"静态发现 {len(static_findings)} 条问题）…",
        flush=True,
    )
    structured_llm = llm.with_structured_output(SyntaxReport)
    result = structured_llm.invoke([SystemMessage(content=SYNTAX_PROMPT), user_msg])
    print(
        f"    [syntax] 语法分析完成，质量评分 {result.quality_score}/100，"
        f"发现 {len(result.findings)} 个问题",
        flush=True,
    )
    return result
