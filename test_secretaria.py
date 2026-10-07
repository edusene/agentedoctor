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


CADASTRO_OK = ("Maria Silva Souza\n12/03/1990\nCPF 529.982.247-25\nRG 1234567\n"
               "Rua das Flores, 120, Centro, Goiânia")


class Fluxo(unittest.TestCase):
    """Fluxo pedido pelo Dr. Fabricio (06/10): queixa, exame, cadastro, agendamento."""

    CONVERSA = [
        "Oi",
        "Maria Silva",
        "Preciso tirar o siso",
        "o de baixo, está doendo um pouco",
        "tenho panorâmica",
        CADASTRO_OK,
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
        self.assertIn(clinica.AREAS["exodontia"]["pergunta_exames"], textos[3])
        # Depois do exame vem o cadastro, pedido de uma vez.
        self.assertIn("Agora vou precisar de alguns dados para fazer o seu cadastro", textos[4])
        for item in ("Nome completo", "Data de nascimento", "CPF", "RG", "Endereço completo"):
            self.assertIn(item, textos[4])
        self.assertIn("Cadastro completo, obrigada! Agora vamos ao agendamento.", textos[5])
        self.assertIn(fp.PERGUNTAS["disponibilidade"], textos[5])
        self.assertIn("Confira os dados da sua solicitação", textos[8])
        self.assertIn(fp.PERGUNTA_CONFIRMACAO, textos[8])
        self.assertIn(clinica.RESPOSTA_ENCAMINHADO, textos[9])
        self.assertTrue(saidas[9][1].encaminhar)

        self.assertEqual(ficha["nome"], "Maria Silva")
        self.assertEqual(ficha["nome_completo"], "Maria Silva Souza")
        self.assertEqual(ficha["nascimento"], "12/03/1990")
        self.assertEqual(ficha["cpf"], "529.982.247-25")
        self.assertEqual(ficha["rg"], "1234567")
        self.assertEqual(ficha["endereco"], "Rua das Flores, 120, Centro, Goiânia")
        self.assertEqual(ficha["tipo_consulta"], "Primeira consulta")
        self.assertEqual(ficha["saude"], "Nada relatado")
        self.assertEqual(ficha["status"], "encaminhado")

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
        self.assertIn("Agora vou precisar de alguns dados para fazer o seu cadastro", saidas[2][2])
        self.assertFalse(any(d.usar_llm for _, d, _ in saidas))

    def test_cadastro_em_partes_pede_so_o_que_falta(self):
        ficha, saidas = conversa(self.CONVERSA[:5] + [
            "Maria Silva Souza\n12/03/1990", "529.982.247-25\nRG 1234567"])
        self.assertIn("ainda preciso de", saidas[5][2])
        self.assertNotIn("Nome completo", saidas[5][2])
        self.assertIn("CPF", saidas[5][2])
        self.assertIn(fp.PERGUNTAS["endereco"], saidas[6][2])
        self.assertEqual(ficha["ultima_pergunta"], "endereco")

    def test_nao_tenho_no_cadastro_nao_apaga_o_nome(self):
        ficha, _ = conversa(self.CONVERSA[:5] + ["não tenho"])
        self.assertEqual(ficha["nome_completo"], "")
        f = fp.nova("1")
        self.assertTrue(fp.capturar_resposta(f, "rg", "não tenho RG"))
        self.assertEqual(f["rg"], fp.NAO_INFORMADO)

    def test_cpf_errado_e_avisado(self):
        ficha, saidas = conversa(self.CONVERSA[:5] + ["Maria Silva Souza, 12/03/1990, CPF 123.456.789-00"])
        self.assertEqual(ficha["cpf"], "")
        self.assertEqual(ficha["rg"], "")
        self.assertIn("CPF informado parece ter algum número trocado", saidas[-1][2])

    def test_resumo_vai_numa_mensagem_so(self):
        _, saidas = conversa(self.CONVERSA)
        blocos = saidas[8][2].split("\n\n")
        self.assertTrue(any(b.startswith("Confira os dados") and "• Nome: Maria Silva" in b for b in blocos))

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
        self.assertGreaterEqual(len(confirmacoes), 5)
        self.assertEqual(len(confirmacoes), len(set(confirmacoes)))
        # Confirmacao e pergunta na MESMA mensagem (uma bolha so).
        self.assertIn(f"Prazer, Maria! {fp.PERGUNTAS['queixa']}", textos[1].split("\n\n"))

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
        ficha, saidas = conversa(self.CONVERSA[:4] + ["não tenho"] + self.CONVERSA[5:])
        self.assertNotIn("leve seus exames", saidas[-1][2])
        self.assertNotIn("Para a avaliação, leve", saidas[-1][2])
        # Com exame e com medicamento: as duas orientacoes.
        ficha, saidas = conversa(self.CONVERSA[:-2] + ["uso losartana", "sim"])
        self.assertIn("Para a avaliação, leve seus exames e a lista dos medicamentos que você usa.",
                      saidas[-1][2])
        self.assertEqual(clinica.orientacoes_pre_consulta({"exames": "Não possui", "saude": "Nada relatado"}), "")

    def test_confirmacao_vem_antes_do_resumo(self):
        _, saidas = conversa(self.CONVERSA)
        blocos = saidas[8][2].split("\n\n")
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
        # Pronto para agendar e exame ja informado: vai direto para o cadastro.
        self.assertEqual(ficha["ultima_pergunta"], "nome_completo")

    def test_nao_sei_espera_a_queixa(self):
        ficha, saidas = conversa(["Não sei qual procedimento preciso", "meu queixo é pequeno"])
        self.assertEqual(saidas[0][1].pergunta_final, "")
        self.assertIn(clinica.RESPOSTA_NAO_SEI, saidas[0][2])
        self.assertEqual(ficha["queixa"], "meu queixo é pequeno")
        self.assertEqual(ficha["area"], "mentoplastia")

    def test_prerequisito_de_exame_por_procedimento(self):
        """Cada area pergunta o proprio exame, e depois vem o cadastro."""
        for area, queixa in [("enxerto", "Não tenho osso para implante"),
                             ("ortognatica", "Minha mordida não encaixa"),
                             ("patologia", "Tenho um cisto na mandíbula"),
                             ("papada", "Tenho papada")]:
            with self.subTest(area=area):
                ficha, saidas = conversa(["Oi", "Ana", queixa, "detalhe qualquer", "não"])
                self.assertIn(clinica.AREAS[area]["pergunta_exames"], saidas[3][2])
                self.assertIn("fazer o seu cadastro", saidas[4][2])

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
        # A queixa ja tinha sido perguntada: volta na versao curta.
        self.assertIn(fp.PERGUNTAS_CURTAS["queixa"], texto)
        self.assertNotIn("R$", texto)

    def test_correcao_no_resumo(self):
        ficha, saidas = conversa(self.CONVERSA[:-1] + ["não", "o nome é Maria Silva Souza Lima", "sim"])
        self.assertIn("corrigir", saidas[-3][2])
        self.assertIn("• Nome: Maria Silva Souza Lima", saidas[-2][2])
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

    BASE = ["Oi", "Pedro", "Preciso extrair um dente", "siso de baixo"]
    ATE = {
        "nome": ["Oi"],
        "queixa": ["Oi", "Pedro"],
        "exames": BASE,
        "cadastro": BASE + ["não tenho"],
        "disponibilidade": BASE + ["não tenho", CADASTRO_OK],
        "tipo_consulta": BASE + ["não tenho", CADASTRO_OK, "manhã"],
        "saude": BASE + ["não tenho", CADASTRO_OK, "manhã", "primeira"],
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
                ficha, texto = self.responder("exames", resposta)
                self.assertEqual(ficha["exames"], "")
                self.assertIn(clinica.AREAS["exodontia"]["pergunta_exames"], texto)

    def test_sem_conteudo_no_cadastro(self):
        for resposta in ["kkkk", "pq?", "?"]:
            with self.subTest(resposta=resposta):
                ficha, texto = self.responder("cadastro", resposta)
                self.assertEqual(ficha["nome_completo"], "")
                self.assertIn("CPF", texto)

    def test_negativas_e_nao_sei(self):
        self.assertEqual(self.responder("exames", "acho que não")[0]["exames"], "Não possui")
        self.assertEqual(self.responder("exames", "não sei")[0]["exames"], "Não sabe informar")
        self.assertTrue(self.responder("exames", "vou fazer semana que vem")[0]["exames"].startswith("Ainda não"))
        self.assertEqual(self.responder("tipo_consulta", "não sei")[0]["tipo_consulta"], "Não sabe informar")
        self.assertEqual(self.responder("tipo_consulta", "já fui aí uma vez")[0]["tipo_consulta"], "Retorno")

    def test_confirmacao_combina_com_a_resposta(self):
        self.assertIn("Sem problema", self.responder("exames", "acho que não")[1])
        self.assertIn("Ótimo, leve no dia da avaliação.", self.responder("exames", "tenho panorâmica")[1])

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


if __name__ == "__main__":
    unittest.main()
