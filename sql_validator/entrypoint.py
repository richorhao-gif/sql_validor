"""
entrypoint.py
──────────────
对外暴露的唯一调用入口。

使用方式：
    from sql_validator.entrypoint import run_validation
    from sql_validator.schemas.inputs import ValidationRequest, SQLFile

    request = ValidationRequest(
        sql_files=[SQLFile(filename="init.sql", content="CREATE TABLE ...")],
        change_description="新增用户分层维度表",
    )
    result = run_validation(request)
    print(result.report_path)
    print(result.syntax_report_path)
    print(result.verdict)
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from sql_validator.agent import create_validator_agent
from sql_validator.config.settings import get_settings
from sql_validator.schemas.inputs import ValidationRequest, ValidationResult
from sql_validator.schemas.report import ValidationReport
from sql_validator.schemas.syntax_report import SyntaxReport
from sql_validator.syntax_analyzer import run_syntax_analysis
from sql_validator.tools.analysis_tools import create_analysis_tools
from sql_validator.tools.db_tools import create_db_tools


# ─────────────────────────────────────────────────────────────────────────────
# Langfuse
# ─────────────────────────────────────────────────────────────────────────────

def _get_langfuse_callback(settings=None):
    """
    若 .env 中配置了 LANGFUSE_* 变量，返回 (CallbackHandler, Langfuse客户端)；
    否则返回 (None, None)。

    返回客户端引用是为了在 agent.invoke() 完成后调用 client.flush()，
    确保异步批量上报的 trace 数据不丢失。
    """
    if settings is None:
        settings = get_settings()

    if not settings.langfuse_public_key or settings.langfuse_public_key.startswith("pk-lf-xxx"):
        return None, None

    try:
        from langfuse import Langfuse  # type: ignore[import-untyped]
        from langfuse.langchain import CallbackHandler  # type: ignore[import-untyped]

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        return CallbackHandler(), client
    except ImportError:
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# 变更校验报告 Markdown 生成
# ─────────────────────────────────────────────────────────────────────────────

def _write_report(report: ValidationReport, sql_file_count: int, output_dir: str) -> str:
    """将 ValidationReport 写成详细 Markdown 文件，返回文件路径。"""
    os.makedirs(output_dir, exist_ok=True)
    ts_file = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_display = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = os.path.join(output_dir, f"change_report_{ts_file}.md")

    verdict_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(report.verdict, "")
    risk_icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}.get(report.risk_level, "")
    sev_icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}
    confidence_str = f"{report.confidence}%" if report.confidence else "—"

    lines: list[str] = [
        "# SQL 脚本变更说明对比报告",
        "",
        "| 字段 | 值 |",
        "|---|---|",
        f"| 生成时间 | {ts_display} |",
        f"| SQL 文件数 | {sql_file_count} |",
        f"| 总体判定 | {verdict_icon} **{report.verdict}** |",
        f"| 风险等级 | {risk_icon} {report.risk_level} |",
        f"| LLM 置信度 | {confidence_str} |",
        "",
        "---",
        "",
    ]

    # 执行概要
    lines += ["## 执行概要", ""]
    if report.execution_overview:
        lines += [report.execution_overview, ""]
    elif report.summary:
        lines += [report.summary, ""]

    if report.execution_order:
        lines += ["> **推荐执行顺序：** " + " → ".join(f"`{f}`" for f in report.execution_order), ""]

    lines += ["---", ""]

    # 变更覆盖情况
    lines += ["## 变更覆盖情况", ""]

    lines += [f"### ✅ 已确认（{len(report.confirmed_changes)} 项）", ""]
    if report.confirmed_changes:
        lines += ["| 变更说明要点 | 对应实现 |", "|---|---|"]
        for c in report.confirmed_changes:
            lines.append(f"| {c.point} | {c.implementation} |")
    else:
        lines.append("无已确认变更。")
    lines.append("")

    lines += [f"### ❌ 遗漏（{len(report.missing_changes)} 项）", ""]
    if report.missing_changes:
        for c in report.missing_changes:
            lines.append(f"- {c}")
    else:
        lines.append("无遗漏项。")
    lines.append("")

    lines += [f"### ⚠️ 额外变更（{len(report.extra_changes)} 项）", ""]
    if report.extra_changes:
        for c in report.extra_changes:
            lines.append(f"- {c}")
    else:
        lines.append("无额外变更。")
    lines += ["", "---", ""]

    # 高风险操作
    lines += ["## 🔴 高风险操作清单", ""]
    if report.high_risk_operations:
        lines += ["| # | 操作描述 |", "|---|---|"]
        for i, op in enumerate(report.high_risk_operations, 1):
            lines.append(f"| {i} | {op} |")
    else:
        lines.append("无高风险操作。")
    lines += ["", "---", ""]

    # 数据库变更影响详情
    lines += ["## 数据库变更影响详情", ""]

    lines += [f"### 新增对象（{len(report.new_objects)} 个）", ""]
    if report.new_objects:
        lines += ["| 对象类型 | Schema | 对象名 | 所在文件 | 备注 |", "|---|---|---|---|---|"]
        for o in report.new_objects:
            lines.append(f"| {o.object_type} | `{o.schema_name}` | `{o.object_name}` | `{o.file}` | {o.notes} |")
    else:
        lines.append("无。")
    lines.append("")

    lines += [f"### 修改对象（{len(report.altered_objects)} 个）", ""]
    if report.altered_objects:
        lines += ["| 对象类型 | Schema | 对象名 | 所在文件 | 备注 |", "|---|---|---|---|---|"]
        for o in report.altered_objects:
            lines.append(f"| {o.object_type} | `{o.schema_name}` | `{o.object_name}` | `{o.file}` | {o.notes} |")
    else:
        lines.append("无。")
    lines.append("")

    lines += [f"### 删除对象（{len(report.dropped_objects)} 个）", ""]
    if report.dropped_objects:
        lines += ["| 对象类型 | Schema | 对象名 | 所在文件 | 备注 |", "|---|---|---|---|---|"]
        for o in report.dropped_objects:
            lines.append(f"| {o.object_type} | `{o.schema_name}` | `{o.object_name}` | `{o.file}` | {o.notes} |")
    else:
        lines.append("无。")
    lines.append("")

    lines += ["### DML 数据影响", ""]
    if report.dml_changes:
        lines += ["| 表名 | 操作 | 影响行数估算 | 所在文件 |", "|---|---|---|---|"]
        for d in report.dml_changes:
            lines.append(f"| `{d.table}` | {d.operation} | {d.estimated_rows} | `{d.file}` |")
    else:
        lines.append("无 DML 操作。")
    lines += ["", "---", ""]

    # 详细 findings
    if report.findings:
        lines += ["## 详细发现", ""]
        for finding in report.findings:
            icon = sev_icon.get(finding.severity, "")
            lines += [
                f"### {icon} [{finding.severity}] {finding.category} — `{finding.file}`",
                "",
                finding.description,
            ]
            if finding.suggestion:
                lines += ["", f"**建议：** {finding.suggestion}"]
            lines.append("")
        lines += ["---", ""]

    # 审核结论
    conclusion_map = {
        "PASS": "✅ 审核结论：建议正常发版",
        "WARN": "⚠️ 审核结论：建议审查高风险项后再发版",
        "FAIL": "❌ 审核结论：存在阻断性风险，暂不建议发版",
    }
    lines += [
        "## 审核结论",
        "",
        f"> **{conclusion_map.get(report.verdict, report.verdict)}**",
        ">",
        f"> {report.summary}",
        "",
        "---",
        "",
        "*本报告由 SQL 变更校验智能体自动生成*",
    ]

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    return path


# ─────────────────────────────────────────────────────────────────────────────
# 语法质量报告 Markdown 生成
# ─────────────────────────────────────────────────────────────────────────────

def _write_syntax_report(report: SyntaxReport, output_dir: str) -> str:
    """将 SyntaxReport 写成 Markdown 文件，返回文件路径。"""
    os.makedirs(output_dir, exist_ok=True)
    ts_file = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_display = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = os.path.join(output_dir, f"syntax_report_{ts_file}.md")

    errors   = [f for f in report.findings if f.severity == "ERROR"]
    warnings = [f for f in report.findings if f.severity == "WARNING"]
    infos    = [f for f in report.findings if f.severity == "INFO"]

    score = report.quality_score
    score_icon = "🟢" if score >= 85 else ("🟡" if score >= 60 else "🔴")

    lines: list[str] = [
        "# SQL 脚本语法与质量分析报告",
        "",
        "| 字段 | 值 |",
        "|---|---|",
        f"| 生成时间 | {ts_display} |",
        f"| 分析文件数 | {len(report.file_results)} |",
        f"| 综合质量评分 | {score_icon} **{score} / 100** |",
        f"| ERROR 数 | {len(errors)} |",
        f"| WARNING 数 | {len(warnings)} |",
        f"| INFO 数 | {len(infos)} |",
        "",
        "---",
        "",
    ]

    # 各文件概览表
    lines += ["## 各文件质量概览", ""]
    lines += ["| 文件名 | ERROR | WARNING | INFO | 主要问题摘要 |", "|---|---|---|---|---|"]
    for fr in report.file_results:
        lines.append(
            f"| `{fr.filename}` | {fr.error_count} | {fr.warning_count} "
            f"| {fr.info_count} | {fr.main_issues} |"
        )
    lines += ["", "---", ""]

    # ERROR
    lines += [f"## 🔴 ERROR 级问题（{len(errors)} 项）", ""]
    if errors:
        for i, f in enumerate(errors, 1):
            lines += [
                f"### E{i} · `{f.filename}` — {f.rule}",
                "",
                f"**规则：** `{f.rule}`  ",
                f"**严重度：** ERROR  ",
                f"**描述：** {f.description}",
            ]
            if f.sql_snippet:
                lines += ["", "**涉及片段：**", f"```sql\n{f.sql_snippet}\n```"]
            if f.suggestion:
                lines += ["", f"**建议：** {f.suggestion}"]
            lines.append("")
    else:
        lines.append("本次发版无 ERROR 级语法问题。")
    lines += ["", "---", ""]

    # WARNING
    lines += [f"## 🟡 WARNING 级问题（{len(warnings)} 项）", ""]
    if warnings:
        for i, f in enumerate(warnings, 1):
            lines += [
                f"### W{i} · `{f.filename}` — {f.rule}",
                "",
                f"**规则：** `{f.rule}`  ",
                f"**严重度：** WARNING  ",
                f"**描述：** {f.description}",
            ]
            if f.sql_snippet:
                lines += ["", "**涉及片段：**", f"```sql\n{f.sql_snippet}\n```"]
            if f.suggestion:
                lines += ["", f"**建议：** {f.suggestion}"]
            lines.append("")
    else:
        lines.append("本次发版无 WARNING 级问题。")
    lines += ["", "---", ""]

    # INFO
    lines += [f"## 🔵 INFO 级问题（{len(infos)} 项）", ""]
    if infos:
        lines += ["| # | 文件 | 规则 | 描述 |", "|---|---|---|---|"]
        for i, f in enumerate(infos, 1):
            desc_short = f.description[:80] + ("…" if len(f.description) > 80 else "")
            lines.append(f"| {i} | `{f.filename}` | `{f.rule}` | {desc_short} |")
    else:
        lines.append("无 INFO 级问题。")
    lines += ["", "---", ""]

    # 专项分析
    lines += [
        "## 专项分析",
        "",
        "### 🛡️ 安全风险",
        "",
        "| 风险类型 | 数量 | 详情 |",
        "|---|---|---|",
        f"| 无 WHERE 的 DELETE | {report.no_where_deletes} | {'见上方 WARNING' if report.no_where_deletes else '—'} |",
        f"| 无 WHERE 的 UPDATE | {report.no_where_updates} | {'见上方 WARNING' if report.no_where_updates else '—'} |",
        f"| TRUNCATE 操作 | {report.truncates} | {'见上方 WARNING' if report.truncates else '—'} |",
        f"| DROP 操作 | {report.drops} | {'见上方 WARNING' if report.drops else '—'} |",
        "",
        "### ⚡ 性能规范",
        "",
        "| 问题类型 | 数量 | 详情 |",
        "|---|---|---|",
        f"| SELECT * | {report.select_stars} | {'见上方 WARNING' if report.select_stars else '—'} |",
        "",
        "---",
        "",
    ]

    # 改进建议
    lines += ["## 改进建议", ""]
    if report.improvement_suggestions:
        for i, s in enumerate(report.improvement_suggestions, 1):
            lines.append(f"{i}. {s}")
    else:
        lines.append("暂无改进建议。")
    lines += [
        "",
        "---",
        "",
        "*本报告由 SQL 变更校验智能体自动生成*",
    ]

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    return path


# ─────────────────────────────────────────────────────────────────────────────
# ReAct Agent stream 执行（在线程中运行）
# ─────────────────────────────────────────────────────────────────────────────

def _run_react_stream(
    agent: Any,
    task_message: HumanMessage,
    invoke_config: dict,
) -> dict:
    """
    在独立线程中消费 ReAct Agent stream，实时打印进度，返回最终状态。
    抽取为独立函数是为了能与语法分析并行执行。
    """
    print("    [agent] 开始 ReAct 循环…", flush=True)
    final_state: dict | None = None
    step = 0
    seen_count = 0

    for chunk in agent.stream(
        {"messages": [task_message]},
        config=invoke_config,
        stream_mode="values",
    ):
        msgs = chunk.get("messages", [])
        new_msgs = msgs[seen_count:]
        seen_count = len(msgs)

        for msg in new_msgs:
            if isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None) or []
                if tool_calls:
                    for tc in tool_calls:
                        step += 1
                        args_preview = ", ".join(
                            f"{k}={str(v)[:50]!r}"
                            for k, v in (tc.get("args") or {}).items()
                        )
                        print(f"    [{step:02d}] ▶ {tc['name']}({args_preview})", flush=True)
                elif msg.content:
                    print("    [end]  ReAct 循环结束，生成结构化报告…", flush=True)
            elif isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "?")
                size = len(str(msg.content))
                call_id = getattr(msg, "tool_call_id", None)
                print(
                    f"          ◀ [{call_id[:8] if call_id else '?'}] {tool_name}: {size:,} 字节",
                    flush=True,
                )

        final_state = chunk

    if final_state is None:
        raise RuntimeError("Agent stream 未产出任何输出，请检查 LLM 配置")

    return final_state


# ─────────────────────────────────────────────────────────────────────────────
# 公开入口
# ─────────────────────────────────────────────────────────────────────────────

def run_validation(request: ValidationRequest) -> ValidationResult:
    """
    执行 SQL 变更校验，返回变更报告和语法报告路径及总体判定结果。

    ReAct 变更校验 Agent 与 LLM 语法分析并行执行，互不阻塞。

    Args:
        request: 经过 Pydantic 校验的 ValidationRequest 对象

    Returns:
        ValidationResult（含两份报告路径、verdict、risk_level、摘要）
    """
    settings = get_settings()
    request.check_file_count(settings.max_sql_files)

    sql_files = [f.model_dump() for f in request.sql_files]

    # 构建工具集：DB 工具 + 纯代码分析工具
    db_tools = create_db_tools(dsn=settings.postgres_dsn)
    analysis_tools = create_analysis_tools(sql_files=sql_files)

    # 创建共享 LLM 实例（两个并行任务共用，HTTP 连接池线程安全）
    llm = settings.create_llm()
    agent = create_validator_agent(llm=llm, tools=db_tools + analysis_tools)

    # 构造 ReAct 任务消息
    file_list = "\n".join(f"  {i + 1}. {f['filename']}" for i, f in enumerate(sql_files))
    task_message = HumanMessage(
        content=(
            f"## 本次发版信息\n\n"
            f"**变更说明：**\n{request.change_description}\n\n"
            f"**SQL 文件列表（共 {len(sql_files)} 个）：**\n{file_list}\n\n"
            f"请按照审查流程完成分析，先调用 parse_sql_files 获取脚本内容，"
            f"再查询数据库现状，最后给出完整的校验报告。"
        )
    )

    langfuse_cb, langfuse_client = _get_langfuse_callback(settings)
    invoke_config: dict = {"recursion_limit": 60, "run_name": "sql-validator"}
    if langfuse_cb:
        invoke_config["callbacks"] = [langfuse_cb]
        print("    [entrypoint] Langfuse 追踪已启用", flush=True)

    # ── 并行执行：ReAct Agent + 语法分析 ─────────────────────────────────
    print("    [entrypoint] 启动并行分析（变更校验 + 语法质量）…", flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_react = pool.submit(_run_react_stream, agent, task_message, invoke_config)
        future_syntax = pool.submit(run_syntax_analysis, sql_files, llm)

        final_state = future_react.result()   # 等待 ReAct 完成（带进度输出）
        try:
            syntax_report: SyntaxReport | None = future_syntax.result()  # 等待语法分析完成
        except Exception as exc:  # noqa: BLE001
            print(f"    [syntax] ⚠ 语法分析失败（不影响变更报告）: {exc}", flush=True)
            syntax_report = None

    print("    [entrypoint] 两项分析已完成，生成报告…", flush=True)

    # Langfuse flush（stream 结束后批量上报）
    if langfuse_client:
        langfuse_client.flush()

    # 取出结构化变更报告
    report: ValidationReport = final_state["structured_response"]

    # 写两份 Markdown 报告
    report_path = _write_report(report, len(sql_files), settings.output_dir)
    syntax_report_path: str | None = None
    if syntax_report is not None:
        syntax_report_path = _write_syntax_report(syntax_report, settings.output_dir)

    print(f"    [entrypoint] 变更报告: {report_path}", flush=True)
    if syntax_report_path:
        print(f"    [entrypoint] 语法报告: {syntax_report_path}", flush=True)
    else:
        print("    [entrypoint] 语法报告未生成", flush=True)

    return ValidationResult(
        report_path=report_path,
        syntax_report_path=syntax_report_path,
        verdict=report.verdict,
        risk_level=report.risk_level,
        summary=report.summary,
    )

