"""
documentos.py — Extração de texto de arquivos enviados para o knowledge.

Aceita .pdf, .docx, .md e .txt. O texto sai com uma linha por parágrafo, que é
o que o chunker do knowledge_rag espera (ele nunca corta linha no meio).
"""

from __future__ import annotations

import io
import re


def pdf_para_texto(dados: bytes) -> str:
    """Texto de um PDF, página a página, sem o rodapé repetido de cada página."""
    from pypdf import PdfReader

    leitor = PdfReader(io.BytesIO(dados))
    paginas = [(p.extract_text() or "") for p in leitor.pages]

    # Linha que aparece em quase todas as páginas é cabeçalho/rodapé
    # ("Base de Conhecimento ... Página 3"): repetida, ela vira ruído no RAG.
    contagem: dict[str, int] = {}
    for pag in paginas:
        for linha in {re.sub(r"\d+", "#", l.strip()) for l in pag.splitlines() if l.strip()}:
            contagem[linha] = contagem.get(linha, 0) + 1
    repetidas = {l for l, n in contagem.items() if len(paginas) > 2 and n >= len(paginas) - 1}

    linhas = []
    for pag in paginas:
        for linha in pag.splitlines():
            limpa = linha.strip()
            if limpa and re.sub(r"\d+", "#", limpa) not in repetidas:
                linhas.append(limpa)
    return "\n".join(linhas).strip()


def docx_para_texto(dados: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(dados))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def extrair_texto(nome: str, dados: bytes) -> str:
    nome = (nome or "").lower()
    if nome.endswith(".pdf"):
        return pdf_para_texto(dados)
    if nome.endswith(".docx"):
        return docx_para_texto(dados)
    return dados.decode("utf-8", errors="replace")
