"""Migrations versionadas do esquema SQLite.

Cada migration é aplicada uma única vez, dentro de uma transação, e registrada em
`schema_version`. Para evoluir o esquema, ACRESCENTE uma nova entrada em MIGRATIONS —
nunca edite uma migration já publicada. Um backup é feito antes de aplicar migrations
em um banco existente (ver connection.init_db).
"""
from __future__ import annotations

import sqlite3

MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "esquema inicial",
        """
        CREATE TABLE user_profile (
            id               INTEGER PRIMARY KEY CHECK (id = 1),
            name             TEXT,
            sex              TEXT NOT NULL CHECK (sex IN ('M','F')),
            birth_date       TEXT,
            age              INTEGER CHECK (age BETWEEN 10 AND 120),
            height_cm        REAL NOT NULL CHECK (height_cm BETWEEN 100 AND 250),
            initial_weight_kg REAL NOT NULL CHECK (initial_weight_kg BETWEEN 25 AND 350),
            activity_level   TEXT NOT NULL,
            goal             TEXT NOT NULL CHECK (goal IN ('emagrecimento','manutencao','ganho_massa')),
            energy_method    TEXT NOT NULL DEFAULT 'sedentario_mais_exercicio',
            sedentary_factor REAL NOT NULL DEFAULT 1.2 CHECK (sedentary_factor BETWEEN 1.0 AND 1.6),
            target_weight_kg REAL,
            weekly_rate_kg   REAL,
            created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        -- Metas versionadas por data de início: o histórico usa a meta vigente em cada dia
        CREATE TABLE goals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            start_date   TEXT NOT NULL UNIQUE,
            kcal         REAL NOT NULL CHECK (kcal BETWEEN 800 AND 8000),
            protein_g    REAL NOT NULL CHECK (protein_g >= 0),
            carbs_g      REAL NOT NULL CHECK (carbs_g >= 0),
            fat_g        REAL NOT NULL CHECK (fat_g >= 0),
            fiber_g      REAL CHECK (fiber_g IS NULL OR fiber_g >= 0),
            created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE foods (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            norm_name     TEXT NOT NULL,
            category      TEXT,
            kcal          REAL NOT NULL CHECK (kcal >= 0 AND kcal <= 950),
            protein_g     REAL CHECK (protein_g IS NULL OR protein_g BETWEEN 0 AND 100),
            carbs_g       REAL CHECK (carbs_g IS NULL OR carbs_g BETWEEN 0 AND 100),
            fat_g         REAL CHECK (fat_g IS NULL OR fat_g BETWEEN 0 AND 100),
            fiber_g       REAL CHECK (fiber_g IS NULL OR fiber_g BETWEEN 0 AND 100),
            density_g_ml  REAL CHECK (density_g_ml IS NULL OR density_g_ml BETWEEN 0.2 AND 3),
            source        TEXT NOT NULL,
            source_ref    TEXT,
            is_custom     INTEGER NOT NULL DEFAULT 0,
            active        INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE (source, source_ref)
        );
        CREATE INDEX idx_foods_norm ON foods(norm_name);

        -- Apelidos (ex.: "arroz" -> "Arroz, tipo 1, cozido"); priority maior = preferido
        CREATE TABLE food_aliases (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            alias     TEXT NOT NULL,
            food_id   INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
            priority  INTEGER NOT NULL DEFAULT 0,
            UNIQUE (alias, food_id)
        );
        CREATE INDEX idx_alias ON food_aliases(alias);

        -- Medidas caseiras: quantos gramas tem 1 unidade/fatia/colher... de um alimento
        CREATE TABLE food_portions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            food_id     INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
            unit        TEXT NOT NULL,
            size        TEXT NOT NULL DEFAULT 'medio',
            grams       REAL NOT NULL CHECK (grams > 0 AND grams <= 5000),
            source      TEXT NOT NULL,
            UNIQUE (food_id, unit, size)
        );

        CREATE TABLE meals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            meal_type   TEXT NOT NULL,
            time        TEXT,
            notes       TEXT,
            source_text TEXT,
            fingerprint TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX idx_meals_date ON meals(date);
        CREATE INDEX idx_meals_fp ON meals(date, fingerprint);

        -- Itens guardam um "retrato" dos nutrientes no momento do registro
        CREATE TABLE meal_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            meal_id     INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
            food_id     INTEGER NOT NULL REFERENCES foods(id) ON DELETE RESTRICT,
            food_name   TEXT NOT NULL,
            quantity    REAL NOT NULL CHECK (quantity > 0),
            unit        TEXT NOT NULL,
            grams       REAL NOT NULL CHECK (grams > 0 AND grams <= 10000),
            kcal        REAL NOT NULL CHECK (kcal >= 0),
            protein_g   REAL NOT NULL DEFAULT 0,
            carbs_g     REAL NOT NULL DEFAULT 0,
            fat_g       REAL NOT NULL DEFAULT 0,
            fiber_g     REAL,
            grams_basis TEXT
        );
        CREATE INDEX idx_items_meal ON meal_items(meal_id);

        CREATE TABLE activities (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            date           TEXT NOT NULL,
            activity_type  TEXT NOT NULL,
            description    TEXT,
            duration_min   REAL NOT NULL CHECK (duration_min > 0 AND duration_min <= 1440),
            distance_km    REAL CHECK (distance_km IS NULL OR (distance_km > 0 AND distance_km <= 500)),
            intensity      TEXT,
            met            REAL NOT NULL CHECK (met > 0 AND met < 30),
            met_source     TEXT,
            weight_kg_used REAL NOT NULL,
            kcal_gross     REAL NOT NULL CHECK (kcal_gross >= 0),
            kcal_net       REAL NOT NULL CHECK (kcal_net >= 0),
            notes          TEXT,
            source_text    TEXT,
            fingerprint    TEXT NOT NULL,
            created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX idx_act_date ON activities(date);
        CREATE INDEX idx_act_fp ON activities(date, fingerprint);

        CREATE TABLE weights (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL UNIQUE,
            weight_kg   REAL NOT NULL CHECK (weight_kg BETWEEN 25 AND 350),
            notes       TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            entity      TEXT NOT NULL,
            entity_id   INTEGER,
            action      TEXT NOT NULL CHECK (action IN ('create','update','delete')),
            before_json TEXT,
            after_json  TEXT,
            origin      TEXT
        );
        CREATE INDEX idx_audit_entity ON audit_log(entity, entity_id);

        CREATE TABLE settings (
            key    TEXT PRIMARY KEY,
            value  TEXT NOT NULL
        );

        CREATE TABLE chat_messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            role       TEXT NOT NULL CHECK (role IN ('user','assistant')),
            content    TEXT NOT NULL
        );
        """,
    ),
]


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY, description TEXT NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))"
    )
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def pending(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    v = current_version(conn)
    return [m for m in MIGRATIONS if m[0] > v]


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Aplica migrations pendentes; cada uma é atômica."""
    applied = []
    for version, description, sql in pending(conn):
        try:
            conn.execute("BEGIN")
            for statement in _split_sql(sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (version, description),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied


def _split_sql(sql: str) -> list[str]:
    # remove comentários primeiro; o esquema não usa ';' dentro de literais
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]
