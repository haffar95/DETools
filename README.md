# Data Quality Tools

A web-based tool for validating data quality across **PostgreSQL** and **Snowflake** databases.  
It supports:

- Standard table validation
- Custom SQL (query) validation
- Schema-level overview
- PostgreSQL connections over **SSL** and (optionally) **SSH tunnels**

This README is focused on getting a new user from zero to a working local setup.

---

## 1. Prerequisites

- **Python** 3.8 or higher
- **pip** (Python package manager)
- Access to at least one:
  - PostgreSQL database (direct or via SSH bastion), or
  - Snowflake database

If you are behind a corporate proxy or need VPN for DB access, make sure it is active before running the app.

---

## 2. Clone the repository

```bash
git clone <repository-url>
cd Postgres_Validation_Report
```

You should now be in the project root (where `run.py` and `requirements.txt` live).

---

## 3. (Recommended) Create and activate a virtual environment

Creating a virtual environment keeps this project’s dependencies isolated.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

After activation, your shell prompt should show `(.venv)` or similar.

---

## 4. Install dependencies

From the project root:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This installs:

- Flask and related web libraries
- PostgreSQL and Snowflake connectors
- Pandas / NumPy
- `sshtunnel` and `paramiko` (for SSH-tunneled Postgres, if needed)

---

## 5. Configure the application

### 5.1 Basic app config

The main app configuration file is `config/config.py`.  
At a minimum, check:

- Secret key (for sessions)
- Any environment-specific flags (dev/prod)

For a simple local run, the defaults should generally work. You can adjust as needed.

### 5.2 Database configurations

Database connections are stored in `database_configs.json` at the project root.

You have **two options** to configure databases:

#### Option A (recommended): Use the web UI

1. Start the app (see section 6).
2. Go to `http://localhost:5000`.
3. Log in.
4. Click **Database Configuration** in the left sidebar.
5. Use the form to add a **new connection**:
   - **Display name** (e.g. `Clarity RDS`, `Snowflake Prod`)
   - **Type**: `Postgres` or `Snowflake`
   - **Host / Port**
   - **Database name**
   - **Username / Password**
   - Snowflake-only fields: `Account`, `Warehouse`, `Role`, `Database`
   - Optional for Postgres over SSH:
     - `SSH host`
     - `SSH username`
     - `SSH password`
     - `SSH port` (usually `22`)

The app will save these details into `database_configs.json` for you.

#### Option B: Edit `database_configs.json` manually

Create or edit `database_configs.json` in the project root and add entries like:

```json
{
  "Example_Postgres_user_20250101000000": {
    "display_name": "Example Postgres",
    "type": "postgres",
    "host": "your-postgres-hostname",
    "port": "5432",
    "user": "db_user",
    "password": "db_password",
    "database": "db_name",
    "creator": "user",
    "created_at": "20250101000000"
  }
}
```

For **Postgres over SSH** (e.g. RDS behind a bastion):

```json
{
  "Example_RDS_admin_20250101000000": {
    "display_name": "Example RDS",
    "type": "postgres",
    "host": "your-rds-endpoint.amazonaws.com",
    "port": "5432",
    "user": "db_user",
    "password": "db_password",
    "database": "postgres",
    "ssh_host": "your-bastion-host",
    "ssh_user": "ssh_username",
    "ssh_password": "ssh_password",
    "ssh_port": "22",
    "creator": "user",
    "created_at": "20250101000000"
  }
}
```

> **Note:** Credentials in this file are sensitive. Treat it like a secrets file and do not commit it to version control.

---

## 6. Run the application locally

From the project root (with the virtual environment activated, if you created one):

```bash
python run.py
```

By default, the app will:

- Start a Flask server on `http://localhost:5000`.
- Show logs in your terminal (including connection and validation errors).

Open your browser and navigate to:

- `http://localhost:5000`

Log in using a user defined in `users.json` (at the project root).  
If none exist or you need a specific admin user, add an entry there following the existing pattern.

---

## 7. Using the app (quick start)

1. **Select or create a database connection**
   - Go to **Database Configuration**.
   - Add a new connection or select an existing one.
   - Once selected, you should see it in the header as the **current database**.

2. **Run a standard table validation**
   - Click **Standard Validation**.
   - Choose a **schema**, then a **table**.
   - (Optional) Choose key/date columns and date range.
   - Click **Validate** and review the results.

3. **Run a query validation**
   - Click **Query Validation**.
   - Paste a `SELECT` or `WITH` query.
   - Click **Validate query** to see data quality issues on that result set.

4. **View schema-level overview**
   - Click **Overview**.
   - Select a schema and click the button to run validation for all tables in that schema.

---

## 8. Troubleshooting

- **Cannot connect to database**
  - Check host, port, database name, username, and password.
  - For SSH connections:
    - Confirm you can SSH from your machine to the `ssh_host` with the given credentials.
    - Make sure outbound SSH (port 22) is allowed.

- **Only `public` schema appears**
  - Your DB user might not have access to other schemas.
  - Ask a DBA to grant:
    - `USAGE` on the relevant schemas
    - `SELECT` on the tables you need.

- **Permission denied errors when validating**
  - Same as above: request the appropriate privileges for your DB user.

- **“Failed to fetch” in the UI**
  - Usually means the backend returned an error.
  - Check the terminal where `python run.py` is running for the detailed error.

---

## 9. Project structure (reference)

```text
├── app/
│   ├── database/         # Database connection handling (Postgres, Snowflake, SSH, SSL)
│   │   ├── __init__.py
│   │   └── db_connector.py
│   ├── models/          # Data models (placeholder)
│   │   └── __init__.py
│   ├── static/          # Static assets
│   │   ├── css/
│   │   ├── images/
│   │   └── js/
│   ├── templates/       # HTML templates (UI)
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── database_config.html
│   │   ├── overview.html
│   │   └── login_base.html
│   └── validation/      # Validation logic
│       ├── __init__.py
│       └── validators.py
├── config/              # Application configuration
│   └── config.py
├── logs/                # Application and validation logs
├── database_configs.json# Database connection definitions (created via UI or manually)
├── users.json           # User accounts
├── requirements.txt     # Python dependencies
└── run.py               # Application entry point
```

---

## 10. License & contributions

- **License**: MIT (see `LICENSE` file if present).
- **Contributions**: Feel free to fork the repository and open pull requests.
