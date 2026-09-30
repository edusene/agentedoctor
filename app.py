"""
app.py — Secretária virtual do Dr. Fabrício Guimarães no WhatsApp.
Flask webhook (Datafy / Meta Cloud API) + pipeline do agente + painel CRM.

O atendimento segue a base de conhecimento do consultório
(knowledge/base_conhecimento_dr_fabricio.md). As respostas que não podem
oscilar estão travadas em clinica.py; o fluxo é decidido em secretaria.py.
"""

import os
import sys
import time
import threading
import hmac
import hashlib
import re as _re_mod
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# Windows: stdout pode estar em cp1252
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

from flask import Flask, request, jsonify, Response, redirect, url_for, render_template, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import memory
import llm
import database
import events
import meta
import knowledge_rag
import clinica
import ficha_paciente
import secretaria
import documentos
import scheduler as crm_scheduler

from meta import send_text, mark_read, send_typing, download_media_bytes
from meta import get_phone_info, list_templates, get_template, delete_template, create_template
from meta import get_business_profile, update_business_profile, get_phone_id, get_waba_id
from meta import get_webhook_media_url
from buffer import MessageBuffer
from auth import login_required, do_login, do_logout

# ── Config ──────────────────────────────────────────────────────────────────
# Janela de debounce: tempo de silencio do paciente antes de o agente responder.
BUFFER_SECONDS = float(os.getenv("BUFFER_SECONDS", "3"))
PORT = int(os.getenv("PORT", "5000"))
SECRET_KEY = os.getenv("SECRET_KEY", "troque_esta_chave_secreta_aleatoria")
DATAFY_WEBHOOK_SECRET = os.getenv("DATAFY_WEBHOOK_SECRET", "")

_DIR = Path(__file__).parent
PROMPT_PATH = _DIR / "prompts" / "secretaria.md"
BASE_CONHECIMENTO_PATH = _DIR / "knowledge" / "base_conhecimento_dr_fabricio.md"
BASE_CONHECIMENTO_NOME = BASE_CONHECIMENTO_PATH.name

_PROMPT_CACHE: dict[str, str] = {}


def _get_current_system_prompt() -> str:
    """Prompt da secretaria (prompts/secretaria.md), editavel pelo painel."""
    if "atual" not in _PROMPT_CACHE:
        try:
            _PROMPT_CACHE["atual"] = PROMPT_PATH.read_text(encoding="utf-8").strip()
        except Exception as e:
            print(f"[prompt] ERRO lendo {PROMPT_PATH}: {e}")
            _PROMPT_CACHE["atual"] = (
                "Voce e a assistente virtual do consultorio do Dr. Fabricio Guimaraes. "
                "Nunca diagnostique, nunca indique procedimento, nunca informe preco."
            )
    return _PROMPT_CACHE["atual"]


def recarregar_prompt() -> str:
    _PROMPT_CACHE.clear()
    return _get_current_system_prompt()


def garantir_base_de_conhecimento() -> None:
    """Sobe a base do Dr. Fabricio para o knowledge (RAG) se ela ainda nao estiver la.

    Com a chave da OpenAI disponivel os embeddings sao gerados na hora; sem
    ela o arquivo entra como 'pending' e a busca textual segue funcionando ate
    alguem clicar em "Gerar Embeddings" no painel.
    """
    try:
        if knowledge_rag.get_file_content(BASE_CONHECIMENTO_NOME):
            return
        conteudo = BASE_CONHECIMENTO_PATH.read_text(encoding="utf-8")
        descricao = ("Base de conhecimento oficial do Dr. Fabricio Guimaraes: regras, "
                     "procedimentos, triagem, respostas-padrao e fluxo de atendimento")
        if os.getenv("OPENAI_API_KEY"):
            knowledge_rag.save_knowledge(BASE_CONHECIMENTO_NOME, conteudo, description=descricao)
        else:
            knowledge_rag.save_knowledge_raw(BASE_CONHECIMENTO_NOME, conteudo, description=descricao)
        print(f"[knowledge] base do Dr. Fabricio carregada no knowledge ({len(conteudo)} chars)")
    except Exception as e:
        print(f"[knowledge] WARN nao carregou a base de conhecimento: {e}")


def _contexto_rag(texto: str) -> str:
    """Trechos da base oficial mais proximos da duvida do paciente (RAG).

    Sem resultado da busca (base vazia, embedding fora do ar), cai para o
    documento inteiro: ele e pequeno, e responder sem a base nao e opcao.
    """
    trechos = ""
    try:
        trechos = knowledge_rag.search_context(texto, top_k=4)
    except Exception as e:
        print(f"[rag] WARN busca falhou: {e}")
    if not trechos:
        try:
            trechos = knowledge_rag.get_full_knowledge_content()
        except Exception as e:
            print(f"[rag] WARN base completa indisponivel: {e}")
    if not trechos:
        try:
            trechos = BASE_CONHECIMENTO_PATH.read_text(encoding="utf-8")
        except Exception:
            trechos = ""
    return trechos


# ── Transfer (transferencia para humano) ──────────────────────────────────────

# Palavras-chave que disparam transferencia ANTES de qualquer outra coisa. A
# agenda real e da equipe: remarcar e cancelar consulta vao para uma pessoa.
TRANSFER_KEYWORDS = [
    "falar com atendente",
    "falar com humano",
    "falar com pessoa",
    "falar com a secretaria",
    "falar com a secretária",
    "falar com o doutor",
    "falar com o dr",
    "quero atendente",
    "quero humano",
    "preciso de atendente",
    "atendimento humano",
    "atendente humano",
    "falar com alguem",
    "falar com alguém",
    "reclamacao",
    "reclamação",
    "remarcar",
    "desmarcar",
    "cancelar a consulta",
    "cancelar minha consulta",
    "cancelar consulta",
    "ouvidoria",
]


def _check_transfer_keywords(items: list[dict]) -> str | None:
    """Verifica se alguma mensagem contém palavras-chave de transferência.
    Retorna a keyword encontrada ou None."""
    full_text = " ".join(
        item.get("text", "").lower()
        for item in items
        if item.get("text")
    )
    for kw in TRANSFER_KEYWORDS:
        if kw in full_text:
            return kw
    return None

# ── Helpers ──────────────────────────────────────────────────────────────────

def _sem_repeticao_consecutiva(texto: str) -> str:
    """Remove um trecho que o modelo repetiu logo em seguida a si mesmo.

    O modelo as vezes emite a mesma frase duas vezes. Quando a copia vem depois
    de uma linha em branco, a deduplicacao por paragrafo pega; quando vem
    separada por UMA quebra de linha, por um espaco ou colada, passava direto e
    o cliente recebia a pergunta duplicada.

    So colapsa repeticao CONSECUTIVA e IDENTICA de um trecho longo: duas linhas
    diferentes de um resumo, ou dois itens parecidos, nao sao tocados.
    """
    import re as _re

    def _chave(s: str) -> str:
        return " ".join(s.lower().split())

    # 1) linhas iguais em sequencia
    linhas, anterior = [], ""
    for linha in texto.split("\n"):
        if linha.strip() and len(linha.strip()) >= 25 and _chave(linha) == anterior:
            continue
        linhas.append(linha)
        if linha.strip():
            anterior = _chave(linha)
    texto = "\n".join(linhas)

    # 2) frases iguais em sequencia, dentro da mesma linha.
    #    O separador vai num grupo de captura para ser recolocado como estava:
    #    juntar tudo com espaco apagava as linhas em branco e mudava a divisao
    #    das mensagens enviadas ao cliente.
    partes = _re.split(r"((?<=[.!?])\s+)", texto)
    frases, anterior = [], ""
    for i in range(0, len(partes), 2):
        frase = partes[i]
        separador = partes[i + 1] if i + 1 < len(partes) else ""
        if len(frase.strip()) >= 30 and _chave(frase) == anterior:
            continue
        frases.append(frase + separador)
        if frase.strip():
            anterior = _chave(frase)
    texto = "".join(frases)

    # 3 e 4) a mensagem INTEIRA e um bloco repetido, com ou sem separador
    #    ("A. B. A. B."). As frases se alternam, entao a checagem consecutiva
    #    acima nao pega. Ancorado nas duas pontas, e so para bloco que pareca
    #    texto de verdade: sem essa guarda, algo degenerado como "A A A A..."
    #    tambem casava e era truncado.
    def _colapsar(m):
        bloco = m.group(1)
        palavras = {p for p in _re.findall(r"\w+", bloco.lower()) if len(p) >= 2}
        return bloco if len(palavras) >= 5 else m.group(0)

    texto = _re.sub(r"^(.{40,}?)(?:\s*\1)+$", _colapsar, texto.strip(), flags=_re.DOTALL)
    return texto


def split_reply(text: str) -> list[str]:
    text = _sem_repeticao_consecutiva(text or "")
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= 800:
            chunks.append(para)
        else:
            sentences = para.split(". ")
            current = ""
            for i, sentence in enumerate(sentences):
                piece = sentence if i == len(sentences) - 1 else sentence + "."
                if current and len(current) + 1 + len(piece) > 800:
                    chunks.append(current.strip())
                    current = piece
                else:
                    current = (current + " " + piece).strip() if current else piece
            if current:
                chunks.append(current.strip())

    # O modelo as vezes repete a mesma frase em dois paragrafos seguidos —
    # imitando o texto do prompt operacional, que vem do .docx com trechos
    # duplicados. Para o cliente isso chega como a mesma pergunta duas vezes.
    # Paragrafo sem nenhuma letra ou numero ("😊", "💛") nao e mensagem: vai
    # colado ao anterior, ou ao seguinte se for o primeiro. Sozinho ele chegava
    # ao cliente como uma bolha so de emoji.
    colados: list[str] = []
    for c in chunks:
        if c and not _re_mod.search(r"\w", c):
            if colados:
                colados[-1] = f"{colados[-1]} {c}"
            else:
                colados.append(c)
            continue
        if colados and not _re_mod.search(r"\w", colados[-1]):
            c = f"{colados.pop()} {c}"
        colados.append(c)
    chunks = colados

    unicos: list[str] = []
    vistos: set[str] = set()
    for c in chunks:
        if not c:
            continue
        chave = " ".join(c.lower().split())
        if chave in vistos:
            print(f"[split] paragrafo repetido descartado: {c[:60]!r}")
            continue
        vistos.add(chave)
        unicos.append(c)
    return unicos


# ── Multimodal parts builder ─────────────────────────────────────────────────

_OPENAI_SUPPORTED_IMAGES = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
}

_OPENAI_SUPPORTED_AUDIO = {
    "audio/ogg", "audio/ogg; codecs=opus", "audio/mpeg", "audio/mp3",
    "audio/mp4", "audio/aac", "audio/wav", "audio/x-wav",
    "audio/webm", "audio/flac", "audio/x-m4a",
}

_OPENAI_SUPPORTED_DOCS = {
    "application/pdf",
}


def _normalize_mime(mime: str) -> str:
    """Normaliza MIME type removendo codecs (ex: 'audio/ogg; codecs=opus' -> 'audio/ogg')."""
    return mime.split(";")[0].strip().lower()


def _parse_data_uri(data_uri: str) -> tuple[str, str]:
    m = __import__("re").match(r"^data:([^;,]+);base64,(.+)$", data_uri, __import__("re").DOTALL)
    if m:
        return m.group(1), m.group(2)
    return "", data_uri


def _vocabulario_do_audio() -> str:
    """Termos do consultorio que o Whisper deve reconhecer.

    O `prompt` do Whisper e so vocabulario: nao muda o que foi dito, desempata
    o que soa parecido. Tem limite (~224 tokens), entao vai curto.
    """
    return ("Consulta com o Dr. Fabricio Guimaraes, cirurgiao bucomaxilofacial: siso, "
            "extracao, exodontia, dente incluso, biopsia, enxerto osseo, implante, "
            "fratura de mandibula, cirurgia ortognatica, mentoplastia, genioplastia, "
            "lift facial, lift cervical, lipo de papada, cisto, tumor odontogenico, "
            "tomografia, radiografia panoramica, laudo, ortodontista.")


def transcribe_audio(b64_data: str, mime: str) -> str:
    """Transcreve áudio via OpenAI Whisper. Retorna texto transcrito ou vazio."""
    try:
        import base64 as _b64
        raw = _b64.b64decode(b64_data)
        if len(raw) > 25 * 1024 * 1024:
            print("[transcribe] áudio > 25MB, ignorando")
            return ""
        ext_map = {
            "audio/ogg": "ogg", "audio/ogg; codecs=opus": "ogg",
            "audio/mpeg": "mp3", "audio/mp3": "mp3",
            "audio/mp4": "m4a", "audio/aac": "m4a",
            "audio/wav": "wav", "audio/x-wav": "wav",
            "audio/webm": "webm", "audio/flac": "flac",
            "audio/x-m4a": "m4a",
        }
        ext = ext_map.get(mime, "ogg")
        from llm import _client as _oai
        resp = _oai.audio.transcriptions.create(
            model="whisper-1",
            file=(f"audio.{ext}", raw, mime.split(";")[0]),
            language="pt",
            prompt=_vocabulario_do_audio(),
        )
        text = (resp.text or "").strip()
        print(f"[transcribe] len={len(text)} preview={text[:80]}")
        return text
    except Exception as e:
        print(f"[transcribe] ERRO: {e}")
        return ""


def _build_user_parts(items: list[dict]) -> list[dict]:
    import re as _re
    parts = []
    seen_media = set()

    for item in items:
        text = item.get("text", "")
        msg_id = item.get("msg_id")

        if msg_id:
            msg = database.get_message(msg_id)
            media_url = str((msg or {}).get("media_url") or "").strip()
            msg_type = str((msg or {}).get("msg_type") or "text")

            if not media_url and msg_type != "text":
                wa_media_id_db = str((msg or {}).get("wa_media_id") or "").strip()
                if wa_media_id_db:
                    try:
                        info = get_webhook_media_url(wa_media_id_db)
                        if info.get("ok") and isinstance(info.get("data"), dict):
                            url = info["data"].get("url", "")
                            mime_from_api = info["data"].get("mime_type", "application/octet-stream")
                            if url:
                                import requests as _req
                                resp = _req.get(url, timeout=30)
                                if resp.status_code == 200:
                                    import base64 as _b64
                                    b64_data = _b64.b64encode(resp.content).decode()
                                    media_url = f"data:{mime_from_api};base64,{b64_data}"
                                    database.update_message_media(msg["id"], media_url)
                                    print(f"[flush] on-demand download ok msg={msg['id']} mime={mime_from_api}")
                    except Exception as e:
                        print(f"[flush] WARN on-demand download falhou msg={msg_id}: {e}")

            if media_url and msg_type != "text" and media_url not in seen_media:
                seen_media.add(media_url)
                mime = ""
                b64 = ""

                if media_url.startswith("data:"):
                    mime, b64 = _parse_data_uri(media_url)
                elif media_url.startswith("http"):
                    try:
                        import requests as _req
                        resp = _req.get(media_url, timeout=15)
                        if resp.status_code == 200:
                            ct = resp.headers.get("Content-Type", "")
                            mime = ct.split(";")[0].strip() if ct else ""
                            import base64 as _b64
                            b64 = _b64.b64encode(resp.content).decode()
                    except Exception as e:
                        print(f"[flush] WARN download media falhou msg={msg_id}: {e}")

                media_desc = {
                    "image": "O paciente enviou uma imagem.",
                    "video": "O paciente enviou um video.",
                    "audio": "O paciente enviou um audio.",
                    "ptt": "O paciente enviou um audio (mensagem de voz).",
                    "sticker": "O paciente enviou uma figurinha.",
                    "document": "O paciente enviou um documento.",
                }.get(msg_type, f"O paciente enviou midia ({msg_type}).")

                # A legenda vem colada no marcador ("[Imagem] meu raio-x").
                legenda = _re_mod.sub(r"^\[[^\]]*\]\s*", "", text or "").strip()
                if legenda:
                    media_desc += f" Legenda: {legenda}"

                if mime and b64 and msg_type in ("audio", "ptt") and _normalize_mime(mime) in _OPENAI_SUPPORTED_AUDIO:
                    # Transcreve uma vez por item: handle_flush chama esta
                    # funcao cedo (para a ficha ouvir o audio) e de novo ao
                    # montar o prompt - a segunda vez usa o que ja veio.
                    transcription = item.get("transcricao")
                    if transcription is None:
                        transcription = transcribe_audio(b64, mime)
                        item["transcricao"] = transcription
                    if transcription:
                        parts.append({"text": f"O paciente enviou uma mensagem de voz. Transcrição: {transcription}"})
                    else:
                        parts.append({"text": media_desc})
                elif mime and b64 and _normalize_mime(mime) in _OPENAI_SUPPORTED_IMAGES:
                    parts.append({"text": media_desc})
                    parts.append({
                        "inline_data": {
                            "mime_type": mime,
                            "data": b64,
                        }
                    })
                elif mime and b64 and _normalize_mime(mime) in _OPENAI_SUPPORTED_DOCS:
                    decoded_size = len(b64) * 3 // 4
                    if decoded_size > 2 * 1024 * 1024:
                        parts.append({"text": media_desc + " (arquivo muito grande para analisar automaticamente)"})
                    else:
                        parts.append({"text": media_desc})
                        parts.append({
                            "inline_data": {
                                "mime_type": _normalize_mime(mime),
                                "data": b64,
                            }
                        })
                else:
                    parts.append({"text": media_desc})

                continue

        if text:
            parts.append({"text": text})

    if not parts:
        parts.append({"text": "[Mensagem sem conteudo de texto]"})

    return parts


# ── Transfer ──────────────────────────────────────────────────────────────────

def perform_transfer(phone: str, reason: str = "", send_message: bool = True) -> bool:
    """Transfere a conversa de um usuário para atendimento humano.

    - Muda auto_mode do contato para 0
    - Registra transferred_at na conversa
    - Salva mensagem interna de sistema no chat
    - Envia mensagem configurável ao cliente (se send_message=True)
    - Emite evento SSE para atualizar o painel em tempo real

    Retorna True se a transferência foi feita, False se já estava em modo humano.
    """
    contact = database.get_contact(phone)
    if contact and not contact.get("auto_mode", 1):
        print(f"[transfer] user={phone} já está em modo humano, ignorando")
        return False

    now = datetime.utcnow().isoformat()
    now_fmt = datetime.utcnow().strftime("%d/%m %H:%M")

    # Muda para modo humano
    if contact:
        database.update_contact(contact["id"], auto_mode=0)
    else:
        # Cria contato se não existir
        contact = database.upsert_contact(phone)
        database.update_contact(contact["id"], auto_mode=0)

    # Busca ou cria conversa
    conv = database.get_or_create_conversation(phone)
    database.update_conversation(conv["id"], transferred_at=now)

    reason_log = f" Motivo: {reason}" if reason else ""
    print(f"[transfer] user={phone} transferido para humano.{reason_log}")

    # Mensagem interna no chat (não visível ao cliente)
    internal_body = f"Transferido pelo agente em {now_fmt}"
    if reason:
        internal_body += f" — {reason}"
    database.save_message(
        conversation_id=conv["id"],
        phone=phone,
        direction="internal",
        body=internal_body,
        sender="system",
        msg_type="system",
    )

    # Busca mensagem de transferência configurável
    transfer_msg = database.get_setting("transfer_message", "") or _DEFAULT_TRANSFER_MESSAGE

    # Envia mensagem ao cliente (somente se send_message=True)
    if send_message:
        res = send_text(phone, transfer_msg)
        if res.get("ok"):
            database.save_message(
                conversation_id=conv["id"],
                phone=phone,
                direction="out",
                body=transfer_msg,
                sender="agent",
                msg_type="text",
            )
            database.update_conversation(conv["id"], last_message_at=database.agora_utc())
        else:
            print(f"[transfer] WARN: falha ao enviar msg de transferência p/ {phone}: {res.get('error')}")
    else:
        # Salva a mensagem de transferência no banco para envio posterior
        database.save_message(
            conversation_id=conv["id"],
            phone=phone,
            direction="out",
            body=transfer_msg,
            sender="agent",
            msg_type="text",
        )

    # Emite evento SSE para o painel atualizar em tempo real
    events.emit("conversation_updated", {
        "conversation_id": conv["id"],
        "auto_mode": 0,
        "transferred": True,
        "transferred_at": now,
    })

    return True


# ── Reset ─────────────────────────────────────────────────────────────────────

_PALAVRA_RESET_PADRAO = "#reset"

_MENSAGEM_RESET_PADRAO = (
    "Prontinho, recomecei o atendimento do zero! Aqui é a assistente virtual do "
    "consultório do Dr. Fabrício Guimarães. " + ficha_paciente.PERGUNTAS["nome"]
)


def palavra_de_reset() -> str:
    return (database.get_setting("reset_keyword", "") or _PALAVRA_RESET_PADRAO).strip().lower()


def e_pedido_de_reset(texto: str) -> bool:
    """A mensagem e a palavra-chave de reset?

    Token inteiro, nao trecho: "#reset" e "#reset por favor" contam, mas uma
    frase que apenas cite a palavra no meio de outra ("resetar a conversa") nao.
    """
    chave = palavra_de_reset()
    if not chave:
        return False
    limpo = (texto or "").strip().lower()
    return limpo == chave or chave in limpo.split()


def perform_reset(phone: str, origem: str = "cliente", avisar: bool = True) -> None:
    """Zera o atendimento e devolve a conversa para o agente.

    O espelho de perform_transfer: la a conversa sai do agente e vai para uma
    pessoa; aqui ela volta, com a ficha do paciente zerada.
    """
    agora_iso = datetime.utcnow().isoformat()

    contact = database.get_contact(phone) or database.upsert_contact(phone)
    database.update_contact(contact["id"], auto_mode=1)

    conv = database.get_or_create_conversation(phone)
    # reset_at corta o historico lido do banco; transferred_at volta a NULL
    # para a conversa sair da fila de atendimento humano do painel.
    database.update_conversation(conv["id"], reset_at=agora_iso, transferred_at=None)

    # Historico em memoria + ficha do atendimento.
    memory.reset(phone)

    database.save_message(
        conversation_id=conv["id"],
        phone=phone,
        direction="internal",
        body=f"Atendimento reiniciado por {origem} ({palavra_de_reset()}) em "
             f"{datetime.utcnow().strftime('%d/%m %H:%M')} — agente reativado",
        sender="system",
        msg_type="system",
    )

    events.emit("conversation_updated", {
        "conversation_id": conv["id"],
        "auto_mode": 1,
        "transferred": False,
        "reset_at": agora_iso,
    })

    print(f"[reset] user={phone} atendimento zerado e agente reativado ({origem})")

    if not avisar:
        return

    resposta = database.get_setting("reset_message", "") or _MENSAGEM_RESET_PADRAO
    res = send_text(phone, resposta)
    if res.get("ok"):
        database.save_message(
            conversation_id=conv["id"],
            phone=phone,
            direction="out",
            body=resposta,
            sender="agent",
            msg_type="text",
        )
        database.update_conversation(conv["id"], last_message_at=database.agora_utc())
        # A saudacao e a pergunta do nome acabaram de sair: a proxima mensagem
        # do paciente e a resposta a elas.
        try:
            ficha = ficha_paciente.load(phone)
            ficha["saudacao_feita"] = True
            ficha_paciente.marcar_pergunta(ficha, "nome")
            ficha_paciente.save(phone, ficha)
        except Exception as e:
            print(f"[reset] WARN nao marcou saudacao de {phone}: {e}")
    else:
        print(f"[reset] WARN falha ao confirmar reset p/ {phone}: {res.get('error')}")

# ── Envio ───────────────────────────────────────────────────────────────────

# Ritmo de digitacao entre as mensagens divididas por split_reply.
# Antes toda mensagem esperava 1 + len/200 segundos, inclusive a PRIMEIRA: o
# cliente ja tinha esperado o debounce e o modelo, e ainda levava mais ~2s para
# ver a primeira linha. Agora a primeira sai quase imediata e so as seguintes
# tem a pausa curta que imita digitacao.
PAUSA_PRIMEIRA = float(os.getenv("PAUSA_PRIMEIRA_SEG", "0.4"))
PAUSA_MIN = float(os.getenv("PAUSA_MIN_SEG", "0.8"))
PAUSA_MAX = float(os.getenv("PAUSA_MAX_SEG", "2.0"))

# Piso do tempo de resposta: o agente responde entre 5 e 10
# segundos. O teto sai do debounce curto e do ritmo acima; o piso existe porque
# resposta pronta e curta saia em ~4s, e resposta instantanea entrega que do
# outro lado nao tem ninguem digitando. Conta do ponto de vista do cliente,
# entao o debounce ja consumido entra na conta.
RESPOSTA_MIN_SEG = float(os.getenv("RESPOSTA_MIN_SEG", "5.0"))


def _pausa_digitacao(indice: int, chunk: str) -> float:
    if indice == 0:
        return PAUSA_PRIMEIRA
    return min(PAUSA_MAX, max(PAUSA_MIN, len(chunk) / 200))


def _esperar_piso(chegada: float | None) -> None:
    """Segura a primeira mensagem ate fechar RESPOSTA_MIN_SEG desde o cliente.

    `chegada` e o instante em que a mensagem entrou no webhook — o relogio do
    cliente. Antes isso era o comeco do flush mais BUFFER_SECONDS, o que
    ignorava os segundos gastos em gravar a mensagem e fazia o piso somar
    espera a quem ja tinha esperado demais.
    """
    if chegada is None:
        return
    decorrido = time.monotonic() - chegada
    if decorrido < RESPOSTA_MIN_SEG:
        time.sleep(RESPOSTA_MIN_SEG - decorrido)


def enviar_em_blocos(user: str, texto: str, chegada: float | None = None) -> None:
    """Envia a resposta ja dividida, com o ritmo de digitacao, e espelha no painel.

    `chegada` e o time.monotonic() de quando a mensagem do cliente chegou; com
    ele a primeira mensagem respeita o piso de RESPOSTA_MIN_SEG.
    """
    chunks = split_reply(texto) or ([texto] if texto else [])
    for indice, chunk in enumerate(chunks):
        pausa = _pausa_digitacao(indice, chunk)
        if pausa > 0:
            time.sleep(pausa)
        if indice == 0:
            _esperar_piso(chegada)
        res = send_text(user, chunk)
        if not res.get("ok"):
            print(f"[flush] ERRO ao enviar p/ {user}: {res.get('error')}")
            continue
        send_msg_out_to_panel(user, chunk)

# ── Flush handler ───────────────────────────────────────────────────────────

def _midia_do_lote(items: list[dict]) -> str:
    """Classifica a midia do lote para secretaria.decidir().

    Imagem e documento viram "arquivo": quase sempre e exame ou laudo, e a
    regra da base e nao interpretar exame - entao o conteudo nem vai ao modelo.
    """
    textos = [str(it.get("text", "")).strip() for it in items]
    if textos and all(t.startswith("[Video") for t in textos):
        return "video"
    if any(t.startswith(("[Imagem", "[Documento")) for t in textos):
        return "arquivo"
    return ""


_PLACEHOLDERS_SEM_TEXTO = ("[Figurinha]", "[Contato]", "[Video", "[Imagem", "[Documento", "[Localizacao")


def _texto_do_lote(items: list[dict]) -> str:
    """Texto que o paciente escreveu ou falou, sem os marcadores de midia."""
    partes = []
    for it in items:
        bruto = str(it.get("text", "") or "")
        if it.get("transcricao"):
            partes.append(it["transcricao"])
            continue
        if bruto.startswith("[Audio"):
            continue
        if bruto.startswith(_PLACEHOLDERS_SEM_TEXTO):
            # Legenda de imagem/documento ainda e texto do paciente.
            legenda = _re_mod.sub(r"^\[[^\]]*\]\s*", "", bruto).strip()
            if legenda:
                partes.append(legenda)
            continue
        partes.append(bruto)
    return "\n".join(p for p in partes if p.strip()).strip()


def _registrar_encaminhamento(user: str, ficha: dict) -> None:
    """Agendamento confirmado: nota interna, tarefa no CRM e fila humana.

    A agenda real e da equipe. O agente entrega o caso pronto - resumo da
    ficha e prioridade - para quem vai marcar o horario.
    """
    area = clinica.AREAS.get(ficha.get("area"), {})
    prioridade = "PRIORIDADE (trauma) - " if ficha.get("area") == "trauma" else ""
    titulo = f"{prioridade}Agendar avaliacao - {ficha.get('nome') or user}"
    descricao = (f"{ficha_paciente.resumo(ficha)}\n\nArea provavel (triagem, nao e diagnostico): "
                 f"{area.get('nome', 'nao identificada')}\nIntencao: {ficha.get('intencao', '')}")
    try:
        contact = database.get_contact(user) or database.upsert_contact(user)
        database.create_task(contact["id"], titulo, descricao)
        conv = database.get_or_create_conversation(user)
        database.save_message(
            conversation_id=conv["id"], phone=user, direction="internal",
            body=f"{titulo}\n\n{descricao}", sender="system", msg_type="system",
        )
    except Exception as e:
        print(f"[agendamento] WARN nao registrou tarefa de {user}: {e}")
    perform_transfer(user, reason=titulo, send_message=False)


def handle_flush(user: str, items: list[dict]) -> None:
    _chegada = min((it.get("recebido_em") or 0.0) for it in items) if items else 0.0
    if not _chegada:
        _chegada = time.monotonic() - BUFFER_SECONDS
    try:
        global_mode = int(database.get_setting("agent_mode", "1"))
        if not global_mode:
            print(f"[flush] user={user} agente GLOBAL desligado, ignorando")
            return

        contact = database.get_contact(user)
        if contact and not contact["auto_mode"]:
            print(f"[flush] user={user} modo=humano, ignorando agente")
            return

        # ── Palavras-chave de transferencia (antes de tudo) ─────────────────
        matched_kw = _check_transfer_keywords(items)
        if matched_kw:
            print(f"[flush] user={user} keyword de transferência detectada: '{matched_kw}'")
            perform_transfer(user, reason=f"paciente mencionou '{matched_kw}'")
            return

        last_wa_msg_id = items[-1].get("wa_message_id", "") if items else ""
        if last_wa_msg_id and last_wa_msg_id.startswith("wamid."):
            threading.Thread(target=_avisar_digitando_async,
                             args=(last_wa_msg_id,), daemon=True).start()

        # Audio: transcrito aqui, uma vez, para a ficha e o funil lerem o que
        # o paciente falou (e nao "[Audio]").
        if any(str(it.get("text", "")).startswith("[Audio") for it in items):
            _build_user_parts(items)

        midia = _midia_do_lote(items)
        texto = _texto_do_lote(items)
        if not texto and not midia and any(
                str(it.get("text", "")).startswith("[Audio") for it in items):
            midia = "audio_falhou"
        print(f"[flush] user={user} texto={texto[:120]!r} midia={midia or '-'}")

        ficha = ficha_paciente.load(user)
        decisao = secretaria.decidir(ficha, texto, secretaria.agora(), midia=midia)
        print(f"[secretaria] user={user} decisao={decisao.tipos} "
              f"llm={decisao.usar_llm} proxima={ficha.get('ultima_pergunta')!r}")

        # O historico guarda TEXTO: imagem de exame nunca vai ao modelo.
        memory.append(user, "user", texto or {
            "video": "[paciente enviou um video]",
            "arquivo": "[paciente enviou um arquivo/exame]",
            "audio_falhou": "[paciente enviou um audio que nao foi transcrito]",
        }.get(midia, "[mensagem sem texto]"))

        texto_modelo = ""
        if decisao.usar_llm:
            system = (
                _get_current_system_prompt()
                + "\n\n=== BASE OFICIAL (trechos recuperados da base de conhecimento) ===\n"
                + _contexto_rag(texto)
                + "\n\n" + secretaria.instrucoes_para_modelo(ficha, texto)
            )
            try:
                texto_modelo = llm.generate_reply(history=memory.get(user), system=system)
            except Exception as e:
                # Modelo fora do ar (429, rede): a duvida recebe a resposta
                # travada generica e o funil segue - nunca silencio.
                print(f"[flush] ERRO llm p/ {user}: {e}")

        mensagem, violacoes = secretaria.montar(decisao, texto_modelo)
        if violacoes:
            print(f"[trava] user={user} resposta do modelo BARRADA {violacoes}: "
                  f"{texto_modelo[:160]!r}")

        ficha_paciente.save(user, ficha)
        if ficha.get("nome") and (not contact or contact.get("name") != ficha["nome"]):
            try:
                database.upsert_contact(user, name=ficha["nome"])
            except Exception as e:
                print(f"[ficha] WARN nao atualizou contato: {e}")

        if mensagem:
            memory.append(user, "assistant", mensagem)
            enviar_em_blocos(user, mensagem, _chegada)

        if decisao.transferir:
            perform_transfer(user, reason=decisao.transferir, send_message=False)
        elif decisao.encaminhar:
            _registrar_encaminhamento(user, ficha)

        try:
            conv = database.get_or_create_conversation(user)
            database.reset_unread(conv["id"])
            events.emit("conversation_updated", {"conversation_id": conv["id"], "unread_count": 0})
        except Exception as e:
            print(f"[flush] WARN reset_unread falhou p/ {user}: {e}")
    except Exception as e:
        print(f"[flush] ERRO inesperado p/ {user}: {e}")
        import traceback
        traceback.print_exc()

def send_msg_out_to_panel(user: str, text: str) -> None:
    conv = database.get_or_create_conversation(user)
    database.save_message(
        conversation_id=conv["id"],
        phone=user,
        direction="out",
        body=text,
        sender="agent",
        msg_type="text",
    )
    database.update_conversation(conv["id"], last_message_at=database.agora_utc())
    events.emit("message_sent", {"conversation_id": conv["id"], "phone": user, "body": text})


# ── Download de midia async ──────────────────────────────────────────────────

_media_download_locks: dict[int, threading.Lock] = {}
_media_locks_guard = threading.Lock()


def _get_media_lock(msg_id: int) -> threading.Lock:
    with _media_locks_guard:
        lock = _media_download_locks.get(msg_id)
        if not lock:
            lock = threading.Lock()
            _media_download_locks[msg_id] = lock
        return lock


def _marcar_lido_async(wa_message_id: str) -> None:
    """Tique azul no celular do cliente. Nada depende do resultado."""
    try:
        mark_read(wa_message_id)
    except Exception as e:
        print(f"[meta] WARN: falha ao marcar como lido: {e}")


def _avisar_digitando_async(wa_message_id: str) -> None:
    """'digitando...' no WhatsApp. Enfeite: nao pode atrasar a resposta."""
    try:
        send_typing(wa_message_id)
    except Exception as e:
        print(f"[meta] WARN: falha ao enviar typing: {e}")


def _download_media_async(message_db_id: int, wa_media_id: str) -> None:
    """Baixa midia da Meta via media_id e armazena como data-URI."""
    try:
        m = database.get_message(message_db_id)
        if not m:
            return
        lock = _get_media_lock(message_db_id)
        with lock:
            fresh = database.get_message(message_db_id)
            if fresh and str(fresh.get("media_url") or "").strip():
                return
            if not wa_media_id:
                return
            info = get_webhook_media_url(wa_media_id)
            if not info.get("ok") or not isinstance(info.get("data"), dict):
                print(f"[media] falha get_media_url msg={message_db_id}: {info.get('error')}")
                return
            url = info["data"].get("url", "")
            mime = info["data"].get("mime_type", "application/octet-stream")
            if not url:
                print(f"[media] URL vazia msg={message_db_id}")
                return
            data = download_media_bytes(url)
            if not data:
                print(f"[media] download vazio msg={message_db_id}")
                return
            import base64
            b64 = base64.b64encode(data).decode()
            data_uri = f"data:{mime};base64,{b64}"
            database.update_message_media(message_db_id, data_uri)
            print(f"[media] msg={message_db_id} guardado len={len(data_uri)}")
    except Exception as e:
        print(f"[media] ERRO download msg={message_db_id}: {e}")


def _fetch_and_store_media(m: dict) -> str:
    """Busca media on-demand (para o painel)."""
    msg_id = m["id"]
    lock = _get_media_lock(msg_id)
    with lock:
        fresh = database.get_message(msg_id)
        if fresh and str(fresh.get("media_url") or "").strip():
            url = fresh["media_url"]
            if url.startswith("data:") and len(url) > 500:
                return url
        wa_media_id = str((fresh or {}).get("wa_media_id") or "")
        if not wa_media_id:
            return ""
        info = get_webhook_media_url(wa_media_id)
        if not info.get("ok") or not isinstance(info.get("data"), dict):
            return ""
        url = info["data"].get("url", "")
        mime = info["data"].get("mime_type", "application/octet-stream")
        if not url:
            return ""
        data = download_media_bytes(url)
        if not data:
            return ""
        import base64
        b64 = base64.b64encode(data).decode()
        data_uri = f"data:{mime};base64,{b64}"
        database.update_message_media(msg_id, data_uri)
        return data_uri


# ── Mapeamento de tipos de midia ─────────────────────────────────────────────

_MEDIA_PLACEHOLDERS = {
    "image": lambda m: f"[Imagem]{(' ' + m.get('caption', '')) if m.get('caption') else ''}",
    "video": lambda m: f"[Video]{(' ' + m.get('caption', '')) if m.get('caption') else ''}",
    "audio": lambda m: "[Audio]" if not m.get("audio", {}).get("voice") else "[Audio (mensagem de voz)]",
    "document": lambda m: f"[Documento: {m.get('document', {}).get('filename', '')}]",
    "sticker": lambda m: "[Figurinha]",
    # Pino do mapa: com endereco, ele vira texto (a ficha pode ler a cidade).
    "location": lambda m: (
        "[Localizacao] " + ", ".join(p for p in (
            (m.get("location") or {}).get("name", ""),
            (m.get("location") or {}).get("address", "")) if p)
        if ((m.get("location") or {}).get("name") or (m.get("location") or {}).get("address"))
        else "[Localizacao]"),
    "contacts": lambda m: "[Contato]",
}


def _extract_body_from_meta_message(msg_data: dict) -> tuple[str, str, str]:
    """Extrai (body, msg_type, wa_media_id) de uma mensagem Meta.
    Retorna (body, msg_type, wa_media_id).
    """
    msg_type = msg_data.get("type", "text")
    wa_media_id = ""

    if msg_type == "text":
        return msg_data.get("text", {}).get("body", ""), "text", ""

    if msg_type in _MEDIA_PLACEHOLDERS:
        media_obj = msg_data.get(msg_type, {})
        wa_media_id = media_obj.get("id", "")
        body = _MEDIA_PLACEHOLDERS[msg_type](msg_data)
        return body, msg_type, wa_media_id

    if msg_type == "interactive":
        interactive = msg_data.get("interactive", {})
        itype = interactive.get("type", "")
        if itype == "button_reply":
            br = interactive.get("button_reply", {})
            return br.get("title", br.get("id", "")), "button_reply", ""
        if itype == "list_reply":
            lr = interactive.get("list_reply", {})
            return lr.get("title", lr.get("id", "")), "list_reply", ""
        return f"[Interativo: {itype}]", itype, ""

    return f"[{msg_type}]", msg_type, ""


# ── App & Buffer ──────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

limiter = Limiter(get_remote_address, app=app, default_limits=["200 per minute"])

buffer = MessageBuffer(wait_seconds=BUFFER_SECONDS, on_flush=handle_flush)

database.init_db()

# Sobe a base do Dr. Fabricio para o knowledge (RAG) na primeira subida.
garantir_base_de_conhecimento()

# Inicia o scheduler de follow-ups CRM
try:
    crm_scheduler.start_scheduler()
except Exception as e:
    print(f"[crm] WARN: scheduler nao iniciado: {e}")

print(f"[config] Datafy API: PHONE_ID={os.getenv('DATAFY_PHONE_NUMBER_ID', '') or 'N/A'}")
print(f"[config] Datafy API: WABA_ID={os.getenv('DATAFY_WABA_ID', '') or 'N/A'}")

# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/login")
def login_page():
    if session.get("logged_in"):
        return redirect(url_for("panel_page"))
    return render_template("login.html")


@app.post("/login")
@limiter.limit("5 per minute")
def login_action():
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    if do_login(username, password):
        return redirect(url_for("panel_page"))
    return render_template("login.html", error="Credenciais invalidas")


@app.get("/logout")
def logout_action():
    do_logout()
    return redirect(url_for("login_page"))


# ── Security Headers ─────────────────────────────────────────────────────────

@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ── Webhook ──────────────────────────────────────────────────────────────────

@app.get("/webhook")
def webhook_verify():
    """Para a Datafy API essa rota não é chamada da mesma maneira que a Meta chama com GET."""
    return "Datafy API endpoint", 200


@app.post("/webhook")
def webhook():
    # Validação Datafy
    signature = request.headers.get("x-datafy-signature-256", "")
    timestamp = request.headers.get("x-datafy-timestamp", "")
    raw_body = request.get_data(as_text=True)

    if DATAFY_WEBHOOK_SECRET and signature and timestamp:
        expected = "sha256=" + hmac.new(
            DATAFY_WEBHOOK_SECRET.encode("utf-8"),
            f"{timestamp}.{raw_body}".encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature.encode("utf-8"), expected.encode("utf-8")):
            print("[webhook] Assinatura invalida (Datafy)")
            return "Forbidden", 401

        try:
            req_ts = int(timestamp)
            if abs(time.time() - req_ts) > 300:
                print("[webhook] Timestamp fora do limite de 5 minutos (Datafy)")
                return "Forbidden", 401
        except ValueError:
            print("[webhook] Timestamp invalido (Datafy)")
            return "Forbidden", 401

    data = request.get_json(silent=True) or {}

    # Validacao basica Meta / Datafy
    if data.get("object") != "whatsapp_business_account":
        print(f"[webhook] object invalido: {data.get('object')}")
        return jsonify({"ok": True})

    # Itera entry -> changes -> value
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if change.get("field") != "messages":
                continue

            # Status updates (entrega/leitura) -> ignorar
            if "statuses" in value:
                for status in value["statuses"]:
                    print(f"[webhook] status: {status.get('status')} id={status.get('id', '')[:30]}")
                continue

            # Mensagens recebidas
            if "messages" not in value:
                continue

            contacts = value.get("contacts", [])
            messages = value["messages"]

            if not messages:
                continue

            msg_data = messages[0]
            number = msg_data.get("from", "")
            message_id = msg_data.get("id", "")
            timestamp = msg_data.get("timestamp", "")

            if not number:
                print("[webhook] SEM REMETENTE")
                continue

            # push_name e avatar do contato
            push_name = ""
            profile_picture_url = ""
            if contacts:
                profile = contacts[0].get("profile", {})
                push_name = profile.get("name", "")
                profile_picture_url = profile.get("profile_picture_url", "")

            # Extrai body e tipo
            body, msg_type, wa_media_id = _extract_body_from_meta_message(msg_data)

            if not body:
                print(f"[webhook] SEM BODY: msg_type={msg_type} from={number}")
                continue

            _chegou_em = time.monotonic()
            print(f"[webhook] from={number} ({push_name}) type={msg_type} len={len(body)} msg_id={message_id[:30]}")

            # Marca como lido em background. E uma chamada de rede a Datafy
            # (0,9s medido em producao) cujo resultado ninguem espera: o tique
            # azul no celular do cliente nao muda uma virgula da resposta.
            # Segurava o debounce sem motivo.
            threading.Thread(
                target=_marcar_lido_async, args=(str(message_id),), daemon=True,
            ).start()

            # Salva contato e conversa
            contact_kwargs = {}
            if push_name:
                contact_kwargs["name"] = push_name
            if profile_picture_url:
                contact_kwargs["avatar_url"] = profile_picture_url
            contact = database.upsert_contact(number, **contact_kwargs)
            conv = database.get_or_create_conversation(number)
            saved = database.save_message(
                conversation_id=conv["id"],
                phone=number,
                direction="in",
                body=body,
                sender="user",
                msg_type=str(msg_type) if msg_type else "text",
                wa_message_id=str(message_id) if message_id else None,
                wa_media_id=wa_media_id,
            )
            # A Meta REENTREGA o mesmo wamid quando o ack demora — foi assim
            # que um unico "#RESET" do dono virou dois resets no banco, com
            # 51 segundos de diferenca (24/09, 02:42:21 e 02:43:02). Ali foi
            # inofensivo; num pedido, a segunda entrega seria uma segunda
            # resposta, e num "SIM" seria um segundo pedido.
            #
            # save_message devolve None em DOIS casos: duplicata e falha ao
            # gravar. So o primeiro pode ser descartado — descartar o segundo
            # seria deixar um cliente sem resposta por causa de um erro nosso.
            _ja_processada = False
            if saved is None and message_id:
                _ja_processada = database.mensagem_ja_recebida(str(message_id))
                if _ja_processada:
                    print(f"[webhook] REENTREGA ignorada wamid={message_id} "
                          f"from={number}")
                else:
                    print(f"[webhook] WARN falha ao gravar wamid={message_id}; "
                          f"processando assim mesmo para nao perder o cliente")

            # A partir daqui nada mais precisa ser feito ANTES de comecar a
            # contar o debounce. O que vem abaixo — CRM, follow-ups, SSE do
            # painel — sao 1,4s de banco que o cliente estava esperando de pe,
            # embora nenhum deles mude a resposta. Disparando o buffer aqui,
            # eles passam a correr dentro dos 3s de silencio, de graca.
            #
            # save_message fica acima porque e ele quem faz a deduplicacao (a
            # Meta reentrega o mesmo wamid) e quem devolve o msg_id da midia.
            # Comecar o debounce antes dele processaria a mensagem duas vezes.
            if not e_pedido_de_reset(body) and not _ja_processada:
                # Download de midia em background — antes do CRM, para ter os
                # 3s inteiros do debounce e chegar pronta em _build_user_parts.
                if saved and wa_media_id and msg_type != "text":
                    threading.Thread(
                        target=_download_media_async,
                        args=(saved["id"], wa_media_id),
                        daemon=True,
                    ).start()
                buffer.add(number, body,
                           msg_id=saved["id"] if saved else None,
                           wa_message_id=str(message_id) if message_id else "",
                           wa_media_id=wa_media_id,
                           recebido_em=_chegou_em)

            if saved:
                database.update_conversation(conv["id"], last_message_at=database.agora_utc())
                database.increment_unread(conv["id"])
                # CRM: atualizar última interação e cancelar/recriar follow-ups
                database.update_contact(contact["id"], last_interaction_at=database.agora_utc())
                database.cancel_follow_ups_for_contact(contact["id"])
                try:
                    database.create_follow_ups_for_contact(contact["id"])
                except Exception as e:
                    print(f"[crm] WARN: falha ao recriar follow-ups: {e}")
                events.emit("new_message", {
                    "conversation_id": conv["id"],
                    "contact_name": contact.get("name", ""),
                    "phone": number,
                    "body": body,
                    "message_id": str(message_id),
                })
                print(f"[webhook] MSG SALVA conv={conv['id']} from={number} len={len(body)}")
            elif not _ja_processada:
                print(f"[webhook] MSG NAO GRAVADA msg_id={message_id}")

            # #reset nao entra no debounce — a palavra nao e conversa, e
            # comando — e roda DEPOIS do CRM justamente por nao ter pressa:
            # ele precisa funcionar quando a conversa esta em modo humano, que
            # e onde handle_flush desiste logo no inicio.
            if e_pedido_de_reset(body) and not _ja_processada:
                try:
                    perform_reset(number, origem="cliente")
                except Exception as e:
                    print(f"[reset] ERRO ao reiniciar {number}: {e}")
                continue

    return jsonify({"ok": True})


@app.get("/")
def index():
    return redirect(url_for("panel_page"))


# ── Panel page ────────────────────────────────────────────────────────────────

@app.get("/panel")
@login_required
def panel_page():
    return render_template("index.html")


# ── SSE ───────────────────────────────────────────────────────────────────────

@app.get("/api/events")
@login_required
def sse_stream():
    import queue as _queue
    def stream():
        q = events.subscribe()
        try:
            while True:
                try:
                    data = q.get(timeout=20)
                    yield f"data: {data}\n\n"
                except _queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            events.unsubscribe(q)
    return Response(stream(), content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/api/dashboard")
@login_required
def api_dashboard():
    return jsonify(database.get_dashboard_stats())


# ── Conversations ─────────────────────────────────────────────────────────────

@app.get("/api/conversations")
@login_required
def api_conversations_list():
    status = request.args.get("status", "")
    limit = min(int(request.args.get("limit", "100")), 500)
    offset = max(int(request.args.get("offset", "0")), 0)
    arch = request.args.get("archived", "")
    archived = None if arch == "" else (arch == "1" or arch.lower() == "true")
    if status == "archived":
        status = ""
        archived = True
    # Filtro por modo: auto_mode=1 (bot) ou auto_mode=0 (fila humana)
    auto_mode_param = request.args.get("auto_mode", "")
    auto_mode = int(auto_mode_param) if auto_mode_param in ("0", "1") else None
    convs = database.list_conversations(status=status, archived=archived, auto_mode=auto_mode, limit=limit, offset=offset)
    return jsonify(convs)


@app.get("/api/conversations/<int:conv_id>")
@login_required
def api_conversations_detail(conv_id):
    conv = database.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "not found"}), 404
    contact = database.get_contact_by_id(conv["contact_id"])
    messages = database.get_messages(conv_id, limit=200)
    for m in messages:
        mu = m.get("media_url") or ""
        if mu.startswith("data:"):
            m["media_url"] = ""
    tags = database.get_conversation_tags(conv_id)
    return jsonify({"conversation": conv, "contact": contact, "messages": messages, "tags": tags})


@app.put("/api/conversations/<int:conv_id>/status")
@login_required
def api_conversations_update_status(conv_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status", "")
    if status not in ("new", "open", "waiting", "resolved", "closed"):
        return jsonify({"error": "invalid status"}), 400
    database.update_conversation(conv_id, status=status)
    events.emit("conversation_updated", {"conversation_id": conv_id, "status": status})
    return jsonify({"ok": True})


@app.put("/api/conversations/<int:conv_id>/assign")
@login_required
def api_conversations_assign(conv_id):
    data = request.get_json(silent=True) or {}
    assigned_to = data.get("assigned_to", "")
    database.update_conversation(conv_id, assigned_to=assigned_to)
    events.emit("conversation_updated", {"conversation_id": conv_id, "assigned_to": assigned_to})
    return jsonify({"ok": True})


@app.put("/api/conversations/<int:conv_id>/mode")
@login_required
def api_conversations_toggle_mode(conv_id):
    conv = database.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "not found"}), 404
    contact = database.get_contact_by_id(conv["contact_id"])
    if not contact:
        return jsonify({"error": "contact not found"}), 404
    new_mode = 0 if contact["auto_mode"] else 1
    database.update_contact(contact["id"], auto_mode=new_mode)
    events.emit("conversation_updated", {"conversation_id": conv_id, "auto_mode": new_mode})
    return jsonify({"ok": True, "auto_mode": new_mode})


@app.put("/api/conversations/<int:conv_id>/read")
@login_required
def api_conversations_mark_read(conv_id):
    conv = database.get_conversation(conv_id)
    database.reset_unread(conv_id)
    if conv:
        contact = database.get_contact_by_id(conv["contact_id"])
        if contact and contact.get("phone"):
            number = str(contact["phone"])
            # Busca a ultima mensagem RECEBIDA para mark_read na Meta
            # (nao usa a ultima mensagem da conversa, que pode ser enviada pelo agente)
            import db as _db
            msgs = _db.fetch_all(
                "SELECT * FROM messages WHERE conversation_id=? AND direction='in' ORDER BY created_at DESC LIMIT 1",
                (conv_id,),
            )
            if msgs:
                wa_mid = msgs[0].get("wa_message_id", "")
                if wa_mid:
                    try:
                        mark_read(wa_mid)
                    except Exception:
                        pass
    events.emit("conversation_updated", {"conversation_id": conv_id, "unread_count": 0})
    return jsonify({"ok": True})


@app.put("/api/conversations/<int:conv_id>/unread")
@login_required
def api_conversations_mark_unread(conv_id):
    database.mark_unread(conv_id)
    events.emit("conversation_updated", {"conversation_id": conv_id, "unread_count": 1})
    return jsonify({"ok": True})


@app.put("/api/conversations/<int:conv_id>/flags")
@login_required
def api_conversations_update_flags(conv_id):
    """Atualiza flags (archived/muted/pinned/favorite). DB only — Meta nao suporta."""
    data = request.get_json(silent=True) or {}
    fields = {}
    for key in ("archived", "muted", "pinned", "favorite"):
        if key in data:
            fields[key] = 1 if data[key] else 0

    conv = database.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "not found"}), 404

    if fields:
        database.update_conversation(conv_id, **fields)
        events.emit("conversation_updated", {"conversation_id": conv_id, **fields})

    return jsonify({"ok": True, **fields})


@app.post("/api/conversations/<int:conv_id>/clear")
@login_required
def api_conversations_clear(conv_id):
    database.clear_conversation(conv_id)
    events.emit("conversation_updated", {"conversation_id": conv_id, "cleared": True})
    return jsonify({"ok": True})


@app.delete("/api/conversations/<int:conv_id>")
@login_required
def api_conversations_delete(conv_id):
    database.delete_conversation(conv_id)
    events.emit("conversation_updated", {"conversation_id": conv_id, "deleted": True})
    return jsonify({"ok": True})


@app.post("/api/conversations/<int:conv_id>/tags")
@login_required
def api_conversations_add_tag(conv_id):
    data = request.get_json(silent=True) or {}
    tag_id = data.get("tag_id")
    if not tag_id:
        return jsonify({"error": "tag_id required"}), 400
    database.add_tag_to_conversation(conv_id, tag_id)
    events.emit("tags_updated", {"conversation_id": conv_id, "tag_id": tag_id, "action": "add"})
    return jsonify({"ok": True})


@app.delete("/api/conversations/<int:conv_id>/tags/<int:tag_id>")
@login_required
def api_conversations_remove_tag(conv_id, tag_id):
    import db
    db.execute("DELETE FROM conversation_tags WHERE conversation_id=? AND tag_id=?", (conv_id, tag_id))
    events.emit("tags_updated", {"conversation_id": conv_id, "tag_id": tag_id, "action": "remove"})
    return jsonify({"ok": True})


@app.post("/api/conversations/bulk")
@login_required
def api_conversations_bulk():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    action = data.get("action", "")
    params = data.get("params") or {}
    if not ids or not isinstance(ids, list):
        return jsonify({"error": "ids required"}), 400

    processed = 0
    errors = []

    # Otimizacao: queries bulk sem validacao individual
    if action in ("read", "unread") and ids:
        if action == "read":
            database.reset_unread_bulk(ids)
        else:
            database.mark_unread_bulk(ids)
        events.emit("conversation_updated", {"conversation_ids": ids, "unread_count": 0 if action == "read" else 1})
        return jsonify({"ok": True, "processed": len(ids), "errors": []})

    if action in ("archive", "mute", "pin", "favorite") and ids:
        field_map = {"archive": "archived", "mute": "muted", "pin": "pinned", "favorite": "favorite"}
        field = field_map[action]
        value = 1 if params.get(field, True) else 0
        now = datetime.utcnow().isoformat()
        placeholders = ",".join("?" * len(ids))
        import db
        db.execute(
            f"UPDATE conversations SET {field}=?, updated_at=? WHERE id IN ({placeholders})",
            (value, now, *ids),
        )
        events.emit("conversation_updated", {"conversation_ids": ids, field: value})
        return jsonify({"ok": True, "processed": len(ids), "errors": []})

    if action == "status" and ids:
        status = params.get("status", "")
        if status not in ("new", "open", "waiting", "resolved", "closed"):
            return jsonify({"error": "invalid status"}), 400
        now = datetime.utcnow().isoformat()
        placeholders = ",".join("?" * len(ids))
        import db
        db.execute(
            f"UPDATE conversations SET status=?, updated_at=? WHERE id IN ({placeholders})",
            (status, now, *ids),
        )
        events.emit("conversation_updated", {"conversation_ids": ids, "status": status})
        return jsonify({"ok": True, "processed": len(ids), "errors": []})

    if action == "clear" and ids:
        for cid in ids:
            try:
                database.clear_conversation(cid)
            except Exception:
                pass
        events.emit("conversation_updated", {"conversation_ids": ids, "cleared": True})
        return jsonify({"ok": True, "processed": len(ids), "errors": []})

    if action == "delete" and ids:
        for cid in ids:
            try:
                database.delete_conversation(cid)
            except Exception:
                pass
        events.emit("conversation_updated", {"conversation_ids": ids, "deleted": True})
        return jsonify({"ok": True, "processed": len(ids), "errors": []})

    if action == "add_tag" and ids:
        tag_id = params.get("tag_id")
        if not tag_id:
            return jsonify({"error": "tag_id required"}), 400
        for cid in ids:
            try:
                database.add_tag_to_conversation(cid, tag_id)
            except Exception:
                pass
        events.emit("tags_updated", {"conversation_ids": ids, "tag_id": tag_id, "action": "add"})
        return jsonify({"ok": True, "processed": len(ids), "errors": []})

    if action == "remove_tag" and ids:
        tag_id = params.get("tag_id")
        if not tag_id:
            return jsonify({"error": "tag_id required"}), 400
        for cid in ids:
            try:
                import db
                db.execute("DELETE FROM conversation_tags WHERE conversation_id=? AND tag_id=?", (cid, tag_id))
            except Exception:
                pass
        events.emit("tags_updated", {"conversation_ids": ids, "tag_id": tag_id, "action": "remove"})
        return jsonify({"ok": True, "processed": len(ids), "errors": []})

    # Fallback: mode (precisa de loop por contact individual)
    if action == "mode" and ids:
        now = datetime.utcnow().isoformat()
        placeholders = ",".join("?" * len(ids))
        import db
        rows = db.fetch_all(
            f"SELECT c.id as conv_id, ct.id as contact_id, ct.auto_mode FROM conversations c "
            f"JOIN contacts ct ON c.contact_id=ct.id WHERE c.id IN ({placeholders})",
            tuple(ids),
        )
        for row in rows:
            new_mode = 0 if row["auto_mode"] else 1
            database.update_contact(row["contact_id"], auto_mode=new_mode)
            events.emit("conversation_updated", {"conversation_id": row["conv_id"], "auto_mode": new_mode})
            processed += 1
        return jsonify({"ok": True, "processed": processed, "errors": errors})

    return jsonify({"ok": True, "processed": processed, "errors": errors})


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings/agent-mode")
@login_required
def api_get_agent_mode():
    val = database.get_setting("agent_mode", "1")
    return jsonify({"auto_mode": int(val)})


@app.put("/api/settings/agent-mode")
@login_required
def api_set_agent_mode():
    data = request.get_json(silent=True) or {}
    auto = 1 if data.get("auto_mode", True) else 0
    database.set_setting("agent_mode", str(auto))
    return jsonify({"ok": True, "auto_mode": auto})


_DEFAULT_TRANSFER_MESSAGE = os.getenv(
    "TRANSFER_MESSAGE",
    "Estou transferindo você para um atendente humano. Aguarde um momento, logo alguém irá te atender. 😊"
)


@app.get("/api/settings/transfer-message")
@login_required
def api_get_transfer_message():
    msg = database.get_setting("transfer_message", "") or _DEFAULT_TRANSFER_MESSAGE
    return jsonify({"transfer_message": msg})


@app.put("/api/settings/transfer-message")
@login_required
def api_set_transfer_message():
    data = request.get_json(silent=True) or {}
    msg = data.get("transfer_message", "").strip()
    if not msg:
        return jsonify({"error": "transfer_message não pode ser vazio"}), 400
    database.set_setting("transfer_message", msg)
    return jsonify({"ok": True, "transfer_message": msg})

@app.get("/api/settings/reset")
@login_required
def api_get_reset_settings():
    return jsonify({
        "reset_keyword": palavra_de_reset(),
        "reset_message": database.get_setting("reset_message", "") or _MENSAGEM_RESET_PADRAO,
    })


@app.put("/api/settings/reset")
@login_required
def api_set_reset_settings():
    data = request.get_json(silent=True) or {}
    if "reset_keyword" in data:
        chave = str(data["reset_keyword"]).strip().lower()
        # Palavra de uma peca so: o reconhecimento e por token, entao uma chave
        # com espaco nunca seria reconhecida.
        if not chave or len(chave.split()) != 1:
            return jsonify({"error": "reset_keyword deve ser uma palavra unica, sem espacos"}), 400
        database.set_setting("reset_keyword", chave)
    if "reset_message" in data:
        msg = str(data["reset_message"]).strip()
        if not msg:
            return jsonify({"error": "reset_message não pode ser vazio"}), 400
        database.set_setting("reset_message", msg)
    return jsonify({
        "ok": True,
        "reset_keyword": palavra_de_reset(),
        "reset_message": database.get_setting("reset_message", "") or _MENSAGEM_RESET_PADRAO,
    })

@app.post("/api/conversations/<phone>/reset")
@login_required
def api_reset_conversation(phone: str):
    """Mesmo reset da palavra-chave, disparado pelo painel.

    Antes isto so apagava a ficha (conversation_state), o que deixava a
    conversa em modo humano e com o historico antigo: quem clicava aqui depois
    de um transbordo continuava sem o agente. Agora faz o reset inteiro.
    Para o comportamento antigo, silencioso, passe {"avisar": false}.
    """
    data = request.get_json(silent=True) or {}
    try:
        perform_reset(phone, origem="painel", avisar=bool(data.get("avisar", True)))
        return jsonify({"ok": True, "message": f"Atendimento de {phone} reiniciado"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/conversations/<phone>/state")
@login_required
def api_get_conversation_state(phone: str):
    """Retorna a ficha do paciente (estado da conversa)."""
    state = database.get_conversation_state(phone)
    if state:
        return jsonify({"phone": phone, "state": state})
    return jsonify({"phone": phone, "state": None})


@app.get("/api/conversations/human-queue/count")
@login_required
def api_human_queue_count():
    """Retorna a contagem de conversas não lidas em modo humano (auto_mode=0 e unread_count > 0)."""
    count = database.count_unread_human_conversations()
    return jsonify({"count": count})


# ── Messages ──────────────────────────────────────────────────────────────────

@app.post("/api/messages/send")
@login_required
def api_messages_send():
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    body = data.get("body", "").strip()
    if not phone or not body:
        return jsonify({"error": "phone and body required"}), 400

    res = send_text(phone, body)
    if not res.get("ok"):
        err = res.get("error") or "Falha ao enviar mensagem."
        print(f"[api] ERRO ao enviar p/ {phone}: {err}")
        return jsonify({"error": err}), (res.get("status") or 500)

    # Extrai wa_id da resposta Meta
    data_res = res.get("data") or {}
    contacts = data_res.get("contacts", [])
    wa_id = contacts[0].get("wa_id", phone) if contacts else phone
    messages_res = data_res.get("messages", [])
    meta_msg_id = messages_res[0].get("id", "") if messages_res else ""

    contact = database.upsert_contact(wa_id)
    conv = database.get_or_create_conversation(wa_id)
    database.save_message(
        conversation_id=conv["id"],
        phone=wa_id,
        direction="out",
        body=body,
        sender="human",
        msg_type="text",
        wa_message_id=meta_msg_id,
    )
    database.update_conversation(conv["id"], last_message_at=database.agora_utc())
    events.emit("message_sent", {"conversation_id": conv["id"], "phone": wa_id, "body": body})
    return jsonify({"ok": True, "phone": wa_id, "message_id": meta_msg_id})


@app.post("/api/messages/send-media")
@login_required
def api_messages_send_media():
    """Envia midia (imagem, video, audio, documento) via WhatsApp."""
    if "media" not in request.files:
        return jsonify({"error": "Arquivo de midia requerido"}), 400
    
    phone = request.form.get("phone", "").strip()
    media_type = request.form.get("type", "").strip()
    caption = request.form.get("caption", "").strip()
    
    if not phone:
        return jsonify({"error": "Phone requerido"}), 400
    
    if not media_type or media_type not in ["image", "video", "audio", "document"]:
        return jsonify({"error": "Tipo de midia invalido"}), 400
    
    f = request.files["media"]
    if not f.filename:
        return jsonify({"error": "Filename requerido"}), 400
    
    import mimetypes
    mime = mimetypes.guess_type(f.filename)[0] or "application/octet-stream"
    file_bytes = f.read()
    
    # Upload da midia para o servidor Meta
    from meta import upload_media_bytes
    upload_result = upload_media_bytes(file_bytes, mime, f.filename)
    
    if not upload_result.get("ok"):
        err = upload_result.get("error", "Erro ao fazer upload da midia")
        print(f"[api] ERRO upload media p/ {phone}: {err}")
        return jsonify({"error": err}), (upload_result.get("status") or 500)
    
    media_id = upload_result.get("data", {}).get("id", "")
    if not media_id:
        return jsonify({"error": "media_id nao retornado"}), 500
    
    # Envia a midia conforme o tipo
    from meta import send_image, send_video, send_audio, send_document
    
    if media_type == "image":
        res = send_image(phone, media_id, caption)
    elif media_type == "video":
        res = send_video(phone, media_id, caption)
    elif media_type == "audio":
        res = send_audio(phone, media_id)
    elif media_type == "document":
        res = send_document(phone, media_id, f.filename, caption)
    else:
        return jsonify({"error": "Tipo de midia nao suportado"}), 400
    
    if not res.get("ok"):
        err = res.get("error") or "Falha ao enviar midia."
        print(f"[api] ERRO ao enviar media p/ {phone}: {err}")
        return jsonify({"error": err}), (res.get("status") or 500)
    
    # Extrai wa_id da resposta Meta
    data_res = res.get("data") or {}
    contacts = data_res.get("contacts", [])
    wa_id = contacts[0].get("wa_id", phone) if contacts else phone
    messages_res = data_res.get("messages", [])
    meta_msg_id = messages_res[0].get("id", "") if messages_res else ""
    
    # Salva no banco
    contact = database.upsert_contact(wa_id)
    conv = database.get_or_create_conversation(wa_id)
    
    # Corpo da mensagem
    body = caption if caption else f"[{media_type.upper()}]"
    
    saved_msg = database.save_message(
        conversation_id=conv["id"],
        phone=wa_id,
        direction="out",
        body=body,
        sender="human",
        msg_type=media_type,
        wa_message_id=meta_msg_id,
        wa_media_id=media_id,
    )
    
    db_msg_id = saved_msg["id"] if saved_msg else ""
    
    database.update_conversation(conv["id"], last_message_at=database.agora_utc())
    events.emit("message_sent", {"conversation_id": conv["id"], "phone": wa_id, "body": body})
    
    return jsonify({"ok": True, "phone": wa_id, "message_id": meta_msg_id, "media_type": media_type, "db_msg_id": db_msg_id})


@app.get("/api/messages/<int:msg_id>/media")
@login_required
def api_messages_media(msg_id):
    m = database.get_message(msg_id)
    if not m:
        return jsonify({"error": "not found"}), 404
    media_url = str(m.get("media_url", "") or "").strip()
    if not media_url:
        try:
            media_url = _fetch_and_store_media(m)
        except Exception as e:
            print(f"[media] erro on-demand msg={msg_id}: {e}")
            media_url = ""
    return jsonify({
        "msg_id": m["id"],
        "msg_type": m.get("msg_type", "text"),
        "media_url": media_url,
        "body": m.get("body", "") or "",
        "ready": bool(media_url),
    })


# ── Contacts ──────────────────────────────────────────────────────────────────

@app.get("/api/contacts")
@login_required
def api_contacts_list():
    limit = min(int(request.args.get("limit", "100")), 500)
    offset = max(int(request.args.get("offset", "0")), 0)
    return jsonify(database.list_contacts(limit=limit, offset=offset))


@app.post("/api/contacts")
@login_required
def api_contacts_create():
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400
    contact = database.upsert_contact(
        phone,
        name=data.get("name", ""),
        email=data.get("email", ""),
        company=data.get("company", ""),
        notes=data.get("notes", ""),
    )
    return jsonify(contact)


@app.get("/api/contacts/<int:contact_id>")
@login_required
def api_contacts_detail(contact_id):
    contact = database.get_contact_by_id(contact_id)
    if not contact:
        return jsonify({"error": "not found"}), 404
    tags = database.get_contact_tags(contact_id)
    tasks = database.list_tasks(contact_id)
    return jsonify({"contact": contact, "tags": tags, "tasks": tasks})


@app.put("/api/contacts/<int:contact_id>")
@login_required
def api_contacts_update(contact_id):
    data = request.get_json(silent=True) or {}
    database.update_contact(contact_id, **data)
    return jsonify({"ok": True})


@app.delete("/api/contacts/<int:contact_id>")
@login_required
def api_contacts_delete(contact_id):
    database.delete_contact(contact_id)
    return jsonify({"ok": True})


@app.post("/api/contacts/<int:contact_id>/tags")
@login_required
def api_contacts_add_tag(contact_id):
    data = request.get_json(silent=True) or {}
    tag_id = data.get("tag_id")
    if not tag_id:
        return jsonify({"error": "tag_id required"}), 400
    database.add_tag_to_contact(contact_id, tag_id)
    events.emit("tags_updated", {"contact_id": contact_id, "tag_id": tag_id, "action": "add"})
    return jsonify({"ok": True})


@app.delete("/api/contacts/<int:contact_id>/tags/<int:tag_id>")
@login_required
def api_contacts_remove_tag(contact_id, tag_id):
    database.remove_tag_from_contact(contact_id, tag_id)
    events.emit("tags_updated", {"contact_id": contact_id, "tag_id": tag_id, "action": "remove"})
    return jsonify({"ok": True})


# ── Tags ──────────────────────────────────────────────────────────────────────

@app.get("/api/tags")
@login_required
def api_tags_list():
    return jsonify(database.list_tags())


@app.post("/api/tags")
@login_required
def api_tags_create():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    tag = database.create_tag(name, color=data.get("color", "#6366f1"))
    events.emit("tags_updated", {"tag": tag, "action": "create"})
    return jsonify(tag)


@app.put("/api/tags/<int:tag_id>")
@login_required
def api_tags_update(tag_id):
    data = request.get_json(silent=True) or {}
    database.update_tag(tag_id, name=data.get("name", ""), color=data.get("color", ""))
    events.emit("tags_updated", {"tag_id": tag_id, "action": "update"})
    return jsonify({"ok": True})


@app.delete("/api/tags/<int:tag_id>")
@login_required
def api_tags_delete(tag_id):
    database.delete_tag(tag_id)
    events.emit("tags_updated", {"tag_id": tag_id, "action": "delete"})
    return jsonify({"ok": True})


# ── Templates ─────────────────────────────────────────────────────────────────

@app.get("/api/templates")
@login_required
def api_templates_list():
    return jsonify(database.list_templates())


@app.post("/api/templates")
@login_required
def api_templates_create():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    body = data.get("body", "").strip()
    if not title or not body:
        return jsonify({"error": "title and body required"}), 400
    tpl = database.create_template(title, body)
    return jsonify(tpl)


@app.put("/api/templates/<int:tpl_id>")
@login_required
def api_templates_update(tpl_id):
    data = request.get_json(silent=True) or {}
    database.update_template(tpl_id, title=data.get("title", ""), body=data.get("body", ""))
    return jsonify({"ok": True})


@app.delete("/api/templates/<int:tpl_id>")
@login_required
def api_templates_delete(tpl_id):
    database.delete_template(tpl_id)
    return jsonify({"ok": True})


# ── Tasks ─────────────────────────────────────────────────────────────────────

@app.get("/api/tasks")
@login_required
def api_tasks_list():
    contact_id = request.args.get("contact_id", type=int)
    return jsonify(database.list_tasks(contact_id=contact_id))


@app.post("/api/tasks")
@login_required
def api_tasks_create():
    data = request.get_json(silent=True) or {}
    contact_id = data.get("contact_id")
    title = data.get("title", "").strip()
    if not contact_id or not title:
        return jsonify({"error": "contact_id and title required"}), 400
    task = database.create_task(contact_id, title, data.get("description", ""), data.get("due_date", ""))
    return jsonify(task)


@app.put("/api/tasks/<int:task_id>")
@login_required
def api_tasks_update(task_id):
    data = request.get_json(silent=True) or {}
    database.update_task(task_id, **data)
    return jsonify({"ok": True})


@app.delete("/api/tasks/<int:task_id>")
@login_required
def api_tasks_delete(task_id):
    database.delete_task(task_id)
    return jsonify({"ok": True})


# ── Search ────────────────────────────────────────────────────────────────────

@app.get("/api/search")
@login_required
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    return jsonify(database.search_messages(q))


# ── Knowledge (RAG via Supabase) ─────────────────────────────────────────────

@app.get("/api/knowledge")
@login_required
def api_knowledge_list():
    return jsonify(knowledge_rag.list_files_with_status())


@app.get("/api/knowledge/descriptions")
@login_required
def api_knowledge_descriptions():
    return jsonify(knowledge_rag.get_file_descriptions())


@app.get("/api/knowledge/<filename>")
@login_required
def api_knowledge_get(filename):
    file_data = knowledge_rag.get_file(filename)
    if not file_data:
        return jsonify({"error": "Arquivo nao encontrado"}), 404
    return jsonify(file_data)

@app.post("/api/knowledge")
@login_required
def api_knowledge_create():
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "").strip()
    content = data.get("content", "")
    description = data.get("description", "").strip()
    skip_embed = data.get("skip_embed", True)
    if not filename:
        return jsonify({"error": "filename obrigatorio"}), 400
    if not filename.endswith(('.md', '.txt')):
        return jsonify({"error": "Extensao invalida (.md ou .txt)"}), 400
    existing = knowledge_rag.get_file(filename)
    if existing:
        return jsonify({"error": "Arquivo ja existe"}), 409
    try:
        knowledge_rag.save_knowledge_raw(filename, content, description=description)
    except knowledge_rag.ConteudoCorrompido as e:
        print(f"[knowledge] RECUSADO {filename}: {e}")
        return jsonify({"error": f"Conteudo recusado - {e}"}), 400
    print(f"[knowledge] criado: {filename}")
    return jsonify({"ok": True, "filename": filename})


@app.put("/api/knowledge/<filename>")
@login_required
def api_knowledge_update(filename):
    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    description = data.get("description", "").strip()
    try:
        mudou = knowledge_rag.save_knowledge_raw(filename, content, description=description)
    except knowledge_rag.ConteudoCorrompido as e:
        # Barra aqui: salvar o texto remontado por cima do original foi o que
        # destruiu o prompt operacional uma vez. O arquivo local tambem nao e
        # tocado, entao nada se perde.
        print(f"[knowledge] RECUSADO {filename}: {e}")
        return jsonify({"error": f"Conteudo recusado - {e}"}), 400

    if not mudou:
        print(f"[knowledge] salvo sem mudanca no texto: {filename}")
        return jsonify({"ok": True, "unchanged": True})

    # A base oficial tambem vive no repositorio (knowledge/): editar pelo
    # painel atualiza o arquivo, para o proximo deploy nao voltar ao texto velho.
    if filename == BASE_CONHECIMENTO_NOME:
        try:
            BASE_CONHECIMENTO_PATH.write_text(content.strip() + "\n", encoding="utf-8")
            print(f"[knowledge] arquivo local salvo: {BASE_CONHECIMENTO_PATH}")
        except Exception as e:
            print(f"[knowledge] aviso: nao foi possivel salvar arquivo local: {e}")

    print(f"[knowledge] salvo: {filename}")
    return jsonify({"ok": True})


@app.delete("/api/knowledge/<filename>")
@login_required
def api_knowledge_delete(filename):
    existing = knowledge_rag.get_file(filename)
    if not existing:
        return jsonify({"error": "Arquivo nao encontrado"}), 404
    knowledge_rag.delete_file(filename)
    print(f"[knowledge] deletado: {filename}")
    return jsonify({"ok": True})

_EXTENSOES_KNOWLEDGE = ('.md', '.txt', '.docx', '.pdf')


@app.post("/api/knowledge/upload")
@login_required
def api_knowledge_upload():
    """Upload de múltiplos arquivos (multipart). Aceita .md, .txt, .docx e .pdf."""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400

    saved = []
    errors = []
    for f in files:
        filename = f.filename or ""
        if not filename:
            continue
        lower = filename.lower()
        if not lower.endswith(_EXTENSOES_KNOWLEDGE):
            errors.append({"filename": filename, "error": "Extensao invalida (.md, .txt, .docx ou .pdf)"})
            continue
        existing = knowledge_rag.get_file(filename)
        if existing:
            errors.append({"filename": filename, "error": "Arquivo ja existe"})
            continue
        try:
            content = documentos.extrair_texto(filename, f.read())
            if not content or not content.strip():
                errors.append({"filename": filename, "error": "Arquivo vazio ou nao parseado"})
                continue
            knowledge_rag.save_knowledge_raw(filename, content)
            saved.append(filename)
        except Exception as e:
            errors.append({"filename": filename, "error": str(e)})

    print(f"[knowledge] upload: {len(saved)} salvos, {len(errors)} erros")
    return jsonify({"ok": True, "saved": saved, "errors": errors})


@app.post("/api/knowledge/reload")
@login_required
def api_knowledge_reload():
    """Recarrega o prompt da secretaria e os caches do knowledge."""
    knowledge_rag.invalidate_knowledge_caches()
    prompt = recarregar_prompt()
    print(f"[knowledge] recarregado: prompt={len(prompt)} chars")
    return jsonify({"ok": True, "prompt_chars": len(prompt)})


@app.get("/api/knowledge/health")
@login_required
def api_knowledge_health():
    """Diagnostico da base: o que o agente realmente le antes de responder."""
    import knowledge_repair

    arquivos = []
    for item in knowledge_rag.list_files_with_status():
        filename = item["filename"]
        documento = database.get_knowledge_document(filename)
        conteudo = documento or knowledge_rag.get_file_content(filename)
        arquivos.append({
            "filename": filename,
            "chunks": item.get("chunks", 0),
            "status": item.get("status", ""),
            "chars": len(conteudo),
            "tem_documento_original": bool(documento),
            "texto_duplicado": knowledge_repair.looks_corrupted(conteudo),
        })

    problemas = []
    if not any(a["filename"] == BASE_CONHECIMENTO_NOME for a in arquivos):
        problemas.append(f"{BASE_CONHECIMENTO_NOME} nao esta no knowledge - rode ingest_knowledge.py")
    for a in arquivos:
        if a["texto_duplicado"]:
            problemas.append(f"{a['filename']}: texto com trechos duplicados")
        if a["status"] != "indexed":
            problemas.append(f"{a['filename']}: status '{a['status']}' (sem embeddings - clique em Gerar Embeddings)")

    return jsonify({
        "ok": not problemas,
        "arquivos": arquivos,
        "prompt_chars": len(_get_current_system_prompt()),
        "problemas": problemas,
    })


@app.get("/api/knowledge/prompt")
@login_required
def api_knowledge_prompt_get():
    """Prompt da secretaria (prompts/secretaria.md)."""
    return jsonify({"content": _get_current_system_prompt(), "filename": PROMPT_PATH.name})


@app.put("/api/knowledge/prompt")
@login_required
def api_knowledge_prompt_put():
    """Salva o prompt da secretaria em disco e recarrega."""
    data = request.get_json(silent=True) or {}
    content = str(data.get("content", "")).strip()
    if not content:
        return jsonify({"error": "Prompt vazio"}), 400
    PROMPT_PATH.write_text(content + "\n", encoding="utf-8")
    recarregar_prompt()
    print(f"[knowledge] prompt da secretaria salvo ({len(content)} chars)")
    return jsonify({"ok": True})

@app.post("/api/knowledge/embed-all")
@login_required
def api_knowledge_embed_all():
    """Gera embeddings para todos os arquivos pendentes."""
    result = knowledge_rag.embed_pending_files()
    print(f"[knowledge] embed-all: {result}")
    return jsonify(result)


@app.post("/api/knowledge/clear-embeddings")
@login_required
def api_knowledge_clear_embeddings():
    """Remove todos os embeddings, mantém conteúdo, marca como pending."""
    count = knowledge_rag.clear_all_embeddings()
    return jsonify({"ok": True, "cleared": count})


@app.delete("/api/knowledge/all")
@login_required
def api_knowledge_delete_all():
    """Deleta todo o knowledge (chunks + metadados)."""
    count = knowledge_rag.delete_all()
    return jsonify({"ok": True, "deleted": count})

# ── WhatsApp Cloud API (Meta) ────────────────────────────────────────────────

@app.get("/api/whatsapp/status")
@login_required
def api_whatsapp_status():
    """Status do numero: quality rating, display name, etc."""
    problem = meta.config_problem()
    if problem:
        return jsonify({"error": problem}), 400
    r = get_phone_info()
    if not r.get("ok"):
        return jsonify({"error": r.get("error", "Erro ao consultar status")}), 500
    return jsonify(r.get("data", {}))


@app.get("/api/whatsapp/templates")
@login_required
def api_whatsapp_templates():
    """Lista templates aprovados na WABA."""
    problem = meta.config_problem()
    if problem:
        return jsonify({"error": problem}), 400
    r = list_templates()
    if not r.get("ok"):
        return jsonify({"error": r.get("error", "Erro ao listar templates")}), 500
    return jsonify(r.get("data", {}))


@app.get("/api/whatsapp/templates/<template_id>")
@login_required
def api_whatsapp_template_detail(template_id):
    """Detalhe de um template."""
    problem = meta.config_problem()
    if problem:
        return jsonify({"error": problem}), 400
    r = get_template(template_id)
    if not r.get("ok"):
        return jsonify({"error": r.get("error", "Template nao encontrado")}), 404
    return jsonify(r.get("data", {}))


@app.delete("/api/whatsapp/templates/<template_name>")
@login_required
def api_whatsapp_template_delete(template_name):
    """Deleta um template da WABA."""
    problem = meta.config_problem()
    if problem:
        return jsonify({"error": problem}), 400
    r = delete_template(template_name)
    if not r.get("ok"):
        return jsonify({"error": r.get("error", "Erro ao deletar template")}), 500
    return jsonify({"ok": True})


@app.post("/api/whatsapp/templates")
@login_required
def api_whatsapp_template_create():
    """Cria um template na WABA."""
    problem = meta.config_problem()
    if problem:
        return jsonify({"error": problem}), 400
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    category = data.get("category", "UTILITY").strip()
    language = data.get("language", "pt_BR").strip()
    body = data.get("body", "").strip()
    header_text = data.get("header_text", "").strip()
    if not name or not body:
        return jsonify({"error": "name e body sao obrigatorios"}), 400
    r = create_template(name, category, language, body, header_text=header_text)
    if not r.get("ok"):
        return jsonify({"error": r.get("error", "Erro ao criar template")}), 500
    return jsonify({"ok": True, "data": r.get("data", {})})


@app.get("/api/whatsapp/profile")
@login_required
def api_whatsapp_profile():
    """Business profile do numero."""
    problem = meta.config_problem()
    if problem:
        return jsonify({"error": problem}), 400
    r = get_business_profile()
    if not r.get("ok"):
        return jsonify({"error": r.get("error", "Erro ao consultar profile")}), 500
    return jsonify(r.get("data", {}))


@app.post("/api/whatsapp/profile")
@login_required
def api_whatsapp_profile_update():
    """Atualiza business profile."""
    problem = meta.config_problem()
    if problem:
        return jsonify({"error": problem}), 400
    data = request.get_json(silent=True) or {}
    allowed = ("about", "address", "description", "email", "websites", "vertical")
    kwargs = {k: data[k] for k in allowed if k in data}
    if not kwargs:
        return jsonify({"error": "nenhum campo para atualizar"}), 400
    r = update_business_profile(**kwargs)
    if not r.get("ok"):
        return jsonify({"error": r.get("error", "Erro ao atualizar profile")}), 500
    return jsonify({"ok": True})


@app.post("/api/whatsapp/send-template")
@login_required
def api_whatsapp_send_template():
    """Envia uma template message para um numero."""
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    template_name = data.get("template_name", "").strip()
    language = data.get("language", "pt_BR")
    body_params = data.get("body_params")
    header_params = data.get("header_params")
    if not phone or not template_name:
        return jsonify({"error": "phone and template_name required"}), 400
    from meta import send_template
    r = send_template(phone, template_name, language, body_params, header_params)
    if not r.get("ok"):
        return jsonify({"error": r.get("error", "Erro ao enviar template")}), (r.get("status") or 500)
    return jsonify({"ok": True, "data": r.get("data", {})})


@app.post("/api/whatsapp/send-interactive")
@login_required
def api_whatsapp_send_interactive():
    """Envia mensagem interativa (botoes ou lista)."""
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    msg_type = data.get("type", "button")
    if not phone:
        return jsonify({"error": "phone required"}), 400

    if msg_type == "list":
        from meta import send_interactive_list
        r = send_interactive_list(
            phone,
            header_text=data.get("header", ""),
            body_text=data.get("body", ""),
            button_text=data.get("button_text", "Opcoes"),
            sections=data.get("sections", []),
        )
    elif msg_type == "button":
        from meta import send_interactive_buttons
        r = send_interactive_buttons(
            phone,
            body_text=data.get("body", ""),
            buttons=data.get("buttons", []),
            header_text=data.get("header", ""),
            footer_text=data.get("footer", ""),
        )
    else:
        return jsonify({"error": f"tipo interativo invalido: {msg_type}"}), 400

    if not r.get("ok"):
        return jsonify({"error": r.get("error", "Erro ao enviar interativo")}), (r.get("status") or 500)
    return jsonify({"ok": True, "data": r.get("data", {})})


@app.post("/api/whatsapp/upload-media")
@login_required
def api_whatsapp_upload_media():
    """Upload de midia para o servidor Meta (retorna media_id)."""
    problem = meta.config_problem()
    if problem:
        return jsonify({"error": problem}), 400
    if "file" not in request.files:
        return jsonify({"error": "file required"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "filename required"}), 400
    import mimetypes
    mime = mimetypes.guess_type(f.filename)[0] or "application/octet-stream"
    file_bytes = f.read()
    from meta import upload_media_bytes
    r = upload_media_bytes(file_bytes, mime, f.filename)
    if not r.get("ok"):
        return jsonify({"error": r.get("error", "Erro ao upload")}), (r.get("status") or 500)
    data = r.get("data", {})
    return jsonify({"ok": True, "media_id": data.get("id", ""), "data": data})


# ── WhatsApp — Conexao e Configuracao (Datafy) ──────────────────────────────

_ENV_KEYS = [
    ("DATAFY_TOKEN", "Token Datafy", True),
    ("DATAFY_PHONE_NUMBER_ID", "Phone Number ID", False),
    ("DATAFY_WABA_ID", "WABA ID", False),
    ("DATAFY_WEBHOOK_SECRET", "Webhook Secret", True),
    ("WEBHOOK_URL", "URL Webhook", False),
    ("OPENAI_API_KEY", "OpenAI API Key", True),
    ("OPENAI_MODEL", "Modelo OpenAI", False),
    ("OPENAI_TEMPERATURE", "Temperatura (0.0 a 2.0)", False),
    ("BUFFER_SECONDS", "Buffer (segundos)", False),
    ("MAX_HISTORY", "Max Historico", False),
    ("SYSTEM_PROMPT", "System Prompt", False),
]


def _mask_value(val: str, is_secret: bool) -> str:
    if not is_secret or not val or len(val) <= 8:
        return val
    return "*" * (len(val) - 4) + val[-4:]


def _read_env_file() -> dict[str, str]:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    result = {}
    if not os.path.isfile(env_path):
        return result
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip()
    return result


def _write_env_file(updates: dict[str, str]) -> None:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    lines = []
    existing_keys = set()
    if os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k = stripped.split("=", 1)[0].strip()
                    existing_keys.add(k)
                    if k in updates:
                        lines.append(f"{k}={updates[k]}\n")
                    else:
                        lines.append(line)
                else:
                    lines.append(line)
    for k, v in updates.items():
        if k not in existing_keys:
            lines.append(f"{k}={v}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


@app.get("/api/whatsapp/connection")
@login_required
def api_whatsapp_connection():
    """Testa conexao com a Datafy API e retorna dados da instância."""
    problem = meta.config_problem()
    if problem:
        return jsonify({"ok": False, "error": problem})

    r = meta.get_phone_info()
    if not r.get("ok"):
        return jsonify({
            "ok": False,
            "error": r.get("error", "Erro ao conectar com Datafy"),
            "phone_number_id": get_phone_id(),
            "waba_id": get_waba_id(),
        })

    d = r.get("data", {})
    return jsonify({
        "ok": True,
        "phone_number_id": get_phone_id(),
        "waba_id": get_waba_id(),
        "display_name": d.get("verified_name", ""),
        "display_phone": d.get("display_phone_number", ""),
        "quality_rating": d.get("quality_rating", ""),
        "name_status": d.get("name_status", ""),
    })


@app.get("/api/whatsapp/config")
@login_required
def api_whatsapp_config_get():
    """Retorna valores atuais do .env (secrets mascarados)."""
    env = _read_env_file()
    result = {}
    for key, label, is_secret in _ENV_KEYS:
        raw = env.get(key, os.getenv(key, ""))
        result[key] = {"label": label, "value": _mask_value(raw, is_secret), "is_secret": is_secret}
    return jsonify(result)


@app.post("/api/whatsapp/config")
@login_required
def api_whatsapp_config_post():
    """Salva novos valores no .env e recarrega configuracao."""
    data = request.get_json(silent=True) or {}
    updates = {}
    for key, _, _ in _ENV_KEYS:
        if key in data:
            val = str(data[key]).strip()
            if val.startswith("*" * 4):
                continue
            updates[key] = val
    if not updates:
        return jsonify({"ok": False, "error": "Nenhum campo para atualizar"}), 400
    try:
        _write_env_file(updates)
        os.environ.update(updates)
        meta.reload_config()
        print(f"[config] .env atualizado: {list(updates.keys())}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── CRM API ─────────────────────────────────────────────────────────────────

@app.get("/api/crm/dashboard")
@login_required
def api_crm_dashboard():
    return jsonify(database.get_crm_dashboard_stats())


@app.get("/api/crm/contacts")
@login_required
def api_crm_contacts_list():
    status = request.args.get("status", "")
    tag_id = int(request.args.get("tag_id", "0"))
    days_without = int(request.args.get("days_without", "0"))
    has_follow_up = request.args.get("has_follow_up", "")
    search = request.args.get("search", "")
    limit = min(int(request.args.get("limit", "100")), 500)
    offset = max(int(request.args.get("offset", "0")), 0)
    contacts = database.list_contacts_crm(
        status=status, tag_id=tag_id, days_without=days_without,
        has_follow_up=has_follow_up, search=search, limit=limit, offset=offset,
    )
    return jsonify(contacts)


@app.get("/api/crm/contacts/<int:contact_id>")
@login_required
def api_crm_contact_detail(contact_id):
    detail = database.get_crm_contact_detail(contact_id)
    if not detail:
        return jsonify({"error": "not found"}), 404
    return jsonify(detail)


@app.put("/api/crm/contacts/<int:contact_id>/status")
@login_required
def api_crm_contact_update_status(contact_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status", "")
    if status not in ("novo", "em_atendimento", "cliente", "inativo", "nao_interessado", ""):
        return jsonify({"error": "invalid status"}), 400
    database.update_contact(contact_id, crm_status=status)
    return jsonify({"ok": True})


@app.put("/api/crm/contacts/<int:contact_id>/notes")
@login_required
def api_crm_contact_update_notes(contact_id):
    data = request.get_json(silent=True) or {}
    notes = data.get("notes", "")
    database.update_contact(contact_id, notes=notes)
    return jsonify({"ok": True})


@app.get("/api/crm/automations")
@login_required
def api_crm_automations_list():
    return jsonify(database.list_automations())


def _exige_template_meta(days, hours, use_meta_template, meta_template_name) -> str:
    """Erro quando o prazo passa das 24h e nao ha template aprovado.

    Fora da janela de 24 horas o WhatsApp so entrega template aprovado: uma
    automacao de dias com mensagem de texto falha em TODO envio e o usuario so
    descobre pelo log, dias depois. Melhor recusar na hora de salvar.
    """
    try:
        total_horas = int(days or 0) * 24 + int(hours or 0)
    except (TypeError, ValueError):
        return ""
    if total_horas < 24:
        return ""
    if int(use_meta_template or 0) and str(meta_template_name or "").strip():
        return ""
    return (
        f"Esta automacao dispara {total_horas}h depois da ultima interacao, "
        "fora da janela de 24 horas do WhatsApp. Nesse prazo a Meta so entrega "
        "template aprovado: marque 'Usar template aprovado pela Meta' e escolha "
        "um template, ou reduza o prazo para menos de 24 horas."
    )


@app.post("/api/crm/automations")
@login_required
def api_crm_automations_create():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    problema = _exige_template_meta(
        data.get("days", 0), data.get("hours", 0),
        data.get("use_meta_template", 0), data.get("meta_template_name", ""),
    )
    if problema:
        return jsonify({"error": problema}), 400
    auto = database.create_automation(
        name=name,
        days=int(data.get("days", 0)),
        hours=int(data.get("hours", 0)),
        message_template=data.get("message_template", ""),
        use_meta_template=int(data.get("use_meta_template", 0)),
        meta_template_name=data.get("meta_template_name", ""),
        meta_template_language=data.get("meta_template_language", "pt_BR"),
        action_tag_add=data.get("action_tag_add", ""),
        action_tag_remove=data.get("action_tag_remove", ""),
        action_status_change=data.get("action_status_change", ""),
        is_active=int(data.get("is_active", 1)),
        send_window_start=data.get("send_window_start", "08:00"),
        send_window_end=data.get("send_window_end", "18:00"),
    )
    return jsonify(auto)


@app.put("/api/crm/automations/<int:auto_id>")
@login_required
def api_crm_automations_update(auto_id):
    data = request.get_json(silent=True) or {}
    # Valida o estado FINAL: o PUT pode mandar so alguns campos, e o resto
    # continua valendo do que ja esta salvo.
    atual = database.get_automation(auto_id) or {}
    final = {**atual, **data}
    problema = _exige_template_meta(
        final.get("days", 0), final.get("hours", 0),
        final.get("use_meta_template", 0), final.get("meta_template_name", ""),
    )
    if problema:
        return jsonify({"error": problema}), 400
    database.update_automation(auto_id, **data)
    return jsonify({"ok": True})


@app.delete("/api/crm/automations/<int:auto_id>")
@login_required
def api_crm_automations_delete(auto_id):
    database.delete_automation(auto_id)
    return jsonify({"ok": True})


@app.put("/api/crm/automations/<int:auto_id>/toggle")
@login_required
def api_crm_automations_toggle(auto_id):
    auto = database.get_automation(auto_id)
    if not auto:
        return jsonify({"error": "not found"}), 404
    new_val = 0 if auto["is_active"] else 1
    database.update_automation(auto_id, is_active=new_val)
    return jsonify({"ok": True, "is_active": new_val})


@app.get("/api/crm/follow-ups")
@login_required
def api_crm_follow_ups_list():
    status = request.args.get("status", "")
    limit = min(int(request.args.get("limit", "100")), 500)
    offset = max(int(request.args.get("offset", "0")), 0)
    return jsonify(database.list_follow_ups(status=status, limit=limit, offset=offset))


@app.get("/api/crm/follow-ups/pending")
@login_required
def api_crm_follow_ups_pending():
    return jsonify(database.get_pending_follow_ups())


@app.get("/api/crm/logs")
@login_required
def api_crm_logs_list():
    limit = min(int(request.args.get("limit", "100")), 500)
    offset = max(int(request.args.get("offset", "0")), 0)
    return jsonify(database.list_crm_logs(limit=limit, offset=offset))

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
