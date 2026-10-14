import json
from pathlib import Path

from do_audit_scraper.parser import parse_events
from do_audit_scraper.storage import Store

FIXTURE = Path(__file__).parent / "fixtures" / "audit_response.json"


def _events():
    return parse_events(json.loads(FIXTURE.read_text()))


def test_parse_events():
    events = _events()
    actions = [e.action for e in events]
    assert actions == ["api_token.create", "firewall.created", "firewall.created"]
    assert events[0].ip_address == "203.0.113.10"
    assert events[0].user_email == "alice@example.com"
    assert events[0].timestamp_utc.isoformat() == "2026-10-13T11:23:26+00:00"


def test_identical_events_keep_distinct_ids():
    events = _events()
    assert len({e.event_id for e in events}) == 3


def test_store_dedup(tmp_path):
    events = _events()
    store = Store(tmp_path / "o.ndjson", tmp_path / "s.json", 100)
    assert store.append(events) == 3
    assert store.append(events) == 0
    store2 = Store(tmp_path / "o.ndjson", tmp_path / "s.json", 100)  # state survives restart
    assert store2.append(events) == 0
    assert len((tmp_path / "o.ndjson").read_text().splitlines()) == 3
