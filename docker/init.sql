-- =====================================================================
-- sql_validator — Mock 数据仓库初始化脚本
-- 模拟一个电商平台 DW（Data Warehouse）的现有状态
-- 该脚本在 Docker 首次启动时自动执行
-- =====================================================================

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

\echo '>>> [1/5] 创建维度表...'

-- ── 日期维度 ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.dim_date (
    date_id      INTEGER      PRIMARY KEY,           -- YYYYMMDD 格式
    full_date    DATE         NOT NULL UNIQUE,
    year         SMALLINT     NOT NULL,
    quarter      SMALLINT     NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month        SMALLINT     NOT NULL CHECK (month  BETWEEN 1 AND 12),
    day          SMALLINT     NOT NULL CHECK (day    BETWEEN 1 AND 31),
    week_of_year SMALLINT     NOT NULL,
    is_weekend   BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE  public.dim_date               IS '日期维度表（DW 标准日历维度）';
COMMENT ON COLUMN public.dim_date.date_id       IS '日期主键，格式 YYYYMMDD';
COMMENT ON COLUMN public.dim_date.is_weekend    IS 'TRUE 表示周六/周日';

-- ── 用户等级维度（已有，测试变更脚本会在此基础上 ALTER）────────────────
CREATE TABLE IF NOT EXISTS public.dim_user_level (
    level_id    SERIAL       PRIMARY KEY,
    level_name  VARCHAR(50)  NOT NULL UNIQUE,
    min_score   INTEGER      NOT NULL DEFAULT 0,
    max_score   INTEGER      NOT NULL DEFAULT 100,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE  public.dim_user_level            IS '用户等级维度表（按积分分层）';
COMMENT ON COLUMN public.dim_user_level.min_score  IS '达到该等级所需最低积分';
COMMENT ON COLUMN public.dim_user_level.max_score  IS '该等级积分上限（含）';

-- ── 商品维度 ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.dim_product (
    product_id   BIGINT        PRIMARY KEY,
    product_name VARCHAR(200)  NOT NULL,
    category     VARCHAR(100),
    brand        VARCHAR(100),
    unit_price   DECIMAL(12,2) NOT NULL CHECK (unit_price >= 0),
    is_active    BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP     NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE  public.dim_product             IS '商品维度表';
COMMENT ON COLUMN public.dim_product.is_active   IS 'FALSE 表示已下架';

\echo '>>> [2/5] 创建事实表...'

-- ── 订单事实表 ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.fact_orders (
    order_id     BIGSERIAL     PRIMARY KEY,
    date_id      INTEGER       NOT NULL REFERENCES public.dim_date(date_id),
    user_id      BIGINT        NOT NULL,
    level_id     INTEGER       REFERENCES public.dim_user_level(level_id),
    product_id   BIGINT        NOT NULL REFERENCES public.dim_product(product_id),
    quantity     INTEGER       NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price   DECIMAL(12,2) NOT NULL,
    total_amount DECIMAL(14,2) NOT NULL CHECK (total_amount >= 0),
    discount_amt DECIMAL(12,2) NOT NULL DEFAULT 0 CHECK (discount_amt >= 0),
    net_amount   DECIMAL(14,2) NOT NULL CHECK (net_amount >= 0),
    status       VARCHAR(20)   NOT NULL DEFAULT 'COMPLETED'
                               CHECK (status IN ('COMPLETED','CANCELLED','PENDING','REFUNDED')),
    created_at   TIMESTAMP     NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE  public.fact_orders              IS '订单事实表（最细粒度：单笔订单）';
COMMENT ON COLUMN public.fact_orders.total_amount IS '订单原始金额（含折扣前）';
COMMENT ON COLUMN public.fact_orders.discount_amt IS '折扣金额';
COMMENT ON COLUMN public.fact_orders.net_amount   IS '实收金额 = total_amount - discount_amt';

CREATE INDEX IF NOT EXISTS idx_fact_orders_date_id    ON public.fact_orders(date_id);
CREATE INDEX IF NOT EXISTS idx_fact_orders_user_id    ON public.fact_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_fact_orders_level_id   ON public.fact_orders(level_id);
CREATE INDEX IF NOT EXISTS idx_fact_orders_product_id ON public.fact_orders(product_id);
CREATE INDEX IF NOT EXISTS idx_fact_orders_status     ON public.fact_orders(status);
CREATE INDEX IF NOT EXISTS idx_fact_orders_created_at ON public.fact_orders(created_at);

-- ── 用户积分变更日志 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.fact_user_score_log (
    log_id       BIGSERIAL    PRIMARY KEY,
    date_id      INTEGER      NOT NULL REFERENCES public.dim_date(date_id),
    user_id      BIGINT       NOT NULL,
    score_change INTEGER      NOT NULL,                -- 正数增加，负数扣减
    action_type  VARCHAR(50)  NOT NULL
                              CHECK (action_type IN ('ORDER','REFUND','ADMIN','EXPIRE','BONUS')),
    order_id     BIGINT       REFERENCES public.fact_orders(order_id),
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE  public.fact_user_score_log             IS '用户积分变更明细日志';
COMMENT ON COLUMN public.fact_user_score_log.score_change IS '积分变化量（正=增，负=减）';

CREATE INDEX IF NOT EXISTS idx_score_log_user_id    ON public.fact_user_score_log(user_id);
CREATE INDEX IF NOT EXISTS idx_score_log_date_id    ON public.fact_user_score_log(date_id);
CREATE INDEX IF NOT EXISTS idx_score_log_action_type ON public.fact_user_score_log(action_type);

\echo '>>> [3/5] 创建现有视图...'

-- ── 现有分析视图（用来验证变更脚本是否破坏依赖）──────────────────────
CREATE OR REPLACE VIEW public.vw_order_daily_summary AS
SELECT
    d.full_date,
    d.year,
    d.month,
    ul.level_name,
    COUNT(fo.order_id)             AS order_count,
    SUM(fo.total_amount)           AS total_gmv,
    SUM(fo.discount_amt)           AS total_discount,
    SUM(fo.net_amount)             AS net_revenue,
    ROUND(AVG(fo.total_amount), 2) AS avg_order_value
FROM  public.fact_orders fo
JOIN  public.dim_date       d  ON fo.date_id  = d.date_id
LEFT JOIN public.dim_user_level ul ON fo.level_id = ul.level_id
WHERE fo.status = 'COMPLETED'
GROUP BY d.full_date, d.year, d.month, ul.level_name;
COMMENT ON VIEW public.vw_order_daily_summary IS '每日订单汇总视图（供 BI 使用）';

\echo '>>> [4/5] 插入 Mock 基础数据...'

-- ── 日期维度（最近 60 天）────────────────────────────────────────────
INSERT INTO public.dim_date (date_id, full_date, year, quarter, month, day, week_of_year, is_weekend)
SELECT
    TO_CHAR(d, 'YYYYMMDD')::INTEGER,
    d::DATE,
    EXTRACT(YEAR    FROM d)::SMALLINT,
    EXTRACT(QUARTER FROM d)::SMALLINT,
    EXTRACT(MONTH   FROM d)::SMALLINT,
    EXTRACT(DAY     FROM d)::SMALLINT,
    EXTRACT(WEEK    FROM d)::SMALLINT,
    EXTRACT(DOW     FROM d) IN (0, 6)
FROM generate_series(
    CURRENT_DATE - INTERVAL '59 days',
    CURRENT_DATE,
    '1 day'::INTERVAL
) AS d
ON CONFLICT (date_id) DO NOTHING;

-- ── 用户等级 ─────────────────────────────────────────────────────────
INSERT INTO public.dim_user_level (level_name, min_score, max_score)
VALUES
    ('普通用户',   0,   59),
    ('银牌用户',  60,   79),
    ('金牌用户',  80,   99),
    ('钻石用户', 100,  999)
ON CONFLICT (level_name) DO NOTHING;

-- ── 商品数据（15 件）────────────────────────────────────────────────
INSERT INTO public.dim_product (product_id, product_name, category, brand, unit_price)
VALUES
    (1001, '无线蓝牙耳机 Pro',   '数码配件', '声海达',   299.00),
    (1002, '机械键盘 TKL 87键',  '外设',     '键圣',     589.00),
    (1003, '27寸显示器 4K IPS',  '显示器',   '明锐',    2499.00),
    (1004, '便携充电宝 20000mAh','数码配件', '能达',     169.00),
    (1005, '智能手表 S3 运动版', '穿戴设备', '时智',     899.00),
    (1006, 'USB-C 七合一扩展坞', '数码配件', '联拓',     349.00),
    (1007, '游戏鼠标 G502 Pro',  '外设',     '键圣',     399.00),
    (1008, '主动降噪耳机 NC700', '数码配件', '声海达',  1299.00),
    (1009, 'NVMe SSD 固态 1TB',  '存储',     '铁威马',   499.00),
    (1010, '1080P 网络摄像头',   '外设',     '洛技',     299.00),
    (1011, '无线充电底座 15W',   '数码配件', '贝尔金',   229.00),
    (1012, '机械手表 皮带版',    '穿戴设备', '时智',    3999.00),
    (1013, '平板电脑支架 铝合金','配件',     '山竹',     159.00),
    (1014, '路由器 WiFi6 AX3000','网络',     '网深',     599.00),
    (1015, '移动硬盘 2TB 加密版','存储',     '西数',     489.00)
ON CONFLICT (product_id) DO NOTHING;

\echo '>>> [5/5] 生成订单与积分模拟数据...'

-- ── 订单事实数据（过去 60 天，每天约 8-12 笔，共约 600 笔）──────────
INSERT INTO public.fact_orders (
    date_id, user_id, level_id, product_id,
    quantity, unit_price, total_amount, discount_amt, net_amount, status
)
SELECT
    TO_CHAR(order_date, 'YYYYMMDD')::INTEGER            AS date_id,
    (floor(random() * 500) + 1001)::BIGINT              AS user_id,
    (floor(random() * 4)   + 1)::INTEGER                AS level_id,
    p.product_id                                         AS product_id,
    (floor(random() * 3)   + 1)::INTEGER                AS quantity,
    p.unit_price,
    ROUND(((floor(random() * 3) + 1) * p.unit_price)::NUMERIC, 2) AS total_amount,
    ROUND((random() * 80)::NUMERIC, 2)                  AS discount_amt,
    ROUND(
        ((floor(random() * 3) + 1) * p.unit_price - random() * 80)::NUMERIC, 2
    )                                                    AS net_amount,
    CASE
        WHEN random() < 0.85 THEN 'COMPLETED'
        WHEN random() < 0.93 THEN 'CANCELLED'
        WHEN random() < 0.97 THEN 'REFUNDED'
        ELSE 'PENDING'
    END                                                  AS status
FROM generate_series(
    CURRENT_DATE - INTERVAL '59 days',
    CURRENT_DATE,
    '1 day'::INTERVAL
) AS order_date
CROSS JOIN LATERAL (
    SELECT product_id, unit_price
    FROM   public.dim_product
    WHERE  is_active = TRUE
    ORDER  BY random()
    LIMIT  (floor(random() * 5) + 8)   -- 每天 8~12 件商品被下单
) AS p;

-- ── 积分日志（从已完成订单中生成，每笔订单产生积分）────────────────────
INSERT INTO public.fact_user_score_log (date_id, user_id, score_change, action_type, order_id)
SELECT
    fo.date_id,
    fo.user_id,
    (fo.net_amount / 10)::INTEGER  AS score_change,   -- 每消费 10 元得 1 积分
    'ORDER'                        AS action_type,
    fo.order_id
FROM public.fact_orders fo
WHERE fo.status = 'COMPLETED';

-- ── 验证结果摘要 ────────────────────────────────────────────────────
DO $$
DECLARE
    v_dates   INTEGER;
    v_levels  INTEGER;
    v_products INTEGER;
    v_orders  INTEGER;
    v_scores  INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_dates    FROM public.dim_date;
    SELECT COUNT(*) INTO v_levels   FROM public.dim_user_level;
    SELECT COUNT(*) INTO v_products FROM public.dim_product;
    SELECT COUNT(*) INTO v_orders   FROM public.fact_orders;
    SELECT COUNT(*) INTO v_scores   FROM public.fact_user_score_log;
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Mock DW 初始化完成！';
    RAISE NOTICE '  dim_date         : % 行', v_dates;
    RAISE NOTICE '  dim_user_level   : % 行', v_levels;
    RAISE NOTICE '  dim_product      : % 行', v_products;
    RAISE NOTICE '  fact_orders      : % 行', v_orders;
    RAISE NOTICE '  fact_user_score_log: % 行', v_scores;
    RAISE NOTICE '========================================';
END;
$$;
