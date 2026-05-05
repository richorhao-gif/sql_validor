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
    "01_sauce_mat_brd_prdct_atribt_redeploy.sql",
    "02_sauce_mat_abbr_add_column.sql",
    "03_sauce_mat_variety_new_asset.sql",
]

CHANGE_DESCRIPTION = (
    "本次发版共 3 个 SQL 脚本，涉及供应链域调味品板块 3 个数据资产：\n"
    "① 调味物料品种与产品属性（sauce_mat_brd_prdct_atribt）全链路重建：\n"
    "   新增 is_rawmat（是否原料）和 prdct_atribt（产品属性）两列，\n"
    "   DS→ODS→DWD→DA→BI 所有层全部 DROP+CREATE 重建；\n"
    "   影响下游：da.v_da_sauce_material_full 和 da_selfhp 两个视图需随之重建。\n"
    "② 调味物料简称（sauce_mat_abbr）全链路新增 mat_abbr_short（物料短简称）列：\n"
    "   DS 层重建 FOREIGN TABLE，ODS/DWD/DA 层 ALTER 追加列，BI 视图同步重建；\n"
    "   与脚本①无执行顺序依赖，但共用同一 oss_serv。\n"
    "③ 调味品品种（sauce_mat_variety）全新资产创建：\n"
    "   从零建立 DS→ODS→DWD→DA→BI 完整链路，库中当前不存在同名对象；\n"
    "   共用 oss_serv OSS Server（该 Server 已被①②使用，需确认 Server 状态）。\n"
    "执行顺序：脚本①②③均可独立执行，无跨脚本字段依赖。"
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
    _info("节点路由：input_processor ─┬─ db_context_agent → file_analyzer×N")
    _info("         syntax_chain    ├─ syntax_file_worker×N → syntax_summarizer → END")
    _info("         main chain      └─ dependency_analyzer → db_impact_analyzer → change_verifier → END")
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
        db_tools = create_db_tools(dsn=settings.postgres_dsn)
        graph    = build_graph(llm=llm, db_tools=db_tools, output_dir=settings.output_dir)

        initial_state = make_initial_state(
            sql_files=[f.model_dump() for f in request.sql_files],
            change_description=request.change_description,
        )

        print(_c("  图执行中，逐节点输出进度……", _Colors.GREY))
        from sql_validator.entrypoint import _get_langfuse_callback
        langfuse_cb = _get_langfuse_callback()
        if langfuse_cb:
            _ok(f"LangFuse 追踪已启用 → {settings.postgres_dsn[:10]}... (见 http://localhost:3000)")
        invoke_config = {"callbacks": [langfuse_cb]} if langfuse_cb else {}

        final_state: dict = {}
        for chunk in graph.stream(initial_state, config=invoke_config, stream_mode="updates"):
            for node_name, node_output in chunk.items():
                node_errors = node_output.get("errors") if isinstance(node_output, dict) else []
                status = _c("✘", _Colors.RED) if node_errors else _c("✔", _Colors.GREEN)
                _info(f"  {status} {node_name}（{time.time()-t_start:.1f}s）")
                if node_errors:
                    for e in node_errors:
                        _warn(f"    └ {e}")
            if isinstance(chunk, dict):
                for v in chunk.values():
                    if isinstance(v, dict):
                        final_state.update(v)
        elapsed = time.time() - t_start

        # Langfuse v3 异步批量上报，进程退出前必须显式 flush，否则队列丢失
        # v3 的 flush/shutdown 在客户端单例上，不在 handler 上
        if langfuse_cb:
            try:
                from langfuse import get_client
                get_client().flush()
                _ok("Langfuse 追踪数据已上报完毕")
            except Exception as _lf_exc:
                _warn(f"Langfuse flush 失败（不影响主流程）: {_lf_exc}")

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
            change_report_path = final_state.get("change_report_path", "（未生成）"),
            syntax_report_path = final_state.get("syntax_report_path", "（未生成）"),
        )
    except Exception:
        # ValidationResult 字段可能与实际不同，回退到简单打印
        result = type("R", (), {
            "verdict":            final_state.get("change_verification", {}).get("verdict", "?"),
            "risk_level":         final_state.get("change_verification", {}).get("risk_level", "?"),
            "summary":            "",
            "change_report_path": final_state.get("change_report_path", "（未生成）"),
            "syntax_report_path": final_state.get("syntax_report_path", "（未生成）"),
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
