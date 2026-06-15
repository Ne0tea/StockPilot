from datetime import date, datetime
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api import dashboard
from db.models import Base, MailDeliveryRecord, NotificationLog


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_clear_notifications_hides_records_without_deleting_history():
    db = _session()
    db.add(
        MailDeliveryRecord(
            delivery_date=date(2026, 6, 14),
            report_date=date(2026, 6, 14),
            subject="每日推送",
            holding_names="平安银行",
            status="sent",
        )
    )
    db.add(
        NotificationLog(
            channel="email",
            status="failed",
            subject="推送失败",
            error_message="SMTP timeout",
            is_test=False,
            created_at=datetime(2026, 6, 14, 9, 30),
        )
    )
    db.commit()

    assert len(dashboard.get_delivery_records(db)) == 1
    assert len(dashboard.get_notifications(db)) == 1

    result = dashboard.clear_notifications(db)

    assert result == {"hidden_delivery_records": 1, "hidden_notification_logs": 1}
    assert dashboard.get_delivery_records(db) == []
    assert dashboard.get_notifications(db) == []
    assert db.query(MailDeliveryRecord).count() == 1
    assert db.query(NotificationLog).count() == 1
    assert db.query(MailDeliveryRecord).first().is_hidden is True
    assert db.query(NotificationLog).first().is_hidden is True
