"""
core/sql_parser.py
──────────────────
纯函数层：用 sqlglot 解析单个 SQL 文件，无 LLM、无 DB 连接。

输入 : SQLFile.model_dump() 格式的 dict
输出 : (ParsedScript, list[SyntaxIssue])
      ParsedScript.intent_summary 留空，由 file_analyzer 节点用 LLM 填充
"""
from __future__ import annotations

import logging
from typing import Any

import sqlglot
import sqlglot.expressions as exp

_sqlglot_logger = logging.getLogger("sqlglot")

from sql_validator.schemas.analysis import (
    ParsedScript,
    StatementInfo,
    SyntaxIssue,
)

# ─────────────────────────────────────────────────────────────────────────────
# 公共入口
# ─────────────────────────────────────────────────────────────────────────────

def parse_sql_file(file: dict[str, Any]) -> tuple[ParsedScript, list[SyntaxIssue]]:
    """
    解析单个 SQL 文件。

    Args:
        file: SQLFile.model_dump() 结果，包含 filename 和 content 字段。

    Returns:
        (ParsedScript, list[SyntaxIssue])
    """
    filename: str = file["filename"]
    content: str = file["content"]

    issues: list[SyntaxIssue] = []
    syntax_error_count = 0

    # ── 解析 ──────────────────────────────────────────────────────────────────
    try:
        _sqlglot_logger.setLevel(logging.ERROR)
        parsed_stmts = sqlglot.parse(
            content,
            dialect="postgres",
            error_level=sqlglot.ErrorLevel.IGNORE,
        )
    except Exception as exc:  # noqa: BLE001
        issues.append(
            SyntaxIssue(
                filename=filename,
                severity="ERROR",
                category="SYNTAX",
                rule="PARSE_FAILED",
                message=f"文件整体解析失败: {exc}",
                sql_snippet=content[:300],
                suggestion="检查 SQL 语法，确认是否为合法的 PostgreSQL 语句",
            )
        )
        return (
            ParsedScript(filename=filename, syntax_error_count=1),
            issues,
        )

    # ── 逐语句处理 ────────────────────────────────────────────────────────────
    statements: list[StatementInfo] = []

    for i, stmt in enumerate(parsed_stmts):
        if stmt is None:
            continue

        # sqlglot 解析告警（软错误）— 使用 error_messages() 方法而非不存在的 .errors 属性
        try:
            stmt_errors = list(stmt.error_messages())
        except Exception:  # noqa: BLE001
            stmt_errors = []

        for err in stmt_errors:
            syntax_error_count += 1
            try:
                snippet = stmt.sql(dialect="postgres")[:300]
            except Exception:  # noqa: BLE001
                snippet = ""
            issues.append(
                SyntaxIssue(
                    filename=filename,
                    severity="ERROR",
                    category="SYNTAX",
                    rule="SYNTAX_ERROR",
                    message=str(err),
                    sql_snippet=snippet,
                    suggestion="修复语法错误后重新提交",
                )
            )

        # 提取结构化信息
        info = _extract_statement_info(stmt, i, filename)
        if info:
            statements.append(info)

        # 质量规则检查
        issues.extend(_check_quality_rules(stmt, filename))

    # ── 聚合对象集合 ──────────────────────────────────────────────────────────
    objects_created = _unique([s.full_object_name for s in statements if s.operation == "CREATE" and s.full_object_name])
    objects_altered = _unique([s.full_object_name for s in statements if s.operation == "ALTER" and s.full_object_name])
    objects_dropped = _unique([s.full_object_name for s in statements if s.operation == "DROP" and s.full_object_name])
    objects_written = _unique([
        s.full_object_name for s in statements
        if s.operation in {"INSERT", "UPDATE", "DELETE", "TRUNCATE", "MERGE"}
        and s.full_object_name
    ])
    objects_read = _unique([s.full_object_name for s in statements if s.operation == "SELECT" and s.full_object_name])

    script = ParsedScript(
        filename=filename,
        dialect="postgres",
        statements=statements,
        objects_created=objects_created,
        objects_altered=objects_altered,
        objects_dropped=objects_dropped,
        objects_read=objects_read,
        objects_written=objects_written,
        syntax_error_count=syntax_error_count,
        intent_summary="",  # 由 LLM 填充
    )
    return script, issues


# ─────────────────────────────────────────────────────────────────────────────
# 私有辅助：对象名提取
# ─────────────────────────────────────────────────────────────────────────────

def _extract_table_name(table_expr: exp.Expression | None) -> tuple[str, str]:
    """从 exp.Table 中提取 (schema, name)，schema 缺省为 public。"""
    if table_expr is None:
        return "public", ""
    if isinstance(table_expr, exp.Table):
        db_part = table_expr.args.get("db")
        this_part = table_expr.args.get("this")
        schema = db_part.name if db_part else "public"
        name = this_part.name if this_part else ""
        return schema, name
    return "public", str(table_expr)


def _extract_statement_info(
    stmt: exp.Expression, index: int, filename: str
) -> StatementInfo | None:
    """将单条 sqlglot 语句转为 StatementInfo，无法识别时返回 None。"""
    sql_snippet = stmt.sql(dialect="postgres")[:300]

    # ── DDL ──────────────────────────────────────────────────────────────────
    if isinstance(stmt, exp.Create):
        kind = str(stmt.args.get("kind", "TABLE")).upper()
        this = stmt.args.get("this")
        if isinstance(this, exp.Table):
            schema, name = _extract_table_name(this)
        elif isinstance(this, exp.Schema):
            # CREATE TABLE foo (...) — this 是 exp.Schema，内部 this 才是 exp.Table
            inner = this.args.get("this")
            schema, name = _extract_table_name(inner if isinstance(inner, exp.Table) else None)
        elif hasattr(this, "name"):
            schema, name = "public", this.name  # type: ignore[attr-defined]
        else:
            return None
        return StatementInfo(
            index=index, statement_type="DDL", operation="CREATE",
            object_type=kind, object_schema=schema, object_name=name,
            full_object_name=f"{schema}.{name}", raw_sql_snippet=sql_snippet,
        )

    if isinstance(stmt, exp.Alter):
        kind = str(stmt.args.get("kind", "TABLE")).upper()
        this = stmt.args.get("this")
        schema, name = _extract_table_name(this if isinstance(this, exp.Table) else None)
        if not name and hasattr(this, "name"):
            name = this.name  # type: ignore[attr-defined]
        return StatementInfo(
            index=index, statement_type="DDL", operation="ALTER",
            object_type=kind, object_schema=schema, object_name=name,
            full_object_name=f"{schema}.{name}", raw_sql_snippet=sql_snippet,
        )

    if isinstance(stmt, exp.Drop):
        kind = str(stmt.args.get("kind", "TABLE")).upper()
        this = stmt.args.get("this")
        schema, name = _extract_table_name(this if isinstance(this, exp.Table) else None)
        if not name and hasattr(this, "name"):
            name = this.name  # type: ignore[attr-defined]
        return StatementInfo(
            index=index, statement_type="DDL", operation="DROP",
            object_type=kind, object_schema=schema, object_name=name,
            full_object_name=f"{schema}.{name}", raw_sql_snippet=sql_snippet,
        )

    # ── DML ──────────────────────────────────────────────────────────────────
    if isinstance(stmt, exp.Insert):
        this = stmt.args.get("this")
        schema, name = _extract_table_name(this if isinstance(this, exp.Table) else None)
        return StatementInfo(
            index=index, statement_type="DML", operation="INSERT",
            object_type="TABLE", object_schema=schema, object_name=name,
            full_object_name=f"{schema}.{name}" if name else "",
            raw_sql_snippet=sql_snippet,
        )

    if isinstance(stmt, exp.Update):
        this = stmt.args.get("this")
        schema, name = _extract_table_name(this if isinstance(this, exp.Table) else None)
        return StatementInfo(
            index=index, statement_type="DML", operation="UPDATE",
            object_type="TABLE", object_schema=schema, object_name=name,
            full_object_name=f"{schema}.{name}" if name else "",
            raw_sql_snippet=sql_snippet,
        )

    if isinstance(stmt, exp.Delete):
        this = stmt.args.get("this")
        schema, name = _extract_table_name(this if isinstance(this, exp.Table) else None)
        return StatementInfo(
            index=index, statement_type="DML", operation="DELETE",
            object_type="TABLE", object_schema=schema, object_name=name,
            full_object_name=f"{schema}.{name}" if name else "",
            raw_sql_snippet=sql_snippet,
        )

    if isinstance(stmt, exp.TruncateTable):
        expressions = stmt.args.get("expressions") or []
        first = expressions[0] if expressions else None
        schema, name = _extract_table_name(first if isinstance(first, exp.Table) else None)
        return StatementInfo(
            index=index, statement_type="DML", operation="TRUNCATE",
            object_type="TABLE", object_schema=schema, object_name=name,
            full_object_name=f"{schema}.{name}" if name else "",
            raw_sql_snippet=sql_snippet,
        )

    if isinstance(stmt, exp.Merge):
        into = stmt.args.get("into")
        schema, name = _extract_table_name(into if isinstance(into, exp.Table) else None)
        return StatementInfo(
            index=index, statement_type="DML", operation="MERGE",
            object_type="TABLE", object_schema=schema, object_name=name,
            full_object_name=f"{schema}.{name}" if name else "",
            raw_sql_snippet=sql_snippet,
        )

    # ── QUERY ─────────────────────────────────────────────────────────────────
    if isinstance(stmt, exp.Select):
        # 取 FROM 子句的第一张表作为"主表"
        tables = list(stmt.find_all(exp.Table))
        schema, name = _extract_table_name(tables[0]) if tables else ("", "")
        return StatementInfo(
            index=index, statement_type="QUERY", operation="SELECT",
            object_type="TABLE", object_schema=schema, object_name=name,
            full_object_name=f"{schema}.{name}" if name else "",
            raw_sql_snippet=sql_snippet,
        )

    # ── DCL ───────────────────────────────────────────────────────────────────
    if isinstance(stmt, exp.Grant):
        return StatementInfo(
            index=index, statement_type="DCL", operation="GRANT",
            object_type="UNKNOWN", object_schema="", object_name="",
            full_object_name="", raw_sql_snippet=sql_snippet,
        )
    if isinstance(stmt, exp.Revoke):
        return StatementInfo(
            index=index, statement_type="DCL", operation="REVOKE",
            object_type="UNKNOWN", object_schema="", object_name="",
            full_object_name="", raw_sql_snippet=sql_snippet,
        )

    return None  # 未知语句类型，跳过


# ─────────────────────────────────────────────────────────────────────────────
# 私有辅助：质量规则检查
# ─────────────────────────────────────────────────────────────────────────────

def _check_quality_rules(stmt: exp.Expression, filename: str) -> list[SyntaxIssue]:
    """对单条语句执行所有静态质量规则，返回发现的问题列表。"""
    issues: list[SyntaxIssue] = []
    try:
        snippet = stmt.sql(dialect="postgres")[:300]
    except Exception:  # noqa: BLE001
        snippet = ""

    # ── Rule: SELECT * ────────────────────────────────────────────────────────
    if isinstance(stmt, (exp.Select, exp.Insert)):
        for node in stmt.find_all(exp.Star):
            # COUNT(*) 中的 * 不算
            if not isinstance(node.parent, exp.Count):
                issues.append(SyntaxIssue(
                    filename=filename, severity="WARNING", category="CONVENTION",
                    rule="SELECT_STAR",
                    message="使用了 SELECT *，建议明确指定所需列名",
                    sql_snippet=snippet,
                    suggestion="将 SELECT * 替换为明确的列名列表，减少不必要的数据传输",
                ))
                break

    # ── Rule: UPDATE 无 WHERE ─────────────────────────────────────────────────
    if isinstance(stmt, exp.Update) and stmt.find(exp.Where) is None:
        issues.append(SyntaxIssue(
            filename=filename, severity="ERROR", category="SECURITY",
            rule="UPDATE_WITHOUT_WHERE",
            message="UPDATE 语句缺少 WHERE 条件，将更新表中所有行",
            sql_snippet=snippet,
            suggestion="添加 WHERE 条件；若确需全表更新，请在变更说明中明确说明",
        ))

    # ── Rule: DELETE 无 WHERE ─────────────────────────────────────────────────
    if isinstance(stmt, exp.Delete) and stmt.find(exp.Where) is None:
        issues.append(SyntaxIssue(
            filename=filename, severity="ERROR", category="SECURITY",
            rule="DELETE_WITHOUT_WHERE",
            message="DELETE 语句缺少 WHERE 条件，将删除表中所有行",
            sql_snippet=snippet,
            suggestion="添加 WHERE 条件以限制删除范围",
        ))

    # ── Rule: TRUNCATE ────────────────────────────────────────────────────────
    if isinstance(stmt, exp.TruncateTable):
        issues.append(SyntaxIssue(
            filename=filename, severity="WARNING", category="SECURITY",
            rule="TRUNCATE_TABLE",
            message="TRUNCATE 操作将清空整张表的所有数据，属不可逆破坏性操作",
            sql_snippet=snippet,
            suggestion="确认已做好数据备份，并在变更说明中明确说明此操作的必要性",
        ))

    # ── Rule: DROP 未加 IF EXISTS ─────────────────────────────────────────────
    if isinstance(stmt, exp.Drop) and not stmt.args.get("exists"):
        issues.append(SyntaxIssue(
            filename=filename, severity="INFO", category="CONVENTION",
            rule="DROP_WITHOUT_IF_EXISTS",
            message="DROP 语句未使用 IF EXISTS，若对象不存在将导致脚本报错",
            sql_snippet=snippet,
            suggestion="改为 DROP ... IF EXISTS 以提升脚本健壮性",
        ))

    # ── Rule: CREATE TABLE 未加 IF NOT EXISTS ─────────────────────────────────
    if isinstance(stmt, exp.Create):
        kind = str(stmt.args.get("kind", "")).upper()
        if kind == "TABLE" and not stmt.args.get("exists"):
            issues.append(SyntaxIssue(
                filename=filename, severity="INFO", category="CONVENTION",
                rule="CREATE_WITHOUT_IF_NOT_EXISTS",
                message="CREATE TABLE 未使用 IF NOT EXISTS，若表已存在将报错",
                sql_snippet=snippet,
                suggestion="改为 CREATE TABLE IF NOT EXISTS 以提升脚本幂等性",
            ))

    return issues


def _unique(items: list[str]) -> list[str]:
    """去重并保持顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

