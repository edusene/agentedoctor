"""
ficha_paciente.py — Memória estruturada do atendimento (seção 14 da base).

A ficha é a verdade sobre o que o paciente já informou. Ela fica no banco
(conversation_states), então sobrevive a reinício do servidor e a janela de
histórico do modelo. O funil lê a ficha para decidir a próxima pergunta: nada
que já está preenchido é perguntado de novo.
"""

from __future__ import annotations

import re
from datetime import datetime

import clinica
import database

# Ordem da seção 14. "telefone" vem do próprio WhatsApp e nunca é perguntado;
# "detalhe_area" é a pergunta específica da área provável (seções 2 a 11).
ORDEM = [
    "nome", "queixa", "detalhe_area", "tempo_queixa", "avaliacao_previa",
    "exames", "cidade", "disponibilidade", "tipo_consulta", "saude",
]

ROTULOS = {
    "nome": "Nome",
    "telefone": "Telefone",
    "queixa": "Queixa principal",
    "detalhe_area": "Detalhes",
    "tempo_queixa": "Há quanto tempo",
    "avaliacao_previa": "Já passou por avaliação",
    "exames": "Exames/encaminhamento",
    "cidade": "Cidade",
    "disponibilidade": "Disponibilidade",
    "tipo_consulta": "Consulta",
    "saude": "Saúde (condições, alergias, medicamentos)",
}

PERGUNTAS = {
    "nome": "Com quem eu falo? Qual é o seu nome?",
    # Seção 16, segundo parágrafo.
    "queixa": ("Para eu te orientar melhor, me conta qual é a sua principal queixa "
               "ou o que você gostaria de tratar."),
    "tempo_queixa": "Há quanto tempo você tem essa queixa?",
    "avaliacao_previa": "Você já passou por avaliação com algum dentista ou médico por causa disso?",
    "exames": "Você tem exames (radiografia, tomografia, laudo) ou algum encaminhamento?",
    "cidade": "Em qual cidade você mora?",
    "disponibilidade": "Quais dias e horários ficam melhores para você vir à avaliação?",
    "tipo_consulta": "Esta seria a sua primeira consulta com o Dr. Fabrício ou é um retorno?",
    "saude": ("Por último: você tem alguma condição de saúde, alergia ou usa algum "
              "medicamento contínuo? Se não tiver, é só responder \"não\"."),
}

PERGUNTA_CONFIRMACAO = "Está tudo certo? Posso encaminhar para a equipe confirmar o seu horário?"
PERGUNTA_CURIOSIDADE = ("Posso te ajudar com mais alguma dúvida ou você gostaria de "
                        "agendar uma avaliação com o Dr. Fabrício?")

# Depois de perguntar duas vezes sem resposta aproveitável, o campo fica como
# "Não informado" e o funil segue. Sem isso, uma resposta que o código não
# entende vira laço: a mesma pergunta para sempre.
MAX_TENTATIVAS = 2
NAO_INFORMADO = "Não informado"


def nova(phone: str = "") -> dict:
    return {
        "telefone": phone,
        **{c: "" for c in ORDEM},
        "area": "",
        "areas": [],
        "intencao": "curiosidade",
        "status": "coletando",          # coletando | aguardando_confirmacao | encaminhado
        "ultima_pergunta": "",
        "tentativas": {},
        "saudacao_feita": False,
        "triagem_trauma": "",           # "" | "perguntada" | "sem_gravidade"
        "emergencia": False,
        "cta_curiosidade_feito": False,
        "observacoes": "",
        "atualizado_em": "",
    }


# ── Persistência ─────────────────────────────────────────────────────────────

def load(phone: str) -> dict:
    ficha = nova(phone)
    try:
        salvo = database.get_conversation_state(phone) or {}
        if isinstance(salvo.get("ficha"), dict):
            ficha.update(salvo["ficha"])
    except Exception as e:
        print(f"[ficha] WARN nao leu ficha de {phone}: {e}")
    ficha["telefone"] = ficha.get("telefone") or phone
    return ficha


def save(phone: str, ficha: dict) -> None:
    ficha["atualizado_em"] = datetime.utcnow().isoformat()
    try:
        database.save_conversation_state(phone, {"ficha": ficha})
    except Exception as e:
        print(f"[ficha] WARN nao salvou ficha de {phone}: {e}")


def reset(phone: str) -> None:
    try:
        database.delete_conversation_state(phone)
    except Exception as e:
        print(f"[ficha] WARN nao apagou ficha de {phone}: {e}")


# ── Funil ────────────────────────────────────────────────────────────────────

def _campo_aplicavel(ficha: dict, campo: str) -> bool:
    if campo == "detalhe_area":
        # Seção 13: pronto para agendar = reduzir explicação.
        return bool(ficha.get("area")) and ficha.get("intencao") != "pronto_agendar"
    return True


def faltando(ficha: dict) -> list[str]:
    return [c for c in ORDEM if _campo_aplicavel(ficha, c) and not ficha.get(c)]


def pergunta_do_campo(ficha: dict, campo: str) -> str:
    if campo == "detalhe_area":
        return clinica.AREAS.get(ficha.get("area"), {}).get("pergunta", "")
    return PERGUNTAS.get(campo, "")


def proximo_campo(ficha: dict) -> str:
    """Próximo campo a perguntar, pulando o que já estourou as tentativas."""
    for campo in faltando(ficha):
        if ficha.get("tentativas", {}).get(campo, 0) >= MAX_TENTATIVAS:
            ficha[campo] = NAO_INFORMADO
            continue
        return campo
    return ""


def marcar_pergunta(ficha: dict, campo: str) -> None:
    ficha["ultima_pergunta"] = campo
    if campo in ORDEM:
        t = dict(ficha.get("tentativas") or {})
        t[campo] = t.get(campo, 0) + 1
        ficha["tentativas"] = t


def resumo(ficha: dict) -> str:
    linhas = ["Confira os dados da sua solicitação:"]
    for campo in ["nome", "telefone"] + ORDEM[1:]:
        valor = (ficha.get(campo) or "").strip()
        if not valor or (campo == "detalhe_area" and not _campo_aplicavel(ficha, campo)):
            continue
        linhas.append(f"• {ROTULOS[campo]}: {valor}")
    if ficha.get("observacoes"):
        linhas.append(f"• Observações: {ficha['observacoes']}")
    return "\n".join(linhas)


def render_para_prompt(ficha: dict) -> str:
    """Ficha para o modelo ler. Só leitura: quem pergunta é o código."""
    preenchidos = [f"- {ROTULOS[c]}: {ficha[c]}" for c in ["nome"] + ORDEM[1:]
                   if ficha.get(c) and c in ROTULOS]
    area = clinica.AREAS.get(ficha.get("area"), {}).get("nome", "não identificada")
    return (
        "=== FICHA DO PACIENTE (o que ele JÁ informou; não pergunte de novo) ===\n"
        + ("\n".join(preenchidos) or "- (nada ainda)")
        + f"\n- Área provável (uso interno, NÃO é diagnóstico): {area}"
        + f"\n- Intenção (seção 13): {ficha.get('intencao', 'curiosidade')}"
    )


# ── Extração ─────────────────────────────────────────────────────────────────

_LETRAS = r"A-Za-zÀ-ÿ"
_PARADAS_NOME = {
    "e", "eu", "tenho", "preciso", "quero", "gostaria", "estou", "to", "tô", "moro",
    "sou", "com", "de", "da", "do", "paciente", "aqui", "boa", "bom", "tarde", "noite",
    "dia", "queria", "vim", "venho", "minha", "meu", "para", "pra", "que",
}
_NAO_E_NOME = {
    "sim", "nao", "não", "oi", "ola", "olá", "ok", "obrigado", "obrigada", "bom dia",
    "boa tarde", "boa noite", "tudo bem", "certo", "isso", "pode", "blz", "beleza",
}

_RX_NOME = re.compile(
    rf"(?i)\b(?:meu nome [ée]|me chamo|aqui [ée] (?:o|a)|quem fala [ée] (?:o|a)|sou (?:o|a))\s+"
    rf"([{_LETRAS}]+(?:\s+[{_LETRAS}]+){{0,4}})"
)
_RX_CIDADE = re.compile(
    rf"(?i)\b(?:moro em|moro na cidade de|sou de|resido em|sou da cidade de|moro no|moro na)\s+"
    rf"([{_LETRAS}]+(?:[\s-]+[{_LETRAS}]+){{0,3}})"
)
_RX_TEMPO = re.compile(
    r"(?i)\b(?:h[aá]|faz|tem|desde|uns|umas|cerca de|mais de|quase)\s+"
    r"(?:\d+|um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|alguns|algumas|poucos|poucas|v[aá]rios|v[aá]rias)\s+"
    r"(?:dia|dias|semana|semanas|m[eê]s|meses|ano|anos)\b"
)
_RX_EXAME_SIM = re.compile(
    r"\b(?:tenho|fiz|possuo|estou com|to com|ja tenho|ja fiz|trouxe|tem)\s+(?:a |o |uma |um |os |as )?"
    r"(tomografia|radiografia|raio ?-?x|rx|panoramica|laudo|exames?|encaminhamento)"
)
_RX_EXAME_NAO = re.compile(
    r"\bnao (?:tenho|fiz|possuo)\s+(?:nenhum |nenhuma )?(?:exame|tomografia|radiografia|raio|laudo|encaminhamento)"
)
_RX_AVALIACAO_SIM = re.compile(
    r"\b(?:meu|minha|o|a) (?:dentista|ortodontista|medico|medica|doutor|doutora)\s+"
    r"(?:disse|falou|pediu|mandou|encaminhou|indicou|viu|solicitou|recomendou)"
    r"|\bja (?:passei|fui|consultei) (?:em|no|na|por|ao|a|com) (?:um |uma )?(?:dentista|medico|avaliacao|consulta|ortodontista|cirurgiao)"
)
_RX_PRIMEIRA = re.compile(r"\bprimeira (?:consulta|vez)\b|\bnunca (?:fui|me consultei|passei)\b|\bprimeira\b")
_RX_RETORNO = re.compile(r"\bretorno\b|\bja sou paciente\b|\bja (?:fui|me consultei) com (?:ele|o dr|o doutor)\b|\bvoltar\b")


def _titulo(nome: str) -> str:
    minusculas = {"de", "da", "do", "dos", "das", "e"}
    partes = [p for p in nome.split() if p]
    return " ".join(p.lower() if (i and p.lower() in minusculas) else p.capitalize()
                    for i, p in enumerate(partes))


def _limpar_nome(bruto: str) -> str:
    palavras = []
    for p in bruto.split():
        if clinica.normalizar(p) in _PARADAS_NOME:
            break
        palavras.append(p)
    return _titulo(" ".join(palavras[:4]))


def extrair_nome(texto: str) -> str:
    m = _RX_NOME.search(texto or "")
    return _limpar_nome(m.group(1)) if m else ""


def nome_de_resposta_direta(texto: str) -> str:
    """Resposta seca à pergunta do nome ("Maria Souza", "é a Maria")."""
    bruto = (texto or "").strip().strip(".!,")
    achado = extrair_nome(bruto)
    if achado:
        return achado
    bruto = re.sub(r"(?i)^(?:[ée]\s+(?:o|a)\s+|[ée]\s+|o\s+|a\s+)", "", bruto)
    t = clinica.normalizar(bruto)
    if (not bruto or t in _NAO_E_NOME or any(ch.isdigit() for ch in bruto)
            or "?" in bruto or len(bruto.split()) > 4
            or not re.fullmatch(rf"[{_LETRAS}\s'-]+", bruto)
            or clinica.classificar_areas(bruto)):
        return ""
    return _limpar_nome(bruto)


def _cidade(texto: str) -> str:
    m = _RX_CIDADE.search(texto or "")
    if not m:
        return ""
    palavras = []
    for p in m.group(1).split():
        if clinica.normalizar(p) in {"e", "tenho", "preciso", "quero", "mas", "com", "e"}:
            break
        palavras.append(p)
    return _titulo(" ".join(palavras))


def extrair_passivo(ficha: dict, texto: str) -> list[str]:
    """Dados que o paciente deu sem ter sido perguntado. Só preenche lacunas."""
    mudou = []
    t = clinica.normalizar(texto)

    if not ficha.get("nome"):
        nome = extrair_nome(texto)
        if nome:
            ficha["nome"] = nome
            mudou.append("nome")

    if not ficha.get("cidade"):
        cidade = _cidade(texto)
        if cidade:
            ficha["cidade"] = cidade
            mudou.append("cidade")

    if not ficha.get("tempo_queixa"):
        m = _RX_TEMPO.search(texto or "")
        if m:
            ficha["tempo_queixa"] = m.group(0).strip()
            mudou.append("tempo_queixa")

    if not ficha.get("exames"):
        if _RX_EXAME_NAO.search(t):
            ficha["exames"] = "Não possui"
            mudou.append("exames")
        else:
            m = _RX_EXAME_SIM.search(t)
            if m:
                ficha["exames"] = f"Sim ({m.group(1)})"
                mudou.append("exames")

    if not ficha.get("avaliacao_previa") and _RX_AVALIACAO_SIM.search(t):
        ficha["avaliacao_previa"] = "Sim"
        mudou.append("avaliacao_previa")

    if not ficha.get("tipo_consulta"):
        if _RX_RETORNO.search(t):
            ficha["tipo_consulta"] = "Retorno"
            mudou.append("tipo_consulta")
        elif re.search(r"\bprimeira (?:consulta|vez)\b", t):
            ficha["tipo_consulta"] = "Primeira consulta"
            mudou.append("tipo_consulta")

    # Pergunta educativa ("todo siso precisa ser tirado?") nao e queixa do
    # paciente (secao 13, curiosidade): nao vira area nem queixa na ficha.
    educativa = "?" in (texto or "") and clinica.classificar_intencao(texto) == "curiosidade"
    areas = [] if educativa else clinica.classificar_areas(texto)
    if areas:
        novas = [a for a in areas if a not in (ficha.get("areas") or [])]
        ficha["areas"] = list(dict.fromkeys((ficha.get("areas") or []) + areas))
        # A área principal só troca para uma de maior prioridade (seção 19).
        atual = ficha.get("area")
        if not atual or clinica.PRIORIDADE_AREAS.index(areas[0]) < clinica.PRIORIDADE_AREAS.index(atual):
            ficha["area"] = areas[0]
        if novas:
            mudou.append("area")
        if not ficha.get("queixa"):
            ficha["queixa"] = (texto or "").strip()[:300]
            mudou.append("queixa")

    intencao = clinica.intencao_maior(ficha.get("intencao", "curiosidade"),
                                      clinica.classificar_intencao(texto))
    if intencao != ficha.get("intencao"):
        ficha["intencao"] = intencao
        mudou.append("intencao")
    return mudou


def capturar_resposta(ficha: dict, campo: str, texto: str) -> bool:
    """Grava a resposta à pergunta que o código fez. False = não aproveitável."""
    bruto = (texto or "").strip()
    t = clinica.normalizar(bruto)
    if not bruto or not campo or campo not in ORDEM:
        return False
    # Uma pergunta de volta não é resposta ("vocês atendem em Goiânia?").
    if "?" in bruto:
        return False

    if campo == "nome":
        nome = nome_de_resposta_direta(bruto)
        if not nome:
            return False
        ficha["nome"] = nome
        return True

    if campo == "queixa":
        if len(t) < 3 or clinica.e_sim(bruto) or clinica.e_nao(bruto):
            return False
        ficha["queixa"] = bruto[:300]
        return True

    if campo == "cidade":
        ficha["cidade"] = _cidade(bruto) or _titulo(re.sub(r"(?i)^(?:em|de|moro em|sou de)\s+", "", bruto))[:80]
        return True

    if campo == "tipo_consulta":
        if _RX_RETORNO.search(t):
            ficha["tipo_consulta"] = "Retorno"
        elif _RX_PRIMEIRA.search(t) or clinica.e_nao(bruto):
            ficha["tipo_consulta"] = "Primeira consulta"
        else:
            ficha["tipo_consulta"] = bruto[:120]
        return True

    if campo == "exames":
        if _RX_EXAME_NAO.search(t) or clinica.e_nao(bruto):
            ficha["exames"] = "Não possui"
        elif clinica.e_sim(bruto) and len(t.split()) <= 2:
            ficha["exames"] = "Sim"
        else:
            ficha["exames"] = bruto[:300]
        return True

    if campo == "avaliacao_previa":
        if clinica.e_nao(bruto) and len(t.split()) <= 3:
            ficha["avaliacao_previa"] = "Não"
        elif clinica.e_sim(bruto) and len(t.split()) <= 2:
            ficha["avaliacao_previa"] = "Sim"
        else:
            ficha["avaliacao_previa"] = bruto[:300]
        return True

    if campo == "saude":
        ficha["saude"] = ("Nada relatado" if clinica.e_nao(bruto) and len(t.split()) <= 3
                          else bruto[:300])
        return True

    # detalhe_area, tempo_queixa, disponibilidade: texto do paciente como veio.
    if len(t) < 1:
        return False
    ficha[campo] = bruto[:300]
    return True


# Correcao no resumo: "a cidade e Candeias", "meu nome e Ana Paula". O campo
# certo e reescrito; sem isso a correcao ia para Observacoes e o resumo
# mostrava os dois valores, o velho e o novo.
_CAMPOS_CORRIGIVEIS = [
    ("nome", r"\bnome\b"),
    ("cidade", r"\bcidade\b|\bmoro\b"),
    ("disponibilidade", r"\b(horario|horarios|dia|dias|disponibilidade|turno|periodo)\b"),
    ("tempo_queixa", r"\btempo\b"),
    ("exames", r"\bexames?\b|\btomografia\b|\bradiografia\b|\blaudo\b"),
    ("tipo_consulta", r"\bretorno\b|\bprimeira consulta\b"),
    ("saude", r"\balergia|\bmedicamento|\bremedio|\bdoenca|\bsaude\b"),
    ("queixa", r"\bqueixa\b"),
]
_RX_VALOR_CORRIGIDO = re.compile(
    r"(?i)\s(?:é|e|eh|:|seria|correta é|certa é|para|pra|na verdade é|em)\s+(.+)$")


def aplicar_correcao(ficha: dict, texto: str) -> str:
    """Aplica a correcao ao campo citado. Devolve o campo, ou "" se nao achou."""
    t = clinica.normalizar(texto)
    citados = [c for c, rx in _CAMPOS_CORRIGIVEIS if re.search(rx, t)]
    if len(citados) != 1:
        return ""
    campo = citados[0]
    if campo == "tipo_consulta":
        ficha[campo] = "Retorno" if "retorno" in t else "Primeira consulta"
        return campo
    m = _RX_VALOR_CORRIGIDO.search(texto or "")
    if not m:
        return ""
    valor = m.group(1).strip().strip(".!")
    if not valor:
        return ""
    ficha[campo] = _titulo(valor) if campo in ("nome", "cidade") else valor[:300]
    return campo
