# Migração para o Supabase

Como o AgenteDoctor saiu do SQLite local para o Supabase, e como repetir o
processo (outro projeto, ou de volta). Só o banco muda: nenhuma funcionalidade
do agente ou do painel depende do driver.

## Projeto atual

| Item | Valor |
|---|---|
| Projeto | `kchcnjhkphxprewoxjtn` — `agentedoctor` (organização AgentDoctot, plano free) |
| Região | sa-east-1 (São Paulo) — ~36 ms por consulta a partir do Brasil |
| Conexão | Transaction pooler, porta 6543, `sslmode=require` |
| pgvector | 0.8.2, no schema `extensions` |
| RLS | ativo em todas as tabelas `public`, sem políticas |

## Passo a passo

1. **Connection string.** No painel do projeto, clique em **Connect** →
   **Transaction pooler** e copie a URI. Troque `[YOUR-PASSWORD]` pela senha do
   banco, em percent-encoding. Para gerar o valor:
   `python -c "from urllib.parse import quote; print(quote('SENHA', safe=''))"`.
2. **`.env`**:
   ```
   DB_DRIVER=postgresql
   DATABASE_URL=postgresql://postgres.<ref>:<senha-codificada>@aws-0-<regiao>.pooler.supabase.com:6543/postgres?sslmode=require
   ```
3. **Copiar os dados** do SQLite (a origem é aberta só para leitura):
   ```bash
   python migrar_para_supabase.py --dry-run   # conta o que há na origem
   python migrar_para_supabase.py --sim       # cria o schema e copia
   ```
   - O schema é criado pelo próprio `database.init_db()`.
   - Os ids são preservados e as sequências ajustadas.
   - Os embeddings são copiados sem chamar a OpenAI.
   - O script recusa destino que já tenha dados.
   - No fim, compara origem × destino.
4. **Segurança** (já aplicado neste projeto, migração `seguranca_rls_e_vector`):
   - RLS ligado em todas as tabelas `public`, sem políticas.
   - Gatilho `ensure_rls` + função `private.rls_auto_enable()`: toda tabela
     nova em `public` já nasce com RLS. A função fica fora do schema exposto
     pela API e sem `EXECUTE` para anon/authenticated.
   - `vector` movido para o schema `extensions`.

   **Atenção:** projeto criado pela API/MCP **não** vem com RLS automático
   (o criado pelo painel vem). Sem esse passo, as tabelas ficam legíveis pela
   chave pública. Confira em **Advisors → Security**: só deve restar o aviso
   informativo "RLS Enabled No Policy", que é o desejado.

## Rollback

Volte `DB_DRIVER=sqlite` no `.env`. O `secretaria.db` não é alterado pela
migração e continua sendo o backup local do estado de antes.

## Histórico

- 2026-10-01: primeiro migrado para `wizduleefiuoeyzjgyck` (us-east-2), ~186 ms
  por consulta a partir do Brasil. Movido para São Paulo no mesmo dia (região
  não pode ser trocada em projeto existente). O projeto de Ohio foi pausado
  para liberar a vaga do plano free (limite de 2 projetos ativos por dono).

## Notas

- `db.py` liga `autocommit` nas conexões do pool. Sem isso, cada consulta
  custava 3 idas e voltas ao banco (BEGIN, a consulta e o ROLLBACK do pool).
- `db.table_columns()` filtra o schema `public`. O Supabase tem
  `realtime.messages`, e sem o filtro as colunas dela se misturariam às da
  nossa tabela `messages`.
