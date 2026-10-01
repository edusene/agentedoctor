# Migração para o Supabase

Como o AgenteDoctor saiu do SQLite local para o Supabase, e como repetir o
processo (outro projeto, ou de volta). Só o banco muda: nenhuma funcionalidade
do agente ou do painel depende do driver.

## Projeto atual

| Item | Valor |
|---|---|
| Projeto | `wizduleefiuoeyzjgyck` (organização AgentDoctot, plano free) |
| Região | us-east-2 (Ohio) |
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
4. **Segurança** (já aplicado neste projeto, migração `seguranca_vector_e_rls_auto_enable`):
   ```sql
   create schema if not exists extensions;
   alter extension vector set schema extensions;
   revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
   ```
   O RLS nas tabelas é ligado automaticamente pelo gatilho `ensure_rls` do
   Supabase. Confira em **Advisors → Security**: só deve restar o aviso
   informativo "RLS Enabled No Policy", que é o desejado.

## Rollback

Volte `DB_DRIVER=sqlite` no `.env`. O `secretaria.db` não é alterado pela
migração e continua sendo o backup local do estado de antes.

## Notas

- `db.py` liga `autocommit` nas conexões do pool. Sem isso, cada consulta
  custava 3 idas e voltas ao banco (BEGIN, a consulta e o ROLLBACK do pool).
- `db.table_columns()` filtra o schema `public`. O Supabase tem
  `realtime.messages`, e sem o filtro as colunas dela se misturariam às da
  nossa tabela `messages`.
