# Secretária virtual — Dr. Fabrício Guimarães

## Produto e stack

- Produto e escopo: `PRODUCT.md`. Arquitetura: `docs/architecture.md`. Setup e evidências: `docs/setup.md`.
- Stack: Python 3 (testado em 3.14) + Flask, Supabase PostgreSQL/pgvector (SQLite só offline), OpenAI, API própria de WhatsApp (AutoZap), Render. Gerenciador: `pip` + `requirements.txt`; venv em `.venv`. Sem Node, sem build.
- Repositório **público**. Dado de paciente é dado de saúde: só dados fictícios em teste, log e doc.

## Comandos canônicos

- Instalar: `python -m venv .venv` e `.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt`
- Logs: nunca imprimir telefone inteiro nem texto do paciente; use `clinica.mascarar_fone()`.
- Rodar: `python app.py` (painel em `http://localhost:5000/panel`; precisa de `.env`)
- Testes: `python verify.py --testes` (SQLite temporário, sem rede, com a trava contra produção). Um módulo: `python -m unittest test_secretaria` só é seguro porque esse teste não abre conexão; não rode script novo que importe `app`/`db`/`database` fora do `verify.py`.
- Lint: `python -m pyflakes *.py`
- Verificação completa: `python verify.py` (sintaxe, pyflakes, segredos nos arquivos versionados, testes com a trava contra produção)
- Build/tipos: indisponíveis (sem type checker adotado; ver `docs/quality.md`)

## Regras que não mudam

- **Teste nunca em produção.** `app.py`, `db.py` e outros fazem `load_dotenv(override=True)` no import: `DB_DRIVER=sqlite` no ambiente é sobrescrito pelo `.env` e o teste grava no Supabase real. Use `verify.py --testes` ou repita a trava (`docs/quality.md`).
- **Resposta que oscila vira código.** Trave em `clinica.py`/`secretaria.py`; o modelo só responde dúvida aberta e passa por `clinica.conferir_resposta()`. Gaste o mínimo de OpenAI nos testes.
- O funil do atendimento é a ordem do doutor (`ficha_paciente.ORDEM`). Não acrescente pergunta nem invente preço sem pedido dele.
- Segredos só no `.env` local e no painel do Render. Nenhum valor padrão para `SECRET_KEY`/`ADMIN_PASSWORD`. Nada da loja original.
- Deploy = `git push` na `main` (o Render publica sozinho). **Só com pedido explícito**; confira que o remote é `edusene/agentedoctor`.
- Lentidão: peça as linhas `[tempo]` do log do Render antes de mexer; já foi o pool do banco, nunca a lógica.

## Acordos de trabalho

- Leia as instruções e o código relevante antes de editar; separe observação, suposição e evidência.
- Menor mudança completa; reaproveite o que existe. Bug: reproduza e deixe teste de regressão.
- Atualize o documento responsável junto com a mudança (comando, esquema, fronteira, configuração).
- Continue o trabalho autorizado; bloqueio parcial só trava o que depende dele. Publicar, enviar mensagem a terceiros, gastar dinheiro e ações destrutivas exigem autorização. Instalar ferramenta não autoriza.
- Trabalho em várias sessões: handoff curto no registro da tarefa (objetivo, estado verificado, pendência, próximo passo); ao retomar, confira checkout, arquivos e processos antes de confiar nele.
- Revisão independente para mudança não trivial, com escopo pelo risco; delegue só com ganho de isolamento ou paralelismo, um escritor por arquivo.

## Ferramentas (estado real em `docs/setup.md`)

- **Context7**: consulte documentação atual de bibliotecas (Flask, psycopg2, OpenAI SDK, APScheduler); nunca envie segredo ou código privado.
- **Graphify**: `graphify-out/graph.json` (só código, sem LLM) responde "quem chama X". Regenere após mudança grande: `GRAPHIFY_NO_AUTO_REFRESH=1 graphify extract . --code-only --no-cluster`. Confirme no código o que importar; sem hook de Git.
- **Superpowers / Ponytail / Caveman**: processo proporcional, menor mudança completa, conversa concisa; código, docs e commits em linguagem normal.
- **Skill `supabase-postgres-best-practices`**: carregue antes de mexer em esquema, SQL, RLS ou pgvector (quando instalada; ver `docs/setup.md`).
- **Revisão de segurança**: prompt em `docs/prompts/security-review.md`; relatório fora do repositório.

## Documentos

`PRODUCT.md` escopo · `docs/architecture.md` estrutura · `docs/onboarding.md` preparo local · `docs/quality.md` verificações e segurança · `docs/design.md` painel · `docs/setup.md` toolkit e evidências · `README.md` visão geral e operação · `SUPABASE_MIGRATION.md` migração SQLite↔Supabase.
