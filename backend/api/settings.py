import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from db.database import get_db
from db.models import Settings
from core.claude_settings import sync_claude_settings_file
from core.scheduler import reschedule_daily_report
from core.notify import send_email, send_wechat

router = APIRouter(tags=["settings"])


class SettingsIn(BaseModel):
    smtp_email: Optional[str] = None
    smtp_password: Optional[str] = None
    receiver_email: Optional[str] = None
    wechat_webhook_url: Optional[str] = None
    wechat_msg_type: Optional[str] = None
    schedule_time: Optional[str] = None
    agent_api_key: Optional[str] = None
    agent_base_url: Optional[str] = None
    agent_model: Optional[str] = None
    tickflow_api_key: Optional[str] = None
    claude_model: Optional[str] = None
    claude_api_key: Optional[str] = None
    claude_auth_token: Optional[str] = None
    claude_base_url: Optional[str] = None


def apply_tickflow_env_from_settings(settings_row: Settings) -> None:
    value = (getattr(settings_row, "tickflow_api_key", "") or "").strip()
    if value:
        os.environ["TICKFLOW_API_KEY"] = value
    else:
        os.environ.pop("TICKFLOW_API_KEY", None)


def apply_tickflow_env_value(value: Optional[str]) -> None:
    normalized = (value or "").strip()
    if normalized:
        os.environ["TICKFLOW_API_KEY"] = normalized
    else:
        os.environ.pop("TICKFLOW_API_KEY", None)


def get_or_create_settings(db: Session) -> Settings:
    s = db.query(Settings).first()
    if not s:
        s = Settings()
        db.add(s)
        db.commit()
        db.refresh(s)
    apply_tickflow_env_from_settings(s)
    return s


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    return get_or_create_settings(db)


@router.put("/settings")
def update_settings(data: SettingsIn, db: Session = Depends(get_db)):
    s = get_or_create_settings(db)
    updates = data.model_dump(exclude_none=True)
    for key, val in updates.items():
        setattr(s, key, val)
    db.commit()
    db.refresh(s)
    if "tickflow_api_key" in updates:
        apply_tickflow_env_value(updates.get("tickflow_api_key"))
    else:
        apply_tickflow_env_from_settings(s)
    sync_claude_settings_file(s)
    if "schedule_time" in updates:
        reschedule_daily_report(s.schedule_time)
    return s


@router.post("/settings/test-email")
def test_email(db: Session = Depends(get_db)):
    s = get_or_create_settings(db)
    ok, err = send_email(
        s,
        content="## 邮件测试\n\n这是一封来自股票助手的测试邮件，说明邮件推送配置正确。",
        subject="📧 股票助手 - 邮件推送测试",
        is_test=True,
    )
    if ok:
        return {"ok": True, "message": "测试邮件发送成功"}
    return {"ok": False, "message": err or "发送失败"}


@router.post("/settings/test-wechat")
def test_wechat(db: Session = Depends(get_db)):
    s = get_or_create_settings(db)
    ok, err = send_wechat(
        s,
        content="## 企业微信测试\n\n这是一条来自股票助手的测试消息，说明企业微信推送配置正确。",
        subject="企业微信推送测试",
        is_test=True,
    )
    if ok:
        return {"ok": True, "message": "测试消息发送成功"}
    return {"ok": False, "message": err or "发送失败"}
