from sqlalchemy import inspect, text, column, table


SETTINGS_TABLE = "settings"
SETTINGS_COLUMNS = (
    "id",
    "smtp_email",
    "smtp_password",
    "receiver_email",
    "wechat_webhook_url",
    "wechat_msg_type",
    "schedule_time",
    "agent_api_key",
    "agent_base_url",
    "agent_model",
    "tickflow_api_key",
    "claude_model",
    "claude_api_key",
    "claude_auth_token",
    "claude_base_url",
)
DEPRECATED_SETTINGS_COLUMNS = {
    "total_capital",
    "risk_preference",
    "eastmoney_search_api",
    "eastmoney_quote_api",
    "eastmoney_headers",
    "eastmoney_timeout",
    "smtp_host",
    "smtp_port",
}
NEW_SETTINGS_COLUMNS_DEFAULTS = {
    "agent_api_key": "''",
    "agent_base_url": "''",
    "agent_model": "''",
    "tickflow_api_key": "''",
    "claude_model": "''",
    "claude_api_key": "''",
    "claude_auth_token": "''",
    "claude_base_url": "''",
    "wechat_webhook_url": "''",
    "wechat_msg_type": "'markdown'",
}


def migrate_settings_schema(engine):
    inspector = inspect(engine)
    if SETTINGS_TABLE not in inspector.get_table_names():
        return

    current_columns = {column["name"] for column in inspector.get_columns(SETTINGS_TABLE)}
    desired_columns = set(SETTINGS_COLUMNS)

    missing_columns = desired_columns - current_columns
    has_deprecated = bool(current_columns & DEPRECATED_SETTINGS_COLUMNS)

    if not missing_columns and not has_deprecated:
        return

    if not has_deprecated and missing_columns.issubset(set(NEW_SETTINGS_COLUMNS_DEFAULTS.keys())):
        with engine.begin() as conn:
            for col in missing_columns:
                default_clause = NEW_SETTINGS_COLUMNS_DEFAULTS[col]
                conn.execute(text(f"alter table settings add column {col} varchar default {default_clause}"))
        return

    with engine.begin() as conn:
        conn.execute(text("""
            create table if not exists settings_new (
                id integer primary key,
                smtp_email varchar default '',
                smtp_password varchar default '',
                receiver_email varchar default '',
                wechat_webhook_url varchar default '',
                wechat_msg_type varchar default 'markdown',
                schedule_time varchar default '15:35',
                agent_api_key varchar default '',
                agent_base_url varchar default '',
                agent_model varchar default '',
                tickflow_api_key varchar default '',
                claude_model varchar default '',
                claude_api_key varchar default '',
                claude_auth_token varchar default '',
                claude_base_url varchar default ''
            )
        """))

        select_columns = []
        for column in SETTINGS_COLUMNS:
            if column in current_columns:
                select_columns.append(column)
            elif column == "schedule_time":
                select_columns.append("'15:35' as schedule_time")
            elif column == "wechat_msg_type":
                select_columns.append("'markdown' as wechat_msg_type")
            else:
                select_columns.append(f"'' as {column}")

        conn.execute(text(f"""
            insert into settings_new ({", ".join(SETTINGS_COLUMNS)})
            select {", ".join(select_columns)}
            from settings
        """))
        conn.execute(text("drop table settings"))
        conn.execute(text("alter table settings_new rename to settings"))


WATCHLIST_TABLE = "watchlist"
WATCHLIST_COLUMNS = ("id", "stock_code", "market", "name", "is_active", "added_at")


def migrate_watchlist_stock_code(engine):
    inspector = inspect(engine)
    if WATCHLIST_TABLE not in inspector.get_table_names():
        return

    current_columns = {column["name"] for column in inspector.get_columns(WATCHLIST_TABLE)}
    if "stock_code" in current_columns:
        return

    with engine.begin() as conn:
        conn.execute(text("""
            create table if not exists watchlist_new (
                id integer primary key,
                stock_code varchar not null,
                market varchar not null,
                name varchar not null,
                is_active boolean default 1,
                added_at timestamp
            )
        """))

        conn.execute(text("""
            insert into watchlist_new (id, stock_code, market, name, is_active, added_at)
            select id, code, market, name, is_active, added_at
            from watchlist
        """))

        conn.execute(text("drop table watchlist"))
        conn.execute(text("alter table watchlist_new rename to watchlist"))


MAIL_DELIVERY_TABLE = "mail_delivery_record"


def migrate_mail_delivery_record_schema(engine):
    inspector = inspect(engine)
    if MAIL_DELIVERY_TABLE in inspector.get_table_names():
        return

    with engine.begin() as conn:
        conn.execute(text("""
            create table if not exists mail_delivery_record (
                id integer primary key,
                delivery_date date not null,
                report_date date not null,
                subject varchar default '',
                holding_codes varchar default '',
                holding_names varchar default '',
                status varchar default 'sent',
                created_at timestamp
            )
        """))
        conn.execute(text("""
            create index if not exists ix_mail_delivery_record_delivery_date
            on mail_delivery_record (delivery_date)
        """))


STOCK_REPORT_TABLE = "stock_report"


def migrate_stock_report_current_price(engine):
    inspector = inspect(engine)
    if STOCK_REPORT_TABLE not in inspector.get_table_names():
        return

    current_columns = {column["name"] for column in inspector.get_columns(STOCK_REPORT_TABLE)}
    if "current_price" in current_columns:
        return

    with engine.begin() as conn:
        conn.execute(text("alter table stock_report add column current_price float"))


NOTIFICATION_LOG_TABLE = "notification_log"
ANALYSIS_TASK_STATE_TABLE = "analysis_task_state"


def migrate_notification_log_schema(engine):
    inspector = inspect(engine)
    if NOTIFICATION_LOG_TABLE in inspector.get_table_names():
        return

    with engine.begin() as conn:
        conn.execute(text("""
            create table if not exists notification_log (
                id integer primary key,
                channel varchar not null,
                status varchar not null,
                subject varchar default '',
                message_preview varchar default '',
                error_message varchar default '',
                is_test boolean default 0,
                created_at timestamp
            )
        """))
        conn.execute(text("""
            create index if not exists ix_notification_log_channel
            on notification_log (channel)
        """))
        conn.execute(text("""
            create index if not exists ix_notification_log_status
            on notification_log (status)
        """))
        conn.execute(text("""
            create index if not exists ix_notification_log_created_at
            on notification_log (created_at)
        """))


def migrate_analysis_task_state_schema(engine):
    inspector = inspect(engine)
    if ANALYSIS_TASK_STATE_TABLE in inspector.get_table_names():
        return

    with engine.begin() as conn:
        conn.execute(text("""
            create table if not exists analysis_task_state (
                id integer primary key,
                stock_code varchar not null,
                analysis_date date not null,
                status varchar not null,
                status_message varchar default '',
                run_mode varchar default '',
                started_at timestamp,
                finished_at timestamp,
                updated_at timestamp not null
            )
        """))
        conn.execute(text("""
            create unique index if not exists uq_analysis_task_state_stock_code_analysis_date
            on analysis_task_state (stock_code, analysis_date)
        """))
        conn.execute(text("""
            create index if not exists ix_analysis_task_state_analysis_date
            on analysis_task_state (analysis_date)
        """))
        conn.execute(text("""
            create index if not exists ix_analysis_task_state_status
            on analysis_task_state (status)
        """))
