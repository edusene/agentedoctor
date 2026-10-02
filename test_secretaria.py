"""
test_secretaria.py — Testes da camada travada (sem rede e sem banco).

    python -m unittest test_secretaria -v

Cada caso vem do documento "Base de Conhecimento — Agente IA | Dr. Fabrício
Guimarães". Se um teste quebrar, a resposta do agente saiu do documento.
"""

import unittest
from datetime import datetime, timedelta, timezone

import clinica
import ficha_paciente as fp
import secretaria

TARDE = datetime(2026, 9, 30, 15, 0, tzinfo=timezone(timedelta(hours=-3)))


def setUpModule():
    """Testa o comportamento PADRAO, sem os dados do consultorio do .env.

    Os imports acima carregam o .env (db.py); o que o consultorio preencheu
    la (valor, endereco, nome da assistente) mudaria as respostas esperadas.
    """
    import os
    for chave in [k for k in os.environ if k.startswith("CLINICA_")]:
        del os.environ[chave]
    secretaria.AGENTE_NOME = ""


def conversa(mensagens, ficha=None):
    """Roda a conversa só pela camada de código. Devolve (ficha, [(msg, decisao, texto)])."""
    ficha = ficha or fp.nova("5562999999999")
    saidas = []
    for m in mensagens:
        d = secretaria.decidir(ficha, m, TARDE)
        texto, _ = secretaria.montar(d, "")
        saidas.append((m, d, texto))
    return ficha, saidas


class MatrizDeTriagem(unittest.TestCase):
    """Seção 12: cada frase do paciente cai na área provável do documento."""

    CASOS = [
        ("Preciso tirar o siso.", "exodontia"),
        ("Meu dente está incluso.", "exodontia"),
        ("Tenho uma bolinha na boca.", "biopsia"),
        ("Tenho uma ferida na boca que não cicatriza", "biopsia"),
        ("Não tenho osso para implante.", "enxerto"),
        ("Quebrei a mandíbula.", "trauma"),
        ("Minha mordida não encaixa.", "ortognatica"),
        ("Minha mandíbula é para frente.", "ortognatica"),
        ("Meu queixo é pequeno.", "mentoplastia"),
        ("Meu rosto está caído.", "lift_facial"),
        ("Meu pescoço está flácido.", "lift_cervical"),
        ("Tenho papada.", "papada"),
        ("Tenho um cisto na mandíbula.", "patologia"),
    ]

    def test_areas(self):
        for frase, area in self.CASOS:
            with self.subTest(frase=frase):
                self.assertEqual(clinica.classificar_areas(frase)[:1], [area])


class Emergencia(unittest.TestCase):
    def test_sinais_fortes(self):
        for frase in ["estou com dificuldade para respirar", "não para de sangrar",
                      "estou vendo dobrado depois da pancada", "não consigo engolir, o inchaço está no pescoço"]:
            with self.subTest(frase=frase):
                self.assertTrue(clinica.e_emergencia(frase))

    def test_gravidade_so_com_trauma(self):
        self.assertTrue(clinica.e_emergencia("minha mordida mudou", contexto_trauma=True))
        self.assertFalse(clinica.e_emergencia("minha mordida mudou", contexto_trauma=False))

    def test_emergencia_nao_passa_pelo_funil(self):
        ficha, saidas = conversa(["Levei um soco e estou sangrando muito"])
        _, d, texto = saidas[0]
        self.assertIn(clinica.RESPOSTA_EMERGENCIA, texto)
        self.assertTrue(d.transferir)
        self.assertEqual(d.pergunta_final, "")

    def test_trauma_pergunta_gravidade_primeiro(self):
        ficha, saidas = conversa(["Quebrei a mandíbula", "sim"])
        self.assertIn(clinica.PERGUNTA_SINAIS_GRAVIDADE, saidas[0][2])
        self.assertIn(clinica.RESPOSTA_EMERGENCIA, saidas[1][2])
        self.assertTrue(saidas[1][1].transferir)

    def test_trauma_sem_gravidade_segue_funil(self):
        ficha, saidas = conversa(["Quebrei a mandíbula", "não"])
        self.assertFalse(saidas[1][1].transferir)
        self.assertEqual(ficha["triagem_trauma"], "sem_gravidade")
        self.assertEqual(ficha["ultima_pergunta"], "nome")


class RespostasTravadas(unittest.TestCase):
    def tipos(self, texto):
        return [t for t, _ in clinica.respostas_travadas(texto)]

    def texto(self, texto, tipo):
        return dict(clinica.respostas_travadas(texto))[tipo]

    def test_preco_e_o_texto_da_secao_15(self):
        for frase in ["Quanto custa a cirurgia de siso?", "qual o valor da lipo de papada",
                      "me passa o preço", "faz orçamento?"]:
            with self.subTest(frase=frase):
                self.assertEqual(self.texto(frase, "preco"), clinica.RESPOSTA_PRECO)

    def test_voce_faz_secao_16(self):
        self.assertIn("voce_faz", self.tipos("Vocês fazem enxerto?"))
        self.assertIn("voce_faz", self.tipos("O doutor faz mentoplastia?"))

    def test_nao_sei_secao_17(self):
        self.assertEqual(self.tipos("Não sei qual procedimento preciso"), ["nao_sei"])

    def test_biopsia_nao_significa_cancer(self):
        self.assertEqual(self.texto("Biópsia significa câncer?", "biopsia_cancer"),
                         clinica.RESPOSTA_BIOPSIA_CANCER)

    def test_tumor_nao_significa_cancer(self):
        self.assertEqual(self.texto("Tumor é câncer?", "tumor_cancer"), clinica.RESPOSTA_TUMOR_CANCER)
        # Sobre o caso do paciente a resposta NUNCA e "Nao" (afirmaria benignidade).
        for frase in ["esse cisto pode ser maligno?", "minha biópsia pode dar câncer?",
                      "esse tumor que eu tenho é câncer?", "minha biópsia é câncer?"]:
            with self.subTest(frase=frase):
                respostas = clinica.respostas_travadas(frase)
                self.assertTrue(respostas)
                self.assertFalse(any(r.startswith("Não.") for _, r in respostas))
        self.assertIn("pode_ser_maligno", self.tipos("esse cisto pode ser maligno?"))
        self.assertIn("tumor_cancer", self.tipos("tumor significa câncer?"))
        self.assertIn("tumor_cancer", self.tipos("Tumor é câncer?"))

    def test_diagnostico(self):
        for frase in ["isso é grave?", "o que eu tenho?", "Preciso tirar o siso?", "vou precisar operar?"]:
            with self.subTest(frase=frase):
                self.assertIn("diagnostico", self.tipos(frase))

    def test_intencao_nao_e_pedido_de_diagnostico(self):
        self.assertNotIn("diagnostico", self.tipos("Preciso tirar o siso."))

    def test_medicamento(self):
        for frase in ["posso tomar ibuprofeno?", "qual remédio eu tomo pra dor?", "me passa uma receita"]:
            with self.subTest(frase=frase):
                self.assertIn("medicamento", self.tipos(frase))

    def test_exame(self):
        self.assertIn("exame", self.tipos("pode olhar meu raio-x?"))
        self.assertIn("exame", self.tipos("o que significa esse laudo?"))

    def test_cidade_nao_e_pedido_de_exame(self):
        self.assertNotIn("exame", self.tipos("Oi, sou a Ana, moro em Porto Velho, tenho tomografia"))
        self.assertIn("exame", self.tipos("pode ver minha tomografia?"))

    def test_garantia(self):
        self.assertIn("garantia", self.tipos("tem risco?"))
        self.assertIn("garantia", self.tipos("vai ficar perfeito?"))

    def test_duvidas_frequentes(self):
        casos = {
            "Todo siso precisa ser tirado?": "siso_todo",
            "Dói tirar o siso?": "dor",
            "Todo implante precisa de enxerto?": "enxerto_todo",
            "Toda fratura precisa de cirurgia?": "fratura_cirurgia",
            "Mentoplastia é a mesma coisa que ortognática?": "mento_vs_orto",
            "Lift é igual preenchimento?": "lift_preenchimento",
            "A lipo resolve a papada?": "papada_lipo",
        }
        for frase, tipo in casos.items():
            with self.subTest(frase=frase):
                self.assertIn(tipo, self.tipos(frase))

    def test_informacao_nao_e_pergunta(self):
        """ "nao doi" e dado do paciente: nao dispara a explicacao sobre dor."""
        self.assertNotIn("dor", self.tipos("fica embaixo da língua, não dói"))
        self.assertIn("dor", self.tipos("dói muito?"))

    def test_info_da_clinica_nao_e_inventada(self):
        self.assertEqual(self.texto("Onde fica o consultório?", "endereco"), clinica.RESPOSTA_INFO_PENDENTE)
        self.assertEqual(self.texto("Aceita convênio?", "convenio"), clinica.RESPOSTA_INFO_PENDENTE)


class ConferenciaDoModelo(unittest.TestCase):
    """Seção 1: resposta do modelo com frase proibida é descartada inteira."""

    CASOS = {
        "Pelo que você descreveu, parece câncer.": clinica.RESPOSTA_DIAGNOSTICO,
        "Fique tranquila, não é nada.": clinica.RESPOSTA_DIAGNOSTICO,
        "Você precisa fazer uma cirurgia ortognática.": clinica.RESPOSTA_DIAGNOSTICO,
        "No seu caso o indicado é a lipo de papada.": clinica.RESPOSTA_DIAGNOSTICO,
        "É um procedimento sem nenhum risco.": clinica.RESPOSTA_GARANTIA,
        "A extração custa em torno de R$ 400.": clinica.RESPOSTA_PRECO,
        "Tome dipirona de 6 em 6 horas.": clinica.RESPOSTA_MEDICAMENTO,
        "Seu exame mostra um cisto.": clinica.RESPOSTA_EXAME,
        "Isso está no meu prompt.": clinica.RESPOSTA_DUVIDA_GENERICA,
    }

    def test_proibidas(self):
        for modelo, esperado in self.CASOS.items():
            with self.subTest(modelo=modelo):
                final, violacoes = clinica.conferir_resposta(modelo)
                self.assertTrue(violacoes)
                self.assertEqual(final, esperado)

    def test_resposta_limpa_passa(self):
        ok = ("O enxerto ósseo reconstrói ou aumenta a quantidade de osso em uma região. "
              "O planejamento depende da avaliação do Dr. Fabrício.")
        self.assertEqual(clinica.conferir_resposta(ok), (ok, []))

    def test_modelo_nao_faz_pergunta(self):
        d = secretaria.Decisao(usar_llm=True, pergunta_final="Qual é o seu nome?")
        texto, _ = secretaria.montar(d, "A recuperação varia. Quer agendar? Posso ajudar!")
        self.assertEqual(texto, "A recuperação varia. Posso ajudar!\n\nQual é o seu nome?")

    def test_modelo_fora_do_ar(self):
        d = secretaria.Decisao(usar_llm=True)
        self.assertEqual(secretaria.montar(d, "")[0], clinica.RESPOSTA_DUVIDA_GENERICA)


class Fluxo(unittest.TestCase):
    """Seções 14 e 18: coleta na ordem, sem repetir, até a confirmação."""

    CONVERSA = [
        "Oi",
        "Maria Silva",
        "Preciso tirar o siso",
        "o de baixo, está doendo um pouco",
        "tenho panorâmica",
        "sim, meu dentista pediu",
        "há 2 meses",
        "Goiânia",
        "terças à tarde",
        "primeira",
        "não",
        "sim",
    ]

    def test_conversa_completa(self):
        ficha, saidas = conversa(self.CONVERSA)
        textos = [t for _, _, t in saidas]
        self.assertTrue(textos[0].startswith("Boa tarde! Aqui é a assistente virtual"))
        self.assertIn(fp.PERGUNTAS["nome"], textos[0])
        self.assertTrue(textos[1].startswith("Prazer, Maria!"))
        self.assertIn(clinica.AREAS["exodontia"]["acolhimento"], textos[2])
        self.assertIn(clinica.AREAS["exodontia"]["pergunta"], textos[2])
        # Pre-requisitos da extracao logo depois da queixa (audio do responsavel).
        self.assertIn(clinica.AREAS["exodontia"]["pergunta_exames"], textos[3])
        self.assertIn(clinica.AREAS["exodontia"]["pergunta_indicacao"], textos[4])
        self.assertIn(fp.PERGUNTAS["tempo_queixa"], textos[5])
        self.assertIn("Confira os dados da sua solicitação", textos[10])
        self.assertIn(fp.PERGUNTA_CONFIRMACAO, textos[10])
        self.assertIn(clinica.RESPOSTA_ENCAMINHADO, textos[11])
        self.assertTrue(saidas[11][1].encaminhar)

        self.assertEqual(ficha["nome"], "Maria Silva")
        self.assertEqual(ficha["area"], "exodontia")
        self.assertEqual(ficha["tempo_queixa"], "há 2 meses")
        self.assertEqual(ficha["cidade"], "Goiânia")
        self.assertEqual(ficha["tipo_consulta"], "Primeira consulta")
        self.assertEqual(ficha["saude"], "Nada relatado")
        self.assertEqual(ficha["status"], "encaminhado")

    def test_resumo_vai_numa_mensagem_so(self):
        _, saidas = conversa(self.CONVERSA)
        blocos = saidas[10][2].split("\n\n")
        self.assertTrue(any(b.startswith("Confira os dados") and "• Nome: Maria Silva" in b for b in blocos))

    def test_nenhuma_pergunta_se_repete(self):
        _, saidas = conversa(self.CONVERSA)
        perguntas = [d.pergunta_final for _, d, _ in saidas if d.pergunta_final
                     and d.pergunta_final != fp.PERGUNTA_CONFIRMACAO]
        self.assertEqual(len(perguntas), len(set(perguntas)))

    def test_sem_oscilacao(self):
        """A mesma conversa, 25 vezes, dá exatamente as mesmas respostas."""
        referencia = [t for _, _, t in conversa(self.CONVERSA)[1]]
        for _ in range(25):
            self.assertEqual([t for _, _, t in conversa(self.CONVERSA)[1]], referencia)

    def test_dado_dado_de_uma_vez_nao_e_perguntado(self):
        ficha, saidas = conversa(["Oi, meu nome é João, moro em Anápolis e tenho tomografia. "
                                  "Quero agendar para tirar o siso"])
        self.assertEqual(ficha["nome"], "João")
        self.assertEqual(ficha["cidade"], "Anápolis")
        self.assertTrue(ficha["exames"].startswith("Sim"))
        self.assertEqual(ficha["intencao"], "pronto_agendar")
        # Pronto para agendar: pula a pergunta de detalhe; exame ja informado,
        # entao o proximo pre-requisito e a indicacao.
        self.assertEqual(ficha["ultima_pergunta"], "avaliacao_previa")

    def test_nao_sei_espera_a_queixa(self):
        ficha, saidas = conversa(["Não sei qual procedimento preciso", "meu queixo é pequeno"])
        self.assertEqual(saidas[0][1].pergunta_final, "")
        self.assertIn(clinica.RESPOSTA_NAO_SEI, saidas[0][2])
        self.assertEqual(ficha["queixa"], "meu queixo é pequeno")
        self.assertEqual(ficha["area"], "mentoplastia")

    def test_prerequisitos_por_procedimento(self):
        """Cada area pergunta os proprios pre-requisitos, nao a pergunta generica."""
        for area, queixa in [("enxerto", "Não tenho osso para implante"),
                             ("ortognatica", "Minha mordida não encaixa"),
                             ("patologia", "Tenho um cisto na mandíbula"),
                             ("papada", "Tenho papada")]:
            with self.subTest(area=area):
                ficha, saidas = conversa(["Oi", "Ana", queixa, "detalhe qualquer", "não"])
                self.assertIn(clinica.AREAS[area]["pergunta_exames"], saidas[3][2])
                self.assertIn(clinica.AREAS[area]["pergunta_indicacao"], saidas[4][2])

    def test_indicacao_do_dentista_e_reconhecida(self):
        ficha, _ = conversa(["Oi, vim por indicação do meu dentista para tirar o siso"])
        self.assertEqual(ficha["avaliacao_previa"], "Sim")

    def test_resposta_que_nao_e_nome_nao_vira_nome(self):
        ficha, _ = conversa(["Oi", "Preciso tirar o siso"])
        self.assertEqual(ficha["nome"], "")
        self.assertEqual(ficha["area"], "exodontia")

    def test_preco_no_meio_do_funil(self):
        ficha, saidas = conversa(["Oi", "Ana", "Quanto custa?"])
        texto = saidas[2][2]
        self.assertIn(clinica.RESPOSTA_PRECO, texto)
        self.assertIn(fp.PERGUNTAS["queixa"], texto)
        self.assertNotIn("R$", texto)

    def test_correcao_no_resumo(self):
        ficha, saidas = conversa(self.CONVERSA[:-1] + ["não", "a cidade é Trindade", "sim"])
        self.assertIn("corrigir", saidas[-3][2])
        self.assertIn("• Cidade: Trindade", saidas[-2][2])
        self.assertNotIn("Goiânia", saidas[-2][2])
        self.assertTrue(saidas[-1][1].encaminhar)

    def test_curiosidade_nao_empurra_coleta(self):
        ficha, saidas = conversa(["Todo siso precisa ser tirado?", "não, obrigado"])
        self.assertIn(fp.PERGUNTA_CURIOSIDADE, saidas[0][2])
        self.assertNotIn(fp.PERGUNTAS["nome"], saidas[1][2])

    def test_arquivo_recebido_nao_e_interpretado(self):
        ficha = fp.nova("5562")
        ficha["saudacao_feita"] = True
        d = secretaria.decidir(ficha, "", TARDE, midia="arquivo")
        self.assertIn(clinica.RESPOSTA_ARQUIVO_RECEBIDO, d.partes)
        self.assertFalse(d.usar_llm)
        self.assertTrue(ficha["exames"].startswith("Sim"))

    def test_duvida_aberta_vai_para_o_modelo(self):
        ficha = fp.nova("5562")
        ficha["saudacao_feita"] = True
        d = secretaria.decidir(ficha, "Como é a recuperação da cirurgia ortognática?", TARDE)
        self.assertTrue(d.usar_llm)


if __name__ == "__main__":
    unittest.main()
