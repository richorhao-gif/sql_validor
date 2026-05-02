


-- ========================================
-- 资产名称：调味物料品种与产品属性
-- 资产技术名：sauce_mat_brd_prdct_atribt
-- 数据域：供应链域
-- 资产类型：业务资产
-- 主键：plant_code, mat_code
-- ========================================

-- ========================================
-- DS层：OSS外部表（FOREIGN TABLE）
-- ========================================
DROP VIEW IF EXISTS ods.v_ods_mannual_sauce_mat_brd_prdct_atribt;
DROP FOREIGN TABLE IF EXISTS ds_mannual.sauce_mat_brd_prdct_atribt;

CREATE FOREIGN TABLE ds_mannual.sauce_mat_brd_prdct_atribt (
    plant_code varchar,
    plant_descrptn varchar,
    mat_code varchar,
    mat_name varchar,
    is_rawmat varchar,
    sauce_brd varchar,
    prdct_atribt varchar,
    zdelta_time timestamp
)
SERVER oss_serv
OPTIONS (
    prefix '/offline_data/M0008_川渝经营驾驶舱/调味物料品种与产品属性导入/',
    format 'csv',
    header 'true',
    delimiter ','
);

COMMENT ON FOREIGN TABLE ds_mannual.sauce_mat_brd_prdct_atribt IS '调味物料品种与产品属性';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.plant_code IS '工厂代码';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.plant_descrptn IS '工厂描述';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.mat_code IS '物料编码';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.mat_name IS '物料名称';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.is_rawmat IS '是否原料';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.sauce_brd IS '调味品种';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.prdct_atribt IS '产品属性';
COMMENT ON COLUMN ds_mannual.sauce_mat_brd_prdct_atribt.zdelta_time IS '更新时间戳';

-- ========================================
-- ODS层表
-- ========================================
DROP VIEW IF EXISTS dwd.v_dwd_scd_sauce_mat_brd_prdct_atribt;
DROP TABLE IF EXISTS ods.ods_mannual_sauce_mat_brd_prdct_atribt;

CREATE TABLE ods.ods_mannual_sauce_mat_brd_prdct_atribt (
    plant_code varchar,
    plant_descrptn varchar,
    mat_code varchar,
    mat_name varchar,
    is_rawmat varchar,
    sauce_brd varchar,
    prdct_atribt varchar,
    zdelta_time timestamp,
    zis_physc_del int4 DEFAULT 0,
    CONSTRAINT pk_ods_mannual_sauce_mat_brd_prdct_atribt PRIMARY KEY (plant_code, mat_code)
)
USING beam;

COMMENT ON TABLE ods.ods_mannual_sauce_mat_brd_prdct_atribt IS '调味物料品种与产品属性';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.plant_code IS '工厂代码';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.plant_descrptn IS '工厂描述';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.mat_code IS '物料编码';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.mat_name IS '物料名称';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.is_rawmat IS '是否原料';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.sauce_brd IS '调味品种';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.prdct_atribt IS '产品属性';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.zdelta_time IS '更新时间戳';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_brd_prdct_atribt.zis_physc_del IS '物理删除标识(0=未删除,1=已删除)';

-- ========================================
-- ODS层视图（无数据过滤）
-- ========================================
DROP VIEW IF EXISTS ods.v_ods_mannual_sauce_mat_brd_prdct_atribt;

CREATE OR REPLACE VIEW ods.v_ods_mannual_sauce_mat_brd_prdct_atribt AS
SELECT
    plant_code,
    plant_descrptn,
    mat_code,
    mat_name,
    is_rawmat,
    sauce_brd,
    prdct_atribt,
    zdelta_time,
    zis_physc_del
FROM ods.ods_mannual_sauce_mat_brd_prdct_atribt;

COMMENT ON VIEW ods.v_ods_mannual_sauce_mat_brd_prdct_atribt IS '调味物料品种与产品属性-ODS层视图';

-- ========================================
-- DWD层表
-- ========================================
DROP VIEW IF EXISTS da.v_da_td_scd_sauce_mat_brd_prdct_atribt;
DROP TABLE IF EXISTS dwd.dwd_scd_sauce_mat_brd_prdct_atribt;
CREATE TABLE dwd.dwd_scd_sauce_mat_brd_prdct_atribt (
    plant_code varchar,
    plant_descrptn varchar,
    mat_code varchar,
    mat_name varchar,
    is_rawmat varchar,
    sauce_brd varchar,
    prdct_atribt varchar,
    zdelta_time timestamp,
    zis_physc_del int4 DEFAULT 0,
    CONSTRAINT pk_dwd_scd_sauce_mat_brd_prdct_atribt PRIMARY KEY (plant_code, mat_code)
)
USING beam;

COMMENT ON TABLE dwd.dwd_scd_sauce_mat_brd_prdct_atribt IS '调味物料品种与产品属性';
COMMENT ON COLUMN dwd.dwd_scd_sauce_mat_brd_prdct_atribt.plant_code IS '工厂代码';
COMMENT ON COLUMN dwd.dwd_scd_sauce_mat_brd_prdct_atribt.plant_descrptn IS '工厂描述';
COMMENT ON COLUMN dwd.dwd_scd_sauce_mat_brd_prdct_atribt.mat_code IS '物料编码';
COMMENT ON COLUMN dwd.dwd_scd_sauce_mat_brd_prdct_atribt.mat_name IS '物料名称';
COMMENT ON COLUMN dwd.dwd_scd_sauce_mat_brd_prdct_atribt.is_rawmat IS '是否原料';
COMMENT ON COLUMN dwd.dwd_scd_sauce_mat_brd_prdct_atribt.sauce_brd IS '调味品种';
COMMENT ON COLUMN dwd.dwd_scd_sauce_mat_brd_prdct_atribt.prdct_atribt IS '产品属性';
COMMENT ON COLUMN dwd.dwd_scd_sauce_mat_brd_prdct_atribt.zdelta_time IS '更新时间戳';
COMMENT ON COLUMN dwd.dwd_scd_sauce_mat_brd_prdct_atribt.zis_physc_del IS '物理删除标识(0=未删除,1=已删除)';

-- ========================================
-- DWD层视图（含反向增量CTE，只包含主表逻辑）
-- ========================================
DROP VIEW IF EXISTS dwd.v_dwd_scd_sauce_mat_brd_prdct_atribt;
CREATE OR REPLACE VIEW dwd.v_dwd_scd_sauce_mat_brd_prdct_atribt AS
WITH delta_records AS (
    SELECT a.plant_code, a.mat_code, count(1) AS count
    FROM (
        -- 主表增量逻辑（所有字段都从CSV提取）
        SELECT delta.plant_code, delta.mat_code
        FROM ods.ods_mannual_sauce_mat_brd_prdct_atribt delta
        WHERE true
    ) a
    GROUP BY a.plant_code, a.mat_code
)
SELECT
    ods.plant_code,
    ods.plant_descrptn,
    ods.mat_code,
    ods.mat_name,
    ods.is_rawmat,
    ods.sauce_brd,
    ods.prdct_atribt,
    ods.zdelta_time,
    ods.zis_physc_del
FROM ods.ods_mannual_sauce_mat_brd_prdct_atribt ods
WHERE 'TRUE'::text = 'TRUE'::text OR (EXISTS (
    SELECT 1
    FROM delta_records dr
    WHERE dr.plant_code = ods.plant_code
    AND dr.mat_code = ods.mat_code
));

COMMENT ON VIEW dwd.v_dwd_scd_sauce_mat_brd_prdct_atribt IS '调味物料品种与产品属性-DWD层视图(含反向增量CTE)';

-- ========================================
-- DA层表
-- ========================================
DROP VIEW IF EXISTS da_selfhp.da_td_scd_sauce_mat_brd_prdct_atribt_调味物料品种与产品属性;
DROP TABLE IF EXISTS da.da_td_scd_sauce_mat_brd_prdct_atribt;
CREATE TABLE da.da_td_scd_sauce_mat_brd_prdct_atribt (
    plant_code varchar,
    plant_descrptn varchar,
    mat_code varchar,
    mat_name varchar,
    is_rawmat varchar,
    sauce_brd varchar,
    prdct_atribt varchar,
    zdelta_time timestamp,
    zis_physc_del int4 DEFAULT 0,
    CONSTRAINT pk_da_td_scd_sauce_mat_brd_prdct_atribt PRIMARY KEY (plant_code, mat_code)
)
USING beam;

COMMENT ON TABLE da.da_td_scd_sauce_mat_brd_prdct_atribt IS '调味物料品种与产品属性';
COMMENT ON COLUMN da.da_td_scd_sauce_mat_brd_prdct_atribt.plant_code IS '工厂代码';
COMMENT ON COLUMN da.da_td_scd_sauce_mat_brd_prdct_atribt.plant_descrptn IS '工厂描述';
COMMENT ON COLUMN da.da_td_scd_sauce_mat_brd_prdct_atribt.mat_code IS '物料编码';
COMMENT ON COLUMN da.da_td_scd_sauce_mat_brd_prdct_atribt.mat_name IS '物料名称';
COMMENT ON COLUMN da.da_td_scd_sauce_mat_brd_prdct_atribt.is_rawmat IS '是否原料';
COMMENT ON COLUMN da.da_td_scd_sauce_mat_brd_prdct_atribt.sauce_brd IS '调味品种';
COMMENT ON COLUMN da.da_td_scd_sauce_mat_brd_prdct_atribt.prdct_atribt IS '产品属性';
COMMENT ON COLUMN da.da_td_scd_sauce_mat_brd_prdct_atribt.zdelta_time IS '更新时间戳';
COMMENT ON COLUMN da.da_td_scd_sauce_mat_brd_prdct_atribt.zis_physc_del IS '物理删除标识(0=未删除,1=已删除)';

-- ========================================
-- DA层视图（含反向增量CTE，只包含主表逻辑）
-- ========================================
DROP VIEW IF EXISTS da.v_da_td_scd_sauce_mat_brd_prdct_atribt;

CREATE OR REPLACE VIEW da.v_da_td_scd_sauce_mat_brd_prdct_atribt AS
WITH delta_records AS (
    SELECT a.plant_code, a.mat_code, count(1) AS count
    FROM (
        -- 主表增量逻辑（所有字段都从CSV提取）
        SELECT delta.plant_code, delta.mat_code
        FROM dwd.dwd_scd_sauce_mat_brd_prdct_atribt delta
        WHERE true
    ) a
    GROUP BY a.plant_code, a.mat_code
)
SELECT
    dwd.plant_code,
    dwd.plant_descrptn,
    dwd.mat_code,
    dwd.mat_name,
    dwd.is_rawmat,
    dwd.sauce_brd,
    dwd.prdct_atribt,
    dwd.zdelta_time,
    dwd.zis_physc_del
FROM dwd.dwd_scd_sauce_mat_brd_prdct_atribt dwd
WHERE 'TRUE'::text = 'TRUE'::text OR (EXISTS (
    SELECT 1
    FROM delta_records dr
    WHERE dr.plant_code = dwd.plant_code
    AND dr.mat_code = dwd.mat_code
));

COMMENT ON VIEW da.v_da_td_scd_sauce_mat_brd_prdct_atribt IS '调味物料品种与产品属性-DA层视图(含反向增量CTE)';

-- ========================================
-- DA层中文查询视图
-- ========================================
DROP VIEW IF EXISTS da_selfhp.da_td_scd_sauce_mat_brd_prdct_atribt_调味物料品种与产品属性;

CREATE OR REPLACE VIEW da_selfhp.da_td_scd_sauce_mat_brd_prdct_atribt_调味物料品种与产品属性 WITH (security_invoker=true) AS
SELECT
    plant_code AS "工厂代码",
    plant_descrptn AS "工厂描述",
    mat_code AS "物料编码",
    mat_name AS "物料名称",
    is_rawmat AS "是否原料",
    sauce_brd AS "调味品种",
    prdct_atribt AS "产品属性",
    zdelta_time AS "更新时间戳",
    zis_physc_del AS "物理删除标识"
FROM da.da_td_scd_sauce_mat_brd_prdct_atribt
WHERE zis_physc_del = 0;

COMMENT ON VIEW da_selfhp.da_td_scd_sauce_mat_brd_prdct_atribt_调味物料品种与产品属性 IS '调味物料品种与产品属性-DA层中文查询视图';













