from __future__ import annotations

from shared.alert_service import build_alert
from shared.config import AppConfig
from shared.email_service import AlertNotificationService, build_email_subscription, email_hash, severity_meets_threshold
from shared.table_repository import InMemoryTableRepository


class FakeSender:
    def __init__(self):
        self.sent = []

    def is_configured(self):
        return True

    def send_alert_email(self, to_email, alert):
        self.sent.append((to_email, alert["alertId"]))


def test_severity_threshold_excludes_low_alerts():
    assert severity_meets_threshold("medium", "medium")
    assert severity_meets_threshold("high", "medium")
    assert not severity_meets_threshold("low", "medium")


def test_alert_notification_sends_medium_and_high_to_subscribers_once():
    config = AppConfig.from_env(require_secrets=False)
    table = InMemoryTableRepository()
    table.upsert_email_subscription(build_email_subscription("owner@example.com"))
    sender = FakeSender()
    notifier = AlertNotificationService(table, config, sender)
    alert = build_alert("over_target", "2026-05-17", "CatA is over target.", "cat_a", "CatA")

    notifier.notify_alert(alert)
    notifier.notify_alert(alert)

    assert sender.sent == [("owner@example.com", alert["alertId"])]
    notification = table.get_alert_email_notification(alert["alertId"], email_hash("owner@example.com"))
    assert notification["status"] == "sent"


def test_alert_notification_records_missing_smtp_configuration():
    config = AppConfig.from_env(require_secrets=False)
    table = InMemoryTableRepository()
    table.upsert_email_subscription(build_email_subscription("owner@example.com"))
    notifier = AlertNotificationService(table, config)
    alert = build_alert("device_health_error", "2026-05-17", "Device health issue.")

    notifier.notify_alert(alert)

    notification = table.get_alert_email_notification(alert["alertId"], email_hash("owner@example.com"))
    assert notification["status"] == "email_not_configured"


def test_email_subscription_can_be_deactivated():
    table = InMemoryTableRepository()
    subscription = build_email_subscription("owner@example.com")
    table.upsert_email_subscription(subscription)

    subscription["status"] = "inactive"
    table.upsert_email_subscription(subscription)

    assert table.list_active_email_subscriptions() == []
    assert table.get_email_subscription(email_hash("owner@example.com"))["status"] == "inactive"


def test_backlog_notification_sends_only_open_medium_or_high_alerts_up_to_limit():
    config = AppConfig.from_env(require_secrets=False)
    table = InMemoryTableRepository()
    subscription = build_email_subscription("owner@example.com")
    table.upsert_email_subscription(subscription)
    sender = FakeSender()
    notifier = AlertNotificationService(table, config, sender)

    alerts = [
        build_alert("over_target", "2026-05-17", f"Medium alert {index}.", "cat_a", "CatA", suffix=f"m-{index}")
        for index in range(5)
    ]
    alerts.append(build_alert("under_target", "2026-05-17", "Low alert.", "cat_b", "CatB", suffix="low"))
    resolved = build_alert("device_health_error", "2026-05-17", "Resolved high alert.", suffix="resolved")
    resolved["status"] = "resolved"
    alerts.append(resolved)

    count = notifier.notify_subscription_backlog(subscription, alerts, max_alerts=4)

    assert count == 4
    assert len(sender.sent) == 4
    assert all(alert_id.startswith("alert-cat_a-") for _, alert_id in sender.sent)
