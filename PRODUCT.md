# Secretária virtual do Dr. Fabrício Guimarães

## Problema e objetivo

O consultório de cirurgia bucomaxilofacial recebe pacientes pelo WhatsApp. A secretária virtual faz o atendimento inicial: entende a queixa, tira dúvidas básicas sem dar diagnóstico, colhe o pré-cadastro, a disponibilidade e a saúde do paciente, e entrega o pedido de avaliação pronto para a equipe confirmar. O painel permite à equipe acompanhar conversas, assumir a fila humana e confirmar horários.

## Público e papéis

- **Paciente** (WhatsApp): conversa com o agente. Não tem login.
- **Equipe do consultório** (painel web, login único `ADMIN_USER`/`ADMIN_PASSWORD`): conversas, fila humana, agendamentos, agenda, horários, contatos, tarefas, knowledge e automações. Não há perfis diferentes de acesso.
- **Dr. Fabrício**: dono do conteúdo clínico (a Base de Conhecimento) e do roteiro do atendimento. Quando ele e o responsável pelo projeto divergem, vale o doutor.

## Fluxos críticos (implementados)

1. **Atendimento**: nome → motivo da consulta → preferência de médico (Dr. Fabrício, Dr. Tadeu ou sem preferência; pedido do doutor em 24/10) → pré-cadastro (nome completo, nascimento, CPF, RG, e-mail, endereço com CEP) → dias e horários → saúde → resumo → confirmação → cartão de valor. A ordem fica em `ficha_paciente.ORDEM`.
2. **Dúvida aberta**: resposta travada em código quando existe; senão, modelo + RAG, com a saída conferida por `clinica.conferir_resposta()`.
3. **Emergência**: sinais de urgência recebem a orientação de pronto-socorro/SAMU (192) e a conversa vai para a equipe.
4. **Fila humana**: pedido de atendente, remarcar ou cancelar transfere para a equipe; o agente fica calado enquanto a equipe atende.
5. **Agendamento**: pedido confirmado pelo paciente vira pendente em Agendamentos; a equipe confirma o horário, o paciente é avisado e o evento vai para a Agenda (e para o Google Calendar, se conectado).

## Regras de negócio e de segurança

- O agente **nunca** fecha diagnóstico, indica procedimento, interpreta exame, promete resultado, prescreve nem inventa informação. Preço só nos casos definidos pelo doutor (`TABELA_VALORES`); fora deles, "a equipe confirma".
- Respostas que não podem oscilar ficam **travadas em código**, não no modelo.
- Foto e documento do paciente **não vão ao modelo**.
- Dado de paciente é dado de saúde (LGPD): nenhum dado real em teste, log, commit ou grafo. O repositório é **público**.
- Testes nunca tocam o banco de produção.

## Fora do escopo

Prontuário, cobrança, convênios, agenda separada por médico ou múltiplas clínicas (a preferência só muda o nome nos cartões; o valor depende do motivo), perfis de acesso, app mobile. O CRM é só automação de mensagens (lembretes e marketing). Não reintroduzir tempo de queixa, cidade, indicação, exames nem primeira consulta/retorno no funil sem pedido do doutor.

## Restrições e decisões técnicas

Python 3 + Flask, Supabase (PostgreSQL + pgvector) como banco, OpenAI para as dúvidas abertas e embeddings, API própria de WhatsApp (AutoZap) e Render para hospedagem. Detalhes e motivos em [docs/architecture.md](docs/architecture.md). Origem: o projeto nasceu como cópia de um bot de loja; nada da loja deve ser reutilizado (credenciais, banco, WhatsApp).

## Suposições e decisões pendentes

- Os dados do consultório (`CLINICA_*`, `AGENTE_NOME`) são preenchidos no Render pela equipe; vazios, o agente diz que a equipe confirma.
- Pendências abertas e riscos conhecidos: [docs/setup.md](docs/setup.md).

## Critérios de aceite

- A mesma conversa sempre gera as mesmas respostas (teste de não oscilação em `test_secretaria.py`).
- Cada resposta clínica bate com a Base de Conhecimento.
- Nenhum diagnóstico, preço fora da tabela, remédio ou promessa passa pela conferência.
- O pedido confirmado chega a Agendamentos com a ficha completa.
- `python verify.py` passa (sintaxe, pyflakes, segredos, testes).

## Manutenção

Atualize este arquivo quando objetivo, escopo, fluxo ou critérios mudarem. O roteiro vigente do doutor é a fonte do funil; registre a data de cada mudança aqui.
