from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from app.database.db_connector import DatabaseConnector
from app.validation.validators import DataValidator
from app.models.user import User
from app.auth import login_required, admin_required, connection_access_required
from app.checks import engine as check_engine
from app.checks.catalog import CHECK_CATALOG
from flask_cors import CORS
from functools import lru_cache
import os
import re as _re
import secrets

# ── Optional: sqlglot for SQL-body parsing (routine lineage) ─────────────────
try:
    import sqlglot as _sqlglot
    from sqlglot import exp as _sg_exp
    _has_sqlglot = True
except ImportError:          # pragma: no cover
    _has_sqlglot = False

# Regex: captures the inner body between PostgreSQL dollar-quote delimiters
# e.g.  $$ ... $$  or  $function$ ... $function$
_DOLLAR_BODY_RE = _re.compile(
    r'\$(?P<tag>[^$]*)\$(?P<body>.*?)\$(?P=tag)\$',
    _re.DOTALL,
)
# Regex: strip the outermost plpgsql BEGIN … END wrapper so we can parse
# just the DML statements inside.
_PLPGSQL_BLOCK_RE = _re.compile(
    r'(?:DECLARE\b.*?)?^\s*BEGIN\b(?P<inner>.*?)^\s*END\s*;?\s*$',
    _re.DOTALL | _re.MULTILINE | _re.IGNORECASE,
)


def _extract_routine_body(funcdef: str) -> str:
    """
    Given the output of pg_get_functiondef(), return the SQL body to parse.
    Strips the CREATE FUNCTION header and dollar-quote delimiters, then
    removes the PL/pgSQL BEGIN … END wrapper so sqlglot sees plain SQL.
    """
    m = _DOLLAR_BODY_RE.search(funcdef)
    inner = m.group('body').strip() if m else funcdef

    # If it starts with DECLARE or BEGIN it is a plpgsql block —
    # extract the statements between BEGIN and END.
    m2 = _PLPGSQL_BLOCK_RE.search(inner)
    if m2:
        inner = m2.group('inner').strip()

    return inner


@lru_cache(maxsize=512)
def _parse_routine_deps(body: str, dialect: str = 'postgres'):
    """
    Parse a function/procedure SQL body and return (reads, writes) — two
    frozensets of 'schema.name' strings representing tables the routine reads
    from and writes to.  Uses sqlglot for AST-level accuracy.
    Returns (frozenset(), frozenset()) when sqlglot is unavailable or parsing fails.
    """
    if not _has_sqlglot or not body:
        return frozenset(), frozenset()

    # Extract just the DML body from the full CREATE FUNCTION definition
    sql = _extract_routine_body(body)

    reads, writes = set(), set()
    try:
        stmts = _sqlglot.parse(
            sql, dialect=dialect,
            error_level=_sqlglot.errors.ErrorLevel.WARN,
        )
        for stmt in (stmts or []):
            if not stmt:
                continue

            def _tbl_name(expr):
                """Unwrap Schema(Table, cols) → Table, then return 'schema.name'."""
                if isinstance(expr, _sg_exp.Schema):
                    expr = expr.this          # Schema wraps Table when column list present
                if isinstance(expr, _sg_exp.Table) and expr.name:
                    return f"{expr.db}.{expr.name}" if expr.db else expr.name
                return None

            # ── Write targets ─────────────────────────────────────────
            for node in stmt.find_all(_sg_exp.Insert):
                n = _tbl_name(node.this)
                if n: writes.add(n)
            for node in stmt.find_all(_sg_exp.Update):
                n = _tbl_name(node.this)
                if n: writes.add(n)
            for node in stmt.find_all(_sg_exp.Delete):
                n = _tbl_name(node.this)
                if n: writes.add(n)
            for node in stmt.find_all(_sg_exp.Create):
                if node.kind in ('TABLE', 'VIEW', 'MATERIALIZED VIEW'):
                    n = _tbl_name(node.this)
                    if n: writes.add(n)
            # ── All other table references = read sources ─────────────
            for t in stmt.find_all(_sg_exp.Table):
                if t.name:
                    qname = f"{t.db}.{t.name}" if t.db else t.name
                    if qname not in writes:
                        reads.add(qname)
    except Exception:
        pass    # never crash lineage on a parse error

    return frozenset(reads), frozenset(writes)

# Create Flask app with explicit template and static folders
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'app', 'templates'))
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'app', 'static'))
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
CORS(app)
app.config.from_object('config.config.Config')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB limit
app.config['SECRET_KEY'] = secrets.token_hex(16)

db = DatabaseConnector()
validator = DataValidator()


def _friendly_conn_error(raw: str) -> str:
    """Convert a raw connection exception string into a short, user-friendly message."""
    r = raw.lower()
    if 'password authentication failed' in r or '28p01' in r or 'authentication failed' in r:
        return 'Incorrect username or password.'
    if 'database' in r and ('does not exist' in r or 'not found' in r):
        return 'Database not found. Check the database name.'
    if 'role' in r and 'does not exist' in r:
        return 'User/role not found. Check the username.'
    if 'connection refused' in r or 'cannot connect' in r or 'could not connect' in r:
        return 'Connection refused. Check the host and port.'
    if 'timeout' in r or 'timed out' in r:
        return 'Connection timed out. Check the host and port.'
    if 'name or service not known' in r or 'nodename nor servname' in r or 'gaierror' in r:
        return 'Hostname not found. Check the host address.'
    if 'ssl' in r:
        return 'SSL error. The server may not support SSL or the certificate is invalid.'
    if 'account' in r and 'snowflake' in r:
        return 'Invalid Snowflake account identifier.'
    # Fallback: strip internal dict repr, show first sentence only
    clean = raw.split('{')[0].strip().rstrip(':').strip()
    return clean if clean else 'Connection failed. Check your credentials and network settings.'



@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.get_user(username)
        if user and user.check_password(password):
            session['user_id'] = user.username
            session['is_admin'] = user.is_admin
            return redirect(url_for('overview_page'))
        
    return render_template('login.html')

@app.route('/logout')
def logout():
    # Clear Flask session
    session.clear()
    # Clear database validator session data
    validator.clear_session()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('overview_page'))
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/columns/<table_name>')
@login_required
def get_columns(table_name):
    columns = db.get_table_columns(table_name)
    return jsonify({
        'columns': columns
    })

@app.route('/api/validate')
@login_required
def validate():
    table_name  = request.args.get('table')
    schema      = request.args.get('schema', 'public')
    key_column  = request.args.get('key_column')
    foreign_key = request.args.get('foreign_key')
    start_date  = request.args.get('start_date')
    end_date    = request.args.get('end_date')
    date_column = request.args.get('date_column')
    database    = request.args.get('db') or None   # which database on the active server

    if not table_name:
        return jsonify({'error': 'Table name is required'}), 400

    # Use the session's active connection, then override the database if the picker
    # selected a different one (e.g. the server has multiple databases).
    conn_key = session.get('current_connection')
    if conn_key:
        try:
            validator.set_selected_database(conn_key, current_user=session['user_id'])
            if database and hasattr(validator.db, 'conn_params'):
                validator.db.conn_params['database'] = database
            elif database and hasattr(validator.db, 'snowflake_params'):
                validator.db.snowflake_params['database'] = database
        except Exception:
            pass

    try:
        results = validator.validate_table(table_name, schema, start_date, end_date, date_column, key_column, foreign_key)
        if 'error' in results:
            return jsonify({'error': results['error']}), 200
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': f'Validation failed: {str(e)}'}), 200

@app.route('/api/tables/<schema>')
@login_required
def get_tables(schema):
    tables = db.get_tables(schema)
    return jsonify({
        'tables': tables
    })

@app.route('/api/validate-schema', methods=['POST'])
@login_required
def validate_schema():
    data = request.get_json()
    schema = data.get('schema')
    if not schema:
        return jsonify({'error': 'Schema is required'}), 400

    # Call your validation logic here
    results = validator.validate_schema(schema)
    return jsonify(results)

@app.route('/admin')
@admin_required
def admin_panel():
    users = User('temp').load_users()
    db_configs = validator.get_database_configs()
    return render_template('admin.html', users=users, connections=db_configs)

@app.route('/admin/create-user', methods=['POST'])
@admin_required
def create_user():
    username = request.form.get('username')
    password = request.form.get('password')
    is_admin = request.form.get('is_admin') == '1'
    
    if not username or not password:
        return redirect(url_for('admin_panel'))
    
    existing_user = User.get_user(username)
    if existing_user:
        return redirect(url_for('admin_panel'))
    
    new_user = User(username, password, is_admin)
    users = User('temp').load_users()
    users.append(new_user)
    new_user.save_users(users)
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete-user/<username>', methods=['POST'])
@admin_required
def delete_user(username):
    if username == session.get('user_id'):
        return redirect(url_for('admin_panel'))
    
    users = User('temp').load_users()
    users = [u for u in users if u.username != username]
    User('temp').save_users(users)
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/update-user-connections/<username>', methods=['POST'])
@admin_required
def update_user_connections(username):
    connection = request.form.get('connection')
    action = request.form.get('action')
    
    if not connection or not action:
        return redirect(url_for('admin_panel'))
    
    user = User.get_user(username)
    if not user:
        return redirect(url_for('admin_panel'))
    
    if action == 'add':
        user.add_connection(connection)
    elif action == 'remove':
        user.remove_connection(connection)
    
    return redirect(url_for('admin_panel'))

@app.route('/api/validate-query', methods=['POST'])
@login_required
@connection_access_required
def validate_query():
    try:
        if not request.is_json:
            return jsonify({'error': 'Request must be JSON'}), 400
            
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid JSON in request'}), 400
            
        query = data.get('query')
        database = data.get('database') or None

        if not query:
            return jsonify({'error': 'Query is required'}), 400

        # Normalize query by removing extra whitespace
        normalized_query = ' '.join(query.strip().split())
        
        # Additional security check for non-SELECT operations
        dangerous_keywords = ['insert', 'update', 'delete', 'drop', 'truncate', 'alter', 'create', 'replace']
        dangerous_patterns = [f' {keyword} ' for keyword in dangerous_keywords]  # Add spaces to avoid matching substrings
        if any(pattern in f' {normalized_query.lower()} ' for pattern in dangerous_patterns):
            return jsonify({'error': 'Only SELECT queries are allowed. No data modification operations permitted.'}), 400

        # Resolve the active connection config so we target the correct server + database
        conn_key = session.get('current_connection')
        cfg = None
        if conn_key:
            configs = validator.get_database_configs(current_user=session['user_id'])
            cfg = next((c for c in configs if c['name'] == conn_key), None)

        results = validator._validate_custom_query(query=query, config=cfg, database=database)
        
        if 'error' in results:
            return jsonify(results), 200  # Return 200 even for validation errors to allow proper error display

        return jsonify(results)
        
    except Exception as e:
        error_msg = str(e)
        print(f"Error in validate_query route: {error_msg}")
        return jsonify({
            'error': f"An error occurred while validating the query: {error_msg}",
            'row_count': 0,
            'duplicates': {'count': 0, 'details': []},
            'null_values': {'details': {}},
            'date_issues': {}
        }), 200  # Return 200 to allow proper error display

@app.route('/overview')
@login_required
def overview_page():
    try:
        schemas = db.get_schemas()
        return render_template('overview.html', schemas=schemas, needs_connection=False)
    except ConnectionError:
        return render_template('overview.html', schemas=[], needs_connection=True)

@app.route('/database-config', methods=['GET'])
@login_required
def database_config():
    # Retrieve database configurations for the current user only
    databases = validator.get_database_configs(current_user=session['user_id'])
    return render_template('database_config.html', databases=databases)

@app.route('/api/test-connection', methods=['POST'])
@login_required
def test_connection():
    try:
        data     = request.get_json(silent=True) or {}
        db_type  = data.get('db_type', 'postgres')
        host     = data.get('db_host', '')
        port     = data.get('db_port', '5432')
        user     = data.get('db_user', '')
        password = data.get('db_password', '')
        database = data.get('db_database', '')
        account  = data.get('db_account', '')
        warehouse= data.get('db_warehouse', '')
        role     = data.get('db_role', '')
        ssh_host = data.get('ssh_host', '') or None
        ssh_user = data.get('ssh_user', '') or None

        test_db = DatabaseConnector()
        test_db.update_connection(
            host=host, port=port, user=user, password=password,
            db_type=db_type, database=database,
            account=account, warehouse=warehouse, role=role,
            ssh_host=ssh_host, ssh_user=ssh_user,
        )
        return jsonify({'ok': True, 'message': 'Connection successful'})
    except Exception as e:
        return jsonify({'ok': False, 'error': _friendly_conn_error(str(e))})

@app.route('/add_database_config', methods=['POST'])
@login_required
def add_database_config():
    try:
        db_name = request.form['db_name']
        db_type = request.form['db_type']
        db_host = request.form.get('db_host', '')
        db_port = request.form.get('db_port', '')
        db_user = request.form['db_user']
        db_password = request.form['db_password']
        
        # Get Snowflake-specific parameters
        db_account = request.form.get('db_account')
        db_warehouse = request.form.get('db_warehouse')
        db_role = request.form.get('db_role')
        db_database = request.form.get('db_database')
        
        # Add the current user as the creator of the database configuration
        validator.save_database_config(
            db_name=db_name,
            db_type=db_type,
            db_host=db_host,
            db_port=db_port,
            db_user=db_user,
            creator=session['user_id'],
            db_password=db_password,
            db_account=db_account,
            db_warehouse=db_warehouse,
            db_role=db_role,
            db_database=db_database
        )
    except Exception:
        pass
    
    return redirect(url_for('database_config'))

@app.route('/edit_database_config', methods=['POST'])
@login_required
def edit_database_config():
    try:
        key          = request.form['db_key']
        display_name = request.form['db_name']
        db_password  = request.form.get('db_password', '').strip()  # blank = keep existing
        validator.update_database_config(
            key=key,
            current_user=session['user_id'],
            display_name=display_name,
            db_host=request.form.get('db_host') or None,
            db_port=request.form.get('db_port') or None,
            db_user=request.form.get('db_user') or None,
            db_password=db_password or None,
            db_account=request.form.get('db_account') or None,
            db_warehouse=request.form.get('db_warehouse') or None,
            db_role=request.form.get('db_role') or None,
            db_database=request.form.get('db_database') or None,
            ssh_host=request.form.get('ssh_host') or None,
            ssh_user=request.form.get('ssh_user') or None,
            ssh_key_path=request.form.get('ssh_key_path') or None,
        )
    except (PermissionError, Exception):
        pass
    return redirect(url_for('database_config'))

@app.route('/delete_database', methods=['POST'])
@login_required
def delete_database():
    try:
        db_name = request.form['db_name']
        validator.delete_database_config(db_name, current_user=session['user_id'])
    except Exception:
        pass
    
    return redirect(url_for('database_config'))

@app.route('/select-database', methods=['POST'])
@login_required
@connection_access_required
def select_database():
    """Set the selected database for validation"""
    try:
        selected_db = request.form.get('selected_db')
        print(f"Selected database: {selected_db}")  # Debug log
        
        if not selected_db:
            return redirect(url_for('database_config'))
        
        # Get the database configuration
        db_configs = validator.get_database_configs()
        print(f"Available database configs: {db_configs}")  # Debug log
        
        # Verify that the selected database belongs to the current user
        selected_config = next((db for db in db_configs if db['name'] == selected_db and db.get('creator') == session['user_id']), None)
        
        if not selected_config:
            return redirect(url_for('database_config'))
        print(f"Selected config: {selected_config}")  # Debug log
        
        if not selected_config:
            return redirect(url_for('database_config'))
        
        # Check if user has access to this connection
        user = User.get_user(session['user_id'])
        if not user.can_access_connection(selected_db):
            return redirect(url_for('database_config'))
        
        # Update the database connector with the selected configuration
        if selected_config['type'] == 'postgres':
            db.update_connection(
                host=selected_config['host'],
                port=selected_config['port'],
                user=selected_config['user'],
                password=selected_config['password'],
                database=selected_config['database'],
                db_type='postgres',
                ssh_host=selected_config.get('ssh_host'),
                ssh_user=selected_config.get('ssh_user'),
                ssh_password=selected_config.get('ssh_password'),
                ssh_port=selected_config.get('ssh_port')
            )
        else:  # Snowflake
            db.update_connection(
                host='',  # Empty host for Snowflake
                port='443',  # Default Snowflake port
                user=selected_config['user'],
                password=selected_config['password'],
                db_type='snowflake',
                account=selected_config['account'],
                warehouse=selected_config['warehouse'],
                role=selected_config['role'],
                database=selected_config['database']
            )
        
        # Store the current connection in session
        session['current_connection'] = selected_db
        
        # Set the current database in the validator with user check
        if validator.set_selected_database(selected_db, current_user=session['user_id']):
            print(f"Successfully set selected database to: {selected_db}")  # Debug log
            return redirect(request.referrer or url_for('overview_page'))
        else:
            print(f"Failed to set selected database: {selected_db}")  # Debug log
            return redirect(request.referrer or url_for('overview_page'))
    except Exception as e:
        print(f"Error selecting database: {str(e)}")  # Debug log
        return redirect(request.referrer or url_for('overview_page'))

@app.route('/api/activate-conn', methods=['POST'])
@login_required
def activate_conn():
    """Activate a specific connection for the session without a page redirect. Returns JSON."""
    data = request.get_json(silent=True) or {}
    conn_key = data.get('conn_key', '').strip()
    if not conn_key:
        return jsonify({'error': 'conn_key required'}), 400
    configs = validator.get_database_configs(current_user=session['user_id'])
    cfg = next((c for c in configs if c['name'] == conn_key), None)
    if not cfg:
        return jsonify({'error': 'Connection not found or not authorised'}), 404
    user = User.get_user(session['user_id'])
    if not user.can_access_connection(conn_key):
        return jsonify({'error': 'Access denied'}), 403
    try:
        if cfg['type'] == 'postgres':
            db.update_connection(
                host=cfg['host'], port=cfg['port'],
                user=cfg['user'], password=cfg['password'],
                database=cfg['database'], db_type='postgres',
                ssh_host=cfg.get('ssh_host'), ssh_user=cfg.get('ssh_user'),
                ssh_password=cfg.get('ssh_password'), ssh_port=cfg.get('ssh_port'),
            )
        else:
            db.update_connection(
                host='', port='443',
                user=cfg['user'], password=cfg['password'], db_type='snowflake',
                account=cfg['account'], warehouse=cfg['warehouse'],
                role=cfg['role'], database=cfg['database'],
            )
        session['current_connection'] = conn_key
        validator.set_selected_database(conn_key, current_user=session['user_id'])
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/current-database')
def get_current_database():
    """Get information about the currently selected database."""
    try:
        selected_db = validator.get_selected_database()
        print(f"Current selected database: {selected_db}")  # Debug log
        
        if selected_db:
            db_configs = validator.get_database_configs()
            selected_config = next((db for db in db_configs if db['name'] == selected_db), None)
            print(f"Selected config for current database: {selected_config}")  # Debug log
            
            if selected_config:
                return jsonify({
                    'selected_db': {
                        'name': selected_config['name'],
                        'type': selected_config['type']
                    }
                })
        
        return jsonify({
            'selected_db': None
        })
    except Exception as e:
        print(f"Error getting current database: {str(e)}")  # Debug log
        return jsonify({
            'error': str(e)
        }), 500

@app.route('/api/database-configs')
@login_required
def get_database_configs():
    """Get all available database configurations for the current user"""
    try:
        # Get configurations filtered by current user
        user_databases = validator.get_database_configs(current_user=session['user_id'])
        return jsonify({
            'databases': user_databases
        })
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500

@app.route('/api/tree/connections')
@login_required
def get_tree_connections():
    """List all database connections available to the current user."""
    try:
        configs = validator.get_database_configs(current_user=session['user_id'])
        selected_db = validator.get_selected_database()
        connections = [
            {
                'key': cfg['name'],
                'label': cfg.get('display_name') or cfg['name'],
                'type': cfg['type'],
                'active': cfg['name'] == selected_db,
            }
            for cfg in configs
        ]
        return jsonify({'connections': connections})
    except Exception as e:
        return jsonify({'connections': [], 'error': str(e)}), 200

@app.route('/api/tree/databases')
@login_required
def get_tree_databases():
    """List all databases on a specific connection's server. Pass ?conn=<key>."""
    try:
        conn_key = request.args.get('conn')
        if not conn_key:
            return jsonify({'databases': [], 'error': 'conn parameter required'}), 200
        configs = validator.get_database_configs(current_user=session['user_id'])
        cfg = next((c for c in configs if c['name'] == conn_key), None)
        if not cfg:
            return jsonify({'databases': [], 'error': 'Connection not found'}), 200
        databases = db.get_databases_for_config(cfg)
        return jsonify({'databases': databases})
    except Exception as e:
        return jsonify({'databases': [], 'error': str(e)}), 200

@app.route('/api/tree/schemas')
@login_required
def get_tree_schemas():
    """Get schemas. Pass ?conn=<key>&db=<database> for a specific connection+database."""
    try:
        conn_key = request.args.get('conn')
        database = request.args.get('db') or None
        if conn_key:
            configs = validator.get_database_configs(current_user=session['user_id'])
            cfg = next((c for c in configs if c['name'] == conn_key), None)
            if not cfg:
                return jsonify({'schemas': [], 'error': 'Connection not found'}), 200
            schemas = db.get_schemas_for_config(cfg, database=database)
        else:
            if 'current_connection' not in session:
                return jsonify({'schemas': [], 'error': 'No database selected'}), 200
            schemas = db.get_schemas()
        return jsonify({'schemas': schemas})
    except Exception as e:
        return jsonify({'schemas': [], 'error': str(e)}), 200

@app.route('/api/tree/tables')
@login_required
def get_tree_tables():
    """Get tables. Pass ?conn=<key>&db=<database>&schema=<schema>."""
    try:
        schema = request.args.get('schema', '')
        conn_key = request.args.get('conn')
        database = request.args.get('db') or None
        if conn_key:
            configs = validator.get_database_configs(current_user=session['user_id'])
            cfg = next((c for c in configs if c['name'] == conn_key), None)
            if not cfg:
                return jsonify({'tables': [], 'error': 'Connection not found'}), 200
            tables = db.get_tables_for_config(cfg, schema, database=database)
        else:
            tables = db.get_tables(schema)
        return jsonify({'tables': tables})
    except Exception as e:
        return jsonify({'tables': [], 'error': str(e)}), 200

@app.route('/api/tree/routines')
@login_required
def get_tree_routines():
    """Get routines (functions/procedures). Pass ?conn=<key>&db=<database>&schema=<schema>."""
    try:
        schema = request.args.get('schema', '')
        conn_key = request.args.get('conn')
        database = request.args.get('db') or None
        if conn_key:
            configs = validator.get_database_configs(current_user=session['user_id'])
            cfg = next((c for c in configs if c['name'] == conn_key), None)
            if not cfg:
                return jsonify({'routines': [], 'error': 'Connection not found'}), 200
            routines = db.get_routines_for_config(cfg, schema, database=database)
        else:
            routines = []
        return jsonify({'routines': routines})
    except Exception as e:
        return jsonify({'routines': [], 'error': str(e)}), 200

@app.route('/api/tree/sequences')
@login_required
def get_tree_sequences():
    """Get sequences. Pass ?conn=<key>&db=<database>&schema=<schema>."""
    try:
        schema = request.args.get('schema', '')
        conn_key = request.args.get('conn')
        database = request.args.get('db') or None
        if conn_key:
            configs = validator.get_database_configs(current_user=session['user_id'])
            cfg = next((c for c in configs if c['name'] == conn_key), None)
            if not cfg:
                return jsonify({'sequences': [], 'error': 'Connection not found'}), 200
            sequences = db.get_sequences_for_config(cfg, schema, database=database)
        else:
            sequences = []
        return jsonify({'sequences': sequences})
    except Exception as e:
        return jsonify({'sequences': [], 'error': str(e)}), 200

@app.route('/api/tree/columns')
@login_required
def get_tree_columns():
    """Get columns. Pass ?conn=<key>&db=<database>&schema=<schema>&table=<table>."""
    try:
        schema = request.args.get('schema', '')
        table_name = request.args.get('table', '')
        conn_key = request.args.get('conn')
        database = request.args.get('db') or None
        if conn_key:
            configs = validator.get_database_configs(current_user=session['user_id'])
            cfg = next((c for c in configs if c['name'] == conn_key), None)
            if not cfg:
                return jsonify({'columns': [], 'error': 'Connection not found'}), 200
            columns = db.get_columns_for_config(cfg, schema, table_name, database=database)
        else:
            columns = db.get_table_columns_with_schema(table_name, schema)
        return jsonify({'columns': columns})
    except Exception as e:
        return jsonify({'columns': [], 'error': str(e)}), 200


# ── Phase 1: Checks Framework ───────────────────────────────────────────────

@app.route('/api/checks/catalog')
@login_required
def checks_catalog():
    """Return the full check catalog (check types + metadata)."""
    return jsonify({'catalog': CHECK_CATALOG})


@app.route('/api/checks/run', methods=['POST'])
@login_required
def checks_run():
    """
    Execute a list of checks against a table and return results immediately.
    Nothing is persisted — results are returned in the response only.

    Body JSON:
    {
      "conn_key":  str,
      "database":  str,
      "schema":    str,
      "table_name": str,
      "checks": [
        {
          "check_type":        str,
          "column_name":       str | null,
          "params":            {},
          "warning_threshold": float | null,
          "error_threshold":   float | null,
          "fatal_threshold":   float | null
        }
      ]
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    conn_key   = data.get('conn_key', '')
    database   = data.get('database', '')
    schema     = data.get('schema', '')
    table_name = data.get('table_name', '')
    checks     = data.get('checks', [])

    if not checks:
        return jsonify({'error': 'No checks provided'}), 400

    db_configs = validator.get_database_configs(current_user=session['user_id'])
    cfg = next((c for c in db_configs if c['name'] == conn_key), None)
    if not cfg:
        return jsonify({'error': 'Connection not found'}), 404

    try:
        results = check_engine.run_checks(db, cfg, database, schema, table_name, checks)
        # Quick summary (no persistence)
        total   = len(results)
        passed  = sum(1 for r in results if r['passed'])
        errors  = sum(1 for r in results if r['severity'] in ('error', 'fatal'))
        kpi     = round(passed / total * 100, 1) if total else None
        return jsonify({
            'results': results,
            'summary': {'total': total, 'passed': passed, 'errors': errors, 'kpi_score': kpi},
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



# ── Overview API ─────────────────────────────────────────────────────────────

@app.route('/api/overview/connections')
@login_required
def overview_connections():
    """
    Health-check every connection configured for the current user.
    Returns reachability + schema count for each.
    """
    try:
        configs = validator.get_database_configs(current_user=session['user_id'])
        results = []
        for cfg in configs:
            entry = {
                'key':   cfg['name'],
                'label': cfg.get('display_name') or cfg['name'],
                'type':  cfg.get('type', 'postgres'),
            }
            try:
                schemas = db.get_schemas_for_config(cfg)
                entry['reachable']    = True
                entry['schema_count'] = len(schemas)
            except Exception as e:
                entry['reachable']    = False
                entry['schema_count'] = 0
                entry['error']        = str(e)
            results.append(entry)
        return jsonify({'connections': results})
    except Exception as e:
        return jsonify({'connections': [], 'error': str(e)}), 500


@app.route('/api/overview/scan')
@login_required
def overview_scan():
    """
    Quick schema scan: row count + column count per table, using the
    multi-connection system (conn + db + schema query params).
    """
    conn_key = request.args.get('conn')
    database = request.args.get('db') or None
    schema   = request.args.get('schema')

    if not conn_key or not schema:
        return jsonify({'error': 'conn and schema are required'}), 400

    try:
        configs = validator.get_database_configs(current_user=session['user_id'])
        cfg = next((c for c in configs if c['name'] == conn_key), None)
        if not cfg:
            return jsonify({'error': 'Connection not found'}), 404

        db_type = cfg.get('type', 'postgres').lower()
        tables  = db.get_tables_for_config(cfg, schema, database=database)

        table_results = []
        total_rows  = 0
        scan_errors = 0

        # DQ tracking variables
        nullable_by_table = {}
        pk_col_by_table   = {}
        ts_cols_by_table  = {}
        text_cols_by_table = {}
        total_null_cells     = 0
        total_non_null_cells = 0
        uniq_num = 0;  uniq_den = 0
        freshness_scores = []
        validity_scores  = []
        schema_accuracy  = None

        with db._get_connection_for_config(cfg, database=database) as conn:
            if db_type == 'postgres':
                try:
                    # Nullable columns (Completeness)
                    for row in conn.run(
                        "SELECT table_name, column_name FROM information_schema.columns "
                        "WHERE table_schema = :s AND is_nullable = 'YES' "
                        "ORDER BY table_name, ordinal_position", s=schema
                    ):
                        nullable_by_table.setdefault(row[0], []).append(row[1])

                    # Primary keys (Uniqueness)
                    for row in conn.run(
                        "SELECT kcu.table_name, kcu.column_name "
                        "FROM information_schema.table_constraints tc "
                        "JOIN information_schema.key_column_usage kcu "
                        "  ON tc.constraint_name = kcu.constraint_name "
                        " AND tc.table_schema    = kcu.table_schema "
                        "WHERE tc.table_schema = :s AND tc.constraint_type = 'PRIMARY KEY'", s=schema
                    ):
                        pk_col_by_table.setdefault(row[0], row[1])   # keep first PK column

                    # Column types (Freshness + Validity)
                    for row in conn.run(
                        "SELECT table_name, column_name, data_type "
                        "FROM information_schema.columns WHERE table_schema = :s", s=schema
                    ):
                        tname, cname, dtype = row[0], row[1], (row[2] or '').lower()
                        if any(k in dtype for k in ('timestamp', 'date', 'time')):
                            ts_cols_by_table.setdefault(tname, []).append(cname)
                        elif any(k in dtype for k in ('text', 'varchar', 'char', 'character')):
                            text_cols_by_table.setdefault(tname, []).append(cname)

                    # Accuracy: % of NOT-NULL-constrained columns (schema quality proxy)
                    acc_r = conn.run(
                        "SELECT ROUND(100.0 * SUM(CASE WHEN is_nullable='NO' THEN 1 ELSE 0 END)"
                        " / NULLIF(COUNT(*),0), 1) "
                        "FROM information_schema.columns WHERE table_schema = :s", s=schema
                    )
                    if acc_r and acc_r[0][0] is not None:
                        schema_accuracy = float(acc_r[0][0])
                except Exception:
                    pass

            for table in tables[:200]:
                try:
                    if db_type == 'postgres':
                        row_count = conn.run(f'SELECT COUNT(*) FROM "{schema}"."{table}"')[0][0]
                        col_count = conn.run(
                            "SELECT COUNT(*) FROM information_schema.columns "
                            "WHERE table_schema = :s AND table_name = :t", s=schema, t=table
                        )[0][0]

                        # per-table DQ accumulators
                        t_completeness = None
                        t_uniqueness   = None
                        t_freshness    = None
                        t_validity     = None

                        # ── Completeness ──────────────────────────────────
                        ncols = nullable_by_table.get(table, [])[:50]
                        if ncols and row_count:
                            try:
                                expr = ' + '.join(
                                    f'SUM(CASE WHEN "{c}" IS NULL THEN 1 ELSE 0 END)'
                                    for c in ncols
                                )
                                nr = conn.run(f'SELECT {expr} FROM "{schema}"."{table}"')
                                if nr and nr[0]:
                                    null_count = sum(v or 0 for v in (nr[0] if isinstance(nr[0], (list, tuple)) else [nr[0]]))
                                    total_null_cells     += null_count
                                    total_non_null_cells += row_count * len(ncols) - null_count
                                    denom = row_count * len(ncols)
                                    t_completeness = round((denom - null_count) * 100.0 / denom, 1) if denom else None
                            except Exception:
                                pass

                        # ── Uniqueness ────────────────────────────────────
                        if row_count:
                            pk = pk_col_by_table.get(table)
                            try:
                                if pk:
                                    ur = conn.run(f'SELECT COUNT(DISTINCT "{pk}") FROM "{schema}"."{table}"')
                                    dist = int(ur[0][0])
                                    uniq_num += dist; uniq_den += row_count
                                    t_uniqueness = round(dist * 100.0 / row_count, 1)
                                elif row_count <= 500000:
                                    ur = conn.run(f'SELECT COUNT(*) FROM (SELECT DISTINCT * FROM "{schema}"."{table}") _t')
                                    dist = int(ur[0][0])
                                    uniq_num += dist; uniq_den += row_count
                                    t_uniqueness = round(dist * 100.0 / row_count, 1)
                            except Exception:
                                pass

                        # ── Freshness ─────────────────────────────────────
                        ts_list = ts_cols_by_table.get(table, [])
                        if ts_list and row_count:
                            try:
                                ts_col = ts_list[0]
                                fr = conn.run(
                                    f'SELECT EXTRACT(EPOCH FROM (NOW() - MAX("{ts_col}"))) / 3600 '
                                    f'FROM "{schema}"."{table}"'
                                )
                                if fr and fr[0] and fr[0][0] is not None:
                                    h = float(fr[0][0])
                                    if h <= 1:       fscore = 100.0
                                    elif h <= 24:    fscore = 100.0 - (h / 24) * 5
                                    elif h <= 168:   fscore = 95.0  - ((h - 24)  / 144)  * 15
                                    elif h <= 720:   fscore = 80.0  - ((h - 168) / 552)  * 30
                                    elif h <= 2160:  fscore = 50.0  - ((h - 720) / 1440) * 30
                                    else:            fscore = max(5.0, 20.0 - (h - 2160) / 1000)
                                    freshness_scores.append(fscore)
                                    t_freshness = round(fscore, 1)
                            except Exception:
                                pass

                        # ── Validity ──────────────────────────────────────
                        txt_cols = text_cols_by_table.get(table, [])[:10]
                        if txt_cols and row_count:
                            try:
                                parts = [
                                    f'AVG(CASE WHEN "{c}" IS NOT NULL AND TRIM("{c}") != \'\' THEN 100.0 ELSE 0.0 END)'
                                    for c in txt_cols
                                ]
                                vr = conn.run(f'SELECT {", ".join(parts)} FROM "{schema}"."{table}"')
                                if vr and vr[0]:
                                    vals = vr[0] if isinstance(vr[0], (list, tuple)) else [vr[0]]
                                    vscore = float(sum(v or 0 for v in vals)) / len(vals)
                                    validity_scores.append(vscore)
                                    t_validity = round(vscore, 1)
                            except Exception:
                                pass

                        # ── Accuracy (per-table: % non-nullable cols) ──────
                        t_accuracy = None
                        if col_count:
                            n_nullable = len(nullable_by_table.get(table, []))
                            t_accuracy = round((col_count - n_nullable) * 100.0 / col_count, 1)

                    else:  # Snowflake
                        t_completeness = t_uniqueness = t_freshness = t_validity = t_accuracy = None
                        cursor = conn.cursor()
                        cursor.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
                        row_count = cursor.fetchone()[0]
                        cursor.execute(
                            "SELECT COUNT(*) FROM information_schema.columns "
                            f"WHERE table_schema = '{schema.upper()}' AND table_name = '{table.upper()}'"
                        )
                        col_count = cursor.fetchone()[0]

                    total_rows += row_count
                    table_results.append({
                        'name': table, 'row_count': row_count, 'col_count': col_count,
                        'dq': {
                            'Completeness': t_completeness,
                            'Uniqueness':   t_uniqueness,
                            'Freshness':    t_freshness,
                            'Validity':     t_validity,
                            'Accuracy':     t_accuracy,
                            'Consistency':  100.0,
                        },
                    })
                except Exception as e:
                    scan_errors += 1
                    table_results.append({
                        'name': table, 'row_count': None, 'col_count': None,
                        'error': str(e),
                        'dq': {'Completeness': None, 'Uniqueness': None, 'Freshness': None,
                               'Validity': None, 'Accuracy': None, 'Consistency': 0.0},
                    })

        # ── Aggregate DQ scores ───────────────────────────────────────────
        def _pct(num, den):
            return round(float(num) * 100.0 / float(den), 1) if den else None
        def _avg(lst):
            return round(float(sum(lst)) / len(lst), 1) if lst else None

        total_cells = total_null_cells + total_non_null_cells
        ok_tables   = len([t for t in table_results if 'error' not in t])
        dq_scores = {
            'Completeness': _pct(total_non_null_cells, total_cells),
            'Uniqueness':   _pct(uniq_num, uniq_den),
            'Freshness':    _avg(freshness_scores),
            'Validity':     _avg(validity_scores),
            'Accuracy':     float(schema_accuracy) if schema_accuracy is not None else None,
            'Consistency':  _pct(ok_tables, len(table_results)) if table_results else None,
        }

        return jsonify({
            'conn_key':     conn_key,
            'database':     database,
            'schema':       schema,
            'total_tables': len(tables),
            'total_rows':   total_rows,
            'scan_errors':  scan_errors,
            'tables':       table_results,
            'dq_scores':    dq_scores,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Lineage ──────────────────────────────────────────────────────────────────

@app.route('/lineage')
@login_required
def lineage():
    return render_template('lineage.html')


@app.route('/api/lineage/objects')
@login_required
def lineage_objects():
    """
    List all tables / views / matviews / functions / procedures in one or more schemas.
    Used by the lineage scope builder to populate the 'Focus Object' picker.
    Query params: conn=<key>  db=<database>  schema=<s1>&schema=<s2> ...
    """
    conn_key = request.args.get('conn', '').strip()
    database = request.args.get('db') or None
    schemas  = [s for s in request.args.getlist('schema') if s]
    if not conn_key or not schemas:
        return jsonify({'objects': []})

    configs = validator.get_database_configs(current_user=session['user_id'])
    cfg = next((c for c in configs if c['name'] == conn_key), None)
    if not cfg:
        return jsonify({'objects': [], 'error': 'Connection not found'})

    try:
        if cfg.get('type', 'postgres').lower() != 'postgres':
            return jsonify({'objects': []})

        sch_in = ', '.join(f"'{s}'" for s in schemas)
        objs   = []
        with db._get_connection_for_config(cfg, database=database) as conn:
            # Tables / views / matviews
            for r in conn.run(f"""
                SELECT n.nspname, c.relname,
                    CASE c.relkind
                        WHEN 'r' THEN 'table'  WHEN 'v' THEN 'view'
                        WHEN 'm' THEN 'matview' ELSE 'table' END
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r','v','m','p')
                  AND n.nspname IN ({sch_in})
                ORDER BY n.nspname, c.relname
            """):
                objs.append({'schema': r[0], 'name': r[1], 'kind': r[2]})

            # Functions / procedures
            for r in conn.run(f"""
                SELECT DISTINCT ON (n.nspname, p.proname)
                    n.nspname, p.proname,
                    CASE p.prokind WHEN 'p' THEN 'procedure' ELSE 'function' END
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                JOIN pg_language  l ON l.oid = p.prolang
                WHERE n.nspname IN ({sch_in})
                  AND p.prokind IN ('f','p')
                  AND l.lanname IN ('sql','plpgsql')
                ORDER BY n.nspname, p.proname
            """):
                objs.append({'schema': r[0], 'name': r[1] + '()', 'kind': r[2]})

        return jsonify({'objects': sorted(objs, key=lambda o: (o['schema'], o['name']))})
    except Exception as e:
        return jsonify({'objects': [], 'error': str(e)})


@app.route('/api/lineage/graph', methods=['POST'])
@login_required
def lineage_graph():
    """
    Build a lineage graph from one or more user-selected scopes.
    Body: { "selections": [{"conn":"<key>","db":"<dbname>","schemas":["s1","s2"],
                             "focus":{"schema":"...","name":"...","kind":"..."}}, ...] }
    Empty schemas = all schemas. Cross-scope referenced tables are added as dim 'external' nodes
    so edges are never silently dropped.
    If 'focus' is set on a selection, only the focused object and its connected
    nodes (bidirectional BFS) are kept from that scope.
    """
    data             = request.get_json(silent=True) or {}
    selections       = data.get('selections', [])
    include_routines = bool(data.get('include_routines', False))

    if not selections:
        return jsonify({'error': 'No scopes selected. Add at least one.'}), 400

    configs   = validator.get_database_configs(current_user=session['user_id'])
    all_nodes = []
    all_edges = []
    errors    = []

    for sel in selections:
        conn_key = (sel.get('conn') or '').strip()
        database = (sel.get('db')   or '').strip() or None   # handles JSON null safely
        schemas  = [s for s in (sel.get('schemas') or []) if s]
        focus    = sel.get('focus') or None   # {schema, name, kind} — optional object focus

        if not conn_key:
            continue

        cfg = next((c for c in configs if c['name'] == conn_key), None)
        if not cfg:
            errors.append(f'Connection not found: {conn_key}')
            continue

        db_type      = cfg.get('type', 'postgres').lower()
        scope_prefix = f"{conn_key}|||{database or '__default__'}|||"
        scope_label  = f"{cfg.get('display_name') or conn_key} / {database or '(default)'}"
        node_start   = len(all_nodes)   # snapshot before this scope
        edge_start   = len(all_edges)

        try:
            if db_type == 'postgres':
                with db._get_connection_for_config(cfg, database=database) as conn:

                    # ── Schema WHERE clauses ──────────────────────────────
                    if schemas:
                        sch_in          = ', '.join(f"'{s}'" for s in schemas)
                        sch_where_nodes = f"AND n.nspname IN ({sch_in})"
                        sch_where_fk    = f"AND n1.nspname IN ({sch_in})"
                        sch_where_views = f"AND n_view.nspname IN ({sch_in})"
                    else:
                        _excl = "('pg_catalog','information_schema','pg_toast')"
                        sch_where_nodes = (f"AND n.nspname NOT IN {_excl} "
                                           "AND n.nspname NOT LIKE 'pg_%'")
                        sch_where_fk    = f"AND n1.nspname NOT IN {_excl}"
                        sch_where_views = f"AND n_view.nspname NOT IN {_excl}"

                    # ── Nodes ─────────────────────────────────────────────
                    for r in conn.run(f"""
                        SELECT n.nspname, c.relname,
                            CASE c.relkind
                                WHEN 'r' THEN 'table'  WHEN 'v' THEN 'view'
                                WHEN 'm' THEN 'matview' ELSE 'table' END,
                            GREATEST(pg_stat_get_live_tuples(c.oid), 0),
                            pg_size_pretty(pg_total_relation_size(c.oid))
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relkind IN ('r','v','m','p')
                          {sch_where_nodes}
                        ORDER BY n.nspname, c.relname
                    """):
                        schema_name, table_name, kind, rows, size = r
                        all_nodes.append({
                            'id':       f"{scope_prefix}{schema_name}.{table_name}",
                            'label':    table_name,
                            'schema':   schema_name,
                            'kind':     kind,
                            'rows':     int(rows),
                            'size':     size,
                            'conn_key': conn_key,
                            'database': database or '',
                            'scope':    scope_label,
                            'group':    f"{conn_key}__{database or '_'}__{schema_name}",
                            'external': False,
                        })

                    # ── FK edges (simplified: one edge per constraint) ────
                    # Uses subqueries to avoid cross-join on multi-col FKs
                    for r in conn.run(f"""
                        SELECT DISTINCT
                            n1.nspname || '.' || c1.relname  AS from_tbl,
                            n2.nspname || '.' || c2.relname  AS to_tbl,
                            (SELECT string_agg(a.attname,', '
                                ORDER BY array_position(con.conkey, a.attnum))
                             FROM pg_attribute a
                             WHERE a.attrelid = c1.oid
                               AND a.attnum   = ANY(con.conkey))  AS from_cols,
                            (SELECT string_agg(a.attname,', '
                                ORDER BY array_position(con.confkey, a.attnum))
                             FROM pg_attribute a
                             WHERE a.attrelid = c2.oid
                               AND a.attnum   = ANY(con.confkey)) AS to_cols,
                            con.conname
                        FROM pg_constraint con
                        JOIN pg_class     c1 ON c1.oid = con.conrelid
                        JOIN pg_namespace n1 ON n1.oid = c1.relnamespace
                        JOIN pg_class     c2 ON c2.oid = con.confrelid
                        JOIN pg_namespace n2 ON n2.oid = c2.relnamespace
                        WHERE con.contype = 'f'
                          {sch_where_fk}
                        ORDER BY 1
                    """):
                        from_d, to_d, fc, tc, cname = r
                        # Edge direction: parent → child (data flows from parent into child)
                        all_edges.append({
                            'from':       f"{scope_prefix}{to_d}",   # parent (upstream)
                            'to':         f"{scope_prefix}{from_d}",  # child  (downstream)
                            'type':       'fk',
                            'label':      f'{tc or ""} → {fc or ""}',
                            'constraint': cname,
                            'conn_key':   conn_key,
                            'scope_prefix': scope_prefix,
                        })

                    # ── View dependency edges (pg_depend is far more accurate
                    #    than information_schema.view_table_usage) ──────────
                    seen_view_edges = set()
                    for r in conn.run(f"""
                        SELECT DISTINCT
                            n_view.nspname || '.' || c_view.relname  AS view_name,
                            n_ref.nspname  || '.' || c_ref.relname   AS ref_name
                        FROM pg_depend d
                        JOIN pg_rewrite   rw     ON rw.oid      = d.objid
                                                 AND d.classid  = 'pg_rewrite'::regclass
                        JOIN pg_class     c_view ON c_view.oid  = rw.ev_class
                        JOIN pg_namespace n_view ON n_view.oid  = c_view.relnamespace
                        JOIN pg_class     c_ref  ON c_ref.oid   = d.refobjid
                                                 AND d.refclassid = 'pg_class'::regclass
                        JOIN pg_namespace n_ref  ON n_ref.oid   = c_ref.relnamespace
                        WHERE c_view.relkind IN ('v','m')
                          AND c_ref.relkind  IN ('r','m','p')
                          AND c_view.oid     != c_ref.oid
                          AND n_ref.nspname  NOT IN
                              ('pg_catalog','information_schema','pg_toast')
                          {sch_where_views}
                        ORDER BY 1
                    """):
                        fd, td = r
                        key = (fd, td)
                        if key not in seen_view_edges:
                            seen_view_edges.add(key)
                            # Edge direction: source table → view (data flows from source into view)
                            all_edges.append({
                                'from':         f"{scope_prefix}{td}",  # source table (upstream)
                                'to':           f"{scope_prefix}{fd}",  # view (downstream)
                                'type':         'view',
                                'label':        'feeds into',
                                'conn_key':     conn_key,
                                'scope_prefix': scope_prefix,
                            })

                    # ── Routine / SP lineage (sqlglot SQL-body parsing) ───
                    if include_routines and _has_sqlglot:
                        # Fast lookup: 'schema.table' → node_id
                        scope_nodes = [n for n in all_nodes
                                       if n.get('scope_prefix', scope_prefix) == scope_prefix
                                       or n['conn_key'] == conn_key]
                        qualified_lu   = {f"{n['schema']}.{n['label']}": n['id']
                                          for n in scope_nodes}
                        unqualified_lu = {}
                        for n in scope_nodes:
                            unqualified_lu.setdefault(n['label'].lower(), []).append(n['id'])

                        def _resolve(qname):
                            """Map a parsed table ref to an existing node ID."""
                            if qname in qualified_lu:
                                return qualified_lu[qname]
                            name_part = qname.split('.')[-1].lower()
                            matches = unqualified_lu.get(name_part, [])
                            return matches[0] if len(matches) == 1 else None

                        def _ensure_ext_node(qname):
                            """For cross-schema refs that _resolve() misses, create an
                            external placeholder node and cache it in qualified_lu so
                            subsequent calls for the same name resolve immediately."""
                            ext_id = f"{scope_prefix}{qname}"
                            if qname not in qualified_lu:
                                parts = qname.split('.', 1)
                                schema_p = parts[0] if len(parts) > 1 else ''
                                label_p  = parts[1] if len(parts) > 1 else qname
                                all_nodes.append({
                                    'id':       ext_id,
                                    'label':    label_p,
                                    'schema':   schema_p,
                                    'kind':     'table',
                                    'rows':     0,
                                    'size':     '',
                                    'conn_key': conn_key,
                                    'database': database or '',
                                    'scope':    'external reference',
                                    'group':    f"external__{schema_p}",
                                    'external': True,
                                })
                                qualified_lu[qname] = ext_id
                            return qualified_lu[qname]

                        # When a focus object is set, search routines in ALL
                        # non-system schemas so that SPs from any schema that
                        # reference the focused object are discovered.
                        # The BFS filter will discard unrelated routines.
                        # Without focus, stay within the user-selected schemas.
                        sch_where_rtn = (
                            "AND n.nspname NOT LIKE 'pg_%'"
                            if focus
                            else sch_where_nodes
                        )
                        routine_rows = conn.run(f"""
                            SELECT DISTINCT ON (n.nspname, p.proname)
                                n.nspname,
                                p.proname,
                                CASE p.prokind
                                    WHEN 'f' THEN 'function'
                                    WHEN 'p' THEN 'procedure'
                                    ELSE          'function'
                                END,
                                pg_get_functiondef(p.oid)
                            FROM pg_proc p
                            JOIN pg_namespace n  ON n.oid  = p.pronamespace
                            JOIN pg_language  l  ON l.oid  = p.prolang
                            WHERE n.nspname NOT IN
                                  ('pg_catalog','information_schema','pg_toast')
                              AND p.prokind IN ('f','p')
                              AND l.lanname IN ('sql','plpgsql')
                              {sch_where_rtn}
                            ORDER BY n.nspname, p.proname, p.oid
                        """)

                        for r_schema, r_name, r_kind, r_body in (routine_rows or []):
                            if r_name.lower().startswith('xxx'):
                                continue   # skip deprecated routines (xxx* naming convention)
                            reads, writes = _parse_routine_deps(
                                r_body or '', 'postgres')
                            if not reads and not writes:
                                continue   # skip routines with no detectable refs

                            rtn_id = f"{scope_prefix}{r_schema}.{r_name}()"
                            all_nodes.append({
                                'id':       rtn_id,
                                'label':    f"{r_name}()",
                                'schema':   r_schema,
                                'kind':     r_kind,
                                'rows':     0,
                                'size':     '',
                                'conn_key': conn_key,
                                'database': database or '',
                                'scope':    scope_label,
                                'group':    f"{conn_key}__{database or '_'}__{r_schema}",
                                'external': False,
                            })
                            for tbl in reads:
                                nid = _resolve(tbl)
                                # Cross-schema ref that isn't in scope: create an
                                # external placeholder so the edge isn't silently dropped
                                if nid is None and '.' in tbl:
                                    nid = _ensure_ext_node(tbl)
                                if nid:
                                    all_edges.append({
                                        'from':         nid,
                                        'to':           rtn_id,
                                        'type':         'rtn_reads',
                                        'label':        'reads',
                                        'conn_key':     conn_key,
                                        'scope_prefix': scope_prefix,
                                    })
                            for tbl in writes:
                                nid = _resolve(tbl)
                                if nid is None and '.' in tbl:
                                    nid = _ensure_ext_node(tbl)
                                if nid:
                                    all_edges.append({
                                        'from':         rtn_id,
                                        'to':           nid,
                                        'type':         'rtn_writes',
                                        'label':        'writes',
                                        'conn_key':     conn_key,
                                        'scope_prefix': scope_prefix,
                                    })

            else:  # Snowflake
                with db._get_connection_for_config(cfg, database=database) as conn:
                    cursor = conn.cursor()
                    sch_f = (f"AND table_schema IN ({', '.join(repr(s) for s in schemas)})"
                             if schemas else "AND table_schema <> 'INFORMATION_SCHEMA'")
                    cursor.execute(f"""
                        SELECT table_schema, table_name, table_type
                        FROM information_schema.tables WHERE true {sch_f}
                        ORDER BY table_schema, table_name
                    """)
                    for row in cursor.fetchall():
                        schema_name, table_name, ttype = row
                        all_nodes.append({
                            'id': f"{scope_prefix}{schema_name}.{table_name}",
                            'label': table_name, 'schema': schema_name,
                            'kind': 'view' if ttype == 'VIEW' else 'table',
                            'rows': 0, 'size': '', 'conn_key': conn_key,
                            'database': database or '', 'scope': scope_label,
                            'group': f"{conn_key}__{database or '_'}__{schema_name}",
                            'external': False,
                        })
                    sch_fk = (f"AND kcu.table_schema IN ({', '.join(repr(s) for s in schemas)})"
                              if schemas else "")
                    cursor.execute(f"""
                        SELECT DISTINCT
                            kcu.table_schema||'.'||kcu.table_name,
                            ccu.table_schema||'.'||ccu.table_name,
                            kcu.column_name, ccu.column_name, tc.constraint_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                             ON kcu.constraint_name=tc.constraint_name
                            AND kcu.table_schema=tc.table_schema
                        JOIN information_schema.constraint_column_usage ccu
                             ON ccu.constraint_name=tc.constraint_name
                        WHERE tc.constraint_type='FOREIGN KEY' {sch_fk}
                    """)
                    for r in cursor.fetchall():
                        all_edges.append({
                            'from': f"{scope_prefix}{r[0]}", 'to': f"{scope_prefix}{r[1]}",
                            'type': 'fk', 'label': f'{r[2]} → {r[3]}',
                            'constraint': r[4], 'conn_key': conn_key,
                            'scope_prefix': scope_prefix,
                        })

            # ── Focus BFS filter + role tagging ─────────────────────────────────────
            # Keep only the focused object and everything reachable from it
            # (bidirectional).  Then tag each surviving node with focusRole
            # (upstream | focus | downstream) and focusDepth using directed BFS.
            if focus:
                f_schema = (focus.get('schema') or '').strip()
                f_name   = (focus.get('name')   or '').strip()
                focus_id = f"{scope_prefix}{f_schema}.{f_name}"

                this_nodes = all_nodes[node_start:]
                this_edges = all_edges[edge_start:]
                node_ids   = {n['id'] for n in this_nodes}

                if focus_id in node_ids:
                    # ── Step 1: bidirectional connectivity filter ────────────────
                    bi_adj = {}
                    for e in this_edges:
                        bi_adj.setdefault(e['from'], set()).add(e['to'])
                        bi_adj.setdefault(e['to'],   set()).add(e['from'])

                    connected = set()
                    queue = [focus_id]
                    while queue:
                        nid = queue.pop()
                        if nid in connected:
                            continue
                        connected.add(nid)
                        for nb in bi_adj.get(nid, set()):
                            queue.append(nb)

                    kept_nodes = [n for n in this_nodes if n['id'] in connected]
                    kept_edges = [e for e in this_edges
                                  if e['from'] in connected and e['to'] in connected]

                    # ── Step 2: directed BFS to tag upstream / downstream ────────
                    # Edges are now directed: from=upstream, to=downstream
                    fwd = {}   # forward:  follow edges from→to  → reaches downstream
                    bwd = {}   # backward: follow edges to→from  → reaches upstream
                    for e in kept_edges:
                        fwd.setdefault(e['from'], set()).add(e['to'])
                        bwd.setdefault(e['to'],   set()).add(e['from'])

                    def _bfs_depth(start, adj_map):
                        depths = {}
                        q = [(start, 0)]
                        while q:
                            nid, d = q.pop(0)
                            if nid in depths:
                                continue
                            depths[nid] = d
                            for nb in adj_map.get(nid, set()):
                                if nb not in depths:
                                    q.append((nb, d + 1))
                        return depths

                    ds_depth = _bfs_depth(focus_id, fwd)  # downstream depths
                    us_depth = _bfs_depth(focus_id, bwd)  # upstream depths
                    bi_depth = _bfs_depth(focus_id, bi_adj)  # undirected distances (fallback)

                    for n in kept_nodes:
                        nid = n['id']
                        if nid == focus_id:
                            n['focusRole']  = 'focus'
                            n['focusDepth'] = 0
                        elif nid in us_depth and nid in ds_depth:
                            # Reachable both ways (cycle / shared node): pick shorter
                            if us_depth[nid] <= ds_depth[nid]:
                                n['focusRole']  = 'upstream'
                                n['focusDepth'] = -us_depth[nid]
                            else:
                                n['focusRole']  = 'downstream'
                                n['focusDepth'] = ds_depth[nid]
                        elif nid in us_depth:
                            n['focusRole']  = 'upstream'
                            n['focusDepth'] = -us_depth[nid]
                        elif nid in ds_depth:
                            n['focusRole']  = 'downstream'
                            n['focusDepth'] = ds_depth[nid]
                        else:
                            # Sibling node: connected via shared neighbour but no directed
                            # path to/from focus. Use undirected hop count as depth.
                            n['focusRole']  = 'downstream'
                            n['focusDepth'] = bi_depth.get(nid, 1)

                    del all_nodes[node_start:]
                    del all_edges[edge_start:]
                    all_nodes.extend(kept_nodes)
                    all_edges.extend(kept_edges)
                else:
                    # Focus object not found in scope — skip it gracefully
                    errors.append(
                        f"Focus object '{f_schema}.{f_name}' not found in scope "
                        f"'{scope_label}' — showing full scope instead."
                    )

        except Exception as e:
            errors.append(f'{conn_key} / {database}: {str(e)}')

    # ── Add 'external' placeholder nodes for cross-scope edge endpoints ───────
    # This ensures FK/view edges that cross schema boundaries are never dropped.
    node_id_set = {n['id'] for n in all_nodes}
    for edge in all_edges:
        for endpoint in ('from', 'to'):
            eid = edge[endpoint]
            if eid not in node_id_set:
                parts        = eid.split('|||', 2)
                schema_table = parts[2] if len(parts) > 2 else eid
                dot          = schema_table.find('.')
                schema       = schema_table[:dot]  if dot >= 0 else ''
                table        = schema_table[dot+1:] if dot >= 0 else schema_table
                all_nodes.append({
                    'id':       eid,
                    'label':    table,
                    'schema':   schema,
                    'kind':     'table',
                    'rows':     0,
                    'size':     '',
                    'conn_key': parts[0] if parts else '',
                    'database': parts[1] if len(parts) > 1 else '',
                    'scope':    'external reference',
                    'group':    f"external__{schema}",
                    'external': True,
                })
                node_id_set.add(eid)

    return jsonify({'nodes': all_nodes, 'edges': all_edges, 'errors': errors})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
