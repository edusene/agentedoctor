"""
auth.py — Login/logout simples via sessão Flask.
Usuário/senha definidos em variáveis de ambiente (.env).
"""

import hmac
import os
from functools import wraps

from flask import session, redirect, url_for, request

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
# Sem senha padrao: o codigo e publico, e uma senha escrita aqui vale para
# qualquer um. Sem ADMIN_PASSWORD (ou com o texto do exemplo) o login fica fechado.
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
if ADMIN_PASSWORD == "troque_esta_senha":
    ADMIN_PASSWORD = ""
if not ADMIN_PASSWORD:
    print("[auth] ERRO: ADMIN_PASSWORD nao definida; login do painel bloqueado")


def login_required(f):
    """Decorator que redireciona para /login se não autenticado."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


def check_credentials(username: str, password: str) -> bool:
    """Verifica se as credenciais são válidas (comparação em tempo constante)."""
    if not ADMIN_PASSWORD:
        return False
    usuario_ok = hmac.compare_digest(username.encode("utf-8"), ADMIN_USER.encode("utf-8"))
    senha_ok = hmac.compare_digest(password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8"))
    return usuario_ok and senha_ok


def do_login(username: str, password: str) -> bool:
    """Tenta fazer login. Retorna True se bem-sucedido."""
    if check_credentials(username, password):
        session["logged_in"] = True
        session["username"] = username
        return True
    return False


def do_logout() -> None:
    """Encerra a sessão."""
    session.pop("logged_in", None)
    session.pop("username", None)
