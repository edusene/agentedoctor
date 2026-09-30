"""
meta.py — Cliente Meta WhatsApp Cloud API (Graph API).
Envio de mensagens, templates, mídia, indicadores, business profile.
"""

import os
import io
import requests

_PHONE_ID = os.getenv("DATAFY_PHONE_NUMBER_ID", "")
_WABA_ID = os.getenv("DATAFY_WABA_ID", "")
_TOKEN = os.getenv("DATAFY_TOKEN", "")
_BASE = "https://cloud.datafyapi.com.br/v1"


def _headers(content_type="application/json"):
    h = {"Authorization": f"Bearer {_TOKEN}"}
    if content_type:
        h["Content-Type"] = content_type
    return h


def _request(method, url, body=None, params=None, extra_headers=None):
    h = _headers()
    if extra_headers:
        h.update(extra_headers)
    try:
        r = requests.request(method, url, json=body, params=params,
                             headers=h, timeout=30)
        data = None
        try:
            data = r.json()
        except Exception:
            data = r.text
        short = str(data)[:300]
        url_path = url.split("//", 1)[-1].split("/", 1)[-1][:60] if "//" in url else url[:60]
        print(f"[meta] {method} {url_path} -> {r.status_code} | {short}", flush=True)
        if r.ok:
            return {"ok": True, "status": r.status_code, "data": data}
        return {"ok": False, "status": r.status_code,
                "error": f"HTTP {r.status_code}: {str(data)[:300]}"}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "status": 0, "error": f"Connection error: {url}"}
    except requests.exceptions.Timeout:
        return {"ok": False, "status": 0, "error": f"Timeout: {url}"}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}


def _messages_url():
    return f"{_BASE}/{_PHONE_ID}/messages"


def _send(payload):
    return _request("POST", _messages_url(), body=payload)


# ── Envio de mensagens ───────────────────────────────────────────────────────


def send_text(number: str, text: str) -> dict:
    if not number:
        return {"ok": False, "status": 400, "error": "Numero vazio/invalido."}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": number,
        "type": "text",
        "text": {"body": text},
    }
    return _send(payload)


def send_image(number: str, media_id: str, caption: str = "") -> dict:
    if not number or not media_id:
        return {"ok": False, "status": 400, "error": "number e media_id requeridos."}
    img = {"id": media_id}
    if caption:
        img["caption"] = caption
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": number,
        "type": "image",
        "image": img,
    }
    return _send(payload)


def send_audio(number: str, media_id: str) -> dict:
    if not number or not media_id:
        return {"ok": False, "status": 400, "error": "number e media_id requeridos."}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": number,
        "type": "audio",
        "audio": {"id": media_id},
    }
    return _send(payload)


def send_document(number: str, media_id: str, filename: str = "", caption: str = "") -> dict:
    if not number or not media_id:
        return {"ok": False, "status": 400, "error": "number e media_id requeridos."}
    doc = {"id": media_id}
    if filename:
        doc["filename"] = filename
    if caption:
        doc["caption"] = caption
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": number,
        "type": "document",
        "document": doc,
    }
    return _send(payload)


def send_video(number: str, media_id: str, caption: str = "") -> dict:
    if not number or not media_id:
        return {"ok": False, "status": 400, "error": "number e media_id requeridos."}
    vid = {"id": media_id}
    if caption:
        vid["caption"] = caption
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": number,
        "type": "video",
        "video": vid,
    }
    return _send(payload)


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
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": number,
        "type": "template",
        "template": tpl,
    }
    return _send(payload)


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
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": number,
        "type": "interactive",
        "interactive": interactive,
    }
    return _send(payload)


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
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": number,
        "type": "interactive",
        "interactive": interactive,
    }
    return _send(payload)


# ── Indicadores e leitura ────────────────────────────────────────────────────


def mark_read(message_id: str) -> dict:
    if not message_id:
        return {"ok": False, "status": 400, "error": "message_id vazio."}
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    return _send(payload)


def send_typing(message_id: str) -> dict:
    if not message_id:
        return {"ok": False, "status": 400, "error": "message_id vazio."}
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    return _send(payload)


# ── Mídia (upload/download) ─────────────────────────────────────────────────


def upload_media_bytes(file_bytes: bytes, mime_type: str, filename: str = "file") -> dict:
    url = f"{_BASE}/{_PHONE_ID}/media"
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {_TOKEN}"},
                          data={"messaging_product": "whatsapp"},
                          files={"file": (filename, io.BytesIO(file_bytes), mime_type)},
                          timeout=60)
        data = r.json() if r.ok else {"error": r.text[:300]}
        print(f"[meta] POST /media upload_bytes -> {r.status_code} | {str(data)[:200]}", flush=True)
        if r.ok:
            return {"ok": True, "status": r.status_code, "data": data}
        return {"ok": False, "status": r.status_code, "error": str(data)[:300]}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}


def get_media_url(media_id: str) -> dict:
    url = f"{_BASE}/{media_id}"
    params = {"phone_number_id": _PHONE_ID}
    return _request("GET", url, params=params)


def get_webhook_media_url(media_id: str) -> dict:
    """Obtém URL de download de mídia recebida via webhook (Datafy, válida 30 dias)."""
    url = f"https://cloud.datafyapi.com.br/media/{media_id}"
    return _request("GET", url)


def download_media_bytes(media_url: str) -> bytes:
    try:
        r = requests.get(media_url, headers={"Authorization": f"Bearer {_TOKEN}"}, timeout=60)
        if r.ok:
            return r.content
        print(f"[meta] download_media falhou: {r.status_code}", flush=True)
        return b""
    except Exception as e:
        print(f"[meta] download_media erro: {e}", flush=True)
        return b""


# ── Templates ────────────────────────────────────────────────────────────────


def list_templates() -> dict:
    url = f"{_BASE}/{_WABA_ID}/message_templates"
    return _request("GET", url)


def get_template(template_id: str) -> dict:
    url = f"{_BASE}/{template_id}"
    return _request("GET", url)


def delete_template(template_name: str) -> dict:
    url = f"{_BASE}/{_WABA_ID}/message_templates"
    params = {"name": template_name}
    return _request("DELETE", url, params=params)


def create_template(name: str, category: str, language: str, body: str,
                    header_text: str = "", buttons: list | None = None) -> dict:
    """Cria um template na WABA via Meta Graph API.
    category: MARKETING | UTILITY | AUTHENTICATION
    language: ex 'pt_BR'
    body: texto do template, use {{1}}, {{2}} etc para variaveis
    header_text: (opcional) texto do header
    buttons: (opcional) lista de botoes, ex [{"type": "QUICK_REPLY", "text": "Sim"}]
    """
    components = []
    if header_text:
        components.append({
            "type": "HEADER",
            "format": "TEXT",
            "text": header_text,
        })
    if body:
        components.append({
            "type": "BODY",
            "text": body,
        })
    if buttons:
        components.append({
            "type": "BUTTONS",
            "buttons": buttons,
        })
    payload = {
        "name": name,
        "category": category.upper(),
        "language": language,
        "components": components,
    }
    url = f"{_BASE}/{_WABA_ID}/message_templates"
    return _request("POST", url, body=payload)


# ── Business Profile / Phone Info ────────────────────────────────────────────


def get_phone_info() -> dict:
    url = f"{_BASE}/{_PHONE_ID}"
    params = {"fields": "verified_name,display_phone_number,quality_rating,name_status,status"}
    return _request("GET", url, params=params)


def get_business_profile() -> dict:
    url = f"{_BASE}/{_PHONE_ID}/whatsapp_business_profile"
    params = {"fields": "about,address,description,email,profile_picture_url,websites,vertical"}
    return _request("GET", url, params=params)


def update_business_profile(**kwargs) -> dict:
    url = f"{_BASE}/{_PHONE_ID}/whatsapp_business_profile"
    body = {"messaging_product": "whatsapp", **kwargs}
    return _request("POST", url, body=body)


# ── Configuração ─────────────────────────────────────────────────────────────


def config_problem() -> str | None:
    if not _TOKEN or "cole_o" in _TOKEN.lower():
        return "DATAFY_TOKEN nao configurado no .env"
    if not _PHONE_ID or "cole_o" in _PHONE_ID.lower():
        return "DATAFY_PHONE_NUMBER_ID nao configurado no .env"
    if not _WABA_ID or "cole_o" in _WABA_ID.lower():
        return "DATAFY_WABA_ID nao configurado no .env"
    return None


# ── Datafy extras ────────────────────────────────────────────────────────────


def reload_config() -> None:
    """Recarrega variaveis de ambiente nos modulos (apos salvar .env pelo painel)."""
    global _PHONE_ID, _WABA_ID, _TOKEN
    from dotenv import load_dotenv
    load_dotenv(override=True)
    _PHONE_ID = os.getenv("DATAFY_PHONE_NUMBER_ID", "")
    _WABA_ID = os.getenv("DATAFY_WABA_ID", "")
    _TOKEN = os.getenv("DATAFY_TOKEN", "")


def get_phone_id() -> str:
    return _PHONE_ID


def get_waba_id() -> str:
    return _WABA_ID
