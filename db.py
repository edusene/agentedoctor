"""
db.py — Camada de abstração de banco de dados.
Suporta SQLite e PostgreSQL (Supabase).
Usa conexão persistente para PostgreSQL (evita overhead de abrir/fechar por query).
"""

import os
from typing import Any
from dotenv import load_dotenv

load_dotenv(override=True)

DB_DRIVER = os.getenv("DB_DRIVER", "sqlite")

if DB_DRIVER == "postgresql":
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool

# ── Conexão persistente (PostgreSQL) ─────────────────────────────────────────

_pg_pool: "psycopg2.pool.ThreadedConnectionPool | None" = None
_pg_init_done = False


def _init_pg_pool():
    """Inicializa o pool de conexões PostgreSQL (chamado uma vez)."""
    global _pg_pool, _pg_init_done
    if _pg_init_done:
        return
    _pg_init_done = True
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("[db] WARN: DATABASE_URL nao configurada")
        return
    try:
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(1, 5, url)
        print(f"[db] pool PostgreSQL conectado (1-5 conexoes)")
    except Exception as e:
        print(f"[db] ERRO pool PostgreSQL: {e}")
        _pg_pool = None


def _get_pg_conn():
    """Retorna uma conexão do pool. Reconnecta se necessário."""
    global _pg_pool
    if _pg_pool is None:
        _init_pg_pool()
    if _pg_pool is None:
        raise ConnectionError("Pool PostgreSQL nao disponivel")

    try:
        conn = _pg_pool.getconn()
        # Verifica se a conexão está viva
        if conn.closed:
            _pg_pool.putconn(conn, close=True)
            conn = _pg_pool.getconn()
        return conn
    except Exception:
        # Pool pode ter perdido conexões — reinicializa
        try:
            _init_pg_pool()
            if _pg_pool:
                return _pg_pool.getconn()
        except Exception:
            pass
        raise


def _put_pg_conn(conn):
    """Devolve a conexão ao pool."""
    if _pg_pool and conn and not conn.closed:
        try:
            _pg_pool.putconn(conn)
        except Exception:
            pass


def _get_conn():
    """Retorna uma conexão de banco (compatibilidade com código existente)."""
    if DB_DRIVER == "postgresql":
        return _get_pg_conn()
    else:
        import sqlite3
        db_path = os.getenv("DB_PATH", "whatsapp.db")
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def _cursor(conn):
    """Retorna um cursor adequado ao driver."""
    if DB_DRIVER == "postgresql":
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        return conn.cursor()


def _to_dict(row) -> dict | None:
    """Converte um resultado de query para dict."""
    if row is None:
        return None
    return dict(row)


def _to_dicts(rows) -> list[dict]:
    """Converte uma lista de resultados para lista de dicts."""
    return [_to_dict(r) for r in rows]


# ── Query helpers ────────────────────────────────────────────────────────────

def _adapt_query(query: str) -> str:
    """Adapta placeholders de SQLite (?) para PostgreSQL (%s) se necessário."""
    if DB_DRIVER == "postgresql":
        return query.replace("?", "%s")
    return query


def ago_sql(column: str, seconds: int) -> str:
    """Retorna comparação SQL 'col > agora-N-segundos', compatível com SQLite e PostgreSQL.
    No PostgreSQL, faz cast ::timestamptz porque created_at é TEXT no schema."""
    if DB_DRIVER == "postgresql":
        return f"{column}::timestamptz > NOW() - INTERVAL '{seconds} seconds'"
    return f"{column} > datetime('now', '-{seconds} seconds')"


def execute(query: str, params: tuple | list | None = None, *, commit: bool = True) -> Any:
    """Executa uma query e opcionalmente faz commit. Retorna o cursor."""
    conn = _get_conn()
    cur = _cursor(conn)
    adapted = _adapt_query(query)
    try:
        if params:
            cur.execute(adapted, params)
        else:
            cur.execute(adapted)
        if commit:
            conn.commit()
        if DB_DRIVER == "postgresql":
            _put_pg_conn(conn)
        return cur
    except Exception:
        if DB_DRIVER == "postgresql":
            try:
                conn.rollback()
            except Exception:
                pass
            _put_pg_conn(conn)
        raise


def fetch_one(query: str, params: tuple | list | None = None) -> dict | None:
    """Executa uma query e retorna uma linha como dict (ou None)."""
    conn = _get_conn()
    cur = _cursor(conn)
    adapted = _adapt_query(query)
    try:
        if params:
            cur.execute(adapted, params)
        else:
            cur.execute(adapted)
        row = cur.fetchone()
        if DB_DRIVER == "postgresql":
            _put_pg_conn(conn)
        return _to_dict(row)
    except Exception:
        if DB_DRIVER == "postgresql":
            try:
                conn.rollback()
            except Exception:
                pass
            _put_pg_conn(conn)
        raise


def fetch_all(query: str, params: tuple | list | None = None) -> list[dict]:
    """Executa uma query e retorna todas as linhas como lista de dicts."""
    conn = _get_conn()
    cur = _cursor(conn)
    adapted = _adapt_query(query)
    try:
        if params:
            cur.execute(adapted, params)
        else:
            cur.execute(adapted)
        rows = cur.fetchall()
        if DB_DRIVER == "postgresql":
            _put_pg_conn(conn)
        return _to_dicts(rows)
    except Exception:
        if DB_DRIVER == "postgresql":
            try:
                conn.rollback()
            except Exception:
                pass
            _put_pg_conn(conn)
        raise


def _schema_para_sqlite(sql: str) -> str:
    """O schema e escrito para PostgreSQL; estas tres trocas o fazem valer no SQLite."""
    return (sql.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
               .replace("DEFAULT NOW()", "DEFAULT CURRENT_TIMESTAMP")
               .replace("JSONB", "TEXT"))


def executescript(sql: str) -> None:
    """Executa um script SQL (múltiplos statements). Usado no init_db."""
    if DB_DRIVER != "postgresql":
        sql = _schema_para_sqlite(sql)
    conn = _get_conn()
    try:
        if DB_DRIVER == "postgresql":
            cur = _cursor(conn)
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    cur.execute(statement)
            conn.commit()
            _put_pg_conn(conn)
        else:
            conn.executescript(sql)
            conn.close()
    except Exception:
        if DB_DRIVER == "postgresql":
            try:
                conn.rollback()
            except Exception:
                pass
            _put_pg_conn(conn)
        raise


def execute_returning(query: str, params: tuple | list | None = None) -> int | None:
    """Executa um INSERT ... RETURNING id no PostgreSQL e retorna o ID."""
    conn = _get_conn()
    cur = _cursor(conn)
    try:
        if DB_DRIVER == "postgresql":
            adapted = query.replace("?", "%s")
            pg_query = adapted.rstrip().rstrip(";") + " RETURNING id"
            if params:
                cur.execute(pg_query, params)
            else:
                cur.execute(pg_query)
            conn.commit()
            row = cur.fetchone()
            _put_pg_conn(conn)
            return row["id"] if row else None
        else:
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)
            conn.commit()
            lid = cur.lastrowid
            conn.close()
            return lid
    except Exception:
        if DB_DRIVER == "postgresql":
            try:
                conn.rollback()
            except Exception:
                pass
            _put_pg_conn(conn)
        raise


def insert_ignore(table: str, columns: list[str], values: tuple) -> None:
    """Insere uma linha ignorando duplicatas (INSERT OR IGNORE / ON CONFLICT DO NOTHING)."""
    if DB_DRIVER == "postgresql":
        ph = ",".join(["%s"] * len(columns))
        cols = ",".join(columns)
        query = f"INSERT INTO {table} ({cols}) VALUES ({ph}) ON CONFLICT DO NOTHING"
    else:
        placeholders = ",".join(["?"] * len(columns))
        cols = ",".join(columns)
        query = f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})"
    execute(query, values)


def table_columns(table_name: str) -> set[str]:
    """Retorna os nomes das colunas de uma tabela."""
    if DB_DRIVER == "postgresql":
        rows = fetch_all(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s", (table_name,)
        )
        return {r["column_name"] for r in rows}
    else:
        rows = fetch_all(f"PRAGMA table_info({table_name})")
        return {r["name"] for r in rows}
