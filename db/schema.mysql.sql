-- ============================================================
-- UtilityLog 数据库 Schema（MySQL）
-- 版本: 0.3.1
-- 说明:
--   - 与 db/schema.sql（SQLite 版）结构一致，方言为 MySQL 8 / MariaDB 兼容
--   - 建库与授权由部署步骤完成（utilitylog 库 + ul_app 低权限用户），本文件仅建表
--   - 使用方式（ul_app 用户在 utilitylog 库上执行）:
--       mysql -h127.0.0.1 -P9306 -uul_app -p utilitylog < db/schema.mysql.sql
-- ============================================================

-- ------------------------------------------------------------
-- 家庭表（账单归属的家庭；归属 user_id 用户）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS families (
    id         BIGINT NOT NULL AUTO_INCREMENT,
    name       VARCHAR(255) NOT NULL,
    user_id    BIGINT,
    created_at DATETIME NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id),
    UNIQUE KEY uq_families_user_name (user_id, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 水费账单表
-- 总价 amount = water_fee(水费金额) + sewage_fee(污水处理费金额)
-- 污水费计收比例 0.9（按用水量 90% 计收）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bills_water (
    id                BIGINT NOT NULL AUTO_INCREMENT,
    family_id         BIGINT NOT NULL,
    user_id           BIGINT,
    bill_month        VARCHAR(7) NOT NULL,          -- YYYY-MM
    `usage`         DOUBLE,                       -- 用量 m³
    usage_unit        VARCHAR(16) DEFAULT 'm³',
    prev_reading      DOUBLE,                       -- 上期读数
    cur_reading       DOUBLE,                       -- 本期读数
    water_unit_price  DOUBLE,                       -- 水费单价（元/m³）
    sewage_unit_price DOUBLE,                       -- 污水单价（元/m³）
    water_fee         DOUBLE,                       -- 水费金额（元）
    sewage_fee        DOUBLE,                       -- 污水处理费金额（元）
    amount            DOUBLE,                       -- 费用合计（元）= water_fee + sewage_fee
    bill_date         VARCHAR(16),                  -- 账单日期 YYYY-MM-DD
    image             VARCHAR(512),                 -- 截图相对路径
    note              TEXT,
    current_tier      VARCHAR(32),
    tier_remaining    DOUBLE,
    year_usage        DOUBLE,
    tier_detail       TEXT,                         -- JSON 档位明细
    created_at        DATETIME NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id),
    UNIQUE KEY uq_bills_water_family_month (family_id, bill_month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 电费账单表（峰谷分项，四示数独立不可合并）
-- 总价 amount = peak_usage*peak_price + valley_usage*valley_price
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bills_electric (
    id                  BIGINT NOT NULL AUTO_INCREMENT,
    family_id           BIGINT NOT NULL,
    user_id             BIGINT,
    bill_month          VARCHAR(7) NOT NULL,        -- YYYY-MM
    `usage`         DOUBLE,                     -- 总用量 kWh
    usage_unit          VARCHAR(16) DEFAULT 'kWh',
    prev_reading        DOUBLE,
    cur_reading         DOUBLE,
    unit_price          DOUBLE,                     -- 综合/平均单价（元/kWh）
    peak_prev_reading   DOUBLE,
    peak_cur_reading    DOUBLE,
    valley_prev_reading DOUBLE,
    valley_cur_reading  DOUBLE,
    peak_usage          DOUBLE,
    peak_price          DOUBLE,
    valley_usage        DOUBLE,
    valley_price        DOUBLE,
    amount              DOUBLE,                     -- 费用合计（元）
    bill_date           VARCHAR(16),
    image               VARCHAR(512),
    note                TEXT,
    current_tier        VARCHAR(32),
    tier_remaining      DOUBLE,
    year_usage          DOUBLE,
    tier_detail         TEXT,
    created_at          DATETIME NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id),
    UNIQUE KEY uq_bills_electric_family_month (family_id, bill_month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 燃气费账单表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bills_gas (
    id             BIGINT NOT NULL AUTO_INCREMENT,
    family_id      BIGINT NOT NULL,
    user_id        BIGINT,
    bill_month     VARCHAR(7) NOT NULL,             -- YYYY-MM
    `usage`         DOUBLE,                          -- 用量 m³
    usage_unit     VARCHAR(16) DEFAULT 'm³',
    prev_reading   DOUBLE,
    cur_reading    DOUBLE,
    unit_price     DOUBLE,                          -- 单价（元/m³）
    amount         DOUBLE,                          -- 费用（元）
    bill_date      VARCHAR(16),
    image          VARCHAR(512),
    note           TEXT,
    current_tier   VARCHAR(32),
    tier_remaining DOUBLE,
    year_usage     DOUBLE,
    tier_detail    TEXT,
    created_at     DATETIME NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id),
    UNIQUE KEY uq_bills_gas_family_month (family_id, bill_month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 多用户表（0.2 起启用）
-- ============================================================

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id            BIGINT NOT NULL AUTO_INCREMENT,
    username      VARCHAR(64) NOT NULL,            -- 登录名
    password_hash VARCHAR(512) NOT NULL,           -- PBKDF2 哈希
    display_name  VARCHAR(128),
    created_at    DATETIME NOT NULL DEFAULT NOW(),
    is_active     TINYINT NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 用户 API Token
CREATE TABLE IF NOT EXISTS api_tokens (
    id         BIGINT NOT NULL AUTO_INCREMENT,
    user_id    BIGINT NOT NULL,
    token      VARCHAR(255) NOT NULL,              -- secrets.token_urlsafe(32)
    scope      VARCHAR(32) NOT NULL DEFAULT 'bill:write',
    expires_at VARCHAR(32),                        -- 过期时间（NULL 永不过期）
    created_at DATETIME NOT NULL DEFAULT NOW(),
    last_used  VARCHAR(32),
    PRIMARY KEY (id),
    UNIQUE KEY uq_api_tokens_token (token)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 用户设置（模型 API / 展示偏好等）
CREATE TABLE IF NOT EXISTS user_settings (
    user_id        BIGINT NOT NULL PRIMARY KEY,
    model_api_base VARCHAR(512),
    model_api_key  TEXT,
    model_name     VARCHAR(128),
    theme          VARCHAR(16) DEFAULT 'light',
    updated_at     VARCHAR(32)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
