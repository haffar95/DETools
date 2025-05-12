# Data Quality Tools

A powerful web-based tool for validating data quality across PostgreSQL and Snowflake databases. This tool provides comprehensive data validation capabilities through both standard validation modes and custom query validations.

## Features

- **Multi-Database Support**
  - PostgreSQL database integration
  - Snowflake database integration
  - Easy database switching through UI

- **Validation Modes**
  - Standard Validation: Pre-built validation rules for common data quality checks
  - Query Validation: Custom SQL query-based validation
  - Date-range based validation support

- **User Interface**
  - Modern, responsive web interface
  - Interactive dashboard for validation results
  - Real-time database connection status
  - Schema and table selection dropdowns

## Prerequisites

- Python 3.8 or higher
- PostgreSQL/Snowflake database access
- pip (Python package manager)

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

## Configuration

1. Database Configuration:
   - Create `database_configs.json` in the root directory
   - Add your database configurations:
   ```json
   {
     "databases": [
       {
         "name": "your_database_name",
         "type": "postgres",
         "host": "your_host",
         "port": "5432",
         "database": "db_name",
         "user": "username",
         "password": "your_password"
       }
     ]
   }
   ```
   Or Just use the UI to add your database configurations.

2. Application Configuration:
   - Update `config/config.py` with your settings

## Project Structure

```
├── app/
│   ├── database/         # Database connection handling
│   │   ├── __init__.py
│   │   └── db_connector.py
│   ├── models/          # Data models
│   │   └── __init__.py
│   ├── static/          # Static assets
│   │   ├── css/
│   │   ├── images/
│   │   └── js/
│   ├── templates/       # HTML templates
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── database_config.html
│   │   └── overview.html
│   └── validation/      # Validation logic
│       ├── __init__.py
│       └── validators.py
├── config/             # Configuration files
│   └── config.py
├── requirements.txt    # Python dependencies
└── run.py             # Application entry point
```

## Running the Application

1. Start the Flask server:
   ```bash
   python run.py
   ```

2. Access the web interface:
   - Open your browser and navigate to `http://localhost:5000`
   - Select your database from the dropdown menu
   - Choose validation mode (Standard/Query)
   - Configure validation parameters
   - Run validation checks

## Dependencies

- Flask==2.0.1
- Werkzeug==3.0.1
- Jinja2>=3.0.0
- pg8000==1.29.1
- numpy>=1.24.0
- pandas>=2.0.0

## Features in Detail

### Standard Validation
- Schema and table selection
- Primary/Unique key validation
- Date range filtering
- Null value analysis
- Duplicate record detection
- Data type consistency checks

### Query Validation
- Custom SQL query execution
- Query result validation
- Performance optimization suggestions

### Database Management
- Multiple database configuration support
- Real-time connection status
- Easy database switching
- Connection error handling

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.