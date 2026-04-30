"""
scripts/run_test.py
────────────────────
本地集成测试快捷运行脚本。

功能：
  1. 从 tests/fixtures/ 加载 3 个模拟变更 SQL 文件
  2. 调用 sql_validator.entrypoint.run_validation 执行完整智能体流程
  3. 打印结构化执行摘要和报告路径

前提条件：
  - Docker 服务已启动（docker compose up -d）
  - .env 中 POSTGRES_DSN / LLM_API_KEY 已正确配置
  - 已安装依赖（uv sync）

运行方式：
  uv run python scripts/run_test.py
  uv run python scripts/run_test.py --verbose   # 打印完整状态快照
"""
from __future__ import annotations

import argparse
import sys
import textwrap
import time
from pathlib import Path

# ── 根路径注入（确保从项目根运行时可找到 sql_validator 包）────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# 彩色终端输出工具（无外部依赖）
# ─────────────────────────────────────────────────────────────────────────────

class _Colors:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    GREY   = "\033[90m"


def _c(text: str, color: str) -> str:
    return f"{color}{text}{_Colors.RESET}"


def _section(title: str) -> None:
    print(f"\n{_c('━' * 60, _Colors.CYAN)}")
    print(_c(f"  {title}", _Colors.BOLD + _Colors.CYAN))
    print(_c('━' * 60, _Colors.CYAN))


def _ok(msg: str)   -> None: print(_c(f"  ✔  {msg}", _Colors.GREEN))
def _warn(msg: str) -> None: print(_c(f"  ⚠  {msg}", _Colors.YELLOW))
def _err(msg: str)  -> None: print(_c(f"  ✘  {msg}", _Colors.RED))
def _info(msg: str) -> None: print(_c(f"     {msg}", _Colors.GREY))


# ─────────────────────────────────────────────────────────────────────────────
# 加载 Fixture SQL 文件
# ─────────────────────────────────────────────────────────────────────────────

FIXTURES_DIR = ROOT / "tests" / "fixtures"

FIXTURE_FILES = [
    "01_alter_dim_user_level_add_discount.sql",
    "02_create_fact_user_daily_summary.sql",
    "03_create_view_vw_user_level_revenue.sql",
]

CHANGE_DESCRIPTION = (
    "本次发版共 3 个 SQL 脚本：\n"
    "① 为用户等级维度表(dim_user_level)新增 discount_rate 折扣率字段，并初始化各等级折扣值；\n"
    "② 新建用户每日汇总宽表 fact_user_daily_summary，"
    "依赖现有维度表 dim_user_level 和 dim_date；\n"
    "③ 新建视图 vw_user_level_revenue，引用脚本①新增的 discount_rate 字段，"
    "依赖现有的 fact_orders 和 dim_user_level。\n"
    "注意：脚本③必须在脚本①之后执行（存在跨脚本字段依赖）。"
)


def load_sql_files() -> list[dict]:
    """加载 fixtures 目录下的测试 SQL 文件。"""
    sql_files = []
    for fname in FIXTURE_FILES:
        fpath = FIXTURES_DIR / fname
        if not fpath.exists():
            _err(f"找不到 fixture 文件: {fpath}")
            sys.exit(1)
        content = fpath.read_text(encoding="utf-8")
        sql_files.append({"filename": fname, "content": content})
        _ok(f"已加载: {fname} ({len(content)} 字符)")
    return sql_files


# ─────────────────────────────────────────────────────────────────────────────
# 打印运行结果
# ─────────────────────────────────────────────────────────────────────────────

_VERDICT_COLOR = {
    "PASS": _Colors.GREEN,
    "WARN": _Colors.YELLOW,
    "FAIL": _Colors.RED,
}
_RISK_COLOR = {
    "LOW":      _Colors.GREEN,
    "MEDIUM":   _Colors.YELLOW,
    "HIGH":     _Colors.RED,
    "CRITICAL": _Colors.RED + _Colors.BOLD,
}


def print_result(result, final_state: dict, verbose: bool, elapsed: float) -> None:
    """输出格式化的校验结果。"""
    verdict_color = _VERDICT_COLOR.get(result.verdict, _Colors.GREY)
    risk_color    = _RISK_COLOR.get(result.risk_level, _Colors.GREY)

    _section("校验结果摘要")
    print(f"  总体判定 : {_c(result.verdict,    verdict_color + _Colors.BOLD)}")
    print(f"  风险等级 : {_c(result.risk_level, risk_color    + _Colors.BOLD)}")
    print(f"  耗时     : {elapsed:.1f} 秒")

    if result.summary:
        _section("分析摘要")
        for line in textwrap.wrap(result.summary, width=70):
            _info(line)

    errors: list[str] = final_state.get("errors", [])
    if errors:
        _section("执行过程中的错误/警告")
        for e in errors:
            _warn(e)

    _section("输出报告路径")
    _ok(f"变更对比报告 : {result.change_report_path}")
    _ok(f"语法质量报告 : {result.syntax_report_path}")

    dep_graph = final_state.get("dependency_graph") or {}
    if dep_graph.get("execution_order"):
        _section("推断执行顺序")
        order = " → ".join(dep_graph["execution_order"])
        _info(order)
    if dep_graph.get("has_cycles"):
        _warn(f"检测到循环依赖！路径: {dep_graph.get('cycle_paths')}")

    if verbose:
        _section("完整状态快照（--verbose）")
        import json
        # 过滤掉过长的 messages 字段
        snapshot = {k: v for k, v in final_state.items() if k != "messages"}
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))


# ─────────────────────────────────────────────────────────────────────────────
# 连通性预检
# ─────────────────────────────────────────────────────────────────────────────

def preflight_check(dsn: str) -> bool:
    """简单 SELECT 1 验证数据库是否可连通。"""
    try:
        import psycopg  # type: ignore[import-untyped]
        with psycopg.connect(dsn) as conn:
            cur = conn.execute("SELECT current_database(), current_user, version()")
            row = cur.fetchone()
            if row:
                _ok(f"DB 连通成功 | 库: {row[0]} | 用户: {row[1]}")
                _info(f"PostgreSQL 版本: {row[2][:60]}")
        return True
    except Exception as exc:
        _err(f"数据库连通性检查失败: {exc}")
        _warn("请确认 Docker 服务已启动：docker compose up -d")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="SQL 变更校验智能体 — 本地集成测试")
    parser.add_argument("--verbose", "-v", action="store_true", help="打印完整状态快照")
    parser.add_argument("--skip-preflight", action="store_true", help="跳过数据库连通性预检")
    args = parser.parse_args()

    print(_c("\n  SQL 变更校验智能体 — 本地集成测试", _Colors.BOLD))
    print(_c("  ─────────────────────────────────────", _Colors.CYAN))

    # ── 加载配置 ────────────────────────────────────────────────────────────
    _section("加载配置")
    try:
        from sql_validator.config.settings import get_settings
        settings = get_settings()
        _ok(f"LLM 提供商 : {settings.llm_provider}")
        _ok(f"模型       : {settings.llm_model}")
        _ok(f"DB DSN     : {settings.postgres_dsn[:40]}...")
    except Exception as exc:
        _err(f"配置加载失败: {exc}")
        _warn("请检查 .env 文件中 LLM_API_KEY 和 POSTGRES_DSN 是否已填写")
        sys.exit(1)

    # ── 数据库预检 ──────────────────────────────────────────────────────────
    if not args.skip_preflight:
        _section("数据库连通性预检")
        if not preflight_check(settings.postgres_dsn):
            sys.exit(1)

    # ── 加载 SQL fixture 文件 ────────────────────────────────────────────────
    _section("加载测试 SQL 变更文件")
    sql_files = load_sql_files()

    # ── 显示变更说明 ─────────────────────────────────────────────────────────
    _section("变更说明（change_description）")
    for line in CHANGE_DESCRIPTION.strip().split("\n"):
        _info(line)

    # ── 构造请求 ─────────────────────────────────────────────────────────────
    _section("启动智能体校验流程")
    _info("节点路由：input_processor → db_context_agent → file_analyzer×N")
    _info("         → dependency_analyzer → db_impact_analyzer")
    _info("         → [change_verifier ∥ syntax_summarizer] → report_generator")
    print()

    try:
        from sql_validator.schemas.inputs import SQLFile, ValidationRequest
        request = ValidationRequest(
            sql_files=[SQLFile(**f) for f in sql_files],
            change_description=CHANGE_DESCRIPTION,
        )
    except Exception as exc:
        _err(f"请求构造失败（Pydantic 校验不通过）: {exc}")
        sys.exit(1)

    # ── 执行图 ───────────────────────────────────────────────────────────────
    t_start = time.time()
    try:
        # 直接调用图以拿到 final_state（entrypoint 返回值有限，这里稍作扩展）
        from sql_validator.graph.builder import build_graph
        from sql_validator.graph.state import make_initial_state
        from sql_validator.tools.db_tools import create_db_tools

        llm      = settings.create_llm()
        db_tools = create_db_tools(dsn=settings.postgres_dsn, llm=llm)
        graph    = build_graph(llm=llm, db_tools=db_tools, output_dir=settings.output_dir)

        initial_state = make_initial_state(
            sql_files=[f.model_dump() for f in request.sql_files],
            change_description=request.change_description,
        )

        print(_c("  图执行中，请稍候……", _Colors.GREY))
        from sql_validator.entrypoint import _get_langfuse_callback
        langfuse_cb = _get_langfuse_callback()
        if langfuse_cb:
            _ok(f"LangFuse 追踪已启用 → {settings.postgres_dsn[:10]}... (见 http://localhost:3000)")
        invoke_config = {"callbacks": [langfuse_cb]} if langfuse_cb else {}
        final_state = graph.invoke(initial_state, config=invoke_config)
        elapsed = time.time() - t_start

    except KeyboardInterrupt:
        _warn("用户中断执行")
        sys.exit(130)
    except Exception as exc:
        elapsed = time.time() - t_start
        _err(f"图执行异常（{elapsed:.1f}s）: {exc}")
        import traceback
        if args.verbose:
            traceback.print_exc()
        sys.exit(1)

    # ── 构造结果对象 ─────────────────────────────────────────────────────────
    try:
        from sql_validator.schemas.inputs import ValidationResult
        change_verif = final_state.get("change_verification") or {}
        result = ValidationResult(
            verdict            = change_verif.get("verdict", "FAIL"),
            risk_level         = change_verif.get("risk_level", "HIGH"),
            summary            = change_verif.get("analysis_notes", ""),
            change_report_path = final_state.get("change_report_md", "（未生成）"),
            syntax_report_path = final_state.get("syntax_report_md", "（未生成）"),
        )
    except Exception:
        # ValidationResult 字段可能与实际不同，回退到简单打印
        result = type("R", (), {
            "verdict":            final_state.get("change_verification", {}).get("verdict", "?"),
            "risk_level":         final_state.get("change_verification", {}).get("risk_level", "?"),
            "summary":            "",
            "change_report_path": final_state.get("change_report_md", ""),
            "syntax_report_path": final_state.get("syntax_report_md", ""),
        })()

    print_result(result, final_state, args.verbose, elapsed)

    _section("完成")
    if result.verdict == "PASS":
        _ok("所有变更校验通过 ✔")
    elif result.verdict == "WARN":
        _warn("变更校验存在警告，请核对报告")
    else:
        _err("变更校验失败，请查看报告排查问题")

    print()


if __name__ == "__main__":
    main()
