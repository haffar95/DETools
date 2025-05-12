from app.database.db_connector import DatabaseConnector, DatabaseType
from datetime import datetime
from functools import lru_cache
from time import time
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Union

class DataValidator:
    def __init__(self):
        self.db = DatabaseConnector()
        self._cache = {}
        self._cache_timestamps = {}
        self._cache_ttl = 1800  # 30 minutes in seconds
        self._config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'database_configs.json')
        self._database_configs = {}
        self._selected_database = None
        # Load existing database configurations
        self._load_database_configs()
        # Define table-specific validation rules
        self.table_rules = {
            'contacts': {
                'required_columns': [
                    'ssn', 'zip', 'city', 'email', 'phone', 'id', 'state', 'address'
                ],
                'unique_columns': [
                    'ssn', 'email', 'phone', 'id'
                ],
                'date_rules': {
                    'min_date': '1900-01-01',
                    'allow_future': False,
                    'date_columns': [
                        'birth_date',
                        'created_at',
                        'updated_at'
                    ]
                },
                'timeliness_rules': {
                    'freshness': {
                        'created_at': {'max_age_days': 30},  # Data should not be older than 30 days
                        'updated_at': {'max_age_days': 7}    # Records should be updated weekly
                    },
                    'frequency': {
                        'created_at': {'expected_daily_records': 100}  # Expect ~100 new records per day
                    }
                }
            },
            'liquidation_contacts': {
                'required_columns': [
                    'id',
                    'claw_back',
                    'payment_frequency_type',
                    'gateway',
                    'purchase_status',
                    'purchased_debt',
                    'affiliate_name',
                    'affiliate_id',
                    'lastname',
                    'firstname'
                ],
                'unique_columns': [
                    'id'
                ],
                'timeliness_rules': {
                    'freshness': {
                        'created_at': {'max_age_days': 14},
                        'updated_at': {'max_age_days': 3}
                    }
                }
            }
        }

    def _load_database_configs(self):
        """Load database configurations from the JSON file"""
        try:
            if os.path.exists(self._config_file):
                with open(self._config_file, 'r') as f:
                    self._database_configs = json.load(f)
        except Exception as e:
            print(f"Error loading database configurations: {str(e)}")
            self._database_configs = {}

    def _save_database_configs(self):
        """Save database configurations to the JSON file"""
        try:
            os.makedirs(os.path.dirname(self._config_file), exist_ok=True)
            with open(self._config_file, 'w') as f:
                json.dump(self._database_configs, f, indent=4)
        except Exception as e:
            print(f"Error saving database configurations: {str(e)}")

    def get_database_configs(self) -> List[Dict[str, Any]]:
        """Get all database configurations"""
        configs = [
            {
                'name': name,
                'type': config['type'],
                'host': config.get('host', ''),
                'port': config.get('port', ''),
                'user': config['user'],
                'password': config['password'],
                'account': config.get('account'),
                'warehouse': config.get('warehouse'),
                'role': config.get('role'),
                'database': config.get('database')
            }
            for name, config in self._database_configs.items()
        ]
        return configs

    def save_database_config(self, db_name: str, db_type: str, db_host: str, db_port: str, db_user: str, db_password: str, 
                           db_account: str = None, db_warehouse: str = None, db_role: str = None, db_database: str = None):
        """Save a new database configuration"""
        self._database_configs[db_name] = {
            'type': db_type,
            'host': db_host,
            'port': db_port,
            'user': db_user,
            'password': db_password,
            'account': db_account,
            'warehouse': db_warehouse,
            'role': db_role,
            'database': db_database
        }
        self._save_database_configs()

    def delete_database_config(self, db_name: str):
        """Delete a database configuration"""
        if db_name in self._database_configs:
            del self._database_configs[db_name]
            self._save_database_configs()
            # If the deleted database was selected, clear the selection
            if self._selected_database == db_name:
                self._selected_database = None
            return True
        return False

    def set_selected_database(self, db_name: str):
        """Set the selected database for validation"""
        if db_name in self._database_configs:
            self._selected_database = db_name
            # Update the database connector with the new configuration
            config = self._database_configs[db_name]
            
            # Set default port for Snowflake if not specified
            if config['type'] == 'snowflake' and not config['port']:
                config['port'] = 443
                
            self.db.update_connection(
                host=config['host'],
                port=config['port'],
                user=config['user'],
                password=config['password'],
                db_type=config['type'],
                account=config.get('account'),
                warehouse=config.get('warehouse'),
                role=config.get('role'),
                database=config.get('database')
            )
            return True
        return False

    def get_selected_database(self) -> Optional[str]:
        """Get the currently selected database name"""
        return self._selected_database

    def _check_accuracy(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Check data accuracy including realistic value ranges, date formats, and patterns"""
        accuracy_issues = {
            'type_mismatches': 0,
            'value_range_violations': 0,
            'format_violations': 0,
            'total_checked': 0,
            'details': {}
        }

        # Common date formats to try
        date_formats = ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y/%m/%d', '%d/%m/%Y', '%m/%d/%Y']

        for col in df.columns:
            col_issues = []
            total_checked = len(df[col].dropna())
            accuracy_issues['total_checked'] += total_checked

            # Check data types and basic patterns
            if 'date' in col.lower() or 'time' in col.lower():
                # Try each format until one works
                dates = None
                for fmt in date_formats:
                    try:
                        dates = pd.to_datetime(df[col], format=fmt, errors='raise')
                        break
                    except ValueError:
                        continue
                
                # If no format worked, use ISO format as a last resort
                if dates is None:
                    try:
                        dates = pd.to_datetime(df[col], format='%Y-%m-%d', errors='raise')
                    except ValueError:
                        # If ISO format fails, mark as invalid
                        dates = pd.Series([pd.NaT] * len(df))
                    
                invalid_dates = df[dates.isna() & df[col].notna()]
                if not invalid_dates.empty:
                    col_issues.append({
                        'type': 'invalid_date_format',
                        'count': len(invalid_dates),
                        'examples': invalid_dates[col].head().tolist()
                    })
                    accuracy_issues['format_violations'] += len(invalid_dates)

                # Check for future dates where inappropriate
                if not col.lower().endswith('_due') and not col.lower().endswith('_deadline'):
                    future_dates = df[dates > pd.Timestamp.now()]
                    if not future_dates.empty:
                        col_issues.append({
                            'type': 'future_date',
                            'count': len(future_dates),
                            'examples': future_dates[col].head().tolist()
                        })
                        accuracy_issues['value_range_violations'] += len(future_dates)

            # Check numerical values for realistic ranges
            elif df[col].dtype in ['int64', 'float64']:
                if 'age' in col.lower():
                    invalid_ages = df[(df[col] < 0) | (df[col] > 120)]
                    if not invalid_ages.empty:
                        col_issues.append({
                            'type': 'unrealistic_age',
                            'count': len(invalid_ages),
                            'examples': invalid_ages[col].head().tolist()
                        })
                        accuracy_issues['value_range_violations'] += len(invalid_ages)

                elif any(term in col.lower() for term in ['amount', 'price', 'cost']):
                    negative_values = df[df[col] < 0]
                    if not negative_values.empty:
                        col_issues.append({
                            'type': 'negative_amount',
                            'count': len(negative_values),
                            'examples': negative_values[col].head().tolist()
                        })
                        accuracy_issues['value_range_violations'] += len(negative_values)

            # Check email format
            elif 'email' in col.lower():
                import re
                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                invalid_emails = df[~df[col].str.match(email_pattern, na=False)]
                if not invalid_emails.empty:
                    col_issues.append({
                        'type': 'invalid_email',
                        'count': len(invalid_emails),
                        'examples': invalid_emails[col].head().tolist()
                    })
                    accuracy_issues['format_violations'] += len(invalid_emails)

            # Check phone number format
            elif 'phone' in col.lower():
                phone_pattern = r'^\+?[1-9]\d{1,14}$'
                invalid_phones = df[~df[col].str.match(phone_pattern, na=False)]
                if not invalid_phones.empty:
                    col_issues.append({
                        'type': 'invalid_phone',
                        'count': len(invalid_phones),
                        'examples': invalid_phones[col].head().tolist()
                    })
                    accuracy_issues['format_violations'] += len(invalid_phones)

            if col_issues:
                accuracy_issues['details'][col] = col_issues

        return accuracy_issues

    def validate_table(self, table_name: str, schema: str = 'public', start_date: Optional[str] = None, end_date: Optional[str] = None, date_column: Optional[str] = None, key_column: Optional[str] = None, foreign_key: Optional[str] = None) -> Dict[str, Any]:
        """Perform basic validations on a table"""
        # Build base query
        query = f"""
            SELECT t.* 
            FROM "{schema}"."{table_name}" t
            {f"WHERE DATE({date_column}) BETWEEN '{start_date}' AND '{end_date}'" 
                if start_date and end_date and date_column else ""}
        """

        with self.db.get_connection() as conn:
            try:
                results = conn.run(query)
                if not results:
                    return {
                        'error': 'No data found',
                        'row_count': 0,
                        'null_values': {'details': {}}
                    }
                columns = [desc['name'] for desc in conn.columns]
                df = pd.DataFrame(results, columns=columns)

                # Basic validation results
                validation_results = {
                    'null_values': self._check_null_values(df),
                    'duplicates': self._check_duplicates(df, key_column=key_column, foreign_key=foreign_key),
                    'format_issues': self._check_format_issues(df),
                    'outliers': self._check_outliers(df),
                    'timeliness': self._check_basic_timeliness(df),
                    'row_count': len(df)
                }
                
                return self._ensure_serializable(validation_results)
            except Exception as e:
                return {
                    'error': str(e),
                    'row_count': 0,
                    'null_values': {'details': {}}
                }

    def _validate_primary_key(self, df: pd.DataFrame, key_column: str, occurrences_col: str, null_col: str) -> Dict[str, Any]:
        """Validate primary key constraints"""
        result = {
            'is_valid': True,
            'issues': []
        }
        
        # Check for nulls in primary key
        null_count = df[df[null_col] == 1].shape[0]
        if null_count > 0:
            result['is_valid'] = False
            result['issues'].append(f"Found {null_count} null values in primary key column")

        # Check for duplicates in primary key
        duplicates = df[df[occurrences_col] > 1]
        duplicate_count = len(duplicates)
        if duplicate_count > 0:
            result['is_valid'] = False
            result['issues'].append(f"Found {duplicate_count} duplicate values in primary key column")
            # Get the duplicate values
            duplicate_values = duplicates[key_column].unique().tolist()
            result['duplicate_values'] = duplicate_values

        return result

    def _validate_foreign_key(self, df: pd.DataFrame, foreign_key: str, null_col: str) -> Dict[str, Any]:
        """Validate foreign key references"""
        result = {
            'is_valid': True,
            'issues': []
        }

        # Check for nulls in foreign key
        null_count = df[df[null_col] == 1].shape[0]
        if null_count > 0:
            result['issues'].append(f"Found {null_count} null values in foreign key column")

        # Get unique values in foreign key column
        unique_values = df[foreign_key].unique().tolist()
        result['unique_values_count'] = len(unique_values)

        return result

    def _check_duplicates(self, df: pd.DataFrame, columns: Optional[List[str]] = None, key_column: Optional[str] = None, foreign_key: Optional[str] = None) -> Dict[str, Any]:
        """Check for duplicate records"""
        duplicate_info = {
            'count': 0,
            'has_duplicates': False,
            'duplicate_records': [],
            'details': {}
        }
        
        # Define columns to check for duplicates
        check_columns = []
        
        # Add primary key if specified
        if key_column:
            check_columns.append(key_column)
            duplicate_mask = df.duplicated(subset=[key_column], keep=False)
            duplicate_records = df[duplicate_mask]
            if not duplicate_records.empty:
                duplicate_info['details']['primary_key'] = {
                    'count': len(duplicate_records) // 2,
                    'values': sorted(duplicate_records[key_column].unique().tolist()),
                    'records': duplicate_records.to_dict('records')
                }
        
        # Add foreign key if specified
        if foreign_key:
            check_columns.append(foreign_key)
            duplicate_mask = df.duplicated(subset=[foreign_key], keep=False)
            duplicate_records = df[duplicate_mask]
            if not duplicate_records.empty:
                duplicate_info['details']['foreign_key'] = {
                    'count': len(duplicate_records) // 2,
                    'values': sorted(duplicate_records[foreign_key].unique().tolist()),
                    'records': duplicate_records.to_dict('records')
                }
        
        # Check for complete duplicate records (all columns)
        all_columns_mask = df.duplicated(keep=False)
        all_columns_dupes = df[all_columns_mask]
        if not all_columns_dupes.empty:
            duplicate_info['details']['complete_records'] = {
                'count': len(all_columns_dupes) // 2,
                'records': all_columns_dupes.to_dict('records')
            }
        
        # Set overall duplicate status
        duplicate_info['count'] = sum(detail.get('count', 0) for detail in duplicate_info['details'].values())
        duplicate_info['has_duplicates'] = duplicate_info['count'] > 0
        
        return duplicate_info

    def _check_null_values(self, df: pd.DataFrame, required_columns: Optional[List[str]] = None) -> Dict[str, Any]:
        """Check for null values in each column"""
        null_details = {}
        columns_to_check = required_columns if required_columns else df.columns
        
        for col in columns_to_check:
            if col in df.columns:
                # Enhanced null check to catch more variations of null values
                null_mask = (
                    df[col].isnull() |
                    (df[col].astype(str).str.strip() == '') |
                    (df[col].astype(str).str.strip().str.lower() == 'none') |
                    (df[col].astype(str).str.strip().str.upper() == 'NULL') |
                    (df[col].astype(str).str.strip() == 'nan')
                )
                null_count = null_mask.sum()
                total_rows = len(df)
                
                # Always include column statistics, even if no nulls found
                null_details[col] = {
                    'count': null_count,
                    'percentage': (null_count / total_rows) * 100 if total_rows > 0 else 0,
                    'total_rows': total_rows,
                    'rows': df[null_mask].to_dict('records')[:100] if null_count > 0 else []  # Limit to 100 rows for display
                }
        
        return {'details': null_details}

    def _check_outliers(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Check for numerical outliers using statistical methods"""
        outliers = {}
        
        # Only analyze numeric columns
        numeric_columns = df.select_dtypes(include=['int64', 'float64']).columns
        
        for col in numeric_columns:
            try:
                # Calculate statistics
                Q1 = df[col].quantile(0.25)
                Q3 = df[col].quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - 1.5 * IQR
                upper_bound = Q3 + 1.5 * IQR
                
                # Find outliers
                outlier_mask = (df[col] < lower_bound) | (df[col] > upper_bound)
                outlier_values = df[outlier_mask][[col]].copy()
                
                if len(outlier_values) > 0:
                    outliers[col] = {
                        'count': len(outlier_values),
                        'values': outlier_values[col].tolist()[:100],  # Limit to 100 examples
                        'bounds': {
                            'lower': float(lower_bound),
                            'upper': float(upper_bound)
                        },
                        'stats': {
                            'q1': float(Q1),
                            'q3': float(Q3),
                            'median': float(df[col].median()),
                            'mean': float(df[col].mean())
                        }
                    }
            except Exception:
                pass
        
        return outliers

    def _check_format_issues(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Check for format inconsistencies"""
        format_issues = {}
        
        # Check date formats
        date_columns = df.select_dtypes(include=['datetime64']).columns
        for col in date_columns:
            invalid_mask = pd.to_datetime(df[col], errors='coerce').isna()
            invalid_dates = df[invalid_mask][col].astype(str).tolist()
            if invalid_dates:
                format_issues[col] = {
                    'invalid_dates': invalid_dates,
                    'count': len(invalid_dates)
                }
        
        return format_issues

    def _check_basic_timeliness(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Simple check for data timeliness"""
        timeliness_issues = {
            'stale_records': 0,
            'newest_record': None,
            'oldest_record': None,
            'total_records': len(df)
        }

        # Common date formats to try
        date_formats = ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y/%m/%d', '%d/%m/%Y', '%m/%d/%Y']
        
        # Check common date columns
        date_columns = [col for col in df.columns if any(term in col.lower() 
                      for term in ['date', 'created', 'updated', 'timestamp'])]

        for col in date_columns:
            try:
                # Try each format until one works
                dates = None
                for fmt in date_formats:
                    try:
                        dates = pd.to_datetime(df[col], format=fmt, errors='raise')
                        break
                    except ValueError:
                        continue
                
                # If no format worked, use ISO format as a last resort
                if dates is None:
                    try:
                        dates = pd.to_datetime(df[col], format='%Y-%m-%d', errors='raise')
                    except ValueError:
                        # If ISO format fails, mark as invalid
                        dates = pd.Series([pd.NaT] * len(df))
                
                if dates.notna().any():
                    current_time = pd.Timestamp.now()
                    # Consider records older than 30 days as stale
                    stale_mask = (current_time - dates) > pd.Timedelta(days=30)
                    stale_count = stale_mask.sum()
                    
                    # Update stale records count if this column has more stale records
                    if stale_count > timeliness_issues['stale_records']:
                        timeliness_issues['stale_records'] = int(stale_count)
                    
                    if dates.notna().any():
                        timeliness_issues['newest_record'] = dates.max().strftime('%Y-%m-%d')
                        timeliness_issues['oldest_record'] = dates.min().strftime('%Y-%m-%d')
                        
                    # Break after finding the first valid date column
                    break
            except Exception as e:
                continue

        return timeliness_issues

    def _check_basic_dates(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Simple check for date format issues"""
        date_issues = {}
        
        # Common date formats to try
        date_formats = ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y/%m/%d', '%d/%m/%Y', '%m/%d/%Y']
        
        # Check common date columns
        date_columns = [col for col in df.columns if any(term in col.lower() 
                      for term in ['date', 'created', 'updated', 'timestamp'])]

        for col in date_columns:
            try:
                # Try each format until one works
                dates = None
                valid_format = None
                for fmt in date_formats:
                    try:
                        dates = pd.to_datetime(df[col], format=fmt, errors='raise')
                        valid_format = fmt
                        break
                    except ValueError:
                        continue
                
                # If no format worked, use ISO format as a last resort
                if dates is None:
                    try:
                        dates = pd.to_datetime(df[col], format='%Y-%m-%d', errors='raise')
                    except ValueError:
                        # If ISO format fails, mark as invalid
                        dates = pd.Series([pd.NaT] * len(df))
                
                invalid_dates = df[dates.isna()][col].astype(str).tolist()
                
                if invalid_dates:
                    date_issues[col] = {
                        'invalid_count': len(invalid_dates),
                        'values': invalid_dates[:5],  # Show only first 5 examples
                        'expected_format': valid_format if valid_format else 'unknown'
                    }
            except:
                continue

        return date_issues

    def _ensure_serializable(self, data):
        """Convert any non-serializable values to strings"""
        if isinstance(data, dict):
            return {k: self._ensure_serializable(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._ensure_serializable(item) for item in data]
        elif isinstance(data, (pd.Timestamp, datetime, pd.Series)):
            return str(data)
        elif pd.isna(data):
            return None
        elif isinstance(data, float) and np.isnan(data):
            return None
        elif hasattr(data, 'dtype') and np.issubdtype(data.dtype, np.integer):
            return int(data)
        elif hasattr(data, 'dtype') and np.issubdtype(data.dtype, np.floating):
            return float(data)
        return data

    def _is_valid_data_type(self, value, column):
        """Check if value matches expected data type for column"""
        try:
            if 'date' in column.lower() or 'time' in column.lower():
                pd.to_datetime(value)
            elif 'amount' in column.lower() or 'price' in column.lower():
                float(value)
            elif 'count' in column.lower() or 'quantity' in column.lower():
                int(value)
            return True
        except (ValueError, TypeError):
            return False

    def _check_data_pattern_consistency(self, results, column):
        """Check if data patterns are consistent across the dataset"""
        values = results.get('null_values', {}).get('details', {}).get(column, {}).get('values', [])
        if not values:
            return True
        patterns = [self._get_value_pattern(str(v)) for v in values if v is not None]
        return len(set(patterns)) <= 1

    def _get_value_pattern(self, value):
        """Extract pattern from value (e.g., date format, number format)"""
        if not value:
            return 'empty'
        if value.replace('.', '').isdigit():
            return 'numeric'
        try:
            pd.to_datetime(value)
            return 'date'
        except:
            return 'string'

    def _is_fuzzy_duplicate(self, record):
        """Check for fuzzy duplicates using string similarity"""
        for key in record:
            if isinstance(record[key], str) and len(record[key]) > 3:
                # Simple character-based similarity check
                similar_chars = sum(1 for c in record[key] if c.isalnum())
                if similar_chars / len(record[key]) > 0.8:
                    return True
        return False

    def _validate_business_rules(self, results, column, rules):
        """Validate data against business rules"""
        if not rules:
            return True
        values = results.get('null_values', {}).get('details', {}).get(column, {}).get('values', [])
        if 'required_columns' in rules and column in rules['required_columns']:
            return not any(v is None or str(v).strip() == '' for v in values)
        return True

    def _validate_metadata(self, results, column):
        """Validate data against metadata constraints"""
        values = results.get('null_values', {}).get('details', {}).get(column, {}).get('values', [])
        if not values:
            return True
        # Check for consistent data types
        value_types = set(type(v) for v in values if v is not None)
        return len(value_types) <= 1

    @lru_cache(maxsize=128)
    def _validate_table_cached(self, table_name, schema):
        """Cached version of validate_table with TTL for improved performance"""
        cache_key = f"{schema}.{table_name}"
        current_time = time()
        
        # Check if result is cached and not expired
        if cache_key in self._cache:
            if current_time - self._cache_timestamps[cache_key] < self._cache_ttl:
                return self._cache[cache_key]
            else:
                # Remove expired cache entry
                del self._cache[cache_key]
                del self._cache_timestamps[cache_key]
        
        # Get fresh result and cache it
        result = self.validate_table(table_name, schema)
        self._cache[cache_key] = result
        self._cache_timestamps[cache_key] = current_time
        return result

    def validate_schema(self, schema, batch_size=10):
        """Validate all tables in a schema with overview metrics"""
        try:
            start_time = time()
            query = f"""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = '{schema}'
                AND table_type = 'BASE TABLE'
            """
            
            with self.db.get_connection() as conn:
                if self.db.db_type == DatabaseType.POSTGRES:
                    tables = [row[0] for row in conn.run(query)]
                else:  # Snowflake
                    cursor = conn.cursor()
                    cursor.execute(query)
                    tables = [row[0] for row in cursor.fetchall()]
                
                if not tables:
                    return {
                        'error': f'No tables found in schema {schema}',
                        'overall_score': 0,
                        'total_rows': 0,
                        'failed_rows': 0,
                        'processing_info': {
                            'total_tables': 0,
                            'processed_tables': 0,
                            'skipped_tables': 0,
                            'processing_time': 0
                        }
                    }
                
                # Initialize metrics
                total_rows = 0
                total_failed_rows = 0
                processed_tables = 0
                skipped_tables = 0
                failed_tables = []
                
                metrics = {
                    'completeness': {'score': 0, 'total_nulls': 0, 'total_values': 0},
                    'timeliness': {'score': 0, 'stale_records': 0, 'total_records': 0},
                    'accuracy': {'score': 0, 'type_mismatches': 0, 'total_checked': 0},
                    'consistency': {'score': 0, 'pattern_violations': 0, 'total_patterns': 0},
                    'uniqueness': {'score': 0, 'duplicates': 0, 'total_records': 0},
                    'validity': {'score': 0, 'format_violations': 0, 'total_checked': 0}
                }
                
                # Process tables in batches
                for i in range(0, len(tables), batch_size):
                    batch = tables[i:i + batch_size]
                    max_workers = min(len(batch), os.cpu_count() * 2)
                    
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        future_to_table = {}
                        for table in batch:
                            future = executor.submit(self._validate_table_cached, table, schema)
                            future_to_table[future] = table
                        
                        for future in as_completed(future_to_table, timeout=1200):  # Increased timeout to 20 minutes
                            table = future_to_table[future]
                            try:
                                results = future.result()
                                
                                if 'error' in results or results['row_count'] == 0:
                                    skipped_tables += 1
                                    failed_tables.append({'table': table, 'error': results.get('error', 'No data')})
                                    continue
                                
                                processed_tables += 1
                                rows = results['row_count']
                                total_rows += rows
                                
                                # Calculate metrics for overview page
                                self._calculate_overview_metrics(results, metrics, rows)
                                
                            except Exception as e:
                                skipped_tables += 1
                                failed_tables.append({'table': table, 'error': str(e)})
                                continue
                
                # Calculate final scores
                self._calculate_final_scores(metrics)
                
                processing_time = time() - start_time
                
                return {
                    'overall_score': sum(metric['score'] for metric in metrics.values()) / len(metrics),
                    'total_rows': total_rows,
                    'failed_rows': total_failed_rows,
                    'metrics': metrics,
                    'processing_info': {
                        'total_tables': len(tables),
                        'processed_tables': processed_tables,
                        'skipped_tables': skipped_tables,
                        'failed_tables': failed_tables,
                        'processing_time': processing_time
                    }
                }
                
        except Exception as e:
            print(f"Error during schema validation: {str(e)}")
            return {
                'error': str(e),
                'overall_score': 0,
                'total_rows': 0,
                'failed_rows': 0,
                'processing_info': {
                    'total_tables': len(tables) if 'tables' in locals() else 0,
                    'processed_tables': processed_tables if 'processed_tables' in locals() else 0,
                    'skipped_tables': skipped_tables if 'skipped_tables' in locals() else 0,
                    'failed_tables': failed_tables if 'failed_tables' in locals() else [],
                    'processing_time': time() - start_time if 'start_time' in locals() else 0
                }
            }

    def _calculate_overview_metrics(self, results, metrics, rows):
        """Calculate metrics for overview page"""
        # Update completeness metrics
        null_values = results.get('null_values', {})
        if 'details' in null_values:
            total_nulls = sum(detail.get('count', 0) for detail in null_values['details'].values())
            metrics['completeness']['total_nulls'] += total_nulls
            metrics['completeness']['total_values'] += rows * len(null_values['details'])
        
        # Update uniqueness metrics
        duplicates = results.get('duplicates', {})
        metrics['uniqueness']['duplicates'] += duplicates.get('count', 0)
        metrics['uniqueness']['total_records'] += rows
        
        # Update validity metrics
        format_issues = results.get('format_issues', {})
        metrics['validity']['format_violations'] += sum(issue.get('count', 0) for issue in format_issues.values())
        metrics['validity']['total_checked'] += rows
        
        # Update consistency metrics
        # Assuming pattern violations are tracked in format_issues
        metrics['consistency']['pattern_violations'] += len(format_issues)
        metrics['consistency']['total_patterns'] += rows
        
        # Update timeliness metrics
        timeliness = results.get('timeliness', {})
        if timeliness:
            metrics['timeliness']['stale_records'] += timeliness.get('stale_records', 0)
            metrics['timeliness']['total_records'] += rows
            # Calculate table-specific timeliness score
            if timeliness.get('stale_records', 0) > 0:
                table_score = 100 * (1 - timeliness['stale_records'] / rows)
            else:
                table_score = 100
            
            if 'table_scores' not in metrics['timeliness']:
                metrics['timeliness']['table_scores'] = []
            metrics['timeliness']['table_scores'].append(table_score)
            # Update overall timeliness score as weighted average
            metrics['timeliness']['score'] = sum(metrics['timeliness']['table_scores']) / len(metrics['timeliness']['table_scores'])

    def _calculate_final_scores(self, metrics):
        """Calculate final scores for overview metrics"""
        metrics['completeness']['score'] = 100 * (1 - metrics['completeness']['total_nulls'] / max(metrics['completeness']['total_values'], 1))
        metrics['uniqueness']['score'] = 100 * (1 - metrics['uniqueness']['duplicates'] / max(metrics['uniqueness']['total_records'], 1))
        metrics['validity']['score'] = 100 * (1 - metrics['validity']['format_violations'] / max(metrics['validity']['total_checked'], 1))
        metrics['consistency']['score'] = 100 * (1 - metrics['consistency']['pattern_violations'] / max(metrics['consistency']['total_patterns'], 1))
        # Calculate timeliness score based on actual metrics
        if 'table_scores' in metrics['timeliness'] and metrics['timeliness']['table_scores']:
            # Score is already calculated in validate_schema using weighted average
            pass
        else:
            metrics['timeliness']['score'] = 0
        # Set default score for accuracy as it's not currently implemented
        metrics['accuracy']['score'] = 100

    def _validate_custom_query(self, query):
        """
        Validate data from a custom query
        Args:
            query: SQL query to execute
        """
        with self.db.get_connection() as conn:
            try:
                if self.db.db_type == DatabaseType.POSTGRES:
                    results = conn.run(query)
                    columns = [desc['name'] for desc in conn.columns]
                else:  # Snowflake
                    cursor = conn.cursor()
                    cursor.execute(query)
                    results = cursor.fetchall()
                    columns = [desc[0] for desc in cursor.description]

                if not results:
                    return {
                        'error': 'Query returned no results',
                        'row_count': 0,
                        'duplicates': {'count': 0, 'details': []},
                        'null_values': {'details': {}},
                        'date_issues': {}
                    }

                if not columns:
                    return {
                        'error': 'Query returned no columns',
                        'row_count': 0,
                        'duplicates': {'count': 0, 'details': []},
                        'null_values': {'details': {}},
                        'date_issues': {}
                    }

                df = pd.DataFrame(results, columns=columns)
                total_rows = len(df)

                validation_results = {
                    'duplicates': self._check_duplicates(
                        df, 
                        key_column=None,
                        foreign_key=None
                    ),
                    'null_values': self._check_null_values(df),
                    'date_issues': self._check_basic_dates(df),
                    'anomalies': self._check_outliers(df),
                    'timeliness': self._check_basic_timeliness(df),  # Remove table-specific rules for custom queries
                    'row_count': total_rows,
                    'preview_limit': 100  # Only limit the preview of detailed results
                }
                
                # Only limit the preview records while keeping full counts
                if 'duplicates' in validation_results and 'details' in validation_results['duplicates']:
                    for key in validation_results['duplicates']['details']:
                        if 'records' in validation_results['duplicates']['details'][key]:
                            full_count = len(validation_results['duplicates']['details'][key]['records'])
                            validation_results['duplicates']['details'][key]['records'] = \
                                validation_results['duplicates']['details'][key]['records'][:100]
                            validation_results['duplicates']['details'][key]['total_records'] = full_count

                if 'null_values' in validation_results and 'details' in validation_results['null_values']:
                    for col in validation_results['null_values']['details']:
                        if 'rows' in validation_results['null_values']['details'][col]:
                            full_count = len(validation_results['null_values']['details'][col]['rows'])
                            validation_results['null_values']['details'][col]['rows'] = \
                                validation_results['null_values']['details'][col]['rows'][:100]
                            validation_results['null_values']['details'][col]['total_rows'] = full_count

                return self._ensure_serializable(validation_results)
            except Exception as e:
                error_msg = str(e)
                print(f"Error during custom query validation: {error_msg}")
                return {
                    'error': f"Query validation failed: {error_msg}",
                    'row_count': 0,
                    'duplicates': {'count': 0, 'details': []},
                    'null_values': {'details': {}},
                    'date_issues': {},
                    'row_count': 0
                }

    def validate_schema(self, schema: str) -> Dict[str, Any]:
        """Validate a database schema and its tables"""
        try:
            # Get all tables in the schema
            tables = self.db.get_tables(schema)
            if not tables:
                return {
                    'error': f'No tables found in schema {schema}',
                    'tables_count': 0,
                    'validation_results': {}
                }

            validation_results = {}
            total_tables = len(tables)
            processed_tables = 0

            # Use ThreadPoolExecutor for parallel processing
            with ThreadPoolExecutor(max_workers=4) as executor:
                # Create a dictionary to store futures
                future_to_table = {}
                
                # Submit validation tasks for each table
                for table in tables:
                    future = executor.submit(self.validate_table, table, schema)
                    future_to_table[future] = table

                # Process completed validations
                for future in as_completed(future_to_table):
                    table = future_to_table[future]
                    try:
                        result = future.result()
                        validation_results[table] = result
                        processed_tables += 1
                    except Exception as e:
                        validation_results[table] = {
                            'error': str(e),
                            'row_count': 0,
                            'null_values': {'details': {}}
                        }

            return {
                'schema': schema,
                'tables_count': total_tables,
                'processed_tables': processed_tables,
                'validation_results': validation_results
            }

        except Exception as e:
            return {
                'error': f'Schema validation failed: {str(e)}',
                'tables_count': 0,
                'validation_results': {}
            }