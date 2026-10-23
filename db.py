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

import threading
import time

_pg_pool: "psycopg2.pool.ThreadedConnectionPool | None" = None
_pg_init_done = False

# Ate 09/10 o pool tinha 5 conexoes e NAO esperava: a sexta consulta ao mesmo
# tempo levava "connection pool exhausted" na hora. Com a conversa aberta no
# painel, cada mensagem dispara varias requisicoes juntas com o webhook e o
# agente - e quem perdia a corrida era o agente, que entao nao respondia.
# Agora o pool e maior e quem chega com ele cheio ESPERA a vez.
_PG_MAX = int(os.getenv("DB_POOL_MAX", "12"))
_PG_ESPERA_SEG = 20
_pg_vagas = threading.BoundedSemaphore(_PG_MAX)

# Conexao parada por muito tempo pode ter sido derrubada no caminho (proxy do
# Supabase, NAT do Render): reaproveitada, a consulta ficava ~50 s pendurada
# esperando a rede. Keepalive mantem viva e detecta a morta; tcp_user_timeout
# poe um teto; e a que ficou parada demais e trocada antes de usar.
_PG_OCIOSA_SEG = 120
_PG_REDE = dict(connect_timeout=10, keepalives=1, keepalives_idle=20,
                keepalives_interval=5, keepalives_count=3, tcp_user_timeout=10000)
_pg_ultimo_uso: dict[int, float] = {}


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
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(1, _PG_MAX, url, **_PG_REDE)
    except psycopg2.ProgrammingError:
        # libpq antiga sem tcp_user_timeout: segue so com os keepalives
        rede = {k: v for k, v in _PG_REDE.items() if k != "tcp_user_timeout"}
        try:
            _pg_pool = psycopg2.pool.ThreadedConnectionPool(1, _PG_MAX, url, **rede)
        except Exception as e:
            print(f"[db] ERRO pool PostgreSQL: {e}")
            _pg_pool = None
            return
    except Exception as e:
        print(f"[db] ERRO pool PostgreSQL: {e}")
        _pg_pool = None
        return
    print(f"[db] pool PostgreSQL conectado (ate {_PG_MAX} conexoes, com espera)")


def _autocommit(conn):
    """Liga autocommit na conexao do pool.

    Sem ele, cada consulta custava 3 idas e voltas ao banco: o psycopg2 abre
    BEGIN antes da consulta, e o pool faz ROLLBACK ao receber a conexao de
    volta de uma leitura (que nunca da commit). Com o Supabase a ~180 ms, isso
    era ~560 ms por consulta. Cada chamada daqui ja confirma ou descarta
    sozinha - nenhuma transacao atravessa duas chamadas -, entao o
    comportamento e o mesmo e sobra 1 ida e volta.
    """
    if conn is not None and not conn.closed and not conn.autocommit:
        conn.autocommit = True
    return conn


def _get_pg_conn():
    """Uma conexao do pool. Com todas em uso, espera a vez (ate 20 s)."""
    if _pg_pool is None:
        _init_pg_pool()
    if _pg_pool is None:
        raise ConnectionError("Pool PostgreSQL nao disponivel")
    if not _pg_vagas.acquire(timeout=_PG_ESPERA_SEG):
        raise ConnectionError(f"Banco ocupado: nenhuma conexao livre em {_PG_ESPERA_SEG}s")
    try:
        conn = _pg_pool.getconn()
        parada = time.monotonic() - _pg_ultimo_uso.get(id(conn), time.monotonic())
        if conn.closed or parada > _PG_OCIOSA_SEG:
            _descartar(conn)
            conn = _pg_pool.getconn()
        return _autocommit(conn)
    except Exception:
        _pg_vagas.release()
        raise


def _descartar(conn):
    """Fecha a conexao e tira do pool (sem devolver a vaga)."""
    _pg_ultimo_uso.pop(id(conn), None)
    try:
        _pg_pool.putconn(conn, close=True)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def _put_pg_conn(conn, quebrada: bool = False):
    """Devolve a conexao ao pool e libera a vaga. Quebrada nao volta."""
    if conn is None:
        return
    try:
        if _pg_pool is None:
            return
        if quebrada or conn.closed:
            _descartar(conn)
        else:
            _pg_ultimo_uso[id(conn)] = time.monotonic()
            _pg_pool.putconn(conn)
    except Exception:
        pass
    finally:
        try:
            _pg_vagas.release()
        except ValueError:
            pass


def _erro_de_conexao(e: Exception) -> bool:
    """A conexao em si falhou (rede, servidor fechou) - e nao a consulta."""
    if DB_DRIVER != "postgresql":
        return False
    return isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError))


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


# ── Medicao (linha [tempo] do atendimento) ───────────────────────────────────
# Quanto do atendimento foi espera do banco: cada thread soma o proprio tempo.

_medicao = threading.local()


def iniciar_medicao() -> None:
    _medicao.seg = 0.0
    _medicao.idas = 0


def medicao() -> tuple[float, int]:
    return getattr(_medicao, "seg", 0.0), getattr(_medicao, "idas", 0)


def _medir(inicio: float) -> None:
    if hasattr(_medicao, "seg"):
        _medicao.seg += time.monotonic() - inicio
        _medicao.idas += 1


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


def _falhou(conn, e: Exception) -> None:
    """Devolve a conexao depois de um erro; a quebrada e descartada."""
    if DB_DRIVER != "postgresql":
        return
    quebrada = _erro_de_conexao(e)
    if not quebrada:
        try:
            conn.rollback()
        except Exception:
            quebrada = True
    _put_pg_conn(conn, quebrada=quebrada)


def execute(query: str, params: tuple | list | None = None, *, commit: bool = True) -> Any:
    """Executa uma query e opcionalmente faz commit. Retorna o cursor."""
    inicio = time.monotonic()
    try:
        return _execute(query, params, commit=commit)
    finally:
        _medir(inicio)


def _execute(query: str, params, *, commit: bool) -> Any:
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
    except Exception as e:
        _falhou(conn, e)
        raise


def _ler(query: str, params, uma: bool):
    conn = _get_conn()
    cur = _cursor(conn)
    adapted = _adapt_query(query)
    try:
        if params:
            cur.execute(adapted, params)
        else:
            cur.execute(adapted)
        resultado = cur.fetchone() if uma else cur.fetchall()
        if DB_DRIVER == "postgresql":
            _put_pg_conn(conn)
        return resultado
    except Exception as e:
        _falhou(conn, e)
        raise


def _ler_com_nova_tentativa(query: str, params, uma: bool):
    """Leitura nao altera nada: se a conexao estava morta, tenta numa nova."""
    inicio = time.monotonic()
    try:
        return _ler(query, params, uma)
    except Exception as e:
        if not _erro_de_conexao(e):
            raise
        print(f"[db] conexao caiu ({str(e).strip()[:80]}); repetindo a leitura")
        return _ler(query, params, uma)
    finally:
        _medir(inicio)


def fetch_one(query: str, params: tuple | list | None = None) -> dict | None:
    """Executa uma query e retorna uma linha como dict (ou None)."""
    return _to_dict(_ler_com_nova_tentativa(query, params, uma=True))


def fetch_all(query: str, params: tuple | list | None = None) -> list[dict]:
    """Executa uma query e retorna todas as linhas como lista de dicts."""
    return _to_dicts(_ler_com_nova_tentativa(query, params, uma=False))


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
    except Exception as e:
        _falhou(conn, e)
        raise


def execute_returning(query: str, params: tuple | list | None = None) -> int | None:
    """Executa um INSERT ... RETURNING id no PostgreSQL e retorna o ID."""
    inicio = time.monotonic()
    try:
        return _execute_returning(query, params)
    finally:
        _medir(inicio)


def _execute_returning(query: str, params) -> int | None:
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
    except Exception as e:
        _falhou(conn, e)
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
            # Só o schema public: no Supabase existe realtime.messages, e as
            # colunas dela se misturariam às da nossa tabela messages.
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s", (table_name,)
        )
        return {r["column_name"] for r in rows}
    else:
        rows = fetch_all(f"PRAGMA table_info({table_name})")
        return {r["name"] for r in rows}
