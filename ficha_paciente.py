"""
ficha_paciente.py — Memória estruturada do atendimento (seção 14 da base).

A ficha é a verdade sobre o que o paciente já informou. Ela fica no banco
(conversation_states), então sobrevive a reinício do servidor e a janela de
histórico do modelo. O funil lê a ficha para decidir a próxima pergunta: nada
que já está preenchido é perguntado de novo.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import clinica
import database

# Fluxo pedido pelo Dr. Fabricio (06/10): nome, queixa, detalhe da area, o
# pre-requisito de exame da area, CADASTRO (dados pessoais) e agendamento.
# "Ha quanto tempo", "cidade" e "indicacao" sairam do funil: o tempo o
# cirurgiao pergunta na consulta e a cidade vem no endereco do cadastro. Se o
# paciente contar por conta propria, a ficha ainda guarda (CAMPOS_EXTRAS).
# "telefone" vem do proprio WhatsApp e nunca e perguntado.
# Roteiro do doutor (23/10): nome -> queixa -> pre-cadastro (com e-mail e CEP)
# -> dias e horarios -> saude. Detalhes da area, exames e primeira/retorno
# sairam do funil; o que o paciente contar sozinho a ficha ainda guarda.
CADASTRO = ["nome_completo", "nascimento", "cpf", "rg", "email", "endereco", "cep"]
ORDEM = ["nome", "queixa", *CADASTRO, "disponibilidade", "saude"]
CAMPOS_EXTRAS = ["avaliacao_previa", "tempo_queixa", "cidade", "detalhe_area", "exames",
                 "tipo_consulta"]

ROTULOS = {
    "nome": "Nome",
    "nome_completo": "Nome completo",
    "nascimento": "Data de nascimento",
    "cpf": "CPF",
    "rg": "RG",
    "email": "E-mail",
    "endereco": "Endereço",
    "cep": "CEP",
    "telefone": "Telefone",
    "queixa": "Queixa principal",
    "detalhe_area": "Detalhes",
    "tempo_queixa": "Há quanto tempo",
    "avaliacao_previa": "Avaliação/indicação",
    "exames": "Exames/encaminhamento",
    "cidade": "Cidade",
    "disponibilidade": "Disponibilidade",
    "tipo_consulta": "Consulta",
    "para_quem": "Atendimento para",
    "saude": "Saúde (condições, alergias, medicamentos)",
}

PERGUNTAS = {
    # Textos curtos de proposito: o Dr. Fabricio pediu menos texto (07/10).
    # Roteiro do doutor (23/10), texto dele.
    "nome": "Qual o seu nome e em que posso ajudar?",
    "queixa": ("Poderia me adiantar qual seria o motivo da sua consulta? Qual seria a sua "
               "queixa (reclamação)?"),
    "exames": "Você tem exames (radiografia, tomografia, laudo) ou algum encaminhamento?",
    "nome_completo": "Qual é o seu nome completo?",
    "nascimento": "Qual é a sua data de nascimento?",
    "cpf": "Qual é o seu CPF?",
    "rg": "Qual é o seu RG?",
    "email": "Qual é o seu e-mail?",
    "endereco": "Qual é o seu endereço completo, com CEP?",
    "cep": "Qual é o CEP do seu endereço?",
    "disponibilidade": "Quais dias e horários ficam melhores para você?",
    "tipo_consulta": "É a sua primeira consulta ou um retorno?",
    "saude": ("Por último: você tem algum problema de saúde, alergia ou usa algum "
              "medicamento contínuo?"),
}

# Quando a pergunta precisa ser repetida (o paciente respondeu outra coisa).
PERGUNTAS_CURTAS = {
    "nome": "Qual é o seu nome?",
    "queixa": "Qual seria a sua queixa (reclamação)?",
    "disponibilidade": "Quais dias e horários são melhores?",
    "saude": "Você tem algum problema de saúde, alergia ou usa medicamento contínuo?",
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
        **{c: "" for c in ORDEM + CAMPOS_EXTRAS},
        "cadastro_pedido": False,
        "aviso_cadastro": "",
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
        "para_quem": "",
        "atualizado_em": "",
    }


# ── Persistência ─────────────────────────────────────────────────────────────

class FichaIndisponivel(Exception):
    """O banco nao respondeu: a ficha nao pode ser lida ou gravada agora."""


# Teste do Dr. Fabricio, 21/10: o banco oscilou e load() devolveu uma ficha
# VAZIA no lugar do erro. O agente cumprimentou de novo, perguntou o que ja
# sabia e o save() seguinte gravou a ficha vazia por cima da verdadeira. No
# atendimento (estrito=True) a falha agora tenta de novo e, se o banco nao
# voltar, sobe FichaIndisponivel: melhor responder depois do que errado.
_ESPERAS_BANCO = (0.5, 1.5, 3.0)


def _com_novas_tentativas(acao, oque: str, phone: str):
    for espera in (*_ESPERAS_BANCO, None):
        try:
            return acao()
        except Exception as e:
            if espera is None:
                raise FichaIndisponivel(f"{oque} de {clinica.mascarar_fone(phone)}: {e}") from e
            print(f"[ficha] WARN {oque} de {clinica.mascarar_fone(phone)} falhou ({str(e).strip()[:80]}); "
                  f"nova tentativa em {espera}s")
            time.sleep(espera)


def load(phone: str, estrito: bool = False) -> dict:
    ficha = nova(phone)
    try:
        if estrito:
            salvo = _com_novas_tentativas(
                lambda: database.get_conversation_state(phone), "leitura da ficha", phone) or {}
        else:
            salvo = database.get_conversation_state(phone) or {}
        if isinstance(salvo.get("ficha"), dict):
            ficha.update(salvo["ficha"])
    except FichaIndisponivel:
        raise
    except Exception as e:
        print(f"[ficha] WARN nao leu ficha de {clinica.mascarar_fone(phone)}: {e}")
    ficha["telefone"] = ficha.get("telefone") or phone
    # Ficha gravada antes da trava de 14/10 pode ter o texto do pedido como
    # dado ("Endereço: rua, número, bairro e cidade)"): vale como vazio.
    for campo in CADASTRO:
        if ficha.get(campo) and _so_modelo(str(ficha[campo])):
            ficha[campo] = ""
    return ficha


def save(phone: str, ficha: dict, estrito: bool = False) -> None:
    ficha["atualizado_em"] = datetime.utcnow().isoformat()
    if estrito:
        _com_novas_tentativas(
            lambda: database.save_conversation_state(phone, {"ficha": ficha}), "gravacao da ficha", phone)
        return
    try:
        database.save_conversation_state(phone, {"ficha": ficha})
    except Exception as e:
        print(f"[ficha] WARN nao salvou ficha de {clinica.mascarar_fone(phone)}: {e}")


def reset(phone: str) -> None:
    try:
        database.delete_conversation_state(phone)
    except Exception as e:
        print(f"[ficha] WARN nao apagou ficha de {clinica.mascarar_fone(phone)}: {e}")


# ── Funil ────────────────────────────────────────────────────────────────────

def _campo_aplicavel(ficha: dict, campo: str) -> bool:
    if campo == "detalhe_area":
        # Seção 13: pronto para agendar = reduzir explicação.
        return bool(ficha.get("area")) and ficha.get("intencao") != "pronto_agendar"
    if campo == "cep":
        # Sem endereco, nao ha CEP para pedir.
        return ficha.get("endereco") != NAO_INFORMADO
    return True


def faltando(ficha: dict) -> list[str]:
    return [c for c in ORDEM if _campo_aplicavel(ficha, c) and not ficha.get(c)]


_PERGUNTA_DA_AREA = {
    "detalhe_area": "pergunta",
    "exames": "pergunta_exames",
    "avaliacao_previa": "pergunta_indicacao",
}


_ITENS_CADASTRO = {
    "nome_completo": "Nome completo",
    "nascimento": "Data de nascimento",
    "cpf": "CPF",
    "rg": "RG",
    "email": "E-mail",
    "endereco": "Endereço com CEP",
    "cep": "CEP",
}


def _pergunta_cadastro(ficha: dict) -> str:
    """Pede o cadastro de uma vez; depois, so o que ficou faltando."""
    faltam = [c for c in CADASTRO if not ficha.get(c) and _campo_aplicavel(ficha, c)]
    # "Endereço com CEP" ja pede o CEP: o item CEP so aparece sozinho.
    itens = [c for c in faltam if not (c == "cep" and "endereco" in faltam)]
    lista = "\n".join(f"• {_ITENS_CADASTRO[c]}" for c in itens)
    if not ficha.get("cadastro_pedido"):
        ficha["cadastro_pedido"] = True
        # Roteiro do doutor (23/10), texto dele.
        return ("Para agendamento da sua consulta, vou precisar fazer um pré-cadastro do(a) "
                "senhor(a). Para isso, poderia me passar as seguintes informações, por "
                f"gentileza:\n{lista}")
    if len(itens) == 1:
        return PERGUNTAS[itens[0]]
    return f"Para completar o seu cadastro, ainda preciso de:\n{lista}"


def pergunta_do_campo(ficha: dict, campo: str, repetida: bool = False) -> str:
    """Pergunta do campo. Com area identificada, a da area tem preferencia."""
    if campo in CADASTRO:
        return _pergunta_cadastro(ficha)
    # "...e em que posso ajudar?" so quando ainda nao se sabe o que ele quer.
    if campo == "nome" and ficha.get("queixa"):
        return PERGUNTAS_CURTAS["nome"]
    if repetida and campo in PERGUNTAS_CURTAS:
        return PERGUNTAS_CURTAS[campo]
    chave = _PERGUNTA_DA_AREA.get(campo)
    if chave:
        da_area = clinica.AREAS.get(ficha.get("area"), {}).get(chave, "")
        if da_area or campo == "detalhe_area":
            return da_area
    return PERGUNTAS.get(campo, "")


def proximo_campo(ficha: dict) -> str:
    """Próximo campo a perguntar, pulando o que já estourou as tentativas."""
    for campo in faltando(ficha):
        if ficha.get("tentativas", {}).get(campo, 0) >= MAX_TENTATIVAS:
            ficha[campo] = NAO_INFORMADO
            continue
        # O endereco pode ter virado "Não informado" agora: o CEP cai junto.
        if not _campo_aplicavel(ficha, campo):
            continue
        return campo
    return ""


def cadastro_completo(ficha: dict) -> bool:
    return all(ficha.get(c) or not _campo_aplicavel(ficha, c) for c in CADASTRO)


def marcar_pergunta(ficha: dict, campo: str, contar: bool = True) -> None:
    ficha["ultima_pergunta"] = campo
    if campo in ORDEM and contar:
        t = dict(ficha.get("tentativas") or {})
        t[campo] = t.get(campo, 0) + 1
        ficha["tentativas"] = t


_ORDEM_RESUMO = ["nome", "telefone", "para_quem", "queixa", "detalhe_area", "exames",
                 "avaliacao_previa", "tempo_queixa", *CADASTRO, "cidade",
                 "disponibilidade", "tipo_consulta", "saude"]


# "Detalhes: Já uso" nao dizia de que (teste do Dr. Fabricio, 12/10): o rotulo
# diz o assunto da pergunta da area.
_ROTULO_DETALHE = {
    "trauma": "Quando aconteceu / atendimento",
    "patologia": "Região e sintomas",
    "biopsia": "Local e evolução",
    "enxerto": "Implante e região",
    "exodontia": "Dente e sintomas",
    "ortognatica": "Aparelho ortodôntico",
    "mentoplastia": "Incômodo e mordida",
    "lift_facial": "O que mais incomoda",
    "lift_cervical": "O que mais incomoda",
    "papada": "O que mais incomoda",
}


def resumo(ficha: dict) -> str:
    linhas = ["Confira os dados da sua solicitação:"]
    # Nome e nome completo eram duas linhas com o mesmo nome ("Alguns dados
    # repetidos", Dr. Fabricio, 12/10): com o nome completo, so ele.
    tem_nome_completo = ficha.get("nome_completo") not in (None, "", NAO_INFORMADO)
    for campo in _ORDEM_RESUMO:
        if campo == "nome" and tem_nome_completo:
            continue
        # Resposta em varias linhas ("Quarta de manha / Quinta a tarde") vira
        # uma linha so: quebrada, ela desmontava a lista do resumo (06/10).
        linhas_valor = [" ".join(l.split()) for l in str(ficha.get(campo) or "").splitlines()]
        valor = " / ".join(l for l in linhas_valor if l)
        if not valor or (campo == "detalhe_area" and not _campo_aplicavel(ficha, campo)):
            continue
        rotulo = ROTULOS[campo]
        if campo == "detalhe_area":
            rotulo = _ROTULO_DETALHE.get(ficha.get("area", ""), rotulo)
        linhas.append(f"• {rotulo}: {valor}")
    if ficha.get("observacoes"):
        linhas.append(f"• Observações: {ficha['observacoes']}")
    return "\n".join(linhas)


def render_para_prompt(ficha: dict) -> str:
    """Ficha para o modelo ler. Só leitura: quem pergunta é o código."""
    # Dados do cadastro (CPF, RG, endereco) nunca vao para o modelo.
    preenchidos = [f"- {ROTULOS[c]}: {ficha[c]}" for c in ["nome"] + ORDEM[1:]
                   if ficha.get(c) and c in ROTULOS and c not in CADASTRO]
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
    r"\b(?:vim|venho|fui|cheguei) (?:por|com|atraves de) (?:uma )?indicacao"
    r"|\bindicacao (?:do|da) (?:meu |minha )?(?:dentista|ortodontista|medico|medica|implantodontista)"
    r"|\b(?:dentista|ortodontista|medico|medica|implantodontista) (?:me )?(?:indicou|encaminhou|mandou|pediu)"
    r"|\b(?:meu|minha|o|a) (?:dentista|ortodontista|medico|medica|doutor|doutora)\s+"
    r"(?:disse|falou|pediu|mandou|encaminhou|indicou|viu|solicitou|recomendou)"
    r"|\bja (?:passei|fui|consultei) (?:em|no|na|por|ao|a|com) (?:um |uma )?(?:dentista|medico|avaliacao|consulta|ortodontista|cirurgiao)"
)
_RX_PRIMEIRA = re.compile(r"\bprimeira (?:consulta|vez)\b|\bnunca (?:fui|me consultei|passei)\b|\bprimeira\b")
_RX_RETORNO = re.compile(
    r"\bretorno\b|\bja (?:sou|fui) paciente\b|\bja consultei\b|\bvoltar\b"
    r"|\bja (?:fui|vim|estive|passei|me consultei) (?:ai|aqui|la|no consultorio|com voces|com ele|com o dr|com o doutor)\b")


def _titulo(nome: str) -> str:
    """'joao da silva' -> 'Joao da Silva'; 'ji-parana' -> 'Ji-Parana'; 'RO' fica 'RO'."""
    minusculas = {"de", "da", "do", "dos", "das", "e"}

    def palavra(i: int, p: str) -> str:
        if i and p.lower() in minusculas:
            return p.lower()
        if len(p) <= 2 and p.isupper():
            return p  # sigla de estado (RO, SP)
        return "-".join(s.capitalize() for s in p.split("-"))

    return " ".join(palavra(i, p) for i, p in enumerate(p for p in nome.split() if p))


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


_RX_CUMPRIMENTO_NO_FIM = re.compile(
    r"(?i)[\s,!.]*(?:tudo bem|tudo bom|tudo certo|td bem|blz|beleza|bom dia|boa tarde|boa noite|ol[aá]|oi)"
    r"[\s,!?.]*$")
_RX_TITULO = re.compile(r"(?i)^(?:dr|dra|sr|sra|srta|doutor|doutora|prof|profa)\.?\s+")
_RX_CHAMAR_DE = re.compile(rf"(?i)\b(?:pode )?(?:me )?cham(?:ar|a|e)(?: me)? de\s+([{_LETRAS}]+(?:\s+[{_LETRAS}]+){{0,3}})")
_PARTICULAS = {"de", "da", "do", "dos", "das", "e"}


def limpar_resposta_de_nome(texto: str) -> str:
    """Tira emoji, titulo e cumprimento do fim: "Ana Paula, tudo bem?" -> "Ana Paula"."""
    bruto = re.sub(rf"[^{_LETRAS}\s'.,!?-]", " ", texto or "")
    bruto = _RX_CUMPRIMENTO_NO_FIM.sub("", bruto).strip(" .,!")
    return " ".join(_RX_TITULO.sub("", bruto).split())


def nome_de_resposta_direta(texto: str) -> str:
    """Resposta seca à pergunta do nome ("Maria Souza", "é a Maria", "pode me chamar de Bia")."""
    m = _RX_CHAMAR_DE.search(texto or "")
    if m:
        return _limpar_nome(m.group(1))
    bruto = limpar_resposta_de_nome(texto)
    achado = extrair_nome(bruto)
    if achado:
        return achado
    bruto = re.sub(r"(?i)^(?:[ée]\s+(?:o|a)\s+|[ée]\s+|o\s+|a\s+)", "", bruto)
    t = clinica.normalizar(bruto)
    palavras = bruto.split()
    # Ate 4 palavras "de verdade" (Joao Pedro da Silva Santos tem 4 + 'da').
    if (not bruto or t in _NAO_E_NOME or any(ch.isdigit() for ch in bruto)
            or "?" in bruto or len([p for p in palavras if p.lower() not in _PARTICULAS]) > 4
            or len(palavras) > 6
            or not re.fullmatch(rf"[{_LETRAS}\s'-]+", bruto)
            or clinica.classificar_areas(bruto)):
        return ""
    # Para no primeiro "aqui", "sou", "eu"... ("e a Maria aqui", "sou eu"), mas
    # nao nas particulas de nome composto ("Joao Pedro da Silva").
    nome = []
    for p in palavras[:6]:
        if clinica.normalizar(p) in (_PARADAS_NOME - _PARTICULAS):
            break
        nome.append(p.lower() if p.lower() in _PARTICULAS else _titulo(p))
    while nome and nome[-1] in _PARTICULAS:
        nome.pop()
    return " ".join(nome)


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
            ficha["queixa"] = limpar_queixa(texto)[:300]
            mudou.append("queixa")

    intencao = clinica.intencao_maior(ficha.get("intencao", "curiosidade"),
                                      clinica.classificar_intencao(texto))
    if intencao != ficha.get("intencao"):
        ficha["intencao"] = intencao
        mudou.append("intencao")
    return mudou


# Mensagens que nao respondem nada: risada, agradecimento, "ok", cumprimento,
# so emoji. Eram gravadas como resposta ("kkkk" virava o exame do paciente).
_RX_SEM_CONTEUDO = re.compile(
    r"^(?:k+|(?:ha)+h?|(?:he)+|(?:rs)+|obrigad[oa](?: .*)?|valeu|vlw|ok|okay|beleza|blz|show|top|legal"
    r"|bom dia|boa tarde|boa noite|oi+|ola|opa|hum+|ah+|eita|tudo bem|tudo bom|perfeito)$")

# "e pra minha filha": o atendimento e de outra pessoa, nao e a queixa.
RX_TERCEIRO = re.compile(
    r"\b(?:pra|para) (?:o |a )?(?:minha|meu) (filh[oa]|mae|pai|espos[oa]|marido|mulher|irma|irmao|avo|"
    r"neto|neta|namorad[oa]|sobrinh[oa]|enteado|enteada|sogr[oa])\b")

_RX_SO_TERCEIRO = re.compile(r"^(?:e |eh )?(?:pra|para) (?:o |a )?(?:minha|meu) \w+$")


def sem_conteudo(texto: str) -> bool:
    t = " ".join(re.sub(r"[^\w\s]", " ", clinica.normalizar(texto)).split())
    return not t or bool(_RX_SEM_CONTEUDO.match(t))


def capturar_resposta(ficha: dict, campo: str, texto: str) -> bool:
    """Grava a resposta à pergunta que o código fez. False = não aproveitável."""
    bruto = (texto or "").strip()
    if campo == "nome":
        # "Ana Paula, tudo bem?": o "?" e do cumprimento, nao do nome.
        bruto = limpar_resposta_de_nome(bruto) if not _RX_CHAMAR_DE.search(bruto) else bruto
    t = clinica.normalizar(bruto)
    if not bruto or not campo or campo not in ORDEM:
        return False
    # Uma pergunta de volta não é resposta ("vocês atendem em Goiânia?").
    if "?" in bruto or sem_conteudo(bruto):
        return False
    # "Nao sei" e resposta valida, mas nao e "nao".
    nao_sabe = clinica.e_nao_sabe(bruto)
    if nao_sabe and campo in ("exames", "avaliacao_previa", "tipo_consulta", "saude", "tempo_queixa"):
        ficha[campo] = "Não sabe informar"
        return True

    if campo == "nome":
        nome = nome_de_resposta_direta(bruto)
        if not nome:
            return False
        ficha["nome"] = nome
        return True

    if campo == "queixa":
        if len(t) < 3 or clinica.e_sim(bruto) or clinica.e_nao(bruto):
            return False
        # So "e pra minha filha": falta a queixa.
        if _RX_SO_TERCEIRO.match(t.strip(" .!")):
            return False
        # So "quero agendar uma avaliacao": e intencao, nao queixa.
        if (clinica.classificar_intencao(bruto) == "pronto_agendar"
                and not clinica.classificar_areas(bruto) and len(t.split()) <= 6):
            return False
        ficha["queixa"] = limpar_queixa(bruto)[:300]
        return True

    if campo == "cidade":
        if re.search(r"\b(?:aqui|daqui|mesma cidade|nessa cidade|aqui mesmo)\b", t):
            ficha["cidade"] = "Mesma cidade do consultório"
            return True
        sem_prefixo = re.sub(r"(?i)^(?:eu )?(?:moro|resido|sou|fico|estou)?\s*(?:em|no|na|de|da|do)?\s+",
                             "", " " + bruto).strip()
        ficha["cidade"] = _cidade(bruto) or _titulo(sem_prefixo)[:80]
        return True

    if campo in CADASTRO:
        # Recusa vale para qualquer campo; "nao tenho" so para documento (RG,
        # CPF) - para o nome completo ele nao quer dizer nada.
        recusa = re.search(r"\b(?:prefiro nao|nao quero (?:informar|passar|dizer))\b", t)
        # "Não" seco a "Qual é o seu RG?" (teste de 22/10) tambem e "nao tenho".
        sem_documento = campo in ("rg", "cpf", "email", "cep") and (
            re.search(r"\bnao tenho\b", t) or (clinica.e_nao(bruto) and len(t.split()) <= 2))
        if recusa or sem_documento:
            ficha[campo] = NAO_INFORMADO
            return True
        achados = extrair_cadastro(bruto, campo_esperado=campo)
        for c, v in achados.items():
            if c == "_aviso":
                ficha["aviso_cadastro"] = v
            elif not ficha.get(c):
                ficha[c] = v
        _rg_que_era_o_cep(ficha)
        return any(c != "_aviso" for c in achados)

    if campo == "tipo_consulta":
        if re.search(r"\bprimeira\b", t) and not re.search(r"\bnao (?:e|eh) (?:a )?primeira\b", t):
            ficha["tipo_consulta"] = "Primeira consulta"
        elif _RX_RETORNO.search(t):
            ficha["tipo_consulta"] = "Retorno"
        elif _RX_PRIMEIRA.search(t) or clinica.e_nao(bruto):
            ficha["tipo_consulta"] = "Primeira consulta"
        else:
            ficha["tipo_consulta"] = bruto[:120]
        return True

    if campo == "exames":
        if re.search(r"\b(?:vou|vai|irei|preciso) fazer\b|\bvou tirar\b|\bainda vou\b", t):
            ficha["exames"] = f"Ainda não ({bruto[:200]})"
        elif _RX_EXAME_NAO.search(t) or clinica.e_nao(bruto) or re.search(r"\b(?:nao|nunca)\b", t):
            # "acho que nao", "ainda nao fiz": negativo em qualquer posicao.
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
        if clinica.e_nao(bruto) and len(t.split()) <= 3:
            ficha["saude"] = "Nada relatado"
        else:
            # "Sim\nHipertensão": o "sim" so responde a pergunta.
            sem_sim = re.sub(r"(?i)^\s*sim\b\s*[,.:;!\-]?\s*(?=\S)", "", bruto, count=1)
            ficha["saude"] = (sem_sim if sem_sim.strip() else bruto)[:300]
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
    ("nome", r"\bnome\b(?! completo)"),
    ("nome_completo", r"\bnome completo\b"),
    ("nascimento", r"\bnascimento\b|\bnasci\b|\bdata de nasc"),
    ("cpf", r"\bcpf\b"),
    ("rg", r"\brg\b|\bidentidade\b"),
    ("email", r"\be-?mail\b"),
    ("cep", r"\bcep\b"),
    ("endereco", r"\bendereco\b|\bmoro\b|\brua\b|\bavenida\b|\bnumero da casa\b"),
    ("cidade", r"\bcidade\b"),
    ("disponibilidade", r"\b(horario|horarios|dia|dias|disponibilidade|turno|periodo)\b"),
    ("tempo_queixa", r"\btempo\b"),
    ("exames", r"\bexames?\b|\btomografia\b|\bradiografia\b|\blaudo\b"),
    ("tipo_consulta", r"\bretorno\b|\bprimeira consulta\b"),
    ("saude", r"\balergia|\bmedicamento|\bremedio|\bdoenca|\bsaude\b"),
    ("queixa", r"\bqueixa\b"),
]
_RX_VALOR_CORRIGIDO = re.compile(
    r"(?i)\s(?:é|e|eh|:|seria|correta é|certa é|para|pra|na verdade é|em)\s+(.+)$")


def campo_citado(texto: str) -> str:
    """O campo de que a correcao fala ("esta faltando meu endereco"), ou ""."""
    t = clinica.normalizar(texto)
    citados = [c for c, rx in _CAMPOS_CORRIGIVEIS if re.search(rx, t)]
    return citados[0] if len(citados) == 1 else ""


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
    if campo in ("cpf", "nascimento", "rg", "email", "cep"):
        # Mesmo leitor do cadastro: CPF conferido, data padronizada.
        dados = extrair_cadastro(texto, campo_esperado=campo)
        if dados.get("_aviso"):
            ficha["aviso_cadastro"] = dados["_aviso"]
        if dados.get(campo):
            ficha[campo] = dados[campo]
            return campo
        return ""
    m = _RX_VALOR_CORRIGIDO.search(texto or "")
    if not m:
        return ""
    valor = m.group(1).strip().strip(".!")
    if not valor:
        return ""
    ficha[campo] = _titulo(valor) if campo in ("nome", "cidade") else valor[:300]
    # O resumo mostra o nome completo no lugar do nome: corrigir "o nome"
    # tem de corrigir o que aparece.
    if campo == "nome" and ficha.get("nome_completo") not in (None, "", NAO_INFORMADO):
        ficha["nome_completo"] = _titulo(valor)
    return campo


# ── Queixa ───────────────────────────────────────────────────────────────────

_RX_FRASE_DE_NOME = re.compile(
    r"(?i)^\s*(?:oi|ola|olá|bom dia|boa tarde|boa noite)?[\s,!.]*"
    r"(?:meu nome [ée]|me chamo|aqui [ée] (?:o|a)|sou (?:o|a))\s+[^\n.!?,]*[.!,]?\s*$")
_RX_FRASE_CUMPRIMENTO = re.compile(
    r"(?i)^\s*(?:oi|ola|olá|opa|bom dia|boa tarde|boa noite|tudo bem|tudo bom)[\s,!?.]*$")


def limpar_queixa(texto: str) -> str:
    """Queixa sem o nome e sem cumprimento junto.

    "Me chamo José / Minha principal queixa é a posição do meu queixo" virava a
    queixa inteira, com o nome dentro (teste do Dr. Fabricio, 06/10).
    """
    partes = [p.strip() for p in re.split(r"[\n]+|(?<=[.!?])\s+", texto or "") if p.strip()]
    uteis = [p for p in partes if not _RX_FRASE_DE_NOME.match(p) and not _RX_FRASE_CUMPRIMENTO.match(p)]
    limpa = " ".join(uteis or partes).strip()
    # "Sou a Ana, preciso tirar o siso" / "Meu nome é Ana e tenho dor": o nome
    # vem na mesma frase da queixa (teste de 22/10).
    m = _RX_NOME_NO_COMECO.match(limpa)
    if m and len(limpa[m.end():].split()) >= 2:
        resto = limpa[m.end():].strip()
        limpa = resto[0].upper() + resto[1:]
    return limpa


_RX_NOME_NO_COMECO = re.compile(
    r"(?i)^\s*(?:(?:oi|ola|olá|bom dia|boa tarde|boa noite)[\s,!.]*)?"
    r"(?:meu nome [ée]|me chamo|aqui [ée] (?:o|a)|sou (?:o|a))\s+"
    rf"[{_LETRAS}]+(?:\s+(?!e\s)[{_LETRAS}]+){{0,3}}\s*(?:[,.;!\-–]+\s*|\s+e\s+)")


# ── Cadastro (nome completo, nascimento, CPF, RG, endereco) ──────────────────

_RX_CPF = re.compile(r"(?<!\d)(\d{3})[.\s]?(\d{3})[.\s]?(\d{3})[-.\s]?(\d{2})(?!\d)")
_RX_DATA = re.compile(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})(?!\d)")
_RX_ROTULO = re.compile(
    r"(?im)^[\s•*·\-–]*(nome(?: completo)?|data de nascimento|nascimento|data nasc\w*|dn|cpf|rg|identidade"
    r"|e-?mail|endere[cç]o(?: completo| com cep)?|end\.?|cep)\s*[:=\-]\s*(.+?)\s*$")
_ROTULO_CAMPO = {
    "nome": "nome_completo", "nome completo": "nome_completo",
    "data de nascimento": "nascimento", "nascimento": "nascimento", "dn": "nascimento",
    "cpf": "cpf", "rg": "rg", "identidade": "rg", "endereco": "endereco", "endereço": "endereco",
    "endereco completo": "endereco", "endereco com cep": "endereco", "end": "endereco",
    "end.": "endereco", "e-mail": "email", "email": "email", "cep": "cep",
}
_RX_EMAIL = re.compile(r"(?i)\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# CEP com hifen ("76820-000", "76.820-000") ou com a palavra CEP. Oito
# digitos soltos podem ser RG: sem o rotulo, nao viram CEP.
_RX_CEP = re.compile(r"(?i)(?:\bcep\b\s*[:.\-]?\s*(\d{2}\.?\d{3}-?\d{3})|(?<![\d.])(\d{2}\.?\d{3}-\d{3})(?![\d-]))")


def _formatar_cep(bruto: str) -> str:
    d = re.sub(r"\D", "", bruto)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else ""

# O paciente copia a mensagem do pedido e preenche por cima (teste do Dr.
# Fabricio, 12/10): a frase da assistente e o item que ficou sem resposta
# ("• Endereço completo (rua, número, bairro e cidade)") voltam junto. O item
# vazio virava o endereco "rua, número, bairro e cidade)" e o cadastro dava
# como completo sem o endereco.
_RX_TEXTO_DO_PEDIDO = re.compile(
    r"(?i)vou precisar de alguns dados|pode me enviar|para completar o seu cadastro|"
    r"ainda preciso de|leve no dia da avalia|sem problema, isso pode ser visto|"
    r"pre-cadastro|pré-cadastro|seguintes informa")
_PALAVRAS_DO_MODELO = {"rua", "numero", "bairro", "cidade", "e", "completo", "endereco",
                       "nome", "data", "de", "nascimento", "cpf", "rg", "com", "cep",
                       "mail", "email"}


def _so_modelo(valor: str) -> bool:
    """O valor e so o texto do pedido (sem dado nenhum do paciente)?"""
    palavras = re.findall(r"[a-z0-9]+", clinica.normalizar(valor))
    return not palavras or all(p in _PALAVRAS_DO_MODELO for p in palavras)


def _sem_texto_do_pedido(texto: str) -> str:
    """Tira da mensagem as linhas copiadas do pedido de cadastro."""
    linhas = []
    for linha in (texto or "").splitlines():
        limpa = linha.strip().lstrip("•*·-– ").strip()
        if not limpa or _RX_TEXTO_DO_PEDIDO.search(limpa):
            continue
        # Item sem resposta: o rotulo da lista, sem ":" e sem dado.
        if ":" not in limpa and _so_modelo(limpa):
            continue
        linhas.append(linha)
    return "\n".join(linhas)
_RX_ENDERECO = re.compile(
    r"(?i)\b(rua|r\.|av\.?|avenida|travessa|tv\.|alameda|rodovia|estrada|bairro|quadra|qd\.?|lote|"
    r"condom[ií]nio|residencial|setor|n[º°o]\s*\d|numero|número)\b")
_RX_RG = re.compile(r"(?i)\b(?:rg|identidade)\s*(?:n[º°o.]*)?\s*(?:[:\-]|é|e|eh)?\s*([\dxX][\d.\-xX]{3,14})")


def cpf_valido(digitos: str) -> bool:
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return False
    for n in (9, 10):
        soma = sum(int(digitos[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10 % 11) % 10 != int(digitos[n]):
            return False
    return True


def _formatar_cpf(d: str) -> str:
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def _data(m: re.Match) -> str:
    dia, mes, ano = m.group(1), m.group(2), m.group(3)
    if len(ano) == 2:
        ano = ("19" if int(ano) > 30 else "20") + ano
    if not (1 <= int(dia) <= 31 and 1 <= int(mes) <= 12 and 1900 <= int(ano) <= 2100):
        return ""
    return f"{int(dia):02d}/{int(mes):02d}/{ano}"


def _eh_nome_completo(trecho: str) -> bool:
    # "nao tenho", "sim", "nao sei" sao resposta, nao nome.
    if clinica.e_nao(trecho) or clinica.e_sim(trecho) or clinica.e_nao_sabe(trecho):
        return False
    if any(clinica.normalizar(p) in (_PARADAS_NOME - _PARTICULAS) for p in trecho.split()):
        return False
    palavras = [p for p in trecho.split() if p.lower() not in _PARTICULAS]
    return (len(palavras) >= 2 and bool(re.fullmatch(rf"[{_LETRAS}\s'-]+", trecho))
            and not _RX_ENDERECO.search(trecho) and not clinica.classificar_areas(trecho))


def extrair_cadastro(texto: str, campo_esperado: str = "") -> dict:
    """Le os dados do cadastro numa mensagem so, em qualquer ordem.

    Aceita com rotulo ("CPF: 123...") ou sem ("José da Silva, 12/03/1990,
    123.456.789-09, RG 1234567, Rua X, 123, Centro, Porto Velho"). Uma resposta
    seca a pergunta de um campo so ("12/03/1990") vale para aquele campo.
    """
    achados: dict = {}
    texto = _sem_texto_do_pedido(texto)
    resto = texto

    for rotulo, valor in _RX_ROTULO.findall(resto):
        campo = _ROTULO_CAMPO.get(clinica.normalizar(rotulo).rstrip("."), "")
        if campo and valor and not _so_modelo(valor):
            achados[campo] = valor.strip()
    resto = _RX_ROTULO.sub(" ", resto)

    # E-mail e CEP saem do texto antes de tudo: o CEP com hifen virava RG e o
    # e-mail virava pedaco de nome.
    if "email" in achados:
        m = _RX_EMAIL.search(achados["email"])
        if m:
            achados["email"] = m.group(0).lower()
        elif not re.search(r"\bnao tenho\b", clinica.normalizar(achados["email"])):
            achados.pop("email")
    m = _RX_EMAIL.search(resto)
    if m:
        achados.setdefault("email", m.group(0).lower())
        resto = resto.replace(m.group(0), " ")
    # RG com rotulo antes do CEP: "RG 12.345-678" tem o formato de um CEP.
    m = _RX_RG.search(resto)
    if m and "rg" not in achados:
        achados["rg"] = m.group(1).strip(".-")
        resto = resto.replace(m.group(0), " ")
    if "cep" in achados:
        cep = _formatar_cep(achados["cep"])
        if cep:
            achados["cep"] = cep
        else:
            achados.pop("cep")
    for m in list(_RX_CEP.finditer(resto)):
        cep = _formatar_cep(m.group(1) or m.group(2))
        if cep:
            achados.setdefault("cep", cep)
            resto = resto.replace(m.group(0), " ")
    aviso_cpf = "O CPF informado parece ter algum número trocado. Pode conferir?"
    # CPF com rotulo: confere o digito verificador e padroniza.
    if "cpf" in achados:
        dig = re.sub(r"\D", "", achados["cpf"])
        if cpf_valido(dig):
            achados["cpf"] = _formatar_cpf(dig)
        else:
            achados.pop("cpf")
            achados["_aviso"] = aviso_cpf
    # CPF sem rotulo: 11 digitos no formato de CPF. Invalido, ele e avisado e
    # sai do texto - antes um CPF errado virava o RG.
    for m in _RX_CPF.finditer(resto):
        dig = "".join(m.groups())
        if cpf_valido(dig) and "cpf" not in achados:
            achados["cpf"] = _formatar_cpf(dig)
        elif not cpf_valido(dig) and "cpf" not in achados:
            achados["_aviso"] = aviso_cpf
        resto = resto.replace(m.group(0), " ")

    if "nascimento" in achados:
        m = _RX_DATA.search(achados["nascimento"])
        if m and _data(m):
            achados["nascimento"] = _data(m)
    m = _RX_DATA.search(resto)
    if m and "nascimento" not in achados and _data(m):
        achados["nascimento"] = _data(m)
        resto = resto.replace(m.group(0), " ")

    m = _RX_RG.search(resto)
    if m and "rg" not in achados:
        achados["rg"] = m.group(1).strip(".-")
        resto = resto.replace(m.group(0), " ")

    # O que sobrou, por pedaco: endereco a partir da palavra de logradouro;
    # nome completo e o trecho so de letras com duas palavras ou mais.
    resto = re.sub(r"(?i)\b(cpf|rg|nascimento|endere[cç]o|nome completo|e-?mail|cep)\b", " ", resto)
    if "endereco" not in achados:
        m = _RX_ENDERECO.search(resto)
        if m:
            achado = " ".join(resto[m.start():].replace("\n", ", ").split()).strip(" ,;.")
            if not _so_modelo(achado):
                achados["endereco"] = achado
            resto = resto[:m.start()]
    pedacos = [p.strip(" .;-") for p in re.split(r"[\n,;]+", resto) if p.strip(" .;-")]
    if "nome_completo" not in achados:
        for p in pedacos:
            if _eh_nome_completo(p):
                achados["nome_completo"] = _titulo(p)
                pedacos.remove(p)
                break
    if "rg" not in achados:
        for p in pedacos:
            so_rg = re.fullmatch(r"[\dxX][\d.\-xX]{3,14}", p.replace(" ", ""))
            if so_rg and len(re.sub(r"\D", "", p)) >= 5:
                achados["rg"] = p.replace(" ", "")
                break

    # Resposta seca a pergunta de um campo so ("Rua X, 10" sem palavra-chave).
    if campo_esperado and campo_esperado not in achados and not achados.get("_aviso"):
        limpo = (texto or "").strip()
        if (campo_esperado == "endereco" and len(limpo) >= 8 and re.search(r"\d", limpo)
                and not _so_modelo(limpo)):
            achados["endereco"] = " ".join(limpo.split())
            # "Rio Madeira, 15": o nome da rua nao e o nome do paciente.
            if not _RX_ROTULO.search(texto or ""):
                achados.pop("nome_completo", None)
        elif campo_esperado == "nome_completo" and _eh_nome_completo(limpo):
            achados["nome_completo"] = _titulo(limpo)
        elif campo_esperado == "cep" and _formatar_cep(limpo) and re.fullmatch(r"[\d.\-\s]+", limpo):
            # Resposta seca a "Qual é o CEP?": oito digitos valem, sem hifen.
            achados["cep"] = _formatar_cep(limpo)

    if achados.get("endereco"):
        _separar_cep_do_endereco(achados)
    if "nome_completo" in achados:
        achados["nome_completo"] = _titulo(achados["nome_completo"])
    return achados


# Dentro do endereco, oito digitos soltos so podem ser o CEP ("Rua Angico,
# 3170 - Eletronorte 76808526", teste de 22/10).
_RX_CEP_NO_ENDERECO = re.compile(r"(?<![\d.\-])(\d{8})(?![\d\-])")
_RX_NUMERO_LONGO = re.compile(r"(?<![\d.\-])(\d{6,12})(?![\d\-])")


def _separar_cep_do_endereco(achados: dict) -> None:
    """"Rua X, 10, Centro, CEP 76820-000": o CEP vai para o campo dele."""
    endereco = achados["endereco"]
    for m in list(_RX_CEP.finditer(endereco)) + list(_RX_CEP_NO_ENDERECO.finditer(endereco)):
        cep = _formatar_cep(next(g for g in m.groups() if g))
        if cep:
            achados.setdefault("cep", cep)
            endereco = endereco.replace(m.group(0), " ")
    # "Rua Angico, 3170 - Eletronorte 76808526 e 1234567 e ana@email.com"
    # (teste de 22/10): numero com 6+ digitos nao e o numero da casa - e o RG
    # que veio na mesma linha.
    for m in list(_RX_NUMERO_LONGO.finditer(endereco)):
        if "rg" not in achados:
            achados["rg"] = m.group(1)
        endereco = endereco.replace(m.group(0), " ")
    endereco = re.sub(r"(?:\s+e)+\s*$", "", " ".join(endereco.split()))
    endereco = re.sub(r"\s+e(?:\s+e)+\s+", " e ", endereco)
    achados["endereco"] = endereco.strip(" ,;.-")


def _rg_que_era_o_cep(ficha: dict) -> None:
    """Oito digitos soltos na lista do cadastro viram RG; se depois o CEP vem
    com os mesmos digitos, aquele numero era o CEP e o RG ainda falta."""
    rg = re.sub(r"\D", "", str(ficha.get("rg") or ""))
    cep = re.sub(r"\D", "", str(ficha.get("cep") or ""))
    if rg and rg == cep:
        ficha["rg"] = ""
        t = dict(ficha.get("tentativas") or {})
        t.pop("rg", None)
        ficha["tentativas"] = t
