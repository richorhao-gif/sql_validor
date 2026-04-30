"""
core/report_builder.py
───────────────────────
纯函数层：将各分析阶段的结构化数据组装为 Prompt 上下文字符串，
供 LLM 调用节点使用。不包含任何 LLM 调用。
"""
from __future__ import annotations

import json
from typing import Any


def format_scripts_summary(parsed_scripts: list[dict[str, Any]]) -> str:
    """将多个 ParsedScript 格式化为易于 LLM 阅读的摘要文本。"""
    lines: list[str] = []
    for script in parsed_scripts:
        fn = script["filename"]
        lines.append(f"### {fn}")
        lines.append(f"- 语句总数: {len(script.get('statements', []))}")
        lines.append(f"- 语法错误数: {script.get('syntax_error_count', 0)}")
        if script.get("objects_created"):
            lines.append(f"- 新建对象: {', '.join(script['objects_created'])}")
        if script.get("objects_altered"):
            lines.append(f"- 修改对象: {', '.join(script['objects_altered'])}")
        if script.get("objects_dropped"):
            lines.append(f"- 删除对象: {', '.join(script['objects_dropped'])}")
        if script.get("objects_written"):
            lines.append(f"- DML写入: {', '.join(script['objects_written'])}")
        if script.get("objects_read"):
            lines.append(f"- SELECT读取: {', '.join(script['objects_read'])}")
        if script.get("intent_summary"):
            lines.append(f"- 业务意图: {script['intent_summary']}")
        lines.append("")
    return "\n".join(lines)


def format_db_impact_for_verification(db_impact: dict[str, Any]) -> str:
    """将 DBImpactAnalysis 格式化为变更说明对比使用的上下文字符串。"""
    lines: list[str] = []
    lines.append(f"**执行顺序**: {' → '.join(db_impact.get('execution_sequence', []))}")
    lines.append("")

    if db_impact.get("new_objects"):
        lines.append(f"**新增对象**: {', '.join(db_impact['new_objects'])}")
    if db_impact.get("modified_objects"):
        lines.append("**修改对象**:")
        for obj in db_impact["modified_objects"]:
            lines.append(f"  - {obj}")
    if db_impact.get("removed_objects"):
        lines.append(f"**删除对象**: {', '.join(db_impact['removed_objects'])}")
    if db_impact.get("data_affected_tables"):
        lines.append(f"**数据变更表**: {', '.join(db_impact['data_affected_tables'])}")
    if db_impact.get("cross_file_dependencies"):
        lines.append("**跨文件依赖**:")
        for dep in db_impact["cross_file_dependencies"]:
            lines.append(f"  - {dep}")

    lines.append("")
    lines.append(f"**Schema变更摘要**: {db_impact.get('schema_changes_summary', '无')}")
    lines.append(f"**数据变更摘要**: {db_impact.get('data_changes_summary', '无')}")
    lines.append(f"**整体摘要**: {db_impact.get('overall_summary', '')}")
    return "\n".join(lines)


def format_changes_detail(db_impact: dict[str, Any]) -> str:
    """将 DBChange 列表格式化为详细变更清单。"""
    changes = db_impact.get("changes", [])
    if not changes:
        return "（无变更记录）"
    lines: list[str] = []
    for c in changes:
        flag = "🔴 " if c.get("is_destructive") else ""
        lines.append(
            f"{flag}[{c.get('source_file')}] "
            f"{c.get('operation')} {c.get('object_type')} "
            f"`{c.get('object_full_name')}`"
        )
        if c.get("before_state"):
            lines.append(f"   变更前: {c['before_state']}")
        lines.append(f"   变更后: {c.get('after_state', '')}")
    return "\n".join(lines)


def format_issues_for_summary(issues: list[dict[str, Any]]) -> str:
    """将 SyntaxIssue 列表格式化为 JSON，供 LLM 生成汇总评估。"""
    # 保留结构但截断 sql_snippet 避免 Token 过多
    compact = []
    for issue in issues:
        compact.append({
            "filename": issue.get("filename"),
            "severity": issue.get("severity"),
            "category": issue.get("category"),
            "rule": issue.get("rule"),
            "message": issue.get("message"),
            "suggestion": issue.get("suggestion"),
        })
    return json.dumps(compact, ensure_ascii=False, indent=2)


def format_file_stats(issues: list[dict[str, Any]], file_list: list[str]) -> str:
    """按文件聚合问题统计。"""
    from collections import Counter
    stats: dict[str, Counter[str]] = {fn: Counter() for fn in file_list}
    for issue in issues:
        fn = issue.get("filename", "")
        sev = issue.get("severity", "INFO")
        if fn in stats:
            stats[fn][sev] += 1

    lines = ["| 文件名 | ERROR | WARNING | INFO |", "|---|---|---|---|"]
    for fn in file_list:
        c = stats.get(fn, Counter())
        lines.append(f"| {fn} | {c['ERROR']} | {c['WARNING']} | {c['INFO']} |")
    return "\n".join(lines)
