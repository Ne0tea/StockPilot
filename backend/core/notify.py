# -*- coding: utf-8 -*-
"""Adapter that wraps notification_sender's EmailSender / WechatSender.

Builds a minimal config namespace from DB Settings and persists every send
attempt (success or failure) to the NotificationLog table so the frontend
bell can surface delivery + failure history.
"""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

# notification_sender / formatters / data_provider live under backend/core,
# but use absolute imports of the form `from src.config import Config`.
# Make `src`, `data_provider`, and `notification_sender` directly importable
# by inserting backend/core onto sys.path.
_CORE_DIR = Path(__file__).resolve().parent
if str(_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_CORE_DIR))

from src.notification_sender.email_sender import EmailSender  # noqa: E402
from src.notification_sender.wechat_sender import WechatSender  # noqa: E402

from db.database import SessionLocal  # noqa: E402
from db.models import NotificationLog  # noqa: E402

logger = logging.getLogger(__name__)

_PREVIEW_MAX = 400
_ERROR_MAX = 1000


def _build_email_config(settings) -> SimpleNamespace:
    """Build a minimal config namespace consumed by EmailSender."""
    sender_email = (getattr(settings, "smtp_email", "") or "").strip()
    receiver_raw = (getattr(settings, "receiver_email", "") or "").strip()
    receivers: List[str] = [
        addr.strip()
        for addr in receiver_raw.replace(";", ",").split(",")
        if addr.strip()
    ]
    if not receivers and sender_email:
        receivers = [sender_email]
    return SimpleNamespace(
        email_sender=sender_email,
        email_password=(getattr(settings, "smtp_password", "") or "").strip(),
        email_receivers=receivers,
        email_sender_name="股票分析助手",
        stock_email_groups=[],
    )


def _build_wechat_config(settings) -> SimpleNamespace:
    """Build a minimal config namespace consumed by WechatSender."""
    return SimpleNamespace(
        wechat_webhook_url=(getattr(settings, "wechat_webhook_url", "") or "").strip(),
        wechat_max_bytes=4000,
        wechat_msg_type=(getattr(settings, "wechat_msg_type", "") or "markdown").strip() or "markdown",
        webhook_verify_ssl=True,
    )


def _truncate(value: str, limit: int) -> str:
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _record_log(
    *,
    channel: str,
    status: str,
    subject: str = "",
    message_preview: str = "",
    error_message: str = "",
    is_test: bool = False,
) -> None:
    """Persist a single send attempt to NotificationLog (best-effort)."""
    db = SessionLocal()
    try:
        db.add(
            NotificationLog(
                channel=channel,
                status=status,
                subject=_truncate(subject or "", 200),
                message_preview=_truncate(message_preview or "", _PREVIEW_MAX),
                error_message=_truncate(error_message or "", _ERROR_MAX),
                is_test=is_test,
            )
        )
        db.commit()
    except Exception:
        logger.exception("写入 NotificationLog 失败")
        db.rollback()
    finally:
        db.close()


def email_configured(settings) -> bool:
    return bool(
        (getattr(settings, "smtp_email", "") or "").strip()
        and (getattr(settings, "smtp_password", "") or "").strip()
        and (getattr(settings, "receiver_email", "") or "").strip()
    )


def wechat_configured(settings) -> bool:
    return bool((getattr(settings, "wechat_webhook_url", "") or "").strip())


def send_email(
    settings,
    *,
    content: str,
    subject: str,
    receivers: Optional[List[str]] = None,
    is_test: bool = False,
) -> tuple[bool, Optional[str]]:
    """Send an email via EmailSender. Returns (ok, error_message)."""
    if not email_configured(settings):
        msg = "邮件未配置（缺少发件邮箱、授权码或收件邮箱）"
        _record_log(
            channel="email",
            status="test_failed" if is_test else "failed",
            subject=subject,
            message_preview=content,
            error_message=msg,
            is_test=is_test,
        )
        return False, msg

    cfg = _build_email_config(settings)
    sender = EmailSender(cfg)
    try:
        ok = sender.send_to_email(content, subject=subject, receivers=receivers)
    except Exception as exc:
        err = f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc(limit=4)}"
        _record_log(
            channel="email",
            status="test_failed" if is_test else "failed",
            subject=subject,
            message_preview=content,
            error_message=err,
            is_test=is_test,
        )
        return False, str(exc)

    if ok:
        _record_log(
            channel="email",
            status="test_sent" if is_test else "sent",
            subject=subject,
            message_preview=content,
            is_test=is_test,
        )
        return True, None

    err = "邮件发送失败，请检查 SMTP 配置或网络（详情见后端日志）"
    _record_log(
        channel="email",
        status="test_failed" if is_test else "failed",
        subject=subject,
        message_preview=content,
        error_message=err,
        is_test=is_test,
    )
    return False, err


def send_wechat(
    settings,
    *,
    content: str,
    subject: str = "",
    is_test: bool = False,
) -> tuple[bool, Optional[str]]:
    """Send a wechat message via WechatSender. Returns (ok, error_message)."""
    if not wechat_configured(settings):
        msg = "企业微信 Webhook 未配置"
        _record_log(
            channel="wechat",
            status="test_failed" if is_test else "failed",
            subject=subject,
            message_preview=content,
            error_message=msg,
            is_test=is_test,
        )
        return False, msg

    cfg = _build_wechat_config(settings)
    sender = WechatSender(cfg)
    try:
        ok = sender.send_to_wechat(content)
    except Exception as exc:
        err = f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc(limit=4)}"
        _record_log(
            channel="wechat",
            status="test_failed" if is_test else "failed",
            subject=subject,
            message_preview=content,
            error_message=err,
            is_test=is_test,
        )
        return False, str(exc)

    if ok:
        _record_log(
            channel="wechat",
            status="test_sent" if is_test else "sent",
            subject=subject,
            message_preview=content,
            is_test=is_test,
        )
        return True, None

    err = "企业微信发送失败，请检查 Webhook 或消息内容（详情见后端日志）"
    _record_log(
        channel="wechat",
        status="test_failed" if is_test else "failed",
        subject=subject,
        message_preview=content,
        error_message=err,
        is_test=is_test,
    )
    return False, err


def _append_missing_section(lines: list[str], title: str, missing_items: list[dict]) -> None:
    lines.append(title)
    lines.append("")
    if missing_items:
        for item in missing_items:
            name = item.get("name") or "未知"
            code = item.get("code") or "—"
            lines.append(f"- {name}({code})：今日未生成分析结果，状态为缺失/未完成")
    else:
        lines.append("_无缺失项_")
    lines.append("")


def build_daily_report_markdown(
    holding_recs: list,
    watchlist_signals: list,
    *,
    holding_missing: Optional[list[dict]] = None,
    watchlist_missing: Optional[list[dict]] = None,
) -> str:
    """Render the daily report as Markdown (consumed by both email and wechat)."""
    lines: list[str] = []
    holding_missing = holding_missing or []
    watchlist_missing = watchlist_missing or []
    lines.append("## 📌 持仓股操作建议")
    lines.append("")
    if holding_recs:
        lines.append("| 股票 | 评分 | 操作 | 原因 | 目标价 | 止损价 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in holding_recs:
            name = r.get("name") or "未知"
            code = r.get("code") or "—"
            score = r.get("score_total")
            score_str = f"{score}/10" if score is not None else "—"
            action = r.get("action") or "—"
            reason = (r.get("reason") or "—").replace("|", "／").replace("\n", " ")
            target = r.get("target_price") if r.get("target_price") is not None else "—"
            stop = r.get("stop_loss_price") if r.get("stop_loss_price") is not None else "—"
            lines.append(f"| {name}({code}) | {score_str} | {action} | {reason} | {target} | {stop} |")
    else:
        lines.append("_暂无持仓股建议_")
    lines.append("")
    lines.append("## 👀 自选股关注信号")
    lines.append("")
    if watchlist_signals:
        lines.append("| 股票 | 评分 | 评级 | 建仓价 |")
        lines.append("| --- | --- | --- | --- |")
        for s in watchlist_signals:
            name = s.get("name") or "未知"
            code = s.get("code") or "—"
            score = s.get("score_total")
            score_str = f"{score}/10" if score is not None else "—"
            recommendation = s.get("recommendation") or "—"
            entry = s.get("entry_price") if s.get("entry_price") is not None else "—"
            lines.append(f"| {name}({code}) | {score_str} | {recommendation} | {entry} |")
    else:
        lines.append("_暂无自选股信号_")
    lines.append("")
    _append_missing_section(lines, "## ⚠️ 持仓股缺失/未完成", holding_missing)
    _append_missing_section(lines, "## ⚠️ 自选股缺失/未完成", watchlist_missing)
    return "\n".join(lines)
