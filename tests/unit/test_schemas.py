"""
tests/unit/test_schemas.py
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sql_validator.schemas.inputs import SQLFile, ValidationRequest
from sql_validator.schemas.db_context import DBSnapshot, DBTable, DBColumn
from sql_validator.schemas.analysis import SyntaxIssue, ParsedScript
from sql_validator.schemas.reports import ChangeVerificationResult


# ── SQLFile ───────────────────────────────────────────────────────────────────

def test_sql_file_valid():
    f = SQLFile(filename="init.sql", content="SELECT 1;")
    assert f.filename == "init.sql"


def test_sql_file_invalid_extension():
    with pytest.raises(ValidationError, match="必须以 .sql 结尾"):
        SQLFile(filename="init.txt", content="SELECT 1;")


def test_sql_file_empty_content():
    with pytest.raises(ValidationError):
        SQLFile(filename="init.sql", content="   ")


def test_sql_file_path_traversal():
    with pytest.raises(ValidationError):
        SQLFile(filename="../etc/passwd.sql", content="SELECT 1;")


# ── ValidationRequest ──────────────────────────────────────────────────────────

def test_validation_request_duplicate_filenames():
    files = [
        SQLFile(filename="a.sql", content="SELECT 1;"),
        SQLFile(filename="a.sql", content="SELECT 2;"),
    ]
    with pytest.raises(ValidationError, match="重复的文件名"):
        ValidationRequest(sql_files=files, change_description="测试变更说明文字")


def test_validation_request_short_description():
    with pytest.raises(ValidationError):
        ValidationRequest(
            sql_files=[SQLFile(filename="a.sql", content="SELECT 1;")],
            change_description="太短",
        )


def test_validation_request_file_count():
    req = ValidationRequest(
        sql_files=[SQLFile(filename="a.sql", content="SELECT 1;")],
        change_description="这是一段足够长的变更说明文字",
    )
    with pytest.raises(ValueError, match="超过上限"):
        req.check_file_count(max_files=0)


# ── DBSnapshot ────────────────────────────────────────────────────────────────

def test_db_snapshot_default_empty():
    snap = DBSnapshot()
    assert snap.tables == {}
    assert snap.views == {}


def test_db_table_column_names():
    table = DBTable(
        schema_name="public",
        table_name="orders",
        full_name="public.orders",
        columns=[
            DBColumn(name="id", data_type="integer"),
            DBColumn(name="status", data_type="varchar"),
        ],
    )
    assert table.column_names == ["id", "status"]


# ── ChangeVerificationResult ──────────────────────────────────────────────────

def test_change_verification_valid():
    r = ChangeVerificationResult(
        verdict="PASS",
        risk_level="LOW",
        confidence=95,
        analysis_notes="全部一致",
    )
    assert r.verdict == "PASS"


def test_change_verification_invalid_verdict():
    with pytest.raises(ValidationError):
        ChangeVerificationResult(
            verdict="UNKNOWN",  # 不是合法值
            risk_level="LOW",
            confidence=95,
            analysis_notes="测试",
        )


def test_change_verification_confidence_range():
    with pytest.raises(ValidationError):
        ChangeVerificationResult(
            verdict="PASS",
            risk_level="LOW",
            confidence=150,  # 超出范围
            analysis_notes="测试",
        )
