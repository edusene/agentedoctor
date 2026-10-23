# Preparo local

## Pré-requisitos

Python 3.12+ (verificado em 3.14.7) e Git. Para as ferramentas de agente: Graphify (`graphify --version`, 0.9.95 verificado) e o Claude Code com os plugins do `docs/setup.md`. Nada de Node.

## Primeira execução

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt   # Windows
cp .env.example .env     # preencha; nunca versione o .env
python verify.py         # confirma o ambiente sem rede e sem banco
python app.py            # painel em http://localhost:5000/panel
```

Variáveis: ver `.env.example` (comentado) e a tabela de produção no `README.md`. `SECRET_KEY` e `ADMIN_PASSWORD` não têm padrão: sem elas o login do painel fica fechado. Gere a chave com `python -c "import secrets;print(secrets.token_hex(32))"`. As variáveis do servidor ficam no painel do Render, não no `.env` local.

## Banco

Produção é o Supabase (pooler de transação, porta 6543). **O `.env` local aponta para o Supabase de produção**: rodar `python app.py` com ele grava dados reais. Para trabalhar sem tocar nele, use um `.env` separado com `DB_DRIVER=sqlite` e `DB_PATH=secretaria.db` e confira o destino impresso na subida. Esquema: `database.init_db()` cria o que falta ao subir. Migração entre SQLite e Supabase: `SUPABASE_MIGRATION.md`.

## Verificar

`python verify.py` roda sintaxe, pyflakes, varredura de segredos e os testes (SQLite temporário). Esperado: quatro linhas `[ok]`. Não depende de credenciais nem de serviço externo. Teste que precise de serviço real (OpenAI, Datafy, Supabase) não existe e não deve ser criado contra produção.

## Agentes

Leia [AGENTS.md](../AGENTS.md); [CLAUDE.md](../CLAUDE.md) o importa. Ferramentas e escopos: [setup.md](setup.md).

## Problemas conhecidos

- Resposta lenta (20–45 s): era o pool do banco abrindo conexão por consulta; corrigido com `DB_POOL_MIN=6`. Se voltar, colete as linhas `[tempo]` do log do Render.
- `ADMIN_PASSWORD nao definida` na subida: o login está bloqueado de propósito; defina a variável.
- Teste gravando no Supabase: causado por `load_dotenv(override=True)`; use `verify.py --testes`.
