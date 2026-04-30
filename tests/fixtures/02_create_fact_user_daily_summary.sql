-- =====================================================================
-- 02_create_fact_user_daily_summary.sql
-- 变更说明：新建用户每日汇总宽表，用于精细化运营分析
-- 影响对象：public.fact_user_daily_summary（CREATE，全新表）
-- 依赖说明：依赖 public.dim_date（已存在）和 public.dim_user_level（已存在）
--           与 01_alter 无依赖关系，可并行执行
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.fact_user_daily_summary (
    summary_id     BIGSERIAL     PRIMARY KEY,
    date_id        INTEGER       NOT NULL REFERENCES public.dim_date(date_id),
    user_id        BIGINT        NOT NULL,
    level_id       INTEGER       REFERENCES public.dim_user_level(level_id),
    order_count    INTEGER       NOT NULL DEFAULT 0 CHECK (order_count >= 0),
    total_gmv      DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    total_discount DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    net_revenue    DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    score_earned   INTEGER       NOT NULL DEFAULT 0 CHECK (score_earned >= 0),
    created_at     TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMP     NOT NULL DEFAULT NOW(),
    UNIQUE (date_id, user_id)
);

COMMENT ON TABLE  public.fact_user_daily_summary               IS '用户每日行为汇总宽表（ETL 聚合产物，用于精细化运营）';
COMMENT ON COLUMN public.fact_user_daily_summary.total_gmv     IS '当日下单原始金额（含折扣前）';
COMMENT ON COLUMN public.fact_user_daily_summary.net_revenue   IS '当日实收金额';
COMMENT ON COLUMN public.fact_user_daily_summary.score_earned  IS '当日累计获得积分';

CREATE INDEX IF NOT EXISTS idx_fuds_date_id  ON public.fact_user_daily_summary(date_id);
CREATE INDEX IF NOT EXISTS idx_fuds_user_id  ON public.fact_user_daily_summary(user_id);
CREATE INDEX IF NOT EXISTS idx_fuds_level_id ON public.fact_user_daily_summary(level_id);
