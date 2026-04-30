"""
graph/nodes/file_analyzer.py
──────────────────────────────
并行 Worker 节点工厂函数。

每个实例接收 FileAnalyzerInput（通过 Send API 分发），处理单个 SQL 文件：
  1. sqlglot 解析（纯代码）
  2. DB 快照比对（纯代码）
  3. 一次 LLM 调用填充 intent_summary

输出追加到主图的 parsed_scripts 和 raw_syntax_issues（Annotated operator.add）。
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from pydantic import ValidationError

from sql_validator.core.db_comparator import compare_against_snapshot
from sql_validator.core.sql_parser import parse_sql_file
from sql_validator.graph.state import FileAnalyzerInput
from sql_validator.prompts.file_analysis import FILE_INTENT_PROMPT
from sql_validator.schemas.analysis import ParsedScript, SyntaxIssue
from sql_validator.schemas.db_context import DBSnapshot


def make_file_analyzer_node(llm: BaseChatModel):
    """
    工厂函数：返回 file_analyzer Worker 节点函数。

    Args:
        llm: 已配置的 ChatModel 实例（用于生成 intent_summary）
    """

    def file_analyzer(state: FileAnalyzerInput) -> dict:
        """处理单个 SQL 文件，返回解析结果和问题列表（追加到主图状态）。"""
        file_dict: dict = state["file"]
        snapshot_dict: dict | None = state.get("db_snapshot")
        filename: str = file_dict.get("filename", "unknown.sql")

        errors: list[str] = []
        all_issues: list[dict] = []

        # ── Step 1: sqlglot 解析 ──────────────────────────────────────────────
        try:
            script, syntax_issues = parse_sql_file(file_dict)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"[{filename}] sqlglot 解析异常: {exc}")
            return {"parsed_scripts": [], "raw_syntax_issues": [], "errors": errors}

        all_issues.extend(i.model_dump() for i in syntax_issues)

        # ── Step 2: DB 快照比对 ───────────────────────────────────────────────
        if snapshot_dict:
            try:
                snapshot = DBSnapshot.model_validate(snapshot_dict)
                db_issues = compare_against_snapshot(script, snapshot)
                all_issues.extend(i.model_dump() for i in db_issues)
            except (ValidationError, Exception) as exc:  # noqa: BLE001
                errors.append(f"[{filename}] DB 快照比对异常: {exc}")

        # ── Step 3: LLM 填充 intent_summary（整文件一次调用）─────────────────
        statements_preview = "\n".join(
            f"  {i}. [{s.operation}] {s.full_object_name or '(无对象名)'}"
            for i, s in enumerate(script.statements[:10])
        )

        db_context = "（未提供 DB 快照）"
        if snapshot_dict and snapshot_dict.get("tables"):
            table_names = list(snapshot_dict["tables"].keys())[:10]
            db_context = f"数据库中相关表: {', '.join(table_names)}"

        try:
            intent_prompt = FILE_INTENT_PROMPT.format(
                filename=filename,
                objects_created=script.objects_created or "无",
                objects_altered=script.objects_altered or "无",
                objects_dropped=script.objects_dropped or "无",
                objects_written=script.objects_written or "无",
                objects_read=script.objects_read or "无",
                statements_preview=statements_preview or "（无语句）",
                db_context=db_context,
            )
            response = llm.invoke(intent_prompt)
            intent_text = response.content if hasattr(response, "content") else str(response)
            script = script.model_copy(update={"intent_summary": intent_text.strip()[:300]})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"[{filename}] LLM 意图提取失败: {exc}")

        return {
            "parsed_scripts": [script.model_dump()],
            "raw_syntax_issues": all_issues,
            "errors": errors,
        }

    return file_analyzer
