"""
secretaria.py — Decide a resposta de cada mensagem do paciente.

Fluxo da seção 18: PACIENTE → IDENTIFICAÇÃO DA QUEIXA → CLASSIFICAÇÃO DA
INTENÇÃO → ÁREA PROVÁVEL → QUALIFICAÇÃO → INFORMAÇÃO → AVALIAÇÃO → AGENDAMENTO →
CONFIRMAÇÃO → ORIENTAÇÕES PRÉ-CONSULTA.

Quem anda o fluxo é o código. O modelo só entra para explicar uma dúvida aberta
que não tem resposta travada em clinica.py, e mesmo assim:
- recebe só o trecho da base que interessa (RAG) e o cartão da área;
- não faz pergunta (as frases interrogativas dele são removidas);
- passa por clinica.conferir_resposta() antes de chegar ao paciente.

Sem dependência de Flask nem de rede: decidir() e montar() são testáveis puros.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import clinica
import ficha_paciente as fp

AGENTE_NOME = os.getenv("AGENTE_NOME", "").strip()


def agora() -> datetime:
    """Hora local da clínica. Offset fixo: no Windows não há base IANA sem tzdata."""
    try:
        horas = float(os.getenv("TZ_OFFSET_HORAS", "-3"))
    except ValueError:
        horas = -3.0
    return datetime.now(timezone(timedelta(hours=horas)))


def saudacao(momento: datetime) -> str:
    h = momento.hour
    if 5 <= h < 12:
        return "Bom dia"
    if 12 <= h < 18:
        return "Boa tarde"
    return "Boa noite"


def apresentacao(momento: datetime, nome: str = "") -> str:
    quem = f"a {AGENTE_NOME}, assistente virtual" if AGENTE_NOME else "a assistente virtual"
    vocativo = f", {nome.split()[0]}" if nome else ""
    return (f"{saudacao(momento)}{vocativo}! Aqui é {quem} do consultório do "
            f"{clinica.PROFISSIONAL_COMPLETO}, cirurgião bucomaxilofacial.")


_SO_CUMPRIMENTO = re.compile(
    r"^(oi+|ola|opa|e ai|bom dia|boa tarde|boa noite|tudo bem|tudo bom|hello|hi|alo|"
    r"oi tudo bem|ola tudo bem|oi boa tarde|oi bom dia|oi boa noite|ola boa tarde|"
    r"ola bom dia|ola boa noite)[\s!.,?]*$"
)


def e_so_cumprimento(texto: str) -> bool:
    # Sem pontuação: "Olá, boa noite" tem de casar igual a "ola boa noite".
    sem_pontuacao = re.sub(r"[^\w\s]", " ", clinica.normalizar(texto))
    return bool(_SO_CUMPRIMENTO.match(" ".join(sem_pontuacao.split())))


# "Tudo bem?" no meio de "Olá / Tudo bem? / Gostaria de agendar" e cumprimento,
# nao duvida: com ele a mensagem ia para o modelo, que escrevia um texto livre
# ("Posso ajudar com o agendamento...") - teste do Dr. Fabricio, 06/10.
_RX_PERGUNTA_DE_CUMPRIMENTO = re.compile(
    r"(?i)\b(?:tudo bem|tudo bom|td bem|tudo certo|como vai|como (?:voce|vc) (?:esta|vai)|blz|beleza)\s*\?+")


def tem_duvida_aberta(texto: str) -> bool:
    sem_cumprimento = _RX_PERGUNTA_DE_CUMPRIMENTO.sub(" ", clinica.normalizar(texto))
    t = " ".join(sem_cumprimento.split())
    return "?" in t or t.startswith(clinica.INTERROGATIVAS)


@dataclass
class Decisao:
    partes: list[str] = field(default_factory=list)   # texto travado, em ordem
    confirmacao: str = ""                              # "Entendi." antes da pergunta
    usar_llm: bool = False                             # há dúvida aberta p/ o modelo
    pergunta_final: str = ""                           # fecha a mensagem
    transferir: str = ""                               # motivo, se transfere
    encaminhar: bool = False                           # agendamento confirmado
    tipos: list[str] = field(default_factory=list)     # rótulos para log


def decidir(ficha: dict, texto: str, momento: datetime | None = None,
            midia: str = "") -> Decisao:
    """Decide a resposta e atualiza a ficha (o chamador salva).

    `midia`: "video", "arquivo" (imagem/documento) ou "audio_falhou". Áudio
    transcrito chega como texto normal.
    """
    momento = momento or agora()
    d = Decisao()
    texto = (texto or "").strip()
    t = clinica.normalizar(texto)

    abertura = not ficha.get("saudacao_feita")
    ficha["saudacao_feita"] = True

    def fechar() -> Decisao:
        # Montada no fim: "Oi, sou a Carla" ja cumprimenta pelo nome.
        if abertura:
            d.partes.insert(0, apresentacao(momento, ficha.get("nome", "")))
        return d

    # ── Encaminhado: a equipe já está com o caso ─────────────────────────────
    # Normalmente o contato já está em modo humano e nem chega aqui; se o
    # painel devolveu ao agente sem #reset, não se reabre o funil sozinho.
    if ficha.get("status") == "encaminhado":
        d.tipos.append("ja_encaminhado")
        d.partes.append("Sua solicitação já está com a equipe do Dr. Fabrício, que vai "
                        "te responder por aqui.")
        return fechar()

    # ── 1. Emergência (seção 5): antes de tudo, sem funil ─────────────────────
    contexto_trauma = "trauma" in (ficha.get("areas") or []) or bool(
        clinica.AREAS["trauma"]["gatilhos"].search(t))
    gravidade_confirmada = (ficha.get("ultima_pergunta") == "sinais_gravidade"
                            and clinica.e_sim(texto))
    if clinica.e_emergencia(texto, contexto_trauma) or gravidade_confirmada:
        ficha["emergencia"] = True
        ficha["ultima_pergunta"] = ""
        fp.extrair_passivo(ficha, texto)
        d.tipos.append("emergencia")
        d.partes.append(clinica.RESPOSTA_EMERGENCIA)
        relato = (f"confirmou sinais de gravidade apos trauma ({ficha.get('queixa', '')[:120]})"
                  if gravidade_confirmada else f"relatou: {texto[:200]}")
        d.transferir = f"POSSIVEL EMERGENCIA - paciente {relato}"
        return fechar()

    # ── 2. Mídia ──────────────────────────────────────────────────────────────
    if midia == "video":
        d.tipos.append("video")
        d.partes.append(clinica.RESPOSTA_VIDEO)
        return fechar()
    if midia == "audio_falhou":
        d.tipos.append("audio_falhou")
        d.partes.append(clinica.RESPOSTA_AUDIO_FALHOU)
        return fechar()
    if midia == "arquivo":
        d.tipos.append("arquivo")
        d.partes.append(clinica.RESPOSTA_ARQUIVO_RECEBIDO)
        if not ficha.get("exames"):
            ficha["exames"] = "Sim (enviou arquivo pelo WhatsApp)"
        if ficha.get("ultima_pergunta") == "exames":
            ficha["ultima_pergunta"] = ""

    # ── 2b. Retorno: o agente retomou e o paciente tem consulta em andamento ──
    # Quem volta com avaliacao marcada (ou pedido na fila da equipe) nao refaz
    # o funil: ouve como esta a consulta e o agente ajuda no que cabe a ele.
    if ficha.get("status") == "retorno":
        consulta = ficha.get("consulta") or {}
        pede_outra = bool(texto) and (
            _RX_NOVA_CONSULTA.search(t) is not None
            or (fp.RX_TERCEIRO.search(t) is not None
                and clinica.classificar_intencao(texto) == "pronto_agendar"))
        if consulta and not pede_outra:
            return _retorno(ficha, d, texto, t, consulta, fechar)
        # Sem consulta em andamento, ou pedindo outra: atendimento novo, com o
        # cadastro que ja se tinha.
        ficha["status"] = "coletando"
        ficha.pop("consulta", None)
        d.tipos.append("retorno:novo_atendimento")

    # ── 3. Confirmação do resumo (seção 18: CONFIRMAÇÃO) ─────────────────────
    if ficha.get("status") == "aguardando_confirmacao" and not midia:
        # Resposta ao dado que o paciente disse que faltava ou estava errado.
        ultima_c = ficha.get("ultima_pergunta", "")
        if ultima_c.startswith("corrigir:"):
            campo = ultima_c.split(":", 1)[1]
            anterior = ficha.get(campo)
            ficha[campo] = ""
            if fp.capturar_resposta(ficha, campo, texto) and ficha.get(campo):
                aviso = ficha.pop("aviso_cadastro", "") or ""
                d.tipos.append(f"corrigido:{campo}")
                d.partes.append("Anotado.")
                d.partes.append(fp.resumo(ficha))
                d.pergunta_final = fp.PERGUNTA_CONFIRMACAO
                ficha["ultima_pergunta"] = "confirmacao"
                return fechar()
            ficha[campo] = anterior
            aviso = ficha.pop("aviso_cadastro", "") or ""
            d.tipos.append("corrigir_de_novo")
            d.partes.append(aviso or fp.PERGUNTAS.get(campo, "Pode me enviar de novo?"))
            return fechar()
        # "Não, está faltando meu endereço" / "Adicionar meu endereço": o
        # campo foi citado sem o valor. Pede o dado em vez de anotar a frase
        # em Observações (teste do Dr. Fabricio, 12/10).
        if ultima_c in ("confirmacao", "correcao") and "?" not in texto:
            campo = fp.campo_citado(texto)
            copia = dict(ficha)
            # So quando o valor nao veio: com numero na frase ("o CPF e 123...")
            # e o caminho normal da correcao, com o aviso de CPF trocado.
            if (campo and campo in fp.PERGUNTAS and not re.search(r"\d", texto)
                    and not fp.aplicar_correcao(copia, texto) and not copia.get("aviso_cadastro")):
                ficha["ultima_pergunta"] = f"corrigir:{campo}"
                d.tipos.append(f"pedir_campo:{campo}")
                d.partes.append(fp.PERGUNTAS[campo])
                return fechar()
        if ficha.get("ultima_pergunta") == "correcao":
            corrigido = fp.aplicar_correcao(ficha, texto)
            aviso = ficha.get("aviso_cadastro", "")
            if aviso:
                # CPF com número trocado: pede de novo, sem fingir que anotou.
                ficha["aviso_cadastro"] = ""
                d.tipos.append("correcao_invalida")
                d.partes.append(aviso)
                return fechar()
            if not corrigido:
                ficha["observacoes"] = (f"{ficha.get('observacoes', '')} {texto}").strip()[:500]
            d.tipos.append("correcao")
            d.partes.append("Anotado.")
            d.partes.append(fp.resumo(ficha))
            d.pergunta_final = fp.PERGUNTA_CONFIRMACAO
            ficha["ultima_pergunta"] = "confirmacao"
            return fechar()
        if clinica.e_sim(texto) and "?" not in texto:
            ficha["status"] = "encaminhado"
            ficha["ultima_pergunta"] = ""
            d.tipos.append("encaminhado")
            d.partes.append(clinica.RESPOSTA_ENCAMINHADO)
            orientacoes = clinica.orientacoes_pre_consulta(ficha)
            if orientacoes:
                d.partes.append(orientacoes)
            d.encaminhar = True
            return fechar()
        if clinica.e_nao(texto) and "?" not in texto:
            d.tipos.append("pedir_correcao")
            d.partes.append("Sem problema! Me diga o que você gostaria de corrigir.")
            ficha["ultima_pergunta"] = "correcao"
            return fechar()
        # Outra coisa (uma dúvida no meio da confirmação): responde e volta.

    ultima = ficha.get("ultima_pergunta", "")

    # ── 3b. Mensagens que não respondem à pergunta (travadas, sem IA) ─────────
    # Antes iam para o modelo ("pq?", "?", "tem alguém aí?") ou eram gravadas
    # como resposta ("kkkk" virava o exame do paciente).
    if not midia and texto:
        if _RX_SO_INFORMACAO.search(t.strip(" .!")) and not clinica.respostas_travadas(texto):
            ficha["ultima_pergunta"] = ""
            d.tipos.append("so_informacao")
            d.partes.append("Sem problema! Fique à vontade para perguntar o que quiser sobre os "
                            "procedimentos. Se quiser agendar uma avaliação, é só me avisar.")
            return fechar()
        resposta_curta = _resposta_fora_do_fluxo(ficha, texto, t, ultima)
        if resposta_curta is not None:
            d.tipos.append("fora_do_fluxo")
            if resposta_curta:
                d.confirmacao = resposta_curta
            _proximo_passo(ficha, d, False, repetir=True)
            return fechar()
        # "e pra minha filha tirar o siso": anota para quem e o atendimento.
        terceiro = fp.RX_TERCEIRO.search(t)
        if terceiro and not ficha.get("para_quem"):
            ficha["para_quem"] = terceiro.group(1)
            d.tipos.append("para_terceiro")
            if fp._RX_SO_TERCEIRO.match(t.strip(" .!")):
                d.confirmacao = (f"Certo, anotei que o atendimento é para {'o seu' if terceiro.group(1)[-1] == 'o' or terceiro.group(1) in ('pai', 'marido', 'irmao', 'avo') else 'a sua'} "
                                 f"{terceiro.group(1)}.")
                _proximo_passo(ficha, d, False)
                return fechar()

    # ── 4. Resposta à pergunta que o código fez ───────────────────────────────
    capturou = False
    if ultima == "cta_curiosidade" and not midia:
        ficha["ultima_pergunta"] = ""
        if clinica.e_nao(texto) and "?" not in texto and not clinica.classificar_areas(texto):
            d.tipos.append("cta_recusado")
            d.partes.append("Combinado! Se surgir qualquer dúvida ou quiser agendar a "
                            "avaliação, é só me chamar por aqui.")
            return fechar()
        if clinica.e_sim(texto):
            ficha["intencao"] = clinica.intencao_maior(ficha.get("intencao", ""), "intencao")
            capturou = True
    if ultima == "sinais_gravidade" and clinica.e_nao(texto):
        ficha["triagem_trauma"] = "sem_gravidade"
        ficha["ultima_pergunta"] = ""
        capturou = True
    elif ultima in fp.ORDEM and not ficha.get(ultima) and not midia:
        capturou = fp.capturar_resposta(ficha, ultima, texto)
        if capturou:
            ficha["ultima_pergunta"] = ""
            d.tipos.append(f"captura:{ultima}")

    area_antes = ficha.get("area", "")
    mudou = fp.extrair_passivo(ficha, texto) if texto else []
    if mudou:
        d.tipos.append("passivo:" + ",".join(mudou))

    # ── 5. Trauma: descartar gravidade antes de qualquer outra coisa ─────────
    if ficha.get("area") == "trauma" and not ficha.get("triagem_trauma"):
        ficha["triagem_trauma"] = "perguntada"
        ficha["ultima_pergunta"] = "sinais_gravidade"
        d.tipos.append("triagem_trauma")
        d.partes.append(clinica.AREAS["trauma"]["acolhimento"])
        d.pergunta_final = clinica.PERGUNTA_SINAIS_GRAVIDADE
        return fechar()

    # ── 6. Respostas travadas do documento ────────────────────────────────────
    travadas = clinica.respostas_travadas(texto) if texto else []
    # Dados do cadastro nao sao duvida: "Endereço completo: ..." disparava a
    # resposta do endereco do CONSULTORIO (teste do Dr. Fabricio, 12/10).
    if ultima in fp.CADASTRO and "?" not in texto:
        travadas = []
    cobre_queixa = False
    for tipo, resposta in travadas:
        d.tipos.append(tipo)
        d.partes.append(resposta)
        if tipo == "nao_sei":
            cobre_queixa = True

    # ── 7. Acolhimento da área, quando ela aparece pela primeira vez ─────────
    area = ficha.get("area", "")
    if (area and area != area_antes and area != "trauma"
            and ficha.get("intencao") != "pronto_agendar"):
        d.tipos.append(f"area:{area}")
        d.partes.append(clinica.AREAS[area]["acolhimento"])

    # ── 8. Dúvida aberta que nada acima respondeu: vai para o modelo ─────────
    # Cumprimento com "?" ("oi, tudo bem?") nao e duvida: nao vai ao modelo.
    if (texto and not travadas and tem_duvida_aberta(texto) and not e_so_cumprimento(texto)
            and not (capturou and ("?" not in texto or ultima == "nome"))):
        d.usar_llm = True
        d.tipos.append("llm")
    elif (texto and not travadas and not capturou and not mudou and not midia
          and not e_so_cumprimento(texto) and len(t.split()) > 3):
        # Mensagem livre que o código não soube classificar: o modelo responde
        # (sem pergunta), e o funil continua de onde estava.
        d.usar_llm = True
        d.tipos.append("llm_livre")

    if capturou and not d.partes and not d.usar_llm:
        d.confirmacao = _confirmacao(ultima, ficha)
        # "Ana Paula, tudo bem?": responde ao cumprimento junto com o nome.
        if ultima == "nome" and re.search(r"\btudo (bem|bom|certo)\b", t):
            d.confirmacao += " Tudo ótimo por aqui."
    elif (not ficha.get("queixa") and not d.partes and not d.usar_llm
          and ficha.get("intencao") == "pronto_agendar"
          and (ultima == "queixa" or clinica.classificar_intencao(texto) == "pronto_agendar")):
        # "Gostaria de agendar uma consulta": reconhece o pedido antes de
        # perguntar nome/queixa, em texto fixo (antes ia para o modelo).
        d.confirmacao = "Claro, vamos agendar a sua avaliação!"
        if _RX_PERGUNTA_DE_CUMPRIMENTO.search(t):
            d.confirmacao = "Tudo ótimo por aqui! " + d.confirmacao
    elif texto and e_so_cumprimento(texto) and not abertura and not d.partes:
        # "Boa noite" no meio do atendimento: responde ao cumprimento antes de
        # repetir a pergunta, em vez de ignora-lo (teste de 02/10).
        d.confirmacao = f"{saudacao(momento)}!"

    # ── 9. Próximo passo do funil ─────────────────────────────────────────────
    _proximo_passo(ficha, d, cobre_queixa)
    return fechar()


def _confirmacao(campo: str, ficha: dict) -> str:
    """Confirmacao curta da resposta, diferente para cada campo.

    Era "Certo, anotado." para tudo, em bolha propria: 9 vezes iguais numa
    conversa so (teste de 02/10). Cada campo tem a sua frase e ela vai na
    mesma mensagem da pergunta seguinte. Fixa por campo: nada oscila.
    """
    valor = clinica.normalizar(ficha.get(campo, ""))
    if campo in fp.CADASTRO:
        aviso = ficha.pop("aviso_cadastro", "") or ""
        ficha["aviso_cadastro"] = ""
        if aviso:
            return aviso
        if all(ficha.get(c) for c in fp.CADASTRO):
            return "Cadastro completo, obrigada! Agora vamos ao agendamento."
        return "Obrigada!"
    if campo == "nome" and ficha.get("nome"):
        return f"Prazer, {ficha['nome'].split()[0]}!"
    if campo == "sinais_gravidade":
        return "Obrigada por responder."
    if campo == "exames":
        return ("Sem problema." if valor.startswith(("nao", "ainda nao"))
                else "Ótimo, leve no dia da avaliação.")
    if campo == "avaliacao_previa":
        profissional = re.search(r"\b(dentista|ortodontista|medic|doutor|doutora|dr|dra|implantodontista|cirurgiao)", valor)
        return ("Ótimo, isso ajuda o Dr. Fabrício a entender o seu caso." if valor == "sim" or profissional
                else "Tudo bem.")
    return {
        "queixa": "Entendi.",
        "detalhe_area": "Obrigada pelos detalhes.",
        "tempo_queixa": "Entendi.",
        "cidade": "Perfeito.",
        "disponibilidade": "Anotado.",
        "tipo_consulta": "Certo.",
        "saude": "Obrigada pelas informações.",
    }.get(campo, "")


_RX_PRESENCA = re.compile(r"^(?:oi |ola )?(?:tem alguem (?:ai|aqui|ae)|alguem (?:ai|aqui|ae)|ta ai|esta ai|tem gente|alo)$")
_RX_POR_QUE = re.compile(r"^(?:mas )?(?:pq|pra que|para que|por que|porque|por qual motivo|pra q|pq isso|pra que isso|por que isso)$")
_RX_AGRADECIMENTO = re.compile(r"^(?:muito )?(?:obrigad[oa]|obg|valeu|vlw|agradeco)\b")
_RX_SO_INFORMACAO = re.compile(
    r"^(?:nada|nenhum[a]?|nao)?[ ,]*(?:so|apenas|somente) (?:queria|quero|estava|tava|to|estou) "
    r"(?:saber|vendo|olhando|perguntando|conhecendo|tirar uma duvida|uma informacao)\b"
    r"|^(?:so|apenas) (?:uma )?(?:duvida|informacao|olhando|vendo)$")
_RX_PRECISA_EXAME = re.compile(r"\b(?:preciso|precisa|tenho que|tem que|e necessario|obrigatorio|e preciso)\b")
_RX_FIM_DE_SEMANA = re.compile(r"\b(?:sabado|sabados|domingo|domingos|fim de semana|final de semana)\b")
_RX_DIA_UTIL = re.compile(r"\b(?:segunda|terca|quarta|quinta|sexta|qualquer|semana|dia util|dias uteis)\b")


def _resposta_fora_do_fluxo(ficha: dict, texto: str, t: str, ultima: str) -> str | None:
    """Mensagem que não responde à pergunta pendente.

    Devolve a frase que vai antes da pergunta repetida ("" = só repete), ou
    None quando a mensagem é uma resposta normal e segue o fluxo.
    """
    limpo = " ".join(re.sub(r"[^\w\s]", " ", t).split())
    if not limpo:
        return "Desculpe, não entendi bem."
    if _RX_PRESENCA.match(limpo):
        return "Estou aqui, sim!"
    if _RX_POR_QUE.match(limpo) and ultima in fp.ORDEM:
        return ("Pergunto para registrar o seu atendimento e passar as informações "
                "certas para o Dr. Fabrício.")
    if ultima in fp.ORDEM and not ficha.get(ultima):
        if _RX_AGRADECIMENTO.match(limpo) and len(limpo.split()) <= 4:
            return "Por nada!"
        if fp.sem_conteudo(texto) and not e_so_cumprimento(texto):
            return ""
        if ultima == "exames" and "?" in texto and _RX_PRECISA_EXAME.search(limpo) and not clinica.classificar_areas(texto):
            return "Se algum exame for necessário, o Dr. Fabrício orienta na avaliação."
        if ultima == "disponibilidade" and _RX_FIM_DE_SEMANA.search(limpo) and not _RX_DIA_UTIL.search(limpo):
            horario = clinica.info_clinica("horario")
            h = clinica.normalizar(horario)
            if horario and "fechad" in h and ("sab" in h or "dom" in h):
                return f"{clinica.resposta_horario()} Algum dia de segunda a sexta funciona para você?"
    return None


def _proximo_passo(ficha: dict, d: Decisao, cobre_queixa: bool, repetir: bool = False) -> None:
    # "So queria saber": responde sem empurrar coleta (secao 13).
    if repetir and d.confirmacao.endswith("funciona para você?"):
        ficha["ultima_pergunta"] = "disponibilidade"
        return
    # A resposta da secao 17 ja pede que o paciente conte a queixa: nenhuma
    # outra pergunta na mesma mensagem, e a resposta dele vira a queixa.
    if cobre_queixa and not ficha.get("queixa"):
        fp.marcar_pergunta(ficha, "queixa")
        return
    # Seção 13: curiosidade = responder e orientar, sem empurrar coleta.
    if (ficha.get("intencao") == "curiosidade" and not ficha.get("queixa")
            and not ficha.get("nome") and (d.partes or d.usar_llm)
            and not ficha.get("cta_curiosidade_feito")):
        ficha["cta_curiosidade_feito"] = True
        ficha["ultima_pergunta"] = "cta_curiosidade"
        d.pergunta_final = fp.PERGUNTA_CURIOSIDADE
        return

    campo = fp.proximo_campo(ficha)
    # A mesma pergunta da mensagem anterior (o paciente nao respondeu): vai a
    # versao curta. Repetir a frase inteira era texto a toa (teste de 07/10).
    repetida = bool(campo) and ficha.get("ultima_pergunta") == campo
    if campo:
        fp.marcar_pergunta(ficha, campo)
        if campo == "queixa" and cobre_queixa:
            return  # a resposta da seção 17 já pede a queixa
        d.pergunta_final = fp.pergunta_do_campo(ficha, campo, repetida=repetida)
        return

    # Ficha completa: resumo e confirmação (seção 18).
    if ficha.get("status") != "aguardando_confirmacao" or ficha.get("ultima_pergunta") != "confirmacao":
        # A confirmação da última resposta vem antes do resumo, não depois.
        if d.confirmacao:
            d.partes.append(d.confirmacao)
            d.confirmacao = ""
        d.partes.append(fp.resumo(ficha))
    ficha["status"] = "aguardando_confirmacao"
    ficha["ultima_pergunta"] = "confirmacao"
    d.pergunta_final = fp.PERGUNTA_CONFIRMACAO
    d.tipos.append("resumo")


# ── Retorno com consulta em andamento ─────────────────────────────────────────

_DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
                "sexta-feira", "sábado", "domingo"]

# Remarcar e cancelar ficam com a equipe: so ela mexe na agenda.
_RX_MUDAR_CONSULTA = re.compile(
    r"\b(remarc\w*|desmarc\w*|cancel\w*|adiar|adia[rm]?\b"
    r"|(trocar|mudar|alterar|antecipar)\b.{0,25}\b(dia|data|horario|hora|consulta|avaliacao)"
    r"|nao (vou|vai|irei) (poder|conseguir)|nao (posso|consigo) (ir|comparecer))")
_RX_AGRADECIMENTO = re.compile(r"\b(obrigad\w*|valeu|agradec\w*|grat[oa])\b")
_RX_NOVA_CONSULTA = re.compile(r"\b(outra|nova|mais uma|segunda) (consulta|avaliacao)\b")
# "Que dia e a minha consulta?", "ja tem horario?": a resposta e a situacao.
_RX_PERGUNTA_SITUACAO = re.compile(
    r"\b(que dia|que horas|qual (e )?(o |a )?(dia|data|horario|hora)|quando (e|vai ser|sera)"
    r"|(ja )?(tem|tenho|saiu) (o )?(horario|data|dia)"
    r"|(esta|ta|foi|ficou|ja) (marcad|agendad|confirmad)\w*|minha (consulta|avaliacao))\b")

MENSAGEM_RETORNO_MUDAR = ("Vou passar seu pedido para a equipe do Dr. Fabrício, que cuida "
                          "da agenda e te responde por aqui.")
MENSAGEM_RETORNO_AJUDA = "Se tiver alguma dúvida sobre a avaliação, é só me perguntar por aqui."


def quando_por_extenso(inicio: str) -> str:
    """'2026-10-08T09:00' -> 'quinta-feira, 08/10, às 09h00'."""
    d = datetime.fromisoformat(inicio)
    return f"{_DIAS_SEMANA[d.weekday()]}, {d.strftime('%d/%m')}, às {d.strftime('%Hh%M')}"


def situacao_da_consulta(consulta: dict) -> str:
    if consulta.get("situacao") == "marcada" and consulta.get("inicio"):
        return ("Sua avaliação com o Dr. Fabrício está confirmada para "
                f"{quando_por_extenso(consulta['inicio'])}.")
    return ("Seu pedido de agendamento está com a equipe do Dr. Fabrício, que vai te "
            "passar o dia e o horário por aqui.")


def _retorno(ficha: dict, d: Decisao, texto: str, t: str, consulta: dict, fechar) -> Decisao:
    situacao = consulta.get("situacao", "pendente")
    d.tipos.append(f"retorno:{situacao}")
    primeira = not ficha.get("retorno_avisado")
    ficha["retorno_avisado"] = True
    ficha["ultima_pergunta"] = ""

    if texto and _RX_MUDAR_CONSULTA.search(t):
        d.tipos.append("retorno:mudar_consulta")
        d.partes.append(MENSAGEM_RETORNO_MUDAR)
        alvo = (f"consulta de {quando_por_extenso(consulta['inicio'])}"
                if situacao == "marcada" and consulta.get("inicio")
                else "pedido de agendamento pendente")
        d.transferir = f"Paciente quer remarcar/cancelar ({alvo}): {texto[:200]}"
        return fechar()

    perguntou_situacao = bool(texto) and _RX_PERGUNTA_SITUACAO.search(t) is not None
    if primeira or perguntou_situacao:
        d.partes.append(situacao_da_consulta(consulta))

    travadas = clinica.respostas_travadas(texto) if texto else []
    for tipo, resposta in travadas:
        d.tipos.append(tipo)
        d.partes.append(resposta)

    if (texto and not travadas and not perguntou_situacao and tem_duvida_aberta(texto)
            and not e_so_cumprimento(texto)):
        d.usar_llm = True
        d.tipos.append("llm")
    elif not travadas and not perguntou_situacao:
        if _RX_AGRADECIMENTO.search(t) and not primeira:
            d.confirmacao = "Por nada!"
        d.pergunta_final = MENSAGEM_RETORNO_AJUDA
    return fechar()


def montar(d: Decisao, texto_modelo: str = "") -> tuple[str, list[str]]:
    """Junta partes travadas + resposta conferida do modelo + pergunta do funil.

    Devolve (mensagem, violacoes). Com o modelo fora do ar ou barrado, a
    dúvida recebe a resposta genérica travada.
    """
    violacoes: list[str] = []
    partes = list(d.partes)
    if d.usar_llm:
        limpo = clinica.sem_perguntas(texto_modelo or "")
        if limpo:
            limpo, violacoes = clinica.conferir_resposta(limpo)
        partes.append(limpo or clinica.RESPOSTA_DUVIDA_GENERICA)
    if d.confirmacao and d.pergunta_final:
        partes.append(f"{d.confirmacao} {d.pergunta_final}")
    elif d.confirmacao or d.pergunta_final:
        partes.append(d.confirmacao or d.pergunta_final)
    vistos, unicas = set(), []
    for p in partes:
        p = (p or "").strip()
        if p and p not in vistos:
            vistos.add(p)
            unicas.append(p)
    return "\n\n".join(unicas), violacoes


def instrucoes_para_modelo(ficha: dict, texto: str) -> str:
    """Bloco dinâmico do prompt: ficha, área provável e a tarefa desta volta."""
    areas = clinica.classificar_areas(texto) or ([ficha["area"]] if ficha.get("area") else [])
    cartoes = "\n".join(clinica.cartao_da_area(a) for a in areas[:2])
    return (
        f"{fp.render_para_prompt(ficha)}\n\n"
        + (f"{cartoes}\n\n" if cartoes else "")
        + "=== TAREFA DESTA RESPOSTA ===\n"
        "Responda SOMENTE a dúvida da última mensagem do paciente, em no máximo 3 "
        "frases curtas, usando apenas a BASE OFICIAL acima. Não cumprimente, não faça "
        "perguntas e não peça dados: a próxima pergunta é acrescentada pelo sistema. "
        "Se a base não responde a dúvida, diga que o Dr. Fabrício esclarece isso na "
        "avaliação."
    )
