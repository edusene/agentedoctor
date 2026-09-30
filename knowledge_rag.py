"""
knowledge_rag.py — Knowledge base via RAG no Supabase (pgvector + OpenAI embeddings).
Chunking, embedding e busca semântica para injetar contexto no LLM.
"""

import re
import os
from openai import OpenAI
import database

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

_client = OpenAI(api_key=OPENAI_API_KEY)

# Caches de leitura. Toda escrita no knowledge passa por
# invalidate_knowledge_caches(), que limpa os dois.
_DOC_CACHE: dict[str, str] = {}
_CONTEXT_CACHE: dict[str, str] = {}

# ── Embeddings ───────────────────────────────────────────────────────────────


def embed_text(text: str) -> list[float]:
    """Gera embedding via OpenAI text-embedding-3-small."""
    result = _client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return result.data[0].embedding


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Gera embeddings em lote (mais eficiente para indexação)."""
    result = _client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [e.embedding for e in result.data]


# ── Chunking ─────────────────────────────────────────────────────────────────

# Arquivos que sao INSTRUCOES do agente (prompts), nao dados consultaveis.
# Nunca entram no bloco de knowledge injetado no system prompt.
PROMPT_FILES = {"secretaria.md"}


def is_prompt_file(filename: str) -> bool:
    """True para arquivos de prompt (instrucoes), False para dados."""
    return (filename or "").strip() in PROMPT_FILES


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return True
    if stripped.startswith("===") and stripped.endswith("==="):
        return True
    return False


def chunk_text(text: str, max_len: int = 900, overlap_lines: int = 1) -> list[str]:
    """Divide o texto em chunks SEM cortar linhas no meio.

    Regras:
    - nunca parte uma linha (linhas = registros de tabela, itens de lista);
    - cada chunk carrega o cabecalho de secao vigente, para continuar
      legivel quando recuperado isolado pela busca vetorial;
    - a sobreposicao e feita por LINHAS inteiras, nunca por fatia de caracteres.

    O conteudo salvo aqui e usado apenas para BUSCA. O texto oficial do
    arquivo fica em knowledge_files.content (ver database.set_knowledge_document).
    """
    text = (text or "").strip()
    if not text:
        return []

    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    heading = ""

    def flush():
        nonlocal current, current_len
        if not current:
            return
        body = "\n".join(current).strip()
        if body:
            if heading and not body.startswith(heading):
                chunks.append(f"{heading}\n{body}")
            else:
                chunks.append(body)
        current = []
        current_len = 0

    for line in lines:
        if _is_heading(line):
            flush()
            heading = line.strip()
            current = [line]
            current_len = len(line)
            continue

        line_len = len(line) + 1
        if current_len + line_len > max_len and current:
            tail = [ln for ln in current[-overlap_lines:] if ln.strip()] if overlap_lines > 0 else []
            flush()
            current = list(tail)
            current_len = sum(len(ln) + 1 for ln in current)

        current.append(line)
        current_len += line_len

    flush()

    # Descarta chunks sem conteudo util (so cabecalho ou lixo curto)
    result = [c for c in chunks if len(c.strip()) >= 12]
    return result or [text[:max_len]]


# ── Knowledge CRUD ───────────────────────────────────────────────────────────


class ConteudoCorrompido(ValueError):
    """Conteudo com a assinatura do chunker antigo (sobreposicao de 50 chars)."""


# Trecho longo repetido 3x ou mais em sequencia na mesma linha. E a marca que o
# chunker antigo deixava ao remontar o texto a partir de chunks sobrepostos.
# Prosa normal nao repete 25+ caracteres tres vezes seguidas.
_ASSINATURA_OVERLAP = re.compile(r"(.{25,}?)\1{2,}")


def detectar_corrupcao(content: str) -> str:
    """Descreve a corrupcao encontrada no texto, ou "" se estiver limpo.

    O prompt operacional foi destruido uma vez assim: o conteudo remontado dos
    chunks foi salvo de volta por cima do original, e cada edicao seguinte pela
    aba Knowledge amplificou o estrago. Salvar e o ponto onde da para barrar.
    """
    linhas_ruins = []
    for n, linha in enumerate((content or "").split("\n"), start=1):
        m = _ASSINATURA_OVERLAP.search(linha)
        if m:
            linhas_ruins.append((n, m.group(1).strip()[:60]))
    if not linhas_ruins:
        return ""
    amostra = "; ".join(f"linha {n}: ...{t}..." for n, t in linhas_ruins[:3])
    return (
        f"{len(linhas_ruins)} linha(s) com trecho repetido em sequencia "
        f"({amostra}). Isso e sinal de texto remontado dos chunks do RAG, nao "
        f"de conteudo real - salvar assim apagaria o original."
    )


def save_knowledge(filename: str, content: str, description: str = "") -> None:
    """Salva knowledge no banco: deleta antigo, chunka, embeda, insere."""
    content = (content or "").strip()
    if not content:
        return

    problema = detectar_corrupcao(content)
    if problema:
        raise ConteudoCorrompido(f"{filename}: {problema}")

    # Deleta chunks anteriores deste arquivo
    database.delete_knowledge_file(filename)

    chunks = chunk_text(content)
    if not chunks:
        return

    # Gera embeddings em lote
    try:
        embeddings = embed_batch(chunks)
    except Exception as e:
        print(f"[rag] ERRO embedding {filename}: {e}")
        # Fallback: salva sem embedding (busca por LIKE ainda funciona)
        embeddings = [None] * len(chunks)

    # Insere no banco
    database.insert_knowledge_chunks(filename, chunks, embeddings)

    # Texto ORIGINAL: fonte da verdade lida pelo agente (chunks sao so busca)
    database.set_knowledge_document(filename, content, description, status="indexed")

    invalidate_knowledge_caches()
    print(f"[rag] salvo {filename}: {len(chunks)} chunks")


def _format_search_results(results: list[dict], query: str) -> str:
    """Formata os trechos recuperados, cada um rotulado com o arquivo de origem.

    Quando os trechos recuperados de um arquivo forem pequenos demais para
    responder com segurança (tabelas cortadas, por exemplo), devolve o arquivo
    inteiro daquele arquivo — e só dele, nunca de todos.
    """
    if not results:
        return ""

    by_file: dict[str, list[str]] = {}
    for result in results:
        filename = result.get("filename", "")
        content = (result.get("content") or "").strip()
        if not content:
            continue
        by_file.setdefault(filename, []).append(content)

    blocks = []
    for filename, contents in by_file.items():
        joined = ("\n\n").join(contents)
        full = get_file_content(filename)
        # Se o arquivo inteiro e pequeno, ou se os trechos cobrem quase tudo,
        # vale mais entregar o documento completo do que fragmentos.
        if full and (len(full) <= 4000 or len(joined) >= 0.6 * len(full)):
            blocks.append(f"[{filename}]" + "\n" + full)
        else:
            blocks.append(f"[{filename}]" + "\n" + joined)

    return ("\n\n---\n\n").join(blocks)


def search_context(query: str, top_k: int = 3) -> str:
    """Busca os chunks mais relevantes para a query do usuario.
    Retorna texto concatenado com labels de arquivo para injetar no system prompt.
    Se embedding falhar, retorna os chunks mais recentes como fallback.
    """
    if not query or not query.strip():
        return ""

    # Tenta busca vetorial
    try:
        query_embedding = embed_text(query)
        results = database.search_knowledge(query_embedding, top_k=top_k, query_text=query)
        if results:
            joined = _format_search_results(results, query)
            print(f"[rag] search vectorial query_len={len(query)} results={len(results)} context_len={len(joined)}")
            return joined
    except Exception as e:
        print(f"[rag] WARN busca vetorial falhou: {e}")

    # Fallback: busca textual por palavras-chave no banco
    try:
        results = database.search_knowledge([], top_k=top_k, query_text=query)
        if results:
            joined = _format_search_results(results, query)
            print(f"[rag] search fallback query_len={len(query)} results={len(results)} context_len={len(joined)}")
            return joined
    except Exception as e:
        print(f"[rag] WARN fallback falhou: {e}")

    return ""


def list_files() -> list[dict]:
    """Lista arquivos de knowledge no banco (filename + chunks + descrição)."""
    return database.list_knowledge_files()


def get_file(filename: str) -> dict | None:
    """Retorna o conteúdo completo de um arquivo + descrição."""
    content = get_file_content(filename)
    if not content:
        return None
    description = database.get_knowledge_file_description(filename)
    return {"filename": filename, "content": content, "description": description}


def delete_file(filename: str) -> None:
    """Deleta todos os chunks de um arquivo e sua descrição."""
    database.delete_knowledge_file(filename)
    invalidate_knowledge_caches()
    print(f"[rag] deletado {filename}")


# ── Smart Knowledge (tool call support) ──────────────────────────────────────

def get_file_descriptions() -> list[dict]:
    """Retorna índice compacto de arquivos + descrições para injetar no system prompt."""
    return database.get_all_knowledge_descriptions()


def get_file_content(filename: str) -> str:
    """Retorna o conteúdo completo e FIEL de um arquivo.

    Prioriza o documento original guardado em knowledge_files.content. Só cai
    para a remontagem dos chunks em bases antigas — essa remontagem é
    aproximada; rode ingest_knowledge.py.
    """
    filename = (filename or "").strip()
    if not filename:
        return ""

    cached = _DOC_CACHE.get(filename)
    if cached is not None:
        return cached

    content = ""
    try:
        content = database.get_knowledge_document(filename)
    except Exception as e:
        print(f"[rag] WARN documento original indisponivel ({filename}): {e}")

    if not content:
        chunks = database.get_knowledge_chunks(filename)
        if not chunks:
            return ""
        chunks.sort(key=lambda c: c["chunk_index"])
        content = "\n".join(c["content"] for c in chunks)
        print(f"[rag] AVISO: {filename} sem documento original - remontado dos chunks (rode ingest_knowledge.py)")

    _DOC_CACHE[filename] = content
    return content


def invalidate_knowledge_caches():
    """Invalida caches que dependem do conteudo atualizado do knowledge."""
    _DOC_CACHE.clear()
    _CONTEXT_CACHE.clear()


def get_full_knowledge_content(include_prompts: bool = False) -> str:
    """Retorna o conteúdo dos arquivos de knowledge, pronto para o system prompt.

    Por padrão devolve só os arquivos de DADOS (a base do consultório e o que
    mais for enviado pelo painel). O prompt da secretária fica de fora: ele já
    vai no início do system prompt, e repeti-lo aqui duplicaria instruções.
    """
    cache_key = "all" if include_prompts else "dados"
    cached = _CONTEXT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    docs = database.get_all_knowledge_documents()
    parts = []
    used = []

    if docs:
        for doc in docs:
            filename = doc.get("filename", "")
            if not include_prompts and is_prompt_file(filename):
                continue
            content = (doc.get("content") or "").strip()
            if not content:
                continue
            used.append(filename)
            parts.append(f"=== {filename} ==="  + "\n\n" + content)
    else:
        # Base antiga (sem documento original): remonta pelos chunks
        chunks = database.get_all_knowledge_content()
        current_file = None
        buf = []
        for c in chunks:
            if c["filename"] != current_file:
                if buf and current_file and (include_prompts or not is_prompt_file(current_file)):
                    used.append(current_file)
                    parts.append(f"=== {current_file} ==="  + "\n\n" + "\n".join(buf))
                current_file = c["filename"]
                buf = []
            buf.append(c["content"])
        if buf and current_file and (include_prompts or not is_prompt_file(current_file)):
            used.append(current_file)
            parts.append(f"=== {current_file} ==="  + "\n\n" + "\n".join(buf))

    result = ("\n\n").join(parts)
    _CONTEXT_CACHE[cache_key] = result
    print(f"[rag] knowledge context: {len(result)} chars, arquivos={used}")
    return result


# ── Knowledge Batch Operations ────────────────────────────────────────────────


def _mesmo_texto(a: str, b: str) -> bool:
    """Iguais a menos de quebra de linha Windows e espaco nas pontas.

    O textarea do painel devolve as quebras de linha sempre no formato Unix.
    """
    return ("\n".join((a or "").splitlines()).strip()
            == "\n".join((b or "").splitlines()).strip())


def save_knowledge_raw(filename: str, content: str, description: str = "",
                       forcar: bool = False) -> bool:
    """Salva knowledge SEM embeddings (status=pending). Para upload em lote.

    Devolve False quando o texto e o mesmo que ja esta salvo: nesse caso os
    chunks e os embeddings ficam, e so a descricao e atualizada. Sem isso,
    apertar Salvar no painel sem mudar nada apagava os embeddings e o arquivo
    voltava a "pendente". `forcar` refaz os chunks mesmo assim.
    """
    content = (content or "").strip()
    if not content:
        return False

    problema = detectar_corrupcao(content)
    if problema:
        raise ConteudoCorrompido(f"{filename}: {problema}")

    if not forcar and _mesmo_texto(database.get_knowledge_document(filename), content):
        status = database.get_knowledge_file_status(filename) or "pending"
        database.set_knowledge_document(filename, content, description, status=status)
        invalidate_knowledge_caches()
        print(f"[rag] {filename}: texto sem mudanca, embeddings mantidos ({status})")
        return False

    database.delete_knowledge_file(filename)

    chunks = chunk_text(content)
    if not chunks:
        return False

    database.insert_knowledge_chunks(filename, chunks, [None] * len(chunks))
    database.set_knowledge_document(filename, content, description, status="pending")
    invalidate_knowledge_caches()
    print(f"[rag] salvo (raw) {filename}: {len(chunks)} chunks (pendente de embedding)")
    return True


def embed_pending_files() -> dict:
    """Processa todos os arquivos com status='pending': gera embeddings e atualiza status.
    Retorna {processed: int, errors: int, files: list[str]}.
    """
    pending = database.get_pending_knowledge_files()
    if not pending:
        return {"processed": 0, "errors": 0, "files": []}

    processed = 0
    errors = 0
    processed_files = []

    for file_info in pending:
        filename = file_info["filename"]
        try:
            chunks = database.get_knowledge_chunks(filename)
            if not chunks:
                database.update_knowledge_file_status(filename, "error")
                errors += 1
                continue

            chunks.sort(key=lambda c: c["chunk_index"])
            texts = [c["content"] for c in chunks]

            try:
                embeddings = embed_batch(texts)
            except Exception as e:
                print(f"[rag] ERRO embedding {filename}: {e}")
                database.update_knowledge_file_status(filename, "error")
                errors += 1
                continue

            database.delete_knowledge_chunks_by_filename(filename)
            database.insert_knowledge_chunks(filename, texts, embeddings)
            database.update_knowledge_file_status(filename, "indexed")
            processed += 1
            processed_files.append(filename)
            print(f"[rag] embedado {filename}: {len(chunks)} chunks")

        except Exception as e:
            print(f"[rag] ERRO processando {filename}: {e}")
            database.update_knowledge_file_status(filename, "error")
            errors += 1

    return {"processed": processed, "errors": errors, "files": processed_files}


def clear_all_embeddings() -> int:
    """Remove todos os embeddings, mantém conteúdo e marca como pending."""
    count = database.clear_knowledge_embeddings()
    database.set_all_knowledge_pending()
    print(f"[rag] embeddings limpos: {count} chunks marcados como pending")
    return count


def delete_all() -> int:
    """Deleta todo o knowledge (chunks + metadados)."""
    count = database.delete_all_knowledge()
    invalidate_knowledge_caches()
    print(f"[rag] todo knowledge deletado: {count} arquivos")
    return count


def list_files_with_status() -> list[dict]:
    """Lista arquivos com status (pending/indexed/error)."""
    return database.list_knowledge_files_with_status()
