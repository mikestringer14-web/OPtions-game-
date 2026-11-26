-- Central memory schema (SQLite). Portable to PostgreSQL with minor type changes.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    phone        TEXT UNIQUE,              -- E.164
    email        TEXT UNIQUE,
    relationship TEXT DEFAULT 'unknown',   -- family | friend | work | legal | medical | landlord | business | unknown
    tier         TEXT DEFAULT 'normal',    -- vip | normal | blocked
    notes        TEXT DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- Every call, text, email, dashboard chat. Raw content is UNTRUSTED data.
CREATE TABLE IF NOT EXISTS interactions (
    id            INTEGER PRIMARY KEY,
    channel       TEXT NOT NULL,           -- call | sms | email | dashboard | voice_room
    direction     TEXT NOT NULL,           -- inbound | outbound
    external_id   TEXT,                    -- provider id (conversation_id, MessageSid, gmail id)
    contact_id    INTEGER REFERENCES contacts(id),
    from_addr     TEXT,
    to_addr       TEXT,
    subject       TEXT DEFAULT '',
    body          TEXT DEFAULT '',         -- transcript / message text
    summary       TEXT DEFAULT '',
    priority      TEXT DEFAULT 'normal',   -- critical | high | normal | low
    priority_why  TEXT DEFAULT '',
    injection_flag INTEGER DEFAULT 0,
    occurred_at   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE(channel, external_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS interactions_fts USING fts5(
    subject, body, summary, content='interactions', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS interactions_ai AFTER INSERT ON interactions BEGIN
  INSERT INTO interactions_fts(rowid, subject, body, summary) VALUES (new.id, new.subject, new.body, new.summary);
END;
CREATE TRIGGER IF NOT EXISTS interactions_ad AFTER DELETE ON interactions BEGIN
  INSERT INTO interactions_fts(interactions_fts, rowid, subject, body, summary) VALUES('delete', old.id, old.subject, old.body, old.summary);
END;
CREATE TRIGGER IF NOT EXISTS interactions_au AFTER UPDATE ON interactions BEGIN
  INSERT INTO interactions_fts(interactions_fts, rowid, subject, body, summary) VALUES('delete', old.id, old.subject, old.body, old.summary);
  INSERT INTO interactions_fts(rowid, subject, body, summary) VALUES (new.id, new.subject, new.body, new.summary);
END;

-- Facts the assistant believes. subject+attribute identifies a fact slot so contradictions can be detected.
CREATE TABLE IF NOT EXISTS memories (
    id             INTEGER PRIMARY KEY,
    subject        TEXT NOT NULL,          -- e.g. 'contact:12', 'owner', 'project:hrto'
    attribute      TEXT NOT NULL,          -- e.g. 'callback_number', 'preference.tone'
    value          TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',  -- active | disputed | superseded | deleted
    verified       INTEGER NOT NULL DEFAULT 0,      -- 1 = confirmed by owner, 0 = assumption/extracted
    confidence     REAL NOT NULL DEFAULT 0.5,
    source_type    TEXT NOT NULL,          -- owner | call | sms | email | system
    source_id      INTEGER,                -- interactions.id when applicable
    superseded_by  INTEGER REFERENCES memories(id),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mem_slot ON memories(subject, attribute, status);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(subject, attribute, value, content='memories', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, subject, attribute, value) VALUES (new.id, new.subject, new.attribute, new.value);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, subject, attribute, value) VALUES('delete', old.id, old.subject, old.attribute, old.value);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, subject, attribute, value) VALUES('delete', old.id, old.subject, old.attribute, old.value);
  INSERT INTO memories_fts(rowid, subject, attribute, value) VALUES (new.id, new.subject, new.attribute, new.value);
END;

-- Things someone promised (owner to others, or others to owner), tasks and deadlines.
CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL DEFAULT 'task',   -- task | commitment | deadline | follow_up | appointment
    title         TEXT NOT NULL,
    details       TEXT DEFAULT '',
    owed_by       TEXT DEFAULT 'owner',           -- owner | contact
    contact_id    INTEGER REFERENCES contacts(id),
    due_at        TEXT,
    status        TEXT NOT NULL DEFAULT 'open',   -- open | done | cancelled
    source_id     INTEGER REFERENCES interactions(id),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Notifications produced. dedupe_key stops repeat alerts.
CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY,
    priority      TEXT NOT NULL,
    title         TEXT NOT NULL,
    body          TEXT NOT NULL,
    interaction_id INTEGER REFERENCES interactions(id),
    dedupe_key    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'new',    -- new | sent | queued_for_briefing | archived | acknowledged
    channels      TEXT DEFAULT '',                -- comma list actually attempted
    delivery_log  TEXT DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alert_dedupe ON alerts(dedupe_key, created_at);

-- Outbound actions waiting for the owner (Approval mode) or already executed.
CREATE TABLE IF NOT EXISTS actions (
    id            INTEGER PRIMARY KEY,
    action_type   TEXT NOT NULL,     -- send_sms | send_email | create_event | reply_call | ...
    payload       TEXT NOT NULL,     -- JSON
    sensitivity   TEXT NOT NULL,     -- routine | sensitive | forbidden
    status        TEXT NOT NULL,     -- pending | approved | rejected | executed | failed | blocked
    reason        TEXT DEFAULT '',
    result        TEXT DEFAULT '',
    created_at    TEXT NOT NULL,
    decided_at    TEXT
);

-- Append-only audit trail.
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY,
    ts         TEXT NOT NULL,
    actor      TEXT NOT NULL,       -- owner | system | webhook:<provider> | external:<addr>
    event      TEXT NOT NULL,
    detail     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS spend (
    id       INTEGER PRIMARY KEY,
    ts       TEXT NOT NULL,
    service  TEXT NOT NULL,
    usd      REAL NOT NULL,
    note     TEXT DEFAULT ''
);
