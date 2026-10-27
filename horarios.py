"""
horarios.py — Horários de atendimento e vagas livres da agenda.

A equipe define na aba Horários em que dias e faixas o Dr. Fabrício atende,
de quanto em quanto tempo começa uma avaliação, a antecedência mínima e os
dias bloqueados (feriado, congresso). vagas() cruza isso com o que já está
ocupado (agendamentos confirmados e eventos do Google) e devolve os horários
que ainda cabem uma avaliação.

No modo Auto do painel, escolher() devolve a vaga que cabe na disponibilidade
do paciente e o agente agenda sozinho; no Manual a equipe confirma.

Sem Flask, banco ou rede: as funções recebem tudo e são testáveis puras.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta

DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

PADRAO = {
    # Chave = weekday() do Python (0 = segunda). Cada faixa = [inicio, fim].
    "dias": {
        "0": [["08:00", "12:00"], ["14:00", "18:00"]],
        "1": [["08:00", "12:00"], ["14:00", "18:00"]],
        "2": [["08:00", "12:00"], ["14:00", "18:00"]],
        "3": [["08:00", "12:00"], ["14:00", "18:00"]],
        "4": [["08:00", "12:00"], ["14:00", "18:00"]],
        "5": [],
        "6": [],
    },
    "passo_min": 60,          # de quanto em quanto tempo começa uma vaga
    "antecedencia_horas": 24,  # vaga mais cedo que isso não é oferecida
    "janela_dias": 30,         # até quantos dias à frente
    "bloqueios": [],           # [{"data": "2026-12-25", "motivo": "Natal"}]
}


def _hhmm(valor) -> str:
    """'8:00' -> '08:00'. ValueError se não for um horário válido."""
    return datetime.strptime(str(valor).strip(), "%H:%M").strftime("%H:%M")


def normalizar(cfg) -> tuple[dict, str]:
    """(config limpa, erro). Erro vazio = ok. Campo ausente vira o padrão."""
    if not isinstance(cfg, dict):
        return json.loads(json.dumps(PADRAO)), "Configuração inválida."
    saida = {}

    dias_in = cfg.get("dias", PADRAO["dias"])
    if not isinstance(dias_in, dict):
        return {}, "Dias inválidos."
    dias = {}
    for k in range(7):
        faixas = []
        for faixa in dias_in.get(str(k)) or []:
            try:
                ini, fim = _hhmm(faixa[0]), _hhmm(faixa[1])
            except (ValueError, TypeError, IndexError):
                return {}, f"{DIAS[k]}: horário inválido."
            if ini >= fim:
                return {}, f"{DIAS[k]}: o fim ({fim}) precisa ser depois do início ({ini})."
            faixas.append([ini, fim])
        faixas.sort()
        for a, b in zip(faixas, faixas[1:]):
            if b[0] < a[1]:
                return {}, f"{DIAS[k]}: as faixas {a[0]}–{a[1]} e {b[0]}–{b[1]} se sobrepõem."
        dias[str(k)] = faixas
    saida["dias"] = dias

    for campo, minimo, maximo, nome in (
        ("passo_min", 10, 240, "O intervalo entre vagas"),
        ("antecedencia_horas", 0, 720, "A antecedência"),
        ("janela_dias", 1, 180, "O período de agendamento"),
    ):
        try:
            v = int(cfg.get(campo, PADRAO[campo]))
        except (TypeError, ValueError):
            return {}, f"{nome} é inválido."
        if not minimo <= v <= maximo:
            return {}, f"{nome} deve ficar entre {minimo} e {maximo}."
        saida[campo] = v

    bloqueios, vistos = [], set()
    for b in cfg.get("bloqueios") or []:
        try:
            dia = date.fromisoformat(str(b.get("data", "")).strip()).isoformat()
        except (ValueError, AttributeError):
            return {}, "Data bloqueada inválida."
        if dia in vistos:
            continue
        vistos.add(dia)
        bloqueios.append({"data": dia, "motivo": str(b.get("motivo", "")).strip()[:80]})
    saida["bloqueios"] = sorted(bloqueios, key=lambda b: b["data"])
    return saida, ""


def carregar(texto: str) -> dict:
    """Config salva (JSON) -> config limpa. Vazia ou estragada volta ao padrão."""
    try:
        cfg, erro = normalizar(json.loads(texto)) if texto else ({}, "vazio")
    except ValueError:
        cfg, erro = {}, "json"
    return cfg if not erro else json.loads(json.dumps(PADRAO))


def vagas(cfg: dict, de: date, ate: date, ocupados: list[tuple[datetime, datetime]],
          duracao_min: int, agora: datetime) -> list[dict]:
    """Vagas livres de `de` (incluso) a `ate` (excluso), limitadas à janela.

    `ocupados` são intervalos (inicio, fim) em hora local, sem fuso; `agora`
    também. Devolve [{"data": "2026-10-20", "dia": "Terça", "horarios": ["08:00", ...]}],
    só com os dias que têm alguma vaga.
    """
    agora = agora.replace(tzinfo=None, second=0, microsecond=0)
    primeiro = agora + timedelta(hours=cfg["antecedencia_horas"])
    limite = agora.date() + timedelta(days=cfg["janela_dias"] + 1)
    ate = min(ate, limite)
    bloqueados = {b["data"] for b in cfg["bloqueios"]}
    passo = timedelta(minutes=cfg["passo_min"])
    dur = timedelta(minutes=duracao_min)

    saida = []
    dia = de
    while dia < ate:
        horarios = []
        if dia.isoformat() not in bloqueados:
            for ini_txt, fim_txt in cfg["dias"].get(str(dia.weekday()), []):
                t = datetime.combine(dia, datetime.strptime(ini_txt, "%H:%M").time())
                fim_faixa = datetime.combine(dia, datetime.strptime(fim_txt, "%H:%M").time())
                while t + dur <= fim_faixa:
                    if t >= primeiro and not any(o_ini < t + dur and t < o_fim for o_ini, o_fim in ocupados):
                        horarios.append(t.strftime("%H:%M"))
                    t += passo
        if horarios:
            saida.append({"data": dia.isoformat(), "dia": DIAS[dia.weekday()], "horarios": horarios})
        dia += timedelta(days=1)
    return saida


def livre(cfg: dict, inicio: datetime, ocupados: list[tuple[datetime, datetime]],
          duracao_min: int, agora: datetime) -> bool:
    """O horário exato `inicio` é uma vaga oferecida?"""
    dia = inicio.date()
    for v in vagas(cfg, dia, dia + timedelta(days=1), ocupados, duracao_min, agora):
        return inicio.strftime("%H:%M") in v["horarios"]
    return False


# ── Escolha automática (modo Auto) ───────────────────────────────────────────
# "Terças manhã e sextas à tarde", "quarta-feira às 8 horas", "qualquer dia à
# tarde": a disponibilidade que o paciente escreveu vira filtro das vagas.
_NOMES_DIAS = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
_RX_HORA = re.compile(
    r"(?:\b(?:as|a partir das|depois das|apos as|apos)\s+)?\b(\d{1,2})(?::(\d{2}))?(?:\s*(?:h|hs|hrs|horas?))?\b"
    r"(?:\s+da\s+(manha|tarde|noite))?")
# Dia relativo ou data solta: o código não sabe resolver, a equipe decide.
_RX_RELATIVO = re.compile(r"\b(amanha|hoje|depois de amanha|semana que vem|proxim\w+|mes que vem|dia \d+)\b")


# Disponibilidade aberta ("qualquer horário", "quando der"); com restrição ("menos sexta") a equipe decide.
_RX_QUALQUER = re.compile(
    r"\bqualquer (?:horario|hora|dia|periodo|turno|momento)\b|\bquando (?:der|puder|voces puderem|for melhor para voces)\b"
    r"|\btanto faz\b|\bsem preferencia\b|\bflexivel\b|\btodos os (?:horarios|dias|periodos)\b|\bdisponibilidade total\b"
    r"|\bem qualquer\b|\bqualquer um\b|\bo que (?:voces )?tiver(?:em)?\b|\bo que der\b")
_RX_RESTRICAO = re.compile(r"\b(?:menos|exceto|except\w*|so nao|nao (?:posso|consigo|da|dá)|fora)\b")


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def _dias_do_trecho(trecho: str) -> set:
    achados = set()
    for palavra in re.findall(r"[a-z]+", trecho):
        if len(palavra) < 3:
            continue
        for i, nome in enumerate(_NOMES_DIAS):
            # "ter", "qua", "sex" (abreviado) ou o nome com até um erro de digitação
            if (palavra in ("seg", "ter", "qua", "qui", "sex", "sab", "dom") and nome.startswith(palavra)
                    or difflib.SequenceMatcher(None, palavra.rstrip("s"), nome).ratio() >= 0.8
                    or (len(palavra) > 4 and palavra.rstrip("s").removesuffix("feira").rstrip("-") == nome)):
                achados.add(i)
    return achados


def _filtros(texto: str) -> list[tuple[set, str, str, bool]]:
    """[(dias da semana, periodo, 'HH:MM', 'a partir de')] um por trecho; vazio = sem restrição.

    None-like: texto com dia relativo ("amanhã") ou número que não é horário.
    """
    texto = _sem_acento(texto)
    if _RX_RELATIVO.search(texto) or _RX_RESTRICAO.search(texto):
        return []
    saida = []
    for trecho in re.split(r"[;,\n]| e (?=\w)", texto):
        dias = _dias_do_trecho(trecho)
        if re.search(r"\bsegunda a sexta\b|\bdias? uteis\b|\bqualquer dia\b|\btodos os dias\b", trecho):
            dias = set()
        periodo = next((p for p, rx in (("manha", r"\bmanha\b|\bcedo\b"), ("tarde", r"\btarde\b"),
                                        ("noite", r"\bnoite\b")) if re.search(rx, trecho)), "")
        hora, a_partir = "", False
        m = _RX_HORA.search(trecho)
        if m:
            h, mi = int(m.group(1)), m.group(2) or "00"
            if h > 23:
                return []
            if m.group(3) == "tarde" and h < 12:
                h += 12
            hora = f"{h:02d}:{mi}"
            a_partir = bool(re.search(r"a partir das|depois das|apos", trecho))
        if dias or periodo or hora:
            saida.append((dias, periodo, hora, a_partir))
    if not saida and _RX_QUALQUER.search(texto):
        return [(set(), "", "", False)]  # "qualquer horário": a primeira vaga serve
    # "terça e quinta à tarde": o período do último trecho vale para os dias soltos antes dele.
    for i in range(len(saida) - 2, -1, -1):
        dias, periodo, hora, a_partir = saida[i]
        if dias and not periodo and not hora and saida[i + 1][1]:
            saida[i] = (dias, saida[i + 1][1], hora, a_partir)
    return saida


def escolher(vagas_livres: list[dict], disponibilidade: str) -> datetime | None:
    """Primeira vaga que cabe no que o paciente disse; None se nenhuma cabe.

    Sem dia nem período reconhecível ("quando der") não se escolhe: a equipe decide.
    """
    filtros = _filtros(disponibilidade)
    if not filtros:
        return None
    for v in vagas_livres:
        dia = date.fromisoformat(v["data"])
        for h in v["horarios"]:
            hh = int(h[:2])
            periodo = "manha" if hh < 12 else "tarde" if hh < 18 else "noite"
            for dias, per, hora, a_partir in filtros:
                if ((not dias or dia.weekday() in dias) and (not per or per == periodo)
                        and (not hora or (h >= hora if a_partir else hora == h))):
                    return datetime.combine(dia, datetime.strptime(h, "%H:%M").time())
    return None
