"""
tests/unit/test_db_comparator.py
"""
from __future__ import annotations

import pytest

from sql_validator.core.db_comparator import compare_against_snapshot, compute_quality_score
from sql_validator.schemas.analysis import ParsedScript, StatementInfo
from sql_validator.schemas.db_context import DBColumn, DBSnapshot, DBTable


def _make_snapshot_with_table(full_name: str) -> DBSnapshot:
    schema, table = full_name.split(".", 1)
    return DBSnapshot(
        tables={
            full_name: DBTable(
                schema_name=schema,
                table_name=table,
                full_name=full_name,
                columns=[DBColumn(name="id", data_type="integer")],
            )
        }
    )


def _make_script_with_stmt(filename: str, operation: str, obj: str) -> ParsedScript:
    return ParsedScript(
        filename=filename,
        statements=[
            StatementInfo(
                index=0,
                statement_type="DDL" if operation in ("CREATE", "ALTER", "DROP") else "DML",
                operation=operation,
                object_type="TABLE",
                object_schema=obj.split(".")[0],
                object_name=obj.split(".")[1],
                full_object_name=obj,
                raw_sql_snippet=f"{operation} TABLE {obj};",
            )
        ],
    )


def test_create_existing_table_flagged():
    snapshot = _make_snapshot_with_table("public.orders")
    script = _make_script_with_stmt("test.sql", "CREATE", "public.orders")
    script = script.model_copy(update={"objects_created": ["public.orders"]})
    issues = compare_against_snapshot(script, snapshot)
    assert any(i.rule == "OBJECT_ALREADY_EXISTS" for i in issues)


def test_drop_nonexistent_table_warned():
    snapshot = DBSnapshot()  # 空快照，表不存在
    script = _make_script_with_stmt("test.sql", "DROP", "public.ghost_table")
    issues = compare_against_snapshot(script, snapshot)
    assert any(i.rule == "DROP_NONEXISTENT_OBJECT" for i in issues)


def test_insert_into_missing_table_info():
    snapshot = DBSnapshot()
    script = _make_script_with_stmt("test.sql", "INSERT", "public.new_table")
    script = script.model_copy(update={"objects_written": ["public.new_table"]})
    issues = compare_against_snapshot(script, snapshot)
    assert any(i.rule == "DML_TARGET_NOT_IN_DB" for i in issues)


def test_no_issues_for_clean_operations():
    snapshot = _make_snapshot_with_table("public.orders")
    # SELECT 已存在的表，无问题
    script = ParsedScript(
        filename="clean.sql",
        statements=[
            StatementInfo(
                index=0,
                statement_type="QUERY",
                operation="SELECT",
                object_type="TABLE",
                object_schema="public",
                object_name="orders",
                full_object_name="public.orders",
                raw_sql_snippet="SELECT id FROM public.orders;",
            )
        ],
        objects_read=["public.orders"],
    )
    issues = compare_against_snapshot(script, snapshot)
    assert len(issues) == 0


def test_compute_quality_score():
    issues = [
        {"severity": "ERROR"},
        {"severity": "ERROR"},
        {"severity": "WARNING"},
        {"severity": "INFO"},
    ]
    score = compute_quality_score(issues)
    # 100 - 10 - 10 - 3 - 0.5 = 76.5 → int → 76
    assert score == 76


def test_quality_score_floor_zero():
    issues = [{"severity": "ERROR"}] * 15
    score = compute_quality_score(issues)
    assert score == 0
