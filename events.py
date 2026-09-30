"""
events.py — SSE (Server-Sent Events) pub/sub thread-safe.
Permite push de eventos do servidor para o frontend do painel.
"""

import json
import queue
import threading
from typing import Any

_lock = threading.Lock()
_subscribers: list[queue.Queue] = []


def subscribe() -> queue.Queue:
    """Registra um novo subscriber e retorna sua fila."""
    q: queue.Queue = queue.Queue()
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    """Remove um subscriber."""
    with _lock:
        if q in _subscribers:
            _subscribers.remove(q)


def emit(event: str, data: Any) -> None:
    """Envia um evento para todos os subscribers conectados."""
    payload = json.dumps({"event": event, "data": data}, default=str, ensure_ascii=False)
    with _lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)
