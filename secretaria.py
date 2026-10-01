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
    return bool(_SO_CUMPRIMENTO.match(clinica.normalizar(texto)))


def tem_duvida_aberta(texto: str) -> bool:
    t = clinica.normalizar(texto)
    return "?" in (texto or "") or t.startswith(clinica.INTERROGATIVAS)


@dataclass
class Decisao:
    partes: list[str] = field(default_factory=list)   # texto travado, em ordem
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

    abertura = ""
    if not ficha.get("saudacao_feita"):
        abertura = apresentacao(momento, ficha.get("nome", ""))
        ficha["saudacao_feita"] = True

    def fechar() -> Decisao:
        if abertura:
            d.partes.insert(0, abertura)
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

    # ── 3. Confirmação do resumo (seção 18: CONFIRMAÇÃO) ─────────────────────
    if ficha.get("status") == "aguardando_confirmacao" and not midia:
        if ficha.get("ultima_pergunta") == "correcao":
            if not fp.aplicar_correcao(ficha, texto):
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
            d.partes.append(clinica.orientacoes_pre_consulta())
            d.encaminhar = True
            return fechar()
        if clinica.e_nao(texto) and "?" not in texto:
            d.tipos.append("pedir_correcao")
            d.partes.append("Sem problema! Me diga o que você gostaria de corrigir.")
            ficha["ultima_pergunta"] = "correcao"
            return fechar()
        # Outra coisa (uma dúvida no meio da confirmação): responde e volta.

    # ── 4. Resposta à pergunta que o código fez ───────────────────────────────
    capturou = False
    ultima = ficha.get("ultima_pergunta", "")
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
    if texto and not travadas and tem_duvida_aberta(texto):
        d.usar_llm = True
        d.tipos.append("llm")
    elif (texto and not travadas and not capturou and not mudou and not midia
          and not e_so_cumprimento(texto) and len(t.split()) > 3):
        # Mensagem livre que o código não soube classificar: o modelo responde
        # (sem pergunta), e o funil continua de onde estava.
        d.usar_llm = True
        d.tipos.append("llm_livre")

    if capturou and not d.partes and not d.usar_llm:
        if ultima == "nome" and ficha.get("nome"):
            d.partes.append(f"Prazer, {ficha['nome'].split()[0]}!")
        elif ultima == "sinais_gravidade":
            d.partes.append("Certo, obrigado por responder.")
        else:
            d.partes.append("Certo, anotado.")

    # ── 9. Próximo passo do funil ─────────────────────────────────────────────
    _proximo_passo(ficha, d, cobre_queixa)
    return fechar()


def _proximo_passo(ficha: dict, d: Decisao, cobre_queixa: bool) -> None:
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
    if campo:
        fp.marcar_pergunta(ficha, campo)
        if campo == "queixa" and cobre_queixa:
            return  # a resposta da seção 17 já pede a queixa
        d.pergunta_final = fp.pergunta_do_campo(ficha, campo)
        return

    # Ficha completa: resumo e confirmação (seção 18).
    if ficha.get("status") != "aguardando_confirmacao" or ficha.get("ultima_pergunta") != "confirmacao":
        d.partes.append(fp.resumo(ficha))
    ficha["status"] = "aguardando_confirmacao"
    ficha["ultima_pergunta"] = "confirmacao"
    d.pergunta_final = fp.PERGUNTA_CONFIRMACAO
    d.tipos.append("resumo")


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
    if d.pergunta_final:
        partes.append(d.pergunta_final)
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
