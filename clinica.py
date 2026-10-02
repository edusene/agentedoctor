"""
clinica.py — Base de conhecimento do Dr. Fabrício Guimarães TRAVADA em código.

Fonte: knowledge/base_conhecimento_dr_fabricio.md (transcrição fiel do PDF
"Base_de_Conhecimento_Agente_IA_Dr_Fabricio_Guimaraes.pdf").

Por que em código e não só no prompt: o que está aqui não pode oscilar. Preço,
emergência, "biópsia é câncer?", pedido de remédio, pedido para interpretar
exame, promessa de resultado e a matriz de triagem têm resposta ÚNICA — a do
documento. O modelo nunca é consultado nesses casos, e quando ele responde
outra coisa (dúvida aberta sobre um procedimento), a resposta dele passa por
conferir_resposta() antes de chegar ao paciente.

Regra de ouro (seção 19): o agente pode explicar procedimentos, mas não pode
determinar sozinho qual procedimento o paciente deve realizar.
"""

from __future__ import annotations

import os
import re
import unicodedata

PROFISSIONAL = "Dr. Fabrício"
PROFISSIONAL_COMPLETO = "Dr. Fabrício Guimarães"
ESPECIALIDADE = "cirurgia bucomaxilofacial"


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento, espaços simples. Toda comparação passa por aqui."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[“”\"']", " ", t)
    return " ".join(t.split())


def _rx(*padroes: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in padroes))


# ── Informações da clínica (seção 20: inserir antes da produção) ─────────────
# O documento manda NÃO inventar local, valores, convênios nem horários. Onde
# nada for configurado, a resposta é a de encaminhar para a equipe.

def info_clinica(chave: str) -> str:
    return (os.getenv(f"CLINICA_{chave.upper()}", "") or "").strip()


# ── Respostas-padrão (texto exato do documento) ──────────────────────────────

# Seção 15.
RESPOSTA_PRECO = (
    "O valor pode variar de acordo com o procedimento indicado, a complexidade do "
    "caso, os exames necessários e o planejamento cirúrgico. Por isso, o Dr. "
    "Fabrício precisa avaliar o caso antes de definir o tratamento e o orçamento. "
    "Posso te orientar sobre como funciona a avaliação e verificar as opções de "
    "agendamento."
)

# Seção 16 (primeiro parágrafo). O segundo parágrafo do documento é a pergunta
# da queixa, que é feita pelo funil (PERGUNTAS["queixa"]).
RESPOSTA_VOCE_FAZ = (
    "Sim, o Dr. Fabrício atua na área de cirurgia bucomaxilofacial e realiza "
    "procedimentos relacionados à face, boca e estruturas maxilofaciais. A "
    "indicação e a técnica adequada dependem da avaliação individual de cada "
    "paciente."
)

# Seção 17.
RESPOSTA_NAO_SEI = (
    "Sem problema. Você não precisa saber o nome do procedimento. Me explique o "
    "que está te incomodando ou o que aconteceu, e eu vou entender melhor a sua "
    "necessidade para direcionar o atendimento ao Dr. Fabrício."
)

# Seção 3, dúvida crítica.
RESPOSTA_BIOPSIA_CANCER = (
    "Não. A biópsia é uma ferramenta de investigação. A natureza da lesão depende "
    "de avaliação adequada e, quando indicada, da análise do tecido."
)

# Seção 11, dúvida crítica.
RESPOSTA_TUMOR_CANCER = (
    "Não. O termo pode se referir a um crescimento anormal e não determina, "
    "sozinho, malignidade. A definição depende da investigação, feita na "
    "avaliação com o Dr. Fabrício."
)

# Seção 11 + regra: "pode ser maligno?" NÃO recebe "Não" - isso afirmaria
# benignidade. O documento diz que podem ser benignas ou malignas.
RESPOSTA_PODE_SER_MALIGNO = (
    "Alterações como cistos e tumores podem ser benignas ou malignas, e essa "
    "definição só é possível com a investigação adequada. Por isso, a avaliação "
    "do Dr. Fabrício é importante para entender o seu caso."
)

# Seção 1 + 19: não fechar diagnóstico, não definir indicação cirúrgica.
RESPOSTA_DIAGNOSTICO = (
    "Não consigo afirmar isso por aqui. Só a avaliação do Dr. Fabrício, com os "
    "exames adequados, pode definir o que está acontecendo e qual tratamento é "
    "indicado para o seu caso."
)

# Seção 1: não prescrever medicamentos.
RESPOSTA_MEDICAMENTO = (
    "Não posso indicar nem prescrever medicamentos por aqui. Essa orientação "
    "precisa ser feita pelo Dr. Fabrício, depois de avaliar o seu caso. Se a dor "
    "ou o inchaço estiverem fortes ou piorando, procure atendimento presencial."
)

# Seção 1: não interpretar exame como diagnóstico.
RESPOSTA_EXAME = (
    "Não consigo interpretar exames por aqui. A análise de radiografias, "
    "tomografias e laudos é feita pelo Dr. Fabrício na avaliação. Vou deixar "
    "registrado que você já tem exame."
)

# Resposta para arquivo recebido (foto, PDF de laudo etc.).
RESPOSTA_ARQUIVO_RECEBIDO = (
    "Recebi o seu arquivo. Não consigo interpretar exames por aqui: ele será "
    "avaliado pelo Dr. Fabrício na consulta. Vou deixar registrado que você já "
    "tem exame."
)

# Seção 1: não prometer resultado ou ausência de riscos.
RESPOSTA_GARANTIA = (
    "Todo procedimento tem indicações, cuidados e riscos que variam de pessoa "
    "para pessoa, e não é possível garantir resultado. O Dr. Fabrício explica "
    "tudo isso na avaliação, de acordo com o seu caso."
)

# Seção 5: o agente não deve tentar resolver uma emergência pelo chat.
RESPOSTA_EMERGENCIA = (
    "Pelo que você descreveu, isso precisa de atendimento imediato. Procure "
    "agora um pronto-socorro ou hospital, ou ligue para o SAMU (192). Não é "
    "possível resolver uma emergência por aqui. Vou avisar a equipe do Dr. "
    "Fabrício para acompanhar o seu caso."
)

# Seção 5, triagem de trauma: primeiro descartar sinais de gravidade.
PERGUNTA_SINAIS_GRAVIDADE = (
    "Para eu direcionar com prioridade: neste momento há sangramento, "
    "dificuldade para respirar, alteração na visão, mudança na mordida ou "
    "dificuldade para abrir a boca?"
)

RESPOSTA_VIDEO = (
    "Não consigo abrir vídeos por aqui. Pode me escrever ou mandar um áudio "
    "contando o que está acontecendo?"
)

RESPOSTA_AUDIO_FALHOU = (
    "Não consegui ouvir o seu áudio. Pode me escrever, por favor?"
)

RESPOSTA_INFO_PENDENTE = (
    "Essa informação a equipe do Dr. Fabrício confirma para você por aqui."
)

# Quando o modelo falha ou a resposta dele é barrada sem categoria específica.
RESPOSTA_DUVIDA_GENERICA = (
    "Essa é uma dúvida importante, e a resposta depende do seu caso. O Dr. "
    "Fabrício esclarece isso na avaliação."
)

# Seção 18: ... AGENDAMENTO → CONFIRMAÇÃO → ORIENTAÇÕES PRÉ-CONSULTA.
RESPOSTA_ENCAMINHADO = (
    "Perfeito! Sua solicitação foi encaminhada à equipe do Dr. Fabrício, que vai "
    "confirmar o dia e o horário da sua avaliação por aqui mesmo."
)


def orientacoes_pre_consulta() -> str:
    """Seção 18. O protocolo real da clínica entra por CLINICA_ORIENTACOES."""
    return info_clinica("orientacoes") or (
        "Para a avaliação, leve seus exames (radiografia, tomografia, laudos) e o "
        "encaminhamento do seu dentista ou médico, se tiver. Se usa medicamentos, "
        "leve também a lista deles."
    )


def resposta_preco() -> str:
    valor = info_clinica("valor_avaliacao")
    if valor:
        return f"{RESPOSTA_PRECO}\n\nA consulta de avaliação tem o valor de {valor}."
    return RESPOSTA_PRECO


def resposta_endereco() -> str:
    end = info_clinica("endereco")
    return f"O atendimento é em: {end}." if end else RESPOSTA_INFO_PENDENTE


def resposta_horario() -> str:
    h = info_clinica("horario")
    return f"O horário de atendimento é: {h}." if h else RESPOSTA_INFO_PENDENTE


def resposta_convenio() -> str:
    c = info_clinica("convenios")
    return f"Sobre convênios: {c}." if c else RESPOSTA_INFO_PENDENTE


# ── Áreas (seções 2 a 11) ────────────────────────────────────────────────────
# `gatilhos` sao regex sobre o texto NORMALIZADO (sem acento). `acolhimento` e
# a resposta travada quando a queixa aparece: explica sem concluir. `pergunta`
# e a pergunta de qualificacao especifica da area, tirada da lista "Perguntas"
# do documento (as genericas - tempo, exames, avaliacao - ficam no funil).

AREAS: dict[str, dict] = {
    "trauma": {
        "nome": "Tratamento de fraturas ósseas da face",
        "secao": 5,
        "acao": "Prioridade/urgência",
        "gatilhos": _rx(
            r"quebr\w* (a |o |minha |meu )?(mandibula|maxilar|queixo|osso do rosto|rosto|nariz|face)",
            r"fratur", r"trauma (no|na) (rosto|face|boca)", r"acidente",
            r"(levei|tomei) (um )?(soco|pancada|chute)", r"pancada (no|na) (rosto|boca|queixo)",
            r"bati (o |a |com o |com a )?(rosto|boca|queixo|cara)", r"cai e bati",
        ),
        "acolhimento": "Sinto muito pelo ocorrido.",
        "pergunta": "Quando aconteceu e você já foi atendido(a) em algum hospital?",
        "pergunta_exames": "Você fez tomografia ou radiografia depois do trauma?",
        "pergunta_indicacao": "Algum médico ou dentista já confirmou se houve fratura?",
    },
    "patologia": {
        "nome": "Cistos e tumores odontogênicos",
        "secao": 11,
        "acao": "Avaliação especializada",
        "gatilhos": _rx(
            r"\bcisto", r"\btumor", r"imagem escura", r"mancha escura no (raio|rx|exame)",
            r"lesao (na|no) (mandibula|maxila|osso)", r"ameloblastoma", r"queratocisto",
        ),
        "acolhimento": (
            "Entendi. Cistos e outras alterações nos ossos da face precisam de "
            "avaliação especializada. O Dr. Fabrício vai analisar os exames e "
            "definir a investigação adequada."
        ),
        "pergunta": "Em qual região fica? Você sente dor, aumento de volume ou alteração de sensibilidade?",
        "pergunta_exames": "Em qual exame isso apareceu (radiografia, tomografia)? Você tem o laudo?",
        "pergunta_indicacao": "Quem identificou essa alteração: dentista ou médico? Já foi feita biópsia?",
    },
    "biopsia": {
        "nome": "Biópsias",
        "secao": 3,
        "acao": "Avaliação",
        "gatilhos": _rx(
            r"biopsia", r"bolinha (na|no|dentro da) (boca|lingua|labio|gengiva|bochecha)",
            r"ferida (na|no|dentro da) (boca|lingua|labio|gengiva)", r"ferida que nao (cicatriza|sara|fecha)",
            r"mancha (na|no) (boca|lingua|labio|gengiva|bochecha)", r"nodulo", r"caroco (na|no) (boca|lingua|labio|gengiva)",
            r"lesao (na|no) (boca|lingua|labio|gengiva|bochecha)", r"afta que nao (sara|passa|cicatriza)",
        ),
        "acolhimento": (
            "Entendi, obrigado por contar. Alterações como essa precisam ser "
            "avaliadas pessoalmente pelo Dr. Fabrício, que vai definir se há "
            "necessidade de investigação."
        ),
        "pergunta": "Onde fica essa alteração? Ela cresceu, dói ou sangra?",
        "pergunta_exames": "Você tem algum exame ou encaminhamento sobre essa alteração?",
        "pergunta_indicacao": "Algum dentista ou médico já viu essa alteração ou recomendou biópsia?",
    },
    "enxerto": {
        "nome": "Enxerto ósseo",
        "secao": 4,
        "acao": "Avaliar + exames",
        "gatilhos": _rx(
            r"enxerto", r"(nao tenho|sem|falta de|pouco) osso", r"perdi (o )?osso",
            r"perda ossea", r"osso (para|pra) (o )?implante",
        ),
        "acolhimento": (
            "Entendi. Nem todo paciente de implante precisa de enxerto: existem "
            "diferentes materiais e técnicas, e o planejamento depende da avaliação "
            "do Dr. Fabrício."
        ),
        "pergunta": "É para colocar implante? Em qual região e quando você perdeu o dente?",
        "pergunta_exames": "Você já tem tomografia da região?",
        "pergunta_indicacao": "Quem te informou sobre a perda de osso: seu dentista ou implantodontista?",
    },
    "exodontia": {
        "nome": "Exodontias / extrações",
        "secao": 2,
        "acao": "Qualificar + agendar",
        "gatilhos": _rx(
            r"\bsiso", r"dente do juizo", r"terceiro molar", r"extra(ir|cao|coes)", r"exodontia",
            r"(tirar|arrancar|remover) (o |um |uns |os |meu |meus |dois |2 )?(dente|dentes|siso)",
            r"dente (esta |ta )?incluso", r"\bincluso", r"dente (quebrou|quebrado|rachou|partiu)",
        ),
        "acolhimento": (
            "Entendi. O Dr. Fabrício realiza extrações simples e cirúrgicas, "
            "inclusive de siso. A forma de remoção depende da posição do dente, das "
            "raízes e da complexidade, e isso é definido na avaliação."
        ),
        "pergunta": "Qual dente é? E você está com dor ou inchaço?",
        "pergunta_exames": "Você já tem radiografia (panorâmica) ou tomografia desse dente?",
        "pergunta_indicacao": "Foi o seu dentista que indicou a extração, ou você veio por conta própria?",
    },
    "ortognatica": {
        "nome": "Cirurgia ortognática",
        "secao": 6,
        "acao": "Avaliação",
        "gatilhos": _rx(
            r"ortognatica", r"mordida (nao encaixa|aberta|cruzada|torta|errada)",
            r"(mandibula|queixo) (e |esta |ta |fica |muito )*(para|pra) frente", r"mandibula (e |esta |muito )*(grande|projetada)",
            r"prognatismo", r"assimetria (facial|do rosto|no rosto)", r"rosto torto",
        ),
        "acolhimento": (
            "Entendi. Alterações de mordida e de posição dos ossos da face são "
            "avaliadas pelo Dr. Fabrício, muitas vezes em conjunto com o "
            "ortodontista. Só a avaliação define o tratamento indicado."
        ),
        "pergunta": "Você usa ou já usou aparelho ortodôntico? Tem ortodontista?",
        "pergunta_exames": "Você já tem exames ou planejamento feitos com o ortodontista?",
        "pergunta_indicacao": "Você já recebeu indicação de cirurgia ortognática ou já consultou um cirurgião bucomaxilofacial?",
    },
    "mentoplastia": {
        "nome": "Mentoplastia",
        "secao": 9,
        "acao": "Avaliação",
        "gatilhos": _rx(
            r"mentoplastia", r"genioplastia",
            r"queixo (e |esta |ta |fica |muito |bem )*(pequeno|para tras|pra tras|retraido|grande|projetado|apagado)",
            r"perfil (sem definicao|reto|feio)", r"desproporcao (facial|do rosto)",
        ),
        "acolhimento": (
            "Entendi. Queixas sobre a forma ou a projeção do queixo são avaliadas "
            "pelo Dr. Fabrício, que vai entender se a questão é só do queixo ou "
            "também envolve a mordida."
        ),
        "pergunta": "O incômodo é mais de frente ou de perfil? Você percebe alguma alteração na mordida?",
        "pergunta_exames": "Você possui exames da face ou da mordida?",
        "pergunta_indicacao": "Você já fez cirurgia ortognática ou outra avaliação sobre o queixo?",
    },
    "lift_facial": {
        "nome": "Lift facial / Facelift",
        "secao": 7,
        "acao": "Avaliação",
        "gatilhos": _rx(
            r"lift facial", r"face ?lift", r"rosto (esta |ta )?caido", r"flacidez (facial|no rosto|do rosto)",
            r"bochecha caida", r"jowls?", r"rosto flacido", r"(aparencia|rosto) envelhecid",
        ),
        "acolhimento": (
            "Entendi. A flacidez facial é avaliada pelo Dr. Fabrício, que vai "
            "entender o que mais contribui para o que te incomoda antes de indicar "
            "qualquer tratamento."
        ),
        "pergunta": "O que mais te incomoda é a flacidez ou a perda de volume? Em qual região?",
        "pergunta_exames": "Você tem alguma avaliação ou exame anterior sobre isso?",
        "pergunta_indicacao": "Você já fez procedimentos ou cirurgias faciais antes?",
    },
    "lift_cervical": {
        "nome": "Lift cervical",
        "secao": 8,
        "acao": "Avaliação",
        "gatilhos": _rx(
            r"lift cervical", r"pescoco (esta |ta )?(flacido|caido)", r"flacidez (no|do) pescoco",
            r"pescoco de peru", r"pele (sobrando )?(no|do|abaixo do) (pescoco|queixo)",
        ),
        "acolhimento": (
            "Entendi. O incômodo no pescoço pode ter causas diferentes, como pele, "
            "gordura ou estrutura óssea, e a avaliação do Dr. Fabrício define a "
            "melhor abordagem."
        ),
        "pergunta": "O que mais incomoda no pescoço: a flacidez da pele, a gordura ou o contorno?",
        "pergunta_exames": "Você tem alguma avaliação ou exame anterior sobre isso?",
        "pergunta_indicacao": "Você já fez algum procedimento no rosto ou no pescoço?",
    },
    "papada": {
        "nome": "Lipo de papada",
        "secao": 10,
        "acao": "Não diagnosticar; avaliar",
        "gatilhos": _rx(
            r"papada", r"gordura (abaixo|embaixo|debaixo) do queixo", r"gordura no pescoco",
            r"lipo (de|da|na) papada", r"queixo duplo",
        ),
        "acolhimento": (
            "Entendi. A papada pode ter causas diferentes, como gordura, flacidez, "
            "excesso de pele ou a posição do queixo, por isso a avaliação do Dr. "
            "Fabrício é importante antes de definir qualquer tratamento."
        ),
        "pergunta": "Você percebe mais gordura, flacidez ou excesso de pele nessa região?",
        "pergunta_exames": "Você tem alguma avaliação ou exame anterior sobre isso?",
        "pergunta_indicacao": "Você já fez algum procedimento na região da papada?",
    },
}

# Ordem de prioridade quando a mensagem cai em mais de uma área: risco clínico
# primeiro (seção 19: quanto maior o risco, menos conclusão e mais avaliação).
PRIORIDADE_AREAS = [
    "trauma", "patologia", "biopsia", "enxerto", "exodontia",
    "ortognatica", "mentoplastia", "lift_facial", "lift_cervical", "papada",
]


def classificar_areas(texto: str) -> list[str]:
    """Áreas prováveis da seção 12 (matriz de triagem), por prioridade."""
    t = normalizar(texto)
    return [a for a in PRIORIDADE_AREAS if AREAS[a]["gatilhos"].search(t)]


# ── Emergência (seção 5) ─────────────────────────────────────────────────────

# Sinais que valem sozinhos, com ou sem trauma.
_EMERGENCIA_FORTE = _rx(
    r"(dificuldade|dificil) (para|pra|de) respirar", r"nao (consigo|to conseguindo|estou conseguindo) respirar",
    r"falta de ar", r"sufocando",
    r"sangr\w* (muito|demais|sem parar|forte)", r"nao para de sangrar", r"muito sangue", r"sangramento (forte|intenso|que nao para)",
    r"(alteracao|perda|mudanca|problema) (na|da) visao", r"visao (dupla|embacada|turva)", r"vendo (dobrado|duplo)",
    r"nao (consigo|to conseguindo) (enxergar|ver)", r"desmai", r"perdi a consciencia", r"desacordado",
    r"(dificuldade|dificil) (para|pra|de) engolir", r"nao consigo engolir",
    r"inchaco (no|na|chegando no|chegando na) (pescoco|garganta|olho)",
)

# Sinais de gravidade que, com trauma, indicam emergência (seção 5).
_GRAVIDADE_TRAUMA = _rx(
    r"sangr", r"mordida (mudou|torta|nao (fecha|encaixa))", r"dente(s)? (nao )?encaixa",
    r"nao (consigo|to conseguindo) abrir a boca", r"(dificuldade|dificil) (para|pra|de) abrir a boca",
    r"respirar", r"visao",
)


def e_emergencia(texto: str, contexto_trauma: bool = False) -> bool:
    t = normalizar(texto)
    if _EMERGENCIA_FORTE.search(t):
        return True
    return bool(contexto_trauma and _GRAVIDADE_TRAUMA.search(t))


# ── Sim / não ────────────────────────────────────────────────────────────────

_SIM = _rx(
    r"^(sim|s|ss|isso|isso mesmo|pode|pode sim|pode ser|claro|com certeza|ok|okay|certo|"
    r"correto|confirmo|confirmado|esta certo|ta certo|tudo certo|exato|exatamente|perfeito|"
    r"yes|aham|uhum|beleza|blz|positivo|pode encaminhar|encaminha|manda)\b",
)
_NAO = _rx(r"^(nao|n|nop|negativo|nenhum|nenhuma|nada|nunca)\b", r"^(ainda )?nao\b")


def e_sim(texto: str) -> bool:
    t = normalizar(texto).strip(" .!")
    return bool(_SIM.search(t)) and not e_nao(texto)


def e_nao(texto: str) -> bool:
    t = normalizar(texto).strip(" .!")
    return bool(_NAO.search(t))


# ── Intenção (seção 13) ──────────────────────────────────────────────────────

INTENCOES = ["curiosidade", "interesse", "intencao", "pronto_agendar"]

_PRONTO_AGENDAR = _rx(
    r"\bagend", r"marcar (uma |a )?(consulta|avaliacao|horario)", r"(tem|tenha|ha) (horario|vaga|agenda)",
    r"quero (uma |marcar )?(consulta|avaliacao)", r"(quando|que dia) (posso|consigo) (ir|passar|ser atendid)",
    r"(consulta|avaliacao) (com|para|pra) o (dr|doutor)",
)
_INTENCAO = _rx(
    r"(quero|preciso|gostaria de|queria|pretendo|vou) (fazer|tirar|operar|extrair|resolver|tratar|arrumar|corrigir|colocar|remover)",
    r"tenho interesse em (fazer|tirar|operar)", r"meu dentista (pediu|mandou|encaminhou|indicou)",
    r"(fui|foi) encaminhad",
)
_INTERESSE = _rx(
    r"quanto (custa|fica|sai|e|cobra)", r"\bvalor", r"\bpreco", r"orcamento",
    r"(voce|voces|vcs|o doutor|o dr|ele) (faz|fazem|realiza|realizam|atende|atendem|trabalha)",
)


def classificar_intencao(texto: str) -> str:
    t = normalizar(texto)
    if _PRONTO_AGENDAR.search(t):
        return "pronto_agendar"
    if _INTENCAO.search(t):
        return "intencao"
    if _INTERESSE.search(t):
        return "interesse"
    return "curiosidade"


def intencao_maior(a: str, b: str) -> str:
    """A intenção só sobe: quem já quis agendar não volta a ser curiosidade."""
    ia = INTENCOES.index(a) if a in INTENCOES else 0
    ib = INTENCOES.index(b) if b in INTENCOES else 0
    return INTENCOES[max(ia, ib)]


# ── Respostas travadas por tipo de pergunta ─────────────────────────────────
# Cada entrada: (tipo, regex, função que devolve o texto). A ordem é a ordem em
# que aparecem na resposta quando a mensagem cai em mais de uma.

_RX_PRECO = _rx(
    r"quanto (custa|fica|sai|e|cobra|seria|ficaria)", r"qual (o |e o |seria o )?(valor|preco)",
    r"\bvalor(es)?\b", r"\bpreco", r"orcamento", r"custa quanto", r"parcel", r"\bcaro\b",
)
_RX_VOCE_FAZ = _rx(
    r"(voce|voces|vcs|o doutor|o dr|dr fabricio|doutor fabricio|ele) (faz|fazem|realiza|realizam|trabalha com|mexe com|opera)\b",
    r"(voce|voces|vcs|o doutor|o dr|ele) (atende|atendem) (caso|casos|paciente|quem)",
)
_RX_NAO_SEI = _rx(
    r"nao sei (qual|o que|que|se) .{0,20}(procedimento|tratamento|cirurgia|fazer|preciso|tenho)",
    r"nao sei o nome", r"nao sei (explicar|dizer) o que",
)
_RX_CANCER = _rx(r"cancer", r"maligno", r"malign", r"\bcarcinoma")
_RX_BIOPSIA = _rx(r"biopsia")
_DEFINE = r"(significa|quer dizer|e sinal de|e sinonimo de|indica|e o mesmo que|tem a ver com|e)"
_RX_BIOPSIA_SIGNIFICA = _rx(
    r"^(a |uma |fazer (uma )?|fazer a )?biopsia " + _DEFINE + r" (que (e|tem|seja) )?(um |uma )?(cancer|maligno|tumor maligno)",
    r"(toda|quem faz) biopsia (e|tem) cancer",
)
_RX_TUMOR_SIGNIFICA = _rx(
    r"^(o )?tumor " + _DEFINE + r" (um |uma )?(cancer|maligno)",
    r"(todo|toda) (tumor|cisto) (e|e um|vira) cancer",
    r"(o termo|a palavra) tumor",
)
_RX_TUMOR = _rx(r"\btumor", r"\bcisto")
_RX_DIAGNOSTICO = _rx(
    r"(e|sera|pode ser|seria|acha que e|voce acha) (cancer|grave|maligno|benigno|perigoso|serio)",
    r"o que (eu )?(tenho|sera que (eu )?tenho|pode ser (isso)?)", r"o que e isso",
    r"e caso de cirurgia", r"qual (procedimento|tratamento|cirurgia) (eu )?(preciso|devo|tenho que)",
)
# "Preciso tirar o siso." é intenção; "Preciso tirar o siso?" pede indicação.
# Estes só valem como pergunta.
_RX_INDICACAO_PERGUNTA = _rx(
    r"(eu )?(preciso|vou precisar|tenho que|devo) (mesmo )?(operar|de cirurgia|fazer cirurgia|tirar|extrair|fazer enxerto|fazer biopsia|fazer a cirurgia)",
    r"(tem que|precisa) operar",
)


INTERROGATIVAS = (
    "como ", "o que ", "qual ", "quais ", "quanto", "quando ", "onde ", "por que", "porque ",
    "pode ", "posso ", "da pra", "da para", "demora", "precisa ", "existe ", "e verdade",
    "e possivel", "tem como", "sera ", "doi", "vai doer", "todo ", "toda ", "tem que",
)


def _e_pergunta(texto_original: str, t: str) -> bool:
    return "?" in (texto_original or "") or t.startswith(INTERROGATIVAS)
_RX_MEDICAMENTO = _rx(
    r"(qual|que) (remedio|medicamento|antibiotico|anti-?inflamatorio|analgesico)",
    r"(posso|devo|preciso) tomar", r"o que (eu )?(tomo|posso tomar|devo tomar)", r"\breceita\b",
    r"prescrev", r"passa (um|algum) (remedio|antibiotico)",
    r"dipirona", r"ibuprofeno", r"nimesulida", r"amoxicilina", r"paracetamol", r"\bantibiotico",
    r"cetoprofeno", r"diclofenaco", r"dexametasona", r"tylenol", r"novalgina",
)
_RX_EXAME = _rx(
    r"\b(olha|olhar|ve|ver|veja|avalia|avaliar|analisa|analisar|analise|interpreta|interpretar|le|ler|leia|confere|conferir)\b"
    r"(?: \w+){0,4} (exame|exames|laudo|raio|rx|tomografia|radiografia|panoramica|resultado)",
    r"o que (significa|quer dizer|diz).{0,30}(exame|laudo|raio|rx|tomografia|radiografia|panoramica|resultado)",
    r"(meu|o) (exame|laudo|resultado) (deu|mostrou|mostra|diz|esta)",
)
_RX_GARANTIA = _rx(
    r"(tem|ha|existe|corre) (algum |muito )?risco", r"e (seguro|arriscado|perigoso) (fazer|operar)",
    r"\bgarant", r"vai ficar (perfeito|bom|bonito|igual)", r"(da|vai dar) certo", r"resultado (garantido|certo)",
)

# Dúvidas frequentes de cada área (campos "Dúvidas" das seções 2 a 11), com o
# texto do documento. Vêm antes do modelo: dúvida conhecida não oscila.
FAQ: list[tuple[str, re.Pattern, str]] = [
    ("dor", _rx(r"\b(doi|doe|vai doer|sente dor|sentir dor|e dolorido|da dor)\b", r"anestesia"),
     "A anestesia é utilizada para evitar dor durante o procedimento. Na recuperação "
     "pode haver desconforto e inchaço, e o Dr. Fabrício orienta os cuidados de "
     "acordo com o seu caso."),
    ("siso_todo", _rx(r"(todo|todos os|tod[oa]s? [oa]s?) siso", r"siso (sempre )?(precisa|tem que) (ser )?(tirar|tirado|remov|extra)",
                      r"(precisa|tem que) (mesmo )?tirar (o )?siso"),
     "Nem todo siso precisa ser removido. A indicação depende da avaliação do Dr. Fabrício."),
    ("varias_extracoes", _rx(r"(varios|mais de um|todos os|dois|2|tres|3|quatro|4) (dentes|sisos).{0,25}(mesma vez|de uma vez|junto|mesmo dia)",
                             r"(tirar|extrair) (os )?(quatro|4|dois|2|tres|3) (sisos|dentes)"),
     "Múltiplas extrações podem ser possíveis, dependendo da avaliação do Dr. Fabrício."),
    ("enxerto_todo", _rx(r"(todo|toda|sempre).{0,20}implante.{0,25}enxerto", r"implante.{0,25}(precisa|tem que|sempre).{0,15}enxerto",
                         r"(tipo|tipos|material|materiais) de enxerto"),
     "Nem todo paciente de implante precisa de enxerto. Existem diferentes materiais "
     "e técnicas, e o planejamento depende do defeito ósseo e da avaliação."),
    ("fratura_cirurgia", _rx(r"(toda|todas as) fratura", r"fratura.{0,25}(precisa|tem que|sempre).{0,15}(operar|cirurgia)"),
     "Nem toda fratura exige cirurgia. O tratamento depende da localização, do "
     "deslocamento, da gravidade e das condições do paciente. Quando indicado, pode "
     "envolver reposicionamento e estabilização."),
    ("ortognatica_estetica", _rx(r"ortognatica.{0,30}(estetic|beleza|aparencia)", r"(estetic|beleza).{0,30}ortognatica"),
     "A cirurgia ortognática pode produzir mudanças estéticas, mas tem foco nas "
     "relações funcionais e esqueléticas dos maxilares. A ortodontia frequentemente "
     "participa do planejamento."),
    ("ortognatica_tempo", _rx(r"(quanto tempo|demora|duracao|dura).{0,30}(ortognatica|tratamento ortognatico)",
                              r"ortognatica.{0,30}(quanto tempo|demora|dura)"),
     "O tempo total do tratamento ortognático varia conforme o caso, e a ortodontia "
     "frequentemente participa do planejamento."),
    ("mento_vs_orto", _rx(r"mentoplastia.{0,40}(ortognatica|mesma coisa|diferenca|igual)",
                          r"(ortognatica).{0,40}mentoplastia", r"diferenca.{0,30}(queixo|mento).{0,30}(ortognatica)"),
     "Mentoplastia não é o mesmo que cirurgia ortognática. A primeira atua "
     "principalmente no queixo; a segunda corrige as relações dos maxilares e pode "
     "ter objetivos funcionais e esqueléticos mais amplos."),
    ("lift_preenchimento", _rx(r"(lift|facelift).{0,40}(preenchimento|botox|harmonizacao)",
                               r"(preenchimento|harmonizacao).{0,40}(lift|facelift)"),
     "O lift facial não é equivalente a preenchimento. Ele pode melhorar sinais "
     "ligados à flacidez, mas não substitui todos os tratamentos de pele ou de "
     "expressão."),
    ("papada_lipo", _rx(r"lipo.{0,30}(resolve|resolver|tira|acaba).{0,20}papada", r"papada.{0,30}(so|somente|apenas) (com )?lipo",
                        r"papada.{0,30}(resolve|sai|some) com lipo"),
     "Nem toda papada é resolvida por lipo isolada. Flacidez, excesso de pele, "
     "anatomia cervical e posição do queixo podem influenciar o resultado."),
    ("lift_cervical_associado", _rx(r"lift cervical.{0,40}(junto|associad|combina|mesma cirurgia)"),
     "A abordagem pode variar e, em alguns casos, ser associada a outros "
     "procedimentos. A avaliação define a indicação."),
]
_RX_ENDERECO = _rx(r"onde (fica|e|atende)", r"\bendereco", r"localizacao", r"qual (a )?cidade (voce|voces|o doutor) atende")
_RX_HORARIO = _rx(r"horario de (atendimento|funcionamento)", r"que horas (abre|fecha|atende)", r"atende (sabado|domingo|a noite)")
_RX_CONVENIO = _rx(r"convenio", r"plano de saude", r"aceita (plano|unimed|amil|bradesco|sulamerica|hapvida)", r"particular ou")


def respostas_travadas(texto: str) -> list[tuple[str, str]]:
    """Perguntas da mensagem que têm resposta única no documento.

    Devolve [(tipo, texto)] na ordem fixa. Lista vazia = nada travado; a
    dúvida, se houver, vai para o modelo (com RAG e conferência depois).
    """
    t = normalizar(texto)
    saida: list[tuple[str, str]] = []

    # Câncer primeiro: é a dúvida crítica (seções 3 e 11). O "Não" do
    # documento responde só à DEFINIÇÃO ("biópsia significa câncer?"). Sobre o
    # caso do paciente ("pode ser maligno?", "a biópsia deu câncer?") a
    # resposta nunca é "não": seria afirmar benignidade sem diagnóstico.
    if _RX_BIOPSIA_SIGNIFICA.search(t):
        saida.append(("biopsia_cancer", RESPOSTA_BIOPSIA_CANCER))
    elif _RX_TUMOR_SIGNIFICA.search(t):
        saida.append(("tumor_cancer", RESPOSTA_TUMOR_CANCER))
    elif _RX_CANCER.search(t) and _RX_TUMOR.search(t):
        saida.append(("pode_ser_maligno", RESPOSTA_PODE_SER_MALIGNO))
    elif _RX_NAO_SEI.search(t) and not _RX_CANCER.search(t):
        pass  # "nao sei qual procedimento preciso" tem resposta propria (secao 17)
    elif (_RX_CANCER.search(t) or _RX_DIAGNOSTICO.search(t)
          or (_RX_INDICACAO_PERGUNTA.search(t) and _e_pergunta(texto, t))):
        saida.append(("diagnostico", RESPOSTA_DIAGNOSTICO))

    # Duvida frequente so vale como pergunta: "nao doi" e informacao do
    # paciente, nao pedido de explicacao sobre dor.
    if _e_pergunta(texto, t):
        for tipo, rx, resposta in FAQ:
            if rx.search(t):
                saida.append((tipo, resposta))

    if _RX_MEDICAMENTO.search(t):
        saida.append(("medicamento", RESPOSTA_MEDICAMENTO))
    if _RX_EXAME.search(t):
        saida.append(("exame", RESPOSTA_EXAME))
    if _RX_GARANTIA.search(t):
        saida.append(("garantia", RESPOSTA_GARANTIA))
    if _RX_VOCE_FAZ.search(t):
        saida.append(("voce_faz", RESPOSTA_VOCE_FAZ))
    if _RX_PRECO.search(t):
        saida.append(("preco", resposta_preco()))
    if _RX_NAO_SEI.search(t):
        saida.append(("nao_sei", RESPOSTA_NAO_SEI))
    if _RX_ENDERECO.search(t):
        saida.append(("endereco", resposta_endereco()))
    if _RX_HORARIO.search(t):
        saida.append(("horario", resposta_horario()))
    if _RX_CONVENIO.search(t):
        saida.append(("convenio", resposta_convenio()))
    return saida


# ── Conferência da resposta do modelo (regras da seção 1) ───────────────────
# Qualquer frase proibida derruba a resposta INTEIRA do modelo, e no lugar dela
# vai o texto travado da categoria. Consertar só a frase deixaria o resto do
# raciocínio que levou a ela.

_PROIBIDO: list[tuple[str, re.Pattern, str]] = [
    ("diagnostico", _rx(
        r"parece (ser )?(um |uma )?(cancer|tumor|maligno|benigno|cisto|infeccao|fratura)",
        r"nao (e|parece) (nada|grave|cancer|maligno|serio|preocupante)", r"nao deve ser (nada|grave|cancer)",
        r"(isso|que|seu caso|o seu caso|voce) (e|seja) (um |uma )?(cancer|maligno|benigno|tumor maligno)\b",
        r"provavelmente (e|seja|voce tem|se trata de) (um |uma |o |a )?(cancer|cisto|tumor|siso|fratura|infeccao|lesao|benign|malign|caso de)",
        r"com certeza (e|voce tem|se trata)", r"voce (tem|esta com) (um |uma )?(cisto|tumor|fratura|infeccao|lesao|cancer|abscesso)",
        r"nao precisa se preocupar", r"(e|seria) so (um |uma )?\w+ (simples|normal|comum)", r"isso e normal",
        r"(isso|o seu caso|seu caso) (se trata|e) de (um |uma )",
    ), RESPOSTA_DIAGNOSTICO),
    ("indicacao", _rx(
        r"voce (precisa|vai precisar|tera que|tem que|deve|necessita) (fazer |de |realizar |passar por )?(uma |um |o |a )?"
        r"(cirurgia|extracao|exodontia|biopsia|enxerto|ortognatica|mentoplastia|genioplastia|lift|facelift|lipo|implante|operar|operacao|tirar|extrair|remover)",
        r"(o )?(indicado|ideal|recomendado|melhor) (para voce|no seu caso|pra voce|pro seu caso) (e|seria|sera)",
        r"(no seu caso|para voce|pra voce|pro seu caso),? (o )?(indicado|ideal|recomendado|melhor|tratamento) (e|seria|sera)",
        r"seu caso (e|sera|seria) (de|para) (cirurgia|extracao|enxerto|biopsia|ortognatica|lift|lipo)",
        r"(recomendo|indico|sugiro) (que voce )?(fazer|faca|a cirurgia|o procedimento|a extracao|o enxerto|a lipo|o lift)",
    ), RESPOSTA_DIAGNOSTICO),
    ("promessa", _rx(
        r"sem (nenhum |qualquer )?risco", r"risco zero", r"nao (tem|ha|existe) (nenhum )?risco", r"totalmente seguro",
        r"\bgaranti(mos|do|da|a|r)\b", r"\bgaranto\b", r"resultado (perfeito|garantido|certo)", r"100 ?%",
        r"nao (vai doer|doi) nada", r"(fica|vai ficar) perfeito",
    ), RESPOSTA_GARANTIA),
    ("preco", _rx(
        r"r\$ ?\d", r"\d+ ?(mil )?reais", r"a partir de \d", r"(custa|fica|sai) (em torno|cerca|aproximadamente|por volta|uns|umas|mais ou menos)",
        r"em \d+ ?x\b", r"parcel\w* em \d",
    ), None),
    ("medicamento", _rx(
        r"\btome\b", r"\btomar (um|uma|\d)", r"\d+ ?mg\b", r"de \d+ em \d+ ?h", r"a cada \d+ ?h",
        r"dipirona", r"ibuprofeno", r"nimesulida", r"amoxicilina", r"paracetamol", r"antibiotico",
        r"cetoprofeno", r"diclofenaco", r"dexametasona", r"anti-?inflamatorio", r"analgesico",
    ), RESPOSTA_MEDICAMENTO),
    ("exame", _rx(
        r"(seu|no seu|pelo seu|o seu) (exame|raio|rx|tomografia|laudo|radiografia|resultado) (mostra|indica|aparece|revela|sugere|confirma)",
        r"pelo que (vi|aparece|mostra) (no|na)", r"(o|a) (exame|tomografia|radiografia) (mostra|indica) que",
    ), RESPOSTA_EXAME),
    ("vazamento", _rx(
        r"\bprompt", r"base de conhecimento", r"search_knowledge", r"\btool\b", r"modelo de linguagem",
        r"minhas instrucoes", r"fui (programad|treinad)", r"\bchatgpt\b", r"\bopenai\b",
    ), RESPOSTA_DUVIDA_GENERICA),
]


def conferir_resposta(texto_modelo: str) -> tuple[str, list[str]]:
    """Confere a resposta do modelo contra as proibições da seção 1.

    Devolve (texto_final, violacoes). Com violação, o texto do modelo é
    descartado e entra a resposta travada da primeira categoria violada.
    """
    t = normalizar(texto_modelo)
    violacoes = [nome for nome, rx, _ in _PROIBIDO if rx.search(t)]
    if not violacoes:
        return texto_modelo, []
    for nome, _, substituta in _PROIBIDO:
        if nome == violacoes[0]:
            return (substituta or resposta_preco()), violacoes
    return RESPOSTA_DUVIDA_GENERICA, violacoes


def sem_perguntas(texto: str) -> str:
    """Tira as frases interrogativas: quem faz a pergunta do funil é o código."""
    frases = re.split(r"(?<=[.!?])\s+", (texto or "").strip())
    mantidas = [f for f in frases if f and not f.rstrip().endswith("?")]
    return " ".join(mantidas).strip()


# ── Texto da base para o prompt (seções 1, 13, 19) ──────────────────────────

def cartao_da_area(area: str) -> str:
    """Resumo travado de uma área, para o modelo explicar sem sair do documento."""
    a = AREAS.get(area)
    if not a:
        return ""
    return (f"ÁREA PROVÁVEL (seção {a['secao']}): {a['nome']}. Ação da matriz: {a['acao']}. "
            f"Use APENAS a seção {a['secao']} da base para explicar. Nunca conclua que o "
            f"paciente precisa deste procedimento.")
