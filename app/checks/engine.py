"""
DETools — Phase 1 Check Engine
Builds and executes SQL for each check type, evaluates thresholds,
and returns results in-memory (stateless — no persistence).
"""

from .catalog import CHECK_CATALOG


# ── SQL builders ────────────────────────────────────────────────────────────


def _quote_val(v):
    """Single-quote a value for SQL IN lists, escaping embedded quotes."""
    return "'" + str(v).replace("'", "''") + "'"


def _build_sql(check_type, db_type, schema, table, column, params):
    """
    Return a SQL string that produces exactly one row with one numeric column.
    db_type: 'postgres' | 'snowflake'
    """
    p = params or {}
    s = f'"{schema}"'
    t = f'"{table}"'
    c = f'"{column}"' if column else None

    is_pg = db_type == 'postgres'

    def null_filter(col):
        """COUNT of nulls — syntax differs between PG and Snowflake."""
        if is_pg:
            return f'COUNT(*) FILTER (WHERE {col} IS NULL)'
        return f'SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END)'

    def not_in_filter(col, quoted_list):
        if is_pg:
            return f'COUNT(*) FILTER (WHERE {col}::text NOT IN ({quoted_list}))'
        return f'SUM(CASE WHEN {col}::TEXT NOT IN ({quoted_list}) THEN 1 ELSE 0 END)'

    def regex_filter(col, pattern):
        if is_pg:
            safe_pat = pattern.replace("'", "''")
            return f"COUNT(*) FILTER (WHERE {col}::text !~ '{safe_pat}')"
        # Snowflake uses REGEXP_LIKE (returns bool, opposite logic)
        safe_pat = pattern.replace("'", "''")
        return f"SUM(CASE WHEN NOT REGEXP_LIKE({col}::TEXT, '{safe_pat}') THEN 1 ELSE 0 END)"

    # ── Table-level ──────────────────────────────────────────────────────────
    if check_type == 'row_count':
        return f'SELECT COUNT(*) FROM {s}.{t}'

    if check_type == 'row_count_min':
        return f'SELECT COUNT(*) FROM {s}.{t}'

    if check_type == 'freshness_hours':
        fc = f'"{p.get("freshness_column", column or "created_at")}"'
        if is_pg:
            return (
                f'SELECT EXTRACT(EPOCH FROM (NOW() - MAX({fc}::timestamp))) / 3600.0 '
                f'FROM {s}.{t}'
            )
        return (
            f'SELECT DATEDIFF(\'hour\', MAX({fc}::TIMESTAMP), CURRENT_TIMESTAMP()) '
            f'FROM {s}.{t}'
        )

    # ── Column-level ─────────────────────────────────────────────────────────
    if check_type == 'nulls_percent':
        nf = null_filter(c)
        return (
            f'SELECT ROUND({nf} * 100.0 / NULLIF(COUNT(*), 0), 4) '
            f'FROM {s}.{t}'
        )

    if check_type == 'nulls_count':
        return f'SELECT {null_filter(c)} FROM {s}.{t}'

    if check_type == 'unique_percent':
        if is_pg:
            return (
                f'SELECT ROUND(COUNT(DISTINCT {c}) * 100.0 / NULLIF(COUNT({c}), 0), 4) '
                f'FROM {s}.{t}'
            )
        return (
            f'SELECT ROUND(COUNT(DISTINCT {c}) * 100.0 / NULLIF(COUNT({c}), 0), 4) '
            f'FROM {s}.{t}'
        )

    if check_type == 'accepted_values':
        raw = p.get('accepted_values', [])
        if isinstance(raw, str):
            raw = [v.strip() for v in raw.split(',')]
        quoted_list = ', '.join(_quote_val(v) for v in raw) if raw else "''"
        return f'SELECT {not_in_filter(c, quoted_list)} FROM {s}.{t}'

    if check_type == 'regex_pattern':
        pattern = p.get('pattern', '.*')
        return f'SELECT {regex_filter(c, pattern)} FROM {s}.{t}'

    if check_type == 'min_value':
        return f'SELECT MIN({c}::numeric) FROM {s}.{t}'

    if check_type == 'max_value':
        return f'SELECT MAX({c}::numeric) FROM {s}.{t}'

    if check_type == 'min_length':
        return f'SELECT MIN(LENGTH({c}::text)) FROM {s}.{t}'

    if check_type == 'max_length':
        return f'SELECT MAX(LENGTH({c}::text)) FROM {s}.{t}'

    if check_type == 'custom_sql':
        return p.get('custom_sql', 'SELECT NULL')

    return None


# ── Threshold evaluation ─────────────────────────────────────────────────────


def _evaluate(actual_value, warning_op, warning, error_op, error, fatal_op, fatal):
    """
    Evaluate actual_value against up to three threshold levels using explicit
    relational operators.  Operators: '>' '>=' '<' '<=' '=' '!='

    Severity priority (most severe first): fatal → error → warning
    Warning counts as passed=True for KPI purposes.
    """
    if actual_value is None:
        return 'error', False

    def _hit(op, threshold):
        if threshold is None:
            return False
        op = op or '>'
        return {
            '>':  actual_value >  threshold,
            '>=': actual_value >= threshold,
            '<':  actual_value <  threshold,
            '<=': actual_value <= threshold,
            '=':  actual_value == threshold,
            '!=': actual_value != threshold,
        }.get(op, False)

    if _hit(fatal_op, fatal):
        return 'fatal', False
    if _hit(error_op, error):
        return 'error', False
    if _hit(warning_op, warning):
        return 'warning', True
    return 'passed', True


# ── Runner ───────────────────────────────────────────────────────────────────


def _run_sql(conn, db_type, sql):
    """Execute sql and return the first cell as float (or None)."""
    if db_type == 'postgres':
        rows = conn.run(sql)
        if rows and rows[0][0] is not None:
            return float(rows[0][0])
        return None
    else:  # Snowflake
        cursor = conn.cursor()
        cursor.execute(sql)
        row = cursor.fetchone()
        if row and row[0] is not None:
            return float(row[0])
        return None


def run_checks(db_connector, config_dict, database, schema, table_name, checks):
    """
    Run a list of ad-hoc checks against a table and return results in-memory.
    Nothing is written to disk.

    Parameters
    ----------
    db_connector : DatabaseConnector
        The project's DatabaseConnector instance.
    config_dict : dict
        Connection config dict (from validator.get_database_configs()).
    database : str
        Database to connect to.
    schema : str
        Schema containing the table.
    table_name : str
        Table to run checks against.
    checks : list[dict]
        Each item describes one check::
            {
              "check_type":        str,          # key from CHECK_CATALOG
              "column_name":       str | None,   # None for table-level checks
              "params":            dict,         # extra params (pattern, accepted_values, …)
              "warning_op":        str,          # relational operator: > >= < <= = !=
              "warning_threshold": float | None,
              "error_op":          str,
              "error_threshold":   float | None,
              "fatal_op":          str,
              "fatal_threshold":   float | None,
            }

    Returns
    -------
    list[dict]
        One result dict per check, including actual_value and severity.
    """
    conn_key = config_dict['name']
    db_type  = config_dict.get('type', 'postgres').lower()
    results  = []

    if not checks:
        return results

    with db_connector._get_connection_for_config(config_dict, database=database) as conn:
        for chk in checks:
            check_type    = chk.get('check_type', '')
            catalog_entry = CHECK_CATALOG.get(check_type)
            if not catalog_entry:
                continue

            column_name = chk.get('column_name')  # None = table-level
            params      = chk.get('params') or {}

            try:
                sql = _build_sql(check_type, db_type, schema, table_name, column_name, params)
                if not sql:
                    continue

                actual_value = _run_sql(conn, db_type, sql)

                direction = catalog_entry['direction']
                # Default operator: '>' for max-direction checks, '<' for min-direction
                default_op = '<' if direction == 'min' else '>'
                severity, passed = _evaluate(
                    actual_value,
                    chk.get('warning_op') or default_op, chk.get('warning_threshold'),
                    chk.get('error_op')   or default_op, chk.get('error_threshold'),
                    chk.get('fatal_op')   or default_op, chk.get('fatal_threshold'),
                )

                results.append({
                    'conn_key':          conn_key,
                    'database':          database,
                    'schema':            schema,
                    'table_name':        table_name,
                    'column_name':       column_name,
                    'check_type':        check_type,
                    'check_label':       catalog_entry['label'],
                    'actual_value':      actual_value,
                    'warning_op':        chk.get('warning_op') or default_op,
                    'warning_threshold': chk.get('warning_threshold'),
                    'error_op':          chk.get('error_op') or default_op,
                    'error_threshold':   chk.get('error_threshold'),
                    'fatal_op':          chk.get('fatal_op') or default_op,
                    'fatal_threshold':   chk.get('fatal_threshold'),
                    'direction':         direction,
                    'unit':              catalog_entry['unit'],
                    'severity':          severity,
                    'passed':            passed,
                    'error_message':     None,
                })

            except Exception as exc:
                results.append({
                    'conn_key':          conn_key,
                    'database':          database,
                    'schema':            schema,
                    'table_name':        table_name,
                    'column_name':       column_name,
                    'check_type':        check_type,
                    'check_label':       catalog_entry.get('label', check_type),
                    'actual_value':      None,
                    'warning_threshold': chk.get('warning_threshold'),
                    'error_threshold':   chk.get('error_threshold'),
                    'fatal_threshold':   chk.get('fatal_threshold'),
                    'direction':         catalog_entry.get('direction'),
                    'unit':              catalog_entry.get('unit', ''),
                    'severity':          'error',
                    'passed':            False,
                    'error_message':     str(exc),
                })

    return results
