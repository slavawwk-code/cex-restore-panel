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

ACCOUNT_SESSION_COLUMNS = {
    # These columns predate the multi-source session architecture, but are
    # included here so a very old installation can still migrate in one pass.
    "session_connected": "BOOLEAN DEFAULT FALSE",
    "session_connected_at": "DATETIME",
    "session_last_checked_at": "DATETIME",
    "session_user_id": "VARCHAR",
    "session_username": "VARCHAR",
    "api_id": "INTEGER",
    "api_hash": "VARCHAR",
    "session_file_path": "VARCHAR",
    "string_session": "TEXT",
    "auth_status": "VARCHAR NOT NULL DEFAULT 'unverified'",
    "last_auth_error": "TEXT",
    "health_score": "INTEGER NOT NULL DEFAULT 0",
    "last_health_check": "DATETIME",
    "proxy_id": "INTEGER",
    "orchestration_state": "VARCHAR NOT NULL DEFAULT 'CREATED'",
    "orchestration_error": "TEXT",
    "orchestration_updated_at": "DATETIME",
    "autopilot_frozen_until": "DATETIME",
    "autopilot_freeze_reason": "TEXT",
    "disabled_at": "DATETIME",
    "reauth_requested_at": "DATETIME",
    "lifecycle_updated_at": "DATETIME",
    "lifecycle_reason": "TEXT",
    "login_attempt_count": "INTEGER NOT NULL DEFAULT 0",
    "auth_generation": "INTEGER NOT NULL DEFAULT 0",
    "device_model": "VARCHAR",
    "system_version": "VARCHAR",
    "app_version": "VARCHAR",
    "lang_code": "VARCHAR",
    "system_lang_code": "VARCHAR",
    "lang_pack": "VARCHAR",
    "timezone": "VARCHAR",
    "identity_created_at": "DATETIME",
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
    required_columns = {**ACCOUNT_PROXY_COLUMNS, **ACCOUNT_SESSION_COLUMNS}
    missing_columns = {
        name: ddl
        for name, ddl in required_columns.items()
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
                "auth_status = CASE "
                "WHEN session_connected = TRUE THEN 'active' "
                "ELSE 'unverified' END "
                "WHERE auth_status IS NULL OR auth_status = 'unverified'"
            )
        )
        connection.execute(
            text(
                "UPDATE advertising_accounts SET orchestration_state = CASE "
                "WHEN auth_status IN ('error', 'banned') THEN 'ERROR' "
                "WHEN session_connected = TRUE AND "
                "(proxy_enabled = FALSE OR proxy_status = 'working') THEN 'ACTIVE' "
                "WHEN session_connected = TRUE THEN 'DEGRADED' "
                "ELSE 'REAUTH_REQUIRED' END "
                "WHERE orchestration_state IS NULL "
                "OR orchestration_state = 'CREATED'"
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
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS proxy_endpoints ("
                "id INTEGER PRIMARY KEY, proxy_type VARCHAR NOT NULL, "
                "host VARCHAR NOT NULL, port INTEGER NOT NULL, "
                "username VARCHAR, password VARCHAR, "
                "enabled BOOLEAN NOT NULL DEFAULT TRUE, "
                "status VARCHAR NOT NULL DEFAULT 'unknown', "
                "latency_ms INTEGER, last_checked_at DATETIME, "
                "last_error TEXT, max_accounts INTEGER NOT NULL DEFAULT 10, "
                "created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_proxy_endpoints_status "
                "ON proxy_endpoints (status)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_proxy_endpoints_enabled "
                "ON proxy_endpoints (enabled)"
            )
        )
        proxy_columns = {
            column["name"]
            for column in inspect(connection).get_columns("proxy_endpoints")
        }
        for name, ddl in {
            "score": "INTEGER NOT NULL DEFAULT 100",
            "success_count": "INTEGER NOT NULL DEFAULT 0",
            "failure_count": "INTEGER NOT NULL DEFAULT 0",
            "disabled_until": "DATETIME",
        }.items():
            if name not in proxy_columns:
                connection.execute(
                    text(f"ALTER TABLE proxy_endpoints ADD COLUMN {name} {ddl}")
                )
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS autopilot_control_state ("
                "id INTEGER PRIMARY KEY, "
                "system_state VARCHAR NOT NULL DEFAULT 'HEALTHY', "
                "action_taken TEXT, reason TEXT, "
                "affected_accounts INTEGER NOT NULL DEFAULT 0, "
                "affected_proxies INTEGER NOT NULL DEFAULT 0, "
                "client_limit INTEGER NOT NULL DEFAULT 5, "
                "login_queue_paused BOOLEAN NOT NULL DEFAULT FALSE, "
                "proxy_pool_paused BOOLEAN NOT NULL DEFAULT FALSE, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_autopilot_control_state_system_state "
                "ON autopilot_control_state (system_state)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS campaigns ("
                "id INTEGER PRIMARY KEY, "
                "name VARCHAR NOT NULL, "
                "account_id INTEGER NOT NULL, "
                "template_id INTEGER, "
                "interval_minutes INTEGER NOT NULL DEFAULT 60, "
                "status VARCHAR NOT NULL DEFAULT 'active', "
                "schedule_enabled BOOLEAN NOT NULL DEFAULT TRUE, "
                "schedule_timezone VARCHAR NOT NULL DEFAULT 'Europe/Moscow', "
                "schedule_start_time VARCHAR, "
                "schedule_end_time VARCHAR, "
                "first_send_at DATETIME, "
                "created_at DATETIME, "
                "updated_at DATETIME, "
                "FOREIGN KEY(account_id) REFERENCES advertising_accounts(id), "
                "FOREIGN KEY(template_id) REFERENCES templates(id)"
                ")"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_campaigns_account_id "
                "ON campaigns (account_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_campaigns_template_id "
                "ON campaigns (template_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_campaigns_status "
                "ON campaigns (status)"
            )
        )
        campaign_columns = {
            column["name"]
            for column in inspect(connection).get_columns("campaigns")
        }
        if "first_send_at" not in campaign_columns:
            connection.execute(
                text("ALTER TABLE campaigns ADD COLUMN first_send_at DATETIME")
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_campaigns_first_send_at "
                "ON campaigns (first_send_at)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS campaign_chats ("
                "campaign_id INTEGER NOT NULL, "
                "chat_id INTEGER NOT NULL, "
                "PRIMARY KEY (campaign_id, chat_id), "
                "FOREIGN KEY(campaign_id) REFERENCES campaigns(id), "
                "FOREIGN KEY(chat_id) REFERENCES chats(id)"
                ")"
            )
        )
