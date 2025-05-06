import pg8000.native
import snowflake.connector
from config.config import Config
import socket
from typing import Dict, Any
from enum import Enum
import os
import json

class DatabaseType(Enum):
    POSTGRES = "postgres"
    SNOWFLAKE = "snowflake"

class DatabaseConnector:
    def __init__(self):
        self.db_type = DatabaseType.POSTGRES  # Default to PostgreSQL
        self.conn_params = {
            "host": Config.DB_HOST,
            "database": Config.DB_NAME,
            "user": Config.DB_USER,
            "password": Config.DB_PASSWORD,
            "port": int(Config.DB_PORT)
        }
        self.snowflake_params = {}  # Will store Snowflake specific parameters
        self.connection = None
        self.current_database = None
        self.config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'database_configs.json')
        self.config = {}  # Initialize config dictionary
        self.load_config()

        # Validate connection parameters
        if not all(self.conn_params.values()):
            raise ValueError("Missing required database connection parameters. Please check your config.py")

        # Test connection
        try:
            with self.get_connection() as conn:
                if self.db_type == DatabaseType.POSTGRES:
                    conn.run("SELECT 1")
                else:  # Snowflake
                    conn.cursor().execute("SELECT 1")
            print("Successfully connected to the database")
        except Exception as e:
            print(f"Failed to connect to the database: {str(e)}")
            print(f"Connection parameters (excluding password): {dict(filter(lambda x: x[0] != 'password', self.conn_params.items()))}")
            raise

    def load_config(self):
        """Load database configurations from the config file."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
            else:
                self.config = {}
        except Exception as e:
            print(f"Error loading database configurations: {str(e)}")
            self.config = {}

    def update_connection(self, host: str, port: str, user: str, password: str, db_type: str = "postgres", 
                         account: str = None, warehouse: str = None, role: str = None, database: str = None):
        """Update the database connection parameters"""
        try:
            self.db_type = DatabaseType(db_type.lower())
            
            if self.db_type == DatabaseType.POSTGRES:
                # Validate port is a number
                port_num = int(port)
                if not (0 < port_num < 65536):
                    raise ValueError("Port number must be between 1 and 65535")

                # Test if host is reachable
                try:
                    socket.create_connection((host, port_num), timeout=5)
                except (socket.gaierror, socket.timeout, ConnectionRefusedError) as e:
                    raise ConnectionError(f"Cannot connect to {host}:{port}. Please check if the host is correct and the port is open.")

                self.conn_params.update({
                    "host": host,
                    "port": port_num,
                    "user": user,
                    "password": password
                })
            else:  # Snowflake
                if not account:
                    raise ValueError("Account is required for Snowflake connection")
                if not database:
                    raise ValueError("Database is required for Snowflake connection")
                if not warehouse:
                    raise ValueError("Warehouse is required for Snowflake connection")
                if not role:
                    raise ValueError("Role is required for Snowflake connection")
                
                # Clean up account identifier and ensure it includes region
                account = account.split('.')[0] if '.snowflakecomputing.com' in account else account
                if '.' not in account and not account.endswith('.us-east-1'):
                    account = f"{account}.us-east-1"  # Default to us-east-1 if no region specified
                
                self.snowflake_params = {
                    "account": account,
                    "user": user,
                    "password": password,
                    "warehouse": warehouse,
                    "role": role,
                    "database": database,
                    "insecure_mode": False,  # Enable SSL
                    "protocol": "https"
                }

            # Test the new connection
            with self.get_connection() as conn:
                if self.db_type == DatabaseType.POSTGRES:
                    conn.run("SELECT 1")
                else:  # Snowflake
                    conn.cursor().execute("SELECT 1")
            print("Successfully updated database connection")
            return True

        except ValueError as e:
            print(f"Invalid connection parameters: {str(e)}")
            raise
        except ConnectionError as e:
            print(f"Connection error: {str(e)}")
            raise
        except Exception as e:
            print(f"Failed to update database connection: {str(e)}")
            raise

    def get_connection(self):
        """Get a database connection with improved error handling"""
        try:
            if self.db_type == DatabaseType.POSTGRES:
                return pg8000.native.Connection(**self.conn_params)
            else:  # Snowflake
                try:
                    return snowflake.connector.connect(**self.snowflake_params)
                except snowflake.connector.errors.OperationalError as e:
                    if "Could not connect to Snowflake backend" in str(e):
                        raise ConnectionError("Could not connect to Snowflake. Please check your account identifier and network connectivity.")
                    elif "Authentication failed" in str(e):
                        raise ConnectionError("Authentication failed. Please check your username and password.")
                    else:
                        raise ConnectionError(f"Snowflake connection error: {str(e)}")
        except (pg8000.exceptions.InterfaceError, snowflake.connector.errors.Error) as e:
            error_msg = str(e)
            if "password authentication failed" in error_msg.lower():
                raise ConnectionError("Authentication failed. Please check your username and password.")
            elif "could not connect to server" in error_msg.lower():
                raise ConnectionError(f"Cannot connect to the database server. Please check if the server is running.")
            else:
                raise ConnectionError(f"Database connection error: {error_msg}")
        except Exception as e:
            raise ConnectionError(f"Unexpected error while connecting to database: {str(e)}")

    def get_tables(self, schema='public'):
        """Get all tables in the database"""
        if self.db_type == DatabaseType.POSTGRES:
            query = """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = '{}'
                ORDER BY table_name;
            """
            with self.get_connection() as conn:
                results = conn.run(query.format(schema))
                return [row[0] for row in results]
        else:  # Snowflake
            query = f"""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = '{schema.upper()}'
                ORDER BY table_name;
            """
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                return [row[0] for row in cursor.fetchall()]

    def get_table_columns(self, table_name):
        """Get all columns and their data types for a table"""
        if self.db_type == DatabaseType.POSTGRES:
            query = f"""
                SELECT column_name, data_type
                FROM information_schema.columns 
                WHERE table_name = '{table_name}'
                ORDER BY ordinal_position
            """
            with self.get_connection() as conn:
                columns = [(col[0], col[1]) for col in conn.run(query)]
                return columns
        else:  # Snowflake
            query = f"""
                SELECT column_name, data_type
                FROM information_schema.columns 
                WHERE table_name = '{table_name.upper()}'
                ORDER BY ordinal_position
            """
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                return [(row[0], row[1]) for row in cursor.fetchall()]

    def get_primary_key_columns(self, table_name):
        """Get primary key and unique columns for a table"""
        if self.db_type == DatabaseType.POSTGRES:
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
        else:  # Snowflake
            # Get all columns first
            columns_query = f"""
                SELECT column_name, data_type
                FROM information_schema.columns 
                WHERE table_name = '{table_name.upper()}'
            """
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(columns_query)
                all_columns = [(row[0], row[1]) for row in cursor.fetchall()]

            # Get primary key and unique columns
            query = f"""
                SELECT column_name,
                       data_type,
                       CASE 
                           WHEN constraint_type = 'PRIMARY KEY' THEN 'PRIMARY KEY'
                           WHEN constraint_type = 'UNIQUE' THEN 'UNIQUE'
                       END as constraint_type
                FROM (
                    SELECT c.column_name,
                           c.data_type,
                           tc.constraint_type
                    FROM information_schema.columns c
                    LEFT JOIN information_schema.table_constraints tc
                        ON tc.table_name = c.table_name
                    LEFT JOIN information_schema.key_column_usage kcu
                        ON kcu.constraint_name = tc.constraint_name
                        AND kcu.column_name = c.column_name
                    WHERE c.table_name = '{table_name.upper()}'
                    AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
                )
                ORDER BY constraint_type DESC;
            """
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                results = [(row[0], row[1], row[2]) for row in cursor.fetchall()]
                
                if not results and all_columns:
                    # If no primary/unique keys found, suggest the first column as identifier
                    first_col, first_type = all_columns[0]
                    results = [(first_col, first_type, 'SUGGESTED ID')]
                
                return results

    def get_foreign_keys(self, table_name):
        """Get foreign key columns for a table"""
        if self.db_type == DatabaseType.POSTGRES:
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
        else:  # Snowflake
            query = f"""
                SELECT
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name,
                    c.data_type
                FROM 
                    information_schema.table_constraints AS tc 
                    JOIN information_schema.key_column_usage AS kcu
                      ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.constraint_column_usage AS ccu
                      ON ccu.constraint_name = tc.constraint_name
                    JOIN information_schema.columns c
                      ON c.table_name = tc.table_name
                      AND c.column_name = kcu.column_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_name = '{table_name.upper()}';
            """
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                return [(row[0], row[1], row[2], row[3]) for row in cursor.fetchall()]

    def get_schemas(self):
        """Get all schemas in the database"""
        if self.db_type == DatabaseType.POSTGRES:
            query = """
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
                ORDER BY schema_name;
            """
            with self.get_connection() as conn:
                results = conn.run(query)
                return [row[0] for row in results]
        else:  # Snowflake
            query = """
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE schema_name NOT IN ('INFORMATION_SCHEMA')
                ORDER BY schema_name;
            """
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                return [row[0] for row in cursor.fetchall()]

    def get_current_database(self):
        """Get the currently selected database"""
        return self.current_database

    def set_current_database(self, db_name):
        """Set the current database"""
        if db_name in self.config:
            db_config = self.config[db_name]
            
            # Update connection parameters based on database type
            if db_config['type'] == 'postgres':
                self.db_type = DatabaseType.POSTGRES
                self.conn_params.update({
                    'host': db_config['host'],
                    'port': int(db_config['port']),
                    'user': db_config['user'],
                    'password': db_config['password']
                })
            else:  # Snowflake
                self.db_type = DatabaseType.SNOWFLAKE
                self.snowflake_params = {
                    'account': db_config['account'],
                    'user': db_config['user'],
                    'password': db_config['password'],
                    'warehouse': db_config['warehouse'],
                    'role': db_config['role'],
                    'database': db_config['database']
                }
            
            self.current_database = db_name
            return True
        return False