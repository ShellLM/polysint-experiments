Here's a complete Alembic-based migration strategy that replaces the manual `init_db()` approach with proper, versioned, reversible migrations:

## 1. Project Structure
```
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
├── models.py          # Schema definitions for Alembic
├── db.py              # Updated to run migrations
└── start.py           # Calls migration at startup
```

## 2. New Files

### `models.py`
Schema definitions Alembic uses for autogeneration. These mirror the sqlite3 tables but are only used by Alembic:

```python
"""
SQLAlchemy schema definitions for Alembic migrations.
Alembic uses this metadata for autogenerate — NOT imported by the application's db.py.
"""
from sqlalchemy import MetaData, Table, Column, String, Text, Float, DateTime, Integer

metadata = MetaData()

markets = Table(
    "markets",
    metadata,
    Column("id", Text, primary_key=True),
    Column("question", Text),
    Column("outcomes", Text),
    Column("volume", Float),
    Column("created_at", Text),
    Column("clob_token_id", Text),
)

snapshots = Table(
    "snapshots",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("market_id", Text),
    Column("timestamp", DateTime),
    Column("prices", Text),
    Column("volume", Float),
)

watch_list = Table(
    "watch_list",
    metadata,
    Column("address", Text, primary_key=True),
    Column("label", Text),
    Column("added_at", DateTime),
)
```

### `alembic.ini`
```ini
[alembic]
script_location = alembic
sqlalchemy.url = sqlite:///polysint_core.db

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

### `alembic/env.py`
```python
"""
Alembic environment configuration.
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Alembic Config object
config = context.config

# Override sqlalchemy.url with application's DB path
from config import Config
db_path = os.path.abspath(Config.DB_NAME)
config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

# Configure Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import metadata target for 'autogenerate' support
from models import metadata

target_metadata = metadata


def run_migrations_offline():
    """Generate SQL script without a live database connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True  # Required for SQLite ALTER TABLE support
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### `alembic/versions/001_initial_schema.py`
```python
"""initial schema — markets, snapshots, watch_list

Revision ID: 001
Revises:
Create Date: 2025-01-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the complete initial schema."""
    op.create_table(
        "markets",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("question", sa.Text),
        sa.Column("outcomes", sa.Text),
        sa.Column("volume", sa.Float),
        sa.Column("created_at", sa.Text),
        sa.Column("clob_token_id", sa.Text),
    )

    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Text),
        sa.Column("timestamp", sa.DateTime),
        sa.Column("prices", sa.Text),
        sa.Column("volume", sa.Float),
    )

    op.create_table(
        "watch_list",
        sa.Column("address", sa.Text, primary_key=True),
        sa.Column("label", sa.Text),
        sa.Column("added_at", sa.DateTime),
    )


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table("watch_list")
    op.drop_table("snapshots")
    op.drop_table("markets")
```

## 3. Modified Files

### `db.py`
```python
"""
Database connection — schema is managed exclusively by Alembic migrations.
"""
import sqlite3
from config import Config
from logger import get_logger

log = get_logger("Database")


def get_db():
    """Return a sqlite3 connection with WAL journaling and Row factory."""
    try:
        conn = sqlite3.connect(Config.DB_NAME)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn
    except Exception as e:
        log.critical(f"Database connection failed: {e}")
        raise


def run_migrations():
    """
    Programmatically run all pending Alembic migrations.
    Called once at application startup before any queries.
    """
    from alembic.config import Config as AlembicConfig
    from alembic import command

    alembic_cfg = AlembicConfig("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    log.info("Database migrations applied successfully.")
```

### `start.py`
Add migration check at the beginning of `start_engine()`:

```python
def start_engine():
    print("🚀 Starting PolySINT Engine...")
    
    # ── Step 0: Migrations ────────────────────────────────────────────────
    print(" -> Running database migrations...")
    try:
        from db import run_migrations
        run_migrations()
        print("    ✓ Schema is up to date.")
    except Exception as e:
        print(f"    ✗ Migration failed: {e}")
        log.critical(f"Migration failed: {e}")
        sys.exit(1)
    
    # ... rest of start_engine unchanged ...
```

## 4. Installation & Setup

```bash
# Install Alembic
pip install alembic
```

### For New Installations
```bash
python start.py
# Alembic creates the database, runs all migrations, then launches workers
```

### For Existing Installations
Mark the initial migration as already applied:
```bash
alembic stamp head
```

## 5. Workflow: Making Schema Changes

**1. Edit `models.py`** with your change:
```python
markets = Table(
    "markets",
    metadata,
    # ... existing columns ...
    Column("category", Text),           # new column
    Column("source", Text, default="gamma"),  # new column
)
```

**2. Generate the migration:**
```bash
alembic revision --autogenerate -m "add category and source to markets"
```

**3. Review the generated file** in `alembic/versions/` — verify it captures your intent.

**4. Apply it:**
```bash
alembic upgrade head
```

The next `python start.py` run will also apply it automatically.

## 6. Useful Commands

```bash
alembic current          # Show current revision
alembic history          # Show full revision chain
alembic upgrade head     # Apply all pending
alembic downgrade -1     # Roll back one step
alembic upgrade +2       # Apply next two
alembic revision --sql -m "preview" --rev-id preview1  # Generate SQL without applying
```

## Key Benefits of This Approach:

1. **Minimal Changes**: Existing application code continues to work unchanged
2. **Version Control**: Database schema changes are tracked in version-controlled migration files
3. **Rollback Capability**: Each migration has an upgrade and downgrade path
4. **Auto-generation**: Can auto-generate migrations from model changes
5. **Production Ready**: Handles both development and production databases
6. **Backward Compatibility**: Works with existing sqlite3 connections
