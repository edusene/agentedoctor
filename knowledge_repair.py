"""
knowledge_repair.py — Conserta textos danificados pelo chunker antigo.

O chunker anterior gravava, dentro de cada chunk, os ultimos 50 caracteres do
chunk anterior — e cortava no meio de palavras e de linhas de tabela. Toda vez
que o texto era remontado e salvo de volta (painel -> .docx/.md), a duplicacao
era assada no arquivo. Resultado: prompt e base de conhecimento cheios de
trechos repetidos e palavras partidas ("em co ntexto", "com e xatamente").

Este modulo desfaz esse estrago:
  1. remove repeticoes adjacentes de trechos longos;
  2. remonta palavras partidas usando o vocabulario do proprio documento.

Usado por reindex_knowledge.py. Nao e chamado em runtime.
"""

import re
from collections import Counter

_WORD_RE = re.compile(r"[0-9A-Za-zÀ-ÿ]+")


def dedupe_adjacent(text: str, min_len: int = 25, max_len: int = 90) -> tuple[str, int]:
    """Remove trechos longos repetidos imediatamente apos si mesmos."""
    out = []
    i = 0
    removed = 0
    n = len(text)
    while i < n:
        hit = 0
        for k in range(max_len, min_len - 1, -1):
            if i - k < 0 or i + k > n:
                continue
            prev = text[i - k:i]
            if not prev.strip():
                continue
            if text[i:i + k] == prev:
                hit = k
                break
            # tolera um separador curto de pontuacao/espaco entre as copias
            for sep in range(1, 4):
                if i + sep + k > n:
                    continue
                gap = text[i:i + sep]
                if gap.strip(" .\n\t-") == "" and text[i + sep:i + sep + k] == prev:
                    hit = sep + k
                    break
            if hit:
                break
        if hit:
            i += hit
            removed += hit
            continue
        out.append(text[i])
        i += 1
    return "".join(out), removed


def _vocabulary(text: str) -> Counter:
    return Counter(w.lower() for w in _WORD_RE.findall(text))


def rejoin_split_words(text: str) -> tuple[str, int]:
    """Remonta palavras partidas por um espaco no ponto de corte do chunk.

    Junta "co ntexto" -> "contexto" somente quando a palavra resultante ja
    aparece no proprio documento e o segundo fragmento, sozinho, nao aparece.
    Sem dicionario externo e sem adivinhacao.
    """
    vocab = _vocabulary(text)
    fixed = 0

    def repl(match: re.Match) -> str:
        nonlocal fixed
        first, second = match.group(1), match.group(2)
        merged = (first + second).lower()
        if vocab.get(merged, 0) >= 1 and vocab.get(second.lower(), 0) <= 1:
            fixed += 1
            return first + second
        return match.group(0)

    # fragmento curto + resto da palavra, no meio da frase (minusculas e MAIUSCULAS)
    lower = re.compile(r"\b([a-zà-ÿ]{1,3}) ([a-zà-ÿ]{3,})\b")
    upper = re.compile(r"\b([A-ZÀ-Þ]{1,3}) ([A-ZÀ-Þ]{3,})\b")
    text = lower.sub(repl, text)
    text = upper.sub(repl, text)
    return text, fixed


def collapse_blank_lines(text: str) -> str:
    """No maximo uma linha em branco entre blocos."""
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def repair(text: str, label: str = "") -> str:
    """Aplica todo o conserto e registra o que mudou."""
    original_len = len(text or "")
    if not original_len:
        return ""

    cleaned, removed1 = dedupe_adjacent(text)
    cleaned, removed2 = dedupe_adjacent(cleaned)  # 2a passada: duplicatas que so ficam adjacentes depois da 1a
    cleaned, rejoined = rejoin_split_words(cleaned)
    cleaned = collapse_blank_lines(cleaned)

    print(
        f"[repair] {label or 'texto'}: {original_len} -> {len(cleaned)} chars "
        f"(duplicado removido={removed1 + removed2}, palavras remontadas={rejoined})"
    )
    return cleaned


def looks_corrupted(text: str) -> bool:
    """Heuristica: ha trechos longos repetidos em sequencia?"""
    if not text:
        return False
    _, removed = dedupe_adjacent(text[:20000])
    return removed > 200
