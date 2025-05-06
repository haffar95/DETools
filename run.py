from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from app.database.db_connector import DatabaseConnector
from app.validation.validators import DataValidator
from flask_cors import CORS
import os

# Create Flask app with explicit template and static folders
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'app', 'templates'))
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'app', 'static'))
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
CORS(app)
app.config.from_object('config.config.Config')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB limit

db = DatabaseConnector()
validator = DataValidator()

@app.route('/')
def dashboard():
    schemas = db.get_schemas()
    return render_template('dashboard.html', schemas=schemas)

@app.route('/api/columns/<table_name>')
def get_columns(table_name):
    columns = db.get_table_columns(table_name)
    return jsonify({
        'columns': columns
    })

@app.route('/api/validate')
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
def get_tables(schema):
    tables = db.get_tables(schema)
    return jsonify({
        'tables': tables
    })

@app.route('/api/validate-schema', methods=['POST'])
def validate_schema():
    data = request.get_json()
    schema = data.get('schema')
    if not schema:
        return jsonify({'error': 'Schema is required'}), 400

    # Call your validation logic here
    results = validator.validate_schema(schema)
    return jsonify(results)

@app.route('/api/validate-query', methods=['POST'])
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
            return jsonify(results), 200

        return jsonify(results)
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'row_count': 0,
            'duplicates': {'count': 0, 'details': []},
            'null_values': {'details': {}}
        }), 500

@app.route('/overview')
def overview_page():
    schemas = db.get_schemas()
    return render_template('overview.html', schemas=schemas)

@app.route('/database-config', methods=['GET'])
def database_config():
    # Retrieve existing database configurations
    databases = validator.get_database_configs()  # Implement this method in your validator
    return render_template('database_config.html', databases=databases)

@app.route('/add_database_config', methods=['POST'])
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
        
        validator.save_database_config(
            db_name=db_name,
            db_type=db_type,
            db_host=db_host,
            db_port=db_port,
            db_user=db_user,
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
def delete_database():
    try:
        db_name = request.form['db_name']
        if validator.delete_database_config(db_name):
            flash('Database configuration deleted successfully!', 'success')
        else:
            flash('Database configuration not found!', 'error')
    except Exception as e:
        flash(f'Error deleting database configuration: {str(e)}', 'error')
    
    return redirect(url_for('database_config'))

@app.route('/select-database', methods=['POST'])
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
        
        selected_config = next((db for db in db_configs if db['name'] == selected_db), None)
        print(f"Selected config: {selected_config}")  # Debug log
        
        if not selected_config:
            flash('Database configuration not found', 'error')
            return redirect(url_for('database_config'))
        
        # Update the database connector with the selected configuration
        if selected_config['type'] == 'postgres':
            db.update_connection(
                host=selected_config['host'],
                port=selected_config['port'],
                user=selected_config['user'],
                password=selected_config['password'],
                db_type='postgres'
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
        
        # Set the current database in the validator
        if validator.set_selected_database(selected_db):
            print(f"Successfully set selected database to: {selected_db}")  # Debug log
            flash(f'Successfully connected to {selected_db}', 'success')
            return redirect(url_for('dashboard'))
        else:
            print(f"Failed to set selected database: {selected_db}")  # Debug log
            flash('Failed to connect to selected database', 'error')
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
def get_database_configs():
    """Get all available database configurations"""
    try:
        databases = validator.get_database_configs()
        return jsonify({
            'databases': databases
        })
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)