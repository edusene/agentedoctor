"""
test_app.py — Rotas do app (login, webhook, cabecalhos, limite) com o cliente de teste do Flask.

Importa o app, que carrega o .env no import: so roda pelo `python verify.py --testes`,
que liga a trava contra producao (SQLite temporario). Fora dele, pula.
"""

import hashlib
import hmac
import os
import time
import unittest
from unittest import mock

if not os.environ.get("VERIFY_TESTES"):
    raise unittest.SkipTest("rode por: python verify.py --testes (trava contra producao)")

os.environ.update(ADMIN_PASSWORD="senha-de-teste-123", SECRET_KEY="k" * 32,
                  WHATSAPI_WEBHOOK_SECRET="segredo-de-teste")
import db  # noqa: E402

assert db.DB_DRIVER == "sqlite"
import app as app_mod  # noqa: E402


def cliente():
    return app_mod.app.test_client()


class TestPainel(unittest.TestCase):
    def test_rotas_exigem_login(self):
        c = cliente()
        for rota in ("/panel", "/api/conversations"):
            r = c.get(rota)
            self.assertEqual((r.status_code, r.headers["Location"]), (302, "/login"))

    def test_cabecalhos_de_seguranca(self):
        h = cliente().get("/login").headers
        self.assertIn("max-age", h["Strict-Transport-Security"])
        self.assertEqual(h["X-Frame-Options"], "DENY")

    def test_login_e_sessao_com_validade(self):
        c = cliente()
        self.assertEqual(c.post("/login", data={"username": "admin", "password": "errada"}).status_code, 200)
        r = c.post("/login", data={"username": "admin", "password": "senha-de-teste-123"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(any("Expires" in h for h in r.headers.getlist("Set-Cookie")))
        self.assertEqual(c.get("/panel").status_code, 200)

    def test_editor_de_env_recusa_quebra_de_linha(self):
        c = cliente()
        c.post("/login", data={"username": "admin", "password": "senha-de-teste-123"})
        r = c.post("/api/whatsapp/config", json={"WHATSAPI_KEY": "a\nDATABASE_URL=x"})
        self.assertEqual(r.status_code, 400)


class TestSessaoEMidia(unittest.TestCase):
    def test_logout_so_por_post(self):
        c = cliente()
        c.post("/login", data={"username": "admin", "password": "senha-de-teste-123"})
        self.assertEqual(c.get("/logout").status_code, 405)
        self.assertEqual(c.post("/logout").status_code, 302)
        self.assertEqual(c.get("/panel").status_code, 302)

    def test_mime_do_provedor_so_passa_se_for_midia_conhecida(self):
        self.assertEqual(app_mod._mime_seguro("image/jpeg; charset=x"), "image/jpeg")
        self.assertEqual(app_mod._mime_seguro('text/html"><script>'), "application/octet-stream")
        self.assertEqual(app_mod._mime_seguro(None), "application/octet-stream")


class TestWebhook(unittest.TestCase):
    def test_corpo_grande_e_recusado(self):
        r = cliente().post("/webhook", data="x" * (1024 * 1024 + 1), headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)

    def test_sem_assinatura_e_recusado(self):
        r = cliente().post("/webhook", data="{}", headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 401)

    def _assinado(self, corpo, segredo):
        ts = str(int(time.time()))
        sig = "sha256=" + hmac.new(segredo.encode(), f"{ts}.{corpo}".encode(), hashlib.sha256).hexdigest()
        return {"Content-Type": "application/json", "X-Webhook-Signature": sig, "X-Webhook-Timestamp": ts}

    def test_pedido_assinado_corretamente_passa(self):
        r = cliente().post("/webhook", data="{}", headers=self._assinado("{}", "segredo-de-teste"))
        self.assertEqual(r.status_code, 200)

    def test_segredo_trocado_no_painel_vale_sem_reiniciar(self):
        with mock.patch.dict(os.environ, {"WHATSAPI_WEBHOOK_SECRET": "segredo-novo"}):
            c = cliente()
            self.assertEqual(c.post("/webhook", data="{}", headers=self._assinado("{}", "segredo-novo")).status_code, 200)
            self.assertEqual(c.post("/webhook", data="{}", headers=self._assinado("{}", "segredo-de-teste")).status_code, 401)

    def test_assinatura_errada_e_recusada(self):
        r = cliente().post("/webhook", data="{}", headers={
            "Content-Type": "application/json", "X-Webhook-Signature": "sha256=00",
            "X-Webhook-Timestamp": "1"})
        self.assertEqual(r.status_code, 401)


class TestApiWhatsapp(unittest.TestCase):
    """API propria de WhatsApp: formato do webhook e do envio (sem rede)."""

    EVENTO = {"id": "x", "event": "message.received", "data": {
        "phone_number_id": "123", "contact": {"wa_id": "5511999998888", "name": "Ana"},
        "message": {"id": "wamid.X", "from": "5511999998888", "timestamp": "1", "type": "text",
                    "text": {"body": "Ola"}}}}

    def test_evento_vira_o_formato_da_meta(self):
        d = app_mod._evento_para_formato_meta(self.EVENTO)
        value = d["entry"][0]["changes"][0]["value"]
        self.assertEqual(value["messages"][0]["text"]["body"], "Ola")
        self.assertEqual(value["contacts"][0]["profile"]["name"], "Ana")
        self.assertEqual(app_mod._evento_para_formato_meta({"event": "message.sent"}), {})

    def test_envio_usa_a_rota_da_api_e_devolve_a_resposta_da_meta(self):
        import meta
        resp = mock.Mock(ok=True, status_code=201)
        resp.json.return_value = {"data": {"id": "i", "wamid": "wamid.Y", "meta_response": {
            "messages": [{"id": "wamid.Y"}], "contacts": [{"wa_id": "5511999998888"}]}}}
        resp.json.return_value["data"]["content"] = {"body": "TEXTO-SECRETO"}
        resp.json.return_value["request_id"] = "req1"
        import contextlib
        import io as _io
        saida = _io.StringIO()
        with mock.patch.object(meta, "_PHONE_ID", "123"), mock.patch.object(meta, "_TOKEN", "sk_test_x"),                 mock.patch.object(meta.requests, "request", return_value=resp) as rq,                 contextlib.redirect_stdout(saida):
            r = meta.send_text("5511999998888", "Oi")
        # O log nao leva o texto enviado nem o telefone inteiro.
        self.assertNotIn("TEXTO-SECRETO", saida.getvalue())
        self.assertNotIn("5511999998888", saida.getvalue())
        self.assertIn("req1", saida.getvalue())
        args, kw = rq.call_args
        self.assertTrue(args[1].endswith("/whatsapp/123/messages"))
        self.assertEqual(kw["json"], {"to": "5511999998888", "type": "text", "text": {"body": "Oi"}})
        self.assertEqual(kw["headers"]["Authorization"], "Bearer sk_test_x")
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["messages"][0]["id"], "wamid.Y")

    def test_digitando_modelo_perfil_e_midia_usam_as_rotas_novas(self):
        import meta
        resp = mock.Mock(ok=True, status_code=200, headers={"Content-Type": "image/jpeg; x=1"}, content=b"IMG")
        resp.json.return_value = {"data": {"success": True}}
        with mock.patch.object(meta, "_PHONE_ID", "123"), mock.patch.object(meta.requests, "request", return_value=resp) as rq:
            meta.send_typing("wamid.Z")
            self.assertEqual(rq.call_args.kwargs["json"], {"message_id": "wamid.Z", "typing": True})
            meta.create_template("aviso", "utility", "pt_BR", "Oi {{1}}")
            body = rq.call_args.kwargs["json"]
            self.assertEqual((body["category"], body["components"]), ("UTILITY", [{"type": "BODY", "text": "Oi {{1}}"}]))
            meta.delete_template("aviso")
            self.assertEqual(rq.call_args.args[:2][0], "DELETE")
            self.assertTrue(rq.call_args.args[1].endswith("/whatsapp/123/templates/aviso"))
            meta.update_business_profile(about="Clinica")
            self.assertTrue(rq.call_args.args[1].endswith("/whatsapp/123/business_profile"))
        with mock.patch.object(meta, "_PHONE_ID", "123"), mock.patch.object(meta.requests, "get", return_value=resp) as g:
            info = meta.get_webhook_media_url("m1")
            self.assertEqual(info["data"]["mime_type"], "image/jpeg")
            self.assertEqual(meta.download_media_bytes(info["data"]["url"]), b"IMG")
            self.assertEqual(g.call_count, 1)  # uma chamada por midia

    def test_erro_da_api_vira_texto_com_o_motivo(self):
        import meta
        resp = mock.Mock(ok=False, status_code=429)
        resp.json.return_value = {"error": {"code": "rate_limited", "message": "Muitas requisicoes"}}
        with mock.patch.object(meta.requests, "request", return_value=resp):
            r = meta.send_text("5511999998888", "Oi")
        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], 429)
        self.assertIn("rate_limited", r["error"])


class TestLimites(unittest.TestCase):
    def test_x_forwarded_for_forjado_nao_zera_o_limite_do_login(self):
        c = cliente()
        r = None
        for i in range(8):
            r = c.post("/login", data={"username": "a", "password": "b"},
                       headers={"X-Forwarded-For": f"9.9.9.{i}, 1.2.3.4"})
        self.assertEqual(r.status_code, 429)

    def test_teto_de_chamadas_ao_modelo_por_numero(self):
        app_mod._llm_chamadas.clear()
        resultados = [app_mod._llm_dentro_do_limite("5562000000000") for _ in range(app_mod._LLM_POR_HORA + 1)]
        self.assertEqual(resultados, [True] * app_mod._LLM_POR_HORA + [False])



class TestTokenGoogle(unittest.TestCase):
    def test_refresh_token_fica_cifrado_no_banco_e_volta_igual(self):
        import database
        import google_agenda
        google_agenda._guardar_token("1//token-de-teste")
        guardado = database.get_setting("google_refresh_token", "")
        self.assertTrue(guardado.startswith("enc1:"))
        self.assertNotIn("token-de-teste", guardado)
        self.assertEqual(google_agenda._ler_token(), "1//token-de-teste")

    def test_token_antigo_em_texto_ainda_e_lido(self):
        import database
        import google_agenda
        database.set_setting("google_refresh_token", "1//antigo")
        self.assertEqual(google_agenda._ler_token(), "1//antigo")


if __name__ == "__main__":
    unittest.main()
