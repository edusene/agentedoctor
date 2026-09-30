# Migração de Conta Supabase

Guia completo para migrar o banco de dados para uma nova conta Supabase.

---

## Pré-requisitos

- Conta criada no Supabase (novo projeto)
- Acesso ao painel do Render (ou onde a variável de ambiente estiver configurada)

---

## Passo a passo

### 1. Criar novo projeto no Supabase

1. Acesse [supabase.com](https://supabase.com) e faça login
2. Clique em **"New project"**
3. Escolha uma senha para o banco (anote — usada na connection string)
4. Região: selecione a mais próxima
5. Aguarde o projeto ser criado (~1 minuto)

### 2. Copiar a Connection String

1. No painel do novo projeto, vá em **Settings → Database → URI**
2. Copie a connection string completa no formato:
   ```
   postgresql://postgres.PROJECT_REF:SENHA@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
   ```
3. **Substitua** `SENHA` pela senha que você definiu ao criar o projeto

### 3. Rodar o SQL no SQL Editor

1. No painel do Supabase, vá em **SQL Editor**
2. Clique em **"New query"**
3. Cole o bloco SQL abaixo (seção [SQL Completo](#sql-completo))
4. Clique em **"Run"** (ou Ctrl+Enter)
5. Aguarde a mensagem de sucesso — todas as tabelas e índices serão criados

### 4. Atualizar variável de ambiente no Render

1. Acesse o painel do Render
2. Vá em **Environment** do serviço
3. Atualize a variável `DATABASE_URL` com a nova connection string:
   ```
   DATABASE_URL=postgresql://postgres.NOVO_PROJECT_REF:SENHA@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
   ```
4. Clique em **"Save"**

### 5. Redeploy

1. O app fará deploy automaticamente ao salvar as variáveis
2. Caso não deploye automaticamente, vá em **Manual Deploy → Clear build cache & deploy**
3. Ao iniciar, o app roda `init_db()` que cria qualquer coluna que falte (migrações idempotentes)

### 6. Verificar

1. Acesse o painel do app
2. Verifique se as tabelas existem: vá no **Supabase → Table Editor**
3. Deve ver: contacts, conversations, messages, tags, contact_tags, conversation_tags, templates, tasks, settings, knowledge, knowledge_files

---

## SQL Completo

Cole este bloco inteiro no SQL Editor do novo projeto Supabase:

```sql
-- ============================================================
-- Extensão pgvector (busca semântica do RAG)
-- ============================================================
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- Tabela: contacts
-- ============================================================
CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    phone TEXT UNIQUE NOT NULL,
    name TEXT DEFAULT '',
    email TEXT DEFAULT '',
    company TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    avatar_url TEXT DEFAULT '',
    avatar_color TEXT DEFAULT '',
    assigned_to TEXT DEFAULT '',
    auto_mode INTEGER DEFAULT 1,
    created_at TEXT DEFAULT NOW(),
    updated_at TEXT DEFAULT NOW()
);

-- ============================================================
-- Tabela: conversations
-- ============================================================
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    status TEXT DEFAULT 'new',
    assigned_to TEXT DEFAULT '',
    priority TEXT DEFAULT 'normal',
    unread_count INTEGER DEFAULT 0,
    last_message_at TEXT,
    archived INTEGER DEFAULT 0,
    muted INTEGER DEFAULT 0,
    pinned INTEGER DEFAULT 0,
    favorite INTEGER DEFAULT 0,
    created_at TEXT DEFAULT NOW(),
    updated_at TEXT DEFAULT NOW()
);

-- ============================================================
-- Tabela: messages
-- ============================================================
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    phone TEXT NOT NULL,
    wa_message_id TEXT UNIQUE,
    direction TEXT NOT NULL,
    sender TEXT DEFAULT '',
    body TEXT DEFAULT '',
    msg_type TEXT DEFAULT 'text',
    media_url TEXT DEFAULT '',
    status TEXT DEFAULT 'sent',
    created_at TEXT DEFAULT NOW(),
    wa_media_id TEXT DEFAULT ''
);

-- ============================================================
-- Tabela: tags
-- ============================================================
CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    color TEXT DEFAULT '#6366f1'
);

-- ============================================================
-- Tabela: contact_tags (junção)
-- ============================================================
CREATE TABLE IF NOT EXISTS contact_tags (
    contact_id INTEGER REFERENCES contacts(id),
    tag_id INTEGER REFERENCES tags(id),
    PRIMARY KEY (contact_id, tag_id)
);

-- ============================================================
-- Tabela: conversation_tags (junção)
-- ============================================================
CREATE TABLE IF NOT EXISTS conversation_tags (
    conversation_id INTEGER REFERENCES conversations(id),
    tag_id INTEGER REFERENCES tags(id),
    PRIMARY KEY (conversation_id, tag_id)
);

-- ============================================================
-- Tabela: templates
-- ============================================================
CREATE TABLE IF NOT EXISTS templates (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT DEFAULT NOW()
);

-- ============================================================
-- Tabela: tasks
-- ============================================================
CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER REFERENCES contacts(id),
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    due_date TEXT,
    created_at TEXT DEFAULT NOW()
);

-- ============================================================
-- Tabela: settings
-- ============================================================
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT '',
    created_at TEXT DEFAULT NOW(),
    updated_at TEXT DEFAULT NOW()
);

-- ============================================================
-- Tabela: knowledge (RAG com embeddings pgvector)
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    chunk_index INTEGER DEFAULT 0,
    title TEXT DEFAULT '',
    content TEXT DEFAULT '',
    created_at TEXT DEFAULT NOW(),
    updated_at TEXT DEFAULT NOW(),
    embedding vector(1536)
);

-- ============================================================
-- Tabela: knowledge_files (metadados de arquivos)
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_files (
    filename TEXT PRIMARY KEY,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'indexed',
    created_at TEXT DEFAULT NOW(),
    updated_at TEXT DEFAULT NOW()
);

-- ============================================================
-- Índices
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_wa_msg ON messages(wa_message_id);
CREATE INDEX IF NOT EXISTS idx_conversations_contact ON conversations(contact_id);
CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);
CREATE INDEX IF NOT EXISTS idx_conversations_pinned ON conversations(pinned);
CREATE INDEX IF NOT EXISTS idx_tasks_contact ON tasks(contact_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_filename ON knowledge(filename);
```

---

## Notas

- **Dados não migram automaticamente** — se quiser manter dados do banco antigo, exporte via Supabase Dashboard (Settings → Database → Backups) e importe no novo projeto
- O SQL é **idempotente** — pode rodar mais de uma vez sem erro (`CREATE TABLE IF NOT EXISTS`)
- O app cria colunas faltantes automaticamente via migrações no startup (`init_db()`)
- Sem funções, triggers ou RLS — toda lógica é em Python
