"""
graph/nodes/input_processor.py
────────────────────────────────
第一个节点：验证输入，用 sqlglot 轻量预扫描提取涉及的对象名清单。
无 LLM、无 DB 连接。
"""
from __future__ import annotations

from sql_validator.core.sql_parser import extract_all_object_names
from sql_validator.graph.state import SQLValidationState
from sql_validator.schemas.inputs import SQLFile, ValidationRequest


def input_processor(state: SQLValidationState) -> dict:
    """
    验证输入文件，并将对象名清单注入 messages（供 db_context_agent 使用）。
    """
    from langchain_core.messages import HumanMessage

    errors: list[str] = []

    # ── Pydantic 校验 ────────────────────────────────────────────────────────
    try:
        request = ValidationRequest(
            sql_files=[SQLFile.model_validate(f) for f in state["sql_files"]],
            change_description=state["change_description"],
        )
    except Exception as exc:  # noqa: BLE001
        return {"errors": [f"输入校验失败: {exc}"]}

    # ── 轻量预扫描：提取所有对象名 ────────────────────────────────────────────
    object_names = extract_all_object_names(
        [f.model_dump() for f in request.sql_files]
    )

    file_list = "\n".join(f"  - {f.filename}" for f in request.sql_files)
    objects_list = "\n".join(f"  - {o}" for o in object_names) or "  （未识别到具体对象名）"

    init_message = HumanMessage(
        content=(
            f"本次发版共 {len(request.sql_files)} 个 SQL 文件：\n{file_list}\n\n"
            f"脚本中涉及的数据库对象（供你参考）：\n{objects_list}\n\n"
            "请查询数据库，获取这些对象的当前结构，并主动追查外键依赖关系。"
        )
    )

    return {
        "messages": [init_message],
        "errors": errors,
    }
