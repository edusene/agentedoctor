"""
buffer.py — Debounce buffer por usuario.
Cada mensagem nova reseta o timer; flush so ocorre apos BUFFER_SECONDS de silencio.
Com BUFFER_SECONDS=0 a resposta sai na hora, e o que o paciente mandar enquanto
ela e gerada vira um lote so, atendido logo depois.
"""

import threading
import time
from typing import Callable


class MessageBuffer:
    def __init__(self, wait_seconds: float, on_flush: Callable[[str, list[dict]], None]):
        self._wait = wait_seconds
        self._on_flush = on_flush
        self._lock = threading.Lock()
        # {user: {"items": [{"text": ..., "msg_id": ..., "wa_message_id": ..., "wa_media_id": ...}], "timer": Timer | None}}
        self._state: dict[str, dict] = {}
        # Um atendimento por vez para cada paciente: mensagem que chega enquanto
        # a resposta anterior ainda esta sendo enviada espera a vez, em vez de
        # ler e gravar a mesma ficha em paralelo.
        self._em_atendimento: dict[str, threading.Lock] = {}

    def add(self, user: str, text: str, msg_id: int | None = None,
            wa_message_id: str = "", wa_media_id: str = "",
            recebido_em: float = 0.0) -> None:
        with self._lock:
            if user not in self._state:
                self._state[user] = {"items": [], "timer": None}

            # recebido_em e o relogio do CLIENTE, nao o do servidor: quem mede
            # a espera dele e o instante em que a mensagem entrou no webhook,
            # nao o instante em que o debounce terminou. Sem isso a linha
            # [tempo] media so a segunda metade e escondia os 3,8s de webhook
            # que eram justamente o maior pedaco.
            self._state[user]["items"].append({
                "text": text, "msg_id": msg_id,
                "wa_message_id": wa_message_id, "wa_media_id": wa_media_id,
                "recebido_em": recebido_em or time.monotonic(),
            })

            # Cancela timer anterior e cria novo (debounce)
            timer = self._state[user]["timer"]
            if timer is not None:
                timer.cancel()

            new_timer = threading.Timer(self._wait, self._flush, args=[user])
            self._state[user]["timer"] = new_timer
            new_timer.start()

    def reagendar(self, user: str, items: list[dict], atraso: float) -> None:
        """Devolve o lote a fila e atende de novo daqui a `atraso` s (banco fora).

        O que chegar nesse meio tempo entra junto, depois do lote devolvido.
        """
        with self._lock:
            estado = self._state.setdefault(user, {"items": [], "timer": None})
            estado["items"] = items + estado["items"]
            if estado["timer"] is not None:
                estado["timer"].cancel()
            timer = threading.Timer(atraso, self._flush, args=[user])
            estado["timer"] = timer
            timer.start()

    def _flush(self, user: str) -> None:
        with self._lock:
            vez = self._em_atendimento.setdefault(user, threading.Lock())
        # Pega o lote so depois de ganhar a vez: o que chegou enquanto o
        # atendimento anterior rodava sai junto, em uma resposta. Os timers
        # dessas mensagens acham a fila vazia e voltam sem fazer nada.
        with vez:
            with self._lock:
                if user not in self._state:
                    return
                items = self._state[user]["items"]
                if not items:
                    return
                # Limpa estado antes de chamar o callback (evita race condition)
                self._state[user] = {"items": [], "timer": None}
            print(f"[buffer] flush user={user} msgs={len(items)}")
            self._on_flush(user, items)
