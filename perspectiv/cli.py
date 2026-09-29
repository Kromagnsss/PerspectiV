from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import MetaData, create_engine, inspect, select, text

from .database import init_db
from .settings import DATABASE_URL


def migrate_sqlite(source: Path, target_url: str) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    source_engine = create_engine(f"sqlite:///{source.resolve()}")
    target_engine = create_engine(target_url)
    source_meta, target_meta = MetaData(), MetaData()
    source_meta.reflect(source_engine)
    target_meta.reflect(target_engine)
    order = [
        "users",
        "user_grid_preferences",
        "projects",
        "budgets",
        "budget_lines",
        "tasks",
        "task_assignments",
        "task_dependencies",
        "time_entries",
        "planned_time_entries",
    ]
    with source_engine.connect() as source_connection, target_engine.begin() as target_connection:
        for table_name in order:
            if table_name not in source_meta.tables or table_name not in target_meta.tables:
                continue
            source_table = source_meta.tables[table_name]
            target_table = target_meta.tables[table_name]
            rows = [dict(row._mapping) for row in source_connection.execute(select(source_table))]
            allowed = {column.name for column in target_table.columns}
            cleaned = [{key: value for key, value in row.items() if key in allowed} for row in rows]
            if cleaned:
                target_connection.execute(target_table.insert(), cleaned)
            if target_engine.dialect.name == "postgresql" and "id" in allowed:
                target_connection.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                        "COALESCE((SELECT MAX(id) FROM \"" + table_name + "\"), 1), true)"
                    ),
                    {"table_name": table_name},
                )
    print(f"Migration terminée depuis {source} vers {target_url.split(':', 1)[0]}.")


def backup_postgres(output: Path) -> None:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("La commande backup nécessite PostgreSQL.")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pg_dump", "--format=custom", "--file", str(output), DATABASE_URL], check=True)
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser(prog="perspectiv")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    migrate = subparsers.add_parser("migrate-sqlite")
    migrate.add_argument("source", type=Path)
    migrate.add_argument("--target", default=DATABASE_URL)
    backup = subparsers.add_parser("backup")
    backup.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "init-db":
        init_db()
        print("Base PerspectiV initialisée.")
    elif args.command == "migrate-sqlite":
        migrate_sqlite(args.source, args.target)
    elif args.command == "backup":
        backup_postgres(args.output)


if __name__ == "__main__":
    main()
