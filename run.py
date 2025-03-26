from flask import Flask, render_template, jsonify, request
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

        # Normalize query by removing extra whitespace and converting to lowercase
        normalized_query = ' '.join(query.lower().split())
        
        # Check if the query is a SELECT statement (including CTEs and subqueries)
        if not any(normalized_query.startswith(prefix) for prefix in ['select', 'with', '(select']):
            return jsonify({'error': 'Only SELECT queries are allowed. Query must start with SELECT, WITH, or (SELECT)'}), 400
            
        # Additional security check for non-SELECT operations
        dangerous_keywords = ['insert', 'update', 'delete', 'drop', 'truncate', 'alter', 'create', 'replace']
        dangerous_patterns = [f' {keyword} ' for keyword in dangerous_keywords]  # Add spaces to avoid matching substrings
        if any(pattern in f' {normalized_query} ' for pattern in dangerous_patterns):
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)