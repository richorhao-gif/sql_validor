"""
tools/analysis_tools.py
────────────────────────
纯代码分析工具，封装 sqlglot AST 解析和 Kahn 拓扑排序。

工厂函数 create_analysis_tools(sql_files) 使用闭包将 SQL 文件集合预加载进工具，
Agent 调用这些工具时无需传入文件内容，直接获取结构化分析结果。

工具列表：
  parse_sql_files()      - AST 解析所有文件，返回变更清单
  get_execution_order()  - 拓扑排序，返回推荐执行顺序
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool, tool

from sql_validator.core.dependency import build_dependency_graph
from sql_validator.core.sql_parser import parse_sql_file


def create_analysis_tools(sql_files: list[dict[str, Any]]) -> list[BaseTool]:
    """
    创建预加载了本次发版 SQL 文件的纯代码分析工具。

    Args:
        sql_files: SQLFile.model_dump() 列表，必须包含 filename 和 content 字段

    Returns:
        工具列表，可与 DB 工具合并后传入 create_react_agent
    """

    @tool
    def parse_sql_files() -> str:
        """
        对本次发版的所有 SQL 文件进行 AST 解析，返回每个文件的结构化变更清单。

        返回字段说明：
          - filename          : 文件名
          - objects_created   : 本文件新建的对象（CREATE TABLE/VIEW/FOREIGN TABLE 等）
          - objects_altered   : 本文件修改的对象（ALTER TABLE/VIEW）
          - objects_dropped   : 本文件删除的对象（DROP TABLE/VIEW 等）
          - objects_written   : 本文件写入数据的对象（INSERT/UPDATE/DELETE/TRUNCATE）
          - objects_read      : 本文件读取的对象（SELECT FROM）
          - statements        : 逐语句明细（操作类型、对象类型、目标对象全限定名）
          - syntax_errors     : 语法错误列表（severity=ERROR）
          - quality_warnings  : 代码质量警告（如无 WHERE 的 DML、缺少幂等保护等）

        **必须作为审查的第一步调用**，后续所有 DB 查询决策都基于此输出。
        注意：objects_created 中的对象是本次新建的，数据库中尚不存在，无需查询其结构。
        """
        results = []
        for f in sql_files:
            script, issues = parse_sql_file(f)
            results.append({
                "filename": script.filename,
                "objects_created": script.objects_created,
                "objects_altered": script.objects_altered,
                "objects_dropped": script.objects_dropped,
                "objects_written": script.objects_written,
                "objects_read": script.objects_read,
                "statements": [s.model_dump() for s in script.statements],
                "syntax_errors": [
                    i.model_dump() for i in issues if i.severity == "ERROR"
                ],
                "quality_warnings": [
                    i.model_dump() for i in issues if i.severity != "ERROR"
                ],
            })
        return json.dumps(results, ensure_ascii=False, indent=2)

    @tool
    def get_execution_order() -> str:
        """
        基于 Kahn 拓扑排序算法，计算本次发版 SQL 文件的推荐执行顺序。

        依赖规则：若文件 B 读写的对象中有任一是文件 A 新建的，则 B 依赖 A，A 必须先执行。

        返回字段说明：
          - execution_order : 拓扑排序后的文件执行顺序列表（前置文件在前）
          - dependency_map  : 每个文件依赖哪些文件（B → [A] 表示 B 依赖 A）
          - has_cycles      : 是否存在循环依赖（true 则无法确定执行顺序，属于 CRITICAL 风险）
          - cycle_paths     : 具体的循环路径（有循环时填充）
        """
        parsed = []
        for f in sql_files:
            script, _ = parse_sql_file(f)
            parsed.append(script.model_dump())
        graph = build_dependency_graph(parsed)
        return json.dumps(graph, ensure_ascii=False, indent=2)

    return [parse_sql_files, get_execution_order]
