"""
ingest_knowledge.py — Sobe a base de conhecimento para o knowledge (RAG).

Gera os chunks por seção e os embeddings (OpenAI) e grava no banco configurado
no .env. O app faz isso sozinho na primeira subida; este script serve para
recarregar depois de editar a base, ou para subir um PDF novo.

Uso:
    python ingest_knowledge.py                 # knowledge/base_conhecimento_dr_fabricio.md
    python ingest_knowledge.py --pdf ARQ.pdf   # extrai o texto de um PDF e sobe
    python ingest_knowledge.py --dry-run       # so mostra os chunks, nao grava

Em PostgreSQL o script pede --sim: e o jeito de ninguem gravar sem querer no
banco de outro projeto.
"""

import argparse
import os
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

BASE = Path(__file__).parent
MD_PADRAO = BASE / "knowledge" / "base_conhecimento_dr_fabricio.md"
DESCRICAO = ("Base de conhecimento oficial do Dr. Fabricio Guimaraes: regras, procedimentos, "
             "triagem, respostas-padrao e fluxo de atendimento")


def destino() -> str:
    driver = os.getenv("DB_DRIVER", "sqlite")
    if driver == "postgresql":
        url = urlparse(os.getenv("DATABASE_URL", ""))
        return f"PostgreSQL em {url.hostname or '?'} (usuario {url.username or '?'})"
    return f"SQLite em {os.path.abspath(os.getenv('DB_PATH', 'whatsapp.db'))}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", help="PDF a extrair e subir (em vez do .md padrao)")
    ap.add_argument("--dry-run", action="store_true", help="so mostra os chunks")
    ap.add_argument("--sim", action="store_true", help="confirma a gravacao em PostgreSQL")
    args = ap.parse_args()

    import knowledge_rag

    if args.pdf:
        import documentos
        caminho = Path(args.pdf)
        conteudo = documentos.pdf_para_texto(caminho.read_bytes())
        nome = caminho.with_suffix(".md").name
    else:
        caminho = MD_PADRAO
        conteudo = caminho.read_text(encoding="utf-8")
        nome = caminho.name

    chunks = knowledge_rag.chunk_text(conteudo)
    print(f"Fonte: {caminho}")
    print(f"Arquivo no knowledge: {nome}  |  {len(conteudo)} chars  |  {len(chunks)} chunks")
    for i, c in enumerate(chunks):
        print(f"  [{i:02d}] {c.splitlines()[0][:70]}  ({len(c)} chars)")

    if args.dry_run:
        print("\n--dry-run: nada gravado.")
        return 0

    print(f"\nDestino: {destino()}")
    if os.getenv("DB_DRIVER", "sqlite") == "postgresql" and not args.sim:
        print("Confira se este e o banco DESTE projeto e rode de novo com --sim.")
        return 1
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY ausente: sem ela nao ha embeddings.")
        return 1

    import database
    database.init_db()
    knowledge_rag.save_knowledge(nome, conteudo, description=DESCRICAO)

    status = database.get_knowledge_file_status(nome)
    com_vetor = sum(1 for c in database.get_knowledge_chunks(nome) if c.get("embedding"))
    print(f"\nOK: {nome} status={status}, {com_vetor}/{len(chunks)} chunks com embedding.")
    teste = "biópsia significa câncer?"
    print(f"\nBusca de teste: {teste!r}")
    print(knowledge_rag.search_context(teste, top_k=2)[:400] + " ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
