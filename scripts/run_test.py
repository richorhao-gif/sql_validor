"""
scripts/run_test.py
────────────────────
本地集成测试快捷运行脚本。

功能：
  1. 从 tests/fixtures/ 加载 3 个模拟变更 SQL 文件
  2. 调用 sql_validator.entrypoint.run_validation 执行校验
  3. 打印执行摘要和报告路径

前提条件：
  - Docker 服务已启动（docker compose up -d）
  - .env 中 POSTGRES_DSN / LLM_API_KEY 已正确配置
  - 已安装依赖（uv sync）

运行方式：
  uv run python scripts/run_test.py
  uv run python scripts/run_test.py --verbose
"""
from __future__ import annotations

import argparse
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# 终端输出工具
# ─────────────────────────────────────────────────────────────────────────────

class _C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    GREY   = "\033[90m"


def _c(text: str, color: str) -> str:
    return f"{color}{text}{_C.RESET}"


def _section(title: str) -> None:
    print(f"\n{_c('━' * 60, _C.CYAN)}")
    print(_c(f"  {title}", _C.BOLD + _C.CYAN))
    print(_c('━' * 60, _C.CYAN))


def _ok(msg: str)   -> None: print(_c(f"  ✔  {msg}", _C.GREEN))
def _warn(msg: str) -> None: print(_c(f"  ⚠  {msg}", _C.YELLOW))
def _err(msg: str)  -> None: print(_c(f"  ✘  {msg}", _C.RED))
def _info(msg: str) -> None: print(_c(f"     {msg}", _C.GREY))


# ─────────────────────────────────────────────────────────────────────────────
# 测试数据
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
# 数据库连通性预检
# ─────────────────────────────────────────────────────────────────────────────

def preflight_check(dsn: str) -> bool:
    try:
        import psycopg  # type: ignore[import-untyped]

        with psycopg.connect(dsn) as conn:
            row = conn.execute(
                "SELECT current_database(), current_user, version()"
            ).fetchone()
            if row:
                _ok(f"DB 连通成功 | 库: {row[0]} | 用户: {row[1]}")
                _info(f"PostgreSQL 版本: {str(row[2])[:60]}")
        return True
    except Exception as exc:
        _err(f"数据库连通性检查失败: {exc}")
        _warn("请确认 Docker 服务已启动：docker compose up -d")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 结果打印
# ─────────────────────────────────────────────────────────────────────────────

_VERDICT_COLOR = {"PASS": _C.GREEN, "WARN": _C.YELLOW, "FAIL": _C.RED}
_RISK_COLOR    = {
    "LOW": _C.GREEN, "MEDIUM": _C.YELLOW,
    "HIGH": _C.RED, "CRITICAL": _C.RED + _C.BOLD,
}


def print_result(result, elapsed: float, verbose: bool) -> None:
    vc = _VERDICT_COLOR.get(result.verdict, _C.GREY)
    rc = _RISK_COLOR.get(result.risk_level, _C.GREY)

    _section("校验结果摘要")
    print(f"  总体判定 : {_c(result.verdict,    vc + _C.BOLD)}")
    print(f"  风险等级 : {_c(result.risk_level, rc + _C.BOLD)}")
    print(f"  耗时     : {elapsed:.1f} 秒")

    if result.summary:
        _section("分析摘要")
        for line in textwrap.wrap(result.summary, width=70):
            _info(line)

    _section("输出报告路径")
    _ok(f"报告文件 : {result.report_path}")

    if verbose:
        _section("详细报告内容（--verbose，前 60 行）")
        try:
            md = Path(result.report_path).read_text(encoding="utf-8")
            for line in md.splitlines()[:60]:
                _info(line)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="SQL 变更校验智能体 — 本地集成测试")
    parser.add_argument("--verbose", "-v", action="store_true", help="打印报告前 60 行")
    parser.add_argument("--skip-preflight", action="store_true", help="跳过数据库连通性预检")
    args = parser.parse_args()

    print(_c("\n  SQL 变更校验智能体 — 本地集成测试", _C.BOLD))
    print(_c("  ─────────────────────────────────────", _C.CYAN))

    # ── 加载配置 ─────────────────────────────────────────────────────────────
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

    # ── 数据库预检 ────────────────────────────────────────────────────────────
    if not args.skip_preflight:
        _section("数据库连通性预检")
        if not preflight_check(settings.postgres_dsn):
            sys.exit(1)

    # ── 加载 SQL fixture 文件 ─────────────────────────────────────────────────
    _section("加载测试 SQL 变更文件")
    sql_files = load_sql_files()

    # ── 显示变更说明 ──────────────────────────────────────────────────────────
    _section("变更说明（change_description）")
    for line in CHANGE_DESCRIPTION.strip().split("\n"):
        _info(line)

    # ── 执行校验 ──────────────────────────────────────────────────────────────
    _section("启动智能体校验流程")
    _info("ReAct Agent 自主调用工具完成分析……")
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

    t_start = time.time()
    try:
        from sql_validator.entrypoint import run_validation
        result = run_validation(request)
        elapsed = time.time() - t_start
    except KeyboardInterrupt:
        _warn("用户中断执行")
        sys.exit(130)
    except Exception as exc:
        elapsed = time.time() - t_start
        _err(f"执行异常（{elapsed:.1f}s）: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print_result(result, elapsed, args.verbose)

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
