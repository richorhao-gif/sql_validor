-- =====================================================================
-- 03_sauce_mat_variety_new_asset.sql
-- 资产名称：调味品品种
-- 资产技术名：sauce_mat_variety
-- 数据域：供应链域 | 资产类型：全新资产（库中不存在同名对象）
--
-- 变更内容：
--   从零建立调味品品种全链路：DS → ODS → DWD → DA → BI
--
-- 注意事项：
--   1. SERVER oss_serv 已被 sauce_mat_brd / sauce_mat_abbr 使用
--      本脚本新增第三张挂载到 oss_serv 的 FOREIGN TABLE
--      需确认 oss_serv 当前状态正常
--   2. 品种表包含 parent_code（树型结构），自引用逻辑需后续处理
--   3. 本脚本与 Fixture 01 / 02 无执行顺序依赖，可并行部署
-- =====================================================================

-- ── DS 层：创建 FOREIGN TABLE（新资产，库中当前不存在）────────────────
DROP FOREIGN TABLE IF EXISTS ds_mannual.sauce_mat_variety;

CREATE FOREIGN TABLE ds_mannual.sauce_mat_variety (
    variety_code   varchar,
    variety_name   varchar,
    variety_type   varchar,
    parent_code    varchar,
    is_active      varchar,
    zdelta_time    timestamp
)
SERVER oss_serv
OPTIONS (
    prefix    '/offline_data/M0008_川渝经营驾驶舱/调味品品种导入/',
    format    'csv',
    header    'true',
    delimiter ','
);
COMMENT ON FOREIGN TABLE ds_mannual.sauce_mat_variety IS '调味品品种';
COMMENT ON COLUMN ds_mannual.sauce_mat_variety.variety_code IS '品种编码';
COMMENT ON COLUMN ds_mannual.sauce_mat_variety.variety_name IS '品种名称';
COMMENT ON COLUMN ds_mannual.sauce_mat_variety.variety_type IS '品种类型（如：酱类/醋类/料酒类）';
COMMENT ON COLUMN ds_mannual.sauce_mat_variety.parent_code  IS '父级品种编码（树型结构，根节点为空）';
COMMENT ON COLUMN ds_mannual.sauce_mat_variety.is_active    IS '是否有效（Y/N）';

-- ── ODS 层 ───────────────────────────────────────────────────────────
DROP VIEW IF EXISTS ods.v_ods_mannual_sauce_mat_variety;
DROP TABLE IF EXISTS ods.ods_mannual_sauce_mat_variety;

CREATE TABLE ods.ods_mannual_sauce_mat_variety (
    variety_code  varchar,
    variety_name  varchar,
    variety_type  varchar,
    parent_code   varchar,
    is_active     varchar,
    zdelta_time   timestamp,
    zis_physc_del int4 DEFAULT 0,
    CONSTRAINT pk_ods_mannual_sauce_mat_variety PRIMARY KEY (variety_code)
) USING beam;
COMMENT ON TABLE  ods.ods_mannual_sauce_mat_variety IS '调味品品种-ODS';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_variety.variety_code IS '品种编码（主键）';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_variety.parent_code  IS '父级品种编码';
COMMENT ON COLUMN ods.ods_mannual_sauce_mat_variety.zis_physc_del IS '物理删除标识(0=未删除,1=已删除)';

CREATE OR REPLACE VIEW ods.v_ods_mannual_sauce_mat_variety AS
SELECT variety_code, variety_name, variety_type, parent_code,
       is_active, zdelta_time, zis_physc_del
FROM ods.ods_mannual_sauce_mat_variety;
COMMENT ON VIEW ods.v_ods_mannual_sauce_mat_variety IS '调味品品种-ODS视图';

-- ── DWD 层 ───────────────────────────────────────────────────────────
DROP VIEW IF EXISTS dwd.v_dwd_scd_sauce_mat_variety;
DROP TABLE IF EXISTS dwd.dwd_scd_sauce_mat_variety;

CREATE TABLE dwd.dwd_scd_sauce_mat_variety (
    variety_code  varchar,
    variety_name  varchar,
    variety_type  varchar,
    parent_code   varchar,
    is_active     varchar,
    zdelta_time   timestamp,
    zis_physc_del int4 DEFAULT 0,
    CONSTRAINT pk_dwd_scd_sauce_mat_variety PRIMARY KEY (variety_code)
) USING beam;
COMMENT ON TABLE dwd.dwd_scd_sauce_mat_variety IS '调味品品种-DWD';

CREATE OR REPLACE VIEW dwd.v_dwd_scd_sauce_mat_variety AS
WITH delta_records AS (
    SELECT a.variety_code, count(1) AS cnt
    FROM (
        SELECT delta.variety_code
        FROM ods.ods_mannual_sauce_mat_variety delta
        WHERE true
    ) a
    GROUP BY a.variety_code
)
SELECT
    ods.variety_code, ods.variety_name, ods.variety_type,
    ods.parent_code, ods.is_active, ods.zdelta_time, ods.zis_physc_del
FROM ods.ods_mannual_sauce_mat_variety ods
WHERE 'TRUE'::text = 'TRUE'::text
   OR EXISTS (
        SELECT 1 FROM delta_records dr WHERE dr.variety_code = ods.variety_code
   );
COMMENT ON VIEW dwd.v_dwd_scd_sauce_mat_variety IS '调味品品种-DWD视图（含反向增量CTE）';

-- ── DA 层 ────────────────────────────────────────────────────────────
DROP VIEW IF EXISTS da.v_da_td_scd_sauce_mat_variety;
DROP TABLE IF EXISTS da.da_td_scd_sauce_mat_variety;

CREATE TABLE da.da_td_scd_sauce_mat_variety (
    variety_code  varchar,
    variety_name  varchar,
    variety_type  varchar,
    parent_code   varchar,
    is_active     varchar,
    zdelta_time   timestamp,
    zis_physc_del int4 DEFAULT 0,
    CONSTRAINT pk_da_td_scd_sauce_mat_variety PRIMARY KEY (variety_code)
) USING beam;
COMMENT ON TABLE da.da_td_scd_sauce_mat_variety IS '调味品品种-DA';

CREATE OR REPLACE VIEW da.v_da_td_scd_sauce_mat_variety AS
WITH delta_records AS (
    SELECT a.variety_code, count(1) AS cnt
    FROM (
        SELECT delta.variety_code
        FROM dwd.dwd_scd_sauce_mat_variety delta
        WHERE true
    ) a
    GROUP BY a.variety_code
)
SELECT
    dwd.variety_code, dwd.variety_name, dwd.variety_type,
    dwd.parent_code, dwd.is_active, dwd.zdelta_time, dwd.zis_physc_del
FROM dwd.dwd_scd_sauce_mat_variety dwd
WHERE 'TRUE'::text = 'TRUE'::text
   OR EXISTS (
        SELECT 1 FROM delta_records dr WHERE dr.variety_code = dwd.variety_code
   );
COMMENT ON VIEW da.v_da_td_scd_sauce_mat_variety IS '调味品品种-DA视图（含反向增量CTE）';

-- ── BI 自助层 ────────────────────────────────────────────────────────
DROP VIEW IF EXISTS da_selfhp.sauce_mat_variety_调味品品种;

CREATE OR REPLACE VIEW da_selfhp.sauce_mat_variety_调味品品种
    WITH (security_invoker=true) AS
SELECT
    variety_code AS "品种编码",
    variety_name AS "品种名称",
    variety_type AS "品种类型",
    parent_code  AS "父级编码",
    is_active    AS "是否有效",
    zdelta_time  AS "更新时间戳"
FROM da.da_td_scd_sauce_mat_variety
WHERE zis_physc_del = 0;
COMMENT ON VIEW da_selfhp.sauce_mat_variety_调味品品种
    IS '调味品品种-BI中文查询视图（security_invoker，全新资产）';
