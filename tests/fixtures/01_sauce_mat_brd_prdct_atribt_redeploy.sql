-- =====================================================================
-- 01_sauce_mat_brd_prdct_atribt_redeploy.sql
-- 资产名称：调味物料品种与产品属性
-- 资产技术名：sauce_mat_brd_prdct_atribt
-- 数据域：供应链域 | 资产类型：业务资产
-- 主键：plant_code, mat_code
--
-- 变更内容：
--   新增 is_rawmat（是否原料）、prdct_atribt（产品属性）两列
--   全链路 DS→ODS→DWD→DA→BI 全部 DROP+CREATE 重建
--
-- 影响面分析（发版前需确认）：
--   1. da.v_da_sauce_material_full 引用 da.da_td_scd_sauce_mat_brd_prdct_atribt
--      → DROP 该 DA 表会破坏此宽视图
--   2. da_selfhp 层两个视图直接/间接引用 DA 层表
--      → 需先 DROP 下游视图再 DROP 上游表
--   3. ODS 表上有触发器 trg_record_physc_del_sauce_mat_brd
--      → DROP TABLE 会自动删除触发器，但审计日志表保留
-- =====================================================================

-- ── 预清理：自顶向下 DROP 下游视图（防止级联错误）───────────────────────
DROP VIEW IF EXISTS da_selfhp.v_sauce_material_带简称;
DROP VIEW IF EXISTS da_selfhp.da_td_scd_sauce_mat_brd_prdct_atribt_调味物料品种与产品属性;
DROP VIEW IF EXISTS da.v_da_sauce_material_full;
DROP VIEW IF EXISTS da.v_da_td_scd_sauce_mat_brd_prdct_atribt;
DROP VIEW IF EXISTS dwd.v_dwd_scd_sauce_mat_brd_prdct_atribt;
DROP VIEW IF EXISTS ods.v_ods_mannual_sauce_mat_brd_prdct_atribt;

-- ── DS 层：重建 FOREIGN TABLE（新增 is_rawmat / prdct_atribt）──────────
DROP FOREIGN TABLE IF EXISTS ds_mannual.sauce_mat_brd_prdct_atribt;

CREATE FOREIGN TABLE ds_mannual.sauce_mat_brd_prdct_atribt (
    plant_code     varchar,
    plant_descrptn varchar,
    mat_code       varchar,
    mat_name       varchar,
    is_rawmat      varchar,
    sauce_brd      varchar,
    prdct_atribt   varchar,
    zdelta_time    timestamp
)
SERVER oss_serv
OPTIONS (
    prefix    '/offline_data/M0008_川渝经营驾驶舱/调味物料品种与产品属性导入/',
    format    'csv',
    header    'true',
    delimiter ','
);

COMMENT ON FOREIGN TABLE ds_mannual.sauce_mat_brd_prdct_atribt IS '调味物料品种与产品属性';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.plant_code     IS '工厂代码';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.plant_descrptn IS '工厂描述';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.mat_code       IS '物料编码';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.mat_name       IS '物料名称';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.is_rawmat      IS '是否原料';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.sauce_brd      IS '调味品种';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.prdct_atribt   IS '产品属性';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.zdelta_time    IS '更新时间戳';

-- ── ODS 层：DROP TABLE + 重建（含新字段）──────────────────────────────
DROP TABLE IF EXISTS ods.ods_mannual_sauce_mat_brd_prdct_atribt;

CREATE TABLE ods.ods_mannual_sauce_mat_brd_prdct_atribt (
    plant_code       varchar,
    plant_descrptn   varchar,
    mat_code         varchar,
    mat_name         varchar,
    is_rawmat        varchar,
    sauce_brd        varchar,
    prdct_atribt     varchar,
    zdelta_time      timestamp,
    zis_physc_del    int4 DEFAULT 0,
    CONSTRAINT pk_ods_mannual_sauce_mat_brd_prdct_atribt PRIMARY KEY (plant_code, mat_code)
) USING beam;

COMMENT ON TABLE  ods.ods_mannual_sauce_mat_brd_prdct_atribt IS '调味物料品种与产品属性';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.is_rawmat    IS '是否原料';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.prdct_atribt IS '产品属性';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.zis_physc_del IS '物理删除标识(0=未删除,1=已删除)';

CREATE OR REPLACE VIEW ods.v_ods_mannual_sauce_mat_brd_prdct_atribt AS
SELECT
    plant_code, plant_descrptn, mat_code, mat_name,
    is_rawmat, sauce_brd, prdct_atribt, zdelta_time, zis_physc_del
FROM ods.ods_mannual_sauce_mat_brd_prdct_atribt;
COMMENT ON VIEW ods.v_ods_mannual_sauce_mat_brd_prdct_atribt IS '调味物料品种与产品属性-ODS视图';

-- ── DWD 层：DROP TABLE + 重建 ────────────────────────────────────────
DROP TABLE IF EXISTS dwd.dwd_scd_sauce_mat_brd_prdct_atribt;

CREATE TABLE dwd.dwd_scd_sauce_mat_brd_prdct_atribt (
    plant_code       varchar,
    plant_descrptn   varchar,
    mat_code         varchar,
    mat_name         varchar,
    is_rawmat        varchar,
    sauce_brd        varchar,
    prdct_atribt     varchar,
    zdelta_time      timestamp,
    zis_physc_del    int4 DEFAULT 0,
    CONSTRAINT pk_dwd_scd_sauce_mat_brd_prdct_atribt PRIMARY KEY (plant_code, mat_code)
) USING beam;
COMMENT ON TABLE dwd.dwd_scd_sauce_mat_brd_prdct_atribt IS '调味物料品种与产品属性-DWD';

CREATE OR REPLACE VIEW dwd.v_dwd_scd_sauce_mat_brd_prdct_atribt AS
WITH delta_records AS (
    SELECT a.plant_code, a.mat_code, count(1) AS cnt
    FROM (
        SELECT delta.plant_code, delta.mat_code
        FROM ods.ods_mannual_sauce_mat_brd_prdct_atribt delta
        WHERE true
    ) a
    GROUP BY a.plant_code, a.mat_code
)
SELECT
    ods.plant_code, ods.plant_descrptn, ods.mat_code, ods.mat_name,
    ods.is_rawmat, ods.sauce_brd, ods.prdct_atribt,
    ods.zdelta_time, ods.zis_physc_del
FROM ods.ods_mannual_sauce_mat_brd_prdct_atribt ods
WHERE 'TRUE'::text = 'TRUE'::text
   OR EXISTS (
        SELECT 1 FROM delta_records dr
        WHERE dr.plant_code = ods.plant_code AND dr.mat_code = ods.mat_code
   );
COMMENT ON VIEW dwd.v_dwd_scd_sauce_mat_brd_prdct_atribt
    IS '调味物料品种与产品属性-DWD视图（含反向增量CTE）';

-- ── DA 层：DROP TABLE + 重建 ─────────────────────────────────────────
DROP TABLE IF EXISTS da.da_td_scd_sauce_mat_brd_prdct_atribt;

CREATE TABLE da.da_td_scd_sauce_mat_brd_prdct_atribt (
    plant_code       varchar,
    plant_descrptn   varchar,
    mat_code         varchar,
    mat_name         varchar,
    is_rawmat        varchar,
    sauce_brd        varchar,
    prdct_atribt     varchar,
    zdelta_time      timestamp,
    zis_physc_del    int4 DEFAULT 0,
    CONSTRAINT pk_da_td_scd_sauce_mat_brd_prdct_atribt PRIMARY KEY (plant_code, mat_code)
) USING beam;
COMMENT ON TABLE da.da_td_scd_sauce_mat_brd_prdct_atribt IS '调味物料品种与产品属性-DA';

CREATE OR REPLACE VIEW da.v_da_td_scd_sauce_mat_brd_prdct_atribt AS
WITH delta_records AS (
    SELECT a.plant_code, a.mat_code, count(1) AS cnt
    FROM (
        SELECT delta.plant_code, delta.mat_code
        FROM dwd.dwd_scd_sauce_mat_brd_prdct_atribt delta
        WHERE true
    ) a
    GROUP BY a.plant_code, a.mat_code
)
SELECT
    dwd.plant_code, dwd.plant_descrptn, dwd.mat_code, dwd.mat_name,
    dwd.is_rawmat, dwd.sauce_brd, dwd.prdct_atribt,
    dwd.zdelta_time, dwd.zis_physc_del
FROM dwd.dwd_scd_sauce_mat_brd_prdct_atribt dwd
WHERE 'TRUE'::text = 'TRUE'::text
   OR EXISTS (
        SELECT 1 FROM delta_records dr
        WHERE dr.plant_code = dwd.plant_code AND dr.mat_code = dwd.mat_code
   );
COMMENT ON VIEW da.v_da_td_scd_sauce_mat_brd_prdct_atribt
    IS '调味物料品种与产品属性-DA视图（含反向增量CTE）';

-- 重建宽视图（含新字段）
CREATE OR REPLACE VIEW da.v_da_sauce_material_full AS
SELECT
    brd.plant_code,
    brd.plant_descrptn,
    brd.mat_code,
    brd.mat_name,
    abbr.mat_abbr,
    brd.is_rawmat,
    brd.sauce_brd,
    brd.prdct_atribt,
    brd.zdelta_time
FROM da.da_td_scd_sauce_mat_brd_prdct_atribt brd
LEFT JOIN da.da_td_scd_sauce_mat_abbr abbr
       ON brd.plant_code = abbr.plant_code
      AND brd.mat_code   = abbr.mat_code
WHERE brd.zis_physc_del = 0;
COMMENT ON VIEW da.v_da_sauce_material_full IS '调味物料完整宽视图（品种+简称，含产品属性）';

-- ── DA 自助层 ────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW da_selfhp.da_td_scd_sauce_mat_brd_prdct_atribt_调味物料品种与产品属性
    WITH (security_invoker=true) AS
SELECT
    plant_code     AS "工厂代码",
    plant_descrptn AS "工厂描述",
    mat_code       AS "物料编码",
    mat_name       AS "物料名称",
    is_rawmat      AS "是否原料",
    sauce_brd      AS "调味品种",
    prdct_atribt   AS "产品属性",
    zdelta_time    AS "更新时间戳",
    zis_physc_del  AS "物理删除标识"
FROM da.da_td_scd_sauce_mat_brd_prdct_atribt
WHERE zis_physc_del = 0;
COMMENT ON VIEW da_selfhp.da_td_scd_sauce_mat_brd_prdct_atribt_调味物料品种与产品属性
    IS '调味物料品种与产品属性-BI中文查询视图（security_invoker）';

CREATE OR REPLACE VIEW da_selfhp.v_sauce_material_带简称
    WITH (security_invoker=true) AS
SELECT
    "工厂代码",
    "工厂描述",
    "物料编码",
    "物料名称",
    "是否原料",
    "调味品种",
    "产品属性",
    abbr.mat_abbr AS "物料简称",
    "更新时间戳"
FROM da_selfhp.da_td_scd_sauce_mat_brd_prdct_atribt_调味物料品种与产品属性 base
LEFT JOIN da.da_td_scd_sauce_mat_abbr abbr
       ON base."工厂代码" = abbr.plant_code
      AND base."物料编码" = abbr.mat_code;
COMMENT ON VIEW da_selfhp.v_sauce_material_带简称
    IS 'BI全量物料视图（含产品属性和简称，security_invoker）';
