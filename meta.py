"""
meta.py — Cliente da API própria de WhatsApp (AutoZap), camada REST sobre a Cloud API da Meta.
Envio de mensagens, mídia, indicadores e modelos. Mantém a forma de retorno de antes
({"ok", "status", "data"}, com "data" no formato da Meta), então o resto do app não muda.
"""

import os
import io
import requests

_BASE = os.getenv("WHATSAPI_URL", "https://eduwhatsapi-elpj.onrender.com/api/v1").rstrip("/")
_TOKEN = os.getenv("WHATSAPI_KEY", "")
# O phone_number_id é o mesmo número da Meta: aceita o nome antigo da variável.
_PHONE_ID = os.getenv("WHATSAPI_PHONE_NUMBER_ID") or os.getenv("DATAFY_PHONE_NUMBER_ID", "")

# A API não consulta modelo por id.
_NAO_SUPORTADO = {"ok": False, "status": 501,
                  "error": "Não disponível na API de WhatsApp; use o painel da API ou o WhatsApp Manager."}

# Mídia recebida: a API só entrega o arquivo (sem URL), então o GET que descobre o tipo
# já traz os bytes; download_media_bytes os entrega e esquece. Pequeno e de uso único.
_midia_baixada: dict[str, bytes] = {}
_MIDIA_MAX = 20


def _headers(content_type="application/json"):
    h = {"Authorization": f"Bearer {_TOKEN}"}
    if content_type:
        h["Content-Type"] = content_type
    return h


def _erro(status: int, data) -> str:
    """Envelope de erro da API: {"error": {"code", "message", "meta_error": {...}}}."""
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        texto = f"{err.get('code', '')}: {err.get('message', '')}".strip(": ")
        meta_err = err.get("meta_error")
        if isinstance(meta_err, dict) and meta_err.get("message"):
            texto += f" ({meta_err['message']})"
        return f"HTTP {status}: {texto}"[:300]
    return f"HTTP {status}: {str(data)[:300]}"


def _desembrulha(data):
    """{"data": {..., "meta_response": {...}}} -> a resposta da Meta, como antes."""
    inner = data.get("data") if isinstance(data, dict) else None
    if isinstance(inner, dict):
        return inner.get("meta_response") or inner
    return data


def _request(method, path, body=None, params=None, extra_headers=None):
    url = path if path.startswith("http") else f"{_BASE}{path}"
    h = _headers()
    if extra_headers:
        h.update(extra_headers)
    try:
        r = requests.request(method, url, json=body, params=params,
                             headers=h, timeout=30)
        try:
            data = r.json()
        except Exception:
            data = r.text
        print(f"[meta] {method} {path[:60]} -> {r.status_code} | {str(data)[:300]}", flush=True)
        if r.ok:
            return {"ok": True, "status": r.status_code, "data": _desembrulha(data)}
        return {"ok": False, "status": r.status_code, "error": _erro(r.status_code, data)}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "status": 0, "error": f"Connection error: {url}"}
    except requests.exceptions.Timeout:
        return {"ok": False, "status": 0, "error": f"Timeout: {url}"}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}


def _send(payload):
    # A API acrescenta messaging_product por conta própria.
    payload = {k: v for k, v in payload.items() if k not in ("messaging_product", "recipient_type")}
    return _request("POST", f"/whatsapp/{_PHONE_ID}/messages", body=payload)


# ── Envio de mensagens ───────────────────────────────────────────────────────


def send_text(number: str, text: str) -> dict:
    if not number:
        return {"ok": False, "status": 400, "error": "Numero vazio/invalido."}
    return _send({"to": number, "type": "text", "text": {"body": text}})


def send_image(number: str, media_id: str, caption: str = "") -> dict:
    if not number or not media_id:
        return {"ok": False, "status": 400, "error": "number e media_id requeridos."}
    img = {"id": media_id}
    if caption:
        img["caption"] = caption
    return _send({"to": number, "type": "image", "image": img})


def send_audio(number: str, media_id: str) -> dict:
    if not number or not media_id:
        return {"ok": False, "status": 400, "error": "number e media_id requeridos."}
    return _send({"to": number, "type": "audio", "audio": {"id": media_id}})


def send_document(number: str, media_id: str, filename: str = "", caption: str = "") -> dict:
    if not number or not media_id:
        return {"ok": False, "status": 400, "error": "number e media_id requeridos."}
    doc = {"id": media_id}
    if filename:
        doc["filename"] = filename
    if caption:
        doc["caption"] = caption
    return _send({"to": number, "type": "document", "document": doc})


def send_video(number: str, media_id: str, caption: str = "") -> dict:
    if not number or not media_id:
        return {"ok": False, "status": 400, "error": "number e media_id requeridos."}
    vid = {"id": media_id}
    if caption:
        vid["caption"] = caption
    return _send({"to": number, "type": "video", "video": vid})


def send_template(number: str, template_name: str, language_code: str = "pt_BR",
                  body_params: list[str] | None = None,
                  header_params: list[dict] | None = None) -> dict:
    if not number or not template_name:
        return {"ok": False, "status": 400, "error": "number e template_name requeridos."}
    components = []
    if header_params:
        components.append({"type": "header", "parameters": header_params})
    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": v} for v in body_params],
        })
    tpl = {"name": template_name, "language": {"code": language_code}}
    if components:
        tpl["components"] = components
    return _send({"to": number, "type": "template", "template": tpl})


def send_interactive_list(number: str, header_text: str, body_text: str,
                          button_text: str, sections: list[dict]) -> dict:
    if not number:
        return {"ok": False, "status": 400, "error": "number requerido."}
    interactive = {
        "type": "list",
        "body": {"text": body_text},
        "action": {"button": button_text, "sections": sections},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    return _send({"to": number, "type": "interactive", "interactive": interactive})


def send_interactive_buttons(number: str, body_text: str,
                             buttons: list[dict], header_text: str = "",
                             footer_text: str = "") -> dict:
    if not number:
        return {"ok": False, "status": 400, "error": "number requerido."}
    interactive = {
        "type": "button",
        "body": {"text": body_text},
        "action": {"buttons": buttons},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive["footer"] = {"text": footer_text}
    return _send({"to": number, "type": "interactive", "interactive": interactive})


# ── Indicadores e leitura ────────────────────────────────────────────────────


def mark_read(message_id: str) -> dict:
    if not message_id:
        return {"ok": False, "status": 400, "error": "message_id vazio."}
    return _request("POST", f"/whatsapp/{_PHONE_ID}/messages/read", body={"message_id": message_id})


def send_typing(message_id: str) -> dict:
    if not message_id:
        return {"ok": False, "status": 400, "error": "message_id vazio."}
    return _request("POST", f"/whatsapp/{_PHONE_ID}/messages/read",
                    body={"message_id": message_id, "typing": True})


# ── Mídia (upload/download) ─────────────────────────────────────────────────


def upload_media_bytes(file_bytes: bytes, mime_type: str, filename: str = "file") -> dict:
    url = f"{_BASE}/whatsapp/{_PHONE_ID}/media"
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {_TOKEN}"},
                          files={"file": (filename, io.BytesIO(file_bytes), mime_type)},
                          timeout=60)
        try:
            data = r.json()
        except Exception:
            data = r.text
        print(f"[meta] POST /media upload_bytes -> {r.status_code} | {str(data)[:200]}", flush=True)
        if r.ok:
            return {"ok": True, "status": r.status_code, "data": _desembrulha(data)}
        return {"ok": False, "status": r.status_code, "error": _erro(r.status_code, data)}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}


def get_webhook_media_url(media_id: str) -> dict:
    """Mídia recebida: a API entrega o arquivo em /media/{id}, sem URL temporária.

    Uma chamada só: o tipo vem no Content-Type e os bytes ficam guardados para o
    download_media_bytes seguinte.
    """
    url = f"{_BASE}/whatsapp/{_PHONE_ID}/media/{media_id}"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {_TOKEN}"}, timeout=60)
        if not r.ok:
            return {"ok": False, "status": r.status_code, "error": f"HTTP {r.status_code}"}
        if len(_midia_baixada) >= _MIDIA_MAX:
            _midia_baixada.pop(next(iter(_midia_baixada)))
        _midia_baixada[url] = r.content
        mime = r.headers.get("Content-Type", "application/octet-stream").split(";")[0].strip()
        return {"ok": True, "status": 200, "data": {"url": url, "mime_type": mime}}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}


get_media_url = get_webhook_media_url


def download_media_bytes(media_url: str) -> bytes:
    guardado = _midia_baixada.pop(media_url, b"")
    if guardado:
        return guardado
    try:
        r = requests.get(media_url, headers={"Authorization": f"Bearer {_TOKEN}"}, timeout=60)
        if r.ok:
            return r.content
        print(f"[meta] download_media falhou: {r.status_code}", flush=True)
        return b""
    except Exception as e:
        print(f"[meta] download_media erro: {e}", flush=True)
        return b""


# ── Modelos ──────────────────────────────────────────────────────────────────


def list_templates() -> dict:
    return _request("GET", f"/whatsapp/{_PHONE_ID}/templates")


def get_template(template_id: str) -> dict:
    return dict(_NAO_SUPORTADO)


def delete_template(template_name: str) -> dict:
    return _request("DELETE", f"/whatsapp/{_PHONE_ID}/templates/{template_name}")


def create_template(name: str, category: str, language: str, body: str,
                    header_text: str = "", buttons: list | None = None) -> dict:
    """category: MARKETING | UTILITY | AUTHENTICATION; body usa {{1}}, {{2}} para variáveis."""
    components = []
    if header_text:
        components.append({"type": "HEADER", "format": "TEXT", "text": header_text})
    if body:
        components.append({"type": "BODY", "text": body})
    if buttons:
        components.append({"type": "BUTTONS", "buttons": buttons})
    return _request("POST", f"/whatsapp/{_PHONE_ID}/templates",
                    body={"name": name, "category": category.upper(),
                          "language": language, "components": components})


# ── Número / perfil ──────────────────────────────────────────────────────────


def get_phone_info() -> dict:
    return _request("GET", f"/channels/{_PHONE_ID}")


def get_business_profile() -> dict:
    return _request("GET", f"/whatsapp/{_PHONE_ID}/business_profile")


def update_business_profile(**kwargs) -> dict:
    return _request("POST", f"/whatsapp/{_PHONE_ID}/business_profile", body=kwargs)


# ── Configuração ─────────────────────────────────────────────────────────────


def config_problem() -> str | None:
    if not _TOKEN or "cole_o" in _TOKEN.lower():
        return "WHATSAPI_KEY nao configurado no .env"
    if not _PHONE_ID or "cole_o" in _PHONE_ID.lower():
        return "WHATSAPI_PHONE_NUMBER_ID nao configurado no .env"
    return None


def reload_config() -> None:
    """Recarrega variaveis de ambiente nos modulos (apos salvar .env pelo painel)."""
    global _BASE, _PHONE_ID, _TOKEN
    from dotenv import load_dotenv
    load_dotenv(override=True)
    _BASE = os.getenv("WHATSAPI_URL", "https://eduwhatsapi-elpj.onrender.com/api/v1").rstrip("/")
    _PHONE_ID = os.getenv("WHATSAPI_PHONE_NUMBER_ID") or os.getenv("DATAFY_PHONE_NUMBER_ID", "")
    _TOKEN = os.getenv("WHATSAPI_KEY", "")


def get_phone_id() -> str:
    return _PHONE_ID


def get_waba_id() -> str:
    # A API não pede o WABA; o campo fica só por compatibilidade com o painel.
    return ""
