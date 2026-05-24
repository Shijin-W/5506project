from __future__ import annotations

import hashlib
import re
import smtplib
from email.message import EmailMessage

from .config import AppConfig
from .time_utils import now_utc_iso

try:
    from azure.communication.email import EmailClient
except ImportError:  # Allows local tests without the optional Azure SDK installed.
    EmailClient = None


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SEVERITY_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def validate_email(email: str) -> str:
    normalized = normalize_email(email)
    if not EMAIL_RE.match(normalized):
        raise ValueError("A valid email address is required")
    return normalized


def email_hash(email: str) -> str:
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()


def mask_email(email: str) -> str:
    normalized = normalize_email(email)
    local, _, domain = normalized.partition("@")
    if not local or not domain:
        return normalized
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}***@{domain}"


def severity_meets_threshold(severity: str, threshold: str = "medium") -> bool:
    return SEVERITY_RANK.get(str(severity).lower(), 2) >= SEVERITY_RANK.get(str(threshold).lower(), 2)


def build_email_subscription(email: str, min_severity: str = "medium") -> dict:
    normalized = validate_email(email)
    now = now_utc_iso()
    return {
        "PartitionKey": "EMAIL_SUBS",
        "RowKey": email_hash(normalized),
        "email": normalized,
        "emailHash": email_hash(normalized),
        "status": "active",
        "minSeverity": min_severity,
        "createdAtUtc": now,
        "updatedAtUtc": now,
    }


def build_alert_email_content(alert: dict) -> tuple[str, str]:
    severity = str(alert.get("severity", "medium")).upper()
    subject = f"[Smart Cat Feeder] {severity} alert"
    if alert.get("catName"):
        subject += f" for {alert['catName']}"

    body = "\n".join(
        [
            "Smart Multi-Cat Feeder alert",
            "",
            f"Severity: {severity}",
            f"Type: {alert.get('alertType', '-')}",
            f"Cat: {alert.get('catName') or alert.get('catId') or 'System'}",
            f"Message: {alert.get('message', '-')}",
            f"Detected UTC: {alert.get('createdAtUtc', '-')}",
            f"Alert ID: {alert.get('alertId', '-')}",
        ]
    )
    return subject, body


class AlertEmailSender:
    def __init__(self, config: AppConfig):
        self.config = config

    def is_configured(self) -> bool:
        return bool(
            (self.config.acs_connection_string and self.config.acs_sender_email)
            or (self.config.smtp_host and self.config.smtp_from_email)
        )

    def send_alert_email(self, to_email: str, alert: dict) -> None:
        if self.config.acs_connection_string and self.config.acs_sender_email:
            self._send_with_acs(to_email, alert)
            return
        self._send_with_smtp(to_email, alert)

    def _send_with_acs(self, to_email: str, alert: dict) -> None:
        if EmailClient is None:
            raise RuntimeError("azure-communication-email is not installed")
        subject, body = build_alert_email_content(alert)
        client = EmailClient.from_connection_string(self.config.acs_connection_string)
        poller = client.begin_send(
            {
                "senderAddress": self.config.acs_sender_email,
                "recipients": {
                    "to": [{"address": to_email}],
                },
                "content": {
                    "subject": subject,
                    "plainText": body,
                },
            }
        )
        poller.result()

    def _send_with_smtp(self, to_email: str, alert: dict) -> None:
        if not self.is_configured():
            raise RuntimeError("Email delivery is not configured")

        subject, body = build_alert_email_content(alert)
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.config.smtp_from_email
        message["To"] = to_email
        message.set_content(body)

        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
            if self.config.smtp_use_tls:
                smtp.starttls()
            if self.config.smtp_username:
                smtp.login(self.config.smtp_username, self.config.smtp_password)
            smtp.send_message(message)


class AlertNotificationService:
    def __init__(self, table_repo, config: AppConfig, sender: AlertEmailSender | None = None):
        self.table = table_repo
        self.config = config
        self.sender = sender or AlertEmailSender(config)

    def notify_alert(self, alert: dict) -> None:
        severity = str(alert.get("severity", "medium")).lower()
        if not severity_meets_threshold(severity, "medium"):
            return

        alert_id = alert.get("alertId")
        if not alert_id:
            return

        for subscription in self.table.list_active_email_subscriptions():
            min_severity = subscription.get("minSeverity", "medium")
            if not severity_meets_threshold(severity, min_severity):
                continue
            self._notify_subscription(alert, subscription)

    def notify_subscription_backlog(self, subscription: dict, alerts: list[dict], max_alerts: int = 4) -> int:
        sent_or_queued = 0

        for alert in alerts:
            if sent_or_queued >= max_alerts:
                break
            if alert.get("status") != "open":
                continue
            if not severity_meets_threshold(alert.get("severity", "medium"), subscription.get("minSeverity", "medium")):
                continue

            before = self.table.get_alert_email_notification(alert["alertId"], subscription["emailHash"])
            self._notify_subscription(alert, subscription)
            after = self.table.get_alert_email_notification(alert["alertId"], subscription["emailHash"])

            if after and (not before or before.get("status") != after.get("status")):
                sent_or_queued += 1

        return sent_or_queued

    def _notify_subscription(self, alert: dict, subscription: dict) -> None:
        alert_id = alert["alertId"]
        subscriber_hash = subscription["emailHash"]
        existing = self.table.get_alert_email_notification(alert_id, subscriber_hash)
        if existing and existing.get("status") == "sent":
            return

        now = now_utc_iso()
        notification = {
            "PartitionKey": alert_id,
            "RowKey": subscriber_hash,
            "alertId": alert_id,
            "emailHash": subscriber_hash,
            "email": subscription["email"],
            "severity": alert.get("severity", ""),
            "status": "pending",
            "createdAtUtc": existing.get("createdAtUtc", now) if existing else now,
            "updatedAtUtc": now,
        }

        try:
            self.sender.send_alert_email(subscription["email"], alert)
            notification["status"] = "sent"
            notification["sentAtUtc"] = now_utc_iso()
        except Exception as exc:
            notification["status"] = "email_not_configured" if not self.sender.is_configured() else "failed"
            notification["error"] = str(exc)[:500]

        self.table.upsert_alert_email_notification(notification)
