"""
database.py — ORM leve para o painel CRM.
Usa db.py como camada de abstração (suporta SQLite e PostgreSQL).
O agente Gemini continua usando memory.py (in-memory) para seu histórico.
"""

import db
import json
from datetime import datetime, timedelta
from typing import Any


def init_db() -> None:
    """Cria todas as tabelas se não existirem (e aplica migrações idempotentes)."""
    db.executescript(SCHEMA)

    # Migration: renomear uazapi_id -> wa_message_id (Supabase/PostgreSQL)
    cols = db.table_columns("messages")
    if "uazapi_id" in cols and "wa_message_id" not in cols:
        try:
            db.execute("DROP INDEX IF EXISTS idx_messages_uazapi")
        except Exception:
            pass
        db.execute("ALTER TABLE messages RENAME COLUMN uazapi_id TO wa_message_id")
        print("[db] migration: uazapi_id -> wa_message_id concluida")

    # Migração idempotente: adiciona colunas de gerenciamento de conversa
    cols = db.table_columns("conversations")
    for col, ddl in (
        ("archived", "ALTER TABLE conversations ADD COLUMN archived INTEGER DEFAULT 0"),
        ("muted", "ALTER TABLE conversations ADD COLUMN muted INTEGER DEFAULT 0"),
        ("pinned", "ALTER TABLE conversations ADD COLUMN pinned INTEGER DEFAULT 0"),
        ("favorite", "ALTER TABLE conversations ADD COLUMN favorite INTEGER DEFAULT 0"),
    ):
        if col not in cols:
            db.execute(ddl)

    # Habilita extensão pgvector no PostgreSQL (necessário para busca semântica)
    if db.DB_DRIVER == "postgresql":
        try:
            db.execute("CREATE EXTENSION IF NOT EXISTS vector")
            print("[db] extensão vector habilitada")
        except Exception as e:
            print(f"[db] WARN: vector extension: {e}")

    # Migração idempotente: cria tabela knowledge se não existir
    kcols = db.table_columns("knowledge") if "knowledge" in _get_tables() else set()
    if not kcols:
        db.executescript(KNOWLEDGE_SCHEMA)
        print("[db] tabela knowledge criada")
        kcols = db.table_columns("knowledge")
    # A tabela nasce sem a coluna do vetor: ela entra aqui, na mesma subida.
    if "embedding" not in kcols:
        # PostgreSQL: pgvector. SQLite: o vetor vai como JSON em TEXT e a
        # similaridade e calculada em Python (a base e pequena).
        tipo = "vector(1536)" if db.DB_DRIVER == "postgresql" else "TEXT"
        try:
            db.execute(f"ALTER TABLE knowledge ADD COLUMN embedding {tipo}")
            print("[db] coluna embedding adicionada")
        except Exception:
            pass

    # Migração idempotente: cria tabela knowledge_files (descrições)
    if "knowledge_files" not in _get_tables():
        db.executescript(KNOWLEDGE_FILES_SCHEMA)
        print("[db] tabela knowledge_files criada")
    else:
        kfcols = db.table_columns("knowledge_files")
        if "status" not in kfcols:
            try:
                db.execute("ALTER TABLE knowledge_files ADD COLUMN status TEXT DEFAULT 'indexed'")
                print("[db] coluna status adicionada em knowledge_files")
            except Exception:
                pass
        if "content" not in kfcols:
            try:
                db.execute("ALTER TABLE knowledge_files ADD COLUMN content TEXT DEFAULT ''")
                print("[db] coluna content adicionada em knowledge_files (documento original)")
            except Exception:
                pass

    # Migração: adiciona wa_media_id na tabela messages
    mcols = db.table_columns("messages")
    if "wa_media_id" not in mcols:
        try:
            db.execute("ALTER TABLE messages ADD COLUMN wa_media_id TEXT DEFAULT ''")
            print("[db] coluna wa_media_id adicionada")
        except Exception:
            pass

    # Migração: adiciona avatar_color na tabela contacts
    ccols = db.table_columns("contacts")
    if "avatar_color" not in ccols:
        try:
            db.execute("ALTER TABLE contacts ADD COLUMN avatar_color TEXT DEFAULT ''")
            print("[db] coluna avatar_color adicionada")
        except Exception:
            pass

    # Migração: adiciona transferred_at na tabela conversations
    cvcols = db.table_columns("conversations")
    if "transferred_at" not in cvcols:
        try:
            db.execute("ALTER TABLE conversations ADD COLUMN transferred_at TEXT DEFAULT NULL")
            print("[db] coluna transferred_at adicionada em conversations")
        except Exception:
            pass

    # Migração: reset_at marca onde o atendimento recomecou (#reset). O
    # historico enviado ao LLM e cortado nesse ponto; sem a coluna, o corte
    # viveria so em memoria e o Render reiniciando trazia a conversa velha de
    # volta do banco.
    cvcols = db.table_columns("conversations")
    if "reset_at" not in cvcols:
        try:
            db.execute("ALTER TABLE conversations ADD COLUMN reset_at TEXT DEFAULT NULL")
            print("[db] coluna reset_at adicionada em conversations")
        except Exception:
            pass

    # Migração CRM: adiciona crm_status e last_interaction_at na tabela contacts
    ccols2 = db.table_columns("contacts")
    if "crm_status" not in ccols2:
        try:
            db.execute("ALTER TABLE contacts ADD COLUMN crm_status TEXT DEFAULT 'novo'")
            print("[db] coluna crm_status adicionada em contacts")
        except Exception:
            pass
    if "last_interaction_at" not in ccols2:
        try:
            db.execute("ALTER TABLE contacts ADD COLUMN last_interaction_at TEXT")
            print("[db] coluna last_interaction_at adicionada em contacts")
        except Exception:
            pass
    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_contacts_crm_status ON contacts(crm_status)")
    except Exception:
        pass

    # Migração CRM: cria tabelas de automações, follow-ups e logs
    crm_tables = _get_tables()
    if "crm_automations" not in crm_tables:
        db.executescript(CRM_SCHEMA)
        print("[db] tabelas CRM criadas")

    # Agendamentos (abas Confirmação de Agendamento e Agenda do painel)
    if "agendamentos" not in _get_tables():
        db.executescript(AGENDAMENTOS_SCHEMA)
        print("[db] tabela agendamentos criada")

    _ensure_indexes()


# ═══ Settings (key-value global) ═════════════════════════════════════════════

def get_setting(key: str, default: str = "") -> str:
    row = db.fetch_one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    now = datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
        (key, value, now),
    )


def _ensure_indexes() -> None:
    """Crea índices faltantes que aceleran las consultas más usadas (idempotente).

    La mayoría ya los crea el SCHEMA (messages.conversation_id/created_at,
    conversations.contact_id/status). Aquí solo añadimos el orden por pinned de la
    lista de conversas y el índice de wa_message_id, sin duplicar ni alterar las consultas existentes.
    """
    for name, table, column in (
        ("idx_conversations_pinned", "conversations", "pinned"),
        ("idx_messages_wa_msg", "messages", "wa_message_id"),
    ):
        try:
            db.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({column})")
        except Exception as e:
            print(f"[db] WARN index {name}: {e}")


def _get_tables() -> set[str]:
    """Retorna nomes das tabelas existentes no banco."""
    if db.DB_DRIVER == "postgresql":
        rows = db.fetch_all(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        )
        return {r["table_name"] for r in rows}
    else:
        rows = db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
        return {r["name"] for r in rows}


KNOWLEDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    chunk_index INTEGER DEFAULT 0,
    title TEXT DEFAULT '',
    content TEXT DEFAULT '',
    created_at TEXT DEFAULT NOW(),
    updated_at TEXT DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_filename ON knowledge(filename);
"""

KNOWLEDGE_FILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_files (
    filename TEXT PRIMARY KEY,
    description TEXT DEFAULT '',
    content TEXT DEFAULT '',
    status TEXT DEFAULT 'indexed',
    created_at TEXT DEFAULT NOW(),
    updated_at TEXT DEFAULT NOW()
);
"""

AGENDAMENTOS_SCHEMA = """
CREATE TABLE IF NOT EXISTS agendamentos (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER REFERENCES contacts(id),
    conversation_id INTEGER REFERENCES conversations(id),
    phone TEXT DEFAULT '',
    nome TEXT DEFAULT '',
    resumo TEXT DEFAULT '',
    ficha TEXT DEFAULT '{}',
    status TEXT DEFAULT 'pendente',
    inicio TEXT DEFAULT '',
    duracao_min INTEGER DEFAULT 60,
    observacoes TEXT DEFAULT '',
    google_event_id TEXT DEFAULT '',
    confirmado_em TEXT DEFAULT '',
    created_at TEXT DEFAULT NOW(),
    updated_at TEXT DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agendamentos_status ON agendamentos(status);
CREATE INDEX IF NOT EXISTS idx_agendamentos_inicio ON agendamentos(inicio);
CREATE INDEX IF NOT EXISTS idx_agendamentos_contact ON agendamentos(contact_id)
"""

CRM_SCHEMA = """
CREATE TABLE IF NOT EXISTS crm_automations (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    days INTEGER DEFAULT 0,
    hours INTEGER DEFAULT 0,
    message_template TEXT DEFAULT '',
    use_meta_template INTEGER DEFAULT 0,
    meta_template_name TEXT DEFAULT '',
    meta_template_language TEXT DEFAULT 'pt_BR',
    action_tag_add TEXT DEFAULT '',
    action_tag_remove TEXT DEFAULT '',
    action_status_change TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    send_window_start TEXT DEFAULT '08:00',
    send_window_end TEXT DEFAULT '18:00',
    created_at TEXT DEFAULT NOW(),
    updated_at TEXT DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS crm_follow_ups (
    id SERIAL PRIMARY KEY,
    automation_id INTEGER NOT NULL REFERENCES crm_automations(id),
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    scheduled_for TEXT NOT NULL,
    status TEXT DEFAULT 'pendente',
    message_sent TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    sent_at TEXT,
    created_at TEXT DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS crm_logs (
    id SERIAL PRIMARY KEY,
    automation_id INTEGER REFERENCES crm_automations(id),
    contact_id INTEGER REFERENCES contacts(id),
    action TEXT DEFAULT 'send',
    message TEXT DEFAULT '',
    result TEXT DEFAULT '',
    error TEXT DEFAULT '',
    created_at TEXT DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_follow_ups_status ON crm_follow_ups(status);
CREATE INDEX IF NOT EXISTS idx_follow_ups_scheduled ON crm_follow_ups(scheduled_for);
CREATE INDEX IF NOT EXISTS idx_follow_ups_contact ON crm_follow_ups(contact_id);
CREATE INDEX IF NOT EXISTS idx_automations_active ON crm_automations(is_active);
"""

SCHEMA = """
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
    transferred_at TEXT DEFAULT NULL,
    created_at TEXT DEFAULT NOW(),
    updated_at TEXT DEFAULT NOW()
);

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
    created_at TEXT DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    color TEXT DEFAULT '#6366f1'
);

CREATE TABLE IF NOT EXISTS contact_tags (
    contact_id INTEGER REFERENCES contacts(id),
    tag_id INTEGER REFERENCES tags(id),
    PRIMARY KEY (contact_id, tag_id)
);

CREATE TABLE IF NOT EXISTS conversation_tags (
    conversation_id INTEGER REFERENCES conversations(id),
    tag_id INTEGER REFERENCES tags(id),
    PRIMARY KEY (conversation_id, tag_id)
);

CREATE TABLE IF NOT EXISTS templates (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER REFERENCES contacts(id),
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    due_date TEXT,
    created_at TEXT DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT '',
    created_at TEXT DEFAULT NOW(),
    updated_at TEXT DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_contact ON conversations(contact_id);
CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);
CREATE INDEX IF NOT EXISTS idx_tasks_contact ON tasks(contact_id);

CREATE TABLE IF NOT EXISTS crm_automations (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    days INTEGER DEFAULT 0,
    hours INTEGER DEFAULT 0,
    message_template TEXT DEFAULT '',
    use_meta_template INTEGER DEFAULT 0,
    meta_template_name TEXT DEFAULT '',
    meta_template_language TEXT DEFAULT 'pt_BR',
    action_tag_add TEXT DEFAULT '',
    action_tag_remove TEXT DEFAULT '',
    action_status_change TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    send_window_start TEXT DEFAULT '08:00',
    send_window_end TEXT DEFAULT '18:00',
    created_at TEXT DEFAULT NOW(),
    updated_at TEXT DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crm_follow_ups (
    id SERIAL PRIMARY KEY,
    automation_id INTEGER NOT NULL REFERENCES crm_automations(id),
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    scheduled_for TEXT NOT NULL,
    status TEXT DEFAULT 'pendente',
    message_sent TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    sent_at TEXT,
    created_at TEXT DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crm_logs (
    id SERIAL PRIMARY KEY,
    automation_id INTEGER REFERENCES crm_automations(id),
    contact_id INTEGER REFERENCES contacts(id),
    action TEXT DEFAULT 'send',
    message TEXT DEFAULT '',
    result TEXT DEFAULT '',
    error TEXT DEFAULT '',
    created_at TEXT DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_follow_ups_status ON crm_follow_ups(status);
CREATE INDEX IF NOT EXISTS idx_follow_ups_scheduled ON crm_follow_ups(scheduled_for);
CREATE INDEX IF NOT EXISTS idx_follow_ups_contact ON crm_follow_ups(contact_id);
CREATE INDEX IF NOT EXISTS idx_automations_active ON crm_automations(is_active);

CREATE TABLE IF NOT EXISTS conversation_states (
    phone TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT DEFAULT NOW()
);
"""


# ── Contacts ──────────────────────────────────────────────────────────────────

def upsert_contact(phone: str, name: str = "", **extra: Any) -> dict:
    """Insere ou atualiza contato pelo phone. Retorna o contato."""
    now = datetime.utcnow().isoformat()
    existing = db.fetch_one("SELECT * FROM contacts WHERE phone=?", (phone,))
    if existing:
        fields = []
        vals = []
        for k, v in extra.items():
            if k in ("name", "email", "company", "notes", "avatar_url", "avatar_color", "assigned_to", "auto_mode"):
                fields.append(f"{k}=?")
                vals.append(v)
        if name:
            fields.append("name=?")
            vals.append(name)
        fields.append("updated_at=?")
        vals.append(now)
        vals.append(phone)
        db.execute(f"UPDATE contacts SET {','.join(fields)} WHERE phone=?", tuple(vals))
    else:
        default_auto = int(get_setting("agent_mode", "1"))
        db.execute(
            "INSERT INTO contacts (phone, name, email, company, notes, avatar_url, avatar_color, assigned_to, auto_mode, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (phone, name, extra.get("email", ""), extra.get("company", ""),
             extra.get("notes", ""), extra.get("avatar_url", ""),
             extra.get("avatar_color", ""), extra.get("assigned_to", ""), extra.get("auto_mode", default_auto), now, now),
        )
    return db.fetch_one("SELECT * FROM contacts WHERE phone=?", (phone,))


def get_contact(phone: str) -> dict | None:
    return db.fetch_one("SELECT * FROM contacts WHERE phone=?", (phone,))


def get_contact_by_id(contact_id: int) -> dict | None:
    return db.fetch_one("SELECT * FROM contacts WHERE id=?", (contact_id,))


def list_contacts(limit: int = 100, offset: int = 0) -> list[dict]:
    return db.fetch_all(
        "SELECT * FROM contacts ORDER BY updated_at DESC LIMIT ? OFFSET ?", (limit, offset)
    )


def update_contact(contact_id: int, **fields: Any) -> None:
    allowed = ("name", "email", "company", "notes", "avatar_url", "avatar_color", "assigned_to", "auto_mode", "crm_status", "last_interaction_at")
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if sets:
        sets.append("updated_at=?")
        vals.append(datetime.utcnow().isoformat())
        vals.append(contact_id)
        db.execute(f"UPDATE contacts SET {','.join(sets)} WHERE id=?", tuple(vals))


def delete_contact(contact_id: int) -> None:
    convs = db.fetch_all("SELECT id FROM conversations WHERE contact_id=?", (contact_id,))
    for conv in convs:
        cid = conv["id"]
        for tbl in ("crm_follow_ups", "crm_logs", "agendamentos"):
            try:
                db.execute(f"DELETE FROM {tbl} WHERE conversation_id=?", (cid,))
            except Exception:
                pass
        db.execute("DELETE FROM conversation_tags WHERE conversation_id=?", (cid,))
        db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
    db.execute("DELETE FROM conversations WHERE contact_id=?", (contact_id,))
    for tbl in ("contact_tags", "tasks", "crm_follow_ups", "crm_logs", "agendamentos"):
        try:
            db.execute(f"DELETE FROM {tbl} WHERE contact_id=?", (contact_id,))
        except Exception:
            pass
    db.execute("DELETE FROM contacts WHERE id=?", (contact_id,))


# ── Conversations ─────────────────────────────────────────────────────────────

def get_or_create_conversation(phone: str) -> dict:
    """Retorna conversa aberta (new|open|waiting) ou cria uma nova."""
    contact = db.fetch_one("SELECT id FROM contacts WHERE phone=?", (phone,))
    if not contact:
        now = datetime.utcnow().isoformat()
        db.execute("INSERT INTO contacts (phone, created_at, updated_at) VALUES (?,?,?)", (phone, now, now))
        contact = db.fetch_one("SELECT id FROM contacts WHERE phone=?", (phone,))
    contact_id = contact["id"]

    conv = db.fetch_one(
        "SELECT * FROM conversations WHERE contact_id=? ORDER BY id DESC LIMIT 1",
        (contact_id,),
    )
    if conv:
        return conv

    now = datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO conversations (contact_id, status, last_message_at, created_at, updated_at) VALUES (?,?,?,?,?)",
        (contact_id, "new", now, now, now),
    )
    return db.fetch_one(
        "SELECT * FROM conversations WHERE contact_id=? ORDER BY id DESC LIMIT 1", (contact_id,)
    )


def get_conversation(conv_id: int) -> dict | None:
    return db.fetch_one("SELECT * FROM conversations WHERE id=?", (conv_id,))


def list_conversations(status: str = "", archived: bool | None = None,
                       auto_mode: int | None = None,
                       limit: int = 100, offset: int = 0) -> list[dict]:
    """Lista conversas. Por padrão esconde arquivadas; `archived=True` mostra só arquivadas.
    `auto_mode=1` filtra apenas conversas do bot; `auto_mode=0` apenas fila humana."""
    if status == "archived":
        status = ""
        archived = True

    where = []
    params: list[Any] = []
    if status:
        where.append("c.status=?")
        params.append(status)
    if archived is True:
        where.append("c.archived=1")
    else:
        where.append("c.archived=0")
    if auto_mode is not None:
        where.append("ct.auto_mode=?")
        params.append(auto_mode)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.fetch_all(
        "SELECT c.*, ct.name as contact_name, ct.phone as contact_phone, "
        "ct.avatar_url as contact_avatar, ct.avatar_color as contact_avatar_color, "
        "ct.auto_mode as contact_auto_mode, "
        "(SELECT m.body FROM messages m WHERE m.conversation_id=c.id ORDER BY m.created_at DESC LIMIT 1) as last_message_body "
        "FROM conversations c LEFT JOIN contacts ct ON c.contact_id=ct.id "
        f"{where_sql} ORDER BY c.pinned DESC, c.last_message_at DESC, c.id DESC "
        "LIMIT ? OFFSET ?",
        (*params, limit, offset),
    )

    conv_ids = [r["id"] for r in rows]
    tags_by_conv: dict[int, list[dict]] = {}
    if conv_ids:
        placeholders = ",".join(["?"] * len(conv_ids))
        tag_rows = db.fetch_all(
            f"SELECT ct.conversation_id AS conv_id, t.id, t.name, t.color "
            f"FROM conversation_tags ct JOIN tags t ON t.id=ct.tag_id "
            f"WHERE ct.conversation_id IN ({placeholders}) ORDER BY t.name",
            conv_ids,
        )
        for tr in tag_rows:
            tags_by_conv.setdefault(tr["conv_id"], []).append(
                {"id": tr["id"], "name": tr["name"], "color": tr["color"]}
            )

    result = []
    for r in rows:
        item = dict(r)
        item["tags"] = tags_by_conv.get(item["id"], [])
        result.append(item)
    return result


def update_conversation(conv_id: int, **fields: Any) -> None:
    allowed = ("status", "assigned_to", "priority", "unread_count", "last_message_at",
               "archived", "muted", "pinned", "favorite", "transferred_at",
               "reset_at")
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if sets:
        sets.append("updated_at=?")
        vals.append(datetime.utcnow().isoformat())
        vals.append(conv_id)
        db.execute(f"UPDATE conversations SET {','.join(sets)} WHERE id=?", tuple(vals))


def increment_unread(conv_id: int) -> None:
    db.execute(
        "UPDATE conversations SET unread_count=unread_count+1, updated_at=? WHERE id=?",
        (datetime.utcnow().isoformat(), conv_id),
    )


def reset_unread(conv_id: int) -> None:
    db.execute(
        "UPDATE conversations SET unread_count=0, updated_at=? WHERE id=?",
        (datetime.utcnow().isoformat(), conv_id),
    )


def reset_unread_bulk(conv_ids: list[int]) -> None:
    """Marca N conversas como lidas em uma unica query."""
    if not conv_ids:
        return
    now = datetime.utcnow().isoformat()
    placeholders = ",".join("?" * len(conv_ids))
    db.execute(
        f"UPDATE conversations SET unread_count=0, updated_at=? WHERE id IN ({placeholders})",
        (now, *conv_ids),
    )


def mark_unread(conv_id: int) -> None:
    """Marca como não lida (garante unread_count >= 1)."""
    if db.DB_DRIVER == "postgresql":
        db.execute(
            "UPDATE conversations SET unread_count=GREATEST(unread_count,1), updated_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), conv_id),
        )
    else:
        db.execute(
            "UPDATE conversations SET unread_count=MAX(unread_count,1), updated_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), conv_id),
        )


def mark_unread_bulk(conv_ids: list[int]) -> None:
    """Marca N conversas como nao lidas em uma unica query."""
    if not conv_ids:
        return
    now = datetime.utcnow().isoformat()
    placeholders = ",".join("?" * len(conv_ids))
    if db.DB_DRIVER == "postgresql":
        db.execute(
            f"UPDATE conversations SET unread_count=GREATEST(unread_count,1), updated_at=? WHERE id IN ({placeholders})",
            (now, *conv_ids),
        )
    else:
        db.execute(
            f"UPDATE conversations SET unread_count=MAX(unread_count,1), updated_at=? WHERE id IN ({placeholders})",
            (now, *conv_ids),
        )


def count_unread_human_conversations() -> int:
    """Conta conversas em modo humano (auto_mode=0) que não foram lidas (unread_count > 0)."""
    row = db.fetch_one(
        "SELECT COUNT(*) as cnt FROM conversations c "
        "JOIN contacts ct ON c.contact_id=ct.id "
        "WHERE ct.auto_mode=0 AND c.unread_count>0 AND c.archived=0"
    )
    return row["cnt"] if row else 0


def clear_conversation(conv_id: int) -> None:
    """Remove todas as mensagens da conversa (mantém o chat/contato)."""
    db.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
    db.execute(
        "UPDATE conversations SET unread_count=0, last_message_at=NULL, updated_at=? WHERE id=?",
        (datetime.utcnow().isoformat(), conv_id),
    )


def delete_conversation(conv_id: int) -> None:
    """Remove todas as dependências FK e a própria conversa."""
    for tbl in ("crm_follow_ups", "crm_logs", "agendamentos"):
        try:
            db.execute(f"DELETE FROM {tbl} WHERE conversation_id=?", (conv_id,))
        except Exception:
            pass
    db.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
    db.execute("DELETE FROM conversation_tags WHERE conversation_id=?", (conv_id,))
    db.execute("DELETE FROM conversations WHERE id=?", (conv_id,))


# ── Conversation States (Sub-agentes) ────────────────────────────────────────

def agora_utc() -> str:
    """O "agora" que vai para o banco. SEMPRE UTC, com segundos.

    Todo carimbo daqui (created_at, updated_at) nasce de datetime.utcnow(), e o
    painel confia nisso: static/app.js renderiza a data somando "Z" ao texto
    ("new Date(c.last_message_at + 'Z')"), ou seja, LE o valor como UTC.

    Quem gravava last_message_at e last_interaction_at era time.strftime(), que
    devolve a hora LOCAL da maquina. Enquanto o app roda num servidor em UTC as
    duas coincidem e nada aparece. Rodando fora de UTC, a mesma conversa fica
    com created_at em UTC e last_message_at deslocado - e o painel, que soma
    "Z" nos dois, mostra a conversa horas mais cedo do que ela foi.

    Existe para que ninguem mais precise lembrar disso: chame esta funcao.
    """
    return datetime.utcnow().isoformat(timespec="seconds")


def save_conversation_state(phone: str, state: dict) -> None:
    """Salva estado da conversa (sub-agentes) pelo phone."""
    now = datetime.utcnow().isoformat()
    state_json = json.dumps(state, ensure_ascii=False, default=str)
    existing = db.fetch_one("SELECT phone FROM conversation_states WHERE phone=?", (phone,))
    if existing:
        db.execute(
            "UPDATE conversation_states SET state=?, updated_at=? WHERE phone=?",
            (state_json, now, phone),
        )
    else:
        db.execute(
            "INSERT INTO conversation_states (phone, state, updated_at) VALUES (?,?,?)",
            (phone, state_json, now),
        )


def get_conversation_state(phone: str) -> dict | None:
    """Carrega estado da conversa (sub-agentes) pelo phone."""
    row = db.fetch_one("SELECT state FROM conversation_states WHERE phone=?", (phone,))
    if row:
        raw = row["state"] if isinstance(row, dict) else row[0]
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return None
        return raw
    return None


def delete_conversation_state(phone: str) -> None:
    """Deleta estado da conversa pelo phone."""
    db.execute("DELETE FROM conversation_states WHERE phone=?", (phone,))


# ── Messages ──────────────────────────────────────────────────────────────────

def save_message(
    conversation_id: int,
    phone: str,
    direction: str,
    body: str,
    sender: str = "",
    msg_type: str = "text",
    media_url: str = "",
    wa_message_id: str = "",
    status: str = "sent",
    wa_media_id: str = "",
) -> dict | None:
    """Salva mensagem com idempotencia via wa_message_id. Retorna a mensagem ou None se duplicata."""
    wa_msg_clean = wa_message_id if wa_message_id else None
    if wa_msg_clean:
        existing = db.fetch_one("SELECT id FROM messages WHERE wa_message_id=?", (wa_msg_clean,))
        if existing:
            return None

    now = datetime.utcnow().isoformat()
    msg_id = db.execute_returning(
        "INSERT INTO messages (conversation_id, phone, wa_message_id, direction, sender, body, msg_type, media_url, status, created_at, wa_media_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (conversation_id, phone, wa_msg_clean, direction, sender, body, msg_type, media_url, status, now, wa_media_id or ""),
    )
    print(f"[db] save_message: msg_id={msg_id} wa_msg_clean={wa_msg_clean} direction={direction}")
    if msg_id:
        return db.fetch_one("SELECT * FROM messages WHERE id=?", (msg_id,))
    print(f"[db] save_message: FALHA - msg_id is None!")
    return None


def mensagem_ja_recebida(wa_message_id: str) -> bool:
    """A Meta ja entregou esta mensagem antes?

    save_message devolve None em dois casos bem diferentes: duplicata e falha
    ao gravar. Quem decide se PROCESSA a mensagem precisa saber qual dos dois
    foi — descartar uma duplicata e o certo, descartar uma falha de banco e
    perder o cliente. Por isso a pergunta e feita em separado.
    """
    if not wa_message_id:
        return False
    try:
        return bool(db.fetch_one(
            "SELECT 1 FROM messages WHERE wa_message_id=?", (wa_message_id,)
        ))
    except Exception as e:
        # Na duvida, processa: responder duas vezes incomoda, nao responder perde.
        print(f"[db] WARN mensagem_ja_recebida({wa_message_id}): {e}")
        return False


def update_message_media(msg_id: int, media_url: str) -> None:
    """Guarda o data-URI base64 da média baixada (image/audio/video/sticker)."""
    try:
        db.execute(
            "UPDATE messages SET media_url=? WHERE id=?",
            (media_url or "", int(msg_id)),
        )
    except Exception as e:
        print(f"[db] update_message_media: {e}")


def get_message(msg_id: int) -> dict | None:
    return db.fetch_one("SELECT * FROM messages WHERE id=?", (msg_id,))


def get_messages(conversation_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
    """As `limit` mensagens MAIS RECENTES, em ordem cronologica para exibir.

    Era "ORDER BY created_at ASC LIMIT 200", que devolve as 200 mais ANTIGAS: a
    conversa aberta no painel parava no comeco e nunca chegava no fim. Na
    conversa do dono, com 765 mensagens, o painel mostrava ate 22/09 17h01 e
    escondia as outras 565 - inclusive a bateria inteira de 26/09 que ele tinha
    acabado de rodar. Ele viu a mensagem certa na LISTA (que le
    last_message_at) e a conversa velha ao ABRIR, o que e exatamente esse
    descasamento.

    `offset` continua sendo "pule as N mais recentes", que e como se pagina
    conversa - para tras, a partir do fim.
    """
    recentes = db.fetch_all(
        "SELECT * FROM messages WHERE conversation_id=? "
        "ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (conversation_id, limit, offset),
    )
    # A consulta vem do mais novo para o mais velho porque e assim que se pega
    # "as ultimas N"; a tela le de cima para baixo.
    return list(reversed(list(recentes)))


def search_messages(query: str, limit: int = 50) -> list[dict]:
    return db.fetch_all(
        "SELECT m.*, c.id as conv_id, ct.name as contact_name "
        "FROM messages m "
        "JOIN conversations c ON m.conversation_id=c.id "
        "LEFT JOIN contacts ct ON c.contact_id=ct.id "
        "WHERE m.body LIKE ? ORDER BY m.created_at DESC LIMIT ?",
        (f"%{query}%", limit),
    )


# ── Tags ──────────────────────────────────────────────────────────────────────

def create_tag(name: str, color: str = "#6366f1") -> dict:
    db.execute("INSERT INTO tags (name, color) VALUES (?,?)", (name, color))
    return db.fetch_one("SELECT * FROM tags WHERE name=?", (name,))


def list_tags() -> list[dict]:
    return db.fetch_all("SELECT * FROM tags ORDER BY name")


def get_tag(tag_id: int) -> dict | None:
    return db.fetch_one("SELECT * FROM tags WHERE id=?", (tag_id,))


def update_tag(tag_id: int, name: str = "", color: str = "") -> None:
    sets, vals = [], []
    if name:
        sets.append("name=?")
        vals.append(name)
    if color:
        sets.append("color=?")
        vals.append(color)
    if sets:
        vals.append(tag_id)
        db.execute(f"UPDATE tags SET {','.join(sets)} WHERE id=?", tuple(vals))


def delete_tag(tag_id: int) -> None:
    db.execute("DELETE FROM contact_tags WHERE tag_id=?", (tag_id,))
    db.execute("DELETE FROM conversation_tags WHERE tag_id=?", (tag_id,))
    db.execute("DELETE FROM tags WHERE id=?", (tag_id,))


def add_tag_to_contact(contact_id: int, tag_id: int) -> None:
    db.insert_ignore("contact_tags", ["contact_id", "tag_id"], (contact_id, tag_id))


def remove_tag_from_contact(contact_id: int, tag_id: int) -> None:
    db.execute("DELETE FROM contact_tags WHERE contact_id=? AND tag_id=?", (contact_id, tag_id))


def get_contact_tags(contact_id: int) -> list[dict]:
    return db.fetch_all(
        "SELECT t.* FROM tags t JOIN contact_tags ct ON t.id=ct.tag_id WHERE ct.contact_id=?",
        (contact_id,),
    )


def add_tag_to_conversation(conversation_id: int, tag_id: int) -> None:
    db.insert_ignore("conversation_tags", ["conversation_id", "tag_id"], (conversation_id, tag_id))


def get_conversation_tags(conversation_id: int) -> list[dict]:
    return db.fetch_all(
        "SELECT t.* FROM tags t JOIN conversation_tags ct ON t.id=ct.tag_id WHERE ct.conversation_id=?",
        (conversation_id,),
    )


# ── Templates ─────────────────────────────────────────────────────────────────

def create_template(title: str, body: str) -> dict:
    now = datetime.utcnow().isoformat()
    tpl_id = db.execute_returning("INSERT INTO templates (title, body, created_at) VALUES (?,?,?)", (title, body, now))
    return db.fetch_one("SELECT * FROM templates WHERE id=?", (tpl_id,))


def list_templates() -> list[dict]:
    return db.fetch_all("SELECT * FROM templates ORDER BY title")


def get_template(tpl_id: int) -> dict | None:
    return db.fetch_one("SELECT * FROM templates WHERE id=?", (tpl_id,))


def update_template(tpl_id: int, title: str = "", body: str = "") -> None:
    sets, vals = [], []
    if title:
        sets.append("title=?")
        vals.append(title)
    if body:
        sets.append("body=?")
        vals.append(body)
    if sets:
        vals.append(tpl_id)
        db.execute(f"UPDATE templates SET {','.join(sets)} WHERE id=?", tuple(vals))


def delete_template(tpl_id: int) -> None:
    db.execute("DELETE FROM templates WHERE id=?", (tpl_id,))


# ── Tasks ─────────────────────────────────────────────────────────────────────

def create_task(contact_id: int, title: str, description: str = "", due_date: str = "") -> dict:
    now = datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO tasks (contact_id, title, description, due_date, created_at) VALUES (?,?,?,?,?)",
        (contact_id, title, description, due_date, now),
    )
    return db.fetch_one("SELECT * FROM tasks WHERE title=? AND contact_id=?", (title, contact_id))


def list_tasks(contact_id: int | None = None) -> list[dict]:
    if contact_id:
        return db.fetch_all(
            "SELECT * FROM tasks WHERE contact_id=? ORDER BY created_at DESC", (contact_id,)
        )
    return db.fetch_all("SELECT * FROM tasks ORDER BY created_at DESC")


def update_task(task_id: int, **fields: Any) -> None:
    allowed = ("title", "description", "status", "due_date")
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if sets:
        vals.append(task_id)
        db.execute(f"UPDATE tasks SET {','.join(sets)} WHERE id=?", tuple(vals))


def delete_task(task_id: int) -> None:
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))


# ── Dashboard / Stats ─────────────────────────────────────────────────────────

def get_dashboard_stats() -> dict:
    total_contacts = db.fetch_one("SELECT COUNT(*) as cnt FROM contacts")["cnt"]
    total_conversations = db.fetch_one("SELECT COUNT(*) as cnt FROM conversations")["cnt"]
    open_conversations = db.fetch_one(
        "SELECT COUNT(*) as cnt FROM conversations WHERE status IN ('new','open','waiting')"
    )["cnt"]
    total_messages = db.fetch_one("SELECT COUNT(*) as cnt FROM messages")["cnt"]
    unread_messages = db.fetch_one(
        "SELECT COALESCE(SUM(unread_count),0) as cnt FROM conversations"
    )["cnt"]
    # "Mensagens hoje" e o hoje do CONSULTORIO, mas created_at esta em UTC. O
    # corte e a meia-noite local (TZ_OFFSET_HORAS), convertida para UTC antes
    # de ir ao banco; comparar a data local crua contava errado nas horas em
    # que os dois calendarios divergem.
    import os
    try:
        offset = timedelta(hours=float(os.getenv("TZ_OFFSET_HORAS", "-3")))
    except ValueError:
        offset = timedelta(hours=-3)
    inicio_local = (datetime.utcnow() + offset).replace(hour=0, minute=0, second=0, microsecond=0)
    inicio = (inicio_local - offset).isoformat()
    messages_today = db.fetch_one(
        "SELECT COUNT(*) as cnt FROM messages WHERE created_at >= ?", (inicio,)
    )["cnt"]
    return {
        "total_contacts": total_contacts,
        "total_conversations": total_conversations,
        "open_conversations": open_conversations,
        "total_messages": total_messages,
        "unread_messages": unread_messages,
        "messages_today": messages_today,
    }


# ── Knowledge (RAG) ──────────────────────────────────────────────────────────

def insert_knowledge_chunks(filename: str, chunks: list[str], embeddings: list) -> None:
    """Insere chunks de knowledge com embeddings."""
    now = datetime.utcnow().isoformat()
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        if db.DB_DRIVER == "postgresql" and emb is not None:
            # Converte lista para string pgvector: '[0.1, 0.2, ...]'
            emb_str = "[" + ",".join(str(x) for x in emb) + "]"
            db.execute(
                "INSERT INTO knowledge (filename, chunk_index, content, embedding, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (filename, i, chunk, emb_str, now, now),
            )
        elif emb is not None:
            db.execute(
                "INSERT INTO knowledge (filename, chunk_index, content, embedding, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (filename, i, chunk, json.dumps(emb), now, now),
            )
        else:
            db.execute(
                "INSERT INTO knowledge (filename, chunk_index, content, created_at, updated_at) "
                "VALUES (?,?,?, ?,?)",
                (filename, i, chunk, now, now),
            )


def _cosseno(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    dbb = sum(y * y for y in b) ** 0.5
    return num / (da * dbb) if da and dbb else 0.0


def _busca_vetorial_sqlite(query_embedding: list[float], top_k: int) -> list[dict]:
    rows = db.fetch_all("SELECT * FROM knowledge WHERE embedding IS NOT NULL AND embedding <> ''")
    pontuados = []
    for r in rows:
        try:
            vetor = json.loads(r["embedding"])
        except (TypeError, ValueError):
            continue
        r = dict(r)
        r.pop("embedding", None)
        r["similarity"] = _cosseno(query_embedding, vetor)
        pontuados.append(r)
    pontuados.sort(key=lambda r: r["similarity"], reverse=True)
    return pontuados[:top_k]


def search_knowledge(query_embedding: list[float], top_k: int = 5, query_text: str = "") -> list[dict]:
    """Busca chunks por cosine similarity. Fallback para LIKE se pgvector indisponível."""
    if db.DB_DRIVER != "postgresql":
        # SQLite: similaridade de cosseno em Python sobre os vetores em JSON.
        if query_embedding:
            rows = _busca_vetorial_sqlite(query_embedding, top_k)
            if rows:
                return rows
        # Sem embeddings: busca textual por LIKE
        if query_text:
            keywords = [w.strip() for w in query_text.split() if len(w.strip()) >= 3]
            if keywords:
                like_conditions = " OR ".join(["content LIKE ?"] * len(keywords))
                like_params = [f"%{kw}%" for kw in keywords]
                rows = db.fetch_all(
                    f"SELECT * FROM knowledge WHERE {like_conditions} ORDER BY filename, chunk_index LIMIT ?",
                    (*like_params, top_k),
                )
                if rows:
                    return rows
        return []

    # PostgreSQL: busca vetorial com pgvector
    emb_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    try:
        rows = db.fetch_all(
            "SELECT *, 1 - (embedding <=> %s::vector) AS similarity "
            "FROM knowledge "
            "WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> %s::vector "
            "LIMIT %s",
            (emb_str, emb_str, top_k),
        )
        if rows:
            return rows
    except Exception as e:
        print(f"[db] WARN: busca vetorial falhou, usando LIKE: {e}")

    # Fallback PostgreSQL: busca textual por LIKE
    if query_text:
        keywords = [w.strip() for w in query_text.split() if len(w.strip()) >= 3]
        if keywords:
            like_conditions = " OR ".join(["content LIKE %s"] * len(keywords))
            like_params = [f"%{kw}%" for kw in keywords]
            try:
                rows = db.fetch_all(
                    f"SELECT * FROM knowledge WHERE {like_conditions} ORDER BY filename, chunk_index LIMIT %s",
                    (*like_params, top_k),
                )
                if rows:
                    return rows
            except Exception:
                pass

    return []


def list_knowledge_files() -> list[dict]:
    """Lista arquivos distintos com contagem de chunks e descrição."""
    rows = db.fetch_all(
        "SELECT k.filename, COUNT(*) as chunks, kf.description, MIN(k.created_at) as created_at "
        "FROM knowledge k LEFT JOIN knowledge_files kf ON k.filename = kf.filename "
        "GROUP BY k.filename, kf.description ORDER BY k.filename"
    )
    return rows


def get_all_knowledge_content() -> list[dict]:
    """Retorna todos os chunks de todos os arquivos knowledge, ordenados por filename + chunk_index."""
    return db.fetch_all(
        "SELECT filename, chunk_index, content FROM knowledge ORDER BY filename, chunk_index"
    )


def get_knowledge_chunks(filename: str) -> list[dict]:
    """Retorna todos os chunks de um arquivo."""
    return db.fetch_all(
        "SELECT * FROM knowledge WHERE filename=? ORDER BY chunk_index",
        (filename,),
    )


def delete_knowledge_file(filename: str) -> None:
    """Deleta todos os chunks de um arquivo e sua descrição."""
    db.execute("DELETE FROM knowledge WHERE filename=?", (filename,))
    db.execute("DELETE FROM knowledge_files WHERE filename=?", (filename,))


# ── Knowledge Files (descrições) ──────────────────────────────────────────────


# ── Documento original (fonte da verdade, sem perdas de chunking) ────────────

def set_knowledge_document(filename: str, content: str, description: str = "", status: str = "indexed") -> None:
    """Guarda o texto ORIGINAL completo do arquivo.

    Os chunks da tabela `knowledge` existem só para busca semântica; a
    reconstrução do documento a partir deles é lossy (quebras e sobreposição).
    Esta coluna preserva o texto exato que o agente deve ler.
    """
    now = datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO knowledge_files (filename, description, content, status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(filename) DO UPDATE SET "
        "description=CASE WHEN EXCLUDED.description = '' THEN knowledge_files.description "
        "ELSE EXCLUDED.description END, "
        "content=EXCLUDED.content, status=EXCLUDED.status, updated_at=EXCLUDED.updated_at",
        (filename, description, content, status, now, now),
    )


def get_knowledge_document(filename: str) -> str:
    """Retorna o texto original de um arquivo (vazio se não houver)."""
    try:
        row = db.fetch_one("SELECT content FROM knowledge_files WHERE filename=?", (filename,))
    except Exception:
        return ""
    if not row:
        return ""
    return (row.get("content") or "") if isinstance(row, dict) else ""


def get_all_knowledge_documents() -> list[dict]:
    """Retorna {filename, description, content} de todos os arquivos com texto original."""
    try:
        return db.fetch_all(
            "SELECT filename, description, content FROM knowledge_files "
            "WHERE content IS NOT NULL AND content <> '' ORDER BY filename"
        )
    except Exception:
        return []


def get_knowledge_file_status(filename: str) -> str:
    """Status do arquivo (pending/indexed/error), vazio se nao existir."""
    row = db.fetch_one("SELECT status FROM knowledge_files WHERE filename=?", (filename,))
    return (row.get("status") or "") if isinstance(row, dict) else ""


def get_knowledge_file_description(filename: str) -> str:
    """Retorna a descrição de um arquivo knowledge."""
    row = db.fetch_one("SELECT description FROM knowledge_files WHERE filename=?", (filename,))
    return row["description"] if row else ""


def get_all_knowledge_descriptions() -> list[dict]:
    """Retorna todos os arquivos com suas descrições (para montar o índice)."""
    return db.fetch_all(
        "SELECT filename, description FROM knowledge_files ORDER BY filename"
    )


# ── Knowledge Batch Operations ────────────────────────────────────────────────

def list_knowledge_files_with_status() -> list[dict]:
    """Lista arquivos com status (pending/indexed/error)."""
    rows = db.fetch_all(
        "SELECT kf.filename, kf.description, kf.status, "
        "COALESCE(COUNT(k.id), 0) as chunks "
        "FROM knowledge_files kf "
        "LEFT JOIN knowledge k ON k.filename = kf.filename "
        "GROUP BY kf.filename, kf.description, kf.status "
        "ORDER BY kf.filename"
    )
    return rows


def update_knowledge_file_status(filename: str, status: str) -> None:
    """Atualiza o status de um arquivo (pending/indexed/error)."""
    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE knowledge_files SET status=?, updated_at=? WHERE filename=?",
        (status, now, filename),
    )


def clear_knowledge_embeddings() -> int:
    """Remove todos os embeddings, mantendo conteúdo. Retorna qtd de chunks afetados."""
    rows = db.fetch_all("SELECT id FROM knowledge WHERE embedding IS NOT NULL")
    db.execute("UPDATE knowledge SET embedding = NULL")
    print(f"[db] embeddings limpos: {len(rows)} chunks")
    return len(rows)


def set_all_knowledge_pending() -> None:
    """Marca todos os knowledge_files como pending (após limpar embeddings)."""
    now = datetime.utcnow().isoformat()
    db.execute("UPDATE knowledge_files SET status='pending', updated_at=?", (now,))


def delete_all_knowledge() -> int:
    """Deleta todos os chunks e metadados. Retorna qtd de arquivos deletados."""
    files = db.fetch_all("SELECT DISTINCT filename FROM knowledge")
    db.execute("DELETE FROM knowledge")
    db.execute("DELETE FROM knowledge_files")
    print(f"[db] todo knowledge deletado: {len(files)} arquivos")
    return len(files)


def get_pending_knowledge_files() -> list[dict]:
    """Retorna arquivos com status='pending'."""
    return db.fetch_all(
        "SELECT filename, description FROM knowledge_files WHERE status='pending' ORDER BY filename"
    )


def delete_knowledge_chunks_by_filename(filename: str) -> None:
    """Deleta apenas os chunks (não os metadados)."""
    db.execute("DELETE FROM knowledge WHERE filename=?", (filename,))


# ── Memory Recovery (load history from DB into memory on restart) ────────────


def get_reset_at(phone: str) -> str:
    """Instante do ultimo #reset dessa conversa (vazio se nunca houve)."""
    row = db.fetch_one(
        "SELECT cv.reset_at FROM conversations cv "
        "JOIN contacts ct ON ct.id = cv.contact_id "
        "WHERE ct.phone=? ORDER BY cv.id DESC LIMIT 1",
        (phone,),
    )
    return (row or {}).get("reset_at") or ""


def get_recent_messages(phone: str, limit: int = 20) -> list[dict]:
    """Retorna últimas mensagens no formato para memory.py.

    Mensagens anteriores ao ultimo #reset ficam de fora: o ponto do #reset e
    justamente "esqueca o que veio antes". Elas continuam no banco e no painel,
    so nao voltam para o contexto do agente.

    Notas internas (direction='internal') tambem ficam de fora. Elas sao
    recado de sistema para a equipe — "Transferido pelo agente em 19/09
    22h26" — e entravam no historico como se o agente tivesse dito aquilo
    ao cliente.
    """
    corte = ""
    try:
        corte = get_reset_at(phone)
    except Exception as e:
        print(f"[db] WARN nao leu reset_at de {phone}: {e}")
    if corte:
        rows = db.fetch_all(
            "SELECT direction, body FROM messages WHERE phone=? AND body <> '' "
            "AND direction IN ('in','out') AND created_at > ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (phone, corte, limit),
        )
    else:
        rows = db.fetch_all(
            "SELECT direction, body FROM messages WHERE phone=? AND body <> '' "
            "AND direction IN ('in','out') "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (phone, limit),
        )
    if not rows:
        return []
    messages = []
    for r in reversed(rows):
        role = "user" if r["direction"] == "in" else "assistant"
        messages.append({"role": role, "parts": [{"text": r["body"]}]})
    return messages


# ── Agendamentos ─────────────────────────────────────────────────────────────
# Pedido confirmado pelo paciente no WhatsApp entra como 'pendente' (aba
# Confirmação de Agendamento). A equipe escolhe dia e hora: vira 'confirmado'
# e aparece na Agenda. 'cancelado' sai das duas. `inicio` e hora LOCAL do
# consultorio em ISO ("2026-10-08T09:00"), que e o que a equipe ve e digita.

_CAMPOS_AGENDAMENTO = ("status", "inicio", "duracao_min", "observacoes", "google_event_id",
                       "confirmado_em", "nome", "resumo")


def criar_agendamento(contact_id: int, conversation_id: int, phone: str, nome: str,
                      resumo: str, ficha: dict) -> dict:
    now = agora_utc()
    ag_id = db.execute_returning(
        "INSERT INTO agendamentos (contact_id, conversation_id, phone, nome, resumo, ficha, "
        "status, created_at, updated_at) VALUES (?,?,?,?,?,?,'pendente',?,?)",
        (contact_id, conversation_id, phone, nome, resumo,
         json.dumps(ficha, ensure_ascii=False, default=str), now, now),
    )
    return obter_agendamento(ag_id)


def _agendamento_com_ficha(row: dict | None) -> dict | None:
    if not row:
        return None
    item = dict(row)
    try:
        item["ficha"] = json.loads(item.get("ficha") or "{}")
    except (TypeError, ValueError):
        item["ficha"] = {}
    return item


def obter_agendamento(ag_id: int) -> dict | None:
    return _agendamento_com_ficha(db.fetch_one("SELECT * FROM agendamentos WHERE id=?", (ag_id,)))


def listar_agendamentos(status: str = "", de: str = "", ate: str = "") -> list[dict]:
    """Pendentes por ordem de chegada; confirmados por data da consulta."""
    where, params = [], []
    if status:
        where.append("status=?")
        params.append(status)
    if de:
        where.append("inicio >= ?")
        params.append(de)
    if ate:
        where.append("inicio < ?")
        params.append(ate)
    sql = "SELECT * FROM agendamentos"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at ASC" if status == "pendente" else " ORDER BY inicio ASC, id ASC"
    return [_agendamento_com_ficha(r) for r in db.fetch_all(sql + " LIMIT 1000", tuple(params))]


def atualizar_agendamento(ag_id: int, **campos: Any) -> None:
    sets, vals = [], []
    for k, v in campos.items():
        if k in _CAMPOS_AGENDAMENTO:
            sets.append(f"{k}=?")
            vals.append(v)
    if sets:
        sets.append("updated_at=?")
        vals.extend([agora_utc(), ag_id])
        db.execute(f"UPDATE agendamentos SET {','.join(sets)} WHERE id=?", tuple(vals))


def contar_agendamentos_pendentes() -> int:
    row = db.fetch_one("SELECT COUNT(*) AS n FROM agendamentos WHERE status='pendente'")
    return int((row or {}).get("n") or 0)


def equipe_agiu_desde(conv_id: int, phone: str, desde: str) -> bool:
    """A equipe mexeu no caso depois de `desde` (ISO UTC)? Mensagem enviada pelo
    painel, ou agendamento do paciente confirmado/remarcado/cancelado."""
    if db.fetch_one("SELECT 1 AS x FROM messages WHERE conversation_id=? AND sender='human' "
                    "AND created_at > ? LIMIT 1", (conv_id, desde)):
        return True
    return bool(db.fetch_one("SELECT 1 AS x FROM agendamentos WHERE phone=? AND status<>'pendente' "
                             "AND updated_at > ? LIMIT 1", (phone, desde)))


def ids_eventos_google() -> set:
    """Eventos do Google que o painel criou (um por agendamento confirmado)."""
    linhas = db.fetch_all("SELECT google_event_id FROM agendamentos "
                          "WHERE google_event_id IS NOT NULL AND google_event_id <> ''")
    return {l["google_event_id"] for l in linhas}


def conflitos_de_horario(inicio: str, duracao_min: int, ignorar_id: int = 0) -> list[dict]:
    """Agendamentos confirmados que se sobrepoem ao horario pedido."""
    try:
        ini = datetime.fromisoformat(inicio)
    except ValueError:
        return []
    fim = ini + timedelta(minutes=duracao_min)
    dia = ini.strftime("%Y-%m-%d")
    candidatos = db.fetch_all(
        "SELECT id, nome, inicio, duracao_min FROM agendamentos "
        "WHERE status='confirmado' AND id<>? AND inicio >= ? AND inicio < ?",
        (ignorar_id, dia, (ini + timedelta(days=1)).strftime("%Y-%m-%d")),
    )
    saida = []
    for c in candidatos:
        try:
            c_ini = datetime.fromisoformat(c["inicio"])
        except (TypeError, ValueError):
            continue
        c_fim = c_ini + timedelta(minutes=int(c.get("duracao_min") or 60))
        if c_ini < fim and ini < c_fim:
            saida.append(dict(c))
    return saida


# ── CRM: Automações ─────────────────────────────────────────────────────────

def list_automations() -> list[dict]:
    return db.fetch_all("SELECT * FROM crm_automations ORDER BY created_at DESC")


def get_automation(automation_id: int) -> dict | None:
    return db.fetch_one("SELECT * FROM crm_automations WHERE id=?", (automation_id,))


def create_automation(**fields) -> dict:
    now = datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO crm_automations (name, days, hours, message_template, use_meta_template, "
        "meta_template_name, meta_template_language, action_tag_add, action_tag_remove, "
        "action_status_change, is_active, send_window_start, send_window_end, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            fields.get("name", ""),
            fields.get("days", 0),
            fields.get("hours", 0),
            fields.get("message_template", ""),
            fields.get("use_meta_template", 0),
            fields.get("meta_template_name", ""),
            fields.get("meta_template_language", "pt_BR"),
            fields.get("action_tag_add", ""),
            fields.get("action_tag_remove", ""),
            fields.get("action_status_change", ""),
            fields.get("is_active", 1),
            fields.get("send_window_start", "08:00"),
            fields.get("send_window_end", "18:00"),
            now,
            now,
        ),
    )
    return db.fetch_one("SELECT * FROM crm_automations WHERE created_at=?", (now,))


def update_automation(automation_id: int, **fields) -> None:
    allowed = (
        "name", "days", "hours", "message_template", "use_meta_template",
        "meta_template_name", "meta_template_language", "action_tag_add",
        "action_tag_remove", "action_status_change", "is_active",
        "send_window_start", "send_window_end",
    )
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if sets:
        sets.append("updated_at=?")
        vals.append(datetime.utcnow().isoformat())
        vals.append(automation_id)
        db.execute(f"UPDATE crm_automations SET {','.join(sets)} WHERE id=?", tuple(vals))


def delete_automation(automation_id: int) -> None:
    db.execute("DELETE FROM crm_follow_ups WHERE automation_id=?", (automation_id,))
    db.execute("DELETE FROM crm_automations WHERE id=?", (automation_id,))


# ── CRM: Follow-ups ─────────────────────────────────────────────────────────

def create_follow_up(automation_id: int, contact_id: int, scheduled_for: str) -> dict | None:
    """Cria follow-up pendente. Retorna None se já existir um pendente para esta automação+contato."""
    existing = db.fetch_one(
        "SELECT id FROM crm_follow_ups WHERE automation_id=? AND contact_id=? AND status='pendente'",
        (automation_id, contact_id),
    )
    if existing:
        return None
    now = agora_utc()
    fu_id = db.execute_returning(
        "INSERT INTO crm_follow_ups (automation_id, contact_id, scheduled_for, created_at) VALUES (?,?,?,?)",
        (automation_id, contact_id, scheduled_for, now),
    )
    if fu_id:
        return db.fetch_one("SELECT * FROM crm_follow_ups WHERE id=?", (fu_id,))
    return None


def get_pending_follow_ups() -> list[dict]:
    """Follow-ups pendentes que JA VENCERAM, com dados da automacao e contato.

    O filtro por scheduled_for e o que faz o prazo valer: sem ele a consulta
    devolvia todos os pendentes e o scheduler enviava tudo no tique seguinte,
    ignorando os dias configurados na automacao.
    """
    # scheduled_for e gravado em UTC (ver schedule_follow_ups_for_contact e o
    # reagendamento por janela no scheduler); o filtro compara em UTC.
    agora = datetime.utcnow().isoformat()
    return db.fetch_all(
        "SELECT fu.*, "
        "a.name as automation_name, a.message_template, a.use_meta_template, "
        "a.meta_template_name, a.meta_template_language, a.action_tag_add, "
        "a.action_tag_remove, a.action_status_change, a.send_window_start, a.send_window_end, "
        "c.name as contact_name, c.phone as contact_phone "
        "FROM crm_follow_ups fu "
        "JOIN crm_automations a ON fu.automation_id=a.id "
        "JOIN contacts c ON fu.contact_id=c.id "
        "WHERE fu.status='pendente' AND a.is_active=1 "
        "AND fu.scheduled_for <= ? "
        "ORDER BY fu.scheduled_for ASC",
        (agora,),
    )


def list_follow_ups(status: str = "", limit: int = 100, offset: int = 0) -> list[dict]:
    where = []
    params: list = []
    if status:
        where.append("fu.status=?")
        params.append(status)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.extend([limit, offset])
    return db.fetch_all(
        f"SELECT fu.*, a.name as automation_name, c.name as contact_name, c.phone as contact_phone "
        f"FROM crm_follow_ups fu "
        f"JOIN crm_automations a ON fu.automation_id=a.id "
        f"JOIN contacts c ON fu.contact_id=c.id "
        f"{where_sql} ORDER BY fu.created_at DESC LIMIT ? OFFSET ?",
        tuple(params),
    )


def update_follow_up_status(fu_id: int, status: str, sent_at: str = "", error_message: str = "", message_sent: str = "") -> None:
    sets = ["status=?"]
    vals: list = [status]
    if sent_at:
        sets.append("sent_at=?")
        vals.append(sent_at)
    if error_message:
        sets.append("error_message=?")
        vals.append(error_message)
    if message_sent:
        sets.append("message_sent=?")
        vals.append(message_sent)
    vals.append(fu_id)
    db.execute(f"UPDATE crm_follow_ups SET {','.join(sets)} WHERE id=?", tuple(vals))


def update_follow_up_scheduled(fu_id: int, new_scheduled_for: str) -> None:
    db.execute("UPDATE crm_follow_ups SET scheduled_for=? WHERE id=?", (new_scheduled_for, fu_id))


def cancel_follow_ups_for_contact(contact_id: int) -> int:
    """Cancela todos os follow-ups pendentes de um contato. Retorna qtd cancelada."""
    result = db.execute(
        "UPDATE crm_follow_ups SET status='cancelado' WHERE contact_id=? AND status='pendente'",
        (contact_id,),
    )
    # O docstring sempre prometeu a quantidade, mas o retorno era 0 fixo.
    try:
        return int(result or 0)
    except (TypeError, ValueError):
        return 0


def get_follow_ups_stats() -> dict:
    """Contagem dos follow-ups em UMA consulta (eram 5, uma ida ao banco cada)."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    row = db.fetch_one(
        "SELECT "
        "COALESCE(SUM(CASE WHEN status='pendente' THEN 1 ELSE 0 END), 0) AS pending, "
        "COALESCE(SUM(CASE WHEN status='enviado' THEN 1 ELSE 0 END), 0) AS sent, "
        "COALESCE(SUM(CASE WHEN status='enviado' AND sent_at >= ? THEN 1 ELSE 0 END), 0) AS sent_today, "
        "COALESCE(SUM(CASE WHEN status='cancelado' THEN 1 ELSE 0 END), 0) AS cancelled, "
        "COALESCE(SUM(CASE WHEN status='erro' THEN 1 ELSE 0 END), 0) AS errors "
        "FROM crm_follow_ups",
        (today,),
    ) or {}
    return {k: int(row.get(k) or 0) for k in ("pending", "sent", "sent_today", "cancelled", "errors")}


# ── CRM: Logs ───────────────────────────────────────────────────────────────

def create_crm_log(automation_id: int = 0, contact_id: int = 0, action: str = "send",
                   message: str = "", result: str = "", error: str = "") -> dict:
    now = datetime.utcnow().isoformat()
    log_id = db.execute_returning(
        "INSERT INTO crm_logs (automation_id, contact_id, action, message, result, error, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (automation_id, contact_id, action, message, result, error, now),
    )
    if log_id:
        return db.fetch_one("SELECT * FROM crm_logs WHERE id=?", (log_id,))
    return {}


def list_crm_logs(limit: int = 100, offset: int = 0) -> list[dict]:
    return db.fetch_all(
        "SELECT l.*, a.name as automation_name, c.name as contact_name, c.phone as contact_phone "
        "FROM crm_logs l "
        "LEFT JOIN crm_automations a ON l.automation_id=a.id "
        "LEFT JOIN contacts c ON l.contact_id=c.id "
        "ORDER BY l.created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )


# ── CRM: Contatos ───────────────────────────────────────────────────────────

def list_contacts_crm(status: str = "", tag_id: int = 0, days_without: int = 0,
                      has_follow_up: str = "", search: str = "",
                      limit: int = 100, offset: int = 0) -> list[dict]:
    """Lista contatos CRM com filtros."""
    where = []
    params: list = []

    if status:
        where.append("ct.crm_status=?")
        params.append(status)

    if tag_id:
        where.append("ct.id IN (SELECT contact_id FROM contact_tags WHERE tag_id=?)")
        params.append(tag_id)

    if days_without > 0:
        cutoff = (datetime.utcnow() - timedelta(days=days_without)).strftime("%Y-%m-%dT%H:%M:%S")
        where.append(
            "ct.last_interaction_at IS NOT NULL AND ct.last_interaction_at < ?"
        )
        params.append(cutoff)

    if has_follow_up == "sim":
        where.append("ct.id IN (SELECT contact_id FROM crm_follow_ups WHERE status='pendente')")
    elif has_follow_up == "nao":
        where.append("ct.id NOT IN (SELECT contact_id FROM crm_follow_ups WHERE status='pendente')")

    if search:
        where.append("(ct.name LIKE ? OR ct.phone LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.extend([limit, offset])

    rows = db.fetch_all(
        f"SELECT ct.*, "
        f"(SELECT c.last_message_at FROM conversations c WHERE c.contact_id=ct.id ORDER BY c.id DESC LIMIT 1) as last_message_at "
        f"FROM contacts ct "
        f"{where_sql} ORDER BY ct.last_interaction_at DESC NULLS LAST LIMIT ? OFFSET ?",
        tuple(params),
    )

    # Adicionar tags e dias sem interação
    result = []
    now = datetime.utcnow()
    for r in rows:
        item = dict(r)
        item["tags"] = get_contact_tags(item["id"])
        # Calcular dias sem interação
        lia = item.get("last_interaction_at")
        if lia:
            try:
                li_dt = datetime.fromisoformat(lia.replace("Z", "+00:00").replace("+00:00", ""))
                delta = now - li_dt
                item["days_without_interaction"] = delta.days
            except Exception:
                item["days_without_interaction"] = None
        else:
            item["days_without_interaction"] = None
        result.append(item)

    return result


# Campos de mensagem que o perfil do CRM mostra. Sem media_url: ela guarda a
# midia inteira em base64 e pesava megabytes numa tela que so mostra texto.
_CAMPOS_MSG_CRM = "id, direction, body, msg_type, created_at"
_LIMITE_MSGS_CRM = 100


def _detalhe_crm_postgres(contact_id: int) -> dict | None:
    """Perfil do contato inteiro em UMA consulta (json montado no banco)."""
    row = db.fetch_one(
        "SELECT row_to_json(ct) AS contato, "
        " (SELECT COALESCE(json_agg(t ORDER BY t.name), '[]'::json) FROM "
        "   (SELECT tg.* FROM tags tg JOIN contact_tags x ON x.tag_id = tg.id "
        "    WHERE x.contact_id = ct.id) t) AS tags, "
        " (SELECT COALESCE(json_agg(t ORDER BY t.name), '[]'::json) FROM tags t) AS all_tags, "
        " (SELECT COALESCE(json_agg(f ORDER BY f.created_at DESC), '[]'::json) FROM "
        "   (SELECT fu.*, a.name AS automation_name FROM crm_follow_ups fu "
        "    JOIN crm_automations a ON fu.automation_id = a.id WHERE fu.contact_id = ct.id) f) AS follow_ups, "
        " (SELECT COALESCE(json_agg(l ORDER BY l.created_at DESC), '[]'::json) FROM "
        "   (SELECT lg.*, a.name AS automation_name FROM crm_logs lg "
        "    LEFT JOIN crm_automations a ON lg.automation_id = a.id WHERE lg.contact_id = ct.id "
        "    ORDER BY lg.created_at DESC LIMIT 50) l) AS logs, "
        " (SELECT COALESCE(json_agg(tk ORDER BY tk.created_at DESC), '[]'::json) FROM "
        "   (SELECT * FROM tasks WHERE contact_id = ct.id) tk) AS tasks, "
        " (SELECT id FROM conversations WHERE contact_id = ct.id ORDER BY id DESC LIMIT 1) AS conversation_id, "
        " (SELECT COALESCE(json_agg(m ORDER BY m.created_at, m.id), '[]'::json) FROM "
        f"   (SELECT {_CAMPOS_MSG_CRM} FROM messages WHERE conversation_id = "
        "     (SELECT id FROM conversations WHERE contact_id = ct.id ORDER BY id DESC LIMIT 1) "
        f"    ORDER BY created_at DESC, id DESC LIMIT {_LIMITE_MSGS_CRM}) m) AS messages "
        "FROM contacts ct WHERE ct.id = ?",
        (contact_id,),
    )
    if not row or not row.get("contato"):
        return None
    item = dict(row["contato"])
    for campo in ("tags", "all_tags", "follow_ups", "logs", "tasks", "messages"):
        item[campo] = row.get(campo) or []
    item["conversation_id"] = row.get("conversation_id")
    return item


def _detalhe_crm_sqlite(contact_id: int) -> dict | None:
    contact = get_contact_by_id(contact_id)
    if not contact:
        return None
    item = dict(contact)
    item["tags"] = get_contact_tags(contact_id)
    item["all_tags"] = list_tags()
    item["follow_ups"] = db.fetch_all(
        "SELECT fu.*, a.name as automation_name "
        "FROM crm_follow_ups fu JOIN crm_automations a ON fu.automation_id=a.id "
        "WHERE fu.contact_id=? ORDER BY fu.created_at DESC",
        (contact_id,),
    )
    item["tasks"] = db.fetch_all(
        "SELECT * FROM tasks WHERE contact_id=? ORDER BY created_at DESC", (contact_id,)
    )
    item["logs"] = db.fetch_all(
        "SELECT l.*, a.name as automation_name "
        "FROM crm_logs l LEFT JOIN crm_automations a ON l.automation_id=a.id "
        "WHERE l.contact_id=? ORDER BY l.created_at DESC LIMIT 50",
        (contact_id,),
    )
    conv = db.fetch_one(
        "SELECT id FROM conversations WHERE contact_id=? ORDER BY id DESC LIMIT 1", (contact_id,)
    )
    item["conversation_id"] = conv["id"] if conv else None
    msgs = db.fetch_all(
        f"SELECT {_CAMPOS_MSG_CRM} FROM messages WHERE conversation_id=? "
        f"ORDER BY created_at DESC, id DESC LIMIT {_LIMITE_MSGS_CRM}",
        (item["conversation_id"],),
    ) if conv else []
    item["messages"] = list(reversed(msgs))
    return item


def get_crm_contact_detail(contact_id: int) -> dict | None:
    """Detalhe completo do contato CRM, com tags, tarefas e mensagens.

    O painel fazia 4 pedidos em sequência para montar esta tela (detalhe,
    todas as tags, as 50 últimas conversas para achar a deste contato e a
    conversa inteira, com as mídias em base64). Agora vem tudo aqui.
    """
    item = (_detalhe_crm_postgres(contact_id) if db.DB_DRIVER == "postgresql"
            else _detalhe_crm_sqlite(contact_id))
    if not item:
        return None
    lia = item.get("last_interaction_at")
    now = datetime.utcnow()
    if lia:
        try:
            li_dt = datetime.fromisoformat(lia.replace("Z", "+00:00").replace("+00:00", ""))
            item["days_without_interaction"] = (now - li_dt).days
        except Exception:
            item["days_without_interaction"] = None
    else:
        item["days_without_interaction"] = None
    return item


def get_crm_dashboard_stats() -> dict:
    """Estatísticas do dashboard CRM em UMA consulta (eram 7, mais 5 dos follow-ups).

    Com o banco no Supabase cada consulta é uma ida e volta pela rede: doze
    seguidas deixavam a aba CRM lenta a cada abertura.
    """
    status = ("novo", "em_atendimento", "agendamento", "cliente", "inativo", "nao_interessado")
    somas = ", ".join(
        f"COALESCE(SUM(CASE WHEN crm_status='{s}' THEN 1 ELSE 0 END), 0) AS {s}" for s in status
    )
    row = db.fetch_one(f"SELECT COUNT(*) AS total_contacts, {somas} FROM contacts") or {}
    resultado = {"total_contacts": int(row.get("total_contacts") or 0)}
    resultado.update({s: int(row.get(s) or 0) for s in status})
    resultado["follow_ups"] = get_follow_ups_stats()
    return resultado


def create_follow_ups_for_contact(contact_id: int) -> int:
    """Cria follow-ups pendentes para um contato baseado nas automações ativas. Retorna qtd criada."""
    contact = get_contact_by_id(contact_id)
    if not contact:
        return 0
    last_interaction = contact.get("last_interaction_at")
    if not last_interaction:
        conv = db.fetch_one(
            "SELECT last_message_at FROM conversations WHERE contact_id=? ORDER BY id DESC LIMIT 1",
            (contact_id,),
        )
        last_interaction = conv["last_message_at"] if conv else None
    if not last_interaction:
        return 0

    try:
        li_dt = datetime.fromisoformat(last_interaction.replace("Z", "+00:00").replace("+00:00", ""))
    except Exception:
        return 0

    # last_interaction_at vem do banco, e o banco fala UTC (agora_utc). A
    # comparacao e em UTC pelo mesmo motivo.
    #
    # Ja foi local aqui, e com razao: naquele momento quem gravava o campo era
    # time.strftime(), que devolve a hora da maquina. So que o MESMO campo e
    # lido pelo painel como UTC (static/app.js soma "Z"), entao ele era local
    # para o follow-up e UTC para a tela - uma das duas leituras estava sempre
    # errada, e qual delas dependia de onde o app estava rodando. Agora o campo
    # e UTC dos dois lados, e quem converte e so a tela.
    agora = datetime.utcnow()

    automations = db.fetch_all("SELECT * FROM crm_automations WHERE is_active=1")
    created = 0
    for auto in automations:
        total_seconds = auto["days"] * 86400 + auto["hours"] * 3600
        if total_seconds <= 0:
            scheduled_for = agora + timedelta(minutes=1)
        else:
            scheduled_for = li_dt + timedelta(seconds=total_seconds)
            if scheduled_for < agora:
                scheduled_for = agora + timedelta(minutes=1)
        fu = create_follow_up(auto["id"], contact_id, scheduled_for.isoformat())
        if fu:
            created += 1
    return created
