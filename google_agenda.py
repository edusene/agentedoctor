"""
google_agenda.py — Sincronização opcional da Agenda do painel com o Google Calendar.

Sem conexão, a agenda funciona só no painel: nada aqui é obrigatório. Com
conexão, cada agendamento confirmado vira um evento no calendário do
consultório, e reagendar/cancelar no painel atualiza/apaga o evento. No
sentido contrário, o que for marcado direto no Google aparece na Agenda do
painel (só leitura) e conta no alerta de conflito de horário. O Google avisa o
painel quando a agenda muda (push), e a tela se atualiza sozinha.

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

import hmac
import os
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests

import database

_PREFIXO_CIFRA = "enc1:"


def _fernet():
    """Chave derivada da SECRET_KEY. Sem a chave ou sem a biblioteca, o token fica como antes (texto)."""
    chave = os.getenv("SECRET_KEY", "")
    if chave in ("", "troque_esta_chave_secreta_aleatoria"):
        return None
    try:
        import base64
        import hashlib
        from cryptography.fernet import Fernet
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(chave.encode("utf-8")).digest()))
    except ImportError:
        return None


def _guardar_token(token: str) -> None:
    f = _fernet() if token else None
    if token and not f:
        print("[google] AVISO: SECRET_KEY invalida ou 'cryptography' ausente; token guardado sem cifra")
    database.set_setting("google_refresh_token",
                         _PREFIXO_CIFRA + f.encrypt(token.encode("utf-8")).decode() if f else token)


def _ler_token() -> str:
    valor = database.get_setting("google_refresh_token", "")
    if not valor.startswith(_PREFIXO_CIFRA):
        if valor and _fernet():
            _guardar_token(valor)  # token antigo em texto: cifra na primeira leitura
        return valor
    f = _fernet()
    try:
        return f.decrypt(valor[len(_PREFIXO_CIFRA):].encode("utf-8")).decode("utf-8") if f else ""
    except Exception:
        return ""  # SECRET_KEY trocada: reconectar o Google

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
    return configurado() and bool(_ler_token())


def status() -> dict:
    ligado = conectado()
    return {
        "configurado": configurado(),
        "conectado": ligado,
        "email": database.get_setting("google_email", "") if ligado else "",
        "calendario": _cfg("GOOGLE_CALENDAR_ID", "primary"),
        "atualizacao": diagnostico() if ligado else {},
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
        _guardar_token(dados["refresh_token"])
    _token_cache.update(access_token=dados["access_token"],
                        expira_em=time.time() + int(dados.get("expires_in", 3600)) - 60)
    try:
        info = requests.get("https://openidconnect.googleapis.com/v1/userinfo",
                            headers={"Authorization": f"Bearer {dados['access_token']}"}, timeout=10).json()
        database.set_setting("google_email", info.get("email", ""))
    except Exception:
        pass


def desconectar() -> None:
    parar_avisos()
    token = _ler_token()
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
    refresh = _ler_token()
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
            limpar_cache()
            return ag["google_event_id"]
        if r.status_code not in (404, 410):
            raise RuntimeError(f"Google Calendar: {r.status_code} {r.text[:150]}")
        # Evento apagado direto no Google: recria.
    r = requests.post(f"{_API}/calendars/{_calendario()}/events", json=corpo,
                      headers=headers, timeout=20)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Google Calendar: {r.status_code} {r.text[:150]}")
    limpar_cache()
    return r.json().get("id", "")


def apagar_evento(event_id: str) -> None:
    if not event_id:
        return
    r = requests.delete(f"{_API}/calendars/{_calendario()}/events/{event_id}",
                        headers={"Authorization": f"Bearer {_access_token()}"}, timeout=20)
    if r.status_code not in (200, 204, 404, 410):
        raise RuntimeError(f"Google Calendar: {r.status_code} {r.text[:150]}")
    with _janela_lock:
        if _JANELA["eventos"] is not None:
            _JANELA["eventos"] = [e for e in _JANELA["eventos"] if e["id"] != event_id]
    limpar_cache()


# ── Leitura: o que foi marcado direto no Google aparece no painel ────────────
# Cache curto por período: a grade pede o mês e os vizinhos a cada clique, e a
# agenda do consultório não muda a cada segundo. Gravar ou apagar pelo painel
# limpa o cache.
_CACHE_SEG = 60.0
_cache_eventos: dict[tuple, tuple[float, list]] = {}


def _horas_offset() -> float:
    try:
        return float(os.getenv("TZ_OFFSET_HORAS", "-3"))
    except ValueError:
        return -3.0


def _para_local(valor: str) -> datetime:
    """'2026-10-09T10:00:00-03:00' (ou 'Z') -> datetime local sem fuso."""
    from datetime import timezone
    dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone(timedelta(hours=_horas_offset()))).replace(tzinfo=None)


def _evento_do_google(ev: dict) -> dict | None:
    ini, fim = ev.get("start") or {}, ev.get("end") or {}
    if ini.get("dateTime"):
        inicio = _para_local(ini["dateTime"])
        termino = _para_local(fim["dateTime"]) if fim.get("dateTime") else inicio + timedelta(hours=1)
        dia_inteiro = False
    elif ini.get("date"):
        inicio = datetime.fromisoformat(ini["date"])
        termino = datetime.fromisoformat(fim["date"]) if fim.get("date") else inicio + timedelta(days=1)
        dia_inteiro = True
    else:
        return None
    return {
        "id": ev.get("id", ""),
        "titulo": ev.get("summary") or "(sem título)",
        "inicio": inicio.strftime("%Y-%m-%dT%H:%M"),
        "fim": termino.strftime("%Y-%m-%dT%H:%M"),
        "duracao_min": max(1, int((termino - inicio).total_seconds() // 60)),
        "dia_inteiro": dia_inteiro,
        "descricao": (ev.get("description") or "")[:2000],
        "local": ev.get("location") or "",
        "link": ev.get("htmlLink") or "",
        # "Livre" no Google (transparent) não ocupa o horário.
        "ocupa": ev.get("transparency") != "transparent",
    }


def listar_eventos(de: str, ate: str, ignorar: set | None = None) -> list[dict]:
    """Eventos do calendário entre as datas (YYYY-MM-DD, `ate` exclusivo).

    `ignorar`: ids de evento que o próprio painel criou (os agendamentos) -
    esses já aparecem na grade como agendamento e não podem vir em dobro.
    """
    if not conectado():
        return []
    chave = (de, ate)
    guardado = _cache_eventos.get(chave)
    if guardado and time.time() - guardado[0] < _CACHE_SEG:
        eventos = guardado[1]
    else:
        params = {
            "timeMin": f"{de}T00:00:00{_offset()}",
            "timeMax": f"{ate}T00:00:00{_offset()}",
            "singleEvents": "true",      # repetições viram ocorrências
            "orderBy": "startTime",
            "maxResults": "500",
        }
        r = requests.get(f"{_API}/calendars/{_calendario()}/events", params=params,
                         headers={"Authorization": f"Bearer {_access_token()}"}, timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"Google Calendar: {r.status_code} {r.text[:150]}")
        eventos = [e for e in (_evento_do_google(ev) for ev in r.json().get("items") or []
                               if ev.get("status") != "cancelled") if e]
        _cache_eventos[chave] = (time.time(), eventos)
    ignorar = ignorar or set()
    return [e for e in eventos if e["id"] not in ignorar]


def limpar_cache() -> None:
    _cache_eventos.clear()


def conflitos(inicio: str, duracao_min: int, ignorar: set | None = None) -> list[dict]:
    """Eventos do Google que ocupam o horário pedido, no formato dos conflitos do banco."""
    ini = datetime.fromisoformat(inicio)
    fim = ini + timedelta(minutes=duracao_min)
    dia = ini.strftime("%Y-%m-%d")
    seguinte = (ini + timedelta(days=1)).strftime("%Y-%m-%d")
    saida = []
    for e in eventos_do_periodo(dia, seguinte, ignorar):
        if e["dia_inteiro"] or not e["ocupa"]:
            continue
        e_ini, e_fim = datetime.fromisoformat(e["inicio"]), datetime.fromisoformat(e["fim"])
        if e_ini < fim and ini < e_fim:
            saida.append({"id": 0, "nome": f"{e['titulo']} (Google Agenda)",
                          "inicio": e["inicio"], "duracao_min": e["duracao_min"]})
    return saida



# ── Avisos do Google (push): mudança na agenda aparece no painel na hora ─────
# O Google chama POST /api/google/notificacao quando algo muda no calendário.
# O canal vale até 7 dias e é renovado pelo agendador antes de vencer. Se um
# aviso se perder, houve_mudanca() é a rede de segurança (checagem curta).
_CANAL_TTL_SEG = 7 * 24 * 3600
_RENOVAR_ANTES_SEG = 24 * 3600


def base_publica(host_url: str = "") -> str:
    """https://dominio/ do painel. O Render informa em RENDER_EXTERNAL_URL."""
    base = (_cfg("GOOGLE_WEBHOOK_BASE") or _cfg("RENDER_EXTERNAL_URL")
            or database.get_setting("google_base_url", "") or host_url)
    return base.rstrip("/") + "/" if base else ""


def iniciar_avisos(host_url: str = "") -> bool:
    """Abre o canal de avisos. False (sem erro) quando não há endereço https."""
    import secrets
    import uuid
    base = base_publica(host_url)
    if not base.startswith("https://"):
        _DIAG["avisos_erro"] = f"sem endereço https público ({base or 'nenhum'})"
        print(f"[google] avisos desligados: o Google so avisa endereco https ({base or 'sem endereco'})")
        return False
    if host_url.startswith("https://"):
        database.set_setting("google_base_url", host_url.rstrip("/") + "/")
    parar_avisos()
    token = secrets.token_urlsafe(24)
    r = requests.post(f"{_API}/calendars/{_calendario()}/events/watch", json={
        "id": str(uuid.uuid4()),
        "type": "web_hook",
        "address": f"{base}api/google/notificacao",
        "token": token,
        "params": {"ttl": str(_CANAL_TTL_SEG)},
    }, headers={"Authorization": f"Bearer {_access_token()}"}, timeout=20)
    if r.status_code != 200:
        _DIAG["avisos_erro"] = f"Google recusou ({r.status_code}): {r.text[:160]}"
        raise RuntimeError(f"Google recusou os avisos: {r.status_code} {r.text[:200]}")
    _DIAG["avisos_erro"] = ""
    dados = r.json()
    database.set_setting("google_canal_id", dados.get("id", ""))
    database.set_setting("google_canal_recurso", dados.get("resourceId", ""))
    database.set_setting("google_canal_token", token)
    database.set_setting("google_canal_expira", str(int(dados.get("expiration") or 0) // 1000))
    print(f"[google] avisos ligados ate {dados.get('expiration')}")
    return True


def parar_avisos() -> None:
    canal = database.get_setting("google_canal_id", "")
    recurso = database.get_setting("google_canal_recurso", "")
    if canal and recurso:
        try:
            requests.post(f"{_API}/channels/stop", json={"id": canal, "resourceId": recurso},
                          headers={"Authorization": f"Bearer {_access_token()}"}, timeout=15)
        except Exception as e:
            print(f"[google] WARN ao parar os avisos: {e}")
    for chave in ("google_canal_id", "google_canal_recurso", "google_canal_token", "google_canal_expira"):
        database.set_setting(chave, "")


def renovar_avisos_se_preciso() -> None:
    """Chamado pelo agendador: abre o canal se não há, ou renova antes de vencer."""
    if not conectado():
        return
    try:
        expira = int(database.get_setting("google_canal_expira", "") or 0)
    except ValueError:
        expira = 0
    if expira - time.time() > _RENOVAR_ANTES_SEG:
        return
    # Google recusou ha pouco: nao insiste a cada 20 s (a checagem curta cobre).
    if time.time() - _DIAG.get("avisos_falha_em", 0.0) < 1800:
        return
    try:
        iniciar_avisos()
    except Exception:
        _DIAG["avisos_falha_em"] = time.time()
        raise


def aviso_valido(canal_id: str, token: str) -> bool:
    esperado = database.get_setting("google_canal_token", "")
    return bool(esperado) and hmac.compare_digest(str(token).encode("utf-8"), esperado.encode("utf-8")) and canal_id == database.get_setting("google_canal_id", "")



# ── Copia da agenda do Google em memoria ─────────────────────────────────────
# Abrir a aba Agenda nao pode esperar o Google: a janela de 3 meses para tras
# ate 1 ano para frente fica em memoria, atualizada em segundo plano (pelo
# agendador e a cada aviso). As requisicoes do painel so filtram.
import threading as _threading
from datetime import date as _date

_JANELA: dict = {"de": "", "ate": "", "eventos": None, "em": 0.0}
_janela_lock = _threading.Lock()
_atualizando = _threading.Lock()
_DIAG: dict = {"avisos_erro": "", "leitura_erro": "", "checagem_em": 0.0}


def _limites_da_janela() -> tuple[str, str]:
    hoje = _date.today()
    return (hoje - timedelta(days=95)).isoformat(), (hoje + timedelta(days=400)).isoformat()


_releitura = {"pedida": False}


def atualizar_janela() -> bool:
    """Le de novo a janela inteira. True se algo mudou desde a ultima leitura.

    Pedido no meio de outra leitura nao e descartado: a leitura em andamento
    pode ter comecado antes da mudanca, entao quem esta lendo le de novo.
    """
    if not conectado():
        return False
    if not _atualizando.acquire(blocking=False):
        _releitura["pedida"] = True
        return False
    try:
        mudou = False
        while True:
            _releitura["pedida"] = False
            mudou = _ler_janela() or mudou
            if not _releitura["pedida"]:
                return mudou
    finally:
        _atualizando.release()


def _ler_janela() -> bool:
    de, ate = _limites_da_janela()
    eventos, pagina = [], ""
    while True:
        params = {"timeMin": f"{de}T00:00:00{_offset()}", "timeMax": f"{ate}T00:00:00{_offset()}",
                  "singleEvents": "true", "orderBy": "startTime", "maxResults": "2500"}
        if pagina:
            params["pageToken"] = pagina
        r = requests.get(f"{_API}/calendars/{_calendario()}/events", params=params,
                         headers={"Authorization": f"Bearer {_access_token()}"}, timeout=20)
        if r.status_code != 200:
            _DIAG["leitura_erro"] = f"{r.status_code} {r.text[:120]}"
            raise RuntimeError(f"Google Calendar: {r.status_code} {r.text[:150]}")
        dados = r.json()
        eventos += [e for e in (_evento_do_google(ev) for ev in dados.get("items") or []
                                if ev.get("status") != "cancelled") if e]
        pagina = dados.get("nextPageToken", "")
        if not pagina:
            break
    _DIAG["leitura_erro"] = ""
    _DIAG["checagem_em"] = time.time()
    with _janela_lock:
        mudou = _JANELA["eventos"] is not None and _JANELA["eventos"] != eventos
        _JANELA.update(de=de, ate=ate, eventos=eventos, em=time.time())
    return mudou


def atualizar_janela_em_segundo_plano(depois=None) -> None:
    """Le a janela numa thread; `depois(mudou)` roda no fim (ex.: avisar o painel)."""
    def _trabalho():
        try:
            mudou = atualizar_janela()
        except Exception as e:
            print(f"[google] WARN leitura da agenda: {e}")
            return
        if depois:
            depois(mudou)
    _threading.Thread(target=_trabalho, daemon=True).start()


def idade_da_janela() -> float:
    return time.time() - _JANELA["em"] if _JANELA["eventos"] is not None else float("inf")


def eventos_do_periodo(de: str, ate: str, ignorar: set | None = None) -> list[dict]:
    """Eventos que tocam o periodo, da copia em memoria (sem esperar o Google).

    Periodo fora da janela, ou janela ainda vazia (logo apos o servidor
    subir), cai na leitura direta com cache curto.
    """
    if not conectado():
        return []
    with _janela_lock:
        eventos, j_de, j_ate = _JANELA["eventos"], _JANELA["de"], _JANELA["ate"]
    if eventos is None or not (j_de <= de and ate <= j_ate):
        if eventos is None:
            atualizar_janela_em_segundo_plano()
        return listar_eventos(de, ate, ignorar)
    ignorar = ignorar or set()
    ini, fim = f"{de}T00:00", f"{ate}T00:00"
    return [e for e in eventos if e["id"] not in ignorar and e["inicio"] < fim and e["fim"] > ini]


def diagnostico() -> dict:
    """Para a linha de status da Agenda: a atualizacao automatica esta viva?"""
    try:
        expira = int(database.get_setting("google_canal_expira", "") or 0)
    except ValueError:
        expira = 0
    idade = idade_da_janela()
    return {
        "avisos_ativos": expira > time.time(),
        "avisos_erro": _DIAG["avisos_erro"],
        "leitura_erro": _DIAG["leitura_erro"],
        "idade_seg": None if idade == float("inf") else int(idade),
        "checagem_seg": int(time.time() - _DIAG["checagem_em"]) if _DIAG["checagem_em"] else None,
    }
