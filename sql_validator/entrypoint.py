"""
entrypoint.py
──────────────
对外暴露的唯一调用入口，封装图的构建与调用逻辑。

使用方式：
    from sql_validator.entrypoint import run_validation
    from sql_validator.schemas import ValidationRequest, SQLFile

    request = ValidationRequest(
        sql_files=[SQLFile(filename="init.sql", content="CREATE TABLE ...")],
        change_description="新增用户分层维度表",
    )
    result = run_validation(request)
    print(result.change_report_path)
"""
from __future__ import annotations

from sql_validator.config.settings import get_settings
from sql_validator.graph.builder import build_graph
from sql_validator.graph.state import make_initial_state
from sql_validator.schemas.inputs import ValidationRequest, ValidationResult
from sql_validator.tools.db_tools import create_db_tools


def _get_langfuse_callback(settings=None):
    """
    若 .env 中配置了 LANGFUSE_* 变量，返回 LangFuse CallbackHandler；否则返回 None。
    LangFuse 是开源本地可观测平台（替代 LangSmith），需在 docker-compose.yml 中启动。
    """
    if settings is None:
        settings = get_settings()

    public_key = settings.langfuse_public_key
    secret_key = settings.langfuse_secret_key
    host       = settings.langfuse_host

    if not public_key or public_key.startswith("pk-lf-xxx"):
        return None

    try:
        # langfuse v3 SDK：先初始化单例客户端，再创建 CallbackHandler
        from langfuse import Langfuse  # type: ignore[import-untyped]
        from langfuse.langchain import CallbackHandler  # type: ignore[import-untyped]
        Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        return CallbackHandler()
    except ImportError:
        # langfuse 包未安装时静默跳过，不影响主流程
        return None


def run_validation(request: ValidationRequest) -> ValidationResult:
    """
    执行 SQL 变更校验，返回报告路径和总体判定结果。

    Args:
        request: 经过 Pydantic 校验的 ValidationRequest 对象

    Returns:
        ValidationResult（含报告路径、verdict、risk_level、摘要）
    """
    settings = get_settings()

    # 文件数量上限校验
    request.check_file_count(settings.max_sql_files)

    # 构建 LLM 和 DB 工具
    llm = settings.create_llm()
    db_tools = create_db_tools(dsn=settings.postgres_dsn)

    # 构建并编译图
    graph = build_graph(
        llm=llm,
        db_tools=db_tools,
        output_dir=settings.output_dir,
    )

    # 构造初始状态
    initial_state = make_initial_state(
        sql_files=[f.model_dump() for f in request.sql_files],
        change_description=request.change_description,
    )

    # 调用图（注入 LangFuse callback 实现全链路追踪）
    langfuse_cb = _get_langfuse_callback()
    invoke_config = {"callbacks": [langfuse_cb]} if langfuse_cb else {}
    final_state = graph.invoke(initial_state, config=invoke_config)

    # 提取结果
    verification = final_state.get("change_verification") or {}
    verdict = verification.get("verdict", "FAIL")
    risk_level = verification.get("risk_level", "HIGH")

    syntax_summary = final_state.get("syntax_summary") or {}
    quality_score = syntax_summary.get("quality_score", 0)

    summary = (
        f"变更校验：{verdict}（风险：{risk_level}），"
        f"代码质量：{quality_score}/100 分，"
        f"共 {len(request.sql_files)} 个文件"
    )

    # 从 report_generator 写入的 MD 文件路径中推断文件名
    # （report_generator 使用时间戳命名，此处从 state 中获取相对路径）
    from pathlib import Path
    from datetime import datetime

    # 找最新的报告文件
    out_dir = Path(settings.output_dir)
    change_reports = sorted(out_dir.glob("change_report_*.md"), reverse=True)
    syntax_reports = sorted(out_dir.glob("syntax_report_*.md"), reverse=True)

    change_path = str(change_reports[0]) if change_reports else f"{settings.output_dir}/change_report.md"
    syntax_path = str(syntax_reports[0]) if syntax_reports else f"{settings.output_dir}/syntax_report.md"

    return ValidationResult(
        change_report_path=change_path,
        syntax_report_path=syntax_path,
        verdict=verdict,
        risk_level=risk_level,
        summary=summary,
    )
