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
    print(result.verdict)
"""
from __future__ import annotations

import os
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from sql_validator.agent import create_validator_agent
from sql_validator.config.settings import get_settings
from sql_validator.schemas.inputs import ValidationRequest, ValidationResult
from sql_validator.schemas.report import ValidationReport
from sql_validator.tools.analysis_tools import create_analysis_tools
from sql_validator.tools.db_tools import create_db_tools


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


def _write_report(report: ValidationReport, output_dir: str) -> str:
    """将 ValidationReport 写成 Markdown 文件，返回文件路径。"""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"validation_report_{ts}.md")

    verdict_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(report.verdict, "")
    risk_icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}.get(
        report.risk_level, ""
    )
    sev_icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}

    lines: list[str] = [
        "# SQL 变更校验报告",
        "",
        f"**判定：** {verdict_icon} `{report.verdict}`　　**风险等级：** {risk_icon} `{report.risk_level}`",
        "",
        f"> {report.summary}",
        "",
    ]

    if report.execution_order:
        lines += ["## 推荐执行顺序", ""]
        for i, fn in enumerate(report.execution_order, 1):
            lines.append(f"{i}. `{fn}`")
        lines.append("")

    if report.high_risk_operations:
        lines += ["## ⚠️ 高风险操作", ""]
        for op in report.high_risk_operations:
            lines.append(f"- {op}")
        lines.append("")

    if report.confirmed_changes:
        lines += ["## ✅ 已确认变更", ""]
        for c in report.confirmed_changes:
            lines.append(f"- {c}")
        lines.append("")

    if report.missing_changes:
        lines += ["## ❌ 未实现变更（变更说明有，脚本无）", ""]
        for c in report.missing_changes:
            lines.append(f"- {c}")
        lines.append("")

    if report.extra_changes:
        lines += ["## ⚠️ 额外变更（脚本有，变更说明未提及）", ""]
        for c in report.extra_changes:
            lines.append(f"- {c}")
        lines.append("")

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

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    return path


def run_validation(request: ValidationRequest) -> ValidationResult:
    """
    执行 SQL 变更校验，返回报告路径和总体判定结果。

    Args:
        request: 经过 Pydantic 校验的 ValidationRequest 对象

    Returns:
        ValidationResult（含报告路径、verdict、risk_level、摘要）
    """
    settings = get_settings()
    request.check_file_count(settings.max_sql_files)

    sql_files = [f.model_dump() for f in request.sql_files]

    # 构建工具集：DB 工具 + 纯代码分析工具（预加载 SQL 文件内容）
    db_tools = create_db_tools(dsn=settings.postgres_dsn)
    analysis_tools = create_analysis_tools(sql_files=sql_files)

    # 创建 ReAct Agent
    llm = settings.create_llm()
    agent = create_validator_agent(llm=llm, tools=db_tools + analysis_tools)

    # 构造任务消息
    file_list = "\n".join(
        f"  {i + 1}. {f['filename']}" for i, f in enumerate(sql_files)
    )
    task_message = HumanMessage(
        content=(
            f"## 本次发版信息\n\n"
            f"**变更说明：**\n{request.change_description}\n\n"
            f"**SQL 文件列表（共 {len(sql_files)} 个）：**\n{file_list}\n\n"
            f"请按照审查流程完成分析，先调用 parse_sql_files 获取脚本内容，"
            f"再查询数据库现状，最后给出完整的校验报告。"
        )
    )

    # 调用 Agent（recursion_limit 控制最大步数，防止无限循环）
    langfuse_cb, langfuse_client = _get_langfuse_callback(settings)
    invoke_config: dict = {"recursion_limit": 60, "run_name": "sql-validator"}
    if langfuse_cb:
        invoke_config["callbacks"] = [langfuse_cb]
        print("    [entrypoint] Langfuse 追踪已启用", flush=True)

    # 用 stream 替代 invoke，实时打印每步进度——否则 ReAct 循环在黑盒里跑，
    # 用户看不到任何输出，误以为程序卡死。
    #
    # stream_mode="values" 每个 chunk 是完整累积状态，messages 列表持续增长。
    # 用 seen_count 记录已处理消息数，每个 chunk 只处理新增消息，
    # 这样并行 tool_calls（一次 AIMessage 含多个 tool_call）和对应的多条
    # ToolMessage 都能逐条打印，不会因为只看 msgs[-1] 而吞掉中间返回值。
    print("    [agent] 开始 ReAct 循环…", flush=True)
    final_state: dict | None = None
    step = 0
    seen_count = 0  # 已打印的消息数量

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
                    # 无 tool_calls 的 AIMessage = ReAct 循环已结束
                    print("    [end]  ReAct 循环结束，生成结构化报告…", flush=True)
            elif isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "?")
                size = len(str(msg.content))
                # 找到对应的 step 编号（tool_call_id 与 AIMessage.tool_calls 对应）
                call_id = getattr(msg, "tool_call_id", None)
                print(f"          ◀ [{call_id[:8] if call_id else '?'}] {tool_name}: {size:,} 字节", flush=True)

        final_state = chunk

    # Langfuse 异步批量上报，stream 完成后必须 flush，否则 trace 数据丢失
    if langfuse_client:
        langfuse_client.flush()

    if final_state is None:
        raise RuntimeError("Agent stream 未产出任何输出，请检查 LLM 配置")

    # response_format 产出的结构化报告存于 state["structured_response"]
    report: ValidationReport = final_state["structured_response"]

    # 写 Markdown 报告
    report_path = _write_report(report, settings.output_dir)
    print(f"    [entrypoint] 报告已写入: {report_path}", flush=True)

    return ValidationResult(
        report_path=report_path,
        verdict=report.verdict,
        risk_level=report.risk_level,
        summary=report.summary,
    )
