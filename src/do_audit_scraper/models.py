from datetime import UTC, datetime

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    """One audit-log event, serialized as one NDJSON line (Wazuh decodes JSON natively)."""

    event_id: str  # DigitalOcean ULID, stable and unique
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    user: str | None = None
    user_email: str | None = None
    ip_address: str | None = None
    timestamp_utc: datetime
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = "digitalocean_audit"
