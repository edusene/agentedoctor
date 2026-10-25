"""
verify.py — Verificacao local e do CI: sintaxe, pyflakes, segredos e testes.

    python verify.py            # tudo
    python verify.py --testes   # so os testes (com a trava contra producao)

Nao publica, nao abre rede e nao toca no Supabase: os testes rodam num SQLite
temporario. Ver docs/quality.md.
"""

import compileall
import os
import re
import subprocess
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.abspath(__file__))

# Segredos que nunca podem ir para o repositorio publico.
PADROES_SEGREDO = {
    "chave OpenAI": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    "token Datafy/Stripe": re.compile(r"\bsk_live_[A-Za-z0-9]{8,}"),
    "segredo de webhook": re.compile(r"\bwhsec_[A-Za-z0-9]{8,}"),
    "chave privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "URL de banco com senha": re.compile(r"postgres(?:ql)?://[^\s:@/]+:(?![<*]|SUA_SENHA|SENHA)[^\s@/]{6,}@"),
    "token do Google": re.compile(r"\bya29\.[A-Za-z0-9_\-]{20,}"),
}
ARQUIVOS_IGNORADOS = {"verify.py", "test_verify.py"}


def achar_segredos(texto: str) -> list[str]:
    return [nome for nome, rx in PADROES_SEGREDO.items() if rx.search(texto)]


def arquivos_versionados() -> list[str]:
    saida = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True)
    return [f for f in saida.stdout.splitlines() if f not in ARQUIVOS_IGNORADOS]


def checar_segredos() -> int:
    achados = 0
    for rel in arquivos_versionados():
        if rel.lower().endswith((".ico", ".pdf", ".png", ".jpg", ".jpeg")):
            continue
        try:
            with open(os.path.join(RAIZ, rel), encoding="utf-8", errors="ignore") as f:
                texto = f.read()
        except OSError:
            continue
        for nome in achar_segredos(texto):
            print(f"  SEGREDO? {rel}: {nome}")
            achados += 1
    return achados


def rodar_testes() -> int:
    """Trava contra producao (ver docs/quality.md): app/db carregam o .env no
    import com override e mandariam o teste para o Supabase real."""
    import dotenv
    dotenv.load_dotenv = lambda *a, **k: False
    for chave in ("DATABASE_URL", "DATAFY_TOKEN", "DATAFY_WEBHOOK_SECRET",
                  "WHATSAPI_KEY", "WHATSAPI_WEBHOOK_SECRET", "WHATSAPI_PHONE_NUMBER_ID"):
        os.environ.pop(chave, None)
    os.environ["OPENAI_API_KEY"] = "sk-teste-falsa"
    os.environ["DB_DRIVER"] = "sqlite"
    os.environ["VERIFY_TESTES"] = "1"
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:9"  # nada sai: conexao recusada
    os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "teste.db")
    sys.path.insert(0, RAIZ)
    import db
    if db.DB_DRIVER != "sqlite":
        print("ABORTADO: db.DB_DRIVER nao e sqlite; teste nao pode tocar o banco real")
        return 2
    suite = unittest.defaultTestLoader.discover(RAIZ, pattern="test_*.py")
    return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1


def passo(nome: str, ok: bool) -> bool:
    print(f"[{'ok' if ok else 'FALHOU'}] {nome}")
    return ok


def main() -> int:
    if "--testes" in sys.argv:
        return rodar_testes()
    py = sys.executable
    ok = passo("sintaxe (compileall)", compileall.compile_dir(RAIZ, quiet=1, maxlevels=1, rx=re.compile(r"\.venv")))
    flakes = subprocess.run([py, "-m", "pyflakes", *sorted(f for f in os.listdir(RAIZ) if f.endswith(".py"))], cwd=RAIZ)
    ok &= passo("pyflakes (pip install -r requirements-dev.txt)", flakes.returncode == 0)
    ok &= passo("segredos nos arquivos versionados", checar_segredos() == 0)
    testes = subprocess.run([py, os.path.join(RAIZ, "verify.py"), "--testes"], cwd=RAIZ)
    ok &= passo("testes (SQLite temporario, sem rede)", testes.returncode == 0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
