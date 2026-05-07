"""
entrypoint.py
──────────────
对外暴露的唯一调用入口。

使用方式：
    from sql_validator.entrypoint import run_validation
    from sql_validator.schemas.inputs import ValidationRequest, SQLFile

    request = ValidationRequest(
        sql_files=[SQLFile(filename="init.sql", content="CREATE TABLE ...", developer="张三")],
        change_description="新增用户分层维度表",
    )
    result = run_validation(request)
    print(result.report_path)
    print(result.syntax_report_path)
    print(result.verdict)
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from sql_validator.agents.change_agent import create_change_agent
from sql_validator.agents.syntax_agent import create_syntax_agent
from sql_validator.config.settings import get_settings
from sql_validator.report_writer import write_change_report, write_syntax_report
from sql_validator.schemas.inputs import ValidationRequest, ValidationResult
from sql_validator.schemas.report import ValidationReport
from sql_validator.schemas.syntax_report import SyntaxReport
from sql_validator.tools.analysis_tools import create_analysis_tools
from sql_validator.tools.db_tools import create_db_tools


# ─────────────────────────────────────────────────────────────────────────────
# Langfuse
# ─────────────────────────────────────────────────────────────────────────────

def _get_langfuse_callback(settings=None):
    """
    若 .env 中配置了 LANGFUSE_* 变量，返回 (CallbackHandler, Langfuse客户端)；
    否则返回 (None, None)。
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
# ReAct Agent stream 执行
# ─────────────────────────────────────────────────────────────────────────────

def _run_react_stream(
    agent: Any,
    task_message: HumanMessage,
    invoke_config: dict,
    label: str = "agent",
) -> dict:
    """
    消费 ReAct Agent stream，实时打印进度，返回最终状态。

    Args:
        agent       : create_react_agent 产出的 CompiledStateGraph
        task_message: 初始 HumanMessage（任务描述）
        invoke_config: LangGraph invoke 配置（recursion_limit 等）
        label       : 日志前缀，用于区分并行的两个 Agent 输出
    """
    print(f"    [{label}] 开始 ReAct 循环…", flush=True)
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
                        print(f"    [{label}][{step:02d}] ▶ {tc['name']}({args_preview})", flush=True)
                elif msg.content:
                    print(f"    [{label}] ReAct 循环结束，生成结构化报告…", flush=True)
            elif isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "?")
                size = len(str(msg.content))
                call_id = getattr(msg, "tool_call_id", None)
                print(
                    f"    [{label}]    ◀ [{call_id[:8] if call_id else '?'}] {tool_name}: {size:,} 字节",
                    flush=True,
                )

        final_state = chunk

    if final_state is None:
        raise RuntimeError(f"[{label}] Agent stream 未产出任何输出，请检查 LLM 配置")

    return final_state


# ─────────────────────────────────────────────────────────────────────────────
# 公开入口
# ─────────────────────────────────────────────────────────────────────────────

def run_validation(request: ValidationRequest) -> ValidationResult:
    """
    执行 SQL 变更校验，返回变更报告和语法报告路径及总体判定结果。

    变更校验 Agent（change_agent）与语法审查 Agent（syntax_agent）并行执行，互不阻塞。

    Args:
        request: 经过 Pydantic 校验的 ValidationRequest 对象

    Returns:
        ValidationResult（含两份报告路径、verdict、risk_level、摘要）
    """
    settings = get_settings()
    request.check_file_count(settings.max_sql_files)

    sql_files = [f.model_dump() for f in request.sql_files]

    # ── 构建共享工具集 ────────────────────────────────────────────────────────
    db_tools       = create_db_tools(dsn=settings.postgres_dsn)
    analysis_tools = create_analysis_tools(sql_files=sql_files)
    all_tools      = db_tools + analysis_tools

    # ── 创建共享 LLM（HTTP 连接池线程安全，两个 Agent 共用）────────────────
    llm          = settings.create_llm()
    change_agent = create_change_agent(llm=llm, tools=all_tools)
    syntax_agent = create_syntax_agent(llm=llm, tools=all_tools)

    # ── 构造各自的任务消息 ────────────────────────────────────────────────────
    file_list = "\n".join(
        f"  {i + 1}. {f['filename']}"
        + (f" (开发者：{f['developer']})" if f.get("developer") else "")
        for i, f in enumerate(sql_files)
    )

    change_task = HumanMessage(
        content=(
            f"## 本次发版信息\n\n"
            f"**变更说明：**\n{request.change_description}\n\n"
            f"**SQL 文件列表（共 {len(sql_files)} 个）：**\n{file_list}\n\n"
            f"请按照审查流程完成分析，先调用 parse_sql_files 获取脚本内容，"
            f"再查询数据库现状，最后给出完整的校验报告。"
        )
    )

    syntax_task = HumanMessage(
        content=(
            f"## 本次发版信息\n\n"
            f"**SQL 文件列表（共 {len(sql_files)} 个）：**\n{file_list}\n\n"
            f"请先调用 parse_sql_files 获取所有文件内容，"
            f"然后按照语法审查流程和数仓发版规范（RULE4.x）逐项完成审查，"
            f"给出完整的 SyntaxReport。"
        )
    )

    langfuse_cb, langfuse_client = _get_langfuse_callback(settings)
    base_config: dict = {"recursion_limit": 60, "run_name": "sql-validator"}
    if langfuse_cb:
        base_config["callbacks"] = [langfuse_cb]
        print("    [entrypoint] Langfuse 追踪已启用", flush=True)

    # ── 并行执行：变更校验 Agent + 语法审查 Agent ─────────────────────────
    print("    [entrypoint] 启动并行分析（change_agent + syntax_agent）…", flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_change = pool.submit(
            _run_react_stream, change_agent, change_task,
            {**base_config, "run_name": "change-agent"}, "change",
        )
        future_syntax = pool.submit(
            _run_react_stream, syntax_agent, syntax_task,
            {**base_config, "run_name": "syntax-agent"}, "syntax",
        )

        change_state = future_change.result()
        try:
            syntax_state: dict | None = future_syntax.result()
        except Exception as exc:  # noqa: BLE001
            print(f"    [syntax] ⚠ 语法审查失败（不影响变更报告）: {exc}", flush=True)
            syntax_state = None

    print("    [entrypoint] 两项分析已完成，生成报告…", flush=True)

    if langfuse_client:
        langfuse_client.flush()

    # ── 取出结构化报告 ────────────────────────────────────────────────────────
    change_report: ValidationReport = change_state["structured_response"]
    syntax_report: SyntaxReport | None = (
        syntax_state["structured_response"] if syntax_state else None
    )

    # ── 写出 Markdown 报告 ────────────────────────────────────────────────────
    report_path = write_change_report(change_report, sql_files, settings.output_dir)
    syntax_report_path: str | None = None
    if syntax_report is not None:
        syntax_report_path = write_syntax_report(syntax_report, sql_files, settings.output_dir)

    print(f"    [entrypoint] 变更报告: {report_path}", flush=True)
    if syntax_report_path:
        print(f"    [entrypoint] 语法报告: {syntax_report_path}", flush=True)
    else:
        print("    [entrypoint] 语法报告未生成", flush=True)

    return ValidationResult(
        report_path=report_path,
        syntax_report_path=syntax_report_path,
        verdict=change_report.verdict,
        risk_level=change_report.risk_level,
        summary=change_report.summary,
    )


