# DETools — Data Quality & Validation Platform

A self-hosted, browser-based **Data Quality (DQ) platform** that connects to **PostgreSQL** and **Snowflake** databases, runs automated validation checks, and surfaces results through a modern dashboard. Designed as a white-label internal tooling solution for data engineering and analytics teams.

---

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [Technology Stack](#technology-stack)
4. [Architecture](#architecture)
5. [Prerequisites](#prerequisites)
6. [Installation](#installation)
7. [Configuration](#configuration)
8. [Running the Application](#running-the-application)
9. [User Management](#user-management)
10. [Connection Management](#connection-management)
11. [Data Quality Checks](#data-quality-checks)
12. [Validation Modes](#validation-modes)
13. [API Reference](#api-reference)
14. [Security](#security)
15. [Project Structure](#project-structure)
16. [Contributing](#contributing)

---

## Overview

DETools gives data teams a centralised place to:

- **Browse** all connected databases through an interactive sidebar tree (databases ? schemas ? tables ? columns, routines, sequences)
- **Scan** entire databases and receive DQ scores across 6 dimensions in seconds
- **Validate** individual tables with a point-and-click UI — no SQL required
- **Write custom SQL** queries and run the same validation suite against the result set
- **Configure rule-based checks** (row count thresholds, null %, regex patterns, freshness, accepted values, custom SQL) and track results over time
- **Manage users and connection access** from a built-in admin panel

All results are displayed inline in the browser with colour-coded scoring, sortable tables, and drill-down detail panels.

---

## Key Features

### ?? Multi-Database Connectivity
- **PostgreSQL** — direct TCP, SSL, and SSH tunnel (bastion host) support
- **Snowflake** — native connector with account/warehouse/role/schema configuration
- Multiple simultaneous connection profiles; switch globally with one click in the navbar

### ?? Interactive Database Tree
- Collapsible sidebar explorer: Connections ? Databases ? Schemas ? Tables / Views / Routines / Sequences
- Flash icon in the navbar activates a connection for the whole session
- Column-level detail: data type, nullable flag, default value

### ?? Overview & DQ Scoring
- Full database scan producing per-table and aggregate scores
- **6 DQ dimensions** scored as percentages (0–100 %):

| Dimension | What is measured |
|---|---|
| Completeness | Non-null cell rate across all columns |
| Uniqueness | Distinct value rate across key columns |
| Freshness | Recency of timestamp columns |
| Validity | Format / pattern compliance |
| Accuracy | Schema-level structural accuracy |
| Consistency | Cross-table conformance rate |

- Circular gauge visualisation for each dimension
- Sortable table with per-table scores for all 6 dimensions

### ? Standard Table Validation
- Point-and-click: pick Database ? Schema ? Table
- Optional key column, foreign key column, and date range filter
- Returns:
  - Null value analysis per column (count, %, sample rows)
  - Duplicate detection (full-row and key-column duplicates)
  - Format issue detection (email, phone, date patterns)
  - Statistical outlier detection (IQR method on numeric columns)
  - Timeliness / freshness check on timestamp columns

### ??? Query Mode Validation
- Write any `SELECT` or `WITH … SELECT` query in the built-in editor
- The same validation suite runs on the query result set — identical output format to Standard mode
- Only read-only operations allowed; `INSERT`, `UPDATE`, `DELETE`, `DROP`, etc. are blocked at the API level

### ?? Rule-Based Checks Engine
Pre-defined check types (configurable via UI, stored in SQLite):

| Check | Level | DQ Dimension |
|---|---|---|
| Row Count (max) | Table | Completeness |
| Row Count (min expected) | Table | Completeness |
| Freshness (hours since latest record) | Table | Freshness |
| Null % | Column | Completeness |
| Null Count | Column | Completeness |
| Unique % | Column | Uniqueness |
| Accepted Values | Column | Validity |
| Regex Pattern | Column | Validity |
| Minimum Value | Column | Accuracy |
| Maximum Value | Column | Accuracy |
| Minimum Text Length | Column | Validity |
| Maximum Text Length | Column | Validity |
| Custom SQL | Table / Column | Consistency |

Each check supports **warning / error / fatal** severity thresholds.

### ?? User & Access Management
- Username + bcrypt-hashed password authentication
- Role-based access: **Admin** and **standard user**
- Per-user connection allow-list: admins grant or revoke access to specific database connections per user
- Session-scoped connection isolation

### ??? Security
- Passwords hashed with bcrypt (Werkzeug)
- SQL injection prevention: parameterised queries throughout; query mode blocks write operations
- `database_configs.json` and `users.json` are gitignored — credentials never committed
- CORS enabled via Flask-Cors
- `MAX_CONTENT_LENGTH` = 50 MB to prevent oversized payloads
- Admin-only routes decorated with `@admin_required`

---

## Technology Stack

### Backend

| Component | Technology |
|---|---|
| Web framework | Flask 2.0.1 |
| WSGI toolkit | Werkzeug 2.0.1 |
| Templating | Jinja2 3.1.5 |
| PostgreSQL driver | pg8000 1.29.1, psycopg2-binary 2.9.10 |
| Snowflake driver | snowflake-connector-python 3.13.2 |
| ORM / SQL toolkit | SQLAlchemy 2.0.37 |
| Data processing | pandas 2.2.3, NumPy 2.2.1 |
| SSH tunnelling | sshtunnel 0.4.0 + paramiko 2.12.0 |
| Auth / security | bcrypt 4.3.0, PyJWT 2.10.1, cryptography 44.0.0 |
| Check result store | SQLite (via Python `sqlite3`) |
| Environment | python-dotenv 1.0.1 |
| Testing | pytest 8.3.5, pytest-mock 3.14.0 |

### Frontend

| Component | Technology |
|---|---|
| CSS framework | Bootstrap 5.3.3 (CDN) |
| Icons | Bootstrap Icons 1.11.3 (CDN) |
| JavaScript | Vanilla ES6 + jQuery 3.7.1 |
| Select dropdowns | Select2 (CDN) |
| Charts / gauges | Custom CSS arc gauges |

---

## Architecture

```
+-----------------------------------------------------------------+
¦                        Browser (User)                           ¦
¦   overview.js  ¦  validation.js  ¦  treeview.js  ¦  main.js     ¦
+-----------------------------------------------------------------+
                            ¦ HTTP / JSON
+---------------------------?-------------------------------------+
¦                     Flask (run.py)                              ¦
¦                                                                 ¦
¦  Pages:  /overview  /dashboard  /database-config  /admin        ¦
¦  API:    /api/validate  /api/validate-query  /api/tree/*        ¦
¦          /api/overview-scan  /api/activate-conn  /api/checks/*  ¦
+-----------------------------------------------------------------+
       ¦                          ¦
+------?------+           +-------?------+
¦  validators ¦           ¦ db_connector ¦
¦  (DQ logic) ¦           ¦ (pg8000 /    ¦
¦             ¦           ¦  Snowflake / ¦
¦             ¦           ¦  SSH tunnel) ¦
+-------------+           +--------------+
       ¦                          ¦
+------?------+           +-------?------+
¦ checks/     ¦           ¦  PostgreSQL  ¦
¦ engine.py   ¦           ¦  Snowflake   ¦
¦ catalog.py  ¦           +--------------+
¦ store.py    ¦
+-------------+
  (SQLite: data/detools.db)
```

---

## Prerequisites

- **Python 3.10+** (3.12 recommended)
- **pip** (bundled with Python)
- Access to at least one:
  - PostgreSQL 12+ instance (direct, SSL, or via SSH bastion)
  - Snowflake account
- Git

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/haffar95/DETools.git
cd DETools
```

### 2. Create a virtual environment

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell)**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create the credentials files

These files are gitignored and must be created manually.

**`database_configs.json`** — list of database connection profiles:

```json
[
  {
    "name": "my-postgres",
    "type": "postgres",
    "host": "db.example.com",
    "port": 5432,
    "user": "myuser",
    "password": "mypassword",
    "database": "mydb",
    "ssh_host": null,
    "ssh_user": null,
    "ssh_key_path": null,
    "allowed_users": ["admin"]
  }
]
```

For a **Snowflake** connection:

```json
[
  {
    "name": "my-snowflake",
    "type": "snowflake",
    "account": "xy12345.us-east-1",
    "user": "myuser",
    "password": "mypassword",
    "warehouse": "COMPUTE_WH",
    "database": "MY_DB",
    "schema": "PUBLIC",
    "role": "SYSADMIN",
    "allowed_users": ["admin"]
  }
]
```

**`users.json`** is auto-created on first run with the default admin account. Change the password immediately after first login.

---

## Configuration

Edit `config/config.py`:

```python
class Config:
    SECRET_KEY = "replace-with-a-long-random-string"
    DEBUG = False   # True for development only
```

The app listens on `0.0.0.0:5001` by default (configurable at the bottom of `run.py`).

---

## Running the Application

```bash
python run.py
```

Open your browser at `http://localhost:5001` (or the server IP if hosted remotely).

### Default credentials

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Admin |

> **Change the default password immediately** via the Admin panel after first login.

---

## User Management

Accessed at `/admin` (admin users only).

- **Create user** — set username, password, and optionally grant admin rights
- **Delete user** — remove any account except your own
- **Manage connections** — grant or revoke per-user access to specific connection profiles

Standard users can only see and use connections explicitly granted to them by an admin.

---

## Connection Management

Accessed at `/database-config`.

### PostgreSQL fields

| Field | Description |
|---|---|
| Host | Server hostname or IP |
| Port | Default `5432` |
| User / Password | Database credentials |
| Database | Default database name |
| SSH Host | Bastion host (optional) |
| SSH User | SSH login user (optional) |
| SSH Key Path | Absolute path to private key file (optional) |

### Snowflake fields

| Field | Description |
|---|---|
| Account | Account identifier (e.g. `xy12345.us-east-1`) |
| User / Password | Snowflake credentials |
| Warehouse | Virtual warehouse name |
| Database | Default database |
| Schema | Default schema |
| Role | Snowflake role |

Connections are activated globally per session by clicking the **? flash icon** next to a connection in the sidebar tree.

---

## Data Quality Checks

Navigate to a table in the sidebar ? open the **Checks** panel.

1. Select a **check type** from the catalog
2. Set **warning / error / fatal** thresholds (leave blank to skip a severity level)
3. Save — stored in `data/detools.db`
4. Run on demand; results are colour-coded by severity

### Severity levels

| Level | Colour | Meaning |
|---|---|---|
| `pass` | Green | Within all thresholds |
| `warning` | Amber | First threshold breached |
| `error` | Red | Second threshold breached |
| `fatal` | Dark red | Third threshold breached |

---

## Validation Modes

### Standard Mode
1. Go to **Validate** in the top navbar
2. Select Database ? Schema ? Table
3. Optionally set Key Column, Foreign Key Column, and Date Range
4. Click **Run Validation**

### Query Mode
1. Go to **Validate** ? switch to the **Query** tab
2. Select the target database
3. Write a `SELECT` or `WITH … SELECT` statement
4. Click **Validate Query**

Both modes run the same DQ engine and produce identical output sections:

- **Null Analysis** — per-column null counts and percentages with sample rows
- **Duplicate Detection** — full-row duplicates and key-column duplicates
- **Format Issues** — pattern validation for emails, phones, and date strings
- **Outliers** — IQR-based anomaly detection on numeric columns
- **Timeliness** — freshness assessment of timestamp columns

---

## API Reference

All endpoints require an active login session.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/validate` | Standard table validation |
| `POST` | `/api/validate-query` | Custom query validation |
| `POST` | `/api/validate-schema` | Validate all tables in a schema |
| `GET` | `/api/overview-scan` | Full database DQ scan |
| `POST` | `/api/activate-conn` | Set active session connection |
| `GET` | `/api/current-database` | Get current connection info |
| `GET` | `/api/database-configs` | List connections available to the current user |
| `GET` | `/api/tree/connections` | Sidebar tree — connection list |
| `GET` | `/api/tree/databases` | Sidebar tree — databases |
| `GET` | `/api/tree/schemas` | Sidebar tree — schemas |
| `GET` | `/api/tree/tables` | Sidebar tree — tables |
| `GET` | `/api/tree/columns` | Sidebar tree — columns |
| `GET` | `/api/tree/routines` | Sidebar tree — stored procedures/functions |
| `GET` | `/api/tree/sequences` | Sidebar tree — sequences |
| `GET` | `/api/checks/list` | List saved checks for a table |
| `POST` | `/api/checks/save` | Save a check configuration |
| `POST` | `/api/checks/run` | Execute saved checks |
| `POST` | `/api/checks/delete` | Delete a check |

---

## Security

| Control | Implementation |
|---|---|
| Authentication | Session-based login; all routes protected by `@login_required` |
| Authorisation | Admin routes: `@admin_required`; connection routes: `@connection_access_required` |
| Password storage | bcrypt via Werkzeug `generate_password_hash` |
| SQL injection | Parameterised queries; query mode allows only `SELECT`/`WITH` |
| Secrets management | `database_configs.json` and `users.json` in `.gitignore` — never committed |
| Payload limit | 50 MB `MAX_CONTENT_LENGTH` on Flask |
| CORS | Enabled globally; restrict `origins` in production |

---

## Project Structure

```
DETools/
+-- run.py                       # Flask entry point & all route definitions
+-- requirements.txt
+-- config/
¦   +-- config.py                # Flask config (SECRET_KEY, DEBUG, host/port)
+-- app/
¦   +-- auth.py                  # @login_required / @admin_required decorators
¦   +-- database/
¦   ¦   +-- db_connector.py      # DatabaseConnector: pg8000, Snowflake, SSH tunnel
¦   +-- models/
¦   ¦   +-- user.py              # User model (bcrypt, allow-list, JSON persistence)
¦   +-- validation/
¦   ¦   +-- validators.py        # DataValidator: all DQ check logic
¦   +-- checks/
¦   ¦   +-- catalog.py           # CHECK_CATALOG: built-in check type definitions
¦   ¦   +-- engine.py            # Check execution engine
¦   ¦   +-- store.py             # SQLite persistence for check configs & results
¦   +-- static/
¦   ¦   +-- css/
¦   ¦   ¦   +-- overview.css     # Shared DQ page styles (overview + validation)
¦   ¦   ¦   +-- treeview.css     # Sidebar tree styles
¦   ¦   ¦   +-- checks-panel.css
¦   ¦   ¦   +-- app.css
¦   ¦   +-- js/
¦   ¦       +-- overview.js      # Overview page logic
¦   ¦       +-- validation.js    # Validation page logic (standard + query modes)
¦   ¦       +-- treeview.js      # Sidebar tree logic
¦   ¦       +-- checks-panel.js  # Checks panel logic
¦   ¦       +-- main.js          # Global utilities
¦   +-- templates/
¦       +-- base.html            # Base layout (navbar, sidebar, CDN scripts)
¦       +-- overview.html        # DQ overview / scan results page
¦       +-- dashboard.html       # Standard & Query validation page
¦       +-- database_config.html # Connection management page
¦       +-- admin.html           # Admin panel
¦       +-- login.html           # Login page
+-- data/
¦   +-- detools.db               # SQLite: check configs & run history
+-- logs/                        # Application logs
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m "feat: add my feature"`
4. Push to your fork: `git push origin feature/my-feature`
5. Open a Pull Request

**Never commit** `database_configs.json` or `users.json`.

---

*DETools is a white-label internal platform — customise the branding, colour scheme, and check catalog to match your organisation's data quality standards.*
