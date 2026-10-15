import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("AGENTFLOW_DATABASE_URL", f"sqlite:///{Path(__file__).resolve().parents[1] / 'agentflow.db'}")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def migrate_additive_schema():
    """Small additive SQLite migration kept local to the single-user first release."""
    inspector = inspect(engine)
    if "tasks" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("tasks")}
        if "origin" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE tasks ADD COLUMN origin VARCHAR(20) NOT NULL DEFAULT 'task'"))
    inspector = inspect(engine)
    if "evaluation_runs" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("evaluation_runs")}
        if "model_name" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE evaluation_runs ADD COLUMN model_name VARCHAR(240) NOT NULL DEFAULT '演示执行器'"))
    inspector = inspect(engine)
    if "runs" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("runs")}
        if "workflow_id" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE runs ADD COLUMN workflow_id VARCHAR(40)"))
    inspector = inspect(engine)
    if "workflows" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("workflows")}
        with engine.begin() as connection:
            if "is_default" not in columns:
                connection.execute(text("ALTER TABLE workflows ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0"))
            if "is_archived" not in columns:
                connection.execute(text("ALTER TABLE workflows ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0"))
    inspector = inspect(engine)
    if "model_provider_configs" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("model_provider_configs")}
        if "is_default" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE model_provider_configs ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0"))
        unique_sets = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("model_provider_configs")}
        if ("scope_id", "provider_id") not in unique_sets:
            with engine.begin() as connection:
                connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_model_config_scope_provider ON model_provider_configs (scope_id, provider_id)"))
