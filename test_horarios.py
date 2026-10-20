"""
test_horarios.py — Vagas livres da aba Horários (sem rede e sem banco).

    python -m unittest test_horarios -v
"""

import unittest
from datetime import date, datetime

import horarios

# Segunda-feira, 19/10/2026, 07h00.
AGORA = datetime(2026, 10, 19, 7, 0)


def cfg(**mudar):
    c, erro = horarios.normalizar({**horarios.PADRAO, **mudar})
    assert not erro, erro
    return c


class TestVagas(unittest.TestCase):
    def test_semana_padrao(self):
        v = horarios.vagas(cfg(antecedencia_horas=0), date(2026, 10, 19), date(2026, 10, 26), [], 60, AGORA)
        self.assertEqual([x["dia"] for x in v], ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"])
        self.assertEqual(v[0]["horarios"], ["08:00", "09:00", "10:00", "11:00",
                                            "14:00", "15:00", "16:00", "17:00"])

    def test_antecedencia(self):
        v = horarios.vagas(cfg(antecedencia_horas=24), date(2026, 10, 19), date(2026, 10, 21), [], 60, AGORA)
        self.assertEqual(v[0]["data"], "2026-10-20")
        self.assertEqual(v[0]["horarios"][0], "08:00")

    def test_ocupado_tira_a_vaga_que_sobrepoe(self):
        ocupado = [(datetime(2026, 10, 19, 9, 30), datetime(2026, 10, 19, 10, 30))]
        v = horarios.vagas(cfg(antecedencia_horas=0), date(2026, 10, 19), date(2026, 10, 20), ocupado, 60, AGORA)
        self.assertNotIn("09:00", v[0]["horarios"])
        self.assertNotIn("10:00", v[0]["horarios"])
        self.assertIn("08:00", v[0]["horarios"])
        self.assertIn("11:00", v[0]["horarios"])

    def test_duracao_maior_que_o_passo_nao_estoura_a_faixa(self):
        v = horarios.vagas(cfg(antecedencia_horas=0, passo_min=30), date(2026, 10, 19), date(2026, 10, 20), [], 90, AGORA)
        self.assertEqual(v[0]["horarios"][:6], ["08:00", "08:30", "09:00", "09:30", "10:00", "10:30"])
        self.assertNotIn("11:00", v[0]["horarios"])
        self.assertEqual(v[0]["horarios"][-1], "16:30")

    def test_dia_bloqueado(self):
        c = cfg(antecedencia_horas=0, bloqueios=[{"data": "2026-10-20", "motivo": "Congresso"}])
        v = horarios.vagas(c, date(2026, 10, 19), date(2026, 10, 22), [], 60, AGORA)
        self.assertEqual([x["data"] for x in v], ["2026-10-19", "2026-10-21"])

    def test_janela(self):
        v = horarios.vagas(cfg(antecedencia_horas=0, janela_dias=7), date(2026, 10, 19), date(2026, 12, 31), [], 60, AGORA)
        self.assertLessEqual(v[-1]["data"], "2026-10-27")

    def test_livre(self):
        c = cfg(antecedencia_horas=0)
        self.assertTrue(horarios.livre(c, datetime(2026, 10, 19, 14, 0), [], 60, AGORA))
        self.assertFalse(horarios.livre(c, datetime(2026, 10, 19, 12, 0), [], 60, AGORA))
        self.assertFalse(horarios.livre(c, datetime(2026, 10, 24, 9, 0), [], 60, AGORA))  # sabado


class TestConfig(unittest.TestCase):
    def test_faixa_invertida(self):
        _, erro = horarios.normalizar({"dias": {"0": [["12:00", "08:00"]]}})
        self.assertIn("Segunda", erro)

    def test_faixas_sobrepostas(self):
        _, erro = horarios.normalizar({"dias": {"0": [["08:00", "12:00"], ["11:00", "13:00"]]}})
        self.assertIn("sobrepõem", erro)

    def test_passo_fora_do_limite(self):
        _, erro = horarios.normalizar({"passo_min": 5})
        self.assertTrue(erro)

    def test_salvo_estragado_volta_ao_padrao(self):
        self.assertEqual(horarios.carregar("{nao e json"), horarios.PADRAO)
        self.assertEqual(horarios.carregar(""), horarios.PADRAO)

    def test_ida_e_volta(self):
        import json
        c = cfg(bloqueios=[{"data": "2026-12-25", "motivo": "Natal"}, {"data": "2026-12-25"}])
        self.assertEqual(len(c["bloqueios"]), 1)
        self.assertEqual(horarios.carregar(json.dumps(c)), c)


if __name__ == "__main__":
    unittest.main()
