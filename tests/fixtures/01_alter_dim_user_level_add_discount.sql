-- =====================================================================
-- 01_alter_dim_user_level_add_discount.sql
-- 变更说明：为用户等级维度表新增折扣率字段，并初始化各等级折扣值
-- 影响对象：public.dim_user_level（ALTER，现有表）
-- 依赖说明：无前置脚本依赖，可独立执行
-- =====================================================================

-- 新增折扣率字段（ADD COLUMN IF NOT EXISTS 保证幂等）
ALTER TABLE public.dim_user_level
    ADD COLUMN IF NOT EXISTS discount_rate DECIMAL(5,2) NOT NULL DEFAULT 0.00;

COMMENT ON COLUMN public.dim_user_level.discount_rate
    IS '该等级用户享受的折扣率，例如 0.10 表示九折（10% 折扣），0.00 表示无折扣';

-- 初始化各等级折扣值
UPDATE public.dim_user_level SET discount_rate = 0.00 WHERE level_name = '普通用户';
UPDATE public.dim_user_level SET discount_rate = 0.05 WHERE level_name = '银牌用户';
UPDATE public.dim_user_level SET discount_rate = 0.10 WHERE level_name = '金牌用户';
UPDATE public.dim_user_level SET discount_rate = 0.15 WHERE level_name = '钻石用户';
