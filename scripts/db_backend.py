#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UtilityLog 数据库后端抽象层（0.3 双后端：SQLite 默认 / MySQL 可选）

- 后端选择：环境变量 UL_BACKEND（sqlite / mysql），默认 sqlite
- 运行目录：环境变量 UL_APP_DIR（优先）→ UL_ROOT → 脚本上级推导
  - SQLite 库默认 <APP_DIR>/data/utility.db（可用 UL_DB 覆盖）
  - MySQL 连接配置默认读取 <APP_DIR>/db_config.json（可用 UL_DB_CONFIG 覆盖）
- 方言兼容：业务代码统一写 SQLite 风格 SQL（? 占位、AUTOINCREMENT、
  datetime('now','localtime')、ON CONFLICT ... excluded），MySQL 后端自动翻译；
  upsert 请用本模块的 upsert_sql() 生成（ON CONFLICT / ON DUPLICATE KEY 差异）。
"""
import json
import os
import re
from pathlib import Path


def resolve_app_dir():
    """运行目录解析：UL_APP_DIR > UL_ROOT > 仓库根"""
    env = os.environ.get("UL_APP_DIR") or os.environ.get("UL_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def get_backend():
    """后端选择，优先级与文档完全一致：UL_BACKEND > db_config.json.backend > sqlite

    早期实现只读环境变量，而 README / INSTALL / DESIGN 都声称会读配置文件的
    backend 字段 —— 文档与实现不一致（0.5.2 修）。launchd 部署仍在 plist 里
    显式写 UL_BACKEND，行为不变。
    """
    env = (os.environ.get("UL_BACKEND") or "").strip().lower()
    if env in ("sqlite", "mysql"):
        return env
    try:
        cfg = json.loads(Path(db_config_path()).read_text(encoding="utf-8"))
        b = str(cfg.get("mysql", cfg).get("backend", "")).strip().lower()
        if b in ("sqlite", "mysql"):
            return b
    except Exception:
        pass
    return "sqlite"


def db_config_path():
    return os.environ.get("UL_DB_CONFIG", str(resolve_app_dir() / "db_config.json"))


def load_mysql_config():
    """读取 MySQL 连接配置（本地配置文件，不入库）"""
    path = Path(db_config_path())
    if not path.exists():
        raise FileNotFoundError(
            f"MySQL backend requires config file: {path} (copy from db_config.example.json and fill in)")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    mysql = cfg.get("mysql", cfg)
    return {
        "host": mysql.get("host", "127.0.0.1"),
        "port": int(mysql.get("port", 3306)),
        "user": mysql["user"],
        "password": mysql["password"],
        "database": mysql.get("database", "utilitylog"),
        "charset": mysql.get("charset", "utf8mb4"),
    }


class _Conn:
    """统一连接适配器：SQLite 原生 Connection 与 MySQL DictCursor 封装同接口"""

    def __init__(self, raw, backend):
        self._raw = raw
        self._backend = backend
        self._last_cur = None

    def execute(self, sql, params=None):
        if self._backend == "mysql":
            cur = self._raw.cursor()
            cur.execute(_mysql_sql(sql), params or ())
        else:
            cur = self._raw.execute(sql, params or ())
        self._last_cur = cur
        return cur

    def executescript(self, sql):
        """多语句执行：SQLite 原生支持；MySQL 按分号拆句逐条执行"""
        if self._backend == "mysql":
            for stmt in _split_statements(sql):
                if stmt:
                    self._raw.cursor().execute(_mysql_sql(stmt))
        else:
            self._raw.executescript(sql)

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()

    @property
    def raw(self):
        return self._raw


def _mysql_sql(sql):
    """SQLite 风格 SQL -> MySQL 方言（仅做安全字符级替换）"""
    sql = sql.replace("AUTOINCREMENT", "AUTO_INCREMENT")
    sql = re.sub(r"\bdatetime\(['\"]now['\"],\s*['\"]localtime['\"]\)", "NOW()", sql, flags=re.I)
    sql = sql.replace("?", "%s")
    # usage 是 MySQL 保留字，统一反引号（已反引号的保持不变；SQLite 同样接受反引号标识符）
    sql = re.sub(r"(?<!`)\busage\b(?!`)", "`usage`", sql)
    sql = sql.replace("last_insert_rowid()", "LAST_INSERT_ID()")
    return sql


def _split_statements(sql):
    """按分号拆分；跳过空行与 -- 注释行（本项目 schema 无存储过程/触发器）"""
    parts = []
    cur = []
    for line in sql.splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        cur.append(line)
        if line.rstrip().endswith(";"):
            parts.append("\n".join(cur))
            cur = []
    if cur:
        parts.append("\n".join(cur))
    return [p.strip() for p in parts if p.strip()]


def get_conn():
    """返回统一连接对象（sqlite3 Row / pymysql DictCursor，均支持 row['col']）"""
    backend = get_backend()
    if backend == "mysql":
        import pymysql
        cfg = load_mysql_config()
        conn = pymysql.connect(
            host=cfg["host"], port=cfg["port"], user=cfg["user"],
            password=cfg["password"], database=cfg["database"],
            charset=cfg["charset"], cursorclass=pymysql.cursors.DictCursor,
        )
        c = _Conn(conn, "mysql")
        ensure_schema(c)
        return c
    import sqlite3
    db = os.environ.get("UL_DB", str(resolve_app_dir() / "data" / "utility.db"))
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    # PRAGMA foreign_keys 是「连接级」开关，默认 OFF —— schema.sql 里的声明
    # 只对执行该脚本的那一次连接有效，运行时连接必须逐个开启，
    # 否则 families.user_id / bills_*.family_id 的引用完整性形同虚设。
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL 模式：读写不互相阻塞，缓解多线程写入时的 database is locked
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error:
        pass
    c = _Conn(conn, "sqlite")
    ensure_schema(c)
    return c


REQUIRED_TABLES = {
    "users", "families",
    "bills_water", "bills_electric", "bills_gas",
    "api_tokens", "user_settings",
}

# 进程内「表已就绪」缓存，避免每次连接都做一次建表检测
# （MySQL 的 SHOW TABLES 是网络往返，在请求热路径上代价明显）
_SCHEMA_OK = set()


def _schema_cache_key():
    """缓存键：后端 + 目标库路径（不同库不能共用同一结论）"""
    backend = get_backend()
    if backend == "mysql":
        try:
            cfg = load_mysql_config()
            return f"mysql:{cfg['host']}:{cfg['port']}/{cfg['database']}"
        except Exception:
            return "mysql:unknown"
    return f"sqlite:{os.environ.get('UL_DB', str(resolve_app_dir() / 'data' / 'utility.db'))}"


def schema_file_path():
    """返回仓库内 schema 文件（MySQL: db/schema.mysql.sql；SQLite: db/schema.sql）"""
    repo_root = Path(__file__).resolve().parent.parent
    name = "db/schema.mysql.sql" if get_backend() == "mysql" else "db/schema.sql"
    return repo_root / name


def ensure_schema(conn):
    """幂等建表：检测核心表缺失后执行 schema 文件（均为 CREATE TABLE IF NOT EXISTS）。

    - 仅在缺表时执行一次，避免每次连接重复 DDL；
    - schema.mysql.sql 仍保留，供手动建表或 DBA 审阅；
    - 目标库已存在全部核心表时直接跳过（不校验列变更，升级用 deploy.sh 处理）。

    性能：检测结果按「后端 + 库路径」缓存到进程内。
    MySQL 下 SHOW TABLES 是网络往返，每个请求都查会显著放大开销。
    缓存仅在进程生命周期内有效——服务重启后会重新检测一次（幂等，代价可接受）。
    """
    backend = get_backend()
    key = _schema_cache_key()
    if key in _SCHEMA_OK:
        return
    missing = False
    if backend == "mysql":
        cur = conn.execute("SHOW TABLES")
        tables = {list(r.values())[0] for r in cur.fetchall()}
        missing = not REQUIRED_TABLES.issubset(tables)
    else:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = {r[0] for r in cur.fetchall()}
        missing = not REQUIRED_TABLES.issubset(tables)
    if not missing:
        _SCHEMA_OK.add(key)
        return
    schema = schema_file_path()
    if not schema.exists():
        raise FileNotFoundError(f"schema file not found: {schema}")
    conn.executescript(schema.read_text(encoding="utf-8"))
    _SCHEMA_OK.add(key)


def upsert_sql(table, cols, params_count, conflict_cols, update_cols):
    """生成方言正确的 upsert 语句（SQLite ON CONFLICT / MySQL ON DUPLICATE KEY）"""
    ph = "?" if get_backend() == "sqlite" else "%s"
    placeholders = ", ".join(ph for _ in range(params_count))
    col_list = ", ".join(cols)
    conflict = ", ".join(conflict_cols)
    if get_backend() == "mysql":
        upd = ", ".join(f"{c}=VALUES({c})" for c in update_cols)
        return (f"INSERT INTO {table}({col_list}) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE {upd}")
    upd = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
    return (f"INSERT INTO {table}({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict}) DO UPDATE SET {upd}")


def now_expr():
    return "datetime('now','localtime')" if get_backend() == "sqlite" else "NOW()"
