"""
utils.py
─────────
项目公用工具函数。

目前包含：
  - parse_developer_from_filename : 从 CODING 标准文件名解析开发者姓名
"""
from __future__ import annotations

import re
from pathlib import Path

# 文件名格式:  YYYYMMDD_开发者_#编号_描述.sql
_DEVELOPER_RE = re.compile(r"^\d{8}_(.+?)_#\d+")


def parse_developer_from_filename(filename: str) -> str:
    """
    从 CODING 标准文件名中提取开发者姓名。

    文件名格式示例：
        20260422_刘全祥_#2590_调味品产品属性逻辑-1对象.sql
        20260422_王五_#2591_物料简称导入-1刷数.sql

    Args:
        filename: 文件名（含或不含路径、含或不含 .sql 后缀均可）

    Returns:
        开发者姓名字符串；若文件名不符合 CODING 格式则返回空字符串。
    """
    stem = Path(filename).stem          # 去掉 .sql 后缀
    m = _DEVELOPER_RE.match(stem)
    if not m:
        return ""
    name = m.group(1)
    # 去掉姓名末尾可能附带的数字序号（历史遗留，如"刘全祥1"→"刘全祥"）
    name = re.sub(r"\d+$", "", name).strip()
    return name
