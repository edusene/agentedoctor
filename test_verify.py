"""test_verify.py — Auto-teste do detector de segredos do verify.py."""

import unittest

import verify


class TestSegredos(unittest.TestCase):
    def test_pega_segredos_reais(self):
        self.assertTrue(verify.achar_segredos("OPENAI_API_KEY=sk-" + "a" * 30))
        self.assertTrue(verify.achar_segredos("DATAFY_TOKEN=sk_live_" + "A1b2C3d4E5"))
        self.assertTrue(verify.achar_segredos("postgresql://postgres.abc:Senh4Real9@host:6543/postgres"))

    def test_aceita_placeholders_do_exemplo(self):
        self.assertEqual(verify.achar_segredos("DATAFY_TOKEN=sk_live_xxx"), [])
        self.assertEqual(verify.achar_segredos("postgresql://postgres.REF:SUA_SENHA@host:6543/postgres"), [])
        self.assertEqual(verify.achar_segredos("postgresql://postgres.<ref>:<senha>@aws-0-<regiao>.pooler.supabase.com:6543/postgres"), [])
        self.assertEqual(verify.achar_segredos("DATAFY_WEBHOOK_SECRET=whsec_xxx"), [])


if __name__ == "__main__":
    unittest.main()
