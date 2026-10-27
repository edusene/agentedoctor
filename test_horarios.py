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


class EscolhaAutomatica(unittest.TestCase):
    VAGAS = [
        {"data": "2026-10-27", "dia": "Terça", "horarios": ["08:00", "09:00", "14:00"]},
        {"data": "2026-10-28", "dia": "Quarta", "horarios": ["08:00", "15:00"]},
        {"data": "2026-10-30", "dia": "Sexta", "horarios": ["14:00", "16:00"]},
    ]

    def test_dia_e_periodo(self):
        self.assertEqual(horarios.escolher(self.VAGAS, "Terças à tarde"), datetime(2026, 10, 27, 14))
        self.assertEqual(horarios.escolher(self.VAGAS, "Terças manhã e sextas a tarde"), datetime(2026, 10, 27, 8))

    def test_hora_exata(self):
        self.assertEqual(horarios.escolher(self.VAGAS, "quarta-feira as 8 horas"), datetime(2026, 10, 28, 8))
        self.assertEqual(horarios.escolher(self.VAGAS, "quarta às 15h"), datetime(2026, 10, 28, 15))

    def test_qualquer_dia_a_tarde(self):
        self.assertEqual(horarios.escolher(self.VAGAS, "Qualquer dia a tarde"), datetime(2026, 10, 27, 14))

    def test_sem_vaga_ou_sem_criterio_nao_escolhe(self):
        self.assertIsNone(horarios.escolher(self.VAGAS, "quintas de manhã"))
        self.assertIsNone(horarios.escolher(self.VAGAS, "qualquer horário, menos sexta"))
        self.assertIsNone(horarios.escolher(self.VAGAS, "qualquer horário amanhã"))
        self.assertIsNone(horarios.escolher(self.VAGAS, "ainda não sei"))
        self.assertIsNone(horarios.escolher([], "terça"))

    def test_horario_aberto_pega_a_primeira_vaga(self):
        for frase in ("qualquer horário", "Quando der", "tanto faz", "Qualquer dia e qualquer hora",
                      "tenho disponibilidade total", "o que vocês tiverem"):
            self.assertEqual(horarios.escolher(self.VAGAS, frase), datetime(2026, 10, 27, 8), frase)

    def test_variacoes(self):
        casos = {
            "ter e qui a tarde": datetime(2026, 10, 27, 14),
            "sexta às 16": datetime(2026, 10, 30, 16),
            "sexta depois das 15": datetime(2026, 10, 30, 16),
            "sexta-feira 16hrs": datetime(2026, 10, 30, 16),
            "quarta as 3 da tarde": datetime(2026, 10, 28, 15),
            "TERÇAS A TARDE": datetime(2026, 10, 27, 14),
            "terssa de manhã": datetime(2026, 10, 27, 8),
            "amanhã de manhã": None,
            "dia 30": None,
        }
        for texto, esperado in casos.items():
            self.assertEqual(horarios.escolher(self.VAGAS, texto), esperado, texto)


class VagaMaisProxima(unittest.TestCase):
    """Modo Auto: o que não cabe exato vira a vaga livre mais perto, não pedido para a equipe."""

    VAGAS = EscolhaAutomatica.VAGAS

    def test_exato_continua_exato(self):
        self.assertEqual(horarios.proxima(self.VAGAS, "sexta às 16"), (datetime(2026, 10, 30, 16), True))

    def test_hora_sem_vaga_vai_para_a_mais_perto_no_mesmo_dia(self):
        vagas = [{"data": "2026-10-28", "dia": "Quarta", "horarios": ["08:00", "11:00", "14:00", "15:00"]}]
        self.assertEqual(horarios.proxima(vagas, "quarta às 13h"), (datetime(2026, 10, 28, 14), False))
        self.assertEqual(horarios.proxima(vagas, "quarta às 12h"), (datetime(2026, 10, 28, 11), False))

    def test_horario_ja_agendado_nao_e_oferecido_e_vira_proposta(self):
        # Outro paciente ja tem 10h de segunda: a vaga some e o pedido "10h" recebe a mais perto.
        ocupado = [(datetime(2026, 10, 19, 10), datetime(2026, 10, 19, 11))]
        vagas = horarios.vagas(cfg(antecedencia_horas=0), date(2026, 10, 19), date(2026, 10, 20), ocupado, 60, AGORA)
        self.assertNotIn("10:00", vagas[0]["horarios"])
        escolhida = horarios.proxima(vagas, "segunda às 10h")
        self.assertFalse(escolhida[1])
        self.assertIn(escolhida[0], (datetime(2026, 10, 19, 9), datetime(2026, 10, 19, 11)))

    def test_dia_sem_atendimento_vai_para_o_mesmo_periodo(self):
        self.assertEqual(horarios.proxima(self.VAGAS, "sábado de manhã"), (datetime(2026, 10, 27, 8), False))
        self.assertEqual(horarios.proxima(self.VAGAS, "domingo à tarde"), (datetime(2026, 10, 27, 14), False))

    def test_dia_bloqueado_ou_lotado_vai_para_a_primeira_vaga_que_resta(self):
        self.assertEqual(horarios.proxima(self.VAGAS, "quintas de manhã"), (datetime(2026, 10, 27, 8), False))
        self.assertEqual(horarios.proxima(self.VAGAS, "quinta às 15h"), (datetime(2026, 10, 27, 14), False))

    def test_menos_um_dia_e_dia_relativo(self):
        self.assertEqual(horarios.proxima(self.VAGAS, "qualquer horário, menos terça"), (datetime(2026, 10, 28, 8), True))
        self.assertEqual(horarios.proxima(self.VAGAS, "terça ou sexta, exceto terça"), (datetime(2026, 10, 30, 14), True))
        self.assertEqual(horarios.proxima(self.VAGAS, "amanhã de manhã"), (datetime(2026, 10, 27, 8), True))
        self.assertEqual(horarios.proxima(self.VAGAS, "amanhã"), (datetime(2026, 10, 27, 8), True))

    def test_sem_sentido_fica_para_a_equipe(self):
        self.assertIsNone(horarios.proxima(self.VAGAS, "ainda não sei"))
        self.assertIsNone(horarios.proxima([], "terça"))
        self.assertIsNone(horarios.proxima(self.VAGAS, "dia 45"))

    def test_dia_do_mes(self):
        self.assertEqual(horarios.proxima(self.VAGAS, "dia 30"), (datetime(2026, 10, 30, 14), True))
        self.assertEqual(horarios.proxima(self.VAGAS, "dia 30 às 16h"), (datetime(2026, 10, 30, 16), True))
        self.assertEqual(horarios.proxima(self.VAGAS, "30/10 à tarde"), (datetime(2026, 10, 30, 14), True))
        # sem vaga no dia 29: a data mais perto (28, a mais cedo no empate), e avisa
        self.assertEqual(horarios.proxima(self.VAGAS, "dia 29"), (datetime(2026, 10, 28, 8), False))
        # dia 30 de manhã: nao ha manha no dia 30, fica a data pedida
        self.assertEqual(horarios.proxima(self.VAGAS, "dia 30 de manhã"), (datetime(2026, 10, 30, 14), False))
