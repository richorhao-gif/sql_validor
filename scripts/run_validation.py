"""
scripts/run_validation.py
──────────────────────────
SQL 发版审查工具 —— 交互式命令行入口。

功能：
  1. 从 CODING Git 仓库按 Coding 编号拉取发版脚本
  2. 若多个日期文件夹匹配，提示用户选择
  3. 接受手动输入的变更说明
  4. 调用 run_validation 并行启动变更校验 + 语法审查
  5. 打印摘要和报告路径

运行方式：
  uv run python scripts/run_validation.py
  uv run python scripts/run_validation.py --verbose
  uv run python scripts/run_validation.py --skip-preflight
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
    BLUE   = "\033[94m"


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
# 数据库预检
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
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 交互：Coding 编号
# ─────────────────────────────────────────────────────────────────────────────

def prompt_coding_numbers() -> list[str]:
    """
    提示用户输入一个或多个 Coding 编号。

    Returns:
        编号列表，均已规范化为 "#XXXX" 格式。
    """
    print()
    print(_c("  输入 Coding 编号", _C.BOLD))
    print(_c("  格式：#2590 或 2590，多个编号用英文逗号分隔", _C.GREY))
    raw = input(_c("  > ", _C.BLUE)).strip()
    if not raw:
        _err("编号不能为空")
        sys.exit(1)

    numbers = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        # 统一加 # 前缀
        numbers.append(part if part.startswith("#") else f"#{part}")

    if not numbers:
        _err("未识别到有效编号")
        sys.exit(1)

    _ok(f"已记录编号：{', '.join(numbers)}")
    return numbers


# ─────────────────────────────────────────────────────────────────────────────
# 交互：从仓库获取脚本
# ─────────────────────────────────────────────────────────────────────────────

def fetch_from_repo(
    repo_url: str,
    branch: str,
    token: str,
    coding_numbers: list[str],
) -> list[dict]:
    """
    通过 CODING OpenAPI 拉取匹配的脚本文件，若有多个日期版本则提示用户选择。

    Returns:
        SQLFile.model_dump() 格式的 dict 列表（含 filename / content / developer）。
    """
    from sql_validator.fetcher import fetch_scripts_by_coding, FetchedFile

    _info(f"正在通过 CODING OpenAPI 获取脚本（分支：{branch}）…")

    try:
        results = fetch_scripts_by_coding(repo_url, branch, token, coding_numbers)
    except FileNotFoundError as exc:
        _err(str(exc))
        sys.exit(1)
    except ValueError as exc:
        _err(str(exc))
        sys.exit(1)
    except Exception as exc:
        _err(f"获取脚本失败: {exc}")
        _warn("请检查：① CODING Token 是否有效；② 仓库 URL 是否正确；"
              "③ 网络连通性是否正常")
        sys.exit(1)

    date_folders = list(results.keys())
    _ok(f"找到 {len(date_folders)} 个日期文件夹的匹配脚本")

    if len(date_folders) == 1:
        chosen = date_folders[0]
    else:
        # 多个日期版本，让用户选择
        print()
        print(_c("  发现多个日期的发版记录，请选择：", _C.BOLD))
        for i, date in enumerate(date_folders, 1):
            files = results[date]
            print(_c(f"  [{i}] {date}（{len(files)} 个文件）", _C.CYAN))
            for f in files:
                dev_str = f" [{f.developer}]" if f.developer else ""
                print(_c(f"       • {f.filename}{dev_str}", _C.GREY))

        while True:
            chosen_input = input(
                _c(f"  请输入序号 [1-{len(date_folders)}]: ", _C.BLUE)
            ).strip()
            try:
                idx = int(chosen_input) - 1
                if 0 <= idx < len(date_folders):
                    chosen = date_folders[idx]
                    break
                _warn(f"序号超出范围，请输入 1 到 {len(date_folders)}")
            except ValueError:
                _warn("请输入有效数字")

    chosen_files: list[FetchedFile] = results[chosen]
    _ok(f"已选择日期：{chosen}（{len(chosen_files)} 个文件）")
    for f in chosen_files:
        dev_str = f" (开发者：{f.developer})" if f.developer else ""
        _info(f"{f.filename}{dev_str}")

    return [
        {"filename": f.filename, "content": f.content, "developer": f.developer}
        for f in chosen_files
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 交互：变更说明
# ─────────────────────────────────────────────────────────────────────────────

def prompt_change_description() -> str:
    """
    多行输入变更说明，空行结束。

    Returns:
        变更说明字符串（至少 10 个字符）。
    """
    print()
    print(_c("  请输入本次发版变更说明", _C.BOLD))
    print(_c("  （多行输入，输入空行结束）", _C.GREY))
    lines = []
    while True:
        line = input(_c("  > ", _C.BLUE))
        if line.strip() == "":
            if lines:
                break
            # 第一行不允许为空
            _warn("变更说明不能为空，请至少输入一行内容")
            continue
        lines.append(line)

    description = "\n".join(lines)
    if len(description.strip()) < 10:
        _err("变更说明太短（至少 10 个字符），请重新输入")
        return prompt_change_description()

    _ok(f"变更说明已记录（{len(description)} 字符）")
    return description


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
    _ok(f"变更校验报告 : {result.report_path}")
    if getattr(result, "syntax_report_path", None):
        _ok(f"语法质量报告 : {result.syntax_report_path}")
    else:
        _warn("语法质量报告未生成（分析失败或未启用）")

    if verbose:
        _section("详细报告（--verbose，前 60 行）")
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
    parser = argparse.ArgumentParser(description="SQL 发版脚本审查工具")
    parser.add_argument("--verbose", "-v", action="store_true", help="打印报告前 60 行")
    parser.add_argument(
        "--skip-preflight", action="store_true", help="跳过数据库连通性预检"
    )
    args = parser.parse_args()

    print(_c("\n  SQL 发版脚本审查工具", _C.BOLD + _C.CYAN))
    print(_c("  ─────────────────────────────────────", _C.CYAN))

    # ── 加载配置 ─────────────────────────────────────────────────────────────
    _section("加载配置")
    try:
        from sql_validator.config.settings import get_settings
        settings = get_settings()
        _ok(f"LLM 提供商 : {settings.llm_provider}")
        _ok(f"模型       : {settings.llm_model}")
        _ok(f"DB DSN     : {settings.postgres_dsn[:45]}…")
        _ok(f"CODING 仓库: {settings.coding_repo_url[:60]}…")
        _ok(f"CODING Token: {'已配置' if settings.coding_token else '未配置（将使用匿名访问）'}")
    except Exception as exc:
        _err(f"配置加载失败: {exc}")
        _warn("请检查 .env 文件中 LLM_API_KEY、POSTGRES_DSN、CODING_REPO_URL、CODING_TOKEN 是否已填写")
        sys.exit(1)

    # ── 数据库预检 ────────────────────────────────────────────────────────────
    if not args.skip_preflight:
        _section("数据库连通性预检")
        if not preflight_check(settings.postgres_dsn):
            _warn("若确认数据库暂不可用，可使用 --skip-preflight 跳过此步骤")
            sys.exit(1)

    # ── 输入 Coding 编号 ──────────────────────────────────────────────────────
    _section("Coding 编号")
    coding_numbers = prompt_coding_numbers()

    # ── 从仓库获取脚本 ────────────────────────────────────────────────────────
    _section("从 CODING 仓库拉取脚本")
    sql_file_dicts = fetch_from_repo(
        settings.coding_repo_url,
        settings.coding_branch,
        settings.coding_token,
        coding_numbers,
    )

    # ── 输入变更说明 ──────────────────────────────────────────────────────────
    _section("变更说明")
    change_description = prompt_change_description()

    # ── 构建请求 ──────────────────────────────────────────────────────────────
    _section("启动智能体审查")
    _info("变更校验 Agent 与语法审查 Agent 并行运行中，请稍候…")
    print()

    try:
        from sql_validator.schemas.inputs import SQLFile, ValidationRequest
        request = ValidationRequest(
            sql_files=[SQLFile(**f) for f in sql_file_dicts],
            change_description=change_description,
        )
    except Exception as exc:
        _err(f"请求构造失败（Pydantic 校验不通过）: {exc}")
        sys.exit(1)

    # ── 执行校验 ──────────────────────────────────────────────────────────────
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
        _warn("变更校验存在警告，请核对报告后决定是否发版")
    else:
        _err("变更校验失败，存在阻断性风险，请查看报告排查问题")
    print()


if __name__ == "__main__":
    main()
