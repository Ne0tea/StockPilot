from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Date, Index, UniqueConstraint
from datetime import datetime
from .database import Base

class Watchlist(Base):
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True)
    stock_code = Column(String, nullable=False)
    market = Column(String, nullable=False)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.now)

class StockReport(Base):
    __tablename__ = "stock_report"
    id = Column(Integer, primary_key=True)
    stock_code = Column(String, nullable=False, index=True)
    date = Column(Date, nullable=False)
    score_total = Column(Float)
    score_fundamental = Column(Float)
    score_news = Column(Float)
    score_capital = Column(Float)
    score_technical = Column(Float)
    recommendation = Column(String)
    action = Column(String)
    reason = Column(String)
    target_price = Column(Float)
    stop_loss_price = Column(Float)
    entry_price = Column(Float)
    current_price = Column(Float)
    report_file_path = Column(String)
    report_time = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)


class AnalysisTaskState(Base):
    __tablename__ = "analysis_task_state"
    __table_args__ = (
        UniqueConstraint("stock_code", "analysis_date", name="uq_analysis_task_state_stock_code_analysis_date"),
        Index("ix_analysis_task_state_analysis_date", "analysis_date"),
        Index("ix_analysis_task_state_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    stock_code = Column(String, nullable=False, index=True)
    analysis_date = Column(Date, nullable=False)
    status = Column(String, nullable=False)
    status_message = Column(String, default="")
    run_mode = Column(String, default="")
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now, nullable=False)

class Portfolio(Base):
    __tablename__ = "portfolio"
    id = Column(Integer, primary_key=True)
    stock_code = Column(String, nullable=False)
    stock_name = Column(String)
    shares = Column(Integer, nullable=False)
    cost_price = Column(Float, nullable=False)
    buy_date = Column(Date, nullable=False)
    status = Column(String, default="holding")

class TradeLog(Base):
    __tablename__ = "trade_log"
    id = Column(Integer, primary_key=True)
    stock_code = Column(String, nullable=False)
    stock_name = Column(String)
    action = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    shares = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    smtp_email = Column(String, default="")
    smtp_password = Column(String, default="")
    receiver_email = Column(String, default="")
    wechat_webhook_url = Column(String, default="")
    wechat_msg_type = Column(String, default="markdown")
    schedule_time = Column(String, default="15:35")
    agent_api_key = Column(String, default="")
    agent_base_url = Column(String, default="")
    agent_model = Column(String, default="")
    tickflow_api_key = Column(String, default="")
    claude_model = Column(String, default="")
    claude_api_key = Column(String, default="")
    claude_auth_token = Column(String, default="")
    claude_base_url = Column(String, default="")


class MailDeliveryRecord(Base):
    __tablename__ = "mail_delivery_record"
    id = Column(Integer, primary_key=True)
    delivery_date = Column(Date, nullable=False, index=True)
    report_date = Column(Date, nullable=False)
    subject = Column(String, default="")
    holding_codes = Column(String, default="")
    holding_names = Column(String, default="")
    status = Column(String, default="sent")
    is_hidden = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class NotificationLog(Base):
    __tablename__ = "notification_log"
    id = Column(Integer, primary_key=True)
    channel = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, index=True)
    subject = Column(String, default="")
    message_preview = Column(String, default="")
    error_message = Column(String, default="")
    is_test = Column(Boolean, default=False)
    is_hidden = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.now, index=True)
