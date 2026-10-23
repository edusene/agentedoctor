# Qualidade

## Comandos

| Comando | O que prova |
|---|---|
| `python verify.py` | Tudo abaixo, em sequência. Roda igual no CI (`.github/workflows/verify.yml`). |
| `python verify.py --testes` | Só os testes, num SQLite temporário e com a trava contra produção |
| `python -m pyflakes *.py` | Imports e variáveis mortas, erros de nome (precisa de `requirements-dev.txt`) |

`verify.py` não publica, não usa rede nem banco real, e se recusa a rodar os testes se `db.DB_DRIVER` não for `sqlite`. Não há type checker, build nem linter de estilo: Python sem anotações consistentes, e adotar mypy/ruff agora geraria centenas de avisos de legado. Reavaliar quando houver anotações ou um formatador acordado.

## Regras base

- Resposta clínica nova entra em `clinica.py`/`secretaria.py` com teste; o texto sai da Base de Conhecimento, não da cabeça de ninguém.
- SQL sempre parametrizado; entrada externa validada na borda (webhook, rotas `/api`, upload).
- Log sem segredo, sem telefone completo e sem texto de paciente além do necessário ao diagnóstico.
- Limite de tamanho de arquivo (referência do toolkit: 350 linhas): **não atendido** por `app.py` (~3,6 mil), `database.py` (~1,9 mil), `ficha_paciente.py`, `clinica.py`, `secretaria.py`, `test_secretaria.py`. Dívida registrada; nenhum arquivo novo deve passar do limite, e `app.py` é dividido por rotas só junto com uma mudança que o toque.

## Estratégia de testes

`test_secretaria.py` cobre a matriz de triagem, emergências, cada resposta travada, a conferência da saída do modelo, o fluxo completo e a não oscilação (mesma conversa 25 vezes). `test_horarios.py` cobre as vagas. `test_verify.py` é o auto-teste do detector de segredos. `test_app.py` cobre login, sessão, cabeçalhos, webhook sem/errado de assinatura, limite do login contra `X-Forwarded-For` forjado e o teto de chamadas ao modelo; ele só roda por `verify.py --testes` (pula fora disso) e usa `OPENAI_BASE_URL` apontando para uma porta fechada, então nada sai para a rede. Não há teste de fluxo completo do webhook com mensagem real. Correção de bug: reproduzir num teste antes de corrigir.

**Trava contra produção** (obrigatória para qualquer script que importe `app`, `db` ou `database`): antes de qualquer import, `dotenv.load_dotenv = lambda *a, **k: False`; tirar `DATABASE_URL` e `DATAFY_TOKEN` do ambiente; definir `OPENAI_API_KEY` falsa, `DB_DRIVER=sqlite` e `DB_PATH` temporário; depois do import, abortar se `db.DB_DRIVER != "sqlite"`. `verify.py` já faz isso. Origem: em 2026-10-07/08 um teste criou dados falsos e trocou o refresh token do Google em produção.

Gaste o mínimo de OpenAI: rode cenários com a OpenAI bloqueada e chame o modelo só nas dúvidas abertas.

## Revisão após implementação

Escolha o escopo pelo risco e pelo diff real; use revisão independente para mudança não trivial. Registre o alvo exato, os chamadores e testes conectados, os achados confirmados e a cobertura. Termine quando os achados relevantes estiverem resolvidos ou com disposição explícita e as verificações afetadas passarem. Mais rodadas só com evidência nova ou risco aberto.

## Revisão de segurança

Prompt reutilizável: `docs/prompts/security-review.md` (fonte e revisão do toolkit no cabeçalho). Modo padrão: baseline do repositório; para um diff, informe `base` e `head`. O relatório fica **fora do repositório** (ele é público) e sem segredo ou dado de paciente. Revisão é só leitura; correção é pedido separado. Resultado da revisão de 2026-10-23 e pendências: `docs/setup.md`.

## Dependências e entrega

Auditoria: `pip install pip-audit` num venv separado e `pip-audit -r requirements.txt` (2026-10-23: nenhuma vulnerabilidade conhecida). `requirements.lock` é a referência das versões auditadas; o Render ainda instala `requirements.txt`, então as versões podem mudar a cada deploy (ver `docs/setup.md`). O CI roda `verify.py` mas **não bloqueia o deploy**: o Render publica no push independentemente. Hooks de Git e proteção de branch não fazem parte do projeto.

## Harness do agente

Procedimento de avaliação do toolkit (`docs/07-harness-evaluation.md` e prompts 14 e 15, revisão `790a895`) aplicado em modo nativo: casos de fumaça em cópia descartável, um candidato por falha observada, sem mexer em instruções que funcionam. Resultados em `docs/setup.md`. Repetir depois de mudar `AGENTS.md`, memória, skills ou modelo.
