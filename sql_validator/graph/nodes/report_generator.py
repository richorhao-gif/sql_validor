"""
graph/nodes/report_generator.py
─────────────────────────────────
等两条并行分支（change_verifier + syntax_summarizer）都完成后，
用 LLM 生成两份 MD 报告并写入磁盘。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from sql_validator.graph.state import SQLValidationState
from sql_validator.prompts.report_gen import CHANGE_REPORT_PROMPT, SYNTAX_REPORT_PROMPT


def make_report_generator_node(llm: BaseChatModel, output_dir: str = "./reports"):
    """工厂函数：返回 report_generator 节点函数。"""

    def report_generator(state: SQLValidationState) -> dict:
        change_verification: dict | None = state.get("change_verification")
        syntax_summary: dict | None = state.get("syntax_summary")
        db_impact: dict | None = state.get("db_impact")
        dep_graph: dict | None = state.get("dependency_graph")
        parsed_scripts: list[dict] = state.get("parsed_scripts", [])
        raw_issues: list[dict] = state.get("raw_syntax_issues", [])

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        errors: list[str] = []

        # ── 生成变更对比报告 ──────────────────────────────────────────────────
        change_report_md = ""
        try:
            change_data = {
                "generated_at": datetime.now().isoformat(),
                "file_count": len(parsed_scripts),
                "change_verification": change_verification,
                "db_impact": db_impact,
                "dependency_graph": dep_graph,
            }
            change_prompt = CHANGE_REPORT_PROMPT.format(
                report_data=json.dumps(change_data, ensure_ascii=False, indent=2)[:12000]
            )
            response = llm.invoke(change_prompt)
            change_report_md = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"变更对比报告生成失败: {exc}")
            change_report_md = f"# 变更对比报告生成失败\n\n错误: {exc}"

        # ── 生成语法质量报告 ──────────────────────────────────────────────────
        syntax_report_md = ""
        try:
            syntax_data = {
                "generated_at": datetime.now().isoformat(),
                "syntax_summary": syntax_summary,
                "issues": raw_issues[:200],  # 最多传 200 条问题避免超 Token
                "files": [
                    {"filename": s["filename"], "intent": s.get("intent_summary", "")}
                    for s in parsed_scripts
                ],
            }
            syntax_prompt = SYNTAX_REPORT_PROMPT.format(
                report_data=json.dumps(syntax_data, ensure_ascii=False, indent=2)[:12000]
            )
            response = llm.invoke(syntax_prompt)
            syntax_report_md = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"语法质量报告生成失败: {exc}")
            syntax_report_md = f"# 语法质量报告生成失败\n\n错误: {exc}"

        # ── 写入磁盘 ──────────────────────────────────────────────────────────
        change_report_path = out_path / f"change_report_{timestamp}.md"
        syntax_report_path = out_path / f"syntax_report_{timestamp}.md"

        change_report_path.write_text(change_report_md, encoding="utf-8")
        syntax_report_path.write_text(syntax_report_md, encoding="utf-8")

        return {
            "change_report_md": change_report_md,
            "syntax_report_md": syntax_report_md,
            "errors": errors,
        }

    return report_generator
