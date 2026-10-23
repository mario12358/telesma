CREATE TABLE IF NOT EXISTS settings (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO settings (name, value) VALUES ('day', '2026-01-01');

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL CHECK (length(title) > 0),
    type TEXT NOT NULL CHECK (type IN ('book', 'film')),
    copies INTEGER NOT NULL CHECK (copies >= 1)
);

CREATE TABLE IF NOT EXISTS readers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(name) > 0),
    email TEXT NOT NULL CHECK (instr(email, '@') > 0),
    email_normalized TEXT NOT NULL UNIQUE,
    fine_balance_cents INTEGER NOT NULL DEFAULT 0 CHECK (fine_balance_cents >= 0)
);

CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reader_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    loan_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'on_loan' CHECK (state IN ('on_loan', 'returned')),
    return_date TEXT,
    fine_cents INTEGER NOT NULL DEFAULT 0 CHECK (fine_cents >= 0),
    FOREIGN KEY (reader_id) REFERENCES readers (id),
    FOREIGN KEY (item_id) REFERENCES items (id),
    CHECK ((state = 'returned') = (return_date IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS loans_reader_state ON loans (reader_id, state);
CREATE INDEX IF NOT EXISTS loans_item_state ON loans (item_id, state);
CREATE INDEX IF NOT EXISTS loans_state_due_date ON loans (state, due_date);
