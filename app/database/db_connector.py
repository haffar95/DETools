import pg8000.native
from config.config import Config

class DatabaseConnector:
    def __init__(self):
        # Get environment variables with default values
        self.conn_params = {
            "host": Config.DB_HOST,
            "database": Config.DB_NAME,
            "user": Config.DB_USER,
            "password": Config.DB_PASSWORD,
            "port": int(Config.DB_PORT)
        }

        # Validate connection parameters
        if not all(self.conn_params.values()):
            raise ValueError("Missing required database connection parameters. Please check your config.py")

        # Test connection
        try:
            with self.get_connection() as conn:
                conn.run("SELECT 1")
            print("Successfully connected to the database")
        except Exception as e:
            print(f"Failed to connect to the database: {str(e)}")
            print(f"Connection parameters (excluding password): {dict(filter(lambda x: x[0] != 'password', self.conn_params.items()))}")
            raise

    def get_connection(self):
        try:
            return pg8000.native.Connection(**self.conn_params)
        except Exception as e:
            print(f"Connection error: {str(e)}")
            raise

    def get_tables(self, schema='public'):
        """Get all tables in the database"""
        query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = '{}'
            ORDER BY table_name;
        """
        with self.get_connection() as conn:
            results = conn.run(query.format(schema))
            return [row[0] for row in results]

    def get_table_columns(self, table_name):
        """Get all columns and their data types for a table"""
        query = f"""
            SELECT column_name, data_type
            FROM information_schema.columns 
            WHERE table_name = '{table_name}'
            ORDER BY ordinal_position
        """
        with self.get_connection() as conn:
            columns = [(col[0], col[1]) for col in conn.run(query)]
            return columns

    def get_primary_key_columns(self, table_name):
        """Get primary key and unique columns for a table"""
        # First check if the table exists
        check_table_query = f"""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_name = '{table_name}'
            );
        """
        with self.get_connection() as conn:
            exists = conn.run(check_table_query)[0][0]
            if not exists:
                return []

        # Get all columns first
        columns_query = f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}'
        """
        with self.get_connection() as conn:
            all_columns = [col[0] for col in conn.run(columns_query)]

        # Get primary key and unique columns
        query = f"""
            SELECT a.attname as column_name,
                   format_type(a.atttypid, a.atttypmod) as data_type,
                   CASE 
                       WHEN i.indisprimary THEN 'PRIMARY KEY'
                       WHEN i.indisunique THEN 'UNIQUE'
                   END as constraint_type,
                   c.relname as table_name
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid
            AND a.attnum = ANY(i.indkey)
            JOIN pg_class c ON c.oid = i.indrelid
            WHERE i.indrelid = '{table_name}'::regclass
            AND (i.indisprimary OR i.indisunique)
            ORDER BY i.indisprimary DESC, i.indisunique DESC
        """
        
        with self.get_connection() as conn:
            results = [(col[0], col[1], col[2]) for col in conn.run(query)]
            
            if not results:
                # If no primary/unique keys found, suggest the first column as identifier
                if all_columns:
                    first_col = all_columns[0]
                    # Get the data type of the first column
                    type_query = f"""
                        SELECT data_type 
                        FROM information_schema.columns 
                        WHERE table_name = '{table_name}' 
                        AND column_name = '{first_col}'
                    """
                    col_type = conn.run(type_query)[0][0]
                    results = [(first_col, col_type, 'SUGGESTED ID')]
            
            return results 

    def get_foreign_keys(self, table_name):
        """Get foreign key columns for a table"""
        query = f"""
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                format_type(a.atttypid, a.atttypmod) as data_type
            FROM 
                information_schema.table_constraints AS tc 
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
                  AND ccu.table_schema = tc.table_schema
                JOIN pg_attribute a 
                  ON a.attname = kcu.column_name
                  AND a.attrelid = tc.table_name::regclass
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_name = '{table_name}';
        """
        with self.get_connection() as conn:
            results = [(col[0], col[1], col[2], col[3]) for col in conn.run(query)]
            return results 

    def get_schemas(self):
        """Get all schemas in the database"""
        query = """
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
            ORDER BY schema_name;
        """
        with self.get_connection() as conn:
            results = conn.run(query)
            return [row[0] for row in results]