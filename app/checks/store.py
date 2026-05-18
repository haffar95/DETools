"""
DETools — Check Store (not yet implemented)

When result persistence is needed, this module will be implemented
against a dedicated DETools schema in Postgres (or another target
chosen at that time).  For now the checks engine is stateless —
results are returned in the HTTP response only and never written to disk.
"""

# Placeholder — no implementation here.
# Future: create a detools schema in Postgres with check_configs and
# check_results tables and implement storage/retrieval here.

import sqlite3
import json
import os
from datetime import datetime, timezone
from contextlib import contextmanager

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'data', 'detools.db'
)


@contextmanager
def _conn():
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS check_configs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            conn_key          TEXT    NOT NULL,
            database          TEXT    NOT NULL,
            schema            TEXT    NOT NULL,
            table_name        TEXT    NOT NULL,
            column_name       TEXT,                  -- NULL for table-level checks
            check_type        TEXT    NOT NULL,
            params            TEXT    DEFAULT '{}',  -- JSON: extra params (pattern, accepted_values, etc.)
            warning_threshold REAL,
            error_threshold   REAL,
            fatal_threshold   REAL,
            enabled           INTEGER DEFAULT 1,
            created_at        TEXT,
            updated_at        TEXT,
            UNIQUE(conn_key, database, schema, table_name, column_name, check_type)
        );

        CREATE TABLE IF NOT EXISTS check_results (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            config_id         INTEGER,
            conn_key          TEXT,
            database          TEXT,
            schema            TEXT,
            table_name        TEXT,
            column_name       TEXT,
            check_type        TEXT,
            actual_value      REAL,
            warning_threshold REAL,
            error_threshold   REAL,
            fatal_threshold   REAL,
            severity          TEXT,   -- 'passed' | 'warning' | 'error' | 'fatal'
            passed            INTEGER,
            error_message     TEXT,
            ran_at            TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_results_table
            ON check_results(conn_key, database, schema, table_name, ran_at DESC);
        """)


# ── Config CRUD ────────────────────────────────────────────────────────────


def get_configs(conn_key, database, schema, table_name):
    """Return all check configs for a specific table."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM check_configs "
            "WHERE conn_key=? AND database=? AND schema=? AND table_name=? "
            "ORDER BY column_name NULLS FIRST, check_type",
            (conn_key, database, schema, table_name)
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_config(conn_key, database, schema, table_name, column_name,
                  check_type, params, warning, error, fatal, enabled=1):
    """Insert or update a check config. Returns the row id."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        existing = con.execute(
            "SELECT id FROM check_configs "
            "WHERE conn_key=? AND database=? AND schema=? AND table_name=? "
            "AND column_name IS ? AND check_type=?",
            (conn_key, database, schema, table_name, column_name, check_type)
        ).fetchone()

        if existing:
            con.execute(
                "UPDATE check_configs "
                "SET params=?, warning_threshold=?, error_threshold=?, "
                "    fatal_threshold=?, enabled=?, updated_at=? "
                "WHERE id=?",
                (json.dumps(params or {}), warning, error, fatal, enabled, now, existing['id'])
            )
            return existing['id']
        else:
            cur = con.execute(
                "INSERT INTO check_configs "
                "(conn_key, database, schema, table_name, column_name, check_type, "
                " params, warning_threshold, error_threshold, fatal_threshold, "
                " enabled, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (conn_key, database, schema, table_name, column_name, check_type,
                 json.dumps(params or {}), warning, error, fatal, enabled, now, now)
            )
            return cur.lastrowid


def delete_config(config_id):
    with _conn() as con:
        con.execute("DELETE FROM check_configs WHERE id=?", (config_id,))


def toggle_config(config_id, enabled):
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "UPDATE check_configs SET enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, now, config_id)
        )


# ── Results ────────────────────────────────────────────────────────────────


def save_results(results):
    """Persist a list of result dicts (from engine.run_checks_for_table)."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        for r in results:
            con.execute(
                "INSERT INTO check_results "
                "(config_id, conn_key, database, schema, table_name, column_name, "
                " check_type, actual_value, warning_threshold, error_threshold, "
                " fatal_threshold, severity, passed, error_message, ran_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r.get('config_id'), r.get('conn_key'), r.get('database'),
                    r.get('schema'), r.get('table_name'), r.get('column_name'),
                    r.get('check_type'), r.get('actual_value'),
                    r.get('warning_threshold'), r.get('error_threshold'),
                    r.get('fatal_threshold'), r.get('severity'),
                    1 if r.get('passed') else 0,
                    r.get('error_message'), now,
                )
            )


def get_results(conn_key, database, schema, table_name, limit=100):
    """Return the latest check results for a table, most recent first."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM check_results "
            "WHERE conn_key=? AND database=? AND schema=? AND table_name=? "
            "ORDER BY ran_at DESC LIMIT ?",
            (conn_key, database, schema, table_name, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_latest_run_results(conn_key, database, schema, table_name):
    """Return only the results from the single most-recent run for a table."""
    with _conn() as con:
        latest = con.execute(
            "SELECT ran_at FROM check_results "
            "WHERE conn_key=? AND database=? AND schema=? AND table_name=? "
            "ORDER BY ran_at DESC LIMIT 1",
            (conn_key, database, schema, table_name)
        ).fetchone()
        if not latest:
            return []
        rows = con.execute(
            "SELECT * FROM check_results "
            "WHERE conn_key=? AND database=? AND schema=? AND table_name=? AND ran_at=?",
            (conn_key, database, schema, table_name, latest['ran_at'])
        ).fetchall()
    return [dict(r) for r in rows]


def get_table_dq_status(conn_key, database, schema, table_name):
    """
    Returns a summary of the latest run for a table:
    { total, passed, warning, error, fatal, kpi_score }
    KPI = passed / (passed + error + fatal)  [warnings don't reduce KPI]
    """
    results = get_latest_run_results(conn_key, database, schema, table_name)
    if not results:
        return None

    counts = {'passed': 0, 'warning': 0, 'error': 0, 'fatal': 0}
    for r in results:
        counts[r['severity']] = counts.get(r['severity'], 0) + 1

    total = sum(counts.values())
    denominator = counts['passed'] + counts['error'] + counts['fatal']
    kpi = round(counts['passed'] / denominator * 100, 1) if denominator > 0 else None

    return {
        'total': total,
        'passed': counts['passed'],
        'warning': counts['warning'],
        'error': counts['error'],
        'fatal': counts['fatal'],
        'kpi_score': kpi,
        'ran_at': results[0]['ran_at'],
    }
