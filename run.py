from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, session
from app.database.db_connector import DatabaseConnector
from app.validation.validators import DataValidator
from app.models.user import User
from app.auth import login_required, admin_required, connection_access_required
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
            return redirect(url_for('dashboard'))
        
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
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        schemas = []
        if 'current_connection' in session:
            try:
                schemas = db.get_schemas()
            except Exception as e:
                print(f"Error fetching schemas: {str(e)}")
        return render_template('dashboard.html', schemas=schemas, needs_connection='current_connection' not in session)
        return render_template('dashboard.html', schemas=schemas)
    except ConnectionError as e:
        flash(str(e), 'error')
        return redirect(url_for('database_config'))

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
    table_name = request.args.get('table')
    schema = request.args.get('schema', 'public')
    key_column = request.args.get('key_column')
    foreign_key = request.args.get('foreign_key')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    date_column = request.args.get('date_column')
    
    if not table_name:
        return jsonify({'error': 'Table name is required'}), 400
        
    try:
        results = validator.validate_table(table_name, schema, start_date, end_date, date_column, key_column, foreign_key)
        if 'error' in results:
            return jsonify({'error': results['error']}), 500
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': f"Validation failed: {str(e)}"}), 500

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
        
        if not query:
            return jsonify({'error': 'Query is required'}), 400

        # Normalize query by removing extra whitespace
        normalized_query = ' '.join(query.strip().split())
        
        # Additional security check for non-SELECT operations
        dangerous_keywords = ['insert', 'update', 'delete', 'drop', 'truncate', 'alter', 'create', 'replace']
        dangerous_patterns = [f' {keyword} ' for keyword in dangerous_keywords]  # Add spaces to avoid matching substrings
        if any(pattern in f' {normalized_query.lower()} ' for pattern in dangerous_patterns):
            return jsonify({'error': 'Only SELECT queries are allowed. No data modification operations permitted.'}), 400
            
        results = validator._validate_custom_query(query=query)
        
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
            return redirect(url_for('dashboard'))
        else:
            print(f"Failed to set selected database: {selected_db}")  # Debug log
            flash('You do not have permission to access this database', 'error')
            return redirect(url_for('database_config'))
    except Exception as e:
        print(f"Error selecting database: {str(e)}")  # Debug log
        flash(f'Error selecting database: {str(e)}', 'error')
        return redirect(url_for('database_config'))

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)