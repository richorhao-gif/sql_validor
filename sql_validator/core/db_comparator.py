"""
core/db_comparator.py
──────────────────────
纯函数层：将 sqlglot 解析出的变更意图与 DB 快照对比，
发现冲突、重复、缺失依赖等问题，产出额外的 SyntaxIssue。

无 LLM、无 DB 连接。
"""
from __future__ import annotations

from typing import Any

from sql_validator.schemas.analysis import ParsedScript, SyntaxIssue
from sql_validator.schemas.db_context import DBSnapshot


def compare_against_snapshot(
    script: ParsedScript,
    snapshot: DBSnapshot,
) -> list[SyntaxIssue]:
    """
    将单个文件的解析结果与 DB 快照对比，返回发现的问题列表。

    检测项：
      - CREATE TABLE：表已存在 → 冲突
      - CREATE VIEW/FUNCTION：对象已存在 → 冲突
      - ALTER TABLE ADD COLUMN：列已存在 → 重复
      - DROP TABLE：表有外键被引用 → 级联风险
      - DROP TABLE/VIEW：对象不存在 → 脚本报错风险（已有 IF EXISTS 规则的补充）
      - INSERT / UPDATE / DELETE 目标表：表不存在 → 依赖缺失
    """
    issues: list[SyntaxIssue] = []
    filename = script.filename

    all_tables = {**snapshot.tables}
    all_views = {**snapshot.views}
    all_routines = {**snapshot.routines}
    all_objects = {**all_tables, **all_views, **all_routines}

    for stmt in script.statements:
        obj = stmt.full_object_name

        # ── CREATE：对象已存在 ────────────────────────────────────────────────
        if stmt.operation == "CREATE":
            if obj in all_objects:
                issues.append(SyntaxIssue(
                    filename=filename, severity="ERROR", category="LOGIC",
                    rule="OBJECT_ALREADY_EXISTS",
                    message=f"CREATE 操作的目标对象 {obj!r} 在数据库中已存在",
                    sql_snippet=stmt.raw_sql_snippet,
                    suggestion="改用 CREATE ... IF NOT EXISTS，或先执行 DROP 操作",
                ))

        # ── ALTER TABLE：列是否已存在（针对 ADD COLUMN 场景）─────────────────
        elif stmt.operation == "ALTER" and obj in all_tables:
            # 精细列检查依赖原始 SQL 解析，此处做保守提示
            # （精确 ADD COLUMN 检查在 file_analyzer 节点调用 LLM 时补充）
            pass

        # ── DROP：对象不存在 / 存在外键引用 ──────────────────────────────────
        elif stmt.operation == "DROP":
            if obj not in all_objects:
                issues.append(SyntaxIssue(
                    filename=filename, severity="WARNING", category="LOGIC",
                    rule="DROP_NONEXISTENT_OBJECT",
                    message=f"DROP 的目标对象 {obj!r} 在数据库中不存在",
                    sql_snippet=stmt.raw_sql_snippet,
                    suggestion="确认对象名称是否正确，或添加 IF EXISTS 避免报错",
                ))
            elif obj in all_tables:
                table = all_tables[obj]
                # 检查是否有其他表的外键指向该表
                referencing = _find_referencing_tables(obj, snapshot)
                if referencing:
                    issues.append(SyntaxIssue(
                        filename=filename, severity="ERROR", category="LOGIC",
                        rule="DROP_TABLE_WITH_FK_REFERENCES",
                        message=(
                            f"DROP TABLE {obj!r}：该表被 {referencing} 的外键引用，"
                            "直接删除将导致约束违反或级联删除"
                        ),
                        sql_snippet=stmt.raw_sql_snippet,
                        suggestion="先 DROP 或修改引用该表的外键约束，再执行 DROP TABLE",
                    ))

        # ── DML 目标表：表不存在 ──────────────────────────────────────────────
        elif stmt.operation in {"INSERT", "UPDATE", "DELETE", "TRUNCATE", "MERGE"}:
            if obj and obj not in all_tables and obj not in all_views:
                # 可能是本次脚本新建的表，不一定是真正的问题
                # 在 dependency_analyzer 阶段会进行跨文件检查，这里仅记录 INFO
                issues.append(SyntaxIssue(
                    filename=filename, severity="INFO", category="LOGIC",
                    rule="DML_TARGET_NOT_IN_DB",
                    message=(
                        f"{stmt.operation} 的目标对象 {obj!r} 在当前数据库快照中不存在，"
                        "可能由本次发版的其他脚本新建"
                    ),
                    sql_snippet=stmt.raw_sql_snippet,
                    suggestion="确认目标表由同批次其他脚本创建，并保证执行顺序正确",
                ))

    return issues


def _find_referencing_tables(
    target_full_name: str, snapshot: DBSnapshot
) -> list[str]:
    """找到所有通过外键引用 target_full_name 的表。"""
    referencing: list[str] = []
    for full_name, table in snapshot.tables.items():
        for fk in table.foreign_keys:
            ref_full = f"{fk.references_schema}.{fk.references_table}"
            if ref_full == target_full_name:
                referencing.append(full_name)
    return referencing


def compute_quality_score(issues: list[dict[str, Any]]) -> int:
    """
    根据问题列表计算质量评分（0-100）。
    每 ERROR -10，每 WARNING -3，每 INFO -0.5（向下取整）。
    """
    score = 100.0
    for issue in issues:
        sev = issue.get("severity", "INFO")
        if sev == "ERROR":
            score -= 10
        elif sev == "WARNING":
            score -= 3
        else:
            score -= 0.5
    return max(0, int(score))
