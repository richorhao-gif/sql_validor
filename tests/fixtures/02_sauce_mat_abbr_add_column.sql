-- =====================================================================
-- 02_sauce_mat_abbr_add_column.sql
-- 资产名称：调味物料简称
-- 资产技术名：sauce_mat_abbr
-- 数据域：供应链域
--
-- 变更内容：
--   新增 mat_abbr_short（物料短简称）字段，用于移动端窄屏展示
--   DS 层重建 FOREIGN TABLE；ODS/DWD/DA 层 ALTER TABLE 追加列（避免全量重建）
--
-- 注意事项：
--   1. da.v_da_sauce_material_full 引用 da.da_td_scd_sauce_mat_abbr
--      ALTER TABLE 不会破坏此视图，但重建视图时需包含新字段
--   2. da_selfhp.v_sauce_material_带简称 引用简称数据
--      需同步重建以暴露 mat_abbr_short 字段
--   3. oss_serv 同时服务于 sauce_mat_brd_prdct_atribt
--      本脚本修改 sauce_mat_abbr 的 OSS OPTIONS 时不影响品种表
-- =====================================================================

-- ── 预清理下游视图（ODS 视图引用简称表，重建前需先 DROP）──────────────
DROP VIEW IF EXISTS da_selfhp.v_sauce_material_带简称;
DROP VIEW IF EXISTS da.v_da_sauce_material_full;
DROP VIEW IF EXISTS ods.v_ods_mannual_sauce_mat_abbr;

-- ── DS 层：重建 FOREIGN TABLE（新增 mat_abbr_short）───────────────────
DROP FOREIGN TABLE IF EXISTS ds_mannual.sauce_mat_abbr;

CREATE FOREIGN TABLE ds_mannual.sauce_mat_abbr (
    plant_code     varchar,
    mat_code       varchar,
    mat_abbr       varchar,
    mat_abbr_short varchar,
    zdelta_time    timestamp
)
SERVER oss_serv
OPTIONS (
    prefix    '/offline_data/M0008_川渝经营驾驶舱/调味物料简称导入/',
    format    'csv',
    header    'true',
    delimiter ','
);
COMMENT ON FOREIGN TABLE ds_mannual.sauce_mat_abbr IS '调味物料简称';
COMMENT ON COLUMN ds_mannual.sauce_mat_abbr.mat_abbr       IS '物料完整简称';
COMMENT ON COLUMN ds_mannual.sauce_mat_abbr.mat_abbr_short IS '物料短简称（移动端展示，≤4字）';

-- ── ODS 层：ALTER 追加列（保留历史数据）──────────────────────────────
ALTER TABLE ods.ods_mannual_sauce_mat_abbr
    ADD COLUMN IF NOT EXISTS mat_abbr_short varchar;
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_abbr.mat_abbr_short IS '物料短简称';

CREATE OR REPLACE VIEW ods.v_ods_mannual_sauce_mat_abbr AS
SELECT plant_code, mat_code, mat_abbr, mat_abbr_short, zdelta_time, zis_physc_del
FROM ods.ods_mannual_sauce_mat_abbr;
COMMENT ON VIEW ods.v_ods_mannual_sauce_mat_abbr IS '调味物料简称-ODS视图（含短简称）';

-- ── DWD 层：ALTER 追加列 ────────────────────────────────────────────
ALTER TABLE dwd.dwd_scd_sauce_mat_abbr
    ADD COLUMN IF NOT EXISTS mat_abbr_short varchar;

CREATE OR REPLACE VIEW dwd.v_dwd_scd_sauce_mat_abbr AS
SELECT plant_code, mat_code, mat_abbr, mat_abbr_short, zdelta_time, zis_physc_del
FROM dwd.dwd_scd_sauce_mat_abbr;
COMMENT ON VIEW dwd.v_dwd_scd_sauce_mat_abbr IS '调味物料简称-DWD视图（含短简称）';

-- ── DA 层：ALTER 追加列 ─────────────────────────────────────────────
ALTER TABLE da.da_td_scd_sauce_mat_abbr
    ADD COLUMN IF NOT EXISTS mat_abbr_short varchar;

-- 重建宽视图（含新字段 mat_abbr_short）
CREATE OR REPLACE VIEW da.v_da_sauce_material_full AS
SELECT
    brd.plant_code,
    brd.plant_descrptn,
    brd.mat_code,
    brd.mat_name,
    abbr.mat_abbr,
    abbr.mat_abbr_short,
    brd.is_rawmat,
    brd.sauce_brd,
    brd.prdct_atribt,
    brd.zdelta_time
FROM da.da_td_scd_sauce_mat_brd_prdct_atribt brd
LEFT JOIN da.da_td_scd_sauce_mat_abbr abbr
       ON brd.plant_code = abbr.plant_code
      AND brd.mat_code   = abbr.mat_code
WHERE brd.zis_physc_del = 0;
COMMENT ON VIEW da.v_da_sauce_material_full
    IS '调味物料完整宽视图（品种+简称+短简称）';

-- ── BI 自助层：重建含新字段的视图 ────────────────────────────────────
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
    abbr.mat_abbr       AS "物料简称",
    abbr.mat_abbr_short AS "物料短简称",
    "更新时间戳"
FROM da_selfhp.da_td_scd_sauce_mat_brd_prdct_atribt_调味物料品种与产品属性 base
LEFT JOIN da.da_td_scd_sauce_mat_abbr abbr
       ON base."工厂代码" = abbr.plant_code
      AND base."物料编码" = abbr.mat_code;
COMMENT ON VIEW da_selfhp.v_sauce_material_带简称
    IS 'BI全量物料视图（含短简称，security_invoker）';
