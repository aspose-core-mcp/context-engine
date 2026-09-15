"""SMTP notification abstraction and in-memory adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Protocol

from adcs.ops.critical_events import CriticalEventRecord


class NotificationStatus(StrEnum):
    """Notification dispatch status."""

    SENT = "sent"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SmtpNotificationDispatch:
    """One SMTP notification dispatch record."""

    notification_id: str
    event_id: str
    channel: str
    recipient_group: str
    status: NotificationStatus
    error_message: str | None
    sent_at: datetime


@dataclass(frozen=True, slots=True)
class SmtpMessage:
    """One SMTP message payload."""

    subject: str
    body: str
    recipient_group: str


class SmtpTransport(Protocol):
    """Contract for SMTP transport adapters."""

    def send_email(self, *, subject: str, body: str, recipient_group: str) -> None:
        """Send an SMTP message."""


class InMemorySmtpTransport:
    """In-memory SMTP transport for local runs and tests."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._messages: list[SmtpMessage] = []

    def send_email(self, *, subject: str, body: str, recipient_group: str) -> None:
        with self._lock:
            self._messages.append(
                SmtpMessage(subject=subject, body=body, recipient_group=recipient_group)
            )

    def list_messages(self, *, limit: int = 20) -> tuple[SmtpMessage, ...]:
        """List recent SMTP messages in reverse chronological order."""
        if limit < 1:
            return ()
        with self._lock:
            return tuple(reversed(self._messages[-limit:]))


class NotificationService:
    """Notification service that fans out critical events to SMTP."""

    def __init__(
        self,
        *,
        smtp_transport: SmtpTransport | None = None,
        recipient_group: str = "all_admins",
    ) -> None:
        self._smtp_transport = smtp_transport or InMemorySmtpTransport()
        self._recipient_group = recipient_group
        self._lock = Lock()
        self._counter = 0
        self._dispatches: list[SmtpNotificationDispatch] = []

    def notify_event(self, event: CriticalEventRecord) -> SmtpNotificationDispatch:
        """Send one critical-event notification via SMTP abstraction."""
        subject = f"[ADCS][{event.severity.value}] {event.event_type.value}"
        body = f"{event.message}\n\nDetails: {event.details}"
        error_message: str | None = None
        status = NotificationStatus.SENT
        try:
            self._smtp_transport.send_email(
                subject=subject,
                body=body,
                recipient_group=self._recipient_group,
            )
        except Exception as exc:  # pragma: no cover - defensive adapter boundary
            status = NotificationStatus.FAILED
            error_message = str(exc)

        with self._lock:
            self._counter += 1
            notification_id = f"smtp-{self._counter:08d}"
            dispatch = SmtpNotificationDispatch(
                notification_id=notification_id,
                event_id=event.event_id,
                channel="smtp",
                recipient_group=self._recipient_group,
                status=status,
                error_message=error_message,
                sent_at=datetime.now(tz=UTC),
            )
            self._dispatches.append(dispatch)
        return dispatch

    def list_dispatches(self, *, limit: int = 20) -> tuple[SmtpNotificationDispatch, ...]:
        """List recent SMTP dispatches in reverse chronological order."""
        if limit < 1:
            return ()
        with self._lock:
            return tuple(reversed(self._dispatches[-limit:]))
