# Data Quality Validation Tool

A Flask-based web application for validating data quality in PostgreSQL databases. This tool provides comprehensive data validation capabilities including schema validation, custom query validation, and automated data quality checks.

## Features

- **Schema-level Validation**: Validate entire database schemas
- **Table-level Validation**: Perform detailed validation on specific tables
- **Custom Query Validation**: Run validations on custom SQL queries
- **Data Quality Metrics**:
  - Completeness (null value analysis)
  - Uniqueness (duplicate detection)
  - Accuracy (value range and format validation)
  - Timeliness (data freshness checks)
  - Consistency (referential integrity)

## Prerequisites

- Python 3.x
- PostgreSQL database
- pip (Python package installer)

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd Postgres_Validation_Report
   ```

2. Install required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure database connection:
   - Update `config/config.py` with your PostgreSQL database credentials

## Usage

### Starting the Application

```bash
python run.py
```

The application will start on `http://localhost:5001`

### Available Endpoints

#### Web Interface
- `/`: Main dashboard
- `/overview`: Overview page for schema-level validation

#### API Endpoints
- `GET /api/tables/<schema>`: Get all tables in a schema
- `GET /api/columns/<table_name>`: Get columns for a specific table
- `GET /api/validate`: Validate a specific table
- `POST /api/validate-schema`: Validate an entire schema
- `POST /api/validate-query`: Validate results of a custom query

### Validation Modes

1. **Table Validation**
   - Select schema and table
   - Choose validation period (optional)
   - Specify key columns for uniqueness checks
   - View detailed validation results

2. **Schema Validation**
   - Select schema to validate
   - Get comprehensive validation report for all tables

3. **Custom Query Validation**
   - Write custom SELECT queries
   - Get validation results for the query output

## Project Structure

```
├── app/
│   ├── database/         # Database connection handling
│   ├── validation/       # Validation logic
│   ├── static/          # Static files (CSS, JS)
│   └── templates/       # HTML templates
├── config/             # Configuration files
└── run.py             # Application entry point
```

## Validation Rules

The tool includes predefined validation rules for common data types:

- **Dates**: Format validation, future date detection
- **Numeric Values**: Range checks, negative value detection
- **Emails**: Format validation
- **Phone Numbers**: Format validation
- **Custom Rules**: Configurable in `validators.py`

## Security Features

- Query validation to prevent SQL injection
- Restricted to SELECT queries only
- File size limits for data processing
- Configurable rate limiting

## Contributing

Contributions are welcome! Please feel free to submit pull requests.

## License

This project is licensed under the MIT License - see the LICENSE file for details.