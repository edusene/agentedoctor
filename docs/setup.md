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
| RTK | Reuso: 1.0.1 instalado globalmente, instruções em `~/.claude/RTK.md` importadas pelo CLAUDE.md global, hook no `settings.json` do usuário | Usuário | Configurado e em uso nesta sessão; saída condensada observada. Para a saída original: `rtk bypass <cmd>` |
| Ponytail | Reuso (plugin, `full`) | Usuário | Validado: hook de sessão ativo |
| Caveman | Reuso (plugin) | Usuário | Validado: hook ativo. Docs e código em linguagem normal |
| ESLint/Biome | Inapplicável (sem JS/TS na aplicação) | — | `static/app.js` validado com `node --check`; pyflakes cobre o Python |
| Graphify | CLI global 0.9.95 reutilizada; `.graphifyignore`; grafo completo com 2 subagentes Sonnet para os documentos (2026-10-23) | Projeto (`graphify-out/`, ignorado no git) | Validado: 1571 nós, 3795 arestas, 83 comunidades, `query` respondeu; 0 segredos no `graph.json`. Aviso de saúde: 200 arestas com ponta pendente e 45 colapsadas. Um subagente só varreu por busca as linhas 30–360 de `templates/index.html`. Grafo anterior às correções de 2026-10-23 (tarde); regenerar com `/graphify . --update` |
| Obsidian | Inapplicável (sem necessidade nem destino autorizado) | — | — |
| Memória do Claude | Reuso: memória nativa do projeto (`~/.claude/projects/.../memory/`, índice `MEMORY.md`, 7 entradas + 1 nova) | Usuário | Validado: carregada no início da sessão. Fatos duráveis no repo ficam em `AGENTS.md`/docs |
| Hooks do cliente | Não adotados (nenhuma necessidade; evita interceptadores duplicados) | — | — |
| agent-browser | agent-browser 0.39.2 (global, já instalado) + Chrome 155; sessão nomeada própria, app em SQLite descartável na porta 5099 | Máquina | Validado: login, logout POST, 9 telas, sem erros de JS, auditoria de acessibilidade, contraste e foco por teclado. Corrigidos 9 controles sem nome, botão "Sair" e contraste (3,9:1 → 6:1). Chrome DevTools MCP não usado (sem necessidade) |
| Context7 | Reuso do plugin (MCP) | Usuário | Validado: 2 consultas reais (Flask-Limiter e Flask). Resultado: trocar o parser manual de `X-Forwarded-For` por `ProxyFix(x_for=1)`; `request.max_content_length` por requisição confirmado |
| Anthropic skills / skill-creator / extras | Disponíveis globalmente; nenhuma necessidade do projeto | Usuário | Não instalados no projeto, por decisão |
| Vercel skills / find-skills | Inapplicável (não é React/Next) | — | — |
| next-dev-loop, next-bundle-optimizer | Inapplicável (sem Next.js) | — | — |
| supabase-postgres-best-practices | Reuso: skill descoberta pelo cliente nesta sessão; roteada em `AGENTS.md` | Usuário | Descoberta confirmada; **execução real não feita** (nenhuma mudança de esquema) |
| gh-fix-ci | Inapplicável agora: sem `gh` instalado e sem Codex; CI só criado | — | Bloqueado até haver `gh` autenticado e uma execução de CI |
| differential-review | Skill do Trail of Bits (`trailofbits/skills` @ `196a907`, CC BY-SA 4.0), fonte lida antes; copiada para `.claude/skills/differential-review/` (local, fora do git) | Projeto (local) | Validado por execução: revisão do intervalo `dc15356..HEAD` por subagente Opus que seguiu o `SKILL.md` . Descoberta confirmada em sessão nova (2026-10-23): o cliente listou e carregou a skill pelo mecanismo de skills. O agente `differential-review:adversarial-modeler` não existe na cópia local (só no plugin do marketplace); a modelagem de ataque foi feita manualmente pelo `adversarial.md`. Relatório privado fora do repo. 14 achados; os válidos foram corrigidos |
| shadcn | Inapplicável (sem UI de componentes) | — | — |
| Sentry MCP | Não adotado: sem serviço Sentry escolhido | — | Pendente de decisão do responsável |
| Harness2 (método nativo) | Adotado em modo nativo: procedimento em `docs/quality.md` | Projeto | Caso "boundary fix" executado por subagente Sonnet em cópia descartável: baseline com 2 falhas esperadas, final 7/7 no avaliador do toolkit, `local-notes.txt` e `AGENTS.md` intactos. Um caso, um modelo: não prova confiabilidade geral. CLI oficial e benchmarks não selecionados (custo/isolamento) |
| Revisão de segurança | Prompt copiado para `docs/prompts/security-review.md` (revisão `790a895`) | Projeto | Baseline executada, relatório privado fora do repo |

## Documentação criada

PRODUCT.md, README.md (links adicionados), AGENTS.md, CLAUDE.md, docs/architecture.md, docs/design.md, docs/onboarding.md, docs/quality.md, docs/setup.md, docs/prompts/security-review.md. Sem placeholders. `design.md` registra que critérios visuais não se aplicam ao canal WhatsApp e que não houve revisão de acessibilidade do painel.

## Verificações (antes → depois)

| Item | Antes | Depois |
|---|---|---|
| Testes | 106 OK (`test_secretaria`, `test_horarios`) | 124 OK (+2 detector de segredos, +15 em `test_app.py`, +1 guarda de saída) |
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
- **F8** teto de 12 chamadas ao modelo por número por hora (contador em memória, zera no reinício); no máximo 500 respostas abertas em cache; guarda de saída ampliada com preço por extenso/gíria e diagnóstico parafraseado ("pode ser um cisto").
- **F9** token do canal Google em tempo constante; **refresh token do Google cifrado no banco** (Fernet, chave derivada da `SECRET_KEY`; token antigo em texto é cifrado na primeira leitura; se a `SECRET_KEY` mudar, reconectar o Google); tipos MIME do provedor só entram em `data:` se forem mídia conhecida. Nova dependência: `cryptography`.
- **F5/F7 completos** logout só por POST (botão "Sair" virou formulário); corpo do `/webhook` limitado a 1 MB (413).
- **Acessibilidade do painel (revisão estática)**: 12 botões só com ícone ganharam `aria-label`; foco visível (`:focus-visible`) global. Contraste, ordem de foco e leitor de tela **não** foram testados em navegador.
- `requirements.lock` regenerado com `cryptography`.

## Revisão diferencial (2026-10-23, `dc15356..f9859ce`) — correções aplicadas

Dos 14 achados, corrigidos: segredo do webhook lido na hora (rotação pelo painel não exige reinício) e aviso na subida se faltar; `/webhook` fora do limite global de 200/min; teto do cache de respostas só da versão atual; `conectado()` pelo token legível; chave de cifra rejeita o placeholder e avisa quando o token fica sem cifra; telefone mascarado em `buffer.py`, `database.py`, `memory.py` e `ficha_paciente.py`; guarda de preço cobre "cinquenta reais", "trezentos e cinquenta reais" e "350,00"; MIME de documentos (txt, Word, Excel) permitido; `flask>=3.1.0` (o `max_content_length` por requisição exige 3.1); teste do editor de `.env` sem tocar o `.env` real; testes de pedido assinado e de rotação do segredo. Aceitos sem mudança: teto de 25 MB em uploads (F14) e contador de chamadas ao modelo em memória (F7).

## Pendências e próxima entrega

| Item | Causa | Próxima ação |
|---|---|---|
| F2: confirmar `WHATSAPI_WEBHOOK_SECRET` (e `WHATSAPI_KEY`, `WHATSAPI_PHONE_NUMBER_ID`) no Render | Sem acesso ao painel do Render daqui | Após o deploy, uma mensagem de teste deve chegar; se o log mostrar `Recusado`, definir a variável |
| Rate limit do login assume 1 salto de proxy (`ProxyFix(x_for=1)`) | Não dá para ver o `X-Forwarded-For` real do Render daqui; com Cloudflare na frente o IP seria compartilhado e o limite de 5/min viraria global | Conferir o cabeçalho nos logs do Render e ajustar `x_for` |
| Cookie `Secure` depende de `RENDER` estar definido | Variável do Render, não verificada daqui | Conferir o login no Render após o deploy |
| Render instala `requirements.txt` (sem pins) | Comando de build é decisão de deploy | Trocar para `requirements.lock`, se quiser versões fixas |
| Rate limit do login em memória por processo | Sem storage compartilhado | Só importa com mais de um worker; então usar Redis |
| `app.py` ~3,6 mil linhas e outros arquivos acima de 350 | Dividir 113 rotas sem testes de rota suficientes é risco alto | Dividir por Blueprints, uma área por vez, junto de testes em `test_app.py` |
| Guarda de saída continua sendo lista de regex | Limite da abordagem | Ampliar a lista quando aparecer caso real; `[trava] ... BARRADA` no log mostra os casos |
| Acessibilidade: teste real em navegador | Não executado | Rodar o painel local (SQLite) com a extensão Chrome e checar teclado/contraste |
| `gh`, differential-review, Sentry | Instalação global ou conta Sentry | Decidir; guias 19, 20 e 22 do toolkit |
| CI nunca executado | Workflow criado | Conferir a primeira execução no GitHub |
