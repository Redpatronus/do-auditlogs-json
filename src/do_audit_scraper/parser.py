"""GraphQL `GetAuditActions` payload -> AuditEvent (pure, easy to unit test)."""

from datetime import datetime

from .models import AuditEvent


def parse_events(payload: dict) -> list[AuditEvent]:
    items = payload["data"]["GetAuditActions"]["audit_actions"] or []
    events: list[AuditEvent] = []
    for it in items:
        actor = it.get("actor") or {}
        events.append(
            AuditEvent(
                event_id=it["ulid"],
                action=it["name"],
                resource_type=it.get("resource_type"),
                resource_id=it.get("resource_id"),
                user=actor.get("name"),
                user_email=actor.get("email"),
                ip_address=it.get("actor_ip"),
                timestamp_utc=datetime.fromisoformat(it["created_at"]),
            )
        )
    return events
