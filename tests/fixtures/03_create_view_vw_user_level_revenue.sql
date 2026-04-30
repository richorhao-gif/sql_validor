-- =====================================================================
-- 03_create_view_vw_user_level_revenue.sql
-- 变更说明：新建用户等级收入汇总视图，引用 discount_rate 新字段
-- 影响对象：public.vw_user_level_revenue（CREATE VIEW，全新视图）
-- 依赖说明：⚠️  引用了 01_alter 新增的 discount_rate 字段
--           必须在 01_alter_dim_user_level_add_discount.sql 执行完成后才能运行
--           依赖链：01 → 03
-- =====================================================================

CREATE OR REPLACE VIEW public.vw_user_level_revenue AS
SELECT
    ul.level_id,
    ul.level_name,
    ul.discount_rate,                                       -- 依赖 01_alter 新增字段
    COUNT(DISTINCT fo.user_id)             AS active_users,
    COUNT(fo.order_id)                     AS total_orders,
    SUM(fo.total_amount)                   AS total_gmv,
    SUM(fo.discount_amt)                   AS total_discount,
    SUM(fo.net_amount)                     AS net_revenue,
    ROUND(AVG(fo.total_amount), 2)         AS avg_order_value,
    ROUND(
        CASE
            WHEN SUM(fo.total_amount) > 0
            THEN SUM(fo.discount_amt) / SUM(fo.total_amount) * 100
            ELSE 0
        END, 2
    )                                      AS actual_discount_pct
FROM       public.dim_user_level ul
LEFT JOIN  public.fact_orders fo
        ON ul.level_id = fo.level_id
       AND fo.status   = 'COMPLETED'
GROUP BY ul.level_id, ul.level_name, ul.discount_rate
ORDER BY ul.level_id;

COMMENT ON VIEW public.vw_user_level_revenue
    IS '用户等级收入汇总视图（引用 discount_rate，执行前需完成 01_alter）';
