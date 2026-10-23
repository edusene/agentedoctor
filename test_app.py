"""
test_app.py — Rotas do app (login, webhook, cabecalhos, limite) com o cliente de teste do Flask.

Importa o app, que carrega o .env no import: so roda pelo `python verify.py --testes`,
que liga a trava contra producao (SQLite temporario). Fora dele, pula.
"""

import os
import unittest

if not os.environ.get("VERIFY_TESTES"):
    raise unittest.SkipTest("rode por: python verify.py --testes (trava contra producao)")

os.environ.update(ADMIN_PASSWORD="senha-de-teste-123", SECRET_KEY="k" * 32,
                  DATAFY_WEBHOOK_SECRET="segredo-de-teste")
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
        r = c.post("/api/whatsapp/config", json={"DATAFY_TOKEN": "a\nDATABASE_URL=x"})
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

    def test_assinatura_errada_e_recusada(self):
        r = cliente().post("/webhook", data="{}", headers={
            "Content-Type": "application/json", "x-datafy-signature-256": "sha256=00",
            "x-datafy-timestamp": "1"})
        self.assertEqual(r.status_code, 401)


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
