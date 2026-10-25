# Código e arquitetura

## Stack real

Python 3 (verificado em 3.14.7) com Flask 3.1, Flask-Limiter 4.1, psycopg2-binary 2.9 (pool), pgvector, openai 3.x, APScheduler, pypdf, python-docx e cryptography (cifra do token do Google). Versões mínimas em `requirements.txt` (`requirements.lock` como referência; ver `docs/setup.md`). Banco: Supabase PostgreSQL com pgvector (projeto `agentedoctor`, São Paulo). SQLite só para desenvolvimento offline e rollback. Hospedagem: Render, com deploy automático a cada push na `main`. WhatsApp: Datafy (API compatível com a Meta Cloud API).

## Mapa do código

Todos os módulos ficam na raiz (estrutura plana, sem pacote).

| Arquivo | Responsabilidade |
|---|---|
| `app.py` | Webhook `/webhook`, pipeline do agente, rotas do painel `/api/...`, SSE, inicialização |
| `clinica.py` | Base de conhecimento travada em código: respostas, matriz de triagem, emergência, conferência da saída do modelo |
| `secretaria.py` | Decide cada resposta do fluxo (`decidir`, `montar`) |
| `ficha_paciente.py` | Ficha estruturada do paciente (funil, cadastro, validação de CPF), persistida em `conversation_states` |
| `llm.py`, `memory.py` | Cliente OpenAI (tool calling) e histórico em memória |
| `knowledge_rag.py`, `ingest_knowledge.py`, `knowledge_repair.py`, `documentos.py` | RAG: chunking, embeddings, busca, ingestão e extração de PDF/DOCX |
| `database.py`, `db.py` | Camada de dados do painel/CRM e abstração SQLite/PostgreSQL com pool |
| `meta.py` | Cliente da API de WhatsApp (AutoZap): envio, mídia, modelos, perfil comercial, indicador de digitando |
| `google_agenda.py`, `horarios.py` | Google Calendar (OAuth, opcional) e vagas livres |
| `scheduler.py` | APScheduler: follow-ups e automações do CRM |
| `buffer.py`, `events.py`, `auth.py` | Debounce por usuário, SSE e login do painel |
| `prompts/secretaria.md`, `knowledge/` | Prompt do modelo e Base de Conhecimento oficial (lidos em runtime) |
| `static/`, `templates/` | Painel (JS/CSS sem build, HTML Jinja) |
| `test_*.py`, `verify.py` | Testes e verificação (`docs/quality.md`) |

## Fronteiras e fluxo

`API de WhatsApp → /webhook (evento `message.received`, assinatura HMAC `X-Webhook-Signature`) → MessageBuffer → handle_flush → secretaria.decidir (código) → [dúvida aberta: knowledge_rag + llm → clinica.conferir_resposta] → meta.send_text`. A ficha e o histórico vão ao banco a cada passo. Quem faz as perguntas do funil é o código; o modelo nunca decide o fluxo nem informa preço. O painel (`login_required`) lê e escreve pelas rotas `/api/...` e recebe atualizações por SSE (`events.py`).

Pontos de confiança: (1) webhook externo, exige assinatura com `WHATSAPI_WEBHOOK_SECRET` (`WEBHOOK_EXIGE_ASSINATURA=0` desliga); (2) painel, sessão Flask com `SECRET_KEY` sem padrão; (3) texto do paciente, que chega ao modelo e é conferido na saída; (4) arquivos enviados ao knowledge.

## Dados e migrações

Tabelas criadas por `database.init_db()` ao subir: `contacts`, `conversations`, `messages`, `conversation_states` (ficha), `agendamentos`, `knowledge`, `knowledge_files`, `settings` (inclui respostas abertas em cache `resposta_aberta:*`), `tags`, `contact_tags`, `conversation_tags`, `tasks`, `templates`, `crm_automations`, `crm_follow_ups`, `crm_logs`. Não há ferramenta de migração: mudanças de esquema são `CREATE/ALTER ... IF NOT EXISTS` em `init_db()`, aplicadas quando o app sobe (isto é, no deploy). Todas as tabelas têm RLS ativo sem políticas; o app conecta como `postgres`. Pool: `ThreadedConnectionPool(DB_POOL_MIN=6, DB_POOL_MAX=12)` com `SELECT 1` a cada 45 s para manter as conexões abertas. Regras de SQL: parâmetros sempre (`?`/`%s`), nunca concatenar entrada do usuário.

## Decisões

| Decisão | Motivo | Rever quando |
|---|---|---|
| Resposta clínica travada em código | O doutor exige zero oscilação; temperatura 0 não bastou (2026-10-01) | Nunca para preço/diagnóstico |
| Cache de resposta aberta no banco | Mesma pergunta, mesmo texto, sem nova chamada | Edição da base ou do prompt (já renova) |
| `DB_POOL_MIN=6` + keepalive | Cada consulta além de `minconn` abria conexão a ~1,5 s (2026-10-23) | Troca de região ou plano do Supabase |
| Estrutura plana, `app.py` com ~3,6 mil linhas | Herdado; ainda funciona | Ver dívida em `docs/setup.md` (dividir por rotas com Blueprints) |
| Sem ORM nem migrações versionadas | Esquema pequeno, uma instância | Segundo ambiente ou mudança destrutiva |
| Sem Node/build | Painel em JS puro | Se o painel passar a precisar de bundler |

## Manutenção

Atualize este mapa quando um módulo nascer, mudar de responsabilidade ou uma fronteira mudar. Remova decisões que deixaram de valer.
