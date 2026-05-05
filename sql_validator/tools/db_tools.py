"""
tools/db_tools.py
──────────────────
基于原生 psycopg 实现的 PostgreSQL 专用只读工具集。
供 db_context_agent（ReAct）使用，覆盖四类场景：

  第一组 - 环境探索  : get_all_schemas, list_objects_in_schema
  第二组 - 对象结构  : get_table_structure, get_view_definition, get_foreign_table_info
  第三组 - 依赖关系  : get_downstream_dependents, get_upstream_dependencies,
                       get_objects_using_server
  第四组 - PG专有特性: get_rls_policies, get_triggers, get_sequences, get_indexes
  第五组 - 兜底查询  : query_pg_catalog
"""
from __future__ import annotations

import json
import re
import warnings
from typing import Any

# @tool 装饰器用 Pydantic 生成输入模型时，参数名 "schema" 与 BaseModel 内置属性同名，
# 该警告属于误报（不影响功能），统一屏蔽。
warnings.filterwarnings(
    "ignore",
    message=r'Field name "schema" .* shadows an attribute',
    category=UserWarning,
)

from langchain_core.tools import BaseTool, tool


# ─────────────────────────────────────────────────────────────────────────────
# 连接管理
# ─────────────────────────────────────────────────────────────────────────────

def _get_conn(dsn: str):
    """获取 psycopg 连接（每次调用建立短连接）。"""
    import psycopg
    return psycopg.connect(dsn)


def _query(dsn: str, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """执行查询，返回 list[dict]。"""
    with _get_conn(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def _fmt(rows: list[dict]) -> str:
    """将结果格式化为 JSON 字符串，供 LLM 阅读。"""
    return json.dumps(rows, ensure_ascii=False, default=str, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# 兜底查询安全校验
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_SYSTEM_PREFIXES = ("pg_", "information_schema.")
_WRITE_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|truncate|create|alter|grant|revoke|"
    r"call|execute|copy|vacuum|analyze|reindex)\b",
    re.IGNORECASE,
)

_MAX_JOINS = 3   # 防止笛卡尔积炸库
_MAX_ROWS  = 100


def _validate_catalog_query(sql: str) -> str | None:
    """
    校验 query_pg_catalog 的 SQL 安全性。
    返回 None 表示通过；返回字符串表示拒绝原因。
    """
    sql_lower = sql.lower().strip()

    # 必须是 SELECT
    if not sql_lower.startswith(("select", "with")):
        return "只允许 SELECT / WITH 开头的查询"

    # 不允许写操作关键字
    if _WRITE_KEYWORDS.search(sql):
        return "SQL 中包含写操作关键字，已拒绝"

    # 目标表必须是系统表
    # 提取 FROM / JOIN 后的表名做简单判断
    table_refs = re.findall(
        r"(?:from|join)\s+([a-z_][a-z0-9_.]*)",
        sql_lower,
    )
    for ref in table_refs:
        # 去掉 schema 前缀后判断
        base = ref.split(".")[-1] if "." in ref else ref
        schema = ref.split(".")[0] if "." in ref else ""
        if schema == "information_schema":
            continue
        if not base.startswith("pg_"):
            return (
                f"表 '{ref}' 不是系统表（pg_* / information_schema.*），已拒绝。"
                "此工具仅用于查询 PostgreSQL 系统目录。"
            )

    # JOIN 数量限制
    join_count = len(re.findall(r"\bjoin\b", sql_lower))
    if join_count > _MAX_JOINS:
        return f"JOIN 数量（{join_count}）超过限制（{_MAX_JOINS}），防止性能问题"

    # 必须有 WHERE 条件（防止全表扫描系统表）
    if "where" not in sql_lower:
        return "必须包含 WHERE 条件，防止对系统表进行全量扫描"

    return None


# ─────────────────────────────────────────────────────────────────────────────
# 工具工厂
# ─────────────────────────────────────────────────────────────────────────────

def create_db_tools(dsn: str) -> list[BaseTool]:
    """
    创建面向 db_context_agent 的 13 个只读工具。

    Args:
        dsn: PostgreSQL 连接字符串（postgresql://user:pass@host:port/db）

    Returns:
        工具列表，可直接传入 create_react_agent
    """

    # ── 第一组：环境探索 ─────────────────────────────────────────────────────

    @tool
    def get_all_schemas() -> str:
        """
        列出数据库中所有用户可见的 schema 及其对象数量概览。
        应作为探查的第一步，建立仓库全貌认知。
        """
        rows = _query(dsn, """
            SELECT
                n.nspname                          AS schema_name,
                COUNT(c.relname) FILTER (WHERE c.relkind = 'r') AS tables,
                COUNT(c.relname) FILTER (WHERE c.relkind = 'v') AS views,
                COUNT(c.relname) FILTER (WHERE c.relkind = 'f') AS foreign_tables
            FROM pg_catalog.pg_namespace n
            LEFT JOIN pg_catalog.pg_class c ON c.relnamespace = n.oid
                AND c.relkind IN ('r','v','f')
            WHERE n.nspname NOT IN ('pg_catalog','pg_toast','pg_temp_1',
                                    'pg_toast_temp_1','information_schema')
              AND n.nspname NOT LIKE 'pg_temp_%%'
              AND n.nspname NOT LIKE 'pg_toast_temp_%%'
            GROUP BY n.nspname
            ORDER BY n.nspname
        """)
        return _fmt(rows)

    @tool
    def list_objects_in_schema(schema: str) -> str:
        """
        列出指定 schema 下的所有对象：普通表、视图、外部表（FOREIGN TABLE），三类一起返回。
        Args:
            schema: schema 名称，例如 'ods'、'dwd'、'ds_mannual'
        """
        rows = _query(dsn, """
            SELECT
                c.relname   AS object_name,
                CASE c.relkind
                    WHEN 'r' THEN 'table'
                    WHEN 'v' THEN 'view'
                    WHEN 'f' THEN 'foreign_table'
                    WHEN 'm' THEN 'materialized_view'
                    ELSE c.relkind::text
                END         AS object_type,
                obj_description(c.oid, 'pg_class') AS comment
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s
              AND c.relkind IN ('r','v','f','m')
            ORDER BY c.relkind, c.relname
        """, (schema,))
        return _fmt(rows)

    # ── 第二组：对象结构 ─────────────────────────────────────────────────────

    @tool
    def get_table_structure(schema: str, table: str) -> str:
        """
        获取普通表的完整结构：列信息、主键约束、存储引擎（如 beam）、表注释。
        Args:
            schema: schema 名称
            table:  表名
        """
        cols = _query(dsn, """
            SELECT
                a.attnum                                    AS ordinal,
                a.attname                                   AS column_name,
                pg_catalog.format_type(a.atttypid,a.atttypmod) AS data_type,
                NOT a.attnotnull                             AS is_nullable,
                pg_catalog.pg_get_expr(ad.adbin, ad.adrelid) AS column_default,
                col_description(a.attrelid, a.attnum)       AS comment
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class     c ON c.oid = a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_catalog.pg_attrdef ad
                   ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
            WHERE n.nspname = %s AND c.relname = %s
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
        """, (schema, table))

        pks = _query(dsn, """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_name = tc.constraint_name
             AND kcu.table_schema    = tc.table_schema
            WHERE tc.table_schema    = %s
              AND tc.table_name      = %s
              AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
        """, (schema, table))

        # 存储引擎（USING beam 等）
        storage = _query(dsn, """
            SELECT am.amname AS storage_engine
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_catalog.pg_am am ON am.oid = c.relam
            WHERE n.nspname = %s AND c.relname = %s
        """, (schema, table))

        tbl_comment = _query(dsn, """
            SELECT obj_description(c.oid,'pg_class') AS table_comment
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
        """, (schema, table))

        result = {
            "columns": cols,
            "primary_keys": [r["column_name"] for r in pks],
            "storage_engine": storage[0]["storage_engine"] if storage else None,
            "table_comment": tbl_comment[0]["table_comment"] if tbl_comment else None,
        }
        return _fmt([result])

    @tool
    def get_view_definition(schema: str, view: str) -> str:
        """
        获取视图的完整 SQL 定义（含 CTE）、视图选项（如 security_invoker）及注释。
        用于理解跨 schema 引用链和权限行为。
        Args:
            schema: schema 名称
            view:   视图名
        """
        rows = _query(dsn, """
            SELECT
                v.table_schema,
                v.table_name,
                v.view_definition,
                v.is_updatable,
                v.is_insertable_into,
                obj_description(c.oid,'pg_class') AS comment,
                -- 视图选项（security_invoker / security_barrier 等）
                array_to_string(c.reloptions, ', ') AS view_options
            FROM information_schema.views v
            JOIN pg_catalog.pg_class c
              ON c.relname = v.table_name
            JOIN pg_catalog.pg_namespace n
              ON n.oid = c.relnamespace AND n.nspname = v.table_schema
            WHERE v.table_schema = %s AND v.table_name = %s
        """, (schema, view))
        return _fmt(rows)

    @tool
    def get_foreign_table_info(schema: str, table: str) -> str:
        """
        获取 FOREIGN TABLE（外部表）的列结构、挂载的 SERVER 名称及 OSS OPTIONS
        （如 prefix、format、delimiter 等）。
        Args:
            schema: schema 名称，通常为 ds_mannual 等
            table:  外部表名
        """
        meta = _query(dsn, """
            SELECT
                n.nspname       AS schema_name,
                c.relname       AS table_name,
                s.srvname       AS server_name,
                ft.ftoptions    AS ftoptions
            FROM pg_catalog.pg_foreign_table ft
            JOIN pg_catalog.pg_class         c  ON c.oid  = ft.ftrelid
            JOIN pg_catalog.pg_namespace     n  ON n.oid  = c.relnamespace
            JOIN pg_catalog.pg_foreign_server s  ON s.oid = ft.ftserver
            WHERE n.nspname = %s AND c.relname = %s
        """, (schema, table))

        # ftoptions 是 text[] 数组，每项格式为 "key=value"
        options: dict[str, str] = {}
        for row in meta:
            for opt_str in row.get("ftoptions") or []:
                if opt_str and "=" in opt_str:
                    k, v = opt_str.split("=", 1)
                    options[k] = v

        cols = _query(dsn, """
            SELECT
                a.attnum  AS ordinal,
                a.attname AS column_name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                col_description(a.attrelid, a.attnum) AS comment
            FROM pg_catalog.pg_attribute  a
            JOIN pg_catalog.pg_class      c ON c.oid = a.attrelid
            JOIN pg_catalog.pg_namespace  n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
        """, (schema, table))

        server_name = meta[0]["server_name"] if meta else None
        result = {
            "schema": schema,
            "table": table,
            "server_name": server_name,
            "oss_options": options,
            "columns": cols,
        }
        return _fmt([result])

    # ── 第三组：依赖关系 ─────────────────────────────────────────────────────

    @tool
    def get_downstream_dependents(schema: str, obj: str) -> str:
        """
        查询哪些对象依赖了指定对象（即 DROP 该对象会影响哪些下游）。
        基于 pg_depend 系统表，用于评估 DROP TABLE / DROP VIEW 的级联风险。
        Args:
            schema: 被依赖对象所在的 schema
            obj:    被依赖的对象名（表名或视图名）
        """
        rows = _query(dsn, """
            SELECT DISTINCT
                vn.nspname  AS dependent_schema,
                vc.relname  AS dependent_object,
                CASE vc.relkind
                    WHEN 'v' THEN 'view'
                    WHEN 'm' THEN 'materialized_view'
                    WHEN 'r' THEN 'table'
                    ELSE vc.relkind::text
                END         AS dependent_type
            FROM pg_catalog.pg_rewrite     r
            JOIN pg_catalog.pg_class       vc   ON vc.oid  = r.ev_class
            JOIN pg_catalog.pg_namespace   vn   ON vn.oid  = vc.relnamespace
            JOIN pg_catalog.pg_depend      d    ON d.objid = r.oid
            JOIN pg_catalog.pg_class       ref  ON ref.oid = d.refobjid
            JOIN pg_catalog.pg_namespace   refn ON refn.oid = ref.relnamespace
            WHERE refn.nspname = %s
              AND ref.relname  = %s
              AND d.deptype    = 'n'
              AND vc.relkind  IN ('v','m')
              AND vc.oid      <> ref.oid
            ORDER BY vn.nspname, vc.relname
        """, (schema, obj))
        return _fmt(rows) if rows else json.dumps(
            {"message": f"{schema}.{obj} 没有发现下游依赖对象"}, ensure_ascii=False
        )

    @tool
    def get_upstream_dependencies(schema: str, obj: str) -> str:
        """
        查询指定对象引用了哪些上游对象（该视图/表依赖了什么）。
        用于确认发版后引用链完整性，以及跨 schema 的隐式依赖。
        Args:
            schema: 对象所在的 schema
            obj:    对象名（通常是视图名）
        """
        rows = _query(dsn, """
            SELECT DISTINCT
                refn.nspname  AS ref_schema,
                ref.relname   AS ref_object,
                CASE ref.relkind
                    WHEN 'r' THEN 'table'
                    WHEN 'v' THEN 'view'
                    WHEN 'f' THEN 'foreign_table'
                    WHEN 'm' THEN 'materialized_view'
                    ELSE ref.relkind::text
                END           AS ref_type
            FROM pg_catalog.pg_rewrite     r
            JOIN pg_catalog.pg_class       vc   ON vc.oid  = r.ev_class
            JOIN pg_catalog.pg_namespace   vn   ON vn.oid  = vc.relnamespace
            JOIN pg_catalog.pg_depend      d    ON d.objid = r.oid
            JOIN pg_catalog.pg_class       ref  ON ref.oid = d.refobjid
            JOIN pg_catalog.pg_namespace   refn ON refn.oid = ref.relnamespace
            WHERE vn.nspname = %s
              AND vc.relname = %s
              AND d.deptype  = 'n'
              AND ref.relkind IN ('r','v','f','m')
              AND ref.oid   <> vc.oid
            ORDER BY refn.nspname, ref.relname
        """, (schema, obj))
        return _fmt(rows) if rows else json.dumps(
            {"message": f"{schema}.{obj} 没有发现上游依赖"}, ensure_ascii=False
        )

    @tool
    def get_objects_using_server(server_name: str) -> str:
        """
        查询哪些 FOREIGN TABLE 挂载在同一个 FOREIGN SERVER 下。
        用于评估修改 OSS server 配置时的影响范围。
        Args:
            server_name: FOREIGN SERVER 名称，例如 'oss_serv'
        """
        rows = _query(dsn, """
            SELECT
                n.nspname       AS schema_name,
                c.relname       AS table_name,
                ft.ftoptions    AS ftoptions
            FROM pg_catalog.pg_foreign_table  ft
            JOIN pg_catalog.pg_class          c  ON c.oid  = ft.ftrelid
            JOIN pg_catalog.pg_namespace      n  ON n.oid  = c.relnamespace
            JOIN pg_catalog.pg_foreign_server s  ON s.oid  = ft.ftserver
            WHERE s.srvname = %s
            ORDER BY n.nspname, c.relname
        """, (server_name,))
        return _fmt(rows)

    # ── 第四组：PostgreSQL 专有特性 ──────────────────────────────────────────

    @tool
    def get_rls_policies(schema: str, table: str) -> str:
        """
        查询表上的行级安全（RLS）策略。
        与 security_invoker 视图组合时，策略会影响发版后的数据访问行为。
        Args:
            schema: schema 名称
            table:  表名
        """
        rows = _query(dsn, """
            SELECT
                pol.polname         AS policy_name,
                CASE pol.polcmd
                    WHEN 'r' THEN 'SELECT'
                    WHEN 'a' THEN 'INSERT'
                    WHEN 'w' THEN 'UPDATE'
                    WHEN 'd' THEN 'DELETE'
                    ELSE 'ALL'
                END                 AS command,
                pol.polpermissive   AS is_permissive,
                pg_catalog.pg_get_expr(pol.polqual,    pol.polrelid) AS using_expr,
                pg_catalog.pg_get_expr(pol.polwithcheck, pol.polrelid) AS with_check_expr
            FROM pg_catalog.pg_policy  pol
            JOIN pg_catalog.pg_class   c   ON c.oid  = pol.polrelid
            JOIN pg_catalog.pg_namespace n ON n.oid  = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
            ORDER BY pol.polname
        """, (schema, table))
        return _fmt(rows) if rows else json.dumps(
            {"message": f"{schema}.{table} 未配置 RLS 策略"}, ensure_ascii=False
        )

    @tool
    def get_triggers(schema: str, table: str) -> str:
        """
        查询表上定义的所有触发器。
        发版后写操作行为可能因触发器产生副作用，需提前评估。
        Args:
            schema: schema 名称
            table:  表名
        """
        rows = _query(dsn, """
            SELECT
                t.trigger_name,
                t.event_manipulation        AS event,
                t.action_timing             AS timing,
                t.action_orientation        AS orientation,
                t.action_statement          AS trigger_body
            FROM information_schema.triggers t
            WHERE t.trigger_schema = %s AND t.event_object_table = %s
            ORDER BY t.trigger_name
        """, (schema, table))
        return _fmt(rows) if rows else json.dumps(
            {"message": f"{schema}.{table} 未定义触发器"}, ensure_ascii=False
        )

    @tool
    def get_sequences(schema: str, table: str) -> str:
        """
        查询表中列所使用的 sequence，及该 sequence 是否还被其他表共用。
        DROP 表时如果 sequence 被共用，可能产生副作用。
        Args:
            schema: schema 名称
            table:  表名
        """
        seqs = _query(dsn, """
            SELECT
                a.attname           AS column_name,
                pg_catalog.pg_get_expr(ad.adbin, ad.adrelid) AS default_expr,
                seq_n.nspname       AS sequence_schema,
                seq_c.relname       AS sequence_name
            FROM pg_catalog.pg_attribute   a
            JOIN pg_catalog.pg_class       c    ON c.oid   = a.attrelid
            JOIN pg_catalog.pg_namespace   n    ON n.oid   = c.relnamespace
            JOIN pg_catalog.pg_attrdef     ad   ON ad.adrelid = a.attrelid
                                                AND ad.adnum  = a.attnum
            -- 从 default 表达式中找到 sequence 依赖
            JOIN pg_catalog.pg_depend      d    ON d.objid  = ad.oid
            JOIN pg_catalog.pg_class       seq_c ON seq_c.oid = d.refobjid
                                                AND seq_c.relkind = 'S'
            JOIN pg_catalog.pg_namespace   seq_n ON seq_n.oid = seq_c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
              AND a.attnum > 0 AND NOT a.attisdropped
        """, (schema, table))

        if not seqs:
            return json.dumps(
                {"message": f"{schema}.{table} 没有使用 sequence"}, ensure_ascii=False
            )

        # 检查每个 sequence 是否被其他表共用
        result = []
        for seq in seqs:
            shared = _query(dsn, """
                SELECT DISTINCT
                    n2.nspname  AS other_schema,
                    c2.relname  AS other_table,
                    a2.attname  AS other_column
                FROM pg_catalog.pg_depend   d2
                JOIN pg_catalog.pg_class    seq_c2 ON seq_c2.oid = d2.refobjid
                                                   AND seq_c2.relkind = 'S'
                JOIN pg_catalog.pg_namespace seq_n2 ON seq_n2.oid = seq_c2.relnamespace
                JOIN pg_catalog.pg_attrdef  ad2    ON ad2.oid = d2.objid
                JOIN pg_catalog.pg_attribute a2    ON a2.attrelid = ad2.adrelid
                                                   AND a2.attnum  = ad2.adnum
                JOIN pg_catalog.pg_class    c2     ON c2.oid = a2.attrelid
                JOIN pg_catalog.pg_namespace n2    ON n2.oid = c2.relnamespace
                WHERE seq_n2.nspname = %s AND seq_c2.relname = %s
                  AND NOT (n2.nspname = %s AND c2.relname = %s)
            """, (
                seq["sequence_schema"], seq["sequence_name"],
                schema, table,
            ))
            result.append({**seq, "shared_by": shared})

        return _fmt(result)

    @tool
    def get_indexes(schema: str, table: str) -> str:
        """
        查询表上的所有索引（类型、列、唯一性）。
        用于评估发版对查询性能的影响。
        Args:
            schema: schema 名称
            table:  表名
        """
        rows = _query(dsn, """
            SELECT
                i.relname                       AS index_name,
                am.amname                       AS index_type,
                ix.indisunique                  AS is_unique,
                ix.indisprimary                 AS is_primary,
                pg_catalog.pg_get_indexdef(i.oid) AS index_def
            FROM pg_catalog.pg_index      ix
            JOIN pg_catalog.pg_class      i   ON i.oid   = ix.indexrelid
            JOIN pg_catalog.pg_class      t   ON t.oid   = ix.indrelid
            JOIN pg_catalog.pg_namespace  n   ON n.oid   = t.relnamespace
            JOIN pg_catalog.pg_am         am  ON am.oid  = i.relam
            WHERE n.nspname = %s AND t.relname = %s
            ORDER BY i.relname
        """, (schema, table))
        return _fmt(rows) if rows else json.dumps(
            {"message": f"{schema}.{table} 没有索引"}, ensure_ascii=False
        )

    # ── 第五组：兜底查询 ─────────────────────────────────────────────────────

    @tool
    def query_pg_catalog(
        table_name: str,
        where_clause: str,
        columns: str = "*",
        limit: int = 100,
    ) -> str:
        """
        兜底工具：在 pg_* 系统表或 information_schema.* 上执行受限只读查询。
        用于上面命名工具无法覆盖的场景。

        限制：
          - table_name 必须是 pg_* 或 information_schema.* 表
          - where_clause 不能为空，防止全表扫描
          - 结果最多返回 100 行

        ⚠️ 重要：where_clause 必须是静态字符串，直接把值写进去，
        例如 "nspname = 'ods' AND relname = 'my_table'"。
        禁止使用任何占位符（%s、%v、? 等），否则会报错。

        Args:
            table_name:   系统表全名，如 'pg_class'、'information_schema.columns'
            where_clause: WHERE 条件（不含 WHERE 关键字），值直接写入，如 "nspname = 'ods'"
            columns:      SELECT 的列名，默认 '*'
            limit:        最大返回行数，上限 100
        """
        if not where_clause or not where_clause.strip():
            return "[BLOCKED] where_clause 不能为空，防止对系统表进行全量扫描"

        # 校验 table_name 是系统表
        tbl = table_name.strip().lower()
        base = tbl.split(".")[-1] if "." in tbl else tbl
        schema_part = tbl.split(".")[0] if "." in tbl else ""
        if schema_part == "information_schema":
            pass  # OK
        elif not base.startswith("pg_"):
            return (
                f"[BLOCKED] '{table_name}' 不是系统表（pg_* / information_schema.*），已拒绝。"
            )

        # 行数上限
        safe_limit = min(int(limit), _MAX_ROWS)

        sql = (
            f"SELECT {columns} FROM {table_name} "  # noqa: S608
            f"WHERE {where_clause} LIMIT {safe_limit}"
        )

        # 占位符检测：where_clause 必须是静态值，不允许 %x 格式
        if re.search(r"%[^%]", where_clause):
            return (
                "[BLOCKED] where_clause 包含占位符（如 %s、%v），"
                "请直接把值写入字符串，例如 \"nspname = 'ods'\"，不要使用参数占位符。"
            )

        # 再过一遍写操作检查
        reason = _validate_catalog_query(sql)
        if reason:
            return f"[BLOCKED] {reason}"

        try:
            rows = _query(dsn, sql)
            return _fmt(rows)
        except Exception as exc:  # noqa: BLE001
            return f"[ERROR] 查询失败: {exc}"

    return [
        get_all_schemas,
        list_objects_in_schema,
        get_table_structure,
        get_view_definition,
        get_foreign_table_info,
        get_downstream_dependents,
        get_upstream_dependencies,
        get_objects_using_server,
        get_rls_policies,
        get_triggers,
        get_sequences,
        get_indexes,
        query_pg_catalog,
    ]
