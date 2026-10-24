-- ============================================================
-- UtilityLog 数据库 Schema（SQLite）
-- 版本: 0.2.0
-- 说明:
--   - 多用户（users / api_tokens / user_settings）已启用
--   - families 与 bills_* 均带 user_id，数据按用户隔离
-- ============================================================

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
-- 家庭表（账单归属的家庭；归属 user_id 用户）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS families (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    user_id    INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ------------------------------------------------------------
-- 水费账单表
-- 总价 amount = water_fee(水费金额) + sewage_fee(污水处理费金额)
-- 污水费计收比例 0.9（按用水量 90% 计收）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bills_water (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id         INTEGER NOT NULL REFERENCES families(id),
    user_id           INTEGER REFERENCES users(id),
    bill_month        TEXT NOT NULL,              -- YYYY-MM
    usage             REAL,                       -- 用量 m³
    usage_unit        TEXT DEFAULT 'm³',
    prev_reading      REAL,                       -- 上期读数
    cur_reading       REAL,                       -- 本期读数
    water_unit_price  REAL,                       -- 水费单价（元/m³）
    sewage_unit_price REAL,                       -- 污水单价（元/m³）
    water_fee         REAL,                       -- 水费金额（元）
    sewage_fee        REAL,                       -- 污水处理费金额（元）
    amount            REAL,                       -- 费用合计（元）= water_fee + sewage_fee
    bill_date         TEXT,                       -- 账单日期 YYYY-MM-DD
    image             TEXT,                       -- 截图相对路径（site/images 下）
    note              TEXT,
    current_tier      TEXT,                       -- 当前档位
    tier_remaining    REAL,                       -- 本档剩余量
    year_usage        REAL,                       -- 年累计用量
    tier_detail       TEXT,                       -- JSON 档位明细
    created_at        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(family_id, bill_month)
);

-- ------------------------------------------------------------
-- 电费账单表（峰谷分项，四示数独立不可合并）
-- 总价 amount = peak_usage*peak_price + valley_usage*valley_price
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bills_electric (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id           INTEGER NOT NULL REFERENCES families(id),
    user_id             INTEGER REFERENCES users(id),
    bill_month          TEXT NOT NULL,            -- YYYY-MM
    usage               REAL,                     -- 总用量 kWh
    usage_unit          TEXT DEFAULT 'kWh',
    prev_reading        REAL,
    cur_reading         REAL,
    unit_price          REAL,                     -- 综合/平均单价（元/kWh）
    peak_prev_reading   REAL,                     -- 峰上期示数
    peak_cur_reading    REAL,                     -- 峰本期示数
    valley_prev_reading REAL,                     -- 谷上期示数
    valley_cur_reading  REAL,                     -- 谷本期示数
    peak_usage          REAL,                     -- 峰电量
    peak_price          REAL,                     -- 峰单价
    valley_usage        REAL,                     -- 谷电量
    valley_price        REAL,                     -- 谷单价
    amount              REAL,                     -- 费用合计（元）
    bill_date           TEXT,
    image               TEXT,
    note                TEXT,
    current_tier        TEXT,
    tier_remaining      REAL,
    year_usage          REAL,
    tier_detail         TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(family_id, bill_month)
);

-- ------------------------------------------------------------
-- 燃气费账单表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bills_gas (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id      INTEGER NOT NULL REFERENCES families(id),
    user_id        INTEGER REFERENCES users(id),
    bill_month     TEXT NOT NULL,                 -- YYYY-MM
    usage          REAL,                          -- 用量 m³
    usage_unit     TEXT DEFAULT 'm³',
    prev_reading   REAL,
    cur_reading    REAL,
    unit_price     REAL,                          -- 单价（元/m³）
    amount         REAL,                          -- 费用（元）
    bill_date      TEXT,
    image          TEXT,
    note           TEXT,
    current_tier   TEXT,
    tier_remaining REAL,
    year_usage     REAL,
    tier_detail    TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(family_id, bill_month)
);

-- ============================================================
-- 多用户表（0.2 起启用）
-- ============================================================

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,           -- 登录名
    password_hash TEXT NOT NULL,                  -- PBKDF2/argon2 哈希
    display_name  TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    is_active     INTEGER NOT NULL DEFAULT 1
);

-- 用户 API Token（供 Skill / 外部程序调用）
CREATE TABLE IF NOT EXISTS api_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    token      TEXT NOT NULL UNIQUE,              -- secrets.token_urlsafe(32)
    scope      TEXT NOT NULL DEFAULT 'bill:write',-- 权限范围
    expires_at TEXT,                              -- 过期时间（NULL 永不过期）
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    last_used  TEXT
);

-- 用户设置（模型 API / 展示偏好等）
CREATE TABLE IF NOT EXISTS user_settings (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id),
    model_api_base  TEXT,                         -- 通用模型 API 地址
    model_api_key   TEXT,                         -- 模型 Token（加密存储）
    model_name      TEXT,
    theme           TEXT DEFAULT 'light',
    updated_at      TEXT
);

-- 迁移说明：0.2 已为 families 与 bills_* 增加 user_id 列（正式 DDL 见上）
-- 旧库升级请使用 db/migrations/migrate_multiuser.py（自动备份 + ALTER + 数据归属）
