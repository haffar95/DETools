from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, session
from app.database.db_connector import DatabaseConnector
from app.validation.validators import DataValidator
from app.models.user import User
from app.auth import login_required, admin_required, connection_access_required
from app.checks import engine as check_engine
from app.checks.catalog import CHECK_CATALOG
from flask_cors import CORS
import os
import secrets

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



@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.get_user(username)
        if user and user.check_password(password):
            session['user_id'] = user.username
            session['is_admin'] = user.is_admin
            flash('Successfully logged in!', 'success')
            return redirect(url_for('overview_page'))
        
        flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    # Clear Flask session
    session.clear()
    # Clear database validator session data
    validator.clear_session()
    flash('Successfully logged out', 'success')
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
        flash('Username and password are required', 'danger')
        return redirect(url_for('admin_panel'))
    
    existing_user = User.get_user(username)
    if existing_user:
        flash('Username already exists', 'danger')
        return redirect(url_for('admin_panel'))
    
    new_user = User(username, password, is_admin)
    users = User('temp').load_users()
    users.append(new_user)
    new_user.save_users(users)
    
    flash('User created successfully', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete-user/<username>', methods=['POST'])
@admin_required
def delete_user(username):
    if username == session.get('user_id'):
        flash('Cannot delete your own account', 'danger')
        return redirect(url_for('admin_panel'))
    
    users = User('temp').load_users()
    users = [u for u in users if u.username != username]
    User('temp').save_users(users)
    
    flash('User deleted successfully', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/update-user-connections/<username>', methods=['POST'])
@admin_required
def update_user_connections(username):
    connection = request.form.get('connection')
    action = request.form.get('action')
    
    if not connection or not action:
        flash('Connection and action are required', 'danger')
        return redirect(url_for('admin_panel'))
    
    user = User.get_user(username)
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('admin_panel'))
    
    if action == 'add':
        user.add_connection(connection)
        flash('Connection added successfully', 'success')
    elif action == 'remove':
        user.remove_connection(connection)
        flash('Connection removed successfully', 'success')
    
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
        
        flash('Database configuration added successfully!', 'success')
    except Exception as e:
        flash(f'Error adding database configuration: {str(e)}', 'error')
    
    return redirect(url_for('database_config'))

@app.route('/delete_database', methods=['POST'])
@login_required
def delete_database():
    try:
        db_name = request.form['db_name']
        if validator.delete_database_config(db_name, current_user=session['user_id']):
            flash('Database configuration deleted successfully!', 'success')
        else:
            flash('You do not have permission to delete this database configuration', 'error')
    except Exception as e:
        flash(f'Error deleting database configuration: {str(e)}', 'error')
    
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
            flash('No database selected', 'error')
            return redirect(url_for('database_config'))
        
        # Get the database configuration
        db_configs = validator.get_database_configs()
        print(f"Available database configs: {db_configs}")  # Debug log
        
        # Verify that the selected database belongs to the current user
        selected_config = next((db for db in db_configs if db['name'] == selected_db and db.get('creator') == session['user_id']), None)
        
        if not selected_config:
            flash('You do not have access to this database', 'error')
            return redirect(url_for('database_config'))
        print(f"Selected config: {selected_config}")  # Debug log
        
        if not selected_config:
            flash('Database configuration not found', 'error')
            return redirect(url_for('database_config'))
        
        # Check if user has access to this connection
        user = User.get_user(session['user_id'])
        if not user.can_access_connection(selected_db):
            flash('You do not have access to this connection', 'danger')
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
            flash(f'Successfully connected to {selected_db}', 'success')
            return redirect(request.referrer or url_for('overview_page'))
        else:
            print(f"Failed to set selected database: {selected_db}")  # Debug log
            flash('You do not have permission to access this database', 'error')
            return redirect(request.referrer or url_for('overview_page'))
    except Exception as e:
        print(f"Error selecting database: {str(e)}")  # Debug log
        flash(f'Error selecting database: {str(e)}', 'error')
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)