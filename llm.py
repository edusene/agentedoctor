"""
llm.py — Cliente OpenAI para geração de respostas.
Suporta function calling para busca seletiva de knowledge.
"""

import os
import json
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

_client = OpenAI(api_key=OPENAI_API_KEY)

# Temperatura zero: a secretaria so pode repetir o que esta na base oficial,
# nunca variar de redacao a ponto de inventar informacao clinica. Lida a cada
# chamada (e nao uma vez no import) para o painel poder mexer sem redeploy.
# Temperatura nao substitui trava: as respostas que nao podem oscilar estao em
# clinica.py e nem passam pelo modelo.
_TEMPERATURA_PADRAO = "0.0"

# Familias que so aceitam a temperatura default (gpt-5, o1, o3...). Mandar
# temperature para elas devolve 400 e derruba a resposta inteira.
_SEM_TEMPERATURA: set[str] = set()


def _temperatura() -> float:
    bruto = os.getenv("OPENAI_TEMPERATURE", _TEMPERATURA_PADRAO)
    try:
        return max(0.0, min(2.0, float(str(bruto).replace(",", "."))))
    except (TypeError, ValueError):
        print(f"[llm] OPENAI_TEMPERATURE invalida ({bruto!r}); usando {_TEMPERATURA_PADRAO}")
        return float(_TEMPERATURA_PADRAO)


# Consumo acumulado desde que o processo subiu. Existe porque ninguem sabia
# quanto custa um atendimento: a conta da OpenAI vinha fechada, sem dizer se
# o peso estava no prompt, no historico ou nas voltas de tool. Somado em
# _create, que e por onde passam TODAS as chamadas do arquivo - inclusive o
# retry sem tools.
#
# 'entrada' e o total que a OpenAI cobrou como prompt; 'cache' e a parte dele
# que veio do cache do prefixo, que custa um quarto do preco. Guardar os dois
# separados e o que permite ver se o cache esta pegando.
_CONSUMO = {"chamadas": 0, "entrada": 0, "cache": 0, "saida": 0}

# Precos por 1M de tokens (gpt-4.1-mini, tabela oficial de 26/09/2026).
PRECO_ENTRADA_USD = 0.40
PRECO_CACHE_USD = 0.10
PRECO_SAIDA_USD = 1.60


def _somar_consumo(response) -> None:
    """Acumula o usage de uma resposta. Nunca levanta: e contabilidade."""
    try:
        uso = getattr(response, "usage", None)
        if not uso:
            return
        detalhe = getattr(uso, "prompt_tokens_details", None)
        _CONSUMO["chamadas"] += 1
        _CONSUMO["entrada"] += int(getattr(uso, "prompt_tokens", 0) or 0)
        _CONSUMO["cache"] += int(getattr(detalhe, "cached_tokens", 0) or 0)
        _CONSUMO["saida"] += int(getattr(uso, "completion_tokens", 0) or 0)
    except Exception as e:
        print(f"[llm] WARN contagem de consumo falhou: {e}")


def consumo() -> dict:
    """Copia do acumulado, para quem quiser somar por conta propria."""
    return dict(_CONSUMO)


def zerar_consumo() -> None:
    for k in _CONSUMO:
        _CONSUMO[k] = 0


def custo(usd_brl: float = 5.18) -> dict:
    """O que o acumulado custou, em dolar e em real.

    A entrada cobrada tem duas faixas: o que veio do cache sai por um quarto
    do preco. Cobrar tudo a preco cheio superestimaria em quase 3x num
    prompt com prefixo fixo grande, como o nosso.
    """
    c = dict(_CONSUMO)
    entrada_cheia = max(0, c["entrada"] - c["cache"])
    usd = (entrada_cheia / 1e6 * PRECO_ENTRADA_USD
           + c["cache"] / 1e6 * PRECO_CACHE_USD
           + c["saida"] / 1e6 * PRECO_SAIDA_USD)
    return {
        **c,
        "entrada_cheia": entrada_cheia,
        "usd": round(usd, 6),
        "brl": round(usd * usd_brl, 4),
        "brl_por_chamada": round(usd * usd_brl / c["chamadas"], 4) if c["chamadas"] else 0.0,
    }

def _create(**kwargs):
    """chat.completions.create com temperatura, tolerante a modelo que a recusa."""
    modelo = kwargs.get("model", "")
    if modelo not in _SEM_TEMPERATURA:
        kwargs.setdefault("temperature", _temperatura())
    try:
        _r = _client.chat.completions.create(**kwargs)
        _somar_consumo(_r)
        return _r
    except Exception as e:
        if "temperature" not in str(e).lower() or "temperature" not in kwargs:
            raise
        # Modelo da familia de raciocinio: aceita so o default. Anota para nao
        # gastar uma chamada perdida a cada mensagem.
        print(f"[llm] modelo {modelo} nao aceita temperature; seguindo sem ela")
        _SEM_TEMPERATURA.add(modelo)
        kwargs.pop("temperature", None)
        _r = _client.chat.completions.create(**kwargs)
        _somar_consumo(_r)
        return _r


def _convert_history(history: list[dict]) -> list[dict]:
    """Converte histórico do formato interno para formato OpenAI.

    Formato interno: {"role": "user"|"assistant", "parts": [{"text": "..."}, ...]}
    Formato OpenAI:  {"role": "user"|"assistant", "content": "..." | [...]}
    """
    messages = []
    for msg in history:
        role = msg.get("role", "user")
        parts = msg.get("parts", [])

        # Verifica se tem conteúdo multimodal (inline_data / image_url)
        has_media = any(
            "inline_data" in p or "image_url" in p
            for p in parts
        )

        if has_media:
            # Formato multimodal OpenAI: content é uma lista
            content_parts = []
            for p in parts:
                if "text" in p:
                    content_parts.append({"type": "text", "text": p["text"]})
                elif "image_url" in p:
                    # Já está no formato OpenAI
                    content_parts.append(p)
                elif "inline_data" in p:
                    mime = p["inline_data"].get("mime_type", "")
                    data = p["inline_data"].get("data", "")
                    if mime.startswith("image/"):
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{data}",
                                "detail": "low",
                            },
                        })
                    elif mime == "application/pdf":
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{data}",
                            },
                        })
            if not content_parts:
                content_parts.append({"type": "text", "text": "[Midia nao processada]"})
            messages.append({"role": role, "content": content_parts})
        else:
            # Texto puro: concatena todos os parts de texto
            text = "\n".join(p.get("text", "") for p in parts if "text" in p)
            messages.append({"role": role, "content": text})

    return messages


def generate_reply(
    history: list[dict],
    system: str,
    tools: list | None = None,
    tool_handlers: dict | None = None,
) -> str:
    """Chama OpenAI com suporte a function calling.

    Se o modelo pedir uma tool, executa localmente e retorna o resultado
    para gerar a resposta final.
    """
    messages = [{"role": "system", "content": system}]
    messages.extend(_convert_history(history))

    kwargs = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "max_completion_tokens": 1024,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    response = _create(**kwargs)
    choice = response.choices[0]

    # Log de cache hits (prompt caching)
    if hasattr(response, 'usage') and response.usage:
        _cached = getattr(response.usage.prompt_tokens_details, 'cached_tokens', 0) if response.usage.prompt_tokens_details else 0
        _total = response.usage.prompt_tokens or 0
        if _total > 0:
            print(f"[llm] cache tokens: {_cached}/{_total} cached ({_cached*100//_total}% hit)")

    # Loop de tool calling: permite múltiplos rounds de tools
    max_tool_rounds = 5
    rounds = 0
    while (
        tools
        and tool_handlers
        and choice.finish_reason == "tool_calls"
        and choice.message.tool_calls
        and rounds < max_tool_rounds
    ):
        rounds += 1
        # Adiciona a mensagem do assistente (com as chamadas de tool) ao histórico
        messages.append(choice.message.model_dump())

        for tool_call in choice.message.tool_calls:
            fn_name = tool_call.function.name
            
            try:
                fn_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
            except Exception as e:
                print(f"[llm] erro ao parsear args da tool {fn_name}: {e}")
                fn_args = {}

            if fn_name in tool_handlers:
                try:
                    result = tool_handlers[fn_name](**fn_args)
                except Exception as e:
                    print(f"[llm] excecao ao executar tool {fn_name}: {e}")
                    result = f"Erro ao executar a tool {fn_name}: {e}. Verifique se os parametros enviados estao corretos e aderem ao schema."
            else:
                result = f"Função {fn_name} não encontrada"

            print(f"[llm] tool_call={fn_name} args={fn_args} result_len={len(str(result))} round={rounds}")

            # Adiciona resultado da tool ao histórico
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(result),
            })

        # Gera resposta final (ou próxima tool call) com o resultado da tool
        response = _create(
            model=OPENAI_MODEL,
            messages=messages,
            max_completion_tokens=1024,
            tools=tools,
            tool_choice="auto",
        )
        choice = response.choices[0]

        # Log de cache hits no tool calling loop
        if hasattr(response, 'usage') and response.usage:
            _cached = getattr(response.usage.prompt_tokens_details, 'cached_tokens', 0) if response.usage.prompt_tokens_details else 0
            _total = response.usage.prompt_tokens or 0
            if _total > 0:
                print(f"[llm] cache tokens (tool round {rounds}): {_cached}/{_total} cached ({_cached*100//_total}% hit)")

    text = (choice.message.content or "").strip()

    if not text:
        # O modelo terminou sem texto: estourou os rounds de tool, ou o limite
        # de tokens no meio de uma tool call. Sem isto o cliente recebe
        # silencio - nenhuma mensagem chega no WhatsApp. A segunda chamada vai
        # sem tools, obrigando uma resposta em prosa com o que ja foi apurado.
        print(f"[llm] resposta VAZIA (finish_reason={choice.finish_reason}); "
              f"refazendo sem tools")
        try:
            retry = _create(
                model=OPENAI_MODEL,
                messages=messages,
                max_completion_tokens=1024,
            )
            text = (retry.choices[0].message.content or "").strip()
        except Exception as e:
            print(f"[llm] ERRO na segunda tentativa: {e}")

    print(f"[llm] reply len={len(text)} temp={_temperatura()}")
    return text
