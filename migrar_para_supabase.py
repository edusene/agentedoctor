"""
migrar_para_supabase.py — Copia os dados do SQLite local para o Supabase.

Só o banco muda: o schema é criado pelo próprio database.init_db() (o mesmo
código que o app roda ao subir), e os dados são copiados tabela a tabela,
preservando os ids. Os embeddings são copiados como estão, sem chamar a
OpenAI de novo, e as respostas em cache (settings) vão junto.

Uso:
    python migrar_para_supabase.py --dry-run     # só conta o que há na origem
    python migrar_para_supabase.py               # mostra o destino e para
    python migrar_para_supabase.py --sim         # grava

Antes: no .env, DB_DRIVER=postgresql e DATABASE_URL do projeto NOVO
(agentedoctor). A origem é lida em modo somente leitura e nunca é alterada:
ela continua sendo o backup (voltar DB_DRIVER=sqlite desfaz a migração).
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv(override=True)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ordem das chaves estrangeiras: quem é referenciado vem antes.
TABELAS = [
    "contacts", "conversations", "messages", "tags", "contact_tags",
    "conversation_tags", "templates", "tasks", "crm_automations",
    "crm_follow_ups", "crm_logs", "conversation_states", "settings",
    "knowledge_files", "knowledge",
]


def abrir_origem(caminho: str) -> sqlite3.Connection:
    if not Path(caminho).exists():
        sys.exit(f"Origem não encontrada: {caminho}")
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def tabelas_origem(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--origem", default=os.getenv("DB_PATH_ORIGEM", "secretaria.db"),
                    help="arquivo SQLite de origem (padrão: secretaria.db)")
    ap.add_argument("--dry-run", action="store_true", help="só conta as linhas da origem")
    ap.add_argument("--sim", action="store_true", help="confirma a gravação no Supabase")
    args = ap.parse_args()

    origem = abrir_origem(args.origem)
    existentes = tabelas_origem(origem)
    contagem_origem = {t: origem.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                       for t in TABELAS if t in existentes}
    print(f"Origem: {os.path.abspath(args.origem)} (somente leitura)")
    for t, n in contagem_origem.items():
        print(f"  {t:22} {n}")
    if args.dry_run:
        print("\n--dry-run: nada gravado.")
        return 0

    if os.getenv("DB_DRIVER") != "postgresql" or not os.getenv("DATABASE_URL"):
        print("\nConfigure o .env com DB_DRIVER=postgresql e o DATABASE_URL do projeto novo.")
        return 1
    url = urlparse(os.getenv("DATABASE_URL", ""))
    print(f"\nDestino: PostgreSQL em {url.hostname} (usuário {url.username})")
    if not args.sim:
        print("Confira se este é o projeto agentedoctor (e NÃO o da Balbino) e rode com --sim.")
        return 1

    import db
    import database

    database.init_db()
    print("Schema criado/atualizado pelo database.init_db().")

    ocupadas = [t for t in contagem_origem
                if db.fetch_one(f"SELECT COUNT(*) AS n FROM {t}")["n"] > 0]
    if ocupadas:
        print(f"Destino já tem dados em {ocupadas}. Nada foi copiado (evita duplicar).")
        return 1

    for tabela in contagem_origem:
        cols_origem = [r[1] for r in origem.execute(f"PRAGMA table_info({tabela})")]
        cols_destino = db.table_columns(tabela)
        cols = [c for c in cols_origem if c in cols_destino]
        ignoradas = [c for c in cols_origem if c not in cols_destino]
        if ignoradas:
            print(f"  aviso: {tabela}: colunas só na origem, ignoradas: {ignoradas}")

        marcadores = ["?::vector" if (tabela == "knowledge" and c == "embedding") else "?"
                      for c in cols]
        sql = (f"INSERT INTO {tabela} ({', '.join(cols)}) "
               f"VALUES ({', '.join(marcadores)})")
        copiadas = 0
        for linha in origem.execute(f"SELECT {', '.join(cols)} FROM {tabela}"):
            valores = []
            for c in cols:
                v = linha[c]
                if tabela == "knowledge" and c == "embedding" and v:
                    # SQLite guarda o vetor como JSON; pgvector quer '[x,y,...]'.
                    v = "[" + ",".join(str(x) for x in json.loads(v)) + "]"
                valores.append(v if v != "" or c != "embedding" else None)
            db.execute(sql, tuple(valores))
            copiadas += 1

        if "id" in cols:
            db.execute(
                f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {tabela}), 1), "
                f"(SELECT MAX(id) FROM {tabela}) IS NOT NULL)"
            )
        print(f"  {tabela:22} {copiadas} linha(s) copiada(s)")

    print("\nConferência (origem x destino):")
    tudo_ok = True
    for t, n in contagem_origem.items():
        d = db.fetch_one(f"SELECT COUNT(*) AS n FROM {t}")["n"]
        marca = "ok" if d == n else "DIFERENTE"
        tudo_ok &= d == n
        print(f"  {t:22} {n:>6} x {d:<6} {marca}")
    vetores = db.fetch_one("SELECT COUNT(*) AS n FROM knowledge WHERE embedding IS NOT NULL")["n"]
    print(f"  embeddings no destino: {vetores}")
    print("\nMIGRAÇÃO OK" if tudo_ok else "\nATENÇÃO: contagens diferentes")
    return 0 if tudo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
