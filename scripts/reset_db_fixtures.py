#!/usr/bin/env python3
"""
scripts/reset_db_fixtures.py
将 docker/init.sql 替换为调味品供应链多 Schema 复杂测试场景。
运行后需要重启 Docker volume 使其生效：
    docker compose --project-name sql-validator down -v
    docker compose --project-name sql-validator up -d
"""
from pathlib import Path

ROOT = Path(__file__).parent.parent

INIT_SQL = r"""-- =====================================================================
-- sql_validator — 调味品供应链数仓 Mock 初始化脚本
-- 模拟生产环境 DS→ODS→DWD→DA→BI 五层架构的当前状态
--
-- 本次测试场景说明：
--   Fixture 01: 物料品种与产品属性资产全链路重建（新增 is_rawmat/prdct_atribt 列）
--   Fixture 02: 物料简称资产新增 mat_abbr_short 列
--   Fixture 03: 全新创建调味品品种资产（sauce_mat_variety）
--
-- 当前快照特征（供 Agent 探查）：
--   - 5 个 schema，2 张 FOREIGN TABLE（共用同一 oss_serv）
--   - ODS 层有审计触发器
--   - DA 层有 RLS 策略
--   - DA 层有跨表宽视图（JOIN 品种+简称，形成级联依赖）
--   - da_selfhp 层有 security_invoker 视图
-- =====================================================================

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

\echo '>>> [1/6] 创建 Schema...'

CREATE SCHEMA IF NOT EXISTS ds_mannual;
COMMENT ON SCHEMA ds_mannual IS 'DS层：OSS 外部数据源（FOREIGN TABLE）';

CREATE SCHEMA IF NOT EXISTS ods;
COMMENT ON SCHEMA ods IS 'ODS层：贴源落库层（原始数据写入）';

CREATE SCHEMA IF NOT EXISTS dwd;
COMMENT ON SCHEMA dwd IS 'DWD层：明细数据层（SCD 增量处理）';

CREATE SCHEMA IF NOT EXISTS da;
COMMENT ON SCHEMA da IS 'DA层：数据应用层（分析宽表）';

CREATE SCHEMA IF NOT EXISTS da_selfhp;
COMMENT ON SCHEMA da_selfhp IS 'BI自助层：中文列名查询视图（security_invoker）';

\echo '>>> [2/6] 创建 OSS FDW 和 SERVER...'

-- 创建无 handler 的 stub FDW，仅用于元数据注册（无法 SELECT，但工具可查 pg_catalog）
CREATE FOREIGN DATA WRAPPER oss_fdw;
COMMENT ON FOREIGN DATA WRAPPER oss_fdw IS 'OSS 离线数据导入 FDW（阿里云 OSS）';

CREATE SERVER oss_serv
    FOREIGN DATA WRAPPER oss_fdw
    OPTIONS (
        endpoint 'oss-cn-shanghai-internal.aliyuncs.com',
        bucket   'sc-dw-offline-cn-sh'
    );
COMMENT ON SERVER oss_serv IS 'OSS 离线数据导入服务（内网端点，多个外部表共用此 Server）';

\echo '>>> [3/6] 创建 DS层 FOREIGN TABLE（旧版结构，本次发版将变更）...'

-- 物料品种与产品属性外部表（旧版：缺少 is_rawmat / prdct_atribt 两列）
-- Fixture 01 将 DROP + 重建此表，新增这两列
CREATE FOREIGN TABLE ds_mannual.sauce_mat_brd_prdct_atribt (
    plant_code     varchar,
    plant_descrptn varchar,
    mat_code       varchar,
    mat_name       varchar,
    sauce_brd      varchar,
    zdelta_time    timestamp
)
SERVER oss_serv
OPTIONS (
    prefix    '/offline_data/M0008_川渝经营驾驶舱/调味物料品种与产品属性导入/',
    format    'csv',
    header    'true',
    delimiter ','
);
COMMENT ON FOREIGN TABLE ds_mannual.sauce_mat_brd_prdct_atribt
    IS '调味物料品种与产品属性（旧版，缺 is_rawmat 与 prdct_atribt 列）';

-- 物料简称外部表（第二张挂载在同一 oss_serv 上的 FOREIGN TABLE）
-- 探查 get_objects_using_server('oss_serv') 时应返回此表
-- Fixture 02 将新增 mat_abbr_short 列
CREATE FOREIGN TABLE ds_mannual.sauce_mat_abbr (
    plant_code  varchar,
    mat_code    varchar,
    mat_abbr    varchar,
    zdelta_time timestamp
)
SERVER oss_serv
OPTIONS (
    prefix    '/offline_data/M0008_川渝经营驾驶舱/调味物料简称导入/',
    format    'csv',
    header    'true',
    delimiter ','
);
COMMENT ON FOREIGN TABLE ds_mannual.sauce_mat_abbr
    IS '调味物料简称（与品种表共用 oss_serv，Fixture 02 将新增 mat_abbr_short 列）';

\echo '>>> [4/6] 创建 ODS/DWD/DA 层表和视图...'

-- ════════════════ ODS 层 ════════════════

-- 物料品种 ODS 表（旧版：缺 is_rawmat / prdct_atribt）
CREATE TABLE ods.ods_mannual_sauce_mat_brd_prdct_atribt (
    plant_code       varchar,
    plant_descrptn   varchar,
    mat_code         varchar,
    mat_name         varchar,
    sauce_brd        varchar,
    zdelta_time      timestamp,
    zis_physc_del    int4 DEFAULT 0,
    CONSTRAINT pk_ods_mannual_sauce_mat_brd_prdct_atribt PRIMARY KEY (plant_code, mat_code)
);
COMMENT ON TABLE  ods.ods_mannual_sauce_mat_brd_prdct_atribt
    IS '调味物料品种与产品属性-ODS（旧版，缺 is_rawmat/prdct_atribt）';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.zis_physc_del
    IS '物理删除标识(0=未删除,1=已删除)';

CREATE INDEX idx_ods_sauce_mat_brd_zdelta
    ON ods.ods_mannual_sauce_mat_brd_prdct_atribt (zdelta_time);
CREATE INDEX idx_ods_sauce_mat_brd_del
    ON ods.ods_mannual_sauce_mat_brd_prdct_atribt (zis_physc_del);

-- 审计日志表（触发器写入目标）
CREATE TABLE ods.ods_physc_del_audit (
    id         bigserial PRIMARY KEY,
    tbl        varchar   NOT NULL,
    plant_code varchar,
    mat_code   varchar,
    del_at     timestamp DEFAULT now(),
    del_by     varchar   DEFAULT current_user
);
COMMENT ON TABLE ods.ods_physc_del_audit IS 'ODS 物理删除操作审计日志';

-- 触发器函数
CREATE OR REPLACE FUNCTION ods.fn_record_physc_del()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.zis_physc_del = 1 AND (OLD.zis_physc_del IS DISTINCT FROM 1) THEN
        INSERT INTO ods.ods_physc_del_audit (tbl, plant_code, mat_code)
        VALUES (TG_TABLE_NAME, NEW.plant_code, NEW.mat_code);
    END IF;
    RETURN NEW;
END;
$$;
COMMENT ON FUNCTION ods.fn_record_physc_del()
    IS '物理删除审计触发器函数（zis_physc_del 从 0 变为 1 时写入审计日志）';

-- 挂载触发器（测试 get_triggers 工具：DROP TABLE 前需关注此触发器）
CREATE TRIGGER trg_record_physc_del_sauce_mat_brd
    AFTER UPDATE ON ods.ods_mannual_sauce_mat_brd_prdct_atribt
    FOR EACH ROW EXECUTE FUNCTION ods.fn_record_physc_del();

-- ODS 物料品种视图
CREATE OR REPLACE VIEW ods.v_ods_mannual_sauce_mat_brd_prdct_atribt AS
SELECT plant_code, plant_descrptn, mat_code, mat_name,
       sauce_brd, zdelta_time, zis_physc_del
FROM ods.ods_mannual_sauce_mat_brd_prdct_atribt;
COMMENT ON VIEW ods.v_ods_mannual_sauce_mat_brd_prdct_atribt
    IS '调味物料品种与产品属性-ODS视图（旧版）';

-- 物料简称 ODS 表（旧版：无 mat_abbr_short）
CREATE TABLE ods.ods_mannual_sauce_mat_abbr (
    plant_code    varchar,
    mat_code      varchar,
    mat_abbr      varchar,
    zdelta_time   timestamp,
    zis_physc_del int4 DEFAULT 0,
    CONSTRAINT pk_ods_mannual_sauce_mat_abbr PRIMARY KEY (plant_code, mat_code)
);
COMMENT ON TABLE ods.ods_mannual_sauce_mat_abbr IS '调味物料简称-ODS（旧版，无 mat_abbr_short）';

CREATE OR REPLACE VIEW ods.v_ods_mannual_sauce_mat_abbr AS
SELECT plant_code, mat_code, mat_abbr, zdelta_time, zis_physc_del
FROM ods.ods_mannual_sauce_mat_abbr;
COMMENT ON VIEW ods.v_ods_mannual_sauce_mat_abbr IS '调味物料简称-ODS视图';

-- ════════════════ DWD 层 ════════════════

CREATE TABLE dwd.dwd_scd_sauce_mat_brd_prdct_atribt (
    plant_code       varchar,
    plant_descrptn   varchar,
    mat_code         varchar,
    mat_name         varchar,
    sauce_brd        varchar,
    zdelta_time      timestamp,
    zis_physc_del    int4 DEFAULT 0,
    CONSTRAINT pk_dwd_scd_sauce_mat_brd_prdct_atribt PRIMARY KEY (plant_code, mat_code)
);
COMMENT ON TABLE dwd.dwd_scd_sauce_mat_brd_prdct_atribt
    IS '调味物料品种与产品属性-DWD（旧版）';

CREATE OR REPLACE VIEW dwd.v_dwd_scd_sauce_mat_brd_prdct_atribt AS
SELECT plant_code, plant_descrptn, mat_code, mat_name,
       sauce_brd, zdelta_time, zis_physc_del
FROM dwd.dwd_scd_sauce_mat_brd_prdct_atribt;
COMMENT ON VIEW dwd.v_dwd_scd_sauce_mat_brd_prdct_atribt
    IS '调味物料品种与产品属性-DWD视图（旧版）';

CREATE TABLE dwd.dwd_scd_sauce_mat_abbr (
    plant_code    varchar,
    mat_code      varchar,
    mat_abbr      varchar,
    zdelta_time   timestamp,
    zis_physc_del int4 DEFAULT 0,
    CONSTRAINT pk_dwd_scd_sauce_mat_abbr PRIMARY KEY (plant_code, mat_code)
);
COMMENT ON TABLE dwd.dwd_scd_sauce_mat_abbr IS '调味物料简称-DWD';

CREATE OR REPLACE VIEW dwd.v_dwd_scd_sauce_mat_abbr AS
SELECT plant_code, mat_code, mat_abbr, zdelta_time, zis_physc_del
FROM dwd.dwd_scd_sauce_mat_abbr;
COMMENT ON VIEW dwd.v_dwd_scd_sauce_mat_abbr IS '调味物料简称-DWD视图';

-- ════════════════ DA 层 ════════════════

CREATE TABLE da.da_td_scd_sauce_mat_brd_prdct_atribt (
    plant_code       varchar,
    plant_descrptn   varchar,
    mat_code         varchar,
    mat_name         varchar,
    sauce_brd        varchar,
    zdelta_time      timestamp,
    zis_physc_del    int4 DEFAULT 0,
    CONSTRAINT pk_da_td_scd_sauce_mat_brd_prdct_atribt PRIMARY KEY (plant_code, mat_code)
);
COMMENT ON TABLE da.da_td_scd_sauce_mat_brd_prdct_atribt
    IS '调味物料品种与产品属性-DA（旧版，缺 is_rawmat/prdct_atribt）';

-- RLS 策略：DA 层只可见未删除记录（测试 get_rls_policies 工具）
ALTER TABLE da.da_td_scd_sauce_mat_brd_prdct_atribt ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_no_deleted
    ON da.da_td_scd_sauce_mat_brd_prdct_atribt
    FOR SELECT
    USING (zis_physc_del = 0);

CREATE OR REPLACE VIEW da.v_da_td_scd_sauce_mat_brd_prdct_atribt AS
SELECT plant_code, plant_descrptn, mat_code, mat_name,
       sauce_brd, zdelta_time, zis_physc_del
FROM da.da_td_scd_sauce_mat_brd_prdct_atribt;
COMMENT ON VIEW da.v_da_td_scd_sauce_mat_brd_prdct_atribt
    IS '调味物料品种与产品属性-DA视图（旧版）';

CREATE TABLE da.da_td_scd_sauce_mat_abbr (
    plant_code    varchar,
    mat_code      varchar,
    mat_abbr      varchar,
    zdelta_time   timestamp,
    zis_physc_del int4 DEFAULT 0,
    CONSTRAINT pk_da_td_scd_sauce_mat_abbr PRIMARY KEY (plant_code, mat_code)
);
COMMENT ON TABLE da.da_td_scd_sauce_mat_abbr IS '调味物料简称-DA';

-- 跨表宽视图（JOIN 品种+简称，是级联依赖测试的关键对象）
-- DROP da.da_td_scd_sauce_mat_brd_prdct_atribt 或 da.da_td_scd_sauce_mat_abbr
-- 都会导致此视图失效
CREATE OR REPLACE VIEW da.v_da_sauce_material_full AS
SELECT
    brd.plant_code,
    brd.plant_descrptn,
    brd.mat_code,
    brd.mat_name,
    abbr.mat_abbr,
    brd.sauce_brd,
    brd.zdelta_time
FROM da.da_td_scd_sauce_mat_brd_prdct_atribt brd
LEFT JOIN da.da_td_scd_sauce_mat_abbr abbr
       ON brd.plant_code = abbr.plant_code
      AND brd.mat_code   = abbr.mat_code
WHERE brd.zis_physc_del = 0;
COMMENT ON VIEW da.v_da_sauce_material_full
    IS '调味物料完整宽视图（品种+简称，BI层直接引用，DROP品种/简称表均产生级联）';

\echo '>>> [5/6] 创建 BI自助层视图（security_invoker，中文列名）...'

-- 物料品种中文查询视图
CREATE OR REPLACE VIEW da_selfhp.da_td_scd_sauce_mat_brd_prdct_atribt_调味物料品种与产品属性
    WITH (security_invoker=true) AS
SELECT
    plant_code     AS "工厂代码",
    plant_descrptn AS "工厂描述",
    mat_code       AS "物料编码",
    mat_name       AS "物料名称",
    sauce_brd      AS "调味品种",
    zdelta_time    AS "更新时间戳",
    zis_physc_del  AS "物理删除标识"
FROM da.da_td_scd_sauce_mat_brd_prdct_atribt
WHERE zis_physc_del = 0;
COMMENT ON VIEW da_selfhp.da_td_scd_sauce_mat_brd_prdct_atribt_调味物料品种与产品属性
    IS '调味物料品种与产品属性-BI中文查询视图（security_invoker，旧版无产品属性列）';

-- 全量物料信息视图（引用宽视图，级联依赖链最深处）
CREATE OR REPLACE VIEW da_selfhp.v_sauce_material_带简称
    WITH (security_invoker=true) AS
SELECT
    "工厂代码",
    "工厂描述",
    "物料编码",
    "物料名称",
    "调味品种",
    abbr.mat_abbr AS "物料简称",
    "更新时间戳"
FROM da_selfhp.da_td_scd_sauce_mat_brd_prdct_atribt_调味物料品种与产品属性 base
LEFT JOIN da.da_td_scd_sauce_mat_abbr abbr
       ON base."工厂代码" = abbr.plant_code
      AND base."物料编码" = abbr.mat_code;
COMMENT ON VIEW da_selfhp.v_sauce_material_带简称
    IS 'BI全量物料视图（含简称，引用 security_invoker 视图，存在多层级联依赖）';

\echo '>>> [6/6] 验证摘要...'

DO $$
DECLARE
    v_schemas  int;
    v_tables   int;
    v_views    int;
    v_ftables  int;
    v_triggers int;
    v_policies int;
BEGIN
    SELECT COUNT(*) INTO v_schemas  FROM pg_namespace
        WHERE nspname IN ('ds_mannual','ods','dwd','da','da_selfhp');
    SELECT COUNT(*) INTO v_tables   FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('ods','dwd','da') AND c.relkind = 'r';
    SELECT COUNT(*) INTO v_views    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('ods','dwd','da','da_selfhp') AND c.relkind = 'v';
    SELECT COUNT(*) INTO v_ftables  FROM pg_foreign_table ft
        JOIN pg_class c ON c.oid = ft.ftrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'ds_mannual';
    SELECT COUNT(*) INTO v_triggers FROM pg_trigger WHERE NOT tgisinternal;
    SELECT COUNT(*) INTO v_policies FROM pg_policy;

    RAISE NOTICE '========================================';
    RAISE NOTICE '调味品供应链数仓 Mock 初始化完成！';
    RAISE NOTICE '  Schemas       : %', v_schemas;
    RAISE NOTICE '  Tables        : %', v_tables;
    RAISE NOTICE '  Views         : %', v_views;
    RAISE NOTICE '  Foreign Tables: %', v_ftables;
    RAISE NOTICE '  Triggers      : %', v_triggers;
    RAISE NOTICE '  RLS Policies  : %', v_policies;
    RAISE NOTICE '========================================';
    RAISE NOTICE '关键测试点：';
    RAISE NOTICE '  1. oss_serv 下挂 2 张 FOREIGN TABLE，Fixture01/02 均影响';
    RAISE NOTICE '  2. ODS 层有触发器，DROP TABLE 前需关注';
    RAISE NOTICE '  3. DA 层有 RLS 策略，security_invoker 视图行为需评估';
    RAISE NOTICE '  4. da.v_da_sauce_material_full 依赖两张表，级联风险高';
    RAISE NOTICE '  5. da_selfhp 层两个视图存在多层级联依赖';
    RAISE NOTICE '========================================';
END;
$$;
"""

(ROOT / "docker" / "init.sql").write_text(INIT_SQL.lstrip(), encoding="utf-8")
print(f"✔ docker/init.sql 已更新（{len(INIT_SQL.splitlines())} 行）")
