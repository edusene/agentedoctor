# Setup e evidências

## Fonte e contexto

- Data: 2026-10-23. Toolkit: `soumatheusgomes/vibe-coding-toolkit` revisão `790a895304e0c08b70a5b215c9d334f1c86b816c` (2026-10-18), clonada em diretório temporário fora do projeto; todos os guias e modelos vêm dessa revisão. Atualização: repetir o prompt `docs/prompts/12-existing-project-setup.md` do toolkit; ele preserva o que já existe.
- Cliente: Claude Code, Windows 11, shell bash/PowerShell, Python 3.14.7, Node 22+ (só para o avaliador do toolkit). Modelo principal preservado; subagentes: revisão de segurança com Opus (risco alto, só leitura) e smoke de contexto limpo com Haiku (leitura simples).
- Context7: consultado só como plugin ativo; nenhuma consulta de biblioteca foi necessária (nenhuma API foi alterada).

## Decisões

- O toolkit mira Next.js/TypeScript. Aqui ele foi **adaptado** a Python/Flask: sem ESLint, Drizzle, Next, shadcn nem Vercel skills. Equivalentes: `pyflakes` + `verify.py` (qualidade), SQL parametrizado e RLS já existentes (dados).
- Documentos: `PRODUCT.md`, `AGENTS.md`, `CLAUDE.md` (importa `AGENTS.md`), `docs/{architecture,design,onboarding,quality,setup}.md` criados. `README.md` preservado como documento operacional canônico (só ganhou links). `SUPABASE_MIGRATION.md` mantido. Nada competindo com o existente.
- Sem migração de stack, sem mudança de banco, sem push, sem hooks de Git, sem agendamentos.
- F2 (webhook sem segredo) virou recusa obrigatória por pedido do responsável; ver o risco de deploy na seção de segurança.

## Componentes

| Componente | Ação e motivo | Escopo | Estado e evidência |
|---|---|---|---|
| Superpowers | Reuso (plugin 7.0.0); brainstorming invocado, usuário dispensou perguntas | Usuário | Validado: skill carregada nesta sessão |
| Subagentes | Usados com critério: review de segurança (Opus) e smoke (Haiku) | Sessão | Validado: ambos retornaram; escritor único, revisores só leitura |
| RTK | Reuso: 1.0.1 instalado globalmente (`~/.local/bin/rtk`), instruções em `~/.claude/RTK.md` importadas pelo CLAUDE.md global, hook no `settings.json` do usuário. Não duplicado no projeto | Usuário | Configurado e carregado; saída condensada observada nesta sessão. Para saída original: `rtk bypass <cmd>` |
| Ponytail | Reuso (plugin, `full`) | Usuário | Validado: hook de sessão ativo |
| Caveman | Reuso (plugin) | Usuário | Validado: hook ativo. Docs e código em linguagem normal |
| ESLint/Biome | Inapplicável (sem JS/TS na aplicação) | — | `static/app.js` validado com `node --check`; pyflakes cobre o Python |
| Graphify | CLI global 0.9.95 reutilizada; `.graphifyignore` criado; grafo só de código | Projeto (`graphify-out/`, ignorado no git) | Validado: 25 arquivos de código, 1329 nós, 3434 arestas, sem clusters; consulta `query` respondeu; varredura de segredos no `graph.json`: 0. Docs (`*.md`) fora (modo sem LLM). Regenerar com o comando do `AGENTS.md` |
| Obsidian | Inapplicável (sem necessidade nem destino autorizado) | — | — |
| Memória do Claude | Reuso: memória nativa do projeto (`~/.claude/projects/.../memory/`, índice `MEMORY.md`, 7 entradas + 1 nova) | Usuário | Validado: carregada no início da sessão. Fatos duráveis no repo ficam em `AGENTS.md`/docs |
| Hooks do cliente | Não adotados (nenhuma necessidade; evita interceptadores duplicados) | — | — |
| agent-browser / Chrome DevTools MCP | Não instalados. Há extensão Chrome do Claude disponível; fluxo de UI do painel **não** foi exercitado em navegador | — | Parcial: rotas e cabeçalhos testados com o cliente de teste do Flask (abaixo) |
| Context7 | Reuso do plugin (MCP) | Usuário | Configurado e carregado; sem consulta real nesta rodada. Não duplicado em `.mcp.json` |
| Anthropic skills / skill-creator / extras | Disponíveis globalmente; nenhuma necessidade do projeto | Usuário | Não instalados no projeto, por decisão |
| Vercel skills / find-skills | Inapplicável (não é React/Next) | — | — |
| next-dev-loop, next-bundle-optimizer | Inapplicável (sem Next.js) | — | — |
| supabase-postgres-best-practices | Reuso: skill descoberta pelo cliente nesta sessão; roteada em `AGENTS.md` | Usuário | Descoberta confirmada; **execução real não feita** (nenhuma mudança de esquema) |
| gh-fix-ci | Inapplicável agora: sem `gh` instalado e sem Codex; CI só criado | — | Bloqueado até haver `gh` autenticado e uma execução de CI |
| differential-review | Não instalada; revisão manual por subagente como alternativa explícita | — | Revisão baseline feita (abaixo) |
| shadcn | Inapplicável (sem UI de componentes) | — | — |
| Sentry MCP | Não adotado: sem serviço Sentry escolhido | — | Pendente de decisão do responsável |
| Harness2 (método nativo) | Adotado em modo nativo: procedimento em `docs/quality.md` | Projeto | Smoke abaixo. CLI oficial e benchmarks não selecionados (custo/isolamento) |
| Revisão de segurança | Prompt copiado para `docs/prompts/security-review.md` (revisão `790a895`) | Projeto | Baseline executada, relatório privado fora do repo |

## Documentação criada

PRODUCT.md, README.md (links adicionados), AGENTS.md, CLAUDE.md, docs/architecture.md, docs/design.md, docs/onboarding.md, docs/quality.md, docs/setup.md, docs/prompts/security-review.md. Sem placeholders. `design.md` registra que critérios visuais não se aplicam ao canal WhatsApp e que não houve revisão de acessibilidade do painel.

## Verificações (antes → depois)

| Item | Antes | Depois |
|---|---|---|
| Testes | 106 OK (`test_secretaria`, `test_horarios`) | 116 OK (+2 detector de segredos, +8 rotas/webhook/limites em `test_app.py`) |
| pyflakes | 8 avisos | 0 |
| Segredos nos versionados | não verificado | 0 (detector em `verify.py`, com teste) |
| `pip-audit -r requirements.txt` | não verificado | nenhuma vulnerabilidade conhecida (venv temporário) |
| `python verify.py` | inexistente | 4/4 `[ok]` |
| JS | — | `node --check static/app.js` OK |
| Boot + rotas (cliente de teste, SQLite temporário, trava ativa) | — | `/login` 200 com HSTS; `/panel` e `/api/*` sem login → 302; login errado 200; certo 302; cookie com expiração; `.env` com quebra de linha → 400; 7 logins com `X-Forwarded-For` forjado → 429 |

Recursos temporários criados e a limpar: `%TEMP%\vct-toolkit` (clone do toolkit), `%TEMP%\h2case1`, `%TEMP%\claude-scratch` (venv de auditoria, scripts), relatório em `scratchpad\security-baseline.md`. Nenhum processo ficou ativo. Produção não foi tocada.

## Memória e harness

- Memória: índice `MEMORY.md` + arquivos por fato; verificada como carregada na sessão. Cada entrada tem data; invalidar ao mudar o roteiro do doutor, o banco ou o deploy.
- Smoke (subagente novo, contexto limpo, Haiku; **não** é reinício do cliente): 5/5 corretas — comando de verificação, trava contra produção, ordem do funil (e proibição de acrescentar pergunta), push só com pedido, `[tempo]` antes de mexer em lentidão. Apontou `docs/setup.md` ausente (criado agora).
- Avaliador do toolkit em cópia descartável (`validate-harness.mjs`): baseline falha exatamente em 2 verificações esperadas (tenant cruzado e identidade inválida), 5 passam. Casos com agente sobre o fixture (correção, handoff velho, review read-only, reaplicação, conflito de recurso, bloqueio parcial, pausa/retomada): **não executados**. Nenhuma falha observada justificou um candidato de melhoria.
- Reaplicação: todos os arquivos de instrução foram criados novos, sem seções duplicadas; `.gitignore` recebeu uma linha (`graphify-out/`), idempotente se verificada antes de repetir.

## Revisão de segurança (2026-10-23, HEAD `dc15356`, estática)

Nada crítico; sem segredo ativo no histórico. Corrigido nesta entrega (testes em `test_app.py`):

- **F1** chave do rate limit usava o primeiro `X-Forwarded-For` (forjável); agora o último salto.
- **F2** webhook agora **recusa** pedido sem assinatura ou sem `DATAFY_WEBHOOK_SECRET` (a menos que `WEBHOOK_EXIGE_ASSINATURA=0`). **Antes do deploy, confirme que `DATAFY_WEBHOOK_SECRET` existe no Render**; sem ele o bot deixa de receber mensagens.
- **F3** logs: telefone mascarado (`5562...99`), texto do paciente e da transcrição fora dos logs, nome de perfil fora. As linhas `[tempo]` seguem completas.
- **F4** editor de `.env` rejeita quebra de linha. **F5** sessão de 12 h e cookie `Secure` quando `RENDER` está definido (o Render define). **F6** toast/iniciais escapados e HSTS. **F7 parcial** `MAX_CONTENT_LENGTH` 25 MB.
- **F8 parcial** teto de 12 chamadas ao modelo por número por hora (acima disso vale a resposta travada genérica; contador em memória, zera no reinício).
- **F9 parcial** token do canal Google comparado em tempo constante. `requirements.lock` criado (referência; auditado sem vulnerabilidades).

## Pendências e próxima entrega

| Item | Causa | Próxima ação |
|---|---|---|
| F2: confirmar `DATAFY_WEBHOOK_SECRET` no Render | Não há acesso ao painel do Render daqui | Conferir após o deploy: uma mensagem de teste deve chegar; se vier `Recusado` no log, definir a variável |
| F5 resto: logout por GET | Troca exige mudar painel e template | Logout POST com o JS do painel |
| F7 resto: corpo do webhook lido inteiro antes da assinatura | Teto global de 25 MB, sem teto menor no `/webhook` | `request.content_length` > 1 MB → 413 no `/webhook` |
| F8 resto: guarda de saída é lista de regex; cache `resposta_aberta:*` sem validade | Design atual | Mais padrões de preço; validade do cache |
| F9 resto: refresh token do Google em texto no banco; MIME do provedor em `data:` | Dívida | Avaliar criptografia do token; lista de MIME |
| Render instala `requirements.txt` (sem pins) | Mudar o comando de build é decisão de deploy | Trocar para `requirements.lock` no Render, se quiser versões fixas |
| Rate limit em memória por processo | Sem storage | Storage compartilhado se houver mais de um worker |
| Arquivos acima de 350 linhas (`app.py` ~3,6 mil) | Herdado | Dividir por Blueprints junto de mudanças que os toquem |
| Sem revisão de acessibilidade do painel | Não feita | Revisar com a extensão Chrome |
| `gh`, differential-review, Sentry | Instalação global ou conta | Decidir; guias 19, 20 e 22 do toolkit |
| CI nunca executado | Workflow criado | Conferir a primeira execução no GitHub após o push |

Próxima entrega útil: logout POST e teto do `/webhook`.
