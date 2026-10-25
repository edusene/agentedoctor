"""
test_secretaria.py — Testes da camada travada (sem rede e sem banco).

    python -m unittest test_secretaria -v

Cada caso vem do documento "Base de Conhecimento — Agente IA | Dr. Fabrício
Guimarães". Se um teste quebrar, a resposta do agente saiu do documento.
"""

import os
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

    def test_preco_por_extenso_e_diagnostico_parafraseado(self):
        for modelo in ("A avaliação fica em quinhentos reais.", "Sai uns 300 pila.",
                       "Isso pode ser um cisto, mas só na consulta.", "Seu caso seria uma infecção.",
                       "Fica cinquenta reais.", "São trezentos e cinquenta reais.", "O valor é 350,00."):
            with self.subTest(modelo=modelo):
                self.assertTrue(clinica.conferir_resposta(modelo)[1])

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


CADASTRO_OK = ("Maria Silva Souza\n12/03/1990\nCPF 529.982.247-25\nRG 1234567\n"
               "maria@email.com\nRua das Flores, 120, Centro, Goiânia, CEP 74000-000")


class Fluxo(unittest.TestCase):
    """Roteiro do Dr. Fabricio (23/10): nome, queixa, pre-cadastro, dias e
    horarios, saude, resumo, encaminhamento e valor da consulta."""

    CONVERSA = [
        "Oi",
        "Maria Silva",
        "Preciso tirar o siso",
        "Tanto faz",
        CADASTRO_OK,
        "terças à tarde",
        "não",
        "sim",
    ]

    def test_conversa_completa(self):
        ficha, saidas = conversa(self.CONVERSA)
        textos = [t for _, _, t in saidas]
        self.assertEqual(textos[0], "Boa tarde! Me chamo Elisângela. Sou a colaboradora da "
                                    "Accuratio e vou iniciar o seu atendimento.\n\n"
                                    "Qual o seu nome e em que posso ajudar?")
        self.assertEqual(textos[1], "Tudo bem, Maria. Poderia me adiantar qual seria o motivo "
                                    "da sua consulta? Qual seria a sua queixa (reclamação)?")
        # Depois da queixa, direto o pre-cadastro: sem acolhimento nem exame.
        self.assertTrue(textos[3].startswith("Perfeito. Para agendamento da sua consulta, vou "
                                             "precisar fazer um pré-cadastro"))
        self.assertNotIn(clinica.AREAS["exodontia"]["acolhimento"], textos[3])
        for item in ("Nome completo", "Data de nascimento", "CPF", "RG", "E-mail", "Endereço com CEP"):
            self.assertIn(f"• {item}", textos[3])
        self.assertEqual(textos[4], "Cadastro completo, obrigada. Agora vamos ao agendamento. "
                                    "Quais dias e horários ficam melhores para você?")
        self.assertEqual(textos[5], "Certo. Por último: você tem algum problema de saúde, alergia "
                                    "ou usa algum medicamento contínuo?")
        self.assertIn("Confira os dados da sua solicitação", textos[6])
        self.assertIn(fp.PERGUNTA_CONFIRMACAO, textos[6])
        self.assertIn(clinica.RESPOSTA_ENCAMINHADO, textos[7])
        # Siso: o valor de R$ 300 vem depois do encaminhamento.
        self.assertIn(clinica.cartao_valor(300), textos[7])
        self.assertTrue(saidas[7][1].encaminhar)

        self.assertEqual(ficha["nome"], "Maria Silva")
        self.assertEqual(ficha["nome_completo"], "Maria Silva Souza")
        self.assertEqual(ficha["nascimento"], "12/03/1990")
        self.assertEqual(ficha["cpf"], "529.982.247-25")
        self.assertEqual(ficha["rg"], "1234567")
        self.assertEqual(ficha["email"], "maria@email.com")
        self.assertEqual(ficha["endereco"], "Rua das Flores, 120, Centro, Goiânia")
        self.assertEqual(ficha["cep"], "74000-000")
        self.assertEqual(ficha["saude"], "Nada relatado")
        self.assertEqual(ficha["status"], "encaminhado")

    def test_perguntas_tiradas_pelo_roteiro(self):
        """Detalhes da area, exames e primeira/retorno sairam (roteiro de 23/10)."""
        _, saidas = conversa(self.CONVERSA)
        tudo = " ".join(t for _, _, t in saidas)
        self.assertNotIn(clinica.AREAS["exodontia"]["pergunta"], tudo)
        self.assertNotIn(clinica.AREAS["exodontia"]["pergunta_exames"], tudo)
        self.assertNotIn("primeira consulta ou um retorno", tudo)

    def test_perguntas_removidas_pelo_doutor(self):
        """Indicacao, ha quanto tempo e cidade nao sao mais perguntados (06/10)."""
        _, saidas = conversa(self.CONVERSA)
        tudo = " ".join(t for _, _, t in saidas)
        self.assertNotIn(clinica.AREAS["exodontia"]["pergunta_indicacao"], tudo)
        self.assertNotIn("Há quanto tempo", tudo)
        self.assertNotIn("Em qual cidade", tudo)

    def test_conversa_do_doutor(self):
        """A conversa de teste do Dr. Fabricio (05/10), refeita com o fluxo novo."""
        ficha, saidas = conversa([
            "Olá\nTudo bem?\nGostaria de agendar uma consulta com o dr Fabricio",
            "Me chamo José\nMinha principal queixa é a posição do meu queixo.\n"
            "Acho que preciso de cirurgia Ortognática",
            "Não",
        ])
        primeira = saidas[0]
        self.assertFalse(primeira[1].usar_llm, "o 'Tudo bem?' mandava a mensagem para a IA")
        self.assertIn("Claro, vamos agendar a sua avaliação!", primeira[2])
        self.assertIn(fp.PERGUNTAS["nome"], primeira[2])
        self.assertEqual(ficha["nome"], "José")
        # A queixa sem o "Me chamo José" junto.
        self.assertEqual(ficha["queixa"], "Minha principal queixa é a posição do meu queixo. "
                                          "Acho que preciso de cirurgia Ortognática")
        self.assertIn(fp.PERGUNTAS["medico"], saidas[1][2])
        self.assertFalse(any(d.usar_llm for _, d, _ in saidas))

    def test_cadastro_em_partes_pede_so_o_que_falta(self):
        ficha, saidas = conversa(self.CONVERSA[:4] + [
            "Maria Silva Souza\n12/03/1990", "529.982.247-25\nRG 1234567\nmaria@email.com"])
        self.assertIn("ainda preciso de", saidas[4][2])
        self.assertNotIn("Nome completo", saidas[4][2])
        self.assertIn("CPF", saidas[4][2])
        self.assertIn(fp.PERGUNTAS["endereco"], saidas[5][2])
        self.assertEqual(ficha["ultima_pergunta"], "endereco")

    def test_endereco_sem_cep_pede_o_cep(self):
        ficha, saidas = conversa(self.CONVERSA[:4] + [
            "Maria Silva Souza\n12/03/1990\n529.982.247-25\nRG 1234567\nmaria@email.com\n"
            "Rua das Flores, 120, Centro, Goiânia", "74000000"])
        self.assertIn(fp.PERGUNTAS["cep"], saidas[4][2])
        self.assertEqual(ficha["cep"], "74000-000")
        self.assertEqual(ficha["rg"], "1234567")
        self.assertIn("Cadastro completo", saidas[5][2])

    def test_rg_com_hifen_nao_vira_cep(self):
        d = fp.extrair_cadastro("Ana Lima, 529.982.247-25, RG 12.345-678, Rua A, 10, Centro, 76820-000")
        self.assertEqual((d["rg"], d["cep"], d["endereco"]), ("12.345-678", "76820-000", "Rua A, 10, Centro"))

    def test_teste_de_22_10_cep_solto_nao_vira_rg(self):
        """O paciente pulou o RG e mandou o CEP solto; depois o endereco com o CEP."""
        ficha, saidas = conversa(self.CONVERSA[:4] + [
            "Carlos Pereira Lima\n08/11/2004\n529.982.247-25\n76808526\ncarlos@email.com",
            "Rua Angico, 3170 - Eletronorte 76808526", "1234567"])
        self.assertIn(fp.PERGUNTAS["endereco"], saidas[4][2])
        self.assertIn(fp.PERGUNTAS["rg"], saidas[5][2])          # o RG ainda faltava
        self.assertEqual(ficha["endereco"], "Rua Angico, 3170 - Eletronorte")
        self.assertEqual(ficha["cep"], "76808-526")
        self.assertEqual(ficha["rg"], "1234567")
        self.assertIn("Cadastro completo", saidas[6][2])

    def test_sem_email_segue_o_cadastro(self):
        f = fp.nova("1")
        self.assertTrue(fp.capturar_resposta(f, "email", "não tenho e-mail"))
        self.assertEqual(f["email"], fp.NAO_INFORMADO)

    def test_nao_tenho_no_cadastro_nao_apaga_o_nome(self):
        ficha, _ = conversa(self.CONVERSA[:4] + ["não tenho"])
        self.assertEqual(ficha["nome_completo"], "")
        f = fp.nova("1")
        self.assertTrue(fp.capturar_resposta(f, "rg", "não tenho RG"))
        self.assertEqual(f["rg"], fp.NAO_INFORMADO)

    def test_cpf_errado_e_avisado(self):
        ficha, saidas = conversa(self.CONVERSA[:4] + ["Maria Silva Souza, 12/03/1990, CPF 123.456.789-00"])
        self.assertEqual(ficha["cpf"], "")
        self.assertEqual(ficha["rg"], "")
        self.assertIn("CPF informado parece ter algum número trocado", saidas[-1][2])

    def test_cpf_errado_duas_vezes_avisa_e_o_certo_nao_herda_o_aviso(self):
        """Teste do Dr. Fabricio, 24/10: 2o envio errado ficava mudo e o aviso
        saia na resposta ao CPF certo. Endereco saia com '. .' no meio."""
        cad = ("Fabricio Souza\n07/09/1982\n70971528265\n674423\nfabricio@email.com\n"
               "Av Rio Madeira 6739. Cep 76822340. Nova esperanca - Porto Velho - RO")
        _, saidas = conversa(self.CONVERSA[:4] + [cad, "70971528265", "70971528268"])
        self.assertIn("número trocado", saidas[-2][2])
        self.assertNotIn("número trocado", saidas[-1][2])
        ficha, _ = conversa(self.CONVERSA[:4] + [cad, "70971528265", "70971528268"])
        self.assertEqual(ficha["cpf"], "709.715.282-68")
        self.assertNotIn(". .", ficha["endereco"])

    def test_preferencia_de_medico(self):
        """Pedido do Dr. Fabricio (24/10): pergunta depois da queixa; o cartao
        mostra o escolhido, ou os dois quando nao ha preferencia."""
        for resposta, esperado in [("Prefiro o Dr. Fabrício", "Dr. Fabrício"),
                                   ("com o Tadeu", "Dr. Tadeu"),
                                   ("não quero o Tadeu", "Dr. Fabrício"),
                                   ("tanto faz", "Sem preferência"),
                                   ("os dois", "Sem preferência"),
                                   ("não", "Sem preferência")]:
            with self.subTest(resposta=resposta):
                f = fp.nova("1")
                self.assertTrue(fp.capturar_resposta(f, "medico", resposta))
                self.assertEqual(f["medico"], esperado)
        self.assertFalse(fp.capturar_resposta(fp.nova("1"), "medico", "quero marcar logo"))
        ficha, saidas = conversa(self.CONVERSA[:3])
        self.assertIn(fp.PERGUNTAS["medico"], saidas[2][2])
        for resposta, nomes in [("Dr. Tadeu", "🥼 Dr. Tadeu\n"), ("tanto faz", f"🥼 {clinica.MEDICOS}\n")]:
            ficha, saidas = conversa(self.CONVERSA[:2] + ["Preciso tirar o siso", resposta]
                                     + self.CONVERSA[4:])
            self.assertIn(nomes, saidas[-1][2])
        self.assertIn("🥼 Dr. Tadeu\n📌", clinica.cartao_consulta_agendada("2026-08-02T15:00", preferencia="Dr. Tadeu"))

    def test_resumo_vai_numa_mensagem_so(self):
        _, saidas = conversa(self.CONVERSA)
        blocos = saidas[6][2].split("\n\n")
        self.assertTrue(any(b.startswith("Confira os dados") and "• Nome completo: Maria Silva Souza" in b
                            and "• E-mail: maria@email.com" in b and "• CEP: 74000-000" in b
                            for b in blocos))

    def test_resumo_com_resposta_em_varias_linhas(self):
        ficha = fp.nova("1")
        ficha["disponibilidade"] = "Quarta feira de manhã \nQuinta feira a tarde"
        self.assertIn("• Disponibilidade: Quarta feira de manhã / Quinta feira a tarde", fp.resumo(ficha))

    def test_confirmacao_nao_se_repete(self):
        """'Certo, anotado.' saia 9 vezes iguais (teste de 02/10)."""
        _, saidas = conversa(self.CONVERSA)
        textos = [t for _, _, t in saidas]
        self.assertFalse(any("Certo, anotado." in t for t in textos))
        confirmacoes = [d.confirmacao for _, d, _ in saidas if d.confirmacao]
        self.assertGreaterEqual(len(confirmacoes), 4)
        self.assertEqual(len(confirmacoes), len(set(confirmacoes)))
        # Confirmacao e pergunta na MESMA mensagem (uma bolha so).
        self.assertIn(f"Tudo bem, Maria. {fp.PERGUNTAS['queixa']}", textos[1].split("\n\n"))

    def test_cumprimento_no_meio_e_respondido(self):
        for cumprimento in ["Boa noite", "Olá, boa noite", "oi, tudo bem?"]:
            with self.subTest(cumprimento=cumprimento):
                ficha, saidas = conversa(["Oi", cumprimento])
                self.assertTrue(saidas[1][2].startswith("Boa tarde! Qual é o seu nome?"))

    def test_menos_texto(self):
        """Pedidos do teste de 07/10: sem 'Se nao tiver, e so responder nao'."""
        _, saidas = conversa(self.CONVERSA)
        tudo = " ".join(t for _, _, t in saidas)
        self.assertNotIn("é só responder", tudo)
        self.assertNotIn("Com quem eu falo", tudo)
        self.assertNotIn("Para eu te orientar melhor", tudo)

    def test_pergunta_repetida_e_curta(self):
        # Depois do #reset o nome ja foi perguntado; "quero agendar" nao responde.
        ficha = fp.nova("1")
        ficha["saudacao_feita"] = True
        fp.marcar_pergunta(ficha, "nome")
        d = secretaria.decidir(ficha, "Gostaria de agendar uma consulta com o Doutor Fabrício", TARDE)
        self.assertEqual(secretaria.montar(d)[0], "Claro, vamos agendar a sua avaliação! Qual é o seu nome?")
        ficha, saidas = conversa(["Oi", "Ana", "kkkk"])
        self.assertIn(fp.PERGUNTAS_CURTAS["queixa"], saidas[2][2])

    def test_orientacoes_conforme_a_ficha(self):
        # Sem exames, sem indicacao e sem medicamento: nada de "leve seus exames".
        ficha, saidas = conversa(self.CONVERSA)
        self.assertNotIn("leve seus exames", saidas[-1][2])
        self.assertNotIn("Para a avaliação, leve", saidas[-1][2])
        # Exame contado pelo paciente e medicamento: as duas orientacoes.
        ficha, saidas = conversa(["Oi", "Maria Silva", "Preciso tirar o siso, tenho panorâmica", "Tanto faz",
                                  CADASTRO_OK, "terças à tarde", "uso losartana", "sim"])
        self.assertIn("Para a avaliação, leve seus exames e a lista dos medicamentos que você usa.",
                      saidas[-1][2])
        self.assertEqual(clinica.orientacoes_pre_consulta({"exames": "Não possui", "saude": "Nada relatado"}), "")

    def test_confirmacao_vem_antes_do_resumo(self):
        _, saidas = conversa(self.CONVERSA)
        blocos = saidas[6][2].split("\n\n")
        self.assertEqual(blocos[0], "Obrigada pelas informações.")
        self.assertTrue(blocos[1].startswith("Confira os dados"))

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
        # Nome e queixa ja informados: vai direto para o pre-cadastro.
        self.assertEqual(ficha["ultima_pergunta"], "medico")

    def test_nao_sei_espera_a_queixa(self):
        ficha, saidas = conversa(["Não sei qual procedimento preciso", "meu queixo é pequeno"])
        self.assertEqual(saidas[0][1].pergunta_final, "")
        self.assertIn(clinica.RESPOSTA_NAO_SEI, saidas[0][2])
        self.assertEqual(ficha["queixa"], "meu queixo é pequeno")
        self.assertEqual(ficha["area"], "mentoplastia")

    def test_queixa_de_qualquer_area_vai_ao_pre_cadastro(self):
        """Roteiro de 23/10: sem pergunta de exame; a queixa leva ao pre-cadastro."""
        for area, queixa in [("enxerto", "Não tenho osso para implante"),
                             ("ortognatica", "Minha mordida não encaixa"),
                             ("patologia", "Tenho um cisto na mandíbula"),
                             ("papada", "Tenho papada")]:
            with self.subTest(area=area):
                ficha, saidas = conversa(["Oi", "Ana", queixa])
                self.assertEqual(ficha["area"], area)
                self.assertTrue(saidas[2][2].startswith("Entendido. " + fp.PERGUNTAS["medico"]))

    def test_indicacao_do_dentista_e_reconhecida(self):
        ficha, _ = conversa(["Oi, vim por indicação do meu dentista para tirar o siso"])
        self.assertEqual(ficha["avaliacao_previa"], "Sim")

    def test_resposta_que_nao_e_nome_nao_vira_nome(self):
        ficha, _ = conversa(["Oi", "Preciso tirar o siso"])
        self.assertEqual(ficha["nome"], "")
        self.assertEqual(ficha["area"], "exodontia")

    def test_preco_no_meio_do_funil(self):
        # Sem queixa ainda: a tabela de valores por motivo, sem chutar.
        ficha, saidas = conversa(["Oi", "Ana", "Quanto custa?"])
        texto = saidas[2][2]
        self.assertIn(clinica.TABELA_VALORES, texto)
        # A queixa ja tinha sido perguntada: volta na versao curta.
        self.assertIn(fp.PERGUNTAS_CURTAS["queixa"], texto)

    def test_valor_pela_queixa(self):
        """R$ 400: ATM, apneia, ortognatica, esteticas. R$ 300: siso, enxerto,
        lesoes, biopsias. O resto recebe a tabela por motivo (23/10)."""
        for queixa, valor in [("Tenho dor na ATM", 400), ("Tenho apneia do sono", 400),
                              ("Minha mordida não encaixa", 400), ("Tenho papada", 400),
                              ("Preciso tirar o siso", 300), ("Tenho um cisto na mandíbula", 300),
                              ("Não tenho osso para implante", 300), ("dor no dente", None)]:
            with self.subTest(queixa=queixa):
                ficha, saidas = conversa(["Oi", "Ana", queixa, "quanto custa a consulta?"])
                texto = saidas[3][2]
                if valor:
                    self.assertIn(f"o valor da consulta é R$ {valor}.", texto)
                    # O cartao fica para o fim do atendimento.
                    self.assertNotIn(clinica.cartao_valor(valor), texto)
                    self.assertNotIn(clinica.TABELA_VALORES, texto)
                else:
                    self.assertIn(clinica.TABELA_VALORES, texto)

    def test_cartao_do_valor_fecha_o_atendimento_mesmo_ja_perguntado(self):
        conversa_ = self.CONVERSA[:4] + ["qual o valor?"] + self.CONVERSA[4:]
        _, saidas = conversa(conversa_)
        self.assertIn("o valor da consulta é R$ 300.", saidas[4][2])
        self.assertIn(clinica.RESPOSTA_ENCAMINHADO, saidas[-1][2])
        self.assertIn(clinica.cartao_valor(300), saidas[-1][2])

    def test_sem_valor_definido_o_encaminhamento_avisa_que_a_equipe_confirma(self):
        _, saidas = conversa(["Oi", "Ana", "dor no dente", "Tanto faz", CADASTRO_OK, "terças à tarde",
                              "não", "sim"])
        self.assertIn(clinica.RESPOSTA_VALOR_A_CONFIRMAR, saidas[-1][2])
        self.assertNotIn("R$", saidas[-1][2])

    def test_pergunta_se_e_robo_tem_resposta_verdadeira(self):
        for pergunta in ["Você é um robô?", "estou falando com uma pessoa de verdade?",
                         "é uma IA?"]:
            with self.subTest(pergunta=pergunta):
                _, saidas = conversa(["Oi", pergunta])
                self.assertIn(clinica.RESPOSTA_IDENTIDADE, saidas[1][2])

    def test_cartao_da_consulta_agendada(self):
        self.assertEqual(clinica.cartao_consulta_agendada("2026-08-02T15:00"),
                         "Sua Consulta foi agendada:\n🥼 Dr. Tadeu / Dr. Fabrício\n"
                         "📌 Dia 02/08 (Domingo)\n⏱️ 15:00 horas\n"
                         "🏥 Clínica Omnilux / Av. Lauro Sodré, 2800, Bairro Costa e Silva - "
                         "Porto Velho - RO")

    def test_correcao_no_resumo(self):
        ficha, saidas = conversa(self.CONVERSA[:-1] + ["não", "o nome é Maria Silva Souza Lima", "sim"])
        self.assertIn("corrigir", saidas[-3][2])
        self.assertIn("• Nome completo: Maria Silva Souza Lima", saidas[-2][2])
        self.assertTrue(saidas[-1][1].encaminhar)

    def test_correcao_do_cadastro_no_resumo(self):
        ficha, saidas = conversa(self.CONVERSA[:-1] + ["não", "o CPF é 123.456.789-00",
                                                       "o CPF é 111.444.777-35", "sim"])
        self.assertIn("parece ter algum número trocado", saidas[-3][2])
        self.assertEqual(ficha["cpf"], "111.444.777-35")
        self.assertIn("• CPF: 111.444.777-35", saidas[-2][2])
        self.assertTrue(saidas[-1][1].encaminhar)
        for frase, campo, valor in [("o RG é 7654321", "rg", "7654321"),
                                    ("nasci em 01/02/1991", "nascimento", "01/02/1991"),
                                    ("o endereço é Rua B, 45, Centro", "endereco", "Rua B, 45, Centro")]:
            with self.subTest(frase=frase):
                f = fp.nova("1")
                self.assertEqual(fp.aplicar_correcao(f, frase), campo)
                self.assertEqual(f[campo], valor)

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


class LeituraDoCadastro(unittest.TestCase):
    def test_com_e_sem_rotulo(self):
        for texto in [CADASTRO_OK,
                      "Maria Silva Souza, 12/03/1990, 52998224725, RG 1234567, Rua das Flores, 120, Centro, Goiânia",
                      "Nome completo: Maria Silva Souza\nData de nascimento: 12/3/90\nCPF: 529.982.247-25\n"
                      "RG: 1234567\nEndereço: Rua das Flores, 120, Centro, Goiânia"]:
            with self.subTest(texto=texto[:30]):
                dados = fp.extrair_cadastro(texto)
                self.assertEqual(dados["nome_completo"], "Maria Silva Souza")
                self.assertEqual(dados["nascimento"], "12/03/1990")
                self.assertEqual(dados["cpf"], "529.982.247-25")
                self.assertEqual(dados["rg"], "1234567")
                self.assertEqual(dados["endereco"], "Rua das Flores, 120, Centro, Goiânia")

    def test_cpf_invalido_nao_vira_rg(self):
        dados = fp.extrair_cadastro("123.456.789-00")
        self.assertNotIn("cpf", dados)
        self.assertNotIn("rg", dados)
        self.assertIn("_aviso", dados)

    def test_endereco_sozinho_nao_vira_nome(self):
        self.assertEqual(fp.extrair_cadastro("Rio Madeira, 15 - Centro", campo_esperado="endereco"),
                         {"endereco": "Rio Madeira, 15 - Centro"})

    def test_cpf_valido(self):
        self.assertTrue(fp.cpf_valido("52998224725"))
        self.assertFalse(fp.cpf_valido("12345678900"))
        self.assertFalse(fp.cpf_valido("11111111111"))

    def test_queixa_sem_nome(self):
        self.assertEqual(fp.limpar_queixa("Me chamo José\nMinha principal queixa é o queixo."),
                         "Minha principal queixa é o queixo.")


class RespostasForaDoEsperado(unittest.TestCase):
    """Respostas que nao seguem o roteiro (bateria de 03/10). Nenhuma vai para a IA."""

    BASE = ["Oi", "Pedro", "Preciso extrair um dente", "Tanto faz"]
    ATE = {
        "nome": ["Oi"],
        "queixa": ["Oi", "Pedro"],
        "cadastro": BASE,
        "disponibilidade": BASE + [CADASTRO_OK],
        "saude": BASE + [CADASTRO_OK, "manhã"],
    }

    def responder(self, campo, resposta):
        ficha, saidas = conversa(self.ATE[campo] + [resposta])
        d, texto = saidas[-1][1], saidas[-1][2]
        self.assertFalse(d.usar_llm, f"{resposta!r} foi para a IA")
        return ficha, texto

    def test_nomes(self):
        casos = {"Pedro 😊": "Pedro", "pode me chamar de Bia": "Bia", "Dr. Carlos": "Carlos",
                 "joao pedro da silva santos": "Joao Pedro da Silva Santos",
                 "Ana Paula, tudo bem?": "Ana Paula", "é a Maria aqui": "Maria", "sou eu": ""}
        for resposta, nome in casos.items():
            with self.subTest(resposta=resposta):
                self.assertEqual(self.responder("nome", resposta)[0]["nome"], nome)

    def test_tudo_bem_junto_do_nome_e_respondido(self):
        self.assertIn("Tudo ótimo por aqui.", self.responder("nome", "Ana Paula, tudo bem?")[1])

    def test_sem_conteudo_nao_vira_resposta(self):
        for resposta in ["kkkk", "obrigado", "?", "tem alguém aí?", "bom dia", "pq?"]:
            with self.subTest(resposta=resposta):
                ficha, texto = self.responder("disponibilidade", resposta)
                self.assertEqual(ficha["disponibilidade"], "")
                self.assertIn("dias e horários", texto)

    def test_sem_conteudo_no_cadastro(self):
        for resposta in ["kkkk", "pq?", "?"]:
            with self.subTest(resposta=resposta):
                ficha, texto = self.responder("cadastro", resposta)
                self.assertEqual(ficha["nome_completo"], "")
                self.assertIn("CPF", texto)

    def test_negativas_e_nao_sei(self):
        self.assertEqual(self.responder("saude", "não")[0]["saude"], "Nada relatado")
        self.assertEqual(self.responder("saude", "não sei")[0]["saude"], "Não sabe informar")

    def test_confirmacao_combina_com_a_resposta(self):
        self.assertTrue(self.responder("saude", "não")[1].startswith("Obrigada pelas informações."))
        self.assertTrue(self.responder("disponibilidade", "manhã")[1].startswith("Certo. Por último:"))

    def test_remedio_citado_na_saude_nao_e_pedido(self):
        ficha, texto = self.responder("saude", "sou alérgica a dipirona")
        self.assertNotIn(clinica.RESPOSTA_MEDICAMENTO, texto)
        self.assertEqual(ficha["saude"], "sou alérgica a dipirona")
        self.assertIn("medicamento", [t for t, _ in clinica.respostas_travadas("posso tomar dipirona?")])

    def test_queixa_que_nao_e_queixa(self):
        ficha, texto = self.responder("queixa", "é pra minha filha")
        self.assertEqual((ficha["queixa"], ficha["para_quem"]), ("", "filha"))
        self.assertIn("para a sua filha", texto)
        ficha, texto = self.responder("queixa", "quero fazer uma avaliação")
        self.assertEqual(ficha["queixa"], "")
        self.assertTrue(texto.startswith("Claro, vamos agendar a sua avaliação!"))
        ficha, texto = self.responder("queixa", "nada, só queria saber")
        self.assertEqual(ficha["ultima_pergunta"], "")

    def test_grafia_errada_do_siso(self):
        for resposta in ["PRESISO TIRAR O SIZO", "qro tirar o ciso"]:
            with self.subTest(resposta=resposta):
                self.assertEqual(self.responder("queixa", resposta)[0]["area"], "exodontia")

    def test_confirmacao_do_resumo(self):
        for resposta in ["👍", "certinho", "isso", "ok", "aham"]:
            with self.subTest(resposta=resposta):
                ficha, saidas = conversa(self.ATE["saude"] + ["não", resposta])
                self.assertTrue(saidas[-1][1].encaminhar)

    def test_fim_de_semana_com_consultorio_fechado(self):
        import os
        os.environ["CLINICA_HORARIO"] = "SEG - SEX (08:00 - 18:00) SAB E DOM. FECHADO"
        try:
            ficha, texto = self.responder("disponibilidade", "só sábado")
            self.assertEqual(ficha["disponibilidade"], "")
            self.assertIn("segunda a sexta", texto)
            self.assertEqual(self.responder("disponibilidade", "sábado ou quarta")[0]["disponibilidade"],
                             "sábado ou quarta")
        finally:
            del os.environ["CLINICA_HORARIO"]


class TesteDoDoutor1210(unittest.TestCase):
    """Teste do Dr. Fabricio em 12/10: "Alguns dados repetidos" e "alguns dados
    ela deixa passar: não passei o endereço"."""

    COLADO = ("Ótimo, leve no dia da avaliação. Agora vou precisar de alguns dados para fazer o "
              "seu cadastro. Pode me enviar:\n• Nome completo: Fabiana Lúcia Souza \n"
              "• Data de nascimento: 15/04/1985\n• CPF: 11144477735\n• RG: 445566\n"
              "• Endereço completo (rua, número, bairro e cidade)")
    INICIO = ["Bom dia\nGostaria de agendar uma consulta com o dr Fabricio", "Pedro Augusto",
              "Perdi um dente e me disseram que preciso colocar um implante e prótese", "Tanto faz", "Sim"]

    def test_lista_copiada_le_os_dados_e_nao_inventa_endereco(self):
        d = fp.extrair_cadastro(self.COLADO, "nome_completo")
        self.assertEqual(d, {"nome_completo": "Fabiana Lúcia Souza", "nascimento": "15/04/1985",
                             "cpf": "111.444.777-35", "rg": "445566"})

    def test_pede_so_o_endereco_que_faltou(self):
        os.environ["CLINICA_ENDERECO"] = "Av. Lauro Sodré, 2800"
        try:
            ficha, saidas = conversa(self.INICIO + [self.COLADO])
        finally:
            del os.environ["CLINICA_ENDERECO"]
        texto = saidas[-1][2]
        self.assertNotIn("Lauro Sodré", texto)            # nao responde o endereco do consultorio
        self.assertNotIn("nome completo", texto.lower())   # o nome ja veio
        self.assertIn("• E-mail\n• Endereço com CEP", texto)  # so o que faltou
        self.assertEqual(ficha["endereco"], "")
        ficha, saidas = conversa(["fabiana@email.com\nRua Jatuarana, 1500, Nova Floresta, Porto Velho, "
                                  "CEP 76820-000"], ficha)
        self.assertEqual(ficha["endereco"], "Rua Jatuarana, 1500, Nova Floresta, Porto Velho")
        self.assertEqual(ficha["cep"], "76820-000")
        self.assertIn("Cadastro completo", saidas[-1][2])

    def test_resumo_sem_nome_repetido_e_detalhe_com_assunto(self):
        f = fp.nova("1")
        f.update(nome="Moacyr Tadeu", nome_completo="Moacyr Tadeu", area="ortognatica",
                 detalhe_area="Já uso")
        r = fp.resumo(f)
        self.assertNotIn("• Nome: ", r)
        self.assertIn("• Nome completo: Moacyr Tadeu", r)
        self.assertIn("• Aparelho ortodôntico: Já uso", r)

    def test_saude_sem_o_sim_na_frente(self):
        f = fp.nova("1")
        fp.capturar_resposta(f, "saude", "Sim\nHipertensão \nUso almesartana")
        self.assertEqual(f["saude"], "Hipertensão \nUso almesartana")

    def test_faltando_endereco_no_resumo_pede_o_endereco(self):
        for frases in (["Não\nEstá faltando meu endereço"], ["Não", "Adicionar meu endereço"]):
            with self.subTest(frases=frases):
                ficha, saidas = conversa(Fluxo.CONVERSA[:-1] + frases)
                self.assertEqual(saidas[-1][2], fp.PERGUNTAS["endereco"])
                ficha, saidas = conversa(["Rua B, 22, Centro, Porto Velho", "sim"], ficha)
                self.assertEqual(ficha["endereco"], "Rua B, 22, Centro, Porto Velho")
                self.assertIn("• Endereço: Rua B, 22, Centro, Porto Velho", saidas[0][2])
                self.assertNotIn("Observações", saidas[0][2])
                self.assertTrue(saidas[1][1].encaminhar)

    def test_sem_oscilacao(self):
        msgs = self.INICIO + [self.COLADO, "Rua Jatuarana, 1500, Centro, Porto Velho", "Terça à tarde",
                              "Primeira consulta", "Sim\nHipertensão", "Não\nEstá faltando meu endereço",
                              "Rua B, 22, Centro, Porto Velho", "Sim"]
        primeira = [s[2] for s in conversa(msgs)[1]]
        for _ in range(10):
            self.assertEqual([s[2] for s in conversa(msgs)[1]], primeira)


class TestFichaComBancoFora(unittest.TestCase):
    """Teste de 21/10: banco oscilando nao pode virar ficha vazia gravada por cima."""

    def setUp(self):
        import database
        self.database = database
        self.originais = (database.get_conversation_state, database.save_conversation_state,
                          fp._ESPERAS_BANCO)
        fp._ESPERAS_BANCO = (0,)

    def tearDown(self):
        (self.database.get_conversation_state, self.database.save_conversation_state,
         fp._ESPERAS_BANCO) = self.originais

    def _banco_fora(self, *a, **k):
        raise ConnectionError("Banco ocupado")

    def test_leitura_estrita_sobe_erro(self):
        self.database.get_conversation_state = self._banco_fora
        with self.assertRaises(fp.FichaIndisponivel):
            fp.load("5562999999999", estrito=True)

    def test_gravacao_estrita_sobe_erro(self):
        self.database.save_conversation_state = self._banco_fora
        with self.assertRaises(fp.FichaIndisponivel):
            fp.save("5562999999999", fp.nova("5562999999999"), estrito=True)

    def test_leitura_tenta_de_novo(self):
        chamadas = []
        def instavel(phone):
            chamadas.append(phone)
            if len(chamadas) == 1:
                raise ConnectionError("caiu")
            return {"ficha": {"queixa": "Sou classe iii"}}
        self.database.get_conversation_state = instavel
        self.assertEqual(fp.load("5562999999999", estrito=True)["queixa"], "Sou classe iii")
        self.assertEqual(len(chamadas), 2)

    def test_endereco_com_texto_do_pedido_vale_como_vazio(self):
        self.database.get_conversation_state = lambda phone: {"ficha": {
            "endereco": "rua, número, bairro e cidade)", "cpf": "111.444.777-35"}}
        ficha = fp.load("5562999999999")
        self.assertEqual(ficha["endereco"], "")
        self.assertEqual(ficha["cpf"], "111.444.777-35")


class RetornoComConsulta(unittest.TestCase):
    """O agente retomou a conversa e o paciente tem consulta em andamento."""

    def ficha(self, situacao="marcada", inicio="2026-10-08T09:00", saudou=False):
        f = fp.nova("5562999999999")
        f.update(nome="Ana", cpf="111.444.777-35", status="retorno", saudacao_feita=saudou,
                 consulta={"situacao": situacao, "inicio": inicio if situacao == "marcada" else ""})
        return f

    def responder(self, ficha, texto):
        d = secretaria.decidir(ficha, texto, TARDE)
        return d, secretaria.montar(d, "")[0]

    def test_consulta_marcada_cumprimenta_e_conta_o_dia(self):
        d, texto = self.responder(self.ficha(), "Oi, boa tarde")
        self.assertIn("confirmada para quinta-feira, 08/10, às 09h00", texto)
        self.assertTrue(texto.startswith("Boa tarde"))
        self.assertNotIn("queixa", d.tipos)
        self.assertFalse(d.transferir)

    def test_pedido_pendente_diz_que_esta_com_a_equipe(self):
        _, texto = self.responder(self.ficha("pendente"), "Oi")
        self.assertIn("Seu pedido de agendamento está com a equipe", texto)

    def test_remarcar_vai_para_a_equipe(self):
        d, texto = self.responder(self.ficha(saudou=True), "Preciso remarcar, não vou poder ir")
        self.assertIn("retorno:mudar_consulta", d.tipos)
        self.assertIn("08/10", d.transferir)
        self.assertIn("cuida da agenda", texto)

    def test_pergunta_do_dia_responde_a_situacao(self):
        ficha = self.ficha(saudou=True)
        self.responder(ficha, "oi")
        d, texto = self.responder(ficha, "que dia é minha consulta?")
        self.assertIn("08/10", texto)
        self.assertFalse(d.usar_llm)

    def test_duvida_vai_para_o_modelo_sem_reabrir_o_funil(self):
        ficha = self.ficha(saudou=True)
        self.responder(ficha, "oi")
        d, _ = self.responder(ficha, "Preciso levar algum exame no dia?")
        self.assertTrue(d.usar_llm)
        self.assertEqual(ficha["status"], "retorno")
        self.assertEqual(ficha["ultima_pergunta"], "")

    def test_outra_consulta_reabre_o_funil_com_o_cadastro(self):
        ficha = self.ficha(saudou=True)
        d, _ = self.responder(ficha, "Quero marcar outra consulta")
        self.assertIn("retorno:novo_atendimento", d.tipos)
        self.assertEqual(ficha["status"], "coletando")
        self.assertEqual(ficha["cpf"], "111.444.777-35")

    def test_sem_consulta_volta_ao_atendimento_normal(self):
        ficha = self.ficha(saudou=True)
        ficha["consulta"] = {}
        d, _ = self.responder(ficha, "Oi, queria saber sobre implante")
        self.assertIn("retorno:novo_atendimento", d.tipos)
        self.assertEqual(ficha["status"], "coletando")


if __name__ == "__main__":
    unittest.main()
