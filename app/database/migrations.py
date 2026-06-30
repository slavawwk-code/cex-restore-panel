import logging

from sqlalchemy import Engine, inspect, text

logger = logging.getLogger(__name__)


ACCOUNT_PROXY_COLUMNS = {
    "proxy_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
    "proxy_type": "VARCHAR",
    "proxy_host": "VARCHAR",
    "proxy_port": "INTEGER",
    "proxy_username": "VARCHAR",
    "proxy_password": "VARCHAR",
    "proxy_last_check_at": "DATETIME",
    "proxy_last_check_success": "BOOLEAN",
    "proxy_status": "VARCHAR NOT NULL DEFAULT 'unknown'",
    "proxy_last_checked_at": "DATETIME",
    "proxy_last_success_at": "DATETIME",
    "proxy_last_error": "VARCHAR",
    "proxy_latency_ms": "INTEGER",
    "proxy_detected_type": "VARCHAR",
    "proxy_diagnostics": "TEXT",
}


def run_startup_migrations(engine: Engine) -> None:
    """Apply small additive migrations required by existing installations."""
    inspector = inspect(engine)
    table_name = "advertising_accounts"
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns(table_name)
    }
    missing_columns = {
        name: ddl
        for name, ddl in ACCOUNT_PROXY_COLUMNS.items()
        if name not in existing_columns
    }
    with engine.begin() as connection:
        for name, ddl in missing_columns.items():
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}")
            )
            logger.info("Added database column %s.%s", table_name, name)

        # Preserve status information written by the previous proxy implementation.
        connection.execute(
            text(
                "UPDATE advertising_accounts SET "
                "proxy_status = CASE "
                "WHEN proxy_last_check_success = TRUE THEN 'working' "
                "WHEN proxy_last_check_success = FALSE "
                "AND proxy_last_check_at IS NOT NULL THEN 'failed' "
                "ELSE 'unknown' END "
                "WHERE proxy_status IS NULL OR proxy_status = 'unknown'"
            )
        )
        connection.execute(
            text(
                "UPDATE advertising_accounts SET "
                "proxy_last_checked_at = proxy_last_check_at "
                "WHERE proxy_last_checked_at IS NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE advertising_accounts SET "
                "proxy_last_success_at = proxy_last_check_at "
                "WHERE proxy_last_success_at IS NULL "
                "AND proxy_last_check_success = TRUE"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS proxy_check_history ("
                "id INTEGER PRIMARY KEY, "
                "account_id INTEGER NOT NULL, "
                "checked_at DATETIME NOT NULL, "
                "status VARCHAR NOT NULL, "
                "latency_ms INTEGER, "
                "error TEXT, "
                "FOREIGN KEY(account_id) REFERENCES advertising_accounts(id)"
                ")"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_proxy_check_history_account_id "
                "ON proxy_check_history (account_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_proxy_check_history_checked_at "
                "ON proxy_check_history (checked_at)"
            )
        )
