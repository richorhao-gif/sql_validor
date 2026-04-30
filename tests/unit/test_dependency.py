"""
tests/unit/test_dependency.py
"""
from __future__ import annotations

import pytest

from sql_validator.core.dependency import build_dependency_graph, _topological_sort


def _make_script(filename: str, created: list, read: list, written: list) -> dict:
    return {
        "filename": filename,
        "objects_created": created,
        "objects_altered": [],
        "objects_dropped": [],
        "objects_read": read,
        "objects_written": written,
    }


def test_simple_dependency():
    scripts = [
        _make_script("b.sql", [], ["public.dim_date"], []),
        _make_script("a.sql", ["public.dim_date"], [], []),
    ]
    result = build_dependency_graph(scripts)
    order = result["execution_order"]
    # a.sql 必须在 b.sql 之前
    assert order.index("a.sql") < order.index("b.sql")


def test_no_dependency():
    scripts = [
        _make_script("a.sql", ["public.table_a"], [], []),
        _make_script("b.sql", ["public.table_b"], [], []),
    ]
    result = build_dependency_graph(scripts)
    assert not result["has_cycles"]
    assert set(result["execution_order"]) == {"a.sql", "b.sql"}


def test_cycle_detection():
    scripts = [
        _make_script("a.sql", ["public.t_a"], ["public.t_b"], []),
        _make_script("b.sql", ["public.t_b"], ["public.t_a"], []),
    ]
    result = build_dependency_graph(scripts)
    assert result["has_cycles"] is True
    assert len(result["cycle_paths"]) > 0


def test_topological_sort_linear():
    nodes = ["a", "b", "c"]
    dep_map = {"b": ["a"], "c": ["b"]}
    order, has_cycles, _ = _topological_sort(nodes, dep_map)
    assert order == ["a", "b", "c"]
    assert not has_cycles


def test_three_way_dependency():
    scripts = [
        _make_script("init.sql", ["public.dim_user"], [], []),
        _make_script("migrate.sql", [], ["public.dim_user"], ["public.dim_user"]),
        _make_script("index.sql", [], [], []),
    ]
    result = build_dependency_graph(scripts)
    order = result["execution_order"]
    assert order.index("init.sql") < order.index("migrate.sql")
