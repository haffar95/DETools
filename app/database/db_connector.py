import pg8000.native
import ssl
from contextlib import contextmanager
try:
    from sshtunnel import SSHTunnelForwarder
except Exception:
    SSHTunnelForwarder = None
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
        self.db_type = None
        self.conn_params = {}
        self.snowflake_params = {}  # Will store Snowflake specific parameters
        self.connection = None
        self.current_database = None
        self._use_ssh_tunnel = False
        self._ssh_params = {}
        self.config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'database_configs.json')
        self.config = {}  # Initialize config dictionary
        self.load_config()

        if not self.config:
            print("No database configurations found. Please add a connection first.")


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
                         account: str = None, warehouse: str = None, role: str = None, database: str = None,
                         ssh_host: str = None, ssh_user: str = None, ssh_password: str = None, ssh_port: int = 22):
        """Update the database connection parameters"""
        try:
            self.db_type = DatabaseType(db_type.lower())
            
            if self.db_type == DatabaseType.POSTGRES:
                # Validate port is a number
                port_num = int(port)
                if not (0 < port_num < 65536):
                    raise ValueError("Port number must be between 1 and 65535")

                # Determine if SSH tunneling is used
                self._use_ssh_tunnel = bool(ssh_host and ssh_user)
                if self._use_ssh_tunnel:
                    if SSHTunnelForwarder is None:
                        raise ConnectionError("SSH tunneling requested but 'sshtunnel' is not installed. Please install sshtunnel.")
                    # Store SSH parameters
                    self._ssh_params = {
                        "ssh_address_or_host": (ssh_host, int(ssh_port) if ssh_port else 22),
                        "ssh_username": ssh_user,
                        "ssh_password": ssh_password,
                        "remote_bind_address": (host, port_num)
                    }
                else:
                    # Test if host is reachable directly
                    try:
                        socket.create_connection((host, port_num), timeout=5)
                    except (socket.gaierror, socket.timeout, ConnectionRefusedError) as e:
                        raise ConnectionError(f"Cannot connect to {host}:{port}. Please check if the host is correct and the port is open.")

                # Use SSL but do not verify certificates to support providers with self-signed chains
                unverified_ssl = ssl._create_unverified_context()
                unverified_ssl.check_hostname = False
                self.conn_params.update({
                    "host": host,
                    "port": port_num,
                    "user": user,
                    "password": password,
                    "database": database,
                    "ssl_context": unverified_ssl
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
                    "schema": "READER",  # Set default schema to READER
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
        if not self.db_type:
            raise ConnectionError("No database connection configured. Please configure a database connection first.")
            
        try:
            if self.db_type == DatabaseType.POSTGRES:
                if not all(key in self.conn_params for key in ['host', 'port', 'user', 'password']):
                    raise ConnectionError("Incomplete PostgreSQL connection parameters. Please configure all required fields.")
                if self._use_ssh_tunnel:
                    return self._get_ssh_tunneled_pg_connection()
                return pg8000.native.Connection(**self.conn_params)
            else:  # Snowflake
                if not all(key in self.snowflake_params for key in ['account', 'user', 'password', 'warehouse', 'role', 'database']):
                    raise ConnectionError("Incomplete Snowflake connection parameters. Please configure all required fields.")
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

    @contextmanager
    def _get_ssh_tunneled_pg_connection(self):
        """Open an SSH tunnel and return a pg8000 connection within a context manager."""
        # Create and start tunnel
        forwarder = SSHTunnelForwarder(
            self._ssh_params["ssh_address_or_host"],
            ssh_username=self._ssh_params["ssh_username"],
            ssh_password=self._ssh_params.get("ssh_password"),
            remote_bind_address=self._ssh_params["remote_bind_address"],
            local_bind_address=("127.0.0.1", 0)
        )
        forwarder.start()
        try:
            local_port = forwarder.local_bind_port
            params = dict(self.conn_params)
            params.update({
                "host": "127.0.0.1",
                "port": int(local_port)
            })
            conn = pg8000.native.Connection(**params)
            try:
                with conn:
                    yield conn
            finally:
                # pg8000 context manager handles connection close
                pass
        finally:
            try:
                forwarder.stop()
            except Exception:
                pass

    def _add_schema_prefix(self, query, schema='reader'):
        """Add schema prefix to table references in a query if not already present"""
        import sqlparse
        from sqlparse.sql import Identifier, Token
        from sqlparse.tokens import Name

        # Parse the SQL query
        parsed = sqlparse.parse(query)[0]
        modified_query = query

        # Find all table references (identifiers that are not already schema-qualified)
        table_refs = []
        for token in parsed.flatten():
            if isinstance(token, Identifier):
                # Check if this is a table reference (not schema-qualified)
                if '.' not in token.value and token.value.lower() not in ['information_schema', 'pg_catalog']:
                    table_refs.append(token.value)
            elif token.ttype == Name and token.value.lower() not in ['information_schema', 'pg_catalog']:
                # Simple table references might appear as Name tokens
                if not any(token.value.lower() == kw.lower() for kw in ['select', 'from', 'where', 'and', 'or', 'join']):
                    table_refs.append(token.value)

        # Add schema prefix to each table reference
        for table in table_refs:
            # Only add schema if it's not already schema-qualified
            if f"{schema}.{table}" not in modified_query and f"\"{schema}\".{table}" not in modified_query:
                modified_query = modified_query.replace(f" {table} ", f" {schema}.{table} ")
                modified_query = modified_query.replace(f"({table} ", f"({schema}.{table} ")
                modified_query = modified_query.replace(f" {table})", f" {schema}.{table})")
                modified_query = modified_query.replace(f" {table},", f" {schema}.{table},")
                modified_query = modified_query.replace(f"({table},", f"({schema}.{table},")

        return modified_query

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
            # For Snowflake, ensure schema name is uppercase and properly quoted
            schema_name = f'"{schema.upper()}"'
            query = f"""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = {schema_name}
                ORDER BY table_name;
            """
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                return [row[0].upper() for row in cursor.fetchall()]  # Ensure consistent casing

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
            # For Snowflake, ensure table name is uppercase and properly quoted
            table_name = f'"{table_name.upper()}"'
            query = f"""
                SELECT column_name, data_type
                FROM information_schema.columns 
                WHERE table_name = {table_name}
                ORDER BY ordinal_position
            """
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                return [(row[0].upper(), row[1]) for row in cursor.fetchall()]  # Ensure consistent casing

    def get_table_columns_with_schema(self, table_name, schema):
        """Get all columns and their data types for a table within a specific schema"""
        if self.db_type == DatabaseType.POSTGRES:
            with self.get_connection() as conn:
                results = conn.run(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table "
                    "ORDER BY ordinal_position",
                    schema=schema, table=table_name
                )
                return [{'name': col[0], 'type': col[1]} for col in results]
        else:  # Snowflake
            schema_upper = schema.upper()
            table_upper = table_name.upper()
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT column_name, data_type "
                    "FROM information_schema.columns "
                    f"WHERE table_schema = '{schema_upper}' AND table_name = '{table_upper}' "
                    "ORDER BY ordinal_position"
                )
                return [{'name': row[0], 'type': row[1]} for row in cursor.fetchall()]

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
                SELECT nspname AS schema_name
                FROM pg_catalog.pg_namespace
                WHERE nspname NOT LIKE 'pg_%'
                  AND nspname <> 'information_schema'
                ORDER BY nspname;
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

    # ------------------------------------------------------------------
    # Per-config introspection (temporary connections, no side-effects)
    # ------------------------------------------------------------------

    @contextmanager
    def _get_connection_for_config(self, config, database=None):
        """Open a temporary connection to any config dict without touching the active connection.
        Pass `database` to override the database in the config (e.g. to introspect a specific DB)."""
        db_type = config.get('type', 'postgres').lower()

        if db_type == 'postgres':
            port_num = int(config.get('port', 5432))
            unverified_ssl = ssl._create_unverified_context()
            unverified_ssl.check_hostname = False
            # Use the explicitly requested database, then config database, then 'postgres' as fallback
            target_db = database or config.get('database') or 'postgres'
            conn_params = {
                'host': config['host'],
                'port': port_num,
                'user': config['user'],
                'password': config['password'],
                'ssl_context': unverified_ssl,
                'database': target_db,
            }

            use_ssh = bool(config.get('ssh_host') and config.get('ssh_user'))
            if use_ssh and SSHTunnelForwarder is not None:
                forwarder = SSHTunnelForwarder(
                    (config['ssh_host'], int(config.get('ssh_port') or 22)),
                    ssh_username=config['ssh_user'],
                    ssh_password=config.get('ssh_password'),
                    remote_bind_address=(config['host'], port_num),
                    local_bind_address=('127.0.0.1', 0),
                )
                forwarder.start()
                try:
                    p = dict(conn_params)
                    p.update({'host': '127.0.0.1', 'port': forwarder.local_bind_port})
                    conn = pg8000.native.Connection(**p)
                    try:
                        yield conn
                    finally:
                        try:
                            conn.close()
                        except Exception:
                            pass
                finally:
                    try:
                        forwarder.stop()
                    except Exception:
                        pass
            else:
                conn = pg8000.native.Connection(**conn_params)
                try:
                    yield conn
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

        else:  # Snowflake
            account = config.get('account', '')
            if '.snowflakecomputing.com' in account:
                account = account.split('.')[0]
            if account and '.' not in account:
                account = f"{account}.us-east-1"
            target_db = database or config.get('database', '')
            sf_params = {
                'account': account,
                'user': config['user'],
                'password': config['password'],
                'warehouse': config.get('warehouse', ''),
                'role': config.get('role', ''),
                'database': target_db,
                'insecure_mode': False,
                'protocol': 'https',
            }
            conn = snowflake.connector.connect(**sf_params)
            try:
                yield conn
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def get_databases_for_config(self, config):
        """Return all database names on the server for an arbitrary config dict."""
        db_type = config.get('type', 'postgres').lower()
        with self._get_connection_for_config(config) as conn:
            if db_type == 'postgres':
                results = conn.run(
                    "SELECT datname FROM pg_database "
                    "WHERE datistemplate = false ORDER BY datname"
                )
                return [row[0] for row in results]
            else:  # Snowflake
                cursor = conn.cursor()
                cursor.execute("SHOW DATABASES")
                # SHOW DATABASES result: created_on, name, ...
                return [row[1] for row in cursor.fetchall()]

    def get_schemas_for_config(self, config, database=None):
        """Return schema names for an arbitrary config dict, optionally scoped to a specific database."""
        db_type = config.get('type', 'postgres').lower()
        with self._get_connection_for_config(config, database=database) as conn:
            if db_type == 'postgres':
                results = conn.run(
                    "SELECT nspname FROM pg_catalog.pg_namespace "
                    "WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema' "
                    "ORDER BY nspname"
                )
                return [row[0] for row in results]
            else:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name NOT IN ('INFORMATION_SCHEMA') ORDER BY schema_name"
                )
                return [row[0] for row in cursor.fetchall()]

    def get_tables_for_config(self, config, schema, database=None):
        """Return table names in a schema for an arbitrary config dict."""
        db_type = config.get('type', 'postgres').lower()
        with self._get_connection_for_config(config, database=database) as conn:
            if db_type == 'postgres':
                results = conn.run(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema ORDER BY table_name",
                    schema=schema,
                )
                return [row[0] for row in results]
            else:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT table_name FROM information_schema.tables "
                    f"WHERE table_schema = '{schema.upper()}' ORDER BY table_name"
                )
                return [row[0] for row in cursor.fetchall()]

    def get_routines_for_config(self, config, schema, database=None):
        """Return routine (function/procedure) names and types in a schema."""
        db_type = config.get('type', 'postgres').lower()
        with self._get_connection_for_config(config, database=database) as conn:
            if db_type == 'postgres':
                results = conn.run(
                    "SELECT routine_name, routine_type FROM information_schema.routines "
                    "WHERE routine_schema = :schema ORDER BY routine_name",
                    schema=schema,
                )
                return [{'name': row[0], 'type': row[1]} for row in results]
            else:
                try:
                    cursor = conn.cursor()
                    cursor.execute(f'SHOW USER FUNCTIONS IN SCHEMA "{schema.upper()}"')
                    return [{'name': row[1], 'type': 'FUNCTION'} for row in cursor.fetchall()]
                except Exception:
                    return []

    def get_sequences_for_config(self, config, schema, database=None):
        """Return sequence names in a schema."""
        db_type = config.get('type', 'postgres').lower()
        with self._get_connection_for_config(config, database=database) as conn:
            if db_type == 'postgres':
                results = conn.run(
                    "SELECT sequence_name FROM information_schema.sequences "
                    "WHERE sequence_schema = :schema ORDER BY sequence_name",
                    schema=schema,
                )
                return [row[0] for row in results]
            else:
                try:
                    cursor = conn.cursor()
                    cursor.execute(f'SHOW SEQUENCES IN SCHEMA "{schema.upper()}"')
                    return [row[1] for row in cursor.fetchall()]
                except Exception:
                    return []

    def get_columns_for_config(self, config, schema, table, database=None):
        """Return column info for a table in an arbitrary config dict."""
        db_type = config.get('type', 'postgres').lower()
        with self._get_connection_for_config(config, database=database) as conn:
            if db_type == 'postgres':
                results = conn.run(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table "
                    "ORDER BY ordinal_position",
                    schema=schema, table=table,
                )
                return [{'name': row[0], 'type': row[1]} for row in results]
            else:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT column_name, data_type FROM information_schema.columns "
                    f"WHERE table_schema = '{schema.upper()}' AND table_name = '{table.upper()}' "
                    f"ORDER BY ordinal_position"
                )
                return [{'name': row[0], 'type': row[1]} for row in cursor.fetchall()]

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