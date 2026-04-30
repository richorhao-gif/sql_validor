"""
tests/unit/test_sql_parser.py
"""
from __future__ import annotations

import pytest

from sql_validator.core.sql_parser import parse_sql_file, extract_all_object_names


# ── parse_sql_file ────────────────────────────────────────────────────────────

def test_parse_create_table():
    file = {"filename": "test.sql", "content": "CREATE TABLE public.orders (id SERIAL PRIMARY KEY);"}
    script, issues = parse_sql_file(file)
    assert script.filename == "test.sql"
    assert len(script.statements) == 1
    assert script.statements[0].operation == "CREATE"
    assert "public.orders" in script.objects_created
    assert script.syntax_error_count == 0


def test_parse_alter_table():
    file = {"filename": "alter.sql", "content": "ALTER TABLE orders ADD COLUMN status VARCHAR(20);"}
    script, issues = parse_sql_file(file)
    assert script.statements[0].operation == "ALTER"
    assert "public.orders" in script.objects_altered


def test_parse_drop_table():
    file = {"filename": "drop.sql", "content": "DROP TABLE IF EXISTS old_table;"}
    script, issues = parse_sql_file(file)
    assert script.statements[0].operation == "DROP"


def test_detect_update_without_where():
    file = {"filename": "bad.sql", "content": "UPDATE orders SET status = 'active';"}
    script, issues = parse_sql_file(file)
    rules = [i.rule for i in issues]
    assert "UPDATE_WITHOUT_WHERE" in rules


def test_detect_delete_without_where():
    file = {"filename": "bad.sql", "content": "DELETE FROM orders;"}
    script, issues = parse_sql_file(file)
    rules = [i.rule for i in issues]
    assert "DELETE_WITHOUT_WHERE" in rules


def test_detect_select_star():
    file = {"filename": "star.sql", "content": "SELECT * FROM dim_date;"}
    script, issues = parse_sql_file(file)
    rules = [i.rule for i in issues]
    assert "SELECT_STAR" in rules


def test_detect_truncate():
    file = {"filename": "trunc.sql", "content": "TRUNCATE TABLE fact_sales;"}
    script, issues = parse_sql_file(file)
    rules = [i.rule for i in issues]
    assert "TRUNCATE_TABLE" in rules


def test_parse_insert():
    file = {"filename": "insert.sql", "content": "INSERT INTO dim_user SELECT id, name FROM staging_user;"}
    script, issues = parse_sql_file(file)
    assert script.statements[0].operation == "INSERT"
    assert "public.dim_user" in script.objects_written


def test_empty_result_on_invalid_sql():
    file = {"filename": "bad.sql", "content": "THIS IS NOT SQL AT ALL !!!"}
    script, issues = parse_sql_file(file)
    # 不应抛出异常，应返回解析结果（可能有错误）
    assert isinstance(issues, list)


def test_extract_all_object_names():
    files = [
        {"filename": "a.sql", "content": "CREATE TABLE public.dim_user (id INT);"},
        {"filename": "b.sql", "content": "INSERT INTO public.dim_user SELECT * FROM staging.user_raw;"},
    ]
    names = extract_all_object_names(files)
    assert "public.dim_user" in names


# ── IF NOT EXISTS / IF EXISTS 规则 ────────────────────────────────────────────

def test_create_without_if_not_exists():
    file = {"filename": "t.sql", "content": "CREATE TABLE orders (id INT);"}
    _, issues = parse_sql_file(file)
    rules = [i.rule for i in issues]
    assert "CREATE_WITHOUT_IF_NOT_EXISTS" in rules


def test_drop_without_if_exists():
    file = {"filename": "t.sql", "content": "DROP TABLE orders;"}
    _, issues = parse_sql_file(file)
    rules = [i.rule for i in issues]
    assert "DROP_WITHOUT_IF_EXISTS" in rules
