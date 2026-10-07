"""
google_agenda.py — Sincronização opcional da Agenda do painel com o Google Calendar.

Sem conexão, a agenda funciona só no painel: nada aqui é obrigatório. Com
conexão, cada agendamento confirmado vira um evento no calendário do
consultório, e reagendar/cancelar no painel atualiza/apaga o evento.

Conexão por OAuth 2.0 (fluxo web), só com `requests` — sem dependência nova:
1. No Google Cloud Console, crie um "ID do cliente OAuth" do tipo "Aplicativo
   da Web" e cadastre como URI de redirecionamento:
       https://SEU-DOMINIO/api/google/callback
2. No Render (variáveis de ambiente): GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET.
   Opcionais: GOOGLE_REDIRECT_URI (se o domínio não puder ser deduzido) e
   GOOGLE_CALENDAR_ID (padrão: "primary", o calendário principal da conta).
3. No painel, aba Agenda → "Conectar Google Calendar".

O refresh token fica na tabela settings (nunca no código nem no git).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests

import database

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_API = "https://www.googleapis.com/calendar/v3"
_SCOPES = "https://www.googleapis.com/auth/calendar.events openid email"

_token_cache: dict = {"access_token": "", "expira_em": 0.0}


def _cfg(nome: str, padrao: str = "") -> str:
    return (os.getenv(nome, "") or padrao).strip()


def configurado() -> bool:
    """As credenciais do app Google estão no ambiente?"""
    return bool(_cfg("GOOGLE_CLIENT_ID") and _cfg("GOOGLE_CLIENT_SECRET"))


def conectado() -> bool:
    return configurado() and bool(database.get_setting("google_refresh_token", ""))


def status() -> dict:
    return {
        "configurado": configurado(),
        "conectado": conectado(),
        "email": database.get_setting("google_email", "") if conectado() else "",
        "calendario": _cfg("GOOGLE_CALENDAR_ID", "primary"),
    }


def redirect_uri(host_url: str = "") -> str:
    return _cfg("GOOGLE_REDIRECT_URI") or f"{host_url.rstrip('/')}/api/google/callback"


def url_autorizacao(state: str, redirect: str) -> str:
    return _AUTH_URL + "?" + urlencode({
        "client_id": _cfg("GOOGLE_CLIENT_ID"),
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": _SCOPES,
        "access_type": "offline",   # devolve o refresh token
        "prompt": "consent",        # garante o refresh token mesmo em reconexão
        "include_granted_scopes": "true",
        "state": state,
    })


def trocar_codigo(code: str, redirect: str) -> None:
    """Troca o código do callback pelos tokens e guarda o refresh token."""
    r = requests.post(_TOKEN_URL, data={
        "code": code,
        "client_id": _cfg("GOOGLE_CLIENT_ID"),
        "client_secret": _cfg("GOOGLE_CLIENT_SECRET"),
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }, timeout=20)
    dados = r.json() if r.content else {}
    if r.status_code != 200 or not dados.get("access_token"):
        raise RuntimeError(f"Google recusou a conexão: {dados.get('error_description') or dados.get('error') or r.status_code}")
    if dados.get("refresh_token"):
        database.set_setting("google_refresh_token", dados["refresh_token"])
    _token_cache.update(access_token=dados["access_token"],
                        expira_em=time.time() + int(dados.get("expires_in", 3600)) - 60)
    try:
        info = requests.get("https://openidconnect.googleapis.com/v1/userinfo",
                            headers={"Authorization": f"Bearer {dados['access_token']}"}, timeout=10).json()
        database.set_setting("google_email", info.get("email", ""))
    except Exception:
        pass


def desconectar() -> None:
    token = database.get_setting("google_refresh_token", "")
    if token:
        try:
            requests.post(_REVOKE_URL, params={"token": token}, timeout=10)
        except Exception as e:
            print(f"[google] WARN ao revogar token: {e}")
    database.set_setting("google_refresh_token", "")
    database.set_setting("google_email", "")
    _token_cache.update(access_token="", expira_em=0.0)


def _access_token() -> str:
    if _token_cache["access_token"] and time.time() < _token_cache["expira_em"]:
        return _token_cache["access_token"]
    refresh = database.get_setting("google_refresh_token", "")
    if not refresh:
        raise RuntimeError("Google Calendar não conectado")
    r = requests.post(_TOKEN_URL, data={
        "client_id": _cfg("GOOGLE_CLIENT_ID"),
        "client_secret": _cfg("GOOGLE_CLIENT_SECRET"),
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    }, timeout=20)
    dados = r.json() if r.content else {}
    if r.status_code != 200 or not dados.get("access_token"):
        if dados.get("error") == "invalid_grant":
            # Acesso revogado na conta Google: deixa de tentar até reconectar.
            database.set_setting("google_refresh_token", "")
        raise RuntimeError(f"Falha ao renovar acesso ao Google: {dados.get('error') or r.status_code}")
    _token_cache.update(access_token=dados["access_token"],
                        expira_em=time.time() + int(dados.get("expires_in", 3600)) - 60)
    return dados["access_token"]


def _offset() -> str:
    try:
        horas = float(os.getenv("TZ_OFFSET_HORAS", "-3"))
    except ValueError:
        horas = -3.0
    sinal = "-" if horas < 0 else "+"
    h = abs(horas)
    return f"{sinal}{int(h):02d}:{int(round((h - int(h)) * 60)):02d}"


def _corpo_evento(ag: dict) -> dict:
    inicio = datetime.fromisoformat(ag["inicio"])
    fim = inicio + timedelta(minutes=int(ag.get("duracao_min") or 60))
    descricao = "\n".join(p for p in (
        f"Paciente: {ag.get('nome') or '-'}",
        f"WhatsApp: {ag.get('phone') or '-'}",
        "",
        ag.get("resumo") or "",
        f"\nObservações: {ag['observacoes']}" if ag.get("observacoes") else "",
    ) if p is not None)
    corpo = {
        "summary": f"Avaliação - {ag.get('nome') or ag.get('phone')}",
        "description": descricao.strip(),
        "start": {"dateTime": inicio.strftime("%Y-%m-%dT%H:%M:00") + _offset()},
        "end": {"dateTime": fim.strftime("%Y-%m-%dT%H:%M:00") + _offset()},
    }
    endereco = _cfg("CLINICA_ENDERECO")
    if endereco:
        corpo["location"] = endereco
    return corpo


def _calendario() -> str:
    return requests.utils.quote(_cfg("GOOGLE_CALENDAR_ID", "primary"), safe="")


def salvar_evento(ag: dict) -> str:
    """Cria ou atualiza o evento do agendamento. Devolve o id do evento."""
    headers = {"Authorization": f"Bearer {_access_token()}"}
    corpo = _corpo_evento(ag)
    if ag.get("google_event_id"):
        r = requests.patch(f"{_API}/calendars/{_calendario()}/events/{ag['google_event_id']}",
                           json=corpo, headers=headers, timeout=20)
        if r.status_code == 200:
            return ag["google_event_id"]
        if r.status_code not in (404, 410):
            raise RuntimeError(f"Google Calendar: {r.status_code} {r.text[:150]}")
        # Evento apagado direto no Google: recria.
    r = requests.post(f"{_API}/calendars/{_calendario()}/events", json=corpo,
                      headers=headers, timeout=20)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Google Calendar: {r.status_code} {r.text[:150]}")
    return r.json().get("id", "")


def apagar_evento(event_id: str) -> None:
    if not event_id:
        return
    r = requests.delete(f"{_API}/calendars/{_calendario()}/events/{event_id}",
                        headers={"Authorization": f"Bearer {_access_token()}"}, timeout=20)
    if r.status_code not in (200, 204, 404, 410):
        raise RuntimeError(f"Google Calendar: {r.status_code} {r.text[:150]}")
