"""
auth.py — Login/logout simples via sessão Flask.
Usuário/senha definidos em variáveis de ambiente (.env).
"""

import os
from functools import wraps

from flask import session, redirect, url_for, request

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "troque_esta_senha")


def login_required(f):
    """Decorator que redireciona para /login se não autenticado."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


def check_credentials(username: str, password: str) -> bool:
    """Verifica se as credenciais são válidas."""
    return username == ADMIN_USER and password == ADMIN_PASSWORD


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
