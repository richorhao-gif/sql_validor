"""
graph/nodes/syntax_summarizer.py
──────────────────────────────────
语法报告聚合节点：汇总所有 syntax_file_worker 的结果，纯代码生成 MD 报告写入磁盘。
无 LLM 调用。在 input_processor 之后与主链路并行，最早完成。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sql_validator.core.db_comparator import compute_quality_score
from sql_validator.graph.state import SQLValidationState


def make_syntax_summarizer_node(output_dir: str = "./reports"):
    """工厂函数：返回 syntax_summarizer 节点函数（无 llm 参数）。"""

    def syntax_summarizer(state: SQLValidationState) -> dict:
        file_results: list[dict] = state.get("syntax_file_results", [])

        # ── 聚合统计 ───────────────────────────────────────────────────────────
        total_errors   = sum(r.get("error_count",   0) for r in file_results)
        total_warnings = sum(r.get("warning_count", 0) for r in file_results)
        total_info     = sum(r.get("info_count",    0) for r in file_results)
        all_issues     = [i for r in file_results for i in r.get("issues", [])]
        quality_score  = compute_quality_score(all_issues)

        # ── 纯代码生成 MD 报告 ────────────────────────────────────────────────
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines: list[str] = [
            "# SQL 脚本语法与质量分析报告",
            "",
            f"**生成时间**：{now}  ",
            f"**文件数**：{len(file_results)}  ",
            f"**综合质量评分**：{quality_score}/100  ",
            f"**ERROR**：{total_errors} | **WARNING**：{total_warnings} | **INFO**：{total_info}",
            "",
            "---",
            "",
            "## 各文件概览",
            "",
            "| 文件 | ERROR | WARNING | INFO | 主要问题 |",
            "| --- | :---: | :---: | :---: | --- |",
        ]
        for r in file_results:
            top = r.get("top_issues", [])
            main_issue = top[0] if top else "—"
            lines.append(
                f"| `{r['filename']}` "
                f"| {r.get('error_count', 0)} "
                f"| {r.get('warning_count', 0)} "
                f"| {r.get('info_count', 0)} "
                f"| {main_issue} |"
            )

        lines += ["", "---", ""]

        for r in file_results:
            lines.append(f"## {r['filename']}")
            lines.append("")
            issues = r.get("issues", [])
            errors   = [i for i in issues if i.get("severity") == "ERROR"]
            warnings = [i for i in issues if i.get("severity") == "WARNING"]
            infos    = [i for i in issues if i.get("severity") == "INFO"]

            if errors:
                lines.append("### 🔴 ERROR")
                for i in errors:
                    lines.append(f"- **[{i.get('rule', '?')}]** {i.get('message', '')}")
                    if i.get("suggestion"):
                        lines.append(f"  - 建议：{i['suggestion']}")
                lines.append("")

            if warnings:
                lines.append("### 🟡 WARNING")
                for i in warnings:
                    lines.append(f"- **[{i.get('rule', '?')}]** {i.get('message', '')}")
                    if i.get("suggestion"):
                        lines.append(f"  - 建议：{i['suggestion']}")
                lines.append("")

            if infos:
                lines.append("### 🔵 INFO")
                for i in infos:
                    lines.append(f"- **[{i.get('rule', '?')}]** {i.get('message', '')}")
                lines.append("")

            if not errors and not warnings and not infos:
                lines.append("*无语法问题*")
                lines.append("")

            if r.get("top_issues"):
                lines.append("### 关键问题摘要")
                for item in r["top_issues"]:
                    lines.append(f"- {item}")
                lines.append("")

            if r.get("recommendations"):
                lines.append("### 改进建议")
                for rec in r["recommendations"]:
                    lines.append(f"- {rec}")
                lines.append("")

        report_md = "\n".join(lines)

        # ── 写入磁盘 ──────────────────────────────────────────────────────────
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = out_path / f"syntax_report_{timestamp}.md"
        report_path.write_text(report_md, encoding="utf-8")
        print(f"    [syntax_summarizer] 语法报告已写入: {report_path}", flush=True)

        return {
            "syntax_report_path": str(report_path),
            "errors": [],
        }

    return syntax_summarizer

