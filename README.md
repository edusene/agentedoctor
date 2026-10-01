# Secretária virtual — Dr. Fabrício Guimarães

Agente de IA no WhatsApp que faz o atendimento inicial do consultório do
Dr. Fabrício Guimarães (cirurgia bucomaxilofacial): recebe o paciente, entende
a queixa, tira dúvidas básicas, qualifica e encaminha o agendamento da
avaliação para a equipe. Inclui o painel CRM (conversas, fila humana,
contatos, tarefas, knowledge, automações).

A fonte de tudo o que o agente diz é a **Base de Conhecimento do Agente de IA**
(`Base_de_Conhecimento_Agente_IA_Dr_Fabricio_Guimaraes.pdf`), transcrita em
[`knowledge/base_conhecimento_dr_fabricio.md`](knowledge/base_conhecimento_dr_fabricio.md).

---

## Como o agente decide o que responder

Três camadas, nesta ordem:

| Camada | Arquivo | O que faz |
|---|---|---|
| **Travas** | `clinica.py` | Respostas que **não podem oscilar**, com o texto do documento: preço (seção 15), "você faz?" (16), "não sei o que preciso" (17), "biópsia/tumor é câncer?" (3 e 11), pedido de diagnóstico, remédio, interpretação de exame, promessa de resultado, emergência (5), matriz de triagem (12) e as dúvidas frequentes de cada área (2 a 11). O modelo nem é chamado nesses casos. |
| **Fluxo** | `secretaria.py` + `ficha_paciente.py` | Segue a seção 18 (queixa → intenção → área → qualificação → avaliação → agendamento → confirmação → orientações). Coleta os dados da seção 14 um por vez, na ordem, sem repetir o que já foi respondido, e guarda tudo na ficha do paciente, persistida no banco. Quem faz as perguntas é o código. |
| **Modelo + RAG** | `app.py` → `llm.py`, `knowledge_rag.py` | Só para uma **dúvida aberta** que não tem trava. Recebe os trechos da base mais próximos da dúvida (busca por embeddings), o cartão da área provável e a ficha. A resposta dele perde as perguntas e passa por `clinica.conferir_resposta()`: qualquer diagnóstico, indicação de procedimento, preço, remédio, leitura de exame ou promessa derruba a resposta inteira, e no lugar dela entra o texto travado. A primeira resposta aprovada fica guardada no banco: a mesma pergunta recebe sempre o mesmo texto, sem nova chamada à OpenAI. Editar a base ou o prompt renova essas respostas. |

Regras que valem sempre (seção 1 e 19): não fechar diagnóstico, não indicar
procedimento, não interpretar exame, não prometer resultado, não prescrever,
não dar preço. Foto e documento enviados pelo paciente **não vão ao modelo**:
o agente registra que há exame e diz que o Dr. Fabrício avalia na consulta.

Quando o paciente confirma o resumo, o agente cria uma **tarefa** "Agendar
avaliação" no CRM com a ficha completa e passa a conversa para a **fila
humana**. Traumas entram marcados como prioridade. Sinais de emergência
recebem na hora a orientação de procurar pronto-socorro/SAMU (192), e a
conversa é transferida.

---

## Instalação

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt     # Windows
cp .env.example .env                               # e preencha
```

O banco é o **Supabase** (PostgreSQL + pgvector), projeto `wizduleefiuoeyzjgyck`
(us-east-2). Conexão pelo Transaction pooler:

```
DB_DRIVER=postgresql
DATABASE_URL=postgresql://postgres.wizduleefiuoeyzjgyck:SENHA@aws-0-us-east-2.pooler.supabase.com:6543/postgres?sslmode=require
```

A senha vai em percent-encoding se tiver caracteres especiais (`#` → `%23`,
`@` → `%40`...). Todas as tabelas têm RLS ativo sem políticas: o app conecta
como `postgres` e acessa tudo; a API pública do Supabase não lê dado nenhum.

Para desenvolvimento offline dá para usar SQLite (`DB_DRIVER=sqlite`,
`DB_PATH=secretaria.db`), com embeddings em JSON e similaridade em Python. Veja
[SUPABASE_MIGRATION.md](SUPABASE_MIGRATION.md) para migrar dados entre os dois.

**Latência:** o banco fica em Ohio (EUA). Hospede o app nos EUA (ex.: Render
em Ohio/Virgínia) para cada consulta levar poucos milissegundos; rodando no
Brasil, cada consulta custa ~180 ms.

## Base de conhecimento (RAG)

O app sobe a base para o knowledge sozinho na primeira inicialização. Para
recarregar depois de editar o `.md`, ou para subir um PDF novo:

```bash
python ingest_knowledge.py --dry-run           # mostra os chunks (1 por seção)
python ingest_knowledge.py                     # grava + gera embeddings
python ingest_knowledge.py --pdf arquivo.pdf   # extrai o texto de um PDF
```

Em PostgreSQL o script mostra o destino e só grava com `--sim`, para ninguém
gravar sem querer no banco de outro projeto.

Pelo painel (aba **Knowledge**) dá para importar `.pdf`, `.docx`, `.md` e
`.txt`, gerar embeddings, editar a base e editar o prompt da secretária
(`prompts/secretaria.md`).

## Rodando

```bash
python app.py                      # painel em http://localhost:5000/panel
python -m unittest test_secretaria -v
```

Os testes não precisam de rede nem de banco. Cobrem a matriz de triagem, as
emergências, cada resposta travada, a conferência das respostas do modelo, o
fluxo completo até o encaminhamento e a ausência de oscilação: a mesma conversa
rodada 25 vezes tem de dar exatamente as mesmas respostas.

---

## Antes de colocar em produção (seção 20 da base)

O documento manda inserir as informações reais da clínica. Enquanto estiverem
vazias, o agente responde que a equipe confirma, e **nunca inventa**:

| Variável | Exemplo |
|---|---|
| `CLINICA_ENDERECO` | `Rua X, 123 - Setor Y, Goiânia` |
| `CLINICA_HORARIO` | `segunda a sexta, das 8h às 18h` |
| `CLINICA_CONVENIOS` | `atendimento particular; emitimos recibo para reembolso` |
| `CLINICA_VALOR_AVALIACAO` | só se a política da clínica permitir informar |
| `CLINICA_ORIENTACOES` | orientações pré-consulta do consultório |
| `AGENTE_NOME` | nome da assistente, se houver |
| `TZ_OFFSET_HORAS` | `-3` (Brasília) |

Também é preciso configurar o WhatsApp do consultório (Datafy API):
`DATAFY_TOKEN`, `DATAFY_PHONE_NUMBER_ID`, `DATAFY_WABA_ID`,
`DATAFY_WEBHOOK_SECRET`, e apontar o webhook para `https://SEU-DOMINIO/webhook`.

Comandos úteis no WhatsApp: `#reset` zera o atendimento e devolve a conversa ao
agente. "Falar com atendente", "remarcar", "cancelar consulta" e parecidos
transferem direto para a equipe.

---

## Estrutura

```
app.py               webhook, pipeline do agente, rotas do painel
clinica.py           base travada em código (respostas, triagem, conferência)
secretaria.py        decide cada resposta (fluxo da seção 18)
ficha_paciente.py    memória do paciente (seção 14), persistida no banco
knowledge_rag.py     chunking, embeddings, busca semântica
documentos.py        extração de texto de PDF/DOCX
ingest_knowledge.py  sobe a base para o knowledge
prompts/secretaria.md  prompt do modelo (dúvidas abertas)
knowledge/           base de conhecimento oficial
database.py, db.py   banco (SQLite ou PostgreSQL)
meta.py              Datafy / Meta Cloud API
scheduler.py         follow-ups automáticos do CRM
```
